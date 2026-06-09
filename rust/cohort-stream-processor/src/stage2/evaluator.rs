//! Pure Boolean composition over Stage 1 leaf membership.
//!
//! [`leaf_membership`] turns one leaf's stored state into a member bit; [`evaluate_tree`] folds those
//! bits up a cohort's AND/OR tree. Reached only for a `Stage2Composable` cohort (≥2 positive,
//! state-keyed, cohort-ref-free leaves), so composition is positive AND/OR only — the per-person
//! projection of the existing pipeline's set algebra (`INTERSECT DISTINCT` for AND, `UNION DISTINCT`
//! for OR in `hogql_cohort_query.py`): `person ∈ A∩B ⟺ bit_A ∧ bit_B`, `person ∈ A∪B ⟺ bit_A ∨ bit_B`.

use std::collections::HashMap;

use metrics::counter;

use crate::filters::reverse_index::LeafStateMeta;
use crate::filters::tree::{BoolOp, FilterNode};
use crate::observability::metrics::{STAGE2_STATE_DECODE_ERROR, STAGE2_UNEXPECTED_COHORT_REF};
use crate::stage1::key::LeafStateKey;
use crate::stage1::predicate::{compressed_predicate, daily_predicate, predicate};
use crate::stage1::state::{Stage1State, StateVariant};

/// Whether one leaf is currently a member.
///
/// Dispatches on `meta.variant`, **not** the stored state's tag: the op-less [`predicate`] returns
/// `false` for the bucket variants (no comparator), so a `performed_event_multiple` leaf is routed to
/// [`daily_predicate`] / [`compressed_predicate`] with the leaf's comparator. Absent state is `false`,
/// exact against the oracle (each per-condition `SELECT` requires ≥1 row via `GROUP BY person_id`, and
/// the bucket predicates enforce the matching `count >= 1` floor). A state tag that disagrees with
/// `meta.variant`, or a bucket leaf with no comparator, counts [`STAGE2_STATE_DECODE_ERROR`] and reads
/// as a non-member.
pub fn leaf_membership(state: Option<&Stage1State>, meta: &LeafStateMeta) -> bool {
    let Some(state) = state else {
        return false;
    };
    match meta.variant {
        StateVariant::BehavioralSingle | StateVariant::PersonProperty => predicate(state),
        StateVariant::BehavioralDailyBuckets => match (state, meta.predicate_op) {
            (Stage1State::BehavioralDailyBuckets { buckets, .. }, Some(op)) => {
                daily_predicate(buckets, op)
            }
            _ => {
                counter!(STAGE2_STATE_DECODE_ERROR).increment(1);
                false
            }
        },
        StateVariant::BehavioralCompressedHistory => match (state, meta.predicate_op) {
            (Stage1State::BehavioralCompressedHistory { entries, .. }, Some(op)) => {
                compressed_predicate(entries, op)
            }
            _ => {
                counter!(STAGE2_STATE_DECODE_ERROR).increment(1);
                false
            }
        },
    }
}

