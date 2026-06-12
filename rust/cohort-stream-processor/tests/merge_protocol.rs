//! Cross-partition merge protocol driven end-to-end through the public handler API against a real
//! RocksDB (no Kafka). Seeds state via `process_event`, then drives drain + transfer + apply
//! handlers directly, comparing merged state to the same-partition fast path and to an "all events
//! keyed to P_new from the start" oracle. Replays every handler twice for idempotence and exercises
//! the reopen-without-wipe recovery via `scan_pending_transfers`.

use chrono_tz::UTC;
use cohort_stream_processor::consumers::CohortStreamEvent;
use cohort_stream_processor::filters::{CohortId, TeamFilters, TeamFiltersBuilder, TeamId};
use cohort_stream_processor::merge::apply_handler::{
    handle_transfer, ApplyOutcome, MAX_TRANSFER_FORWARD_HOPS,
};
use cohort_stream_processor::merge::drain_handler::{handle_merge_event, DrainOutcome};
use cohort_stream_processor::merge::transfer::{
    MergeStateTransfer, PendingTransfer, PersonMergeEvent, Tombstone, MERGE_EVENT_SCHEMA_VERSION,
};
use cohort_stream_processor::partitions::{partition_of, COHORT_PARTITION_COUNT};
use cohort_stream_processor::producer::{now_last_updated, MembershipStatus};
use cohort_stream_processor::stage1::{Stage1State, StateVariant, StatefulRecord};
use cohort_stream_processor::store::{
    CohortStore, LeafStateKey, MergeAppliedKey, MergeDrainKey, PendingTransferKey, Stage1Key,
    StoreConfig, TombstoneKey,
};
use cohort_stream_processor::sweep::EvictionQueue;
use cohort_stream_processor::workers::{
    compose_stage2, handle_merge_gc, process_event, MergeGcCursor,
};
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
        redirect_hops: 0,
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

/// Three persons `(A, B, C)` on three pairwise-distinct partitions, so every hop of a chain
/// `A → B → C` is cross-partition.
fn chain_persons() -> (Uuid, Uuid, Uuid) {
    let a = Uuid::from_u128(0xA);
    let a_part = part(a);
    let b = person_not_on(a_part);
    let b_part = part(b);
    let c = (1u128..)
        .map(Uuid::from_u128)
        .find(|p| part(*p) != a_part && part(*p) != b_part)
        .unwrap();
    (a, b, c)
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

/// Seed a cross-partition `(P_old, P_new)` pair (one `$pageview` each), drain P_old, and return the
/// staged transfer alongside everything an apply-dedup test needs.
fn seed_and_drain(dir: &TempDir) -> (CohortStore, TeamFilters, u16, Uuid, MergeStateTransfer) {
    let store = temp_store_in(dir);
    let filters = build_filters();

    let p_old = Uuid::from_u128(0x0DD);
    let p_old_part = part(p_old);
    let p_new = person_not_on(p_old_part);
    let p_new_part = part(p_new);

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
    (store, filters, p_new_part, p_new, transfer)
}

/// Each transfer copy lands at fresh transfer-topic coordinates, so the apply dedup must key by the
/// source merge message's coordinates.
#[test]
fn duplicate_transfer_copy_under_different_transfer_coords_is_already_applied() {
    let dir = TempDir::new().unwrap();
    let (store, filters, p_new_part, p_new, transfer) = seed_and_drain(&dir);

    let mut queue = EvictionQueue::<Stage1Key>::new();
    let first =
        handle_transfer(p_new_part, &store, &filters, &transfer, (5, 7), &mut queue).unwrap();
    assert!(matches!(first, ApplyOutcome::Applied { .. }));

    let duplicate = handle_transfer(
        p_new_part,
        &store,
        &filters,
        &transfer,
        (63, 9_999),
        &mut queue,
    )
    .unwrap();
    assert_eq!(
        duplicate,
        ApplyOutcome::AlreadyApplied,
        "the same merge under different transfer coords dedups by source coords"
    );

    // The merged state itself is unchanged — the duplicate never re-ran the bucket merge.
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
        "daily buckets not double-counted by the duplicate copy"
    );
    assert_eq!(
        compressed_sum(&compressed.unwrap()),
        2,
        "compressed history not double-counted by the duplicate copy"
    );
}

