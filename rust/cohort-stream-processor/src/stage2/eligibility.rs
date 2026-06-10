//! Parse-time cohort eligibility for Stage 2 composition.
//!
//! Classifies each cohort once, at filter-freeze, into one of three buckets:
//!
//! - [`SingleLeaf`](CohortEligibility::SingleLeaf) — exactly one state-keyed leaf, whose flip *is*
//!   the cohort's membership. Mapped into `by_lsk_to_single_leaf_cohorts` and emitted.
//! - [`Stage2Composable`](CohortEligibility::Stage2Composable) — ≥2 state-keyed leaves (some
//!   potentially negated) with no cohort references.
//! - [`Excluded`](CohortEligibility::Excluded) — not emitted, with a reason for observability.
//!
//! A dropped leaf produces no node, so [`CohortParseFlags::has_dropped_leaf`] records the loss
//! during the parse. Negation and empty groups are recovered from the frozen tree.

use crate::filters::tree::{BoolOp, CohortTree, FilterNode};
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
    /// The cohort lost ≥1 leaf during parse (unsupported variant, malformed, …). The dropped
    /// constraint is gone, so the cohort cannot be composed correctly from what survived.
    pub has_dropped_leaf: bool,
}

/// Why a cohort is excluded from composition. Doubles as the `excluded_<reason>` suffix on the
/// `cohort_eligibility_total{class}` counter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExcludedReason {
    /// Neither a single state-keyed leaf nor ≥2 composable leaves. Defensive-only: `EmptyGroup`
    /// fires first for any zero-leaf tree, since every such tree has an empty group.
    NotMultiLeaf,
    /// The root condition is negated (AND: all children negated; OR: any child negated).
    TopLevelNegation,
    /// A group anywhere in the tree has zero children. Without exclusion an empty AND evaluates to
    /// `true` (identity), making everyone a member.
    EmptyGroup,
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
            Self::TopLevelNegation => "excluded_top_level_negation",
            Self::EmptyGroup => "excluded_empty_group",
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

/// Whether a tree's root condition is negated: leaf → its `negated()` bit; AND → all children
/// negated; OR → any child negated. Empty AND is `false` (unreachable — `has_empty_group` fires
/// first).
pub(crate) fn condition_negation(node: &FilterNode) -> bool {
    match node {
        FilterNode::Leaf(leaf) => leaf.negated(),
        FilterNode::Group { op, children } => match op {
            BoolOp::And => !children.is_empty() && children.iter().all(condition_negation),
            BoolOp::Or => children.iter().any(condition_negation),
        },
    }
}

/// Whether any group in the tree has zero children.
fn has_empty_group(node: &FilterNode) -> bool {
    match node {
        FilterNode::Leaf(_) => false,
        FilterNode::Group { children, .. } => {
            children.is_empty() || children.iter().any(has_empty_group)
        }
    }
}

