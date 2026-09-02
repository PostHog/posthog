//! State types for the personhog handoff-protocol model.
//!
//! Every field maps to a production counterpart (see the README mapping
//! table). The whole distributed system — etcd, coordinator, routers,
//! leader pods, and the Kafka changelog — is one plain-data `SystemState`
//! so the checker can hash, compare, and exhaustively explore it.

use std::collections::{BTreeMap, BTreeSet};

pub type PodId = u8;
pub type RouterId = u8;
pub type Partition = u8;
/// Identity of one handoff attempt — production `HandoffState.handoff_id`.
/// Acks echo it and quorum checks only count matching acks.
pub type HandoffId = u8;

/// The production phase enum, used directly: a new phase added to the
/// protocol breaks the model's exhaustive matches at compile time.
pub use personhog_coordination::types::HandoffPhase as Phase;

/// Production `HandoffState`, in compact model form (u8 ids; the model
/// materializes production-typed views when calling shared logic).
#[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Handoff {
    pub id: HandoffId,
    pub old_owner: Option<PodId>,
    pub new_owner: PodId,
    pub phase: Phase,
    /// The freeze-quorum snapshot: routers registered when the rebalance
    /// created this handoff (production `HandoffState::freeze_quorum`,
    /// always captured — the model never writes legacy records, so the
    /// production `None` fallback is pinned by unit tests instead).
    /// With `RouterJoin` in the action space this diverges from the live
    /// registry, which is exactly what the checker is here to explore.
    pub quorum: BTreeSet<RouterId>,
}

/// Per-partition warm state on a pod — everything the invariants need to
/// know about one warmed partition.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct WarmState {
    /// What this warm was installed for (production:
    /// `WarmProvenance` on the pod handle). `None` is a serving-era warm
    /// (restart, or the returning old owner of an in-flight handoff);
    /// `Some(id)` was installed for that handoff's Warming. An Acquiring
    /// convergence honors a warm only when it carries the current
    /// handoff's id — anything else is a leftover from an earlier era
    /// whose cache may predate writes accepted since, and is released
    /// and rebuilt.
    pub for_handoff: Option<HandoffId>,
    /// How much of the changelog this pod's cache reflects: the HWM
    /// captured at warm time, plus every write it has accepted since. A
    /// strong read served while `changelog.len` exceeds this returns state
    /// missing at least one acked write.
    ///
    /// The two halves are deliberately one number. Nothing reads them
    /// apart — the cutoff is never consulted on its own, and the accept
    /// count only ever advances the same total — so keeping them separate
    /// would only split behaviorally identical states (warmed at 1 and
    /// accepted nothing, versus warmed at 0 and accepted one).
    pub visible: u8,
}

/// A warm caught between its two steps, under the rejected read-first
/// ordering: the changelog read is taken while the fence — and with it
/// the rejection of a stale owner's write — does not exist yet, so a
/// write can be acked into the gap and sit above the cutoff forever.
///
/// Fence-first needs no such state. Its epoch bump precedes the read and
/// an append requires an installed warm carrying the current epoch, so
/// nothing can append between the two steps and the model installs the
/// warm atomically.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct PendingWarm {
    /// The changelog length captured before the fence existed.
    pub cutoff: u8,
}

/// One leader pod. `registered` is the etcd lease-bound registration key;
/// everything else is process memory and dies with the process.
#[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Pod {
    /// The etcd registration key exists (production: lease alive).
    pub registered: bool,
    /// The process is running and its data plane serves requests.
    pub running: bool,
    /// Partitions warmed by this process incarnation (production:
    /// `warmed_partitions` on the pod handle).
    pub warmed: BTreeMap<Partition, WarmState>,
    /// Warms mid-flight under `EpochFenced` — one step of
    /// `warm_partition` done, the other not (empty under `Current`,
    /// whose warm has no broker step to separate from the read).
    pub pending_warm: BTreeMap<Partition, PendingWarm>,
    /// Write-fenced partitions (production: `InflightTracker` fences +
    /// the pod handle's `fenced_partitions`).
    pub fenced: BTreeSet<Partition>,
    /// Remaining writes this pod may accept after losing its lease before
    /// its keepalive notices and the process self-fences (production: the
    /// bounded zombie window; fix 1 bounds it to ~one heartbeat tick).
    pub zombie_writes_left: u8,
    /// Whether this pod still claims the right to serve (production: the
    /// `AuthorityClock` the keepalive stamps and the data plane reads).
    ///
    /// Deliberately not the same fact as `registered`. A lease can be
    /// revoked out from under a pod, leaving it claiming a partition it
    /// no longer holds until something tells it otherwise — which is the
    /// window the read gate is trying to close, and cannot be expressed
    /// if the two are one flag.
    pub claims_authority: bool,
}

