//! The Stage 1 single-condition worker, driven end-to-end against a real RocksDB through the public
//! API (no Kafka). Synthetic events flow through
//! [`process_event`](cohort_stream_processor::workers::process_event); one case is driven through a
//! spawned [`Stage1Worker`](cohort_stream_processor::workers::Stage1Worker) + a test channel to
//! cover the drain loop and post-commit emission.
//!
//! Parse-layer behaviors (globals shape, dropped/cohort-ref leaves, key derivation) are covered by
//! the in-crate classifier / catalog tests, not duplicated here.

use std::collections::BTreeMap;
use std::sync::Arc;

use chrono_tz::Asia::Kolkata;
use chrono_tz::{Tz, UTC};
use cohort_stream_processor::consumers::CohortStreamEvent;
use cohort_stream_processor::filters::{
    CatalogHandle, CohortId, FilterCatalog, TeamFilters, TeamFiltersBuilder, TeamId,
};
use cohort_stream_processor::partitions::{
    MeteredReceiver, OffsetTracker, PartitionIntake, ShuffleMessage,
};
use cohort_stream_processor::producer::{CaptureSink, MembershipStatus};
use cohort_stream_processor::stage1::bucket_tz::{day_idx_in_tz, start_of_day_ms_in_tz};
use cohort_stream_processor::stage1::{
    clickhouse_timestamp_to_millis, AppliedOffsets, LeafTransition, Stage1State, StateVariant,
    StatefulRecord, TransitionKind,
};
use cohort_stream_processor::store::{
    CohortStore, LeafStateKey, PersonIndexKey, Stage1Key, StoreConfig,
};
use cohort_stream_processor::workers::{process_event, MergeWorkerDeps, SkipReason, Stage1Worker};
use serde_json::{json, Value};
use tempfile::TempDir;
use tokio::sync::mpsc;
use uuid::Uuid;

const TEAM: i32 = 7;
const PARTITION_ID: u16 = 0;
const BEHAVIORAL_HASH: [u8; 16] = *b"0123456789abcdef";
const PERSON_HASH: [u8; 16] = *b"fedcba9876543210";
const BASE_TS: &str = "2026-05-26 12:34:56.789000";
/// A window over 180 days routes `performed_event_multiple` to the compressed history variant.
const COMPRESSED_WINDOW_DAYS: i64 = 365;

fn temp_store() -> (TempDir, CohortStore) {
    let dir = TempDir::new().unwrap();
    let config = StoreConfig {
        path: dir.path().join("db"),
        ..StoreConfig::default()
    };
    let store = CohortStore::open(&config).expect("open store");
    (dir, store)
}

