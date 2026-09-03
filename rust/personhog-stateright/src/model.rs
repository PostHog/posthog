//! Stateright `Model` for the personhog partition handoff protocol.
//!
//! Each action's transition logic mirrors a specific production code path
//! (named in comments) so a divergence between model and code is
//! reviewable line by line. The checker exhaustively interleaves every
//! action from every reachable state and verifies the properties at each.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use personhog_coordination::pod::{desired_state, DesiredState};
use personhog_coordination::protocol::{
    drain_satisfied, freeze_quorum_met, plan_partial_rebalance, warm_satisfied, PlannedHandoff,
};
use personhog_coordination::strategy::{AssignmentStrategy, Member, StickyBalancedStrategy};
use personhog_coordination::types::{
    AssignmentStatus, HandoffState, PartitionAssignment, PodDrainedAck, PodStatus, PodWarmedAck,
    RegisteredPod, RegisteredRouter, RouterFreezeAck,
};
use stateright::{Model, Property};

use crate::types::{
    Action, Changelog, Handoff, HandoffId, Partition, PendingUnit, PendingWarm, Phase, Pod, PodId,
    Router, RouterId, StashedRequest, SystemState, WarmState,
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
        // The model verifies ownership/fencing; addresses are transport
        // detail outside its state space.
        new_owner_address: None,
        phase: h.phase,
        started_at: 0,
        handoff_id: h.id.to_string(),
        // Membership lives beside the record in production, so the
        // record carries neither form. `production_quorum` supplies it
        // to the predicates that need it.
        freeze_quorum: None,
        freeze_quorum_ref: None,
        created_at_ms: 0,
        phase_entered_at_ms: 0,
    }
}

/// The membership a model handoff was created with, in the form the
/// production quorum predicates take. The model always captures a
/// snapshot; the production `None` fallback is a serialization concern
/// pinned by unit tests, not a reachable state here. `RouterJoin` makes
/// the snapshot diverge from the live registry, which is what exercises
/// the predicate.
fn production_quorum(h: &Handoff) -> Vec<String> {
    h.quorum.iter().map(|r| router_name(*r)).collect()
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

/// How promptly a pod learns that its lease is gone.
///
/// The keepalive only finds out on its next round, so a revoked lease
/// leaves the pod claiming a partition the coordinator can already have
/// reassigned. Production closes that by watching its own registration;
/// `Delayed` is what the window looks like without it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ClaimDetection {
    /// The registration watch: the claim drops with the registration.
    Prompt,
    /// Keepalive-only: the claim outlives the registration until a later
    /// round notices, which the checker explores as a separate step.
    Delayed,
}

/// Which side of the warm read acquires the broker fence, under
/// `Variant::EpochFenced`. `warm_partition` ships `FenceFirst`;
/// `ReadFirst` is the rejected ordering, kept checkable as the machine
/// record of why the fence must precede the read.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WarmOrder {
    FenceFirst,
    ReadFirst,
}

/// Model parameters. Small numbers — state spaces explode; protocol bugs
/// are structural and show up at minimum viable scale.
#[derive(Clone, Debug)]
pub struct HandoffModel {
    pub pods: u8,
    pub routers: u8,
    /// Additional router slots that start unregistered and not running;
    /// they exist only to `RouterJoin` mid-run.
    pub late_routers: u8,
    pub partitions: u8,
    pub variant: Variant,
    /// Fence-vs-read ordering of the decomposed warm; ignored under
    /// `Variant::Current`, whose warm is a single atomic step.
    pub warm_order: WarmOrder,
    /// How promptly a pod notices its lease is gone; only meaningful
    /// with `lease_gated_reads`, since nothing else consults the claim.
    pub claim_detection: ClaimDetection,
    /// Whether a pod consults its lease before serving a strong read
    /// (production: the leader's `LEASE_GATED_AUTHORITY`). Without it a
    /// pod that has lost its registration keeps answering out of a cache
    /// the new owner is already changing.
    pub lease_gated_reads: bool,
    /// Whether a lapsed claim can come back without the session ending
    /// (production: the keepalive confirming a renewal again). Turning it
    /// off is what makes the black hole permanent, which is the only way
    /// to show that stability actually notices one.
    pub claim_recovers: bool,
    /// Total client writes the checker may inject.
    pub writes: u8,
    /// Total strong reads the checker may inject.
    pub reads: u8,
    /// Total failure events (crash-restarts + lease expiries).
    pub crashes: u8,
    /// Total deadline cancellations the checker may inject.
    pub cancels: u8,
    /// Times a dead pod may rejoin under its old name.
    pub rejoins: u8,
    /// Times a router may (re)join: late slots coming up, or dead
    /// routers returning as fresh processes.
    pub router_joins: u8,
    /// Writes a lease-expired pod may still accept before its keepalive
    /// self-fences it. Zero disables the zombie window entirely.
    pub zombie_window: u8,
    /// Pods below this id form a departing generation for the planner:
    /// they are Hold members, and every other pod is capped at its final
    /// share (the coordinator's rollout policies). Zero models the
    /// steady state, where every pod is an uncapped active member.
    pub hold_pods: u8,
    /// Apply rebalance plans in chunks (production: `apply_plan` past
    /// the txn budget): the first planned handoff lands with the plan,
    /// the rest apply later through `ApplyPendingUnit`.
    pub chunked_plans: bool,
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
            advertise_address: None,
            status: AssignmentStatus::Active,
        });
    let handoff = state
        .handoffs
        .get(&partition)
        .map(|h| production_handoff(partition, h));
    desired_state(&pod_name(pod), assignment.as_ref(), handoff.as_ref())
}

impl HandoffModel {
    // Whether each cancellation-reachability probe can reach its shape in
    // this configuration, and therefore whether its evidence flag is worth
    // recording.
    //
    // The flags are sticky, so recording one in a configuration whose probe
    // can never read it is pure cost: every state that sets it roots a
    // duplicate of the subtree beneath it, and most configurations set
    // `cancels` to zero while still reaching `CancelDeadNewOwner`, which is
    // unbudgeted. Each predicate below is used by both the `properties`
    // probe and the `cancel_by_replacement` arm that feeds it, so the two
    // cannot drift apart — and under-recording fails loudly rather than
    // quietly, since the `sometimes` probe then finds no discovery and
    // `assert_properties` panics.
    fn probes_reaffirm(&self) -> bool {
        // A reaffirm needs a move handoff whose old owner is alive, which
        // takes a crash and a rejoin to manufacture.
        self.cancels > 0 && self.rejoins > 0
    }
    fn probes_successor_replacement(&self) -> bool {
        self.cancels > 0
    }
    fn probes_stash_racing_cancellation(&self) -> bool {
        self.cancels > 0 && self.writes > 0
    }

