use anyhow::Error;
use common_redis::{Client, RedisClient};
use std::sync::Arc;
use std::time::Duration;

use super::{memory::MemoryIdentifyCache, IdentifyCache};

/// Two-tier cache with in-memory cache as L1 and Redis as L2
/// for tracking user_id -> device_id mappings to determine
/// when to inject $identify events (first time only per user-device pair)
pub struct RedisIdentifyCache {
    redis_client: Arc<dyn Client + Send + Sync>,
    memory_cache: MemoryIdentifyCache,
    ttl_seconds: u64,
}

impl std::fmt::Debug for RedisIdentifyCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RedisIdentifyCache")
            .field("redis_client", &"<redis client>")
            .field("memory_cache", &self.memory_cache)
            .field("ttl_seconds", &self.ttl_seconds)
            .finish()
    }
}

#[async_trait::async_trait]
impl super::IdentifyCache for RedisIdentifyCache {
    async fn has_seen_user_device(
        &self,
        team_id: i32,
        user_id: &str,
        device_id: &str,
    ) -> Result<bool, Error> {
        self.has_seen_user_device(team_id, user_id, device_id).await
    }

    async fn mark_seen_user_device(
        &self,
        team_id: i32,
        user_id: &str,
        device_id: &str,
    ) -> Result<(), Error> {
        self.mark_seen_user_device(team_id, user_id, device_id)
            .await
    }
}

impl RedisIdentifyCache {
    pub async fn new(
        redis_url: &str,
        ttl_seconds: u64,
        memory_capacity: u64,
        memory_ttl_seconds: u64,
    ) -> Result<Self, Error> {
        let redis_client = RedisClient::new(redis_url.to_string()).await?;
        let client_arc = Arc::from(redis_client);
        let memory_cache =
            MemoryIdentifyCache::new(memory_capacity, Duration::from_secs(memory_ttl_seconds));

        Ok(Self {
            redis_client: client_arc,
            memory_cache,
            ttl_seconds,
        })
    }

    /// Generate Redis key for user-device combination
    fn make_key(team_id: i32, user_id: &str, device_id: &str) -> String {
        // URL encode user_id and device_id to prevent key format conflicts
        let encoded_user_id = urlencoding::encode(user_id);
        let encoded_device_id = urlencoding::encode(device_id);
        format!("identify:{team_id}:{encoded_user_id}:{encoded_device_id}")
    }

    /// Check if we've already seen this user_id + device_id combination
    /// First checks memory cache (L1), then Redis (L2) if not found
    pub async fn has_seen_user_device(
        &self,
        team_id: i32,
        user_id: &str,
        device_id: &str,
    ) -> Result<bool, Error> {
        let key = Self::make_key(team_id, user_id, device_id);

        // First check memory cache (L1)
        if self
            .memory_cache
            .has_seen_user_device(team_id, user_id, device_id)
            .await?
        {
            return Ok(true);
        }

        // If not in memory cache, check Redis (L2)
        match self.redis_client.get(key.clone()).await {
            Ok(_) => {
                // Found in Redis, cache it in memory for future requests
                self.memory_cache
                    .mark_seen_user_device(team_id, user_id, device_id)
                    .await?;
                Ok(true)
            }
            Err(common_redis::CustomRedisError::NotFound) => Ok(false), // Key doesn't exist
            Err(e) => Err(Error::msg(format!("Redis error checking user-device: {e}"))),
        }
    }

