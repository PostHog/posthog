//! The key-table scheduler: at most one request per key is in flight.
//!
//! The key table holds one FIFO queue per routing key, an outstanding flag,
//! and a parked list. A key's messages are in exactly one place: the
//! packer's open batch, a request in flight, or the key's queue. A key with
//! nothing in flight forwards its arrivals to the [`Packer`], which holds
//! them per key until a batch reaches the target size or its latency
//! budget expires; at a zero budget every key's messages leave at the end
//! of the seam call that brought them. Releasing a batch marks its keys
//! outstanding, and the batch is placed as it leaves: the configured
//! router picks a worker against that moment's snapshot and load. A batch
//! with no routable worker waits, unplaced, for the pack deadline.
//!
//! An outstanding or parked key queues its arrivals. A delivered settlement
//! clears the flag and forwards the queue to the packer. A failed
//! settlement returns the run to the front of its queue, then clears the
//! flag — requeue before release, in one seam call — and parks the key. The
//! parked-retry deadline ([`Deadline::ParkedRetry`]) resends parked keys
//! directly, past the packer, with the replay flag.
//!
//! At most one outstanding request per key preserves per-key order. Nothing
//! else does, and nothing else must: placement carries no pins and no stash.

use std::collections::{HashMap, HashSet, VecDeque};
use std::time::Instant;

use metrics::{counter, gauge, histogram};

use crate::order_sentinel::SendKind;
use crate::packer::{Batch, PackTargets, Packer};
use crate::routing::{Router, WorkerLoad};
use crate::scheduler::{
    bump_load, working_load, Deadline, Dispatch, KeyRun, Scheduler, SchedulerEffects, Settlement,
    SettlementOutcome, WorkerSnapshot,
};
use crate::types::SerializedKafkaMessage;
use crate::worker_registry::WorkerId;

/// Record a parked retry's head-of-line wait: how long its oldest message
/// sat queued behind the park. The packer records the fresh kind at
/// release, from the message's arrival, so that wait includes the pack
/// hold.
fn record_queue_wait(drained: &Drained, kind: SendKind) {
    let kind = match kind {
        SendKind::Fresh => "fresh",
        SendKind::Resend => "resend",
    };
    histogram!("ingestion_consumer_key_table_queue_wait_seconds", "kind" => kind)
        .record(drained.first_arrival.elapsed().as_secs_f64());
}

fn payload_bytes(messages: &[SerializedKafkaMessage]) -> usize {
    messages
        .iter()
        .map(SerializedKafkaMessage::payload_bytes)
        .sum()
}

/// One queued message: the epoch it was polled under and its arrival time,
/// for the queue-wait histogram. A requeued failure restarts the clock, so
/// a resend's wait measures the pause before the redelivery.
struct QueuedMessage {
    epoch: u64,
    enqueued_at: Instant,
    message: SerializedKafkaMessage,
}

/// The longest same-epoch prefix drained from a key's queue.
struct Drained {
    epoch: u64,
    /// When the oldest message was queued: the start of its wait.
    first_arrival: Instant,
    messages: Vec<SerializedKafkaMessage>,
    bytes: usize,
}

/// One key's scheduling state.
struct KeyState {
    /// Queued messages in arrival order. A failed run returns to the front.
    queue: VecDeque<QueuedMessage>,
    /// A request for this key is in flight. No second dispatch may happen
    /// until it settles.
    outstanding: bool,
    /// The epoch of the outstanding run, so its failed messages requeue
    /// under the epoch they were polled in.
    outstanding_epoch: u64,
    /// Remember revocations until this send settles: its messages live in
    /// the transport, not the queue. New assignments must remain retryable.
    revoked_while_outstanding: Vec<(String, i32)>,
    /// The key waits for the parked-retry deadline. A parked key is never
    /// outstanding: it parks only when nothing of its is in flight.
    parked: bool,
    /// The queue's front messages were sent once and failed. Their next
    /// dispatch is a [`SendKind::Resend`]; a key parked only as unroutable
    /// has never been sent, so its retry stays a strictly checked first send.
    redelivering: bool,
}

impl KeyState {
    fn new() -> Self {
        Self {
            queue: VecDeque::new(),
            outstanding: false,
            outstanding_epoch: 0,
            revoked_while_outstanding: Vec::new(),
            parked: false,
            redelivering: false,
        }
    }
}

/// Per-key FIFO queues, outstanding flags, and the parked list.
#[derive(Default)]
pub struct KeyTable {
    keys: HashMap<String, KeyState>,
    /// Keys awaiting the parked-retry deadline, in park order, so retries
    /// preserve arrival fairness across keys.
    parked: Vec<String>,
    /// Total queued messages and payload bytes across all keys, kept
    /// incrementally for the gauges. Bytes matter for visibility: every key
    /// with an outstanding request buffers all later arrivals, and key
    /// cardinality is customer-controlled.
    queued_messages: usize,
    queued_bytes: usize,
    outstanding_keys: usize,
}

impl KeyTable {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn key_count(&self) -> usize {
        self.keys.len()
    }

    pub fn queued_messages(&self) -> usize {
        self.queued_messages
    }

    pub fn queued_bytes(&self) -> usize {
        self.queued_bytes
    }

    pub fn outstanding_keys(&self) -> usize {
        self.outstanding_keys
    }

    pub fn parked_keys(&self) -> usize {
        self.parked.len()
    }

    /// Whether the key's arrivals may go straight to the packer: nothing
    /// in flight, not parked, and nothing queued ahead of them. An untracked
    /// key is free.
    fn is_free(&self, key: &str) -> bool {
        self.keys
            .get(key)
            .is_none_or(|state| !state.outstanding && !state.parked && state.queue.is_empty())
    }

    /// Append messages to the key's queue, creating the key when new.
    fn enqueue_back(&mut self, key: &str, epoch: u64, messages: Vec<SerializedKafkaMessage>) {
        self.queued_messages += messages.len();
        self.queued_bytes += payload_bytes(&messages);
        let enqueued_at = Instant::now();
        self.keys
            .entry(key.to_string())
            .or_insert_with(KeyState::new)
            .queue
            .extend(messages.into_iter().map(|message| QueuedMessage {
                epoch,
                enqueued_at,
                message,
            }));
    }

    /// Return a failed run to the front of its queue, ahead of anything that
    /// arrived while the run was in flight, so the redelivery keeps offset order.
    /// The messages keep the outstanding run's epoch, except those revoked
    /// while the send was in flight, which the new owner will replay.
    fn requeue_front(&mut self, key: &str, mut messages: Vec<SerializedKafkaMessage>) {
        let state = self
            .keys
            .entry(key.to_string())
            .or_insert_with(KeyState::new);
        if !state.revoked_while_outstanding.is_empty() {
            messages.retain(|message| {
                !state
                    .revoked_while_outstanding
                    .iter()
                    .any(|(topic, partition)| {
                        *topic == message.topic && *partition == message.partition
                    })
            });
        }
        if messages.is_empty() {
            return;
        }
        self.queued_messages += messages.len();
        self.queued_bytes += payload_bytes(&messages);
        state.redelivering = true;
        let epoch = state.outstanding_epoch;
        let enqueued_at = Instant::now();
        for message in messages.into_iter().rev() {
            state.queue.push_front(QueuedMessage {
                epoch,
                enqueued_at,
                message,
            });
        }
    }

    /// Drain the queue's longest same-epoch prefix. A batch never mixes
    /// epochs, so its completions carry one valid stamp; later-epoch
    /// messages wait for the key's next settlement. Returns None, with no
    /// state change, when the key is outstanding or has nothing queued.
    fn drain_key(&mut self, key: &str) -> Option<Drained> {
        let state = self.keys.get_mut(key)?;
        debug_assert!(!state.outstanding, "at most one request per key");
        if state.outstanding || state.queue.is_empty() {
            return None;
        }
        let front = state.queue.front().expect("checked non-empty");
        let epoch = front.epoch;
        let first_arrival = front.enqueued_at;
        let mut messages: Vec<SerializedKafkaMessage> = Vec::new();
        while state
            .queue
            .front()
            .is_some_and(|queued| queued.epoch == epoch)
        {
            messages.push(state.queue.pop_front().expect("front checked").message);
        }
        let bytes = payload_bytes(&messages);
        // Saturate so an accounting bug publishes zero to the gauges instead
        // of a wrapped huge value.
        debug_assert!(self.queued_messages >= messages.len());
        self.queued_messages = self.queued_messages.saturating_sub(messages.len());
        self.queued_bytes = self.queued_bytes.saturating_sub(bytes);
        Some(Drained {
            epoch,
            first_arrival,
            messages,
            bytes,
        })
    }

