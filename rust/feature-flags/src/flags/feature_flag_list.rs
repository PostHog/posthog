use crate::metrics::consts::TOMBSTONE_COUNTER;
use metrics::counter;

use crate::api::errors::FlagError;
use crate::database::get_connection_with_metrics;
use crate::flags::flag_models::{
    FeatureFlag, FeatureFlagList, FeatureFlagRow, HypercacheFlagsWrapper,
};
use common_database::PostgresReader;
use common_hypercache::HYPER_CACHE_EMPTY_VALUE;
use common_types::TeamId;

impl FeatureFlagList {
    pub fn new(flags: Vec<FeatureFlag>) -> Self {
        Self { flags }
    }

    /// Parses a JSON Value from hypercache into a list of feature flags.
    ///
    /// Handles:
    /// - Null values (returns empty vec)
    /// - Sentinel "__missing__" value (returns empty vec)
    /// - Standard hypercache format `{"flags": [...]}`
    pub fn parse_hypercache_value(
        data: serde_json::Value,
        team_id: TeamId,
    ) -> Result<Vec<FeatureFlag>, FlagError> {
        // Handle null (can happen when hypercache returns empty)
        if data.is_null() {
            return Ok(vec![]);
        }

        // Check for the sentinel value indicating no flags for this team
        if data.as_str() == Some(HYPER_CACHE_EMPTY_VALUE) {
            tracing::debug!("Hypercache sentinel (no flags) for team {}", team_id);
            return Ok(vec![]);
        }

        // Parse the hypercache format: {"flags": [...]}
        let wrapper: HypercacheFlagsWrapper =
            serde_json::from_value(data.clone()).map_err(|e| {
                tracing::error!(
                    "Failed to parse hypercache data for team {}: {}. Data: {}",
                    team_id,
                    e,
                    &data.to_string()[..data.to_string().len().min(200)]
                );
                counter!(
                    TOMBSTONE_COUNTER,
                    "failure_type" => "hypercache_parse_error",
                    "team_id" => team_id.to_string(),
                )
                .increment(1);
                FlagError::RedisDataParsingError
            })?;

        tracing::debug!("Parsed {} flags for team {}", wrapper.flags.len(), team_id);

        Ok(wrapper.flags)
    }