/// One router. A clean router restart is indistinguishable from a
/// delayed `Observe` (production `load_initial` rebuilds everything from
/// etcd before serving), so restarts need no modeling — but lease expiry
/// does: an unregistered router is excluded from the freeze quorum while
/// its process may keep routing with a stale table until its keepalive
/// self-fences it (the zombie-router half of the double-zombie residual).
#[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Router {
    /// The etcd registration key exists (production: lease alive). Only
    /// registered routers count toward the freeze quorum.
    pub registered: bool,
    /// The process is running and forwards traffic.
    pub running: bool,
    /// partition → pod the router forwards to (production: the shared
    /// routing table, edge-updated from handoff Complete events).
    pub table: BTreeMap<Partition, PodId>,
    /// Partitions currently buffering leader-path requests (production:
    /// the `StashTable`).
    pub stashing: BTreeSet<Partition>,
    /// Parked leader-path requests in arrival order (production:
    /// `StashedRequest` queues, which carry their gRPC method so writes
    /// and strong reads share one per-partition FIFO).
    pub stash: BTreeMap<Partition, Vec<StashedRequest>>,
}

/// One parked leader-path request.
///
/// Deliberately identity-free. A parked write is only ever drained or
/// dropped, never matched against a particular client, so carrying a write
/// id would add a dimension to the state space that nothing reads — two
/// otherwise-identical states would differ only in how many writes had ever
/// been parked. Order and count still matter, and the per-partition `Vec`
/// keeps both.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum StashedRequest {
    Write,
    StrongRead,
}

/// The Kafka changelog for one partition, reduced to what the safety
/// invariants need: an append counter (the HWM) and who currently holds
/// the broker's producer fence.
#[derive(Clone, Debug, Default, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Changelog {
    /// Number of records appended (the HWM).
    pub len: u8,
    /// The pod whose transactional producer the broker currently accepts,
    /// under `Variant::EpochFenced` (production: the latest
    /// `init_transactions` wins and every earlier producer is fenced out).
    /// Always `None` under `Current`, which has no broker-side fence.
    ///
    /// This is an owner rather than an epoch number because nothing
    /// compares epochs for order — the single consumer asks whether *this*
    /// pod's producer is the live one. A counter would have split states
    /// that differ only in how many fences had been acquired along the way,
    /// and, being a `u8`, would eventually have wrapped a stale epoch onto
    /// a live one and admitted a write it should reject.
    pub epoch_holder: Option<PodId>,
}

/// One planned-but-unapplied handoff from a chunked plan: the placement
/// decision plus its plan-time guards (production: a later `apply_plan`
/// chunk, applied without re-reading).
#[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct PendingUnit {
    pub partition: Partition,
    pub old_owner: Option<PodId>,
    pub new_owner: PodId,
    /// Freeze requirement snapshotted at plan time.
    pub quorum: BTreeSet<RouterId>,
    /// Assignment version at plan time (production: the mod_revision
    /// its `AssignmentPrecondition` compares; 0 = Absent).
    pub expected_assignment_version: u8,
}

