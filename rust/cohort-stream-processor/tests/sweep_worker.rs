//! The time-driven eviction sweep, driven end-to-end through the public API (no Kafka). Events flow
//! through a spawned [`Stage1Worker`](cohort_stream_processor::workers::Stage1Worker) to schedule
//! evictions, then a [`ShuffleMessage::Sweep`](cohort_stream_processor::partitions::ShuffleMessage)
//! with a synthetic cutoff drains the worker's queue. One case drives the real
//! [`DispatchSweeper`](cohort_stream_processor::sweep::DispatchSweeper) over an
//! [`EventDispatcher`](cohort_stream_processor::consumers::EventDispatcher) to cover the production
//! routing path. The scheduling/queue mechanics themselves are unit-tested in
//! `tests/sweep_eviction_queue.rs`; the per-variant eviction in `src/workers/sweep_callback.rs`.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use chrono_tz::UTC;
use cohort_stream_processor::consumers::{CohortStreamEvent, EventDispatcher};
use cohort_stream_processor::filters::{
    CatalogHandle, CohortId, FilterCatalog, TeamFilters, TeamFiltersBuilder, TeamId,
};
use cohort_stream_processor::partitions::{OffsetTracker, PartitionRouter, ShuffleMessage};
use cohort_stream_processor::producer::{
    CaptureSink, CohortMembershipChange, MembershipSink, MembershipStatus,
};
use cohort_stream_processor::stage1::bucket_tz::{day_idx_in_tz, start_of_day_ms_in_tz};
use cohort_stream_processor::stage1::{
    clickhouse_timestamp_to_millis, Stage1State, StateVariant, StatefulRecord,
};
use cohort_stream_processor::store::{CohortStore, LeafStateKey, Stage1Key, StoreConfig};
use cohort_stream_processor::workers::{process_event, Stage1Worker};
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

/// A `performed_event` leaf over an explicit date range (so its eviction deadline is `i64::MAX`).
fn explicit_behavioral_leaf() -> Value {
    json!({
        "type": "behavioral", "value": "performed_event", "key": "$pageview",
        "explicit_datetime": "2026-01-01 00:00:00.000000",
        "explicit_datetime_to": "2026-12-31 00:00:00.000000",
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

fn cohort(values: Vec<Value>) -> Value {
    json!({ "properties": { "type": "AND", "values": values } })
}

fn build_team_filters(leaves: Vec<Value>) -> TeamFilters {
    let mut builder = TeamFiltersBuilder::default();
    builder
        .add_cohort(CohortId(1), TeamId(TEAM), &cohort(leaves))
        .expect("add cohort");
    builder.freeze(UTC)
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
    }
}

fn behavioral_lsk(filters: &TeamFilters) -> LeafStateKey {
    filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0]
}

fn state_at(store: &CohortStore, lsk: LeafStateKey, person: Uuid) -> Option<Stage1State> {
    let key = Stage1Key {
        partition_id: PARTITION_ID,
        team_id: TEAM as u64,
        leaf_state_key: lsk,
        person_id: person,
    };
    store
        .get_stage1(&key)
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
    tx.send(vec![ShuffleMessage::Event { event, cse_offset }])
        .await
        .unwrap();
}

async fn send_sweep(tx: &mpsc::Sender<Vec<ShuffleMessage>>, due_before_ms: i64) {
    tx.send(vec![ShuffleMessage::Sweep { due_before_ms }])
        .await
        .unwrap();
}

/// Drive the current-thread runtime until the worker has recorded `count` changes, so a test can read
/// the intermediate post-sweep state mid-stream (the queue is per-worker, so it can't drop the worker
/// to barrier). [`CaptureSink::produce`] is immediately-ready and `handle_sweep` does its state write
/// and reschedule synchronously right after it, so once a sweep's change lands its state mutation is
/// durable too — no wall-clock sleep needed.
async fn drain_until_changes(sink: &CaptureSink, count: usize) {
    for _ in 0..10_000 {
        if sink.changes().len() >= count {
            return;
        }
        tokio::task::yield_now().await;
    }
    panic!("worker did not record {count} changes");
}

fn spawn_worker(
    store: &CohortStore,
    catalog: Arc<CatalogHandle>,
    sink: Arc<dyn MembershipSink>,
    tracker: Arc<OffsetTracker>,
) -> (mpsc::Sender<Vec<ShuffleMessage>>, Stage1Worker) {
    let (tx, rx) = mpsc::channel(16);
    let worker = Stage1Worker::spawn(PARTITION_ID, rx, store.clone(), catalog, sink, tracker);
    (tx, worker)
}

// ── BehavioralSingle eviction ────────────────────────────────────────────────────

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

// ── BehavioralDailyBuckets eviction ──────────────────────────────────────────────

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
    // rescheduled to the surviving D+3 bucket's leave boundary (start of D+11).
    drain_until_changes(&sink, 3).await;
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

// ── BehavioralCompressedHistory eviction (>180-day windows) ──────────────────────

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

    drain_until_changes(&sink, 3).await;
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

// ── Produce-before-write retry ───────────────────────────────────────────────────

/// A sink that records like [`CaptureSink`] but fails the `fail_call`-th produce (1-based), so a
/// preceding event's `Entered` flushes cleanly and the sweep's `Left` flush can be forced to fail.
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
    // Fail the 2nd produce: the event's Entered (call 1) flushes, the first sweep's Left (call 2) fails.
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

// ── Scheduling: explicit windows are excluded ────────────────────────────────────

#[test]
fn relative_window_schedules_an_eviction_but_an_explicit_window_does_not() {
    let (_dir, store) = temp_store();
    let alice = person(1);
    let ts = "2026-05-20 10:00:00.000000";
    let event_ms = clickhouse_timestamp_to_millis(ts).unwrap();

    // A relative window schedules its eviction at event + window.
    let relative = build_team_filters(vec![behavioral_leaf(7)]);
    let lsk = behavioral_lsk(&relative);
    let out = process_event(PARTITION_ID, &store, &relative, &event_at(alice, ts, 0)).unwrap();
    assert_eq!(out.transitions.len(), 1, "the match enters");
    assert_eq!(
        out.schedules,
        vec![(
            Stage1Key {
                partition_id: PARTITION_ID,
                team_id: TEAM as u64,
                leaf_state_key: lsk,
                person_id: alice,
            },
            event_ms + 7 * DAY_MS,
        )],
        "a relative-window single schedules at event + window",
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

// ── DispatchSweeper end-to-end over the dispatcher ───────────────────────────────

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
        store.clone(),
        catalog_of(filters),
        sink.clone(),
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
