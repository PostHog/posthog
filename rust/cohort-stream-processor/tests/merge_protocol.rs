//! Cross-partition merge protocol driven end-to-end through the public handler API against a real
//! RocksDB (no Kafka). Seeds state via `process_event`, then drives drain + transfer + apply
//! handlers directly, comparing merged state to the same-partition fast path and to an "all events
//! keyed to P_new from the start" oracle. Replays every handler twice for idempotence and exercises
//! the reopen-without-wipe recovery via `scan_pending_transfers`.

// Tests seed and assert through `CohortStore` directly — the sanctioned direct-store test surface.
#![allow(clippy::disallowed_methods)]

use chrono_tz::UTC;
use cohort_stream_processor::consumers::CohortStreamEvent;
use cohort_stream_processor::filters::{
    CatalogHandle, CohortId, FilterCatalog, TeamFilters, TeamFiltersBuilder, TeamId,
};
use cohort_stream_processor::merge::apply_handler::{
    handle_transfer, ApplyOutcome, MAX_TRANSFER_FORWARD_HOPS,
};
use cohort_stream_processor::merge::drain_handler::{handle_merge_event, DrainOutcome};
use cohort_stream_processor::merge::tombstone_redirect::{resolve, Resolution};
use cohort_stream_processor::merge::transfer::{
    MergeStateTransfer, PendingTransfer, PersonMergeEvent, Tombstone, MERGE_EVENT_SCHEMA_VERSION,
};
use cohort_stream_processor::partitions::{partition_of, COHORT_PARTITION_COUNT};
use cohort_stream_processor::producer::{now_last_updated, MembershipStatus};
use cohort_stream_processor::stage1::{Stage1State, StateVariant, StatefulRecord};
use cohort_stream_processor::stage2::Stage2State;
use cohort_stream_processor::store::{
    CohortStore, LeafStateKey, MergeAppliedKey, MergeDrainKey, OffloadConfig, OffloadMode,
    PendingTransferKey, Stage1Key, Stage2Key, StoreConfig, StoreHandle, TombstoneKey,
};
use cohort_stream_processor::workers::{
    compose_stage2, handle_merge_gc, handle_stage2_orphan_gc, process_event, MergeGcCursor,
    Stage2GcCursor,
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

/// `All` mode so `compose_stage2` exercises the blocking-pool transport; handlers still take the raw store.
fn handle(store: &CohortStore) -> StoreHandle {
    StoreHandle::new(
        store.clone(),
        OffloadConfig {
            mode: OffloadMode::All,
            event_read_permits: 16,
            maintenance_permits: 6,
        },
    )
}

fn behavioral_bytecode() -> Value {
    json!(["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11])
}

fn single_leaf() -> Value {
    json!({
        "type": "behavioral", "value": "performed_event", "key": "$pageview",
        "time_value": 7, "time_interval": "day",
        "conditionHash": "0123456789abcdef", "bytecode": behavioral_bytecode(),
    })
}

/// `performed_event_multiple gte 2` daily leaf (7d) — shares the conditionHash with `single_leaf`.
fn daily_leaf() -> Value {
    json!({
        "type": "behavioral", "value": "performed_event_multiple", "key": "$pageview",
        "time_value": 7, "time_interval": "day", "operator": "gte", "operator_value": 2,
        "conditionHash": "0123456789abcdef", "bytecode": behavioral_bytecode(),
    })
}

/// `performed_event_multiple gte 2` compressed leaf (365d) — over-180-day window uses compressed storage.
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

/// Cohorts 1–3: one single-leaf each (single/daily/compressed); cohort 4: `AND(daily, person)` so
/// apply transitions can fan into Stage 2 composition.
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

fn person_on(target: u16) -> Uuid {
    (1u128..)
        .map(Uuid::from_u128)
        .find(|p| part(*p) == target)
        .unwrap()
}

fn person_not_on(avoid: u16) -> Uuid {
    (1u128..)
        .map(Uuid::from_u128)
        .find(|p| part(*p) != avoid)
        .unwrap()
}

/// Three persons on pairwise-distinct partitions so every hop of `A → B → C` is cross-partition.
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

/// All three behavioral leaves share `BEHAVIORAL_HASH` but differ by `StateVariant`.
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

    let p_old = Uuid::from_u128(0xA11CE);
    let p_old_part = part(p_old);
    let p_new = person_not_on(p_old_part);
    let p_new_part = part(p_new);
    assert_ne!(
        p_old_part, p_new_part,
        "test requires a cross-partition pair"
    );

    fold_pageview(&store, &filters, p_old_part, p_old, 10, 0);
    fold_pageview(&store, &filters, p_new_part, p_new, 20, 0);

    let drained = handle_merge_event(
        p_old_part,
        &store,
        &filters,
        &merge_event(p_old, p_new),
        (5, 100),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    let transfer = match drained {
        DrainOutcome::Drained { transfer, .. } => transfer,
        other => panic!("expected a cross-partition Drained, got {other:?}"),
    };

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

    let applied = handle_transfer(
        p_new_part,
        &store,
        &filters,
        &transfer,
        (5, 7),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    assert!(
        matches!(applied, ApplyOutcome::Applied { .. }),
        "the transfer applied"
    );

    // Merged state: daily/compressed sum to 2 (gte 2 → member).
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

    // Oracle: a person that received both events from the start, keyed to P_new's partition.
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

    let replay_drain = handle_merge_event(
        p_old_part,
        &store,
        &filters,
        &merge_event(p_old, p_new),
        (5, 100),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    assert_eq!(replay_drain, DrainOutcome::AlreadyDrained);
    let replay_apply = handle_transfer(
        p_new_part,
        &store,
        &filters,
        &transfer,
        (5, 7),
        COHORT_PARTITION_COUNT,
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

fn seed_and_drain(dir: &TempDir) -> (CohortStore, TeamFilters, u16, Uuid, MergeStateTransfer) {
    let store = temp_store_in(dir);
    let filters = build_filters();

    let p_old = Uuid::from_u128(0x0DD);
    let p_old_part = part(p_old);
    let p_new = person_not_on(p_old_part);
    let p_new_part = part(p_new);

    fold_pageview(&store, &filters, p_old_part, p_old, 10, 0);
    fold_pageview(&store, &filters, p_new_part, p_new, 20, 0);

    let transfer = match handle_merge_event(
        p_old_part,
        &store,
        &filters,
        &merge_event(p_old, p_new),
        (5, 100),
        COHORT_PARTITION_COUNT,
    )
    .unwrap()
    {
        DrainOutcome::Drained { transfer, .. } => transfer,
        other => panic!("expected Drained, got {other:?}"),
    };
    (store, filters, p_new_part, p_new, transfer)
}

/// Apply dedup keys on the source merge coordinates, not the transfer-topic coordinates.
#[test]
fn duplicate_transfer_copy_under_different_transfer_coords_is_already_applied() {
    let dir = TempDir::new().unwrap();
    let (store, filters, p_new_part, p_new, transfer) = seed_and_drain(&dir);

    let first = handle_transfer(
        p_new_part,
        &store,
        &filters,
        &transfer,
        (5, 7),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    assert!(matches!(first, ApplyOutcome::Applied { .. }));

    let duplicate = handle_transfer(
        p_new_part,
        &store,
        &filters,
        &transfer,
        (63, 9_999),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    assert_eq!(
        duplicate,
        ApplyOutcome::AlreadyApplied,
        "the same merge under different transfer coords dedups by source coords"
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
        "daily buckets not double-counted by the duplicate copy"
    );
    assert_eq!(
        compressed_sum(&compressed.unwrap()),
        2,
        "compressed history not double-counted by the duplicate copy"
    );
}

/// A re-drain with the same source coordinates but different payload (e.g. rebuilt state) is dropped.
/// The dedup keys on source coords, not payload content.
#[test]
fn redrained_transfer_with_rebuilt_state_is_dropped_by_source_coords_dedup() {
    let dir = TempDir::new().unwrap();
    let (store, filters, p_new_part, p_new, transfer) = seed_and_drain(&dir);

    let first = handle_transfer(
        p_new_part,
        &store,
        &filters,
        &transfer,
        (5, 7),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    assert!(matches!(first, ApplyOutcome::Applied { .. }));

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
        COHORT_PARTITION_COUNT,
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

    let p_old = Uuid::from_u128(0xFA57);
    let p_old_part = part(p_old);
    let p_new = person_on(p_old_part);

    fold_pageview(&store, &filters, p_old_part, p_old, 10, 0);
    fold_pageview(&store, &filters, p_old_part, p_new, 20, 0);

    let outcome = handle_merge_event(
        p_old_part,
        &store,
        &filters,
        &merge_event(p_old, p_new),
        (5, 100),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    let DrainOutcome::FastPath { effects, .. } = &outcome else {
        panic!("same partition → fast path, got {outcome:?}");
    };
    // The fast path returns queue effects for the caller to apply rather than applying them inline.
    assert!(
        !effects.schedules.is_empty(),
        "the merged behavioral leaves schedule P_new's eviction deadlines",
    );
    assert!(
        effects
            .schedules
            .iter()
            .all(|(key, _)| key.person_id == p_new),
        "every scheduled key belongs to the survivor P_new",
    );
    assert!(
        effects.cancels.iter().all(|key| key.person_id == p_old),
        "the cancelled keys are P_old's drained keys",
    );

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

    // Simulate a crash between drain and produce: drain, then drop the store.
    {
        let store = temp_store_in(&dir);
        fold_pageview(&store, &filters, p_old_part, p_old, 10, 0);
        fold_pageview(&store, &filters, p_new_part, p_new, 20, 0);
        let drained = handle_merge_event(
            p_old_part,
            &store,
            &filters,
            &merge_event(p_old, p_new),
            (5, 100),
            COHORT_PARTITION_COUNT,
        )
        .unwrap();
        assert!(matches!(drained, DrainOutcome::Drained { .. }));
        store.flush().unwrap();
    }

    let store = temp_store_in(&dir);
    let recovered = store
        .scan_pending_transfers(p_old_part, None, usize::MAX)
        .unwrap();
    assert_eq!(
        recovered.len(),
        1,
        "the orphaned drain is recovered on reopen"
    );
    let pending = PendingTransfer::decode(&recovered[0].1).unwrap();
    assert_eq!(pending.transfer.old_person_uuid, p_old);

    let applied = handle_transfer(
        p_new_part,
        &store,
        &filters,
        &pending.transfer,
        (5, 7),
        COHORT_PARTITION_COUNT,
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
        store
            .scan_pending_transfers(p_old_part, None, usize::MAX)
            .unwrap()
            .is_empty(),
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

#[tokio::test]
async fn apply_transitions_compose_into_stage2() {
    let dir = TempDir::new().unwrap();
    let store = temp_store_in(&dir);
    let filters = build_filters();

    let p_old = Uuid::from_u128(0xBEE5);
    let p_old_part = part(p_old);
    let p_new = person_not_on(p_old_part);
    let p_new_part = part(p_new);

    // After merge: daily sum = 2 (a flip on gte 2), person leaf already true → AND(daily, person) enters.
    fold_pageview(&store, &filters, p_old_part, p_old, 10, 0);
    fold_pageview(&store, &filters, p_new_part, p_new, 20, 0);

    let transfer = match handle_merge_event(
        p_old_part,
        &store,
        &filters,
        &merge_event(p_old, p_new),
        (5, 100),
        COHORT_PARTITION_COUNT,
    )
    .unwrap()
    {
        DrainOutcome::Drained { transfer, .. } => transfer,
        other => panic!("expected Drained, got {other:?}"),
    };
    let transitions = match handle_transfer(
        p_new_part,
        &store,
        &filters,
        &transfer,
        (5, 7),
        COHORT_PARTITION_COUNT,
    )
    .unwrap()
    {
        ApplyOutcome::Applied { transitions, .. } => transitions,
        other => panic!("expected Applied, got {other:?}"),
    };

    let changes = compose_stage2(
        p_new_part,
        &handle(&store),
        &filters,
        &transitions,
        MERGED_AT,
        &now_last_updated(),
    )
    .await
    .unwrap();
    let composable_enter = changes
        .iter()
        .find(|c| c.cohort_id == 4 && c.person_id == p_new.to_string());
    assert!(
        composable_enter.is_some_and(|c| c.status == MembershipStatus::Entered),
        "the merged daily flip composes AND(daily, person) → Entered for P_new",
    );
}

/// An empty re-drain (P_old already drained, different source coords) must not overwrite a still-pending
/// transfer that has not yet been applied.
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

    // Different source coords → drain marker misses → re-drain (empty, P_old already gone).
    let redrain = handle_merge_event(
        p_old_part,
        &store,
        &filters,
        &merge_event(p_old, p_new),
        (5, 101),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    let DrainOutcome::Drained {
        transfer: redrained,
        ..
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

/// GC is a no-op while `cutoff < merged_at`; once the cutoff passes, it reclaims the drain marker,
/// apply marker, and tombstone. A replay after reclaim re-runs (dedup window closed), confirmed by
/// getting `Drained` with an empty transfer rather than `AlreadyDrained`.
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

    let transfer = match handle_merge_event(
        p_old_part,
        &store,
        &filters,
        &merge_event(p_old, p_new),
        (5, 100),
        COHORT_PARTITION_COUNT,
    )
    .unwrap()
    {
        DrainOutcome::Drained { transfer, .. } => transfer,
        other => panic!("expected Drained, got {other:?}"),
    };
    assert!(matches!(
        handle_transfer(
            p_new_part,
            &store,
            &filters,
            &transfer,
            (5, 7),
            COHORT_PARTITION_COUNT,
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

    // (a) In-retention: cutoffs before merged_at → GC is a no-op.
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

    // In-retention markers still dedup: same-coords re-drain short-circuits, same-source-coords
    // transfer at fresh transfer coords is AlreadyApplied.
    assert_eq!(
        handle_merge_event(
            p_old_part,
            &store,
            &filters,
            &merge_event(p_old, p_new),
            (5, 100),
            COHORT_PARTITION_COUNT,
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
            COHORT_PARTITION_COUNT,
        )
        .unwrap(),
        ApplyOutcome::AlreadyApplied,
        "the in-retention apply marker still dedupes the replayed transfer",
    );

    // (b) Out-of-retention: cutoffs after merged_at → GC reclaims all three.
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

    let reclaimed_redrain = handle_merge_event(
        p_old_part,
        &store,
        &filters,
        &merge_event(p_old, p_new),
        (5, 100),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    assert!(
        matches!(&reclaimed_redrain, DrainOutcome::Drained { transfer, .. } if transfer.leaves.is_empty()),
        "after GC the marker no longer dedupes; the replay re-drains (empty), got {reclaimed_redrain:?}",
    );
}

/// An absent-team drain leaves `cf_stage2` rows behind (no composable_cohort_ids to delete). A later
/// orphan-GC tick against a non-empty catalog reclaims the orphan while a co-resident live cohort
/// row on the same partition survives.
#[test]
fn stage2_orphans_from_an_absent_team_drain_are_reclaimed_by_a_later_gc_tick() {
    // TEAM (7) is absent from the GC catalog; LIVE_TEAM stays composable.
    const LIVE_TEAM: i32 = 8;

    let dir = TempDir::new().unwrap();
    let store = temp_store_in(&dir);

    let p_old = Uuid::from_u128(0xABED);
    let p_old_part = part(p_old);
    let p_new = person_not_on(p_old_part);

    let orphan = Stage2Key {
        partition_id: p_old_part,
        team_id: TEAM as u64,
        cohort_id: 4,
        person_id: p_old,
    };
    let row = Stage2State {
        in_cohort: true,
        last_evaluated_at_ms: MERGED_AT,
    }
    .encode();
    store.write_batch(|b| b.put_stage2(&orphan, &row)).unwrap();

    // Empty filters = absent-team fallback; drain deletes no cf_stage2 rows, so the row orphans.
    let absent_team_filters = TeamFiltersBuilder::default().freeze(UTC);
    handle_merge_event(
        p_old_part,
        &store,
        &absent_team_filters,
        &merge_event(p_old, p_new),
        (5, 100),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    assert!(
        store.get_stage2(&orphan).unwrap().is_some(),
        "the absent-team drain leaves P_old's cf_stage2 row behind (the orphan)",
    );

    let live = Stage2Key {
        partition_id: p_old_part,
        team_id: LIVE_TEAM as u64,
        cohort_id: 4,
        person_id: p_old,
    };
    store.write_batch(|b| b.put_stage2(&live, &row)).unwrap();

    // Catalog has LIVE_TEAM (composable cohort 4) but not TEAM — so TEAM's row is an orphan.
    let mut builder = TeamFiltersBuilder::default();
    builder
        .add_cohort(
            CohortId(4),
            TeamId(LIVE_TEAM),
            &cohort(vec![daily_leaf(), person_leaf()]),
        )
        .unwrap();
    let catalog = CatalogHandle::from_catalog(FilterCatalog::from_teams([(
        TeamId(LIVE_TEAM),
        builder.freeze(UTC),
    )]));

    let mut cursor = Stage2GcCursor::default();
    handle_stage2_orphan_gc(p_old_part, &store, &catalog, &mut cursor, 10_000);

    assert!(
        store.get_stage2(&orphan).unwrap().is_none(),
        "the absent-team orphan is reclaimed by the GC tick",
    );
    assert!(
        store.get_stage2(&live).unwrap().is_some(),
        "the co-resident live cohort's row survives",
    );
}

fn drain_cross(
    store: &CohortStore,
    filters: &TeamFilters,
    old: Uuid,
    new: Uuid,
    coords: (i32, i64),
) -> MergeStateTransfer {
    match handle_merge_event(
        part(old),
        store,
        filters,
        &merge_event(old, new),
        coords,
        COHORT_PARTITION_COUNT,
    )
    .unwrap()
    {
        DrainOutcome::Drained { transfer, .. } => transfer,
        other => panic!("expected a cross-partition Drained for {old}->{new}, got {other:?}"),
    }
}

/// `B → C` drains before `A → B` transfer applies: when the transfer lands on B's slice, B is already
/// tombstoned to C, so apply forwards A's state to C (hops=1) instead of stranding it at B.
/// Applying the forwarded transfer at C leaves C with A + B + C contributions.
#[test]
fn raced_chain_forwards_the_grandparent_transfer_through_the_tombstoned_intermediate_to_the_survivor(
) {
    let dir = TempDir::new().unwrap();
    let store = temp_store_in(&dir);
    let filters = build_filters();
    let (a, b, c) = chain_persons();
    let (a_part, b_part, c_part) = (part(a), part(b), part(c));

    fold_pageview(&store, &filters, a_part, a, 10, 0);
    fold_pageview(&store, &filters, b_part, b, 20, 0);
    fold_pageview(&store, &filters, c_part, c, 30, 0);

    // 1) B → C drains and applies at C → C = B + C (daily 2); B tombstoned to C.
    let b_to_c = drain_cross(&store, &filters, b, c, (5, 200));
    assert!(matches!(
        handle_transfer(
            c_part,
            &store,
            &filters,
            &b_to_c,
            (5, 71),
            COHORT_PARTITION_COUNT
        )
        .unwrap(),
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

    // 2) A → B drains; transfer keyed to B.
    let a_to_b = drain_cross(&store, &filters, a, b, (5, 100));

    // 3) Apply on B's partition: B tombstoned to C (cross-partition) → Forward(C, hops=1).
    let forwarded = match handle_transfer(
        b_part,
        &store,
        &filters,
        &a_to_b,
        (5, 80),
        COHORT_PARTITION_COUNT,
    )
    .unwrap()
    {
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

    let (b_single, b_daily, b_compressed) = behavioral_states(&store, &filters, b_part, b);
    assert!(
        b_single.is_none() && b_daily.is_none() && b_compressed.is_none(),
        "B stays drained — no resurrected orphan state",
    );

    // 4) Apply forwarded transfer at C → C = A + B + C.
    let applied = handle_transfer(
        c_part,
        &store,
        &filters,
        &forwarded,
        (5, 81),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
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

    // Apply marker written under C keyed to A → B's source coords so a redelivery dedups.
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

/// `A → B` applies before `B → C` drains: the marker lives under B, so a redelivery of `A → B`
/// hits B's marker directly — no forward, no double-count at C.
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

    // 1) A → B drains and applies at B (not yet tombstoned) → marker under B.
    let a_to_b = drain_cross(&store, &filters, a, b, (5, 100));
    assert!(matches!(
        handle_transfer(
            b_part,
            &store,
            &filters,
            &a_to_b,
            (5, 80),
            COHORT_PARTITION_COUNT
        )
        .unwrap(),
        ApplyOutcome::Applied { .. }
    ));

    // 2) B → C drains (B carries A + B) and applies at C → C = A + B + C.
    let b_to_c = drain_cross(&store, &filters, b, c, (5, 200));
    assert!(matches!(
        handle_transfer(
            c_part,
            &store,
            &filters,
            &b_to_c,
            (5, 71),
            COHORT_PARTITION_COUNT
        )
        .unwrap(),
        ApplyOutcome::Applied { .. }
    ));
    let (_, c_daily, _) = behavioral_states(&store, &filters, c_part, c);
    assert_eq!(
        daily_sum(&c_daily.unwrap()),
        3,
        "ordered chain reaches C correctly"
    );

    // 3) Redeliver A → B at B → the pre-tombstone marker absorbs it: AlreadyApplied, no forward.
    let redelivered = handle_transfer(
        b_part,
        &store,
        &filters,
        &a_to_b,
        (61, 999),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
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

/// Redelivery of `A → B` after a raced forward re-resolves B → C; C's marker (written by the first
/// forwarded apply) absorbs it: AlreadyApplied, no double-count.
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
    handle_transfer(
        c_part,
        &store,
        &filters,
        &b_to_c,
        (5, 71),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();

    let a_to_b = drain_cross(&store, &filters, a, b, (5, 100));
    let forwarded = match handle_transfer(
        b_part,
        &store,
        &filters,
        &a_to_b,
        (5, 80),
        COHORT_PARTITION_COUNT,
    )
    .unwrap()
    {
        ApplyOutcome::Forward { transfer } => *transfer,
        other => panic!("expected Forward, got {other:?}"),
    };
    handle_transfer(
        c_part,
        &store,
        &filters,
        &forwarded,
        (5, 81),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    let (_, c_daily, _) = behavioral_states(&store, &filters, c_part, c);
    assert_eq!(daily_sum(&c_daily.unwrap()), 3);

    // Redeliver original A → B at B → re-resolves to C → Forward; apply at C dedupes on C's marker.
    let reforwarded = match handle_transfer(
        b_part,
        &store,
        &filters,
        &a_to_b,
        (62, 1000),
        COHORT_PARTITION_COUNT,
    )
    .unwrap()
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
        COHORT_PARTITION_COUNT,
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

/// Returns `(partition, B, C, D)` where B/C/D colocate on a partition ≠ `avoid`, so `B → C → D`
/// resolves inline while `A` (on `avoid`) drains cross-partition into the chain.
fn colocated_chain_off(avoid: u16) -> (u16, Uuid, Uuid, Uuid) {
    let mut by_partition: std::collections::HashMap<u16, Vec<Uuid>> =
        std::collections::HashMap::new();
    for n in 1u128.. {
        let person = Uuid::from_u128(n);
        let p = part(person);
        if p == avoid {
            continue;
        }
        let bucket = by_partition.entry(p).or_default();
        bucket.push(person);
        if bucket.len() == 3 {
            return (p, bucket[0], bucket[1], bucket[2]);
        }
    }
    unreachable!("the uuid space fills three slots on some partition off the avoided one")
}

/// The raced-then-extended hazard: `A → B` applies after `B → C` drains (inline resolve to C), so
/// the apply writes markers under C (resolved target) AND B (original target, the dual-write). Then
/// `C → D` drains, leaving C's marker stranded. A redelivery of `A → B` re-resolves B → C → D;
/// the resolved-target probe under D misses, but the fixed-origin probe under B hits and dedups —
/// without the dual-write, A's leaves would be summed into D twice.
#[test]
fn raced_chain_then_extends_dedups_on_the_origin_marker() {
    let dir = TempDir::new().unwrap();
    let store = temp_store_in(&dir);
    let filters = build_filters();

    let a = Uuid::from_u128(0xA);
    let a_part = part(a);
    let (bcd_part, b, c, d) = colocated_chain_off(a_part);
    assert_ne!(a_part, bcd_part, "A drains cross-partition into the chain");

    fold_pageview(&store, &filters, a_part, a, 10, 0);
    fold_pageview(&store, &filters, bcd_part, b, 20, 0);
    fold_pageview(&store, &filters, bcd_part, c, 30, 0);
    fold_pageview(&store, &filters, bcd_part, d, 40, 0);

    // 1) B → C: same-partition fast path → B tombstoned to C, C = B + C (daily 2).
    //    Fast path writes no apply marker.
    assert!(matches!(
        handle_merge_event(
            bcd_part,
            &store,
            &filters,
            &merge_event(b, c),
            (5, 200),
            COHORT_PARTITION_COUNT,
        )
        .unwrap(),
        DrainOutcome::FastPath { .. }
    ));

    // 2) A → B drains cross-partition; B's tombstone is on the chain's slice (not A's), so the
    //    drain-side assist does not retarget → transfer keyed to B.
    let a_to_b = drain_cross(&store, &filters, a, b, (5, 100));
    assert_eq!(
        a_to_b.new_person_uuid, b,
        "transfer keyed to the raw target B"
    );

    // 3) Apply on chain's partition: B tombstoned to C (inline) → apply into C = A+B+C (daily 3).
    //    Dual-write: marker written under C (resolved target) and B (original target).
    assert!(matches!(
        handle_transfer(
            bcd_part,
            &store,
            &filters,
            &a_to_b,
            (5, 80),
            COHORT_PARTITION_COUNT,
        )
        .unwrap(),
        ApplyOutcome::Applied { .. }
    ));
    let (_, c_daily, _) = behavioral_states(&store, &filters, bcd_part, c);
    assert_eq!(daily_sum(&c_daily.unwrap()), 3, "C summed A + B + C");

    let c_marker = MergeAppliedKey {
        partition_id: bcd_part,
        team_id: TEAM as u64,
        new_person: c,
        source_partition: a_to_b.source_partition,
        source_offset: a_to_b.source_offset,
    };
    let b_marker = MergeAppliedKey {
        new_person: b,
        ..c_marker
    };
    assert!(
        store.get_merge_applied(&c_marker).unwrap().is_some(),
        "resolved-target marker under C",
    );
    assert!(
        store.get_merge_applied(&b_marker).unwrap().is_some(),
        "fixed-origin marker also under the original target B",
    );

    // 4) C → D: same-partition fast path → C tombstoned to D, D = A+B+C+D (daily 4).
    //    The fast path writes no apply marker, so C's marker is stranded (no redelivery resolves to C).
    assert!(matches!(
        handle_merge_event(
            bcd_part,
            &store,
            &filters,
            &merge_event(c, d),
            (5, 300),
            COHORT_PARTITION_COUNT,
        )
        .unwrap(),
        DrainOutcome::FastPath { .. }
    ));
    let (_, d_daily, _) = behavioral_states(&store, &filters, bcd_part, d);
    assert_eq!(
        daily_sum(&d_daily.unwrap()),
        4,
        "the chain folded A + B + C + D into D",
    );

    // 5) Redeliver A → B: re-resolves B → C → D; resolved-target probe under D misses (marker at C),
    //    but the original-target probe under B hits → AlreadyApplied.
    let redelivered = handle_transfer(
        bcd_part,
        &store,
        &filters,
        &a_to_b,
        (61, 999),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    assert_eq!(
        redelivered,
        ApplyOutcome::AlreadyApplied,
        "the fixed-origin marker under B absorbs the raced-then-extended redelivery",
    );

    let (d_single, d_daily_after, d_compressed_after) =
        behavioral_states(&store, &filters, bcd_part, d);
    assert!(matches!(
        d_single,
        Some(Stage1State::BehavioralSingle {
            has_match: true,
            ..
        })
    ));
    assert_eq!(
        daily_sum(&d_daily_after.unwrap()),
        4,
        "the redelivery did not double-count D's daily buckets",
    );
    assert_eq!(
        compressed_sum(&d_compressed_after.unwrap()),
        4,
        "the redelivery did not double-count D's compressed history",
    );
}

/// Drain-side assist: when B is already tombstoned to a same-partition C, the drain resolves inline
/// to C rather than staging a transfer keyed to B and forwarding later.
#[test]
fn drain_assist_folds_into_a_same_partition_tombstoned_target_directly() {
    let dir = TempDir::new().unwrap();
    let store = temp_store_in(&dir);
    let filters = build_filters();

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
    assert!(matches!(
        handle_merge_event(
            b_part,
            &store,
            &filters,
            &merge_event(b, c),
            (5, 200),
            COHORT_PARTITION_COUNT,
        )
        .unwrap(),
        DrainOutcome::FastPath { .. }
    ));

    // A → B: B's tombstone is on B/C's slice (not A's), so the drain does not retarget → transfer
    // keyed to B. On apply, B and C colocate → inline resolve to C.
    let a_to_b = drain_cross(&store, &filters, a, b, (5, 100));
    assert_eq!(
        a_to_b.new_person_uuid, b,
        "A and B differ in partition, so the assist did not retarget at A's drain (B's tombstone lives on B's slice, not A's)",
    );
    assert!(matches!(
        handle_transfer(
            b_part,
            &store,
            &filters,
            &a_to_b,
            (5, 81),
            COHORT_PARTITION_COUNT
        )
        .unwrap(),
        ApplyOutcome::Applied { .. }
    ));

    let (_, c_daily, _) = behavioral_states(&store, &filters, b_part, c);
    assert_eq!(daily_sum(&c_daily.unwrap()), 3, "A + B + C folded into C");
    let (b_single, b_daily, b_compressed) = behavioral_states(&store, &filters, b_part, b);
    assert!(b_single.is_none() && b_daily.is_none() && b_compressed.is_none());
}

/// A corrupt cross-partition tombstone cycle (B ↔ C): the apply forwards until `forward_hops` hits
/// `MAX_TRANSFER_FORWARD_HOPS`, then returns `HopCapped` so the caller can mark and move past it.
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

    write_tombstone(&store, b_part, b, c);
    write_tombstone(&store, part(c), c, b);

    let a_to_b = drain_cross(&store, &filters, a, b, (5, 100));

    let mut transfer = a_to_b;
    let mut hops = 0u8;
    loop {
        let on_part = part(transfer.new_person_uuid);
        match handle_transfer(
            on_part,
            &store,
            &filters,
            &transfer,
            (5, 80 + hops as i64),
            COHORT_PARTITION_COUNT,
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

/// Checkpoints `store` into a sibling of `dir` (RocksDB hard-links SSTs — checkpoint must be on the
/// same filesystem and not inside the source dir), then reopens it without wiping.
fn checkpoint_then_restore(dir: &TempDir, store: CohortStore) -> CohortStore {
    let checkpoint = dir.path().join("checkpoint");
    store.create_checkpoint(&checkpoint).unwrap();
    drop(store);
    CohortStore::open(&StoreConfig {
        path: checkpoint,
        wipe_on_start: false,
        ..StoreConfig::default()
    })
    .expect("open the restored checkpoint")
}

fn only_pending(store: &CohortStore, partition_id: u16) -> Vec<(PendingTransferKey, Vec<u8>)> {
    store
        .scan_pending_transfers(partition_id, None, usize::MAX)
        .unwrap()
}

#[test]
fn checkpoint_restore_then_redrive_and_already_drained_replay_apply_once() {
    let dir = TempDir::new().unwrap();
    let (store, filters, p_new_part, p_new, transfer) = seed_and_drain(&dir);
    let p_old = transfer.old_person_uuid;
    let p_old_part = part(p_old);
    let merge_coords = (transfer.source_partition, transfer.source_offset);
    assert_eq!(
        merge_coords,
        (5, 100),
        "the seed drains at the known coords"
    );

    // Checkpoint while the pending transfer is still staged; snapshot carries all four merge CFs.
    let restored = checkpoint_then_restore(&dir, store);

    let recovered = only_pending(&restored, p_old_part);
    assert_eq!(
        recovered.len(),
        1,
        "the still-staged pending transfer survived the checkpoint",
    );
    let pending = PendingTransfer::decode(&recovered[0].1).unwrap();
    assert_eq!(pending.transfer.old_person_uuid, p_old);
    assert_eq!(
        pending.transfer, transfer,
        "the staged transfer round-tripped intact"
    );
    let drain_key = MergeDrainKey {
        partition_id: p_old_part,
        team_id: TEAM as u64,
        old_person: p_old,
        merge_msg_partition: merge_coords.0,
        merge_msg_offset: merge_coords.1,
    };
    assert!(
        restored
            .get_merge_drain_applied(&drain_key)
            .unwrap()
            .is_some(),
        "the drain marker survived the checkpoint",
    );
    let tombstone_key = TombstoneKey {
        partition_id: p_old_part,
        team_id: TEAM as u64,
        person: p_old,
    };
    let tombstone_bytes = restored
        .get_tombstone(&tombstone_key)
        .unwrap()
        .expect("the tombstone survived the checkpoint");
    assert_eq!(
        Tombstone::decode(&tombstone_bytes).unwrap().new_person,
        p_new
    );

    let applied = handle_transfer(
        p_new_part,
        &restored,
        &filters,
        &pending.transfer,
        (5, 7),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    assert!(
        matches!(applied, ApplyOutcome::Applied { .. }),
        "the recovered transfer applies once against the restored DB",
    );
    let (single, daily, compressed) = behavioral_states(&restored, &filters, p_new_part, p_new);
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
        "P_old + P_new daily merged to 2"
    );
    assert_eq!(compressed_sum(&compressed.unwrap()), 2);

    let replay_drain = handle_merge_event(
        p_old_part,
        &restored,
        &filters,
        &merge_event(p_old, p_new),
        merge_coords,
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    assert_eq!(
        replay_drain,
        DrainOutcome::AlreadyDrained,
        "the restored drain marker short-circuits the replayed merge",
    );
    // Re-apply at different transfer offsets: apply dedup keys on source merge coords, not these.
    let replay_apply = handle_transfer(
        p_new_part,
        &restored,
        &filters,
        &pending.transfer,
        (63, 9_999),
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    assert_eq!(
        replay_apply,
        ApplyOutcome::AlreadyApplied,
        "the restored apply marker dedups the re-applied transfer by source coords",
    );

    let (single_after, daily_after, compressed_after) =
        behavioral_states(&restored, &filters, p_new_part, p_new);
    assert!(matches!(
        single_after,
        Some(Stage1State::BehavioralSingle {
            has_match: true,
            ..
        })
    ));
    assert_eq!(
        daily_sum(&daily_after.unwrap()),
        2,
        "the double application was absorbed — daily is not doubled",
    );
    assert_eq!(compressed_sum(&compressed_after.unwrap()), 2);
    let (s, d, c) = behavioral_states(&restored, &filters, p_old_part, p_old);
    assert!(
        s.is_none() && d.is_none() && c.is_none(),
        "P_old's drained state is still absent after the restore",
    );
    assert_eq!(
        Tombstone::decode(
            &restored
                .get_tombstone(&tombstone_key)
                .unwrap()
                .expect("tombstone still present")
        )
        .unwrap()
        .new_person,
        p_new,
        "the tombstone still redirects P_old → P_new",
    );
}

/// Event-level rewrite is driven through `tombstone_redirect::resolve` directly — the same resolver
/// that the worker, drain, and apply paths all call.
#[test]
fn checkpoint_restore_preserves_the_tombstone_and_redirects_a_straggler() {
    let dir = TempDir::new().unwrap();
    let store = temp_store_in(&dir);
    let filters = build_filters();

    let p_old = Uuid::from_u128(0x705B);
    let p_old_part = part(p_old);
    let p_new = person_not_on(p_old_part);
    assert_ne!(p_old_part, part(p_new), "cross-partition pair");

    fold_pageview(&store, &filters, p_old_part, p_old, 10, 0);
    drain_cross(&store, &filters, p_old, p_new, (5, 100));
    let (s, d, c) = behavioral_states(&store, &filters, p_old_part, p_old);
    assert!(
        s.is_none() && d.is_none() && c.is_none(),
        "P_old's slice is drained in tenure 1",
    );

    let restored = checkpoint_then_restore(&dir, store);

    let tombstone_key = TombstoneKey {
        partition_id: p_old_part,
        team_id: TEAM as u64,
        person: p_old,
    };
    let tombstone = Tombstone::decode(
        &restored
            .get_tombstone(&tombstone_key)
            .unwrap()
            .expect("the tombstone survived the checkpoint"),
    )
    .unwrap();
    assert_eq!(
        tombstone.new_person, p_new,
        "the restored tombstone targets P_new"
    );

    // CrossPartition: a P_old straggler is re-keyed to P_new's worker, never folded back into the drained P_old.
    let resolution = resolve(
        &restored,
        p_old_part,
        TeamId(TEAM),
        p_old,
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    assert_eq!(
        resolution,
        Resolution::CrossPartition {
            target_person: p_new,
            origin: p_old,
        },
        "post-restore, a P_old straggler redirects to P_new",
    );

    // Control on the same partition/team: NotMerged proves the tombstone content (not a key miss)
    // drives the redirect.
    let control = person_on(p_old_part);
    assert_ne!(control, p_old);
    assert_eq!(
        resolve(
            &restored,
            p_old_part,
            TeamId(TEAM),
            control,
            COHORT_PARTITION_COUNT
        )
        .unwrap(),
        Resolution::NotMerged,
        "a never-tombstoned person is not redirected — the P_new resolution is not vacuous",
    );

    let (s, d, c) = behavioral_states(&restored, &filters, p_old_part, p_old);
    assert!(
        s.is_none() && d.is_none() && c.is_none(),
        "the restored tombstone redirects, it does not resurrect P_old's state",
    );
}

#[test]
fn checkpoint_restore_preserves_the_drain_marker_so_a_replayed_merge_does_not_re_transfer() {
    let dir = TempDir::new().unwrap();
    let (store, filters, _p_new_part, p_new, transfer) = seed_and_drain(&dir);
    let p_old = transfer.old_person_uuid;
    let p_old_part = part(p_old);
    let merge_coords = (transfer.source_partition, transfer.source_offset);

    // Clear the pending transfer so the snapshot isolates the drain marker.
    store
        .clear_pending_transfer(&PendingTransferKey {
            partition_id: p_old_part,
            team_id: TEAM as u64,
            old_person: p_old,
        })
        .unwrap();
    assert!(
        only_pending(&store, p_old_part).is_empty(),
        "the outbox is empty before the checkpoint",
    );

    let restored = checkpoint_then_restore(&dir, store);
    assert!(
        only_pending(&restored, p_old_part).is_empty(),
        "the restored outbox starts empty",
    );

    let replay = handle_merge_event(
        p_old_part,
        &restored,
        &filters,
        &merge_event(p_old, p_new),
        merge_coords,
        COHORT_PARTITION_COUNT,
    )
    .unwrap();
    assert_eq!(
        replay,
        DrainOutcome::AlreadyDrained,
        "the restored drain marker short-circuits the redelivered merge",
    );

    // A lost marker would also leave the outbox empty (empty re-drain); AlreadyDrained above proves
    // the marker survived, not just that the outbox is empty.
    assert!(
        only_pending(&restored, p_old_part).is_empty(),
        "the replayed merge did not stage a duplicate pending transfer",
    );
}
