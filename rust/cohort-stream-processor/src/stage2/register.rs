//! Typed writes for the persisted single-leaf membership register.

use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::TeamId;
use crate::stage1::key::LeafStateKey;
use crate::stage1::transition::{LeafTransition, TransitionKind};
use crate::store::{Stage2Key, StagedBatch};

use super::Stage2State;

/// One complete `cf_stage2` register write for a single-leaf cohort.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct MembershipRegisterWrite {
    pub key: Stage2Key,
    pub state: Stage2State,
}

/// Person/leaf coordinates shared by every register write in one fan-out.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct MembershipRegisterSource {
    pub partition_id: u16,
    pub team_id: TeamId,
    pub person_id: Uuid,
    pub leaf_state_key: LeafStateKey,
}

/// Fan out one leaf's current membership to every single-leaf cohort backed by that leaf. The
/// returned iterator borrows `filters`, so it stays allocation-free on the hot per-transition path.
pub(crate) fn single_leaf_register_writes(
    filters: &TeamFilters,
    source: MembershipRegisterSource,
    in_cohort: bool,
    last_evaluated_at_ms: i64,
) -> impl Iterator<Item = MembershipRegisterWrite> + '_ {
    filters
        .by_lsk_to_single_leaf_cohorts
        .get(&source.leaf_state_key)
        .into_iter()
        .flatten()
        .map(move |cohort_id| MembershipRegisterWrite {
            key: Stage2Key {
                partition_id: source.partition_id,
                team_id: source.team_id.0 as u64,
                cohort_id: cohort_id.0 as u64,
                person_id: source.person_id,
            },
            state: Stage2State {
                in_cohort,
                last_evaluated_at_ms,
            },
        })
}

/// Fan out a membership transition as a complete register overwrite, including explicit `false`.
pub(crate) fn single_leaf_transition_register_writes<'a>(
    filters: &'a TeamFilters,
    partition_id: u16,
    transition: &LeafTransition,
    last_evaluated_at_ms: i64,
) -> impl Iterator<Item = MembershipRegisterWrite> + 'a {
    single_leaf_register_writes(
        filters,
        MembershipRegisterSource {
            partition_id,
            team_id: transition.team_id,
            person_id: transition.person_id,
            leaf_state_key: transition.leaf_state_key,
        },
        matches!(transition.kind, TransitionKind::Entered),
        last_evaluated_at_ms,
    )
}

/// Stage a register fan-out into `staged`, encoding each write into its `cf_stage2` row.
pub(crate) fn stage_register_writes(
    staged: &mut StagedBatch,
    writes: impl IntoIterator<Item = MembershipRegisterWrite>,
) {
    for write in writes {
        staged.put_stage2(&write.key, &write.state.encode());
    }
}

#[cfg(test)]
mod tests {
    use chrono_tz::UTC;
    use serde_json::json;

    use super::*;
    use crate::filters::{CohortId, TeamFiltersBuilder};

    #[test]
    fn fans_out_a_leaf_to_each_single_leaf_cohort_with_an_explicit_bit() {
        let mut builder = TeamFiltersBuilder::default();
        let cohort = json!({
            "properties": {
                "type": "AND",
                "values": [{
                    "type": "behavioral",
                    "key": "purchase",
                    "value": "performed_event",
                    "time_value": 7,
                    "time_interval": "day",
                    "conditionHash": "0123456789abcdef",
                    "bytecode": ["_H", 1, 32, "purchase", 32, "event", 1, 3, 11]
                }]
            }
        });
        builder.add_cohort(CohortId(1), TeamId(7), &cohort).unwrap();
        builder.add_cohort(CohortId(2), TeamId(7), &cohort).unwrap();
        let filters = builder.freeze(UTC);
        let leaf_state_key = *filters.by_lsk_to_single_leaf_cohorts.keys().next().unwrap();
        let person_id = Uuid::from_u128(42);

        let mut writes: Vec<_> = single_leaf_register_writes(
            &filters,
            MembershipRegisterSource {
                partition_id: 3,
                team_id: TeamId(7),
                person_id,
                leaf_state_key,
            },
            false,
            1_700_000_000_123,
        )
        .collect();
        writes.sort_unstable_by_key(|write| write.key.cohort_id);

        assert_eq!(writes.len(), 2);
        assert_eq!(writes[0].key.cohort_id, 1);
        assert_eq!(writes[1].key.cohort_id, 2);
        assert!(writes.iter().all(|write| {
            write.key.partition_id == 3
                && write.key.team_id == 7
                && write.key.person_id == person_id
                && write.state
                    == Stage2State {
                        in_cohort: false,
                        last_evaluated_at_ms: 1_700_000_000_123,
                    }
        }));
    }

    #[test]
    fn a_leaf_with_no_single_leaf_cohort_keyed_on_it_registers_nothing() {
        // A single-leaf cohort exists, but the queried leaf is not the one it is keyed on.
        let mut builder = TeamFiltersBuilder::default();
        let cohort = json!({
            "properties": {
                "type": "AND",
                "values": [{
                    "type": "behavioral",
                    "key": "purchase",
                    "value": "performed_event",
                    "time_value": 7,
                    "time_interval": "day",
                    "conditionHash": "0123456789abcdef",
                    "bytecode": ["_H", 1, 32, "purchase", 32, "event", 1, 3, 11]
                }]
            }
        });
        builder.add_cohort(CohortId(1), TeamId(7), &cohort).unwrap();
        let filters = builder.freeze(UTC);

        let writes: Vec<_> = single_leaf_register_writes(
            &filters,
            MembershipRegisterSource {
                partition_id: 3,
                team_id: TeamId(7),
                person_id: Uuid::from_u128(42),
                leaf_state_key: LeafStateKey([0xEE; 16]),
            },
            true,
            1_700_000_000_123,
        )
        .collect();

        assert!(writes.is_empty());
    }
}
