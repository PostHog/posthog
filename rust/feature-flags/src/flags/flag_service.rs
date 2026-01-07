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

/// Result of fetching feature flags, including cache source information.
#[derive(Debug, Clone)]
pub struct FlagResult {
    pub flag_list: FeatureFlagList,
    /// The source of the flags data (Redis, S3, or Fallback/PostgreSQL).
    pub cache_source: common_hypercache::CacheSource,
}

/// Service layer for handling feature flag operations
pub struct FlagService {
    /// Shared Redis client for non-critical path operations
    /// Reserved for future use (analytics counters, billing limits, etc.)
    #[allow(dead_code)]
    shared_redis_client: Arc<dyn RedisClient + Send + Sync>,
    pg_client: PostgresReader,
    /// HyperCache reader for fetching team metadata from Redis/S3
    team_hypercache_reader: Arc<HyperCacheReader>,
    /// HyperCache reader for fetching flags from Redis/S3
    /// Arc-wrapped to allow sharing across requests
    flags_hypercache_reader: Arc<HyperCacheReader>,
}

impl FlagService {
    pub fn new(
        shared_redis_client: Arc<dyn RedisClient + Send + Sync>,
        pg_client: PostgresReader,
        team_hypercache_reader: Arc<HyperCacheReader>,
        flags_hypercache_reader: Arc<HyperCacheReader>,
    ) -> Self {
        Self {
            shared_redis_client,
            pg_client,
            team_hypercache_reader,
            flags_hypercache_reader,
        }
    }

    /// Verifies the Project API token against HyperCache or the database.
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

        Ok(FlagResult {
            flag_list: FeatureFlagList { flags },
            cache_source: source,
        })
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use crate::{
        flags::{
            flag_models::{FeatureFlag, FlagFilters, FlagPropertyGroup, HypercacheFlagsWrapper},
            test_helpers::{hypercache_test_key, update_flags_in_hypercache},
        },
        properties::property_models::{OperatorType, PropertyFilter, PropertyType},
        utils::test_utils::{
            insert_new_team_in_redis, setup_hypercache_reader,
            setup_hypercache_reader_with_mock_redis, setup_pg_reader_client, setup_redis_client,
            setup_team_hypercache_reader, TestContext,
        },
    };

    use super::*;

