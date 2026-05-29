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
use crate::filters::tree::{parse_cohort_tree, CohortLeaf, CohortTree, FilterNode, LeafSink};
use crate::filters::{CohortId, FilterError, TeamId};
use crate::observability::metrics::FILTER_CATALOG_SKIPPED_LEAVES;
use crate::stage1::key::LeafStateKey;
use crate::stage1::pick_state::{pick_state_variant, EvictionWindow};
use crate::stage1::state::StateVariant;

/// Per-`LeafStateKey` worker metadata, derived from a leaf's config at freeze time: the state
/// representation and (for behavioral leaves) the eviction window. The worker reads it to pick the
/// apply path and compute deadlines without re-deriving anything on the hot path. Two leaves that
/// share a `LeafStateKey` agree on this by construction (the key hashes exactly the fields it
/// depends on), so a last-write-wins insert during the freeze walk is safe.
#[derive(Debug, Clone, Copy)]
pub struct LeafStateMeta {
    pub variant: StateVariant,
    pub window: Option<EvictionWindow>,
}

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
    /// `LeafStateKey → LeafStateMeta`. The worker's per-leaf state contract: which variant to apply
    /// and, for behavioral leaves, the eviction window. Built in [`freeze`](TeamFiltersBuilder::freeze)
    /// by walking the parsed trees (no change to [`LeafSink`]).
    pub by_lsk: HashMap<LeafStateKey, LeafStateMeta>,
    /// conditionHashes whose leaves are behavioral (`performed_event`). The worker builds the
    /// behavioral globals and runs these only when this set is non-empty. Disjoint from
    /// [`person_property_conditions`](Self::person_property_conditions) — the two leaf kinds compile
    /// to different bytecode, so they never share a conditionHash. Mirrors the Node consumer's
    /// separate behavioral / person-property lists (`cdp-precalculated-filters.consumer.ts:217`).
    pub behavioral_conditions: HashSet<[u8; 16]>,
    /// conditionHashes whose leaves are person-property filters.
    pub person_property_conditions: HashSet<[u8; 16]>,
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
    /// `Vec`s for deterministic iteration and deriving the per-leaf worker indices
    /// ([`by_lsk`](TeamFilters::by_lsk) + the two condition-kind sets) by walking the parsed trees.
    pub fn freeze(self) -> TeamFilters {
        let mut by_lsk = HashMap::new();
        let mut behavioral_conditions = HashSet::new();
        let mut person_property_conditions = HashSet::new();
        for tree in self.cohorts.values() {
            collect_leaf_meta(
                &tree.root,
                &mut by_lsk,
                &mut behavioral_conditions,
                &mut person_property_conditions,
            );
        }

        TeamFilters {
            by_condition_to_lsk: sorted_vec_map(self.by_condition_to_lsk),
            by_condition_to_cohorts: sorted_vec_map(self.by_condition_to_cohorts),
            by_condition_to_bytecode: self.by_condition_to_bytecode,
            unique_condition_hashes: self.unique_condition_hashes,
            by_lsk,
            behavioral_conditions,
            person_property_conditions,
            cohorts: self.cohorts,
        }
    }
}

