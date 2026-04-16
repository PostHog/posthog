#[cfg(test)]
mod tests {
    use crate::api::errors::FlagError;
    use crate::utils::graph_utils::{
        DependencyGraph, DependencyProvider, DependencyType, GraphError,
    };
    use std::collections::{HashMap, HashSet};

    /// Convenience helper that extracts edges from each node's `extract_dependencies()`
    /// and delegates to `DependencyGraph::from_nodes`. Keeps test call sites simple.
    #[allow(clippy::type_complexity)]
    fn build_graph_from_nodes(
        nodes: &[TestItem],
    ) -> Result<
        (
            DependencyGraph<TestItem>,
            Vec<GraphError<i64>>,
            HashSet<i64>,
        ),
        FlagError,
    > {
        let mut edges = HashMap::with_capacity(nodes.len());
        for node in nodes {
            edges.insert(node.get_id(), node.extract_dependencies()?);
        }
        DependencyGraph::from_nodes(nodes.to_vec(), &edges)
    }

    // Test helper struct that implements DependencyProvider
    #[derive(Debug, Clone, PartialEq, Eq)]
    struct TestItem {
        id: i64,
        dependencies: HashSet<i64>,
    }

    impl std::hash::Hash for TestItem {
        fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
            self.id.hash(state);
        }
    }

    impl TestItem {
        fn new(id: i64, dependencies: HashSet<i64>) -> Self {
            Self { id, dependencies }
        }
    }

    impl DependencyProvider for TestItem {
        type Id = i64;
        type Error = FlagError;

        fn get_id(&self) -> Self::Id {
            self.id
        }

        fn extract_dependencies(&self) -> Result<HashSet<Self::Id>, Self::Error> {
            Ok(self.dependencies.clone())
        }

        fn dependency_type() -> DependencyType {
            DependencyType::Flag
        }
    }

    mod new_graph_creation {
        use super::*;

        #[test]
        fn test_create_simple_linear_graph() {
            // Create a linear chain: 1 -> 2 -> 3
            let items = vec![
                TestItem::new(1, HashSet::from([2])),
                TestItem::new(2, HashSet::from([3])),
                TestItem::new(3, HashSet::new()),
            ];

            let graph = DependencyGraph::new(items[0].clone(), &items).unwrap();
            assert_eq!(graph.node_count(), 3);
            assert_eq!(graph.edge_count(), 2);
        }

        #[test]
        fn test_single_item_graph() {
            let items = vec![TestItem::new(1, HashSet::new())];

            let graph = DependencyGraph::new(items[0].clone(), &items).unwrap();
            assert_eq!(graph.node_count(), 1);
            assert_eq!(graph.edge_count(), 0);
        }

        #[test]
        fn test_create_graph_with_multiple_dependencies() {
            // Create a graph where one node depends on multiple others:
            // 1 -> 2
            // 1 -> 3
            // 2 -> 4
            // 3 -> 4
            let items = vec![
                TestItem::new(1, HashSet::from([2, 3])),
                TestItem::new(2, HashSet::from([4])),
                TestItem::new(3, HashSet::from([4])),
                TestItem::new(4, HashSet::new()),
            ];

            let graph = DependencyGraph::new(items[0].clone(), &items).unwrap();
            assert_eq!(graph.node_count(), 4);
            assert_eq!(graph.edge_count(), 4);
        }

        #[test]
        fn test_duplicate_dependencies() {
            // Create a graph where a node depends on the same node multiple times
            let items = vec![
                TestItem::new(1, HashSet::from([2, 2, 2])), // Multiple references to 2
                TestItem::new(2, HashSet::new()),
            ];

            let graph = DependencyGraph::new(items[0].clone(), &items).unwrap();
            assert_eq!(graph.node_count(), 2);
            assert_eq!(graph.edge_count(), 1); // Should only create one edge despite multiple dependencies
        }
    }

    mod new_error_handling {
        use super::*;

        #[test]
        fn test_missing_dependency() {
            let items = vec![
                TestItem::new(1, HashSet::from([999])), // 999 doesn't exist
            ];

            let result = DependencyGraph::new(items[0].clone(), &items);
            assert!(result.is_err());
            assert!(matches!(
                result.unwrap_err(),
                FlagError::DependencyNotFound(DependencyType::Flag, 999)
            ));
        }

        #[test]
        fn test_self_referential_cycle() {
            let items = vec![
                TestItem::new(1, HashSet::from([1])), // 1 depends on itself
            ];

            let result = DependencyGraph::new(items[0].clone(), &items);
            assert!(result.is_err());
            assert!(matches!(
                result.unwrap_err(),
                FlagError::DependencyCycle(DependencyType::Flag, 1)
            ));
        }

        #[test]
        fn test_cyclic_dependency() {
            // Create a cycle: 1 -> 2 -> 3 -> 1
            let items = vec![
                TestItem::new(1, HashSet::from([2])),
                TestItem::new(2, HashSet::from([3])),
                TestItem::new(3, HashSet::from([1])),
            ];

            let result = DependencyGraph::new(items[0].clone(), &items);
            assert!(result.is_err());
            assert!(matches!(
                result.unwrap_err(),
                FlagError::DependencyCycle(DependencyType::Flag, _)
            ));
        }

        #[test]
        fn test_root_not_in_pool_returns_error() {
            let root = TestItem::new(1, HashSet::from([2]));
            let pool = vec![
                TestItem::new(2, HashSet::new()),
                TestItem::new(3, HashSet::new()),
            ];

            let result = DependencyGraph::new(root, &pool);
            assert!(result.is_err());
            assert!(matches!(
                result.unwrap_err(),
                FlagError::DependencyNotFound(DependencyType::Flag, 1)
            ));
        }
    }

    mod new_traversal {
        use super::*;

        #[test]
        fn test_traverse_linear_chain() {
            // Create a linear chain: 1 -> 2 -> 3
            let items = vec![
                TestItem::new(1, HashSet::from([2])),
                TestItem::new(2, HashSet::from([3])),
                TestItem::new(3, HashSet::new()),
            ];

            let graph = DependencyGraph::new(items[0].clone(), &items).unwrap();

            let mut visited = Vec::new();
            let results = graph
                .for_each_dependencies_first::<_, ()>(|item, _, _| {
                    visited.push(item.id);
                    Ok(())
                })
                .unwrap();

            // Should visit in order: 3, 2, 1 (dependencies first)
            assert_eq!(visited, vec![3, 2, 1]);
            assert_eq!(results.len(), 3);
        }

        #[test]
        fn test_traverse_with_multiple_dependencies() {
            // Create a graph where one node depends on multiple others:
            // 1 -> 2
            // 1 -> 3
            // 2 -> 4
            // 3 -> 4
            let items = vec![
                TestItem::new(1, HashSet::from([2, 3])),
                TestItem::new(2, HashSet::from([4])),
                TestItem::new(3, HashSet::from([4])),
                TestItem::new(4, HashSet::new()),
            ];

            let graph = DependencyGraph::new(items[0].clone(), &items).unwrap();

            let mut visited = Vec::new();
            let results = graph
                .for_each_dependencies_first::<_, ()>(|item, _, _| {
                    visited.push(item.id);
                    Ok(())
                })
                .unwrap();

            // 4 must be visited before 2 and 3, and 2 and 3 must be visited before 1
            assert_eq!(visited[0], 4); // 4 is visited first
            assert!(visited[1..3].contains(&2) && visited[1..3].contains(&3)); // 2 and 3 are visited next
            assert_eq!(visited[3], 1); // 1 is visited last
            assert_eq!(results.len(), 4);
        }

        #[test]
        fn test_traverse_with_result_accumulation() {
            // Create a simple chain: 1 -> 2 -> 3
            let items = vec![
                TestItem::new(1, HashSet::from([2])),
                TestItem::new(2, HashSet::from([3])),
                TestItem::new(3, HashSet::new()),
            ];

            let graph = DependencyGraph::new(items[0].clone(), &items).unwrap();

            // Accumulate the sum of all visited nodes' dependencies
            let results = graph
                .for_each_dependencies_first(|item, results, sum| {
                    *sum = item.dependencies.len() as i32;
                    for dep_id in &item.dependencies {
                        if let Some(dep_sum) = results.get(dep_id) {
                            *sum += dep_sum;
                        }
                    }
                    Ok(())
                })
                .unwrap();

            // Node 3 has 0 dependencies
            // Node 2 has 1 dependency (3) with sum 0
            // Node 1 has 1 dependency (2) with sum 1
            assert_eq!(results.get(&3), Some(&0));
            assert_eq!(results.get(&2), Some(&1));
            assert_eq!(results.get(&1), Some(&2));
        }

        #[test]
        fn test_traverse_complex_dag() {
            // Create a more complex DAG:
            //     1
            //    / \
            //   2   3
            //  / \ / \
            // 4   5   6
            //  \ / \ /
            //   7   8
            //    \ /
            //     9
            let items = vec![
                TestItem::new(1, HashSet::from([2, 3])),
                TestItem::new(2, HashSet::from([4, 5])),
                TestItem::new(3, HashSet::from([5, 6])),
                TestItem::new(4, HashSet::from([7])),
                TestItem::new(5, HashSet::from([7, 8])),
                TestItem::new(6, HashSet::from([8])),
                TestItem::new(7, HashSet::from([9])),
                TestItem::new(8, HashSet::from([9])),
                TestItem::new(9, HashSet::new()),
            ];

            let graph = DependencyGraph::new(items[0].clone(), &items).unwrap();

            let mut visited = Vec::new();
            let _results = graph
                .for_each_dependencies_first::<_, ()>(|item, _, _| {
                    visited.push(item.id);
                    Ok(())
                })
                .unwrap();

            // Verify that dependencies are visited before their dependents
            let get_position = |id: i64| visited.iter().position(|&x| x == id).unwrap();

            // 9 must be visited before 7 and 8
            let pos_9 = get_position(9);
            assert!(get_position(7) > pos_9);
            assert!(get_position(8) > pos_9);

            // 7 and 8 must be visited before 4, 5, and 6
            let pos_7 = get_position(7);
            let pos_8 = get_position(8);
            assert!(get_position(4) > pos_7);
            assert!(get_position(5) > pos_7 && get_position(5) > pos_8);
            assert!(get_position(6) > pos_8);

            // 4, 5, and 6 must be visited before 2 and 3
            let pos_4 = get_position(4);
            let pos_5 = get_position(5);
            let pos_6 = get_position(6);
            assert!(get_position(2) > pos_4 && get_position(2) > pos_5);
            assert!(get_position(3) > pos_5 && get_position(3) > pos_6);

            // 2 and 3 must be visited before 1
            let pos_2 = get_position(2);
            let pos_3 = get_position(3);
            assert!(get_position(1) > pos_2 && get_position(1) > pos_3);

            // Verify all nodes were visited
            assert_eq!(visited.len(), 9);
        }
    }

    mod new_edge_cases {
        use super::*;

        #[test]
        fn test_empty_dependencies() {
            let items = vec![TestItem::new(1, HashSet::new())];

            let graph = DependencyGraph::new(items[0].clone(), &items).unwrap();
            assert_eq!(graph.node_count(), 1);
            assert_eq!(graph.edge_count(), 0);
        }

        #[test]
        fn test_disconnected_nodes() {
            // Create two disconnected subgraphs: 1->2 and 3->4
            let items = vec![
                TestItem::new(1, HashSet::from([2])),
                TestItem::new(2, HashSet::new()),
                TestItem::new(3, HashSet::from([4])),
                TestItem::new(4, HashSet::new()),
            ];

            // Starting from node 1, should only include 1 and 2
            let graph = DependencyGraph::new(items[0].clone(), &items).unwrap();
            assert_eq!(graph.node_count(), 2);
            assert_eq!(graph.edge_count(), 1);

            // Starting from node 3, should only include 3 and 4
            let graph = DependencyGraph::new(items[2].clone(), &items).unwrap();
            assert_eq!(graph.node_count(), 2);
            assert_eq!(graph.edge_count(), 1);
        }
    }

    mod from_nodes_tests {
        use super::*;

        #[test]
        fn test_build_multiple_independent_nodes() {
            let items = vec![
                TestItem::new(1, HashSet::new()),
                TestItem::new(2, HashSet::new()),
                TestItem::new(3, HashSet::new()),
            ];

            let (graph, errors, nodes_with_missing_deps) = build_graph_from_nodes(&items).unwrap();
            assert!(errors.is_empty(), "Expected no errors, found: {errors:?}");
            assert!(
                nodes_with_missing_deps.is_empty(),
                "Expected no missing deps, found: {nodes_with_missing_deps:?}"
            );
            assert_eq!(graph.node_count(), 3);
            assert_eq!(graph.edge_count(), 0);
        }

        #[test]
        fn test_build_multiple_subgraphs() {
            let items = vec![
                TestItem::new(1, HashSet::from([2])),
                TestItem::new(2, HashSet::from([3])),
                TestItem::new(3, HashSet::new()),
                TestItem::new(4, HashSet::from([5])),
                TestItem::new(5, HashSet::new()),
                TestItem::new(6, HashSet::new()),
            ];

            let (graph, errors, nodes_with_missing_deps) = build_graph_from_nodes(&items).unwrap();
            assert!(errors.is_empty(), "Expected no errors, found: {errors:?}");
            assert!(
                nodes_with_missing_deps.is_empty(),
                "Expected no missing deps"
            );
            assert_eq!(graph.node_count(), 6);
            assert_eq!(graph.edge_count(), 3);
        }

        #[test]
        fn test_build_multiple_subgraphs_removes_cycles() {
            let items = vec![
                TestItem::new(1, HashSet::from([2])),
                TestItem::new(2, HashSet::from([3])),
                TestItem::new(3, HashSet::new()),
                TestItem::new(4, HashSet::from([5])),
                TestItem::new(5, HashSet::new()),
                TestItem::new(6, HashSet::new()),
                // Cycle: (7 -> 8 -> 9 -> 7)
                // 10 -> (7 cycle)
                // 11 -> 10 -> (7 cycle)
                // 11 -> (7 cycle)
                // 12 -> 10 -> (7 cycle)
                // 13 -> (7 cycle)
                TestItem::new(7, HashSet::from([8])),
                TestItem::new(8, HashSet::from([9])), // Starts the cycle.
                TestItem::new(9, HashSet::from([7])),
                TestItem::new(10, HashSet::from([7])), // Needs to removed because it depends on a cycle.
                TestItem::new(11, HashSet::from([10, 7])), // Needs to removed because it depends on a node that depends on a cycle.
                TestItem::new(12, HashSet::from([10])), // Needs to removed because it depends on a node that depends on a cycle.
                TestItem::new(13, HashSet::from([7])), // Needs to removed because it depends on a cycle.
                // Cycle: 14 -> 15 -> 16 -> 14
                TestItem::new(14, HashSet::from([15])),
                TestItem::new(15, HashSet::from([16])),
                TestItem::new(16, HashSet::from([14])),
            ];

            let (graph, errors, _) = build_graph_from_nodes(&items).unwrap();
            assert_eq!(
                errors.len(),
                2,
                "Expected two cycle errors, found: {errors:?}",
            );
            // Check that both cycles are detected (order may vary)
            let cycle_ids: Vec<_> = errors
                .iter()
                .filter_map(|e| {
                    if let GraphError::CycleDetected(id) = e {
                        Some(*id)
                    } else {
                        None
                    }
                })
                .collect();
            assert!(cycle_ids.contains(&9), "Expected cycle starting at node 9");
            assert!(
                cycle_ids.contains(&16),
                "Expected cycle starting at node 16"
            );
            assert_eq!(
                graph.node_count(),
                6,
                "Expected only the valid subgraphs (1->2->3, 4->5, 6)"
            );
            assert_eq!(graph.edge_count(), 3, "Expected edges: 1->2, 2->3, 4->5");

            assert!(graph.contains_node(1));
            assert!(graph.contains_node(2));
            assert!(graph.contains_node(3));
            assert!(graph.contains_node(4));
            assert!(graph.contains_node(5));
            assert!(graph.contains_node(6));

            assert!(!graph.contains_node(7));
            assert!(!graph.contains_node(8));
            assert!(!graph.contains_node(9));
            assert!(!graph.contains_node(10));

            assert!(!graph.contains_node(14));
            assert!(!graph.contains_node(15));
            assert!(!graph.contains_node(16));
        }

        #[test]
        fn test_build_from_nodes_with_missing_dependencies() {
            // Test that nodes with missing dependencies (direct or transitive) are
            // KEPT in the graph but tracked for fail-closed evaluation.
            //
            // Graph structure:
            // 4 -> 2 -> 1 -> (999: missing)
            // 3 -> 1 -> (999: missing)
            // 6 -> (1000: missing)
            // 5 (no deps, valid)
            //
            // Expected: nodes 1, 2, 3, 4, 6 should be tracked (transitive propagation)
            // Only node 5 should NOT be tracked.
            let items = vec![
                TestItem::new(1, HashSet::from([999])), // Direct missing dependency
                TestItem::new(2, HashSet::from([1])),   // Transitive (via 1)
                TestItem::new(3, HashSet::from([1])),   // Transitive (via 1)
                TestItem::new(4, HashSet::from([2])),   // Transitive (via 2 -> 1)
                TestItem::new(5, HashSet::new()),       // No deps, valid
                TestItem::new(6, HashSet::from([1000])), // Direct missing dependency
            ];

            let (graph, errors, nodes_with_missing_deps) = build_graph_from_nodes(&items).unwrap();

            // All nodes are kept in the graph (no removal of broken flags)
            assert_eq!(
                graph.node_count(),
                6,
                "All nodes should be kept in the graph"
            );

            // Errors only track the DIRECT missing dependencies (not transitive)
            assert_eq!(
                errors.len(),
                2,
                "Expected two errors due to direct missing dependencies"
            );

            // Check that both missing dependencies are reported
            let missing_ids: Vec<_> = errors
                .iter()
                .filter_map(|e| {
                    if let GraphError::MissingDependency(id) = e {
                        Some(*id)
                    } else {
                        None
                    }
                })
                .collect();
            assert!(
                missing_ids.contains(&999),
                "Expected missing dependency 999"
            );
            assert!(
                missing_ids.contains(&1000),
                "Expected missing dependency 1000"
            );

            // All nodes that transitively depend on missing deps are tracked
            assert_eq!(
                nodes_with_missing_deps.len(),
                5,
                "Expected 5 nodes with missing deps (1, 2, 3, 4, 6)"
            );
            assert!(nodes_with_missing_deps.contains(&1));
            assert!(nodes_with_missing_deps.contains(&2));
            assert!(nodes_with_missing_deps.contains(&3));
            assert!(nodes_with_missing_deps.contains(&4));
            assert!(nodes_with_missing_deps.contains(&6));
            assert!(
                !nodes_with_missing_deps.contains(&5),
                "Node 5 should NOT be tracked (no missing deps)"
            );

            // All nodes are present in the graph
            assert!(graph.contains_node(1));
            assert!(graph.contains_node(2));
            assert!(graph.contains_node(3));
            assert!(graph.contains_node(4));
            assert!(graph.contains_node(5));
            assert!(graph.contains_node(6));
        }

        #[test]
        fn test_diamond_dependency_with_missing_dep() {
            // Test diamond dependency where one branch has a missing dep.
            //
            // Graph structure:
            //       1
            //      / \
            //     2   3
            //      \ /
            //       4 -> (999: missing)
            //
            // Expected: nodes 1, 2, 3, 4 should all be in nodes_with_missing_deps
            let items = vec![
                TestItem::new(1, HashSet::from([2, 3])), // Depends on both 2 and 3
                TestItem::new(2, HashSet::from([4])),    // Depends on 4
                TestItem::new(3, HashSet::from([4])),    // Depends on 4
                TestItem::new(4, HashSet::from([999])),  // Missing dependency
            ];

            let (graph, errors, nodes_with_missing_deps) = build_graph_from_nodes(&items).unwrap();

            assert_eq!(graph.node_count(), 4);
            assert_eq!(errors.len(), 1);

            // All nodes transitively depend on the missing dependency
            assert_eq!(nodes_with_missing_deps.len(), 4);
            assert!(nodes_with_missing_deps.contains(&1));
            assert!(nodes_with_missing_deps.contains(&2));
            assert!(nodes_with_missing_deps.contains(&3));
            assert!(nodes_with_missing_deps.contains(&4));
        }

        #[test]
        fn test_partial_missing_dependency_branch() {
            // Test where only one branch of dependencies has a missing dep.
            //
            // Graph structure:
            //   1 -> 2 -> (999: missing)
            //   3 -> 4 (valid, no missing deps)
            //   5 (no deps)
            //
            // Expected: only nodes 1, 2 should be in nodes_with_missing_deps
            let items = vec![
                TestItem::new(1, HashSet::from([2])), // Depends on 2 (transitive missing)
                TestItem::new(2, HashSet::from([999])), // Missing dependency
                TestItem::new(3, HashSet::from([4])), // Depends on 4 (valid)
                TestItem::new(4, HashSet::new()),     // No deps, valid
                TestItem::new(5, HashSet::new()),     // No deps, valid
            ];

            let (graph, errors, nodes_with_missing_deps) = build_graph_from_nodes(&items).unwrap();

            assert_eq!(graph.node_count(), 5);
            assert_eq!(errors.len(), 1);

            // Only nodes 1 and 2 should be tracked (the broken branch)
            assert_eq!(
                nodes_with_missing_deps.len(),
                2,
                "Expected 2 nodes with missing deps, got: {nodes_with_missing_deps:?}"
            );
            assert!(nodes_with_missing_deps.contains(&1));
            assert!(nodes_with_missing_deps.contains(&2));
            assert!(!nodes_with_missing_deps.contains(&3));
            assert!(!nodes_with_missing_deps.contains(&4));
            assert!(!nodes_with_missing_deps.contains(&5));
        }

        #[test]
        fn test_edges_referencing_absent_node_reports_missing_dependency() {
            use std::collections::HashMap;

            let items = vec![
                TestItem::new(1, HashSet::from([2])),
                TestItem::new(2, HashSet::new()),
            ];
            // Edge map claims node 2 depends on node 99, which isn't in nodes.
            let mut edges: HashMap<i64, HashSet<i64>> = HashMap::new();
            edges.insert(1, HashSet::from([2]));
            edges.insert(2, HashSet::from([99]));

            let (graph, errors, nodes_with_missing_deps) =
                DependencyGraph::from_nodes(items, &edges).unwrap();

            assert_eq!(graph.node_count(), 2);
            assert_eq!(errors.len(), 1);
            assert!(nodes_with_missing_deps.contains(&2));
            assert!(nodes_with_missing_deps.contains(&1));
        }

        #[test]
        fn test_node_with_no_entry_in_edges_map_treated_as_no_deps() {
            use std::collections::HashMap;

            let items = vec![
                TestItem::new(1, HashSet::from([2])),
                TestItem::new(2, HashSet::new()),
            ];
            // Only provide edges for node 1; node 2 has no entry at all.
            let mut edges: HashMap<i64, HashSet<i64>> = HashMap::new();
            edges.insert(1, HashSet::from([2]));

            let (graph, errors, nodes_with_missing_deps) =
                DependencyGraph::from_nodes(items, &edges).unwrap();

            assert_eq!(graph.node_count(), 2);
            assert!(errors.is_empty());
            assert!(nodes_with_missing_deps.is_empty());
        }
    }

    mod evaluation_stages {
        use super::*;

        #[test]
        fn test_linear_chain_stages() {
            let items = vec![
                TestItem::new(1, HashSet::from([2])),
                TestItem::new(2, HashSet::from([3])),
                TestItem::new(3, HashSet::new()),
            ];

            let (graph, errors, _) = build_graph_from_nodes(&items).unwrap();
            assert!(errors.is_empty(), "Expected no errors, found: {errors:?}");
            let stages = graph.evaluation_stages().unwrap();

            assert_eq!(stages.len(), 3);
            assert_eq!(
                stages[0].iter().map(|item| item.id).collect::<Vec<_>>(),
                vec![3]
            );
            assert_eq!(
                stages[1].iter().map(|item| item.id).collect::<Vec<_>>(),
                vec![2]
            );
            assert_eq!(
                stages[2].iter().map(|item| item.id).collect::<Vec<_>>(),
                vec![1]
            );
        }

        #[test]
        fn test_multiple_independent_nodes_stages() {
            let items = vec![
                TestItem::new(1, HashSet::new()),
                TestItem::new(2, HashSet::new()),
                TestItem::new(3, HashSet::new()),
            ];

            let (graph, errors, _) = build_graph_from_nodes(&items).unwrap();
            assert!(errors.is_empty(), "Expected no errors, found: {errors:?}");
            let stages = graph.evaluation_stages().unwrap();

            assert_eq!(stages.len(), 1);
            let stage_zero: HashSet<_> = stages[0].iter().map(|item| item.id).collect();
            assert_eq!(stage_zero, HashSet::from([1, 2, 3]));
        }

        #[test]
        fn test_multiple_disconnected_subgraphs_stages() {
            let items = vec![
                TestItem::new(1, HashSet::from([2])),
                TestItem::new(2, HashSet::from([3])),
                TestItem::new(3, HashSet::new()),
                TestItem::new(4, HashSet::from([5])),
                TestItem::new(5, HashSet::new()),
                TestItem::new(6, HashSet::new()),
            ];

            let (graph, errors, _) = build_graph_from_nodes(&items).unwrap();
            assert!(errors.is_empty(), "Expected no errors, found: {errors:?}");
            let stages = graph.evaluation_stages().unwrap();

            let expected_stages: Vec<HashSet<_>> = vec![
                HashSet::from([3, 5, 6]),
                HashSet::from([2, 4]),
                HashSet::from([1]),
            ];

            assert_eq!(stages.len(), expected_stages.len());

            assert!(
                stages
                    .iter()
                    .zip(expected_stages.iter())
                    .all(|(actual, expected)| {
                        actual.iter().map(|item| item.id).collect::<HashSet<_>>() == *expected
                    }),
                "Stages do not match expected order"
            );
        }

        #[test]
        fn test_complex_dag_stages() {
            let items = vec![
                TestItem::new(1, HashSet::from([2, 3])),
                TestItem::new(2, HashSet::from([4])),
                TestItem::new(3, HashSet::from([4])),
                TestItem::new(4, HashSet::new()),
            ];

            let (graph, errors, _) = build_graph_from_nodes(&items).unwrap();
            assert!(errors.is_empty(), "Expected no errors, found: {errors:?}");
            let stages = graph.evaluation_stages().unwrap();

            let expected_stages: Vec<HashSet<_>> = vec![
                HashSet::from([4]),
                HashSet::from([2, 3]),
                HashSet::from([1]),
            ];

            assert_eq!(stages.len(), expected_stages.len());

            assert!(
                stages
                    .iter()
                    .zip(expected_stages.iter())
                    .all(|(actual, expected)| {
                        actual.iter().map(|item| item.id).collect::<HashSet<_>>() == *expected
                    }),
                "Stages do not match expected order"
            );
        }

        #[test]
        fn test_evaluation_stages_complex_shared_dependencies() {
            let items = vec![
                TestItem::new(1, HashSet::from([2])),
                TestItem::new(2, HashSet::from([3])),
                TestItem::new(3, HashSet::from([4])),
                TestItem::new(4, HashSet::from([6])),
                TestItem::new(5, HashSet::from([4])),
                TestItem::new(6, HashSet::new()),
                TestItem::new(7, HashSet::new()),
                TestItem::new(8, HashSet::from([9])),
                TestItem::new(9, HashSet::new()),
            ];

            let (graph, errors, _) = build_graph_from_nodes(&items).unwrap();
            assert!(errors.is_empty(), "Expected no errors, found: {errors:?}");
            let stages = graph.evaluation_stages().unwrap();

            let expected_stages: Vec<HashSet<_>> = vec![
                HashSet::from([6, 7, 9]),
                HashSet::from([4, 8]),
                HashSet::from([3, 5]),
                HashSet::from([2]),
                HashSet::from([1]),
            ];

            assert_eq!(stages.len(), expected_stages.len());

            assert!(
                stages
                    .iter()
                    .zip(expected_stages.iter())
                    .all(|(actual, expected)| {
                        actual.iter().map(|item| item.id).collect::<HashSet<_>>() == *expected
                    }),
                "Stages do not match expected order"
            );
        }
    }

    mod into_evaluation_stages {
        use super::*;

        /// Verifies that `into_evaluation_stages` (owned) produces the same stage
        /// groupings as `evaluation_stages` (borrowed) across varied graph shapes.
        #[test]
        fn test_into_evaluation_stages_matches_borrowed_version() {
            let cases: Vec<(&str, Vec<TestItem>)> = vec![
                (
                    "linear_chain",
                    vec![
                        TestItem::new(1, HashSet::from([2])),
                        TestItem::new(2, HashSet::from([3])),
                        TestItem::new(3, HashSet::new()),
                    ],
                ),
                (
                    "independent_nodes",
                    vec![
                        TestItem::new(1, HashSet::new()),
                        TestItem::new(2, HashSet::new()),
                        TestItem::new(3, HashSet::new()),
                    ],
                ),
                (
                    "diamond_dag",
                    vec![
                        TestItem::new(1, HashSet::from([2, 3])),
                        TestItem::new(2, HashSet::from([4])),
                        TestItem::new(3, HashSet::from([4])),
                        TestItem::new(4, HashSet::new()),
                    ],
                ),
                (
                    "complex_shared_deps",
                    vec![
                        TestItem::new(1, HashSet::from([2])),
                        TestItem::new(2, HashSet::from([3])),
                        TestItem::new(3, HashSet::from([4])),
                        TestItem::new(4, HashSet::from([6])),
                        TestItem::new(5, HashSet::from([4])),
                        TestItem::new(6, HashSet::new()),
                        TestItem::new(7, HashSet::new()),
                        TestItem::new(8, HashSet::from([9])),
                        TestItem::new(9, HashSet::new()),
                    ],
                ),
            ];

            for (name, items) in cases {
                // Build two identical graphs — one for borrowed, one for owned
                let (borrowed_graph, errors, _) = build_graph_from_nodes(&items).unwrap();
                assert!(errors.is_empty(), "{name}: unexpected errors: {errors:?}");
                let (owned_graph, errors, _) = build_graph_from_nodes(&items).unwrap();
                assert!(errors.is_empty(), "{name}: unexpected errors: {errors:?}");

                let borrowed_stages = borrowed_graph.evaluation_stages().unwrap();
                let owned_stages = owned_graph.into_evaluation_stages().unwrap();

                assert_eq!(
                    borrowed_stages.len(),
                    owned_stages.len(),
                    "{name}: stage count mismatch"
                );

                for (i, (borrowed, owned)) in
                    borrowed_stages.iter().zip(owned_stages.iter()).enumerate()
                {
                    let borrowed_ids: HashSet<_> = borrowed.iter().map(|item| item.id).collect();
                    let owned_ids: HashSet<_> = owned.iter().map(|item| item.id).collect();
                    assert_eq!(
                        borrowed_ids, owned_ids,
                        "{name}: stage {i} mismatch: borrowed={borrowed_ids:?}, owned={owned_ids:?}"
                    );
                }
            }
        }
    }

    mod compute_evaluation_metadata {
        use super::*;

        #[test]
        fn test_empty_graph() {
            let nodes: Vec<TestItem> = vec![];
            let (graph, _, missing) = build_graph_from_nodes(&nodes).unwrap();
            let result = graph.compute_evaluation_metadata(&missing).unwrap();

            assert!(result.stages.is_empty());
            assert!(result.transitive_deps.is_empty());
            assert!(result.nodes_with_missing_deps.is_empty());
        }

        #[test]
        fn test_linear_chain() {
            // 1 → 2 → 3 (1 depends on 2, 2 depends on 3)
            let nodes = vec![
                TestItem::new(1, HashSet::from([2])),
                TestItem::new(2, HashSet::from([3])),
                TestItem::new(3, HashSet::new()),
            ];
            let (graph, _, missing) = build_graph_from_nodes(&nodes).unwrap();
            let result = graph.compute_evaluation_metadata(&missing).unwrap();

            assert_eq!(result.stages, vec![vec![3], vec![2], vec![1]]);
            assert!(result.transitive_deps[&3].is_empty());
            assert_eq!(result.transitive_deps[&2], HashSet::from([3]));
            assert_eq!(result.transitive_deps[&1], HashSet::from([2, 3]));
            assert!(result.nodes_with_missing_deps.is_empty());
        }

        #[test]
        fn test_diamond() {
            // 4 depends on 2 and 3; both 2 and 3 depend on 1
            let nodes = vec![
                TestItem::new(1, HashSet::new()),
                TestItem::new(2, HashSet::from([1])),
                TestItem::new(3, HashSet::from([1])),
                TestItem::new(4, HashSet::from([2, 3])),
            ];
            let (graph, _, missing) = build_graph_from_nodes(&nodes).unwrap();
            let result = graph.compute_evaluation_metadata(&missing).unwrap();

            assert_eq!(result.stages.len(), 3);
            assert_eq!(result.stages[0], vec![1]);
            assert_eq!(result.stages[1], vec![2, 3]);
            assert_eq!(result.stages[2], vec![4]);
            assert_eq!(result.transitive_deps[&4], HashSet::from([1, 2, 3]));
            assert!(result.nodes_with_missing_deps.is_empty());
        }

        #[test]
        fn test_missing_dep_propagation() {
            // Node 1 has no deps, node 2 depends on 1, node 3 depends on 2
            // Mark node 1 as having missing deps — should propagate to 2 and 3
            let nodes = vec![
                TestItem::new(1, HashSet::new()),
                TestItem::new(2, HashSet::from([1])),
                TestItem::new(3, HashSet::from([2])),
            ];
            let (graph, _, _) = build_graph_from_nodes(&nodes).unwrap();
            let pre_missing = HashSet::from([1_i64]);
            let result = graph.compute_evaluation_metadata(&pre_missing).unwrap();

            assert_eq!(result.nodes_with_missing_deps, vec![1, 2, 3]);
        }
    }
}

