# Capture outputs refactor — implementation plan

Working contract for implementation agents.
This doc is the first commit of the draft PR;
each `Step N` below becomes one commit in this combined PR
and later graduates to its own standalone PR.

This plan supersedes the sinks-everywhere plan
(`SINKS_REFACTOR_PLAN.md` on the `pl/ingestion/capture-sinks-refactor-sinks-v1` backup branch).
That branch reached its final state and taught us the target was one layer short:
a caller-facing two-phase `Sink` trait still mixed policy (routing, serialization choice)
into the mechanism layer,
and multi-target behaviors (split, failover) had to be implemented as sink composites
with information smuggled through serialized records.
Steps 1–3 of that plan survive verbatim here;
later machinery (hoisted prepare, breaker state machine, registry completeness)
is ported into the new shape, not rebuilt from scratch.
Port sources are named per step as `port: <commit> on -sinks-v1`.

## Context

**Goal.**
Layer `rust/capture`'s produce path into five strata with one-way dependencies:

```text
edge              → Pipeline {Analytics, Heatmaps, Warnings, ErrorTracking, Replay}
pipeline steps    → stamp intent (restrictions, overflow, historical)
lane resolution   → Lane {Main, Overflow, Historical, Dlq, Custom} + key policy + headers
outputs           → (Pipeline, Lane) → output = 1..n targets + selection policy
                     (single | failover(health) | split(token) | dual-write(pct))
serialization     → per-output: format (json | protobuf…) × envelope (none | lz4);
                     stamps content-type/encoding headers; produces sink-agnostic payload
sinks             → single backend: wrap payload into wire record (topic/key vs object key),
                     enqueue, ack. Kafka, S3, print, noop.
```

- **Pipeline** is decided at the edge (endpoint + event name) — the high-level
  "which product stream is this" classification.
- **Lane** is decided once, at the end of a pipeline, by folding the intent
  stamped during processing (restrictions, overflow reasons, historical flag)
  through one precedence chain. Today that chain is `route()` inside the Kafka
  sink; it moves up and runs before anything is serialized.
- **Output** is the named destination an event is published to, addressed by
  `(Pipeline, Lane)`. An output owns 1..n targets and the policy that picks
  between them per batch. All multi-target behavior lives here and only here.
- **Serialization** is a contract with the *consumers of a destination*, not a
  property of a transport. Each output names its format and envelope; the
  produced payload is sink-agnostic bytes plus the content headers that let
  old and new encodings coexist on a topic during migration (the existing
  replay lz4 `content-encoding` design, generalized).
- **Sink** is a single backend. It turns an addressed, serialized payload into
  its wire shape and acks it. It reads no event metadata and makes no decision.

**Why it exists.**
Three drivers, in order:

1. **Safe automatic failover** (the original driver, unchanged): Kafka-primary /
   S3-secondary failover as an output policy over any two targets, with the
   breaker ported intact.
2. **Cluster migrations without code changes**: split (AI → WarpStream) and
   dual-write become configuration of an output's targets, as in the Node.js
   `IngestionOutputs` module — capture and Node converge on the same model.
3. **Payload format evolution**: a protobuf cutover becomes an output-level
   config change behind the serialization seam, rolled out with content-header
   coexistence like the replay lz4 envelope.

**Where we start.**
The branch base is master (`54725e436d8`) plus Steps 1–3 below,
reproduced exactly from the superseded branch:
the routing golden oracle, the pure `route()`, and the `OutputRegistry`
with its startup completeness check.
Production call sites still publish through the v0 `Event` trait
(`send` / `send_batch`); the v1 stack (`CAPTURE_V1_SINKS`, opt-in) still runs
its own serialize-then-publish pipeline with a per-event response model.
The v1 `PreparedEvent { uuid, destination, payload: Bytes, headers, partition_key }`
is the shape our output→sink handoff adopts.

### Vocabulary rules

- **Pipeline** and **Lane** are the two halves of an event's address.
  Never reintroduce a flat destination enum that conflates them.
- **Output** = the addressed destination: targets + selection policy +
  serializer. **OutputTable** = the `(Pipeline, Lane)` → output mapping with
  the per-mode completeness check. The Step-3 `OutputRegistry` (output → topic)
  is absorbed into the table's targets.
- **Sink** = backend mechanism. Kafka, S3, print, noop. Nothing else is a sink;
  a thing that picks between sinks is an output policy.
