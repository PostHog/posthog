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
}

#[cfg(test)]
mod filter_graph_by_keys_tests {
    use super::make_flag_list;
    use crate::flags::flag_models::FeatureFlag;
    use crate::utils::graph_utils::{
        build_dependency_graph, filter_graph_by_keys, DependencyGraphResult, FilteredGraphResult,
    };
    use std::collections::HashSet;

    // Helper function to create a test flag with dependencies for graph testing
    fn create_test_flag_with_dependencies(
        id: i32,
        key: &str,
        dependencies: HashSet<i32>,
    ) -> FeatureFlag {
        super::create_flag_with_deps(id, key, dependencies, true, false)
    }

    #[test]
    fn test_filter_graph_by_keys_no_requested_keys() {
        // Create a simple graph with no dependencies
        let flag1 = create_test_flag_with_dependencies(1, "flag1", HashSet::new());
        let flag2 = create_test_flag_with_dependencies(2, "flag2", HashSet::new());
        let flag3 = create_test_flag_with_dependencies(3, "flag3", HashSet::new());

        let flags = vec![flag1, flag2, flag3];
        let feature_flags = make_flag_list(flags);
        let team_id = 1;

        let DependencyGraphResult {
            graph: global_graph,
            flags_with_missing_deps,
            ..
        } = build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(&global_graph, &[], &flags_with_missing_deps);

        assert!(result.is_some());
        let FilteredGraphResult { graph, .. } = result.unwrap();
        assert_eq!(graph.node_count(), 0);
        assert_eq!(graph.edge_count(), 0);
        // Verify the actual flag content
        let nodes = graph.get_all_nodes();
        assert_eq!(nodes.len(), 0);
    }

    #[test]
    fn test_filter_graph_by_keys_single_flag_no_dependencies() {
        // Create a simple graph with no dependencies
        let flag1 = create_test_flag_with_dependencies(1, "flag1", HashSet::new());
        let flag2 = create_test_flag_with_dependencies(2, "flag2", HashSet::new());
        let flag3 = create_test_flag_with_dependencies(3, "flag3", HashSet::new());

        let flags = vec![flag1, flag2, flag3];
        let feature_flags = make_flag_list(flags);
        let team_id = 1;

        let DependencyGraphResult {
            graph: global_graph,
            flags_with_missing_deps,
            ..
        } = build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(
            &global_graph,
            &["flag1".to_string()],
            &flags_with_missing_deps,
        );

        assert!(result.is_some());
        let FilteredGraphResult { graph, .. } = result.unwrap();
        assert_eq!(graph.node_count(), 1);
        assert_eq!(graph.edge_count(), 0);
        assert!(graph.contains_node(1));

        // Verify the actual flag content
        let nodes = graph.get_all_nodes();
        assert_eq!(nodes.len(), 1);
        assert_eq!(nodes[0].id, 1);
        assert_eq!(nodes[0].key, "flag1");
    }

    #[test]
    fn test_filter_graph_by_keys_single_flag_with_dependencies() {
        // Create a simple dependency: flag1 -> flag2
        let flag1 = create_test_flag_with_dependencies(1, "flag1", HashSet::from([2]));
        let flag2 = create_test_flag_with_dependencies(2, "flag2", HashSet::new());
        let flag3 = create_test_flag_with_dependencies(3, "flag3", HashSet::new());

        let flags = vec![flag1, flag2, flag3];
        let feature_flags = make_flag_list(flags);
        let team_id = 1;

        let DependencyGraphResult {
            graph: global_graph,
            flags_with_missing_deps,
            ..
        } = build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(
            &global_graph,
            &["flag1".to_string()],
            &flags_with_missing_deps,
        );

        assert!(result.is_some());
        let FilteredGraphResult { graph, .. } = result.unwrap();
        assert_eq!(graph.node_count(), 2);
        assert_eq!(graph.edge_count(), 1);
        assert!(graph.contains_node(1));
        assert!(graph.contains_node(2));

        // Verify the actual flag content
        let nodes = graph.get_all_nodes();
        assert_eq!(nodes.len(), 2);
        let flag_ids: Vec<i32> = nodes.iter().map(|f| f.id).collect();
        let flag_keys: Vec<&str> = nodes.iter().map(|f| f.key.as_str()).collect();
        assert!(flag_ids.contains(&1));
        assert!(flag_ids.contains(&2));
        assert!(flag_keys.contains(&"flag1"));
        assert!(flag_keys.contains(&"flag2"));
    }

