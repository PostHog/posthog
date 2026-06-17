//! The `cohort_stream_events` wire envelope and the group consumer that drives it.
//!
//! [`CohortStreamEvent`] is the processor's own deserialize struct, deliberately decoupled from
//! `cohort-event-shuffler`'s producer type: the two services share only the JSON field names, so a
//! private copy means neither can break the other by adding a one-sided field.
//!
//! The Kafka-free routing core lives in [`EventDispatcher`] so it can be unit-tested with an
//! in-process router/store/catalog and no broker.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use dashmap::mapref::entry::Entry;
use dashmap::{DashMap, DashSet};
use lifecycle::Handle;
use metrics::{counter, gauge, histogram};
use rdkafka::consumer::{CommitMode, Consumer, ConsumerContext, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::{Offset, TopicPartitionList};
use serde::{Deserialize, Serialize};
use tracing::{debug, info, warn};

use crate::consumers::merges::{ConsumedCascade, ConsumedMerge, ConsumedTransfer};
use crate::filters::manager::CatalogHandle;
use crate::observability::metrics::{
    CASCADE_HELD_OFFSET_GAUGE, COHORT_STREAM_CASCADES_SKIPPED_NOT_OWNED,
    COHORT_STREAM_CONSUME_BATCH_SIZE, COHORT_STREAM_DESERIALIZE_ERRORS,
    COHORT_STREAM_EMPTY_PAYLOAD, COHORT_STREAM_EVENTS_CONSUMED, COHORT_STREAM_EVENTS_DISPATCHED,
    COHORT_STREAM_EVENTS_SKIPPED_NOT_OWNED, COHORT_STREAM_KAFKA_RECV_ERRORS,
    COHORT_STREAM_MERGES_SKIPPED_NOT_OWNED, COHORT_STREAM_OFFSET_COMMITS,
    COHORT_STREAM_OFFSET_COMMIT_ERRORS, COHORT_STREAM_ROUTE_ERRORS,
    COHORT_STREAM_TRANSFERS_SKIPPED_NOT_OWNED, COHORT_STREAM_WORKERS_SPAWNED,
    MERGE_HELD_OFFSET_GAUGE, MERGE_PENDING_TRANSFERS_GAUGE, PARTITIONS_ASSIGNED_TOTAL,
    PARTITIONS_REVOKED_TOTAL, PARTITION_STATE_DELETED_TOTAL, REBALANCE_CLEANUP_SKIPPED_TOTAL,
    REVOKE_DRAIN_DURATION_SECONDS,
};
use crate::partitions::offset_tracker::OffsetTracker;
use crate::partitions::rebalance::{CohortConsumerContext, ConsumerCommandReceiver};
use crate::partitions::router::PartitionRouter;
use crate::partitions::shuffle_message::ShuffleMessage;
use crate::producer::MembershipSink;
use crate::store::CohortStore;
use crate::workers::{MergeWorkerDeps, Stage1Worker};

/// Back-off after a Kafka transport error so a fast-failing `recv()` can't spin a consume loop.
pub(crate) const RECV_ERROR_BACKOFF: Duration = Duration::from_millis(500);

/// One re-keyed event as published to `cohort_stream_events`. Field names mirror the shuffler
/// envelope exactly.
///
/// `properties` / `person_properties` are raw JSON strings parsed lazily in globals construction.
/// `source_partition` / `source_offset` are the upstream coordinates for replay-safe counter
/// increments.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CohortStreamEvent {
    pub team_id: i32,
    pub person_id: String,
    pub distinct_id: String,
    pub uuid: String,
    pub event: String,
    /// ClickHouse wire format `"YYYY-MM-DD HH:MM:SS.ffffff"`; normalized to ISO 8601 in globals.
    pub timestamp: String,
    pub properties: Option<String>,
    pub person_properties: Option<String>,
    pub elements_chain: Option<String>,
    pub source_offset: i64,
    pub source_partition: i32,
    /// The merge origin person, set when a post-merge straggler is redirected to the merged-into
    /// person. `None` for a normal event. Stage 1 routes replay-dedup through
    /// `redirect_dedup[origin]` when set, preventing double-fold.
    #[serde(default)]
    pub redirected_from: Option<String>,
    /// Cross-partition re-produce hops this straggler has taken through the tombstone redirect.
    /// `0` for a normal event; incremented on each re-key produce. At the cap
    /// (`MAX_CROSS_PARTITION_REDIRECT_HOPS`) the worker degrades to an inline fold to break cycles.
    #[serde(default)]
    pub redirect_hops: u8,
}

/// One event consumed from `cohort_stream_events`, paired with its commit coordinates on that topic.
///
/// `partition`/`offset` here are commit coordinates, distinct from the event's upstream
/// `source_partition`/`source_offset` which drive per-key replay idempotence.
#[derive(Debug)]
pub struct ConsumedEvent {
    pub event: CohortStreamEvent,
    pub partition: i32,
    pub offset: i64,
}

/// The Kafka-free routing core: dispatches consumed batches to per-partition workers, tracks
/// processed offsets, and owns the partition lifecycle the rebalance handler drives.
pub struct EventDispatcher {
    router: Arc<PartitionRouter>,
    tracker: Arc<OffsetTracker>,
    workers: Arc<DashMap<i32, Stage1Worker>>,
    /// Partitions currently assigned to this consumer.
    owned: Arc<DashSet<i32>>,
    store: CohortStore,
    catalog: Arc<CatalogHandle>,
    sink: Arc<dyn MembershipSink>,
    merge: Arc<MergeWorkerDeps>,
    /// Set by [`shutdown`](Self::shutdown), consulted by every dispatch entry point and
    /// [`ensure_worker`](Self::ensure_worker). Prevents post-shutdown worker registration that would
    /// hang the join. The structural guarantee is the router's terminal closed state, which refuses
    /// registration after `clear()`.
    draining: AtomicBool,
}

impl EventDispatcher {
    pub fn new(
        router: PartitionRouter,
        tracker: Arc<OffsetTracker>,
        store: CohortStore,
        catalog: Arc<CatalogHandle>,
        sink: Arc<dyn MembershipSink>,
        merge: Arc<MergeWorkerDeps>,
    ) -> Self {
        Self {
            router: Arc::new(router),
            tracker,
            workers: Arc::new(DashMap::new()),
            owned: Arc::new(DashSet::new()),
            store,
            catalog,
            sink,
            merge,
            draining: AtomicBool::new(false),
        }
    }

    /// Route a consumed batch to its per-partition workers, lazily spawning a worker per
    /// first-seen partition.
    ///
    /// Offsets are marked by the worker after producing, not here. The dispatch ceiling
    /// (`mark_dispatched`) is raised before routing so a `RouteError` leaves the offset uncommittable
    /// and Kafka replays it. Events for unowned partitions are dropped before any ceiling bump.
    pub async fn dispatch(&self, batch: Vec<ConsumedEvent>) {
        if batch.is_empty() {
            return;
        }
        let items = batch
            .into_iter()
            .map(|consumed| {
                (
                    consumed.partition,
                    consumed.offset,
                    ShuffleMessage::Event {
                        event: consumed.event,
                        cse_offset: consumed.offset,
                    },
                )
            })
            .collect();
        let stats = self.dispatch_to_workers(items, &self.tracker).await;
        counter!(COHORT_STREAM_EVENTS_SKIPPED_NOT_OWNED).increment(stats.not_owned_skipped);
        counter!(COHORT_STREAM_EVENTS_DISPATCHED).increment(stats.dispatched);
    }

    /// Route a consumed `person_merge_events` batch to per-partition workers, ceiling marked on the
    /// merge tracker. Spawns workers (unlike sweep) because merges are durable external input.
    pub async fn dispatch_merges(&self, batch: Vec<ConsumedMerge>) {
        if batch.is_empty() {
            return;
        }
        let items = batch
            .into_iter()
            .map(|consumed| {
                (
                    consumed.partition,
                    consumed.offset,
                    ShuffleMessage::Merge {
                        event: consumed.event,
                        offset: consumed.offset,
                    },
                )
            })
            .collect();
        let stats = self
            .dispatch_to_workers(items, &self.merge.merge_tracker)
            .await;
        counter!(COHORT_STREAM_MERGES_SKIPPED_NOT_OWNED).increment(stats.not_owned_skipped);
    }

    /// Route a consumed `cohort_merge_state_transfer` batch to per-partition workers, ceiling marked
    /// on the transfer tracker. Spawns workers because a dropped transfer is unrecoverable.
    pub async fn dispatch_transfers(&self, batch: Vec<ConsumedTransfer>) {
        if batch.is_empty() {
            return;
        }
        let items = batch
            .into_iter()
            .map(|consumed| {
                (
                    consumed.partition,
                    consumed.offset,
                    ShuffleMessage::Transfer {
                        transfer: Box::new(consumed.transfer),
                        offset: consumed.offset,
                    },
                )
            })
            .collect();
        let stats = self
            .dispatch_to_workers(items, &self.merge.transfer_tracker)
            .await;
        counter!(COHORT_STREAM_TRANSFERS_SKIPPED_NOT_OWNED).increment(stats.not_owned_skipped);
    }

    /// Route a consumed `cohort_cascade_events` batch to per-partition workers, ceiling marked on the
    /// cascade tracker. Spawns workers (like merges/transfers) because a dropped cascade silently
    /// fails to propagate a referrer flip.
    pub async fn dispatch_cascade(&self, batch: Vec<ConsumedCascade>) {
        if batch.is_empty() {
            return;
        }
        let items = batch
            .into_iter()
            .map(|consumed| {
                (
                    consumed.partition,
                    consumed.offset,
                    ShuffleMessage::Cascade {
                        message: Box::new(consumed.message),
                        offset: consumed.offset,
                    },
                )
            })
            .collect();
        let stats = self
            .dispatch_to_workers(items, &self.merge.cascade_tracker)
            .await;
        counter!(COHORT_STREAM_CASCADES_SKIPPED_NOT_OWNED).increment(stats.not_owned_skipped);
    }

    /// Shared skeleton: draining gate → owned gate → ensure_worker → dispatch ceiling → route.
    /// Route errors are counted here; per-topic skip counters come from the returned stats.
    async fn dispatch_to_workers(
        &self,
        items: Vec<(i32, i64, ShuffleMessage)>,
        tracker: &OffsetTracker,
    ) -> DispatchStats {
        let mut stats = DispatchStats::default();
        if self.draining.load(Ordering::SeqCst) {
            stats.not_owned_skipped = items.len() as u64;
            debug!(
                dropped = items.len(),
                "dispatch after shutdown began; dropping batch for replay"
            );
            return stats;
        }

        let mut messages: Vec<(i32, ShuffleMessage)> = Vec::with_capacity(items.len());
        for (partition, offset, message) in items {
            if !self.owned.contains(&partition) {
                stats.not_owned_skipped += 1;
                continue;
            }
            self.ensure_worker(partition);
            // Next-offset-to-consume convention.
            tracker.mark_dispatched(partition, offset + 1);
            messages.push((partition, message));
        }
        stats.dispatched = messages.len() as u64;

        let errors = self.router.route_batch(messages).await;
        if !errors.is_empty() {
            counter!(COHORT_STREAM_ROUTE_ERRORS).increment(errors.len() as u64);
        }
        stats
    }

