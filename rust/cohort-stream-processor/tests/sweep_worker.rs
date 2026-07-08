//! The time-driven eviction sweep, driven end-to-end through the public API (no Kafka). Events flow
//! through a spawned [`Stage1Worker`](cohort_stream_processor::workers::Stage1Worker) to schedule
//! evictions, then a [`ShuffleMessage::Sweep`](cohort_stream_processor::partitions::ShuffleMessage)
//! with a synthetic cutoff drains the worker's queue. One case drives the real
//! [`DispatchSweeper`](cohort_stream_processor::sweep::DispatchSweeper) over an
//! [`EventDispatcher`](cohort_stream_processor::consumers::EventDispatcher) to cover the production
//! routing path. The scheduling/queue mechanics themselves are unit-tested in
//! `tests/sweep_eviction_queue.rs`; the per-variant eviction in `src/workers/sweep_callback.rs`.
//! The Stage 2 section covers a time-driven leaf flip recomposing its composable (multi-leaf)
//! cohorts through the sweep's second produce.

// Tests seed and assert through `CohortStore` directly — the sanctioned direct-store test surface.
#![allow(clippy::disallowed_methods)]

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use chrono_tz::America::New_York;
use chrono_tz::Asia::Kolkata;
use chrono_tz::{Tz, UTC};
use cohort_stream_processor::consumers::{CohortStreamEvent, EventDispatcher};
use cohort_stream_processor::filters::{
    CatalogHandle, CohortId, FilterCatalog, TeamFilters, TeamFiltersBuilder, TeamId,
};
use cohort_stream_processor::partitions::{
    MeteredReceiver, OffsetTracker, PartitionRouter, ShuffleMessage,
};
use cohort_stream_processor::producer::{
    CaptureSink, CohortMembershipChange, MembershipSink, MembershipStatus,
};
use cohort_stream_processor::stage1::bucket_tz::{day_idx_in_tz, start_of_day_ms_in_tz};
use cohort_stream_processor::stage1::{
    clickhouse_timestamp_to_millis, Stage1State, StateVariant, StatefulRecord,
};
use cohort_stream_processor::stage2::Stage2State;
use cohort_stream_processor::store::{
    BehavioralKey, CohortStore, LeafStateKey, OffloadConfig, OffloadMode, PersonRecordKey,
    Stage2Key, StoreConfig, StoreHandle,
};
use cohort_stream_processor::workers::{process_event, MergeWorkerDeps, Stage1Worker};
use common_kafka::kafka_producer::KafkaProduceError;
use serde_json::{json, Value};
use tempfile::TempDir;
use tokio::sync::mpsc;
use uuid::Uuid;

const TEAM: i32 = 7;
const PARTITION_ID: u16 = 0;
const BEHAVIORAL_HASH: [u8; 16] = *b"0123456789abcdef";
const DAY_MS: i64 = 86_400_000;
/// A window over 180 days routes `performed_event_multiple` to the compressed history variant.
const COMPRESSED_WINDOW_DAYS: i64 = 365;

fn temp_store() -> (TempDir, CohortStore) {
    let dir = TempDir::new().unwrap();
    let store = CohortStore::open(&StoreConfig {
        path: dir.path().join("db"),
        ..StoreConfig::default()
    })
    .expect("open store");
    (dir, store)
}

/// `All` mode so the worker and dispatcher exercise the blocking-pool transport; the raw store stays for seeding and assertions.
fn test_handle(store: &CohortStore) -> StoreHandle {
    test_handle_with_mode(store, OffloadMode::All)
}

fn test_handle_with_mode(store: &CohortStore, mode: OffloadMode) -> StoreHandle {
    StoreHandle::new(
        store.clone(),
        OffloadConfig {
            mode,
            event_read_permits: 16,
            maintenance_permits: 6,
        },
    )
}

fn behavioral_bytecode() -> Value {
    json!(["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11])
}

/// A `performed_event` leaf on `$pageview` with a tunable relative window (in days).
fn behavioral_leaf(window_days: i64) -> Value {
    json!({
        "type": "behavioral", "value": "performed_event", "key": "$pageview",
        "time_value": window_days, "time_interval": "day",
        "conditionHash": "0123456789abcdef",
        "bytecode": behavioral_bytecode(),
    })
}

/// A `performed_event` leaf over an explicit date range (so its eviction deadline is `i64::MAX`). The
/// lower bound is the space-separated ClickHouse shape; the upper bound is the real cohort-date-picker
/// wire shape (`dayjs(...).format('YYYY-MM-DDTHH:mm:ss')` — T-separated, no offset), so the test
/// exercises a format the UI actually emits rather than one only the old test fabricated.
fn explicit_behavioral_leaf() -> Value {
    explicit_behavioral_leaf_range("2026-01-01 00:00:00.000000", "2026-12-31T00:00:00")
}

fn explicit_behavioral_leaf_range(from: &str, to: &str) -> Value {
    json!({
        "type": "behavioral", "value": "performed_event", "key": "$pageview",
        "explicit_datetime": from,
        "explicit_datetime_to": to,
        "conditionHash": "0123456789abcdef",
        "bytecode": behavioral_bytecode(),
    })
}

/// A `performed_event_multiple` leaf: `<op> <value>` over a `window_days`-day window.
fn behavioral_leaf_multiple(window_days: i64, op: &str, value: i64) -> Value {
    json!({
        "type": "behavioral", "value": "performed_event_multiple", "key": "$pageview",
        "time_value": window_days, "time_interval": "day",
        "operator": op, "operator_value": value,
        "conditionHash": "0123456789abcdef",
        "bytecode": behavioral_bytecode(),
    })
}

/// A person-property leaf: `email == "u@p.com"`. Never time-evicted, so it pairs with a behavioral
/// leaf to make a composable (multi-leaf) cohort whose sweep flips must recompose Stage 2.
fn person_leaf() -> Value {
    json!({
        "type": "person", "key": "email", "value": "u@p.com", "operator": "exact",
        "conditionHash": "fedcba9876543210",
        "bytecode": ["_H", 1, 32, "u@p.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
    })
}

fn cohort(values: Vec<Value>) -> Value {
    json!({ "properties": { "type": "AND", "values": values } })
}

fn build_team_filters(leaves: Vec<Value>) -> TeamFilters {
    build_team_filters_multi(vec![(CohortId(1), leaves)])
}

fn build_team_filters_multi(cohorts: Vec<(CohortId, Vec<Value>)>) -> TeamFilters {
    let mut builder = TeamFiltersBuilder::default();
    for (id, leaves) in cohorts {
        builder
            .add_cohort(id, TeamId(TEAM), &cohort(leaves))
            .expect("add cohort");
    }
    builder.freeze(UTC)
}

/// A single-cohort catalog frozen under an explicit team timezone, so the sweep evicts at that zone's
/// local midnight rather than UTC's.
fn build_team_filters_tz(leaves: Vec<Value>, tz: Tz) -> TeamFilters {
    let mut builder = TeamFiltersBuilder::default();
    builder
        .add_cohort(CohortId(1), TeamId(TEAM), &cohort(leaves))
        .expect("add cohort");
    builder.freeze(tz)
}

fn catalog_of(filters: TeamFilters) -> Arc<CatalogHandle> {
    Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([(
        TeamId(TEAM),
        filters,
    )])))
}

fn person(n: u128) -> Uuid {
    Uuid::from_u128(n)
}

/// A matching `$pageview` event for `person` at `timestamp`.
fn event_at(person: Uuid, timestamp: &str, source_offset: i64) -> CohortStreamEvent {
    CohortStreamEvent {
        team_id: TEAM,
        person_id: person.to_string(),
        distinct_id: "d".to_string(),
        uuid: Uuid::from_u128(0xE0_0000 + source_offset as u128).to_string(),
        event: "$pageview".to_string(),
        timestamp: timestamp.to_string(),
        properties: Some("{}".to_string()),
        person_properties: None,
        elements_chain: None,
        source_offset,
        source_partition: 1,
        redirected_from: None,
        redirect_hops: 0,
    }
}

/// Like [`event_at`] but carrying the matching person properties, so one event flips a behavioral
/// and a person leaf together.
fn person_event_at(person: Uuid, timestamp: &str, source_offset: i64) -> CohortStreamEvent {
    CohortStreamEvent {
        person_properties: Some(r#"{"email":"u@p.com"}"#.to_string()),
        ..event_at(person, timestamp, source_offset)
    }
}

fn behavioral_lsk(filters: &TeamFilters) -> LeafStateKey {
    filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0]
}

/// The stored `cf_stage2` membership bit for `(cohort_id, person)`, or `None` when never evaluated.
fn stage2_bit(store: &CohortStore, cohort_id: u64, person: Uuid) -> Option<bool> {
    let key = Stage2Key {
        partition_id: PARTITION_ID,
        team_id: TEAM as u64,
        cohort_id,
        person_id: person,
    };
    store
        .get_stage2(&key)
        .unwrap()
        .map(|bytes| Stage2State::decode(&bytes).unwrap().in_cohort)
}

fn state_at(store: &CohortStore, lsk: LeafStateKey, person: Uuid) -> Option<Stage1State> {
    let key = BehavioralKey::new(PARTITION_ID, TEAM as u64, person, lsk);
    store
        .get_behavioral(&key)
        .unwrap()
        .map(|bytes| StatefulRecord::decode(&bytes).unwrap().state)
}

fn day_of(ts: &str) -> i32 {
    day_idx_in_tz(clickhouse_timestamp_to_millis(ts).unwrap(), UTC)
}

/// Raise the dispatch ceiling, then deliver one event to the worker (matching the dispatcher's
/// produce-before-commit ordering).
async fn send_event(
    tracker: &OffsetTracker,
    tx: &mpsc::Sender<Vec<ShuffleMessage>>,
    event: CohortStreamEvent,
    cse_offset: i64,
) {
    tracker.mark_dispatched(PARTITION_ID as i32, cse_offset + 1);
    tx.send(vec![ShuffleMessage::Event {
        event: Box::new(event),
        cse_offset,
    }])
    .await
    .unwrap();
}

async fn send_sweep(tx: &mpsc::Sender<Vec<ShuffleMessage>>, due_before_ms: i64) {
    tx.send(vec![ShuffleMessage::Sweep { due_before_ms }])
        .await
        .unwrap();
}

/// Poll `predicate` until it holds, so a test can observe intermediate mid-stream state without a
/// barrier. Store I/O runs on the blocking pool, so probes sleep (rather than yield-spin) to let that
/// wall-clock work land.
async fn drain_until(what: &str, mut predicate: impl FnMut() -> bool) {
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(30);
    while std::time::Instant::now() < deadline {
        if predicate() {
            return;
        }
        tokio::time::sleep(std::time::Duration::from_millis(1)).await;
    }
    panic!("timed out waiting for {what}");
}

/// [`drain_until`] on the sink's change count. `handle_sweep` produces before its state write, so a
/// test inspecting post-sweep state must follow this with a [`drain_until`] on the store itself.
async fn drain_until_changes(sink: &CaptureSink, count: usize) {
    drain_until("the worker to record changes", || {
        sink.changes().len() >= count
    })
    .await;
}

fn spawn_worker(
    store: &CohortStore,
    catalog: Arc<CatalogHandle>,
    sink: Arc<dyn MembershipSink>,
    tracker: Arc<OffsetTracker>,
) -> (mpsc::Sender<Vec<ShuffleMessage>>, Stage1Worker) {
    spawn_worker_with_restore(store, catalog, sink, tracker, false)
}

/// Like [`spawn_worker`] but with the durable-restart `EvictionQueue` rebuild on: the worker re-seeds
/// its queue from the partition's existing `cf_behavioral` on spawn.
fn spawn_worker_durable(
    store: &CohortStore,
    catalog: Arc<CatalogHandle>,
    sink: Arc<dyn MembershipSink>,
    tracker: Arc<OffsetTracker>,
) -> (mpsc::Sender<Vec<ShuffleMessage>>, Stage1Worker) {
    spawn_worker_with_restore(store, catalog, sink, tracker, true)
}

/// Like [`spawn_worker`] but pinned to a given offload mode instead of the default `All`.
fn spawn_worker_with_mode(
    store: &CohortStore,
    catalog: Arc<CatalogHandle>,
    sink: Arc<dyn MembershipSink>,
    tracker: Arc<OffsetTracker>,
    mode: OffloadMode,
) -> (mpsc::Sender<Vec<ShuffleMessage>>, Stage1Worker) {
    let (tx, rx) = mpsc::channel(16);
    let rx = MeteredReceiver::unmetered(rx);
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        test_handle_with_mode(store, mode),
        catalog,
        sink,
        tracker,
        MergeWorkerDeps::capture(),
        false,
    );
    (tx, worker)
}

