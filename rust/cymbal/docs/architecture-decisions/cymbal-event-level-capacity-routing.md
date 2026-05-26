# Cymbal event-level capacity-aware routing

## Decision

Cymbal uses a reusable, transport-neutral framework that routes each event/item independently while still dispatching efficient remote sub-batches.
Dependency-light framework pieces live in `cymbal-core` modules, not in `cymbal-server`, because candidate ordering, capacity accounting, fallback decisions, and item ordering are not inherently gRPC, DNS, metrics, or Cymbal-runtime concerns.

A new crate should only be introduced if the reusable framework grows beyond `cymbal-core`'s contract role, for example by needing heavyweight async execution dependencies, multiple concrete executors, or enough public surface area that it obscures the core stage contracts.
Until then:

- `cymbal-core` should own reusable routing keys, routing policies, capacity snapshots, partitioning results, fallback/attempt decision enums, and minimal item-index/outcome contracts.
- `cymbal-pipeline` should own pure Rust pipeline composition and any buffered or incremental orchestration that wires stage executors together.
- `cymbal-server` should own gRPC transport, DNS endpoint discovery, tonic status/metadata mapping, metrics/log emission, env parsing, endpoint clients, and Cymbal's default remote-stage policy selection.
- Stage crates should continue to own business logic and side effects.

## Event-level routing semantics

For each logical stage invocation, the orchestrator should treat the input vector as indexed items:

1. Compute a routing key per item with a stage-specific `RoutingKeyExtractor<Item>`.
2. Ask the routing policy for an ordered concrete endpoint candidate list per item.
3. Consult fresh per-endpoint capacity and a local reservation ledger for this invocation.
4. Assign each item to the first candidate with effective remaining capacity.
5. Group assigned items by selected endpoint into remote sub-batches, preserving each item's original index and ID.
6. Return explicit unroutable/over-capacity items when no candidate can accept the item under the policy.

The ordered candidate logic should preserve the current policy behavior where possible: affinity-first uses deterministic rendezvous ordering, random uses injected RNG, strict affinity emits only the primary, and max fallback attempts cap candidate count.
The event-level change is that this ordering is evaluated for every item rather than once for the whole input batch.

## Remote API remains batch/sub-batch based

`CymbalStageRuntime.ProcessStage(StageBatch) -> StageBatchResult` should remain a unary batch API.
Event-level routing does not imply one gRPC request per event.
Sub-batches keep the existing stage contract efficient because they:

- amortize gRPC, TLS/HTTP2, codec, and metadata overhead;
- let stages perform vectorized repository/cache work and produce item-level errors in one response;
- keep overload and load-snapshot metadata tied to a concrete pod response;
- avoid creating a request fan-out explosion for ordinary public batches;
- preserve the current internal `StageItem`/`StageItemResult` envelope and stage type validation.

Very small sub-batches may naturally contain one event, but that should be an outcome of capacity/routing, not the default dispatch unit.

## Capacity semantics

Capacity is expressed in concurrent events/items, not only concurrent stage batches.
A remote stage pod should admit a sub-batch of `N` items only if it can reserve `N` item permits before doing work.
If it cannot reserve the full sub-batch, it should reject before work with `RESOURCE_EXHAUSTED` and include a load snapshot when possible.
Partial acceptance should not be the default because it complicates idempotency, item ordering, and fallback accounting.

Each concrete endpoint has an `EndpointCapacity` snapshot with at least:

- current in-flight items/events;
- maximum in-flight items/events;
- optional current/max in-flight batches for backward-compatible observability;
- draining, overloaded, and ejected state;
- freshness/staleness supplied by the caller rather than embedded deeply in wall-clock policy.

For a logical stage backed by multiple pods, available logical capacity is the sum of fresh concrete endpoint capacities.
Assignment still targets concrete pods because cache locality, circuit state, load observations, and shutdown/drain are endpoint-specific.
Within one input batch, the partitioner must maintain local reservations so a stale snapshot cannot assign every item to the same apparently-empty pod.

