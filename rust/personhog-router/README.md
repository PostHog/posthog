### personhog-router context

### Requirements

- defines the API contract for all external personhog clients to consume
- provides a stateless/dependency-less routing path to personhog-replica pods
- participates in the handoff protocol to ensure requests are correctly and efficiently routed to personhog-leader pods
- scales horizontally through k8s
- accepts protobuf requests
- sends protobuf requests to respective BEs

### To Implement

- routers participate in handoff protocol/have vNode ownership awareness
- consistently/correctly/efficiently route requests to personhog-leader pods
- personhog-leader client installed on service to consume personhog-leader API
- define API contract that allows clients to consume strongly consistent/write to person state (consume personhog-leader BE capabilities)

### Implementation Details

#### personhog-replica routing

Routing decisions are made per-request in `src/router/routing.rs` based on two dimensions:
the data category and the consistency level from the request's `ReadOptions`.

Non-person data (hash key overrides, cohort membership, groups, group type mappings)
always routes to personhog-replica regardless of consistency level or operation type.
The replica service handles strong vs eventual consistency internally
by choosing the appropriate Postgres pool.

Person data (person, persondistinctid) checks the `ConsistencyLevel` on the request:

- `EVENTUAL` or unset → routes to personhog-replica
- `STRONG` → returns `UNIMPLEMENTED` (requires personhog-leader)
- Writes → returns `UNIMPLEMENTED` (requires personhog-leader)

#### personhog-leader routing

Person writes and strong reads route to the partition's owning leader pod. The
router holds a per-partition routing table fed by `personhog-coordination`'s
handoff watch — the table flips to the new owner atomically with the handoff
reaching `Complete`.

#### Stash and drain during partition handoffs

Partition handoffs go through `Freezing → Draining → Warming → Complete`
(see `personhog-coordination`'s README for the full protocol). Routers
participate by buffering writes for a partition during the non-terminal
phases and replaying them once the handoff completes:

- **Begin stash** (on `Freezing`, re-asserted on `Draining` and `Warming`):
  the router registers the partition in its `StashTable` and writes a
  `RouterFreezeAck` (only during `Freezing`, when the freeze quorum is
  still being collected). Subsequent writes for that partition are
  parked on a `oneshot` instead of being forwarded.

- **Drain** (on `Complete`): the router replays the parked writes to the
  new owner via `LeaderBackend::update_person_properties_no_stash`,
  bypassing the stash hook so each replayed request actually reaches
  the leader. New requests that arrive during drain land on the same
  queue and are picked up by the next loop iteration — drain only
  evicts the partition from the stash table when it observes the queue
  empty under the lock, preserving FIFO ordering across the cutover.

Two policies layer on the raw mechanism:

1. **Per-request deadline** (`STASH_MAX_WAIT_MS`, default 10 s): if a
   stashed request waits longer than this, drain returns `UNAVAILABLE`
   to the original caller without forwarding. This caps client-perceived
   latency during long drains and gives clients a definitive retryable
   error code instead of an ambiguous gRPC timeout.

2. **Per-key concurrent forwarding** (`STASH_DRAIN_CONCURRENCY`,
   default 32): each drain batch is grouped by `(team_id, person_id)`
   and forwarded with up to that many keys in parallel. Within a key
   the requests forward sequentially to preserve per-key ordering at
   the leader; across keys the drain fans out to shrink wall-clock
   drain duration.

Bounds are configurable per partition (`STASH_MAX_MESSAGES_PER_PARTITION`,
`STASH_MAX_BYTES_PER_PARTITION`); requests that would exceed either bound
are rejected with `UNAVAILABLE` so callers retry rather than the router
silently dropping writes.
