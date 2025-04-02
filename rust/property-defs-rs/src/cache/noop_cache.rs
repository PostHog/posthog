use crate::types::Update;
use super::secondary_cache::SecondaryCache;

/// A no-op cache implementation that can be used in place of RedisCache when Redis caching is not desired
#[derive(Clone, Debug, Default)]
pub struct NoOpCache;

impl NoOpCache {
    pub fn new() -> Self {
        Self
    }
}

impl SecondaryCache for NoOpCache {
    fn insert_batch(&self, _keys: &[Update]) -> Result<(), redis::RedisError> {
        Ok(())
    }

    fn get_batch(&self, _keys: &[Update]) -> Result<Vec<Update>, redis::RedisError> {
        Ok(Vec::new())
    }
}
