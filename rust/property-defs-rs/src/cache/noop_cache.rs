use crate::types::Update;
use super::CacheOperations;
use redis::RedisError;

/// A no-op cache implementation that can be used in place of RedisCache when Redis caching is not desired
#[derive(Clone)]
pub struct NoOpCache;

impl NoOpCache {
    pub fn new() -> Self {
        Self
    }
}

#[async_trait::async_trait]
impl CacheOperations for NoOpCache {
    async fn insert_batch(&self, _updates: &[Update]) -> Result<(), RedisError> {
        Ok(())
    }

    async fn filter_cached_updates(&self, updates: &[Update]) -> Result<Vec<Update>, RedisError> {
        // NoOpCache assumes nothing is cached, so return all updates
        Ok(updates.to_vec())
    }
}
