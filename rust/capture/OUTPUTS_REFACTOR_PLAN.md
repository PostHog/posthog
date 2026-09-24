# Capture outputs refactor — implementation plan

Working contract for implementation agents. Steps 1–8 have shipped. Each remaining step is one commit in its own PR.

This doc is deleted when it schedules nothing. Step 18 closes objective 1; objectives 2 and 3 are then scheduled in order. Before deletion, the parts still needed — the vocabulary rules, the ordering-vs-person-processing contract, the repartitioning note — move into module docs or `v1/sinks/DESIGN.md`, and unscheduled work becomes issues.

## Objectives

Capture has two produce stacks. The v0 endpoints (`/e`, `/batch`, `/i/v0/*`, replay, OTEL) stay forever. The v1 stack is live beside them: capture-analytics and capture-import serve `/i/v1/analytics/events` through it, and capture-ai serves `/i/v1/ai/events`. Both stacks produce through the outputs layer, and v0's internals move toward v1's shape.

1. **Manual fallback for all capture traffic.** If MSK degrades, capture-analytics can produce to another cluster, with its own brokers, TLS, and topic names. One environment variable and a pod roll arm it, for v0 and v1 traffic alike. Boot-time checks prove the configuration is sound before any traffic moves. Steps 9–18.
2. **One set of internals for v0 and v1.** The two stacks share producers and producer tuning, v0 builds prepared events before the outputs layer like v1, and both use one prepared-event builder and one lane-decision model. The v0 endpoints do not change. Steps 19–22.
3. **Automated fallback, capture side.** A separate circuit-breaker service decides when to switch. Capture sends producer health, receives switch signals, and applies them at runtime without a redeploy. Consumers are out of scope. Steps 23–25.

Objective 2 goes before 3 because it deletes v0's event-level route into the outputs layer; the runtime switch is then built once, on the one remaining route. Neither depends on the other otherwise, and objective 3 also waits on the breaker service existing.

All three use one mechanism:

- A **producer** is named, holds only connection config, and is instantiated once.
- An **output** holds its own topic names and the name of the producer it publishes through.
- Outputs take **prepared events**; each sink does its transport's encoding.
- Every output a deployment can reach must be fully configured.
- Each output's topics are checked against its producer's broker at boot.

A fallback is then a configuration of an output's targets, not a new code path. The policy tree already composes two outputs (Step 7). It needs targets that can be configured independently, a policy that picks the live target at boot (Step 17), and for objective 3, a way to change that pick at runtime.

Today this is not possible. One deployment-wide `KafkaConfig` holds ten topic names, each with a compiled-in default, so a boot check cannot tell a configured topic from a missing one. The existing completeness flag demands all ten on every pod. It fails any deployment that deliberately blanks a topic it never produces to, and where it can be enabled it still misses a missing variable, because the default fills it in. v1 publishes through its own sinks, so nothing in the outputs layer moves its traffic.

Every step is a small commit, proven by the Step-1 goldens, and reverted by plain revert. Cluster migration by split or dual-write stays under **Deferred work**.

## Target architecture

```text
request handler   → Pipeline {Analytics, Ai, Heatmaps, Warnings, ErrorTracking, Replay}
pipeline steps    → stamp intent (restrictions, overflow, historical)
lane decision     → Address {(Pipeline, Lane {Main, Overflow, Historical}) | Dlq | Custom(topic)}
                     + ordering guarantee
prepared event    → address, ordering + key, header values, JSON body; built once per event
outputs           → Address → output = 1..n targets + selection policy
                     (single | select | split | dual-write);
                     target = own topics + a named producer
sinks             → transport encoding (Kafka: topic, key, headers, optional lz4 envelope;
                     S3 until Step 18: JSON lines), enqueue, ack
producers         → named connections (brokers, TLS, tuning), instantiated once,
                     shared by every output that names them
```