/// Raise the dispatch ceiling *before* sending: `mark_processed` clamps a processed offset to what
/// was dispatched, and the worker may mark as soon as it receives the message.
async fn dispatch_to_worker(
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

/// `event == "$pageview"` — the matcher every behavioral leaf with `BEHAVIORAL_HASH` shares.
fn behavioral_bytecode() -> Value {
    json!(["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11])
}

/// `person.properties.email == "u@p.com"`.
fn person_email_bytecode() -> Value {
    json!([
        "_H",
        1,
        32,
        "u@p.com",
        32,
        "email",
        32,
        "properties",
        32,
        "person",
        1,
        3,
        11
    ])
}

/// A `performed_event` leaf on `$pageview` with a tunable relative window (in days).
fn behavioral_leaf(window_days: i64) -> Value {
    json!({
        "type": "behavioral",
        "value": "performed_event",
        "key": "$pageview",
        "time_value": window_days,
        "time_interval": "day",
        "conditionHash": "0123456789abcdef",
        "bytecode": behavioral_bytecode(),
    })
}

/// A `performed_event_multiple` leaf on `$pageview`: `<op> <value>` over a `window_days`-day window,
/// routed to the daily-bucket state. Shares the matcher bytecode/conditionHash with
/// [`behavioral_leaf`], so both fan out from one HogVM eval but key to distinct leaf state.
fn behavioral_leaf_multiple(window_days: i64, op: &str, value: i64) -> Value {
    json!({
        "type": "behavioral",
        "value": "performed_event_multiple",
        "key": "$pageview",
        "time_value": window_days,
        "time_interval": "day",
        "operator": op,
        "operator_value": value,
        "conditionHash": "0123456789abcdef",
        "bytecode": behavioral_bytecode(),
    })
}

fn person_leaf() -> Value {
    person_leaf_with_bytecode(person_email_bytecode())
}

fn person_leaf_with_bytecode(bytecode: Value) -> Value {
    json!({
        "type": "person",
        "key": "email",
        "value": "u@p.com",
        "operator": "exact",
        "conditionHash": "fedcba9876543210",
        "bytecode": bytecode,
    })
}

fn cohort(values: Vec<Value>) -> Value {
    json!({ "properties": { "type": "AND", "values": values } })
}

fn build_team_filters(cohorts: Vec<(CohortId, Value)>) -> TeamFilters {
    build_team_filters_tz(cohorts, UTC)
}

/// Like [`build_team_filters`] but freezes under an explicit team timezone, so the bucket folds run
/// their `day_idx_in_tz(event_ms, tz)` path against a non-UTC zone.
fn build_team_filters_tz(cohorts: Vec<(CohortId, Value)>, tz: Tz) -> TeamFilters {
    let mut builder = TeamFiltersBuilder::default();
    for (id, filters) in cohorts {
        builder
            .add_cohort(id, TeamId(TEAM), &filters)
            .expect("add cohort");
    }
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

/// A `$pageview` event for `person` with matching person-properties, at `BASE_TS`.
fn event(person: Uuid, source_partition: i32, source_offset: i64) -> CohortStreamEvent {
    CohortStreamEvent {
        team_id: TEAM,
        person_id: person.to_string(),
        distinct_id: "d".to_string(),
        uuid: "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string(),
        event: "$pageview".to_string(),
        timestamp: BASE_TS.to_string(),
        properties: Some("{}".to_string()),
        person_properties: Some(r#"{"email":"u@p.com"}"#.to_string()),
        elements_chain: None,
        source_offset,
        source_partition,
        redirected_from: None,
        redirect_hops: 0,
    }
}

/// A person event whose `email` and timestamp are tunable, for the argMax / flip cases.
fn person_event(
    person: Uuid,
    email: &str,
    timestamp: &str,
    source_partition: i32,
    source_offset: i64,
) -> CohortStreamEvent {
    CohortStreamEvent {
        person_properties: Some(format!(r#"{{"email":"{email}"}}"#)),
        timestamp: timestamp.to_string(),
        ..event(person, source_partition, source_offset)
    }
}

/// A matching `$pageview` event for `person` at a specific `timestamp` (drives the day-bucket fold).
fn event_at(
    person: Uuid,
    timestamp: &str,
    source_partition: i32,
    source_offset: i64,
) -> CohortStreamEvent {
    CohortStreamEvent {
        timestamp: timestamp.to_string(),
        ..event(person, source_partition, source_offset)
    }
}

fn stage1_key(lsk: LeafStateKey, person: Uuid) -> Stage1Key {
    Stage1Key {
        partition_id: PARTITION_ID,
        team_id: TEAM as u64,
        leaf_state_key: lsk,
        person_id: person,
    }
}

fn person_index_key(person: Uuid) -> PersonIndexKey {
    PersonIndexKey {
        partition_id: PARTITION_ID,
        team_id: TEAM as u64,
        person_id: person,
    }
}

fn state_at(store: &CohortStore, lsk: LeafStateKey, person: Uuid) -> Option<Stage1State> {
    record_at(store, lsk, person).map(|record| record.state)
}

/// The full persisted record (state + per-source-partition applied offsets), for the cross-partition
/// replay-dedup assertions.
fn record_at(store: &CohortStore, lsk: LeafStateKey, person: Uuid) -> Option<StatefulRecord> {
    store
        .get_stage1(&stage1_key(lsk, person))
        .unwrap()
        .map(|bytes| StatefulRecord::decode(&bytes).unwrap())
}

/// Assert `offset` is the recorded high-water mark for `partition` — probed via the public
/// `is_replay` (the inner map is intentionally private): `offset` is a replay, `offset + 1` is new.
fn assert_high_water(applied: &AppliedOffsets, partition: i32, offset: i64) {
    assert!(
        applied.is_replay(partition, offset),
        "offset {offset} on partition {partition} should be ≤ the high-water mark",
    );
    assert!(
        !applied.is_replay(partition, offset + 1),
        "offset {} on partition {partition} should be above the high-water mark",
        offset + 1,
    );
}

fn behavioral_deadline(state: &Stage1State) -> i64 {
    match state {
        Stage1State::BehavioralSingle {
            earliest_eviction_at_ms,
            ..
        } => *earliest_eviction_at_ms,
        other => panic!("expected BehavioralSingle, got {other:?}"),
    }
}

/// The daily-bucket state's `(buckets, window_start_day, earliest_eviction_at_ms)`.
fn daily_state(state: &Stage1State) -> (&[u32], i32, i64) {
    match state {
        Stage1State::BehavioralDailyBuckets {
            buckets,
            window_start_day,
            earliest_eviction_at_ms,
            ..
        } => (buckets, *window_start_day, *earliest_eviction_at_ms),
        other => panic!("expected BehavioralDailyBuckets, got {other:?}"),
    }
}

fn window_count(state: &Stage1State) -> u32 {
    daily_state(state).0.iter().sum()
}

/// The compressed-history state's `(entries, window_start_day, earliest_eviction_at_ms)`.
fn compressed_state(state: &Stage1State) -> (&[(i32, u32)], i32, i64) {
    match state {
        Stage1State::BehavioralCompressedHistory {
            entries,
            window_start_day,
            earliest_eviction_at_ms,
            ..
        } => (entries, *window_start_day, *earliest_eviction_at_ms),
        other => panic!("expected BehavioralCompressedHistory, got {other:?}"),
    }
}

fn compressed_count(state: &Stage1State) -> u32 {
    compressed_state(state)
        .0
        .iter()
        .map(|&(_, count)| count)
        .sum()
}

/// The `stage1_transitions_total{kind}` label for a transition, resolved through the snapshot — the
/// same mapping the worker emits.
fn transition_kind(filters: &TeamFilters, transition: &LeafTransition) -> &'static str {
    let variant = filters.by_lsk[&transition.leaf_state_key].variant;
    match (variant, transition.kind) {
        (StateVariant::BehavioralSingle, TransitionKind::Entered) => "behavioral_entered",
        (StateVariant::BehavioralSingle, TransitionKind::Left) => "behavioral_left",
        (StateVariant::BehavioralDailyBuckets, TransitionKind::Entered) => {
            "behavioral_daily_entered"
        }
        (StateVariant::BehavioralDailyBuckets, TransitionKind::Left) => "behavioral_daily_left",
        (StateVariant::BehavioralCompressedHistory, TransitionKind::Entered) => {
            "behavioral_compressed_entered"
        }
        (StateVariant::BehavioralCompressedHistory, TransitionKind::Left) => {
            "behavioral_compressed_left"
        }
        (StateVariant::PersonProperty, TransitionKind::Entered) => "person_entered",
        (StateVariant::PersonProperty, TransitionKind::Left) => "person_left",
    }
}

#[test]
fn c1_same_hash_two_windows_get_independent_state_and_deadlines() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![
        (CohortId(1), cohort(vec![behavioral_leaf(7)])),
        (CohortId(2), cohort(vec![behavioral_leaf(30)])),
    ]);
    let lsks = &filters.by_condition_to_lsk[&BEHAVIORAL_HASH];
    assert_eq!(lsks.len(), 2, "two distinct LSKs under one conditionHash");
    assert_eq!(
        filters.behavioral_conditions.len(),
        1,
        "one unique conditionHash → one HogVM eval that fans out",
    );
    for lsk in lsks {
        assert_eq!(filters.by_lsk[lsk].variant, StateVariant::BehavioralSingle);
    }

    let alice = person(1);

    // One eval fans out to both LSKs → two Entered, independent state.
    let first = event(alice, 1, 10);
    let out = process_event(PARTITION_ID, &store, &filters, &first).unwrap();
    assert_eq!(out.skipped, None);
    assert_eq!(out.transitions.len(), 2);
    assert!(out
        .transitions
        .iter()
        .all(|t| t.kind == TransitionKind::Entered));

    let event_ms = clickhouse_timestamp_to_millis(BASE_TS).unwrap();
    let event_day = day_idx_in_tz(event_ms, UTC);
    let mut deadlines: Vec<i64> = lsks
        .iter()
        .map(|lsk| behavioral_deadline(&state_at(&store, *lsk, alice).unwrap()))
        .collect();
    deadlines.sort_unstable();
    assert_eq!(deadlines[0], start_of_day_ms_in_tz(event_day + 7 + 1, UTC));
    assert_eq!(deadlines[1], start_of_day_ms_in_tz(event_day + 30 + 1, UTC));
    assert_eq!(
        deadlines[1] - deadlines[0],
        (30 - 7) * 86_400 * 1000,
        "the two deadlines differ by exactly (30-7) days",
    );

    let later_ts = "2026-05-27 12:34:56.789000";
    let later_ms = clickhouse_timestamp_to_millis(later_ts).unwrap();
    let later_day = day_idx_in_tz(later_ms, UTC);
    let second = CohortStreamEvent {
        timestamp: later_ts.to_string(),
        source_offset: 11,
        ..event(alice, 1, 11)
    };
    let out = process_event(PARTITION_ID, &store, &filters, &second).unwrap();
    assert!(
        out.transitions.is_empty(),
        "already a member → no transition"
    );
    let mut advanced: Vec<i64> = lsks
        .iter()
        .map(|lsk| behavioral_deadline(&state_at(&store, *lsk, alice).unwrap()))
        .collect();
    advanced.sort_unstable();
    assert_eq!(advanced[0], start_of_day_ms_in_tz(later_day + 7 + 1, UTC));
    assert_eq!(advanced[1], start_of_day_ms_in_tz(later_day + 30 + 1, UTC));

    // Replay the first event (lower offset): idempotent, no regression.
    let out = process_event(PARTITION_ID, &store, &filters, &first).unwrap();
    assert!(out.transitions.is_empty());
    let mut after_replay: Vec<i64> = lsks
        .iter()
        .map(|lsk| behavioral_deadline(&state_at(&store, *lsk, alice).unwrap()))
        .collect();
    after_replay.sort_unstable();
    assert_eq!(after_replay, advanced, "replay must not regress state");
}

#[test]
fn behavioral_deadline_tracks_newest_event_not_the_late_one() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![behavioral_leaf(7)]))]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let alice = person(1);

    // Newest-by-event-time arrives first (offset 10), at a later ts than BASE_TS.
    let later_ts = "2026-05-27 12:34:56.789000";
    let later_ms = clickhouse_timestamp_to_millis(later_ts).unwrap();
    let newest_deadline = start_of_day_ms_in_tz(day_idx_in_tz(later_ms, UTC) + 7 + 1, UTC);
    let newest = CohortStreamEvent {
        timestamp: later_ts.to_string(),
        ..event(alice, 1, 10)
    };
    let out = process_event(PARTITION_ID, &store, &filters, &newest).unwrap();
    assert_eq!(out.skipped, None);
    assert_eq!(out.transitions.len(), 1, "first match enters");
    assert_eq!(
        behavioral_deadline(&state_at(&store, lsk, alice).unwrap()),
        newest_deadline,
        "deadline seeded off the newest event's calendar day",
    );

    // A late event (earlier ts, higher offset) is applied — not a replay — but must not regress the deadline.
    let earlier_ts = "2026-05-25 12:34:56.789000";
    let late = CohortStreamEvent {
        timestamp: earlier_ts.to_string(),
        ..event(alice, 1, 11)
    };
    let out = process_event(PARTITION_ID, &store, &filters, &late).unwrap();
    assert_eq!(out.skipped, None);
    assert!(
        out.transitions.is_empty(),
        "already a member → no transition"
    );
    assert_eq!(
        behavioral_deadline(&state_at(&store, lsk, alice).unwrap()),
        newest_deadline,
        "a late lower-ts event must not regress the deadline below the newest event's midnight",
    );
}

#[test]
fn single_eviction_deadline_is_team_local_midnight_for_both_edge_persons() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters_tz(
        vec![(CohortId(1), cohort(vec![behavioral_leaf(7)]))],
        Kolkata,
    );
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];

    let alice = person(1);
    let bob = person(2);
    // 00:30 and 23:30 Kolkata local on 2026-05-20, expressed in UTC (−05:30) → one Kolkata day.
    let alice_ts = "2026-05-19 19:00:00.000000"; // 00:30 next-day Kolkata
    let bob_ts = "2026-05-20 18:00:00.000000"; // 23:30 same-day Kolkata
    let alice_ms = clickhouse_timestamp_to_millis(alice_ts).unwrap();
    let bob_ms = clickhouse_timestamp_to_millis(bob_ts).unwrap();
    let kolkata_day = day_idx_in_tz(alice_ms, Kolkata);
    assert_eq!(
        kolkata_day,
        day_idx_in_tz(bob_ms, Kolkata),
        "both events fall on the same Kolkata calendar day",
    );

    process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(alice, alice_ts, 1, 10),
    )
    .unwrap();
    process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(bob, bob_ts, 1, 11),
    )
    .unwrap();

    let expected = start_of_day_ms_in_tz(kolkata_day + 7 + 1, Kolkata);
    assert_eq!(
        behavioral_deadline(&state_at(&store, lsk, alice).unwrap()),
        expected,
        "alice (00:30 local) evicts at the team-local midnight after day + 7",
    );
    assert_eq!(
        behavioral_deadline(&state_at(&store, lsk, bob).unwrap()),
        expected,
        "bob (23:30 local) shares the same eviction midnight as alice",
    );
    assert_ne!(
        expected,
        start_of_day_ms_in_tz(kolkata_day + 7 + 1, UTC),
        "the deadline is the team-local (Kolkata) midnight, not the UTC midnight",
    );
}

