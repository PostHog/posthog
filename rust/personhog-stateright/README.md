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
As of 2026-10-16 the suite explores ~19M states across 43 runs.
Its long pole is the two-partition epoch-fenced double zombie, about a quarter of the wall clock on its own:

| Scenario | Unique states | Wall time |
|---|---|---|
| `epoch_fenced_two_partitions_double_zombie_is_safe` | 4.9M | 8.7s |
| `cancellation_with_live_owner_reaffirms_and_resumes` | 1.9M | 3.1s |
| `chunked_plan_application_is_safe_and_live` | 1.4M | 2.2s |
| `probe_chunked_pending_units_reach_both_fates_safely` | 1.4M | 2.8s |
| `rollout_quota_mode_is_safe_and_live` | 1.2M | 2.0s |
| `a_two_to_four_grow_is_safe_and_live` | 1.1M | 2.8s |
| `a_chunked_plan_across_a_migration_is_safe_and_live` | 0.9M | 2.4s |
| *everything else (36 runs)* | 6.1M | 11s |

Roughly: a second partition costs ~20x, a second failure in the budget ~10x, a third pod ~2x. The migration scenarios run at one or two partitions with keyed traffic and cost 20k to 1.1M states each; the 2→4 grow is the largest.
Times are release mode, one scenario at a time on 12 cores — a CI runner with 4 slower cores is several times that, so treat them as ratios rather than absolutes.

The test suite (41 scenarios; the two-partition double zombie dominates the runtime) runs the full
verdict matrix — the 1-partition scenarios, the 2-partition cases, the
3-pod rejoin, and the reachability probes. Two partitions matter for the coordinator's
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
| `protocol::migration::plan_freeze` | which held self-handoffs the freeze creates, and what cancels it (a stray ordinary handoff, a holder or owner that is gone) — `Action::MigrateDrive` at Freezing calls it |
| `protocol::migration::fleet_quiet` | when a requested saga may start: no handoff record, and every old partition assigned to a registered, Ready pod — `Action::MigrateStart` is enabled through it, as the coordinator's start step is |
| `protocol::migration::plan_resume` | what Resuming does with the holds: dissolve the shrunk ones, abandon a dead holder's, restart the rest over the new changelog, and place the partitions a grow created — `Action::MigrateDrive` at Resuming calls it |
| `protocol::migration::migration_unsealed` / `migration_unsettled` | the Sealing and Resuming gates (every old partition sealed; no held handoff left) — `Action::MigrateDrive` calls them |
| `protocol::migration::seal_targets` | which old partitions a pod seals: every one assigned to it, every one owned by no registered peer, and once the seal is overdue every one no ack reports sealed — `Action::SealTick` calls it |
| `protocol::migration::planner_may_place` | when the ordinary planner may place during a saga — `Action::Rebalance` and `RebalanceChunked` are enabled through it, as the coordinator's pass is |
| `changelog::warm_sources` | the partitions a warm replays: the congruent old partitions (mod gcd, key-filtered) then the live one — a pod's warm effect reads it |
| `types::MigrationPhase::may_transition_to` | the saga's legal phase moves, so a new phase or a new edge fails the model's matches at compile time |

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
| `Changelog.epoch_holder` | Kafka transactional-producer fencing: warming = `init_transactions`, which takes the fence from whoever held it; a produce from a fenced-out producer is rejected before any client ack |
| `Action::MigrateRequest` / `MigrateStart` / `MigrateRequestExpires` | the control plane's request, the coordinator's start once the fleet is quiet, and a request rejected or expired before it starts |
| `Action::MigrateDrive` / `MigrateCancel` | the coordinator's migration saga: one guarded phase step per drive (freeze, drain, seal, flip, resume, complete); cancel from any pre-Seal phase, standing in for both the operator and the pre-flip deadline |
| `Action::SealTick(pod)` | the leader's seal duty: a registered pod seals its `seal_targets` on the old generation, no capture needed, plus every unsealed partition once the grace has lapsed |
| `Action::SealGraceElapses` / `BreakSeal(pod)` | the 2s Sealing grace lapsing, and a registered pod whose seal never succeeds (a hung Kafka client with a live lease); a new incarnation heals it |
| `Action::AdoptConfig(router)` | the router's config watch: adopt the flipped config. Parked requests stay where they are, and the new count only decides which drain takes them; a write for a partition born in the flip parks until its handoff drains |
| `Action::ClientWrite(router, key)` / `ClientStrongRead(router, key)` | keyed traffic: the router hashes the key under its own adopted modulus, so a stale router routes to the old partition until it adopts |
| `Changelog` keyed by `(epoch, partition)` | one changelog per generation; the old generation stays readable for the warm's tail replay and must take no produce after the flip |

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
| `no_overtaken_request` (safety) | A router never delivers a request while an earlier request for the same key is still parked |
| `no_mixed_modulus_acceptance` (safety) | Every acked write lands in the live generation's changelog, never a retired one |
| `holds_stop_at_draining` (safety) | The ordinary handoff loop never moves a migration hold past Draining |
| `old_generation_quiet_after_flip` (safety) | Once flipped, no pod can produce to the old generation |
| `migration_completes`, `migration_cancels` (sanity) | Both saga outcomes are reachable in a migration config |
| `converges_to_stable` (liveness) | Every full run ends quiescent: no handoffs, every partition served warm and unfenced by its sticky target, all live routers agreeing, no stashed traffic, and no saga in flight or left to request |

