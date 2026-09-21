use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use common_kafka_consumer::{Offset, Partition};
use k8s_awareness::PeerTracker;
use metrics::{counter, histogram};

use crate::aperture;
use crate::debug_recorder::{
    record_if, DebugEventKind, DebugRecorder, DispatcherLoad, LoadEntry, RoutingDebug, SubBatchInfo,
};
use crate::key_table::KeyTableScheduler;
use crate::order_sentinel::KeyOrderSentinel;
use crate::routing::{Router, RoutingStrategy, WorkerLoad};
use crate::scheduler::{
    Dispatch, KeyRun, Scheduler, SchedulerEffects, Settlement, SettlementOutcome, WorkerHealth,
    WorkerSnapshot,
};
use crate::types::{Accumulator, Group, SerializedKafkaMessage};
use crate::worker_registry::{WorkerId, WorkerRegistry};

/// The max offset a sub-batch carries for one routing key, over keyed
/// messages only (null-key offsets live on arbitrary partitions and carry no
/// per-key order promise). Passed back via
/// [`Dispatcher::on_sub_batch_acked`] when the worker ACKs, so the
/// [`KeyOrderSentinel`] can advance the key's ACK high-water mark.
#[derive(Clone)]
pub struct KeyOffset {
    pub routing_key: String,
    pub max_offset: i64,
}

/// A slice of a batch assigned to one worker, carrying the messages and the
/// routing keys they belong to. Routing keys are passed back at settlement so
/// the scheduler can release them.
pub struct SubBatch {
    pub worker: WorkerId,
    pub messages: Vec<SerializedKafkaMessage>,
    /// Unique routing keys contained in this sub-batch. Pass back to
    /// `Dispatcher::settle` on ACK or DLQ.
    pub routing_keys: Vec<String>,
    /// Per-key max offsets. Pass back to `Dispatcher::on_sub_batch_acked` on
    /// a successful ACK (only) so the order sentinel tracks ACK progress.
    pub key_offsets: Vec<KeyOffset>,
    /// The runs' epoch, for stamping completions.
    pub assignment_epoch: u64,
}

struct WorkerSubBatchBuilder {
    messages: Vec<SerializedKafkaMessage>,
    routing_keys: Vec<String>,
    key_offsets: Vec<KeyOffset>,
}

impl WorkerSubBatchBuilder {
    fn is_empty(&self) -> bool {
        self.messages.is_empty()
    }

    fn message_count(&self) -> usize {
        self.messages.len()
    }
}

#[derive(Default)]
struct WorkerAssignments {
    /// Keyed by worker and epoch, so a sub-batch never mixes runs from two
    /// epochs and its completions carry one stamp.
    by_worker: HashMap<(WorkerId, u64), WorkerSubBatchBuilder>,
}

impl WorkerAssignments {
    fn new() -> Self {
        Self::default()
    }

    fn add_dispatch(&mut self, dispatch: Dispatch) {
        let Dispatch {
            worker,
            routing_key,
            messages,
            assignment_epoch,
            ..
        } = dispatch;
        let builder = self
            .by_worker
            .entry((worker, assignment_epoch))
            .or_insert_with(|| WorkerSubBatchBuilder {
                messages: Vec::new(),
                routing_keys: Vec::new(),
                key_offsets: Vec::new(),
            });

        // Only keyed messages participate in the key-order sentinel: an
        // unkeyed message lives on an arbitrary partition and is grouped under
        // a synthetic key, so it has no ACK watermark to advance.
        if let Some(max_offset) = messages
            .iter()
            .filter(|m| m.key.is_some())
            .map(|m| m.offset)
            .max()
        {
            builder.key_offsets.push(KeyOffset {
                routing_key: routing_key.clone(),
                max_offset,
            });
        }
        builder.messages.extend(messages);
        builder.routing_keys.push(routing_key);
    }

    fn sub_batch_infos(&self) -> Vec<SubBatchInfo> {
        self.by_worker
            .iter()
            .filter(|(_, builder)| !builder.is_empty())
            .map(|((worker, _), builder)| SubBatchInfo {
                worker: worker.to_string(),
                messages: builder.message_count(),
                routing_keys: builder.routing_keys.len(),
            })
            .collect()
    }

    fn routed_counts(&self) -> impl Iterator<Item = (WorkerId, usize)> + '_ {
        self.by_worker
            .iter()
            .filter(|(_, builder)| !builder.is_empty())
            .map(|((worker, _), builder)| (worker.clone(), builder.message_count()))
    }

    fn into_sub_batches(self) -> Vec<SubBatch> {
        self.by_worker
            .into_iter()
            .filter(|(_, builder)| !builder.is_empty())
            .map(|((worker, assignment_epoch), builder)| SubBatch {
                worker,
                messages: builder.messages,
                routing_keys: builder.routing_keys,
                key_offsets: builder.key_offsets,
                assignment_epoch,
            })
            .collect()
    }
}

/// The immediate result of assigning one submission while the scheduler lock
/// is held. `retained` describes this submission, not mutable table state that
/// a later task might observe after a purge or settlement.
pub struct Submission<T> {
    pub pending: Vec<T>,
    pub retained: bool,
}

/// The scheduler and the load table, behind the dispatcher's single Mutex.
struct DispatcherInner {
    /// The decision core. Every ordering and placement decision happens in
    /// its seam calls; the dispatcher applies the returned effects.
    scheduler: KeyTableScheduler,
    /// Outstanding (in-flight) message count per worker. Both routing
    /// strategies use it as the per-worker load signal so new key-groups land
    /// on lightly-loaded workers — load is balanced by message volume rather
    /// than by sub-batch count. A worker with no outstanding messages has no
    /// entry.
    in_flight: WorkerLoad,
}

