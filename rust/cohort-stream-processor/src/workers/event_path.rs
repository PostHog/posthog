//! The per-event read-modify-write (TDD §4.1, §4.1.1) — the Stage 1 "brain".
//!
//! [`process_event`] is the single hot-path function: given one re-keyed event and a team's frozen
//! filters, it evaluates the relevant cohort bytecode, folds the result into each affected leaf's
//! RocksDB state under one atomic [`WriteBatch`](crate::store::CohortStore::write_batch), and
//! returns the membership transitions that flipped. It is pure with respect to control flow — the
//! only side effects are the store write and metric emission — so the integration test drives it
//! directly with synthetic events (no Kafka).
//!
//! ## The order is the contract
//!
//! The step order below is the parity + replay-idempotence contract (preserved from the Node
//! consumer where it matters; see the module-level audit, TDD §2.4):
//!
//! 1. **Preflight** — skip the whole event (with a distinct reason) on a null/unparseable
//!    `person_id` or a team with no Stage 1 conditions.
//! 2. **Globals** — build the behavioral dict (only if behavioral conditions exist) and the person
//!    dict (only if person conditions exist *and* `person_properties` is a non-empty string — JS
//!    truthiness). Any malformed payload skips the whole event, behavioral path first.
//! 3. **Collect affected** — evaluate each unique conditionHash once. Behavioral records an apply
//!    only on match; person records on every evaluation (match and non-match).
//! 4. **Timestamp** — parse the event time once; if it's unparseable and there is work to do, skip
//!    the event (the value drives deadlines and the argMax tiebreaker).
//! 5. **Mutate + detect** — per affected leaf: replay-guard, variant-specific fold, transition iff
//!    the predicate flipped. A corrupt stored value or an unexpected variant skips that one leaf.
//! 6. **Commit** — one atomic `WriteBatch` per event; `cf_person_index` append only on first write
//!    for a `(person, leaf_state_key)`.
//! 7. **Surface** — transitions are returned only after the commit succeeds, so none is reported
//!    without durable state behind it.

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
use crate::partitions::offset_tracker::is_replay;
use crate::stage1::key::{LeafStateKey, Stage1Key};
use crate::stage1::predicate::predicate;
use crate::stage1::state::{Stage1State, StateVariant, StatefulRecord};
use crate::stage1::time::clickhouse_timestamp_to_millis;
use crate::stage1::transition::{LeafTransition, TransitionKind};
use crate::store::{CohortStore, IndexOp, PersonIndexKey, StoreError};

/// Why an event was skipped whole, before any state change. Doubles as the `reason` label on
/// [`STAGE1_EVENTS_SKIPPED`](crate::observability::metrics::STAGE1_EVENTS_SKIPPED), emitted by the
/// worker.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SkipReason {
    /// `person_id` was the empty string. Stage 1 keys by person, so there is nothing to update.
    NullPersonId,
    /// `person_id` was non-empty but not a UUID. Rust-only divergence from Node (which keys by the
    /// raw string): we store state under a [`Uuid`], so an unparseable id cannot be keyed.
    UnparseablePersonId,
    /// The team is in the catalog but has no Stage 1 conditions (e.g. only cohort references).
    /// Detected by the worker before [`process_event`] when the team is absent from the catalog
    /// entirely, and inside it when the team has only non-state-keyed leaves.
    NoTeamFilters,
    /// The team has no behavioral and no person-property conditions.
    NoConditions,
    /// A `properties` / `person_properties` payload was present but not valid JSON (the per-field
    /// counter is emitted by the globals builder; this is the event-level skip).
    GlobalsParseError,
    /// The event timestamp could not be parsed, so no deadline/argMax value could be computed.
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

/// The result of processing one event. Either it was skipped whole (`skipped = Some`, no
/// transitions) or it was processed (`skipped = None`, with zero or more transitions). The worker
/// turns this into metrics + downstream emission.
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

