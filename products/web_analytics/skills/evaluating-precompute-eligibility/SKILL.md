---
name: evaluating-precompute-eligibility
description: >
  Investigates how often each web analytics filter / date-range / breakdown
  combination runs and whether it lands on the lazy precompute path, by
  slicing the `web_analytics_query` and `lazy_computation.executed` Loki log
  lines on `filters_eligibility_hash`. Use when prioritizing which tiles or
  teams to migrate to precompute next, computing per-team `q/key`
  (queries-per-distinct-cache-key) over multi-day windows, finding hot
  combinations that fall back to live HogQL, or quantifying the impact of an
  eligibility-gate change. Wraps the `monitoring-ingestion-pipeline` Grafana
  MCP patterns with the web-analytics-specific log lines and the
  `filters_eligibility_hash` join key.
---

# Evaluating precompute eligibility for web analytics queries

Every web analytics query runner binds a `filters_eligibility_hash` on
`structlog.contextvars` for the duration of `WebAnalyticsQueryRunner.calculate`.
The project-wide `merge_contextvars` processor attaches it to every structured
log emitted in the call tree — so it shows up on:

- `web_analytics_query` (canonical request log line — fires for **every** web
  analytics query regardless of which path serves it)
- `web_analytics_query_started`
- each lazy-precompute path's `*_rejected` / `*_eligible` outcome
- `lazy_computation.executed` (only when the precompute path actually ran)

The hash covers the user-facing query schema (kind + properties + dateRange +
breakdownBy + conversionGoal + sampling + interval + compareFilter +
filterTestAccounts) plus team timezone. See
`compute_filters_eligibility_hash` in
`products/web_analytics/backend/hogql_queries/web_lazy_precompute_common.py`
for the exact field set and which fields are stripped before hashing
(`useWebAnalyticsPrecompute`, `modifiers`, `version`, `tags`, `response`,
`limit`, `offset`, `limitBy`).

**Important: the hash is _not_ in `system.query_log.log_comment`.** ClickHouse
query_log has sub-day retention on prod, so the hash is only available where
multi-day analysis is meaningful — Loki, ~14 d. Don't reach for the Metabase
playbook for this; use Grafana MCP.

## When to use this

- Ranking **which teams or tiles** to migrate to precompute next: filter combos
  that recur often are the cheapest wins.
- Estimating **`q/key`** per team — the queries-per-distinct-cache-key metric
  that drives the rollout's cache-tier classification (Cache-A through
  Cache-D in the rollout-strategy notes).
- Quantifying the **eligibility rate** of a specific filter combo — what
  fraction of queries with the same `filters_eligibility_hash` actually
  reached the precompute path vs. fell back to live HogQL.
- Sizing the impact of an eligibility-gate change: count how many of today's
  rejections would become eligible under a relaxed gate (e.g. allowing more
  than one property filter, or non-`$host` keys).
- Confirming a deploy: after a runner code change that should not alter the
  cache shape, the per-hash query distribution should be stable.

Do not use this skill to chase per-CH-query latency or memory issues —
`filters_eligibility_hash` only exists on the application side. For
per-`query_type` tail latency or per-strategy memory, fall back to
`evaluating-web-analytics-performance` and Metabase.

## Required context

You will need:

- A Grafana MCP session that can reach the prod-us Loki datasource. UID:
  `P44D702D3E93867EC` (sole Loki datasource at the time of writing — confirm
  with `mcp__grafana__list_datasources` filtered to `type=loki`).
- Reasonable familiarity with LogQL's JSON parser and label aggregation.

If you don't yet have the datasource UID, `mcp__grafana__list_datasources`
returns the current list.

## Log line shapes

### `web_analytics_query` — the canonical request line

Emitted on every web analytics query, from
`products/web_analytics/backend/hogql_queries/web_analytics_query_runner.py`.

Stream labels: `{namespace="posthog", app="posthog-web-django"}` (HTTP path)
or `{namespace="posthog", app="posthog-worker-django"}` (digest/temporal
paths). Always `service_name="posthog.web_analytics.backend.hogql_queries.web_analytics_query_runner"`.

Relevant JSON fields:

| Field                      | Meaning                                                         |
| -------------------------- | --------------------------------------------------------------- |
| `event`                    | always `"web_analytics_query"`                                  |
| `team_id`                  | numeric team id                                                 |
| `organization_id`          | string UUID                                                     |
| `query_kind`               | `WebOverviewQuery`, `WebStatsTableQuery`, `WebGoalsQuery`, etc. |
| `query_strategy`           | runner sub-strategy (e.g. `stats_table_simple_breakdown`)       |
| `clickhouse_query_type`    | the `query_type` that lands in `system.query_log`               |
| `breakdown`                | the breakdown column (`Page`, `Browser`, ...) or `"none"`       |
| `has_conversion_goal`      | `"true"` / `"false"`                                            |
| `used_preaggregated`       | `"true"` (precompute path), `"false"` (live), `"unknown"`       |
| `duration_s`               | wall-clock duration in seconds (4 dp)                           |
| `error`, `error_type`      | error indication                                                |
| `filter_count`             | length of `properties` array                                    |
| `date_from`, `date_to`     | resolved date range strings                                     |
| `sampling_enabled`         | bool                                                            |
| `filters_eligibility_hash` | hex SHA-256 — **the join key**                                  |

