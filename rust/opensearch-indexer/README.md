# opensearch-indexer

Reverse-indexes `$ai_*` events into OpenSearch so LLM trace content is
keyword/phrase-searchable. Reads `clickhouse_events_json` (the same Kafka topic
ClickHouse consumes from), filters `$ai_*` at parse time, samples to keep cost
bounded, and bulk-writes the indexable subset to OpenSearch under the
`llm-traces` write alias.

Companion to:

- index template + local docker compose: [`products/llm_analytics/opensearch/`](../../products/llm_analytics/opensearch/)
- prod hot/ultrawarm cluster + ISM: `posthog-cloud-infra` Terraform; ISM
  auto-attaches via `ism_template` matching `llm-traces-v0_1-*`.

Search returns `{trace_id, score}` only. Trace bodies stay in ClickHouse;
the index is a pointer, not a copy. End-to-end lag from capture to
searchable is ~1 second, set by the bulk-flush cadence below. UX should
not assume a just-emitted trace is immediately findable.

## Flow

```text
clickhouse_events_json (Kafka)
  → parse $ai_*
  → sampling.decide() (Redis floor + above-floor rate)
  → mpsc
  → bulk writer (5 MiB / 1000 ms flush)
  → OpenSearch (llm-traces alias)
```

Indexed fields: `trace_id`, `team_id`, `model`, `provider`, `tool_names`
(keyword-only — args are not indexed), `is_error`, `cost`, `latency_ms`,
`input`, `output`, `error`, `@timestamp`. `_id` is `event_uuid`, so consumer
replay is a no-op re-PUT.

## Run locally

OpenSearch lives in the `opensearch_search` capability under the
`ai_features` intent:

```bash
bin/start ai_features
```

Direct: `cargo run -p opensearch-indexer`. Pre-flight checks
`_alias/llm-traces`; bootstrap of the local cluster is in
[`products/llm_analytics/opensearch/README.md`](../../products/llm_analytics/opensearch/README.md).

## Configuration

Standard kafka/redis/lifecycle env vars apply, plus:

| Var                        | Default                   | Notes                                                  |
| -------------------------- | ------------------------- | ------------------------------------------------------ |
| `OPENSEARCH_URL`           | `http://localhost:9201`   | dev points at the docker compose cluster              |
| `OPENSEARCH_INDEX_ALIAS`   | `llm-traces`              | write alias; readiness gate refuses startup if missing|
| `BULK_MAX_BATCH_BYTES`     | `5242880` (5 MiB)         | flush whichever fires first                           |
| `BULK_MAX_AGE_MS`          | `1000`                    |                                                        |
| `DEFAULT_FLOOR`            | `10000`                   | per-day per-team always-index floor                   |
| `DEFAULT_ABOVE_FLOOR_RATE` | `0.20`                    | bucketed by `trace_id`                                |
| `DENY_TEAMS`               | _empty_                   | comma-separated `team_id`s to drop                    |
| `TEAM_OVERRIDES`           | _empty_                   | JSON `{"42":{"floor":50000,"rate":0.5}}`              |
| `ROLLOUT_ENABLED`          | `false`                   | master gate; false ⇒ fast path skips Redis            |
| `ROLLOUT_TEAMS`            | _empty_                   | `*` for all, else comma-separated `team_id`s          |
| `ROLLOUT_PERCENTAGE`       | `0`                       | sticky knuth-bucket; `0..=100`                        |

Bad values fail startup loudly. Rate out of `[0, 1]`, non-numeric `team_id`
keys, percentage > 100, malformed JSON: hard error, no silent clamp.

## Module map

| File           | Responsibility                                                                |
| -------------- | ----------------------------------------------------------------------------- |
| `main.rs`      | wire-up: tracing, signal listener, readiness gate, lifecycle Manager          |
| `config.rs`    | envconfig + parsers (`RolloutTeams`, `TeamOverridesEnv`, `RolloutPercentage`) |
| `parser.rs`    | `clickhouse_events_json` → `IndexDoc`; non-`$ai_*` returns `Ok(None)`         |
| `sampling.rs`  | rollout gate + `decide()` → `Drop`/`IndexFloor`/`IndexSample`/`IndexError`/`Deny`/`NotEnrolled` |
| `work_loop.rs` | `run_consumer` + `run_sink`; offset-ordering, batching, retry-after backoff   |
| `bulk.rs`      | `BulkBatch`, `BulkWriter`, `RetryGate`; bulk-response classification          |
| `readiness.rs` | poll `_alias/<alias>` until 200 or shutdown                                   |
| `types.rs`     | `AiEvent` (in), `IndexDoc` (out), `SinkMsg`                                   |
| `api/`         | axum routes for liveness/readiness/metrics                                    |