    #[test]
    fn test_filter_graph_by_keys_multiple_flags_with_shared_dependencies() {
        // Create dependencies: flag1 -> flag3, flag2 -> flag3
        let flag1 = create_test_flag_with_dependencies(1, "flag1", HashSet::from([3]));
        let flag2 = create_test_flag_with_dependencies(2, "flag2", HashSet::from([3]));
        let flag3 = create_test_flag_with_dependencies(3, "flag3", HashSet::new());
        let flag4 = create_test_flag_with_dependencies(4, "flag4", HashSet::new());

        let flags = vec![flag1, flag2, flag3, flag4];
        let feature_flags = make_flag_list(flags);
        let team_id = 1;

        let DependencyGraphResult {
            graph: global_graph,
            flags_with_missing_deps,
            ..
        } = crate::utils::graph_utils::build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(
            &global_graph,
            &["flag1".to_string(), "flag2".to_string()],
            &flags_with_missing_deps,
        );

        assert!(result.is_some());
        let FilteredGraphResult { graph, .. } = result.unwrap();
        assert_eq!(graph.node_count(), 3);
        assert_eq!(graph.edge_count(), 2);
        assert!(graph.contains_node(1));
        assert!(graph.contains_node(2));
        assert!(graph.contains_node(3));
        assert!(!graph.contains_node(4)); // flag4 should not be included
                                          // Verify the actual flag content
        let nodes = graph.get_all_nodes();
        let flag_ids: std::collections::HashSet<i32> = nodes.iter().map(|f| f.id).collect();
        let flag_keys: std::collections::HashSet<&str> =
            nodes.iter().map(|f| f.key.as_str()).collect();
        assert_eq!(flag_ids, [1, 2, 3].iter().cloned().collect());
        assert_eq!(
            flag_keys,
            ["flag1", "flag2", "flag3"].iter().cloned().collect()
        );
    }

    #[test]
    fn test_filter_graph_by_keys_missing_flag_key() {
        // Create a simple graph
        let flag1 = create_test_flag_with_dependencies(1, "flag1", HashSet::new());
        let flag2 = create_test_flag_with_dependencies(2, "flag2", HashSet::new());

        let flags = vec![flag1, flag2];
        let feature_flags = make_flag_list(flags);
        let team_id = 1;

        let DependencyGraphResult {
            graph: global_graph,
            flags_with_missing_deps,
            ..
        } = crate::utils::graph_utils::build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(
            &global_graph,
            &["nonexistent_flag".to_string()],
            &flags_with_missing_deps,
        );

        assert!(result.is_some());
        let FilteredGraphResult { graph, .. } = result.unwrap();
        assert_eq!(graph.node_count(), 0);
        assert_eq!(graph.edge_count(), 0);
        // Verify the actual flag content
        let nodes = graph.get_all_nodes();
        assert_eq!(nodes.len(), 0);
    }