### `lazy_computation.executed` — only when precompute path ran

Emitted from
`products/analytics_platform/backend/lazy_computation/lazy_computation_executor.py`.
Stream labels: `{namespace="posthog", app="posthog-worker-django"}`.

Relevant JSON fields:

| Field                                | Meaning                                                                                                                          |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| `event`                              | always `"lazy_computation.executed"`                                                                                             |
| `query_hash`                         | the framework's **post-build AST hash** (cache identity for the precompute job table) — distinct from `filters_eligibility_hash` |
| `table`                              | preagg table name (e.g. `web_overview_preaggregated`)                                                                            |
| `outcome`                            | `success` / `timeout` / `max_retries_exceeded` / `non_retryable_error`                                                           |
| `cache_state`                        | `hit` / `partial_hit` / `miss`                                                                                                   |
| `total_duration_ms`                  | wall clock                                                                                                                       |
| `jobs_created`, `jobs_waited_for`    | int                                                                                                                              |
| `time_range_start`, `time_range_end` | str                                                                                                                              |
| `time_range_days`                    | int                                                                                                                              |
| `filters_eligibility_hash`           | same value as on the corresponding `web_analytics_query` line — **the join key**                                                 |

The two log lines for the **same request** share `filters_eligibility_hash`.
The same logical filter combo across different requests also shares it.
That's the property the queries below rely on.

## Investigation workflow

1. **Frame the question precisely.** "How often does combo X run?" "Which
   team has the most repeat combos?" "What's the eligibility rate for combo
   X?" Each has a different aggregation shape.
2. **Pick the smallest window that fits.** 7 d is the rollout-strategy
   default; 14 d is the retention ceiling. Bigger windows trade query cost
   for tighter `q/key` estimates.
3. **Start broad, then narrow.** Top-N hashes per team is cheaper than
   detailed-shape extraction; once a hash is interesting, pull a sample of
   its log lines to inspect the underlying query.
4. **Cross-reference with the rollout-strategy notes** at
   `~/notes/work/posthog/web-analytics/investigations/` (especially
   `2026-05-25-web-analytics-precompute-rollout.md` and
   `2026-05-26-precompute-filter-distinctiveness.md`) — those define the
   Cache-A / Cache-B / Cache-C / Cache-D tier framework that this hash
   feeds.

## LogQL patterns

These are starting points. Adjust the window, team filter, and aggregation
to your question.

### Top N most-frequent filter combos for a team

```logql
topk(10,
  sum by (filters_eligibility_hash) (
    count_over_time(
      {namespace="posthog"}
        | json
        | event = "web_analytics_query"
        | team_id = "151290"
        [7d]
    )
  )
)
```

The `topk` numerator is the query count per hash. Sort the output and the
first row is the team's hottest cache key candidate. Repeat per team in a
shortlist; or aggregate cross-team for project-wide rankings.

### Per-team `q/key` over a 7-day window

```logql
sum by (team_id) (
  count_over_time({namespace="posthog"} | json | event = "web_analytics_query" [7d])
)
/
sum by (team_id) (
  count_values without () ("filters_eligibility_hash",
    {namespace="posthog"} | json | event = "web_analytics_query" [7d]
  )
)
```

Higher numbers indicate more amortization potential. The rollout-strategy
notes peg Cache-A at q/key ≥ 30, Cache-B at 3–30, Cache-C at 1.5–3,
Cache-D at < 1.5. This LogQL is the in-place version of the Metabase
`system.query_log` query in the methodology note — same math, Loki source.

### Eligibility rate for a specific hash

```logql
sum by (used_preaggregated) (
  count_over_time(
    {namespace="posthog"}
      | json
      | event = "web_analytics_query"
      | filters_eligibility_hash = "<hash>"
      [7d]
  )
)
```

Three buckets: `"true"` (precompute hit), `"false"` (live HogQL), `"unknown"`
(no response object — typically an error). The ratio `"true" / total` is
the realised eligibility for that combo; the gap to 1.0 is what an
eligibility-gate change would have to absorb.

### "Which combos would benefit if we relaxed the gate"

Two-step:

1. Filter to `used_preaggregated = "false"` and bucket by hash — these are the
   queries that didn't reach precompute.
