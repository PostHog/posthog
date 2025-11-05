use std::sync::Arc;
use tracing;

use crate::api::errors::FlagError;
use crate::database::get_connection_with_metrics;
use crate::flags::flag_models::{
    FeatureFlag, FeatureFlagList, FeatureFlagRow, TEAM_FLAGS_CACHE_PREFIX,
};
use common_cache::{CacheConfig, CacheResult, ReadThroughCache};
use common_database::PostgresReader;
use common_redis::Client as RedisClient;
use common_types::ProjectId;

// Constants for cache configuration
/// Default TTL for feature flags cache: 5 days (432,000 seconds)
/// This matches the TTL used by the Python cache layer
pub const DEFAULT_FLAGS_CACHE_TTL_SECONDS: u64 = 432_000;

/// Result of loading flags from the database, including deserialization error tracking
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct FlagsWithMetadata {
    pub flags: Vec<FeatureFlag>,
    pub had_deserialization_errors: bool,
}

impl FeatureFlagList {
    pub fn new(flags: Vec<FeatureFlag>) -> Self {
        Self { flags }
    }

    /// Creates a ReadThroughCache instance for feature flags
    ///
    /// # Arguments
    /// * `redis_reader` - Redis client for reading cached data
    /// * `redis_writer` - Redis client for writing cached data
    /// * `ttl_seconds` - Cache TTL in seconds (defaults to DEFAULT_FLAGS_CACHE_TTL_SECONDS if None)
    ///
    /// # Returns
    /// A configured ReadThroughCache instance for feature flags
    pub fn create_cache(
        redis_reader: Arc<dyn RedisClient + Send + Sync>,
        redis_writer: Arc<dyn RedisClient + Send + Sync>,
        ttl_seconds: Option<u64>,
    ) -> ReadThroughCache {
        let ttl = ttl_seconds.unwrap_or(DEFAULT_FLAGS_CACHE_TTL_SECONDS);
        ReadThroughCache::new(
            redis_reader,
            redis_writer,
            CacheConfig::with_ttl(TEAM_FLAGS_CACHE_PREFIX, ttl),
            None, // No negative caching for now
        )
    }

    /// Get feature flags from cache or database using the read-through cache pattern
    ///
    /// This is the primary method for fetching feature flags. It:
    /// 1. Checks Redis cache first
    /// 2. On cache miss, loads from PostgreSQL
    /// 3. Automatically updates the cache when loading from DB (unless Redis is unavailable)
    ///
    /// # Arguments
    /// * `cache` - ReadThroughCache instance
    /// * `pg_client` - PostgreSQL client for database fallback
    /// * `project_id` - Project ID to fetch flags for
    ///
    /// # Returns
    /// * `Ok(CacheResult<FlagsWithMetadata>)` - Cache result containing flags and metadata
    /// * `Err(FlagError)` - Error from database or cache
    pub async fn get_with_cache(
        cache: &ReadThroughCache,
        pg_client: PostgresReader,
        project_id: ProjectId,
    ) -> Result<CacheResult<FlagsWithMetadata>, FlagError> {
        let pg_client = pg_client.clone();
        let mut cache_result = cache
            .get_or_load(&project_id, |&project_id| async move {
                Self::load_from_pg(pg_client, project_id).await
            })
            .await?;

        // Our loader (load_from_pg) always returns Some(metadata), never None.
        // Even empty flag lists are wrapped in Some. However, we use unwrap_or
        // defensively to gracefully handle any future loader contract violations.
        if cache_result.value.is_none() {
            cache_result.value = Some(FlagsWithMetadata {
                flags: vec![],
                had_deserialization_errors: false,
            });
        }

        Ok(cache_result)
    }

    /// Load feature flags from PostgreSQL
    ///
    /// This is the loader function used by the cache. It returns:
    /// - `Ok(Some(metadata))` when loading succeeds (including empty list for projects with no flags)
    /// - `Ok(None)` is never returned (we always return Some, even for empty results)
    /// - `Err(FlagError)` when there's a database error
    ///
    /// Note: We always return `Some` (even for empty flag lists) because an empty list
    /// is a valid state that should be cached. This prevents repeated DB queries for
    /// projects that have no flags.
    async fn load_from_pg(
        pg_client: PostgresReader,
        project_id: ProjectId,
    ) -> Result<Option<FlagsWithMetadata>, FlagError> {
        let (flag_list, had_deserialization_errors) = Self::from_pg(pg_client, project_id).await?;
        Ok(Some(FlagsWithMetadata {
            flags: flag_list.flags,
            had_deserialization_errors,
        }))
    }

