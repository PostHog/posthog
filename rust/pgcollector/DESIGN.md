# pgcollector — design

A self-owned Postgres telemetry collector. Scrapes telemetry
from a fleet of RDS/Aurora instances and writes it to a Postgres stats database.
An API / UI / MCP server will sit on top of the stats DB later; this document
covers only the collector and its storage schema.

**Goal:** every stat we collect, and how it is aggregated, is a change we control.
Adding a column or a whole new stat source should be a two-minute edit, not a
feature request.

Decisions already made:

| Decision | Choice |
|---|---|
| Language | Rust |
| Storage | Postgres, native range partitioning by time, short retention (days–weeks) |
| Targets | RDS / Aurora Postgres almost exclusively |
| Deployment | One long-running binary per environment, many target servers per binary |

---

## 1. Architecture

```text
┌──────────────┐  pg_stat_* / catalogs / logs  ┌──────────────────────────────┐  Snapshot  ┌────────────┐
│ RDS / Aurora │ ◄──────────────────────────── │  pgcollector                 │ ─────────► │ Sink       │
│ (N servers)  │                                │  scheduler + collector mods  │            │ (stats PG) │
└──────────────┘                                └──────────────────────────────┘            └────────────┘
```

* **Scheduler** — for each configured server, opens a small connection pool
  (2–3 conns) and drives every enabled collector on its own tick. Ticks are
  aligned to wall-clock boundaries (`:00`, `:10`, …) so samples from different
  servers line up.
* **Collector** — produces a `Snapshot` (batch of rows + identity + timestamp)
  each tick. Two kinds, see §2.
* **Sink** — trait. First implementation writes straight to the stats
  Postgres. Future: HTTP-to-ingest-API, file/S3 for replay. Collection code
  never knows where data goes.

The collector holds **per-collector, per-server in-memory `State`** so cumulative
sources (`pg_stat_statements`, `pg_stat_user_tables`, …) are turned into deltas
without reading back from storage.

## 2. Two tiers of collectors

### Tier A — declarative SQL collectors (`collectors/*.yaml`)

Most stats are "run this query every N seconds, key by these columns, diff these
counters". Those are YAML files loaded at startup — no code:

```yaml
name: table_stats
interval: 10m
scope: database          # cluster = once per server | database = once per db
min_pg_version: 12
kind: cumulative         # cumulative | gauge | snapshot
key: [schemaname, relname]
query: |
  SELECT schemaname, relname, seq_scan, seq_tup_read, idx_scan, idx_tup_fetch,
         n_tup_ins, n_tup_upd, n_tup_del, n_tup_hot_upd,
         n_live_tup, n_dead_tup, n_mod_since_analyze,
         vacuum_count, autovacuum_count, analyze_count, autoanalyze_count,
         last_vacuum, last_autovacuum, last_analyze, last_autoanalyze
  FROM pg_stat_user_tables
```

`kind` tells the pipeline what to do with the rows:

| kind | behaviour |
|---|---|
| `gauge` | write rows as-is with `collected_at` |
| `cumulative` | numeric non-key columns are diffed against the previous tick per `key`; negative delta or changed `stats_reset` ⇒ drop tick, re-baseline; non-numeric columns pass through |
| `snapshot` | rows are a full picture of an entity set; sink upserts into a current table and records a content hash so diffs become `events` |

The sink derives the target table (`ts_<name>` / `cur_<name>`) from the query's
result columns and adds missing columns (`ALTER TABLE … ADD COLUMN … NULL`) on
first sight. **Adding a stat = adding a column to the SELECT.**

### Tier B — code collectors (`src/collectors/*.rs`)

For the few sources that need real logic. Same trait:

```rust
#[async_trait]
pub trait Collector: Send + Sync {
    fn name(&self) -> &str;
    fn interval(&self) -> Duration;
    fn scope(&self) -> Scope;                 // Cluster | Database
    fn min_pg_version(&self) -> u32 { 120000 }
    async fn collect(&self, cx: &CollectCtx, prev: Option<&State>) -> Result<(Snapshot, State)>;
}
```

Planned Tier B collectors:

* **`query_stats`** — `pg_stat_statements` deltas (§4).
* (`activity_samples`, `activity_sessions`, `lock_waits` turned out to be
  expressible in SQL — they are Tier A YAML.)
