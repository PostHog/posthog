-- Notebooks ClickHouse observability — query_log_archive query pack.
--
-- Every notebook data-plane query is tagged `product=notebooks, feature=query`
-- (sql_v2_data_plane.py wraps both enqueue paths in tags_context; the tags ride the
-- Celery task argument on the inline path and the Temporal activity's context on the
-- materialize path), so `lc_product = 'notebooks'` is the one filter that scopes
-- everything below.
--
-- Run these through the internal Metabase against "PostHog ClickHouse PROD <REGION>
-- Data Tier" (see the query-clickhouse-via-metabase skill):
--   hogli metabase:login --region us
--   hogli metabase:databases --region us
--   hogli metabase:query --region us --database-id <id> < this-file
--
-- Reading notes that apply throughout:
--   * `is_initial_query` drops the per-shard sub-queries a distributed query fans out
--     into. The initiator row already sums read_bytes/read_rows across replicas, so
--     without this filter every cost number roughly doubles.
--   * `query_log_archive` is a Distributed read table pointing at the OPS cluster and is
--     readable from any cluster. Always bound `event_date` — it is partitioned by month.
--   * Rows are QueryFinish / ExceptionBeforeStart / ExceptionWhileProcessing only
--     (the MV filters out QueryStart), so one row is one finished query attempt.
--   * The two write modes are distinguishable by `query_kind`: 'Select' is the
--     phase-1 worker-relay stream, 'Insert' is the phase-2 CH-writes
--     `INSERT INTO FUNCTION s3`. This matters for result columns — see query 4.
--   * `lc_temporal__attempt` is the Temporal retry attempt, so re-executions of the
--     same materialization are visible and attributable.


-- ---------------------------------------------------------------------------
-- 1. Headline: notebook query volume, latency, and ClickHouse cost per hour.
--    This is the panel to watch during a rollout.
-- ---------------------------------------------------------------------------
SELECT
    toStartOfHour(event_time)                        AS hour,
    count()                                          AS queries,
    countIf(exception_code != 0)                     AS errors,
    round(quantile(0.50)(query_duration_ms))         AS p50_ms,
    round(quantile(0.95)(query_duration_ms))         AS p95_ms,
    round(quantile(0.99)(query_duration_ms))         AS p99_ms,
    formatReadableSize(sum(read_bytes))              AS scanned_total,
    formatReadableSize(quantile(0.95)(read_bytes))   AS scanned_p95,
    formatReadableSize(sum(result_bytes))            AS returned_total,
    sum(result_rows)                                 AS rows_returned,
    formatReadableSize(quantile(0.95)(memory_usage)) AS memory_p95
FROM query_log_archive
WHERE event_date >= today() - 7
  AND lc_product = 'notebooks'
  AND is_initial_query
GROUP BY hour
ORDER BY hour;


-- ---------------------------------------------------------------------------
-- 2. Rollout verification: which path, pool, and ClickHouse identity is actually
--    serving notebook queries. The design doc's phase-1/phase-2 prerequisites
--    (dedicated `notebooks` CH user, offline pool) fail *open* and silently — this
--    is the ClickHouse-side confirmation that they engaged.
--      user           — 'notebooks' once the dedicated CH user is provisioned, else the default
--      lc_workload    — 'offline' once CLICKHOUSE_OFFLINE_CLUSTER_HOST is set on the worker fleet
--      query_kind     — Select = worker relay (phase 1); Insert = CH writes (phase 2)
-- ---------------------------------------------------------------------------
SELECT
    toStartOfHour(event_time)   AS hour,
    user                        AS ch_user,
    lc_workload                 AS workload,
    query_kind,
    lc_temporal__workflow_type  AS workflow,
    count()                     AS queries,
    countIf(exception_code != 0) AS errors
FROM query_log_archive
WHERE event_date >= today() - 7
  AND lc_product = 'notebooks'
  AND is_initial_query
GROUP BY hour, ch_user, workload, query_kind, workflow
ORDER BY hour, queries DESC;


-- ---------------------------------------------------------------------------
-- 3. Failures by ClickHouse exception code. The budget codes the materialize path
--    treats as terminal: 158 TOO_MANY_ROWS, 159 TIMEOUT_EXCEEDED, 160 TOO_SLOW,
--    241 MEMORY_LIMIT_EXCEEDED, 307 TOO_MANY_BYTES, 396 TOO_MANY_ROWS_OR_BYTES
--    (the result-bytes cap). 202 TOO_MANY_SIMULTANEOUS_QUERIES means the cluster
--    or the notebooks user's own quota is saturated, not that the query is bad.
-- ---------------------------------------------------------------------------
SELECT
    exception_code,
    errorCodeToName(exception_code)          AS exception_name,
    count()                                  AS occurrences,
    uniq(team_id)                            AS teams_affected,
    round(avg(query_duration_ms))            AS avg_ms_before_failing,
    formatReadableSize(sum(read_bytes))      AS wasted_scan,
    max(event_time)                          AS last_seen
FROM query_log_archive
WHERE event_date >= today() - 7
  AND lc_product = 'notebooks'
  AND is_initial_query
  AND exception_code != 0
GROUP BY exception_code
ORDER BY occurrences DESC;


