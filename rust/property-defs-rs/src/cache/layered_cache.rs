use std::sync::Arc;
use quick_cache::sync::Cache as InMemoryCache;
use crate::types::Update;
use crate::errors::CacheError;
use super::{SecondaryCache, CacheOperations};
use tracing::warn;

#[derive(Clone)]
pub struct LayeredCache {
    memory: Arc<InMemoryCache<Update, ()>>,
    secondary: SecondaryCache,
}

impl LayeredCache {
    pub fn new(memory: Arc<InMemoryCache<Update, ()>>, secondary: SecondaryCache) -> Self {
        Self { memory, secondary }
    }

    pub async fn insert_batch(&self, keys: Vec<Update>) {
        let mut new_keys = Vec::new();

        for key in &keys {
            if self.memory.get(key).is_none() {
                new_keys.push(key.clone());
            }
            self.memory.insert(key.clone(), ());
        }

        if !new_keys.is_empty() {
            match self.secondary.insert_batch(&new_keys).await {
                Ok(()) => (),
                Err(CacheError::NotSupported) => (),
                Err(e) => warn!("Failed to insert batch into secondary cache: {}", e),
            }
        }
    }

    pub async fn filter_cached_updates(&self, updates: Vec<Update>) -> Vec<Update> {
        let mut check_secondary = Vec::new();

        // First pass: check memory cache and collect items not in memory
        for update in &updates {
            if self.memory.get(update).is_none() {
                check_secondary.push(update.clone());
            }
        }

        if check_secondary.is_empty() {
            return Vec::new();
        }

        // Second pass: check secondary cache
        match self.secondary.filter_cached_updates(&check_secondary).await {
            Ok(not_in_cache) => not_in_cache,
            Err(CacheError::NotSupported) => check_secondary,
            Err(e) => {
                warn!("Failed to check secondary cache: {}", e);
                check_secondary
            }
        }
    }

    pub fn len(&self) -> usize {
        self.memory.len()
    }

    pub fn remove(&self, key: &Update) -> Option<()> {
        self.memory.remove(key).map(|_| ())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cache::noop_cache::NoOpCache;
    use crate::types::{Update, EventDefinition};
    use chrono::Utc;

    #[tokio::test]
    async fn test_layered_cache_basic() {
        let memory = Arc::new(InMemoryCache::new(1000));
        let secondary = SecondaryCache::NoOp(NoOpCache::new());
        let cache = LayeredCache::new(memory, secondary);

        let events: Vec<Update> = (0..3)
            .map(|i| {
                Update::Event(EventDefinition {
                    name: format!("test_{}", i),
                    team_id: 1,
                    project_id: 1,
                    last_seen_at: Utc::now(),
                })
            })
            .collect();

        // First insert the events
        cache.insert_batch(events.clone()).await;

        // Then verify none of them are returned by filter_cached_updates
        let not_in_cache = cache.filter_cached_updates(events.clone()).await;
        assert_eq!(not_in_cache.len(), 0);
    }

    #[tokio::test]
    async fn test_layered_cache_large() {
        let memory = Arc::new(InMemoryCache::new(10000));
        let secondary = SecondaryCache::NoOp(NoOpCache::new());
        let cache = LayeredCache::new(memory, secondary);

        let events: Vec<Update> = (0..3)
            .map(|i| {
                Update::Event(EventDefinition {
                    name: format!("test_{}", i),
                    team_id: 1,
                    project_id: 1,
                    last_seen_at: Utc::now(),
                })
            })
            .collect();

        // First insert the events
        cache.insert_batch(events.clone()).await;

        // Then verify none of them are returned by filter_cached_updates
        let not_in_cache = cache.filter_cached_updates(events.clone()).await;
        assert_eq!(not_in_cache.len(), 0);
    }
}
