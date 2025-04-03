use crate::types::Update;
use crate::errors::CacheError;
use super::CacheOperations;

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
    async fn insert_batch(&self, _updates: &[Update]) -> Result<(), CacheError> {
        Err(CacheError::NotSupported)
    }

    async fn filter_cached_updates(&self, _updates: &[Update]) -> Result<Vec<Update>, CacheError> {
        // NoOpCache returns a NotSupported error to avoid copying updates, since layered cache will fail open
        Err(CacheError::NotSupported)
    }
}
