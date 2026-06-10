//! The cross-partition merge protocol (TDD §4.5.1) driven end-to-end through the public handler API
//! against a real RocksDB — **no Kafka**. Seeds P_old and P_new state by folding events through
//! [`process_event`](cohort_stream_processor::workers::process_event), then drives the drain +
//! transfer + apply handlers directly, comparing the merged state to the same-partition fast path and
//! to an "all events keyed to P_new from the start" oracle (Single + Daily + Compressed). Replays
//! every handler twice for idempotence, and exercises the reopen-without-wipe recovery via
//! `scan_pending_transfers` (crash criteria #5–#7 at the store level).

use chrono_tz::UTC;
use cohort_stream_processor::consumers::CohortStreamEvent;
use cohort_stream_processor::filters::{CohortId, TeamFilters, TeamFiltersBuilder, TeamId};
use cohort_stream_processor::merge::apply_handler::{handle_transfer, ApplyOutcome};
use cohort_stream_processor::merge::drain_handler::{handle_merge_event, DrainOutcome};
use cohort_stream_processor::merge::transfer::{
    PendingTransfer, PersonMergeEvent, MERGE_EVENT_SCHEMA_VERSION,
};
use cohort_stream_processor::partitions::{partition_of, COHORT_PARTITION_COUNT};
use cohort_stream_processor::producer::{now_last_updated, MembershipStatus};
use cohort_stream_processor::stage1::{Stage1State, StateVariant, StatefulRecord};
use cohort_stream_processor::store::{
    CohortStore, LeafStateKey, PendingTransferKey, Stage1Key, StoreConfig, TombstoneKey,
};
use cohort_stream_processor::sweep::EvictionQueue;
use cohort_stream_processor::workers::{compose_stage2, process_event};
use serde_json::{json, Value};
use tempfile::TempDir;
use uuid::Uuid;

const TEAM: i32 = 7;
const BEHAVIORAL_HASH: [u8; 16] = *b"0123456789abcdef";
const TS: &str = "2026-05-26 12:34:56.789000";
const MERGED_AT: i64 = 1_716_800_000_000;

fn temp_store_in(dir: &TempDir) -> CohortStore {
    CohortStore::open(&StoreConfig {
        path: dir.path().join("db"),
        ..StoreConfig::default()
    })
    .expect("open store")
}

