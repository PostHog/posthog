use crate::{
    api::errors::FlagError,
    flags::{
        flag_models::FeatureFlagList, flags_cache::flags_get_or_load, team_cache::team_get_or_load,
    },
    team::team_models::Team,
};
use common_database::PostgresReader;
use common_redis::Client as RedisClient;
use std::sync::Arc;

/// Result of fetching feature flags, including cache hit status and deserialization errors status
#[derive(Debug, Clone)]
pub struct FlagResult {
    pub flag_list: FeatureFlagList,
    pub was_cache_hit: bool,
    pub had_deserialization_errors: bool,
}

/// Service layer for handling feature flag operations
pub struct FlagService {
    redis_reader: Arc<dyn RedisClient + Send + Sync>,
    redis_writer: Arc<dyn RedisClient + Send + Sync>,
    pg_client: PostgresReader,
    team_token_cache: Arc<common_cache::ReadThroughCache>,
    flags_cache_ttl_seconds: u64,
}

impl FlagService {
    pub fn new(
        redis_reader: Arc<dyn RedisClient + Send + Sync>,
        redis_writer: Arc<dyn RedisClient + Send + Sync>,
        pg_client: PostgresReader,
        team_token_cache: Arc<common_cache::ReadThroughCache>,
        flags_cache_ttl_seconds: u64,
    ) -> Self {
        Self {
            redis_reader,
            redis_writer,
            pg_client,
            team_token_cache,
            flags_cache_ttl_seconds,
        }
    }

    /// Fetches the team from the cache or the database.
    /// If the team is not found in the cache, it will be fetched from the database and stored in the cache (only on true cache misses).
    /// Returns the team if found, otherwise an error.
    ///
    /// # Cache Write Behavior
    /// Only writes to cache when the Redis error is TokenValidationError (NotFound).
    /// Skips cache writes for Redis timeouts or unavailability to avoid overloading Redis.
    pub async fn get_team_from_cache_or_pg(&self, token: &str) -> Result<Team, FlagError> {
        let (team, _cache_hit) =
            team_get_or_load(self.team_token_cache.clone(), self.pg_client.clone(), token).await?;

        Ok(team)
    }

    /// Fetches the flags from the cache or the database. Returns a tuple containing
    /// the flags and a boolean indicating whether there were deserialization errors.
    /// Also tracks cache hits and misses for a given project_id.
    pub async fn get_flags_from_cache_or_pg(
        &self,
        project_id: i64,
    ) -> Result<FlagResult, FlagError> {
        let (flag_list, was_cache_hit, had_deserialization_errors) = flags_get_or_load(
            self.redis_reader.clone(),
            self.redis_writer.clone(),
            self.pg_client.clone(),
            project_id,
            Some(self.flags_cache_ttl_seconds),
            None, // TODO: Add negative cache to prevent repeated DB queries for non-existent projects. Should be passed from State/router.
        )
        .await?;

        let flag_result = FlagResult {
            flag_list,
            was_cache_hit,
            had_deserialization_errors,
        };

        Ok(flag_result)
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use crate::{
        flags::flag_models::{
            FeatureFlag, FlagFilters, FlagPropertyGroup, TEAM_FLAGS_CACHE_PREFIX,
        },
        properties::property_models::{OperatorType, PropertyFilter, PropertyType},
        team::team_models::TEAM_TOKEN_CACHE_PREFIX,
        utils::test_utils::{
            insert_new_team_in_redis, setup_pg_reader_client, setup_redis_client, TestContext,
        },
    };
    use common_cache::{CacheConfig, ReadThroughCache};

    use super::*;

    /// Helper function to create a team token cache for testing
    fn create_team_token_cache(
        redis_client: Arc<dyn RedisClient + Send + Sync>,
        ttl_seconds: Option<u64>,
    ) -> Arc<ReadThroughCache> {
        let cache_config = CacheConfig::new("posthog:1:team_token:", ttl_seconds);
        Arc::new(ReadThroughCache::new(
            redis_client.clone(),
            redis_client.clone(),
            cache_config,
            None, // no negative cache for tests
        ))
    }

    #[tokio::test]
    async fn test_get_team_from_cache_or_pg() {
        let redis_client = setup_redis_client(None).await;
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in database");

        // Also insert the team in Redis cache
        Team::update_redis_cache(redis_client.clone(), &team, None)
            .await
            .expect("Failed to insert team in Redis cache");

        let team_token_cache = create_team_token_cache(redis_client.clone(), Some(432000));
        let flag_service = FlagService::new(
            redis_client.clone(),
            redis_client.clone(),
            context.non_persons_reader.clone(),
            team_token_cache,
            432000, // flags_cache_ttl_seconds
        );

        // Test fetching from Redis
        let result = flag_service
            .get_team_from_cache_or_pg(&team.api_token)
            .await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap().id, team.id);

        // Test fetching from PostgreSQL (simulate Redis miss)
        // First, remove the team from Redis
        redis_client
            .del(format!("{TEAM_TOKEN_CACHE_PREFIX}{}", team.api_token))
            .await
            .expect("Failed to remove team from Redis");

        let team_token_cache = create_team_token_cache(redis_client.clone(), Some(432000));
        let flag_service = FlagService::new(
            redis_client.clone(),
            redis_client.clone(),
            context.non_persons_reader.clone(),
            team_token_cache,
            432000, // flags_cache_ttl_seconds
        );

        let result = flag_service
            .get_team_from_cache_or_pg(&team.api_token)
            .await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap().id, team.id);

