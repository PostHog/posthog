//! The `cohort_stream_events` wire envelope (TDD §4.3) and the group consumer that drives it.
//!
//! [`CohortStreamEvent`] is the processor's **own** deserialize struct — deliberately decoupled
//! from `cohort-event-shuffler`'s producer type (`cohort-event-shuffler/src/event.rs:30-42`). The
//! two services share only the JSON field names on the wire; the shuffler comment at `event.rs:25`
//! anticipates exactly this split. Keeping a private copy means neither service can break the other
//! by adding a producer-only or consumer-only field.
//!
//! [`CohortStreamEventsConsumer`] (PR 1.7) is the first runnable artifact of the new pipeline: it
//! consumes the topic, routes each event to its partition-affined [`Stage1Worker`], and commits
//! processed offsets. The Kafka-free routing core lives in [`EventDispatcher`] so it can be
//! unit-tested with an in-process router/store/catalog and no broker.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;
use lifecycle::Handle;
use metrics::{counter, histogram};
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::{Offset, TopicPartitionList};
use serde::Deserialize;
use tracing::{debug, info, warn};

use crate::filters::manager::CatalogHandle;
use crate::observability::metrics::{
    COHORT_STREAM_CONSUME_BATCH_SIZE, COHORT_STREAM_DESERIALIZE_ERRORS,
    COHORT_STREAM_EMPTY_PAYLOAD, COHORT_STREAM_EVENTS_CONSUMED, COHORT_STREAM_EVENTS_DISPATCHED,
    COHORT_STREAM_KAFKA_RECV_ERRORS, COHORT_STREAM_OFFSET_COMMITS,
    COHORT_STREAM_OFFSET_COMMIT_ERRORS, COHORT_STREAM_ROUTE_ERRORS, COHORT_STREAM_WORKERS_SPAWNED,
};
use crate::partitions::offset_tracker::OffsetTracker;
use crate::partitions::router::PartitionRouter;
use crate::partitions::shuffle_message::ShuffleMessage;
use crate::producer::MembershipSink;
use crate::store::CohortStore;
use crate::workers::Stage1Worker;

/// Back-off after a Kafka transport error so a fast-failing `recv()` can't spin the consume loop.
/// Short relative to the liveness deadline (60s × stall_threshold 3): a *sustained* outage stops
/// the heartbeat and the stall detector restarts the pod; a transient one recovers well within it.
const RECV_ERROR_BACKOFF: Duration = Duration::from_millis(500);

/// One re-keyed event as published to `cohort_stream_events`. Field names mirror TDD §4.3 and the
/// shuffler envelope exactly so this deserializes the same bytes the shuffler emits.
///
/// `properties` / `person_properties` are raw, unparsed JSON strings (as stored in
/// `clickhouse_events_json`); [`crate::hogvm::globals`] parses them lazily so a malformed payload
/// can skip a single event without failing the deserialize. `source_partition` / `source_offset`
/// carry the upstream coordinates Stage 1 (PR 1.6) uses for replay-safe counter increments.
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
    /// Raw event-properties JSON, or `None` when the source column was null.
    pub properties: Option<String>,
    /// Raw person-properties JSON, or `None` when the source column was null.
    pub person_properties: Option<String>,
    pub elements_chain: Option<String>,
    pub source_offset: i64,
    pub source_partition: i32,
}

/// One event consumed from `cohort_stream_events`, paired with its position **on that topic**.
///
/// The topic `partition`/`offset` here are the consumer's own commit coordinates — distinct from
/// the event's upstream [`CohortStreamEvent::source_partition`]/[`source_offset`](CohortStreamEvent::source_offset),
/// which anchor per-key replay idempotence inside Stage 1. The two never mix: this pair drives the
/// router affinity and the [`OffsetTracker`]; the source pair drives
/// [`is_replay`](crate::partitions::is_replay).
#[derive(Debug)]
pub struct ConsumedEvent {
    pub event: CohortStreamEvent,
    pub partition: i32,
    pub offset: i64,
}