- **Serializer** = format × envelope. Formats and envelopes compose; neither
  knows about sinks or outputs.

### Invariants (carry the old plan's, plus new ones)

- Metric names and labels stay stable:
  `capture_events_rerouted_*`, `capture_primary_sink_health`,
  `capture_fallback_sink_failovers_total`, `capture_split_sink_selected`,
  `capture_failover_breaker_*`, `capture_event_batch_size`.
  Renames are out of scope for every step.
- Wire parity is proven by the Step-1 goldens and existing endpoint/integration
  tests passing **unmodified**, except where a step explicitly says otherwise.
- Never mix a mechanical move with a behavior change in one commit.
- Every step ships green (`cargo test -p capture`, clippy `-D warnings`, fmt)
  and rolls back by plain revert.
- The per-event response model (v1 `BatchResponse`) stays out of scope; call
  sites keep folding per-event results into today's whole-request
  `CaptureError`.
- Sinks read no `ProcessedEventMetadata`. After Step 6 the only consumer of
  routing metadata is lane resolution.

## The stages and steps

### Stage A — oracle and groundwork (reproduced from -sinks-v1)

#### Step 1 · Consolidate the routing golden oracle

Reproduced exactly (`d38e26bbba0 on -sinks-v1`).
The `assert_routing` suite pins topic + partition key + every stamped header +
the rerouted counters for all pipelines and lanes.
It is the parity instrument for every later step.

#### Step 2 · Extract routing into a pure `route()`

Reproduced exactly (`488f685a44c on -sinks-v1`).
`route(&ProcessedEventMetadata) -> Route { target, key_policy, effect }`,
consulted by the sink.
This is the function Step 5 hoists out of the sink into lane resolution.

#### Step 3 · `OutputRegistry` + startup completeness check

Reproduced exactly (`7c2eb1bcffc on -sinks-v1`).
One output→topic wiring point plus refuse-to-boot on a blank topic.
Step 7 absorbs it into the `OutputTable`;
the mode-scoped demand (`d4801674e5b on -sinks-v1`) is folded in there,
where `(Pipeline, Lane)` makes the per-mode reachable set explicit.

### Stage B — the two new seams (no caller-visible change)

#### Step 4 · Serialization layer: format × envelope

- **Goal.** New `serialization` module:
  `Format` (event → payload bytes + `content-type`) with `Json` as the only
  impl, `Envelope` (bytes → bytes + `content-encoding`) with `None` and `Lz4`
  (the replay 4-byte LE size-prefix block format, moved verbatim), and a
  `Serializer` composing one of each.
  `prepare_record` calls the serializer instead of inlining
  `serde_json::to_string` + the lz4 branch.
  Replay's serializer is `Json × Lz4` when
  `kafka_replay_envelope_compression` says so; everything else `Json × None`.
- **Explicitly not in the serializer:** partition keys, routing headers,
  topics. Bytes and content headers only.
- **Files.** `rust/capture/src/serialization/` (new);
  `rust/capture/src/sinks/kafka.rs` (`prepare_record` consumes it).
- **Parity proof.** Step-1 goldens unmodified — including the lz4 goldens and
  `content-encoding` assertions. New unit tests on format/envelope composition.
- **Risk / rollback.** Low — mechanical hoist. Revert.
- **Size.** M.

#### Step 5 · `Pipeline` + `Lane`; lane resolution at pipeline end

