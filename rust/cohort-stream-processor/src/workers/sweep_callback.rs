//! The per-key time-driven eviction — the sweep's "brain", mirroring [`process_event`]'s shape.
//!
//! [`sweep_evict`] is a pure read-and-compute pass: for each due key it reads the stored state,
//! drops the aged-out bucket(s), recomputes the predicate, and returns what *would* change — the
//! `Left` transition, the state mutation (rewrite or delete), and the next eviction deadline — but
//! writes nothing. The worker ([`handle_sweep`](crate::workers::worker)) orchestrates the
//! produce-before-write ordering over the returned results, so a clean produce failure can replay
//! against still-un-evicted state.
//!
//! It depends only on `stage1` / `store` / `producer` / `filters` — no `consumers` coupling — so it
//! can be unit-tested against an in-process store and frozen `TeamFilters` with no Kafka.
//!
//! [`process_event`]: crate::workers::event_path::process_event

use chrono_tz::Tz;
use metrics::counter;

use crate::filters::reverse_index::{LeafStateMeta, TeamFilters};
use crate::filters::TeamId;
use crate::observability::metrics::{
    STAGE1_STATE_DECODE_ERROR, STAGE1_UNSUPPORTED_VARIANT_SKIPPED,
};
use crate::stage1::bucket_tz::{daily_bucket_len, day_idx_in_tz};
use crate::stage1::daily::{daily_eviction_deadline, slide_window_forward};
use crate::stage1::key::Stage1Key;
use crate::stage1::predicate::{daily_predicate, predicate};
use crate::stage1::state::{Stage1State, StateVariant, StatefulRecord};
use crate::stage1::transition::{LeafTransition, TransitionKind};
use crate::store::{CohortStore, StoreError};

/// The state mutation an eviction implies, applied by the worker in one `WriteBatch` only after the
/// `Left`s are durably produced. The key lives on the [`EvictionResult`], so this is just the verb.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum EvictionAction {
    /// Persist the advanced state (a daily window with surviving buckets), encoded.
    Write(Vec<u8>),
    /// Remove the fully-expired state. A late event re-creates it from its own timestamp.
    Delete,
}

/// What evicting one key implies: the optional `Left` it emits, the state mutation to apply, and the
/// next deadline to reschedule (`Some` only for a [`Write`](EvictionAction::Write) that still has a
/// finite eviction boundary).
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct EvictionResult {
    pub key: Stage1Key,
    pub variant: StateVariant,
    pub transition: Option<LeafTransition>,
    pub action: EvictionAction,
    pub reschedule: Option<i64>,
}

/// Compute the eviction for each due key against one team's frozen filters, **without writing**.
/// Returns one [`EvictionResult`] per key that has a supported, decodable state still in the catalog;
/// a missing/corrupt row, a leaf that left the catalog, or a person-property key is silently skipped
/// (no result → the worker simply does not reschedule it). A RocksDB read error fails the whole call
/// so the worker can reschedule and retry the tick.
///
/// All `due_keys` must belong to `filters`' team (the worker groups by team before calling).
pub(crate) fn sweep_evict(
    filters: &TeamFilters,
    due_keys: &[Stage1Key],
    store: &CohortStore,
    due_before_ms: i64,
) -> Result<Vec<EvictionResult>, StoreError> {
    let mut results = Vec::with_capacity(due_keys.len());
    for &key in due_keys {
        // A backend read error fails the whole call (the worker reschedules for retry); a missing or
        // corrupt row skips just this key.
        let record = match store.get_stage1(&key)? {
            None => continue,
            Some(bytes) => match StatefulRecord::decode(&bytes) {
                Ok(record) => record,
                Err(_) => {
                    counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
                    continue;
                }
            },
        };
        // The leaf left the catalog mid-tenure (drift) → skip. The state lingers until the next
        // rebalance reclaims the partition slice; it is never spuriously evicted.
        let Some(meta) = filters.by_lsk.get(&key.leaf_state_key) else {
            continue;
        };
        let result = match meta.variant {
            StateVariant::BehavioralSingle => evict_single(key, meta, record),
            StateVariant::BehavioralDailyBuckets => {
                evict_daily(key, meta, record, filters.timezone, due_before_ms)
            }
            // Person-property leaves carry no eviction deadline, so they are never scheduled; defend
            // against a stale schedule by skipping.
            StateVariant::PersonProperty => None,
        };
        results.extend(result);
    }
    Ok(results)
}

