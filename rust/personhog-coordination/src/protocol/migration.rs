//! The migration saga's decisions, shared by the coordinator, the leaders and the model.

use std::collections::{HashMap, HashSet};

use super::plan_rebalance;
use crate::strategy::{AssignmentStrategy, Member};
use crate::types::{
    HandoffPhase, HandoffState, MigrationPhase, MigrationState, PartitionAssignment, SealAck,
};

/// What one freeze pass does: the holds to create and what still blocks Draining.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct FreezePlan {
    pub holds: Vec<(u32, String)>,
    pub blocking: Vec<String>,
    /// A partition whose owner or holder is not registered, which cancels the saga.
    pub holder_died: Option<(u32, String)>,
    /// An ordinary handoff on an old partition, which the quiet start rules out;
    /// it cancels the saga before anything it touches can be stranded.
    pub stray_handoff: Option<(u32, String)>,
}

/// Why the fleet is not quiet enough to start a saga, empty when it is: no
/// handoff record exists, and every old partition is assigned to a ready pod.
pub fn fleet_quiet(
    from_partitions: u32,
    assignments: &[PartitionAssignment],
    handoffs: &[HandoffState],
    ready: &HashSet<&str>,
) -> Vec<String> {
    let mut waiting: Vec<String> = handoffs
        .iter()
        .map(|h| format!("partition {}: handoff in {:?}", h.partition, h.phase))
        .collect();
    let owners: HashMap<u32, &str> = assignments
        .iter()
        .map(|a| (a.partition, a.owner.as_str()))
        .collect();
    for partition in 0..from_partitions {
        match owners.get(&partition) {
            None => waiting.push(format!("partition {partition}: unassigned")),
            Some(owner) if !ready.contains(owner) => {
                waiting.push(format!("partition {partition}: owner {owner} is not ready"))
            }
            Some(_) => {}
        }
    }
    waiting
}

/// The freeze decision: every assigned old partition gets a hold.
pub fn plan_freeze(
    from_partitions: u32,
    assignments: &[PartitionAssignment],
    handoffs: &[HandoffState],
    registered: &HashSet<&str>,
) -> FreezePlan {
    let by_partition: HashMap<u32, &HandoffState> =
        handoffs.iter().map(|h| (h.partition, h)).collect();
    let mut plan = FreezePlan::default();
    for assignment in assignments.iter().filter(|a| a.partition < from_partitions) {
        let partition = assignment.partition;
        match by_partition.get(&partition) {
            Some(h) if h.is_held() => {
                if !registered.contains(h.new_owner.as_str()) {
                    plan.holder_died = Some((partition, h.new_owner.clone()));
                }
                if h.phase == HandoffPhase::Freezing {
                    plan.blocking
                        .push(format!("partition {partition}: freeze quorum"));
                }
            }
            Some(_) => {}
            // A dead owner's partition is the planner's; holding it would only cancel next pass.
            None if !registered.contains(assignment.owner.as_str()) => {
                plan.holder_died = Some((partition, assignment.owner.clone()));
            }
            None => {
                plan.holds.push((partition, assignment.owner.clone()));
                plan.blocking
                    .push(format!("partition {partition}: hold created"));
            }
        }
    }
    plan.stray_handoff = handoffs
        .iter()
        .find(|h| h.partition < from_partitions && !h.is_held())
        .map(|h| (h.partition, h.handoff_id.clone()));
    plan
}

/// The old-topic partitions one leader seals: those no registered peer owns in the
/// assignment table, plus any no ack reports sealed once the seal is overdue.
pub fn seal_targets(
    pod_name: &str,
    migration_id: &str,
    from_partitions: u32,
    assignments: &[PartitionAssignment],
    registered: &HashSet<&str>,
    acks: &[SealAck],
    overdue: bool,
) -> Vec<u32> {
    let owned_by_a_peer: HashSet<u32> = assignments
        .iter()
        .filter(|a| a.owner != pod_name && registered.contains(a.owner.as_str()))
        .map(|a| a.partition)
        .collect();
    let unsealed: HashSet<u32> = if overdue {
        migration_unsealed(acks, migration_id, from_partitions)
            .into_iter()
            .collect()
    } else {
        HashSet::new()
    };
    (0..from_partitions)
        .filter(|p| !owned_by_a_peer.contains(p) || unsealed.contains(p))
        .collect()
}