* **`schema`** — catalog snapshot + diff → schema-change events.
* **`vacuum_needed`** — derived: per-table dead tuples vs. effective autovacuum
  threshold (reloptions ⊕ GUCs), `age(relfrozenxid)` vs `autovacuum_freeze_max_age`.
* **`logs`** — RDS log tailing (phase 4).
* **`explain`** — plan collection (phase 4).
* **`system`** — CloudWatch metrics (phase 4).

## 3. Catalog of what we collect

| Interval | Module | Tier | Source |
|---|---|---|---|
| 10s | activity samples | A | `pg_stat_activity` — counts by (state, wait_event_type, wait_event, query_id, usename, datname); raw rows kept for sessions > 5s or blocked |
| 10s | lock waits | A | `pg_locks` joined to `pg_blocking_pids()`; only emits when blocking exists |
| 60s | query stats | B | `pg_stat_statements` deltas keyed by (queryid, userid, dbid, toplevel) |
| 60s | database stats | A | `pg_stat_database` + `age(datfrozenxid)` |
| 60s | bgwriter / checkpointer | A | `pg_stat_bgwriter`; `pg_stat_checkpointer` on 17+ |
| 60s | wal | A | `pg_stat_wal` (14+) |
| 60s | io | A | `pg_stat_io` (16+) |
| 60s | archiver | A | `pg_stat_archiver` |
| 60s | replication | A | `pg_stat_replication`, `pg_replication_slots`, `pg_stat_wal_receiver`, recovery status / replay lag (Aurora: `aurora_replica_status()` when present) |
| 60s | vacuum progress | A | `pg_stat_progress_vacuum` / `_analyze` / `_cluster` / `_create_index` |
| 10m | table stats | A | `pg_stat_user_tables`, `pg_statio_user_tables` |
| 10m | index stats | A | `pg_stat_user_indexes`, `pg_statio_user_indexes` |
| 10m | relation sizes | A | `pg_total_relation_size` etc., TOAST, bloat estimate (heuristic, no pgstattuple) |
| 10m | vacuum needed | B | derived from table stats + settings |
| 1h | schema | B | `pg_class`, `pg_attribute`, `pg_index`, `pg_constraint`, partitions, view defs |
| 1h | settings | A (snapshot) | `pg_settings` |
| 1h | extensions / roles / version | A (snapshot) | `pg_extension`, `pg_roles`, `version()` |
| 60s | query plans (Aurora) | B | `aurora_stat_plans` — pgss split by `planid`, plan text into `cur_query_plans` |
| 60s | system waits (Aurora) | A | `aurora_stat_system_waits` — exact wait counts/time per event |
| 10s | backend waits (Aurora) | A | `aurora_stat_backend_waits(pid)` for non-idle backends, top 5 events |
| 60s | db latency (Aurora) | A | `aurora_stat_get_db_commit_latency`, `aurora_stat_dml_activity` |
| 60s | replica status (Aurora) | A | `aurora_replica_status()` — lag, replay latency, oldest read view |
| 60s | memory contexts (Aurora) | A | `aurora_stat_memctx_usage()` — backends > 64 MB |
| 60s | system cpu / memory / disk | A | `pg_proctab`: `pg_cputime`, `pg_memusage`, `pg_loadavg`, `pg_diskusage` |
| 60s | backend cpu | A | `pg_proctab()` per pid joined to `pg_stat_activity` |
| 30s | logs | B | CloudWatch Logs (RDS) or files: `ts_query_durations` (latency quantiles), `ts_log_plans` (auto_explain), `ts_autovacuum_runs`, `ts_checkpoints`, `ts_temp_files`, `ts_log_errors`, `ts_logs` counts, deadlock/lock-wait/cancel events |

On Aurora, `query_stats` reads `aurora_stat_statements` (adds Aurora-storage I/O
and per-query peak memory) and `activity_samples` reads `aurora_stat_activity`
(adds `plan_id`). Collectors declare `requires: {aurora, extension}`; the
scheduler probes each target's capabilities and skips unmet ones, re-checking
every 10 minutes so `CREATE EXTENSION` is picked up live. See
`docs/telemetry-sources.md` for the research behind these.

