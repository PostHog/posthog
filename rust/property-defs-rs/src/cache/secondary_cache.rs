use crate::types::Update;

#[async_trait::async_trait]
pub trait SecondaryCache: Send + Sync + Clone {
    /// Insert multiple updates into the cache
    async fn insert_batch(&self, updates: &[Update]) -> Result<(), redis::RedisError>;
    /// Get multiple updates from the cache, returns only the found updates
    async fn get_batch(&self, updates: &[Update]) -> Result<Vec<Update>, redis::RedisError>;
}