/// Whether the ordinary planner may place: no saga, or a Resuming one whose
/// holds are all restarted. Until then the migration driver owns placement.
pub fn planner_may_place(migration_phase: Option<MigrationPhase>, holds_remain: bool) -> bool {
    match migration_phase {
        None => true,
        Some(MigrationPhase::Resuming) => !holds_remain,
        Some(_) => false,
    }
}

/// How long after Sealing begins every leader also seals whatever no ack reports sealed.
/// Counted from the phase, not per owner, so a slow pass is resealed by peers; seals are idempotent.
pub const SEAL_GRACE_MS: i64 = 2_000;

/// Past the grace, peers also seal an owner's unsealed partitions. Safe because
/// every hold is drained before Sealing.
pub fn seal_overdue(migration: &MigrationState, now_ms: i64) -> bool {
    migration.phase == MigrationPhase::Sealing
        && now_ms.saturating_sub(migration.phase_entered_at_ms) >= SEAL_GRACE_MS
}

/// Old-topic partitions no seal ack of this migration reports sealed.
pub fn migration_unsealed(acks: &[SealAck], migration_id: &str, partitions: u32) -> Vec<u32> {
    let sealed: HashSet<u32> = acks
        .iter()
        .filter(|a| a.migration_id == migration_id)
        .flat_map(|a| a.sealed.iter().copied())
        .collect();
    (0..partitions).filter(|p| !sealed.contains(p)).collect()
}

/// What one resume pass does with the saga's holds.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct ResumePlan {
    /// Holds the shrink removed: the hold, its acks and the assignment go together.
    pub dissolve: Vec<u32>,
    /// Holds whose holder is gone; the ordinary planner places them once the holds end.
    pub abandon: Vec<u32>,
    /// Holds restarted over the new changelog by their holder.
    pub restart: Vec<(u32, String)>,
    /// Partitions the grow created, placed fresh in the same plan.
    pub place: Vec<(u32, String)>,
}

/// The resume decision over the holds, each `(partition, holder)`: restart every
/// live hold in place, and place the partitions a grow created around them.
pub fn plan_resume<S: AssignmentStrategy + ?Sized>(
    strategy: &S,
    members: &[Member],
    to_partitions: u32,
    held: &[(u32, String)],
    assignments: &[PartitionAssignment],
    handoffs: &[HandoffState],
    registered: &HashSet<&str>,
) -> ResumePlan {
    let mut plan = ResumePlan::default();
    let mut current: HashMap<u32, String> = HashMap::new();
    for (partition, holder) in held {
        if *partition >= to_partitions {
            plan.dissolve.push(*partition);
        } else if !registered.contains(holder.as_str()) {
            plan.abandon.push(*partition);
        } else {
            current.insert(*partition, holder.clone());
            plan.restart.push((*partition, holder.clone()));
        }
    }
    let in_flight: HashSet<u32> = handoffs.iter().map(|h| h.partition).collect();
    let assigned: HashSet<u32> = assignments.iter().map(|a| a.partition).collect();
    for a in assignments {
        if a.partition < to_partitions
            && registered.contains(a.owner.as_str())
            && !in_flight.contains(&a.partition)
        {
            current.insert(a.partition, a.owner.clone());
        }
    }
    let mut placed = plan_rebalance(strategy, &current, members, to_partitions).handoffs;
    placed.sort_by_key(|h| h.partition);
    for planned in placed {
        let p = planned.partition;
        // Only partitions with no assignment and no handoff are new.
        if !current.contains_key(&p) && !in_flight.contains(&p) && !assigned.contains(&p) {
            plan.place.push((p, planned.new_owner));
        }
    }
    plan
}

