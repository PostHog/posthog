//! Domain layer: the person-property run — run kinds, UUID-range chunk tiling, pinned-payload
//! validation into [`PinnedPersonRun`], and the pure per-row evaluation fold. Depends on `chunk`,
//! `pinned`, `aggregate`, `ids`, and `cohort-core`.
//!
//! Range semantics (owned by this module): a person run's chunks tile the full UUID space in
//! **ClickHouse's UUID order** — boundaries arrive from a `GROUP BY id … ORDER BY id` stream and are
//! opaque here. Rust never sorts or compares person UUIDs beyond byte equality: a Rust-side
//! reordering would produce overlapping ranges in ClickHouse semantics, and an ordering check on
//! decode would strand claimed chunks `scanning`.

use std::collections::{BTreeMap, HashSet};
use std::sync::Arc;

use chrono::NaiveDate;
use cohort_core::filters::{CohortId, TeamFilters, TeamId};
use cohort_core::hogvm::{
    parse_person_scan_properties, person_scan_globals, CohortEvaluator, ConditionProgram,
};
use cohort_core::seed::PersonSeed;
use cohort_core::{LeafStateKey, StateVariant};
use serde::Deserialize;
use serde_json::Value;
use uuid::Uuid;

use super::aggregate::RecordStats;
use super::chunk::{ChunkLease, ChunkSpec};
use super::ids::{ClaimEpoch, ConditionHash, RunId, ScannedAtMs, UtcMillis};
use super::person_analysis::{ConditionVerdict, PersonAnalysisCensus, PersonConditionAnalyses};
use super::person_relevance::{ConditionIndex, Relevance, RelevanceOracle, TruthVector};
use super::pinned::{
    resolve_timezone, ParticipationSet, PinnedDropReason, PinnedError, PinnedParticipation,
    PinnedParticipationState, PinnedWarning,
};
use super::projection::ProjectedKeys;

/// The wire cap a single seed's `evaluated` list admits; validation enforces it run-wide.
pub use cohort_core::seed::MAX_PERSON_SEED_HASHES;

/// The fixed far-future `day` every person chunk is planned under. `claim_next` orders by
/// `(day, band)`, so behavioral chunks (readiness-gating, fence-sensitive) always claim first.
pub fn person_chunk_sentinel_day() -> NaiveDate {
    NaiveDate::from_ymd_opt(9999, 1, 1).expect("9999-01-01 is a valid date")
}

/// One person chunk's UUID range: `lo` inclusive (always present — the nil UUID is minimal under
/// any byte-permutation ordering, so band 0's `id >= nil` is a tautology), `hi` exclusive (`None`
/// only on the last band). Both endpoints are opaque ClickHouse-order boundaries.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PersonRange {
    lo: Uuid,
    hi: Option<Uuid>,
}

impl PersonRange {
    /// Rejects only a byte-equal `lo`/`hi` pair (a provably empty range); deliberately no ordering
    /// check — the ordering lives in ClickHouse.
    pub fn new(lo: Uuid, hi: Option<Uuid>) -> Result<Self, PersonRangeError> {
        if hi == Some(lo) {
            return Err(PersonRangeError(lo));
        }
        Ok(Self { lo, hi })
    }

    pub const fn lo(self) -> Uuid {
        self.lo
    }

    pub const fn hi(self) -> Option<Uuid> {
        self.hi
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[error("person range with lo == hi == {0} is empty")]
pub struct PersonRangeError(pub Uuid);

/// The chunk-count ceiling: `band` is a PostgreSQL `smallint`.
pub const MAX_PERSON_CHUNKS: usize = i16::MAX as usize;

/// Tile the full UUID space from an in-order boundary stream: positional and order-preserving —
/// adjacent byte-equal boundaries (and a leading nil) are dropped, nothing is sorted. Every person,
/// including one inserted after planning, falls into exactly one range.
pub fn tile_ranges(boundaries: &[Uuid]) -> Result<Vec<PersonRange>, PersonPlanError> {
    let mut ranges = Vec::with_capacity(boundaries.len() + 1);
    let mut lo = Uuid::nil();
    for boundary in boundaries {
        if *boundary == lo {
            continue;
        }
        ranges.push(PersonRange {
            lo,
            hi: Some(*boundary),
        });
        lo = *boundary;
    }
    ranges.push(PersonRange { lo, hi: None });
    if ranges.len() > MAX_PERSON_CHUNKS {
        return Err(PersonPlanError::TooManyChunks(ranges.len()));
    }
    Ok(ranges)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum PersonPlanError {
    #[error(
        "person planning produced {0} chunks; the band column holds at most {MAX_PERSON_CHUNKS}"
    )]
    TooManyChunks(usize),
}

/// A claimed chunk narrowed to the person path: the range is proven present and the claim stamp is
/// re-typed as the seed's LWW instant.
#[derive(Debug, Clone, Copy)]
pub struct PersonChunkSpec {
    pub lease: ChunkLease,
    pub team_id: TeamId,
    pub range: PersonRange,
    pub scanned_at: ScannedAtMs,
}

#[derive(Debug, thiserror::Error)]
pub enum PersonChunkSpecError {
    #[error(
        "chunk run/team ({chunk_run_id:?}, {chunk_team_id}) does not match pinned run/team ({pinned_run_id:?}, {pinned_team_id})"
    )]
    RunMismatch {
        chunk_run_id: RunId,
        chunk_team_id: i32,
        pinned_run_id: RunId,
        pinned_team_id: i32,
    },
    #[error("chunk {0:?} carries no person range; it does not belong to a person run")]
    MissingRange(RunId),
}

/// A person run's participation rows and pinned payload, assembled by the store for validation.
#[derive(Debug)]
pub struct PersonPinnedSnapshot {
    pub run_id: RunId,
    pub team_id: TeamId,
    pub timezone: String,
    pub person_scan_since: Option<UtcMillis>,
    pub pinned: Value,
    pub participations: Vec<PinnedParticipation>,
}

/// A person run proven scannable: `scan_since` present, at least one condition surviving.
///
/// The two analyses are built once here, from the participation set validation assembles and then
/// drops: [`PersonConditionAnalyses`] says what each condition needs from a row, and
/// [`RelevanceOracle`] says which leaf truths can move a participating cohort. Both are pure
/// functions of the pinned payload, so a run re-validated on another replica derives the same ones.
#[derive(Debug)]
pub struct PinnedPersonRun {
    pub run_id: RunId,
    pub team_id: TeamId,
    pub scan_since: UtcMillis,
    pub conditions: EvaluatedConditions,
    pub horizon_days: u32,
    analyses: PersonConditionAnalyses,
    relevance: RelevanceOracle,
}

/// Which scanned persons a chunk emits.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PersonEmissionPolicy {
    /// The healer cadence. It exists to retract stale state, so it has to see every scanned person:
    /// nothing is pruned and no scan filter is applied.
    EveryScannedPerson,
    /// Every other run: emit only a person whose leaf truths can move a participating cohort's
    /// verdict against an absent prior.
    RelevantToSomeCohort,
}

impl PersonEmissionPolicy {
    pub const fn from_emit_nonmatchers(emit_nonmatchers: bool) -> Self {
        if emit_nonmatchers {
            Self::EveryScannedPerson
        } else {
            Self::RelevantToSomeCohort
        }
    }

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::EveryScannedPerson => "every_scanned_person",
            Self::RelevantToSomeCohort => "relevant_to_some_cohort",
        }
    }
}

#[derive(Debug)]
pub struct ValidatedPinnedPersonRun {
    pub run: PinnedPersonRun,
    pub warnings: Vec<PinnedWarning>,
    /// Active participations left with no surviving condition, ascending — they withhold the
    /// planning proof exactly as behavioral uncovered cohorts do.
    pub uncovered_cohorts: Vec<CohortId>,
}

