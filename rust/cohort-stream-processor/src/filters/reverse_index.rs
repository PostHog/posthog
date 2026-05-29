//! Per-team reverse indices and dedup set (TDD §2.7).
//!
//! [`TeamFiltersBuilder`] implements [`LeafSink`] so a cohort's tree parse populates the
//! indices in the same pass. The two `conditionHash`-keyed maps serve the two consumers:
//! Stage 1 (condition → leaf states to update) and Stage 2 / cleanup (condition → owning
//! cohorts). `Vec` (not `SmallVec`) is used for the value lists — `smallvec` is not a
//! workspace dependency and this is a cold 5-minute path (D-1).

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use metrics::counter;
use serde_json::Value;

use crate::filters::leaf_classifier::LeafDropReason;
use crate::filters::tree::{parse_cohort_tree, CohortTree, LeafSink};
use crate::filters::{CohortId, FilterError, TeamId};
use crate::observability::metrics::FILTER_CATALOG_SKIPPED_LEAVES;
use crate::stage1::key::LeafStateKey;

/// A team's frozen filter view: two reverse indices, the dedup set, and the parsed trees.
#[derive(Debug, Default)]
pub struct TeamFilters {
    /// `conditionHash → [LeafStateKey]`. On a HogVM match, Stage 1 enumerates which leaf
    /// states to update — one conditionHash can fan out to several windows/thresholds.
    pub by_condition_to_lsk: HashMap<[u8; 16], Vec<LeafStateKey>>,
    /// `conditionHash → [CohortId]`. Stage 2 / cleanup walks back from a condition to the
    /// cohorts that contain a leaf with it.
    pub by_condition_to_cohorts: HashMap<[u8; 16], Vec<CohortId>>,
    /// `conditionHash → bytecode`. PR 1.6's hot path fetches the program here, builds the globals,
    /// and calls [`crate::hogvm::evaluate`] once per unique conditionHash per event. One entry per
    /// conditionHash: the bytecode is identical across cohorts/leaves that share it, since
    /// `conditionHash = sha256(bytecode)`.
    pub by_condition_to_bytecode: HashMap<[u8; 16], Arc<Vec<Value>>>,
    /// Distinct conditionHashes for this team — preserves the per-team HogVM dedup
    /// (`manager.ts:109-113`): one execution per unique conditionHash per event.
    pub unique_condition_hashes: HashSet<[u8; 16]>,
    /// Parsed trees by cohort, retained for the Stage 2 re-walk.
    pub cohorts: HashMap<CohortId, CohortTree>,
}

/// Accumulates a team's filters across its cohorts (deduping index values via `HashSet`), then
/// [`freeze`](Self::freeze)s into an immutable [`TeamFilters`].
#[derive(Debug, Default)]
pub struct TeamFiltersBuilder {
    by_condition_to_lsk: HashMap<[u8; 16], HashSet<LeafStateKey>>,
    by_condition_to_cohorts: HashMap<[u8; 16], HashSet<CohortId>>,
    by_condition_to_bytecode: HashMap<[u8; 16], Arc<Vec<Value>>>,
    unique_condition_hashes: HashSet<[u8; 16]>,
    cohorts: HashMap<CohortId, CohortTree>,
}

impl LeafSink for TeamFiltersBuilder {
    fn record_state_keyed(
        &mut self,
        cohort_id: CohortId,
        condition_hash: [u8; 16],
        leaf_state_key: LeafStateKey,
        bytecode: &Arc<Vec<Value>>,
    ) {
        self.by_condition_to_lsk
            .entry(condition_hash)
            .or_default()
            .insert(leaf_state_key);
        self.by_condition_to_cohorts
            .entry(condition_hash)
            .or_default()
            .insert(cohort_id);
        // First-wins: every leaf sharing this conditionHash carries identical bytecode, so the Arc
        // is cloned at most once per conditionHash.
        self.by_condition_to_bytecode
            .entry(condition_hash)
            .or_insert_with(|| Arc::clone(bytecode));
        self.unique_condition_hashes.insert(condition_hash);
    }

    fn record_dropped(&mut self, reason: LeafDropReason) {
        counter!(FILTER_CATALOG_SKIPPED_LEAVES, "reason" => reason.as_str()).increment(1);
    }
}

