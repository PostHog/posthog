//! The per-event read-modify-write — the Stage 1 "brain".
//!
//! [`process_event`] folds one re-keyed event into each affected leaf's RocksDB state under one
//! atomic [`WriteBatch`](crate::store::CohortStore::write_batch) and returns the transitions that
//! flipped. Transitions are surfaced only after the commit succeeds.
//!
//! The behavioral side stages a per-leaf `cf_behavioral` row per matching condition; the person side
//! collapses all of a person's person-property leaf state into one durable [`PersonRecord`] in
//! `cf_person_records`, updated per the freshness decision table in [`crate::stage1::person_record`].

// The sync `process_event`/`process_event_gated` compositions are the public test surface and run in
// blocking contexts, so their direct `CohortStore` I/O is sanctioned.
#![allow(clippy::disallowed_methods)]

use std::collections::BTreeMap;
use std::sync::Arc;

use metrics::{counter, histogram};
use uuid::Uuid;

use crate::consumers::events::CohortStreamEvent;
use crate::filters::reverse_index::TeamFilters;
use crate::filters::TeamId;
use crate::hogvm::{build_behavioral_globals, build_person_property_globals, CohortEvaluator};
use crate::observability::metrics::{
    STAGE1_BEHAVIORAL_APPLIES, STAGE1_CONDITIONS_EVALUATED, STAGE1_CONDITIONS_SKIPPED,
    STAGE1_PERSON_RECORD_SIZE_BYTES, STAGE1_PERSON_RECORD_TOTAL, STAGE1_REPLAY_SKIPPED,
    STAGE1_SNAPSHOT_KEYS, STAGE1_STATE_DECODE_ERROR, STAGE1_STATE_WRITES,
    STAGE1_UNSUPPORTED_VARIANT_SKIPPED,
};
use crate::stage1::bucket_tz::{
    daily_bucket_len, day_idx_in_tz, now_day_for_window, window_start_for_now,
};
use crate::stage1::compressed_history;
use crate::stage1::daily::{daily_eviction_deadline, slide_window_forward};
use crate::stage1::key::LeafStateKey;
use crate::stage1::person_record::{
    apply_eval, apply_skip_eval, apply_stale, decide, CatalogFingerprint, Decision, DedupCoords,
    MatchedSet, PersonRecord, PriorRecord, PropsFingerprint, Stamp,
};
use crate::stage1::pick_state::EvictionWindow;
use crate::stage1::predicate::{compressed_predicate, daily_predicate, predicate};
use crate::stage1::state::{
    dedup_is_replay, dedup_record, AppliedOffsets, Stage1State, StateVariant, StatefulRecord,
};
use crate::stage1::time::clickhouse_timestamp_to_millis;
use crate::stage1::transition::{LeafTransition, TransitionKind};
use crate::store::{
    Behavioral, BehavioralKey, CohortStore, EventSnapshotRaw, PersonPrefix, PersonRecords,
    StagedBatch, StoreError, StoreHandle,
};

/// Whether to evaluate only the behavioral conditions matching the incoming event name. A behavioral
/// leaf's bytecode roots at `event == event_key`, so a name mismatch can never match: gating it out
/// drops no `BehavioralApply`.
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
    pub schedules: Vec<(BehavioralKey, i64)>,
    /// This event's parsed timestamp (epoch ms). `0` on skip/no-applies paths.
    pub event_ms: i64,
    pub skipped: Option<SkipReason>,
}

