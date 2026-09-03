# Deploying pgcollector

## 1. Database users (posthog-cloud-infra)

`aurora_user_management/v3.0.0` has four tiers, all built on
`pg_read_all_data` / `pg_write_all_data`. None fit a monitoring agent:
`readonly` grants SELECT on every table (too much) while still **not** letting
the role see other users' rows in `pg_stat_statements` / `pg_stat_activity`
(too little — that needs `pg_read_all_stats`, which `pg_monitor` includes).

Add a `monitor` tier to the module. It is the same shape as the others:

```hcl
# variables.tf
variable "users_monitor" {
  description = "Users granted pg_monitor (pg_read_all_stats + pg_read_all_settings + pg_stat_scan_tables): full visibility into stats views and settings, NO data access. For telemetry agents such as pgcollector."
  type        = list(string)
  default     = []
}

# main.tf — locals
tier = merge(
  ...,
  { for u in var.users_monitor : u => "monitor" },
)
all_users = concat(..., var.users_monitor)

builtin_roles = {
  ...
  monitor = ["pg_monitor"]
}
database_privileges = {
  ...
  monitor = ["CONNECT"]
}
```

(`validate_tiers`' error message should mention the new list.)

Then, per monitored cluster, add `"pgcollector"` to `users_monitor` in that
cluster's users config — for the `cloud` cluster that's the `posthog_app_db_users`
module outputs (a new `cloud_users_monitor` output feeding the v3 lane), for
`persons` the `postgres-persons` configuration.

The **sink** database is a normal app database: pgcollector creates and alters
its own tables, so its user goes in `users_ddl` of whichever config manages
the stats cluster.

`pg_monitor` is enough for every collector shipped today, including
`pg_stat_statements` (the extension must be installed in the target database
— `CREATE EXTENSION pg_stat_statements` once, by a DDL user — and
`shared_preload_libraries` must include it, which is the RDS default parameter
group's setting on Aurora Postgres).

### Extensions and Aurora functions

Nothing here requires a parameter-group change or a reboot.

* `pg_stat_statements` — already in `shared_preload_libraries` on every
  cluster, but `CREATE EXTENSION` is per database and the collector reads
  cluster-wide stats from the **maintenance database (`postgres`)**. Run
  `CREATE EXTENSION IF NOT EXISTS pg_stat_statements` there (DDL user) if it
  hasn't been. This is the only step that is genuinely required.
* `pg_proctab` — optional. Not installed anywhere today; `CREATE EXTENSION
  pg_proctab` in the maintenance database enables `system_cpu`,
  `system_memory`, `system_disk`, `backend_cpu`. Until then those four log one
  `skipping: prerequisite not met` line and re-check every 10 minutes. Its
  functions may need `GRANT EXECUTE ... TO pgcollector`.
* `aurora_stat_*` / `aurora_replica_status` — built in, no setup.
  `aurora_compute_plan_id` (default on, 14.10+/15.5+) must stay on for
  `aurora_plans` and `plan_id` in activity samples.

Parameter-group niceties (dynamic, no reboot; both optional): append `%Q` to
`log_line_prefix` so log rows join `cur_queries` by query id instead of text
fingerprint; the log sampling, lock-wait and CloudWatch-export settings the
logs collector relies on are already set fleet-wide. Clusters that don't
preload `auto_explain` simply produce no `ts_log_plans`.

### Load profile on the monitored cluster

Every session runs with `statement_timeout = 5s` and `lock_timeout = 1s`, so a
misbehaving collector is cut off, not merely slow. Per tick:

| collector | interval | cost | notes |
|---|---|---|---|
| `activity_samples`, `activity_sessions` | 10s | one `pg_stat_activity` scan each | `pg_blocking_pids()` only for lock waiters |
| `lock_waits` | 10s | `pg_stat_activity` scan; `pg_blocking_pids()` per lock waiter only | empty unless something is blocked |
| `query_stats` | 60s | `pg_stat_statements(false)` (no text); text for ≤500 new ids per tick | no query text on the hot path |
| `database_stats`, `bgwriter`, `wal`, `replication*`, `vacuum_progress`, `aurora_system_waits`, `aurora_db_latency`, `aurora_replica_status` | 60s | shared-memory counter reads | negligible |
| `aurora_plans` | 5m | `aurora_stat_plans(false)`; plan text for new plan ids | ≤ `pg_stat_statements.max` rows |
| `table_stats`, `index_stats`, `vacuum_needed` | 10m | one catalog/stats scan per database | linear in relations; on the writer |
| `sizes` | 1h | four size functions per relation | reader endpoint when configured |
| `schema_*`, `settings`, `extensions` | 1h | catalog reads | reader for schema |
| `system_*`, `backend_cpu` | 60s | `/proc` reads via `pg_proctab` | only if the extension exists |
| `aurora_backend_waits`, `aurora_memctx` | — | **off by default** | per-backend function calls; enable per server via `overrides.<name>.enabled = true` |
| `logs` | 30s | no database load | CloudWatch Logs API; bounded per tick |

### Discovering every database on a cluster

`databases = ["*"]` lists `pg_database` and connects to each one with the same
credentials. That works because v3 grants `CONNECT` on the *module's*
`database_name` only — so a cluster with several databases needs the monitor
user granted CONNECT on each, or (simpler) `GRANT CONNECT ON DATABASE x TO
pgcollector` handled by the same lane. For clusters with one application
database this is a non-issue.

## 2. Helm (charts/posthog-app)

See [`deploy/values.example.yaml`](../deploy/values.example.yaml). Key points:

* **`pgbouncer: false` on every `psql:` entry.** pgcollector sets session GUCs
  and needs stable backends; it refuses to start if it detects PgBouncer.
* **Monitored servers come from env var names**, not from the TOML. A `psql:`
  entry whose `write.env` maps `PGCOLLECTOR_SERVER_<ID>_URL: POSTGRES_URL` is all
  it takes; add `read.env: {PGCOLLECTOR_SERVER_<ID>_READER_URL: POSTGRES_URL}` for
  the reader endpoint.
  Adding a cluster = one `psql:` entry + one Terraform user.
* `configFiles:` carries the TOML (sink URL, retention, defaults). Explicit
  `[[servers]]` blocks are still allowed for per-server overrides and
  `instances`; they merge with env-discovered servers by `id`.
* Probes and metrics on `:9187` (`/healthz`, `/readyz`, `/metrics`), scraped
  via the chart's `monitoring.prometheus` pod annotations.

## 3. Logs (statement durations, plans, autovacuum, checkpoints, errors)

The `logs` collector reads the Postgres log and writes typed rows —
`ts_query_durations` is where **real per-query latency quantiles** come from.
On Aurora the log is already exported to CloudWatch Logs
(`enabled_cloudwatch_logs_exports = ["postgresql"]`), one group per cluster,
one stream per instance:

```text
PGCOLLECTOR_SERVER_CLOUD_LOG_GROUP=/aws/rds/cluster/<cluster-id>/postgresql
PGCOLLECTOR_SERVER_CLOUD_LOG_LINE_PREFIX='%t:%r:%u@%d:[%p]:'     # only if not the RDS default
```

or in TOML: `logs = { source = "cloudwatch", log_group = "...", log_line_prefix = "..." }`.
The IRSA role needs `logs:FilterLogEvents` (and `logs:DescribeLogStreams`) on
those groups. The collector polls every 30s with a 10s lag, keeps its cursor in
`collector_state`, and warns when it falls behind.

Parameter-group settings that make this worthwhile (mostly already set):

| parameter | value | gives |
|---|---|---|
| `log_min_duration_sample` / `log_statement_sample_rate` | `1000` / `0.01` | sampled per-statement durations → p50/p95/p99 |
| `log_min_duration_statement` | `10000` | every slow statement |
| `log_line_prefix` | RDS default + `%Q` | **query id on every line** so log rows join `cur_queries` exactly; without it we join on a text fingerprint |
| `auto_explain.*` | json, sample 0.01 | plans for sampled slow statements → `ts_log_plans` |
| `log_lock_waits`, `log_temp_files=0`, `log_checkpoints`, `log_autovacuum_min_duration=0` | on | events + `ts_temp_files`, `ts_checkpoints`, `ts_autovacuum_runs` |

Validate a prefix against a downloaded log file with
`pgcollector --parse-log file.log --log-line-prefix '%t:%r:%u@%d:[%p]:%Q:'`.

The collector's own sessions try `SET log_min_duration_statement = -1` etc. so
they don't log themselves; grant `SET` on those GUCs to the monitor role if you
see pgcollector's queries in the log.

## 4. Replicas / multiple instances

Aurora replicas each have **their own** `pg_stat_statements`,
`pg_stat_activity`, bgwriter and I/O counters. The cluster reader endpoint
load-balances across them, so stats read through it are from "whichever
replica answered" and are useless as a time series. To see reader workload,
give pgcollector each instance endpoint:

```text
PGCOLLECTOR_SERVER_CLOUD_INSTANCE_READER_1_URL=postgres://.../   (instance endpoint)
PGCOLLECTOR_SERVER_CLOUD_INSTANCE_READER_2_URL=postgres://.../
```

or in TOML:

```toml
[[servers]]
id = "cloud"
url = "${PGCOLLECTOR_SERVER_CLOUD_URL}"
[servers.instances]
reader-1 = "${CLOUD_READER_1_URL}"
reader-2 = "${CLOUD_READER_2_URL}"
```

Cluster-scoped collectors then run against the writer **and** each instance,
and every row carries `instance` (`writer`, `reader-1`, …). Database-scoped
collectors (table/index stats, sizes, schema) run on the writer only by
default; set `per_instance: true` on a collector to change that.

Instance endpoints aren't something the `psql:` harness produces today; the
credentials are the same as the writer's, so they can be passed via
`secret_env_app_specific`, or (phase 4) discovered from the RDS API
(`rds:DescribeDBClusters` on the IRSA role) so new replicas are picked up
automatically. Aurora failover keeps the cluster endpoint pointing at the
current writer, so the `writer` series survives a failover; the promoted
instance's series moves from `reader-N` to `writer` at that point.

## 5. pgapi

The API + MCP server over this stats DB lives in `rust/pgapi` (separate PR) with its own README.
