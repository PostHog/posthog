# Capture outputs refactor — implementation plan

Working contract for implementation agents. Steps 1–8 have shipped. Each remaining step is one commit in its own PR.

This doc is deleted when it schedules nothing. Step 17 closes objective 1; objectives 2 and 3 are then scheduled in order. Before deletion, the parts still needed — the vocabulary rules, the ordering-vs-person-processing contract, the repartitioning note — move into module docs or `v1/sinks/DESIGN.md`, and unscheduled work becomes issues.

## Objectives

1. **Manual fallback.** If MSK degrades, capture-analytics can produce to another cluster, with its own brokers, TLS, and topic names. One environment variable and a pod roll arm it, and boot-time checks prove the configuration is sound before any traffic moves. Steps 9–17.
2. **One produce surface.** The v1 stack is live: capture-analytics and capture-import serve `/i/v1/analytics/events` through it, and capture-ai serves `/i/v1/ai/events`. It publishes through its own sinks, so a fallback in the outputs layer does not move its traffic. This objective moves v1 onto the outputs layer and deletes the v1 sink stack. Steps 18–21.
3. **Automated fallback, capture side.** A separate circuit-breaker service decides when to switch. Capture sends producer health, receives switch signals, and applies them at runtime without a redeploy. Consumers are out of scope. It comes last because an automatic switch that moves only part of the traffic is worse than the manual one. Steps 22–24.

All three use one mechanism:

- A **producer** is named, holds only connection config, and is instantiated once.
- An **output** holds its own topic names and the name of the producer it publishes through.
- Every output a deployment can reach must be fully configured.
- Each output's topics are checked against its producer's broker at boot.

A fallback is then a configuration of an output's targets, not a new code path. `Output::failover` already composes two outputs; it needs targets that can be configured independently, and for objective 3, a target selection that can change at runtime.

Today this is not possible. One deployment-wide `KafkaConfig` holds ten topic names, each with a compiled-in default, so a boot check cannot tell a configured topic from a missing one. The existing completeness flag demands all ten on every pod, so no deployment can enable it.

Every step is a small commit, proven by the Step-1 goldens, and reverted by plain revert. Cluster migration by split or dual-write, and a protobuf cutover, stay under **Deferred work**.

## Target architecture

```text
request handler   → Pipeline {Analytics, Ai, Heatmaps, Warnings, ErrorTracking, Replay}
pipeline steps    → stamp intent (restrictions, overflow, historical)
lane resolution   → Address {(Pipeline, Lane {Main, Overflow, Historical}) | Dlq | Custom(topic)}
                     + ordering guarantee + headers
outputs           → Address → output = 1..n targets + selection policy
                     (single | failover | split | dual-write);
                     target = own topics + a named producer
serialization     → per output: format (json | protobuf…) × envelope (none | lz4);
                     stamps content-type/encoding headers
sinks             → one backend: build the wire record, enqueue, ack. Kafka, S3, print, noop.
producers         → named connections (brokers, TLS, tuning), instantiated once,
                     shared by every output that names them
```

- **Pipeline** is decided by the HTTP handler that receives the request, from the endpoint and the event name, and stamped on the event as its `DataType`.
- **Lane** is decided once, by `pipeline::resolve`, from the intent stamped during processing. Precedence: dlq > custom > historical > overflow > main.
- **Output** is the destination for a `(Pipeline, Lane)`. It owns 1..n targets and the policy that picks between them per batch. All multi-target behavior lives here.
- **Serialization** is a contract with a destination's consumers, not with a transport. Content headers let old and new encodings share a topic during a migration, as replay's lz4 `content-encoding` does today.
- **Sink** is one backend. It turns a serialized payload into its wire shape and acks it. It makes no routing decision.
- **Producer** is a named connection, configured under its own namespace, like Node.js ingestion's `KafkaProducerRegistry`. Outputs share producers by name and never open their own connection. The ingestion-warnings producer (fire-and-forget, its own hosts) stays outside this model.

### Vocabulary rules