/// A person run's validation outcome. `Retired` mirrors the behavioral zero-condition retirement:
/// with every participation superseded, nothing expects coverage, so the run finishes as zero-work
/// instead of failing.
#[derive(Debug)]
pub enum PersonRunValidation {
    Seedable(ValidatedPinnedPersonRun),
    Retired { warnings: Vec<PinnedWarning> },
}

#[derive(Debug, Deserialize)]
struct PersonPinnedPayload {
    schema_version: u32,
    conditions: Vec<RawPersonPinnedCondition>,
    person_horizon_days: u32,
}

#[derive(Debug, Deserialize)]
struct RawPersonPinnedCondition {
    cohort_id: i32,
    condition_hash: String,
}

impl PinnedPersonRun {
    pub fn validate(snapshot: PersonPinnedSnapshot) -> Result<PersonRunValidation, PinnedError> {
        let payload: PersonPinnedPayload = serde_json::from_value(snapshot.pinned)?;
        if payload.schema_version != 1 {
            return Err(PinnedError::SchemaVersion(payload.schema_version));
        }
        let scan_since = snapshot
            .person_scan_since
            .ok_or(PinnedError::MissingPersonScanSince)?;
        let mut warnings = Vec::new();
        let tz = resolve_timezone(&snapshot.timezone, &mut warnings);
        let participation = ParticipationSet::build(snapshot.team_id, snapshot.participations, tz)?;

        let mut surviving: BTreeMap<ConditionHash, ConditionProgram> = BTreeMap::new();
        let mut covered: HashSet<CohortId> = HashSet::new();
        for raw in payload.conditions {
            let cohort_id = CohortId(raw.cohort_id);
            let Some(state) = participation.state(cohort_id) else {
                return Err(PinnedError::MissingParticipation(raw.cohort_id));
            };
            let hash = ConditionHash::parse(&raw.condition_hash).map_err(|source| {
                PinnedError::InvalidConditionHash {
                    value: raw.condition_hash.clone(),
                    source,
                }
            })?;
            if state == PinnedParticipationState::Superseded {
                warnings.push(PinnedWarning::ConditionSuperseded { cohort_id, hash });
                continue;
            }
            match classify_person_condition(hash, participation.filters()) {
                PersonSurvival::Survives(program) => {
                    surviving.entry(hash).or_insert(program);
                    covered.insert(cohort_id);
                }
                PersonSurvival::Dropped(reason) => {
                    warnings.push(PinnedWarning::ConditionDropped {
                        cohort_id,
                        hash,
                        reason,
                    });
                }
            }
        }
        let uncovered_cohorts = participation.uncovered_from(&covered);
        if surviving.is_empty() && uncovered_cohorts.is_empty() {
            // No active participation expects coverage (all superseded or none exist): retire.
            // Zero survivors with an active participation stays terminal below — that cohort's
            // pinned conditions dropped from the catalog, which is a genuine data problem.
            return Ok(PersonRunValidation::Retired { warnings });
        }
        let conditions = EvaluatedConditions::new(surviving)?;
        let analyses = PersonConditionAnalyses::build(snapshot.team_id, &conditions);
        let relevance = RelevanceOracle::build(participation.filters(), &conditions);

        Ok(PersonRunValidation::Seedable(ValidatedPinnedPersonRun {
            run: PinnedPersonRun {
                run_id: snapshot.run_id,
                team_id: snapshot.team_id,
                scan_since,
                conditions,
                horizon_days: payload.person_horizon_days,
                analyses,
                relevance,
            },
            warnings,
            uncovered_cohorts,
        }))
    }

    /// The top-level `properties` keys ClickHouse may drop a chunk's rows on, or `None` to scan the
    /// whole range.
    ///
    /// Three things have to hold together. The policy has to be the relevant-only one, because the
    /// healer must see every scanned person. Every condition has to be key-decidable, or a dropped
    /// row might have decided one the VM had to run. And the vacuous vector — the truths every
    /// dropped row carries — has to be irrelevant, because that is the verdict being discarded.
    pub fn scan_key_filter(&self, emission: PersonEmissionPolicy) -> Option<ProjectedKeys> {
        match emission {
            PersonEmissionPolicy::EveryScannedPerson => return None,
            PersonEmissionPolicy::RelevantToSomeCohort => {}
        }
        match self.relevance.judge(&self.analyses.vacuous_truths()?) {
            Relevance::CanChangeSomeCohort => None,
            Relevance::IrrelevantToEveryCohort => {
                self.analyses.keys_if_every_condition_is_key_decidable()
            }
        }
    }

    /// The verdict `index` reaches on `object` without the VM, or `None` when it needs one.
    fn shortcut(
        &self,
        index: ConditionIndex,
        object: Option<&serde_json::Map<String, Value>>,
    ) -> Option<ConditionVerdict> {
        self.analyses.shortcut(index, object)
    }

    /// How the run's conditions classified, for the per-run log line.
    pub fn analysis_census(&self) -> PersonAnalysisCensus {
        self.analyses.census()
    }

    /// How many participations the relevance oracle walks, or `None` when it proves nothing.
    pub fn composable_cohorts(&self) -> Option<usize> {
        self.relevance.composable_cohorts()
    }

    /// Narrow a claimed chunk to the person path, after proving it belongs to this run/team. This
    /// is the one deliberate `SChunkMs` → [`ScannedAtMs`] bridge: the claim stamp becomes the
    /// seed's LWW instant, and re-claims re-stamp so LWW converges to the fresher snapshot.
    pub fn chunk_spec(&self, spec: &ChunkSpec) -> Result<PersonChunkSpec, PersonChunkSpecError> {
        if self.run_id != spec.lease.run_id() || self.team_id != spec.team_id {
            return Err(PersonChunkSpecError::RunMismatch {
                chunk_run_id: spec.lease.run_id(),
                chunk_team_id: spec.team_id.0,
                pinned_run_id: self.run_id,
                pinned_team_id: self.team_id.0,
            });
        }
        let range = spec
            .person_range
            .ok_or(PersonChunkSpecError::MissingRange(spec.lease.run_id()))?;
        Ok(PersonChunkSpec {
            lease: spec.lease,
            team_id: spec.team_id,
            range,
            scanned_at: ScannedAtMs(spec.s_chunk.0),
        })
    }
}

/// Whether one pinned hash survives against the frozen catalog — the structural mirror of the
/// processor's `effective_hashes` projection.
enum PersonSurvival {
    Survives(ConditionProgram),
    Dropped(PinnedDropReason),
}

fn classify_person_condition(hash: ConditionHash, filters: &TeamFilters) -> PersonSurvival {
    let bytes = hash.as_bytes();
    if !filters.person_property_conditions.contains(&bytes) {
        return PersonSurvival::Dropped(PinnedDropReason::AbsentFromFrozenCatalog);
    }
    match filters
        .by_lsk
        .get(&LeafStateKey::for_person_property(&bytes))
        .map(|meta| meta.variant)
    {
        Some(StateVariant::PersonProperty) => {}
        Some(_) => return PersonSurvival::Dropped(PinnedDropReason::VariantMismatch),
        None => return PersonSurvival::Dropped(PinnedDropReason::AbsentFromFrozenCatalog),
    }
    match filters.by_condition_to_program.get(&bytes) {
        Some(program) => PersonSurvival::Survives(program.clone()),
        None => PersonSurvival::Dropped(PinnedDropReason::AbsentFromFrozenCatalog),
    }
}

/// The surviving person conditions: non-empty, sorted-distinct by hash, each with its frozen
/// program — so an empty `evaluated` or a hash/program mismatch is unrepresentable at eval time.
#[derive(Debug, Clone)]
pub struct EvaluatedConditions(Vec<(ConditionHash, ConditionProgram)>);

