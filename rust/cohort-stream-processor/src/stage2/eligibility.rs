//! Parse-time cohort eligibility for Stage 2 composition.
//!
//! Classifies each cohort once, at filter-freeze, into one of three buckets:
//!
//! - [`SingleLeaf`](CohortEligibility::SingleLeaf) — exactly one state-keyed leaf, whose flip *is*
//!   the cohort's membership. Mapped into `by_lsk_to_single_leaf_cohorts` and emitted.
//! - [`Stage2Composable`](CohortEligibility::Stage2Composable) — ≥2 positive state-keyed leaves with
//!   no cohort references; not emitted.
//! - [`Excluded`](CohortEligibility::Excluded) — not emitted, with a reason for observability.
//!
//! Two signals classification needs do not survive the parse, so they are captured during it (in
//! [`CohortParseFlags`]) rather than re-walked from the frozen tree:
//!
//! - A dropped leaf produces no node, so a multi-leaf cohort whose sibling dropped would otherwise
//!   look single-leaf; [`CohortParseFlags::has_dropped_leaf`] records the loss so its lone survivor
//!   never drives whole-cohort membership.
//! - Behavioral-leaf negation is not read into the parsed leaf and is excluded from [`LeafStateKey`];
//!   [`CohortParseFlags::has_negation`] captures it so a negated cohort is not classified `Composable`.

use crate::filters::tree::{CohortTree, FilterNode};
use crate::stage1::key::LeafStateKey;

/// Per-cohort signals accumulated while parsing the cohort's filter tree, via the
/// [`LeafSink`](crate::filters::tree::LeafSink) callbacks. The complete flag input to [`classify`].
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct CohortParseFlags {
    /// Kept, state-keyed leaves (person-property + supported behavioral). Counts occurrences, which
    /// equals the number of state-keyed leaf nodes in the parsed tree.
    pub state_keyed_leaf_count: u32,
    /// The cohort has ≥1 cohort-reference leaf.
    pub has_cohort_ref: bool,
    /// The cohort has ≥1 negated leaf (`negation: true` or `operator: "not_in"`).
    pub has_negation: bool,
    /// The cohort lost ≥1 leaf during parse (unsupported variant, malformed, …). The dropped
    /// constraint is gone, so the cohort cannot be composed correctly from what survived.
    pub has_dropped_leaf: bool,
}

/// Why a cohort is excluded from composition. Doubles as the `excluded_<reason>` suffix on the
/// `cohort_eligibility_total{class}` counter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExcludedReason {
    /// Neither a single state-keyed leaf nor ≥2 composable leaves — an empty cohort.
    NotMultiLeaf,
    /// Has a negated leaf.
    HasNegation,
    /// Has a cohort-reference leaf.
    HasCohortRef,
    /// Lost a leaf during parse; the dropped constraint cannot be recovered, so the cohort is never
    /// composable.
    HasDroppedLeaf,
}

impl ExcludedReason {
    /// The `excluded_<reason>` label value for `cohort_eligibility_total`.
    fn metric_class(self) -> &'static str {
        match self {
            Self::NotMultiLeaf => "excluded_not_multi_leaf",
            Self::HasNegation => "excluded_has_negation",
            Self::HasCohortRef => "excluded_has_cohort_ref",
            Self::HasDroppedLeaf => "excluded_has_dropped_leaf",
        }
    }
}

/// A cohort's composition class, computed once at freeze.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CohortEligibility {
    /// Exactly one state-keyed leaf; its [`LeafStateKey`] is the cohort's membership.
    SingleLeaf(LeafStateKey),
    /// ≥2 positive, state-keyed, cohort-ref-free leaves.
    Stage2Composable,
    /// Not emitted; see [`ExcludedReason`].
    Excluded(ExcludedReason),
}

impl CohortEligibility {
    /// The `class` label value for `cohort_eligibility_total`.
    pub fn metric_class(self) -> &'static str {
        match self {
            Self::SingleLeaf(_) => "single_leaf",
            Self::Stage2Composable => "stage2_composable",
            Self::Excluded(reason) => reason.metric_class(),
        }
    }
}

