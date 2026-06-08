//! The `cohort_stream_events` wire envelope and the group consumer that drives it.
//!
//! [`CohortStreamEvent`] is the processor's own deserialize struct, deliberately decoupled from
//! `cohort-event-shuffler`'s producer type: the two services share only the JSON field names, so a
//! private copy means neither can break the other by adding a one-sided field.
//!
//! The Kafka-free routing core lives in [`EventDispatcher`] so it can be unit-tested with an
//! in-process router/store/catalog and no broker.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use dashmap::mapref::entry::Entry;
use dashmap::{DashMap, DashSet};
use lifecycle::Handle;
use metrics::{counter, histogram};
use rdkafka::consumer::{CommitMode, Consumer, ConsumerContext, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::{Offset, TopicPartitionList};
use serde::Deserialize;
use tracing::{debug, info, warn};

use crate::filters::manager::CatalogHandle;
use crate::observability::metrics::{
    COHORT_STREAM_CONSUME_BATCH_SIZE, COHORT_STREAM_DESERIALIZE_ERRORS,
    COHORT_STREAM_EMPTY_PAYLOAD, COHORT_STREAM_EVENTS_CONSUMED, COHORT_STREAM_EVENTS_DISPATCHED,
    COHORT_STREAM_EVENTS_SKIPPED_NOT_OWNED, COHORT_STREAM_KAFKA_RECV_ERRORS,
    COHORT_STREAM_OFFSET_COMMITS, COHORT_STREAM_OFFSET_COMMIT_ERRORS, COHORT_STREAM_ROUTE_ERRORS,
    COHORT_STREAM_WORKERS_SPAWNED, PARTITIONS_ASSIGNED_TOTAL, PARTITIONS_REVOKED_TOTAL,
    PARTITION_STATE_DELETED_TOTAL, REBALANCE_CLEANUP_SKIPPED_TOTAL, REVOKE_DRAIN_DURATION_SECONDS,
};
use crate::partitions::offset_tracker::OffsetTracker;
use crate::partitions::rebalance::{CohortConsumerContext, ConsumerCommandReceiver};
use crate::partitions::router::PartitionRouter;
use crate::partitions::shuffle_message::ShuffleMessage;
use crate::producer::MembershipSink;
use crate::store::CohortStore;
use crate::workers::Stage1Worker;

/// Back-off after a Kafka transport error so a fast-failing `recv()` can't spin the consume loop.
/// Short relative to the liveness deadline (60s × stall_threshold 3): a sustained outage stops the
/// heartbeat and trips the stall detector; a transient one recovers well within it.
const RECV_ERROR_BACKOFF: Duration = Duration::from_millis(500);

/// One re-keyed event as published to `cohort_stream_events`. Field names mirror the shuffler
/// envelope exactly so this deserializes the same bytes the shuffler emits.
///
/// `properties` / `person_properties` are raw, unparsed JSON strings; [`crate::hogvm::globals`]
/// parses them lazily so a malformed payload can skip a single event without failing the
/// deserialize. `source_partition` / `source_offset` are the upstream coordinates Stage 1 uses for
/// replay-safe counter increments.
#[derive(Debug, Clone, Deserialize)]
pub struct CohortStreamEvent {
    pub team_id: i32,
    pub person_id: String,
    pub distinct_id: String,
    pub uuid: String,
    pub event: String,
    /// ClickHouse wire format `"YYYY-MM-DD HH:MM:SS.ffffff"`; normalized to ISO 8601 when the
    /// globals dict is built (matching Node's `convertClickhouseRawEventToFilterGlobals`).
    pub timestamp: String,
    pub properties: Option<String>,
    pub person_properties: Option<String>,
    pub elements_chain: Option<String>,
    pub source_offset: i64,
    pub source_partition: i32,
}

/// One event consumed from `cohort_stream_events`, paired with its position on that topic.
///
/// These `partition`/`offset` are the consumer's commit coordinates (drive router affinity + the
/// [`OffsetTracker`]) — distinct from the event's upstream `source_partition`/`source_offset`, which
/// drive per-key replay idempotence in Stage 1
/// ([`AppliedOffsets::is_replay`](crate::stage1::state::AppliedOffsets::is_replay)). The two never
/// mix.
#[derive(Debug)]
pub struct ConsumedEvent {
    pub event: CohortStreamEvent,
    pub partition: i32,
    pub offset: i64,
}

/// The Kafka-free routing core: dispatches a consumed batch to per-partition workers, tracks
/// processed offsets, and owns the partition lifecycle the rebalance handler drives.
///
/// `router`, `workers`, and `owned` are shared `Arc`s so the [`CohortConsumerContext`] and its async
/// rebalance worker drive the *same* state this dispatcher routes through.
pub struct EventDispatcher {
    router: Arc<PartitionRouter>,
    /// `Arc` because each worker records its own offsets here (after producing) while the commit
    /// loop reads it — shared, not dispatcher-owned.
    tracker: Arc<OffsetTracker>,
    /// Interior mutability so the consume loop can spawn through a shared `&self`, the rebalance
    /// worker can evict through it, and shutdown can drain it — all over one coherent set.
    workers: Arc<DashMap<i32, Stage1Worker>>,
    /// Partitions currently assigned to this consumer. Set by `assign_partition`, cleared by
    /// `revoke_partition_sync`, and re-checked by `revoke_partition_drain` so a rapid revoke→assign
    /// leaves the live worker and its state untouched.
    owned: Arc<DashSet<i32>>,
    store: CohortStore,
    catalog: Arc<CatalogHandle>,
    sink: Arc<dyn MembershipSink>,
}

impl EventDispatcher {
    pub fn new(
        router: PartitionRouter,
        tracker: Arc<OffsetTracker>,
        store: CohortStore,
        catalog: Arc<CatalogHandle>,
        sink: Arc<dyn MembershipSink>,
    ) -> Self {
        Self {
            router: Arc::new(router),
            tracker,
            workers: Arc::new(DashMap::new()),
            owned: Arc::new(DashSet::new()),
            store,
            catalog,
            sink,
        }
    }

    /// Route a consumed batch to its per-partition workers, lazily spawning a worker per
    /// first-seen partition.
    ///
    /// Processed offsets are *not* marked here — the worker records an offset only after the
    /// event's membership changes are produced and acked (produce before commit). What is recorded
    /// here, before routing, is the per-partition dispatch ceiling
    /// ([`OffsetTracker::mark_dispatched`](crate::partitions::OffsetTracker::mark_dispatched)): the
    /// worker can never later commit past an offset that was not handed to it. A `RouteError` then
    /// needs no special handling — a message that reached no worker is never processed, so its
    /// offset stays below the committable point (the ceiling is a cap, never a floor) and Kafka
    /// replays it.
    ///
    /// An event whose partition this consumer no longer [`owns`](Self::owns) is dropped before any
    /// worker spawn or ceiling bump: a revoke clears `owned` synchronously on the poll thread
    /// (`revoke_partition_sync`), but an already-`recv()`'d batch can still arrive here afterwards.
    /// Routing it would resurrect a partition the revoke drain has reclaimed, so the gate skips it.
    /// The skipped event is never marked processed, so Kafka replays it on the true owner. The gate
    /// sits *before* `mark_dispatched` deliberately: bumping the ceiling for a dropped event would
    /// leak a tracker entry that the next reassignment would inherit.
    pub async fn dispatch(&self, batch: Vec<ConsumedEvent>) {
        if batch.is_empty() {
            return;
        }

        let mut not_owned_skipped: u64 = 0;
        let mut messages: Vec<(i32, ShuffleMessage)> = Vec::with_capacity(batch.len());
        for ConsumedEvent {
            event,
            partition,
            offset,
        } in batch
        {
            if !self.owned.contains(&partition) {
                not_owned_skipped += 1;
                continue;
            }
            self.ensure_worker(partition);
            // `+ 1` is the next-offset-to-consume convention.
            self.tracker.mark_dispatched(partition, offset + 1);
            messages.push((
                partition,
                ShuffleMessage::Event {
                    event,
                    cse_offset: offset,
                },
            ));
        }
        counter!(COHORT_STREAM_EVENTS_SKIPPED_NOT_OWNED).increment(not_owned_skipped);
        counter!(COHORT_STREAM_EVENTS_DISPATCHED).increment(messages.len() as u64);

        let errors = self.router.route_batch(messages).await;
        if !errors.is_empty() {
            counter!(COHORT_STREAM_ROUTE_ERRORS).increment(errors.len() as u64);
        }
    }

    /// Spawn a worker the first time an *owned* partition delivers, registering its router channel; a
    /// no-op once the worker exists, and a no-op for a partition this consumer no longer owns. The
    /// ownership check and the worker insert happen atomically under the `workers` shard guard, so a
    /// late in-flight batch can never resurrect a partition a concurrent revoke drain is reclaiming
    /// (the drain's `workers.remove` takes the same shard lock). `partition as u16` is exact (64-part
    /// shuffler output, non-negative) and matches the store's `partition_id` key type. The `None` arm
    /// is effectively unreachable, but is logged rather than asserted so a concurrent-spawn race
    /// degrades to a replayed batch instead of a panic.
    fn ensure_worker(&self, partition: i32) {
        match self.workers.entry(partition) {
            Entry::Occupied(_) => {}
            Entry::Vacant(slot) => {
                // INVARIANT: nothing in this arm may become `.await` — the DashMap shard guard is held
                // across the whole arm, and holding a guard across an await would both deadlock the
                // shard and risk UB. `owned.contains`, `router.add_partition`, and `Stage1Worker::spawn`
                // (which only calls `tokio::spawn`, never `.await`) are all synchronous; keep them so.
                //
                // The ownership check + insert are atomic under this guard, serializing the spawn
                // against a concurrent revoke drain's `workers.remove` (same shard lock). A revoke
                // clears `owned` synchronously *before* the drain is queued, so observing
                // `owned(partition) = true` here means no drain for this epoch has begun: either we
                // spawn first (the drain then removes + joins our worker and wipes its slice), or the
                // drain removed first (we see `Vacant` and `owned` is false — unless legitimately
                // re-acquired, where spawning is correct). Never spawn for an unowned partition.
                if !self.owned.contains(&partition) {
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
                        );
                        slot.insert(worker);
                        counter!(COHORT_STREAM_WORKERS_SPAWNED).increment(1);
                        info!(
                            partition,
                            "spawned stage 1 worker for newly-delivered partition"
                        );
                    }
                    None => warn!(
                        partition,
                        "router holds a live channel but no worker is registered; skipping spawn",
                    ),
                }
            }
        }
    }

    /// Whether `partition` is currently assigned to this consumer.
    pub fn owns(&self, partition: i32) -> bool {
        self.owned.contains(&partition)
    }

    /// Record a newly-assigned partition. The worker spawns lazily on the first message
    /// ([`ensure_worker`](Self::ensure_worker)), so there is no eager setup here.
    pub fn assign_partition(&self, partition: i32) {
        self.owned.insert(partition);
        counter!(PARTITIONS_ASSIGNED_TOTAL).increment(1);
    }

    /// Synchronous half of a revoke, safe to call from the librdkafka poll thread: mark the partition
    /// un-owned so the async drain's ownership re-check is accurate even if a reassign races in.
    ///
    /// The worker's channel is deliberately left intact. Under cooperative-sticky the broker has
    /// already stopped delivering this partition, so dropping the sender now would only tear down a
    /// worker a rapid revoke→assign is about to hand straight back. Teardown is decided in
    /// [`revoke_partition_drain`](Self::revoke_partition_drain), once the race has settled.
    pub fn revoke_partition_sync(&self, partition: i32) {
        self.owned.remove(&partition);
        counter!(PARTITIONS_REVOKED_TOTAL).increment(1);
    }

    /// Asynchronous half of a revoke: reclaim the partition unless a reassign re-acquired it.
    ///
    /// Run off the poll thread (it does async I/O). Re-checks ownership against the *current* state,
    /// not the queued snapshot, at **two** points — the rapid revoke→assign guard:
    /// - **Re-acquired before the drain starts** → skip entirely. The worker, its channel, and its
    ///   state are still ours.
    /// - **Truly revoked** → drop the sender (the worker drains its tail, produces, and exits), evict
    ///   it from `workers`, then delete its on-disk state slice.
    /// - **Re-acquired *during* the worker join** → skip the wipe after the join. The new tenure reuses
    ///   its own `partition_id`-prefixed slice, so there is nothing foreign to reclaim, and the worker
    ///   respawns lazily on the next dispatch.
    ///
    /// Evicting from `workers` is mandatory: [`ensure_worker`](Self::ensure_worker) only spawns into a
    /// vacant `workers` entry, so a stale entry would block a future reassignment from respawning the
    /// partition — its messages would `RouteError` and replay forever. The eviction sits *after* the
    /// entry ownership re-check so it never tears down a re-acquired partition.
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

        // A reassign that landed *during* the join means the slice and tracker entry belong to the new
        // tenure now — re-acquiring a partition reuses its own `partition_id`-prefixed slice, so there
        // is no foreign state to reclaim. Skip the wipe; the worker respawns lazily on the next
        // dispatch. (The entry re-check above can't catch this window because the join awaits.)
        if self.owned.contains(&partition) {
            counter!(REBALANCE_CLEANUP_SKIPPED_TOTAL, "phase" => "post_join").increment(1);
            debug!(
                partition,
                "skipping revoke cleanup post-join: partition re-acquired during the worker drain"
            );
            return;
        }

        // Drop the offset entry, or the commit loop keeps committing this partition after we lost it.
        // After the join: the worker's drain re-inserts the entry via `mark_processed`.
        self.tracker.forget_partition(partition);

        // Reclaim the state slice so a later tenure of this partition never reads a previous owner's
        // state. `delete_partition` takes the store's `u16` partition id; guard the cast rather than
        // silently truncate (the shuffler emits 64 partitions, so this never bites in practice).
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

    /// Processed offsets restricted to still-owned partitions. `owned` is cleared synchronously on
    /// revoke (before any async commit runs), so this drops a revoked partition's tail immediately —
    /// the authoritative guard against committing a partition this consumer no longer owns.
    fn owned_committable_offsets(&self) -> HashMap<i32, i64> {
        self.tracker
            .committable_offsets()
            .into_iter()
            .filter(|(partition, _)| self.owned.contains(partition))
            .collect()
    }

    /// Stop feeding workers and drain them. [`clear`](PartitionRouter::clear)ing the router closes
    /// every worker channel, so each worker drains its queued batches, produces their membership
    /// changes, marks their offsets, and exits. Joining *after* the clear guarantees all state is
    /// durable and all offsets marked before the caller's final commit. Returns the shared tracker
    /// so the caller can build that commit.
    ///
    /// Takes `&self` (not `self`): the dispatcher is shared (`Arc`) with the rebalance context, so it
    /// cannot be consumed. Removing each worker from the shared `workers` map before joining means a
    /// concurrent `revoke_partition_drain` and this drain can never both join the same worker — the
    /// `DashMap::remove` hands the worker to exactly one of them.
    async fn shutdown(&self) -> Arc<OffsetTracker> {
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

/// Map a Kafka partition (`i32`) to the store's `u16` partition id. Returns `None` for an
/// out-of-range value rather than silently truncating; consistent with the `partition as u16` cast
/// in [`EventDispatcher::ensure_worker`].
fn partition_to_store_id(partition: i32) -> Option<u16> {
    u16::try_from(partition).ok()
}

/// The `cohort_stream_events` group consumer: consume → route → commit.
///
/// Uses a raw `StreamConsumer` with manual commit rather than `common-kafka`'s
/// `SingleTopicConsumer`, because the per-partition [`OffsetTracker`] commits a
/// `TopicPartitionList` the wrapper can't express. The consumer carries a
/// [`CohortConsumerContext`] so Kafka's rebalance callbacks drive the partition lifecycle.
pub struct CohortStreamEventsConsumer {
    consumer: StreamConsumer<CohortConsumerContext>,
    topic: String,
    /// Shared with the rebalance context: the consume loop dispatches through it while the context's
    /// async worker assigns/revokes partitions on the same shared router/workers/owned state.
    dispatcher: Arc<EventDispatcher>,
    handle: Handle,
    recv_batch_size: usize,
    recv_batch_timeout: Duration,
    offset_commit_interval: Duration,
    /// Receiver for [`ConsumerCommand`](crate::partitions::ConsumerCommand)s; currently unused, held
    /// so the channel stays open.
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

    /// Run until the lifecycle handle signals shutdown. A successful consume cycle (even an empty
    /// poll) heartbeats liveness, so an idle topic stays healthy and only a wedged loop or sustained
    /// broker outage trips the stall detector.
    ///
    /// ## Why the commit is deadline-driven, not a `select!` arm
    ///
    /// Racing [`consume_batch`](Self::consume_batch) against a periodic commit tick in the same
    /// `select!` is unsafe: when the tick wins, tokio cancels the in-flight `consume_batch` and
    /// drops every event it had already buffered — `recv()`'d off librdkafka (gone from the broker)
    /// but never dispatched, then committed *past* by the next batch's offset mark, silently
    /// dropping events under bursty arrival. Instead, commit *after* `handle_outcome` returns, gated
    /// on a wall-clock deadline, so the `select!` only ever races shutdown against `consume_batch`.
    /// The single future it can still cancel is `consume_batch` on shutdown — safe, because that
    /// dropped buffer was never marked processed and the final sync commit leaves those offsets for
    /// Kafka to replay.
    pub async fn process(self) {
        let _guard = self.handle.process_scope();
        info!(topic = %self.topic, "cohort_stream_events consume loop starting");

        let mut commit_deadline = tokio::time::Instant::now() + self.offset_commit_interval;

        loop {
            tokio::select! {
                // Check shutdown before `consume_batch` so a steady topic can't starve it.
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

    /// Account for a consumed batch, dispatch it, and heartbeat. A transport error suppresses the
    /// heartbeat (so a sustained outage eventually restarts the pod) and backs off to avoid a hot
    /// loop; otherwise the cycle is healthy even when it consumed nothing.
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

    /// Accumulate up to `recv_batch_size` deserialized events within `recv_batch_timeout`. Each
    /// payload is deserialized immediately so no `BorrowedMessage` lifetime escapes the loop
    /// (mirroring `common-kafka`'s `json_recv_batch`). An idle topic yields an empty batch every
    /// `recv_batch_timeout`, which still heartbeats.
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

/// What one [`consume_batch`](CohortStreamEventsConsumer::consume_batch) cycle gathered.
struct ConsumeOutcome {
    events: Vec<ConsumedEvent>,
    deserialize_errors: u64,
    /// Zero-byte payloads, skipped without deserializing — counted so they aren't a conservation
    /// blind spot (the shuffler never emits these).
    empty_payloads: u64,
    transport_error: bool,
}

/// Turn a `partition → next-offset-to-consume` snapshot into the `TopicPartitionList` committed to
/// Kafka. Pure (no consumer, no I/O) so the mapping is unit-testable.
fn build_commit_tpl(topic: &str, offsets: &HashMap<i32, i64>) -> TopicPartitionList {
    let mut tpl = TopicPartitionList::new();
    for (&partition, &next_offset) in offsets {
        // `add_partition_offset` only errors on an invalid sentinel; the tracker's non-negative
        // offsets are always valid.
        if let Err(err) = tpl.add_partition_offset(topic, partition, Offset::Offset(next_offset)) {
            warn!(topic, partition, next_offset, error = %err, "skipping partition in commit list");
        }
    }
    tpl
}

/// Commit the given processed offsets (already restricted to owned partitions by the caller) and
/// record what was acked. A free function so both the periodic (async) and final (sync) commits
/// reuse it. Generic over the consumer context so it works regardless of which [`ConsumerContext`]
/// the consumer carries.
fn commit_offsets<C: ConsumerContext>(
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
            warn!(topic, error = %err, "failed to commit cohort_stream_events offsets");
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
    use crate::producer::{CaptureSink, MembershipStatus};
    use crate::stage1::{Stage1State, StatefulRecord};
    use crate::store::{LeafStateKey, Stage1Key, StoreConfig};

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
    fn envelope_round_trips_through_wire_bytes() {
        // Covers the `from_slice` path the consumer actually uses (not `from_value`), catching a
        // number-as-string regression in the shuffler's output.
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

    /// A team with one `performed_event` leaf on `$pageview` (7d) — every `$pageview` enters.
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

    /// Like [`dispatcher_with`] but also returns the capture sink, so a test can assert what the
    /// workers produced (e.g. that a revoke drain flushed a partition's tail before reclaiming it).
    fn dispatcher_and_sink(
        store: &CohortStore,
        catalog: Arc<CatalogHandle>,
    ) -> (EventDispatcher, Arc<CaptureSink>) {
        let sink = Arc::new(CaptureSink::new());
        let dispatcher = EventDispatcher::new(
            PartitionRouter::new(64),
            Arc::new(OffsetTracker::new()),
            store.clone(),
            catalog,
            sink.clone(),
        );
        (dispatcher, sink)
    }

    /// The behavioral leaf's `LeafStateKey`, read through the catalog like the worker does rather
    /// than reconstructed by hand.
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
        }
    }

    fn consumed(person: Uuid, topic_partition: i32, topic_offset: i64) -> ConsumedEvent {
        ConsumedEvent {
            // Source coordinates mirror the topic coordinates: this exercises routing + commit
            // tracking, not the separately-tested per-key replay guard.
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

        // `dispatch` now drops events for unowned partitions, so the batch's partitions must be owned.
        dispatcher.assign_partition(0);
        dispatcher.assign_partition(1);

        let batch = vec![
            consumed(person(1), 0, 10),
            consumed(person(2), 0, 11),
            consumed(person(3), 1, 5),
        ];
        dispatcher.dispatch(batch).await;

        assert_eq!(dispatcher.workers.len(), 2);

        // Offsets are marked only after the workers produce, so they're observable only once the
        // drain completes.
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

        // Spawn a worker for owned partition 9, then revoke its router channel: the dispatcher still
        // "knows" the partition (so won't re-spawn), but `route_batch` finds no sender and surfaces
        // a RouteError. The dropped event reaches no worker, so its offset is never marked.
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
        // The ceiling was raised before routing (a cap, not a floor), so the partition is tracked
        // even though it has no committable offset.
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

        // Sync half marks un-owned but leaves the worker running (cooperative-sticky has already
        // stopped delivery), so the sender survives until the async drain.
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
        // Guards the eviction gotcha: a fully-revoked partition must respawn cleanly on reassignment.
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

        // Revoke then re-assign before the async cleanup runs: the drain must skip.
        dispatcher.revoke_partition_sync(0);
        dispatcher.assign_partition(0);
        dispatcher.revoke_partition_drain(0).await;

        assert!(dispatcher.owns(0), "re-owned partition stays owned");
        assert_eq!(dispatcher.workers.len(), 1, "worker preserved");
        assert_eq!(dispatcher.router.partition_count(), 1, "sender preserved");

        // The same worker keeps routing — a fresh message lands on it and advances the offset.
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
        // Revoke and shutdown share one `Arc<DashMap>`, so `remove` hands a worker to exactly one of
        // them (no double-drain). The revoked partition is drained then forgotten; the survivor
        // commits on shutdown.
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

        // Produced exactly once: partition 0 drained before being forgotten, with no double-drain.
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
        // A revoked partition's tail must leave the tracker, or the periodic/final commit keeps
        // committing it for a partition this consumer no longer owns → regresses the new owner.
        let (_dir, store) = temp_store();
        let (dispatcher, sink) = dispatcher_and_sink(&store, behavioral_catalog());

        dispatcher.assign_partition(0);
        dispatcher.assign_partition(1);
        dispatcher
            .dispatch(vec![consumed(person(1), 0, 10), consumed(person(2), 1, 20)])
            .await;

        dispatcher.revoke_partition_sync(0);
        dispatcher.revoke_partition_drain(0).await;

        // The drain produced partition 0's tail, so its offset was marked before being forgotten.
        assert_eq!(
            sink.changes()
                .iter()
                .filter(|change| change.person_id == person(1).to_string())
                .count(),
            1,
        );
        assert_eq!(dispatcher.tracker().committable_offsets().get(&0), None);
        assert!(!dispatcher.owned_committable_offsets().contains_key(&0));

        // The marking mechanism still works: the still-owned partition commits on shutdown.
        let tracker = dispatcher.shutdown().await;
        assert_eq!(tracker.committable_offsets().get(&1), Some(&21));
    }

    #[tokio::test]
    async fn owned_committable_offsets_excludes_unowned_partitions() {
        // The owned filter is the authoritative commit guard, covering the window between the sync
        // revoke (clears ownership) and the async drain (forgets the lingering tracker entry).
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
    async fn dispatch_after_full_revoke_does_not_resurrect_partition() {
        // The #1 rebalance race: a batch that `recv()`'d before the revoke must not respawn a worker
        // (or write a fresh slice) for a partition this pod has fully reclaimed. Both the dispatch gate
        // and the spawn gate consult `owned`, which the sync revoke clears before the drain runs.
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let lsk = behavioral_lsk(&catalog);
        let dispatcher = dispatcher_with(&store, catalog);

        dispatcher.assign_partition(0);
        dispatcher.dispatch(vec![consumed(person(1), 0, 10)]).await;
        dispatcher.revoke_partition_sync(0);
        dispatcher.revoke_partition_drain(0).await;

        // Fully reclaimed: no worker, no sender, no slice.
        assert_eq!(dispatcher.workers.len(), 0);
        assert_eq!(dispatcher.router.partition_count(), 0);
        assert!(behavioral_state(&store, 0, person(1), lsk).is_none());

        // A late, already-`recv()`'d batch for the now-unowned partition is dropped, not resurrected.
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
        // The gate sits before `mark_dispatched`, so the dropped event leaks no tracker entry/ceiling.
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
        // The spawn gate (layer 2): even called directly, `ensure_worker` creates neither a worker nor
        // a router channel for a partition this consumer does not own.
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

        // Once owned, the same call spawns.
        dispatcher.assign_partition(5);
        dispatcher.ensure_worker(5);
        assert_eq!(dispatcher.workers.len(), 1);
        assert_eq!(dispatcher.router.partition_count(), 1);

        let _tracker = dispatcher.shutdown().await;
    }

    #[tokio::test]
    async fn dispatch_routes_owned_and_drops_revoked_without_raising_its_ceiling() {
        // A batch spanning an owned partition and a just-revoked one routes the owned and drops the
        // rest — without raising the dropped partition's dispatch ceiling (the gate precedes
        // `mark_dispatched`).
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let lsk = behavioral_lsk(&catalog);
        let dispatcher = dispatcher_with(&store, catalog);

        dispatcher.assign_partition(0);
        dispatcher.assign_partition(1);
        // Revoke (and drain) partition 1 so only 0 is owned when the mixed batch arrives.
        dispatcher.revoke_partition_sync(1);
        dispatcher.revoke_partition_drain(1).await;

        dispatcher
            .dispatch(vec![consumed(person(1), 0, 10), consumed(person(2), 1, 20)])
            .await;

        // Owned partition 0 spawned + routed; revoked partition 1 dropped — no worker, no ceiling.
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
        // Assigned then revoked without ever dispatching: the drain has no worker to join, no tracker
        // entry to forget, and an empty slice to delete — all a clean no-op.
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
        // The consume loop's final `dispatch` always completes *before* `process()` breaks to
        // `shutdown` — the biased `select!` only ever cancels an idle `consume_batch`, never an
        // in-flight dispatch (see `process`). So a worker a last-moment dispatch spawns is guaranteed
        // to be in `workers` when shutdown drains it. (`shutdown` deliberately does not race a live
        // dispatch: it does not clear `owned`, so a *concurrent* dispatch could register a worker after
        // its `router.clear()` and never be signalled to stop — which is exactly why the loop never
        // dispatches once shutdown has begun.) This pins the no-strand + replay-safe-offset property of
        // that ordering; the genuine dispatch-vs-cleanup race is covered by the revoke stress test.
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
        // Stress the rebalance race the sequential tests can't: a revoke (sync clear + async drain)
        // runs concurrently with an in-flight dispatch, over many rounds. Invariant under test: once
        // the partition is un-owned, no worker and no on-disk slice may survive — and neither the
        // dispatch nor the drain may hang (the awaits below are the no-progress tripwire).
        let (_dir, store) = temp_store();
        let catalog = behavioral_catalog();
        let lsk = behavioral_lsk(&catalog);
        let dispatcher = Arc::new(dispatcher_with(&store, catalog));

        const P: i32 = 0;
        for round in 0..200u128 {
            // Own it so the dispatch can attempt a (racing) spawn, then revoke it out from under it.
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

            // No re-assign this round, so both paths must make progress and the partition ends unowned.
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
}