fn spawn_worker_with_restore(
    store: &CohortStore,
    catalog: Arc<CatalogHandle>,
    sink: Arc<dyn MembershipSink>,
    tracker: Arc<OffsetTracker>,
    durable_restore: bool,
) -> (mpsc::Sender<Vec<ShuffleMessage>>, Stage1Worker) {
    let (tx, rx) = mpsc::channel(16);
    let rx = MeteredReceiver::unmetered(rx);
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        test_handle(store),
        catalog,
        sink,
        tracker,
        MergeWorkerDeps::capture(),
        durable_restore,
    );
    (tx, worker)
}

#[tokio::test]
async fn sweep_evicts_a_single_leaf_member_emits_left_and_deletes() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf(7)]);
    let lsk = behavioral_lsk(&filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";
    let event_ms = clickhouse_timestamp_to_millis(ts).unwrap();
    let deadline = event_ms + 7 * DAY_MS;

    // The matching event enters the cohort and schedules the eviction for `deadline`.
    send_event(&tracker, &tx, event_at(alice, ts, 0), 0).await;
    // A sweep whose cutoff is past the deadline pops the key: the window expired → the member leaves.
    send_sweep(&tx, deadline + DAY_MS).await;
    drop(tx);
    worker.join().await.unwrap();

    let changes = sink.changes();
    assert_eq!(changes.len(), 2, "an Entered (event) then a Left (sweep)");
    assert_eq!(changes[0].status, MembershipStatus::Entered);
    assert_eq!(changes[1].status, MembershipStatus::Left);
    assert_eq!(changes[1].cohort_id, 1);
    assert_eq!(changes[1].person_id, alice.to_string());
    assert!(
        state_at(&store, lsk, alice).is_none(),
        "a fully-expired single is deleted",
    );
}

#[tokio::test]
async fn durable_restart_rebuilds_the_eviction_queue_so_a_dormant_left_still_fires() {
    // A member whose window expires during downtime — with no new event to reschedule her — must still
    // emit `Left`. The first worker enters alice and schedules her eviction in its in-memory queue,
    // then "crashes" (drop loses the queue, but cf_behavioral persists); a durable-restart worker re-seeds
    // its queue from cf_behavioral, so a later sweep still evicts her.
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf(7)]);
    let lsk = behavioral_lsk(&filters);
    let catalog = catalog_of(filters);
    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";

    // First tenure: alice enters; her state + deadline persist to cf_behavioral.
    let sink1 = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx1, worker1) = spawn_worker(
        &store,
        catalog.clone(),
        Arc::new(sink1.clone()),
        tracker.clone(),
    );
    send_event(&tracker, &tx1, event_at(alice, ts, 0), 0).await;
    drop(tx1);
    worker1.join().await.unwrap();
    assert_eq!(sink1.changes().len(), 1, "first tenure: just the Entered");
    let deadline = state_at(&store, lsk, alice)
        .expect("alice's state persisted across the crash")
        .eviction_deadline()
        .expect("a behavioral single has a finite eviction deadline");

    // Second tenure: the durable-restart worker rebuilds its queue; alice sends no new event, yet the
    // sweep past her deadline still evicts her.
    let sink2 = CaptureSink::new();
    let (tx2, worker2) =
        spawn_worker_durable(&store, catalog, Arc::new(sink2.clone()), tracker.clone());
    send_sweep(&tx2, deadline + DAY_MS).await;
    drop(tx2);
    worker2.join().await.unwrap();

    let changes = sink2.changes();
    assert_eq!(changes.len(), 1, "the rebuilt queue fires exactly one Left");
    assert_eq!(changes[0].status, MembershipStatus::Left);
    assert_eq!(changes[0].cohort_id, 1);
    assert_eq!(changes[0].person_id, alice.to_string());
    assert!(
        state_at(&store, lsk, alice).is_none(),
        "the fully-expired single is deleted by the sweep",
    );
}

#[tokio::test]
async fn without_durable_restart_a_dormant_member_is_not_re_evicted() {
    // The contrast: without the rebuild the worker's queue starts empty, so the dormant member is never
    // re-evaluated and no `Left` fires (the over-count the rebuild closes).
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf(7)]);
    let lsk = behavioral_lsk(&filters);
    let catalog = catalog_of(filters);
    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";

    let sink1 = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx1, worker1) = spawn_worker(
        &store,
        catalog.clone(),
        Arc::new(sink1.clone()),
        tracker.clone(),
    );
    send_event(&tracker, &tx1, event_at(alice, ts, 0), 0).await;
    drop(tx1);
    worker1.join().await.unwrap();
    let deadline = state_at(&store, lsk, alice)
        .unwrap()
        .eviction_deadline()
        .unwrap();

    // A plain (non-durable) restart worker: queue starts empty, so the sweep pops nothing.
    let sink2 = CaptureSink::new();
    let (tx2, worker2) = spawn_worker(&store, catalog, Arc::new(sink2.clone()), tracker.clone());
    send_sweep(&tx2, deadline + DAY_MS).await;
    drop(tx2);
    worker2.join().await.unwrap();

    assert!(
        sink2.changes().is_empty(),
        "without the rebuild the dormant member's Left never fires",
    );
    assert!(
        state_at(&store, lsk, alice).is_some(),
        "and her now-stale state lingers (the over-count)",
    );
}