/// Classify a parsed cohort for composition from its tree and accumulated parse flags.
///
/// Exclusions are checked first, most-permanent → least: a dropped leaf can never be recovered, so
/// it outranks negation and cohort references. A cohort clear of all three is `SingleLeaf` (exactly
/// one state-keyed leaf) or `Stage2Composable` (≥2); only an empty cohort falls through to
/// [`ExcludedReason::NotMultiLeaf`].
pub fn classify(tree: &CohortTree, flags: &CohortParseFlags) -> CohortEligibility {
    if flags.has_dropped_leaf {
        return CohortEligibility::Excluded(ExcludedReason::HasDroppedLeaf);
    }
    if flags.has_negation {
        return CohortEligibility::Excluded(ExcludedReason::HasNegation);
    }
    if flags.has_cohort_ref {
        return CohortEligibility::Excluded(ExcludedReason::HasCohortRef);
    }

    // No drops, negation, or cohort refs: every leaf node is a kept, state-keyed leaf, so the tree
    // walk and `state_keyed_leaf_count` agree on the leaf count.
    match single_supported_leaf(&tree.root) {
        Some(lsk) => CohortEligibility::SingleLeaf(lsk),
        None if flags.state_keyed_leaf_count >= 2 => CohortEligibility::Stage2Composable,
        None => CohortEligibility::Excluded(ExcludedReason::NotMultiLeaf),
    }
}

