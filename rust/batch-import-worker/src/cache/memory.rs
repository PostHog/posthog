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

#[cfg(test)]
mod tests {
    use super::*;
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
}