// Non-empty by construction, so an `is_empty` would be a method whose contract is "never call me".
#[allow(clippy::len_without_is_empty)]
impl EvaluatedConditions {
    fn new(surviving: BTreeMap<ConditionHash, ConditionProgram>) -> Result<Self, PinnedError> {
        if surviving.is_empty() {
            return Err(PinnedError::NoSurvivingPersonConditions);
        }
        if surviving.len() > MAX_PERSON_SEED_HASHES {
            return Err(PinnedError::PersonConditionsOverCap(surviving.len()));
        }
        Ok(Self(surviving.into_iter().collect()))
    }

    pub fn len(&self) -> usize {
        self.0.len()
    }

    pub fn iter(&self) -> impl Iterator<Item = &(ConditionHash, ConditionProgram)> {
        self.0.iter()
    }

    /// Each condition with its [`ConditionIndex`]. The conversion is total because
    /// [`EvaluatedConditions::new`] refuses a set larger than the wire cap the index restates.
    pub fn indexed(
        &self,
    ) -> impl Iterator<Item = (ConditionIndex, &ConditionHash, &ConditionProgram)> {
        self.0
            .iter()
            .enumerate()
            .map(|(position, (hash, program))| {
                let index = ConditionIndex::new(position)
                    .expect("EvaluatedConditions::new caps the set at MAX_PERSON_SEED_HASHES");
                (index, hash, program)
            })
    }
}

/// The mint constants a chunk's seeds share.
#[derive(Debug, Clone, Copy)]
pub struct PersonSeedContext {
    pub scanned_at: ScannedAtMs,
    pub run_id: RunId,
    pub claim_epoch: ClaimEpoch,
}

/// One scanned person's outcome.
#[derive(Debug, PartialEq, Eq)]
pub enum PersonRowOutcome {
    Seed(PersonSeed),
    /// Evaluated fully, nothing matched, and the policy is relevant-only.
    NonMatcher,
    /// Evaluated fully, and the truths reached cannot move any participating cohort's verdict
    /// against an absent prior — so the seed would produce a record write and a recompose that
    /// changes nothing.
    Irrelevant,
    Skipped(PersonRowSkip),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PersonRowSkip {
    InvalidPersonId,
    InvalidProperties,
    /// Every condition failed to evaluate; asserting FALSE for hashes the VM never answered would
    /// mint wrong `Left`s, so the row emits nothing.
    NothingEvaluated,
}

impl PersonRowSkip {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::InvalidPersonId => "invalid_person_id",
            Self::InvalidProperties => "invalid_properties",
            Self::NothingEvaluated => "nothing_evaluated",
        }
    }
}

/// The pure per-row fold: decide each surviving condition — from the run's cached vacuous verdict
/// where the blob's keys allow, from the VM otherwise — and mint at most one [`PersonSeed`].
/// Unit-testable without ClickHouse or Kafka.
pub struct PersonEvaluator {
    run: Arc<PinnedPersonRun>,
    evaluator: CohortEvaluator,
    emission: PersonEmissionPolicy,
    /// One slot per condition, refilled per row: `Some` where the blob's key set already decides the
    /// condition. A field rather than a local so the fold allocates nothing per person.
    shortcuts: Vec<Option<ConditionVerdict>>,
}

impl PersonEvaluator {
    pub fn new(run: &Arc<PinnedPersonRun>, emission: PersonEmissionPolicy) -> Self {
        Self {
            run: Arc::clone(run),
            evaluator: CohortEvaluator::new(),
            emission,
            shortcuts: Vec::with_capacity(run.conditions.len()),
        }
    }

    pub fn evaluate_row(
        &mut self,
        person_id: &str,
        properties: &str,
        ctx: &PersonSeedContext,
    ) -> (PersonRowOutcome, RecordStats) {
        let mut stats = RecordStats::default();
        let Ok(person_id) = Uuid::parse_str(person_id) else {
            return (
                PersonRowOutcome::Skipped(PersonRowSkip::InvalidPersonId),
                stats,
            );
        };
        let Ok(properties) = parse_person_scan_properties(properties) else {
            return (
                PersonRowOutcome::Skipped(PersonRowSkip::InvalidProperties),
                stats,
            );
        };

        let Self {
            run,
            evaluator,
            emission,
            shortcuts,
        } = self;

        // A non-object blob is not "an object missing keys": an array makes `GET_GLOBAL` coerce a
        // string key to a number and error, so those rows keep going through the VM.
        let object = properties.as_object();
        shortcuts.clear();
        shortcuts.extend(
            run.conditions
                .indexed()
                .map(|(index, _, _)| run.shortcut(index, object)),
        );
        if shortcuts.iter().any(Option::is_none) {
            evaluator.set_globals(person_scan_globals(run.team_id, person_id, properties));
        }

        let mut evaluated = Vec::with_capacity(run.conditions.len());
        let mut matched = Vec::new();
        let mut truths = TruthVector::ABSENT;
        for ((index, hash, program), shortcut) in run.conditions.indexed().zip(&*shortcuts) {
            let verdict = match shortcut {
                Some(cached) => {
                    stats.shortcut_evaluations += 1;
                    *cached
                }
                None => evaluator.evaluate_detailed(program).into(),
            };
            match verdict {
                ConditionVerdict::Matched(true) => {
                    evaluated.push(*hash);
                    matched.push(*hash);
                    truths.set(index);
                    stats.matched += 1;
                }
                ConditionVerdict::Matched(false) => {
                    evaluated.push(*hash);
                    stats.non_matched += 1;
                }
                // A hash the VM never answered is excluded from `evaluated`: its absence from
                // `matched` would otherwise assert FALSE and mint a wrong `Left`.
                ConditionVerdict::UnknownFunction => stats.unknown_functions += 1,
                ConditionVerdict::VmFailure(class) => stats
                    .vm_failures
                    .increment(class)
                    .expect("per-row VM failure counts are bounded by the condition cap"),
            }
        }
        if evaluated.is_empty() {
            return (
                PersonRowOutcome::Skipped(PersonRowSkip::NothingEvaluated),
                stats,
            );
        }
        match emission {
            PersonEmissionPolicy::EveryScannedPerson => {}
            PersonEmissionPolicy::RelevantToSomeCohort => {
                // A deliberate policy choice, not an optimization of the line below: it keeps
                // `seeder_person_nonmatchers_skipped_total` counting what it has always counted.
                // It is also *narrower* than the oracle — a collapsed oracle judges every vector
                // relevant, the absent one included — so the two branches cannot be merged.
                if matched.is_empty() {
                    return (PersonRowOutcome::NonMatcher, stats);
                }
                // Pruning models the consumer's recompose as a walk over `truths`, and that holds
                // only while the seed asserts every pinned leaf. A condition the VM never answered
                // is absent from `evaluated`, so the consumer keeps whatever bit it already stored
                // for that leaf (`apply_person_seed`'s `untouched`) and composes
                // `matched ∪ untouched`, which is not `truths`. Emit rather than judge a vector the
                // fold will not use.
                let asserts_every_leaf = evaluated.len() == run.conditions.len();
                if asserts_every_leaf
                    && run.relevance.judge(&truths) == Relevance::IrrelevantToEveryCohort
                {
                    return (PersonRowOutcome::Irrelevant, stats);
                }
            }
        }
        let seed = PersonSeed::new(
            run.team_id,
            person_id,
            evaluated,
            matched,
            ctx.scanned_at,
            ctx.run_id,
            ctx.claim_epoch,
        )
        .expect("sorted-distinct subset by construction with a positive claim stamp");
        (PersonRowOutcome::Seed(seed), stats)
    }
}