/// The [`LeafStateKey`] of a tree that is **exactly one** state-keyed leaf, or [`None`] otherwise
/// (zero leaves, ≥2 leaves, or a lone cohort-reference leaf — cohort refs have no `leaf_state_key`).
/// Used by [`classify`] only after the cohort-ref / dropped-leaf exclusions, where the sole reason
/// it can return `None` for a one-leaf tree (a cohort ref) is already ruled out.
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

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use serde_json::Value;

    use super::*;
    use crate::filters::tree::{BoolOp, CohortLeaf, CohortRefLeafConfig, PersonLeafConfig};
    use crate::filters::{CohortId, TeamId};

    const HASH_A: [u8; 16] = *b"aaaaaaaaaaaaaaaa";
    const HASH_B: [u8; 16] = *b"bbbbbbbbbbbbbbbb";

    fn person_leaf(hash: [u8; 16]) -> FilterNode {
        FilterNode::Leaf(CohortLeaf::PersonProperty(PersonLeafConfig {
            condition_hash: hash,
            leaf_state_key: LeafStateKey::for_person_property(&hash),
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

    fn and(children: Vec<FilterNode>) -> CohortTree {
        CohortTree {
            cohort_id: CohortId(1),
            team_id: TeamId(7),
            root: FilterNode::Group {
                op: BoolOp::And,
                children,
            },
        }
    }

    /// Flags for a clean tree of `n` positive state-keyed leaves.
    fn positive(n: u32) -> CohortParseFlags {
        CohortParseFlags {
            state_keyed_leaf_count: n,
            ..Default::default()
        }
    }

    #[test]
    fn one_state_keyed_leaf_is_single_leaf() {
        let tree = and(vec![person_leaf(HASH_A)]);
        assert_eq!(
            classify(&tree, &positive(1)),
            CohortEligibility::SingleLeaf(LeafStateKey::for_person_property(&HASH_A)),
        );
    }

    #[test]
    fn two_state_keyed_leaves_are_composable() {
        let tree = and(vec![person_leaf(HASH_A), person_leaf(HASH_B)]);
        assert_eq!(
            classify(&tree, &positive(2)),
            CohortEligibility::Stage2Composable,
        );
    }

    #[test]
    fn empty_cohort_is_not_multi_leaf() {
        let tree = and(vec![]);
        assert_eq!(
            classify(&tree, &positive(0)),
            CohortEligibility::Excluded(ExcludedReason::NotMultiLeaf),
        );
    }

    #[test]
    fn dropped_leaf_excludes_even_with_a_lone_survivor() {
        // One survivor in the tree but a sibling dropped: must be Excluded, not SingleLeaf.
        let tree = and(vec![person_leaf(HASH_A)]);
        let flags = CohortParseFlags {
            state_keyed_leaf_count: 1,
            has_dropped_leaf: true,
            ..Default::default()
        };
        assert_eq!(
            classify(&tree, &flags),
            CohortEligibility::Excluded(ExcludedReason::HasDroppedLeaf),
        );
    }

    #[test]
    fn negation_excludes_single_and_composable_shapes() {
        for count in [1, 2] {
            let leaves: Vec<FilterNode> = (0..count).map(|_| person_leaf(HASH_A)).collect();
            let tree = and(leaves);
            let flags = CohortParseFlags {
                state_keyed_leaf_count: count as u32,
                has_negation: true,
                ..Default::default()
            };
            assert_eq!(
                classify(&tree, &flags),
                CohortEligibility::Excluded(ExcludedReason::HasNegation),
                "count={count}",
            );
        }
    }

    #[test]
    fn cohort_ref_excludes() {
        let tree = and(vec![person_leaf(HASH_A), cohort_ref_leaf()]);
        let flags = CohortParseFlags {
            state_keyed_leaf_count: 1,
            has_cohort_ref: true,
            ..Default::default()
        };
        assert_eq!(
            classify(&tree, &flags),
            CohortEligibility::Excluded(ExcludedReason::HasCohortRef),
        );
    }

    #[test]
    fn exclusion_precedence_is_dropped_then_negation_then_cohort_ref() {
        let tree = and(vec![person_leaf(HASH_A), person_leaf(HASH_B)]);
        let all = CohortParseFlags {
            state_keyed_leaf_count: 2,
            has_cohort_ref: true,
            has_negation: true,
            has_dropped_leaf: true,
        };
        assert_eq!(
            classify(&tree, &all),
            CohortEligibility::Excluded(ExcludedReason::HasDroppedLeaf),
        );
        assert_eq!(
            classify(
                &tree,
                &CohortParseFlags {
                    has_dropped_leaf: false,
                    ..all
                }
            ),
            CohortEligibility::Excluded(ExcludedReason::HasNegation),
        );
        assert_eq!(
            classify(
                &tree,
                &CohortParseFlags {
                    has_dropped_leaf: false,
                    has_negation: false,
                    ..all
                }
            ),
            CohortEligibility::Excluded(ExcludedReason::HasCohortRef),
        );
    }

    #[test]
    fn metric_class_strings() {
        assert_eq!(
            CohortEligibility::SingleLeaf(LeafStateKey(HASH_A)).metric_class(),
            "single_leaf",
        );
        assert_eq!(
            CohortEligibility::Stage2Composable.metric_class(),
            "stage2_composable",
        );
        assert_eq!(
            CohortEligibility::Excluded(ExcludedReason::NotMultiLeaf).metric_class(),
            "excluded_not_multi_leaf",
        );
        assert_eq!(
            CohortEligibility::Excluded(ExcludedReason::HasNegation).metric_class(),
            "excluded_has_negation",
        );
        assert_eq!(
            CohortEligibility::Excluded(ExcludedReason::HasCohortRef).metric_class(),
            "excluded_has_cohort_ref",
        );
        assert_eq!(
            CohortEligibility::Excluded(ExcludedReason::HasDroppedLeaf).metric_class(),
            "excluded_has_dropped_leaf",
        );
    }

    #[test]
    fn nested_groups_count_one_leaf_as_single() {
        // A single leaf nested under OR(AND(..)) is still one state-keyed leaf.
        let tree = CohortTree {
            cohort_id: CohortId(1),
            team_id: TeamId(7),
            root: FilterNode::Group {
                op: BoolOp::Or,
                children: vec![FilterNode::Group {
                    op: BoolOp::And,
                    children: vec![person_leaf(HASH_A)],
                }],
            },
        };
        assert_eq!(
            classify(&tree, &positive(1)),
            CohortEligibility::SingleLeaf(LeafStateKey::for_person_property(&HASH_A)),
        );
    }
}