/// Recursively record each state-keyed leaf's [`LeafStateMeta`] and condition-kind membership.
/// Behavioral leaves re-run [`pick_state_variant`] (a cold 5-minute path) to recover the variant +
/// window; a kept leaf always succeeds, since the classifier dropped any unsupported variant.
fn collect_leaf_meta(
    node: &FilterNode,
    by_lsk: &mut HashMap<LeafStateKey, LeafStateMeta>,
    behavioral_conditions: &mut HashSet<[u8; 16]>,
    person_property_conditions: &mut HashSet<[u8; 16]>,
) {
    match node {
        FilterNode::Group { children, .. } => {
            for child in children {
                collect_leaf_meta(
                    child,
                    by_lsk,
                    behavioral_conditions,
                    person_property_conditions,
                );
            }
        }
        FilterNode::Leaf(CohortLeaf::Behavioral(leaf)) => {
            if let Ok((variant, window)) = pick_state_variant(leaf) {
                by_lsk.insert(leaf.leaf_state_key, LeafStateMeta { variant, window });
                behavioral_conditions.insert(leaf.condition_hash);
            }
        }
        FilterNode::Leaf(CohortLeaf::PersonProperty(leaf)) => {
            by_lsk.insert(
                leaf.leaf_state_key,
                LeafStateMeta {
                    variant: StateVariant::PersonProperty,
                    window: None,
                },
            );
            person_property_conditions.insert(leaf.condition_hash);
        }
        FilterNode::Leaf(CohortLeaf::CohortRef(_)) => {}
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

    const PERSON_HASH: [u8; 16] = *b"fedcba9876543210";

    fn behavioral_bytecode() -> Value {
        json!(["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11])
    }

    /// A `performed_event` leaf on `$pageview` with a tunable window — the only field of the three
    /// (value/window) that the conditionHash does not encode, so different windows fan out to
    /// distinct LeafStateKeys under one conditionHash.
    fn behavioral_performed_event(time_value: i64) -> Value {
        json!({
            "type": "behavioral",
            "value": "performed_event",
            "key": "$pageview",
            "time_value": time_value,
            "time_interval": "day",
            "conditionHash": "0123456789abcdef",
            // Identical across windows: the bytecode encodes only the event matcher, so leaves
            // sharing a conditionHash share bytecode (conditionHash = sha256(bytecode)).
            "bytecode": behavioral_bytecode(),
        })
    }

    fn person_leaf() -> Value {
        json!({
            "type": "person",
            "key": "email",
            "value": "a@b.com",
            "operator": "exact",
            "conditionHash": "fedcba9876543210",
            "bytecode": ["_H", 1, 32, "a@b.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        })
    }

    fn wrap(values: Vec<Value>) -> Value {
        json!({ "properties": { "type": "AND", "values": values } })
    }

    #[test]
    fn identical_leaves_dedupe_to_single_entries() {
        let mut builder = TeamFiltersBuilder::default();
        // Same cohort, the same leaf twice → one LSK, one cohort, one unique hash.
        let filters = wrap(vec![
            behavioral_performed_event(7),
            behavioral_performed_event(7),
        ]);
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
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        builder
            .add_cohort(
                CohortId(2),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(30)]),
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
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        let frozen = builder.freeze();

        let bytecode = frozen
            .by_condition_to_bytecode
            .get(&HASH)
            .expect("bytecode captured under the conditionHash");
        assert_eq!(bytecode.as_ref(), behavioral_bytecode().as_array().unwrap());
    }

    #[test]
    fn freeze_builds_by_lsk_with_variant_and_window() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7), person_leaf()]),
            )
            .unwrap();
        let frozen = builder.freeze();

        // One behavioral + one person leaf, each with its own LeafStateMeta.
        assert_eq!(frozen.by_lsk.len(), 2);

        // The behavioral leaf's LSK carries BehavioralSingle + a 7-day relative window.
        let beh_lsk = frozen.by_condition_to_lsk[&HASH][0];
        let beh_meta = frozen.by_lsk[&beh_lsk];
        assert_eq!(beh_meta.variant, StateVariant::BehavioralSingle);
        assert_eq!(
            beh_meta.window,
            Some(EvictionWindow::Relative {
                seconds: 7 * 86_400
            })
        );

        // The person leaf's LSK is its conditionHash, carrying PersonProperty + no window.
        let per_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        let per_meta = frozen.by_lsk[&per_lsk];
        assert_eq!(per_meta.variant, StateVariant::PersonProperty);
        assert_eq!(per_meta.window, None);
    }

    #[test]
    fn freeze_partitions_conditions_by_kind() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7), person_leaf()]),
            )
            .unwrap();
        let frozen = builder.freeze();

        assert_eq!(
            frozen.behavioral_conditions,
            HashSet::from([HASH]),
            "the performed_event conditionHash is behavioral",
        );
        assert_eq!(
            frozen.person_property_conditions,
            HashSet::from([PERSON_HASH]),
            "the person conditionHash is person-property",
        );
        // Disjoint by construction (different bytecode → different hash).
        assert!(frozen
            .behavioral_conditions
            .is_disjoint(&frozen.person_property_conditions));
    }

    #[test]
    fn freeze_recurses_into_nested_groups() {
        // by_lsk must be populated from leaves nested under inner groups, not just the root.
        let mut builder = TeamFiltersBuilder::default();
        let filters = json!({
            "properties": {
                "type": "OR",
                "values": [{
                    "type": "AND",
                    "values": [behavioral_performed_event(7)],
                }],
            }
        });
        builder
            .add_cohort(CohortId(1), TeamId(7), &filters)
            .unwrap();
        let frozen = builder.freeze();

        assert_eq!(frozen.by_lsk.len(), 1);
        assert_eq!(frozen.behavioral_conditions, HashSet::from([HASH]));
    }
}
