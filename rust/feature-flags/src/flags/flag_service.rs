use crate::{
    api::errors::FlagError,
    flags::{
        flag_definitions_cache::FlagDefinitionsCache,
        flag_models::{FeatureFlagList, HypercacheFlagsWrapper, PreparedFlagDefinitions},
    },
    handler::canonical_log::with_canonical_log,
    metrics::consts::{
        DB_TEAM_READS_COUNTER, PG_TEAM_FALLBACK_SKIPPED_COUNTER, TEAM_CACHE_HIT_COUNTER,
        TEAM_NEGATIVE_CACHE_HIT_COUNTER, TOKEN_VALIDATION_ERRORS_COUNTER, TOMBSTONE_COUNTER,
    },
    team::team_models::Team,
};
use common_cache::NegativeCache;
use common_database::PostgresReader;
use common_hypercache::{
    CacheSource, HyperCacheError, HyperCacheReader, KeyType, HYPERCACHE_COUNTER_NAME,
};
use common_metrics::inc;
use common_redis::Client as RedisClient;
use common_types::TeamId;
use metrics::counter;
use std::sync::Arc;

/// Result of fetching feature flags, including cache source information.
#[derive(Debug, Clone)]
pub struct FlagResult {
    /// Pre-compiled flag definitions (deserialized + regex-compiled), shared across requests.
    pub prepared: Arc<PreparedFlagDefinitions>,
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
    /// In-memory cache for deserialized + regex-compiled flag definitions
    flag_definitions_cache: Arc<FlagDefinitionsCache>,
    /// In-memory negative cache for invalid API tokens
    team_negative_cache: NegativeCache,
    /// When true, skip PG fallback for team token lookups
    skip_pg_team_fallback: bool,
}

impl FlagService {
    pub fn new(
        shared_redis_client: Arc<dyn RedisClient + Send + Sync>,
        pg_client: PostgresReader,
        team_hypercache_reader: Arc<HyperCacheReader>,
        flags_hypercache_reader: Arc<HyperCacheReader>,
        flag_definitions_cache: Arc<FlagDefinitionsCache>,
        team_negative_cache: NegativeCache,
        skip_pg_team_fallback: bool,
    ) -> Self {
        Self {
            shared_redis_client,
            pg_client,
            team_hypercache_reader,
            flags_hypercache_reader,
            flag_definitions_cache,
            team_negative_cache,
            skip_pg_team_fallback,
        }
    }

    /// Deprecated: use `verify_token_and_get_team` instead, which returns the Team
    /// directly and avoids a redundant cache lookup.
    #[allow(dead_code)]
    pub async fn verify_token(&self, token: &str) -> Result<String, FlagError> {
        self.verify_token_and_get_team(token)
            .await
            .map(|_| token.to_string())
    }

    /// Verifies the Project API token and returns the Team.
    ///
    /// This combines token verification with team fetching to avoid a redundant
    /// cache lookup — callers get the Team directly instead of re-fetching it.
    /// Invalid tokens are tracked in a negative cache to avoid repeated lookups
    /// against Redis/S3/PG for tokens that don't correspond to any team.
    pub async fn verify_token_and_get_team(&self, token: &str) -> Result<Team, FlagError> {
        if self.team_negative_cache.contains(token) {
            with_canonical_log(|log| log.team_cache_source = Some("negative_cache"));
            inc(TEAM_NEGATIVE_CACHE_HIT_COUNTER, &[], 1);
            inc(
                TOKEN_VALIDATION_ERRORS_COUNTER,
                &[("reason".to_string(), "token_not_found".to_string())],
                1,
            );
            return Err(FlagError::TokenValidationError);
        }

        match self.get_team_from_cache_or_pg(token).await {
            Ok(team) => Ok(team),
            Err(e) => {
                tracing::warn!("Token validation failed for token '{}': {:?}", token, e);
                if e.is_token_not_found() {
                    self.team_negative_cache.insert(token.to_string());
                    inc(
                        TOKEN_VALIDATION_ERRORS_COUNTER,
                        &[("reason".to_string(), "token_not_found".to_string())],
                        1,
                    );
                }
                Err(FlagError::TokenValidationError)
            }
        }
    }

