//! Stateright `Model` for the personhog partition handoff protocol.
//!
//! Each action's transition logic mirrors a specific production code path
//! (named in comments) so a divergence between model and code is
//! reviewable line by line. The checker exhaustively interleaves every
//! action from every reachable state and verifies the properties at each.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use personhog_coordination::pod::{desired_state, DesiredState};
use personhog_coordination::protocol::{
    drain_satisfied, freeze_quorum_met, plan_rebalance, warm_satisfied,
};
use personhog_coordination::strategy::{AssignmentStrategy, StickyBalancedStrategy};
use personhog_coordination::types::{
    AssignmentStatus, HandoffState, PartitionAssignment, PodDrainedAck, PodStatus, PodWarmedAck,
    RegisteredPod, RegisteredRouter, RouterFreezeAck,
};
use stateright::{Model, Property};

use crate::types::{
    Action, Changelog, Handoff, Partition, Phase, Pod, PodId, Router, RouterId, StashedRequest,
    SystemState, WarmState,
};

/// Deterministic names bridging the model's compact u8 ids to the
/// string-keyed production types.
fn pod_name(x: PodId) -> String {
    format!("p{x}")
}
fn pod_id(name: &str) -> PodId {
    name.trim_start_matches('p').parse().expect("pod name")
}
fn router_name(r: RouterId) -> String {
    format!("r{r}")
}

/// Materialize the production `HandoffState` view of a model handoff, so
/// shared production functions can be called on checker state.
fn production_handoff(p: Partition, h: &Handoff) -> HandoffState {
    HandoffState {
        partition: p as u32,
        old_owner: h.old_owner.map(pod_name),
        new_owner: pod_name(h.new_owner),
        phase: h.phase,
        started_at: 0,
        handoff_id: h.id.to_string(),
    }
}

/// Which produce-path protection the model runs with.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Variant {
    /// The shipped protocol: leases + self-fencing bound the zombie
    /// window but nothing rejects a zombie's produce at the broker.
    Current,
    /// The proposed fix: per-partition Kafka transactional producers.
    /// Warming bumps the broker's producer epoch (`init_transactions`),
    /// and the broker rejects produces bearing a stale epoch.
    EpochFenced,
}

/// Model parameters. Small numbers — state spaces explode; protocol bugs
/// are structural and show up at minimum viable scale.
#[derive(Clone, Debug)]
pub struct HandoffModel {
    pub pods: u8,
    pub routers: u8,
    pub partitions: u8,
    pub variant: Variant,
    /// Total client writes the checker may inject.
    pub writes: u8,
    /// Total strong reads the checker may inject.
    pub reads: u8,
    /// Total failure events (crash-restarts + lease expiries).
    pub crashes: u8,
    /// Times a dead pod may rejoin under its old name.
    pub rejoins: u8,
    /// Writes a lease-expired pod may still accept before its keepalive
    /// self-fences it. Zero disables the zombie window entirely.
    pub zombie_window: u8,
    /// Adds reachability probes (`sometimes` properties) for scenario
    /// shapes that only exist at larger scale — used to measure, rather
    /// than assume, which configurations actually reach them. Off in the
    /// verdict tests: an unreached probe would fail `assert_properties`.
    pub probes: bool,
}

/// Derive one pod's desired state by calling the production
/// `pod::desired_state` on production-typed views of the checker state —
/// the model checks the exact function production executes.
fn model_desired_state(pod: PodId, state: &SystemState, partition: Partition) -> DesiredState {
    let assignment = state
        .assignments
        .get(&partition)
        .map(|owner| PartitionAssignment {
            partition: partition as u32,
            owner: pod_name(*owner),
            status: AssignmentStatus::Active,
        });
    let handoff = state
        .handoffs
        .get(&partition)
        .map(|h| production_handoff(partition, h));
    desired_state(&pod_name(pod), assignment.as_ref(), handoff.as_ref())
}

impl HandoffModel {
    fn pod_ids(&self) -> impl Iterator<Item = PodId> {
        0..self.pods
    }
    fn router_ids(&self) -> impl Iterator<Item = RouterId> {
        0..self.routers
    }
    fn partition_ids(&self) -> impl Iterator<Item = Partition> {
        0..self.partitions
    }