/// Partitions of the new space without a registered owner or with a handoff in flight.
pub fn migration_unsettled(
    assignments: &[PartitionAssignment],
    handoffs: &[HandoffState],
    registered: &HashSet<&str>,
    to_partitions: u32,
) -> Vec<u32> {
    let owned: HashSet<u32> = assignments
        .iter()
        .filter(|a| registered.contains(a.owner.as_str()))
        .map(|a| a.partition)
        .collect();
    let in_flight: HashSet<u32> = handoffs.iter().map(|h| h.partition).collect();
    (0..to_partitions)
        .filter(|p| !owned.contains(p) || in_flight.contains(p))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn handoff(partition: u32, old_owner: Option<&str>, new_owner: &str) -> HandoffState {
        HandoffState {
            partition,
            old_owner: old_owner.map(str::to_string),
            new_owner: new_owner.to_string(),
            phase: HandoffPhase::Warming,
            started_at: 0,
            handoff_id: String::new(),
            freeze_quorum: None,
            freeze_quorum_ref: None,
            created_at_ms: 0,
            phase_entered_at_ms: 0,
            held_by: None,
            config_epoch: 0,
            new_owner_address: None,
        }
    }

    fn owned(partition: u32, owner: &str) -> PartitionAssignment {
        PartitionAssignment {
            partition,
            owner: owner.to_string(),
            advertise_address: None,
            status: crate::types::AssignmentStatus::Active,
        }
    }

    #[test]
    fn the_fleet_is_quiet_only_with_no_handoff_and_every_owner_ready() {
        let ready: HashSet<&str> = ["p0", "p1"].into_iter().collect();
        let settled = [owned(0, "p0"), owned(1, "p1")];
        assert!(fleet_quiet(2, &settled, &[], &ready).is_empty());

        let cases: [(&str, Vec<PartitionAssignment>, Vec<HandoffState>); 3] = [
            (
                "a handoff in flight",
                settled.to_vec(),
                vec![handoff(1, Some("p1"), "p0")],
            ),
            (
                "an owner that is gone",
                vec![owned(0, "p0"), owned(1, "gone")],
                vec![],
            ),
            ("an unassigned partition", vec![owned(0, "p0")], vec![]),
        ];
        for (name, assignments, handoffs) in cases {
            assert!(
                !fleet_quiet(2, &assignments, &handoffs, &ready).is_empty(),
                "{name}"
            );
        }
    }

    #[test]
    fn an_ordinary_handoff_during_the_freeze_is_a_stray() {
        let registered: HashSet<&str> = ["p0", "p1"].into_iter().collect();
        // Partition 1 has no assignment yet: a fresh placement.
        let placing = handoff(1, None, "p1");
        let plan = plan_freeze(2, &[owned(0, "p0")], &[placing], &registered);
        assert_eq!(plan.stray_handoff.map(|(p, _)| p), Some(1));
    }

    #[test]
    fn the_freeze_names_a_holder_that_is_gone() {
        let registered: HashSet<&str> = ["p0"].into_iter().collect();
        let unheld = plan_freeze(2, &[owned(0, "p0"), owned(1, "gone")], &[], &registered);
        assert_eq!(unheld.holder_died, Some((1, "gone".to_string())));
        assert_eq!(unheld.holds, vec![(0, "p0".to_string())]);

        let hold = HandoffState {
            held_by: Some("m-1".to_string()),
            ..handoff(1, Some("gone"), "gone")
        };
        let held = plan_freeze(2, &[owned(0, "p0"), owned(1, "gone")], &[hold], &registered);
        assert_eq!(held.holder_died, Some((1, "gone".to_string())));
    }
}