#[tokio::test]
async fn event_then_sweep_in_one_batch_emits_entered_before_left() {
    // Regression: event-path changes accumulate in the buffer and were produced *after* the message
    // loop, while the Sweep arm produces inline mid-loop. So a single `[Event, Sweep]` batch where the
    // event enters then the sweep immediately ages it out used to emit `Left` (inline) before `Entered`
    // (post-loop) — out of state-commit order. A last-write-wins consumer of the shadow topic would then
    // read "member" while RocksDB says "left", a false parity mismatch. The buffer is now flushed before
    // the Sweep arm, so produce order matches commit order: Entered then Left.
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf(7)]);
    let lsk = behavioral_lsk(&filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";
    let event_ms = clickhouse_timestamp_to_millis(ts).unwrap();
    let deadline = event_ms + 7 * DAY_MS;

    // One batch: the event enters and schedules eviction at `deadline`; the sweep's cutoff is already
    // past it, so the same batch ages the key out. The fix must order Entered (event) before Left (sweep).
    tracker.mark_dispatched(PARTITION_ID as i32, 1);
    tx.send(vec![
        ShuffleMessage::Event {
            event: Box::new(event_at(alice, ts, 0)),
            cse_offset: 0,
        },
        ShuffleMessage::Sweep {
            due_before_ms: deadline + DAY_MS,
        },
    ])
    .await
    .unwrap();
    drop(tx);
    worker.join().await.unwrap();

    let statuses: Vec<MembershipStatus> =
        sink.changes().iter().map(|change| change.status).collect();
    assert_eq!(
        statuses,
        vec![MembershipStatus::Entered, MembershipStatus::Left],
        "within one batch the event's Entered must be produced before the sweep's inline Left",
    );
    assert!(
        state_at(&store, lsk, alice).is_none(),
        "the fully-expired single is deleted by the in-batch sweep",
    );
    assert_eq!(
        tracker.committable_offsets().get(&(PARTITION_ID as i32)),
        Some(&1),
        "both produces acked, so the batch's offset advances past the event",
    );
}

#[tokio::test]
async fn sweep_full_expiry_delete_retracts_the_person_index_entry() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf(7)]);
    let lsk = behavioral_lsk(&filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";
    let event_ms = clickhouse_timestamp_to_millis(ts).unwrap();
    let deadline = event_ms + 7 * DAY_MS;

    send_event(&tracker, &tx, event_at(alice, ts, 0), 0).await;
    // Wait for the Entered to land, so the event's cf_behavioral WriteBatch is durable.
    drain_until_changes(&sink, 1).await;

    // Sweep past the deadline: the single fully expires (Delete), removing the behavioral row.
    send_sweep(&tx, deadline + DAY_MS).await;
    drop(tx);
    worker.join().await.unwrap();

    assert!(
        state_at(&store, lsk, alice).is_none(),
        "the expired single's cf_behavioral row is gone",
    );
}

#[tokio::test]
async fn sweep_before_the_deadline_evicts_nothing() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf(7)]);
    let lsk = behavioral_lsk(&filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";
    let event_ms = clickhouse_timestamp_to_millis(ts).unwrap();

    send_event(&tracker, &tx, event_at(alice, ts, 0), 0).await;
    // Cutoff one day *before* the deadline: nothing is due.
    send_sweep(&tx, event_ms + 6 * DAY_MS).await;
    drop(tx);
    worker.join().await.unwrap();

    let changes = sink.changes();
    assert_eq!(changes.len(), 1, "only the Entered, no premature Left");
    assert_eq!(changes[0].status, MembershipStatus::Entered);
    assert!(
        state_at(&store, lsk, alice).is_some(),
        "state survives a sweep before its deadline",
    );
}

#[tokio::test]
async fn sweep_on_an_empty_queue_is_a_noop() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf(7)]);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    // A sweep with no scheduled keys yet: nothing pops, nothing produces.
    send_sweep(&tx, i64::MAX).await;
    drop(tx);
    worker.join().await.unwrap();

    assert!(
        sink.changes().is_empty(),
        "an empty-queue sweep emits nothing"
    );
    assert!(
        !tracker
            .committable_offsets()
            .contains_key(&(PARTITION_ID as i32)),
        "a sweep-only batch advances no offset",
    );
}

#[tokio::test]
async fn sweep_caps_evictions_per_pass_and_drains_the_remainder_next_tick() {
    // A large wave of single-leaf members all come due at one cutoff. `handle_sweep` caps the pop loop
    // at `MAX_SWEEP_KEYS_PER_PASS` (10_000, private to the worker), so the first pass evicts exactly the
    // cap and the leftover keys stay scheduled, draining on a second sweep. This bounds the per-pass
    // RocksDB read + produce + write batch so events do not starve behind one giant sweep.
    const CAP: usize = 10_000; // mirrors worker::MAX_SWEEP_KEYS_PER_PASS
    let total = CAP + 1;

    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf(7)]);
    let lsk = behavioral_lsk(&filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let ts = "2026-05-20 10:00:00.000000";
    let event_ms = clickhouse_timestamp_to_millis(ts).unwrap();
    let deadline = event_ms + 7 * DAY_MS;

    // One batch of `total` matching events (one distinct person each) schedules `total` evictions, all
    // due at the same deadline. Batching avoids `total` per-event async round-trips through the channel.
    tracker.mark_dispatched(PARTITION_ID as i32, total as i64);
    let events: Vec<ShuffleMessage> = (0..total)
        .map(|i| ShuffleMessage::Event {
            event: Box::new(event_at(person(i as u128 + 1), ts, i as i64)),
            cse_offset: i as i64,
        })
        .collect();
    tx.send(events).await.unwrap();
    drain_until_changes(&sink, total).await; // all `total` Entered have landed.

    // First sweep past the deadline: every key is due, but only `CAP` are popped this pass.
    send_sweep(&tx, deadline + DAY_MS).await;
    drain_until_changes(&sink, total + CAP).await;
    let lefts_after_first = sink
        .changes()
        .iter()
        .filter(|c| c.status == MembershipStatus::Left)
        .count();
    assert_eq!(
        lefts_after_first, CAP,
        "the first pass evicts exactly the per-pass cap, not the whole wave",
    );
    // The one capped-out key is still scheduled, so its state still exists.
    let leftover_person = person(total as u128); // offset total-1 ⇒ person `total`
    assert!(
        state_at(&store, lsk, leftover_person).is_some(),
        "the over-cap key was not popped, so its state is untouched after the first pass",
    );

    // Second sweep at the same cutoff drains the leftover.
    send_sweep(&tx, deadline + DAY_MS).await;
    drain_until_changes(&sink, total + total).await;
    drop(tx);
    worker.join().await.unwrap();

    let total_lefts = sink
        .changes()
        .iter()
        .filter(|c| c.status == MembershipStatus::Left)
        .count();
    assert_eq!(
        total_lefts, total,
        "the remaining over-cap key evicts on the next tick: all members eventually leave",
    );
    assert!(
        state_at(&store, lsk, leftover_person).is_none(),
        "the leftover key is evicted (deleted) by the second sweep",
    );
}