    /// Mark the key outstanding under `epoch`: its request is leaving. The
    /// key is created when the packer held its messages before the table
    /// ever saw it.
    fn mark_outstanding(&mut self, key: &str, epoch: u64) {
        let state = self
            .keys
            .entry(key.to_string())
            .or_insert_with(KeyState::new);
        debug_assert!(!state.outstanding, "at most one request per key");
        state.outstanding = true;
        state.outstanding_epoch = epoch;
        state.parked = false;
        state.redelivering = false;
        self.outstanding_keys += 1;
    }

    /// Put the key on the parked list, to be retried at the parked-retry
    /// deadline. A no-op when it is already parked or not tracked.
    fn park(&mut self, key: &str) {
        let Some(state) = self.keys.get_mut(key) else {
            return;
        };
        if !state.parked {
            state.parked = true;
            self.parked.push(key.to_string());
        }
    }

    /// Take the parked list for one retry pass. Keys that still cannot route
    /// go back via [`KeyTable::repark`]; their `parked` flag stays set so
    /// arrivals keep queueing behind them in the meantime.
    fn take_parked(&mut self) -> Vec<String> {
        std::mem::take(&mut self.parked)
    }

    /// Restore a key's parked-list entry after a retry pass could not route
    /// it. Its `parked` flag never dropped, so only the entry returns.
    fn repark(&mut self, key: String) {
        self.parked.push(key);
    }

    /// Messages queued for the key.
    fn queued_len(&self, key: &str) -> usize {
        self.keys.get(key).map_or(0, |state| state.queue.len())
    }

    /// Whether the key's next dispatch redelivers messages from a failed send.
    fn is_redelivering(&self, key: &str) -> bool {
        self.keys.get(key).is_some_and(|state| state.redelivering)
    }

    #[cfg(test)]
    fn is_outstanding(&self, key: &str) -> bool {
        self.keys.get(key).is_some_and(|state| state.outstanding)
    }

    #[cfg(test)]
    fn is_parked(&self, key: &str) -> bool {
        self.keys.get(key).is_some_and(|state| state.parked)
    }

    /// Clear the key's outstanding flag when its request settles. Returns
    /// false for a key this table is not tracking as outstanding — a stale
    /// settlement to ignore.
    fn settle_key(&mut self, key: &str) -> bool {
        match self.keys.get_mut(key) {
            Some(state) if state.outstanding => {
                state.outstanding = false;
                state.revoked_while_outstanding.clear();
                self.outstanding_keys = self.outstanding_keys.saturating_sub(1);
                true
            }
            _ => false,
        }
    }

    /// Drop queued messages on revoked partitions and the keys that emptied,
    /// unless still outstanding. Returns the purged message count and the
    /// evicted keys.
    fn purge_partitions(&mut self, revoked: &[(String, i32)]) -> (usize, Vec<String>) {
        let revoked: HashSet<(&str, i32)> = revoked
            .iter()
            .map(|(topic, partition)| (topic.as_str(), *partition))
            .collect();
        let mut purged = 0usize;
        let mut purged_bytes = 0usize;
        for state in self.keys.values_mut() {
            if state.outstanding {
                for &(topic, partition) in &revoked {
                    if !state.revoked_while_outstanding.iter().any(
                        |(revoked_topic, revoked_partition)| {
                            revoked_topic == topic && *revoked_partition == partition
                        },
                    ) {
                        state
                            .revoked_while_outstanding
                            .push((topic.to_string(), partition));
                    }
                }
            }
            let before = state.queue.len();
            state.queue.retain(|queued| {
                let keep =
                    !revoked.contains(&(queued.message.topic.as_str(), queued.message.partition));
                if !keep {
                    purged_bytes += queued.message.payload_bytes();
                }
                keep
            });
            purged += before - state.queue.len();
            if state.queue.is_empty() {
                state.parked = false;
                state.redelivering = false;
            }
        }
        self.queued_messages = self.queued_messages.saturating_sub(purged);
        self.queued_bytes = self.queued_bytes.saturating_sub(purged_bytes);

        let keys = &mut self.keys;
        self.parked
            .retain(|key| keys.get(key).is_some_and(|state| state.parked));
        let evicted: Vec<String> = keys
            .iter()
            .filter(|(_, state)| state.queue.is_empty() && !state.outstanding && !state.parked)
            .map(|(key, _)| key.clone())
            .collect();
        for key in &evicted {
            keys.remove(key);
        }
        (purged, evicted)
    }

    /// Drop the key when nothing is queued, outstanding, or parked, so its
    /// order-sentinel state can go too. Returns true when it was removed.
    fn evict_if_idle(&mut self, key: &str) -> bool {
        let idle = self
            .keys
            .get(key)
            .is_some_and(|state| state.queue.is_empty() && !state.outstanding && !state.parked);
        if idle {
            self.keys.remove(key);
        }
        idle
    }
}

/// A released batch that found no routable worker when it left the packer.
/// Its keys are outstanding; the pack deadline retries the placement.
struct UnplacedBatch {
    epoch: u64,
    runs: Vec<KeyRun>,
}

/// The target scheduler: the key table, the packer, and placement at
/// release via the configured routing strategy (P2C within the aperture
/// slice, or bin-pack).
pub struct KeyTableScheduler {
    table: KeyTable,
    router: Router,
    packer: Packer,
    unplaced: VecDeque<UnplacedBatch>,
    unplaced_messages: usize,
    unplaced_keys: usize,
    #[cfg(test)]
    now_override: Option<Instant>,
}

impl KeyTableScheduler {
    /// Starts with zero pack targets: send on arrival.
    pub fn new(router: Router) -> Self {
        Self {
            table: KeyTable::new(),
            router,
            packer: Packer::new(PackTargets::default()),
            unplaced: VecDeque::new(),
            unplaced_messages: 0,
            unplaced_keys: 0,
            #[cfg(test)]
            now_override: None,
        }
    }

    pub fn table(&self) -> &KeyTable {
        &self.table
    }

    pub fn pack_targets(&self) -> PackTargets {
        self.packer.targets()
    }

    pub fn set_pack_targets(&mut self, targets: PackTargets) {
        self.packer.set_targets(targets);
    }

    /// Messages not queued and not on the wire: in the packer's open batch,
    /// or in a batch that found no worker.
    pub fn held_messages(&self) -> usize {
        self.packer.held_messages() + self.unplaced_messages
    }

    /// Keys of unplaced batches. They are outstanding in the table but
    /// nothing of theirs is on the wire; a key in the open batch is not
    /// outstanding at all.
    pub fn unplaced_keys(&self) -> usize {
        self.unplaced_keys
    }

    pub fn unplaced_batches(&self) -> usize {
        self.unplaced.len()
    }

    #[cfg(test)]
    pub(crate) fn set_now(&mut self, now: Instant) {
        self.now_override = Some(now);
    }

    fn now(&self) -> Instant {
        #[cfg(test)]
        if let Some(now) = self.now_override {
            return now;
        }
        Instant::now()
    }

    /// Hand a free key's messages to the packer, and place the batch that
    /// fills. The open batch spans one epoch: messages from a newer epoch
    /// release it first. A cooperative assign bumps the epoch with no
    /// revoke to flush the packer, and a batch stamped with the wrong
    /// epoch would leave its poll's completions discarded as stale.
    #[allow(clippy::too_many_arguments)]
    fn forward(
        &mut self,
        candidates: &[WorkerId],
        working_load: &mut WorkerLoad,
        key: &str,
        epoch: u64,
        messages: Vec<SerializedKafkaMessage>,
        bytes: usize,
        arrived_at: Instant,
        effects: &mut SchedulerEffects,
    ) {
        let now = self.now();
        if self.packer.epoch().is_some_and(|held| held != epoch) {
            if let Some(batch) = self.packer.flush(now) {
                self.place(batch, candidates, working_load, effects);
            }
        }
        if let Some(batch) = self
            .packer
            .push(key, epoch, messages, bytes, arrived_at, now)
        {
            self.place(batch, candidates, working_load, effects);
        }
    }

    /// At a zero budget, every key's messages leave at the end of the seam
    /// call that brought them, each key as its own batch, placed like the
    /// runs the scheduler dispatched before the packer: largest first under
    /// bin-packing, so heavy hitters drive the load distribution.
    fn release_arrivals(
        &mut self,
        candidates: &[WorkerId],
        working_load: &mut WorkerLoad,
        effects: &mut SchedulerEffects,
    ) {
        let mut batches = self.packer.release_entries(self.now());
        if self.router.prefers_largest_first() {
            batches.sort_by_key(|batch| std::cmp::Reverse(batch.message_count()));
        }
        for batch in batches {
            self.place(batch, candidates, working_load, effects);
        }
    }

