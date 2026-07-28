//! Domain layer: `ChunkAccumulator` — folds scanned events through the shared HogVM evaluator into
//! per-`(person, condition, day)` tiles. Depends on `plan`, `window`, `ids`, and `cohort-core`
//! (including its `seed::SeedTile` wire type).

use std::collections::hash_map::Entry;
use std::collections::HashMap;
use std::num::NonZeroU32;
use std::sync::Arc;

use cohort_core::events::CohortStreamEvent;
use cohort_core::filters::{TeamFilters, TeamId};
use cohort_core::hogvm::{
    build_behavioral_globals, classify_vm_error, CohortEvaluator, EvalOutcome, VmErrorClass,
};
use uuid::Uuid;

use super::ids::{ClaimEpoch, ConditionHash, RunId};
use super::plan::ActiveConditions;
use super::window::SeedDomain;
use cohort_core::seed::SeedTile;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RecordOutcome {
    Evaluated(RecordStats),
    SkippedGlobals,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct RecordStats {
    pub matched: u32,
    pub non_matched: u32,
    pub unknown_functions: u32,
    pub vm_failures: VmFailureCounts,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct VmFailureCounts([u32; VmErrorClass::COUNT]);

impl Default for VmFailureCounts {
    fn default() -> Self {
        Self([0; VmErrorClass::COUNT])
    }
}

impl VmFailureCounts {
    pub fn get(&self, class: VmErrorClass) -> u32 {
        self.0.get(class.index()).copied().unwrap_or(0)
    }

    pub fn iter(&self) -> impl Iterator<Item = (VmErrorClass, u32)> + '_ {
        VmErrorClass::ALL
            .into_iter()
            .map(|class| (class, self.get(class)))
    }

    fn increment(&mut self, class: VmErrorClass) -> Result<(), AggregateError> {
        let count = self
            .0
            .get_mut(class.index())
            .ok_or(AggregateError::VmErrorClassInvariant(class))?;
        *count = count
            .checked_add(1)
            .ok_or(AggregateError::OutcomeCountOverflow(
                OutcomeKind::VmFailures,
            ))?;
        Ok(())
    }
}

struct ActiveCandidate {
    hash: ConditionHash,
    bytecode: Arc<Vec<serde_json::Value>>,
}

pub struct ChunkAccumulator {
    team_id: TeamId,
    active_by_event_name: HashMap<String, Vec<ActiveCandidate>>,
    evaluator: CohortEvaluator,
    counts: HashMap<(Uuid, ConditionHash), NonZeroU32>,
}

impl ChunkAccumulator {
    pub fn new(
        team_id: TeamId,
        filters: &TeamFilters,
        active: &ActiveConditions,
    ) -> Result<Self, AggregateError> {
        let active_by_event_name = filters
            .behavioral_by_event_name
            .iter()
            .map(|(event_name, candidates)| {
                let candidates = candidates
                    .iter()
                    .filter_map(|candidate| active.get(candidate).map(|hash| (candidate, hash)))
                    .map(|(candidate, hash)| {
                        let bytecode = filters
                            .by_condition_to_bytecode
                            .get(candidate)
                            .map(Arc::clone)
                            .ok_or(AggregateError::MissingBytecode(hash))?;
                        Ok(ActiveCandidate { hash, bytecode })
                    })
                    .collect::<Result<Vec<_>, AggregateError>>()?;
                Ok((event_name.clone(), candidates))
            })
            .filter_map(|result| match result {
                Ok((_, candidates)) if candidates.is_empty() => None,
                other => Some(other),
            })
            .collect::<Result<HashMap<_, _>, AggregateError>>()?;
        Ok(Self {
            team_id,
            active_by_event_name,
            evaluator: CohortEvaluator::new(),
            counts: HashMap::new(),
        })
    }

    pub fn record_event(
        &mut self,
        event: &CohortStreamEvent,
    ) -> Result<RecordOutcome, AggregateError> {
        if event.team_id != self.team_id.0 {
            return Err(AggregateError::TeamMismatch {
                expected: self.team_id,
                actual: event.team_id,
            });
        }
        let person_id = Uuid::parse_str(&event.person_id).map_err(|source| {
            AggregateError::InvalidPersonId {
                value: event.person_id.clone(),
                source,
            }
        })?;
        if self.active_by_event_name.is_empty() {
            return Ok(RecordOutcome::Evaluated(RecordStats::default()));
        }
        let Ok(globals) = build_behavioral_globals(event) else {
            return Ok(RecordOutcome::SkippedGlobals);
        };
        self.evaluator.set_globals(globals);
        let candidates = self
            .active_by_event_name
            .get(&event.event)
            .map_or(&[][..], Vec::as_slice);
        let mut stats = RecordStats::default();
        for candidate in candidates {
            match self
                .evaluator
                .evaluate_detailed(Arc::clone(&candidate.bytecode))
            {
                EvalOutcome::Matched(true) => {
                    increment_outcome(&mut stats.matched, OutcomeKind::Matched)?;
                }
                EvalOutcome::Matched(false) => {
                    increment_outcome(&mut stats.non_matched, OutcomeKind::NonMatched)?;
                    continue;
                }
                EvalOutcome::UnknownFunction(_) => {
                    increment_outcome(&mut stats.unknown_functions, OutcomeKind::UnknownFunctions)?;
                    continue;
                }
                EvalOutcome::VmError(error) => {
                    stats.vm_failures.increment(classify_vm_error(&error))?;
                    continue;
                }
            }
            match self.counts.entry((person_id, candidate.hash)) {
                Entry::Vacant(entry) => {
                    entry.insert(NonZeroU32::MIN);
                }
                Entry::Occupied(mut entry) => {
                    let next = entry
                        .get()
                        .checked_add(1)
                        .ok_or(AggregateError::CountOverflow {
                            person_id,
                            hash: candidate.hash,
                        })?;
                    entry.insert(next);
                }
            }
        }
        Ok(RecordOutcome::Evaluated(stats))
    }

    pub fn entry_count(&self) -> usize {
        self.counts.len()
    }

    pub fn into_tiles(
        self,
        domain: &SeedDomain,
        run_id: RunId,
        claim_epoch: ClaimEpoch,
    ) -> Vec<SeedTile> {
        let mut counts = self.counts.into_iter().collect::<Vec<_>>();
        counts.sort_unstable_by_key(|((person_id, hash), _)| (*person_id, *hash));
        counts
            .into_iter()
            .map(|((person_id, hash), count)| {
                SeedTile::new(
                    self.team_id,
                    person_id,
                    hash,
                    count,
                    domain.day(),
                    domain.s_chunk(),
                    run_id,
                    claim_epoch,
                )
            })
            .collect()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OutcomeKind {
    Matched,
    NonMatched,
    UnknownFunctions,
    VmFailures,
}

impl OutcomeKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Matched => "matched",
            Self::NonMatched => "non_matched",
            Self::UnknownFunctions => "unknown_functions",
            Self::VmFailures => "vm_failures",
        }
    }
}

