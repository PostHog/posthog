//! Per-key time-driven eviction.
//!
//! [`sweep_evict`] is a pure compute pass over states the caller has already read: for each due key
//! it drops aged-out bucket(s), recomputes the predicate, and returns the membership transition,
//! state mutation, and next eviction deadline --- but reads and writes nothing. The worker prefetches
//! the states, orchestrates produce-before-write ordering (so a produce failure can replay against
//! still-un-evicted state), and applies the resulting writes.

use chrono_tz::Tz;
use metrics::counter;

use crate::filters::reverse_index::{LeafStateMeta, TeamFilters};
use crate::filters::TeamId;
use crate::observability::metrics::{
    STAGE1_STATE_DECODE_ERROR, STAGE1_UNSUPPORTED_VARIANT_SKIPPED,
};
use crate::stage1::bucket_tz::{daily_bucket_len, day_idx_in_tz};
use crate::stage1::compressed_history;
use crate::stage1::daily::{daily_eviction_deadline, slide_window_forward};
use crate::stage1::key::Stage1Key;
use crate::stage1::predicate::{compressed_predicate, daily_predicate, predicate};
use crate::stage1::state::{Stage1State, StateVariant, StatefulRecord};
use crate::stage1::transition::{LeafTransition, TransitionKind};

/// The state mutation an eviction implies.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum EvictionAction {
    /// Persist the advanced state (surviving entries/buckets), encoded.
    Write(Vec<u8>),
    /// Remove the fully-expired state. A late event re-creates it from its own timestamp.
    Delete,
}

/// The outcome of evicting one key: optional transition, state mutation, and next deadline.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct EvictionResult {
    pub key: Stage1Key,
    pub variant: StateVariant,
    pub transition: Option<LeafTransition>,
    pub action: EvictionAction,
    pub reschedule: Option<i64>,
}

/// Why the sweep dropped a popped key instead of evicting it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum SweepDropReason {
    TeamDrift,
    LeafDrift,
    MissingState,
    Decode,
    UnsupportedVariant,
    PersonProperty,
}

impl SweepDropReason {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::TeamDrift => "team_drift",
            Self::LeafDrift => "leaf_drift",
            Self::MissingState => "missing_state",
            Self::Decode => "decode_error",
            Self::UnsupportedVariant => "unsupported_variant",
            Self::PersonProperty => "person_property",
        }
    }
}

/// Outcome of one [`sweep_evict`] pass: evictions to apply and drop reasons.
#[derive(Debug, Default)]
pub(crate) struct SweepEvictions {
    pub results: Vec<EvictionResult>,
    pub drops: Vec<SweepDropReason>,
}

/// Compute the eviction for each due key against a team's frozen filters, over states the caller has
/// already read. `values` is aligned with `due_keys` (same order, same length, `None` for an absent
/// key). All `due_keys` must belong to `filters`' team. Pure: no reads, no writes.
pub(crate) fn sweep_evict(
    filters: &TeamFilters,
    due_keys: &[Stage1Key],
    values: Vec<Option<Vec<u8>>>,
    due_before_ms: i64,
) -> SweepEvictions {
    let mut out = SweepEvictions {
        results: Vec::with_capacity(due_keys.len()),
        drops: Vec::new(),
    };
    // Alignment-safe zip: `multi_get_stage1` preserves input order, `None` for absent keys.
    for (&key, bytes) in due_keys.iter().zip(values) {
        let record = match bytes {
            None => {
                out.drops.push(SweepDropReason::MissingState);
                continue;
            }
            Some(bytes) => match StatefulRecord::decode(&bytes) {
                Ok(record) => record,
                Err(_) => {
                    counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
                    out.drops.push(SweepDropReason::Decode);
                    continue;
                }
            },
        };
        let Some(meta) = filters.by_lsk.get(&key.leaf_state_key) else {
            out.drops.push(SweepDropReason::LeafDrift);
            continue;
        };
        let evicted = match meta.variant {
            StateVariant::BehavioralSingle => evict_single(key, meta, record),
            StateVariant::BehavioralDailyBuckets => {
                evict_daily(key, meta, record, filters.timezone, due_before_ms)
            }
            StateVariant::BehavioralCompressedHistory => {
                evict_compressed(key, meta, record, filters.timezone, due_before_ms)
            }
            StateVariant::PersonProperty => Err(SweepDropReason::PersonProperty),
        };
        match evicted {
            Ok(result) => out.results.push(result),
            Err(reason) => out.drops.push(reason),
        }
    }
    out
}

