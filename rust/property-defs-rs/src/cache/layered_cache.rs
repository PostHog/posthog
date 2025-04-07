use std::sync::Arc;
use quick_cache::sync::Cache as InMemoryCache;
use crate::types::Update;
use crate::errors::CacheError;
use crate::cache::secondary_cache::SecondaryCacheOperations;
use crate::cache::secondary_cache::SecondaryCache;
use tracing::warn;

#[derive(Clone)]
pub struct LayeredCache<S: SecondaryCacheOperations = SecondaryCache> {
    memory: Arc<InMemoryCache<Update, ()>>,
    secondary: S,
}

impl<S: SecondaryCacheOperations> LayeredCache<S> {
    pub fn new(memory: Arc<InMemoryCache<Update, ()>>, secondary: S) -> Self {
        Self { memory, secondary }
    }

    pub async fn insert_batch(&self, keys: Vec<Update>) {
        let mut new_keys = Vec::new();

        for key in &keys {
            if self.memory.get(key).is_none() {
                self.memory.insert(key.clone(), ());
                new_keys.push(key.clone());
            }
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
            return check_secondary;
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