fn increment_outcome(value: &mut u32, kind: OutcomeKind) -> Result<(), AggregateError> {
    *value = value
        .checked_add(1)
        .ok_or(AggregateError::OutcomeCountOverflow(kind))?;
    Ok(())
}

#[derive(Debug, thiserror::Error)]
pub enum AggregateError {
    #[error("event team {actual} does not match accumulator team {}", .expected.0)]
    TeamMismatch { expected: TeamId, actual: i32 },
    #[error("invalid person UUID {value:?}: {source}")]
    InvalidPersonId {
        value: String,
        #[source]
        source: uuid::Error,
    },
    #[error("active condition {0} has no frozen bytecode")]
    MissingBytecode(ConditionHash),
    #[error("record outcome counter {} overflowed", .0.as_str())]
    OutcomeCountOverflow(OutcomeKind),
    #[error("VM error class {0:?} is outside the bounded counter set")]
    VmErrorClassInvariant(VmErrorClass),
    #[error("daily count overflowed for person {person_id}, condition {hash}")]
    CountOverflow {
        person_id: Uuid,
        hash: ConditionHash,
    },
}

#[cfg(test)]
mod tests {
    use chrono_tz::UTC;
    use cohort_core::filters::{CohortId, TeamFiltersBuilder};
    use proptest::prelude::*;
    use serde_json::json;