/// Evict a `performed_event` single: always deletes.
fn evict_single(
    key: Stage1Key,
    meta: &LeafStateMeta,
    record: StatefulRecord,
) -> Result<EvictionResult, SweepDropReason> {
    if !matches!(record.state, Stage1State::BehavioralSingle { .. }) {
        counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
        return Err(SweepDropReason::Decode);
    }
    let transition =
        predicate(&record.state).then(|| transition_for(key, meta, TransitionKind::Left));
    Ok(EvictionResult {
        key,
        variant: StateVariant::BehavioralSingle,
        transition,
        action: EvictionAction::Delete,
        reschedule: None,
    })
}

/// Slide the daily window forward, recompute the predicate, and return the net membership flip.
/// Rewrites while any bucket survives; deletes when every bucket drains.
fn evict_daily(
    key: Stage1Key,
    meta: &LeafStateMeta,
    record: StatefulRecord,
    tz: Tz,
    due_before_ms: i64,
) -> Result<EvictionResult, SweepDropReason> {
    let (Some(window_days), Some(op)) = (meta.window_days, meta.predicate_op) else {
        counter!(STAGE1_UNSUPPORTED_VARIANT_SKIPPED, "variant" => StateVariant::BehavioralDailyBuckets.as_str())
            .increment(1);
        return Err(SweepDropReason::UnsupportedVariant);
    };
    let StatefulRecord {
        state,
        applied_offsets,
        redirect_dedup,
    } = record;
    let Stage1State::BehavioralDailyBuckets {
        mut buckets,
        mut window_start_day,
        last_event_at_ms,
        ..
    } = state
    else {
        counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
        return Err(SweepDropReason::Decode);
    };
    if buckets.len() != daily_bucket_len(window_days) {
        counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
        return Err(SweepDropReason::Decode);
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
    let kind = match (predicate_before, predicate_after) {
        (false, true) => Some(TransitionKind::Entered),
        (true, false) => Some(TransitionKind::Left),
        _ => None,
    };
    let transition = kind.map(|kind| transition_for(key, meta, kind));

    let new_deadline = daily_eviction_deadline(&buckets, window_start_day, window_days, tz);
    let (action, reschedule) = if new_deadline == i64::MAX {
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
            redirect_dedup,
        };
        (EvictionAction::Write(advanced.encode()), Some(new_deadline))
    };
    debug_assert!(
        !predicate_after || matches!(action, EvictionAction::Write(_)),
        "a still-member eviction must rewrite + reschedule, not delete",
    );
    Ok(EvictionResult {
        key,
        variant: StateVariant::BehavioralDailyBuckets,
        transition,
        action,
        reschedule,
    })
}

/// Slide the compressed window forward and return the net membership flip (sparse run-length
/// analog of [`evict_daily`]).
fn evict_compressed(
    key: Stage1Key,
    meta: &LeafStateMeta,
    record: StatefulRecord,
    tz: Tz,
    due_before_ms: i64,
) -> Result<EvictionResult, SweepDropReason> {
    let (Some(window_days), Some(op)) = (meta.window_days, meta.predicate_op) else {
        counter!(STAGE1_UNSUPPORTED_VARIANT_SKIPPED, "variant" => StateVariant::BehavioralCompressedHistory.as_str())
            .increment(1);
        return Err(SweepDropReason::UnsupportedVariant);
    };
    let StatefulRecord {
        state,
        applied_offsets,
        redirect_dedup,
    } = record;
    let Stage1State::BehavioralCompressedHistory {
        mut entries,
        mut window_start_day,
        last_event_at_ms,
        ..
    } = state
    else {
        counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
        return Err(SweepDropReason::Decode);
    };

    let predicate_before = compressed_predicate(&entries, op);
    let target_now_day = day_idx_in_tz(due_before_ms, tz);
    compressed_history::slide_window_forward(
        &mut entries,
        &mut window_start_day,
        window_days,
        target_now_day,
    );
    let predicate_after = compressed_predicate(&entries, op);
    let kind = match (predicate_before, predicate_after) {
        (false, true) => Some(TransitionKind::Entered),
        (true, false) => Some(TransitionKind::Left),
        _ => None,
    };
    let transition = kind.map(|kind| transition_for(key, meta, kind));

    let new_deadline = compressed_history::compressed_eviction_deadline(&entries, window_days, tz);
    let (action, reschedule) = if new_deadline == i64::MAX {
        (EvictionAction::Delete, None)
    } else {
        let advanced = StatefulRecord {
            state: Stage1State::BehavioralCompressedHistory {
                entries,
                window_start_day,
                last_event_at_ms,
                earliest_eviction_at_ms: new_deadline,
            },
            applied_offsets,
            redirect_dedup,
        };
        (EvictionAction::Write(advanced.encode()), Some(new_deadline))
    };
    debug_assert!(
        !predicate_after || matches!(action, EvictionAction::Write(_)),
        "a still-member eviction must rewrite + reschedule, not delete",
    );
    Ok(EvictionResult {
        key,
        variant: StateVariant::BehavioralCompressedHistory,
        transition,
        action,
        reschedule,
    })
}