-- ---------------------------------------------------------------------------
-- 4. Bytes and rows delivered to the user, split by write mode.
--    The two modes populate different columns and averaging them together is wrong:
--      * Select (worker relay): the frame leaves CH as a result set  -> result_bytes / result_rows
--      * Insert (CH writes s3): the frame is written to S3 by CH     -> written_rows, and
--        ProfileEvents['WriteBufferFromS3Bytes'] for the bytes actually pushed to S3
--        (result_bytes is ~0 for an INSERT).
--    `posthog_notebooks_frame_object_bytes` is the mode-independent equivalent, but
--    only on the success path — this query also sees the runs that died.
-- ---------------------------------------------------------------------------
SELECT
    query_kind,
    count()                                                       AS queries,
    formatReadableSize(quantile(0.95)(result_bytes))              AS result_bytes_p95,
    quantile(0.95)(result_rows)                                   AS result_rows_p95,
    quantile(0.95)(written_rows)                                  AS written_rows_p95,
    formatReadableSize(quantile(0.95)(ProfileEvents_WriteBufferFromS3Bytes)) AS s3_written_p95,
    formatReadableSize(sum(ProfileEvents_WriteBufferFromS3Bytes)) AS s3_written_total
FROM query_log_archive
WHERE event_date >= today() - 7
  AND lc_product = 'notebooks'
  AND is_initial_query
GROUP BY query_kind;


-- ---------------------------------------------------------------------------
-- 5. Parallel notebook queries per team — exact concurrency, not a rejection count.
--    Prometheus only counts limiter *rejections*; this reconstructs actual occupancy
--    by replaying each query as a +1 at its start and a -1 at its end and taking a
--    running sum. Compare the peak against the design doc's per-team ceiling of 2
--    (MATERIALIZE_PER_TEAM_CONCURRENCY) and global 10.
--    Swap `team_id` for `lc_user_id` to get the per-user view.
--    Note: there is no notebook_short_id in the query tags today, so a per-notebook
--    breakdown is not possible — see the gaps list in sql_v2_observability.md.
-- ---------------------------------------------------------------------------
WITH notebook_queries AS (
    SELECT
        team_id,
        query_start_time_microseconds AS started,
        query_start_time_microseconds + toIntervalMillisecond(query_duration_ms) AS ended
    FROM query_log_archive
    WHERE event_date >= today() - 1
      AND lc_product = 'notebooks'
      AND is_initial_query
),
edges AS (
    SELECT team_id, started AS t,  1 AS delta FROM notebook_queries
    UNION ALL
    SELECT team_id, ended   AS t, -1 AS delta FROM notebook_queries
)
SELECT
    team_id,
    max(running) AS peak_concurrent_queries
FROM (
    SELECT
        team_id,
        t,
        sum(delta) OVER (
            PARTITION BY team_id ORDER BY t
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS running
    FROM edges
)
GROUP BY team_id
ORDER BY peak_concurrent_queries DESC
LIMIT 20;


-- ---------------------------------------------------------------------------
-- 6. The whales: most expensive individual notebook queries.
--    `lc_client_query_id` is the data-plane query_id, so a row here joins straight to
--    the `notebook_frame_materialized` structured log and to the Temporal workflow.
--    NB: the `query` column is user-authored SQL — internal triage only, never paste
--    it into a public PR or issue.
-- ---------------------------------------------------------------------------
SELECT
    event_time,
    team_id,
    lc_user_id                          AS user_id,
    lc_client_query_id                  AS data_plane_query_id,
    lc_temporal__attempt                AS temporal_attempt,
    query_duration_ms,
    formatReadableSize(read_bytes)      AS scanned,
    read_rows,
    formatReadableSize(memory_usage)    AS memory,
    peak_threads_usage,
    exception_code,
    substring(query, 1, 200)            AS query_head
FROM query_log_archive
WHERE event_date >= today() - 1
  AND lc_product = 'notebooks'
  AND is_initial_query
ORDER BY read_bytes DESC
LIMIT 25;


-- ---------------------------------------------------------------------------
-- 7. Retry amplification. A deterministically-failing whale can re-execute up to 10
--    times (the workflow's maximum_attempts), re-scanning on every attempt. Any row
--    here with attempts > 1 is ClickHouse work spent on a query that was already
--    doomed — the terminal-vs-retryable error classification is what bounds it.
-- ---------------------------------------------------------------------------
SELECT
    lc_client_query_id                       AS data_plane_query_id,
    team_id,
    max(lc_temporal__attempt)                AS attempts,
    count()                                  AS ch_executions,
    formatReadableSize(sum(read_bytes))      AS total_scanned,
    sum(query_duration_ms)                   AS total_ms,
    groupUniqArray(exception_code)           AS exception_codes
FROM query_log_archive
WHERE event_date >= today() - 1
  AND lc_product = 'notebooks'
  AND is_initial_query
  AND lc_temporal__workflow_type = 'notebook-frame-materialize'
GROUP BY data_plane_query_id, team_id
HAVING attempts > 1
ORDER BY total_scanned DESC
LIMIT 25;


-- ---------------------------------------------------------------------------
-- 8. Notebooks' share of the offline pool — the "am I hurting batch exports?"
--    question the design doc's pool-isolation decision rests on.
-- ---------------------------------------------------------------------------
SELECT
    toStartOfHour(event_time)                AS hour,
    if(lc_product = 'notebooks', 'notebooks', 'other offline work') AS bucket,
    count()                                  AS queries,
    formatReadableSize(sum(read_bytes))      AS scanned,
    round(sum(query_duration_ms) / 1000)     AS ch_seconds,
    round(sum(ProfileEvents_OSCPUVirtualTimeMicroseconds) / 1e6) AS cpu_seconds
FROM query_log_archive
WHERE event_date >= today() - 3
  AND lc_workload = 'offline'
  AND is_initial_query
GROUP BY hour, bucket
ORDER BY hour, bucket;