#[test]
fn ten_thousand_events_then_replay_is_idempotent() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf(7), person_leaf()]),
    )]);

    const PERSONS: u128 = 100;
    const PER_PERSON: usize = 100;
    let persons: Vec<Uuid> = (1..=PERSONS).map(person).collect();

    // Person-major so each person's offsets strictly increase (the replay-guard ordering).
    let mut events = Vec::with_capacity(persons.len() * PER_PERSON);
    let mut offset = 0i64;
    for &p in &persons {
        for _ in 0..PER_PERSON {
            events.push(event(p, 1, offset));
            offset += 1;
        }
    }

    // Each person's first event enters both leaves; later events are flip no-ops. One enter each.
    let (mut behavioral_entered, mut person_entered, mut unexpected) = (0, 0, 0);
    for ev in &events {
        let out = process_event(PARTITION_ID, &store, &filters, ev).unwrap();
        assert_eq!(out.skipped, None);
        for t in &out.transitions {
            match transition_kind(&filters, t) {
                "behavioral_entered" => behavioral_entered += 1,
                "person_entered" => person_entered += 1,
                _ => unexpected += 1,
            }
        }
    }
    assert_eq!(behavioral_entered, persons.len());
    assert_eq!(person_entered, persons.len());
    assert_eq!(unexpected, 0);

    for &p in &persons {
        for lsk in filters.by_lsk.keys() {
            assert!(
                store.get_stage1(&stage1_key(*lsk, p)).unwrap().is_some(),
                "missing state row",
            );
        }
        assert_eq!(
            store.get_person_index(&person_index_key(p)).unwrap().len(),
            2
        );
    }

    let before = snapshot_state(&store, &filters, &persons);
    let mut replay_transitions = 0;
    for ev in &events {
        replay_transitions += process_event(PARTITION_ID, &store, &filters, ev)
            .unwrap()
            .transitions
            .len();
    }
    assert_eq!(replay_transitions, 0, "replay must produce no transitions");
    assert_eq!(
        before,
        snapshot_state(&store, &filters, &persons),
        "replay must leave state byte-identical",
    );
}

type StateSnapshot = BTreeMap<(u128, [u8; 16]), Vec<u8>>;

fn snapshot_state(store: &CohortStore, filters: &TeamFilters, persons: &[Uuid]) -> StateSnapshot {
    let mut map = BTreeMap::new();
    for &p in persons {
        for lsk in filters.by_lsk.keys() {
            if let Some(bytes) = store.get_stage1(&stage1_key(*lsk, p)).unwrap() {
                map.insert((p.as_u128(), lsk.0), bytes);
            }
        }
    }
    map
}

#[test]
fn cross_partition_low_offset_is_not_masked_by_a_high_offset_elsewhere() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![person_leaf()]))]);
    let lsk = LeafStateKey::for_person_property(&PERSON_HASH);
    let p = person(1);

    // Enter from source partition 10 at a high offset.
    let enter = person_event(p, "u@p.com", "2026-05-26 12:00:00.000000", 10, 100);
    let out = process_event(PARTITION_ID, &store, &filters, &enter).unwrap();
    assert_eq!(out.transitions[0].kind, TransitionKind::Entered);

    // Leave from source partition 20 at a low offset, with a newer event time so argMax applies it.
    let leave = person_event(p, "nope@x.com", "2026-05-26 13:00:00.000000", 20, 3);
    let out = process_event(PARTITION_ID, &store, &filters, &leave).unwrap();
    assert_eq!(
        out.transitions.len(),
        1,
        "the low-offset event on a new partition must apply"
    );
    assert_eq!(out.transitions[0].kind, TransitionKind::Left);

    let applied = record_at(&store, lsk, p).unwrap().applied_offsets;
    assert_high_water(&applied, 10, 100);
    assert_high_water(&applied, 20, 3);
}

#[test]
fn cross_partition_replay_does_not_double_apply_or_disturb_other_partitions() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![behavioral_leaf(7)]))]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let p = person(1);

    // Event from partition 10 (offset 5), then a later event from partition 20 (offset 10).
    process_event(PARTITION_ID, &store, &filters, &event(p, 10, 5)).unwrap();
    let later_b = CohortStreamEvent {
        timestamp: "2026-05-27 12:34:56.789000".to_string(),
        ..event(p, 20, 10)
    };
    process_event(PARTITION_ID, &store, &filters, &later_b).unwrap();

    let before = record_at(&store, lsk, p).unwrap();
    assert_high_water(&before.applied_offsets, 10, 5);
    assert_high_water(&before.applied_offsets, 20, 10);

    // Replay partition 10's original event: is_replay(10, 5) is true (5 ≤ 5) even though the most
    // recent activity is on partition 20.
    let out = process_event(PARTITION_ID, &store, &filters, &event(p, 10, 5)).unwrap();
    assert!(out.transitions.is_empty(), "a replay flips nothing");

    let after = record_at(&store, lsk, p).unwrap();
    assert_eq!(
        after, before,
        "the replay neither double-applied nor disturbed partition 20's high-water mark",
    );
}

#[test]
fn cross_partition_person_replay_leaves_state_and_other_partitions_intact() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![person_leaf()]))]);
    let lsk = LeafStateKey::for_person_property(&PERSON_HASH);
    let p = person(1);

    let from_a = person_event(p, "u@p.com", "2026-05-26 12:00:00.000000", 10, 5);
    process_event(PARTITION_ID, &store, &filters, &from_a).unwrap();
    let later_b = person_event(p, "u@p.com", "2026-05-26 13:00:00.000000", 20, 10);
    process_event(PARTITION_ID, &store, &filters, &later_b).unwrap();

    let before = record_at(&store, lsk, p).unwrap();
    assert_high_water(&before.applied_offsets, 10, 5);
    assert_high_water(&before.applied_offsets, 20, 10);

    let out = process_event(PARTITION_ID, &store, &filters, &from_a).unwrap();
    assert!(
        out.transitions.is_empty(),
        "the person replay flips nothing"
    );

    assert_eq!(
        record_at(&store, lsk, p).unwrap(),
        before,
        "the person replay left state and partition 20 untouched",
    );
}

#[test]
fn argmax_stale_event_still_advances_applied_offsets_across_partitions() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![person_leaf()]))]);
    let lsk = LeafStateKey::for_person_property(&PERSON_HASH);
    let p = person(1);

    // Newest write from partition 10 (offset 5).
    let newest = person_event(p, "u@p.com", "2026-05-26 13:00:00.000000", 10, 5);
    process_event(PARTITION_ID, &store, &filters, &newest).unwrap();

    // An older event from partition 20 at offset 0: argMax-stale, but a genuine first sighting of
    // partition 20 that must be recorded.
    let older_b = person_event(p, "nope@x.com", "2026-05-26 12:00:00.000000", 20, 0);
    let out = process_event(PARTITION_ID, &store, &filters, &older_b).unwrap();
    assert!(out.transitions.is_empty(), "a stale event flips nothing");

    let record = record_at(&store, lsk, p).unwrap();
    match record.state {
        Stage1State::PersonProperty {
            matches,
            last_updated_offset,
            ..
        } => {
            assert!(matches, "the stale event kept the newer match");
            assert_eq!(last_updated_offset, 5, "argMax kept partition 10's offset");
        }
        other => panic!("expected PersonProperty, got {other:?}"),
    }
    assert_high_water(&record.applied_offsets, 10, 5);
    assert_high_water(&record.applied_offsets, 20, 0);
}

#[test]
fn out_of_order_person_events_keep_the_latest_by_event_time() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![person_leaf()]))]);
    let bob = person(1);
    let lsk = LeafStateKey::for_person_property(&PERSON_HASH);

    let newest_ts = "2026-05-26 12:00:00.000000";
    let newest = person_event(bob, "u@p.com", newest_ts, 1, 100);
    let out = process_event(PARTITION_ID, &store, &filters, &newest).unwrap();
    assert_eq!(out.transitions.len(), 1, "first write enters");

    // An older event arriving later is stale by the argMax tiebreaker: neither flips nor overwrites.
    let older = person_event(bob, "nope@x.com", "2026-05-25 12:00:00.000000", 1, 101);
    let out = process_event(PARTITION_ID, &store, &filters, &older).unwrap();
    assert!(out.transitions.is_empty(), "stale event emits nothing");

    let newest_ms = clickhouse_timestamp_to_millis(newest_ts).unwrap();
    match state_at(&store, lsk, bob).unwrap() {
        Stage1State::PersonProperty {
            matches,
            last_updated_at_ms,
            last_updated_offset,
        } => {
            assert!(matches, "the newest-by-event-time value (a match) is kept");
            assert_eq!(last_updated_at_ms, newest_ms);
            assert_eq!(last_updated_offset, 100);
        }
        other => panic!("expected PersonProperty, got {other:?}"),
    }
}

