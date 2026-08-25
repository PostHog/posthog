//! Exhaustive model-checking runs with the expected verdicts per
//! variant. These are the durable record of what the protocol does and
//! does not guarantee:
//!
//! | scenario                     | no_lost_acked_write | no_split_acceptance |
//! |------------------------------|---------------------|----------------------|
//! | Current, no failures         | holds               | holds                |
//! | Current, crash/lease loss    | holds               | holds                |
//! | Current, single zombie pod   | holds               | holds                |
//! | Current, double zombie       | VIOLATED (residual) | VIOLATED (residual)  |
//! | EpochFenced, double zombie   | holds               | holds                |
//!
//! Every row above is about *write* safety. Stale strong reads from a
//! zombie pod are a separate, still-open residual that fencing does not
//! address; only the configurations without a zombie window uphold
//! `strong_reads_complete`.
//!
//! The single-zombie row is a result the checker sharpened beyond what
//! the manual review claimed: a zombie *pod* alone cannot lose an acked
//! write, because the identity freeze quorum has every registered router
//! stashing before the drain (no honest router routes to the zombie
//! post-warm) and anything the zombie accepts pre-warm sits below the
//! warm HWM and is captured. Loss requires the double zombie — a
//! lease-expired router (outside the quorum, stale table) feeding a
//! lease-expired pod. That is the documented residual epoch fencing
//! closes; the checker finds the exact interleaving as a counterexample.

use std::time::Instant;

use personhog_stateright::model::{ClaimDetection, HandoffModel, Variant, WarmOrder};
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
        variant: Variant::Current,
        warm_order: WarmOrder::FenceFirst,
        lease_gated_reads: false,
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
        probes: false,
    }
}

fn model(variant: Variant, crashes: u8, zombie_window: u8) -> HandoffModel {
    HandoffModel {
        variant,
        crashes,
        zombie_window,
        ..base()
    }
}

/// The shipped protocol with no failures: every safety property holds at
/// every reachable state, the liveness property holds on every full run,
/// and the interesting states are genuinely reachable.
#[test]
fn current_protocol_without_failures_is_safe_and_live() {
    model(Variant::Current, 0, 0)
        .explore("current_protocol_without_failures_is_safe_and_live")
        .assert_properties();
}

/// Crash-restart within the lease TTL and clean lease expiry (no zombie
/// data plane): the convergence machinery repairs wiped pod memory and
/// the dead-owner paths reassign, with no safety violation anywhere.
#[test]
fn current_protocol_with_crashes_is_safe_and_live() {
    model(Variant::Current, 1, 0)
        .explore("current_protocol_with_crashes_is_safe_and_live")
        .assert_properties();
}

/// A single zombie pod is provably safe: the freeze quorum has every
/// registered router stashing before the drain, so nothing routes to the
/// zombie after the new owner warms, and pre-warm zombie writes land
/// below the warm HWM. This is a stronger guarantee than the manual
/// review claimed — found by the checker refusing to produce a
/// counterexample for the weaker claim.
#[test]
fn current_protocol_single_zombie_pod_is_safe() {
    model(Variant::Current, 1, 1)
        .explore("current_protocol_single_zombie_pod_is_safe")
        .assert_properties();
}

/// The documented residual, now precisely characterized: a lease-expired
/// router (excluded from the freeze quorum, never stashing, stale table)
/// routes a write to a lease-expired pod (coordination loop dead, never
/// fenced) after the partition's new owner warmed — the write is acked
/// but sits beyond the warm HWM, invisible to the new owner forever.
#[test]
fn current_protocol_double_zombie_loses_acked_writes() {
    let checker = model(Variant::Current, 2, 1).explore_until(
        "current_protocol_double_zombie_loses_acked_writes",
        &["no_lost_acked_write", "no_split_write_acceptance"],
    );
    assert!(
        checker.discovery("no_lost_acked_write").is_some(),
        "the double zombie must produce an acked-write-loss counterexample"
    );
    assert!(
        checker.discovery("no_split_write_acceptance").is_some(),
        "the double zombie must produce a dual-capability counterexample"
    );
}

