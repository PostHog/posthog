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

#### Step 5 · `Pipeline` + `Lane`; the lane decision becomes pipeline-layer code

- **Goal.** Introduce the address pair and relocate the decision logic:
  - `Pipeline { Analytics, Heatmaps, Warnings, ErrorTracking, Replay }`
    (`Pipeline::from_data_type` extracts the pipeline half of `DataType`).
  - `Lane { Main, Overflow, Historical, Dlq, Custom(&str) }`.
  - `pipeline::resolve(&ProcessedEventMetadata) -> LaneDecision { pipeline, lane, key_policy, effect }`
    — Step-2's `route()` moved out of the sink module wholesale, precedence
    unchanged (dlq > custom > historical > overflow > main), pure (no
    counters, no headers, no I/O). `KeyPolicy` and the effect enum move with
    it as decision *data*.
  - The sink keeps a private `output_for((pipeline, lane)) -> Outputs` bridge
    and still *invokes* `resolve` from its prep path — the invocation site
    moves up in Step 7 when the outputs layer exists to own it. This keeps
    the commit a pure relocation: no metadata changes, no call-site changes,
    goldens byte-identical.
- **Files.** `rust/capture/src/pipeline.rs` (new);
  `rust/capture/src/sinks/kafka.rs` (drops `route()`/`Route`/`KeyPolicy`/
  `RouteEffect`, gains the `output_for` bridge); `rust/capture/src/lib.rs`.
- **Parity proof.** Step-1 goldens unmodified. `route()`'s precedence tests
  move to `pipeline::tests` with assertions preserved, plus a pipeline
  classification test.
- **Risk / rollback.** Low-medium — mechanical relocation. Revert.
- **Size.** M/L.

### Stage C — sinks become mechanism, outputs become the API

#### Step 6 · Narrow the Kafka sink to backend mechanism

- **Goal.** New `sinks/sink.rs`:
  `PreparedPayload { uuid, record: ProduceRecord }` (serialized, addressed) is
  the sink input; `trait Sink { publish(Vec<PreparedPayload>) -> Vec<SinkResult>; flush() }`
  — no prepare on the trait, no metadata access — plus `Outcome` and
  `fold_results` (first failure wins).
  Kafka: `prepare_batch` (serial <8 / scatter-gather ≥8, fail-fast) extracted
  from `send_batch` as an inherent method the outputs layer will call;
  `impl Sink` = serial enqueue + fail-fast ack drain, reporting batch-uniform
  per-event results (the per-event surface refines only with the response
  model). `Event::send_batch` becomes the bridge: prep → publish → fold.
  Kafka only — s3/print/noop gain mechanism impls with the outputs layer,
  which is what needs them.
- **Sequencing decision.** `FallbackSink` and `SplitKafkaSink` are never
  ported onto the mechanism trait: the outputs layer owns multi-target
  policies (single | failover | split) from its first commit, built from the
  same config, and the Event-era composites are deleted when their last
  caller migrates. Old Steps 10/11 fold into Steps 7/9 accordingly.
- **Files.** `rust/capture/src/sinks/sink.rs` (new),
  `rust/capture/src/sinks/kafka.rs`, `rust/capture/src/sinks/mod.rs`.
- **Parity proof.** Step-1 goldens + `send_batch` three-phase suite unmodified
  (they now drive prep → publish → fold — the exact production path).
- **Risk / rollback.** Medium-high — core mechanism. Revert.
- **Size.** L.

#### Step 7 · Outputs layer with policies; composites retired

- **Goal.** New `outputs` module — the produce surface, with multi-target
  policy ownership from day one:
  - `Output`: a single backend, or a policy composing two *outputs* —
    `failover` (health-gated Kafka→S3: skip primary while the advisory handle
    is unhealthy, re-publish the batch on a retriable failure, fatal never
    fails over) and `split` (token-routed AI secondary). Targets are outputs
    themselves, so policies compose the way the old composites did (split
    over a failover pair). Policies operate on *events*, before prep — each
    target resolves topics and serializes for itself, exactly like the old
    per-sink `send_batch` paths, so parity is structural.
  - Leaves run the dance internally via the `pub(crate)` `Prepare` trait
    (prep → publish → fold); no caller ever sees a two-phase protocol.
  - `OutputTable`: the `(pipeline, lane)` → output handle the state holds;
    degenerate today (one deployment-wide output; per-lane topics resolve in
    prep via the `OutputRegistry`).
  - `setup::create_output` builds the policy tree from the same config;
    **`FallbackSink` and `SplitKafkaSink` are deleted**, their tests
    re-expressed on `Output` with assertions preserved (+ a new
    fatal-no-failover case).
  - Call sites are untouched: the table serves them through a transitional
    `Event` facade (which records `capture_event_batch_size`, where the old
    sink impls recorded it). Migration is Step 8.
- **Files.** `rust/capture/src/outputs.rs` (new); `rust/capture/src/setup.rs`;
  `rust/capture/src/sinks/{mod,s3,print,noop,test_sink}.rs` (mechanism +
  `Prepare` impls); `fallback.rs`/`split.rs` deleted.
