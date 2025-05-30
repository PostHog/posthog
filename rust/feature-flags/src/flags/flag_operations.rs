use crate::api::errors::FlagError;
use crate::cohorts::cohort_models::CohortId;
use crate::flags::flag_models::*;
use crate::properties::property_models::PropertyFilter;
use common_database::Client as DatabaseClient;
use common_redis::Client as RedisClient;
use std::sync::Arc;
use tracing::instrument;

impl PropertyFilter {
    /// Checks if the filter is a cohort filter
    pub fn is_cohort(&self) -> bool {
        self.key == "id" && self.prop_type == "cohort"
    }

    /// Returns the cohort id if the filter is a cohort filter, or None if it's not a cohort filter
    /// or if the value cannot be parsed as a cohort id
    pub fn get_cohort_id(&self) -> Option<CohortId> {
        if !self.is_cohort() {
            return None;
        }
        self.value
            .as_ref()
            .and_then(|value| value.as_i64())
            .map(|id| id as CohortId)
    }
}

impl FeatureFlag {
    pub fn get_group_type_index(&self) -> Option<i32> {
        self.filters.aggregation_group_type_index
    }

    pub fn get_conditions(&self) -> &Vec<FlagPropertyGroup> {
        &self.filters.groups
    }

    pub fn get_variants(&self) -> Vec<MultivariateFlagVariant> {
        self.filters
            .multivariate
            .clone()
            .map_or(vec![], |m| m.variants)
    }

    pub fn get_payload(&self, match_val: &str) -> Option<serde_json::Value> {
        self.filters.payloads.as_ref().and_then(|payloads| {
            payloads
                .as_object()
                .and_then(|obj| obj.get(match_val).cloned())
        })
    }
}

impl FeatureFlagList {
    /// Returns feature flags from redis given a project_id
    #[instrument(skip_all)]
    pub async fn from_redis(
        client: Arc<dyn RedisClient + Send + Sync>,
        project_id: i64,
    ) -> Result<FeatureFlagList, FlagError> {
        tracing::info!(
            "Attempting to read flags from Redis at key '{}{}'",
            TEAM_FLAGS_CACHE_PREFIX,
            project_id
        );

        let serialized_flags = client
            .get(format!("{TEAM_FLAGS_CACHE_PREFIX}{}", project_id))
            .await?;

        let flags_list: Vec<FeatureFlag> =
            serde_json::from_str(&serialized_flags).map_err(|e| {
                tracing::error!("failed to parse data to flags list: {}", e);
                FlagError::RedisDataParsingError
            })?;

        tracing::info!(
            "Successfully read {} flags from Redis at key '{}{}'",
            flags_list.len(),
            TEAM_FLAGS_CACHE_PREFIX,
            project_id
        );

        Ok(FeatureFlagList { flags: flags_list })
    }

    /// Returns feature flags from postgres given a project_id
    #[instrument(skip_all)]
    pub async fn from_pg(
        client: Arc<dyn DatabaseClient + Send + Sync>,
        project_id: i64,
    ) -> Result<FeatureFlagList, FlagError> {
        let mut conn = client.get_connection().await.map_err(|e| {
            tracing::error!("Failed to get database connection: {}", e);
            FlagError::DatabaseUnavailable
        })?;

        let query = r#"
            SELECT f.id,
                  f.team_id,
                  f.name,
                  f.key,
                  f.filters,
                  f.deleted,
                  f.active,
                  f.ensure_experience_continuity,
                  f.version,
                  f.creation_context
              FROM posthog_featureflag AS f
              JOIN posthog_team AS t ON (f.team_id = t.id)
            WHERE t.project_id = $1
              AND f.deleted = false
              AND f.active = true
        "#;
        let flags_row = sqlx::query_as::<_, FeatureFlagRow>(query)
            .bind(project_id)
            .fetch_all(&mut *conn)
            .await
            .map_err(|e| {
                tracing::error!("Failed to fetch feature flags from database: {}", e);
                FlagError::Internal(format!("Database query error: {}", e))
            })?;

        let flags_list = flags_row
            .into_iter()
            .map(|row| {
                let filters = serde_json::from_value(row.filters).map_err(|e| {
                    tracing::error!("Failed to deserialize filters for flag {}: {}", row.key, e);
                    FlagError::DeserializeFiltersError
                })?;

                Ok(FeatureFlag {
                    id: row.id,
                    team_id: row.team_id,
                    name: row.name,
                    key: row.key,
                    filters,
                    deleted: row.deleted,
                    active: row.active,
                    ensure_experience_continuity: row.ensure_experience_continuity,
                    version: row.version,
                    creation_context: row.creation_context,
                })
            })
            .collect::<Result<Vec<FeatureFlag>, FlagError>>()?;

        Ok(FeatureFlagList { flags: flags_list })
    }