#[tokio::test]
async fn single_does_not_evict_before_its_calendar_midnight_and_does_after() {
    let lsk = behavioral_lsk(&build_team_filters_tz(vec![behavioral_leaf(7)], Kolkata));
    let alice = person(1);
    let bob = person(2);
    // 00:30 and 23:30 Kolkata local on 2026-05-20, expressed in UTC (−05:30) → one Kolkata day.
    let early = "2026-05-19 19:00:00.000000"; // 00:30 next-day Kolkata
    let late = "2026-05-20 18:00:00.000000"; // 23:30 same-day Kolkata
    let kolkata_day = day_idx_in_tz(clickhouse_timestamp_to_millis(early).unwrap(), Kolkata);
    let midnight = start_of_day_ms_in_tz(kolkata_day + 7 + 1, Kolkata);
    assert_ne!(
        midnight,
        start_of_day_ms_in_tz(kolkata_day + 7 + 1, UTC),
        "the eviction boundary is the team-local (Kolkata) midnight, not UTC's",
    );

    // A sweep exactly at the shared midnight evicts neither edge person.
    {
        let (_dir, store) = temp_store();
        let sink = CaptureSink::new();
        let tracker = Arc::new(OffsetTracker::new());
        let (tx, worker) = spawn_worker(
            &store,
            catalog_of(build_team_filters_tz(vec![behavioral_leaf(7)], Kolkata)),
            Arc::new(sink.clone()),
            tracker.clone(),
        );
        send_event(&tracker, &tx, event_at(alice, early, 0), 0).await;
        send_event(&tracker, &tx, event_at(bob, late, 1), 1).await;
        send_sweep(&tx, midnight).await;
        drop(tx);
        worker.join().await.unwrap();

        let changes = sink.changes();
        assert_eq!(
            changes.len(),
            2,
            "two Entered, no premature Left at the exact midnight",
        );
        assert!(changes
            .iter()
            .all(|c| c.status == MembershipStatus::Entered));
        assert!(state_at(&store, lsk, alice).is_some());
        assert!(state_at(&store, lsk, bob).is_some());
    }

    // One ms past the shared midnight evicts both edge persons in the same tick.
    {
        let (_dir, store) = temp_store();
        let sink = CaptureSink::new();
        let tracker = Arc::new(OffsetTracker::new());
        let (tx, worker) = spawn_worker(
            &store,
            catalog_of(build_team_filters_tz(vec![behavioral_leaf(7)], Kolkata)),
            Arc::new(sink.clone()),
            tracker.clone(),
        );
        send_event(&tracker, &tx, event_at(alice, early, 0), 0).await;
        send_event(&tracker, &tx, event_at(bob, late, 1), 1).await;
        send_sweep(&tx, midnight + 1).await;
        drop(tx);
        worker.join().await.unwrap();

        let lefts = sink
            .changes()
            .iter()
            .filter(|c| c.status == MembershipStatus::Left)
            .count();
        assert_eq!(
            lefts, 2,
            "both edge persons leave in the same tick one ms past midnight",
        );
        assert!(state_at(&store, lsk, alice).is_none());
        assert!(state_at(&store, lsk, bob).is_none());
    }
}

#[tokio::test]
async fn sweep_evicts_a_daily_member_on_full_window_expiry() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf_multiple(7, "gte", 3)]);
    let lsk = behavioral_lsk(&filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";
    let day = day_of(ts);

    // Three same-day matches cross gte 3 → Entered on the third.
    for offset in 0..3 {
        send_event(&tracker, &tx, event_at(alice, ts, offset), offset).await;
    }
    // Slide the window well past the lone bucket → every bucket drains → Left + delete.
    send_sweep(&tx, start_of_day_ms_in_tz(day + 9, UTC)).await;
    drop(tx);
    worker.join().await.unwrap();

    let changes = sink.changes();
    assert_eq!(
        changes.len(),
        2,
        "one Entered (3rd event) then one Left (sweep)"
    );
    assert_eq!(changes[0].status, MembershipStatus::Entered);
    assert_eq!(changes[1].status, MembershipStatus::Left);
    assert!(
        state_at(&store, lsk, alice).is_none(),
        "an all-zero daily window is deleted",
    );
}

#[tokio::test]
async fn sweep_drops_the_oldest_daily_bucket_and_keeps_a_member() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf_multiple(7, "gte", 1)]);
    let lsk = behavioral_lsk(&filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    // Matches four days apart, both inside a 7-day window. The first crosses gte 1 (Entered).
    let first = "2026-05-20 10:00:00.000000";
    let second = "2026-05-24 10:00:00.000000";
    let day_first = day_of(first);
    send_event(&tracker, &tx, event_at(alice, first, 0), 0).await;
    send_event(&tracker, &tx, event_at(alice, second, 1), 1).await;

    // Slide so only the first day's bucket leaves; the later bucket keeps the person a member.
    send_sweep(&tx, start_of_day_ms_in_tz(day_first + 9, UTC)).await;
    drop(tx);
    worker.join().await.unwrap();

    let changes = sink.changes();
    assert_eq!(
        changes.len(),
        1,
        "Entered only — dropping the oldest bucket emits no Left"
    );
    assert_eq!(changes[0].status, MembershipStatus::Entered);

    // The state survives with the later bucket's single match and a deadline pushed forward.
    match state_at(&store, lsk, alice).expect("still a member") {
        Stage1State::BehavioralDailyBuckets {
            buckets,
            earliest_eviction_at_ms,
            ..
        } => {
            assert_eq!(
                buckets.iter().sum::<u32>(),
                1,
                "only the later bucket remains"
            );
            let day_second = day_of(second);
            assert_eq!(
                earliest_eviction_at_ms,
                start_of_day_ms_in_tz(day_second + 7 + 1, UTC),
                "the deadline now tracks the surviving bucket",
            );
        }
        other => panic!("expected daily buckets, got {other:?}"),
    }
}

#[tokio::test]
async fn sweep_emits_entered_when_a_daily_eq_count_falls_into_range() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf_multiple(7, "eq", 1)]);
    let lsk = behavioral_lsk(&filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    // `eq 1` over a 7-day window, one match on day D and one on D+3. The event path emits Enter@D
    // (count 1) then Leave@D+3 (count 2); as each day's bucket ages out, the falling count re-enters
    // and finally leaves `eq 1`. The sweep must reproduce both directions, not only the Leave — this
    // is the bidirectional flip a `gte`-only sweep would have dropped.
    let alice = person(1);
    let first = "2026-05-20 10:00:00.000000";
    let second = "2026-05-23 10:00:00.000000";
    let day = day_of(first);
    send_event(&tracker, &tx, event_at(alice, first, 0), 0).await;
    send_event(&tracker, &tx, event_at(alice, second, 1), 1).await;

    // Sweep one day past the day-D bucket's leave boundary (start of D+8): count 2 → 1 → Entered.
    send_sweep(&tx, start_of_day_ms_in_tz(day + 9, UTC)).await;

    // Barrier on the Enter+Leave (events) + Enter (sweep): the slide advanced the window and
    // rescheduled to the surviving D+3 bucket's leave boundary (start of D+11). The sweep produces
    // before its state write, so also wait for the slid record itself.
    drain_until_changes(&sink, 3).await;
    drain_until("the slid daily record to land", || {
        matches!(
            state_at(&store, lsk, alice),
            Some(Stage1State::BehavioralDailyBuckets { ref buckets, .. })
                if buckets.iter().sum::<u32>() == 1
        )
    })
    .await;
    match state_at(&store, lsk, alice).expect("still a member after the slide into eq 1") {
        Stage1State::BehavioralDailyBuckets {
            buckets,
            earliest_eviction_at_ms,
            ..
        } => {
            assert_eq!(
                buckets.iter().sum::<u32>(),
                1,
                "only the D+3 bucket remains"
            );
            assert_eq!(
                earliest_eviction_at_ms,
                start_of_day_ms_in_tz(day + 11, UTC),
                "rescheduled to the surviving bucket's leave boundary",
            );
        }
        other => panic!("expected daily buckets, got {other:?}"),
    }

    // A later sweep past the D+3 bucket's boundary (start of D+12): count 1 → 0 → Left + delete.
    send_sweep(&tx, start_of_day_ms_in_tz(day + 12, UTC)).await;
    drop(tx);
    worker.join().await.unwrap();

    let statuses: Vec<MembershipStatus> =
        sink.changes().iter().map(|change| change.status).collect();
    assert_eq!(
        statuses,
        vec![
            MembershipStatus::Entered, // event @ D    — count 1
            MembershipStatus::Left,    // event @ D+3  — count 2
            MembershipStatus::Entered, // sweep        — day-D bucket leaves, count 1
            MembershipStatus::Left,    // sweep        — day-(D+3) bucket leaves, count 0
        ],
        "the sweep reproduces the event path's bidirectional eq-1 flips, not an orphan Left",
    );
    assert!(
        state_at(&store, lsk, alice).is_none(),
        "the fully-drained window is deleted",
    );
}

#[tokio::test]
async fn sweep_evicts_a_compressed_member_on_full_window_expiry() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf_multiple(
        COMPRESSED_WINDOW_DAYS,
        "gte",
        3,
    )]);
    let lsk = behavioral_lsk(&filters);
    assert_eq!(
        filters.by_lsk[&lsk].variant,
        StateVariant::BehavioralCompressedHistory,
    );
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";
    let day = day_of(ts);

    // Three same-day matches cross gte 3 → Entered on the third.
    for offset in 0..3 {
        send_event(&tracker, &tx, event_at(alice, ts, offset), offset).await;
    }
    // Slide the window well past the lone entry → it drains → Left + delete.
    send_sweep(
        &tx,
        start_of_day_ms_in_tz(day + COMPRESSED_WINDOW_DAYS as i32 + 2, UTC),
    )
    .await;
    drop(tx);
    worker.join().await.unwrap();

    let changes = sink.changes();
    assert_eq!(
        changes.len(),
        2,
        "one Entered (3rd event) then one Left (sweep)"
    );
    assert_eq!(changes[0].status, MembershipStatus::Entered);
    assert_eq!(changes[1].status, MembershipStatus::Left);
    assert!(
        state_at(&store, lsk, alice).is_none(),
        "a fully-drained compressed window is deleted",
    );
}

