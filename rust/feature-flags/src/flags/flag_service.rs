use crate::{
    api::errors::FlagError,
    flags::flag_models::FeatureFlagList,
    metrics::consts::{
        DB_TEAM_READS_COUNTER, TEAM_CACHE_HIT_COUNTER, TOKEN_VALIDATION_ERRORS_COUNTER,
    },
    team::team_models::Team,
};
use common_database::PostgresReader;
use common_hypercache::{CacheSource, HyperCacheReader, KeyType};
use common_metrics::inc;
use common_redis::Client as RedisClient;
use common_types::TeamId;
use std::sync::Arc;

/// Result of fetching feature flags, including cache hit status
#[derive(Debug, Clone)]
pub struct FlagResult {
    pub flag_list: FeatureFlagList,
    pub was_cache_hit: bool,
}

/// Service layer for handling feature flag operations
pub struct FlagService {
    /// Shared Redis client (kept for potential future use)
    _shared_redis_client: Arc<dyn RedisClient + Send + Sync>,
    pg_client: PostgresReader,
    /// HyperCache reader for fetching flags from Redis/S3
    flags_hypercache_reader: HyperCacheReader,
    /// HyperCache reader for fetching team metadata from Redis/S3
    team_hypercache_reader: HyperCacheReader,
}

impl FlagService {
    pub fn new(
        shared_redis_client: Arc<dyn RedisClient + Send + Sync>,
        pg_client: PostgresReader,
        flags_hypercache_reader: HyperCacheReader,
        team_hypercache_reader: HyperCacheReader,
    ) -> Self {
        Self {
            _shared_redis_client: shared_redis_client,
            pg_client,
            flags_hypercache_reader,
            team_hypercache_reader,
        }
    }

