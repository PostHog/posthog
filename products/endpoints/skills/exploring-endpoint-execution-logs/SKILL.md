---
name: exploring-endpoint-execution-logs
description: >
  Explore and diagnose a PostHog endpoint's execution logs — error messages, failed runs, cache
  misses, slow runs, or unexpected row counts during endpoint invocations. Use when the user says
  "my endpoint is failing", "show me the logs for endpoint X", "what error did endpoint Y produce",
  "why did endpoint Z return no rows", "is this endpoint hitting cache", or "check the last N runs".
  Focused on a single named endpoint's runtime log entries, not project-wide auditing or query
  performance profiling.
---

# Exploring endpoint execution logs

Every endpoint run emits one execution log entry to PostHog's `log_entries` store. This skill
reads those entries for a specific endpoint to answer "what happened when it ran?". It is the
log-level counterpart to `diagnosing-endpoint-performance` (which reasons about cache/materialisation
strategy from config and `query_log`).

## When to use this skill

- "Why is my endpoint failing / erroring?"
- "Show me the logs / recent runs for endpoint X"
- "Did the last run hit cache? How many rows did it return?"
- "What happened the last time endpoint Y ran?"

If the question is "this endpoint is slow, what should I change?", use
`diagnosing-endpoint-performance`. If it's project-wide ("what can I clean up?"), use
`auditing-endpoints`.

## What an execution log entry looks like

Each run produces exactly one entry. The level is `INFO` on success and `ERROR` on failure, and the
message carries the extra data as searchable `key=value` tokens:

```text
Endpoint executed · path=materialized cache=hit duration_ms=142 rows=1024 version=3
Endpoint execution failed · path=inline error=ResolutionError version=3
```

Token meanings:

| Token         | Values                                                       | Meaning                                                        |
| ------------- | ------------------------------------------------------------ | -------------------------------------------------------------- |
| `path`        | `materialized` / `inline` / `ducklake` / `ducklake_fallback` | Which execution path ran                                       |
| `cache`       | `hit` / `miss`                                               | Whether the query result cache was used (omitted for ducklake) |
| `duration_ms` | integer                                                      | Wall-clock execution time                                      |
| `rows`        | integer                                                      | Number of result rows returned                                 |
| `version`     | integer                                                      | Which endpoint version ran                                     |
| `error`       | e.g. `ResolutionError`, `HogVMException`                     | Error class / HogQL code name (failures only)                  |

Each run gets a distinct `instance_id`, so logs group one-per-execution in the viewer.

## Available tools

| Tool            | Purpose                                                                                                                       |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `endpoint-logs` | Primary. Execution log entries for one endpoint by name. Filter by level, search, time range, instance_id; `limit` up to 500. |
| `endpoint-get`  | Endpoint config for context (current version, materialisation, query kind)                                                    |
| `execute-sql`   | Fallback / aggregation directly against `log_entries` (`log_source='endpoints'`)                                              |

## Filtering

`endpoint-logs` exposes the standard log filters:

- **level** — comma-separated, e.g. `ERROR` to see only failed runs, or `INFO,ERROR` for all.
- **search** — case-insensitive substring over the message. Because the extra data is in
  `key=value` tokens, you can search `cache=miss`, `path=inline`, `error=ResolutionError`, or a
  specific `version=3`.
- **after / before** — ISO timestamps to bound the time range.
- **instance_id** — pin a single execution.
- **limit** — 1–500 (default 50).

## Workflow

1. Identify the endpoint by name. If given a URL, parse it from
   `/api/projects/{team_id}/endpoints/{name}/run`.
2. Start broad: `endpoint-logs` for the endpoint with a recent time range. Skim levels and tokens.
3. Narrow to the symptom:
   - Failures → `level=ERROR`; read the `error=` token and `path=` to see where it broke.
   - Cache concerns → `search=cache=miss` to see how often runs miss cache.
   - Wrong results → compare `rows=` across runs, and `version=` to spot a regression after a
     version bump.
4. For counts/trends across many runs (e.g. error rate over a week), drop to `execute-sql` against
   `log_entries`:

   ```sql
   SELECT toDate(timestamp) AS day, upper(level) AS level, count() AS runs
   FROM log_entries
   WHERE log_source = 'endpoints' AND log_source_id = '<endpoint_uuid>'
   GROUP BY day, level ORDER BY day DESC
   ```

   Get the endpoint UUID from `endpoint-get` (the `log_source_id` is the endpoint id, not its name).

5. Summarize: what's failing, since when, on which version/path, and whether it's a config issue
   (hand off to `diagnosing-endpoint-performance`) or a query bug.

## Example interaction

```text
User: "weekly_signups started erroring this morning"

Agent steps:
- endpoint-logs weekly_signups, level=ERROR, after=<this morning>
  → several "Endpoint execution failed · path=inline error=ResolutionError version=5"
- endpoint-get weekly_signups → current version is v5 (bumped today)
- endpoint-logs weekly_signups, level=INFO, before=<this morning>
  → prior runs: "path=inline cache=hit ... version=4" succeeded

- "v5 (created this morning) is failing with a ResolutionError on the inline path — it can't
   resolve a table or field reference. v4 ran fine. This looks like a bad query in the new
   version. Want me to pull the v5 query (endpoint-versions) so we can fix it, or roll back to v4?"
```

## Important notes

- **One entry per run.** Don't expect step-by-step traces — endpoints log a single completion line.
  The detail lives in the tokens, not in multiple lines.
- **`log_source_id` is the endpoint UUID**, not the name. For `execute-sql`, fetch it via
  `endpoint-get` first.
- **Logs are retained ~90 days** (the `log_entries` TTL). Older runs won't appear.
- **Execution logs ≠ query performance.** `endpoint-logs` tells you what happened and why a run
  failed; for "should I materialise / bump cache TTL?" use `diagnosing-endpoint-performance`, which
  reasons over config and `query_log` cost metrics.
- **Best-effort emission.** A log line is emitted after each run but never blocks it — if a run
  succeeded for the caller but no log shows, the emit was dropped, not the query.
