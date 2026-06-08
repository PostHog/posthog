//! The per-event read-modify-write — the Stage 1 "brain".
//!
//! [`process_event`] folds one re-keyed event into each affected leaf's RocksDB state under one
//! atomic [`WriteBatch`](crate::store::CohortStore::write_batch) and returns the transitions that
//! flipped. Its step order is a parity + replay-idempotence contract preserved from the Node
//! consumer, and transitions are surfaced only after the commit succeeds.

use chrono_tz::Tz;
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
use crate::stage1::bucket_tz::{daily_bucket_len, day_idx_in_tz, start_of_day_ms_in_tz};
use crate::stage1::key::{LeafStateKey, Stage1Key};
use crate::stage1::predicate::{daily_predicate, predicate};
use crate::stage1::state::{AppliedOffsets, Stage1State, StateVariant, StatefulRecord};
use crate::stage1::time::clickhouse_timestamp_to_millis;
use crate::stage1::transition::{LeafTransition, TransitionKind};
use crate::store::{CohortStore, IndexOp, PersonIndexKey, StoreError};

/// Why an event was skipped whole. Doubles as the `reason` label on
/// [`STAGE1_EVENTS_SKIPPED`](crate::observability::metrics::STAGE1_EVENTS_SKIPPED).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SkipReason {
    NullPersonId,
    /// Non-empty but not a UUID. Rust-only divergence from Node (which keys by the raw string): we
    /// store state under a [`Uuid`], so an unparseable id cannot be keyed.
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
    pub skipped: Option<SkipReason>,
}

impl EventOutcome {
    fn processed(transitions: Vec<LeafTransition>) -> Self {
        Self {
            transitions,
            skipped: None,
        }
    }

    fn skipped(reason: SkipReason) -> Self {
        Self {
            transitions: Vec::new(),
            skipped: Some(reason),
        }
    }
}

/// One leaf to fold this event into.
enum Apply {
    /// A behavioral leaf whose conditionHash matched (recorded only on match).
    Behavioral {
        lsk: LeafStateKey,
        condition_hash: [u8; 16],
    },
    /// A person-property leaf evaluated this event (recorded on match *and* non-match).
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
    /// `true` when the prior read was absent — the only time a `cf_person_index` append is staged.
    first_write: bool,
    variant: StateVariant,
}

