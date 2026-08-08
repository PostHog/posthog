#!/usr/bin/env node
// Benchmark of the RTK rewrite policy: candidate (working tree) vs baseline
// (main's policy, materialized via `git show`) vs raw, on a fixed command
// corpus against this repo's own files. Both arms apply the REAL
// `rewriteBashForRtk` (imported via tsx), so policy drift between bench and
// production is impossible, and the reported delta is candidate-vs-baseline —
// the net policy gain — not candidate-vs-raw.
//
// Every row is fidelity-gated: exit-status parity with raw, output-presence
// parity, and per-row fact checks (ls: every filename survives; grep/rg/find:
// the exact uncapped totals survive in the summary header, since rtk
// truncates shown results by design). A candidate-only failure fails the run —
// a rewrite that errors into empty output registers as a REGRESSION, never as
// savings; a baseline-only failure is a main bug the candidate fixed.
//
// Token figures are bytes/4, a size heuristic comparable to `rtk gain` — NOT
// provider tokenizer counts, and this measures command output only (no prompt
// guidance, retries, or session-level effects).
//
// Usage: node scripts/rtk-bench.mjs [--json]

import { execFileSync, spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const RTK_MODULE_DIR = "packages/agent/src/adapters/claude/session";

const lines = (s) => s.split("\n").filter(Boolean);
// rtk's search/list filters are lossy by design past their result caps but
// must report accurate uncapped totals ("924 matches in 209 files", "229F
// 23D") so truncation stays discoverable. The facts below encode exactly that
// contract; completeness is asserted only where rtk is complete (ls).
const MATCH_HEADER = /\d+ matches in \d+ files/;
const findHeader = (raw) =>
  `${lines(raw).filter((l) => l.includes("/")).length}F`;
const lsNames = (raw) =>
  lines(raw)
    .filter((l) => !/^total \d+/.test(l))
    .map((l) => path.basename(l.trim().split(/\s+/).pop() ?? ""))
    .filter((n) => n && n !== "." && n !== "..");

// facts(rawStdout) → strings/regexes the rewritten arm's output must contain.
const CORPUS = [
  {
    label: "grep import",
    cmd: `grep -rn "^import" packages/agent/src`,
    facts: () => [MATCH_HEADER],
  },
  {
    label: "grep export",
    cmd: `grep -rn "^export" packages/core/src`,
    facts: () => [MATCH_HEADER],
  },
  {
    label: "grep no-match",
    cmd: `grep -rn "zz-no-match-zz" scripts`,
    facts: () => [],
  },
  {
    label: "find ts",
    cmd: `find packages/agent/src -name "*.ts"`,
    facts: (raw) => [findHeader(raw)],
  },
  {
    label: "find -not (raw)",
    cmd: `find packages/agent -name "*.test.ts" -not -path "*/node_modules/*"`,
    facts: (raw) => [findHeader(raw)],
  },
  {
    label: "ls -la agent/src",
    cmd: "ls -la packages/agent/src",
    facts: lsNames,
  },
  { label: "git status", cmd: "git status", facts: () => [] },
  { label: "git branch -a", cmd: "git branch -a", facts: () => [] },
  {
    label: "chain: status+diff",
    cmd: "git status && git diff --stat",
    facts: () => [],
  },
  {
    label: "chain: ls+find",
    cmd: `ls packages/agent/src/adapters && find packages/agent/src/adapters -name "*.test.ts"`,
    facts: (raw) => [findHeader(raw)],
  },
  {
    label: "rg import",
    cmd: `rg -n "^import" packages/core/src`,
    facts: () => [MATCH_HEADER],
  },
  // Under rtk's 200-result cap rg passes through verbatim (no header), so the
  // fact is presence of a known raw line, not the header.
  {
    label: "chain: rg+status",
    cmd: `rg -n "Symbol.for" packages/core/src && git status`,
    facts: (raw) => lines(raw).slice(0, 1),
  },
];

// rg in agent sessions is often Claude Code's embedded ripgrep behind a shell
// function; expose it as a real executable so the bench mirrors a dev machine
// and `rtk rg` can exec it.
function ensureRgOnPath() {
  try {
    execFileSync("bash", ["-c", "command -v rg"], { encoding: "utf8" });
    return process.env.PATH;
  } catch {
    const dir = path.join(os.tmpdir(), "rtk-bench-rg");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      path.join(dir, "rg"),
      `#!/bin/bash\nexec -a rg "\${CLAUDE_CODE_EXECPATH:-$HOME/.local/bin/claude}" "$@"\n`,
      { mode: 0o755 },
    );
    return `${process.env.PATH}:${dir}`;
  }
}

const BENCH_PATH = ensureRgOnPath();
// Keep bench traffic out of the user's real rtk gain telemetry.
const BENCH_ENV = {
  ...process.env,
  PATH: BENCH_PATH,
  RTK_DB_PATH: path.join(os.tmpdir(), "rtk-bench-gain.db"),
};

function tokensOf(text) {
  return Math.ceil(Buffer.byteLength(text, "utf8") / 4);
}

function runShell(cmd) {
  const started = Date.now();
  const res = spawnSync("bash", ["-c", cmd], {
    cwd: repoRoot,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
    env: BENCH_ENV,
  });
  return {
    stdout: res.stdout ?? "",
    stderr: res.stderr ?? "",
    code: res.status ?? -1,
    ms: Date.now() - started,
  };
}