    /// The production `StickyBalancedStrategy`, called on
    /// production-typed views of the checker state — placement logic is
    /// single-sourced with the coordinator.
    fn target_assignments(&self, state: &SystemState) -> HashMap<u32, String> {
        let current: HashMap<u32, String> = state
            .assignments
            .iter()
            .map(|(p, owner)| (*p as u32, pod_name(*owner)))
            .collect();
        let mut active: Vec<String> = state
            .pods
            .iter()
            .filter(|(_, p)| p.registered)
            .map(|(id, _)| pod_name(*id))
            .collect();
        active.sort();
        StickyBalancedStrategy.compute_assignments(&current, &active, self.partitions as u32)
    }

    fn target_owner(&self, state: &SystemState, partition: Partition) -> Option<PodId> {
        self.target_assignments(state)
            .get(&(partition as u32))
            .map(|name| pod_id(name))
    }

    /// Whether pod `x` would accept a write for `partition` — the leader
    /// data plane's admission: process serving, partition warmed
    /// (`PartitionNotOwned` otherwise), not write-fenced (`try_begin`),
    /// and under `EpochFenced` the broker additionally rejects produces
    /// whose transactional epoch is stale.
    fn write_capable(&self, state: &SystemState, x: PodId, partition: Partition) -> bool {
        let pod = &state.pods[&x];
        if !pod.running {
            return false;
        }
        // A zombie (lease lost, keepalive not yet fired) keeps serving
        // only within its bounded window.
        if !pod.registered && pod.zombie_writes_left == 0 {
            return false;
        }
        let Some(warm) = pod.warmed.get(&partition) else {
            return false;
        };
        if pod.fenced.contains(&partition) {
            return false;
        }
        match self.variant {
            Variant::Current => true,
            Variant::EpochFenced => warm.epoch == state.changelogs[&partition].epoch,
        }
    }

    /// Serve a strong read at pod `x`, if it can (running, partition
    /// warmed). Sets the staleness flag when the pod's visible prefix
    /// (warm cutoff + own accepted writes) is behind the changelog — the
    /// read returned state missing at least one acked write. Returns
    /// whether the read was served.
    fn serve_read(&self, state: &mut SystemState, x: PodId, partition: Partition) -> bool {
        let pod = &state.pods[&x];
        if !pod.running {
            return false;
        }
        let Some(warm) = pod.warmed.get(&partition) else {
            return false;
        };
        let visible = warm.cutoff.saturating_add(warm.accepted);
        if visible < state.changelogs[&partition].len {
            state.stale_strong_read = true;
        }
        state.reads_served = state.reads_served.saturating_add(1);
        true
    }

    /// Append one acked write to the changelog, tracking the loss flag:
    /// if the protocol has designated a *different* pod as the (incoming
    /// or current) owner and that pod has already warmed, this write sits
    /// beyond its warm cutoff and is invisible to it forever.
    fn accept_write(&self, state: &mut SystemState, x: PodId, partition: Partition) {
        let designated_other = match state.handoffs.get(&partition) {
            Some(h) if h.new_owner != x => state.pods[&h.new_owner].warmed.contains_key(&partition),
            Some(_) => false,
            None => match state.assignments.get(&partition) {
                Some(owner) if *owner != x => state.pods[owner].warmed.contains_key(&partition),
                _ => false,
            },
        };
        if designated_other {
            state.lost_acked_write = true;
        }

        let log = state.changelogs.get_mut(&partition).unwrap();
        log.len = log.len.saturating_add(1);

        let pod = state.pods.get_mut(&x).unwrap();
        if let Some(warm) = pod.warmed.get_mut(&partition) {
            warm.accepted = warm.accepted.saturating_add(1);
        }
        if !pod.registered {
            pod.zombie_writes_left = pod.zombie_writes_left.saturating_sub(1);
        }
    }

