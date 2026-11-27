# metrics-ingestion

Rust port of the Node metrics ingestion consumer (`nodejs/src/ingestion/pipelines/metrics`).
The library holds the pipeline. The parity corpus keeps the ported steps equal to Node's, and [PORTING.md](PORTING.md) lists the steps that are not ported yet.
The `metrics-ingestion` binary runs it against Kafka, as the primary consumer or as a shadow beside the Node consumer.

The crate builds on `ingestion-framework` and reuses `logs-ingestion` for everything the two consumers share: the Node env parsing, the Kafka source, outputs and batch loop, the Postgres team manager, quota limiting, the usage-ingestion client, the app metrics aggregator, the token-bucket Lua script and the shadow wrappers.

## The consumer service

`PLUGIN_SERVER_MODE` must be `ingestion-metrics`, as for the Node server. The consumer reads `METRICS_INGESTION_CONSUMER_CONSUME_TOPIC` with the group `METRICS_INGESTION_CONSUMER_GROUP_ID` (Node default `ingestion-metrics`).

`METRICS_RUST_SHADOW_MODE` is the only setting the Node server does not have. It defaults to `true` (shadow mode), and only `false` (or `0`, `no`, `off`) selects primary mode. Any other value stops startup.
The binary reads the Node env unchanged, so a Node metrics deployment can run it as a shadow with the same env.

Every setting the Rust consumer reads keeps its Node name, default and parse: the `METRICS_*` keys of `metrics/config.ts`, the `METRICS_INGESTION_OUTPUT_*` keys, `KAFKA_WARPSTREAM_METRICS_PRODUCER_*` and `KAFKA_WARPSTREAM_INGESTION_PRODUCER_*`, `KAFKA_CONSUMER_*` (rdkafka keys), `KAFKA_CLIENT_RACK`, `KAFKA_PREFIX`, `NODE_ENV`, `DATABASE_URL` (or, when it is empty, `POSTHOG_DB_NAME` with `POSTHOG_DB_USER`, `POSTHOG_DB_PASSWORD`, `POSTHOG_POSTGRES_HOST` and `POSTHOG_POSTGRES_PORT`), `DATABASE_READONLY_URL`, `POSTGRES_CONNECTION_POOL_SIZE`, `REDIS_URL`, `POSTHOG_REDIS_*`, `USAGE_INGESTION_*`, `CONSUMER_BATCH_SIZE`, `CONSUMER_MAX_BACKGROUND_TASKS`, `CONSUMER_BACKGROUND_TASK_TIMEOUT_MS` and `HTTP_SERVER_PORT` (default 6738).
The defaults that depend on `NODE_ENV` (limiter allowlist, Redis TLS, `_test` topic suffix, the `phc_local` dev token) follow Node's `isProdEnv` and `isDevEnv`.
As in Node, `METRICS_REDIS_PASSWORD` is read but not used.
`METRICS_AGGREGATION_ENABLED_TEAMS` is the exception: Rust has no aggregation step, so it only checks that primary mode does not ask for one.

