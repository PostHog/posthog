# Capture sinks-everywhere refactor — implementation plan

Working contract for implementation agents.
This doc is the first commit of the draft PR;
each `Step N` below becomes one commit in this combined PR
and later graduates to its own standalone PR.

File:line references were verified against `PostHog/posthog@b3db0b9993` (master)
and are carried here as plain text.

## Context

**Goal.**
Make the unified, v1-shaped `Sink` the *only* sink model in `rust/capture` —
every pipeline, every endpoint —
and retire the v0 `Event` trait.
Routing becomes data (a pure `route()`), serialization is hoisted out of the sink,
one `OutputRegistry` covers every destination,
and automatic failover lives entirely behind the `Sink` trait.
This is Phase 1 of the evolution plan; it is capture-local
and does not depend on the pipelines framework.

**Why it exists.**
The master plan's #1 driver is safely adding an automatic failover / circuit breaker.
That is only safe once *all* production traffic runs through one sink trait,
so the failover logic can be encapsulated behind it (Step 11).
Everything before Step 11 is the groundwork that makes that encapsulation possible.

**Where we start — two parallel sink stacks.**

- v0 `Event` trait (production): `send(ProcessedEvent)` / `send_batch(Vec<ProcessedEvent>)`
  → `Result<(), CaptureError>`.
  Serializes *inside* the sink (`prepare_record` serializes + lz4-envelopes);
  routing is a `match data_type` inside `prepare_record`;
  request-scoped error model; concrete `FallbackSink` + AI-only `SplitKafkaSink`.
  Serves all 6 pipelines, all endpoints.
- v1 `Sink` / `Router` (opt-in, gated on `CAPTURE_V1_SINKS`):
  `publish_batch(ctx, &[PreparedEvent])` → `Vec<Box<dyn SinkResult>>`.
  Serialization hoisted into `serialize_batch` → `PreparedEvent`;
  routing via `Destination` enum + `topic_for`;
  per-event `SinkResult` / `Outcome` error model;
  `Router` dispatches by `SinkName` (dual-write).
  Wired only for the v1 analytics handler.

The refactor promotes the v1 shape into the shared `capture::sinks` module,
turns v0 `Event` into a thin delegating shim, migrates the four call sites,
deletes the shim, then converges the v1 path onto the unified module.

### Vocabulary rules

- **Outputs / OutputRegistry** = the topic-completeness surface.
  The promoted `Destination` enum becomes `Outputs` (for Node parity);
  the registry that maps each output → configured topic is the `OutputRegistry`.
- **Sink** = the trait that produces events (mechanism: enqueue, ack-drain, health gate).
- Never write `SinkRegistry`.
  The registry is always the `OutputRegistry`.

### Two-surface clarification (do not conflate)

There are two distinct "routing" concepts in v1:

- **Router** = physical `SinkName` dispatch — `Msk`, `MskAlt`, `Ws`,
  i.e. physical Kafka clusters for dual-write and cutover; holds a `default`.
  This is `rust/capture/src/v1/sinks/router.rs:41`.
- **OutputRegistry** = `Destination`/`Outputs` → topic completeness.
  This is `KafkaConfig::topic_for` (`rust/capture/src/v1/sinks/kafka/config.rs:152`).

The master plan's "outputs" model and the startup completeness check map to the
`Destination`/`topic_for` surface — **not** the `Router`.
Topic selection and physical-cluster dispatch are separate concerns; keep them separate.

## Corrections from the verification pass

These five corrections against the current tree carry into the steps below:

1. **Goldens already exist** — do not author from scratch.
   `rust/capture/src/sinks/kafka.rs` already ships a table-driven `assert_routing`
   suite (~line 1256 onward): `analytics_main_*`, `analytics_historical_*`, `snapshot_*`,
   `heatmap_*`, `exception_*`, `client_ingestion_warning_*`, the custom-topic precedence
   cases (`analytics_main_redirect_to_topic`), and lz4 compression
   (`snapshot_payload_lz4_compressed_when_enabled`).
   Step 1 is **consolidate + extend**, not "author".
2. **Step 4 is not a drop-in wrap.**
   v1 `Sink::publish_batch` consumes *already-serialized* `PreparedEvent`s and needs a
   `RequestContext`; v0 `prepare_record` serializes inside the sink and has no context.
   Step 4 must first **hoist serialize + prepare** for the v0 path
   (build `PreparedEvent` from `ProcessedEvent`, reusing the Step-2 `route()`) before wrapping.
