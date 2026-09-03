# Telemetry sources on Aurora PostgreSQL beyond pg_stat_*

Research (2026-08) into what Aurora PostgreSQL 15/16/17 exposes that could give
pgcollector more than the usual `pg_stat_*` views, ranked by value. Our fleet runs Aurora
`aurora-postgresql15/16/17` (some 18), with Performance Insights enabled
(7-day retention), `pg_stat_statements` (`max=10000`, `track=all`),
`auto_explain` on some clusters (json, 1% sample), `log_min_duration_sample=1s`
at 1% and `log_lock_waits=on`.

## Not available on Aurora (don't plan around them)

`pg_stat_monitor`, `pg_stat_kcache`, `pg_qualstats`, `pg_wait_sampling`,
`pageinspect`, `pg_walinspect`. The first three are what community tools use
for latency histograms, per-query CPU, and predicate stats; none are on the
[Aurora extension list](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraPostgreSQLReleaseNotes/AuroraPostgreSQL.Extensions.html).

## Tier 1 — free, built-in, high value

### `aurora_stat_statements(showtext)` — drop-in upgrade of `query_stats`

All `pg_stat_statements` columns plus 11 more (APG 14.9+/15.4+; peak-memory
columns 14.12+/15.7+/16.3+):

* `storage_blks_read`, `storage_blk_read_time` — blocks/time read from **Aurora
  storage** (vs. `shared_blks_read`, which on Aurora includes OS cache). This is
  the real "did this query hit the network" signal.
* `orcache_blks_hit`, `orcache_blk_read_time` — Optimized Reads tiered cache.
* `total/min/max_exec_peakmem`, `*_plan_peakmem` — **peak memory per query**.
  Most monitoring tools lack this; it's the direct answer to "which query is
  blowing `work_mem`".

Same `queryid`, same reset function. Plan: `query_stats` detects
`aurora_version()` and switches its SQL; the sink just gains columns.

### `aurora_stat_plans(showtext)` + `aurora_stat_activity()` — per-plan stats

APG 14.10+/15.5+, **on by default** (`aurora_compute_plan_id`), no
`auto_explain` overhead. Every `pg_stat_statements` row split by `planid`, with
`explain_plan` text, `plan_type` (`estimate`/`actual`), `plan_captured_time`.
`aurora_stat_activity()` = `pg_stat_activity` + `plan_id`, so activity samples
can be grouped by (query_id, plan_id).

Commercial tools expose this as "plan statistics"; we get it cheaply, plus
we can store *every* plan variant and diff them (plan flips). Limited to
`pg_stat_statements.max` plans.

### `aurora_stat_system_waits()` / `aurora_stat_backend_waits(pid)` — wait *time*

Cumulative `waits` and `wait_time` (ms) per wait event, instance-wide and per
backend. Our `activity_samples` only *sample* wait events every
10s; this gives exact counts and durations — e.g. total ms spent in
`IO:XactSync` or `Lock:transactionid` per minute, and per-session wait
profiles for the "interesting" backends we already record. Join with
`aurora_stat_wait_type()` / `aurora_stat_wait_event()` for names.
`aurora_wait_report(seconds)` (needs `aurora_stat_utils`) is the same thing
pre-diffed; we do our own diffing so we don't need it.

### `aurora_stat_get_db_commit_latency(oid)` and `aurora_stat_dml_activity(oid)`

Per-database cumulative **commit latency** (µs; what CloudWatch's CommitLatency
is computed from) and per-database SELECT/INSERT/UPDATE/DELETE **counts and
latency**. Cheap deltas, one row per database per minute. Gives "average
latency per statement class per database" that `pg_stat_database` cannot.
Reset by `pg_stat_reset`, so reuse `stats_reset` from `pg_stat_database`.

### `aurora_replica_status()`

Per-replica replay lag (ms), oldest read-view xid, CPU, current LSN — this is
the replication view on Aurora, since `pg_stat_replication` is empty.
Replaces the community `replication` collector on Aurora.

### `pg_proctab` — OS stats from SQL (no CloudWatch needed)

Supported on Aurora. `pg_cputime()`, `pg_loadavg()`, `pg_memusage()`,
`pg_diskusage()`, and **`pg_proctab()` per process** (utime/stime/RSS per
backend). Per-backend CPU is what `pg_stat_kcache` would give; joined to `pg_stat_activity` it attributes CPU to queries/users.
Cheaper and lower-latency than CloudWatch for host metrics.

### `aurora_stat_memctx_usage()`

Memory-context usage across backends (community PG only has this for your own
backend until 18). Catches the one connection eating 8 GB.

## Tier 2 — worth having, opt-in or expensive

### Performance Insights API (`pi:GetResourceMetrics`, `DescribeDimensionKeys`)