    fn pod_ids(&self) -> impl Iterator<Item = PodId> {
        0..self.pods
    }
    fn router_ids(&self) -> impl Iterator<Item = RouterId> {
        0..(self.routers + self.late_routers)
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
        let members = self.planner_members(state);
        StickyBalancedStrategy.compute_assignments(&current, &members, self.partitions as u32)
    }

    /// Planner membership with the model's placement policies applied —
    /// shared by target computation and rebalance planning so every
    /// property judges the same placement mode.
    fn planner_members(&self, state: &SystemState) -> Vec<Member> {
        let mut ids: Vec<PodId> = state
            .pods
            .iter()
            .filter(|(_, p)| p.registered)
            .map(|(id, _)| *id)
            .collect();
        ids.sort();
        if self.hold_pods == 0 {
            return ids
                .into_iter()
                .map(|id| Member::active(pod_name(id)))
                .collect();
        }
        // The cap mirrors the coordinator's: total over the incoming
        // fleet's *desired* size, not its live count, so a crashed
        // incoming pod does not inflate its peers' quota.
        let incoming = self.pods.saturating_sub(self.hold_pods).max(1);
        let cap = (self.partitions as u32).div_ceil(incoming as u32);
        ids.into_iter()
            .map(|id| {
                if id < self.hold_pods {
                    Member::hold(pod_name(id))
                } else {
                    Member::active_capped(pod_name(id), cap)
                }
            })
            .collect()
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
        if !pod.warmed.contains_key(&partition) {
            return false;
        }
        if pod.fenced.contains(&partition) {
            return false;
        }
        match self.variant {
            Variant::Current => true,
            // The broker accepts one producer per partition — whichever
            // acquired the fence most recently. A warmed pod that is no
            // longer the holder would be producing under a fenced-out
            // producer, and the broker rejects it before any client ack.
            Variant::EpochFenced => state.changelogs[&partition].epoch_holder == Some(x),
        }
    }

    /// One step of `warm_partition` for pod `x` on `partition`. Under
    /// `Current` the warm is a single atomic install — there is no
    /// broker step to separate from the read. Under `EpochFenced` it is
    /// two steps whose order is `self.warm_order`, with the in-between
    /// state held in `pending_warm` so the checker interleaves every
    /// other action against the gap.
    fn warm_step(
        &self,
        state: &mut SystemState,
        x: PodId,
        partition: Partition,
        for_handoff: Option<HandoffId>,
    ) {
        // Both orderings are two steps in production, but only one of
        // them is *observably* two steps. Acquiring the fence first bumps
        // the epoch before the read, and an append requires an installed
        // warm carrying the current epoch — which no pod has during the
        // gap, this one included. The changelog therefore cannot grow
        // between the two steps, so the cutoff read at acquire time and
        // at install time are the same value and no interleaving can tell
        // them apart. Collapsing that case keeps the state space at the
        // size it had before the decomposition; `ReadFirst`, where the
        // gap is the entire point, stays split.
        //
        // Be precise about what that buys: the checker *proves* ReadFirst
        // unsafe by exploring its gap, and never explores FenceFirst's —
        // FenceFirst's safety rests on the argument above, not on
        // enumeration. If the no-observable-gap argument ever stops
        // holding (an append path that does not require an installed
        // warm), this collapse is the assumption to revisit first.
        let observable_gap =
            self.variant == Variant::EpochFenced && self.warm_order == WarmOrder::ReadFirst;
        if !observable_gap {
            let warm = {
                let log = state.changelogs.get_mut(&partition).unwrap();
                if self.variant == Variant::EpochFenced {
                    log.epoch_holder = Some(x);
                }
                WarmState {
                    for_handoff,
                    visible: log.len,
                }
            };
            let pod = state.pods.get_mut(&x).unwrap();
            pod.warmed.insert(partition, warm);
            pod.fenced.remove(&partition);
            return;
        }
        match state.pods[&x].pending_warm.get(&partition).copied() {
            None => {
                // The rejected ordering: the changelog read runs to the
                // current HWM while the fence — and thus the rejection of
                // a zombie's write — does not exist yet.
                let pending = PendingWarm {
                    cutoff: state.changelogs[&partition].len,
                };
                state
                    .pods
                    .get_mut(&x)
                    .unwrap()
                    .pending_warm
                    .insert(partition, pending);
            }
            Some(PendingWarm { cutoff }) => {
                // The cutoff predates the fence: anything committed in
                // the gap sits beyond it, invisible forever.
                let warm = {
                    let log = state.changelogs.get_mut(&partition).unwrap();
                    log.epoch_holder = Some(x);
                    WarmState {
                        for_handoff,
                        visible: cutoff,
                    }
                };
                let pod = state.pods.get_mut(&x).unwrap();
                pod.pending_warm.remove(&partition);
                pod.warmed.insert(partition, warm);
                pod.fenced.remove(&partition);
            }
        }
    }

    /// Whether the handoff's new owner has fixed the cutoff it will
    /// serve with: a warm installed for *this* handoff, or a mid-warm
    /// read already taken (a pending warm always belongs to the current
    /// attempt — cancellation requires the target unregistered, which
    /// wipes its process memory). An earlier-era warm does NOT freeze
    /// the cutoff: the Acquiring convergence releases and rebuilds it.
    fn handoff_cutoff_frozen(
        &self,
        state: &SystemState,
        h: &Handoff,
        partition: Partition,
    ) -> bool {
        let pod = &state.pods[&h.new_owner];
        match pod.warmed.get(&partition) {
            Some(w) => w.for_handoff == Some(h.id),
            None => pod.pending_warm.contains_key(&partition),
        }
    }

    /// Whether the assignment owner has fixed its serving cutoff — the
    /// Serving convergence honors any installed warm (an owner's warm
    /// cannot go stale while ownership is continuous), so any warm or a
    /// taken mid-warm read freezes it.
    fn owner_cutoff_frozen(&self, state: &SystemState, x: PodId, partition: Partition) -> bool {
        let pod = &state.pods[&x];
        pod.warmed.contains_key(&partition) || pod.pending_warm.contains_key(&partition)
    }

    /// Serve a strong read at pod `x`, if it can (running, partition
    /// warmed). Sets the staleness flag when the pod's visible prefix is
    /// behind the changelog — the read returned state missing at least one
    /// acked write. Returns whether the read was served.
    fn serve_read(&self, state: &mut SystemState, x: PodId, partition: Partition) -> bool {
        let pod = &state.pods[&x];
        if !pod.running {
            return false;
        }
        // The read gate: a pod that no longer claims the partition
        // refuses rather than serving from a cache it cannot vouch for.
        // The claim is what production actually consults — a stamp the
        // keepalive publishes — and it is not the same fact as holding
        // the lease, which is the whole point of modeling it separately.
        //
        // Production refuses on a margin against the last confirmed
        // renewal, which is a *later*-firing predicate than this one in
        // the case where a lease is revoked between keepalive rounds:
        // the stamp stays fresh for up to a heartbeat after the
        // registration is gone. The model is therefore optimistic about
        // that window, and the property holding here does not cover it —
        // it is recorded as a residual in the coordination README rather
        // than claimed as closed.
        if self.lease_gated_reads && !pod.claims_authority {
            return false;
        }
        let Some(warm) = pod.warmed.get(&partition) else {
            return false;
        };
        if warm.visible < state.changelogs[&partition].len {
            state.stale_strong_read = true;
        }
        state.read_served = true;
        true
    }

