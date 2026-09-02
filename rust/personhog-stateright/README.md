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
minimum viable scale or not at all.
The suite explores ~24M states across 31 runs.
Its long pole is the two-partition epoch-fenced double zombie, which is more than half the wall clock on its own:

| Scenario | Unique states | Wall time |
|---|---|---|
| `epoch_fenced_two_partitions_double_zombie_is_safe` | 13.1M | 19s |
| `two_partitions_double_zombie_loses_acked_writes` | 3.7M | 4.0s |
| `cancellation_with_live_owner_reaffirms_and_resumes` | 2.6M | 3.9s |
| `current_two_partitions_single_zombie_is_safe` | 0.9M | 1.4s |
| `probe_dual_role_pod_is_reachable_and_safe` | 0.7M | 1.2s |
| *everything else (26 runs)* | 3.4M | 4s |

Roughly: a second partition costs ~20x, a second failure in the budget ~10x, a third pod ~2x.
Times are release mode, one scenario at a time on 14 cores — a CI runner with 4 slower cores is several times that, so treat them as ratios rather than absolutes.

The test suite (twenty-odd scenarios; the heavy double-zombie pair dominates the runtime) runs the full
verdict matrix — the 1-partition scenarios, the 2-partition cases
including both double-zombie verdicts, the 3-pod rejoin, and the
reachability probes. Two partitions matter for the coordinator's
cross-partition scheduling (rebalancing defers while any handoff is in
flight); the safety invariants themselves are per-partition, which is
why every violation class reproduces at one.

### Judging a state-space change

`STATERIGHT_REPORT=1` reports every scenario's explored size (see Usage), and those counts are the review gate for any change to how `SystemState` is encoded.
Two kinds of change, two different expectations:

- A change meant to cost nothing — skipping work, reordering guards, avoiding a clone — must leave every scenario's `unique` and `generated` **identical**.
  A moved count means the transition relation changed, which was not the intent.
- A deliberate collapse — dropping a field no guard or property reads back — must **shrink** `unique` while every verdict in `tests/model_tests.rs` stays as it was.
  Each one needs an argument in its commit message for why forgetting that information is a bisimulation, because a collapse that is wrong does not fail loudly: it quietly stops exploring states where a bug could live.

Three kinds of field are worth suspecting when a configuration is too slow, all of them found by asking "who reads this, and when":

- **A history counter.** It only ever grows, and nothing reads its magnitude, so every count reached roots its own copy of the subtree beneath it. Replace it with whatever the logic actually consumes — a flag, a sum, an owner id.
- **A value only ever read through a function of it.** Two fields compared only via their sum, or only for equality, cost more than the one number or one identity that decides the outcome.
- **Evidence for a probe that some configurations cannot reach.** A `sometimes` probe guarded to be vacuous outside its own scenario must not have its flag recorded elsewhere: nothing will look at it, and a sticky flag doubles its subtree. Gate the write on the same predicate the probe reads, so the two cannot drift.

Note which way each mistake fails. Recording too little makes a `sometimes` probe find no discovery and `assert_properties` panic — loud. Dropping something a safety property needed is silent, which is why the argument matters more than the measurement.

### Runs that stop early

A run that only asserts a counterexample *exists* does not need the rest of the space, so those call `explore_until` with the discoveries they assert and stop there.
Everything asserting that a property *holds* still explores exhaustively — an `always` property is only proven by exhaustion, and stateright's default stopping condition never fires on these models anyway, since a safety property that holds never produces a discovery to stop on.

The rule for touching one of these tests: adding an assertion that a discovery is *absent* means moving that run back to `explore`.
The early exit makes the run prove less, not less well.

### How the threads are divided

Every checker explores with as many threads as the machine has, and `.config/nextest.toml` reserves the whole thread budget for the one scenario big enough to want it (`epoch_fenced_two_partitions_double_zombie_is_safe`) so it does not contend with the rest of the suite mid-explore.

Two things worth knowing before tuning this.
BFS parallelizes poorly here — 14 checker threads buy under a 3x speedup — so a checker asking for every core does not get every core's worth of work done.
And a single-threaded BFS reports the *shortest* path to each discovery, which makes a failure far easier to read, so there is a real argument for exploring the small scenarios on one thread and letting nextest supply the parallelism instead.

That argument has not been measured on a CI-sized machine, and it is not measurable on a large one: reducing nextest's lane count on a 14-core laptop just idles cores rather than emulating a 4-core runner.
Reserving judgement until it can be measured where it matters.

`generated / unique` is the duplicate-successor ratio, and `depth` is a racing maximum across checker threads, so it varies run to run and means nothing on its own.
Wall times move by up to 10% between runs of the same binary, so judge a change by its state counts and treat a timing difference under that as no difference.

Only the exhaustive runs have stable counts.
A run that stops at its counterexample (see below) reports how far it happened to get, which depends on thread count and scheduling, so its numbers are informational and not a gate.

## Coupling to production (drift prevention)

The protocol's *decision logic* is single-sourced: the model calls the
same functions the coordinator and pods execute, on production-typed
views of the checker state. A change to any of these changes what the
checker verifies, automatically:

| Shared (called directly, cannot drift) | Where it lives |
|---|---|
| `pod::desired_state` + `DesiredState` | the pod's entire state machine — `Action::Converge` derives through the real function |
| `protocol::freeze_quorum_met` / `drain_satisfied` / `warm_satisfied` | the phase-advancement rules (identity quorum, id-correlated acks, vacuous drain) — `Action::AdvancePhase` calls them |
| `protocol::plan_partial_rebalance` | the rebalance decision (placement via `StickyBalancedStrategy` + the move/fresh diff, old_owner from the current assignment, in-flight partitions pinned) — `Action::Rebalance` calls it, as does the coordinator |
| `types::HandoffPhase` | used directly as the model's phase enum, so adding a phase breaks the model's exhaustive matches at compile time |

What remains model-side is the *environment and effect application* —
what warming does to a cache, what leases and zombies mean, how stashes
queue — mapped to named production behavior for review:

| Model | Production behavior modeled |
|---|---|
| `Action::CancelDeadNewOwner` / `Action::Cancel` / `Action::CleanupComplete` | the planner's cancellation-by-replacement and mod_revision-guarded Complete cleanup, modeled as atomic check-and-swap / check-and-delete |
| `Action::AdvancePhase` Warming→Complete | `complete_handoff` (phase write + assignment flip as one txn) |
| `Action::Converge` effect application | `PodHandle::apply` (warm installs at HWM and unfences, drain fences, acks echo the handoff id and are phase-gated) |
| `Action::Observe` | Router watch handlers: `begin_stash` + FreezeAck (Freezing only), cutover + stash drain at Complete, drain-back on cancellation |
| `Action::ClientWrite` | The raw proxy leader path: stash if stashing, else forward to the table entry; leader admission = warmed + unfenced (`try_begin`) |
| `Action::CrashRestartWithinTtl` | Process death + same-name restart before lease expiry: registration and assignments survive, memory wiped |
| `Action::LeaseExpire` / `SelfFence` | Lease loss with the bounded zombie window before the keepalive self-fences (fix 1); same pair for routers, where lease loss also drops them from the freeze quorum |
| `Changelog.epoch_holder` under `Variant::EpochFenced` | Kafka transactional-producer fencing: warming = `init_transactions`, which takes the fence from whoever held it; a produce from a fenced-out producer is rejected before any client ack |

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
| Current, pod death past TTL + rejoin (3 pods) | holds | holds | holds |
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

**Scenario reachability is measured, not assumed.** Two `sometimes`
probes (enabled via the model's `probes` flag) answer "does more scale
open scenarios the small configs can't reach?" with checker facts:
**concurrent handoffs are reachable** (one rebalance transaction creates
a handoff per moved/fresh partition, and safety is verified at every
such state), and **a dual-role pod — drain-side of one handoff while
warm-side of another — is machine-proven reachable and safe**. Under
the old global rebalance gate it was unreachable; partial rebalancing
(in-flight partitions pinned, everything else planned) deliberately
lets handoffs from different plans coexist, so the probe that once
proved unreachability now pins the state as reached — and the same run
verifies every safety property across those interleavings, which holds
because every mechanism the two roles touch is partition-scoped. The rejoin scenario runs at 3 pods because that is
the smallest scale where the strategy genuinely chooses a placement
target rather than having it forced — the one axis a 2-pod world
under-exercises; the per-partition safety relations themselves are
two-party (old owner ↔ new owner, zombie ↔ successor).

## Usage

```sh
# Exhaustive checks with expected verdicts per scenario (~2min):
cargo test -p personhog-stateright --release

# The same run, reporting the explored size of every scenario. This is
# the sizing tool for a new configuration, and the review gate for any
# change to how state is encoded — see "Judging a state-space change":
STATERIGHT_REPORT=1 cargo test -p personhog-stateright --release -- --nocapture --test-threads=1

# Interactive state-space explorer (http://localhost:3000), for
# stepping through the double-zombie counterexample trace:
cargo run -p personhog-stateright --release -- current-zombie
```

Explorer variants: `current` (failures without zombie windows),
`current-zombie` (the residual, with counterexamples), `epoch-fenced`
(the fix).

## Coverage notes

Now in the explored space: pod rejoin after TTL expiry (at 3 pods, so
placement is genuinely chosen); coordinator concurrency (cleanup,
rebalance, phase advance, and completion cleanup are independently
scheduled actions, which also covers an overlapping outgoing
coordinator — every coordinator write is a guarded
check-on-current-state, so two coordinators are just more interleavings
of the same actions); strong reads (stashing with writes, per the
shipped design); two routers draining stashed FIFOs concurrently at
cutover (thaw ordering); multi-partition rebalance gating; concurrent
handoffs (probed reachable, safety checked throughout); the dual-role
pod shape (probed reachable since partial rebalancing — see Results).

The claim to serve is modeled apart from the lease (`Pod.claims_authority`,
production's `AuthorityClock`), because in production the two diverge and
the interesting failures live in the gap: a revoked lease leaves a pod
claiming what it no longer holds until something tells it. `ClaimDetection`
selects whether that is immediate — the pod watching its own registration —
or waits for a keepalive round, and the verdict pins that only the prompt
form closes the stale-read half. Stability now also requires the assigned
owner to still claim its partitions, so an owner that refuses its own
reads while looking alive to the coordinator fails liveness rather than
passing quietly.

Known remaining abstractions: warming is instant and atomic (production
streams from Kafka with retries — availability, not safety); stash
deadlines/bounds are not modeled (availability policies); the
mod_revision cleanup guard is encoded as atomic check-and-delete rather
than itself verified (an unguarded-cleanup variant could demonstrate
its necessity). Full elimination of the environment layer would mean
deterministic simulation behind a `PersonhogStore` trait seam — held as
a later investment.
