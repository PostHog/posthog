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

/// Team-specific cache-or-fallback helper
async fn team_cache_or_fallback(
    redis_reader: Arc<dyn RedisClient + Send + Sync>,
    redis_writer: Arc<dyn RedisClient + Send + Sync>,
    pg_client: PostgresReader,
    token: &str,
) -> Result<(Team, bool), FlagError> {
    match Team::from_redis(redis_reader, token).await {
        Ok(team) => Ok((team, true)),
        Err(FlagError::TokenValidationError) => {
            // True cache miss - key doesn't exist
            let team = Team::from_pg(pg_client, token).await?;
            inc(DB_TEAM_READS_COUNTER, &[], 1);

            // Write to cache for future hits
            if Team::update_redis_cache(redis_writer, &team).await.is_err() {
                inc(
                    TEAM_CACHE_ERRORS_COUNTER,
                    &[("reason".to_string(), "redis_update_failed".to_string())],
                    1,
                );
            }

            Ok((team, false))
        }
        Err(e) => {
            // Redis timeout, unavailable, or other errors - skip cache write
            tracing::warn!(
                "Redis error reading team: {}, skipping cache write on fallback",
                e
            );
            let team = Team::from_pg(pg_client, token).await?;
            inc(DB_TEAM_READS_COUNTER, &[], 1);
            // Skip cache write to avoid overloading Redis
            Ok((team, false))
        }
    }
}

/// Flags-specific cache-or-fallback helper
async fn flags_cache_or_fallback(
    redis_reader: Arc<dyn RedisClient + Send + Sync>,
    redis_writer: Arc<dyn RedisClient + Send + Sync>,
    pg_client: PostgresReader,
    project_id: i64,
) -> Result<(FeatureFlagList, bool, bool), FlagError> {
    match FeatureFlagList::from_redis(redis_reader, project_id).await {
        Ok(flags) => Ok((flags, true, false)),
        Err(FlagError::TokenValidationError) => {
            // True cache miss - key doesn't exist
            let (flags, had_deserialization_errors) =
                FeatureFlagList::from_pg(pg_client, project_id).await?;
            inc(DB_FLAG_READS_COUNTER, &[], 1);

            // Write to cache for future hits
            if FeatureFlagList::update_flags_in_redis(redis_writer, project_id, &flags)
                .await
                .is_err()
            {
                inc(
                    FLAG_CACHE_ERRORS_COUNTER,
                    &[("reason".to_string(), "redis_update_failed".to_string())],
                    1,
                );
            }

            Ok((flags, false, had_deserialization_errors))
        }
        Err(e) => {
            // Redis timeout, unavailable, or other errors - skip cache write
            tracing::warn!(
                "Redis error reading flags: {}, skipping cache write on fallback",
                e
            );
            let (flags, had_deserialization_errors) =
                FeatureFlagList::from_pg(pg_client, project_id).await?;
            inc(DB_FLAG_READS_COUNTER, &[], 1);
            // Skip cache write to avoid overloading Redis
            Ok((flags, false, had_deserialization_errors))
        }
    }
}

/// Token verification cache-or-fallback helper
async fn token_verification_cache_or_fallback(
    redis_reader: Arc<dyn RedisClient + Send + Sync>,
    redis_writer: Arc<dyn RedisClient + Send + Sync>,
    pg_client: PostgresReader,
    token: &str,
) -> Result<(String, bool), FlagError> {
    match Team::from_redis(redis_reader, token).await {
        Ok(_) => Ok((token.to_string(), true)),
        Err(FlagError::TokenValidationError) => {
            // True cache miss - key doesn't exist
            match Team::from_pg(pg_client, token).await {
                Ok(team) => {
                    inc(DB_TEAM_READS_COUNTER, &[], 1);
                    // Token found in PostgreSQL, update Redis cache so that we can verify it from Redis next time
                    if let Err(e) = Team::update_redis_cache(redis_writer, &team).await {
                        tracing::warn!("Failed to update Redis cache: {}", e);
                        inc(
                            TEAM_CACHE_ERRORS_COUNTER,
                            &[("reason".to_string(), "redis_update_failed".to_string())],
                            1,
                        );
                    }
                    Ok((token.to_string(), false))
                }
                Err(e) => {
                    tracing::warn!("Token validation failed for token '{}': {:?}", token, e);
                    inc(
                        TOKEN_VALIDATION_ERRORS_COUNTER,
                        &[("reason".to_string(), "token_not_found".to_string())],
                        1,
                    );
                    Err(FlagError::TokenValidationError)
                }
            }
        }
        Err(e) => {
            // Redis timeout, unavailable, or other errors - skip cache write
            tracing::warn!(
                "Redis error reading team: {}, skipping cache write on fallback",
                e
            );
            match Team::from_pg(pg_client, token).await {
                Ok(_team) => {
                    inc(DB_TEAM_READS_COUNTER, &[], 1);
                    // Skip cache write to avoid overloading Redis
                    Ok((token.to_string(), false))
                }
                Err(e) => {
                    tracing::warn!("Token validation failed for token '{}': {:?}", token, e);
                    inc(
                        TOKEN_VALIDATION_ERRORS_COUNTER,
                        &[("reason".to_string(), "token_not_found".to_string())],
                        1,
                    );
                    Err(FlagError::TokenValidationError)
                }
            }
        }
    }
}

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
}

