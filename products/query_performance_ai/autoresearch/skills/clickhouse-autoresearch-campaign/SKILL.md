---
name: clickhouse-autoresearch-campaign
description: Run a ClickHouse query optimization campaign on one git branch using pi-autoresearch, dynamic lanes and hypotheses, baseline result capture, correctness checks, and stagnation-aware lane/campaign review.
---

# ClickHouse Autoresearch Campaign

This skill packages the orchestration for optimizing one ClickHouse query on one git branch.

## Required reads

Before taking action, read these files completely:

- `../../docs/orchestration.md`
- `../../docs/interface.md`

Treat them as the operating contract.

## Preconditions

This skill assumes:

- `pi-autoresearch` is installed and its tools are available
- the current directory is a git repository
- you have a target query or enough context to identify one
- the operator will provide or help configure `.clickhouse-autoresearch/adapter.env`

## Branch rule

One campaign = one git branch.

If the current branch is not a dedicated campaign branch yet, create one before initializing the workspace.

## Workspace rule

Use a single workspace at:

```text
.clickhouse-autoresearch/
```

The branch is the campaign boundary. The workspace is just the artifact layout.

If `autoresearch.config.json` exists in the current working directory, read its `workingDir` field and use that path as the workspace instead of the default above. Automated orchestrators (for example PostHog's `run_campaign.py`) initialize the workspace at `/tmp/autoresearch-campaign/` and write the config alongside it.

## Pre-initialized workspace detection

**Before doing anything in the Setup sequence, check whether the workspace has already been prepared by an external orchestrator.** If the resolved workspace contains **all** of:

- `adapter.json`
- `baseline/metrics.json`
- `query/original.sql`

…then the workspace is pre-initialized. In that case:

- **Skip the entire Setup sequence (steps 1–6).** Do not ask the operator for a target query, connection details, or anything else — the orchestrator has already supplied them.
- Treat `operator-hunches.md` as optional context. If it only contains the stub template, proceed without hunches.
- Jump directly to step 7 of the Setup sequence (read the baseline and seed the first lanes and hypotheses), then continue with steps 8–9 and the normal campaign loop.
- Operate headlessly: at no point prompt the operator for input. If a decision requires judgment, apply the skill's default guidance and record the choice in `state.json` / `autoresearch.md`.

Only fall back to the interactive Setup sequence below when the workspace is empty or partially initialized.

## Setup sequence

1. Confirm or infer the target query and query identifier.
2. Create or verify the campaign branch.
3. Run:

```bash
bash ../../scripts/ch_campaign_init.sh --workspace .clickhouse-autoresearch --query-id <id>
```

Add optional flags as needed:

- `--query-file <path>`
- `--branch-name <name>`
- `--primary-metric latency_ms`
- `--metric-unit ms`
- `--direction lower`
- `--lane-stagnation-window <n>`
- `--campaign-stagnation-window <n>`
- `--max-total-iterations <n>`
- `--significant-improvement-pct <number>`
- `--repair-budget <n>`

4. Inspect the generated workspace.
5. Fill in or update:

- `.clickhouse-autoresearch/adapter.env`
- `.clickhouse-autoresearch/operator-hunches.md`
- `.clickhouse-autoresearch/state.json`
- `.clickhouse-autoresearch/autoresearch.md`

6. Capture the baseline:

```bash
bash ../../scripts/ch_capture_baseline.sh --workspace .clickhouse-autoresearch
```

If the baseline times out, enter range narrowing (see `orchestration.md` § Timeout queries):

1.  Copy `query/original.sql` to `query/narrowed.sql`
2.  Halve the time range in `narrowed.sql`
3.  Retry: `bash ../../scripts/ch_capture_baseline.sh --workspace .clickhouse-autoresearch` (after updating `query/original.sql` in the workspace to the narrowed version)
4.  Repeat until the query completes in 1–10s
5.  Record narrowing state in `state.json`: `{ "narrowed": true, "original_range": "...", "working_range": "..." }`
6.  Keep `query/original.sql` in the repo root as the full-range reference

7.  Read the baseline artifacts and seed the first lanes and hypotheses.
8.  Initialize the autoresearch session against the configured primary metric.
9.  Start the experiment loop using:

```bash
./.clickhouse-autoresearch/autoresearch.sh
```

with correctness backpressure through:

```bash
./.clickhouse-autoresearch/autoresearch.checks.sh
```

## Runtime responsibilities

During the campaign, you must:

- if the workspace was pre-initialized (see "Pre-initialized workspace detection"), never prompt the operator — assume headless operation and apply default guidance for every decision
- keep `query/current.sql` as the next candidate to test
- keep `query/best.sql` aligned with the best kept result
- maintain the lane / hypothesis / review notes
- update `state.json` after every experiment
- reflect after every experiment
- trigger lane review tactically
- trigger campaign review strategically
- preserve durable learning in `autoresearch.md` and `autoresearch.jsonl`
- maintain `suggestions.md` with generalizable improvement recommendations (schema-level and query-generation patterns)
- classify every kept optimization as schema-level, query-generation, or query-specific
- if narrowed: after every `keep`, run an escalation check against the original time range and log the result
- if an escalation check succeeds, graduate to the full range (re-capture baseline, update correctness reference)

## What the scripts do vs what you do

The scripts do deterministic work:

- create the workspace
- invoke environment-specific commands from `adapter.env`
- capture baseline artifacts
- run candidate queries
- compare candidate results to the saved baseline result set
- emit `METRIC ...` lines

You do the reasoning:

- choose the active lane
- choose the hypothesis
- decide whether to repair a wrong-but-fast candidate
- decide when to integrate wins across lanes
- decide when a lane is exhausted
- decide when the campaign is exhausted

## Review rule

Remember the separation:

- lane review may pause or close a lane
- only campaign review may close the campaign

## Integration rule

When validated wins from different lanes appear combinable, create and test an explicit integration hypothesis unless the wins are already naturally accumulated on the branch's current best query.

## Correctness rule

A saved baseline result set is the semantic source of truth.

If a candidate is faster but fails correctness checks:

- inspect the comparison summary
- decide whether the mismatch is trivial, repairable, or fundamental
- if the performance win is meaningful and the defect is likely fixable, open a bounded repair path
- otherwise record the dead end and move on

## Closure rule

Stop only after campaign-level review concludes that continuation no longer has enough expected value, signal, or budget.
