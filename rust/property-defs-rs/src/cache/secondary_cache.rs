use crate::types::Update;
use crate::errors::CacheError;
use super::{RedisCache, NoOpCache};
use futures::Stream;
use std::pin::Pin;

#[async_trait::async_trait]
pub trait CacheOperations {
    async fn insert_batch(&self, updates: &[Update]) -> Result<(), CacheError>;
    async fn filter_cached_updates(&self, updates: Vec<Update>) -> Pin<Box<dyn Stream<Item = Update> + Send + '_>>;
}

#[async_trait::async_trait]
pub trait SecondaryCacheOperations: Send + Sync {
    /// Insert multiple updates into the cache
    async fn insert_batch(&self, updates: &[Update]) -> Result<(), CacheError>;

    /// Filter out updates that exist in the cache, returns updates that are not in the cache
    async fn filter_cached_updates(&self, updates: Vec<Update>) -> Pin<Box<dyn Stream<Item = Update> + Send + '_>>;
}

#[derive(Clone)]
pub enum SecondaryCache {
    Redis(RedisCache),
    NoOp(NoOpCache),
}

#[async_trait::async_trait]
impl SecondaryCacheOperations for SecondaryCache {
    async fn insert_batch(&self, updates: &[Update]) -> Result<(), CacheError> {
        match self {
            SecondaryCache::Redis(cache) => cache.insert_batch(updates).await,
            SecondaryCache::NoOp(cache) => cache.insert_batch(updates).await,
        }
    }

    async fn filter_cached_updates(&self, updates: Vec<Update>) -> Pin<Box<dyn Stream<Item = Update> + Send + '_>> {
        match self {
            SecondaryCache::Redis(cache) => cache.filter_cached_updates(updates).await,
            SecondaryCache::NoOp(cache) => cache.filter_cached_updates(updates).await,
        }
    }
}
