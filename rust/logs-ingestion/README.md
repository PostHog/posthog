# logs-ingestion

Rust port of the Node logs and traces ingestion consumers (`nodejs/src/logs`).
The library holds the pipeline, kept 1:1 with Node by the parity corpus (see [PORTING.md](PORTING.md)).
The `logs-ingestion` binary runs it against Kafka, as the primary consumer or as a shadow beside the Node consumer.

## The consumer service

`PLUGIN_SERVER_MODE` picks the consumer, as it picks the Node server:

| `PLUGIN_SERVER_MODE` | Consumer | Reads | Group (Node default) |
| --- | --- | --- | --- |
| `ingestion-logs` | `LogsIngestionConsumer` | `LOGS_INGESTION_CONSUMER_CONSUME_TOPIC` | `ingestion-logs` |
| `ingestion-traces` | `TracesIngestionConsumer` | `TRACES_INGESTION_CONSUMER_CONSUME_TOPIC` | `ingestion-traces` |

`LOGS_RUST_SHADOW_MODE` is the only setting the Node servers do not have. It defaults to `true` (shadow mode), and only `false` (or `0`, `no`, `off`) selects primary mode. Any other value stops startup.
The image is `logs-ingestion-rust`, so a Node logs or traces deployment can switch to it with the same env.

Every setting the Node servers read keeps its Node name, default and parse: the `LOGS_*` and `TRACES_*` keys of `logs/config.ts`, the `LOGS_INGESTION_OUTPUT_*` keys, `KAFKA_WARPSTREAM_LOGS_PRODUCER_*` and `KAFKA_WARPSTREAM_INGESTION_PRODUCER_*`, `KAFKA_CONSUMER_*` (rdkafka keys, so `KAFKA_CONSUMER_METADATA_BROKER_LIST` is `metadata.broker.list`), `KAFKA_CLIENT_RACK`, `KAFKA_PREFIX`, `NODE_ENV`, `DATABASE_URL`, `DATABASE_READONLY_URL`, `POSTGRES_CONNECTION_POOL_SIZE`, `REDIS_URL`, `POSTHOG_REDIS_*`, `USAGE_INGESTION_*`, `CONSUMER_BATCH_SIZE`, `CONSUMER_MAX_BACKGROUND_TASKS`, `CONSUMER_BACKGROUND_TASK_TIMEOUT_MS` and `HTTP_SERVER_PORT` (default 6738).
The defaults that depend on `NODE_ENV` (limiter, metric rules, retention and backfill allowlists, Redis TLS, `_test` topic suffix) follow Node's `isProdEnv`.
The Kafka consumer follows `consumer-v1.ts` and `consumer-v2.ts`: `auto.offset.reset` defaults to `earliest` (`KAFKA_CONSUMER_AUTO_OFFSET_RESET` overrides it), and with `KAFKA_CONSUMER_GROUP_PROTOCOL=consumer` the classic-protocol keys (`session.timeout.ms`, `heartbeat.interval.ms`, `partition.assignment.strategy`, `group.protocol.type`) are removed, as `stripClassicProtocolConfig` does.

HTTP: `/_health` (liveness), `/_ready` (503 once shutdown starts) and `/metrics` on `HTTP_SERVER_PORT`.

### Batches and offsets

The loop follows the Node consumer (`consumer-v2.ts`):

- It reads up to `CONSUMER_BATCH_SIZE` messages within 500 ms and runs `process_kafka_batch`.
- Up to `CONSUMER_MAX_BACKGROUND_TASKS` background tasks run at once (default 1).
- A batch's offsets are stored only after its background task and every earlier one succeeded. librdkafka's auto commit commits them, and shutdown commits once more.
- A batch that fails, or a background task that fails or runs past `CONSUMER_BACKGROUND_TASK_TIMEOUT_MS` after its dispatch, stops the loop and exits the process with an error. Nothing from that batch or later is stored, so the restart replays it (at least once).
- A produce to the `logs` topic that fails with a Kafka outage, such as a delivery timeout, a full queue or a topic authorization failure, is retried in place and then fails the batch. Only an error that a replay cannot fix, such as an oversized or invalid record, sends the message to the DLQ.
- A consume error is tried 3 times, 100 ms apart doubling, as `retryIfRetriable` does, and then exits the process.
- A revoke bumps the epoch of each revoked partition. A task dispatched before the revoke does not store that partition's offset, as `consumer-v2.ts` fences it.
- SIGTERM stops fetching, lets the in-flight batch finish, stores and commits its offsets, then exits. A task still running 60 s after SIGTERM is aborted.

### Primary mode

