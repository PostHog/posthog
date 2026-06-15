//! The per-event read-modify-write — the Stage 1 "brain".
//!
//! [`process_event`] folds one re-keyed event into each affected leaf's RocksDB state under one
//! atomic [`WriteBatch`](crate::store::CohortStore::write_batch) and returns the transitions that
//! flipped. Transitions are surfaced only after the commit succeeds.

use std::collections::BTreeMap;

use metrics::counter;
use uuid::Uuid;

use crate::consumers::events::CohortStreamEvent;
use crate::filters::reverse_index::TeamFilters;
use crate::filters::TeamId;
use crate::hogvm::{build_behavioral_globals, build_person_property_globals, evaluate};
use crate::observability::metrics::{
    STAGE1_ARGMAX_STALE, STAGE1_CONDITIONS_EVALUATED, STAGE1_PERSON_INDEX_APPENDS,
    STAGE1_REPLAY_SKIPPED, STAGE1_STATE_DECODE_ERROR, STAGE1_STATE_WRITES,
    STAGE1_UNSUPPORTED_VARIANT_SKIPPED,
};
use crate::stage1::bucket_tz::{daily_bucket_len, day_idx_in_tz};
use crate::stage1::compressed_history;
use crate::stage1::daily::{daily_eviction_deadline, slide_window_forward};
use crate::stage1::key::{LeafStateKey, Stage1Key};
use crate::stage1::pick_state::EvictionWindow;
use crate::stage1::predicate::{compressed_predicate, daily_predicate, predicate};
use crate::stage1::state::{
    dedup_is_replay, dedup_record, AppliedOffsets, Stage1State, StateVariant, StatefulRecord,
};
use crate::stage1::time::clickhouse_timestamp_to_millis;
use crate::stage1::transition::{LeafTransition, TransitionKind};
use crate::store::{CohortStore, IndexOp, PersonIndexKey, StoreError};

/// Why an event was skipped whole.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SkipReason {
    NullPersonId,
    /// Non-empty but not a valid UUID.
    UnparseablePersonId,
    NoTeamFilters,
    NoConditions,
    GlobalsParseError,
    BadTimestamp,
}

impl SkipReason {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::NullPersonId => "null_person_id",
            Self::UnparseablePersonId => "unparseable_person_id",
            Self::NoTeamFilters => "no_team_filters",
            Self::NoConditions => "no_conditions",
            Self::GlobalsParseError => "globals_parse_error",
            Self::BadTimestamp => "bad_timestamp",
        }
    }
}

/// Either skipped whole (`skipped = Some`, no transitions) or processed (`skipped = None`).
#[derive(Debug, Default, PartialEq, Eq)]
pub struct EventOutcome {
    pub transitions: Vec<LeafTransition>,
    pub schedules: Vec<(Stage1Key, i64)>,
    /// This event's parsed timestamp (epoch ms). `0` on skip/no-applies paths.
    pub event_ms: i64,
    pub skipped: Option<SkipReason>,
}

impl EventOutcome {
    fn processed(
        transitions: Vec<LeafTransition>,
        schedules: Vec<(Stage1Key, i64)>,
        event_ms: i64,
    ) -> Self {
        Self {
            transitions,
            schedules,
            event_ms,
            skipped: None,
        }
    }

    fn skipped(reason: SkipReason) -> Self {
        Self {
            transitions: Vec::new(),
            schedules: Vec::new(),
            event_ms: 0,
            skipped: Some(reason),
        }
    }
}

enum Apply {
    /// Behavioral leaf matched (recorded only on match).
    Behavioral {
        lsk: LeafStateKey,
        condition_hash: [u8; 16],
    },
    /// Person-property leaf evaluated (recorded on match *and* non-match).
    Person {
        lsk: LeafStateKey,
        condition_hash: [u8; 16],
        matches: bool,
    },
}

impl Apply {
    fn lsk(&self) -> LeafStateKey {
        match self {
            Self::Behavioral { lsk, .. } | Self::Person { lsk, .. } => *lsk,
        }
    }
}

struct PendingWrite {
    key: Stage1Key,
    bytes: Vec<u8>,
    first_write: bool,
    variant: StateVariant,
}