- **Pipeline** is decided by the HTTP handler that receives the request, from the endpoint and the event name, and stamped on the event as its `DataType`.
- **Lane** is decided once per event, by `pipeline::resolve` in v0 and by assign-then-reroute in v1. Precedence: dlq > custom > historical > overflow > main.
- **Prepared event** is everything a destination's consumers see, independent of transport: the address, the ordering guarantee and its key, the header values, and the event body as JSON. It is built once, and every target of an output receives the same bytes.
- **Output** is the destination for an address. It owns 1..n targets and the policy that picks between them per batch. A target maps the address to its own topic and publishes through its named producer. All multi-target behavior lives here.
- **Sink** is one transport. It turns a prepared event into its wire record and acks it. The lz4 envelope and its `content-encoding` header are Kafka encoding, set per target. The sink makes no routing decision.
- **Producer** is a named connection, configured under its own namespace, like Node.js ingestion's `KafkaProducerRegistry`. Outputs share producers by name and never open their own connection. The ingestion-warnings producer (fire-and-forget, its own hosts) stays outside this model.

### Vocabulary rules

- **Address** = a lane of a pipeline, or an admin redirect (`Dlq`, `Custom(topic)`) outside the lane model. v0 builds it through `resolve`, v1 by mapping its `Destination`. Never reintroduce a flat enum that mixes pipeline and lane.
- **Prepared event** = the transport-independent result of processing one event. v1's `PreparedEvent` is the shape; v0's `PreparedPayload` differs only in carrying a topic instead of an address.
- **Output** = targets + selection policy. **OutputRegistry** = the address → output map. The Step-3 **TopicTable** is absorbed into the targets.
- **Destination** = v0's `sinks::registry::Destination` and v1's `v1::sinks::types::Destination` name the same routed slots. Both map onto `Address`. Never call both a policy tree and a routed topic an `Output`.
- **Sink** = one transport. Anything that picks between sinks is an output policy.
- **Producer** config never carries topic names, and output config never carries connection config. An output moves clusters by naming a different producer.

### Invariants

- Metric names and labels stay stable: `capture_events_rerouted_*`, `capture_event_batch_size`, and until Step 18, `capture_primary_sink_health` and `capture_fallback_sink_failovers_total`. Steps that retire a metric list it as an accepted difference.
- Wire parity: the Step-1 goldens and existing endpoint and integration tests pass **unmodified**, unless a step says otherwise.
- Never mix a mechanical move with a behavior change in one commit.
- Every step ships green (`cargo test -p capture`, clippy `-D warnings`, fmt).
- v0 call sites keep the whole-request `CaptureError`. v1 keeps its per-event response.
- No new sink code reads `ProcessedEventMetadata`. The Kafka sink's v0 prep path is the one remaining reader; Step 20 removes it.

## Starting point

Steps 1–8 shipped the structure:

- **1** — `assert_routing` goldens pin topic, partition key, headers, and reroute counters for every pipeline and lane.
- **2, 5** — routing is the pure `pipeline::resolve(&metadata, ai_events_overflow_armed) -> AddressDecision { address, ordering }`. The Kafka sink still calls it during prep.
- **3** — `TopicTable` maps each `Destination` to a topic. `check_complete` refuses to boot on an empty topic, behind `CAPTURE_OUTPUTS_COMPLETENESS_CHECK_ENABLED` (default off).
- **4** — `serialization`: `Format` (JSON only) × `Envelope` (none or lz4) → `Serializer`, used in Kafka prep.
- **6** — the `Sink` trait takes `PreparedPayload`s and returns per-event `SinkResult`s. Kafka's `prepare_batch` is an inherent method.
- **7** — `outputs.rs`: `Output` is a leaf or a `failover` over two outputs. `FallbackSink` is deleted. Accepted metric change: `capture_event_batch_size` now records on the S3 fallback path and on print/noop single sends.
- **8** — every v0 call site publishes through `OutputRegistry::publish`. `State.outputs` is a concrete `Arc<OutputRegistry>`. The v0 `Event` trait is deleted. `kafka_send` stays on the one-event path: removing it adds a task spawn per event and drops the `ack_wait_one` span, so Step 20 takes it.

Today the registry holds one deployment-wide `Output`: a Kafka leaf, or Kafka→S3 failover. v1 (`CAPTURE_V1_SINKS`) serializes its own `PreparedEvent`s and publishes them through its own `Router` to one default sink, the first name in `CAPTURE_V1_SINKS`.