fn behavioral_bytecode() -> Value {
    json!(["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11])
}

/// A `performed_event` single leaf (7d).
fn single_leaf() -> Value {
    json!({
        "type": "behavioral", "value": "performed_event", "key": "$pageview",
        "time_value": 7, "time_interval": "day",
        "conditionHash": "0123456789abcdef", "bytecode": behavioral_bytecode(),
    })
}

/// A `performed_event_multiple gte 2` daily leaf (7d) — shares the matcher with the single leaf.
fn daily_leaf() -> Value {
    json!({
        "type": "behavioral", "value": "performed_event_multiple", "key": "$pageview",
        "time_value": 7, "time_interval": "day", "operator": "gte", "operator_value": 2,
        "conditionHash": "0123456789abcdef", "bytecode": behavioral_bytecode(),
    })
}

/// A `performed_event_multiple gte 2` compressed leaf (365d) — over-180-day window.
fn compressed_leaf() -> Value {
    json!({
        "type": "behavioral", "value": "performed_event_multiple", "key": "$pageview",
        "time_value": 365, "time_interval": "day", "operator": "gte", "operator_value": 2,
        "conditionHash": "0123456789abcdef", "bytecode": behavioral_bytecode(),
    })
}

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

/// Single-leaf cohorts for each behavioral variant, plus a composable `AND(daily, person)` cohort so
/// the apply transitions fan into Stage 2.
fn build_filters() -> TeamFilters {
    let mut builder = TeamFiltersBuilder::default();
    builder
        .add_cohort(CohortId(1), TeamId(TEAM), &cohort(vec![single_leaf()]))
        .unwrap();
    builder
        .add_cohort(CohortId(2), TeamId(TEAM), &cohort(vec![daily_leaf()]))
        .unwrap();
    builder
        .add_cohort(CohortId(3), TeamId(TEAM), &cohort(vec![compressed_leaf()]))
        .unwrap();
    builder
        .add_cohort(
            CohortId(4),
            TeamId(TEAM),
            &cohort(vec![daily_leaf(), person_leaf()]),
        )
        .unwrap();
    builder.freeze(UTC)
}

fn pageview_event(person: Uuid, source_partition: i32, source_offset: i64) -> CohortStreamEvent {
    CohortStreamEvent {
        team_id: TEAM,
        person_id: person.to_string(),
        distinct_id: "d".to_string(),
        uuid: Uuid::from_u128(0xE0_0000 + source_offset as u128).to_string(),
        event: "$pageview".to_string(),
        timestamp: TS.to_string(),
        properties: Some("{}".to_string()),
        person_properties: Some(r#"{"email":"u@p.com"}"#.to_string()),
        elements_chain: None,
        source_offset,
        source_partition,
        redirected_from: None,
    }
}

fn merge_event(old: Uuid, new: Uuid) -> PersonMergeEvent {
    PersonMergeEvent {
        team_id: TEAM,
        old_person_uuid: old,
        new_person_uuid: new,
        merged_at_ms: MERGED_AT,
        schema_version: MERGE_EVENT_SCHEMA_VERSION,
    }
}

fn part(person: Uuid) -> u16 {
    partition_of(TeamId(TEAM), &person, COHORT_PARTITION_COUNT) as u16
}

/// A person whose merge partition equals `target`.
fn person_on(target: u16) -> Uuid {
    (1u128..)
        .map(Uuid::from_u128)
        .find(|p| part(*p) == target)
        .unwrap()
}

/// A person whose merge partition differs from `avoid`.
fn person_not_on(avoid: u16) -> Uuid {
    (1u128..)
        .map(Uuid::from_u128)
        .find(|p| part(*p) != avoid)
        .unwrap()
}

/// Resolve the `LeafStateKey` for a behavioral variant: all three leaves share `BEHAVIORAL_HASH` but
/// get distinct keys by window/value, so look them up by their resolved `StateVariant`.
fn lsk_of(filters: &TeamFilters, variant: StateVariant) -> LeafStateKey {
    filters.by_condition_to_lsk[&BEHAVIORAL_HASH]
        .iter()
        .copied()
        .find(|lsk| filters.by_lsk[lsk].variant == variant)
        .unwrap_or_else(|| panic!("no LSK for {variant:?}"))
}

fn leaf_state(
    store: &CohortStore,
    partition_id: u16,
    lsk: LeafStateKey,
    person: Uuid,
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

/// Fold a `$pageview` for `person` at `partition_id`, writing all three behavioral leaves' state.
fn fold_pageview(
    store: &CohortStore,
    filters: &TeamFilters,
    partition_id: u16,
    person: Uuid,
    source_partition: i32,
    source_offset: i64,
) {
    process_event(
        partition_id,
        store,
        filters,
        &pageview_event(person, source_partition, source_offset),
    )
    .unwrap();
}

/// The three behavioral leaf states for `person` at `partition_id`.
fn behavioral_states(
    store: &CohortStore,
    filters: &TeamFilters,
    partition_id: u16,
    person: Uuid,
) -> (
    Option<Stage1State>,
    Option<Stage1State>,
    Option<Stage1State>,
) {
    (
        leaf_state(
            store,
            partition_id,
            lsk_of(filters, StateVariant::BehavioralSingle),
            person,
        ),
        leaf_state(
            store,
            partition_id,
            lsk_of(filters, StateVariant::BehavioralDailyBuckets),
            person,
        ),
        leaf_state(
            store,
            partition_id,
            lsk_of(filters, StateVariant::BehavioralCompressedHistory),
            person,
        ),
    )
}

#[test]
fn cross_partition_drain_transfer_apply_merges_all_variants_and_matches_the_oracle() {
    let dir = TempDir::new().unwrap();
    let store = temp_store_in(&dir);
    let filters = build_filters();

    // P_old and P_new on different partitions (the ~98.4% case).
    let p_old = Uuid::from_u128(0xA11CE);
    let p_old_part = part(p_old);
    let p_new = person_not_on(p_old_part);
    let p_new_part = part(p_new);
    assert_ne!(
        p_old_part, p_new_part,
        "test requires a cross-partition pair"
    );

    // P_old: one $pageview (single=match, daily=1, compressed=1). P_new: one $pageview on a different
    // upstream partition so the oracle below folds both.
    fold_pageview(&store, &filters, p_old_part, p_old, 10, 0);
    fold_pageview(&store, &filters, p_new_part, p_new, 20, 0);

    // Drain P_old → cross-partition slow path.
    let mut old_queue = EvictionQueue::<Stage1Key>::new();
    let drained = handle_merge_event(
        p_old_part,
        &store,
        &filters,
        &merge_event(p_old, p_new),
        (5, 100),
        &mut old_queue,
    )
    .unwrap();
    let transfer = match drained {
        DrainOutcome::Drained { transfer } => transfer,
        other => panic!("expected a cross-partition Drained, got {other:?}"),
    };

    // P_old's state is gone and a tombstone points at P_new.
    let (s, d, c) = behavioral_states(&store, &filters, p_old_part, p_old);
    assert!(
        s.is_none() && d.is_none() && c.is_none(),
        "P_old's state was drained"
    );
    assert!(store
        .get_tombstone(&TombstoneKey {
            partition_id: p_old_part,
            team_id: TEAM as u64,
            person: p_old
        })
        .unwrap()
        .is_some());

    // Apply on P_new's worker.
    let mut new_queue = EvictionQueue::<Stage1Key>::new();
    let applied = handle_transfer(
        p_new_part,
        &store,
        &filters,
        &transfer,
        (5, 7),
        &mut new_queue,
    )
    .unwrap();
    assert!(
        matches!(applied, ApplyOutcome::Applied { .. }),
        "the transfer applied"
    );

    // The merged P_new state: single still a match; daily/compressed summed to 2 (gte 2 → member).
    let (single, daily, compressed) = behavioral_states(&store, &filters, p_new_part, p_new);
    assert!(matches!(
        single,
        Some(Stage1State::BehavioralSingle {
            has_match: true,
            ..
        })
    ));
    assert_eq!(
        daily_sum(&daily.clone().unwrap()),
        2,
        "daily summed across both persons"
    );
    assert_eq!(compressed_sum(&compressed.clone().unwrap()), 2);

    // Oracle: a fresh person that received BOTH events from the start, keyed to P_new's partition.
    let oracle = Uuid::from_u128(0xABCDE);
    fold_pageview(&store, &filters, p_new_part, oracle, 10, 0);
    fold_pageview(&store, &filters, p_new_part, oracle, 20, 0);
    let (o_single, o_daily, o_compressed) = behavioral_states(&store, &filters, p_new_part, oracle);
    assert_eq!(
        single, o_single,
        "single state matches the all-to-P_new oracle"
    );
    assert_eq!(daily, o_daily, "daily state matches the oracle");
    assert_eq!(
        compressed, o_compressed,
        "compressed state matches the oracle"
    );

    // Idempotence: replay the drain (AlreadyDrained — P_old already drained) and the transfer
    // (AlreadyApplied) — no double-count.
    let replay_drain = handle_merge_event(
        p_old_part,
        &store,
        &filters,
        &merge_event(p_old, p_new),
        (5, 100),
        &mut old_queue,
    )
    .unwrap();
    assert_eq!(replay_drain, DrainOutcome::AlreadyDrained);
    let replay_apply = handle_transfer(
        p_new_part,
        &store,
        &filters,
        &transfer,
        (5, 7),
        &mut new_queue,
    )
    .unwrap();
    assert_eq!(replay_apply, ApplyOutcome::AlreadyApplied);
    let (_, daily_after, compressed_after) = behavioral_states(&store, &filters, p_new_part, p_new);
    assert_eq!(
        daily_sum(&daily_after.unwrap()),
        2,
        "replay did not double-count daily"
    );
    assert_eq!(compressed_sum(&compressed_after.unwrap()), 2);
}

fn daily_sum(state: &Stage1State) -> u32 {
    match state {
        Stage1State::BehavioralDailyBuckets { buckets, .. } => buckets.iter().sum(),
        other => panic!("expected daily, got {other:?}"),
    }
}

fn compressed_sum(state: &Stage1State) -> u32 {
    match state {
        Stage1State::BehavioralCompressedHistory { entries, .. } => {
            entries.iter().map(|&(_, c)| c).sum()
        }
        other => panic!("expected compressed, got {other:?}"),
    }
}

#[test]
fn fast_path_equals_the_cross_partition_result() {
    let dir = TempDir::new().unwrap();
    let store = temp_store_in(&dir);
    let filters = build_filters();

    // Same-partition pair: P_old and P_new collide (the ~1.6% fast path).
    let p_old = Uuid::from_u128(0xFA57);
    let p_old_part = part(p_old);
    let p_new = person_on(p_old_part);

    fold_pageview(&store, &filters, p_old_part, p_old, 10, 0);
    fold_pageview(&store, &filters, p_old_part, p_new, 20, 0);

    let mut queue = EvictionQueue::<Stage1Key>::new();
    let outcome = handle_merge_event(
        p_old_part,
        &store,
        &filters,
        &merge_event(p_old, p_new),
        (5, 100),
        &mut queue,
    )
    .unwrap();
    assert!(
        matches!(outcome, DrainOutcome::FastPath { .. }),
        "same partition → fast path"
    );

    // P_old gone; P_new merged in one shot.
    let (s, d, c) = behavioral_states(&store, &filters, p_old_part, p_old);
    assert!(s.is_none() && d.is_none() && c.is_none());
    let (single, daily, compressed) = behavioral_states(&store, &filters, p_old_part, p_new);
    assert!(matches!(
        single,
        Some(Stage1State::BehavioralSingle {
            has_match: true,
            ..
        })
    ));
    assert_eq!(daily_sum(&daily.unwrap()), 2);
    assert_eq!(compressed_sum(&compressed.unwrap()), 2);
}

#[test]
fn reopen_between_drain_and_apply_recovers_via_scan_pending_transfers() {
    let dir = TempDir::new().unwrap();
    let filters = build_filters();

    let p_old = Uuid::from_u128(0xC0FFEE);
    let p_old_part = part(p_old);
    let p_new = person_not_on(p_old_part);
    let p_new_part = part(p_new);

    // Drain (slow path), then drop the store handle — simulating a crash after the drain WriteBatch
    // but before the transfer was produced.
    {
        let store = temp_store_in(&dir);
        fold_pageview(&store, &filters, p_old_part, p_old, 10, 0);
        fold_pageview(&store, &filters, p_new_part, p_new, 20, 0);
        let mut queue = EvictionQueue::<Stage1Key>::new();
        let drained = handle_merge_event(
            p_old_part,
            &store,
            &filters,
            &merge_event(p_old, p_new),
            (5, 100),
            &mut queue,
        )
        .unwrap();
        assert!(matches!(drained, DrainOutcome::Drained { .. }));
        store.flush().unwrap();
    }

    // Reopen without wiping: the pending transfer is recovered from the scan.
    let store = temp_store_in(&dir);
    let recovered = store.scan_pending_transfers(p_old_part).unwrap();
    assert_eq!(
        recovered.len(),
        1,
        "the orphaned drain is recovered on reopen"
    );
    let pending = PendingTransfer::decode(&recovered[0].1).unwrap();
    assert_eq!(pending.transfer.old_person_uuid, p_old);

    // Apply the recovered transfer, then clear the outbox (the C2 produce → clear → commit sequence).
    let mut new_queue = EvictionQueue::<Stage1Key>::new();
    let applied = handle_transfer(
        p_new_part,
        &store,
        &filters,
        &pending.transfer,
        (5, 7),
        &mut new_queue,
    )
    .unwrap();
    assert!(matches!(applied, ApplyOutcome::Applied { .. }));
    store
        .clear_pending_transfer(&PendingTransferKey {
            partition_id: p_old_part,
            team_id: TEAM as u64,
            old_person: p_old,
        })
        .unwrap();
    assert!(
        store.scan_pending_transfers(p_old_part).unwrap().is_empty(),
        "the outbox is cleared post-apply"
    );

    let (single, daily, compressed) = behavioral_states(&store, &filters, p_new_part, p_new);
    assert!(matches!(
        single,
        Some(Stage1State::BehavioralSingle {
            has_match: true,
            ..
        })
    ));
    assert_eq!(
        daily_sum(&daily.unwrap()),
        2,
        "the recovered transfer applied correctly"
    );
    assert_eq!(compressed_sum(&compressed.unwrap()), 2);
}

#[test]
fn apply_transitions_compose_into_stage2() {
    let dir = TempDir::new().unwrap();
    let store = temp_store_in(&dir);
    let filters = build_filters();

    let p_old = Uuid::from_u128(0xBEE5);
    let p_old_part = part(p_old);
    let p_new = person_not_on(p_old_part);
    let p_new_part = part(p_new);

    // Both have a matching $pageview (with the person-property email), so the daily leaf merges to
    // count 2 (a flip) and the person leaf is already true → the composable AND(daily, person) enters.
    fold_pageview(&store, &filters, p_old_part, p_old, 10, 0);
    fold_pageview(&store, &filters, p_new_part, p_new, 20, 0);

    let mut old_queue = EvictionQueue::<Stage1Key>::new();
    let transfer = match handle_merge_event(
        p_old_part,
        &store,
        &filters,
        &merge_event(p_old, p_new),
        (5, 100),
        &mut old_queue,
    )
    .unwrap()
    {
        DrainOutcome::Drained { transfer } => transfer,
        other => panic!("expected Drained, got {other:?}"),
    };
    let mut new_queue = EvictionQueue::<Stage1Key>::new();
    let transitions = match handle_transfer(
        p_new_part,
        &store,
        &filters,
        &transfer,
        (5, 7),
        &mut new_queue,
    )
    .unwrap()
    {
        ApplyOutcome::Applied { transitions } => transitions,
        other => panic!("expected Applied, got {other:?}"),
    };

    // Compose Stage 2 over the apply transitions: the daily flip recomposes AND(daily, person) → it
    // enters for P_new (cohort 4).
    let changes = compose_stage2(
        p_new_part,
        &store,
        &filters,
        &transitions,
        MERGED_AT,
        &now_last_updated(),
    )
    .unwrap();
    let composable_enter = changes
        .iter()
        .find(|c| c.cohort_id == 4 && c.person_id == p_new.to_string());
    assert!(
        composable_enter.is_some_and(|c| c.status == MembershipStatus::Entered),
        "the merged daily flip composes AND(daily, person) → Entered for P_new",
    );
}
