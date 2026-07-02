//! The `cohort_stream_events` wire envelope and the group consumer that drives it.
//!
//! [`CohortStreamEvent`] is the processor's own deserialize struct, deliberately decoupled from
//! `cohort-event-shuffler`'s producer type: the two services share only the JSON field names, so a
//! private copy means neither can break the other by adding a one-sided field.
//!
//! The Kafka-free routing core lives in [`EventDispatcher`] so it can be unit-tested with an
//! in-process router/store/catalog and no broker.

use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, OnceLock};
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
use crate::merge::transfer::PendingTransfer;
use crate::observability::metrics::{
    CASCADE_HELD_OFFSET_GAUGE, COHORT_STREAM_CASCADES_SKIPPED_NOT_OWNED,
    COHORT_STREAM_CONSUME_BATCH_SIZE, COHORT_STREAM_DESERIALIZE_ERRORS,
    COHORT_STREAM_EMPTY_PAYLOAD, COHORT_STREAM_EVENTS_CONSUMED, COHORT_STREAM_EVENTS_DISPATCHED,
    COHORT_STREAM_EVENTS_SKIPPED_NOT_OWNED, COHORT_STREAM_KAFKA_RECV_ERRORS,
    COHORT_STREAM_MERGES_SKIPPED_NOT_OWNED, COHORT_STREAM_OFFSET_COMMITS,
    COHORT_STREAM_OFFSET_COMMIT_ERRORS, COHORT_STREAM_ROUTE_ERRORS,
    COHORT_STREAM_TRANSFERS_SKIPPED_NOT_OWNED, COHORT_STREAM_WORKERS_SPAWNED,
    DURABLE_RESTORE_PARTITIONS_KEPT_TOTAL, DURABLE_RESTORE_PARTITIONS_WIPED_STALE_TOTAL,
    DURABLE_RESTORE_PENDING_TRANSFERS_RECOVERED_PARTITIONS_TOTAL, MERGE_HELD_OFFSET_GAUGE,
    MERGE_PENDING_TRANSFERS_GAUGE, PARTITIONS_ASSIGNED_TOTAL, PARTITIONS_PAUSED,
    PARTITIONS_REVOKED_TOTAL, PARTITION_STATE_DELETED_TOTAL, PENDING_HELD_EVENTS,
    REBALANCE_CLEANUP_SKIPPED_TOTAL, REVOKE_DRAIN_DURATION_SECONDS,
};
use crate::partitions::backpressure::Backpressure;
use crate::partitions::offset_tracker::OffsetTracker;
use crate::partitions::pause::{ConsumerPauser, PartitionPauser};
use crate::partitions::rebalance::{CohortConsumerContext, ConsumerCommandReceiver};
use crate::partitions::router::{PartitionRouter, SendOutcome};
use crate::partitions::shuffle_message::ShuffleMessage;
use crate::producer::MembershipSink;
use crate::store::durability::OffsetManifest;
use crate::store::CohortStore;
use crate::workers::{EventNameGating, MergeWorkerDeps, PersonMemoConfig, Stage1Worker};

/// Back-off after a Kafka transport error so a fast-failing `recv()` can't spin a consume loop.
pub(crate) const RECV_ERROR_BACKOFF: Duration = Duration::from_millis(500);

/// Timeout for the one-shot restore seek of the events topic. A local fetch-position reposition, so a
/// few seconds is ample; a timeout is a seek failure and retries (never resumes from the broker offset).
const RESTORE_SEEK_TIMEOUT: Duration = Duration::from_secs(10);