/// The entire distributed system. One value = one node in the explored
/// state graph.
#[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct SystemState {
    // ── durable (etcd) ─────────────────────────────────────────
    /// partition → owning pod (production: `PartitionAssignment`; flips
    /// only atomically with a handoff reaching Complete).
    pub assignments: BTreeMap<Partition, PodId>,
    /// In-flight handoffs, at most one per partition.
    pub handoffs: BTreeMap<Partition, Handoff>,
    /// (partition, router) → handoff id acked (production:
    /// `RouterFreezeAck` with `handoff_id`).
    pub freeze_acks: BTreeMap<(Partition, RouterId), HandoffId>,
    /// (partition, pod) → handoff id acked (production: `PodDrainedAck`).
    pub drained_acks: BTreeMap<(Partition, PodId), HandoffId>,
    /// (partition, pod) → handoff id acked (production: `PodWarmedAck`).
    pub warmed_acks: BTreeMap<(Partition, PodId), HandoffId>,
    /// Monotonic handoff id allocator (production: `new_handoff_id`).
    pub next_handoff_id: HandoffId,
    /// Unapplied suffix of a chunked plan, front unit next
    /// (production: `apply_plan`'s later chunks).
    pub pending_plan: Vec<PendingUnit>,
    /// partition → count of assignment writes (production: the
    /// mod_revision an `AssignmentPrecondition` compares). Only
    /// maintained under `chunked_plans`.
    pub assignment_versions: BTreeMap<Partition, u8>,

    // ── processes ──────────────────────────────────────────────
    pub pods: BTreeMap<PodId, Pod>,
    pub routers: BTreeMap<RouterId, Router>,

    // ── kafka ──────────────────────────────────────────────────
    pub changelogs: BTreeMap<Partition, Changelog>,

    // ── failure/workload budgets (bound the state space) ───────
    pub writes_left: u8,
    pub reads_left: u8,
    pub crashes_left: u8,
    pub rejoins_left: u8,
    /// Times a router may (re)join: a late slot coming up for the first
    /// time, or a dead router returning as a fresh process.
    pub router_joins_left: u8,
    /// Deadline cancellations the checker may still inject.
    pub cancels_left: u8,
    /// Whether any strong read was actually served (reachability evidence
    /// for the read properties). A flag rather than a count: nothing reads
    /// how many, and a count would split otherwise-identical states by
    /// their read history.
    pub read_served: bool,

    // ── violation flags (history-free invariant encoding) ──────
    /// Set when a write is acked by a pod while a *different* pod that
    /// the protocol has designated as the (incoming or current) owner
    /// has already warmed — the acked write sits beyond that owner's
    /// warm cutoff and is invisible to it forever. This is the
    /// acked-write loss the drain/fence/HWM machinery exists to prevent.
    pub lost_acked_write: bool,
    /// Set when a rebalance plans a partition that already has an
    /// in-flight handoff, clobbering it — the overlap
    /// `plan_partial_rebalance`'s pinning must make unreachable.
    pub double_planned_handoff: bool,
    /// Set when a strong read is served by a pod whose `WarmState::visible`
    /// prefix is behind the changelog — the read returned state missing at
    /// least one acked write.
    pub stale_strong_read: bool,

    // ── reachability flags (probe evidence, history encoding) ──
    /// A cancellation resolved as a reaffirm-Complete toward the live
    /// current owner.
    pub reaffirmed: bool,
    /// A cancellation resolved as an atomic successor replacement.
    pub replaced_with_successor: bool,
    /// A cancellation happened while some router held parked requests
    /// for the partition — the composition the replacement design must
    /// keep safe and live.
    pub cancelled_while_stash_parked: bool,
    /// A pending chunk unit applied after its plan's first transaction.
    pub pending_unit_applied: bool,
    /// A pending chunk unit dropped by a failed plan-time guard.
    pub pending_unit_dropped: bool,
}