    /// Mark that we've seen this user_id + device_id combination
    /// Stores in both memory cache (L1) and Redis (L2)
    pub async fn mark_seen_user_device(
        &self,
        team_id: i32,
        user_id: &str,
        device_id: &str,
    ) -> Result<(), Error> {
        let key = Self::make_key(team_id, user_id, device_id);

        // Store in Redis (L2)
        self.redis_client
            .set_nx_ex(key.clone(), "1".to_string(), self.ttl_seconds)
            .await
            .map_err(|e| Error::msg(format!("Redis error marking user-device: {e}")))?;

        // Also store in memory cache (L1) for future requests
        self.memory_cache
            .mark_seen_user_device(team_id, user_id, device_id)
            .await?;

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::{CustomRedisError, MockRedisClient};

    #[tokio::test]
    async fn test_redis_cache_make_key() {
        let key = super::RedisIdentifyCache::make_key(1, "user123", "device456");
        assert_eq!(key, "identify:1:user123:device456");
    }

    #[tokio::test]
    async fn test_cache_first_time_detection() {
        // Setup mock to return NotFound for first call, then success for second call
        let mut mock_client = MockRedisClient::new();
        mock_client = mock_client.get_ret(
            "identify:1:user123:device456",
            Err(CustomRedisError::NotFound),
        );
        let cache = RedisIdentifyCache {
            redis_client: Arc::new(mock_client),
            memory_cache: MemoryIdentifyCache::new(100, Duration::from_secs(300)), // 5 min TTL for test
            ttl_seconds: 86400, // 24 hours for test
        };

        // First call should return false (not seen)
        let result1 = cache
            .has_seen_user_device(1, "user123", "device456")
            .await
            .unwrap();
        assert!(!result1);

        // Now setup mock for mark operation (set_nx_ex should succeed)
        let mut mock_client2 = MockRedisClient::new();
        mock_client2 = mock_client2.set_nx_ex_ret("identify:1:user123:device456", Ok(true));
        let cache2 = RedisIdentifyCache {
            redis_client: Arc::new(mock_client2),
            memory_cache: MemoryIdentifyCache::new(100, Duration::from_secs(300)), // 5 min TTL for test
            ttl_seconds: 86400, // 24 hours for test
        };

        // Mark as seen
        cache2
            .mark_seen_user_device(1, "user123", "device456")
            .await
            .unwrap();

        // Setup mock for second has_seen call (should find the key)
        let mut mock_client3 = MockRedisClient::new();
        mock_client3 = mock_client3.get_ret("identify:1:user123:device456", Ok("1".to_string()));
        let cache3 = RedisIdentifyCache {
            redis_client: Arc::new(mock_client3),
            memory_cache: MemoryIdentifyCache::new(100, Duration::from_secs(300)), // 5 min TTL for test
            ttl_seconds: 86400, // 24 hours for test
        };

        // Second call should return true (seen)
        let result2 = cache3
            .has_seen_user_device(1, "user123", "device456")
            .await
            .unwrap();
        assert!(result2);
    }

    #[tokio::test]
    async fn test_cache_different_teams_isolated() {
        // Setup mocks for two different teams
        let mut mock_client1 = MockRedisClient::new();
        mock_client1 = mock_client1.get_ret(
            "identify:1:user123:device456",
            Err(CustomRedisError::NotFound),
        );
        let cache1 = RedisIdentifyCache {
            redis_client: Arc::new(mock_client1),
            memory_cache: MemoryIdentifyCache::new(100, Duration::from_secs(300)), // 5 min TTL for test
            ttl_seconds: 86400, // 24 hours for test
        };

        let mut mock_client2 = MockRedisClient::new();
        mock_client2 = mock_client2.get_ret("identify:2:user123:device456", Ok("1".to_string()));
        let cache2 = RedisIdentifyCache {
            redis_client: Arc::new(mock_client2),
            memory_cache: MemoryIdentifyCache::new(100, Duration::from_secs(300)), // 5 min TTL for test
            ttl_seconds: 86400, // 24 hours for test
        };

        // Same user and device, different teams should be isolated
        let result1 = cache1
            .has_seen_user_device(1, "user123", "device456")
            .await
            .unwrap();
        let result2 = cache2
            .has_seen_user_device(2, "user123", "device456")
            .await
            .unwrap();

        assert!(!result1); // Team 1 hasn't seen it
        assert!(result2); // Team 2 has seen it
    }

    #[tokio::test]
    async fn test_cache_key_format_edge_cases() {
        // Test with special characters in user_id and device_id
        let key1 = RedisIdentifyCache::make_key(1, "user@123", "device:456");
        assert_eq!(key1, "identify:1:user%40123:device%3A456");

        // Test with empty strings
        let key2 = RedisIdentifyCache::make_key(1, "", "");
        assert_eq!(key2, "identify:1::");

        // Test with unicode characters
        let key3 = RedisIdentifyCache::make_key(1, "用户123", "设备456");
        assert_eq!(
            key3,
            "identify:1:%E7%94%A8%E6%88%B7123:%E8%AE%BE%E5%A4%87456"
        );

        // Test with negative team_id
        let key4 = RedisIdentifyCache::make_key(-1, "user123", "device456");
        assert_eq!(key4, "identify:-1:user123:device456");

        // Test with multiple colons in user_id and device_id
        let key5 = RedisIdentifyCache::make_key(1, "user:123:abc", "device:456:xyz");
        assert_eq!(key5, "identify:1:user%3A123%3Aabc:device%3A456%3Axyz");

        // Test with only colons (should be fully escaped)
        let key6 = RedisIdentifyCache::make_key(1, ":::", ":::"); // 3 colons each
        assert_eq!(key6, "identify:1:%3A%3A%3A:%3A%3A%3A");

        // Test with other special characters
        let key7 = RedisIdentifyCache::make_key(1, "user space", "device+plus");
        assert_eq!(key7, "identify:1:user%20space:device%2Bplus");
    }

    #[tokio::test]
    async fn test_cache_error_handling() {
        // Test Redis connection error during has_seen
        let mut mock_client = MockRedisClient::new();
        mock_client = mock_client.get_ret(
            "identify:1:user123:device456",
            Err(CustomRedisError::Other("Connection failed".to_string())),
        );
        let cache = RedisIdentifyCache {
            redis_client: Arc::new(mock_client),
            memory_cache: MemoryIdentifyCache::new(100, Duration::from_secs(300)), // 5 min TTL for test
            ttl_seconds: 86400, // 24 hours for test
        };

        let result = cache.has_seen_user_device(1, "user123", "device456").await;
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Redis error checking user-device"));

        // Test Redis connection error during mark_seen
        let mut mock_client2 = MockRedisClient::new();
        mock_client2 = mock_client2.set_nx_ex_ret(
            "identify:1:user123:device456",
            Err(CustomRedisError::Other("Connection failed".to_string())),
        );
        let cache2 = RedisIdentifyCache {
            redis_client: Arc::new(mock_client2),
            memory_cache: MemoryIdentifyCache::new(100, Duration::from_secs(300)), // 5 min TTL for test
            ttl_seconds: 86400, // 24 hours for test
        };

        let result2 = cache2
            .mark_seen_user_device(1, "user123", "device456")
            .await;
        assert!(result2.is_err());
        assert!(result2
            .unwrap_err()
            .to_string()
            .contains("Redis error marking user-device"));
    }

    #[tokio::test]
    async fn test_cache_mark_seen_twice_same_key() {
        // First mark_seen should succeed
        let mut mock_client1 = MockRedisClient::new();
        mock_client1 = mock_client1.set_nx_ex_ret("identify:1:user123:device456", Ok(true));
        let cache1 = RedisIdentifyCache {
            redis_client: Arc::new(mock_client1),
            memory_cache: MemoryIdentifyCache::new(100, Duration::from_secs(300)), // 5 min TTL for test
            ttl_seconds: 86400, // 24 hours for test
        };

        let result1 = cache1
            .mark_seen_user_device(1, "user123", "device456")
            .await;
        assert!(result1.is_ok());

        // Second mark_seen should also succeed (set_nx_ex doesn't fail if key exists)
        let mut mock_client2 = MockRedisClient::new();
        mock_client2 = mock_client2.set_nx_ex_ret("identify:1:user123:device456", Ok(false)); // false = key already existed
        let cache2 = RedisIdentifyCache {
            redis_client: Arc::new(mock_client2),
            memory_cache: MemoryIdentifyCache::new(100, Duration::from_secs(300)), // 5 min TTL for test
            ttl_seconds: 86400, // 24 hours for test
        };

        let result2 = cache2
            .mark_seen_user_device(1, "user123", "device456")
            .await;
        assert!(result2.is_ok());
    }

    #[tokio::test]
    async fn test_cache_with_different_user_device_combinations() {
        // Test different combinations of user_id and device_id
        let test_cases = vec![
            (1, "user1", "device1"),
            (1, "user1", "device2"), // Same user, different device
            (1, "user2", "device1"), // Different user, same device
            (2, "user1", "device1"), // Same user/device, different team
        ];

        for (team_id, user_id, device_id) in test_cases {
            // URL encode user_id and device_id for expected key
            let encoded_user_id = urlencoding::encode(user_id);
            let encoded_device_id = urlencoding::encode(device_id);
            let expected_key = format!("identify:{team_id}:{encoded_user_id}:{encoded_device_id}");
            let actual_key = RedisIdentifyCache::make_key(team_id, user_id, device_id);
            assert_eq!(actual_key, expected_key);
        }
    }

    #[tokio::test]
    async fn test_cache_colon_combinations_separate() {
        // Test that different colon combinations result in different cache keys
        // This ensures that similar-looking IDs with colons are properly isolated

        let mut mock_client = MockRedisClient::new();

        // Setup different responses for different key combinations
        mock_client =
            mock_client.get_ret("identify:1:foo%3Abar::baz", Err(CustomRedisError::NotFound)); // "foo:bar" + ":baz"
        mock_client = mock_client.get_ret(
            "identify:1:foo%3A:bar%3Abaz",
            Err(CustomRedisError::NotFound),
        ); // "foo:" + "bar:baz"

        let cache = RedisIdentifyCache {
            redis_client: Arc::new(mock_client),
            memory_cache: MemoryIdentifyCache::new(100, Duration::from_secs(300)), // 5 min TTL for test
            ttl_seconds: 86400, // 24 hours for test
        };

        // Test first combination: "foo:bar" + ":baz"
        let result1 = cache
            .has_seen_user_device(1, "foo:bar", ":baz")
            .await
            .unwrap();
        assert!(!result1); // Should not be seen

        // Test second combination: "foo:" + "bar:baz"
        let result2 = cache
            .has_seen_user_device(1, "foo:", "bar:baz")
            .await
            .unwrap();
        assert!(!result2); // Should not be seen

        // Verify they produce different keys
        let key1 = RedisIdentifyCache::make_key(1, "foo:bar", ":baz");
        let key2 = RedisIdentifyCache::make_key(1, "foo:", "bar:baz");
        assert_ne!(
            key1, key2,
            "Keys should be different for different colon combinations"
        );

        // Test that marking one doesn't affect the other
        let mut mock_client2 = MockRedisClient::new();
        mock_client2 = mock_client2.set_nx_ex_ret("identify:1:foo%3Abar:%3Abaz", Ok(true));
        let cache2 = RedisIdentifyCache {
            redis_client: Arc::new(mock_client2),
            memory_cache: MemoryIdentifyCache::new(100, Duration::from_secs(300)), // 5 min TTL for test
            ttl_seconds: 86400, // 24 hours for test
        };

        // Mark first combination as seen (this should succeed)
        let mark_result = cache2.mark_seen_user_device(1, "foo:bar", ":baz").await;
        assert!(
            mark_result.is_ok(),
            "Marking first combination should succeed"
        );

        // Check that second combination is still not seen
        let mut mock_client3 = MockRedisClient::new();
        mock_client3 = mock_client3.get_ret(
            "identify:1:foo%3A:bar%3Abaz",
            Err(CustomRedisError::NotFound),
        );
        let cache3 = RedisIdentifyCache {
            redis_client: Arc::new(mock_client3),
            memory_cache: MemoryIdentifyCache::new(100, Duration::from_secs(300)), // 5 min TTL for test
            ttl_seconds: 86400, // 24 hours for test
        };

        let result3 = cache3
            .has_seen_user_device(1, "foo:", "bar:baz")
            .await
            .unwrap();
        assert!(!result3, "Second combination should still be unseen");
    }

    #[tokio::test]
    async fn test_cache_redis_url_validation() {
        // Test that empty Redis URL now fails at Redis client level (not our validation)
        let result = RedisIdentifyCache::new("", 3600, 100, 300).await;
        assert!(result.is_err());
        // Should fail due to Redis client initialization, not our validation

        // Test with invalid Redis URL
        let result2 = RedisIdentifyCache::new("invalid://url", 7200, 100, 300).await;
        assert!(result2.is_err());
        // Should fail due to Redis client initialization
    }

    #[tokio::test]
    async fn test_two_tier_cache_behavior() {
        // Test that memory cache (L1) serves requests without hitting Redis (L2)
        let mut mock_client = MockRedisClient::new();

        // Setup Redis to return NotFound initially
        mock_client = mock_client.get_ret(
            "identify:1:user123:device456",
            Err(CustomRedisError::NotFound),
        );
        // Setup Redis to succeed on set
        mock_client = mock_client.set_nx_ex_ret("identify:1:user123:device456", Ok(true));

        let cache = RedisIdentifyCache {
            redis_client: Arc::new(mock_client),
            memory_cache: MemoryIdentifyCache::new(100, Duration::from_secs(300)),
            ttl_seconds: 86400,
        };

        // First check - should hit Redis (L2) and return false
        let result1 = cache
            .has_seen_user_device(1, "user123", "device456")
            .await
            .unwrap();
        assert!(!result1);

        // Mark as seen - should store in both L1 and L2
        cache
            .mark_seen_user_device(1, "user123", "device456")
            .await
            .unwrap();

        // Second check - should hit memory cache (L1) and return true without touching Redis
        let result2 = cache
            .has_seen_user_device(1, "user123", "device456")
            .await
            .unwrap();
        assert!(result2);
    }
}