When capacity is stale or absent, the client should use a conservative effective capacity and rely on stage-side `RESOURCE_EXHAUSTED` rejection as the source of truth.
Fresh capacity can increase throughput across pods; stale capacity must not be treated as permission to overrun a single pod indefinitely.

## Load propagation

Stage pods should attach load snapshots to successful `StageBatchResult` responses and, when possible, to pre-work `RESOURCE_EXHAUSTED` rejections via response metadata/trailers.
The load signal includes current/max in-flight item counts in addition to the existing batch load fields.
The pipeline server records observations per `(stage_id, target, endpoint/pod)` so routing decisions can distinguish a hot pod from a hot logical stage.

Load emitted after a successful sub-batch should ideally be sampled after the item permits for that sub-batch are released, so the next caller sees post-work availability.
A rejection snapshot should describe the pre-work state that caused the rejection.

## Fallback safety

Fallback is safe only when the first candidate did not do stage work or could not have been called:

- pre-call ejection/circuit-open decisions made by the client;
- explicit pre-work admission rejection such as `RESOURCE_EXHAUSTED`;
- other future rejection metadata that proves no item work started.

Ambiguous failures remain conservative, especially for side-effectful stages.
Timeouts, broken connections after a request was accepted, and generic transport errors may occur after repository writes, issue creation, alerting, or limiter updates.
For linking, alerting, and other side-effectful stages, ambiguous timeout should produce retry/error outcomes according to today's semantics rather than fallback to a second pod.
Resolution and grouping can opt into broader behavior only if their stage contracts explicitly remain idempotent and side-effect-free.

Fallback should be applied to the affected sub-batch or item set, not to unrelated items that completed or were assigned elsewhere.

## Streaming result semantics

The public API currently returns one final outcome per input event and the server orders results with `order_event_results` before streaming them.
Existing tests and callers should continue to see deterministic input order unless a later batch explicitly changes that contract and updates tests/Node expectations.

The framework supports incremental execution internally:

- track each item by stable input index and event ID;
- advance items through stages as their sub-batch results arrive;
- emit terminal outcomes into a reorder buffer as soon as they are final;
- allow a stage to declare a barrier when it needs whole-batch context or side-effect ordering;
- flush public results in input order by default, while leaving room for an explicitly unordered mode later.

This lets fast items stop occupying internal stage capacity once they finish, while preserving current public ordering guarantees.

## Cymbal-specific pieces

The reusable framework should not know Cymbal exception semantics.
Keep these in Cymbal crates outside the framework:

- concrete stage IDs such as `resolution:v1`, `grouping:v1`, `linking:v1`, `alerting:v1`, and `rate-limiting:v1`;
- affinity-key extraction from `InputEvent`, `ResolvedEvent`, `GroupedEvent`, `AlertingEvent`, exception properties, debug images, sourcemap/chunk identifiers, releases, and team IDs;
- default policy choices such as affinity-first for resolution/grouping and strict/no-fallback for linking, alerting, and rate limiting;
- side-effect and barrier decisions for issue linking, suppression/assignment, alerting, and limiter state;
- metrics names, logs, env var parsing, tonic status conversion, DNS refresh, and endpoint client reuse.

## Target framework API sketch

The implemented API is close to this shape; names may continue to evolve as more pipelines adopt the framework.

```rust
pub trait RoutingKeyExtractor<Item> {
    fn routing_key(&self, item: &Item) -> RoutingKey;
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum RoutingKey {
    TeamId(i64),
    StageCache { kind: RoutingCacheKeyKind, value: String },
    NoAffinity,
}

#[derive(Clone, Debug)]
pub struct EndpointCapacity<EndpointId> {
    pub endpoint: EndpointId,
    pub current_in_flight_items: u64,
    pub max_in_flight_items: u64,
    pub current_in_flight_batches: Option<u64>,
    pub max_in_flight_batches: Option<u64>,
    pub draining: bool,
    pub overloaded: bool,
    pub ejected: bool,
    pub freshness: CapacityFreshness,
}

#[derive(Clone, Debug)]
pub enum CapacityFreshness {
    Fresh,
    Stale,
    Missing,
}

#[derive(Clone, Debug)]
pub struct CapacitySnapshot<EndpointId> {
    pub endpoints: Vec<EndpointCapacity<EndpointId>>,
}

impl<EndpointId> CapacitySnapshot<EndpointId>
where
    EndpointId: Eq + std::hash::Hash,
{
    pub fn fresh_available_items(&self) -> u64;
    pub fn effective_remaining_for(&self, endpoint: &EndpointId) -> Option<u64>;
}
```

