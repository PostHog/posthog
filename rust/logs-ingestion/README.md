# logs-ingestion

Rust port of the Node logs and traces ingestion consumers (`nodejs/src/logs`).
The library holds the pipeline, kept 1:1 with Node by the parity corpus (see [PORTING.md](PORTING.md)).
Two binaries run it against Kafka:

- `logs-ingestion` is the consumer service. It runs as the primary consumer, or as a shadow beside the Node consumer.
- `logs-shadow-compare` compares the Node output with the shadow output.

## The consumer service

`PLUGIN_SERVER_MODE` picks the consumer, as it picks the Node server:

| `PLUGIN_SERVER_MODE` | Consumer | Reads | Group (Node default) |
| --- | --- | --- | --- |
| `ingestion-logs` | `LogsIngestionConsumer` | `LOGS_INGESTION_CONSUMER_CONSUME_TOPIC` | `ingestion-logs` |
| `ingestion-traces` | `TracesIngestionConsumer` | `TRACES_INGESTION_CONSUMER_CONSUME_TOPIC` | `ingestion-traces` |

`LOGS_RUST_MODE` is required and has no default: `primary` or `shadow`.

Every setting the Node servers read keeps its Node name, default and parse: the `LOGS_*` and `TRACES_*` keys of `logs/config.ts`, the `LOGS_INGESTION_OUTPUT_*` keys, `KAFKA_WARPSTREAM_LOGS_PRODUCER_*` and `KAFKA_WARPSTREAM_INGESTION_PRODUCER_*`, `KAFKA_CONSUMER_*` (rdkafka keys, so `KAFKA_CONSUMER_METADATA_BROKER_LIST` is `metadata.broker.list`), `KAFKA_CLIENT_RACK`, `KAFKA_PREFIX`, `NODE_ENV`, `DATABASE_URL`, `DATABASE_READONLY_URL`, `POSTGRES_CONNECTION_POOL_SIZE`, `REDIS_URL`, `POSTHOG_REDIS_*`, `USAGE_INGESTION_*`, `CONSUMER_BATCH_SIZE`, `CONSUMER_MAX_BACKGROUND_TASKS`, `CONSUMER_BACKGROUND_TASK_TIMEOUT_MS` and `HTTP_SERVER_PORT` (default 6738).
The defaults that depend on `NODE_ENV` (limiter, metric rules, retention and backfill allowlists, Redis TLS, `_test` topic suffix) follow Node's `isProdEnv`.
The Kafka consumer follows `consumer-v1.ts` and `consumer-v2.ts`: `auto.offset.reset` defaults to `earliest` (`KAFKA_CONSUMER_AUTO_OFFSET_RESET` overrides it), and with `KAFKA_CONSUMER_GROUP_PROTOCOL=consumer` the classic-protocol keys (`session.timeout.ms`, `heartbeat.interval.ms`, `partition.assignment.strategy`, `group.protocol.type`) are removed, as `stripClassicProtocolConfig` does.

Settings that only the Rust service has:

| Variable | Meaning |
| --- | --- |
| `LOGS_RUST_MODE` | `primary` or `shadow`. Required. |
| `LOGS_RUST_SHADOW_CONSUMER_GROUP_ID` | Shadow only, required. Must end with `-rust-shadow`. |
| `LOGS_RUST_SHADOW_LOGS_TOPIC` | Shadow only, required. Must end with `_rust_shadow`. Takes the `logs` output. |
| `LOGS_RUST_SHADOW_DLQ_TOPIC` | Shadow only, required. Must end with `_rust_shadow`. Takes the `logs_dlq` output. |
| `LOGS_RUST_SHADOW_APP_METRICS_TOPIC` | Shadow only, required. Must end with `_rust_shadow`. Takes the `app_metrics` output. |
| `LOGS_RUST_SHADOW_REDIS_HOST` | Shadow only, required. The shadow's own Redis for rate-limit and sampling buckets. A host name, not a URL. |
| `LOGS_RUST_SHADOW_REDIS_PORT` | Shadow only, default 6379. |
| `LOGS_RUST_SHADOW_REDIS_PASSWORD` | Shadow only, default none. |
| `LOGS_RUST_SHADOW_REDIS_TLS` | Shadow only, default false. |
| `LOGS_RUST_SHUTDOWN_TIMEOUT_SECS` | Graceful shutdown budget, default 60. |

HTTP: `/_health` (liveness), `/_ready` (503 once shutdown starts) and `/metrics` on `HTTP_SERVER_PORT`.

### Batches and offsets

The loop follows the Node consumer (`consumer-v2.ts`):