#[test]
fn whole_event_skips_carry_distinct_reasons() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf(7), person_leaf()]),
    )]);

    type SkipCase = (&'static str, fn(&mut CohortStreamEvent), SkipReason);
    let cases: [SkipCase; 5] = [
        (
            "empty person id",
            |e| e.person_id = String::new(),
            SkipReason::NullPersonId,
        ),
        (
            "non-uuid person id",
            |e| e.person_id = "not-a-uuid".to_string(),
            SkipReason::UnparseablePersonId,
        ),
        (
            "unparseable timestamp",
            |e| e.timestamp = "nonsense".to_string(),
            SkipReason::BadTimestamp,
        ),
        (
            "malformed properties",
            |e| e.properties = Some("{not json".to_string()),
            SkipReason::GlobalsParseError,
        ),
        (
            "malformed person_properties",
            |e| e.person_properties = Some("nope".to_string()),
            SkipReason::GlobalsParseError,
        ),
    ];

    for (name, mutate, expected) in cases {
        let mut ev = event(person(1), 1, 0);
        mutate(&mut ev);
        let out = process_event(PARTITION_ID, &store, &filters, &ev).unwrap();
        assert_eq!(out.skipped, Some(expected), "{name}");
        assert!(out.transitions.is_empty(), "{name}");
    }

    let empty = TeamFiltersBuilder::default().freeze(UTC);
    let out = process_event(PARTITION_ID, &store, &empty, &event(person(1), 1, 0)).unwrap();
    assert_eq!(out.skipped, Some(SkipReason::NoConditions));
}

#[test]
fn behavioral_records_and_emits_only_on_match() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![behavioral_leaf(7)]))]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let alice = person(1);

    let non_match = CohortStreamEvent {
        event: "$autocapture".to_string(),
        ..event(alice, 1, 0)
    };
    let out = process_event(PARTITION_ID, &store, &filters, &non_match).unwrap();
    assert_eq!(out.skipped, None);
    assert!(out.transitions.is_empty());
    assert!(
        state_at(&store, lsk, alice).is_none(),
        "no write on non-match"
    );

    let out = process_event(PARTITION_ID, &store, &filters, &event(alice, 1, 1)).unwrap();
    assert_eq!(out.transitions.len(), 1);
    assert!(state_at(&store, lsk, alice).is_some());
}

#[test]
fn person_records_every_event_with_no_false_to_false_transition() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![person_leaf()]))]);
    let carol = person(1);
    let lsk = LeafStateKey::for_person_property(&PERSON_HASH);

    let miss = person_event(carol, "nope@x.com", "2026-05-26 12:00:00.000000", 1, 10);
    let out = process_event(PARTITION_ID, &store, &filters, &miss).unwrap();
    assert!(out.transitions.is_empty(), "no false→false transition");
    match state_at(&store, lsk, carol).expect("row written even on non-match") {
        Stage1State::PersonProperty { matches, .. } => assert!(!matches),
        other => panic!("expected PersonProperty, got {other:?}"),
    }

    let hit = person_event(carol, "u@p.com", "2026-05-26 13:00:00.000000", 1, 11);
    let out = process_event(PARTITION_ID, &store, &filters, &hit).unwrap();
    assert_eq!(out.transitions.len(), 1);
    assert_eq!(out.transitions[0].kind, TransitionKind::Entered);
}

#[test]
fn person_property_flip_to_non_match_emits_left() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![person_leaf()]))]);
    let dave = person(1);

    let enter = person_event(dave, "u@p.com", "2026-05-26 12:00:00.000000", 1, 10);
    let out = process_event(PARTITION_ID, &store, &filters, &enter).unwrap();
    assert_eq!(out.transitions[0].kind, TransitionKind::Entered);

    let leave = person_event(dave, "nope@x.com", "2026-05-26 13:00:00.000000", 1, 11);
    let out = process_event(PARTITION_ID, &store, &filters, &leave).unwrap();
    assert_eq!(out.transitions.len(), 1);
    assert_eq!(out.transitions[0].kind, TransitionKind::Left);
    assert_eq!(
        transition_kind(&filters, &out.transitions[0]),
        "person_left"
    );
}

#[test]
fn person_path_is_inactive_for_null_or_empty_person_properties() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![person_leaf()]))]);
    let erin = person(1);
    let lsk = LeafStateKey::for_person_property(&PERSON_HASH);

    // Null and empty-string are both JS-falsy → person path never runs → processed no-op, no row.
    for (offset, payload) in [(10, None), (11, Some(String::new()))] {
        let ev = CohortStreamEvent {
            person_properties: payload,
            ..event(erin, 1, offset)
        };
        let out = process_event(PARTITION_ID, &store, &filters, &ev).unwrap();
        assert_eq!(out.skipped, None, "processed as a no-op, not skipped whole");
        assert!(out.transitions.is_empty());
        assert!(
            state_at(&store, lsk, erin).is_none(),
            "no person row written"
        );
    }
}

#[test]
fn empty_person_properties_does_not_skip_a_behavioral_match() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf(7), person_leaf()]),
    )]);
    let behavioral_lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let person_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
    let alice = person(1);

    // Empty-string person_properties is JS-falsy: Node skips the person path but still runs the
    // behavioral one, so it must not skip the whole event and drop the behavioral match.
    let ev = CohortStreamEvent {
        person_properties: Some(String::new()),
        ..event(alice, 1, 0)
    };
    let out = process_event(PARTITION_ID, &store, &filters, &ev).unwrap();

    assert_eq!(
        out.skipped, None,
        "empty person_properties is not a whole-event skip"
    );
    assert_eq!(out.transitions.len(), 1);
    assert_eq!(out.transitions[0].kind, TransitionKind::Entered);
    assert_eq!(
        transition_kind(&filters, &out.transitions[0]),
        "behavioral_entered"
    );
    assert!(
        state_at(&store, behavioral_lsk, alice).is_some(),
        "behavioral row written"
    );
    assert!(
        state_at(&store, person_lsk, alice).is_none(),
        "empty person_properties → person path inactive, no row",
    );
}

#[test]
fn non_boolean_person_result_coerces_to_false() {
    let (_dir, store) = temp_store();
    let nonbool = person_leaf_with_bytecode(json!(["_H", 1, 33, 42]));
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![nonbool]))]);
    let frank = person(1);
    let lsk = LeafStateKey::for_person_property(&PERSON_HASH);

    let out = process_event(PARTITION_ID, &store, &filters, &event(frank, 1, 0)).unwrap();
    assert!(out.transitions.is_empty(), "false → no enter");
    match state_at(&store, lsk, frank).expect("row written") {
        Stage1State::PersonProperty { matches, .. } => {
            assert!(!matches, "non-bool result coerced to false")
        }
        other => panic!("expected PersonProperty, got {other:?}"),
    }
}

#[tokio::test]
async fn spawned_worker_drains_a_batch_and_commits_state() {
    let (_dir, store) = temp_store();
    // Composable cohort: this one event matches and flips both leaves, so Stage 2 composes a single
    // `entered` for the cohort.
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf(7), person_leaf()]),
    )]);
    let behavioral_lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let person_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
    let alice = person(1);

    let catalog = catalog_of(filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());

    let (tx, rx) = mpsc::channel(16);
    let rx = MeteredReceiver::new(rx, std::sync::Arc::new(PartitionIntake::new(0, usize::MAX)));
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        store.clone(),
        catalog,
        Arc::new(sink.clone()),
        tracker.clone(),
        MergeWorkerDeps::capture(),
        false,
    );

    dispatch_to_worker(&tracker, &tx, event(alice, 1, 0), 0).await;
    // Closing the channel makes the worker drain the queued batch and exit.
    drop(tx);
    worker.join().await.unwrap();

    assert!(state_at(&store, behavioral_lsk, alice).is_some());
    assert!(state_at(&store, person_lsk, alice).is_some());
    assert_eq!(
        store
            .get_person_index(&person_index_key(alice))
            .unwrap()
            .len(),
        2
    );
    let changes = sink.changes();
    assert_eq!(
        changes.len(),
        1,
        "both leaves flipping in one event composes a single entered",
    );
    assert_eq!(changes[0].cohort_id, 1);
    assert_eq!(changes[0].status, MembershipStatus::Entered);
    assert_eq!(changes[0].person_id, alice.to_string());
    assert_eq!(
        tracker.committable_offsets().get(&(PARTITION_ID as i32)),
        Some(&1)
    );
}