#[tokio::test]
async fn sweep_drops_the_oldest_compressed_day_and_keeps_a_member() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf_multiple(
        COMPRESSED_WINDOW_DAYS,
        "gte",
        1,
    )]);
    let lsk = behavioral_lsk(&filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    // Matches 100 days apart, both inside a 365-day window. The first crosses gte 1 (Entered).
    let first = "2026-05-20 10:00:00.000000";
    let second = "2026-08-28 10:00:00.000000";
    let day_first = day_of(first);
    let day_second = day_of(second);
    send_event(&tracker, &tx, event_at(alice, first, 0), 0).await;
    send_event(&tracker, &tx, event_at(alice, second, 1), 1).await;

    // Slide so only the first day's entry leaves; the later entry keeps the person a member.
    send_sweep(
        &tx,
        start_of_day_ms_in_tz(day_first + COMPRESSED_WINDOW_DAYS as i32 + 2, UTC),
    )
    .await;
    drop(tx);
    worker.join().await.unwrap();

    let changes = sink.changes();
    assert_eq!(
        changes.len(),
        1,
        "Entered only — dropping the oldest day emits no Left"
    );
    assert_eq!(changes[0].status, MembershipStatus::Entered);

    // The state survives with the later day's single match and a deadline pushed forward.
    match state_at(&store, lsk, alice).expect("still a member") {
        Stage1State::BehavioralCompressedHistory {
            entries,
            earliest_eviction_at_ms,
            ..
        } => {
            assert_eq!(
                entries,
                vec![(day_second, 1)],
                "only the later day's entry remains",
            );
            assert_eq!(
                earliest_eviction_at_ms,
                start_of_day_ms_in_tz(day_second + COMPRESSED_WINDOW_DAYS as i32 + 1, UTC),
                "the deadline now tracks the surviving entry",
            );
        }
        other => panic!("expected compressed history, got {other:?}"),
    }
}

#[tokio::test]
async fn sweep_emits_entered_when_a_compressed_eq_count_falls_into_range() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf_multiple(
        COMPRESSED_WINDOW_DAYS,
        "eq",
        1,
    )]);
    let lsk = behavioral_lsk(&filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    // `eq 1` over a 365-day window, one match on day D and one on D+100. The event path emits Enter@D
    // (count 1) then Leave@D+100 (count 2); as each day's entry ages out, the falling count re-enters
    // and finally leaves `eq 1`. The sweep must reproduce both directions — the bidirectional flip a
    // `gte`-only sweep would have dropped.
    let alice = person(1);
    let first = "2026-05-20 10:00:00.000000";
    let second = "2026-08-28 10:00:00.000000";
    let day_first = day_of(first);
    let day_second = day_of(second);
    send_event(&tracker, &tx, event_at(alice, first, 0), 0).await;
    send_event(&tracker, &tx, event_at(alice, second, 1), 1).await;

    // Sweep past the day-D entry's leave boundary: count 2 → 1 → Entered, rescheduled to the surviving
    // D+100 entry's leave boundary.
    send_sweep(
        &tx,
        start_of_day_ms_in_tz(day_first + COMPRESSED_WINDOW_DAYS as i32 + 2, UTC),
    )
    .await;

    // The sweep produces before its state write, so also wait for the slid record before inspecting it.
    drain_until_changes(&sink, 3).await;
    drain_until("the slid compressed record to land", || {
        matches!(
            state_at(&store, lsk, alice),
            Some(Stage1State::BehavioralCompressedHistory { ref entries, .. })
                if entries.len() == 1
        )
    })
    .await;
    match state_at(&store, lsk, alice).expect("still a member after the slide into eq 1") {
        Stage1State::BehavioralCompressedHistory {
            entries,
            earliest_eviction_at_ms,
            ..
        } => {
            assert_eq!(
                entries,
                vec![(day_second, 1)],
                "only the D+100 entry remains"
            );
            assert_eq!(
                earliest_eviction_at_ms,
                start_of_day_ms_in_tz(day_second + COMPRESSED_WINDOW_DAYS as i32 + 1, UTC),
                "rescheduled to the surviving entry's leave boundary",
            );
        }
        other => panic!("expected compressed history, got {other:?}"),
    }

    // A later sweep past the D+100 entry's boundary: count 1 → 0 → Left + delete.
    send_sweep(
        &tx,
        start_of_day_ms_in_tz(day_second + COMPRESSED_WINDOW_DAYS as i32 + 2, UTC),
    )
    .await;
    drop(tx);
    worker.join().await.unwrap();

    let statuses: Vec<MembershipStatus> =
        sink.changes().iter().map(|change| change.status).collect();
    assert_eq!(
        statuses,
        vec![
            MembershipStatus::Entered, // event @ D     — count 1
            MembershipStatus::Left,    // event @ D+100 — count 2
            MembershipStatus::Entered, // sweep         — day-D entry leaves, count 1
            MembershipStatus::Left,    // sweep         — day-(D+100) entry leaves, count 0
        ],
        "the sweep reproduces the event path's bidirectional eq-1 flips for the compressed variant",
    );
    assert!(
        state_at(&store, lsk, alice).is_none(),
        "the fully-drained compressed window is deleted",
    );
}

/// A sink that fails the `fail_call`-th produce (1-based).
#[derive(Clone)]
struct FailNthSink {
    changes: Arc<Mutex<Vec<CohortMembershipChange>>>,
    calls: Arc<AtomicUsize>,
    fail_call: usize,
}

impl FailNthSink {
    fn new(fail_call: usize) -> Self {
        Self {
            changes: Arc::default(),
            calls: Arc::default(),
            fail_call,
        }
    }

    fn changes(&self) -> Vec<CohortMembershipChange> {
        self.changes.lock().unwrap().clone()
    }

    fn calls(&self) -> usize {
        self.calls.load(Ordering::SeqCst)
    }
}

async fn drain_until_calls(sink: &FailNthSink, count: usize) {
    for _ in 0..10_000 {
        if sink.calls() >= count {
            return;
        }
        tokio::task::yield_now().await;
    }
    panic!("worker did not reach {count} produce calls");
}

#[async_trait]
impl MembershipSink for FailNthSink {
    async fn produce(
        &self,
        changes: Vec<CohortMembershipChange>,
    ) -> Vec<Result<(), KafkaProduceError>> {
        let call = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
        if call == self.fail_call {
            return changes
                .iter()
                .map(|_| Err(KafkaProduceError::KafkaProduceCanceled))
                .collect();
        }
        let acks = changes.iter().map(|_| Ok(())).collect();
        self.changes.lock().unwrap().extend(changes);
        acks
    }
}

#[tokio::test]
async fn sweep_produce_failure_reschedules_and_a_later_sweep_retries() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf(7)]);
    let lsk = behavioral_lsk(&filters);
    let sink = FailNthSink::new(2);
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";
    let event_ms = clickhouse_timestamp_to_millis(ts).unwrap();
    let cutoff = event_ms + 8 * DAY_MS;

    send_event(&tracker, &tx, event_at(alice, ts, 0), 0).await;
    // First sweep: the Left produce fails → the key is rescheduled, the state is NOT deleted.
    send_sweep(&tx, cutoff).await;
    // Second sweep at the same cutoff: the rescheduled key re-pops and the retry succeeds.
    send_sweep(&tx, cutoff).await;
    drop(tx);
    worker.join().await.unwrap();

    let changes = sink.changes();
    assert_eq!(
        changes.len(),
        2,
        "Entered + the retried Left (the failed flush recorded nothing)",
    );
    assert_eq!(changes[0].status, MembershipStatus::Entered);
    assert_eq!(changes[1].status, MembershipStatus::Left);
    assert!(
        state_at(&store, lsk, alice).is_none(),
        "the retry deleted the state once its Left was durable",
    );
}