    /// Place a released batch: its keys go outstanding, the router picks a
    /// worker against the current load, and the batch becomes one dispatch.
    /// With no routable worker the batch waits for the pack deadline.
    fn place(
        &mut self,
        batch: Batch,
        candidates: &[WorkerId],
        working_load: &mut WorkerLoad,
        effects: &mut SchedulerEffects,
    ) {
        for run in &batch.runs {
            self.table.mark_outstanding(&run.routing_key, batch.epoch);
        }
        match self.router.select(candidates, working_load) {
            Some(worker) => {
                bump_load(working_load, &worker, batch.message_count());
                effects.dispatches.push(Dispatch {
                    worker,
                    runs: batch.runs,
                    kind: SendKind::Fresh,
                    assignment_epoch: Some(batch.epoch),
                });
            }
            None => {
                // Counted once, here: a retry that fails again does not
                // re-count, so the counter tracks newly stranded messages.
                // The unplaced gauges carry the backlog.
                counter!("ingestion_consumer_dispatcher_unroutable_messages_total")
                    .increment(batch.message_count() as u64);
                effects.deferred.unroutable += batch.runs.len() as u64;
                self.unplaced_messages += batch.message_count();
                self.unplaced_keys += batch.runs.len();
                self.unplaced.push_back(UnplacedBatch {
                    epoch: batch.epoch,
                    runs: batch.runs,
                });
            }
        }
    }

    /// Retry every unplaced batch over `pool`, oldest first. A batch that
    /// still cannot route waits for the next deadline.
    fn place_unplaced(
        &mut self,
        pool: &[WorkerId],
        working_load: &mut WorkerLoad,
        effects: &mut SchedulerEffects,
    ) {
        while let Some(batch) = self.unplaced.pop_front() {
            let Some(worker) = self.router.select(pool, working_load) else {
                self.unplaced.push_front(batch);
                break;
            };
            let message_count: usize = batch.runs.iter().map(|run| run.messages.len()).sum();
            self.unplaced_messages = self.unplaced_messages.saturating_sub(message_count);
            self.unplaced_keys = self.unplaced_keys.saturating_sub(batch.runs.len());
            bump_load(working_load, &worker, message_count);
            effects.dispatches.push(Dispatch {
                worker,
                runs: batch.runs,
                kind: SendKind::Fresh,
                assignment_epoch: Some(batch.epoch),
            });
        }
    }

    /// Resend every parked key that can route now, directly and past the
    /// packer; the rest stay parked for the next deadline.
    fn retry_parked(&mut self, snapshot: &WorkerSnapshot) -> SchedulerEffects {
        let parked = self.table.take_parked();
        let mut effects = SchedulerEffects::with_dispatch_capacity(parked.len());
        let mut load = working_load(snapshot);

        for key in parked {
            // A retry escapes the aperture slice and routes over the whole
            // healthy pool, like a deferred flush: the slice may be exactly
            // what the key could not route into.
            let Some(worker) = self.router.select(&snapshot.healthy, &load) else {
                self.table.repark(key);
                continue;
            };
            // A key parked only as unroutable has never been sent: its retry
            // is a first send, checked strictly by the order sentinel.
            let kind = if self.table.is_redelivering(&key) {
                SendKind::Resend
            } else {
                SendKind::Fresh
            };
            let Some(drained) = self.table.drain_key(&key) else {
                continue;
            };
            record_queue_wait(&drained, kind);
            self.table.mark_outstanding(&key, drained.epoch);
            bump_load(&mut load, &worker, drained.messages.len());
            counter!("ingestion_consumer_parked_retries_total").increment(1);
            effects.dispatches.push(Dispatch {
                worker,
                runs: vec![KeyRun {
                    routing_key: key,
                    messages: drained.messages,
                }],
                kind,
                assignment_epoch: Some(drained.epoch),
            });
        }

        self.record_gauges();
        effects
    }

    fn record_gauges(&self) {
        gauge!("ingestion_consumer_key_table_keys").set(self.table.key_count() as f64);
        gauge!("ingestion_consumer_key_table_queued_messages")
            .set(self.table.queued_messages() as f64);
        gauge!("ingestion_consumer_key_table_queued_bytes").set(self.table.queued_bytes() as f64);
        gauge!("ingestion_consumer_key_table_outstanding_keys")
            .set(self.table.outstanding_keys() as f64);
        gauge!("ingestion_consumer_key_table_parked_keys").set(self.table.parked_keys() as f64);
        gauge!("ingestion_consumer_packer_held_messages").set(self.packer.held_messages() as f64);
        gauge!("ingestion_consumer_packer_held_keys").set(self.packer.held_keys() as f64);
        gauge!("ingestion_consumer_packer_unplaced_batches").set(self.unplaced.len() as f64);
        gauge!("ingestion_consumer_packer_unplaced_messages").set(self.unplaced_messages as f64);
    }
}

impl Scheduler for KeyTableScheduler {
    /// Forward each free key's messages to the packer; an outstanding or
    /// parked key queues them — they go out behind the earlier ones, when
    /// the request settles or the parked retry fires.
    fn on_groups(
        &mut self,
        snapshot: &WorkerSnapshot,
        _batch_id: &str,
        assignment_epoch: u64,
        groups: Vec<KeyRun>,
    ) -> SchedulerEffects {
        let mut effects = SchedulerEffects::with_dispatch_capacity(groups.len());
        let mut load = working_load(snapshot);
        let now = self.now();

        for group in groups {
            if self.table.is_free(&group.routing_key) {
                let bytes = payload_bytes(&group.messages);
                // Fresh work routes within the aperture slice, like an
                // unpinned key in the pin-stash scheduler.
                self.forward(
                    &snapshot.candidates,
                    &mut load,
                    &group.routing_key,
                    assignment_epoch,
                    group.messages,
                    bytes,
                    now,
                    &mut effects,
                );
            } else {
                self.table
                    .enqueue_back(&group.routing_key, assignment_epoch, group.messages);
                // The group queues behind an outstanding request or a
                // parked backlog: the "why is this key not moving" signal.
                effects.deferred.queued_behind_deferral += 1;
            }
        }
        self.release_arrivals(&snapshot.candidates, &mut load, &mut effects);

        self.record_gauges();
        effects
    }

    /// Clear each settled key. Success forwards the key's queue to the
    /// packer, or evicts an emptied key. Failure requeues the failed runs at
    /// the front of their queues, then clears the flags — requeue before
    /// release, so a newer send can never overtake the failed messages — and
    /// parks the keys for the parked-retry deadline.
    fn on_settled(
        &mut self,
        snapshot: &WorkerSnapshot,
        settlement: Settlement,
    ) -> SchedulerEffects {
        let mut effects = SchedulerEffects::default();
        let mut load = working_load(snapshot);

        match settlement.outcome {
            SettlementOutcome::Delivered => {
                for key in &settlement.routing_keys {
                    if !self.table.settle_key(key) {
                        continue;
                    }
                    if let Some(drained) = self.table.drain_key(key) {
                        self.forward(
                            &snapshot.candidates,
                            &mut load,
                            key,
                            drained.epoch,
                            drained.messages,
                            drained.bytes,
                            drained.first_arrival,
                            &mut effects,
                        );
                    } else if self.table.evict_if_idle(key) {
                        effects.evicted_keys.push(key.clone());
                    }
                }
                self.release_arrivals(&snapshot.candidates, &mut load, &mut effects);
            }
            SettlementOutcome::Failed { runs, .. } => {
                effects.deferred.send_failed = runs.len() as u64;
                for run in runs {
                    self.table.requeue_front(&run.routing_key, run.messages);
                }
                for key in &settlement.routing_keys {
                    if !self.table.settle_key(key) {
                        continue;
                    }
                    // Failed work waits for the parked-retry deadline instead
                    // of retrying at once, so a failing worker pool gets a
                    // pause before the redelivery.
                    if self.table.queued_len(key) > 0 {
                        self.table.park(key);
                    } else if self.table.evict_if_idle(key) {
                        effects.evicted_keys.push(key.clone());
                    }
                }
            }
        }

        self.record_gauges();
        effects
    }

    /// Parked retry: resend every parked key that can route now, keep the
    /// rest parked for the next deadline. Pack: place every unplaced batch
    /// that can route now, then release the open batch if its deadline
    /// passed. The per-batch arm belongs to the pin-stash scheduler and is
    /// a no-op here.
    fn on_deadline(
        &mut self,
        snapshot: &WorkerSnapshot,
        deadline: Deadline<'_>,
    ) -> SchedulerEffects {
        match deadline {
            Deadline::ParkedRetry => self.retry_parked(snapshot),
            Deadline::Pack => {
                let mut effects = SchedulerEffects::default();
                let mut load = working_load(snapshot);
                // An unplaced batch escapes the aperture slice, like a
                // parked retry: the slice may be exactly what it could not
                // route into.
                self.place_unplaced(&snapshot.healthy, &mut load, &mut effects);
                if let Some(batch) = self.packer.take_expired(self.now()) {
                    self.place(batch, &snapshot.candidates, &mut load, &mut effects);
                }
                self.record_gauges();
                effects
            }
            Deadline::Batch(_) => SchedulerEffects::default(),
        }
    }

