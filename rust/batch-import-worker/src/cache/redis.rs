use anyhow::Error;
use common_redis::{Client, RedisClient};
use std::sync::Arc;

use super::CacheStats;

/// Redis-based cache for tracking user_id -> device_id mappings to determine
/// when to inject $identify events (first time only per user-device pair)
pub struct IdentifyCache {
    redis_client: Arc<dyn Client + Send + Sync>,
    ttl_seconds: u64,
}

impl std::fmt::Debug for IdentifyCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("IdentifyCache")
            .field("redis_client", &"<redis client>")
            .field("ttl_seconds", &self.ttl_seconds)
            .finish()
    }
}

impl IdentifyCache {
    pub async fn new(redis_url: &str) -> Result<Self, Error> {
        Self::with_ttl(redis_url, 86400).await
    }

    pub async fn with_ttl(redis_url: &str, ttl_seconds: u64) -> Result<Self, Error> {
        if redis_url.is_empty() {
            return Err(Error::msg("Redis URL is required for cache"));
        }

        let redis_client = RedisClient::new(redis_url.to_string()).await?;
        let client_arc = Arc::from(redis_client);
        Ok(Self {
            redis_client: client_arc,
            ttl_seconds,
        })
    }

    /// Create a test instance with mock Redis client (for testing only)
    #[cfg(test)]
    pub fn test_new() -> Self {
        use common_redis::MockRedisClient;
        let mock_client = MockRedisClient::new();
        let client_arc = Arc::new(mock_client);

        Self {
            redis_client: client_arc,
            ttl_seconds: 86400,
        }
    }

    /// Generate Redis key for user-device combination
    fn make_key(team_id: i32, user_id: &str, device_id: &str) -> String {
        format!("identify:{}:{}:{}", team_id, user_id, device_id)
    }

    /// Check if we've already seen this user_id + device_id combination
    pub async fn has_seen_user_device(&self, team_id: i32, user_id: &str, device_id: &str) -> Result<bool, Error> {
        let key = Self::make_key(team_id, user_id, device_id);

        match self.redis_client.get(key).await {
            Ok(_) => Ok(true), // Key exists, we've seen this combination
            Err(common_redis::CustomRedisError::NotFound) => Ok(false), // Key doesn't exist
            Err(e) => Err(Error::msg(format!("Redis error checking user-device: {}", e))),
        }
    }

    /// Mark that we've seen this user_id + device_id combination
    pub async fn mark_seen_user_device(&self, team_id: i32, user_id: &str, device_id: &str) -> Result<(), Error> {
        let key = Self::make_key(team_id, user_id, device_id);

        self.redis_client.set_nx_ex(key, "1".to_string(), self.ttl_seconds).await
            .map_err(|e| Error::msg(format!("Redis error marking user-device: {}", e)))?;

        Ok(())
    }

    /// Get cache statistics for monitoring
    pub async fn stats(&self) -> Result<CacheStats, Error> {
        // For Redis, we don't maintain in-memory stats
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
    #[tokio::test]
    async fn test_redis_cache_make_key() {
        let key = super::IdentifyCache::make_key(1, "user123", "device456");
        assert_eq!(key, "identify:1:user123:device456");
    }
}
