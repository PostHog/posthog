# personhog-writer

Consumes person state updates from the `personhog_updates` Kafka topic and batch-upserts them to Postgres, closing the durability loop between the personhog-leader's in-memory cache and persistent storage.

## Architecture

```text
personhog_updates (Kafka, compacted)
    │
    ▼
┌──────────────────────────────────────────────────────┐
│  personhog-writer                                    │
│                                                      │
│  Consumer Task              Writer Task              │
│  ┌────────────────┐        ┌───────────────────┐    │
│  │ Kafka recv     │        │ PG batch upsert   │    │
│  │ Proto decode   │────────│ Per-row fallback   │    │
│  │ Buffer dedup   │ channel│ Offset commit      │    │
│  │ Flush triggers │        └───────────────────┘    │
│  └────────────────┘                                  │
└──────────────────────────────────────────────────────┘
    │
    ▼
personhog_person_tmp (PG)
```

The service runs two concurrent tokio tasks connected by a bounded channel:

- **Consumer task**: reads from Kafka, decodes Person protobuf messages, deduplicates in an in-memory buffer keyed by (team_id, person_id), and sends batches to the writer task on flush triggers.
- **Writer task**: receives batches, upserts to Postgres via `INSERT ... ON CONFLICT`, isolates failures with per-row fallback, and commits Kafka offsets only after every row in the flush has been applied.

The writer is a pure applier: the leader admits every record against this service's exact rejection surface (the `pg_column_size` measure, jsonb content rules, bindability of every column) before acking, so everything on the topic applies verbatim. The writer never corrects, trims, or skips — any writer-side edit or drop would permanently diverge Postgres from the leader's cache and changelog, because every later snapshot for the person builds on the same state.

## Code organization

| Module | Responsibility |
|--------|---------------|
| `kafka.rs` | Kafka consumer (`PersonConsumer`). Owns all Kafka config construction. |
| `consumer.rs` | Consumer loop: recv, decode, buffer, flush triggers, backpressure. |
| `writer.rs` | Writer loop: batch dispatch, retry orchestration, offset commit. Generic over `PersonStore` for testability. |
| `store.rs` | Batch orchestration: parallel chunk execution, outcome partitioning, per-row violation isolation. Defines the `PersonDb` trait; holds `Arc<D: PersonDb>`. |
| `pg.rs` | PG implementation of `PersonDb`: UNNEST-based chunk upsert, single-row upsert, type conversion, sqlx error classification. |
| `buffer.rs` | In-memory dedup buffer keyed by (team_id, person_id), keeps highest version. |
| `config.rs` | Envconfig-based configuration. |

## Flush triggers

The consumer flushes the buffer when any of these conditions are met:

- **Timer**: every `FLUSH_INTERVAL_MS` (default 30s)
- **Size threshold**: buffer reaches `FLUSH_BUFFER_SIZE` entries (default 10k)
- **Backpressure**: buffer reaches `BUFFER_CAPACITY` (default 100k), flush immediately
- **Shutdown**: graceful shutdown flushes remaining buffer

Every flush drains at most `FLUSH_BUFFER_SIZE` rows (rounded up to whole partitions), so a backlogged buffer empties as a sequence of bounded batches paced by the writer instead of one giant batch. Whole partitions only: a partition's max offset is safe to commit exactly when every buffered person from it has flushed, so a drained batch's offsets never skip past a person still in the buffer.

## Idempotency

The upsert uses `WHERE EXCLUDED.version > COALESCE(table.version, -1)`, so out-of-order or replayed messages from Kafka are safely ignored. The `COALESCE` handles nullable version columns (existing rows with NULL version will accept any update).

