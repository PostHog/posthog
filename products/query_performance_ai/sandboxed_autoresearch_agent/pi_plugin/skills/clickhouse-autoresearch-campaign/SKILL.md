---
name: clickhouse-autoresearch-campaign
description: Run a ClickHouse query optimization campaign on one git branch using pi-autoresearch, dynamic lanes and hypotheses, baseline result capture, correctness checks, and stagnation-aware lane/campaign review.
---

# ClickHouse Autoresearch Campaign

This skill packages the orchestration for optimizing one ClickHouse query on one git branch.

## Required reads

Before taking action, read `orchestration.md` (sibling of this file) completely. Treat it as the operating contract.

## Preconditions

This skill assumes:

- `pi-autoresearch` is installed and its tools are available
- the current directory is a git repository
- you have a target query or enough context to identify one
- the operator will provide or help configure `.clickhouse-autoresearch/adapter.json`

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
- Jump directly to step 7 of the Setup sequence (read the baseline and seed the first lanes and hypotheses), then continue with steps 8–9 and the normal campaign loop.
- Operate headlessly: at no point prompt the operator for input. If a decision requires judgment, apply the skill's default guidance and record the choice in `state.json` / `autoresearch.md`.

Only fall back to the interactive Setup sequence below when the workspace is empty or partially initialized.

## Adapter capabilities (what you can and cannot run)

Campaign queries flow through the adapter configured in `adapter.json`. Every campaign script (`ch_capture_baseline.py`, `ch_run_candidate.py`, any ad-hoc probe) ultimately submits SQL through this adapter, and the adapter enforces what ClickHouse sees.