/// Process one re-keyed event against a team's frozen filters.
pub fn process_event(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    event: &CohortStreamEvent,
) -> Result<EventOutcome, StoreError> {
    if event.person_id.is_empty() {
        return Ok(EventOutcome::skipped(SkipReason::NullPersonId));
    }
    let Ok(person_id) = Uuid::parse_str(&event.person_id) else {
        return Ok(EventOutcome::skipped(SkipReason::UnparseablePersonId));
    };

    let origin: Option<Uuid> = event
        .redirected_from
        .as_deref()
        .and_then(|raw| Uuid::parse_str(raw).ok());
    let origin = origin.as_ref();

    let has_behavioral = !filters.behavioral_conditions.is_empty();
    let has_person = !filters.person_property_conditions.is_empty();
    if !has_behavioral && !has_person {
        return Ok(EventOutcome::skipped(SkipReason::NoConditions));
    }

    let behavioral_globals = if has_behavioral {
        match build_behavioral_globals(event) {
            Ok(globals) => Some(globals),
            Err(_) => return Ok(EventOutcome::skipped(SkipReason::GlobalsParseError)),
        }
    } else {
        None
    };
    let person_active = has_person
        && event
            .person_properties
            .as_deref()
            .is_some_and(|raw| !raw.is_empty());
    let person_globals = if person_active {
        match build_person_property_globals(event) {
            Ok(globals) => Some(globals),
            Err(_) => return Ok(EventOutcome::skipped(SkipReason::GlobalsParseError)),
        }
    } else {
        None
    };

    let applies = collect_applies(
        filters,
        behavioral_globals.as_ref(),
        person_globals.as_ref(),
    );
    if applies.is_empty() {
        return Ok(EventOutcome::processed(Vec::new(), Vec::new(), 0));
    }

    let Some(event_ms) = clickhouse_timestamp_to_millis(&event.timestamp) else {
        return Ok(EventOutcome::skipped(SkipReason::BadTimestamp));
    };

    let team_id = event.team_id as u64;
    let mut transitions = Vec::new();
    let mut schedules: Vec<(Stage1Key, i64)> = Vec::new();
    let mut pending = Vec::new();

    for apply in &applies {
        let key = Stage1Key {
            partition_id,
            team_id,
            leaf_state_key: apply.lsk(),
            person_id,
        };

        let prev = match store.get_stage1(&key)? {
            None => None,
            Some(bytes) => match StatefulRecord::decode(&bytes) {
                Ok(record) => Some(record),
                Err(_) => {
                    counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
                    continue;
                }
            },
        };
        let first_write = prev.is_none();

        let mutation = match apply {
            Apply::Behavioral { condition_hash, .. } => {
                match filters.by_lsk.get(&apply.lsk()).map(|meta| meta.variant) {
                    Some(StateVariant::BehavioralDailyBuckets) => mutate_behavioral_daily(
                        filters,
                        apply.lsk(),
                        *condition_hash,
                        person_id,
                        origin,
                        event,
                        event_ms,
                        prev,
                    ),
                    Some(StateVariant::BehavioralCompressedHistory) => {
                        mutate_behavioral_compressed(
                            filters,
                            apply.lsk(),
                            *condition_hash,
                            person_id,
                            origin,
                            event,
                            event_ms,
                            prev,
                        )
                    }
                    _ => mutate_behavioral(
                        filters,
                        apply.lsk(),
                        *condition_hash,
                        person_id,
                        origin,
                        event,
                        event_ms,
                        prev,
                    ),
                }
            }
            Apply::Person {
                condition_hash,
                matches,
                ..
            } => mutate_person(
                apply.lsk(),
                *condition_hash,
                *matches,
                person_id,
                origin,
                event,
                event_ms,
                prev,
            ),
        };

        let Some((record, transition)) = mutation else {
            continue;
        };

        if let Some(transition) = transition {
            transitions.push(transition);
        }
        if let Some(deadline) = schedule_deadline(&record.state) {
            schedules.push((key, deadline));
        }
        pending.push(PendingWrite {
            variant: record.state.variant(),
            bytes: record.encode(),
            key,
            first_write,
        });
    }

    if !pending.is_empty() {
        let person_index = PersonIndexKey {
            partition_id,
            team_id,
            person_id,
        };
        store.write_batch(|batch| {
            for write in &pending {
                batch.put_stage1(&write.key, &write.bytes);
                if write.first_write {
                    batch.merge_person_index(
                        &person_index,
                        IndexOp::Append(write.key.leaf_state_key),
                    );
                }
            }
        })?;

        for write in &pending {
            counter!(STAGE1_STATE_WRITES, "variant" => write.variant.as_str()).increment(1);
            if write.first_write {
                counter!(STAGE1_PERSON_INDEX_APPENDS).increment(1);
            }
        }
    }

    Ok(EventOutcome::processed(transitions, schedules, event_ms))
}

