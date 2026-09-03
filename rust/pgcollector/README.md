# pgcollector

A Postgres telemetry collector for RDS/Aurora: query statistics, activity and
wait events, table/index/vacuum health, schema and settings changes, and
statement-level data from the Postgres log, written to a Postgres stats
database that `pgapi` serves.
See [DESIGN.md](DESIGN.md) for the full design.

## Run

```sh
cp deploy/pgcollector.example.toml pgcollector.toml   # edit servers + sink
cargo run -p pgcollector -- --check                            # validate config + collectors
cargo run -p pgcollector -- --once                             # run every collector once, print to stdout
cargo run -p pgcollector                        # run forever
```

Target role: `GRANT pg_monitor TO pgcollector;` — nothing else.

TLS is required for every connection (sink and targets) unless the URL says
`sslmode=disable` (local dev) or `sslmode=prefer`. Statement text taken from
logs and `pg_stat_activity` is stored with string literals replaced by `'?'`.

Servers can be declared in TOML or discovered from env vars
(`PGCOLLECTOR_SERVER_<ID>_URL`, `..._READER_URL`, `..._INSTANCE_<NAME>_URL`) —
see [docs/deploy.md](docs/deploy.md) for the Helm + Terraform setup.
`/healthz`, `/readyz`, `/metrics` on `:9187`.

## Adding a stat

Most collectors are YAML in `collectors/`, compiled into the binary; a
`--collectors-dir` overlay can replace, add, or (`enabled: false`) remove one
at runtime. To add a column, add it to the
`SELECT`; the sink adds the column to `ts_<name>` / `cur_<name>` on the next
tick. To add a new stat source, add a new file:

```yaml
name: my_stats
interval: 60s
scope: cluster            # or: database
kind: cumulative          # gauge | cumulative | snapshot
key: [some_id]
query: SELECT ...
variants:                 # optional, version-specific SQL (highest matching wins)
  - min_pg_version: 170000
    query: SELECT ...
```

`per_instance: true|false` overrides the default (cluster scope → every
instance, database scope → writer only).

Rules: cast anything that isn't bool/int/float/numeric/text/timestamptz/json
(`::text`, `::bigint`, `::float8`). `cumulative` diffs every numeric non-key
column per `key` and understands a `stats_reset` column.

Logic-heavy collectors (`pg_stat_statements`, activity sampling, locks, schema
diffs) are Rust in `src/collectors/` implementing the same `Collector` trait.

Validate a `log_line_prefix` against a log file:
`pgcollector --parse-log postgresql.log --log-line-prefix '%t:%r:%u@%d:[%p]:%Q:'`.

## Local testing

`test/setup-local.sh` starts a throwaway PG16 with `pg_stat_statements`,
`auto_explain`, file logging into `.local/pglog/`, and stub `aurora_*`
functions (`test/aurora_stubs.sql`) so the Aurora collectors can be exercised.

## Layout

```text
src/collector.rs          Collector trait, Snapshot/Row/Value, shared delta logic
src/collectors/           registry + declarative (YAML) collector
src/scheduler.rs          per-server, per-collector tick loops
src/sink/                 Sink trait; Postgres sink (auto-DDL, partitions, retention)
src/pg.rs                 target connections (TLS, session safety settings, PgBouncer guard)
src/http.rs               /healthz /readyz /metrics
deploy/, docs/deploy.md   golden-chart values + Terraform user tier
collectors/*.yaml         Tier A collectors
migrations/*.sql          hand-written sink tables
```

## Provenance

Every query in `collectors/` and `src/collectors/` was written for this project
against the PostgreSQL and Aurora documentation. Nothing is copied from
pgwatch, postgres_exporter or any other project; the
research notes in `docs/telemetry-sources.md` cite their docs only.
