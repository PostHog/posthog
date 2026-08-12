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
use std::time::Duration;

use assignment_coordination::util::compute_required_handoffs;

use crate::strategy::AssignmentStrategy;
use crate::types::{
    HandoffPhase, HandoffState, PodDrainedAck, PodWarmedAck, RegisteredPod, RegisteredRouter,
    RouterFreezeAck,
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
/// Identity-based: every router this handoff requires must have acked
/// this partition's freeze. A count comparison would let a stale ack
/// from a departed router (acks are not lease-bound) stand in for a live
/// router that hasn't stashed yet — advancing to Draining while that
/// router still forwards writes to the old owner. Only acks echoing this
/// handoff's id count: an ack left over from a previous handoff of the
/// same partition proves nothing about this one.
///
/// The required set is the handoff's creation-time snapshot intersected
/// with the live registry, so it only ever shrinks; see
/// [`required_freeze_ackers`].
///
/// With no required routers there is no traffic to stash, so the quorum
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
    required_freeze_ackers(routers, handoff).all(|name| acked.contains(name))
}

/// The routers whose freeze ack this handoff needs: those it was created
/// with that are still registered.
///
/// Intersecting the snapshot with the live set makes the requirement
/// monotonic — it can only shrink. A router that dies drops out (it is no
/// longer routing, so it cannot reach the old owner), and one that joins
/// later is never added (safe to exclude — see
/// [`HandoffState::freeze_quorum`] for why).
pub fn required_freeze_ackers<'a>(
    routers: &'a [RegisteredRouter],
    handoff: &'a HandoffState,
) -> impl Iterator<Item = &'a str> + 'a {
    routers
        .iter()
        .map(|r| r.router_name.as_str())
        // `None` is a pre-upgrade record: fall back to requiring every
        // live router, which is what it was written under. A `Some`
        // snapshot is authoritative even when empty — zero routers at
        // creation means nobody must ack, not "apply the legacy rule".
        .filter(move |name| match &handoff.freeze_quorum {
            None => true,
            Some(quorum) => quorum.iter().any(|member| member == name),
        })
}

/// Whether `handoff` has sat in its *current phase* longer than that
/// phase's deadline.
///
/// Per-phase rather than total-age on purpose: the deadline exists to
/// catch a handoff that is wedged, and wedged is a property of a phase,
/// not of a lifetime. Freezing and Draining wait only on
/// acknowledgements, so their budget is short. Warming replays a
/// changelog whose length scales with the partition — a total-age
/// deadline would cancel a legitimately long warm and restart it from
/// zero, forever. Warming therefore gets its own, far more generous
/// budget (`warming_deadline`; zero disables it).
///
/// Records written before the phase clock existed carry a zero
/// `phase_entered_at_ms`; they fall back to the creation-time seconds
/// clock. A record with neither stamp cannot be judged on age at all —
/// acting on it would be acting on an age of "since the epoch".
pub fn past_phase_deadline(
    handoff: &HandoffState,
    now_ms: i64,
    handoff_deadline: Duration,
    warming_deadline: Duration,
) -> bool {
    if handoff.phase == HandoffPhase::Complete {
        return false;
    }
    let entered_ms = if handoff.phase_entered_at_ms > 0 {
        handoff.phase_entered_at_ms
    } else if handoff.started_at > 0 {
        handoff.started_at.saturating_mul(1000)
    } else {
        return false;
    };
    let deadline = match handoff.phase {
        HandoffPhase::Warming => warming_deadline,
        _ => handoff_deadline,
    };
    if deadline.is_zero() {
        return false;
    }
    now_ms.saturating_sub(entered_ms) > deadline.as_millis() as i64
}