    #[test]
    fn test_filter_graph_by_keys_mixed_existing_and_missing_keys() {
        // Create a simple graph
        let flag1 = create_test_flag_with_dependencies(1, "flag1", HashSet::new());
        let flag2 = create_test_flag_with_dependencies(2, "flag2", HashSet::new());

        let flags = vec![flag1, flag2];
        let feature_flags = make_flag_list(flags);
        let team_id = 1;

        let DependencyGraphResult {
            graph: global_graph,
            flags_with_missing_deps,
            ..
        } = crate::utils::graph_utils::build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(
            &global_graph,
            &["flag1".to_string(), "nonexistent_flag".to_string()],
            &flags_with_missing_deps,
        );

        assert!(result.is_some());
        let FilteredGraphResult { graph, .. } = result.unwrap();
        assert_eq!(graph.node_count(), 1);
        assert_eq!(graph.edge_count(), 0);
        assert!(graph.contains_node(1));

        // Verify the actual flag content
        let nodes = graph.get_all_nodes();
        assert_eq!(nodes.len(), 1);
        assert_eq!(nodes[0].id, 1);
        assert_eq!(nodes[0].key, "flag1");
    }

    #[test]
    fn test_filter_graph_by_keys_complex_dependency_tree() {
        // Create a complex dependency tree:
        // flag1 -> flag2 -> flag4
        // flag1 -> flag3 -> flag4
        // flag5 -> flag6
        let flag1 = create_test_flag_with_dependencies(1, "flag1", HashSet::from([2, 3]));
        let flag2 = create_test_flag_with_dependencies(2, "flag2", HashSet::from([4]));
        let flag3 = create_test_flag_with_dependencies(3, "flag3", HashSet::from([4]));
        let flag4 = create_test_flag_with_dependencies(4, "flag4", HashSet::new());
        let flag5 = create_test_flag_with_dependencies(5, "flag5", HashSet::from([6]));
        let flag6 = create_test_flag_with_dependencies(6, "flag6", HashSet::new());

        let flags = vec![flag1, flag2, flag3, flag4, flag5, flag6];
        let feature_flags = make_flag_list(flags);
        let team_id = 1;

        let DependencyGraphResult {
            graph: global_graph,
            flags_with_missing_deps,
            ..
        } = crate::utils::graph_utils::build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(
            &global_graph,
            &["flag1".to_string()],
            &flags_with_missing_deps,
        );

        assert!(result.is_some());
        let FilteredGraphResult { graph, .. } = result.unwrap();
        assert_eq!(graph.node_count(), 4);
        assert_eq!(graph.edge_count(), 4);
        assert!(graph.contains_node(1));
        assert!(graph.contains_node(2));
        assert!(graph.contains_node(3));
        assert!(graph.contains_node(4));
        assert!(!graph.contains_node(5)); // flag5 should not be included
        assert!(!graph.contains_node(6)); // flag6 should not be included
                                          // Verify the actual flag content
        let nodes = graph.get_all_nodes();
        let flag_ids: std::collections::HashSet<i32> = nodes.iter().map(|f| f.id).collect();
        let flag_keys: std::collections::HashSet<&str> =
            nodes.iter().map(|f| f.key.as_str()).collect();
        assert_eq!(flag_ids, [1, 2, 3, 4].iter().cloned().collect());
        assert_eq!(
            flag_keys,
            ["flag1", "flag2", "flag3", "flag4"]
                .iter()
                .cloned()
                .collect()
        );
    }