## Objective 1 — manual fallback for all capture traffic

Steps 9–10 move configuration onto named producers and outputs. Steps 11–12 bring v1 onto the outputs layer. Steps 13–14 make the set of reachable outputs a type. Steps 15–16 are the checks that type allows. Step 17 is the fallback. Step 18 deletes the S3 fallback it replaces.

### Step 9 · Named producers, instantiated once

- **Goal.** Producer slots are declared in code, and each holds only connection config (brokers, TLS, client tuning) and is instantiated once at startup. The v0 Kafka output publishes through the `INGESTION` slot, which replaces the connection half of `KafkaConfig`. Behavior is byte-identical.
- **Why.** Two outputs on one cluster must share one connection, and moving one output to another cluster must not move the others. Sharing by name makes both structural.
- **Same model as Node.js ingestion.** A slot is a role, not a cluster; charts wire it to a cluster per deployment. Its settings are `KAFKA_<SLOT>_PRODUCER_<RDKAFKA_KEY>`, for example `KAFKA_INGESTION_PRODUCER_METADATA_BROKER_LIST`. Slot names are single words, so no slot's prefix is a prefix of another's.
- **Migration.** Explicit: capture stops reading `KAFKA_HOSTS`, `KAFKA_TLS`, and the `KAFKA_PRODUCER_*` tuning; charts set the new variables first. The broker list defaults to `kafka:9092`, the local dev and hobby broker, so those setups need no change. capture-logs keeps its own `KafkaConfig`.
- **Parity proof.** Goldens and integration suites unmodified. A test pins the rdkafka settings of the default slot config to capture's current ones.
- **Size.** M.

### Step 10 · An output owns its topics and names its producer

- **Goal.** Each leaf output is built from its own config block: its topic names and a producer name. It no longer reads `KafkaConfig`. Two outputs can name different producers (different clusters) or the same one (one connection).
- **Why.** The policy tree composes any two outputs; the only pair today is Kafka→S3 because `setup` builds it that way. After this step, a second cluster is one more producer and one more output block: a `setup` change and a values file.
- **Topic defaults stay** until Step 15.
- **Size.** M.

### Step 11 · Outputs accept prepared events

- **Goal.** A second route into the outputs layer: `publish_prepared(Vec<PreparedEvent>) -> Vec<SinkResult>`, one result per event. Each target maps the event's address to its own topic, and its sink does the transport encoding: the Kafka sink builds the record, and the S3 sink writes the JSON body as a line. Every policy works on this route. v0's event route is unchanged.
- **Why.** v1 already produces prepared events with per-event results. Joining at this level leaves v1's lane decision, JSON body, and response model untouched, so there is no second pass through `resolve` and no parity mapping of v1 decisions onto v0 metadata.
- **Parity proof.** New tests drive prepared events through each leaf and each policy. Goldens unmodified.
- **Size.** M.

### Step 12 · v1 publishes through the outputs layer

- **Goal.** v1 maps its `Destination` to `Address` and calls `publish_prepared`. v1's `Router`, `Sink`, `KafkaSink`, and per-sink Kafka config are deleted. Each `CAPTURE_V1_SINK_*` cluster becomes a named producer, and its topics become output rows. The `topic_ai` override in `setup::create_v1_sink_router` goes with it.
- **Produce timeout moves to the shared Kafka sink.** v1 bounds each batch's acks by a produce timeout; acks that miss it return `Outcome::Timeout`, and the events are retried. The shared Kafka sink gains this, configured per target.
- **Kept separate until Step 19.** v1's producer tuning differs from v0's (for example lz4 vs no compression, 4 vs 2 retries, 30 s vs 20 s message timeout), so each stack keeps its own named producer and tuning. capture-analytics keeps its two MSK connections, one per stack.
- **Accepted differences.** The `capture_v1_kafka_*` metrics are replaced by the shared Kafka sink's metrics.
- **Parity proof.** `v1_pipeline`, `v1_sink_integration`, and `overflow_parity.rs` unmodified.
- **Size.** L.

### Step 13 · Typed per-pipeline lanes