#[tokio::test]
async fn sweep_left_recomposes_a_two_leaf_cohort() {
    let (_dir, store) = temp_store();
    // A composable cohort: AND(behavioral 7d, person email). Neither leaf is owned by a single-leaf
    // cohort, so every change below comes from Stage 2 composition.
    let filters = build_team_filters(vec![behavioral_leaf(7), person_leaf()]);
    let lsk = behavioral_lsk(&filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";
    let event_ms = clickhouse_timestamp_to_millis(ts).unwrap();

    // One matching event flips both leaves → the cohort composes an Entered.
    send_event(&tracker, &tx, person_event_at(alice, ts, 0), 0).await;
    // The sweep expires the behavioral window; its time-driven Left must recompose the cohort even
    // though the sibling person leaf (never time-evicted) is still true.
    send_sweep(&tx, event_ms + 8 * DAY_MS).await;
    drop(tx);
    worker.join().await.unwrap();

    let emitted: Vec<(i32, MembershipStatus)> = sink
        .changes()
        .iter()
        .map(|change| (change.cohort_id, change.status))
        .collect();
    assert_eq!(
        emitted,
        vec![(1, MembershipStatus::Entered), (1, MembershipStatus::Left)],
        "the sweep's leaf Left recomposes the two-leaf cohort to a cohort Left",
    );
    assert!(
        state_at(&store, lsk, alice).is_none(),
        "the expired behavioral leaf was deleted before compose read it",
    );
    assert_eq!(
        stage2_bit(&store, 1, alice),
        Some(false),
        "a composed Left writes the false bit, it does not delete the row",
    );
}

#[tokio::test]
async fn sweep_entered_recomposes_via_daily_slide() {
    let (_dir, store) = temp_store();
    // AND(daily eq 1 over 7d, person email): the behavioral leaf is a member only at exactly one
    // match in the window.
    let filters = build_team_filters(vec![behavioral_leaf_multiple(7, "eq", 1), person_leaf()]);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    let first = "2026-05-20 10:00:00.000000";
    let second = "2026-05-23 10:00:00.000000";
    let day = day_of(first);

    // Count 1 @ D satisfies eq 1 (cohort Entered); count 2 @ D+3 fails it (cohort Left).
    send_event(&tracker, &tx, person_event_at(alice, first, 0), 0).await;
    send_event(&tracker, &tx, person_event_at(alice, second, 1), 1).await;
    // The slide drops the day-D bucket: count 2 → 1 re-enters eq 1, so the sweep's *Entered* must
    // drive a recompose exactly like a Left does.
    send_sweep(&tx, start_of_day_ms_in_tz(day + 9, UTC)).await;
    drop(tx);
    worker.join().await.unwrap();

    let statuses: Vec<MembershipStatus> =
        sink.changes().iter().map(|change| change.status).collect();
    assert_eq!(
        statuses,
        vec![
            MembershipStatus::Entered, // event @ D   — count 1, the AND is satisfied
            MembershipStatus::Left,    // event @ D+3 — count 2 fails eq 1
            MembershipStatus::Entered, // sweep       — the day-D bucket leaves, count back to 1
        ],
        "a sweep Entered (daily slide into range) recomposes the cohort, not only a Left",
    );
    assert_eq!(stage2_bit(&store, 1, alice), Some(true));
}

#[tokio::test]
async fn sweep_dormant_person_left_is_emitted() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf(7), person_leaf()]);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    // Alice enters and goes dormant — no event of hers ever drives a recompose again. Bob stays
    // active, superseding his own deadline past the sweep. Only the sweep can emit alice's Left
    // (the staleness invariant for a churned-then-dormant person).
    let alice = person(1);
    let bob = person(2);
    let t0 = "2026-05-20 10:00:00.000000";
    let t0_ms = clickhouse_timestamp_to_millis(t0).unwrap();
    send_event(&tracker, &tx, person_event_at(alice, t0, 0), 0).await;
    send_event(&tracker, &tx, person_event_at(bob, t0, 1), 1).await;
    send_event(
        &tracker,
        &tx,
        person_event_at(bob, "2026-05-26 10:00:00.000000", 2),
        2,
    )
    .await;

    send_sweep(&tx, t0_ms + 8 * DAY_MS).await;
    drop(tx);
    worker.join().await.unwrap();

    let changes = sink.changes();
    let lefts: Vec<_> = changes
        .iter()
        .filter(|change| change.status == MembershipStatus::Left)
        .collect();
    assert_eq!(lefts.len(), 1, "the sweep alone drives exactly one Left");
    assert_eq!(lefts[0].person_id, alice.to_string());
    assert_eq!(lefts[0].cohort_id, 1);
    assert_eq!(stage2_bit(&store, 1, alice), Some(false));
    assert_eq!(
        stage2_bit(&store, 1, bob),
        Some(true),
        "the still-active person is untouched by the dormant person's eviction",
    );
}

#[tokio::test]
async fn sweep_recompose_and_single_leaf_share_a_leaf() {
    let (_dir, store) = temp_store();
    // Cohort 1 ANDs the behavioral leaf with a person leaf (composable); cohort 2 is the bare
    // behavioral leaf (single-leaf), sharing cohort 1's LSK. One eviction must emit both cohorts'
    // Lefts — cohort 2 via map_transition (first produce), cohort 1 via compose (second produce) —
    // disjoint cohort ids, each exactly once.
    let filters = build_team_filters_multi(vec![
        (CohortId(1), vec![behavioral_leaf(7), person_leaf()]),
        (CohortId(2), vec![behavioral_leaf(7)]),
    ]);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";
    let event_ms = clickhouse_timestamp_to_millis(ts).unwrap();

    send_event(&tracker, &tx, person_event_at(alice, ts, 0), 0).await;
    send_sweep(&tx, event_ms + 8 * DAY_MS).await;
    drop(tx);
    worker.join().await.unwrap();

    let by_status = |status: MembershipStatus| -> Vec<i32> {
        let mut cohorts: Vec<i32> = sink
            .changes()
            .iter()
            .filter(|change| change.status == status)
            .map(|change| change.cohort_id)
            .collect();
        cohorts.sort_unstable();
        cohorts
    };
    assert_eq!(
        by_status(MembershipStatus::Entered),
        vec![1, 2],
        "the event enters the single-leaf cohort and composes the two-leaf cohort",
    );
    assert_eq!(
        by_status(MembershipStatus::Left),
        vec![1, 2],
        "one eviction fans out to the single-leaf Left and the composed Left, each exactly once",
    );
    assert_eq!(stage2_bit(&store, 1, alice), Some(false));
}

#[tokio::test]
async fn sweep_two_leaves_same_cohort_one_tick() {
    let (_dir, store) = temp_store();
    // AND of a 7d and a 30d performed_event on one matcher: a single event enters both leaves, and
    // a far-future sweep pops both windows in one tick — two transitions for one (cohort, person).
    let filters = build_team_filters(vec![behavioral_leaf(7), behavioral_leaf(30)]);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";
    let event_ms = clickhouse_timestamp_to_millis(ts).unwrap();

    send_event(&tracker, &tx, event_at(alice, ts, 0), 0).await;
    // Both deadlines (event+7d, event+30d) are past the cutoff: both leaves evict in one tick.
    send_sweep(&tx, event_ms + 31 * DAY_MS).await;
    drop(tx);
    worker.join().await.unwrap();

    let statuses: Vec<MembershipStatus> =
        sink.changes().iter().map(|change| change.status).collect();
    assert_eq!(
        statuses,
        vec![MembershipStatus::Entered, MembershipStatus::Left],
        "two same-tick leaf evictions of one cohort dedup to a single composed Left",
    );
    assert_eq!(stage2_bit(&store, 1, alice), Some(false));
}