/// One leaf to fold this event into, resolved during the collect-affected step.
enum Apply {
    /// A behavioral leaf whose conditionHash matched. State becomes (or stays) `has_match = true`.
    Behavioral {
        lsk: LeafStateKey,
        condition_hash: [u8; 16],
    },
    /// A person-property leaf evaluated this event (recorded on match *and* non-match), carrying
    /// the evaluation result.
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

/// A staged `cf_stage1` write, accumulated before the single atomic commit.
struct PendingWrite {
    key: Stage1Key,
    bytes: Vec<u8>,
    /// `true` when the prior read was absent — the only time a `cf_person_index` append is staged.
    first_write: bool,
    variant: StateVariant,
}

/// Process one re-keyed event against a team's frozen filters. See the module docs for the
/// step-by-step contract. Returns the flipped transitions on success, a [`SkipReason`] when the
/// event is skipped whole, or a [`StoreError`] when a RocksDB read/commit fails (the worker logs
/// and continues — no commit state advances).
pub fn process_event(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    event: &CohortStreamEvent,
) -> Result<EventOutcome, StoreError> {
    // 1. Preflight — person id.
    if event.person_id.is_empty() {
        return Ok(EventOutcome::skipped(SkipReason::NullPersonId));
    }
    let Ok(person_id) = Uuid::parse_str(&event.person_id) else {
        return Ok(EventOutcome::skipped(SkipReason::UnparseablePersonId));
    };

    // 1. Preflight — the team must have at least one Stage 1 condition.
    let has_behavioral = !filters.behavioral_conditions.is_empty();
    let has_person = !filters.person_property_conditions.is_empty();
    if !has_behavioral && !has_person {
        return Ok(EventOutcome::skipped(SkipReason::NoConditions));
    }

    // 2. Globals. Behavioral first; bail before the person path on any parse error so a malformed
    //    payload skips the whole event (Node catches the JSON.parse throw per-message).
    let behavioral_globals = if has_behavioral {
        match build_behavioral_globals(event) {
            Ok(globals) => Some(globals),
            Err(_) => return Ok(EventOutcome::skipped(SkipReason::GlobalsParseError)),
        }
    } else {
        None
    };
    // JS truthiness: an empty `person_properties` string is falsy, so the person path is inactive
    // (identical to a null payload) — we never parse `""`.
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

    // 3. Collect affected leaves, evaluating each unique conditionHash once.
    let applies = collect_applies(
        filters,
        behavioral_globals.as_ref(),
        person_globals.as_ref(),
    );
    if applies.is_empty() {
        return Ok(EventOutcome::processed(Vec::new()));
    }

    // 4. Event time, parsed once. Load-bearing for deadlines + argMax — an unparseable value with
    //    work to do skips the event.
    let Some(event_ms) = clickhouse_timestamp_to_millis(&event.timestamp) else {
        return Ok(EventOutcome::skipped(SkipReason::BadTimestamp));
    };

    // 5. Read-modify-detect per affected leaf. Postgres team ids are positive, so the `as u64`
    //    keeps the big-endian key-ordering invariant (store::keys docs the negative-id caveat).
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
            Apply::Behavioral { condition_hash, .. } => mutate_behavioral(
                filters,
                apply.lsk(),
                *condition_hash,
                person_id,
                event,
                event_ms,
                prev.as_ref(),
            ),
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
                prev.as_ref(),
            ),
        };

        let Some((record, transition)) = mutation else {
            continue; // replay / unexpected variant → skip this leaf (counter emitted inside)
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

    // 6. One atomic WriteBatch per event. The person-index append is staged only on first write.
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

    // 7. Surface transitions only now that the backing state is committed.
    Ok(EventOutcome::processed(transitions))
}