#[tokio::test]
async fn spawned_worker_composes_two_leaf_cohort_and_emits_single_leaf_independently() {
    let (_dir, store) = temp_store();
    // Cohort 1 ANDs a behavioral and a person leaf (composable); cohort 2 is the bare behavioral leaf
    // (single-leaf), sharing cohort 1's behavioral leaf.
    let filters = build_team_filters(vec![
        (CohortId(1), cohort(vec![behavioral_leaf(7), person_leaf()])),
        (CohortId(2), cohort(vec![behavioral_leaf(7)])),
    ]);
    let alice = person(1);

    let catalog = catalog_of(filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());

    let (tx, rx) = mpsc::channel(16);
    let rx = MeteredReceiver::new(rx, std::sync::Arc::new(PartitionIntake::new(0, usize::MAX)));
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        store.clone(),
        catalog,
        Arc::new(sink.clone()),
        tracker.clone(),
        MergeWorkerDeps::capture(),
        false,
    );

    // Event A flips only the behavioral leaf (non-matching email): the single-leaf cohort 2 enters,
    // while the composable cohort 1 stays out — its person leaf is still false.
    dispatch_to_worker(
        &tracker,
        &tx,
        person_event(
            alice,
            "other@example.com",
            "2026-05-26 12:00:00.000000",
            1,
            0,
        ),
        0,
    )
    .await;
    // Event B flips the person leaf: cohort 1's AND is now satisfied, so it enters; cohort 2 is
    // untouched (its leaf did not transition this event).
    dispatch_to_worker(
        &tracker,
        &tx,
        person_event(alice, "u@p.com", "2026-05-26 12:00:01.000000", 1, 1),
        1,
    )
    .await;
    drop(tx);
    worker.join().await.unwrap();

    let mut emitted: Vec<(i32, MembershipStatus)> = sink
        .changes()
        .iter()
        .map(|change| (change.cohort_id, change.status))
        .collect();
    emitted.sort_by_key(|(cohort, _)| *cohort);
    assert_eq!(
        emitted,
        vec![
            (1, MembershipStatus::Entered),
            (2, MembershipStatus::Entered),
        ],
        "single-leaf cohort 2 enters on its leaf's flip; composable cohort 1 enters only once both \
         of its leaves are true, and exactly once",
    );
}

#[tokio::test]
async fn spawned_worker_skips_events_for_unknown_teams() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![behavioral_leaf(7)]))]);
    let behavioral_lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let alice = person(1);

    let catalog = catalog_of(filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());

    let (tx, rx) = mpsc::channel(16);
    let rx = MeteredReceiver::new(rx, std::sync::Arc::new(PartitionIntake::new(0, usize::MAX)));
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        store.clone(),
        catalog,
        Arc::new(sink.clone()),
        tracker.clone(),
        MergeWorkerDeps::capture(),
        false,
    );

    // Skipped before touching the store, but the offset must still advance (no partition wedge).
    let unknown = CohortStreamEvent {
        team_id: 999,
        ..event(alice, 1, 0)
    };
    dispatch_to_worker(&tracker, &tx, unknown, 3).await;
    drop(tx);
    worker.join().await.unwrap();

    let key = Stage1Key {
        partition_id: PARTITION_ID,
        team_id: 999,
        leaf_state_key: behavioral_lsk,
        person_id: alice,
    };
    assert!(
        store.get_stage1(&key).unwrap().is_none(),
        "no write for unknown team"
    );
    assert!(sink.changes().is_empty());
    assert_eq!(
        tracker.committable_offsets().get(&(PARTITION_ID as i32)),
        Some(&4)
    );
}

fn single_leaf_catalog() -> Arc<CatalogHandle> {
    catalog_of(build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf(7)]),
    )]))
}

#[tokio::test]
async fn worker_produces_changes_and_advances_offset() {
    let (_dir, store) = temp_store();
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());

    let (tx, rx) = mpsc::channel(16);
    let rx = MeteredReceiver::new(rx, std::sync::Arc::new(PartitionIntake::new(0, usize::MAX)));
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        store.clone(),
        single_leaf_catalog(),
        Arc::new(sink.clone()),
        tracker.clone(),
        MergeWorkerDeps::capture(),
        false,
    );

    dispatch_to_worker(&tracker, &tx, event(person(1), 1, 0), 5).await;
    drop(tx);
    worker.join().await.unwrap();

    assert_eq!(
        tracker.committable_offsets().get(&(PARTITION_ID as i32)),
        Some(&6)
    );
    let changes = sink.changes();
    assert_eq!(changes.len(), 1);
    assert_eq!(changes[0].cohort_id, 1);
    assert_eq!(changes[0].status, MembershipStatus::Entered);
    assert_eq!(changes[0].person_id, person(1).to_string());
}

#[tokio::test]
async fn worker_advances_offset_on_empty_transition_subbatch() {
    // A no-op (or poison) event must not wedge the partition: the offset still advances.
    let (_dir, store) = temp_store();
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());

    let (tx, rx) = mpsc::channel(16);
    let rx = MeteredReceiver::new(rx, std::sync::Arc::new(PartitionIntake::new(0, usize::MAX)));
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        store.clone(),
        single_leaf_catalog(),
        Arc::new(sink.clone()),
        tracker.clone(),
        MergeWorkerDeps::capture(),
        false,
    );

    let non_match = CohortStreamEvent {
        event: "$autocapture".to_string(),
        ..event(person(1), 1, 0)
    };
    dispatch_to_worker(&tracker, &tx, non_match, 42).await;
    drop(tx);
    worker.join().await.unwrap();

    assert_eq!(
        tracker.committable_offsets().get(&(PARTITION_ID as i32)),
        Some(&43),
        "an empty sub-batch still advances the offset",
    );
    assert!(sink.changes().is_empty());
}

#[tokio::test]
async fn worker_holds_offset_when_the_only_flush_fails() {
    let (_dir, store) = temp_store();
    let sink = CaptureSink::failing_first(1);
    let tracker = Arc::new(OffsetTracker::new());

    let (tx, rx) = mpsc::channel(16);
    let rx = MeteredReceiver::new(rx, std::sync::Arc::new(PartitionIntake::new(0, usize::MAX)));
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        store.clone(),
        single_leaf_catalog(),
        Arc::new(sink.clone()),
        tracker.clone(),
        MergeWorkerDeps::capture(),
        false,
    );

    dispatch_to_worker(&tracker, &tx, event(person(1), 1, 0), 10).await;
    drop(tx);
    worker.join().await.unwrap();

    assert_eq!(
        tracker.committable_offsets().get(&(PARTITION_ID as i32)),
        None,
        "a failed produce holds the offset back for replay",
    );
    assert!(sink.changes().is_empty(), "a failed flush emits nothing");
}

#[tokio::test]
async fn worker_keeps_processing_after_a_produce_failure() {
    let (_dir, store) = temp_store();
    let sink = CaptureSink::failing_first(1);
    let tracker = Arc::new(OffsetTracker::new());

    let (tx, rx) = mpsc::channel(16);
    let rx = MeteredReceiver::new(rx, std::sync::Arc::new(PartitionIntake::new(0, usize::MAX)));
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        store.clone(),
        single_leaf_catalog(),
        Arc::new(sink.clone()),
        tracker.clone(),
        MergeWorkerDeps::capture(),
        false,
    );

    dispatch_to_worker(&tracker, &tx, event(person(1), 1, 0), 10).await;
    dispatch_to_worker(&tracker, &tx, event(person(2), 1, 1), 11).await;
    drop(tx);
    worker.join().await.unwrap();

    // The second flush's success advances the offset to 12; the held first event relies on replay.
    assert_eq!(
        tracker.committable_offsets().get(&(PARTITION_ID as i32)),
        Some(&12)
    );
    let changes = sink.changes();
    assert_eq!(changes.len(), 1, "only the second flush's change landed");
    assert_eq!(changes[0].person_id, person(2).to_string());
}

#[test]
fn daily_multiple_enters_when_count_crosses_threshold() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf_multiple(7, "gte", 3)]),
    )]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    assert_eq!(
        filters.by_lsk[&lsk].variant,
        StateVariant::BehavioralDailyBuckets,
    );
    let alice = person(1);

    // Three matching events on consecutive days, all inside the 7-day window.
    let days = [
        "2026-05-20 10:00:00.000000",
        "2026-05-21 11:00:00.000000",
        "2026-05-22 09:30:00.000000",
    ];
    for (offset, ts) in days[..2].iter().enumerate() {
        let out = process_event(
            PARTITION_ID,
            &store,
            &filters,
            &event_at(alice, ts, 1, offset as i64),
        )
        .unwrap();
        assert!(out.transitions.is_empty(), "count below 3 → no transition");
    }
    assert_eq!(window_count(&state_at(&store, lsk, alice).unwrap()), 2);

    // The third event crosses `gte 3`.
    let out = process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(alice, days[2], 1, 2),
    )
    .unwrap();
    assert_eq!(out.transitions.len(), 1);
    assert_eq!(out.transitions[0].kind, TransitionKind::Entered);
    assert_eq!(
        transition_kind(&filters, &out.transitions[0]),
        "behavioral_daily_entered",
    );
    assert_eq!(window_count(&state_at(&store, lsk, alice).unwrap()), 3);
}

