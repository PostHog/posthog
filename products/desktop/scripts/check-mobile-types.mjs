#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const BASELINE = join(ROOT, "scripts", "mobile-type-baseline.json");
const MOBILE = join(ROOT, "apps", "mobile");

const USAGE = `check-mobile-types — typecheck apps/mobile, failing only on errors that are not already baselined.

  node scripts/check-mobile-types.mjs           verify: fail on any error not in the baseline
  node scripts/check-mobile-types.mjs --init     (re)generate the baseline from current errors
  node scripts/check-mobile-types.mjs --prune    drop baseline entries that no longer error (after fixing)

apps/mobile had no typecheck at all, so a breaking change to a shared package
(a new method on a platform interface, a renamed export) only surfaced when
someone opened the file. Metro strips types, so nothing else caught it. The
baseline grandfathers the errors that already existed so that gap could be
closed today; its length is the cleanup still owed. Goal: 0.`;

const ERROR_LINE = /^(\S.*?)\((\d+),(\d+)\): error (TS\d+): (.*)$/;
const ABSOLUTE_PATH = /\/\S*\/(node_modules\/\S*)/g;

/**
 * Some messages quote a resolved absolute path (TS7016 names the JS file it
 * could not find types for). The path differs between a laptop and CI, so a
 * baseline written on one machine would not match on the other.
 */
function normalizeMessage(message) {
  return message.replaceAll(ROOT, "<desktop>").replace(ABSOLUTE_PATH, "$1");
}

/**
 * Error identity is file + code + message, without line/column, so unrelated
 * edits above an error don't churn the baseline. The cost: swapping one
 * baselined error for an identical one elsewhere in the same file keeps the
 * count level and passes. Keying on lines would trade that narrow hole for a
 * baseline that needs rewriting on every edit, which is the worse deal.
 */
function runTsc() {
  const result = spawnSync(
    "pnpm",
    ["exec", "tsc", "--noEmit", "--pretty", "false"],
    {
      cwd: MOBILE,
      encoding: "utf8",
    },
  );
  const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;
  const errors = {};
  let parsed = 0;

  for (const line of output.split("\n")) {
    const match = ERROR_LINE.exec(line);
    if (!match) continue;
    const [, file, , , code, message] = match;
    const key = `${code} ${normalizeMessage(message)}`;
    errors[file] ??= {};
    errors[file][key] = (errors[file][key] ?? 0) + 1;
    parsed += 1;
  }

  // tsc exits non-zero for a broken config or a missing compiler too, and that
  // must not read as "no errors found".
  if (result.status !== 0 && parsed === 0) {
    console.error(`\n✗ tsc failed without reporting type errors:\n\n${output}`);
    process.exit(1);
  }

  return errors;
}

function loadBaseline() {
  if (!existsSync(BASELINE)) return {};
  return JSON.parse(readFileSync(BASELINE, "utf8")).files ?? {};
}

function saveBaseline(files) {
  const sorted = Object.fromEntries(
    Object.keys(files)
      .filter((file) => Object.keys(files[file]).length)
      .sort()
      .map((file) => [
        file,
        Object.fromEntries(
          Object.keys(files[file])
            .sort()
            .map((message) => [message, files[file][message]]),
        ),
      ]),
  );
  writeFileSync(
    BASELINE,
    `${JSON.stringify(
      {
        note: "Pre-existing apps/mobile type errors, counted per file and message. Remove entries as you fix them. Goal: empty.",
        files: sorted,
      },
      null,
      2,
    )}\n`,
  );
}

function count(files) {
  return Object.values(files).reduce(
    (total, byKey) =>
      total + Object.values(byKey).reduce((sum, n) => sum + n, 0),
    0,
  );
}

const mode = process.argv[2];
if (mode === "--help" || mode === "-h") {
  console.log(USAGE);
  process.exit(0);
}

const current = runTsc();
const baseline = loadBaseline();

if (mode === "--init") {
  saveBaseline(current);
  console.log(`Baseline written: ${count(current)} known error(s).`);
  process.exit(0);
}

if (mode === "--prune") {
  const kept = {};
  for (const [file, byKey] of Object.entries(baseline)) {
    for (const [key, allowed] of Object.entries(byKey)) {
      const still = current[file]?.[key] ?? 0;
      if (!still) continue;
      kept[file] ??= {};
      kept[file][key] = Math.min(allowed, still);
    }
  }
  saveBaseline(kept);
  console.log(
    `Pruned. ${count(baseline) - count(kept)} fixed, ${count(kept)} remaining.`,
  );
  process.exit(0);
}

const fresh = [];
let fixed = 0;

for (const [file, byKey] of Object.entries(current)) {
  for (const [key, seen] of Object.entries(byKey)) {
    const allowed = baseline[file]?.[key] ?? 0;
    if (seen > allowed) fresh.push({ file, key, extra: seen - allowed });
  }
}

for (const [file, byKey] of Object.entries(baseline)) {
  for (const [key, allowed] of Object.entries(byKey)) {
    fixed += Math.max(0, allowed - (current[file]?.[key] ?? 0));
  }
}

if (fixed) {
  console.log(
    `\n✓ ${fixed} baselined error(s) fixed since the baseline — run --prune to shrink it.`,
  );
}

if (fresh.length) {
  console.error(`\n✗ ${fresh.length} NEW type error(s) in apps/mobile:\n`);
  for (const { file, key, extra } of fresh) {
    console.error(`  ${file}\n    ${key}${extra > 1 ? ` (×${extra})` : ""}`);
  }
  console.error(
    `\nFix them, or if this is a deliberate widening of an existing problem, justify it in review and rerun with --init.`,
  );
  process.exit(1);
}

console.log(
  `\n✓ No new type errors. ${count(baseline)} baselined error(s) remaining. Goal: 0.`,
);
process.exit(0);
