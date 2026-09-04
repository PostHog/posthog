#!/usr/bin/env node

import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const LOCK_PATH = join(here, "canvas-modules.lock.json");
const OUT_DIR = join(root, "apps/code/resources/canvas-modules");

const ESM = "https://esm.sh";
const JSDELIVR = "https://cdn.jsdelivr.net";
const MODULE_LOCK = JSON.parse(await readFile(LOCK_PATH, "utf8"));
const { imports: IMPORTS, runtime: RUNTIME } = MODULE_LOCK;

const HOSTS = { esm: ESM, cdn: JSDELIVR };

const SPECIFIER =
  /(?:\bfrom\s*|\bimport\s*|\bexport\s*\*\s*from\s*)["']([^"'\n]+)["']/g;
const CSS_REFERENCE =
  /@import\s+["']([^"'\n]+)["']|url\(\s*["']?([^"')\n]+)["']?\s*\)/g;

const update = process.argv.includes("--update");
const concurrency = 16;

async function main() {
  if (MODULE_LOCK.version !== 2)
    throw new Error("Unsupported canvas module lock version");
  if (update) {
    await crawlAndWriteLock();
    return;
  }
  await restoreFromLock({
    files: Object.fromEntries(
      Object.entries(MODULE_LOCK.files).flatMap(([type, files]) =>
        Object.entries(files).map(([key, sha256]) => [key, { sha256, type }]),
      ),
    ),
  });
}

async function crawlAndWriteLock() {
  const found = new Map();
  const pinned = new Set([
    ...Object.values(IMPORTS),
    RUNTIME.babel,
    RUNTIME.tailwind,
    ...RUNTIME.styles,
  ]);
  const queue = [...pinned];
  const seen = new Set(queue);

  while (queue.length > 0) {
    const batch = queue.splice(0, concurrency);
    const results = await Promise.all(
      batch.map((url) => load(url, null, pinned.has(url))),
    );
    for (const result of results) {
      if (!result) continue;
      found.set(result.url, result);
      for (const next of result.references) {
        if (seen.has(next)) continue;
        seen.add(next);
        queue.push(next);
      }
    }
  }

  const files = {};
  const grouped = {};
  for (const [url, entry] of [...found].sort(([a], [b]) => (a < b ? -1 : 1))) {
    grouped[entry.type] ??= {};
    grouped[entry.type][keyOf(url)] = entry.sha256;
    files[keyOf(url)] = {
      sha256: entry.sha256,
      type: entry.type,
    };
  }
  await writeFile(
    LOCK_PATH,
    `${JSON.stringify({ version: 2, imports: IMPORTS, runtime: RUNTIME, files: grouped }, null, 2)}\n`,
  );
  await writeResources(found, files);
  const total = [...found.values()].reduce((sum, e) => sum + e.body.length, 0);
  console.log(
    `Locked ${found.size} files (${(total / 1e6).toFixed(1)} MB). Review the lock before you commit it.`,
  );
}

async function restoreFromLock(lock) {
  await mkdir(join(OUT_DIR, "blobs"), { recursive: true });
  let fetched = 0;
  const entries = Object.entries(lock.files);
  for (let at = 0; at < entries.length; at += concurrency) {
    await Promise.all(
      entries.slice(at, at + concurrency).map(async ([key, entry]) => {
        const path = join(OUT_DIR, "blobs", `${entry.sha256}.bin`);
        if (await hasDigest(path, entry.sha256)) return;
        const result = await load(urlOf(key), lock, true);
        await writeFile(path, result.body);
        fetched += 1;
      }),
    );
  }
  await writeFile(
    join(OUT_DIR, "manifest.json"),
    `${JSON.stringify({ version: 1, files: lock.files }, null, 2)}\n`,
  );
  console.log(
    fetched === 0
      ? `All ${entries.length} locked files are already in place.`
      : `Fetched ${fetched} of ${entries.length} locked files; every byte matches the lock.`,
  );
}

async function hasDigest(path, sha256) {
  if (!existsSync(path)) return false;
  const body = await readFile(path);
  return createHash("sha256").update(body).digest("hex") === sha256;
}

async function load(url, lock, required) {
  const expected = lock?.files?.[keyOf(url)];
  if (!expected && lock) {
    if (!required) return null;
    throw new Error(
      `${url} is not in the lock. Run "node scripts/fetch-canvas-modules.mjs --update" and review the change.`,
    );
  }
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) {
    if (!required && res.status === 404) return null;
    throw new Error(`${res.status} for ${url}`);
  }
  const body = Buffer.from(await res.arrayBuffer());
  const sha256 = createHash("sha256").update(body).digest("hex");
  if (expected && expected.sha256 !== sha256) {
    throw new Error(
      `${url} changed upstream.\n  locked ${expected.sha256}\n  served ${sha256}\nRun with --update and review the change before you accept it.`,
    );
  }
  const type = (res.headers.get("content-type") ?? "").split(";")[0].trim();
  return { url, sha256, type, body, references: referencesOf(body, url, type) };
}

function referencesOf(body, url, type) {
  const text = body.toString("utf8");
  const specifiers = [];
  if (type.includes("javascript")) {
    for (const match of text.matchAll(SPECIFIER)) specifiers.push(match[1]);
  } else if (type.includes("css")) {
    for (const match of text.matchAll(CSS_REFERENCE)) {
      specifiers.push(match[1] ?? match[2]);
    }
  }
  const out = [];
  for (const specifier of specifiers) {
    const resolved = resolve(specifier, url);
    if (resolved) out.push(resolved);
  }
  return out;
}

function resolve(specifier, base) {
  if (!specifier || specifier.startsWith("data:")) return null;
  const bare = !/^[./]/.test(specifier) && !/^https?:/.test(specifier);
  if (bare) return IMPORTS[specifier] ?? null;
  let absolute;
  try {
    absolute = new URL(specifier, base).href;
  } catch {
    return null;
  }
  return hostKeyOf(absolute) ? absolute : null;
}

function hostKeyOf(url) {
  for (const [key, host] of Object.entries(HOSTS)) {
    if (url.startsWith(`${host}/`)) return key;
  }
  return null;
}

function keyOf(url) {
  const parsed = new URL(url);
  return `${hostKeyOf(url)}|${parsed.pathname}${parsed.search}`;
}

function urlOf(key) {
  const separator = key.indexOf("|");
  const host = HOSTS[key.slice(0, separator)];
  if (!host) throw new Error(`Unknown module host: ${key}`);
  return host + key.slice(separator + 1);
}

async function writeResources(found, files) {
  await rm(OUT_DIR, { recursive: true, force: true });
  await mkdir(join(OUT_DIR, "blobs"), { recursive: true });
  for (const entry of found.values()) {
    await writeFile(join(OUT_DIR, "blobs", `${entry.sha256}.bin`), entry.body);
  }
  await writeFile(
    join(OUT_DIR, "manifest.json"),
    `${JSON.stringify({ version: 1, files }, null, 2)}\n`,
  );
}

main().catch((error) => {
  console.error(`\ncanvas modules: ${error.message}\n`);
  process.exit(1);
});
