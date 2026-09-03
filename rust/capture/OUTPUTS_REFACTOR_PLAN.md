# Capture outputs refactor — implementation plan

Working contract for implementation agents. Steps 1–8 have shipped; each remaining step is one commit in its own PR.

**Retirement.** This doc dies when it schedules nothing and owns no unsequenced objective. Step 26 closes the first objective (the manual fallback); the second — capture prepared for an automated fallback — is then sequenced by promoting the steps under **Objective 2** below into a scheduled stage, parity proofs intact. Whatever is still load-bearing at the end — the vocabulary rules, the ordering-vs-person-processing contract, the repartitioning design note — graduates into module docs or `v1/sinks/DESIGN.md` first, and only work serving neither objective leaves as issues.

## Motivation

**Two objectives, one mechanism: an output owns the configuration it produces with.**

**Objective 1 — ship a manual fallback.** If MSK degrades, capture-analytics must be able to produce to an alternative cluster — its brokers, its TLS, its own topic names — armed by one environment variable and a pod roll, and we must know the configuration is sound before any traffic moves. Running capture against a half-wired cluster is the risk this objective removes, and the boot-time checks that remove it (Steps 22 and 23) are only buildable once configuration is isolated per output (Step 21): a single deployment-wide `KafkaConfig` with ten defaulted topic names is exactly what a startup check cannot verify. Steps 21–26 are this objective; Step 24 is the feature.

**Objective 2 — prepare capture for an automated fallback.** The switch decision moves to a separate circuit-breaker service; how that service decides is not this plan's concern. Capture's side of the contract is narrow: submit producer health metrics, receive switch signals, and apply a signal at runtime through the failover output it already has — no redeploy. Consumers are out of scope throughout; this plan is capture prep. The steps live under **Objective 2** below, unsequenced until objective 1 closes.

The mechanism both objectives ride is the same: make an output carry its own connection and topic configuration, require that configuration for every output a deployment can reach, and verify those topics against that output's own broker at boot. A fallback — manual or signal-driven — is then *a configuration of an output's targets*: no new policy, no new trait, no per-feature code path. `Output::failover` already composes two arbitrary outputs (Step 7); what it lacks is targets configurable independently of each other, and, for objective 2, a target selection that can change while the process runs.

Safety is why this plan is mostly refactoring. Moving production traffic between clusters tolerates no ambient state and no half-understood code path, so every step is one small commit, parity-proven by the Step-1 goldens, revertible by plain revert — and the steps that read as pure structure are what make the boot checks and the runtime switch possible at all.

Steps 1–8 landed the structure: routing is a pure function, the lane decision is pipeline-layer code, sinks are backend mechanism over prepared payloads, and the outputs layer owns multi-target policy behind one produce surface. Cluster migration by split/dual-write and a protobuf cutover behind the serialization seam stay recorded under **Deferred work**: real, unscheduled, and cheaper once outputs are independently configurable, not more expensive.

## Target architecture

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

- **Pipeline** is decided at the edge (endpoint + event name) — the high-level "which product stream is this" classification.
- **Lane** is decided once, at the end of a pipeline, by folding the intent stamped during processing (restrictions, overflow reasons, historical flag) through one precedence chain. Today that chain is `route()` inside the Kafka sink; it moves up and runs before anything is serialized.
- **Output** is the named destination an event is published to, addressed by `(Pipeline, Lane)`. An output owns 1..n targets and the policy that picks between them per batch. All multi-target behavior lives here and only here.
- **Serialization** is a contract with the *consumers of a destination*, not a property of a transport. Each output names its format and envelope; the produced payload is sink-agnostic bytes plus the content headers that let old and new encodings coexist on a topic during migration (the existing replay lz4 `content-encoding` design, generalized).
- **Sink** is a single backend. It turns an addressed, serialized payload into its wire shape and acks it. It reads no event metadata and makes no decision.

## Starting point

Steps 1–3 land together with this doc: the routing golden oracle, the pure `route()`, and the `TopicTable` with its startup completeness check. Production call sites still publish through the v0 `Event` trait (`send` / `send_batch`); the v1 stack (`CAPTURE_V1_SINKS`, opt-in) still runs its own serialize-then-publish pipeline with a per-event response model. The v1 `PreparedEvent { uuid, destination, payload: Bytes, headers, partition_key }` is the shape our output→sink handoff adopts.

### Vocabulary rules

- An event's **Address** is a lane of its pipeline (lanes typed per pipeline — `AnalyticsLane`, `AiLane`, `SessionReplayLane`, `BasicLane` — so invalid pairs are unrepresentable), or an admin **custom redirect** that carries its own topic outside the lane model. Pipeline and lane kind are projections; construction goes through `resolve`. Never reintroduce a flat destination enum that conflates pipeline and lane.
- **Output** = the addressed destination: targets + selection policy + serializer. **OutputRegistry** = the `(Pipeline, Lane)` → output mapping with the per-mode completeness check. The Step-3 **TopicTable** (destination → topic) is absorbed into the registry's targets.
- **Destination** = a routed topic slot (`AnalyticsMain`, `Dlq`, `AiEvents`, `Custom`). One word across both stacks: v0's `sinks::registry::Destination` and v1's `v1::sinks::types::Destination` are the same concept and converge at Step 20. Never name a backend policy tree an `Output` *and* a routed topic an `Output`.
- **Sink** = backend mechanism. Kafka, S3, print, noop. Nothing else is a sink; a thing that picks between sinks is an output policy.
- **Serializer** = format × envelope. Formats and envelopes compose; neither knows about sinks or outputs.

### Invariants