#[cfg(test)]
mod tests {
    use cohort_core::filters::LeafStateMeta;
    use cohort_core::hogvm::EvalOutcome;
    use proptest::prelude::*;
    use serde_json::json;

    use super::super::backoff::AttemptCount;
    use super::super::chunk::BandSpec;
    use super::super::ids::{ChunkId, SChunkMs};
    use super::*;

    fn hash(value: &str) -> ConditionHash {
        ConditionHash::parse(value).unwrap()
    }

    fn person_bytecode(key: &str, value: &str) -> Value {
        json!([
            "_H",
            1,
            32,
            value,
            32,
            key,
            32,
            "properties",
            32,
            "person",
            1,
            3,
            11
        ])
    }

    fn person_filter_leaves(leaves: &[(&str, &str, &str)]) -> Value {
        let values = leaves
            .iter()
            .map(|(hash, key, value)| {
                json!({
                    "type": "person",
                    "key": key,
                    "value": value,
                    "operator": "exact",
                    "conditionHash": hash,
                    "bytecode": person_bytecode(key, value),
                })
            })
            .collect::<Vec<_>>();
        json!({ "properties": { "type": "AND", "values": values } })
    }

    /// `email is_set OR email not_icontains '@posthog.com'`, with the bytecode the cohort compiler
    /// emits. The OR is what makes the vacuous vector matter: a person with no email is a member.
    fn vacuously_true_or_filter() -> Value {
        json!({ "properties": { "type": "OR", "values": [
            {
                "type": "person", "key": "email", "value": "is_set", "operator": "is_set",
                "conditionHash": HASH_A,
                "bytecode": ["_H", 1, 31, 32, "email", 32, "properties", 32, "person", 1, 3, 12],
            },
            {
                "type": "person", "key": "email", "value": "@posthog.com",
                "operator": "not_icontains", "conditionHash": HASH_B,
                "bytecode": [
                    "_H", 1, 32, "%@posthog.com%", 32, "email", 32, "properties", 32, "person", 1,
                    3, 2, "toString", 1, 20
                ],
            },
        ] } })
    }

    /// `AND(person A, person B, cohort ref 99)`. The reference makes the cohort
    /// `Excluded(HasCohortRef)` in the seeder, which freezes with cascade off — while the consumer
    /// runs with it on and composes the cohort. The oracle has to treat it as composable.
    fn and_with_a_cohort_reference() -> Value {
        json!({ "properties": { "type": "AND", "values": [
            {
                "type": "person", "key": "email", "value": "a@b.com", "operator": "exact",
                "conditionHash": HASH_A, "bytecode": person_bytecode("email", "a@b.com"),
            },
            {
                "type": "person", "key": "plan", "value": "paid", "operator": "exact",
                "conditionHash": HASH_B, "bytecode": person_bytecode("plan", "paid"),
            },
            { "type": "cohort", "value": 99 },
        ] } })
    }

    /// A single negated person leaf at the root: `TopLevelNegation`, which both services decide the
    /// same way and neither composes.
    fn negated_root_filter(hash: &str) -> Value {
        let mut leaf = json!({
            "type": "person", "key": "email", "value": "a@b.com", "operator": "exact",
            "conditionHash": hash, "bytecode": person_bytecode("email", "a@b.com"),
        });
        leaf["negation"] = json!(true);
        json!({ "properties": { "type": "AND", "values": [leaf] } })
    }

    /// A condition the analyzer can narrow to `person.properties.email` but the VM cannot answer,
    /// because no native is registered under that name.
    fn unknown_native_filter() -> Value {
        json!({ "properties": { "type": "AND", "values": [
            {
                "type": "person", "key": "email", "value": "a@b.com", "operator": "exact",
                "conditionHash": HASH_A,
                "bytecode": [
                    "_H", 1, 32, "email", 32, "properties", 32, "person", 1, 3, 2,
                    "noSuchNativeExists", 1
                ],
            },
            {
                "type": "person", "key": "plan", "value": "paid", "operator": "exact",
                "conditionHash": HASH_B, "bytecode": person_bytecode("plan", "paid"),
            },
        ] } })
    }

    /// A leaf reading `person.id`, which differs on every row and so can never be shortcut.
    fn person_id_filter() -> Value {
        json!({ "properties": { "type": "AND", "values": [
            {
                "type": "person", "key": "id", "value": "x", "operator": "exact",
                "conditionHash": HASH_A,
                "bytecode": ["_H", 1, 32, "x", 32, "id", 32, "person", 1, 2, 11],
            },
            {
                "type": "person", "key": "plan", "value": "paid", "operator": "exact",
                "conditionHash": HASH_B,
                "bytecode": person_bytecode("plan", "paid"),
            },
        ] } })
    }

    fn participation(cohort_id: i32, filters: Value, superseded: bool) -> PinnedParticipation {
        PinnedParticipation {
            cohort_id: CohortId(cohort_id),
            pinned_filters: filters,
            state: if superseded {
                PinnedParticipationState::Superseded
            } else {
                PinnedParticipationState::Active
            },
        }
    }

    fn pinned(conditions: &[(i32, &str)]) -> Value {
        let conditions = conditions
            .iter()
            .map(|(cohort_id, hash)| json!({ "cohort_id": cohort_id, "condition_hash": hash }))
            .collect::<Vec<_>>();
        json!({ "schema_version": 1, "conditions": conditions, "person_horizon_days": 30 })
    }

    fn snapshot(pinned: Value, participations: Vec<PinnedParticipation>) -> PersonPinnedSnapshot {
        PersonPinnedSnapshot {
            run_id: RunId(Uuid::nil()),
            team_id: TeamId(2),
            timezone: "UTC".to_string(),
            person_scan_since: Some(UtcMillis::new(1_780_000_000_000)),
            pinned,
            participations,
        }
    }

    const HASH_A: &str = "aaaaaaaaaaaaaaaa";
    const HASH_B: &str = "bbbbbbbbbbbbbbbb";

    fn seedable(validation: Result<PersonRunValidation, PinnedError>) -> ValidatedPinnedPersonRun {
        match validation.unwrap() {
            PersonRunValidation::Seedable(validated) => validated,
            PersonRunValidation::Retired { .. } => panic!("expected a seedable run"),
        }
    }

    #[test]
    fn tile_ranges_covers_the_full_space_for_no_boundaries() {
        let ranges = tile_ranges(&[]).unwrap();
        assert_eq!(ranges.len(), 1);
        assert_eq!(ranges[0].lo(), Uuid::nil());
        assert_eq!(ranges[0].hi(), None);
    }

    proptest! {
        /// Structural tiling only — no ordering assertions, by design: boundaries are opaque
        /// ClickHouse-order values and the tiling must preserve their arrival order.
        #[test]
        fn tile_ranges_is_structural_and_order_preserving(
            raw in prop::collection::vec(any::<u128>(), 0..64),
            duplicate_at in any::<prop::sample::Index>(),
        ) {
            let mut boundaries: Vec<Uuid> = raw.iter().copied().map(Uuid::from_u128).collect();
            if !boundaries.is_empty() {
                let index = duplicate_at.index(boundaries.len());
                boundaries.insert(index, boundaries[index]);
            }
            let ranges = tile_ranges(&boundaries).unwrap();

            prop_assert_eq!(ranges[0].lo(), Uuid::nil());
            prop_assert_eq!(ranges[ranges.len() - 1].hi(), None);
            prop_assert!(ranges.len() <= boundaries.len() + 1);
            for pair in ranges.windows(2) {
                prop_assert_eq!(pair[0].hi(), Some(pair[1].lo()));
            }
            // The kept boundaries appear as endpoints in their arrival order.
            let mut endpoints = ranges.iter().filter_map(|range| range.hi());
            let mut previous = Uuid::nil();
            for boundary in &boundaries {
                if *boundary == previous {
                    continue;
                }
                prop_assert_eq!(endpoints.next(), Some(*boundary));
                previous = *boundary;
            }
            prop_assert!(ranges.iter().all(|range| range.hi() != Some(range.lo())));
        }
    }