#[cfg(test)]
mod evaluation_metadata_serde_tests {
    use crate::flags::flag_models::EvaluationMetadata;
    use std::collections::{HashMap, HashSet};

    #[test]
    fn test_round_trip_serialization() {
        let original = EvaluationMetadata {
            dependency_stages: vec![vec![3, 4], vec![2], vec![1]],
            flags_with_missing_deps: vec![4],
            transitive_deps: HashMap::from([
                (1, HashSet::from([2, 3])),
                (2, HashSet::from([3])),
                (3, HashSet::new()),
                (4, HashSet::new()),
            ]),
        };

        let json = serde_json::to_string(&original).expect("serialize");
        let deserialized: EvaluationMetadata =
            serde_json::from_str(&json).expect("deserialize round-trip");

        assert_eq!(deserialized.dependency_stages, original.dependency_stages);
        assert_eq!(
            deserialized.flags_with_missing_deps,
            original.flags_with_missing_deps
        );
        assert_eq!(deserialized.transitive_deps, original.transitive_deps);
    }

    #[test]
    fn test_empty_transitive_deps_round_trip() {
        let original = EvaluationMetadata {
            dependency_stages: vec![vec![1]],
            flags_with_missing_deps: vec![],
            transitive_deps: HashMap::new(),
        };

        let json = serde_json::to_string(&original).expect("serialize");
        let deserialized: EvaluationMetadata = serde_json::from_str(&json).expect("deserialize");

        assert!(deserialized.transitive_deps.is_empty());
    }