/// The finite eviction deadline to schedule for a just-written state, or [`None`] when it never
/// evicts (states with `i64::MAX` deadline are left out of the sweep queue).
pub(crate) fn schedule_deadline(state: &Stage1State) -> Option<i64> {
    let deadline = match state {
        Stage1State::BehavioralSingle {
            earliest_eviction_at_ms,
            ..
        }
        | Stage1State::BehavioralDailyBuckets {
            earliest_eviction_at_ms,
            ..
        }
        | Stage1State::BehavioralCompressedHistory {
            earliest_eviction_at_ms,
            ..
        } => *earliest_eviction_at_ms,
        Stage1State::PersonProperty { .. } => return None,
    };
    (deadline != i64::MAX).then_some(deadline)
}

/// Evaluate each conditionHash once and gather the leaves to fold.
fn collect_applies(
    filters: &TeamFilters,
    behavioral_globals: Option<&serde_json::Value>,
    person_globals: Option<&serde_json::Value>,
) -> Vec<Apply> {
    let mut applies = Vec::new();

    if let Some(globals) = behavioral_globals {
        for &hash in &filters.behavioral_conditions {
            let Some(bytecode) = filters.by_condition_to_bytecode.get(&hash) else {
                continue;
            };
            counter!(STAGE1_CONDITIONS_EVALUATED, "kind" => "behavioral").increment(1);
            if !evaluate(bytecode, globals.clone()) {
                continue;
            }
            let Some(lsks) = filters.by_condition_to_lsk.get(&hash) else {
                continue;
            };
            for &lsk in lsks {
                match filters.by_lsk.get(&lsk).map(|meta| meta.variant) {
                    Some(
                        StateVariant::BehavioralSingle
                        | StateVariant::BehavioralDailyBuckets
                        | StateVariant::BehavioralCompressedHistory,
                    ) => {
                        applies.push(Apply::Behavioral {
                            lsk,
                            condition_hash: hash,
                        });
                    }
                    Some(other) => {
                        counter!(STAGE1_UNSUPPORTED_VARIANT_SKIPPED, "variant" => other.as_str())
                            .increment(1);
                    }
                    None => {}
                }
            }
        }
    }

    if let Some(globals) = person_globals {
        for &hash in &filters.person_property_conditions {
            let Some(bytecode) = filters.by_condition_to_bytecode.get(&hash) else {
                continue;
            };
            counter!(STAGE1_CONDITIONS_EVALUATED, "kind" => "person_property").increment(1);
            let matches = evaluate(bytecode, globals.clone());
            let lsk = LeafStateKey::for_person_property(&hash);
            match filters.by_lsk.get(&lsk).map(|meta| meta.variant) {
                Some(StateVariant::PersonProperty) => {
                    applies.push(Apply::Person {
                        lsk,
                        condition_hash: hash,
                        matches,
                    });
                }
                Some(other) => {
                    counter!(STAGE1_UNSUPPORTED_VARIANT_SKIPPED, "variant" => other.as_str())
                        .increment(1);
                }
                None => {}
            }
        }
    }

    applies
}