    /// Returns feature flags from postgres given a project_id
    pub async fn from_pg(
        client: PostgresReader,
        project_id: ProjectId,
    ) -> Result<(FeatureFlagList, bool), FlagError> {
        let mut conn = get_connection_with_metrics(&client, "non_persons_reader", "fetch_flags")
            .await
            .map_err(|e| {
                tracing::error!(
                    "Failed to get database connection for project {}: {}",
                    project_id,
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
                  ) AS evaluation_tags
              FROM posthog_featureflag AS f
              JOIN posthog_team AS t ON (f.team_id = t.id)
              -- Evaluation tags are distinct from organizational tags. This bridge table links
              -- flags to tags that constrain runtime evaluation. We use LEFT JOIN to retain flags
              -- with zero evaluation tags, so ARRAY_AGG(...) returns an empty array rather than
              -- dropping the flag row entirely.
              LEFT JOIN posthog_featureflagevaluationtag AS et ON (f.id = et.feature_flag_id)
              -- Only fetch names for tags that are evaluation constraints (not all org tags)
              LEFT JOIN posthog_tag AS tag ON (et.tag_id = tag.id)
            WHERE t.project_id = $1
              AND f.deleted = false
              AND f.active = true
            GROUP BY f.id, f.team_id, f.name, f.key, f.filters, f.deleted, f.active, 
                     f.ensure_experience_continuity, f.version, f.evaluation_runtime
        "#;
        let flags_row = sqlx::query_as::<_, FeatureFlagRow>(query)
            .bind(project_id)
            .fetch_all(&mut *conn)
            .await
            .map_err(|e| {
                tracing::error!(
                    "Failed to fetch feature flags from database for project {}: {}",
                    project_id,
                    e
                );
                FlagError::Internal(format!("Database query error: {e}"))
            })?;

        let mut had_deserialization_errors = false;
        let flags_list: Vec<FeatureFlag> = flags_row
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
                    }),
                    Err(e) => {
                        tracing::warn!(
                            "Failed to deserialize filters for flag {} in project {} (team {}): {}",
                            row.key,
                            project_id,
                            row.team_id,
                            e
                        );
                        had_deserialization_errors = true;
                        None // Skip this flag, continue with others
                    }
                }
            })
            .collect();

        tracing::debug!(
            "Successfully fetched {} flags from database for project {}",
            flags_list.len(),
            project_id
        );

        Ok((
            FeatureFlagList { flags: flags_list },
            had_deserialization_errors,
        ))
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

        insert_flags_for_team_in_redis(redis_client.clone(), team.id, team.project_id(), None)
            .await
            .expect("Failed to insert flags");

        let flags_from_redis = get_flags_from_redis(redis_client.clone(), team.project_id())
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

        let (flags_from_pg, _) =
            FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.project_id())
                .await
                .expect("Failed to fetch flags from pg");

        assert_eq!(flags_from_pg.flags.len(), 1);
        let flag = flags_from_pg.flags.first().expect("Flags should be in pg");
        assert_eq!(flag.key, "flag1");
        assert_eq!(flag.team_id, team.id);
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(flag.filters.groups[0].properties.as_ref().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn test_fetch_empty_team_from_pg() {
        let context = TestContext::new(None).await;

        let (FeatureFlagList { flags }, _) =
            FeatureFlagList::from_pg(context.non_persons_reader.clone(), 1234)
                .await
                .expect("Failed to fetch flags from pg");

        assert_eq!(flags.len(), 0);
    }

    #[tokio::test]
    async fn test_fetch_nonexistent_team_from_pg() {
        let context = TestContext::new(None).await;

        match FeatureFlagList::from_pg(context.non_persons_reader.clone(), -1).await {
            Ok((flags, _)) => assert_eq!(flags.flags.len(), 0),
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
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
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

        let (flags_from_pg, _) =
            FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.project_id())
                .await
                .expect("Failed to fetch flags from pg");

        assert_eq!(flags_from_pg.flags.len(), 2);
        for flag in &flags_from_pg.flags {
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

        let (flags_from_pg, _) =
            FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.project_id())
                .await
                .expect("Failed to fetch flags from pg");

        assert_eq!(flags_from_pg.flags.len(), 1);
        let flag = flags_from_pg.flags.first().expect("Should have one flag");
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
}