    /// Fetches a team by its database ID.
    ///
    /// Used when the team_id is known from authentication (e.g. a phs_ token)
    /// but the team object is needed for cache lookups and response building.
    pub async fn get_team_by_id(&self, team_id: i32) -> Result<Team, FlagError> {
        with_canonical_log(|log| log.team_cache_source = Some("pg_by_id"));
        inc(
            DB_TEAM_READS_COUNTER,
            &[("path".to_string(), "by_id".to_string())],
            1,
        );
        Team::from_pg_by_id(self.pg_client.clone(), team_id)
            .await
            .map_err(|e| match e {
                FlagError::RowNotFound => FlagError::SecretApiTokenInvalid,
                other => other,
            })
    }

    /// Fetches the team from HyperCache or the database.
    ///
    /// Uses team_metadata HyperCache (Redis → S3 → PostgreSQL fallback).
    /// PostgreSQL fallback can be disabled via `skip_pg_team_fallback`.
    /// This is a read-only cache - Django handles cache writes.
    pub async fn get_team_from_cache_or_pg(&self, token: &str) -> Result<Team, FlagError> {
        let key = KeyType::string(token);
        let skip_pg = self.skip_pg_team_fallback;
        let pg_client = self.pg_client.clone();
        let token_owned = token.to_string();

        let (data, source) = self
            .team_hypercache_reader
            .get_typed_with_source_or_fallback::<Team, _, _, FlagError>(&key, || async move {
                // This closure runs on cache miss (key not found in Redis and
                // S3) or infrastructure errors (timeouts, connection failures)
                // as a resilience fallback.
                if skip_pg {
                    inc(PG_TEAM_FALLBACK_SKIPPED_COUNTER, &[], 1);
                    return Err(FlagError::TokenValidationError);
                }

                let team = Team::from_pg(pg_client, &token_owned).await?;
                inc(DB_TEAM_READS_COUNTER, &[], 1);

                Ok::<Option<Team>, FlagError>(Some(team))
            })
            .await?;

        let team = data.ok_or(FlagError::TokenValidationError)?;
        let cache_hit = !matches!(source, CacheSource::Fallback);

        with_canonical_log(|log| log.team_cache_source = Some(source.as_log_str()));

        inc(
            TEAM_CACHE_HIT_COUNTER,
            &[("cache_hit".to_string(), cache_hit.to_string())],
            1,
        );

        Ok(team)
    }

    /// Fetches flags from the hypercache (Redis → S3), falling back to PostgreSQL
    /// on cache miss or infra errors. Parse errors (`Json`/`Pickle`) hard-fail with
    /// a tombstone rather than serving degraded single-stage PG data.
    ///
    /// On the hot path the in-memory `FlagDefinitionsCache` is keyed on the etag
    /// Django writes alongside the payload (`enable_etag=True`), so an in-memory
    /// hit short-circuits the payload fetch / pickle / JSON / validation work
    /// entirely. The loader passed to `get_or_load` only runs on a true miss
    /// or when no etag is available.
    pub async fn get_flags_from_cache_or_pg(
        &self,
        team_id: TeamId,
    ) -> Result<FlagResult, FlagError> {
        let key = KeyType::int(team_id);

        // Cheap version probe: a single Redis GET on a 16-byte string. On a
        // Redis error we bypass `get_or_load` entirely so the request
        // increments only `etag_redis_error`, not also `etag_missing` /
        // `sentinel` (each request must increment exactly one `reason`).
        match self.flags_hypercache_reader.get_etag(&key).await {
            Ok(etag) => {
                let (prepared, cache_source) = self
                    .flag_definitions_cache
                    .get_or_load(team_id, etag, || async {
                        self.fetch_wrapper_or_pg(team_id).await
                    })
                    .await?;
                Ok(FlagResult {
                    prepared,
                    cache_source,
                })
            }
            Err(e) => {
                tracing::debug!(
                    team_id,
                    error = %e,
                    "etag fetch failed; bypassing in-memory cache for this request"
                );
                inc(
                    crate::metrics::consts::FLAG_DEFINITIONS_INMEM_CACHE_NO_VERSION_COUNTER,
                    &[("reason".to_string(), "etag_redis_error".to_string())],
                    1,
                );
                let (wrapper, cache_source) = self.fetch_wrapper_or_pg(team_id).await?;
                let prepared =
                    crate::flags::flag_definitions_cache::compile_from_wrapper(team_id, wrapper)?;
                Ok(FlagResult {
                    prepared,
                    cache_source,
                })
            }
        }
    }