    #[test]
    fn validate_covers_survival_drops_and_terminal_failures() {
        let active = person_filter_leaves(&[(HASH_A, "email", "a@b.com")]);

        // Wrong schema version.
        let mut wrong_schema = pinned(&[(1, HASH_A)]);
        wrong_schema["schema_version"] = json!(2);
        assert!(matches!(
            PinnedPersonRun::validate(snapshot(
                wrong_schema,
                vec![participation(1, active.clone(), false)]
            )),
            Err(PinnedError::SchemaVersion(2))
        ));

        // Missing person_scan_since is terminal.
        let mut no_since = snapshot(
            pinned(&[(1, HASH_A)]),
            vec![participation(1, active.clone(), false)],
        );
        no_since.person_scan_since = None;
        assert!(matches!(
            PinnedPersonRun::validate(no_since),
            Err(PinnedError::MissingPersonScanSince)
        ));

        // A hash absent from the frozen catalog warns, drops, and leaves the cohort uncovered.
        let validated = seedable(PinnedPersonRun::validate(snapshot(
            pinned(&[(1, HASH_A), (2, HASH_B)]),
            vec![
                participation(1, active.clone(), false),
                participation(
                    2,
                    json!({ "properties": { "type": "AND", "values": [] } }),
                    false,
                ),
            ],
        )));
        assert_eq!(
            validated
                .run
                .conditions
                .iter()
                .map(|(hash, _)| *hash)
                .collect::<Vec<_>>(),
            vec![hash(HASH_A)]
        );
        assert_eq!(validated.uncovered_cohorts, vec![CohortId(2)]);
        assert!(validated
            .warnings
            .contains(&PinnedWarning::ConditionDropped {
                cohort_id: CohortId(2),
                hash: hash(HASH_B),
                reason: PinnedDropReason::AbsentFromFrozenCatalog,
            }));
        assert_eq!(validated.run.horizon_days, 30);

        // A superseded cohort's hash warns distinctly and expects no coverage.
        let validated = seedable(PinnedPersonRun::validate(snapshot(
            pinned(&[(1, HASH_A), (2, HASH_B)]),
            vec![
                participation(1, active.clone(), false),
                participation(2, person_filter_leaves(&[(HASH_B, "plan", "paid")]), true),
            ],
        )));
        assert_eq!(validated.run.conditions.len(), 1);
        assert!(validated.uncovered_cohorts.is_empty());
        assert!(validated
            .warnings
            .contains(&PinnedWarning::ConditionSuperseded {
                cohort_id: CohortId(2),
                hash: hash(HASH_B),
            }));

        // A condition naming a cohort outside the participations is a hard error.
        assert!(matches!(
            PinnedPersonRun::validate(snapshot(
                pinned(&[(9, HASH_A)]),
                vec![participation(1, active.clone(), false)],
            )),
            Err(PinnedError::MissingParticipation(9))
        ));

        // Cross-cohort duplicate hashes dedup to one evaluated condition covering both cohorts.
        let validated = seedable(PinnedPersonRun::validate(snapshot(
            pinned(&[(1, HASH_A), (2, HASH_A)]),
            vec![
                participation(1, active.clone(), false),
                participation(
                    2,
                    person_filter_leaves(&[(HASH_A, "email", "a@b.com")]),
                    false,
                ),
            ],
        )));
        assert_eq!(validated.run.conditions.len(), 1);
        assert!(validated.uncovered_cohorts.is_empty());

        // Zero surviving hashes with an active participation is terminal — that cohort's pinned
        // conditions dropped from the catalog, a genuine data problem.
        assert!(matches!(
            PinnedPersonRun::validate(snapshot(
                pinned(&[(1, HASH_B)]),
                vec![participation(1, active.clone(), false)],
            )),
            Err(PinnedError::NoSurvivingPersonConditions)
        ));

        // Every participation superseded: nothing expects coverage, so the run retires as
        // zero-work instead of failing (the behavioral zero-condition semantics).
        assert!(matches!(
            PinnedPersonRun::validate(snapshot(
                pinned(&[(1, HASH_A)]),
                vec![participation(1, active, true)],
            )),
            Ok(PersonRunValidation::Retired { warnings })
                if warnings.contains(&PinnedWarning::ConditionSuperseded {
                    cohort_id: CohortId(1),
                    hash: hash(HASH_A),
                })
        ));
    }

    #[test]
    fn validate_enforces_the_seed_hash_cap() {
        let leaves: Vec<(String, String)> = (0..=MAX_PERSON_SEED_HASHES)
            .map(|index| (format!("{index:016}"), format!("key{index}")))
            .collect();
        let leaf_refs: Vec<(&str, &str, &str)> = leaves
            .iter()
            .map(|(hash, key)| (hash.as_str(), key.as_str(), "v"))
            .collect();
        let conditions: Vec<(i32, &str)> =
            leaves.iter().map(|(hash, _)| (1, hash.as_str())).collect();
        assert!(matches!(
            PinnedPersonRun::validate(snapshot(
                pinned(&conditions),
                vec![participation(1, person_filter_leaves(&leaf_refs), false)],
            )),
            Err(PinnedError::PersonConditionsOverCap(count)) if count == MAX_PERSON_SEED_HASHES + 1
        ));
    }

    /// A hash present in the person-condition set whose leaf-state entry resolves to a behavioral
    /// variant must drop with the distinct reason — the mirror of the processor's projection.
    #[test]
    fn a_variant_mismatched_hash_drops_distinctly() {
        let mut filters = TeamFilters::default();
        let bytes = hash(HASH_A).as_bytes();
        filters.person_property_conditions.insert(bytes);
        filters.by_lsk.insert(
            LeafStateKey::for_person_property(&bytes),
            LeafStateMeta {
                variant: StateVariant::BehavioralSingle,
                condition_hash: bytes,
                window: None,
                window_days: None,
                predicate_op: None,
            },
        );
        assert!(matches!(
            classify_person_condition(hash(HASH_A), &filters),
            PersonSurvival::Dropped(PinnedDropReason::VariantMismatch)
        ));
    }

    fn seedable_run() -> ValidatedPinnedPersonRun {
        seedable(PinnedPersonRun::validate(snapshot(
            pinned(&[(1, HASH_A), (1, HASH_B)]),
            vec![participation(
                1,
                person_filter_leaves(&[(HASH_A, "email", "a@b.com"), (HASH_B, "plan", "paid")]),
                false,
            )],
        )))
    }

    fn build_evaluator(emit_nonmatchers: bool) -> PersonEvaluator {
        PersonEvaluator::new(
            &Arc::new(seedable_run().run),
            PersonEmissionPolicy::from_emit_nonmatchers(emit_nonmatchers),
        )
    }

    const CLAIM_STAMP_MS: i64 = 1_783_470_000_000;

    fn claimed_spec(
        run_id: RunId,
        team_id: TeamId,
        person_range: Option<PersonRange>,
    ) -> ChunkSpec {
        ChunkSpec {
            lease: ChunkLease::new(ChunkId(Uuid::from_u128(11)), run_id, ClaimEpoch(3)),
            team_id,
            day: 0,
            band: BandSpec::new(0, 1).unwrap(),
            s_chunk: SChunkMs(CLAIM_STAMP_MS),
            person_range,
            attempt: AttemptCount::from_row(1),
        }
    }

