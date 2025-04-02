use crate::types::Update;

/// Trait defining the interface for secondary caches that can be used with LayeredCache
pub trait SecondaryCache: Clone {
    /// Insert multiple updates into the cache
    fn insert_batch(&self, updates: &[Update]) -> Result<(), redis::RedisError>;
    /// Get multiple updates from the cache, returns only the found updates
    fn get_batch(&self, updates: &[Update]) -> Result<Vec<Update>, redis::RedisError>;
}