Primary mode behaves as the Node consumer: Node's topics and producers, `ingested_event` writes, usage records to usage-ingestion over gRPC, and metric-rule OTLP pushes to `LOGS_METRICS_RULES_EXPORT_URL` (or the traces one). [PORTING.md](PORTING.md) lists what it does not reproduce.
Hog transformations are not ported, so primary mode refuses to start when `LOGS_TRANSFORMATIONS_ENABLED_TEAMS` is not empty. The traces consumer reads the same key, as in Node.

## Shadow mode

Shadow mode reads the same input topic as Node and cannot affect production.
It derives every name it writes from the Node settings:

- The consumer group is the Node group with `-rust-shadow` appended, for example `ingestion-logs-rust-shadow`. No Node or ClickHouse group uses that suffix, so the shadow never takes Node's partitions or moves its offsets.
- Each output topic is the Node topic with `_rust_shadow` appended, for example `clickhouse_logs_rust_shadow`, `logs_ingestion_dlq_rust_shadow` and `clickhouse_app_metrics2_rust_shadow`.
- Each shadow topic must exist. The shadow producers set `allow.auto.create.topics=false`, and at startup they read the metadata of all topics and stop if a shadow topic is missing, because brokers below Metadata v4 ignore that setting and create a topic that a metadata request names.
- Postgres is read through `DATABASE_READONLY_URL` when it is set, and through `DATABASE_URL` otherwise. Shadow mode opens no write pool.

What shadow mode suppresses, and why:

| Effect | In shadow mode | Why |
| --- | --- | --- |
| `logs`, `logs_dlq`, `app_metrics` outputs | Written to the shadow topics | ClickHouse reads the production topics. `app_metrics` rows are customer-visible usage. |
| Usage records (usage-ingestion gRPC) | Dropped, no client is built | They bill. The shadow mints its own record ids, so they would bill twice. |
| `ingested_event` write | Skipped, no write pool is opened | Postgres is read only for the shadow. |
| Metric-rule OTLP push | Reported as sent, nothing is sent | It would create customer metrics twice. The emitter stays present, because its presence decides whether a buffer is decoded, and so the DLQ routing. |
| Hog transformations and their function logs | Not run (not ported) | They write to `log_entries`. |
| Rate-limit and sampling buckets | Kept under `@posthog-logs-rust-shadow/` in Node's logs or traces Redis | Spending Node's tokens would drop Node's traffic. The shadow sees the same traffic, so its buckets drain at the same rate. |
| Quota limits | Read from the production PostHog Redis (`POSTHOG_REDIS_*`), as Node does | This is a deliberate read of production state. It is `ZRANGEBYSCORE` only, so it writes nothing, and the shadow needs the same quota decisions as Node for parity. |

The shadow `logs` output carries `source_offset` next to Node's `source_topic` and `source_partition`, so each output names its input message exactly. Primary mode never writes it. The DLQ already carries all three in both implementations.

Run it locally against the dev stack:

```bash
cd rust
PLUGIN_SERVER_MODE=ingestion-logs NODE_ENV=dev \
KAFKA_CONSUMER_METADATA_BROKER_LIST=localhost:9092 \
KAFKA_WARPSTREAM_LOGS_PRODUCER_METADATA_BROKER_LIST=localhost:9092 \
KAFKA_WARPSTREAM_INGESTION_PRODUCER_METADATA_BROKER_LIST=localhost:9092 \
HTTP_SERVER_PORT=6740 \
cargo run --release -p logs-ingestion --bin logs-ingestion
```

## Tests

```bash
cd rust
cargo test --release -p logs-ingestion
```

- `tests/parity_corpus.rs` replays the corpus through the pipeline. It needs Redis on 127.0.0.1:6379.
- `tests/service_postgres.rs` runs the Postgres dependencies against `test_posthog` on localhost:5432. It copies a team, seeds rule rows and deletes them. It skips without Postgres.
- `tests/service_kafka.rs` runs on librdkafka's mock cluster: the Kafka outputs, commit-after-success with a real consumer group, and shadow mode end to end. For the `passthrough`, `parse-failures` and `codecs` scenarios it produces the inputs, runs one batch, and checks that the shadow topics hold the outputs Node recorded and that no production topic received anything.

## Image

`rust/Dockerfile` builds one binary named by `BIN`:

```bash
docker build -f rust/Dockerfile --build-arg BIN=logs-ingestion -t logs-ingestion-rust rust
```

CI builds it as the `logs-ingestion-rust` image (`.github/rust-images.yml`). The build needs `protoc`, which the Dockerfile installs, for `usage-ingestion-proto`.
