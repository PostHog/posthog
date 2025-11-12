#[cfg(test)]
mod tests {
    use common_types::TeamId;
    use serde_json::json;
    use std::collections::HashMap;
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
                get_fetch_calls_count, reset_fetch_calls_count, set_feature_flag_hash_key_overrides,
            },
            flag_models::{
                FeatureFlag, FeatureFlagList, FlagFilters, FlagPropertyGroup,
                MultivariateFlagOptions, MultivariateFlagVariant,
            },
        },
        properties::property_models::{OperatorType, PropertyFilter, PropertyType},
        utils::test_utils::{create_test_flag, TestContext},
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
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let match_result = matcher.get_match(&flag, None, None).unwrap();
        assert!(match_result.matches);
        assert_eq!(match_result.variant, None);

        // Matcher for a non-matching distinct_id
        let router2 = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            not_matching_distinct_id.clone(),
            team.id,
            team.project_id(),
            router2,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let match_result = matcher.get_match(&flag, None, None).unwrap();
        assert!(!match_result.matches);
        assert_eq!(match_result.variant, None);

        // Matcher for a distinct_id that does not exist
        let router3 = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "other_distinct_id".to_string(),
            team.id,
            team.project_id(),
            router3,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let match_result = matcher.get_match(&flag, None, None).unwrap();

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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let overrides = HashMap::from([("email".to_string(), json!("override@example.com"))]);

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id(),
            router,
            cohort_cache,
            None,
            None,
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };
        let result = matcher
            .evaluate_all_feature_flags(flags, Some(overrides), None, None, Uuid::new_v4(), None)
            .await;
        assert!(!result.errors_while_computing_flags);
        assert_eq!(
            result.flags.get("test_flag").unwrap().to_value(),
            FlagValue::Boolean(true)
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
                }],
                multivariate: None,
                aggregation_group_type_index: Some(1),
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id());
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
            team.id,
            team.project_id(),
            context.create_postgres_router(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            Some(groups),
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };
        let result = matcher
            .evaluate_all_feature_flags(
                flags,
                None,
                Some(group_overrides),
                None,
                Uuid::new_v4(),
                None,
            )
            .await;

        let legacy_response = LegacyFlagsResponse::from_response(result);
        assert!(!legacy_response.errors_while_computing_flags);
        assert_eq!(
            legacy_response.feature_flags.get("test_flag"),
            Some(&FlagValue::Boolean(true))
        );
    }

    // Use the shared test utility functions from test_utils.rs
    use crate::utils::test_utils::{
        create_test_flag_that_depends_on_flag, create_test_flag_with_properties,
        create_test_flag_with_property,
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
            team.id,
            team.project_id(),
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
                )
                .await;
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
                .evaluate_all_feature_flags(flags.clone(), None, None, None, Uuid::new_v4(), None)
                .await;
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
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![]),
                        rollout_percentage: Some(100.0),
                        variant: Some("other".to_string()),
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
                holdout_groups: None,
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
            team.id,
            team.project_id(),
            router,
            cohort_cache,
            None,
            None,
        );
        let flags = FeatureFlagList {
            flags: vec![leaf_flag.clone(), parent_flag.clone()],
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
                )
                .await;
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
                )
                .await;
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
                )
                .await;
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
            team.id,
            team.project_id(),
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
        };

        reset_fetch_calls_count();

        let result = matcher
            .evaluate_all_feature_flags(flags.clone(), None, None, None, Uuid::new_v4(), None)
            .await;
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
            team.id,
            team.project_id(),
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
                )
                .await;
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
            assert!(!result.flags.contains_key("cycle_start_flag"));
            assert!(!result.flags.contains_key("cycle_middle_flag"));
            assert!(!result.flags.contains_key("cycle_node"));
            assert!(!result.flags.contains_key("missing_dependency_flag"));
        }
        {
            // Leaf flag evaluates to false
            let result = matcher
                .evaluate_all_feature_flags(flags.clone(), None, None, None, Uuid::new_v4(), None)
                .await;
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
            assert!(!result.flags.contains_key("cycle_start_flag"));
            assert!(!result.flags.contains_key("cycle_middle_flag"));
            assert!(!result.flags.contains_key("cycle_node"));
            assert!(!result.flags.contains_key("missing_dependency_flag"));
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
                holdout_groups: None,
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
            team.id,
            team.project_id(),
            router,
            cohort_cache,
            None,
            None,
        );
        let flags = FeatureFlagList {
            flags: vec![leaf_flag.clone(), parent_flag.clone()],
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
                )
                .await;
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
                )
                .await;
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
                .evaluate_all_feature_flags(flags.clone(), None, None, None, Uuid::new_v4(), None)
                .await;
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
            1,
            1,
            context.create_postgres_router(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            Some(groups),
        );
        let variant = matcher.get_matching_variant(&flag, None).unwrap();
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

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id());
        group_type_mapping_cache
            .init(context.persons_reader.clone())
            .await
            .unwrap();

        let router = context.create_postgres_router();
        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            None,
        );

        let variant = matcher.get_matching_variant(&flag, None).unwrap();
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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let condition = FlagPropertyGroup {
            variant: None,
            properties: Some(vec![]),
            rollout_percentage: Some(100.0),
        };

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            1,
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );
        let (is_match, reason) = matcher
            .is_condition_match(&flag, &condition, None, None)
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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
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
        };

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
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
            .is_condition_match(&flag, &condition, None, None)
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
                holdout_groups: None,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
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
            team.id,
            team.project_id(),
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
                },
                Some(person_property_overrides),
                None,
                None,
                Uuid::new_v4(),
                None,
            )
            .await;

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
        let project_id = team.project_id();
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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
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
                    team_id,
                    project_id,
                    router,
                    cohort_cache_clone,
                    None,
                    None,
                );
                matcher.get_match(&flag_clone, None, None).unwrap()
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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
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
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "".to_string(),
            1,
            1,
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            1,
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(!result.matches);

        // Now set the rollout percentage to 100%
        flag.filters.groups[0].rollout_percentage = Some(100.0);

        let result = matcher.get_match(&flag, None, None).unwrap();

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
            1,
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
            let variant = matcher.get_matching_variant(&flag, None).unwrap();
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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id(),
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id(),
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            1,
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );

        let (is_match, reason) = matcher
            .is_condition_match(&flag, &flag.filters.groups[0], None, None)
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
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
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
            team.id,
            team.project_id(),
            context.create_postgres_router(),
            cohort_cache,
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
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
                team.id,
                team.project_id(),
                router,
                cohort_cache.clone(),
                None,
                None,
            );

            matcher
                .prepare_flag_evaluation_state(&[&flag])
                .await
                .unwrap();

            let result = matcher.get_match(&flag, None, None).unwrap();
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
                    },
                    FlagPropertyGroup {
                        properties: None,
                        rollout_percentage: Some(50.0),
                        variant: None,
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
                }]),
                holdout_groups: None,
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
            team.id,
            team.project_id(),
            router.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_example_id = FeatureFlagMatcher::new(
            "lil_id".to_string(),
            team.id,
            team.project_id(),
            router.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_another_id = FeatureFlagMatcher::new(
            "another_id".to_string(),
            team.id,
            team.project_id(),
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

        let result_test_id = matcher_test_id.get_match(&flag, None, None).unwrap();
        let result_example_id = matcher_example_id.get_match(&flag, None, None).unwrap();
        let result_another_id = matcher_another_id.get_match(&flag, None, None).unwrap();

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
                    },
                    FlagPropertyGroup {
                        properties: None,
                        rollout_percentage: Some(50.0),
                        variant: None,
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
                }]),
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_id".to_string(),
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

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
                    },
                    FlagPropertyGroup {
                        properties: None,
                        rollout_percentage: Some(50.0),
                        variant: None,
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
                }]),
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher_test_id = FeatureFlagMatcher::new(
            "test_id".to_string(),
            team.id,
            team.project_id(),
            router.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_example_id = FeatureFlagMatcher::new(
            "lil_id".to_string(),
            team.id,
            team.project_id(),
            router.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_another_id = FeatureFlagMatcher::new(
            "another_id".to_string(),
            team.id,
            team.project_id(),
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

        let result_test_id = matcher_test_id.get_match(&flag, None, None).unwrap();
        let result_example_id = matcher_example_id.get_match(&flag, None, None).unwrap();
        let result_another_id = matcher_another_id.get_match(&flag, None, None).unwrap();

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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

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

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id());
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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
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
            team.project_id(),
            "hash_key_continuity".to_string(),
        )
        .await
        .unwrap();

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id(),
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
        )
        .await;

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

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id());
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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            Some(true),
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            None,
        )
        .evaluate_all_feature_flags(flags, None, None, None, Uuid::new_v4(), None)
        .await;

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

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id());
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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
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
            team.project_id(),
            "hash_key_mixed".to_string(),
        )
        .await
        .unwrap();

        let flags = FeatureFlagList {
            flags: vec![flag_continuity.clone(), flag_no_continuity.clone()],
        };

        let router = context.create_postgres_router();
        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id(),
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
        )
        .await;

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
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

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
                holdout_groups: None,
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
            .get_match(&flag_invalid_override, None, None)
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
                }],
                holdout_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(70.0),
                    variant: Some("holdout".to_string()),
                }]),
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
                }],
                holdout_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(70.0),
                    variant: Some("holdout".to_string()),
                }]),
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
                }],
                holdout_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(0.0),
                    variant: Some("holdout".to_string()),
                }]),
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
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag_with_holdout])
            .await
            .unwrap();

        let result = matcher.get_match(&flag_with_holdout, None, None).unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("second-variant".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::ConditionMatch);

        // Test inside holdout behavior - should get holdout variant override
        let router2 = context.create_postgres_router();
        let mut matcher2 = FeatureFlagMatcher::new(
            "example_id2".to_string(),
            team.id,
            team.project_id(),
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

        let result = matcher2.get_match(&flag_with_holdout, None, None).unwrap();

        assert!(result.matches);
        assert_eq!(result.variant, Some("holdout".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::HoldoutConditionValue);

        // same should hold true for a different feature flag when within holdout
        let result = matcher2
            .get_match(&other_flag_with_holdout, None, None)
            .unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("holdout".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::HoldoutConditionValue);

        // Test with matcher1 (outside holdout) to verify different variants
        let result = matcher
            .get_match(&other_flag_with_holdout, None, None)
            .unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("third-variant".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::ConditionMatch);

        // when holdout exists but is zero, should default to regular flag evaluation
        let result = matcher
            .get_match(&flag_without_holdout, None, None)
            .unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("second-variant".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::ConditionMatch);

        let result = matcher2
            .get_match(&flag_without_holdout, None, None)
            .unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("second-variant".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::ConditionMatch);
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
                holdout_groups: None,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
        };

        // Test user "11" - should get first-variant
        let router = context.create_postgres_router();
        let matcher = FeatureFlagMatcher::new(
            "11".to_string(),
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );
        let result = matcher.get_match(&flag, None, None).unwrap();
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
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );
        let result = matcher.get_match(&flag, None, None).unwrap();
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
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );
        let result = matcher.get_match(&flag, None, None).unwrap();
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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        let router = context.create_postgres_router();
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id(),
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
        let result = matcher.get_match(&flag, None, None);
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
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
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
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher
            .evaluate_all_feature_flags(
                FeatureFlagList {
                    flags: vec![flag.clone()],
                },
                Some(person_property_overrides),
                None,
                None,
                Uuid::new_v4(),
                None,
            )
            .await;

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
                }],
                multivariate: None,
                aggregation_group_type_index: Some(1),
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        // Set up group type mapping cache
        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id());
        group_type_mapping_cache
            .init(context.persons_reader.clone())
            .await
            .unwrap();

        // Test with numeric group key
        let groups_numeric = HashMap::from([("organization".to_string(), json!(123))]);
        let router = context.create_postgres_router();
        let mut matcher_numeric = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups_numeric),
        );

        matcher_numeric
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result_numeric = matcher_numeric.get_match(&flag, None, None).unwrap();

        // Test with string group key (same value)
        let groups_string = HashMap::from([("organization".to_string(), json!("123"))]);
        let router2 = context.create_postgres_router();
        let mut matcher_string = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id(),
            router2,
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups_string),
        );

        matcher_string
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result_string = matcher_string.get_match(&flag, None, None).unwrap();

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
            team.id,
            team.project_id(),
            router3,
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups_float),
        );

        matcher_float
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result_float = matcher_float.get_match(&flag, None, None).unwrap();
        assert!(result_float.matches, "Float group key should match");

        // Test with invalid group key type (should use empty string and not match this specific case)
        let groups_bool = HashMap::from([("organization".to_string(), json!(true))]);
        let router4 = context.create_postgres_router();
        let mut matcher_bool = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id(),
            router4,
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups_bool),
        );

        matcher_bool
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result_bool = matcher_bool.get_match(&flag, None, None).unwrap();
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
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: Some(vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "$feature_enrollment/artificial-hog".to_string(),
                        value: Some(json!(["true"])),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }]),
                holdout_groups: None,
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
                    "$feature_enrollment/artificial-hog": true
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
                    "$feature_enrollment/artificial-hog": false
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
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();
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
            team.id,
            team.project_id(),
            router2,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();
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
            team.id,
            team.project_id(),
            router3,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();
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
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[&flag])
            .await
            .unwrap();

        let match_result = matcher.get_match(&flag, None, None).unwrap();
        assert!(match_result.matches);
        assert_eq!(match_result.variant, None);
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
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
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
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
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
            )
            .await;

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
            team.id,
            team.project_id(),
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
            )
            .await;

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
            team.id,
            team.project_id(),
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
            )
            .await;

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
            team.id,
            team.project_id(),
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
            )
            .await;

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
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: Some(1), // This is a group-based flag
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            }),
            None,
            None,
            None,
        );

        // Set up group type mappings
        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id());
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
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups.clone()),
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };

        let result = matcher
            .evaluate_all_feature_flags(
                flags.clone(),
                None,
                Some(partial_group_overrides),
                None,
                Uuid::new_v4(),
                None,
            )
            .await;

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
            team.id,
            team.project_id(),
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
            )
            .await;

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
            team.id,
            team.project_id(),
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
            )
            .await;

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
            team.id,
            team.project_id(),
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
            )
            .await;

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
            team.id,
            team.project_id(),
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
            )
            .await;

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
                    },
                    FlagPropertyGroup {
                        variant: Some("test".to_string()), // Has variant override
                        properties: Some(vec![]),          // Catch-all
                        rollout_percentage: Some(100.0),
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
                holdout_groups: None,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
        };

        let router = context.create_postgres_router();

        // Test 1: User with email "specific@example.com" should match first condition
        let matcher = FeatureFlagMatcher::new(
            "specific_user".to_string(),
            team.id,
            team.project_id(),
            router.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        // Pass email as a property override to avoid database lookup
        let mut user_properties = HashMap::new();
        user_properties.insert("email".to_string(), json!("specific@example.com"));

        let result = matcher
            .get_match(&flag, Some(user_properties), None)
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
            team.id,
            team.project_id(),
            router,
            cohort_cache.clone(),
            None,
            None,
        );

        let mut other_properties = HashMap::new();
        other_properties.insert("email".to_string(), json!("other@example.com"));

        let result2 = matcher2
            .get_match(&flag, Some(other_properties), None)
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
            team.id,
            team.project_id(),
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
        };

        // Test the scenario where hash key override reading fails
        // This simulates the case where we have experience continuity flags but hash override reads fail
        let overrides = crate::flags::flag_matching::FlagEvaluationOverrides {
            person_property_overrides: None,
            group_property_overrides: None,
            hash_key_overrides: None, // hash_key_overrides (None simulates read failure)
            hash_key_override_error: true, // hash_key_override_error (simulates the error occurred)
        };

        let response = matcher
            .evaluate_flags_with_overrides(
                flags,
                overrides,
                Uuid::new_v4(),
                None, // flag_keys
            )
            .await;

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
}
