# Flags consumer

`flags-consumer` builds the dedicated feature-flag read store from person and distinct ID CDC topics. It applies version-guarded batches so replayed or out-of-order messages cannot replace newer state.

## Read-store schema

The store uses two tables, each hash-partitioned by `team_id`:

- `flags_person` stores one properties row per `(team_id, person_uuid)`.
- `flags_distinct_id_map` stores one owner per `(team_id, distinct_id)`.

Both tables use primary-key B-tree indexes. Deletes are versioned tombstones. A canonical lookup uses one round trip and two primary-key probes:

```sql
SELECT p.person_uuid, p.properties
FROM flags_distinct_id_map AS m
JOIN flags_person AS p
  ON p.team_id = m.team_id
 AND p.person_uuid = m.person_uuid
WHERE m.team_id = $1
  AND m.distinct_id = $2
  AND m.deleted_at IS NULL
  AND p.deleted_at IS NULL;
```

`rust/flags_read_store_migrations` owns this DDL. It replaces an earlier `flags_person_lookup` draft that used a `distinct_ids` array with a GIN index; that draft never ran outside a local checkout, so it was rewritten in place rather than retired by a second migration. If your local `flags_read_store` database applied the draft, `sqlx migrate run` reports a checksum mismatch — drop and recreate the database, then re-run `bin/migrate --scope=flags-read-store`.

## Schema benchmark

The benchmark populates the two tables, runs `VACUUM ANALYZE` and `CHECKPOINT`, verifies every storage query plan, then runs six phases:

1. `baseline_reads` sends average-rate reads only.
2. `steady_mix` sends every class at its average production rate.
3. `peak_mix` sends every class at its measured five-minute peak rate.
4. `merge_storm` adds ten times the peak merge rate to the steady mix.
5. `recovery` vacuums both table groups before measuring the steady mix again.
6. `catch_up` keeps reads open-loop while write classes use independent backpressured feeds to measure sustainable throughput.

Creation traffic produces one person upsert and one distinct ID assignment. In open-loop phases, the independent distinct ID schedule is reduced by the paired creation rate so the total class rate stays at the requested target. Catch-up disables paired creation so each closed write feed measures its class independently.

The gate profile checks every open feed's deadline-scoped rate and backlog, zero shedding and operation errors in every phase, peak and storm read latency, interval drift, storm-drain-inclusive recovery time, catch-up write headroom, and load-generator dispatch latency. The smoke profile prints the same diagnostics but does not fail on production thresholds.

Warning: unless `--skip-populate` is passed, the benchmark drops `flags_person_lookup`, `flags_person`, and `flags_distinct_id_map`, then recreates the current tables. Use a dedicated benchmark database. Destructive setup requires the explicit `--allow-destructive-reset` flag. `--skip-populate` inspects the existing partition layout but cannot verify that its rows match the supplied scale, team count, and seed; run metadata records the population as unverified.

Set `FLAGS_READ_STORE_DATABASE_URL` for the dedicated benchmark database. The benchmark does not fall back to `DATABASE_URL`. Run these commands from `rust/`.

Local smoke run:

```sh
FLAGS_READ_STORE_DATABASE_URL=postgres://posthog:posthog@localhost:5432/flags_read_store \
  cargo run -p flags-consumer --release -- benchmark \
  --profile smoke --scale 400000 --partitions 8 --allow-destructive-reset
```

Single partition at target density:

```sh
FLAGS_READ_STORE_DATABASE_URL="$BENCHMARK_DATABASE_URL" \
  cargo run -p flags-consumer --release -- benchmark \
  --profile smoke --partitions 1 --scale 45000000 --allow-destructive-reset
```

Aurora gate run on the production-candidate instance:

```sh
FLAGS_READ_STORE_DATABASE_URL="$AURORA_BENCHMARK_DATABASE_URL" \
  cargo run -p flags-consumer --release -- benchmark \
  --profile gate --scale 45000000 --partitions 64 \
  --allow-destructive-reset \
  --out tmp/flags-read-store-aurora-gate.jsonl
```

The output path defaults to `tmp/flags-read-store-benchmark.jsonl`. JSONL records include run metadata, actual schema metadata, 10-second latency intervals, PostgreSQL table and WAL samples, phase summaries, and the automated gate result. The console report shows deadline-scoped scheduled and achieved rates alongside eventual completion totals, deadline backlog, post-deadline and executor-drain time, latency percentiles, retries, deadlocks, table statistics, WAL volume, catch-up headroom against peak, and each gate decision.

An automated pass is only part of the go/no-go decision. The report lists the remaining manual qualifications: bloat equilibrium and per-partition autovacuum progress, bootstrap extrapolation, production-candidate working-set size, and guaranteed load-generator CPU.

## Follow-ups outside this repository

- Amend the RFC in `requests-for-comments-internal` to describe the mapping-table design and correct the legacy `= ANY` read query.
- Give the benchmark load generator guaranteed CPU in `cloud-infra` before using it for production-candidate latency gates.
