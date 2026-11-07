# Porting notes: metrics ingestion, Node to Rust

This crate ports the Node metrics consumer in `nodejs/src/ingestion/pipelines/metrics`.
The JavaScript semantics it relies on (`Date.parse`, `parseInt`, `Number#toString`, JSON key order) come from `logs_ingestion::js`, and [the logs PORTING.md](../logs-ingestion/PORTING.md) describes them.

## Parity contract

For the same messages in, the two must give equivalent output: the same produced packets and headers, the same drops and DLQ routing, the same rate-limit decisions, the same `app_metrics` rows, the same usage records and the same teams marked as ingested.
Error message text in `dlq_reason` may differ for real Kafka errors, and the order of produced messages is not part of the contract.

The contract is the corpus in `nodejs/src/ingestion/pipelines/metrics/parity/fixtures`.
Each file holds a scenario and the outputs Node recorded for it.
`dlq_timestamp` compares as "an ISO timestamp", because the Rust DLQ helper reads the wall clock.

| Scenario | Covers |
| --- | --- |
| `passthrough` | Unchanged packets, added headers, a repeated header, a key, binary values, an empty batch, usage records and rows |
| `drops` | Missing and empty token, each invalid size header, the safe-integer limit, an unknown token, a quota-limited token, a null value that still bills |
| `rate-limit` | Partial batches, a per-team bucket override, a disabled team, an unparsable `created_at`, refill across batches, against real Redis |
| `produce-faults` | `MessageSizeTooLarge` (no retry), a retried timeout, a retriable error that exhausts 5 tries, a non-retriable error, a failed `app_metrics` write |
| `team-lookup` | A lookup error to the DLQ, a retriable lookup that recovers, one that fails the batch |
| `dlq-down-produce`, `dlq-down-lookup` | A failed DLQ write fails the background task |

## Status

| TypeScript | Rust | Status |
| --- | --- | --- |
| `parse-metrics-headers-step.ts`, `resolve-metrics-team-step.ts`, `drop-quota-limited-step.ts`, `prepare-metrics-message-step.ts`, `rate-limit-metrics-step.ts`, `produce-metrics-step.ts` | `pipeline::steps` | Done |
| `metrics-retry.ts` | `pipeline::retry` | Done |
| `services/metrics-rate-limiter.service.ts`, `services/metrics-redis.ts` | `pipeline::rate_limiter`, `service` | Done |
| `metrics-usage.ts`, `metrics-usage-steps.ts` | `pipeline::usage` | Done |
| `metrics-ingestion-pipeline.ts`, `metrics-pipeline-consumer.ts` | `pipeline::consumer` | Done |
| `config.ts`, `outputs/*`, `servers/ingestion-metrics-server.ts` | `service`, `bin/metrics-ingestion.rs` | Done, with shadow mode |
| `ingestion-otel-metrics.ts` | none | Not ported |

## How Node's `isRetriable` maps

`retryAfterFirstFailure` retries every error whose `isRetriable` is not `false`, and the team lookup rethrows only `isRetriable === true`.
`pipeline::retry::is_retriable` reads it from the Rust error types:

| Rust error | Node error | `isRetriable` |
| --- | --- | --- |
| `KafkaProduceError` with code 10 | `MessageSizeTooLarge` | `false` |
| any other `KafkaProduceError` | `LibrdKafkaError` | unset, so retried |
| `DependencyUnavailableError` (Postgres outage) | `DependencyUnavailableError` | `true` |
| `PipelineError` | an error with an explicit flag | its flag |
| anything else | a plain `Error` | unset |

## Known differences

- `ingestion-otel-metrics.ts` is not ported. Node pushes per-team `metrics_ingestion_bytes_ingested_total` and `metrics_ingestion_records_ingested_total` over OTLP; the Rust consumer does not, so a shadow cannot count twice.
- With no team enabled for rate limiting, the Rust limiter sends nothing to Redis. Node still runs an empty pipeline, which needs a pooled Redis client.
- The rate limiter falls back to the global bucket size when a script reply is missing, as Node does. The keyed limiter in `logs-ingestion` falls back to the team's size, which is why this crate has its own limiter.
- A Kafka message without a timestamp gives a usage record dated at the flush, as Node does for an undefined timestamp. What node-rdkafka passes for a missing broker timestamp was not checked.
- Header maps keep insertion order. A JavaScript object lists integer-like keys first, which no reader of the headers depends on.
- After a failed side effect, the Rust scheduler reports the failure once and clears it. Node keeps it latched, so every later background task fails too. Both end the process on the first failure.
- The pipeline is built per batch. Node builds it once; a Node pipeline that threw is not reused either, because the process exits.
- The Kafka source, outputs and shadow counters come from `logs-ingestion`, so their Prometheus names start with `logs_ingestion_`. The metrics-specific counters keep Node's `metrics_ingestion_*` names.
- `USAGE_INGESTION_TLS=true` is not supported, as in the logs consumer.
- `instrumentFn` spans and Kafka debug contexts are not ported.
