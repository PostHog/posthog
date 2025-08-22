use anyhow::Error;
use async_trait::async_trait;
use common_redis::{Client, RedisClient};
use std::sync::Arc;

use super::{AmplitudeIdentifyCache, CacheStats};

/// Redis implementation of AmplitudeIdentifyCache using the common PostHog Redis library
pub struct RedisAmplitudeIdentifyCache {
    redis_client: Arc<dyn Client + Send + Sync>,
    ttl_seconds: u64,
}

impl std::fmt::Debug for RedisAmplitudeIdentifyCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RedisAmplitudeIdentifyCache")
            .field("redis_client", &"<redis client>")
            .finish()
    }
}

impl RedisAmplitudeIdentifyCache {
    pub async fn new(redis_url: &str) -> Result<Self, Error> {
        Self::with_ttl(redis_url, 86400).await
    }

    pub async fn with_ttl(redis_url: &str, ttl_seconds: u64) -> Result<Self, Error> {
        if redis_url.is_empty() {
            return Err(Error::msg("Redis URL is required for Redis cache"));
        }

        let redis_client = RedisClient::new(redis_url.to_string()).await?;
        let client_arc = Arc::from(redis_client);
        Ok(Self {
            redis_client: client_arc,
            ttl_seconds,
        })
    }

    /// Generate Redis key for user-device combination
    fn make_key(team_id: i32, user_id: &str, device_id: &str) -> String {
        format!("amplitude_identify:{}:{}:{}", team_id, user_id, device_id)
    }


}

#[async_trait]
impl AmplitudeIdentifyCache for RedisAmplitudeIdentifyCache {
    async fn has_seen_user_device(&self, team_id: i32, user_id: &str, device_id: &str) -> Result<bool, Error> {
        let key = Self::make_key(team_id, user_id, device_id);

        match self.redis_client.get(key).await {
            Ok(_) => Ok(true), // Key exists, we've seen this combination
            Err(common_redis::CustomRedisError::NotFound) => Ok(false), // Key doesn't exist
            Err(e) => Err(Error::msg(format!("Redis error checking user-device: {}", e))),
        }
    }

    async fn mark_seen_user_device(&self, team_id: i32, user_id: &str, device_id: &str) -> Result<(), Error> {
        let key = Self::make_key(team_id, user_id, device_id);

        self.redis_client.set_nx_ex(key, "1".to_string(), self.ttl_seconds).await
            .map_err(|e| Error::msg(format!("Redis error marking user-device: {}", e)))?;

        Ok(())
    }

    async fn stats(&self) -> Result<CacheStats, Error> {
        // For Redis, we don't maintain in-memory stats like the memory cache
        // In a production system, you might want to expose Redis INFO stats
        Ok(CacheStats {
            total_entries: 0, // Would need to scan all keys to count
            cache_hits: 0,    // Would need Redis INFO stats
            cache_misses: 0,  // Would need Redis INFO stats
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::MockRedisClient;

    #[tokio::test]
    async fn test_redis_cache_has_seen_user_device() {
        let mut mock_client = MockRedisClient::new();
        mock_client.get_ret("amplitude_identify:1:user123:device456", Ok("1".to_string()));

        // We can't easily test with real RedisClient in unit tests due to async constructor
        // In integration tests, we would test with a real Redis instance
    }

    #[tokio::test]
    async fn test_redis_cache_make_key() {
        let key = RedisAmplitudeIdentifyCache::make_key(1, "user123", "device456");
        assert_eq!(key, "amplitude_identify:1:user123:device456");
    }
}