- **Address** = a lane of a pipeline, or an admin redirect (`Dlq`, `Custom(topic)`) outside the lane model. Construct it only through `resolve`. Never reintroduce a flat enum that mixes pipeline and lane.
- **Output** = targets + selection policy + serializer. **OutputRegistry** = the `(Pipeline, Lane)` → output map. The Step-3 **TopicTable** is absorbed into the registry's targets.
- **Destination** = a routed topic slot. v0's `sinks::registry::Destination` and v1's `v1::sinks::types::Destination` are the same concept and merge at Steps 19–21. Never call both a policy tree and a routed topic an `Output`.
- **Sink** = backend mechanism. Anything that picks between sinks is an output policy.
- **Producer** config never carries topic names, and output config never carries connection config. An output moves clusters by naming a different producer.
- **Serializer** = format × envelope. Neither knows about sinks or outputs.

### Invariants

- Metric names and labels stay stable: `capture_events_rerouted_*`, `capture_primary_sink_health`, `capture_fallback_sink_failovers_total`, `capture_event_batch_size`.
- Wire parity: the Step-1 goldens and existing endpoint and integration tests pass **unmodified**, unless a step says otherwise.
- Never mix a mechanical move with a behavior change in one commit.
- Every step ships green (`cargo test -p capture`, clippy `-D warnings`, fmt).
- Call sites keep the whole-request `CaptureError` until Step 18.
- No new sink code reads `ProcessedEventMetadata`. The Kafka sink's prep path is the one remaining reader; Step 25 removes it.

## Starting point

Steps 1–8 shipped the structure:

- **1** — `assert_routing` goldens pin topic, partition key, headers, and reroute counters for every pipeline and lane.
- **2, 5** — routing is the pure `pipeline::resolve(&metadata, ai_events_overflow_armed) -> AddressDecision { address, ordering }`. The Kafka sink still calls it during prep.
- **3** — `TopicTable` maps each `Destination` to a topic. `check_complete` refuses to boot on an empty topic, behind `CAPTURE_OUTPUTS_COMPLETENESS_CHECK_ENABLED` (default off).
- **4** — `serialization`: `Format` × `Envelope` → `Serializer`.
- **6** — the `Sink` trait takes `PreparedPayload`s. Kafka's `prepare_batch` is an inherent method.
- **7** — `outputs.rs`: `Output` is a leaf or a `failover` over two outputs. `FallbackSink` is deleted. Accepted metric change: `capture_event_batch_size` now records on the S3 fallback path and on print/noop single sends.
- **8** — every v0 call site publishes through `OutputRegistry::publish`. `State.outputs` is a concrete `Arc<OutputRegistry>`. The v0 `Event` trait is deleted. `kafka_send` stays on the one-event path: removing it adds a task spawn per event and drops the `ack_wait_one` span, so Step 25 takes it.

Today the registry holds one deployment-wide `Output`: a Kafka leaf, or Kafka→S3 failover. v1 (`CAPTURE_V1_SINKS`) runs its own serialize-then-publish pipeline with per-event results.

## Objective 1 — manual fallback

Steps 9–11 put every output, v1's included, on one config model. Steps 12–13 make the set of reachable outputs a type. Steps 14–15 are the checks that type allows. Step 16 is the fallback. Step 17 deletes what it replaces.

### Step 9 · Named producers, instantiated once

- **Goal.** Each producer is declared under `CAPTURE_PRODUCER_<NAME>_*`, holds only connection config (brokers, TLS, client tuning), and is instantiated once at startup. The connection half of `KafkaConfig` becomes one named producer. Behavior is byte-identical.
- **Why.** Two outputs on one cluster must share one connection, and moving one output to another cluster must not move the others. Sharing by name makes both structural.
- **How.** Reuse v1's namespaced parsing: `Envconfig::init_from_hashmap` under a name prefix, as `CAPTURE_V1_SINK_MSK_KAFKA_HOSTS` → `HOSTS` works today.
- **Parity proof.** Goldens and integration suites unmodified. A construction test pins one producer instance in the default configuration.
- **Size.** M.

### Step 10 · An output owns its topics and names its producer

- **Goal.** Each leaf output is built from its own config block: its topic names and a producer name. It no longer reads `KafkaConfig`. Two outputs can name different producers (different clusters) or the same one (one connection).
- **Why this is the whole mechanism.** `Output::failover` is Kafka→S3 only because `setup` builds it that way. After this step, a second cluster is one more producer and one more output block: a `setup` change and a values file.
- **Topic defaults stay** until Step 14.
- **Size.** M.

