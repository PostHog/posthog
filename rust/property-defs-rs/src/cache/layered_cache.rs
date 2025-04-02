use std::sync::Arc;
use quick_cache::sync::Cache as InMemoryCache;
use crate::types::Update;
use super::secondary_cache::SecondaryCache;
use tracing::warn;

#[derive(Clone)]
pub struct LayeredCache<T: SecondaryCache> {
    memory: Arc<InMemoryCache<Update, ()>>,
    secondary: T,
}

impl<T: SecondaryCache> LayeredCache<T> {
    pub fn new(memory: Arc<InMemoryCache<Update, ()>>, secondary: T) -> Self {
        Self { memory, secondary }
    }

    pub async fn insert_batch(&self, keys: Vec<Update>) {
        let mut new_keys = Vec::new();

        for key in keys {
            if self.memory.get(&key).is_none() {
                new_keys.push(key.clone());
            }
            self.memory.insert(key, ());
        }

        if !new_keys.is_empty() {
            if let Err(e) = self.secondary.insert_batch(&new_keys).await {
                warn!("Failed to insert batch into secondary cache: {}", e);
            }
        }
    }

    pub async fn get_batch(&self, keys: &[Update]) -> Vec<Update> {
        let mut found = Vec::new();
        let mut missing = Vec::new();

        for key in keys {
            if self.memory.get(key).is_some() {
                found.push(key.clone());
            } else {
                missing.push(key.clone());
            }
        }

        if !missing.is_empty() {
            match self.secondary.get_batch(&missing).await {
                Ok(updates) => {
                    for update in updates {
                        self.memory.insert(update.clone(), ());
                        found.push(update);
                    }
                }
                Err(e) => {
                    warn!("Failed to get batch from secondary cache: {}", e);
                }
            }
        }

        found
    }

    pub fn len(&self) -> usize {
        self.memory.len()
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
        let secondary = NoOpCache::new();
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

        cache.insert_batch(events.clone()).await;
        let found = cache.get_batch(&events).await;
        assert_eq!(found.len(), events.len());
    }

    #[tokio::test]
    async fn test_layered_cache_large() {
        let memory = Arc::new(InMemoryCache::new(10000));
        let secondary = NoOpCache::new();
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

        cache.insert_batch(events.clone()).await;
        let found = cache.get_batch(&events).await;
        assert_eq!(found.len(), events.len());
    }
}
