//! The per-event read-modify-write — the Stage 1 "brain".
//!
//! [`process_event`] folds one re-keyed event into each affected leaf's RocksDB state under one
//! atomic [`WriteBatch`](crate::store::CohortStore::write_batch) and returns the transitions that
//! flipped. Transitions are surfaced only after the commit succeeds.

use std::collections::BTreeMap;
use std::sync::Arc;

use metrics::counter;
use uuid::Uuid;

use crate::consumers::events::CohortStreamEvent;
use crate::filters::reverse_index::TeamFilters;
use crate::filters::{Generation, TeamId};
use crate::hogvm::{build_behavioral_globals, build_person_property_globals, CohortEvaluator};
use crate::observability::metrics::{
    STAGE1_ARGMAX_STALE, STAGE1_CONDITIONS_EVALUATED, STAGE1_CONDITIONS_SKIPPED,
    STAGE1_PERSON_INDEX_APPENDS, STAGE1_REPLAY_SKIPPED, STAGE1_STATE_DECODE_ERROR,
    STAGE1_STATE_WRITES, STAGE1_UNSUPPORTED_VARIANT_SKIPPED,
};
use crate::stage1::bucket_tz::{
    daily_bucket_len, day_idx_in_tz, now_day_for_window, window_start_for_now,
};
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
use crate::workers::person_memo::{ConditionBitset, Lookup, PersonKey, PersonMemo, Receipt};

/// Whether to evaluate only the behavioral conditions matching the incoming event name. A behavioral
/// leaf's bytecode roots at `event == event_key`, so a name mismatch can never match: gating it out
/// drops no `Apply`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EventNameGating {
    /// Evaluate only the event's name bucket.
    Enabled,
    /// Evaluate every behavioral condition.
    Disabled,
}

impl EventNameGating {
    pub fn from_enabled(enabled: bool) -> Self {
        if enabled {
            Self::Enabled
        } else {
            Self::Disabled
        }
    }
}

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

/// Fold one event with the person memo disabled (full person sweep). The memoizing entry is
/// [`process_event_with_memo`].
pub fn process_event(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    event: &CohortStreamEvent,
) -> Result<EventOutcome, StoreError> {
    process_event_with_memo(
        partition_id,
        store,
        filters,
        Generation::INITIAL,
        event,
        &mut PersonMemo::disabled(),
        EventNameGating::Disabled,
    )
}

/// Fold one event, consulting the per-worker person memo. A hit answers the person conditions from
/// cache — no JSON parse, no HogVM eval — keyed on `generation` plus a fingerprint of the raw
/// `person_properties`.
pub fn process_event_with_memo(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    generation: Generation,
    event: &CohortStreamEvent,
    memo: &mut PersonMemo,
    event_name_gating: EventNameGating,
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

    // Build globals and resolve the person plan before any evaluation, so a malformed payload skips
    // the event before any condition runs. A memo hit resolves without parsing person globals.
    let behavioral_globals = if has_behavioral {
        match build_behavioral_globals(event) {
            Ok(globals) => Some(globals),
            Err(_) => return Ok(EventOutcome::skipped(SkipReason::GlobalsParseError)),
        }
    } else {
        None
    };
    let person = match resolve_person(filters, event, person_id, generation, memo) {
        Ok(person) => person,
        Err(skip) => return Ok(EventOutcome::skipped(skip)),
    };

    // One evaluator reused across the event's conditions: globals set once per kind, program per condition.
    let mut evaluator = CohortEvaluator::new();
    let mut applies: Vec<Apply> = Vec::new();
    if let Some(globals) = behavioral_globals {
        evaluator.set_globals(globals);
        collect_behavioral_applies(
            filters,
            &event.event,
            event_name_gating,
            &mut evaluator,
            &mut applies,
        );
    }
    collect_person_applies(filters, &mut evaluator, person, memo, &mut applies);

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

/// Returns `None` for permanent-membership states (`i64::MAX` sentinel), so only time-bounded
/// leaves get scheduled for sweep eviction.
pub(crate) fn schedule_deadline(state: &Stage1State) -> Option<i64> {
    state.eviction_deadline().filter(|&d| d != i64::MAX)
}

/// How the event's person conditions will be answered, resolved before any evaluation.
enum PersonResolution {
    /// No person conditions, or empty `person_properties`.
    Inactive,
    /// Memo hit: reuse the cached results (globals never parsed).
    Cached(ConditionBitset),
    /// Evaluate `globals`, then cache the results under `receipt`.
    Evaluate {
        globals: serde_json::Value,
        receipt: Receipt,
    },
}

/// The raw `person_properties` iff there is a person condition and the payload is non-empty.
fn active_person_props<'a>(filters: &TeamFilters, event: &'a CohortStreamEvent) -> Option<&'a str> {
    if filters.person_property_conditions.is_empty() {
        return None;
    }
    event
        .person_properties
        .as_deref()
        .filter(|raw| !raw.is_empty())
}