// Materialize main's policy module so the baseline arm runs the code actually
// shipped, not a reimplementation of it.
function materializeBaselinePolicy() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rtk-bench-baseline-"));
  fs.mkdirSync(path.join(dir, "session"), { recursive: true });
  for (const [gitPath, outPath] of [
    [`${RTK_MODULE_DIR}/rtk.ts`, "session/rtk.ts"],
    ["packages/agent/src/adapters/claude/git-command.ts", "git-command.ts"],
  ]) {
    const content = execFileSync("git", ["show", `main:${gitPath}`], {
      cwd: repoRoot,
      encoding: "utf8",
      maxBuffer: 16 * 1024 * 1024,
    });
    fs.writeFileSync(path.join(dir, outPath), content);
  }
  return path.join(dir, "session", "rtk.ts");
}

// One tsx eval applies both real policies to the whole corpus.
function applyPolicies(commands) {
  const baselineModule = materializeBaselinePolicy();
  const script = `
    import * as cand from ${JSON.stringify(path.join(repoRoot, RTK_MODULE_DIR, "rtk.ts"))};
    import * as base from ${JSON.stringify(baselineModule)};
    const cmds = JSON.parse(process.env.RTK_BENCH_CMDS);
    const options = { rgOnPath: "rgOnPath" in cand ? cand.rgOnPath(process.env) : false };
    console.log(JSON.stringify(cmds.map((c) => ({
      base: base.rewriteBashForRtk(c, "rtk"),
      cand: cand.rewriteBashForRtk(c, "rtk", options),
    }))));
  `;
  const stdout = execFileSync("pnpm", ["exec", "tsx", "-e", script], {
    cwd: path.join(repoRoot, "packages/agent"),
    encoding: "utf8",
    env: { ...BENCH_ENV, RTK_BENCH_CMDS: JSON.stringify(commands) },
  });
  const lines = stdout.trim().split("\n");
  return JSON.parse(lines[lines.length - 1]);
}

function fidelityIssues(facts, raw, arm) {
  const issues = [];
  if (arm.code !== raw.code) {
    issues.push(`exit ${arm.code} != raw ${raw.code}`);
  }
  if (raw.stdout.trim() && !arm.stdout.trim()) {
    issues.push("raw produced output, arm produced none");
  }
  if (arm.stdout === raw.stdout) return issues; // passthrough

  for (const fact of facts(raw.stdout)) {
    const present =
      fact instanceof RegExp
        ? fact.test(arm.stdout)
        : arm.stdout.includes(fact);
    if (!present) {
      issues.push(`missing fact ${fact}`);
      break;
    }
  }
  return issues;
}

const rewritten = applyPolicies(CORPUS.map((c) => c.cmd));

const rows = CORPUS.map(({ label, cmd, facts }, i) => {
  const raw = runShell(cmd);
  const arms = {};
  for (const arm of ["base", "cand"]) {
    const cmdForArm = rewritten[i][arm];
    const run = cmdForArm ? runShell(cmdForArm) : raw;
    arms[arm] = {
      rewritten: cmdForArm,
      tokens: tokensOf(run.stdout),
      ms: run.ms,
      issues: cmdForArm ? fidelityIssues(facts, raw, run) : [],
    };
  }
  return { label, rawTokens: tokensOf(raw.stdout), rawMs: raw.ms, ...arms };
});

const total = (pick) => rows.reduce((s, r) => s + pick(r), 0);
const totalRaw = total((r) => r.rawTokens);
const totalBase = total((r) => r.base.tokens);
const totalCand = total((r) => r.cand.tokens);
// A candidate-only failure is a regression this PR would ship — hard fail.
// A baseline failure the candidate fixed is evidence, not an error.
const regressions = rows.filter((r) => r.cand.issues.length);
const preexisting = rows.filter(
  (r) => r.base.issues.length && !r.cand.issues.length,
);

if (process.argv.includes("--json")) {
  console.log(
    JSON.stringify({ rows, totalRaw, totalBase, totalCand }, null, 2),
  );
} else {
  console.log(
    "RTK Bench -- raw vs baseline(main) vs candidate; tokens = bytes/4 heuristic",
  );
  console.log("=".repeat(78));
  for (const r of rows) {
    const fid = r.cand.issues.length
      ? "REGRESSION"
      : r.base.issues.length
        ? "fixed-vs-main"
        : "ok";
    console.log(
      `${r.label.padEnd(20)} raw=${String(r.rawTokens).padStart(7)}  base=${String(r.base.tokens).padStart(7)}  cand=${String(r.cand.tokens).padStart(7)}  fid=${fid}`,
    );
    for (const [arm, a] of [
      ["base", r.base],
      ["cand", r.cand],
    ]) {
      for (const issue of a.issues) console.log(`  !! ${arm}: ${issue}`);
    }
  }
  console.log("-".repeat(78));
  const pct = (n, d) => (d > 0 ? `${((1 - n / d) * 100).toFixed(1)}%` : "n/a");
  console.log(
    `TOTAL                raw=${String(totalRaw).padStart(7)}  base=${String(totalBase).padStart(7)}  cand=${String(totalCand).padStart(7)}`,
  );
  console.log(
    `reduction vs raw:    base=${pct(totalBase, totalRaw)}  cand=${pct(totalCand, totalRaw)}`,
  );
  console.log(
    `net policy gain (candidate vs baseline): ${pct(totalCand, totalBase)} of baseline output`,
  );
  if (preexisting.length) {
    console.log(
      `\n${preexisting.length} row(s) broken on main's policy are fixed by the candidate.`,
    );
  }
  if (regressions.length) {
    console.error(
      `\nCANDIDATE FIDELITY REGRESSIONS in ${regressions.length} row(s) — savings figures are not trustworthy.`,
    );
  }
}

process.exit(regressions.length ? 1 : 0);