    /// Flush the packer before the purge, so the messages it held leave
    /// under their own epoch before the new assignment replays their
    /// partitions; a held key was not outstanding, so the purge would
    /// otherwise have dropped queued messages behind messages still to be
    /// sent.
    fn on_partitions_revoked(
        &mut self,
        snapshot: &WorkerSnapshot,
        partitions: &[(String, i32)],
    ) -> SchedulerEffects {
        let mut effects = SchedulerEffects::default();
        if let Some(batch) = self.packer.flush(self.now()) {
            let mut load = working_load(snapshot);
            self.place(batch, &snapshot.candidates, &mut load, &mut effects);
        }
        debug_assert!(self.packer.is_empty(), "a revoke leaves the packer empty");
        let (purged, evicted) = self.table.purge_partitions(partitions);
        if purged > 0 {
            counter!("ingestion_consumer_key_table_purged_messages_total").increment(purged as u64);
        }
        effects.evicted_keys = evicted;
        self.record_gauges();
        effects
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::time::Duration;

    use rstest::rstest;

    use super::*;
    use crate::routing::RoutingStrategy;
    use crate::scheduler::WorkerHealth;

    const A: &str = "http://worker:1";
    const B: &str = "http://worker:2";

    fn wid(s: &str) -> WorkerId {
        WorkerId::from(s)
    }

    fn msg(key: &str, offset: i64) -> SerializedKafkaMessage {
        SerializedKafkaMessage {
            topic: "test".to_string(),
            partition: 0,
            offset,
            timestamp: 0,
            key: Some(key.to_string()),
            value: None,
            headers: HashMap::new(),
        }
    }

    fn run(key: &str, offsets: &[i64]) -> KeyRun {
        KeyRun {
            routing_key: key.to_string(),
            messages: offsets.iter().map(|o| msg(key, *o)).collect(),
        }
    }

    /// Snapshot where every listed worker is live, with the given loads and
    /// candidates equal to the healthy pool.
    fn snapshot(live: &[&str], load: &[(&str, usize)]) -> WorkerSnapshot {
        snapshot_narrowed(live, live, load)
    }

    /// Snapshot with an aperture-narrowed candidate slice.
    fn snapshot_narrowed(
        live: &[&str],
        candidates: &[&str],
        load: &[(&str, usize)],
    ) -> WorkerSnapshot {
        let healthy: Vec<WorkerId> = live.iter().map(|w| wid(w)).collect();
        let candidates: Vec<WorkerId> = candidates.iter().map(|w| wid(w)).collect();
        let workers: HashMap<WorkerId, WorkerHealth> = live
            .iter()
            .map(|w| {
                (
                    wid(w),
                    WorkerHealth {
                        dead: false,
                        draining: false,
                    },
                )
            })
            .collect();
        let load: WorkerLoad = load.iter().map(|(w, n)| (wid(w), *n)).collect();
        WorkerSnapshot::new(healthy, candidates, load, workers)
    }

    fn scheduler() -> KeyTableScheduler {
        KeyTableScheduler::new(Router::with_seed(RoutingStrategy::BinPack, 0))
    }

    fn delivered(worker: &str, keys: &[&str]) -> Settlement {
        Settlement {
            worker: wid(worker),
            message_count: keys.len(),
            routing_keys: keys.iter().map(|k| k.to_string()).collect(),
            from_flush: false,
            outcome: SettlementOutcome::Delivered,
        }
    }

    fn failed(worker: &str, runs: Vec<KeyRun>) -> Settlement {
        Settlement {
            worker: wid(worker),
            message_count: runs.iter().map(|r| r.messages.len()).sum(),
            routing_keys: runs.iter().map(|r| r.routing_key.clone()).collect(),
            from_flush: false,
            outcome: SettlementOutcome::Failed {
                batch_id: "b".to_string(),
                runs,
            },
        }
    }

    fn offsets_of(dispatch: &Dispatch) -> Vec<i64> {
        dispatch
            .runs
            .iter()
            .flat_map(|run| run.messages.iter().map(|m| m.offset))
            .collect()
    }

    const HOUR: Duration = Duration::from_secs(3600);

    /// A scheduler that packs: a budget long enough that only the targets
    /// and explicit deadlines release a batch.
    fn packing_scheduler(events: usize, bytes: usize) -> KeyTableScheduler {
        let mut sched = scheduler();
        sched.set_pack_targets(PackTargets {
            events,
            bytes,
            latency_budget: HOUR,
        });
        sched
    }

    fn keys_of(dispatch: &Dispatch) -> Vec<&str> {
        dispatch
            .runs
            .iter()
            .map(|run| run.routing_key.as_str())
            .collect()
    }

    // ---- on_groups: arrival ----

    #[test]
    fn test_fresh_key_dispatches_its_whole_run_and_goes_outstanding() {
        let mut sched = scheduler();

        let effects = sched.on_groups(&snapshot(&[A], &[]), "b1", 0, vec![run("t:a", &[1, 2])]);

        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(effects.dispatches[0].worker, wid(A));
        assert_eq!(effects.dispatches[0].kind, SendKind::Fresh);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![1, 2]);
        assert_eq!(effects.deferred.total(), 0);
        assert_eq!(sched.table().outstanding_keys(), 1);
        assert_eq!(sched.table().queued_messages(), 0);
    }

    #[test]
    fn test_arrival_behind_an_outstanding_request_only_enqueues() {
        let mut sched = scheduler();
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b1", 0, vec![run("t:a", &[1])]);

        let effects = sched.on_groups(&snapshot(&[A], &[]), "b2", 0, vec![run("t:a", &[2])]);

        assert!(
            effects.dispatches.is_empty(),
            "at most one request per key may be in flight"
        );
        assert_eq!(effects.deferred.queued_behind_deferral, 1);
        assert_eq!(sched.table().queued_messages(), 1);
        assert_eq!(sched.table().queued_bytes(), "t:a".len());
        assert_eq!(sched.table().outstanding_keys(), 1);
    }

    #[test]
    fn test_intra_batch_placement_accounts_for_earlier_picks() {
        let mut sched = scheduler();

        // Two fresh equal-size runs, two idle workers: the first pick must
        // bump the working load so the second run lands on the other worker.
        let effects = sched.on_groups(
            &snapshot(&[A, B], &[]),
            "b1",
            0,
            vec![run("t:a", &[1, 2, 3]), run("t:b", &[1, 2, 3])],
        );

        assert_eq!(effects.dispatches.len(), 2);
        assert_ne!(effects.dispatches[0].worker, effects.dispatches[1].worker);
    }

    #[test]
    fn test_binpack_places_largest_run_first() {
        let mut sched = scheduler();

        let effects = sched.on_groups(
            &snapshot(&[A, B], &[]),
            "b1",
            0,
            vec![run("t:small", &[1]), run("t:big", &[1, 2, 3, 4, 5])],
        );

        assert_eq!(
            keys_of(&effects.dispatches[0]),
            vec!["t:big"],
            "heavy hitters drive the load distribution"
        );
    }