- **Parity proof.** Goldens + all integration suites unmodified. Known
  metrics-only deltas, accepted: the batch-size histogram now records on the
  fallback-to-S3 path (it silently didn't before), and print/noop single
  sends record it (they didn't).
- **Risk / rollback.** Medium. Revert.
- **Size.** L.

#### Step 8 · Call sites migrate to the table; `Event` retired

- **Goal.** All four call sites (`events/analytics.rs`, `ai_endpoint.rs`,
  `otel/mod.rs`, `events/recordings.rs`) publish via `OutputTable::publish`,
  recording `capture_event_batch_size` at the call site; `State` and test
  mocks retype; then delete the v0 `Event` trait, the outputs facade, the
  Kafka `Event` bridge, and the single-event `kafka_send` path.
- **Parity proof.** All endpoint/integration suites green; grep proves
  `Event` call-site-free before the deletion half.
- **Size.** M/L. May split into per-call-site commits if the diff grows.

### Stage D — completeness, dark failover, convergence

#### Step 9 · Mode-scoped registry completeness

- **Goal.** `OutputRegistry::check_complete` scopes its demand per
  `CaptureMode` (port: `d4801674e5b on -sinks-v1`): an Events/Ai pod demands
  the analytics family, a Recordings pod main/replay-overflow/dlq only.
- **Parity proof.** Ported per-mode refusal + anti-over-demand tests.
- **Size.** M.

#### Step 10 · Breaker failover mode (dark)

- **Goal.** `FailoverMode::Breaker` — port the pure clock-injected `Breaker`
  state machine, half-open single-probe permit, `StaticControlPlane` seam, and
  all 13+ deterministic tests (port: `62b3a43d7f1 on -sinks-v1`) as the
  second failover mode, dark behind `failover_enabled` (default off; off ⇒
  Advisory mode byte-identical).
- **Parity proof.** Breaker unit tests ported verbatim; four output-level
  behavior tests (healthy-primary, open→fallback→recover cycle,
  control-plane-down, fatal-no-failover). Deviations, deliberate: the old
  DebuggingRecorder gauge test and the Notify-gated probe-concurrency test
  were not ported — the effective-route gauge and single-probe permit logic
  carried over verbatim, and those two harnesses graduate with the feature
  when it leaves dark mode.
- **Size.** M.

#### Step 11 · v1 converges on the shared strata

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

## Closing state

All steps are complete. The five strata are landed:

- **Pipelines and lanes.** `pipeline::resolve` is the one lane decision
  (dlq > custom > historical > overflow > main), pure over
  `ProcessedEventMetadata`; `Pipeline`/`Lane` are the event's address.
- **Outputs are the produce surface.** Every pipeline publishes through the
  `OutputTable`; the `Output` policy tree (single | failover | split) owns all
  multi-target behavior, composing the way the old sink composites did. The
  v0 `Event` trait, `FallbackSink`, and `SplitKafkaSink` are gone.
- **Serialization is a seam.** Format × envelope per destination, with
  content headers carrying encoding coexistence (the lz4 replay design,
  generalized); a protobuf cutover is an output-level config change.
- **Sinks are mechanism.** Kafka/S3/print/noop take prepared payloads and
  ack them; `Prepare` is backend SPI, never caller API. Prep still lives with
  each backend and migrates into the outputs layer without touching callers.
- **Breaker failover is dark-launched** behind `CAPTURE_FAILOVER_ENABLED`,
  ported intact from `-sinks-v1` as the failover output's autonomous mode.
- **v1 resolves topics through the shared `OutputRegistry`** via
  `Destination::as_output`. The v1 `Sink`/`Router` trait convergence stays
  gated on the per-event response model, as before.

## Progress tracker

| Step | Status | Commit subject |
| --- | --- | --- |
| 0 · This plan doc | done | `docs(capture): outputs refactor plan and progress tracker` |
| 1 · Routing golden oracle | done | `test(capture): consolidate routing golden oracle with headers and counters` |
| 2 · Pure `route()` | done | `refactor(capture): extract pure route() from prepare_record` |
| 3 · `OutputRegistry` + completeness | done | `refactor(capture): output registry with startup completeness check` |
| 4 · Serialization layer | done | `refactor(capture): serialization layer — format and envelope behind one seam` |
| 5 · `Pipeline` + `Lane`; lane resolution | done | `refactor(capture): pipeline and lane address; lane decision moves to the pipeline layer` |
| 6 · Kafka sink → backend mechanism | done | `refactor(capture): narrow the kafka sink to backend mechanism over prepared payloads` |
| 7 · Outputs layer with policies; composites retired | done | `feat(capture): outputs layer owns failover and split policies` |
| 8a · Call sites on the table | done | `refactor(capture): call sites publish through outputs` |
| 8b · `Event` retired | done | `refactor(capture): retire v0 Event trait` |
| 9 · Mode-scoped completeness | done | `refactor(capture): mode-scoped output registry completeness` |
| 10 · Breaker mode (dark) | done | `feat(capture): breaker-driven failover mode (dark)` |
| 11 · v1 convergence | done | `refactor(capture): v1 resolves through shared pipeline/lane strata` |
