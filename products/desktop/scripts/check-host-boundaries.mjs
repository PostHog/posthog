#!/usr/bin/env node
import { execSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const ALLOWLIST = join(ROOT, "scripts", "host-boundary-allowlist.json");
const SCAN_ROOT = "apps/code/src";

const USAGE = `check-host-boundaries — enforce that apps/code stays a thin Electron host.

  node scripts/check-host-boundaries.mjs           verify: fail on any violation not in the allowlist
  node scripts/check-host-boundaries.mjs --init     (re)generate the baseline allowlist from current violations
  node scripts/check-host-boundaries.mjs --prune     drop allowlist entries that no longer violate (after evacuating)

The allowlist length is the number of files still trapped in apps/code. Goal: 0.`;

const RULES = [
  {
    id: "injectable-outside-host",
    why: "Business services belong in packages/*. apps/code may only declare @injectable in platform-adapters or di.",
    test: (path, src) =>
      /@injectable\s*\(/.test(src) &&
      !path.includes("/platform-adapters/") &&
      !path.includes("/di/"),
  },
  {
    id: "feature-ui-in-host",
    why: "Renderer feature UI (components/hooks/stories) is portable and belongs in @posthog/ui.",
    test: (path) =>
      path.includes("/renderer/features/") && path.endsWith(".tsx"),
  },
  {
    id: "cloud-client-in-renderer",
    why: "Cloud-API logic belongs in packages/core, not a renderer adapter. The host only carries transport.",
    test: (path, src) =>
      path.includes("/renderer/") &&
      (/from\s+["']@posthog\/api-client/.test(src) ||
        /getAuthenticatedClient\s*\(/.test(src)),
  },
  {
    id: "router-with-logic",
    why: "tRPC router bodies with real logic belong in @posthog/host-router. apps/code routers aggregate/delegate only.",
    test: (path, src) =>
      path.includes("/main/trpc/routers/") &&
      (/\bfetch\s*\(/.test(src) ||
        /https?:\/\//.test(src.replace(/\/\/.*$/gm, ""))),
  },
];

function listFiles() {
  const out = execSync(
    `git -C "${ROOT}" ls-files "${SCAN_ROOT}/**/*.ts" "${SCAN_ROOT}/**/*.tsx"`,
    { encoding: "utf8" },
  );
  return out
    .split("\n")
    .map((f) => f.trim())
    .filter(Boolean)
    .filter((f) => !f.endsWith(".d.ts") && !f.includes("/generated"));
}

function findViolations() {
  const violations = {};
  for (const path of listFiles()) {
    let src;
    try {
      src = readFileSync(join(ROOT, path), "utf8");
    } catch {
      continue;
    }
    const hit = RULES.filter((r) => r.test(path, src)).map((r) => r.id);
    if (hit.length) violations[path] = hit;
  }
  return violations;
}

function loadAllowlist() {
  if (!existsSync(ALLOWLIST)) return {};
  return JSON.parse(readFileSync(ALLOWLIST, "utf8")).files ?? {};
}

function saveAllowlist(files) {
  const sorted = Object.fromEntries(
    Object.keys(files)
      .sort()
      .map((k) => [k, files[k]]),
  );
  writeFileSync(
    ALLOWLIST,
    `${JSON.stringify({ note: "Files still trapped in apps/code. Remove entries as you evacuate. Goal: empty.", files: sorted }, null, 2)}\n`,
  );
}

const mode = process.argv[2];
if (mode === "--help" || mode === "-h") {
  console.log(USAGE);
  process.exit(0);
}

const current = findViolations();
const allow = loadAllowlist();

if (mode === "--init") {
  saveAllowlist(current);
  console.log(
    `Baseline written: ${Object.keys(current).length} trapped files.`,
  );
  process.exit(0);
}

if (mode === "--prune") {
  const kept = {};
  for (const f of Object.keys(allow)) if (current[f]) kept[f] = current[f];
  saveAllowlist(kept);
  console.log(
    `Pruned. ${Object.keys(allow).length - Object.keys(kept).length} evacuated, ${Object.keys(kept).length} remaining.`,
  );
  process.exit(0);
}

const fresh = Object.keys(current).filter((f) => !allow[f]);
const evacuated = Object.keys(allow).filter((f) => !current[f]);

if (evacuated.length) {
  console.log(
    `\n✓ ${evacuated.length} file(s) evacuated since baseline — run --prune to shrink the allowlist:`,
  );
  for (const f of evacuated) console.log(`    ${f}`);
}

if (fresh.length) {
  console.error(
    `\n✗ ${fresh.length} NEW host-boundary violation(s) — apps/code must stay a thin Electron host:\n`,
  );
  for (const f of fresh) {
    for (const id of current[f]) {
      const rule = RULES.find((r) => r.id === id);
      console.error(`  ${f}\n    [${id}] ${rule.why}`);
    }
  }
  console.error(
    `\nMove the logic to a package, or if this is a legitimate host file, justify it in review and add to scripts/host-boundary-allowlist.json.`,
  );
  process.exit(1);
}

console.log(
  `\n✓ No new violations. ${Object.keys(allow).length} file(s) still trapped (baseline). Goal: 0.`,
);
process.exit(0);