/// Page size for the eager boot redrive's paginated scan of `cf_pending_transfers`. The outbox only
/// ever holds transfers stranded by inline-retry exhaustion (rare), so this large page drains a
/// typical outbox in a single round; a larger backlog is drained across successive pages, bounding
/// peak memory per page.
const EAGER_BOOT_REDRIVE_PAGE_SIZE: usize = 100_000;

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
    /// Prevents post-shutdown worker registration that would hang the join. The structural guarantee
    /// is the router's terminal closed state, which refuses registration after `clear()`.
    draining: AtomicBool,
    /// When set, workers rebuild their `EvictionQueue` on spawn and boot/assign paths reclaim stale
    /// on-disk slices. Set once at startup before any worker spawns.
    durable_restore: AtomicBool,
    /// Settled boot assignment, recorded once. The assign path reclaims only partitions that move in
    /// after boot. `OnceLock` is `Sync`; the only race (get sees `None` before set) resolves to
    /// "skip", so a boot partition is never wiped.
    boot_assignment: OnceLock<HashSet<i32>>,
    /// Person-memo config for spawned workers, set once at startup. Unset → disabled.
    person_memo: OnceLock<PersonMemoConfig>,
    /// Event-name fan-out gating for spawned workers, set once at startup. Unset → disabled.
    event_name_gating: OnceLock<EventNameGating>,
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
            durable_restore: AtomicBool::new(false),
            boot_assignment: OnceLock::new(),
            person_memo: OnceLock::new(),
            event_name_gating: OnceLock::new(),
        }
    }

    /// Enable crash-restart durability. Must be called before any worker spawns.
    pub fn enable_durable_restore(&self) {
        self.durable_restore.store(true, Ordering::SeqCst);
    }

    pub fn durable_restore_enabled(&self) -> bool {
        self.durable_restore.load(Ordering::SeqCst)
    }

    /// Must be called before any worker spawns; later calls are ignored.
    pub fn set_person_memo_config(&self, config: PersonMemoConfig) {
        let _ = self.person_memo.set(config);
    }

    fn person_memo_config(&self) -> PersonMemoConfig {
        self.person_memo
            .get()
            .copied()
            .unwrap_or(PersonMemoConfig::DISABLED)
    }

    /// Must be called before any worker spawns; later calls are ignored.
    pub fn set_event_name_gating(&self, gating: EventNameGating) {
        let _ = self.event_name_gating.set(gating);
    }

    fn event_name_gating(&self) -> EventNameGating {
        self.event_name_gating
            .get()
            .copied()
            .unwrap_or(EventNameGating::Disabled)
    }

    pub(crate) fn store(&self) -> &CohortStore {
        &self.store
    }

    /// Blocking events dispatch, retained for tests; the consume loop uses
    /// [`dispatch_events_nonblocking`](Self::dispatch_events_nonblocking).
    ///
    /// The dispatch ceiling is raised before routing so a `RouteError` leaves the offset
    /// uncommittable and Kafka replays it. Events for unowned partitions are dropped before any
    /// ceiling bump.
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
                        event: Box::new(consumed.event),
                        cse_offset: consumed.offset,
                    },
                )
            })
            .collect();
        let stats = self.dispatch_to_workers(items, &self.tracker).await;
        counter!(COHORT_STREAM_EVENTS_SKIPPED_NOT_OWNED).increment(stats.not_owned_skipped);
        counter!(COHORT_STREAM_EVENTS_DISPATCHED).increment(stats.dispatched);
    }

    /// Non-blocking events dispatch: `try_send`s each non-held partition's sub-batch and raises the
    /// dispatch ceiling only for what lands. Events for a partition in `held` (already paused behind an
    /// older holdover) skip the send and are returned to queue behind it. Returns the un-dispatched
    /// events per partition for the caller to hold and pause.
    pub fn dispatch_events_nonblocking(
        &self,
        batch: Vec<ConsumedEvent>,
        held: &HashSet<i32>,
    ) -> HashMap<i32, Vec<ShuffleMessage>> {
        if self.draining.load(Ordering::SeqCst) {
            if !batch.is_empty() {
                counter!(COHORT_STREAM_EVENTS_SKIPPED_NOT_OWNED).increment(batch.len() as u64);
                debug!(
                    dropped = batch.len(),
                    "dispatch after shutdown began; dropping batch for replay"
                );
            }
            return HashMap::new();
        }

        let mut full: HashMap<i32, Vec<ShuffleMessage>> = HashMap::new();
        let mut fresh: Vec<(i32, ShuffleMessage)> = Vec::with_capacity(batch.len());
        let mut not_owned = 0u64;
        for consumed in batch {
            let partition = consumed.partition;
            if !self.owned.contains(&partition) {
                not_owned += 1;
                continue;
            }
            self.ensure_worker(partition);
            let message = ShuffleMessage::Event {
                event: Box::new(consumed.event),
                cse_offset: consumed.offset,
            };
            // A paused partition can still deliver a few already-fetched stragglers; queue them behind
            // the holdover rather than racing them ahead of older offsets.
            if held.contains(&partition) {
                full.entry(partition).or_default().push(message);
            } else {
                fresh.push((partition, message));
            }
        }
        counter!(COHORT_STREAM_EVENTS_SKIPPED_NOT_OWNED).increment(not_owned);

        self.route_fresh(fresh, &mut full);
        full
    }

    /// Retry-send held sub-batches, raising the ceiling for any that flush. Returns the partitions
    /// still full (retained holdover) to keep paused; a flushed or worker-gone one is absent, so the
    /// caller resumes it.
    pub fn redispatch_held(
        &self,
        held: Vec<(i32, Vec<ShuffleMessage>)>,
    ) -> HashMap<i32, Vec<ShuffleMessage>> {
        // Each partition's Vec stays contiguous, so the regrouped route keeps offset order.
        let mut messages: Vec<(i32, ShuffleMessage)> = Vec::new();
        for (partition, batch) in held {
            for message in batch {
                messages.push((partition, message));
            }
        }
        let mut still_full = HashMap::new();
        self.route_fresh(messages, &mut still_full);
        still_full
    }

    /// `try_send` events and fold the outcomes: raise the ceiling for what landed, collect a full
    /// channel's un-sent sub-batch into `full`, and count a missing/closed worker as a route error.
    fn route_fresh(
        &self,
        messages: Vec<(i32, ShuffleMessage)>,
        full: &mut HashMap<i32, Vec<ShuffleMessage>>,
    ) {
        let mut dispatched = 0u64;
        let mut route_errors = 0u64;
        for (partition, outcome) in self.router.try_route_batch(messages) {
            match outcome {
                SendOutcome::Sent { max_offset, count } => {
                    self.tracker.mark_dispatched(partition, max_offset + 1);
                    dispatched += count as u64;
                }
                SendOutcome::Full(returned) => {
                    full.entry(partition).or_default().extend(returned);
                }
                SendOutcome::NoWorker | SendOutcome::ChannelClosed => route_errors += 1,
            }
        }
        if dispatched > 0 {
            counter!(COHORT_STREAM_EVENTS_DISPATCHED).increment(dispatched);
        }
        if route_errors > 0 {
            counter!(COHORT_STREAM_ROUTE_ERRORS).increment(route_errors);
        }
    }

    /// Snapshot of the partitions currently owned, for the backpressure prune/reconcile pass.
    pub fn owned_set(&self) -> HashSet<i32> {
        self.owned.iter().map(|entry| *entry).collect()
    }

    /// Route a consumed `person_merge_events` batch to per-partition workers, ceiling on the merge
    /// tracker. Spawns workers (unlike sweep) because merges are durable external input.
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

    /// Route a consumed `cohort_merge_state_transfer` batch to per-partition workers, ceiling on the
    /// transfer tracker. Spawns workers because a dropped transfer is unrecoverable.
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

    /// Route a consumed `cohort_cascade_events` batch to per-partition workers, ceiling on the
    /// cascade tracker. Spawns workers because a dropped cascade silently fails to propagate a flip.
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
            tracker.mark_dispatched(partition, offset + 1); // next-to-consume convention
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
                // No `.await` in this arm — the DashMap shard guard is held.
                if !self.owned.contains(&partition) {
                    return;
                }
                if self.draining.load(Ordering::SeqCst) {
                    return;
                }
                // Durable restart only: wipe a post-boot move-in's stale on-disk slice (left by a
                // revoke-delete that failed before the partition returned to this pod) before the
                // worker rebuilds its eviction queue from it. Runs under the shard guard, so the wipe
                // strictly precedes the spawn. `reclaim_stale_slice` must never touch `self.workers` —
                // a `contains_key`/`entry` on the same shard while this write guard is held deadlocks.
                if self.durable_restore_enabled() {
                    self.reclaim_stale_slice(partition);
                }
                match self.router.add_partition(partition) {
                    Some(receiver) => {
                        let worker = Stage1Worker::spawn_with_memo(
                            partition as u16,
                            receiver,
                            self.store.clone(),
                            self.catalog.clone(),
                            self.sink.clone(),
                            self.tracker.clone(),
                            self.merge.clone(),
                            self.durable_restore_enabled(),
                            self.person_memo_config(),
                            self.event_name_gating(),
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

    pub(crate) fn merge_deps(&self) -> &MergeWorkerDeps {
        &self.merge
    }

    /// Route a sweep tick to each owned partition that has a live worker. Never spawns, so a revoked
    /// partition is not resurrected; a worker-less owned partition has no in-memory state to evict, so
    /// it is skipped rather than producing a `no_worker` drop.
    pub async fn route_sweep(&self, due_before_ms: i64) {
        self.route_to_owned(|| ShuffleMessage::Sweep { due_before_ms })
            .await;
    }

    /// Route a redrive tick to each owned partition that has a live worker, without spawning; each
    /// worker re-produces any `cf_pending_transfers` entries stranded by inline-retry exhaustion.
    pub async fn route_redrive(&self) {
        self.route_to_owned(|| ShuffleMessage::RedrivePendingTransfers)
            .await;
    }

    /// Route a merge-GC tick to each owned partition that has a live worker, without spawning. Cutoffs
    /// are computed by the sweeper and passed verbatim, keeping workers clock-free.
    pub async fn route_merge_gc(&self, marker_cutoff_ms: i64, tombstone_cutoff_ms: i64) {
        self.route_to_owned(|| ShuffleMessage::MergeCfGc {
            marker_cutoff_ms,
            tombstone_cutoff_ms,
        })
        .await;
    }

    /// Owned partitions that currently have a live worker channel — the only partitions a maintenance
    /// tick can reach. An owned partition that never received an event has no worker, so a tick to it
    /// is a guaranteed `no_worker` no-op (no in-memory state to evict, redrive, or GC); skipping it
    /// keeps the idle fan-out silent instead of dropping one message per worker-less partition.
    fn tickable_partitions(&self) -> Vec<i32> {
        self.owned_partitions()
            .into_iter()
            .filter(|partition| self.router.has_partition(*partition))
            .collect()
    }

    async fn route_to_owned(&self, make_message: impl Fn() -> ShuffleMessage) {
        if self.draining.load(Ordering::SeqCst) {
            return;
        }
        let messages: Vec<(i32, ShuffleMessage)> = self
            .tickable_partitions()
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

    pub fn assign_partition(&self, partition: i32) {
        self.owned.insert(partition);
        counter!(PARTITIONS_ASSIGNED_TOTAL).increment(1);
    }

    /// Synchronous half of a revoke: mark the partition un-owned. The worker channel is left intact
    /// for rapid revoke-then-reassign; teardown is decided in the async drain.
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

        if self.owned.contains(&partition) {
            // re-acquired during the join — skip cleanup
            counter!(REBALANCE_CLEANUP_SKIPPED_TOTAL, "phase" => "post_join").increment(1);
            debug!(
                partition,
                "skipping revoke cleanup post-join: partition re-acquired during the worker drain"
            );
            return;
        }

        self.tracker.forget_partition(partition);
        self.merge.merge_tracker.forget_partition(partition);
        self.merge.transfer_tracker.forget_partition(partition);
        self.merge.cascade_tracker.forget_partition(partition);

        // Reset per-partition gauges. Held-offset gauges in particular are alerted on a sustained
        // non-zero level — without this, a hold that cleared on revoke would keep the alert firing.
        gauge!(MERGE_PENDING_TRANSFERS_GAUGE, "partition" => partition.to_string()).set(0.0);
        gauge!(MERGE_HELD_OFFSET_GAUGE, "partition" => partition.to_string()).set(0.0);
        gauge!(CASCADE_HELD_OFFSET_GAUGE, "partition" => partition.to_string()).set(0.0);

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

    /// Delete a moving-in partition's stale on-disk slice so the worker cold-rebuilds from the
    /// committed offset. Called from [`Self::ensure_worker`] under the partition's shard guard, right
    /// before the worker spawns, so the wipe deterministically precedes the eviction-queue rebuild.
    ///
    /// Boot-snapshot partitions are kept (the boot sweep is the authority and reopen-live is intact),
    /// and pre-boot calls (snapshot not yet recorded) are kept too — only genuine post-boot move-ins
    /// are reclaimed. Must not touch `self.workers`: the caller holds a DashMap shard write guard for
    /// `partition`, so a `contains_key`/`entry` on the same shard would deadlock.
    fn reclaim_stale_slice(&self, partition: i32) {
        match self.boot_assignment.get() {
            // Pre-boot: the sweep is the authority — never wipe.
            None => return,
            Some(boot) if boot.contains(&partition) => return,
            Some(_) => {}
        }
        let Some(partition_id) = partition_to_store_id(partition) else {
            warn!(
                partition,
                "assigned partition out of u16 range; skipping stale-slice reclaim"
            );
            return;
        };
        match self.store.delete_partition(partition_id) {
            Ok(()) => counter!(DURABLE_RESTORE_PARTITIONS_WIPED_STALE_TOTAL).increment(1),
            Err(err) => warn!(
                partition,
                error = %err, "failed to reclaim stale assigned-partition state"
            ),
        }
    }

    /// Delete on-disk slices for partitions in `0..partition_count` not in `assignment`: they
    /// moved away while this pod was down. `assignment` must be the settled (non-empty) assignment
    /// — an empty set would delete all slices.
    pub(crate) fn reclaim_unassigned_partitions_on_boot(
        &self,
        assignment: &std::collections::HashSet<i32>,
        partition_count: usize,
    ) {
        let mut kept = 0u64;
        let mut wiped = 0u64;
        for partition in 0..partition_count as i32 {
            if assignment.contains(&partition) {
                kept += 1;
                continue;
            }
            if let Some(partition_id) = partition_to_store_id(partition) {
                match self.store.delete_partition(partition_id) {
                    Ok(()) => wiped += 1,
                    Err(err) => warn!(
                        partition,
                        error = %err, "failed to reclaim unassigned-partition state at boot"
                    ),
                }
            }
        }
        counter!(DURABLE_RESTORE_PARTITIONS_KEPT_TOTAL).increment(kept);
        counter!(DURABLE_RESTORE_PARTITIONS_WIPED_STALE_TOTAL).increment(wiped);
        info!(
            kept,
            wiped, partition_count, "durable restore: boot staleness sweep complete"
        );
    }

    /// Record the boot assignment snapshot, then sweep stale on-disk slices. Recording first makes
    /// the assign path defer to the boot decision and reclaim only post-boot move-ins.
    pub(crate) fn reconcile_boot_assignment(
        &self,
        assignment: &HashSet<i32>,
        partition_count: usize,
    ) {
        if self.boot_assignment.set(assignment.clone()).is_err() {
            debug!("boot assignment snapshot already recorded; keeping the first");
        }
        self.reclaim_unassigned_partitions_on_boot(assignment, partition_count);
    }

    /// Re-produce every staged `cf_pending_transfers` entry for the owned partitions at boot,
    /// without spawning workers. An idle partition never spawns a worker — and the periodic redrive
    /// routes through `route_to_owned`, which skips worker-less partitions, so it never fires for one
    /// either; this paginates the whole outbox directly and re-produces every entry regardless of
    /// backlog size.
    ///
    /// Produce + clear only — no `mark_processed`: a fresh tenure starts at `dispatched_offset == 0`
    /// so marking would clamp to 0 and trip `CappedAheadOfDispatch`. A per-entry produce failure
    /// leaves that entry for the periodic redrive. Must run after the boot staleness reconcile.
    pub async fn eager_redrive_pending_transfers_on_boot(&self, assignment: &HashSet<i32>) {
        for &partition in assignment {
            let Some(store_partition) = partition_to_store_id(partition) else {
                warn!(
                    partition,
                    "eager boot redrive: partition out of u16 range; skipping"
                );
                continue;
            };
            let recovered = self
                .eager_redrive_partition(partition, store_partition, EAGER_BOOT_REDRIVE_PAGE_SIZE)
                .await;
            if recovered > 0 {
                counter!(DURABLE_RESTORE_PENDING_TRANSFERS_RECOVERED_PARTITIONS_TOTAL).increment(1);
                info!(
                    partition,
                    recovered, "eager boot redrive: re-produced stranded pending transfers",
                );
            }
        }
    }

    /// Paginate one partition's `cf_pending_transfers` outbox, re-producing and clearing each entry;
    /// returns the count re-produced. `page_size` is a parameter so tests can force multi-page
    /// pagination without seeding a full [`EAGER_BOOT_REDRIVE_PAGE_SIZE`] page.
    async fn eager_redrive_partition(
        &self,
        partition: i32,
        store_partition: u16,
        page_size: usize,
    ) -> usize {
        let mut cursor: Option<Vec<u8>> = None;
        let mut recovered = 0usize;
        loop {
            let page = match self.store.scan_pending_transfers(
                store_partition,
                cursor.as_deref(),
                page_size,
            ) {
                Ok(page) => page,
                Err(error) => {
                    warn!(
                        partition,
                        error = %error,
                        "eager boot redrive: pending-transfer scan failed; the periodic redrive retries it",
                    );
                    break;
                }
            };
            if page.is_empty() {
                break;
            }
            let page_len = page.len();
            // Advance past the whole page before processing it: an entry left in place (decode or
            // produce failure) is never re-scanned this boot, so the loop always terminates and the
            // stranded entry defers to the periodic redrive.
            let next_cursor = page.last().map(|(key, _)| key.encode().to_vec());

            for (key, bytes) in page {
                let pending = match PendingTransfer::decode(&bytes) {
                    Ok(pending) => pending,
                    Err(error) => {
                        warn!(
                            partition,
                            team_id = key.team_id,
                            old_person = %key.old_person,
                            error = %error,
                            "eager boot redrive: undecodable pending transfer; leaving it in place",
                        );
                        continue;
                    }
                };
                let team_id = pending.transfer.team_id;
                let old_person = pending.transfer.old_person_uuid;
                let acks = self
                    .merge
                    .transfer_sink
                    .produce(vec![pending.transfer])
                    .await;
                if !acks.iter().all(Result::is_ok) {
                    warn!(
                        partition,
                        team_id,
                        old_person = %old_person,
                        "eager boot redrive: transfer produce failed; leaving the entry for the periodic redrive",
                    );
                    continue;
                }
                if let Err(error) = self.store.clear_pending_transfer(&key) {
                    warn!(
                        partition,
                        team_id,
                        old_person = %old_person,
                        error = %error,
                        "eager boot redrive: outbox clear failed after an acked produce; the periodic redrive re-produces it idempotently",
                    );
                }
                recovered += 1;
            }

            cursor = next_cursor;
            if page_len < page_size {
                break;
            }
        }
        recovered
    }

    fn tracker(&self) -> &OffsetTracker {
        self.tracker.as_ref()
    }

    fn owned_committable_offsets(&self) -> HashMap<i32, i64> {
        self.tracker
            .committable_offsets()
            .into_iter()
            .filter(|(partition, _)| self.owned.contains(partition))
            .collect()
    }

    /// Drain all workers and return the tracker for the caller's final sync commit.
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

fn partition_to_store_id(partition: i32) -> Option<u16> {
    u16::try_from(partition).ok()
}

/// Returns `true` once the same non-empty assignment is seen on two consecutive polls. An empty or
/// changing assignment is not yet settled; a cooperative-incremental assign re-baselines until stable.
fn boot_assignment_settled(assignment: &HashSet<i32>, prev: &mut Option<HashSet<i32>>) -> bool {
    if assignment.is_empty() {
        return false;
    }
    if prev.as_ref() != Some(assignment) {
        *prev = Some(assignment.clone());
        return false;
    }
    true
}

/// The `cohort_stream_events` group consumer: consume, route, commit.
///
/// Uses a raw `StreamConsumer` with manual commit because the per-partition `OffsetTracker`
/// commits a `TopicPartitionList` that the `common-kafka` wrapper can't express.
pub struct CohortStreamEventsConsumer {
    /// `Arc` so the commit task and consume loop share one consumer; rdkafka supports concurrent
    /// `recv` and `commit`.
    consumer: Arc<StreamConsumer<CohortConsumerContext>>,
    topic: String,
    dispatcher: Arc<EventDispatcher>,
    handle: Handle,
    /// Pauses/resumes events partitions to express downstream backpressure as lag.
    pauser: Arc<dyn PartitionPauser>,
    recv_batch_size: usize,
    recv_batch_timeout: Duration,
    offset_commit_interval: Duration,
    /// Partition count of `cohort_stream_events`, used by the boot staleness sweep.
    events_partitions: usize,
    #[allow(dead_code)]
    consumer_command_rx: ConsumerCommandReceiver,
    /// Offset manifest from a disaster restore. When set, the consume loop runs a one-shot seek of
    /// the events topic to the manifest positions once the boot assignment settles.
    restore_manifest: Option<OffsetManifest>,
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
        events_partitions: usize,
        consumer_command_rx: ConsumerCommandReceiver,
        restore_manifest: Option<OffsetManifest>,
    ) -> Self {
        let consumer = Arc::new(consumer);
        let pauser: Arc<dyn PartitionPauser> =
            Arc::new(ConsumerPauser::new(consumer.clone(), topic.clone()));
        Self {
            consumer,
            topic,
            dispatcher,
            handle,
            pauser,
            recv_batch_size,
            recv_batch_timeout,
            offset_commit_interval,
            events_partitions,
            consumer_command_rx,
            restore_manifest,
        }
    }

    /// Run until the lifecycle handle signals shutdown.
    ///
    /// Offset commit runs on its own interval task so a CPU-saturated consume loop or worker backlog
    /// can't block offset advancement; it shares the shutdown signal and is awaited before the final
    /// synchronous commit. Liveness is reported inline from the non-blocking backpressure cycle.
    pub async fn process(self) {
        let _guard = self.handle.process_scope();
        info!(topic = %self.topic, "cohort_stream_events consume loop starting");

        let commit_task = tokio::spawn(run_commit_loop(
            self.consumer.clone(),
            self.dispatcher.clone(),
            self.topic.clone(),
            self.offset_commit_interval,
            self.handle.clone(),
        ));

        // One-shot guards; each pre-marked done when its gate is off, keeping the non-durable path unchanged.
        let mut boot_sweep_done = !self.dispatcher.durable_restore_enabled();
        let mut eager_redrive_done = !self.dispatcher.durable_restore_enabled();
        let mut restore_seek_done = self.restore_manifest.is_none();
        let mut prev_assignment: Option<HashSet<i32>> = None;
        // Untouched until boot recovery completes below, so nothing pauses during boot.
        let mut backpressure = Backpressure::new();

        loop {
            tokio::select! {
                biased;
                _ = self.handle.shutdown_recv() => {
                    info!("shutdown signal received, stopping consume loop");
                    break;
                }
                outcome = self.consume_batch() => {
                    // Sweep before dispatching, so the reclaim never races a worker spawn.
                    if !boot_sweep_done {
                        boot_sweep_done = self.run_boot_staleness_sweep(&mut prev_assignment);
                    }
                    // Redrive after the boot sweep settles. Skip dispatching this batch so boot
                    // recovery completes before any fold work.
                    if !eager_redrive_done && boot_sweep_done {
                        let owned: HashSet<i32> =
                            self.dispatcher.owned_partitions().into_iter().collect();
                        self.dispatcher
                            .eager_redrive_pending_transfers_on_boot(&owned)
                            .await;
                        eager_redrive_done = true;
                        continue;
                    }
                    // Seek after the boot sweep settles. Skip dispatching the pre-seek batch so no
                    // ahead-of-seek event is folded first. Fail-stop: retry without dispatching on
                    // failure; never fold from the broker-stored offset.
                    if !restore_seek_done && boot_sweep_done {
                        restore_seek_done = self.run_restore_seek();
                        continue;
                    }
                    self.dispatch_with_backpressure(outcome, &mut backpressure).await;
                }
            }
        }

        // Await the commit task before the final synchronous commit so the two don't race.
        if let Err(err) = commit_task.await {
            warn!(error = %err, "offset-commit task did not exit cleanly");
        }

        let tracker = self.dispatcher.shutdown().await;
        let offsets = self.dispatcher.owned_committable_offsets();
        fsync_then_commit(
            self.dispatcher.store(),
            &self.consumer,
            &tracker,
            offsets,
            &self.topic,
            CommitMode::Sync,
        );
        info!(topic = %self.topic, "cohort_stream_events consume loop stopped");
    }

    /// Returns `true` once the boot snapshot is reconciled, `false` while the assignment is unsettled.
    fn run_boot_staleness_sweep(&self, prev: &mut Option<HashSet<i32>>) -> bool {
        let assignment = self.assigned_partitions();
        if !boot_assignment_settled(&assignment, prev) {
            return false;
        }
        self.dispatcher
            .reconcile_boot_assignment(&assignment, self.events_partitions);
        true
    }

    /// Seek the owned events partitions to the manifest's committed offsets. A no-op when
    /// `restore_manifest` is `None`. Returns `true` only once every targeted partition is sought;
    /// `false` on any failure so the caller retries without dispatching. A persistent failure stalls
    /// and surfaces as consumer lag, never silent event loss.
    fn run_restore_seek(&self) -> bool {
        let Some(manifest) = self.restore_manifest.as_ref() else {
            return true;
        };
        let owned = self.dispatcher.owned_partitions();
        let Some((tpl, sought)) = restore_seek_tpl(&self.topic, &owned, manifest) else {
            info!(
                topic = %self.topic,
                "restore seek: manifest carried no committed offset for any owned events partition; nothing to seek",
            );
            return true;
        };

        let result = match self.consumer.seek_partitions(tpl, RESTORE_SEEK_TIMEOUT) {
            Ok(result) => result,
            Err(err) => {
                warn!(
                    topic = %self.topic,
                    offsets = ?sought,
                    error = %err,
                    "restore seek failed; holding off dispatch and retrying (no progress until it succeeds)",
                );
                return false;
            }
        };

        let failed: Vec<i32> = result
            .elements_for_topic(&self.topic)
            .iter()
            .filter(|elem| elem.error().is_err())
            .map(|elem| elem.partition())
            .collect();
        if !failed.is_empty() {
            warn!(
                topic = %self.topic,
                failed_partitions = ?failed,
                offsets = ?sought,
                "restore seek failed for some partitions; holding off dispatch and retrying (no progress until it succeeds)",
            );
            return false;
        }

        info!(
            topic = %self.topic,
            partitions = sought.len(),
            offsets = ?sought,
            "restore seek: sought owned events partitions to their committed manifest offsets",
        );
        true
    }

    fn assigned_partitions(&self) -> HashSet<i32> {
        match self.consumer.assignment() {
            Ok(tpl) => tpl
                .elements_for_topic(&self.topic)
                .iter()
                .map(|elem| elem.partition())
                .collect(),
            Err(err) => {
                warn!(error = %err, "failed to read consumer assignment for the boot staleness sweep");
                HashSet::new()
            }
        }
    }

    /// One steady-state cycle: prune revoked holdover, retry-flush held partitions, dispatch the polled
    /// batch, reconcile pauses/resumes. Every step is non-blocking, so the heartbeat below fires each
    /// iteration regardless of downstream drain.
    async fn dispatch_with_backpressure(
        &self,
        outcome: ConsumeOutcome,
        backpressure: &mut Backpressure,
    ) {
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

        let owned = self.dispatcher.owned_set();
        backpressure.prune_revoked(&owned);
        // Retry-flush held partitions before dispatching new events, so a newer offset never leapfrogs
        // an older held one on the same partition.
        let still_full = self.dispatcher.redispatch_held(backpressure.take_held());
        backpressure.set_pending(still_full);
        let full = self
            .dispatcher
            .dispatch_events_nonblocking(outcome.events, &backpressure.held_partitions());
        backpressure.absorb(full);
        let deltas = backpressure.reconcile();
        self.pauser.pause(&deltas.pause);
        self.pauser.resume(&deltas.resume);
        gauge!(PARTITIONS_PAUSED).set(backpressure.paused_count() as f64);
        gauge!(PENDING_HELD_EVENTS).set(backpressure.held_event_count() as f64);

        if outcome.transport_error {
            tokio::time::sleep(RECV_ERROR_BACKOFF).await;
        } else {
            self.handle.report_healthy();
        }
    }

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

/// Build the seek list for a disaster restore: owned partitions with a committed offset in
/// `manifest`, at `Offset::Offset(next_offset)` (next-to-consume convention). Returns the TPL and
/// logged pairs, or `None` when no owned partition has a manifest offset.
fn restore_seek_tpl(
    topic: &str,
    owned: &[i32],
    manifest: &OffsetManifest,
) -> Option<(TopicPartitionList, Vec<(i32, i64)>)> {
    let mut tpl = TopicPartitionList::new();
    let mut sought: Vec<(i32, i64)> = Vec::new();
    for &partition in owned {
        let Some(next_offset) = manifest.offset_for(topic, partition) else {
            continue;
        };
        if let Err(err) = tpl.add_partition_offset(topic, partition, Offset::Offset(next_offset)) {
            warn!(topic, partition, next_offset, error = %err, "skipping partition in restore seek list");
            continue;
        }
        sought.push((partition, next_offset));
    }
    (tpl.count() > 0).then_some((tpl, sought))
}

pub(crate) fn build_commit_tpl(topic: &str, offsets: &HashMap<i32, i64>) -> TopicPartitionList {
    let mut tpl = TopicPartitionList::new();
    for (&partition, &next_offset) in offsets {
        if let Err(err) = tpl.add_partition_offset(topic, partition, Offset::Offset(next_offset)) {
            warn!(topic, partition, next_offset, error = %err, "skipping partition in commit list");
        }
    }
    tpl
}

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

/// fsync the store's WAL before committing offsets, upholding `committed <= durable`. Unconditional
/// so reopen-live is safe whenever the durability gate is flipped. A fsync error skips the commit.
pub(crate) fn fsync_then_commit<C: ConsumerContext>(
    store: &CohortStore,
    consumer: &StreamConsumer<C>,
    tracker: &OffsetTracker,
    offsets: HashMap<i32, i64>,
    topic: &str,
    mode: CommitMode,
) {
    if offsets.is_empty() {
        return;
    }
    if store.flush_wal_sync().is_err() {
        return; // store counted the error; skip commit so `committed` never outruns `durable`
    }
    commit_offsets(consumer, tracker, offsets, topic, mode);
}

/// Flushes the store's WAL and commits the owned committable offsets on a fixed interval, independent
/// of the consume loop so a stalled loop can't block offset advancement. Exits on shutdown.
async fn run_commit_loop(
    consumer: Arc<StreamConsumer<CohortConsumerContext>>,
    dispatcher: Arc<EventDispatcher>,
    topic: String,
    interval: Duration,
    handle: Handle,
) {
    let mut ticker = tokio::time::interval(interval);
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        tokio::select! {
            biased;
            _ = handle.shutdown_recv() => break,
            _ = ticker.tick() => {
                fsync_then_commit(
                    dispatcher.store(),
                    &consumer,
                    dispatcher.tracker(),
                    dispatcher.owned_committable_offsets(),
                    &topic,
                    CommitMode::Async,
                );
            }
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
    use crate::partitions::offset_tracker::MarkOutcome;
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

    fn manifest_for(topic: &str, committed: &[(i32, i64)]) -> OffsetManifest {
        let tracker = OffsetTracker::new();
        let owned: Vec<i32> = committed.iter().map(|(p, _)| *p).collect();
        for &(partition, next) in committed {
            tracker.mark_dispatched(partition, next);
            let _ = tracker.mark_processed(partition, next);
            tracker.mark_committed(partition, next);
        }
        OffsetManifest::capture(&owned, &[(topic, &tracker)])
    }

    #[test]
    fn restore_seek_tpl_targets_owned_partitions_with_a_manifest_offset() {
        let manifest = manifest_for("cohort_stream_events", &[(0, 100), (3, 250)]);
        let (tpl, sought) = restore_seek_tpl("cohort_stream_events", &[0, 3, 7], &manifest)
            .expect("a non-empty seek");
        assert_eq!(tpl.count(), 2);
        assert_eq!(
            tpl.find_partition("cohort_stream_events", 0)
                .unwrap()
                .offset(),
            Offset::Offset(100),
        );
        assert_eq!(
            tpl.find_partition("cohort_stream_events", 3)
                .unwrap()
                .offset(),
            Offset::Offset(250),
        );
        assert!(tpl.find_partition("cohort_stream_events", 7).is_none());
        let mut sought_sorted = sought;
        sought_sorted.sort_unstable();
        assert_eq!(sought_sorted, vec![(0, 100), (3, 250)]);
    }

    #[test]
    fn restore_seek_tpl_is_none_for_an_empty_manifest_topic() {
        let empty = manifest_for("cohort_stream_events", &[]);
        assert!(restore_seek_tpl("cohort_stream_events", &[0, 1, 2], &empty).is_none());
    }

    #[test]
    fn restore_seek_tpl_is_none_when_no_owned_partition_matches() {
        let manifest = manifest_for("cohort_stream_events", &[(0, 100), (3, 250)]);
        assert!(restore_seek_tpl("cohort_stream_events", &[5, 9], &manifest).is_none());
    }

    #[test]
    fn restore_seek_tpl_is_none_for_a_missing_topic() {
        let manifest = manifest_for("cohort_stream_events", &[(0, 100)]);
        assert!(restore_seek_tpl("person_merge_events", &[0], &manifest).is_none());
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
            stage2_orphan_gc_enabled: true,
            cascade_sink: Arc::new(crate::producer::CaptureCascadeSink::new()),
            cascade_tracker: Arc::new(OffsetTracker::new()),
            cascade: crate::workers::CascadeConfig::default(),
            partition_count: COHORT_PARTITION_COUNT,
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

    fn seed_slice(store: &CohortStore, partition: u16, lsk: LeafStateKey) {
        store
            .write_batch(|b| {
                b.put_stage1(
                    &Stage1Key {
                        partition_id: partition,
                        team_id: TEAM as u64,
                        leaf_state_key: lsk,
                        person_id: person(1),
                    },
                    b"state",
                )
            })
            .unwrap();
    }

    fn slice_present(store: &CohortStore, partition: u16, lsk: LeafStateKey) -> bool {
        store
            .get_stage1(&Stage1Key {
                partition_id: partition,
                team_id: TEAM as u64,
                leaf_state_key: lsk,
                person_id: person(1),
            })
            .unwrap()
            .is_some()
    }

    #[tokio::test]
    async fn reclaim_stale_slice_wipes_move_in_keeps_boot_partition() {
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let lsk = behavioral_lsk(&catalog);
        let dispatcher = dispatcher_with(&store, catalog);
        seed_slice(&store, 5, lsk);
        seed_slice(&store, 6, lsk);

        // Boot snapshot includes 6 (reopen-live) but not 5 (post-boot move-in); partition_count 5
        // keeps the boot sweep off both 5 and 6.
        dispatcher.reconcile_boot_assignment(&[6].into_iter().collect(), 5);

        dispatcher.reclaim_stale_slice(5);
        assert!(
            !slice_present(&store, 5, lsk),
            "a post-boot move-in has its stale slice wiped",
        );

        dispatcher.reclaim_stale_slice(6);
        assert!(
            slice_present(&store, 6, lsk),
            "a boot-snapshot partition keeps its slice (the boot sweep is the authority)",
        );
    }

    #[tokio::test]
    async fn ensure_worker_wipes_stale_move_in_slice_before_spawn() {
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let lsk = behavioral_lsk(&catalog);
        let dispatcher = dispatcher_with(&store, catalog);
        dispatcher.enable_durable_restore();

        seed_slice(&store, 5, lsk);
        // Boot excludes 5 (a post-boot move-in); partition_count 5 keeps the boot sweep off 5.
        dispatcher.reconcile_boot_assignment(&[6].into_iter().collect(), 5);
        dispatcher.assign_partition(5);

        dispatcher.ensure_worker(5);
        assert!(
            dispatcher.workers.contains_key(&5),
            "the moved-in partition spawned a worker",
        );
        assert!(
            !slice_present(&store, 5, lsk),
            "the stale slice was wiped before the worker read it (cold rebuild)",
        );

        // A second delivery finds the worker already live: the Entry::Occupied arm is a no-op, so a
        // freshly-written (current, not stale) slice is never re-wiped.
        seed_slice(&store, 5, lsk);
        dispatcher.ensure_worker(5);
        assert!(
            slice_present(&store, 5, lsk),
            "an existing worker keeps its current slice (ensure_worker does not re-reclaim)",
        );

        dispatcher.shutdown().await;
    }

    #[tokio::test]
    async fn ensure_worker_with_durable_restore_off_keeps_slice() {
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let lsk = behavioral_lsk(&catalog);
        let dispatcher = dispatcher_with(&store, catalog);
        // Durable restore left off: ensure_worker must never reclaim — wipe-on-start handles staleness.

        seed_slice(&store, 5, lsk);
        dispatcher.reconcile_boot_assignment(&[6].into_iter().collect(), 5);
        dispatcher.assign_partition(5);

        dispatcher.ensure_worker(5);
        assert!(dispatcher.workers.contains_key(&5), "the worker spawned");
        assert!(
            slice_present(&store, 5, lsk),
            "with durable restore off, ensure_worker leaves the on-disk slice untouched",
        );

        dispatcher.shutdown().await;
    }

    #[test]
    fn boot_assignment_settled_requires_a_stable_non_empty_assignment() {
        let mut prev: Option<HashSet<i32>> = None;

        assert!(!boot_assignment_settled(&HashSet::new(), &mut prev));
        assert_eq!(prev, None);

        let first: HashSet<i32> = [0].into_iter().collect();
        assert!(!boot_assignment_settled(&first, &mut prev));
        assert_eq!(prev.as_ref(), Some(&first));

        let second: HashSet<i32> = [0, 1].into_iter().collect();
        assert!(!boot_assignment_settled(&second, &mut prev));
        assert_eq!(prev.as_ref(), Some(&second));

        assert!(boot_assignment_settled(&second, &mut prev));
    }

    #[tokio::test]
    async fn reclaim_unassigned_partitions_on_boot_wipes_only_unassigned_slices() {
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let lsk = behavioral_lsk(&catalog);
        let dispatcher = dispatcher_with(&store, catalog);
        for partition in 0..3u16 {
            seed_slice(&store, partition, lsk);
        }

        let assignment: HashSet<i32> = [0, 2].into_iter().collect();
        dispatcher.reclaim_unassigned_partitions_on_boot(&assignment, 3);

        assert!(
            slice_present(&store, 0, lsk),
            "assigned 0 is kept (reopen-live)",
        );
        assert!(
            !slice_present(&store, 1, lsk),
            "unassigned 1 is wiped (stale slice from a previous tenure)",
        );
        assert!(
            slice_present(&store, 2, lsk),
            "assigned 2 is kept (reopen-live)",
        );
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

    /// A dispatcher whose router uses `buffer` channel slots and no real worker, so a pre-filled
    /// channel exercises the `try_send`-full path.
    fn dispatcher_with_buffer(
        store: &CohortStore,
        catalog: Arc<CatalogHandle>,
        buffer: usize,
    ) -> EventDispatcher {
        let sink: Arc<dyn MembershipSink> = Arc::new(CaptureSink::new());
        EventDispatcher::new(
            PartitionRouter::new(buffer),
            Arc::new(OffsetTracker::new()),
            store.clone(),
            catalog,
            sink,
            MergeWorkerDeps::capture(),
        )
    }

    fn held_offsets(messages: &[ShuffleMessage]) -> Vec<i64> {
        messages
            .iter()
            .filter_map(ShuffleMessage::event_offset)
            .collect()
    }

    #[tokio::test]
    async fn nonblocking_dispatch_holds_a_full_channel_and_advances_the_offset_only_after_flush() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with_buffer(&store, behavioral_catalog(), 1);
        dispatcher.assign_partition(0);
        // Hold the receiver so nothing drains; ensure_worker reuses the registered channel and spawns
        // no worker, leaving this rx the only consumer.
        let mut rx = dispatcher.router.add_partition(0).unwrap();
        let no_held = HashSet::new();

        // Batch A fills the one slot and raises the ceiling to 105.
        assert!(dispatcher
            .dispatch_events_nonblocking(vec![consumed(person(1), 0, 104)], &no_held)
            .is_empty());
        // Batch B finds the channel full: held verbatim, ceiling unchanged.
        let mut full =
            dispatcher.dispatch_events_nonblocking(vec![consumed(person(2), 0, 105)], &no_held);
        let held = full.remove(&0).expect("partition 0 was held");
        assert_eq!(held_offsets(&held), vec![105]);
        assert!(
            dispatcher.workers.is_empty(),
            "no worker drained the channel"
        );

        // The hole at 105 can't be committed past: a worker marking beyond the ceiling clamps to it.
        assert_eq!(
            dispatcher.tracker().mark_processed(0, 106),
            MarkOutcome::CappedAheadOfDispatch,
        );
        assert_eq!(
            dispatcher.tracker().committable_offsets().get(&0),
            Some(&105),
            "committable pinned at the sent ceiling while 105 is held",
        );

        // Drain A; the retry-flush now sends B and the ceiling advances past it.
        let _a = rx.recv().await.unwrap();
        assert!(
            dispatcher.redispatch_held(vec![(0, held)]).is_empty(),
            "the holdover flushed once the channel had room",
        );
        assert_eq!(
            dispatcher.tracker().mark_processed(0, 106),
            MarkOutcome::WithinDispatch,
        );
        assert_eq!(
            dispatcher.tracker().committable_offsets().get(&0),
            Some(&106)
        );
    }

    #[tokio::test]
    async fn nonblocking_dispatch_defers_events_for_a_held_partition_even_with_room() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with_buffer(&store, behavioral_catalog(), 16);
        dispatcher.assign_partition(0);
        let mut rx = dispatcher.router.add_partition(0).unwrap();

        // Partition 0 is already held: its fresh events queue behind the holdover rather than racing
        // onto the channel, even with room.
        let held: HashSet<i32> = [0].into_iter().collect();
        let mut full =
            dispatcher.dispatch_events_nonblocking(vec![consumed(person(1), 0, 200)], &held);

        assert_eq!(held_offsets(&full.remove(&0).unwrap()), vec![200]);
        assert!(rx.try_recv().is_err(), "nothing was sent to the channel");
        assert!(
            !dispatcher.tracker().committable_offsets().contains_key(&0),
            "a deferred event never raised the ceiling",
        );
    }

    #[tokio::test]
    async fn nonblocking_dispatch_returns_promptly_when_the_channel_is_saturated() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with_buffer(&store, behavioral_catalog(), 1);
        dispatcher.assign_partition(0);
        let _rx = dispatcher.router.add_partition(0).unwrap();
        let no_held = HashSet::new();

        dispatcher.dispatch_events_nonblocking(vec![consumed(person(1), 0, 0)], &no_held);
        // The second dispatch onto the saturated channel returns the holdover synchronously instead of
        // awaiting a drain.
        let full =
            dispatcher.dispatch_events_nonblocking(vec![consumed(person(2), 0, 1)], &no_held);
        assert!(
            full.contains_key(&0),
            "the saturated partition's events are held, never blocked on",
        );
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
    async fn maintenance_ticks_skip_owned_partitions_without_a_worker() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with(&store, behavioral_catalog());

        // Three owned partitions, but only 0 and 2 ever spawned a worker. Partition 1 is owned and
        // worker-less — the steady state of an idle partition that never received an event, which is
        // what produced the `no_worker` route-drop noise.
        dispatcher.assign_partition(0);
        dispatcher.assign_partition(1);
        dispatcher.assign_partition(2);
        let mut rx0 = dispatcher.router.add_partition(0).unwrap();
        let mut rx2 = dispatcher.router.add_partition(2).unwrap();

        let mut tickable = dispatcher.tickable_partitions();
        tickable.sort_unstable();
        assert_eq!(
            tickable,
            vec![0, 2],
            "a tick targets only owned partitions with a live worker, never the worker-less one",
        );

        // The fan-out reaches the worker-bearing partitions and silently skips the worker-less one
        // (no `no_worker` drop): only 0 and 2 receive the sweep.
        dispatcher.route_sweep(777).await;
        for rx in [&mut rx0, &mut rx2] {
            let batch = rx
                .recv()
                .await
                .expect("a worker-bearing partition got the sweep");
            assert_eq!(batch.len(), 1);
            match &batch[0] {
                ShuffleMessage::Sweep { due_before_ms } => assert_eq!(*due_before_ms, 777),
                other => panic!("expected Sweep, got {other:?}"),
            }
        }
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

    fn absent_team_catalog() -> Arc<CatalogHandle> {
        Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([])))
    }

    fn person_hashing_to(partition: u16, start: u128) -> Uuid {
        (start..start + 100_000)
            .map(Uuid::from_u128)
            .find(|p| partition_of(TeamId(TEAM), p, COHORT_PARTITION_COUNT) as u16 == partition)
            .expect("some person hashes to the partition")
    }

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

        // Simulate a crash between produce ack and outbox clear.
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

        dispatcher.assign_partition(0);
        dispatcher.route_merge_gc(1_000, 500).await;
        assert_eq!(dispatcher.workers.len(), 0, "GC never spawns a worker");
        assert_eq!(
            dispatcher.router.partition_count(),
            0,
            "no channel registered"
        );

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

        dispatcher
            .dispatch(vec![consumed(person(1), partition, 0)])
            .await;

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

    fn stage_pending(
        store: &CohortStore,
        partition: i32,
        p_old: Uuid,
        p_new: Uuid,
        merge_offset: i64,
    ) -> (PendingTransferKey, MergeStateTransfer) {
        let transfer = transfer_with(p_old, p_new, (partition, merge_offset), vec![]);
        let key = pending_key_of(partition, p_old);
        let pending = PendingTransfer {
            transfer: transfer.clone(),
            merge_msg_partition: partition,
            merge_msg_offset: merge_offset,
        };
        store
            .write_batch(|b| b.put_pending_transfer(&key, &pending.encode()))
            .unwrap();
        (key, transfer)
    }

    #[tokio::test]
    async fn eager_boot_redrive_re_produces_a_restored_pending_transfer_without_a_worker() {
        let (_dir, store) = temp_store();
        let (dispatcher, _sink, transfer_sink, merge) = dispatcher_full(
            &store,
            behavioral_catalog(),
            CaptureSink::new(),
            CaptureTransferSink::new(),
        );

        let partition = 3;
        let (key, transfer) = stage_pending(&store, partition, person(1), person(2), 41);
        dispatcher.assign_partition(partition);

        // No dispatch yet: dispatched_offset == 0, so mark_processed would clamp and trip
        // CappedAheadOfDispatch — the eager redrive correctly skips it.
        let owned: HashSet<i32> = [partition].into_iter().collect();
        dispatcher
            .eager_redrive_pending_transfers_on_boot(&owned)
            .await;

        assert_eq!(
            transfer_sink.transfers(),
            vec![transfer],
            "the stranded transfer was re-produced with no worker spawned",
        );
        assert!(
            store.get_pending_transfer(&key).unwrap().is_none(),
            "the outbox entry was cleared after the ack",
        );
        assert!(
            merge.merge_tracker.committable_offsets().is_empty(),
            "the eager redrive marks no offset (would clamp to dispatched_offset==0 and trip F1)",
        );
        assert_eq!(
            merge.merge_tracker.partition_count(),
            0,
            "no tracker entry was created — the merge offset was already committed-past",
        );
        assert!(
            !dispatcher.workers.contains_key(&partition),
            "the eager redrive does not spawn a worker",
        );
    }

    #[tokio::test]
    async fn eager_boot_redrive_is_a_noop_for_an_empty_outbox() {
        let (_dir, store) = temp_store();
        let (dispatcher, _sink, transfer_sink, merge) = dispatcher_full(
            &store,
            behavioral_catalog(),
            CaptureSink::new(),
            CaptureTransferSink::new(),
        );

        dispatcher.assign_partition(0);
        dispatcher.assign_partition(1);
        let owned: HashSet<i32> = [0, 1].into_iter().collect();
        dispatcher
            .eager_redrive_pending_transfers_on_boot(&owned)
            .await;

        assert!(
            transfer_sink.transfers().is_empty(),
            "an empty outbox produces nothing",
        );
        assert_eq!(
            merge.merge_tracker.partition_count(),
            0,
            "an empty outbox marks no offset",
        );
    }

    #[tokio::test]
    async fn eager_boot_redrive_only_touches_owned_partitions() {
        let (_dir, store) = temp_store();
        let (dispatcher, _sink, transfer_sink, _merge) = dispatcher_full(
            &store,
            behavioral_catalog(),
            CaptureSink::new(),
            CaptureTransferSink::new(),
        );

        let owned_partition = 3;
        let unowned_partition = 7;
        let (owned_key, owned_transfer) =
            stage_pending(&store, owned_partition, person(1), person(2), 41);
        let (unowned_key, _unowned_transfer) =
            stage_pending(&store, unowned_partition, person(3), person(4), 51);

        dispatcher.assign_partition(owned_partition);
        let owned: HashSet<i32> = [owned_partition].into_iter().collect();
        dispatcher
            .eager_redrive_pending_transfers_on_boot(&owned)
            .await;

        assert_eq!(
            transfer_sink.transfers(),
            vec![owned_transfer],
            "only the owned partition's transfer was re-produced",
        );
        assert!(
            store.get_pending_transfer(&owned_key).unwrap().is_none(),
            "the owned partition's outbox entry was cleared",
        );
        assert!(
            store.get_pending_transfer(&unowned_key).unwrap().is_some(),
            "the unowned partition's outbox entry was left untouched",
        );
    }

    #[tokio::test]
    async fn eager_boot_redrive_paginates_until_the_whole_outbox_is_drained() {
        let (_dir, store) = temp_store();
        let (dispatcher, _sink, transfer_sink, _merge) = dispatcher_full(
            &store,
            behavioral_catalog(),
            CaptureSink::new(),
            CaptureTransferSink::new(),
        );

        let partition = 3;
        let store_partition = partition_to_store_id(partition).unwrap();
        // Seed five entries so a page size of two spans three pages (2 + 2 + 1).
        let mut expected = Vec::new();
        for n in 1..=5u128 {
            let (_key, transfer) =
                stage_pending(&store, partition, person(n), person(100 + n), 40 + n as i64);
            expected.push(transfer);
        }

        let recovered = dispatcher
            .eager_redrive_partition(partition, store_partition, 2)
            .await;

        assert_eq!(
            recovered, 5,
            "every staged entry was re-produced across pages"
        );
        // Production follows key order across pages; sort both sides on the stable old-person key so
        // the assertion does not depend on the seeding order.
        let mut produced = transfer_sink.transfers();
        produced.sort_by_key(|t| t.old_person_uuid);
        expected.sort_by_key(|t| t.old_person_uuid);
        assert_eq!(produced, expected);
        assert!(
            store
                .scan_pending_transfers(store_partition, None, usize::MAX)
                .unwrap()
                .is_empty(),
            "the outbox is fully drained — no entry stranded past the first page",
        );
    }
}