/// Fold a behavioral match into a single-bit leaf. Never emits `Left` (match is never cleared).
#[allow(clippy::too_many_arguments)]
fn mutate_behavioral(
    filters: &TeamFilters,
    lsk: LeafStateKey,
    condition_hash: [u8; 16],
    person_id: Uuid,
    origin: Option<&Uuid>,
    event: &CohortStreamEvent,
    event_ms: i64,
    prev: Option<StatefulRecord>,
) -> Option<(StatefulRecord, Option<LeafTransition>)> {
    let (prev_last_event, predicate_before, mut applied, mut redirect_dedup) = match prev {
        None => (i64::MIN, false, AppliedOffsets::default(), BTreeMap::new()),
        Some(record) => {
            let predicate_before = predicate(&record.state);
            match record.state {
                Stage1State::BehavioralSingle {
                    last_event_at_ms, ..
                } => (
                    last_event_at_ms,
                    predicate_before,
                    record.applied_offsets,
                    record.redirect_dedup,
                ),
                _ => {
                    counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
                    return None;
                }
            }
        }
    };

    let window = filters.by_lsk.get(&lsk).and_then(|meta| meta.window);

    // An absolute explicit range matches at **day** granularity, inclusive on both ends, mirroring
    // the oracle's `date >= toDate(from) AND date <= toDate(to)` against `precalculated_events.date`.
    // Drop an out-of-range event whole (no dedup record, no state, no schedule, no transition): it is
    // simply not a match for this leaf, just as the oracle's date filter excludes it. The event's day
    // is its team-tz calendar day (`day_idx_in_tz`); the bound is already a tz-naive calendar day (the
    // oracle treats `explicit_datetime` as a tz-naive date, so `toDate('2026-05-01')` is the literal
    // date), so it is compared **directly** — never re-projected through a timezone, which would shift
    // it one calendar day under a UTC-offset team.
    if let Some(EvictionWindow::Explicit { from_day, to_day }) = window {
        let event_day = day_idx_in_tz(event_ms, filters.timezone);
        let before_from = from_day.is_some_and(|f| event_day < f);
        let after_to = to_day.is_some_and(|t| event_day > t);
        if before_from || after_to {
            return None;
        }
    }

    if dedup_is_replay(
        &applied,
        &redirect_dedup,
        origin,
        event.source_partition,
        event.source_offset,
    ) {
        counter!(STAGE1_REPLAY_SKIPPED, "variant" => StateVariant::BehavioralSingle.as_str())
            .increment(1);
        return None;
    }
    dedup_record(
        &mut applied,
        &mut redirect_dedup,
        origin,
        event.source_partition,
        event.source_offset,
    );

    let last_event_at_ms = prev_last_event.max(event_ms);
    let earliest_eviction_at_ms = window.map_or(i64::MAX, |w| {
        w.earliest_eviction_at_ms(last_event_at_ms, filters.timezone)
    });

    let record = StatefulRecord {
        state: Stage1State::BehavioralSingle {
            has_match: true,
            last_event_at_ms,
            earliest_eviction_at_ms,
        },
        applied_offsets: applied,
        redirect_dedup,
    };
    let transition = if predicate_before {
        None
    } else {
        Some(LeafTransition {
            team_id: TeamId(event.team_id),
            leaf_state_key: lsk,
            person_id,
            condition_hash,
            kind: TransitionKind::Entered,
        })
    };
    Some((record, transition))
}

