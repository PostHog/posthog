//! The per-key time-driven eviction, mirroring [`process_event`]'s shape.
//!
//! [`sweep_evict`] is a pure read-and-compute pass: for each due key it reads the stored state,
//! drops the aged-out bucket(s), recomputes the predicate, and returns what *would* change — the
//! membership transition (a `Left`, or an `Entered` when a daily slide lowers the count into an
//! `Eq`/`Lte`/`Lt` range), the state mutation (rewrite or delete), and the next eviction deadline —
//! but writes nothing. The worker ([`handle_sweep`](crate::workers::worker)) orchestrates the
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
use crate::stage1::compressed_history;
use crate::stage1::daily::{daily_eviction_deadline, slide_window_forward};
use crate::stage1::key::Stage1Key;
use crate::stage1::predicate::{compressed_predicate, daily_predicate, predicate};
use crate::stage1::state::{Stage1State, StateVariant, StatefulRecord};
use crate::stage1::transition::{LeafTransition, TransitionKind};
use crate::store::{CohortStore, StoreError};

/// The state mutation an eviction implies, applied by the worker in one `WriteBatch` only after the
/// `Left`s are durably produced. The key lives on the [`EvictionResult`], so this is just the verb.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum EvictionAction {
    /// Persist the advanced state (surviving entries/buckets), encoded.
    Write(Vec<u8>),
    /// Remove the fully-expired state. A late event re-creates it from its own timestamp.
    Delete,
}

/// What evicting one key implies: the optional membership transition it emits (`Left` for any
/// variant; `Entered` only for a daily slide lowering the count into an `Eq`/`Lte`/`Lt` range), the
/// state mutation to apply, and the next deadline to reschedule (`Some` only for a
/// [`Write`](EvictionAction::Write) that still has a finite eviction boundary).
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct EvictionResult {
    pub key: Stage1Key,
    pub variant: StateVariant,
    pub transition: Option<LeafTransition>,
    pub action: EvictionAction,
    pub reschedule: Option<i64>,
}

/// Why the sweep dropped a popped key instead of evicting it — a key that was due but had no valid,
/// supported state to advance. Doubles as the `reason` label on
/// [`SWEEP_KEYS_DROPPED_TOTAL`](crate::observability::metrics::SWEEP_KEYS_DROPPED_TOTAL); the
/// `Decode`/`UnsupportedVariant` arms are *also* surfaced on the existing error counters.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum SweepDropReason {
    /// The team left the catalog mid-tenure; its keys cannot be evaluated until a rebalance reclaims
    /// the slice. Raised by the worker, which groups by team before calling [`sweep_evict`].
    TeamDrift,
    /// The leaf left the catalog mid-tenure (its `LeafStateKey` is no longer in the reverse index).
    LeafDrift,
    /// No stored state for the key.
    MissingState,
    /// The stored record failed to decode, or its value disagreed with the variant the `LeafStateKey`
    /// pins (corruption / format desync). Also counted on `stage1_state_decode_error_total`.
    Decode,
    /// A daily leaf whose catalog meta is missing `window_days`/`predicate_op` (a desync). Also
    /// counted on `stage1_unsupported_variant_skipped_total`.
    UnsupportedVariant,
    /// A person-property key — never time-evicted, so it should never have been scheduled; a stale
    /// schedule is dropped defensively.
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

/// The outcome of one [`sweep_evict`] pass over a team's due keys: the per-key evictions to apply, and
/// the reason each popped-but-not-evicted key was dropped. The worker counts both only once the tick
/// commits, so `popped == evicted + dropped` holds in steady state.
#[derive(Debug, Default)]
pub(crate) struct SweepEvictions {
    pub results: Vec<EvictionResult>,
    pub drops: Vec<SweepDropReason>,
}

/// Compute the eviction for each due key against one team's frozen filters, **without writing**.
/// Returns a [`SweepEvictions`] with one [`EvictionResult`] per key that has a supported, decodable
/// state still in the catalog, plus a [`SweepDropReason`] for each key that was popped but not evicted
/// (a missing/corrupt row, a leaf that left the catalog, or a person-property key). A RocksDB read
/// error fails the whole call so the worker can reschedule and retry the tick.
///
/// All `due_keys` must belong to `filters`' team (the worker groups by team before calling).
pub(crate) fn sweep_evict(
    filters: &TeamFilters,
    due_keys: &[Stage1Key],
    store: &CohortStore,
    due_before_ms: i64,
) -> Result<SweepEvictions, StoreError> {
    let mut out = SweepEvictions {
        results: Vec::with_capacity(due_keys.len()),
        drops: Vec::new(),
    };
    for &key in due_keys {
        // Read errors propagate (?); missing/corrupt rows drop the key and continue.
        let record = match store.get_stage1(&key)? {
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
        // The leaf left the catalog mid-tenure (drift) → drop. The state lingers until the next
        // rebalance reclaims the partition slice; it is never spuriously evicted.
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
            // Person-property leaves carry no eviction deadline, so they are never scheduled; defend
            // against a stale schedule by dropping.
            StateVariant::PersonProperty => Err(SweepDropReason::PersonProperty),
        };
        match evicted {
            Ok(result) => out.results.push(result),
            Err(reason) => out.drops.push(reason),
        }
    }
    Ok(out)
}