    #[test]
    fn test_filter_graph_by_keys_multiple_disconnected_subgraphs() {
        // Create two disconnected subgraphs:
        // flag1 -> flag2
        // flag3 -> flag4
        let flag1 = create_test_flag_with_dependencies(1, "flag1", HashSet::from([2]));
        let flag2 = create_test_flag_with_dependencies(2, "flag2", HashSet::new());
        let flag3 = create_test_flag_with_dependencies(3, "flag3", HashSet::from([4]));
        let flag4 = create_test_flag_with_dependencies(4, "flag4", HashSet::new());

        let flags = vec![flag1, flag2, flag3, flag4];
        let feature_flags = make_flag_list(flags);
        let team_id = 1;

        let DependencyGraphResult {
            graph: global_graph,
            flags_with_missing_deps,
            ..
        } = crate::utils::graph_utils::build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(
            &global_graph,
            &["flag1".to_string(), "flag3".to_string()],
            &flags_with_missing_deps,
        );

        assert!(result.is_some());
        let FilteredGraphResult { graph, .. } = result.unwrap();
        assert_eq!(graph.node_count(), 4);
        assert_eq!(graph.edge_count(), 2);
        assert!(graph.contains_node(1));
        assert!(graph.contains_node(2));
        assert!(graph.contains_node(3));
        assert!(graph.contains_node(4));
        // Verify the actual flag content
        let nodes = graph.get_all_nodes();
        let flag_ids: std::collections::HashSet<i32> = nodes.iter().map(|f| f.id).collect();
        let flag_keys: std::collections::HashSet<&str> =
            nodes.iter().map(|f| f.key.as_str()).collect();
        assert_eq!(flag_ids, [1, 2, 3, 4].iter().cloned().collect());
        assert_eq!(
            flag_keys,
            ["flag1", "flag2", "flag3", "flag4"]
                .iter()
                .cloned()
                .collect()
        );
    }

    #[test]
    fn test_filter_graph_by_keys_preserves_edge_structure() {
        // Create a complex dependency structure to test edge preservation
        // flag1 -> flag2 -> flag3
        // flag1 -> flag3
        let flag1 = create_test_flag_with_dependencies(1, "flag1", HashSet::from([2, 3]));
        let flag2 = create_test_flag_with_dependencies(2, "flag2", HashSet::from([3]));
        let flag3 = create_test_flag_with_dependencies(3, "flag3", HashSet::new());

        let flags = vec![flag1, flag2, flag3];
        let feature_flags = make_flag_list(flags);
        let team_id = 1;

        let DependencyGraphResult {
            graph: global_graph,
            flags_with_missing_deps,
            ..
        } = crate::utils::graph_utils::build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(
            &global_graph,
            &["flag1".to_string()],
            &flags_with_missing_deps,
        );

        assert!(result.is_some());
        let FilteredGraphResult { graph, .. } = result.unwrap();
        assert_eq!(graph.node_count(), 3);
        assert_eq!(graph.edge_count(), 3);
        // Verify the actual flag content
        let nodes = graph.get_all_nodes();
        let flag_ids: std::collections::HashSet<i32> = nodes.iter().map(|f| f.id).collect();
        let flag_keys: std::collections::HashSet<&str> =
            nodes.iter().map(|f| f.key.as_str()).collect();
        assert_eq!(flag_ids, [1, 2, 3].iter().cloned().collect());
        assert_eq!(
            flag_keys,
            ["flag1", "flag2", "flag3"].iter().cloned().collect()
        );
        // Verify the edge structure is preserved
        let evaluation_stages = graph.evaluation_stages().unwrap();
        assert_eq!(evaluation_stages.len(), 3);
        assert_eq!(evaluation_stages[0].len(), 1); // flag3 (no dependencies)
        assert_eq!(evaluation_stages[1].len(), 1); // flag2 (depends on flag3)
        assert_eq!(evaluation_stages[2].len(), 1); // flag1 (depends on flag2 and flag3)
    }
}

/// Creates a test flag with the given dependencies, active state, and deleted state.
/// Builds a `FeatureFlagList` with `filtered_out_flag_ids` pre-populated
/// from inactive/deleted flags, matching production behavior.
#[cfg(test)]
fn make_flag_list(
    flags: Vec<crate::flags::flag_models::FeatureFlag>,
) -> crate::flags::flag_models::FeatureFlagList {
    let filtered_out_flag_ids = flags
        .iter()
        .filter(|f| !f.active || f.deleted)
        .map(|f| f.id)
        .collect();
    crate::flags::flag_models::FeatureFlagList {
        flags,
        filtered_out_flag_ids,
    }
}