/// Fold a cohort's filter tree into one membership bit over `membership` (`LeafStateKey → member?`).
/// `And` is `all` and `Or` is `any`, so an empty group yields the operator's identity (`And` → `true`,
/// `Or` → `false`). A leaf absent from `membership` reads as `false`. A `CohortRef` leaf is unreachable
/// for a composable cohort; if one is reached it reads `false` and counts
/// [`STAGE2_UNEXPECTED_COHORT_REF`], surfacing a classification regression.
pub fn evaluate_tree(node: &FilterNode, membership: &HashMap<LeafStateKey, bool>) -> bool {
    match node {
        FilterNode::Group { op, children } => match op {
            BoolOp::And => children
                .iter()
                .all(|child| evaluate_tree(child, membership)),
            BoolOp::Or => children
                .iter()
                .any(|child| evaluate_tree(child, membership)),
        },
        FilterNode::Leaf(leaf) => match leaf.leaf_state_key() {
            Some(lsk) => membership.get(&lsk).copied().unwrap_or(false),
            None => {
                counter!(STAGE2_UNEXPECTED_COHORT_REF).increment(1);
                false
            }
        },
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use serde_json::Value;

    use super::*;
    use crate::filters::tree::{CohortLeaf, CohortRefLeafConfig, PersonLeafConfig};
    use crate::filters::CohortId;
    use crate::stage1::pick_state::PredicateOp;

    fn lsk(byte: u8) -> LeafStateKey {
        LeafStateKey([byte; 16])
    }

    /// A person-property leaf node carrying `key` so the tree walk can route it to `membership`.
    fn person_leaf(key: LeafStateKey) -> FilterNode {
        FilterNode::Leaf(CohortLeaf::PersonProperty(PersonLeafConfig {
            condition_hash: key.0,
            leaf_state_key: key,
            bytecode: Arc::new(Vec::new()),
            raw: Value::Null,
        }))
    }

    fn cohort_ref_leaf() -> FilterNode {
        FilterNode::Leaf(CohortLeaf::CohortRef(CohortRefLeafConfig {
            referenced_cohort_id: CohortId(99),
            negation: false,
        }))
    }

    fn group(op: BoolOp, children: Vec<FilterNode>) -> FilterNode {
        FilterNode::Group { op, children }
    }

    fn person_meta() -> LeafStateMeta {
        LeafStateMeta {
            variant: StateVariant::PersonProperty,
            condition_hash: [0; 16],
            window: None,
            window_days: None,
            predicate_op: None,
        }
    }

    fn daily_meta(op: PredicateOp) -> LeafStateMeta {
        LeafStateMeta {
            variant: StateVariant::BehavioralDailyBuckets,
            condition_hash: [0; 16],
            window: None,
            window_days: Some(7),
            predicate_op: Some(op),
        }
    }

    // ── leaf_membership ──────────────────────────────────────────────────────

    #[test]
    fn leaf_membership_absent_state_is_false() {
        assert!(!leaf_membership(None, &person_meta()));
    }

    #[test]
    fn leaf_membership_reads_the_op_less_bit() {
        let yes = Stage1State::PersonProperty {
            matches: true,
            last_updated_at_ms: 1,
            last_updated_offset: 2,
        };
        let no = Stage1State::PersonProperty {
            matches: false,
            last_updated_at_ms: 1,
            last_updated_offset: 2,
        };
        assert!(leaf_membership(Some(&yes), &person_meta()));
        assert!(!leaf_membership(Some(&no), &person_meta()));

        let single = LeafStateMeta {
            variant: StateVariant::BehavioralSingle,
            ..person_meta()
        };
        let matched = Stage1State::BehavioralSingle {
            has_match: true,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: 2,
        };
        assert!(leaf_membership(Some(&matched), &single));
    }

    #[test]
    fn leaf_membership_dispatches_a_daily_bucket_leaf_through_its_comparator() {
        // Dispatch must apply the leaf's comparator to the bucket sum, not the op-less `predicate`
        // (which reads any bucket state as false). Buckets sum to 3.
        let state = Stage1State::BehavioralDailyBuckets {
            buckets: vec![1, 0, 2],
            window_start_day: 20_600,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: 2,
        };
        assert!(
            leaf_membership(Some(&state), &daily_meta(PredicateOp::Gte(3))),
            "count 3 satisfies gte 3 — dispatch reached daily_predicate",
        );
        assert!(!leaf_membership(
            Some(&state),
            &daily_meta(PredicateOp::Gte(4))
        ));
        assert!(
            leaf_membership(Some(&state), &daily_meta(PredicateOp::Lte(3))),
            "lte 3 holds (and the count>=1 floor is satisfied)",
        );
    }

    #[test]
    fn leaf_membership_dispatches_a_compressed_leaf_through_its_comparator() {
        let state = Stage1State::BehavioralCompressedHistory {
            entries: vec![(20_240, 2), (20_400, 1)],
            window_start_day: 20_240,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: 2,
        };
        let meta = LeafStateMeta {
            variant: StateVariant::BehavioralCompressedHistory,
            window_days: Some(365),
            predicate_op: Some(PredicateOp::Gte(3)),
            ..person_meta()
        };
        assert!(
            leaf_membership(Some(&state), &meta),
            "count 3 satisfies gte 3"
        );
    }

    #[test]
    fn leaf_membership_variant_state_desync_reads_false() {
        // meta says daily buckets, but the stored value is a single bit: a desync reads as a
        // non-member rather than silently a member (the single bit is `true`).
        let mismatched = Stage1State::BehavioralSingle {
            has_match: true,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: 2,
        };
        assert!(!leaf_membership(
            Some(&mismatched),
            &daily_meta(PredicateOp::Gte(1)),
        ));
    }

    #[test]
    fn leaf_membership_daily_missing_op_reads_false() {
        let meta = LeafStateMeta {
            predicate_op: None,
            ..daily_meta(PredicateOp::Gte(1))
        };
        let state = Stage1State::BehavioralDailyBuckets {
            buckets: vec![5, 0],
            window_start_day: 1,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: 2,
        };
        assert!(!leaf_membership(Some(&state), &meta));
    }

    // ── evaluate_tree ────────────────────────────────────────────────────────

    #[test]
    fn evaluate_and_is_the_conjunction() {
        let tree = group(BoolOp::And, vec![person_leaf(lsk(1)), person_leaf(lsk(2))]);
        let both = HashMap::from([(lsk(1), true), (lsk(2), true)]);
        let one = HashMap::from([(lsk(1), true), (lsk(2), false)]);
        assert!(evaluate_tree(&tree, &both));
        assert!(
            !evaluate_tree(&tree, &one),
            "AND fails when either leaf is false"
        );
    }

    #[test]
    fn evaluate_or_is_the_disjunction() {
        let tree = group(BoolOp::Or, vec![person_leaf(lsk(1)), person_leaf(lsk(2))]);
        let one = HashMap::from([(lsk(1), false), (lsk(2), true)]);
        let neither = HashMap::from([(lsk(1), false), (lsk(2), false)]);
        assert!(
            evaluate_tree(&tree, &one),
            "OR holds when either leaf is true"
        );
        assert!(!evaluate_tree(&tree, &neither));
    }

    #[test]
    fn evaluate_nested_groups_compose() {
        // AND( OR(a, b), c ): true iff (a ∨ b) ∧ c.
        let tree = group(
            BoolOp::And,
            vec![
                group(BoolOp::Or, vec![person_leaf(lsk(1)), person_leaf(lsk(2))]),
                person_leaf(lsk(3)),
            ],
        );
        let sat = HashMap::from([(lsk(1), false), (lsk(2), true), (lsk(3), true)]);
        let c_false = HashMap::from([(lsk(1), true), (lsk(2), true), (lsk(3), false)]);
        assert!(evaluate_tree(&tree, &sat));
        assert!(!evaluate_tree(&tree, &c_false), "the outer AND needs c");
    }

    #[test]
    fn evaluate_empty_group_identities() {
        let membership = HashMap::new();
        assert!(
            evaluate_tree(&group(BoolOp::And, vec![]), &membership),
            "an empty AND is the conjunction identity (true)",
        );
        assert!(
            !evaluate_tree(&group(BoolOp::Or, vec![]), &membership),
            "an empty OR is the disjunction identity (false)",
        );
    }

    #[test]
    fn evaluate_duplicate_leaf_collapses() {
        // AND(L, L) ≡ AND(L): the membership map collapses the duplicate to one key, and the leaf's
        // bit decides the whole cohort.
        let tree = group(BoolOp::And, vec![person_leaf(lsk(1)), person_leaf(lsk(1))]);
        assert!(evaluate_tree(&tree, &HashMap::from([(lsk(1), true)])));
        assert!(!evaluate_tree(&tree, &HashMap::from([(lsk(1), false)])));
    }

    #[test]
    fn evaluate_absent_leaf_reads_false() {
        // lsk(2) is not in the map (its state was absent / undecodable): the AND fails.
        let tree = group(BoolOp::And, vec![person_leaf(lsk(1)), person_leaf(lsk(2))]);
        assert!(!evaluate_tree(&tree, &HashMap::from([(lsk(1), true)])));
    }

    #[test]
    fn evaluate_unexpected_cohort_ref_reads_false() {
        // A cohort-ref leaf cannot appear in a composable cohort; if one does, it reads false rather
        // than mis-composing (and bumps stage2_unexpected_cohort_ref_total).
        let tree = group(BoolOp::Or, vec![person_leaf(lsk(1)), cohort_ref_leaf()]);
        assert!(
            evaluate_tree(&tree, &HashMap::from([(lsk(1), true)])),
            "the OR still holds on the real leaf",
        );
        assert!(
            !evaluate_tree(&tree, &HashMap::from([(lsk(1), false)])),
            "the cohort ref reads false, so OR(false, ref) is false",
        );
    }
}