- Metric names and labels stay stable: `capture_events_rerouted_*`, `capture_primary_sink_health`, `capture_fallback_sink_failovers_total`, `capture_event_batch_size`. Renames are out of scope for every step.
- Wire parity is proven by the Step-1 goldens and existing endpoint/integration tests passing **unmodified**, except where a step explicitly says otherwise.
- Never mix a mechanical move with a behavior change in one commit.
- Every step ships green (`cargo test -p capture`, clippy `-D warnings`, fmt) and rolls back by plain revert.
- The per-event response model (v1 `BatchResponse`) stays out of scope; call sites keep folding per-event results into today's whole-request `CaptureError`.
- Sinks read no `ProcessedEventMetadata`. After Step 6 the only consumer of routing metadata is lane resolution.

## The stages and steps

### Stage A — oracle and groundwork

#### Step 1 · Consolidate the routing golden oracle

The `assert_routing` suite pins topic + partition key + every stamped header + the rerouted counters for all pipelines and lanes. It is the parity instrument for every later step.

#### Step 2 · Extract routing into a pure `route()`

`route(&ProcessedEventMetadata, ai_events_overflow_armed) -> Result<Route { target, ordering }, CaptureError>`, consulted by the sink.
The decision is the target `Output` plus the customer-facing `OrderingGuarantee` the sink realizes as a partition key; side effects are implied by the target rather than carried as decision data, the AI overflow valve rides in as an explicit argument to keep the function pure, and a replay decision with no session id is rejected rather than returned unrealizable.
This is the function Step 5 hoists out of the sink into lane resolution.

#### Step 3 · `TopicTable` + startup completeness check