    pub async fn update_flags_in_redis(
        client: Arc<dyn RedisClient + Send + Sync>,
        project_id: i64,
        flags: &FeatureFlagList,
    ) -> Result<(), FlagError> {
        let payload = serde_json::to_string(&flags.flags).map_err(|e| {
            tracing::error!("Failed to serialize flags: {}", e);
            FlagError::RedisDataParsingError
        })?;

        tracing::info!(
            "Writing flags to Redis at key '{}{}': {} flags",
            TEAM_FLAGS_CACHE_PREFIX,
            project_id,
            flags.flags.len()
        );

        client
            .set(format!("{TEAM_FLAGS_CACHE_PREFIX}{}", project_id), payload)
            .await
            .map_err(|e| {
                tracing::error!("Failed to update Redis cache: {}", e);
                FlagError::CacheUpdateError
            })?;

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use crate::{flags::flag_models::*, properties::property_models::OperatorType};
    use rand::Rng;
    use serde_json::json;
    use std::time::Instant;
    use tokio::task;

    use super::*;
    use crate::utils::test_utils::{
        insert_flag_for_team_in_pg, insert_flags_for_team_in_redis, insert_new_team_in_pg,
        insert_new_team_in_redis, setup_invalid_pg_client, setup_pg_reader_client,
        setup_redis_client,
    };

    #[tokio::test]
    async fn test_fetch_flags_from_redis() {
        let redis_client = setup_redis_client(None);

        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert team");

        // TODO HANDLE THIS
        insert_flags_for_team_in_redis(redis_client.clone(), team.id, team.project_id, None)
            .await
            .expect("Failed to insert flags");

        let flags_from_redis = FeatureFlagList::from_redis(redis_client.clone(), team.project_id)
            .await
            .expect("Failed to fetch flags from redis");
        assert_eq!(flags_from_redis.flags.len(), 1);
        let flag = flags_from_redis
            .flags
            .first()
            .expect("Empty flags in redis");
        assert_eq!(flag.key, "flag1");
        assert_eq!(flag.team_id, team.id);
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(
            flag.filters.groups[0]
                .properties
                .as_ref()
                .expect("Properties don't exist on flag")
                .len(),
            1
        );
    }

    #[tokio::test]
    async fn test_fetch_invalid_team_from_redis() {
        let redis_client = setup_redis_client(None);

        match FeatureFlagList::from_redis(redis_client.clone(), 1234).await {
            Err(FlagError::TokenValidationError) => (),
            _ => panic!("Expected TokenValidationError"),
        };
    }

    #[tokio::test]
    async fn test_cant_connect_to_redis_error_is_not_token_validation_error() {
        let client = setup_redis_client(Some("redis://localhost:1111/".to_string()));

        match FeatureFlagList::from_redis(client.clone(), 1234).await {
            Err(FlagError::RedisUnavailable) => (),
            _ => panic!("Expected RedisUnavailable"),
        };
    }

    #[tokio::test]
    async fn test_fetch_flags_from_pg() {
        let reader = setup_pg_reader_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
            .await
            .expect("Failed to insert team in pg");

        insert_flag_for_team_in_pg(reader.clone(), team.id, None)
            .await
            .expect("Failed to insert flags");

        let flags_from_pg = FeatureFlagList::from_pg(reader.clone(), team.project_id)
            .await
            .expect("Failed to fetch flags from pg");

        assert_eq!(flags_from_pg.flags.len(), 1);
        let flag = flags_from_pg.flags.first().expect("Flags should be in pg");

        assert_eq!(flag.key, "flag1");
        assert_eq!(flag.team_id, team.id);
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(
            flag.filters.groups[0]
                .properties
                .as_ref()
                .expect("Properties don't exist on flag")
                .len(),
            1
        );
        let property_filter = &flag.filters.groups[0]
            .properties
            .as_ref()
            .expect("Properties don't exist on flag")[0];

        assert_eq!(property_filter.key, "email");
        assert_eq!(property_filter.value, Some(json!("a@b.com")));
        assert_eq!(property_filter.operator, None);
        assert_eq!(property_filter.prop_type, "person");
        assert_eq!(property_filter.group_type_index, None);
        assert_eq!(flag.filters.groups[0].rollout_percentage, Some(50.0));
    }

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
            "ensure_experience_continuity": false
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
        assert!(!flag.ensure_experience_continuity);
    }

