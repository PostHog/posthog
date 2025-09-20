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
            assert!(errors.is_empty(), "Expected no errors, found: {errors:?}");
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
            assert!(errors.is_empty(), "Expected no errors, found: {errors:?}");
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

            let (graph, errors) = DependencyGraph::from_nodes(&items).unwrap();
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

            let (graph, errors) = DependencyGraph::from_nodes(&items).unwrap();
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

            let (graph, errors) = DependencyGraph::from_nodes(&items).unwrap();
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

            let (graph, errors) = DependencyGraph::from_nodes(&items).unwrap();
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
}

#[cfg(test)]
mod filter_graph_by_keys_tests {
    use crate::flags::flag_models::{FeatureFlag, FeatureFlagList, FlagFilters, FlagPropertyGroup};
    use crate::utils::graph_utils::{build_dependency_graph, filter_graph_by_keys};
    use crate::utils::test_utils::create_test_flag;
    use std::collections::HashSet;

    // Helper function to create a test flag with dependencies for graph testing
    fn create_test_flag_with_dependencies(
        id: i32,
        key: &str,
        dependencies: HashSet<i32>,
    ) -> FeatureFlag {
        let mut filters = FlagFilters {
            groups: vec![FlagPropertyGroup {
                properties: Some(vec![]),
                rollout_percentage: Some(100.0),
                variant: None,
            }],
            multivariate: None,
            aggregation_group_type_index: None,
            payloads: None,
            super_groups: None,
            holdout_groups: None,
        };

        // Add dependency filters for each dependency
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

        create_test_flag(
            Some(id),
            Some(1), // team_id
            None,    // name
            Some(key.to_string()),
            Some(filters),
            None, // deleted
            None, // active
            None, // ensure_experience_continuity
        )
    }

    #[test]
    fn test_filter_graph_by_keys_no_requested_keys() {
        // Create a simple graph with no dependencies
        let flag1 = create_test_flag_with_dependencies(1, "flag1", HashSet::new());
        let flag2 = create_test_flag_with_dependencies(2, "flag2", HashSet::new());
        let flag3 = create_test_flag_with_dependencies(3, "flag3", HashSet::new());

        let flags = vec![flag1, flag2, flag3];
        let feature_flags = FeatureFlagList { flags };
        let team_id = 1;

        let (global_graph, _) = build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(&global_graph, &[]);

        assert!(result.is_some());
        let filtered_graph = result.unwrap();
        assert_eq!(filtered_graph.node_count(), 0);
        assert_eq!(filtered_graph.edge_count(), 0);
        // Verify the actual flag content
        let nodes = filtered_graph.get_all_nodes();
        assert_eq!(nodes.len(), 0);
    }

    #[test]
    fn test_filter_graph_by_keys_single_flag_no_dependencies() {
        // Create a simple graph with no dependencies
        let flag1 = create_test_flag_with_dependencies(1, "flag1", HashSet::new());
        let flag2 = create_test_flag_with_dependencies(2, "flag2", HashSet::new());
        let flag3 = create_test_flag_with_dependencies(3, "flag3", HashSet::new());

        let flags = vec![flag1, flag2, flag3];
        let feature_flags = FeatureFlagList { flags };
        let team_id = 1;

        let (global_graph, _) = build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(&global_graph, &["flag1".to_string()]);

        assert!(result.is_some());
        let filtered_graph = result.unwrap();
        assert_eq!(filtered_graph.node_count(), 1);
        assert_eq!(filtered_graph.edge_count(), 0);
        assert!(filtered_graph.contains_node(1));

        // Verify the actual flag content
        let nodes = filtered_graph.get_all_nodes();
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
        let feature_flags = FeatureFlagList { flags };
        let team_id = 1;

        let (global_graph, _) = build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(&global_graph, &["flag1".to_string()]);

        assert!(result.is_some());
        let filtered_graph = result.unwrap();
        assert_eq!(filtered_graph.node_count(), 2);
        assert_eq!(filtered_graph.edge_count(), 1);
        assert!(filtered_graph.contains_node(1));
        assert!(filtered_graph.contains_node(2));

        // Verify the actual flag content
        let nodes = filtered_graph.get_all_nodes();
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
        let feature_flags = FeatureFlagList { flags };
        let team_id = 1;

        let (global_graph, _) =
            crate::utils::graph_utils::build_dependency_graph(&feature_flags, team_id).unwrap();
        let result =
            filter_graph_by_keys(&global_graph, &["flag1".to_string(), "flag2".to_string()]);

        assert!(result.is_some());
        let filtered_graph = result.unwrap();
        assert_eq!(filtered_graph.node_count(), 3);
        assert_eq!(filtered_graph.edge_count(), 2);
        assert!(filtered_graph.contains_node(1));
        assert!(filtered_graph.contains_node(2));
        assert!(filtered_graph.contains_node(3));
        assert!(!filtered_graph.contains_node(4)); // flag4 should not be included
                                                   // Verify the actual flag content
        let nodes = filtered_graph.get_all_nodes();
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
        let feature_flags = FeatureFlagList { flags };
        let team_id = 1;

        let (global_graph, _) =
            crate::utils::graph_utils::build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(&global_graph, &["nonexistent_flag".to_string()]);

        assert!(result.is_some());
        let filtered_graph = result.unwrap();
        assert_eq!(filtered_graph.node_count(), 0);
        assert_eq!(filtered_graph.edge_count(), 0);
        // Verify the actual flag content
        let nodes = filtered_graph.get_all_nodes();
        assert_eq!(nodes.len(), 0);
    }

