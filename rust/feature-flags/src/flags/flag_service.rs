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
use axum::async_trait;
use common_database::PostgresReader;
use common_metrics::inc;
use common_redis::Client as RedisClient;
use std::sync::Arc;

/// Trait that abstracts cache and database operations for the cache-or-fallback pattern
#[async_trait]
pub trait CacheOrFallback<K: ?Sized, R> {
    /// Fetch from Redis cache
    async fn from_cache(
        redis_reader: Arc<dyn RedisClient + Send + Sync>,
        key: &K,
    ) -> Result<R, FlagError>;

    /// Fetch from PostgreSQL database
    async fn from_database(pg_client: PostgresReader, key: &K) -> Result<R, FlagError>;

    /// Update Redis cache with the result
    async fn update_cache(
        redis_writer: Arc<dyn RedisClient + Send + Sync>,
        key: &K,
        result: &R,
    ) -> Result<(), FlagError>;
}

/// Metrics configuration for cache operations
#[derive(Clone)]
pub struct CacheMetrics {
    pub db_reads_counter: &'static str,
    pub cache_errors_counter: &'static str,
}

/// Generic cache-or-fallback implementation that handles Redis cache misses and errors
async fn cache_or_fallback<T, K, R>(
    redis_reader: Arc<dyn RedisClient + Send + Sync>,
    redis_writer: Arc<dyn RedisClient + Send + Sync>,
    pg_client: PostgresReader,
    key: &K,
    metrics: CacheMetrics,
) -> Result<(R, bool), FlagError>
where
    T: CacheOrFallback<K, R>,
    K: Send + Sync + ?Sized,
    R: Send + Sync,
{
    match T::from_cache(redis_reader, key).await {
        Ok(result) => Ok((result, true)),
        Err(FlagError::TokenValidationError) => {
            // True cache miss - key doesn't exist
            let result = T::from_database(pg_client, key).await?;
            inc(metrics.db_reads_counter, &[], 1);

            // Write to cache for future hits
            if T::update_cache(redis_writer, key, &result).await.is_err() {
                inc(
                    metrics.cache_errors_counter,
                    &[("reason".to_string(), "redis_update_failed".to_string())],
                    1,
                );
            }

            Ok((result, false))
        }
        Err(e) => {
            // Redis timeout, unavailable, or other errors - skip cache write
            tracing::warn!("Redis error: {}, skipping cache write on fallback", e);

            match T::from_database(pg_client, key).await {
                Ok(result) => {
                    inc(metrics.db_reads_counter, &[], 1);
                    // Skip cache write to avoid overloading Redis
                    Ok((result, false))
                }
                Err(db_error) => {
                    // Let the caller handle validation vs infrastructure error distinction
                    // and appropriate metrics/logging based on context
                    Err(db_error)
                }
            }
        }
    }
}

/// Team cache operations
pub struct TeamCache;

#[async_trait]
impl CacheOrFallback<str, Team> for TeamCache {
    async fn from_cache(
        redis_reader: Arc<dyn RedisClient + Send + Sync>,
        token: &str,
    ) -> Result<Team, FlagError> {
        Team::from_redis(redis_reader, token).await
    }

    async fn from_database(pg_client: PostgresReader, token: &str) -> Result<Team, FlagError> {
        Team::from_pg(pg_client, token).await
    }

    async fn update_cache(
        redis_writer: Arc<dyn RedisClient + Send + Sync>,
        _token: &str,
        team: &Team,
    ) -> Result<(), FlagError> {
        Team::update_redis_cache(redis_writer, team).await
    }
}

/// Flags cache operations
pub struct FlagsCache;

#[async_trait]
impl CacheOrFallback<i64, (FeatureFlagList, bool)> for FlagsCache {
    async fn from_cache(
        redis_reader: Arc<dyn RedisClient + Send + Sync>,
        project_id: &i64,
    ) -> Result<(FeatureFlagList, bool), FlagError> {
        let flags = FeatureFlagList::from_redis(redis_reader, *project_id).await?;
        Ok((flags, false)) // No deserialization errors from cache
    }

    async fn from_database(
        pg_client: PostgresReader,
        project_id: &i64,
    ) -> Result<(FeatureFlagList, bool), FlagError> {
        FeatureFlagList::from_pg(pg_client, *project_id).await
    }

    async fn update_cache(
        redis_writer: Arc<dyn RedisClient + Send + Sync>,
        project_id: &i64,
        result: &(FeatureFlagList, bool),
    ) -> Result<(), FlagError> {
        FeatureFlagList::update_flags_in_redis(redis_writer, *project_id, &result.0).await
    }
}

/// Token verification cache operations
pub struct TokenVerificationCache;

