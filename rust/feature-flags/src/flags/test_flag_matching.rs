#[cfg(test)]
mod tests {
    use common_types::TeamId;
    use serde_json::json;
    use std::collections::{HashMap, HashSet};
    use std::sync::Arc;
    use uuid::Uuid;

    use crate::{
        api::types::{FlagValue, LegacyFlagsResponse},
        cohorts::cohort_cache_manager::CohortCacheManager,
        flags::{
            flag_group_type_mapping::GroupTypeMappingCache,
            flag_match_reason::FeatureFlagMatchReason,
            flag_matching::{FeatureFlagMatch, FeatureFlagMatcher},
            flag_matching_utils::{
                get_fetch_calls_count, get_hash_key_override_lookup_count, reset_fetch_calls_count,
                reset_hash_key_override_lookup_count, set_feature_flag_hash_key_overrides,
            },
            flag_models::{
                EvaluationMetadata, FeatureFlag, FeatureFlagList, FlagFilters, FlagPropertyGroup,
                Holdout, MultivariateFlagOptions, MultivariateFlagVariant,
            },
        },
        properties::property_models::{OperatorType, PropertyFilter, PropertyType},
        utils::{
            graph_utils::PrecomputedDependencyGraph,
            test_utils::{create_test_flag, create_test_flag_that_depends_on_flag, TestContext},
        },
    };