/// Evaluate each behavioral / person conditionHash once and gather the leaves to fold this event
/// into. Behavioral fans out to every `LeafStateKey` sharing the matched hash; person maps to the
/// single LSK equal to its hash.
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
                continue; // behavioral records only on match (the Node `if (matches)` guard)
            }
            let Some(lsks) = filters.by_condition_to_lsk.get(&hash) else {
                continue;
            };
            for &lsk in lsks {
                match filters.by_lsk.get(&lsk).map(|meta| meta.variant) {
                    Some(StateVariant::BehavioralSingle) => {
                        applies.push(Apply::Behavioral {
                            lsk,
                            condition_hash: hash,
                        });
                    }
                    // Belt-and-suspenders: a behavioral hash whose LSK resolved to a non-M1 variant
                    // (only possible once PR 2.1 lands with a stale catalog) is skipped, not panicked.
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

/// Fold a behavioral match into a leaf's state. Returns the new record + an optional `Entered`
/// transition, or [`None`] to skip the leaf (replay or unexpected stored variant). M1 never clears
/// `has_match`, so this never emits `Left`.
fn mutate_behavioral(
    filters: &TeamFilters,
    lsk: LeafStateKey,
    condition_hash: [u8; 16],
    person_id: Uuid,
    event: &CohortStreamEvent,
    event_ms: i64,
    prev: Option<&StatefulRecord>,
) -> Option<(StatefulRecord, Option<LeafTransition>)> {
    let (prev_last_event, last_partition, last_offset) = match prev {
        // Fresh baseline: sentinel offset below any real one, on this event's source partition, so
        // the first real event is never mistaken for a replay.
        None => (i64::MIN, event.source_partition, i64::MIN),
        Some(record) => match &record.state {
            Stage1State::BehavioralSingle {
                last_event_at_ms, ..
            } => (
                *last_event_at_ms,
                record.last_applied_partition,
                record.last_applied_offset,
            ),
            // The LSK pins the variant, so a stored non-behavioral value here is impossible; treat
            // a corrupt one defensively rather than panicking.
            _ => {
                counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
                return None;
            }
        },
    };

    if is_replay(
        last_partition,
        last_offset,
        event.source_partition,
        event.source_offset,
    ) {
        counter!(STAGE1_REPLAY_SKIPPED, "variant" => StateVariant::BehavioralSingle.as_str())
            .increment(1);
        return None;
    }

    let predicate_before = prev.is_some_and(|record| predicate(&record.state));
    let last_event_at_ms = prev_last_event.max(event_ms);
    let window = filters.by_lsk.get(&lsk).and_then(|meta| meta.window);
    // The deadline tracks the newest matching event; a late (out-of-order) event must not pull it
    // earlier than `last_event_at_ms + window`.
    let earliest_eviction_at_ms =
        window.map_or(i64::MAX, |w| w.earliest_eviction_at_ms(last_event_at_ms));

    let record = StatefulRecord {
        state: Stage1State::BehavioralSingle {
            has_match: true,
            last_event_at_ms,
            earliest_eviction_at_ms,
        },
        last_applied_partition: event.source_partition,
        last_applied_offset: event.source_offset,
    };
    // Lazily — an existing member (the hottest case) builds no transition.
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

/// Fold a person-property evaluation into a leaf's state. Two guards: replay on the source
/// coordinates, then the event-time argMax tiebreaker for out-of-order events. Returns the new
/// record + an optional flip transition, or [`None`] to skip (replay / unexpected variant).
fn mutate_person(
    lsk: LeafStateKey,
    condition_hash: [u8; 16],
    matches: bool,
    person_id: Uuid,
    event: &CohortStreamEvent,
    event_ms: i64,
    prev: Option<&StatefulRecord>,
) -> Option<(StatefulRecord, Option<LeafTransition>)> {
    let (prev_matches, prev_updated_at, prev_updated_offset, last_partition, last_offset) =
        match prev {
            None => (false, i64::MIN, i64::MIN, event.source_partition, i64::MIN),
            Some(record) => match &record.state {
                Stage1State::PersonProperty {
                    matches,
                    last_updated_at_ms,
                    last_updated_offset,
                } => (
                    *matches,
                    *last_updated_at_ms,
                    *last_updated_offset,
                    record.last_applied_partition,
                    record.last_applied_offset,
                ),
                _ => {
                    counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
                    return None;
                }
            },
        };

    // Guard (a): Kafka-replay idempotence on the source coordinates.
    if is_replay(
        last_partition,
        last_offset,
        event.source_partition,
        event.source_offset,
    ) {
        counter!(STAGE1_REPLAY_SKIPPED, "variant" => StateVariant::PersonProperty.as_str())
            .increment(1);
        return None;
    }

    // Guard (b): event-time argMax — an event no newer than the last write keeps the prior
    // `matches` but still advances the applied offset (so the same offset isn't reprocessed).
    if (event_ms, event.source_offset) <= (prev_updated_at, prev_updated_offset) {
        counter!(STAGE1_ARGMAX_STALE).increment(1);
        let record = StatefulRecord {
            state: Stage1State::PersonProperty {
                matches: prev_matches,
                last_updated_at_ms: prev_updated_at,
                last_updated_offset: prev_updated_offset,
            },
            last_applied_partition: event.source_partition,
            last_applied_offset: event.source_offset,
        };
        return Some((record, None));
    }

    let record = StatefulRecord {
        state: Stage1State::PersonProperty {
            matches,
            last_updated_at_ms: event_ms,
            last_updated_offset: event.source_offset,
        },
        last_applied_partition: event.source_partition,
        last_applied_offset: event.source_offset,
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