    /// The narrowing guard fences the scan: a chunk from another run or team must never be scanned
    /// against this run's conditions, and a chunk with no range is a behavioral chunk — scanning it
    /// would sweep the entire UUID space. The accepted case pins the one deliberate claim-stamp →
    /// `scanned_at` bridge.
    #[test]
    fn chunk_spec_admits_only_this_runs_ranged_chunks() {
        let run = seedable_run().run;
        let range = PersonRange::new(Uuid::nil(), None).unwrap();

        assert!(matches!(
            run.chunk_spec(&claimed_spec(
                RunId(Uuid::from_u128(9)),
                run.team_id,
                Some(range)
            )),
            Err(PersonChunkSpecError::RunMismatch { .. })
        ));
        assert!(matches!(
            run.chunk_spec(&claimed_spec(run.run_id, TeamId(3), Some(range))),
            Err(PersonChunkSpecError::RunMismatch { .. })
        ));
        assert!(matches!(
            run.chunk_spec(&claimed_spec(run.run_id, run.team_id, None)),
            Err(PersonChunkSpecError::MissingRange(_))
        ));

        let spec = run
            .chunk_spec(&claimed_spec(run.run_id, run.team_id, Some(range)))
            .unwrap();
        assert_eq!(spec.range, range);
        assert_eq!(spec.scanned_at, ScannedAtMs(CLAIM_STAMP_MS));
    }

    fn context() -> PersonSeedContext {
        PersonSeedContext {
            scanned_at: ScannedAtMs(1_783_470_000_000),
            run_id: RunId(Uuid::nil()),
            claim_epoch: ClaimEpoch(1),
        }
    }