#[test]
fn daily_multiple_slide_drops_contributing_bucket_and_emits_left() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf_multiple(7, "gte", 3)]),
    )]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let alice = person(1);

    // Three matches on the same day → one bucket of count 3 → Entered on the third.
    let day = "2026-05-20 10:00:00.000000";
    for offset in 0..3 {
        let out = process_event(
            PARTITION_ID,
            &store,
            &filters,
            &event_at(alice, day, 1, offset),
        )
        .unwrap();
        if offset < 2 {
            assert!(out.transitions.is_empty());
        } else {
            assert_eq!(out.transitions[0].kind, TransitionKind::Entered);
        }
    }
    assert_eq!(
        window_count(&state_at(&store, lsk, alice).unwrap()),
        3,
        "all three accumulate in one day-bucket",
    );

    // A match 8 days later slides the whole window past that bucket: it falls out, and the slide event
    // itself only contributes 1 → count 1 < 3 → Left.
    let out = process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(alice, "2026-05-28 10:00:00.000000", 1, 3),
    )
    .unwrap();
    assert_eq!(out.transitions.len(), 1);
    assert_eq!(out.transitions[0].kind, TransitionKind::Left);
    assert_eq!(
        transition_kind(&filters, &out.transitions[0]),
        "behavioral_daily_left",
    );
    assert_eq!(
        window_count(&state_at(&store, lsk, alice).unwrap()),
        1,
        "only the slide event remains in the window",
    );
}

#[test]
fn daily_multiple_counts_same_day_repeats_in_one_bucket() {
    // Proves the daily state is a counter, not a bit: two same-day matches show count 2 in one bucket.
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf_multiple(7, "gte", 5)]), // high threshold: inspect state, no flip
    )]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let alice = person(1);

    let day = "2026-05-20 10:00:00.000000";
    process_event(PARTITION_ID, &store, &filters, &event_at(alice, day, 1, 0)).unwrap();
    let out = process_event(PARTITION_ID, &store, &filters, &event_at(alice, day, 1, 1)).unwrap();
    assert!(out.transitions.is_empty(), "count 2 is still under gte 5");

    let state = state_at(&store, lsk, alice).unwrap();
    let (buckets, _, _) = daily_state(&state);
    assert_eq!(
        buckets.iter().filter(|&&count| count > 0).count(),
        1,
        "both matches land in a single day-bucket",
    );
    assert_eq!(
        buckets.iter().copied().max().unwrap(),
        2,
        "that bucket counts 2 — a bit would read 1",
    );
    assert_eq!(window_count(&state), 2);
}

#[test]
fn daily_multiple_cross_partition_replay_after_slide_is_byte_identical() {
    // Skip vs re-fold are NOT state-identical here, so byte-identity proves `is_replay` fired.
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf_multiple(7, "gte", 1)]),
    )]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let p = person(1);

    // Event from partition 10 (offset 5) on 05-20, then a later event from partition 20 (offset 10) on
    // 05-23 that slides the window forward.
    process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(p, "2026-05-20 10:00:00.000000", 10, 5),
    )
    .unwrap();
    process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(p, "2026-05-23 10:00:00.000000", 20, 10),
    )
    .unwrap();

    let before = record_at(&store, lsk, p).unwrap();
    assert_high_water(&before.applied_offsets, 10, 5);
    assert_high_water(&before.applied_offsets, 20, 10);

    // Replay partition 10's original event (offset 5 ≤ 5): is_replay fires regardless of the slide.
    let out = process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(p, "2026-05-20 10:00:00.000000", 10, 5),
    )
    .unwrap();
    assert!(out.transitions.is_empty(), "a replay flips nothing");

    let after = record_at(&store, lsk, p).unwrap();
    assert_eq!(
        after, before,
        "the replay neither re-folded its bucket nor disturbed partition 20's high-water mark",
    );
}

#[test]
fn daily_multiple_late_behind_event_records_offset_without_counting() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf_multiple(2, "gte", 1)]),
    )]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let alice = person(1);

    // Newest event first (offset 10) on 05-27 → window covers [05-25 ..= 05-27].
    let out = process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(alice, "2026-05-27 12:00:00.000000", 1, 10),
    )
    .unwrap();
    assert_eq!(out.transitions[0].kind, TransitionKind::Entered);
    let before = record_at(&store, lsk, alice).unwrap();

    // A late event before the window's lower bound (05-22 < 05-25): behind the window, so it does not
    // count — but it is a genuine new offset and must be recorded.
    let out = process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(alice, "2026-05-22 12:00:00.000000", 1, 11),
    )
    .unwrap();
    assert!(
        out.transitions.is_empty(),
        "a behind-window event flips nothing"
    );

    let after = record_at(&store, lsk, alice).unwrap();
    assert_eq!(
        after.state, before.state,
        "the behind-window event left the buckets, window, deadline, and newest-event all unchanged",
    );
    assert_high_water(&after.applied_offsets, 1, 11);
}

#[test]
fn daily_multiple_eq_or_lte_zero_is_never_a_member() {
    for op in ["eq", "lte"] {
        let (_dir, store) = temp_store();
        let filters = build_team_filters(vec![(
            CohortId(1),
            cohort(vec![behavioral_leaf_multiple(7, op, 0)]),
        )]);
        let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
        let alice = person(1);

        let out = process_event(
            PARTITION_ID,
            &store,
            &filters,
            &event_at(alice, "2026-05-20 10:00:00.000000", 1, 0),
        )
        .unwrap();
        assert!(
            out.transitions.is_empty(),
            "{op} 0 over count 1 is not a member → no transition",
        );
        assert_eq!(
            window_count(&state_at(&store, lsk, alice).unwrap()),
            1,
            "{op}: the match is still counted in state",
        );
    }
}

#[test]
fn daily_multiple_stores_eviction_deadline_at_oldest_bucket_day_boundary() {
    let (_dir, store) = temp_store();
    let window_days = 7;
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf_multiple(window_days, "gte", 1)]),
    )]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let alice = person(1);

    let ts = "2026-05-20 10:00:00.000000";
    process_event(PARTITION_ID, &store, &filters, &event_at(alice, ts, 1, 0)).unwrap();

    let state = state_at(&store, lsk, alice).unwrap();
    let (_, window_start_day, deadline) = daily_state(&state);
    let event_day = day_idx_in_tz(clickhouse_timestamp_to_millis(ts).unwrap(), UTC);
    assert_eq!(
        window_start_day,
        event_day - window_days as i32,
        "the lone event sits in the window's last bucket (the now-day)",
    );
    assert_eq!(
        deadline,
        start_of_day_ms_in_tz(event_day + window_days as i32 + 1, UTC),
        "oldest non-zero bucket leaves at start of day event_day + window_days + 1",
    );
}

#[test]
fn daily_multiple_buckets_by_team_timezone_day_not_utc_day() {
    let (_dir, store) = temp_store();
    let window_days = 7;
    let filters = build_team_filters_tz(
        vec![(
            CohortId(1),
            cohort(vec![behavioral_leaf_multiple(window_days, "gte", 1)]),
        )],
        Kolkata,
    );
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let alice = person(1);

    let ts = "2026-05-26 20:00:00.000000"; // 20:00 UTC = 01:30 next-day Kolkata
    let event_ms = clickhouse_timestamp_to_millis(ts).unwrap();
    let kolkata_day = day_idx_in_tz(event_ms, Kolkata);
    let utc_day = day_idx_in_tz(event_ms, UTC);
    assert_eq!(
        kolkata_day,
        utc_day + 1,
        "the chosen instant lands on different UTC and Kolkata calendar days",
    );

    let out = process_event(PARTITION_ID, &store, &filters, &event_at(alice, ts, 1, 0)).unwrap();
    assert_eq!(out.transitions[0].kind, TransitionKind::Entered);

    let state = state_at(&store, lsk, alice).unwrap();
    let (_, window_start_day, deadline) = daily_state(&state);
    assert_eq!(
        window_start_day,
        kolkata_day - window_days as i32,
        "the fresh window anchors on the team-tz (Kolkata) now-day",
    );
    assert_ne!(
        window_start_day,
        utc_day - window_days as i32,
        "a UTC-hardcoded fold would anchor one day earlier — this is the discriminating assertion",
    );
    // The deadline is the Kolkata local-midnight the lone bucket leaves the window, and that instant
    // differs from the UTC anchoring (Kolkata midnight is 18:30 UTC the prior day).
    assert_eq!(
        deadline,
        start_of_day_ms_in_tz(kolkata_day + window_days as i32 + 1, Kolkata),
        "eviction anchors on Kolkata local midnight",
    );
    assert_ne!(
        deadline,
        start_of_day_ms_in_tz(utc_day + window_days as i32 + 1, UTC),
        "a UTC-hardcoded fold would compute a different deadline",
    );
}