## Sampling

Search is not exhaustive: only sampled-in traces appear in OpenSearch results.
The remainder still lives in ClickHouse but won't surface from a search query,
so a "no results" UI should say "no indexed traces matched", not "no traces
matched".

- Daily volume floor counted via Redis `INCR` keyed by `(team_id, YYYY-MM-DD)`,
  TTL 25h. Above the floor, a per-event coin flip at `rate` decides whether
  to index.
- Bucketing is keyed on `trace_id` (fallback `event_uuid`). All spans of one
  trace share the sample outcome — a trace either indexes wholly or not at
  all.
- Errors (`$ai_is_error: true`) bypass both the floor and the rate sample.
- Per-decision counters are recorded to `team_decisions:{team}:{date}` via a
  spawned `HINCRBY` task off the consumer's critical path. Best-effort drain
  on shutdown within 5s; aborted writes increment
  `opensearch_indexer_team_decisions_shutdown_aborted_total`.
- Decision label strings (`floor`, `sample`, `drop`, `deny`, `error`,
  `redis_error`, `not_enrolled`) are pinned. Renaming any variant re-buckets
  historical Redis hashes and Prometheus series.

## Redis fail-open

- One `INCR` per `$ai_*` event. 50 ms send and receive timeouts. On error,
  `decide()` returns `Err`; the consumer indexes the event and tags the
  Prometheus label `decision="redis_error"`. Redis-down does not halt
  ingest.
- Capacity: Redis ops/sec scales 1:1 with `$ai_*` event throughput. The
  per-event round-trip is the throughput ceiling.

## Offset commit ordering

Offsets are committed only by the sink, not the consumer. Both `Index` and
`Skip` messages flow through the mpsc channel so a non-`$ai_*` event at
offset N+1 cannot commit ahead of an in-flight `Index(...)` at offset N.

A per-partition low-water mark holds back commits at or above the lowest
unresolved retryable; SIGKILL mid-storm replays from the last fully-resolved
checkpoint.

## Bulk retry classification

- **Top-level retryable** (transport, 5xx, 429, 408): exponential backoff
  1s → 60s, uncapped attempts. Channel back-pressure pauses the consumer;
  cluster pressure flows back to Kafka via consumer-group lag. A brief
  OpenSearch outage doesn't lose traces: search lag grows during the
  outage, the index catches up after recovery.
- **Per-item ES_REJECTED**: a `RetryGate` widens between flushes and resets
  between storms. Sink `recv` is gated on `gate.ready()`; the mpsc fills
  during a degraded window so the batch can't grow unboundedly.
- **Item-count mismatch** on a bulk response: non-retryable, batch state
  preserved for the next flush.
- **Permanent per-item failures** (e.g. `mapper_parsing_exception`) are
  warn-logged. No Kafka DLQ producer in v1.

## Lifecycle

- **Readiness gate** refuses to bind HTTP until `_alias/<alias>` returns
  200. A failing gate in prod usually means rollover left the alias
  detached. Auto-creating a missing index would silently produce wrong
  mappings, so we'd rather fail loudly.
- **Early SIGTERM listener** is installed before the lifecycle Manager so
  readiness polling exits promptly when shutdown lands during startup.
- **Sink timer arm** checks `rx.is_closed() && rx.is_empty()` so a consumer
  panic during a closed-gate window can't hang the sink past the lifecycle
  stall threshold.

## Idempotent re-indexing

`_id = event_uuid` (UUIDv5 in upstream producers). Re-PUT is a no-op, so
consumer replay on SIGKILL doesn't double-write or duplicate-score.

## Schema source of truth

`products/llm_analytics/opensearch/llm-traces-v0_1.template.json`. Local
init container and Terraform both consume the same file. The
`tests/schema_drift.rs` integration test walks a synthetic event through
the parser and asserts the field shape matches the template.

Adding a new searchable field is a schema change to that template, and
the new field applies only to traces captured after the change rolls out.
Existing index documents are not backfilled, so historical traces stay
un-indexed on the new field.