## Results

| Scenario | `no_lost_acked_write` | `no_split_write_acceptance` | `strong_reads_complete` |
|---|---|---|---|
| No failures | holds | holds | holds |
| Crash-restart within TTL / clean lease expiry | holds | holds | holds |
| Pod death past TTL + rejoin (3 pods) | holds | holds | holds |
| Single zombie pod | **holds** | **holds** | holds |
| Double zombie (router + pod) | holds | holds | holds |
| Strong reads + one failure | holds | holds | holds |
| Changelog migration: grow 1→2, shrink 2→1, grow 2→4 | holds | holds | holds |
| Migration with a stale router (adopts late) | holds | holds | holds |
| Migration with the holder crash-restarted mid-hold | holds | holds | holds |
| Migration, seal targets by residency (rejected rule) | holds | holds | wedges (liveness) |
| Migration, live-only warm (rejected rule) | holds | holds | **violated** |
| Migration, a registered holder that cannot seal, with the grace | holds | holds | holds |
| Migration, a registered holder that cannot seal, no grace (rejected rule) | holds | holds | wedges (liveness) |
| Migration racing a chunked bootstrap plan, with the plan basis | holds | holds | holds |
| Migration racing a chunked bootstrap plan, no plan basis (rejected rule) | **violated** (old generation written after the flip) | holds | holds |
| Migration started with a handoff in flight (rejected rule) | **violated** | **violated** | **violated** |

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

**Epoch fencing closes the double zombie.** Warming bumps the broker's
producer epoch, and the zombie's produce is rejected before any client
ack. The model carried an unfenced variant until the leader stopped
being able to run one; the counterexample it produced is the reason the
protocol is shaped this way, and it lives in this repository's history
rather than in a checked property.

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

**The migration saga is checked against the same production decision functions.** The model drives `plan_freeze`, `migration_unsealed`, `migration_unsettled`, `seal_targets` and `warm_sources` through a grow, a shrink and a 2→4 grow, with keyed traffic, a stale router, a crash-restarted holder, and the deadline cancel. Its first run on the branch found a real hole: the freeze held the partitions in the assignment table, but an ordinary handoff for a fresh placement (a partition with no assignment yet) kept running, warmed, and accepted a write the flip then stranded. The saga now starts only from a fleet with no handoff in flight (`MigrateStart` requires it), and `quiet_start: false` keeps the rejected start, which loses acked writes. Two rejected rules stay in the model as variants, each pinned by the counterexample that rejected it: sealing by residency (`SealRule::Residency`) wedges a holder that crash-restarted before sealing, because it no longer holds the data and nobody else is assigned, so the saga never leaves Sealing; a live-only warm (`WarmReplay::LiveOnly`) loses the old generation's tail, because a key's last write before the flip sits in an old partition the new one never replays. A third, `seal_grace: false`, pins why the seal grace exists: one registered holder whose seal never succeeds holds Sealing forever, since peers leave a registered owner's partitions alone and nothing cancels past Draining.

## Usage

```sh
# Exhaustive checks with expected verdicts per scenario (~2min):
cargo test -p personhog-stateright --release

# The same run, reporting the explored size of every scenario. This is
# the sizing tool for a new configuration, and the review gate for any
# change to how state is encoded — see "Judging a state-space change":
STATERIGHT_REPORT=1 cargo test -p personhog-stateright --release -- --nocapture --test-threads=1

# Interactive state-space explorer (http://localhost:3000), for
# stepping through a trace state by state:
cargo run -p personhog-stateright --release -- fenced-zombie
```

Explorer scenarios: `fenced` (failures without zombie windows),
`fenced-zombie` (a zombie window), `fenced-read-first` (the rejected
warm ordering, with counterexamples).

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

Migration coverage: one migration per run with at most one draining generation, which admission also enforces, so the retire step and a second migration are not modeled; the key hash is `key % partitions`, which keeps the congruence structure of the real hash without its constant; the seal is instant (production claims and drops every lane's transactional id); the cancel is unbudgeted, standing in for the pre-flip deadline as well as the operator; the writer is not modeled, since its drain only gates retirement. Coordinator passes are atomic steps in the model, so a stalled pass that wakes after a successor acted cannot occur here; the rule that every plan requires the record it was decided on unchanged is pinned by the coordination store tests instead.

Known remaining abstractions: warming is instant and atomic (production
streams from Kafka with retries — availability, not safety); stash
deadlines/bounds are not modeled (availability policies); the
mod_revision cleanup guard is encoded as atomic check-and-delete rather
than itself verified (an unguarded-cleanup variant could demonstrate
its necessity). Full elimination of the environment layer would mean
deterministic simulation behind a `PersonhogStore` trait seam — held as
a later investment.