/// Routes batches to workers: the plumbing around the [`Scheduler`] seam.
///
/// The dispatcher owns the lock, the in-flight load table, the metrics and
/// debug events, the sentinel calls, and the sub-batch assembly. Every
/// ordering and placement decision — dispatch a runnable key, queue behind
/// its outstanding request, park it unroutable, evict on settle — lives in
/// the scheduler behind the seam. The dispatcher captures a
/// [`WorkerSnapshot`] before each seam call and applies the returned
/// [`SchedulerEffects`].
pub struct Dispatcher {
    inner: Mutex<DispatcherInner>,
    registry: Arc<WorkerRegistry>,
    /// The configured routing strategy; the scheduler owns the router itself.
    /// Kept here for view construction (aperture narrowing) and debug.
    strategy: RoutingStrategy,
    /// Per-key send/ACK order checker. Called under the inner lock (lock
    /// order: inner → sentinel; the sentinel never takes the inner lock),
    /// so its check order matches the intended per-key send order.
    key_sentinel: Arc<KeyOrderSentinel>,
    /// Peer tracker + aperture width for [`RoutingStrategy::Aperture`]: this
    /// dispatcher's ring slice is derived from its agreed peer index. `None`
    /// (or a not-yet-known peer index) falls back to the full healthy pool.
    aperture: Option<(Arc<PeerTracker>, usize)>,
    /// Debug event recorder; `None` unless `DEBUG_API_ENABLED`.
    debug_recorder: Option<Arc<DebugRecorder>>,
}

impl Dispatcher {
    /// Construct a dispatcher with the default routing strategy.
    pub fn new(registry: Arc<WorkerRegistry>) -> Self {
        Self::with_strategy(registry, RoutingStrategy::default())
    }

    /// Construct a dispatcher with an explicit routing strategy.
    pub fn with_strategy(registry: Arc<WorkerRegistry>, strategy: RoutingStrategy) -> Self {
        Self::from_router(registry, strategy, Router::new(strategy))
    }

    /// Test-only constructor with a seeded RNG so P2C selection is deterministic.
    #[cfg(test)]
    fn with_strategy_seeded(
        registry: Arc<WorkerRegistry>,
        strategy: RoutingStrategy,
        seed: u64,
    ) -> Self {
        Self::from_router(registry, strategy, Router::with_seed(strategy, seed))
    }

    fn from_router(
        registry: Arc<WorkerRegistry>,
        strategy: RoutingStrategy,
        router: Router,
    ) -> Self {
        Self {
            inner: Mutex::new(DispatcherInner {
                scheduler: KeyTableScheduler::new(router),
                in_flight: WorkerLoad::new(),
            }),
            registry,
            strategy,
            key_sentinel: Arc::new(KeyOrderSentinel::new()),
            aperture: None,
            debug_recorder: None,
        }
    }

    /// The per-key order sentinel, shared with the consumer's rdkafka context
    /// so rebalances can reset its baselines.
    pub fn key_order_sentinel(&self) -> Arc<KeyOrderSentinel> {
        Arc::clone(&self.key_sentinel)
    }

    /// Enable deterministic-aperture candidate narrowing: fresh keys route
    /// within this dispatcher's slice of the worker ring, `min_aperture` wide.
    /// Only consulted under [`RoutingStrategy::Aperture`]. Call before the
    /// dispatcher is shared.
    pub fn set_aperture(&mut self, tracker: Arc<PeerTracker>, min_aperture: usize) {
        self.aperture = Some((tracker, min_aperture.max(1)));
    }

    /// Inject the debug UI recorder. Call before the dispatcher is shared.
    pub fn set_debug_recorder(&mut self, recorder: Arc<DebugRecorder>) {
        self.debug_recorder = Some(recorder);
    }

    /// Point-in-time load and key-table snapshot for the debug UI.
    pub fn debug_load(&self) -> DispatcherLoad {
        let inner = self.inner.lock().unwrap();
        let per_worker: Vec<LoadEntry> = inner
            .in_flight
            .iter()
            .map(|(worker, in_flight)| LoadEntry {
                worker: worker.to_string(),
                in_flight: *in_flight,
            })
            .collect();
        let table = inner.scheduler.table();
        DispatcherLoad {
            total_in_flight: per_worker.iter().map(|e| e.in_flight).sum(),
            per_worker,
            queued_messages: table.queued_messages(),
            queued_bytes: table.queued_bytes(),
            outstanding_keys: table.outstanding_keys(),
            parked_keys: table.parked_keys(),
        }
    }

    /// Routing strategy and current aperture slice for the debug UI. Runs the
    /// same ring/slice computation as assignment, over a worker view the caller
    /// captured in one registry effects — so within one debug response the ring,
    /// slice, and worker rows can't disagree under churn.
    pub fn debug_routing(&self, workers: Vec<WorkerId>, healthy: &[WorkerId]) -> RoutingDebug {
        let strategy = self.strategy;
        let ring = aperture::sorted_ring(workers);
        let slice = if strategy == RoutingStrategy::Aperture {
            self.aperture.as_ref().and_then(|(tracker, width)| {
                let peers = tracker.snapshot();
                aperture::ring_slice(&ring, healthy, peers.self_index, peers.peer_count(), *width)
            })
        } else {
            None
        };
        RoutingDebug {
            strategy: strategy.as_str().to_string(),
            min_aperture: self.aperture.as_ref().map(|(_, width)| *width),
            ring: ring.iter().map(|w| w.to_string()).collect(),
            slice: slice.map(|s| s.iter().map(|w| w.to_string()).collect()),
        }
    }

    /// Capture the worker world for one seam call: routable workers, the
    /// fresh-key candidates (aperture-narrowed when configured), per-worker
    /// health, and the current load table. The scheduler decides over this
    /// snapshot instead of querying the registry itself.
    fn worker_snapshot(&self, in_flight: &WorkerLoad) -> WorkerSnapshot {
        let healthy = self.registry.healthy_workers();
        let workers = self
            .registry
            .workers()
            .into_iter()
            .map(|worker| {
                let health = WorkerHealth {
                    dead: self.registry.is_dead(&worker),
                    draining: self.registry.is_draining(&worker),
                };
                (worker, health)
            })
            .collect();
        // Aperture: narrow the candidates to this dispatcher's ring slice, so
        // the fleet's slices tile the pool and each batch consolidates onto
        // few workers. Falls back to the full healthy pool while the peer set
        // is unknown (startup, peer awareness disabled).
        let narrowed = if self.strategy == RoutingStrategy::Aperture {
            self.aperture.as_ref().and_then(|(tracker, width)| {
                let peers = tracker.snapshot();
                let ring = aperture::sorted_ring(self.registry.workers());
                aperture::ring_slice(
                    &ring,
                    &healthy,
                    peers.self_index,
                    peers.peer_count(),
                    *width,
                )
            })
        } else {
            None
        };
        let candidates = narrowed.unwrap_or_else(|| healthy.clone());
        WorkerSnapshot::new(healthy, candidates, in_flight.clone(), workers)
    }