/// Shared helper for `build_dependency_graph` integration tests.
#[cfg(test)]
fn create_flag_with_deps(
    id: i32,
    key: &str,
    dependencies: std::collections::HashSet<i32>,
    active: bool,
    deleted: bool,
) -> crate::flags::flag_models::FeatureFlag {
    use crate::flags::flag_models::{FlagFilters, FlagPropertyGroup};

    let mut filters = FlagFilters {
        groups: vec![FlagPropertyGroup {
            properties: Some(vec![]),
            rollout_percentage: Some(100.0),
            variant: None,
            ..Default::default()
        }],
        multivariate: None,
        aggregation_group_type_index: None,
        payloads: None,
        super_groups: None,

        holdout: None,
    };

    for dep_id in dependencies {
        filters.groups[0].properties.as_mut().unwrap().push(
            crate::properties::property_models::PropertyFilter {
                key: dep_id.to_string(),
                value: Some(serde_json::json!(true)),
                operator: Some(crate::properties::property_models::OperatorType::Exact),
                prop_type: crate::properties::property_models::PropertyType::Flag,
                group_type_index: None,
                negation: None,
            },
        );
    }

    crate::utils::test_utils::create_test_flag(
        Some(id),
        Some(1),
        None,
        Some(key.to_string()),
        Some(filters),
        Some(deleted),
        Some(active),
        None,
    )
}

#[cfg(test)]
mod inactive_flag_dependency_tests {
    use super::{create_flag_with_deps, make_flag_list};
    use crate::utils::graph_utils::build_dependency_graph;
    use std::collections::HashSet;

    #[test]
    fn test_inactive_flag_with_missing_dependency_produces_no_error() {
        // An inactive flag references a non-existent flag (id=999). Since the
        // inactive flag's dependencies are skipped, no MissingDependency error
        // should be produced.
        let inactive_flag =
            create_flag_with_deps(1, "inactive_flag", HashSet::from([999]), false, false);
        let other_flag = create_flag_with_deps(2, "other_flag", HashSet::new(), true, false);

        let flags = vec![inactive_flag, other_flag];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert!(
            result.errors.is_empty(),
            "Inactive flag's missing dependency should not produce errors, got: {:?}",
            result.errors
        );
        assert!(result.flags_with_missing_deps.is_empty());
    }

    #[test]
    fn test_active_flag_depending_on_inactive_flag_still_works() {
        // Active flag depends on an inactive flag. The inactive flag should
        // still be present in the graph (it's in id_map), so the active flag's
        // dependency is satisfied.
        let active_flag = create_flag_with_deps(1, "active_flag", HashSet::from([2]), true, false);
        let inactive_dep = create_flag_with_deps(2, "inactive_dep", HashSet::new(), false, false);

        let flags = vec![active_flag, inactive_dep];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert!(
            result.errors.is_empty(),
            "Active flag depending on an inactive flag should produce no errors, got: {:?}",
            result.errors
        );
        assert_eq!(result.graph.node_count(), 2);
        assert_eq!(
            result.graph.edge_count(),
            1,
            "Edge from active flag to inactive flag should be preserved"
        );
    }

    #[test]
    fn test_inactive_flag_with_missing_dep_does_not_affect_active_flags() {
        // Mix of active and inactive flags. The inactive flag references a
        // deleted flag (id=999), but this should not propagate missing-dep
        // status to unrelated active flags. The inactive flag is excluded
        // from the graph because it is not an active seed and no active
        // flag depends on it.
        let active_flag = create_flag_with_deps(1, "active_flag", HashSet::new(), true, false);
        let inactive_flag =
            create_flag_with_deps(2, "inactive_flag", HashSet::from([999]), false, false);

        let flags = vec![active_flag, inactive_flag];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert!(result.errors.is_empty());
        assert!(result.flags_with_missing_deps.is_empty());
        assert_eq!(result.graph.node_count(), 1);
    }

