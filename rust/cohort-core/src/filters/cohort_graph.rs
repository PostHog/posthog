//! Per-team cohort-reference graph and Tarjan-SCC cycle analysis.

use std::collections::{HashMap, HashSet};

use petgraph::algo::tarjan_scc;
use petgraph::graph::{DiGraph, NodeIndex};

use crate::filters::tree::{CohortLeaf, CohortTree, FilterNode};
use crate::filters::CohortId;

#[derive(Debug, Default)]
pub(crate) struct RefGraphAnalysis {
    /// Cohorts participating in a reference cycle (SCC of size > 1, or self-loop).
    pub in_cycle: HashSet<CohortId>,
    /// Ref-bearing cohorts in referenced-before-referrer order (reverse topological order of the
    /// condensation graph).
    pub refinement_order: Vec<CohortId>,
    /// Each ref-bearing cohort's distinct referenced ids (sorted), including ids absent from the
    /// team catalog.
    pub ref_targets: HashMap<CohortId, Vec<CohortId>>,
    /// Targets reached through at least one non-negated (positive) leaf. A target reached only
    /// through negated leaves is omitted: an absent negated ref reads `true`, so it never blocks
    /// composition. Resolvability is decided over this set, not `ref_targets`.
    pub positive_ref_targets: HashMap<CohortId, HashSet<CohortId>>,
}

pub(crate) fn analyze(cohorts: &HashMap<CohortId, CohortTree>) -> RefGraphAnalysis {
    let mut ref_targets: HashMap<CohortId, Vec<CohortId>> = HashMap::new();
    let mut positive_ref_targets: HashMap<CohortId, HashSet<CohortId>> = HashMap::new();
    for (&cohort_id, tree) in cohorts {
        let mut targets = HashSet::new();
        let mut positives = HashSet::new();
        collect_cohort_refs(&tree.root, &mut targets, &mut positives);
        if !targets.is_empty() {
            let mut targets: Vec<CohortId> = targets.into_iter().collect();
            targets.sort_unstable();
            ref_targets.insert(cohort_id, targets);
        }
        if !positives.is_empty() {
            positive_ref_targets.insert(cohort_id, positives);
        }
    }
    if ref_targets.is_empty() {
        return RefGraphAnalysis::default();
    }

    let mut node_ids: Vec<CohortId> = cohorts.keys().copied().collect();
    for targets in ref_targets.values() {
        node_ids.extend(targets.iter().copied());
    }
    node_ids.sort_unstable();
    node_ids.dedup();

    let mut graph: DiGraph<CohortId, ()> = DiGraph::new();
    let mut index_of: HashMap<CohortId, NodeIndex> = HashMap::with_capacity(node_ids.len());
    for id in node_ids {
        index_of.insert(id, graph.add_node(id));
    }

    // Self-loops are size-1 SCCs in Tarjan, so capture them separately.
    let mut self_loops = HashSet::new();
    for (&referrer, targets) in &ref_targets {
        let src = index_of[&referrer];
        for &target in targets {
            if referrer == target {
                self_loops.insert(referrer);
            }
            graph.add_edge(src, index_of[&target], ());
        }
    }

    let mut in_cycle = self_loops;
    let mut refinement_order = Vec::with_capacity(ref_targets.len());
    for scc in tarjan_scc(&graph) {
        if scc.len() > 1 {
            in_cycle.extend(scc.iter().map(|&idx| graph[idx]));
        }
        // Keep only the ref-bearing cohorts; their referenced-first order is what refinement needs.
        refinement_order.extend(
            scc.iter()
                .map(|&idx| graph[idx])
                .filter(|id| ref_targets.contains_key(id)),
        );
    }

    RefGraphAnalysis {
        in_cycle,
        refinement_order,
        ref_targets,
        positive_ref_targets,
    }
}