/// Evict a `performed_event` single: the window expired (the queue popped it past its deadline), so a
/// member leaves. Always deletes — a late event re-creates the state from its own timestamp.
/// Explicit-window singles never reach here (their `i64::MAX` deadline is never scheduled).
fn evict_single(
    key: Stage1Key,
    meta: &LeafStateMeta,
    record: StatefulRecord,
) -> Option<EvictionResult> {
    if !matches!(record.state, Stage1State::BehavioralSingle { .. }) {
        // The LSK pins the variant; a non-single value is corruption — skip.
        counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
        return None;
    }
    // A stored single is written only on a match, so the predicate is `true`; gate the `Left` on it
    // defensively so a (impossible) non-member single deletes without a spurious emit.
    let transition = predicate(&record.state, None).then(|| left_transition(key, meta));
    Some(EvictionResult {
        key,
        variant: StateVariant::BehavioralSingle,
        transition,
        action: EvictionAction::Delete,
        reschedule: None,
    })
}

/// Evict a `performed_event_multiple` daily window: slide it forward to `day_idx(due_before_ms)`
/// (the same AHEAD slide the event path does, minus the per-event increment), recompute the count
/// predicate, and emit `Left` on a true→false flip. Rewrites the advanced state with its new deadline
/// while any bucket survives; deletes once every bucket has drained.
fn evict_daily(
    key: Stage1Key,
    meta: &LeafStateMeta,
    record: StatefulRecord,
    tz: Tz,
    due_before_ms: i64,
) -> Option<EvictionResult> {
    // A daily leaf carries both by construction; absence is a catalog desync — skip.
    let (Some(window_days), Some(op)) = (meta.window_days, meta.predicate_op) else {
        counter!(STAGE1_UNSUPPORTED_VARIANT_SKIPPED, "variant" => StateVariant::BehavioralDailyBuckets.as_str())
            .increment(1);
        return None;
    };
    let StatefulRecord {
        state,
        applied_offsets,
    } = record;
    let Stage1State::BehavioralDailyBuckets {
        mut buckets,
        mut window_start_day,
        last_event_at_ms,
        ..
    } = state
    else {
        // The LSK pins the variant; a non-bucket value here is corruption — skip.
        counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
        return None;
    };
    // A stored array whose length disagrees with the leaf window is a format desync — skip rather
    // than slide out of bounds (mirrors the event path's guard).
    if buckets.len() != daily_bucket_len(window_days) {
        counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
        return None;
    }

    let predicate_before = daily_predicate(&buckets, op);
    let target_now_day = day_idx_in_tz(due_before_ms, tz);
    slide_window_forward(
        &mut buckets,
        &mut window_start_day,
        window_days,
        target_now_day,
    );
    let predicate_after = daily_predicate(&buckets, op);
    // A slide only drains buckets, so the predicate can only flip true→false; emit `Left` on that.
    let transition = (predicate_before && !predicate_after).then(|| left_transition(key, meta));

    let new_deadline = daily_eviction_deadline(&buckets, window_start_day, window_days, tz);
    let (action, reschedule) = if new_deadline == i64::MAX {
        // Every bucket drained: nothing left to evict, so delete. The topic's 24 h retention is below
        // the ≥1-day window, so no replayable event remains to spuriously re-create the state.
        (EvictionAction::Delete, None)
    } else {
        let advanced = StatefulRecord {
            state: Stage1State::BehavioralDailyBuckets {
                buckets,
                window_start_day,
                last_event_at_ms,
                earliest_eviction_at_ms: new_deadline,
            },
            applied_offsets,
        };
        (EvictionAction::Write(advanced.encode()), Some(new_deadline))
    };
    Some(EvictionResult {
        key,
        variant: StateVariant::BehavioralDailyBuckets,
        transition,
        action,
        reschedule,
    })
}

