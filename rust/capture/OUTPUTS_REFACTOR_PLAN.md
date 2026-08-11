# Capture outputs refactor — implementation plan

Working contract for implementation agents. This doc is the first commit of the draft PR; each `Step N` below becomes one commit in this combined PR and later graduates to its own standalone PR.

## Motivation

Three drivers, in order:

1. **Safe automatic failover**: Kafka-primary / S3-secondary failover as an output policy over any two targets, driven by a health breaker.
2. **Cluster migrations without code changes**: split (AI → WarpStream) and dual-write become configuration of an output's targets, as in the Node.js `IngestionOutputs` module — capture and Node converge on the same model.
3. **Payload format evolution**: a protobuf cutover becomes an output-level config change behind the serialization seam, rolled out with content-header coexistence like the replay lz4 envelope.

None of these fit the current shape: routing policy, serialization choice, and multi-target behavior are all tangled into the sink layer, so every one of them requires new sink composites with information smuggled through serialized records.

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

Steps 1–3 land together with this doc: the routing golden oracle, the pure `route()`, and the `OutputRegistry` with its startup completeness check. Production call sites still publish through the v0 `Event` trait (`send` / `send_batch`); the v1 stack (`CAPTURE_V1_SINKS`, opt-in) still runs its own serialize-then-publish pipeline with a per-event response model. The v1 `PreparedEvent { uuid, destination, payload: Bytes, headers, partition_key }` is the shape our output→sink handoff adopts.

### Vocabulary rules

- An event's **Address** is a lane of its pipeline (lanes typed per pipeline — `AnalyticsLane`, `AiLane`, `SessionReplayLane`, `BasicLane` — so invalid pairs are unrepresentable), or an admin **custom redirect** that carries its own topic outside the lane model. Pipeline and lane kind are projections; construction goes through `resolve`. Never reintroduce a flat destination enum that conflates pipeline and lane.
- **Output** = the addressed destination: targets + selection policy + serializer. **OutputTable** = the `(Pipeline, Lane)` → output mapping with the per-mode completeness check. The Step-3 `OutputRegistry` (output → topic) is absorbed into the table's targets.
- **Sink** = backend mechanism. Kafka, S3, print, noop. Nothing else is a sink; a thing that picks between sinks is an output policy.
- **Serializer** = format × envelope. Formats and envelopes compose; neither knows about sinks or outputs.

### Invariants

- Metric names and labels stay stable: `capture_events_rerouted_*`, `capture_primary_sink_health`, `capture_fallback_sink_failovers_total`, `capture_failover_breaker_*`, `capture_event_batch_size`. Renames are out of scope for every step.
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

#### Step 3 · `OutputRegistry` + startup completeness check

