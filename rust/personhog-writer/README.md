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
│  │ Buffer dedup   │ channel│ Property trimming  │    │
│  │ Flush triggers │        │ Offset commit      │    │
│  └────────────────┘        └───────────────────┘    │
│                                    │                 │
│                                    ▼                 │
│                            ┌───────────────────┐    │
│                            │ Warnings Producer  │    │
│                            │ (ingestion warns)  │    │
│                            └───────────────────┘    │
└──────────────────────────────────────────────────────┘
    │                                │
    ▼                                ▼
personhog_person_tmp (PG)    client_iwarnings_ingestion (Kafka)
```

The service runs two concurrent tokio tasks connected by a bounded channel:

- **Consumer task**: reads from Kafka, decodes Person protobuf messages, deduplicates in an in-memory buffer keyed by (team_id, person_id), and sends batches to the writer task on flush triggers.
- **Writer task**: receives batches, upserts to Postgres via `INSERT ... ON CONFLICT`, handles errors with per-row fallback and property trimming, commits Kafka offsets only after a successful write, and emits ingestion warnings for user-facing visibility.

## Code organization

| Module | Responsibility |
|--------|---------------|
| `kafka.rs` | Kafka consumer (`PersonConsumer`) and warnings producer (`WarningsProducer`). Owns all Kafka config construction. |
| `consumer.rs` | Consumer loop: recv, decode, buffer, flush triggers, backpressure. |
| `writer.rs` | Writer loop: batch dispatch, retry orchestration, offset commit. Generic over `PersonStore` for testability. |
| `store.rs` | Batch orchestration: parallel chunk execution, outcome partitioning, per-row fallback with property trimming. Defines the `PersonDb` trait; holds `Arc<D: PersonDb>`. |
| `pg.rs` | PG implementation of `PersonDb`: UNNEST-based chunk upsert, single-row upsert, type conversion, sqlx error classification. |
| `properties.rs` | Property trimming algorithm matching the Node.js pipeline. Protected properties list. |
| `buffer.rs` | In-memory dedup buffer keyed by (team_id, person_id), keeps highest version. |
| `config.rs` | Envconfig-based configuration. |

## Flush triggers

The consumer flushes the buffer when any of these conditions are met:

- **Timer**: every `FLUSH_INTERVAL_MS` (default 5s)
- **Size threshold**: buffer reaches `FLUSH_BUFFER_SIZE` entries (default 1000)
- **Backpressure**: buffer reaches `BUFFER_CAPACITY` (default 50k), flush immediately
- **Shutdown**: graceful shutdown flushes remaining buffer

## Idempotency

The upsert uses `WHERE EXCLUDED.version > COALESCE(table.version, -1)`, so out-of-order or replayed messages from Kafka are safely ignored. The `COALESCE` handles nullable version columns (existing rows with NULL version will accept any update).

Persons with invalid UUIDs are filtered out before the batch INSERT to prevent unique constraint violations from multiple nil UUIDs in the same batch.

## Error handling

Failures are handled at chunk granularity: the store splits each batch into chunks (sized by `upsert_batch_size`), runs them in parallel against `PgStore::execute_chunk`, and reports successful, transient-failed, and data-failed chunks separately so only the affected rows need retry.

- **Transient** (connection loss, pool timeout, deadlock): retry just the failed chunks with exponential backoff (1s, 2s, 4s). Successful chunks are not re-executed. After 3 consecutive failures, signal unhealthy and shut down.
- **Data** (constraint violation, invalid input): fall back to per-row inserts for the failed chunks' rows, isolating the bad records. Per-row upserts run with bounded concurrency (`ROW_FALLBACK_CONCURRENCY`). Successful chunks are not re-executed.
- **Properties size violation**: trim non-protected properties alphabetically until under 512KB, then retry. If untrimable (only protected properties exceed the limit), skip the row and emit an ingestion warning.
- **Chunk task panic**: a spawned chunk task that panics cannot hand its persons back — the task's stack is unwound. The writer treats this as a fatal error, signals failure, and exits. Because Kafka offsets are committed only on full batch success, redelivery after restart recovers the records; the panic payload is captured in the error message for diagnosis.

Ingestion warnings are produced to the `client_iwarnings_ingestion` Kafka topic so users see property size violations in-product. The producer is fire-and-forget (enqueued into rdkafka's internal buffer) to avoid blocking the write path, with a flush on graceful shutdown.

## JSON handling

The leader serializes person properties via `serde_json::RawValue` into proto bytes, which are already valid JSON. The writer passes these through as `text[]` in the UNNEST query and lets PostgreSQL cast `::jsonb`, avoiding unnecessary parse/serialize cycles on the hot path. JSON is only parsed in the error path when property trimming is needed.

## Backpressure

When the writer is slow (PG latency, connection pool exhaustion), the bounded channel between consumer and writer fills up (capacity: 8 batches). The consumer blocks on channel send, which stops Kafka consumption. This naturally limits memory usage and prevents unbounded buffering.

## Kafka consumer configuration

- **Cooperative-sticky assignment**: during autoscaling, only partitions that need to move are revoked
- **Static group membership**: when `KAFKA_CLIENT_ID` is set, the broker holds partition assignments during pod restarts (requires StatefulSet for stable pod names)
- **Manual offset commits**: offsets are committed only after a successful Postgres write

## Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `personhog_writer_messages_consumed_total` | counter | Messages decoded from Kafka |
| `personhog_writer_decode_errors_total` | counter | Proto decode failures |
| `personhog_writer_invalid_uuid_total` | counter | Persons skipped due to invalid UUIDs |
| `personhog_writer_invalid_team_id_total` | counter | Persons skipped because `team_id` exceeds i32 range |
| `personhog_writer_invalid_json_total` | counter | Non-UTF8 JSON fields defaulted |
| `personhog_writer_kafka_errors_total` | counter | Kafka recv errors |
| `personhog_writer_flushes_total` | counter | Total flush events |
| `personhog_writer_flushes_by_trigger_total{trigger}` | counter | Flush trigger breakdown (timer, size, backpressure, shutdown) |
| `personhog_writer_rows_upserted_total{mode}` | counter | Rows PG reported as affected (mode: chunk, row) |
| `personhog_writer_rows_version_skipped_total{mode}` | counter | Rows skipped by version guard (mode: chunk, row) |
| `personhog_writer_rows_skipped_total` | counter | Rows skipped due to per-row errors |
| `personhog_writer_upsert_errors_total{mode}` | counter | PG write failures (mode: chunk, row) |
| `personhog_writer_batch_fallback_total` | counter | Batches that fell back to per-row |
| `personhog_writer_chunk_fallback_rows_total` | counter | Rows from data-failed chunks sent to per-row fallback |
| `personhog_writer_chunk_retry_rows_total` | counter | Rows from transient-failed chunks retried as a batch |
| `personhog_writer_chunk_fatal_total` | counter | Chunk tasks that panicked or were cancelled |
| `personhog_writer_row_fallback_duration_seconds` | histogram | Duration of the per-row fallback for a batch |
| `personhog_writer_row_fallback_in_flight` | gauge | Concurrent per-row upserts in flight during fallback |
| `personhog_writer_pg_pool_size` | gauge | Total sqlx pool connections (sampled every 5s) |
| `personhog_writer_pg_pool_idle` | gauge | Idle sqlx pool connections (sampled every 5s) |
| `personhog_writer_properties_trimmed_total` | counter | Properties trimming attempted |
| `personhog_writer_properties_trimmed_writes_total` | counter | Rows written after trimming |
| `personhog_writer_ingestion_warnings_emitted_total` | counter | Warnings produced to Kafka |
| `personhog_writer_offset_commits_total` | counter | Successful offset commits |
| `personhog_writer_offset_commit_errors_total` | counter | Failed offset commits |
| `personhog_writer_flush_duration_seconds` | histogram | PG write latency per flush |
| `personhog_writer_flush_rows` | histogram | Rows per flush |
| `personhog_writer_channel_send_duration_seconds` | histogram | Time waiting on the writer channel (backpressure indicator) |
| `personhog_writer_e2e_latency_seconds` | histogram | End-to-end latency from Kafka message creation to PG commit |
| `personhog_writer_buffer_size` | gauge | Current buffer entries |
| `personhog_writer_partition_offset{partition}` | gauge | Current offset per partition |

Consumer lag per partition is monitored externally via KMinion (`kminion_kafka_consumer_group_topic_lag`).

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_HOSTS` | `localhost:9092` | Kafka bootstrap servers |
| `KAFKA_TLS` | `false` | Enable TLS for Kafka |
| `KAFKA_CLIENT_ID` | (empty) | Pod name for static group membership |
| `KAFKA_CLIENT_RACK` | (empty) | Rack ID for rack-aware consumption |
| `KAFKA_TOPIC` | `personhog_updates` | Topic to consume |
| `KAFKA_CONSUMER_GROUP` | `personhog-writer` | Consumer group ID |
| `KAFKA_CONSUMER_OFFSET_RESET` | `earliest` | Offset reset policy |
| `KAFKA_INGESTION_WARNINGS_TOPIC` | `client_iwarnings_ingestion` | Topic for ingestion warnings |
| `DATABASE_URL` | (required) | Postgres connection string |
| `PG_MAX_CONNECTIONS` | `20` | Connection pool size |
| `PG_TARGET_TABLE` | `personhog_person_tmp` | Target table (`posthog_person` for production cutover) |
| `FLUSH_INTERVAL_MS` | `30000` | Timer-based flush interval (longer = better dedup, higher latency) |
| `FLUSH_BUFFER_SIZE` | `10000` | Size-based flush trigger |
| `BUFFER_CAPACITY` | `100000` | Hard cap for backpressure |
| `UPSERT_BATCH_SIZE` | `5000` | Max rows per INSERT statement (chunks execute in parallel) |
| `ROW_FALLBACK_CONCURRENCY` | `16` | Max concurrent per-row upserts during per-row fallback |
| `FLUSH_CHANNEL_CAPACITY` | `8` | Channel capacity between tasks |
| `METRICS_PORT` | `9103` | Prometheus metrics HTTP port |