## 4. Identity and delta semantics

**Server** — `server_id` from config (stable human name) plus
`pg_control_system().system_identifier` recorded on `cur_servers`. Aurora
failover keeps the same system identifier; restore-from-snapshot does not,
which we surface as an event rather than silently splitting history.

**Database** — `(server_id, datname)`. `oid` stored, not part of the key.

**Relation** — `(server_id, datname, schemaname, relname)`; `oid` alongside.
`pg_repack` and table recreation change OIDs; names survive.

**Query** — `query_id` (from `compute_query_id = on`, PG14+; falls back to
`pg_stat_statements.queryid`). Text is stored once in `cur_queries` keyed by
`(server_id, query_id)`, fetched with `pg_stat_statements(showtext := false)`
on the hot path and a second lookup only for unseen ids. A `fingerprint` from
`pg_query` normalisation allows grouping the same shape across servers.
Literals are stripped in the collector before anything leaves the process.

**Query latency: what you can and cannot get.** `pg_stat_statements` exposes
`calls`, `total`, `min`, `max`, `mean`, `stddev` per query — no per-call
distribution — so per-call quantiles (p95 of query X) cannot be derived from it.
What we do instead:

* store `sumsq_exec_time` per interval (`calls × (stddev² + mean²)` is cumulative
  and deltas cleanly), so mean **and** stddev are exact for any time range;
* `activity_samples` (10s) records, per `query_id`, how many backends were seen
  running it and for how long (`active_over_1s`, `active_over_10s`,
  `max_query_age_s`) — a sampled view of the tail, ASH-style;
* real quantiles come from sampled statement logs (phase 4):
  `log_min_duration_sample` + `log_statement_sample_rate` → `ts_query_durations`
  keyed by the same `query_id`, from which the API computes p50/p95/p99.

**Cumulative counters** — always stored as per-interval deltas. Rows whose every
counter delta is zero are not written (idle pg_stat_statements entries would
otherwise dominate). Reset detection:

1. `stats_reset` column present and changed → drop tick, re-baseline.
2. Any numeric delta < 0 → drop tick, re-baseline (per row, not whole tick).
3. Row absent in previous state → baseline, no emit.
4. `pg_stat_statements_info.dealloc` incremented → emit `event: pgss_dealloc`
   (means our top-N is lossy; raise `pg_stat_statements.max`).

Previous state is in memory. On clean shutdown it is persisted to the stats DB
(`collector_state` table, JSONB) so a restart loses at most one interval.

**Activity sampling** — each 10s tick records aggregate counts, plus raw rows for
"interesting" backends (active > 5s, waiting on a lock, idle-in-transaction
> 60s). Wait-event charts come from the aggregate; blocked-session drill-down
from the raw rows.

## 5. Storage schema (stats Postgres)

Two families:

**Time series** `ts_<collector>` — append-only, `PARTITION BY RANGE (collected_at)`,
daily partitions created ahead by the collector's sink on startup and hourly,
old partitions dropped by `retention_days` (default 14). Columns: `server_id`,
`instance`, `datname` (nullable for cluster scope), `collected_at`, `interval_seconds`, key
columns, then metric columns. Index on `(server_id, collected_at)` and on key
columns + time for the hot ones.

**Current state** `cur_<collector>` — upsert by identity, with `first_seen`,
`last_seen`, `content_hash`. Snapshot diffs append to `events(server_id,
datname, at, kind, subject, before jsonb, after jsonb)`.

Hand-written tables (Tier B): `ts_query_stats`, `cur_queries`,
`ts_activity_samples`, `ts_activity_sessions`, `ts_lock_waits`,
`cur_relations`, `cur_indexes`, `cur_settings`, `events`, `collector_state`,
`collector_runs` (self-metrics: per collector/server tick duration, rows,
error). Roll-ups (`ts_query_stats_1h`) are done by a periodic job in the sink,
not by the collector.

Migrations: `migrations/*.sql`, applied by the sink on startup (`sqlx` migrate).

## 6. Operational safety on RDS

* Role: `GRANT pg_monitor` (covers `pg_read_all_stats` + `pg_read_all_settings`).
  No table data. Provisioned as a `monitor` tier in `aurora_user_management`.