fn transition_for(key: Stage1Key, meta: &LeafStateMeta, kind: TransitionKind) -> LeafTransition {
    LeafTransition {
        team_id: TeamId(key.team_id as i32),
        leaf_state_key: key.leaf_state_key,
        person_id: key.person_id,
        condition_hash: meta.condition_hash,
        kind,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono_tz::UTC;
    use serde_json::{json, Value};
    use uuid::Uuid;

    use crate::filters::{CohortId, TeamFiltersBuilder, TeamId};
    use crate::stage1::bucket_tz::start_of_day_ms_in_tz;
    use crate::stage1::key::LeafStateKey;
    use crate::stage1::state::AppliedOffsets;
    use crate::stage1::time::clickhouse_timestamp_to_millis;

    const TEAM: u64 = 7;
    const HASH: [u8; 16] = *b"0123456789abcdef";
    const PERSON_HASH: [u8; 16] = *b"fedcba9876543210";
    const PARTITION: u16 = 0;
    const WINDOW_DAYS: u32 = 7;
    const LEN: usize = WINDOW_DAYS as usize + 1;
    const COMPRESSED_WINDOW_DAYS: u32 = 365;

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

    fn compressed_leaf(window_days: i64, op: &str, value: i64) -> Value {
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

    /// The encoded stored record for `state`, as the worker's prefetch would hand `sweep_evict`.
    fn encoded(state: Stage1State) -> Option<Vec<u8>> {
        Some(StatefulRecord::new(state, AppliedOffsets::default()).encode())
    }

    fn day_of(ts: &str) -> i32 {
        day_idx_in_tz(clickhouse_timestamp_to_millis(ts).unwrap(), UTC)
    }

    #[test]
    fn single_eviction_emits_left_and_deletes() {
        let filters = freeze(vec![single_leaf(7)]);
        let key = key_for(&filters, 1);
        let event_ms = clickhouse_timestamp_to_millis("2026-05-20 10:00:00.000000").unwrap();
        let deadline = event_ms + 7 * 86_400 * 1_000;
        let values = vec![encoded(Stage1State::BehavioralSingle {
            has_match: true,
            last_event_at_ms: event_ms,
            earliest_eviction_at_ms: deadline,
        })];

        let results = sweep_evict(&filters, &[key], values, deadline + 86_400_000).results;
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
        let filters = freeze(vec![daily_leaf(7, "gte", 3)]);
        let key = key_for(&filters, 1);

        let day = day_of("2026-05-20 10:00:00.000000");
        let mut buckets = vec![0u32; LEN];
        buckets[LEN - 1] = 3;
        let window_start = day - WINDOW_DAYS as i32;
        let deadline = daily_eviction_deadline(&buckets, window_start, WINDOW_DAYS, UTC);
        let values = vec![encoded(Stage1State::BehavioralDailyBuckets {
            buckets,
            window_start_day: window_start,
            last_event_at_ms: 1_700_000_000_000,
            earliest_eviction_at_ms: deadline,
        })];

        let cutoff = start_of_day_ms_in_tz(day + WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], values, cutoff).results;
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
        let filters = freeze(vec![daily_leaf(7, "gte", 1)]);
        let key = key_for(&filters, 1);

        let now_day = day_of("2026-05-27 10:00:00.000000");
        let window_start = now_day - WINDOW_DAYS as i32;
        let mut buckets = vec![0u32; LEN];
        buckets[0] = 1; // day window_start
        buckets[4] = 1; // day window_start + 4
        let deadline = daily_eviction_deadline(&buckets, window_start, WINDOW_DAYS, UTC);
        let values = vec![encoded(Stage1State::BehavioralDailyBuckets {
            buckets,
            window_start_day: window_start,
            last_event_at_ms: 1_700_000_000_000,
            earliest_eviction_at_ms: deadline,
        })];

        let cutoff = start_of_day_ms_in_tz(window_start + WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], values, cutoff).results;
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
                assert_eq!(buckets.iter().sum::<u32>(), 1);
                assert_eq!(last_event_at_ms, 1_700_000_000_000);
                assert_eq!(earliest_eviction_at_ms, result.reschedule.unwrap());
            }
            other => panic!("expected daily buckets, got {other:?}"),
        }
        assert!(result.reschedule.unwrap() > deadline);
    }

    #[test]
    fn daily_eq_slide_into_range_emits_entered() {
        let filters = freeze(vec![daily_leaf(7, "eq", 1)]);
        let key = key_for(&filters, 1);

        let day = day_of("2026-05-27 10:00:00.000000");
        let window_start = day - WINDOW_DAYS as i32;
        let mut buckets = vec![0u32; LEN];
        buckets[0] = 1;
        buckets[4] = 1;
        let deadline = daily_eviction_deadline(&buckets, window_start, WINDOW_DAYS, UTC);
        let values = vec![encoded(Stage1State::BehavioralDailyBuckets {
            buckets,
            window_start_day: window_start,
            last_event_at_ms: 1_700_000_000_000,
            earliest_eviction_at_ms: deadline,
        })];

        let cutoff = start_of_day_ms_in_tz(window_start + WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], values, cutoff).results;
        assert_eq!(results.len(), 1);
        let result = &results[0];
        assert_eq!(
            result
                .transition
                .as_ref()
                .expect("a falling count enters eq 1")
                .kind,
            TransitionKind::Entered,
            "eq 1 flips false→true as the count drops to 1",
        );
        assert!(
            matches!(result.action, EvictionAction::Write(_)),
            "a still-member eviction rewrites the advanced state",
        );
        assert!(
            result.reschedule.is_some(),
            "the surviving bucket carries a finite next deadline",
        );
    }

    #[test]
    fn daily_lte_slide_into_range_emits_entered() {
        let filters = freeze(vec![daily_leaf(7, "lte", 2)]);
        let key = key_for(&filters, 1);

        let day = day_of("2026-05-27 10:00:00.000000");
        let window_start = day - WINDOW_DAYS as i32;
        let mut buckets = vec![0u32; LEN];
        buckets[0] = 1;
        buckets[4] = 2;
        let deadline = daily_eviction_deadline(&buckets, window_start, WINDOW_DAYS, UTC);
        let values = vec![encoded(Stage1State::BehavioralDailyBuckets {
            buckets,
            window_start_day: window_start,
            last_event_at_ms: 1_700_000_000_000,
            earliest_eviction_at_ms: deadline,
        })];

        let cutoff = start_of_day_ms_in_tz(window_start + WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], values, cutoff).results;
        assert_eq!(results.len(), 1);
        let result = &results[0];
        assert_eq!(
            result
                .transition
                .as_ref()
                .expect("a falling count enters lte 2")
                .kind,
            TransitionKind::Entered,
            "lte 2 flips false→true as the count drops to 2",
        );
        assert!(matches!(result.action, EvictionAction::Write(_)));
        assert!(result.reschedule.is_some());
    }

    #[test]
    fn compressed_all_entries_drain_emits_left_and_deletes() {
        let filters = freeze(vec![compressed_leaf(
            COMPRESSED_WINDOW_DAYS as i64,
            "gte",
            3,
        )]);
        let key = key_for(&filters, 1);

        let day = day_of("2026-05-20 10:00:00.000000");
        let entries = vec![(day, 3u32)];
        let window_start = day - COMPRESSED_WINDOW_DAYS as i32;
        let deadline =
            compressed_history::compressed_eviction_deadline(&entries, COMPRESSED_WINDOW_DAYS, UTC);
        let values = vec![encoded(Stage1State::BehavioralCompressedHistory {
            entries,
            window_start_day: window_start,
            last_event_at_ms: 1_700_000_000_000,
            earliest_eviction_at_ms: deadline,
        })];

        let cutoff = start_of_day_ms_in_tz(day + COMPRESSED_WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], values, cutoff).results;
        assert_eq!(results.len(), 1);
        let result = &results[0];
        assert_eq!(result.variant, StateVariant::BehavioralCompressedHistory);
        assert_eq!(
            result.transition.as_ref().unwrap().kind,
            TransitionKind::Left,
        );
        assert_eq!(result.action, EvictionAction::Delete);
        assert_eq!(result.reschedule, None);
    }

    #[test]
    fn compressed_drops_oldest_entry_keeps_member_and_reschedules_later() {
        let filters = freeze(vec![compressed_leaf(
            COMPRESSED_WINDOW_DAYS as i64,
            "gte",
            1,
        )]);
        let key = key_for(&filters, 1);

        let now_day = day_of("2026-05-27 10:00:00.000000");
        let window_start = now_day - COMPRESSED_WINDOW_DAYS as i32;
        let entries = vec![(window_start, 1u32), (window_start + 100, 1u32)];
        let deadline =
            compressed_history::compressed_eviction_deadline(&entries, COMPRESSED_WINDOW_DAYS, UTC);
        let values = vec![encoded(Stage1State::BehavioralCompressedHistory {
            entries,
            window_start_day: window_start,
            last_event_at_ms: 1_700_000_000_000,
            earliest_eviction_at_ms: deadline,
        })];

        let cutoff = start_of_day_ms_in_tz(window_start + COMPRESSED_WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], values, cutoff).results;
        assert_eq!(results.len(), 1);
        let result = &results[0];
        assert!(result.transition.is_none(), "still ≥ 1 match → no Left");

        let EvictionAction::Write(bytes) = &result.action else {
            panic!("a surviving entry rewrites, not deletes");
        };
        let advanced = StatefulRecord::decode(bytes).unwrap();
        match advanced.state {
            Stage1State::BehavioralCompressedHistory {
                entries,
                last_event_at_ms,
                earliest_eviction_at_ms,
                ..
            } => {
                assert_eq!(entries, vec![(window_start + 100, 1)]);
                assert_eq!(last_event_at_ms, 1_700_000_000_000);
                assert_eq!(earliest_eviction_at_ms, result.reschedule.unwrap());
            }
            other => panic!("expected compressed history, got {other:?}"),
        }
        assert!(result.reschedule.unwrap() > deadline);
    }

    #[test]
    fn compressed_eq_slide_into_range_emits_entered() {
        let filters = freeze(vec![compressed_leaf(
            COMPRESSED_WINDOW_DAYS as i64,
            "eq",
            1,
        )]);
        let key = key_for(&filters, 1);

        let now_day = day_of("2026-05-27 10:00:00.000000");
        let window_start = now_day - COMPRESSED_WINDOW_DAYS as i32;
        let entries = vec![(window_start, 1u32), (window_start + 100, 1u32)];
        let deadline =
            compressed_history::compressed_eviction_deadline(&entries, COMPRESSED_WINDOW_DAYS, UTC);
        let values = vec![encoded(Stage1State::BehavioralCompressedHistory {
            entries,
            window_start_day: window_start,
            last_event_at_ms: 1_700_000_000_000,
            earliest_eviction_at_ms: deadline,
        })];

        let cutoff = start_of_day_ms_in_tz(window_start + COMPRESSED_WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], values, cutoff).results;
        assert_eq!(results.len(), 1);
        let result = &results[0];
        assert_eq!(
            result
                .transition
                .as_ref()
                .expect("a falling count enters eq 1")
                .kind,
            TransitionKind::Entered,
            "eq 1 flips false→true as the count drops to 1",
        );
        assert!(
            matches!(result.action, EvictionAction::Write(_)),
            "a still-member eviction rewrites the advanced state",
        );
        assert!(result.reschedule.is_some());
    }

    #[test]
    fn compressed_lte_slide_into_range_emits_entered() {
        let filters = freeze(vec![compressed_leaf(
            COMPRESSED_WINDOW_DAYS as i64,
            "lte",
            2,
        )]);
        let key = key_for(&filters, 1);

        let now_day = day_of("2026-05-27 10:00:00.000000");
        let window_start = now_day - COMPRESSED_WINDOW_DAYS as i32;
        let entries = vec![(window_start, 1u32), (window_start + 100, 2u32)];
        let deadline =
            compressed_history::compressed_eviction_deadline(&entries, COMPRESSED_WINDOW_DAYS, UTC);
        let values = vec![encoded(Stage1State::BehavioralCompressedHistory {
            entries,
            window_start_day: window_start,
            last_event_at_ms: 1_700_000_000_000,
            earliest_eviction_at_ms: deadline,
        })];

        let cutoff = start_of_day_ms_in_tz(window_start + COMPRESSED_WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], values, cutoff).results;
        assert_eq!(results.len(), 1);
        let result = &results[0];
        assert_eq!(
            result
                .transition
                .as_ref()
                .expect("a falling count enters lte 2")
                .kind,
            TransitionKind::Entered,
            "lte 2 flips false→true as the count drops to 2",
        );
        assert!(matches!(result.action, EvictionAction::Write(_)));
        assert!(result.reschedule.is_some());
    }

    #[test]
    fn daily_length_mismatch_skips_without_panic() {
        let filters = freeze(vec![daily_leaf(7, "gte", 1)]); // expects length 8
        let key = key_for(&filters, 1);
        let values = vec![encoded(Stage1State::BehavioralDailyBuckets {
            buckets: vec![1, 2, 3], // wrong length
            window_start_day: 100,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: 2,
        })];
        let out = sweep_evict(&filters, &[key], values, i64::MAX);
        assert!(
            out.results.is_empty(),
            "a length mismatch is skipped, not panicked"
        );
        assert_eq!(
            out.drops,
            vec![SweepDropReason::Decode],
            "a length mismatch is dropped as a decode/format desync",
        );
    }

    #[test]
    fn person_property_key_is_skipped() {
        let filters = freeze(vec![person_leaf()]);
        let key = Stage1Key {
            partition_id: PARTITION,
            team_id: TEAM,
            leaf_state_key: LeafStateKey::for_person_property(&PERSON_HASH),
            person_id: Uuid::from_u128(1),
        };
        let values = vec![encoded(Stage1State::PersonProperty {
            matches: true,
            last_updated_at_ms: 1,
            last_updated_offset: 2,
        })];
        let out = sweep_evict(&filters, &[key], values, i64::MAX);
        assert!(
            out.results.is_empty(),
            "person-property leaves are never time-evicted",
        );
        assert_eq!(
            out.drops,
            vec![SweepDropReason::PersonProperty],
            "a scheduled person-property key is dropped defensively",
        );
    }

    #[test]
    fn unknown_leaf_and_missing_state_are_skipped() {
        let filters = freeze(vec![single_leaf(7)]);

        let drifted = Stage1Key {
            partition_id: PARTITION,
            team_id: TEAM,
            leaf_state_key: LeafStateKey([0xFF; 16]),
            person_id: Uuid::from_u128(1),
        };
        let missing = key_for(&filters, 999);
        // The drifted key has state; the missing key reads back as `None`.
        let values = vec![
            encoded(Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: 1,
                earliest_eviction_at_ms: 2,
            }),
            None,
        ];

        let out = sweep_evict(&filters, &[drifted, missing], values, i64::MAX);
        assert!(
            out.results.is_empty(),
            "drift and missing rows both skip cleanly"
        );
        assert_eq!(
            out.drops,
            vec![SweepDropReason::LeafDrift, SweepDropReason::MissingState],
            "the drifted key drops as leaf drift, the absent key as missing state",
        );
    }

    #[test]
    fn evicts_multiple_keys_in_one_pass() {
        let filters = freeze(vec![single_leaf(7)]);
        let keys: Vec<Stage1Key> = (1..=3).map(|p| key_for(&filters, p)).collect();
        let values: Vec<Option<Vec<u8>>> = keys
            .iter()
            .map(|_| {
                encoded(Stage1State::BehavioralSingle {
                    has_match: true,
                    last_event_at_ms: 1_000,
                    earliest_eviction_at_ms: 2_000,
                })
            })
            .collect();
        let results = sweep_evict(&filters, &keys, values, 10_000).results;
        assert_eq!(results.len(), 3, "every member key evicts to a Left+Delete");
        assert!(results
            .iter()
            .all(|r| r.action == EvictionAction::Delete && r.transition.is_some()));
    }
}