- **Goal.** Replace the flat `Lane` with `AnalyticsLane`, `AiLane`, `SessionReplayLane`, `BasicLane`, so invalid `(pipeline, lane)` pairs cannot be built. There is no `AiLane::Historical`: the AI divert wins over historical, as in v1. Both stacks hand this address type to the outputs layer.
- **Why.** Step 14's registry rows need one field per lane that exists. With a flat `Lane`, the registry needs a runtime error for pairs routing never produces.
- **Parity proof.** Goldens unmodified; `resolve` precedence tests retyped with the same assertions.
- **Size.** M/L.

### Step 14 · Per-mode output registries

- **Goal.** One registry type per capture mode, with required fields: `AnalyticsFamilyOutputs` (analytics, ai, heatmaps, warnings, error tracking) for Events and Import pods, `AiOutputs` for Ai pods, and `SessionReplayOutputs` for Recordings pods. Rows naming the same producer share its one instance.
- **Each type holds exactly what its mode can reach.** The set comes from the routes the mode mounts: Ai pods serve only the AI batch, AI, OTEL, and v1 AI routes (`router.rs`), so `AiOutputs` does not demand heatmaps, warnings, or error-tracking topics. The exact rows for each mode, Import included, are derived from its routes when this step is scheduled.
- **Why.** Step 15 demands configuration per mode. Without these types, that demand is a hand-written mode → outputs map. With them, the type is the list.
- **Out of scope.** Binding handlers to capability traits over a generic `State<T>` (Step 29).
- **Parity proof.** Goldens and integration suites unmodified; per-mode construction tests.
- **Size.** L.

### Step 15 · A reachable output must be configured

- **Goal.** An output the deployment's mode can reach must have its topics and a defined producer name, or capture refuses to boot. An unreachable output is never asked for: a Recordings pod has no error-tracking row.
- **Defaults go.** Delete `#[envconfig(default = ...)]` from reachable outputs' topic fields. Today a missing or misspelled variable silently resolves to a compiled-in name.
- **Replaces** `CAPTURE_OUTPUTS_COMPLETENESS_CHECK_ENABLED`.
- **Parity proof.** Per-mode refusal tests, and tests proving no mode is asked for an output it cannot reach.
- **Size.** M.

