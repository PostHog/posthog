# LLMA ingestion usage metrics (compressed + uncompressed bytes) — spec

## Goal

Add an **opt-in** metrics-tracking option to the AI (LLM analytics / "llma") ingestion
pipeline that records the **uncompressed** and **compressed** byte size of the events
coming in, and writes those numbers to the `app_metrics2` ClickHouse table.

This mirrors what the **logs ingestion** pipeline already does for billing: it measures
per-batch byte sizes at capture time and emits per-team `usage` rows into `app_metrics2`.
We want the same signal for AI events so we can gather the data (and later bill on it),
behind env-var flags so it can be turned on/off without a code change.

The feature is **off by default**. When off, there is zero behavioral or throughput change
to the AI ingestion path.

## Background: how logs does it today

The logs pipeline splits the work across the Rust capture layer and a Node consumer:

1. **Rust producer** (`rust/capture-logs/src/kafka.rs`, `write_avro_batch`) compresses the
   Avro batch and stamps three Kafka headers on the produced message:
   - `bytes_uncompressed` — raw HTTP body size of the batch (caller-provided)
   - `bytes_compressed` — `payload.len()` after Avro + Zstandard encoding
   - `record_count` — number of rows in the batch
2. **Node consumer** (`nodejs/src/logs-ingestion/logs-ingestion-consumer.ts`):
   - `_parseKafkaBatch` reads those headers (`bytes_uncompressed`, `bytes_compressed`,
     `record_count`) and resolves `team_id` from the token via `TeamManager`.
   - `trackOutgoingTrafficAndBuildUsageStats` aggregates per-team byte/record counts.
   - `emitUsageMetrics` → `queueUsageMetric` → `AppMetricsAggregator.queue(...)` produces
     rows to the `app_metrics2` Kafka topic with `app_source='logs'`, `metric_kind='usage'`,
     and metric names like `bytes_received`, `bytes_ingested`, `records_received`, etc.

The `app_metrics2` row shape (see `posthog/models/app_metrics2/sql.py` and
`nodejs/src/common/services/app-metrics-aggregator.ts`):

```
team_id Int64
timestamp DateTime64(6, 'UTC')      -- truncated to the hour on read (AggregatingMergeTree)
app_source LowCardinality(String)   -- e.g. "logs", "traces", "hog"
app_source_id String
instance_id String
metric_kind LowCardinality(String)  -- "usage" for billing-style counters
metric_name LowCardinality(String)  -- e.g. "bytes_received"
count SimpleAggregateFunction(sum, Int64)
```

> Note: logs currently parses `bytes_compressed` but does **not** emit a compressed-byte
> metric to `app_metrics2` — only `bytes_uncompressed` is billed. This spec emits **both**
> for AI so we can compare compression ratios while gathering data.

## The pivotal constraint: capture has no `team_id`

