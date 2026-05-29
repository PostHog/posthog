//! PR 1.6 acceptance: the Stage 1 single-condition worker, driven end-to-end against a real
//! RocksDB through the public API (no Kafka). Synthetic events flow through
//! [`process_event`](cohort_stream_processor::workers::process_event); one case is driven through a
//! spawned [`Stage1Worker`](cohort_stream_processor::workers::Stage1Worker) + a test channel to
//! cover the drain loop and post-commit emission.
//!
//! Parse-layer behaviors from the §2.4 audit are covered by the in-crate classifier / catalog
//! tests and are cited rather than duplicated here:
//! - behavioral / person globals **shape** (full behavioral key set; person `project.id == team_id`)
//!   — `hogvm::globals` unit tests (`behavioral_globals_*`, `person_globals_are_the_small_strict_shape`).
//! - dropping leaves with no bytecode / conditionHash, skipping cohort-ref leaves, and behavioral
//!   `negation` being excluded from the key — `filters::leaf_classifier` / `filters::tree` /
//!   `stage1::key` unit tests and `tests/filter_catalog.rs`.
//!
//! What is exercised here is strictly worker-observable: which writes and transitions a sequence of
//! events produces, replay idempotence, the out-of-order argMax tiebreaker, and the whole-event
//! skip reasons.

use std::collections::BTreeMap;
use std::sync::Arc;

use cohort_stream_processor::consumers::CohortStreamEvent;
use cohort_stream_processor::filters::{
    CatalogHandle, CohortId, FilterCatalog, TeamFilters, TeamFiltersBuilder, TeamId,
};
use cohort_stream_processor::partitions::{OffsetTracker, ShuffleMessage};
use cohort_stream_processor::producer::{CaptureSink, MembershipStatus};
use cohort_stream_processor::stage1::{
    clickhouse_timestamp_to_millis, LeafTransition, Stage1State, StateVariant, StatefulRecord,
    TransitionKind,
};
use cohort_stream_processor::store::{
    CohortStore, LeafStateKey, PersonIndexKey, Stage1Key, StoreConfig,
};
use cohort_stream_processor::workers::{process_event, SkipReason, Stage1Worker};
use serde_json::{json, Value};
use tempfile::TempDir;
use tokio::sync::mpsc;
use uuid::Uuid;

const TEAM: i32 = 7;
const PARTITION_ID: u16 = 0;
/// The shared conditionHash for the behavioral leaves (16 ASCII chars).
const BEHAVIORAL_HASH: [u8; 16] = *b"0123456789abcdef";
/// A distinct conditionHash for the person leaf.
const PERSON_HASH: [u8; 16] = *b"fedcba9876543210";
/// `2026-05-26 12:34:56.789Z` in epoch ms — the base event's timestamp.
const BASE_TS: &str = "2026-05-26 12:34:56.789000";

// ── Fixtures ────────────────────────────────────────────────────────────────────

fn temp_store() -> (TempDir, CohortStore) {
    let dir = TempDir::new().unwrap();
    let config = StoreConfig {
        path: dir.path().join("db"),
        ..StoreConfig::default()
    };
    let store = CohortStore::open(&config).expect("open store");
    (dir, store)
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
    let mut builder = TeamFiltersBuilder::default();
    for (id, filters) in cohorts {
        builder
            .add_cohort(id, TeamId(TEAM), &filters)
            .expect("add cohort");
    }
    builder.freeze()
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

// ── Key + state helpers ──────────────────────────────────────────────────────────

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
    store
        .get_stage1(&stage1_key(lsk, person))
        .unwrap()
        .map(|bytes| StatefulRecord::decode(&bytes).unwrap().state)
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

/// The `stage1_transitions_total{kind}` label for a transition, resolved through the snapshot — the
/// same mapping the worker emits.
fn transition_kind(filters: &TeamFilters, transition: &LeafTransition) -> &'static str {
    let variant = filters.by_lsk[&transition.leaf_state_key].variant;
    match (variant, transition.kind) {
        (StateVariant::BehavioralSingle, TransitionKind::Entered) => "behavioral_entered",
        (StateVariant::BehavioralSingle, TransitionKind::Left) => "behavioral_left",
        (StateVariant::PersonProperty, TransitionKind::Entered) => "person_entered",
        (StateVariant::PersonProperty, TransitionKind::Left) => "person_left",
    }
}

