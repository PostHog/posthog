#!/usr/bin/env node
// Stress benchmark of the RTK rewrite policy: candidate (working tree) vs
// baseline (main's policy, materialized via `git show`) vs raw, on a fixed
// command corpus against this repo's own files. Both arms apply the REAL
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
// SCOPE — what this bench does and does not prove. The corpus intentionally
// overrepresents large compressible commands and is not a production-traffic
// estimate. Token figures are
// bytes/4 over stdout+stderr, a size heuristic comparable to `rtk gain`, NOT
// provider tokenizer counts. The corpus is fixed and NOT usage-weighted, and
// the bench measures command output only: no prompt-guidance overhead, no
// model retries, no session outcomes. It can prove output reduction and
// fidelity for these command shapes; a net harness gain claim additionally
// requires a session-level A/B (total input/output tokens, retries, task
// success) — see the rtk-context-fidelity e2e for the fidelity half.
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
// contract with EXACT expected values derived from raw output — a generic
// "any number" pattern would let materially wrong totals pass. Completeness
// is asserted only where rtk is complete (ls, under-cap rg passthrough).
//
// The exact-count fact is only valid for anchored patterns (one match per
// line); rtk counts match occurrences, raw output counts matching lines.
const matchHeader = (raw) => {
  const files = new Set(lines(raw).map((l) => l.split(":", 1)[0]));
  return `${lines(raw).length} matches in ${files.size} files`;
};
const findHeader = (raw) =>
  `${lines(raw).filter((l) => l.includes("/")).length}F`;
const lsNames = (raw) =>
  lines(raw)
    .filter((l) => !/^total \d+/.test(l))
    .map((l) => path.basename(l.trim().split(/\s+/).pop() ?? ""))
    .filter((n) => n && n !== "." && n !== "..");
// Per-file facts from `git status` long format: every modified/new/deleted
// path and the current branch must survive compression.
const gitStatusFacts = (raw) => {
  const facts = [];
  const branch = raw.match(/^On branch (\S+)/m);
  if (branch) facts.push(branch[1]);
  for (const m of raw.matchAll(
    /^\s+(?:modified|new file|deleted):\s+(\S+)/gm,
  )) {
    facts.push(m[1]);
  }
  return facts;
};
// Under rtk's 200-result cap rg passes through verbatim, so every raw
// file:line match must be present, not just a summary.
const rgLines = (raw) => lines(raw).filter((l) => /^\S+:\d+:/.test(l));

