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

    pub fn insert_batch(&mut self, keys: Vec<Update>) {
        let mut new_keys = Vec::new();

        for key in keys {
            if self.memory.get(&key).is_none() {
                new_keys.push(key.clone());
            }
            self.memory.insert(key, ());
        }

        if !new_keys.is_empty() {
            if let Err(e) = self.secondary.insert_batch(&new_keys) {
                warn!("Failed to insert batch into secondary cache: {}", e);
            }
        }
    }

    pub fn get_batch(&self, keys: &[Update]) -> Vec<Update> {
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
            match self.secondary.get_batch(&missing) {
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
    use crate::types::EventDefinition;
    use super::super::redis_cache::RedisCache;
    use super::super::noop_cache::NoOpCache;
    use chrono::Utc;

    #[test]
    fn test_layered_cache_batch() {
        let noop = NoOpCache::new();
        let mut cache = LayeredCache::new(Arc::new(InMemoryCache::new(100)), noop);

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

        cache.insert_batch(events.clone());
        let found = cache.get_batch(&events);
        assert_eq!(found.len(), events.len());
    }

    #[test]
    fn test_layered_cache_batch_with_redis() {
        let redis = RedisCache::new("redis://127.0.0.1/", 3600).unwrap();
        let mut cache = LayeredCache::new(Arc::new(InMemoryCache::new(100)), redis);

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

        cache.insert_batch(events.clone());
        let found = cache.get_batch(&events);
        assert_eq!(found.len(), events.len());
    }
}
