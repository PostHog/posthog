//! Per-team cohort-reference graph and Tarjan-SCC cycle analysis.

use std::collections::{HashMap, HashSet};

use petgraph::algo::tarjan_scc;
use petgraph::graph::{DiGraph, NodeIndex};

use crate::filters::tree::{CohortLeaf, CohortTree, FilterNode};
use crate::filters::CohortId;

/// Structural facts about a team's cohort-reference graph, computed once at filter freeze.
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
}

/// Analyze a team's parsed cohort trees for reference cycles and refinement order.
pub(crate) fn analyze(cohorts: &HashMap<CohortId, CohortTree>) -> RefGraphAnalysis {
    let mut ref_targets: HashMap<CohortId, Vec<CohortId>> = HashMap::new();
    for (&cohort_id, tree) in cohorts {
        let mut targets = HashSet::new();
        collect_cohort_refs(&tree.root, &mut targets);
        if !targets.is_empty() {
            let mut targets: Vec<CohortId> = targets.into_iter().collect();
            targets.sort_unstable();
            ref_targets.insert(cohort_id, targets);
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
    }
}

/// Collect every distinct cohort-reference target in a tree.
fn collect_cohort_refs(node: &FilterNode, out: &mut HashSet<CohortId>) {
    match node {
        FilterNode::Group { children, .. } => {
            for child in children {
                collect_cohort_refs(child, out);
            }
        }
        FilterNode::Leaf(CohortLeaf::CohortRef(config)) => {
            out.insert(config.referenced_cohort_id);
        }
        FilterNode::Leaf(_) => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::filters::tree::{BoolOp, CohortRefLeafConfig};
    use crate::filters::TeamId;

    /// A cohort whose only leaves are cohort-references to `refs`.
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

    fn catalog(cohorts: Vec<(CohortId, CohortTree)>) -> HashMap<CohortId, CohortTree> {
        cohorts.into_iter().collect()
    }

    fn ids(set: &HashSet<CohortId>) -> Vec<i32> {
        let mut v: Vec<i32> = set.iter().map(|c| c.0).collect();
        v.sort_unstable();
        v
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
        // The placeholder is never itself ref-bearing.
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
    }
}