/// The subset of [`required_freeze_ackers`] whose ack for `handoff` has
/// not arrived. Acks are correlated by handoff id, exactly as in
/// [`freeze_quorum_met`]: a stale ack left over from a predecessor
/// handoff of the same partition must not mask a router that has yet to
/// observe this one.
pub fn missing_freeze_ackers(
    routers: &[RegisteredRouter],
    freeze_acks: &[RouterFreezeAck],
    handoff: &HandoffState,
) -> Vec<String> {
    let acked: HashSet<&str> = freeze_acks
        .iter()
        .filter(|a| a.handoff_id == handoff.handoff_id)
        .map(|a| a.router_name.as_str())
        .collect();
    required_freeze_ackers(routers, handoff)
        .filter(|name| !acked.contains(name))
        .map(str::to_string)
        .collect()
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
            phase: HandoffPhase::Warming,
            started_at: 0,
            handoff_id: String::new(),
            freeze_quorum: None,
            created_at_ms: 0,
            phase_entered_at_ms: 0,
            new_owner_address: None,
        }
    }

    fn router(name: &str) -> RegisteredRouter {
        RegisteredRouter {
            router_name: name.to_string(),
            registered_at: 0,
            last_heartbeat: 0,
        }
    }

    fn freeze_ack(router: &str, handoff: &HandoffState) -> RouterFreezeAck {
        RouterFreezeAck {
            router_name: router.to_string(),
            partition: handoff.partition,
            acked_at: 0,
            acked_at_ms: 0,
            handoff_id: handoff.handoff_id.clone(),
        }
    }

    /// The wedge this snapshot exists to prevent: a router that
    /// registers after the handoff was created never receives its
    /// `Freezing` event, so requiring its ack leaves a quorum that
    /// nothing can satisfy and no cleanup path removes.
    #[test]
    fn a_router_that_joined_after_creation_is_not_required() {
        let mut h = handoff(0, Some("pod-a"), "pod-b");
        h.freeze_quorum = Some(vec!["router-0".to_string()]);
        let acks = [freeze_ack("router-0", &h)];

        assert!(
            freeze_quorum_met(&[router("router-0"), router("late-joiner")], &acks, &h),
            "a router registered after creation must not block the quorum"
        );
    }

    /// The deadline is a per-phase clock: a warm that outlives the
    /// general deadline must survive on Warming's own budget, while a
    /// wedged freeze of the same age cancels. A total-age deadline would
    /// livelock any partition whose changelog replay exceeds it — cancel,
    /// replan, warm from zero, cancel again.
    #[test]
    fn deadline_is_per_phase_and_patient_with_warming() {
        let short = Duration::from_secs(120);
        let long = Duration::from_secs(1800);
        let mut h = handoff(0, Some("pod-a"), "pod-b");
        h.phase = HandoffPhase::Warming;
        h.phase_entered_at_ms = 1_000;
        let now = 1_000 + 600_000;

        assert!(
            !past_phase_deadline(&h, now, short, long),
            "ten minutes into a warm is within Warming's budget"
        );
        h.phase = HandoffPhase::Freezing;
        assert!(
            past_phase_deadline(&h, now, short, long),
            "the same age in Freezing is a wedge"
        );

        // The phase clock restarts on advancement: a warm that follows a
        // slow freeze starts a fresh budget.
        h.phase = HandoffPhase::Warming;
        h.phase_entered_at_ms = now - 1_000;
        assert!(!past_phase_deadline(&h, now, short, long));

        // Zero disables a budget outright.
        h.phase_entered_at_ms = 1_000;
        assert!(!past_phase_deadline(&h, now, short, Duration::ZERO));
    }

    /// Pre-upgrade records fall back to the creation-time seconds clock;
    /// a record with no stamp at all is never judged on age.
    #[test]
    fn deadline_falls_back_to_started_at_and_skips_unstamped_records() {
        let short = Duration::from_secs(120);
        let long = Duration::from_secs(1800);
        let mut h = handoff(0, Some("pod-a"), "pod-b");
        h.phase = HandoffPhase::Freezing;

        h.started_at = 1;
        assert!(past_phase_deadline(&h, 601_000, short, long));

        h.started_at = 0;
        assert!(!past_phase_deadline(&h, i64::MAX, short, long));
    }

    /// Attribution mirror of the quorum predicate: the missing set names
    /// exactly the required routers whose ack for *this* handoff hasn't
    /// arrived — a stale ack from a predecessor handoff must not hide
    /// one.
    #[test]
    fn missing_ackers_names_the_holdout_and_ignores_stale_acks() {
        let mut h = handoff(0, Some("pod-a"), "pod-b");
        h.freeze_quorum = Some(vec!["router-0".to_string(), "router-1".to_string()]);
        let mut stale = freeze_ack("router-1", &h);
        stale.handoff_id = "a-previous-handoff".to_string();
        let acks = [freeze_ack("router-0", &h), stale];

        assert_eq!(
            missing_freeze_ackers(&[router("router-0"), router("router-1")], &acks, &h),
            vec!["router-1".to_string()],
            "router-1's stale ack proves nothing about this handoff"
        );
    }

    /// The other direction is what keeps it safe: a router that was
    /// present at creation may hold a routing table pointing at the old
    /// owner, so its ack stays mandatory.
    #[test]
    fn a_router_present_at_creation_is_still_required() {
        let mut h = handoff(0, Some("pod-a"), "pod-b");
        h.freeze_quorum = Some(vec!["router-0".to_string(), "router-1".to_string()]);
        let acks = [freeze_ack("router-0", &h)];

        assert!(
            !freeze_quorum_met(&[router("router-0"), router("router-1")], &acks, &h),
            "a snapshot member that has not acked must block the quorum"
        );
        // ...until it departs: a router that is gone cannot route.
        assert!(
            freeze_quorum_met(&[router("router-0")], &acks, &h),
            "a departed snapshot member must drop out of the requirement"
        );
    }

    /// Records written before the snapshot existed must keep their old
    /// meaning: with no captured requirement, every live router is
    /// required, since any of them might hold a table pointing at the
    /// old owner.
    #[test]
    fn an_absent_snapshot_requires_every_live_router() {
        let h = handoff(0, Some("pod-a"), "pod-b");
        assert!(h.freeze_quorum.is_none());
        let acks = [freeze_ack("router-0", &h)];

        assert!(
            !freeze_quorum_met(&[router("router-0"), router("router-1")], &acks, &h),
            "without a snapshot every live router must still be required"
        );
        assert!(freeze_quorum_met(&[router("router-0")], &acks, &h));
    }

    /// A captured-but-empty snapshot is not the legacy fallback: zero
    /// routers were registered at creation, so nobody must ack — even
    /// routers that register afterward. Falling back to the live-set
    /// rule here would let the requirement grow from zero and reopen
    /// the wedge for exactly this corner.
    #[test]
    fn an_empty_snapshot_requires_nobody() {
        let mut h = handoff(0, Some("pod-a"), "pod-b");
        h.freeze_quorum = Some(Vec::new());

        assert!(
            freeze_quorum_met(&[router("late-joiner")], &[], &h),
            "a router that registered after a zero-router creation must not be required"
        );
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
