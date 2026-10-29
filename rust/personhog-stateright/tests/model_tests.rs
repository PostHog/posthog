//! Exhaustive model-checking runs and their verdicts. Each test's doc
//! comment states what its configuration proves; the README carries the
//! verdict table and the state-space sizes.

use std::time::Instant;

use personhog_stateright::model::{ClaimDetection, HandoffModel, SealRule, WarmOrder, WarmReplay};
use stateright::{Checker, HasDiscoveries, Model};

/// Every checker explores in parallel: stateright defaults to a single
/// thread, which left the largest models (the two-partition
/// double-zombie pair) as multi-minute single-core BFS runs. The
/// nextest `stateright-heavy` group gives those tests the machine to
/// themselves so this parallelism gets real cores.
fn parallelism() -> usize {
    std::thread::available_parallelism().map_or(1, Into::into)
}

/// How every test in this file runs its checker, with optional size
/// reporting.
///
/// Going through one place means the size of each scenario can be reported
/// from the *real* test configurations — a separate config list would drift
/// from what CI actually runs. Set `STATERIGHT_REPORT` to print them:
///
/// ```sh
/// STATERIGHT_REPORT=1 cargo test -p personhog-stateright --release -- --nocapture --test-threads=1
/// ```
///
/// Those counts are the review gate for state-space work on this model: a
/// change meant to cost nothing must leave `unique` identical, and a
/// deliberate collapse must shrink it while every verdict below is
/// unchanged.
trait Explore {
    /// Explore the whole reachable state space. Required by any run that
    /// asserts a property *holds* — an `always` property is only proven by
    /// exhaustion.
    fn explore(self, scenario: &str) -> impl Checker<HandoffModel>;