/// Process one re-keyed event against a team's frozen filters. Returns the flipped transitions on
/// success, a [`SkipReason`] when the event is skipped whole, or a [`StoreError`] when a RocksDB
/// read/commit fails (the worker logs and continues — no commit state advances).
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

    let has_behavioral = !filters.behavioral_conditions.is_empty();
    let has_person = !filters.person_property_conditions.is_empty();
    if !has_behavioral && !has_person {
        return Ok(EventOutcome::skipped(SkipReason::NoConditions));
    }

    // Behavioral first; a parse error bails before the person path so a malformed payload skips the
    // whole event (matching Node's per-message JSON.parse throw).
    let behavioral_globals = if has_behavioral {
        match build_behavioral_globals(event) {
            Ok(globals) => Some(globals),
            Err(_) => return Ok(EventOutcome::skipped(SkipReason::GlobalsParseError)),
        }
    } else {
        None
    };
    // JS truthiness: an empty `person_properties` string is falsy, so the person path is inactive.
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
        return Ok(EventOutcome::processed(Vec::new()));
    }

    // Parsed once; load-bearing for deadlines + argMax, so an unparseable value with work to do
    // skips the event.
    let Some(event_ms) = clickhouse_timestamp_to_millis(&event.timestamp) else {
        return Ok(EventOutcome::skipped(SkipReason::BadTimestamp));
    };

    // Postgres team ids are positive, so `as u64` keeps the big-endian key-ordering invariant
    // (store::keys docs the negative-id caveat).
    let team_id = event.team_id as u64;
    let mut transitions = Vec::new();
    let mut pending = Vec::new();

    for apply in &applies {
        let key = Stage1Key {
            partition_id,
            team_id,
            leaf_state_key: apply.lsk(),
            person_id,
        };

        // Backend error → propagate (whole event fails). Corrupt bytes → skip just this leaf.
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
            // Single-bit and daily-bucket leaves both arrive as `Apply::Behavioral`; the variant
            // picks the fold.
            Apply::Behavioral { condition_hash, .. } => {
                let variant = filters.by_lsk.get(&apply.lsk()).map(|meta| meta.variant);
                if variant == Some(StateVariant::BehavioralDailyBuckets) {
                    mutate_behavioral_daily(
                        filters,
                        apply.lsk(),
                        *condition_hash,
                        person_id,
                        event,
                        event_ms,
                        prev,
                    )
                } else {
                    mutate_behavioral(
                        filters,
                        apply.lsk(),
                        *condition_hash,
                        person_id,
                        event,
                        event_ms,
                        prev,
                    )
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
                event,
                event_ms,
                prev,
            ),
        };

        let Some((record, transition)) = mutation else {
            continue; // replay / unexpected variant — counter emitted inside the mutate fn
        };

        if let Some(transition) = transition {
            transitions.push(transition);
        }
        pending.push(PendingWrite {
            variant: record.state.variant(),
            bytes: record.encode(),
            key,
            first_write,
        });
    }

    // One atomic WriteBatch per event; the person-index append is staged only on first write.
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

        // Post-commit: the writes are durable, so account for them now.
        for write in &pending {
            counter!(STAGE1_STATE_WRITES, "variant" => write.variant.as_str()).increment(1);
            if write.first_write {
                counter!(STAGE1_PERSON_INDEX_APPENDS).increment(1);
            }
        }
    }

    // Surfaced only now that the backing state is committed.
    Ok(EventOutcome::processed(transitions))
}