#[async_trait]
impl CacheOrFallback<str, (Team, String)> for TokenVerificationCache {
    async fn from_cache(
        redis_reader: Arc<dyn RedisClient + Send + Sync>,
        token: &str,
    ) -> Result<(Team, String), FlagError> {
        let team = Team::from_redis(redis_reader, token).await?;
        Ok((team, token.to_string()))
    }

    async fn from_database(
        pg_client: PostgresReader,
        token: &str,
    ) -> Result<(Team, String), FlagError> {
        match Team::from_pg(pg_client, token).await {
            Ok(team) => Ok((team, token.to_string())),
            Err(FlagError::RowNotFound) => {
                // Token doesn't exist in database - this is a legitimate validation error
                tracing::debug!("Token '{}' not found in database", token);
                inc(
                    TOKEN_VALIDATION_ERRORS_COUNTER,
                    &[("reason".to_string(), "token_not_found".to_string())],
                    1,
                );
                Err(FlagError::TokenValidationError)
            }
            Err(e) => {
                // Database availability issues (timeouts, unavailable, etc.) should propagate
                // as-is rather than being masked as authentication failures
                tracing::warn!(
                    "Database error during token verification for token '{}': {:?}",
                    token,
                    e
                );
                Err(e)
            }
        }
    }

    async fn update_cache(
        redis_writer: Arc<dyn RedisClient + Send + Sync>,
        _token: &str,
        result: &(Team, String),
    ) -> Result<(), FlagError> {
        Team::update_redis_cache(redis_writer, &result.0).await
    }
}

/// Team-specific cache-or-fallback helper
async fn team_cache_or_fallback(
    redis_reader: Arc<dyn RedisClient + Send + Sync>,
    redis_writer: Arc<dyn RedisClient + Send + Sync>,
    pg_client: PostgresReader,
    token: &str,
) -> Result<(Team, bool), FlagError> {
    cache_or_fallback::<TeamCache, str, Team>(
        redis_reader,
        redis_writer,
        pg_client,
        token,
        CacheMetrics {
            db_reads_counter: DB_TEAM_READS_COUNTER,
            cache_errors_counter: TEAM_CACHE_ERRORS_COUNTER,
        },
    )
    .await
}

/// Flags-specific cache-or-fallback helper
async fn flags_cache_or_fallback(
    redis_reader: Arc<dyn RedisClient + Send + Sync>,
    redis_writer: Arc<dyn RedisClient + Send + Sync>,
    pg_client: PostgresReader,
    project_id: i64,
) -> Result<(FeatureFlagList, bool, bool), FlagError> {
    let ((flags, had_deserialization_errors), was_cache_hit) =
        cache_or_fallback::<FlagsCache, i64, (FeatureFlagList, bool)>(
            redis_reader,
            redis_writer,
            pg_client,
            &project_id,
            CacheMetrics {
                db_reads_counter: DB_FLAG_READS_COUNTER,
                cache_errors_counter: FLAG_CACHE_ERRORS_COUNTER,
            },
        )
        .await?;
    Ok((flags, was_cache_hit, had_deserialization_errors))
}

/// Token verification cache-or-fallback helper
async fn token_verification_cache_or_fallback(
    redis_reader: Arc<dyn RedisClient + Send + Sync>,
    redis_writer: Arc<dyn RedisClient + Send + Sync>,
    pg_client: PostgresReader,
    token: &str,
) -> Result<(String, bool), FlagError> {
    let ((_team, token_string), was_cache_hit) =
        cache_or_fallback::<TokenVerificationCache, str, (Team, String)>(
            redis_reader,
            redis_writer,
            pg_client,
            token,
            CacheMetrics {
                db_reads_counter: DB_TEAM_READS_COUNTER,
                cache_errors_counter: TEAM_CACHE_ERRORS_COUNTER,
            },
        )
        .await?;
    Ok((token_string, was_cache_hit))
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

    #[tokio::test]
    async fn test_verify_token_database_errors_not_masked_as_auth_failures() {
        // This test documents that database availability errors should NOT be converted
        // to TokenValidationError. Only RowNotFound should be converted.

        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None).await;

        let flag_service = FlagService::new(
            redis_client.clone(),
            redis_client.clone(),
            pg_client.clone(),
        );

        // Test 1: Non-existent token should return TokenValidationError (RowNotFound case)
        let result = flag_service.verify_token("definitely_does_not_exist").await;
        assert!(matches!(result, Err(FlagError::TokenValidationError)));

        // Note: Testing actual database timeout/unavailability scenarios would require
        // either mocking the database or creating unreliable timeout conditions.
        // The behavior is now documented: only FlagError::RowNotFound gets converted
        // to TokenValidationError, while DatabaseError, DatabaseUnavailable, and
        // TimeoutError propagate as-is for proper 503 responses.
    }
}