        // Verify that the team was re-added to Redis
        let redis_team = Team::from_redis(redis_client.clone(), &team.api_token).await;
        assert!(redis_team.is_ok());
    }

    #[tokio::test]
    async fn test_get_flags_from_cache_or_pg() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        // Insert some mock flags into Redis
        let mock_flags = FeatureFlagList {
            flags: vec![
                FeatureFlag {
                    id: 1,
                    team_id: team.id,
                    name: Some("Beta Feature".to_string()),
                    key: "beta_feature".to_string(),
                    filters: FlagFilters {
                        groups: vec![FlagPropertyGroup {
                            properties: Some(vec![PropertyFilter {
                                key: "country".to_string(),
                                value: Some(json!("US")),
                                operator: Some(OperatorType::Exact),
                                prop_type: PropertyType::Person,
                                group_type_index: None,
                                negation: None,
                            }]),
                            rollout_percentage: Some(50.0),
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
                    version: Some(1),
                    evaluation_runtime: Some("all".to_string()),
                    evaluation_tags: None,
                },
                FeatureFlag {
                    id: 2,
                    team_id: team.id,
                    name: Some("New User Interface".to_string()),
                    key: "new_ui".to_string(),
                    filters: FlagFilters {
                        groups: vec![],
                        multivariate: None,
                        aggregation_group_type_index: None,
                        payloads: None,
                        super_groups: None,
                        holdout_groups: None,
                    },
                    deleted: false,
                    active: false,
                    ensure_experience_continuity: Some(false),
                    version: Some(1),
                    evaluation_runtime: Some("all".to_string()),
                    evaluation_tags: None,
                },
                FeatureFlag {
                    id: 3,
                    team_id: team.id,
                    name: Some("Premium Feature".to_string()),
                    key: "premium_feature".to_string(),
                    filters: FlagFilters {
                        groups: vec![FlagPropertyGroup {
                            properties: Some(vec![PropertyFilter {
                                key: "is_premium".to_string(),
                                value: Some(json!(true)),
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
                    },
                    deleted: false,
                    active: true,
                    ensure_experience_continuity: Some(false),
                    version: Some(1),
                    evaluation_runtime: Some("all".to_string()),
                    evaluation_tags: None,
                },
            ],
        };

        FeatureFlagList::update_flags_in_redis(
            redis_client.clone(),
            team.project_id,
            &mock_flags,
            None,
        )
        .await
        .expect("Failed to insert mock flags in Redis");

        let team_token_cache = create_team_token_cache(redis_client.clone(), Some(432000));
        let flag_service = FlagService::new(
            redis_client.clone(),
            redis_client.clone(),
            pg_client.clone(),
            team_token_cache,
            432000, // flags_cache_ttl_seconds
        );

        // Test fetching from Redis
        let result = flag_service
            .get_flags_from_cache_or_pg(team.project_id)
            .await;
        assert!(result.is_ok());
        let flag_result = result.unwrap();
        assert_eq!(flag_result.flag_list.flags.len(), mock_flags.flags.len());

        // Verify the contents of the fetched flags
        let beta_feature = flag_result
            .flag_list
            .flags
            .iter()
            .find(|f| f.key == "beta_feature")
            .unwrap();
        assert!(beta_feature.active);
        assert_eq!(
            beta_feature.filters.groups[0].rollout_percentage,
            Some(50.0)
        );
        assert_eq!(
            beta_feature.filters.groups[0].properties.as_ref().unwrap()[0].key,
            "country"
        );

        let new_ui = flag_result
            .flag_list
            .flags
            .iter()
            .find(|f| f.key == "new_ui")
            .unwrap();
        assert!(!new_ui.active);
        assert!(new_ui.filters.groups.is_empty());

        let premium_feature = flag_result
            .flag_list
            .flags
            .iter()
            .find(|f| f.key == "premium_feature")
            .unwrap();
        assert!(premium_feature.active);
        assert_eq!(
            premium_feature.filters.groups[0].rollout_percentage,
            Some(100.0)
        );
        assert_eq!(
            premium_feature.filters.groups[0]
                .properties
                .as_ref()
                .unwrap()[0]
                .key,
            "is_premium"
        );

        // Test fetching from PostgreSQL (simulate Redis miss)
        // First, remove the flags from Redis
        redis_client
            .del(format!("{}:{}", TEAM_FLAGS_CACHE_PREFIX, team.id))
            .await
            .expect("Failed to remove flags from Redis");

        let result = flag_service
            .get_flags_from_cache_or_pg(team.project_id)
            .await;
        assert!(result.is_ok());
        // Verify that the flags were re-added to Redis
        let redis_flags = FeatureFlagList::from_redis(redis_client.clone(), team.project_id).await;
        assert!(redis_flags.is_ok());
        assert_eq!(redis_flags.unwrap().flags.len(), mock_flags.flags.len());
    }

    #[tokio::test]
    async fn test_get_flags_from_cache_or_pg_skips_cache_write_on_redis_timeout() {
        use common_redis::{CustomRedisError, MockRedisClient};

        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Set up mock redis_reader to return Timeout
        let mut mock_reader = MockRedisClient::new();
        mock_reader.get_ret(
            &format!("{TEAM_FLAGS_CACHE_PREFIX}{}", team.project_id),
            Err(CustomRedisError::Timeout),
        );

        // Set up mock redis_writer to track SET calls
        let mock_writer = MockRedisClient::new();

        let reader: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_reader.clone());
        let writer: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_writer.clone());

        let team_token_cache = create_team_token_cache(reader.clone(), Some(432000));
        let flag_service = FlagService::new(
            reader,
            writer,
            context.non_persons_reader.clone(),
            team_token_cache,
            432000, // flags_cache_ttl_seconds
        );

        let result = flag_service
            .get_flags_from_cache_or_pg(team.project_id)
            .await;

        // Should succeed despite Redis timeout
        assert!(result.is_ok());
        let flag_result = result.unwrap();
        assert!(!flag_result.was_cache_hit);

        // Verify SET was NOT called (cache write was skipped)
        let writer_calls = mock_writer.get_calls();
        assert!(
            !writer_calls.iter().any(|call| call.op == "set"),
            "Expected SET to NOT be called for Timeout error, but it was"
        );
    }

    #[tokio::test]
    async fn test_get_flags_from_cache_or_pg_skips_cache_write_on_redis_unavailable() {
        use common_redis::{CustomRedisError, MockRedisClient};

        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Set up mock redis_reader to return Other error (maps to RedisUnavailable)
        let mut mock_reader = MockRedisClient::new();
        mock_reader.get_ret(
            &format!("{TEAM_FLAGS_CACHE_PREFIX}{}", team.project_id),
            Err(CustomRedisError::Other("Connection refused".to_string())),
        );

        // Set up mock redis_writer to track SET calls
        let mock_writer = MockRedisClient::new();

        let reader: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_reader.clone());
        let writer: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_writer.clone());

        let team_token_cache = create_team_token_cache(reader.clone(), Some(432000));
        let flag_service = FlagService::new(
            reader,
            writer,
            context.non_persons_reader.clone(),
            team_token_cache,
            432000, // flags_cache_ttl_seconds
        );

        let result = flag_service
            .get_flags_from_cache_or_pg(team.project_id)
            .await;

        // Should succeed despite Redis being unavailable
        assert!(result.is_ok());
        let flag_result = result.unwrap();
        assert!(!flag_result.was_cache_hit);

        // Verify SET was NOT called (cache write was skipped)
        let writer_calls = mock_writer.get_calls();
        assert!(
            !writer_calls.iter().any(|call| call.op == "set"),
            "Expected SET to NOT be called for RedisUnavailable error, but it was"
        );
    }

    // Note: The test_config_ttl_values_are_used test was removed because
    // it tested implementation details that changed when we moved cache creation
    // outside of FlagService. TTL values are now configured when creating the
    // ReadThroughCache instances in State.
}