    #[test]
    fn test_deserialize_string_keyed_map_from_python_format() {
        // Python serializes int keys as strings in JSON
        let json = r#"{
            "dependency_stages": [[1]],
            "flags_with_missing_deps": [],
            "transitive_deps": {"1": [2, 3], "2": [3], "3": []}
        }"#;

        let meta: EvaluationMetadata = serde_json::from_str(json).expect("deserialize");

        assert_eq!(meta.transitive_deps[&1], HashSet::from([2, 3]));
        assert_eq!(meta.transitive_deps[&2], HashSet::from([3]));
        assert!(meta.transitive_deps[&3].is_empty());
    }

    #[test]
    fn test_deserialize_non_numeric_string_key_fails() {
        let json = r#"{
            "dependency_stages": [[1]],
            "flags_with_missing_deps": [],
            "transitive_deps": {"abc": [1, 2]}
        }"#;

        let result = serde_json::from_str::<EvaluationMetadata>(json);
        assert!(
            result.is_err(),
            "Non-numeric string key should fail deserialization"
        );
    }
}

#[cfg(test)]
mod precomputed_dependency_graph_tests {
    use crate::flags::flag_models::{EvaluationMetadata, FeatureFlag, FeatureFlagList};
    use crate::mock;
    use crate::properties::property_models::PropertyType;
    use crate::utils::graph_utils::PrecomputedDependencyGraph;
    use crate::utils::mock::MockInto;
    use crate::utils::test_utils::flag_list_with_metadata;
    use serde_json::json;
    use std::collections::{HashMap, HashSet};