impl TeamFiltersBuilder {
    /// Parse one cohort and fold it into the team's indices. A parse error (e.g. missing
    /// `properties`) is returned to the caller, which counts and skips the cohort.
    pub fn add_cohort(
        &mut self,
        cohort_id: CohortId,
        team_id: TeamId,
        filters: &Value,
    ) -> Result<(), FilterError> {
        let tree = parse_cohort_tree(cohort_id, team_id, filters, self)?;
        self.cohorts.insert(cohort_id, tree);
        Ok(())
    }

    /// Freeze into an immutable [`TeamFilters`], turning the dedup `HashSet`s into sorted
    /// `Vec`s for deterministic iteration.
    pub fn freeze(self) -> TeamFilters {
        TeamFilters {
            by_condition_to_lsk: sorted_vec_map(self.by_condition_to_lsk),
            by_condition_to_cohorts: sorted_vec_map(self.by_condition_to_cohorts),
            by_condition_to_bytecode: self.by_condition_to_bytecode,
            unique_condition_hashes: self.unique_condition_hashes,
            cohorts: self.cohorts,
        }
    }
}

/// Vec-ify a `conditionHash → HashSet<V>` map, sorting each value list for determinism.
fn sorted_vec_map<V: Ord>(map: HashMap<[u8; 16], HashSet<V>>) -> HashMap<[u8; 16], Vec<V>> {
    map.into_iter()
        .map(|(hash, set)| {
            let mut values: Vec<V> = set.into_iter().collect();
            values.sort_unstable();
            (hash, values)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const HASH: [u8; 16] = *b"0123456789abcdef";

    fn behavioral_bytecode() -> Value {
        json!(["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11])
    }

    fn behavioral_multiple(time_value: i64, operator_value: i64) -> Value {
        json!({
            "type": "behavioral",
            "value": "performed_event_multiple",
            "key": "$pageview",
            "time_value": time_value,
            "time_interval": "day",
            "operator": "gte",
            "operator_value": operator_value,
            "conditionHash": "0123456789abcdef",
            // Identical across windows: the bytecode encodes only the event matcher, so leaves
            // sharing a conditionHash share bytecode (conditionHash = sha256(bytecode)).
            "bytecode": behavioral_bytecode(),
        })
    }

    fn wrap(values: Vec<Value>) -> Value {
        json!({ "properties": { "type": "AND", "values": values } })
    }

    #[test]
    fn identical_leaves_dedupe_to_single_entries() {
        let mut builder = TeamFiltersBuilder::default();
        // Same cohort, the same leaf twice → one LSK, one cohort, one unique hash.
        let filters = wrap(vec![behavioral_multiple(7, 3), behavioral_multiple(7, 3)]);
        builder
            .add_cohort(CohortId(1), TeamId(7), &filters)
            .unwrap();
        let frozen = builder.freeze();

        assert_eq!(frozen.by_condition_to_lsk[&HASH].len(), 1);
        assert_eq!(frozen.by_condition_to_cohorts[&HASH], vec![CohortId(1)]);
        assert_eq!(frozen.unique_condition_hashes.len(), 1);
    }

    #[test]
    fn same_hash_different_windows_fan_out_to_distinct_leaf_state_keys() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_multiple(7, 3)]),
            )
            .unwrap();
        builder
            .add_cohort(
                CohortId(2),
                TeamId(7),
                &wrap(vec![behavioral_multiple(30, 5)]),
            )
            .unwrap();
        let frozen = builder.freeze();

        // Same conditionHash, but two distinct windows → two leaf state keys.
        assert_eq!(frozen.by_condition_to_lsk[&HASH].len(), 2);
        // Both owning cohorts recorded, sorted.
        assert_eq!(
            frozen.by_condition_to_cohorts[&HASH],
            vec![CohortId(1), CohortId(2)]
        );
        // Still one unique conditionHash (the HogVM dedup unit).
        assert_eq!(frozen.unique_condition_hashes.len(), 1);
        // ...and exactly one captured bytecode (first-wins; identical per conditionHash).
        assert_eq!(frozen.by_condition_to_bytecode.len(), 1);
    }

    #[test]
    fn bytecode_is_captured_under_its_condition_hash() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_multiple(7, 3)]),
            )
            .unwrap();
        let frozen = builder.freeze();

        let bytecode = frozen
            .by_condition_to_bytecode
            .get(&HASH)
            .expect("bytecode captured under the conditionHash");
        assert_eq!(bytecode.as_ref(), behavioral_bytecode().as_array().unwrap());
    }
}