    #[test]
    fn test_filter_graph_by_keys_mixed_existing_and_missing_keys() {
        // Create a simple graph
        let flag1 = create_test_flag_with_dependencies(1, "flag1", HashSet::new());
        let flag2 = create_test_flag_with_dependencies(2, "flag2", HashSet::new());

        let flags = vec![flag1, flag2];
        let feature_flags = FeatureFlagList { flags };
        let team_id = 1;

        let (global_graph, _) =
            crate::utils::graph_utils::build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(
            &global_graph,
            &["flag1".to_string(), "nonexistent_flag".to_string()],
        );

        assert!(result.is_some());
        let filtered_graph = result.unwrap();
        assert_eq!(filtered_graph.node_count(), 1);
        assert_eq!(filtered_graph.edge_count(), 0);
        assert!(filtered_graph.contains_node(1));

        // Verify the actual flag content
        let nodes = filtered_graph.get_all_nodes();
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
        let feature_flags = FeatureFlagList { flags };
        let team_id = 1;

        let (global_graph, _) =
            crate::utils::graph_utils::build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(&global_graph, &["flag1".to_string()]);

        assert!(result.is_some());
        let filtered_graph = result.unwrap();
        assert_eq!(filtered_graph.node_count(), 4);
        assert_eq!(filtered_graph.edge_count(), 4);
        assert!(filtered_graph.contains_node(1));
        assert!(filtered_graph.contains_node(2));
        assert!(filtered_graph.contains_node(3));
        assert!(filtered_graph.contains_node(4));
        assert!(!filtered_graph.contains_node(5)); // flag5 should not be included
        assert!(!filtered_graph.contains_node(6)); // flag6 should not be included
                                                   // Verify the actual flag content
        let nodes = filtered_graph.get_all_nodes();
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
        let feature_flags = FeatureFlagList { flags };
        let team_id = 1;

        let (global_graph, _) =
            crate::utils::graph_utils::build_dependency_graph(&feature_flags, team_id).unwrap();
        let result =
            filter_graph_by_keys(&global_graph, &["flag1".to_string(), "flag3".to_string()]);

        assert!(result.is_some());
        let filtered_graph = result.unwrap();
        assert_eq!(filtered_graph.node_count(), 4);
        assert_eq!(filtered_graph.edge_count(), 2);
        assert!(filtered_graph.contains_node(1));
        assert!(filtered_graph.contains_node(2));
        assert!(filtered_graph.contains_node(3));
        assert!(filtered_graph.contains_node(4));
        // Verify the actual flag content
        let nodes = filtered_graph.get_all_nodes();
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
        let feature_flags = FeatureFlagList { flags };
        let team_id = 1;

        let (global_graph, _) =
            crate::utils::graph_utils::build_dependency_graph(&feature_flags, team_id).unwrap();
        let result = filter_graph_by_keys(&global_graph, &["flag1".to_string()]);

        assert!(result.is_some());
        let filtered_graph = result.unwrap();
        assert_eq!(filtered_graph.node_count(), 3);
        assert_eq!(filtered_graph.edge_count(), 3);
        // Verify the actual flag content
        let nodes = filtered_graph.get_all_nodes();
        let flag_ids: std::collections::HashSet<i32> = nodes.iter().map(|f| f.id).collect();
        let flag_keys: std::collections::HashSet<&str> =
            nodes.iter().map(|f| f.key.as_str()).collect();
        assert_eq!(flag_ids, [1, 2, 3].iter().cloned().collect());
        assert_eq!(
            flag_keys,
            ["flag1", "flag2", "flag3"].iter().cloned().collect()
        );
        // Verify the edge structure is preserved
        let evaluation_stages = filtered_graph.evaluation_stages().unwrap();
        assert_eq!(evaluation_stages.len(), 3);
        assert_eq!(evaluation_stages[0].len(), 1); // flag3 (no dependencies)
        assert_eq!(evaluation_stages[1].len(), 1); // flag2 (depends on flag3)
        assert_eq!(evaluation_stages[2].len(), 1); // flag1 (depends on flag2 and flag3)
    }
}