/// The Kafka-free routing core: dispatches a consumed batch to per-partition workers and tracks
/// processed offsets. Split out from [`CohortStreamEventsConsumer`] so the routing, lazy-spawn, and
/// offset logic is unit-testable against an in-process router/store/catalog with no broker.
pub struct EventDispatcher {
    router: PartitionRouter,
    /// Per-partition processed offsets. `Arc` because each worker now records its own offsets here
    /// (after producing), while the consumer's commit loop reads it — shared, not dispatcher-owned.
    tracker: Arc<OffsetTracker>,
    /// Partition → its long-lived Stage 1 worker. Interior mutability so the consume loop can spawn
    /// through a shared `&self`; also the join set drained on shutdown.
    workers: DashMap<i32, Stage1Worker>,
    store: CohortStore,
    catalog: Arc<CatalogHandle>,
    /// Shared shadow-topic output sink, handed to every spawned worker (cheap `Arc` clone).
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
            router,
            tracker,
            workers: DashMap::new(),
            store,
            catalog,
            sink,
        }
    }

    /// Route a consumed batch to its per-partition workers.
    ///
    /// For each partition seen for the first time, lazily registers a worker channel and spawns its
    /// [`Stage1Worker`] (single-replica M1: partitions are assigned once and only revoked at
    /// shutdown, so a per-batch check is cheap and there are no mid-life revocations — the formal
    /// rebalance callbacks are deferred to PR 3.5). Then routes every event, carrying its
    /// `cohort_stream_events` offset on the message.
    ///
    /// Processed offsets are **not** marked here — PR 1.8 moved that into the worker, which records
    /// an offset only after the event's membership changes are produced and acked (produce before
    /// commit). What *is* recorded here, before routing, is the per-partition **dispatch ceiling**
    /// ([`OffsetTracker::mark_dispatched`](crate::partitions::OffsetTracker::mark_dispatched)): the
    /// worker can never later commit past an offset that was not handed to it. A `RouteError` then
    /// needs no special handling — a message that reached no worker is never *processed*, so its
    /// offset stays below the committable point (raising the ceiling is a cap, never a floor) and
    /// Kafka replays it. The error count is surfaced via `cohort_stream_route_errors_total`.
    pub async fn dispatch(&self, batch: Vec<ConsumedEvent>) {
        if batch.is_empty() {
            return;
        }

        let dispatched = batch.len() as u64;
        let mut messages: Vec<(i32, ShuffleMessage)> = Vec::with_capacity(batch.len());
        for ConsumedEvent {
            event,
            partition,
            offset,
        } in batch
        {
            self.ensure_worker(partition);
            // Raise the dispatch ceiling for this offset *before* routing, so a later
            // `mark_processed` cannot advance the committed position past a consumed-but-undispatched
            // offset (the F1 defense-in-depth). `+ 1` is the next-offset-to-consume convention.
            self.tracker.mark_dispatched(partition, offset + 1);
            messages.push((
                partition,
                ShuffleMessage::Event {
                    event,
                    cse_offset: offset,
                },
            ));
        }
        counter!(COHORT_STREAM_EVENTS_DISPATCHED).increment(dispatched);

        let errors = self.router.route_batch(messages).await;
        if !errors.is_empty() {
            counter!(COHORT_STREAM_ROUTE_ERRORS).increment(errors.len() as u64);
        }
    }

    /// Spawn a worker the first time a partition delivers, registering its router channel. A no-op
    /// once the worker exists. Kafka partitions for this topic are small and non-negative (64-part
    /// shuffler output), so `partition as u16` is exact — `u16` is the store's `partition_id` key
    /// type. The `None` arm is unreachable in single-replica M1 (we only ask the router for a
    /// channel when we hold no worker, and insert the worker immediately), but is logged rather than
    /// asserted so a future multi-pod race degrades to a replayed batch instead of a panic.
    fn ensure_worker(&self, partition: i32) {
        if self.workers.contains_key(&partition) {
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
                self.workers.insert(partition, worker);
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

    /// The per-partition offset tracker (read by the commit loop; the workers mark it after they
    /// produce). `Arc` derefs to `&OffsetTracker`.
    fn tracker(&self) -> &OffsetTracker {
        self.tracker.as_ref()
    }

    /// Stop feeding workers and drain them. Dropping the router closes every worker channel; each
    /// worker's `recv()` then returns `None`, it drains its queued batches, applies them to RocksDB,
    /// **produces their membership changes, and marks their offsets**, then exits. Joining *after*
    /// the drop guarantees all routed state is durable and all offsets are marked before the
    /// caller's final commit. Returns the shared tracker so the caller can build that commit.
    async fn shutdown(self) -> Arc<OffsetTracker> {
        let Self {
            router,
            tracker,
            workers,
            ..
        } = self;
        drop(router);
        for (partition, worker) in workers {
            if let Err(err) = worker.join().await {
                warn!(partition, error = %err, "stage 1 worker panicked during shutdown drain");
            }
        }
        tracker
    }
}

/// The `cohort_stream_events` group consumer: consume → route → commit. Owns the raw
/// `StreamConsumer` and the Kafka-free [`EventDispatcher`].
///
/// Mirrors `cohort-event-shuffler`'s `EventShuffler::process` loop shape, but consumes a raw
/// `StreamConsumer` with manual offset commit (decision 1) rather than `common-kafka`'s
/// `SingleTopicConsumer`, because the per-partition [`OffsetTracker`] commits a
/// `TopicPartitionList` the wrapper can't express.
pub struct CohortStreamEventsConsumer {
    consumer: StreamConsumer,
    topic: String,
    dispatcher: EventDispatcher,
    handle: Handle,
    recv_batch_size: usize,
    recv_batch_timeout: Duration,
    offset_commit_interval: Duration,
}

impl CohortStreamEventsConsumer {
    pub fn new(
        consumer: StreamConsumer,
        topic: String,
        dispatcher: EventDispatcher,
        handle: Handle,
        recv_batch_size: usize,
        recv_batch_timeout: Duration,
        offset_commit_interval: Duration,
    ) -> Self {
        Self {
            consumer,
            topic,
            dispatcher,
            handle,
            recv_batch_size,
            recv_batch_timeout,
            offset_commit_interval,
        }
    }

    /// Run until the lifecycle handle signals shutdown. A successful consume cycle (even an empty
    /// poll) heartbeats liveness, so an idle topic stays healthy and only a wedged loop or a
    /// sustained broker outage trips the stall detector. On shutdown: drop the router (workers drain
    /// then exit), join them, then a final *synchronous* commit so the just-drained offsets are
    /// durable before exit (the periodic commit is async to keep the hot loop cheap).
    ///
    /// ## Why the commit is deadline-driven, not a `select!` arm (F1 fix)
    ///
    /// An earlier shape raced [`consume_batch`](Self::consume_batch) against a periodic
    /// `commit_tick` in the same `select!`. When the tick won, tokio **cancelled the in-flight
    /// `consume_batch` and dropped every event it had already buffered** — events `recv()`'d off
    /// librdkafka (gone from the broker) but never dispatched, never counted, and then committed
    /// *past* by the next batch's offset mark. That silently dropped ~10% of events under bursty
    /// arrival. The fix: commit **after** `handle_outcome` returns, gated on a wall-clock deadline,
    /// so the loop's `select!` only ever races shutdown against `consume_batch`. `consume_batch`
    /// self-bounds at `recv_batch_timeout`, so commits still fire ≈ every `offset_commit_interval`,
    /// at most one `recv_batch_timeout` late. The single future the `select!` can still cancel is
    /// `consume_batch` **on shutdown** — and that is safe: its dropped buffer was never marked
    /// processed, so the final sync commit below leaves those offsets for Kafka to replay.
    pub async fn process(self) {
        let _guard = self.handle.process_scope();
        info!(topic = %self.topic, "cohort_stream_events consume loop starting");

        // First commit waits a full interval rather than firing on the very first iteration.
        let mut commit_deadline = tokio::time::Instant::now() + self.offset_commit_interval;

        loop {
            tokio::select! {
                // `biased`: check shutdown before polling `consume_batch`, so a pending shutdown
                // can't be starved by a steadily-arriving topic.
                biased;
                _ = self.handle.shutdown_recv() => {
                    info!("shutdown signal received, stopping consume loop");
                    break;
                }
                outcome = self.consume_batch() => {
                    self.handle_outcome(outcome).await;
                    // Deadline-driven commit: never cancels accumulation. The workers mark offsets
                    // as they finish producing; this flushes whatever is marked so far.
                    let now = tokio::time::Instant::now();
                    if now >= commit_deadline {
                        commit_offsets(&self.consumer, self.dispatcher.tracker(), &self.topic, CommitMode::Async);
                        commit_deadline = now + self.offset_commit_interval;
                    }
                }
            }
        }

        let Self {
            consumer,
            dispatcher,
            topic,
            ..
        } = self;
        let tracker = dispatcher.shutdown().await;
        commit_offsets(&consumer, &tracker, &topic, CommitMode::Sync);
        info!(topic = %topic, "cohort_stream_events consume loop stopped");
    }

    /// Account for a consumed batch, dispatch it, and manage the liveness heartbeat. A transport
    /// error suppresses the heartbeat (so a sustained outage eventually restarts the pod) and backs
    /// off to avoid a hot loop; otherwise the cycle is healthy even when it consumed nothing.
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

    /// Accumulate up to `recv_batch_size` deserialized events within `recv_batch_timeout`, mirroring
    /// `common-kafka`'s `json_recv_batch` discipline: each payload is deserialized immediately so no
    /// `BorrowedMessage` lifetime escapes the loop. Returns whatever it gathered when the window
    /// elapses, so an idle topic yields an empty batch every `recv_batch_timeout` (and heartbeats).
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
    /// Messages with a `None` (zero-byte) payload, skipped without deserializing — counted so they
    /// are not a conservation blind spot (the shuffler never emits these).
    empty_payloads: u64,
    /// A Kafka transport error occurred; the caller suppresses the heartbeat and backs off.
    transport_error: bool,
}

/// Turn a `partition → next-offset-to-consume` snapshot into the `TopicPartitionList` committed to
/// Kafka. Pure (no consumer, no I/O) so the offset → commit-list mapping is unit-testable.
fn build_commit_tpl(topic: &str, offsets: &HashMap<i32, i64>) -> TopicPartitionList {
    let mut tpl = TopicPartitionList::new();
    for (&partition, &next_offset) in offsets {
        // `add_partition_offset` only errors on an invalid offset sentinel; `Offset::Offset(n)` for
        // the non-negative offsets the tracker holds is always valid.
        if let Err(err) = tpl.add_partition_offset(topic, partition, Offset::Offset(next_offset)) {
            warn!(topic, partition, next_offset, error = %err, "skipping partition in commit list");
        }
    }
    tpl
}

/// Commit the tracker's processed offsets to Kafka and record what was acked. A free function over
/// `(&consumer, &tracker)` so both the periodic (async) and final (sync) commit reuse it — the
/// final commit runs after [`EventDispatcher::shutdown`] has moved the tracker out of the dispatcher.
fn commit_offsets(
    consumer: &StreamConsumer,
    tracker: &OffsetTracker,
    topic: &str,
    mode: CommitMode,
) {
    let offsets = tracker.committable_offsets();
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
    use serde_json::json;
    use tempfile::TempDir;
    use uuid::Uuid;

    use crate::filters::{CohortId, FilterCatalog, TeamFiltersBuilder, TeamId};
    use crate::producer::CaptureSink;
    use crate::stage1::{Stage1State, StatefulRecord};
    use crate::store::{LeafStateKey, Stage1Key, StoreConfig};

    const TEAM: i32 = 7;
    const BEHAVIORAL_HASH: [u8; 16] = *b"0123456789abcdef";
    const BASE_TS: &str = "2026-05-26 12:34:56.789000";

    // ── Wire deserialize ──────────────────────────────────────────────────────

    #[test]
    fn deserializes_a_full_shuffler_envelope() {
        // The exact key set the shuffler emits (TDD §4.3) must round-trip into this struct.
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
        // The consumer decodes raw bytes via `serde_json::from_slice`, not `from_value`; cover that
        // exact path so a number-as-string regression in the shuffler's output is caught here.
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

    // ── Commit-list building ──────────────────────────────────────────────────

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

    // ── Dispatch core (lazy spawn + route; offsets marked by the workers), no Kafka ──────────

    fn temp_store() -> (TempDir, CohortStore) {
        let dir = TempDir::new().unwrap();
        let config = StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        };
        let store = CohortStore::open(&config).expect("open store");
        (dir, store)
    }

    /// A team with a single `performed_event` behavioral leaf on `$pageview` (window 7d) — every
    /// `$pageview` matches and enters.
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
        let filters = builder.freeze();
        Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([(
            TeamId(TEAM),
            filters,
        )])))
    }

    fn dispatcher_with(store: &CohortStore, catalog: Arc<CatalogHandle>) -> EventDispatcher {
        EventDispatcher::new(
            PartitionRouter::new(64),
            Arc::new(OffsetTracker::new()),
            store.clone(),
            catalog,
            Arc::new(CaptureSink::new()),
        )
    }

    /// The behavioral leaf's `LeafStateKey`, read back through the catalog the same way the worker
    /// does — its derivation hashes the full leaf config, so we never reconstruct it by hand.
    fn behavioral_lsk(catalog: &CatalogHandle) -> LeafStateKey {
        let snapshot = catalog.load();
        let team = snapshot.team(TeamId(TEAM)).expect("team in catalog");
        team.by_condition_to_lsk[&BEHAVIORAL_HASH][0]
    }

    fn person(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    /// A matching `$pageview` event for `person`, carrying its upstream source coordinates.
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
            // Source coordinates mirror the topic coordinates here; this test exercises routing +
            // commit tracking, not the (separately tested) per-key source-offset replay guard.
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

        // Two events on partition 0 (offsets 10, 11) and one on partition 1 (offset 5).
        let batch = vec![
            consumed(person(1), 0, 10),
            consumed(person(2), 0, 11),
            consumed(person(3), 1, 5),
        ];
        dispatcher.dispatch(batch).await;

        // One worker spawned per distinct partition.
        assert_eq!(dispatcher.workers.len(), 2);

        // Offsets are marked by the workers after they produce (produce before commit), so they are
        // observable only once the drain completes. Draining also applies the routed state.
        let tracker = dispatcher.shutdown().await;

        // Each partition's next-offset-to-consume is max(offset) + 1.
        let committable = tracker.committable_offsets();
        assert_eq!(committable.get(&0), Some(&12));
        assert_eq!(committable.get(&1), Some(&6));

        // Each person entered the behavioral leaf under its own topic partition (the store key's
        // partition_id).
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

        dispatcher.dispatch(vec![consumed(person(1), 0, 1)]).await;
        assert_eq!(dispatcher.workers.len(), 1);

        // A second batch on the same partition must not spawn a second worker.
        dispatcher.dispatch(vec![consumed(person(2), 0, 2)]).await;
        assert_eq!(dispatcher.workers.len(), 1);

        // After draining, the single worker has produced both events and marked max(offset) + 1.
        let tracker = dispatcher.shutdown().await;
        assert_eq!(tracker.committable_offsets().get(&0), Some(&3));
    }

    #[tokio::test]
    async fn dispatch_route_error_does_not_advance_the_offset() {
        let (_dir, store) = temp_store();
        let dispatcher = dispatcher_with(&store, behavioral_catalog());

        // Spawn a worker for partition 9, then revoke its router channel: the worker drains nothing
        // and exits, but the dispatcher still "knows" it, so the next dispatch won't re-spawn — and
        // route_batch finds no sender, surfacing a RouteError. The dropped event reaches no worker,
        // so its offset is never marked and Kafka replays it.
        dispatcher.ensure_worker(9);
        dispatcher.router.remove_partition(9);

        dispatcher.dispatch(vec![consumed(person(1), 9, 100)]).await;

        let tracker = dispatcher.shutdown().await;
        assert_eq!(
            tracker.committable_offsets().get(&9),
            None,
            "a route error leaves the offset unmarked for Kafka to replay",
        );
        // The dispatch ceiling *was* raised before routing (the partition is tracked), so the
        // event is accounted for; it simply has no processed offset to commit. Raising the ceiling
        // is a cap, never a floor — it never advances the committed position on its own.
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
}
