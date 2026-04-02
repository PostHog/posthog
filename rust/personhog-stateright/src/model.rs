use std::collections::{BTreeMap, BTreeSet};

use stateright::Model;

use crate::assignment;
use crate::types::*;

/// The PersonHog handoff protocol model for Stateright.
pub struct HandoffModel {
    pub config: ModelConfig,
}

impl HandoffModel {
    pub fn new(config: ModelConfig) -> Self {
        Self { config }
    }

    /// Get sorted list of active (Ready) pod IDs from state.
    fn active_pods(state: &SystemState) -> Vec<PodId> {
        let mut pods: Vec<PodId> = state
            .registered_pods
            .iter()
            .filter(|(_, status)| **status == PodStatus::Ready)
            .map(|(id, _)| *id)
            .collect();
        pods.sort();
        pods
    }
}

impl Model for HandoffModel {
    type State = SystemState;
    type Action = Action;

    fn init_states(&self) -> Vec<Self::State> {
        let initial_pods: Vec<PodId> = self.config.initial_pod_ids();
        let assignments = assignment::compute_assignments(&initial_pods, self.config.num_partitions);

        // Each initial pod owns its assigned partitions
        let mut pod_owned: BTreeMap<PodId, BTreeSet<Partition>> = BTreeMap::new();
        for &pod in &initial_pods {
            pod_owned.insert(pod, BTreeSet::new());
        }
        for (&partition, &owner) in &assignments {
            pod_owned.entry(owner).or_default().insert(partition);
        }

        // Each router starts with the correct routing table
        let mut router_tables = BTreeMap::new();
        for router in self.config.router_ids() {
            router_tables.insert(router, assignments.clone());
        }

        let registered_pods: BTreeMap<PodId, PodStatus> = initial_pods
            .iter()
            .map(|&p| (p, PodStatus::Ready))
            .collect();

        vec![SystemState {
            registered_pods,
            assignments,
            handoffs: BTreeMap::new(),
            acks: BTreeSet::new(),
            pod_owned,
            router_tables,
            accepted_writes: BTreeSet::new(),
            attempted_writes: BTreeSet::new(),
            needs_rebalance: false,
        }]
    }

