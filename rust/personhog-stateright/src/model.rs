//! Stateright `Model` for the personhog partition handoff protocol.
//!
//! Each action's transition logic mirrors a specific production code path
//! (named in comments) so a divergence between model and code is
//! reviewable line by line. The checker exhaustively interleaves every
//! action from every reachable state and verifies the properties at each.

mod migration;

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

use personhog_coordination::changelog::warm_sources;
use personhog_coordination::pod::{desired_state, DesiredState};
use personhog_coordination::protocol::migration::{
    fleet_quiet, migration_unsealed, migration_unsettled, plan_freeze, plan_resume,
    planner_may_place, seal_targets,
};
use personhog_coordination::protocol::{
    drain_satisfied, freeze_quorum_met, plan_partial_rebalance, warm_satisfied, PlannedHandoff,
};
use personhog_coordination::strategy::{AssignmentStrategy, Member, StickyBalancedStrategy};
use personhog_coordination::types::{
    AssignmentStatus, ChangelogConfig, Generation as ProductionGeneration, HandoffState,
    MigrationPhase, PartitionAssignment, PodDrainedAck, PodStatus, PodWarmedAck, RegisteredPod,
    RegisteredRouter, RouterFreezeAck, SealAck,
};
use stateright::{Model, Property};

use crate::types::{
    Action, Changelog, Config, Epoch, Generation, Handoff, HandoffId, Key, Migration, Partition,
    PendingUnit, PendingWarm, Phase, Pod, PodId, Router, RouterId, StashedRequest, SystemState,
    WarmState,
};

/// The one migration id the model ever runs.
const MIGRATION_ID: &str = "m";

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
fn generation_topic(epoch: Epoch) -> String {
    format!("g{epoch}")
}
fn topic_epoch(topic: &str) -> Epoch {
    topic
        .trim_start_matches('g')
        .parse()
        .expect("generation topic")
}

/// The identity hash: a key's home is its remainder.
fn home(key: Key, partitions: u8) -> Partition {
    key % partitions
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
        held_by: h.held.then(|| MIGRATION_ID.to_string()),
        config_epoch: h.config_epoch as u64,
    }
}

fn production_config(config: &Config) -> ChangelogConfig {
    ChangelogConfig {
        topic: generation_topic(config.live.epoch),
        partitions: config.live.partitions as u32,
        epoch: config.live.epoch as u64,
        writer_group: String::new(),
        retire_groups: vec![],
        draining: config
            .draining
            .map(|g| ProductionGeneration {
                topic: generation_topic(g.epoch),
                partitions: g.partitions as u32,
                epoch: g.epoch as u64,
            })
            .into_iter()
            .collect(),
    }
}

fn production_assignments(state: &SystemState) -> Vec<PartitionAssignment> {
    state
        .assignments
        .iter()
        .map(|(p, owner)| PartitionAssignment {
            partition: *p as u32,
            owner: pod_name(*owner),
            advertise_address: None,
            status: AssignmentStatus::Active,
        })
        .collect()
}

fn production_registered(state: &SystemState) -> Vec<RegisteredPod> {
    state
        .pods
        .iter()
        .filter(|(_, pod)| pod.registered)
        .map(|(x, _)| RegisteredPod {
            pod_name: pod_name(*x),
            generation: String::new(),
            status: PodStatus::Ready,
            registered_at: 0,
            last_heartbeat: 0,
            controller: None,
            advertise_address: None,
        })
        .collect()
}

fn production_seal_acks(state: &SystemState) -> Vec<SealAck> {
    state
        .seal_acks
        .iter()
        .map(|(x, sealed)| SealAck {
            migration_id: MIGRATION_ID.to_string(),
            pod_name: pod_name(*x),
            sealed: sealed.iter().map(|p| *p as u32).collect(),
        })
        .collect()
}

/// The modulus a captured epoch hashes with; `None` once that generation is gone.
fn modulus_of(config: &Config, epoch: Epoch) -> Option<u8> {
    if config.live.epoch == epoch {
        Some(config.live.partitions)
    } else {
        config
            .draining
            .filter(|g| g.epoch == epoch)
            .map(|g| g.partitions)
    }
}