/// Fold a `performed_event_multiple` match into a dense daily-bucket state. A window slide can
/// drop the count below threshold and emit `Left`.
#[allow(clippy::too_many_arguments)]
fn mutate_behavioral_daily(
    filters: &TeamFilters,
    lsk: LeafStateKey,
    condition_hash: [u8; 16],
    person_id: Uuid,
    origin: Option<&Uuid>,
    event: &CohortStreamEvent,
    event_ms: i64,
    prev: Option<StatefulRecord>,
) -> Option<(StatefulRecord, Option<LeafTransition>)> {
    let (Some(window_days), Some(op)) = filters
        .by_lsk
        .get(&lsk)
        .map_or((None, None), |meta| (meta.window_days, meta.predicate_op))
    else {
        counter!(STAGE1_UNSUPPORTED_VARIANT_SKIPPED, "variant" => StateVariant::BehavioralDailyBuckets.as_str())
            .increment(1);
        return None;
    };
    let tz = filters.timezone;
    let len = daily_bucket_len(window_days);

    let (prior_buckets, prior_window_start_day, prev_last_event, mut applied, mut redirect_dedup) =
        match prev {
            None => (
                None,
                0_i32,
                i64::MIN,
                AppliedOffsets::default(),
                BTreeMap::new(),
            ),
            Some(record) => match record.state {
                Stage1State::BehavioralDailyBuckets {
                    buckets,
                    window_start_day,
                    last_event_at_ms,
                    ..
                } => (
                    Some(buckets),
                    window_start_day,
                    last_event_at_ms,
                    record.applied_offsets,
                    record.redirect_dedup,
                ),
                _ => {
                    counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
                    return None;
                }
            },
        };

    if dedup_is_replay(
        &applied,
        &redirect_dedup,
        origin,
        event.source_partition,
        event.source_offset,
    ) {
        counter!(STAGE1_REPLAY_SKIPPED, "variant" => StateVariant::BehavioralDailyBuckets.as_str())
            .increment(1);
        return None;
    }
    dedup_record(
        &mut applied,
        &mut redirect_dedup,
        origin,
        event.source_partition,
        event.source_offset,
    );

    let mut buckets = match prior_buckets {
        Some(buckets) if buckets.len() == len => buckets,
        Some(_) => {
            counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
            return None;
        }
        None => Vec::new(),
    };

    let predicate_before = daily_predicate(&buckets, op);

    let event_day = day_idx_in_tz(event_ms, tz);
    let window_days_idx = window_days as i32;
    let mut window_start_day = if buckets.is_empty() {
        buckets = vec![0; len];
        event_day - window_days_idx
    } else {
        prior_window_start_day
    };

    let cur_now_day = window_start_day + window_days_idx;
    if event_day > cur_now_day {
        slide_window_forward(&mut buckets, &mut window_start_day, window_days, event_day);
        let last = len - 1;
        buckets[last] = buckets[last].saturating_add(1);
    } else if event_day < window_start_day {
        // Already slid out of the window.
    } else {
        let idx = (event_day - window_start_day) as usize;
        buckets[idx] = buckets[idx].saturating_add(1);
    }

    let last_event_at_ms = prev_last_event.max(event_ms);
    let earliest_eviction_at_ms =
        daily_eviction_deadline(&buckets, window_start_day, window_days, tz);
    let predicate_after = daily_predicate(&buckets, op);

    let record = StatefulRecord {
        state: Stage1State::BehavioralDailyBuckets {
            buckets,
            window_start_day,
            last_event_at_ms,
            earliest_eviction_at_ms,
        },
        applied_offsets: applied,
        redirect_dedup,
    };
    let kind = match (predicate_before, predicate_after) {
        (false, true) => Some(TransitionKind::Entered),
        (true, false) => Some(TransitionKind::Left),
        _ => None,
    };
    let transition = kind.map(|kind| LeafTransition {
        team_id: TeamId(event.team_id),
        leaf_state_key: lsk,
        person_id,
        condition_hash,
        kind,
    });
    Some((record, transition))
}

/// Fold a `performed_event_multiple` match into sparse compressed-history state (>180-day windows).
/// Structurally identical to [`mutate_behavioral_daily`] but over run-length entries.
#[allow(clippy::too_many_arguments)]
fn mutate_behavioral_compressed(
    filters: &TeamFilters,
    lsk: LeafStateKey,
    condition_hash: [u8; 16],
    person_id: Uuid,
    origin: Option<&Uuid>,
    event: &CohortStreamEvent,
    event_ms: i64,
    prev: Option<StatefulRecord>,
) -> Option<(StatefulRecord, Option<LeafTransition>)> {
    let (Some(window_days), Some(op)) = filters
        .by_lsk
        .get(&lsk)
        .map_or((None, None), |meta| (meta.window_days, meta.predicate_op))
    else {
        counter!(STAGE1_UNSUPPORTED_VARIANT_SKIPPED, "variant" => StateVariant::BehavioralCompressedHistory.as_str())
            .increment(1);
        return None;
    };
    let tz = filters.timezone;

    let (prior_entries, prior_window_start_day, prev_last_event, mut applied, mut redirect_dedup) =
        match prev {
            None => (
                None,
                0_i32,
                i64::MIN,
                AppliedOffsets::default(),
                BTreeMap::new(),
            ),
            Some(record) => match record.state {
                Stage1State::BehavioralCompressedHistory {
                    entries,
                    window_start_day,
                    last_event_at_ms,
                    ..
                } => (
                    Some(entries),
                    window_start_day,
                    last_event_at_ms,
                    record.applied_offsets,
                    record.redirect_dedup,
                ),
                _ => {
                    counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
                    return None;
                }
            },
        };

    if dedup_is_replay(
        &applied,
        &redirect_dedup,
        origin,
        event.source_partition,
        event.source_offset,
    ) {
        counter!(STAGE1_REPLAY_SKIPPED, "variant" => StateVariant::BehavioralCompressedHistory.as_str())
            .increment(1);
        return None;
    }
    dedup_record(
        &mut applied,
        &mut redirect_dedup,
        origin,
        event.source_partition,
        event.source_offset,
    );

    let first_write = prior_entries.is_none();
    let mut entries = prior_entries.unwrap_or_default();

    let predicate_before = compressed_predicate(&entries, op);

    let event_day = day_idx_in_tz(event_ms, tz);
    let window_days_idx = window_days as i32;
    let mut window_start_day = if first_write {
        event_day - window_days_idx
    } else {
        prior_window_start_day
    };

    let cur_now_day = window_start_day + window_days_idx;
    if event_day > cur_now_day {
        compressed_history::slide_window_forward(
            &mut entries,
            &mut window_start_day,
            window_days,
            event_day,
        );
        compressed_history::insert_event(&mut entries, event_day);
    } else if event_day < window_start_day {
        // Already slid out of the window.
    } else {
        compressed_history::insert_event(&mut entries, event_day);
    }

    let last_event_at_ms = prev_last_event.max(event_ms);
    let earliest_eviction_at_ms =
        compressed_history::compressed_eviction_deadline(&entries, window_days, tz);
    let predicate_after = compressed_predicate(&entries, op);

    let record = StatefulRecord {
        state: Stage1State::BehavioralCompressedHistory {
            entries,
            window_start_day,
            last_event_at_ms,
            earliest_eviction_at_ms,
        },
        applied_offsets: applied,
        redirect_dedup,
    };
    let kind = match (predicate_before, predicate_after) {
        (false, true) => Some(TransitionKind::Entered),
        (true, false) => Some(TransitionKind::Left),
        _ => None,
    };
    let transition = kind.map(|kind| LeafTransition {
        team_id: TeamId(event.team_id),
        leaf_state_key: lsk,
        person_id,
        condition_hash,
        kind,
    });
    Some((record, transition))
}

