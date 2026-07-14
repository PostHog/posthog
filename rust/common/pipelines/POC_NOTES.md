# common-pipelines POC notes

This crate is a proof-of-concept for the design in
`rust-ingestion-pipelines-design.md`. It follows the POC execution plan
(`rust-pipelines-poc-plan.md`): working + unit-tested + honest over maximal. No
derive macros, no typestate build-gating, no Redpanda integration tests.

This file records where the implementation deliberately deviates from the design
doc, and why.

## Framework (Phase A)

### Executor uses type-erased steps, not a monomorphized `Chain`

The design doc (§3.3) describes consecutive sync steps fusing into "one pass over
the chunk ... with no intermediate collections", monomorphized as a tower-style
`Chain<A, B>`. Two requirements pull against that fusion:

1. The executor must record **which step decided** a terminal verdict, for the
   `last_step_name` metric label. A fused `Chain::apply` returns only the verdict,
   losing the deciding step's identity.
2. The design wants **type-changing** steps (`RawMessage -> WithHeaders -> ...`)
   within a sync segment.

To satisfy both cheaply, the executor stores each sync segment as a
`Vec<Box<dyn ErasedStep<Fx, O>>>`. Each step is wrapped so it downcasts its input
from `Box<dyn Any + Send>`, runs, and re-boxes its output. The **typed builder**
(`PipelineBuilder<In, Cur, ...>`) threads the current context type as a generic
parameter, so `.step()` only accepts a step whose input matches the current type —
the chain is checked at compile time exactly as the design intends, and the
downcasts inside the executor can never fail by construction (a mismatch is a
framework bug and panics with a clear message).

Cost of the deviation: one `Box` allocation per event per step boundary, versus
the design's zero-allocation `Continue` path. This is the "simplest working
alternative" the plan explicitly blesses (`Vec<Box<dyn ...>>`). A future
monomorphized `Chain` that tags verdicts with step names can replace the erased
executor without changing the public `Step`/`ChunkStep` traits.

### No typestate `handle_results` build-gating

The design (§3.3) gates `.build()` behind `.handle_results()` via typestate. Per
the POC plan ("no typestate build-gating"), `.build()` is unconditional and
result handling is a separate free function (`outputs::handle_results`) the caller
invokes on the `ChunkOutcome`. The `Outputs`/`OutputRegistry` split still gives a
startup check (`OutputRegistry::check`) that fails if an output has no topic.

### `Observer::on_verdict` drops the `EventView` argument

The design's `Observer::on_verdict` takes `event: &dyn EventView`. The POC passes
only `(step, VerdictKind, reason)` — enough for the built-in metrics observer and
the dry-run comparison use case, without designing an event-view abstraction that
no POC consumer needs yet.

### `fail_open` requires `In: Clone`