    /// Creates a test flag with the given dependencies and active state.
    ///
    /// For deleted flags, set `.deleted = true` on the returned value.
    fn flag(id: i32, key: &str, deps: HashSet<i32>, active: bool) -> FeatureFlag {
        let dep_filters: Vec<crate::properties::property_models::PropertyFilter> = deps
            .into_iter()
            .map(|dep_id| {
                mock!(crate::properties::property_models::PropertyFilter,
                    key: dep_id.to_string(),
                    value: Some(json!(true)),
                    prop_type: PropertyType::Flag
                )
            })
            .collect();

        if dep_filters.is_empty() {
            mock!(FeatureFlag, id: id, key: key.mock_into(), active: active)
        } else {
            mock!(FeatureFlag, id: id, key: key.mock_into(), active: active, filters: dep_filters.mock_into())
        }
    }

    /// Extracts sorted flag keys from evaluation stages for deterministic comparison.
    fn stage_keys(stages: &[Vec<FeatureFlag>]) -> Vec<Vec<String>> {
        stages
            .iter()
            .map(|stage| {
                let mut keys: Vec<String> = stage.iter().map(|f| f.key.clone()).collect();
                keys.sort();
                keys
            })
            .collect()
    }

    #[test]
    fn test_build_no_dependencies() {
        let flags = vec![
            flag(1, "flag_a", HashSet::new(), true),
            flag(2, "flag_b", HashSet::new(), true),
            flag(3, "flag_c", HashSet::new(), true),
        ];
        let feature_flags = flag_list_with_metadata(flags);

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, None);