    /// Append one acked write to the changelog, tracking the loss flag:
    /// if the protocol has designated a *different* pod as the (incoming
    /// or current) owner and that pod's warm cutoff is already fixed,
    /// this write sits beyond the cutoff and is invisible to it forever.
    fn accept_write(&self, state: &mut SystemState, x: PodId, partition: Partition) {
        let designated_other = match state.handoffs.get(&partition) {
            Some(h) if h.new_owner != x => self.handoff_cutoff_frozen(state, h, partition),
            Some(_) => false,
            None => match state.assignments.get(&partition) {
                Some(owner) if *owner != x => self.owner_cutoff_frozen(state, *owner, partition),
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
            // Its own write is immediately visible to it.
            warm.visible = warm.visible.saturating_add(1);
        }
        if !pod.registered {
            pod.zombie_writes_left = pod.zombie_writes_left.saturating_sub(1);
        }
    }

    /// Cancel the in-flight handoff at `p` by atomic replacement — the
    /// single disposition rule production's planner applies on any
    /// cancellation trigger. The record is swapped, in one guarded
    /// transaction that also clears the predecessor's acks, for whatever
    /// resolves the routers' stashes:
    ///
    /// * current owner registered → a reaffirm: `Complete` toward that
    ///   owner, `old_owner: None`. Routers drain home through their
    ///   ordinary Complete handling; the owner pod re-derives `Serving`
    ///   and unfences. (`old_owner` must be `None` — naming the owner on
    ///   both sides would match `desired_state`'s old-owner arm first
    ///   and derive `Released`, making the pod drop the partition.)
    /// * otherwise, a placeable successor → a fresh `Freezing` handoff
    ///   toward the planner's target, new id, new quorum snapshot.
    ///   Routers keep stashing without ever observing a gap.
    /// * nothing placeable (owner dead, no registered pod) → plain
    ///   delete. Safe because stash disposal is derived from durable
    ///   state (`Observe`'s no-handoff arm drains to the assignment
    ///   owner, fail-closed), not decided on the deletion event.
    fn cancel_by_replacement(&self, state: &mut SystemState, p: Partition) {
        if self.probes_stash_racing_cancellation()
            && state
                .routers
                .values()
                .any(|r| r.stash.get(&p).is_some_and(|q| !q.is_empty()))
        {
            state.cancelled_while_stash_parked = true;
        }

        state.freeze_acks.retain(|(fp, _), _| fp != &p);
        state.drained_acks.retain(|(dp, _), _| dp != &p);
        state.warmed_acks.retain(|(wp, _), _| wp != &p);

        let owner = state.assignments.get(&p).copied();
        if let Some(owner) = owner.filter(|o| state.pods[o].registered) {
            let id = state.next_handoff_id;
            state.next_handoff_id += 1;
            state.handoffs.insert(
                p,
                Handoff {
                    id,
                    old_owner: None,
                    new_owner: owner,
                    phase: Phase::Complete,
                    quorum: BTreeSet::new(),
                },
            );
            if self.probes_reaffirm() {
                state.reaffirmed = true;
            }
            return;
        }
        if let Some(target) = self.target_owner(state, p) {
            let id = state.next_handoff_id;
            state.next_handoff_id += 1;
            let quorum: BTreeSet<RouterId> = self
                .router_ids()
                .filter(|r| state.routers[r].registered)
                .collect();
            state.handoffs.insert(
                p,
                Handoff {
                    id,
                    old_owner: owner,
                    new_owner: target,
                    phase: Phase::Freezing,
                    quorum,
                },
            );
            if self.probes_successor_replacement() {
                state.replaced_with_successor = true;
            }
            return;
        }
        state.handoffs.remove(&p);
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
            state
                .routers
                .get_mut(&r)
                .unwrap()
                .stash
                .entry(partition)
                .or_default()
                .push(StashedRequest::Write);
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

    /// Whether `action` can produce a successor from `state`.
    ///
    /// Every condition here is a precondition already required by the
    /// matching `next_state` arm, and this is the only place it is
    /// written: `actions` filters on it so the checker never asks for a
    /// transition that cannot happen, and `next_state` gates on it so the
    /// state clone is never paid for one. It carries only the cheap
    /// guards — it runs once per action per explored state, so anything
    /// that allocates or calls into the production planner is decided in
    /// the arm instead, still ahead of the clone.
    ///
    /// It must stay *exactly* as strict as those guards. Returning `false`
    /// where the arm would have produced a successor silently deletes
    /// behavior from the model; the review gate is that
    /// `unique_state_count` is unchanged.
    fn enabled(&self, state: &SystemState, action: &Action) -> bool {
        match *action {
            // Decided in the arm: enablement is "the planner produced a
            // non-empty plan", which costs a full placement computation.
            Action::Rebalance => true,
            // One pending suffix at a time: chunks of one plan apply
            // sequentially in production; a competing plan is the
            // Rebalance interleavings.
            Action::RebalanceChunked => self.chunked_plans && state.pending_plan.is_empty(),
            Action::ApplyPendingUnit => !state.pending_plan.is_empty(),

            Action::CancelDeadNewOwner(p) => matches!(
                state.handoffs.get(&p),
                Some(h) if h.phase != Phase::Complete && !state.pods[&h.new_owner].registered
            ),
            Action::Cancel(p) => {
                state.cancels_left > 0
                    && matches!(state.handoffs.get(&p), Some(h) if h.phase != Phase::Complete)
            }
            // The quorum/drain/warm predicates are the expensive half and
            // stay in the arm; a handoff short of Complete must exist.
            Action::AdvancePhase(p) => {
                matches!(state.handoffs.get(&p), Some(h) if h.phase != Phase::Complete)
            }
            Action::CleanupComplete(p) => {
                matches!(state.handoffs.get(&p), Some(h) if h.phase == Phase::Complete)
            }

            // Which transition a converging pod owes is `desired_state`'s
            // answer, derived in the arm; only a live, registered process
            // converges at all.
            Action::Converge(x, _) => {
                let pod = &state.pods[&x];
                pod.running && pod.registered
            }
            Action::Observe(r, _) => {
                let router = &state.routers[&r];
                router.registered && router.running
            }

            Action::ClientWrite(_, _) => state.writes_left > 0,
            Action::ClientStrongRead(_, _) => state.reads_left > 0,

            Action::CrashRestartWithinTtl(x) => {
                let pod = &state.pods[&x];
                state.crashes_left > 0 && pod.running && pod.registered
            }
            Action::LeaseExpire(x) => state.crashes_left > 0 && state.pods[&x].registered,
            Action::SelfFence(x) => {
                let pod = &state.pods[&x];
                !pod.registered && pod.running
            }
            Action::NoticeLeaseLoss(x) => {
                let pod = &state.pods[&x];
                !pod.registered && pod.claims_authority
            }
            Action::AuthorityLapse(x) => {
                let pod = &state.pods[&x];
                pod.registered && pod.claims_authority
            }
            Action::AuthorityRenew(x) => {
                let pod = &state.pods[&x];
                pod.registered && !pod.claims_authority
            }
            Action::Join(x) => {
                let pod = &state.pods[&x];
                state.rejoins_left > 0 && !pod.registered && !pod.running
            }
            Action::RouterLeaseExpire(r) => state.crashes_left > 0 && state.routers[&r].registered,
            Action::RouterSelfFence(r) => {
                let router = &state.routers[&r];
                !router.registered && router.running
            }
            Action::RouterJoin(r) => {
                let router = &state.routers[&r];
                state.router_joins_left > 0 && !router.registered && !router.running
            }
        }
    }
}

/// Clone-then-mutate for the arms whose enablement `enabled` already
/// settled: the clone is the last thing to happen before a successor
/// exists, and a mutation that changed nothing still collapses to `None`.
fn mutate(last: &SystemState, apply: impl FnOnce(&mut SystemState)) -> Option<SystemState> {
    let mut state = last.clone();
    apply(&mut state);
    (state != *last).then_some(state)
}

/// The four transitions whose enablement is too expensive to answer in
/// `enabled` — each derives it from `last` and clones only once a
/// successor is certain.
impl HandoffModel {
    /// The rebalance half of `handle_pod_change`, applied in one
    /// transition. In-flight handoffs pin their partitions
    /// (`plan_partial_rebalance`), so rebalancing is enabled in every
    /// state and races every handoff phase. Production guards each
    /// partition's unit on its read-set, so a stale unit stands down
    /// instead of clobbering an in-flight handoff; plans past the txn
    /// budget apply in chunks, which `rebalance_chunked` explores.
    fn rebalance(&self, last: &SystemState) -> Option<SystemState> {
        let (handoffs, quorum) = self.planned_handoffs(last)?;
        mutate(last, |state| {
            for planned in &handoffs {
                Self::create_planned_handoff(state, planned, &quorum);
            }
        })
    }

    /// The planner's decision, shared by both apply shapes: the sorted
    /// plan and the freeze quorum snapshotted with it. `None` when the
    /// plan is empty — an empty plan is a no-op successor the checker
    /// would dedup anyway, and deciding it before the clone skips the
    /// clone-and-hash per state.
    fn planned_handoffs(
        &self,
        last: &SystemState,
    ) -> Option<(Vec<PlannedHandoff>, BTreeSet<RouterId>)> {
        let current: HashMap<u32, String> = last
            .assignments
            .iter()
            .map(|(p, owner)| (*p as u32, pod_name(*owner)))
            .collect();
        let in_flight: Vec<HandoffState> = last
            .handoffs
            .iter()
            .map(|(p, h)| production_handoff(*p, h))
            .collect();
        let members = self.planner_members(last);
        let mut plan = plan_partial_rebalance(
            &StickyBalancedStrategy,
            &current,
            &in_flight,
            &members,
            self.partitions as u32,
        );
        if plan.handoffs.is_empty() {
            return None;
        }
        // The plan's order follows HashMap iteration; sort so sequential
        // handoff-id assignment is deterministic (`next_state` must be a
        // pure function of its inputs).
        plan.handoffs.sort_by_key(|h| h.partition);
        // Mirror of the coordinator's snapshot read: the routers
        // registered when the plan is applied become the freeze
        // requirement for every handoff it creates.
        let quorum: BTreeSet<RouterId> = self
            .router_ids()
            .filter(|r| last.routers[r].registered)
            .collect();
        Some((plan.handoffs, quorum))
    }

    /// One planned creation landing (the atomic-apply path, where guards
    /// trivially hold within the transition).
    fn create_planned_handoff(
        state: &mut SystemState,
        planned: &PlannedHandoff,
        quorum: &BTreeSet<RouterId>,
    ) {
        let id = state.next_handoff_id;
        state.next_handoff_id += 1;
        let clobbered = state
            .handoffs
            .insert(
                planned.partition as Partition,
                Handoff {
                    id,
                    old_owner: planned.old_owner.as_deref().map(pod_id),
                    new_owner: pod_id(&planned.new_owner),
                    phase: Phase::Freezing,
                    quorum: quorum.clone(),
                },
            )
            .is_some();
        if clobbered {
            // Planning a pinned partition would destroy its
            // in-flight handoff (and orphan its acks); the
            // always-property flags any interleaving where the
            // exclusion fails to prevent that.
            state.double_planned_handoff = true;
        }
    }

    /// `rebalance` applying its plan the way `apply_plan` does past the
    /// txn budget: the first handoff lands now, the rest wait as
    /// pending units carrying their plan-time guards. Only offered when
    /// the plan actually splits — a one-handoff plan is `Rebalance`.
    fn rebalance_chunked(&self, last: &SystemState) -> Option<SystemState> {
        let (handoffs, quorum) = self.planned_handoffs(last)?;
        let (first, rest) = handoffs.split_first()?;
        if rest.is_empty() {
            return None;
        }
        mutate(last, |state| {
            Self::create_planned_handoff(state, first, &quorum);
            state.pending_plan = rest
                .iter()
                .map(|planned| {
                    let partition = planned.partition as Partition;
                    PendingUnit {
                        partition,
                        old_owner: planned.old_owner.as_deref().map(pod_id),
                        new_owner: pod_id(&planned.new_owner),
                        quorum: quorum.clone(),
                        expected_assignment_version: state
                            .assignment_versions
                            .get(&partition)
                            .copied()
                            .unwrap_or(0),
                    }
                })
                .collect();
        })
    }

    /// A later chunk landing: the front pending unit applies if its
    /// plan-time guards still hold — handoff key absent, assignment
    /// version unchanged — and is dropped (stood down) otherwise, as a
    /// conflicted chunk unit is in production.
    fn apply_pending_unit(&self, last: &SystemState) -> Option<SystemState> {
        let unit = last.pending_plan.first()?.clone();
        mutate(last, |state| {
            state.pending_plan.remove(0);
            let version = state
                .assignment_versions
                .get(&unit.partition)
                .copied()
                .unwrap_or(0);
            if state.handoffs.contains_key(&unit.partition)
                || version != unit.expected_assignment_version
            {
                state.pending_unit_dropped = true;
                return;
            }
            let id = state.next_handoff_id;
            state.next_handoff_id += 1;
            state.handoffs.insert(
                unit.partition,
                Handoff {
                    id,
                    old_owner: unit.old_owner,
                    new_owner: unit.new_owner,
                    phase: Phase::Freezing,
                    quorum: unit.quorum,
                },
            );
            state.pending_unit_applied = true;
        })
    }

    /// Mirror of `check_phase_advance`, with the identity quorum and
    /// handoff_id ack correlation. Each phase's production predicate runs
    /// against `last`, so an unsatisfied one costs no clone.
    fn advance_phase(&self, last: &SystemState, p: Partition) -> Option<SystemState> {
        let h = last.handoffs.get(&p)?;
        let next_phase = match h.phase {
            Phase::Freezing => {
                // The production quorum predicate on production-typed
                // views: registered routers only (which is what admits
                // the zombie-router half of the double-zombie residual),
                // id-correlated acks, vacuous at zero routers.
                let routers: Vec<RegisteredRouter> = self
                    .router_ids()
                    .filter(|r| last.routers[r].registered)
                    .map(|r| RegisteredRouter {
                        router_name: router_name(r),
                        registered_at: 0,
                        last_heartbeat: 0,
                    })
                    .collect();
                let acks: Vec<RouterFreezeAck> = self
                    .router_ids()
                    .filter_map(|r| {
                        last.freeze_acks.get(&(p, r)).map(|id| RouterFreezeAck {
                            router_name: router_name(r),
                            partition: p as u32,
                            acked_at: 0,
                            acked_at_ms: 0,
                            handoff_id: id.to_string(),
                        })
                    })
                    .collect();
                if !freeze_quorum_met(
                    &routers,
                    &acks,
                    &production_handoff(p, h),
                    Some(&production_quorum(h)),
                ) {
                    return None;
                }
                // Initial assignments (no old owner) skip the drain
                // entirely.
                match h.old_owner {
                    None => Phase::Warming,
                    Some(_) => Phase::Draining,
                }
            }
            Phase::Draining => {
                let registered: Vec<RegisteredPod> = self
                    .pod_ids()
                    .filter(|x| last.pods[x].registered)
                    .map(|x| RegisteredPod {
                        pod_name: pod_name(x),
                        generation: String::new(),
                        status: PodStatus::Ready,
                        registered_at: 0,
                        last_heartbeat: 0,
                        controller: None,
                        advertise_address: None,
                    })
                    .collect();
                let acks: Vec<PodDrainedAck> = self
                    .pod_ids()
                    .filter_map(|x| {
                        last.drained_acks.get(&(p, x)).map(|id| PodDrainedAck {
                            pod_name: pod_name(x),
                            partition: p as u32,
                            acked_at: 0,
                            acked_at_ms: 0,
                            handoff_id: id.to_string(),
                        })
                    })
                    .collect();
                if !drain_satisfied(&registered, &acks, &production_handoff(p, h)) {
                    return None;
                }
                Phase::Warming
            }
            Phase::Warming => {
                let acks: Vec<PodWarmedAck> = self
                    .pod_ids()
                    .filter_map(|x| {
                        last.warmed_acks.get(&(p, x)).map(|id| PodWarmedAck {
                            pod_name: pod_name(x),
                            partition: p as u32,
                            acked_at: 0,
                            acked_at_ms: 0,
                            handoff_id: id.to_string(),
                        })
                    })
                    .collect();
                if !warm_satisfied(&acks, &production_handoff(p, h)) {
                    return None;
                }
                Phase::Complete
            }
            Phase::Complete => return None,
        };
        let new_owner = h.new_owner;
        mutate(last, |state| {
            state.handoffs.get_mut(&p).unwrap().phase = next_phase;
            if next_phase == Phase::Complete {
                // `complete_handoff`: phase write and assignment flip are
                // one etcd transaction.
                state.assignments.insert(p, new_owner);
                if self.chunked_plans {
                    // The mod_revision a pending unit's precondition
                    // compares; maintained only where something reads it,
                    // so other configs don't split states by history.
                    *state.assignment_versions.entry(p).or_insert(0) += 1;
                }
            }
        })
    }

    /// Mirror of `PodHandle::apply` — one idempotent transition toward the
    /// desired state. Startup reconcile after a crash is these same
    /// actions running against wiped local state.
    ///
    /// Each arm decides on `last` whether it owes a transition at all, so
    /// an already-converged pod costs a `desired_state` derivation and no
    /// clone.
    fn converge(&self, last: &SystemState, x: PodId, p: Partition) -> Option<SystemState> {
        match model_desired_state(x, last, p) {
            DesiredState::Serving => {
                let pod = &last.pods[&x];
                if !pod.warmed.contains_key(&p) {
                    // `warm_partition`, one step at a time (see
                    // `warm_step` for the two orderings under
                    // EpochFenced).
                    mutate(last, |state| self.warm_step(state, x, p, None))
                } else if pod.fenced.contains(&p) {
                    mutate(last, |state| {
                        // `resume_partition`. Under EpochFenced the
                        // cancelled handoff's target may have taken the
                        // broker fence from this pod's producer;
                        // production re-acquires it before re-admitting
                        // writes, or every write would fail as fenced
                        // until the next handoff.
                        if self.variant == Variant::EpochFenced {
                            state.changelogs.get_mut(&p).unwrap().epoch_holder = Some(x);
                        }
                        state.pods.get_mut(&x).unwrap().fenced.remove(&p);
                    })
                } else {
                    None
                }
            }
            DesiredState::Drained { ack } => {
                let h_id = last.handoffs[&p].id;
                let pod = &last.pods[&x];
                let fences = !pod.fenced.contains(&p);
                // The flip to Drained abandons an in-flight warm: the
                // production warm future is dropped, and any later warm
                // re-acquires the fence rather than resuming this
                // attempt's stale init.
                let drops_pending = pod.pending_warm.contains_key(&p);
                // `put_drained_ack`, only while the phase is Draining,
                // echoing the handoff id.
                let acks = ack && last.drained_acks.get(&(p, x)) != Some(&h_id);
                if !fences && !drops_pending && !acks {
                    return None;
                }
                mutate(last, |state| {
                    let pod = state.pods.get_mut(&x).unwrap();
                    pod.fenced.insert(p);
                    pod.pending_warm.remove(&p);
                    if acks {
                        state.drained_acks.insert((p, x), h_id);
                    }
                })
            }
            DesiredState::Acquiring => {
                let h_id = last.handoffs[&p].id;
                // Only a warm installed for *this* handoff satisfies its
                // warming; one from an earlier era is released and
                // rebuilt (its cutoff can predate writes accepted since —
                // the `WarmProvenance` guard in the production Acquiring
                // arm).
                let valid = last.pods[&x]
                    .warmed
                    .get(&p)
                    .is_some_and(|w| w.for_handoff == Some(h_id));
                if valid && last.warmed_acks.get(&(p, x)) == Some(&h_id) {
                    return None;
                }
                mutate(last, |state| {
                    if !valid {
                        // Release a warm from an earlier era, then
                        // `warm_partition`, one step at a time.
                        state.pods.get_mut(&x).unwrap().warmed.remove(&p);
                        self.warm_step(state, x, p, Some(h_id));
                    }
                    // `put_warmed_ack`, echoing the handoff id — only
                    // once this handoff's warm has installed.
                    if state.pods[&x]
                        .warmed
                        .get(&p)
                        .is_some_and(|w| w.for_handoff == Some(h_id))
                        && state.warmed_acks.get(&(p, x)) != Some(&h_id)
                    {
                        state.warmed_acks.insert((p, x), h_id);
                    }
                })
            }
            DesiredState::Released => {
                let pod = &last.pods[&x];
                // `release_partition` also drops a mid-warm fence
                // producer.
                if !pod.warmed.contains_key(&p)
                    && !pod.fenced.contains(&p)
                    && !pod.pending_warm.contains_key(&p)
                {
                    return None;
                }
                mutate(last, |state| {
                    let pod = state.pods.get_mut(&x).unwrap();
                    pod.warmed.remove(&p);
                    pod.fenced.remove(&p);
                    pod.pending_warm.remove(&p);
                })
            }
        }
    }

    /// Mirror of the routing-table watch handler + stash handler. The
    /// router acts on the CURRENT durable state — the same semantics its
    /// event handlers converge to, since a late router processes events up
    /// to the present (load_initial / anchored watches guarantee it misses
    /// nothing).
    ///
    /// Each arm first asks of `last` whether it has anything to do, so a
    /// router already agreeing with durable state costs no clone.
    fn observe(&self, last: &SystemState, r: RouterId, p: Partition) -> Option<SystemState> {
        let router = &last.routers[&r];
        let parked = router.stash.get(&p).is_some_and(|q| !q.is_empty());
        match last.handoffs.get(&p) {
            Some(h) if h.phase != Phase::Complete => {
                // begin_stash on every non-terminal phase; FreezeAck only
                // while Freezing, echoing the id.
                let (id, phase) = (h.id, h.phase);
                let stashes = !router.stashing.contains(&p);
                let acks_freeze =
                    phase == Phase::Freezing && last.freeze_acks.get(&(p, r)) != Some(&id);
                if !stashes && !acks_freeze {
                    return None;
                }
                mutate(last, |state| {
                    state.routers.get_mut(&r).unwrap().stashing.insert(p);
                    if acks_freeze {
                        state.freeze_acks.insert((p, r), id);
                    }
                })
            }
            Some(h) => {
                // Complete: cutover the table, then drain the stash to
                // the new owner in FIFO order.
                let new_owner = h.new_owner;
                if router.table.get(&p) == Some(&new_owner)
                    && !router.stashing.contains(&p)
                    && !parked
                {
                    return None;
                }
                mutate(last, |state| {
                    let parked = {
                        let router = state.routers.get_mut(&r).unwrap();
                        router.table.insert(p, new_owner);
                        router.stashing.remove(&p);
                        router.stash.remove(&p).unwrap_or_default()
                    };
                    for entry in parked {
                        match entry {
                            StashedRequest::Write => {
                                if self.write_capable(state, new_owner, p) {
                                    self.accept_write(state, new_owner, p);
                                }
                                // Rejected drains surface UNAVAILABLE to
                                // the client (never acked).
                            }
                            StashedRequest::StrongRead => {
                                self.serve_read(state, new_owner, p);
                            }
                        }
                    }
                })
            }
            None => {
                // No handoff: converge the table to the assignment; a
                // cancellation drains the stash back to the assignment
                // owner.
                let assignment = last.assignments.get(&p).copied();
                let retables = match assignment {
                    Some(owner) => router.table.get(&p) != Some(&owner),
                    None => router.table.contains_key(&p),
                };
                if !retables && !router.stashing.contains(&p) && !parked {
                    return None;
                }
                mutate(last, |state| {
                    let parked = {
                        let router = state.routers.get_mut(&r).unwrap();
                        match assignment {
                            Some(owner) => {
                                router.table.insert(p, owner);
                            }
                            None => {
                                router.table.remove(&p);
                            }
                        }
                        router.stashing.remove(&p);
                        router.stash.remove(&p).unwrap_or_default()
                    };
                    for entry in parked {
                        let Some(owner) = assignment else { continue };
                        match entry {
                            StashedRequest::Write => {
                                if self.write_capable(state, owner, p) {
                                    self.accept_write(state, owner, p);
                                }
                            }
                            StashedRequest::StrongRead => {
                                self.serve_read(state, owner, p);
                            }
                        }
                    }
                })
            }
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
                        pending_warm: BTreeMap::new(),
                        zombie_writes_left: 0,
                        claims_authority: true,
                    },
                )
            })
            .collect();
        let routers: BTreeMap<RouterId, Router> = self
            .router_ids()
            .map(|id| {
                // Slots at or past `routers` start dark and only come up
                // via `RouterJoin`.
                let active = id < self.routers;
                (
                    id,
                    Router {
                        registered: active,
                        running: active,
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
            pending_plan: Vec::new(),
            assignment_versions: BTreeMap::new(),
            pods,
            routers,
            changelogs,
            writes_left: self.writes,
            reads_left: self.reads,
            crashes_left: self.crashes,
            rejoins_left: self.rejoins,
            router_joins_left: self.router_joins,
            cancels_left: self.cancels,
            read_served: false,
            lost_acked_write: false,
            double_planned_handoff: false,
            stale_strong_read: false,
            reaffirmed: false,
            replaced_with_successor: false,
            cancelled_while_stash_parked: false,
            pending_unit_applied: false,
            pending_unit_dropped: false,
        }]
    }

    /// Only enabled actions are offered, so the checker never pays a
    /// state clone for a transition that cannot happen. The `if`s that
    /// remain are model *configuration* — whether an action exists in this
    /// variant at all — rather than per-state enablement, which lives in
    /// [`HandoffModel::enabled`].
    fn actions(&self, state: &Self::State, actions: &mut Vec<Self::Action>) {
        let mut offer = |action: Action| {
            if self.enabled(state, &action) {
                actions.push(action);
            }
        };
        offer(Action::Rebalance);
        offer(Action::RebalanceChunked);
        offer(Action::ApplyPendingUnit);
        for p in self.partition_ids() {
            offer(Action::CancelDeadNewOwner(p));
            offer(Action::Cancel(p));
            offer(Action::AdvancePhase(p));
            offer(Action::CleanupComplete(p));
            for pod in self.pod_ids() {
                offer(Action::Converge(pod, p));
            }
            for r in self.router_ids() {
                offer(Action::Observe(r, p));
                offer(Action::ClientWrite(r, p));
                offer(Action::ClientStrongRead(r, p));
            }
        }
        for pod in self.pod_ids() {
            offer(Action::CrashRestartWithinTtl(pod));
            offer(Action::LeaseExpire(pod));
        }
        for r in self.router_ids() {
            offer(Action::RouterLeaseExpire(r));
        }
        for pod in self.pod_ids() {
            offer(Action::SelfFence(pod));
            if self.claim_detection == ClaimDetection::Delayed {
                offer(Action::NoticeLeaseLoss(pod));
            }
            // Only meaningful when something consults the claim, and the
            // state space is expensive enough that exploring it in
            // configurations that ignore the claim would buy nothing.
            if self.lease_gated_reads {
                offer(Action::AuthorityLapse(pod));
                if self.claim_recovers {
                    offer(Action::AuthorityRenew(pod));
                }
            }
            offer(Action::Join(pod));
        }
        for r in self.router_ids() {
            offer(Action::RouterSelfFence(r));
            offer(Action::RouterJoin(r));
        }
    }

    /// Every arm clones `last` only once it knows a successor exists, so a
    /// disabled or no-op transition costs no state materialization. The
    /// four arms whose enablement needs real work — the planner, the phase
    /// predicates, `desired_state`, and a router's table diff — live in
    /// their own methods above.
    fn next_state(&self, last: &Self::State, action: Self::Action) -> Option<Self::State> {
        if !self.enabled(last, &action) {
            return None;
        }
        match action {
            // ── coordinator ────────────────────────────────────
            Action::Rebalance => self.rebalance(last),
            Action::RebalanceChunked => self.rebalance_chunked(last),
            Action::ApplyPendingUnit => self.apply_pending_unit(last),
            Action::AdvancePhase(p) => self.advance_phase(last, p),

            // The dead-new-owner arm of the coordinator's cleanup, now a
            // replacement. The mod_revision guard lets the model treat
            // check-and-replace as atomic; scheduling it freely against
            // Rebalance/AdvancePhase/CleanupComplete covers the
            // concurrency of the pod watch, handoff watch, tick, and an
            // overlapping outgoing coordinator. Complete records are
            // excluded — they resolve through CleanupComplete and a
            // later Rebalance, exactly as in production.
            Action::CancelDeadNewOwner(p) => {
                mutate(last, |state| self.cancel_by_replacement(state, p))
            }

            // Deadline cancellation: any in-flight handoff, any phase
            // short of Complete, whenever the checker feels like it —
            // the superset of every production deadline policy. Same
            // disposition as the dead-new-owner arm.
            Action::Cancel(p) => mutate(last, |state| {
                state.cancels_left -= 1;
                self.cancel_by_replacement(state, p);
            }),

            // Mirror of the Complete arm of `handle_handoff_update_static`
            // (guarded delete of the record and its acks).
            Action::CleanupComplete(p) => mutate(last, |state| {
                state.handoffs.remove(&p);
                state.freeze_acks.retain(|(fp, _), _| fp != &p);
                state.drained_acks.retain(|(dp, _), _| dp != &p);
                state.warmed_acks.retain(|(wp, _), _| wp != &p);
            }),

            // ── pod converge ───────────────────────────────────
            Action::Converge(x, p) => self.converge(last, x, p),

            // ── router ─────────────────────────────────────────
            Action::Observe(r, p) => self.observe(last, r, p),

            // ── workload ───────────────────────────────────────
            Action::ClientWrite(r, p) => mutate(last, |state| {
                state.writes_left -= 1;
                // A rejected write still consumes its budget: the state
                // changed, so the transition is kept and rejected paths
                // are explored too.
                self.route_write(state, r, p);
            }),

            Action::ClientStrongRead(r, p) => mutate(last, |state| {
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
                    self.serve_read(state, target, p);
                }
            }),

            // ── failures ───────────────────────────────────────
            Action::Join(x) => mutate(last, |state| {
                state.rejoins_left -= 1;
                let pod = state.pods.get_mut(&x).unwrap();
                pod.registered = true;
                pod.running = true;
                pod.warmed.clear();
                pod.fenced.clear();
                pod.pending_warm.clear();
                pod.zombie_writes_left = 0;
                // A new session is a new claim.
                pod.claims_authority = true;
            }),
            Action::CrashRestartWithinTtl(x) => mutate(last, |state| {
                state.crashes_left -= 1;
                let pod = state.pods.get_mut(&x).unwrap();
                pod.warmed.clear();
                pod.fenced.clear();
                pod.pending_warm.clear();
            }),
            Action::LeaseExpire(x) => mutate(last, |state| {
                state.crashes_left -= 1;
                let zombie_window = self.zombie_window;
                let prompt = self.claim_detection == ClaimDetection::Prompt;
                let pod = state.pods.get_mut(&x).unwrap();
                pod.registered = false;
                // With the registration watch the claim drops here;
                // without it the pod keeps claiming until a later round
                // notices, which `NoticeLeaseLoss` explores as its own
                // step so every interleaving in between is checked.
                if prompt {
                    pod.claims_authority = false;
                }
                if pod.running {
                    pod.zombie_writes_left = zombie_window;
                }
            }),
            // The gap the registration watch closes: between losing the
            // lease and noticing, the pod still answers as the owner.
            // The window production's clock actually creates: the stamp
            // ages past the margin at two thirds of the TTL, but etcd
            // holds the registration until the full TTL. For that third
            // the pod refuses to serve while still looking alive to the
            // coordinator — the black hole `converges_to_stable` has to
            // be able to see, and which tying the claim to the
            // registration made unrepresentable.
            Action::AuthorityLapse(x) => mutate(last, |state| {
                state.pods.get_mut(&x).unwrap().claims_authority = false;
            }),
            Action::AuthorityRenew(x) => mutate(last, |state| {
                state.pods.get_mut(&x).unwrap().claims_authority = true;
            }),
            Action::NoticeLeaseLoss(x) => mutate(last, |state| {
                state.pods.get_mut(&x).unwrap().claims_authority = false;
            }),

            Action::SelfFence(x) => mutate(last, |state| {
                let pod = state.pods.get_mut(&x).unwrap();
                pod.running = false;
                pod.warmed.clear();
                pod.fenced.clear();
                pod.pending_warm.clear();
                pod.zombie_writes_left = 0;
                pod.claims_authority = false;
            }),
            Action::RouterLeaseExpire(r) => mutate(last, |state| {
                state.crashes_left -= 1;
                state.routers.get_mut(&r).unwrap().registered = false;
            }),
            Action::RouterSelfFence(r) => mutate(last, |state| {
                // The process exits; parked stash requests die with it
                // (their clients get errors — the writes were never
                // acked).
                let router = state.routers.get_mut(&r).unwrap();
                router.running = false;
                router.stashing.clear();
                router.stash.clear();
            }),
            Action::RouterJoin(r) => mutate(last, |state| {
                state.router_joins_left -= 1;
                // A fresh process: registration written, table empty
                // (fail-closed until Observe converges it — the model's
                // bootstrap). Handoffs created before this point do not
                // carry it in their quorum; the live-set legacy rule
                // would have counted it from here on.
                let router = state.routers.get_mut(&r).unwrap();
                router.registered = true;
                router.running = true;
                router.table.clear();
                router.stashing.clear();
                router.stash.clear();
            }),
        }
    }