2. For each hash with high count, drill into a sample line and look at the
   `query` JSON inside `web_analytics_query`'s metadata (the runner doesn't
   include the full query on this log line by default; if you need it, pull
   the corresponding `system.query_log` row by `query_id` from a logged
   `lazy_computation.executed` or by team + timestamp).

```logql
topk(20,
  sum by (filters_eligibility_hash) (
    count_over_time(
      {namespace="posthog"}
        | json
        | event = "web_analytics_query"
        | used_preaggregated = "false"
        [7d]
    )
  )
)
```

Pair the list with the eligibility-gate code path
(`check_common_eligibility` in
`products/web_analytics/backend/hogql_queries/web_lazy_precompute_common.py`)
to identify which gate the combo trips.

### Eligibility outcomes by family (which rejection reasons fire?)

The lazy paths emit `<family>_rejected` log lines with a `reason` field.
Tally those without needing the hash:

```logql
sum by (reason, app) (
  count_over_time(
    {namespace="posthog"}
      | json
      | event =~ "web_(overview|stats|stats_paths|stats_frustration|goals|vitals_paths)_(rejected|eligible)"
      [7d]
  )
)
```

Cross with `filters_eligibility_hash` to find the most common
`(reason, hash)` pairs — those are the rejection patterns that would unlock
the most queries if fixed.

### Joining `web_analytics_query` to `lazy_computation.executed`

For a specific request, both lines share `filters_eligibility_hash`. Pull
the pair like:

```logql
{namespace="posthog"}
  | json
  | event =~ "web_analytics_query|lazy_computation.executed"
  | filters_eligibility_hash = "<hash>"
  | line_format "{{.event}} | team={{.team_id}} | outcome={{.outcome}} | cache_state={{.cache_state}} | duration_ms={{.total_duration_ms}}{{.duration_s}}"
```

This is how you confirm a single request that reached precompute and what
its cache state was. For aggregate analysis, use the queries above instead.

### Hot combos across a sample of teams

When prioritizing the rollout cohort, you want the cross-team view:

```logql
topk(50,
  sum by (team_id, filters_eligibility_hash) (
    count_over_time({namespace="posthog"} | json | event = "web_analytics_query" [7d])
  )
)
```

Each row is `(team, combo) -> count`. Sort descending. The first few rows
are usually a handful of teams with a small number of dashboards hammered
on auto-refresh — they're the highest-leverage rollout candidates.

## Common gotchas

- **`filters_eligibility_hash` is missing on older log lines.** This field
  was added in PR
  [#60378](https://github.com/PostHog/posthog/pull/60378). Lines before that
  deploy lack it. Bound queries to a window after the deploy.
- **Property order is not canonicalized.** Two requests that send the same
  filter set in different orders hash to different keys. This is documented
  in `test_property_order_does_not_fragment_key` (the test name describes
  current behavior, not the desired one).
- **The hash includes resolved date strings.** Relative ranges like `-7d` are
  stable across calls; absolute timestamps are not — if a UI sends absolute
  dates, the hash will drift per-second.
- **Loki's retention is ~14 d**; don't promise longer windows than that
  source supports.
- **`lazy_computation.executed`'s `query_hash` is _not_ the same field** as
  `filters_eligibility_hash`. The framework's `query_hash` is the post-build
  AST hash (cache identity in the precompute job table); the eligibility
  hash is the input-side schema hash (logical cache key). Don't conflate
  them when joining.

## How to report

Keep the writeup concrete and small:

- a `topk` per-team or per-hash table for the window in question
- the explicit window, team filter, and event filter used
- a paragraph mapping each row to the rollout-strategy tier (Cache-A
  through Cache-D) — that's the language the rollout planning uses
- the rejection-reason tally if relevant

Cite the LogQL you ran so the analysis is reproducible. When something
seems off, sample a single line via `query_loki_logs` with a small
`limit` and inspect the JSON directly before drawing conclusions.

## Related skills and notes

- `monitoring-ingestion-pipeline` — Grafana MCP cheat-sheet (similar shape,
  different log streams).
- `evaluating-web-analytics-performance` — Metabase/ClickHouse-side
  analysis for per-`query_type` latency and per-team cost. Use that when
  the question is about CPU / memory / tail latency rather than
  eligibility / repeat-frequency.
- `~/notes/work/posthog/web-analytics/investigations/2026-05-25-web-analytics-precompute-rollout.md`
  — plan of record for the rollout, including cohort definitions
  (Cohort A through D) and the Cache-A / B / C / D tier framework.
- `~/notes/work/posthog/web-analytics/investigations/2026-05-26-precompute-filter-distinctiveness.md`
  — methodology behind `q/key`, including the cost model and the
  break-even-at-1.0 derivation.
