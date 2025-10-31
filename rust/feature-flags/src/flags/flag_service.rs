use crate::{
    api::errors::FlagError,
    flags::flag_models::FeatureFlagList,
    metrics::consts::{
        DB_FLAG_READS_COUNTER, DB_TEAM_READS_COUNTER, FLAG_CACHE_ERRORS_COUNTER,
        FLAG_CACHE_HIT_COUNTER, TEAM_CACHE_ERRORS_COUNTER, TEAM_CACHE_HIT_COUNTER,
        TOKEN_VALIDATION_ERRORS_COUNTER,
    },
    team::team_models::Team,
};
use common_database::PostgresReader;
use common_metrics::inc;
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
    team_cache_ttl_seconds: u64,
    flags_cache_ttl_seconds: u64,
}

impl FlagService {
    pub fn new(
        redis_reader: Arc<dyn RedisClient + Send + Sync>,
        redis_writer: Arc<dyn RedisClient + Send + Sync>,
        pg_client: PostgresReader,
        team_cache_ttl_seconds: u64,
        flags_cache_ttl_seconds: u64,
    ) -> Self {
        Self {
            redis_reader,
            redis_writer,
            pg_client,
            team_cache_ttl_seconds,
            flags_cache_ttl_seconds,
        }
    }

    /// Verifies the Project API token against the cache or the database.
    /// If the token is not found in the cache, it will be verified against the database,
    /// and the result will be cached in redis.
    pub async fn verify_token(&self, token: &str) -> Result<String, FlagError> {
        let (result, cache_hit) = match Team::from_redis(self.redis_reader.clone(), token).await {
            Ok(_) => (Ok(token.to_string()), true),
            Err(_) => {
                match Team::from_pg(self.pg_client.clone(), token).await {
                    Ok(team) => {
                        inc(DB_TEAM_READS_COUNTER, &[], 1);
                        // Token found in PostgreSQL, update Redis cache so that we can verify it from Redis next time
                        if let Err(e) = Team::update_redis_cache(
                            self.redis_writer.clone(),
                            &team,
                            Some(self.team_cache_ttl_seconds),
                        )
                        .await
                        {
                            tracing::warn!("Failed to update Redis cache: {}", e);
                            inc(
                                TEAM_CACHE_ERRORS_COUNTER,
                                &[("reason".to_string(), "redis_update_failed".to_string())],
                                1,
                            );
                        }
                        (Ok(token.to_string()), false)
                    }
                    Err(e) => {
                        tracing::warn!("Token validation failed for token '{}': {:?}", token, e);
                        inc(
                            TOKEN_VALIDATION_ERRORS_COUNTER,
                            &[("reason".to_string(), "token_not_found".to_string())],
                            1,
                        );
                        (Err(FlagError::TokenValidationError), false)
                    }
                }
            }
        };

        inc(
            TEAM_CACHE_HIT_COUNTER,
            &[("cache_hit".to_string(), cache_hit.to_string())],
            1,
        );

        result
    }

    /// Fetches the team from the cache or the database.
    /// If the team is not found in the cache, it will be fetched from the database and stored in the cache.
    /// Returns the team if found, otherwise an error.
    pub async fn get_team_from_cache_or_pg(&self, token: &str) -> Result<Team, FlagError> {
        let (team_result, cache_hit) =
            match Team::from_redis(self.redis_reader.clone(), token).await {
                Ok(team) => (Ok(team), true),
                Err(_) => match Team::from_pg(self.pg_client.clone(), token).await {
                    Ok(team) => {
                        inc(DB_TEAM_READS_COUNTER, &[], 1);
                        // If we have the team in postgres, but not redis, update redis so we're faster next time
                        if Team::update_redis_cache(
                            self.redis_writer.clone(),
                            &team,
                            Some(self.team_cache_ttl_seconds),
                        )
                        .await
                        .is_err()
                        {
                            inc(
                                TEAM_CACHE_ERRORS_COUNTER,
                                &[("reason".to_string(), "redis_update_failed".to_string())],
                                1,
                            );
                        }
                        (Ok(team), false)
                    }
                    // TODO what kind of error should we return here?
                    Err(e) => (Err(e), false),
                },
            };

        inc(
            TEAM_CACHE_HIT_COUNTER,
            &[("cache_hit".to_string(), cache_hit.to_string())],
            1,
        );

        team_result
    }

