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

use personhog_stateright::model::{HandoffModel, Variant};
use stateright::{Checker, Model};

/// Baseline configuration; tests override fields with struct-update
/// syntax. Reads default on so every scenario also exercises the read
/// path under the shipped (stashed) design.
fn base() -> HandoffModel {
    HandoffModel {
        pods: 2,
        routers: 2,
        partitions: 1,
        variant: Variant::Current,
        writes: 2,
        reads: 1,
        crashes: 0,
        rejoins: 0,
        zombie_window: 0,
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
        .checker()
        .spawn_bfs()
        .join()
        .assert_properties();
}

/// Crash-restart within the lease TTL and clean lease expiry (no zombie
/// data plane): the convergence machinery repairs wiped pod memory and
/// the dead-owner paths reassign, with no safety violation anywhere.
#[test]
fn current_protocol_with_crashes_is_safe_and_live() {
    model(Variant::Current, 1, 0)
        .checker()
        .spawn_bfs()
        .join()
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
        .checker()
        .spawn_bfs()
        .join()
        .assert_properties();
}

/// The documented residual, now precisely characterized: a lease-expired
/// router (excluded from the freeze quorum, never stashing, stale table)
/// routes a write to a lease-expired pod (coordination loop dead, never
/// fenced) after the partition's new owner warmed — the write is acked
/// but sits beyond the warm HWM, invisible to the new owner forever.
#[test]
fn current_protocol_double_zombie_loses_acked_writes() {
    let checker = model(Variant::Current, 2, 1).checker().spawn_bfs().join();
    assert!(
        checker.discovery("no_lost_acked_write").is_some(),
        "the double zombie must produce an acked-write-loss counterexample"
    );
    assert!(
        checker.discovery("no_split_write_acceptance").is_some(),
        "the double zombie must produce a dual-capability counterexample"
    );
}

/// Epoch fencing closes the residual: warming bumps the broker's
/// producer epoch, so the zombie's produce is rejected before any ack.
/// All safety properties hold again, zombie window and all.
#[test]
fn epoch_fenced_double_zombie_is_safe() {
    let checker = model(Variant::EpochFenced, 2, 1)
        .checker()
        .spawn_bfs()
        .join();
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
    .checker()
    .spawn_bfs()
    .join()
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
    .checker()
    .spawn_bfs()
    .join()
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
    .checker()
    .spawn_bfs()
    .join()
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
    .checker()
    .spawn_bfs()
    .join();
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
    .checker()
    .spawn_bfs()
    .join();
    assert!(checker.discovery("no_lost_acked_write").is_none());
    assert!(checker.discovery("no_split_write_acceptance").is_none());
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
    .checker()
    .spawn_bfs()
    .join();
    assert!(
        checker.discovery("concurrent_handoffs").is_some(),
        "two in-flight handoffs must be reachable (one rebalance txn creates both)"
    );
}

/// Reachability probe: a pod simultaneously drain-side of one handoff
/// and warm-side of another is UNREACHABLE under the shipped protocol,
/// even with churn (crash + rejoin) at the smallest scale where the
/// strategy has real choices. The checker proves what the code only
/// implies: within one plan the sticky strategy never takes from and
/// gives to the same pod, and the rebalance deferral gate keeps handoffs
/// from different plans from coexisting. If a strategy or gate change
/// ever makes this reachable, this test fails and the dual-role case
/// needs explicit safety analysis.
#[test]
fn probe_dual_role_pod_is_unreachable() {
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
    .checker()
    .spawn_bfs()
    .join();
    assert!(
        checker.discovery("pod_holds_both_roles").is_none(),
        "the sticky strategy + rebalance deferral gate should make dual-role pods unreachable"
    );
}

/// Prints the explored state-space size per configuration. Not a
/// verdict test — run manually to judge config tractability:
/// `cargo test -p personhog-stateright --release -- --ignored --nocapture state_space`
#[test]
#[ignore = "informational; prints state counts"]
fn state_space_report() {
    let configs = [
        (
            "2 pods / 2 routers / 1 partition, w2 c1 z1",
            2u8,
            2u8,
            1u8,
            2u8,
            1u8,
            1u8,
        ),
        (
            "2 pods / 2 routers / 1 partition, w2 c2 z1",
            2,
            2,
            1,
            2,
            2,
            1,
        ),
        (
            "2 pods / 2 routers / 2 partitions, w2 c1 z1",
            2,
            2,
            2,
            2,
            1,
            1,
        ),
        (
            "2 pods / 2 routers / 2 partitions, w2 c2 z1",
            2,
            2,
            2,
            2,
            2,
            1,
        ),
        (
            "3 pods / 2 routers / 2 partitions, w2 c2 z1",
            3,
            2,
            2,
            2,
            2,
            1,
        ),
    ];
    for (label, pods, routers, partitions, writes, crashes, zombie) in configs {
        let start = Instant::now();
        let checker = HandoffModel {
            pods,
            routers,
            partitions,
            writes,
            crashes,
            zombie_window: zombie,
            ..base()
        }
        .checker()
        .spawn_bfs()
        .join();
        println!(
            "{label}: {} unique states, {:?}",
            checker.unique_state_count(),
            start.elapsed()
        );
    }
}
