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
            flag_matching_utils::set_feature_flag_hash_key_overrides,
            flag_models::{
                FeatureFlag, FeatureFlagList, FlagFilters, FlagPropertyGroup,
                MultivariateFlagOptions, MultivariateFlagVariant,
            },
        },
        properties::property_models::{OperatorType, PropertyFilter, PropertyType},
        utils::test_utils::{
            add_person_to_cohort, create_test_flag, get_person_id_by_distinct_id,
            insert_cohort_for_team_in_pg, insert_new_team_in_pg, insert_person_for_team_in_pg,
            setup_pg_reader_client, setup_pg_writer_client,
        },
    };

    #[tokio::test]
    async fn test_fetch_properties_from_pg_to_match() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));

        let team = insert_new_team_in_pg(reader.clone(), None)
            .await
            .expect("Failed to insert team in pg");

        let distinct_id = "user_distinct_id".to_string();
        insert_person_for_team_in_pg(reader.clone(), team.id, distinct_id.clone(), None)
            .await
            .expect("Failed to insert person");

        let not_matching_distinct_id = "not_matching_distinct_id".to_string();
        insert_person_for_team_in_pg(
            reader.clone(),
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
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let match_result = matcher.get_match(&flag, None, None).unwrap();
        assert!(match_result.matches);
        assert_eq!(match_result.variant, None);

        // Matcher for a non-matching distinct_id
        let mut matcher = FeatureFlagMatcher::new(
            not_matching_distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let match_result = matcher.get_match(&flag, None, None).unwrap();
        assert!(!match_result.matches);
        assert_eq!(match_result.variant, None);

        // Matcher for a distinct_id that does not exist
        let mut matcher = FeatureFlagMatcher::new(
            "other_distinct_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let match_result = matcher.get_match(&flag, None, None).unwrap();

        // Expecting false for non-existent distinct_id
        assert!(!match_result.matches);
    }

    #[tokio::test]
    async fn test_person_property_overrides() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

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

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader,
            writer,
            cohort_cache,
            None,
            None,
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };
        let result = matcher
            .evaluate_all_feature_flags(flags, Some(overrides), None, None, Uuid::new_v4())
            .await;
        assert!(!result.errors_while_computing_flags);
        assert_eq!(
            result.flags.get("test_flag").unwrap().to_value(),
            FlagValue::Boolean(true)
        );
    }

    #[tokio::test]
    async fn test_group_property_overrides() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

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

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id);
        group_type_mapping_cache.init(reader.clone()).await.unwrap();

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
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            Some(groups),
        );

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };
        let result = matcher
            .evaluate_all_feature_flags(flags, None, Some(group_overrides), None, Uuid::new_v4())
            .await;

        let legacy_response = LegacyFlagsResponse::from_response(result);
        assert!(!legacy_response.errors_while_computing_flags);
        assert_eq!(
            legacy_response.feature_flags.get("test_flag"),
            Some(&FlagValue::Boolean(true))
        );
    }

    #[tokio::test]
    async fn test_get_matching_variant_with_cache() {
        let flag = create_test_flag_with_variants(1);
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let mut group_type_mapping_cache = GroupTypeMappingCache::new(1);
        let group_types_to_indexes = [("group_type_1".to_string(), 1)].into_iter().collect();
        let indexes_to_types = [(1, "group_type_1".to_string())].into_iter().collect();
        group_type_mapping_cache.set_test_mappings(group_types_to_indexes, indexes_to_types);

        let groups = HashMap::from([("group_type_1".to_string(), json!("group_key_1"))]);

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            1,
            1,
            reader.clone(),
            writer.clone(),
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        let flag = create_test_flag_with_variants(team.id);

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id);
        group_type_mapping_cache.init(reader.clone()).await.unwrap();

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
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
            reader,
            writer,
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
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
                operator: Some(OperatorType::Exact),
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
            reader,
            writer,
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
            ensure_experience_continuity: false,
            version: Some(1),
        }
    }

    #[tokio::test]
    async fn test_overrides_avoid_db_lookups() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

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

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
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
            )
            .await;

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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();
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
            let reader_clone = reader.clone();
            let writer_clone = writer.clone();
            let cohort_cache_clone = cohort_cache.clone();
            handles.push(tokio::spawn(async move {
                let matcher = FeatureFlagMatcher::new(
                    format!("test_user_{}", i),
                    team.id,
                    team.project_id,
                    reader_clone,
                    writer_clone,
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

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

        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"email": "user@example@domain.com", "age": 30})),
        )
        .await
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_empty_hashed_identifier() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
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
            reader,
            writer,
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_rollout_percentage() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
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
            reader,
            writer,
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
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
            reader,
            writer,
            cohort_cache,
            None,
            None,
        );

        let mut control_count = 0;
        let mut test_count = 0;
        let mut test2_count = 0;

        // Run the test multiple times to simulate distribution
        for i in 0..1000 {
            matcher.distinct_id = format!("user_{}", i);
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a person without properties
        insert_person_for_team_in_pg(reader.clone(), team.id, "test_user".to_string(), None)
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
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache,
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_malformed_property_data() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a person with malformed properties
        insert_person_for_team_in_pg(
            reader.clone(),
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
            team.project_id,
            reader.clone(),
            writer.clone(),
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
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
            reader.clone(),
            writer.clone(),
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

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

        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "test_user".to_string(),
            Some(json!({"email": "user2@example.com", "age": 35})),
        )
        .await
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache,
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_complex_cohort_conditions() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a cohort with complex conditions
        let cohort_row = insert_cohort_for_team_in_pg(
            reader.clone(),
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
        insert_person_for_team_in_pg(
            reader.clone(),
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
        insert_person_for_team_in_pg(
            reader.clone(),
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
        insert_person_for_team_in_pg(
            reader.clone(),
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
        insert_person_for_team_in_pg(
            reader.clone(),
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
        insert_person_for_team_in_pg(
            reader.clone(),
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
        insert_person_for_team_in_pg(
            reader.clone(),
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
            let mut matcher = FeatureFlagMatcher::new(
                user_id.to_string(),
                team.id,
                team.project_id,
                reader.clone(),
                writer.clone(),
                cohort_cache.clone(),
                None,
                None,
            );

            matcher
                .prepare_flag_evaluation_state(&[flag.clone()])
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

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

        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "test_id".to_string(),
            Some(json!({"email": "test@posthog.com", "is_enabled": true})),
        )
        .await
        .unwrap();

        insert_person_for_team_in_pg(reader.clone(), team.id, "lil_id".to_string(), None)
            .await
            .unwrap();

        insert_person_for_team_in_pg(reader.clone(), team.id, "another_id".to_string(), None)
            .await
            .unwrap();

        let mut matcher_test_id = FeatureFlagMatcher::new(
            "test_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_example_id = FeatureFlagMatcher::new(
            "lil_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_another_id = FeatureFlagMatcher::new(
            "another_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher_test_id
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        matcher_example_id
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        matcher_another_id
            .prepare_flag_evaluation_state(&[flag.clone()])
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        insert_person_for_team_in_pg(
            reader.clone(),
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

        let mut matcher = FeatureFlagMatcher::new(
            "test_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(result.matches);
        assert_eq!(result.reason, FeatureFlagMatchReason::SuperConditionValue);
        assert_eq!(result.condition_index, Some(0));
    }

    #[tokio::test]
    async fn test_super_condition_matches_and_false() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "test_id".to_string(),
            Some(json!({"email": "test@posthog.com", "is_enabled": true})),
        )
        .await
        .unwrap();

        insert_person_for_team_in_pg(reader.clone(), team.id, "another_id".to_string(), None)
            .await
            .unwrap();

        insert_person_for_team_in_pg(reader.clone(), team.id, "lil_id".to_string(), None)
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

        let mut matcher_test_id = FeatureFlagMatcher::new(
            "test_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_example_id = FeatureFlagMatcher::new(
            "lil_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let mut matcher_another_id = FeatureFlagMatcher::new(
            "another_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher_test_id
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        matcher_example_id
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        matcher_another_id
            .prepare_flag_evaluation_state(&[flag.clone()])
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a cohort with the condition that matches the test user's properties
        let cohort_row = insert_cohort_for_team_in_pg(
            reader.clone(),
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
        insert_person_for_team_in_pg(
            reader.clone(),
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

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_not_in_cohort_matching() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a cohort with a condition that does not match the test user's properties
        let cohort_row = insert_cohort_for_team_in_pg(
            reader.clone(),
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
        insert_person_for_team_in_pg(
            reader.clone(),
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

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_not_in_cohort_matching_user_in_cohort() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a cohort with a condition that matches the test user's properties
        let cohort_row = insert_cohort_for_team_in_pg(
            reader.clone(),
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
        insert_person_for_team_in_pg(
            reader.clone(),
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

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a base cohort
        let base_cohort_row = insert_cohort_for_team_in_pg(
            reader.clone(),
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
        let dependent_cohort_row = insert_cohort_for_team_in_pg(
            reader.clone(),
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
        insert_person_for_team_in_pg(
            reader.clone(),
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

        let mut matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag, None, None).unwrap();

        assert!(result.matches);
    }

    #[tokio::test]
    async fn test_in_cohort_matching_user_not_in_cohort() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a cohort with a condition that does not match the test user's properties
        let cohort_row = insert_cohort_for_team_in_pg(
            reader.clone(),
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
        insert_person_for_team_in_pg(
            reader.clone(),
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

        let matcher = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        let result = matcher.get_match(&flag, None, None).unwrap();

        // The user does not match the cohort, and the flag is set to In, so it should evaluate to false
        assert!(!result.matches);
    }

    #[tokio::test]
    async fn test_static_cohort_matching_user_in_cohort() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a static cohort
        let cohort = insert_cohort_for_team_in_pg(
            reader.clone(),
            team.id,
            Some("Static Cohort".to_string()),
            json!({}), // Static cohorts don't have property filters
            true,      // is_static = true
        )
        .await
        .unwrap();

        // Insert a person
        let distinct_id = "static_user".to_string();
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "static@user.com"})),
        )
        .await
        .unwrap();

        // Retrieve the person's ID
        let person_id = get_person_id_by_distinct_id(reader.clone(), team.id, &distinct_id)
            .await
            .unwrap();

        // Associate the person with the static cohort
        add_person_to_cohort(reader.clone(), person_id, cohort.id)
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

        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a static cohort
        let cohort = insert_cohort_for_team_in_pg(
            reader.clone(),
            team.id,
            Some("Another Static Cohort".to_string()),
            json!({}), // Static cohorts don't have property filters
            true,
        )
        .await
        .unwrap();

        // Insert a person
        let distinct_id = "non_static_user".to_string();
        insert_person_for_team_in_pg(
            reader.clone(),
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

        let matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a static cohort
        let cohort = insert_cohort_for_team_in_pg(
            reader.clone(),
            team.id,
            Some("Static Cohort NotIn".to_string()),
            json!({}), // Static cohorts don't have property filters
            true,      // is_static = true
        )
        .await
        .unwrap();

        // Insert a person
        let distinct_id = "not_in_static_user".to_string();
        insert_person_for_team_in_pg(
            reader.clone(),
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

        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a static cohort
        let cohort = insert_cohort_for_team_in_pg(
            reader.clone(),
            team.id,
            Some("Static Cohort NotIn User In".to_string()),
            json!({}), // Static cohorts don't have property filters
            true,      // is_static = true
        )
        .await
        .unwrap();

        // Insert a person
        let distinct_id = "in_not_in_static_user".to_string();
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "innotinstatic@user.com"})),
        )
        .await
        .unwrap();

        // Retrieve the person's ID
        let person_id = get_person_id_by_distinct_id(reader.clone(), team.id, &distinct_id)
            .await
            .unwrap();

        // Associate the person with the static cohort
        add_person_to_cohort(reader.clone(), person_id, cohort.id)
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

        let matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();
        let distinct_id = "user3".to_string();

        // Insert person
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "user3@example.com"})),
        )
        .await
        .unwrap();

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id);
        group_type_mapping_cache.init(reader.clone()).await.unwrap();

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
        set_feature_flag_hash_key_overrides(
            writer.clone(),
            team.id,
            vec![distinct_id.clone()],
            team.project_id,
            "hash_key_continuity".to_string(),
        )
        .await
        .unwrap();

        let flags = FeatureFlagList {
            flags: vec![flag.clone()],
        };

        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();
        let distinct_id = "user4".to_string();

        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "user4@example.com"})),
        )
        .await
        .unwrap();

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id);
        group_type_mapping_cache.init(reader.clone()).await.unwrap();

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

        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache),
            None,
        )
        .evaluate_all_feature_flags(flags, None, None, None, Uuid::new_v4())
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();
        let distinct_id = "user5".to_string();

        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "user5@example.com"})),
        )
        .await
        .unwrap();

        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id);
        group_type_mapping_cache.init(reader.clone()).await.unwrap();

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
        set_feature_flag_hash_key_overrides(
            writer.clone(),
            team.id,
            vec![distinct_id.clone()],
            team.project_id,
            "hash_key_mixed".to_string(),
        )
        .await
        .unwrap();

        let flags = FeatureFlagList {
            flags: vec![flag_continuity.clone(), flag_no_continuity.clone()],
        };

        let result = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();
        let distinct_id = "test_user".to_string();

        // Insert a person with properties that will match our condition
        insert_person_for_team_in_pg(
            reader.clone(),
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

        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
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
            .prepare_flag_evaluation_state(&[flag_invalid_override.clone()])
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // example_id is outside 70% holdout
        let _person1 = insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "example_id".to_string(),
            Some(json!({"$some_prop": 5})),
        )
        .await
        .unwrap();

        // example_id2 is within 70% holdout
        let _person2 = insert_person_for_team_in_pg(
            reader.clone(),
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
        let mut matcher = FeatureFlagMatcher::new(
            "example_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag_with_holdout.clone()])
            .await
            .unwrap();

        let result = matcher.get_match(&flag_with_holdout, None, None).unwrap();
        assert!(result.matches);
        assert_eq!(result.variant, Some("second-variant".to_string()));
        assert_eq!(result.reason, FeatureFlagMatchReason::ConditionMatch);

        // Test inside holdout behavior - should get holdout variant override
        let mut matcher2 = FeatureFlagMatcher::new(
            "example_id2".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher2
            .prepare_flag_evaluation_state(&[
                flag_with_holdout.clone(),
                flag_without_holdout.clone(),
                other_flag_with_holdout.clone(),
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

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
            ensure_experience_continuity: false,
            version: Some(1),
        };

        // Test user "11" - should get first-variant
        let matcher = FeatureFlagMatcher::new(
            "11".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
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
        let matcher = FeatureFlagMatcher::new(
            "example_id".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
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
        let matcher = FeatureFlagMatcher::new(
            "3".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

        // Insert a static cohort
        let cohort = insert_cohort_for_team_in_pg(
            reader.clone(),
            team.id,
            Some("Static Cohort".to_string()),
            json!({}), // Static cohorts don't have property filters
            true,      // is_static = true
        )
        .await
        .unwrap();

        // Insert a person
        let distinct_id = "static_user".to_string();
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "static@user.com"})),
        )
        .await
        .unwrap();

        // Get person ID and add to cohort
        let person_id = get_person_id_by_distinct_id(reader.clone(), team.id, &distinct_id)
            .await
            .unwrap();
        add_person_to_cohort(reader.clone(), person_id, cohort.id)
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

        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

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

        let mut matcher = FeatureFlagMatcher::new(
            "nonexistent_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
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
            )
            .await;

        // Should succeed because we have overrides
        assert!(!result.errors_while_computing_flags);
        let flag_details = result.flags.get("test_flag").unwrap();
        assert!(flag_details.enabled);
    }

    #[tokio::test]
    async fn test_numeric_group_keys() {
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

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
        let mut group_type_mapping_cache = GroupTypeMappingCache::new(team.project_id);
        group_type_mapping_cache.init(reader.clone()).await.unwrap();

        // Test with numeric group key
        let groups_numeric = HashMap::from([("organization".to_string(), json!(123))]);
        let mut matcher_numeric = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups_numeric),
        );

        matcher_numeric
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result_numeric = matcher_numeric.get_match(&flag, None, None).unwrap();

        // Test with string group key (same value)
        let groups_string = HashMap::from([("organization".to_string(), json!("123"))]);
        let mut matcher_string = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups_string),
        );

        matcher_string
            .prepare_flag_evaluation_state(&[flag.clone()])
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
        let mut matcher_float = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups_float),
        );

        matcher_float
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let result_float = matcher_float.get_match(&flag, None, None).unwrap();
        assert!(result_float.matches, "Float group key should match");

        // Test with invalid group key type (should use empty string and not match this specific case)
        let groups_bool = HashMap::from([("organization".to_string(), json!(true))]);
        let mut matcher_bool = FeatureFlagMatcher::new(
            "test_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            Some(group_type_mapping_cache.clone()),
            Some(groups_bool),
        );

        matcher_bool
            .prepare_flag_evaluation_state(&[flag.clone()])
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

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
        insert_person_for_team_in_pg(
            reader.clone(),
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
        insert_person_for_team_in_pg(
            reader.clone(),
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
        insert_person_for_team_in_pg(
            reader.clone(),
            team.id,
            "regular_user".to_string(),
            Some(json!({
                "email": "regular@example.com"
            })),
        )
        .await
        .unwrap();

        // Test super condition user
        let mut matcher = FeatureFlagMatcher::new(
            "super_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
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
        let mut matcher = FeatureFlagMatcher::new(
            "posthog_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
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
        let mut matcher = FeatureFlagMatcher::new(
            "regular_user".to_string(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
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
        let reader = setup_pg_reader_client(None).await;
        let writer = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));

        let team = insert_new_team_in_pg(reader.clone(), None)
            .await
            .expect("Failed to insert team in pg");

        let distinct_id = "user_distinct_id".to_string();
        insert_person_for_team_in_pg(reader.clone(), team.id, distinct_id.clone(), None)
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
        let mut matcher = FeatureFlagMatcher::new(
            distinct_id.clone(),
            team.id,
            team.project_id,
            reader.clone(),
            writer.clone(),
            cohort_cache.clone(),
            None,
            None,
        );

        matcher
            .prepare_flag_evaluation_state(&[flag.clone()])
            .await
            .unwrap();

        let match_result = matcher.get_match(&flag, None, None).unwrap();
        assert!(match_result.matches);
        assert_eq!(match_result.variant, None);
    }
}