// ── C1 regression (headline) ─────────────────────────────────────────────────────

#[test]
fn c1_same_hash_two_windows_get_independent_state_and_deadlines() {
    let (_dir, store) = temp_store();
    // Two cohorts, both performed_event on $pageview, windows 7d vs 30d → one conditionHash, two LSKs.
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

    // First match: one eval fans out to both LSKs → two Entered, independent state.
    let first = event(alice, 1, 10);
    let out = process_event(PARTITION_ID, &store, &filters, &first).unwrap();
    assert_eq!(out.skipped, None);
    assert_eq!(out.transitions.len(), 2);
    assert!(out
        .transitions
        .iter()
        .all(|t| t.kind == TransitionKind::Entered));

    let event_ms = clickhouse_timestamp_to_millis(BASE_TS).unwrap();
    let mut deadlines: Vec<i64> = lsks
        .iter()
        .map(|lsk| behavioral_deadline(&state_at(&store, *lsk, alice).unwrap()))
        .collect();
    deadlines.sort_unstable();
    assert_eq!(deadlines[0], event_ms + 7 * 86_400 * 1000);
    assert_eq!(deadlines[1], event_ms + 30 * 86_400 * 1000);
    assert_eq!(
        deadlines[1] - deadlines[0],
        (30 - 7) * 86_400 * 1000,
        "the two deadlines differ by exactly (30-7) days",
    );

    // Second match (later event): no new transitions, both deadlines advance with the new event.
    let later_ts = "2026-05-27 12:34:56.789000";
    let later_ms = clickhouse_timestamp_to_millis(later_ts).unwrap();
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
    assert_eq!(advanced[0], later_ms + 7 * 86_400 * 1000);
    assert_eq!(advanced[1], later_ms + 30 * 86_400 * 1000);

    // Replay the first event (lower offset, same partition): idempotent — no transition, deadlines
    // stay at the second event's values.
    let out = process_event(PARTITION_ID, &store, &filters, &first).unwrap();
    assert!(out.transitions.is_empty());
    let mut after_replay: Vec<i64> = lsks
        .iter()
        .map(|lsk| behavioral_deadline(&state_at(&store, *lsk, alice).unwrap()))
        .collect();
    after_replay.sort_unstable();
    assert_eq!(after_replay, advanced, "replay must not regress state");
}

// ── Late (out-of-order) behavioral event must not regress the eviction deadline ────

#[test]
fn behavioral_deadline_tracks_newest_event_not_the_late_one() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![behavioral_leaf(7)]))]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let alice = person(1);

    // The newest-by-event-time match arrives first (offset 10), at a LATER ts than BASE_TS.
    let later_ts = "2026-05-27 12:34:56.789000";
    let later_ms = clickhouse_timestamp_to_millis(later_ts).unwrap();
    let newest = CohortStreamEvent {
        timestamp: later_ts.to_string(),
        ..event(alice, 1, 10)
    };
    let out = process_event(PARTITION_ID, &store, &filters, &newest).unwrap();
    assert_eq!(out.skipped, None);
    assert_eq!(out.transitions.len(), 1, "first match enters");
    assert_eq!(
        behavioral_deadline(&state_at(&store, lsk, alice).unwrap()),
        later_ms + 7 * 86_400 * 1000,
        "deadline seeded off the newest event",
    );

    // A late event (EARLIER ts, higher offset 11) is applied — not a replay — but must NOT pull the
    // deadline earlier: it tracks the newest matching event, not this one.
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
        later_ms + 7 * 86_400 * 1000,
        "a late lower-ts event must not regress the deadline below newest_ms + window",
    );
}

// ── 10k synthetic events + replay idempotence ────────────────────────────────────

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

    // First pass: every person's first event enters both leaves (behavioral match + person match);
    // every later event is a no-op flip-wise. So exactly one of each per person.
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

    // Every person has both leaf-state rows and a person index listing both LSKs.
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

    // Replay the exact same 10k (same source offsets): zero new transitions, byte-identical state.
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

/// All stored Stage 1 bytes keyed by `(person, leaf_state_key)` — the unit of the replay
/// byte-identity check.
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

// ── Out-of-order person events: argMax keeps the latest by event time ─────────────