impl FlagService {
    pub fn new(
        redis_reader: Arc<dyn RedisClient + Send + Sync>,
        redis_writer: Arc<dyn RedisClient + Send + Sync>,
        pg_client: PostgresReader,
    ) -> Self {
        Self {
            redis_reader,
            redis_writer,
            pg_client,
        }
    }

    /// Verifies the Project API token against the cache or the database.
    /// If the token is not found in the cache, it will be verified against the database,
    /// and the result will be cached in redis (only on true cache misses).
    ///
    /// # Cache Write Behavior
    /// Only writes to cache when the Redis error is TokenValidationError (NotFound).
    /// Skips cache writes for Redis timeouts or unavailability to avoid overloading Redis.
    pub async fn verify_token(&self, token: &str) -> Result<String, FlagError> {
        let (result, cache_hit) = token_verification_cache_or_fallback(
            self.redis_reader.clone(),
            self.redis_writer.clone(),
            self.pg_client.clone(),
            token,
        )
        .await?;

        inc(
            TEAM_CACHE_HIT_COUNTER,
            &[("cache_hit".to_string(), cache_hit.to_string())],
            1,
        );

        Ok(result)
    }

    /// Fetches the team from the cache or the database.
    /// If the team is not found in the cache, it will be fetched from the database and stored in the cache (only on true cache misses).
    /// Returns the team if found, otherwise an error.
    ///
    /// # Cache Write Behavior
    /// Only writes to cache when the Redis error is TokenValidationError (NotFound).
    /// Skips cache writes for Redis timeouts or unavailability to avoid overloading Redis.
    pub async fn get_team_from_cache_or_pg(&self, token: &str) -> Result<Team, FlagError> {
        let (team, cache_hit) = team_cache_or_fallback(
            self.redis_reader.clone(),
            self.redis_writer.clone(),
            self.pg_client.clone(),
            token,
        )
        .await?;

        inc(
            TEAM_CACHE_HIT_COUNTER,
            &[("cache_hit".to_string(), cache_hit.to_string())],
            1,
        );

        Ok(team)
    }

    /// Fetches the flags from the cache or the database. Returns a tuple containing
    /// the flags and a boolean indicating whether there were deserialization errors.
    /// Also tracks cache hits and misses for a given project_id.
    pub async fn get_flags_from_cache_or_pg(
        &self,
        project_id: i64,
    ) -> Result<FlagResult, FlagError> {
        let (flag_list, was_cache_hit, had_deserialization_errors) = flags_cache_or_fallback(
            self.redis_reader.clone(),
            self.redis_writer.clone(),
            self.pg_client.clone(),
            project_id,
        )
        .await?;

        let flag_result = FlagResult {
            flag_list,
            was_cache_hit,
            had_deserialization_errors,
        };

        // Track cache hits and misses
        inc(
            FLAG_CACHE_HIT_COUNTER,
            &[("cache_hit".to_string(), was_cache_hit.to_string())],
            1,
        );

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

        FeatureFlagList::update_flags_in_redis(redis_client.clone(), team.project_id, &mock_flags)
            .await
            .expect("Failed to insert mock flags in Redis");

        let flag_service = FlagService::new(
            redis_client.clone(),
            redis_client.clone(),
            pg_client.clone(),
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

        let flag_service = FlagService::new(reader, writer, context.non_persons_reader.clone());

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

        let flag_service = FlagService::new(reader, writer, context.non_persons_reader.clone());

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
}