    #[test]
    fn test_inactive_flag_with_present_dependency_produces_no_edge() {
        // An inactive flag references a present flag. The inactive flag is
        // excluded from the graph (not an active seed, not depended upon by
        // any active flag), so only the active flag remains.
        let inactive_flag =
            create_flag_with_deps(1, "inactive_flag", HashSet::from([2]), false, false);
        let present_dep = create_flag_with_deps(2, "present_dep", HashSet::new(), true, false);

        let flags = vec![inactive_flag, present_dep];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert!(result.errors.is_empty());
        assert_eq!(result.graph.node_count(), 1);
        assert_eq!(
            result.graph.edge_count(),
            0,
            "Inactive flag should not be in the graph"
        );
    }

    #[test]
    fn test_active_flag_with_missing_dependency_still_produces_error() {
        // Sanity check: an active flag referencing a non-existent flag should
        // still produce a MissingDependency error.
        let active_flag =
            create_flag_with_deps(1, "active_flag", HashSet::from([999]), true, false);

        let flags = vec![active_flag];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert_eq!(result.errors.len(), 1);
        assert!(result.flags_with_missing_deps.contains(&1));
    }
}

#[cfg(test)]
mod seed_set_closure_tests {
    use super::{create_flag_with_deps, make_flag_list};
    use crate::utils::graph_utils::build_dependency_graph;
    use std::collections::HashSet;

    #[test]
    fn test_seed_set_only_includes_active_flags() {
        // 5 flags: 3 active with no deps, 2 inactive with no deps.
        // Only the 3 active flags should appear in the graph.
        let flags = vec![
            create_flag_with_deps(1, "active_1", HashSet::new(), true, false),
            create_flag_with_deps(2, "active_2", HashSet::new(), true, false),
            create_flag_with_deps(3, "active_3", HashSet::new(), true, false),
            create_flag_with_deps(4, "inactive_1", HashSet::new(), false, false),
            create_flag_with_deps(5, "inactive_2", HashSet::new(), false, false),
        ];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert_eq!(result.graph.node_count(), 3);
        assert!(result.graph.contains_node(1));
        assert!(result.graph.contains_node(2));
        assert!(result.graph.contains_node(3));
        assert!(!result.graph.contains_node(4));
        assert!(!result.graph.contains_node(5));
    }

    #[test]
    fn test_seed_set_transitive_closure_includes_only_reachable_deps() {
        // A(active) -> B(active) -> C(active) chain, plus D(active, no deps)
        // and E(inactive, no deps). Graph should have 4 nodes: A, B, C, D.
        let flags = vec![
            create_flag_with_deps(1, "a", HashSet::from([2]), true, false),
            create_flag_with_deps(2, "b", HashSet::from([3]), true, false),
            create_flag_with_deps(3, "c", HashSet::new(), true, false),
            create_flag_with_deps(4, "d", HashSet::new(), true, false),
            create_flag_with_deps(5, "e", HashSet::new(), false, false),
        ];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert_eq!(result.graph.node_count(), 4);
        assert!(result.graph.contains_node(1));
        assert!(result.graph.contains_node(2));
        assert!(result.graph.contains_node(3));
        assert!(result.graph.contains_node(4));
        assert!(!result.graph.contains_node(5));
    }

    #[test]
    fn test_seed_set_diamond_dependency_pattern() {
        // A -> B, A -> C, B -> D, C -> D (diamond). All active.
        // Graph should have 4 nodes and 4 edges.
        let flags = vec![
            create_flag_with_deps(1, "a", HashSet::from([2, 3]), true, false),
            create_flag_with_deps(2, "b", HashSet::from([4]), true, false),
            create_flag_with_deps(3, "c", HashSet::from([4]), true, false),
            create_flag_with_deps(4, "d", HashSet::new(), true, false),
        ];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert!(result.errors.is_empty());
        assert_eq!(result.graph.node_count(), 4);
        assert_eq!(result.graph.edge_count(), 4);
    }