/// Build the `Left` transition for an evicted key. The sweep starts from a [`Stage1Key`] + catalog
/// meta rather than an event, so `condition_hash` comes from [`LeafStateMeta`].
fn left_transition(key: Stage1Key, meta: &LeafStateMeta) -> LeafTransition {
    LeafTransition {
        team_id: TeamId(key.team_id as i32),
        leaf_state_key: key.leaf_state_key,
        person_id: key.person_id,
        condition_hash: meta.condition_hash,
        kind: TransitionKind::Left,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono_tz::UTC;
    use serde_json::{json, Value};
    use tempfile::TempDir;
    use uuid::Uuid;

    use crate::filters::{CohortId, TeamFiltersBuilder, TeamId};
    use crate::stage1::bucket_tz::start_of_day_ms_in_tz;
    use crate::stage1::key::LeafStateKey;
    use crate::stage1::state::AppliedOffsets;
    use crate::stage1::time::clickhouse_timestamp_to_millis;
    use crate::store::StoreConfig;

    const TEAM: u64 = 7;
    const HASH: [u8; 16] = *b"0123456789abcdef";
    const PERSON_HASH: [u8; 16] = *b"fedcba9876543210";
    const PARTITION: u16 = 0;
    const WINDOW_DAYS: u32 = 7;
    const LEN: usize = WINDOW_DAYS as usize + 1;

    fn temp_store() -> (TempDir, CohortStore) {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        (dir, store)
    }

    fn freeze(values: Vec<Value>) -> TeamFilters {
        let cohort = json!({ "properties": { "type": "AND", "values": values } });
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(TEAM as i32), &cohort)
            .unwrap();
        builder.freeze(UTC)
    }

    fn single_leaf(window_days: i64) -> Value {
        json!({
            "type": "behavioral", "value": "performed_event", "key": "$pageview",
            "time_value": window_days, "time_interval": "day",
            "conditionHash": "0123456789abcdef",
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        })
    }

    fn daily_leaf(window_days: i64, op: &str, value: i64) -> Value {
        json!({
            "type": "behavioral", "value": "performed_event_multiple", "key": "$pageview",
            "time_value": window_days, "time_interval": "day",
            "operator": op, "operator_value": value,
            "conditionHash": "0123456789abcdef",
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        })
    }

    fn person_leaf() -> Value {
        json!({
            "type": "person", "key": "email", "value": "u@p.com", "operator": "exact",
            "conditionHash": "fedcba9876543210",
            "bytecode": ["_H", 1, 32, "u@p.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        })
    }

    fn key_for(filters: &TeamFilters, person: u128) -> Stage1Key {
        Stage1Key {
            partition_id: PARTITION,
            team_id: TEAM,
            leaf_state_key: filters.by_condition_to_lsk[&HASH][0],
            person_id: Uuid::from_u128(person),
        }
    }

    fn write(store: &CohortStore, key: &Stage1Key, state: Stage1State) {
        let record = StatefulRecord {
            state,
            applied_offsets: AppliedOffsets::default(),
        };
        store
            .write_batch(|b| b.put_stage1(key, &record.encode()))
            .unwrap();
    }

    fn day_of(ts: &str) -> i32 {
        day_idx_in_tz(clickhouse_timestamp_to_millis(ts).unwrap(), UTC)
    }

    #[test]
    fn single_eviction_emits_left_and_deletes() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![single_leaf(7)]);
        let key = key_for(&filters, 1);
        let event_ms = clickhouse_timestamp_to_millis("2026-05-20 10:00:00.000000").unwrap();
        let deadline = event_ms + 7 * 86_400 * 1_000;
        write(
            &store,
            &key,
            Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: event_ms,
                earliest_eviction_at_ms: deadline,
            },
        );

        let results = sweep_evict(&filters, &[key], &store, deadline + 86_400_000).unwrap();
        assert_eq!(results.len(), 1);
        let result = &results[0];
        assert_eq!(result.variant, StateVariant::BehavioralSingle);
        let transition = result.transition.as_ref().expect("a single evicts to Left");
        assert_eq!(transition.kind, TransitionKind::Left);
        assert_eq!(
            transition.condition_hash, HASH,
            "condition_hash from the meta"
        );
        assert_eq!(transition.person_id, key.person_id);
        assert_eq!(transition.team_id, TeamId(TEAM as i32));
        assert_eq!(result.action, EvictionAction::Delete);
        assert_eq!(result.reschedule, None);
    }

    #[test]
    fn daily_all_buckets_drain_emits_left_and_deletes() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![daily_leaf(7, "gte", 3)]);
        let key = key_for(&filters, 1);

        // Three matches on one day → the last bucket holds 3, window anchored that day.
        let day = day_of("2026-05-20 10:00:00.000000");
        let mut buckets = vec![0u32; LEN];
        buckets[LEN - 1] = 3;
        let window_start = day - WINDOW_DAYS as i32;
        let deadline = daily_eviction_deadline(&buckets, window_start, WINDOW_DAYS, UTC);
        write(
            &store,
            &key,
            Stage1State::BehavioralDailyBuckets {
                buckets,
                window_start_day: window_start,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: deadline,
            },
        );

        // Slide to the day the lone bucket leaves the window: every bucket drains.
        let cutoff = start_of_day_ms_in_tz(day + WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], &store, cutoff).unwrap();
        assert_eq!(results.len(), 1);
        let result = &results[0];
        assert_eq!(
            result.transition.as_ref().unwrap().kind,
            TransitionKind::Left,
        );
        assert_eq!(result.action, EvictionAction::Delete);
        assert_eq!(result.reschedule, None);
    }

    #[test]
    fn daily_drops_oldest_bucket_keeps_member_and_reschedules_later() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![daily_leaf(7, "gte", 1)]);
        let key = key_for(&filters, 1);

        // Two matches: the window's lower-bound day and four days later. Sliding past the oldest still
        // leaves the later bucket, so the person stays a member (gte 1) — a rewrite, not a delete.
        let now_day = day_of("2026-05-27 10:00:00.000000");
        let window_start = now_day - WINDOW_DAYS as i32;
        let mut buckets = vec![0u32; LEN];
        buckets[0] = 1; // day window_start
        buckets[4] = 1; // day window_start + 4
        let deadline = daily_eviction_deadline(&buckets, window_start, WINDOW_DAYS, UTC);
        write(
            &store,
            &key,
            Stage1State::BehavioralDailyBuckets {
                buckets,
                window_start_day: window_start,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: deadline,
            },
        );

        // Slide one day past the window's current now-day so only the oldest bucket leaves.
        let cutoff = start_of_day_ms_in_tz(window_start + WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], &store, cutoff).unwrap();
        assert_eq!(results.len(), 1);
        let result = &results[0];
        assert!(result.transition.is_none(), "still ≥ 1 match → no Left");

        let EvictionAction::Write(bytes) = &result.action else {
            panic!("a surviving bucket rewrites, not deletes");
        };
        let advanced = StatefulRecord::decode(bytes).unwrap();
        match advanced.state {
            Stage1State::BehavioralDailyBuckets {
                buckets,
                last_event_at_ms,
                earliest_eviction_at_ms,
                ..
            } => {
                assert_eq!(buckets.iter().sum::<u32>(), 1, "the oldest bucket dropped");
                assert_eq!(
                    last_event_at_ms, 1_700_000_000_000,
                    "preserved across the slide"
                );
                assert_eq!(earliest_eviction_at_ms, result.reschedule.unwrap());
            }
            other => panic!("expected daily buckets, got {other:?}"),
        }
        assert!(
            result.reschedule.unwrap() > deadline,
            "the surviving later bucket pushes the deadline forward",
        );
    }

    #[test]
    fn daily_length_mismatch_skips_without_panic() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![daily_leaf(7, "gte", 1)]); // expects length 8
        let key = key_for(&filters, 1);
        write(
            &store,
            &key,
            Stage1State::BehavioralDailyBuckets {
                buckets: vec![1, 2, 3], // wrong length
                window_start_day: 100,
                last_event_at_ms: 1,
                earliest_eviction_at_ms: 2,
            },
        );
        let results = sweep_evict(&filters, &[key], &store, i64::MAX).unwrap();
        assert!(
            results.is_empty(),
            "a length mismatch is skipped, not panicked"
        );
    }

    #[test]
    fn person_property_key_is_skipped() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![person_leaf()]);
        let key = Stage1Key {
            partition_id: PARTITION,
            team_id: TEAM,
            leaf_state_key: LeafStateKey::for_person_property(&PERSON_HASH),
            person_id: Uuid::from_u128(1),
        };
        write(
            &store,
            &key,
            Stage1State::PersonProperty {
                matches: true,
                last_updated_at_ms: 1,
                last_updated_offset: 2,
            },
        );
        let results = sweep_evict(&filters, &[key], &store, i64::MAX).unwrap();
        assert!(
            results.is_empty(),
            "person-property leaves are never time-evicted",
        );
    }

    #[test]
    fn unknown_leaf_and_missing_state_are_skipped() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![single_leaf(7)]);

        // A key whose LSK isn't in the catalog (drift): state present but no meta → skip.
        let drifted = Stage1Key {
            partition_id: PARTITION,
            team_id: TEAM,
            leaf_state_key: LeafStateKey([0xFF; 16]),
            person_id: Uuid::from_u128(1),
        };
        write(
            &store,
            &drifted,
            Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: 1,
                earliest_eviction_at_ms: 2,
            },
        );

        // A known leaf whose state was never written: missing row → skip.
        let missing = key_for(&filters, 999);

        let results = sweep_evict(&filters, &[drifted, missing], &store, i64::MAX).unwrap();
        assert!(
            results.is_empty(),
            "drift and missing rows both skip cleanly"
        );
    }

    #[test]
    fn evicts_multiple_keys_in_one_pass() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![single_leaf(7)]);
        let keys: Vec<Stage1Key> = (1..=3).map(|p| key_for(&filters, p)).collect();
        for key in &keys {
            write(
                &store,
                key,
                Stage1State::BehavioralSingle {
                    has_match: true,
                    last_event_at_ms: 1_000,
                    earliest_eviction_at_ms: 2_000,
                },
            );
        }
        let results = sweep_evict(&filters, &keys, &store, 10_000).unwrap();
        assert_eq!(results.len(), 3, "every member key evicts to a Left+Delete");
        assert!(results
            .iter()
            .all(|r| r.action == EvictionAction::Delete && r.transition.is_some()));
    }
}