    fn properties(&self) -> Vec<Property<Self>> {
        let mut props = vec![
            // The acked-write-loss invariant the drain/fence/HWM
            // machinery exists to uphold. Expected to FAIL under
            // Variant::Current with a zombie window (the documented
            // residual) and PASS under Variant::EpochFenced.
            Property::<Self>::always("no_lost_acked_write", |_, s| !s.lost_acked_write),
            // Rebalancing is enabled concurrently with in-flight handoffs;
            // pinning must keep it from ever planning one of their
            // partitions a second time.
            Property::<Self>::always("no_double_planned_handoff", |_, s| {
                !s.double_planned_handoff
            }),
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
                m.reads == 0 || s.read_served
            }),
            // Replacement-cancellation reachability. Each probe is vacuous
            // outside the configurations shaped to reach it, so
            // `assert_properties` stays usable across the matrix — and the
            // same predicate decides whether its evidence flag is recorded
            // at all, so a vacuous probe costs no state space.
            Property::<Self>::sometimes("cancellation_reaffirms", |m, s| {
                !m.probes_reaffirm() || s.reaffirmed
            }),
            Property::<Self>::sometimes("cancellation_replaces_with_successor", |m, s| {
                !m.probes_successor_replacement() || s.replaced_with_successor
            }),
            Property::<Self>::sometimes("cancellation_races_a_parked_stash", |m, s| {
                !m.probes_stash_racing_cancellation() || s.cancelled_while_stash_parked
            }),
            // Liveness: every full run ends quiescent and converged —
            // no handoffs in flight, every assignment served by a warm,
            // unfenced, registered pod, all routers agreeing, nothing
            // parked in a stash.
            Property::<Self>::eventually("converges_to_stable", |m, s| {
                // Ordered cheapest-first on purpose. This runs at every
                // explored state, and the placement computation below is
                // the one expensive part — it must stay behind the
                // conjuncts that reject most states outright.
                if !s.handoffs.is_empty() || !s.pending_plan.is_empty() {
                    return false;
                }
                let no_capacity = s.pods.values().all(|p| !p.registered);
                let owners_converged = no_capacity
                    || (!s.assignments.is_empty() && {
                        // One placement computation for the whole state
                        // rather than one per partition: `target_owner`
                        // rebuilds `String` maps and reruns the production
                        // strategy on every call.
                        let targets = m.target_assignments(s);
                        m.partition_ids().all(|p| {
                            let Some(target) = targets.get(&(p as u32)).map(|name| pod_id(name))
                            else {
                                return true;
                            };
                            let assigned = s.assignments.get(&p) == Some(&target);
                            let pod = &s.pods[&target];
                            // `write_capable` (not just warmed +
                            // unfenced) so a stale producer epoch — the
                            // fenced-wedge a resume without
                            // re-acquisition would leave — fails
                            // stability rather than passing it.
                            assigned
                                && pod.running
                                && pod.registered
                                && m.write_capable(s, target, p)
                                // A converged owner that refuses its own
                                // reads is a black hole the coordinator
                                // will not reassign, because it still
                                // looks alive.
                                && (!m.lease_gated_reads || pod.claims_authority)
                        })
                    });
                owners_converged
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
            // The freeze-quorum snapshot doing its job: a handoff
            // advanced past Freezing while some registered router — a
            // late joiner outside the snapshot — never wrote a freeze
            // ack for it. Under the pre-snapshot live-set rule this
            // state is unreachable; its reachability is the machine
            // statement that the wedge is fixed, and the safety
            // properties judge every interleaving that reaches it.
            // Two in-flight handoffs carrying different snapshots —
            // one created before a join, one after, coexisting because
            // the first is pinned while a crash forces a second
            // rebalance. This is the shape that would expose a refactor
            // computing "the" requirement once from live state and
            // sharing it across handoffs: correct-looking, wrong only
            // here, invisible to every single-partition config.
            props.push(Property::<Self>::sometimes(
                "handoffs_with_divergent_quorums",
                |_, s| {
                    s.handoffs
                        .values()
                        .any(|h1| s.handoffs.values().any(|h2| h1.quorum != h2.quorum))
                },
            ));
            props.push(Property::<Self>::sometimes(
                "advances_past_silent_late_joiner",
                |m, s| {
                    s.handoffs.iter().any(|(p, h)| {
                        h.phase != Phase::Freezing
                            && m.router_ids().any(|r| {
                                s.routers[&r].registered
                                    && !h.quorum.contains(&r)
                                    && s.freeze_acks.get(&(*p, r)) != Some(&h.id)
                            })
                    })
                },
            ));
            // Two or more handoffs in flight at once (one rebalance txn
            // creates them all; concurrent rebalances only add handoffs
            // for unpinned partitions).
            props.push(Property::<Self>::sometimes(
                "concurrent_handoffs",
                |_, s| s.handoffs.len() >= 2,
            ));
            // A pod that is old owner of one in-flight handoff and new
            // owner of another — simultaneously drain-side and warm-side.
            // Reachable since partial rebalancing let handoffs from
            // different plans coexist (within one plan the sticky
            // strategy never takes from and gives to the same pod). Safe
            // because every protocol mechanism the two roles touch —
            // fences, inflight counts, cache partitions, acks — is
            // partition-scoped; the probe makes the checker explore the
            // dual-role interleavings the safety properties then judge.
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
        if self.probes && self.chunked_plans {
            // Both fates of a chunked plan's suffix are genuinely
            // reachable: a late unit landing after other actions
            // interleaved, and one stood down by a failed guard. The
            // safety properties judge every interleaving that reaches
            // them.
            props.push(Property::<Self>::sometimes(
                "chunked_pending_unit_applied",
                |_, s| s.pending_unit_applied,
            ));
            props.push(Property::<Self>::sometimes(
                "chunked_pending_unit_dropped",
                |_, s| s.pending_unit_dropped,
            ));
        }
        props
    }
}