- **Goal.** Introduce the address pair and move the decision up:
  - `Pipeline { Analytics, Heatmaps, Warnings, ErrorTracking, Replay }`,
    stamped where `DataType` is classified today
    (`DataType::from_event_name`, replay's separate ingress).
  - `Lane { Main, Overflow, Historical, Dlq, Custom(String) }`.
  - `resolve_lane(&ProcessedEventMetadata) -> LaneDecision { lane, key_policy, effects }`
    — Step-2's `route()` hoisted out of the sink and renamed, precedence
    unchanged (dlq > custom > historical > overflow > main). Runs as the last
    step of each pipeline (`events/analytics.rs` after overflow stamping,
    `ai_endpoint`, `otel`, `events/recordings.rs`); the DLQ/custom-topic
    header stamps and counters move with it.
  - `ProcessedEventMetadata` carries the resolved `(pipeline, lane, key_policy)`;
    the intent flags (`force_overflow`, `overflow_reason`, `redirect_to_dlq`,
    `redirect_to_topic`) become inputs to resolution and are no longer read
    below it. `DataType` stays only as the classification input and the v1
    bridge; the sink stops reading it.
- **Files.** `rust/capture/src/pipeline/` (new: types + `resolve_lane`);
  `rust/capture/src/v0_request.rs` (metadata);
  `rust/capture/src/events/analytics.rs`, `rust/capture/src/ai_endpoint.rs`,
  `rust/capture/src/otel/mod.rs`, `rust/capture/src/events/recordings.rs`;
  `rust/capture/src/sinks/kafka.rs` (consumes `LaneDecision`, drops `route()`).
- **Parity proof.** Step-1 goldens unmodified (the oracle asserts through the
  public produce path, which now spans resolution + sink). `route()`'s direct
  precedence tests become `resolve_lane` tests unchanged.
- **Risk / rollback.** Medium — touches every pipeline, but each move is a hoist.
  Revert.
- **Size.** L.

### Stage C — sinks become mechanism, outputs become the API

#### Step 6 · Narrow sinks to backend mechanism

- **Goal.** `PreparedPayload { uuid, payload: Bytes, headers, partition_key, topic }`
  (the v1 `PreparedEvent` shape, addressed) becomes the sink input.
  `trait Sink { publish(Vec<PreparedPayload>) -> Vec<SinkResult>; flush() }` —
  no prepare on the trait, no metadata access.
  Kafka keeps the three-phase batch mechanics
  (port: `a037f5b4e33 on -sinks-v1` — serial <8 / scatter-gather ≥8 prep is
  outputs-layer machinery now, serial enqueue + fail-fast ack drain stays in
  the sink). S3 writes payload bytes; print/noop trivial.
  The v0 `Event` trait survives this step as a thin bridge
  (resolve → serialize → publish inside the Kafka `Event` impl)
  so call sites don't move yet.
- **Files.** `rust/capture/src/sinks/` (trait, kafka, s3, print, noop).
- **Parity proof.** Step-1 goldens + `send_batch` three-phase suite unmodified.
- **Risk / rollback.** Medium-high — core mechanism. Revert.
- **Size.** L.

#### Step 7 · Outputs layer + `OutputTable`; analytics family migrates

- **Goal.** New `outputs` module:
  - `Output = { targets: 1..n of (sink, topic), policy: Single, serializer }`,
    `publish(Vec<ProcessedEvent>) -> Result<(), CaptureError>` — runs lane
    lookup, serializer, sink publish, result fold internally. Scatter-gather
    serialization for large batches lives here.
  - `OutputTable`: `(Pipeline, Lane)` → `Output`, built at boot from
    `KafkaConfig`; absorbs Step-3's `OutputRegistry` and the mode-scoped
    completeness demand (port: `d4801674e5b on -sinks-v1`) —
    an Events pod must wire the analytics family, a Recordings pod
    main/overflow/dlq only, and refuses to boot otherwise.
  - `events/analytics.rs` (5 pipelines ride it) publishes via the table;
    `capture_event_batch_size` recorded at the call site.
- **Files.** `rust/capture/src/outputs/` (new); `rust/capture/src/setup.rs`;
  `rust/capture/src/events/analytics.rs`; `rust/capture/src/router.rs`
  (State holds the table).
- **Parity proof.** Goldens + analytics integration suites unmodified.
- **Risk / rollback.** Medium. Revert.
- **Size.** L.

#### Step 8 · AI + OTEL migrate

- **Goal.** `ai_endpoint.rs` and `otel/mod.rs` publish via the `OutputTable`.
  Response semantics preserved exactly (first-failure-wins mapping, the OTEL
  `report_internal_error_metrics` path).
- **Parity proof.** ai (64) + ai_restrictions (7) + otel (21) suites unmodified.
- **Size.** S/M.

#### Step 9 · Replay migrates; `Event` trait deleted

- **Goal.** `events/recordings.rs` publishes via the table
  (session-id key policy, lz4 serializer, replay-overflow lane all already
  expressed in Steps 4–7); then delete the v0 `Event` trait, the Step-6
  bridge, and every `impl Event`. `State` and test mocks retype to the table /
  `Sink`.
- **Parity proof.** recordings + replay_restrictions + s_endpoint +
  kafka_headers suites green; grep proves `Event` call-site-free before the
  deletion half.
- **Size.** M.

### Stage D — multi-target policies and convergence

#### Step 10 · Split becomes an output policy

- **Goal.** `Policy::Split { secondary target, AiRouting }` — token-routed
  target selection *before* serialization; each partition serializes and
  publishes through its own target. Delete `SplitKafkaSink` and the
  token-header round-trip. `capture_split_sink_selected` kept.
- **Parity proof.** Split routing tests re-expressed at the output layer;
  AI endpoint suites unmodified.
- **Size.** M.

#### Step 11 · Failover becomes an output policy (advisory parity)

- **Goal.** `Policy::Failover { secondary target, mode: Advisory }` —
  kafka-primary / s3-secondary as a two-target output: skip primary while the
  advisory `lifecycle::Handle` is unhealthy, reactively re-publish the batch's
  *payloads* to the secondary on a retriable failure (payloads are
  sink-agnostic post-Step-4, so no re-serialization and no cross-format
  records). Delete `FallbackSink`.
  `capture_primary_sink_health` / `capture_fallback_sink_failovers_total`
  semantics identical.
- **Parity proof.** Fallback tests (incl. advisory-handle) re-expressed at the
  output layer, assertions preserved.
- **Size.** M.

#### Step 12 · Breaker failover mode (dark)

- **Goal.** `FailoverMode::Breaker` — port the pure clock-injected `Breaker`
  state machine, half-open single-probe permit, `StaticControlPlane` seam, and
  all 13+ deterministic tests (port: `62b3a43d7f1 on -sinks-v1`) as the
  second failover mode, dark behind `failover_enabled` (default off; off ⇒
  Advisory mode byte-identical).
- **Parity proof.** Breaker unit tests ported; existing tests unchanged.
- **Size.** M.

#### Step 13 · v1 converges on the shared strata

- **Goal.** v1's `Destination` bridges to `(Pipeline, Lane)`; v1 topic
  resolution goes through the shared table (port intent:
  `5f803e37d51 on -sinks-v1`); v1's `serialize_batch` uses the Step-4
  serializer. The v1 `Sink`/`Router` trait convergence stays gated on the
  per-event response model, as before.
- **Parity proof.** v1_pipeline (17) + v1_sink_integration (10) unmodified.
- **Size.** M/L.

## Agent conventions

**Build / test.** All cargo commands run via `flox activate -- cargo <cmd>`
from `rust/`.

**Acceptance per step:**

- `flox activate -- cargo test -p capture` — scope to the named suites where
  the full run is slow; the Step-1 goldens always run.
- `flox activate -- cargo clippy -p capture --all-targets -- -D warnings`
- `flox activate -- cargo fmt`

**Porting discipline.** When a step names a port source on `-sinks-v1`,
start from that commit's code (`git show <sha>:<path>`) and reshape;
do not rewrite from memory.
Test bodies port with assertions preserved.

**Git.** The orchestrator commits each step;
one step = one commit, subject from the tracker below.
No `--no-verify` — pre-commit hooks must pass.

## Progress tracker

| Step | Status | Commit subject |
| --- | --- | --- |
| 0 · This plan doc | done | `docs(capture): outputs refactor plan and progress tracker` |
| 1 · Routing golden oracle | done | `test(capture): consolidate routing golden oracle with headers and counters` |
| 2 · Pure `route()` | done | `refactor(capture): extract pure route() from prepare_record` |
| 3 · `OutputRegistry` + completeness | pending | `refactor(capture): output registry with startup completeness check` |
| 4 · Serialization layer | pending | `refactor(capture): serialization layer — format and envelope behind one seam` |
| 5 · `Pipeline` + `Lane`; lane resolution | pending | `refactor(capture): pipeline and lane address; lane resolution at pipeline end` |
| 6 · Sinks → backend mechanism | pending | `refactor(capture): narrow sinks to backend mechanism over prepared payloads` |
| 7 · Outputs layer; analytics migrates | pending | `feat(capture): outputs layer with (pipeline, lane) table; analytics on outputs` |
| 8 · AI + OTEL migrate | pending | `refactor(capture): ai and otel publish through outputs` |
| 9 · Replay migrates; `Event` deleted | pending | `refactor(capture): replay through outputs; retire v0 Event trait` |
| 10 · Split policy | pending | `refactor(capture): split routing as an output policy` |
| 11 · Failover policy (advisory) | pending | `refactor(capture): failover as an output policy` |
| 12 · Breaker mode (dark) | pending | `feat(capture): breaker-driven failover mode (dark)` |
| 13 · v1 convergence | pending | `refactor(capture): v1 resolves through shared pipeline/lane strata` |