One output→topic wiring point plus refuse-to-boot on a blank topic, gated behind `CAPTURE_OUTPUTS_COMPLETENESS_CHECK_ENABLED` (default off; see Step 9's arming precondition).
Step 7 absorbs it into the `OutputTable`; the mode-scoped demand is folded in at Step 9, where `(Pipeline, Lane)` makes the per-mode reachable set explicit.

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
  - `OutputTable`: the `(pipeline, lane)` → output handle the state holds; degenerate today (one deployment-wide output; per-lane topics resolve in prep via the `OutputRegistry`).
  - `setup::create_output` builds the policy tree from the same config; **`FallbackSink` is deleted**, its tests re-expressed on `Output` with assertions preserved (+ a new fatal-no-failover case).
  - Call sites are untouched: the table serves them through a transitional `Event` facade (which records `capture_event_batch_size`, where the old sink impls recorded it). Migration is Step 8.
- **Files.** `rust/capture/src/outputs.rs` (new); `rust/capture/src/setup.rs`; `rust/capture/src/sinks/{mod,s3,print,noop,test_sink}.rs` (mechanism + `PublishEvents` impls); `fallback.rs` deleted.
- **Parity proof.** Goldens + all integration suites unmodified. Known metrics-only deltas, accepted: the batch-size histogram now records on the fallback-to-S3 path (it silently didn't before), and print/noop single sends record it (they didn't).
- **Risk / rollback.** Medium. Revert.
- **Size.** L.

#### Step 8 · Call sites migrate to the table; `Event` retired

- **Goal.** All four call sites (`events/analytics.rs`, `ai_endpoint.rs`, `otel/mod.rs`, `events/recordings.rs`) publish via `OutputTable::publish`, recording `capture_event_batch_size` at the call site; `State` and test mocks retype; then delete the v0 `Event` trait, the outputs facade, the Kafka `Event` bridge, and the single-event `kafka_send` path.
- **Parity proof.** All endpoint/integration suites green; grep proves `Event` call-site-free before the deletion half.
- **Size.** M/L. May split into per-call-site commits if the diff grows.

### Stage D — completeness, dark failover, convergence

#### Step 9 · Mode-scoped registry completeness

- **Goal.** `OutputRegistry::check_complete` scopes its demand per `CaptureMode`: an Events/Ai pod demands the analytics family, a Recordings pod main/replay-overflow/dlq only.
- **Arming precondition.** `CAPTURE_OUTPUTS_COMPLETENESS_CHECK_ENABLED` stays off in every deployment until this step lands and the chart env is audited for explicitly-blank topic values.
  The mode-blind check demands every registered topic on every pod, so a recordings or import deployment that sets an analytics topic to `""` would crashloop the fleet at boot, not degrade.
- **Parity proof.** Per-mode refusal + anti-over-demand tests.
- **Size.** M.

#### Step 10 · Breaker failover mode (dark)

- **Goal.** `FailoverMode::Breaker` — a pure clock-injected `Breaker` state machine, half-open single-probe permit, and a `StaticControlPlane` seam, as the second failover mode, dark behind `failover_enabled` (default off; off ⇒ Advisory mode byte-identical).
- **Parity proof.** 13+ deterministic breaker unit tests; four output-level behavior tests (healthy-primary, open→fallback→recover cycle, control-plane-down, fatal-no-failover). The effective-route gauge harness and a Notify-gated probe-concurrency harness graduate with the feature when it leaves dark mode.
- **Size.** M.

#### Step 11 · v1 converges on the shared strata

- **Goal.** v1's `Destination` bridges to `(Pipeline, Lane)`; v1 topic resolution goes through the shared table; v1's `serialize_batch` uses the Step-4 serializer. The v1 `Sink`/`Router` trait convergence stays gated on the per-event response model, as before.
- **Parity proof.** v1_pipeline (17) + v1_sink_integration (10) unmodified, plus `overflow_parity.rs` unmodified. That suite drives both pipelines end to end over the overflow and rate-limit matrix and is the oracle for the ordering-vs-person-processing contract this step has to carry across (see the Hazard note under "v1 convergence on the outputs machinery"). Both paths already share `OrderingGuarantee` from `crate::ordering`.
- **Size.** M/L.

### Stage E — prep hoists up; sinks become pure transport

#### Step 12 · Prep hoists into the outputs layer; `PublishEvents` retired

- **Goal.** Sinks take prepared payloads as input, full stop. `PrepSpec` (registry + per-destination serializers) moves payload assembly — lane resolution, serialization, header stamps, topic and partition key, and the scatter-gather batch prep — into the outputs layer; the `(pipeline, lane)` → output bridge and the `OutputRegistry` move with it (`outputs::registry`). The `PublishEvents` trait is deleted; every backend (Kafka, S3, print, noop) preps identically via its output's spec, and the Kafka sink is reduced to producer + enqueue + ack drain. The boot completeness check moves to `setup::create_output`.
- **Test posture change (deliberate).** Capturing mocks intercept *published payloads*, not `ProcessedEvent`s, so ~60 assertions that read metadata stamps migrate to wire-level outcomes: topic, partition key, headers, and payload bytes (deserialized for content checks). The declarative `ExpectedEvent` checkers recompute the expected record from the same expectations, so test bodies stay put. Wire-level assertions also pin a semantic the metadata-level ones couldn't see: replay events redirected to dlq/custom topics partition on the event key, not the session id.
- **Known deltas, accepted:** print/noop deployments run the real prep path (lane effects and their counters included), and prep can fail there (e.g. `MissingSessionId`) where the old passthrough couldn't. The prep histograms keep their `capture_kafka_*` names for dashboard continuity.
- **Files.** `outputs/mod.rs`, `outputs/registry.rs` (moved), `sinks/*`, `setup.rs`, all capturing test mocks.
- **Size.** L.

### Per-mode output tables (Step 15)

The deployment's output table is a concrete type — `AnalyticsFamilyOutputs` (analytics, ai, heatmaps, warnings, error tracking rows) for Events/Ai pods, `SessionReplayOutputs` for Recordings pods — with required fields, so the narrow list of what a deployment must wire is the type itself. Handlers bound on sealed capability traits (`PublishesAnalyticsFamily`, `PublishesSessionReplay`); `State<T>` is generic over the table and `setup` instantiates the monomorphized router per `CaptureMode` (`router` for the analytics family, `session_replay_router` for recordings) — mounting an ingress on a table that cannot publish its family is a compile error. Rows share backends (one Kafka connection, one S3 client, one breaker controller), so per-row policy trees behave as the single pre-table output did. The runtime backstop for a pipeline without a row is an explicit fatal error, structurally dead while ingress mounting and table type derive from the same mode.

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
5. **Plan retirement.** The 20c commit deletes this document — the plan must not outlive its last step.
   Anything still load-bearing then (the repartitioning design note, the ordering-vs-person-processing contract) graduates into module docs or `v1/sinks/DESIGN.md` first.

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

**A `ShardRouted` output policy.** Routing lives in the outputs layer as a policy node holding two child outputs (old cluster, new cluster) and a swappable assignment table `shard → Old | New` (an `ArcSwap`, updated by the coordinator's control plane the same way the failover breaker's control plane seam works). Batch publish splits by assignment and forwards — scatter-gather like the old `Split` composite, no serialization changes (both clusters share the prep/serialization contract, as the retired AI-secondary split proved).

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
- Breaker control-plane seam — the pattern for the coordinator's assignment updates (swappable state, no request-path locks).
- `ProduceRecord` — grows `partition`; sinks realize shard → partition.
- Per-pipeline rows + topic tables (Step 18) — a coordinator can retarget one pipeline's row without touching the rest of the deployment.

## End state

When all steps land, the five strata hold:

- **Pipelines and lanes.** `pipeline::resolve` is the one lane decision (dlq > custom > historical > overflow > main), pure over `ProcessedEventMetadata`; `Pipeline`/`Lane` are the event's address.
- **Outputs are the produce surface.** Every pipeline publishes through the `OutputTable`; the `Output` policy tree (single | failover) owns all multi-target behavior, composing the way the old sink composites did. The v0 `Event` trait and `FallbackSink` are gone; `SplitKafkaSink` already is, deleted with the retired AI secondary-cluster routing.
- **Serialization is a seam.** Format × envelope per destination, with content headers carrying encoding coexistence (the lz4 replay design, generalized); a protobuf cutover is an output-level config change.
- **Sinks are mechanism, and own their namespace.** Payloads carry the abstract `Address`; each sink realizes it in its own namespace at publish time (Kafka: its per-cluster topic table — the swappable seam a repartitioning coordinator plugs into; S3: the buffer path; print/noop: trivially). Sinks make no routing decisions; a failover pair can share one prepared batch because payloads are target-agnostic. Serialization stays output-level (a consumer contract, shared across targets).
- **Breaker failover is dark-launched** behind `CAPTURE_FAILOVER_ENABLED` as the failover output's autonomous mode.
- **v1 resolves topics through the shared `OutputRegistry`** via `Destination::as_output`. The v1 `Sink`/`Router` trait convergence stays gated on the per-event response model.

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
| 3 · `OutputRegistry` + completeness | done | `refactor(capture): output registry with startup completeness check` |
| 4 · Serialization layer | done | `refactor(capture): serialization layer behind one seam` |
| 5 · `Pipeline` + `Lane`; lane resolution | done | `refactor(capture): lane decision moves to the pipeline layer` |
| 6 · Kafka sink → backend mechanism | done | `refactor(capture): narrow the kafka sink to backend mechanism over prepared payloads` |
| 7 · Outputs layer with policies; composites retired | done | `feat(capture): outputs layer owns the failover policy` |
| 8a · Call sites on the table | pending | `refactor(capture): call sites publish through outputs` |
| 8b · `Event` retired | pending | `refactor(capture): retire v0 Event trait` |
| 9 · Mode-scoped completeness | pending | `refactor(capture): mode-scoped output registry completeness` |
| 10 · Breaker mode (dark) | pending | `feat(capture): breaker-driven failover mode (dark)` |
| 11 · v1 convergence | pending | `refactor(capture): v1 resolves through shared pipeline/lane strata` |
| 12 · Prep hoist; `PublishEvents` retired | pending | `refactor(capture): hoist prep into outputs; sinks take prepared payloads only` |
| 13 · Typed addresses; AI pipeline | pending | `refactor(capture): typed per-pipeline lanes; custom redirects and the ai stream become addresses` |
| 14 · Sinks realize namespaces | pending | `refactor(capture): payloads carry addresses; sinks realize them in their own namespace` |
| 15 · Per-mode output tables | pending | `feat(capture): per-mode output tables; handlers bound by publish capabilities` |
| 16 · AI ingress family | pending | `feat(capture): ai ingress is its own router family with its own capability` |
| 17 · Topic tables injected into sinks | pending | `refactor(capture): topic tables are sink-side data, injected at construction` |
| 18 · Per-pipeline output overrides; boot topic verification | pending | `feat(capture): per-pipeline output overrides and boot topic verification` |
| 19a · Naming and import hygiene | pending | `refactor(capture): replace remaining nested paths with imports` + `refactor(capture): name the session replay pipeline consistently` |
| 19b · Outputs as an open trait; sinks pure transport | pending | `refactor(capture): outputs own namespace realization; Outputs becomes an open trait` |
| 19c · Dynamic outputs prototype | pending | `feat(capture): prototype dynamic outputs with incremental switchover (test-only)` |
| 19d · Per-event publish results | pending | `refactor(capture): Outputs::publish reports per-event results` |
| 20a · v1 boundary mapping + parity oracle | pending | `feat(capture): v1 boundary mapping onto the shared produce interchange` |
| 20b · v1 publishes through shared outputs | pending | `feat(capture): v1 endpoints publish through the shared outputs machinery` |
| 20c · Legacy v1 sink stack deleted; this plan retired | pending | `refactor(capture): delete the legacy v1 sink stack` |