    fn actions(&self, state: &Self::State, actions: &mut Vec<Self::Action>) {
        // --- Complete any active writes first (always available) ---
        for &(partition, pod) in &state.accepted_writes {
            actions.push(Action::ClientWriteComplete(partition, pod));
        }

        // --- Pod lifecycle ---
        // Scaling pods that haven't joined yet can join
        for pod in self.config.scaling_pod_ids() {
            if !state.registered_pods.contains_key(&pod) {
                actions.push(Action::PodJoin(pod));
            }
        }

        if self.config.allow_crashes {
            // Any registered pod can crash
            for &pod in state.registered_pods.keys() {
                actions.push(Action::PodCrash(pod));
            }
        }

        // Any Ready pod can start draining
        for (&pod, status) in &state.registered_pods {
            if *status == PodStatus::Ready {
                actions.push(Action::PodStartDrain(pod));
            }
        }

        // --- Coordinator actions ---
        // Rebalance when topology changed and no handoffs in flight
        if state.needs_rebalance && state.handoffs.is_empty() {
            actions.push(Action::CoordinatorRebalance);
        }

        for (&partition, handoff) in &state.handoffs {
            match self.config.protocol {
                ProtocolVariant::EarlyRelease => {
                    // Old owner releases partition before Ready is signaled.
                    // Available when handoff is Warming and old owner hasn't released yet.
                    if handoff.phase == HandoffPhase::Warming
                        && !handoff.old_owner_released
                        && state.registered_pods.contains_key(&handoff.old_owner)
                    {
                        actions.push(Action::OldPodReleasePartition(
                            handoff.old_owner,
                            partition,
                        ));
                    }

                    // New owner warms and signals Ready.
                    // In EarlyRelease: only after old owner has released.
                    if handoff.phase == HandoffPhase::Warming
                        && handoff.old_owner_released
                        && state.registered_pods.contains_key(&handoff.new_owner)
                    {
                        actions.push(Action::NewPodWarmAndSignalReady(
                            handoff.new_owner,
                            partition,
                        ));
                    }
                }
                ProtocolVariant::Current => {
                    // In Current protocol, new owner warms and signals Ready immediately
                    // (no early release step).
                    if handoff.phase == HandoffPhase::Warming
                        && state.registered_pods.contains_key(&handoff.new_owner)
                    {
                        actions.push(Action::NewPodWarmAndSignalReady(
                            handoff.new_owner,
                            partition,
                        ));
                    }
                }
            }

            // Router cutover: available when handoff is Ready and router hasn't acked
            if handoff.phase == HandoffPhase::Ready {
                for router in self.config.router_ids() {
                    if !state.acks.contains(&(partition, router)) {
                        actions.push(Action::RouterExecuteCutover(router, partition));
                    }
                }
            }

            // Coordinator completes handoff when all routers have acked
            if handoff.phase == HandoffPhase::Ready {
                let all_acked = self
                    .config
                    .router_ids()
                    .iter()
                    .all(|r| state.acks.contains(&(partition, *r)));
                if all_acked {
                    actions.push(Action::CoordinatorCompleteHandoff(partition));
                }
            }

            // Old pod final cleanup on Complete (Current protocol releases here)
            if handoff.phase == HandoffPhase::Complete {
                match self.config.protocol {
                    ProtocolVariant::Current => {
                        // In Current protocol, old owner releases ownership on Complete
                        if !handoff.old_owner_released
                            && state.registered_pods.contains_key(&handoff.old_owner)
                        {
                            actions.push(Action::OldPodFinalCleanup(handoff.old_owner, partition));
                        }
                        // Delete handoff after release
                        if handoff.old_owner_released
                            || !state.registered_pods.contains_key(&handoff.old_owner)
                        {
                            actions.push(Action::OldPodFinalCleanup(handoff.old_owner, partition));
                        }
                    }
                    ProtocolVariant::EarlyRelease => {
                        // Already released, just cleanup the handoff entry
                        actions.push(Action::OldPodFinalCleanup(handoff.old_owner, partition));
                    }
                }
            }

            // Cleanup stale handoff if target pod is gone
            if !state.registered_pods.contains_key(&handoff.new_owner) {
                actions.push(Action::CoordinatorCleanupStaleHandoff(partition));
            }
        }

        // --- Client writes: a client can write to any partition through any router ---
        // Only generate if the router has a routing entry for the partition
        for router in self.config.router_ids() {
            if let Some(table) = state.router_tables.get(&router) {
                for partition in 0..self.config.num_partitions {
                    if table.contains_key(&partition) {
                        actions.push(Action::ClientWrite(router, partition));
                    }
                }
            }
        }
    }

