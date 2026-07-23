//! Pure protocol decision functions, shared between the coordinator and
//! the stateright model (`personhog-stateright`).
//!
//! The coordinator calls these on state it reads from etcd; the model
//! calls them on checker state. One implementation on both sides means
//! the logic the checker verifies is the logic production runs — the
//! phase-advancement rules cannot drift from their verified form.
//!
//! Every function is a pure predicate over partition-scoped inputs: the
//! caller supplies the acks already filtered to one partition (as
//! `list_*_acks(partition)` returns them).

use std::collections::{HashMap, HashSet};

use assignment_coordination::util::compute_required_handoffs;

use crate::strategy::AssignmentStrategy;
use crate::types::{
    HandoffState, PodDrainedAck, PodWarmedAck, RegisteredPod, RegisteredRouter, RouterFreezeAck,
};

/// One handoff a rebalance has decided to create. `old_owner` is `None`
/// for a fresh assignment (no prior owner), which skips the drain.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PlannedHandoff {
    pub partition: u32,
    pub old_owner: Option<String>,
    pub new_owner: String,
}

/// A rebalance decision: the full desired placement, and the handoffs
/// required to reach it from the current placement.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RebalancePlan {
    /// partition → owner for every assigned partition (the strategy's
    /// output, verbatim).
    pub desired: HashMap<u32, String>,
    /// Handoffs to create: moves (owner changed) carry the prior owner;
    /// fresh partitions (assigned for the first time) carry none.
    /// Partitions already owned by their target appear in `desired` only.
    pub handoffs: Vec<PlannedHandoff>,
}

/// Plan a rebalance: compute the desired placement via `strategy`, then
/// diff it against the current assignments. Every planned handoff starts
/// at Freezing — including fresh assignments — so routers never route to
/// a pod whose cache hasn't been warmed.
///
/// Callers with handoffs in flight must plan through
/// `plan_partial_rebalance`, which pins those partitions — planning a
/// mid-move partition twice would create overlapping handoffs and
/// conflicting assignment writes. The coordinator and the stateright
/// model both plan through the partial variant; the model's
/// `no_double_planned_handoff` property verifies the pinning across
/// every interleaving of rebalances with in-flight handoffs.
pub fn plan_rebalance<S: AssignmentStrategy + ?Sized>(
    strategy: &S,
    current: &HashMap<u32, String>,
    active_pods: &[String],
    total_partitions: u32,
) -> RebalancePlan {
    let desired = strategy.compute_assignments(current, active_pods, total_partitions);
    let moves = compute_required_handoffs(current, &desired);
    let moved: HashSet<u32> = moves.iter().map(|(p, _, _)| *p).collect();

    let mut handoffs: Vec<PlannedHandoff> = moves
        .into_iter()
        .map(|(partition, old_owner, new_owner)| PlannedHandoff {
            partition,
            old_owner: Some(old_owner),
            new_owner,
        })
        .collect();
    for (partition, new_owner) in &desired {
        if !current.contains_key(partition) && !moved.contains(partition) {
            handoffs.push(PlannedHandoff {
                partition: *partition,
                old_owner: None,
                new_owner: new_owner.clone(),
            });
        }
    }
    RebalancePlan { desired, handoffs }
}

/// Plan a rebalance around in-flight handoffs. Their partitions are
/// pinned: excluded from the planned handoffs and from `desired` (whose
/// entries the coordinator writes as stable assignments), so the two
/// overlap hazards — a second handoff for a mid-move partition, and an
/// assignment write for one — are impossible by construction, and a
/// stuck handoff defers only its own partition instead of the topology.
/// For the placement computation each pinned partition is attributed to
/// its handoff's new owner, so the balance math agrees with the imminent
/// state and a sticky strategy plans around the in-flight moves instead
/// of fighting them.
pub fn plan_partial_rebalance<S: AssignmentStrategy + ?Sized>(
    strategy: &S,
    current: &HashMap<u32, String>,
    in_flight: &[HandoffState],
    active_pods: &[String],
    total_partitions: u32,
) -> RebalancePlan {
    let pinned: HashSet<u32> = in_flight.iter().map(|h| h.partition).collect();
    let mut effective = current.clone();
    for handoff in in_flight {
        effective.insert(handoff.partition, handoff.new_owner.clone());
    }
    let mut plan = plan_rebalance(strategy, &effective, active_pods, total_partitions);
    plan.handoffs.retain(|h| !pinned.contains(&h.partition));
    plan.desired
        .retain(|partition, _| !pinned.contains(partition));
    plan
}