    /// Returns feature flags from postgres given a team_id
    pub async fn from_pg(
        client: PostgresReader,
        team_id: TeamId,
    ) -> Result<Vec<FeatureFlag>, FlagError> {
        let mut conn = get_connection_with_metrics(&client, "non_persons_reader", "fetch_flags")
            .await
            .map_err(|e| {
                tracing::error!(
                    "Failed to get database connection for team {}: {}",
                    team_id,
                    e
                );
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
                  f.evaluation_runtime,
                  COALESCE(
                      ARRAY_AGG(tag.name) FILTER (WHERE tag.name IS NOT NULL),
                      '{}'::text[]
                  ) AS evaluation_tags,
                  bucketing_identifier
              FROM posthog_featureflag AS f
              JOIN posthog_team AS t ON (f.team_id = t.id)
              -- Evaluation tags are distinct from organizational tags. This bridge table links
              -- flags to tags that constrain runtime evaluation. We use LEFT JOIN to retain flags
              -- with zero evaluation tags, so ARRAY_AGG(...) returns an empty array rather than
              -- dropping the flag row entirely.
              LEFT JOIN posthog_featureflagevaluationtag AS et ON (f.id = et.feature_flag_id)
              -- Only fetch names for tags that are evaluation constraints (not all org tags)
              LEFT JOIN posthog_tag AS tag ON (et.tag_id = tag.id)
            WHERE t.id = $1
              AND f.deleted = false
            GROUP BY f.id, f.team_id, f.name, f.key, f.filters, f.deleted, f.active, 
                     f.ensure_experience_continuity, f.version, f.evaluation_runtime
        "#;
        let flags_row = sqlx::query_as::<_, FeatureFlagRow>(query)
            .bind(team_id)
            .fetch_all(&mut *conn)
            .await
            .map_err(|e| {
                tracing::error!(
                    "Failed to fetch feature flags from database for team {}: {}",
                    team_id,
                    e
                );
                FlagError::Internal(format!("Database query error: {e}"))
            })?;

        let flags: Vec<FeatureFlag> = flags_row
            .into_iter()
            .filter_map(|row| {
                match serde_json::from_value(row.filters) {
                    Ok(filters) => Some(FeatureFlag {
                        id: row.id,
                        team_id: row.team_id,
                        name: row.name,
                        key: row.key,
                        filters,
                        deleted: row.deleted,
                        active: row.active,
                        ensure_experience_continuity: row.ensure_experience_continuity,
                        version: row.version,
                        evaluation_runtime: row.evaluation_runtime,
                        evaluation_tags: row.evaluation_tags,
                        bucketing_identifier: row.bucketing_identifier,
                    }),
                    Err(e) => {
                        // This is highly unlikely to happen, but if it does, we skip the flag.
                        tracing::warn!(
                            "Failed to deserialize filters for flag {} in team {}: {}",
                            row.key,
                            row.team_id,
                            e
                        );
                        // Also track as a tombstone - invalid data in postgres should never happen
                        // Details (team_id, flag_key) are logged above to avoid high-cardinality labels
                        counter!(
                            TOMBSTONE_COUNTER,
                            "namespace" => "feature_flags",
                            "operation" => "flag_filter_deserialization_error",
                            "component" => "feature_flag_list",
                        )
                        .increment(1);

                        None // Skip this flag, continue with others
                    }
                }
            })
            .collect();

        tracing::debug!(
            "Successfully fetched {} flags from database for team {}",
            flags.len(),
            team_id
        );

        Ok(flags)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        flags::test_helpers::get_flags_from_redis,
        utils::test_utils::{
            insert_flags_for_team_in_redis, insert_new_team_in_redis, setup_invalid_pg_client,
            setup_redis_client, TestContext,
        },
    };
    use rand::Rng;

    #[tokio::test]
    async fn test_fetch_flags_from_redis() {
        let redis_client = setup_redis_client(None).await;

        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert team");

        insert_flags_for_team_in_redis(redis_client.clone(), team.id, None)
            .await
            .expect("Failed to insert flags");

        let flags_from_redis = get_flags_from_redis(redis_client.clone(), team.id)
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
        assert_eq!(flag.filters.groups[0].properties.as_ref().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn test_fetch_invalid_team_from_redis() {
        let redis_client = setup_redis_client(None).await;

        match get_flags_from_redis(redis_client.clone(), 1234).await {
            Err(FlagError::TokenValidationError) => {
                // Expected error
            }
            _ => panic!("Expected TokenValidationError"),
        }
    }

    #[tokio::test]
    #[should_panic(expected = "Failed to create redis client")]
    async fn test_cant_connect_to_redis_error_is_not_token_validation_error() {
        // Test that client creation fails when Redis is unavailable
        setup_redis_client(Some("redis://localhost:1111/".to_string())).await;
    }

    #[tokio::test]
    async fn test_fetch_flags_from_pg() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        context
            .insert_flag(team.id, None)
            .await
            .expect("Failed to insert flag");

        let flags_from_pg = FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.id)
            .await
            .expect("Failed to fetch flags from pg");

        assert_eq!(flags_from_pg.len(), 1);
        let flag = flags_from_pg.first().expect("Flags should be in pg");
        assert_eq!(flag.key, "flag1");
        assert_eq!(flag.team_id, team.id);
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(flag.filters.groups[0].properties.as_ref().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn test_fetch_empty_team_from_pg() {
        let context = TestContext::new(None).await;

        let flags = FeatureFlagList::from_pg(context.non_persons_reader.clone(), 1234)
            .await
            .expect("Failed to fetch flags from pg");

        assert_eq!(flags.len(), 0);
    }

    #[tokio::test]
    async fn test_fetch_nonexistent_team_from_pg() {
        let context = TestContext::new(None).await;

        match FeatureFlagList::from_pg(context.non_persons_reader.clone(), -1).await {
            Ok(flags) => assert_eq!(flags.len(), 0),
            Err(err) => panic!("Expected empty result, got error: {err:?}"),
        }
    }

    #[tokio::test]
    async fn test_fetch_flags_db_connection_failure() {
        let invalid_client = setup_invalid_pg_client().await;

        match FeatureFlagList::from_pg(invalid_client, 1).await {
            Ok(_) => panic!("Expected error for invalid database connection"),
            Err(FlagError::DatabaseUnavailable) => {
                // Expected error
            }
            Err(e) => panic!("Unexpected error: {e:?}"),
        }
    }

    #[tokio::test]
    async fn test_fetch_multiple_flags_from_pg() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        let random_id_1 = rand::thread_rng().gen_range(1_000_000..100_000_000);
        let random_id_2 = rand::thread_rng().gen_range(1_000_000..100_000_000);

        let flag1 = FeatureFlagRow {
            id: random_id_1,
            team_id: team.id,
            name: Some("Test Flag".to_string()),
            key: "test_flag".to_string(),
            filters: serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}),
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: None,
        };

        let flag2 = FeatureFlagRow {
            id: random_id_2,
            team_id: team.id,
            name: Some("Test Flag 2".to_string()),
            key: "test_flag_2".to_string(),
            filters: serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}),
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: None,
        };