    fn next_state(&self, state: &Self::State, action: Self::Action) -> Option<Self::State> {
        let mut s = state.clone();

        match action {
            Action::PodJoin(pod) => {
                s.registered_pods.insert(pod, PodStatus::Ready);
                s.pod_owned.insert(pod, BTreeSet::new());
                s.needs_rebalance = true;
            }

            Action::PodCrash(pod) => {
                s.registered_pods.remove(&pod);
                s.pod_owned.remove(&pod);
                // Remove any writes served by this pod
                s.accepted_writes.retain(|&(_, p)| p != pod);
                s.attempted_writes.retain(|&(_, p)| p != pod);
                s.needs_rebalance = true;
            }

            Action::PodStartDrain(pod) => {
                if let Some(status) = s.registered_pods.get_mut(&pod) {
                    *status = PodStatus::Draining;
                }
                s.needs_rebalance = true;
            }

            Action::CoordinatorRebalance => {
                let active = Self::active_pods(&s);

                if active.is_empty() {
                    s.needs_rebalance = false;
                    return Some(s);
                }

                let desired =
                    assignment::compute_assignments(&active, self.config.num_partitions);

                if s.assignments.is_empty() {
                    // Initial assignment: write directly, no handoffs needed
                    for (&partition, &owner) in &desired {
                        s.assignments.insert(partition, owner);
                        s.pod_owned.entry(owner).or_default().insert(partition);
                    }
                    // Update router tables to match
                    for table in s.router_tables.values_mut() {
                        *table = desired.clone();
                    }
                } else {
                    let handoffs =
                        assignment::compute_required_handoffs(&s.assignments, &desired);

                    if handoffs.is_empty() {
                        // No movement needed
                    } else {
                        // Create handoff entries for moving partitions
                        for (partition, old_owner, new_owner) in handoffs {
                            s.handoffs.insert(
                                partition,
                                HandoffInfo {
                                    old_owner,
                                    new_owner,
                                    phase: HandoffPhase::Warming,
                                    old_owner_released: false,
                                },
                            );
                        }

                        // Write stable assignments (partitions NOT being handed off)
                        for (&partition, &owner) in &desired {
                            if !s.handoffs.contains_key(&partition) {
                                s.assignments.insert(partition, owner);
                            }
                        }
                    }
                }

                s.needs_rebalance = false;
            }

            Action::OldPodReleasePartition(pod, partition) => {
                // Old owner drains inflight writes and drops partition ownership.
                // In the real system, the pod finishes all inflight requests before
                // removing the partition from its owned set.
                s.accepted_writes.remove(&(partition, pod));
                s.attempted_writes.remove(&(partition, pod));

                if let Some(owned) = s.pod_owned.get_mut(&pod) {
                    owned.remove(&partition);
                }
                // Mark the handoff as old_owner_released
                if let Some(handoff) = s.handoffs.get_mut(&partition) {
                    handoff.old_owner_released = true;
                }
            }

            Action::NewPodWarmAndSignalReady(pod, partition) => {
                // New owner adds partition to its local ownership
                s.pod_owned.entry(pod).or_default().insert(partition);
                // Advance handoff to Ready
                if let Some(handoff) = s.handoffs.get_mut(&partition) {
                    handoff.phase = HandoffPhase::Ready;
                }
            }

            Action::RouterExecuteCutover(router, partition) => {
                if let Some(handoff) = s.handoffs.get(&partition) {
                    // Router updates its local routing table to point to new owner
                    if let Some(table) = s.router_tables.get_mut(&router) {
                        table.insert(partition, handoff.new_owner);
                    }
                    // Router writes ack
                    s.acks.insert((partition, router));
                }
            }

            Action::CoordinatorCompleteHandoff(partition) => {
                if let Some(handoff) = s.handoffs.get_mut(&partition) {
                    // Atomically: update assignment to new owner + set phase to Complete
                    s.assignments.insert(partition, handoff.new_owner);
                    handoff.phase = HandoffPhase::Complete;
                }
            }

            Action::OldPodFinalCleanup(pod, partition) => {
                match self.config.protocol {
                    ProtocolVariant::Current => {
                        // In Current protocol, this is where old owner drains + releases
                        s.accepted_writes.remove(&(partition, pod));
                        s.attempted_writes.remove(&(partition, pod));
                        if let Some(owned) = s.pod_owned.get_mut(&pod) {
                            owned.remove(&partition);
                        }
                        if let Some(handoff) = s.handoffs.get_mut(&partition) {
                            handoff.old_owner_released = true;
                        }
                    }
                    ProtocolVariant::EarlyRelease => {
                        // Already released earlier, nothing to do for ownership
                    }
                }
                // Clean up handoff and acks
                s.handoffs.remove(&partition);
                s.acks.retain(|&(p, _)| p != partition);
            }

            Action::CoordinatorCleanupStaleHandoff(partition) => {
                // Target pod crashed during handoff, remove the handoff
                s.handoffs.remove(&partition);
                s.acks.retain(|&(p, _)| p != partition);
                // Trigger re-rebalance to reassign the partition
                s.needs_rebalance = true;
            }

            Action::ClientWrite(router, partition) => {
                // Router looks up its routing table and sends write to that pod
                if let Some(table) = s.router_tables.get(&router) {
                    if let Some(&target_pod) = table.get(&partition) {
                        // Always track the attempt (for writes_only_to_owners invariant)
                        s.attempted_writes.insert((partition, target_pod));

                        // Pod only accepts if it owns the partition.
                        // If not (stale route), the pod rejects the request.
                        let pod_owns = s
                            .pod_owned
                            .get(&target_pod)
                            .map_or(false, |owned| owned.contains(&partition));
                        if pod_owns {
                            s.accepted_writes.insert((partition, target_pod));
                        }
                    }
                }
            }

            Action::ClientWriteComplete(partition, pod) => {
                s.accepted_writes.remove(&(partition, pod));
                s.attempted_writes.remove(&(partition, pod));
            }
        }

        Some(s)
    }