Partitioning should be transport-neutral and preserve original item indices:

```rust
#[derive(Clone, Debug)]
pub struct IndexedItem<Item> {
    pub index: usize,
    pub item: Item,
}

#[derive(Clone, Debug)]
pub struct EndpointSubBatch<EndpointId, Item> {
    pub endpoint: EndpointId,
    pub items: Vec<IndexedItem<Item>>,
}

#[derive(Clone, Debug)]
pub struct UnroutableItem<Item> {
    pub item: IndexedItem<Item>,
    pub reason: UnroutableReason,
    pub candidates_considered: usize,
}

#[derive(Clone, Debug)]
pub struct PartitionedSubBatches<EndpointId, Item> {
    pub sub_batches: Vec<EndpointSubBatch<EndpointId, Item>>,
    pub unroutable: Vec<UnroutableItem<Item>>,
}

pub struct CapacityAwarePartitioner<EndpointId, Policy> {
    pub policy: Policy,
    pub conservative_missing_capacity_items: u64,
    pub strict_affinity_overflow_is_unroutable: bool,
    _endpoint: std::marker::PhantomData<EndpointId>,
}

impl<EndpointId, Policy> CapacityAwarePartitioner<EndpointId, Policy>
where
    EndpointId: Clone + Eq + std::hash::Hash,
{
    pub fn partition<Item, Extractor, Rng>(
        &self,
        stage_id: &str,
        items: Vec<Item>,
        endpoints: &[EndpointId],
        capacity: &CapacitySnapshot<EndpointId>,
        extractor: &Extractor,
        rng: &mut Rng,
    ) -> PartitionedSubBatches<EndpointId, Item>
    where
        Extractor: RoutingKeyExtractor<Item>,
        Rng: rand::Rng + ?Sized;
}
```

Fallback classification should be independent of tonic and map into transport-specific statuses in `cymbal-server`:

```rust
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AttemptFailureKind {
    PreCallEjected,
    PreWorkResourceExhausted,
    PreWorkRejected,
    AmbiguousTimeout,
    AmbiguousTransport,
    RemoteItemErrors,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FallbackDecision {
    TryNextCandidate,
    RetryOriginalItems { retry_after_ms: Option<u64> },
    TerminalError { retryable: bool },
}

pub struct FallbackPolicy {
    pub allow_pre_work_fallback: bool,
    pub allow_ambiguous_fallback: bool,
    pub max_attempts: Option<usize>,
}

impl FallbackPolicy {
    pub fn decide(&self, failure: AttemptFailureKind, attempt_index: usize) -> FallbackDecision;
}
```

Incremental pipeline primitives should separate final outcome order from execution order:

```rust
#[derive(Clone, Debug)]
pub struct PipelineItemState<Item> {
    pub input_index: usize,
    pub event_id: String,
    pub item: Item,
}

#[derive(Clone, Debug)]
pub enum StageProgress<Next, Final> {
    Continue(PipelineItemState<Next>),
    Final { input_index: usize, outcome: Final },
}

pub trait ReorderBuffer<Final> {
    fn push(&mut self, input_index: usize, outcome: Final);
    fn drain_ready_in_order(&mut self) -> Vec<Final>;
    fn drain_any_ready(&mut self) -> Vec<Final>;
}

pub enum StageBarrier {
    PerItem,
    WholeBatch,
    SideEffectOrdered,
}
```

The current implementation keeps public ordered streaming by using input-order draining at the server boundary.
Later work can expose an unordered mode only after public API compatibility is explicitly revisited.