`FailOpen<S>` passes the original event through on error. To hand the event to the
wrapped step *and* still have it available on the error path, the input is cloned
before the inner `apply` call. The design left the choice open ("`In: Clone` or
takes-and-returns pattern — pick one"); `In: Clone` is the simpler of the two and
all POC contexts are cheap to clone (`Bytes` refcounts, small structs).

### `handle_results` awaits produces sequentially, not concurrently

The design (§3.4) flushes all deferred effects into an `EffectQueue` and joins
every produce future before the batch completes. The POC's `handle_results`
awaits each DLQ/redirect produce in turn. This still satisfies the load-bearing
property — every produce completes before the function returns, so a caller can
gate commit on it — but does not exploit intra-batch produce concurrency. A
future version can collect the futures and `join_all` them without changing the
signature.

### Two produce paths coexist: `EffectQueue` (plugins) and `handle_results` (verdicts)

The design routes *everything* (plugin effects and verdict DLQ/redirect produces)
through the `EffectQueue`, executed once at chunk end. The POC keeps them
separate: plugin sinks flush into an `EffectQueue` (A4), while verdict-driven
DLQ/redirect produces go straight through `handle_results` (A5) from the
`ChunkOutcome` + aligned `RawRecord`s. A full harness (`harness.rs` in the
design) would unify these; the POC omits that harness and lets the consumer wire
the two pieces together, which is enough to prove both mechanisms.

### `EffectProducer` is built directly on rdkafka, not `common/kafka`

The design (§3.10) layers the output registry over `common/kafka`'s
`FutureProducer`. The POC's `RdKafkaEffectProducer<C>` is generic over any
`rdkafka` `ClientContext`, so a caller can pass a `common/kafka` producer without
this crate depending on `common-kafka`. Keeps the framework free of a
service-adjacent dependency for the POC.

## Event restrictions promotion (A6)

`rust/capture/src/event_restrictions/` moved verbatim to the new
`common-event-restrictions` crate (`rust/common/event-restrictions`). Capture
re-exports it (`pub use common_event_restrictions::*;` in a thin
`capture/src/event_restrictions.rs` shim), so every existing
`crate::event_restrictions::…` path in capture still resolves and capture code is
untouched beyond imports.

One method could not move as-is: `Pipeline::for_capture_mode(CaptureMode)`
depended on capture's `config::CaptureMode`, which the shared crate must not know
about. It became a free function `pipelines_for_capture_mode(mode)` in the capture
shim (with its own unit test); its two call sites (`setup.rs`, a `process.rs`
test) were updated. Everything else — the manager, repository, types, and their
42 tests — moved unchanged (only the moved `manager.rs` test-module import paths
were rewritten from `crate::event_restrictions::…` to `crate::…`). Test-only deps
`rand` (mock repo key suffixes) and `chrono` are declared on the new crate.

## §capture — capture v1 policy phase on the framework (Phase B1)

Capture v1's analytics policy phase (`rust/capture/src/v1/analytics/process.rs`)
is rebuilt as framework steps. The adapter is
`rust/capture/src/v1/analytics/pipeline.rs` (`CaptureFx`, `CaptureOutputs`,
`run_in_place`). All work is inside `rust/capture`; nothing in `rust/common/*`
changed except this note.

### Parity strategy: steps wrap the unchanged `apply_*` functions

Hard constraint: existing v1 tests pass **unmodified** (that is the parity
proof). To guarantee byte-for-byte parity, the ported policy functions
(`apply_restrictions`, `apply_historical_rerouting`, `apply_overflow_stamping`,
`apply_token_distinct_id_limits`) keep their exact signatures and bodies. The
framework steps are thin wrappers that call them:

- **Async, whole-batch aggregate** (`ApplyRestrictions`,
  `ApplyTokenDistinctIdLimits`) → `ChunkStep`; the wrapper calls the `apply_*`
  fn on the whole chunk (`&mut Vec` → `&mut [WrappedEvent]`).
- **Sync, per-event** (`ApplyHistoricalRerouting`, `ApplyOverflowStamping`) →
  `Step`; the wrapper applies the `apply_*` fn to a one-event slice via
  `std::slice::from_mut(&mut event)`.

The `apply_*` fns remain the single source of truth; their tests exercise them
directly and are untouched. Consecutive sync steps (historical, overflow) fuse
into one executor segment, so their per-event order becomes
`h(e1),o(e1),h(e2),o(e2)` rather than `h(all),o(all)`. This is behavior-identical
here: both steps are purely per-event, their metrics are commutative counters,
and overflow's `destination == AnalyticsMain` guard makes it order-independent
(the code already noted this invariant).

### Verdict → per-event state mapping (the adapter contract)

Framework verdicts are `Continue | Drop | Dlq | Redirect`. Capture never
*removes* an event from the batch (v1 keeps every event in the response slice and
skips by `EventResult`), so:

- **Capture steps only ever return `Continue`.** A logical drop is realized as a
  `Continue` whose event was stamped `EventResult::Drop` + `Destination::Drop` +
  a `details` tag — "framework Drop ⇒ v1 per-event Drop result, NOT removal".
- **Redirects are `Destination` stamping, not framework `Redirect`.** Force-
  overflow / DLQ / custom-topic set `Destination` on the event; the unchanged
  sink layer turns that into the actual topic. Capture therefore never emits a
  framework redirect, and its `Outputs` type is `NoOutputs` (the compiler proves
  capture never redirects at the framework level).

Consequence: `run_in_place` moves the owned `Vec<WrappedEvent>` through
`Pipeline::run_chunk` and back via `into_survivors()`. Because every verdict is
`Continue`, survivors == inputs (same order, same length); a `debug_assert`
guards the invariant. Capture deliberately does **not** feed `Drop`/`Redirect`
verdicts to `run_chunk` — those discard the event value (`ItemOutcome::Terminated`
carries only a `Verdict`, not the `WrappedEvent`), which would lose the event.

### `fail_open()` is not applied — steps are intrinsically infallible

The plan asks that steps which fail open be wrapped `fail_open()`. Capture's
steps never return `StepError` (they call infallible `apply_*` fns), so they
already satisfy the capture-profile "infallible steps only" constraint without a
wrapper. The restriction fail-open behavior lives *inside*
`EventRestrictionService` (it returns an empty restriction set when its config is
stale), not at the step boundary. Independently, the framework `fail_open()`
combinator requires `In: Clone`, and `WrappedEvent` is **not** `Clone` (it holds
`Box<RawValue>`), so the combinator is inapplicable to capture events regardless
— intrinsic infallibility is the right fit here.

### Pipeline built per batch, not once at setup

The design (§3.9) hoped to construct the pipeline once at setup. The framework's
`Step: 'static` bound forbids steps borrowing request-scoped data, so steps own
their deps. Per-request inputs — `token`, `server_received_at`, the full
`RequestContext` (needed by `partition_key`) — are only available per batch, so
the pipeline is built per batch. Deps are cheap to capture: services are `Clone`
(Arc-backed: `EventRestrictionService`, `Arc<OverflowLimiter>`,
`Arc<GlobalRateLimiter>`), `HistoricalConfig` is `Copy`, and a single
`Arc<RequestContext>` snapshot is shared across the sync steps rather than cloned
per step. Steps are present in the pipeline only when their dep is configured,
matching the previous per-check `if let Some(..)` gating exactly.

### Not ported — left as plain functions (gate-phase / validation)

Per §3.9's gate-vs-policy split and the plan's B1.5 note, these stay plain
functions:

- `validate_batch`, `validate_events`, `normalize_timestamp` — request/validation
  phase that builds the `WrappedEvent`s the policy phase consumes.
- `apply_gateway_provenance` — pre-quota signature verification (gate-flavored:
  it fails *closed*, dropping unparseable forged-marker events).
- `apply_quota_limits` (quota limiter shim) — billing gate; async and fallible
  (`?` propagates a request-level error), i.e. request-gate-flavored rather than
  a per-event fail-open policy step. Modeling it as a `Gate` (§3.9) is future
  work.

`process_batch` now reads as: validate → provenance → quota → **one composed
policy pipeline** (restrictions → historical → overflow → token:distinct_id
limits) → serialize → publish.

## Consumer preprocess pipeline (Phase B2)

Lives entirely in `rust/ingestion-consumer/src/preprocess/` (`headers.rs`,
`context.rs`, `parse_headers.rs`, `deny_events.rs`, `restrictions.rs`,
`outputs.rs`, `mod.rs`). The pipeline is `ParseHeaders -> DenyEvents ->
ApplyEventRestrictions`, built on `common-pipelines` with `Fx = ()` (no plugins
— the steps are pre-team and emit no ingestion warnings). Gated behind
`PREPROCESS_MODE` (`off` default): when off, `Preprocessor::from_config` returns
`None`, the pipeline is never constructed, and `process_collected_batch` is a
straight passthrough — byte-for-byte the pre-B2 behavior.

### Kill switch is structural, not a branch

`off` isn't a runtime `if` inside the hot path — the `Option<Arc<Preprocessor>>`
is `None`, so the batch path calls `dispatcher.assign(collected.messages)`
exactly as before. Zero added allocations or awaits when disabled.

### Commit accounting for removed events

`ProcessedBatch.total_accepted` gates the offset commit. Terminated events
(drop / DLQ / redirect) are removed from dispatch but returned as
`PreprocessOutcome.removed_accepted`, which `process_collected_batch` adds to the
scatter's accepted count. So `survivors_dispatched + removed_accepted ==
batch_size` and the commit gate still closes. If preprocessing removes *every*
message, dispatch is skipped entirely and the batch commits on the removed count
alone (the pre-B2 "no healthy workers" bail is guarded behind a non-empty
survivor set). Unit tests: `enforce_counts_dropped_as_accepted`,
`enforce_produces_verdicts_and_counts_accepted`.

### Verdict production (B2.4 — done)

Implemented. In enforce mode with `INGESTION_OUTPUT_DLQ_TOPIC` /
`INGESTION_OUTPUT_OVERFLOW_TOPIC` configured, `Preprocessor::from_config` builds
a `common-kafka` `FutureProducer` and a framework `OutputRegistry`, and terminal
verdicts route through the framework's `handle_results` (Node-parity DLQ /
redirect provenance headers, produces awaited before the batch reports
accepted). A terminated event is counted as accepted only after its produce
acks; any `dlq_failed`/`redirect_failed` fails the batch (process exit,
redelivery) so nothing meant to land somewhere is silently dropped. Verified
with `MockProducer` (`enforce_produces_verdicts_and_counts_accepted`); real
Kafka production is not integration-tested (the POC plan forbids Redpanda
tests).

**Fallback** (no output topic configured, or the topics are empty): enforce mode
still enforces drops (removed + counted), but DLQ/redirect verdicts **fail open**
— the event is passed through to dispatch unchanged and a warning is logged.
Selected structurally by `outputs: Option<OutputRegistry>` being `None`
(`enforce_passthrough`).

### Producer liveness handle is shared, not dedicated

The preprocess producer reuses the consumer's `lifecycle::Handle` as its
`SyncLivenessReporter` rather than registering a dedicated lifecycle component.
Fine for the POC; a production version would isolate producer liveness so a
stuck producer trips its own deadline.

### Static restrictions only (dynamic Redis config deferred)

`ApplyEventRestrictions` is fed only the three static env lists
(`DROP_EVENTS_BY_TOKEN_DISTINCT_ID`,
`SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID`,
`INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID`), parsed into a shared
`common-event-restrictions` `RestrictionManager` (so token/filter matching is the
same code capture uses). The Redis-backed `EventRestrictionService` background
refresh is **not** wired (stretch goal per the plan). Consequence: no
fail-open-on-stale-config path exists here because there is no async config
source to fail — the static manager is infallible, so `ApplyEventRestrictions`
is not `fail_open()`-wrapped. `overflow_redirect` is hardcoded `true` whenever
the pipeline is constructed, so dry-run and enforce compute identical verdicts
(clean dry-run/enforce comparison); a real lane would gate this on lane config.

### No `Bytes` intake refactor

The consumer still collects messages as `SerializedKafkaMessage` (owned
`String` payload/key/headers). The pipeline input `RawMessage` is a **clone** of
each message's `HashMap<String, String>` headers, and DLQ/redirect `RawRecord`s
re-`Bytes`-wrap the owned `String`s. WP2.1's zero-copy `Bytes` intake is out of
scope for the POC; both clones vanish once intake hands over `Bytes`. All of
this cost is gated behind `PREPROCESS_MODE != off`.

### Header parsing parity gaps

`EventHeaders::parse` extracts the same 10 tracked headers as Node's
`parseEventHeaders` and emits the same `kafka_header_status_total{header,status}`
counter (present = truthy, mirroring Node). Not ported: `sanitizeString` on
`token`/`distinct_id` and `normalizeSessionId` on `session_id` — values are taken
verbatim. `now` is kept as the raw header string (not parsed to a timestamp); the
restriction `EventContext.now_ts` uses `Utc::now()` since the static manager
never consults it.

## Request-level rejection (`StepError::Reject`)

Design §3.9 sketches a "gate" phase for request-scoped fallible steps (decode,
auth, quota) that reject the whole request rather than a single event. The POC
realizes this as a second `StepError` variant rather than a separate `Gate`
trait: `StepError::Reject(anyhow::Error)` aborts the chunk exactly like
`Unexpected`, but is documented as an *expected, policy-driven* outcome, and the
caller recovers its own typed error via `StepError::try_into_reject::<E>()`
(anyhow downcast). This keeps the step vocabulary at one trait and one error
enum; a dedicated `Gate` trait with typed request/response phases remains open
for the real implementation if the reject-vs-unexpected distinction proves too
thin in practice.

## §capture, continued — full request→events pipeline breakdown

`process_batch` is now: request pipeline → guard → event pipeline → serialize →
publish (sink) → merge → response. Everything between the decoded request and
the sink is a pipeline step with a single responsibility:

- **Request pipeline** (`CaptureRequestPipeline<Vec<WrappedEvent>>`, one item =
  the request): `ValidateBatch` (structural request checks; rejects) →
  `ValidateEvents` (Batch → per-event `WrappedEvent` state; uuid integrity
  failures reject, malformed events are stamped `Drop`). The batch→events
  expansion is expressed as an ordinary type-changing `Continue` (`Batch` →
  `Vec<WrappedEvent>`) — the framework has no 1→N fan-out, and this avoids
  needing one.
- **Guard** (in `process_batch`, deliberately between the pipelines): an
  all-invalid batch answers 200 with per-event drops and must not reach the
  quota step (402) or the sink (may be unconfigured).
- **Event pipeline** (one `CapturePipeline`): `ApplyGatewayProvenance` (fail-
  closed) → `ApplyQuotaLimits` (global 402 via `StepError::Reject`; scoped
  limits stamp drops) → `ApplyRestrictions` → `ApplyHistoricalRerouting` →
  `ApplyOverflowStamping` → `ApplyTokenDistinctIdLimits` (optional steps gated
  on their dep being configured, as before).
- **Outside the pipeline:** `serialize_batch` (the sink boundary — it changes
  representation, not policy, and its scatter-gather + panic isolation is sink
  infrastructure), `publish_batch`, `merge_sink_results`, `BatchResponse`.

Other notes:

- `set_batch_metadata` moved before validation (it only stamps context fields;
  a rejected request never reads them). The `Arc<RequestContext>` snapshot is
  taken right after it and shared by every step of both pipelines.
- `run_in_place` is now fallible: `StepError::Reject` surfaces as the typed
  capture `Error` (via anyhow downcast in `reject_to_error`); any other error
  maps to a 500 instead of panicking on the request path. On rejection the
  event vec is left empty — matching the old `?`-return where the batch never
  reached the sink.
- The old `apply_gateway_provenance(state, ...)` wrapper is `#[cfg(test)]` —
  kept solely so the existing provenance tests run unmodified.
- Not steps, and why: `apply_quota_limits`'s inner shim and the other `apply_*`
  functions keep their bodies unchanged (steps are thin wrappers) so the
  existing direct-call tests remain the parity proof.