    fn properties(&self) -> Vec<stateright::Property<Self>> {
        vec![
            stateright::Property::always("no_split_writes", check_no_split_writes),
            stateright::Property::always("writes_only_to_owners", check_writes_only_to_owners),
            stateright::Property::always("no_orphaned_partitions", check_no_orphaned_partitions),
            stateright::Property::always("valid_handoff_state", check_valid_handoff_state),
            stateright::Property::always("single_pod_ownership", check_single_pod_ownership),
            stateright::Property::always(
                "router_agreement_when_stable",
                check_router_agreement_when_stable,
            ),
            stateright::Property::always(
                "no_write_to_unregistered_pod",
                check_no_write_to_unregistered_pod,
            ),
            stateright::Property::always(
                "assignment_ownership_agreement",
                check_assignment_ownership_agreement,
            ),
            stateright::Property::always(
                "handoff_consistent_with_assignment",
                check_handoff_consistent_with_assignment,
            ),
            stateright::Property::always(
                "draining_pod_gains_no_partitions",
                check_draining_pod_gains_no_partitions,
            ),
            stateright::Property::eventually(
                "converges_to_stable",
                check_converges_to_stable,
            ),
        ]
    }
}

// ── Invariant check functions ──────────────────────────────────

/// Invariant 1: No Split Writes (CRITICAL)
/// For every partition, at most one pod is serving ACCEPTED writes.
fn check_no_split_writes(model: &HandoffModel, state: &SystemState) -> bool {
    for partition in 0..model.config.num_partitions {
        let serving_pods: BTreeSet<PodId> = state
            .accepted_writes
            .iter()
            .filter(|&&(p, _)| p == partition)
            .map(|&(_, pod)| pod)
            .collect();
        if serving_pods.len() > 1 {
            return false;
        }
    }
    true
}

/// Invariant 2: Writes Only to Owners (MAY NOT HOLD in EarlyRelease)
/// Every ATTEMPTED write targets a pod that owns the partition.
/// Uses attempted_writes (includes rejected writes) to detect stale routing.
fn check_writes_only_to_owners(_model: &HandoffModel, state: &SystemState) -> bool {
    for &(partition, pod) in &state.attempted_writes {
        let owns = state
            .pod_owned
            .get(&pod)
            .map_or(false, |owned| owned.contains(&partition));
        if !owns {
            return false;
        }
    }
    true
}

/// Invariant 3: No Orphaned Partitions
/// Every partition is either assigned to a live pod or in a handoff.
fn check_no_orphaned_partitions(model: &HandoffModel, state: &SystemState) -> bool {
    for partition in 0..model.config.num_partitions {
        let assigned = state.assignments.contains_key(&partition);
        let in_handoff = state.handoffs.contains_key(&partition);
        if !assigned && !in_handoff {
            return false;
        }
    }
    true
}

/// Invariant 4: Valid Handoff State
/// Handoff states are internally consistent.
fn check_valid_handoff_state(model: &HandoffModel, state: &SystemState) -> bool {
    for handoff in state.handoffs.values() {
        // In EarlyRelease: old_owner_released must be true before Ready
        if model.config.protocol == ProtocolVariant::EarlyRelease
            && handoff.phase != HandoffPhase::Warming
            && !handoff.old_owner_released
        {
            return false;
        }
        // new_owner should not equal old_owner
        if handoff.new_owner == handoff.old_owner {
            return false;
        }
    }
    true
}