- It reads up to `CONSUMER_BATCH_SIZE` messages within 500 ms and runs `process_kafka_batch`.
- Up to `CONSUMER_MAX_BACKGROUND_TASKS` background tasks run at once (default 1).
- A batch's offsets are stored only after its background task and every earlier one succeeded. librdkafka's auto commit commits them, and shutdown commits once more.
- A batch that fails, or a background task that fails or runs past `CONSUMER_BACKGROUND_TASK_TIMEOUT_MS`, stops the loop and exits the process with an error. Nothing from that batch or later is stored, so the restart replays it (at least once).
- SIGTERM stops fetching, lets the in-flight batch finish, stores and commits its offsets, then exits.

### Primary mode

Primary mode behaves as the Node consumer: Node's topics and producers, `ingested_event` writes, usage records to usage-ingestion over gRPC, and metric-rule OTLP pushes to `LOGS_METRICS_RULES_EXPORT_URL` (or the traces one). [PORTING.md](PORTING.md) lists what it does not reproduce.
Hog transformations are not ported, so primary mode refuses to start when `LOGS_TRANSFORMATIONS_ENABLED_TEAMS` is not empty. The traces consumer reads the same key, as in Node.

## Shadow mode

Shadow mode reads the same input topic as Node and cannot affect production.
The shadow pod cannot see the env of the Node deployment, so its main guards are allowlists of reserved names, not lists of production names.
The service refuses to start unless all of these hold:

- `LOGS_RUST_SHADOW_CONSUMER_GROUP_ID` ends with `-rust-shadow`. No Node or ClickHouse group uses that suffix, and sharing a group would take its partitions or move its offsets.
- Each of the three shadow topics ends with `_rust_shadow` (after trimming), and they differ from each other.
- As defence in depth, the group is not `ingestion-logs`, `ingestion-traces`, or a value of `LOGS_INGESTION_CONSUMER_GROUP_ID` or `TRACES_INGESTION_CONSUMER_GROUP_ID` in env, and no shadow topic is a known production topic: the Node default names of every logs and traces topic (bare, with `_test`, and with this env's prefix and suffix), the input topic, and any `LOGS_INGESTION_OUTPUT_*_TOPIC`, `*_CLICKHOUSE_TOPIC`, `*_DLQ_TOPIC`, `*_CONSUME_TOPIC` or `*_OVERFLOW_TOPIC` value in env.
- Each shadow topic exists. The shadow producers set `allow.auto.create.topics=false`, and at startup they read the metadata of each shadow topic and stop if it is missing, because brokers below Metadata v4 ignore that setting. A mistyped name cannot create a topic.
- `LOGS_RUST_SHADOW_REDIS_HOST` is set and is not the value of `LOGS_REDIS_HOST` (logs) or `TRACES_REDIS_HOST` (traces) when that key is in env. Shadow mode never reads `LOGS_REDIS_*`, `TRACES_REDIS_*` or `REDIS_URL`.
- `DATABASE_READONLY_URL` is set. Shadow mode reads Postgres only through it and never falls back to `DATABASE_URL`.

What shadow mode suppresses, and why:

| Effect | In shadow mode | Why |
| --- | --- | --- |
| `logs`, `logs_dlq`, `app_metrics` outputs | Written to the shadow topics | ClickHouse reads the production topics. `app_metrics` rows are customer-visible usage. |
| Usage records (usage-ingestion gRPC) | Dropped, no client is built | They bill. The shadow mints its own record ids, so they would bill twice. |
| `ingested_event` write | Skipped, no write pool is opened | Postgres is read only for the shadow. |
| Metric-rule OTLP push | Reported as sent, nothing is sent | It would create customer metrics twice. The emitter stays present, because its presence decides whether a buffer is decoded, and so the DLQ routing. |
| Hog transformations and their function logs | Not run (not ported) | They write to `log_entries`. |
| Rate-limit and sampling buckets | Kept under `@posthog-logs-rust-shadow/` in the shadow Redis (`LOGS_RUST_SHADOW_REDIS_*`) | Spending Node's tokens would drop Node's traffic. The shadow sees the same traffic, so its buckets drain at the same rate. |
| Quota limits | Read from the production PostHog Redis (`POSTHOG_REDIS_*`), as Node does | This is a deliberate read of production state. It is `ZRANGEBYSCORE` only, so it writes nothing, and the shadow needs the same quota decisions as Node for parity. |

The shadow `logs` output carries `source_offset` next to Node's `source_topic` and `source_partition`, so each output names its input message exactly. Primary mode never writes it. The DLQ already carries all three in both implementations.

Run it locally against the dev stack:

```bash
cd rust
PLUGIN_SERVER_MODE=ingestion-logs NODE_ENV=dev LOGS_RUST_MODE=shadow \
LOGS_RUST_SHADOW_CONSUMER_GROUP_ID=ingestion-logs-rust-shadow \
LOGS_RUST_SHADOW_REDIS_HOST=localhost \
DATABASE_READONLY_URL=postgres://posthog:posthog@localhost:5432/posthog \
LOGS_RUST_SHADOW_LOGS_TOPIC=clickhouse_logs_rust_shadow \
LOGS_RUST_SHADOW_DLQ_TOPIC=logs_ingestion_dlq_rust_shadow \
LOGS_RUST_SHADOW_APP_METRICS_TOPIC=clickhouse_app_metrics2_rust_shadow \
KAFKA_CONSUMER_METADATA_BROKER_LIST=localhost:9092 \
KAFKA_WARPSTREAM_LOGS_PRODUCER_METADATA_BROKER_LIST=localhost:9092 \
KAFKA_WARPSTREAM_INGESTION_PRODUCER_METADATA_BROKER_LIST=localhost:9092 \
HTTP_SERVER_PORT=6740 \
cargo run --release -p logs-ingestion --bin logs-ingestion
```

## The comparator

`logs-shadow-compare` reads the Node and the shadow topics with its own group and compares them under the parity contract. It has no Kafka producer.

- A `logs` record is matched by `source_topic`, `source_partition` and the record's `uuid`. A record with no `uuid` is matched by a hash of its content. A value that is not an Avro container is one item, matched by its hash.
- A DLQ message is matched by `source_topic`, `source_partition` and `source_offset`.
- Matched items compare every record field (numbers as doubles, map keys in any order) and every header. These headers are left out: `source_offset` on `logs` (shadow only), and `failed_at` (a clock) and `error_message` (the contract lets error text differ) on the DLQ.
- An item whose counterpart has not arrived within the lag tolerance counts as Node-only or Rust-only. Items that arrive during the warm-up count as `warmup_unmatched` instead, because the two consumers start at different offsets.

| Variable | Default | Meaning |
| --- | --- | --- |
| `LOGS_SHADOW_COMPARE_GROUP_ID` | required | The comparator's group. Must end with `-rust-shadow-compare` (after trimming), so it never equals a Node, ClickHouse Kafka-engine or shadow group. Auto commit records only its own progress. |
| `LOGS_SHADOW_COMPARE_NODE_TOPIC`, `LOGS_SHADOW_COMPARE_RUST_TOPIC` | required | The two `logs` topics. |
| `LOGS_SHADOW_COMPARE_NODE_DLQ_TOPIC`, `LOGS_SHADOW_COMPARE_RUST_DLQ_TOPIC` | unset | Both or neither. |
| `LOGS_SHADOW_COMPARE_LAG_TOLERANCE_MS` | 120000 | How long an item waits for its counterpart. |
| `LOGS_SHADOW_COMPARE_WARMUP_MS` | 300000 | Start-up window for `warmup_unmatched`. |
| `LOGS_SHADOW_COMPARE_MAX_PENDING` | 1000000 | Waiting items kept before the oldest count as one-sided. |
| `LOGS_SHADOW_COMPARE_MISMATCH_SAMPLE` | 200 | Mismatches logged with the key, field and both values. |
| `LOGS_SHADOW_COMPARE_HTTP_PORT` | 6739 | `/_health` and `/metrics`. |
| `KAFKA_CONSUMER_*` | | rdkafka settings, as for the service. `auto.offset.reset` defaults to `earliest`; set `KAFKA_CONSUMER_AUTO_OFFSET_RESET=latest` to skip the backlog. `allow.auto.create.topics` is always false. |

Metrics: `logs_shadow_compare_records_total{result=matched|mismatched|node_only|rust_only|warmup_unmatched}`, `logs_shadow_compare_field_mismatches_total{field}` (`header:<name>` for a header) and `logs_shadow_compare_pending`. A summary is logged every minute and on SIGTERM.

## Tests

```bash
cd rust
cargo test --release -p logs-ingestion
```

- `tests/parity_corpus.rs` replays the corpus through the pipeline. It needs Redis on 127.0.0.1:6379.
- `tests/service_postgres.rs` runs the Postgres dependencies against `test_posthog` on localhost:5432. It copies a team, seeds rule rows and deletes them. It skips without Postgres.
- `tests/service_kafka.rs` runs on librdkafka's mock cluster: the Kafka outputs, commit-after-success with a real consumer group, and shadow mode end to end. For the `passthrough`, `parse-failures` and `codecs` scenarios it produces the inputs, runs one batch, checks that the shadow topics hold the outputs Node recorded and that no production topic received anything, then seeds a topic with Node's outputs and checks that the comparator reports zero mismatches.

## Image

`rust/Dockerfile` builds one binary named by `BIN`:

```bash
docker build -f rust/Dockerfile --build-arg BIN=logs-ingestion -t logs-ingestion rust
docker build -f rust/Dockerfile --build-arg BIN=logs-shadow-compare -t logs-shadow-compare rust
```

CI builds only the images listed in `.github/rust-images.yml`, so both need an entry there before CI builds them. The build needs `protoc`, which the Dockerfile installs, for `usage-ingestion-proto`.
