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
    build_person_scan_globals, classify_vm_error, CohortEvaluator, EvalOutcome,
};
use cohort_core::seed::PersonSeed;
use cohort_core::{LeafStateKey, StateVariant};
use serde::Deserialize;
use serde_json::Value;
use uuid::Uuid;

use super::aggregate::RecordStats;
use super::chunk::{ChunkLease, ChunkSpec};
use super::ids::{ClaimEpoch, ConditionHash, RunId, ScannedAtMs, UtcMillis};
use super::pinned::{
    resolve_timezone, ParticipationSet, PinnedDropReason, PinnedError, PinnedParticipation,
    PinnedParticipationState, PinnedWarning,
};

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
#[derive(Debug)]
pub struct PinnedPersonRun {
    pub run_id: RunId,
    pub team_id: TeamId,
    pub scan_since: UtcMillis,
    pub conditions: EvaluatedConditions,
    pub horizon_days: u32,
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

        let mut surviving: BTreeMap<ConditionHash, Arc<Vec<Value>>> = BTreeMap::new();
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
                PersonSurvival::Survives(bytecode) => {
                    surviving.entry(hash).or_insert(bytecode);
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

        Ok(PersonRunValidation::Seedable(ValidatedPinnedPersonRun {
            run: PinnedPersonRun {
                run_id: snapshot.run_id,
                team_id: snapshot.team_id,
                scan_since,
                conditions,
                horizon_days: payload.person_horizon_days,
            },
            warnings,
            uncovered_cohorts,
        }))
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
    Survives(Arc<Vec<Value>>),
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
    match filters.by_condition_to_bytecode.get(&bytes) {
        Some(bytecode) => PersonSurvival::Survives(Arc::clone(bytecode)),
        None => PersonSurvival::Dropped(PinnedDropReason::AbsentFromFrozenCatalog),
    }
}

/// The surviving person conditions: non-empty, sorted-distinct by hash, each with its frozen
/// bytecode — so an empty `evaluated` or a hash/bytecode mismatch is unrepresentable at eval time.
#[derive(Debug, Clone)]
pub struct EvaluatedConditions(Vec<(ConditionHash, Arc<Vec<Value>>)>);

// Non-empty by construction, so an `is_empty` would be a method whose contract is "never call me".
#[allow(clippy::len_without_is_empty)]
impl EvaluatedConditions {
    fn new(surviving: BTreeMap<ConditionHash, Arc<Vec<Value>>>) -> Result<Self, PinnedError> {
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

    pub fn iter(&self) -> impl Iterator<Item = &(ConditionHash, Arc<Vec<Value>>)> {
        self.0.iter()
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
    /// Evaluated fully, nothing matched, and non-matcher emission is off.
    NonMatcher,
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

/// The pure per-row fold: build scan globals, run every surviving condition through the shared
/// evaluator, and mint at most one [`PersonSeed`]. Unit-testable without ClickHouse or Kafka.
pub struct PersonEvaluator {
    team_id: TeamId,
    conditions: EvaluatedConditions,
    evaluator: CohortEvaluator,
    emit_nonmatchers: bool,
}

impl PersonEvaluator {
    pub fn new(team_id: TeamId, conditions: EvaluatedConditions, emit_nonmatchers: bool) -> Self {
        Self {
            team_id,
            conditions,
            evaluator: CohortEvaluator::new(),
            emit_nonmatchers,
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
        let Ok(globals) = build_person_scan_globals(self.team_id, person_id, properties) else {
            return (
                PersonRowOutcome::Skipped(PersonRowSkip::InvalidProperties),
                stats,
            );
        };
        self.evaluator.set_globals(globals);

        let mut evaluated = Vec::with_capacity(self.conditions.len());
        let mut matched = Vec::new();
        for (hash, bytecode) in self.conditions.iter() {
            match self.evaluator.evaluate_detailed(Arc::clone(bytecode)) {
                EvalOutcome::Matched(true) => {
                    evaluated.push(*hash);
                    matched.push(*hash);
                    stats.matched += 1;
                }
                EvalOutcome::Matched(false) => {
                    evaluated.push(*hash);
                    stats.non_matched += 1;
                }
                // A hash the VM never answered is excluded from `evaluated`: its absence from
                // `matched` would otherwise assert FALSE and mint a wrong `Left`.
                EvalOutcome::UnknownFunction(_) => stats.unknown_functions += 1,
                EvalOutcome::VmError(error) => stats
                    .vm_failures
                    .increment(classify_vm_error(&error))
                    .expect("per-row VM failure counts are bounded by the condition cap"),
            }
        }
        if evaluated.is_empty() {
            return (
                PersonRowOutcome::Skipped(PersonRowSkip::NothingEvaluated),
                stats,
            );
        }
        if matched.is_empty() && !self.emit_nonmatchers {
            return (PersonRowOutcome::NonMatcher, stats);
        }
        let seed = PersonSeed::new(
            self.team_id,
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
    use proptest::prelude::*;
    use serde_json::json;

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
        PersonEvaluator::new(TeamId(2), seedable_run().run.conditions, emit_nonmatchers)
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
        for properties in [r#"{"email":"a@b.com","plan":"paid"}"#, r#"{"email":"x"}"#] {
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
            let mut evaluator = build_evaluator(true);
            let (outcome, _) = evaluator.evaluate_row(&person.to_string(), properties, &ctx);
            let PersonRowOutcome::Seed(seed) = outcome else {
                panic!("expected a seed, got {outcome:?}");
            };
            for (hash, bytecode) in build_evaluator(true).conditions.iter() {
                let live = matches!(
                    cohort_core::hogvm::evaluate_detailed(bytecode, globals.clone()),
                    EvalOutcome::Matched(true)
                );
                assert_eq!(seed.matched().contains(hash), live, "hash {hash} diverged");
            }
        }
    }

    /// A condition whose bytecode fails the VM is excluded from `evaluated` — the seed must never
    /// assert FALSE for a hash the VM never answered — and an all-failure row emits nothing.
    #[test]
    fn vm_failures_drop_hashes_from_evaluated_rather_than_asserting_false() {
        let broken = json!([]);
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
        let mut evaluator = PersonEvaluator::new(TeamId(2), validated.run.conditions, true);
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