3. **Step 3 introduces the completeness check** — it does not replace existing asserts.
   There are no literal topic `assert!`s in `setup.rs`;
   the duplication is two topic-config structs (`KafkaTopicConfig` vs v1 `topic_for`),
   and there is *no* cross-destination completeness check today
   (v1 `Config::validate` checks hosts/timeouts only).
   Step 3 *introduces* that check while centralizing the wiring — the #68719 seam.
4. **Stage C = exactly four call sites** (analytics, ai, otel, recordings) — confirmed.
   The analytics call site carries five pipelines
   (Analytics, Heatmaps, Client warnings, Exceptions all ride `process_events`),
   so the six-pipeline migration is four edits.
5. **Two surfaces, not one** — see the two-surface clarification above.

## The stages and steps

### Stage A — make routing data, not code (no behavior change)

Establishes the parity oracle and lifts routing out of the sink mechanism.

#### Step 1 · Consolidate the routing golden oracle

- **Goal.** Freeze the current `prepare_record` topic / key / header decisions behind one
  explicit, exhaustive golden test that every later step diffs against.
- **Files.** `rust/capture/src/sinks/kafka.rs` (tests module, ~1256–2040).
  The existing `assert_routing` suite is the seed;
  extend each case to assert the emitted headers
  (`force_disable_person_processing`, `skip_heatmap_processing`,
  DLQ `reason`/`step`/`timestamp`, replay `content-encoding`)
  and the `capture_events_rerouted_dlq` / `capture_events_rerouted_custom_topic` counters —
  not just topic + partition key.
- **Parity proof.** The suite *is* the oracle;
  it must pass unchanged (except additive assertions) through Steps 2–9.
- **Risk / rollback.** None — test-only. Revert.
- **Size.** S (tests only).
- **Unblocks.** Every later step diffs against this.

#### Step 2 · Extract routing into a pure `route()`

- **Goal.** Lift the `match data_type { … }` block (`rust/capture/src/sinks/kafka.rs:482`)
  out of `prepare_record` into a pure
  `route(&ProcessedEventMetadata) -> Route { topic, key_policy, headers }` the sink consults.
  Serialization and the lz4 envelope stay in the sink for now
  (they depend on payload bytes, not on the routing decision).
- **Files.** `rust/capture/src/sinks/kafka.rs` (`prepare_record`, 402–570; new `route`);
  `rust/capture/src/v0_request.rs:219` (`ProcessedEventMetadata`, read-only).
  Mirrors v1's already-shipped `Destination` + `topic_for` split (the convergence target).
- **Parity proof.** Step-1 goldens unchanged;
  add direct unit tests on `route()` for DLQ → custom-topic → per-datatype precedence.
- **Risk / rollback.** Low — mechanical extraction. Revert.
- **Size.** M.
- **Unblocks.** Step 3 (registry consults route targets), Step 4 (the shim).

#### Step 3 · Output registry + startup completeness check (#68719 seam)

