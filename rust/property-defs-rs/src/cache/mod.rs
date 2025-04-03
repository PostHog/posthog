use crate::types::Update;
use crate::errors::CacheError;
use async_trait::async_trait;

pub mod layered_cache;
pub mod noop_cache;
pub mod redis_cache;

pub use layered_cache::LayeredCache;
pub use noop_cache::NoOpCache;
pub use redis_cache::RedisCache;

#[async_trait]
pub trait CacheOperations {
    async fn insert_batch(&self, updates: &[Update]) -> Result<(), CacheError>;
    async fn filter_cached_updates(&self, updates: &[Update]) -> Result<Vec<Update>, CacheError>;
}

#[derive(Clone)]
pub enum SecondaryCache {
    Redis(RedisCache),
    NoOp(NoOpCache),
}

#[async_trait]
impl CacheOperations for SecondaryCache {
    async fn insert_batch(&self, updates: &[Update]) -> Result<(), CacheError> {
        match self {
            SecondaryCache::Redis(cache) => cache.insert_batch(updates).await,
            SecondaryCache::NoOp(cache) => cache.insert_batch(updates).await,
        }
    }

    async fn filter_cached_updates(&self, updates: &[Update]) -> Result<Vec<Update>, CacheError> {
        match self {
            SecondaryCache::Redis(cache) => cache.filter_cached_updates(updates).await,
            SecondaryCache::NoOp(cache) => cache.filter_cached_updates(updates).await,
        }
    }
}