/// Classify a parsed cohort for composition from its tree and accumulated parse flags.
///
/// Exclusion precedence (most-permanent first): dropped leaf → empty group → root-negated →
/// cohort reference. Dropped fires first so drop-created empty groups are attributed correctly.
pub fn classify(tree: &CohortTree, flags: &CohortParseFlags) -> CohortEligibility {
    if flags.has_dropped_leaf {
        return CohortEligibility::Excluded(ExcludedReason::HasDroppedLeaf);
    }
    if has_empty_group(&tree.root) {
        return CohortEligibility::Excluded(ExcludedReason::EmptyGroup);
    }
    if condition_negation(&tree.root) {
        return CohortEligibility::Excluded(ExcludedReason::TopLevelNegation);
    }
    if flags.has_cohort_ref {
        return CohortEligibility::Excluded(ExcludedReason::HasCohortRef);
    }

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
    use crate::filters::tree::{CohortLeaf, CohortRefLeafConfig, PersonLeafConfig};
    use crate::filters::{CohortId, TeamId};

    const HASH_A: [u8; 16] = *b"aaaaaaaaaaaaaaaa";
    const HASH_B: [u8; 16] = *b"bbbbbbbbbbbbbbbb";
    const HASH_C: [u8; 16] = *b"cccccccccccccccc";

    fn person_leaf(hash: [u8; 16]) -> FilterNode {
        person_leaf_negated(hash, false)
    }

    fn person_leaf_negated(hash: [u8; 16], negated: bool) -> FilterNode {
        FilterNode::Leaf(CohortLeaf::PersonProperty(PersonLeafConfig {
            condition_hash: hash,
            leaf_state_key: LeafStateKey::for_person_property(&hash),
            bytecode: Arc::new(Vec::new()),
            raw: Value::Null,
            negated,
        }))
    }

    fn cohort_ref_leaf() -> FilterNode {
        cohort_ref_leaf_negated(false)
    }

    fn cohort_ref_leaf_negated(negation: bool) -> FilterNode {
        FilterNode::Leaf(CohortLeaf::CohortRef(CohortRefLeafConfig {
            referenced_cohort_id: CohortId(99),
            negation,
        }))
    }

    fn and(children: Vec<FilterNode>) -> CohortTree {
        tree_with(BoolOp::And, children)
    }

    fn or(children: Vec<FilterNode>) -> CohortTree {
        tree_with(BoolOp::Or, children)
    }

    fn tree_with(op: BoolOp, children: Vec<FilterNode>) -> CohortTree {
        CohortTree {
            cohort_id: CohortId(1),
            team_id: TeamId(7),
            root: FilterNode::Group { op, children },
        }
    }

    fn group(op: BoolOp, children: Vec<FilterNode>) -> FilterNode {
        FilterNode::Group { op, children }
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
    fn empty_cohort_is_empty_group() {
        let tree = and(vec![]);
        assert_eq!(
            classify(&tree, &positive(0)),
            CohortEligibility::Excluded(ExcludedReason::EmptyGroup),
        );
    }

    #[test]
    fn dropped_leaf_excludes_even_with_a_lone_survivor() {
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

    // ── condition_negation ──────────────────────────────────────────────────────

    #[test]
    fn condition_negation_leaf_bits() {
        assert!(!condition_negation(&person_leaf(HASH_A)));
        assert!(condition_negation(&person_leaf_negated(HASH_A, true)));
    }

    #[test]
    fn condition_negation_and_propagation() {
        // AND all-negated → true; AND mixed → false; AND all-positive → false.
        assert!(condition_negation(&group(
            BoolOp::And,
            vec![
                person_leaf_negated(HASH_A, true),
                person_leaf_negated(HASH_B, true),
            ],
        )));
        assert!(!condition_negation(&group(
            BoolOp::And,
            vec![person_leaf(HASH_A), person_leaf_negated(HASH_B, true)],
        )));
        assert!(!condition_negation(&group(
            BoolOp::And,
            vec![person_leaf(HASH_A), person_leaf(HASH_B)],
        )));
    }

    #[test]
    fn condition_negation_or_propagation() {
        // OR any-negated → true; OR all-positive → false.
        assert!(condition_negation(&group(
            BoolOp::Or,
            vec![person_leaf(HASH_A), person_leaf_negated(HASH_B, true)],
        )));
        assert!(condition_negation(&group(
            BoolOp::Or,
            vec![
                person_leaf_negated(HASH_A, true),
                person_leaf_negated(HASH_B, true),
            ],
        )));
        assert!(!condition_negation(&group(
            BoolOp::Or,
            vec![person_leaf(HASH_A), person_leaf(HASH_B)],
        )));
    }

    #[test]
    fn condition_negation_empty_groups_are_false() {
        assert!(!condition_negation(&group(BoolOp::And, vec![])));
        assert!(!condition_negation(&group(BoolOp::Or, vec![])));
    }

    #[test]
    fn condition_negation_cohort_ref_negated_is_true() {
        assert!(condition_negation(&cohort_ref_leaf_negated(true)));
        assert!(!condition_negation(&cohort_ref_leaf_negated(false)));
    }

    // ── classifier shapes ───────────────────────────────────────────────────────

    #[test]
    fn and_a_neg_b_is_composable() {
        // AND(A, ¬B): root is not negated (AND needs ALL negated), so it's composable.
        let tree = and(vec![person_leaf(HASH_A), person_leaf_negated(HASH_B, true)]);
        assert_eq!(
            classify(&tree, &positive(2)),
            CohortEligibility::Stage2Composable,
        );
    }

    #[test]
    fn or_a_neg_b_is_composable() {
        // OR(A, ¬B): root is negated (OR with any negated), so excluded.
        let tree = or(vec![person_leaf(HASH_A), person_leaf_negated(HASH_B, true)]);
        assert_eq!(
            classify(&tree, &positive(2)),
            CohortEligibility::Excluded(ExcludedReason::TopLevelNegation),
        );
    }

    #[test]
    fn or_neg_a_neg_b_is_top_level_negation() {
        let tree = or(vec![
            person_leaf_negated(HASH_A, true),
            person_leaf_negated(HASH_B, true),
        ]);
        assert_eq!(
            classify(&tree, &positive(2)),
            CohortEligibility::Excluded(ExcludedReason::TopLevelNegation),
        );
    }

    #[test]
    fn and_neg_a_neg_b_is_top_level_negation() {
        let tree = and(vec![
            person_leaf_negated(HASH_A, true),
            person_leaf_negated(HASH_B, true),
        ]);
        assert_eq!(
            classify(&tree, &positive(2)),
            CohortEligibility::Excluded(ExcludedReason::TopLevelNegation),
        );
    }

    #[test]
    fn bare_negated_leaf_is_top_level_negation() {
        // A single negated leaf under AND(¬A) propagates to the root.
        let tree = and(vec![person_leaf_negated(HASH_A, true)]);
        assert_eq!(
            classify(&tree, &positive(1)),
            CohortEligibility::Excluded(ExcludedReason::TopLevelNegation),
        );
    }

    #[test]
    fn nested_negated_and_propagates() {
        // AND(¬A) → root negated; OR(AND(¬A)) → root negated (OR any).
        let tree = or(vec![group(
            BoolOp::And,
            vec![person_leaf_negated(HASH_A, true)],
        )]);
        assert_eq!(
            classify(&tree, &positive(1)),
            CohortEligibility::Excluded(ExcludedReason::TopLevelNegation),
        );
    }

    #[test]
    fn and_c_or_a_neg_b_is_composable() {
        // AND(C, OR(A, ¬B)): root is AND with two children. The OR child is negated but the AND
        // needs ALL negated. C is positive → root is not negated → composable.
        let tree = and(vec![
            person_leaf(HASH_C),
            group(
                BoolOp::Or,
                vec![person_leaf(HASH_A), person_leaf_negated(HASH_B, true)],
            ),
        ]);
        assert_eq!(
            classify(&tree, &positive(3)),
            CohortEligibility::Stage2Composable,
        );
    }

    #[test]
    fn and_c_or_neg_a_neg_b_is_composable() {
        // AND(C, OR(¬A, ¬B)): the OR child is negated, but C is positive so root AND is not.
        let tree = and(vec![
            person_leaf(HASH_C),
            group(
                BoolOp::Or,
                vec![
                    person_leaf_negated(HASH_A, true),
                    person_leaf_negated(HASH_B, true),
                ],
            ),
        ]);
        assert_eq!(
            classify(&tree, &positive(3)),
            CohortEligibility::Stage2Composable,
        );
    }

    // ── empty-group ─────────────────────────────────────────────────────────────

    #[test]
    fn root_empty_and_is_empty_group() {
        let tree = and(vec![]);
        assert_eq!(
            classify(&tree, &positive(0)),
            CohortEligibility::Excluded(ExcludedReason::EmptyGroup),
        );
    }

    #[test]
    fn nested_empty_or_is_empty_group() {
        // AND(leaf, OR()): the nested empty OR triggers EmptyGroup.
        let tree = and(vec![person_leaf(HASH_A), group(BoolOp::Or, vec![])]);
        assert_eq!(
            classify(&tree, &positive(1)),
            CohortEligibility::Excluded(ExcludedReason::EmptyGroup),
        );
    }

    #[test]
    fn or_with_empty_and_child_is_empty_group() {
        // OR(A, B, AND()): the empty AND child is the always-true divergence the oracle rejects.
        let tree = or(vec![
            person_leaf(HASH_A),
            person_leaf(HASH_B),
            group(BoolOp::And, vec![]),
        ]);
        assert_eq!(
            classify(&tree, &positive(2)),
            CohortEligibility::Excluded(ExcludedReason::EmptyGroup),
        );
    }

    // ── precedence ──────────────────────────────────────────────────────────────

    #[test]
    fn precedence_dropped_over_empty_group() {
        // AND(¬A, OR()) + dropped flag: dropped fires first.
        let tree = and(vec![
            person_leaf_negated(HASH_A, true),
            group(BoolOp::Or, vec![]),
        ]);
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
    fn precedence_empty_group_over_top_level_negation() {
        // AND(¬A, OR()): both EmptyGroup and TopLevelNegation apply, but EmptyGroup wins.
        let tree = and(vec![
            person_leaf_negated(HASH_A, true),
            group(BoolOp::Or, vec![]),
        ]);
        assert_eq!(
            classify(&tree, &positive(1)),
            CohortEligibility::Excluded(ExcludedReason::EmptyGroup),
        );
    }

    #[test]
    fn precedence_top_level_negation_over_cohort_ref() {
        // AND(¬A, ¬ref): both TopLevelNegation and HasCohortRef apply.
        let tree = and(vec![
            person_leaf_negated(HASH_A, true),
            cohort_ref_leaf_negated(true),
        ]);
        let flags = CohortParseFlags {
            state_keyed_leaf_count: 1,
            has_cohort_ref: true,
            ..Default::default()
        };
        assert_eq!(
            classify(&tree, &flags),
            CohortEligibility::Excluded(ExcludedReason::TopLevelNegation),
        );
    }

    #[test]
    fn positive_negated_a_with_positive_cohort_ref_is_cohort_ref() {
        // AND(¬A, ref⁺): root is not all-negated (ref is positive), so no TopLevelNegation;
        // HasCohortRef fires.
        let tree = and(vec![person_leaf_negated(HASH_A, true), cohort_ref_leaf()]);
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
            CohortEligibility::Excluded(ExcludedReason::TopLevelNegation).metric_class(),
            "excluded_top_level_negation",
        );
        assert_eq!(
            CohortEligibility::Excluded(ExcludedReason::EmptyGroup).metric_class(),
            "excluded_empty_group",
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