    #[test]
    fn test_seed_set_large_flag_set_reduction() {
        // 100 flags total, but only 5 active flags forming a chain (1->2->3->4->5).
        // The remaining 95 flags are inactive. Graph should have exactly 5 nodes.
        let mut flags = Vec::with_capacity(100);
        for i in 1..=5 {
            let deps = if i < 5 {
                HashSet::from([i + 1])
            } else {
                HashSet::new()
            };
            flags.push(create_flag_with_deps(
                i,
                &format!("active_{i}"),
                deps,
                true,
                false,
            ));
        }
        for i in 6..=100 {
            flags.push(create_flag_with_deps(
                i,
                &format!("inactive_{i}"),
                HashSet::new(),
                false,
                false,
            ));
        }
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert_eq!(result.graph.node_count(), 5);
    }

    #[test]
    fn test_seed_set_includes_inactive_dep_of_active_flag() {
        // Active flag A depends on inactive flag B. B should be pulled into the
        // closure (as a terminal node) so from_nodes can wire the edge.
        let flags = vec![
            create_flag_with_deps(1, "active_a", HashSet::from([2]), true, false),
            create_flag_with_deps(2, "inactive_b", HashSet::new(), false, false),
        ];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert_eq!(result.graph.node_count(), 2);
        assert_eq!(result.graph.edge_count(), 1);
        assert!(result.graph.contains_node(1));
        assert!(result.graph.contains_node(2));
    }

    #[test]
    fn test_seed_set_excludes_deleted_flags() {
        // An active-but-deleted flag should not be in the seed set.
        let flags = vec![
            create_flag_with_deps(1, "alive", HashSet::new(), true, false),
            create_flag_with_deps(2, "deleted_flag", HashSet::new(), true, true),
        ];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert_eq!(result.graph.node_count(), 1);
        assert!(result.graph.contains_node(1));
        assert!(!result.graph.contains_node(2));
    }

    #[test]
    fn test_deleted_flag_pulled_in_as_dependency() {
        // An active, non-deleted flag depends on a deleted flag. The deleted
        // flag should be pulled into the closure via BFS.
        let flags = vec![
            create_flag_with_deps(1, "active", HashSet::from([2]), true, false),
            create_flag_with_deps(2, "deleted_dep", HashSet::new(), true, true),
        ];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert_eq!(result.graph.node_count(), 2);
        assert!(result.graph.contains_node(1));
        assert!(result.graph.contains_node(2));
        assert_eq!(result.graph.edge_count(), 1);
    }

    #[test]
    fn test_seed_set_transitive_closure_through_inactive_deps() {
        // Active A -> inactive B -> inactive C. B is pulled into the closure
        // because A depends on it. However, extract_dependencies() returns
        // empty for inactive flags, so B's dependency on C is not followed
        // and C is not included in the graph.
        let flags = vec![
            create_flag_with_deps(1, "active_a", HashSet::from([2]), true, false),
            create_flag_with_deps(2, "inactive_b", HashSet::from([3]), false, false),
            create_flag_with_deps(3, "inactive_c", HashSet::new(), false, false),
        ];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert_eq!(result.graph.node_count(), 2);
        assert_eq!(result.graph.edge_count(), 1);
        assert!(result.graph.contains_node(1));
        assert!(result.graph.contains_node(2));
        assert!(!result.graph.contains_node(3));
    }

    #[test]
    fn test_seed_set_empty_flag_list() {
        let feature_flags = make_flag_list(vec![]);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert_eq!(result.graph.node_count(), 0);
        assert!(result.errors.is_empty());
        assert!(result.flags_with_missing_deps.is_empty());
    }

    #[test]
    fn test_seed_set_all_inactive_produces_empty_graph() {
        let flags = vec![
            create_flag_with_deps(1, "a", HashSet::new(), false, false),
            create_flag_with_deps(2, "b", HashSet::from([1]), false, false),
        ];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert_eq!(result.graph.node_count(), 0);
        assert!(result.errors.is_empty());
    }