`app_metrics2` is keyed by `team_id`. The Rust capture service deliberately does **not**
resolve token → `team_id` (it stays Postgres-free for throughput). The AI endpoint operates
purely on the project token (see the existing TODO in `rust/capture/src/ai_endpoint.rs`:
"Replace token with team_id once secret key signing is implemented and we can resolve tokens
to team IDs in capture").

Therefore the byte measurement happens in capture (which is the only place that sees the raw
compressed request body), but the `app_metrics2` write must happen in a Node consumer that
already resolves `team_id` — exactly the split logs uses.

## Where the bytes are measured

In `rust/capture/src/ai_endpoint.rs::ai_handler_inner`, both numbers are already in hand:

- **compressed bytes** = `body.len()` — the request body *before* gzip decompression
  (line ~147, the `extract_body_with_timeout` result). When the client did not gzip, this
  equals the uncompressed size.
- **uncompressed bytes** = `decompressed_body.len()` — already captured as `body_size`
  (line ~205).

The OTEL AI path (`rust/capture/src/otel/mod.rs`) has the equivalent `body_len` and already
records a `capture_ai_otel_body_size_bytes` histogram; the same env-gated stamping applies
there.

The AI endpoint produces exactly one `CapturedEvent` per request (single-event multipart),
so per-request byte sizes map cleanly to a single event with `record_count = 1`.

## Recommended design

Two parts, each behind its own env flag.

### Part A — Rust capture: measure + stamp (off by default)

Behind a new config flag, stamp the two sizes onto the produced AI event so a downstream
consumer can attribute them to a team.

- Add config in `rust/capture/src/config.rs` (envconfig pattern, matching the existing
  `ai_*` block):

  ```rust
  // Emit per-request AI ingestion size metrics (uncompressed + compressed bytes) to
  // app_metrics2 via downstream consumer. Off by default.
  #[envconfig(default = "false")]
  pub ai_usage_metrics_enabled: bool,
  ```

- In `ai_handler_inner`, when `state.ai_usage_metrics_enabled` is true, attach the two
  numbers to the produced Kafka message as **headers**:
  - `ai_bytes_uncompressed` = `decompressed_body.len()`
  - `ai_bytes_compressed` = `body.len()` (pre-decompression)

  Preferred transport: **Kafka message headers** on the event produced to
  `events_plugin_ingestion`. This keeps the user's event payload clean (no synthetic
  `$ai_*` properties leaking into the events table). This requires the Kafka sink to support
  per-event headers — verify/extend `rust/capture/src/sinks/kafka.rs` and the
  `ProcessedEvent` / `ProcessedEventMetadata` plumbing. If header plumbing proves invasive,
  the fallback is the **dedicated-topic** alternative below (which is the truest logs mirror
  and avoids the main pipeline entirely).

- Always-on Prometheus histograms (operational visibility, independent of the flag) can be
  added next to the existing blob metrics in `ai_endpoint.rs`:
  `capture_ai_request_bytes_uncompressed`, `capture_ai_request_bytes_compressed`.

When the flag is off, none of the above headers are stamped and the consumer side is a no-op,
so behavior is unchanged.

### Part B — Node consumer: aggregate + write `app_metrics2` (off by default)

AI events flow into `events_plugin_ingestion`, processed by the main analytics consumer
(`nodejs/src/ingestion/ingestion-consumer.ts`). That consumer already has a `TeamManager`
(resolves `team_id`) and already imports `AppMetricsOutput`, so the write path is wired.

- Add a config flag (e.g. `INGESTION_AI_USAGE_METRICS_ENABLED`, default `false`).
- For events where the headers `ai_bytes_uncompressed` / `ai_bytes_compressed` are present
  (these only appear when Part A is enabled), and `team_id` is resolved, queue two rows into
  an `AppMetricsAggregator` (reuse `nodejs/src/common/services/app-metrics-aggregator.ts`):

  | field | value |
  |---|---|
  | `app_source` | `"llm_analytics"` |
  | `app_source_id` | `""` |
  | `instance_id` | `""` |
  | `metric_kind` | `"usage"` |
  | `metric_name` | `"bytes_received"` (uncompressed), `"bytes_received_compressed"` (compressed), `"events_received"` (count = 1) |
  | `count` | the byte count / event count |

