//! Per-team reverse indices and dedup set.
//!
//! [`TeamFiltersBuilder`] implements [`LeafSink`] so a cohort's tree parse populates the indices in
//! the same pass. The two `conditionHash`-keyed maps serve the two consumers: Stage 1 (condition →
//! leaf states to update) and Stage 2 / cleanup (condition → owning cohorts). Value lists are `Vec`
//! (not `SmallVec`): `smallvec` is not a workspace dependency and this is a cold 5-minute path.

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

/// Per-`LeafStateKey` worker metadata derived at freeze time: the state representation and (for
/// behavioral leaves) the eviction window, so the worker picks the apply path and computes
/// deadlines without re-deriving on the hot path. Two leaves sharing a `LeafStateKey` agree on this
/// by construction (the key hashes exactly the fields it depends on), so a last-write-wins insert
/// during the freeze walk is safe.
#[derive(Debug, Clone, Copy)]
pub struct LeafStateMeta {
    pub variant: StateVariant,
    pub window: Option<EvictionWindow>,
}

/// A team's frozen filter view: two reverse indices, the dedup set, and the parsed trees.
#[derive(Debug, Default)]
pub struct TeamFilters {
    /// `conditionHash → [LeafStateKey]`. On a HogVM match, Stage 1 enumerates which leaf states to
    /// update — one conditionHash can fan out to several windows/thresholds.
    pub by_condition_to_lsk: HashMap<[u8; 16], Vec<LeafStateKey>>,
    /// `conditionHash → [CohortId]` for the Stage 2 / cleanup walk back to owning cohorts.
    pub by_condition_to_cohorts: HashMap<[u8; 16], Vec<CohortId>>,
    /// `conditionHash → bytecode`, fed to [`crate::hogvm::evaluate`] once per unique conditionHash
    /// per event. One entry per conditionHash: bytecode is identical across leaves that share it,
    /// since `conditionHash = sha256(bytecode)`.
    pub by_condition_to_bytecode: HashMap<[u8; 16], Arc<Vec<Value>>>,
    /// Distinct conditionHashes for this team — preserves the per-team HogVM dedup of one execution
    /// per unique conditionHash per event (`manager.ts:109-113`).
    pub unique_condition_hashes: HashSet<[u8; 16]>,
    /// `LeafStateKey → LeafStateMeta`: the worker's per-leaf state contract (which variant to apply
    /// and, for behavioral leaves, the eviction window).
    pub by_lsk: HashMap<LeafStateKey, LeafStateMeta>,
    /// conditionHashes whose leaves are behavioral. Disjoint from
    /// [`person_property_conditions`](Self::person_property_conditions) — the two leaf kinds compile
    /// to different bytecode, so they never share a conditionHash. Mirrors the Node consumer's
    /// separate lists (`cdp-precalculated-filters.consumer.ts:217`).
    pub behavioral_conditions: HashSet<[u8; 16]>,
    /// conditionHashes whose leaves are person-property filters.
    pub person_property_conditions: HashSet<[u8; 16]>,
    /// `LeafStateKey → [CohortId]`, mapping a leaf flip directly to a cohort membership change. Only
    /// single-leaf cohorts qualify — that leaf's predicate *is* the cohort's membership, so the
    /// output producer emits a per-cohort change without Stage 2 composition. Keyed by
    /// [`LeafStateKey`] (not `condition_hash`) so a 7d and a 30d leaf sharing one conditionHash get
    /// distinct keys and never cross-fire.
    pub by_lsk_to_single_leaf_cohorts: HashMap<LeafStateKey, Vec<CohortId>>,
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
        // First-wins: leaves sharing a conditionHash carry identical bytecode, so the Arc is cloned
        // at most once per conditionHash.
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
    /// Parse one cohort and fold it into the team's indices. A parse error is returned to the
    /// caller, which counts and skips the cohort.
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

