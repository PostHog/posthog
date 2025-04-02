use crate::types::Update;

#[async_trait::async_trait]
pub trait SecondaryCache: Send + Sync + Clone {
    /// Insert multiple updates into the cache
    async fn insert_batch(&self, updates: &[Update]) -> Result<(), redis::RedisError>;
    /// Filter out updates that exist in the cache, returns updates that are not in the cache
    async fn filter_cached_updates(&self, updates: &[Update]) -> Result<Vec<Update>, redis::RedisError>;
}