    /// Hypercache-then-PG payload fetch, extracted so the in-memory cache can
    /// invoke it lazily inside `get_or_load`. Returns `None` for the
    /// `__missing__` sentinel (team has no flags), `Some(wrapper)` otherwise.
    /// `Json`/`Pickle` parse errors hard-fail with a tombstone — we never want
    /// to silently degrade to PG (which lacks dependency metadata) on data
    /// corruption.
    async fn fetch_wrapper_or_pg(
        &self,
        team_id: TeamId,
    ) -> Result<(Option<HypercacheFlagsWrapper>, CacheSource), FlagError> {
        let key = KeyType::int(team_id);

        match self
            .flags_hypercache_reader
            .get_typed_with_source::<HypercacheFlagsWrapper>(&key)
            .await
        {
            Ok((data, source)) => Ok((data, source)),
            Err(e @ (HyperCacheError::Json(_) | HyperCacheError::Pickle(_))) => {
                counter!(
                    TOMBSTONE_COUNTER,
                    "namespace" => "feature_flags",
                    "operation" => "hypercache_parse_error",
                    "component" => "flag_service",
                )
                .increment(1);
                Err(FlagError::DataParsingErrorWithContext(format!(
                    "Failed to parse feature flags for team {team_id}: {e}"
                )))
            }
            Err(e) => {
                // Mirror the hit_fallback counters that `get_typed_with_source_or_fallback`
                // would emit, so flags and team paths stay on identical instrumentation.
                let result_label = if matches!(e, HyperCacheError::CacheMiss) {
                    "hit_fallback"
                } else {
                    "hit_fallback_infra_error"
                };
                let hc_config = self.flags_hypercache_reader.config();
                inc(
                    HYPERCACHE_COUNTER_NAME,
                    &[
                        ("result".to_string(), result_label.to_string()),
                        ("namespace".to_string(), hc_config.namespace.clone()),
                        ("value".to_string(), hc_config.object_name.clone()),
                    ],
                    1,
                );

                // PG has no dependency metadata, so all flags go in a single stage.
                let flags = FeatureFlagList::from_pg(self.pg_client.clone(), team_id).await?;
                let evaluation_metadata =
                    crate::flags::flag_models::EvaluationMetadata::single_stage(&flags);
                let wrapper = HypercacheFlagsWrapper {
                    flags,
                    cohorts: None,
                    evaluation_metadata,
                };
                Ok((Some(wrapper), CacheSource::Fallback))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use common_cache::NegativeCache;
    use rstest::rstest;
    use serde_json::json;

    use crate::{
        flags::{
            feature_flag_list::PreparedFlags,
            flag_definitions_cache::FlagDefinitionsCache,
            flag_models::{
                EvaluationMetadata, FeatureFlag, FlagFilters, FlagPropertyGroup,
                HypercacheFlagsWrapper,
            },
            test_helpers::{hypercache_test_key, update_flags_in_hypercache},
        },
        properties::property_models::{OperatorType, PropertyFilter, PropertyType},
        utils::test_utils::{
            insert_new_team_in_redis, setup_hypercache_reader,
            setup_hypercache_reader_with_mock_redis, setup_pg_reader_client, setup_redis_client,
            setup_team_hypercache_reader, setup_team_hypercache_reader_with_mock_redis,
            TestContext,
        },
    };

    use super::*;

    #[tokio::test]
    async fn test_verify_token_and_get_team() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None);
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
            Arc::new(FlagDefinitionsCache::disabled()),
            NegativeCache::new(100, 300),
            false,
        );

        // Test valid token returns the team
        let result = flag_service
            .verify_token_and_get_team(&team.api_token)
            .await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap().api_token, team.api_token);