/// Epoch fencing closes the *write* half of the residual: warming bumps
/// the broker's producer epoch, so the zombie's produce is rejected
/// before any ack. Acked-write loss, split acceptance, and drain-ack
/// finality all hold again, zombie window and all.
///
/// `strong_reads_complete` is deliberately not asserted here: it still
/// fails, because a zombie pod serves reads from its stale cache and
/// nothing rejects them when the read gate is off. Turning it on closes
/// that — see `fencing_and_lease_gated_reads_together_close_the_double_zombie`.
#[test]
fn epoch_fenced_double_zombie_is_safe() {
    let checker = model(Variant::EpochFenced, 2, 1).explore("epoch_fenced_double_zombie_is_safe");
    assert!(
        checker.discovery("no_lost_acked_write").is_none(),
        "epoch fencing must eliminate acked-write loss"
    );
    assert!(
        checker.discovery("no_split_write_acceptance").is_none(),
        "epoch fencing must restore single-writer capability"
    );
    assert!(
        checker.discovery("drained_ack_is_final").is_none(),
        "a drained ack must remain final under fencing"
    );
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
        ..model(Variant::EpochFenced, 2, 1)
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
        variant: Variant::EpochFenced,
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
fn current_two_partitions_single_zombie_is_safe() {
    HandoffModel {
        partitions: 2,
        crashes: 1,
        zombie_window: 1,
        ..base()
    }
    .explore("current_two_partitions_single_zombie_is_safe")
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

/// The double-zombie residual must also reproduce at two partitions —
/// guards against the cross-partition coordinator logic (rebalance
/// deferral, per-partition cleanup) accidentally masking or altering the
/// single-partition verdict.
#[test]
fn two_partitions_double_zombie_loses_acked_writes() {
    let checker = HandoffModel {
        partitions: 2,
        crashes: 2,
        zombie_window: 1,
        ..base()
    }
    .explore_until(
        "two_partitions_double_zombie_loses_acked_writes",
        &["no_lost_acked_write"],
    );
    assert!(checker.discovery("no_lost_acked_write").is_some());
}

/// Epoch fencing must close the residual at two partitions too — each
/// partition's producer epoch is independent, and this pins that the
/// fix doesn't rely on single-partition structure.
#[test]
fn epoch_fenced_two_partitions_double_zombie_is_safe() {
    let checker = HandoffModel {
        partitions: 2,
        variant: Variant::EpochFenced,
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
        variant: Variant::EpochFenced,
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
        variant: Variant::EpochFenced,
        writes: 1,
        reads: 0,
        cancels: 1,
        ..base()
    }
    .explore("epoch_fenced_under_cancellation_is_safe_and_live")
    .assert_properties();
}

/// Fencing and the read gate are complementary, not alternative.
///
/// Fencing alone leaves `strong_reads_complete` violated under the
/// double zombie: it rejects a zombie's writes, not its reads, and the
/// zombie keeps answering from a cache the new owner is already
/// changing. The gate alone does not close it either — without fencing
/// the zombie's write is lost, so the *legitimate* owner is the one
/// serving a read missing an acked write. Only both together hold every
/// safety property, which is why the leader's read gate is a
/// prerequisite for enabling fencing rather than an independent
/// improvement.
#[test]
fn fencing_and_lease_gated_reads_together_close_the_double_zombie() {
    let cfg = |variant, gated| HandoffModel {
        variant,
        lease_gated_reads: gated,
        claim_recovers: true,
        crashes: 2,
        zombie_window: 1,
        ..base()
    };
    // The two arms below that expect a stale read stop at it; the arm that
    // asserts none exists has to explore everything. Each arm reports under
    // its own label, so their state counts stay comparable separately.
    let stale_reads_reachable = |scenario, variant, gated| {
        cfg(variant, gated)
            .explore_until(scenario, &["strong_reads_complete"])
            .discovery("strong_reads_complete")
            .is_some()
    };

    assert!(
        stale_reads_reachable("read_gate_alone", Variant::Current, true),
        "the read gate alone must not close it: the honest owner serves a read missing the \
         zombie's lost write"
    );
    assert!(
        stale_reads_reachable("fencing_alone", Variant::EpochFenced, false),
        "fencing alone must not close it: the zombie still answers reads"
    );
    assert!(
        cfg(Variant::EpochFenced, true)
            .explore("fencing_and_read_gate_together")
            .discovery("strong_reads_complete")
            .is_none(),
        "together they must close it"
    );
}

/// The gate makes pods refuse reads, which is exactly the kind of change
/// that can starve liveness — so a gated configuration has to clear
/// every property, not just the stale-read one the complementarity
/// verdict inspects.
#[test]
fn a_lease_gated_fleet_is_safe_and_live() {
    HandoffModel {
        variant: Variant::EpochFenced,
        lease_gated_reads: true,
        claim_recovers: true,
        crashes: 1,
        zombie_window: 1,
        ..base()
    }
    .explore("a_lease_gated_fleet_is_safe_and_live")
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
        variant: Variant::EpochFenced,
        lease_gated_reads: true,
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
        variant: Variant::EpochFenced,
        lease_gated_reads: true,
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
