use crate::api::errors::FlagError;
use crate::flags::flag_models::*;
use crate::utils::graph_utils::{DependencyProvider, DependencyType};
use serde_json::Value;
use std::collections::{HashMap, HashSet};

impl FeatureFlag {
    /// Returns the group type index for the flag, or None if it's not set.
    ///
    /// See [`FlagFilters::aggregation_group_type_index`] for more details about group type mappings.
    pub fn get_group_type_index(&self) -> Option<i32> {
        self.filters.aggregation_group_type_index
    }

    pub fn get_conditions(&self) -> &Vec<FlagPropertyGroup> {
        &self.filters.groups
    }

    pub fn get_variants(&self) -> Vec<MultivariateFlagVariant> {
        self.filters
            .multivariate
            .as_ref()
            .map(|m| m.variants.clone())
            .unwrap_or_default()
    }

    pub fn get_payload(&self, match_val: &str) -> Option<serde_json::Value> {
        self.filters.payloads.as_ref().and_then(|payloads| {
            payloads
                .as_object()
                .and_then(|obj| obj.get(match_val).cloned())
        })
    }

    /// Returns true if the flag requires DB preparation in order to evaluate the flag.
    ///
    /// This is true if the flag has a group type index set
    /// OR if the flag has a cohort filter
    /// OR if the flag has a property filter and the property filter is not present in the overrides
    pub fn requires_db_preparation(&self, overrides: &HashMap<String, Value>) -> bool {
        self.filters.requires_db_properties(overrides) || self.filters.requires_cohort_filters()
    }
}

/// Returns the set of flags that require DB preparation
pub fn flags_require_db_preparation<'a>(
    flags: &'a [FeatureFlag],
    overrides: &HashMap<String, Value>,
) -> Vec<&'a FeatureFlag> {
    flags
        .iter()
        .filter(|flag| flag.requires_db_preparation(overrides))
        .collect()
}

impl DependencyProvider for FeatureFlag {
    type Id = FeatureFlagId;
    type Error = FlagError;

    fn get_id(&self) -> Self::Id {
        self.id
    }

    fn extract_dependencies(&self) -> Result<HashSet<Self::Id>, Self::Error> {
        let mut dependencies = HashSet::new();
        for group in &self.filters.groups {
            if let Some(properties) = &group.properties {
                for filter in properties {
                    if filter.depends_on_feature_flag() {
                        if let Some(feature_flag_id) = filter.get_feature_flag_id() {
                            dependencies.insert(feature_flag_id);
                        }
                    }
                }
            }
        }
        Ok(dependencies)
    }

    fn dependency_type() -> DependencyType {
        DependencyType::Flag
    }
}

#[cfg(test)]
mod tests {
    use crate::{
        flags::{
            flag_models::*,
            test_helpers::{create_simple_flag, create_simple_property_filter},
        },
        properties::property_models::{OperatorType, PropertyFilter, PropertyType},
    };
    use serde_json::{json, Value};
    use std::time::Instant;
    use tokio::task;

    use super::*;
    use crate::utils::test_utils::{
        insert_flags_for_team_in_redis, setup_redis_client, TestContext,
    };

