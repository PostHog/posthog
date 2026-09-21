//! The scheduler seam: every ordering and placement decision in the batcher,
//! behind one interface.
//!
//! The scheduler decides which runs may go to a worker now, and where.
//! Nothing else in the batcher decides that. The seam is event-shaped: a
//! group arrives (`on_groups`), a request settles with success or failure
//! (`on_settled`), the parked-retry deadline fires (`on_parked_retry`). Each
//! call is one event, runs to completion, does no I/O, takes no locks, and
//! returns its effects as data: the dispatches to send, the deferral counts,
//! and the evicted keys. The caller owns the lock, the worker-health snapshot
//! ([`WorkerSnapshot`]), the in-flight load accounting, the sentinels, and the
//! sends.
//!
//! [`crate::key_table::KeyTableScheduler`] is the implementation.

use std::collections::HashMap;

use crate::order_sentinel::SendKind;
use crate::routing::WorkerLoad;
use crate::types::SerializedKafkaMessage;
use crate::worker_registry::WorkerId;

/// A point-in-time snapshot of the worker world, captured by the caller
/// before a seam call so the scheduler decides over data instead of querying
/// the registry and the peer tracker itself.
pub struct WorkerSnapshot {
    /// Routable workers.
    pub healthy: Vec<WorkerId>,
    /// Candidates for fresh keys: the aperture ring slice when narrowing
    /// applies, otherwise the healthy pool.
    pub candidates: Vec<WorkerId>,
    /// Outstanding messages per worker (the caller's in-flight table).
    pub load: WorkerLoad,
    /// Health per known worker. A worker absent here is dead (removed from
    /// the registry) and not draining, matching the registry's answers.
    workers: HashMap<WorkerId, WorkerHealth>,
}

pub struct WorkerHealth {
    pub dead: bool,
    pub draining: bool,
}

impl WorkerSnapshot {
    pub fn new(
        healthy: Vec<WorkerId>,
        candidates: Vec<WorkerId>,
        load: WorkerLoad,
        workers: HashMap<WorkerId, WorkerHealth>,
    ) -> Self {
        Self {
            healthy,
            candidates,
            load,
            workers,
        }
    }

    pub fn is_dead(&self, worker: &WorkerId) -> bool {
        self.workers.get(worker).is_none_or(|health| health.dead)
    }

    pub fn is_draining(&self, worker: &WorkerId) -> bool {
        self.workers
            .get(worker)
            .is_some_and(|health| health.draining)
    }
}

/// One run of one key's messages arriving at the seam.
pub struct KeyRun {
    pub routing_key: String,
    pub messages: Vec<SerializedKafkaMessage>,
}

/// One run of one key, placed on the chosen worker.
pub struct Dispatch {
    pub worker: WorkerId,
    pub routing_key: String,
    pub messages: Vec<SerializedKafkaMessage>,
    /// Fresh assignment or a retry of a failed send; the key-order sentinel
    /// notes the send under this kind.
    pub kind: SendKind,
    /// The run's epoch, for stamping its completions.
    pub assignment_epoch: u64,
}

/// One resolved send arriving at the seam.
pub struct Settlement {
    pub worker: WorkerId,
    /// The resolved send's message count, for the caller's load accounting;
    /// the scheduler does not read it.
    pub message_count: usize,
    /// Unique routing keys the send carried.
    pub routing_keys: Vec<String>,
    pub outcome: SettlementOutcome,
}

pub enum SettlementOutcome {
    Delivered,
    /// The send failed; its runs come back for replay, already named by the
    /// caller. Requeue happens before the keys are released, in this one
    /// call, so a newer send can never overtake the failed messages.
    ///
    /// The settlement's `routing_keys` must name every run's key: a run
    /// whose key is missing is requeued but never released, and the key
    /// stays outstanding forever.
    Failed {
        batch_id: String,
        runs: Vec<KeyRun>,
    },
}

/// Groups deferred by one seam call, by reason. The caller emits the debug
/// events from these; the scheduler emits its own counters.
#[derive(Default)]
pub struct DeferredCounts {
    /// The key already has queued or outstanding work; newer messages queue
    /// behind it.
    pub queued_behind_deferral: u64,
    /// No worker was routable.
    pub unroutable: u64,
    /// A failed send's messages went back to the queue.
    pub send_failed: u64,
}

impl DeferredCounts {
    pub fn total(&self) -> u64 {
        self.queued_behind_deferral + self.unroutable + self.send_failed
    }
}

/// One seam call's effects, as data.
#[must_use]
#[derive(Default)]
pub struct SchedulerEffects {
    /// Runs to send now, in decision order. The caller establishes send
    /// order from this order and must send every dispatch, from every seam
    /// call: the scheduler already counts the dispatched keys as in flight,
    /// so a dropped dispatch strands them.
    pub dispatches: Vec<Dispatch>,
    pub deferred: DeferredCounts,
    /// Keys evicted from the scheduler's state: nothing is in flight or
    /// queued for them, so their order-sentinel state can go.
    pub evicted_keys: Vec<String>,
}

impl SchedulerEffects {
    pub(crate) fn with_dispatch_capacity(capacity: usize) -> Self {
        Self {
            dispatches: Vec::with_capacity(capacity),
            ..Self::default()
        }
    }
}

/// The decision core: which runs may go to a worker now, and where.
///
/// The caller owes the seam two things: it sends every dispatch an effects
/// value carries, and every sent dispatch settles exactly once via
/// [`Scheduler::on_settled`]. Settlement is the only release path for an
/// outstanding key, so a dropped dispatch or a lost settlement wedges that
/// key permanently.
pub trait Scheduler {
    /// One poll's key runs arrived, in batch order, collected under
    /// `assignment_epoch`. A key may repeat; its runs merge in queue order.
    fn on_groups(
        &mut self,
        snapshot: &WorkerSnapshot,
        batch_id: &str,
        assignment_epoch: u64,
        groups: Vec<KeyRun>,
    ) -> SchedulerEffects;

    /// A send settled, with success or failure.
    fn on_settled(&mut self, snapshot: &WorkerSnapshot, settlement: Settlement)
        -> SchedulerEffects;

    /// The parked-retry deadline fired: retry every parked key.
    fn on_parked_retry(&mut self, snapshot: &WorkerSnapshot) -> SchedulerEffects;

    /// Partitions were revoked, as `(topic, partition)`. Queued messages for
    /// them must drop: the new partition owner replays them.
    fn on_partitions_revoked(&mut self, partitions: &[(String, i32)]) -> SchedulerEffects;
}

/// Working load for one seam call: each healthy worker's outstanding load,
/// bumped as runs are placed, so placement within the call accounts for
/// earlier picks.
pub(crate) fn working_load(snapshot: &WorkerSnapshot) -> WorkerLoad {
    snapshot
        .healthy
        .iter()
        .map(|w| (w.clone(), snapshot.load.get(w).copied().unwrap_or(0)))
        .collect()
}

/// Add `count` to a worker's working load for this round, if it is a candidate.
/// Workers that aren't routing candidates have no entry and don't affect
/// selection, so they're skipped.
pub(crate) fn bump_load(working_load: &mut WorkerLoad, worker: &WorkerId, count: usize) {
    if let Some(load) = working_load.get_mut(worker) {
        *load = load.saturating_add(count);
    }
}