Already enabled on every cluster. Gives **DB load (average active sessions)
per second, decomposed by `db.sql_tokenized` × `db.wait_event`**, plus per-SQL
counters (`calls_per_sec`, `rows_per_call`, `blks_hit_per_sec`, …) and 7 days
of history. The valuable part is the *per-query wait profile*, which nothing
in-database provides. Costs API calls (rate-limited), needs
`pi:*` on the IRSA role, and its SQL ids (`db.sql_tokenized.id`) are AWS's
own hash, not `queryid` — join on normalized text. Still no per-call latency
quantiles.

### `pgstattuple` — exact bloat

`pgstattuple_approx(rel)` (heap, cheap-ish) and `pgstatindex` for B-trees give
real dead-tuple %, free space, leaf fragmentation, versus the usual
statistical estimate. Run weekly on the reader for tables over N GB; never on
the writer during business hours.

### `pg_buffercache`

What's in `shared_buffers` by relation. PG16+ `pg_buffercache_summary()` and
`pg_buffercache_usage_counts()` are cheap; per-relation aggregation scans every
buffer (fine every 10m on the reader). Answers "is my hot table actually
cached".

### `hypopg` — validate index recommendations

Hypothetical indexes + `EXPLAIN` on the reader: propose an index, see the plan
and cost change without building it. Index advisors usually model this
offline; we can ask the real planner. Foundation for our own advisor (phase 5).

### `log_fdw` — read logs via SQL

`list_postgres_log_files()` / `create_foreign_table_for_log_file()`; with
`log_destination=csvlog` the rows are structured. Functions are owned by
`rds_superuser` and must be granted. An alternative to the RDS
`DownloadDBLogFilePortion` API for the phase-4 log collector — no AWS SDK, same
credentials — but reads only the current instance's files and doubles log
storage. Decide in phase 4; the API path is probably simpler for CloudWatch-
exported logs (`enabled_cloudwatch_logs_exports = ["postgresql"]` is already on).

### `pg_freespacemap`, `pg_visibility`

Free-space and all-visible/all-frozen fractions per relation → vacuum
effectiveness and index-only-scan eligibility. Full-relation scans; opt-in,
reader only, large tables weekly.

### `aurora_stat_logical_wal_cache()`, `aurora_stat_optimized_reads_cache()`

Only if logical replication (`pglogical` is loaded on some clusters) or
Optimized Reads instances are in play. Cheap, cluster-scope, add when needed.

## Tier 3 — not telemetry / skip

`pgaudit` (audit, not perf), `rds_tools`, `pg_tle`, `pg_cron` (could schedule
`pgstattuple` in-database instead of from the collector — not needed),
`plprofiler` (on-demand PL/pgSQL profiling; niche), `apg_plan_mgmt` (plan
pinning; a remediation tool rather than a stat source, but its
`dba_plans` view could be read if it's ever enabled).

## Status

Tier 1 is implemented (`collectors/aurora_*.yaml`, `system_*.yaml`,
`backend_cpu.yaml`, `src/collectors/aurora_plans.rs`, Aurora paths in
`query_stats` and `activity_samples`). Validated against stub functions with
the documented column shapes (`test/aurora_stubs.sql`) and a real
`pg_proctab`; the first run against an actual Aurora cluster is still owed.

## Recommended order

1. **Aurora variants of existing collectors** (cheap, immediate): `query_stats`
   → `aurora_stat_statements`; new `aurora_waits` (system + backend);
   `aurora_db_latency` (commit latency + DML activity); `aurora_replica_status`.
   All gated on `aurora_version()` existing.
2. **`aurora_plans`**: per-plan stats + plan text into `ts_query_plan_stats` /
   `cur_query_plans`; `plan_id` added to `activity_samples` via
   `aurora_stat_activity()`.
3. **`pg_proctab`** system + per-backend CPU (needs `CREATE EXTENSION`).
4. Phase 4 logs (real latency quantiles) — the configured
   `log_min_duration_sample`/`auto_explain` already produce the data.
5. Opt-in heavy collectors: `pgstattuple`, `pg_buffercache`, `pg_visibility`.
6. `hypopg`-backed index validation once the schema collector exists.
7. Performance Insights ingestion, if the per-query wait profile proves
   valuable enough to justify the API plumbing.

Sources: [Aurora functions reference](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Appendix.AuroraPostgreSQL.Functions.html),
[aurora_stat_statements](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora_stat_statements.html),
[aurora_stat_plans](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora_stat_plans.html),
[aurora_stat_backend_waits](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora_stat_backend_waits.html),
[aurora_stat_dml_activity](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora_stat_dml_activity.html),
[aurora_stat_get_db_commit_latency](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora_stat_get_db_commit_latency.html),
[log_fdw](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_PostgreSQL.Extensions.log_fdw.html),
[Performance Insights API](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PerfInsights.API.html),
[pg_stat_monitor not on Aurora (re:Post)](https://repost.aws/questions/QUGNBveStSTx66XIIN9IrT-w/add-support-for-postgresql-pg-stat-monitor-extension-in-rds-aurora).