One destination→topic wiring point plus refuse-to-boot on a blank topic, gated behind `CAPTURE_OUTPUTS_COMPLETENESS_CHECK_ENABLED` (default off; see Step 22's arming precondition).
Step 7 absorbs it into the `OutputRegistry`; the mode-scoped demand is folded in at Step 22, where `(Pipeline, Lane)` makes the per-mode reachable set explicit.

### Stage B — the two new seams (no caller-visible change)

#### Step 4 · Serialization layer: format × envelope

- **Goal.** New `serialization` module: `Format` (event → payload bytes + `content-type`) with `Json` as the only impl, `Envelope` (bytes → bytes + `content-encoding`) with `None` and `Lz4` (the replay 4-byte LE size-prefix block format, moved verbatim), and a `Serializer` composing one of each. `prepare_record` calls the serializer instead of inlining `serde_json::to_string` + the lz4 branch. Replay's serializer is `Json × Lz4` when `kafka_replay_envelope_compression` says so; everything else `Json × None`.
- **Explicitly not in the serializer:** partition keys, routing headers, topics. Bytes and content headers only.
- **Files.** `rust/capture/src/serialization/` (new); `rust/capture/src/sinks/kafka.rs` (`prepare_record` consumes it).
- **Parity proof.** Step-1 goldens unmodified — including the lz4 goldens and `content-encoding` assertions. New unit tests on format/envelope composition.
- **Risk / rollback.** Low — mechanical hoist. Revert.
- **Size.** M.

#### Step 5 · `Pipeline` + `Lane`; the lane decision becomes pipeline-layer code

- **Goal.** Introduce the address pair and relocate the decision logic:
  - `Pipeline { Analytics, Heatmaps, Warnings, ErrorTracking, Replay }` (`Pipeline::from_data_type` extracts the pipeline half of `DataType`).
  - `Lane { Main, Overflow, Historical, Dlq, Custom(&str) }`.
  - `pipeline::resolve(&ProcessedEventMetadata) -> Result<LaneDecision { pipeline, lane, ordering }, CaptureError>` — Step-2's `route()` moved out of the sink module wholesale, precedence unchanged (dlq > custom > historical > overflow > main), pure (no counters, no headers, no I/O). `OrderingGuarantee` moves with it as decision *data*.
  - The sink keeps a private `output_for((pipeline, lane)) -> Output` bridge and still *invokes* `resolve` from its prep path — the invocation site moves up in Step 7 when the outputs layer exists to own it. This keeps the commit a pure relocation: no metadata changes, no call-site changes, goldens byte-identical.
- **Files.** `rust/capture/src/pipeline.rs` (new); `rust/capture/src/sinks/kafka.rs` (drops `route()`/`Route`/`OrderingGuarantee`, gains the `output_for` bridge); `rust/capture/src/lib.rs`.
- **Parity proof.** Step-1 goldens unmodified. `route()`'s precedence tests move to `pipeline::tests` with assertions preserved, plus a pipeline classification test.
- **Risk / rollback.** Low-medium — mechanical relocation. Revert.
- **Size.** M/L.

### Stage C — sinks become mechanism, outputs become the API

#### Step 6 · Narrow the Kafka sink to backend mechanism

- **Goal.** New `sinks/sink.rs`: `PreparedPayload { uuid, record: ProduceRecord }` (serialized, addressed) is the sink input; `trait Sink { publish(Vec<PreparedPayload>) -> Vec<SinkResult>; flush() }` — no prepare on the trait, no metadata access — plus `Outcome` and `fold_results` (first failure wins). Kafka: `prepare_batch` (serial <8 / scatter-gather ≥8, fail-fast) extracted from `send_batch` as an inherent method the outputs layer will call; `impl Sink` = serial enqueue + fail-fast ack drain, reporting batch-uniform per-event results (the per-event surface refines only with the response model). `Event::send_batch` becomes the bridge: prep → publish → fold. Kafka only — s3/print/noop gain mechanism impls with the outputs layer, which is what needs them.
- **Sequencing decision.** `FallbackSink` is never ported onto the mechanism trait: the outputs layer owns multi-target policies (single | failover) from its first commit, built from the same config, and the Event-era composite is deleted when its last caller migrates. `SplitKafkaSink` is already gone — deleted with the retired AI secondary-cluster routing — so split survives only as a policy shape the outputs layer grows back when a cluster migration needs it.
- **Files.** `rust/capture/src/sinks/sink.rs` (new), `rust/capture/src/sinks/kafka.rs`, `rust/capture/src/sinks/mod.rs`.
- **Parity proof.** Step-1 goldens + `send_batch` three-phase suite unmodified (they now drive prep → publish → fold — the exact production path).
- **Risk / rollback.** Medium-high — core mechanism. Revert.
- **Size.** L.

#### Step 7 · Outputs layer with policies; composites retired

- **Goal.** New `outputs` module — the produce surface, with multi-target policy ownership from day one:
  - `Output`: a single backend, or a policy composing two *outputs* — today `failover` (health-gated Kafka→S3: skip primary while the advisory handle is unhealthy, re-publish the batch on a retriable failure, fatal never fails over). Targets are outputs themselves, so a future policy (a split for the next cluster migration) composes over pairs the way the old composites did. Policies operate on *events*, before prep — each target resolves topics and serializes for itself, exactly like the old per-sink `send_batch` paths, so parity is structural.
  - Leaves run the dance internally via the `pub(crate)` `PublishEvents` trait (prep → publish → fold); no caller ever sees a two-phase protocol.
  - `OutputRegistry`: the `(pipeline, lane)` → output handle the state holds; degenerate today (one deployment-wide output; per-lane topics resolve in prep via the `TopicTable`).
  - `setup::create_output` builds the policy tree from the same config; **`FallbackSink` is deleted**, its tests re-expressed on `Output` with assertions preserved (+ a new fatal-no-failover case).
  - Call sites are untouched: the table serves them through a transitional `Event` facade (which records `capture_event_batch_size`, where the old sink impls recorded it). Migration is Step 8.
  - The facade is the only `dyn Event` the production call sites see, so the per-sink `Event` impls on s3, print, and noop are deleted here rather than rewired onto `PublishEvents`. `Event` survives only where callers still need it: the Kafka bridge and `MockSink`, both consumed by tests that Step 8 retypes.
- **Files.** `rust/capture/src/outputs.rs` (new); `rust/capture/src/setup.rs`; `rust/capture/src/sinks/{mod,s3,print,noop,test_sink}.rs` (mechanism + `PublishEvents` impls); `fallback.rs` deleted.
- **Parity proof.** Goldens + all integration suites unmodified. Known metrics-only deltas, accepted: the batch-size histogram now records on the fallback-to-S3 path (it silently didn't before), and print/noop single sends record it (they didn't).
- **Risk / rollback.** Medium. Revert.
- **Size.** L.

#### Step 8 · Call sites migrate to the table; `Event` retired

- **Goal.** All four call sites (`events/analytics.rs`, `ai_endpoint.rs`, `otel/mod.rs`, `events/recordings.rs`) publish via `OutputRegistry::publish`, recording `capture_event_batch_size` at the call site; `State` and test mocks retype; then delete the v0 `Event` trait, its `Box<T>` blanket, the outputs facade, and the `Event` impls on Kafka, S3, print, noop, and the test mock.
- **`State` drops its trait object.** `State.sink: Arc<dyn Event>` becomes `State.outputs: Arc<OutputRegistry>` — a concrete type, since `Output::single` already accepts any leaf. The substitution seam moves down to the leaf: `PublishEvents` and `Output::single` become `pub` so the `tests/` suites can stand their own capturing sinks in (`test_sink` is `cfg(test)`-gated and unreachable from there), and pipeline tests drive the real table and policy path instead of bypassing the outputs layer.
- **`kafka_send` survives this step.** It is not reachable only from `Event::send`: `PublishEvents::publish_events` calls it on its one-event branch, and that is the production single-event path (recordings publishes one event per call). Deleting it means re-expressing that branch over `prepare_batch` + `Sink::publish` + `fold_results`, which adds a task spawn per single event and drops the `ack_wait_one` span — a behavior change, and this step is a mechanical move. Step 12 retires it with the prep hoist.
- **Parity proof.** All endpoint/integration suites green; grep proves `Event` call-site-free before the deletion half.
- **Size.** M/L. May split into per-call-site commits if the diff grows.

### Stage D — outputs carry their own configuration

The remaining committed work, and it is a mechanism, not a feature: an output owns the configuration it produces with. Once that holds, an emergency fallback to another cluster is *a configuration of an output's targets* rather than a code path — which is what the target architecture said all along.

Each step is small, ships green, and reverts by plain revert. Steps 21–23 are the mechanism, Step 24 is the fallback itself, Step 25 removes what it replaces, and Step 26 collapses the second stack onto the same model.

#### Step 21 · An output owns its connection and its topics

- **Goal.** Every leaf output is built from an output-scoped config block — brokers, TLS, and that output's own topic names — instead of reading the one deployment-wide `KafkaConfig`. Two Kafka outputs in the same tree can name different clusters and different topics, because neither consults global state to find out where it produces.
- **Adopt v1's model; do not invent a third.** `v1::sinks::kafka::Config` is already exactly this: per-sink, namespaced by sink name (`CAPTURE_V1_SINK_MSK_KAFKA_HOSTS` → key `HOSTS`), carrying its own connection, its own producer tuning, and its own topics — declared *"Topics (all required — envconfig errors if any are missing)"*, with no defaults. v0 is the stack with one deployment-wide `KafkaConfig` and ten defaulted topics. Step 21 moves v0 onto v1's shape, reusing the struct rather than paralleling it. A v0-specific config model here would leave three to reconcile at Step 20 instead of one.
- **Why this is the whole mechanism.** `Output::failover` already composes two arbitrary outputs (Step 7). It is typed Kafka→S3 today only because `setup` builds it that way. Once a leaf carries its own config, a second cluster with its own topic names is a `setup` change and a values file, with no new trait and no per-feature plumbing.
- **Size.** M.

#### Step 22 · A reachable output must be configured

- **Goal.** The configuration an output requires is required in code: an output the deployment's `CaptureMode` can reach must be fully configured or capture refuses to boot. Unreachable outputs are not asked for at all — a Recordings pod is never asked to name an error-tracking topic.
- **Defaults go.** The `#[envconfig(default = ...)]` on each topic field is what makes a missing or misspelled variable resolve to a compiled-in name instead of failing. A reachable output's topics stop being defaulted; an absent or empty value is a boot failure, which is the behaviour the check was always meant to have.
- **Supersedes** the deployment-wide `CAPTURE_OUTPUTS_COMPLETENESS_CHECK_ENABLED` flag, which demands all ten destinations on every pod and so can be armed nowhere.
- **Parity proof.** Per-mode refusal tests, and anti-over-demand tests proving a mode is never asked for an output it cannot reach.
- **Size.** M.

#### Step 23 · Verify an output's topics against its own broker

- **Goal.** At boot, probe each reachable output's cluster metadata for the topics that output can produce to, and refuse to start on a missing one. Per output, against that output's own broker — so a fallback pointed at a half-provisioned cluster fails before it can take traffic.
- **Why it is separate from Step 22.** Step 22 is config-only and never touches a broker: it answers "is this wired", instantly, with no connect attempt. Step 23 answers "does this exist on the cluster we are about to produce to", which is the question that matters when the cluster is one this deployment has never written to.
- **Default off**, armed per deployment: on brokers with topic auto-creation the metadata probe can create the topic it is checking, which makes a pass meaningless.
- **Size.** M.

#### Step 24 · The capture-analytics emergency fallback

The consumer of Steps 21–23, and the reason they exist.

- **Shape.** The deployment's outputs tree carries *both* Kafka outputs: the primary and a fallback, each configured independently under its own Step-21 namespace (own brokers, own TLS, own topic names — the backup cluster does not have to mirror the primary's topic names, and should not have to).
- **Arming.** One environment variable, matched exactly against a sentinel — not a truthy value. `"1"`, `"true"`, `"yes"` must not move a fleet's traffic, and any value other than the sentinel refuses to boot rather than quietly running on the primary. Unset is normal operation.
- **The switch is static at boot.** Exactly one target publishes; arming means setting the variable and rolling the pods. This is deliberate: the failure it answers is "MSK is degraded and a human has decided to move", not a transient the process should react to on its own. Automatic switching is objective 2, and builds on this step's tree.
- **Both targets are verified, including the dormant one.** The tree holds the fallback whether or not it is armed, so Step 23 probes its cluster and topics at every boot. A misconfigured backup is then discovered on an ordinary deploy, months before the emergency — which is the entire point. Discovering it while arming is discovering it too late.
- **Report which target is live** on a gauge, emitted in both states so a dashboard can tell "on the primary" from "pod not reporting".
- **Scope.** capture-analytics. Other capture modes carry no fallback output and are not asked to configure one (Step 22).
- **Known gaps to carry, not solve here.** Consumers have no equivalent switch, so a repoint is not symmetric; capture-import writes the same topics and must be stopped before any drain-to-zero gate; the AI lane's bridges read MSK-era names. These belong in the runbook, not the code.
- **Size.** M.