    #[test]
    fn test_utf16_property_names_and_values() {
        let json_str = r#"{
            "id": 1,
            "team_id": 2,
            "name": "𝖚𝖙𝖋16_𝖙𝖊𝖘𝖙_𝖋𝖑𝖆𝖌",
            "key": "𝖚𝖙𝖋16_𝖙𝖊𝖘𝖙_𝖋𝖑𝖆𝖌",
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "𝖕𝖗𝖔𝖕𝖊𝖗𝖙𝖞",
                                "value": "𝓿𝓪𝓵𝓾𝓮",
                                "type": "person"
                            }
                        ]
                    }
                ]
            }
        }"#;

        let flag: FeatureFlag = serde_json::from_str(json_str).expect("Failed to deserialize");

        assert_eq!(flag.key, "𝖚𝖙𝖋16_𝖙𝖊𝖘𝖙_𝖋𝖑𝖆𝖌");
        let property = &flag.filters.groups[0].properties.as_ref().unwrap()[0];
        assert_eq!(property.key, "𝖕𝖗𝖔𝖕𝖊𝖗𝖙𝖞");
        assert_eq!(property.value, Some(json!("𝓿𝓪𝓵𝓾𝓮")));
    }

    #[test]
    fn test_deserialize_complex_flag() {
        let json_str = r#"{
            "id": 1,
            "team_id": 2,
            "name": "Complex Flag",
            "key": "complex_flag",
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "test@example.com",
                                "operator": "exact",
                                "type": "person"
                            }
                        ],
                        "rollout_percentage": 50
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33.33
                        },
                        {
                            "key": "test",
                            "name": "Test Group",
                            "rollout_percentage": 66.67
                        }
                    ]
                },
                "aggregation_group_type_index": 0,
                "payloads": {"test": {"type": "json", "value": {"key": "value"}}}
            },
            "deleted": false,
            "active": true,
            "ensure_experience_continuity": false,
            "evaluation_runtime": "all"
        }"#;

        let flag: FeatureFlag = serde_json::from_str(json_str).expect("Failed to deserialize");

        assert_eq!(flag.id, 1);
        assert_eq!(flag.team_id, 2);
        assert_eq!(flag.name, Some("Complex Flag".to_string()));
        assert_eq!(flag.key, "complex_flag");
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(flag.filters.groups[0].properties.as_ref().unwrap().len(), 1);
        assert_eq!(flag.filters.groups[0].rollout_percentage, Some(50.0));
        assert_eq!(
            flag.filters.multivariate.as_ref().unwrap().variants.len(),
            2
        );
        assert_eq!(flag.filters.aggregation_group_type_index, Some(0));
        assert!(flag.filters.payloads.is_some());
        assert!(!flag.deleted);
        assert!(flag.active);
        assert_eq!(flag.evaluation_runtime, Some("all".to_string()));
        assert!(!flag.ensure_experience_continuity.unwrap_or(false));
    }

    // TODO: Add more tests to validate deserialization of flags.
    // TODO: Also make sure old flag data is handled, or everything is migrated to new style in production

    #[test]
    fn test_extract_dependencies() {
        use crate::utils::graph_utils::DependencyProvider;
        use std::collections::HashSet;

        // Test flag with no dependencies
        let flag_no_deps = FeatureFlag {
            id: 1,
            team_id: 1,
            name: Some("No Dependencies".to_string()),
            key: "no_deps".to_string(),
            filters: FlagFilters {
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
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: None,
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
        };

        let deps = flag_no_deps.extract_dependencies().unwrap();
        assert!(deps.is_empty());

        // Test flag with feature flag dependency
        let flag_with_dep = FeatureFlag {
            id: 2,
            team_id: 1,
            name: Some("With Dependency".to_string()),
            key: "with_dep".to_string(),
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "100".to_string(), // Feature flag ID as string
                        value: Some(json!("true")),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Flag,
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
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: None,
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
        };

        let deps = flag_with_dep.extract_dependencies().unwrap();
        assert_eq!(deps, HashSet::from([100]));

        // Test flag with multiple dependencies
        let flag_with_multiple_deps = FeatureFlag {
            id: 3,
            team_id: 1,
            name: Some("Multiple Dependencies".to_string()),
            key: "multiple_deps".to_string(),
            filters: FlagFilters {
                groups: vec![
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "200".to_string(), // Feature flag ID as string
                            value: Some(json!("true")),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Flag,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(50.0),
                        variant: None,
                    },
                    FlagPropertyGroup {
                        properties: Some(vec![PropertyFilter {
                            key: "300".to_string(), // Feature flag ID as string
                            value: Some(json!("false")),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Flag,
                            group_type_index: None,
                            negation: None,
                        }]),
                        rollout_percentage: Some(50.0),
                        variant: None,
                    },
                ],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: None,
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
        };

        let deps = flag_with_multiple_deps.extract_dependencies().unwrap();
        assert_eq!(deps, HashSet::from([200, 300]));

        // Test flag with mixed property types (feature flag + regular properties)
        let flag_with_mixed_props = FeatureFlag {
            id: 4,
            team_id: 1,
            name: Some("Mixed Properties".to_string()),
            key: "mixed_props".to_string(),
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![
                        PropertyFilter {
                            key: "400".to_string(), // Feature flag ID as string
                            value: Some(json!("true")),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Flag,
                            group_type_index: None,
                            negation: None,
                        },
                        PropertyFilter {
                            key: "regular_property".to_string(),
                            value: Some(json!("value")),
                            operator: Some(OperatorType::Exact),
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
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: None,
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
        };

        let deps = flag_with_mixed_props.extract_dependencies().unwrap();
        assert_eq!(deps, HashSet::from([400]));
    }

    #[test]
    fn test_operator_type_deserialization() {
        let operators = vec![
            ("exact", OperatorType::Exact),
            ("is_not", OperatorType::IsNot),
            ("icontains", OperatorType::Icontains),
            ("not_icontains", OperatorType::NotIcontains),
            ("regex", OperatorType::Regex),
            ("not_regex", OperatorType::NotRegex),
            ("gt", OperatorType::Gt),
            ("lt", OperatorType::Lt),
            ("gte", OperatorType::Gte),
            ("lte", OperatorType::Lte),
            ("is_set", OperatorType::IsSet),
            ("is_not_set", OperatorType::IsNotSet),
            ("is_date_exact", OperatorType::IsDateExact),
            ("is_date_after", OperatorType::IsDateAfter),
            ("is_date_before", OperatorType::IsDateBefore),
        ];

        for (op_str, op_type) in operators {
            let json = format!(
                r#"{{
            "key": "test_key",
            "value": "test_value",
            "operator": "{op_str}",
            "type": "person"
        }}"#
            );
            let deserialized: PropertyFilter = serde_json::from_str(&json).unwrap();
            assert_eq!(deserialized.operator, Some(op_type));
        }
    }

    #[tokio::test]
    async fn test_multivariate_flag_parsing() {
        let redis_client = setup_redis_client(None).await;
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let multivariate_flag = json!({
            "id": 1,
            "team_id": team.id,
            "name": "Multivariate Flag",
            "key": "multivariate_flag",
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33.33
                        },
                        {
                            "key": "test_a",
                            "name": "Test Group A",
                            "rollout_percentage": 33.33
                        },
                        {
                            "key": "test_b",
                            "name": "Test Group B",
                            "rollout_percentage": 33.34
                        }
                    ]
                }
            },
            "active": true,
            "deleted": false,
            "evaluation_runtime": "all"
        });

        // Insert into Redis
        insert_flags_for_team_in_redis(
            redis_client.clone(),
            team.id,
            team.project_id,
            Some(json!([multivariate_flag]).to_string()),
        )
        .await
        .expect("Failed to insert flag in Redis");

        // Insert into Postgres
        context
            .insert_flag(
                team.id,
                Some(FeatureFlagRow {
                    id: 1,
                    team_id: team.id,
                    name: Some("Multivariate Flag".to_string()),
                    key: "multivariate_flag".to_string(),
                    filters: multivariate_flag["filters"].clone(),
                    deleted: false,
                    active: true,
                    ensure_experience_continuity: Some(false),
                    version: Some(1),
                    evaluation_runtime: Some("all".to_string()),
                    evaluation_tags: None,
                }),
            )
            .await
            .expect("Failed to insert flag in Postgres");

        // Fetch and verify from Redis
        let redis_flags = FeatureFlagList::from_redis(redis_client, team.project_id)
            .await
            .expect("Failed to fetch flags from Redis");

        assert_eq!(redis_flags.flags.len(), 1);
        let redis_flag = &redis_flags.flags[0];
        assert_eq!(redis_flag.key, "multivariate_flag");
        assert_eq!(redis_flag.get_variants().len(), 3);

        // Fetch and verify from Postgres
        let (pg_flags, _) =
            FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.project_id)
                .await
                .expect("Failed to fetch flags from Postgres");
        assert_eq!(pg_flags.flags.len(), 1);
        let pg_flag = &pg_flags.flags[0];
        assert_eq!(pg_flag.key, "multivariate_flag");
        assert_eq!(pg_flag.get_variants().len(), 3);
    }

    #[tokio::test]
    async fn test_multivariate_flag_with_payloads() {
        let redis_client = setup_redis_client(None).await;
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let multivariate_flag_with_payloads = json!({
            "id": 1,
            "team_id": team.id,
            "name": "Multivariate Flag with Payloads",
            "key": "multivariate_flag_with_payloads",
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33.33
                        },
                        {
                            "key": "test_a",
                            "name": "Test Group A",
                            "rollout_percentage": 33.33
                        },
                        {
                            "key": "test_b",
                            "name": "Test Group B",
                            "rollout_percentage": 33.34
                        }
                    ]
                },
                "payloads": {
                    "control": {"type": "json", "value": {"feature": "old"}},
                    "test_a": {"type": "json", "value": {"feature": "new_a"}},
                    "test_b": {"type": "json", "value": {"feature": "new_b"}}
                }
            },
            "active": true,
            "deleted": false
        });

        // Insert into Redis
        insert_flags_for_team_in_redis(
            redis_client.clone(),
            team.id,
            team.project_id,
            Some(json!([multivariate_flag_with_payloads]).to_string()),
        )
        .await
        .expect("Failed to insert flag in Redis");

        // Insert into Postgres
        context
            .insert_flag(
                team.id,
                Some(FeatureFlagRow {
                    id: 1,
                    team_id: team.id,
                    name: Some("Multivariate Flag with Payloads".to_string()),
                    key: "multivariate_flag_with_payloads".to_string(),
                    filters: multivariate_flag_with_payloads["filters"].clone(),
                    deleted: false,
                    active: true,
                    ensure_experience_continuity: Some(false),
                    version: Some(1),
                    evaluation_runtime: Some("all".to_string()),
                    evaluation_tags: None,
                }),
            )
            .await
            .expect("Failed to insert flag in Postgres");

        // Fetch and verify from Redis
        let redis_flags = FeatureFlagList::from_redis(redis_client, team.project_id)
            .await
            .expect("Failed to fetch flags from Redis");

        assert_eq!(redis_flags.flags.len(), 1);
        let redis_flag = &redis_flags.flags[0];
        assert_eq!(redis_flag.key, "multivariate_flag_with_payloads");

        // Fetch and verify from Postgres
        let (pg_flags, _) =
            FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.project_id)
                .await
                .expect("Failed to fetch flags from Postgres");
        assert_eq!(pg_flags.flags.len(), 1);
        let pg_flag = &pg_flags.flags[0];
        assert_eq!(pg_flag.key, "multivariate_flag_with_payloads");

        // Verify flag contents for both Redis and Postgres
        for (source, flag) in [("Redis", redis_flag), ("Postgres", pg_flag)].iter() {
            // Check multivariate options
            assert!(flag.filters.multivariate.is_some());
            let multivariate = flag.filters.multivariate.as_ref().unwrap();
            assert_eq!(multivariate.variants.len(), 3);

            // Check variant details
            let variant_keys = ["control", "test_a", "test_b"];
            let expected_names = ["Control Group", "Test Group A", "Test Group B"];
            for (i, (key, expected_name)) in
                variant_keys.iter().zip(expected_names.iter()).enumerate()
            {
                let variant = &multivariate.variants[i];
                assert_eq!(variant.key, *key);
                assert_eq!(
                    variant.name,
                    Some(expected_name.to_string()),
                    "Incorrect variant name for {key} in {source}"
                );
            }

            // Check payloads
            assert!(flag.filters.payloads.is_some());
            let payloads = flag.filters.payloads.as_ref().unwrap();

            for key in variant_keys.iter() {
                let payload = payloads[key].as_object().unwrap();
                assert_eq!(payload["type"], "json");

                let value = payload["value"].as_object().unwrap();
                let expected_feature = match *key {
                    "control" => "old",
                    "test_a" => "new_a",
                    "test_b" => "new_b",
                    _ => panic!("Unexpected variant key"),
                };
                assert_eq!(
                    value["feature"], expected_feature,
                    "Incorrect payload value for {key} in {source}"
                );
            }
        }
    }

    #[tokio::test]
    async fn test_flag_with_super_groups() {
        let redis_client = setup_redis_client(None).await;
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let flag_with_super_groups = json!({
            "id": 1,
            "team_id": team.id,
            "name": "Flag with Super Groups",
            "key": "flag_with_super_groups",
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 50
                    }
                ],
                "super_groups": [
                    {
                        "properties": [
                            {
                                "key": "country",
                                "value": "US",
                                "type": "person",
                                "operator": "exact"
                            }
                        ],
                        "rollout_percentage": 100
                    }
                ]
            },
            "active": true,
            "deleted": false
        });

        // Insert into Redis
        insert_flags_for_team_in_redis(
            redis_client.clone(),
            team.id,
            team.project_id,
            Some(json!([flag_with_super_groups]).to_string()),
        )
        .await
        .expect("Failed to insert flag in Redis");

        // Insert into Postgres
        context
            .insert_flag(
                team.id,
                Some(FeatureFlagRow {
                    id: 1,
                    team_id: team.id,
                    name: Some("Flag with Super Groups".to_string()),
                    key: "flag_with_super_groups".to_string(),
                    filters: flag_with_super_groups["filters"].clone(),
                    deleted: false,
                    active: true,
                    ensure_experience_continuity: Some(false),
                    version: Some(1),
                    evaluation_runtime: Some("all".to_string()),
                    evaluation_tags: None,
                }),
            )
            .await
            .expect("Failed to insert flag in Postgres");

        // Fetch and verify from Redis
        let redis_flags = FeatureFlagList::from_redis(redis_client, team.project_id)
            .await
            .expect("Failed to fetch flags from Redis");

        assert_eq!(redis_flags.flags.len(), 1);
        let redis_flag = &redis_flags.flags[0];
        assert_eq!(redis_flag.key, "flag_with_super_groups");
        assert!(redis_flag.filters.super_groups.is_some());
        assert_eq!(redis_flag.filters.super_groups.as_ref().unwrap().len(), 1);

        // Fetch and verify from Postgres
        let (pg_flags, _) =
            FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.project_id)
                .await
                .expect("Failed to fetch flags from Postgres");
        assert_eq!(pg_flags.flags.len(), 1);
        let pg_flag = &pg_flags.flags[0];
        assert_eq!(pg_flag.key, "flag_with_super_groups");
        assert!(pg_flag.filters.super_groups.is_some());
        assert_eq!(pg_flag.filters.super_groups.as_ref().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn test_flags_with_different_property_types() {
        let redis_client = setup_redis_client(None).await;
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let flag_with_different_properties = json!({
            "id": 1,
            "team_id": team.id,
            "name": "Flag with Different Properties",
            "key": "flag_with_different_properties",
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "test@example.com",
                                "type": "person",
                                "operator": "exact"
                            },
                            {
                                "key": "country",
                                "value": "US",
                                "type": "group",
                                "operator": "exact"
                            },
                            {
                                "key": "cohort",
                                "value": "123",
                                "type": "cohort",
                                "operator": "exact"
                            }
                        ],
                        "rollout_percentage": 100
                    }
                ]
            },
            "active": true,
            "deleted": false,
            "evaluation_runtime": "all"
        });

        // Insert into Redis
        insert_flags_for_team_in_redis(
            redis_client.clone(),
            team.id,
            team.project_id,
            Some(json!([flag_with_different_properties]).to_string()),
        )
        .await
        .expect("Failed to insert flag in Redis");

        // Insert into Postgres
        context
            .insert_flag(
                team.id,
                Some(FeatureFlagRow {
                    id: 1,
                    team_id: team.id,
                    name: Some("Flag with Different Properties".to_string()),
                    key: "flag_with_different_properties".to_string(),
                    filters: flag_with_different_properties["filters"].clone(),
                    deleted: false,
                    active: true,
                    ensure_experience_continuity: Some(false),
                    version: Some(1),
                    evaluation_runtime: Some("all".to_string()),
                    evaluation_tags: None,
                }),
            )
            .await
            .expect("Failed to insert flag in Postgres");

        // Fetch and verify from Redis
        let redis_flags = FeatureFlagList::from_redis(redis_client, team.project_id)
            .await
            .expect("Failed to fetch flags from Redis");

        assert_eq!(redis_flags.flags.len(), 1);
        let redis_flag = &redis_flags.flags[0];
        assert_eq!(redis_flag.key, "flag_with_different_properties");
        let redis_properties = &redis_flag.filters.groups[0].properties.as_ref().unwrap();
        assert_eq!(redis_properties.len(), 3);
        assert_eq!(redis_properties[0].prop_type, PropertyType::Person);
        assert_eq!(redis_properties[1].prop_type, PropertyType::Group);
        assert_eq!(redis_properties[2].prop_type, PropertyType::Cohort);

        // Fetch and verify from Postgres
        let (pg_flags, _) =
            FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.project_id)
                .await
                .expect("Failed to fetch flags from Postgres");
        assert_eq!(pg_flags.flags.len(), 1);
        let pg_flag = &pg_flags.flags[0];
        assert_eq!(pg_flag.key, "flag_with_different_properties");
        let pg_properties = &pg_flag.filters.groups[0].properties.as_ref().unwrap();
        assert_eq!(pg_properties.len(), 3);
        assert_eq!(pg_properties[0].prop_type, PropertyType::Person);
        assert_eq!(pg_properties[1].prop_type, PropertyType::Group);
        assert_eq!(pg_properties[2].prop_type, PropertyType::Cohort);
    }

    #[tokio::test]
    async fn test_deleted_and_inactive_flags() {
        let redis_client = setup_redis_client(None).await;
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let deleted_flag = json!({
            "id": 1,
            "team_id": team.id,
            "name": "Deleted Flag",
            "key": "deleted_flag",
            "filters": {"groups": []},
            "active": true,
            "deleted": true
        });

        // Insert into Redis
        insert_flags_for_team_in_redis(
            redis_client.clone(),
            team.id,
            team.project_id,
            Some(json!([deleted_flag]).to_string()),
        )
        .await
        .expect("Failed to insert flags in Redis");

        // Insert into Postgres
        context
            .insert_flag(
                team.id,
                Some(FeatureFlagRow {
                    id: 0,
                    team_id: team.id,
                    name: Some("Deleted Flag".to_string()),
                    key: "deleted_flag".to_string(),
                    filters: deleted_flag["filters"].clone(),
                    deleted: true,
                    active: true,
                    ensure_experience_continuity: Some(false),
                    version: Some(1),
                    evaluation_runtime: Some("all".to_string()),
                    evaluation_tags: None,
                }),
            )
            .await
            .expect("Failed to insert deleted flag in Postgres");

        // Fetch and verify from Redis
        let redis_flags = FeatureFlagList::from_redis(redis_client, team.project_id)
            .await
            .expect("Failed to fetch flags from Redis");

        assert_eq!(redis_flags.flags.len(), 1);
        assert!(redis_flags.flags.iter().any(|f| f.deleted));

        // Fetch and verify from Postgres - deleted flags should be filtered out
        let (pg_flags, _) =
            FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.project_id)
                .await
                .expect("Failed to fetch flags from Postgres");
        assert_eq!(pg_flags.flags.len(), 0); // deleted flag is filtered out
        assert!(!pg_flags.flags.iter().any(|f| f.deleted)); // no deleted flags
    }

    #[tokio::test]
    async fn test_error_handling() {
        let redis_client = setup_redis_client(Some("redis://localhost:6379/".to_string())).await;
        let context = TestContext::new(None).await;

        // Test malformed JSON in Redis
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        redis_client
            .set(
                format!("{}{}", TEAM_FLAGS_CACHE_PREFIX, team.id),
                "not a json".to_string(),
            )
            .await
            .expect("Failed to set malformed JSON in Redis");

        let result = FeatureFlagList::from_redis(redis_client, team.project_id).await;
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));

        // Test database query error (using a non-existent table)
        let result = sqlx::query("SELECT * FROM non_existent_table")
            .fetch_all(&mut *context.non_persons_reader.get_connection().await.unwrap())
            .await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_concurrent_access() {
        let redis_client = setup_redis_client(None).await;
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let flag = json!({
            "id": 1,
            "team_id": team.id,
            "name": "Concurrent Flag",
            "key": "concurrent_flag",
            "filters": {"groups": []},
            "active": true,
            "deleted": false
        });

        insert_flags_for_team_in_redis(
            redis_client.clone(),
            team.id,
            team.project_id,
            Some(json!([flag]).to_string()),
        )
        .await
        .expect("Failed to insert flag in Redis");

        context
            .insert_flag(
                team.id,
                Some(FeatureFlagRow {
                    id: 0,
                    team_id: team.id,
                    name: Some("Concurrent Flag".to_string()),
                    key: "concurrent_flag".to_string(),
                    filters: flag["filters"].clone(),
                    deleted: false,
                    active: true,
                    ensure_experience_continuity: Some(false),
                    version: Some(1),
                    evaluation_runtime: Some("all".to_string()),
                    evaluation_tags: None,
                }),
            )
            .await
            .expect("Failed to insert flag in Postgres");

        let mut handles = vec![];
        for _ in 0..10 {
            let redis_client = redis_client.clone();
            let reader = context.non_persons_reader.clone();
            let project_id = team.project_id;

            let handle = task::spawn(async move {
                let redis_flags = FeatureFlagList::from_redis(redis_client, project_id)
                    .await
                    .unwrap();
                let (pg_flags, _) = FeatureFlagList::from_pg(reader, project_id).await.unwrap();
                (redis_flags, pg_flags)
            });

            handles.push(handle);
        }

        for handle in handles {
            let (redis_flags, pg_flags) = handle.await.unwrap();
            assert_eq!(redis_flags.flags.len(), 1);
            assert_eq!(pg_flags.flags.len(), 1);
            assert_eq!(redis_flags.flags[0].key, "concurrent_flag");
            assert_eq!(pg_flags.flags[0].key, "concurrent_flag");
        }
    }

    #[tokio::test]
    #[ignore]
    async fn test_performance() {
        let redis_client = setup_redis_client(None).await;
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let num_flags = 1000;
        let mut flags = Vec::with_capacity(num_flags);

        for i in 0..num_flags {
            let flag = json!({
                "id": i,
                "team_id": team.id,
                "name": format!("Flag {}", i),
                "key": format!("flag_{}", i),
                "filters": {"groups": []},
                "active": true,
                "deleted": false
            });
            flags.push(flag);
        }

        insert_flags_for_team_in_redis(
            redis_client.clone(),
            team.id,
            team.project_id,
            Some(json!(flags).to_string()),
        )
        .await
        .expect("Failed to insert flags in Redis");

        for flag in flags {
            context
                .insert_flag(
                    team.id,
                    Some(FeatureFlagRow {
                        id: 0,
                        team_id: team.id,
                        name: Some(flag["name"].as_str().unwrap().to_string()),
                        key: flag["key"].as_str().unwrap().to_string(),
                        filters: flag["filters"].clone(),
                        deleted: false,
                        active: true,
                        ensure_experience_continuity: Some(false),
                        version: Some(1),
                        evaluation_runtime: Some("all".to_string()),
                        evaluation_tags: None,
                    }),
                )
                .await
                .expect("Failed to insert flag in Postgres");
        }

        let start = Instant::now();
        let redis_flags = FeatureFlagList::from_redis(redis_client, team.project_id)
            .await
            .expect("Failed to fetch flags from Redis");
        let redis_duration = start.elapsed();

        let start = Instant::now();
        let (pg_flags, _) = FeatureFlagList::from_pg(context.non_persons_reader, team.project_id)
            .await
            .expect("Failed to fetch flags from Postgres");
        let pg_duration = start.elapsed();

        tracing::info!("Redis fetch time: {:?}", redis_duration);
        tracing::info!("Postgres fetch time: {:?}", pg_duration);

        assert_eq!(redis_flags.flags.len(), num_flags);
        assert_eq!(pg_flags.flags.len(), num_flags);

        assert!(redis_duration < std::time::Duration::from_millis(100));
        assert!(pg_duration < std::time::Duration::from_millis(1000));
    }

    #[tokio::test]
    async fn test_edge_cases() {
        let redis_client = setup_redis_client(None).await;
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let edge_case_flags = json!([
            {
                "id": 1,
                "team_id": team.id,
                "name": "Empty Properties Flag",
                "key": "empty_properties",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "active": true,
                "deleted": false
            },
            {
                "id": 2,
                "team_id": team.id,
                "name": "Very Long Key Flag",
                "key": "a".repeat(400), // max key length is 400
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "active": true,
                "deleted": false
            },
            {
                "id": 3,
                "team_id": team.id,
                "name": "Unicode Flag",
                "key": "unicode_flag_🚀",
                "filters": {"groups": [{"properties": [{"key": "country", "value": "🇯🇵", "type": "person"}], "rollout_percentage": 100}]},
                "active": true,
                "deleted": false
            }
        ]);

        // Insert edge case flags
        insert_flags_for_team_in_redis(
            redis_client.clone(),
            team.id,
            team.project_id,
            Some(edge_case_flags.to_string()),
        )
        .await
        .expect("Failed to insert edge case flags in Redis");

        for flag in edge_case_flags.as_array().unwrap() {
            context
                .insert_flag(
                    team.id,
                    Some(FeatureFlagRow {
                        id: 0,
                        team_id: team.id,
                        name: flag["name"].as_str().map(|s| s.to_string()),
                        key: flag["key"].as_str().unwrap().to_string(),
                        filters: flag["filters"].clone(),
                        deleted: false,
                        active: true,
                        ensure_experience_continuity: Some(false),
                        version: Some(1),
                        evaluation_runtime: Some("all".to_string()),
                        evaluation_tags: None,
                    }),
                )
                .await
                .expect("Failed to insert edge case flag in Postgres");
        }

        // Fetch and verify edge case flags
        let redis_flags = FeatureFlagList::from_redis(redis_client, team.project_id)
            .await
            .expect("Failed to fetch flags from Redis");
        let (pg_flags, _) =
            FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.project_id)
                .await
                .expect("Failed to fetch flags from Postgres");
        assert_eq!(redis_flags.flags.len(), 3);
        assert_eq!(pg_flags.flags.len(), 3);

        // Verify empty properties flag
        assert!(redis_flags.flags.iter().any(|f| f.key == "empty_properties"
            && f.filters.groups[0].properties.as_ref().unwrap().is_empty()));
        assert!(pg_flags.flags.iter().any(|f| f.key == "empty_properties"
            && f.filters.groups[0].properties.as_ref().unwrap().is_empty()));

        // Verify very long key flag
        assert!(redis_flags.flags.iter().any(|f| f.key.len() == 400));
        assert!(pg_flags.flags.iter().any(|f| f.key.len() == 400));

        // Verify unicode flag
        assert!(redis_flags.flags.iter().any(|f| f.key == "unicode_flag_🚀"));
        assert!(pg_flags.flags.iter().any(|f| f.key == "unicode_flag_🚀"));
    }

    #[tokio::test]
    async fn test_consistent_behavior_from_both_clients() {
        let redis_client = setup_redis_client(None).await;
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let flags = json!([
            {
                "id": 1,
                "team_id": team.id,
                "name": "Flag 1",
                "key": "flag_1",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]},
                "active": true,
                "deleted": false
            },
            {
                "id": 2,
                "team_id": team.id,
                "name": "Flag 2",
                "key": "flag_2",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 75}]},
                "active": true,
                "deleted": false
            }
        ]);

        // Insert flags in both Redis and Postgres
        insert_flags_for_team_in_redis(
            redis_client.clone(),
            team.id,
            team.project_id,
            Some(flags.to_string()),
        )
        .await
        .expect("Failed to insert flags in Redis");

        for flag in flags.as_array().unwrap() {
            context
                .insert_flag(
                    team.id,
                    Some(FeatureFlagRow {
                        id: 0,
                        team_id: team.id,
                        name: flag["name"].as_str().map(|s| s.to_string()),
                        key: flag["key"].as_str().unwrap().to_string(),
                        filters: flag["filters"].clone(),
                        deleted: false,
                        active: true,
                        ensure_experience_continuity: Some(false),
                        version: Some(1),
                        evaluation_runtime: Some("all".to_string()),
                        evaluation_tags: None,
                    }),
                )
                .await
                .expect("Failed to insert flag in Postgres");
        }

        // Fetch flags from both sources
        let mut redis_flags = FeatureFlagList::from_redis(redis_client, team.project_id)
            .await
            .expect("Failed to fetch flags from Redis");
        let (mut pg_flags, _) =
            FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.project_id)
                .await
                .expect("Failed to fetch flags from Postgres");

        // Sort flags by key to ensure consistent order
        redis_flags.flags.sort_by(|a, b| a.key.cmp(&b.key));
        pg_flags.flags.sort_by(|a, b| a.key.cmp(&b.key));

        // Compare results
        assert_eq!(
            redis_flags.flags.len(),
            pg_flags.flags.len(),
            "Number of flags mismatch"
        );

        for (redis_flag, pg_flag) in redis_flags.flags.iter().zip(pg_flags.flags.iter()) {
            assert_eq!(redis_flag.key, pg_flag.key, "Flag key mismatch");
            assert_eq!(
                redis_flag.name, pg_flag.name,
                "Flag name mismatch for key: {}",
                redis_flag.key
            );
            assert_eq!(
                redis_flag.active, pg_flag.active,
                "Flag active status mismatch for key: {}",
                redis_flag.key
            );
            assert_eq!(
                redis_flag.deleted, pg_flag.deleted,
                "Flag deleted status mismatch for key: {}",
                redis_flag.key
            );
            assert_eq!(
                redis_flag.filters.groups[0].rollout_percentage,
                pg_flag.filters.groups[0].rollout_percentage,
                "Flag rollout percentage mismatch for key: {}",
                redis_flag.key
            );
        }
    }

    #[tokio::test]
    async fn test_rollout_percentage_edge_cases() {
        let redis_client = setup_redis_client(None).await;
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let flags = json!([
            {
                "id": 1,
                "team_id": team.id,
                "name": "0% Rollout",
                "key": "zero_percent",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 0}]},
                "active": true,
                "deleted": false,
                "evaluation_runtime": "all"
            },
            {
                "id": 2,
                "team_id": team.id,
                "name": "100% Rollout",
                "key": "hundred_percent",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "active": true,
                "deleted": false,
                "evaluation_runtime": "all"
            },
            {
                "id": 3,
                "team_id": team.id,
                "name": "Fractional Rollout",
                "key": "fractional_percent",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 33.33}]},
                "active": true,
                "deleted": false,
                "evaluation_runtime": "all"
            }
        ]);

        // Insert flags in both Redis and Postgres
        insert_flags_for_team_in_redis(
            redis_client.clone(),
            team.id,
            team.project_id,
            Some(flags.to_string()),
        )
        .await
        .expect("Failed to insert flags in Redis");

        for flag in flags.as_array().unwrap() {
            context
                .insert_flag(
                    team.id,
                    Some(FeatureFlagRow {
                        id: 0,
                        team_id: team.id,
                        name: flag["name"].as_str().map(|s| s.to_string()),
                        key: flag["key"].as_str().unwrap().to_string(),
                        filters: flag["filters"].clone(),
                        deleted: false,
                        active: true,
                        ensure_experience_continuity: Some(false),
                        version: Some(1),
                        evaluation_runtime: Some("all".to_string()),
                        evaluation_tags: None,
                    }),
                )
                .await
                .expect("Failed to insert flag in Postgres");
        }

        // Fetch flags from both sources
        let redis_flags = FeatureFlagList::from_redis(redis_client, team.project_id)
            .await
            .expect("Failed to fetch flags from Redis");
        let (pg_flags, _) =
            FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.project_id)
                .await
                .expect("Failed to fetch flags from Postgres");

        // Verify rollout percentages
        for flags in &[redis_flags, pg_flags] {
            assert!(flags
                .flags
                .iter()
                .any(|f| f.key == "zero_percent"
                    && f.filters.groups[0].rollout_percentage == Some(0.0)));
            assert!(flags.flags.iter().any(|f| f.key == "hundred_percent"
                && f.filters.groups[0].rollout_percentage == Some(100.0)));
            assert!(flags.flags.iter().any(|f| f.key == "fractional_percent"
                && (f.filters.groups[0].rollout_percentage.unwrap() - 33.33).abs() < f64::EPSILON));
        }
    }

    #[test]
    fn test_empty_filters_deserialization() {
        let empty_filters_json = r#"{
            "id": 1,
            "team_id": 2,
            "name": "Empty Filters Flag",
            "key": "empty_filters",
            "filters": {},
            "deleted": false,
            "active": true,
            "evaluation_runtime": "all"
        }"#;

        let flag: FeatureFlag =
            serde_json::from_str(empty_filters_json).expect("Should deserialize empty filters");

        assert_eq!(flag.filters.groups.len(), 0);
        assert!(flag.filters.multivariate.is_none());
        assert!(flag.filters.aggregation_group_type_index.is_none());
        assert!(flag.filters.payloads.is_none());
        assert!(flag.filters.super_groups.is_none());
        assert!(flag.filters.holdout_groups.is_none());
    }

    #[test]
    fn test_require_db_preparation_if_group_type_index() {
        let mut flag = create_simple_flag(
            vec![create_simple_property_filter(
                "some_property",
                PropertyType::Person,
                OperatorType::Exact,
            )],
            100.0,
        );

        let overrides = HashMap::from([(
            "some_property".to_string(),
            Value::String("value".to_string()),
        )]);

        assert!(flag.get_group_type_index().is_none());
        assert!(!flag.requires_db_preparation(&overrides));

        flag.filters.aggregation_group_type_index = Some(0);

        assert!(flag.get_group_type_index().is_some());
        assert!(flag.requires_db_preparation(&overrides));
    }

    #[test]
    fn test_requires_db_preparation_if_cohort_filter_set() {
        let flag = create_simple_flag(
            vec![create_simple_property_filter(
                "some_property",
                PropertyType::Cohort,
                OperatorType::Exact,
            )],
            100.0,
        );

        // Even though override matches the cohort filter, we still need to prepare the DB
        let overrides = HashMap::from([(
            "some_property".to_string(),
            Value::String("value".to_string()),
        )]);

        assert!(flag.requires_db_preparation(&overrides));
    }

    #[test]
    fn test_requires_db_preparation_if_not_enough_overrides() {
        let flag = create_simple_flag(
            vec![
                create_simple_property_filter(
                    "some_property",
                    PropertyType::Person,
                    OperatorType::Exact,
                ),
                create_simple_property_filter(
                    "another_property",
                    PropertyType::Person,
                    OperatorType::Exact,
                ),
            ],
            1.0,
        );

        {
            let overrides = HashMap::from([
                // Not enough overrides to evaluate locally
                (
                    "some_property".to_string(),
                    Value::String("value".to_string()),
                ),
            ]);
            assert!(flag.requires_db_preparation(&overrides));
        }

        {
            let overrides = HashMap::from([
                (
                    "some_property".to_string(),
                    Value::String("value".to_string()),
                ),
                (
                    "another_property".to_string(),
                    Value::String("value".to_string()),
                ),
            ]);
            assert!(!flag.requires_db_preparation(&overrides));
        }
    }

    #[test]
    fn test_does_not_require_db_preparation_if_holdout_groups_set() {
        let mut flag = create_simple_flag(vec![], 100.0);
        flag.filters.holdout_groups = Some(vec![
            FlagPropertyGroup {
                properties: Some(vec![]),
                variant: Some("holdout-1".to_string()),
                rollout_percentage: Some(10.0),
            },
            // Ignored, but here for testing.
            FlagPropertyGroup {
                properties: Some(vec![create_simple_property_filter(
                    "some_property",
                    PropertyType::Person,
                    OperatorType::Exact,
                )]),
                rollout_percentage: Some(100.0),
                variant: Some("holdout-2".to_string()),
            },
        ]);

        assert!(!flag.requires_db_preparation(&HashMap::new()));
    }
}