    /// Spawn a worker the first time an owned partition delivers; no-op if the worker exists or the
    /// partition is unowned. The ownership check and insert are atomic under the DashMap shard guard.
    fn ensure_worker(&self, partition: i32) {
        match self.workers.entry(partition) {
            Entry::Occupied(_) => {}
            Entry::Vacant(slot) => {
                // Nothing in this arm may `.await` — the DashMap shard guard is held.
                if !self.owned.contains(&partition) {
                    return;
                }
                if self.draining.load(Ordering::SeqCst) {
                    return;
                }
                match self.router.add_partition(partition) {
                    Some(receiver) => {
                        let worker = Stage1Worker::spawn(
                            partition as u16,
                            receiver,
                            self.store.clone(),
                            self.catalog.clone(),
                            self.sink.clone(),
                            self.tracker.clone(),
                            self.merge.clone(),
                        );
                        slot.insert(worker);
                        counter!(COHORT_STREAM_WORKERS_SPAWNED).increment(1);
                        info!(
                            partition,
                            "spawned stage 1 worker for newly-delivered partition"
                        );
                    }
                    None if self.router.is_closed() => {
                        debug!(
                            partition,
                            "router closed by shutdown; skipping worker spawn"
                        )
                    }
                    None => warn!(
                        partition,
                        "router holds a live channel but no worker is registered; skipping spawn",
                    ),
                }
            }
        }
    }

    pub fn owns(&self, partition: i32) -> bool {
        self.owned.contains(&partition)
    }

    /// Snapshot of the partitions currently owned by this consumer.
    pub fn owned_partitions(&self) -> Vec<i32> {
        self.owned.iter().map(|entry| *entry).collect()
    }

    /// The merge-protocol deps shared with every worker.
    pub(crate) fn merge_deps(&self) -> &MergeWorkerDeps {
        &self.merge
    }

    /// Route a [`ShuffleMessage::Sweep`] to every owned partition's worker. Routes through the
    /// router directly (no worker spawn) so a revoked partition is never resurrected.
    pub async fn route_sweep(&self, due_before_ms: i64) {
        self.route_to_owned(|| ShuffleMessage::Sweep { due_before_ms })
            .await;
    }

    /// Route a [`ShuffleMessage::RedrivePendingTransfers`] tick to every owned partition's worker,
    /// so each re-produces any `cf_pending_transfers` entries stranded by inline-retry exhaustion.
    /// Same no-spawn posture as [`route_sweep`](Self::route_sweep).
    pub async fn route_redrive(&self) {
        self.route_to_owned(|| ShuffleMessage::RedrivePendingTransfers)
            .await;
    }

    /// Route a [`ShuffleMessage::MergeCfGc`] tick to every owned partition's worker, so each
    /// garbage-collects expired merge markers/tombstones. The cutoffs are computed by the sweeper and
    /// passed through verbatim, keeping the worker clock-free. Same no-spawn posture as
    /// [`route_sweep`](Self::route_sweep) — a GC tick must never resurrect a revoked partition.
    pub async fn route_merge_gc(&self, marker_cutoff_ms: i64, tombstone_cutoff_ms: i64) {
        self.route_to_owned(|| ShuffleMessage::MergeCfGc {
            marker_cutoff_ms,
            tombstone_cutoff_ms,
        })
        .await;
    }

    /// Shared skeleton for time-driven ticks: draining gate → owned snapshot → route (no spawn).
    async fn route_to_owned(&self, make_message: impl Fn() -> ShuffleMessage) {
        if self.draining.load(Ordering::SeqCst) {
            return;
        }
        let messages: Vec<(i32, ShuffleMessage)> = self
            .owned_partitions()
            .into_iter()
            .map(|partition| (partition, make_message()))
            .collect();
        if messages.is_empty() {
            return;
        }
        let errors = self.router.route_batch(messages).await;
        if !errors.is_empty() {
            counter!(COHORT_STREAM_ROUTE_ERRORS).increment(errors.len() as u64);
        }
    }

    /// Record a newly-assigned partition. The worker spawns lazily on the first message.
    pub fn assign_partition(&self, partition: i32) {
        self.owned.insert(partition);
        counter!(PARTITIONS_ASSIGNED_TOTAL).increment(1);
    }

    /// Synchronous half of a revoke: mark the partition un-owned. The worker channel is left intact
    /// so a rapid revoke-then-reassign preserves it; teardown is decided in the async drain.
    pub fn revoke_partition_sync(&self, partition: i32) {
        self.owned.remove(&partition);
        counter!(PARTITIONS_REVOKED_TOTAL).increment(1);
    }

    /// Asynchronous half of a revoke: reclaim the partition unless a reassign re-acquired it.
    /// Re-checks ownership at entry and after the worker join to handle rapid revoke-then-assign.
    pub async fn revoke_partition_drain(&self, partition: i32) {
        if self.owned.contains(&partition) {
            counter!(REBALANCE_CLEANUP_SKIPPED_TOTAL, "phase" => "entry").increment(1);
            debug!(
                partition,
                "skipping revoke cleanup: partition re-assigned before cleanup ran"
            );
            return;
        }

        self.router.remove_partition(partition);
        if let Some((_, worker)) = self.workers.remove(&partition) {
            let started = Instant::now();
            if let Err(err) = worker.join().await {
                warn!(partition, error = %err, "stage 1 worker panicked during revoke drain");
            }
            histogram!(REVOKE_DRAIN_DURATION_SECONDS).record(started.elapsed().as_secs_f64());
        }

        // Re-acquired during the join — skip cleanup.
        if self.owned.contains(&partition) {
            counter!(REBALANCE_CLEANUP_SKIPPED_TOTAL, "phase" => "post_join").increment(1);
            debug!(
                partition,
                "skipping revoke cleanup post-join: partition re-acquired during the worker drain"
            );
            return;
        }

        // Drop offset entries for all co-partitioned trackers.
        self.tracker.forget_partition(partition);
        self.merge.merge_tracker.forget_partition(partition);
        self.merge.transfer_tracker.forget_partition(partition);
        self.merge.cascade_tracker.forget_partition(partition);

        // Reset the per-partition gauges so they don't linger after the partition is wiped. The
        // held-offset gauges in particular are alerted on a sustained non-zero level — without this
        // reset, a hold that cleared on revoke would keep the alert firing for the stale label.
        gauge!(MERGE_PENDING_TRANSFERS_GAUGE, "partition" => partition.to_string()).set(0.0);
        gauge!(MERGE_HELD_OFFSET_GAUGE, "partition" => partition.to_string()).set(0.0);
        gauge!(CASCADE_HELD_OFFSET_GAUGE, "partition" => partition.to_string()).set(0.0);

        // Delete the on-disk state slice for this partition.
        let Some(partition_id) = partition_to_store_id(partition) else {
            warn!(
                partition,
                "revoked partition out of u16 range; skipping state delete"
            );
            return;
        };
        match self.store.delete_partition(partition_id) {
            Ok(()) => counter!(PARTITION_STATE_DELETED_TOTAL).increment(1),
            Err(err) => {
                warn!(partition, error = %err, "failed to delete revoked partition state")
            }
        }
    }

    fn tracker(&self) -> &OffsetTracker {
        self.tracker.as_ref()
    }

    /// Processed offsets restricted to still-owned partitions.
    fn owned_committable_offsets(&self) -> HashMap<i32, i64> {
        self.tracker
            .committable_offsets()
            .into_iter()
            .filter(|(partition, _)| self.owned.contains(partition))
            .collect()
    }

    /// Stop feeding workers and drain them. Sets `draining`, closes the router (terminally), joins
    /// all workers, and returns the tracker for the caller's final sync commit.
    async fn shutdown(&self) -> Arc<OffsetTracker> {
        self.draining.store(true, Ordering::SeqCst);
        self.router.clear();
        let partitions: Vec<i32> = self.workers.iter().map(|entry| *entry.key()).collect();
        for partition in partitions {
            if let Some((_, worker)) = self.workers.remove(&partition) {
                if let Err(err) = worker.join().await {
                    warn!(partition, error = %err, "stage 1 worker panicked during shutdown drain");
                }
            }
        }
        self.tracker.clone()
    }
}

#[derive(Debug, Default)]
struct DispatchStats {
    dispatched: u64,
    not_owned_skipped: u64,
}

/// Map a Kafka partition (`i32`) to the store's `u16` partition id, returning `None` for
/// out-of-range values.
fn partition_to_store_id(partition: i32) -> Option<u16> {
    u16::try_from(partition).ok()
}

/// The `cohort_stream_events` group consumer: consume, route, commit.
///
/// Uses a raw `StreamConsumer` with manual commit because the per-partition [`OffsetTracker`]
/// commits a `TopicPartitionList` the `common-kafka` wrapper can't express.
pub struct CohortStreamEventsConsumer {
    consumer: StreamConsumer<CohortConsumerContext>,
    topic: String,
    dispatcher: Arc<EventDispatcher>,
    handle: Handle,
    recv_batch_size: usize,
    recv_batch_timeout: Duration,
    offset_commit_interval: Duration,
    #[allow(dead_code)]
    consumer_command_rx: ConsumerCommandReceiver,
}