### Step 11 · v1 joins the shared config model

- **Goal.** Each `CAPTURE_V1_SINK_*` config splits into a named producer and that sink's topic rows. v1's `Destination` maps to `(Pipeline, Lane)`, v1 resolves topics through the shared table, and `serialize_batch` uses the Step-4 serializer. v1's `Sink`/`Router` traits stay until objective 2.
- **Why here.** v1's per-sink config is the last place that bundles connection and topics. Every later step built on a model v1 has not joined makes this step larger. Landing it before Steps 13–15 means those checks cover v1's topics too.
- **Parity proof.** `v1_pipeline`, `v1_sink_integration`, and `overflow_parity.rs` unmodified. `overflow_parity.rs` is the oracle for the ordering contract in the Step 19 hazard note.
- **Size.** M/L.

### Step 12 · Typed per-pipeline lanes

- **Goal.** Replace the flat `Lane` with `AnalyticsLane`, `AiLane`, `SessionReplayLane`, `BasicLane`, so invalid `(pipeline, lane)` pairs cannot be built. There is no `AiLane::Historical`: the AI divert wins over historical, as in v1.
- **Why.** Step 13's registry rows need one field per lane that exists. With a flat `Lane`, the registry needs a runtime error for pairs routing never produces.
- **Parity proof.** Goldens unmodified; `resolve` precedence tests retyped with the same assertions.
- **Size.** M/L.

### Step 13 · Per-mode output registries

- **Goal.** One registry type per capture mode, with required fields: `AnalyticsFamilyOutputs` (analytics, ai, heatmaps, warnings, error tracking) for Events, Ai, and Import pods, and `SessionReplayOutputs` for Recordings pods. Rows naming the same producer share its one instance.
- **Why.** Step 14 demands configuration per mode. Without these types, that demand is a hand-written mode → outputs map. With them, the type is the list.
- **Out of scope.** Binding handlers to capability traits over a generic `State<T>` (Step 28).
- **Parity proof.** Goldens and integration suites unmodified; per-mode construction tests.
- **Size.** L.

### Step 14 · A reachable output must be configured

- **Goal.** An output the deployment's mode can reach must have its topics and a defined producer name, or capture refuses to boot. An unreachable output is never asked for: a Recordings pod has no error-tracking row.
- **Defaults go.** Delete `#[envconfig(default = ...)]` from reachable outputs' topic fields. Today a missing or misspelled variable silently resolves to a compiled-in name.
- **Replaces** `CAPTURE_OUTPUTS_COMPLETENESS_CHECK_ENABLED`.
- **Parity proof.** Per-mode refusal tests, and tests proving no mode is asked for an output it cannot reach.
- **Size.** M.

