#[cfg(test)]
mod tests {
    use crate::api::errors::FlagError;
    use crate::utils::graph_utils::{DependencyGraph, DependencyProvider, DependencyType};
    use std::collections::HashSet;

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
        use crate::utils::graph_utils::GraphError;

        use super::*;

        #[test]
        fn test_build_multiple_independent_nodes() {
            let items = vec![
                TestItem::new(1, HashSet::new()),
                TestItem::new(2, HashSet::new()),
                TestItem::new(3, HashSet::new()),
            ];

            let (graph, errors) = DependencyGraph::from_nodes(&items).unwrap();
            assert!(errors.is_empty(), "Expected no errors, found: {:?}", errors);
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

            let (graph, errors) = DependencyGraph::from_nodes(&items).unwrap();
            assert!(errors.is_empty(), "Expected no errors, found: {:?}", errors);
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

            let (graph, errors) = DependencyGraph::from_nodes(&items).unwrap();
            assert_eq!(
                errors.len(),
                2,
                "Expected two cycle errors, found: {:?}",
                errors
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
            // 4 -> 3 -> 1 -> (999: missing)
            // 2 -> 1 -> (999: missing)
            // 6 -> (1000: missing)
            let items = vec![
                TestItem::new(1, HashSet::from([999])),  // Missing dependency.
                TestItem::new(2, HashSet::from([1])), // Depends on node that depends on a missing dependency.
                TestItem::new(3, HashSet::from([1])), // Depends on node that depends on a missing dependency.
                TestItem::new(4, HashSet::from([2])), // Depends on node that depends on a node that depends on a missing dependency.
                TestItem::new(5, HashSet::new()),     // Should remain.
                TestItem::new(6, HashSet::from([1000])), // Missing dependency.
            ];

            let (graph, errors) = DependencyGraph::from_nodes(&items).unwrap();
            assert_eq!(
                graph.node_count(),
                1,
                "Expected only the valid subgraph (5)"
            );
            assert_eq!(
                errors.len(),
                2,
                "Expected two errors due to missing dependencies"
            );
            // Check that both missing dependencies are reported (order may vary)
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
            assert!(graph.contains_node(5));
            assert!(!graph.contains_node(1));
            assert!(!graph.contains_node(2));
            assert!(!graph.contains_node(3));
            assert!(!graph.contains_node(4));
            assert!(!graph.contains_node(6));
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

            let (graph, errors) = DependencyGraph::from_nodes(&items).unwrap();
            assert!(errors.is_empty(), "Expected no errors, found: {:?}", errors);
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

            let (graph, errors) = DependencyGraph::from_nodes(&items).unwrap();
            assert!(errors.is_empty(), "Expected no errors, found: {:?}", errors);
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

            let (graph, errors) = DependencyGraph::from_nodes(&items).unwrap();
            assert!(errors.is_empty(), "Expected no errors, found: {:?}", errors);
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

            let (graph, errors) = DependencyGraph::from_nodes(&items).unwrap();
            assert!(errors.is_empty(), "Expected no errors, found: {:?}", errors);
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

            let (graph, errors) = DependencyGraph::from_nodes(&items).unwrap();
            assert!(errors.is_empty(), "Expected no errors, found: {:?}", errors);
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
}