impl CohortStreamEventsConsumer {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        consumer: StreamConsumer<CohortConsumerContext>,
        topic: String,
        dispatcher: Arc<EventDispatcher>,
        handle: Handle,
        recv_batch_size: usize,
        recv_batch_timeout: Duration,
        offset_commit_interval: Duration,
        consumer_command_rx: ConsumerCommandReceiver,
    ) -> Self {
        Self {
            consumer,
            topic,
            dispatcher,
            handle,
            recv_batch_size,
            recv_batch_timeout,
            offset_commit_interval,
            consumer_command_rx,
        }
    }

    /// Run until the lifecycle handle signals shutdown. The commit is deadline-driven (not a
    /// `select!` arm) to avoid cancelling an in-flight `consume_batch` and dropping buffered events.
    pub async fn process(self) {
        let _guard = self.handle.process_scope();
        info!(topic = %self.topic, "cohort_stream_events consume loop starting");

        let mut commit_deadline = tokio::time::Instant::now() + self.offset_commit_interval;

        loop {
            tokio::select! {
                biased;
                _ = self.handle.shutdown_recv() => {
                    info!("shutdown signal received, stopping consume loop");
                    break;
                }
                outcome = self.consume_batch() => {
                    self.handle_outcome(outcome).await;
                    let now = tokio::time::Instant::now();
                    if now >= commit_deadline {
                        commit_offsets(
                            &self.consumer,
                            self.dispatcher.tracker(),
                            self.dispatcher.owned_committable_offsets(),
                            &self.topic,
                            CommitMode::Async,
                        );
                        commit_deadline = now + self.offset_commit_interval;
                    }
                }
            }
        }

        let tracker = self.dispatcher.shutdown().await;
        let offsets = self.dispatcher.owned_committable_offsets();
        commit_offsets(
            &self.consumer,
            &tracker,
            offsets,
            &self.topic,
            CommitMode::Sync,
        );
        info!(topic = %self.topic, "cohort_stream_events consume loop stopped");
    }

    /// Record metrics, dispatch the batch, and heartbeat. A transport error suppresses the
    /// heartbeat and backs off.
    async fn handle_outcome(&self, outcome: ConsumeOutcome) {
        histogram!(COHORT_STREAM_CONSUME_BATCH_SIZE).record(outcome.events.len() as f64);
        if !outcome.events.is_empty() {
            counter!(COHORT_STREAM_EVENTS_CONSUMED).increment(outcome.events.len() as u64);
        }
        if outcome.deserialize_errors > 0 {
            counter!(COHORT_STREAM_DESERIALIZE_ERRORS).increment(outcome.deserialize_errors);
        }
        if outcome.empty_payloads > 0 {
            counter!(COHORT_STREAM_EMPTY_PAYLOAD).increment(outcome.empty_payloads);
        }

        self.dispatcher.dispatch(outcome.events).await;

        if outcome.transport_error {
            tokio::time::sleep(RECV_ERROR_BACKOFF).await;
        } else {
            self.handle.report_healthy();
        }
    }

    /// Accumulate up to `recv_batch_size` deserialized events within `recv_batch_timeout`.
    async fn consume_batch(&self) -> ConsumeOutcome {
        let mut outcome = ConsumeOutcome {
            events: Vec::with_capacity(self.recv_batch_size),
            deserialize_errors: 0,
            empty_payloads: 0,
            transport_error: false,
        };

        tokio::select! {
            _ = tokio::time::sleep(self.recv_batch_timeout) => {}
            _ = async {
                while outcome.events.len() < self.recv_batch_size {
                    match self.consumer.recv().await {
                        Ok(message) => {
                            let partition = message.partition();
                            let offset = message.offset();
                            match message.payload() {
                                None => {
                                    outcome.empty_payloads += 1;
                                    debug!(
                                        partition, offset,
                                        "skipping cohort_stream_events message with empty payload",
                                    );
                                }
                                Some(payload) => match serde_json::from_slice::<CohortStreamEvent>(payload) {
                                    Ok(event) => outcome.events.push(ConsumedEvent { event, partition, offset }),
                                    Err(err) => {
                                        outcome.deserialize_errors += 1;
                                        debug!(
                                            partition, offset, error = %err,
                                            "skipping undeserializable cohort_stream_events message",
                                        );
                                    }
                                },
                            }
                        }
                        Err(err) => {
                            outcome.transport_error = true;
                            counter!(COHORT_STREAM_KAFKA_RECV_ERRORS).increment(1);
                            warn!(error = %err, "kafka recv error while consuming cohort_stream_events");
                            break;
                        }
                    }
                }
            } => {}
        }

        outcome
    }
}

struct ConsumeOutcome {
    events: Vec<ConsumedEvent>,
    deserialize_errors: u64,
    empty_payloads: u64,
    transport_error: bool,
}

/// Turn a `partition -> next-offset` snapshot into a `TopicPartitionList` for Kafka commit.
pub(crate) fn build_commit_tpl(topic: &str, offsets: &HashMap<i32, i64>) -> TopicPartitionList {
    let mut tpl = TopicPartitionList::new();
    for (&partition, &next_offset) in offsets {
        if let Err(err) = tpl.add_partition_offset(topic, partition, Offset::Offset(next_offset)) {
            warn!(topic, partition, next_offset, error = %err, "skipping partition in commit list");
        }
    }
    tpl
}

