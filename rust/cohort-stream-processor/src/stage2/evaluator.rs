//! Pure Boolean composition over Stage 1 leaf membership.

use std::collections::HashMap;

use metrics::counter;

use crate::filters::reverse_index::LeafStateMeta;
use crate::filters::tree::{BoolOp, CohortLeaf, FilterNode};
use crate::filters::CohortId;
use crate::observability::metrics::{STAGE2_STATE_DECODE_ERROR, STAGE2_UNEXPECTED_COHORT_REF};
use crate::stage1::key::LeafStateKey;
use crate::stage1::predicate::{compressed_predicate, daily_predicate, predicate};
use crate::stage1::state::{Stage1State, StateVariant};

/// Whether one leaf is currently a member, from its `cf_behavioral` state. Absent state is `false`.
///
/// Person-property leaves are NOT resolved here — their membership lives in the durable
/// [`PersonRecord`](crate::stage1::PersonRecord), read directly by the Stage 2 resolver. A
/// `PersonProperty` meta reaching this function is a desync (no person-property state is ever stored in
/// `cf_behavioral`), counted and read as a non-member — loud, never a silent member.
pub fn leaf_membership(state: Option<&Stage1State>, meta: &LeafStateMeta) -> bool {
    let Some(state) = state else {
        return false;
    };
    match meta.variant {
        StateVariant::BehavioralSingle => predicate(state),
        StateVariant::PersonProperty => {
            counter!(STAGE2_STATE_DECODE_ERROR).increment(1);
            false
        }
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

/// Fold a cohort's filter tree into one membership bit. State-keyed leaves read `membership`,
/// cohort-reference leaves read `ref_membership`; an absent entry reads `false`, then the leaf's
/// negation applies (so a negated absent leaf reads `true`).
pub fn evaluate_tree(
    node: &FilterNode,
    membership: &HashMap<LeafStateKey, bool>,
    ref_membership: &HashMap<CohortId, bool>,
) -> bool {
    match node {
        FilterNode::Group { op, children } => match op {
            BoolOp::And => children
                .iter()
                .all(|child| evaluate_tree(child, membership, ref_membership)),
            BoolOp::Or => children
                .iter()
                .any(|child| evaluate_tree(child, membership, ref_membership)),
        },
        FilterNode::Leaf(CohortLeaf::CohortRef(config)) => {
            let referent = ref_membership.get(&config.referenced_cohort_id).copied();
            if referent.is_none() {
                // The caller fills `ref_membership` for every ref leaf, so a miss signals a bug.
                counter!(STAGE2_UNEXPECTED_COHORT_REF).increment(1);
            }
            referent.unwrap_or(false) ^ config.negation
        }
        FilterNode::Leaf(leaf) => {
            let bit = leaf
                .leaf_state_key()
                .and_then(|lsk| membership.get(&lsk).copied())
                .unwrap_or(false);
            bit ^ leaf.negated()
        }
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
    use crate::stage2::eligibility::condition_negation;

    fn lsk(byte: u8) -> LeafStateKey {
        LeafStateKey([byte; 16])
    }

    fn person_leaf(key: LeafStateKey) -> FilterNode {
        person_leaf_neg(key, false)
    }

    fn person_leaf_neg(key: LeafStateKey, negated: bool) -> FilterNode {
        FilterNode::Leaf(CohortLeaf::PersonProperty(PersonLeafConfig {
            condition_hash: key.0,
            leaf_state_key: key,
            bytecode: Arc::new(Vec::new()),
            raw: Value::Null,
            negated,
        }))
    }

    fn cohort_ref_leaf() -> FilterNode {
        cohort_ref_leaf_neg(CohortId(99), false)
    }

    fn cohort_ref_leaf_neg(referenced: CohortId, negation: bool) -> FilterNode {
        FilterNode::Leaf(CohortLeaf::CohortRef(CohortRefLeafConfig {
            referenced_cohort_id: referenced,
            negation,
        }))
    }

    fn no_refs() -> HashMap<CohortId, bool> {
        HashMap::new()
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

    #[test]
    fn leaf_membership_absent_state_is_false() {
        assert!(!leaf_membership(None, &person_meta()));
    }

    #[test]
    fn leaf_membership_reads_the_behavioral_single_bit() {
        let single = LeafStateMeta {
            variant: StateVariant::BehavioralSingle,
            ..person_meta()
        };
        let matched = Stage1State::BehavioralSingle {
            has_match: true,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: 2,
        };
        let unmatched = Stage1State::BehavioralSingle {
            has_match: false,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: 2,
        };
        assert!(leaf_membership(Some(&matched), &single));
        assert!(!leaf_membership(Some(&unmatched), &single));
    }

    #[test]
    fn leaf_membership_person_property_meta_reads_non_member() {
        let matched = Stage1State::BehavioralSingle {
            has_match: true,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: 2,
        };
        assert!(!leaf_membership(Some(&matched), &person_meta()));
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

    #[test]
    fn evaluate_and_is_the_conjunction() {
        let tree = group(BoolOp::And, vec![person_leaf(lsk(1)), person_leaf(lsk(2))]);
        let both = HashMap::from([(lsk(1), true), (lsk(2), true)]);
        let one = HashMap::from([(lsk(1), true), (lsk(2), false)]);
        assert!(evaluate_tree(&tree, &both, &no_refs()));
        assert!(
            !evaluate_tree(&tree, &one, &no_refs()),
            "AND fails when either leaf is false"
        );
    }

    #[test]
    fn evaluate_or_is_the_disjunction() {
        let tree = group(BoolOp::Or, vec![person_leaf(lsk(1)), person_leaf(lsk(2))]);
        let one = HashMap::from([(lsk(1), false), (lsk(2), true)]);
        let neither = HashMap::from([(lsk(1), false), (lsk(2), false)]);
        assert!(
            evaluate_tree(&tree, &one, &no_refs()),
            "OR holds when either leaf is true"
        );
        assert!(!evaluate_tree(&tree, &neither, &no_refs()));
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
        assert!(evaluate_tree(&tree, &sat, &no_refs()));
        assert!(
            !evaluate_tree(&tree, &c_false, &no_refs()),
            "the outer AND needs c"
        );
    }

    #[test]
    fn evaluate_empty_group_identities() {
        let membership = HashMap::new();
        assert!(
            evaluate_tree(&group(BoolOp::And, vec![]), &membership, &no_refs()),
            "an empty AND is the conjunction identity (true)",
        );
        assert!(
            !evaluate_tree(&group(BoolOp::Or, vec![]), &membership, &no_refs()),
            "an empty OR is the disjunction identity (false)",
        );
    }

    #[test]
    fn evaluate_duplicate_leaf_collapses() {
        // AND(L, L) ≡ AND(L): the membership map collapses the duplicate to one key, and the leaf's
        // bit decides the whole cohort.
        let tree = group(BoolOp::And, vec![person_leaf(lsk(1)), person_leaf(lsk(1))]);
        assert!(evaluate_tree(
            &tree,
            &HashMap::from([(lsk(1), true)]),
            &no_refs()
        ));
        assert!(!evaluate_tree(
            &tree,
            &HashMap::from([(lsk(1), false)]),
            &no_refs()
        ));
    }

    #[test]
    fn evaluate_absent_leaf_reads_false() {
        // lsk(2) is not in the map (its state was absent / undecodable): the AND fails.
        let tree = group(BoolOp::And, vec![person_leaf(lsk(1)), person_leaf(lsk(2))]);
        assert!(!evaluate_tree(
            &tree,
            &HashMap::from([(lsk(1), true)]),
            &no_refs()
        ));
    }

    #[test]
    fn cohort_ref_leaf_reads_the_referent_bit_from_ref_membership() {
        let tree = group(BoolOp::Or, vec![person_leaf(lsk(1)), cohort_ref_leaf()]);
        let off = HashMap::from([(lsk(1), false)]);
        assert!(
            evaluate_tree(&tree, &off, &HashMap::from([(CohortId(99), true)])),
            "referent 99 is a member → OR(false, ref) holds",
        );
        assert!(
            !evaluate_tree(&tree, &off, &HashMap::from([(CohortId(99), false)])),
            "referent 99 is a non-member → OR(false, ref) is false",
        );
    }

    #[test]
    fn cohort_ref_leaf_absent_referent_reads_false() {
        let tree = group(BoolOp::Or, vec![person_leaf(lsk(1)), cohort_ref_leaf()]);
        assert!(!evaluate_tree(
            &tree,
            &HashMap::from([(lsk(1), false)]),
            &no_refs(),
        ));
        assert!(
            evaluate_tree(&tree, &HashMap::from([(lsk(1), true)]), &no_refs()),
            "the real leaf still carries the OR",
        );
    }

    #[test]
    fn negated_cohort_ref_absent_referent_reads_true() {
        let tree = group(
            BoolOp::And,
            vec![person_leaf(lsk(1)), cohort_ref_leaf_neg(CohortId(99), true)],
        );
        assert!(
            evaluate_tree(&tree, &HashMap::from([(lsk(1), true)]), &no_refs()),
            "absent negated referent reads true via false ^ true",
        );
    }

    #[test]
    fn negated_cohort_ref_present_member_reads_false() {
        let tree = group(
            BoolOp::And,
            vec![person_leaf(lsk(1)), cohort_ref_leaf_neg(CohortId(99), true)],
        );
        assert!(
            !evaluate_tree(
                &tree,
                &HashMap::from([(lsk(1), true)]),
                &HashMap::from([(CohortId(99), true)]),
            ),
            "referent is a member → ¬member = false → AND fails",
        );
    }

    #[test]
    fn cohort_ref_and_state_keyed_leaf_compose_in_one_tree() {
        let tree = group(BoolOp::And, vec![person_leaf(lsk(1)), cohort_ref_leaf()]);
        assert!(evaluate_tree(
            &tree,
            &HashMap::from([(lsk(1), true)]),
            &HashMap::from([(CohortId(99), true)]),
        ));
        assert!(
            !evaluate_tree(
                &tree,
                &HashMap::from([(lsk(1), true)]),
                &HashMap::from([(CohortId(99), false)]),
            ),
            "the referent being a non-member fails the AND",
        );
    }

    #[test]
    fn xor_truth_table_for_and_a_neg_b() {
        let tree = group(
            BoolOp::And,
            vec![person_leaf(lsk(1)), person_leaf_neg(lsk(2), true)],
        );
        let cases = [
            ((true, true), false),   // A ∧ ¬B: true ∧ false = false
            ((true, false), true),   // A ∧ ¬B: true ∧ true = true
            ((false, true), false),  // A ∧ ¬B: false ∧ false = false
            ((false, false), false), // A ∧ ¬B: false ∧ true = false
        ];
        for ((a, b), expected) in cases {
            let map = HashMap::from([(lsk(1), a), (lsk(2), b)]);
            assert_eq!(
                evaluate_tree(&tree, &map, &no_refs()),
                expected,
                "AND(A={a}, ¬B={b}) should be {expected}",
            );
        }
    }

    #[test]
    fn negated_absent_leaf_reads_true() {
        let tree = group(
            BoolOp::And,
            vec![person_leaf(lsk(1)), person_leaf_neg(lsk(2), true)],
        );
        assert!(
            evaluate_tree(&tree, &HashMap::from([(lsk(1), true)]), &no_refs()),
            "absent negated leaf reads true via false ^ true",
        );
    }

    #[test]
    fn and_a_neg_a_same_lsk_always_false() {
        // Both leaves share one LSK but opposite negation bits → always false.
        let tree = group(
            BoolOp::And,
            vec![person_leaf(lsk(1)), person_leaf_neg(lsk(1), true)],
        );
        assert!(
            !evaluate_tree(&tree, &HashMap::from([(lsk(1), true)]), &no_refs()),
            "true AND (true ^ true = false) = false",
        );
        assert!(
            !evaluate_tree(&tree, &HashMap::from([(lsk(1), false)]), &no_refs()),
            "false AND (false ^ true = true) = false",
        );
    }

    #[test]
    fn nested_and_c_or_a_neg_b() {
        let tree = group(
            BoolOp::And,
            vec![
                person_leaf(lsk(3)),
                group(
                    BoolOp::Or,
                    vec![person_leaf(lsk(1)), person_leaf_neg(lsk(2), true)],
                ),
            ],
        );
        // C=true, A=false, B=false → OR(false, true) = true → AND(true, true) = true.
        assert!(evaluate_tree(
            &tree,
            &HashMap::from([(lsk(3), true), (lsk(1), false), (lsk(2), false)]),
            &no_refs(),
        ));
        // C=true, A=false, B=true → OR(false, false) = false → AND(true, false) = false.
        assert!(!evaluate_tree(
            &tree,
            &HashMap::from([(lsk(3), true), (lsk(1), false), (lsk(2), true)]),
            &no_refs(),
        ));
        // C=false → AND fails regardless.
        assert!(!evaluate_tree(
            &tree,
            &HashMap::from([(lsk(3), false), (lsk(1), true), (lsk(2), false)]),
            &no_refs(),
        ));
    }

    #[test]
    fn all_absent_invariant_exhaustive() {
        // For every non-root-negated depth-≤2 tree with ≤3 leaves, both ops × all negation
        // assignments: evaluate_tree with an empty map must return false.
        let empty = HashMap::new();
        let ops = [BoolOp::And, BoolOp::Or];
        let negs = [false, true];

        // Depth 1: single leaf under a group.
        for &neg in &negs {
            let leaf = person_leaf_neg(lsk(1), neg);
            for &op in &ops {
                let tree = group(op, vec![leaf.clone()]);
                if !condition_negation(&tree) {
                    assert!(
                        !evaluate_tree(&tree, &empty, &no_refs()),
                        "depth=1, op={op:?}, neg={neg}",
                    );
                }
            }
        }

        // Depth 1: two leaves.
        for &neg_a in &negs {
            for &neg_b in &negs {
                let a = person_leaf_neg(lsk(1), neg_a);
                let b = person_leaf_neg(lsk(2), neg_b);
                for &op in &ops {
                    let tree = group(op, vec![a.clone(), b.clone()]);
                    if !condition_negation(&tree) {
                        assert!(
                            !evaluate_tree(&tree, &empty, &no_refs()),
                            "depth=1, op={op:?}, neg_a={neg_a}, neg_b={neg_b}",
                        );
                    }
                }
            }
        }

        // Depth 2: outer(inner(leaf, leaf), leaf) — 3 leaves, 2 group ops, 8 neg combos.
        for &neg_a in &negs {
            for &neg_b in &negs {
                for &neg_c in &negs {
                    let a = person_leaf_neg(lsk(1), neg_a);
                    let b = person_leaf_neg(lsk(2), neg_b);
                    let c = person_leaf_neg(lsk(3), neg_c);
                    for &inner_op in &ops {
                        for &outer_op in &ops {
                            let tree = group(
                                outer_op,
                                vec![group(inner_op, vec![a.clone(), b.clone()]), c.clone()],
                            );
                            if !condition_negation(&tree) {
                                assert!(
                                    !evaluate_tree(&tree, &empty, &no_refs()),
                                    "depth=2, outer={outer_op:?}, inner={inner_op:?}, \
                                     neg=({neg_a},{neg_b},{neg_c})",
                                );
                            }
                        }
                    }
                }
            }
        }
    }
}
