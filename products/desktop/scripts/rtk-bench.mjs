#!/usr/bin/env node
// Deterministic token benchmark of the RTK rewrite policy. Runs a fixed
// command corpus against this repo's own files, once raw and once after
// applying the REAL `rewriteBashForRtk` hook policy (imported from
// packages/agent via tsx, not reimplemented), and reports the weighted-average
// % token reduction. Token estimate is bytes/4 (rtk's own heuristic).
//
// The corpus mixes single bare commands with `&&`-chained lines, mirroring the
// harness guidance that instructs the agent to batch commands with `&&`.
//
// Usage: node scripts/rtk-bench.mjs [--json]

import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

const CORPUS = [
  // Single bare commands (the pre-existing rewrite surface).
  { label: "grep import", cmd: `grep -rn "^import" packages/agent/src` },
  { label: "grep export", cmd: `grep -rn "^export" packages/core/src` },
  { label: "find ts", cmd: `find packages/agent/src -name "*.ts"` },
  {
    label: "find test",
    cmd: `find packages -name "*.test.ts" -not -path "*/node_modules/*"`,
  },
  { label: "ls -la agent/src", cmd: "ls -la packages/agent/src" },
  { label: "ls -la core/src", cmd: "ls -la packages/core/src" },
  { label: "git status", cmd: "git status" },
  { label: "git branch -a", cmd: "git branch -a" },
  // &&-chained lines, as the harness's batching guidance produces.
  {
    label: "chain: status+diff",
    cmd: "git status && git diff --stat",
  },
  {
    label: "chain: ls+find",
    cmd: `ls -la packages/agent/src/adapters && find packages/agent/src/adapters -name "*.test.ts"`,
  },
  {
    label: "chain: grep+grep",
    cmd: `grep -rn "describe(" packages/agent/src/adapters/claude/session && grep -rn "test.each" packages/agent/src/adapters/claude/session`,
  },
  {
    label: "chain: mixed heads",
    cmd: `echo checking && ls packages/core/src && git branch -a`,
  },
  // rg: often a shell function (Claude Code's embedded ripgrep) rather than a
  // PATH binary, hence the shim in runShell.
  { label: "rg import", cmd: `rg -n "^import" packages/core/src` },
  {
    label: "chain: rg+status",
    cmd: `rg -n "Symbol.for" packages/core/src && git status`,
  },
];

// Non-interactive bash lacks the profile function that exposes Claude Code's
// embedded ripgrep. Expose it as a real executable on PATH instead, matching
// a dev machine with ripgrep installed — which also lets `rtk rg` exec it.
function ensureRgOnPath() {
  try {
    execFileSync("bash", ["-c", "command -v rg"], { encoding: "utf8" });
    return process.env.PATH;
  } catch {
    const dir = path.join(os.tmpdir(), "rtk-bench-rg");
    fs.mkdirSync(dir, { recursive: true });
    const wrapper = path.join(dir, "rg");
    fs.writeFileSync(
      wrapper,
      `#!/bin/bash\nexec -a rg "\${CLAUDE_CODE_EXECPATH:-$HOME/.local/bin/claude}" "$@"\n`,
      { mode: 0o755 },
    );
    return `${process.env.PATH}:${dir}`;
  }
}

const BENCH_PATH = ensureRgOnPath();

function tokensOf(text) {
  return Math.ceil(Buffer.byteLength(text, "utf8") / 4);
}

function runShell(cmd) {
  try {
    return execFileSync("bash", ["-c", cmd], {
      cwd: repoRoot,
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
      env: { ...process.env, PATH: BENCH_PATH },
    });
  } catch (err) {
    return err.stdout ?? "";
  }
}

// Apply the real hook policy from packages/agent in one tsx subprocess.
function applyRewritePolicy(commands) {
  const script = `
    import { rewriteBashForRtk, rgOnPath } from "./src/adapters/claude/session/rtk";
    const cmds = JSON.parse(process.env.RTK_BENCH_CMDS);
    const options = { rgOnPath: rgOnPath(process.env) };
    console.log(JSON.stringify(cmds.map((c) => rewriteBashForRtk(c, "rtk", options))));
  `;
  const stdout = execFileSync("pnpm", ["exec", "tsx", "-e", script], {
    cwd: path.join(repoRoot, "packages/agent"),
    encoding: "utf8",
    env: {
      ...process.env,
      PATH: BENCH_PATH,
      RTK_BENCH_CMDS: JSON.stringify(commands),
    },
  });
  const lines = stdout.trim().split("\n");
  return JSON.parse(lines[lines.length - 1]);
}

const rewritten = applyRewritePolicy(CORPUS.map((c) => c.cmd));

const rows = CORPUS.map(({ label, cmd }, i) => {
  const raw = runShell(cmd);
  const optimized = rewritten[i] ? runShell(rewritten[i]) : raw;
  const rawTokens = tokensOf(raw);
  const optTokens = tokensOf(optimized);
  const pct = rawTokens > 0 ? (1 - optTokens / rawTokens) * 100 : 0;
  return { label, rewritten: rewritten[i] ?? null, rawTokens, optTokens, pct };
});

const totalRaw = rows.reduce((s, r) => s + r.rawTokens, 0);
const totalOpt = rows.reduce((s, r) => s + r.optTokens, 0);
const weightedPct = totalRaw > 0 ? (1 - totalOpt / totalRaw) * 100 : 0;

if (process.argv.includes("--json")) {
  console.log(
    JSON.stringify({ rows, totalRaw, totalOpt, weightedPct }, null, 2),
  );
} else {
  console.log("RTK Bench -- raw vs hook-policy token estimate (bytes/4)");
  console.log("=".repeat(64));
  for (const r of rows) {
    console.log(
      `${r.label.padEnd(22)} raw=${String(r.rawTokens).padStart(7)}  opt=${String(r.optTokens).padStart(6)}  ${r.pct.toFixed(1)}%${r.rewritten ? "" : "  (not rewritten)"}`,
    );
  }
  console.log("-".repeat(64));
  console.log(
    `TOTAL                  raw=${String(totalRaw).padStart(7)}  opt=${String(totalOpt).padStart(6)}  ${weightedPct.toFixed(1)}%`,
  );
}
