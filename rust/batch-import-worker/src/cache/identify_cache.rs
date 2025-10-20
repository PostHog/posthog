use anyhow::Error;
use moka::sync::Cache;
use std::time::Duration;

/// Memory-only implementation of IdentifyCache using moka for when Redis is not available
#[derive(Clone)]
pub struct MemoryIdentifyCache {
    cache: Cache<String, ()>, // Key -> presence marker
}

impl MemoryIdentifyCache {
    /// Create a new memory-only identify cache
    pub fn new(max_capacity: u64, ttl: Duration) -> Self {
        let cache = Cache::builder()
            .time_to_live(ttl)
            .max_capacity(max_capacity)
            .build();

        Self { cache }
    }

    /// Create with default settings (10K entries, 30 min TTL)
    pub fn with_defaults() -> Self {
        Self::new(10_000, Duration::from_secs(30 * 60))
    }

    /// Generate cache key for user-device combination
    fn make_key(team_id: i32, user_id: &str, device_id: &str) -> String {
        // URL encode user_id and device_id to prevent key format conflicts
        let encoded_user_id = urlencoding::encode(user_id);
        let encoded_device_id = urlencoding::encode(device_id);
        format!("identify:{team_id}:{encoded_user_id}:{encoded_device_id}")
    }
}

impl std::fmt::Debug for MemoryIdentifyCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("MemoryIdentifyCache")
            .field("cache", &"<moka cache>")
            .finish()
    }
}

impl super::IdentifyCache for MemoryIdentifyCache {
    fn has_seen_user_device(
        &self,
        team_id: i32,
        user_id: &str,
        device_id: &str,
    ) -> Result<bool, Error> {
        let key = Self::make_key(team_id, user_id, device_id);
        Ok(self.cache.get(&key).is_some())
    }