/// Commit the given processed offsets and record what was acked. Used by both the events and
/// follower consumers.
pub(crate) fn commit_offsets<C: ConsumerContext>(
    consumer: &StreamConsumer<C>,
    tracker: &OffsetTracker,
    offsets: HashMap<i32, i64>,
    topic: &str,
    mode: CommitMode,
) {
    if offsets.is_empty() {
        return;
    }
    let tpl = build_commit_tpl(topic, &offsets);
    match consumer.commit(&tpl, mode) {
        Ok(()) => {
            counter!(COHORT_STREAM_OFFSET_COMMITS).increment(1);
            for (&partition, &next_offset) in &offsets {
                tracker.mark_committed(partition, next_offset);
            }
        }
        Err(err) => {
            counter!(COHORT_STREAM_OFFSET_COMMIT_ERRORS).increment(1);
            warn!(topic, error = %err, "failed to commit consumer offsets");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono_tz::UTC;
    use serde_json::json;
    use tempfile::TempDir;
    use uuid::Uuid;

    use crate::filters::{CohortId, FilterCatalog, TeamFiltersBuilder, TeamId};
    use crate::merge::transfer::{
        MergeStateTransfer, PendingTransfer, PersonMergeEvent, Tombstone, TransferLeaf,
        MERGE_EVENT_SCHEMA_VERSION,
    };
    use crate::partitions::partitioner::{partition_of, COHORT_PARTITION_COUNT};
    use crate::producer::{
        CaptureSink, CaptureStreamEventSink, CaptureTransferSink, MembershipStatus,
    };
    use crate::stage1::state::AppliedOffsets;
    use crate::stage1::{Stage1State, StatefulRecord};
    use crate::store::{
        LeafStateKey, MergeAppliedKey, MergeDrainKey, PendingTransferKey, Stage1Key, StoreConfig,
        TombstoneKey,
    };
    use crate::workers::TransferRetryPolicy;

    const TEAM: i32 = 7;
    const BEHAVIORAL_HASH: [u8; 16] = *b"0123456789abcdef";
    const BASE_TS: &str = "2026-05-26 12:34:56.789000";

    #[test]
    fn deserializes_a_full_shuffler_envelope() {
        let value = json!({
            "team_id": 42,
            "person_id": "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "distinct_id": "user@example.com",
            "uuid": "0192f00d-f00d-f00d-f00d-f00df00df00d",
            "event": "$pageview",
            "timestamp": "2026-05-26 12:34:56.789000",
            "properties": "{\"$browser\":\"Chrome\"}",
            "person_properties": "{\"email\":\"u@p.com\"}",
            "elements_chain": "a:href=\"/x\"",
            "source_offset": 12345,
            "source_partition": 17,
        });

        let event: CohortStreamEvent = serde_json::from_value(value).unwrap();
        assert_eq!(event.team_id, 42);
        assert_eq!(event.person_id, "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee");
        assert_eq!(event.event, "$pageview");
        assert_eq!(
            event.properties.as_deref(),
            Some("{\"$browser\":\"Chrome\"}")
        );
        assert_eq!(event.source_offset, 12345);
        assert_eq!(event.source_partition, 17);
    }

    #[test]
    fn null_optional_payloads_deserialize_to_none() {
        let value = json!({
            "team_id": 1,
            "person_id": "p",
            "distinct_id": "d",
            "uuid": "u",
            "event": "$pageview",
            "timestamp": "2026-05-26 12:34:56.789000",
            "properties": null,
            "person_properties": null,
            "elements_chain": null,
            "source_offset": 0,
            "source_partition": 0,
        });

        let event: CohortStreamEvent = serde_json::from_value(value).unwrap();
        assert!(event.properties.is_none());
        assert!(event.person_properties.is_none());
        assert!(event.elements_chain.is_none());
    }

    #[test]
    fn shuffler_envelope_without_redirected_from_deserializes_to_none() {
        let value = json!({
            "team_id": 7,
            "person_id": "p",
            "distinct_id": "d",
            "uuid": "u",
            "event": "$pageview",
            "timestamp": BASE_TS,
            "properties": null,
            "person_properties": null,
            "elements_chain": null,
            "source_offset": 0,
            "source_partition": 0,
        });
        let event: CohortStreamEvent = serde_json::from_slice(&serde_json::to_vec(&value).unwrap())
            .expect("an envelope without redirected_from deserializes");
        assert!(event.redirected_from.is_none());
        assert_eq!(event.redirect_hops, 0);
    }

    #[test]
    fn redirected_from_round_trips_for_the_c2_re_produce() {
        let event = matching_event(Uuid::from_u128(1), 3, 9);
        let with_origin = CohortStreamEvent {
            redirected_from: Some("01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string()),
            ..event
        };
        let bytes = serde_json::to_vec(&with_origin).unwrap();
        let decoded: CohortStreamEvent = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(
            decoded.redirected_from.as_deref(),
            Some("01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        );
    }

    #[test]
    fn envelope_round_trips_through_wire_bytes() {
        let envelope = json!({
            "team_id": 7,
            "person_id": "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "distinct_id": "d",
            "uuid": "u",
            "event": "$pageview",
            "timestamp": BASE_TS,
            "properties": "{}",
            "person_properties": null,
            "elements_chain": null,
            "source_offset": 99,
            "source_partition": 3,
        });
        let bytes = serde_json::to_vec(&envelope).unwrap();

        let event: CohortStreamEvent = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(event.team_id, 7);
        assert_eq!(event.source_offset, 99);
        assert_eq!(event.source_partition, 3);
        assert!(event.person_properties.is_none());
    }

    #[test]
    fn build_commit_tpl_maps_each_partition_to_its_next_offset() {
        let mut offsets = HashMap::new();
        offsets.insert(3, 100);
        offsets.insert(7, 250);

        let tpl = build_commit_tpl("cohort_stream_events", &offsets);

        assert_eq!(tpl.count(), 2);
        assert_eq!(
            tpl.find_partition("cohort_stream_events", 3)
                .unwrap()
                .offset(),
            Offset::Offset(100),
        );
        assert_eq!(
            tpl.find_partition("cohort_stream_events", 7)
                .unwrap()
                .offset(),
            Offset::Offset(250),
        );
    }

    #[test]
    fn build_commit_tpl_for_no_offsets_is_empty() {
        let tpl = build_commit_tpl("cohort_stream_events", &HashMap::new());
        assert_eq!(tpl.count(), 0);
    }

    fn temp_store() -> (TempDir, CohortStore) {
        let dir = TempDir::new().unwrap();
        let config = StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        };
        let store = CohortStore::open(&config).expect("open store");
        (dir, store)
    }

    /// A team with one `performed_event` leaf on `$pageview` (7d).
    fn behavioral_catalog() -> Arc<CatalogHandle> {
        let behavioral_leaf = json!({
            "type": "behavioral",
            "value": "performed_event",
            "key": "$pageview",
            "time_value": 7,
            "time_interval": "day",
            "conditionHash": "0123456789abcdef",
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        });
        let cohort = json!({ "properties": { "type": "AND", "values": [behavioral_leaf] } });
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(TEAM), &cohort)
            .expect("add cohort");
        let filters = builder.freeze(UTC);
        Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([(
            TeamId(TEAM),
            filters,
        )])))
    }

    fn dispatcher_with(store: &CohortStore, catalog: Arc<CatalogHandle>) -> EventDispatcher {
        dispatcher_and_sink(store, catalog).0
    }

    /// Like [`dispatcher_with`] but also returns the capture sink for assertions.
    fn dispatcher_and_sink(
        store: &CohortStore,
        catalog: Arc<CatalogHandle>,
    ) -> (EventDispatcher, Arc<CaptureSink>) {
        let (dispatcher, sink, _, _) = dispatcher_full(
            store,
            catalog,
            CaptureSink::new(),
            CaptureTransferSink::new(),
        );
        (dispatcher, sink)
    }

    /// Full test wiring: dispatcher + membership capture + transfer capture + merge deps.
    fn dispatcher_full(
        store: &CohortStore,
        catalog: Arc<CatalogHandle>,
        sink: CaptureSink,
        transfer_sink: CaptureTransferSink,
    ) -> (
        EventDispatcher,
        Arc<CaptureSink>,
        Arc<CaptureTransferSink>,
        Arc<MergeWorkerDeps>,
    ) {
        let sink = Arc::new(sink);
        let transfer_sink = Arc::new(transfer_sink);
        let transfer_sink_dyn: Arc<dyn crate::producer::TransferSink> = transfer_sink.clone();
        let merge = Arc::new(MergeWorkerDeps {
            transfer_sink: transfer_sink_dyn,
            stream_event_sink: Arc::new(CaptureStreamEventSink::new()),
            merge_tracker: Arc::new(OffsetTracker::new()),
            transfer_tracker: Arc::new(OffsetTracker::new()),
            retry: TransferRetryPolicy::default(),
            gc_scan_limit: crate::workers::DEFAULT_MERGE_GC_SCAN_LIMIT,
            cascade_sink: Arc::new(crate::producer::CaptureCascadeSink::new()),
            cascade_tracker: Arc::new(OffsetTracker::new()),
            cascade: crate::workers::CascadeConfig::default(),
        });
        let dispatcher = EventDispatcher::new(
            PartitionRouter::new(64),
            Arc::new(OffsetTracker::new()),
            store.clone(),
            catalog,
            sink.clone(),
            merge.clone(),
        );
        (dispatcher, sink, transfer_sink, merge)
    }

    /// The behavioral leaf's `LeafStateKey`, read through the catalog.
    fn behavioral_lsk(catalog: &CatalogHandle) -> LeafStateKey {
        let snapshot = catalog.load();
        let team = snapshot.team(TeamId(TEAM)).expect("team in catalog");
        team.by_condition_to_lsk[&BEHAVIORAL_HASH][0]
    }

    fn person(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    fn matching_event(
        person: Uuid,
        source_partition: i32,
        source_offset: i64,
    ) -> CohortStreamEvent {
        CohortStreamEvent {
            team_id: TEAM,
            person_id: person.to_string(),
            distinct_id: "d".to_string(),
            uuid: Uuid::from_u128(0xE0_0000 + source_offset as u128).to_string(),
            event: "$pageview".to_string(),
            timestamp: BASE_TS.to_string(),
            properties: Some("{}".to_string()),
            person_properties: None,
            elements_chain: None,
            source_offset,
            source_partition,
            redirected_from: None,
            redirect_hops: 0,
        }
    }

    fn consumed(person: Uuid, topic_partition: i32, topic_offset: i64) -> ConsumedEvent {
        ConsumedEvent {
            event: matching_event(person, topic_partition, topic_offset),
            partition: topic_partition,
            offset: topic_offset,
        }
    }

    fn behavioral_state(
        store: &CohortStore,
        partition_id: u16,
        person: Uuid,
        lsk: LeafStateKey,
    ) -> Option<Stage1State> {
        let key = Stage1Key {
            partition_id,
            team_id: TEAM as u64,
            leaf_state_key: lsk,
            person_id: person,
        };
        store
            .get_stage1(&key)
            .unwrap()
            .map(|bytes| StatefulRecord::decode(&bytes).unwrap().state)
    }

    #[tokio::test]
    async fn dispatch_lazily_spawns_one_worker_per_partition_and_marks_next_offsets() {
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let lsk = behavioral_lsk(&catalog);
        let dispatcher = dispatcher_with(&store, catalog);

        dispatcher.assign_partition(0);
        dispatcher.assign_partition(1);

        let batch = vec![
            consumed(person(1), 0, 10),
            consumed(person(2), 0, 11),
            consumed(person(3), 1, 5),
        ];
        dispatcher.dispatch(batch).await;

        assert_eq!(dispatcher.workers.len(), 2);

        let tracker = dispatcher.shutdown().await;

        let committable = tracker.committable_offsets();
        assert_eq!(committable.get(&0), Some(&12));
        assert_eq!(committable.get(&1), Some(&6));

        assert!(
            matches!(
                behavioral_state(&store, 0, person(1), lsk),
                Some(Stage1State::BehavioralSingle {
                    has_match: true,
                    ..
                })
            ),
            "person 1 should have entered under partition 0",
        );
        assert!(
            matches!(
                behavioral_state(&store, 0, person(2), lsk),
                Some(Stage1State::BehavioralSingle {
                    has_match: true,
                    ..
                })
            ),
            "person 2 should have entered under partition 0",
        );
        assert!(
            matches!(
                behavioral_state(&store, 1, person(3), lsk),
                Some(Stage1State::BehavioralSingle {
                    has_match: true,
                    ..
                })
            ),
            "person 3 should have entered under partition 1",
        );
    }

    #[tokio::test]
    async fn dispatch_reuses_an_existing_worker_for_a_known_partition() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with(&store, behavioral_catalog());

        dispatcher.assign_partition(0);

        dispatcher.dispatch(vec![consumed(person(1), 0, 1)]).await;
        assert_eq!(dispatcher.workers.len(), 1);

        dispatcher.dispatch(vec![consumed(person(2), 0, 2)]).await;
        assert_eq!(dispatcher.workers.len(), 1);

        let tracker = dispatcher.shutdown().await;
        assert_eq!(tracker.committable_offsets().get(&0), Some(&3));
    }

    #[tokio::test]
    async fn dispatch_route_error_does_not_advance_the_offset() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with(&store, behavioral_catalog());

        dispatcher.assign_partition(9);
        dispatcher.ensure_worker(9);
        dispatcher.router.remove_partition(9);

        dispatcher.dispatch(vec![consumed(person(1), 9, 100)]).await;

        let tracker = dispatcher.shutdown().await;
        assert_eq!(
            tracker.committable_offsets().get(&9),
            None,
            "a route error leaves the offset unmarked for Kafka to replay",
        );
        assert_eq!(tracker.partition_count(), 1);
    }

    #[tokio::test]
    async fn dispatch_empty_batch_is_a_noop() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with(&store, behavioral_catalog());

        dispatcher.dispatch(vec![]).await;

        assert_eq!(dispatcher.workers.len(), 0);
        assert!(dispatcher.tracker().committable_offsets().is_empty());
        let _tracker = dispatcher.shutdown().await;
    }

    #[tokio::test]
    async fn revoke_partition_drains_produces_evicts_and_deletes_state() {
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let lsk = behavioral_lsk(&catalog);
        let (dispatcher, sink) = dispatcher_and_sink(&store, catalog);

        dispatcher.assign_partition(0);
        dispatcher.dispatch(vec![consumed(person(1), 0, 10)]).await;

        dispatcher.revoke_partition_sync(0);
        assert!(!dispatcher.owns(0));
        assert_eq!(dispatcher.router.partition_count(), 1);

        dispatcher.revoke_partition_drain(0).await;

        // Drained: person 1's enter was produced before the slice was reclaimed.
        let changes = sink.changes();
        assert_eq!(changes.len(), 1);
        assert_eq!(changes[0].status, MembershipStatus::Entered);
        assert_eq!(changes[0].person_id, person(1).to_string());

        assert_eq!(dispatcher.workers.len(), 0, "worker evicted");
        assert_eq!(dispatcher.router.partition_count(), 0, "sender removed");
        assert!(
            behavioral_state(&store, 0, person(1), lsk).is_none(),
            "the partition's state slice was deleted",
        );
    }

    #[tokio::test]
    async fn reassign_after_a_full_revoke_respawns_and_advances_offsets() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with(&store, behavioral_catalog());

        dispatcher.assign_partition(0);
        dispatcher.dispatch(vec![consumed(person(1), 0, 10)]).await;
        dispatcher.revoke_partition_sync(0);
        dispatcher.revoke_partition_drain(0).await;
        assert_eq!(dispatcher.workers.len(), 0);

        dispatcher.assign_partition(0);
        dispatcher.dispatch(vec![consumed(person(2), 0, 20)]).await;
        assert_eq!(
            dispatcher.workers.len(),
            1,
            "a reassigned partition respawns"
        );

        let tracker = dispatcher.shutdown().await;
        assert_eq!(tracker.committable_offsets().get(&0), Some(&21));
    }

    #[tokio::test]
    async fn rapid_revoke_then_assign_skips_cleanup_and_keeps_the_live_worker() {
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let lsk = behavioral_lsk(&catalog);
        let dispatcher = dispatcher_with(&store, catalog);

        dispatcher.assign_partition(0);
        dispatcher.dispatch(vec![consumed(person(1), 0, 10)]).await;

        dispatcher.revoke_partition_sync(0);
        dispatcher.assign_partition(0);
        dispatcher.revoke_partition_drain(0).await;

        assert!(dispatcher.owns(0), "re-owned partition stays owned");
        assert_eq!(dispatcher.workers.len(), 1, "worker preserved");
        assert_eq!(dispatcher.router.partition_count(), 1, "sender preserved");

        dispatcher.dispatch(vec![consumed(person(2), 0, 11)]).await;
        let tracker = dispatcher.shutdown().await;
        assert_eq!(tracker.committable_offsets().get(&0), Some(&12));
        assert!(
            behavioral_state(&store, 0, person(1), lsk).is_some(),
            "state survived the skipped cleanup",
        );
    }

    #[tokio::test]
    async fn revoke_then_shutdown_drain_each_worker_exactly_once() {
        let (_dir, store) = temp_store();
        let (dispatcher, sink) = dispatcher_and_sink(&store, behavioral_catalog());

        dispatcher.assign_partition(0);
        dispatcher.assign_partition(1);
        dispatcher
            .dispatch(vec![consumed(person(1), 0, 10), consumed(person(2), 1, 20)])
            .await;
        assert_eq!(dispatcher.workers.len(), 2);

        dispatcher.revoke_partition_sync(0);
        dispatcher.revoke_partition_drain(0).await;
        assert_eq!(dispatcher.workers.len(), 1);

        let tracker = dispatcher.shutdown().await;
        assert_eq!(dispatcher.workers.len(), 0);

        assert_eq!(
            sink.changes()
                .iter()
                .filter(|change| change.person_id == person(1).to_string())
                .count(),
            1,
        );
        assert_eq!(
            tracker.committable_offsets().get(&0),
            None,
            "the revoked partition's offset was forgotten on drain, not left to re-commit",
        );
        assert_eq!(
            tracker.committable_offsets().get(&1),
            Some(&21),
            "the survivor drained on shutdown",
        );
    }

    #[tokio::test]
    async fn revoke_partition_drain_forgets_the_offset_so_it_is_not_recommitted() {
        let (_dir, store) = temp_store();
        let (dispatcher, sink) = dispatcher_and_sink(&store, behavioral_catalog());

        dispatcher.assign_partition(0);
        dispatcher.assign_partition(1);
        dispatcher
            .dispatch(vec![consumed(person(1), 0, 10), consumed(person(2), 1, 20)])
            .await;

        dispatcher.revoke_partition_sync(0);
        dispatcher.revoke_partition_drain(0).await;

        assert_eq!(
            sink.changes()
                .iter()
                .filter(|change| change.person_id == person(1).to_string())
                .count(),
            1,
        );
        assert_eq!(dispatcher.tracker().committable_offsets().get(&0), None);
        assert!(!dispatcher.owned_committable_offsets().contains_key(&0));

        let tracker = dispatcher.shutdown().await;
        assert_eq!(tracker.committable_offsets().get(&1), Some(&21));
    }

    #[tokio::test]
    async fn owned_committable_offsets_excludes_unowned_partitions() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with(&store, behavioral_catalog());

        for (partition, next) in [(0, 11), (1, 21)] {
            dispatcher.assign_partition(partition);
            dispatcher.tracker().mark_dispatched(partition, next);
            let _ = dispatcher.tracker().mark_processed(partition, next);
        }
        assert_eq!(dispatcher.owned_committable_offsets().get(&0), Some(&11));

        dispatcher.revoke_partition_sync(0);

        assert_eq!(
            dispatcher.tracker().committable_offsets().get(&0),
            Some(&11),
            "the entry lingers in the tracker until the async drain forgets it",
        );
        assert!(!dispatcher.owned_committable_offsets().contains_key(&0));
        assert_eq!(dispatcher.owned_committable_offsets().get(&1), Some(&21));
    }

    #[tokio::test]
    async fn assign_and_revoke_track_ownership() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with(&store, behavioral_catalog());

        assert!(!dispatcher.owns(3));
        dispatcher.assign_partition(3);
        assert!(dispatcher.owns(3));
        dispatcher.revoke_partition_sync(3);
        assert!(!dispatcher.owns(3));
    }

    #[tokio::test]
    async fn owned_partitions_reflects_assign_and_revoke() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with(&store, behavioral_catalog());

        assert!(dispatcher.owned_partitions().is_empty());
        dispatcher.assign_partition(3);
        dispatcher.assign_partition(7);
        let mut owned = dispatcher.owned_partitions();
        owned.sort_unstable();
        assert_eq!(owned, vec![3, 7]);

        dispatcher.revoke_partition_sync(3);
        assert_eq!(dispatcher.owned_partitions(), vec![7]);
    }

    #[tokio::test]
    async fn route_sweep_delivers_the_cutoff_to_each_owned_worker() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with(&store, behavioral_catalog());

        dispatcher.assign_partition(0);
        dispatcher.assign_partition(1);
        let mut rx0 = dispatcher.router.add_partition(0).unwrap();
        let mut rx1 = dispatcher.router.add_partition(1).unwrap();

        let cutoff = 1_700_000_000_000;
        dispatcher.route_sweep(cutoff).await;

        for rx in [&mut rx0, &mut rx1] {
            let batch = rx.recv().await.expect("a sweep was routed");
            assert_eq!(batch.len(), 1);
            match &batch[0] {
                ShuffleMessage::Sweep { due_before_ms } => assert_eq!(*due_before_ms, cutoff),
                other => panic!("expected Sweep, got {other:?}"),
            }
        }
    }

    #[tokio::test]
    async fn route_sweep_is_benign_for_workerless_or_no_owned_partitions() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with(&store, behavioral_catalog());

        dispatcher.assign_partition(0);
        dispatcher.route_sweep(123).await;
        assert_eq!(dispatcher.workers.len(), 0, "a sweep never spawns a worker");
        assert_eq!(
            dispatcher.router.partition_count(),
            0,
            "no channel registered"
        );

        dispatcher.revoke_partition_sync(0);
        dispatcher.route_sweep(123).await;
    }

    #[tokio::test]
    async fn dispatch_after_full_revoke_does_not_resurrect_partition() {
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let lsk = behavioral_lsk(&catalog);
        let dispatcher = dispatcher_with(&store, catalog);

        dispatcher.assign_partition(0);
        dispatcher.dispatch(vec![consumed(person(1), 0, 10)]).await;
        dispatcher.revoke_partition_sync(0);
        dispatcher.revoke_partition_drain(0).await;

        assert_eq!(dispatcher.workers.len(), 0);
        assert_eq!(dispatcher.router.partition_count(), 0);
        assert!(behavioral_state(&store, 0, person(1), lsk).is_none());

        dispatcher.dispatch(vec![consumed(person(2), 0, 11)]).await;

        assert_eq!(
            dispatcher.workers.len(),
            0,
            "no worker respawned for the unowned partition",
        );
        assert_eq!(
            dispatcher.router.partition_count(),
            0,
            "no sender re-registered",
        );
        assert!(
            behavioral_state(&store, 0, person(2), lsk).is_none(),
            "no fresh slice written for the reclaimed partition",
        );
        assert_eq!(
            dispatcher.tracker().partition_count(),
            0,
            "the dropped event raised no dispatch ceiling",
        );
        assert!(!dispatcher.tracker().committable_offsets().contains_key(&0));
        assert!(!dispatcher.owned_committable_offsets().contains_key(&0));
    }

    #[tokio::test]
    async fn ensure_worker_does_not_spawn_for_an_unowned_partition() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with(&store, behavioral_catalog());

        dispatcher.ensure_worker(5);
        assert_eq!(
            dispatcher.workers.len(),
            0,
            "no worker for an unowned partition",
        );
        assert_eq!(
            dispatcher.router.partition_count(),
            0,
            "no channel registered",
        );

        dispatcher.assign_partition(5);
        dispatcher.ensure_worker(5);
        assert_eq!(dispatcher.workers.len(), 1);
        assert_eq!(dispatcher.router.partition_count(), 1);

        let _tracker = dispatcher.shutdown().await;
    }

    #[tokio::test]
    async fn dispatch_routes_owned_and_drops_revoked_without_raising_its_ceiling() {
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let lsk = behavioral_lsk(&catalog);
        let dispatcher = dispatcher_with(&store, catalog);

        dispatcher.assign_partition(0);
        dispatcher.assign_partition(1);
        dispatcher.revoke_partition_sync(1);
        dispatcher.revoke_partition_drain(1).await;

        dispatcher
            .dispatch(vec![consumed(person(1), 0, 10), consumed(person(2), 1, 20)])
            .await;

        assert_eq!(dispatcher.workers.len(), 1);
        assert!(dispatcher.workers.contains_key(&0));
        assert!(!dispatcher.workers.contains_key(&1));
        assert!(
            dispatcher.tracker().committed_offset(1).is_none(),
            "the dropped partition's dispatch ceiling was never raised",
        );

        let tracker = dispatcher.shutdown().await;
        assert_eq!(
            tracker.committable_offsets().get(&0),
            Some(&11),
            "the owned partition advanced",
        );
        assert!(behavioral_state(&store, 0, person(1), lsk).is_some());
        assert!(
            behavioral_state(&store, 1, person(2), lsk).is_none(),
            "the revoked partition wrote no state",
        );
    }

    #[tokio::test]
    async fn revoke_drain_of_a_never_spawned_partition_is_a_clean_noop() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with(&store, behavioral_catalog());

        dispatcher.assign_partition(3);
        dispatcher.revoke_partition_sync(3);
        dispatcher.revoke_partition_drain(3).await;

        assert_eq!(dispatcher.workers.len(), 0);
        assert_eq!(dispatcher.router.partition_count(), 0);
        assert!(!dispatcher.owns(3));
        assert_eq!(dispatcher.tracker().partition_count(), 0);
    }

    #[tokio::test]
    async fn shutdown_drains_a_late_dispatch_without_stranding_its_worker() {
        let (_dir, store) = temp_store();
        let (dispatcher, sink) = dispatcher_and_sink(&store, behavioral_catalog());

        dispatcher.assign_partition(0);
        dispatcher.dispatch(vec![consumed(person(1), 0, 10)]).await;
        assert_eq!(
            dispatcher.workers.len(),
            1,
            "the late dispatch spawned a worker",
        );

        let tracker = dispatcher.shutdown().await;

        assert_eq!(
            dispatcher.workers.len(),
            0,
            "shutdown joined the late worker rather than stranding it",
        );
        assert_eq!(
            tracker.committable_offsets().get(&0),
            Some(&11),
            "its produced tail's offset is committable, so a crash here would replay",
        );
        assert_eq!(sink.changes().len(), 1, "the worker flushed before exiting");
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn concurrent_revoke_and_dispatch_never_resurrects_an_unowned_partition() {
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let lsk = behavioral_lsk(&catalog);
        let dispatcher = Arc::new(dispatcher_with(&store, catalog));

        const P: i32 = 0;
        for round in 0..200u128 {
            dispatcher.assign_partition(P);

            let dispatch = {
                let dispatcher = dispatcher.clone();
                tokio::spawn(async move {
                    dispatcher
                        .dispatch(vec![consumed(person(round + 1), P, round as i64)])
                        .await;
                })
            };

            dispatcher.revoke_partition_sync(P);
            let drain = {
                let dispatcher = dispatcher.clone();
                tokio::spawn(async move {
                    dispatcher.revoke_partition_drain(P).await;
                })
            };

            dispatch.await.unwrap();
            drain.await.unwrap();

            assert!(!dispatcher.owns(P));
            assert!(
                !dispatcher.workers.contains_key(&P),
                "round {round}: a worker survived an unowned partition",
            );
            assert_eq!(
                dispatcher.router.partition_count(),
                0,
                "round {round}: a sender survived an unowned partition",
            );
            assert!(
                behavioral_state(&store, P as u16, person(round + 1), lsk).is_none(),
                "round {round}: a state slice survived an unowned partition",
            );
        }
    }

    const MERGED_AT: i64 = 1_716_800_000_000;

    /// Like [`behavioral_catalog`] plus a composable cohort `AND(behavioral 7d, behavioral 30d)`.
    fn composable_catalog() -> Arc<CatalogHandle> {
        let behavioral_leaf = |days: i64| {
            json!({
                "type": "behavioral",
                "value": "performed_event",
                "key": "$pageview",
                "time_value": days,
                "time_interval": "day",
                "conditionHash": "0123456789abcdef",
                "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
            })
        };
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(TEAM),
                &json!({ "properties": { "type": "AND", "values": [behavioral_leaf(7)] } }),
            )
            .expect("add single-leaf cohort");
        builder
            .add_cohort(
                CohortId(2),
                TeamId(TEAM),
                &json!({ "properties": { "type": "AND", "values": [behavioral_leaf(7), behavioral_leaf(30)] } }),
            )
            .expect("add composable cohort");
        Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([(
            TeamId(TEAM),
            builder.freeze(UTC),
        )])))
    }

    /// An empty catalog — no teams configured.
    fn absent_team_catalog() -> Arc<CatalogHandle> {
        Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([])))
    }

    /// First person at or after `start` hashing to `partition`.
    fn person_hashing_to(partition: u16, start: u128) -> Uuid {
        (start..start + 100_000)
            .map(Uuid::from_u128)
            .find(|p| partition_of(TeamId(TEAM), p, COHORT_PARTITION_COUNT) as u16 == partition)
            .expect("some person hashes to the partition")
    }

    /// First person at or after `start` hashing away from `partition`.
    fn person_hashing_away_from(partition: u16, start: u128) -> Uuid {
        (start..start + 100_000)
            .map(Uuid::from_u128)
            .find(|p| partition_of(TeamId(TEAM), p, COHORT_PARTITION_COUNT) as u16 != partition)
            .expect("some person hashes to another partition")
    }

    fn consumed_merge(p_old: Uuid, p_new: Uuid, partition: i32, offset: i64) -> ConsumedMerge {
        ConsumedMerge {
            event: PersonMergeEvent {
                team_id: TEAM,
                old_person_uuid: p_old,
                new_person_uuid: p_new,
                merged_at_ms: MERGED_AT,
                schema_version: MERGE_EVENT_SCHEMA_VERSION,
            },
            partition,
            offset,
        }
    }

    fn behavioral_match_record() -> StatefulRecord {
        StatefulRecord::new(
            Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: MERGED_AT - 1_000,
                earliest_eviction_at_ms: i64::MAX,
            },
            AppliedOffsets::default(),
        )
    }

    fn transfer_with(
        p_old: Uuid,
        p_new: Uuid,
        source: (i32, i64),
        leaves: Vec<TransferLeaf>,
    ) -> MergeStateTransfer {
        MergeStateTransfer {
            team_id: TEAM,
            old_person_uuid: p_old,
            new_person_uuid: p_new,
            merged_at_ms: MERGED_AT,
            source_partition: source.0,
            source_offset: source.1,
            leaves,
            forward_hops: 0,
        }
    }

    fn pending_key_of(partition: i32, p_old: Uuid) -> PendingTransferKey {
        PendingTransferKey {
            partition_id: partition as u16,
            team_id: TEAM as u64,
            old_person: p_old,
        }
    }

    #[tokio::test]
    async fn dispatch_merges_fast_path_composes_membership_and_marks_only_the_merge_tracker() {
        let (_dir, store) = temp_store();
        let (dispatcher, sink, transfer_sink, merge) = dispatcher_full(
            &store,
            composable_catalog(),
            CaptureSink::new(),
            CaptureTransferSink::new(),
        );

        let p_new = person(2);
        let partition = partition_of(TeamId(TEAM), &p_new, COHORT_PARTITION_COUNT) as i32;
        let p_old = person(1);
        dispatcher.assign_partition(partition);

        dispatcher
            .dispatch(vec![consumed(p_old, partition, 10)])
            .await;
        dispatcher
            .dispatch_merges(vec![consumed_merge(p_old, p_new, partition, 3)])
            .await;
        let tracker = dispatcher.shutdown().await;

        let mut p_new_changes: Vec<(i32, MembershipStatus)> = sink
            .changes()
            .iter()
            .filter(|change| change.person_id == p_new.to_string())
            .map(|change| (change.cohort_id, change.status))
            .collect();
        p_new_changes.sort_unstable_by_key(|(cohort_id, _)| *cohort_id);
        assert_eq!(
            p_new_changes,
            vec![
                (1, MembershipStatus::Entered),
                (2, MembershipStatus::Entered)
            ],
        );

        assert!(
            transfer_sink.transfers().is_empty(),
            "the fast path produces no transfer",
        );
        assert_eq!(
            merge.merge_tracker.committable_offsets().get(&partition),
            Some(&4),
            "the merge offset marks on the merge tracker",
        );
        assert_eq!(
            tracker.committable_offsets().get(&partition),
            Some(&11),
            "the events tracker only ever carries the event's own offset",
        );
        assert_eq!(merge.transfer_tracker.partition_count(), 0);
    }

    #[tokio::test]
    async fn dispatch_merges_slow_path_produces_the_transfer_clears_the_outbox_and_marks() {
        let (_dir, store) = temp_store();
        let (dispatcher, _sink, transfer_sink, merge) = dispatcher_full(
            &store,
            behavioral_catalog(),
            CaptureSink::new(),
            CaptureTransferSink::new(),
        );

        let p_old = person(1);
        let partition = partition_of(TeamId(TEAM), &p_old, COHORT_PARTITION_COUNT) as i32;
        let p_new = person_hashing_away_from(partition as u16, 100);
        dispatcher.assign_partition(partition);

        dispatcher
            .dispatch(vec![consumed(p_old, partition, 10)])
            .await;
        dispatcher
            .dispatch_merges(vec![consumed_merge(p_old, p_new, partition, 5)])
            .await;
        let _tracker = dispatcher.shutdown().await;

        let transfers = transfer_sink.transfers();
        assert_eq!(transfers.len(), 1);
        assert_eq!(transfers[0].new_person_uuid, p_new);
        assert_eq!(
            (transfers[0].source_partition, transfers[0].source_offset),
            (partition, 5),
            "the transfer carries the merge message's source coordinates",
        );
        assert!(
            !transfers[0].leaves.is_empty(),
            "P_old's state was packaged"
        );
        assert!(
            store
                .get_pending_transfer(&pending_key_of(partition, p_old))
                .unwrap()
                .is_none(),
            "the outbox was cleared after the ack",
        );
        assert_eq!(
            merge.merge_tracker.committable_offsets().get(&partition),
            Some(&6),
        );
    }

    #[tokio::test(start_paused = true)]
    async fn transfer_produce_retries_inline_on_the_paused_clock_and_succeeds() {
        let wall = std::time::Instant::now();
        let (_dir, store) = temp_store();
        let (dispatcher, _sink, transfer_sink, merge) = dispatcher_full(
            &store,
            behavioral_catalog(),
            CaptureSink::new(),
            CaptureTransferSink::failing_first(2),
        );

        let p_old = person(1);
        let partition = partition_of(TeamId(TEAM), &p_old, COHORT_PARTITION_COUNT) as i32;
        let p_new = person_hashing_away_from(partition as u16, 100);
        dispatcher.assign_partition(partition);

        dispatcher
            .dispatch(vec![consumed(p_old, partition, 0)])
            .await;
        dispatcher
            .dispatch_merges(vec![consumed_merge(p_old, p_new, partition, 7)])
            .await;
        let _tracker = dispatcher.shutdown().await;

        assert_eq!(
            transfer_sink.transfers().len(),
            1,
            "the third attempt acked"
        );
        assert!(store
            .get_pending_transfer(&pending_key_of(partition, p_old))
            .unwrap()
            .is_none(),);
        assert_eq!(
            merge.merge_tracker.committable_offsets().get(&partition),
            Some(&8),
        );
        assert!(
            wall.elapsed() < Duration::from_secs(2),
            "backoff ran on the paused clock, not the wall clock",
        );
    }

    #[tokio::test(start_paused = true)]
    async fn transfer_produce_exhaustion_leaves_the_outbox_pending_and_does_not_wedge() {
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let (dispatcher, _sink, transfer_sink, merge) = dispatcher_full(
            &store,
            catalog.clone(),
            CaptureSink::new(),
            CaptureTransferSink::failing_always(),
        );

        let p_old = person(1);
        let partition = partition_of(TeamId(TEAM), &p_old, COHORT_PARTITION_COUNT) as i32;
        let p_new = person_hashing_away_from(partition as u16, 100);
        dispatcher.assign_partition(partition);

        dispatcher
            .dispatch(vec![consumed(p_old, partition, 0)])
            .await;
        dispatcher
            .dispatch_merges(vec![consumed_merge(p_old, p_new, partition, 10)])
            .await;
        let _tracker = dispatcher.shutdown().await;

        assert!(transfer_sink.transfers().is_empty());
        let pending = PendingTransfer::decode(
            &store
                .get_pending_transfer(&pending_key_of(partition, p_old))
                .unwrap()
                .expect("the pending entry survives exhaustion"),
        )
        .unwrap();
        assert_eq!(pending.transfer.old_person_uuid, p_old);
        assert!(!pending.transfer.leaves.is_empty());
        assert_eq!(
            merge.merge_tracker.committable_offsets().get(&partition),
            None,
            "exhaustion skips the mark",
        );

        // A later merge on the same partition still processes (no wedge).
        let dispatcher_b = EventDispatcher::new(
            PartitionRouter::new(64),
            Arc::new(OffsetTracker::new()),
            store.clone(),
            catalog,
            Arc::new(CaptureSink::new()),
            merge.clone(),
        );
        let p_new_b = person_hashing_to(partition as u16, 200);
        let p_old_b = person(50);
        dispatcher_b.assign_partition(partition);
        dispatcher_b
            .dispatch_merges(vec![consumed_merge(p_old_b, p_new_b, partition, 11)])
            .await;
        let _tracker_b = dispatcher_b.shutdown().await;

        assert_eq!(
            merge.merge_tracker.committable_offsets().get(&partition),
            Some(&12),
            "the subsequent merge processed and marked",
        );
        assert!(
            store
                .get_pending_transfer(&pending_key_of(partition, p_old))
                .unwrap()
                .is_some(),
            "the failed merge's outbox entry is untouched",
        );
    }

    #[tokio::test(start_paused = true)]
    async fn redelivered_merge_re_produces_the_staged_outbox_entry_and_marks() {
        let (_dir, store) = temp_store();
        let budget = TransferRetryPolicy::default().max_retries as usize + 1;
        let (dispatcher, _sink, transfer_sink, merge) = dispatcher_full(
            &store,
            behavioral_catalog(),
            CaptureSink::new(),
            CaptureTransferSink::failing_first(budget),
        );

        let p_old = person(1);
        let partition = partition_of(TeamId(TEAM), &p_old, COHORT_PARTITION_COUNT) as i32;
        let p_new = person_hashing_away_from(partition as u16, 100);
        dispatcher.assign_partition(partition);
        dispatcher
            .dispatch(vec![consumed(p_old, partition, 0)])
            .await;

        dispatcher
            .dispatch_merges(vec![
                consumed_merge(p_old, p_new, partition, 10),
                consumed_merge(p_old, p_new, partition, 10),
            ])
            .await;
        let _tracker = dispatcher.shutdown().await;

        let transfers = transfer_sink.transfers();
        assert_eq!(transfers.len(), 1, "exactly one copy was ever acked");
        assert_eq!(
            (transfers[0].source_partition, transfers[0].source_offset),
            (partition, 10),
            "the re-produced copy carries the original source coordinates (the apply-side dedup key)",
        );
        assert!(
            store
                .get_pending_transfer(&pending_key_of(partition, p_old))
                .unwrap()
                .is_none(),
            "the outbox was cleared after the redelivered produce acked",
        );
        assert_eq!(
            merge.merge_tracker.committable_offsets().get(&partition),
            Some(&11),
        );
    }

    #[tokio::test(start_paused = true)]
    async fn route_redrive_recovers_an_inline_exhausted_transfer_within_the_tenure() {
        let budget = TransferRetryPolicy::default().max_retries as usize + 1;
        let (_dir, store) = temp_store();
        let (dispatcher, _sink, transfer_sink, merge) = dispatcher_full(
            &store,
            behavioral_catalog(),
            CaptureSink::new(),
            CaptureTransferSink::failing_first(budget),
        );

        let p_old = person(1);
        let partition = partition_of(TeamId(TEAM), &p_old, COHORT_PARTITION_COUNT) as i32;
        let p_new = person_hashing_away_from(partition as u16, 100);
        dispatcher.assign_partition(partition);

        dispatcher
            .dispatch(vec![consumed(p_old, partition, 0)])
            .await;
        dispatcher
            .dispatch_merges(vec![consumed_merge(p_old, p_new, partition, 10)])
            .await;
        dispatcher.route_redrive().await;
        let _tracker = dispatcher.shutdown().await;

        let transfers = transfer_sink.transfers();
        assert_eq!(transfers.len(), 1, "the redrive's single attempt acked");
        assert_eq!(
            (transfers[0].source_partition, transfers[0].source_offset),
            (partition, 10),
            "the redriven copy carries the original source coordinates",
        );
        assert!(
            store
                .get_pending_transfer(&pending_key_of(partition, p_old))
                .unwrap()
                .is_none(),
            "the redrive cleared the outbox after the ack",
        );
        assert_eq!(
            merge.merge_tracker.committable_offsets().get(&partition),
            Some(&11),
            "the stored merge-message coords marked past the exhausted merge",
        );
    }

    #[tokio::test]
    async fn route_redrive_duplicate_of_an_already_acked_transfer_applies_once() {
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let (dispatcher, _sink, transfer_sink, merge) = dispatcher_full(
            &store,
            catalog.clone(),
            CaptureSink::new(),
            CaptureTransferSink::new(),
        );

        let p_old = person(1);
        let partition = partition_of(TeamId(TEAM), &p_old, COHORT_PARTITION_COUNT) as i32;
        let p_new = person_hashing_away_from(partition as u16, 100);
        dispatcher.assign_partition(partition);
        dispatcher
            .dispatch(vec![consumed(p_old, partition, 0)])
            .await;
        dispatcher
            .dispatch_merges(vec![consumed_merge(p_old, p_new, partition, 5)])
            .await;
        let _tracker = dispatcher.shutdown().await;
        let copy_1 = {
            let transfers = transfer_sink.transfers();
            assert_eq!(transfers.len(), 1, "copy 1 acked inline");
            transfers.into_iter().next().unwrap()
        };

        // Simulate a crash between the produce ack and the outbox clear.
        store
            .write_batch(|batch| {
                batch.put_pending_transfer(
                    &pending_key_of(partition, p_old),
                    &PendingTransfer {
                        transfer: copy_1,
                        merge_msg_partition: partition,
                        merge_msg_offset: 5,
                    }
                    .encode(),
                )
            })
            .unwrap();

        // Fresh dispatcher: an event spawns the worker, then the tick re-produces copy 2.
        let dispatcher_b = EventDispatcher::new(
            PartitionRouter::new(64),
            Arc::new(OffsetTracker::new()),
            store.clone(),
            catalog.clone(),
            Arc::new(CaptureSink::new()),
            merge.clone(),
        );
        dispatcher_b.assign_partition(partition);
        dispatcher_b
            .dispatch(vec![consumed(person(2), partition, 1)])
            .await;
        dispatcher_b.route_redrive().await;
        let _tracker_b = dispatcher_b.shutdown().await;

        let copies = transfer_sink.transfers();
        assert_eq!(copies.len(), 2, "the redrive minted the duplicate copy");
        assert_eq!(copies[0], copies[1], "byte-identical source coordinates");
        assert!(store
            .get_pending_transfer(&pending_key_of(partition, p_old))
            .unwrap()
            .is_none());

        // Apply both copies: the second is AlreadyApplied.
        let target = partition_of(TeamId(TEAM), &p_new, COHORT_PARTITION_COUNT) as i32;
        let apply_sink = CaptureSink::new();
        let dispatcher_c = EventDispatcher::new(
            PartitionRouter::new(64),
            Arc::new(OffsetTracker::new()),
            store.clone(),
            catalog,
            Arc::new(apply_sink.clone()),
            merge.clone(),
        );
        dispatcher_c.assign_partition(target);
        dispatcher_c
            .dispatch_transfers(vec![
                ConsumedTransfer {
                    transfer: copies[0].clone(),
                    partition: target,
                    offset: 0,
                },
                ConsumedTransfer {
                    transfer: copies[1].clone(),
                    partition: target,
                    offset: 1,
                },
            ])
            .await;
        let _tracker_c = dispatcher_c.shutdown().await;

        let changes = apply_sink.changes();
        assert_eq!(changes.len(), 1, "exactly one membership change end to end");
        assert_eq!(changes[0].person_id, p_new.to_string());
        assert_eq!(changes[0].status, MembershipStatus::Entered);
        assert_eq!(
            merge.transfer_tracker.committable_offsets().get(&target),
            Some(&2),
            "both copies settled (applied + AlreadyApplied)",
        );
    }

    #[tokio::test]
    async fn route_merge_gc_is_benign_with_no_workers_or_unowned_partitions() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with(&store, behavioral_catalog());

        // Owned but workerless: routes the tick, never spawns a worker.
        dispatcher.assign_partition(0);
        dispatcher.route_merge_gc(1_000, 500).await;
        assert_eq!(dispatcher.workers.len(), 0, "GC never spawns a worker");
        assert_eq!(
            dispatcher.router.partition_count(),
            0,
            "no channel registered"
        );

        // Unowned: nothing to route.
        dispatcher.revoke_partition_sync(0);
        dispatcher.route_merge_gc(1_000, 500).await;
    }

    #[tokio::test]
    async fn route_merge_gc_round_trip_deletes_expired_markers_and_keeps_fresh_ones() {
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let dispatcher = dispatcher_with(&store, catalog);

        let partition = 3i32;
        let partition_id = partition as u16;
        dispatcher.assign_partition(partition);

        // An event spawns the worker so the routed GC tick has a live channel to land on.
        dispatcher
            .dispatch(vec![consumed(person(1), partition, 0)])
            .await;

        // Stage one expired and one fresh tombstone directly. Cutoffs: marker 10_000, tombstone 5_000.
        let marker_cutoff = 10_000;
        let tombstone_cutoff = 5_000;
        let expired = TombstoneKey {
            partition_id,
            team_id: TEAM as u64,
            person: person(10),
        };
        let fresh = TombstoneKey {
            partition_id,
            team_id: TEAM as u64,
            person: person(11),
        };
        store
            .write_batch(|batch| {
                batch.put_tombstone(
                    &expired,
                    &Tombstone {
                        new_person: person(99),
                        merged_at_ms: tombstone_cutoff - 1,
                    }
                    .encode(),
                );
                batch.put_tombstone(
                    &fresh,
                    &Tombstone {
                        new_person: person(99),
                        merged_at_ms: tombstone_cutoff + 1,
                    }
                    .encode(),
                );
            })
            .unwrap();

        dispatcher
            .route_merge_gc(marker_cutoff, tombstone_cutoff)
            .await;
        // Shutdown drains the worker, so the routed GC message is fully processed.
        let _tracker = dispatcher.shutdown().await;

        assert!(
            store.get_tombstone(&expired).unwrap().is_none(),
            "the expired tombstone was GC'd end to end",
        );
        assert!(
            store.get_tombstone(&fresh).unwrap().is_some(),
            "the in-retention tombstone survived",
        );
    }

    #[tokio::test]
    async fn mixed_batch_marks_each_tracker_and_membership_produce_failure_holds_only_events() {
        let (_dir, store) = temp_store();
        let (dispatcher, sink, _transfer_sink, merge) = dispatcher_full(
            &store,
            behavioral_catalog(),
            CaptureSink::failing_first(1),
            CaptureTransferSink::new(),
        );

        let p_new = person_hashing_to(3, 200);
        let partition = partition_of(TeamId(TEAM), &p_new, COHORT_PARTITION_COUNT) as i32;
        let p_old = person(60); // no state → a fast-path no-op drain
        dispatcher.assign_partition(partition);

        dispatcher
            .dispatch(vec![consumed(person(1), partition, 10)])
            .await;
        dispatcher
            .dispatch_merges(vec![consumed_merge(p_old, p_new, partition, 4)])
            .await;
        dispatcher
            .dispatch_transfers(vec![ConsumedTransfer {
                transfer: transfer_with(person(70), person(71), (9, 99), vec![]),
                partition,
                offset: 6,
            }])
            .await;
        let tracker = dispatcher.shutdown().await;

        assert!(
            sink.changes().is_empty(),
            "the failed flush recorded nothing"
        );
        assert_eq!(
            tracker.committable_offsets().get(&partition),
            None,
            "the membership produce failure holds the events offset",
        );
        assert_eq!(
            merge.merge_tracker.committable_offsets().get(&partition),
            Some(&5),
            "the merge offset marks independently",
        );
        assert_eq!(
            merge.transfer_tracker.committable_offsets().get(&partition),
            Some(&7),
            "the transfer offset marks independently",
        );
    }

    #[tokio::test]
    async fn unowned_merge_and_transfer_are_dropped_without_raising_any_ceiling() {
        let (_dir, store) = temp_store();
        let (dispatcher, _sink, transfer_sink, merge) = dispatcher_full(
            &store,
            behavioral_catalog(),
            CaptureSink::new(),
            CaptureTransferSink::new(),
        );

        dispatcher
            .dispatch_merges(vec![consumed_merge(person(1), person(2), 0, 5)])
            .await;
        dispatcher
            .dispatch_transfers(vec![ConsumedTransfer {
                transfer: transfer_with(person(1), person(2), (0, 5), vec![]),
                partition: 0,
                offset: 9,
            }])
            .await;

        assert_eq!(dispatcher.workers.len(), 0, "no worker spawned");
        assert_eq!(merge.merge_tracker.partition_count(), 0);
        assert_eq!(merge.transfer_tracker.partition_count(), 0);
        assert!(transfer_sink.transfers().is_empty());
        let _tracker = dispatcher.shutdown().await;
    }

    #[tokio::test]
    async fn draining_gate_rejects_all_dispatch_after_shutdown_without_hanging() {
        let (_dir, store) = temp_store();
        let (dispatcher, _sink, _transfer_sink, merge) = dispatcher_full(
            &store,
            behavioral_catalog(),
            CaptureSink::new(),
            CaptureTransferSink::new(),
        );

        dispatcher.assign_partition(0);
        dispatcher.dispatch(vec![consumed(person(1), 0, 10)]).await;
        let tracker = dispatcher.shutdown().await;
        assert_eq!(tracker.committable_offsets().get(&0), Some(&11));

        dispatcher.dispatch(vec![consumed(person(2), 0, 11)]).await;
        dispatcher
            .dispatch_merges(vec![consumed_merge(person(3), person(4), 0, 5)])
            .await;
        dispatcher.route_sweep(123).await;
        dispatcher.route_redrive().await;
        dispatcher.ensure_worker(0);

        assert_eq!(
            dispatcher.workers.len(),
            0,
            "no worker registered post-shutdown"
        );
        assert_eq!(
            dispatcher.router.partition_count(),
            0,
            "no sender registered"
        );
        assert_eq!(
            tracker.committable_offsets().get(&0),
            Some(&11),
            "the late event neither marked nor raised a ceiling",
        );
        assert_eq!(merge.merge_tracker.partition_count(), 0);
        let _tracker = dispatcher.shutdown().await;
    }

    #[tokio::test]
    async fn post_shutdown_registration_attempt_is_refused_by_the_closed_router() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with(&store, behavioral_catalog());

        dispatcher.assign_partition(0);
        dispatcher.dispatch(vec![consumed(person(1), 0, 10)]).await;
        let tracker = dispatcher.shutdown().await;

        assert!(
            dispatcher.router.add_partition(0).is_none(),
            "the closed router refuses a late registration",
        );
        assert_eq!(
            dispatcher.router.partition_count(),
            0,
            "no sender was inserted for the refused registration",
        );
        assert_eq!(dispatcher.workers.len(), 0, "no worker to strand");
        assert_eq!(
            tracker.committable_offsets().get(&0),
            Some(&11),
            "the pre-shutdown work still committed",
        );
        let _tracker = dispatcher.shutdown().await;
    }

    #[tokio::test]
    async fn absent_team_merge_still_drains_tombstone_and_marker_and_marks() {
        let (_dir, store) = temp_store();
        let (dispatcher, sink, transfer_sink, merge) = dispatcher_full(
            &store,
            absent_team_catalog(),
            CaptureSink::new(),
            CaptureTransferSink::new(),
        );

        let p_new = person(2);
        let partition = partition_of(TeamId(TEAM), &p_new, COHORT_PARTITION_COUNT) as i32;
        let p_old = person(1);
        let lsk = LeafStateKey([0xAB; 16]);
        let p_old_key = Stage1Key {
            partition_id: partition as u16,
            team_id: TEAM as u64,
            leaf_state_key: lsk,
            person_id: p_old,
        };
        store
            .write_batch(|batch| {
                batch.put_stage1(&p_old_key, &behavioral_match_record().encode());
                batch.merge_person_index(
                    &crate::store::PersonIndexKey {
                        partition_id: partition as u16,
                        team_id: TEAM as u64,
                        person_id: p_old,
                    },
                    crate::store::IndexOp::Append(lsk),
                );
            })
            .unwrap();

        dispatcher.assign_partition(partition);
        dispatcher
            .dispatch_merges(vec![consumed_merge(p_old, p_new, partition, 9)])
            .await;
        let _tracker = dispatcher.shutdown().await;

        assert!(
            store
                .get_tombstone(&TombstoneKey {
                    partition_id: partition as u16,
                    team_id: TEAM as u64,
                    person: p_old,
                })
                .unwrap()
                .is_some(),
            "the tombstone is load-bearing even with no cohorts",
        );
        assert!(store
            .get_merge_drain_applied(&MergeDrainKey {
                partition_id: partition as u16,
                team_id: TEAM as u64,
                old_person: p_old,
                merge_msg_partition: partition,
                merge_msg_offset: 9,
            })
            .unwrap()
            .is_some(),);
        assert!(
            store.get_stage1(&p_old_key).unwrap().is_none(),
            "P_old's state was deleted",
        );
        assert!(sink.changes().is_empty(), "drifted leaves emit nothing");
        assert!(transfer_sink.transfers().is_empty());
        assert_eq!(
            merge.merge_tracker.committable_offsets().get(&partition),
            Some(&10),
            "an absent team never holds the offset",
        );
    }

    #[tokio::test]
    async fn absent_team_transfer_applies_dropping_leaves_as_drift_and_marks() {
        let (_dir, store) = temp_store();
        let (dispatcher, sink, _transfer_sink, merge) = dispatcher_full(
            &store,
            absent_team_catalog(),
            CaptureSink::new(),
            CaptureTransferSink::new(),
        );

        let p_old = person(1);
        let p_new = person(2);
        let lsk = LeafStateKey([0xAB; 16]);
        dispatcher.assign_partition(0);
        dispatcher
            .dispatch_transfers(vec![ConsumedTransfer {
                transfer: transfer_with(
                    p_old,
                    p_new,
                    (3, 7),
                    vec![TransferLeaf::new(lsk, behavioral_match_record())],
                ),
                partition: 0,
                offset: 4,
            }])
            .await;
        let _tracker = dispatcher.shutdown().await;

        assert!(
            store
                .get_merge_applied(&MergeAppliedKey {
                    partition_id: 0,
                    team_id: TEAM as u64,
                    new_person: p_new,
                    source_partition: 3,
                    source_offset: 7,
                })
                .unwrap()
                .is_some(),
            "the apply marker still commits so the transfer is settled, not wedged",
        );
        assert!(
            store
                .get_stage1(&Stage1Key {
                    partition_id: 0,
                    team_id: TEAM as u64,
                    leaf_state_key: lsk,
                    person_id: p_new,
                })
                .unwrap()
                .is_none(),
            "the drifted leaf wrote no state",
        );
        assert!(sink.changes().is_empty());
        assert_eq!(
            merge.transfer_tracker.committable_offsets().get(&0),
            Some(&5),
        );
    }

    #[tokio::test]
    async fn empty_transfer_is_skipped_not_produced_or_staged_and_marks() {
        let (_dir, store) = temp_store();
        let (dispatcher, _sink, transfer_sink, merge) = dispatcher_full(
            &store,
            behavioral_catalog(),
            CaptureSink::new(),
            CaptureTransferSink::new(),
        );

        let p_old = person(1);
        let partition = partition_of(TeamId(TEAM), &p_old, COHORT_PARTITION_COUNT) as i32;
        let p_new = person_hashing_away_from(partition as u16, 100);
        dispatcher.assign_partition(partition);
        dispatcher
            .dispatch_merges(vec![consumed_merge(p_old, p_new, partition, 8)])
            .await;
        let _tracker = dispatcher.shutdown().await;

        assert!(transfer_sink.transfers().is_empty(), "nothing to ferry");
        assert!(
            store
                .get_pending_transfer(&pending_key_of(partition, p_old))
                .unwrap()
                .is_none(),
            "nothing staged, so nothing to clear",
        );
        assert!(
            store
                .get_tombstone(&TombstoneKey {
                    partition_id: partition as u16,
                    team_id: TEAM as u64,
                    person: p_old,
                })
                .unwrap()
                .is_some(),
            "the tombstone still commits",
        );
        assert_eq!(
            merge.merge_tracker.committable_offsets().get(&partition),
            Some(&9),
        );
    }

    #[tokio::test]
    async fn apply_marks_the_transfer_offset_even_when_the_membership_produce_fails() {
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let lsk = behavioral_lsk(&catalog);
        let (dispatcher, sink, _transfer_sink, merge) = dispatcher_full(
            &store,
            catalog,
            CaptureSink::failing_first(1),
            CaptureTransferSink::new(),
        );

        let p_new = person(2);
        dispatcher.assign_partition(0);
        dispatcher
            .dispatch_transfers(vec![ConsumedTransfer {
                transfer: transfer_with(
                    person(1),
                    p_new,
                    (3, 7),
                    vec![TransferLeaf::new(lsk, behavioral_match_record())],
                ),
                partition: 0,
                offset: 6,
            }])
            .await;
        let _tracker = dispatcher.shutdown().await;

        assert!(
            sink.changes().is_empty(),
            "the failed flush recorded nothing"
        );
        assert!(
            matches!(
                behavioral_state(&store, 0, p_new, lsk),
                Some(Stage1State::BehavioralSingle {
                    has_match: true,
                    ..
                })
            ),
            "the merged state committed",
        );
        assert_eq!(
            merge.transfer_tracker.committable_offsets().get(&0),
            Some(&7),
        );
    }

    #[tokio::test]
    async fn dispatch_transfers_applies_emits_membership_and_marks() {
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let lsk = behavioral_lsk(&catalog);
        let (dispatcher, sink, _transfer_sink, merge) = dispatcher_full(
            &store,
            catalog,
            CaptureSink::new(),
            CaptureTransferSink::new(),
        );

        let p_new = person(2);
        dispatcher.assign_partition(0);
        dispatcher
            .dispatch_transfers(vec![ConsumedTransfer {
                transfer: transfer_with(
                    person(1),
                    p_new,
                    (3, 7),
                    vec![TransferLeaf::new(lsk, behavioral_match_record())],
                ),
                partition: 0,
                offset: 6,
            }])
            .await;
        let _tracker = dispatcher.shutdown().await;

        let changes = sink.changes();
        assert_eq!(changes.len(), 1, "P_new entered the single-leaf cohort");
        assert_eq!(changes[0].person_id, p_new.to_string());
        assert_eq!(changes[0].cohort_id, 1);
        assert_eq!(changes[0].status, MembershipStatus::Entered);
        assert_eq!(
            merge.transfer_tracker.committable_offsets().get(&0),
            Some(&7),
        );
    }
}
