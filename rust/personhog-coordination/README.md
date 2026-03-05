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

Partitions that need to move go through a three-phase state machine:

```text
Warming --> Ready --> Complete --> (deleted)
```

1. **Warming**: Coordinator creates the handoff. The new owner warms its cache (e.g. consumes from Kafka until caught up), then signals `Ready`.
2. **Ready**: Each router sees the transition, stops sending to the old pod, drains its inflight requests, switches to the new pod, and writes a `RouterCutoverAck`.
3. **Complete**: Once all routers have acked, the coordinator updates the assignment owner and transitions to `Complete`. The old pod releases partition resources. The coordinator then deletes the handoff and acks.

### Cutover (router-driven)

The key insight is that **routers drive the traffic switch**, not pods. Routers control where requests go, so only they can guarantee inflight requests finish before switching.

When a handoff transitions to `Ready`, each router's `RoutingTable` picks up the change via its etcd watch and calls `CutoverHandler::execute_cutover`. The handler is expected to:

1. **Stop routing** new requests for the partition to the old pod
2. **Stash** any new incoming requests for the partition
3. **Drain** inflight requests still in flight to the old pod
4. **Switch** the routing table entry to the new pod
5. **Flush** stashed requests to the new pod

After cutover completes, the router writes a `RouterCutoverAck` to etcd at `handoff_acks/{partition}/{router_name}`. Each router writes its own key, so there's no contention between routers.

The coordinator watches the ack prefix. On each new ack, it counts acks for that partition against the number of registered routers. When all routers have acked, the coordinator atomically updates the assignment owner and transitions the handoff to `Complete`.

The old pod watches handoffs too. When it sees its partition reach `Complete`, it calls `HandoffHandler::release_partition` to clean up: clear the in-memory cache, unassign the Kafka consumer, and free any resources associated with that partition. At this point, no traffic is flowing to the old pod for this partition (all routers already switched), so the release is safe.

Finally, the coordinator deletes the handoff and ack keys from etcd.

## Known limitations

**Overlapping rebalances**: The coordinator does not guard against concurrent rebalances. When multiple pods join in quick succession, each registration triggers a new rebalance that can overwrite in-flight handoffs, causing some partitions to be reassigned without going through the full handoff protocol (no warming, no coordinated cutover). The fix is to either skip rebalance while handoffs are in flight (with re-evaluation on handoff completion) or compute assignments using "effective state" that treats pending handoffs as completed. See the `rapid_pod_joins` integration test for a reproduction.

**Assignment strategies are minimal**: The two bundled strategies (`JumpHashStrategy` and `StickyBalancedStrategy`) are basic implementations meant to exercise the coordination layer. `JumpHashStrategy` is stateless and deterministic but ignores current assignments entirely, causing unnecessary partition movement on every rebalance. `StickyBalancedStrategy` minimizes movement but uses a naive greedy approach without considering locality, rack awareness, or weighted pods. Both are placeholders to be replaced with a production-grade strategy as requirements become clearer.

## Modules

| Module | Responsibility |
| --- | --- |
| `types` | Core data types: `RegisteredPod`, `PartitionAssignment`, `HandoffState`, `RouterCutoverAck`, etc. |
| `store` | `EtcdStore` abstraction: typed CRUD, watches, leases, transactions over etcd. |
| `coordinator` | Leader election, assignment computation, handoff orchestration, ack quorum checking. |
| `pod` | `PodHandle` + `HandoffHandler` trait: pod registration, heartbeat, handoff reactions. |
| `routing_table` | `RoutingTable` + `CutoverHandler` trait: routing map maintenance, cutover execution. |
| `strategy` | `AssignmentStrategy` trait with `JumpHashStrategy` and `StickyBalancedStrategy` implementations. |
| `hash` | Jump consistent hash function. |
| `error` | Error types. |
