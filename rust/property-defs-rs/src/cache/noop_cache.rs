use crate::types::Update;
use super::secondary_cache::SecondaryCache;
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
impl SecondaryCache for NoOpCache {
    async fn insert_batch(&self, _updates: &[Update]) -> Result<(), RedisError> {
        Ok(())
    }

    async fn get_batch(&self, _updates: &[Update]) -> Result<Vec<Update>, RedisError> {
        Ok(Vec::new())
    }
}