#### Step 25 · Retire the S3 fallback

- **Goal.** Delete `S3Sink`, its `PublishEvents` impl, the `s3_fallback_*` config, and the Kafka→S3 failover wiring in `setup`.
- **Why it is safe.** It is off in every production deployment: six `S3_FALLBACK_ENABLED: "false"` across the charts apps against one `"true"`, and that one is `apps/capture-analytics/values.dev.yaml`. The infra config notes the IAM role is "wired but unused". Retiring it removes dead break-glass machinery, not a live safety net.
- **Why Step 24 replaces it.** A second Kafka cluster keeps events in the pipeline — consumers read them normally. S3 parks them behind a separate replay path that has never been exercised in production.
- **The trade, stated plainly.** S3 failover is *automatic*: the advisory health handle flips and the fallback takes the batch, with no human and no redeploy. Step 24 is *configuration*: arm and roll. Retiring S3 therefore gives up an automatic response — one that is currently disabled everywhere, so nothing running is lost, but the capability is. Getting it back, done properly, is objective 2: the breaker service's signals drive Step 24's fallback through the Step-27 seam; the policy node already composes two outputs.
- **Cross-repo.** Six chart values, the `CaptureAnalyticsV0S3FallbackActive` alert spec and its runbook, and the IAM role in cloud-infra all go with it.
- **Size.** M.

#### Step 26 · v1 converges on the shared strata

- **Goal.** v1's `Destination` bridges to `(Pipeline, Lane)`; v1 topic resolution goes through the shared table; v1's `serialize_batch` uses the Step-4 serializer. The v1 `Sink`/`Router` trait convergence stays gated on the per-event response model, as before.
- **Why it moves up.** After Step 21 both stacks configure a destination the same way — per sink, namespaced, topics required — so the two differ in routing and response granularity, not in how a producer learns where it produces. Convergence is cheapest immediately after Step 21, and gets more expensive the longer v0 carries a second config model.
- **Parity proof.** v1_pipeline (17) + v1_sink_integration (10) unmodified, plus `overflow_parity.rs` unmodified. That suite drives both pipelines end to end over the overflow and rate-limit matrix and is the oracle for the ordering-vs-person-processing contract this step has to carry across (see the Hazard note under "v1 convergence on the outputs machinery"). Both paths already share `OrderingGuarantee` from `crate::ordering`.
- **Size.** M/L.