/// A re-drain after a drain-marker wipe can capture straggler-rebuilt P_old state in a second
/// transfer with the same source coordinates but different payload. The dedup drops it. This pins
/// the drop as intended behavior.
#[test]
fn redrained_transfer_with_rebuilt_state_is_dropped_by_source_coords_dedup() {
    let dir = TempDir::new().unwrap();
    let (store, filters, p_new_part, p_new, transfer) = seed_and_drain(&dir);

    let mut queue = EvictionQueue::<Stage1Key>::new();
    let first =
        handle_transfer(p_new_part, &store, &filters, &transfer, (5, 7), &mut queue).unwrap();
    assert!(matches!(first, ApplyOutcome::Applied { .. }));

    // The re-drain repackaged different state for the same merge (same source coordinates).
    let mut redrained = transfer.clone();
    for leaf in &mut redrained.leaves {
        if let Stage1State::BehavioralDailyBuckets { buckets, .. } = &mut leaf.record.state {
            for bucket in buckets.iter_mut() {
                *bucket += 5;
            }
        }
    }
    assert_ne!(
        redrained.leaves, transfer.leaves,
        "the re-drained payload differs"
    );

    let outcome = handle_transfer(
        p_new_part,
        &store,
        &filters,
        &redrained,
        (12, 345),
        &mut queue,
    )
    .unwrap();
    assert_eq!(outcome, ApplyOutcome::AlreadyApplied);

    let (_, daily, compressed) = behavioral_states(&store, &filters, p_new_part, p_new);
    assert_eq!(
        daily_sum(&daily.unwrap()),
        2,
        "the rebuilt P_old state is dropped, not folded"
    );
    assert_eq!(compressed_sum(&compressed.unwrap()), 2);
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

    // Drain, then drop the store handle (simulating a crash before the transfer was produced).
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

/// A duplicate merge event at new coordinates re-drains the already-empty P_old. The empty re-drain
/// must NOT overwrite a still-pending transfer with its empty payload.
#[test]
fn empty_redrain_does_not_overwrite_a_still_pending_transfer() {
    let dir = TempDir::new().unwrap();
    let (store, filters, _p_new_part, p_new, transfer) = seed_and_drain(&dir);
    let p_old = transfer.old_person_uuid;
    let p_old_part = part(p_old);
    let pending_key = PendingTransferKey {
        partition_id: p_old_part,
        team_id: TEAM as u64,
        old_person: p_old,
    };

    let staged = PendingTransfer::decode(
        &store
            .get_pending_transfer(&pending_key)
            .unwrap()
            .expect("the drain staged the transfer"),
    )
    .unwrap();
    assert!(!staged.transfer.leaves.is_empty());
    assert_eq!(
        (staged.merge_msg_partition, staged.merge_msg_offset),
        (5, 100),
    );

    // Duplicate merge at fresh coordinates → drain marker misses → re-drain.
    let mut queue = EvictionQueue::<Stage1Key>::new();
    let redrain = handle_merge_event(
        p_old_part,
        &store,
        &filters,
        &merge_event(p_old, p_new),
        (5, 101),
        &mut queue,
    )
    .unwrap();
    let DrainOutcome::Drained {
        transfer: redrained,
    } = redrain
    else {
        panic!("expected Drained, got {redrain:?}");
    };
    assert!(
        redrained.leaves.is_empty(),
        "P_old was already drained, so the re-drain packages nothing",
    );

    let after = PendingTransfer::decode(
        &store
            .get_pending_transfer(&pending_key)
            .unwrap()
            .expect("the pending transfer survives the empty re-drain"),
    )
    .unwrap();
    assert_eq!(
        after, staged,
        "an empty re-drain must not overwrite the pending transfer",
    );
}

/// End-to-end retention: a cross-partition drain + apply writes a drain marker + tombstone on P_old's
/// partition and an apply marker on P_new's. While still in retention (cutoff < merged_at) the GC is
/// a no-op and the markers keep deduping replays; once the cutoff advances past merged_at the GC
/// reclaims all three, and a replayed merge/transfer then re-runs (the dedup window has closed).
#[test]
fn merge_cf_gc_keeps_in_retention_markers_then_reclaims_out_of_retention_storage() {
    let dir = TempDir::new().unwrap();
    let store = temp_store_in(&dir);
    let filters = build_filters();

    let p_old = Uuid::from_u128(0x9C1D);
    let p_old_part = part(p_old);
    let p_new = person_not_on(p_old_part);
    let p_new_part = part(p_new);
    assert_ne!(
        p_old_part, p_new_part,
        "test requires a cross-partition pair"
    );

    fold_pageview(&store, &filters, p_old_part, p_old, 10, 0);
    fold_pageview(&store, &filters, p_new_part, p_new, 20, 0);

    // Drain (coords (5, 100)) + apply (transfer coords (5, 7)). All three CF entries carry MERGED_AT.
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
    assert!(matches!(
        handle_transfer(
            p_new_part,
            &store,
            &filters,
            &transfer,
            (5, 7),
            &mut new_queue
        )
        .unwrap(),
        ApplyOutcome::Applied { .. }
    ));

    let drain_key = MergeDrainKey {
        partition_id: p_old_part,
        team_id: TEAM as u64,
        old_person: p_old,
        merge_msg_partition: 5,
        merge_msg_offset: 100,
    };
    let applied_key = MergeAppliedKey {
        partition_id: p_new_part,
        team_id: TEAM as u64,
        new_person: p_new,
        source_partition: 5,
        source_offset: 100,
    };
    let tombstone_key = TombstoneKey {
        partition_id: p_old_part,
        team_id: TEAM as u64,
        person: p_old,
    };
    assert!(store.get_merge_drain_applied(&drain_key).unwrap().is_some());
    assert!(store.get_merge_applied(&applied_key).unwrap().is_some());
    assert!(store.get_tombstone(&tombstone_key).unwrap().is_some());

    // (a) In retention: cutoffs strictly before merged_at → GC deletes nothing on either partition.
    let mut old_cursor = MergeGcCursor::default();
    let mut new_cursor = MergeGcCursor::default();
    let in_retention = MERGED_AT - 1;
    handle_merge_gc(
        p_old_part,
        &store,
        &mut old_cursor,
        in_retention,
        in_retention,
        10_000,
    );
    handle_merge_gc(
        p_new_part,
        &store,
        &mut new_cursor,
        in_retention,
        in_retention,
        10_000,
    );

    assert!(
        store.get_merge_drain_applied(&drain_key).unwrap().is_some(),
        "in-retention drain marker survives",
    );
    assert!(
        store.get_merge_applied(&applied_key).unwrap().is_some(),
        "in-retention apply marker survives",
    );
    assert!(
        store.get_tombstone(&tombstone_key).unwrap().is_some(),
        "in-retention tombstone survives",
    );

    // The surviving markers still dedupe a replay: re-drain at the SAME coords short-circuits, and
    // the duplicate transfer (fresh transfer coords, same source coords) is AlreadyApplied.
    assert_eq!(
        handle_merge_event(
            p_old_part,
            &store,
            &filters,
            &merge_event(p_old, p_new),
            (5, 100),
            &mut old_queue,
        )
        .unwrap(),
        DrainOutcome::AlreadyDrained,
        "the in-retention drain marker still dedupes the replayed merge",
    );
    assert_eq!(
        handle_transfer(
            p_new_part,
            &store,
            &filters,
            &transfer,
            (63, 9_999),
            &mut new_queue
        )
        .unwrap(),
        ApplyOutcome::AlreadyApplied,
        "the in-retention apply marker still dedupes the replayed transfer",
    );

    // (b) Out of retention: cutoffs strictly after merged_at → GC reclaims all three.
    let out_of_retention = MERGED_AT + 1;
    handle_merge_gc(
        p_old_part,
        &store,
        &mut old_cursor,
        out_of_retention,
        out_of_retention,
        10_000,
    );
    handle_merge_gc(
        p_new_part,
        &store,
        &mut new_cursor,
        out_of_retention,
        out_of_retention,
        10_000,
    );

    assert!(
        store.get_merge_drain_applied(&drain_key).unwrap().is_none(),
        "out-of-retention drain marker reclaimed",
    );
    assert!(
        store.get_merge_applied(&applied_key).unwrap().is_none(),
        "out-of-retention apply marker reclaimed",
    );
    assert!(
        store.get_tombstone(&tombstone_key).unwrap().is_none(),
        "out-of-retention tombstone reclaimed",
    );

    // With the drain marker gone, a replay at the same coords no longer short-circuits — it re-drains
    // (P_old's state is already gone, so the re-drain packages nothing). This confirms the dedup
    // window closed only because the storage was reclaimed, not by accident.
    let reclaimed_redrain = handle_merge_event(
        p_old_part,
        &store,
        &filters,
        &merge_event(p_old, p_new),
        (5, 100),
        &mut old_queue,
    )
    .unwrap();
    assert!(
        matches!(&reclaimed_redrain, DrainOutcome::Drained { transfer } if transfer.leaves.is_empty()),
        "after GC the marker no longer dedupes; the replay re-drains (empty), got {reclaimed_redrain:?}",
    );
}

/// Drain `old → new` on `old`'s partition and return the staged cross-partition transfer.
fn drain_cross(
    store: &CohortStore,
    filters: &TeamFilters,
    old: Uuid,
    new: Uuid,
    coords: (i32, i64),
) -> MergeStateTransfer {
    let mut queue = EvictionQueue::<Stage1Key>::new();
    match handle_merge_event(
        part(old),
        store,
        filters,
        &merge_event(old, new),
        coords,
        &mut queue,
    )
    .unwrap()
    {
        DrainOutcome::Drained { transfer } => transfer,
        other => panic!("expected a cross-partition Drained for {old}->{new}, got {other:?}"),
    }
}

/// Chained merge `A → B → C` where the downstream `B → C` drain runs before the upstream `A → B`
/// transfer applies: the `A → B` transfer lands on B's partition where B is already tombstoned to C,
/// so the apply forwards A's state to C (hops=1) instead of stranding it on the drained B. Applying
/// the forwarded transfer at C leaves C with A + B + C contributions.
#[test]
fn raced_chain_forwards_the_grandparent_transfer_through_the_tombstoned_intermediate_to_the_survivor(
) {
    let dir = TempDir::new().unwrap();
    let store = temp_store_in(&dir);
    let filters = build_filters();
    let (a, b, c) = chain_persons();
    let (a_part, b_part, c_part) = (part(a), part(b), part(c));

    // A: 1 pageview; B: 1; C: 1 — each on its own partition.
    fold_pageview(&store, &filters, a_part, a, 10, 0);
    fold_pageview(&store, &filters, b_part, b, 20, 0);
    fold_pageview(&store, &filters, c_part, c, 30, 0);

    // 1) B → C drains first and applies at C → C now has B + C (daily sum 2). B is tombstoned to C.
    let b_to_c = drain_cross(&store, &filters, b, c, (5, 200));
    let mut c_queue = EvictionQueue::<Stage1Key>::new();
    assert!(matches!(
        handle_transfer(c_part, &store, &filters, &b_to_c, (5, 71), &mut c_queue).unwrap(),
        ApplyOutcome::Applied { .. }
    ));
    assert!(store
        .get_tombstone(&TombstoneKey {
            partition_id: b_part,
            team_id: TEAM as u64,
            person: b,
        })
        .unwrap()
        .is_some());

    // 2) A → B drains; its transfer is keyed by B and would apply on B's partition.
    let a_to_b = drain_cross(&store, &filters, a, b, (5, 100));

    // 3) Apply A → B on B's partition: B is tombstoned to C (cross-partition) → Forward to C, hops=1.
    let mut b_queue = EvictionQueue::<Stage1Key>::new();
    let forwarded =
        match handle_transfer(b_part, &store, &filters, &a_to_b, (5, 80), &mut b_queue).unwrap() {
            ApplyOutcome::Forward { transfer } => *transfer,
            other => panic!("expected Forward, got {other:?}"),
        };
    assert_eq!(
        forwarded.new_person_uuid, c,
        "forwarded transfer is re-keyed to C"
    );
    assert_eq!(forwarded.forward_hops, 1, "one forward hop taken");
    assert_eq!(
        forwarded.source_partition, a_to_b.source_partition,
        "the source coords (the apply-side dedup key) are preserved across the forward",
    );
    assert_eq!(forwarded.source_offset, a_to_b.source_offset);
    assert_eq!(
        forwarded.old_person_uuid, a,
        "old_person stays A (the ancestor)"
    );

    // B's slice gained no resurrected stage1 rows for the forwarded leaves — A did not strand at B.
    let (b_single, b_daily, b_compressed) = behavioral_states(&store, &filters, b_part, b);
    assert!(
        b_single.is_none() && b_daily.is_none() && b_compressed.is_none(),
        "B stays drained — no resurrected orphan state",
    );

    // 4) Apply the forwarded transfer at C → C = A + B + C.
    let applied =
        handle_transfer(c_part, &store, &filters, &forwarded, (5, 81), &mut c_queue).unwrap();
    assert!(matches!(applied, ApplyOutcome::Applied { .. }));

    let (single, daily, compressed) = behavioral_states(&store, &filters, c_part, c);
    assert!(matches!(
        single,
        Some(Stage1State::BehavioralSingle {
            has_match: true,
            ..
        })
    ));
    assert_eq!(
        daily_sum(&daily.unwrap()),
        3,
        "C's daily buckets summed A + B + C contributions",
    );
    assert_eq!(compressed_sum(&compressed.unwrap()), 3);

    // The marker is written under C with A → B's source coords (so a redelivered copy dedups).
    assert!(store
        .get_merge_applied(&MergeAppliedKey {
            partition_id: c_part,
            team_id: TEAM as u64,
            new_person: c,
            source_partition: a_to_b.source_partition,
            source_offset: a_to_b.source_offset,
        })
        .unwrap()
        .is_some());
}

/// The ordered case: `A → B` applies *before* `B → C` drains, so the marker is written under B and a
/// redelivery of the `A → B` transfer dedups on B's marker — no forward, no double-count at C.
#[test]
fn ordered_chain_redelivery_dedups_on_the_intermediate_marker_without_forwarding() {
    let dir = TempDir::new().unwrap();
    let store = temp_store_in(&dir);
    let filters = build_filters();
    let (a, b, c) = chain_persons();
    let (a_part, b_part, c_part) = (part(a), part(b), part(c));

    fold_pageview(&store, &filters, a_part, a, 10, 0);
    fold_pageview(&store, &filters, b_part, b, 20, 0);
    fold_pageview(&store, &filters, c_part, c, 30, 0);

    // 1) A → B applies at B first (B not yet tombstoned) → marker under B.
    let a_to_b = drain_cross(&store, &filters, a, b, (5, 100));
    let mut b_queue = EvictionQueue::<Stage1Key>::new();
    assert!(matches!(
        handle_transfer(b_part, &store, &filters, &a_to_b, (5, 80), &mut b_queue).unwrap(),
        ApplyOutcome::Applied { .. }
    ));

    // 2) B → C drains (B now carries A + B) and applies at C → C has A + B + C.
    let b_to_c = drain_cross(&store, &filters, b, c, (5, 200));
    let mut c_queue = EvictionQueue::<Stage1Key>::new();
    assert!(matches!(
        handle_transfer(c_part, &store, &filters, &b_to_c, (5, 71), &mut c_queue).unwrap(),
        ApplyOutcome::Applied { .. }
    ));
    let (_, c_daily, _) = behavioral_states(&store, &filters, c_part, c);
    assert_eq!(
        daily_sum(&c_daily.unwrap()),
        3,
        "ordered chain reaches C correctly"
    );

    // 3) Redeliver the A → B transfer at B → the B marker (written before the tombstone) absorbs it:
    // AlreadyApplied, no forward, no double-count at C.
    let redelivered =
        handle_transfer(b_part, &store, &filters, &a_to_b, (61, 999), &mut b_queue).unwrap();
    assert_eq!(
        redelivered,
        ApplyOutcome::AlreadyApplied,
        "the original-target marker absorbs the ordered-case redelivery",
    );
    let (_, c_daily_after, _) = behavioral_states(&store, &filters, c_part, c);
    assert_eq!(
        daily_sum(&c_daily_after.unwrap()),
        3,
        "redelivery did not double-count at C",
    );
}

/// After a raced forward, redelivering the original `A → B` transfer resolves to C again; C's marker
/// (written by the forwarded apply) is present → AlreadyApplied, exactly-once.
#[test]
fn forwarded_copy_redelivery_dedups_on_the_survivor_marker() {
    let dir = TempDir::new().unwrap();
    let store = temp_store_in(&dir);
    let filters = build_filters();
    let (a, b, c) = chain_persons();
    let (a_part, b_part, c_part) = (part(a), part(b), part(c));

    fold_pageview(&store, &filters, a_part, a, 10, 0);
    fold_pageview(&store, &filters, b_part, b, 20, 0);
    fold_pageview(&store, &filters, c_part, c, 30, 0);

    let b_to_c = drain_cross(&store, &filters, b, c, (5, 200));
    let mut c_queue = EvictionQueue::<Stage1Key>::new();
    handle_transfer(c_part, &store, &filters, &b_to_c, (5, 71), &mut c_queue).unwrap();

    let a_to_b = drain_cross(&store, &filters, a, b, (5, 100));
    let mut b_queue = EvictionQueue::<Stage1Key>::new();
    let forwarded =
        match handle_transfer(b_part, &store, &filters, &a_to_b, (5, 80), &mut b_queue).unwrap() {
            ApplyOutcome::Forward { transfer } => *transfer,
            other => panic!("expected Forward, got {other:?}"),
        };
    handle_transfer(c_part, &store, &filters, &forwarded, (5, 81), &mut c_queue).unwrap();
    let (_, c_daily, _) = behavioral_states(&store, &filters, c_part, c);
    assert_eq!(daily_sum(&c_daily.unwrap()), 3);

    // Redeliver the *original* A → B transfer at B → resolves to C again → Forward; applying the
    // re-forwarded copy at C dedups on the survivor marker (no double-count).
    let reforwarded =
        match handle_transfer(b_part, &store, &filters, &a_to_b, (62, 1000), &mut b_queue).unwrap()
        {
            ApplyOutcome::Forward { transfer } => *transfer,
            other => panic!("expected Forward on redelivery, got {other:?}"),
        };
    let outcome = handle_transfer(
        c_part,
        &store,
        &filters,
        &reforwarded,
        (62, 1001),
        &mut c_queue,
    )
    .unwrap();
    assert_eq!(
        outcome,
        ApplyOutcome::AlreadyApplied,
        "the survivor marker absorbs the re-forwarded copy",
    );
    let (_, c_daily_after, _) = behavioral_states(&store, &filters, c_part, c);
    assert_eq!(
        daily_sum(&c_daily_after.unwrap()),
        3,
        "the forwarded-copy redelivery did not double-count at C",
    );
}

/// Drain-side same-slice assist: a merge `A → B` where B is already tombstoned to a *same-partition*
/// C folds straight into C in one drain (the fast path with the assist), skipping a hop.
#[test]
fn drain_assist_folds_into_a_same_partition_tombstoned_target_directly() {
    let dir = TempDir::new().unwrap();
    let store = temp_store_in(&dir);
    let filters = build_filters();

    // A on one partition; B and C colocated on another so the A → B drain's effective target is C and
    // the assist routes A's state to C in the same slice as B.
    let a = Uuid::from_u128(0xA);
    let a_part = part(a);
    let b = person_not_on(a_part);
    let b_part = part(b);
    let c = (1u128..)
        .map(Uuid::from_u128)
        .find(|p| part(*p) == b_part && *p != b)
        .unwrap();

    fold_pageview(&store, &filters, a_part, a, 10, 0);
    fold_pageview(&store, &filters, b_part, b, 20, 0);
    fold_pageview(&store, &filters, b_part, c, 30, 0);

    // B → C is a same-partition fast-path merge → B tombstoned to C, C has B + C.
    let mut bc_queue = EvictionQueue::<Stage1Key>::new();
    assert!(matches!(
        handle_merge_event(
            b_part,
            &store,
            &filters,
            &merge_event(b, c),
            (5, 200),
            &mut bc_queue
        )
        .unwrap(),
        DrainOutcome::FastPath { .. }
    ));

    // A → B: the effective target resolves to C (cross-partition from A's view, but B and C colocate),
    // so the transfer is keyed to C and applies on C's (= B's) partition.
    let a_to_b = drain_cross(&store, &filters, a, b, (5, 100));
    assert_eq!(
        a_to_b.new_person_uuid, b,
        "A and B differ in partition, so the assist did not retarget at A's drain (B's tombstone lives on B's slice, not A's)",
    );
    let mut c_queue = EvictionQueue::<Stage1Key>::new();
    // B and C colocate → the apply-side resolution is Inline, folding into C directly.
    assert!(matches!(
        handle_transfer(b_part, &store, &filters, &a_to_b, (5, 81), &mut c_queue).unwrap(),
        ApplyOutcome::Applied { .. }
    ));

    // C carries A + B + C; B has no resurrected state.
    let (_, c_daily, _) = behavioral_states(&store, &filters, b_part, c);
    assert_eq!(daily_sum(&c_daily.unwrap()), 3, "A + B + C folded into C");
    let (b_single, b_daily, b_compressed) = behavioral_states(&store, &filters, b_part, b);
    assert!(b_single.is_none() && b_daily.is_none() && b_compressed.is_none());
}

/// A corrupt cross-partition tombstone cycle: the apply forwards until `forward_hops` hits the cap,
/// then drops without forwarding (the offset is marked by the caller so the partition does not wedge).
#[test]
fn transfer_forward_stops_at_the_hop_cap_on_a_corrupt_tombstone_cycle() {
    let dir = TempDir::new().unwrap();
    let store = temp_store_in(&dir);
    let filters = build_filters();

    let a = Uuid::from_u128(0xA);
    let a_part = part(a);
    let b = person_not_on(a_part);
    let b_part = part(b);
    let c = (1u128..)
        .map(Uuid::from_u128)
        .find(|p| part(*p) != a_part && part(*p) != b_part)
        .unwrap();

    fold_pageview(&store, &filters, a_part, a, 10, 0);

    // Write a corrupt cross-partition tombstone cycle B ↔ C on their own slices.
    write_tombstone(&store, b_part, b, c);
    write_tombstone(&store, part(c), c, b);

    let a_to_b = drain_cross(&store, &filters, a, b, (5, 100));

    // Walk the forward: B → C → B → ... until the hop cap. The cap-1'th apply at the cycle drops.
    let mut transfer = a_to_b;
    let mut queue = EvictionQueue::<Stage1Key>::new();
    let mut hops = 0u8;
    loop {
        let on_part = part(transfer.new_person_uuid);
        match handle_transfer(
            on_part,
            &store,
            &filters,
            &transfer,
            (5, 80 + hops as i64),
            &mut queue,
        )
        .unwrap()
        {
            ApplyOutcome::Forward { transfer: next } => {
                hops += 1;
                transfer = *next;
                assert_eq!(
                    transfer.forward_hops, hops,
                    "forward_hops increments per hop"
                );
                assert!(
                    hops <= MAX_TRANSFER_FORWARD_HOPS,
                    "must not exceed the cap before stopping"
                );
            }
            ApplyOutcome::HopCapped => break,
            other => panic!("expected Forward/HopCapped on a cycle, got {other:?}"),
        }
    }
    assert_eq!(
        hops, MAX_TRANSFER_FORWARD_HOPS,
        "the forward took exactly the cap before dropping",
    );
}

fn write_tombstone(store: &CohortStore, on_partition: u16, old: Uuid, new: Uuid) {
    let key = TombstoneKey {
        partition_id: on_partition,
        team_id: TEAM as u64,
        person: old,
    };
    let value = Tombstone {
        new_person: new,
        merged_at_ms: MERGED_AT,
    };
    store
        .write_batch(|b| b.put_tombstone(&key, &value.encode()))
        .unwrap();
}