/// Whether the freeze quorum for `handoff` is met.
///
/// Identity-based: every currently registered router must have acked
/// this partition's freeze. A count comparison would let a stale ack
/// from a departed router (acks are not lease-bound) stand in for a live
/// router that hasn't stashed yet — advancing to Draining while that
/// router still forwards writes to the old owner. Only acks echoing this
/// handoff's id count: an ack left over from a previous handoff of the
/// same partition proves nothing about this one.
///
/// With zero routers there is no traffic to stash, so the freeze quorum
/// is vacuously met. This keeps bootstrap and router-less configurations
/// (e.g. tests exercising only the coordinator+pod) unblocked.
pub fn freeze_quorum_met(
    routers: &[RegisteredRouter],
    freeze_acks: &[RouterFreezeAck],
    handoff: &HandoffState,
) -> bool {
    let acked: HashSet<&str> = freeze_acks
        .iter()
        .filter(|a| a.handoff_id == handoff.handoff_id)
        .map(|a| a.router_name.as_str())
        .collect();
    routers
        .iter()
        .all(|r| acked.contains(r.router_name.as_str()))
}

/// Whether the drain requirement for `handoff` is satisfied.
///
/// "Alive" here means the old owner's etcd registration key still exists
/// (its lease hasn't expired) — not just that it's `Ready`. A `Draining`
/// pod is shutting down gracefully but is still capable of running its
/// handoff handler and writing a `DrainedAck`, and may still have
/// inflight handlers. Bypassing the drain requirement for such a pod
/// would let the coordinator advance to Warming while the old owner is
/// still producing — breaking the protocol's core invariant. Only treat
/// the old owner as drained when its key is genuinely absent, or when it
/// has acked this handoff attempt.
pub fn drain_satisfied(
    registered_pods: &[RegisteredPod],
    drained_acks: &[PodDrainedAck],
    handoff: &HandoffState,
) -> bool {
    match &handoff.old_owner {
        // Defensive: a handoff that reached Draining without an old owner
        // shouldn't exist (Freezing skips Draining when old_owner is
        // None), but if it does, there's nothing to drain.
        None => true,
        Some(name) => {
            let old_owner_present = registered_pods.iter().any(|p| p.pod_name == *name);
            !old_owner_present
                || drained_acks
                    .iter()
                    .any(|a| a.pod_name == *name && a.handoff_id == handoff.handoff_id)
        }
    }
}

/// Whether the new owner has warmed for this handoff attempt.
pub fn warm_satisfied(warmed_acks: &[PodWarmedAck], handoff: &HandoffState) -> bool {
    warmed_acks
        .iter()
        .any(|a| a.pod_name == handoff.new_owner && a.handoff_id == handoff.handoff_id)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::strategy::StickyBalancedStrategy;

    fn handoff(partition: u32, old_owner: Option<&str>, new_owner: &str) -> HandoffState {
        HandoffState {
            partition,
            old_owner: old_owner.map(str::to_string),
            new_owner: new_owner.to_string(),
            phase: crate::types::HandoffPhase::Warming,
            started_at: 0,
            handoff_id: String::new(),
        }
    }

    #[test]
    fn pinned_partitions_are_never_planned() {
        let current: HashMap<u32, String> = (0..4).map(|p| (p, "pod-a".to_string())).collect();
        let in_flight = [handoff(0, Some("pod-a"), "pod-b")];
        let active = [
            "pod-a".to_string(),
            "pod-b".to_string(),
            "pod-c".to_string(),
        ];

        let plan =
            plan_partial_rebalance(&StickyBalancedStrategy, &current, &in_flight, &active, 4);

        assert!(
            plan.handoffs.iter().all(|h| h.partition != 0),
            "a pinned partition must never get a second handoff"
        );
        assert!(
            !plan.desired.contains_key(&0),
            "a pinned partition must never get an assignment write"
        );
        // A stuck handoff defers only itself: the new pod still receives
        // partitions from the unpinned remainder.
        assert!(
            plan.handoffs.iter().any(|h| h.new_owner == "pod-c"),
            "unpinned partitions must still rebalance toward the new pod"
        );
    }

    #[test]
    fn pinned_partitions_count_against_their_target() {
        // Two of pod-a's four partitions are mid-move to pod-b. Attributed
        // to their target, the placement is already balanced — a plan that
        // read the raw current map would see 4-vs-0 and churn the other
        // two partitions to pod-b right behind the in-flight moves.
        let current: HashMap<u32, String> = (0..4).map(|p| (p, "pod-a".to_string())).collect();
        let in_flight = [
            handoff(0, Some("pod-a"), "pod-b"),
            handoff(1, Some("pod-a"), "pod-b"),
        ];
        let active = ["pod-a".to_string(), "pod-b".to_string()];

        let plan =
            plan_partial_rebalance(&StickyBalancedStrategy, &current, &in_flight, &active, 4);

        assert!(
            plan.handoffs.is_empty(),
            "in-flight moves already balance the placement; planning more is churn: {:?}",
            plan.handoffs
        );
    }
}