// facts(rawStdout) → strings/regexes the rewritten arm's output must contain.
const CORPUS = [
  {
    label: "grep import",
    cmd: `grep -rn "^import" packages/agent/src`,
    facts: (raw) => [matchHeader(raw)],
  },
  {
    label: "grep export",
    cmd: `grep -rn "^export" packages/core/src`,
    facts: (raw) => [matchHeader(raw)],
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
  { label: "git status", cmd: "git status", facts: gitStatusFacts },
  {
    label: "git branch -a",
    cmd: "git branch -a",
    facts: (raw) => {
      const current = raw.match(/^\* (\S+)/m);
      return current ? [current[1]] : [];
    },
  },
  {
    label: "chain: status+diff",
    cmd: "git status && git diff --stat",
    facts: gitStatusFacts,
  },
  {
    label: "chain: ls+find",
    cmd: `ls packages/agent/src/adapters && find packages/agent/src/adapters -name "*.test.ts"`,
    facts: (raw) => [findHeader(raw)],
  },
  {
    label: "rg import",
    cmd: `rg -n "^import" packages/core/src`,
    facts: (raw) => [matchHeader(raw)],
  },
  {
    label: "chain: rg+status",
    cmd: `rg -n "Symbol.for" packages/core/src && git status`,
    facts: (raw) => [...rgLines(raw), ...gitStatusFacts(raw)],
  },
];

// rg in agent sessions is often Claude Code's embedded ripgrep behind a shell
// function; expose it as a real executable so the bench mirrors a dev machine
// and `rtk rg` can exec it.
// Per-run private temp dir: fixed shared-tmp paths are plantable (an attacker
// pre-owning the dir can swap the shim executable) and collide across
// concurrent runs.
const RUN_TMP = fs.mkdtempSync(path.join(os.tmpdir(), "rtk-bench-"));
process.on("exit", () => {
  fs.rmSync(RUN_TMP, { recursive: true, force: true });
});

function ensureRgOnPath() {
  try {
    execFileSync("bash", ["-c", "command -v rg"], { encoding: "utf8" });
    return process.env.PATH;
  } catch {
    const dir = path.join(RUN_TMP, "rg-shim");
    fs.mkdirSync(dir);
    const wrapper = path.join(dir, "rg");
    fs.writeFileSync(
      wrapper,
      `#!/bin/bash\nexec -a rg "\${CLAUDE_CODE_EXECPATH:-$HOME/.local/bin/claude}" "$@"\n`,
      { mode: 0o755 },
    );
    // The shim assumes the Claude Code binary multiplexes into ripgrep on
    // argv[0]; verify once so a wrong assumption fails here with a clear
    // message instead of surfacing as a fake fidelity regression.
    try {
      execFileSync(wrapper, ["--version"], { encoding: "utf8" });
    } catch {
      console.error(
        "rg is not on PATH and the Claude Code ripgrep shim does not work here; rg rows would misreport. Install ripgrep and re-run.",
      );
      process.exit(2);
    }
    return `${process.env.PATH}:${dir}`;
  }
}

const BENCH_PATH = ensureRgOnPath();
// Keep bench traffic out of the user's real rtk gain telemetry.
const BENCH_ENV = {
  ...process.env,
  PATH: BENCH_PATH,
  RTK_DB_PATH: path.join(RUN_TMP, "gain.db"),
};

// stderr counts too: in an agent session the model reads both streams, and
// an arm that moves output from stdout to an error on stderr must not score
// as savings.
function tokensOf(run) {
  return Math.ceil(
    (Buffer.byteLength(run.stdout, "utf8") +
      Buffer.byteLength(run.stderr, "utf8")) /
      4,
  );
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
function resolveBaselineRef() {
  for (const ref of ["main", "origin/main"]) {
    try {
      execFileSync("git", ["rev-parse", "--verify", `${ref}^{commit}`], {
        cwd: repoRoot,
        stdio: "pipe",
      });
      return ref;
    } catch {}
  }
  console.error(
    "Neither `main` nor `origin/main` resolves here (shallow or detached checkout?) — cannot materialize the baseline policy arm.",
  );
  process.exit(2);
}

function materializeBaselinePolicy() {
  const ref = resolveBaselineRef();
  const dir = path.join(RUN_TMP, "baseline");
  fs.mkdirSync(path.join(dir, "session"), { recursive: true });
  for (const [gitPath, outPath] of [
    [`${RTK_MODULE_DIR}/rtk.ts`, "session/rtk.ts"],
    ["packages/agent/src/adapters/claude/git-command.ts", "git-command.ts"],
  ]) {
    const content = execFileSync("git", ["show", `${ref}:${gitPath}`], {
      cwd: repoRoot,
      encoding: "utf8",
      maxBuffer: 16 * 1024 * 1024,
    });
    fs.writeFileSync(path.join(dir, outPath), content);
  }
  return path.join(dir, "session", "rtk.ts");
}

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
      tokens: tokensOf(run),
      ms: run.ms,
      issues: cmdForArm ? fidelityIssues(facts, raw, run) : [],
    };
  }
  return { label, rawTokens: tokensOf(raw), rawMs: raw.ms, ...arms };
});

const total = (pick) => rows.reduce((s, r) => s + pick(r), 0);
const totalRaw = total((r) => r.rawTokens);
const totalBase = total((r) => r.base.tokens);
const totalCand = total((r) => r.cand.tokens);
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
    "RTK stress bench -- raw vs baseline(main) vs candidate; tokens = bytes/4 heuristic",
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