    /// Verifies the Project API token against the cache or the database.
    /// If the token is not found in the cache, it will be verified against the database,
    /// and the result will be cached in redis.
    pub async fn verify_token(&self, token: &str) -> Result<String, FlagError> {
        match self.get_team_from_cache_or_pg(token).await {
            Ok(_) => Ok(token.to_string()),
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

    /// Fetches the team from HyperCache or the database.
    ///
    /// Uses team_metadata HyperCache (Redis → S3 → PostgreSQL fallback).
    /// This is a read-only cache - Django handles cache writes.
    pub async fn get_team_from_cache_or_pg(&self, token: &str) -> Result<Team, FlagError> {
        let key = KeyType::string(token);
        let pg_client = self.pg_client.clone();
        let token_owned = token.to_string();

        let (data, source) = self
            .team_hypercache_reader
            .get_with_source_or_fallback(&key, || async move {
                // Fallback: load from PostgreSQL and convert to JSON Value
                let team = Team::from_pg(pg_client, &token_owned).await?;
                inc(DB_TEAM_READS_COUNTER, &[], 1);

                // Convert team to JSON value for consistency with cache format
                let value = serde_json::to_value(&team).map_err(|e| {
                    tracing::error!("Failed to serialize team from PG: {}", e);
                    FlagError::Internal(format!("Failed to serialize team: {e}"))
                })?;
                Ok::<Option<serde_json::Value>, FlagError>(Some(value))
            })
            .await?;

        // Parse the result (from cache or fallback)
        let team = Team::from_hypercache_value(data)?;
        let cache_hit = !matches!(source, CacheSource::Fallback);

        inc(
            TEAM_CACHE_HIT_COUNTER,
            &[("cache_hit".to_string(), cache_hit.to_string())],
            1,
        );

        Ok(team)
    }

    /// Fetches the flags from the hypercache or falls back to the database.
    ///
    /// Uses HyperCacheReader's built-in fallback pattern which:
    /// - Tries Redis first
    /// - Falls back to S3 on Redis miss
    /// - Falls back to PostgreSQL if both cache tiers miss
    /// - Emits appropriate metrics for all scenarios
    pub async fn get_flags_from_cache_or_pg(
        &self,
        team_id: TeamId,
    ) -> Result<FlagResult, FlagError> {
        let key = KeyType::int(team_id);
        let pg_client = self.pg_client.clone();

        let (data, source) = self
            .flags_hypercache_reader
            .get_with_source_or_fallback(&key, || async move {
                // Fallback: load from PostgreSQL and convert to JSON Value
                let flags = FeatureFlagList::from_pg(pg_client, team_id).await?;
                let wrapper = crate::flags::flag_models::HypercacheFlagsWrapper { flags };
                let value = serde_json::to_value(&wrapper).map_err(|e| {
                    tracing::error!(
                        "Failed to serialize flags from PG for team {}: {}",
                        team_id,
                        e
                    );
                    FlagError::Internal(format!("Failed to serialize flags: {e}"))
                })?;
                Ok::<Option<serde_json::Value>, FlagError>(Some(value))
            })
            .await?;

        // Parse the result (from cache or fallback)
        let flags = FeatureFlagList::parse_hypercache_value(data, team_id)?;
        let was_cache_hit = !matches!(source, CacheSource::Fallback);

        Ok(FlagResult {
            flag_list: FeatureFlagList { flags },
            was_cache_hit,
        })
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use crate::{
        flags::{
            flag_models::{FeatureFlag, FlagFilters, FlagPropertyGroup},
            test_helpers::update_flags_in_hypercache,
        },
        properties::property_models::{OperatorType, PropertyFilter, PropertyType},
        utils::test_utils::{
            insert_new_team_in_redis, setup_hypercache_reader,
            setup_hypercache_reader_with_mock_redis, setup_pg_reader_client, setup_redis_client,
            setup_team_hypercache_reader, TestContext,
        },
    };

    /// Generate the Django-compatible hypercache key for test mocks
    /// Format: posthog:1:cache/teams/{team_id}/feature_flags/flags.json
    fn hypercache_test_key(team_id: TeamId) -> String {
        format!("posthog:1:cache/teams/{team_id}/feature_flags/flags.json")
    }

    use super::*;

    #[tokio::test]
    async fn test_verify_token() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None).await;
        let flags_hypercache_reader = setup_hypercache_reader(redis_client.clone()).await;
        let team_hypercache_reader = setup_team_hypercache_reader(redis_client.clone()).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        let flag_service = FlagService::new(
            redis_client.clone(),
            pg_client.clone(),
            flags_hypercache_reader,
            team_hypercache_reader,
        );

        // Test valid token in HyperCache
        let result = flag_service.verify_token(&team.api_token).await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), team.api_token);