#[tokio::test]
async fn sweep_compose_after_delete_reads_false() {
    let (_dir, store) = temp_store();
    // AND(daily gte 1 over 7d, person email): a full-window drain takes the daily leaf through
    // `EvictionAction::Delete`, so compose must read the *deleted* row (a non-member), not the
    // pre-eviction state — pinning the run-after-the-Stage-1-write ordering.
    let filters = build_team_filters(vec![behavioral_leaf_multiple(7, "gte", 1), person_leaf()]);
    let lsk = behavioral_lsk(&filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";
    let day = day_of(ts);

    send_event(&tracker, &tx, person_event_at(alice, ts, 0), 0).await;
    // Slide well past the lone bucket: every bucket drains → Delete + leaf Left.
    send_sweep(&tx, start_of_day_ms_in_tz(day + 9, UTC)).await;
    drop(tx);
    worker.join().await.unwrap();

    let statuses: Vec<MembershipStatus> =
        sink.changes().iter().map(|change| change.status).collect();
    assert_eq!(
        statuses,
        vec![MembershipStatus::Entered, MembershipStatus::Left],
        "compose reads the deleted leaf as a non-member and emits the cohort Left",
    );
    assert!(
        state_at(&store, lsk, alice).is_none(),
        "the fully-drained daily window was deleted before compose read it",
    );
    assert_eq!(stage2_bit(&store, 1, alice), Some(false));
}

#[tokio::test]
async fn sweep_compose_produce_failure_does_not_corrupt() {
    let (_dir, store) = temp_store();
    // Composable-only cohort, so the sweep's single-leaf produce is empty and never calls the sink:
    // call 1 is the event's composed Entered, call 2 is the sweep's compose produce.
    let filters = build_team_filters(vec![behavioral_leaf(7), person_leaf()]);
    let lsk = behavioral_lsk(&filters);
    let sink = FailNthSink::new(2);
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";
    let event_ms = clickhouse_timestamp_to_millis(ts).unwrap();

    send_event(&tracker, &tx, person_event_at(alice, ts, 0), 0).await;
    send_sweep(&tx, event_ms + 8 * DAY_MS).await;

    drain_until_calls(&sink, 2).await;
    assert!(
        state_at(&store, lsk, alice).is_none(),
        "the Stage 1 eviction committed before the failed produce",
    );
    assert_eq!(
        stage2_bit(&store, 1, alice),
        Some(false),
        "the cf_stage2 bit committed before the failed produce",
    );
    assert_eq!(
        sink.changes().len(),
        1,
        "only the initial Entered was recorded — the composed Left is lost (at-most-once)",
    );

    // A follow-up matching event re-creates the behavioral leaf and recomposes an Entered.
    send_event(
        &tracker,
        &tx,
        person_event_at(alice, "2026-05-29 10:00:00.000000", 1),
        1,
    )
    .await;
    drop(tx);
    worker.join().await.unwrap();

    let statuses: Vec<MembershipStatus> =
        sink.changes().iter().map(|change| change.status).collect();
    assert_eq!(
        statuses,
        vec![MembershipStatus::Entered, MembershipStatus::Entered],
        "the dropped Left never reaches the sink; the next event self-heals the membership",
    );
    assert_eq!(stage2_bit(&store, 1, alice), Some(true));
}

#[test]
fn relative_window_schedules_an_eviction_but_an_explicit_window_does_not() {
    let (_dir, store) = temp_store();
    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";

    let relative = build_team_filters(vec![behavioral_leaf(7)]);
    let lsk = behavioral_lsk(&relative);
    let out = process_event(PARTITION_ID, &store, &relative, &event_at(alice, ts, 0)).unwrap();
    assert_eq!(out.transitions.len(), 1, "the match enters");
    assert_eq!(
        out.schedules,
        vec![(
            BehavioralKey::new(PARTITION_ID, TEAM as u64, alice, lsk),
            start_of_day_ms_in_tz(day_of(ts) + 7 + 1, UTC),
        )],
        "a whole-day single schedules at the calendar midnight after day + window",
    );

    // An explicit date range is permanent membership → never scheduled (deadline i64::MAX).
    let (_dir2, store2) = temp_store();
    let explicit = build_team_filters(vec![explicit_behavioral_leaf()]);
    let out = process_event(
        PARTITION_ID,
        &store2,
        &explicit,
        &event_at(person(2), ts, 0),
    )
    .unwrap();
    assert_eq!(out.transitions.len(), 1, "the match still enters");
    assert!(
        out.schedules.is_empty(),
        "an explicit-window single is never scheduled for eviction",
    );
}

#[test]
fn explicit_range_matches_at_day_granularity_inclusive_on_both_ends() {
    // The explicit leaf spans 2026-01-01 .. 2026-12-31 (UTC). The match is at **day** granularity,
    // inclusive on both ends, mirroring the oracle's `date >= toDate(from) AND date <= toDate(to)`.
    // A boundary-day event on either end is a member; a day past either end is not.
    let cases = [
        (
            "2026-01-01 00:00:00.000000",
            true,
            "first instant of the from-day enters",
        ),
        (
            "2026-01-01 23:59:59.000000",
            true,
            "last instant of the from-day still enters",
        ),
        (
            "2026-12-31 23:59:59.000000",
            true,
            "last instant of the to-day enters",
        ),
        ("2026-06-15 12:00:00.000000", true, "mid-range enters"),
        (
            "2025-12-31 23:59:59.000000",
            false,
            "the day before from is out of range",
        ),
        (
            "2027-01-01 00:00:00.000000",
            false,
            "the day after to is out of range",
        ),
    ];
    for (ts, expect_member, why) in cases {
        let (_dir, store) = temp_store();
        let explicit = build_team_filters(vec![explicit_behavioral_leaf()]);
        let lsk = behavioral_lsk(&explicit);
        let alice = person(1);
        let out = process_event(PARTITION_ID, &store, &explicit, &event_at(alice, ts, 0)).unwrap();

        if expect_member {
            assert_eq!(out.transitions.len(), 1, "{why}");
            assert!(
                state_at(&store, lsk, alice).is_some(),
                "an in-range match writes state: {why}",
            );
            assert!(
                out.schedules.is_empty(),
                "an in-range explicit match is permanent, never scheduled: {why}",
            );
        } else {
            assert!(out.transitions.is_empty(), "{why}");
            assert!(out.schedules.is_empty(), "{why}");
            assert!(
                state_at(&store, lsk, alice).is_none(),
                "an out-of-range event writes no state: {why}",
            );
        }
    }
}

#[test]
fn explicit_range_lower_bound_is_the_literal_calendar_day_under_a_negative_offset_team() {
    // Bug 1 regression. Team America/New_York (UTC−4 in May, EDT), absolute range 2026-05-01..2026-05-31
    // emitted as bare dates (the date picker's date-only shape). The oracle treats `toDate('2026-05-01')`
    // as the literal calendar date 2026-05-01, tz-invariant; an event at 2026-04-30 22:00 *New York local*
    // (= 2026-05-01 02:00 UTC) is BEFORE `from` in local time and is NOT a member. The pre-fix code parsed
    // the bare date as UTC midnight then re-projected it into New_York (= 2026-04-30 local), shifting the
    // whole window one calendar day earlier and wrongly admitting this event.
    //
    // Timestamps are passed as their UTC equivalents (the ClickHouse form is read as UTC); the comment on
    // each line is the New-York-local wall clock.
    let cases = [
        (
            "2026-05-01 02:00:00.000000", // 2026-04-30 22:00 NY — just before `from` locally
            false,
            "the local day before from (2026-04-30 NY) is out of range",
        ),
        (
            "2026-05-01 14:00:00.000000", // 2026-05-01 10:00 NY — the from day, locally
            true,
            "an event on the from day (2026-05-01 NY) enters",
        ),
        (
            "2026-06-01 03:00:00.000000", // 2026-05-31 23:00 NY — the to day, locally
            true,
            "an event on the to day (2026-05-31 NY) enters",
        ),
        (
            "2026-06-01 14:00:00.000000", // 2026-06-01 10:00 NY — the day after to, locally
            false,
            "the local day after to (2026-06-01 NY) is out of range",
        ),
    ];
    for (ts, expect_member, why) in cases {
        let (_dir, store) = temp_store();
        let explicit = build_team_filters_tz(
            vec![explicit_behavioral_leaf_range("2026-05-01", "2026-05-31")],
            New_York,
        );
        let lsk = behavioral_lsk(&explicit);
        let alice = person(1);
        let out = process_event(PARTITION_ID, &store, &explicit, &event_at(alice, ts, 0)).unwrap();

        if expect_member {
            assert_eq!(out.transitions.len(), 1, "{why}");
            assert!(state_at(&store, lsk, alice).is_some(), "{why}");
        } else {
            assert!(out.transitions.is_empty(), "{why}");
            assert!(
                state_at(&store, lsk, alice).is_none(),
                "an out-of-range event writes no state: {why}",
            );
        }
    }
}

#[test]
fn explicit_range_upper_bound_from_the_ui_wire_format_bounds_the_range() {
    // Bug 2 regression. The cohort date picker emits the upper bound as
    // `dayjs(...).format('YYYY-MM-DDTHH:mm:ss')` — T-separated, no offset. The pre-fix parser accepted
    // neither that shape nor coerced it, so it silently dropped the upper bound and made every event
    // after the intended end a permanent member. With the bound parsed, an event after the to-day is
    // correctly excluded.
    let leaf = explicit_behavioral_leaf_range("2026-01-01", "2026-12-31T00:00:00");

    // On the to-day → member.
    let (_dir, store) = temp_store();
    let explicit = build_team_filters(vec![leaf.clone()]);
    let lsk = behavioral_lsk(&explicit);
    let alice = person(1);
    let on_to_day = process_event(
        PARTITION_ID,
        &store,
        &explicit,
        &event_at(alice, "2026-12-31 12:00:00.000000", 0),
    )
    .unwrap();
    assert_eq!(
        on_to_day.transitions.len(),
        1,
        "an event on the to-day enters"
    );

    // The day after the to-day → NOT a member (the bound is honored, not dropped).
    let (_dir2, store2) = temp_store();
    let explicit2 = build_team_filters(vec![leaf]);
    let bob = person(2);
    let after_to = process_event(
        PARTITION_ID,
        &store2,
        &explicit2,
        &event_at(bob, "2027-01-01 00:00:00.000000", 0),
    )
    .unwrap();
    assert!(
        after_to.transitions.is_empty() && state_at(&store2, lsk, bob).is_none(),
        "an event after the UI-emitted upper bound is excluded, not a permanent member",
    );
}

#[test]
fn explicit_range_with_an_unparseable_bound_skips_the_leaf_entirely() {
    // A present-but-unparseable bound must skip the leaf (no realtime state at all), NOT degrade to an
    // open-ended range. With the leaf skipped there is no behavioral condition, so even an in-window
    // event produces no transition and no state.
    let (_dir, store) = temp_store();
    let explicit = build_team_filters(vec![explicit_behavioral_leaf_range(
        "2026-01-01",
        "garbage",
    )]);
    assert!(
        explicit.behavioral_conditions.is_empty(),
        "an unparseable bound leaves the leaf with no behavioral condition",
    );
    let alice = person(1);
    let out = process_event(
        PARTITION_ID,
        &store,
        &explicit,
        &event_at(alice, "2026-06-15 12:00:00.000000", 0),
    )
    .unwrap();
    assert!(
        out.transitions.is_empty() && out.schedules.is_empty(),
        "a skipped leaf emits nothing — not an open-ended permanent membership",
    );
}

#[tokio::test]
async fn dispatch_sweeper_routes_an_end_to_end_eviction() {
    use cohort_stream_processor::consumers::ConsumedEvent;
    use cohort_stream_processor::sweep::{DispatchSweeper, Sweeper};

    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![behavioral_leaf(7)]);
    let sink = Arc::new(CaptureSink::new());
    let dispatcher = Arc::new(EventDispatcher::new(
        PartitionRouter::new(64),
        Arc::new(OffsetTracker::new()),
        test_handle(&store),
        catalog_of(filters),
        sink.clone(),
        MergeWorkerDeps::capture(),
    ));

    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";
    let event_ms = clickhouse_timestamp_to_millis(ts).unwrap();

    // Own the partition and dispatch a matching event: spawns the worker and schedules the eviction.
    dispatcher.assign_partition(0);
    dispatcher
        .dispatch(vec![ConsumedEvent {
            event: event_at(alice, ts, 0),
            partition: 0,
            offset: 0,
        }])
        .await;

    // A sweeper whose clock is past `event + window + margin` routes a Sweep that evicts the member.
    let margin_ms = 300_000_i64;
    let now = event_ms + 8 * DAY_MS + margin_ms;
    let sweeper = DispatchSweeper::with_clock(dispatcher.clone(), margin_ms, Arc::new(move || now));
    sweeper.run_once().await;

    // Drain the worker through a revoke so it processes the queued event then the routed sweep before
    // we assert. The `Left` can only come from the sweep evicting the member (a revoke alone never
    // emits one), so its presence proves the routed `Sweep` reached the worker and fired.
    dispatcher.revoke_partition_sync(0);
    dispatcher.revoke_partition_drain(0).await;

    let changes = sink.changes();
    assert_eq!(
        changes.len(),
        2,
        "Entered (dispatch) then Left (routed sweep)"
    );
    assert_eq!(changes[0].status, MembershipStatus::Entered);
    assert_eq!(changes[1].status, MembershipStatus::Left);
}