#[test]
fn out_of_order_person_events_keep_the_latest_by_event_time() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![person_leaf()]))]);
    let bob = person(1);
    let lsk = LeafStateKey::for_person_property(&PERSON_HASH);

    // Newest-by-event-time arrives first and matches.
    let newest_ts = "2026-05-26 12:00:00.000000";
    let newest = person_event(bob, "u@p.com", newest_ts, 1, 100);
    let out = process_event(PARTITION_ID, &store, &filters, &newest).unwrap();
    assert_eq!(out.transitions.len(), 1, "first write enters");

    // An older event (earlier ts) arrives later (higher offset) with a non-matching value — it is
    // stale by the argMax tiebreaker, so it neither flips membership nor overwrites the value.
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

// ── §2.4 audit: worker-observable emission + skip semantics ───────────────────────

#[test]
fn whole_event_skips_carry_distinct_reasons() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf(7), person_leaf()]),
    )]);

    // (label, mutation that triggers the skip, expected reason).
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

    // A team with no Stage 1 conditions (here, an empty catalog) skips with NoConditions.
    let empty = TeamFiltersBuilder::default().freeze();
    let out = process_event(PARTITION_ID, &store, &empty, &event(person(1), 1, 0)).unwrap();
    assert_eq!(out.skipped, Some(SkipReason::NoConditions));
}

#[test]
fn behavioral_records_and_emits_only_on_match() {
    let (_dir, store) = temp_store();
    let filters = build_team_filters(vec![(CohortId(1), cohort(vec![behavioral_leaf(7)]))]);
    let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let alice = person(1);

    // Non-matching event name: no transition, no state row.
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

    // Matching event: one Entered + a state row.
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

    // A non-matching person event still writes a row, but does not emit (false → false).
    let miss = person_event(carol, "nope@x.com", "2026-05-26 12:00:00.000000", 1, 10);
    let out = process_event(PARTITION_ID, &store, &filters, &miss).unwrap();
    assert!(out.transitions.is_empty(), "no false→false transition");
    match state_at(&store, lsk, carol).expect("row written even on non-match") {
        Stage1State::PersonProperty { matches, .. } => assert!(!matches),
        other => panic!("expected PersonProperty, got {other:?}"),
    }

    // A later matching event flips to a member → exactly one Entered.
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

    // Later non-match (newer event time + higher offset) flips true → false → Left.
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

    // Both a null and an empty-string payload are JS-falsy → the person path never runs, so the
    // event is a processed no-op (no row, no transition) — identical for both.
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
    // A team carrying BOTH a behavioral and a person leaf.
    let filters = build_team_filters(vec![(
        CohortId(1),
        cohort(vec![behavioral_leaf(7), person_leaf()]),
    )]);
    let behavioral_lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
    let person_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
    let alice = person(1);

    // Empty-string person_properties is JS-falsy: Node parses the behavioral globals'
    // person_properties as {} (not an error) and skips the person path entirely. Pre-fix this
    // skipped the WHOLE event with GlobalsParseError, dropping the behavioral match.
    let ev = CohortStreamEvent {
        person_properties: Some(String::new()),
        ..event(alice, 1, 0)
    };
    let out = process_event(PARTITION_ID, &store, &filters, &ev).unwrap();

    assert_eq!(
        out.skipped, None,
        "empty person_properties is not a whole-event skip"
    );
    // The behavioral leaf matched on `event == "$pageview"` and entered.
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
    // The person path stayed inactive (Node-parity guard) — no row, even though behavioral ran.
    assert!(
        state_at(&store, person_lsk, alice).is_none(),
        "empty person_properties → person path inactive, no row",
    );
}