Example of what this catches: until [charts#14941](https://github.com/PostHog/charts/pull/14941) (2026-09-01), capture-replay set its overflow topic under `KAFKA_OVERFLOW_TOPIC`, which replay does not read. Replay overflow went to the default `session_recording_snapshot_item_overflow`, and nothing failed. Step 14 refuses that at boot.

### Step 15 · Check each output's topics against its producer's broker

- **Goal.** At boot, read cluster metadata for every topic each reachable output can produce to, once per distinct producer, and refuse to start on a missing topic.
- **Why separate from Step 14.** Step 14 checks config and never connects. Step 15 checks that the topics exist on the cluster, which matters most for a cluster this deployment has never written to.
- **Off by default**, enabled per deployment: on brokers with topic auto-creation, the metadata request can create the topic it checks.
- **Size.** M.

### Step 16 · capture-analytics emergency fallback

- **Shape.** The capture-analytics output tree holds two Kafka outputs, primary and fallback. Each names its own producer (own brokers, own TLS) and its own topic names. The fallback cluster does not have to copy the primary's topic names.
- **Arming.** One environment variable, matched exactly against a sentinel value. `"1"`, `"true"`, or `"yes"` does not arm it; any value other than the sentinel refuses to boot. Unset is normal operation.
- **Static at boot.** One target publishes; switching means setting the variable and rolling the pods. A person decides to move off a degraded MSK. Automatic switching is objective 3.
- **The idle fallback is checked on every boot.** capture-analytics enables Step 15, and the tree always holds the fallback, so a broken fallback config fails an ordinary deploy, not the emergency.
- **Gauge** for the live target, emitted in both states, so a dashboard can tell "on primary" from "not reporting".
- **Scope.** capture-analytics only. Other modes have no fallback output and are not asked to configure one.
- **Known gaps, for the runbook.** Consumers have no matching switch. capture-import writes the same topics and must be stopped before any drain-to-zero check. The AI lane's bridges read MSK topic names. Until Step 20, v1 traffic stays on the primary.
- **Size.** M.

### Step 17 · Delete the S3 fallback

- **Goal.** Delete `S3Sink`, its `PublishEvents` impl, the `s3_fallback_*` config, and the Kafka→S3 wiring in `setup`.
- **Why it is safe.** No production deployment enables it. The charts set `S3_FALLBACK_ENABLED: "false"` in six values files and `"true"` only in `apps/capture-analytics/values.dev.yaml`.
- **Why Step 16 replaces it.** A second Kafka cluster keeps events flowing to consumers. S3 needs a separate replay path that has never run in production.
- **What is lost.** S3 failover is automatic; Step 16 is manual. No deployment uses the automatic path today, but the capability goes. Objective 3 brings it back through Step 22.
- **Cross-repo.** The seven charts values entries, the `CaptureAnalyticsV0S3FallbackActive` alert spec and runbook, and the IAM role in cloud-infra.
- **Size.** M.

## Objective 2 — one produce surface (unscheduled)

Scheduled when objective 1 closes.

### Step 18 · Per-event publish results

`OutputRegistry::publish` returns per-event `SinkResult`s, with a fold to the whole-request `CaptureError` for v0 call sites. v1's `BatchResponse` needs this before it can move.

### Steps 19–21 · v1 publishes through the outputs layer

1. **Boundary mapping (19).** After v1 processing, map each publishable `WrappedEvent` to a `ProcessedEvent` whose metadata makes `resolve` reproduce v1's decision: AnalyticsMain → main, Overflow → `force_overflow`, Historical → historical data type, Dlq → `redirect_to_dlq`, Custom → `redirect_to_topic`. `Destination::Drop` events never reach the outputs layer.
2. **Named outputs (20).** Each `CAPTURE_V1_SINKS` name becomes an output row built from that sink's config. The v1 `Router`, `Sink`, and `Event` traits and `serialize_batch` are deleted (21).
3. **Parity (19, 21).** `v1_pipeline` and `v1_sink_integration` pass against the new path: payload bytes, headers, topics, keys. Known v1-vs-v0 header differences are kept in the mapping. The old serializer and header builder survive only as a frozen `cfg(test)` oracle.

**Hazard: overflow carries two separate decisions.** Whether person processing is disabled (the `force_disable_person_processing` header, which customers see) and whether the partition key is dropped (`OrderingGuarantee`, a load decision). Both stacks follow one rule:

- The header follows the person-processing flag. A `ForceLimited` reason implies the flag (`person_processing_disabled`). v1 has no reason on the event; its one stamping site sets the flag.
- The key is dropped on the analytics main and overflow lanes when the flag is set, and on the AI overflow lane when the flag or a spread decision is set. Nowhere else. Analytics consumers update persons by distinct id, so a person-on burst keeps its key; the AI overflow consumer only reads persons. Historical, dlq, custom, and AI main always keep the key.

Extend `overflow_parity.rs` with the mapped v1 destinations; it pins lane, key presence, and header for both stacks.

**Accepted differences:** `sent_at` fractional-second formatting (parses equal; v1 adopts v0's serializer), and v1's own sink metrics (`capture_v1_serialize_*`, per-sink publish metrics), replaced by the outputs-layer metrics.

## Objective 3 — automated fallback (unscheduled)

A separate circuit-breaker service decides; how it decides is out of scope. Capture sends producer health and receives switch signals. These steps are scheduled with parity proofs once objectives 1 and 2 close.

### Step 22 · Failover target selection at runtime

The failover output's target selection becomes swappable state with no lock on the request path. Step 16's arming sets its boot value. A signal switches the target. No signal, or an unreachable control plane, keeps the current target: missing information must never move traffic. The Step-16 gauge reports the live target. With no service configured, behavior matches Step 16 exactly.

### Step 23 · Producer health out

Each named producer reports delivery latency, error rate, and queue depth under its name, including the idle fallback producer. Transport and cadence are decided when scheduled. Reporting must never slow the produce path.

### Step 24 · Switch signals in

Capture applies the service's switch signals through Step 22 and acknowledges them. The Step-16 variable stays the manual override and outranks the service; exact precedence is decided when scheduled. The breaker logic that an earlier plan put inside capture (`FailoverMode::Breaker`) belongs to the service.

## Deferred work

Unscheduled. To revive a step, move it under an objective with its parity proof.

### Step 25 · Prep moves into the outputs layer; `PublishEvents` deleted

- **Goal.** Sinks take only prepared payloads. A `PrepSpec` (registry + per-destination serializers) moves lane resolution, serialization, headers, topic, partition key, and batch prep into the outputs layer, with the `TopicTable` (`outputs::topics`). Every backend preps the same way; the Kafka sink keeps only producer, enqueue, and ack.
- **Tests.** Capturing mocks see published payloads, not `ProcessedEvent`s, so about 60 metadata assertions become wire-level (topic, key, headers, payload). The `ExpectedEvent` checkers rebuild the expected record, so test bodies stay the same. This also pins that replay events redirected to dlq/custom partition on the event key, not the session id.
- **Accepted differences.** print/noop run the real prep path, so they can now fail prep (e.g. `MissingSessionId`). Prep histograms keep their `capture_kafka_*` names.
- **Size.** L.

### Step 28 · Handlers bound by publish capabilities

Handlers bind on sealed traits (`PublishesAnalyticsFamily`, `PublishesSessionReplay`). `State<T>` is generic over the Step-13 registry, and `setup` builds the router per mode. Mounting an ingress on a registry that cannot publish its pipeline becomes a compile error.

### Steps 33–34 · Outputs as an open trait

`Outputs` becomes an open trait replacing the closed policy enum: `KafkaOutputs`, `S3Outputs`, `PrintOutputs`/`NoopOutputs`, and `FailoverOutputs`/`SplitOutputs` over `Arc<dyn Outputs>`. Sinks become pure transport and never see an `Address`. A test-only prototype (`outputs::dynamic`, Step 34) has `DynamicKafkaOutputs` take config pushes from an in-process `KafkaManagerService` and switch topics and brokers partition by partition.

Steps 27, 29, 30, and 32 are listed in the tracker only. Step 31 (per-pipeline overrides and boot topic checks) is superseded by Steps 10, 13, and 15.

## Repartitioning coordinator (design note)

Unscheduled. This records where a coordinator plugs in, so nothing already landed has to move. The goal: move a deployment between clusters one partition at a time, with a short hold per partition.

- **Shards decided above the sinks.** The coordinator owns `shard = hash(key) % N`, over the same key the sink hashes, with its own `N`. `PreparedPayload` gets `shard: Option<u32>` at prep time, so both targets of a pair see the same shard.
- **A `ShardRouted` output policy** holds two child outputs (old, new) and a swappable `shard → Old | New` table (`ArcSwap`, updated like Step 22). A batch splits by assignment.
- **Partition pass-through.** `ProduceRecord` gets `partition: Option<i32>`; the Kafka sink maps shard to a partition of its topic. `None` keeps key hashing.
- **Fence per shard `s`, Old → New:**
  1. Swap the entry for `s`; new `s` payloads are held.
  2. Wait for in-flight `s` publishes to Old to resolve (a count of `SinkResult`s).
  3. Flush Old's producer.
  4. Record Old's end offset as the consumer-side watermark: consumers read Old to it, then start on New. Release the held payloads to New.
  5. Rollback runs the same steps in reverse. A failure before step 4 releases to the still-assigned side.
- The hold lasts at most one producer flush per shard.
- **Keyless payloads** (`OrderingGuarantee::None`) switch with a bare swap. Replay follows the fence (keyed by session). dlq/custom follow it too (keyed by `token:distinct_id`).

## End state

When the three objectives close:

- `pipeline::resolve` is the one lane decision, pure over `ProcessedEventMetadata`.
- Every pipeline, v0 and v1, publishes through the `OutputRegistry`. The `Output` policy tree owns all multi-target behavior. The v1 sink stack is gone.
- Connection config lives with named producers. Pointing an output at another cluster means naming another producer.
- Serialization is format × envelope per destination.
- Sinks publish prepared payloads and make no routing decisions.
- The failover target can be switched at runtime by the breaker service, and a silent control plane keeps the current target.

## Agent conventions

Run cargo as `flox activate -d <worktree root> -- cargo <cmd>` from `rust/`. Each step must pass:

- `cargo test -p capture`. Scope to the named suites if the full run is slow; the Step-1 goldens always run.
- `cargo clippy -p capture --all-targets -- -D warnings`
- `cargo fmt`

One step = one commit, subject from the tracker. No `--no-verify`.

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
| 9 · Named producers, instantiated once | pending | `refactor(capture): named producers own their connection config` |
| 10 · An output owns its topics and names its producer | pending | `refactor(capture): outputs carry their own topics and name their producer` |
| 11 · v1 config convergence | pending | `refactor(capture): v1 resolves through shared pipeline/lane strata` |
| 12 · Typed per-pipeline lanes | pending | `refactor(capture): typed per-pipeline lanes` |
| 13 · Per-mode output registries | pending | `feat(capture): per-mode output registries with required rows` |
| 14 · A reachable output must be configured | pending | `feat(capture): require configuration for every reachable output` |
| 15 · Verify topics against the producer's broker | pending | `feat(capture): verify each output's topics against its producer's broker at boot` |
| 16 · capture-analytics emergency fallback | pending | `feat(capture): emergency fallback output for capture-analytics` |
| 17 · Retire the S3 fallback | pending | `refactor(capture): delete the s3 fallback output` |
| 18 · Per-event publish results | objective 2 | `refactor(capture): OutputRegistry::publish reports per-event results` |
| 19 · v1 boundary mapping + parity oracle | objective 2 | `feat(capture): v1 boundary mapping onto the shared produce interchange` |
| 20 · v1 publishes through shared outputs | objective 2 | `feat(capture): v1 endpoints publish through the shared outputs machinery` |
| 21 · Legacy v1 sink stack deleted | objective 2 | `refactor(capture): delete the legacy v1 sink stack` |
| 22 · Failover selection behind a control-plane seam | objective 3 | `feat(capture): failover target selection behind a control-plane seam` |
| 23 · Producer health metrics out | objective 3 | `feat(capture): producers report health for the breaker service` |
| 24 · Switch signals in | objective 3 | `feat(capture): apply breaker switch signals to the failover output` |
| 25 · Prep hoist; `PublishEvents` retired | deferred | `refactor(capture): hoist prep into outputs; sinks take prepared payloads only` |
| 26 · AI membership stamp; `AiRouting` retired | done | — (landed with the AI lane rollout, outside this plan's sequence) |
| 27 · Sinks realize namespaces | deferred | `refactor(capture): payloads carry addresses; sinks realize them in their own namespace` |
| 28 · Handlers bound by publish capabilities | deferred | `feat(capture): handlers bound by publish capabilities over per-mode state` |
| 29 · AI ingress family | deferred | `feat(capture): ai ingress is its own router family with its own capability` |
| 30 · Topic tables injected into sinks | deferred | `refactor(capture): topic tables are sink-side data, injected at construction` |
| 31 · Per-pipeline output overrides; boot topic verification | superseded | — (boot verification became Step 15; retargeting is configuration after Steps 10 and 13) |
| 32 · Naming and import hygiene | deferred | `refactor(capture): replace remaining nested paths with imports` + `refactor(capture): name the session replay pipeline consistently` |
| 33 · Outputs as an open trait; sinks pure transport | deferred | `refactor(capture): outputs own namespace realization; Outputs becomes an open trait` |
| 34 · Dynamic outputs prototype | deferred | `feat(capture): prototype dynamic outputs with incremental switchover (test-only)` |