    /// Fetches the flags from the cache or the database. Returns a tuple containing
    /// the flags and a boolean indicating whether there were deserialization errors.
    /// Also tracks cache hits and misses for a given project_id.
    pub async fn get_flags_from_cache_or_pg(
        &self,
        project_id: i64,
    ) -> Result<FlagResult, FlagError> {
        let flag_result = match FeatureFlagList::from_redis(self.redis_reader.clone(), project_id)
            .await
        {
            Ok(flags_from_redis) => Ok(FlagResult {
                flag_list: flags_from_redis,
                was_cache_hit: true,
                had_deserialization_errors: false,
            }),
            Err(_) => match FeatureFlagList::from_pg(self.pg_client.clone(), project_id).await {
                Ok((flags_from_pg, had_deserialization_errors)) => {
                    inc(DB_FLAG_READS_COUNTER, &[], 1);
                    if (FeatureFlagList::update_flags_in_redis(
                        self.redis_writer.clone(),
                        project_id,
                        &flags_from_pg,
                        Some(self.flags_cache_ttl_seconds),
                    )
                    .await)
                        .is_err()
                    {
                        inc(
                            FLAG_CACHE_ERRORS_COUNTER,
                            &[("reason".to_string(), "redis_update_failed".to_string())],
                            1,
                        );
                    }
                    Ok(FlagResult {
                        flag_list: flags_from_pg,
                        was_cache_hit: false,
                        had_deserialization_errors,
                    })
                }
                Err(database_error) => Err(database_error),
            },
        };

        // Track cache hits and misses
        if let Ok(ref result) = flag_result {
            inc(
                FLAG_CACHE_HIT_COUNTER,
                &[("cache_hit".to_string(), result.was_cache_hit.to_string())],
                1,
            );
        }

        flag_result
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
        utils::test_utils::{
            insert_new_team_in_redis, setup_pg_reader_client, setup_redis_client, TestContext,
        },
    };

    use super::*;

    #[tokio::test]
    async fn test_verify_token() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        let flag_service = FlagService::new(
            redis_client.clone(),
            redis_client.clone(),
            pg_client.clone(),
            432000, // team_cache_ttl_seconds
            432000, // flags_cache_ttl_seconds
        );

        // Test valid token in Redis
        let result = flag_service.verify_token(&team.api_token).await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), team.api_token);

        // Test valid token in PostgreSQL (simulate Redis miss)
        // First, remove the team from Redis
        redis_client
            .del(format!("team:{}", team.api_token))
            .await
            .expect("Failed to remove team from Redis");

        let result = flag_service.verify_token(&team.api_token).await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), team.api_token);

        // Test invalid token
        let result = flag_service.verify_token("invalid_token").await;
        assert!(matches!(result, Err(FlagError::TokenValidationError)));

        // Verify that the team was re-added to Redis after PostgreSQL hit
        let redis_team = Team::from_redis(redis_client.clone(), &team.api_token).await;
        assert!(redis_team.is_ok());
    }

    #[tokio::test]
    async fn test_get_team_from_cache_or_pg() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        let flag_service = FlagService::new(
            redis_client.clone(),
            redis_client.clone(),
            pg_client.clone(),
            432000, // team_cache_ttl_seconds
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
            .del(format!("team:{}", team.api_token))
            .await
            .expect("Failed to remove team from Redis");

        let flag_service = FlagService::new(
            redis_client.clone(),
            redis_client.clone(),
            pg_client.clone(),
            432000, // team_cache_ttl_seconds
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

        let flag_service = FlagService::new(
            redis_client.clone(),
            redis_client.clone(),
            pg_client.clone(),
            432000, // team_cache_ttl_seconds
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

        let flag_service = FlagService::new(
            reader,
            writer,
            context.non_persons_reader.clone(),
            432000, // team_cache_ttl_seconds
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

        let flag_service = FlagService::new(
            reader,
            writer,
            context.non_persons_reader.clone(),
            432000, // team_cache_ttl_seconds
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

    #[tokio::test]
    async fn test_config_ttl_values_are_used() {
        use common_redis::{CustomRedisError, MockRedisClient, MockRedisValue};

        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Set up mock redis_reader to return NotFound (cache miss)
        let mut mock_reader = MockRedisClient::new();
        mock_reader.get_ret(&team.api_token, Err(CustomRedisError::NotFound));

        // Set up mock redis_writer to track setex calls
        let mock_writer = MockRedisClient::new();

        let reader: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_reader.clone());
        let writer: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_writer.clone());

        // Test with custom TTL values (different from default 432000)
        let custom_team_ttl = 7200u64; // 2 hours
        let custom_flags_ttl = 1800u64; // 30 minutes

        let flag_service = FlagService::new(
            reader,
            writer,
            context.non_persons_reader.clone(),
            custom_team_ttl,
            custom_flags_ttl,
        );

        // Trigger team cache operation
        let _result = flag_service
            .get_team_from_cache_or_pg(&team.api_token)
            .await;

        // Verify setex was called with the custom team TTL
        let writer_calls = mock_writer.get_calls();
        let setex_calls: Vec<_> = writer_calls
            .iter()
            .filter(|call| call.op == "setex")
            .collect();

        assert!(!setex_calls.is_empty(), "Expected setex to be called");

        // Verify the TTL value used matches our custom config
        let team_setex_call = setex_calls
            .iter()
            .find(|call| call.key.contains(&team.api_token))
            .expect("Expected setex call for team token");

        if let MockRedisValue::StringWithTTL(_, ttl) = &team_setex_call.value {
            assert_eq!(
                *ttl, custom_team_ttl,
                "Expected team cache TTL to be {custom_team_ttl} but got {ttl}",
            );
        } else {
            panic!("Expected setex call to have TTL value");
        }
    }
}