    /// Route one write through router `r` exactly as the raw proxy does:
    /// park it if the partition is stashing, otherwise forward to the
    /// table entry and let the leader's admission decide.
    fn route_write(&self, state: &mut SystemState, r: RouterId, partition: Partition) -> bool {
        let router = &state.routers[&r];
        if !router.running {
            return false;
        }
        if router.stashing.contains(&partition) {
            let id = state.next_write_id;
            state.next_write_id += 1;
            state
                .routers
                .get_mut(&r)
                .unwrap()
                .stash
                .entry(partition)
                .or_default()
                .push(StashedRequest::Write(id));
            return true;
        }
        let Some(target) = router.table.get(&partition).copied() else {
            // No route: the request is rejected; nothing changes.
            return false;
        };
        if self.write_capable(state, target, partition) {
            self.accept_write(state, target, partition);
            true
        } else {
            // Rejected fail-closed at the leader; nothing changes.
            false
        }
    }
}

impl Model for HandoffModel {
    type State = SystemState;
    type Action = Action;

    fn init_states(&self) -> Vec<Self::State> {
        let pods: BTreeMap<PodId, Pod> = self
            .pod_ids()
            .map(|id| {
                (
                    id,
                    Pod {
                        registered: true,
                        running: true,
                        warmed: BTreeMap::new(),
                        fenced: BTreeSet::new(),
                        zombie_writes_left: 0,
                    },
                )
            })
            .collect();
        let routers: BTreeMap<RouterId, Router> = self
            .router_ids()
            .map(|id| {
                (
                    id,
                    Router {
                        registered: true,
                        running: true,
                        table: BTreeMap::new(),
                        stashing: BTreeSet::new(),
                        stash: BTreeMap::new(),
                    },
                )
            })
            .collect();
        let changelogs: BTreeMap<Partition, Changelog> = self
            .partition_ids()
            .map(|p| (p, Changelog::default()))
            .collect();

        vec![SystemState {
            assignments: BTreeMap::new(),
            handoffs: BTreeMap::new(),
            freeze_acks: BTreeMap::new(),
            drained_acks: BTreeMap::new(),
            warmed_acks: BTreeMap::new(),
            next_handoff_id: 0,
            pods,
            routers,
            changelogs,
            writes_left: self.writes,
            reads_left: self.reads,
            crashes_left: self.crashes,
            rejoins_left: self.rejoins,
            next_write_id: 0,
            reads_served: 0,
            lost_acked_write: false,
            stale_strong_read: false,
        }]
    }

    fn actions(&self, state: &Self::State, actions: &mut Vec<Self::Action>) {
        actions.push(Action::Rebalance);
        for p in self.partition_ids() {
            actions.push(Action::CleanupStale(p));
            actions.push(Action::AdvancePhase(p));
            actions.push(Action::CleanupComplete(p));
            for pod in self.pod_ids() {
                actions.push(Action::Converge(pod, p));
            }
            for r in self.router_ids() {
                actions.push(Action::Observe(r, p));
                if state.writes_left > 0 {
                    actions.push(Action::ClientWrite(r, p));
                }
                if state.reads_left > 0 {
                    actions.push(Action::ClientStrongRead(r, p));
                }
            }
        }
        if state.crashes_left > 0 {
            for pod in self.pod_ids() {
                actions.push(Action::CrashRestartWithinTtl(pod));
                actions.push(Action::LeaseExpire(pod));
            }
            for r in self.router_ids() {
                actions.push(Action::RouterLeaseExpire(r));
            }
        }
        for pod in self.pod_ids() {
            actions.push(Action::SelfFence(pod));
            if state.rejoins_left > 0 {
                actions.push(Action::Join(pod));
            }
        }
        for r in self.router_ids() {
            actions.push(Action::RouterSelfFence(r));
        }
    }

