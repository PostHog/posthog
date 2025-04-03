use property_defs_rs::cache::layered_cache::LayeredCache;
use property_defs_rs::cache::secondary_cache::SecondaryCacheOperations;
use property_defs_rs::types::{Update, EventDefinition};
use property_defs_rs::errors::CacheError;
use quick_cache::sync::Cache as InMemoryCache;
use std::sync::Arc;
use chrono::Utc;
use mockall::mock;

mock! {
    SecondaryCache {}
    #[async_trait::async_trait]
    impl SecondaryCacheOperations for SecondaryCache {
        async fn insert_batch(&self, updates: &[Update]) -> Result<(), CacheError>;
        async fn filter_cached_updates(&self, updates: &[Update]) -> Result<Vec<Update>, CacheError>;
    }
}

#[tokio::test]
async fn test_layered_cache_basic() {
    let memory = Arc::new(InMemoryCache::new(1000));
    let mut mock_secondary = MockSecondaryCache::new();

    // Set up expectations
    mock_secondary
        .expect_insert_batch()
        .returning(|_| Ok(()));
    mock_secondary
        .expect_filter_cached_updates()
        .returning(|_| Ok(vec![]));

    let cache = LayeredCache::new(memory, mock_secondary);

    let events: Vec<Update> = (0..3)
        .map(|i| {
            Update::Event(EventDefinition {
                name: format!("test_{}", i),
                team_id: 1,
                project_id: 1,
                last_seen_at: Utc::now(),
            })
        })
        .collect();

    // First insert the events
    cache.insert_batch(events.clone()).await;

    // Then verify none of them are returned by filter_cached_updates
    let not_in_cache = cache.filter_cached_updates(events.clone()).await;
    assert_eq!(not_in_cache.len(), 0);
}