* Never behind PgBouncer: session GUCs would be lost under transaction pooling.
  The collector checks for `SHOW pool_mode` and refuses to start. `pg_stats` (column stats, contains sample values) is opt-in.
* Every session: `statement_timeout = 5s`, `lock_timeout = 1s`,
  `application_name = 'pgcollector'`, `default_transaction_read_only = on`.
* Expensive collectors (`sizes`, `schema`) run against a reader endpoint if
  `reader_url` is configured, else against the writer.
* Per-server concurrency = 1 heavy collector at a time; 10s collectors have a
  reserved connection so a slow `sizes` tick never delays activity sampling.
* Sink outage: bounded on-disk buffer (default 200 MB); drop 10m-tier
  snapshots before 10s-tier ones.
* Self-metrics into `collector_runs` and exposed at `/metrics` (Prometheus) so
  the collector's own footprint on the DB is visible.
* RDS specifics: `rds_superuser` not needed; `log_line_prefix`/`auto_explain`
  are parameter-group changes documented in `docs/rds-setup.md` (phase 4).

## 7. Config

Deployment is via the PostHog golden chart; see `docs/deploy.md`. Two ways to
declare servers, merged by `id`:

* **Env vars** (the normal path — one Helm `psql:` entry per cluster):
  `PGCOLLECTOR_SERVER_<ID>_URL`, `..._READER_URL`, `..._INSTANCE_<NAME>_URL`.
* **TOML `[[servers]]`** for per-server overrides and instance lists.

Databases are re-discovered every `rediscover_interval`; new databases get
their collectors started, dropped ones stopped. Per-collector settings merge
`[defaults.overrides]` → `[servers.overrides]` (`enabled`, `interval`).

Identity gains an `instance` dimension (`writer` | name from `instances`):
cluster-scoped collectors run per instance because Aurora replicas keep their
own stats; database-scoped ones run on the writer unless `per_instance: true`.

```toml
[sink]
database_url = "postgres://pgcollector@stats-host/pgcollector"
retention_days = 14

[defaults]
statement_timeout = "5s"
databases = ["*"]            # or explicit list; excludes template*/rdsadmin

[defaults.overrides]
sizes = { interval = "30m" }

[[servers]]                  # optional when PGCOLLECTOR_SERVER_PROD_MAIN_URL is set
id = "prod-main"
url = "${PGCOLLECTOR_SERVER_PROD_MAIN_URL}"
reader_url = "${PGCOLLECTOR_SERVER_PROD_MAIN_READER_URL}"
databases = ["posthog"]
[servers.instances]
reader-1 = "${PROD_MAIN_READER_1_URL}"
[servers.overrides]
activity = { interval = "5s" }
sizes = { enabled = false }
```

Secrets come from env (`${VAR}` expansion in URLs).

## 8. Phasing

1. ✅ **Skeleton** — config, scheduler, `Collector` trait, YAML loader, Postgres
   sink with auto-DDL + partitioning, Tier A collectors, `collector_runs`.
2. ✅ **`query_stats` + `activity_samples` / `activity_sessions` + `lock_waits`**.
3. ✅ **Aurora + pg_proctab sources** (Tier 1 of `docs/telemetry-sources.md`).
   Validated against stub functions with the documented shapes; needs a first
   run on a real Aurora cluster.
4. ✅ **Schema / settings / extension snapshots → change events; `vacuum_needed`; xid age.**
5. ✅ **Logs** — CloudWatch Logs + file sources, prefix-driven parser, durations
   (real latency quantiles), auto_explain plans, autovacuum, checkpoints, temp
   files, errors, deadlock/lock-wait/cancel events. Query fingerprint on
   `cur_queries` for joining when `%Q` isn't in the prefix.
6. ✅ **`pgapi`** — REST + MCP (17 tools) over the stats DB; edge-provided
   identity (Tailscale whois / ALB Cognito JWT / auth gateway), domain
   allowlist, read-only. UI still to come.
7. UI on top of `pgapi` on top of the stats DB (separate design).

## 9. Non-goals (for now)

* Multi-tenant SaaS concerns (org/user auth) — single team, single stats DB.
* Long retention / downsampled cold storage.
* Running `EXPLAIN ANALYZE` on production. Never.