/// Decide how to answer the person conditions. The only error is a malformed-props parse failure on
/// the eval path, which the caller turns into a `GlobalsParseError` skip.
fn resolve_person(
    filters: &TeamFilters,
    event: &CohortStreamEvent,
    person_id: Uuid,
    generation: Generation,
    memo: &mut PersonMemo,
) -> Result<PersonResolution, SkipReason> {
    let Some(raw) = active_person_props(filters, event) else {
        return Ok(PersonResolution::Inactive);
    };
    let key = PersonKey {
        team: TeamId(event.team_id),
        person: person_id,
    };
    match memo.probe(key, generation, raw) {
        Lookup::Hit(results) => Ok(PersonResolution::Cached(results)),
        Lookup::Miss(receipt) => {
            let globals =
                build_person_property_globals(event).map_err(|_| SkipReason::GlobalsParseError)?;
            Ok(PersonResolution::Evaluate { globals, receipt })
        }
    }
}

/// Evaluate this event's behavioral conditions against the set globals, pushing an `Apply::Behavioral`
/// per matching leaf. Under [`EventNameGating::Enabled`] only the event's name bucket is evaluated.
fn collect_behavioral_applies(
    filters: &TeamFilters,
    event_name: &str,
    gating: EventNameGating,
    evaluator: &mut CohortEvaluator,
    applies: &mut Vec<Apply>,
) {
    match gating {
        EventNameGating::Disabled => {
            for &hash in &filters.behavioral_conditions {
                eval_behavioral_condition(filters, hash, evaluator, applies);
            }
        }
        EventNameGating::Enabled => {
            let matched = filters
                .behavioral_by_event_name
                .get(event_name)
                .map_or(&[][..], Vec::as_slice);
            let skipped = filters
                .behavioral_conditions
                .len()
                .saturating_sub(matched.len());
            if skipped > 0 {
                counter!(STAGE1_CONDITIONS_SKIPPED, "reason" => "event_name_gate")
                    .increment(skipped as u64);
            }
            for &hash in matched {
                eval_behavioral_condition(filters, hash, evaluator, applies);
            }
        }
    }
}

