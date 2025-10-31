use crate::api::errors::FlagError;
use crate::flags::cache_metrics::track_cache_metrics;
use crate::metrics::consts::{
    DB_TEAM_READS_COUNTER, TEAM_CACHE_ERRORS_COUNTER, TEAM_CACHE_HIT_COUNTER,
};
use crate::team::team_models::Team;
use common_cache::{CacheResult, ReadThroughCache};
use common_database::PostgresReader;
use std::sync::Arc;

/// Team-specific get-or-load helper
pub async fn team_get_or_load(
    cache: Arc<ReadThroughCache>,
    pg_client: PostgresReader,
    token: &str,
) -> Result<(Team, bool), FlagError> {
    let result: CacheResult<Team> = cache
        .get_or_load(&token.to_string(), |token| {
            let token = token.clone();
            async move {
                match Team::from_pg(pg_client.clone(), &token).await {
                    Ok(team) => Ok(Some(team)),
                    Err(FlagError::RowNotFound) => Ok(None), // Not found = negative cache
                    Err(e) => Err(e),                        // Other errors propagate
                }
            }
        })
        .await?;

    // Track metrics based on source
    track_cache_metrics(
        result.source,
        TEAM_CACHE_HIT_COUNTER,
        DB_TEAM_READS_COUNTER,
        TEAM_CACHE_ERRORS_COUNTER,
    );

    // Extract value or return error if not found
    let was_cached = result.was_cached();
    match result.value {
        Some(team) => Ok((team, was_cached)),
        None => Err(FlagError::RowNotFound),
    }
}

/// Secret token get-or-load helper
///
/// Loads teams by their secret API token (used for authentication endpoints).
/// Uses a separate cache namespace from regular API tokens.
pub async fn secret_token_get_or_load(
    cache: Arc<ReadThroughCache>,
    pg_client: PostgresReader,
    secret_token: &str,
) -> Result<(Team, bool), FlagError> {
    let result: CacheResult<Team> = cache
        .get_or_load(&secret_token.to_string(), |secret_token| {
            let secret_token = secret_token.clone();
            async move {
                match Team::from_pg_by_secret_token(pg_client.clone(), &secret_token).await {
                    Ok(team) => Ok(Some(team)),
                    Err(FlagError::RowNotFound) => Ok(None), // Not found = negative cache
                    Err(e) => Err(e),                        // Other errors propagate
                }
            }
        })
        .await?;

    // Track metrics based on source
    track_cache_metrics(
        result.source,
        TEAM_CACHE_HIT_COUNTER,
        DB_TEAM_READS_COUNTER,
        TEAM_CACHE_ERRORS_COUNTER,
    );

    // Extract value or return error if not found
    let was_cached = result.was_cached();
    match result.value {
        Some(team) => Ok((team, was_cached)),
        None => Err(FlagError::TokenValidationError),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::test_utils::TestContext;
    use common_cache::{CacheConfig, NegativeCache};
    use common_redis::{Client as RedisClient, MockRedisClient};

    #[tokio::test]
    async fn test_team_cache_basic_functionality() {
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
            &format!("posthog:1:team_token:{}", team.api_token),
            Err(common_redis::CustomRedisError::NotFound),
        );

        // Set up mock redis_writer to succeed
        let mut mock_writer = MockRedisClient::new();
        mock_writer.set_ret(&format!("posthog:1:team_token:{}", team.api_token), Ok(()));

        let reader: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_reader.clone());
        let writer: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_writer.clone());

        // Create cache
        let cache_config = CacheConfig::new("posthog:1:team_token:", None);
        let cache = Arc::new(ReadThroughCache::new(
            reader,
            writer,
            cache_config,
            Some(negative_cache.clone()),
        ));

        // Call team_get_or_load
        let result =
            team_get_or_load(cache, context.non_persons_reader.clone(), &team.api_token).await;

        // Should succeed and return the team
        assert!(result.is_ok());
        let (returned_team, was_cache_hit) = result.unwrap();
        assert_eq!(returned_team.id, team.id);
        assert!(!was_cache_hit); // First call should be a cache miss
    }
}
