# personhog-coordination

Etcd-based coordination primitives for dynamically assigning Kafka partitions to PersonHog writer pods and orchestrating zero-downtime handoffs when pods join or leave.

## Why this crate exists

PersonHog processes person data sharded across Kafka partitions. Each partition must be owned by exactly one writer pod at a time (single-writer invariant). When pods scale up, scale down, or crash, partitions need to move between pods without losing inflight requests.

This crate provides the coordination layer: a coordinator assigns partitions to pods, and when assignments change, it orchestrates a handoff protocol that moves traffic through routers without dropping requests.

## Why etcd

Etcd gives us the building blocks we need without rolling our own consensus:

- **Leases** for failure detection: pod keys auto-delete when a pod crashes, triggering reassignment
- **Watches** for reactivity: components react to state changes instead of polling
- **Transactions (CAS)** for leader election: only one coordinator runs at a time
- **Strong consistency**: all participants see the same state

## Components

| Component | Crate | Role |
| --- | --- | --- |
| **Coordinator** | `personhog-coordination` | Leader-elected singleton. Watches pods, computes partition assignments, orchestrates handoffs. |
| **Writer pod** | `personhog-leader` | Owns partitions, processes person data. Registers with etcd, responds to handoff events (warm cache, release partition). |
| **Router** | `personhog-router` | Routes requests to the correct writer pod. Maintains a local routing table from etcd watches. Executes traffic cutover during handoffs. |
| **etcd** | (external) | Source of truth for pod registrations, partition assignments, and handoff state. |

## How it works

### Registration

Each writer pod and router registers in etcd with a lease-backed key. If a pod crashes, the lease expires, the key is deleted, and the coordinator reacts.

### Assignment

When the set of active pods changes, the coordinator computes a new partition-to-pod mapping using a pluggable `AssignmentStrategy` (jump consistent hash or sticky balanced). It diffs the result against current assignments to determine which partitions need to move.

### Handoff

Partitions that need to move go through a four-phase state machine. The protocol is designed so that no acknowledged write is ever lost across a cutover, even though four independent components (coordinator, old owner, new owner, routers) participate.

```text
Freezing --> Draining --> Warming --> Complete --> (deleted)
```

1. **Freezing**: Coordinator creates the handoff. Routers begin buffering ("stashing") incoming writes for the partition and write a `RouterFreezeAck`. The old owner does *not* yet drain — it continues serving until every router has acked, because while a single router still forwards traffic to the old owner the inflight count cannot meaningfully be observed as zero. Once every registered router has acked, the coordinator advances to `Draining` via a versioned compare-and-swap.

2. **Draining**: No router can forward new requests to the old owner anymore (every router is stashing). The old owner waits for its inflight request handlers to complete, then writes a `PodDrainedAck`. Because the leader's produce path awaits the Kafka delivery future before returning success, "no inflight" implies "every write this pod ever acked is durable in Kafka." When the ack arrives (or the old owner is no longer registered), the coordinator advances to `Warming`.

3. **Warming**: Kafka high-water mark for the partition is now stable — no producer can append. The new owner consumes the changelog from the writer's last committed offset up to the current HWM, populating its cache, then writes a `PodWarmedAck`. The coordinator atomically writes both `phase=Complete` and the new `PartitionAssignment` in a single etcd transaction.

4. **Complete**: Routers observe the handoff completion, drain their stashed writes to the new owner, and resume routing through the standard table lookup (which now points at the new owner). The old owner observes Complete and releases its partition cache. The coordinator deletes the handoff and ack keys.

The handoff record carries `old_owner: Option<String>`. `None` denotes an initial assignment with no prior owner — there's nothing to drain, so the protocol short-circuits and skips `Draining` entirely, advancing `Freezing → Warming` once router quorum is met.

#### Why the Freezing/Draining split matters