        // All flags are independent, so they should be in a single stage
        assert_eq!(precomputed.evaluation_stages.len(), 1);
        assert_eq!(stage_keys(&precomputed.evaluation_stages)[0].len(), 3);
        assert!(precomputed.flags_with_missing_deps.is_empty());
        assert_eq!(precomputed.error_count, 0);
        assert!(!precomputed.has_cycle_errors);
    }

    #[test]
    fn test_build_linear_chain() {
        // flag_a -> flag_b -> flag_c (flag_a depends on flag_b, which depends on flag_c)
        let flags = vec![
            flag(1, "flag_a", HashSet::from([2]), true),
            flag(2, "flag_b", HashSet::from([3]), true),
            flag(3, "flag_c", HashSet::new(), true),
        ];
        let feature_flags = flag_list_with_metadata(flags);

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, None);

        // Three stages: flag_c, then flag_b, then flag_a
        assert_eq!(precomputed.evaluation_stages.len(), 3);
        assert_eq!(
            stage_keys(&precomputed.evaluation_stages)[0],
            vec!["flag_c"]
        );
        assert_eq!(
            stage_keys(&precomputed.evaluation_stages)[1],
            vec!["flag_b"]
        );
        assert_eq!(
            stage_keys(&precomputed.evaluation_stages)[2],
            vec!["flag_a"]
        );
    }

    #[test]
    fn test_build_diamond_dependency() {
        //   flag_a
        //   /    \
        // flag_b  flag_c
        //   \    /
        //   flag_d
        let flags = vec![
            flag(1, "flag_a", HashSet::from([2, 3]), true),
            flag(2, "flag_b", HashSet::from([4]), true),
            flag(3, "flag_c", HashSet::from([4]), true),
            flag(4, "flag_d", HashSet::new(), true),
        ];
        let feature_flags = flag_list_with_metadata(flags);

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, None);

        // Three stages: flag_d, then flag_b+flag_c, then flag_a
        assert_eq!(precomputed.evaluation_stages.len(), 3);
        assert_eq!(
            stage_keys(&precomputed.evaluation_stages)[0],
            vec!["flag_d"]
        );
        assert_eq!(
            stage_keys(&precomputed.evaluation_stages)[1],
            vec!["flag_b", "flag_c"]
        );
        assert_eq!(
            stage_keys(&precomputed.evaluation_stages)[2],
            vec!["flag_a"]
        );
    }

    #[test]
    fn test_build_missing_dependency() {
        // flag_a depends on flag_b (id=2), but flag_b doesn't exist.
        // Django excludes missing-dep flags from dependency_stages, so we hand-craft
        // the metadata to match production behavior rather than computing it.
        let feature_flags = FeatureFlagList {
            flags: vec![
                flag(1, "flag_a", HashSet::from([2]), true),
                flag(3, "flag_c", HashSet::new(), true),
            ],
            evaluation_metadata: EvaluationMetadata {
                dependency_stages: vec![vec![3]],
                flags_with_missing_deps: vec![1],
                transitive_deps: HashMap::from([(1, HashSet::from([2])), (3, HashSet::new())]),
            },
            ..Default::default()
        };

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, None);

        assert!(precomputed.flags_with_missing_deps.contains(&1));
        assert!(!precomputed.flags_with_missing_deps.contains(&3));
        assert!(precomputed.error_count > 0);
    }

    #[test]
    fn test_build_transitive_missing_dependency() {
        // flag_a -> flag_b -> (missing flag_c)
        // flag_a should also be marked as having missing deps
        let feature_flags = FeatureFlagList {
            flags: vec![
                flag(1, "flag_a", HashSet::from([2]), true),
                flag(2, "flag_b", HashSet::from([999]), true),
            ],
            evaluation_metadata: EvaluationMetadata {
                dependency_stages: vec![vec![2], vec![1]],
                flags_with_missing_deps: vec![1, 2],
                transitive_deps: HashMap::from([(1, HashSet::from([2])), (2, HashSet::new())]),
            },
            ..Default::default()
        };

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, None);

        assert!(
            precomputed.flags_with_missing_deps.contains(&1),
            "flag_a should be transitively marked as missing deps"
        );
        assert!(
            precomputed.flags_with_missing_deps.contains(&2),
            "flag_b should be directly marked as missing deps"
        );
    }

    #[test]
    fn test_build_empty_flag_list() {
        let feature_flags = flag_list_with_metadata(vec![]);

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, None);

        assert!(precomputed.evaluation_stages.is_empty());
        assert!(precomputed.flags_with_missing_deps.is_empty());
        assert_eq!(precomputed.error_count, 0);
    }

    #[test]
    fn test_build_single_flag_no_dependencies() {
        let flags = vec![flag(1, "solo_flag", HashSet::new(), true)];
        let feature_flags = flag_list_with_metadata(flags);

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, None);

        assert_eq!(precomputed.evaluation_stages.len(), 1);
        assert_eq!(precomputed.evaluation_stages[0].len(), 1);
        assert_eq!(precomputed.evaluation_stages[0][0].key, "solo_flag");
    }

    #[test]
    fn test_build_inactive_flag_skips_dependencies() {
        // Inactive flag references non-existent dependency — should not produce errors.
        // The inactive flag is in filtered_out_flag_ids, so its missing deps are excluded.
        let feature_flags = FeatureFlagList {
            flags: vec![
                flag(1, "inactive_flag", HashSet::from([999]), false),
                flag(2, "active_flag", HashSet::new(), true),
            ],
            filtered_out_flag_ids: HashSet::from([1]),
            evaluation_metadata: EvaluationMetadata {
                dependency_stages: vec![vec![2]],
                flags_with_missing_deps: vec![],
                transitive_deps: HashMap::from([(2, HashSet::new())]),
            },
            cohorts: None,
        };

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, None);

        assert!(precomputed.flags_with_missing_deps.is_empty());
        assert_eq!(precomputed.error_count, 0);
    }

    #[test]
    fn test_build_with_cycle() {
        // flag_a -> flag_b -> flag_a (cycle), flag_c is independent
        let flags = vec![
            flag(1, "flag_a", HashSet::from([2]), true),
            flag(2, "flag_b", HashSet::from([1]), true),
            flag(3, "flag_c", HashSet::new(), true),
        ];
        let feature_flags = flag_list_with_metadata(flags);

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, None);

        assert!(precomputed.has_cycle_errors);
        assert!(precomputed.error_count > 0);

        // Cyclic flags are removed; only flag_c should remain
        let all_keys: HashSet<String> = precomputed
            .evaluation_stages
            .iter()
            .flat_map(|stage| stage.iter().map(|f| f.key.clone()))
            .collect();
        assert!(all_keys.contains("flag_c"));
        assert!(
            !all_keys.contains("flag_a"),
            "Cyclic flag should be removed"
        );
        assert!(
            !all_keys.contains("flag_b"),
            "Cyclic flag should be removed"
        );
    }

    // --- Precomputed data tests: verify build_from_precomputed path ---

    #[test]
    fn test_deserialization_without_new_fields() {
        let json = r#"{
            "id": 1, "team_id": 1, "key": "test", "name": "Test",
            "filters": {"groups": []}, "deleted": false, "active": true
        }"#;
        let flag: FeatureFlag = serde_json::from_str(json).unwrap();
        assert_eq!(flag.id, 1);
        assert_eq!(flag.key, "test");
        assert!(flag.active);
    }

    #[test]
    fn test_deserialization_with_evaluation_metadata() {
        use crate::flags::flag_models::HypercacheFlagsWrapper;

        let json = r#"{
            "flags": [
                {"id": 1, "team_id": 1, "key": "test", "name": "Test",
                 "filters": {"groups": []}, "deleted": false, "active": true}
            ],
            "evaluation_metadata": {
                "dependency_stages": [[1]],
                "flags_with_missing_deps": [],
                "transitive_deps": {"1": []}
            }
        }"#;
        let wrapper: HypercacheFlagsWrapper = serde_json::from_str(json).unwrap();
        assert_eq!(wrapper.flags.len(), 1);
        assert_eq!(wrapper.flags[0].key, "test");
        let ctx = wrapper.evaluation_metadata;
        assert_eq!(ctx.dependency_stages, vec![vec![1]]);
        assert!(ctx.flags_with_missing_deps.is_empty());
        assert_eq!(ctx.transitive_deps[&1], HashSet::<i32>::new());
    }

    #[test]
    fn test_precomputed_path_selected_when_fields_present() {
        // Flags with precomputed data: A(1) -> B(2) -> C(3)
        let feature_flags = FeatureFlagList {
            flags: vec![
                flag(1, "flag_a", HashSet::from([2]), true),
                flag(2, "flag_b", HashSet::from([3]), true),
                flag(3, "flag_c", HashSet::new(), true),
            ],
            evaluation_metadata: EvaluationMetadata {
                dependency_stages: vec![vec![3], vec![2], vec![1]],
                flags_with_missing_deps: vec![],
                transitive_deps: HashMap::from([
                    (1, HashSet::from([2, 3])),
                    (2, HashSet::from([3])),
                    (3, HashSet::new()),
                ]),
            },
            ..Default::default()
        };

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, None);

        // Verify fast path outputs (error_count=0, no cycles from precomputed)
        assert_eq!(precomputed.error_count, 0);
        assert!(!precomputed.has_cycle_errors);

        // Verify stages: flag_c first, then flag_b, then flag_a
        assert_eq!(precomputed.evaluation_stages.len(), 3);
        assert_eq!(
            stage_keys(&precomputed.evaluation_stages)[0],
            vec!["flag_c"]
        );
        assert_eq!(
            stage_keys(&precomputed.evaluation_stages)[1],
            vec!["flag_b"]
        );
        assert_eq!(
            stage_keys(&precomputed.evaluation_stages)[2],
            vec!["flag_a"]
        );
    }

    #[test]
    fn test_precomputed_missing_deps_collected() {
        let feature_flags = FeatureFlagList {
            flags: vec![
                flag(1, "flag_a", HashSet::from([2]), true),
                flag(2, "flag_b", HashSet::new(), true),
                flag(3, "flag_c", HashSet::new(), true),
            ],
            evaluation_metadata: EvaluationMetadata {
                dependency_stages: vec![vec![2, 3], vec![1]],
                flags_with_missing_deps: vec![1, 2],
                transitive_deps: HashMap::from([
                    (1, HashSet::from([2])),
                    (2, HashSet::new()),
                    (3, HashSet::new()),
                ]),
            },
            ..Default::default()
        };

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, None);

        assert!(precomputed.flags_with_missing_deps.contains(&1));
        assert!(precomputed.flags_with_missing_deps.contains(&2));
        assert!(!precomputed.flags_with_missing_deps.contains(&3));
    }

    #[test]
    fn test_precomputed_path_handles_cycles_via_missing_deps() {
        // Simulate Django output for A(1)->B(2)->A(1) cycle plus independent C(3)
        let feature_flags = FeatureFlagList {
            flags: vec![
                flag(1, "flag_a", HashSet::from([2]), true),
                flag(2, "flag_b", HashSet::from([1]), true),
                flag(3, "flag_c", HashSet::new(), true),
            ],
            evaluation_metadata: EvaluationMetadata {
                dependency_stages: vec![vec![3]], // only C, cycled flags excluded
                flags_with_missing_deps: vec![1, 2],
                transitive_deps: HashMap::from([
                    (1, HashSet::from([2])),
                    (2, HashSet::from([1])),
                    (3, HashSet::new()),
                ]),
            },
            ..Default::default()
        };

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, None);

        // Cyclic flags should be excluded from stages
        let all_keys: HashSet<String> = precomputed
            .evaluation_stages
            .iter()
            .flat_map(|s| s.iter().map(|f| f.key.clone()))
            .collect();
        assert!(
            !all_keys.contains("flag_a"),
            "Cyclic flag should be excluded from stages"
        );
        assert!(
            !all_keys.contains("flag_b"),
            "Cyclic flag should be excluded from stages"
        );
        assert!(all_keys.contains("flag_c"));

        // Both cyclic flags should be in missing deps
        assert!(precomputed.flags_with_missing_deps.contains(&1));
        assert!(precomputed.flags_with_missing_deps.contains(&2));
        assert!(!precomputed.flags_with_missing_deps.contains(&3));

        // Error count = flags_with_missing_deps (A and B are cycle participants)
        assert_eq!(precomputed.error_count, 2);
        assert!(precomputed.has_cycle_errors);
    }

    #[test]
    fn test_filtered_out_flags_do_not_inflate_cycle_count() {
        // Three flags total: flag_a(1) active, flag_b(2) active, flag_c(3) inactive.
        // flag_c is in filtered_out_flag_ids and excluded from dependency_stages.
        // Without the fix, cycle_count = flags.len(3) - flags_in_stages.len(2) = 1,
        // falsely reporting a cycle.
        let feature_flags = FeatureFlagList {
            flags: vec![
                flag(1, "flag_a", HashSet::new(), true),
                flag(2, "flag_b", HashSet::new(), true),
                flag(3, "flag_c", HashSet::new(), false),
            ],
            filtered_out_flag_ids: HashSet::from([3]),
            evaluation_metadata: EvaluationMetadata {
                dependency_stages: vec![vec![1, 2]],
                flags_with_missing_deps: vec![],
                transitive_deps: HashMap::from([(1, HashSet::new()), (2, HashSet::new())]),
            },
            cohorts: None,
        };

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, None);

        assert!(!precomputed.has_cycle_errors);
        assert_eq!(precomputed.error_count, 0);
    }

    #[test]
    fn test_runtime_filtered_active_flag_excluded_from_precomputed_stages() {
        // Django includes all 3 active flags in dependency_stages.
        // At request time, flag_b(2) is runtime-filtered (e.g., tag mismatch).
        let feature_flags = FeatureFlagList {
            flags: vec![
                flag(1, "flag_a", HashSet::from([2]), true),
                flag(2, "flag_b", HashSet::new(), true),
                flag(3, "flag_c", HashSet::new(), true),
            ],
            filtered_out_flag_ids: HashSet::from([2]),
            evaluation_metadata: EvaluationMetadata {
                dependency_stages: vec![vec![2, 3], vec![1]],
                flags_with_missing_deps: vec![],
                transitive_deps: HashMap::from([
                    (1, HashSet::from([2])),
                    (2, HashSet::new()),
                    (3, HashSet::new()),
                ]),
            },
            cohorts: None,
        };

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, None);

        let all_ids: HashSet<i32> = precomputed
            .evaluation_stages
            .iter()
            .flat_map(|s| s.iter().map(|f| f.id))
            .collect();
        assert!(all_ids.contains(&1));
        assert!(
            !all_ids.contains(&2),
            "Runtime-filtered flag should be excluded"
        );
        assert!(all_ids.contains(&3));

        assert!(!precomputed.has_cycle_errors);
        assert_eq!(precomputed.error_count, 0);
    }

    // --- build with flag_keys=Some tests ---

    #[test]
    fn test_build_with_flag_keys_precomputed_filters_to_requested() {
        // A(1)->B(2)->C(3), D(4) independent
        let feature_flags = FeatureFlagList {
            flags: vec![
                flag(1, "flag_a", HashSet::from([2]), true),
                flag(2, "flag_b", HashSet::from([3]), true),
                flag(3, "flag_c", HashSet::new(), true),
                flag(4, "flag_d", HashSet::new(), true),
            ],
            evaluation_metadata: EvaluationMetadata {
                dependency_stages: vec![vec![3, 4], vec![2], vec![1]],
                flags_with_missing_deps: vec![],
                transitive_deps: HashMap::from([
                    (1, HashSet::from([2, 3])),
                    (2, HashSet::from([3])),
                    (3, HashSet::new()),
                    (4, HashSet::new()),
                ]),
            },
            ..Default::default()
        };

        let precomputed =
            PrecomputedDependencyGraph::build(&feature_flags, Some(&["flag_a".to_string()]));

        let all_keys: HashSet<String> = precomputed
            .evaluation_stages
            .iter()
            .flat_map(|s| s.iter().map(|f| f.key.clone()))
            .collect();

        assert!(all_keys.contains("flag_a"));
        assert!(all_keys.contains("flag_b"));
        assert!(all_keys.contains("flag_c"));
        assert!(
            !all_keys.contains("flag_d"),
            "Unrequested independent flag should be excluded"
        );
    }

    #[test]
    fn test_build_with_flag_keys_precomputed_single_no_deps() {
        // Three independent flags, request only one
        let feature_flags = FeatureFlagList {
            flags: vec![
                flag(1, "flag_a", HashSet::new(), true),
                flag(2, "flag_b", HashSet::new(), true),
                flag(3, "flag_c", HashSet::new(), true),
            ],
            evaluation_metadata: EvaluationMetadata {
                dependency_stages: vec![vec![1, 2, 3]],
                flags_with_missing_deps: vec![],
                transitive_deps: HashMap::from([
                    (1, HashSet::new()),
                    (2, HashSet::new()),
                    (3, HashSet::new()),
                ]),
            },
            ..Default::default()
        };

        let precomputed =
            PrecomputedDependencyGraph::build(&feature_flags, Some(&["flag_b".to_string()]));

        assert_eq!(precomputed.evaluation_stages.len(), 1);
        assert_eq!(precomputed.evaluation_stages[0].len(), 1);
        assert_eq!(precomputed.evaluation_stages[0][0].key, "flag_b");
    }

    #[test]
    fn test_build_with_flag_keys_precomputed_nonexistent_key() {
        let feature_flags = FeatureFlagList {
            flags: vec![flag(1, "flag_a", HashSet::new(), true)],
            evaluation_metadata: EvaluationMetadata {
                dependency_stages: vec![vec![1]],
                flags_with_missing_deps: vec![],
                transitive_deps: HashMap::from([(1, HashSet::new())]),
            },
            ..Default::default()
        };

        let precomputed =
            PrecomputedDependencyGraph::build(&feature_flags, Some(&["nonexistent".to_string()]));

        assert!(
            precomputed.evaluation_stages.is_empty(),
            "Nonexistent key should result in empty stages"
        );
    }

    #[test]
    fn test_build_with_flag_keys_precomputed_preserves_missing_deps() {
        // flag_a(1) -> flag_b(2) -> (missing 999), flag_c(3) independent
        let feature_flags = FeatureFlagList {
            flags: vec![
                flag(1, "flag_a", HashSet::from([2]), true),
                flag(2, "flag_b", HashSet::from([999]), true),
                flag(3, "flag_c", HashSet::new(), true),
            ],
            evaluation_metadata: EvaluationMetadata {
                dependency_stages: vec![vec![2, 3], vec![1]],
                flags_with_missing_deps: vec![1, 2],
                transitive_deps: HashMap::from([
                    (1, HashSet::from([2])),
                    (2, HashSet::new()),
                    (3, HashSet::new()),
                ]),
            },
            ..Default::default()
        };

        let precomputed =
            PrecomputedDependencyGraph::build(&feature_flags, Some(&["flag_a".to_string()]));

        assert!(precomputed.flags_with_missing_deps.contains(&1));
        assert!(precomputed.flags_with_missing_deps.contains(&2));
        assert!(
            !precomputed.flags_with_missing_deps.contains(&3),
            "Unrequested flag_c should not appear in missing deps"
        );
    }

    #[test]
    fn test_build_with_flag_keys_precomputed_multiple_keys_shared_deps() {
        // flag_a(1)->flag_c(3), flag_b(2)->flag_c(3), flag_d(4) independent
        let feature_flags = FeatureFlagList {
            flags: vec![
                flag(1, "flag_a", HashSet::from([3]), true),
                flag(2, "flag_b", HashSet::from([3]), true),
                flag(3, "flag_c", HashSet::new(), true),
                flag(4, "flag_d", HashSet::new(), true),
            ],
            evaluation_metadata: EvaluationMetadata {
                dependency_stages: vec![vec![3, 4], vec![1, 2]],
                flags_with_missing_deps: vec![],
                transitive_deps: HashMap::from([
                    (1, HashSet::from([3])),
                    (2, HashSet::from([3])),
                    (3, HashSet::new()),
                    (4, HashSet::new()),
                ]),
            },
            ..Default::default()
        };

        let precomputed = PrecomputedDependencyGraph::build(
            &feature_flags,
            Some(&["flag_a".to_string(), "flag_b".to_string()]),
        );

        let all_keys: HashSet<String> = precomputed
            .evaluation_stages
            .iter()
            .flat_map(|s| s.iter().map(|f| f.key.clone()))
            .collect();

        assert!(all_keys.contains("flag_a"));
        assert!(all_keys.contains("flag_b"));
        assert!(
            all_keys.contains("flag_c"),
            "Shared dependency should be included"
        );
        assert!(
            !all_keys.contains("flag_d"),
            "Unrelated flag should be excluded"
        );
    }

    #[test]
    fn test_build_with_flag_keys_filters_independent_flags_on_pg_fallback() {
        // Simulates PG fallback: single_stage metadata has per-flag empty transitive_deps.
        // flag_keys filtering should work for independent flags since each flag maps to
        // an empty dep set, allowing unrelated flags to be skipped.
        let flags = vec![
            flag(1, "flag_a", HashSet::new(), true),
            flag(2, "flag_b", HashSet::new(), true),
            flag(3, "flag_c", HashSet::new(), true),
        ];
        let feature_flags = FeatureFlagList {
            flags: flags.clone(),
            evaluation_metadata: EvaluationMetadata::single_stage(&flags),
            ..Default::default()
        };

        let precomputed =
            PrecomputedDependencyGraph::build(&feature_flags, Some(&["flag_a".to_string()]));

        let all_keys: HashSet<String> = precomputed
            .evaluation_stages
            .iter()
            .flat_map(|s| s.iter().map(|f| f.key.clone()))
            .collect();

        assert_eq!(all_keys, HashSet::from(["flag_a".to_string()]));
    }

    #[test]
    fn test_precomputed_path_handles_phantom_ids_in_stages() {
        // dependency_stages references flag ID 999 which doesn't exist in flags vec.
        // This simulates stale metadata from Django where a flag was deleted after
        // the dependency stages were computed.
        let feature_flags = FeatureFlagList {
            flags: vec![
                flag(1, "flag_a", HashSet::new(), true),
                flag(2, "flag_b", HashSet::from([1]), true),
            ],
            evaluation_metadata: EvaluationMetadata {
                dependency_stages: vec![
                    vec![1, 999], // 999 is a phantom ID
                    vec![2],
                ],
                flags_with_missing_deps: vec![],
                transitive_deps: HashMap::from([
                    (1, HashSet::new()),
                    (2, HashSet::from([1])),
                    (999, HashSet::new()),
                ]),
            },
            ..Default::default()
        };

        let precomputed = PrecomputedDependencyGraph::build(&feature_flags, None);

        // Phantom ID 999 should be silently skipped — only real flags appear in stages
        let all_keys: HashSet<String> = precomputed
            .evaluation_stages
            .iter()
            .flat_map(|s| s.iter().map(|f| f.key.clone()))
            .collect();
        assert_eq!(all_keys.len(), 2);
        assert!(all_keys.contains("flag_a"));
        assert!(all_keys.contains("flag_b"));

        // Phantom ID still counts as "staged" for cycle detection math:
        // global_flags_in_stages_count = 3 (IDs 1, 999, 2 — all non-filtered-out)
        // cycle_count = flags.len() (2) - filtered_out (0) - staged (3) = 0 (saturating)
        assert_eq!(precomputed.error_count, 0);
        assert!(!precomputed.has_cycle_errors);
    }
}
