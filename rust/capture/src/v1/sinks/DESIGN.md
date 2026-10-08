# v1/sinks design

Architecture and design choices in the `v1::sinks` module: how v1
capture turns request events into prepared events for the outputs layer
(`crate::outputs`), and how the outputs' results become the v1 response.

## Overview

v1 capture endpoints follow the naming scheme
`/i/v<version>/<scope>/<payload>/`:

| Endpoint | Path | Capture mode |
|---|---|---|
| Analytics events | `/i/v1/analytics/events/` | events, import |
| AI events | `/i/v1/ai/events/` | ai |

`CAPTURE_V1_ENABLED` registers them. v0 and v1 are different HTTP
endpoints, not different pipelines, so both publish through the same
outputs, producers and settings.

```text
                    ┌──────────────┐
                    │  HTTP layer  │
                    └──────┬───────┘
                           │  Vec<WrappedEvent>
                           ▼
                   ┌───────────────┐
                   │serialize_batch│─ scatter-gather (prepare.rs)
                   └───────┬───────┘
                           │  Vec<outputs::PreparedEvent>
                           ▼
          ┌─────────────────────────────────┐
          │ OutputRegistry::publish_prepared │─ shared with v0
          └────────────────┬────────────────┘
                           │  Vec<SinkResult>, one per event
                           ▼
                  ┌──────────────────┐
                  │merge_sink_results│─ per-event response
                  └──────────────────┘
```

Key properties:

- **Hoisted serialization** — events are serialized into `PreparedEvent`s
  by `serialize_batch` (`prepare.rs`) before any output sees them. This
  isolates CPU-bound encoding from produce I/O and enables the
  scatter-gather parallelism described in
  [section 2](#2-serialize_batch-scatter-gather).
- **Per-event results** — `publish_prepared` returns one result per
  prepared event, correlated back to request events by UUID.
- **Owned-payload API** — `Event::serialize()` returns `bytes::Bytes` and
  `partition_key()` returns a fresh `String`, keeping the trait simple and
  cheap to move into spawned tasks.

---

## 1. Event abstraction

`trait Event` (`event.rs`) decouples the publish path from any specific
capture endpoint, `CaptureMode`, or event schema:

```rust
pub trait Event: Send + Sync {
    fn uuid(&self) -> Uuid;
    fn should_publish(&self) -> bool;
    fn destination(&self) -> &Destination;
    fn headers(&self, ctx: &RequestContext) -> CapturedEventHeaders;
    fn partition_key(&self, ctx: &RequestContext) -> String;
    fn ordering(&self) -> OrderingGuarantee;
    fn serialize(&self, ctx: &RequestContext) -> anyhow::Result<bytes::Bytes>;
}
```

`headers` receives the request `RequestContext` so each `Event` implementation
can combine batch-scoped fields (token, now, historical_migration) with
event-scoped fields into a single `CapturedEventHeaders`
(`common_types`). The Kafka sink converts the returned struct to its
transport-specific format via `From<CapturedEventHeaders> for
OwnedHeaders`.

The analytics capture endpoint's `WrappedEvent` implements this trait
(see [section 5](#5-analytics-event-serialization)).
Other capture endpoints (e.g. session replay, exceptions) provide
their own `Event` implementations without changing the publish path.

### Context split

Trait methods take `&RequestContext` — the mode-agnostic request context
(token, IP, timing, raw query string) shared by every future capture mode.
The analytics endpoint wraps it in `analytics::Context { req, query }`,
which `Deref`s to `RequestContext`, so the typed `Query` stays an
analytics-only concern while the publish path remains capture-mode-agnostic.

### Owned-return serialization

`serialize(ctx)` returns `bytes::Bytes` and `partition_key(ctx)` returns a
fresh owned `String`. `Bytes` is zero-copy to construct from a `Vec<u8>`
and cheap (refcounted) to clone, so a `PreparedEvent` can be moved into a
tokio task, or held for a fallback output, without re-encoding.
The owned contract needs no shared mutable buffers, which is what makes
the scatter-gather prep loop safe to parallelize.

`WrappedEvent::serialize` pre-sizes its buffer via
`Vec::with_capacity(data.len() + 512)` to minimize reallocations
for typical payloads, then returns `Bytes::from(buf)`.

### Skip mechanisms

Callers have two orthogonal ways to prevent an event from being produced:

| Mechanism | Where set | Effect |
|---|---|---|
| `should_publish() == false` | Pipeline validation (e.g. `EventResult != Ok`) | Never prepared, no result |
| `Destination::Drop` | Routing logic (e.g. quota limiter) | `address()` returns `None`, never prepared |

### Header construction

Each `Event` implementation builds the full `CapturedEventHeaders`
struct per event, combining batch-scoped context (token, now,
historical_migration) with event-scoped fields (distinct_id, uuid,
timestamp, session_id, etc.):

```text
  ┌──────────────────────────────────────────────┐
  │ event.headers(ctx: &RequestContext)          │
  │                                              │
  │   CapturedEventHeaders {                     │
  │     token,                     ◄─ from ctx   │
  │     now,                       ◄─ from ctx   │
  │     historical_migration,      ◄─ from ctx   │
  │     distinct_id,               ◄─ from event │
  │     event,                     ◄─ from event │
  │     uuid,                      ◄─ from event │
  │     timestamp,                 ◄─ from event │
  │     session_id?,               ◄─ from event │
  │     force_disable_*?,          ◄─ from event │
  │     skip_heatmap_processing?,  ◄─ from event │
  │     dlq_reason/step/timestamp? ◄─ from event │
  │   }                                          │
  └──────────────────┬───────────────────────────┘
                     │
                     ▼
  ┌──────────────────────────────────────────────┐
  │ let headers: OwnedHeaders = headers.into();  │
  │   (From impl in common_types)                │
  └──────────────────────────────────────────────┘
```

The Kafka sink converts `CapturedEventHeaders` to `OwnedHeaders` via the
`From` impl in `common_types`. There is no separate merge function —
a single structured type flows from event to transport.

---

## 2. serialize_batch (scatter-gather)

`serialize_batch` (`prepare.rs`) is the mode-agnostic step that turns a
`Vec<E: Event>` into a `SerializedBatch` _before_ the outputs layer.
It is generic over the `Event` impl, so analytics, replay, and AI capture
modes share one implementation.

```rust
pub async fn serialize_batch<E: Event + Send + Sync + 'static>(
    events: Vec<E>,
    ctx: &RequestContext,
    scatter_gather_threshold: usize,
) -> (Vec<E>, SerializedBatch);

pub struct SerializedBatch {
    pub prepared: Vec<PreparedEvent>,           // publishable, in input order
    pub failures: Vec<SerializationFailure>,    // one per failed event
}
```

The caller gets its `Vec<E>` back so it can still build the per-event HTTP
response after publishing (the prepared events alone don't carry the
original request event). Recovery uses `Arc::try_unwrap` after the spawned
tasks finish — see "Ownership" below.

### PreparedEvent

`PreparedEvent` is the outputs layer's type (`crate::outputs`): an
`Address` (the v1 `Destination` mapped by `Destination::address`), the
ordering guarantee and raw partition key, the stamped headers, and the
`Bytes` payload. It carries everything an output needs to produce a
record, so the output does no serialization and holds no reference back
into the request.

### Sequential vs parallel

The threshold is configurable via `CAPTURE_V1_SCATTER_GATHER_MIN_BATCH`
(default 8). Set to 0 to force sequential serialization for all batch
sizes (useful for modes like replay where batches are always single large events).

```text
  scatter_gather_threshold == 0  OR  events.len() < threshold
    └── serialize inline on the request task (no spawn overhead)

  events.len() >= threshold  (threshold > 0)
    └── Arc<Vec<E>> + Arc<RequestContext>
        └── JoinSet of tokio tasks (spawn, not spawn_blocking), one per event index
            └── each task: catch_unwind(prepare_one(&events[i], &ctx))
        └── collect by index → preserves input order
```

Small batches stay inline because a `JoinSet` of tokio tasks costs more
than the serialization itself for a handful of events. Large batches fan
out across the async worker pool to cut tail latency on big payloads. We
use `spawn` (not `spawn_blocking`) to match v0's `send_batch`: per-event
serialize is short CPU work, so concurrent execution is naturally bounded
by `worker_threads` (~num_cpus) and excess events queue cheaply, rather
than spawning one blocking-pool task per event and risking saturation of
the shared `spawn_blocking` pool on very large batches. Both paths produce
identical output (ordering, skips, failures)
— verified by parity tests in `prepare.rs`.

### Panic isolation

Each event is serialized inside `std::panic::catch_unwind`. A panic in one
event's `serialize` becomes a `SerializationFailure { is_panic: true }`
for that event only; the rest of the batch is unaffected. Regular `Err`
returns become `SerializationFailure::from_error`. Both are fatal
(non-retriable) — re-running the same bytes would panic/err again.

### Ownership (Arc::try_unwrap)

`spawn` requires `'static`, so the parallel path wraps the events
in `Arc<Vec<E>>` and tasks borrow by index. After the `JoinSet` drains,
every task has dropped its `Arc` clone, so `Arc::try_unwrap` reclaims the
sole-owner `Vec<E>` and hands it back to the caller. This is why
`serialize_batch` can be parallel yet still return owned events.

### Metrics

| Metric | Type | Labels | When |
|---|---|---|---|
| `capture_v1_serialize_duration_seconds` | histogram | `batch_size` | Per-batch serialize wall-time (sequential or parallel) |
| `capture_v1_serialize_failed_total` | counter | — | Per event that failed to serialize |
| `capture_v1_serialize_panic_total` | counter | — | Per event whose `serialize` panicked |

These are output- and product-agnostic (serialization happens before any
output sees the batch). Per-mode faceting comes from the Kubernetes deployment
(`capture-analytics` / `-replay` / `-ai`) via the `namespace` label
injected by the metrics pipeline.

---

## 3. Publishing and the response

`process_batch` hands the prepared events to
`OutputRegistry::publish_prepared`, the same outputs v0 publishes
through: one producer and one set of settings for both endpoint
versions. The registry returns one `SinkResult` per prepared event, in
input order, and a failure fails only its own event.

`merge_sink_results` correlates serialize failures and output results
back to the request events by UUID:

| Result | `EventResult` | `details` |
|---|---|---|
| published | unchanged (Ok or Warning) | unchanged |
| `RetryableSinkError` | Retry | `not_persisted` |
| `EventTooBig` | Drop | `event_too_big` |
| any other output error | Drop | `rejected` |
| serialize error | Drop | `serialization_failed` |
| serialize panic | Drop | `rejected` |

---

## 4. Destination routing and partition key resolution

### Destination

The `Destination` enum (`types.rs`) represents the semantic routing
target for a processed event, _before_ any output resolves it to a
topic:

```rust
pub enum Destination {
    AnalyticsMain,           // normal analytics events
    AnalyticsHistorical,     // historical migration imports
    Overflow,                // overflow-routed events
    Dlq,                     // dead letter queue (event restriction)
    ExceptionErrorTracking,  // $exception events → error tracking pipeline
    HeatmapMain,             // $$heatmap events → heatmap ingestion
    ClientIngestionWarning,  // $$client_ingestion_warning events
    Custom(String),          // custom topic passthrough
    Drop,                    // do not produce
}
```

`Destination::is_analytics_pipeline()` returns `true` for
`AnalyticsMain` and `AnalyticsHistorical` only. This gate controls
which events are subject to analytics-scoped restrictions, overflow
routing, and related pipeline logic.

`Destination::address()` maps each destination to the outputs layer's
`Address`; the Kafka sink resolves the address to its output's topic and
producer, read from `CAPTURE_OUTPUT_<OUTPUT>_TOPIC` and
`CAPTURE_OUTPUT_<OUTPUT>_PRODUCER`.

### Partition key resolution

Partition key construction is split between the `Event` implementation
and the Kafka sink:

1. **`Event::partition_key(ctx)`** returns an owned key String, captured
   into `PreparedEvent.partition_key` by `serialize_batch`.
   For analytics events (`WrappedEvent`):

```text
  ┌───────────────────────────────────────────────────┐
  │ partition_key(ctx) -> String                       │
  │                                                    │
  │   cookieless_mode?                                 │
  │   ├── yes, capture_internal → "token:127.0.0.1"   │
  │   ├── yes, normal           → "token:client_ip"   │
  │   └── no                    → "token:distinct_id"  │
  └───────────────────────────────────────────────────┘
```

2. **`PreparedEvent::ordering`** decides whether the prepared key is used.
   `Event::ordering()` returns an `OrderingGuarantee` (`crate::ordering`,
   shared with v0) and the Kafka sink passes `None` to rdkafka for
   `OrderingGuarantee::None`, `Some(prepared.partition_key)` otherwise.

   `WrappedEvent::ordering` gives up the guarantee only on the lanes that
   exist to absorb hot keys (`AnalyticsMain`, `Overflow`,
   `AiEventsOverflow`). On the person-writing lanes (`AnalyticsMain`,
   `Overflow`) that takes `force_disable_person_processing`; a
   `spread_partitions` stamp alone takes effect only on the read-only
   `AiEventsOverflow` lane (`Destination::writes_persons`). It is computed
   at prepare time rather than stamped during processing because it
   depends on the final destination, which `apply_historical_rerouting`
   can still change after `apply_restrictions` has disabled person
   processing.

Key design choices:

- **The person-processing header is not a control channel.** Nulling the
  key is driven by `ordering`, never by reading
  `headers.force_disable_person_processing` back out. That header is an
  instruction to downstream to skip identity resolution, so using it to
  request partition spreading silently disabled person processing for
  every rate-limited overflow event.
- **`spread_partitions` is separate from person processing.** The overflow
  limiter sets it alone when a key merely exceeds its burst budget, leaving
  person processing on. The spread takes effect only where the
  consumer does not write persons (the AI overflow lane); on the analytics
  lanes the key holds until person processing is off, because spreading one
  distinct id across partitions contends the consumer's person updates. A
  `ForceLimited` verdict sets both flags, matching v0.
- **`None` = round-robin.** `None` is passed to rdkafka, which
  round-robins across partitions. Passing `Some("")` would hash to a
  single deterministic partition via murmur2, creating a hot spot.
- **DLQ/Historical/Custom/AI-main retain key** even when
  `force_disable_person_processing` is set. Only the analytics main and
  overflow lanes and the AI overflow lane drop it, matching v0's
  `route()`.
- **Cookieless mode** uses `token:client_ip` as partition key instead
  of `token:distinct_id`, with IP redacted to `127.0.0.1` for
  `capture_internal` requests.

---

## 5. Analytics event serialization

The `v1::analytics::WrappedEvent` is the concrete `Event` implementation
for the analytics capture endpoint (`/i/v1/analytics/events/`). It
bridges the new v1 event schema (`Event`, `Options`, raw `properties`)
to the legacy `IngestionEvent` shape that downstream ingestion workers
expect.

### Data flow

```text
  ┌─────────────────────────┐
  │  Inbound v1 Request     │
  │                         │
  │  Batch {                │
  │    created_at,          │
  │    historical_migration,│
  │    batch: [Event, ...]  │
  │  }                      │
  └───────────┬─────────────┘
              │ parse + validate
              ▼
  ┌─────────────────────────┐
  │  WrappedEvent           │
  │                         │
  │  event: Event {         │      ┌────────────────────────────┐
  │    event, uuid,         │      │  Event::Options            │
  │    distinct_id,         │      │    cookieless_mode         │
  │    timestamp,           │      │    disable_skew_correction │
  │    session_id?,         │      │    product_tour_id         │
  │    window_id?,          │      │    process_person_profile  │
  │    options ─────────────┼─────▶└────────────────────────────┘
  │    properties (RawValue)│
  │  }                      │
  │  uuid: Uuid (pre-parsed)│
  │  adjusted_timestamp     │
  │  result: EventResult    │
  │  destination: Destination│
  │  force_disable_*        │
  └───────────┬─────────────┘
              │ serialize(ctx)
              ▼
  ┌──────────────────────────────┐
  │  IngestionEvent (Kafka msg)  │
  │                              │
  │  uuid, distinct_id, ip,     │
  │  token, event, timestamp,   │
  │  now, sent_at,              │
  │  is_cookieless_mode,        │
  │  historical_migration,      │
  │  data: IngestionData (JSON) │
  │    ├── event                 │
  │    ├── distinct_id           │
  │    ├── uuid                  │
  │    ├── timestamp (original)  │
  │    └── properties (merged)   │
  │        ├── original props    │
  │        ├── $session_id       │
  │        ├── $window_id        │
  │        ├── $cookieless_mode  │
  │        ├── $ignore_sent_at   │
  │        ├── $product_tour_id  │
  │        └── $process_person_* │
  └──────────────────────────────┘
```

### Property injection (surgery)

The v1 schema promotes `session_id`, `window_id`, and `Options` fields
to typed, top-level event fields. Legacy ingestion workers expect these
inside `event.properties` under `$`-prefixed keys.

Rather than deserializing the entire properties blob (which is forwarded
as opaque `Box<RawValue>`), `build_property_injections` performs
string-level JSON surgery:

1. Build a comma-separated fragment of `"$key":value` pairs for
   non-`None` option fields.
2. If the fragment is non-empty, splice it into the raw JSON object
   just before the closing `}`.
3. Validate the result via `RawValue::from_string`.

This avoids a full `serde_json::Value` round-trip and preserves the
original property ordering and formatting.

| v1 field | Injected property key | Notes |
|---|---|---|
| `session_id` | `$session_id` | |
| `window_id` | `$window_id` | |
| `options.cookieless_mode` | `$cookieless_mode` | |
| `options.disable_skew_correction` | `$ignore_sent_at` | Legacy rename. v1 reads only `disable_skew_correction` |
| `options.product_tour_id` | `$product_tour_id` | |
| `options.process_person_profile` | `$process_person_profile` | |

`RawOptions::validate` reads the four expected option keys before injection and ignores every other key:

- Boolean options accept booleans, numbers (zero is off), `true`/`t`/`yes`/`y`/`on`/`1` and `false`/`f`/`no`/`n`/`off`/`0` in any case, and numeric strings. `null` and blank strings mean "not set".
- `product_tour_id` accepts a non-empty string, forwarded unchanged, or an integer, forwarded as its decimal string. `null` and blank strings mean "not set".
- Any other value for an expected key drops the event with `invalid_options`, and emits the `invalid_options` ingestion warning, whose `invalidOptions` detail names the failed keys.
- The batch-level `capture_internal` and `historical_migration` flags use the same boolean reader. An unreadable value means "not set" and never fails the batch.

### IngestionEvent / IngestionData

`IngestionEvent` is the Kafka message payload, field-order-compatible
with `common_types::CapturedEvent` so downstream deserializers work
unchanged.

`IngestionData` is the double-encoded `data` field within
`IngestionEvent`. It carries the event name, distinct_id, uuid,
original (un-adjusted) timestamp, and the merged properties blob.

Fields intentionally omitted vs the legacy `RawEvent`:

| Omitted field | Reason |
|---|---|
| `token` | v1 uses Authorization header; downstream handles absence |
| `offset` | Dead field; Node.js ingestion parses but never reads it |
| `$set`/`$set_once` (top-level) | Legacy Python SDK cruft; v1 schema sends these inside `properties` |

### IP redaction

`capture_internal` requests (events the Django app sends on behalf of a customer team) have their IP
redacted to `127.0.0.1` in both `serialize` (the `ip` field on
`IngestionEvent`) and `partition_key` (cookieless mode).

---

## 6. Testing

### Analytics event serialization tests

`v1::analytics::types` has a comprehensive test suite validating:

- **Round-trip parity**: `WrappedEvent::serialize` output
  deserializes as `common_types::CapturedEvent` + `RawEvent`, verifying
  field-by-field compatibility with legacy capture.
- **Property injection**: all option fields are correctly injected into
  properties with `$`-prefixed keys.
- **IP redaction**: `capture_internal` → `127.0.0.1`.
- **Partition key × destination × person-processing matrix**: key
  presence/absence for all combinations.
- **Header completeness**: distinct_id, event, uuid, timestamp,
  session_id, force_disable_*, DLQ headers.