    /// Explore only until `wanted` have all been discovered.
    ///
    /// For a run that asserts a counterexample *exists*, exhaustive search
    /// is wasted after the counterexample turns up — and stateright's
    /// default stopping condition never fires here. It waits for every
    /// property to be discovered, but a discovery for an `always` property
    /// is a violation, so the safety properties that hold never produce
    /// one, and `converges_to_stable` keeps the checker waiting regardless.
    ///
    /// Only use this where every assertion is existential. A run that also
    /// asserts a discovery is *absent* needs the whole space, and adding
    /// such an assertion to one of these tests means putting it back on
    /// [`Explore::explore`].
    fn explore_until(self, scenario: &str, wanted: &[&'static str]) -> impl Checker<HandoffModel>;
}

impl Explore for HandoffModel {
    fn explore(self, scenario: &str) -> impl Checker<HandoffModel> {
        let start = Instant::now();
        let checker = self.checker().threads(parallelism()).spawn_bfs().join();
        report(scenario, start, &checker);
        checker
    }

    fn explore_until(self, scenario: &str, wanted: &[&'static str]) -> impl Checker<HandoffModel> {
        let start = Instant::now();
        let checker = self
            .checker()
            .threads(parallelism())
            .finish_when(HasDiscoveries::AllOf(wanted.iter().copied().collect()))
            .spawn_bfs()
            .join();
        report(scenario, start, &checker);
        checker
    }
}

fn report(scenario: &str, start: Instant, checker: &impl Checker<HandoffModel>) {
    if std::env::var_os("STATERIGHT_REPORT").is_some() {
        println!(
            "STATERIGHT_REPORT\t{scenario}\tunique={}\tgenerated={}\tdepth={}\telapsed={:?}",
            checker.unique_state_count(),
            checker.state_count(),
            checker.max_depth(),
            start.elapsed(),
        );
    }
}

/// Baseline configuration; tests override fields with struct-update
/// syntax. Reads default on so every scenario also exercises the read
/// path under the shipped (stashed) design.
fn base() -> HandoffModel {
    HandoffModel {
        pods: 2,
        routers: 2,
        late_routers: 0,
        partitions: 1,
        warm_order: WarmOrder::FenceFirst,
        claim_lapses: false,
        claim_recovers: true,
        claim_detection: ClaimDetection::Prompt,
        writes: 2,
        reads: 1,
        crashes: 0,
        rejoins: 0,
        router_joins: 0,
        zombie_window: 0,
        hold_pods: 0,
        cancels: 0,
        chunked_plans: false,
        probes: false,
        migrations: 0,
        migrate_to: 1,
        keys: 1,
        seal_rule: SealRule::Assignment,
        warm_replay: WarmReplay::Sources,
        seal_breaks: 0,
        seal_grace: true,
        plan_basis_guard: true,
        quiet_start: true,
        freeze_checks_strays: true,
        park_behind_key: true,
    }
}

fn model(crashes: u8, zombie_window: u8) -> HandoffModel {
    HandoffModel {
        crashes,
        zombie_window,
        ..base()
    }
}

/// The shipped protocol with no failures: every safety property holds at
/// every reachable state, the liveness property holds on every full run,
/// and the interesting states are genuinely reachable.
#[test]
fn the_protocol_without_failures_is_safe_and_live() {
    model(0, 0)
        .explore("the_protocol_without_failures_is_safe_and_live")
        .assert_properties();
}

/// Crash-restart within the lease TTL and clean lease expiry (no zombie
/// data plane): the convergence machinery repairs wiped pod memory and
/// the dead-owner paths reassign, with no safety violation anywhere.
#[test]
fn the_protocol_with_crashes_is_safe_and_live() {
    model(1, 0)
        .explore("the_protocol_with_crashes_is_safe_and_live")
        .assert_properties();
}

/// A single zombie pod is provably safe: the freeze quorum has every
/// registered router stashing before the drain, so nothing routes to the
/// zombie after the new owner warms, and pre-warm zombie writes land
/// below the warm HWM. This is a stronger guarantee than the manual
/// review claimed — found by the checker refusing to produce a
/// counterexample for the weaker claim.
/// Refusing reads is the kind of change that can starve liveness, so this
/// clears every property, not only the safety ones.
#[test]
fn a_single_zombie_pod_is_safe() {
    HandoffModel {
        claim_lapses: true,
        ..model(1, 1)
    }
    .explore("a_single_zombie_pod_is_safe")
    .assert_properties();
}

/// The double zombie, closed by both halves at once: fencing rejects the
/// zombie's produce before any ack, and the read gate stops it answering
/// from a cache the new owner is already changing. Every property holds,
/// including the stale-read one that fencing alone used to leave broken.
#[test]
fn epoch_fenced_double_zombie_is_safe() {
    HandoffModel {
        claim_lapses: true,
        ..model(2, 1)
    }
    .explore("epoch_fenced_double_zombie_is_safe")
    .assert_properties();
}

/// The rejected warm ordering — changelog read before fence acquisition
/// — loses acked writes: a still-unfenced zombie commits a write after
/// the new owner's cutoff is captured but before the epoch bump exists
/// to reject it. This is the machine-checked reason `warm_partition`
/// acquires the fence before the warm read; the FenceFirst tests above
/// prove the shipped ordering closes the gap under the same budget.
#[test]
fn epoch_fenced_read_first_ordering_loses_acked_writes() {
    let checker = HandoffModel {
        warm_order: WarmOrder::ReadFirst,
        ..model(2, 1)
    }
    .explore_until(
        "epoch_fenced_read_first_ordering_loses_acked_writes",
        &["no_lost_acked_write"],
    );
    assert!(
        checker.discovery("no_lost_acked_write").is_some(),
        "read-before-fence must produce an acked-write-loss counterexample"
    );
}

/// A cancelled handoff whose target already acquired the fence leaves
/// the resuming old owner's producer epoch-stale; `resume_partition`
/// re-acquires before re-admitting writes, or the partition wedges with
/// every write rejected as fenced. The stability property requires
/// `write_capable` (not merely warmed + unfenced), so a model without
/// the resume re-acquisition fails liveness here. The pod churn
/// (expire, rejoin, expire mid-warm) is what manufactures a registered
/// old owner whose handoff target dies after the fence bump — two
/// partitions because a move handoff from a registered old owner only
/// arises from imbalance, and the minimum router/workload budgets keep
/// the churn-heavy space tractable (no zombie half is needed here).
#[test]
fn epoch_fenced_resume_after_cancelled_handoff_stays_live() {
    HandoffModel {
        routers: 1,
        partitions: 2,
        writes: 1,
        reads: 0,
        crashes: 2,
        rejoins: 1,
        ..base()
    }
    .explore("epoch_fenced_resume_after_cancelled_handoff_stays_live")
    .assert_properties();
}

/// Two partitions bring the cross-partition coordinator logic into
/// play: rebalancing defers while any handoff is in flight, so one
/// partition's failure handling gates the other's reassignment. All
/// safety and liveness properties must still hold, including under a
/// single zombie.
#[test]
fn two_partitions_single_zombie_is_safe() {
    HandoffModel {
        partitions: 2,
        crashes: 1,
        zombie_window: 1,
        ..base()
    }
    .explore("two_partitions_single_zombie_is_safe")
    .assert_properties();
}

/// A pod that dies past its lease TTL and later rejoins under the same
/// name must come back cleanly: fresh registration triggers a rebalance,
/// partitions return via Warming handoffs, and every safety and liveness
/// property holds across the departure, the interim, and the return.
/// Three pods, deliberately: with two, a departed pod's partition has
/// only one place to go — a third pod is the smallest scale at which the
/// sticky strategy genuinely chooses a target, so the rebalance paths
/// exercised here aren't placement-forced. That is the one axis a 2-pod
/// world under-exercises; the per-partition safety relations themselves
/// are two-party (see the probe tests below).
#[test]
fn current_with_rejoin_is_safe_and_live() {
    HandoffModel {
        pods: 3,
        crashes: 1,
        rejoins: 1,
        ..base()
    }
    .explore("current_with_rejoin_is_safe_and_live")
    .assert_properties();
}

/// Strong reads park in the same per-partition FIFO as writes while the
/// partition is stashing (#69456), so they drain to the warmed new owner
/// and always reflect every acked write across cutover. Before that
/// change shipped, a direct-read variant of this model produced the
/// cutover-race counterexample under this exact failure budget — the
/// machine validation that motivated it.
#[test]
fn strong_reads_are_complete_across_cutover() {
    HandoffModel {
        writes: 1,
        reads: 1,
        crashes: 1,
        ..base()
    }
    .explore("strong_reads_are_complete_across_cutover")
    .assert_properties();
}

/// Epoch fencing must close the residual at two partitions too — each
/// partition's producer epoch is independent, and this pins that the
/// fix doesn't rely on single-partition structure.
#[test]
fn epoch_fenced_two_partitions_double_zombie_is_safe() {
    let checker = HandoffModel {
        partitions: 2,
        crashes: 2,
        zombie_window: 1,
        ..base()
    }
    .explore("epoch_fenced_two_partitions_double_zombie_is_safe");
    assert!(checker.discovery("no_lost_acked_write").is_none());
    assert!(checker.discovery("no_split_write_acceptance").is_none());
}

/// A router that joins mid-run — the rolling-deploy scenario behind the
/// freeze-quorum snapshot. The joiner starts with an empty (fail-closed)
/// table, is excluded from the quorum of every handoff created before
/// it, and the checker explores every interleaving of its bootstrap
/// (`Observe`) with the coordinator's advancement — including the silent
/// joiner whose bootstrap never runs. Every safety property must hold
/// across all of them, and the run must still converge.
///
/// The crash budget also reaches the same-name rejoin: a snapshot
/// member lease-expires, self-fences, and rejoins as a fresh process —
/// required again (snapshot member, live), empty table, while its dead
/// incarnation's freeze ack persists in etcd (acks are not
/// lease-bound, exactly as in production). The checker judges those
/// interleavings here too; safety holds because the fresh process
/// fails closed until its bootstrap converges it.
#[test]
fn late_router_join_is_safe_and_live() {
    HandoffModel {
        routers: 1,
        late_routers: 1,
        router_joins: 1,
        crashes: 1,
        ..base()
    }
    .explore("late_router_join_is_safe_and_live")
    .assert_properties();
}

/// Reachability probe for the snapshot doing its job: a handoff advances
/// past Freezing while a registered late joiner has acked nothing.
/// Under the pre-snapshot live-set rule this state is unreachable — the
/// joiner's ack would be required, which is precisely the wedge — so its
/// reachability is the machine statement that the fix works, and the
/// same run asserts no safety property breaks in any interleaving that
/// reaches it.
#[test]
fn probe_silent_late_joiner_advance_is_reachable_and_safe() {
    let checker = HandoffModel {
        routers: 1,
        late_routers: 1,
        router_joins: 1,
        writes: 1,
        reads: 0,
        probes: true,
        ..base()
    }
    .explore("probe_silent_late_joiner_advance_is_reachable_and_safe");
    assert!(
        checker
            .discovery("advances_past_silent_late_joiner")
            .is_some(),
        "a handoff must be able to advance while a registered late joiner has not acked"
    );
    assert!(
        checker.discovery("no_lost_acked_write").is_none(),
        "advancing past a silent late joiner must not lose acked writes"
    );
    assert!(
        checker.discovery("no_split_write_acceptance").is_none(),
        "advancing past a silent late joiner must not create dual write acceptance"
    );
}

/// A rebalance that fires while zero routers are registered writes a
/// captured-but-empty snapshot, and a router joining afterward must not
/// be required by it — `Some([])` means nobody was routing, not "apply
/// the legacy live-set fallback". The unit test pins the predicate in
/// isolation; this checks the semantics end to end — snapshot capture,
/// shared predicate, advancement, convergence — and the probe confirms
/// the handoff genuinely advances while the joiner has acked nothing.
#[test]
fn zero_router_creation_with_late_joiner_is_safe_and_live() {
    let checker = HandoffModel {
        routers: 0,
        late_routers: 1,
        router_joins: 1,
        writes: 1,
        reads: 0,
        probes: true,
        ..base()
    }
    .explore("zero_router_creation_with_late_joiner_is_safe_and_live");
    assert!(
        checker
            .discovery("advances_past_silent_late_joiner")
            .is_some(),
        "an empty snapshot must advance without the late joiner's ack"
    );
    for safety in [
        "no_lost_acked_write",
        "no_split_write_acceptance",
        "drained_ack_is_final",
        "strong_reads_complete",
        "no_double_planned_handoff",
    ] {
        assert!(
            checker.discovery(safety).is_none(),
            "{safety} must hold under zero-router creation"
        );
    }
    assert!(
        checker.discovery("converges_to_stable").is_none(),
        "runs must still converge when handoffs were created router-less"
    );
}

/// Two in-flight handoffs carrying different snapshots: the first
/// rebalance's handoff (pre-join quorum) is still pinned while a pod
/// crash forces a second rebalance whose handoff captures the post-join
/// registry. Each handoff's requirement must be judged against its own
/// snapshot — this is the config that would catch a refactor computing
/// one requirement from live state and sharing it across handoffs,
/// which no single-partition config can distinguish from correct.
#[test]
fn probe_divergent_quorums_are_reachable_and_safe() {
    let checker = HandoffModel {
        partitions: 2,
        routers: 1,
        late_routers: 1,
        router_joins: 1,
        crashes: 1,
        writes: 1,
        reads: 0,
        probes: true,
        ..base()
    }
    .explore("probe_divergent_quorums_are_reachable_and_safe");
    assert!(
        checker
            .discovery("handoffs_with_divergent_quorums")
            .is_some(),
        "concurrent handoffs with different creation-time snapshots must be reachable"
    );
    assert!(
        checker.discovery("no_lost_acked_write").is_none(),
        "divergent quorums must not lose acked writes"
    );
    assert!(
        checker.discovery("no_double_planned_handoff").is_none(),
        "pinning must hold while snapshots diverge"
    );
    assert!(
        checker.discovery("no_split_write_acceptance").is_none(),
        "divergent quorums must not create dual write acceptance"
    );
}

/// The snapshot made the freeze quorum smaller, so the sharpest question
/// is whether the shrink reopens the residual epoch fencing closed. The
/// worst mix: a zombie router (a departed snapshot member — now exempt —
/// still routing on a stale table), a zombie pod, and a late joiner
/// outside every snapshot, all at once. Fencing is broker-side and
/// membership-independent, so the guarantee must survive; this run
/// checks that argument instead of trusting it.
#[test]
fn epoch_fenced_double_zombie_with_late_joiner_is_safe() {
    let checker = HandoffModel {
        routers: 1,
        late_routers: 1,
        router_joins: 1,
        crashes: 2,
        zombie_window: 1,
        ..base()
    }
    .explore("epoch_fenced_double_zombie_with_late_joiner_is_safe");
    assert!(
        checker.discovery("no_lost_acked_write").is_none(),
        "the shrunken quorum must not reopen acked-write loss under fencing"
    );
    assert!(
        checker.discovery("no_split_write_acceptance").is_none(),
        "the shrunken quorum must not reopen dual write acceptance under fencing"
    );
    assert!(
        checker.discovery("drained_ack_is_final").is_none(),
        "a drained ack must remain final with membership churn"
    );
}

/// Reachability probe: concurrent handoffs are a real scenario — one
/// rebalance transaction creates a handoff per moved/fresh partition, so
/// the phase machinery is genuinely exercised with multiple handoffs in
/// flight (safety is checked at every such state in the same run).
/// Workload budgets are zero: reachability of coordination shapes
/// doesn't need writes, and the space stays tiny.
#[test]
fn probe_concurrent_handoffs_are_reachable() {
    let checker = HandoffModel {
        partitions: 2,
        writes: 0,
        reads: 0,
        probes: true,
        ..base()
    }
    .explore("probe_concurrent_handoffs_are_reachable");
    assert!(
        checker.discovery("concurrent_handoffs").is_some(),
        "two in-flight handoffs must be reachable (one rebalance txn creates both)"
    );
}

/// Reachability probe: a pod simultaneously drain-side of one handoff
/// and warm-side of another. Unreachable under the old global rebalance
/// gate; partial rebalancing (in-flight partitions pinned, everything
/// else planned) deliberately lets handoffs from different plans
/// coexist, so the state is now reachable — and must be safe, since
/// every mechanism the two roles touch is partition-scoped. The same
/// run asserts the safety properties hold across those interleavings
/// and that pinning never plans a mid-move partition a second time.
#[test]
fn probe_dual_role_pod_is_reachable_and_safe() {
    let checker = HandoffModel {
        pods: 3,
        partitions: 3,
        writes: 0,
        reads: 0,
        crashes: 1,
        rejoins: 1,
        probes: true,
        ..base()
    }
    .explore("probe_dual_role_pod_is_reachable_and_safe");
    assert!(
        checker.discovery("pod_holds_both_roles").is_some(),
        "partial rebalancing must reach the dual-role state the checker judges"
    );
    assert!(
        checker.discovery("no_double_planned_handoff").is_none(),
        "pinning must keep concurrent rebalances from replanning a mid-move partition"
    );
    assert!(
        checker.discovery("no_lost_acked_write").is_none(),
        "dual-role concurrency must not lose acked writes"
    );
}

/// Deadline cancellation as atomic replacement, with no failures in the
/// mix: any in-flight handoff may be cancelled at any moment (the model
/// has no clock, so this covers every production deadline policy). The
/// budget of two lets the checker cancel a successor produced by an
/// earlier cancellation. Every safety property must hold across the
/// replacement interleavings — including a cancellation racing parked
/// stash requests — and every full run must still converge with empty
/// stashes.
#[test]
fn deadline_cancellation_by_replacement_is_safe_and_live() {
    HandoffModel {
        cancels: 2,
        ..base()
    }
    .explore("deadline_cancellation_by_replacement_is_safe_and_live")
    .assert_properties();
}

/// The reaffirm arm: cancelling a move handoff whose old owner is alive
/// must resolve as a Complete toward that owner — the pod re-derives
/// Serving and unfences, routers drain home. Manufacturing a move whose
/// old owner survives takes a crash and a rejoin (a fresh handoff has no
/// old owner, and a crashed owner is dead): the pod dies, its partition
/// moves, it rejoins, and the rebalance that moves a partition back is
/// the reaffirmable handoff. Two partitions so the sticky strategy has a
/// move to make at rejoin.
#[test]
fn cancellation_with_live_owner_reaffirms_and_resumes() {
    HandoffModel {
        partitions: 2,
        crashes: 1,
        rejoins: 1,
        cancels: 1,
        // One write keeps the workload probes reachable while holding
        // the state space down — this test's subject is the control
        // plane's reaffirm resolution, not the data path.
        writes: 1,
        reads: 0,
        ..base()
    }
    .explore("cancellation_with_live_owner_reaffirms_and_resumes")
    .assert_properties();
}

/// The successor arm under failure: the owner dies while its handoff is
/// in flight, and the cancellation replaces the record with the
/// successor in one transaction — the stash never observes a gap between
/// attempts. The dead-new-owner arm is exercised in the same space (a
/// cancellation's successor can itself target a pod that then dies).
#[test]
fn cancellation_with_dead_owner_replaces_atomically() {
    HandoffModel {
        crashes: 1,
        cancels: 1,
        ..base()
    }
    .explore("cancellation_with_dead_owner_replaces_atomically")
    .assert_properties();
}

/// Isolation probe for the stale-warm counterexample: the same
/// crash+rejoin+two-partition space with cancellation disabled. If this
/// fails too, the loss mechanism predates cancellation-by-replacement.
#[test]
fn rejoin_two_partitions_without_cancellation() {
    HandoffModel {
        partitions: 2,
        crashes: 1,
        rejoins: 1,
        writes: 1,
        reads: 0,
        ..base()
    }
    .explore("rejoin_two_partitions_without_cancellation")
    .assert_properties();
}

/// Fencing under handoff cancellation: every safety and liveness
/// property must hold when the cancellation budget and the fencing
/// variant are combined, a pairing no other verdict test covers.
///
/// This is breadth, not a pin: it passes with or without the resume's
/// epoch re-acquisition, because the interleaving that strands a
/// resuming owner on a stale epoch needs the cancelled target to have
/// warmed first, which this configuration does not force.
/// `epoch_fenced_resume_after_cancelled_handoff_stays_live` is the
/// red-checked pin for that fix.
#[test]
fn epoch_fenced_under_cancellation_is_safe_and_live() {
    HandoffModel {
        routers: 1,
        partitions: 2,
        writes: 1,
        reads: 0,
        cancels: 1,
        ..base()
    }
    .explore("epoch_fenced_under_cancellation_is_safe_and_live")
    .assert_properties();
}

/// The state the stability property's claim conjunct exists for, made
/// reachable and then made permanent.
///
/// Production's clock lapses at two thirds of the TTL while etcd holds
/// the registration for the full TTL, so for that third a pod refuses
/// every read while still looking alive to the coordinator — which
/// therefore reassigns nothing. Tying the claim to the registration, as
/// the model previously did, made `registered` imply `claims_authority`
/// and left the conjunct unable to change any verdict.
///
/// With recovery available the fleet converges; without it the black
/// hole is permanent and stability has to notice. If this stops
/// producing a counterexample, the conjunct has gone back to being
/// decorative.
#[test]
fn a_lapsed_claim_that_never_returns_fails_stability() {
    let checker = HandoffModel {
        claim_lapses: true,
        claim_recovers: false,
        crashes: 1,
        zombie_window: 1,
        ..base()
    }
    .explore_until(
        "a_lapsed_claim_that_never_returns_fails_stability",
        &["converges_to_stable"],
    );
    assert!(
        checker.discovery("converges_to_stable").is_some(),
        "an owner that refuses its own reads while looking alive to the coordinator \
         must fail stability rather than passing it"
    );
}

/// What the registration watch buys, as a verdict rather than prose.
///
/// A revoked lease deletes a pod's registration at once, but a pod that
/// only learns on its next keepalive round keeps claiming the partition
/// meanwhile — and the coordinator, which saw the deletion immediately,
/// can reassign inside that window. With detection delayed, the read
/// gate does not close the stale-read half at all; with the watch, it
/// does.
#[test]
fn prompt_detection_is_what_makes_the_read_gate_hold() {
    let cfg = |detection| HandoffModel {
        claim_lapses: true,
        claim_recovers: true,
        claim_detection: detection,
        crashes: 2,
        zombie_window: 1,
        ..base()
    };

    // The Delayed arm expects a stale read and stops at it; the Prompt arm
    // asserts there is none, so it has to explore everything.
    assert!(
        cfg(ClaimDetection::Delayed)
            .explore_until("delayed_claim_detection", &["strong_reads_complete"])
            .discovery("strong_reads_complete")
            .is_some(),
        "a claim outliving its lease must still leave stale reads reachable"
    );
    assert!(
        cfg(ClaimDetection::Prompt)
            .explore("prompt_claim_detection")
            .discovery("strong_reads_complete")
            .is_none(),
        "dropping the claim with the registration must close them"
    );
}

/// Rollout quota mode: pod-0 is a departing-generation Hold member and
/// the incoming pods are capped at their final share, the membership
/// the coordinator derives mid-rollout. The checker drives the quota
/// planner through every interleaving with a crash and a rejoin
/// available — pinning that quota-mode plans never double-plan a
/// partition, never strand one, and converge (the frozen-placement
/// failure shape is a liveness violation here). The rejoin covers the
/// capped pod that comes back at zero partitions and must be leveled
/// from its siblings, including when the crashed-and-returned pod is
/// the Hold member and phase-4 forcing pushed a survivor over cap.
#[test]
fn rollout_quota_mode_is_safe_and_live() {
    HandoffModel {
        pods: 3,
        partitions: 2,
        crashes: 1,
        rejoins: 1,
        hold_pods: 1,
        ..base()
    }
    .explore("rollout_quota_mode_is_safe_and_live")
    .assert_properties();
}

/// Chunked plan application (production: `apply_plan` past the etcd txn
/// budget): a plan's later units land against a world that kept moving —
/// phase advances, crashes, cancellations, competing rebalances — each
/// guarded on its plan-time snapshot. Every safety property must hold
/// across those interleavings and every full run must still converge.
#[test]
fn chunked_plan_application_is_safe_and_live() {
    HandoffModel {
        partitions: 2,
        chunked_plans: true,
        crashes: 1,
        cancels: 1,
        writes: 1,
        reads: 0,
        ..base()
    }
    .explore("chunked_plan_application_is_safe_and_live")
    .assert_properties();
}

/// A migration: one router, two pods, two keys, writes and a read racing every phase.
fn migration(partitions: u8, migrate_to: u8) -> HandoffModel {
    HandoffModel {
        routers: 1,
        partitions,
        migrate_to,
        migrations: 1,
        keys: 2,
        writes: 2,
        reads: 1,
        ..base()
    }
}

/// A grow holds, seals, flips and restarts with every safety property intact;
/// a cancel at any point before the seal unwinds in place.
#[test]
fn a_grow_migration_is_safe_and_live() {
    migration(1, 2)
        .explore("a_grow_migration_is_safe_and_live")
        .assert_properties();
}

/// The rejected bucket rule: a request that parks only when its partition
/// is stashing overtakes a request for its key parked under the old count.
#[test]
fn without_parking_behind_its_key_a_request_overtakes() {
    let checker = HandoffModel {
        park_behind_key: false,
        ..migration(1, 2)
    }
    .explore_until(
        "without_parking_behind_its_key_a_request_overtakes",
        &["no_overtaken_request"],
    );
    assert!(
        checker.discovery("no_overtaken_request").is_some(),
        "the bucket rule must let a later request overtake its key's parked one"
    );
}

/// A shrink dissolves the partition past the new space and still converges.
#[test]
fn a_shrink_migration_is_safe_and_live() {
    migration(2, 1)
        .explore("a_shrink_migration_is_safe_and_live")
        .assert_properties();
}

/// Two routers adopt the flip independently, so one hashes with the old
/// modulus while the other already drains under the new one.
#[test]
fn a_grow_migration_with_a_stale_router_is_safe_and_live() {
    HandoffModel {
        routers: 2,
        writes: 1,
        ..migration(1, 2)
    }
    .explore("a_grow_migration_with_a_stale_router_is_safe_and_live")
    .assert_properties();
}

/// A doubling where each new partition inherits one old one and keys split.
#[test]
fn a_two_to_four_grow_is_safe_and_live() {
    HandoffModel {
        writes: 1,
        keys: 4,
        ..migration(2, 4)
    }
    .explore("a_two_to_four_grow_is_safe_and_live")
    .assert_properties();
}

/// A holder that crash-restarts under its own name seals the partitions it
/// never reloaded, so the saga still completes.
#[test]
fn a_holder_restarted_mid_sealing_still_seals_and_the_saga_completes() {
    let checker = HandoffModel {
        crashes: 1,
        probes: true,
        writes: 1,
        ..migration(1, 2)
    }
    .explore("a_holder_restarted_mid_sealing_still_seals_and_the_saga_completes");
    checker.assert_properties();
    assert!(
        checker.discovery("sealed_without_warm").is_some(),
        "the restarted holder must seal a partition it never loaded"
    );
}

/// The rejected seal rule: targets drawn from what a pod has loaded leave a
/// restarted holder's partitions to nobody, and the saga never finishes.
#[test]
fn seal_targets_by_residency_wedge_a_restarted_holder() {
    let checker = HandoffModel {
        crashes: 1,
        writes: 1,
        seal_rule: SealRule::Residency,
        seal_grace: false,
        ..migration(1, 2)
    }
    .explore_until(
        "seal_targets_by_residency_wedge_a_restarted_holder",
        &["converges_to_stable"],
    );
    assert!(
        checker.discovery("converges_to_stable").is_some(),
        "residency-based seal targets must leave a run that never converges"
    );
}

/// The rejected rule: a registered holder whose seal never succeeds holds Sealing forever.
#[test]
fn a_broken_seal_without_the_grace_wedges_sealing() {
    let checker = HandoffModel {
        writes: 1,
        seal_breaks: 1,
        seal_grace: false,
        ..migration(1, 2)
    }
    .explore_until(
        "a_broken_seal_without_the_grace_wedges_sealing",
        &["converges_to_stable"],
    );
    assert!(
        checker.discovery("converges_to_stable").is_some(),
        "a broken seal with no grace must leave a run that never converges"
    );
}

/// Past the grace, peers seal what a broken holder could not, and the saga completes safely.
#[test]
fn a_broken_seal_is_healed_by_peers_after_the_grace() {
    let checker = HandoffModel {
        writes: 1,
        seal_breaks: 1,
        ..migration(1, 2)
    }
    .explore("a_broken_seal_is_healed_by_peers_after_the_grace");
    checker.assert_properties();
}

/// The rejected warm: a restart that reads the live partition alone misses
/// the old tail and serves a stale strong read.
#[test]
fn a_live_only_warm_loses_the_old_tail() {
    let checker = HandoffModel {
        warm_replay: WarmReplay::LiveOnly,
        ..migration(1, 2)
    }
    .explore_until(
        "a_live_only_warm_loses_the_old_tail",
        &["strong_reads_complete"],
    );
    assert!(
        checker.discovery("strong_reads_complete").is_some(),
        "a live-only warm must leave a stale strong read reachable"
    );
}

/// A write for a partition born in the flip parks before its handoff exists
/// and is delivered once it lands.
#[test]
fn probe_a_born_partition_write_parks_and_drains() {
    let checker = HandoffModel {
        probes: true,
        ..migration(1, 2)
    }
    .explore("probe_a_born_partition_write_parks_and_drains");
    checker.assert_properties();
    assert!(
        checker.discovery("born_partition_write_parked").is_some(),
        "a write must be able to park for a partition born in the flip"
    );
}

/// Both fates of a pending unit are genuinely reachable — applied after
/// other actions interleaved, and dropped by a failed plan-time guard —
/// and no interleaving that reaches them loses an acked write or
/// double-plans a partition.
#[test]
fn probe_chunked_pending_units_reach_both_fates_safely() {
    let checker = HandoffModel {
        partitions: 2,
        chunked_plans: true,
        crashes: 1,
        cancels: 1,
        writes: 1,
        reads: 0,
        probes: true,
        ..base()
    }
    .explore("probe_chunked_pending_units_reach_both_fates_safely");
    assert!(
        checker.discovery("chunked_pending_unit_applied").is_some(),
        "a pending unit must be able to land after its plan's first transaction"
    );
    assert!(
        checker.discovery("chunked_pending_unit_dropped").is_some(),
        "a failed plan-time guard must be able to stand a pending unit down"
    );
    for safety in ["no_lost_acked_write", "no_double_planned_handoff"] {
        assert!(
            checker.discovery(safety).is_none(),
            "{safety} must hold across chunked application"
        );
    }
}

/// A chunked bootstrap plan racing a migration: later units land only on
/// the basis they were planned on, so every property holds.
#[test]
fn a_chunked_plan_across_a_migration_is_safe_and_live() {
    HandoffModel {
        chunked_plans: true,
        writes: 1,
        reads: 0,
        ..migration(2, 4)
    }
    .explore("a_chunked_plan_across_a_migration_is_safe_and_live")
    .assert_properties();
}

/// A planner that ignores the plan basis serves the old generation past the flip. The quiet
/// start is off, since this small config reaches a mid-plan start only without it.
#[test]
fn an_unguarded_plan_across_a_migration_serves_the_old_generation() {
    let checker = HandoffModel {
        chunked_plans: true,
        writes: 1,
        reads: 0,
        plan_basis_guard: false,
        quiet_start: false,
        ..migration(2, 4)
    }
    .explore_until(
        "an_unguarded_plan_across_a_migration_serves_the_old_generation",
        &[
            "old_generation_quiet_after_flip",
            "no_mixed_modulus_acceptance",
        ],
    );
    assert!(checker
        .discovery("old_generation_quiet_after_flip")
        .is_some());
    assert!(checker.discovery("no_mixed_modulus_acceptance").is_some());
}

/// The rejected design: a saga that begins mid-handoff, with a freeze that
/// does not notice, freezes a fleet with a partition in motion and loses an acked write.
#[test]
fn starting_mid_handoff_loses_acked_writes() {
    let checker = HandoffModel {
        quiet_start: false,
        freeze_checks_strays: false,
        ..migration(1, 2)
    }
    .explore_until(
        "starting_mid_handoff_loses_acked_writes",
        &["no_lost_acked_write"],
    );
    assert!(checker.discovery("no_lost_acked_write").is_some());
}

/// The quiet start and the freeze's stray check are independent layers: each
/// alone keeps every property, the stray check by cancelling instead.
#[test]
fn either_layer_alone_keeps_a_mid_handoff_start_safe() {
    for (name, quiet_start, freeze_checks_strays) in [
        ("only_the_stray_check", false, true),
        ("only_the_quiet_start", true, false),
    ] {
        HandoffModel {
            quiet_start,
            freeze_checks_strays,
            ..migration(1, 2)
        }
        .explore(name)
        .assert_properties();
    }
}