/// Evaluate each conditionHash once and gather the leaves to fold this event into. Behavioral fans
/// out to every `LeafStateKey` sharing the matched hash; person maps to the single LSK for its hash.
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
                continue; // behavioral records only on match (Node's `if (matches)` guard)
            }
            let Some(lsks) = filters.by_condition_to_lsk.get(&hash) else {
                continue;
            };
            for &lsk in lsks {
                match filters.by_lsk.get(&lsk).map(|meta| meta.variant) {
                    Some(StateVariant::BehavioralSingle | StateVariant::BehavioralDailyBuckets) => {
                        applies.push(Apply::Behavioral {
                            lsk,
                            condition_hash: hash,
                        });
                    }
                    // A behavioral conditionHash resolving to a person LSK is only reachable with a
                    // stale catalog; skip defensively rather than panic.
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
            // Person records on every evaluation — match and non-match (consumer.ts:267).
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

/// Fold a behavioral match into a leaf's state. `has_match` is never cleared here, so this never
/// emits `Left`. [`None`] skips the leaf (replay or unexpected stored variant).
fn mutate_behavioral(
    filters: &TeamFilters,
    lsk: LeafStateKey,
    condition_hash: [u8; 16],
    person_id: Uuid,
    event: &CohortStreamEvent,
    event_ms: i64,
    prev: Option<StatefulRecord>,
) -> Option<(StatefulRecord, Option<LeafTransition>)> {
    // Taken by value so the prior offset map moves into the new record instead of cloning on this
    // per-event hot path. `predicate_before` is read off the prior state here, before the map is
    // moved out; `predicate` is a trivial field read, so computing it on the replay-skip path too
    // is free.
    let (prev_last_event, predicate_before, mut applied) = match prev {
        None => (i64::MIN, false, AppliedOffsets::default()),
        Some(record) => {
            // `BehavioralSingle` is op-less, so no `PredicateOp` is needed.
            let predicate_before = predicate(&record.state, None);
            match record.state {
                Stage1State::BehavioralSingle {
                    last_event_at_ms, ..
                } => (last_event_at_ms, predicate_before, record.applied_offsets),
                // The LSK pins the variant; a non-behavioral value here means corruption, skip it.
                _ => {
                    counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
                    return None;
                }
            }
        }
    };

    if applied.is_replay(event.source_partition, event.source_offset) {
        counter!(STAGE1_REPLAY_SKIPPED, "variant" => StateVariant::BehavioralSingle.as_str())
            .increment(1);
        return None;
    }
    applied.record(event.source_partition, event.source_offset);

    let last_event_at_ms = prev_last_event.max(event_ms);
    let window = filters.by_lsk.get(&lsk).and_then(|meta| meta.window);
    // Tracks the newest matching event; a late event must not pull the deadline earlier.
    let earliest_eviction_at_ms =
        window.map_or(i64::MAX, |w| w.earliest_eviction_at_ms(last_event_at_ms));

    let record = StatefulRecord {
        state: Stage1State::BehavioralSingle {
            has_match: true,
            last_event_at_ms,
            earliest_eviction_at_ms,
        },
        applied_offsets: applied,
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

/// Fold a `performed_event_multiple` match into a leaf's dense daily-bucket state. A window slide
/// that drains the contributing bucket(s) can drop the count below the threshold and emit `Left`.
///
/// The apply path reads **no wall clock**: the event's own calendar day positions it against the
/// stored window, and `window_start_day` only moves forward. [`None`] skips the leaf (replay, a meta
/// desync, or an unexpected stored variant).
fn mutate_behavioral_daily(
    filters: &TeamFilters,
    lsk: LeafStateKey,
    condition_hash: [u8; 16],
    person_id: Uuid,
    event: &CohortStreamEvent,
    event_ms: i64,
    prev: Option<StatefulRecord>,
) -> Option<(StatefulRecord, Option<LeafTransition>)> {
    // `window_days` and the count comparator live on the meta, and are `Some` for a daily leaf by
    // construction; a `None` is a catalog desync — skip rather than panic.
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
    let len = daily_bucket_len(window_days); // window_days + 1

    // Taken by value so the prior bucket array and offset map move into the new record instead of
    // cloning on this per-event hot path.
    let (prior_buckets, prior_window_start_day, prev_last_event, mut applied) = match prev {
        None => (None, 0_i32, i64::MIN, AppliedOffsets::default()),
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
            ),
            // The LSK pins the variant; a non-bucket value here means corruption, skip it.
            _ => {
                counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
                return None;
            }
        },
    };

    // Replay guard FIRST — the `buckets[i] += 1` fold is not idempotent, so a redelivered offset must
    // skip before it is folded.
    if applied.is_replay(event.source_partition, event.source_offset) {
        counter!(STAGE1_REPLAY_SKIPPED, "variant" => StateVariant::BehavioralDailyBuckets.as_str())
            .increment(1);
        return None;
    }
    applied.record(event.source_partition, event.source_offset);

    // A stored array whose length disagrees with the leaf's window is a format desync (the LSK pins
    // `window_days`, so it shouldn't happen); guard it so the fold can't index out of bounds.
    let mut buckets = match prior_buckets {
        Some(buckets) if buckets.len() == len => buckets,
        Some(_) => {
            counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
            return None;
        }
        None => Vec::new(),
    };

    // Membership before this fold; an absent/empty prior is `count == 0` ⇒ not a member.
    let predicate_before = daily_predicate(&buckets, op);

    let event_day = day_idx_in_tz(event_ms, tz);
    let window_days_idx = window_days as i32;
    let mut window_start_day = if buckets.is_empty() {
        // First event for this leaf: seed a zeroed window whose last bucket (the "now" day) is the
        // event's day, so the fold below lands it there.
        buckets = vec![0; len];
        event_day - window_days_idx
    } else {
        prior_window_start_day
    };

    let cur_now_day = window_start_day + window_days_idx; // = window_start_day + (len − 1)
    if event_day > cur_now_day {
        // AHEAD: the event is newer than the window's "now" day. Slide the dense array forward by
        // `shift` days, zero the vacated tail, then count the event in the new last bucket.
        let shift = (event_day - cur_now_day) as usize;
        if shift >= len {
            buckets.iter_mut().for_each(|count| *count = 0);
        } else {
            buckets.copy_within(shift.., 0);
            buckets[len - shift..]
                .iter_mut()
                .for_each(|count| *count = 0);
        }
        window_start_day += shift as i32;
        let last = len - 1;
        buckets[last] = buckets[last].saturating_add(1);
    } else if event_day < window_start_day {
        // BEHIND: the event predates the window's lower bound — the bucket that would hold it already
        // slid out, so it does not count. Its offset is recorded above, so a replay is still skipped.
    } else {
        // WITHIN: count the event in its day's bucket.
        let idx = (event_day - window_start_day) as usize;
        buckets[idx] = buckets[idx].saturating_add(1);
    }

    // Newest matching event; a late (BEHIND) event must not pull it earlier.
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
    };
    // A fold crossing the threshold gives `Entered`; a slide draining the buckets gives `Left`.
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

/// The day-boundary (epoch ms, team tz) at which the oldest non-zero bucket leaves the window — its
/// eviction deadline. A day-`d` bucket is in-window while `now_day ≤ d + window_days`, so it leaves
/// at the start of day `d + window_days + 1`. An all-zero array never evicts → [`i64::MAX`].
fn daily_eviction_deadline(
    buckets: &[u32],
    window_start_day: i32,
    window_days: u32,
    tz: Tz,
) -> i64 {
    match buckets.iter().position(|&count| count > 0) {
        Some(oldest) => {
            let oldest_day = window_start_day + oldest as i32;
            start_of_day_ms_in_tz(oldest_day + window_days as i32 + 1, tz)
        }
        None => i64::MAX,
    }
}

/// Fold a person-property evaluation into a leaf's state, guarding against Kafka replay and then
/// out-of-order events via the event-time argMax tiebreaker. [`None`] skips (replay / unexpected
/// variant).
fn mutate_person(
    lsk: LeafStateKey,
    condition_hash: [u8; 16],
    matches: bool,
    person_id: Uuid,
    event: &CohortStreamEvent,
    event_ms: i64,
    prev: Option<StatefulRecord>,
) -> Option<(StatefulRecord, Option<LeafTransition>)> {
    // Taken by value so the prior offset map moves into the new record instead of cloning on this
    // per-event hot path.
    let (prev_matches, prev_updated_at, prev_updated_offset, mut applied) = match prev {
        None => (false, i64::MIN, i64::MIN, AppliedOffsets::default()),
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
            ),
            _ => {
                counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
                return None;
            }
        },
    };

    if applied.is_replay(event.source_partition, event.source_offset) {
        counter!(STAGE1_REPLAY_SKIPPED, "variant" => StateVariant::PersonProperty.as_str())
            .increment(1);
        return None;
    }
    // Recorded before the argMax branch so a stale-but-not-replay event still advances the applied
    // offset on both paths. The argMax key's `source_offset` is a within-partition tiebreaker only
    // (cross-partition replays are already caught by `is_replay` above).
    applied.record(event.source_partition, event.source_offset);

    // Event-time argMax: an event no newer than the last write keeps the prior `matches` but still
    // advances the applied offset, so the same offset isn't reprocessed.
    if (event_ms, event.source_offset) <= (prev_updated_at, prev_updated_offset) {
        counter!(STAGE1_ARGMAX_STALE).increment(1);
        let record = StatefulRecord {
            state: Stage1State::PersonProperty {
                matches: prev_matches,
                last_updated_at_ms: prev_updated_at,
                last_updated_offset: prev_updated_offset,
            },
            applied_offsets: applied,
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
