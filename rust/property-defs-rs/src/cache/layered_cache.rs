use std::sync::Arc;
use quick_cache::sync::Cache as InMemoryCache;
use crate::types::Update;
use crate::errors::CacheError;
use crate::cache::secondary_cache::SecondaryCacheOperations;
use crate::cache::secondary_cache::SecondaryCache;
use futures::Stream;
use std::pin::Pin;

#[derive(Clone)]
pub struct LayeredCache<S: SecondaryCacheOperations = SecondaryCache> {
    memory: Arc<InMemoryCache<Update, ()>>,
    secondary: S,
}

impl<S: SecondaryCacheOperations> LayeredCache<S> {
    pub fn new(memory: Arc<InMemoryCache<Update, ()>>, secondary: S) -> Self {
        Self { memory, secondary }
    }

    pub async fn insert_batch(&self, keys: Vec<Update>) -> Result<(), CacheError> {
        let mut new_keys = Vec::new();

        for key in &keys {
            if self.memory.get(key).is_none() {
                self.memory.insert(key.clone(), ());
                new_keys.push(key.clone());
            }
        }

        if !new_keys.is_empty() {
            self.secondary.insert_batch(&new_keys).await?;
        }
        Ok(())
    }

    pub async fn filter_cached_updates(&self, updates: Vec<Update>) -> Pin<Box<dyn Stream<Item = Update> + Send + '_>> {
        let mut check_secondary = Vec::new();

        // First pass: check memory cache and collect items not in memory
        for update in &updates {
            if self.memory.get(update).is_none() {
                check_secondary.push(update.clone());
            }
        }

        if check_secondary.is_empty() {
            return Box::pin(futures::stream::empty());
        }

        // Second pass: check secondary cache
        let secondary_stream = self.secondary.filter_cached_updates(check_secondary).await;
        Box::pin(secondary_stream)
    }

    pub fn len(&self) -> usize {
        self.memory.len()
    }

    pub fn remove(&self, key: &Update) -> Option<()> {
        self.memory.remove(key).map(|_| ())
    }
}
