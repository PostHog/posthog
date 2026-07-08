# personhog-stateright

Formal verification of the personhog partition handoff protocol using
[Stateright](https://github.com/stateright/stateright), an exhaustive
model checker for distributed systems.

An earlier incarnation of this crate modeled the pre-2026 three-phase
protocol, found its split-brain window, and recommended the
stash-and-release design that evolved into today's production protocol.
This version models the shipped protocol — the four-phase handoff with
identity freeze quorum, ack-to-handoff correlation, and desired-state
pod convergence — and uses the checker to (a) verify the shipped
invariants under every failure interleaving at model scale, (b)
characterize the one accepted residual precisely, and (c) validate the
epoch-fencing design that closes it, before it is built.

## How it works

The entire distributed system — etcd contents, each pod's process
memory, each router's table and stash, the Kafka changelog — is one
plain-data `SystemState`. Every actor behavior and every failure is an
`Action`. The checker explores every reachable state under every
possible interleaving of actions (BFS with state deduplication),
checking every property at every state. A violated safety property
yields the minimal counterexample trace, browsable step by step in a
web explorer.

Configurations are deliberately small — state spaces grow
combinatorially, and protocol bugs are structural, showing up at
minimum viable scale or not at all. Measured sizes (release mode):

| Configuration (writes=2, reads=1) | Unique states | Wall time |
|---|---|---|
| 2 pods / 2 routers / 1 partition, 1 failure | ~26k | 0.2s |
| 2 pods / 2 routers / 1 partition, 2 failures | ~230k | 1.4s |
| 2 pods / 2 routers / 2 partitions, 1 failure | ~900k | 9s |
| 2 pods / 2 routers / 2 partitions, 2 failures | ~8.9M | 110s |
| 3 pods / 2 routers / 2 partitions, 2 failures | ~24M | 300s |

The default test tier (nine scenarios, ~8s total in release) runs the
1-partition matrix — including the rejoin and read-path scenarios —
plus the 2-partition single-failure case. The `--ignored` extended tier
runs the 2-partition double-zombie scenarios and the state-space
report. Two partitions matter for the coordinator's cross-partition
scheduling (rebalancing defers while any handoff is in flight); the
safety invariants themselves are per-partition, which is why every
violation class reproduces at one.

## Coupling to production (drift prevention)

The protocol's *decision logic* is single-sourced: the model calls the
same functions the coordinator and pods execute, on production-typed
views of the checker state. A change to any of these changes what the
checker verifies, automatically:

| Shared (called directly, cannot drift) | Where it lives |
|---|---|
| `pod::desired_state` + `DesiredState` | the pod's entire state machine — `Action::Converge` derives through the real function |
| `protocol::freeze_quorum_met` / `drain_satisfied` / `warm_satisfied` | the phase-advancement rules (identity quorum, id-correlated acks, vacuous drain) — `Action::AdvancePhase` calls them |
| `StickyBalancedStrategy::compute_assignments` | partition placement — `Action::CoordinatorReconcile` calls it |
| `types::HandoffPhase` | used directly as the model's phase enum, so adding a phase breaks the model's exhaustive matches at compile time |

What remains model-side is the *environment and effect application* —
what warming does to a cache, what leases and zombies mean, how stashes
queue — mapped to named production behavior for review:

| Model | Production behavior modeled |
|---|---|
| `Action::CoordinatorReconcile` cleanup arm | `cleanup_stale_handoffs` (mod_revision-guarded delete, modeled as atomic check-and-delete) |
| `Action::AdvancePhase` Warming→Complete | `complete_handoff` (phase write + assignment flip as one txn) |
| `Action::Converge` effect application | `PodHandle::apply` (warm installs at HWM and unfences, drain fences, acks echo the handoff id and are phase-gated) |
| `Action::Observe` | Router watch handlers: `begin_stash` + FreezeAck (Freezing only), cutover + stash drain at Complete, drain-back on cancellation |
| `Action::ClientWrite` | The raw proxy leader path: stash if stashing, else forward to the table entry; leader admission = warmed + unfenced (`try_begin`) |
| `Action::CrashRestartWithinTtl` | Process death + same-name restart before lease expiry: registration and assignments survive, memory wiped |
| `Action::LeaseExpire` / `SelfFence` | Lease loss with the bounded zombie window before the keepalive self-fences (fix 1); same pair for routers, where lease loss also drops them from the freeze quorum |
| `Changelog.epoch` under `Variant::EpochFenced` | Kafka transactional-producer fencing: warming = `init_transactions`, bumping the broker epoch; stale-epoch produces are rejected before any client ack |

Full elimination of the second table would mean deterministic
simulation — a trait seam over `PersonhogStore` with an in-memory
implementation so the model executes `converge` and
`check_phase_advance` themselves. Held as a possible later investment.

## Properties

| Property | Meaning |
|---|---|
| `no_lost_acked_write` (safety) | No write is acked by a pod after a different designated owner has warmed — i.e. no acked write ever sits beyond the warm HWM of the pod that will serve |
| `no_split_write_acceptance` (safety) | No two pods are simultaneously capable of accepting writes for one partition **and** each reachable via a live, non-stashing router — the real split-brain condition |
| `drained_ack_is_final` (safety) | A pod that wrote a DrainedAck for the current handoff attempt cannot accept another write in that incarnation |
| `some_handoff_completes`, `some_write_accepted` (sanity) | The interesting states are actually reachable |
| `converges_to_stable` (liveness) | Every full run ends quiescent: no handoffs, every partition served warm and unfenced by its sticky target, all live routers agreeing, no stashed traffic |

## Results

| Scenario | `no_lost_acked_write` | `no_split_write_acceptance` | `strong_reads_complete` |
|---|---|---|---|
| Current protocol, no failures | holds | holds | holds |
| Current, crash-restart within TTL / clean lease expiry | holds | holds | holds |
| Current, pod death past TTL + rejoin | holds | holds | holds |
| Current, single zombie pod | **holds** | **holds** | holds |
| Current, double zombie (router + pod) | **violated** — counterexample found | **violated** | — |
| Epoch-fenced, double zombie | holds | holds | holds |
| Current, strong reads + one failure | holds | holds | holds |

Two results worth calling out:

**A single zombie pod is provably safe.** The manual protocol review
treated any zombie pod as the residual risk; the checker refused to
find a counterexample, and the reason is structural: the identity
freeze quorum means every registered router is stashing before the
drain begins, so no live router can route to the zombie after the new
owner warms — and anything the zombie accepts *before* the warm sits
below the warm HWM and is captured. The checker sharpened the
documented residual from "a zombie pod" to "a zombie router feeding a
zombie pod, simultaneously."

**Epoch fencing closes the double zombie.** Under the `EpochFenced`
variant, warming bumps the broker's producer epoch, and the zombie's
produce is rejected before any client ack. This is the design
validation gating the transactional-producer implementation.

**Read stashing was machine-validated before it shipped.** A
direct-read variant of this model (strong reads forwarding to the table
entry even mid-handoff, the pre-#69456 behavior) produced the cutover
race as a counterexample: a slow router serving a strong read from the
old owner's frozen cache after a fast router already delivered writes
to the new owner. With reads parking in the same per-key FIFO as writes
— the shipped design — every property holds under the identical failure
budget. The variant was removed once the change merged, so the model
tracks only the shipped protocol; `strong_reads_complete` remains
checked in every scenario as the standing guarantee.

## Usage

```sh
# Default tier — exhaustive checks with expected verdicts per scenario:
cargo test -p personhog-stateright --release

# Extended tier (2-partition double-zombie, ~20s) + state-space report:
cargo test -p personhog-stateright --release -- --ignored --nocapture

# Interactive state-space explorer (http://localhost:3000), for
# stepping through the double-zombie counterexample trace:
cargo run -p personhog-stateright --release -- current-zombie
```

Explorer variants: `current` (failures without zombie windows),
`current-zombie` (the residual, with counterexamples), `epoch-fenced`
(the fix).

## Coverage notes

Now in the explored space: pod rejoin after TTL expiry; coordinator
concurrency (cleanup, rebalance, phase advance, and completion cleanup
are independently scheduled actions, which also covers an overlapping
outgoing coordinator — every coordinator write is a guarded
check-on-current-state, so two coordinators are just more interleavings
of the same actions); strong reads (stashing with writes, per the shipped design); two
routers draining stashed FIFOs concurrently at cutover (thaw ordering);
multi-partition rebalance gating.

Known remaining abstractions: warming is instant and atomic (production
streams from Kafka with retries — availability, not safety); stash
deadlines/bounds are not modeled (availability policies); the
mod_revision cleanup guard is encoded as atomic check-and-delete rather
than itself verified (an unguarded-cleanup variant could demonstrate
its necessity). Full elimination of the environment layer would mean
deterministic simulation behind a `PersonhogStore` trait seam — held as
a later investment.