#[test]
fn non_boolean_person_result_coerces_to_false() {
    let (_dir, store) = temp_store();
    // A person bytecode that yields a non-bool integer → coerced to `false` (Node parity).
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

// ── Spawned worker: drain loop + post-commit emission ─────────────────────────────

#[tokio::test]
async fn spawned_worker_drains_a_batch_and_commits_state() {
    let (_dir, store) = temp_store();
    // A multi-leaf cohort: state is written for both leaves, but neither leaf alone maps to the
    // (composite) cohort, so the shadow sink stays empty — the offset still advances.
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
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        store.clone(),
        catalog,
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    tx.send(vec![ShuffleMessage::Event {
        event: event(alice, 1, 0),
        cse_offset: 0,
    }])
    .await
    .unwrap();
    // Dropping the sender closes the channel; the worker drains the queued batch and exits.
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
    // Multi-leaf cohort → no per-cohort shadow output, but the offset advances all the same.
    assert!(sink.changes().is_empty());
    assert_eq!(
        tracker.committable_offsets().get(&(PARTITION_ID as i32)),
        Some(&1)
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
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        store.clone(),
        catalog,
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    // Team 999 is not in the catalog → the worker skips before touching the store, but the offset
    // still advances (a skipped event must not wedge the partition).
    let unknown = CohortStreamEvent {
        team_id: 999,
        ..event(alice, 1, 0)
    };
    tx.send(vec![ShuffleMessage::Event {
        event: unknown,
        cse_offset: 3,
    }])
    .await
    .unwrap();
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

// ── PR 1.8: produce-before-commit offset gating (single-leaf cohort, via CaptureSink) ───
//
// Note on store errors: a `process_event` `Err(StoreError)` is, at the worker level, identical to
// an empty sub-batch — `handle_event` returns no changes and the offset advances via `max_offset`
// (a corrupt-event skip that replay won't fix, matching PR 1.7). That path is exercised by
// `worker_advances_offset_on_empty_transition_subbatch`; inducing a real RocksDB backend error
// deterministically is not worth a dedicated test.

/// A single-leaf behavioral cohort (`CohortId(1)`) → a matching `$pageview` produces exactly one
/// `entered` change for that cohort, so the produce path is exercised end to end.
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
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        store.clone(),
        single_leaf_catalog(),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    tx.send(vec![ShuffleMessage::Event {
        event: event(person(1), 1, 0),
        cse_offset: 5,
    }])
    .await
    .unwrap();
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
    // The critical case: a non-matching event produces no transitions/changes, yet the offset MUST
    // still advance so a no-op (or poison) event can't wedge the partition.
    let (_dir, store) = temp_store();
    let sink = CaptureSink::new();
    let tracker = Arc::new(OffsetTracker::new());

    let (tx, rx) = mpsc::channel(16);
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        store.clone(),
        single_leaf_catalog(),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    // A non-$pageview event: the behavioral leaf does not match → no transition → empty buffer.
    let non_match = CohortStreamEvent {
        event: "$autocapture".to_string(),
        ..event(person(1), 1, 0)
    };
    tx.send(vec![ShuffleMessage::Event {
        event: non_match,
        cse_offset: 42,
    }])
    .await
    .unwrap();
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
    // A produce error must hold the sub-batch's offset back so Kafka replays it.
    let (_dir, store) = temp_store();
    let sink = CaptureSink::failing_first(1);
    let tracker = Arc::new(OffsetTracker::new());

    let (tx, rx) = mpsc::channel(16);
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        store.clone(),
        single_leaf_catalog(),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    // One matching event → one change → produce FAILS → offset held, nothing recorded.
    tx.send(vec![ShuffleMessage::Event {
        event: event(person(1), 1, 0),
        cse_offset: 10,
    }])
    .await
    .unwrap();
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
    // After a failed flush the worker must NOT wedge: the next sub-batch still produces and marks.
    let (_dir, store) = temp_store();
    let sink = CaptureSink::failing_first(1);
    let tracker = Arc::new(OffsetTracker::new());

    let (tx, rx) = mpsc::channel(16);
    let worker = Stage1Worker::spawn(
        PARTITION_ID,
        rx,
        store.clone(),
        single_leaf_catalog(),
        Arc::new(sink.clone()),
        tracker.clone(),
    );

    // First sub-batch fails its produce; the second succeeds.
    tx.send(vec![ShuffleMessage::Event {
        event: event(person(1), 1, 0),
        cse_offset: 10,
    }])
    .await
    .unwrap();
    tx.send(vec![ShuffleMessage::Event {
        event: event(person(2), 1, 1),
        cse_offset: 11,
    }])
    .await
    .unwrap();
    drop(tx);
    worker.join().await.unwrap();

    // The second sub-batch produced and advanced the offset past it; the held first event relies on
    // Kafka replay (the monotonic tracker reflects the later success).
    assert_eq!(
        tracker.committable_offsets().get(&(PARTITION_ID as i32)),
        Some(&12)
    );
    let changes = sink.changes();
    assert_eq!(changes.len(), 1, "only the second flush's change landed");
    assert_eq!(changes[0].person_id, person(2).to_string());
}