    /// Freeze into an immutable [`TeamFilters`]: sort the dedup `HashSet`s into `Vec`s for
    /// deterministic iteration and derive the per-leaf worker indices by walking the parsed trees.
    pub fn freeze(self) -> TeamFilters {
        let mut by_lsk = HashMap::new();
        let mut behavioral_conditions = HashSet::new();
        let mut person_property_conditions = HashSet::new();
        let mut by_lsk_to_single_leaf_cohorts: HashMap<LeafStateKey, Vec<CohortId>> =
            HashMap::new();
        for tree in self.cohorts.values() {
            collect_leaf_meta(
                &tree.root,
                &mut by_lsk,
                &mut behavioral_conditions,
                &mut person_property_conditions,
            );
            // Guard on `by_lsk` so a cohort is mapped only if its leaf actually carries worker
            // metadata — keeps the two maps consistent when `pick_state_variant` dropped a leaf.
            if let Some(lsk) = single_supported_leaf(&tree.root) {
                if by_lsk.contains_key(&lsk) {
                    by_lsk_to_single_leaf_cohorts
                        .entry(lsk)
                        .or_default()
                        .push(tree.cohort_id);
                }
            }
        }
        for cohorts in by_lsk_to_single_leaf_cohorts.values_mut() {
            cohorts.sort_unstable();
        }

        TeamFilters {
            by_condition_to_lsk: sorted_vec_map(self.by_condition_to_lsk),
            by_condition_to_cohorts: sorted_vec_map(self.by_condition_to_cohorts),
            by_condition_to_bytecode: self.by_condition_to_bytecode,
            unique_condition_hashes: self.unique_condition_hashes,
            by_lsk,
            behavioral_conditions,
            person_property_conditions,
            by_lsk_to_single_leaf_cohorts,
            cohorts: self.cohorts,
        }
    }
}

/// The [`LeafStateKey`] of a cohort whose filter tree is **exactly one** state-keyed leaf, or
/// [`None`] otherwise (zero leaves, ≥2 leaves, or a lone cohort-reference leaf — cohort refs have no
/// `leaf_state_key`). The single-leaf restriction is what makes a leaf transition equal a
/// whole-cohort membership change, before Stage 2 boolean composition exists.
fn single_supported_leaf(root: &FilterNode) -> Option<LeafStateKey> {
    /// `One` carries the single leaf's key (itself `None` for a cohort ref) so the final answer
    /// needs no second lookup.
    enum LeafCount {
        Zero,
        One(Option<LeafStateKey>),
        Many,
    }

    fn walk(node: &FilterNode, acc: LeafCount) -> LeafCount {
        match node {
            FilterNode::Leaf(leaf) => match acc {
                LeafCount::Zero => LeafCount::One(leaf.leaf_state_key()),
                LeafCount::One(_) | LeafCount::Many => LeafCount::Many,
            },
            FilterNode::Group { children, .. } => {
                let mut acc = acc;
                for child in children {
                    if matches!(acc, LeafCount::Many) {
                        return LeafCount::Many;
                    }
                    acc = walk(child, acc);
                }
                acc
            }
        }
    }

    match walk(root, LeafCount::Zero) {
        LeafCount::One(lsk) => lsk,
        LeafCount::Zero | LeafCount::Many => None,
    }
}