impl EventOutcome {
    fn processed(
        transitions: Vec<LeafTransition>,
        schedules: Vec<(BehavioralKey, i64)>,
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

/// One behavioral leaf that matched this event: recorded only on a match, so a behavioral row is
/// staged for it.
struct BehavioralApply {
    lsk: LeafStateKey,
    condition_hash: [u8; 16],
}

/// How the person side of an event is handled, resolved once before the read.
enum PersonPlan {
    /// No person conditions, or empty `person_properties`: the record is neither read nor written.
    Inactive,
    /// A person condition exists and the payload is non-empty. The record is read and the freshness
    /// decision table runs; `props_fp`/`catalog_fp` are the fingerprints the table compares against
    /// the stored record.
    Active {
        props_fp: PropsFingerprint,
        catalog_fp: CatalogFingerprint,
    },
}

impl PersonPlan {
    fn is_active(&self) -> bool {
        matches!(self, Self::Active { .. })
    }
}

struct PendingWrite {
    key: BehavioralKey,
    bytes: Vec<u8>,
    variant: StateVariant,
}

/// What [`plan_event`] resolved for one event, up to (but not including) the pre-event read.
pub(crate) enum EventPlan {
    /// The event was skipped before any leaf evaluated (`skipped` reason).
    Skip(SkipReason),
    /// Nothing to read or write: no behavioral leaf matched and the person side is inactive.
    NoApplies,
    /// Work to do; read the snapshot and hand the result to [`fold_event`].
    Read(ReadPlan),
}

/// The data [`fold_event`] needs from [`plan_event`], carried by [`EventPlan::Read`]. The behavioral
/// keys are derived from `prefix` in `behavioral` order so the fold's zip over the read result stays
/// aligned; the record key is the person prefix (read iff the person side is active).
pub(crate) struct ReadPlan {
    prefix: PersonPrefix,
    behavioral: Vec<BehavioralApply>,
    person: PersonPlan,
    event_ms: i64,
    origin: Option<Uuid>,
}

impl ReadPlan {
    /// The behavioral keys to read, in `behavioral` order.
    fn behavioral_keys(&self) -> Vec<BehavioralKey> {
        self.behavioral
            .iter()
            .map(|apply| self.prefix.behavioral_key(apply.lsk))
            .collect()
    }
}

/// The metric emissions a successful fold implies, captured so the compositions can defer them until
/// after the commit succeeds. A fold that stages nothing yields empty stats.
pub(crate) struct WriteStats {
    /// Per-`StateVariant` `STAGE1_STATE_WRITES` counts, in first-seen order.
    variant_writes: Vec<(StateVariant, u64)>,
    /// Encoded person-record size to record on [`STAGE1_PERSON_RECORD_SIZE_BYTES`], when a record was
    /// staged.
    record_size: Option<usize>,
    /// The person side's decision outcome for [`STAGE1_PERSON_RECORD_TOTAL`], `None` when the person
    /// side was inactive. Deferred with the write metrics so a failed commit's redelivery cannot
    /// double-count; a write-free outcome (replay) still counts, since emission is gated on the commit
    /// step passing, not on there being writes.
    person_record_result: Option<&'static str>,
}

impl WriteStats {
    /// Emit the deferred write metrics. Called by the compositions only after the commit step
    /// succeeded (an event that staged nothing has no commit to fail), so a failed write records no
    /// phantom counts.
    pub(crate) fn emit(&self) {
        for &(variant, count) in &self.variant_writes {
            counter!(STAGE1_STATE_WRITES, "variant" => variant.as_str()).increment(count);
        }
        if let Some(size) = self.record_size {
            histogram!(STAGE1_PERSON_RECORD_SIZE_BYTES).record(size as f64);
        }
        if let Some(result) = self.person_record_result {
            counter!(STAGE1_PERSON_RECORD_TOTAL, "result" => result).increment(1);
        }
    }
}

/// The pure result of [`fold_event`]: either a whole-event skip (a person-props parse failure on the
/// evaluation arm) or the staged writes plus what the caller surfaces after commit. Infallible
/// w.r.t. the store — the fold touches no store.
pub(crate) enum FoldResult {
    Skip(SkipReason),
    Folded(FoldOutput),
}

/// The staged writes plus what the caller surfaces after commit.
pub(crate) struct FoldOutput {
    pub staged: StagedBatch,
    pub transitions: Vec<LeafTransition>,
    pub schedules: Vec<(BehavioralKey, i64)>,
    pub write_stats: WriteStats,
}

/// One behavioral apply's stored state as read by the event's single batched pre-event read.
enum PriorState {
    /// No row: this apply is the leaf's first write.
    Absent,
    /// The decoded pre-event record.
    Present(StatefulRecord),
    /// A row exists but does not decode; the apply is skipped.
    Corrupt,
}

impl PriorState {
    /// Decode one behavioral snapshot slot. The decode error is counted here — the only place a
    /// `Corrupt` can be born.
    fn decode(bytes: Option<Vec<u8>>) -> Self {
        match bytes {
            None => Self::Absent,
            Some(bytes) => match StatefulRecord::decode(&bytes) {
                Ok(record) => Self::Present(record),
                Err(_) => {
                    counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
                    Self::Corrupt
                }
            },
        }
    }
}

/// Fold one event with event-name gating disabled (full behavioral sweep). The gating-aware entry is
/// [`process_event_gated`].
pub fn process_event(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    event: &CohortStreamEvent,
) -> Result<EventOutcome, StoreError> {
    process_event_gated(
        partition_id,
        store,
        filters,
        event,
        EventNameGating::Disabled,
    )
}

/// Fold one event through the synchronous store, with explicit event-name gating. The public test
/// surface; the production async composition is [`process_event_offloaded`].
pub fn process_event_gated(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    event: &CohortStreamEvent,
    event_name_gating: EventNameGating,
) -> Result<EventOutcome, StoreError> {
    let read = match plan_event(partition_id, filters, event, event_name_gating) {
        EventPlan::Skip(reason) => return Ok(EventOutcome::skipped(reason)),
        EventPlan::NoApplies => return Ok(EventOutcome::processed(Vec::new(), Vec::new(), 0)),
        EventPlan::Read(read) => read,
    };

    let event_ms = read.event_ms;
    let behavioral_keys = read.behavioral_keys();
    let record_key = read.person.is_active().then(|| read.prefix.record_key());
    let snapshot = store.read_event_snapshot(&behavioral_keys, record_key.as_ref())?;
    record_snapshot_keys(&snapshot);

    let (staged, transitions, schedules, write_stats) =
        match fold_event(filters, read, snapshot, event) {
            FoldResult::Skip(reason) => return Ok(EventOutcome::skipped(reason)),
            FoldResult::Folded(FoldOutput {
                staged,
                transitions,
                schedules,
                write_stats,
            }) => (staged, transitions, schedules, write_stats),
        };

    // The batch spans exactly one event: the next event in the sub-batch must see this event's
    // committed writes (argMax tiebreaker, replay dedup, the person record's stamp/matched set).
    // Metrics emit only once the commit step passed.
    if !staged.is_empty() {
        store.apply(&staged)?;
    }
    write_stats.emit();

    Ok(EventOutcome::processed(transitions, schedules, event_ms))
}

/// The production composition of [`plan_event`] + [`fold_event`], reading and writing through the
/// async [`StoreHandle`] facade so the store I/O runs on the blocking pool.
///
/// Sequential awaits only: the batched read must observe the prior event's committed writes, so the
/// read and commit are never joined or reordered.
pub(crate) async fn process_event_offloaded(
    partition_id: u16,
    handle: &StoreHandle,
    filters: &TeamFilters,
    event: &CohortStreamEvent,
    event_name_gating: EventNameGating,
) -> Result<EventOutcome, StoreError> {
    let read = match plan_event(partition_id, filters, event, event_name_gating) {
        EventPlan::Skip(reason) => return Ok(EventOutcome::skipped(reason)),
        EventPlan::NoApplies => return Ok(EventOutcome::processed(Vec::new(), Vec::new(), 0)),
        EventPlan::Read(read) => read,
    };

    let event_ms = read.event_ms;
    let behavioral_keys = read.behavioral_keys();
    let record_key = read.person.is_active().then(|| read.prefix.record_key());
    let snapshot = handle
        .read_event_snapshot(behavioral_keys, record_key)
        .await?;
    record_snapshot_keys(&snapshot);

    let (staged, transitions, schedules, write_stats) =
        match fold_event(filters, read, snapshot, event) {
            FoldResult::Skip(reason) => return Ok(EventOutcome::skipped(reason)),
            FoldResult::Folded(FoldOutput {
                staged,
                transitions,
                schedules,
                write_stats,
            }) => (staged, transitions, schedules, write_stats),
        };

    // Commit before the caller processes the next event; metrics emit only once the commit step passed.
    if !staged.is_empty() {
        handle.commit(staged).await?;
    }
    write_stats.emit();

    Ok(EventOutcome::processed(transitions, schedules, event_ms))
}

/// Record the snapshot's total key count (behavioral rows + the 0-or-1 record slot) on
/// [`STAGE1_SNAPSHOT_KEYS`].
fn record_snapshot_keys(snapshot: &EventSnapshotRaw) {
    let keys = snapshot.behavioral.len() + usize::from(snapshot.record.is_some());
    histogram!(STAGE1_SNAPSHOT_KEYS).record(keys as f64);
}

/// Resolve everything up to the pre-event read: gating, behavioral evaluation and applies, and the
/// person plan (fingerprints only — the person record read and evaluation happen in the fold).
pub(crate) fn plan_event(
    partition_id: u16,
    filters: &TeamFilters,
    event: &CohortStreamEvent,
    event_name_gating: EventNameGating,
) -> EventPlan {
    if event.person_id.is_empty() {
        return EventPlan::Skip(SkipReason::NullPersonId);
    }
    let Ok(person_id) = Uuid::parse_str(&event.person_id) else {
        return EventPlan::Skip(SkipReason::UnparseablePersonId);
    };

    let origin: Option<Uuid> = event
        .redirected_from
        .as_deref()
        .and_then(|raw| Uuid::parse_str(raw).ok());

    let has_behavioral = !filters.behavioral_conditions.is_empty();
    let has_person = !filters.person_property_conditions.is_empty();
    if !has_behavioral && !has_person {
        return EventPlan::Skip(SkipReason::NoConditions);
    }

    // Build behavioral globals before any evaluation, so a malformed payload skips the event before
    // any condition runs. The person side parses its own globals only on the evaluation arm, in the fold.
    let behavioral_globals = if has_behavioral {
        match build_behavioral_globals(event) {
            Ok(globals) => Some(globals),
            Err(_) => return EventPlan::Skip(SkipReason::GlobalsParseError),
        }
    } else {
        None
    };

    let mut evaluator = CohortEvaluator::new();
    let mut behavioral: Vec<BehavioralApply> = Vec::new();
    if let Some(globals) = behavioral_globals {
        evaluator.set_globals(globals);
        collect_behavioral_applies(
            filters,
            &event.event,
            event_name_gating,
            &mut evaluator,
            &mut behavioral,
        );
    }

    // Fingerprints are computed here; the record read and evaluation happen in the fold.
    let person = match active_person_props(filters, event) {
        Some(raw) => PersonPlan::Active {
            props_fp: PropsFingerprint::of(raw),
            catalog_fp: filters.catalog_fingerprint,
        },
        None => PersonPlan::Inactive,
    };

    if behavioral.is_empty() && !person.is_active() {
        return EventPlan::NoApplies;
    }

    let Some(event_ms) = clickhouse_timestamp_to_millis(&event.timestamp) else {
        return EventPlan::Skip(SkipReason::BadTimestamp);
    };

    let prefix = PersonPrefix::new(partition_id, event.team_id as u64, person_id);
    EventPlan::Read(ReadPlan {
        prefix,
        behavioral,
        person,
        event_ms,
        origin,
    })
}

/// Fold the pre-event `snapshot` into the behavioral rows and the person record, staging the writes
/// into a [`StagedBatch`] for the caller to commit. Pure w.r.t. the store. Returns
/// [`FoldResult::Skip`] on a person-props parse failure.
pub(crate) fn fold_event(
    filters: &TeamFilters,
    read: ReadPlan,
    snapshot: EventSnapshotRaw,
    event: &CohortStreamEvent,
) -> FoldResult {
    let ReadPlan {
        prefix,
        behavioral,
        person,
        event_ms,
        origin,
    } = read;
    let person_id = prefix.person_id;
    let origin_ref = origin.as_ref();
    let EventSnapshotRaw {
        behavioral: behavioral_values,
        record: record_slot,
    } = snapshot;

    // Person side first: an evaluation-arm parse failure skips the whole event, so nothing (behavioral
    // included) may be staged before the person decision succeeds.
    let (record_put, mut transitions, record_result) = match fold_person(
        filters,
        &prefix,
        &person,
        record_slot,
        event,
        event_ms,
        origin_ref,
    ) {
        PersonFoldResult::Skip(reason) => return FoldResult::Skip(reason),
        PersonFoldResult::Folded {
            record_put,
            transitions,
            record_result,
        } => (record_put, transitions, record_result),
    };

    let behavioral_keys: Vec<BehavioralKey> = behavioral
        .iter()
        .map(|apply| prefix.behavioral_key(apply.lsk))
        .collect();
    histogram!(STAGE1_BEHAVIORAL_APPLIES).record(behavioral.len() as f64);

    let mut schedules: Vec<(BehavioralKey, i64)> = Vec::new();
    let mut pending: Vec<PendingWrite> = Vec::new();
    fold_behavioral(
        filters,
        &behavioral,
        &behavioral_keys,
        behavioral_values,
        person_id,
        origin_ref,
        event,
        event_ms,
        &mut transitions,
        &mut schedules,
        &mut pending,
    );

    let mut staged = StagedBatch::default();
    let mut write_stats = WriteStats {
        variant_writes: Vec::new(),
        record_size: None,
        person_record_result: record_result,
    };
    for write in &pending {
        staged.put::<Behavioral>(&write.key, &write.bytes);
        record_variant_write(&mut write_stats.variant_writes, write.variant);
    }
    if let Some(bytes) = record_put {
        write_stats.record_size = Some(bytes.len());
        staged.put::<PersonRecords>(&prefix.record_key(), &bytes);
    }

    FoldResult::Folded(FoldOutput {
        staged,
        transitions,
        schedules,
        write_stats,
    })
}

/// Fold each behavioral apply via the `mutate_behavioral*` variants: a match stages an advanced
/// `cf_behavioral` row, may schedule a sweep deadline, and may emit a transition.
#[allow(clippy::too_many_arguments)]
fn fold_behavioral(
    filters: &TeamFilters,
    behavioral: &[BehavioralApply],
    behavioral_keys: &[BehavioralKey],
    behavioral_values: Vec<Option<Vec<u8>>>,
    person_id: Uuid,
    origin: Option<&Uuid>,
    event: &CohortStreamEvent,
    event_ms: i64,
    transitions: &mut Vec<LeafTransition>,
    schedules: &mut Vec<(BehavioralKey, i64)>,
    pending: &mut Vec<PendingWrite>,
) {
    // Alignment-safe zip: the snapshot preserves the request order, `None` for absent keys.
    for ((apply, &key), bytes) in behavioral
        .iter()
        .zip(behavioral_keys)
        .zip(behavioral_values)
    {
        let prev = match PriorState::decode(bytes) {
            PriorState::Absent => None,
            PriorState::Present(record) => Some(record),
            PriorState::Corrupt => continue,
        };

        let mutation = match filters.by_lsk.get(&apply.lsk).map(|meta| meta.variant) {
            Some(StateVariant::BehavioralDailyBuckets) => mutate_behavioral_daily(
                filters,
                apply.lsk,
                apply.condition_hash,
                person_id,
                origin,
                event,
                event_ms,
                prev,
            ),
            Some(StateVariant::BehavioralCompressedHistory) => mutate_behavioral_compressed(
                filters,
                apply.lsk,
                apply.condition_hash,
                person_id,
                origin,
                event,
                event_ms,
                prev,
            ),
            _ => mutate_behavioral(
                filters,
                apply.lsk,
                apply.condition_hash,
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
        });
    }
}

/// The result of the person side of a fold: either a whole-event skip (an evaluation-arm parse
/// failure) or the record put to stage (if any) plus the person transitions.
enum PersonFoldResult {
    Skip(SkipReason),
    Folded {
        record_put: Option<Vec<u8>>,
        transitions: Vec<LeafTransition>,
        /// The decision outcome for [`STAGE1_PERSON_RECORD_TOTAL`]; `None` when the person side was
        /// inactive. Deferred to post-commit via [`WriteStats`] so a failed commit's redelivery
        /// cannot double-count.
        record_result: Option<&'static str>,
    },
}

/// Run the freshness decision table for the person side against the stored record.
///
/// `Inactive` touches nothing. Otherwise the prior record is decoded (its classification — present,
/// absent, corrupt — feeds the metric), [`decide`] classifies the event, and:
///
/// - `Replay`: nothing staged, no transitions.
/// - `Stale`: the record advances its dedup + `last_seen` only; no HogVM, no transitions.
/// - `SkipEval`: the record adopts the event stamp; no HogVM, no transitions.
/// - `Eval`: parse the person globals (a failure skips the whole event), evaluate the effective
///   person conditions, and diff the resulting TRUE set against the record's matched set.
#[allow(clippy::too_many_arguments)]
fn fold_person(
    filters: &TeamFilters,
    prefix: &PersonPrefix,
    person: &PersonPlan,
    record_slot: Option<Option<Vec<u8>>>,
    event: &CohortStreamEvent,
    event_ms: i64,
    origin: Option<&Uuid>,
) -> PersonFoldResult {
    let PersonPlan::Active {
        props_fp,
        catalog_fp,
    } = person
    else {
        return PersonFoldResult::Folded {
            record_put: None,
            transitions: Vec::new(),
            record_result: None,
        };
    };

    // The record slot is always requested for an active person, so the outer `Option` is `Some`.
    let record_bytes = record_slot.flatten();
    let prior = PriorRecord::decode(record_bytes.as_deref());
    let baseline = PersonRecord::absent();
    let event_stamp = Stamp::new(event_ms, event.source_offset);
    let dedup = DedupCoords::new(origin.copied(), event.source_partition, event.source_offset);

    // Absent/corrupt priors fold from an absent baseline; a present prior folds from itself.
    let from = match &prior {
        PriorRecord::Present(record) => record,
        PriorRecord::Absent | PriorRecord::Corrupt => &baseline,
    };

    match decide(&prior, event_stamp, dedup, *props_fp, *catalog_fp) {
        Decision::Replay => PersonFoldResult::Folded {
            record_put: None,
            transitions: Vec::new(),
            record_result: Some("replay"),
        },
        Decision::Stale => {
            let record = apply_stale(from, event_stamp, dedup);
            PersonFoldResult::Folded {
                record_put: Some(record.encode()),
                transitions: Vec::new(),
                record_result: Some("argmax_stale"),
            }
        }
        Decision::SkipEval => {
            let record = apply_skip_eval(from, event_stamp, dedup);
            PersonFoldResult::Folded {
                record_put: Some(record.encode()),
                transitions: Vec::new(),
                record_result: Some("fresh"),
            }
        }
        Decision::Eval { freshness } => {
            // A globals parse failure skips the whole event. The effective condition subset and the
            // catalog slice passed to `diff`/`apply_eval` are the same filtered set, so a
            // defensively-skipped hash in the stored set never emits a spurious `Left`.
            let globals = match build_person_property_globals(event) {
                Ok(globals) => globals,
                Err(_) => return PersonFoldResult::Skip(SkipReason::GlobalsParseError),
            };
            let mut evaluator = CohortEvaluator::new();
            evaluator.set_globals(globals);
            let (true_set, effective_catalog) = eval_person_conditions(filters, &mut evaluator);

            let (record, raw_transitions) = apply_eval(
                true_set,
                &effective_catalog,
                from,
                event_stamp,
                dedup,
                *props_fp,
                *catalog_fp,
            );
            // absent/corrupt are labelled from the prior classification (an eval from nothing), not
            // from the freshness axis (which reports StaleBoth for both).
            let record_result = match &prior {
                PriorRecord::Absent => "absent",
                PriorRecord::Corrupt => "corrupt",
                PriorRecord::Present(_) => freshness.as_str(),
            };

            let transitions = raw_transitions
                .into_iter()
                .map(|(hash, kind)| LeafTransition {
                    team_id: TeamId(event.team_id),
                    leaf_state_key: LeafStateKey::for_person_property(&hash),
                    person_id: prefix.person_id,
                    condition_hash: hash,
                    kind,
                })
                .collect();
            PersonFoldResult::Folded {
                record_put: Some(record.encode()),
                transitions,
                record_result: Some(record_result),
            }
        }
    }
}

/// Accumulate one write into its variant's running count, preserving first-seen order for the
/// deferred emission.
fn record_variant_write(counts: &mut Vec<(StateVariant, u64)>, variant: StateVariant) {
    if let Some((_, count)) = counts.iter_mut().find(|(v, _)| *v == variant) {
        *count += 1;
    } else {
        counts.push((variant, 1));
    }
}

/// Returns `None` for permanent-membership states (`i64::MAX` sentinel), so only time-bounded
/// leaves get scheduled for sweep eviction.
pub(crate) fn schedule_deadline(state: &Stage1State) -> Option<i64> {
    state.eviction_deadline().filter(|&d| d != i64::MAX)
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

/// Evaluate this event's behavioral conditions against the set globals, pushing a [`BehavioralApply`]
/// per matching leaf. Under [`EventNameGating::Enabled`] only the event's name bucket is evaluated.
fn collect_behavioral_applies(
    filters: &TeamFilters,
    event_name: &str,
    gating: EventNameGating,
    evaluator: &mut CohortEvaluator,
    applies: &mut Vec<BehavioralApply>,
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

/// Evaluate one behavioral condition, pushing a [`BehavioralApply`] for each supported state-keyed
/// leaf on a match.
fn eval_behavioral_condition(
    filters: &TeamFilters,
    hash: [u8; 16],
    evaluator: &mut CohortEvaluator,
    applies: &mut Vec<BehavioralApply>,
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
                applies.push(BehavioralApply {
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

/// Evaluate the person conditions in stable order, returning the TRUE set and the effective catalog
/// slice — the subset of `person_conditions_ordered` that has bytecode and a `PersonProperty`-variant
/// LSK meta. Both are the same filtered subset, so passing the effective catalog to
/// [`apply_eval`]/[`MatchedSet::diff`] means a defensively-skipped hash in the stored set is never
/// diffed and never emits a spurious `Left`.
fn eval_person_conditions(
    filters: &TeamFilters,
    evaluator: &mut CohortEvaluator,
) -> (MatchedSet, Vec<[u8; 16]>) {
    let mut true_hashes: Vec<[u8; 16]> = Vec::new();
    let mut effective_catalog: Vec<[u8; 16]> = Vec::new();
    for &hash in &filters.person_conditions_ordered {
        let Some(bytecode) = filters.by_condition_to_bytecode.get(&hash) else {
            continue;
        };
        // A hash whose LSK meta is missing or not a `PersonProperty` variant is skipped, so it is not
        // part of the effective catalog.
        let lsk = LeafStateKey::for_person_property(&hash);
        match filters.by_lsk.get(&lsk).map(|meta| meta.variant) {
            Some(StateVariant::PersonProperty) => {}
            Some(other) => {
                counter!(STAGE1_UNSUPPORTED_VARIANT_SKIPPED, "variant" => other.as_str())
                    .increment(1);
                continue;
            }
            None => continue,
        }
        counter!(STAGE1_CONDITIONS_EVALUATED, "kind" => "person_property").increment(1);
        // `person_conditions_ordered` is sorted, so pushing in iteration order keeps the effective
        // catalog sorted for the binary searches in `diff`/`apply_eval`.
        effective_catalog.push(hash);
        if evaluator.evaluate(Arc::clone(bytecode)) {
            true_hashes.push(hash);
        }
    }
    (MatchedSet::from_iter(true_hashes), effective_catalog)
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
