use anyhow::Error;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// Entry in the memory cache with expiration time
#[derive(Debug, Clone)]
struct CacheEntry {
    expires_at: Instant,
}

/// In-memory cache with TTL and size-based eviction
#[derive(Debug, Clone)]
pub struct MemoryCache {
    entries: Arc<Mutex<HashMap<String, CacheEntry>>>,
    max_size: usize,
    ttl: Duration,
}

impl MemoryCache {
    /// Create a new memory cache with specified max size and TTL
    pub fn new(max_size: usize, ttl: Duration) -> Self {
        Self {
            entries: Arc::new(Mutex::new(HashMap::new())),
            max_size,
            ttl,
        }
    }

    /// Check if a key exists and is not expired
    pub fn contains(&self, key: &str) -> bool {
        let mut entries = self.entries.lock().unwrap();
        self.cleanup_expired(&mut entries);

        if let Some(entry) = entries.get(key) {
            if entry.expires_at > Instant::now() {
                return true;
            } else {
                // Remove expired entry
                entries.remove(key);
            }
        }
        false
    }

    /// Insert a key into the cache
    pub fn insert(&self, key: String) {
        let mut entries = self.entries.lock().unwrap();
        self.cleanup_expired(&mut entries);

        // Evict oldest entries if we're at capacity
        while entries.len() >= self.max_size {
            if let Some(oldest_key) = self.find_oldest_key(&entries) {
                entries.remove(&oldest_key);
            } else {
                break;
            }
        }

        let entry = CacheEntry {
            expires_at: Instant::now() + self.ttl,
        };
        entries.insert(key, entry);
    }

    /// Remove expired entries from the cache
    fn cleanup_expired(&self, entries: &mut HashMap<String, CacheEntry>) {
        let now = Instant::now();
        entries.retain(|_, entry| entry.expires_at > now);
    }

    /// Find the oldest entry in the cache (for eviction)
    fn find_oldest_key(&self, entries: &HashMap<String, CacheEntry>) -> Option<String> {
        entries
            .iter()
            .min_by_key(|(_, entry)| entry.expires_at)
            .map(|(key, _)| key.clone())
    }

    /// Get current cache size (for debugging/metrics)
    pub fn size(&self) -> usize {
        let mut entries = self.entries.lock().unwrap();
        self.cleanup_expired(&mut entries);
        entries.len()
    }

    /// Clear all entries from the cache
    pub fn clear(&self) {
        let mut entries = self.entries.lock().unwrap();
        entries.clear();
    }
}

/// Memory-only implementation of IdentifyCache for when Redis is not available
#[derive(Debug, Clone)]
pub struct MemoryIdentifyCache {
    cache: MemoryCache,
}

impl MemoryIdentifyCache {
    /// Create a new memory-only identify cache
    pub fn new(max_size: usize, ttl: Duration) -> Self {
        Self {
            cache: MemoryCache::new(max_size, ttl),
        }
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
        format!(
            "identify:{}:{}:{}",
            team_id, encoded_user_id, encoded_device_id
        )
    }
}

#[async_trait::async_trait]
impl super::IdentifyCache for MemoryIdentifyCache {
    async fn has_seen_user_device(
        &self,
        team_id: i32,
        user_id: &str,
        device_id: &str,
    ) -> Result<bool, Error> {
        let key = Self::make_key(team_id, user_id, device_id);
        Ok(self.cache.contains(&key))
    }