    #[test]
    fn test_duplicate_key_runs_in_one_call_merge_into_one_dispatch() {
        let mut sched = scheduler();

        let effects = sched.on_groups(
            &snapshot(&[A], &[]),
            "b1",
            0,
            vec![run("t:a", &[1]), run("t:a", &[2])],
        );

        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![1, 2]);
    }

    #[test]
    fn test_fresh_work_routes_within_the_aperture_slice() {
        let mut sched = scheduler();

        // B is healthy but outside the candidate slice — fresh work must not
        // land there.
        let effects = sched.on_groups(
            &snapshot_narrowed(&[A, B], &[A], &[]),
            "b1",
            0,
            vec![run("t:a", &[1])],
        );

        assert_eq!(effects.dispatches[0].worker, wid(A));
    }

    // ---- on_groups: unplaced ----

    #[test]
    fn test_unroutable_arrival_holds_the_batch_unplaced() {
        let mut sched = scheduler();

        let effects = sched.on_groups(&snapshot(&[], &[]), "b1", 0, vec![run("t:a", &[1, 2])]);

        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.unroutable, 1);
        assert_eq!(sched.unplaced_batches(), 1);
        assert_eq!(sched.held_messages(), 2);
        assert_eq!(sched.table().queued_messages(), 0);
        assert_eq!(
            sched.table().parked_keys(),
            0,
            "an unplaced batch parks no key"
        );
        assert_eq!(sched.table().outstanding_keys(), 1, "its key is taken");
    }

    #[test]
    fn test_arrival_behind_an_unplaced_batch_queues_until_it_is_placed() {
        let mut sched = scheduler();
        let _ = sched.on_groups(&snapshot(&[], &[]), "b1", 0, vec![run("t:a", &[1])]);

        // A worker is back, but the unplaced batch must go first, and only
        // the pack deadline places it.
        let effects = sched.on_groups(&snapshot(&[A], &[]), "b2", 0, vec![run("t:a", &[2])]);
        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.queued_behind_deferral, 1);
        assert_eq!(sched.table().queued_messages(), 1);

        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::Pack);
        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![1]);
        assert_eq!(effects.dispatches[0].kind, SendKind::Fresh);
        assert_eq!(sched.unplaced_batches(), 0);

        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:a"]));
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![2]);
    }

    // ---- on_settled: delivered ----

    #[test]
    fn test_settlement_dispatches_the_next_queued_run() {
        let mut sched = scheduler();
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b1", 0, vec![run("t:a", &[1])]);
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b2", 0, vec![run("t:a", &[2, 3])]);

        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:a"]));

        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(effects.dispatches[0].kind, SendKind::Fresh);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![2, 3]);
        assert!(effects.evicted_keys.is_empty(), "the key is busy again");
        assert_eq!(sched.table().outstanding_keys(), 1);
        assert_eq!(sched.table().queued_messages(), 0);
    }

    #[test]
    fn test_settlement_with_an_empty_queue_evicts_the_key() {
        let mut sched = scheduler();
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b1", 0, vec![run("t:a", &[1])]);

        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:a"]));

        assert_eq!(effects.evicted_keys, vec!["t:a".to_string()]);
        assert!(effects.dispatches.is_empty());
        assert_eq!(sched.table().key_count(), 0);
        assert_eq!(sched.table().outstanding_keys(), 0);
    }

    #[test]
    fn test_settlement_holds_the_next_run_unplaced_when_no_worker_is_routable() {
        let mut sched = scheduler();
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b1", 0, vec![run("t:a", &[1])]);
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b2", 0, vec![run("t:a", &[2])]);

        // The pool emptied while the send was in flight (deploy overlap).
        let effects = sched.on_settled(&snapshot(&[], &[]), delivered(A, &["t:a"]));

        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.unroutable, 1);
        assert_eq!(sched.unplaced_batches(), 1);
        assert_eq!(sched.table().parked_keys(), 0);
        assert_eq!(sched.table().outstanding_keys(), 1);
    }

    #[test]
    fn test_settlement_for_an_unknown_key_is_ignored() {
        let mut sched = scheduler();

        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:ghost"]));

        assert!(effects.dispatches.is_empty());
        assert!(effects.evicted_keys.is_empty());
        assert_eq!(sched.table().key_count(), 0);
    }

    // ---- on_settled: failed ----

    #[test]
    fn test_failed_settlement_requeues_at_the_front_and_parks() {
        let mut sched = scheduler();
        let _ = sched.on_groups(&snapshot(&[A, B], &[]), "b1", 0, vec![run("t:a", &[1, 2])]);
        // Newer messages arrive while the send is in flight.
        let _ = sched.on_groups(&snapshot(&[A, B], &[]), "b2", 0, vec![run("t:a", &[3])]);

        let effects = sched.on_settled(
            &snapshot(&[A, B], &[]),
            failed(A, vec![run("t:a", &[1, 2])]),
        );

        assert!(
            effects.dispatches.is_empty(),
            "failed work waits for the parked-retry deadline"
        );
        assert_eq!(effects.deferred.send_failed, 1);
        assert!(effects.evicted_keys.is_empty());
        assert_eq!(sched.table().parked_keys(), 1);
        assert_eq!(sched.table().outstanding_keys(), 0);

        // The retry redelivers the failed run ahead of the later arrival.
        let effects = sched.on_deadline(&snapshot(&[A, B], &[]), Deadline::ParkedRetry);
        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(effects.dispatches[0].kind, SendKind::Resend);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![1, 2, 3]);
    }

    #[test]
    fn test_a_run_that_fails_twice_is_resent_again_and_ends_clean() {
        let mut sched = scheduler();
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b1", 0, vec![run("t:a", &[1, 2])]);
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b2", 0, vec![run("t:a", &[3])]);
        let _ = sched.on_settled(&snapshot(&[A], &[]), failed(A, vec![run("t:a", &[1, 2])]));
        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::ParkedRetry);
        assert_eq!(effects.dispatches[0].kind, SendKind::Resend);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![1, 2, 3]);

        // The resend fails too: requeue, park, wait for the next deadline.
        let effects = sched.on_settled(
            &snapshot(&[A], &[]),
            failed(A, vec![run("t:a", &[1, 2, 3])]),
        );
        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.send_failed, 1);
        assert_eq!(sched.table().parked_keys(), 1);
        assert_eq!(sched.table().outstanding_keys(), 0);
        assert_eq!(sched.table().queued_messages(), 3);

        // The second retry is still a resend, in the same order.
        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::ParkedRetry);
        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(effects.dispatches[0].kind, SendKind::Resend);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![1, 2, 3]);
        assert_eq!(sched.table().parked_keys(), 0);
        assert_eq!(sched.table().outstanding_keys(), 1);

        // Delivery empties the key and evicts it.
        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:a"]));
        assert_eq!(effects.evicted_keys, vec!["t:a".to_string()]);
        assert_eq!(sched.table().key_count(), 0);
        assert_eq!(sched.table().outstanding_keys(), 0);
    }

    #[test]
    fn test_new_arrivals_queue_behind_a_failure_awaiting_retry() {
        let mut sched = scheduler();
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b1", 0, vec![run("t:a", &[1])]);
        let _ = sched.on_settled(&snapshot(&[A], &[]), failed(A, vec![run("t:a", &[1])]));

        let effects = sched.on_groups(&snapshot(&[A], &[]), "b2", 0, vec![run("t:a", &[2])]);

        assert!(
            effects.dispatches.is_empty(),
            "must not overtake the failed run"
        );
        assert_eq!(effects.deferred.queued_behind_deferral, 1);
        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::ParkedRetry);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![1, 2]);
    }

    #[test]
    fn test_a_run_never_mixes_assignment_epochs() {
        let mut sched = scheduler();
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b1", 5, vec![run("t:a", &[1])]);
        // Arrivals from two epochs queue behind the outstanding request.
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b2", 5, vec![run("t:a", &[2])]);
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b3", 6, vec![run("t:a", &[3])]);

        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:a"]));
        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![2]);
        assert_eq!(effects.dispatches[0].assignment_epoch, Some(5));

        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:a"]));
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![3]);
        assert_eq!(effects.dispatches[0].assignment_epoch, Some(6));
    }

    #[test]
    fn test_failed_settlement_for_an_unknown_key_is_not_parked() {
        let mut sched = scheduler();

        // Hand-built: the failed() helper derives routing_keys from runs, so
        // it cannot produce a key with no requeued messages.
        let settlement = Settlement {
            worker: wid(A),
            message_count: 0,
            routing_keys: vec!["t:ghost".to_string()],
            from_flush: false,
            outcome: SettlementOutcome::Failed {
                batch_id: "b".to_string(),
                runs: vec![],
            },
        };
        let effects = sched.on_settled(&snapshot(&[A], &[]), settlement);

        assert!(effects.dispatches.is_empty());
        assert_eq!(sched.table().key_count(), 0);
        assert_eq!(sched.table().parked_keys(), 0);

        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::ParkedRetry);
        assert!(
            effects.dispatches.is_empty(),
            "a stale key must not become a parked entry"
        );
        assert_eq!(sched.table().outstanding_keys(), 0);
    }

    // ---- on_deadline ----

    /// Park two keys through the only path that parks: a failed send.
    fn park_after_failure(sched: &mut KeyTableScheduler, keys: &[&str]) {
        let groups = keys.iter().map(|key| run(key, &[1])).collect();
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b1", 0, groups);
        for key in keys {
            let _ = sched.on_settled(&snapshot(&[A], &[]), failed(A, vec![run(key, &[1])]));
        }
        assert_eq!(sched.table().parked_keys(), keys.len());
    }

    #[test]
    fn test_batch_deadline_is_a_noop_for_the_key_table() {
        let mut sched = scheduler();
        park_after_failure(&mut sched, &["t:a"]);

        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::Batch("b1"));

        assert!(effects.dispatches.is_empty());
        assert_eq!(sched.table().parked_keys(), 1, "still parked");
    }

    #[test]
    fn test_parked_retry_dispatches_in_park_order_and_unparks() {
        let mut sched = scheduler();
        park_after_failure(&mut sched, &["t:a", "t:b"]);

        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::ParkedRetry);

        assert_eq!(effects.dispatches.len(), 2);
        assert_eq!(keys_of(&effects.dispatches[0]), vec!["t:a"]);
        assert_eq!(keys_of(&effects.dispatches[1]), vec!["t:b"]);
        assert_eq!(effects.dispatches[0].kind, SendKind::Resend);
        assert_eq!(sched.table().parked_keys(), 0);
        assert_eq!(sched.table().outstanding_keys(), 2);
    }

    #[test]
    fn test_parked_retry_keeps_keys_parked_when_no_worker_is_healthy() {
        let mut sched = scheduler();
        park_after_failure(&mut sched, &["t:a"]);

        let effects = sched.on_deadline(&snapshot(&[], &[]), Deadline::ParkedRetry);

        assert!(effects.dispatches.is_empty());
        assert_eq!(sched.table().parked_keys(), 1, "kept for a later deadline");

        // Arrivals in the meantime still queue behind the parked work.
        let effects = sched.on_groups(&snapshot(&[], &[]), "b2", 0, vec![run("t:a", &[2])]);
        assert!(effects.dispatches.is_empty());
        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::ParkedRetry);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![1, 2]);
    }

    #[test]
    fn test_parked_retry_routes_over_the_whole_healthy_pool() {
        let mut sched = scheduler();
        park_after_failure(&mut sched, &["t:a"]);

        // The aperture slice is empty but a worker is healthy: the retry must
        // escape the slice, like a deferred flush.
        let effects = sched.on_deadline(&snapshot_narrowed(&[B], &[], &[]), Deadline::ParkedRetry);

        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(effects.dispatches[0].worker, wid(B));
    }

    #[test]
    fn test_revoked_partitions_purge_queued_messages() {
        let mut sched = scheduler();
        // Key a queues behind its outstanding request; key b's batch finds
        // no worker and waits unplaced.
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b1", 0, vec![run("t:a", &[1])]);
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b2", 0, vec![run("t:a", &[2])]);
        let _ = sched.on_groups(&snapshot(&[], &[]), "b3", 0, vec![run("t:b", &[1])]);

        // An unrelated partition purges nothing.
        let effects = sched.on_partitions_revoked(&snapshot(&[A], &[]), &[("test".to_string(), 7)]);
        assert!(effects.evicted_keys.is_empty());
        assert_eq!(sched.table().queued_messages(), 1);

        let effects = sched.on_partitions_revoked(&snapshot(&[A], &[]), &[("test".to_string(), 0)]);

        assert_eq!(sched.table().queued_messages(), 0);
        assert_eq!(sched.table().queued_bytes(), 0);
        assert!(
            effects.evicted_keys.is_empty(),
            "both keys are outstanding: one on the wire, one unplaced"
        );
        assert_eq!(sched.table().outstanding_keys(), 2);
        assert_eq!(
            sched.unplaced_batches(),
            1,
            "an unplaced batch survives the purge"
        );

        // Both keys end clean: a's settlement finds nothing queued, and b's
        // batch is placed at the next deadline like any released work.
        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:a"]));
        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.evicted_keys, vec!["t:a".to_string()]);
        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::Pack);
        assert_eq!(keys_of(&effects.dispatches[0]), vec!["t:b"]);
        let _ = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:b"]));
        assert_eq!(sched.table().key_count(), 0);
    }

    #[test]
    fn test_revoked_outstanding_failure_is_not_retried() {
        let mut sched = scheduler();
        let live = snapshot(&[A], &[]);
        let sent = sched.on_groups(&live, "b1", 5, vec![run("t:a", &[1])]);
        assert_eq!(sent.dispatches.len(), 1);

        // No queued messages exist to identify the outstanding run during purge.
        let _ = sched.on_partitions_revoked(&live, &[("test".to_string(), 0)]);
        let settled = sched.on_settled(&live, failed(A, vec![run("t:a", &[1])]));
        assert!(settled.dispatches.is_empty());

        let retry = sched.on_deadline(&live, Deadline::ParkedRetry);
        assert!(
            retry.dispatches.is_empty(),
            "a failed send must not resurrect revoked work"
        );
        assert_eq!(sched.table().key_count(), 0);
        assert_eq!(sched.table().queued_messages(), 0);
        assert_eq!(sched.table().queued_bytes(), 0);
        assert_eq!(sched.table().outstanding_keys(), 0);
        assert_eq!(sched.table().parked_keys(), 0);
    }

    #[test]
    fn test_revoked_outstanding_failure_preserves_kept_partitions() {
        let mut sched = scheduler();
        let live = snapshot(&[A], &[]);
        let mixed_run = || {
            let mut mixed = run("t:a", &[1, 2, 3, 4]);
            mixed.messages[1].partition = 1;
            mixed.messages[2].topic = "other".to_string();
            mixed.messages[3].partition = 2;
            mixed
        };
        let sent = sched.on_groups(&live, "b1", 5, vec![mixed_run()]);
        assert_eq!(sent.dispatches.len(), 1);

        let _ = sched.on_partitions_revoked(&live, &[("test".to_string(), 0)]);
        let _ = sched.on_partitions_revoked(&live, &[("test".to_string(), 2)]);
        let _ = sched.on_settled(&live, failed(A, vec![mixed_run()]));

        let retry = sched.on_deadline(&live, Deadline::ParkedRetry);
        assert_eq!(retry.dispatches.len(), 1);
        assert_eq!(
            offsets_of(&retry.dispatches[0]),
            vec![2, 3],
            "only revoked topic-partitions may be discarded"
        );
        assert_eq!(retry.dispatches[0].assignment_epoch, Some(5));
        let _ = sched.on_settled(&live, delivered(A, &["t:a"]));
        assert_eq!(sched.table().key_count(), 0);
        assert_eq!(sched.table().queued_bytes(), 0);
    }

    #[test]
    fn test_revoked_outstanding_failure_preserves_reassigned_work() {
        let mut sched = scheduler();
        let live = snapshot(&[A], &[]);
        let sent = sched.on_groups(&live, "b1", 5, vec![run("t:a", &[1])]);
        assert_eq!(sent.dispatches.len(), 1);
        let _ = sched.on_partitions_revoked(&live, &[("test".to_string(), 0)]);

        // The same offset is polled again before the old send settles.
        let queued = sched.on_groups(&live, "b2", 6, vec![run("t:a", &[1, 2])]);
        assert!(queued.dispatches.is_empty());
        let _ = sched.on_settled(&live, failed(A, vec![run("t:a", &[1])]));

        let retry = sched.on_deadline(&live, Deadline::ParkedRetry);
        assert_eq!(retry.dispatches.len(), 1);
        assert_eq!(offsets_of(&retry.dispatches[0]), vec![1, 2]);
        assert_eq!(retry.dispatches[0].assignment_epoch, Some(6));
        assert_eq!(retry.dispatches[0].kind, SendKind::Fresh);

        // Revocation of the old assignment must not suppress this run's retries.
        let _ = sched.on_settled(&live, failed(A, vec![run("t:a", &[1, 2])]));
        let retry = sched.on_deadline(&live, Deadline::ParkedRetry);
        assert_eq!(retry.dispatches.len(), 1);
        assert_eq!(offsets_of(&retry.dispatches[0]), vec![1, 2]);
        assert_eq!(retry.dispatches[0].assignment_epoch, Some(6));
        assert_eq!(retry.dispatches[0].kind, SendKind::Resend);
        let _ = sched.on_settled(&live, delivered(A, &["t:a"]));
        assert_eq!(sched.table().key_count(), 0);
        assert_eq!(sched.table().queued_bytes(), 0);
    }

    // ---- lifecycle ----

    #[test]
    fn test_full_lifecycle_preserves_per_key_order_and_ends_clean() {
        let mut sched = scheduler();
        let mut sent: Vec<i64> = Vec::new();
        let mut record = |effects: &SchedulerEffects| {
            for dispatch in &effects.dispatches {
                assert_eq!(keys_of(dispatch), vec!["t:a"]);
                sent.extend(offsets_of(dispatch));
            }
            effects.dispatches.len()
        };

        // Arrive, dispatch, fail, queue more, retry, settle, queue drains.
        let effects = sched.on_groups(&snapshot(&[A], &[]), "b1", 0, vec![run("t:a", &[1, 2])]);
        assert_eq!(record(&effects), 1);
        let effects = sched.on_groups(&snapshot(&[A], &[]), "b2", 0, vec![run("t:a", &[3])]);
        assert_eq!(record(&effects), 0);
        let effects = sched.on_settled(&snapshot(&[A], &[]), failed(A, vec![run("t:a", &[1, 2])]));
        assert_eq!(record(&effects), 0);
        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::ParkedRetry);
        assert_eq!(record(&effects), 1);
        let effects = sched.on_groups(&snapshot(&[A], &[]), "b3", 0, vec![run("t:a", &[4])]);
        assert_eq!(record(&effects), 0);
        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:a"]));
        assert_eq!(record(&effects), 1);
        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:a"]));
        assert_eq!(record(&effects), 0);

        // The failed prefix is redelivered once, and every offset goes out in order.
        assert_eq!(sent, vec![1, 2, 1, 2, 3, 4]);
        assert_eq!(effects.evicted_keys, vec!["t:a".to_string()]);
        assert_eq!(sched.table().key_count(), 0);
        assert_eq!(sched.table().queued_messages(), 0);
        assert_eq!(sched.table().queued_bytes(), 0);
        assert_eq!(sched.table().outstanding_keys(), 0);
        assert_eq!(sched.table().parked_keys(), 0);
    }

    #[test]
    fn test_keys_progress_independently() {
        let mut sched = scheduler();
        let _ = sched.on_groups(
            &snapshot(&[A, B], &[]),
            "b1",
            0,
            vec![run("t:a", &[1]), run("t:b", &[1])],
        );
        let _ = sched.on_groups(
            &snapshot(&[A, B], &[]),
            "b2",
            0,
            vec![run("t:a", &[2]), run("t:b", &[2])],
        );

        // Only t:a settles — only t:a's next run may go out.
        let effects = sched.on_settled(&snapshot(&[A, B], &[]), delivered(A, &["t:a"]));

        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(keys_of(&effects.dispatches[0]), vec!["t:a"]);
        assert_eq!(sched.table().queued_messages(), 1, "t:b still queued");
    }

    // ---- packing ----

    /// A key's messages are in exactly one place: the open batch, a request
    /// in flight (or waiting unplaced), or the key's queue. The queue holds
    /// messages only behind an outstanding or parked key.
    fn assert_single_location(sched: &KeyTableScheduler, key: &str) {
        let held = sched.packer.held_for(key);
        let queued = sched.table().queued_len(key);
        let outstanding = sched.table().is_outstanding(key);
        let parked = sched.table().is_parked(key);
        if held > 0 {
            assert!(
                !outstanding && !parked && queued == 0,
                "{key}: held {held} while outstanding={outstanding} parked={parked} queued={queued}"
            );
        }
        if queued > 0 {
            assert!(
                outstanding || parked,
                "{key}: {queued} queued behind nothing"
            );
        }
    }

    /// Arrivals in one `on_groups` call per entry of `calls`, on one worker.
    struct PackArrivals {
        targets: PackTargets,
        calls: &'static [&'static [(&'static str, &'static [i64])]],
    }

    struct ExpectedPacking {
        /// Dispatches released by each call.
        released: &'static [usize],
        /// Keys of the last released batch, in first-arrival order; empty
        /// when no call released one.
        last_batch_keys: &'static [&'static str],
        held_messages: usize,
    }

    #[rstest]
    #[case::event_target_across_keys(
        PackArrivals {
            targets: PackTargets { events: 3, bytes: 0, latency_budget: HOUR },
            calls: &[&[("t:a", &[1, 2])], &[("t:b", &[3])]],
        },
        ExpectedPacking { released: &[0, 1], last_batch_keys: &["t:a", "t:b"], held_messages: 0 },
    )]
    #[case::byte_target_across_keys(
        // Every test message carries a 3-byte key and no value.
        PackArrivals {
            targets: PackTargets { events: 0, bytes: 9, latency_budget: HOUR },
            calls: &[&[("t:a", &[1]), ("t:b", &[2])], &[("t:c", &[3])]],
        },
        ExpectedPacking { released: &[0, 1], last_batch_keys: &["t:a", "t:b", "t:c"], held_messages: 0 },
    )]
    #[case::one_key_past_the_target_releases_alone(
        PackArrivals {
            targets: PackTargets { events: 2, bytes: 0, latency_budget: HOUR },
            calls: &[&[("t:a", &[1, 2, 3])]],
        },
        ExpectedPacking { released: &[1], last_batch_keys: &["t:a"], held_messages: 0 },
    )]
    #[case::short_of_both_targets_stays_held(
        PackArrivals {
            targets: PackTargets { events: 10, bytes: 100, latency_budget: HOUR },
            calls: &[&[("t:a", &[1]), ("t:b", &[2])]],
        },
        ExpectedPacking { released: &[0], last_batch_keys: &[], held_messages: 2 },
    )]
    fn test_packing_releases_at_the_target(
        #[case] arrivals: PackArrivals,
        #[case] expected: ExpectedPacking,
    ) {
        let mut sched = scheduler();
        sched.set_pack_targets(arrivals.targets);
        let mut last_batch: Option<Dispatch> = None;

        for (index, call) in arrivals.calls.iter().enumerate() {
            let groups = call
                .iter()
                .map(|(key, offsets)| run(key, offsets))
                .collect();
            let mut effects = sched.on_groups(&snapshot(&[A], &[]), "b", 0, groups);
            assert_eq!(
                effects.dispatches.len(),
                expected.released[index],
                "call {index}"
            );
            if let Some(dispatch) = effects.dispatches.pop() {
                last_batch = Some(dispatch);
            }
            for (key, _) in call.iter() {
                assert_single_location(&sched, key);
            }
        }

        let last_keys: Vec<&str> = last_batch.as_ref().map(keys_of).unwrap_or_default();
        assert_eq!(last_keys, expected.last_batch_keys);
        assert_eq!(sched.held_messages(), expected.held_messages);
    }

    #[test]
    fn test_a_zero_budget_sends_each_key_at_the_end_of_the_seam_call() {
        let mut sched = scheduler();

        // Two keys in one poll leave as two batches, placed independently:
        // bin-packing spreads them over both idle workers.
        let effects = sched.on_groups(
            &snapshot(&[A, B], &[]),
            "b1",
            0,
            vec![run("t:a", &[1, 2]), run("t:b", &[3, 4])],
        );

        assert_eq!(effects.dispatches.len(), 2);
        assert_ne!(effects.dispatches[0].worker, effects.dispatches[1].worker);
        assert_eq!(sched.held_messages(), 0);
        assert_eq!(sched.table().outstanding_keys(), 2);
    }

    #[test]
    fn test_a_hot_key_keeps_appending_until_release() {
        let mut sched = packing_scheduler(4, 0);
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b1", 0, vec![run("t:a", &[1])]);
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b2", 0, vec![run("t:a", &[2])]);
        assert_eq!(sched.packer.held_for("t:a"), 2);
        assert_eq!(
            sched.table().queued_messages(),
            0,
            "nothing in flight, so nothing queues"
        );
        assert!(!sched.table().is_outstanding("t:a"));
        assert_single_location(&sched, "t:a");

        // The fourth message fills the batch: one run for the key, in order.
        let effects = sched.on_groups(&snapshot(&[A], &[]), "b3", 0, vec![run("t:a", &[3, 4])]);

        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(keys_of(&effects.dispatches[0]), vec!["t:a"]);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![1, 2, 3, 4]);
        assert!(
            sched.table().is_outstanding("t:a"),
            "outstanding only at release"
        );
        assert_single_location(&sched, "t:a");
    }

    #[test]
    fn test_an_arrival_for_an_outstanding_key_queues_until_settlement_forwards_it() {
        let mut sched = packing_scheduler(2, 0);
        let effects = sched.on_groups(
            &snapshot(&[A], &[]),
            "b1",
            0,
            vec![run("t:a", &[1]), run("t:b", &[2])],
        );
        assert_eq!(effects.dispatches.len(), 1, "full");

        let effects = sched.on_groups(&snapshot(&[A], &[]), "b2", 0, vec![run("t:a", &[3])]);
        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.queued_behind_deferral, 1);
        assert_eq!(sched.table().queued_len("t:a"), 1);
        assert_eq!(
            sched.packer.held_for("t:a"),
            0,
            "never in the batch while outstanding"
        );
        assert_single_location(&sched, "t:a");

        // Settlement drains the queue into the packer, not into a dispatch.
        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:a", "t:b"]));
        assert!(effects.dispatches.is_empty());
        assert_eq!(sched.packer.held_for("t:a"), 1);
        assert_eq!(sched.table().queued_len("t:a"), 0);
        assert!(!sched.table().is_outstanding("t:a"));
        assert_eq!(effects.evicted_keys, vec!["t:b".to_string()]);
        assert_single_location(&sched, "t:a");

        let effects = sched.on_groups(&snapshot(&[A], &[]), "b3", 0, vec![run("t:c", &[4])]);
        assert_eq!(keys_of(&effects.dispatches[0]), vec!["t:a", "t:c"]);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![3, 4]);
    }

    #[test]
    fn test_a_released_batch_is_placed_against_the_snapshot_at_release() {
        let mut sched = packing_scheduler(2, 0);
        // A is the lighter worker when the batch opens.
        let _ = sched.on_groups(
            &snapshot(&[A, B], &[(B, 100)]),
            "b1",
            0,
            vec![run("t:a", &[1])],
        );
        assert_eq!(sched.held_messages(), 1);

        // By the time the batch fills, B is the lighter one: the batch goes
        // to B as one multi-key dispatch.
        let effects = sched.on_groups(
            &snapshot(&[A, B], &[(A, 100)]),
            "b2",
            0,
            vec![run("t:b", &[2])],
        );

        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(effects.dispatches[0].worker, wid(B));
        assert_eq!(keys_of(&effects.dispatches[0]), vec!["t:a", "t:b"]);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![1, 2]);
        assert_eq!(effects.dispatches[0].assignment_epoch, Some(0));
        assert_eq!(sched.held_messages(), 0);
    }

    #[test]
    fn test_held_messages_do_not_appear_in_working_load() {
        let mut sched = packing_scheduler(10, 0);
        // Three messages held; they sit on no worker.
        let _ = sched.on_groups(
            &snapshot(&[A, B], &[]),
            "b1",
            0,
            vec![run("t:a", &[1, 2, 3])],
        );

        // The pool's recorded load is A 1, B 2. Bin-packing must pick A: the
        // held messages count for neither.
        let effects = sched.on_groups(
            &snapshot(&[A, B], &[(A, 1), (B, 2)]),
            "b2",
            0,
            vec![run("t:b", &[4; 7])],
        );

        assert_eq!(effects.dispatches.len(), 1, "reached the target");
        assert_eq!(effects.dispatches[0].worker, wid(A));
    }

    #[test]
    fn test_an_unplaced_batch_is_placed_once_a_worker_appears() {
        let mut sched = packing_scheduler(2, 0);
        let _ = sched.on_groups(&snapshot(&[], &[]), "b1", 0, vec![run("t:a", &[1])]);
        let effects = sched.on_groups(&snapshot(&[], &[]), "b2", 0, vec![run("t:b", &[2])]);
        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.unroutable, 2, "both keys of the batch");
        assert_eq!(sched.unplaced_batches(), 1);
        assert_eq!(sched.held_messages(), 2);
        assert!(
            sched.table().is_outstanding("t:a"),
            "released, so outstanding"
        );
        assert_single_location(&sched, "t:a");

        // Still nothing routable: the batch waits for the next tick.
        let effects = sched.on_deadline(&snapshot(&[], &[]), Deadline::Pack);
        assert!(effects.dispatches.is_empty());
        assert_eq!(sched.unplaced_batches(), 1);

        // A worker outside the aperture slice is enough: the retry routes
        // over the healthy pool.
        let effects = sched.on_deadline(&snapshot_narrowed(&[B], &[], &[]), Deadline::Pack);
        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(effects.dispatches[0].worker, wid(B));
        assert_eq!(keys_of(&effects.dispatches[0]), vec!["t:a", "t:b"]);
        assert_eq!(sched.unplaced_batches(), 0);
        assert_eq!(sched.held_messages(), 0);
        assert_eq!(sched.table().outstanding_keys(), 2);
    }

    #[test]
    fn test_messages_from_a_newer_epoch_release_the_held_batch_first() {
        let mut sched = packing_scheduler(10, 0);
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b1", 5, vec![run("t:a", &[1])]);

        let effects = sched.on_groups(&snapshot(&[A], &[]), "b2", 6, vec![run("t:b", &[2])]);

        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(keys_of(&effects.dispatches[0]), vec!["t:a"]);
        assert_eq!(effects.dispatches[0].assignment_epoch, Some(5));
        assert_eq!(sched.packer.epoch(), Some(6));
        assert_eq!(sched.held_messages(), 1);
    }

    #[test]
    fn test_the_pack_deadline_releases_the_batch_once_its_budget_expires() {
        let mut sched = scheduler();
        let budget = Duration::from_millis(50);
        sched.set_pack_targets(PackTargets {
            events: 100,
            bytes: 0,
            latency_budget: budget,
        });
        let t0 = Instant::now();
        sched.set_now(t0);
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b1", 0, vec![run("t:a", &[1])]);
        // The deadline is the first message's arrival plus the budget; a
        // later key does not extend it.
        sched.set_now(t0 + budget / 2);
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b2", 0, vec![run("t:b", &[2])]);

        sched.set_now(t0 + budget - Duration::from_millis(1));
        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::Pack);
        assert!(effects.dispatches.is_empty());
        assert_eq!(sched.held_messages(), 2);

        sched.set_now(t0 + budget);
        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::Pack);
        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(keys_of(&effects.dispatches[0]), vec!["t:a", "t:b"]);
        assert_eq!(effects.dispatches[0].kind, SendKind::Fresh);
        assert_eq!(effects.dispatches[0].assignment_epoch, Some(0));
        assert_eq!(sched.held_messages(), 0);
        assert_eq!(sched.table().outstanding_keys(), 2);
    }

    #[test]
    fn test_the_pack_deadline_is_a_noop_at_a_zero_budget() {
        let mut sched = scheduler();
        let _ = sched.on_groups(&snapshot(&[A], &[]), "b1", 0, vec![run("t:a", &[1])]);

        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::Pack);

        assert!(effects.dispatches.is_empty());
        assert!(effects.evicted_keys.is_empty());
    }

    #[test]
    fn test_a_revoke_flushes_the_packer_before_the_purge() {
        let mut sched = packing_scheduler(100, 0);
        let live = snapshot(&[A], &[]);
        let _ = sched.on_groups(&live, "b1", 5, vec![run("t:a", &[1]), run("t:b", &[2])]);
        assert_eq!(sched.held_messages(), 2);
        assert_eq!(sched.table().queued_messages(), 0);

        let effects = sched.on_partitions_revoked(&live, &[("test".to_string(), 0)]);

        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(keys_of(&effects.dispatches[0]), vec!["t:a", "t:b"]);
        assert_eq!(effects.dispatches[0].assignment_epoch, Some(5));
        assert!(sched.packer.is_empty());
        assert_eq!(sched.held_messages(), 0);
        assert_eq!(sched.table().outstanding_keys(), 2, "on the wire now");

        // A failure after the revoke does not resurrect the flushed messages.
        let _ = sched.on_settled(&live, failed(A, vec![run("t:a", &[1]), run("t:b", &[2])]));
        let retry = sched.on_deadline(&live, Deadline::ParkedRetry);
        assert!(retry.dispatches.is_empty());
        assert_eq!(sched.table().key_count(), 0);
    }

    #[test]
    fn test_a_failed_send_resends_past_the_packer() {
        let mut sched = packing_scheduler(100, 0);
        let live = snapshot(&[A], &[]);
        // Fill the target once so a batch is on the wire, then fail it.
        sched.set_pack_targets(PackTargets {
            events: 2,
            bytes: 0,
            latency_budget: HOUR,
        });
        let sent = sched.on_groups(&live, "b1", 0, vec![run("t:a", &[1]), run("t:b", &[2])]);
        assert_eq!(sent.dispatches.len(), 1);
        sched.set_pack_targets(PackTargets {
            events: 100,
            bytes: 0,
            latency_budget: HOUR,
        });
        // Something else is held meanwhile.
        let _ = sched.on_groups(&live, "b2", 0, vec![run("t:c", &[3])]);

        let effects = sched.on_settled(&live, failed(A, vec![run("t:a", &[1]), run("t:b", &[2])]));
        assert!(effects.dispatches.is_empty());
        assert_eq!(sched.table().parked_keys(), 2);
        assert_single_location(&sched, "t:a");

        let effects = sched.on_deadline(&live, Deadline::ParkedRetry);

        assert_eq!(effects.dispatches.len(), 2, "one direct resend per key");
        assert!(effects
            .dispatches
            .iter()
            .all(|dispatch| dispatch.kind == SendKind::Resend));
        assert_eq!(sched.packer.held_for("t:a"), 0);
        assert_eq!(sched.held_messages(), 1, "t:c is still held");
        assert_eq!(sched.table().outstanding_keys(), 2);
        assert_single_location(&sched, "t:a");
        assert_single_location(&sched, "t:c");
    }

    #[test]
    fn test_a_key_lives_in_exactly_one_place_through_its_lifecycle() {
        let mut sched = packing_scheduler(2, 0);
        let live = snapshot(&[A], &[]);
        let check = |sched: &KeyTableScheduler| {
            for key in ["t:a", "t:b"] {
                assert_single_location(sched, key);
            }
        };

        let _ = sched.on_groups(&live, "b1", 0, vec![run("t:a", &[1])]);
        check(&sched);
        let _ = sched.on_groups(&live, "b2", 0, vec![run("t:b", &[2])]);
        check(&sched);
        let _ = sched.on_groups(&live, "b3", 0, vec![run("t:a", &[3]), run("t:b", &[4])]);
        check(&sched);
        let _ = sched.on_settled(&live, failed(A, vec![run("t:a", &[1]), run("t:b", &[2])]));
        check(&sched);
        let _ = sched.on_groups(&live, "b4", 0, vec![run("t:a", &[5])]);
        check(&sched);
        let _ = sched.on_deadline(&live, Deadline::ParkedRetry);
        check(&sched);
        let _ = sched.on_settled(&live, delivered(A, &["t:a", "t:b"]));
        check(&sched);
        let _ = sched.on_deadline(&live, Deadline::Pack);
        check(&sched);
        let _ = sched.on_settled(&live, delivered(A, &["t:a", "t:b"]));
        check(&sched);
        assert_eq!(sched.table().key_count(), 0);
        assert_eq!(sched.held_messages(), 0);
    }
}