    #[test]
    fn test_deleted_flag_deps_not_followed_when_dep_is_also_seed() {
        // Active A -> deleted B (active=true, deleted=true) -> C (active, not deleted).
        // B is filtered out (deleted), so its deps are not followed. C appears
        // in the graph only because it is an active seed, not because of B.
        let flags = vec![
            create_flag_with_deps(1, "active_a", HashSet::from([2]), true, false),
            create_flag_with_deps(2, "deleted_b", HashSet::from([3]), true, true),
            create_flag_with_deps(3, "dep_c", HashSet::new(), true, false),
        ];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert_eq!(result.graph.node_count(), 3);
        assert!(result.graph.contains_node(1));
        assert!(result.graph.contains_node(2));
        assert!(result.graph.contains_node(3));
        // B's dependency on C is NOT wired because B is filtered out.
        // A->B is the only edge; C is disconnected (present as a seed).
        assert_eq!(result.graph.edge_count(), 1);
        assert!(result.errors.is_empty());
    }

    #[test]
    fn test_deleted_flag_deps_not_followed_when_dep_is_not_seed() {
        // Active A -> deleted B -> inactive C. B is filtered out so its deps
        // are not followed. C is also filtered out (inactive) and not
        // reachable from any seed, so it is excluded entirely.
        let flags = vec![
            create_flag_with_deps(1, "active_a", HashSet::from([2]), true, false),
            create_flag_with_deps(2, "deleted_b", HashSet::from([3]), true, true),
            create_flag_with_deps(3, "inactive_c", HashSet::new(), false, false),
        ];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert_eq!(result.graph.node_count(), 2);
        assert!(result.graph.contains_node(1));
        assert!(result.graph.contains_node(2));
        assert!(!result.graph.contains_node(3));
        assert_eq!(result.graph.edge_count(), 1);
        assert!(result.errors.is_empty());
    }

    #[test]
    fn test_runtime_filtered_active_flag_deps_not_followed() {
        // Simulate a flag that is active+non-deleted but filtered at runtime
        // (e.g., tag filter or runtime mismatch). Its dependencies should not
        // be followed even though extract_dependencies() would return them.
        // Flag 3 is inactive so it won't be a seed — it can only enter the
        // graph if flag 2's dependencies are followed.
        let flags = vec![
            create_flag_with_deps(1, "seed_flag", HashSet::from([2]), true, false),
            create_flag_with_deps(2, "runtime_filtered", HashSet::from([3]), true, false),
            create_flag_with_deps(3, "deep_dep", HashSet::new(), false, false),
        ];
        let mut feature_flags = make_flag_list(flags);
        // Manually mark flag 2 as runtime-filtered (on top of make_flag_list's
        // inactive/deleted filtering which already excluded flag 3).
        feature_flags.filtered_out_flag_ids.insert(2);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        // Flag 2 is pulled in as a dependency of flag 1, but flag 3
        // is excluded because flag 2's deps are suppressed.
        assert_eq!(result.graph.node_count(), 2);
        assert!(result.graph.contains_node(1));
        assert!(result.graph.contains_node(2));
        assert!(!result.graph.contains_node(3));
        assert!(result.errors.is_empty());
    }

    #[test]
    fn test_cycle_among_active_flags_produces_error() {
        let flags = vec![
            create_flag_with_deps(1, "a", HashSet::from([2]), true, false),
            create_flag_with_deps(2, "b", HashSet::from([3]), true, false),
            create_flag_with_deps(3, "c", HashSet::from([1]), true, false),
        ];
        let feature_flags = make_flag_list(flags);

        let result = build_dependency_graph(&feature_flags, 1).unwrap();
        assert!(
            result.errors.iter().any(|e| e.is_cycle()),
            "Expected a CycleDetected error, got: {:?}",
            result.errors
        );
    }
}