        // Test invalid token
        let result = flag_service
            .verify_token_and_get_team("invalid_token")
            .await;
        assert!(matches!(result, Err(FlagError::TokenValidationError)));
    }

    #[tokio::test]
    async fn test_get_team_from_cache_or_pg() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None);
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
            Arc::new(FlagDefinitionsCache::disabled()),
            NegativeCache::new(100, 300),
            false,
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
            Arc::new(FlagDefinitionsCache::disabled()),
            NegativeCache::new(100, 300),
            false,
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
        let pg_client = setup_pg_reader_client(None);
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        // Insert some mock flags into hypercache (new format)
        let flags_vec = vec![
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
                            compiled_regex: None,
                        }]),
                        rollout_percentage: Some(50.0),
                        variant: None,
                        ..Default::default()
                    }],
                    multivariate: None,
                    aggregation_group_type_index: None,
                    payloads: None,
                    super_groups: None,
                    feature_enrollment: None,
                    holdout: None,
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
                    feature_enrollment: None,
                    holdout: None,
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
                            compiled_regex: None,
                        }]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                        ..Default::default()
                    }],
                    multivariate: None,
                    aggregation_group_type_index: None,
                    payloads: None,
                    super_groups: None,
                    feature_enrollment: None,
                    holdout: None,
                },
                deleted: false,
                active: true,
                ensure_experience_continuity: Some(false),
                version: Some(1),
                evaluation_runtime: Some("all".to_string()),
                evaluation_tags: None,
                bucketing_identifier: None,
            },
        ];
        let evaluation_metadata = Arc::new(EvaluationMetadata::single_stage(&flags_vec));
        let mock_flags = FeatureFlagList {
            flags: PreparedFlags::seal(flags_vec),
            evaluation_metadata,
            ..Default::default()
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
            Arc::new(FlagDefinitionsCache::disabled()),
            NegativeCache::new(100, 300),
            false,
        );

        // Test fetching from hypercache
        let result = flag_service.get_flags_from_cache_or_pg(team.id).await;
        assert!(result.is_ok());
        let flag_result = result.unwrap();
        assert!(!matches!(
            flag_result.cache_source,
            common_hypercache::CacheSource::Fallback
        ));
        assert_eq!(flag_result.prepared.flags.len(), mock_flags.flags.len());

        // Verify the contents of the fetched flags
        let beta_feature = flag_result
            .prepared
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
            .prepared
            .flags
            .iter()
            .find(|f| f.key == "new_ui")
            .unwrap();
        assert!(!new_ui.active);
        assert!(new_ui.filters.groups.is_empty());

        let premium_feature = flag_result
            .prepared
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
        let pg_client = setup_pg_reader_client(None);
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert team in Redis");

        // Create a large payload with multiple flags (>512 bytes triggers compression in Django)
        let large_flags_vec: Vec<FeatureFlag> = (0..10)
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
                            compiled_regex: None,
                        }]),
                        rollout_percentage: Some(50.0 + i as f64),
                        variant: None,
                        ..Default::default()
                    }],
                    multivariate: None,
                    aggregation_group_type_index: None,
                    payloads: None,
                    super_groups: None,
                    feature_enrollment: None,

                    holdout: None,
                },
                ensure_experience_continuity: Some(false),
                version: Some(1),
                evaluation_runtime: Some("all".to_string()),
                evaluation_tags: None,
                bucketing_identifier: None,
            })
            .collect();
        let large_flags = FeatureFlagList {
            flags: PreparedFlags::seal(large_flags_vec),
            ..Default::default()
        };

        // Serialize exactly like Django does for large payloads: JSON -> Pickle -> Zstd
        let wrapper = HypercacheFlagsWrapper {
            flags: large_flags.flags.to_vec(),
            evaluation_metadata: EvaluationMetadata::single_stage(&large_flags.flags),
            cohorts: None,
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
            Arc::new(FlagDefinitionsCache::disabled()),
            NegativeCache::new(100, 300),
            false,
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
            flag_result.prepared.flags.len(),
            10,
            "Expected 10 flags from compressed payload"
        );

        // Verify flag contents were correctly decompressed and parsed
        let first_flag = &flag_result.prepared.flags[0];
        assert_eq!(
            first_flag.key,
            "test_flag_0_with_extra_chars_for_larger_payload"
        );
        assert!(first_flag.active);

        let last_flag = &flag_result.prepared.flags[9];
        assert_eq!(
            last_flag.key,
            "test_flag_9_with_extra_chars_for_larger_payload"
        );
        assert!(!last_flag.active); // 9 % 2 != 0
    }

    #[tokio::test]
    async fn test_get_flags_falls_back_to_pg_on_hypercache_miss() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None);
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
            Arc::new(FlagDefinitionsCache::disabled()),
            NegativeCache::new(100, 300),
            false,
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
            Arc::new(FlagDefinitionsCache::disabled()),
            NegativeCache::new(100, 300),
            false,
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
            Arc::new(FlagDefinitionsCache::disabled()),
            NegativeCache::new(100, 300),
            false,
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
            Arc::new(FlagDefinitionsCache::disabled()),
            NegativeCache::new(100, 300),
            false,
        );

        let result = flag_service.get_flags_from_cache_or_pg(team.id).await;

        // Should succeed by falling back to PostgreSQL
        assert!(result.is_ok());
        let flag_result = result.unwrap();
        assert!(
            matches!(
                flag_result.cache_source,
                common_hypercache::CacheSource::Fallback
            ),
            "Expected fallback to PostgreSQL since mock returned NotFound"
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

    /// Corrupt Redis payload must hard-fail with DataParsingErrorWithContext rather
    /// than silently fall back to PG (which would serve single-stage data).
    #[tokio::test]
    async fn test_get_flags_hard_fails_on_hypercache_parse_error() {
        use common_redis::MockRedisClient;

        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Pickle a string that isn't the sentinel and isn't valid JSON for the wrapper.
        let invalid_json = "not valid json {{{";
        let pickled =
            serde_pickle::to_vec(&invalid_json, Default::default()).expect("Failed to pickle");

        let mut mock_client = MockRedisClient::new();
        mock_client.get_raw_bytes_ret(&hypercache_test_key(team.id), Ok(pickled));

        let redis_client: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_client);
        let hypercache_reader = setup_hypercache_reader_with_mock_redis(redis_client.clone());
        let team_redis_client = setup_redis_client(None).await;
        let team_hypercache_reader = setup_team_hypercache_reader(team_redis_client).await;

        let flag_service = FlagService::new(
            redis_client,
            context.non_persons_reader.clone(),
            team_hypercache_reader,
            hypercache_reader,
            Arc::new(FlagDefinitionsCache::disabled()),
            NegativeCache::new(100, 300),
            false,
        );

        let result = flag_service.get_flags_from_cache_or_pg(team.id).await;
        assert!(
            matches!(result, Err(FlagError::DataParsingErrorWithContext(_))),
            "parse error must hard-fail, got {result:?}"
        );
    }

    /// Sibling of the Json parse-error test: guards the `Pickle` arm of the
    /// `Err(e @ (Json(_) | Pickle(_)))` pattern against accidental narrowing.
    #[tokio::test]
    async fn test_get_flags_hard_fails_on_hypercache_pickle_error() {
        use common_redis::MockRedisClient;

        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Raw non-pickle bytes make serde_pickle::from_slice::<String> fail.
        let non_pickle_bytes = b"this is not pickle data".to_vec();

        let mut mock_client = MockRedisClient::new();
        mock_client.get_raw_bytes_ret(&hypercache_test_key(team.id), Ok(non_pickle_bytes));

        let redis_client: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_client);
        let hypercache_reader = setup_hypercache_reader_with_mock_redis(redis_client.clone());
        let team_redis_client = setup_redis_client(None).await;
        let team_hypercache_reader = setup_team_hypercache_reader(team_redis_client).await;

        let flag_service = FlagService::new(
            redis_client,
            context.non_persons_reader.clone(),
            team_hypercache_reader,
            hypercache_reader,
            Arc::new(FlagDefinitionsCache::disabled()),
            NegativeCache::new(100, 300),
            false,
        );

        let result = flag_service.get_flags_from_cache_or_pg(team.id).await;
        assert!(
            matches!(result, Err(FlagError::DataParsingErrorWithContext(_))),
            "pickle error must hard-fail, got {result:?}"
        );
    }

    #[tokio::test]
    async fn test_negative_cache_returns_error_for_cached_invalid_token() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None);
        let team_hypercache_reader = setup_team_hypercache_reader(redis_client.clone()).await;
        let hypercache_reader = setup_hypercache_reader(redis_client.clone()).await;

        let negative_cache = NegativeCache::new(100, 300);
        negative_cache.insert("known_bad_token".to_string());

        let flag_service = FlagService::new(
            redis_client.clone(),
            pg_client.clone(),
            team_hypercache_reader,
            hypercache_reader,
            Arc::new(FlagDefinitionsCache::disabled()),
            negative_cache,
            false,
        );

        let result = flag_service
            .verify_token_and_get_team("known_bad_token")
            .await;
        assert!(matches!(result, Err(FlagError::TokenValidationError)));
    }

    #[tokio::test]
    async fn test_negative_cache_populated_on_invalid_token() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None);
        let team_hypercache_reader = setup_team_hypercache_reader(redis_client.clone()).await;
        let hypercache_reader = setup_hypercache_reader(redis_client.clone()).await;

        let negative_cache = NegativeCache::new(100, 300);
        assert!(!negative_cache.contains("nonexistent_token"));

        let flag_service = FlagService::new(
            redis_client.clone(),
            pg_client.clone(),
            team_hypercache_reader,
            hypercache_reader,
            Arc::new(FlagDefinitionsCache::disabled()),
            negative_cache.clone(),
            false,
        );

        // First call should fail and populate the negative cache
        let result = flag_service
            .verify_token_and_get_team("nonexistent_token")
            .await;
        assert!(matches!(result, Err(FlagError::TokenValidationError)));
        assert!(negative_cache.contains("nonexistent_token"));
    }

    #[tokio::test]
    async fn test_negative_cache_does_not_affect_valid_tokens() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None);
        let team_hypercache_reader = setup_team_hypercache_reader(redis_client.clone()).await;
        let hypercache_reader = setup_hypercache_reader(redis_client.clone()).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert team");

        let negative_cache = NegativeCache::new(100, 300);

        let flag_service = FlagService::new(
            redis_client.clone(),
            pg_client.clone(),
            team_hypercache_reader,
            hypercache_reader,
            Arc::new(FlagDefinitionsCache::disabled()),
            negative_cache.clone(),
            false,
        );

        // Valid token should succeed and not be added to negative cache
        let result = flag_service
            .verify_token_and_get_team(&team.api_token)
            .await;
        assert!(result.is_ok());
        assert!(!negative_cache.contains(&team.api_token));
    }

    /// Verifies the full negative cache lifecycle: the first call for an invalid
    /// token hits the backend and populates the cache, and the second call is
    /// served from cache without making additional Redis calls.
    #[tokio::test]
    async fn test_second_call_for_invalid_token_skips_backends() {
        use common_redis::MockRedisClient;

        let mock_client = MockRedisClient::new();
        let mock_redis: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_client.clone());
        let team_hypercache_reader = setup_hypercache_reader_with_mock_redis(mock_redis.clone());
        let hypercache_reader = setup_hypercache_reader_with_mock_redis(mock_redis.clone());
        let context = TestContext::new(None).await;

        let negative_cache = NegativeCache::new(100, 300);

        let flag_service = FlagService::new(
            mock_redis,
            context.non_persons_reader.clone(),
            team_hypercache_reader,
            hypercache_reader,
            Arc::new(FlagDefinitionsCache::disabled()),
            negative_cache.clone(),
            false,
        );

        // First call: misses cache, hits Redis (mock) + PG fallback, fails, populates negative cache
        let result = flag_service.verify_token_and_get_team("bad_token").await;
        assert!(matches!(result, Err(FlagError::TokenValidationError)));
        assert!(negative_cache.contains("bad_token"));
        let calls_after_first = mock_client.get_calls().len();
        assert!(
            calls_after_first > 0,
            "First call should have made Redis calls"
        );

        // Second call: should hit negative cache and return immediately
        let result = flag_service.verify_token_and_get_team("bad_token").await;
        assert!(matches!(result, Err(FlagError::TokenValidationError)));
        let calls_after_second = mock_client.get_calls().len();
        assert_eq!(
            calls_after_first, calls_after_second,
            "Second call should not make additional Redis calls (served from negative cache)"
        );
    }

    #[tokio::test]
    async fn test_skip_pg_fallback_still_resolves_token_from_hypercache() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None);
        let team_hypercache_reader = setup_team_hypercache_reader(redis_client.clone()).await;
        let hypercache_reader = setup_hypercache_reader(redis_client.clone()).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        let negative_cache = NegativeCache::new(100, 300);

        let flag_service = FlagService::new(
            redis_client.clone(),
            pg_client.clone(),
            team_hypercache_reader,
            hypercache_reader,
            Arc::new(FlagDefinitionsCache::disabled()),
            negative_cache.clone(),
            true, // skip PG fallback
        );

        // Token is in HyperCache, so lookup should succeed even with PG fallback disabled
        let result = flag_service
            .verify_token_and_get_team(&team.api_token)
            .await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap().api_token, team.api_token);
        assert!(
            !negative_cache.contains(&team.api_token),
            "Valid token found in HyperCache should not be in negative cache"
        );
    }

    #[rstest]
    #[case::skip_enabled_rejects(true)]
    #[case::skip_disabled_falls_back_to_pg(false)]
    #[tokio::test]
    async fn test_skip_pg_fallback_with_pg_only_token(#[case] skip_pg: bool) {
        use common_redis::MockRedisClient;

        let mock_client = MockRedisClient::new();
        let mock_redis: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_client.clone());
        let team_hypercache_reader =
            setup_team_hypercache_reader_with_mock_redis(mock_redis.clone());
        let hypercache_reader = setup_hypercache_reader_with_mock_redis(mock_redis.clone());
        let context = TestContext::new(None).await;

        // Team exists in PG but not in HyperCache
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in PG");

        let negative_cache = NegativeCache::new(100, 300);

        let flag_service = FlagService::new(
            mock_redis,
            context.non_persons_reader.clone(),
            team_hypercache_reader,
            hypercache_reader,
            Arc::new(FlagDefinitionsCache::disabled()),
            negative_cache.clone(),
            skip_pg,
        );

        let result = flag_service
            .verify_token_and_get_team(&team.api_token)
            .await;

        if skip_pg {
            assert!(matches!(result, Err(FlagError::TokenValidationError)));
            assert!(
                negative_cache.contains(&team.api_token),
                "Token should be negative-cached when PG fallback is skipped"
            );
        } else {
            let resolved_team = result.expect("Should resolve via PG fallback");
            assert_eq!(resolved_team.api_token, team.api_token);
            assert!(
                !negative_cache.contains(&team.api_token),
                "Valid token should not be in negative cache"
            );
        }
    }

    // =========================================================================
    // FlagDefinitionsCache integration: exercises the real (non-disabled) cache
    // through FlagService so the Arc-share path and etag-based invalidation
    // survive the full hypercache round-trip (serde_json → pickle → Redis →
    // get_etag → moka). Unit tests in flag_definitions_cache cover the cache
    // in isolation; these pin the service boundary.
    // =========================================================================

    /// Builds a single-flag wrapper with a Regex operator so the cache hit path
    /// has to pre-compile an actual fancy_regex pattern.
    fn single_regex_flag_wrapper(team_id: i32, pattern: &str) -> FeatureFlagList {
        use crate::mock;
        use crate::properties::property_models::PropertyFilter;
        use crate::utils::mock::MockInto;

        let flag = mock!(FeatureFlag,
            team_id: team_id,
            name: "Regex Flag".mock_into(),
            key: "regex_flag".mock_into(),
            filters: mock!(PropertyFilter,
                key: "email".mock_into(),
                value: Some(json!(pattern)),
                operator: Some(OperatorType::Regex),
            )
            .mock_into(),
        );
        let evaluation_metadata = Arc::new(EvaluationMetadata::single_stage(std::slice::from_ref(
            &flag,
        )));
        FeatureFlagList {
            flags: PreparedFlags::seal(vec![flag]),
            evaluation_metadata,
            ..Default::default()
        }
    }

    fn real_cache() -> Arc<FlagDefinitionsCache> {
        // Default 128 MB / 90 s — same as production. Matters here only insofar
        // as entries must not be evicted between the two fetches in each test.
        Arc::new(FlagDefinitionsCache::new(None, None))
    }

    /// End-to-end Arc sharing: two `get_flags_from_cache_or_pg` calls for the
    /// same team, against identical hypercache content, must return the same
    /// `Arc<PreparedFlagDefinitions>`. Regressions here (e.g. a stray clone in
    /// FlagService or an etag fetch that shifts between calls) would restore
    /// per-request regex compilation without failing any existing test.
    #[tokio::test]
    async fn test_flag_service_cache_hit_reuses_arc() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None);
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("insert team");

        let mock_flags = single_regex_flag_wrapper(team.id, r"^user@.*\.com$");
        update_flags_in_hypercache(redis_client.clone(), team.id, &mock_flags, None)
            .await
            .expect("write hypercache");

        let flag_service = FlagService::new(
            redis_client.clone(),
            pg_client.clone(),
            setup_team_hypercache_reader(redis_client.clone()).await,
            setup_hypercache_reader(redis_client.clone()).await,
            real_cache(),
            NegativeCache::new(100, 300),
            false,
        );

        let first = flag_service
            .get_flags_from_cache_or_pg(team.id)
            .await
            .expect("first fetch");
        let second = flag_service
            .get_flags_from_cache_or_pg(team.id)
            .await
            .expect("second fetch");

        assert!(
            Arc::ptr_eq(&first.prepared, &second.prepared),
            "second fetch must return the cached Arc, not recompile"
        );
        // The cached path must produce compiled regex — otherwise evaluation
        // falls back to on-the-fly compilation and the caching is useless.
        let re = &first.prepared.flags[0].filters.groups[0]
            .properties
            .as_ref()
            .unwrap()[0]
            .compiled_regex;
        assert!(
            matches!(
                re,
                Some(crate::properties::property_models::CompiledRegex::Compiled(
                    _
                ))
            ),
            "cached flag must carry a compiled regex, got {re:?}"
        );
    }

    /// A hypercache rewrite with different content must produce a fresh Arc:
    /// Django writes a new etag whenever the payload bytes change, so the
    /// `(team_id, etag)` cache key shifts and the next fetch misses + recompiles.
    /// Guards against an etag computed over something more abstract than the
    /// actual flag content — e.g. only over flag IDs.
    #[tokio::test]
    async fn test_flag_service_content_change_invalidates_cache() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None);
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("insert team");

        update_flags_in_hypercache(
            redis_client.clone(),
            team.id,
            &single_regex_flag_wrapper(team.id, r"^v1@.*$"),
            None,
        )
        .await
        .expect("write v1");

        let flag_service = FlagService::new(
            redis_client.clone(),
            pg_client.clone(),
            setup_team_hypercache_reader(redis_client.clone()).await,
            setup_hypercache_reader(redis_client.clone()).await,
            real_cache(),
            NegativeCache::new(100, 300),
            false,
        );

        let v1 = flag_service
            .get_flags_from_cache_or_pg(team.id)
            .await
            .expect("v1 fetch");

        // Rewrite the same flag id with a different regex pattern.
        update_flags_in_hypercache(
            redis_client.clone(),
            team.id,
            &single_regex_flag_wrapper(team.id, r"^v2@.*$"),
            None,
        )
        .await
        .expect("write v2");

        let v2 = flag_service
            .get_flags_from_cache_or_pg(team.id)
            .await
            .expect("v2 fetch");

        assert!(
            !Arc::ptr_eq(&v1.prepared, &v2.prepared),
            "content change must produce a new Arc (etag must shift)"
        );
        let re_v2 = &v2.prepared.flags[0].filters.groups[0]
            .properties
            .as_ref()
            .unwrap()[0]
            .compiled_regex;
        match re_v2 {
            Some(crate::properties::property_models::CompiledRegex::Compiled(r)) => {
                assert_eq!(
                    r.as_str(),
                    r"^v2@.*$",
                    "v2 fetch must carry the v2 pattern, not a stale compile"
                );
            }
            other => panic!("expected compiled v2 regex, got {other:?}"),
        }
    }

    /// Etag stability across the Django-path round-trip: write, fetch, rewrite
    /// byte-identical content, fetch again — must return the same Arc. The
    /// guarantee we lean on for the version-key fast path is that identical
    /// payloads produce identical etags (sha256 over `json.dumps(data,
    /// sort_keys=True)` is deterministic on Django's side; the test helper
    /// uses `compute_etag` over the same serialized bytes). Without this, the
    /// etag would shift on every cache refresh and the in-memory cache would
    /// effectively always miss.
    #[tokio::test]
    async fn test_identical_content_round_trip_keeps_etag_stable() {
        let redis_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None);
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("insert team");

        let flags = single_regex_flag_wrapper(team.id, r"^user@.*\.com$");

        // First write + fetch.
        update_flags_in_hypercache(redis_client.clone(), team.id, &flags, None)
            .await
            .expect("write #1");

        let flag_service = FlagService::new(
            redis_client.clone(),
            pg_client.clone(),
            setup_team_hypercache_reader(redis_client.clone()).await,
            setup_hypercache_reader(redis_client.clone()).await,
            real_cache(),
            NegativeCache::new(100, 300),
            false,
        );

        let first = flag_service
            .get_flags_from_cache_or_pg(team.id)
            .await
            .expect("first fetch");

        // Rewrite identical content. This exercises a fresh pickle+etag path
        // producing the same etag bytes — the in-memory cache must still hit.
        update_flags_in_hypercache(redis_client.clone(), team.id, &flags, None)
            .await
            .expect("write #2");

        let second = flag_service
            .get_flags_from_cache_or_pg(team.id)
            .await
            .expect("second fetch after identical rewrite");

        assert!(
            Arc::ptr_eq(&first.prepared, &second.prepared),
            "identical content re-written must produce the same etag and reuse the cached Arc"
        );
    }
}
