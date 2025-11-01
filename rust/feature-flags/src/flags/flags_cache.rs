use crate::api::errors::FlagError;
use crate::flags::cache_metrics::track_cache_metrics;
use crate::flags::flag_models::{FeatureFlag, FeatureFlagList};
use crate::metrics::consts::{
    DB_FLAG_READS_COUNTER, FLAG_CACHE_ERRORS_COUNTER, FLAG_CACHE_HIT_COUNTER,
};
use common_cache::{CacheConfig, CacheResult, NegativeCache, ReadThroughCache};
use common_database::PostgresReader;
use common_redis::Client as RedisClient;
use std::sync::Arc;

// Prefix for team flags cache keys in Redis
const TEAM_FLAGS_CACHE_PREFIX: &str = "posthog:1:team_feature_flags_";

/// Flags-specific get-or-load helper
pub async fn flags_get_or_load(
    redis_reader: Arc<dyn RedisClient + Send + Sync>,
    redis_writer: Arc<dyn RedisClient + Send + Sync>,
    pg_client: PostgresReader,
    project_id: i64,
    ttl_seconds: Option<u64>,
    negative_cache: Option<Arc<NegativeCache>>,
) -> Result<(FeatureFlagList, bool, bool), FlagError> {
    let cache_config = CacheConfig::new(TEAM_FLAGS_CACHE_PREFIX, ttl_seconds);

    let cache = ReadThroughCache::new(redis_reader, redis_writer, cache_config, negative_cache);

    // We cache Vec<FeatureFlag> to maintain compatibility with update_flags_in_redis
    // which serializes just the Vec, not the whole FeatureFlagList struct
    let result: CacheResult<Vec<FeatureFlag>> = cache
        .get_or_load(&project_id, |project_id| {
            let project_id = *project_id;
            async move {
                // FeatureFlagList::from_pg returns (FeatureFlagList, bool)
                // We only cache the Vec, not the deserialization errors indicator
                match FeatureFlagList::from_pg(pg_client.clone(), project_id).await {
                    Ok((flags, _had_errors)) => Ok(Some(flags.flags)),
                    Err(FlagError::RowNotFound) => Ok(None), // Not found = negative cache
                    Err(e) => Err(e),                        // Other errors propagate
                }
            }
        })
        .await?;

    // Track metrics based on source
    track_cache_metrics(
        result.source,
        FLAG_CACHE_HIT_COUNTER,
        DB_FLAG_READS_COUNTER,
        FLAG_CACHE_ERRORS_COUNTER,
    );

    // Extract value or return error if not found
    let was_cached = result.was_cached();
    match result.value {
        Some(flags_vec) => {
            // Wrap the Vec in FeatureFlagList
            let flags = FeatureFlagList { flags: flags_vec };
            // When loaded from cache, we don't have deserialization error info
            // This is acceptable as errors only occur during DB load
            let had_deserialization_errors = false;
            Ok((flags, was_cached, had_deserialization_errors))
        }
        None => Err(FlagError::RowNotFound),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::test_utils::TestContext;
    use common_redis::MockRedisClient;

    #[tokio::test]
    async fn test_flags_cache_basic_functionality() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        // Create negative cache for testing
        let negative_cache = Arc::new(NegativeCache::new(100, 300));

        // Set up mock redis_reader to return NotFound (cache miss)
        let mut mock_reader = MockRedisClient::new();
        mock_reader.get_ret(
            &format!("{}{}", TEAM_FLAGS_CACHE_PREFIX, team.project_id),
            Err(common_redis::CustomRedisError::NotFound),
        );

        // Set up mock redis_writer to succeed
        let mut mock_writer = MockRedisClient::new();
        mock_writer.set_ret(
            &format!("{}{}", TEAM_FLAGS_CACHE_PREFIX, team.project_id),
            Ok(()),
        );

        let reader: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_reader.clone());
        let writer: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_writer.clone());

        // Call flags_get_or_load
        let result = flags_get_or_load(
            reader,
            writer,
            context.non_persons_reader.clone(),
            team.project_id,
            None,
            Some(negative_cache.clone()),
        )
        .await;

        // Should succeed and return flags
        assert!(result.is_ok());
        let (_flags, was_cache_hit, _had_deserialization_errors) = result.unwrap();
        assert!(!was_cache_hit); // First call should be a cache miss
                                 // The flags list might be empty for a new team, but that's valid
    }
}