    #[tokio::test]
    async fn test_verify_token() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None).await;
        let team_hypercache_reader = setup_team_hypercache_reader(redis_client.clone()).await;
        let hypercache_reader = setup_hypercache_reader(redis_client.clone()).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        let flag_service = FlagService::new(
            redis_client.clone(),
            pg_client.clone(),
            team_hypercache_reader,
            hypercache_reader,
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
        let team_hypercache_reader = setup_team_hypercache_reader(redis_client.clone()).await;
        let hypercache_reader = setup_hypercache_reader(redis_client.clone()).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        let flag_service = FlagService::new(
            redis_client.clone(),
            pg_client.clone(),
            team_hypercache_reader,
            hypercache_reader,
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
        let team_hypercache_reader = setup_team_hypercache_reader(redis_client.clone()).await;
        let hypercache_reader = setup_hypercache_reader(redis_client.clone()).await;

        // Insert a team in PG but not in HyperCache
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let flag_service = FlagService::new(
            redis_client.clone(),
            context.non_persons_reader.clone(),
            team_hypercache_reader,
            hypercache_reader,
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
                    bucketing_identifier: None,
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
                    bucketing_identifier: None,
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
                    bucketing_identifier: None,
                },
            ],
        };

        // Write to hypercache (new format: {"flags": [...]})
        update_flags_in_hypercache(redis_client.clone(), team.id, &mock_flags, None)
            .await
            .expect("Failed to insert mock flags in hypercache");

        let team_hypercache_reader = setup_team_hypercache_reader(redis_client.clone()).await;
        let hypercache_reader = setup_hypercache_reader(redis_client.clone()).await;
        let flag_service = FlagService::new(
            redis_client.clone(),
            pg_client.clone(),
            team_hypercache_reader,
            hypercache_reader,
        );

        // Test fetching from hypercache
        let result = flag_service.get_flags_from_cache_or_pg(team.id).await;
        assert!(result.is_ok());
        let flag_result = result.unwrap();
        assert!(!matches!(
            flag_result.cache_source,
            common_hypercache::CacheSource::Fallback
        ));
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
    async fn test_get_flags_from_hypercache_compressed_payload() {
        use common_compression::compress_zstd;

        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert team in Redis");

        // Create a large payload with multiple flags (>512 bytes triggers compression in Django)
        let large_flags = FeatureFlagList {
            flags: (0..10)
                .map(|i| FeatureFlag {
                    id: i,
                    team_id: team.id,
                    name: Some(format!("Test Flag {i} with a longer name for size")),
                    key: format!("test_flag_{i}_with_extra_chars_for_larger_payload"),
                    deleted: false,
                    active: i % 2 == 0,
                    filters: FlagFilters {
                        groups: vec![FlagPropertyGroup {
                            properties: Some(vec![PropertyFilter {
                                key: format!("property_key_{i}"),
                                value: Some(serde_json::json!(format!("value_{i}"))),
                                operator: Some(OperatorType::Exact),
                                prop_type: PropertyType::Person,
                                group_type_index: None,
                                negation: None,
                            }]),
                            rollout_percentage: Some(50.0 + i as f64),
                            variant: None,
                        }],
                        multivariate: None,
                        aggregation_group_type_index: None,
                        payloads: None,
                        super_groups: None,
                        holdout_groups: None,
                    },
                    ensure_experience_continuity: Some(false),
                    version: Some(1),
                    evaluation_runtime: Some("all".to_string()),
                    evaluation_tags: None,
                    bucketing_identifier: None,
                })
                .collect(),
        };

        // Serialize exactly like Django does for large payloads: JSON -> Pickle -> Zstd
        let wrapper = HypercacheFlagsWrapper {
            flags: large_flags.flags.clone(),
        };
        let json_string = serde_json::to_string(&wrapper).expect("Failed to serialize to JSON");

        // Verify payload is large enough to trigger compression
        assert!(
            json_string.len() > 512,
            "Payload should be >512 bytes to simulate compressed data, was {} bytes",
            json_string.len()
        );

        let pickled_bytes =
            serde_pickle::to_vec(&json_string, Default::default()).expect("Failed to pickle");
        let compressed_bytes = compress_zstd(&pickled_bytes).expect("Failed to compress with zstd");

        // Write compressed data directly to Redis (simulating Django's HyperCache)
        let cache_key = hypercache_test_key(team.id);
        redis_client
            .set_bytes(cache_key, compressed_bytes, None)
            .await
            .expect("Failed to write compressed data to Redis");

        // Create FlagService and verify it can read the compressed data
        let team_hypercache_reader = setup_team_hypercache_reader(redis_client.clone()).await;
        let hypercache_reader = setup_hypercache_reader(redis_client.clone()).await;
        let flag_service = FlagService::new(
            redis_client.clone(),
            pg_client.clone(),
            team_hypercache_reader,
            hypercache_reader,
        );

        let result = flag_service.get_flags_from_cache_or_pg(team.id).await;
        assert!(
            result.is_ok(),
            "Failed to read compressed flags: {:?}",
            result.err()
        );

        let flag_result = result.unwrap();
        assert!(
            !matches!(
                flag_result.cache_source,
                common_hypercache::CacheSource::Fallback
            ),
            "Expected cache hit for compressed data"
        );
        assert_eq!(
            flag_result.flag_list.flags.len(),
            10,
            "Expected 10 flags from compressed payload"
        );

        // Verify flag contents were correctly decompressed and parsed
        let first_flag = &flag_result.flag_list.flags[0];
        assert_eq!(
            first_flag.key,
            "test_flag_0_with_extra_chars_for_larger_payload"
        );
        assert!(first_flag.active);

        let last_flag = &flag_result.flag_list.flags[9];
        assert_eq!(
            last_flag.key,
            "test_flag_9_with_extra_chars_for_larger_payload"
        );
        assert!(!last_flag.active); // 9 % 2 != 0
    }

    #[tokio::test]
    async fn test_get_flags_falls_back_to_pg_on_hypercache_miss() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None).await;
        let team_hypercache_reader = setup_team_hypercache_reader(redis_client.clone()).await;
        let hypercache_reader = setup_hypercache_reader(redis_client.clone()).await;
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Don't populate hypercache - should fall back to PG

        let flag_service = FlagService::new(
            redis_client.clone(),
            pg_client.clone(),
            team_hypercache_reader,
            hypercache_reader,
        );

        // Should fall back to PostgreSQL and succeed (returns empty list for new team)
        let result = flag_service.get_flags_from_cache_or_pg(team.id).await;
        assert!(result.is_ok());
        let flag_result = result.unwrap();
        assert!(matches!(
            flag_result.cache_source,
            common_hypercache::CacheSource::Fallback
        ));
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
        // HyperCacheReader calls get_raw_bytes(), so we mock that method
        let mut mock_client = MockRedisClient::new();
        mock_client.get_raw_bytes_ret(
            &hypercache_test_key(team.id),
            Err(CustomRedisError::Timeout),
        );

        let redis_client: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_client.clone());
        let hypercache_reader = setup_hypercache_reader_with_mock_redis(redis_client.clone());
        // Use a real Redis client for team hypercache since we're only mocking flags cache
        let team_redis_client = setup_redis_client(None).await;
        let team_hypercache_reader = setup_team_hypercache_reader(team_redis_client).await;

        let flag_service = FlagService::new(
            redis_client,
            context.non_persons_reader.clone(),
            team_hypercache_reader,
            hypercache_reader,
        );

        let result = flag_service.get_flags_from_cache_or_pg(team.id).await;

        // Should succeed by falling back to PostgreSQL
        assert!(result.is_ok());
        let flag_result = result.unwrap();
        assert!(matches!(
            flag_result.cache_source,
            common_hypercache::CacheSource::Fallback
        ));
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
        // HyperCacheReader calls get_raw_bytes(), so we mock that method
        let mut mock_client = MockRedisClient::new();
        mock_client.get_raw_bytes_ret(
            &hypercache_test_key(team.id),
            Err(CustomRedisError::from_redis_kind(
                RedisErrorKind::IoError,
                "Connection refused",
            )),
        );

        let redis_client: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_client.clone());
        let hypercache_reader = setup_hypercache_reader_with_mock_redis(redis_client.clone());
        // Use a real Redis client for team hypercache since we're only mocking flags cache
        let team_redis_client = setup_redis_client(None).await;
        let team_hypercache_reader = setup_team_hypercache_reader(team_redis_client).await;

        let flag_service = FlagService::new(
            redis_client,
            context.non_persons_reader.clone(),
            team_hypercache_reader,
            hypercache_reader,
        );

        let result = flag_service.get_flags_from_cache_or_pg(team.id).await;

        // Should succeed by falling back to PostgreSQL
        assert!(result.is_ok());
        let flag_result = result.unwrap();
        assert!(matches!(
            flag_result.cache_source,
            common_hypercache::CacheSource::Fallback
        ));

        // Verify SET was NOT called (cache write was skipped)
        // This is tested via FlagsReadThroughCache behavior
        let client_calls = mock_client.get_calls();
        assert!(
            !client_calls.iter().any(|call| call.op == "set"),
            "Expected SET to NOT be called for RedisUnavailable error, but it was"
        );
    }

    /// Verifies that the Rust service never writes to cache on PG fallback.
    /// Django now handles cache population via HyperCache; Rust is read-only.
    #[tokio::test]
    async fn test_cache_write_never_performed_on_pg_fallback() {
        use common_redis::MockRedisClient;

        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Set up mock redis client with no return value for the key.
        // MockRedisClient returns NotFound for keys with no mock set up,
        // which triggers the PG fallback path.
        let mock_client = MockRedisClient::new();

        let redis_client: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_client.clone());
        let hypercache_reader = setup_hypercache_reader_with_mock_redis(redis_client.clone());
        let team_redis_client = setup_redis_client(None).await;
        let team_hypercache_reader = setup_team_hypercache_reader(team_redis_client).await;

        let flag_service = FlagService::new(
            redis_client,
            context.non_persons_reader.clone(),
            team_hypercache_reader,
            hypercache_reader,
        );

        let result = flag_service.get_flags_from_cache_or_pg(team.id).await;

        // Should succeed by falling back to PostgreSQL
        assert!(result.is_ok());
        let flag_result = result.unwrap();
        assert!(
            !flag_result.was_cache_hit,
            "Expected cache miss since mock returned NotFound"
        );

        // Verify no SET calls were made - Django handles cache writes, not Rust
        let client_calls = mock_client.get_calls();
        assert!(
            !client_calls
                .iter()
                .any(|call| call.op == "set" || call.op == "set_bytes"),
            "Cache write detected after PG fallback. Rust should be read-only; \
             Django handles cache population via HyperCache. Found calls: {client_calls:?}",
        );
    }
}