- Flush the aggregator once per batch (mirrors logs' `emitUsageMetrics` → `flush()`),
  wrapped in try/catch so a metrics failure never blocks ingestion.

The `AppMetricsAggregator` already dedupes/sums in memory on the six identity fields, so a
batch with many AI events from one team produces a small number of `app_metrics2` rows.

### Resulting `app_metrics2` rows

```
app_source="llm_analytics", metric_kind="usage", metric_name="bytes_received"             -> Σ uncompressed bytes per team/hour
app_source="llm_analytics", metric_kind="usage", metric_name="bytes_received_compressed"  -> Σ compressed bytes per team/hour
app_source="llm_analytics", metric_kind="usage", metric_name="events_received"            -> Σ AI events per team/hour
```

These are queryable immediately via the `app_metrics2` HogQL table
(`posthog/hogql/database/schema/app_metrics2.py`) and the app metrics API.

## Env vars (the on/off switches)

| Var | Side | Default | Effect |
|---|---|---|---|
| `CAPTURE_AI_USAGE_METRICS_ENABLED` | Rust capture (`ai_usage_metrics_enabled`) | `false` | When true, stamp `ai_bytes_uncompressed` / `ai_bytes_compressed` headers on AI events. |
| `INGESTION_AI_USAGE_METRICS_ENABLED` | Node ingestion consumer | `false` | When true, read those headers, aggregate per team, write `app_metrics2`. |

Both must be on to land rows in `app_metrics2`. Keeping them independent lets us turn on
capture-side stamping first (cheap, header-only) and validate before enabling the write.

## Alternatives considered

1. **Write `app_metrics2` directly from Rust capture.** Rejected for now: requires adding
   token → `team_id` resolution to capture (Postgres dependency it deliberately avoids) and
   extending the Rust `AppMetric2` enum (`rust/common/kafka/src/kafka_messages/app_metrics2.rs`,
   today only `Hoghooks`/`Cyclotron`) plus an `app_metrics2` Kafka producer in capture.

2. **Dedicated AI-usage-metrics topic + dedicated Node consumer** (the closest mirror of
   logs, which even has a separate `metrics_producer`/`kafka_metrics_topic`). Capture produces
   a small extra message per AI request with `token` + byte headers; a new
   `AiUsageMetricsConsumer` (structured like `LogsIngestionConsumer`) resolves the team and
   writes `app_metrics2`. Cleanest isolation from the hot analytics path, but adds a new Kafka
   topic and a new deployable consumer. **Good fallback** if stamping headers onto the main
   event stream proves awkward, or if AI volume warrants isolation.

3. **Inject synthetic `$ai_bytes_*` event properties** instead of headers. Rejected:
   pollutes the user-facing events table and persists in ClickHouse.

## Follow-ups (out of scope for the initial "gather data" milestone)

- **Billing integration.** Once data is flowing, wire the new `llm_analytics` `usage`
  metrics into `posthog/tasks/usage_report.py` the way logs usage is read, if/when AI
  ingestion becomes a billed product.
- **Dropped/allowed split.** Logs distinguishes `bytes_received` vs `bytes_ingested` vs
  `bytes_dropped` (quota/rate-limit). The AI endpoint already runs quota/token-dropper checks
  before producing; if needed we can add `bytes_dropped` by stamping/aggregating on the drop
  branches too. Initial milestone tracks received bytes only.

## Testing

- **Rust** (`rust/capture`): unit/integration test asserting that with
  `ai_usage_metrics_enabled=true` the produced AI event carries `ai_bytes_uncompressed`
  (= decompressed size) and `ai_bytes_compressed` (= raw body size), for both gzip and
  non-gzip requests (where the two are equal); and that with the flag off no headers are
  added. Extend `rust/capture/tests/integration_ai_endpoint.rs`.
- **Node** (`nodejs`): test that the ingestion consumer, with
  `INGESTION_AI_USAGE_METRICS_ENABLED=true`, emits `app_metrics2` rows with
  `app_source='llm_analytics'`, `metric_kind='usage'`, and the expected metric names/counts,
  and emits nothing when the flag is off or headers are absent. Mirror
  `nodejs/src/logs-ingestion/logs-ingestion-consumer.test.ts`.

## Touch list (files)

- `rust/capture/src/config.rs` — add `ai_usage_metrics_enabled`.
- `rust/capture/src/ai_endpoint.rs` — measure + stamp headers; optional Prometheus histograms.
- `rust/capture/src/otel/mod.rs` — same stamping for the OTEL AI path.
- `rust/capture/src/sinks/kafka.rs` (+ `v0_request.rs`) — per-event Kafka header support if
  not already present.
- `nodejs/src/ingestion/ingestion-consumer.ts` (+ its config) — flag, header read, aggregate,
  flush.
- Reuse `nodejs/src/common/services/app-metrics-aggregator.ts` (no change expected).
- Tests as above.
</content>
</invoke>
