---
name: improving-mcp-tools
description: >
  Run an improve-my-MCP campaign: an autoresearch-style loop that measures the
  MCP agent experience with the eval harness, picks the highest-impact tool
  problem from production data, makes one bounded fix, and keeps it only if
  before/after scores improve. Use when asked to "improve my MCP", run an MCP
  improvement campaign, fix tool discoverability or descriptions based on
  evidence, or prepare an eval-backed PR for a tool change. Every shipped
  change must carry eval evidence; guardrails below are hard rules.
---

# Improving MCP tools

An MCP server gets better only in ways you can measure. This skill is the
campaign procedure: score the current agent experience, fix the biggest
problem, re-score, and only ship changes the numbers justify. It is the
operating manual for the "improve my MCP" loop — one iteration per pass,
journaled so a later iteration (or a different agent) can resume without
repeating work.

## The objective function

`services/mcp/evals/` is the harness. `benchmark/tasks.yaml` is a fixed set of
agent tasks with `expected_tools` and `success_criteria`; scores are only
comparable across runs of the same benchmark `version`.

- **Probe mode** (deterministic, no LLM):
  `LIVE_MCP_URL=... LIVE_MCP_TOKEN=... pnpm exec tsx evals/runner/probe.ts --out score.json`
  from `services/mcp/`. Reports tool-presence misses (discoverability), probe
  failures, and latency p50/p95. Non-zero exit = regression.
- **Agent mode** (LLM replay + judge): scores task success and tool-selection
  accuracy. Use it for description/discoverability changes — probes cannot
  detect that an agent picks the wrong tool.

Run the harness against a **seeded local or devbox stack**, never against a
customer project. Local recipe: `NODE_ENV=development PORT=9876
POSTHOG_API_BASE_URL=http://localhost:8000 pnpm dev:hono`, personal API key as
`LIVE_MCP_TOKEN`.

## One iteration

1. **Measure.** Run the harness for a baseline. Pull production evidence with
   the MCP analytics tools (`query-mcp-tool-stats`, `query-mcp-tool-failures`,
   `query-mcp-tool-descriptions`, `query-mcp-tool-sample-intents`) and the
   lenses in the signals scout cookbook
   (`products/signals/skills/signals-scout-mcp-tool-calls/references/queries.md`):
   failure leaderboard, retry/struggle, latency, intents that matched no tool.
2. **Pick one issue.** Rank by reach × severity. Skip anything the journal
   shows with two failed attempts. One issue per iteration — a PR that fixes
   three things can't be attributed to any of them when scores move.
3. **Fix, bounded.** Only files inside the allowlist (below). Typical fixes:
   sharpen a tool description so the right intent finds it, tighten an input
   schema that agents keep getting wrong, fix an annotation, update a skill.
4. **Validate.** Re-run the affected benchmark slice plus a no-regression
   sample. Keep the change only if the target metric improves and nothing else
   degrades. A discarded change is a normal outcome — journal it and move on.
5. **Ship.** One PR per iteration with before/after scores in the body (format
   in [references/campaign-journal.md](references/campaign-journal.md)). Keep
   it stampable: ≤400 changed lines, no deny-listed files, apply the
   `stamphog` label. Autonomy level comes from the campaign config — default
   is **draft PR for human review**; only arm auto-merge when the operator has
   explicitly enabled the self-driving experiment (see guardrails).
6. **Journal.** Append the iteration record before ending the pass.

## Hard guardrails

These are not suggestions; violating any of them ends the campaign pass.

- **Allowlist** — a campaign PR may only touch: `products/*/mcp/tools.yaml`,
  `products/*/skills/**`, `services/mcp/evals/**`, regenerated tool files
  produced by the standard codegen, and docs. Anything else (handler code,
  package manifests, workflows, migrations, auth paths) → stop and hand the
  finding to a human as a draft PR or report instead.
- **Read-only against data.** The harness and all production queries are
  read-only. Never create, mutate, or delete customer-visible objects while
  measuring.
- **Evidence or it didn't happen.** No PR without a baseline score, an after
  score, and the exact harness commands used.
- **Benchmark integrity.** Never edit `benchmark/tasks.yaml` in the same PR as
  a fix it validates — changing the exam and the answer together proves
  nothing. Benchmark changes are their own PR and bump `version`.
- **Budgets.** Respect the operator's iteration/token/PR caps (default: stop
  after 3 open unmerged campaign PRs). Two failed attempts on an issue parks
  it permanently.
- **Kill switch.** If the campaign config, its feature flag, or the operator
  says stop — stop mid-iteration, journal state, end cleanly.

## Failure modes to expect

- A description change that helps one intent can steal traffic from the right
  tool for another — that's why the no-regression sample is mandatory.
- Probe latency varies with stack warmth; compare medians across ≥3 runs
  before attributing a latency change to your fix.
- Tool-presence misses can be feature-flag gating, not catalog absence —
  check `getToolsForFeatures` gating before "fixing" discoverability.