#[tokio::test]
async fn sweep_expiry_of_negated_leaf_emits_entered() {
    // AND(A 7d, ¬B 1d): one $pageview matches both → non-member (A=true, ¬B=false).
    // Sweep expires B's 1-day window while A's 7-day survives → AND(true, ¬absent=true) → Entered.
    let (_dir, store) = temp_store();

    let a = behavioral_leaf(7);
    let mut neg_b = behavioral_leaf(1);
    neg_b
        .as_object_mut()
        .unwrap()
        .insert("negation".to_string(), json!(true));

    let filters = build_team_filters(vec![a, neg_b]);
    let lsks = &filters.by_condition_to_lsk[&BEHAVIORAL_HASH];
    assert_eq!(lsks.len(), 2);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());
    let (tx, worker) = spawn_worker(
        &store,
        catalog_of(filters),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";
    let event_ms = clickhouse_timestamp_to_millis(ts).unwrap();

    send_event(&tracker, &tx, event_at(alice, ts, 0), 0).await;
    send_sweep(&tx, event_ms + 2 * DAY_MS).await;
    drop(tx);
    worker.join().await.unwrap();

    let statuses: Vec<MembershipStatus> =
        sink.changes().iter().map(|change| change.status).collect();
    assert_eq!(statuses, vec![MembershipStatus::Entered]);
    assert_eq!(stage2_bit(&store, 1, alice), Some(true));
}

// Pin that the worker's per-partition state types line up with what the sweep evicts (a compile-time
// reminder if the variant enum is reshaped).
#[test]
fn state_variants_are_exhaustive() {
    for variant in [
        StateVariant::BehavioralSingle,
        StateVariant::BehavioralDailyBuckets,
        StateVariant::BehavioralCompressedHistory,
        StateVariant::PersonProperty,
    ] {
        assert!(!variant.as_str().is_empty());
    }
}

/// The three offload modes route the same store ops inline vs onto the blocking pool; the observable
/// outcome must be identical. One composable cohort driven through enter-then-evict exercises every
/// lane per mode (event fold, stage-2 composition, sweep prefetch + recompose), catching mode
/// plumbing that inverts a lane — e.g. `Maintenance` offloading the event read it must run inline.
#[tokio::test]
async fn each_offload_mode_yields_the_same_emissions_and_state() {
    #[derive(Debug, PartialEq)]
    struct ModeOutcome {
        statuses: Vec<MembershipStatus>,
        stage2_bit: Option<bool>,
        stage1: Vec<(Vec<u8>, Vec<u8>)>,
        person_record: Option<Vec<u8>>,
    }

    let ts = "2026-05-20 10:00:00.000000";
    let event_ms = clickhouse_timestamp_to_millis(ts).unwrap();
    let deadline = event_ms + 7 * DAY_MS;
    let alice = person(1);

    let mut per_mode: Vec<ModeOutcome> = Vec::new();
    for mode in [OffloadMode::Off, OffloadMode::Maintenance, OffloadMode::All] {
        let (_dir, store) = temp_store();
        let filters = build_team_filters(vec![behavioral_leaf(7), person_leaf()]);
        let sink = CaptureSink::new();
        let tracker = Arc::new(OffsetTracker::new());
        let (tx, worker) = spawn_worker_with_mode(
            &store,
            catalog_of(filters),
            Arc::new(sink.clone()),
            tracker.clone(),
            mode,
        );

        send_event(&tracker, &tx, person_event_at(alice, ts, 0), 0).await;
        send_sweep(&tx, deadline + DAY_MS).await;
        drop(tx);
        // Join is the barrier: the worker awaits every commit before exiting.
        worker.join().await.unwrap();

        let statuses: Vec<MembershipStatus> =
            sink.changes().iter().map(|change| change.status).collect();
        assert_eq!(
            statuses,
            vec![MembershipStatus::Entered, MembershipStatus::Left],
            "mode {mode:?}: the cohort enters on the event and leaves on the sweep",
        );
        // After the sweep evicts the behavioral leaf, `cf_behavioral` is empty — the never-evicted
        // person leaf lives in the sweep-invariant `cf_person_records` record, not here.
        let stage1: Vec<(Vec<u8>, Vec<u8>)> = store
            .scan_behavioral(PARTITION_ID, None, 10_000)
            .unwrap()
            .into_iter()
            .map(|(key, value)| (key.encode().to_vec(), value))
            .collect();
        let person_record = store
            .get_person_record(&PersonRecordKey::new(PARTITION_ID, TEAM as u64, alice))
            .unwrap();
        assert!(
            person_record.is_some(),
            "mode {mode:?}: the never-evicted person leaf still holds its durable record",
        );
        per_mode.push(ModeOutcome {
            statuses,
            stage2_bit: stage2_bit(&store, 1, alice),
            stage1,
            person_record,
        });
    }

    let (off, rest) = per_mode.split_first().unwrap();
    for (arm, mode) in rest
        .iter()
        .zip([OffloadMode::Maintenance, OffloadMode::All])
    {
        assert_eq!(
            arm, off,
            "mode {mode:?} diverged from Off: emissions, stage-2 bit, cf_behavioral bytes, and the person record must be identical across operating points",
        );
    }
}