    fn mark_seen_user_device(
        &self,
        team_id: i32,
        user_id: &str,
        device_id: &str,
    ) -> Result<(), Error> {
        let key = Self::make_key(team_id, user_id, device_id);
        self.cache.insert(key, ());
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cache::IdentifyCache;
    use std::thread;

    #[test]
    fn test_memory_identify_cache_basic() {
        let cache = MemoryIdentifyCache::new(100, Duration::from_secs(10));

        // Should not be seen initially
        let result1 = cache
            .has_seen_user_device(1, "user123", "device456")
            .unwrap();
        assert!(!result1);

        // Mark as seen
        cache
            .mark_seen_user_device(1, "user123", "device456")
            .unwrap();

        // Should now be seen
        let result2 = cache
            .has_seen_user_device(1, "user123", "device456")
            .unwrap();
        assert!(result2);
    }

    #[test]
    fn test_memory_identify_cache_team_isolation() {
        let cache = MemoryIdentifyCache::new(100, Duration::from_secs(10));

        // Mark for team 1
        cache
            .mark_seen_user_device(1, "user123", "device456")
            .unwrap();

        // Should be seen for team 1
        let result1 = cache
            .has_seen_user_device(1, "user123", "device456")
            .unwrap();
        assert!(result1);

        // Should not be seen for team 2 (different team)
        let result2 = cache
            .has_seen_user_device(2, "user123", "device456")
            .unwrap();
        assert!(!result2);
    }

    #[test]
    fn test_memory_identify_cache_key_encoding() {
        let cache = MemoryIdentifyCache::new(100, Duration::from_secs(10));

        // Test with special characters
        cache
            .mark_seen_user_device(1, "user:123", "device@456")
            .unwrap();
        let result = cache
            .has_seen_user_device(1, "user:123", "device@456")
            .unwrap();
        assert!(result);

        // Verify key encoding creates different keys for different combinations
        let key1 = MemoryIdentifyCache::make_key(1, "user:123", "device");
        let key2 = MemoryIdentifyCache::make_key(1, "user", ":123device");
        assert_ne!(key1, key2);
    }

    #[test]
    fn test_memory_identify_cache_ttl_expiry() {
        let cache = MemoryIdentifyCache::new(100, Duration::from_millis(100));

        // Should not be seen initially
        let result1 = cache
            .has_seen_user_device(1, "user123", "device456")
            .unwrap();
        assert!(!result1);

        // Mark as seen
        cache
            .mark_seen_user_device(1, "user123", "device456")
            .unwrap();

        // Should now be seen
        let result2 = cache
            .has_seen_user_device(1, "user123", "device456")
            .unwrap();
        assert!(result2);

        // Wait for TTL expiry
        thread::sleep(Duration::from_millis(150));

        // Should no longer be seen after expiry
        let result3 = cache
            .has_seen_user_device(1, "user123", "device456")
            .unwrap();
        assert!(!result3);
    }

    #[test]
    fn test_memory_identify_cache_different_combinations() {
        let cache = MemoryIdentifyCache::new(100, Duration::from_secs(10));

        // Test different combinations of user_id and device_id
        let test_cases = vec![
            (1, "user1", "device1"),
            (1, "user1", "device2"), // Same user, different device
            (1, "user2", "device1"), // Different user, same device
            (2, "user1", "device1"), // Same user/device, different team
        ];

        for (team_id, user_id, device_id) in test_cases {
            // Should not be seen initially
            let result1 = cache
                .has_seen_user_device(team_id, user_id, device_id)
                .unwrap();
            assert!(!result1);

            // Mark as seen
            cache
                .mark_seen_user_device(team_id, user_id, device_id)
                .unwrap();

            // Should now be seen
            let result2 = cache
                .has_seen_user_device(team_id, user_id, device_id)
                .unwrap();
            assert!(result2);
        }

        // Verify all combinations are isolated from each other
        assert!(cache.has_seen_user_device(1, "user1", "device1").unwrap());
        assert!(cache.has_seen_user_device(1, "user1", "device2").unwrap());
        assert!(cache.has_seen_user_device(1, "user2", "device1").unwrap());
        assert!(cache.has_seen_user_device(2, "user1", "device1").unwrap());

        // But these combinations should not be seen
        assert!(!cache.has_seen_user_device(1, "user2", "device2").unwrap());
        assert!(!cache.has_seen_user_device(2, "user2", "device1").unwrap());
    }

    #[test]
    fn test_memory_identify_cache_colon_combinations() {
        let cache = MemoryIdentifyCache::new(100, Duration::from_secs(10));

        // Test that different colon combinations result in different cache behavior
        // This ensures that similar-looking IDs with colons are properly isolated

        // Mark first combination: "foo:bar" + ":baz"
        cache.mark_seen_user_device(1, "foo:bar", ":baz").unwrap();

        // First combination should be seen
        let result1 = cache.has_seen_user_device(1, "foo:bar", ":baz").unwrap();
        assert!(result1);

        // Second combination: "foo:" + "bar:baz" should NOT be seen
        let result2 = cache.has_seen_user_device(1, "foo:", "bar:baz").unwrap();
        assert!(!result2);

        // Verify they produce different keys
        let key1 = MemoryIdentifyCache::make_key(1, "foo:bar", ":baz");
        let key2 = MemoryIdentifyCache::make_key(1, "foo:", "bar:baz");
        assert_ne!(
            key1, key2,
            "Keys should be different for different colon combinations"
        );

        // Mark second combination
        cache.mark_seen_user_device(1, "foo:", "bar:baz").unwrap();

        // Now both should be seen
        assert!(cache.has_seen_user_device(1, "foo:bar", ":baz").unwrap());
        assert!(cache.has_seen_user_device(1, "foo:", "bar:baz").unwrap());
    }

    #[test]
    fn test_memory_identify_cache_special_characters() {
        let cache = MemoryIdentifyCache::new(100, Duration::from_secs(10));

        // Test various special characters that need URL encoding
        let test_cases = vec![
            ("user@123", "device:456"),
            ("user space", "device+plus"),
            ("用户123", "设备456"),   // Unicode
            (":::", ":::"),           // Only colons
            ("user%20", "device%40"), // Already encoded characters
        ];

        for (user_id, device_id) in test_cases {
            // Should not be seen initially
            let result1 = cache.has_seen_user_device(1, user_id, device_id).unwrap();
            assert!(!result1);

            // Mark as seen
            cache.mark_seen_user_device(1, user_id, device_id).unwrap();

            // Should now be seen
            let result2 = cache.has_seen_user_device(1, user_id, device_id).unwrap();
            assert!(result2);
        }
    }
}