    // TODO: Add more tests to validate deserialization of flags.
    // TODO: Also make sure old flag data is handled, or everything is migrated to new style in production

    #[tokio::test]
    async fn test_fetch_empty_team_from_pg() {
        let reader = setup_pg_reader_client(None).await;

        let FeatureFlagList { flags } = FeatureFlagList::from_pg(reader.clone(), 1234)
            .await
            .expect("Failed to fetch flags from pg");
        {
            assert_eq!(flags.len(), 0);
        }
    }

    #[tokio::test]
    async fn test_fetch_nonexistent_team_from_pg() {
        let reader = setup_pg_reader_client(None).await;

        match FeatureFlagList::from_pg(reader.clone(), -1).await {
            Ok(flags) => assert_eq!(flags.flags.len(), 0),
            Err(err) => panic!("Expected empty result, got error: {:?}", err),
        }
    }

    #[tokio::test]
    async fn test_fetch_flags_db_connection_failure() {
        // Simulate a database connection failure by using an invalid client setup
        let invalid_client = setup_invalid_pg_client().await;

        match FeatureFlagList::from_pg(invalid_client, 1).await {
            Err(FlagError::DatabaseUnavailable) => (),
            other => panic!("Expected DatabaseUnavailable error, got: {:?}", other),
        }
    }