    async fn mark_seen_user_device(
        &self,
        team_id: i32,
        user_id: &str,
        device_id: &str,
    ) -> Result<(), Error> {
        let key = Self::make_key(team_id, user_id, device_id);
        self.cache.insert(key);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cache::IdentifyCache;
    use std::thread;

    #[test]
    fn test_memory_cache_basic_operations() {
        let cache = MemoryCache::new(10, Duration::from_secs(1));

        // Should not contain key initially
        assert!(!cache.contains("key1"));

        // Insert and check
        cache.insert("key1".to_string());
        assert!(cache.contains("key1"));
        assert_eq!(cache.size(), 1);
    }

    #[test]
    fn test_memory_cache_ttl_expiry() {
        let cache = MemoryCache::new(10, Duration::from_millis(50));

        cache.insert("key1".to_string());
        assert!(cache.contains("key1"));

        // Wait for expiry
        thread::sleep(Duration::from_millis(60));
        assert!(!cache.contains("key1"));
        assert_eq!(cache.size(), 0);
    }

    #[test]
    fn test_memory_cache_size_eviction() {
        let cache = MemoryCache::new(2, Duration::from_secs(10));

        cache.insert("key1".to_string());
        cache.insert("key2".to_string());
        assert_eq!(cache.size(), 2);

        // Adding third item should evict oldest
        cache.insert("key3".to_string());
        assert_eq!(cache.size(), 2);

        // key1 should be evicted (oldest)
        assert!(!cache.contains("key1"));
        assert!(cache.contains("key2"));
        assert!(cache.contains("key3"));
    }

    #[test]
    fn test_memory_cache_clear() {
        let cache = MemoryCache::new(10, Duration::from_secs(1));

        cache.insert("key1".to_string());
        cache.insert("key2".to_string());
        assert_eq!(cache.size(), 2);

        cache.clear();
        assert_eq!(cache.size(), 0);
        assert!(!cache.contains("key1"));
        assert!(!cache.contains("key2"));
    }

    #[tokio::test]
    async fn test_memory_identify_cache_basic() {
        let cache = MemoryIdentifyCache::new(100, Duration::from_secs(10));

        // Should not be seen initially
        let result1 = cache
            .has_seen_user_device(1, "user123", "device456")
            .await
            .unwrap();
        assert_eq!(result1, false);

        // Mark as seen
        cache
            .mark_seen_user_device(1, "user123", "device456")
            .await
            .unwrap();

        // Should now be seen
        let result2 = cache
            .has_seen_user_device(1, "user123", "device456")
            .await
            .unwrap();
        assert_eq!(result2, true);
    }

    #[tokio::test]
    async fn test_memory_identify_cache_team_isolation() {
        let cache = MemoryIdentifyCache::new(100, Duration::from_secs(10));

        // Mark for team 1
        cache
            .mark_seen_user_device(1, "user123", "device456")
            .await
            .unwrap();

        // Should be seen for team 1
        let result1 = cache
            .has_seen_user_device(1, "user123", "device456")
            .await
            .unwrap();
        assert_eq!(result1, true);

        // Should not be seen for team 2 (different team)
        let result2 = cache
            .has_seen_user_device(2, "user123", "device456")
            .await
            .unwrap();
        assert_eq!(result2, false);
    }

    #[tokio::test]
    async fn test_memory_identify_cache_key_encoding() {
        let cache = MemoryIdentifyCache::new(100, Duration::from_secs(10));

        // Test with special characters
        cache
            .mark_seen_user_device(1, "user:123", "device@456")
            .await
            .unwrap();
        let result = cache
            .has_seen_user_device(1, "user:123", "device@456")
            .await
            .unwrap();
        assert_eq!(result, true);

        // Verify key encoding creates different keys for different combinations
        let key1 = MemoryIdentifyCache::make_key(1, "user:123", "device");
        let key2 = MemoryIdentifyCache::make_key(1, "user", ":123device");
        assert_ne!(key1, key2);
    }

    #[tokio::test]
    async fn test_memory_identify_cache_different_combinations() {
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
                .await
                .unwrap();
            assert_eq!(result1, false);

            // Mark as seen
            cache
                .mark_seen_user_device(team_id, user_id, device_id)
                .await
                .unwrap();

            // Should now be seen
            let result2 = cache
                .has_seen_user_device(team_id, user_id, device_id)
                .await
                .unwrap();
            assert_eq!(result2, true);
        }

        // Verify all combinations are isolated from each other
        assert!(cache
            .has_seen_user_device(1, "user1", "device1")
            .await
            .unwrap());
        assert!(cache
            .has_seen_user_device(1, "user1", "device2")
            .await
            .unwrap());
        assert!(cache
            .has_seen_user_device(1, "user2", "device1")
            .await
            .unwrap());
        assert!(cache
            .has_seen_user_device(2, "user1", "device1")
            .await
            .unwrap());

        // But these combinations should not be seen
        assert!(!cache
            .has_seen_user_device(1, "user2", "device2")
            .await
            .unwrap());
        assert!(!cache
            .has_seen_user_device(2, "user2", "device1")
            .await
            .unwrap());
    }

    #[tokio::test]
    async fn test_memory_identify_cache_colon_combinations() {
        let cache = MemoryIdentifyCache::new(100, Duration::from_secs(10));

        // Test that different colon combinations result in different cache behavior
        // This ensures that similar-looking IDs with colons are properly isolated

        // Mark first combination: "foo:bar" + ":baz"
        cache
            .mark_seen_user_device(1, "foo:bar", ":baz")
            .await
            .unwrap();

        // First combination should be seen
        let result1 = cache
            .has_seen_user_device(1, "foo:bar", ":baz")
            .await
            .unwrap();
        assert_eq!(result1, true);

        // Second combination: "foo:" + "bar:baz" should NOT be seen
        let result2 = cache
            .has_seen_user_device(1, "foo:", "bar:baz")
            .await
            .unwrap();
        assert_eq!(result2, false);

        // Verify they produce different keys
        let key1 = MemoryIdentifyCache::make_key(1, "foo:bar", ":baz");
        let key2 = MemoryIdentifyCache::make_key(1, "foo:", "bar:baz");
        assert_ne!(
            key1, key2,
            "Keys should be different for different colon combinations"
        );

        // Mark second combination
        cache
            .mark_seen_user_device(1, "foo:", "bar:baz")
            .await
            .unwrap();

        // Now both should be seen
        assert!(cache
            .has_seen_user_device(1, "foo:bar", ":baz")
            .await
            .unwrap());
        assert!(cache
            .has_seen_user_device(1, "foo:", "bar:baz")
            .await
            .unwrap());
    }

    #[tokio::test]
    async fn test_memory_identify_cache_special_characters() {
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
            let result1 = cache
                .has_seen_user_device(1, user_id, device_id)
                .await
                .unwrap();
            assert_eq!(result1, false);

            // Mark as seen
            cache
                .mark_seen_user_device(1, user_id, device_id)
                .await
                .unwrap();

            // Should now be seen
            let result2 = cache
                .has_seen_user_device(1, user_id, device_id)
                .await
                .unwrap();
            assert_eq!(result2, true);
        }
    }
}