    use super::*;
    use crate::domain::{Boundary, SChunkMs, UtcMillis};

    const HASH_A: &str = "aaaaaaaaaaaaaaaa";
    const HASH_B: &str = "bbbbbbbbbbbbbbbb";
    const HASH_FALSE: &str = "ffffffffffffffff";
    const HASH_UNKNOWN: &str = "uuuuuuuuuuuuuuuu";
    const HASH_BROKEN: &str = "xxxxxxxxxxxxxxxx";

    fn filters() -> TeamFilters {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(2),
                &json!({
                    "properties": { "type": "AND", "values": [
                        { "type": "behavioral", "value": "performed_event", "key": "a", "conditionHash": HASH_A, "time_value": 7, "time_interval": "day", "bytecode": ["_H", 1, 32, "a", 32, "event", 1, 1, 11] },
                        { "type": "behavioral", "value": "performed_event", "key": "b", "conditionHash": HASH_B, "time_value": 7, "time_interval": "day", "bytecode": ["_H", 1, 32, "b", 32, "event", 1, 1, 11] },
                    ]}
                }),
            )
            .unwrap();
        builder.freeze(UTC)
    }

    fn event(person: Uuid, event_name: &str) -> CohortStreamEvent {
        CohortStreamEvent {
            team_id: 2,
            person_id: person.to_string(),
            distinct_id: person.to_string(),
            uuid: Uuid::now_v7().to_string(),
            event: event_name.to_string(),
            timestamp: "2026-03-08 12:00:00.000000".to_string(),
            properties: Some("{}".to_string()),
            person_properties: Some("{}".to_string()),
            elements_chain: None,
            source_offset: 0,
            source_partition: -1,
            redirected_from: None,
            redirect_hops: 0,
        }
    }

    fn outcome_filters() -> TeamFilters {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(2),
                TeamId(2),
                &json!({
                    "properties": { "type": "AND", "values": [
                        { "type": "behavioral", "value": "performed_event", "key": "false", "conditionHash": HASH_FALSE, "time_value": 7, "time_interval": "day", "bytecode": ["_H", 1, 30] },
                        { "type": "behavioral", "value": "performed_event", "key": "unknown", "conditionHash": HASH_UNKNOWN, "time_value": 7, "time_interval": "day", "bytecode": ["_H", 1, 2, "definitelyNotANative", 0] },
                        { "type": "behavioral", "value": "performed_event", "key": "broken", "conditionHash": HASH_BROKEN, "time_value": 7, "time_interval": "day", "bytecode": [] },
                    ]}
                }),
            )
            .unwrap();
        builder.freeze(UTC)
    }

    fn evaluated(outcome: RecordOutcome) -> RecordStats {
        match outcome {
            RecordOutcome::Evaluated(stats) => stats,
            RecordOutcome::SkippedGlobals => panic!("expected evaluated event"),
        }
    }

    fn active() -> ActiveConditions {
        ActiveConditions::new([
            ConditionHash::parse(HASH_A).unwrap(),
            ConditionHash::parse(HASH_B).unwrap(),
        ])
    }

    fn domain() -> SeedDomain {
        let boundary = Boundary::new(UtcMillis::new(20 * 86_400_000), UTC);
        SeedDomain::new(19, boundary, UTC, SChunkMs(boundary.at_ms().as_i64())).unwrap()
    }

    #[test]
    fn fold_counts_each_matching_event_condition_pair_once() {
        let filters = filters();
        let active = active();
        let mut accumulator = ChunkAccumulator::new(TeamId(2), &filters, &active).unwrap();
        let person = Uuid::from_u128(1);
        assert_eq!(
            evaluated(accumulator.record_event(&event(person, "a")).unwrap()).matched,
            1
        );
        assert_eq!(
            evaluated(accumulator.record_event(&event(person, "a")).unwrap()).matched,
            1
        );
        assert_eq!(
            evaluated(accumulator.record_event(&event(person, "b")).unwrap()).matched,
            1
        );
        assert_eq!(
            evaluated(accumulator.record_event(&event(person, "other")).unwrap()),
            RecordStats::default()
        );

        let tiles = accumulator.into_tiles(&domain(), RunId(Uuid::nil()), ClaimEpoch(1));
        assert_eq!(tiles.iter().map(SeedTile::count).sum::<u32>(), 3);
        assert_eq!(tiles.len(), 2);
        assert_eq!(tiles[0].count(), 2);
        assert_eq!(tiles[1].count(), 1);
    }

    #[test]
    fn record_outcome_separates_false_unknown_function_and_vm_error() {
        let filters = outcome_filters();
        let active = ActiveConditions::new([
            ConditionHash::parse(HASH_FALSE).unwrap(),
            ConditionHash::parse(HASH_UNKNOWN).unwrap(),
            ConditionHash::parse(HASH_BROKEN).unwrap(),
        ]);
        let mut accumulator = ChunkAccumulator::new(TeamId(2), &filters, &active).unwrap();
        let person = Uuid::from_u128(1);

        let ordinary_false = evaluated(accumulator.record_event(&event(person, "false")).unwrap());
        assert_eq!(ordinary_false.non_matched, 1);
        assert_eq!(ordinary_false.unknown_functions, 0);
        assert_eq!(ordinary_false.vm_failures, VmFailureCounts::default());

        let unknown_function =
            evaluated(accumulator.record_event(&event(person, "unknown")).unwrap());
        assert_eq!(unknown_function.non_matched, 0);
        assert_eq!(unknown_function.unknown_functions, 1);
        assert_eq!(unknown_function.vm_failures, VmFailureCounts::default());

        let vm_error = evaluated(accumulator.record_event(&event(person, "broken")).unwrap());
        assert_eq!(vm_error.non_matched, 0);
        assert_eq!(vm_error.unknown_functions, 0);
        assert_eq!(vm_error.vm_failures.get(VmErrorClass::Program), 1);
        assert_eq!(accumulator.entry_count(), 0);
    }

    #[test]
    fn malformed_globals_skip_only_that_event_and_leave_counts_unchanged() {
        let filters = filters();
        let active = active();
        let mut accumulator = ChunkAccumulator::new(TeamId(2), &filters, &active).unwrap();
        let person = Uuid::from_u128(1);
        assert_eq!(
            evaluated(accumulator.record_event(&event(person, "a")).unwrap()).matched,
            1
        );

        let mut malformed = event(person, "a");
        malformed.properties = Some("{".to_string());
        assert_eq!(
            accumulator.record_event(&malformed).unwrap(),
            RecordOutcome::SkippedGlobals
        );
        assert_eq!(accumulator.entry_count(), 1);
        assert_eq!(
            evaluated(accumulator.record_event(&event(person, "a")).unwrap()).matched,
            1
        );

        let tiles = accumulator.into_tiles(&domain(), RunId(Uuid::nil()), ClaimEpoch(1));
        assert_eq!(tiles.iter().map(SeedTile::count).sum::<u32>(), 2);
    }

    proptest! {
        #[test]
        fn tile_sum_conserves_arbitrary_matched_pairs(
            stream in prop::collection::vec((0u8..16, 0u8..4), 0..500),
        ) {
            let filters = filters();
            let active = active();
            let mut accumulator = ChunkAccumulator::new(TeamId(2), &filters, &active).unwrap();
            let expected = stream.iter().filter(|(_, event_kind)| *event_kind < 2).count() as u32;
            for (person, event_kind) in stream {
                let event_name = match event_kind {
                    0 => "a",
                    1 => "b",
                    _ => "other",
                };
                let outcome = accumulator
                    .record_event(&event(Uuid::from_u128(u128::from(person) + 1), event_name))
                    .unwrap();
                prop_assert!(matches!(outcome, RecordOutcome::Evaluated(_)));
            }
            let tiles = accumulator.into_tiles(&domain(), RunId(Uuid::nil()), ClaimEpoch(1));
            prop_assert_eq!(tiles.iter().map(SeedTile::count).sum::<u32>(), expected);
            prop_assert!(tiles.iter().all(|tile| tile.count() > 0));
        }
    }
}