The Kafka consumer, the batch loop, offsets, retries of consume errors and shutdown behave as in the logs service; see [the logs README](../logs-ingestion/README.md#batches-and-offsets).
HTTP: `/_health`, `/_ready`, and the Prometheus metrics on both `/_metrics` and `/metrics`, on `HTTP_SERVER_PORT`.

### Primary mode

Primary mode behaves as the Node consumer: Node's topics and producers, `ingested_event` writes, and usage records to usage-ingestion over gRPC (`x-client-name: metrics`), dated by the Kafka message timestamp, and confirmed unknown tokens go to `capture_logs:unknown_tokens` in the metrics Redis. [PORTING.md](PORTING.md) lists what it does not reproduce.

Primary mode cannot replace the Node consumer yet:

- The aggregation step is not ported. Primary mode refuses to start unless `METRICS_AGGREGATION_ENABLED_TEAMS` is empty, and its default is `*` outside production.
- The per-team OTLP counters (`metrics_ingestion_bytes_ingested_total`, `metrics_ingestion_records_ingested_total`) are not ported. They are the only signal of which teams ingest metrics.

## Shadow mode

Shadow mode reads the same input topic as Node and writes nothing that production reads.
Its `metrics` output matches Node's only for batches that Node did not aggregate, until the aggregation step is ported.
A new consumer group starts at the oldest offset, as in Node. To keep the first start from reading the whole retained topic through the shared rate-limit Redis and Kafka cluster, set `KAFKA_CONSUMER_AUTO_OFFSET_RESET=latest`.

- The consumer group is the Node group with `-rust-shadow` appended, for example `ingestion-metrics-rust-shadow`.
- Each output topic is the Node topic with `_rust_shadow` appended: `clickhouse_metrics_rust_shadow`, `metrics_ingestion_dlq_rust_shadow` and `clickhouse_app_metrics2_rust_shadow`. Each must exist, because the shadow producers set `allow.auto.create.topics=false` and check the topic metadata at startup.
- Postgres is read through `DATABASE_READONLY_URL` when it is set, and through `DATABASE_URL` otherwise. Shadow mode opens no write pool.

| Effect | In shadow mode | Why |
| --- | --- | --- |
| `metrics`, `dlq`, `app_metrics` outputs | Written to the shadow topics | ClickHouse reads the production topics. `app_metrics` rows are customer-visible usage. |
| Usage records (usage-ingestion gRPC) | Dropped, no client is built | They bill. |
| `ingested_event` write | Skipped | Postgres is read only for the shadow. |
| Rate-limit buckets | Kept under `@posthog-metrics-rust-shadow/` in Node's metrics Redis | Spending Node's tokens would drop Node's traffic. The shadow sees the same traffic, so its buckets drain at the same rate. |
| Unknown-token writes to `capture_logs:unknown_tokens` | Skipped, no recorder is built | The set is production state that capture-logs uses to turn tokens away. |
| Quota limits | Read from the production PostHog Redis, as Node does | `ZRANGEBYSCORE` only, so it writes nothing. |

The shadow `metrics` output carries `source_offset` next to Node's `source_topic` and `source_partition`, so each output names its input message. Primary mode never writes it.

Run it locally against the dev stack:

```bash
cd rust
PLUGIN_SERVER_MODE=ingestion-metrics NODE_ENV=dev \
KAFKA_CONSUMER_METADATA_BROKER_LIST=localhost:9092 \
KAFKA_WARPSTREAM_METRICS_PRODUCER_METADATA_BROKER_LIST=localhost:9092 \
KAFKA_WARPSTREAM_INGESTION_PRODUCER_METADATA_BROKER_LIST=localhost:9092 \
HTTP_SERVER_PORT=6741 \
cargo run -p metrics-ingestion --bin metrics-ingestion
```

## Tests

```bash
cd rust
cargo test -p metrics-ingestion
```

- `tests/parity_corpus.rs` replays the Node-recorded corpus in `nodejs/src/ingestion/pipelines/metrics/parity/fixtures`. It needs Redis on 127.0.0.1:6379 and skips without it.
- `tests/service_kafka.rs` runs one recorded batch through shadow mode on librdkafka's mock cluster, and checks the shadow topics and that no production topic received anything.

The Node side is `metrics-parity.serial.test.ts`. `METRICS_PARITY_RECORD=1` re-records the fixtures; re-record only for an intended behavior change, and port it to Rust in the same change.

## Image

```bash
docker build -f rust/Dockerfile --build-arg BIN=metrics-ingestion -t metrics-ingestion-rust rust
```

CI does not build an image yet. The `metrics-ingestion-rust` entry in `.github/rust-images.yml` and the deploy matrix land in a follow-up, after its shared-services ECR repository exists in posthog-cloud-infra.
Until then `rust/affected-services` lists `metrics-ingestion` as non-deployable.