    /// Assign a batch of messages to workers. Demuxes the messages into
    /// groups first, as the collect path does for a poll, then assigns them
    /// like [`Dispatcher::assign_and_send`]. Test-only entry point; the
    /// epoch is fixed at 0.
    pub fn assign(&self, batch_id: &str, messages: Vec<SerializedKafkaMessage>) -> Vec<SubBatch> {
        let mut inner = self.inner.lock().unwrap();
        self.assign_groups(&mut inner, batch_id, 0, demux(messages))
    }

    /// Assign a poll's groups to workers, then hand each sub-batch to `send`
    /// before releasing the lock: `send` fixes each sub-batch's position on
    /// its worker stream, so a key's runs enter the stream in dispatch order.
    /// `send` must not block.
    ///
    /// The scheduler decides per group (dispatch a runnable key, queue behind
    /// its outstanding request, or park it unroutable); see
    /// [`Scheduler::on_groups`]. Sends one `SubBatch` per worker and epoch.
    pub fn assign_and_send<T>(
        &self,
        batch_id: &str,
        assignment_epoch: u64,
        groups: Vec<Group>,
        send: impl FnMut(SubBatch) -> T,
    ) -> Submission<T> {
        // Every non-empty submission is synchronously enqueued before
        // assignment returns, even when no worker is routable.
        let retained = !groups.is_empty();
        let mut inner = self.inner.lock().unwrap();
        let pending = self
            .assign_groups(&mut inner, batch_id, assignment_epoch, groups)
            .into_iter()
            .map(send)
            .collect();
        Submission { pending, retained }
    }

    fn assign_groups(
        &self,
        inner: &mut DispatcherInner,
        batch_id: &str,
        assignment_epoch: u64,
        groups: Vec<Group>,
    ) -> Vec<SubBatch> {
        let GroupedMessages {
            groups: runs,
            unkeyed_count,
        } = routing_groups(groups);

        if unkeyed_count > 0 {
            counter!("ingestion_consumer_dispatcher_unkeyed_messages_total")
                .increment(unkeyed_count);
        }

        let routing_keys = runs.len();
        histogram!("ingestion_consumer_routing_keys_per_batch").record(routing_keys as f64);

        let snapshot = self.worker_snapshot(&inner.in_flight);
        let SchedulerEffects {
            dispatches,
            deferred,
            ..
        } = inner
            .scheduler
            .on_groups(&snapshot, batch_id, assignment_epoch, runs);
        let assignments = self.note_and_assemble(dispatches);

        // Add each worker's message volume to its outstanding load.
        for (worker, message_count) in assignments.routed_counts() {
            *inner.in_flight.entry(worker.clone()).or_insert(0) += message_count;
            counter!(
                "ingestion_consumer_dispatcher_sub_batches_assigned_total",
                "worker" => worker.clone(),
            )
            .increment(1);
            counter!(
                "ingestion_consumer_dispatcher_messages_routed_total",
                "worker" => worker.clone(),
            )
            .increment(message_count as u64);
        }

        for (reason, count) in [
            ("queued_behind_deferral", deferred.queued_behind_deferral),
            ("unroutable", deferred.unroutable),
        ] {
            if count > 0 {
                record_if(&self.debug_recorder, || DebugEventKind::Deferred {
                    batch_id: batch_id.to_string(),
                    reason,
                    groups: count,
                });
            }
        }
        record_if(&self.debug_recorder, || DebugEventKind::BatchAssigned {
            batch_id: batch_id.to_string(),
            routing_keys,
            sub_batches: assignments.sub_batch_infos(),
            deferred_groups: deferred.queued_behind_deferral,
            unroutable_groups: deferred.unroutable,
        });

        assignments.into_sub_batches()
    }

    /// Note each dispatch with the key-order sentinel — dispatch order is the
    /// intended per-key send order, still under the inner lock — and assemble
    /// the per-worker sub-batches.
    fn note_and_assemble(&self, dispatches: Vec<Dispatch>) -> WorkerAssignments {
        let mut assignments = WorkerAssignments::new();
        for dispatch in dispatches {
            self.key_sentinel
                .note_sent(&dispatch.routing_key, &dispatch.messages, dispatch.kind);
            assignments.add_dispatch(dispatch);
        }
        assignments
    }

    /// Whether the worker has any in-flight (sent, unresolved) messages. The
    /// reaper uses this to promptly complete a drain for a worker that was idle
    /// when it left the pool — its in-flight never resolves, so the registry's
    /// `complete_drain` (which fires from settlement) never would.
    pub fn has_in_flight(&self, worker: &WorkerId) -> bool {
        self.inner
            .lock()
            .unwrap()
            .in_flight
            .get(worker)
            .is_some_and(|&n| n > 0)
    }

    /// Messages the scheduler holds in its queues for later.
    pub fn held_messages(&self) -> usize {
        self.inner
            .lock()
            .unwrap()
            .scheduler
            .table()
            .queued_messages()
    }

    /// Total outstanding (sent, unresolved) messages across all workers.
    /// Exposed so tests can assert the load accounting drains back to zero.
    pub fn total_in_flight(&self) -> usize {
        self.inner.lock().unwrap().in_flight.values().sum()
    }

    /// Fire the parked-retry deadline and hand each sub-batch to `send`
    /// under the lock, like `assign_and_send`. The batcher's pump calls this
    /// on its interval; keys that still cannot route stay parked for the
    /// next call.
    pub fn parked_retry_and_send<T>(&self, send: impl FnMut(SubBatch) -> T) -> Vec<T> {
        let mut inner = self.inner.lock().unwrap();
        let snapshot = self.worker_snapshot(&inner.in_flight);
        let SchedulerEffects { dispatches, .. } = inner.scheduler.on_parked_retry(&snapshot);
        if dispatches.is_empty() {
            return Vec::new();
        }
        let assignments = self.note_and_assemble(dispatches);
        for (worker, message_count) in assignments.routed_counts() {
            *inner.in_flight.entry(worker.clone()).or_insert(0) += message_count;
            counter!(
                "ingestion_consumer_dispatcher_messages_routed_total",
                "worker" => worker.clone(),
            )
            .increment(message_count as u64);
        }
        assignments
            .into_sub_batches()
            .into_iter()
            .map(send)
            .collect()
    }