/// Fold a person-property evaluation into a leaf's state with replay-dedup and argMax tiebreaker.
#[allow(clippy::too_many_arguments)]
fn mutate_person(
    lsk: LeafStateKey,
    condition_hash: [u8; 16],
    matches: bool,
    person_id: Uuid,
    origin: Option<&Uuid>,
    event: &CohortStreamEvent,
    event_ms: i64,
    prev: Option<StatefulRecord>,
) -> Option<(StatefulRecord, Option<LeafTransition>)> {
    let (prev_matches, prev_updated_at, prev_updated_offset, mut applied, mut redirect_dedup) =
        match prev {
            None => (
                false,
                i64::MIN,
                i64::MIN,
                AppliedOffsets::default(),
                BTreeMap::new(),
            ),
            Some(record) => match record.state {
                Stage1State::PersonProperty {
                    matches,
                    last_updated_at_ms,
                    last_updated_offset,
                } => (
                    matches,
                    last_updated_at_ms,
                    last_updated_offset,
                    record.applied_offsets,
                    record.redirect_dedup,
                ),
                _ => {
                    counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
                    return None;
                }
            },
        };

    if dedup_is_replay(
        &applied,
        &redirect_dedup,
        origin,
        event.source_partition,
        event.source_offset,
    ) {
        counter!(STAGE1_REPLAY_SKIPPED, "variant" => StateVariant::PersonProperty.as_str())
            .increment(1);
        return None;
    }
    dedup_record(
        &mut applied,
        &mut redirect_dedup,
        origin,
        event.source_partition,
        event.source_offset,
    );

    // argMax tiebreaker: keep the most recent write.
    if (event_ms, event.source_offset) <= (prev_updated_at, prev_updated_offset) {
        counter!(STAGE1_ARGMAX_STALE).increment(1);
        let record = StatefulRecord {
            state: Stage1State::PersonProperty {
                matches: prev_matches,
                last_updated_at_ms: prev_updated_at,
                last_updated_offset: prev_updated_offset,
            },
            applied_offsets: applied,
            redirect_dedup,
        };
        return Some((record, None));
    }

    let record = StatefulRecord {
        state: Stage1State::PersonProperty {
            matches,
            last_updated_at_ms: event_ms,
            last_updated_offset: event.source_offset,
        },
        applied_offsets: applied,
        redirect_dedup,
    };
    let transition = if matches == prev_matches {
        None
    } else {
        Some(LeafTransition {
            team_id: TeamId(event.team_id),
            leaf_state_key: lsk,
            person_id,
            condition_hash,
            kind: if matches {
                TransitionKind::Entered
            } else {
                TransitionKind::Left
            },
        })
    };
    Some((record, transition))
}