Example of what this catches: until [charts#14941](https://github.com/PostHog/charts/pull/14941) (2026-09-01), capture-replay set its overflow topic under `KAFKA_OVERFLOW_TOPIC`, which replay does not read. Replay overflow went to the default `session_recording_snapshot_item_overflow`, and nothing failed. Step 15 refuses that at boot.

### Step 16 · Check each output's topics against its producer's broker

- **Goal.** At boot, read cluster metadata for every topic each reachable output can produce to, once per distinct producer, and refuse to start on a missing topic.
- **Why separate from Step 15.** Step 15 checks config and never connects. Step 16 checks that the topics exist on the cluster, which matters most for a cluster this deployment has never written to.
- **The check never creates a topic.** A producer's metadata request can make a broker with topic auto-creation create the topic, with broker defaults, and then the check passes. The check uses an admin metadata request with auto-creation disabled, so a missing topic stays missing until someone provisions it.
- **Enabled per deployment.**
- **Size.** M.

### Step 17 · capture-analytics emergency fallback

- **Shape.** The capture-analytics output tree holds two Kafka outputs, primary and fallback. Each names its own producer (own brokers, own TLS) and its own topic names. The fallback cluster does not have to copy the primary's topic names. v0 and v1 traffic both publish through this tree.
- **Arming.** One environment variable, matched exactly against a sentinel value. `"1"`, `"true"`, or `"yes"` does not arm it; any value other than the sentinel refuses to boot. Unset is normal operation.
- **Static at boot.** A new `select` policy holds both targets and publishes to one, picked by the arming variable. It does not react to health: switching means setting the variable and rolling the pods, because a person decides to move off a degraded MSK. Automatic switching is objective 3. The health-gated `failover` policy is not used here; it serves only S3.
- **A retryable error stays on the live target.** It returns to the caller like any other publish error and never sends the batch to the other target.
- **The idle fallback is checked on every boot.** capture-analytics enables Step 16, and the tree always holds the fallback, so a broken fallback config shows up on an ordinary deploy, not in the emergency.
- **What an idle-fallback failure does is configuration.** It covers a failed Step-16 check on the fallback cluster and a fallback producer that cannot connect. Producer creation returns the result of its broker probe instead of only logging it, so the configured mode can act on it:
  - `warn` (default): capture keeps serving on the primary. The fallback producer is advisory, a per-producer health gauge reports it as down, and capture logs an error. The gauge needs an alert, since nothing else fails.
  - `strict`: capture refuses to boot, and a dead fallback producer fails pod liveness.
- **Armed, the checks follow the live target.** The fallback is live, so a failed Step-16 check or a fallback producer that cannot connect refuses boot, whatever the mode. In a rolling update the new pods fail and the old pods keep serving on the primary, so traffic never moves to a dead cluster. The primary is idle and always gets `warn` handling: arming means MSK is degraded, so its checks are expected to fail, and they must not block the switch.
- **Gauge** for the live target, emitted in both states, so a dashboard can tell "on primary" from "not reporting".
- **Scope.** capture-analytics only. Other modes have no fallback output and are not asked to configure one.
- **Not in this plan: the consumer switch.** Arming moves where capture writes. It does not move the consumers, which keep reading the primary cluster until they are repointed. This plan does not implement that switch; the runbook repoints consumers in the same operation. Until then, events wait in the fallback topics.
- **Known gaps, for the runbook.** capture-import writes the same topics and must be stopped before any drain-to-zero check. The AI lane's bridges read MSK topic names.
- **Size.** M/L.

### Step 18 · Delete the S3 fallback

- **Goal.** Delete `S3Sink`, the `s3_fallback_*` config, the Kafka→S3 wiring in `setup`, and the health-gated `failover` policy, which serves only S3.
- **Why it is safe.** No production deployment enables it. The charts set `S3_FALLBACK_ENABLED: "false"` in six values files and `"true"` only in `apps/capture-analytics/values.dev.yaml`.
- **Why Step 17 replaces it.** A second Kafka cluster keeps events flowing to consumers. S3 needs a replay path that has never run in production.
- **Accepted differences.** `capture_primary_sink_health` and `capture_fallback_sink_failovers_total` go with the policy that emits them.
- **What is lost.** S3 failover is automatic; Step 17 is manual. No deployment uses the automatic path today, but the capability goes. Objective 3 brings it back through Step 23.
- **Cross-repo.** The seven charts values entries, the `CaptureAnalyticsV0S3FallbackActive` alert spec and runbook, and the IAM role in cloud-infra.
- **Size.** M.

## Objective 2 — one set of internals for v0 and v1 (unscheduled)

Scheduled when objective 1 closes. The v0 endpoints and their responses do not change.

### Step 19 · One producer per cluster

v0 and v1 producer tuning is reconciled into one set per cluster, and capture-analytics opens one MSK connection instead of two. Each difference (compression, retries, message timeout, metadata refresh, and the rest) is either adopted by both stacks or recorded as a per-producer setting with a reason.

### Step 20 · v0 builds prepared events

v0 resolves the lane, builds the JSON body and header values, and hands prepared events to `publish_prepared`, as v1 does. The lz4 envelope moves into the Kafka sink as target config. `PublishEvents`, `kafka_send`, and v0's event route into the outputs layer are deleted. v0 call sites fold per-event results into the whole-request `CaptureError`.

- **Tests.** Capturing mocks see prepared events, not `ProcessedEvent`s, so about 60 metadata assertions become wire-level (topic, key, headers, payload). The `ExpectedEvent` checkers rebuild the expected record, so test bodies stay the same. This also pins that replay events redirected to dlq/custom partition on the event key, not the session id.
- **Accepted differences.** print/noop run the real prep path, so they can now fail prep (e.g. `MissingSessionId`). Prep histograms keep their `capture_kafka_*` names.

### Step 21 · One prepared-event builder

v0 and v1 build the JSON body and header values with the same code. Known differences are settled here: `sent_at` fractional-second formatting (parses equal; v1 adopts v0's), and the header differences pinned by `overflow_parity.rs`.

### Step 22 · One lane-decision model

v0's lane decision moves to v1's model.

**Hazard: overflow carries two separate decisions.** Whether person processing is disabled (the `force_disable_person_processing` header, which customers see) and whether the partition key is dropped (`OrderingGuarantee`, a load decision). Both stacks follow one rule today, and the merged model must keep it:

- The header follows the person-processing flag. A `ForceLimited` reason implies the flag (`person_processing_disabled`). v1 has no reason on the event; its one stamping site sets the flag.
- The key is dropped on the analytics main and overflow lanes when the flag is set, and on the AI overflow lane when the flag or a spread decision is set. Nowhere else. Analytics consumers update persons by distinct id, so a person-on burst keeps its key; the AI overflow consumer only reads persons. Historical, dlq, custom, and AI main always keep the key.

`overflow_parity.rs` pins lane, key presence, and header for both stacks over the overflow and rate-limit matrix. It stays green through the merge.

## Objective 3 — automated fallback (unscheduled)

A separate circuit-breaker service decides; how it decides is out of scope. Capture sends producer health and receives switch signals. These steps are scheduled with parity proofs once objectives 1 and 2 close.

### Step 23 · Target selection at runtime

The `select` policy's live target becomes swappable state with no lock on the request path. Each batch reads the live target once, and its acks and retries stay on that target, so a switch never splits a batch or sends it twice. Step 17's arming sets its boot value. A signal switches the target. No signal, or an unreachable control plane, keeps the current target: missing information must never move traffic. The Step-17 gauge reports the live target. With no service configured, behavior matches Step 17 exactly. As in Step 17, a switch moves only where capture writes. Repointing consumers happens outside capture and outside this plan, and must be coordinated with the switch before it is automated.

### Step 24 · Producer health out

Each named producer reports delivery latency, error rate, and queue depth under its name, including the idle fallback producer. Transport and cadence are decided when scheduled. Reporting must never slow the produce path.

### Step 25 · Switch signals in

Capture applies the service's switch signals through Step 23 and acknowledges them. The Step-17 variable stays the manual override and outranks the service; exact precedence is decided when scheduled. The breaker logic that an earlier plan put inside capture (`FailoverMode::Breaker`) belongs to the service.

## Deferred work

Unscheduled. To revive a step, move it under an objective with its parity proof.

### Step 29 · Handlers bound by publish capabilities

Handlers bind on sealed traits (`PublishesAnalyticsFamily`, `PublishesSessionReplay`). `State<T>` is generic over the Step-14 registry, and `setup` builds the router per mode. Mounting an ingress on a registry that cannot publish its pipeline becomes a compile error.

### Steps 34–35 · Outputs as an open trait

`Outputs` becomes an open trait replacing the closed policy enum: `KafkaOutputs`, `PrintOutputs`/`NoopOutputs`, and `SelectOutputs`/`SplitOutputs` over `Arc<dyn Outputs>`. A test-only prototype (`outputs::dynamic`, Step 35) has `DynamicKafkaOutputs` take config pushes from an in-process `KafkaManagerService` and switch topics and brokers partition by partition.

Split and dual-write policies are also unscheduled. Before either is scheduled, it must define how per-target results become one result per event, which failures it retries, and how it handles an event delivered to both targets.

Steps 30 and 33 are listed in the tracker only. Steps 26, 28, 31, and 32 are superseded; the tracker says by what.

## Repartitioning coordinator (design note)

Unscheduled. This records where a coordinator plugs in, so nothing already landed has to move. The goal: move a deployment between clusters one partition at a time, with a short hold per partition.

- **Shards decided above the sinks.** The coordinator owns `shard = hash(key) % N`, over the same key the sink hashes, with its own `N`. The prepared event gets `shard: Option<u32>`, so both targets of a pair see the same shard.
- **A `ShardRouted` output policy** holds two child outputs (old, new) and a swappable `shard → Old | New` table (`ArcSwap`, updated like Step 23). A batch splits by assignment.
- **Partition pass-through.** `ProduceRecord` gets `partition: Option<i32>`; the Kafka sink maps shard to a partition of its topic. `None` keeps key hashing.
- **Fence per shard `s`, Old → New:**
  1. Swap the entry for `s`; new `s` events are held.
  2. Wait for in-flight `s` publishes to Old to resolve (a count of `SinkResult`s).
  3. Flush Old's producer.
  4. Record Old's end offset as the consumer-side watermark: consumers read Old to it, then start on New. Release the held events to New.
  5. Rollback runs the same steps in reverse. A failure before step 4 releases to the still-assigned side.
- The hold lasts at most one producer flush per shard.
- **Keyless events** (`OrderingGuarantee::None`) switch with a bare swap. Replay follows the fence (keyed by session). dlq/custom follow it too (keyed by `token:distinct_id`).

## End state

When the three objectives close:

- v0 and v1 share producers, one prepared-event builder, and one lane-decision model; the v0 endpoints are unchanged.
- Every prepared event publishes through the `OutputRegistry`. The `Output` policy tree owns all multi-target behavior. The v1 sink stack is gone.
- Connection config lives with named producers, one per cluster. Pointing an output at another cluster means naming another producer.
- Sinks do transport encoding only and make no routing decisions.
- The `select` policy's live target can be switched at runtime by the breaker service, and a silent control plane keeps the current target.

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
| 11 · Outputs accept prepared events | pending | `feat(capture): outputs publish prepared events with per-event results` |
| 12 · v1 publishes through the outputs layer | pending | `refactor(capture): v1 publishes through outputs; v1 sink stack deleted` |
| 13 · Typed per-pipeline lanes | pending | `refactor(capture): typed per-pipeline lanes` |
| 14 · Per-mode output registries | pending | `feat(capture): per-mode output registries with required rows` |
| 15 · A reachable output must be configured | pending | `feat(capture): require configuration for every reachable output` |
| 16 · Verify topics against the producer's broker | pending | `feat(capture): verify each output's topics against its producer's broker at boot` |
| 17 · capture-analytics emergency fallback | pending | `feat(capture): select policy and emergency fallback for capture-analytics` |
| 18 · Delete the S3 fallback | pending | `refactor(capture): delete the s3 fallback and the health-gated failover policy` |
| 19 · One producer per cluster | objective 2 | `refactor(capture): v0 and v1 share one producer per cluster` |
| 20 · v0 builds prepared events | objective 2 | `refactor(capture): v0 publishes prepared events; PublishEvents retired` |
| 21 · One prepared-event builder | objective 2 | `refactor(capture): v0 and v1 share one prepared-event builder` |
| 22 · One lane-decision model | objective 2 | `refactor(capture): v0 lane decision moves to the v1 model` |
| 23 · Target selection at runtime | objective 3 | `feat(capture): select policy target switchable at runtime` |
| 24 · Producer health metrics out | objective 3 | `feat(capture): producers report health for the breaker service` |
| 25 · Switch signals in | objective 3 | `feat(capture): apply breaker switch signals to the select policy` |
| 26 · Prep hoist; `PublishEvents` retired | superseded | — (became Step 20) |
| 27 · AI membership stamp; `AiRouting` retired | done | — (landed with the AI lane rollout, outside this plan's sequence) |
| 28 · Sinks realize namespaces | superseded | — (targets map addresses to topics from Step 11) |
| 29 · Handlers bound by publish capabilities | deferred | `feat(capture): handlers bound by publish capabilities over per-mode state` |
| 30 · AI ingress family | deferred | `feat(capture): ai ingress is its own router family with its own capability` |
| 31 · Topic tables injected into sinks | superseded | — (each target owns its topics from Step 10) |
| 32 · Per-pipeline output overrides; boot topic verification | superseded | — (boot verification became Step 16; retargeting is configuration after Steps 10 and 14) |
| 33 · Naming and import hygiene | deferred | `refactor(capture): replace remaining nested paths with imports` + `refactor(capture): name the session replay pipeline consistently` |
| 34 · Outputs as an open trait | deferred | `refactor(capture): Outputs becomes an open trait` |
| 35 · Dynamic outputs prototype | deferred | `feat(capture): prototype dynamic outputs with incremental switchover (test-only)` |