#[test]
fn daily_multiple_event_on_window_start_day_counts_in_bucket_zero() {
    // An event landing exactly on `window_start_day` is within, not behind, and counts in bucket 0.
    let (_dir, store) = temp_store();
    let window_days = 2;
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf_multiple(window_days, "gte", 1)]),
    )]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let alice = person(1);

    // Newest event first (offset 10) on 05-27 → window covers [05-25 ..= 05-27], so window_start_day is
    // 05-25 and this event lands in the last bucket (the now-day), leaving bucket 0 empty.
    let out = process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(alice, "2026-05-27 12:00:00.000000", 1, 10),
    )
    .unwrap();
    assert_eq!(out.transitions[0].kind, TransitionKind::Entered);
    let before = state_at(&store, lsk, alice).unwrap();
    let (buckets_before, window_start_day, _) = daily_state(&before);
    assert_eq!(
        window_start_day,
        day_of("2026-05-25 00:00:00.000000"),
        "window_start_day is the inclusive lower bound, day 05-25",
    );
    assert_eq!(buckets_before[0], 0, "the boundary bucket starts empty");
    assert_eq!(window_count(&before), 1);

    // An event landing exactly on window_start_day (05-25): event_day == window_start_day, so it is
    // WITHIN (not the strict `event_day < window_start_day` BEHIND drop) and counts in bucket 0.
    let out = process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(alice, "2026-05-25 23:00:00.000000", 1, 11),
    )
    .unwrap();
    assert!(
        out.transitions.is_empty(),
        "already a member (count 1 → 2) → no transition",
    );

    let after = state_at(&store, lsk, alice).unwrap();
    let (buckets_after, window_start_after, _) = daily_state(&after);
    assert_eq!(
        window_start_after, window_start_day,
        "an in-window event does not slide the window",
    );
    assert_eq!(
        buckets_after[0], 1,
        "the boundary-day event counts in bucket 0 (inclusive lower bound)",
    );
    assert_eq!(
        window_count(&after),
        2,
        "the boundary event is counted, not dropped as behind",
    );
}

#[tokio::test]
async fn daily_multiple_single_leaf_cohort_emits_entered_then_left_to_the_sink() {
    let (_dir, store) = temp_store();
    let catalog = catalog_of(build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf_multiple(7, "gte", 3)]),
    )]));
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());

    let (tx, rx) = mpsc::channel(16);
    let rx = MeteredReceiver::new(rx, std::sync::Arc::new(PartitionIntake::new(0, usize::MAX)));
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        store.clone(),
        catalog,
        Arc::new(sink.clone()),
        tracker.clone(),
        MergeWorkerDeps::capture(),
        false,
    );

    let alice = person(1);
    let day = "2026-05-20 10:00:00.000000";
    // Three same-day matches enter on the third; a far event slides them out → Left.
    dispatch_to_worker(&tracker, &tx, event_at(alice, day, 1, 0), 0).await;
    dispatch_to_worker(&tracker, &tx, event_at(alice, day, 1, 1), 1).await;
    dispatch_to_worker(&tracker, &tx, event_at(alice, day, 1, 2), 2).await;
    dispatch_to_worker(
        &tracker,
        &tx,
        event_at(alice, "2026-05-28 10:00:00.000000", 1, 3),
        3,
    )
    .await;
    drop(tx);
    worker.join().await.unwrap();

    let changes = sink.changes();
    assert_eq!(
        changes.len(),
        2,
        "one Entered (3rd event) + one Left (slide)"
    );
    assert_eq!(changes[0].cohort_id, 1);
    assert_eq!(changes[0].status, MembershipStatus::Entered);
    assert_eq!(changes[0].person_id, alice.to_string());
    assert_eq!(changes[1].status, MembershipStatus::Left);
    assert_eq!(
        tracker.committable_offsets().get(&(PARTITION_ID as i32)),
        Some(&4),
    );
}

fn day_of(ts: &str) -> i32 {
    day_idx_in_tz(clickhouse_timestamp_to_millis(ts).unwrap(), UTC)
}

#[test]
fn compressed_multiple_enters_when_count_crosses_threshold() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf_multiple(
            COMPRESSED_WINDOW_DAYS,
            "gte",
            3,
        )]),
    )]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    assert_eq!(
        filters.by_lsk[&lsk].variant,
        StateVariant::BehavioralCompressedHistory,
        "a 365-day window routes to compressed history",
    );
    let alice = person(1);

    // Three matching events on three different days, all inside the 365-day window.
    let days = [
        "2026-01-10 10:00:00.000000",
        "2026-03-15 11:00:00.000000",
        "2026-05-20 09:30:00.000000",
    ];
    for (offset, ts) in days[..2].iter().enumerate() {
        let out = process_event(
            PARTITION_ID,
            &store,
            &filters,
            &event_at(alice, ts, 1, offset as i64),
        )
        .unwrap();
        assert!(out.transitions.is_empty(), "count below 3 → no transition");
    }
    assert_eq!(compressed_count(&state_at(&store, lsk, alice).unwrap()), 2);

    // The third event crosses `gte 3`.
    let out = process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(alice, days[2], 1, 2),
    )
    .unwrap();
    assert_eq!(out.transitions.len(), 1);
    assert_eq!(out.transitions[0].kind, TransitionKind::Entered);
    assert_eq!(
        transition_kind(&filters, &out.transitions[0]),
        "behavioral_compressed_entered",
    );
    assert_eq!(compressed_count(&state_at(&store, lsk, alice).unwrap()), 3);
}

#[test]
fn compressed_multiple_slide_drops_contributing_day_and_emits_left() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf_multiple(
            COMPRESSED_WINDOW_DAYS,
            "gte",
            3,
        )]),
    )]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let alice = person(1);

    // Three matches on the same day → one entry of count 3 → Entered on the third.
    let day = "2025-01-10 10:00:00.000000";
    for offset in 0..3 {
        let out = process_event(
            PARTITION_ID,
            &store,
            &filters,
            &event_at(alice, day, 1, offset),
        )
        .unwrap();
        if offset < 2 {
            assert!(out.transitions.is_empty());
        } else {
            assert_eq!(out.transitions[0].kind, TransitionKind::Entered);
        }
    }
    assert_eq!(
        compressed_count(&state_at(&store, lsk, alice).unwrap()),
        3,
        "all three accumulate in one day-entry",
    );

    // A match well over 365 days later slides the whole window past that entry: it falls out, and the
    // slide event itself only contributes 1 → count 1 < 3 → Left.
    let slide_ts = "2026-06-01 10:00:00.000000";
    let out = process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(alice, slide_ts, 1, 3),
    )
    .unwrap();
    assert_eq!(out.transitions.len(), 1);
    assert_eq!(out.transitions[0].kind, TransitionKind::Left);
    assert_eq!(
        transition_kind(&filters, &out.transitions[0]),
        "behavioral_compressed_left",
    );
    let state = state_at(&store, lsk, alice).unwrap();
    assert_eq!(
        compressed_count(&state),
        1,
        "only the slide event remains in the window",
    );
    assert_eq!(
        compressed_state(&state).0,
        &[(day_of(slide_ts), 1)],
        "the aged-out day entry was pruned, leaving only the slide day",
    );
}

#[test]
fn compressed_multiple_accumulates_sparsely_across_days() {
    // Proves the compressed state stores one entry per matching day (sparse), counts repeats in place,
    // and stays sorted — a dense array would hold 366 slots for the same data.
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf_multiple(
            COMPRESSED_WINDOW_DAYS,
            "gte",
            10,
        )]), // high: inspect, no flip
    )]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let alice = person(1);

    let day_a = "2026-01-10 10:00:00.000000";
    let day_b = "2026-02-20 11:00:00.000000";
    let day_c = "2026-04-05 09:00:00.000000";
    // day_a ×2, day_b ×1, day_c ×3 (count 6) — sent interleaved to exercise the sorted in-place insert.
    for (offset, ts) in [day_a, day_c, day_b, day_a, day_c, day_c]
        .iter()
        .enumerate()
    {
        let out = process_event(
            PARTITION_ID,
            &store,
            &filters,
            &event_at(alice, ts, 1, offset as i64),
        )
        .unwrap();
        assert!(out.transitions.is_empty(), "count 6 stays under gte 10");
    }

    let state = state_at(&store, lsk, alice).unwrap();
    assert_eq!(
        compressed_state(&state).0,
        &[(day_of(day_a), 2), (day_of(day_b), 1), (day_of(day_c), 3)],
        "one sorted entry per matching day, repeats counted in place",
    );
    assert_eq!(compressed_count(&state), 6);
}

#[test]
fn compressed_multiple_late_behind_event_records_offset_without_counting() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf_multiple(
            COMPRESSED_WINDOW_DAYS,
            "gte",
            1,
        )]),
    )]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let alice = person(1);

    // Newest event first (offset 10) on 2026-05-27 → window covers [2025-05-27 ..= 2026-05-27].
    let out = process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(alice, "2026-05-27 12:00:00.000000", 1, 10),
    )
    .unwrap();
    assert_eq!(out.transitions[0].kind, TransitionKind::Entered);
    let before = record_at(&store, lsk, alice).unwrap();

    // A late event well before the window's lower bound (2024-01-01 ≪ 2025-05-27): behind the window,
    // so it does not count — but it is a genuine new offset and must be recorded.
    let out = process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(alice, "2024-01-01 12:00:00.000000", 1, 11),
    )
    .unwrap();
    assert!(
        out.transitions.is_empty(),
        "a behind-window event flips nothing"
    );

    let after = record_at(&store, lsk, alice).unwrap();
    assert_eq!(
        after.state, before.state,
        "the behind-window event left the entries, window, deadline, and newest-event all unchanged",
    );
    assert_high_water(&after.applied_offsets, 1, 11);
}