#### What Steps 22 and 23 would already have caught

`KAFKA_REPLAY_OVERFLOW_TOPIC` appears in **no file** in the charts repo, while `(Pipeline::Replay, Lane::Overflow) → Destination::SessionReplayOverflow` is a reachable route with a passing test. Replay overflow therefore resolves to the compiled-in `session_recording_snapshot_item_overflow`, while prod-us replay wires `ingestion-sessionreplay-overflow-64` under `KAFKA_OVERFLOW_TOPIC`.

Step 22 fails that at boot: a reachable output with no configured topic. Step 23 fails it too, if the defaulted name is absent from the cluster. Worth confirming where that traffic lands today — unconfirmed, and it predates this plan.

## Objective 2 — automated fallback (unsequenced)

Capture's half of an automated fallback, and nothing more. The decision-maker is a separate circuit-breaker service; its internals — how it aggregates, when it trips, whether and how it probes — are outside this plan, and so are consumers. Capture's contract with the service is two channels: producer health metrics out, switch signals in. These steps are promoted into a scheduled stage, with parity proofs, when objective 1 closes; until then they are shapes, not commitments.

### Step 27 · Failover target selection behind a control-plane seam

The failover output's target selection becomes runtime-swappable state — swappable, no request-path locks, the pattern the repartitioning note reuses — with Step 24's static arming as the boot value. Applying a signal switches which target publishes; no signal, or a silent, dead, or unreachable control plane, holds the current selection, because the absence of a decision must never move traffic. The Step-24 live-target gauge reports whichever selection is in force. Dark: with no service endpoint configured, behavior is byte-identical to Step 24's static switch.

### Step 28 · Producer health metrics out

Each Kafka output reports its own produce-path health — delivery latency, error rates, queue depth — keyed by output, so the service sees the path each deployment actually experiences, dormant fallback included. Transport and cadence are sequencing-time decisions; the standing requirements are per-output attribution and that reporting failure never degrades the produce path.

### Step 29 · Switch signals in

Capture receives switch signals from the service and feeds them to the Step-27 seam, acknowledging what it applied. The Step-24 arming variable stays authoritative as the manual override — a human's static decision outranks the service in both directions; exact precedence is settled at sequencing time.

Step 10 (the in-process `FailoverMode::Breaker`) dissolved into this contract: trip/probe/recover logic is the service's concern, not capture's. What survives of it is the control-plane seam and the control-plane-down posture, both carried by Step 27.

## Deferred work

Not scheduled, and serving neither objective directly. Revive a step by moving it back into a stage above, with its parity proof intact. Steps 9–11 are gone from here: Step 9 was promoted into **Step 22**, Step 11 became **Step 26** because Step 21 makes convergence cheap and delay makes it dearer, and Step 10 dissolved into **Objective 2** above.

### Stage E — prep hoists up; sinks become pure transport

#### Step 12 · Prep hoists into the outputs layer; `PublishEvents` retired

- **Goal.** Sinks take prepared payloads as input, full stop. `PrepSpec` (registry + per-destination serializers) moves payload assembly — lane resolution, serialization, header stamps, topic and partition key, and the scatter-gather batch prep — into the outputs layer; the `(pipeline, lane)` → output bridge and the `TopicTable` move with it (`outputs::topics`). The `PublishEvents` trait is deleted; every backend (Kafka, S3, print, noop) preps identically via its output's spec, and the Kafka sink is reduced to producer + enqueue + ack drain. The boot completeness check moves to `setup::create_output`.
- **Test posture change (deliberate).** Capturing mocks intercept *published payloads*, not `ProcessedEvent`s, so ~60 assertions that read metadata stamps migrate to wire-level outcomes: topic, partition key, headers, and payload bytes (deserialized for content checks). The declarative `ExpectedEvent` checkers recompute the expected record from the same expectations, so test bodies stay put. Wire-level assertions also pin a semantic the metadata-level ones couldn't see: replay events redirected to dlq/custom topics partition on the event key, not the session id.
- **Known deltas, accepted:** print/noop deployments run the real prep path (lane effects and their counters included), and prep can fail there (e.g. `MissingSessionId`) where the old passthrough couldn't. The prep histograms keep their `capture_kafka_*` names for dashboard continuity.
- **Files.** `outputs/mod.rs`, `outputs/registry.rs` (moved), `sinks/*`, `setup.rs`, all capturing test mocks.
- **Size.** L.

### Per-mode output registries (Step 15)

The deployment's output registry is a concrete type — `AnalyticsFamilyOutputs` (analytics, ai, heatmaps, warnings, error tracking rows) for Events/Ai pods, `SessionReplayOutputs` for Recordings pods — with required fields, so the narrow list of what a deployment must wire is the type itself. Handlers bound on sealed capability traits (`PublishesAnalyticsFamily`, `PublishesSessionReplay`); `State<T>` is generic over the registry and `setup` instantiates the monomorphized router per `CaptureMode` (`router` for the analytics family, `session_replay_router` for recordings) — mounting an ingress on a table that cannot publish its family is a compile error. Rows share backends (one Kafka connection, one S3 client, one breaker controller), so per-row policy trees behave as the single pre-table output did. The runtime backstop for a pipeline without a row is an explicit fatal error, structurally dead while ingress mounting and registry type derive from the same mode.

