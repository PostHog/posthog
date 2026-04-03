# personhog-stateright

Formal verification of the PersonHog partition handoff protocol using [Stateright](https://github.com/stateright/stateright), an exhaustive model checker for distributed systems.

## Why this exists

PersonHog shards person data across Kafka partitions. Each partition must be owned by exactly one writer pod at a time (single-writer invariant). When pods scale up or down, partitions move between pods through a handoff protocol coordinated via etcd.

The production handoff protocol (`personhog-coordination`) has a **split brain bug**: during a handoff, both the old and new pods believe they own the partition simultaneously. This window exists between the `Ready` phase (when the new pod takes ownership) and `Complete` phase (when the old pod releases it). If two routers send writes to different pods during this window, both pods accept them, leading to divergent state.

This crate models the handoff protocol as a finite state machine and uses Stateright to exhaustively explore every possible interleaving of actions (pod joins, crashes, router cutovers, client writes) to prove whether safety invariants hold or find counterexamples.

## The split brain problem

The current handoff protocol has three phases:

```text
Warming --> Ready --> Complete --> (deleted)
```

1. **Warming**: New pod warms its cache. It also adds the partition to its `owned_partitions` set and signals Ready.
2. **Ready**: Routers execute cutover (switch routing from old to new pod) and write acks.
3. **Complete**: Once all routers acked, coordinator updates the assignment. Old pod releases ownership.

The problem: at step 1, the new pod takes ownership *before* the old pod releases it. Between Ready and Complete, **both pods own the partition**. With multiple routers cutting over at different times, one router may still route to the old pod while another routes to the new pod, causing both to accept writes for the same partition.

```text
Timeline:
  Warming ──────> Ready ──────────────────> Complete
                    │                           │
  New pod takes ────┘                           └── Old pod releases
  ownership here           ↑ SPLIT BRAIN ↑           ownership here
                     Both pods own the partition
```

## Protocol variants

The model explores three protocol variants to compare their safety properties:

### Current (production code)

The protocol as implemented today. The new pod takes ownership during Warming, before Ready is signaled. The old pod only releases at Complete.

**Result**: Fails `single_pod_ownership` and `no_split_writes`.

### EarlyRelease

The old pod releases ownership *before* Ready is signaled. This eliminates the split brain window since at most one pod owns the partition at any time.

**Result**: Fixes split brain, but fails `writes_only_to_owners`. Routers with stale routing tables send requests to the old pod after it has released ownership, causing rejected requests.

### StashAndRelease (recommended)

Adds a `Stashed` phase between Ready and Complete. The sequence:

```text
Warming --> Ready --> Stashed --> Complete --> (deleted)
```

1. **Warming**: New pod warms cache, signals Ready. Does NOT take ownership yet.
2. **Ready**: Each router begins stashing (buffering) requests for the partition and writes an ack.
3. **Stashed**: All routers confirmed stashing. No traffic flows to either pod. Old pod releases ownership, new pod takes it.
4. **Complete**: Coordinator updates assignment. Routers flush stashed requests to the new pod and switch routing.

This eliminates both split brain (ownership transfers while no traffic flows) and rejected requests (routers buffer instead of routing to a non-owner).

**Result**: Passes all safety invariants including `no_split_writes`, `writes_only_to_owners`, and `single_pod_ownership`.

## Invariants checked

| Invariant | Description |
|-----------|-------------|
| `no_split_writes` | For every partition, at most one pod is serving accepted writes at any time |
| `writes_only_to_owners` | Every attempted write targets a pod that owns the partition (no stale routing) |
| `single_pod_ownership` | At most one pod has any given partition in its owned set |
| `no_orphaned_partitions` | Every partition is either assigned to a live pod or in a handoff |
| `valid_handoff_state` | Handoff states are internally consistent (phase/release ordering) |
| `router_agreement_when_stable` | When no handoffs are in flight, all routers agree with etcd assignments |
| `no_write_to_unregistered_pod` | Accepted writes never target a crashed/unregistered pod |
| `assignment_ownership_agreement` | If a partition is assigned and not in handoff, the assigned pod has it in its owned set |
| `handoff_consistent_with_assignment` | Active handoffs are consistent with etcd assignment state |
| `draining_pod_gains_no_partitions` | A draining pod is never the target of a new handoff |
| `converges_to_stable` | The system eventually reaches a state with no pending handoffs |

## Results summary

Without crashes (2 partitions, 2 pods, 2 routers):

| Invariant | Current | EarlyRelease | StashAndRelease |
|-----------|---------|-------------|-----------------|
| `no_split_writes` | FAIL | PASS | PASS |
| `writes_only_to_owners` | FAIL | FAIL | PASS |
| `single_pod_ownership` | FAIL | PASS | PASS |
| `router_agreement_when_stable` | PASS | PASS | PASS |
| `no_orphaned_partitions` | PASS | PASS | PASS |
| `converges_to_stable` | PASS | PASS | PASS |

`draining_pod_gains_no_partitions` fails for all protocols because the coordinator doesn't guard against assigning partitions to a pod that starts draining after the rebalance computation. This is a pre-existing issue unrelated to the handoff protocol.

## Usage

### Run the interactive explorer

```sh
cargo run -p personhog-stateright -- <variant>
```

Where `<variant>` is one of:

- `current` - model the current protocol (shows split brain counterexamples)
- `early-release` - model the early release fix
- `stash` - model the stash-and-release fix (recommended)

This launches the Stateright web explorer at `http://localhost:3000`, where you can:

- Browse the state space graph
- Click on counterexample traces to step through invariant violations
- Inspect system state at each step (pod ownership, router tables, handoff phases)

### Run the tests

```sh
cargo test -p personhog-stateright
```

The test suite runs 16 scenarios covering each protocol variant across different cluster sizes, router counts, and crash configurations. The `protocol_comparison_summary` test prints a side-by-side comparison table.

To see the comparison table output:

```sh
cargo test -p personhog-stateright -- protocol_comparison_summary --nocapture
```

## Architecture

The model is structured as:

| Module | Purpose |
|--------|---------|
| `types` | State types: `SystemState`, `Action`, `HandoffPhase`, `ProtocolVariant`, etc. |
| `model` | Stateright `Model` implementation: initial states, action generation, state transitions, invariant checks |
| `assignment` | Jump consistent hash for deterministic partition-to-pod assignment |
| `main` | CLI entry point for the Stateright web explorer |

### How the model works

The model represents the full distributed system as a single `SystemState` struct containing:

- **etcd state**: registered pods, partition assignments, active handoffs, router acks
- **Pod local state**: what each pod believes it owns (`pod_owned`)
- **Router local state**: each router's routing table and stashing status
- **Write tracking**: accepted and attempted writes for invariant checking

Stateright exhaustively explores every possible interleaving of `Action`s (pod joins, crashes, drains, coordinator rebalances, pod handoff steps, router cutovers, client writes) using BFS, checking all invariants at every reachable state.

### Relationship to production code

This model mirrors the production `personhog-coordination` crate but is intentionally simplified:

- No async, no network, no etcd. Pure deterministic state machine.
- Actions are atomic (no partial failures within a single action).
- All protocol variants share the same state type, differing only in action generation and transition logic.

The types and phases in this model map directly to their production counterparts in `personhog-coordination::types`.