/// Collect every distinct cohort-reference target in a tree. Targets reached through a non-negated
/// leaf are additionally recorded in `positives` — the set resolvability is decided over.
fn collect_cohort_refs(
    node: &FilterNode,
    all: &mut HashSet<CohortId>,
    positives: &mut HashSet<CohortId>,
) {
    match node {
        FilterNode::Group { children, .. } => {
            for child in children {
                collect_cohort_refs(child, all, positives);
            }
        }
        FilterNode::Leaf(CohortLeaf::CohortRef(config)) => {
            all.insert(config.referenced_cohort_id);
            if !config.negation {
                positives.insert(config.referenced_cohort_id);
            }
        }
        FilterNode::Leaf(_) => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::filters::tree::{BoolOp, CohortRefLeafConfig};
    use crate::filters::TeamId;

    fn ref_cohort(id: i32, refs: &[i32]) -> (CohortId, CohortTree) {
        let children = refs
            .iter()
            .map(|&r| {
                FilterNode::Leaf(CohortLeaf::CohortRef(CohortRefLeafConfig {
                    referenced_cohort_id: CohortId(r),
                    negation: false,
                }))
            })
            .collect();
        (
            CohortId(id),
            CohortTree {
                cohort_id: CohortId(id),
                team_id: TeamId(1),
                root: FilterNode::Group {
                    op: BoolOp::And,
                    children,
                },
            },
        )
    }

    fn ref_cohort_negated(id: i32, refs: &[(i32, bool)]) -> (CohortId, CohortTree) {
        let children = refs
            .iter()
            .map(|&(r, negation)| {
                FilterNode::Leaf(CohortLeaf::CohortRef(CohortRefLeafConfig {
                    referenced_cohort_id: CohortId(r),
                    negation,
                }))
            })
            .collect();
        (
            CohortId(id),
            CohortTree {
                cohort_id: CohortId(id),
                team_id: TeamId(1),
                root: FilterNode::Group {
                    op: BoolOp::And,
                    children,
                },
            },
        )
    }

    fn catalog(cohorts: Vec<(CohortId, CohortTree)>) -> HashMap<CohortId, CohortTree> {
        cohorts.into_iter().collect()
    }

    fn ids(set: &HashSet<CohortId>) -> Vec<i32> {
        let mut v: Vec<i32> = set.iter().map(|c| c.0).collect();
        v.sort_unstable();
        v
    }

    fn positive_ids(analysis: &RefGraphAnalysis, id: i32) -> Vec<i32> {
        ids(&analysis.positive_ref_targets[&CohortId(id)])
    }

    #[test]
    fn three_node_cycle_marks_all_members() {
        let analysis = analyze(&catalog(vec![
            ref_cohort(1, &[2]),
            ref_cohort(2, &[3]),
            ref_cohort(3, &[1]),
        ]));
        assert_eq!(ids(&analysis.in_cycle), vec![1, 2, 3]);
    }

    #[test]
    fn cycle_free_isomorph_marks_nothing() {
        let analysis = analyze(&catalog(vec![
            ref_cohort(1, &[2]),
            ref_cohort(2, &[3]),
            ref_cohort(3, &[]),
        ]));
        assert!(analysis.in_cycle.is_empty());
    }

    #[test]
    fn self_loop_is_a_cycle() {
        let analysis = analyze(&catalog(vec![ref_cohort(1, &[1])]));
        assert_eq!(ids(&analysis.in_cycle), vec![1]);
        assert_eq!(analysis.ref_targets[&CohortId(1)], vec![CohortId(1)]);
    }

    #[test]
    fn tail_into_a_cycle_is_not_itself_cyclic() {
        let analysis = analyze(&catalog(vec![
            ref_cohort(4, &[1]),
            ref_cohort(1, &[2]),
            ref_cohort(2, &[1]),
        ]));
        assert_eq!(ids(&analysis.in_cycle), vec![1, 2]);
    }

    #[test]
    fn missing_target_is_in_ref_targets_but_never_in_cycle() {
        let analysis = analyze(&catalog(vec![ref_cohort(1, &[99])]));
        assert_eq!(analysis.ref_targets[&CohortId(1)], vec![CohortId(99)]);
        assert!(analysis.in_cycle.is_empty());
        assert!(!analysis.ref_targets.contains_key(&CohortId(99)));
    }

    #[test]
    fn duplicate_ref_edges_dedupe() {
        let analysis = analyze(&catalog(vec![ref_cohort(1, &[2, 2]), ref_cohort(2, &[])]));
        assert_eq!(analysis.ref_targets[&CohortId(1)], vec![CohortId(2)]);
    }

    #[test]
    fn refinement_order_is_referenced_before_referrer() {
        let analysis = analyze(&catalog(vec![
            ref_cohort(1, &[2]),
            ref_cohort(2, &[3]),
            ref_cohort(3, &[]),
        ]));
        let position = |id: CohortId| {
            analysis
                .refinement_order
                .iter()
                .position(|&c| c == id)
                .expect("ref-bearing cohort present in refinement_order")
        };
        for (&referrer, targets) in &analysis.ref_targets {
            for &target in targets {
                if analysis.ref_targets.contains_key(&target) {
                    assert!(
                        position(target) < position(referrer),
                        "target {target:?} must be refined before referrer {referrer:?}",
                    );
                }
            }
        }
        // 3 is not ref-bearing, so it never appears in the order.
        assert!(!analysis.refinement_order.contains(&CohortId(3)));
    }

    #[test]
    fn team_without_refs_yields_default_analysis() {
        let analysis = analyze(&catalog(vec![ref_cohort(1, &[])]));
        assert!(analysis.in_cycle.is_empty());
        assert!(analysis.refinement_order.is_empty());
        assert!(analysis.ref_targets.is_empty());
        assert!(analysis.positive_ref_targets.is_empty());
    }

    #[test]
    fn negated_only_ref_is_in_ref_targets_but_not_positive() {
        let analysis = analyze(&catalog(vec![ref_cohort_negated(1, &[(99, true)])]));
        assert_eq!(analysis.ref_targets[&CohortId(1)], vec![CohortId(99)]);
        // A purely negated reference contributes no positive target, so the referrer's positive
        // set is empty — resolvability never inspects the negated 99.
        assert!(!analysis.positive_ref_targets.contains_key(&CohortId(1)));
    }

    #[test]
    fn positive_ref_is_in_both_target_maps() {
        let analysis = analyze(&catalog(vec![
            ref_cohort_negated(1, &[(2, false)]),
            ref_cohort(2, &[]),
        ]));
        assert_eq!(analysis.ref_targets[&CohortId(1)], vec![CohortId(2)]);
        assert_eq!(positive_ids(&analysis, 1), vec![2]);
    }

    #[test]
    fn mixed_polarity_ref_to_same_target_keeps_it_positive() {
        // 1 references 2 both positively and negatively → 2 stays in the positive set, so a missing
        // 2 would still block composition.
        let analysis = analyze(&catalog(vec![
            ref_cohort_negated(1, &[(2, false), (2, true)]),
            ref_cohort(2, &[]),
        ]));
        assert_eq!(analysis.ref_targets[&CohortId(1)], vec![CohortId(2)]);
        assert_eq!(positive_ids(&analysis, 1), vec![2]);
    }
}
