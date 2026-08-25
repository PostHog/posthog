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

Every leader forward is a single classified attempt
(`LeaderBackend::forward_classified` — the one shared reading of leader
responses): a response the leader produced is *delivered* (success or error,
it's a real outcome, and an error like `UNAVAILABLE` is also the leader's
backpressure signal), while a fence rejection (`FAILED_PRECONDITION` — always
a routing race, never a client error), an unroutable partition (no assignment
or address known yet — nothing sent), or a transport failure *bounces* with no
outcome. There is no blind inner retry layer; retry policy lives in exactly
two places, both of which re-check routing state between attempts:

- **Direct path** (`forward_or_stash`): a bounced request is held in its handler
  task and the loop re-enters from the stash check after a short backoff — so
  by the re-attempt it parks if a handoff opened a stash window, re-resolves
  if the table flipped, or re-sends if nothing changed. Each re-attempt is
  counted by `personhog_router_forward_retries_total` under the reason that
  caused it. After a few consecutive bounces it fails with a definitive
  `UNAVAILABLE`, counted by `personhog_router_forward_retries_exhausted_total`
  (a router with a dead watch must not hold requests forever — the client's
  own retry can reach a healthier router). A transport bounce marks the
  request possibly-applied; any further forward of it is an at-least-once
  replay, covered by the redelivery contract in `personhog-leader`'s README.
  Clients never see `FAILED_PRECONDITION` from the leader path.
- **Stash path**: the drain's wave loop described below, with put-back for position
  and the reconcile pass as its outer driver.

#### Stash and drain during partition handoffs

Partition handoffs go through `Freezing → Draining → Warming → Complete`
(see `personhog-coordination`'s README for the full protocol). Routers
participate by buffering writes for a partition during the non-terminal
phases and replaying them once the handoff completes:

- **Begin stash** (on `Freezing`, re-asserted on `Draining` and `Warming`):
  the router registers the partition in its `StashTable` and writes a
  `RouterFreezeAck` (only during `Freezing`, when the freeze quorum is
  still being collected). Subsequent writes for that partition are
  parked on a `oneshot` instead of being forwarded. Observing a
  non-terminal phase also pauses any drain still running for the
  partition from a previous ownership era: the drain puts what it had
  taken back and exits, so parked requests wait for whatever owner the
  next `Complete` names rather than draining toward a stale target.

- **Drain** (on `Complete` — including the reaffirm-Complete a
  cancellation resolves to): the router replays each parked request to
  the method it arrived on via the raw forward path, bypassing the
  stash hook so each replayed request actually reaches the leader.
  Each partition's stash is a per-key deferral queue (the shared
  `keyed-stash` crate) keyed by `(team_id, person_id)`: entries are
  seq-stamped at admission and leave only through a definitive outcome
  delivered to their client; an attempt that cannot finish puts its
  entries back at their sequence positions, so a retry can never be
  overtaken by newer same-key work. New requests that arrive during
  drain land on the same queue and are picked up by a later take — the
  drain only evicts the partition from the stash table when it
  observes the queue fully settled (no queued and no in-attempt
  entries) under the lock, preserving per-key admission order across
  the cutover. Drains run off the coordination watch loop in
  per-partition lanes: a drain's duration is data-plane work and must
  never gate freeze acks or routing updates for other partitions. A
  drain toward a different target supersedes the one in flight — the
  old drain puts its in-flight entries back and stops, leaving the
  full backlog parked in order for its successor — while a request
  toward the same target is absorbed by the running drain. Handoff
  deletion events trigger nothing: cancellation is a record
  replacement, so a deletion only ever means post-Complete cleanup.
  The periodic reconcile pass re-derives stash, table, and drain state
  from a fresh snapshot, draining any stash whose partition has no
  handoff to the assignment owner.

Every stashed request therefore ends in exactly one of two ways: a
definitive outcome delivered to its client, or a put-back that re-parks
it for a later attempt — a drain attempt failing to finish is never a
client-visible error. The policies layered on the mechanism:

1. **Per-request deadline** (`STASH_MAX_WAIT_MS`, default 10 s): if a
   stashed request waits longer than this, drain returns `UNAVAILABLE`
   to the original caller without forwarding. This caps client-perceived
   latency during long drains and gives clients a definitive retryable
   error code instead of an ambiguous gRPC timeout. This deadline is
   the only client-visible latency bound; pauses, bounces, and
   supersessions below never surface to callers.

2. **Per-key concurrent forwarding** (`STASH_DRAIN_CONCURRENCY`,
   default 32): each drain wave takes up to that many keys' front runs
   and forwards them in parallel. Within a key the requests forward
   sequentially to preserve per-key ordering at the leader; across
   keys the drain fans out to shrink wall-clock drain duration.

3. **Bounce and retry**: a classified attempt that concludes no outcome
   exists — a `FAILED_PRECONDITION` (the drain raced the target's write
   fence: the owner resuming after a reaffirm, or the new owner's
   cutover), an unroutable target, or a transport failure (a pod
   mid-restart or briefly unreachable) — puts the bounced request and
   the rest of its key run back (the interrupted attempt counts toward
   `personhog_router_forward_retries_total` as a stash-path retry under
   the reason that cut it short; the never-attempted tail goes back
   uncounted), backs off briefly, and retries; after a few consecutive
   bounced waves the drain yields its lane and the reconcile pass
   re-requests it on the next tick. Clients never see a
   bounce — their requests stay parked until the condition clears or
   the per-request deadline expires. A transport bounce marks the
   request possibly-applied: re-forwarding it is an at-least-once
   replay, counted by `personhog_router_stash_replayed_total` and
   covered by the redelivery contract in `personhog-leader`'s README
   (clients retrying `UNAVAILABLE` already impose the same
   requirement).

4. **Cooperative cancellation**: a paused or superseded drain stops at
   the next request boundary and puts everything it took back, in
   order, for the successor drain. Cancellation is a routing decision,
   not a request outcome — it is invisible to clients.

Bounds are configurable per partition (`STASH_MAX_MESSAGES_PER_PARTITION`,
`STASH_MAX_BYTES_PER_PARTITION`); requests that would exceed either bound
are rejected with `UNAVAILABLE` so callers retry rather than the router
silently dropping writes.