        // Test invalid token
        let result = flag_service.verify_token("invalid_token").await;
        assert!(matches!(result, Err(FlagError::TokenValidationError)));
    }

    #[tokio::test]
    async fn test_get_team_from_cache_or_pg() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None).await;
        let flags_hypercache_reader = setup_hypercache_reader(redis_client.clone()).await;
        let team_hypercache_reader = setup_team_hypercache_reader(redis_client.clone()).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        let flag_service = FlagService::new(
            redis_client.clone(),
            pg_client.clone(),
            flags_hypercache_reader,
            team_hypercache_reader,
        );

        // Test fetching from HyperCache
        let result = flag_service
            .get_team_from_cache_or_pg(&team.api_token)
            .await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap().id, team.id);
    }

    #[tokio::test]
    async fn test_get_team_from_pg_fallback() {
        let redis_client = setup_redis_client(None).await;
        let flags_hypercache_reader = setup_hypercache_reader(redis_client.clone()).await;
        let team_hypercache_reader = setup_team_hypercache_reader(redis_client.clone()).await;

        // Insert a team in PG but not in HyperCache
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let flag_service = FlagService::new(
            redis_client.clone(),
            context.non_persons_reader.clone(),
            flags_hypercache_reader,
            team_hypercache_reader,
        );

        // Test fetching from PostgreSQL (cache miss)
        let result = flag_service
            .get_team_from_cache_or_pg(&team.api_token)
            .await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap().id, team.id);
    }

    #[tokio::test]
    async fn test_get_flags_from_hypercache() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        // Insert some mock flags into hypercache (new format)
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

        // Write to hypercache (new format: {"flags": [...]})
        update_flags_in_hypercache(redis_client.clone(), team.id, &mock_flags, None)
            .await
            .expect("Failed to insert mock flags in hypercache");

        let flags_hypercache_reader = setup_hypercache_reader(redis_client.clone()).await;
        let team_hypercache_reader = setup_team_hypercache_reader(redis_client.clone()).await;
        let flag_service = FlagService::new(
            redis_client.clone(),
            pg_client.clone(),
            flags_hypercache_reader,
            team_hypercache_reader,
        );

        // Test fetching from hypercache
        let result = flag_service.get_flags_from_cache_or_pg(team.id).await;
        assert!(result.is_ok());
        let flag_result = result.unwrap();
        assert!(flag_result.was_cache_hit);
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
    }

    #[tokio::test]
    async fn test_get_flags_falls_back_to_pg_on_hypercache_miss() {
        let redis_client = setup_redis_client(None).await;
        let flags_hypercache_reader = setup_hypercache_reader(redis_client.clone()).await;
        let team_hypercache_reader = setup_team_hypercache_reader(redis_client.clone()).await;
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Don't populate hypercache - should fall back to PG

        let flag_service = FlagService::new(
            redis_client.clone(),
            context.non_persons_reader.clone(),
            flags_hypercache_reader,
            team_hypercache_reader,
        );

        // Should fall back to PostgreSQL and succeed (returns empty list for new team)
        let result = flag_service.get_flags_from_cache_or_pg(team.id).await;
        assert!(result.is_ok());
        let flag_result = result.unwrap();
        assert!(!flag_result.was_cache_hit);
    }

    #[tokio::test]
    async fn test_get_flags_falls_back_to_pg_on_redis_timeout() {
        use common_redis::{CustomRedisError, MockRedisClient};

        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Set up mock redis client to return Timeout on read
        let mut mock_client = MockRedisClient::new();
        mock_client.get_ret(
            &hypercache_test_key(team.id),
            Err(CustomRedisError::Timeout),
        );

        let redis_client: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_client.clone());
        let flags_hypercache_reader = setup_hypercache_reader_with_mock_redis(redis_client.clone());
        // Use a real Redis client for team hypercache since we're only mocking flags cache
        let team_redis_client = setup_redis_client(None).await;
        let team_hypercache_reader = setup_team_hypercache_reader(team_redis_client).await;

        let flag_service = FlagService::new(
            redis_client,
            context.non_persons_reader.clone(),
            flags_hypercache_reader,
            team_hypercache_reader,
        );

        let result = flag_service.get_flags_from_cache_or_pg(team.id).await;

        // Should succeed by falling back to PostgreSQL
        assert!(result.is_ok());
        let flag_result = result.unwrap();
        assert!(!flag_result.was_cache_hit);
    }

    #[tokio::test]
    async fn test_get_flags_falls_back_to_pg_on_redis_unavailable() {
        use common_redis::{CustomRedisError, MockRedisClient, RedisErrorKind};

        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Set up mock redis client to return Redis error (maps to RedisUnavailable)
        let mut mock_client = MockRedisClient::new();
        mock_client.get_ret(
            &hypercache_test_key(team.id),
            Err(CustomRedisError::from_redis_kind(
                RedisErrorKind::IoError,
                "Connection refused",
            )),
        );

        let redis_client: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_client.clone());
        let flags_hypercache_reader = setup_hypercache_reader_with_mock_redis(redis_client.clone());
        // Use a real Redis client for team hypercache since we're only mocking flags cache
        let team_redis_client = setup_redis_client(None).await;
        let team_hypercache_reader = setup_team_hypercache_reader(team_redis_client).await;

        let flag_service = FlagService::new(
            redis_client,
            context.non_persons_reader.clone(),
            flags_hypercache_reader,
            team_hypercache_reader,
        );

        let result = flag_service.get_flags_from_cache_or_pg(team.id).await;

        // Should succeed by falling back to PostgreSQL
        assert!(result.is_ok());
        let flag_result = result.unwrap();
        assert!(!flag_result.was_cache_hit);
    }
}