    fn next_state(&self, last: &Self::State, action: Self::Action) -> Option<Self::State> {
        let mut state = last.clone();
        match action {
            // ── coordinator ────────────────────────────────────
            // The cleanup half of `handle_pod_change_static` for one
            // partition. The mod_revision-guarded delete lets the model
            // treat check-and-delete as atomic; scheduling it freely
            // against Rebalance/AdvancePhase/CleanupComplete covers the
            // concurrency of the pod watch, handoff watch, tick, and an
            // overlapping outgoing coordinator.
            Action::CleanupStale(p) => {
                match state.handoffs.get(&p) {
                    Some(h) if !state.pods[&h.new_owner].registered => {}
                    _ => return None,
                }
                state.handoffs.remove(&p);
                state.freeze_acks.retain(|(fp, _), _| fp != &p);
                state.drained_acks.retain(|(dp, _), _| dp != &p);
                state.warmed_acks.retain(|(wp, _), _| wp != &p);
            }

            // The rebalance half: create Freezing handoffs for every
            // assignment diff in one transaction, only while no handoffs
            // are in flight. Placement and diff semantics are the
            // production `protocol::plan_rebalance` (strategy + move/fresh
            // diff, old_owner from the current assignment); only the etcd
            // writes are applied model-side, and assignments for
            // moved/fresh partitions are deferred until Complete
            // (`create_assignments_and_handoffs`).
            Action::Rebalance => {
                if state.handoffs.is_empty() {
                    let current: HashMap<u32, String> = state
                        .assignments
                        .iter()
                        .map(|(p, owner)| (*p as u32, pod_name(*owner)))
                        .collect();
                    let mut active: Vec<String> = state
                        .pods
                        .iter()
                        .filter(|(_, p)| p.registered)
                        .map(|(id, _)| pod_name(*id))
                        .collect();
                    active.sort();
                    let mut plan = plan_rebalance(
                        &StickyBalancedStrategy,
                        &current,
                        &active,
                        self.partitions as u32,
                    );
                    // The plan's order follows HashMap iteration; sort so
                    // sequential handoff-id assignment is deterministic
                    // (next_state must be a pure function of its inputs).
                    plan.handoffs.sort_by_key(|h| h.partition);
                    for planned in plan.handoffs {
                        let id = state.next_handoff_id;
                        state.next_handoff_id += 1;
                        state.handoffs.insert(
                            planned.partition as Partition,
                            Handoff {
                                id,
                                old_owner: planned.old_owner.as_deref().map(pod_id),
                                new_owner: pod_id(&planned.new_owner),
                                phase: Phase::Freezing,
                            },
                        );
                    }
                }
            }

            // Mirror of `check_phase_advance`, with the identity quorum
            // and handoff_id ack correlation.
            Action::AdvancePhase(p) => {
                let h = state.handoffs.get(&p).cloned()?;
                match h.phase {
                    Phase::Freezing => {
                        // The production quorum predicate on
                        // production-typed views: registered routers only
                        // (which is what admits the zombie-router half of
                        // the double-zombie residual), id-correlated acks,
                        // vacuous at zero routers.
                        let routers: Vec<RegisteredRouter> = self
                            .router_ids()
                            .filter(|r| state.routers[r].registered)
                            .map(|r| RegisteredRouter {
                                router_name: router_name(r),
                                registered_at: 0,
                                last_heartbeat: 0,
                            })
                            .collect();
                        let acks: Vec<RouterFreezeAck> = self
                            .router_ids()
                            .filter_map(|r| {
                                state.freeze_acks.get(&(p, r)).map(|id| RouterFreezeAck {
                                    router_name: router_name(r),
                                    partition: p as u32,
                                    acked_at: 0,
                                    handoff_id: id.to_string(),
                                })
                            })
                            .collect();
                        if !freeze_quorum_met(&routers, &acks, &production_handoff(p, &h)) {
                            return None;
                        }
                        // Initial assignments (no old owner) skip the
                        // drain entirely.
                        let next = match h.old_owner {
                            None => Phase::Warming,
                            Some(_) => Phase::Draining,
                        };
                        state.handoffs.get_mut(&p).unwrap().phase = next;
                    }
                    Phase::Draining => {
                        let registered: Vec<RegisteredPod> = self
                            .pod_ids()
                            .filter(|x| state.pods[x].registered)
                            .map(|x| RegisteredPod {
                                pod_name: pod_name(x),
                                generation: String::new(),
                                status: PodStatus::Ready,
                                registered_at: 0,
                                last_heartbeat: 0,
                                controller: None,
                            })
                            .collect();
                        let acks: Vec<PodDrainedAck> = self
                            .pod_ids()
                            .filter_map(|x| {
                                state.drained_acks.get(&(p, x)).map(|id| PodDrainedAck {
                                    pod_name: pod_name(x),
                                    partition: p as u32,
                                    acked_at: 0,
                                    handoff_id: id.to_string(),
                                })
                            })
                            .collect();
                        if !drain_satisfied(&registered, &acks, &production_handoff(p, &h)) {
                            return None;
                        }
                        state.handoffs.get_mut(&p).unwrap().phase = Phase::Warming;
                    }
                    Phase::Warming => {
                        let acks: Vec<PodWarmedAck> = self
                            .pod_ids()
                            .filter_map(|x| {
                                state.warmed_acks.get(&(p, x)).map(|id| PodWarmedAck {
                                    pod_name: pod_name(x),
                                    partition: p as u32,
                                    acked_at: 0,
                                    handoff_id: id.to_string(),
                                })
                            })
                            .collect();
                        if !warm_satisfied(&acks, &production_handoff(p, &h)) {
                            return None;
                        }
                        // `complete_handoff`: phase write and assignment
                        // flip are one etcd transaction.
                        state.handoffs.get_mut(&p).unwrap().phase = Phase::Complete;
                        state.assignments.insert(p, h.new_owner);
                    }
                    Phase::Complete => return None,
                }
            }

            // Mirror of the Complete arm of `handle_handoff_update_static`
            // (guarded delete of the record and its acks).
            Action::CleanupComplete(p) => {
                match state.handoffs.get(&p) {
                    Some(h) if h.phase == Phase::Complete => {}
                    _ => return None,
                }
                state.handoffs.remove(&p);
                state.freeze_acks.retain(|(fp, _), _| fp != &p);
                state.drained_acks.retain(|(dp, _), _| dp != &p);
                state.warmed_acks.retain(|(wp, _), _| wp != &p);
            }

            // ── pod converge ───────────────────────────────────
            // Mirror of `PodHandle::apply` — one idempotent transition
            // toward the desired state. Startup reconcile after a crash
            // is these same actions running against wiped local state.
            Action::Converge(x, p) => {
                let pod = &state.pods[&x];
                if !pod.running || !pod.registered {
                    return None;
                }
                match model_desired_state(x, &state, p) {
                    DesiredState::Serving => {
                        let pod = &state.pods[&x];
                        if !pod.warmed.contains_key(&p) {
                            // `warm_partition`: atomic install at the
                            // current HWM; unfences. Under EpochFenced,
                            // warming is also `init_transactions`, which
                            // bumps the broker epoch and fences every
                            // earlier producer for the partition.
                            let warm = {
                                let log = state.changelogs.get_mut(&p).unwrap();
                                if self.variant == Variant::EpochFenced {
                                    log.epoch = log.epoch.wrapping_add(1);
                                }
                                WarmState {
                                    epoch: log.epoch,
                                    cutoff: log.len,
                                    accepted: 0,
                                }
                            };
                            let pod = state.pods.get_mut(&x).unwrap();
                            pod.warmed.insert(p, warm);
                            pod.fenced.remove(&p);
                        } else if pod.fenced.contains(&p) {
                            // `resume_partition`.
                            state.pods.get_mut(&x).unwrap().fenced.remove(&p);
                        } else {
                            return None;
                        }
                    }
                    DesiredState::Drained { ack } => {
                        let h_id = state.handoffs[&p].id;
                        let pod = state.pods.get_mut(&x).unwrap();
                        let newly_fenced = pod.fenced.insert(p);
                        // `put_drained_ack`, only while the phase is
                        // Draining, echoing the handoff id.
                        let ack_needed = ack && state.drained_acks.get(&(p, x)) != Some(&h_id);
                        if ack_needed {
                            state.drained_acks.insert((p, x), h_id);
                        }
                        if !newly_fenced && !ack_needed {
                            return None;
                        }
                    }
                    DesiredState::Acquiring => {
                        let h_id = state.handoffs[&p].id;
                        let mut changed = false;
                        if !state.pods[&x].warmed.contains_key(&p) {
                            let warm = {
                                let log = state.changelogs.get_mut(&p).unwrap();
                                if self.variant == Variant::EpochFenced {
                                    log.epoch = log.epoch.wrapping_add(1);
                                }
                                WarmState {
                                    epoch: log.epoch,
                                    cutoff: log.len,
                                    accepted: 0,
                                }
                            };
                            let pod = state.pods.get_mut(&x).unwrap();
                            pod.warmed.insert(p, warm);
                            pod.fenced.remove(&p);
                            changed = true;
                        }
                        // `put_warmed_ack`, echoing the handoff id.
                        if state.warmed_acks.get(&(p, x)) != Some(&h_id) {
                            state.warmed_acks.insert((p, x), h_id);
                            changed = true;
                        }
                        if !changed {
                            return None;
                        }
                    }
                    DesiredState::Released => {
                        let pod = state.pods.get_mut(&x).unwrap();
                        let held = pod.warmed.remove(&p).is_some();
                        let fenced = pod.fenced.remove(&p);
                        if !held && !fenced {
                            return None;
                        }
                    }
                }
            }

            // ── router ─────────────────────────────────────────
            // Mirror of the routing-table watch handler + stash handler.
            // The router acts on the CURRENT durable state — the same
            // semantics its event handlers converge to, since a late
            // router processes events up to the present (load_initial /
            // anchored watches guarantee it misses nothing).
            Action::Observe(r, p) => {
                {
                    let router = &state.routers[&r];
                    if !router.registered || !router.running {
                        return None;
                    }
                }
                let mut changed = false;
                match state.handoffs.get(&p).cloned() {
                    Some(h) if h.phase != Phase::Complete => {
                        // begin_stash on every non-terminal phase;
                        // FreezeAck only while Freezing, echoing the id.
                        if state.routers.get_mut(&r).unwrap().stashing.insert(p) {
                            changed = true;
                        }
                        if h.phase == Phase::Freezing
                            && state.freeze_acks.get(&(p, r)) != Some(&h.id)
                        {
                            state.freeze_acks.insert((p, r), h.id);
                            changed = true;
                        }
                    }
                    Some(h) => {
                        // Complete: cutover the table, then drain the
                        // stash to the new owner in FIFO order.
                        let router = state.routers.get_mut(&r).unwrap();
                        if router.table.get(&p) != Some(&h.new_owner) {
                            router.table.insert(p, h.new_owner);
                            changed = true;
                        }
                        if router.stashing.remove(&p) {
                            changed = true;
                        }
                        let parked = state
                            .routers
                            .get_mut(&r)
                            .unwrap()
                            .stash
                            .remove(&p)
                            .unwrap_or_default();
                        for entry in parked {
                            changed = true;
                            match entry {
                                StashedRequest::Write(_) => {
                                    if self.write_capable(&state, h.new_owner, p) {
                                        self.accept_write(&mut state, h.new_owner, p);
                                    }
                                    // Rejected drains surface UNAVAILABLE
                                    // to the client (never acked).
                                }
                                StashedRequest::StrongRead => {
                                    self.serve_read(&mut state, h.new_owner, p);
                                }
                            }
                        }
                    }
                    None => {
                        // No handoff: converge the table to the
                        // assignment; a cancellation drains the stash
                        // back to the assignment owner.
                        let assignment = state.assignments.get(&p).copied();
                        let router = state.routers.get_mut(&r).unwrap();
                        match assignment {
                            Some(owner) => {
                                if router.table.get(&p) != Some(&owner) {
                                    router.table.insert(p, owner);
                                    changed = true;
                                }
                            }
                            None => {
                                if router.table.remove(&p).is_some() {
                                    changed = true;
                                }
                            }
                        }
                        if router.stashing.remove(&p) {
                            changed = true;
                        }
                        let parked = state
                            .routers
                            .get_mut(&r)
                            .unwrap()
                            .stash
                            .remove(&p)
                            .unwrap_or_default();
                        for entry in parked {
                            changed = true;
                            let Some(owner) = assignment else { continue };
                            match entry {
                                StashedRequest::Write(_) => {
                                    if self.write_capable(&state, owner, p) {
                                        self.accept_write(&mut state, owner, p);
                                    }
                                }
                                StashedRequest::StrongRead => {
                                    self.serve_read(&mut state, owner, p);
                                }
                            }
                        }
                    }
                }
                if !changed {
                    return None;
                }
            }

            // ── workload ───────────────────────────────────────
            Action::ClientWrite(r, p) => {
                if state.writes_left == 0 {
                    return None;
                }
                state.writes_left -= 1;
                if !self.route_write(&mut state, r, p) {
                    // The write was rejected everywhere — the state may
                    // still have changed (budget), keep the transition
                    // so rejected paths are explored too.
                }
            }

            Action::ClientStrongRead(r, p) => {
                if state.reads_left == 0 {
                    return None;
                }
                state.reads_left -= 1;
                let router = &state.routers[&r];
                if !router.running {
                    // Router process gone; request fails at the client.
                } else if router.stashing.contains(&p) {
                    // Strong reads park in the same per-partition FIFO as
                    // writes while the partition is stashing (the shipped
                    // read-stashing design, #69456) — which is what keeps
                    // them complete across cutover.
                    state
                        .routers
                        .get_mut(&r)
                        .unwrap()
                        .stash
                        .entry(p)
                        .or_default()
                        .push(StashedRequest::StrongRead);
                } else if let Some(target) = router.table.get(&p).copied() {
                    // Outside a handoff: forward to the table entry.
                    // Rejected reads fail closed at the leader.
                    self.serve_read(&mut state, target, p);
                }
            }

            // ── failures ───────────────────────────────────────
            Action::Join(x) => {
                let pod = &state.pods[&x];
                if state.rejoins_left == 0 || pod.registered || pod.running {
                    return None;
                }
                state.rejoins_left -= 1;
                let pod = state.pods.get_mut(&x).unwrap();
                pod.registered = true;
                pod.running = true;
                pod.warmed.clear();
                pod.fenced.clear();
                pod.zombie_writes_left = 0;
            }
            Action::CrashRestartWithinTtl(x) => {
                let pod = &state.pods[&x];
                if state.crashes_left == 0 || !pod.running || !pod.registered {
                    return None;
                }
                state.crashes_left -= 1;
                let pod = state.pods.get_mut(&x).unwrap();
                pod.warmed.clear();
                pod.fenced.clear();
            }
            Action::LeaseExpire(x) => {
                let pod = &state.pods[&x];
                if state.crashes_left == 0 || !pod.registered {
                    return None;
                }
                state.crashes_left -= 1;
                let zombie_window = self.zombie_window;
                let pod = state.pods.get_mut(&x).unwrap();
                pod.registered = false;
                if pod.running {
                    pod.zombie_writes_left = zombie_window;
                }
            }
            Action::SelfFence(x) => {
                let pod = &state.pods[&x];
                if pod.registered || !pod.running {
                    return None;
                }
                let pod = state.pods.get_mut(&x).unwrap();
                pod.running = false;
                pod.warmed.clear();
                pod.fenced.clear();
                pod.zombie_writes_left = 0;
            }
            Action::RouterLeaseExpire(r) => {
                if state.crashes_left == 0 || !state.routers[&r].registered {
                    return None;
                }
                state.crashes_left -= 1;
                state.routers.get_mut(&r).unwrap().registered = false;
            }
            Action::RouterSelfFence(r) => {
                let router = &state.routers[&r];
                if router.registered || !router.running {
                    return None;
                }
                // The process exits; parked stash requests die with it
                // (their clients get errors — the writes were never
                // acked).
                let router = state.routers.get_mut(&r).unwrap();
                router.running = false;
                router.stashing.clear();
                router.stash.clear();
            }
        }

        if state == *last {
            return None;
        }
        Some(state)
    }