    /// Drop the scheduler's queued messages for revoked partitions, as
    /// `(topic, partition)`. Called from the consumer's rebalance callback.
    pub fn purge_revoked(&self, partitions: &[(String, i32)]) {
        let mut inner = self.inner.lock().unwrap();
        let effects = inner.scheduler.on_partitions_revoked(partitions);
        debug_assert!(effects.dispatches.is_empty(), "a purge never dispatches");
        for key in &effects.evicted_keys {
            self.key_sentinel.evict(key);
        }
    }

    /// The key table's `(queued messages, outstanding keys)`, for the pump's
    /// stall watchdog.
    pub fn key_work(&self) -> (usize, usize) {
        let inner = self.inner.lock().unwrap();
        let table = inner.scheduler.table();
        (table.queued_messages(), table.outstanding_keys())
    }

    /// Resolve one send in a single seam call: subtract its load, requeue a
    /// failure's messages, and release its keys. `failed` carries a failed
    /// send's batch id and messages; the scheduler requeues them before it
    /// releases the keys, so a newer send cannot overtake the failed
    /// messages.
    pub fn settle(
        &self,
        worker: &WorkerId,
        message_count: usize,
        routing_keys: &[String],
        failed: Option<(String, Vec<SerializedKafkaMessage>)>,
    ) {
        let unsent =
            self.settle_and_send(worker, message_count, routing_keys, failed, |sub_batch| {
                sub_batch
            });
        debug_assert!(
            unsent.is_empty(),
            "settle dropped dispatches; use settle_and_send"
        );
    }

    /// Like [`Dispatcher::settle`], and additionally hands the settlement's
    /// dispatches to `send` under the lock — a delivered settlement releases
    /// the key's next run, and sending under the lock keeps a key's runs
    /// entering its worker's stream in dispatch order. The caller must await
    /// every returned send and settle it exactly once.
    pub fn settle_and_send<T>(
        &self,
        worker: &WorkerId,
        message_count: usize,
        routing_keys: &[String],
        failed: Option<(String, Vec<SerializedKafkaMessage>)>,
        send: impl FnMut(SubBatch) -> T,
    ) -> Vec<T> {
        let mut inner = self.inner.lock().unwrap();

        let now_zero = match inner.in_flight.get_mut(worker) {
            Some(load) => {
                *load = load.saturating_sub(message_count);
                *load == 0
            }
            None => false,
        };
        if now_zero {
            inner.in_flight.remove(worker);
            // A draining worker with no in-flight left has finished its work —
            // mark it reapable so it's removed promptly rather than at the timeout.
            if self.registry.is_draining(worker) {
                self.registry.complete_drain(worker);
            }
        }

        let failed_batch_id = failed.as_ref().map(|(batch_id, _)| batch_id.clone());
        let outcome = match failed {
            None => SettlementOutcome::Delivered,
            Some((batch_id, messages)) => SettlementOutcome::Failed {
                batch_id,
                runs: runs_by_routing_key(messages),
            },
        };
        let snapshot = self.worker_snapshot(&inner.in_flight);
        let effects = inner.scheduler.on_settled(
            &snapshot,
            Settlement {
                worker: worker.clone(),
                message_count,
                routing_keys: routing_keys.to_vec(),
                outcome,
            },
        );

        let SchedulerEffects {
            dispatches,
            deferred,
            evicted_keys,
        } = effects;

        for key in &evicted_keys {
            self.key_sentinel.evict(key);
        }

        let sent: Vec<T> = if dispatches.is_empty() {
            Vec::new()
        } else {
            let assignments = self.note_and_assemble(dispatches);
            for (worker, message_count) in assignments.routed_counts() {
                *inner.in_flight.entry(worker.clone()).or_insert(0) += message_count;
                counter!(
                    "ingestion_consumer_dispatcher_sub_batches_assigned_total",
                    "worker" => worker.clone(),
                )
                .increment(1);
                counter!(
                    "ingestion_consumer_dispatcher_messages_routed_total",
                    "worker" => worker.clone(),
                )
                .increment(message_count as u64);
            }
            assignments
                .into_sub_batches()
                .into_iter()
                .map(send)
                .collect()
        };
        drop(inner);

        if deferred.send_failed > 0 {
            record_if(&self.debug_recorder, || DebugEventKind::Deferred {
                batch_id: failed_batch_id.unwrap_or_default(),
                reason: "send_failed",
                groups: deferred.send_failed,
            });
        }
        record_if(&self.debug_recorder, || DebugEventKind::SubBatchResolved {
            worker: worker.to_string(),
            messages: message_count,
            routing_keys: routing_keys.len(),
        });
        sent
    }

    /// Call when a worker ACKed a sub-batch (success path only, **before**
    /// its settle so the sentinel state isn't evicted first).
    /// Advances each key's ACK high-water mark in the order sentinel.
    pub fn on_sub_batch_acked(&self, key_offsets: &[KeyOffset]) {
        for key_offset in key_offsets {
            self.key_sentinel
                .note_acked(&key_offset.routing_key, key_offset.max_offset);
        }
    }

    /// Record the outcome of a send attempt for passive health tracking.
    /// Delegates to the underlying WorkerRegistry.
    pub fn record_send_outcome(&self, worker: &str, is_error: bool) {
        self.registry.record_outcome(worker, is_error);
    }
}

struct GroupedMessages {
    groups: Vec<KeyRun>,
    unkeyed_count: u64,
}

/// Demux messages into groups the way the collect path does for a poll.
fn demux(messages: Vec<SerializedKafkaMessage>) -> Vec<Group> {
    let mut accumulator = Accumulator::default();
    for message in messages {
        accumulator.push(Partition(message.partition), message.into());
    }
    accumulator.into_groups()
}

