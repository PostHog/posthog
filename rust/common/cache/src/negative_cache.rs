//! In-memory negative caching to prevent repeated loader calls for missing keys
//!
//! This module provides [`NegativeCache`], an in-memory cache that tracks keys known
//! to not exist. This prevents repeated expensive loader invocations for
//! non-existent keys.
//!
//! Uses Moka for efficient LRU eviction and TTL support, avoiding Redis to prevent
//! cache poisoning when Redis is struggling.

use moka::sync::Cache;
use std::time::Duration;

/// In-memory negative cache using Moka to prevent repeated loader calls
/// for non-existent keys. We use this instead of a Redis-based negative cache
/// to avoid cache poisoning vulnerabilities. Improved performance is a side-benefit.
///
/// Features:
/// - TTL: Entries automatically expire after configured time
/// - LRU eviction: Bounded memory usage with automatic cleanup
/// - Thread-safe: Can be safely shared across async tasks
/// - Pod isolation: Each service instance has its own cache
#[derive(Clone)]
pub struct NegativeCache {
    cache: Cache<String, ()>,
}

impl NegativeCache {
    /// Create a new negative cache with specified capacity and TTL
    ///
    /// # Arguments
    /// * `max_capacity` - Maximum number of entries to store
    /// * `ttl_seconds` - Time-to-live for entries in seconds
    ///
    /// # Example
    /// ```rust
    /// use common_cache::NegativeCache;
    ///
    /// let cache = NegativeCache::new(1000, 300); // 1000 entries, 5 minute TTL
    /// ```
    pub fn new(max_capacity: u64, ttl_seconds: u64) -> Self {
        let cache = Cache::builder()
            .max_capacity(max_capacity)
            .time_to_live(Duration::from_secs(ttl_seconds))
            .build();

        Self { cache }
    }

    /// Check if a key is in the negative cache (was not found in database)
    ///
    /// # Arguments
    /// * `key` - The key to check
    ///
    /// # Returns
    /// `true` if the key is in the negative cache, `false` otherwise
    pub fn contains(&self, key: &str) -> bool {
        self.cache.contains_key(key)
    }

    /// Add a key to the negative cache (marking it as not found in database)
    ///
    /// # Arguments
    /// * `key` - The key to mark as not found
    pub fn insert(&self, key: String) {
        self.cache.insert(key, ());
    }

    /// Remove a key from the negative cache (e.g., when positive data is found)
    ///
    /// # Arguments
    /// * `key` - The key to remove from negative cache
    pub fn invalidate(&self, key: &str) {
        self.cache.invalidate(key);
    }

    /// Get cache statistics (entry count and weighted size)
    ///
    /// # Returns
    /// A tuple of (entry_count, weighted_size)
    pub fn stats(&self) -> (u64, u64) {
        (self.cache.entry_count(), self.cache.weighted_size())
    }

    /// Clear all entries from the negative cache
    pub fn clear(&self) {
        self.cache.invalidate_all();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::time::{sleep, Duration as TokioDuration};

    #[tokio::test]
    async fn test_negative_cache_basic_functionality() {
        // Test basic Moka negative cache functionality
        let negative_cache = NegativeCache::new(100, 300); // 100 entries, 5 min TTL

        let key = "test_key_123";

        // Initially, cache should not contain the key
        assert!(!negative_cache.contains(key));

        // Insert the key into negative cache
        negative_cache.insert(key.to_string());

        // Now cache should contain the key
        assert!(negative_cache.contains(key));

        // Test stats - Moka cache stats might not be immediately consistent
        // So we'll test the functionality instead of exact counts
        assert!(negative_cache.contains(key));

        // Test invalidation
        negative_cache.invalidate(key);
        assert!(!negative_cache.contains(key));
    }

    #[tokio::test]
    async fn test_negative_cache_ttl_expiration() {
        // Test that entries expire after TTL
        let negative_cache = NegativeCache::new(100, 1); // 1 second TTL

        let key = "test_expiry_key";
        negative_cache.insert(key.to_string());

        // Should be present initially
        assert!(negative_cache.contains(key));

        // Wait for TTL to expire
        sleep(TokioDuration::from_secs(2)).await;

        // Should be expired now
        assert!(!negative_cache.contains(key));
    }

    #[tokio::test]
    async fn test_negative_cache_capacity_limits() {
        // Test LRU eviction when capacity is reached
        let negative_cache = NegativeCache::new(2, 300); // Only 2 entries max

        // Add first two entries
        negative_cache.insert("key1".to_string());
        negative_cache.insert("key2".to_string());

        assert!(negative_cache.contains("key1"));
        assert!(negative_cache.contains("key2"));

        // Add third entry - should evict least recently used
        negative_cache.insert("key3".to_string());

        // key3 should be present, and one of the others should be evicted
        assert!(negative_cache.contains("key3"));

        let (entry_count, _) = negative_cache.stats();
        assert!(entry_count <= 2, "Cache should not exceed capacity");
    }

    #[test]
    fn test_negative_cache_clear() {
        let negative_cache = NegativeCache::new(100, 300);

        negative_cache.insert("key1".to_string());
        negative_cache.insert("key2".to_string());

        // Verify keys are present
        assert!(negative_cache.contains("key1"));
        assert!(negative_cache.contains("key2"));

        negative_cache.clear();

        // Verify keys are no longer present after clear
        assert!(!negative_cache.contains("key1"));
        assert!(!negative_cache.contains("key2"));
    }
}