/// Evaluate one behavioral condition, pushing an `Apply::Behavioral` for each supported state-keyed
/// leaf on a match.
fn eval_behavioral_condition(
    filters: &TeamFilters,
    hash: [u8; 16],
    evaluator: &mut CohortEvaluator,
    applies: &mut Vec<Apply>,
) {
    let Some(bytecode) = filters.by_condition_to_bytecode.get(&hash) else {
        return;
    };
    counter!(STAGE1_CONDITIONS_EVALUATED, "kind" => "behavioral").increment(1);
    if !evaluator.evaluate(Arc::clone(bytecode)) {
        return;
    }
    let Some(lsks) = filters.by_condition_to_lsk.get(&hash) else {
        return;
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

/// Push person applies for a resolved plan. The cached-read and fresh-eval paths produce the
/// identical `Apply` multiset.
fn collect_person_applies(
    filters: &TeamFilters,
    evaluator: &mut CohortEvaluator,
    person: PersonResolution,
    memo: &mut PersonMemo,
    applies: &mut Vec<Apply>,
) {
    match person {
        PersonResolution::Inactive => {}
        PersonResolution::Cached(cached) => {
            read_person_conditions_cached(filters, &cached, applies);
        }
        PersonResolution::Evaluate { globals, receipt } => {
            evaluator.set_globals(globals);
            let results = eval_person_conditions(filters, evaluator, applies);
            memo.store(receipt, results);
        }
    }
}

/// Memo miss: evaluate the person conditions in stable order, recording results into a bitset for
/// the caller to cache.
fn eval_person_conditions(
    filters: &TeamFilters,
    evaluator: &mut CohortEvaluator,
    applies: &mut Vec<Apply>,
) -> ConditionBitset {
    let mut results = ConditionBitset::zeros(filters.person_conditions_ordered.len());
    for (idx, &hash) in filters.person_conditions_ordered.iter().enumerate() {
        let Some(bytecode) = filters.by_condition_to_bytecode.get(&hash) else {
            continue;
        };
        counter!(STAGE1_CONDITIONS_EVALUATED, "kind" => "person_property").increment(1);
        let matches = evaluator.evaluate(Arc::clone(bytecode));
        if matches {
            results.set(idx);
        }
        push_person_apply(filters, hash, matches, applies);
    }
    results
}

/// Memo hit: push applies from the cached bits. The bytecode-presence skip mirrors the eval path so
/// the `Apply` multiset matches a miss.
fn read_person_conditions_cached(
    filters: &TeamFilters,
    cached: &ConditionBitset,
    applies: &mut Vec<Apply>,
) {
    for (idx, &hash) in filters.person_conditions_ordered.iter().enumerate() {
        if !filters.by_condition_to_bytecode.contains_key(&hash) {
            continue;
        }
        counter!(STAGE1_CONDITIONS_SKIPPED, "reason" => "person_memo_hit").increment(1);
        push_person_apply(filters, hash, cached.get(idx), applies);
    }
}

/// Push one person condition's `Apply` behind the catalog variant guard. Shared by all three person
/// paths so the guard is identical across them.
fn push_person_apply(
    filters: &TeamFilters,
    hash: [u8; 16],
    matches: bool,
    applies: &mut Vec<Apply>,
) {
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
            counter!(STAGE1_UNSUPPORTED_VARIANT_SKIPPED, "variant" => other.as_str()).increment(1);
        }
        None => {}
    }
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

    // Explicit range: day-granularity, inclusive, matching `date >= toDate(from) AND date <= toDate(to)`.
    // The bound is a tz-naive calendar day, compared directly to `day_idx_in_tz(event_ms, tz)` —
    // never re-projected through a timezone (which would shift it one day for UTC-offset teams).
    // Out-of-range events are dropped completely: no dedup record, no state, no transition.
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
    let mut window_start_day = if buckets.is_empty() {
        buckets = vec![0; len];
        window_start_for_now(event_day, window_days)
    } else {
        prior_window_start_day
    };

    let cur_now_day = now_day_for_window(window_start_day, window_days);
    if event_day > cur_now_day {
        slide_window_forward(&mut buckets, &mut window_start_day, window_days, event_day);
        let last = len - 1;
        buckets[last] = buckets[last].saturating_add(1);
    } else if event_day < window_start_day {
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
    let mut window_start_day = if first_write {
        window_start_for_now(event_day, window_days)
    } else {
        prior_window_start_day
    };

    let cur_now_day = now_day_for_window(window_start_day, window_days);
    if event_day > cur_now_day {
        compressed_history::slide_window_forward(
            &mut entries,
            &mut window_start_day,
            window_days,
            event_day,
        );
        compressed_history::insert_event(&mut entries, event_day);
    } else if event_day < window_start_day {
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