/// Name a failed send's messages for requeue, one run per routing key.
pub(crate) fn runs_by_routing_key(messages: Vec<SerializedKafkaMessage>) -> Vec<KeyRun> {
    routing_groups(demux(messages)).groups
}

#[cfg(test)]
fn group_messages_by_routing_key(messages: Vec<SerializedKafkaMessage>) -> GroupedMessages {
    routing_groups(demux(messages))
}

/// Name each group for the scheduler. A keyed group's routing key is its
/// Kafka key. An unkeyed message has no order to preserve, so it can go to
/// any worker: a synthetic per-message key spreads such messages across
/// workers instead of pinning them all to one shared fallback key.
///
/// The key table is keyed by routing key alone, so a key that arrives on two
/// partitions in one poll (a partition-count change leaves its backlog on the
/// old partition) merges into one group: two groups for one key could route
/// to two workers at once.
fn routing_groups(groups: Vec<Group>) -> GroupedMessages {
    let mut unkeyed_count = 0u64;
    let mut merged: Vec<KeyRun> = Vec::with_capacity(groups.len());
    let mut index_by_key: HashMap<String, usize> = HashMap::new();
    for group in groups {
        let routing_key = match group.key {
            Some(key) => key,
            None => {
                unkeyed_count += 1;
                let first = group.messages.first().map_or(Offset(-1), |m| m.offset);
                format!(":{}:{}", group.partition, first)
            }
        };
        let messages = group.messages.into_iter().map(|m| m.message);
        match index_by_key.get(&routing_key) {
            Some(&index) => merged[index].messages.extend(messages),
            None => {
                index_by_key.insert(routing_key.clone(), merged.len());
                merged.push(KeyRun {
                    routing_key,
                    messages: messages.collect(),
                });
            }
        }
    }

    GroupedMessages {
        groups: merged,
        unkeyed_count,
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use crate::order_sentinel::SendKind;
    use std::sync::Arc;
    use std::time::Duration;

    use super::*;
    use crate::worker_registry::{WorkerRegistry, WorkerRegistryConfig};

    // ---- helpers ----

    fn worker_url(i: usize) -> String {
        format!("http://worker:{}", 9001 + i)
    }

    fn wid(i: usize) -> WorkerId {
        WorkerId::from(worker_url(i).as_str())
    }

    fn make_msg(key: &str) -> SerializedKafkaMessage {
        SerializedKafkaMessage {
            topic: "test".to_string(),
            partition: 0,
            offset: 0,
            timestamp: 0,
            key: Some(key.to_string()),
            value: None,
            headers: HashMap::new(),
        }
    }

    fn make_msgs(keys: &[&str]) -> Vec<SerializedKafkaMessage> {
        keys.iter().map(|k| make_msg(k)).collect()
    }

    fn make_msg_at(key: &str, offset: i64) -> SerializedKafkaMessage {
        SerializedKafkaMessage {
            offset,
            ..make_msg(key)
        }
    }

    fn make_unkeyed_msg() -> SerializedKafkaMessage {
        SerializedKafkaMessage {
            topic: "test".to_string(),
            partition: 7,
            offset: 42,
            timestamp: 0,
            key: None,
            value: None,
            headers: HashMap::new(),
        }
    }

    /// Registry with N healthy workers and no cooldown. `dead_declaration` is
    /// very short so tests can drive a worker to dead quickly.
    fn healthy_registry(n: usize) -> Arc<WorkerRegistry> {
        let urls: Vec<String> = (0..n).map(worker_url).collect();
        let config = WorkerRegistryConfig {
            probe_interval: Duration::from_millis(50),
            dead_declaration: Duration::from_millis(30),
            passive_window: Duration::from_millis(500),
            passive_error_threshold: 0.5,
            passive_min_samples: 2,
            degraded_hold: Duration::from_millis(50),
            min_state_duration: Duration::ZERO,
            probe_failure_threshold: 2,
            drain_timeout: Duration::from_secs(5),
        };
        Arc::new(WorkerRegistry::new(&urls, config))
    }

    fn in_flight_of(dispatcher: &Dispatcher, worker: &WorkerId) -> usize {
        dispatcher
            .inner
            .lock()
            .unwrap()
            .in_flight
            .get(worker)
            .copied()
            .unwrap_or(0)
    }

    // ---- routing key ----

    #[test]
    fn test_group_messages_by_routing_key_uses_kafka_key() {
        let grouped = group_messages_by_routing_key(vec![make_msg("tok:user-1")]);

        assert_eq!(grouped.unkeyed_count, 0);
        assert_eq!(grouped.groups[0].routing_key, "tok:user-1");
    }

    #[test]
    fn test_group_messages_by_routing_key_uses_synthetic_key_for_unkeyed_messages() {
        let grouped = group_messages_by_routing_key(vec![make_unkeyed_msg()]);

        assert_eq!(grouped.unkeyed_count, 1);
        assert_eq!(grouped.groups.len(), 1);
        assert_eq!(grouped.groups[0].routing_key, ":7:42");
        assert_eq!(grouped.groups[0].messages.len(), 1);
    }

    #[test]
    fn test_group_messages_by_routing_key_groups_same_routing_key() {
        let grouped = group_messages_by_routing_key(make_msgs(&["tok:user-1", "tok:user-1"]));

        assert_eq!(grouped.unkeyed_count, 0);
        assert_eq!(grouped.groups.len(), 1);
        assert_eq!(grouped.groups[0].routing_key, "tok:user-1");
        assert_eq!(grouped.groups[0].messages.len(), 2);
    }

    #[test]
    fn test_same_routing_key_on_two_partitions_stays_one_group() {
        let grouped = group_messages_by_routing_key(vec![
            SerializedKafkaMessage {
                partition: 0,
                offset: 1,
                ..make_msg("tok:user-1")
            },
            SerializedKafkaMessage {
                partition: 3,
                offset: 9,
                ..make_msg("tok:user-1")
            },
        ]);

        assert_eq!(
            grouped.groups.len(),
            1,
            "one key must not split across workers"
        );
        assert_eq!(grouped.groups[0].messages.len(), 2);
    }

    // ---- worker assignments ----

    #[test]
    fn test_worker_assignments_merges_groups_for_same_worker() {
        let mut assignments = WorkerAssignments::new();

        assignments.add_dispatch(Dispatch {
            worker: wid(1),
            routing_key: "tok:user-1".to_string(),
            messages: make_msgs(&["tok:user-1"]),
            kind: SendKind::Fresh,
            assignment_epoch: 0,
        });
        assignments.add_dispatch(Dispatch {
            worker: wid(1),
            routing_key: "tok:user-2".to_string(),
            messages: make_msgs(&["tok:user-2"]),
            kind: SendKind::Fresh,
            assignment_epoch: 0,
        });

        assert_eq!(
            assignments.routed_counts().collect::<Vec<_>>(),
            vec![(wid(1), 2)]
        );

        let sub_batches = assignments.into_sub_batches();
        assert_eq!(sub_batches.len(), 1);
        assert_eq!(sub_batches[0].worker, wid(1));
        assert_eq!(sub_batches[0].messages.len(), 2);
        assert_eq!(
            sub_batches[0].routing_keys,
            vec!["tok:user-1".to_string(), "tok:user-2".to_string()]
        );
    }

    #[test]
    fn test_key_offsets_only_track_keyed_messages() {
        // An unkeyed (overflow) message lands on an arbitrary partition; its
        // offset advancing an ACK watermark would make a later keyed send
        // look like a resend_after_ack.
        let mut assignments = WorkerAssignments::new();
        assignments.add_dispatch(Dispatch {
            worker: wid(1),
            routing_key: "tok:user-1".to_string(),
            messages: vec![make_msg_at("tok:user-1", 100)],
            kind: SendKind::Fresh,
            assignment_epoch: 0,
        });
        let sub_batches = assignments.into_sub_batches();
        assert_eq!(sub_batches[0].key_offsets.len(), 1);
        assert_eq!(sub_batches[0].key_offsets[0].routing_key, "tok:user-1");
        assert_eq!(sub_batches[0].key_offsets[0].max_offset, 100);

        // An unkeyed group produces no ACK watermark at all.
        let mut assignments = WorkerAssignments::new();
        assignments.add_dispatch(Dispatch {
            worker: wid(1),
            routing_key: ":7:42".to_string(),
            messages: vec![make_unkeyed_msg()],
            kind: SendKind::Fresh,
            assignment_epoch: 0,
        });
        assert!(assignments.into_sub_batches()[0].key_offsets.is_empty());
    }

    // ---- basic assignment ----

    #[test]
    fn test_single_worker_all_messages_go_there() {
        let registry = healthy_registry(1);
        let dispatcher = Dispatcher::new(registry);

        let sub_batches = dispatcher.assign("b", make_msgs(&["t:a", "t:b", "t:c"]));

        assert_eq!(sub_batches.len(), 1);
        assert_eq!(sub_batches[0].worker, wid(0));
        assert_eq!(sub_batches[0].messages.len(), 3);
    }

    #[test]
    fn test_empty_batch_returns_no_sub_batches() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);
        assert!(dispatcher.assign("b", vec![]).is_empty());
    }

    #[test]
    fn test_same_key_merges_within_batch() {
        let registry = healthy_registry(3);
        let dispatcher = Dispatcher::new(registry);

        let batch1 = dispatcher.assign("b", make_msgs(&["t:user-1"]));
        assert_eq!(batch1.len(), 1);
        let worker = batch1[0].worker.clone();
        dispatcher.settle(
            &worker,
            batch1[0].messages.len(),
            &batch1[0].routing_keys,
            None,
        );

        // Both user-1 messages merge into one sub-batch.
        let batch2 = dispatcher.assign("b", make_msgs(&["t:user-1", "t:user-1"]));
        assert_eq!(batch2.len(), 1);
    }

    // ---- placement ----

    #[test]
    fn test_different_keys_may_go_to_different_workers() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        // With 2 workers, bin-packing should spread 2 fresh keys across them.
        let sub_batches = dispatcher.assign("b", make_msgs(&["t:user-1", "t:user-2"]));

        let total_msgs: usize = sub_batches.iter().map(|b| b.messages.len()).sum();
        assert_eq!(total_msgs, 2);
    }

    // ---- in-flight load ----

    #[test]
    fn test_in_flight_messages_incremented_by_message_count_on_assign() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        // Two messages for one key → one sub-batch carrying two messages.
        let b1 = dispatcher.assign("b", make_msgs(&["t:user-1", "t:user-1"]));
        let worker = b1[0].worker.clone();

        assert_eq!(in_flight_of(&dispatcher, &worker), 2);
    }

    #[test]
    fn test_in_flight_messages_decremented_on_resolve() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        let b1 = dispatcher.assign("b", make_msgs(&["t:user-1", "t:user-1"]));
        let worker = b1[0].worker.clone();

        dispatcher.settle(&worker, b1[0].messages.len(), &b1[0].routing_keys, None);

        assert_eq!(in_flight_of(&dispatcher, &worker), 0);
    }

    #[test]
    fn test_in_flight_messages_counts_every_message_to_worker() {
        // Three distinct keys routed to the single worker merge into one
        // sub-batch, but in-flight load tracks the total message volume (3),
        // not the sub-batch count.
        let registry = healthy_registry(1);
        let dispatcher = Dispatcher::new(registry);

        dispatcher.assign("b", make_msgs(&["t:a", "t:b", "t:c"]));

        assert_eq!(in_flight_of(&dispatcher, &wid(0)), 3);
    }

    // ---- bin-packing ----

    #[test]
    fn test_bin_packing_targets_least_loaded_worker() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        // Artificially load worker 0 with 3 outstanding messages.
        dispatcher.inner.lock().unwrap().in_flight.insert(wid(0), 3);

        // A fresh key should go to worker 1 (load = 0).
        let b = dispatcher.assign("b", make_msgs(&["t:fresh"]));
        assert_eq!(b.len(), 1);
        assert_eq!(b[0].worker, wid(1));
    }

    #[test]
    fn test_bin_packing_balances_by_message_volume_not_group_count() {
        // Regression: load is tracked by message count, not sub-batch presence.
        // One heavy key (10 msgs) plus five small keys (1 msg each) must not all
        // pile onto one worker — the small keys bin-pack onto the other worker
        // until load is balanced.
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(registry);

        let mut specs: Vec<&str> = vec!["t:heavy"; 10];
        for d in ["t:a", "t:b", "t:c", "t:d", "t:e"] {
            specs.push(d);
        }

        let sub_batches = dispatcher.assign("b", make_msgs(&specs));
        assert_eq!(sub_batches.len(), 2, "both workers must carry messages");

        let load0 = in_flight_of(&dispatcher, &wid(0));
        let load1 = in_flight_of(&dispatcher, &wid(1));
        assert_eq!(load0 + load1, 15);

        // The heavy key lands alone on one worker; the five singles fill the
        // other. With per-sub-batch accounting the singles would all dump onto
        // one worker, giving 15 vs 1.
        let (heavy, light) = if load0 >= load1 {
            (load0, load1)
        } else {
            (load1, load0)
        };
        assert_eq!(heavy, 10);
        assert_eq!(light, 5);
    }

    // ---- dead worker handling ----

    #[test]
    fn test_all_workers_dead_returns_empty() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        // Force both workers to Unhealthy via passive signal (min_state_duration=0).
        for i in 0..2 {
            for _ in 0..5 {
                registry.record_outcome(&worker_url(i), true);
            }
        }

        // Both workers are Unhealthy — the dispatcher should not route to them.
        let b = dispatcher.assign("b", make_msgs(&["t:user-1"]));
        assert!(b.is_empty());
    }

    // ---- P2C routing strategy ----

    fn p2c_dispatcher(n: usize, seed: u64) -> Dispatcher {
        Dispatcher::with_strategy_seeded(healthy_registry(n), RoutingStrategy::P2c, seed)
    }

    #[test]
    fn test_p2c_single_worker_all_messages_go_there() {
        let dispatcher = p2c_dispatcher(1, 1);

        let sub_batches = dispatcher.assign("b", make_msgs(&["t:a", "t:b", "t:c"]));

        assert_eq!(sub_batches.len(), 1);
        assert_eq!(sub_batches[0].worker, wid(0));
        assert_eq!(sub_batches[0].messages.len(), 3);
    }

    #[test]
    fn test_p2c_spreads_fresh_keys_across_two_workers() {
        // With two workers, P2C samples both and the load bump after the first
        // key steers the second to the other worker — one message each.
        let dispatcher = p2c_dispatcher(2, 3);

        let sub_batches = dispatcher.assign("b", make_msgs(&["t:user-1", "t:user-2"]));

        assert_eq!(sub_batches.len(), 2, "both workers must carry a message");
        let total: usize = sub_batches.iter().map(|b| b.messages.len()).sum();
        assert_eq!(total, 2);
    }

    #[test]
    fn test_p2c_prefers_least_loaded_of_two_workers() {
        // With two workers P2C always compares both, so a pre-loaded worker 0
        // sends the fresh key to worker 1.
        let dispatcher = p2c_dispatcher(2, 9);
        dispatcher.inner.lock().unwrap().in_flight.insert(wid(0), 5);

        let b = dispatcher.assign("b", make_msgs(&["t:fresh"]));
        assert_eq!(b.len(), 1);
        assert_eq!(b[0].worker, wid(1));
    }

    #[tokio::test]
    async fn test_p2c_all_workers_dead_returns_empty() {
        let registry = healthy_registry(2);
        let dispatcher =
            Dispatcher::with_strategy_seeded(Arc::clone(&registry), RoutingStrategy::P2c, 1);

        for i in 0..2 {
            for _ in 0..5 {
                registry.record_outcome(&worker_url(i), true);
            }
        }

        let b = dispatcher.assign("b", make_msgs(&["t:user-1"]));
        assert!(b.is_empty());
    }

    // ---- deterministic aperture ----

    fn peer_tracker(self_ip: &str, peer_ips: &[&str]) -> Arc<PeerTracker> {
        let tracker = PeerTracker::new(self_ip.parse().unwrap());
        tracker.set_peers(&peer_ips.iter().map(|ip| ip.parse().unwrap()).collect());
        tracker
    }

    #[test]
    fn test_aperture_routes_fresh_keys_within_ring_slice() {
        // Peer 1 of 2 over a 6-worker ring, configured width 2 floored to
        // ceil(6/2)=3 for coverage, owns ring positions 3-5; every fresh key
        // must land there, nowhere else.
        let mut dispatcher =
            Dispatcher::with_strategy(healthy_registry(6), RoutingStrategy::Aperture);
        dispatcher.set_aperture(peer_tracker("10.0.0.2", &["10.0.0.1", "10.0.0.2"]), 2);

        let msgs: Vec<_> = (0..10).map(|i| make_msg(&format!("t:u{i}"))).collect();
        let sub_batches = dispatcher.assign("b", msgs);

        let total: usize = sub_batches.iter().map(|b| b.messages.len()).sum();
        assert_eq!(total, 10);
        assert!(
            sub_batches
                .iter()
                .all(|b| b.worker == wid(3) || b.worker == wid(4) || b.worker == wid(5)),
            "all sub-batches must stay within the dispatcher's ring slice"
        );
    }

    #[test]
    fn test_aperture_slices_tile_across_peers_without_overlap() {
        // Two dispatchers with complementary indices must route into disjoint
        // slices — the property that keeps the fleet covering the whole pool.
        let keys: Vec<_> = (0..10).map(|i| format!("u{i}")).collect();
        let mut used: Vec<Vec<WorkerId>> = Vec::new();
        for self_ip in ["10.0.0.1", "10.0.0.2"] {
            let mut dispatcher =
                Dispatcher::with_strategy(healthy_registry(6), RoutingStrategy::Aperture);
            dispatcher.set_aperture(peer_tracker(self_ip, &["10.0.0.1", "10.0.0.2"]), 2);
            let msgs: Vec<_> = keys.iter().map(|k| make_msg(k)).collect();
            used.push(
                dispatcher
                    .assign("b", msgs)
                    .iter()
                    .map(|b| b.worker.clone())
                    .collect(),
            );
        }
        assert!(
            used[0].iter().all(|w| !used[1].contains(w)),
            "peer slices must not overlap: {used:?}"
        );
    }

    #[test]
    fn test_aperture_falls_back_to_full_pool_while_self_unknown() {
        // Before this pod is a ready endpoint (self_index None), aperture must
        // not stall or funnel everything through a guessed slice — it routes
        // over the full pool like plain P2C.
        let mut dispatcher =
            Dispatcher::with_strategy_seeded(healthy_registry(4), RoutingStrategy::Aperture, 7);
        dispatcher.set_aperture(peer_tracker("10.0.0.9", &["10.0.0.1", "10.0.0.2"]), 1);

        let msgs: Vec<_> = (0..30).map(|i| make_msg(&format!("t:u{i}"))).collect();
        let sub_batches = dispatcher.assign("b", msgs);

        let total: usize = sub_batches.iter().map(|b| b.messages.len()).sum();
        assert_eq!(total, 30, "no messages may be dropped or stalled");
        assert!(
            sub_batches.len() > 1,
            "fallback must spread beyond a single-worker slice"
        );
    }

    #[test]
    fn test_debug_routing_reports_the_live_aperture_slice() {
        // The debug payload must mirror what `assign` would use: same ring,
        // same slice (peer 1 of 2 over 6 workers → floored width 3, positions
        // 3-5). A drift here would make the control-plane UI lie during an
        // incident.
        let registry = healthy_registry(6);
        let mut dispatcher =
            Dispatcher::with_strategy(Arc::clone(&registry), RoutingStrategy::Aperture);
        dispatcher.set_aperture(peer_tracker("10.0.0.2", &["10.0.0.1", "10.0.0.2"]), 2);

        let routing = dispatcher.debug_routing(registry.workers(), &registry.healthy_workers());

        assert_eq!(routing.strategy, "aperture");
        assert_eq!(routing.min_aperture, Some(2));
        assert_eq!(routing.ring.len(), 6);
        assert_eq!(
            routing.slice,
            Some(vec![
                wid(3).to_string(),
                wid(4).to_string(),
                wid(5).to_string()
            ])
        );

        // Non-aperture strategies report no slice — the UI shows full pool.
        let registry = healthy_registry(2);
        let p2c = Dispatcher::with_strategy(Arc::clone(&registry), RoutingStrategy::P2c);
        let routing = p2c.debug_routing(registry.workers(), &registry.healthy_workers());
        assert_eq!(routing.strategy, "p2c");
        assert!(routing.slice.is_none());
    }

    // ---- graceful drain ----

    #[test]
    fn test_draining_worker_gets_no_new_keys() {
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));
        registry.start_draining(&worker_url(0));

        let msgs: Vec<_> = (0..10).map(|i| make_msg(&format!("t:u{i}"))).collect();
        let sub_batches = dispatcher.assign("b", msgs);

        assert!(
            sub_batches.iter().all(|b| b.worker != wid(0)),
            "no new keys may route to a draining worker"
        );
    }

    #[test]
    fn test_parked_key_retries_when_a_worker_returns() {
        let registry = healthy_registry(0);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        let sub_batches = dispatcher.assign("b1", make_msgs(&["t:user-1"]));
        assert!(sub_batches.is_empty(), "nothing routable yet");
        assert_eq!(
            dispatcher.key_work(),
            (1, 0),
            "the key table keeps the parked message"
        );

        // Still nothing healthy: the key stays parked for the next tick.
        assert!(dispatcher.parked_retry_and_send(|sub| sub).is_empty());

        registry.add_worker(wid(0));
        let retried = dispatcher.parked_retry_and_send(|sub| sub);
        assert_eq!(retried.len(), 1);
        assert_eq!(retried[0].worker, wid(0));
        assert_eq!(retried[0].messages.len(), 1);
        assert_eq!(dispatcher.key_work(), (0, 1), "outstanding until settled");
    }

    #[test]
    fn test_settle_failure_requeues_before_releasing_the_key() {
        // The one-call settlement must requeue the failed messages before it
        // releases the key: reordered, the key's next arrival could route
        // ahead of the replay.
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        let b1 = dispatcher.assign("batch-1", make_msgs(&["t:user-1"]));
        let worker = b1[0].worker.clone();

        dispatcher.settle(
            &worker,
            b1[0].messages.len(),
            &b1[0].routing_keys,
            Some(("batch-1".to_string(), b1[0].messages.clone())),
        );

        assert_eq!(
            dispatcher.key_work(),
            (1, 0),
            "failed messages requeued, key released"
        );
        assert_eq!(dispatcher.total_in_flight(), 0, "load released");
        assert!(
            dispatcher
                .assign("batch-2", make_msgs(&["t:user-1"]))
                .is_empty(),
            "newer work queues behind the replay"
        );
    }

    #[test]
    fn test_resolve_completes_drain_when_in_flight_hits_zero() {
        let registry = healthy_registry(1);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        // Send a batch to worker 0, then mark it draining while in-flight.
        let b = dispatcher.assign("b", make_msgs(&["t:a"]));
        let worker = b[0].worker.clone();
        registry.start_draining(&worker);
        assert!(
            registry.reapable_workers().is_empty(),
            "not reapable while in-flight remains"
        );

        // Resolving the last in-flight sub-batch should mark it reapable.
        dispatcher.settle(&worker, b[0].messages.len(), &b[0].routing_keys, None);
        assert_eq!(registry.reapable_workers(), vec![worker]);
    }

    #[test]
    fn test_idle_drained_worker_reaped_via_reaper_path() {
        // A worker drained while idle has no in-flight to resolve, so
        // `settle`/`complete_drain` never fire for it. The reaper
        // instead completes the drain when `has_in_flight` is false. This checks
        // the accessors that path relies on.
        let registry = healthy_registry(2);
        let dispatcher = Dispatcher::new(Arc::clone(&registry));

        let idle = wid(0);
        registry.start_draining(&idle);

        // Reaper's condition holds: the worker is draining and has no in-flight.
        assert!(registry.draining_workers().contains(&idle));
        assert!(
            !dispatcher.has_in_flight(&idle),
            "idle worker has no in-flight"
        );
        assert!(
            registry.reapable_workers().is_empty(),
            "not reapable yet — its deadline is the full drain timeout"
        );

        // The reaper completes the drain → immediately reapable, no timeout wait.
        registry.complete_drain(&idle);
        assert_eq!(registry.reapable_workers(), vec![idle]);
    }
}