If a single phase served both purposes (router stash *and* old-owner drain in parallel), a slow router could send a final write to the old owner *after* the old owner observed inflight=0 momentarily and wrote `DrainedAck`. The coordinator would then advance to Warming based on a stale ack. The old owner would still process that final write, advancing Kafka HWM past the point warming snapshots, and the new owner's cache would be missing the record — silently stale. Sequencing the phases ensures "no inflight" actually means "no producer can append more."

### Recovery

Several failure modes are handled explicitly:

- **Dead `new_owner`**: If the new owner's etcd registration disappears (lease expired, deregistered) before it can ack warming, `cleanup_stale_handoffs` deletes the handoff. A subsequent rebalance picks a fresh new owner.
- **Dead `old_owner` before drain**: A Freezing handoff whose `old_owner` is no longer registered is also cleaned up. A dead pod can no longer produce writes, so the drain requirement is moot — but only if its etcd key is genuinely absent. A `Draining` pod is still alive and is required to write its `DrainedAck` before the handoff advances.
- **Handoff deleted mid-flight**: When routers see a handoff key disappear (cleanup, ops intervention), they drain their stash back to whoever the routing table currently points at. The protocol never reached `Complete`, so the unchanged owner is the right target.
- **Coordinator restart**: On startup, the coordinator runs `reconcile_pending_handoffs`. For every existing handoff it applies cleanup if `Complete`, otherwise calls `check_phase_advance` to nudge the state machine. This handles the case where acks were written before the coordinator was up — the ack-watch only fires on Put events, so without reconcile those acks would be invisible.

### Concurrency and atomicity

- All phase advancement uses `cas_handoff_phase`, a version-CAS on the handoff key. Two watchers racing to advance the same handoff cannot both succeed; the loser observes `false` and leaves the work to the Put event from the winner.
- Advancing to `Complete` uses an atomic etcd transaction that writes both `phase=Complete` and the new `PartitionAssignment` together. Routers can never observe a torn state where the phase has advanced but the assignment hasn't (or vice versa).
- Routing changes flow exclusively through handoff `Complete` events. There is no separate assignment watch — anything that mutates `assignments/{partition}` outside the handoff protocol is invisible to routers by design.

## Known limitations

**Assignment strategies are minimal**: The two bundled strategies (`JumpHashStrategy` and `StickyBalancedStrategy`) are basic implementations meant to exercise the coordination layer. `JumpHashStrategy` is stateless and deterministic but ignores current assignments entirely, causing unnecessary partition movement on every rebalance. `StickyBalancedStrategy` minimizes movement but uses a naive greedy approach without considering locality, rack awareness, or weighted pods. Both are placeholders to be replaced with a production-grade strategy as requirements become clearer.

**Watch reconnects don't replay missed events**: If the routing table loses its etcd watch and the underlying client reconnects, any handoff Put/Delete events that fired during the disconnect are lost. The routing table relies on the etcd_client's reconnect logic and does not periodically reconcile, so a long disconnect could leave the routing map stale until something forces a re-read. This hasn't bitten us in practice but is worth knowing.

## Modules

| Module | Responsibility |
| --- | --- |
| `types` | Core data types: `RegisteredPod`, `PartitionAssignment`, `HandoffState`, `RouterFreezeAck`, `PodDrainedAck`, `PodWarmedAck`, etc. |
| `store` | `EtcdStore` abstraction: typed CRUD, watches, leases, and transactions over etcd. Hosts `cas_handoff_phase` and `complete_handoff` (the atomic phase + assignment txn). |
| `coordinator` | Leader election, assignment computation, handoff orchestration, ack quorum checking, reconcile-on-startup, stale-handoff cleanup. |
| `pod` | `PodHandle` + `HandoffHandler` trait: pod registration, heartbeat, and the drain/warm/release responses to handoff phases. |
| `routing_table` | `RoutingTable` + `StashHandler` trait: routing map maintenance and the begin-stash / drain-stash phase responses. |
| `strategy` | `AssignmentStrategy` trait with `JumpHashStrategy` and `StickyBalancedStrategy` implementations. |
| `hash` | Jump consistent hash function. |
| `error` | Error types. |