- **Goal.** Collapse the two parallel topic-config surfaces —
  v0 `KafkaTopicConfig` (`rust/capture/src/sinks/kafka.rs:174`)
  and v1 `topic_for` (`rust/capture/src/v1/sinks/kafka/config.rs:152`) —
  into one `OutputRegistry` keyed by the promoted `Outputs` enum (today's `Destination`),
  and add a **startup check** that every non-`Drop` output resolves to a configured,
  non-empty topic. Config keys are unchanged; only their wiring centralizes.
- **Correction in play.** There is no completeness check today —
  adding a topic currently means editing `KafkaTopicConfig`, the `match`, *and*
  v1 `topic_for` in lockstep. That triple-touch is the #68719 sprawl this step removes.
- **Files.** `rust/capture/src/sinks/kafka.rs`, `rust/capture/src/v1/sinks/types.rs:11`,
  `rust/capture/src/v1/sinks/kafka/config.rs:152`,
  `rust/capture/src/setup.rs:486` (`create_sink` / `create_v1_sink_router`).
- **Parity proof.** Existing config tests +
  a new "missing topic → refuse to boot" test per `CaptureMode`.
- **Risk / rollback.** Medium — changes startup behavior
  (a misconfig now fails fast instead of at first produce). Revert; no data migration.
- **Size.** M.
- **Unblocks.** Step 10 (registry everywhere), Step 4.

### Stage B — one sink trait (v0 `Event` becomes a shim)

Promote the v1 `Sink` shape to the shared module;
keep the four call sites frozen by making `Event` a thin delegating shim.

#### Step 4 · Promote `Sink`; make `Event` a shim

- **Goal.** Move the v1 `Sink` trait (`rust/capture/src/v1/sinks/sink.rs:9` —
  `publish_batch(ctx, &[PreparedEvent]) -> Vec<Box<dyn SinkResult>>`, health gate in the impl)
  into the shared `capture::sinks` module,
  implement it for the Kafka mechanism by wrapping today's `KafkaSinkBase`
  (`rust/capture/src/sinks/kafka.rs:211`),
  and keep `sinks::Event` (`rust/capture/src/sinks/mod.rs:14`) as a shim delegating to `Sink` —
  collapsing per-event `SinkResult`s back into today's request-scoped
  `Result<(), CaptureError>`. Zero call sites change.
- **Correction — not a drop-in wrap (prerequisite hoist).**
  `Sink::publish_batch` consumes *already-serialized* `PreparedEvent`s:
  serialization and the lz4 envelope are hoisted out of the sink into `serialize_batch`
  (`rust/capture/src/v1/sinks/prepare.rs`),
  and it needs a `RequestContext` (`rust/capture/src/v1/context.rs`).
  v0 `prepare_record` serializes inside the sink and builds no context.
  So Step 4 (or a split Step 4a) must **first** hoist serialize + prepare for the v0 path —
  building a `PreparedEvent` from a `ProcessedEvent` and reusing the Step-2 `route()`
  for its destination.
  The shim then serializes, calls `publish_batch`, and folds results:
  any non-`Success` `Outcome` maps back to the existing
  `RetryableSinkError` / `NonRetryableSinkError` so whole-request semantics are
  byte-for-byte preserved.
- **Files.** `rust/capture/src/sinks/mod.rs`, `rust/capture/src/sinks/kafka.rs`,
  `rust/capture/src/v1/sinks/sink.rs`, `rust/capture/src/v1/sinks/prepare.rs`,
  `rust/capture/src/v1/sinks/types.rs`.
- **Parity proof.** Step-1 goldens + the existing `KafkaSinkBase` `send`/`send_batch` tests
  (the three-phase `send_batch` suite, `rust/capture/src/sinks/kafka.rs` ~815, ~2271) +
  the fallback tests.
- **Risk / rollback.** Medium-high — this is the core mechanism. Revert.
- **Size.** L.
- **Unblocks.** Step 5 and all of Stage C.

#### Step 5 · Port secondary sinks; rebuild `FallbackSink` as a `Sink` wrapper

- **Goal.** Implement `Sink` for `print` (`rust/capture/src/sinks/print.rs`),
  `noop` (`rust/capture/src/sinks/noop.rs`), `s3` (`rust/capture/src/sinks/s3.rs`),
  and the AI-only `split` `SplitKafkaSink` (`rust/capture/src/sinks/split.rs`,
  constructed at `rust/capture/src/setup.rs:292`);
  rebuild `FallbackSink` (`rust/capture/src/sinks/fallback.rs:11`) as a health-gated
  `Sink` wrapper — the framework primitive Step 11's automatic failover builds on.
- **Parity — metric names must not move (R3 #35).** Preserve exactly:
  the `capture_primary_sink_health` gauge,
  the `capture_fallback_sink_failovers_total` counter,
  failover on `RetryableSinkError`,
  and skipping the primary while the advisory `lifecycle::Handle` reports unhealthy
  (`rust/capture/src/sinks/fallback.rs:50`).
- **Files.** `rust/capture/src/sinks/print.rs`, `rust/capture/src/sinks/noop.rs`,
  `rust/capture/src/sinks/s3.rs`, `rust/capture/src/sinks/split.rs`,
  `rust/capture/src/sinks/fallback.rs`,
  `rust/capture/src/setup.rs:486` (`create_sink`).
- **Parity proof.** The existing fallback tests including the advisory-handle test
  (`rust/capture/src/sinks/fallback.rs:107`), the split-sink tests, and the s3 tests.
- **Risk / rollback.** Medium. Revert.
- **Size.** M.
- **Unblocks.** Step 11 (automatic failover behind the trait).

### Stage C — migrate call sites, pipeline by pipeline

Exactly four edits move all six pipelines onto `Sink` directly.
Per-event results are deliberately collapsed to today's whole-request response —
the per-event surface stays dormant until the v1 response model is adopted.

#### Step 6 · Analytics family → `Sink` (5 pipelines)

- **Goal.** The single call site at `rust/capture/src/events/analytics.rs:395` —
  which carries Analytics, Heatmaps, Client warnings, and Exceptions,
  all riding `process_events` — calls `Sink::publish_batch`.
  Per-event `SinkResult`s are folded to the current whole-request response for parity.
- **Files.** `rust/capture/src/events/analytics.rs:382` (`send`/`send_batch`),
  `rust/capture/src/router.rs:40` (the `State.sink` type).
- **Parity proof.** The analytics integration tests + Step-1 goldens.
- **Risk / rollback.** Medium. Revert.
- **Size.** M.
- **Unblocks.** Step 9.

#### Step 7 · AI + OTEL → `Sink`

- **Goal.** `rust/capture/src/ai_endpoint.rs:449` (`send`) and
  `rust/capture/src/otel/mod.rs:214` (`send_batch`) call `Sink` directly.
  AI events share the analytics `Destination` / topic and reuse the shared overflow stamping
  (`rust/capture/src/events/overflow_stamping.rs`);
  the AI secondary / split routing from Step 5 sits behind the `Sink`,
  so these call sites keep their shape.
- **Files.** `rust/capture/src/ai_endpoint.rs`, `rust/capture/src/otel/mod.rs`.
- **Parity proof.** The AI and OTEL endpoint tests.
- **Risk / rollback.** Low-medium. Revert.
- **Size.** S/M.
- **Unblocks.** Step 9.

#### Step 8 · Replay → `Sink` (bespoke envelope)

- **Goal.** `rust/capture/src/events/recordings.rs:400` (`send`) calls `Sink`.
- **What is special here (call it out).** Replay is the one structurally-separate pipeline.
  Parity must carry:
  (1) the partition key is `session_id`, not `token:distinct_id`
  (`rust/capture/src/sinks/kafka.rs:538`);
  (2) the lz4 envelope — a 4-byte LE uncompressed-size prefix + a `content-encoding: lz4`
  header (`rust/capture/src/sinks/kafka.rs:416`);
  (3) a distinct redis session-limiter overflow to `replay_overflow_topic`,
  stamped upstream in the processor (`rust/capture/src/events/recordings.rs:330`),
  so the sink stays mechanism-only;
  (4) the `MissingSessionId` reject (`rust/capture/src/sinks/kafka.rs:541`).
  These express cleanly through the Step-2 `route()` + `serialize_batch`.
- **Files.** `rust/capture/src/events/recordings.rs`;
  the `SnapshotMain` arms of `route()` / serialization.
- **Parity proof.** The recordings mock-sink tests
  (`rust/capture/src/events/recordings.rs` ~579–649) +
  the lz4 goldens (`rust/capture/src/sinks/kafka.rs:2628`).
- **Risk / rollback.** Medium — bespoke envelope. Revert.
- **Size.** M.
- **Unblocks.** Step 9.

#### Step 9 · Delete the `Event` shim

- **Goal.** With all four call sites on `Sink`, remove `sinks::Event`
  (`rust/capture/src/sinks/mod.rs:14`) and its shim,
  and drop the dead config/types only the shim used.
- **Parity proof.** Compiles call-site-free; the full sink test suite passes.
- **Risk / rollback.** Low — pure deletion after the trait is unreferenced. Revert.
- **Size.** S.
- **Unblocks.** Stage D convergence.

### Stage D — the payoff

One sink stack, a complete registry,
and automatic failover encapsulated behind the trait.

#### Step 10 · Registry completeness everywhere

- **Goal.** Register every destination of every pipeline in the one `OutputRegistry` (Step 3);
  the startup check now covers every topic capture can produce to —
  main / historical / overflow / dlq / exception / heatmap / client-ingestion-warning /
  replay-overflow — across all `CaptureMode`s.
- **Files.** `rust/capture/src/setup.rs`, the `Outputs` enum.
- **Parity proof.** Startup tests per `CaptureMode`.
- **Risk / rollback.** Low. Revert.
- **Size.** S.
- **Unblocks.** Safe fallback rollout.

#### Step 11 · Automatic failover behind the trait (dark) — master-plan contract

- **Goal.** Land the automatic failover / circuit-breaker skeleton as a `Sink` wrapper
  built on Step 5's health-gated `FallbackSink` —
  **dark-launched**: constructed but pass-through (inert), so there is no wire change.
- **The contract.** All failover logic lives behind `Sink`;
  no other layer knows how events are produced
  (`planning/00-master-plan.md`, "Failover is automatic and sink-encapsulated").
  This step is the reason the whole refactor exists —
  it is the master plan's #1 driver
  (safely adding a fallback sink / circuit breaker).
- **Files.** `rust/capture/src/sinks/fallback.rs` → a failover `Sink`;
  `rust/capture/src/setup.rs` wiring (dark).
- **Parity proof.** Constructed-but-inert — existing tests unchanged;
  new wrapper unit tests cover the health transitions.
- **Risk / rollback.** Low — inert until explicitly enabled. Revert or flag off.
- **Size.** M.
- **Unblocks.** The fallback-sink / circuit-breaker goal.

#### Step 12 · v1 path converges onto the unified module

- **Goal.** `v1/sinks` becomes a re-export of (or is replaced by) the unified `sinks` module;
  one sink stack remains.
  The v1 `Router` / `SinkName` dispatch stays as the dual-write / cutover mechanism,
  now over the unified `Sink`.
- **Files.** `rust/capture/src/v1/sinks/mod.rs`, `rust/capture/src/v1/sinks/sink.rs`,
  `rust/capture/src/v1/sinks/router.rs`, `rust/capture/src/v1/sinks/types.rs`,
  `rust/capture/src/sinks/`.
- **Parity proof.** The v1 analytics handler tests
  (`rust/capture/src/v1/analytics/process.rs`) + the full suite.
- **Risk / rollback.** Medium. Revert.
- **Size.** L.
- **Unblocks.** A single sink stack; feeds Phase 4 (v0/v1 convergence) of the evolution plan.

## Agent conventions

**Build / test.** All cargo commands run via `flox activate -- cargo <cmd>` from `rust/`.

**Acceptance per step:**

- `flox activate -- cargo test -p capture` — scope to the relevant modules where the full
  suite is slow. Name the tests explicitly per step:
  - Steps 1–4, 8: the golden/routing suite in `sinks::kafka`
    (`assert_routing` cases, the lz4 goldens ~kafka.rs:2628,
    the three-phase `send_batch` suite ~kafka.rs:815 / ~2271).
  - Step 5: the fallback tests (incl. the advisory-handle test ~fallback.rs:107),
    the split-sink tests, the s3 tests.
  - Steps 3, 10: the startup / `CaptureMode` config tests.
  - Steps 6–8: the analytics integration tests, the AI + OTEL endpoint tests,
    the recordings mock-sink tests (~recordings.rs:579–649) respectively.
  - Step 12: the v1 analytics handler tests (`v1::analytics::process`) + the full suite.
- `flox activate -- cargo clippy -p capture -- -D warnings`
- `flox activate -- cargo fmt`

**Wire parity.** Proven by tests that already exist + the Step-1 goldens,
not by new integration harnesses.
Existing tests and the Step-1 goldens pass **UNMODIFIED**
except where a step explicitly says otherwise
(Step 1 adds additive assertions; Steps 3/10 add new startup tests;
Step 11 adds new wrapper unit tests).

**Stability invariants.**

- Metric names and labels stay stable (R3 #35):
  `capture_events_rerouted_overflow`, `capture_primary_sink_health`,
  `capture_fallback_sink_failovers_total`, and the `capture_events_rerouted_*` counters
  do not move.
- Never mix a mechanical move with a behavior change in one commit.
- Each step ships **dark or inert** where noted (Step 11),
  or is a pure mechanical move the goldens prove neutral.
- Rollback is always a plain revert — no data migrations, no dual-format windows
  beyond the lz4 envelope's existing coexistence design.
- The per-event response model (v1 `BatchResponse`, R3 #34) is **out of scope** here;
  it is adopted only after the sink stack is unified.

**Git.** Agents do **not** run git commands.
The orchestrator commits each step. No `--no-verify` — pre-commit hooks must pass.

## Progress tracker

| Step | Status | Commit subject | Notes |
| --- | --- | --- | --- |
| 0 · This plan doc | done | `docs(capture): sinks-everywhere refactor plan` | Working contract; first commit of the draft PR |
| 1 · Consolidate routing goldens | done | `test(capture): consolidate routing golden oracle` | `assert_routing` now pins topic + key + every stamped header (`force_disable_person_processing`, `skip_heatmap_processing`, content-encoding, DLQ reason/step/RFC-3339 timestamp) + the `capture_events_rerouted_dlq`/`_custom_topic` counters via a thread-local recorder; folded the two standalone DLQ-header tests into the oracle and added skip-heatmap + lz4 content-encoding goldens |
| 2 · Extract pure `route()` | done | `refactor(capture): extract routing into pure route()` | Lifted the DLQ/custom-topic/per-datatype decision into a pure `route(&ProcessedEventMetadata) -> Route { target, key_policy, effect }`; the sink resolves the target to a topic, the key policy to a partition key, and applies the effect (DLQ headers/counter, custom-topic counter, force-disable-person). Serialization + lz4 envelope stay in the sink. 59 goldens pass unmodified + 6 new direct `route()` precedence tests |
| 3 · OutputRegistry + startup check | done | `refactor(capture): output registry with startup completeness check` | #68719 seam; introduces the check. New `sinks/registry.rs`: promoted `RouteTarget` → shared `Outputs` enum + `OutputRegistry` (one output→topic wiring point, replacing the `KafkaTopicConfig` struct and the inline `match route.target`). `KafkaSink::new` builds the registry and runs `check_complete()` before touching a broker — a blank fixed-output topic now refuses to boot instead of failing at first produce; `create_sink` propagates it (`?` not `expect`). Config keys unchanged. 178 `sinks::kafka` goldens unmodified + 12 new registry tests + a per-`CaptureMode` boot-refusal test. v1 `topic_for` convergence deferred to Step 12 (its `Destination` has 280 usages; merging now would exceed M and preempt Step 12) |
| 4 · Promote `Sink`; `Event` shim | done | `refactor(capture): promote Sink trait, make Event a shim` | Kept as one commit — the hoist and the trait both live in `sinks/kafka.rs` and can't be file-separated, so a 4a/4b split would not give the orchestrator cleanly-separable files; the change is internally ordered (hoist → trait). New `sinks/sink.rs`: unified v0-native `Sink` trait (`publish_batch(Vec<PreparedRecord>) -> Vec<SinkResult>` + sync `flush`), promoting the v1 *shape* (prepared batch in → per-event results out) without dragging in v1's `RequestContext`/`Destination` (that convergence stays Step 12, consistent with Step 3 deferring the `topic_for` merge). Hoist: `prepare_record` now returns `PreparedRecord` (serialize + lz4 + route + header stamps + topic/key resolution), and the phase-1 prep loop is lifted into `KafkaSinkBase::prepare_batch` (serial <8, scatter-gather ≥8, fail-fast → zero produced). `impl Sink for KafkaSinkBase` = phases 2+3 (serial enqueue + fail-fast ack drain) producing per-event `SinkResult`s. `Event` is now a shim: `send_batch` = `prepare_batch` → `publish_batch` → `fold_results` (first error wins), collapsing to today's `CaptureError`; `send` stays a lean single-ack path (`kafka_send`, unchanged; still used by 3 compression goldens). Health gate deliberately not on the mechanism trait — Kafka reports liveness via its stats callback; the health-gated wrapper is `FallbackSink` (Step 5). 965 `capture --lib` tests pass unmodified (259 `sinks::`), clippy `--all-targets -D warnings` clean, fmt clean. |
| 5 · Port secondary sinks; FallbackSink wrapper | todo | `refactor(capture): port secondary sinks onto Sink, rebuild FallbackSink` | Keep metric names stable |
| 6 · Analytics family → `Sink` | todo | `refactor(capture): route analytics family through Sink` | 5 pipelines via one call site |
| 7 · AI + OTEL → `Sink` | todo | `refactor(capture): route AI and OTEL endpoints through Sink` | |
| 8 · Replay → `Sink` | todo | `refactor(capture): route replay through Sink` | Bespoke lz4 envelope + session_id key |
| 9 · Delete `Event` shim | todo | `refactor(capture): remove Event trait shim` | Pure deletion |
| 10 · Registry completeness everywhere | todo | `refactor(capture): complete OutputRegistry across all pipelines` | Startup check covers every topic |
| 11 · Automatic failover behind trait (dark) | todo | `feat(capture): automatic failover Sink wrapper (dark)` | Constructed but inert; master-plan contract |
| 12 · v1 converges onto unified module | todo | `refactor(capture): converge v1 sinks onto unified module` | One sink stack remains |