    #[tokio::test]
    async fn test_fetch_properties_from_pg_to_match() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));

        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let distinct_id = "user_distinct_id".to_string();
        context
            .insert_person(team.id, distinct_id.clone(), None)
            .await
            .expect("Failed to insert person");

        let not_matching_distinct_id = "not_matching_distinct_id".to_string();
        context
            .insert_person(
                team.id,
                not_matching_distinct_id.clone(),
                Some(json!({ "email": "a@x.com"})),
            )
            .await
            .expect("Failed to insert person");

        let flag: FeatureFlag = serde_json::from_value(json!(
            {
                "id": 1,
                "team_id": team.id,
                "name": "flag1",
                "key": "flag1",
                "active": true,
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "a@b.com",
                                    "type": "person"
                                }
                            ],
                            "rollout_percentage": 100
                        }
                    ]
                }
            }
        ))
        .unwrap();

        // Matcher for a matching distinct_id
        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let match_result = matcher.get_match(&flag, None, None, &None).unwrap();
        assert!(match_result.matches);
        assert_eq!(match_result.variant, None);

        // Matcher for a non-matching distinct_id
        let router2 = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            not_matching_distinct_id.clone(),
            None, // device_id
            team.id,
            router2,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let match_result = matcher.get_match(&flag, None, None, &None).unwrap();
        assert!(!match_result.matches);
        assert_eq!(match_result.variant, None);

        // Matcher for a distinct_id that does not exist
        let router3 = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "other_distinct_id".to_string(),
            None, // device_id
            team.id,
            router3,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let match_result = matcher.get_match(&flag, None, None, &None).unwrap();

        // Expecting false for non-existent distinct_id
        assert!(!match_result.matches);
    }

    #[tokio::test]
    async fn test_person_property_overrides() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("override@example.com")),
                        operator: None,
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let overrides = HashMap::from([("email".to_string(), json!("override@example.com"))]);

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
            ..Default::default()
        };
        let result = matcher
            .evaluate_all_feature_flags(
                flags,
                Some(overrides),
                None,
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();
        assert!(!result.errors_while_computing_flags);
        assert_eq!(
            result.flags.get("test_flag").unwrap().to_value(),
            FlagValue::Boolean(true)
        );
    }

    #[tokio::test]
    async fn test_person_only_flags_succeed_without_group_type_mappings() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("test@example.com")),
                        operator: None,
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        // No group type mappings initialized — this should not cause an error
        // for person-only flags
        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None,
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
            ..Default::default()
        };
        let result = matcher
            .evaluate_all_feature_flags(
                flags,
                Some(HashMap::from([(
                    "email".to_string(),
                    json!("test@example.com"),
                )])),
                None,
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();
        assert!(
            !result.errors_while_computing_flags,
            "Person-only flag evaluation should not error when group type mappings are uninitialized"
        );
        assert_eq!(
            result.flags.get("test_flag").unwrap().to_value(),
            FlagValue::Boolean(true)
        );
    }

    #[tokio::test]
    async fn test_mixed_person_and_group_flags_succeed_without_group_type_mappings() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let person_flag = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("person_flag".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("test@example.com")),
                        operator: None,
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let group_flag = create_test_flag(
            Some(2),
            Some(team.id),
            None,
            Some("group_flag".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "name".to_string(),
                        value: Some(json!("Acme")),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Group,
                        group_type_index: Some(0),
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: Some(0),
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        // No group type mappings initialized — person flags in a mixed batch
        // should still evaluate successfully
        let groups = HashMap::from([("project".to_string(), json!("proj-1"))]);

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None,
            team.id,
            router,
            cohort_cache,
            None,
            Some(groups),
        );

        let flags = FeatureFlagList {
            flags: vec![person_flag.clone(), group_flag.clone()],
            ..Default::default()
        };
        let result = matcher
            .evaluate_all_feature_flags(
                flags,
                Some(HashMap::from([(
                    "email".to_string(),
                    json!("test@example.com"),
                )])),
                None,
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();

        assert!(
            !result.errors_while_computing_flags,
            "Missing group type mappings should not cause errors for person flags in a mixed batch"
        );
        assert_eq!(
            result.flags.get("person_flag").unwrap().to_value(),
            FlagValue::Boolean(true),
        );
        // Group flag evaluates with empty group properties, so it won't match
        assert_eq!(
            result.flags.get("group_flag").unwrap().to_value(),
            FlagValue::Boolean(false),
        );
    }

    #[tokio::test]
    async fn test_group_property_overrides() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "industry".to_string(),
                        value: Some(json!("tech")),
                        operator: None,
                        prop_type: PropertyType::Group,
                        group_type_index: Some(1),
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: Some(1),
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.id);
        group_type_mapping_cache
            .init(context.persons_reader.clone())
            .await
            .unwrap();

        let group_types_to_indexes = [("organization".to_string(), 1)].into_iter().collect();
        let indexes_to_types = [(1, "organization".to_string())].into_iter().collect();
        group_type_mapping_cache.set_test_mappings(group_types_to_indexes, indexes_to_types);

        let groups = HashMap::from([("organization".to_string(), json!("org_123"))]);

        let group_overrides = HashMap::from([(
            "organization".to_string(),
            HashMap::from([
                ("industry".to_string(), json!("tech")),
                ("$group_key".to_string(), json!("org_123")),
            ]),
        )]);

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            context.create_postgres_router(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            Some(groups),
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
            ..Default::default()
        };
        let result = matcher
            .evaluate_all_feature_flags(
                flags,
                None,
                Some(group_overrides),
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();

        let legacy_response = LegacyFlagsResponse::from_response(result);
        assert!(!legacy_response.errors_while_computing_flags);
        assert_eq!(
            legacy_response.feature_flags.get("test_flag"),
            Some(&FlagValue::Boolean(true))
        );
    }

    // Use the shared test utility functions from test_utils.rs
    use crate::utils::test_utils::{
        create_test_flag_with_properties, create_test_flag_with_property,
    };

    #[tokio::test]
    async fn test_flags_that_depends_on_other_boolean_flag() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let leaf_flag = create_test_flag_with_property(
            23,
            team.id,
            "leaf_flag",
            PropertyFilter {
                key: "email".to_string(),
                value: Some(json!("override@example.com")),
                operator: Some(OperatorType::Exact),
                prop_type: PropertyType::Person,
                group_type_index: None,
                negation: None,
            },
        );
        let independent_flag = create_test_flag_with_property(
            99,
            team.id,
            "independent_flag",
            PropertyFilter {
                key: "email".to_string(),
                value: Some(json!("override@example.com")),
                operator: Some(OperatorType::Exact),
                prop_type: PropertyType::Person,
                group_type_index: None,
                negation: None,
            },
        );
        let parent_flag = create_test_flag_that_depends_on_flag(
            42,
            team.id,
            "parent_flag",
            leaf_flag.id,
            FlagValue::Boolean(true),
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );

        let flags = FeatureFlagList {
            flags: vec![
                independent_flag.clone(),
                leaf_flag.clone(),
                parent_flag.clone(),
            ],
            ..Default::default()
        };

        {
            let overrides = HashMap::from([("email".to_string(), json!("override@example.com"))]);
            let result = matcher
                .evaluate_all_feature_flags(
                    flags.clone(),
                    Some(overrides),
                    None,
                    None,
                    Uuid::new_v4(),
                    None,
                    false,
                )
                .await
                .unwrap();
            assert!(!result.errors_while_computing_flags);
            assert_eq!(
                result.flags.get("independent_flag").unwrap().to_value(),
                FlagValue::Boolean(true)
            );
            assert_eq!(
                result.flags.get("leaf_flag").unwrap().to_value(),
                FlagValue::Boolean(true)
            );
            assert_eq!(
                result.flags.get("parent_flag").unwrap().to_value(),
                FlagValue::Boolean(true)
            );
            assert!(!result.flags.contains_key("cycle_start_flag"));
            assert!(!result.flags.contains_key("cycle_middle_flag"));
            assert!(!result.flags.contains_key("cycle_node"));
            assert!(!result.flags.contains_key("missing_dependency_flag"));
        }
        {
            // Leaf flag evaluates to false
            let result = matcher
                .evaluate_all_feature_flags(
                    flags.clone(),
                    None,
                    None,
                    None,
                    Uuid::new_v4(),
                    None,
                    false,
                )
                .await
                .unwrap();
            assert!(!result.errors_while_computing_flags);
            assert_eq!(
                result.flags.get("independent_flag").unwrap().to_value(),
                FlagValue::Boolean(false)
            );
            assert_eq!(
                result.flags.get("leaf_flag").unwrap().to_value(),
                FlagValue::Boolean(false)
            );
            assert_eq!(
                result.flags.get("parent_flag").unwrap().to_value(),
                FlagValue::Boolean(false)
            );
            assert!(!result.flags.contains_key("cycle_start_flag"));
            assert!(!result.flags.contains_key("cycle_middle_flag"));
            assert!(!result.flags.contains_key("cycle_node"));
            assert!(!result.flags.contains_key("missing_dependency_flag"));
        }
    }

    #[tokio::test]
    async fn test_flags_that_depends_on_other_multivariate_flag_variant_match() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let leaf_flag = create_test_flag(
            Some(2),
            Some(team.id),
            None,
            Some("leaf_flag".to_string()),
            Some(FlagFilters {
                groups: vec![
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("control@example.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: Some("control".to_string()),
                        ..Default::default()
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("test@example.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: Some("test".to_string()),
                        ..Default::default()
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![]),
                        rollout_percentage: Some(100.0),
                        variant: Some("other".to_string()),
                        ..Default::default()
                    },
                ],
                multivariate: Some(MultivariateFlagOptions {
                    variants: vec![
                        MultivariateFlagVariant {
                            name: None,
                            key: "control".to_string(),
                            rollout_percentage: 50.0,
                        },
                        MultivariateFlagVariant {
                            name: None,
                            key: "test".to_string(),
                            rollout_percentage: 50.0,
                        },
                        MultivariateFlagVariant {
                            name: None,
                            key: "other".to_string(),
                            rollout_percentage: 50.0,
                        },
                    ],
                }),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let parent_flag = create_test_flag_that_depends_on_flag(
            1,
            team.id,
            "parent_flag",
            leaf_flag.id,
            FlagValue::String("control".to_string()),
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );
        let flags = FeatureFlagList {
            flags: vec![leaf_flag.clone(), parent_flag.clone()],
            ..Default::default()
        };

        {
            let overrides = HashMap::from([("email".to_string(), json!("control@example.com"))]);
            let result = matcher
                .evaluate_all_feature_flags(
                    flags.clone(),
                    Some(overrides),
                    None,
                    None,
                    Uuid::new_v4(),
                    None,
                    false,
                )
                .await
                .unwrap();
            assert!(!result.errors_while_computing_flags);
            assert_eq!(
                result.flags.get("leaf_flag").unwrap().to_value(),
                FlagValue::String("control".to_string())
            );
            assert_eq!(
                result.flags.get("parent_flag").unwrap().to_value(),
                FlagValue::Boolean(true)
            );
        }
        {
            let overrides = HashMap::from([("email".to_string(), json!("test@example.com"))]);
            let result = matcher
                .evaluate_all_feature_flags(
                    flags.clone(),
                    Some(overrides),
                    None,
                    None,
                    Uuid::new_v4(),
                    None,
                    false,
                )
                .await
                .unwrap();
            assert!(!result.errors_while_computing_flags);
            assert_eq!(
                result.flags.get("leaf_flag").unwrap().to_value(),
                FlagValue::String("test".to_string())
            );
            assert_eq!(
                result.flags.get("parent_flag").unwrap().to_value(),
                FlagValue::Boolean(false)
            );
        }
        {
            let overrides = HashMap::from([("email".to_string(), json!("random@example.com"))]);
            let result = matcher
                .evaluate_all_feature_flags(
                    flags.clone(),
                    Some(overrides),
                    None,
                    None,
                    Uuid::new_v4(),
                    None,
                    false,
                )
                .await
                .unwrap();
            assert!(!result.errors_while_computing_flags);
            assert_eq!(
                result.flags.get("leaf_flag").unwrap().to_value(),
                FlagValue::String("other".to_string())
            );
            assert_eq!(
                result.flags.get("parent_flag").unwrap().to_value(),
                FlagValue::Boolean(false)
            );
        }
    }

    #[tokio::test]
    async fn test_flags_with_deep_dependency_tree_only_calls_db_once_total() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let _person_id = context
            .insert_person(
                team.id,
                "test_user_distinct_id".to_string(),
                Some(json!({ "email": "email-in-db@example.com", "is-cool": true })),
            )
            .await
            .unwrap();

        let leaf_flag = create_test_flag_with_property(
            23,
            team.id,
            "leaf_flag",
            PropertyFilter {
                key: "is-cool".to_string(),
                value: Some(json!(true)),
                operator: Some(OperatorType::Exact),
                prop_type: PropertyType::Person,
                group_type_index: None,
                negation: None,
            },
        );
        let independent_flag = create_test_flag_with_property(
            99,
            team.id,
            "independent_flag",
            PropertyFilter {
                key: "email".to_string(),
                value: Some(json!("email-not-in-db@example.com")),
                operator: Some(OperatorType::Exact),
                prop_type: PropertyType::Person,
                group_type_index: None,
                negation: None,
            },
        );
        let intermediate_flag = create_test_flag_with_properties(
            43,
            team.id,
            "intermediate_flag",
            vec![
                PropertyFilter {
                    key: "email".to_string(),
                    value: Some(json!("email-in-db@example.com")),
                    operator: Some(OperatorType::Exact),
                    prop_type: PropertyType::Person,
                    group_type_index: None,
                    negation: None,
                },
                PropertyFilter {
                    key: leaf_flag.id.to_string(),
                    value: Some(json!(true)),
                    operator: Some(OperatorType::FlagEvaluatesTo),
                    prop_type: PropertyType::Flag,
                    group_type_index: None,
                    negation: None,
                },
            ],
        );
        let parent_flag = create_test_flag_that_depends_on_flag(
            42,
            team.id,
            "parent_flag",
            intermediate_flag.id,
            FlagValue::Boolean(true),
        );

        let mut matcher = FeatureFlagMatcher::new(
            "test_user_distinct_id".to_string(),
            None, // device_id
            team.id,
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );

        let flags = FeatureFlagList {
            flags: vec![
                independent_flag.clone(),
                leaf_flag.clone(),
                intermediate_flag.clone(),
                parent_flag.clone(),
            ],
            ..Default::default()
        };

        reset_fetch_calls_count();

        let result = matcher
            .evaluate_all_feature_flags(
                flags.clone(),
                None,
                None,
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();
        // Add this assertion to check the call count
        let fetch_calls = get_fetch_calls_count();
        assert_eq!(fetch_calls, 1, "Expected fetch_and_locally_cache_all_relevant_properties to be called exactly 1 time, but it was called {fetch_calls} times");
        assert_eq!(
            result.flags.get("leaf_flag").unwrap().to_value(),
            FlagValue::Boolean(true)
        );
        assert_eq!(
            result.flags.get("independent_flag").unwrap().to_value(),
            FlagValue::Boolean(false)
        );
        assert_eq!(
            result.flags.get("intermediate_flag").unwrap().to_value(),
            FlagValue::Boolean(true)
        );
        assert_eq!(
            result.flags.get("parent_flag").unwrap().to_value(),
            FlagValue::Boolean(true)
        );
        assert!(!result.errors_while_computing_flags);
    }

    #[tokio::test]
    async fn test_flags_with_dependency_cycle_and_missing_dependency_still_evaluates_independent_flags(
    ) {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let leaf_flag = create_test_flag_with_property(
            23,
            team.id,
            "leaf_flag",
            PropertyFilter {
                key: "email".to_string(),
                value: Some(json!("override@example.com")),
                operator: Some(OperatorType::Exact),
                prop_type: PropertyType::Person,
                group_type_index: None,
                negation: None,
            },
        );
        let independent_flag = create_test_flag_with_property(
            99,
            team.id,
            "independent_flag",
            PropertyFilter {
                key: "email".to_string(),
                value: Some(json!("override@example.com")),
                operator: Some(OperatorType::Exact),
                prop_type: PropertyType::Person,
                group_type_index: None,
                negation: None,
            },
        );
        let parent_flag = create_test_flag_that_depends_on_flag(
            42,
            team.id,
            "parent_flag",
            leaf_flag.id,
            FlagValue::Boolean(true),
        );

        let cycle_node = create_test_flag_that_depends_on_flag(
            43,
            team.id,
            "self_referencing_flag",
            44,
            FlagValue::Boolean(true),
        );

        let cycle_middle_flag = create_test_flag_that_depends_on_flag(
            44,
            team.id,
            "cycle_middle_flag",
            45,
            FlagValue::Boolean(true),
        );

        let cycle_start_flag = create_test_flag_that_depends_on_flag(
            45,
            team.id,
            "cycle_start_flag",
            43,
            FlagValue::Boolean(true),
        );

        let missing_dependency_flag = create_test_flag_that_depends_on_flag(
            46,
            team.id,
            "missing_dependency_flag",
            999,
            FlagValue::Boolean(true),
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );

        let flags = FeatureFlagList {
            flags: vec![
                independent_flag.clone(),
                leaf_flag.clone(),
                cycle_node.clone(),
                cycle_middle_flag.clone(),
                cycle_start_flag.clone(),
                parent_flag.clone(),
                missing_dependency_flag.clone(),
            ],
            ..Default::default()
        };

        {
            // Leaf flag evaluates to true
            let overrides = HashMap::from([("email".to_string(), json!("override@example.com"))]);
            let result = matcher
                .evaluate_all_feature_flags(
                    flags.clone(),
                    Some(overrides),
                    None,
                    None,
                    Uuid::new_v4(),
                    None,
                    false,
                )
                .await
                .unwrap();
            // Cycle errors still cause errors_while_computing_flags to be true
            assert!(result.errors_while_computing_flags);
            assert_eq!(
                result.flags.get("independent_flag").unwrap().to_value(),
                FlagValue::Boolean(true)
            );
            assert_eq!(
                result.flags.get("leaf_flag").unwrap().to_value(),
                FlagValue::Boolean(true)
            );
            assert_eq!(
                result.flags.get("parent_flag").unwrap().to_value(),
                FlagValue::Boolean(true)
            );
            // Cycle nodes are removed from the graph
            assert!(!result.flags.contains_key("cycle_start_flag"));
            assert!(!result.flags.contains_key("cycle_middle_flag"));
            assert!(!result.flags.contains_key("cycle_node"));
            // Missing dependency flag is included with enabled=false (fail closed)
            let missing_dep_flag = result.flags.get("missing_dependency_flag").unwrap();
            assert!(!missing_dep_flag.enabled);
            assert_eq!(missing_dep_flag.reason.code, "missing_dependency");
        }
        {
            // Leaf flag evaluates to false
            let result = matcher
                .evaluate_all_feature_flags(
                    flags.clone(),
                    None,
                    None,
                    None,
                    Uuid::new_v4(),
                    None,
                    false,
                )
                .await
                .unwrap();
            // Cycle errors still cause errors_while_computing_flags to be true
            assert!(result.errors_while_computing_flags);
            assert_eq!(
                result.flags.get("independent_flag").unwrap().to_value(),
                FlagValue::Boolean(false)
            );
            assert_eq!(
                result.flags.get("leaf_flag").unwrap().to_value(),
                FlagValue::Boolean(false)
            );
            assert_eq!(
                result.flags.get("parent_flag").unwrap().to_value(),
                FlagValue::Boolean(false)
            );
            // Cycle nodes are removed from the graph
            assert!(!result.flags.contains_key("cycle_start_flag"));
            assert!(!result.flags.contains_key("cycle_middle_flag"));
            assert!(!result.flags.contains_key("cycle_node"));
            // Missing dependency flag is included with enabled=false (fail closed)
            let missing_dep_flag = result.flags.get("missing_dependency_flag").unwrap();
            assert!(!missing_dep_flag.enabled);
            assert_eq!(missing_dep_flag.reason.code, "missing_dependency");
        }
    }

    #[tokio::test]
    async fn test_flags_that_depends_on_other_multivariate_flag_boolean_match() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let leaf_flag = create_test_flag(
            Some(3),
            Some(team.id),
            None,
            Some("leaf_flag".to_string()),
            Some(FlagFilters {
                groups: vec![
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("control@example.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: Some("control".to_string()),
                        ..Default::default()
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("test@example.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: Some("test".to_string()),
                        ..Default::default()
                    },
                ],
                multivariate: Some(MultivariateFlagOptions {
                    variants: vec![
                        MultivariateFlagVariant {
                            name: None,
                            key: "control".to_string(),
                            rollout_percentage: 50.0,
                        },
                        MultivariateFlagVariant {
                            name: None,
                            key: "test".to_string(),
                            rollout_percentage: 50.0,
                        },
                    ],
                }),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let parent_flag = create_test_flag_that_depends_on_flag(
            2,
            team.id,
            "parent_flag",
            leaf_flag.id,
            FlagValue::Boolean(true), // KEY DIFFERENCE FROM PREVIOUS TEST
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );
        let flags = FeatureFlagList {
            flags: vec![leaf_flag.clone(), parent_flag.clone()],
            ..Default::default()
        };

        {
            // Leaf flag evaluates to "control"
            let overrides = HashMap::from([("email".to_string(), json!("control@example.com"))]);
            let result = matcher
                .evaluate_all_feature_flags(
                    flags.clone(),
                    Some(overrides),
                    None,
                    None,
                    Uuid::new_v4(),
                    None,
                    false,
                )
                .await
                .unwrap();
            assert!(!result.errors_while_computing_flags);
            assert_eq!(
                result.flags.get("leaf_flag").unwrap().to_value(),
                FlagValue::String("control".to_string())
            );
            assert_eq!(
                result.flags.get("parent_flag").unwrap().to_value(),
                FlagValue::Boolean(true)
            );
        }
        {
            // Leaf flag evaluates to "test"
            let overrides = HashMap::from([("email".to_string(), json!("test@example.com"))]);
            let result = matcher
                .evaluate_all_feature_flags(
                    flags.clone(),
                    Some(overrides),
                    None,
                    None,
                    Uuid::new_v4(),
                    None,
                    false,
                )
                .await
                .unwrap();
            assert!(!result.errors_while_computing_flags);
            assert_eq!(
                result.flags.get("leaf_flag").unwrap().to_value(),
                FlagValue::String("test".to_string())
            );
            assert_eq!(
                result.flags.get("parent_flag").unwrap().to_value(),
                FlagValue::Boolean(true)
            );
        }
        {
            // Leaf flag evaluates to false
            let result = matcher
                .evaluate_all_feature_flags(
                    flags.clone(),
                    None,
                    None,
                    None,
                    Uuid::new_v4(),
                    None,
                    false,
                )
                .await
                .unwrap();
            assert!(!result.errors_while_computing_flags);
            assert_eq!(
                result.flags.get("leaf_flag").unwrap().to_value(),
                FlagValue::Boolean(false)
            );
            assert_eq!(
                result.flags.get("parent_flag").unwrap().to_value(),
                FlagValue::Boolean(false)
            );
        }
    }

    #[tokio::test]
    async fn test_get_matching_variant_with_cache() {
        let flag = create_test_flag_with_variants(1);
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let mut group_type_mapping_cache = GroupTypeMappingCache::new(1);
        let group_types_to_indexes = [("group_type_1".to_string(), 1)].into_iter().collect();
        let indexes_to_types = [(1, "group_type_1".to_string())].into_iter().collect();
        group_type_mapping_cache.set_test_mappings(group_types_to_indexes, indexes_to_types);

        let groups = HashMap::from([("group_type_1".to_string(), json!("group_key_1"))]);

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            1,
            context.create_postgres_router(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            Some(groups),
        );
        let variant = matcher.get_matching_variant(&flag, None, &None).unwrap();
        assert!(variant.is_some(), "No variant was selected");
        assert!(
            ["control", "test", "test2"].contains(&variant.unwrap().as_str()),
            "Selected variant is not one of the expected options"
        );
    }

    #[tokio::test]
    async fn test_get_matching_variant_with_db() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let flag = create_test_flag_with_variants(team.id);

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.id);
        group_type_mapping_cache
            .init(context.persons_reader.clone())
            .await
            .unwrap();

        let router = context.create_postgres_router();
        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            None,
        );

        let variant = matcher.get_matching_variant(&flag, None, &None).unwrap();
        assert!(variant.is_some());
        assert!(["control", "test", "test2"].contains(&variant.unwrap().as_str()));
    }

    #[tokio::test]
    async fn test_is_condition_match_empty_properties() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let flag = create_test_flag(
            Some(1),
            None,
            None,
            None,
            Some(FlagFilters {
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
            }),
            None,
            None,
            None,
        );

        let condition = FlagPropertyGroup {
            variant: None,
            properties: Some(vec![]),
            rollout_percentage: Some(100.0),
            ..Default::default()
        };

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            1,
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );
        let (is_match, reason) = matcher
            .is_condition_match(&flag, &condition, &HashMap::new(), None, &None)
            .unwrap();
        assert!(is_match);
        assert_eq!(reason, FeatureFlagMatchReason::ConditionMatch);
    }

    #[tokio::test]
    async fn test_is_condition_match_flag_value_operator() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let flag = create_test_flag(
            Some(2),
            None,
            None,
            None,
            Some(FlagFilters {
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
            }),
            None,
            None,
            None,
        );

        let condition = FlagPropertyGroup {
            variant: None,
            properties: Some(vec![PropertyFilter {
                key: "1".to_string(),
                value: Some(json!(true)),
                operator: Some(OperatorType::FlagEvaluatesTo),
                prop_type: PropertyType::Flag,
                group_type_index: None,
                negation: None,
            }]),
            rollout_percentage: Some(100.0),
            ..Default::default()
        };

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            1,
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );
        matcher
            .flag_evaluation_state
            .add_flag_evaluation_result(1, FlagValue::Boolean(true));
        let (is_match, reason) = matcher
            .is_condition_match(&flag, &condition, &HashMap::new(), None, &None)
            .unwrap();
        assert!(is_match);
        assert_eq!(reason, FeatureFlagMatchReason::ConditionMatch);
    }

    fn create_test_flag_with_variants(team_id: TeamId) -> FeatureFlag {
        FeatureFlag {
            id: 1,
            team_id,
            name: Some("Test Flag".to_string()),
            key: "test_flag".to_string(),
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: Some(MultivariateFlagOptions {
                    variants: vec![
                        MultivariateFlagVariant {
                            name: Some("Control".to_string()),
                            key: "control".to_string(),
                            rollout_percentage: 33.0,
                        },
                        MultivariateFlagVariant {
                            name: Some("Test".to_string()),
                            key: "test".to_string(),
                            rollout_percentage: 33.0,
                        },
                        MultivariateFlagVariant {
                            name: Some("Test2".to_string()),
                            key: "test2".to_string(),
                            rollout_percentage: 34.0,
                        },
                    ],
                }),
                aggregation_group_type_index: Some(1),
                payloads: None,
                super_groups: None,

                holdout: None,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: None,
        }
    }

    #[tokio::test]
    async fn test_overrides_avoid_db_lookups() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("test@example.com")),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let person_property_overrides =
            HashMap::from([("email".to_string(), json!("test@example.com"))]);

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        reset_fetch_calls_count();
        let result = matcher
            .evaluate_all_feature_flags(
                FeatureFlagList {
                    flags: vec![flag.clone()],
                    ..Default::default()
                },
                Some(person_property_overrides),
                None,
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();

        let fetch_calls = get_fetch_calls_count();
        assert_eq!(
            fetch_calls,
            0,
            "Expected fetch_and_locally_cache_all_relevant_properties to be called exactly 0 times, but it was called {fetch_calls} times",
        );
        let legacy_response = LegacyFlagsResponse::from_response(result);
        assert!(!legacy_response.errors_while_computing_flags);
        assert_eq!(
            legacy_response.feature_flags.get("test_flag"),
            Some(&FlagValue::Boolean(true))
        );

        let cache = &matcher.flag_evaluation_state;
        assert!(cache.person_properties.is_none());
    }

    #[tokio::test]
    async fn test_concurrent_flag_evaluation() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let team_id = team.id;
        let flag = Arc::new(create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
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
            }),
            None,
            None,
            None,
        ));

        let mut handles = vec![];
        for i in 0..100 {
            let flag_clone = flag.clone();
            let router = context.create_postgres_router();
            let cohort_cache_clone = cohort_cache.clone();
            handles.push(tokio::spawn(async move {
                let matcher = FeatureFlagMatcher::new(
                    format!("test_user_{i}"),
                    None, // device_id
                    team_id,
                    router,
                    cohort_cache_clone,
                    None,
                    None,
                );
                matcher.get_match(&flag_clone, None, None, &None).unwrap()
            }));
        }

        let results: Vec<FeatureFlagMatch> = futures::future::join_all(handles)
            .await
            .into_iter()
            .map(|r| r.unwrap())
            .collect();

        // Check that all evaluations completed without errors
        assert_eq!(results.len(), 100);
    }

    #[tokio::test]
    async fn test_property_operators() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![
                        PropertyFilter {
                            key: "age".to_string(),
                            value: Some(json!(25)),
                            operator: Some(OperatorType::Gte),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        },
                        PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("example@domain.com")),
                            operator: Some(OperatorType::Icontains),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        },
                    ]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        context
            .insert_person(
                team.id,
                "test_user".to_string(),
                Some(json!({"email": "user@example@domain.com", "age": 30})),
            )
            .await
            .unwrap();

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_empty_hashed_identifier() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let flag = create_test_flag(
            Some(1),
            None,
            None,
            None,
            Some(FlagFilters {
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
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "".to_string(),
            None, // device_id
            1,
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        // With empty distinct_id and 100% rollout, the flag should match
        // This is consistent with the Python implementation
        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_rollout_percentage() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let mut flag = create_test_flag(
            Some(1),
            None,
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(0.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            1,
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        assert!(!result.matches);

        // Now set the rollout percentage to 100%
        flag.filters.groups[0].rollout_percentage = Some(100.0);

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_uneven_variant_distribution() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let mut flag = create_test_flag_with_variants(1);

        // Adjust variant rollout percentages to be uneven
        flag.filters.multivariate.as_mut().unwrap().variants = vec![
            MultivariateFlagVariant {
                name: Some("Control".to_string()),
                key: "control".to_string(),
                rollout_percentage: 10.0,
            },
            MultivariateFlagVariant {
                name: Some("Test".to_string()),
                key: "test".to_string(),
                rollout_percentage: 30.0,
            },
            MultivariateFlagVariant {
                name: Some("Test2".to_string()),
                key: "test2".to_string(),
                rollout_percentage: 60.0,
            },
        ];

        // Ensure the flag is person-based by setting aggregation_group_type_index to None
        flag.filters.aggregation_group_type_index = None;

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            1,
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );

        let mut control_count = 0;
        let mut test_count = 0;
        let mut test2_count = 0;

        // Run the test multiple times to simulate distribution
        for i in 0..1000 {
            matcher.distinct_id = format!("user_{i}");
            let variant = matcher.get_matching_variant(&flag, None, &None).unwrap();
            match variant.as_deref() {
                Some("control") => control_count += 1,
                Some("test") => test_count += 1,
                Some("test2") => test2_count += 1,
                _ => (),
            }
        }

        // Check that the distribution roughly matches the rollout percentages
        let total = control_count + test_count + test2_count;
        assert!((control_count as f64 / total as f64 - 0.10).abs() < 0.05);
        assert!((test_count as f64 / total as f64 - 0.30).abs() < 0.05);
        assert!((test2_count as f64 / total as f64 - 0.60).abs() < 0.05);
    }

    #[tokio::test]
    async fn test_missing_properties_in_db() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // Insert a person without properties
        context
            .insert_person(team.id, "test_user".to_string(), None)
            .await
            .unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("test@example.com")),
                        operator: None,
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_malformed_property_data() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // Insert a person with malformed properties
        context
            .insert_person(
                team.id,
                "test_user".to_string(),
                Some(json!({"age": "not_a_number"})),
            )
            .await
            .unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "age".to_string(),
                        value: Some(json!(25)),
                        operator: Some(OperatorType::Gte),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        // The match should fail due to invalid data type
        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_evaluation_reasons() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let flag = create_test_flag(
            Some(1),
            None,
            None,
            None,
            Some(FlagFilters {
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
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            1,
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );

        let (is_match, reason) = matcher
            .is_condition_match(&flag, &flag.filters.groups[0], &HashMap::new(), None, &None)
            .unwrap();

        assert!(is_match);
        assert_eq!(reason, FeatureFlagMatchReason::ConditionMatch);
    }

    #[tokio::test]
    async fn test_complex_conditions() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Complex Flag".to_string()),
            Some("complex_flag".to_string()),
            Some(FlagFilters {
                groups: vec![
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("user1@example.com")),
                            operator: None,
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                        ..Default::default()
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "age".to_string(),
                            value: Some(json!(30)),
                            operator: Some(OperatorType::Gte),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                        ..Default::default()
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            Some(false),
            Some(true),
            Some(false),
        );

        context
            .insert_person(
                team.id,
                "test_user".to_string(),
                Some(json!({"email": "user2@example.com", "age": 35})),
            )
            .await
            .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_complex_cohort_conditions() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // Insert a cohort with complex conditions
        let cohort_row = context
            .insert_cohort(
                team.id,
                None,
                json!({
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [{
                                    "key": "email",
                                    "type": "person",
                                    "value": "@posthog\\.com$",
                                    "negation": false,
                                    "operator": "regex"
                                }]
                            },
                            {
                                "type": "AND",
                                "values": [{
                                    "key": "email",
                                    "type": "person",
                                    "value": ["fuziontech@gmail.com"],
                                    "operator": "exact"
                                }]
                            },
                            {
                                "type": "AND",
                                "values": [{
                                    "key": "distinct_id",
                                    "type": "person",
                                    "value": ["D_9eluZIT3gqjO9dJqo1aDeqTbAG4yLwXFhN0bz_Vfc"],
                                    "operator": "exact"
                                }]
                            },
                            {
                                "type": "OR",
                                "values": [{
                                    "key": "email",
                                    "type": "person",
                                    "value": ["neil@posthog.com"],
                                    "negation": false,
                                    "operator": "exact"
                                }]
                            },
                            {
                                "type": "OR",
                                "values": [{
                                    "key": "email",
                                    "type": "person",
                                    "value": ["corywatilo@gmail.com"],
                                    "negation": false,
                                    "operator": "exact"
                                }]
                            },
                            {
                                "type": "OR",
                                "values": [{
                                    "key": "email",
                                    "type": "person",
                                    "value": "@leads\\.io$",
                                    "negation": false,
                                    "operator": "regex"
                                }]
                            },
                            {
                                "type": "OR",
                                "values": [{
                                    "key": "email",
                                    "type": "person",
                                    "value": "@desertcart\\.io$",
                                    "negation": false,
                                    "operator": "regex"
                                }]
                            }
                        ]
                    }
                }),
                false,
            )
            .await
            .unwrap();

        // Test case 1: Should match - posthog.com email (AND condition)
        context
            .insert_person(
                team.id,
                "test_user_1".to_string(),
                Some(json!({
                    "email": "test@posthog.com",
                    "distinct_id": "test_user_1"
                })),
            )
            .await
            .unwrap();

        // Test case 2: Should match - fuziontech@gmail.com (AND condition)
        context
            .insert_person(
                team.id,
                "test_user_2".to_string(),
                Some(json!({
                    "email": "fuziontech@gmail.com",
                    "distinct_id": "test_user_2"
                })),
            )
            .await
            .unwrap();

        // Test case 3: Should match - specific distinct_id (AND condition)
        context
            .insert_person(
                team.id,
                "D_9eluZIT3gqjO9dJqo1aDeqTbAG4yLwXFhN0bz_Vfc".to_string(),
                Some(json!({
                    "email": "other@example.com",
                    "distinct_id": "D_9eluZIT3gqjO9dJqo1aDeqTbAG4yLwXFhN0bz_Vfc"
                })),
            )
            .await
            .unwrap();

        // Test case 4: Should match - neil@posthog.com (OR condition)
        context
            .insert_person(
                team.id,
                "test_user_4".to_string(),
                Some(json!({
                    "email": "neil@posthog.com",
                    "distinct_id": "test_user_4"
                })),
            )
            .await
            .unwrap();

        // Test case 5: Should match - @leads.io email (OR condition with regex)
        context
            .insert_person(
                team.id,
                "test_user_5".to_string(),
                Some(json!({
                    "email": "test@leads.io",
                    "distinct_id": "test_user_5"
                })),
            )
            .await
            .unwrap();

        // Test case 6: Should NOT match - random email
        context
            .insert_person(
                team.id,
                "test_user_6".to_string(),
                Some(json!({
                    "email": "random@example.com",
                    "distinct_id": "test_user_6"
                })),
            )
            .await
            .unwrap();

        // Create a feature flag using this cohort and verify matches
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort_row.id)),
                        operator: Some(OperatorType::In),
                        prop_type: PropertyType::Cohort,
                        group_type_index: None,
                        negation: Some(false),
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        // Test each case
        for (user_id, should_match) in [
            ("test_user_1", true),                                 // @posthog.com
            ("test_user_2", true),                                 // fuziontech@gmail.com
            ("D_9eluZIT3gqjO9dJqo1aDeqTbAG4yLwXFhN0bz_Vfc", true), // specific distinct_id
            ("test_user_4", true),                                 // neil@posthog.com
            ("test_user_5", true),                                 // @leads.io
            ("test_user_6", false),                                // random@example.com
        ] {
            let router = context.create_postgres_router();
            let mut matcher = FeatureFlagMatcher::new(
                user_id.to_string(),
                None, // device_id
                team.id,
                router,
                cohort_cache.clone(),
                None,
                None,
            );

            matcher
                .prepare_flag_evaluation_state(&[&flag])
                .await
                .unwrap();

            let result = matcher.get_match(&flag, None, None, &None).unwrap();
            assert_eq!(
                result.matches,
                should_match,
                "User {} should{} match",
                user_id,
                if should_match { "" } else { " not" }
            );
        }
    }

    #[tokio::test]
    async fn test_super_condition_matches_boolean() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Super Condition Flag".to_string()),
            Some("super_condition_flag".to_string()),
            Some(FlagFilters {
                groups: vec![
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("fake@posthog.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(0.0),
                        variant: None,
                        ..Default::default()
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("test@posthog.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                        ..Default::default()
                    },
                    FlagPropertyGroup {
                        properties: None,
                        rollout_percentage: Some(50.0),
                        variant: None,
                        ..Default::default()
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "is_enabled".to_string(),
                        value: Some(json!(["true"])),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }]),

                holdout: None,
            }),
            None,
            None,
            None,
        );

        context
            .insert_person(
                team.id,
                "test_id".to_string(),
                Some(json!({"email": "test@posthog.com", "is_enabled": true})),
            )
            .await
            .unwrap();

        context
            .insert_person(team.id, "lil_id".to_string(), None)
            .await
            .unwrap();

        context
            .insert_person(team.id, "another_id".to_string(), None)
            .await
            .unwrap();

        let router = context.create_postgres_router();
        let mut matcher_test_id = FeatureFlagMatcher::new(
            "test_id".to_string(),
            None, // device_id
            team.id,
            router.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_example_id = FeatureFlagMatcher::new(
            "lil_id".to_string(),
            None, // device_id
            team.id,
            router.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_another_id = FeatureFlagMatcher::new(
            "another_id".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher_test_id
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        matcher_example_id
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        matcher_another_id
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result_test_id = matcher_test_id.get_match(&flag, None, None, &None).unwrap();
        let result_example_id = matcher_example_id
            .get_match(&flag, None, None, &None)
            .unwrap();
        let result_another_id = matcher_another_id
            .get_match(&flag, None, None, &None)
            .unwrap();

        assert!(result_test_id.matches);
        assert!(result_test_id.reason == FeatureFlagMatchReason::SuperConditionValue);
        assert!(result_example_id.matches);
        assert!(result_example_id.reason == FeatureFlagMatchReason::ConditionMatch);
        assert!(!result_another_id.matches);
        assert!(result_another_id.reason == FeatureFlagMatchReason::OutOfRolloutBound);
    }

    #[tokio::test]
    async fn test_super_condition_matches_string() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        context
            .insert_person(
                team.id,
                "test_id".to_string(),
                Some(json!({"email": "test@posthog.com", "is_enabled": "true"})),
            )
            .await
            .unwrap();

        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Super Condition Flag".to_string()),
            Some("super_condition_flag".to_string()),
            Some(FlagFilters {
                groups: vec![
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("fake@posthog.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(0.0),
                        variant: None,
                        ..Default::default()
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("test@posthog.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                        ..Default::default()
                    },
                    FlagPropertyGroup {
                        properties: None,
                        rollout_percentage: Some(50.0),
                        variant: None,
                        ..Default::default()
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "is_enabled".to_string(),
                        value: Some(json!("true")),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }]),

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_id".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        assert!(result.matches);
        assert_eq!(result.reason, FeatureFlagMatchReason::SuperConditionValue);
        assert_eq!(result.condition_index, Some(0));
    }

    #[tokio::test]
    async fn test_super_condition_matches_and_false() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        context
            .insert_person(
                team.id,
                "test_id".to_string(),
                Some(json!({"email": "test@posthog.com", "is_enabled": true})),
            )
            .await
            .unwrap();

        context
            .insert_person(team.id, "another_id".to_string(), None)
            .await
            .unwrap();

        context
            .insert_person(team.id, "lil_id".to_string(), None)
            .await
            .unwrap();

        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Super Condition Flag".to_string()),
            Some("super_condition_flag".to_string()),
            Some(FlagFilters {
                groups: vec![
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("fake@posthog.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(0.0),
                        variant: None,
                        ..Default::default()
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("test@posthog.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                        ..Default::default()
                    },
                    FlagPropertyGroup {
                        properties: None,
                        rollout_percentage: Some(50.0),
                        variant: None,
                        ..Default::default()
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "is_enabled".to_string(),
                        value: Some(json!(false)),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }]),

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher_test_id = FeatureFlagMatcher::new(
            "test_id".to_string(),
            None, // device_id
            team.id,
            router.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_example_id = FeatureFlagMatcher::new(
            "lil_id".to_string(),
            None, // device_id
            team.id,
            router.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_another_id = FeatureFlagMatcher::new(
            "another_id".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher_test_id
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        matcher_example_id
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        matcher_another_id
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result_test_id = matcher_test_id.get_match(&flag, None, None, &None).unwrap();
        let result_example_id = matcher_example_id
            .get_match(&flag, None, None, &None)
            .unwrap();
        let result_another_id = matcher_another_id
            .get_match(&flag, None, None, &None)
            .unwrap();

        assert!(!result_test_id.matches);
        assert_eq!(
            result_test_id.reason,
            FeatureFlagMatchReason::SuperConditionValue
        );
        assert_eq!(result_test_id.condition_index, Some(0));

        assert!(result_example_id.matches);
        assert_eq!(
            result_example_id.reason,
            FeatureFlagMatchReason::ConditionMatch
        );
        assert_eq!(result_example_id.condition_index, Some(2));

        assert!(!result_another_id.matches);
        assert_eq!(
            result_another_id.reason,
            FeatureFlagMatchReason::OutOfRolloutBound
        );
        assert_eq!(result_another_id.condition_index, Some(2));
    }

    #[tokio::test]
    async fn test_basic_cohort_matching() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // Insert a cohort with the condition that matches the test user's properties
        let cohort_row = context
            .insert_cohort(
                team.id,
                None,
                json!({
                    "properties": {
                        "type": "OR",
                        "values": [{
                            "type": "OR",
                            "values": [{
                                "key": "$browser_version",
                                "type": "person",
                                "value": "125",
                                "negation": false,
                                "operator": "gt"
                            }]
                        }]
                    }
                }),
                false,
            )
            .await
            .unwrap();

        // Insert a person with properties that match the cohort condition
        context
            .insert_person(
                team.id,
                "test_user".to_string(),
                Some(json!({"$browser_version": 126})),
            )
            .await
            .unwrap();

        // Define a flag with a cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort_row.id)),
                        operator: Some(OperatorType::In),
                        prop_type: PropertyType::Cohort,
                        group_type_index: None,
                        negation: Some(false),
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_not_in_cohort_matching() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // Insert a cohort with a condition that does not match the test user's properties
        let cohort_row = context
            .insert_cohort(
                team.id,
                None,
                json!({
                    "properties": {
                        "type": "OR",
                        "values": [{
                            "type": "OR",
                            "values": [{
                                "key": "$browser_version",
                                "type": "person",
                                "value": "130",
                                "negation": false,
                                "operator": "gt"
                            }]
                        }]
                    }
                }),
                false,
            )
            .await
            .unwrap();

        // Insert a person with properties that do not match the cohort condition
        context
            .insert_person(
                team.id,
                "test_user".to_string(),
                Some(json!({"$browser_version": 126})),
            )
            .await
            .unwrap();

        // Define a flag with a NotIn cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort_row.id)),
                        operator: Some(OperatorType::NotIn),
                        prop_type: PropertyType::Cohort,
                        group_type_index: None,
                        negation: Some(false),
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_not_in_cohort_matching_user_in_cohort() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // Insert a cohort with a condition that matches the test user's properties
        let cohort_row = context
            .insert_cohort(
                team.id,
                None,
                json!({
                    "properties": {
                        "type": "OR",
                        "values": [{
                            "type": "OR",
                            "values": [{
                                "key": "$browser_version",
                                "type": "person",
                                "value": "125",
                                "negation": false,
                                "operator": "gt"
                            }]
                        }]
                    }
                }),
                false,
            )
            .await
            .unwrap();

        // Insert a person with properties that match the cohort condition
        context
            .insert_person(
                team.id,
                "test_user".to_string(),
                Some(json!({"$browser_version": 126})),
            )
            .await
            .unwrap();

        // Define a flag with a NotIn cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort_row.id)),
                        operator: Some(OperatorType::NotIn),
                        prop_type: PropertyType::Cohort,
                        group_type_index: None,
                        negation: Some(false),
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        // The user matches the cohort, but the flag is set to NotIn, so it should evaluate to false
        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_cohort_dependent_on_another_cohort() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // Insert a base cohort
        let base_cohort_row = context
            .insert_cohort(
                team.id,
                None,
                json!({
                    "properties": {
                        "type": "OR",
                        "values": [{
                            "type": "OR",
                            "values": [{
                                "key": "$browser_version",
                                "type": "person",
                                "value": "125",
                                "negation": false,
                                "operator": "gt"
                            }]
                        }]
                    }
                }),
                false,
            )
            .await
            .unwrap();

        // Insert a dependent cohort that includes the base cohort
        let dependent_cohort_row = context
            .insert_cohort(
                team.id,
                None,
                json!({
                    "properties": {
                        "type": "OR",
                        "values": [{
                            "type": "OR",
                            "values": [{
                                "key": "id",
                                "type": "cohort",
                                "value": base_cohort_row.id,
                                "negation": false,
                                "operator": "in"
                            }]
                        }]
                    }
                }),
                false,
            )
            .await
            .unwrap();

        // Insert a person with properties that match the base cohort condition
        context
            .insert_person(
                team.id,
                "test_user".to_string(),
                Some(json!({"$browser_version": 126})),
            )
            .await
            .unwrap();

        // Define a flag with a cohort filter that depends on another cohort
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(dependent_cohort_row.id)),
                        operator: Some(OperatorType::In),
                        prop_type: PropertyType::Cohort,
                        group_type_index: None,
                        negation: Some(false),
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_in_cohort_matching_user_not_in_cohort() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // Insert a cohort with a condition that does not match the test user's properties
        let cohort_row = context
            .insert_cohort(
                team.id,
                None,
                json!({
                    "properties": {
                        "type": "OR",
                        "values": [{
                            "type": "OR",
                            "values": [{
                                "key": "$browser_version",
                                "type": "person",
                                "value": "130",
                                "negation": false,
                                "operator": "gt"
                            }]
                        }]
                    }
                }),
                false,
            )
            .await
            .unwrap();

        // Insert a person with properties that do not match the cohort condition
        context
            .insert_person(
                team.id,
                "test_user".to_string(),
                Some(json!({"$browser_version": 125})),
            )
            .await
            .unwrap();

        // Define a flag with an In cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort_row.id)),
                        operator: Some(OperatorType::In),
                        prop_type: PropertyType::Cohort,
                        group_type_index: None,
                        negation: Some(false),
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        // The user does not match the cohort, and the flag is set to In, so it should evaluate to false
        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_static_cohort_matching_user_in_cohort() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // Insert a static cohort
        let cohort = context
            .insert_cohort(
                team.id,
                Some("Static Cohort".to_string()),
                json!({}), // Static cohorts don't have property filters
                true,      // is_static = true
            )
            .await
            .unwrap();

        // Insert a person
        let distinct_id = "static_user".to_string();
        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "static@user.com"})),
            )
            .await
            .unwrap();

        // Retrieve the person's ID
        let person_id = context
            .get_person_id_by_distinct_id(team.id, &distinct_id)
            .await
            .unwrap();

        // Associate the person with the static cohort
        context
            .add_person_to_cohort(cohort.id, person_id)
            .await
            .unwrap();

        // Define a flag with an 'In' cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort.id)),
                        operator: Some(OperatorType::In),
                        prop_type: PropertyType::Cohort,
                        group_type_index: None,
                        negation: Some(false),
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        assert!(
            result.matches,
            "User should match the static cohort and flag"
        );
    }

    #[tokio::test]
    async fn test_static_cohort_matching_user_not_in_cohort() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // Insert a static cohort
        let cohort = context
            .insert_cohort(
                team.id,
                Some("Another Static Cohort".to_string()),
                json!({}), // Static cohorts don't have property filters
                true,
            )
            .await
            .unwrap();

        // Insert a person
        let distinct_id = "non_static_user".to_string();
        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "nonstatic@user.com"})),
            )
            .await
            .unwrap();

        // Note: Do NOT associate the person with the static cohort

        // Define a flag with an 'In' cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort.id)),
                        operator: Some(OperatorType::In),
                        prop_type: PropertyType::Cohort,
                        group_type_index: None,
                        negation: Some(false),
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        assert!(
            !result.matches,
            "User should not match the static cohort and flag"
        );
    }

    #[tokio::test]
    async fn test_static_cohort_not_in_matching_user_not_in_cohort() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // Insert a static cohort
        let cohort = context
            .insert_cohort(
                team.id,
                Some("Static Cohort NotIn".to_string()),
                json!({}), // Static cohorts don't have property filters
                true,      // is_static = true
            )
            .await
            .unwrap();

        // Insert a person
        let distinct_id = "not_in_static_user".to_string();
        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "notinstatic@user.com"})),
            )
            .await
            .unwrap();

        // No association with the static cohort

        // Define a flag with a 'NotIn' cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort.id)),
                        operator: Some(OperatorType::NotIn),
                        prop_type: PropertyType::Cohort,
                        group_type_index: None,
                        negation: Some(false),
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        assert!(
            result.matches,
            "User not in the static cohort should match the 'NotIn' flag"
        );
    }

    #[tokio::test]
    async fn test_static_cohort_not_in_matching_user_in_cohort() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // Insert a static cohort
        let cohort = context
            .insert_cohort(
                team.id,
                Some("Static Cohort NotIn User In".to_string()),
                json!({}), // Static cohorts don't have property filters
                true,      // is_static = true
            )
            .await
            .unwrap();

        // Insert a person
        let distinct_id = "in_not_in_static_user".to_string();
        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "innotinstatic@user.com"})),
            )
            .await
            .unwrap();

        // Retrieve the person's ID
        let person_id = context
            .get_person_id_by_distinct_id(team.id, &distinct_id)
            .await
            .unwrap();

        // Associate the person with the static cohort
        context
            .add_person_to_cohort(cohort.id, person_id)
            .await
            .unwrap();

        // Define a flag with a 'NotIn' cohort filter
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort.id)),
                        operator: Some(OperatorType::NotIn),
                        prop_type: PropertyType::Cohort,
                        group_type_index: None,
                        negation: Some(false),
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        assert!(
            !result.matches,
            "User in the static cohort should not match the 'NotIn' flag"
        );
    }

    #[tokio::test]
    async fn test_evaluate_feature_flags_with_experience_continuity() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let distinct_id = "user3".to_string();

        // Insert person
        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "user3@example.com"})),
            )
            .await
            .unwrap();

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.id);
        group_type_mapping_cache
            .init(context.persons_reader.clone())
            .await
            .unwrap();

        // Create flag with experience continuity
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("flag_continuity".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("user3@example.com")),
                        operator: None,
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(true),
        );

        // Set hash key override
        let router = context.create_postgres_router();
        set_feature_flag_hash_key_overrides(
            &router,
            team.id,
            vec![distinct_id.clone()],
            "hash_key_continuity".to_string(),
        )
        .await
        .unwrap();

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
            ..Default::default()
        };

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            None,
            None,
            Some("hash_key_continuity".to_string()),
            Uuid::new_v4(),
            None,
            false,
        )
        .await
        .unwrap();

        let legacy_response = LegacyFlagsResponse::from_response(result);
        assert!(
            !legacy_response.errors_while_computing_flags,
            "No error should occur"
        );
        assert_eq!(
            legacy_response.feature_flags.get("flag_continuity"),
            Some(&FlagValue::Boolean(true)),
            "Flag should be evaluated as true with continuity"
        );
    }

    #[tokio::test]
    async fn test_evaluate_feature_flags_with_continuity_missing_override() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let distinct_id = "user4".to_string();

        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "user4@example.com"})),
            )
            .await
            .unwrap();

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.id);
        group_type_mapping_cache
            .init(context.persons_reader.clone())
            .await
            .unwrap();

        // Create flag with experience continuity
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("flag_continuity_missing".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("user4@example.com")),
                        operator: None,
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(true),
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
            ..Default::default()
        };

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            None,
        )
        .evaluate_all_feature_flags(flags, None, None, None, Uuid::new_v4(), None, false)
        .await
        .unwrap();

        assert!(result.flags.get("flag_continuity_missing").unwrap().enabled);

        let legacy_response = LegacyFlagsResponse::from_response(result);
        assert!(
            !legacy_response.errors_while_computing_flags,
            "No error should occur"
        );
        assert_eq!(
            legacy_response.feature_flags.get("flag_continuity_missing"),
            Some(&FlagValue::Boolean(true)),
            "Flag should be evaluated as true even without continuity override"
        );
    }

    #[tokio::test]
    async fn test_evaluate_all_feature_flags_mixed_continuity() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let distinct_id = "user5".to_string();

        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "user5@example.com"})),
            )
            .await
            .unwrap();

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.id);
        group_type_mapping_cache
            .init(context.persons_reader.clone())
            .await
            .unwrap();

        // Create flag with continuity
        let flag_continuity = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("flag_continuity_mix".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("user5@example.com")),
                        operator: None,
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(true),
        );

        // Create flag without continuity
        let flag_no_continuity = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("flag_no_continuity_mix".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "age".to_string(),
                        value: Some(json!(30)),
                        operator: Some(OperatorType::Gt),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(false),
        );

        // Set hash key override for the continuity flag
        let router2 = context.create_postgres_router();
        set_feature_flag_hash_key_overrides(
            &router2,
            team.id,
            vec![distinct_id.clone()],
            "hash_key_mixed".to_string(),
        )
        .await
        .unwrap();

        let flags = FeatureFlagList {
            flags: vec![flag_continuity.clone(), flag_no_continuity.clone()],
            ..Default::default()
        };

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            Some(HashMap::from([("age".to_string(), json!(35))])),
            None,
            Some("hash_key_mixed".to_string()),
            Uuid::new_v4(),
            None,
            false,
        )
        .await
        .unwrap();

        let legacy_response = LegacyFlagsResponse::from_response(result);
        assert!(
            !legacy_response.errors_while_computing_flags,
            "No error should occur"
        );
        assert_eq!(
            legacy_response.feature_flags.get("flag_continuity_mix"),
            Some(&FlagValue::Boolean(true)),
            "Continuity flag should be evaluated as true"
        );
        assert_eq!(
            legacy_response.feature_flags.get("flag_no_continuity_mix"),
            Some(&FlagValue::Boolean(true)),
            "Non-continuity flag should be evaluated based on properties"
        );
    }

    #[tokio::test]
    async fn test_variant_override_in_condition() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let distinct_id = "test_user".to_string();

        // Insert a person with properties that will match our condition
        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "test@example.com"})),
            )
            .await
            .unwrap();

        // Create a flag with multiple variants and a condition with a variant override
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("test_flag".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("test@example.com")),
                        operator: None,
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: Some("control".to_string()), // Override to always show "control" variant
                    ..Default::default()
                }],
                multivariate: Some(MultivariateFlagOptions {
                    variants: vec![
                        MultivariateFlagVariant {
                            name: Some("Control".to_string()),
                            key: "control".to_string(),
                            rollout_percentage: 25.0,
                        },
                        MultivariateFlagVariant {
                            name: Some("Test".to_string()),
                            key: "test".to_string(),
                            rollout_percentage: 25.0,
                        },
                        MultivariateFlagVariant {
                            name: Some("Test2".to_string()),
                            key: "test2".to_string(),
                            rollout_percentage: 50.0,
                        },
                    ],
                }),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None, &None).unwrap();

        // The condition matches and has a variant override, so it should return "control"
        // regardless of what the hash-based variant computation would return
        assert!(result.matches);
        assert_eq!(result.variant, Some("control".to_string()));

        // Now test with an invalid variant override
        let flag_invalid_override = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("test_flag_invalid".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("test@example.com")),
                        operator: None,
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: Some("nonexistent_variant".to_string()), // Override with invalid variant
                    ..Default::default()
                }],
                multivariate: Some(MultivariateFlagOptions {
                    variants: vec![
                        MultivariateFlagVariant {
                            name: Some("Control".to_string()),
                            key: "control".to_string(),
                            rollout_percentage: 25.0,
                        },
                        MultivariateFlagVariant {
                            name: Some("Test".to_string()),
                            key: "test".to_string(),
                            rollout_percentage: 75.0,
                        },
                    ],
                }),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag_invalid_override])
            .await
            .unwrap();

        let result_invalid = matcher
            .get_match(&flag_invalid_override, None, None, &None)
            .unwrap();

        // The condition matches but has an invalid variant override,
        // so it should fall back to hash-based variant computation
        assert!(result_invalid.matches);
        assert!(result_invalid.variant.is_some()); // Will be either "control" or "test" based on hash
    }

    #[tokio::test]
    async fn test_feature_flag_with_holdout_filter() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // example_id is outside 70% holdout
        let _person1 = context
            .insert_person(
                team.id,
                "example_id".to_string(),
                Some(json!({"$some_prop": 5})),
            )
            .await
            .unwrap();

        // example_id2 is within 70% holdout
        let _person2 = context
            .insert_person(
                team.id,
                "example_id2".to_string(),
                Some(json!({"$some_prop": 5})),
            )
            .await
            .unwrap();

        let multivariate_json = MultivariateFlagOptions {
            variants: vec![
                MultivariateFlagVariant {
                    key: "first-variant".to_string(),
                    name: Some("First Variant".to_string()),
                    rollout_percentage: 50.0,
                },
                MultivariateFlagVariant {
                    key: "second-variant".to_string(),
                    name: Some("Second Variant".to_string()),
                    rollout_percentage: 25.0,
                },
                MultivariateFlagVariant {
                    key: "third-variant".to_string(),
                    name: Some("Third Variant".to_string()),
                    rollout_percentage: 25.0,
                },
            ],
        };

        let flag_with_holdout = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Flag with holdout".to_string()),
            Some("flag-with-gt-filter".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "$some_prop".to_string(),
                        value: Some(json!(4)),
                        operator: Some(OperatorType::Gt),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                holdout: Some(Holdout {
                    id: 1,
                    exclusion_percentage: 70.0,
                }),
                multivariate: Some(multivariate_json.clone()),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            Some(true),
            None,
        );

        let other_flag_with_holdout = create_test_flag(
            Some(2),
            Some(team.id),
            Some("Other flag with holdout".to_string()),
            Some("other-flag-with-gt-filter".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "$some_prop".to_string(),
                        value: Some(json!(4)),
                        operator: Some(OperatorType::Gt),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                holdout: Some(Holdout {
                    id: 1,
                    exclusion_percentage: 70.0,
                }),
                multivariate: Some(multivariate_json.clone()),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            Some(true),
            None,
        );

        let flag_without_holdout = create_test_flag(
            Some(3),
            Some(team.id),
            Some("Flag".to_string()),
            Some("other-flag-without-holdout-with-gt-filter".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "$some_prop".to_string(),
                        value: Some(json!(4)),
                        operator: Some(OperatorType::Gt),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                holdout: Some(Holdout {
                    id: 1,
                    exclusion_percentage: 0.0,
                }),
                multivariate: Some(multivariate_json),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            Some(true),
            None,
        );

        // regular flag evaluation when outside holdout
        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "example_id".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag_with_holdout])
            .await
            .unwrap();

        let result = matcher
            .get_match(&flag_with_holdout, None, None, &None)
            .unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("second-variant".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::ConditionMatch);

        // Test inside holdout behavior - should get holdout variant override
        let router2 = context.create_postgres_router();
        let mut matcher2 = FeatureFlagMatcher::new(
            "example_id2".to_string(),
            None, // device_id
            team.id,
            router2,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher2
            .prepare_flag_evaluation_state(&[
                &flag_with_holdout,
                &flag_without_holdout,
                &other_flag_with_holdout,
            ])
            .await
            .unwrap();

        let result = matcher2
            .get_match(&flag_with_holdout, None, None, &None)
            .unwrap();

        assert!(result.matches);
        assert_eq!(result.variant, Some("holdout-1".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::HoldoutConditionValue);

        // same should hold true for a different feature flag when within holdout
        let result = matcher2
            .get_match(&other_flag_with_holdout, None, None, &None)
            .unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("holdout-1".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::HoldoutConditionValue);

        // Test with matcher1 (outside holdout) to verify different variants
        let result = matcher
            .get_match(&other_flag_with_holdout, None, None, &None)
            .unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("third-variant".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::ConditionMatch);

        // when holdout exists but is zero, should default to regular flag evaluation
        let result = matcher
            .get_match(&flag_without_holdout, None, None, &None)
            .unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("second-variant".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::ConditionMatch);

        let result = matcher2
            .get_match(&flag_without_holdout, None, None, &None)
            .unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("second-variant".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::ConditionMatch);
    }

    #[tokio::test]
    async fn test_feature_flag_with_new_holdout_format() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // example_id is outside 70% holdout, example_id2 is within
        let _person1 = context
            .insert_person(
                team.id,
                "example_id".to_string(),
                Some(json!({"$some_prop": 5})),
            )
            .await
            .unwrap();

        let _person2 = context
            .insert_person(
                team.id,
                "example_id2".to_string(),
                Some(json!({"$some_prop": 5})),
            )
            .await
            .unwrap();

        let multivariate_json = MultivariateFlagOptions {
            variants: vec![
                MultivariateFlagVariant {
                    key: "first-variant".to_string(),
                    name: Some("First Variant".to_string()),
                    rollout_percentage: 50.0,
                },
                MultivariateFlagVariant {
                    key: "second-variant".to_string(),
                    name: Some("Second Variant".to_string()),
                    rollout_percentage: 25.0,
                },
                MultivariateFlagVariant {
                    key: "third-variant".to_string(),
                    name: Some("Third Variant".to_string()),
                    rollout_percentage: 25.0,
                },
            ],
        };

        // holdout field with id and exclusion_percentage
        let flag_with_new_holdout = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Flag with new holdout".to_string()),
            Some("flag-with-gt-filter".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "$some_prop".to_string(),
                        value: Some(json!(4)),
                        operator: Some(OperatorType::Gt),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],

                holdout: Some(Holdout {
                    id: 1,
                    exclusion_percentage: 70.0,
                }),
                multivariate: Some(multivariate_json.clone()),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            Some(true),
            None,
        );

        // Outside holdout — should get a regular variant
        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "example_id".to_string(),
            None,
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag_with_new_holdout])
            .await
            .unwrap();

        let result = matcher
            .get_match(&flag_with_new_holdout, None, None, &None)
            .unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("second-variant".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::ConditionMatch);

        // Inside holdout — should get holdout-{id} variant
        let router2 = context.create_postgres_router();
        let mut matcher2 = FeatureFlagMatcher::new(
            "example_id2".to_string(),
            None,
            team.id,
            router2,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher2
            .prepare_flag_evaluation_state(&[&flag_with_new_holdout])
            .await
            .unwrap();

        let result = matcher2
            .get_match(&flag_with_new_holdout, None, None, &None)
            .unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("holdout-1".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::HoldoutConditionValue);
    }

    #[tokio::test]
    async fn test_feature_flag_with_new_holdout_format_zero_percent() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let _person = context
            .insert_person(
                team.id,
                "example_id2".to_string(),
                Some(json!({"$some_prop": 5})),
            )
            .await
            .unwrap();

        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            None,
            Some("flag-zero-holdout".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "$some_prop".to_string(),
                        value: Some(json!(4)),
                        operator: Some(OperatorType::Gt),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],

                holdout: Some(Holdout {
                    id: 1,
                    exclusion_percentage: 0.0,
                }),
                multivariate: Some(MultivariateFlagOptions {
                    variants: vec![
                        MultivariateFlagVariant {
                            key: "control".to_string(),
                            name: None,
                            rollout_percentage: 50.0,
                        },
                        MultivariateFlagVariant {
                            key: "test".to_string(),
                            name: None,
                            rollout_percentage: 50.0,
                        },
                    ],
                }),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            Some(true),
            None,
        );

        // 0% exclusion — nobody is held out, should get a regular variant
        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "example_id2".to_string(),
            None,
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None, &None).unwrap();
        assert!(result.matches);
        assert_eq!(result.reason, FeatureFlagMatchReason::ConditionMatch);
        assert!(
            result.variant == Some("control".to_string())
                || result.variant == Some("test".to_string()),
            "Expected a regular variant, got {:?}",
            result.variant
        );
    }

    #[tokio::test]
    async fn test_feature_flag_with_new_holdout_format_hundred_percent() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let _person = context
            .insert_person(
                team.id,
                "example_id".to_string(),
                Some(json!({"$some_prop": 5})),
            )
            .await
            .unwrap();

        let _person2 = context
            .insert_person(
                team.id,
                "example_id2".to_string(),
                Some(json!({"$some_prop": 5})),
            )
            .await
            .unwrap();

        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            None,
            Some("flag-full-holdout".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "$some_prop".to_string(),
                        value: Some(json!(4)),
                        operator: Some(OperatorType::Gt),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],

                holdout: Some(Holdout {
                    id: 1,
                    exclusion_percentage: 100.0,
                }),
                multivariate: Some(MultivariateFlagOptions {
                    variants: vec![
                        MultivariateFlagVariant {
                            key: "control".to_string(),
                            name: None,
                            rollout_percentage: 50.0,
                        },
                        MultivariateFlagVariant {
                            key: "test".to_string(),
                            name: None,
                            rollout_percentage: 50.0,
                        },
                    ],
                }),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            }),
            None,
            Some(true),
            None,
        );

        // 100% exclusion — everyone is held out, both users should get holdout variant
        for distinct_id in ["example_id", "example_id2"] {
            let router = context.create_postgres_router();
            let mut matcher = FeatureFlagMatcher::new(
                distinct_id.to_string(),
                None,
                team.id,
                router,
                cohort_cache.clone(),
                None,
                None,
            );

            matcher
                .prepare_flag_evaluation_state(&[&flag])
                .await
                .unwrap();

            let result = matcher.get_match(&flag, None, None, &None).unwrap();
            assert!(result.matches);
            assert_eq!(result.variant, Some("holdout-1".to_string()));
            assert_eq!(result.reason, FeatureFlagMatchReason::HoldoutConditionValue);
        }
    }

    #[tokio::test]
    async fn test_variants() {
        // Ported from posthog/test/test_feature_flag.py test_variants
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let flag = FeatureFlag {
            id: 1,
            team_id: team.id,
            name: Some("Beta feature".to_string()),
            key: "beta-feature".to_string(),
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: None,
                    variant: None,
                    ..Default::default()
                }],
                multivariate: Some(MultivariateFlagOptions {
                    variants: vec![
                        MultivariateFlagVariant {
                            name: Some("First Variant".to_string()),
                            key: "first-variant".to_string(),
                            rollout_percentage: 50.0,
                        },
                        MultivariateFlagVariant {
                            name: Some("Second Variant".to_string()),
                            key: "second-variant".to_string(),
                            rollout_percentage: 25.0,
                        },
                        MultivariateFlagVariant {
                            name: Some("Third Variant".to_string()),
                            key: "third-variant".to_string(),
                            rollout_percentage: 25.0,
                        },
                    ],
                }),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: None,
        };

        // Test user "11" - should get first-variant
        let router = context.create_postgres_router();
        let matcher = FeatureFlagMatcher::new(
            "11".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );
        let result = matcher.get_match(&flag, None, None, &None).unwrap();
        assert_eq!(
            result,
            FeatureFlagMatch {
                matches: true,
                variant: Some("first-variant".to_string()),
                reason: FeatureFlagMatchReason::ConditionMatch,
                condition_index: Some(0),
                payload: None,
            }
        );

        // Test user "example_id" - should get second-variant
        let router = context.create_postgres_router();
        let matcher = FeatureFlagMatcher::new(
            "example_id".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );
        let result = matcher.get_match(&flag, None, None, &None).unwrap();
        assert_eq!(
            result,
            FeatureFlagMatch {
                matches: true,
                variant: Some("second-variant".to_string()),
                reason: FeatureFlagMatchReason::ConditionMatch,
                condition_index: Some(0),
                payload: None,
            }
        );

        // Test user "3" - should get third-variant
        let router = context.create_postgres_router();
        let matcher = FeatureFlagMatcher::new(
            "3".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );
        let result = matcher.get_match(&flag, None, None, &None).unwrap();
        assert_eq!(
            result,
            FeatureFlagMatch {
                matches: true,
                variant: Some("third-variant".to_string()),
                reason: FeatureFlagMatchReason::ConditionMatch,
                condition_index: Some(0),
                payload: None,
            }
        );
    }

    #[tokio::test]
    async fn test_static_cohort_evaluation_skips_dependency_graph() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // Insert a static cohort
        let cohort = context
            .insert_cohort(
                team.id,
                Some("Static Cohort".to_string()),
                json!({}), // Static cohorts don't have property filters
                true,      // is_static = true
            )
            .await
            .unwrap();

        // Insert a person
        let distinct_id = "static_user".to_string();
        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "static@user.com"})),
            )
            .await
            .unwrap();

        // Get person ID and add to cohort
        let person_id = context
            .get_person_id_by_distinct_id(team.id, &distinct_id)
            .await
            .unwrap();
        context
            .add_person_to_cohort(cohort.id, person_id)
            .await
            .unwrap();

        // Define a flag that references the static cohort
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "id".to_string(),
                        value: Some(json!(cohort.id)),
                        operator: Some(OperatorType::In),
                        prop_type: PropertyType::Cohort,
                        group_type_index: None,
                        negation: Some(false),
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        // This should not throw DependencyNotFound because we skip dependency graph evaluation for static cohorts
        let result = matcher.get_match(&flag, None, None, &None);
        assert!(result.is_ok(), "Should not throw DependencyNotFound error");

        let match_result = result.unwrap();
        assert!(match_result.matches, "User should match the static cohort");
    }

    #[tokio::test]
    async fn test_no_person_id_with_overrides() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!("test@example.com")),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        let person_property_overrides =
            HashMap::from([("email".to_string(), json!("test@example.com"))]);

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "nonexistent_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher
            .evaluate_all_feature_flags(
                FeatureFlagList {
                    flags: vec![flag.clone()],
                    ..Default::default()
                },
                Some(person_property_overrides),
                None,
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();

        // Should succeed because we have overrides
        assert!(!result.errors_while_computing_flags);
        let flag_details = result.flags.get("test_flag").unwrap();
        assert!(flag_details.enabled);
    }

    #[tokio::test]
    async fn test_numeric_group_keys() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: Some(1),
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        // Set up group type mapping cache
        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.id);
        group_type_mapping_cache
            .init(context.persons_reader.clone())
            .await
            .unwrap();

        // Test with numeric group key
        let groups_numeric = HashMap::from([("organization".to_string(), json!(123))]);
        let router = context.create_postgres_router();
        let mut matcher_numeric = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups_numeric),
        );

        matcher_numeric
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result_numeric = matcher_numeric.get_match(&flag, None, None, &None).unwrap();

        // Test with string group key (same value)
        let groups_string = HashMap::from([("organization".to_string(), json!("123"))]);
        let router2 = context.create_postgres_router();
        let mut matcher_string = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router2,
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups_string),
        );

        matcher_string
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result_string = matcher_string.get_match(&flag, None, None, &None).unwrap();

        // Both should match and produce the same result
        assert!(result_numeric.matches, "Numeric group key should match");
        assert!(result_string.matches, "String group key should match");
        assert_eq!(
            result_numeric.matches, result_string.matches,
            "String and numeric group keys should produce the same match result"
        );
        assert_eq!(
            result_numeric.reason, result_string.reason,
            "String and numeric group keys should produce the same match reason"
        );

        // Test with a float value to ensure it works too
        let groups_float = HashMap::from([("organization".to_string(), json!(123.0))]);
        let router3 = context.create_postgres_router();
        let mut matcher_float = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router3,
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups_float),
        );

        matcher_float
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result_float = matcher_float.get_match(&flag, None, None, &None).unwrap();
        assert!(result_float.matches, "Float group key should match");

        // Test with invalid group key type (should use empty string and not match this specific case)
        let groups_bool = HashMap::from([("organization".to_string(), json!(true))]);
        let router4 = context.create_postgres_router();
        let mut matcher_bool = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None, // device_id
            team.id,
            router4,
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups_bool),
        );

        matcher_bool
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result_bool = matcher_bool.get_match(&flag, None, None, &None).unwrap();
        // Boolean group key should use empty string identifier, which returns hash 0.0, making flag evaluate to false
        assert!(
            !result_bool.matches,
            "Boolean group key should not match due to empty identifier"
        );
    }

    #[tokio::test]
    async fn test_complex_super_condition_matching() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            Some("complex_flag".to_string()),
            Some(FlagFilters {
                groups: vec![
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("@storytell.ai")),
                            operator: Some(OperatorType::Icontains),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                        ..Default::default()
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!([
                                "simone.demarchi@outlook.com",
                                "djokovic.dav@gmail.com",
                                "dario.passarello@gmail.com",
                                "matt.amick@purplewave.com"
                            ])),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                        ..Default::default()
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("@posthog.com")),
                            operator: Some(OperatorType::Icontains),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                        ..Default::default()
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "$feature_enrollment/my-flag".to_string(),
                        value: Some(json!(["true"])),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }]),

                holdout: None,
            }),
            None,
            None,
            None,
        );

        // Test case 1: User with super condition property set to true
        context
            .insert_person(
                team.id,
                "super_user".to_string(),
                Some(json!({
                    "email": "random@example.com",
                    "$feature_enrollment/my-flag": true
                })),
            )
            .await
            .unwrap();

        // Test case 2: User with matching email but no super condition
        context
            .insert_person(
                team.id,
                "posthog_user".to_string(),
                Some(json!({
                    "email": "test@posthog.com",
                    "$feature_enrollment/my-flag": false
                })),
            )
            .await
            .unwrap();

        // Test case 3: User with neither super condition nor matching email
        context
            .insert_person(
                team.id,
                "regular_user".to_string(),
                Some(json!({
                    "email": "regular@example.com"
                })),
            )
            .await
            .unwrap();

        // Test super condition user
        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "super_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None, &None).unwrap();
        assert!(result.matches, "Super condition user should match");
        assert_eq!(
            result.reason,
            FeatureFlagMatchReason::SuperConditionValue,
            "Match reason should be SuperConditionValue"
        );

        // Test PostHog user
        let router2 = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "posthog_user".to_string(),
            None, // device_id
            team.id,
            router2,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None, &None).unwrap();
        assert!(!result.matches, "PostHog user should not match");
        assert_eq!(
            result.reason,
            FeatureFlagMatchReason::SuperConditionValue,
            "Match reason should be SuperConditionValue"
        );

        // Test regular user
        let router3 = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "regular_user".to_string(),
            None, // device_id
            team.id,
            router3,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None, &None).unwrap();
        assert!(!result.matches, "Regular user should not match");
        assert_eq!(
            result.reason,
            FeatureFlagMatchReason::NoConditionMatch,
            "Match reason should be NoConditionMatch"
        );
    }
    #[tokio::test]
    async fn test_filters_with_distinct_id_exact() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));

        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let distinct_id = "user_distinct_id".to_string();
        context
            .insert_person(team.id, distinct_id.clone(), None)
            .await
            .expect("Failed to insert person");

        let flag: FeatureFlag = serde_json::from_value(json!(
            {
                "id": 1,
                "team_id": team.id,
                "name": "flag1",
                "key": "flag1",
                "active": true,
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "distinct_id",
                                    "type": "person",
                                    "value": [
                                         distinct_id.clone()
                                    ],
                                    "operator": "exact"
                                }
                            ],
                            "rollout_percentage": 100
                        }
                    ]
                }
            }
        ))
        .unwrap();

        // Matcher for a matching distinct_id
        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let match_result = matcher.get_match(&flag, None, None, &None).unwrap();
        assert!(match_result.matches);
        assert_eq!(match_result.variant, None);
    }

    fn build_device_bucketing_flag(team_id: TeamId) -> FeatureFlag {
        FeatureFlag {
            id: 1,
            team_id,
            name: Some("device flag".to_string()),
            key: "device-flag".to_string(),
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(50.0),
                    variant: None,
                    ..Default::default()
                }],
                ..FlagFilters::default()
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(true),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: Some("device_id".to_string()),
        }
    }

    #[tokio::test]
    async fn test_device_id_bucketing_uses_device_identifier() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let flag = build_device_bucketing_flag(team.id);

        // device-high hashes to ~0.27 (< 0.5), so rollout should match regardless of distinct_id
        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "distinct-alpha".to_string(),
            Some("device-high".to_string()),
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );
        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();
        let high_device_result = matcher.get_match(&flag, None, None, &None).unwrap();
        assert!(
            high_device_result.matches,
            "device-high hash should fall inside rollout"
        );

        // Changing distinct_id with the same device_id should not change the outcome
        let router = context.create_postgres_router();
        let mut matcher_same_device = FeatureFlagMatcher::new(
            "distinct-beta".to_string(),
            Some("device-high".to_string()),
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );
        matcher_same_device
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();
        let same_device_result = matcher_same_device
            .get_match(&flag, None, None, &None)
            .unwrap();
        assert_eq!(
            high_device_result.matches, same_device_result.matches,
            "device hashing should ignore distinct_id changes"
        );

        // device-low hashes to ~0.74 (> 0.5), so rollout should not match
        let router = context.create_postgres_router();
        let mut matcher_low = FeatureFlagMatcher::new(
            "distinct-gamma".to_string(),
            Some("device-low".to_string()),
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );
        matcher_low
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();
        let low_device_result = matcher_low.get_match(&flag, None, None, &None).unwrap();
        assert!(
            !low_device_result.matches,
            "device-low hash should fall outside rollout"
        );
    }

    #[tokio::test]
    async fn test_device_id_bucketing_returns_false_when_missing_device() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let flag = build_device_bucketing_flag(team.id);

        // Without a device_id, the flag should evaluate to false (no distinct_id fallback).
        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "distinct-foo".to_string(),
            None,
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );
        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();
        let match_without_device = matcher.get_match(&flag, None, None, &None).unwrap();
        assert!(
            !match_without_device.matches,
            "missing device_id should always evaluate to false for device_id bucketing"
        );

        // Empty string device_id should also evaluate to false.
        let router = context.create_postgres_router();
        let mut matcher_high = FeatureFlagMatcher::new(
            "distinct-high".to_string(),
            Some(String::new()),
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );
        matcher_high
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();
        let high_distinct_result = matcher_high.get_match(&flag, None, None, &None).unwrap();
        assert!(
            !high_distinct_result.matches,
            "empty device_id should evaluate to false for device_id bucketing"
        );
    }

    #[tokio::test]
    async fn test_distinct_id_bucketing_ignores_device_id() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let mut flag = build_device_bucketing_flag(team.id);
        flag.bucketing_identifier = Some("distinct_id".to_string());

        // distinct-high hashes to > 50%, so rollout should be false even though device-high would match.
        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "distinct-high".to_string(),
            Some("device-high".to_string()),
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );
        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();
        let high_distinct_result = matcher.get_match(&flag, None, None, &None).unwrap();
        assert!(
            !high_distinct_result.matches,
            "distinct-id bucketing should ignore device_id input"
        );

        // distinct-foo hashes to < 50%, so rollout should be true regardless of device_id.
        let router = context.create_postgres_router();
        let mut matcher_low = FeatureFlagMatcher::new(
            "distinct-foo".to_string(),
            Some("device-low".to_string()),
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );
        matcher_low
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();
        let low_distinct_result = matcher_low.get_match(&flag, None, None, &None).unwrap();
        assert!(
            low_distinct_result.matches,
            "distinct-id bucketing should follow the distinct hash even when device_id exists"
        );
    }

    #[tokio::test]
    async fn test_partial_property_overrides_fallback_behavior() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let distinct_id = "test_user".to_string();

        // Insert person with specific properties in DB that would match condition 1
        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({
                    "app_version": "1.3.6",
                    "focus": "all-of-the-above",
                    "os": "iOS",
                    "email": "test@example.com"
                })),
            )
            .await
            .expect("Failed to insert person");

        // Create a flag with two conditions similar to the user's example
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![
                    // Condition 1: Requires app_version, focus, os
                    FlagPropertyGroup {
                        properties: Some(vec![
                            PropertyFilter {
                                key: "app_version".to_string(),
                                value: Some(json!("1\\.[23456789]\\.\\d{1,2}")),
                                operator: Some(OperatorType::Regex),
                                prop_type: PropertyType::Person,
                                group_type_index: None,
                                negation: None,
                            },
                            PropertyFilter {
                                key: "focus".to_string(),
                                value: Some(json!(["become-more-active", "all-of-the-above"])),
                                operator: Some(OperatorType::Exact),
                                prop_type: PropertyType::Person,
                                group_type_index: None,
                                negation: None,
                            },
                            PropertyFilter {
                                key: "os".to_string(),
                                value: Some(json!(["iOS"])),
                                operator: Some(OperatorType::Exact),
                                prop_type: PropertyType::Person,
                                group_type_index: None,
                                negation: None,
                            },
                        ]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                        ..Default::default()
                    },
                    // Condition 2: Requires only email (100% rollout)
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!(["flag-test@example.com"])),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                        ..Default::default()
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        // Test case 1: Partial overrides - missing 'focus' property
        // This should fall back to DB for condition 1, but condition 2 should use overrides and not match
        let partial_overrides = HashMap::from([
            ("os".to_string(), json!("iOS")),
            ("app_version".to_string(), json!("1.3.6")),
            ("email".to_string(), json!("override-test@example.com")), // Different email, won't match condition 2
        ]);

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
            ..Default::default()
        };
        reset_fetch_calls_count();

        let result = matcher
            .evaluate_all_feature_flags(
                flags.clone(),
                Some(partial_overrides),
                None,
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();

        let fetch_calls = get_fetch_calls_count();
        assert_eq!(
            fetch_calls,
            1,
            "Expected fetch_and_locally_cache_all_relevant_properties to be called exactly 1 time, but it was called {fetch_calls} times",
        );
        assert!(!result.errors_while_computing_flags);
        // The flag should evaluate using DB properties for condition 1 (which has focus="all-of-the-above")
        // and overrides for condition 2 (which won't match the email).
        let flag_result = result.flags.get(&flag.key).unwrap();
        assert!(flag_result.enabled);

        // Test case 2: Complete overrides for condition 2
        // This should use overrides and match condition 2
        let complete_overrides_match = HashMap::from([
            ("email".to_string(), json!("flag-test@example.com")), // Matches condition 2
        ]);

        let router2 = context.create_postgres_router();
        let mut matcher2 = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router2,
            cohort_cache.clone(),
            None,
            None,
        );

        let result2 = matcher2
            .evaluate_all_feature_flags(
                flags.clone(),
                Some(complete_overrides_match),
                None,
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();

        assert!(!result2.errors_while_computing_flags);
        let flag_result2 = result2.flags.get(&flag.key).unwrap();

        // Should match condition 2 since email matches and rollout is 100%
        assert!(flag_result2.enabled);

        // Test case 3: Complete overrides for condition 2 with non-matching value
        // This should use overrides and not match condition 2
        let complete_overrides_no_match = HashMap::from([
            ("email".to_string(), json!("wrong@email.com")), // Doesn't match either email condition
        ]);

        let router3 = context.create_postgres_router();
        let mut matcher3 = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router3,
            cohort_cache.clone(),
            None,
            None,
        );

        let result3 = matcher3
            .evaluate_all_feature_flags(
                flags.clone(),
                Some(complete_overrides_no_match),
                None,
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();

        assert!(!result3.errors_while_computing_flags);
        let flag_result3 = result3.flags.get(&flag.key).unwrap();
        assert!(flag_result3.enabled); // Should be true because condition 1 matches (email override doesn't affect condition 1 properties)

        // Should not match condition 2 since email doesn't match, but condition 1 still matches
        // because it only depends on app_version, focus, and os (which come from DB and still match)

        // Test case 4: Complete overrides with all properties for condition 1
        let complete_overrides_condition1 = HashMap::from([
            ("app_version".to_string(), json!("1.3.6")),
            ("focus".to_string(), json!("all-of-the-above")), // Now includes focus
            ("os".to_string(), json!("iOS")),
        ]);

        let router4 = context.create_postgres_router();
        let mut matcher4 = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router4,
            cohort_cache.clone(),
            None,
            None,
        );

        let result4 = matcher4
            .evaluate_all_feature_flags(
                flags,
                Some(complete_overrides_condition1),
                None,
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();

        assert!(!result4.errors_while_computing_flags);
        let flag_result4 = result4.flags.get(&flag.key).unwrap();
        assert!(flag_result4.enabled);
    }

    #[tokio::test]
    async fn test_partial_group_property_overrides_fallback_behavior() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        let distinct_id = "test_user".to_string();

        // Insert person (required for group flag evaluation)
        context
            .insert_person(team.id, distinct_id.clone(), None)
            .await
            .expect("Failed to insert person");

        // Create a group with specific properties in DB that would match condition 1
        context
            .create_group(
                team.id,
                "organization",
                "test_org_123",
                json!({
                    "plan": "enterprise",
                    "region": "us-east-1",
                    "feature_access": "full",
                    "billing_email": "billing@testorg.com"
                }),
            )
            .await
            .expect("Failed to create group");

        // Create a group flag with two conditions similar to the person property test
        let flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![
                    // Condition 1: Requires plan, region, feature_access (group properties)
                    FlagPropertyGroup {
                        properties: Some(vec![
                            PropertyFilter {
                                key: "plan".to_string(),
                                value: Some(json!(["enterprise", "pro"])),
                                operator: Some(OperatorType::Exact),
                                prop_type: PropertyType::Group,
                                group_type_index: Some(1), // organization type
                                negation: None,
                            },
                            PropertyFilter {
                                key: "region".to_string(),
                                value: Some(json!("us-.*")),
                                operator: Some(OperatorType::Regex),
                                prop_type: PropertyType::Group,
                                group_type_index: Some(1),
                                negation: None,
                            },
                            PropertyFilter {
                                key: "feature_access".to_string(),
                                value: Some(json!(["full", "premium"])),
                                operator: Some(OperatorType::Exact),
                                prop_type: PropertyType::Group,
                                group_type_index: Some(1),
                                negation: None,
                            },
                        ]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                        ..Default::default()
                    },
                    // Condition 2: Requires only billing_email (100% rollout)
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "billing_email".to_string(),
                            value: Some(json!(["special-billing@testorg.com"])),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Group,
                            group_type_index: Some(1),
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                        ..Default::default()
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: Some(1), // This is a group-based flag
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        // Set up group type mappings
        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.id);
        group_type_mapping_cache
            .init(context.persons_reader.clone())
            .await
            .unwrap();

        let group_types_to_indexes = [("organization".to_string(), 1)].into_iter().collect();
        let indexes_to_types = [(1, "organization".to_string())].into_iter().collect();
        group_type_mapping_cache.set_test_mappings(group_types_to_indexes, indexes_to_types);

        let groups = HashMap::from([("organization".to_string(), json!("test_org_123"))]);

        // Test case 1: Partial group overrides - missing 'feature_access' property
        // This should fall back to DB for condition 1, but condition 2 should use overrides and not match
        let partial_group_overrides = HashMap::from([(
            "organization".to_string(),
            HashMap::from([
                ("plan".to_string(), json!("enterprise")),
                ("region".to_string(), json!("us-east-1")),
                (
                    "billing_email".to_string(),
                    json!("override-billing@testorg.com"),
                ), // Different email, won't match condition 2
                   // Missing 'feature_access' - should fall back to DB
            ]),
        )]);

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups.clone()),
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
            ..Default::default()
        };

        let result = matcher
            .evaluate_all_feature_flags(
                flags.clone(),
                None,
                Some(partial_group_overrides),
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();

        assert!(!result.errors_while_computing_flags);
        // The flag should evaluate using DB properties for condition 1 (which has feature_access="full")
        // and overrides for condition 2 (which won't match the billing_email).
        let flag_result = result.flags.get(&flag.key).unwrap();
        assert!(flag_result.enabled);

        // Test case 2: Complete group overrides for condition 2
        // This should use overrides and match condition 2
        let complete_group_overrides_match = HashMap::from([(
            "organization".to_string(),
            HashMap::from([
                (
                    "billing_email".to_string(),
                    json!("special-billing@testorg.com"),
                ), // Matches condition 2
            ]),
        )]);

        let router2 = context.create_postgres_router();
        let mut matcher2 = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router2,
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups.clone()),
        );

        let result2 = matcher2
            .evaluate_all_feature_flags(
                flags.clone(),
                None,
                Some(complete_group_overrides_match),
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();

        assert!(!result2.errors_while_computing_flags);
        let flag_result2 = result2.flags.get(&flag.key).unwrap();

        // Should match condition 2 since billing_email matches and rollout is 100%
        assert!(flag_result2.enabled);

        // Test case 3: Complete group overrides for condition 2 with non-matching value
        // This should use overrides and not match condition 2
        let complete_group_overrides_no_match = HashMap::from([(
            "organization".to_string(),
            HashMap::from([
                (
                    "billing_email".to_string(),
                    json!("wrong-billing@testorg.com"),
                ), // Doesn't match condition 2
            ]),
        )]);

        let router3 = context.create_postgres_router();
        let mut matcher3 = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router3,
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups.clone()),
        );

        let result3 = matcher3
            .evaluate_all_feature_flags(
                flags.clone(),
                None,
                Some(complete_group_overrides_no_match),
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();

        assert!(!result3.errors_while_computing_flags);
        let flag_result3 = result3.flags.get(&flag.key).unwrap();
        assert!(flag_result3.enabled); // Should be true because condition 1 matches (billing_email override doesn't affect condition 1 properties)

        // Test case 4: Complete group overrides with all properties for condition 1
        let complete_group_overrides_condition1 = HashMap::from([(
            "organization".to_string(),
            HashMap::from([
                ("plan".to_string(), json!("enterprise")),
                ("region".to_string(), json!("us-east-1")),
                ("feature_access".to_string(), json!("full")), // Now includes feature_access
            ]),
        )]);

        let router4 = context.create_postgres_router();
        let mut matcher4 = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router4,
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups.clone()),
        );

        let result4 = matcher4
            .evaluate_all_feature_flags(
                flags.clone(),
                None,
                Some(complete_group_overrides_condition1),
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();

        assert!(!result4.errors_while_computing_flags);
        let flag_result4 = result4.flags.get(&flag.key).unwrap();
        assert!(flag_result4.enabled);

        // Test case 5: Mixed overrides - some properties sufficient for fast path, others require DB merge
        let mixed_group_overrides = HashMap::from([(
            "organization".to_string(),
            HashMap::from([
                ("plan".to_string(), json!("pro")), // Different plan but still matches condition 1
                ("region".to_string(), json!("us-west-2")), // Different region but still matches regex
                // Missing feature_access - will need DB merge for condition 1
                (
                    "billing_email".to_string(),
                    json!("special-billing@testorg.com"),
                ), // Matches condition 2 exactly
            ]),
        )]);

        let router5 = context.create_postgres_router();
        let mut matcher5 = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None, // device_id
            team.id,
            router5,
            cohort_cache.clone(),
            None,
            Some(groups),
        );

        let result5 = matcher5
            .evaluate_all_feature_flags(
                flags,
                None,
                Some(mixed_group_overrides),
                None,
                Uuid::new_v4(),
                None,
                false,
            )
            .await
            .unwrap();

        assert!(!result5.errors_while_computing_flags);
        let flag_result5 = result5.flags.get(&flag.key).unwrap();
        // Should match because:
        // - Condition 1: plan=pro (matches), region=us-west-2 (matches regex), feature_access=full (from DB merge)
        // - Condition 2: billing_email matches exactly
        assert!(flag_result5.enabled);
    }

    #[tokio::test]
    async fn test_condition_evaluation_order_with_variant_overrides() {
        // Unlike decide, we don't sort conditions with variant overrides to the top.
        // This test ensures that the order is maintained regardless of the presence of a variant override.
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));

        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Create a flag with:
        // 1. First condition: specific user match (no variant override)
        // 2. Second condition: catch-all with variant="test"
        let flag = FeatureFlag {
            id: 1,
            team_id: team.id,
            name: Some("Test Order Flag".to_string()),
            key: "test_order_flag".to_string(),
            filters: FlagFilters {
                groups: vec![
                    FlagPropertyGroup {
                        variant: None, // No variant override
                        properties: Some(vec![PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!("specific@example.com")),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        ..Default::default()
                    },
                    FlagPropertyGroup {
                        variant: Some("test".to_string()), // Has variant override
                        properties: Some(vec![]),          // Catch-all
                        rollout_percentage: Some(100.0),
                        ..Default::default()
                    },
                ],
                multivariate: Some(MultivariateFlagOptions {
                    variants: vec![
                        MultivariateFlagVariant {
                            key: "control".to_string(),
                            name: Some("Control".to_string()),
                            rollout_percentage: 100.0,
                        },
                        MultivariateFlagVariant {
                            key: "test".to_string(),
                            name: Some("Test".to_string()),
                            rollout_percentage: 0.0,
                        },
                    ],
                }),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: None,
        };

        let router = context.create_postgres_router();

        // Test 1: User with email "specific@example.com" should match first condition
        let matcher = FeatureFlagMatcher::new(
            "specific_user".to_string(),
            None, // device_id
            team.id,
            router.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        // Pass email as a property override to avoid database lookup
        let mut user_properties = HashMap::new();
        user_properties.insert("email".to_string(), json!("specific@example.com"));

        let result = matcher
            .get_match(&flag, Some(&user_properties), None, &None)
            .unwrap();
        assert!(result.matches, "Flag should match for specific user");
        assert_eq!(
            result.variant,
            Some("control".to_string()),
            "Specific user should get 'control' from multivariate rollout (100% control), not 'test' from catch-all"
        );
        assert_eq!(
            result.condition_index,
            Some(0),
            "Should match first condition (index 0)"
        );

        // Test 2: Different user should match second condition (catch-all)
        let matcher2 = FeatureFlagMatcher::new(
            "other_user".to_string(),
            None, // device_id
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        let mut other_properties = HashMap::new();
        other_properties.insert("email".to_string(), json!("other@example.com"));

        let result2 = matcher2
            .get_match(&flag, Some(&other_properties), None, &None)
            .unwrap();
        assert!(result2.matches, "Flag should match for other user");
        assert_eq!(
            result2.variant,
            Some("test".to_string()),
            "Other user should get 'test' from catch-all variant override"
        );
        assert_eq!(
            result2.condition_index,
            Some(1),
            "Should match second condition (index 1)"
        );
    }

    #[tokio::test]
    async fn test_hash_key_override_error_marks_continuity_flags_as_errors() {
        let context = TestContext::new(None).await;
        let router = context.create_postgres_router();
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.persons_reader.clone(),
            None,
            None,
        ));

        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let distinct_id = "user_distinct_id".to_string();
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id,
            None, // device_id
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );

        // Create flags: one with experience continuity enabled, one without
        let flag_with_continuity = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Test Flag Continuity".to_string()),
            Some("test-flag-continuity".to_string()),
            None,
            Some(false),
            Some(true),
            Some(true), // ensure_experience_continuity
        );

        let flag_without_continuity = create_test_flag(
            Some(2),
            Some(team.id),
            Some("Test Flag Normal".to_string()),
            Some("test-flag-normal".to_string()),
            None,
            Some(false),
            Some(true),
            Some(false), // ensure_experience_continuity
        );

        let flags = FeatureFlagList {
            flags: vec![flag_with_continuity, flag_without_continuity],
            ..Default::default()
        };

        // Build dependency graph for the flags
        let precomputed = PrecomputedDependencyGraph::build(&flags, team.id, None)
            .expect("Should build dependency graph");

        // Test the scenario where hash key override reading fails
        // This simulates the case where we have experience continuity flags but hash override reads fail
        let overrides = crate::flags::flag_matching::FlagEvaluationOverrides {
            person_property_overrides: None,
            group_property_overrides: None,
            hash_key_overrides: None, // hash_key_overrides (None simulates read failure)
            hash_key_override_error: true, // hash_key_override_error (simulates the error occurred)
            request_hash_key_override: None,
        };

        let response = matcher
            .evaluate_flags_with_overrides(
                overrides,
                Uuid::new_v4(),
                precomputed.evaluation_stages,
                precomputed.flags_with_missing_deps,
            )
            .await
            .unwrap();

        // Should have errors_while_computing_flags set to true
        assert!(
            response.errors_while_computing_flags,
            "Should have errors_while_computing_flags=true when hash override reads fail"
        );

        // The flag with experience continuity should have an error response
        let continuity_flag_response = response
            .flags
            .get("test-flag-continuity")
            .expect("Continuity flag should be present");
        assert!(
            !continuity_flag_response.enabled,
            "Flag with continuity should be disabled due to error"
        );
        assert_eq!(
            continuity_flag_response.reason.code, "hash_key_override_error",
            "Should have hash_key_override_error reason"
        );

        // The flag without experience continuity should NOT have an error (should be evaluated normally)
        let normal_flag_response = response.flags.get("test-flag-normal");
        // The normal flag might be evaluated normally, so we just check it's not affected by the hash override error
        if let Some(normal_response) = normal_flag_response {
            assert_ne!(
                normal_response.reason.code, "hash_key_override_error",
                "Normal flag should not have hash override error"
            );
        }
    }

    #[tokio::test]
    async fn test_filtered_out_flag_with_experience_continuity_excluded_from_hash_key_error_response(
    ) {
        let context = TestContext::new(None).await;
        let router = context.create_postgres_router();
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));

        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let distinct_id = "user_distinct_id".to_string();
        let mut matcher =
            FeatureFlagMatcher::new(distinct_id, None, team.id, router, cohort_cache, None, None);

        // A filtered-out flag with experience continuity should not trigger
        // hash-key-override error handling or appear in the response.
        let filtered_continuity_flag = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Filtered Continuity".to_string()),
            Some("filtered-continuity".to_string()),
            None,
            Some(false),
            Some(true),
            Some(true), // ensure_experience_continuity
        );

        let active_normal_flag = create_test_flag(
            Some(2),
            Some(team.id),
            Some("Active Normal".to_string()),
            Some("active-normal".to_string()),
            None,
            Some(false),
            Some(true),
            Some(false),
        );

        // Flag 1 is filtered out by runtime/tag filtering
        let filtered_out = std::collections::HashSet::from([1]);

        let flags = FeatureFlagList {
            flags: vec![filtered_continuity_flag, active_normal_flag],
            filtered_out_flag_ids: filtered_out.clone(),
            evaluation_metadata: None,
        };

        let precomputed = PrecomputedDependencyGraph::build(&flags, team.id, None)
            .expect("Should build dependency graph");

        // Simulate a hash-key-override read failure
        let overrides = crate::flags::flag_matching::FlagEvaluationOverrides {
            person_property_overrides: None,
            group_property_overrides: None,
            hash_key_overrides: None,
            hash_key_override_error: true,
            request_hash_key_override: None,
        };

        matcher.filtered_out_flag_ids = filtered_out;

        let response = matcher
            .evaluate_flags_with_overrides(
                overrides,
                Uuid::new_v4(),
                precomputed.evaluation_stages,
                precomputed.flags_with_missing_deps,
            )
            .await
            .unwrap();

        // The filtered-out continuity flag must not appear with a hash_key_override_error
        assert!(
            !response.flags.contains_key("filtered-continuity"),
            "Filtered-out flag should not appear in the response at all"
        );

        // The active non-continuity flag should be evaluated normally
        let active_response = response
            .flags
            .get("active-normal")
            .expect("Active flag should be present");
        assert_ne!(
            active_response.reason.code, "hash_key_override_error",
            "Active flag without continuity should not have hash override error"
        );
    }

    #[tokio::test]
    async fn test_flag_depending_on_disabled_flag_evaluates_to_false() {
        use crate::utils::test_utils::create_test_flag_that_depends_on_flag;

        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));

        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        // Create a disabled base flag
        let base_flag: FeatureFlag = serde_json::from_value(json!(
            {
                "id": 1,
                "team_id": team.id,
                "name": "base_flag",
                "key": "base_flag",
                "active": false,
                "filters": {
                    "groups": [
                        {
                            "properties": [],
                            "rollout_percentage": 100
                        }
                    ]
                }
            }
        ))
        .unwrap();

        // Create a flag that depends on the disabled flag
        let dependent_flag = create_test_flag_that_depends_on_flag(
            2,
            team.id,
            "dependent_flag",
            1, // depends on flag id 1
            FlagValue::Boolean(true),
        );

        let flags = FeatureFlagList {
            flags: vec![base_flag, dependent_flag],
            ..Default::default()
        };

        // Build dependency graph for the flags
        let precomputed = PrecomputedDependencyGraph::build(&flags, team.id, None)
            .expect("Should build dependency graph");

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None,
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );

        // The base flag is user-disabled (active=false in DB), so it's in the filter set
        matcher.filtered_out_flag_ids = std::collections::HashSet::from([1]);

        let result = matcher
            .evaluate_flags_with_overrides(
                Default::default(),
                Uuid::new_v4(),
                precomputed.evaluation_stages,
                precomputed.flags_with_missing_deps,
            )
            .await
            .unwrap();

        // Disabled base flag should NOT be in the response (filtered out)
        assert!(
            !result.flags.contains_key("base_flag"),
            "Disabled flags should not be included in the response"
        );

        // Dependent flag should evaluate to false because its dependency is disabled
        // This confirms that dependency resolution works even though the disabled flag
        // is not in the response (it's evaluated internally)
        let dependent_result = result.flags.get("dependent_flag").unwrap();
        assert!(
            !dependent_result.enabled,
            "Flag depending on disabled flag should not be enabled"
        );
        assert_ne!(
            dependent_result.reason.code, "flag_disabled",
            "Dependent flag should not have flag_disabled reason (it's not disabled, its dependency is)"
        );
    }

    #[tokio::test]
    async fn test_filtered_out_flag_satisfies_evaluates_to_false_dependency() {
        use crate::utils::test_utils::create_test_flag_that_depends_on_flag;

        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));

        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        // Flag A: active in DB, but will be filtered out by runtime/tags
        let flag_a: FeatureFlag = serde_json::from_value(json!(
            {
                "id": 1,
                "team_id": team.id,
                "name": "flag_a",
                "key": "flag_a",
                "active": true,
                "filters": {
                    "groups": [
                        {
                            "properties": [],
                            "rollout_percentage": 100
                        }
                    ]
                }
            }
        ))
        .unwrap();

        // Flag B depends on flag A with flag_evaluates_to=false.
        // Since A is filtered out (conceptually false), B's dependency should be satisfied.
        let flag_b = create_test_flag_that_depends_on_flag(
            2,
            team.id,
            "flag_b",
            1, // depends on flag id 1
            FlagValue::Boolean(false),
        );

        // Flag A is filtered out by runtime/tag filtering
        let filtered_out = std::collections::HashSet::from([1]);

        let flags = FeatureFlagList {
            flags: vec![flag_a, flag_b],
            filtered_out_flag_ids: filtered_out.clone(),
            evaluation_metadata: None,
        };

        let precomputed = PrecomputedDependencyGraph::build(&flags, team.id, None)
            .expect("Should build dependency graph");

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None,
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );
        matcher.filtered_out_flag_ids = filtered_out;

        let result = matcher
            .evaluate_flags_with_overrides(
                Default::default(),
                Uuid::new_v4(),
                precomputed.evaluation_stages,
                precomputed.flags_with_missing_deps,
            )
            .await
            .unwrap();

        // Filtered-out flag A should not appear in the response
        assert!(
            !result.flags.contains_key("flag_a"),
            "Filtered-out flag should not appear in the response"
        );

        // Flag B should be enabled because its dependency (A evaluates to false) is satisfied
        let flag_b_result = result
            .flags
            .get("flag_b")
            .expect("Flag B should be in the response");
        assert!(
            flag_b_result.enabled,
            "Flag B should be enabled because filtered-out flag A is treated as false"
        );
    }

    #[tokio::test]
    async fn test_filtered_out_flag_fails_evaluates_to_true_dependency() {
        use crate::utils::test_utils::create_test_flag_that_depends_on_flag;

        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));

        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        // Flag A: active in DB, but will be filtered out by runtime/tags
        let flag_a: FeatureFlag = serde_json::from_value(json!(
            {
                "id": 1,
                "team_id": team.id,
                "name": "flag_a",
                "key": "flag_a",
                "active": true,
                "filters": {
                    "groups": [
                        {
                            "properties": [],
                            "rollout_percentage": 100
                        }
                    ]
                }
            }
        ))
        .unwrap();

        // Flag B depends on flag A with flag_evaluates_to=true.
        // Since A is filtered out (pre-seeded as false), B's dependency should NOT be satisfied.
        let flag_b = create_test_flag_that_depends_on_flag(
            2,
            team.id,
            "flag_b",
            1, // depends on flag id 1
            FlagValue::Boolean(true),
        );

        // Flag A is filtered out by runtime/tag filtering
        let filtered_out = std::collections::HashSet::from([1]);

        let flags = FeatureFlagList {
            flags: vec![flag_a, flag_b],
            filtered_out_flag_ids: filtered_out.clone(),
            evaluation_metadata: None,
        };

        let precomputed = PrecomputedDependencyGraph::build(&flags, team.id, None)
            .expect("Should build dependency graph");

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None,
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );
        matcher.filtered_out_flag_ids = filtered_out;

        let result = matcher
            .evaluate_flags_with_overrides(
                Default::default(),
                Uuid::new_v4(),
                precomputed.evaluation_stages,
                precomputed.flags_with_missing_deps,
            )
            .await
            .unwrap();

        // Filtered-out flag A should not appear in the response
        assert!(
            !result.flags.contains_key("flag_a"),
            "Filtered-out flag should not appear in the response"
        );

        // Flag B should be disabled because its dependency (A evaluates to true) is NOT satisfied
        let flag_b_result = result
            .flags
            .get("flag_b")
            .expect("Flag B should be in the response");
        assert!(
            !flag_b_result.enabled,
            "Flag B should be disabled because filtered-out flag A is treated as false, not true"
        );
    }

    #[tokio::test]
    async fn test_disabled_flags_not_dependencies_excluded_from_response() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));

        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        // Create a disabled standalone flag (not a dependency of any active flag)
        let disabled_standalone: FeatureFlag = serde_json::from_value(json!(
            {
                "id": 1,
                "team_id": team.id,
                "name": "disabled_standalone",
                "key": "disabled_standalone",
                "active": false,
                "filters": {
                    "groups": [
                        {
                            "properties": [],
                            "rollout_percentage": 100
                        }
                    ]
                }
            }
        ))
        .unwrap();

        // Create an active flag that doesn't depend on anything
        let active_flag: FeatureFlag = serde_json::from_value(json!(
            {
                "id": 2,
                "team_id": team.id,
                "name": "active_flag",
                "key": "active_flag",
                "active": true,
                "filters": {
                    "groups": [
                        {
                            "properties": [],
                            "rollout_percentage": 100
                        }
                    ]
                }
            }
        ))
        .unwrap();

        let flags = FeatureFlagList {
            flags: vec![disabled_standalone, active_flag],
            ..Default::default()
        };

        let precomputed = PrecomputedDependencyGraph::build(&flags, team.id, None)
            .expect("Should build dependency graph");

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None,
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );

        // The standalone flag is user-disabled (active=false in DB), so it's in the filter set
        matcher.filtered_out_flag_ids = std::collections::HashSet::from([1]);

        let result = matcher
            .evaluate_flags_with_overrides(
                Default::default(),
                Uuid::new_v4(),
                precomputed.evaluation_stages,
                precomputed.flags_with_missing_deps,
            )
            .await
            .unwrap();

        // Disabled standalone flag should NOT be in the response
        assert!(
            !result.flags.contains_key("disabled_standalone"),
            "Disabled standalone flags should be excluded from response"
        );

        // Active flag should be in the response
        let active_result = result.flags.get("active_flag").unwrap();
        assert!(active_result.enabled, "Active flag should be enabled");
    }

    #[tokio::test]
    async fn test_multi_level_dependency_with_filtered_out_intermediate() {
        use crate::utils::test_utils::create_test_flag_that_depends_on_flag;

        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));

        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        // Three flags: C depends on B, B depends on A, and B is filtered out.
        // A is active and evaluates to true. B is filtered out (pre-seeded as false).
        // C depends on B with evaluates_to=false, so C should be enabled.
        let flag_a: FeatureFlag = serde_json::from_value(json!({
            "id": 1,
            "team_id": team.id,
            "name": "flag_a",
            "key": "flag_a",
            "active": true,
            "filters": {
                "groups": [{"properties": [], "rollout_percentage": 100}]
            }
        }))
        .unwrap();

        let flag_b = create_test_flag_that_depends_on_flag(
            2,
            team.id,
            "flag_b",
            1, // depends on A
            FlagValue::Boolean(true),
        );

        let flag_c = create_test_flag_that_depends_on_flag(
            3,
            team.id,
            "flag_c",
            2,                         // depends on B
            FlagValue::Boolean(false), // expects B to be false
        );

        // B is filtered out by runtime filtering
        let filtered_out = std::collections::HashSet::from([2]);

        let flags = FeatureFlagList {
            flags: vec![flag_a, flag_b, flag_c],
            filtered_out_flag_ids: filtered_out.clone(),
            evaluation_metadata: None,
        };

        let precomputed = PrecomputedDependencyGraph::build(&flags, team.id, None)
            .expect("Should build dependency graph");

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None,
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );
        matcher.filtered_out_flag_ids = filtered_out;

        let result = matcher
            .evaluate_flags_with_overrides(
                Default::default(),
                Uuid::new_v4(),
                precomputed.evaluation_stages,
                precomputed.flags_with_missing_deps,
            )
            .await
            .unwrap();

        // A should be evaluated normally
        let flag_a_result = result.flags.get("flag_a").unwrap();
        assert!(flag_a_result.enabled, "Flag A should be enabled");

        // B is filtered out, should not appear
        assert!(
            !result.flags.contains_key("flag_b"),
            "Filtered-out flag B should not appear in the response"
        );

        // C depends on B (evaluates_to=false). B is pre-seeded as false, so C's dependency is satisfied.
        let flag_c_result = result.flags.get("flag_c").unwrap();
        assert!(
            flag_c_result.enabled,
            "Flag C should be enabled because filtered-out B is treated as false"
        );
    }

    // ======== Integration tests for experience continuity optimization ========

    #[tokio::test]
    async fn test_optimization_enabled_100_percent_rollout_evaluates_correctly() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let distinct_id = "optimization_user_1".to_string();

        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "opt_user@example.com"})),
            )
            .await
            .unwrap();

        // Create a flag with 100% rollout and experience continuity enabled
        // This flag should NOT need a hash key override lookup
        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            None,
            Some("opt_100_percent".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(true), // ensure_experience_continuity = true
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
            ..Default::default()
        };

        // Reset counter before the test
        reset_hash_key_override_lookup_count();

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None,
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            None,
            None,
            Some("anon_distinct_id".to_string()),
            Uuid::new_v4(),
            None,
            true, // optimization enabled
        )
        .await
        .unwrap();

        // Verify the optimization actually skipped the hash key override lookup
        let lookup_count = get_hash_key_override_lookup_count();
        assert_eq!(
            lookup_count, 0,
            "100% rollout flag should skip hash key override lookup, but got {lookup_count} lookups"
        );

        // Flag should evaluate correctly even with optimization enabled
        assert!(
            result.flags.get("opt_100_percent").unwrap().enabled,
            "100% rollout flag should be enabled with optimization"
        );
        assert!(
            !result.errors_while_computing_flags,
            "No errors should occur"
        );
    }

    #[tokio::test]
    async fn test_optimization_enabled_partial_rollout_evaluates_correctly() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let distinct_id = "optimization_user_2".to_string();

        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "opt_user2@example.com"})),
            )
            .await
            .unwrap();

        // Create a flag with 50% rollout and experience continuity enabled
        // This flag SHOULD need a hash key override lookup
        let flag = create_test_flag(
            Some(2),
            Some(team.id),
            None,
            Some("opt_partial_rollout".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(50.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(true), // ensure_experience_continuity = true
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
            ..Default::default()
        };

        // Reset counter before the test
        reset_hash_key_override_lookup_count();

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None,
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            None,
            None,
            Some("anon_distinct_id".to_string()),
            Uuid::new_v4(),
            None,
            true, // optimization enabled
        )
        .await
        .unwrap();

        // Verify the lookup DID happen for partial rollout (optimization doesn't skip it)
        let lookup_count = get_hash_key_override_lookup_count();
        assert_eq!(
            lookup_count, 1,
            "Partial rollout flag should perform hash key override lookup, but got {lookup_count} lookups"
        );

        // Flag should evaluate (result depends on hash)
        assert!(
            result.flags.contains_key("opt_partial_rollout"),
            "Partial rollout flag should be evaluated with optimization"
        );
        assert!(
            !result.errors_while_computing_flags,
            "No errors should occur"
        );
    }

    #[tokio::test]
    async fn test_optimization_enabled_multivariate_evaluates_correctly() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let distinct_id = "optimization_user_3".to_string();

        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "opt_user3@example.com"})),
            )
            .await
            .unwrap();

        // Create a multivariate flag with experience continuity
        // This flag SHOULD need a hash key override lookup
        let flag = create_test_flag(
            Some(3),
            Some(team.id),
            None,
            Some("opt_multivariate".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: Some(MultivariateFlagOptions {
                    variants: vec![
                        MultivariateFlagVariant {
                            key: "control".to_string(),
                            name: Some("Control".to_string()),
                            rollout_percentage: 50.0,
                        },
                        MultivariateFlagVariant {
                            key: "test".to_string(),
                            name: Some("Test".to_string()),
                            rollout_percentage: 50.0,
                        },
                    ],
                }),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(true), // ensure_experience_continuity = true
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
            ..Default::default()
        };

        // Reset counter before the test
        reset_hash_key_override_lookup_count();

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None,
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            None,
            None,
            Some("anon_distinct_id".to_string()),
            Uuid::new_v4(),
            None,
            true, // optimization enabled
        )
        .await
        .unwrap();

        // Verify the lookup DID happen for multivariate (optimization doesn't skip it)
        let lookup_count = get_hash_key_override_lookup_count();
        assert_eq!(
            lookup_count, 1,
            "Multivariate flag should perform hash key override lookup, but got {lookup_count} lookups"
        );

        // Flag should evaluate with a variant
        let flag_result = result.flags.get("opt_multivariate").unwrap();
        assert!(
            flag_result.enabled,
            "Multivariate flag should be enabled with optimization"
        );
        assert!(
            flag_result.variant.is_some(),
            "Multivariate flag should have a variant assigned"
        );
        assert!(
            !result.errors_while_computing_flags,
            "No errors should occur"
        );
    }

    #[tokio::test]
    async fn test_optimization_enabled_multivariate_with_100_percent_variant() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let distinct_id = "optimization_user_4".to_string();

        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "opt_user4@example.com"})),
            )
            .await
            .unwrap();

        // Create a multivariate flag where one variant is at 100%
        // This flag should NOT need a hash key override lookup (optimization applies)
        let flag = create_test_flag(
            Some(4),
            Some(team.id),
            None,
            Some("opt_multivariate_100".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: Some(MultivariateFlagOptions {
                    variants: vec![
                        MultivariateFlagVariant {
                            key: "control".to_string(),
                            name: Some("Control".to_string()),
                            rollout_percentage: 100.0, // 100% variant
                        },
                        MultivariateFlagVariant {
                            key: "test".to_string(),
                            name: Some("Test".to_string()),
                            rollout_percentage: 0.0,
                        },
                    ],
                }),
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(true), // ensure_experience_continuity = true
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
            ..Default::default()
        };

        // Reset counter before the test
        reset_hash_key_override_lookup_count();

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None,
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            None,
            None,
            Some("anon_distinct_id".to_string()),
            Uuid::new_v4(),
            None,
            true, // optimization enabled
        )
        .await
        .unwrap();

        // Verify the optimization skipped the lookup (100% variant = no hashing needed)
        let lookup_count = get_hash_key_override_lookup_count();
        assert_eq!(
            lookup_count, 0,
            "Multivariate flag with 100% variant should skip hash key override lookup, but got {lookup_count} lookups"
        );

        // Flag should evaluate with the 100% variant
        let flag_result = result.flags.get("opt_multivariate_100").unwrap();
        assert!(
            flag_result.enabled,
            "Flag with 100% variant should be enabled"
        );
        assert_eq!(
            flag_result.variant,
            Some("control".to_string()),
            "Should get the 100% variant"
        );
        assert!(
            !result.errors_while_computing_flags,
            "No errors should occur"
        );
    }

    #[tokio::test]
    async fn test_optimization_disabled_legacy_behavior() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let distinct_id = "legacy_user".to_string();

        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "legacy@example.com"})),
            )
            .await
            .unwrap();

        // Create a flag with 100% rollout and experience continuity
        let flag = create_test_flag(
            Some(5),
            Some(team.id),
            None,
            Some("legacy_flag".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(true), // ensure_experience_continuity = true
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
            ..Default::default()
        };

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None,
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            None,
            None,
            Some("anon_distinct_id".to_string()),
            Uuid::new_v4(),
            None,
            false, // optimization disabled (legacy behavior)
        )
        .await
        .unwrap();

        // Flag should still evaluate correctly in legacy mode
        assert!(
            result.flags.get("legacy_flag").unwrap().enabled,
            "Flag should be enabled in legacy mode"
        );
        assert!(
            !result.errors_while_computing_flags,
            "No errors should occur"
        );
    }

    #[tokio::test]
    async fn test_optimization_mixed_flags() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let distinct_id = "mixed_user".to_string();

        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "mixed@example.com"})),
            )
            .await
            .unwrap();

        // Flag 1: 100% rollout with continuity (can be optimized)
        let flag_optimizable = create_test_flag(
            Some(1),
            Some(team.id),
            None,
            Some("flag_optimizable".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(true),
        );

        // Flag 2: 50% rollout with continuity (needs lookup)
        let flag_needs_lookup = create_test_flag(
            Some(2),
            Some(team.id),
            None,
            Some("flag_needs_lookup".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(50.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(true),
        );

        // Flag 3: 100% rollout without continuity (no lookup needed)
        let flag_no_continuity = create_test_flag(
            Some(3),
            Some(team.id),
            None,
            Some("flag_no_continuity".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(false),
        );

        let flags = FeatureFlagList {
            flags: vec![
                flag_optimizable.clone(),
                flag_needs_lookup.clone(),
                flag_no_continuity.clone(),
            ],
            ..Default::default()
        };

        // Reset counter before the test
        reset_hash_key_override_lookup_count();

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None,
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            None,
            None,
            Some("anon_distinct_id".to_string()),
            Uuid::new_v4(),
            None,
            true, // optimization enabled
        )
        .await
        .unwrap();

        // Verify the lookup DID happen because flag_needs_lookup requires it.
        // Even though flag_optimizable could be optimized, the presence of
        // flag_needs_lookup forces a lookup for all flags with experience continuity.
        let lookup_count = get_hash_key_override_lookup_count();
        assert_eq!(
            lookup_count, 1,
            "Mixed flags should perform lookup when at least one flag needs it, but got {lookup_count} lookups"
        );

        // All flags should be evaluated
        assert!(
            result.flags.contains_key("flag_optimizable"),
            "Optimizable flag should be evaluated"
        );
        assert!(
            result.flags.contains_key("flag_needs_lookup"),
            "Needs-lookup flag should be evaluated"
        );
        assert!(
            result.flags.contains_key("flag_no_continuity"),
            "No-continuity flag should be evaluated"
        );

        // 100% rollout flags should be enabled
        assert!(
            result.flags.get("flag_optimizable").unwrap().enabled,
            "100% rollout flag should be enabled"
        );
        assert!(
            result.flags.get("flag_no_continuity").unwrap().enabled,
            "100% rollout no-continuity flag should be enabled"
        );

        assert!(
            !result.errors_while_computing_flags,
            "No errors should occur"
        );
    }

    /// Tests that flag_keys filtering is applied before computing optimization stats.
    /// When only optimizable flags are requested via flag_keys, the lookup should be skipped
    /// even if other flags (not being evaluated) would require it.
    #[tokio::test]
    async fn test_optimization_respects_flag_keys_filter() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let distinct_id = "flag_keys_user".to_string();

        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "flag_keys@example.com"})),
            )
            .await
            .unwrap();

        // Flag 1: 100% rollout with continuity (can be optimized)
        let flag_optimizable = create_test_flag(
            Some(1),
            Some(team.id),
            None,
            Some("flag_optimizable".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(true),
        );

        // Flag 2: 50% rollout with continuity (needs lookup)
        let flag_needs_lookup = create_test_flag(
            Some(2),
            Some(team.id),
            None,
            Some("flag_needs_lookup".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(50.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(true),
        );

        let flags = FeatureFlagList {
            flags: vec![flag_optimizable.clone(), flag_needs_lookup.clone()],
            ..Default::default()
        };

        // Reset counter before the test
        reset_hash_key_override_lookup_count();

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None,
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            None,
            None,
            Some("anon_distinct_id".to_string()),
            Uuid::new_v4(),
            Some(vec!["flag_optimizable".to_string()]), // Only request the optimizable flag
            true,                                       // optimization enabled
        )
        .await
        .unwrap();

        // Verify the lookup was SKIPPED because we only requested flag_optimizable,
        // which is 100% rollout and doesn't need the hash key override lookup.
        // The flag_needs_lookup exists but wasn't requested, so it shouldn't trigger a lookup.
        let lookup_count = get_hash_key_override_lookup_count();
        assert_eq!(
            lookup_count, 0,
            "Lookup should be skipped when flag_keys filters to only optimizable flags, but got {lookup_count} lookups"
        );

        // Only the requested flag should be evaluated
        assert!(
            result.flags.contains_key("flag_optimizable"),
            "Optimizable flag should be evaluated"
        );
        assert!(
            !result.flags.contains_key("flag_needs_lookup"),
            "Needs-lookup flag should NOT be evaluated when not in flag_keys"
        );

        // The optimizable flag should be enabled (100% rollout)
        assert!(
            result.flags.get("flag_optimizable").unwrap().enabled,
            "100% rollout flag should be enabled"
        );

        assert!(
            !result.errors_while_computing_flags,
            "No errors should occur"
        );
    }

    /// Tests that hash key lookup is NOT skipped when a requested flag depends on a flag that needs it.
    /// This ensures the optimization correctly considers transitive dependencies.
    ///
    /// Scenario:
    /// - Flag B: 50% rollout + experience continuity (needs hash lookup)
    /// - Flag A: 100% rollout + experience continuity, depends on Flag B (doesn't need lookup itself)
    /// - User requests only Flag A via flag_keys
    /// - The lookup should happen because Flag B (a dependency) requires it
    #[tokio::test]
    async fn test_optimization_considers_dependencies_for_flag_keys() {
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let distinct_id = "dependency_user".to_string();

        context
            .insert_person(
                team.id,
                distinct_id.clone(),
                Some(json!({"email": "test@example.com"})),
            )
            .await
            .unwrap();

        // Flag B: 50% rollout with experience continuity (NEEDS hash lookup)
        // This is the dependency that requires the hash key override
        let flag_needs_lookup = create_test_flag(
            Some(1),
            Some(team.id),
            None,
            Some("flag_needs_lookup".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(50.0), // Partial rollout means we need consistent bucketing
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(true), // experience continuity enabled
        );

        // Flag A: Depends on Flag B, with 100% rollout and experience continuity.
        // This flag itself wouldn't need a hash lookup (100% rollout), but its dependency does.
        let flag_depends_on_b = create_test_flag(
            Some(2),
            Some(team.id),
            None,
            Some("flag_depends_on_b".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "1".to_string(), // depends on flag with id=1
                        value: Some(json!(true)),
                        operator: Some(OperatorType::FlagEvaluatesTo),
                        prop_type: PropertyType::Flag,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0), // 100% rollout - doesn't need lookup on its own
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            Some(true), // experience continuity enabled
        );

        let flags = FeatureFlagList {
            flags: vec![flag_needs_lookup.clone(), flag_depends_on_b.clone()],
            ..Default::default()
        };

        // Reset counter before the test
        reset_hash_key_override_lookup_count();

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            None,
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            None,
            None,
            Some("anon_distinct_id".to_string()),
            Uuid::new_v4(),
            Some(vec!["flag_depends_on_b".to_string()]), // Only request the dependent flag
            true,                                        // optimization enabled
        )
        .await
        .unwrap();

        // The lookup SHOULD happen because flag_needs_lookup (a dependency) requires it,
        // even though flag_depends_on_b itself wouldn't need it (100% rollout).
        // Before the fix, this would incorrectly be 0.
        let lookup_count = get_hash_key_override_lookup_count();
        assert_eq!(
            lookup_count, 1,
            "Hash key lookup should happen because dependency flag_needs_lookup requires it"
        );

        // The dependent flag should be evaluated
        assert!(
            result.flags.contains_key("flag_depends_on_b"),
            "Dependent flag should be evaluated"
        );

        // The dependency flag should also be in the result since it was evaluated as a dependency
        assert!(
            result.flags.contains_key("flag_needs_lookup"),
            "Dependency flag should also be evaluated"
        );

        assert!(
            !result.errors_while_computing_flags,
            "No errors should occur"
        );
    }

    #[tokio::test]
    async fn test_super_condition_matches_with_override_no_person_in_db() {
        // Test that super_condition can match using person_property_overrides
        // even when the person doesn't exist in the database.
        // This is a key scenario for early access feature enrollment.
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Early Access Flag".to_string()),
            Some("early_access_flag".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(0.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "$feature_enrollment/my-flag".to_string(),
                        value: Some(json!(["true"])),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }]),

                holdout: None,
            }),
            None,
            None,
            None,
        );
        let person_property_overrides =
            HashMap::from([("$feature_enrollment/my-flag".to_string(), json!("true"))]);
        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
            ..Default::default()
        };

        reset_fetch_calls_count();

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            "new_user_not_in_db".to_string(),
            None,
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            Some(person_property_overrides),
            None,
            None,
            Uuid::new_v4(),
            None,
            false,
        )
        .await
        .unwrap();

        // Verify no DB fetch was needed since all required properties are in overrides
        let fetch_calls = get_fetch_calls_count();
        assert_eq!(
            fetch_calls, 0,
            "Should not need DB fetch when super_group properties are in overrides"
        );
        assert!(
            !result.errors_while_computing_flags,
            "Should not have errors"
        );

        let flag_result = result.flags.get("early_access_flag").unwrap();
        assert_eq!(
            flag_result.to_value(),
            FlagValue::Boolean(true),
            "Flag should match via super_condition override even without person in DB"
        );
        assert_eq!(
            flag_result.reason.code,
            FeatureFlagMatchReason::SuperConditionValue.to_string(),
            "Match reason should be SuperConditionValue"
        );
    }

    #[tokio::test]
    async fn test_super_condition_override_takes_precedence_over_db() {
        // Test that person_property_overrides take precedence over DB values
        // for super_condition evaluation.
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Early Access Flag".to_string()),
            Some("early_access_flag".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(0.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "$feature_enrollment/my-flag".to_string(),
                        value: Some(json!(["true"])),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }]),

                holdout: None,
            }),
            None,
            None,
            None,
        );

        // Person exists in DB with enrollment set to FALSE
        context
            .insert_person(
                team.id,
                "test_user".to_string(),
                Some(json!({
                    "email": "test@example.com",
                    "$feature_enrollment/my-flag": "false"
                })),
            )
            .await
            .unwrap();

        // Override says TRUE - this should win
        let person_property_overrides =
            HashMap::from([("$feature_enrollment/my-flag".to_string(), json!("true"))]);

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
            ..Default::default()
        };
        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None,
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            Some(person_property_overrides),
            None,
            None,
            Uuid::new_v4(),
            None,
            false,
        )
        .await
        .unwrap();

        assert!(
            !result.errors_while_computing_flags,
            "Should not have errors"
        );
        let flag_result = result.flags.get("early_access_flag").unwrap();
        assert_eq!(
            flag_result.to_value(),
            FlagValue::Boolean(true),
            "Override should take precedence over DB value for super_condition"
        );
        assert_eq!(
            flag_result.reason.code,
            FeatureFlagMatchReason::SuperConditionValue.to_string(),
            "Match reason should be SuperConditionValue"
        );
    }

    #[tokio::test]
    async fn test_super_condition_with_override_person_exists_without_property() {
        // Test that super_condition matches when person exists in DB
        // but doesn't have the enrollment property, and we provide it via override.
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();
        let flag = create_test_flag(
            Some(1),
            Some(team.id),
            Some("Early Access Flag".to_string()),
            Some("early_access_flag".to_string()),
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: None,
                    rollout_percentage: Some(0.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "$feature_enrollment/my-flag".to_string(),
                        value: Some(json!(["true"])),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }]),

                holdout: None,
            }),
            None,
            None,
            None,
        );

        // Person exists in DB but does NOT have the enrollment property
        context
            .insert_person(
                team.id,
                "test_user".to_string(),
                Some(json!({
                    "email": "test@example.com"
                })),
            )
            .await
            .unwrap();

        // Override provides the enrollment property
        let person_property_overrides =
            HashMap::from([("$feature_enrollment/my-flag".to_string(), json!("true"))]);

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
            ..Default::default()
        };

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None,
            team.id,
            router,
            cohort_cache.clone(),
            None,
            None,
        )
        .evaluate_all_feature_flags(
            flags,
            Some(person_property_overrides),
            None,
            None,
            Uuid::new_v4(),
            None,
            false,
        )
        .await
        .unwrap();

        assert!(
            !result.errors_while_computing_flags,
            "Should not have errors"
        );
        let flag_result = result.flags.get("early_access_flag").unwrap();
        assert_eq!(
            flag_result.to_value(),
            FlagValue::Boolean(true),
            "Override should provide missing property for super_condition match"
        );
        assert_eq!(
            flag_result.reason.code,
            FeatureFlagMatchReason::SuperConditionValue.to_string(),
            "Match reason should be SuperConditionValue"
        );
    }

    #[tokio::test]
    async fn test_paired_group_identifiers_avoid_cartesian_product() {
        use crate::utils::test_utils::create_group_in_pg;

        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context.insert_new_team(None).await.unwrap();

        // Flag targeting "project" (group type index 0)
        let project_flag = create_test_flag(
            None,
            Some(team.id),
            None,
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "name".to_string(),
                        value: Some(json!("Acme")),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Group,
                        group_type_index: Some(0),
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: Some(0),
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        // Flag targeting "organization" (group type index 1)
        let org_flag = create_test_flag(
            Some(2),
            Some(team.id),
            Some("org_flag".to_string()),
            None,
            Some(FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "tier".to_string(),
                        value: Some(json!("enterprise")),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Group,
                        group_type_index: Some(1),
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: Some(1),
                payloads: None,
                super_groups: None,

                holdout: None,
            }),
            None,
            None,
            None,
        );

        // Insert correct group rows
        create_group_in_pg(
            context.persons_reader.clone(),
            team.id,
            "project",
            "proj-456",
            json!({"name": "Acme"}),
        )
        .await
        .unwrap();

        create_group_in_pg(
            context.persons_reader.clone(),
            team.id,
            "organization",
            "org-123",
            json!({"tier": "enterprise"}),
        )
        .await
        .unwrap();

        // Insert a decoy row: project type (index 0) with org's key ("org-123").
        // With the old cartesian-product query this row would be fetched and its
        // properties would overwrite the correct project properties.
        create_group_in_pg(
            context.persons_reader.clone(),
            team.id,
            "project",
            "org-123",
            json!({"name": "DECOY"}),
        )
        .await
        .unwrap();

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.id);
        group_type_mapping_cache
            .init(context.persons_reader.clone())
            .await
            .unwrap();

        let groups = HashMap::from([
            ("project".to_string(), json!("proj-456")),
            ("organization".to_string(), json!("org-123")),
        ]);

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None,
            team.id,
            router,
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            Some(groups),
        );

        matcher
            .prepare_flag_evaluation_state(&[&project_flag, &org_flag])
            .await
            .unwrap();

        let group_props = matcher.flag_evaluation_state.get_group_properties();

        // Project (index 0) should have properties from (0, "proj-456"), not the decoy (0, "org-123")
        let project_props = group_props
            .get(&0)
            .expect("project group properties should be loaded");
        assert_eq!(
            project_props.get("name"),
            Some(&json!("Acme")),
            "Project properties should come from the correct (type_index, key) pair, not the cartesian-product decoy"
        );

        // Organization (index 1) should have its own properties
        let org_props = group_props
            .get(&1)
            .expect("organization group properties should be loaded");
        assert_eq!(org_props.get("tier"), Some(&json!("enterprise")));
    }

    #[tokio::test]
    async fn test_end_to_end_evaluation_via_precomputed_path() {
        // Exercises flag evaluation through the precomputed (EvaluationMetadata) path.
        // A(1)->B(2)->C(3) dependency chain where C has 100% rollout, B depends on C,
        // and A depends on B. All should evaluate to true.
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        // C: no deps, 100% rollout
        let flag_c = create_test_flag(
            Some(3),
            Some(team.id),
            None,
            Some("flag_c".to_string()),
            None,
            None,
            None,
            None,
        );

        // B: depends on C evaluating to true
        let flag_b = create_test_flag_that_depends_on_flag(
            2,
            team.id,
            "flag_b",
            3,
            FlagValue::Boolean(true),
        );

        // A: depends on B evaluating to true
        let flag_a = create_test_flag_that_depends_on_flag(
            1,
            team.id,
            "flag_a",
            2,
            FlagValue::Boolean(true),
        );

        let flags = FeatureFlagList {
            flags: vec![flag_a, flag_b, flag_c],
            evaluation_metadata: Some(EvaluationMetadata {
                dependency_stages: vec![vec![3], vec![2], vec![1]],
                flags_with_missing_deps: vec![],
                transitive_deps: HashMap::from([
                    (1, HashSet::from([2, 3])),
                    (2, HashSet::from([3])),
                    (3, HashSet::new()),
                ]),
            }),
            ..Default::default()
        };

        let precomputed = PrecomputedDependencyGraph::build(&flags, team.id, None)
            .expect("Should build from precomputed metadata");

        assert!(
            !precomputed.is_graph_fallback,
            "Should use the precomputed path"
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None,
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );

        let result = matcher
            .evaluate_flags_with_overrides(
                Default::default(),
                Uuid::new_v4(),
                precomputed.evaluation_stages,
                precomputed.flags_with_missing_deps,
            )
            .await
            .unwrap();

        // All three flags should evaluate to true via the dependency chain
        let flag_c_result = result
            .flags
            .get("flag_c")
            .expect("flag_c should be present");
        assert!(flag_c_result.enabled, "flag_c (no deps) should be enabled");

        let flag_b_result = result
            .flags
            .get("flag_b")
            .expect("flag_b should be present");
        assert!(
            flag_b_result.enabled,
            "flag_b (depends on flag_c=true) should be enabled"
        );

        let flag_a_result = result
            .flags
            .get("flag_a")
            .expect("flag_a should be present");
        assert!(
            flag_a_result.enabled,
            "flag_a (depends on flag_b=true) should be enabled"
        );
    }

    #[tokio::test]
    async fn test_precomputed_path_missing_dep_evaluates_to_false() {
        // Flag with a missing dependency should evaluate to false (fail closed)
        // when stages come from precomputed metadata.
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            None,
            None,
        ));
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        // flag_a depends on a non-existent flag (id=999)
        let flag_a = create_test_flag_that_depends_on_flag(
            1,
            team.id,
            "flag_a",
            999,
            FlagValue::Boolean(true),
        );

        // flag_b has no deps, 100% rollout
        let flag_b = create_test_flag(
            Some(2),
            Some(team.id),
            None,
            Some("flag_b".to_string()),
            None,
            None,
            None,
            None,
        );

        let flags = FeatureFlagList {
            flags: vec![flag_a, flag_b],
            evaluation_metadata: Some(EvaluationMetadata {
                dependency_stages: vec![vec![1, 2]],
                flags_with_missing_deps: vec![1],
                transitive_deps: HashMap::from([(1, HashSet::new()), (2, HashSet::new())]),
            }),
            ..Default::default()
        };

        let precomputed = PrecomputedDependencyGraph::build(&flags, team.id, None)
            .expect("Should build from precomputed metadata");

        assert!(!precomputed.is_graph_fallback);
        assert!(precomputed.flags_with_missing_deps.contains(&1));

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            None,
            team.id,
            router,
            cohort_cache,
            None,
            None,
        );

        let result = matcher
            .evaluate_flags_with_overrides(
                Default::default(),
                Uuid::new_v4(),
                precomputed.evaluation_stages,
                precomputed.flags_with_missing_deps,
            )
            .await
            .unwrap();

        // flag_a has a missing dep and should evaluate to false (fail closed)
        let flag_a_result = result
            .flags
            .get("flag_a")
            .expect("flag_a should be present");
        assert!(
            !flag_a_result.enabled,
            "Flag with missing dependency should evaluate to false"
        );

        // flag_b should still evaluate normally
        let flag_b_result = result
            .flags
            .get("flag_b")
            .expect("flag_b should be present");
        assert!(flag_b_result.enabled, "flag_b (no deps) should be enabled");
    }
}
