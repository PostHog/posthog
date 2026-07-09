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
pub type WriteId = u8;

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
}

/// Per-partition warm state on a pod — everything the invariants need to
/// know about one warmed partition.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct WarmState {
    /// The Kafka transactional-producer epoch held (production:
    /// `init_transactions` under the `EpochFenced` variant; the broker
    /// rejects produces bearing a stale epoch).
    pub epoch: u8,
    /// The changelog HWM captured at warm time — everything below it is
    /// visible to this pod's cache.
    pub cutoff: u8,
    /// Writes this pod itself accepted since warming. `cutoff + accepted`
    /// is the pod's visible prefix of the changelog; a strong read served
    /// while `changelog.len` exceeds it returns stale data.
    pub accepted: u8,
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
    /// Write-fenced partitions (production: `InflightTracker` fences +
    /// the pod handle's `fenced_partitions`).
    pub fenced: BTreeSet<Partition>,
    /// Remaining writes this pod may accept after losing its lease before
    /// its keepalive notices and the process self-fences (production: the
    /// bounded zombie window; fix 1 bounds it to ~one heartbeat tick).
    pub zombie_writes_left: u8,
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
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum StashedRequest {
    Write(WriteId),
    StrongRead,
}

/// The Kafka changelog for one partition, reduced to what the safety
/// invariants need: an append counter (the HWM) and the producer epoch
/// the broker currently accepts.
#[derive(Clone, Debug, Default, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Changelog {
    /// Number of records appended (the HWM).
    pub len: u8,
    /// Broker-side producer epoch. Bumped by each warm under the
    /// `EpochFenced` variant (production: `init_transactions` fencing);
    /// ignored by `Current`.
    pub epoch: u8,
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
    pub next_write_id: WriteId,
    /// Count of strong reads actually served (reachability evidence for
    /// the read properties).
    pub reads_served: u8,

    // ── violation flags (history-free invariant encoding) ──────
    /// Set when a write is acked by a pod while a *different* pod that
    /// the protocol has designated as the (incoming or current) owner
    /// has already warmed — the acked write sits beyond that owner's
    /// warm cutoff and is invisible to it forever. This is the
    /// acked-write loss the drain/fence/HWM machinery exists to prevent.
    pub lost_acked_write: bool,
    /// Set when a strong read is served by a pod whose visible prefix
    /// (`cutoff + accepted`) is behind the changelog — the read returned
    /// state missing at least one acked write.
    pub stale_strong_read: bool,
}

/// Everything that can happen, from every actor, including failures.
/// The checker interleaves these exhaustively.
#[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Action {
    // ── coordinator (pure derivation over etcd state) ──────────
    /// The cleanup half of `handle_pod_change` for one partition:
    /// atomically check-and-delete a handoff whose new owner is
    /// unregistered (the mod_revision guard is what makes modeling this
    /// as atomic faithful). Scheduled independently of `Rebalance` and
    /// `AdvancePhase` — the coordinator's watch handlers and tick run
    /// concurrently in production, and an overlapping outgoing
    /// coordinator is just more interleavings of the same guarded
    /// actions.
    CleanupStale(Partition),
    /// The rebalance half of `handle_pod_change`: when no handoffs are
    /// in flight, create Freezing handoffs for every assignment diff in
    /// one transaction.
    Rebalance,
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
}