### Per-pipeline output overrides and boot verification (Step 18)

Each row of a deployment's table can be retargeted independently: `CAPTURE_OUTPUT_<PIPELINE>_BROKERS` points a pipeline's row at another cluster, `CAPTURE_OUTPUT_<PIPELINE>_TOPIC_<LANE>` renames a lane's topic in that row's namespace (existing `KAFKA_*` keys stay the defaults). The row factory builds one sink per pipeline, each with its own `TopicTable` (base config overlaid with that pipeline's overrides via `TopicTable::with_overrides`); producers are shared per distinct broker set, so the no-override configuration still opens exactly one connection. The gating liveness handle lands on the cluster carrying the deployment's ingress pipeline; other clusters' producers are non-gating. Overrides compose only with the plain per-row Kafka path — combining them with S3 fallback or AI secondary routing is refused at boot, since those policy trees assume every row shares one primary cluster.

`CAPTURE_VERIFY_TOPICS_ON_BOOT` (default off) probes cluster metadata for every topic a row can produce to — pipeline-scoped (`TopicTable::topics_for_pipeline`), so an overridden row probes only its own cluster's namespace — and refuses to start on a missing topic. Off by default because brokers with topic auto-creation make the check misleading (the metadata probe itself can create the topic).

### Outputs as an open trait (Step 19)

`Outputs` is an open trait — a produce surface handling every destination its configuration maps — replacing the closed policy enum. Implementations own payload assembly, namespace realization, backend composition, and policy: `KafkaOutputs` (one cluster: prep + address→topic table + transport sink), `S3Outputs`, `PrintOutputs`/`NoopOutputs`, `FailoverOutputs` and `SplitOutputs` (policies over `Arc<dyn Outputs>`), and the per-mode tables themselves (dispatch-by-pipeline is just another surface; capability traits are markers over `Outputs`). Sinks are pure transport and never see an `Address`: the Kafka sink publishes realized records (concrete topic, key, payload, headers); namespace realization lives in the outputs layer. `publish` reports per-event `SinkResult`s (a provided `publish_folded` collapses to the v0 whole-request response) — the granularity v1's `BatchResponse` requires.

A test-only prototype (`outputs::dynamic`) demonstrates the coordinator-managed surface: `DynamicKafkaOutputs` subscribes to an in-process `KafkaManagerService` (RPC-shaped, acked config pushes) and applies broker add/remove and mapping changes with an enabled-partition set per address — the incremental, key-deterministic drain-and-switch — with tests simulating a topic switchover and a broker switchover end to end.

### v1 convergence on the outputs machinery (Step 20)

Goal: v1 endpoints publish through `dyn Outputs` like every other ingress, so fallback/split/dynamic policies apply uniformly. Plan:

1. **Boundary mapping.** After v1 processing (destination decided, result stamped), map each publishable `WrappedEvent` into `ProcessedEvent`: the existing v1 serialize path already produces CapturedEvent-compatible payloads, so the mapping builds the `CapturedEvent` plus a `ProcessedEventMetadata` that makes `pipeline::resolve` reproduce the decided destination (AnalyticsMain → main; Overflow → force_overflow; Historical → historical data type; Dlq → redirect_to_dlq; Custom → redirect_to_topic). `Destination::Drop` events never reach the outputs layer — dropping is a processing decision, recorded in the response.
2. **Named surfaces.** `CAPTURE_V1_SINKS` names become named `Arc<dyn Outputs>` rows (each a `KafkaOutputs` built from that sink's config); the v1 `Router`/`Sink`/`Event` traits and `serialize_batch` dissolve.
3. **Response granularity.** `Outputs::publish` already returns per-event `SinkResult`s; `merge_sink_results` consumes them unchanged.
4. **Parity oracle.** The v1 pipeline tests and the real-Kafka `v1_sink_integration` suite must pass against the converged path — payload bytes, headers, topics, keys. Documented v1-vs-v0 header deltas (overflow/person-processing decoupling) must be preserved in the mapping, not silently erased. The legacy serializer/header builder survive only as a frozen `cfg(test)` oracle (`legacy_serialize`/`legacy_headers`) the parity suite compares against.
5. **Plan retirement.** Superseded: see **Retirement** in the header — the doc retires when both objectives are served, not with this step.

**Hazard.** The `Destination::Overflow` → metadata mapping must preserve the split between the two intents that ride together on this lane: whether person processing is disabled (a customer-visible instruction, the `force_disable_person_processing` header) and whether the partition key is dropped (a load decision, `OrderingGuarantee`). Both paths now state the same rule, so the mapping has one contract to satisfy rather than two dialects to reconcile:

- The header follows the stamped person-processing intent: the flag, which a `ForceLimited` reason implies on its own (`person_processing_disabled`), so a v0 stamping site cannot keep person processing on for a force-limited key by forgetting the flag.
  v1 carries no reason on the event — its one stamping site sets the flag directly.
- The key is dropped on the analytics main/overflow lanes when the person-processing flag is set, and on the AI overflow lane when either the flag or a spread decision is set — nowhere else.
  The analytics consumers update persons keyed on distinct id, so a person-on burst keeps its key there (spreading one distinct id across partitions contends those updates); the read-only AI overflow consumer takes keyless person-on records safely.
  Historical, dlq, custom redirects and the AI main topic keep the key regardless.

`overflow_parity.rs` is the oracle: it drives both pipelines over the overflow and rate-limit matrix and pins lane, key presence, and header. Extend it with the mapped v1 destinations rather than reasoning about the two paths separately.

**Accepted deltas:** `sent_at` fractional-second formatting (parse-equal; v1 adopts v0's serializer) and the v1 sink-stage metrics (`capture_v1_serialize_*`, per-sink publish metrics), superseded by the outputs-layer metrics.

### AI pipeline and Import mode

- **AI pipeline membership is a name allowlist, resolved once into a stamp.** `AI_EVENT_NAMES` lists the event names on the lane; `DataType::from_event_name` resolves a name against it and stamps `DataType::AiEvents`, on every capture mode, mirroring v1's `Destination::AiEvents`. Everything downstream reads the stamp — `Pipeline::from_metadata` maps it, and the multipart and OTEL AI ingress stamp the same lane at the handler. The allowlist is deliberately not an `$ai_` prefix match: the Node AI pipeline DLQs anything it receives off its own `AI_EVENT_TYPES` list, so a prefixed-but-unlisted name like `$ai_call` must stay on the analytics lane. (The quota predicate `is_llm_event` is separate and *is* prefix-based.) There is no per-batch routing config and no per-deployment divert switch — the rollout-era `AiRouting` mode/allowlist/percentage machinery is retired, and so is the capture-mode predicate that replaced it. A deployment that wants AI traffic on a given topic points `CAPTURE_ANALYTICS_AI_EVENTS_TOPIC` at it.
- **The AI lanes own dedicated topics.** `TopicTable` grows an `ai_events` row (`CAPTURE_ANALYTICS_AI_EVENTS_TOPIC`, required with default `events_plugin_ingestion_ai`) and an optional `ai_events_overflow` row (`..._OVERFLOW_TOPIC`); there is no `AiLane::Historical` — the divert decision wins over historical, matching v1. The AI overflow valve (overflow topic set) rides `PrepSpec` into `resolve`, so an unarmed deployment never routes the AI lane to overflow, force_overflow included.
- **Import mode** is an analytics-family deployment on `router::router`; it mounts `/i/v0/ai/batch` (gated batch handler) but not the ai/otel handlers, and shares the Events topic requirements.

## Repartitioning coordinator (design note)

Not built in this PR; this note records where it plugs in so nothing landed here has to move. The goal: switch a deployment between clusters partition by partition — drain-and-switch with minimal delay — driven by a coordinator, with sinks staying pure mechanism.

**Logical shards, decided before the sinks.** The coordinator owns a stable shard function: `shard = hash(key) % N` over the same partition key the sink would hash, with coordinator-owned `N` (not either cluster's partition count). The shard is stamped at prep time — `AddressedPayload` grows `shard: Option<u32>`, `None` meaning "let the producer partition as today". Stamping at prep keeps the decision above the sinks: both clusters of a failover pair see the same shard on the same payload, so a switchover decision is consistent across targets by construction.

**A `ShardRouted` output policy.** Routing lives in the outputs layer as a policy node holding two child outputs (old cluster, new cluster) and a swappable assignment table `shard → Old | New` (an `ArcSwap`, updated by the coordinator's control plane the same way the Step-27 control-plane seam works). Batch publish splits by assignment and forwards — scatter-gather like the old `Split` composite, no serialization changes (both clusters share the prep/serialization contract, as the retired AI-secondary split proved).

**Explicit partition pass-through in the sink.** `ProduceRecord` grows `partition: Option<i32>`; the Kafka sink maps `shard` to a concrete partition of its own topic (its table realizes the namespace; a shard→ partition map is the same kind of sink-side data as topic names) and sets it on the record. `None` keeps today's key hashing. The sink still makes no routing decisions — it realizes an address (topic) and a shard (partition) in its own namespace.

**Per-partition fence (drain-and-switch).** Moving shard `s` from Old to New, without reordering a key's events across clusters:

1. **Swap** the assignment entry for `s` — new publishes head to New but are *held* (the policy parks `s`-payloads in a short buffer).
2. **Quiesce**: wait for in-flight `s`-publishes accepted before the swap to resolve (the outputs layer already tracks per-payload acks — `SinkResult` — so this is a count, not a scan).
3. **Flush** Old's producer for the affected partition (producer-level `flush`, already a `Sink` trait method).
4. **Watermark**: record Old's end offset for the partition; the consumer side treats it as the fence — consume Old to the watermark, then start New. Only then release the held `s`-payloads to New.
5. **Handoff complete**; rollback is the same protocol with Old/New reversed. Failure inside the fence window falls back to releasing to the still-assigned side (the swap is not observable until step 4 completes).

The hold window is per-shard and bounded by one producer flush — that is the "minimal delay" drain. Shards move independently, so the deployment migrates partition by partition.

**Keyless traffic needs no fence.** `OrderingGuarantee::None` payloads (anonymous analytics without ordering constraints) have no per-key ordering contract — they switch clusters with a bare assignment swap, no hold/flush/watermark. Replay is keyed by session and follows the fenced path; dlq/custom redirects partition on the event key (`token:distinct_id`), same as main.

**Seam inventory:**

- `AddressedPayload` — carries key + address; grows `shard`.
- Outputs policy tree — `ShardRouted` slots in beside single/failover/split.
- The Step-27 control-plane seam — the pattern for the coordinator's assignment updates (swappable state, no request-path locks).
- `ProduceRecord` — grows `partition`; sinks realize shard → partition.
- Per-pipeline rows + topic tables (Step 18) — a coordinator can retarget one pipeline's row without touching the rest of the deployment.

## End state

When all steps land, the five strata hold:

- **Pipelines and lanes.** `pipeline::resolve` is the one lane decision (dlq > custom > historical > overflow > main), pure over `ProcessedEventMetadata`; `Pipeline`/`Lane` are the event's address.
- **Outputs are the produce surface.** Every pipeline publishes through the `OutputRegistry`; the `Output` policy tree (single | failover) owns all multi-target behavior, composing the way the old sink composites did. The v0 `Event` trait and `FallbackSink` are gone; `SplitKafkaSink` already is, deleted with the retired AI secondary-cluster routing.
- **Serialization is a seam.** Format × envelope per destination, with content headers carrying encoding coexistence (the lz4 replay design, generalized); a protobuf cutover is an output-level config change.
- **Sinks are mechanism, and own their namespace.** Payloads carry the abstract `Address`; each sink realizes it in its own namespace at publish time (Kafka: its per-cluster topic table — the swappable seam a repartitioning coordinator plugs into; S3: the buffer path; print/noop: trivially). Sinks make no routing decisions; a failover pair can share one prepared batch because payloads are target-agnostic. Serialization stays output-level (a consumer contract, shared across targets).
- **The failover switch is signal-drivable.** The failover output's target selection sits behind the Step-27 control-plane seam; a separate circuit-breaker service supplies the switch signals, capture supplies producer health, and a silent control plane holds the current target.
- **v1 resolves topics through the shared `TopicTable`** via `Destination::as_output`. The v1 `Sink`/`Router` trait convergence stays gated on the per-event response model.

## Agent conventions

**Build / test.** All cargo commands run via `flox activate -- cargo <cmd>` from `rust/`.

**Acceptance per step:**

- `flox activate -- cargo test -p capture` — scope to the named suites where the full run is slow; the Step-1 goldens always run.
- `flox activate -- cargo clippy -p capture --all-targets -- -D warnings`
- `flox activate -- cargo fmt`

**Git.** The orchestrator commits each step; one step = one commit, subject from the tracker below. No `--no-verify` — pre-commit hooks must pass.

## Progress tracker

| Step | Status | Commit subject |
| --- | --- | --- |
| 0 · This plan doc | done | `docs(capture): outputs refactor plan and progress tracker` |
| 1 · Routing golden oracle | done | `test(capture): consolidate routing golden oracle with headers and counters` |
| 2 · Pure `route()` | done | `refactor(capture): extract pure route() from prepare_record` |
| 3 · `TopicTable` + completeness | done | `refactor(capture): output registry with startup completeness check` |
| 4 · Serialization layer | done | `refactor(capture): serialization layer behind one seam` |
| 5 · `Pipeline` + `Lane`; lane resolution | done | `refactor(capture): lane decision moves to the pipeline layer` |
| 6 · Kafka sink → backend mechanism | done | `refactor(capture): narrow the kafka sink to backend mechanism over prepared payloads` |
| 7 · Outputs layer with policies; composites retired | done | `feat(capture): outputs layer owns the failover policy` |
| 8a · Call sites on the table | done | `refactor(capture): call sites publish through outputs` |
| 8b · `Event` retired | done | `refactor(capture): retire v0 Event trait` |
| 21 · An output owns its connection and topics | pending | `refactor(capture): outputs carry their own connection and topic config` |
| 22 · A reachable output must be configured | pending | `feat(capture): require configuration for every reachable output` |
| 23 · Verify topics against the broker | pending | `feat(capture): verify each output's topics against its own broker at boot` |
| 24 · capture-analytics emergency fallback | pending | `feat(capture): emergency fallback output for capture-analytics` |
| 25 · Retire the S3 fallback | pending | `refactor(capture): delete the s3 fallback output` |
| 26 · v1 convergence | pending | `refactor(capture): v1 resolves through shared pipeline/lane strata` |
| 27 · Failover selection behind a control-plane seam | objective 2 | `feat(capture): failover target selection behind a control-plane seam` |
| 28 · Producer health metrics out | objective 2 | `feat(capture): outputs report producer health for the breaker service` |
| 29 · Switch signals in | objective 2 | `feat(capture): apply breaker switch signals to the failover output` |
| 12 · Prep hoist; `PublishEvents` retired | deferred | `refactor(capture): hoist prep into outputs; sinks take prepared payloads only` |
| 13 · Typed addresses; AI pipeline | deferred | `refactor(capture): typed per-pipeline lanes; custom redirects and the ai stream become addresses` |
| 14 · Sinks realize namespaces | deferred | `refactor(capture): payloads carry addresses; sinks realize them in their own namespace` |
| 15 · Per-mode output registries | deferred | `feat(capture): per-mode output registries; handlers bound by publish capabilities` |
| 16 · AI ingress family | deferred | `feat(capture): ai ingress is its own router family with its own capability` |
| 17 · Topic tables injected into sinks | deferred | `refactor(capture): topic tables are sink-side data, injected at construction` |
| 18 · Per-pipeline output overrides; boot topic verification | deferred | `feat(capture): per-pipeline output overrides and boot topic verification` |
| 19a · Naming and import hygiene | deferred | `refactor(capture): replace remaining nested paths with imports` + `refactor(capture): name the session replay pipeline consistently` |
| 19b · Outputs as an open trait; sinks pure transport | deferred | `refactor(capture): outputs own namespace realization; Outputs becomes an open trait` |
| 19c · Dynamic outputs prototype | deferred | `feat(capture): prototype dynamic outputs with incremental switchover (test-only)` |
| 19d · Per-event publish results | deferred | `refactor(capture): Outputs::publish reports per-event results` |
| 20a · v1 boundary mapping + parity oracle | deferred | `feat(capture): v1 boundary mapping onto the shared produce interchange` |
| 20b · v1 publishes through shared outputs | deferred | `feat(capture): v1 endpoints publish through the shared outputs machinery` |
| 20c · Legacy v1 sink stack deleted; this plan retired | deferred | `refactor(capture): delete the legacy v1 sink stack` |