    fn properties(&self) -> Vec<Property<Self>> {
        let mut props = vec![
            // The acked-write-loss invariant the drain/fence/HWM
            // machinery exists to uphold. Expected to FAIL under
            // Variant::Current with a zombie window (the documented
            // residual) and PASS under Variant::EpochFenced.
            Property::<Self>::always("no_lost_acked_write", |_, s| !s.lost_acked_write),
            // The split-brain condition: two distinct pods each capable
            // of accepting a write for the same partition AND each
            // reachable by some live, non-stashing router. Capability
            // alone is not enough — a zombie pod behind a fully-stashing
            // router fleet can accept nothing, which is exactly why a
            // single zombie is safe and only the double zombie violates
            // this.
            Property::<Self>::always("no_split_write_acceptance", |m, s| {
                m.partition_ids().all(|p| {
                    let acceptors: BTreeSet<_> = m
                        .router_ids()
                        .filter_map(|r| {
                            let router = &s.routers[&r];
                            if !router.running || router.stashing.contains(&p) {
                                return None;
                            }
                            router.table.get(&p).copied()
                        })
                        .filter(|x| m.write_capable(s, *x, p))
                        .collect();
                    acceptors.len() <= 1
                })
            }),
            // A pod that has written a DrainedAck for the current
            // handoff attempt never accepts another write for that
            // partition in the same process incarnation (the ack asserts
            // all its acked writes are durable below the warm HWM).
            Property::<Self>::always("drained_ack_is_final", |m, s| {
                s.drained_acks.iter().all(|((p, x), id)| {
                    match s.handoffs.get(p) {
                        Some(h) if h.id == *id => !m.write_capable(s, *x, *p),
                        // Ack belongs to a finished/cancelled attempt —
                        // correlation makes it inert.
                        _ => true,
                    }
                })
            }),
            // Strong reads reflect every acked write at serve time.
            // This holds because reads stash with writes during handoffs
            // (#69456); before that change, a direct-read variant of this
            // model found the cutover race as a counterexample — the
            // machine validation that motivated shipping read stashing.
            Property::<Self>::always("strong_reads_complete", |_, s| !s.stale_strong_read),
            // Sanity: the interesting states are actually reachable.
            Property::<Self>::sometimes("some_handoff_completes", |_, s| {
                s.handoffs.values().any(|h| h.phase == Phase::Complete)
            }),
            Property::<Self>::sometimes("some_write_accepted", |_, s| {
                s.changelogs.values().any(|log| log.len > 0)
            }),
            Property::<Self>::sometimes("some_strong_read_served", |m, s| {
                // Vacuously discoverable in configs without reads, so
                // `assert_properties` stays usable across the matrix.
                m.reads == 0 || s.reads_served > 0
            }),
            // Liveness: every full run ends quiescent and converged —
            // no handoffs in flight, every assignment served by a warm,
            // unfenced, registered pod, all routers agreeing, nothing
            // parked in a stash.
            Property::<Self>::eventually("converges_to_stable", |m, s| {
                let no_capacity = s.pods.values().all(|p| !p.registered);
                s.handoffs.is_empty()
                    && (no_capacity
                        || (!s.assignments.is_empty()
                            && m.partition_ids().all(|p| {
                                let Some(target) = m.target_owner(s, p) else {
                                    return true;
                                };
                                let assigned = s.assignments.get(&p) == Some(&target);
                                let pod = &s.pods[&target];
                                assigned
                                    && pod.running
                                    && pod.registered
                                    && pod.warmed.contains_key(&p)
                                    && !pod.fenced.contains(&p)
                            })))
                    && m.router_ids().all(|r| {
                        let router = &s.routers[&r];
                        if !router.registered || !router.running {
                            return true;
                        }
                        router.stashing.is_empty()
                            && router.stash.values().all(|q| q.is_empty())
                            && s.assignments
                                .iter()
                                .all(|(p, owner)| router.table.get(p) == Some(owner))
                    })
            }),
        ];
        if self.probes {
            // Two or more handoffs in flight at once (one rebalance txn
            // creates them all; the deferral gate prevents a second
            // rebalance from adding more).
            props.push(Property::<Self>::sometimes(
                "concurrent_handoffs",
                |_, s| s.handoffs.len() >= 2,
            ));
            // A pod that is old owner of one in-flight handoff and new
            // owner of another — simultaneously drain-side and warm-side.
            // Believed unreachable under the shipped protocol: within one
            // plan the sticky strategy only takes partitions from pods
            // above their target and gives to pods below it (never both),
            // and the deferral gate keeps handoffs from different plans
            // from coexisting. The probe lets the checker confirm that
            // instead of us assuming it.
            props.push(Property::<Self>::sometimes(
                "pod_holds_both_roles",
                |_, s| {
                    s.handoffs.values().any(|h1| {
                        h1.old_owner
                            .is_some_and(|x| s.handoffs.values().any(|h2| h2.new_owner == x))
                    })
                },
            ));
        }
        props
    }
}