When `adapter.json` has `type: "coordinator"`, your SQL is routed to whichever ClickHouse the host-side coordinator is pointed at — typically a read-only test cluster (currently team 1 data) or a local dev ClickHouse. Either way the cluster runs SQL under a profile that pins `readonly = 2`, so writes (INSERT, ALTER, CREATE, OPTIMIZE, SYSTEM, TRUNCATE, DROP, ATTACH, DETACH) will fail with a ClickHouse error. **Read `GET /v1/info` (or check `autoresearch.md` — the coordinator's prompt addendum is prepended there)** before issuing any predicate that depends on a specific `team_id`: in test-cluster mode you may need to rewrite team_id predicates to `team_id = 1`. For experiments treat every read-only statement form as available:

- `SELECT …` — arbitrary subqueries, CTEs, joins
- `WITH … SELECT …`
- `EXPLAIN …` — every variant ClickHouse supports. Use them before proposing rewrites:
  - `EXPLAIN SELECT …` (default: PLAN)
  - `EXPLAIN AST SELECT …`
  - `EXPLAIN SYNTAX SELECT …`
  - `EXPLAIN QUERY TREE SELECT …` (post-analyzer logical tree; invaluable on modern ClickHouse)
  - `EXPLAIN PIPELINE SELECT …` — processor-level pipeline, headers, expressions
  - `EXPLAIN ESTIMATE SELECT …` — per-part row/mark estimates before execution
  - `EXPLAIN PLAN indexes = 1, actions = 1, json = 1 SELECT …` — primary-key and skip-index use, JSON for machine parsing
  - `EXPLAIN TABLE OVERRIDE …`
- `SHOW …` — `SHOW CREATE TABLE events`, `SHOW COLUMNS FROM events`, `SHOW INDEX FROM events`, `SHOW SETTINGS ILIKE '%mark_cache%'`, etc.
- `DESCRIBE` / `DESC …`

**Timeout**: every submission is wrapped with `SETTINGS max_execution_time = 60`. Keep ad-hoc probes short. If the target query itself routinely exceeds 60s, use range narrowing (see Setup step 6) and only then start the campaign.

**Cluster scoping**: depends on the coordinator's `target`. The test cluster currently contains only team-1 data — you must rewrite team_id predicates to `team_id = 1` (the prompt addendum prepended to `autoresearch.md` spells this out). The local-CH target runs whatever data your dev container has; no rewrite needed. Read the addendum first.

**Profiling ClickHouse's perspective**:

After a run, the campaign scripts capture client-side `elapsed_ms`, `rows_read`, `bytes_read`, and the server-minted `query_id` from the proxy response (persisted as `query_id` in `runs/run-XXXX-*/metrics.json` and `baseline/metrics.json`). The `autoresearch` CH user can read four `system.*` profiling tables for its own queries (RESTRICTIVE row policies hide every other user's rows):

| Table                     | What's in it                                                                                                                             |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `system.query_log`        | One row per finished query: `query_duration_ms`, `read_rows`, `read_bytes`, `memory_usage`, `ProfileEvents` (map of low-level counters). |
| `system.query_thread_log` | Per-thread breakdown of the query: CPU time, wait time, peak memory per thread.                                                          |
| `system.text_log`         | Server-side log lines tagged with `query_id` (planner messages, mark-cache hits, merge-trigger).                                         |
| `system.trace_log`        | Sampled stack traces during query execution. Lit up by `query_profiler_real_time_period_ns`.                                             |

Look up a finished query's headline stats:

```sql
SELECT query_duration_ms, read_rows, read_bytes, memory_usage, ProfileEvents
FROM system.query_log
WHERE type = 'QueryFinish' AND query_id = '<query_id from metrics.json>'
ORDER BY event_time DESC
LIMIT 1
```

Useful `ProfileEvents` for query-perf work:

- `SelectedParts`, `SelectedRanges`, `SelectedMarks` — how much of the table the planner chose to read (lower = better-pruned predicates).
- `OSReadChars` vs `OSReadBytes` — disk-cache hit ratio.
- `RealTimeMicroseconds`, `UserTimeMicroseconds`, `SystemTimeMicroseconds` — wall vs CPU time (gap = waiting on I/O or locks).
- `Merge*`, `*Mark*`, `*PrimaryKey*` — index usage and compaction cost.

Per-thread to find tail latency:

```sql
SELECT thread_id, query_duration_ms, peak_memory_usage, ProfileEvents['OSReadBytes']
FROM system.query_thread_log
WHERE query_id = '<query_id>'
ORDER BY query_duration_ms DESC
```

Server-side log lines for a single query (planner choices, parts pruning, etc.):

```sql
SELECT event_time, level, logger_name, message
FROM system.text_log
WHERE query_id = '<query_id>'
ORDER BY event_time
```

Sampled stack traces (only useful if `query_profiler_real_time_period_ns > 0` was active for the run):

```sql
SELECT count(), arrayStringConcat(arrayMap(x -> demangle(addressToSymbol(x)), trace), '\n') AS frames
FROM system.trace_log
WHERE query_id = '<query_id>'
GROUP BY frames
ORDER BY count() DESC
LIMIT 20
```

`system.query_log` is readable under `readonly = 2`. Use it to compare ProfileEvents across iterations, not only wall-clock latency.

**Schema inspection** before proposing rewrites is free and often decisive:

```sql
SHOW CREATE TABLE events
DESCRIBE events
SELECT name, type, default_expression, codec_expression, is_in_primary_key, is_in_partition_key
FROM system.columns WHERE database = currentDatabase() AND table = 'events'
SELECT name, expr, type FROM system.data_skipping_indices WHERE table = 'events'
```

Use these to check the primary key, partitioning, codecs, and existing skip-indexes before hypothesizing that "adding an index" would help.

**ClickHouse source code** is bundled into the sandbox at `/opt/clickhouse`, pinned to a recent ClickHouse commit. This likely matches the behavior of the cluster you're querying, but it may lag or diverge from the version actually running in prod — treat it as a strong hint, not ground truth, and be alert to cases where observed behavior disagrees with what the source suggests. `tests/`, `docs/`, `website/`, `contrib/`, and `.git` are stripped; everything else — the engine, query analyzer, storage, functions — is readable. Use it to ground hypotheses in the actual implementation:

- `grep -rn "<FunctionName>" /opt/clickhouse/src/Functions/` — find the C++ implementation of a function you're using
- `ls /opt/clickhouse/src/Storages/MergeTree/` — MergeTree internals (skip indexes, parts, marks)
- `ls /opt/clickhouse/src/Interpreters/` — query-tree rewrites, analyzer passes, join engines
- `ls /opt/clickhouse/src/Processors/` — pipeline / QueryPlan steps (what `EXPLAIN PIPELINE` is describing)

Reading the source is often the fastest way to resolve questions like "does this function short-circuit?", "how does this skip-index decide which granules to read?", "what settings does this pass consult?". Prefer reading the source over guessing or inferring from documentation.

**What this means for hypothesis formation**: start every lane by running `EXPLAIN indexes = 1, actions = 1, json = 1 SELECT <original>` and inspecting the plan. Then propose rewrites that target concrete weaknesses (full table scan, skipped PREWHERE, missing primary-key usage, etc.). Do not guess.

## Setup sequence

1. Confirm or infer the target query and query identifier.
2. Create or verify the campaign branch.
3. Run:

```bash
python3 ../../scripts/ch_campaign_init.py --workspace .clickhouse-autoresearch --query-id <id>
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

- `.clickhouse-autoresearch/adapter.json`
- `.clickhouse-autoresearch/state.json`
- `.clickhouse-autoresearch/autoresearch.md`

6. Capture the baseline:

```bash
python3 ../../scripts/ch_capture_baseline.py --workspace .clickhouse-autoresearch
```

If the baseline times out, enter range narrowing (see `orchestration.md` § Timeout queries):

1. Copy `query/original.sql` to `query/narrowed.sql`
2. Halve the time range in `narrowed.sql` (leave `query/original.sql` untouched — it is the full-range reference used by the escalation check)
3. Retry against the narrowed file: `python3 ../../scripts/ch_capture_baseline.py --workspace .clickhouse-autoresearch --query-file query/narrowed.sql`
4. Repeat halving until the query completes in 1–10s
5. Record narrowing state in `state.json`: `{ "narrowed": true, "original_range": "...", "working_range": "..." }`

6. Read the baseline artifacts and seed the first lanes and hypotheses.
7. Initialize the autoresearch session against the configured primary metric.
8. Start the experiment loop using:

```bash
./.clickhouse-autoresearch/autoresearch.py
```

with correctness backpressure through:

```bash
./.clickhouse-autoresearch/autoresearch_checks.py
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
- maintain `out-of-scope-suggestions.md` — the agent's persistent record of schema-level changes it suspects would help but cannot apply in the sandbox (materialized columns, skip indexes, projections, table-engine swaps). The orchestrator harvests this file as a deliverable, so each entry must include the change, evidence, expected impact, and which queries would benefit
- classify every kept optimization as schema-level, query-generation, or query-specific
- if narrowed: after every `keep`, run an escalation check against the original time range and log the result
- if an escalation check succeeds, graduate to the full range (re-capture baseline, update correctness reference)

## What the scripts do vs what you do

The scripts do deterministic work:

- create the workspace
- invoke environment-specific commands from `adapter.json`
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

## Reasoning rules

Review separation, integration, correctness, and closure are defined in
`orchestration.md` (sibling of this file). Apply them as written.