/// Recursively record each state-keyed leaf's [`LeafStateMeta`] and condition-kind membership.
/// Behavioral leaves re-run [`pick_state_variant`] to recover the variant + window; a kept leaf
/// always succeeds, since the classifier dropped any unsupported variant.
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

    /// A `performed_event` leaf on `$pageview` with a tunable window. The conditionHash does not
    /// encode the window, so different windows fan out to distinct LeafStateKeys under one hash.
    fn behavioral_performed_event(time_value: i64) -> Value {
        json!({
            "type": "behavioral",
            "value": "performed_event",
            "key": "$pageview",
            "time_value": time_value,
            "time_interval": "day",
            "conditionHash": "0123456789abcdef",
            // Identical across windows: leaves sharing a conditionHash share bytecode.
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

        assert_eq!(frozen.by_condition_to_lsk[&HASH].len(), 2);
        assert_eq!(
            frozen.by_condition_to_cohorts[&HASH],
            vec![CohortId(1), CohortId(2)]
        );
        assert_eq!(frozen.unique_condition_hashes.len(), 1);
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

        assert_eq!(frozen.by_lsk.len(), 2);

        let beh_lsk = frozen.by_condition_to_lsk[&HASH][0];
        let beh_meta = frozen.by_lsk[&beh_lsk];
        assert_eq!(beh_meta.variant, StateVariant::BehavioralSingle);
        assert_eq!(
            beh_meta.window,
            Some(EvictionWindow::Relative {
                seconds: 7 * 86_400
            })
        );

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

    fn cohort_ref() -> Value {
        json!({ "type": "cohort", "value": 99, "negation": false })
    }

    #[test]
    fn single_leaf_cohort_is_indexed_by_its_lsk() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        let frozen = builder.freeze();

        let lsk = frozen.by_condition_to_lsk[&HASH][0];
        assert_eq!(
            frozen.by_lsk_to_single_leaf_cohorts.get(&lsk),
            Some(&vec![CohortId(1)]),
        );
    }

    #[test]
    fn c1_two_single_leaf_cohorts_same_hash_different_windows_map_to_their_own_lsk() {
        // Reusing the conditionHash-keyed index would wrongly return both cohorts; the LSK-keyed
        // index splits them by window.
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

        assert_eq!(
            frozen.by_condition_to_cohorts[&HASH],
            vec![CohortId(1), CohortId(2)]
        );

        let lsks = &frozen.by_condition_to_lsk[&HASH];
        assert_eq!(lsks.len(), 2);
        let mut owners: Vec<Vec<CohortId>> = lsks
            .iter()
            .map(|lsk| frozen.by_lsk_to_single_leaf_cohorts[lsk].clone())
            .collect();
        owners.sort();
        assert_eq!(owners, vec![vec![CohortId(1)], vec![CohortId(2)]]);
    }

    #[test]
    fn identical_single_leaf_cohorts_share_one_lsk_sorted() {
        // Added out of order to prove the result is sorted.
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(2),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        let frozen = builder.freeze();

        let lsk = frozen.by_condition_to_lsk[&HASH][0];
        assert_eq!(
            frozen.by_lsk_to_single_leaf_cohorts[&lsk],
            vec![CohortId(1), CohortId(2)],
        );
    }

    #[test]
    fn multi_leaf_cohort_is_not_indexed() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7), person_leaf()]),
            )
            .unwrap();
        let frozen = builder.freeze();

        assert!(
            frozen.by_lsk_to_single_leaf_cohorts.is_empty(),
            "multi-leaf cohort contributes no single-leaf mapping",
        );
    }

    #[test]
    fn single_cohort_ref_cohort_is_not_indexed() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(7), &wrap(vec![cohort_ref()]))
            .unwrap();
        let frozen = builder.freeze();

        assert!(frozen.by_lsk_to_single_leaf_cohorts.is_empty());
    }

    #[test]
    fn nested_single_leaf_cohort_is_indexed() {
        let mut builder = TeamFiltersBuilder::default();
        let filters = json!({
            "properties": {
                "type": "OR",
                "values": [{ "type": "AND", "values": [behavioral_performed_event(7)] }],
            }
        });
        builder
            .add_cohort(CohortId(1), TeamId(7), &filters)
            .unwrap();
        let frozen = builder.freeze();

        let lsk = frozen.by_condition_to_lsk[&HASH][0];
        assert_eq!(
            frozen.by_lsk_to_single_leaf_cohorts[&lsk],
            vec![CohortId(1)]
        );
    }

    #[test]
    fn empty_all_dropped_cohort_is_not_indexed() {
        // The only leaf drops (no conditionHash), leaving an empty group → zero leaves → not indexed.
        let mut builder = TeamFiltersBuilder::default();
        let dropped =
            json!({ "type": "behavioral", "key": "$pageview", "value": "performed_event" });
        builder
            .add_cohort(CohortId(1), TeamId(7), &wrap(vec![dropped]))
            .unwrap();
        let frozen = builder.freeze();

        assert!(frozen.by_lsk_to_single_leaf_cohorts.is_empty());
        assert!(
            frozen.by_lsk.is_empty(),
            "the dropped leaf left no state metadata"
        );
    }
}