        // Insert multiple flags for the team
        context
            .insert_flag(team.id, Some(flag1))
            .await
            .expect("Failed to insert flags");

        context
            .insert_flag(team.id, Some(flag2))
            .await
            .expect("Failed to insert flags");

        let flags_from_pg = FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.id)
            .await
            .expect("Failed to fetch flags from pg");

        assert_eq!(flags_from_pg.len(), 2);
        for flag in &flags_from_pg {
            assert_eq!(flag.team_id, team.id);
        }
    }

    #[tokio::test]
    async fn test_fetch_flags_with_evaluation_tags_from_pg() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        let flag_row = context
            .insert_flag(team.id, None)
            .await
            .expect("Failed to insert flag");

        // Insert evaluation tags for the flag
        context
            .insert_evaluation_tags_for_flag(
                flag_row.id,
                team.id,
                vec!["docs-page", "marketing-site", "app"],
            )
            .await
            .expect("Failed to insert evaluation tags");

        let flags_from_pg = FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.id)
            .await
            .expect("Failed to fetch flags from pg");

        assert_eq!(flags_from_pg.len(), 1);
        let flag = flags_from_pg.first().expect("Should have one flag");
        assert_eq!(flag.key, "flag1");
        assert_eq!(flag.team_id, team.id);

        // Check that evaluation tags were properly fetched
        let tags = flag
            .evaluation_tags
            .as_ref()
            .expect("Should have evaluation tags");
        assert_eq!(tags.len(), 3);
        assert!(tags.contains(&"docs-page".to_string()));
        assert!(tags.contains(&"marketing-site".to_string()));
        assert!(tags.contains(&"app".to_string()));
    }

    #[test]
    fn test_cache_format_backward_compatibility() {
        // This test verifies that the cache format (Vec<FeatureFlag>) remains stable.
        // We cache Vec<FeatureFlag> directly, and any format change would invalidate
        // all existing cache entries, causing a thundering herd of database queries.
        use crate::flags::flag_models::{FeatureFlag, FlagFilters};

        // Create test flags in the format we cache
        let cached_flags = vec![FeatureFlag {
            id: 1,
            team_id: 123,
            name: Some("Test Flag".to_string()),
            key: "test_flag".to_string(),
            filters: FlagFilters::default(),
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: None,
        }];

        // Serialize as we do in production cache
        let cached_json =
            serde_json::to_string(&cached_flags).expect("Failed to serialize flags for cache");

        // Verify we can deserialize it back (cache read path)
        let result = serde_json::from_str::<Vec<FeatureFlag>>(&cached_json);

        assert!(
            result.is_ok(),
            "FAILED: Cannot deserialize cached flags. This indicates a cache format change \
             that will invalidate all existing cache entries, causing thundering herd. \
             Cached JSON: {}\nError: {:?}",
            cached_json,
            result.unwrap_err()
        );

        // Verify the deserialized data is correct
        let deserialized_flags = result.unwrap();
        assert_eq!(deserialized_flags.len(), 1);
        assert_eq!(deserialized_flags[0].key, "test_flag");
        assert_eq!(deserialized_flags[0].id, 1);
    }

    // =========================================================================
    // Tests for parse_hypercache_value()
    // =========================================================================

    use serde_json::json;

    #[test]
    fn test_parse_hypercache_value_valid_flags() {
        let data = json!({
            "flags": [
                {
                    "id": 1,
                    "key": "test_flag",
                    "team_id": 123,
                    "active": true,
                    "deleted": false,
                    "filters": { "groups": [] }
                },
                {
                    "id": 2,
                    "key": "another_flag",
                    "team_id": 123,
                    "active": false,
                    "deleted": false,
                    "filters": { "groups": [] }
                }
            ]
        });

        let result = FeatureFlagList::parse_hypercache_value(data, 123);
        assert!(result.is_ok());
        let flags = result.unwrap();
        assert_eq!(flags.len(), 2);
        assert_eq!(flags[0].key, "test_flag");
        assert!(flags[0].active);
        assert_eq!(flags[1].key, "another_flag");
        assert!(!flags[1].active);
    }

    #[test]
    fn test_parse_hypercache_value_null_returns_empty() {
        let data = serde_json::Value::Null;
        let result = FeatureFlagList::parse_hypercache_value(data, 123);
        assert!(result.is_ok());
        assert!(result.unwrap().is_empty());
    }

    #[test]
    fn test_parse_hypercache_value_sentinel_returns_empty() {
        let data = json!("__missing__");
        let result = FeatureFlagList::parse_hypercache_value(data, 123);
        assert!(result.is_ok());
        assert!(result.unwrap().is_empty());
    }

    #[test]
    fn test_parse_hypercache_value_empty_flags_array() {
        let data = json!({"flags": []});
        let result = FeatureFlagList::parse_hypercache_value(data, 123);
        assert!(result.is_ok());
        assert!(result.unwrap().is_empty());
    }

    #[test]
    fn test_parse_hypercache_value_missing_flags_wrapper() {
        // Data is an array instead of {"flags": [...]} wrapper
        let data = json!([{"id": 1, "key": "test"}]);
        let result = FeatureFlagList::parse_hypercache_value(data, 123);
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));
    }

    #[test]
    fn test_parse_hypercache_value_invalid_json_structure() {
        // Data has wrong structure - flags is not an array
        let data = json!({"flags": "not an array"});
        let result = FeatureFlagList::parse_hypercache_value(data, 123);
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));
    }

    #[test]
    fn test_parse_hypercache_value_invalid_flag_fields() {
        // Missing required fields in flag
        let data = json!({
            "flags": [
                {
                    "id": 1
                    // missing required fields: key, team_id, active, deleted, filters
                }
            ]
        });
        let result = FeatureFlagList::parse_hypercache_value(data, 123);
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));
    }

    #[test]
    fn test_parse_hypercache_value_with_all_optional_fields() {
        let data = json!({
            "flags": [
                {
                    "id": 42,
                    "key": "full_flag",
                    "team_id": 123,
                    "name": "Full Feature Flag",
                    "active": true,
                    "deleted": false,
                    "filters": {
                        "groups": [{
                            "properties": [{
                                "key": "email",
                                "value": "test@test.com",
                                "type": "person",
                                "operator": "exact"
                            }],
                            "rollout_percentage": 50
                        }]
                    },
                    "ensure_experience_continuity": true,
                    "version": 5,
                    "evaluation_runtime": "frontend"
                }
            ]
        });

        let result = FeatureFlagList::parse_hypercache_value(data, 123);
        assert!(result.is_ok());
        let flags = result.unwrap();
        assert_eq!(flags.len(), 1);
        let flag = &flags[0];
        assert_eq!(flag.id, 42);
        assert_eq!(flag.key, "full_flag");
        assert_eq!(flag.name, Some("Full Feature Flag".to_string()));
        assert_eq!(flag.ensure_experience_continuity, Some(true));
        assert_eq!(flag.version, Some(5));
        assert_eq!(flag.evaluation_runtime, Some("frontend".to_string()));
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(flag.filters.groups[0].rollout_percentage, Some(50.0));
    }

    #[test]
    fn test_parse_hypercache_value_random_string_is_not_sentinel() {
        // A random string that's not the sentinel should fail parsing
        let data = json!("some_random_string");
        let result = FeatureFlagList::parse_hypercache_value(data, 123);
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));
    }

    #[test]
    fn test_parse_hypercache_value_empty_object() {
        // Empty object (no flags key)
        let data = json!({});
        let result = FeatureFlagList::parse_hypercache_value(data, 123);
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));
    }
}
