---
name: verifying-web-precompute-rollout
description: >-
  Verifies the web analytics dimensional precompute rollout
  (web_stats_dimensional_preaggregated / web_bounces_dimensional_preaggregated,
  populated by the scheduled web_dimensional_precompute Dagster job) for the
  enrolled teams. Confirms the job is running and each INSERT is memory-bounded,
  the Postgres PreaggregationJob rows are healthy, the new ClickHouse tables are
  populated, the teams actually run web analytics queries, and the output matches
  the v2 pre-aggregation tables (web_pre_aggregated_stats / web_pre_aggregated_bounces).
  Use after the rollout merges/deploys, or when asked to verify/validate web
  precompute, check dimensional precompute, compare new vs v2 web pre-aggregation,
  or confirm a team's web analytics pre-agg usage. Runs read-only via Metabase
  (system.query_log + ClickHouse/Postgres reads) using `hogli metabase:query`.
---

# Verifying the web dimensional precompute rollout

The scheduled `web_dimensional_precompute` Dagster job populates two fixed-dimension
tables — `web_stats_dimensional_preaggregated` and `web_bounces_dimensional_preaggregated`
— for an allowlist of teams (default `DEFAULT_ROLLOUT_TEAM_IDS = [2, 55348]` on Cloud,
overridable via `WEB_DIMENSIONAL_PRECOMPUTE_TEAM_IDS`). It drives the precomputation
framework: a rolling 90-day window, chunked to **one UTC day per INSERT**, with a long
TTL on old days so they compute once. This skill confirms it's working in production and
agrees with v2.

Run the checks in order; stop early if an upstream one fails (no jobs → nothing to compare).

## Setup

Authentication and `hogli metabase:query` usage are covered by the
`query-clickhouse-via-metabase` skill — read it first. In short:

- The user runs `hogli metabase:login --region us` once (browser SSO; agents can't).
  HeyGen (team 55348) and the dogfood project (team 2) are US, so use `--region us`.
- Discover the current DB IDs (they are not stable):
  `hogli metabase:databases --region us`. You need two: the **ClickHouse** DB (query +
  data on US) and the **Postgres** app DB.

Set the team list you're verifying once: `TEAMS = (2, 55348)` (or whatever the env override is).

## Check 1 — the precompute INSERTs are running and memory-bounded

Each `ensure_precomputed` INSERT is tagged `query_type` = `web_stats_dimensional_insert`
or `web_bounces_dimensional_insert`. This is the single most useful check: it proves the
job runs AND that each INSERT scans ~one day (bounded `read_bytes` — the whole point of
1-day chunking).

```sql
-- ClickHouse DB, last 24h
SELECT
    JSONExtractInt(log_comment, 'team_id') AS team_id,
    JSONExtractString(log_comment, 'query_type') AS query_type,
    count() AS inserts,
    round(quantile(0.95)(query_duration_ms)) AS p95_ms,
    formatReadableSize(max(read_bytes)) AS max_scan,
    formatReadableSize(max(memory_usage)) AS peak_mem,
    countIf(exception_code != 0) AS failures
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 1 DAY
    AND type IN ('QueryFinish', 'ExceptionWhileProcessing')
    AND JSONExtractString(log_comment, 'query_type') LIKE 'web_%_dimensional_insert'
    AND JSONExtractInt(log_comment, 'team_id') IN (2, 55348)
GROUP BY team_id, query_type
ORDER BY team_id, query_type
```

**Expect:** rows for each team×table; `max_scan`/`peak_mem` bounded (roughly a single
day of that team's raw sessions+events — for a high-volume team it should still be modest,
not tens of GB); `failures = 0`. A large `max_scan` means a chunk covered more than a day
— check `WEB_DIMENSIONAL_PRECOMPUTE_CHUNK_DAYS` (should be 1). To see the heaviest
individual inserts, drop the `GROUP BY` and `ORDER BY read_bytes DESC LIMIT 20`.

## Check 2 — PreaggregationJob health (Postgres)

The framework tracks every window as a row in `analytics_platform_preaggregationjob`
(verify the name via `information_schema.tables WHERE table_name ILIKE '%preaggregation%'`
if the query errors).

```sql
-- Postgres app DB
SELECT team_id, status, count(*) AS jobs, max(computed_at) AS latest_computed_at
FROM analytics_platform_preaggregationjob
WHERE team_id IN (2, 55348)
GROUP BY team_id, status
ORDER BY team_id, status
```

**Expect:** mostly `ready`, a recent `latest_computed_at` (within the last hour for the
hourly schedule), few/no `failed`. Inspect failures:

```sql
SELECT team_id, time_range_start, time_range_end, error, updated_at
FROM analytics_platform_preaggregationjob
WHERE team_id IN (2, 55348) AND status = 'failed'
ORDER BY updated_at DESC
LIMIT 20
```

## Check 3 — the new tables are populated

```sql
-- ClickHouse DB; repeat for web_bounces_dimensional_preaggregated
SELECT
    team_id,
    count() AS rows,
    uniqExact(job_id) AS jobs,
    min(period_bucket) AS earliest,
    max(period_bucket) AS latest
FROM web_stats_dimensional_preaggregated
WHERE team_id IN (2, 55348)
GROUP BY team_id
```

**Expect:** non-zero rows; `earliest`/`latest` spanning roughly the rolling 90-day window;
`latest` close to now. (Rows are keyed by `job_id` and expire via TTL, so counts grow with
dimensionality, not a concern by themselves.)

## Check 4 — the teams actually run web analytics queries

Confirms the comparison is meaningful (a team with no web analytics traffic isn't worth
comparing) and shows which pre-agg tables their reads currently hit.

```sql
-- ClickHouse DB, last 7d
SELECT
    JSONExtractInt(log_comment, 'team_id') AS team_id,
    countIf(query LIKE '%web_pre_aggregated_%') AS v2_preagg_reads,
    countIf(query LIKE '%_preaggregated%' AND query NOT LIKE '%dimensional%') AS lazy_preagg_reads,
    countIf(query LIKE '%dimensional_preaggregated%') AS dimensional_reads,
    count() AS web_analytics_queries
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 7 DAY
    AND type = 'QueryFinish'
    AND is_initial_query
    AND JSONExtractString(log_comment, 'product') = 'web_analytics'
    AND JSONExtractInt(log_comment, 'team_id') IN (2, 55348)
GROUP BY team_id
```

**Expect:** `web_analytics_queries` > 0 for each team. `dimensional_reads` will be 0 until
the read path is wired (this PR is write-path only) — that's expected.

## Check 5 — parity vs v2 (spot check)

The authoritative parity proof is the offline test suite
(`products/web_analytics/backend/hogql_queries/test/test_web_dimensional_precompute_parity.py`).
In production, do a coarse spot check on a single fully-computed day.

Caveat: the dimensional table is keyed by `job_id`, so re-computed windows produce multiple
rows for the same logical day — a naive `sumMerge` over all rows double-counts. Pick a day
the job computed exactly once (so the comparison is clean):

```sql
-- ClickHouse DB. Replace :day with a recent UTC date, e.g. today - 3.
-- 1. Confirm the day was computed once for the team (expect 1).
SELECT uniqExact(job_id)
FROM web_stats_dimensional_preaggregated
WHERE team_id = 55348 AND toDate(period_bucket) = toDate(:day)

-- 2. If 1, compare totals to v2 for that day.
SELECT 'new' AS src, uniqMerge(persons_uniq_state) AS persons, sumMerge(pageviews_count_state) AS views
FROM web_stats_dimensional_preaggregated
WHERE team_id = 55348 AND toDate(period_bucket) = toDate(:day)
UNION ALL
SELECT 'v2', uniqMerge(persons_uniq_state), sumMerge(pageviews_count_state)
FROM web_pre_aggregated_stats
WHERE team_id = 55348 AND toDate(period_bucket) = toDate(:day)
```

**Expect:** `views` match closely; `persons` within HLL tolerance (`uniq` is ~0.5%
approximate). If the day shows >1 distinct `job_id`, either pick another day or resolve the
fresh `job_id`s from `analytics_platform_preaggregationjob` (READY, covering that window) and
filter the dimensional read to `job_id IN (...)` — that mirrors how the read path will dedup.
Small divergences on session-derived dimensions (region_name, bounce/duration) are expected
and documented in the parity test; the metrics above are event-derived and should match.

## Red flags

- **No `web_%_dimensional_insert` rows in query_log** → the schedule isn't running, the
  allowlist is empty, or `is_cloud()` gated it out. Check the Dagster schedule status and
  `WEB_DIMENSIONAL_PRECOMPUTE_TEAM_IDS`.
- **Large `max_scan`/`peak_mem` on the inserts** → a chunk spanned more than a day; confirm
  `WEB_DIMENSIONAL_PRECOMPUTE_CHUNK_DAYS=1`.
- **Many `failed` PreaggregationJob rows** → read the `error`; a ClickHouse type/identifier
  error means the HogQL template broke against the team's data (e.g. a session-version field).
- **Empty tables but READY jobs** → the INSERT ran but produced no rows; check the team has
  `$pageview`/`$screen` events with `$session_id` in the window.