/// Which old partitions a pod seals; `Residency` is the rejected rule, kept as the record of why.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SealRule {
    Assignment,
    Residency,
}

/// Where a restart's warm reads from; `LiveOnly` is the rejected rule.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WarmReplay {
    Sources,
    LiveOnly,
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

/// Which side of the warm read takes the broker fence. `warm_partition`
/// ships `FenceFirst`; `ReadFirst` is kept as the record of why.
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
    /// Fence-vs-read ordering of the decomposed warm; ignored under
    /// a warm that is a single atomic step.
    pub warm_order: WarmOrder,
    /// How promptly a pod notices its lease is gone; only meaningful
    /// since the read gate is the only thing that consults the claim.
    pub claim_detection: ClaimDetection,
    /// Whether a registered pod's claim may lapse. Only the read gate and
    /// `converges_to_stable` read the claim, so off is safe elsewhere.
    pub claim_lapses: bool,
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
    /// Migrations the control plane may start (at most one draining generation).
    pub migrations: u8,
    /// Partition count a migration moves to.
    pub migrate_to: u8,
    /// Distinct keys the workload writes and reads, at least one per starting
    /// partition so every partition takes writes.
    pub keys: u8,
    pub seal_rule: SealRule,
    pub warm_replay: WarmReplay,
    /// Budget of pods whose seal breaks (`Action::BreakSeal`).
    pub seal_breaks: u8,
    /// Whether peers seal overdue partitions; `false` keeps the rejected no-exit rule.
    pub seal_grace: bool,
    /// Whether a plan's later units stand down when its basis moved; `false`
    /// keeps the rejected unguarded planner.
    pub plan_basis_guard: bool,
    /// Whether a saga starts only once the fleet is quiet (`fleet_quiet`);
    /// `false` keeps the rejected start that freezes a fleet in motion.
    pub quiet_start: bool,
    /// Whether the freeze cancels on an ordinary handoff (`plan_freeze`'s stray).
    pub freeze_checks_strays: bool,
    /// Whether a request parks behind its key's parked requests; `false`
    /// keeps the rejected bucket rule, which lets a later request overtake.
    pub park_behind_key: bool,
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
    /// Every partition number any generation can have.
    fn partition_ids(&self) -> impl Iterator<Item = Partition> {
        0..self.partitions.max(self.migrate_to)
    }
    fn key_ids(&self) -> impl Iterator<Item = Key> {
        0..self.keys.max(self.partitions)
    }

    /// `fleet_quiet` over production views; the model's registered pods are all Ready.
    fn quiet(state: &SystemState) -> bool {
        let handoffs: Vec<HandoffState> = state
            .handoffs
            .iter()
            .map(|(p, h)| production_handoff(*p, h))
            .collect();
        let registered = Self::registered_names(state);
        let ready: HashSet<&str> = registered.iter().map(String::as_str).collect();
        fleet_quiet(
            state.config.live.partitions as u32,
            &production_assignments(state),
            &handoffs,
            &ready,
        )
        .is_empty()
    }

    /// Production `PlanBasis`, coarsened: whether a saga exists, and the live epoch.
    fn plan_basis(state: &SystemState) -> (bool, Epoch) {
        (state.migration.is_some(), state.config.live.epoch)
    }

    /// The planner stands down while a migration owns placement.
    fn planner_active(state: &SystemState) -> bool {
        planner_may_place(
            state.migration.map(|m| m.phase),
            state.handoffs.values().any(|h| h.held),
        )
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
        StickyBalancedStrategy.compute_assignments(
            &current,
            &members,
            state.config.live.partitions as u32,
        )
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
        let cap = (state.config.live.partitions as u32).div_ceil(incoming as u32);
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
        let Some(warm) = pod.warmed.get(&partition) else {
            return false;
        };
        if pod.fenced.contains(&partition) {
            return false;
        }
        // The broker accepts one producer per partition, whichever
        // acquired the fence most recently. A warmed pod that is no
        // longer the holder would be producing under a fenced-out
        // producer, and the broker rejects it before any client ack.
        state.changelogs[&(warm.epoch, partition)].epoch_holder == Some(x)
    }

    /// The leader's `validate_partition`: the key's home under the captured modulus.
    fn validates(&self, state: &SystemState, x: PodId, partition: Partition, key: Key) -> bool {
        state.pods[&x]
            .warmed
            .get(&partition)
            .and_then(|warm| modulus_of(&state.config, warm.epoch))
            .is_some_and(|modulus| home(key, modulus) == partition)
    }

    /// The logs a warm of `partition` replays, each at its current length.
    fn warm_prefixes(
        &self,
        state: &SystemState,
        partition: Partition,
    ) -> BTreeMap<(Epoch, Partition), u8> {
        let live = (state.config.live.epoch, partition);
        let keys: Vec<(Epoch, Partition)> = match self.warm_replay {
            WarmReplay::Sources => {
                warm_sources(&production_config(&state.config), partition as u32)
                    .into_iter()
                    .map(|s| (topic_epoch(&s.topic), s.partition as Partition))
                    .collect()
            }
            WarmReplay::LiveOnly => vec![live],
        };
        keys.into_iter()
            .map(|key| (key, state.changelogs.get(&key).map_or(0, Changelog::len)))
            .collect()
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
        // The strong-read capture: the config as etcd holds it now.
        let epoch = state.config.live.epoch;
        let live = (epoch, partition);
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
        let observable_gap = self.warm_order == WarmOrder::ReadFirst;
        if !observable_gap {
            let sources = self.warm_prefixes(state, partition);
            state.changelogs.get_mut(&live).unwrap().epoch_holder = Some(x);
            let pod = state.pods.get_mut(&x).unwrap();
            pod.warmed.insert(
                partition,
                WarmState {
                    for_handoff,
                    epoch,
                    sources,
                },
            );
            pod.fenced.remove(&partition);
            return;
        }
        match state.pods[&x].pending_warm.get(&partition).copied() {
            None => {
                // The rejected ordering: the changelog read runs to the
                // current HWM while the fence — and thus the rejection of
                // a zombie's write — does not exist yet.
                let pending = PendingWarm {
                    cutoff: state.changelogs[&live].len(),
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
                let mut sources = self.warm_prefixes(state, partition);
                sources.insert(live, cutoff);
                state.changelogs.get_mut(&live).unwrap().epoch_holder = Some(x);
                let pod = state.pods.get_mut(&x).unwrap();
                pod.pending_warm.remove(&partition);
                pod.warmed.insert(
                    partition,
                    WarmState {
                        for_handoff,
                        epoch,
                        sources,
                    },
                );
                pod.fenced.remove(&partition);
            }
        }
    }

    /// Whether the handoff's new owner has fixed its serving cutoff over `log`: a warm
    /// for this handoff, or a mid-warm read already taken. An earlier-era warm does not count.
    fn handoff_cutoff_frozen(
        &self,
        state: &SystemState,
        h: &Handoff,
        partition: Partition,
        log: (Epoch, Partition),
    ) -> bool {
        let pod = &state.pods[&h.new_owner];
        match pod.warmed.get(&partition) {
            Some(w) => w.for_handoff == Some(h.id) && w.sources.contains_key(&log),
            None => pod.pending_warm.contains_key(&partition) && log.1 == partition,
        }
    }

    /// Whether the assignment owner has fixed its serving cutoff over `log`: any warm,
    /// or a mid-warm read already taken.
    fn owner_cutoff_frozen(
        &self,
        state: &SystemState,
        x: PodId,
        partition: Partition,
        log: (Epoch, Partition),
    ) -> bool {
        let pod = &state.pods[&x];
        match pod.warmed.get(&partition) {
            Some(w) => w.sources.contains_key(&log),
            None => pod.pending_warm.contains_key(&partition) && log.1 == partition,
        }
    }

    /// Serve a strong read for `key` at pod `x` if it can, flagging a stale read when a
    /// log holds a newer record the pod cannot see. Returns whether it served.
    fn serve_read(
        &self,
        state: &mut SystemState,
        x: PodId,
        partition: Partition,
        key: Key,
    ) -> bool {
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
        if !pod.claims_authority {
            return false;
        }
        let Some(warm) = pod.warmed.get(&partition) else {
            return false;
        };
        if !self.validates(state, x, partition, key) {
            return false;
        }
        let stale = state.changelogs.iter().any(|(log, changelog)| {
            let visible = warm.sources.get(log).copied().unwrap_or(0) as usize;
            changelog.records.iter().skip(visible).any(|k| *k == key)
        });
        if stale {
            state.stale_strong_read = true;
        }
        state.read_served = true;
        true
    }

    /// Append one acked write to the pod's log, flagging a lost write when another pod
    /// that owns the key's home has already fixed its cutoff over this log.
    fn accept_write(&self, state: &mut SystemState, x: PodId, partition: Partition, key: Key) {
        let epoch = state.pods[&x].warmed[&partition].epoch;
        let log = (epoch, partition);
        let home_now = home(key, state.config.live.partitions);
        let designated_other = match state.handoffs.get(&home_now) {
            Some(h) if h.new_owner != x => self.handoff_cutoff_frozen(state, h, home_now, log),
            Some(_) => false,
            None => match state.assignments.get(&home_now) {
                Some(owner) if *owner != x => {
                    self.owner_cutoff_frozen(state, *owner, home_now, log)
                }
                _ => false,
            },
        };
        if designated_other {
            state.lost_acked_write = true;
        }
        if epoch != state.config.live.epoch {
            state.mixed_modulus_acceptance = true;
        }

        state.changelogs.get_mut(&log).unwrap().records.push(key);

        let pod = state.pods.get_mut(&x).unwrap();
        if let Some(warm) = pod.warmed.get_mut(&partition) {
            // Its own write is immediately visible to it.
            let visible = warm.sources.entry(log).or_insert(0);
            *visible = visible.saturating_add(1);
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
            && state.routers.values().any(|r| Self::parked_at(r, p))
        {
            state.cancelled_while_stash_parked = true;
        }

        Self::clear_acks(state, p);

        let owner = state.assignments.get(&p).copied();
        let epoch = state.config.live.epoch;
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
                    held: false,
                    config_epoch: epoch,
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
            let quorum = Self::quorum_snapshot(state);
            state.handoffs.insert(
                p,
                Handoff {
                    id,
                    old_owner: owner,
                    new_owner: target,
                    phase: Phase::Freezing,
                    quorum,
                    held: false,
                    config_epoch: epoch,
                },
            );
            if self.probes_successor_replacement() {
                state.replaced_with_successor = true;
            }
            return;
        }
        state.handoffs.remove(&p);
    }

    fn clear_acks(state: &mut SystemState, p: Partition) {
        state.freeze_acks.retain(|(fp, _), _| fp != &p);
        state.drained_acks.retain(|(dp, _), _| dp != &p);
        state.warmed_acks.retain(|(wp, _), _| wp != &p);
    }

    /// The coordinator's snapshot read: the routers registered now.
    fn quorum_snapshot(state: &SystemState) -> BTreeSet<RouterId> {
        state
            .routers
            .iter()
            .filter(|(_, r)| r.registered)
            .map(|(r, _)| *r)
            .collect()
    }

    /// Whether router `r` holds a parked request whose key maps to `p` under its count.
    fn parked_at(router: &Router, p: Partition) -> bool {
        router
            .stash
            .iter()
            .any(|e| home(e.key(), router.adopted.partitions) == p)
    }

    /// Remove and return router `r`'s parked requests for `p`, in arrival order.
    fn take_parked(state: &mut SystemState, r: RouterId, p: Partition) -> Vec<StashedRequest> {
        let router = state.routers.get_mut(&r).unwrap();
        let partitions = router.adopted.partitions;
        let (taken, kept) = std::mem::take(&mut router.stash)
            .into_iter()
            .partition(|e| home(e.key(), partitions) == p);
        router.stash = kept;
        taken
    }

    /// Route one request as the raw proxy does: park it behind its key or a stashing
    /// partition, otherwise forward it and let the leader's admission decide.
    fn route(&self, state: &mut SystemState, r: RouterId, request: StashedRequest) -> bool {
        let router = &state.routers[&r];
        if !router.running {
            return false;
        }
        let partition = home(request.key(), router.adopted.partitions);
        if router.stashing.contains(&partition)
            || (self.park_behind_key && router.stash.iter().any(|e| e.key() == request.key()))
        {
            state.routers.get_mut(&r).unwrap().stash.push(request);
            return true;
        }
        let Some(target) = router.table.get(&partition).copied() else {
            // A partition born in the flip parks until its handoff lands.
            let born = state
                .config
                .draining
                .is_some_and(|g| partition >= g.partitions);
            if born {
                let router = state.routers.get_mut(&r).unwrap();
                router.stashing.insert(partition);
                router.stash.push(request);
                state.born_partition_write_parked = true;
                return true;
            }
            // No route: the request is rejected; nothing changes.
            return false;
        };
        self.deliver(state, r, target, partition, request);
        true
    }

    /// Deliver one request from router `r` to `x` for `partition`.
    fn deliver(
        &self,
        state: &mut SystemState,
        r: RouterId,
        x: PodId,
        partition: Partition,
        entry: StashedRequest,
    ) {
        if state.routers[&r]
            .stash
            .iter()
            .any(|parked| parked.key() == entry.key())
        {
            state.overtaken_request = true;
        }
        match entry {
            StashedRequest::Write(key) => {
                if self.validates(state, x, partition, key)
                    && self.write_capable(state, x, partition)
                {
                    self.accept_write(state, x, partition, key);
                }
                // Rejected drains surface UNAVAILABLE to the client (never acked).
            }
            StashedRequest::StrongRead(key) => {
                self.serve_read(state, x, partition, key);
            }
        }
    }

    /// The router adopts the live config (`LiveChangelog::adopt`).
    fn adopt(state: &mut SystemState, r: RouterId) {
        let live = state.config.live;
        let router = state.routers.get_mut(&r).unwrap();
        if router.adopted.epoch < live.epoch {
            router.adopted = live;
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
            Action::Rebalance => Self::planner_active(state),
            // One pending suffix at a time: chunks of one plan apply
            // sequentially in production; a competing plan is the
            // Rebalance interleavings.
            Action::RebalanceChunked => {
                self.chunked_plans && state.pending_plan.is_empty() && Self::planner_active(state)
            }
            Action::ApplyPendingUnit => !state.pending_plan.is_empty(),

            // The planner's cancellations stand down with the planner and never touch a hold;
            // production's fallback deletes are guarded per record and not modeled.
            Action::CancelDeadNewOwner(p) => {
                Self::planner_active(state)
                    && matches!(
                        state.handoffs.get(&p),
                        Some(h) if h.phase != Phase::Complete && !h.held && !state.pods[&h.new_owner].registered
                    )
            }
            Action::Cancel(p) => {
                state.cancels_left > 0
                    && Self::planner_active(state)
                    && matches!(state.handoffs.get(&p), Some(h) if h.phase != Phase::Complete && !h.held)
            }
            // The quorum/drain/warm predicates are the expensive half and
            // stay in the arm; a handoff short of Complete must exist, and
            // a hold stops at Draining.
            Action::AdvancePhase(p) => {
                matches!(
                    state.handoffs.get(&p),
                    Some(h) if h.phase != Phase::Complete && !(h.held && h.phase == Phase::Draining)
                )
            }
            Action::CleanupComplete(p) => {
                matches!(state.handoffs.get(&p), Some(h) if h.phase == Phase::Complete)
            }

            Action::MigrateRequest => {
                state.migrations_left > 0 && !state.requested && state.migration.is_none()
            }
            // Admission refuses a start mid-rollout or while a generation drains.
            Action::MigrateStart => {
                state.requested
                    && state.migration.is_none()
                    && state.config.draining.is_none()
                    && self.hold_pods == 0
                    && (!self.quiet_start || Self::quiet(state))
            }
            Action::MigrateRequestExpires => state.requested,
            Action::MigrateDrive => state.migration.is_some(),
            Action::MigrateCancel => state
                .migration
                .is_some_and(|m| m.phase.may_transition_to(MigrationPhase::Cancelling)),
            Action::SealTick(x) => {
                let pod = &state.pods[&x];
                pod.running
                    && pod.registered
                    && !pod.seal_broken
                    && state
                        .migration
                        .is_some_and(|m| m.phase == MigrationPhase::Sealing)
            }
            Action::SealGraceElapses => {
                self.seal_grace
                    && !state.seal_overdue
                    && state
                        .migration
                        .is_some_and(|m| m.phase == MigrationPhase::Sealing)
            }
            Action::BreakSeal(x) => {
                let pod = &state.pods[&x];
                state.seal_breaks_left > 0
                    && pod.running
                    && pod.registered
                    && !pod.seal_broken
                    && state
                        .migration
                        .is_some_and(|m| m.phase == MigrationPhase::Sealing)
            }
            Action::AdoptConfig(r) => {
                let router = &state.routers[&r];
                router.running && router.adopted.epoch < state.config.live.epoch
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
            last.config.live.partitions as u32,
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
                    held: false,
                    config_epoch: state.config.live.epoch,
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
                        basis: Self::plan_basis(state),
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
            // `apply_plan_on`: a moved basis stands the rest of the plan down.
            if self.plan_basis_guard && unit.basis != Self::plan_basis(state) {
                state.pending_plan.clear();
                state.pending_unit_dropped = true;
                return;
            }
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
            // Production stamps the epoch the plan was read under.
            let config_epoch = unit.basis.1;
            state.handoffs.insert(
                unit.partition,
                Handoff {
                    id,
                    old_owner: unit.old_owner,
                    new_owner: unit.new_owner,
                    phase: Phase::Freezing,
                    quorum: unit.quorum,
                    held: false,
                    config_epoch,
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
                // A hold stops here; the migration driver replaces it.
                if h.held {
                    return None;
                }
                let registered = production_registered(last);
                let acks = self.production_drained_acks(last, p);
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
                match pod.warmed.get(&p) {
                    // `warm_partition`, one step at a time (see
                    // `warm_step` for the two orderings under
                    // EpochFenced).
                    None => mutate(last, |state| self.warm_step(state, x, p, None)),
                    Some(w) if pod.fenced.contains(&p) => {
                        let log = (w.epoch, p);
                        mutate(last, |state| {
                            // `resume_partition`: re-take the broker fence the cancelled
                            // target may hold, or every write fails as fenced.
                            state.changelogs.get_mut(&log).unwrap().epoch_holder = Some(x);
                            state.pods.get_mut(&x).unwrap().fenced.remove(&p);
                        })
                    }
                    Some(_) => None,
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
                // The capture parks until the config reaches the handoff's epoch.
                if last.config.live.epoch < last.handoffs[&p].config_epoch {
                    return None;
                }
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
        let parked = Self::parked_at(router, p);
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
                // Complete: cut over the table, then drain `p`'s requests to the new owner.
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
                        Self::take_parked(state, r, p)
                    };
                    for entry in parked {
                        self.deliver(state, r, new_owner, p, entry);
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
                        Self::take_parked(state, r, p)
                    };
                    for entry in parked {
                        let Some(owner) = assignment else { continue };
                        self.deliver(state, r, owner, p, entry);
                    }
                })
            }
        }
    }

    fn production_drained_acks(&self, state: &SystemState, p: Partition) -> Vec<PodDrainedAck> {
        self.pod_ids()
            .filter_map(|x| {
                state.drained_acks.get(&(p, x)).map(|id| PodDrainedAck {
                    pod_name: pod_name(x),
                    partition: p as u32,
                    acked_at: 0,
                    acked_at_ms: 0,
                    handoff_id: id.to_string(),
                })
            })
            .collect()
    }

    fn registered_names(state: &SystemState) -> HashSet<String> {
        state
            .pods
            .iter()
            .filter(|(_, pod)| pod.registered)
            .map(|(x, _)| pod_name(*x))
            .collect()
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
                        sealed: BTreeSet::new(),
                        seal_broken: false,
                        zombie_writes_left: 0,
                        claims_authority: true,
                    },
                )
            })
            .collect();
        let live = Generation {
            partitions: self.partitions,
            epoch: 1,
        };
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
                        adopted: live,
                        table: BTreeMap::new(),
                        stashing: BTreeSet::new(),
                        stash: Vec::new(),
                    },
                )
            })
            .collect();
        let changelogs: BTreeMap<(Epoch, Partition), Changelog> = (0..self.partitions)
            .map(|p| ((live.epoch, p), Changelog::default()))
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
            config: Config {
                live,
                draining: None,
            },
            migration: None,
            seal_acks: BTreeMap::new(),
            pods,
            routers,
            changelogs,
            writes_left: self.writes,
            reads_left: self.reads,
            crashes_left: self.crashes,
            rejoins_left: self.rejoins,
            router_joins_left: self.router_joins,
            cancels_left: self.cancels,
            migrations_left: self.migrations,
            read_served: false,
            lost_acked_write: false,
            double_planned_handoff: false,
            stale_strong_read: false,
            mixed_modulus_acceptance: false,
            overtaken_request: false,
            reaffirmed: false,
            replaced_with_successor: false,
            cancelled_while_stash_parked: false,
            pending_unit_applied: false,
            pending_unit_dropped: false,
            migration_completed: false,
            migration_cancelled: false,
            sealed_without_warm: false,
            born_partition_write_parked: false,
            seal_overdue: false,
            seal_breaks_left: self.seal_breaks,
            requested: false,
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
        offer(Action::MigrateRequest);
        offer(Action::MigrateStart);
        offer(Action::MigrateRequestExpires);
        offer(Action::MigrateDrive);
        offer(Action::MigrateCancel);
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
            }
        }
        for key in self.key_ids() {
            for r in self.router_ids() {
                offer(Action::ClientWrite(r, key));
                offer(Action::ClientStrongRead(r, key));
            }
        }
        for r in self.router_ids() {
            offer(Action::AdoptConfig(r));
        }
        offer(Action::SealGraceElapses);
        for pod in self.pod_ids() {
            offer(Action::SealTick(pod));
            offer(Action::BreakSeal(pod));
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
            if self.claim_lapses {
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
                Self::clear_acks(state, p);
            }),

            // ── the migration saga ─────────────────────────────
            Action::MigrateRequest => mutate(last, |state| {
                state.migrations_left -= 1;
                state.requested = true;
            }),
            Action::MigrateRequestExpires => mutate(last, |state| state.requested = false),
            Action::MigrateStart => mutate(last, |state| {
                state.requested = false;
                state.migration = Some(Migration {
                    from: state.config.live,
                    to: self.migrate_to,
                    phase: MigrationPhase::Freezing,
                });
            }),
            Action::MigrateDrive => self.migrate_drive(last),
            Action::MigrateCancel => mutate(last, |state| {
                Self::set_phase(state, MigrationPhase::Cancelling);
            }),
            Action::SealTick(x) => self.seal_tick(last, x),
            Action::SealGraceElapses => mutate(last, |state| state.seal_overdue = true),
            Action::BreakSeal(x) => mutate(last, |state| {
                state.seal_breaks_left -= 1;
                state.pods.get_mut(&x).unwrap().seal_broken = true;
            }),
            Action::AdoptConfig(r) => mutate(last, |state| Self::adopt(state, r)),

            // ── pod converge ───────────────────────────────────
            Action::Converge(x, p) => self.converge(last, x, p),

            // ── router ─────────────────────────────────────────
            Action::Observe(r, p) => self.observe(last, r, p),

            // ── workload ───────────────────────────────────────
            Action::ClientWrite(r, key) => mutate(last, |state| {
                state.writes_left -= 1;
                // A rejected write still consumes its budget: the state
                // changed, so the transition is kept and rejected paths
                // are explored too.
                self.route(state, r, StashedRequest::Write(key));
            }),

            Action::ClientStrongRead(r, key) => mutate(last, |state| {
                state.reads_left -= 1;
                // Strong reads take the write path: parked while stashing
                // (#69456), else forwarded to the table entry.
                self.route(state, r, StashedRequest::StrongRead(key));
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
                pod.sealed.clear();
                pod.seal_broken = false;
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
                pod.sealed.clear();
                pod.seal_broken = false;
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
                pod.sealed.clear();
                pod.seal_broken = false;
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
            // The acked-write-loss invariant the drain, fence and HWM
            // machinery exists to uphold.
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
            Property::<Self>::always("no_overtaken_request", |_, s| !s.overtaken_request),
            // An ack lands in the live generation, never a retired one.
            Property::<Self>::always("no_mixed_modulus_acceptance", |_, s| {
                !s.mixed_modulus_acceptance
            }),
            // The ordinary handoff loop never moves a hold past Draining.
            Property::<Self>::always("holds_stop_at_draining", |_, s| {
                s.handoffs
                    .values()
                    .all(|h| !h.held || matches!(h.phase, Phase::Freezing | Phase::Draining))
            }),
            // Once flipped, no pod can produce to the old generation.
            Property::<Self>::always("old_generation_quiet_after_flip", |m, s| {
                s.config.draining.is_none_or(|g| {
                    !s.pods.iter().any(|(x, pod)| {
                        pod.warmed
                            .iter()
                            .any(|(p, w)| w.epoch == g.epoch && m.write_capable(s, *x, *p))
                    })
                })
            }),
            Property::<Self>::sometimes("migration_completes", |m, s| {
                m.migrations == 0 || s.migration_completed
            }),
            Property::<Self>::sometimes("migration_cancels", |m, s| {
                m.migrations == 0 || s.migration_cancelled
            }),
            // Sanity: the interesting states are actually reachable.
            Property::<Self>::sometimes("some_handoff_completes", |_, s| {
                s.handoffs.values().any(|h| h.phase == Phase::Complete)
            }),
            Property::<Self>::sometimes("some_write_accepted", |_, s| {
                s.changelogs.values().any(|log| !log.is_empty())
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
            // parked in a stash, and no migration left to request.
            Property::<Self>::eventually("converges_to_stable", |m, s| {
                // Ordered cheapest-first on purpose. This runs at every
                // explored state, and the placement computation below is
                // the one expensive part — it must stay behind the
                // conjuncts that reject most states outright.
                if !s.handoffs.is_empty()
                    || !s.pending_plan.is_empty()
                    || s.migration.is_some()
                    || s.requested
                    || s.migrations_left > 0
                {
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
                        (0..s.config.live.partitions).all(|p| {
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
                                && pod.claims_authority
                        })
                    });
                owners_converged
                    && m.router_ids().all(|r| {
                        let router = &s.routers[&r];
                        if !router.registered || !router.running {
                            return true;
                        }
                        router.adopted == s.config.live
                            && router.stashing.is_empty()
                            && router.stash.is_empty()
                            && s.assignments
                                .iter()
                                .all(|(p, owner)| router.table.get(p) == Some(owner))
                    })
            }),
        ];
        if self.probes && self.migrations > 0 {
            props.push(Property::<Self>::sometimes(
                "sealed_without_warm",
                |_, s| s.sealed_without_warm,
            ));
            props.push(Property::<Self>::sometimes(
                "born_partition_write_parked",
                |_, s| s.born_partition_write_parked,
            ));
        }
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