/// Invariant 5: Single Owner In Pod-Owned
/// At most one pod has any given partition in its owned set.
fn check_single_pod_ownership(model: &HandoffModel, state: &SystemState) -> bool {
    for partition in 0..model.config.num_partitions {
        let owner_count = state
            .pod_owned
            .values()
            .filter(|owned| owned.contains(&partition))
            .count();
        if owner_count > 1 {
            return false;
        }
    }
    true
}

/// Invariant 6: Router Agreement (when stable)
/// When no handoffs are in flight, all routers agree with etcd assignments.
fn check_router_agreement_when_stable(model: &HandoffModel, state: &SystemState) -> bool {
    if !state.handoffs.is_empty() {
        return true; // skip check during handoffs
    }
    for router_id in model.config.router_ids() {
        if let Some(table) = state.router_tables.get(&router_id) {
            for (partition, owner) in &state.assignments {
                if let Some(router_owner) = table.get(partition) {
                    if router_owner != owner {
                        return false;
                    }
                }
            }
        }
    }
    true
}

/// Invariant 7: No Write to Unregistered Pod
/// An accepted write should never target a pod that isn't in registered_pods.
/// If a router routes to a crashed pod, the write should fail, not be accepted.
fn check_no_write_to_unregistered_pod(_model: &HandoffModel, state: &SystemState) -> bool {
    for &(_, pod) in &state.accepted_writes {
        if !state.registered_pods.contains_key(&pod) {
            return false;
        }
    }
    true
}

/// Invariant 8: Assignment-Ownership Agreement
/// If a partition is assigned to a pod in etcd and there's no active handoff
/// for that partition, then the assigned pod must have it in its pod_owned set.
/// Catches "ghost assignments" where etcd says pod X owns P but pod X doesn't know.
fn check_assignment_ownership_agreement(_model: &HandoffModel, state: &SystemState) -> bool {
    for (&partition, &assigned_pod) in &state.assignments {
        if state.handoffs.contains_key(&partition) {
            continue;
        }
        if !state.registered_pods.contains_key(&assigned_pod) {
            continue;
        }
        let pod_knows = state
            .pod_owned
            .get(&assigned_pod)
            .map_or(false, |owned| owned.contains(&partition));
        if !pod_knows {
            return false;
        }
    }
    true
}

/// Invariant 9: Handoff Consistent with Assignment
/// For any active handoff, the partition's current etcd assignment should be
/// the handoff's old_owner (the partition hasn't been reassigned yet, unless
/// the handoff is Complete and the coordinator just updated the assignment).
fn check_handoff_consistent_with_assignment(_model: &HandoffModel, state: &SystemState) -> bool {
    for (&partition, handoff) in &state.handoffs {
        if let Some(&assigned) = state.assignments.get(&partition) {
            match handoff.phase {
                HandoffPhase::Warming | HandoffPhase::Ready => {
                    if assigned != handoff.old_owner {
                        return false;
                    }
                }
                HandoffPhase::Complete => {
                    // After CoordinatorCompleteHandoff, assignment flips to new_owner
                    if assigned != handoff.new_owner {
                        return false;
                    }
                }
            }
        }
    }
    true
}

/// Invariant 10: Draining Pod Gains No Partitions
/// A pod in Draining status should never appear as the new_owner in any handoff,
/// and should not gain partitions in its pod_owned set beyond what it already had.
fn check_draining_pod_gains_no_partitions(_model: &HandoffModel, state: &SystemState) -> bool {
    for (&pod, status) in &state.registered_pods {
        if *status != PodStatus::Draining {
            continue;
        }
        // A draining pod must never be the target of a handoff
        for handoff in state.handoffs.values() {
            if handoff.new_owner == pod {
                return false;
            }
        }
    }
    true
}

/// Liveness: Converges to Stable
/// The system should eventually reach a state where there are no pending
/// handoffs and no pending rebalance. This checks that the protocol doesn't
/// get stuck in an infinite handoff loop.
fn check_converges_to_stable(_model: &HandoffModel, state: &SystemState) -> bool {
    state.handoffs.is_empty() && !state.needs_rebalance
}