#[test]
fn compressed_multiple_cross_partition_replay_after_slide_is_byte_identical() {
    // Skip vs re-fold are not state-identical here, so byte-identity proves `is_replay` fired.
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf_multiple(
            COMPRESSED_WINDOW_DAYS,
            "gte",
            1,
        )]),
    )]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let p = person(1);

    // Event from partition 10 (offset 5) on 2025-01-10, then a later event from partition 20 (offset
    // 10) on 2025-04-15 that slides the window forward (both days stay inside the 365-day window).
    process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(p, "2025-01-10 10:00:00.000000", 10, 5),
    )
    .unwrap();
    process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(p, "2025-04-15 10:00:00.000000", 20, 10),
    )
    .unwrap();

    let before = record_at(&store, lsk, p).unwrap();
    assert_high_water(&before.applied_offsets, 10, 5);
    assert_high_water(&before.applied_offsets, 20, 10);
    assert_eq!(
        compressed_count(&before.state),
        2,
        "both days are inside the window",
    );

    // Replay partition 10's original event (offset 5 ≤ 5): is_replay fires regardless of the slide.
    let out = process_event(
        PARTITION_ID,
        &store,
        &filters,
        &event_at(p, "2025-01-10 10:00:00.000000", 10, 5),
    )
    .unwrap();
    assert!(out.transitions.is_empty(), "a replay flips nothing");

    let after = record_at(&store, lsk, p).unwrap();
    assert_eq!(
        after, before,
        "the replay neither re-folded its entry nor disturbed partition 20's high-water mark",
    );
}

#[tokio::test]
async fn compressed_sweep_deletes_then_a_late_event_recreates_the_state() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf_multiple(
            COMPRESSED_WINDOW_DAYS,
            "gte",
            1,
        )]),
    )]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let catalog = catalog_of(filters);
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());

    let (tx, rx) = mpsc::channel(16);
    let rx = MeteredReceiver::new(rx, std::sync::Arc::new(PartitionIntake::new(0, usize::MAX)));
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        store.clone(),
        catalog,
        Arc::new(sink.clone()),
        tracker.clone(),
        MergeWorkerDeps::capture(),
        false,
    );

    let alice = person(1);
    let first_ts = "2025-01-15 10:00:00.000000";
    let first_day = day_of(first_ts);

    // The match enters the cohort and schedules eviction at start of day first_day + 365 + 1.
    dispatch_to_worker(&tracker, &tx, event_at(alice, first_ts, 1, 0), 0).await;
    // A sweep whose cutoff is past that deadline drains the lone entry → Left + delete.
    let cutoff = start_of_day_ms_in_tz(first_day + COMPRESSED_WINDOW_DAYS as i32 + 2, UTC);
    tx.send(vec![ShuffleMessage::Sweep {
        due_before_ms: cutoff,
    }])
    .await
    .unwrap();
    // A fresh event, well after the delete, re-creates the state from its own day and re-enters.
    let late_ts = "2026-06-01 10:00:00.000000";
    dispatch_to_worker(&tracker, &tx, event_at(alice, late_ts, 1, 1), 1).await;
    drop(tx);
    worker.join().await.unwrap();

    let statuses: Vec<MembershipStatus> =
        sink.changes().iter().map(|change| change.status).collect();
    assert_eq!(
        statuses,
        vec![
            MembershipStatus::Entered, // first event
            MembershipStatus::Left,    // sweep drains the window
            MembershipStatus::Entered, // the late event re-creates and re-enters
        ],
        "the sweep deletes the compressed state and a later event re-creates it",
    );

    // The re-created state holds only the late event's day, anchored at its own window.
    let state = state_at(&store, lsk, alice).expect("re-created by the late event");
    assert_eq!(
        compressed_state(&state).0,
        &[(day_of(late_ts), 1)],
        "re-created from the late event's own timestamp, not the deleted window",
    );
}

fn applied(entries: &[(i32, i64)]) -> AppliedOffsets {
    let mut applied = AppliedOffsets::default();
    for &(partition, offset) in entries {
        applied.record(partition, offset);
    }
    applied
}

/// Seed a person-property record (with a chosen dedup state) directly into `cf_stage1`.
fn seed_person_record(store: &CohortStore, lsk: LeafStateKey, who: Uuid, record: &StatefulRecord) {
    store
        .write_batch(|b| b.put_stage1(&stage1_key(lsk, who), &record.encode()))
        .unwrap();
}

#[test]
fn fresh_event_on_a_redirect_dedup_partition_still_folds_main_map_authoritative() {
    // A fresh (non-redirected) P_new event must dedup against the MAIN map, not an ancestor's
    // `redirect_dedup` entry.
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![person_leaf()]))]);
    let lsk = LeafStateKey::for_person_property(&PERSON_HASH);
    let p_new = person(2);
    let ancestor = person(1);

    // P_new: not a member, main offsets at partition 5 = 50, an ancestor entry at partition 5 = 100.
    let mut seed = StatefulRecord::new(
        Stage1State::PersonProperty {
            matches: false,
            last_updated_at_ms: 1_000,
            last_updated_offset: 0,
        },
        applied(&[(5, 50)]),
    );
    seed.redirect_dedup.insert(ancestor, applied(&[(5, 100)]));
    seed_person_record(&store, lsk, p_new, &seed);

    // A fresh event on partition 5 at offset 60: 60 > main's 50 ⇒ fold, even though 60 ≤ the ancestor
    // entry's 100. The matching email flips the person leaf false→true.
    let fresh = person_event(p_new, "u@p.com", BASE_TS, 5, 60);
    let out = process_event(PARTITION_ID, &store, &filters, &fresh).unwrap();

    assert_eq!(
        out.transitions.len(),
        1,
        "the fresh event folded and flipped"
    );
    assert_eq!(out.transitions[0].kind, TransitionKind::Entered);
    let after = record_at(&store, lsk, p_new).unwrap();
    assert!(matches!(
        after.state,
        Stage1State::PersonProperty { matches: true, .. }
    ));
    assert!(
        after.applied_offsets.is_replay(5, 60),
        "the main map advanced to the fresh event's offset",
    );
    assert!(
        after.redirect_dedup[&ancestor].is_replay(5, 100)
            && !after.redirect_dedup[&ancestor].is_replay(5, 101),
        "the ancestor entry is untouched by a normal event",
    );
}

#[test]
fn redirected_event_at_or_below_ancestor_max_is_skipped_then_above_folds() {
    // A redirected straggler (origin = P_old) must dedup against `redirect_dedup[P_old]`.
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![person_leaf()]))]);
    let lsk = LeafStateKey::for_person_property(&PERSON_HASH);
    let p_new = person(2);
    let p_old = person(1);

    // P_new is a member; P_old (an ancestor) folded up to offset 100 on partition 5.
    let mut seed = StatefulRecord::new(
        Stage1State::PersonProperty {
            matches: true,
            last_updated_at_ms: 1_000,
            last_updated_offset: 0,
        },
        applied(&[(5, 50)]),
    );
    seed.redirect_dedup.insert(p_old, applied(&[(5, 100)]));
    seed_person_record(&store, lsk, p_new, &seed);

    // A redirected event at offset 80 ≤ the ancestor's 100 → replay via redirect_dedup[P_old] → skip.
    let mut redirected_replay = person_event(p_new, "different@x.com", BASE_TS, 5, 80);
    redirected_replay.redirected_from = Some(p_old.to_string());
    let skipped = process_event(PARTITION_ID, &store, &filters, &redirected_replay).unwrap();
    assert!(
        skipped.transitions.is_empty(),
        "a redirected replay at/below the ancestor max is skipped",
    );
    assert!(
        matches!(
            record_at(&store, lsk, p_new).unwrap().state,
            Stage1State::PersonProperty { matches: true, .. }
        ),
        "the skipped replay leaves P_new's state unchanged",
    );

    // A redirected event at offset 101 > the ancestor's 100 → not a replay → folds (email no longer
    // matches → Left), and advances the ancestor entry.
    let mut redirected_new = person_event(p_new, "different@x.com", BASE_TS, 5, 101);
    redirected_new.redirected_from = Some(p_old.to_string());
    let folded = process_event(PARTITION_ID, &store, &filters, &redirected_new).unwrap();
    assert_eq!(
        folded.transitions.len(),
        1,
        "the above-max redirected event folds"
    );
    assert_eq!(folded.transitions[0].kind, TransitionKind::Left);
    let after = record_at(&store, lsk, p_new).unwrap();
    assert!(
        after.redirect_dedup[&p_old].is_replay(5, 101),
        "the ancestor entry advanced to the folded offset",
    );
    assert!(
        after.applied_offsets.is_replay(5, 50) && !after.applied_offsets.is_replay(5, 51),
        "the redirected fold did not touch the main map",
    );
}