    #[test]
    fn evaluate_row_mints_sorted_subset_seeds_and_classifies_skips() {
        let person = Uuid::from_u128(7).to_string();
        let ctx = context();

        // One matching condition of two: evaluated carries both, matched the sorted subset.
        let mut evaluator = build_evaluator(true);
        let (outcome, stats) =
            evaluator.evaluate_row(&person, r#"{"email":"a@b.com","plan":"free"}"#, &ctx);
        let PersonRowOutcome::Seed(seed) = outcome else {
            panic!("expected a seed, got {outcome:?}");
        };
        assert_eq!(seed.evaluated(), &[hash(HASH_A), hash(HASH_B)]);
        assert_eq!(seed.matched(), &[hash(HASH_A)]);
        assert_eq!(seed.scanned_at_ms(), ctx.scanned_at);
        assert_eq!((stats.matched, stats.non_matched), (1, 1));

        // Non-matcher with emission on: an empty-matched healing seed.
        let (outcome, _) = evaluator.evaluate_row(&person, r#"{"email":"x"}"#, &ctx);
        let PersonRowOutcome::Seed(seed) = outcome else {
            panic!("expected a healing seed, got {outcome:?}");
        };
        assert!(seed.matched().is_empty());

        // Non-matcher with emission off: skipped.
        let mut quiet = build_evaluator(false);
        let (outcome, stats) = quiet.evaluate_row(&person, r#"{"email":"x"}"#, &ctx);
        assert_eq!(outcome, PersonRowOutcome::NonMatcher);
        assert_eq!(stats.non_matched, 2);

        // Invalid person id and malformed properties are classified, never minted.
        let mut evaluator = build_evaluator(true);
        let (outcome, _) = evaluator.evaluate_row("not-a-uuid", "{}", &ctx);
        assert_eq!(
            outcome,
            PersonRowOutcome::Skipped(PersonRowSkip::InvalidPersonId)
        );
        let (outcome, _) = evaluator.evaluate_row(&person, "{not json", &ctx);
        assert_eq!(
            outcome,
            PersonRowOutcome::Skipped(PersonRowSkip::InvalidProperties)
        );
    }

    /// Live-equivalence anchor: for identical person properties, the scan fold reaches exactly the
    /// verdict the live event path reaches through `build_person_property_globals` (byte-equal
    /// globals are pinned in cohort-core; this pins the verdict end to end).
    #[test]
    fn evaluate_row_matches_the_live_event_paths_verdict() {
        use cohort_core::events::CohortStreamEvent;
        use cohort_core::hogvm::build_person_property_globals;

        let person = Uuid::from_u128(7);
        let ctx = context();
        let run = Arc::new(seedable_run().run);
        // Blobs the shortcut decides (no `email`, no `plan`) beside blobs it hands to the VM, so the
        // oracle sees both paths. A non-object blob has to take the VM path: an array makes
        // `GET_GLOBAL` error where an empty object yields null.
        for properties in [
            r#"{"email":"a@b.com","plan":"paid"}"#,
            r#"{"email":"x"}"#,
            r#"{"email":null}"#,
            r#"{}"#,
            "",
            r#"{"other":1}"#,
            r#"{"Email":"a@b.com","PLAN":"paid"}"#,
            r#"null"#,
            r#"[1]"#,
            r#""a string""#,
            r#"42"#,
        ] {
            let event = CohortStreamEvent {
                team_id: 2,
                person_id: person.to_string(),
                distinct_id: person.to_string(),
                uuid: Uuid::from_u128(1).to_string(),
                event: "$pageview".to_string(),
                timestamp: "2026-05-26 12:34:56.789000".to_string(),
                properties: Some("{}".to_string()),
                person_properties: Some(properties.to_string()),
                elements_chain: None,
                source_offset: 0,
                source_partition: -1,
                redirected_from: None,
                redirect_hops: 0,
            };
            let globals = build_person_property_globals(&event).unwrap();
            // `Some(true)` matched, `Some(false)` did not, `None` the VM never answered.
            let live: Vec<Option<bool>> = run
                .conditions
                .iter()
                .map(|(_, program)| {
                    match cohort_core::hogvm::evaluate_detailed(program.tokens(), globals.clone()) {
                        EvalOutcome::Matched(matched) => Some(matched),
                        EvalOutcome::UnknownFunction(_) | EvalOutcome::VmError(_) => None,
                    }
                })
                .collect();

            let mut evaluator =
                PersonEvaluator::new(&run, PersonEmissionPolicy::EveryScannedPerson);
            let (outcome, stats) = evaluator.evaluate_row(&person.to_string(), properties, &ctx);
            // The accounting has to agree too: a shortcut that reached the right verdict while
            // miscounting a VM failure as a non-match would leave the metrics lying.
            assert_eq!(
                (
                    stats.matched,
                    stats.non_matched,
                    stats.unknown_functions,
                    stats
                        .vm_failures
                        .iter()
                        .map(|(_, count)| count)
                        .sum::<u32>(),
                ),
                (
                    live.iter()
                        .filter(|verdict| **verdict == Some(true))
                        .count() as u32,
                    live.iter()
                        .filter(|verdict| **verdict == Some(false))
                        .count() as u32,
                    0,
                    live.iter().filter(|verdict| verdict.is_none()).count() as u32,
                ),
                "{properties:?} accounted differently from live evaluation"
            );
            let seeded: Vec<Option<bool>> = match outcome {
                PersonRowOutcome::Seed(seed) => run
                    .conditions
                    .iter()
                    .map(|(hash, _)| {
                        seed.evaluated()
                            .contains(hash)
                            .then(|| seed.matched().contains(hash))
                    })
                    .collect(),
                PersonRowOutcome::Skipped(PersonRowSkip::NothingEvaluated) => {
                    vec![None; run.conditions.len()]
                }
                other => panic!("{properties:?} produced {other:?}"),
            };
            assert_eq!(seeded, live, "{properties:?} diverged from live evaluation");
        }
    }

    /// The emission policy is the only thing deciding whether a scanned person reaches the topic.
    /// The run's cohort is `email = a@b.com AND plan = paid`, so a person matching one leaf writes a
    /// record and recomposes to the same FALSE an absent record already reads.
    #[test]
    fn the_relevant_only_policy_prunes_a_matcher_that_cannot_move_its_cohort() {
        let person = Uuid::from_u128(7).to_string();
        let ctx = context();
        let run = Arc::new(seedable_run().run);
        let half = r#"{"email":"a@b.com","plan":"free"}"#;
        let member = r#"{"email":"a@b.com","plan":"paid"}"#;
        let neither = r#"{"email":"x"}"#;

        let mut healer = PersonEvaluator::new(&run, PersonEmissionPolicy::EveryScannedPerson);
        for properties in [half, member, neither] {
            let (outcome, _) = healer.evaluate_row(&person, properties, &ctx);
            assert!(
                matches!(outcome, PersonRowOutcome::Seed(_)),
                "the healer must see {properties}, got {outcome:?}"
            );
        }

        let mut quiet = PersonEvaluator::new(&run, PersonEmissionPolicy::RelevantToSomeCohort);
        assert_eq!(
            quiet.evaluate_row(&person, half, &ctx).0,
            PersonRowOutcome::Irrelevant
        );
        // An all-false row stays a non-matcher, so that counter keeps its meaning.
        assert_eq!(
            quiet.evaluate_row(&person, neither, &ctx).0,
            PersonRowOutcome::NonMatcher
        );
        assert!(matches!(
            quiet.evaluate_row(&person, member, &ctx).0,
            PersonRowOutcome::Seed(_)
        ));
    }

    /// A vacuously true leaf under an OR makes every key-less person a member, so nothing about that
    /// run may be pruned or filtered away. This is the case the whole design has to not break.
    #[test]
    fn a_vacuously_true_leaf_under_an_or_is_neither_pruned_nor_filtered() {
        let person = Uuid::from_u128(7).to_string();
        let ctx = context();
        let run = Arc::new(
            seedable(PinnedPersonRun::validate(snapshot(
                pinned(&[(1, HASH_A), (1, HASH_B)]),
                vec![participation(1, vacuously_true_or_filter(), false)],
            )))
            .run,
        );

        assert_eq!(
            run.scan_key_filter(PersonEmissionPolicy::RelevantToSomeCohort),
            None,
            "dropping key-less rows would drop this cohort's members"
        );

        let mut quiet = PersonEvaluator::new(&run, PersonEmissionPolicy::RelevantToSomeCohort);
        let (outcome, stats) = quiet.evaluate_row(&person, r#"{"other":1}"#, &ctx);
        let PersonRowOutcome::Seed(seed) = outcome else {
            panic!("a person with no email is a member here, got {outcome:?}");
        };
        assert_eq!(
            seed.matched(),
            &[hash(HASH_B)],
            "not_icontains is vacuously true"
        );
        assert_eq!(
            stats.shortcut_evaluations, 2,
            "both conditions are still decided without the VM"
        );

        // Every person satisfies one leaf or the other — a PostHog address through `is_set`, a
        // missing one through `not_icontains` — which is what makes this cohort the whole team and
        // why no row of it can be dropped.
        let (outcome, _) = quiet.evaluate_row(&person, r#"{"email":"a@posthog.com"}"#, &ctx);
        let PersonRowOutcome::Seed(seed) = outcome else {
            panic!("a PostHog address still satisfies is_set, got {outcome:?}");
        };
        assert_eq!(seed.matched(), &[hash(HASH_A)]);
    }

    /// Two of the filter's preconditions: the relevant-only policy, and every condition decidable
    /// from the blob's keys. The third — an irrelevant vacuous vector — is
    /// `a_vacuously_true_leaf_under_an_or_is_neither_pruned_nor_filtered`, and the verdict-shaped
    /// fourth is `a_condition_the_vm_cannot_answer_on_an_empty_bag_withholds_the_scan_filter`.
    #[test]
    fn the_scan_key_filter_needs_the_relevant_only_policy_and_key_decidable_conditions() {
        let decidable = seedable_run().run;
        assert_eq!(
            decidable
                .scan_key_filter(PersonEmissionPolicy::RelevantToSomeCohort)
                .as_ref()
                .map(|keys| keys.iter().collect::<Vec<_>>()),
            Some(vec!["email", "plan"]),
        );
        assert_eq!(
            decidable.scan_key_filter(PersonEmissionPolicy::EveryScannedPerson),
            None,
            "the healer has to see every scanned person",
        );

        // A condition reading `person.id` cannot be decided from the blob's keys, so a dropped row
        // might have been one it matched.
        let reads_person_id = seedable(PinnedPersonRun::validate(snapshot(
            pinned(&[(1, HASH_A), (1, HASH_B)]),
            vec![participation(1, person_id_filter(), false)],
        )))
        .run;
        assert_eq!(
            reads_person_id.scan_key_filter(PersonEmissionPolicy::RelevantToSomeCohort),
            None
        );
    }

    /// The consumer keeps its stored bit for any leaf a seed does not assert, so a row where some
    /// condition never answered composes `matched ∪ untouched`, not the vector the oracle judged.
    /// Pruning such a row would lose a real flip: a person with a stored TRUE for the failing leaf
    /// and a fresh TRUE for the other one enters the AND, and the oracle cannot see it.
    #[test]
    fn a_row_whose_seed_does_not_assert_every_leaf_is_never_pruned() {
        let person = Uuid::from_u128(7).to_string();
        let ctx = context();
        // `9999` is no opcode, so the leaf loads and then fails at run time.
        let mut leaves = person_filter_leaves(&[(HASH_A, "email", "a@b.com")]);
        leaves["properties"]["values"]
            .as_array_mut()
            .unwrap()
            .push(json!({
                "type": "person", "key": "plan", "value": "paid", "operator": "exact",
                "conditionHash": HASH_B, "bytecode": ["_H", 1, 9999],
            }));
        let run = Arc::new(
            seedable(PinnedPersonRun::validate(snapshot(
                pinned(&[(1, HASH_A), (1, HASH_B)]),
                vec![participation(1, leaves, false)],
            )))
            .run,
        );

        let mut quiet = PersonEvaluator::new(&run, PersonEmissionPolicy::RelevantToSomeCohort);
        let (outcome, stats) = quiet.evaluate_row(&person, r#"{"email":"a@b.com"}"#, &ctx);
        let PersonRowOutcome::Seed(seed) = outcome else {
            panic!(
                "the failing leaf's stored bit is unknown here, so the row must seed: {outcome:?}"
            );
        };
        assert_eq!(seed.evaluated(), &[hash(HASH_A)]);
        assert_eq!(
            stats
                .vm_failures
                .iter()
                .map(|(_, count)| count)
                .sum::<u32>(),
            1
        );
    }

    /// The same hole, one level up: if a key-less row would leave a condition unanswered, ClickHouse
    /// must not be the one to drop it, because the seeder would have asserted nothing for that leaf
    /// and the consumer would have kept its stored bit.
    #[test]
    fn a_condition_the_vm_cannot_answer_on_an_empty_bag_withholds_the_scan_filter() {
        let run = seedable(PinnedPersonRun::validate(snapshot(
            pinned(&[(1, HASH_A), (1, HASH_B)]),
            vec![participation(1, unknown_native_filter(), false)],
        )))
        .run;

        // Both conditions are key-decidable — the analyzer narrows the unknown native's read set
        // fine — so only the verdict itself withholds the filter.
        assert_eq!(
            run.analysis_census().key_decidable,
            2,
            "the precondition under test is the verdict, not the read set"
        );
        assert_eq!(
            run.scan_key_filter(PersonEmissionPolicy::RelevantToSomeCohort),
            None
        );
    }

    /// The contract between the two mechanisms, checked rather than reasoned: when a run renders a
    /// key filter, every object blob ClickHouse would drop must be one the fold declines to seed.
    /// A filter that outran the fold would silently lose members, and nothing else in the suite
    /// compares the two.
    #[test]
    fn every_blob_the_key_filter_drops_is_one_the_fold_would_not_have_seeded() {
        let person = Uuid::from_u128(7).to_string();
        let ctx = context();
        let run = Arc::new(seedable_run().run);
        let keys = run
            .scan_key_filter(PersonEmissionPolicy::RelevantToSomeCohort)
            .expect("this run renders a filter");
        let mut quiet = PersonEvaluator::new(&run, PersonEmissionPolicy::RelevantToSomeCohort);

        for dropped in [
            r#"{}"#,
            r#"{"other":1}"#,
            r#"{"Email":"a@b.com","Plan":"paid"}"#,
            r#"{"nested":{"email":"a@b.com","plan":"paid"}}"#,
            r#"{"emails":["a@b.com"],"plans":"paid"}"#,
        ] {
            let map = serde_json::from_str::<Value>(dropped).unwrap();
            let map = map.as_object().unwrap().clone();
            assert!(
                keys.iter().all(|key| !map.contains_key(key)),
                "{dropped} must be one ClickHouse drops, or this case proves nothing"
            );
            let (outcome, _) = quiet.evaluate_row(&person, dropped, &ctx);
            assert!(
                !matches!(outcome, PersonRowOutcome::Seed(_)),
                "{dropped} would be dropped by the scan yet seeded by the fold: {outcome:?}"
            );
        }
    }

    /// The cascade-off asymmetry, driven through `RelevanceOracle::build` rather than a hand-built
    /// tree: the seeder calls a ref-bearing cohort `Excluded(HasCohortRef)` because it freezes with
    /// cascade off, while the consumer composes it. Counting it as never-composed would prune its
    /// real members. A root-negated cohort is excluded the same way in both services and is skipped.
    #[test]
    fn build_counts_a_ref_bearing_cohort_and_skips_a_root_negated_one() {
        let person = Uuid::from_u128(7).to_string();
        let ctx = context();
        const HASH_C: &str = "cccccccccccccccc";
        let run = Arc::new(
            seedable(PinnedPersonRun::validate(snapshot(
                pinned(&[(1, HASH_A), (1, HASH_B), (2, HASH_C)]),
                vec![
                    participation(1, and_with_a_cohort_reference(), false),
                    participation(2, negated_root_filter(HASH_C), false),
                ],
            )))
            .run,
        );
        assert_eq!(
            run.composable_cohorts(),
            Some(1),
            "the ref-bearing cohort composes; the root-negated one does not"
        );

        let mut quiet = PersonEvaluator::new(&run, PersonEmissionPolicy::RelevantToSomeCohort);
        // Both pinned leaves true turns the AND's unknown reference into the deciding leaf, so the
        // verdict moves off its absent FALSE and the seed has to reach the consumer.
        assert!(matches!(
            quiet
                .evaluate_row(&person, r#"{"email":"a@b.com","plan":"paid"}"#, &ctx)
                .0,
            PersonRowOutcome::Seed(_)
        ));
        // One leaf true still leaves the AND determinately false, whatever the reference resolves
        // to, so nothing can move.
        assert_eq!(
            quiet
                .evaluate_row(&person, r#"{"email":"a@b.com","plan":"free"}"#, &ctx)
                .0,
            PersonRowOutcome::Irrelevant
        );
    }

    /// The negation bit has to survive `compile`: `email = a@b.com AND NOT plan = paid` composes,
    /// and its member folds TRUE only through `bit ^ negated`. Were the bit dropped, that member
    /// would fold to the absent FALSE and be pruned, with no error and no metric.
    #[test]
    fn build_keeps_the_negation_of_a_pinned_leaf_below_the_root() {
        let person = Uuid::from_u128(7).to_string();
        let ctx = context();
        let mut leaves =
            person_filter_leaves(&[(HASH_A, "email", "a@b.com"), (HASH_B, "plan", "paid")]);
        leaves["properties"]["values"][1]["negation"] = json!(true);
        let run = Arc::new(
            seedable(PinnedPersonRun::validate(snapshot(
                pinned(&[(1, HASH_A), (1, HASH_B)]),
                vec![participation(1, leaves, false)],
            )))
            .run,
        );
        assert_eq!(
            run.composable_cohorts(),
            Some(1),
            "one negated leaf under a two-leaf AND is not a root negation"
        );

        let mut quiet = PersonEvaluator::new(&run, PersonEmissionPolicy::RelevantToSomeCohort);
        // The member: the positive leaf true, the negated one false.
        assert!(matches!(
            quiet
                .evaluate_row(&person, r#"{"email":"a@b.com","plan":"free"}"#, &ctx)
                .0,
            PersonRowOutcome::Seed(_)
        ));
        // Both leaves true is a non-member, which the absent prior already reads as.
        assert_eq!(
            quiet
                .evaluate_row(&person, r#"{"email":"a@b.com","plan":"paid"}"#, &ctx)
                .0,
            PersonRowOutcome::Irrelevant
        );
    }

    /// Only the conditions whose keys the blob lacks skip the VM, and a non-object blob skips none.
    #[test]
    fn the_shortcut_count_tracks_which_keys_the_blob_carries() {
        let person = Uuid::from_u128(7).to_string();
        let ctx = context();
        let run = Arc::new(seedable_run().run);
        let mut evaluator = PersonEvaluator::new(&run, PersonEmissionPolicy::EveryScannedPerson);

        for (properties, expected) in [
            (r#"{"other":1}"#, 2),
            (r#"{}"#, 2),
            (r#"{"email":"a@b.com"}"#, 1),
            (r#"{"email":"a@b.com","plan":"paid"}"#, 0),
            (r#"[1]"#, 0),
            (r#"null"#, 0),
        ] {
            let (_, stats) = evaluator.evaluate_row(&person, properties, &ctx);
            assert_eq!(
                stats.shortcut_evaluations, expected,
                "{properties} shortcut {} conditions",
                stats.shortcut_evaluations
            );
        }
    }

    /// A condition whose bytecode fails the VM is excluded from `evaluated` — the seed must never
    /// assert FALSE for a hash the VM never answered — and an all-failure row emits nothing.
    #[test]
    fn vm_failures_drop_hashes_from_evaluated_rather_than_asserting_false() {
        // Loads (the header is valid) but 9999 is no opcode, so it fails at run time. Bytecode the
        // loader rejects outright never reaches the evaluator: that leaf is dropped at catalog build.
        let broken = json!(["_H", 1, 9999]);
        let mut leaves = person_filter_leaves(&[(HASH_A, "email", "a@b.com")]);
        leaves["properties"]["values"]
            .as_array_mut()
            .unwrap()
            .push(json!({
                "type": "person",
                "key": "plan",
                "value": "paid",
                "operator": "exact",
                "conditionHash": HASH_B,
                "bytecode": broken,
            }));
        let validated = seedable(PinnedPersonRun::validate(snapshot(
            pinned(&[(1, HASH_A), (1, HASH_B)]),
            vec![participation(1, leaves, false)],
        )));
        let mut evaluator = PersonEvaluator::new(
            &Arc::new(validated.run),
            PersonEmissionPolicy::EveryScannedPerson,
        );
        let ctx = context();

        let (outcome, stats) = evaluator.evaluate_row(
            &Uuid::from_u128(7).to_string(),
            r#"{"email":"a@b.com"}"#,
            &ctx,
        );
        let PersonRowOutcome::Seed(seed) = outcome else {
            panic!("expected a seed, got {outcome:?}");
        };
        assert_eq!(seed.evaluated(), &[hash(HASH_A)]);
        assert_eq!(
            stats
                .vm_failures
                .iter()
                .map(|(_, count)| count)
                .sum::<u32>(),
            1
        );
    }
}