A person whose fields cannot be bound losslessly (malformed uuid, `team_id` beyond the column's integer range, non-UTF-8 JSON bytes, out-of-range timestamp) fails its chunk as a `Data` error rather than being silently dropped or repaired; the per-row pass then isolates it as an invariant violation (see below).

## Error handling

Failures are handled at chunk granularity: the store splits each batch into chunks (sized by `upsert_batch_size`), runs them in parallel against `PgStore::execute_chunk`, and reports successful, transient-failed, and data-failed chunks separately so only the affected rows need retry.

- **Transient** (connection loss, deadlock): retry just the failed chunks with exponential backoff (1s, 2s, 4s). Successful chunks are not re-executed. After 3 consecutive failures, signal unhealthy and shut down.
- **Saturation** (local pool acquire timeout): the writer's own in-flight statements exceeded pool capacity — self-inflicted, so it retries with the same backoff but never counts toward the consecutive-failure shutdown. Escalating on it would let a slow-PG burst crash-loop the pod, and each restart drops the buffers and redelivers, worsening the load that caused it.
- **Data** (constraint violation, invalid input): fall back to per-row inserts for the failed chunks' rows, isolating the bad records. Per-row upserts run with bounded concurrency (`ROW_FALLBACK_CONCURRENCY`). Successful chunks are not re-executed.
- **Non-transient row failure** (constraint violation, unbindable field): an invariant violation — the leader admitted a record Postgres cannot apply, so admission has a gap. The flush halts via `signal_failure` without committing; Kafka redelivers after restart, and the alarm stands until the gap is fixed. Skipping is never an option: it would permanently diverge PG from the cache and changelog.
- **Chunk task panic**: a spawned chunk task that panics cannot hand its persons back — the task's stack is unwound. The writer treats this as a fatal error, signals failure, and exits. Because Kafka offsets are committed only on full batch success, redelivery after restart recovers the records; the panic payload is captured in the error message for diagnosis.
- **Slow flush**: the lane keeps its liveness heartbeat ticking while a flush runs, for about five minutes, so a slow database does not restart the pod. A longer flush reports the lane unhealthy, and the pod restarts unless the flush completes before the next health check.

User-facing size warnings are emitted by the leader at admission time, where the client also gets synchronous feedback; the writer emits none.

## JSON handling

The leader serializes a parsed `serde_json::Value` into proto bytes, so they are valid JSON by construction. The writer passes them through as `text[]` in the UNNEST query and lets PostgreSQL cast `::jsonb` — it never parses JSON itself. The `tests/admission_weld.rs` suite welds the leader's admission functions to this exact statement against a live Postgres.

## Backpressure

Total in-flight statement concurrency is capped by a pod-wide permit budget (`UPSERT_CONCURRENCY`) shared across all writer lanes and both the chunk and per-row paths. A burst of chunks queues at the semaphore — a cheap, unbounded wait — instead of oversubscribing the pool and converting its own fan-out into acquire timeouts.

When the writer is slow (PG latency, pool saturation), size-triggered flushes stop being accepted, the lane buffer grows, and at the hard cap the consumer blocks on channel send, which stops Kafka consumption. Capped drains keep the resulting batches bounded, so the backlog releases at the writer's pace. This naturally limits memory usage and prevents unbounded buffering.

## Kafka consumer configuration

- **Cooperative-sticky assignment**: during autoscaling, only partitions that need to move are revoked
- **Static group membership**: when `KAFKA_CLIENT_ID` is set, the broker holds partition assignments during pod restarts (requires StatefulSet for stable pod names)
- **Manual offset commits**: offsets are committed only after a successful Postgres write, and only for partitions still assigned to this pod
- **Revocation**: when the broker takes partitions away, their buffered rows are dropped, and a batch already queued for the writer is filtered the same way when the writer picks it up. Their offsets were never committed, so the new owner reads them from the last commit instead of both pods writing the same rows. A batch already executing against Postgres, including its retries, still completes

## Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `personhog_writer_messages_consumed_total` | counter | Messages decoded from Kafka |
| `personhog_writer_decode_errors_total` | counter | Proto decode failures |
| `personhog_writer_kafka_errors_total` | counter | Kafka recv errors |
| `personhog_writer_flushes_total` | counter | Total flush events |
| `personhog_writer_flushes_by_trigger_total{trigger}` | counter | Flush trigger breakdown (timer, size, backpressure, shutdown) |
| `personhog_writer_rows_upserted_total{mode}` | counter | Rows PG reported as affected (mode: chunk, row) |
| `personhog_writer_rows_version_skipped_total{mode}` | counter | Rows skipped by version guard (mode: chunk, row) |
| `personhog_writer_upsert_errors_total{mode}` | counter | PG write failures (mode: chunk, row) |
| `personhog_writer_batch_fallback_total` | counter | Batches that fell back to per-row |
| `personhog_writer_unbindable_field_total{field}` | counter | Rows whose field could not be bound losslessly (invariant violation) |
| `personhog_writer_unapplyable_rows_total{kind}` | counter | Rows PG refused non-transiently (invariant violation, halts the flush) |
| `personhog_writer_chunk_fallback_rows_total` | counter | Rows from data-failed chunks sent to per-row fallback |
| `personhog_writer_chunk_retry_rows_total` | counter | Rows from transient-failed chunks retried as a batch |
| `personhog_writer_chunk_saturated_rows_total` | counter | Rows from chunks that hit local pool saturation |
| `personhog_writer_saturation_retries_total` | counter | Retry rounds caused only by pool saturation (never escalate) |
| `personhog_writer_chunk_fatal_total` | counter | Chunk tasks that panicked or were cancelled |
| `personhog_writer_row_fallback_duration_seconds` | histogram | Duration of the per-row fallback for a batch |
| `personhog_writer_row_fallback_in_flight` | gauge | Concurrent per-row upserts in flight during fallback |
| `personhog_writer_pg_pool_size` | gauge | Total sqlx pool connections (sampled every 5s) |
| `personhog_writer_pg_pool_idle` | gauge | Idle sqlx pool connections (sampled every 5s) |
| `personhog_writer_offset_commits_total` | counter | Successful offset commits |
| `personhog_writer_offset_commit_errors_total` | counter | Failed offset commits |
| `personhog_writer_offset_commits_skipped_total{reason}` | counter | Partition offsets left uncommitted because the partition is no longer assigned |
| `personhog_writer_partitions_revoked_total` | counter | Partitions the broker revoked from this pod |
| `personhog_writer_revoked_rows_dropped_total{stage}` | counter | Rows dropped because their partition was revoked (stage: buffer, queued) |
| `personhog_writer_flush_duration_seconds` | histogram | PG write latency per flush |
| `personhog_writer_flush_rows` | histogram | Rows per flush |
| `personhog_writer_channel_send_duration_seconds` | histogram | Time waiting on the writer channel (backpressure indicator) |
| `personhog_writer_e2e_latency_seconds` | histogram | End-to-end latency from Kafka message creation to PG commit |
| `personhog_writer_buffer_size` | gauge | Current buffer entries |
| `personhog_writer_partition_offset{partition}` | gauge | Current offset per partition |
| `personhog_writer_property_partitions_lost_total{reason}` | counter | Partitions whose offsets were left uncommitted because SlateDB could not take their rows here (reason: `ownership_lost`, or `unassigned` when the partition had no assignment on this pod) |
| `personhog_writer_backfill_live_lag` | gauge | In `backfill` mode, the pod's changelog lag that paces the backfill topic |
| `personhog_writer_backfill_paused` | gauge | In `backfill` mode, 1 while the backfill topic is paused for live records |
| `personhog_writer_property_catch_ups_total{outcome, partition}` | counter | `dual` mode replays after an assignment (outcome: `finished`, `nothing_to_replay`, `lost`) |
| `personhog_writer_property_catch_up_rows_total` | counter | Changelog rows a `dual` mode replay wrote to SlateDB |
| `personhog_writer_property_fenced_retries_total` | counter | Property-store writes retried after another writer fenced shards this pod still owns |
| `personhog_writer_property_not_ready_total` | counter | Property-store writes retried while their shards were still opening |
| `personhog_backfill_rows_total{outcome}` | counter | `backfill scan`: rows `read`, and of those `written` to the topic, `deleted` (written as delete markers), `trimmed` (written after trimming) or `rejected` |
| `personhog_backfill_ranges_total{outcome}` | counter | `backfill scan`: ranges this worker `finished` or found `already_done` |
| `personhog_backfill_page_seconds` | histogram | `backfill scan`: one page's Postgres scan |
| `personhog_backfill_produce_errors_total` | counter | `backfill scan`: records the backfill topic refused |
| `personhog_verify_persons_total{outcome}` | counter | `backfill verify`: persons judged `match`, `differs`, `behind`, `missing`, `newer_in_slatedb` or `rejected`, or `erased_team` for a row of a team listed as deleted, which is not judged |
| `personhog_verify_ranges_total{outcome}` | counter | `backfill verify`: ranges `finished` or found `already_done` |
| `personhog_verify_deleted_teams_total{outcome}` | counter | `backfill verify`: deleted teams whose SlateDB range is `empty` or still `present` |
| `personhog_writer_team_erasures_total{outcome}` | counter | Deleted-team erasures per tick: `ok`, `failed`, or `list_failed` when the table could not be read |
| `personhog_writer_deleted_teams` | gauge | Teams listed in `personhog_deleted_teams` at the last tick |

Consumer lag per partition is monitored externally via KMinion (`kminion_kafka_consumer_group_topic_lag`).

## Property backfill

The backfill loads existing person properties into SlateDB while the production writer keeps ingesting. Every write keeps the higher version, so the order in which rows arrive does not matter.

The `backfill` subcommands keep a run's plan and progress under `PROPERTY_BACKFILL_STATE_URL`, an object store outside the property store, so the state can be deleted after the cutover without touching the shards. A run id names a plan, a scan and a verification together.

1. `personhog-writer backfill start` with `PROPERTY_BACKFILL_GROUP` set to a new group copies the production writer group's committed changelog offsets to it. The production writer commits only what is in Postgres, so every record below those offsets is in any snapshot taken afterwards. It refuses the production group, a group that already has commits, and a writer group missing a commit on any partition.
2. Start writers in `backfill` mode with `KAFKA_CONSUMER_GROUP` set to that group. They read the changelog from the copied offsets and the backfill topic from its first record, with the range assignor, so one pod owns partition N of both topics. They refuse to start on a group without a commit on every changelog partition. The backfill topic pauses while the changelog lags. These writers refuse to start, and stop, while a changelog migration is draining. Take the snapshot the scanner reads after `start`.
3. `personhog-writer backfill plan --run-id <run>` splits `PG_TARGET_TABLE` into key ranges of about `--rows-per-range` rows (default 5M), each child table of a partitioned table on its own, from a `TABLESAMPLE` of its keys. The plan is saved once under `backfill/<run>/plan`; a run keeps the plan it started with.
4. `personhog-writer backfill scan --run-id <run> --index <n> --workers <count>` scans ranges `n`, `n + count`, and so on in primary-key order, and produces each row to `PROPERTY_BACKFILL_TOPIC` on the changelog partition that person belongs to. Run it as an Indexed Job with `--index` set to the completion index and `--workers` to the completion count, with `DATABASE_URL` pointing at the snapshot. A range records its cursor after every published page, so a restarted worker repeats at most one page, and a finished range does nothing on rerun. A row whose properties do not parse is logged by id and skipped. A document the topic would refuse is trimmed to `PROPERTIES_TRIM_TARGET` the way the leader trims one over its threshold, and logged. Progress is on the metrics port as `personhog_backfill_*`.
5. Once the `backfill` mode writers have read the whole backfill topic and caught up on the changelog, delete them.
6. Switch the production writer to `dual` with `PROPERTY_BACKFILL_GROUP` set to the backfill group, promptly: each newly assigned partition replays the changelog from the backfill group's committed offset up to its own group's, writing SlateDB only, while the writer continues from its own offset, and that replay grows with the time between the two steps. A replay that a crash or a reassignment interrupts runs again in full on the next owner. `PROPERTY_CATCH_UP_CONCURRENCY` replays run at once per pod.
7. Confirm `personhog_writer_property_catch_ups_total` shows `finished` or `nothing_to_replay` for every changelog partition since the switch to `dual`; it takes minutes. Counters live on pods, so check with `increase` over the whole `dual` period, not an instant value. Then redeploy the writer in `dual` without `PROPERTY_BACKFILL_GROUP`: the gap is replayed once, and without the group no later assignment replays anything. Until the replays finish, a person whose newest record is in the gap reads as unavailable from SlateDB.
8. `personhog-writer backfill verify --run-id <run> --index <n> --workers <count>` compares a fresh snapshot (`DATABASE_URL`) with SlateDB over the run's key ranges, judging each person by version: `match`, `differs` (same version, different content), `behind` or `missing` (SlateDB lacks a write), and `newer_in_slatedb` (written after the snapshot, which parity with the snapshot allows), and `rejected` (a row the scan could not turn into a record). `--sample-every N` checks one row in N. Divergent persons are logged by id with both versions; `personhog-writer properties get` shows the two sides of one. A finished range is skipped on rerun; delete `verify/<run>` from the state store to verify a run again. Set `PROPERTY_STORE_BLOCK_CACHE_BYTES` for this job, since it reads in key order. A row of a team listed in `personhog_deleted_teams` is counted `erased_team` and not judged, since the erasure removed its keys; the list is read from `--live-database-url` when given, so run with it, or a project deleted after the snapshot reads as `missing`. Switch the writer to `slatedb` only when `differs`, `behind`, `missing` and `rejected` are zero. A rejected row has properties nested past the parser's limit or too large to trim; such a person is already unwritable under personhog and loses its eventual reads at cutover, so accept a non-zero `rejected` only after checking each logged id is one of those.
9. Switching the writer to `slatedb` is the one-way step: Postgres stops updating the property columns, and every row the writer updates from then on has `{}` in its properties column.

**Remove after cutover.** Once production runs `slatedb`, these exist only for the load and can be deleted: the `backfill` storage mode and `src/backfill_mode.rs`, the dual catch-up in `src/catch_up.rs` with `PROPERTY_BACKFILL_GROUP` and `PROPERTY_CATCH_UP_CONCURRENCY`, `PROPERTY_BACKFILL_TOPIC`, `PROPERTY_BACKFILL_MAX_LIVE_LAG`, `PROPERTY_BACKFILL_STATE_URL` and `PROPERTIES_TRIM_TARGET`, the backfill topic in the consumer, and the `backfill` command in `src/backfill/`. The per-assignment generations and the cross-topic dedup rule stay; they are correctness fixes the load exposed. `personhog-writer properties get` stays as the way to look at one person's record.

## Reading one person

`personhog-writer properties get --team <team> --person <person>` prints the record SlateDB holds for the person and the Postgres row, with the verifier's verdict for the pair. It needs `PROPERTY_STORE_*` and `DATABASE_URL`, opens a one-off reader on the store, and runs anywhere with read access to the bucket.

## Project deletion

`DeletePersonsBatchForTeam` on the replica hard-deletes a project's persons and lists the team in `personhog_deleted_teams`. Every minute the writer reads that table and deletes each listed team's keys from the shards it owns, in every mode that writes SlateDB, and the next full compaction removes the bytes. A team stays listed for the replica's retention window, so a record for it that arrives late, from a lagging changelog, a catch-up replay or the backfill topic, is erased on the next tick. Each batch of an erasure waits a bounded time for storage; a shard that does not answer is left for the next tick while the other shards and teams go on. `backfill verify` reports a listed team that still has keys.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_HOSTS` | `localhost:9092` | Kafka bootstrap servers |
| `KAFKA_TLS` | `false` | Enable TLS for Kafka |
| `KAFKA_CLIENT_ID` | (empty) | Pod name for static group membership |
| `KAFKA_CLIENT_RACK` | (empty) | Rack ID for rack-aware consumption |
| `PROPERTY_STORAGE_MODE` | `postgres` | Where properties go. `postgres`: Postgres only. `dual`: Postgres and SlateDB (`PROPERTY_STORE_*`). `slatedb`: SlateDB only; Postgres keeps the identity columns, and the properties column is `{}` on insert and update. `backfill`: SlateDB only and nothing to Postgres, in its own consumer group (see [Property backfill](#property-backfill)). Offsets commit once every store in the mode has the batch |
| `PROPERTY_BACKFILL_TOPIC` | (empty) | The backfill topic. `backfill` mode reads it next to the changelog, and `personhog-writer backfill scan` writes it. It must have the changelog's partition count |
| `PROPERTY_BACKFILL_MAX_LIVE_LAG` | `10000` | In `backfill` mode, the backfill topic pauses while the pod's changelog lag exceeds this many records |
| `PROPERTY_BACKFILL_GROUP` | (empty) | The `backfill` mode writers' consumer group, which `backfill start` starts. In `dual` mode, each newly assigned partition first replays the changelog from that group's committed offset up to this group's. Empty skips the replay; the writer's own group is refused |
| `PROPERTY_CATCH_UP_CONCURRENCY` | `4` | How many of those replays run at once per pod; each holds a consumer with 8 MiB of prefetch |
| `PROPERTY_BACKFILL_STATE_URL` | (empty) | Where the `backfill` subcommands keep a run's plan and progress: an object store URL that is not the property store, such as a scratch bucket. Required by those subcommands |
| `PROPERTIES_TRIM_TARGET` | `524288` | `backfill scan` trims a document the backfill topic would refuse to this many jsonb bytes, as the leader does with one over its threshold |
| `KAFKA_CONSUMER_GROUP` | `personhog-writer` | Consumer group ID |
| `ETCD_ENDPOINTS` | `http://localhost:2379` | etcd endpoints; the topic comes from `config/changelog` |
| `ETCD_PREFIX` | `/personhog/` | etcd key prefix |
| `DATABASE_URL` | (required in `postgres` mode) | Postgres connection string |
| `PG_MAX_CONNECTIONS` | `20` | Connection pool size |
| `PG_TARGET_TABLE` | `personhog_person_tmp` | Target table (`posthog_person` for production cutover) |
| `FLUSH_INTERVAL_MS` | `30000` | Timer-based flush interval (longer = better dedup, higher latency) |
| `FLUSH_BUFFER_SIZE` | `10000` | Size-based flush trigger and per-flush drain cap |
| `BUFFER_CAPACITY` | `100000` | Hard cap for backpressure |
| `UPSERT_BATCH_SIZE` | `5000` | Max rows per INSERT statement (chunks execute in parallel) |
| `UPSERT_CONCURRENCY` | `8` | Pod-wide cap on concurrent upsert statements, shared across lanes |
| `ROW_FALLBACK_CONCURRENCY` | `16` | Max concurrent per-row upserts during per-row fallback |
| `FLUSH_CHANNEL_CAPACITY` | `8` | Channel capacity between tasks |
| `METRICS_PORT` | `9103` | Prometheus metrics HTTP port |
