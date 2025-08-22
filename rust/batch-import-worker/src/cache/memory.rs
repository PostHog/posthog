use std::collections::HashMap;
use std::sync::Arc;

use anyhow::Error;
use async_trait::async_trait;
use tokio::sync::RwLock;

use super::{AmplitudeIdentifyCache, CacheStats};

/// In-memory implementation of AmplitudeIdentifyCache using a HashMap
/// This is suitable for development and single-instance deployments
#[derive(Debug)]
pub struct MemoryAmplitudeIdentifyCache {
    /// Map from team_id to (user_id -> Set<device_id>)
    /// Using nested structure for efficient lookups and team isolation
    cache: Arc<RwLock<HashMap<i32, HashMap<String, std::collections::HashSet<String>>>>>,
    stats: Arc<RwLock<CacheStats>>,
    ttl_seconds: u64,
}

impl MemoryAmplitudeIdentifyCache {
    pub fn new() -> Self {
        Self::with_ttl(86400) // Default 24 hours
    }

    pub fn with_ttl(ttl_seconds: u64) -> Self {
        Self {
            cache: Arc::new(RwLock::new(HashMap::new())),
            stats: Arc::new(RwLock::new(CacheStats {
                total_entries: 0,
                cache_hits: 0,
                cache_misses: 0,
            })),
            ttl_seconds,
        }
    }
}

impl Default for MemoryAmplitudeIdentifyCache {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl AmplitudeIdentifyCache for MemoryAmplitudeIdentifyCache {
    async fn has_seen_user_device(&self, team_id: i32, user_id: &str, device_id: &str) -> Result<bool, Error> {
        let cache = self.cache.read().await;

        let has_seen = if let Some(team_map) = cache.get(&team_id) {
            if let Some(device_set) = team_map.get(user_id) {
                device_set.contains(device_id)
            } else {
                false
            }
        } else {
            false
        };

        // Update stats
        let mut stats = self.stats.write().await;
        if has_seen {
            stats.cache_hits += 1;
        } else {
            stats.cache_misses += 1;
        }

        Ok(has_seen)
    }

    async fn mark_seen_user_device(&self, team_id: i32, user_id: &str, device_id: &str) -> Result<(), Error> {
        let mut cache = self.cache.write().await;

        let team_map = cache.entry(team_id).or_insert_with(HashMap::new);
        let device_set = team_map.entry(user_id.to_string()).or_insert_with(std::collections::HashSet::new);

        let was_new = device_set.insert(device_id.to_string());

        // Only increment total_entries if this was actually a new entry
        if was_new {
            let mut stats = self.stats.write().await;
            stats.total_entries += 1;
        }

        Ok(())
    }

    async fn stats(&self) -> Result<CacheStats, Error> {
        let stats = self.stats.read().await;
        Ok(stats.clone())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_memory_cache_basic_operations() {
        let cache = MemoryAmplitudeIdentifyCache::new();

        // Initially should not have seen the user-device pair
        assert!(!cache.has_seen_user_device(1, "user123", "device456").await.unwrap());

        // Mark as seen
        cache.mark_seen_user_device(1, "user123", "device456").await.unwrap();

        // Now should have seen it
        assert!(cache.has_seen_user_device(1, "user123", "device456").await.unwrap());

        // Different device for same user should not be seen
        assert!(!cache.has_seen_user_device(1, "user123", "device789").await.unwrap());

        // Different user should not be seen
        assert!(!cache.has_seen_user_device(1, "user999", "device456").await.unwrap());
    }

    #[tokio::test]
    async fn test_memory_cache_team_isolation() {
        let cache = MemoryAmplitudeIdentifyCache::new();

        // Team 1
        cache.mark_seen_user_device(1, "user123", "device456").await.unwrap();
        assert!(cache.has_seen_user_device(1, "user123", "device456").await.unwrap());

        // Team 2 should not see team 1's data
        assert!(!cache.has_seen_user_device(2, "user123", "device456").await.unwrap());
    }

    #[tokio::test]
    async fn test_memory_cache_stats() {
        let cache = MemoryAmplitudeIdentifyCache::new();

        // Initial stats
        let stats = cache.stats().await.unwrap();
        assert_eq!(stats.total_entries, 0);
        assert_eq!(stats.cache_hits, 0);
        assert_eq!(stats.cache_misses, 0);

        // Miss
        cache.has_seen_user_device(1, "user123", "device456").await.unwrap();
        let stats = cache.stats().await.unwrap();
        assert_eq!(stats.cache_misses, 1);

        // Mark as seen
        cache.mark_seen_user_device(1, "user123", "device456").await.unwrap();
        let stats = cache.stats().await.unwrap();
        assert_eq!(stats.total_entries, 1);

        // Hit
        cache.has_seen_user_device(1, "user123", "device456").await.unwrap();
        let stats = cache.stats().await.unwrap();
        assert_eq!(stats.cache_hits, 1);
        assert_eq!(stats.cache_misses, 1);
        assert_eq!(stats.total_entries, 1);
    }

    #[tokio::test]
    async fn test_memory_cache_duplicate_marks() {
        let cache = MemoryAmplitudeIdentifyCache::new();

        // Mark same pair multiple times
        cache.mark_seen_user_device(1, "user123", "device456").await.unwrap();
        cache.mark_seen_user_device(1, "user123", "device456").await.unwrap();
        cache.mark_seen_user_device(1, "user123", "device456").await.unwrap();

        // Should only count as one entry
        let stats = cache.stats().await.unwrap();
        assert_eq!(stats.total_entries, 1);
    }
}