/// Everything that can happen, from every actor, including failures.
/// The checker interleaves these exhaustively.
#[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Action {
    // ── coordinator (pure derivation over etcd state) ──────────
    /// Cancellation of a handoff whose new owner is unregistered — the
    /// dead-new-owner arm of the coordinator's cleanup, as a
    /// mod_revision-guarded atomic *replacement*: the record is swapped
    /// for whatever resolves its stashes (a reaffirm-Complete toward a
    /// live current owner, a successor Freezing handoff, or — only when
    /// nothing is placeable — a plain delete). Scheduled independently
    /// of `Rebalance` and `AdvancePhase` — the coordinator's watch
    /// handlers and tick run concurrently in production, and an
    /// overlapping outgoing coordinator is just more interleavings of
    /// the same guarded actions.
    CancelDeadNewOwner(Partition),
    /// Deadline cancellation of any in-flight handoff, with the same
    /// replacement disposition. The model has no clock, so the deadline
    /// trigger is "the checker schedules this whenever it likes" — a
    /// superset of every timing policy production could apply, which is
    /// exactly what makes the phase-aware deadline a production-only
    /// concern. Budgeted (`cancels_left`): an unbounded cancel action
    /// would let the checker cancel forever and vacuously defeat the
    /// convergence property.
    Cancel(Partition),
    /// The rebalance half of `handle_pod_change`: when no handoffs are
    /// in flight, create Freezing handoffs for every assignment diff in
    /// one transaction.
    Rebalance,
    /// The same rebalance applying its plan in chunks (production:
    /// `apply_plan` past the txn budget): the first planned handoff
    /// lands now, the rest wait in `pending_plan`.
    RebalanceChunked,
    /// Apply the front `pending_plan` unit — or drop it when its
    /// plan-time guards no longer hold (a conflicted unit standing down).
    ApplyPendingUnit,
    /// `check_phase_advance` for one partition (watch nudge or tick).
    AdvancePhase(Partition),
    /// Post-Complete cleanup: delete the handoff record and its acks
    /// (guarded on the record still being the same attempt).
    CleanupComplete(Partition),

    // ── pods (the converge model) ──────────────────────────────
    /// One convergence step for (pod, partition): derive the desired
    /// state from durable state and apply the next transition toward it
    /// (warm / fence+ack / warm+ack / release / unfence).
    Converge(PodId, Partition),

    // ── routers ────────────────────────────────────────────────
    /// The router observes the current durable state of one partition
    /// and reacts: stash+ack during a handoff, cutover+drain at
    /// Complete, drain-back on cancellation. A stale router is modeled
    /// by the checker simply not scheduling this action for a while.
    Observe(RouterId, Partition),

    // ── workload ───────────────────────────────────────────────
    /// A client write for (router, partition): stashes if the router is
    /// stashing, otherwise forwards to the router's table entry.
    ClientWrite(RouterId, Partition),
    /// A strong read for (router, partition): parks with the writes in
    /// the per-partition FIFO when the partition is stashing (the shipped
    /// read-stashing design), otherwise forwards to the table entry.
    ClientStrongRead(RouterId, Partition),

    // ── failures ───────────────────────────────────────────────
    /// The pod process dies and instantly restarts under the same name
    /// before its lease expires: registration and assignments survive,
    /// all process memory (warmed, fenced) is wiped.
    CrashRestartWithinTtl(PodId),
    /// The pod's lease expires while the process is still running: the
    /// registration disappears, but the data plane keeps serving for a
    /// bounded number of writes (the zombie window) until `SelfFence`.
    LeaseExpire(PodId),
    /// The zombie's keepalive notices the dead lease and the process
    /// exits (production fix 1).
    SelfFence(PodId),
    /// A pod notices its lease is gone and stops claiming the partitions
    /// it holds (production: the keepalive's next round, or the
    /// registration watch firing). Only reachable under delayed
    /// detection; prompt detection drops the claim with the lease.
    NoticeLeaseLoss(PodId),
    /// A pod's published claim ages past the renewal margin while its
    /// registration still stands (production: the keepalive stops
    /// confirming, but etcd holds the lease until the full TTL). The pod
    /// refuses to serve and the coordinator, seeing a live registration,
    /// reassigns nothing.
    AuthorityLapse(PodId),
    /// A renewal lands and the claim comes back, without the session ever
    /// having ended.
    AuthorityRenew(PodId),
    /// A previously-dead pod rejoins under its old name: fresh
    /// registration, fresh lease, empty memory (production: normal pod
    /// startup; its partitions come back via Warming handoffs from the
    /// rebalance its registration triggers).
    Join(PodId),
    /// The router's lease expires while its process keeps running: it
    /// drops out of the freeze quorum but continues routing with its
    /// current table, and stops processing events (its watch loop is on
    /// its way down).
    RouterLeaseExpire(RouterId),
    /// The zombie router's keepalive notices the dead lease and the
    /// process exits (production fix 1).
    RouterSelfFence(RouterId),
    /// A router process starts and registers: a late slot coming up
    /// mid-run, or a dead router returning under its old name. Fresh
    /// process, empty table — production `load_initial` starts from an
    /// empty routing table that fails every lookup closed, and the
    /// model's `Observe` is its bootstrap. A joiner whose `Observe` the
    /// checker never schedules is precisely the silent late joiner the
    /// freeze-quorum snapshot exists to tolerate: registered, counted by
    /// the legacy live-set rule, acking nothing.
    RouterJoin(RouterId),
}