/// Evict a `performed_event` single: the window expired (the queue popped it past its deadline), so a
/// member leaves. Always deletes — a late event re-creates the state from its own timestamp.
/// Explicit-window singles never reach here (their `i64::MAX` deadline is never scheduled).
fn evict_single(
    key: Stage1Key,
    meta: &LeafStateMeta,
    record: StatefulRecord,
) -> Result<EvictionResult, SweepDropReason> {
    if !matches!(record.state, Stage1State::BehavioralSingle { .. }) {
        // The LSK pins the variant; a non-single value is corruption — drop.
        counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
        return Err(SweepDropReason::Decode);
    }
    // Defensive: a stored single is always a member; gate the Left to avoid a spurious emit.
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

/// Slide the daily window to `day_idx(due_before_ms)`, recompute the predicate, and return the net
/// membership flip: `Left` on true→false, or `Entered` on false→true (a falling count can enter an
/// `Eq`/`Lte`/`Lt` range). Only the net flip across a multi-boundary slide is emitted. Rewrites the
/// advanced state while any bucket survives; deletes when every bucket drains.
fn evict_daily(
    key: Stage1Key,
    meta: &LeafStateMeta,
    record: StatefulRecord,
    tz: Tz,
    due_before_ms: i64,
) -> Result<EvictionResult, SweepDropReason> {
    // A daily leaf carries both by construction; absence is a catalog desync — drop.
    let (Some(window_days), Some(op)) = (meta.window_days, meta.predicate_op) else {
        counter!(STAGE1_UNSUPPORTED_VARIANT_SKIPPED, "variant" => StateVariant::BehavioralDailyBuckets.as_str())
            .increment(1);
        return Err(SweepDropReason::UnsupportedVariant);
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
        // The LSK pins the variant; a non-bucket value here is corruption — drop.
        counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
        return Err(SweepDropReason::Decode);
    };
    // A stored array whose length disagrees with the leaf window is a format desync — drop rather
    // than slide out of bounds (mirrors the event path's guard).
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
    // Eq/Lte/Lt can flip false→true as the count falls (Entered), not only true→false (Left).
    let kind = match (predicate_before, predicate_after) {
        (false, true) => Some(TransitionKind::Entered),
        (true, false) => Some(TransitionKind::Left),
        _ => None,
    };
    let transition = kind.map(|kind| transition_for(key, meta, kind));

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
    // predicate_after ⟹ count ≥ 1 ⟹ finite deadline ⟹ Write branch, never Delete.
    debug_assert!(
        !predicate_after || matches!(action, EvictionAction::Write(_)),
        "a still-member eviction must rewrite + reschedule, not delete (relies on daily_predicate's count>=1 floor)",
    );
    Ok(EvictionResult {
        key,
        variant: StateVariant::BehavioralDailyBuckets,
        transition,
        action,
        reschedule,
    })
}

/// Slide the compressed window to `day_idx(due_before_ms)` and return the net membership flip —
/// identical in shape to [`evict_daily`] but over sparse run-length entries.
fn evict_compressed(
    key: Stage1Key,
    meta: &LeafStateMeta,
    record: StatefulRecord,
    tz: Tz,
    due_before_ms: i64,
) -> Result<EvictionResult, SweepDropReason> {
    // A compressed leaf carries both by construction; absence is a catalog desync — drop.
    let (Some(window_days), Some(op)) = (meta.window_days, meta.predicate_op) else {
        counter!(STAGE1_UNSUPPORTED_VARIANT_SKIPPED, "variant" => StateVariant::BehavioralCompressedHistory.as_str())
            .increment(1);
        return Err(SweepDropReason::UnsupportedVariant);
    };
    let StatefulRecord {
        state,
        applied_offsets,
    } = record;
    let Stage1State::BehavioralCompressedHistory {
        mut entries,
        mut window_start_day,
        last_event_at_ms,
        ..
    } = state
    else {
        // The LSK pins the variant; a non-compressed value here is corruption — drop.
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
    // Eq/Lte/Lt can flip false→true as the count falls (Entered), not only true→false (Left).
    let kind = match (predicate_before, predicate_after) {
        (false, true) => Some(TransitionKind::Entered),
        (true, false) => Some(TransitionKind::Left),
        _ => None,
    };
    let transition = kind.map(|kind| transition_for(key, meta, kind));

    let new_deadline = compressed_history::compressed_eviction_deadline(&entries, window_days, tz);
    let (action, reschedule) = if new_deadline == i64::MAX {
        // Every entry drained: nothing left to evict, so delete. A compressed key drains ≥180 days
        // after its last matching event — far past the source topic's 24 h retention — so no
        // replayable event remains to spuriously re-create the state.
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
        };
        (EvictionAction::Write(advanced.encode()), Some(new_deadline))
    };
    // predicate_after ⟹ count ≥ 1 ⟹ finite deadline ⟹ Write branch, never Delete.
    debug_assert!(
        !predicate_after || matches!(action, EvictionAction::Write(_)),
        "a still-member eviction must rewrite + reschedule, not delete (relies on compressed_predicate's count>=1 floor)",
    );
    Ok(EvictionResult {
        key,
        variant: StateVariant::BehavioralCompressedHistory,
        transition,
        action,
        reschedule,
    })
}

/// Build the membership transition for an evicted key. The sweep starts from a [`Stage1Key`] +
/// catalog meta rather than an event, so `condition_hash` comes from [`LeafStateMeta`].
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
    /// A >180-day window routes to the compressed variant.
    const COMPRESSED_WINDOW_DAYS: u32 = 365;

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

    /// A `performed_event_multiple` leaf over a >180-day window, routed to the compressed variant.
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

        let results = sweep_evict(&filters, &[key], &store, deadline + 86_400_000)
            .unwrap()
            .results;
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
        let results = sweep_evict(&filters, &[key], &store, cutoff)
            .unwrap()
            .results;
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
        let results = sweep_evict(&filters, &[key], &store, cutoff)
            .unwrap()
            .results;
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
    fn daily_eq_slide_into_range_emits_entered() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![daily_leaf(7, "eq", 1)]);
        let key = key_for(&filters, 1);

        // Two matching days → count 2, which is *not* `eq 1` (a non-member). Sliding past the oldest
        // bucket lowers the count to 1, flipping the predicate false→true — the Enter the old `gte`
        // tests never exercised because `gte` is monotonic under a drain.
        let day = day_of("2026-05-27 10:00:00.000000");
        let window_start = day - WINDOW_DAYS as i32;
        let mut buckets = vec![0u32; LEN];
        buckets[0] = 1; // day window_start — drops on the slide
        buckets[4] = 1; // day window_start + 4 — survives
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

        // Slide one day past the window's now-day so only the oldest bucket leaves: count 2 → 1.
        let cutoff = start_of_day_ms_in_tz(window_start + WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], &store, cutoff)
            .unwrap()
            .results;
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
        let (_dir, store) = temp_store();
        let filters = freeze(vec![daily_leaf(7, "lte", 2)]);
        let key = key_for(&filters, 1);

        // Count 3 is above `lte 2` (a non-member). Dropping the oldest bucket lowers it to 2 → member.
        let day = day_of("2026-05-27 10:00:00.000000");
        let window_start = day - WINDOW_DAYS as i32;
        let mut buckets = vec![0u32; LEN];
        buckets[0] = 1; // drops on the slide
        buckets[4] = 2; // survives, leaving count 2
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

        let cutoff = start_of_day_ms_in_tz(window_start + WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], &store, cutoff)
            .unwrap()
            .results;
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
        let (_dir, store) = temp_store();
        let filters = freeze(vec![compressed_leaf(
            COMPRESSED_WINDOW_DAYS as i64,
            "gte",
            3,
        )]);
        let key = key_for(&filters, 1);

        // Three matches on one day → a lone entry of count 3, window anchored that day.
        let day = day_of("2026-05-20 10:00:00.000000");
        let entries = vec![(day, 3u32)];
        let window_start = day - COMPRESSED_WINDOW_DAYS as i32;
        let deadline =
            compressed_history::compressed_eviction_deadline(&entries, COMPRESSED_WINDOW_DAYS, UTC);
        write(
            &store,
            &key,
            Stage1State::BehavioralCompressedHistory {
                entries,
                window_start_day: window_start,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: deadline,
            },
        );

        // Slide to the day the lone entry leaves the window: every entry drains.
        let cutoff = start_of_day_ms_in_tz(day + COMPRESSED_WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], &store, cutoff)
            .unwrap()
            .results;
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
        let (_dir, store) = temp_store();
        let filters = freeze(vec![compressed_leaf(
            COMPRESSED_WINDOW_DAYS as i64,
            "gte",
            1,
        )]);
        let key = key_for(&filters, 1);

        // Two matches 100 days apart, both inside the 365-day window. Sliding past the oldest still
        // leaves the later entry, so the person stays a member (gte 1) — a rewrite, not a delete.
        let now_day = day_of("2026-05-27 10:00:00.000000");
        let window_start = now_day - COMPRESSED_WINDOW_DAYS as i32;
        let entries = vec![(window_start, 1u32), (window_start + 100, 1u32)];
        let deadline =
            compressed_history::compressed_eviction_deadline(&entries, COMPRESSED_WINDOW_DAYS, UTC);
        write(
            &store,
            &key,
            Stage1State::BehavioralCompressedHistory {
                entries,
                window_start_day: window_start,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: deadline,
            },
        );

        // Slide one day past the window's current now-day so only the oldest entry leaves.
        let cutoff = start_of_day_ms_in_tz(window_start + COMPRESSED_WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], &store, cutoff)
            .unwrap()
            .results;
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
                assert_eq!(
                    entries,
                    vec![(window_start + 100, 1)],
                    "the oldest entry dropped"
                );
                assert_eq!(
                    last_event_at_ms, 1_700_000_000_000,
                    "preserved across the slide"
                );
                assert_eq!(earliest_eviction_at_ms, result.reschedule.unwrap());
            }
            other => panic!("expected compressed history, got {other:?}"),
        }
        assert!(
            result.reschedule.unwrap() > deadline,
            "the surviving later entry pushes the deadline forward",
        );
    }

    #[test]
    fn compressed_eq_slide_into_range_emits_entered() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![compressed_leaf(
            COMPRESSED_WINDOW_DAYS as i64,
            "eq",
            1,
        )]);
        let key = key_for(&filters, 1);

        // Count 2 (two entries) is not `eq 1`. Sliding past the oldest entry lowers the count to 1,
        // flipping false→true — the bidirectional Enter a `gte`-only sweep would have dropped.
        let now_day = day_of("2026-05-27 10:00:00.000000");
        let window_start = now_day - COMPRESSED_WINDOW_DAYS as i32;
        let entries = vec![(window_start, 1u32), (window_start + 100, 1u32)];
        let deadline =
            compressed_history::compressed_eviction_deadline(&entries, COMPRESSED_WINDOW_DAYS, UTC);
        write(
            &store,
            &key,
            Stage1State::BehavioralCompressedHistory {
                entries,
                window_start_day: window_start,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: deadline,
            },
        );

        let cutoff = start_of_day_ms_in_tz(window_start + COMPRESSED_WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], &store, cutoff)
            .unwrap()
            .results;
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
        let (_dir, store) = temp_store();
        let filters = freeze(vec![compressed_leaf(
            COMPRESSED_WINDOW_DAYS as i64,
            "lte",
            2,
        )]);
        let key = key_for(&filters, 1);

        // Count 3 is above `lte 2`. Dropping the oldest entry lowers it to 2 → member.
        let now_day = day_of("2026-05-27 10:00:00.000000");
        let window_start = now_day - COMPRESSED_WINDOW_DAYS as i32;
        let entries = vec![(window_start, 1u32), (window_start + 100, 2u32)];
        let deadline =
            compressed_history::compressed_eviction_deadline(&entries, COMPRESSED_WINDOW_DAYS, UTC);
        write(
            &store,
            &key,
            Stage1State::BehavioralCompressedHistory {
                entries,
                window_start_day: window_start,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: deadline,
            },
        );

        let cutoff = start_of_day_ms_in_tz(window_start + COMPRESSED_WINDOW_DAYS as i32 + 1, UTC);
        let results = sweep_evict(&filters, &[key], &store, cutoff)
            .unwrap()
            .results;
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
        let out = sweep_evict(&filters, &[key], &store, i64::MAX).unwrap();
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
        let out = sweep_evict(&filters, &[key], &store, i64::MAX).unwrap();
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

        let out = sweep_evict(&filters, &[drifted, missing], &store, i64::MAX).unwrap();
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
        let results = sweep_evict(&filters, &keys, &store, 10_000)
            .unwrap()
            .results;
        assert_eq!(results.len(), 3, "every member key evicts to a Left+Delete");
        assert!(results
            .iter()
            .all(|r| r.action == EvictionAction::Delete && r.transition.is_some()));
    }
}