    #[tokio::test]
    async fn test_fetch_multiple_flags_from_pg() {
        let reader = setup_pg_reader_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
            .await
            .expect("Failed to insert team in pg");

        let random_id_1 = rand::thread_rng().gen_range(0..10_000_000);
        let random_id_2 = rand::thread_rng().gen_range(0..10_000_000);

        let flag1 = FeatureFlagRow {
            id: random_id_1,
            team_id: team.id,
            name: Some("Test Flag".to_string()),
            key: "test_flag".to_string(),
            filters: serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}),
            deleted: false,
            active: true,
            ensure_experience_continuity: false,
            version: Some(1),
            creation_context: None,
        };

        let flag2 = FeatureFlagRow {
            id: random_id_2,
            team_id: team.id,
            name: Some("Test Flag 2".to_string()),
            key: "test_flag_2".to_string(),
            filters: serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}),
            deleted: false,
            active: true,
            ensure_experience_continuity: false,
            version: Some(1),
            creation_context: None,
        };

        // Insert multiple flags for the team
        insert_flag_for_team_in_pg(reader.clone(), team.id, Some(flag1))
            .await
            .expect("Failed to insert flags");

        insert_flag_for_team_in_pg(reader.clone(), team.id, Some(flag2))
            .await
            .expect("Failed to insert flags");

        let flags_from_pg = FeatureFlagList::from_pg(reader.clone(), team.project_id)
            .await
            .expect("Failed to fetch flags from pg");

        assert_eq!(flags_from_pg.flags.len(), 2);
        for flag in &flags_from_pg.flags {
            assert_eq!(flag.team_id, team.id);
        }
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
            "operator": "{}",
            "type": "person"
        }}"#,
                op_str
            );
            let deserialized: PropertyFilter = serde_json::from_str(&json).unwrap();
            assert_eq!(deserialized.operator, Some(op_type));
        }
    }

    #[tokio::test]
    async fn test_multivariate_flag_parsing() {
        let redis_client = setup_redis_client(None);
        let reader = setup_pg_reader_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
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
            "deleted": false
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
        insert_flag_for_team_in_pg(
            reader.clone(),
            team.id,
            Some(FeatureFlagRow {
                id: 1,
                team_id: team.id,
                name: Some("Multivariate Flag".to_string()),
                key: "multivariate_flag".to_string(),
                filters: multivariate_flag["filters"].clone(),
                deleted: false,
                active: true,
                ensure_experience_continuity: false,
                version: Some(1),
                creation_context: None,
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
        let pg_flags = FeatureFlagList::from_pg(reader, team.project_id)
            .await
            .expect("Failed to fetch flags from Postgres");

        assert_eq!(pg_flags.flags.len(), 1);
        let pg_flag = &pg_flags.flags[0];
        assert_eq!(pg_flag.key, "multivariate_flag");
        assert_eq!(pg_flag.get_variants().len(), 3);
    }

    #[tokio::test]
    async fn test_multivariate_flag_with_payloads() {
        let redis_client = setup_redis_client(None);
        let reader = setup_pg_reader_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
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
        insert_flag_for_team_in_pg(
            reader.clone(),
            team.id,
            Some(FeatureFlagRow {
                id: 1,
                team_id: team.id,
                name: Some("Multivariate Flag with Payloads".to_string()),
                key: "multivariate_flag_with_payloads".to_string(),
                filters: multivariate_flag_with_payloads["filters"].clone(),
                deleted: false,
                active: true,
                ensure_experience_continuity: false,
                version: Some(1),
                creation_context: None,
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
        let pg_flags = FeatureFlagList::from_pg(reader, team.project_id)
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
                    "Incorrect variant name for {} in {}",
                    key,
                    source
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
                    "Incorrect payload value for {} in {}",
                    key, source
                );
            }
        }
    }

    #[tokio::test]
    async fn test_flag_with_super_groups() {
        let redis_client = setup_redis_client(None);
        let reader = setup_pg_reader_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
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
        insert_flag_for_team_in_pg(
            reader.clone(),
            team.id,
            Some(FeatureFlagRow {
                id: 1,
                team_id: team.id,
                name: Some("Flag with Super Groups".to_string()),
                key: "flag_with_super_groups".to_string(),
                filters: flag_with_super_groups["filters"].clone(),
                deleted: false,
                active: true,
                ensure_experience_continuity: false,
                version: Some(1),
                creation_context: None,
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
        let pg_flags = FeatureFlagList::from_pg(reader, team.project_id)
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
        let redis_client = setup_redis_client(None);
        let reader = setup_pg_reader_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
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
                                "key": "purchase",
                                "value": "completed",
                                "type": "event",
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
            Some(json!([flag_with_different_properties]).to_string()),
        )
        .await
        .expect("Failed to insert flag in Redis");

        // Insert into Postgres
        insert_flag_for_team_in_pg(
            reader.clone(),
            team.id,
            Some(FeatureFlagRow {
                id: 1,
                team_id: team.id,
                name: Some("Flag with Different Properties".to_string()),
                key: "flag_with_different_properties".to_string(),
                filters: flag_with_different_properties["filters"].clone(),
                deleted: false,
                active: true,
                ensure_experience_continuity: false,
                version: Some(1),
                creation_context: None,
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
        assert_eq!(redis_properties[0].prop_type, "person");
        assert_eq!(redis_properties[1].prop_type, "group");
        assert_eq!(redis_properties[2].prop_type, "event");

        // Fetch and verify from Postgres
        let pg_flags = FeatureFlagList::from_pg(reader, team.project_id)
            .await
            .expect("Failed to fetch flags from Postgres");

        assert_eq!(pg_flags.flags.len(), 1);
        let pg_flag = &pg_flags.flags[0];
        assert_eq!(pg_flag.key, "flag_with_different_properties");
        let pg_properties = &pg_flag.filters.groups[0].properties.as_ref().unwrap();
        assert_eq!(pg_properties.len(), 3);
        assert_eq!(pg_properties[0].prop_type, "person");
        assert_eq!(pg_properties[1].prop_type, "group");
        assert_eq!(pg_properties[2].prop_type, "event");
    }

    #[tokio::test]
    async fn test_deleted_and_inactive_flags() {
        let redis_client = setup_redis_client(None);
        let reader = setup_pg_reader_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
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

        let inactive_flag = json!({
            "id": 2,
            "team_id": team.id,
            "name": "Inactive Flag",
            "key": "inactive_flag",
            "filters": {"groups": []},
            "active": false,
            "deleted": false
        });

        // Insert into Redis
        insert_flags_for_team_in_redis(
            redis_client.clone(),
            team.id,
            team.project_id,
            Some(json!([deleted_flag, inactive_flag]).to_string()),
        )
        .await
        .expect("Failed to insert flags in Redis");

        // Insert into Postgres
        insert_flag_for_team_in_pg(
            reader.clone(),
            team.id,
            Some(FeatureFlagRow {
                id: 0,
                team_id: team.id,
                name: Some("Deleted Flag".to_string()),
                key: "deleted_flag".to_string(),
                filters: deleted_flag["filters"].clone(),
                deleted: true,
                active: true,
                ensure_experience_continuity: false,
                version: Some(1),
                creation_context: None,
            }),
        )
        .await
        .expect("Failed to insert deleted flag in Postgres");

        insert_flag_for_team_in_pg(
            reader.clone(),
            team.id,
            Some(FeatureFlagRow {
                id: 0,
                team_id: team.id,
                name: Some("Inactive Flag".to_string()),
                key: "inactive_flag".to_string(),
                filters: inactive_flag["filters"].clone(),
                deleted: false,
                active: false,
                ensure_experience_continuity: false,
                version: Some(1),
                creation_context: None,
            }),
        )
        .await
        .expect("Failed to insert inactive flag in Postgres");

        // Fetch and verify from Redis
        let redis_flags = FeatureFlagList::from_redis(redis_client, team.project_id)
            .await
            .expect("Failed to fetch flags from Redis");

        assert_eq!(redis_flags.flags.len(), 2);
        assert!(redis_flags.flags.iter().any(|f| f.deleted));
        assert!(redis_flags
            .flags
            .iter()
            .any(|f| f.key == "inactive_flag" && !f.active));

        // Fetch and verify from Postgres
        let pg_flags = FeatureFlagList::from_pg(reader, team.project_id)
            .await
            .expect("Failed to fetch flags from Postgres");

        assert_eq!(pg_flags.flags.len(), 0);
        assert!(!pg_flags.flags.iter().any(|f| f.deleted)); // no deleted flags
        assert!(!pg_flags.flags.iter().any(|f| f.active)); // no inactive flags
    }

    #[tokio::test]
    async fn test_error_handling() {
        let redis_client = setup_redis_client(Some("redis://localhost:6379/".to_string()));
        let reader = setup_pg_reader_client(None).await;

        // Test Redis connection error
        let bad_redis_client = setup_redis_client(Some("redis://localhost:1111/".to_string()));
        let result = FeatureFlagList::from_redis(bad_redis_client, 1).await;
        assert!(matches!(result, Err(FlagError::RedisUnavailable)));

        // Test malformed JSON in Redis
        let team = insert_new_team_in_pg(reader.clone(), None)
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
            .fetch_all(&mut *reader.get_connection().await.unwrap())
            .await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_concurrent_access() {
        let redis_client = setup_redis_client(None);
        let reader = setup_pg_reader_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
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

        insert_flag_for_team_in_pg(
            reader.clone(),
            team.id,
            Some(FeatureFlagRow {
                id: 0,
                team_id: team.id,
                name: Some("Concurrent Flag".to_string()),
                key: "concurrent_flag".to_string(),
                filters: flag["filters"].clone(),
                deleted: false,
                active: true,
                ensure_experience_continuity: false,
                version: Some(1),
                creation_context: None,
            }),
        )
        .await
        .expect("Failed to insert flag in Postgres");

        let mut handles = vec![];
        for _ in 0..10 {
            let redis_client = redis_client.clone();
            let reader = reader.clone();
            let project_id = team.project_id;

            let handle = task::spawn(async move {
                let redis_flags = FeatureFlagList::from_redis(redis_client, project_id)
                    .await
                    .unwrap();
                let pg_flags = FeatureFlagList::from_pg(reader, project_id).await.unwrap();
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
        let redis_client = setup_redis_client(None);
        let reader = setup_pg_reader_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
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
            insert_flag_for_team_in_pg(
                reader.clone(),
                team.id,
                Some(FeatureFlagRow {
                    id: 0,
                    team_id: team.id,
                    name: Some(flag["name"].as_str().unwrap().to_string()),
                    key: flag["key"].as_str().unwrap().to_string(),
                    filters: flag["filters"].clone(),
                    deleted: false,
                    active: true,
                    ensure_experience_continuity: false,
                    version: Some(1),
                    creation_context: None,
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
        let pg_flags = FeatureFlagList::from_pg(reader, team.project_id)
            .await
            .expect("Failed to fetch flags from Postgres");
        let pg_duration = start.elapsed();

        println!("Redis fetch time: {:?}", redis_duration);
        println!("Postgres fetch time: {:?}", pg_duration);

        assert_eq!(redis_flags.flags.len(), num_flags);
        assert_eq!(pg_flags.flags.len(), num_flags);

        assert!(redis_duration < std::time::Duration::from_millis(100));
        assert!(pg_duration < std::time::Duration::from_millis(1000));
    }

    #[tokio::test]
    async fn test_edge_cases() {
        let redis_client = setup_redis_client(None);
        let reader = setup_pg_reader_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
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
            insert_flag_for_team_in_pg(
                reader.clone(),
                team.id,
                Some(FeatureFlagRow {
                    id: 0,
                    team_id: team.id,
                    name: flag["name"].as_str().map(|s| s.to_string()),
                    key: flag["key"].as_str().unwrap().to_string(),
                    filters: flag["filters"].clone(),
                    deleted: false,
                    active: true,
                    ensure_experience_continuity: false,
                    version: Some(1),
                    creation_context: None,
                }),
            )
            .await
            .expect("Failed to insert edge case flag in Postgres");
        }

        // Fetch and verify edge case flags
        let redis_flags = FeatureFlagList::from_redis(redis_client, team.project_id)
            .await
            .expect("Failed to fetch flags from Redis");
        let pg_flags = FeatureFlagList::from_pg(reader, team.project_id)
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
        let redis_client = setup_redis_client(None);
        let reader = setup_pg_reader_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
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
            insert_flag_for_team_in_pg(
                reader.clone(),
                team.id,
                Some(FeatureFlagRow {
                    id: 0,
                    team_id: team.id,
                    name: flag["name"].as_str().map(|s| s.to_string()),
                    key: flag["key"].as_str().unwrap().to_string(),
                    filters: flag["filters"].clone(),
                    deleted: false,
                    active: true,
                    ensure_experience_continuity: false,
                    version: Some(1),
                    creation_context: None,
                }),
            )
            .await
            .expect("Failed to insert flag in Postgres");
        }

        // Fetch flags from both sources
        let mut redis_flags = FeatureFlagList::from_redis(redis_client, team.project_id)
            .await
            .expect("Failed to fetch flags from Redis");
        let mut pg_flags = FeatureFlagList::from_pg(reader, team.project_id)
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
        let redis_client = setup_redis_client(None);
        let reader = setup_pg_reader_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
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
                "deleted": false
            },
            {
                "id": 2,
                "team_id": team.id,
                "name": "100% Rollout",
                "key": "hundred_percent",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "active": true,
                "deleted": false
            },
            {
                "id": 3,
                "team_id": team.id,
                "name": "Fractional Rollout",
                "key": "fractional_percent",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 33.33}]},
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
            insert_flag_for_team_in_pg(
                reader.clone(),
                team.id,
                Some(FeatureFlagRow {
                    id: 0,
                    team_id: team.id,
                    name: flag["name"].as_str().map(|s| s.to_string()),
                    key: flag["key"].as_str().unwrap().to_string(),
                    filters: flag["filters"].clone(),
                    deleted: false,
                    active: true,
                    ensure_experience_continuity: false,
                    version: Some(1),
                    creation_context: None,
                }),
            )
            .await
            .expect("Failed to insert flag in Postgres");
        }

        // Fetch flags from both sources
        let redis_flags = FeatureFlagList::from_redis(redis_client, team.project_id)
            .await
            .expect("Failed to fetch flags from Redis");
        let pg_flags = FeatureFlagList::from_pg(reader, team.project_id)
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
            "active": true
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
}
