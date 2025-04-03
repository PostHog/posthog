use property_defs_rs::cache::layered_cache::LayeredCache;
use property_defs_rs::cache::secondary_cache::SecondaryCacheOperations;
use property_defs_rs::types::{Update, EventDefinition};
use property_defs_rs::errors::CacheError;
use quick_cache::sync::Cache as InMemoryCache;
use std::sync::Arc;
use chrono::{Utc, DateTime};
use mockall::mock;
use predicates::prelude::*;

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

    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let events: Vec<Update> = (0..3)
        .map(|i| {
            Update::Event(EventDefinition {
                name: format!("test_{}", i),
                team_id: 1234,
                project_id: 5678,
                last_seen_at: timestamp,
            })
        })
        .collect();

    mock_secondary
        .expect_insert_batch()
        .times(1)
        .with(predicate::eq(events.clone()))
        .returning(|_| Ok(()));
    mock_secondary
        .expect_filter_cached_updates()
        .times(1)
        .returning(|updates| Ok(updates.to_vec()));

    let cache = LayeredCache::new(memory, mock_secondary);

    let not_in_cache = cache.filter_cached_updates(events.clone()).await;
    assert_eq!(not_in_cache, events, "All events should not be in cache initially");

    cache.insert_batch(events.clone()).await;

    let not_in_cache = cache.filter_cached_updates(events.clone()).await;
    assert_eq!(not_in_cache.len(), 0, "All events should be in cache after insertion");
}

#[tokio::test]
async fn test_layered_cache_not_supported() {
    let memory = Arc::new(InMemoryCache::new(1000));
    let mut mock_secondary = MockSecondaryCache::new();

    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let events: Vec<Update> = (0..3)
        .map(|i| {
            Update::Event(EventDefinition {
                name: format!("test_{}", i),
                team_id: 2345,
                project_id: 6789,
                last_seen_at: timestamp,
            })
        })
        .collect();

    mock_secondary
        .expect_insert_batch()
        .times(1)
        .with(predicate::eq(events.clone()))
        .returning(|_| Err(CacheError::NotSupported));
    mock_secondary
        .expect_filter_cached_updates()
        .times(1)
        .returning(|_| Err(CacheError::NotSupported));

    let cache = LayeredCache::new(memory, mock_secondary);

    let not_in_cache = cache.filter_cached_updates(events.clone()).await;
    assert_eq!(not_in_cache, events, "All events should be returned when secondary cache is not supported");

    cache.insert_batch(events.clone()).await;

    let not_in_cache = cache.filter_cached_updates(events.clone()).await;
    assert_eq!(not_in_cache.len(), 0, "All events should be in memory cache after insertion");
}

#[tokio::test]
async fn test_layered_cache_skips_secondary_cache() {
    let memory = Arc::new(InMemoryCache::new(1000));
    let mut mock_secondary = MockSecondaryCache::new();

    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let events: Vec<Update> = (0..3)
        .map(|i| {
            Update::Event(EventDefinition {
                name: format!("test_{}", i),
                team_id: 3456,
                project_id: 7890,
                last_seen_at: timestamp,
            })
        })
        .collect();

    mock_secondary
        .expect_insert_batch()
        .times(1)
        .with(predicate::eq(events.clone()))
        .returning(|_| Ok(()));
    mock_secondary
        .expect_filter_cached_updates()
        .times(0)
        .returning(|_| Ok(vec![]));

    let cache = LayeredCache::new(memory, mock_secondary);

    cache.insert_batch(events.clone()).await;

    let not_in_cache = cache.filter_cached_updates(events.clone()).await;
    assert_eq!(not_in_cache.len(), 0, "All events should be in memory cache");
}

#[tokio::test]
async fn test_layered_cache_partial_hit() {
    let memory = Arc::new(InMemoryCache::new(1000));
    let mut mock_secondary = MockSecondaryCache::new();

    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let all_events: Vec<Update> = (1..=6)
        .map(|i| {
            Update::Event(EventDefinition {
                name: format!("test_{}", i),
                team_id: 4567,
                project_id: 8901,
                last_seen_at: timestamp,
            })
        })
        .collect();

    let events_to_cache = all_events[1..4].to_vec();
    let events_to_check = vec![all_events[0].clone(), all_events[4].clone(), all_events[5].clone()];
    let events_secondary_returns = vec![all_events[0].clone(), all_events[4].clone()];

    mock_secondary
        .expect_insert_batch()
        .times(1)
        .with(predicate::eq(events_to_cache.clone()))
        .returning(|_| Ok(()));
    mock_secondary
        .expect_filter_cached_updates()
        .times(1)
        .with(predicate::eq(events_to_check.clone()))
        .returning(move |_| Ok(events_secondary_returns.clone()));

    let cache = LayeredCache::new(memory, mock_secondary);

    cache.insert_batch(events_to_cache).await;

    let not_in_cache = cache.filter_cached_updates(all_events.clone()).await;
    assert_eq!(not_in_cache, vec![all_events[0].clone(), all_events[4].clone()]);
}

#[tokio::test]
async fn test_layered_cache_full_hit() {
    let memory = Arc::new(InMemoryCache::new(1000));
    let mut mock_secondary = MockSecondaryCache::new();

    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let all_events: Vec<Update> = (1..=6)
        .map(|i| {
            Update::Event(EventDefinition {
                name: format!("test_{}", i),
                team_id: 5678,
                project_id: 9012,
                last_seen_at: timestamp,
            })
        })
        .collect();

    let events_to_cache = all_events[1..4].to_vec();
    let events_to_check = vec![all_events[0].clone(), all_events[4].clone(), all_events[5].clone()];
    let events_secondary_returns = vec![];

    mock_secondary
        .expect_insert_batch()
        .times(1)
        .with(predicate::eq(events_to_cache.clone()))
        .returning(|_| Ok(()));
    mock_secondary
        .expect_filter_cached_updates()
        .times(1)
        .with(predicate::eq(events_to_check.clone()))
        .returning(move |_| Ok(events_secondary_returns.clone()));

    let cache = LayeredCache::new(memory, mock_secondary);

    cache.insert_batch(events_to_cache).await;

    let not_in_cache = cache.filter_cached_updates(all_events.clone()).await;
    assert_eq!(not_in_cache.len(), 0);
}

#[tokio::test]
async fn test_layered_cache_fail_open() {
    let memory = Arc::new(InMemoryCache::new(1000));
    let mut mock_secondary = MockSecondaryCache::new();

    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let all_events: Vec<Update> = (1..=6)
        .map(|i| {
            Update::Event(EventDefinition {
                name: format!("test_{}", i),
                team_id: 6789,
                project_id: 1234,
                last_seen_at: timestamp,
            })
        })
        .collect();

    let events_to_cache = all_events[1..4].to_vec();
    let events_to_check = vec![all_events[0].clone(), all_events[4].clone(), all_events[5].clone()];

    mock_secondary
        .expect_insert_batch()
        .times(1)
        .with(predicate::eq(events_to_cache.clone()))
        .returning(|_| Ok(()));
    mock_secondary
        .expect_filter_cached_updates()
        .times(1)
        .with(predicate::eq(events_to_check.clone()))
        .returning(|_| Err(CacheError::NotSupported));

    let cache = LayeredCache::new(memory, mock_secondary);

    cache.insert_batch(events_to_cache).await;

    let not_in_cache = cache.filter_cached_updates(all_events.clone()).await;
    assert_eq!(not_in_cache, events_to_check);
}

#[tokio::test]
async fn test_layered_cache_len() {
    let memory = Arc::new(InMemoryCache::new(1000));
    let mut mock_secondary = MockSecondaryCache::new();

    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let first_batch: Vec<Update> = (0..3)
        .map(|i| {
            Update::Event(EventDefinition {
                name: format!("test_{}", i),
                team_id: 1234,
                project_id: 5678,
                last_seen_at: timestamp,
            })
        })
        .collect();

    let second_batch: Vec<Update> = (3..6)
        .map(|i| {
            Update::Event(EventDefinition {
                name: format!("test_{}", i),
                team_id: 2345,
                project_id: 6789,
                last_seen_at: timestamp,
            })
        })
        .collect();

    mock_secondary
        .expect_insert_batch()
        .times(1)
        .with(predicate::eq(first_batch.clone()))
        .returning(|_| Ok(()));

    mock_secondary
        .expect_insert_batch()
        .times(1)
        .with(predicate::eq(second_batch.clone()))
        .returning(|_| Ok(()));

    let cache = LayeredCache::new(memory, mock_secondary);

    assert_eq!(cache.len(), 0, "Empty cache should have length 0");

    cache.insert_batch(first_batch.clone()).await;
    assert_eq!(cache.len(), 3, "Cache should have length 3 after first batch");

    cache.insert_batch(second_batch.clone()).await;
    assert_eq!(cache.len(), 6, "Cache should have length 6 after second batch");
}

#[tokio::test]
async fn test_layered_cache_duplicates() {
    let memory = Arc::new(InMemoryCache::new(1000));
    let mut mock_secondary = MockSecondaryCache::new();

    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let all_events: Vec<Update> = (0..4)
        .map(|i| {
            Update::Event(EventDefinition {
                name: format!("test_{}", i),
                team_id: 1234,
                project_id: 5678,
                last_seen_at: timestamp,
            })
        })
        .collect();

    let first_batch = all_events[0..3].to_vec();
    let second_batch = all_events[1..4].to_vec();
    let new_events = vec![all_events[3].clone()];

    mock_secondary
        .expect_insert_batch()
        .times(1)
        .with(predicate::eq(first_batch.clone()))
        .returning(|_| Ok(()));

    mock_secondary
        .expect_insert_batch()
        .times(1)
        .with(predicate::eq(new_events.clone()))
        .returning(|_| Ok(()));

    let cache = LayeredCache::new(memory, mock_secondary);

    cache.insert_batch(first_batch.clone()).await;
    assert_eq!(cache.len(), 3, "Cache should have length 3 after first batch");

    cache.insert_batch(second_batch.clone()).await;
    assert_eq!(cache.len(), 4, "Cache should have length 4 after second batch");

    let not_in_cache = cache.filter_cached_updates(all_events.clone()).await;
    assert_eq!(not_in_cache.len(), 0, "All events should be in cache");
}

#[tokio::test]
async fn test_layered_cache_no_secondary_call_for_cached_events() {
    let memory = Arc::new(InMemoryCache::new(1000));
    let mut mock_secondary = MockSecondaryCache::new();

    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let all_events: Vec<Update> = (0..4)
        .map(|i| {
            Update::Event(EventDefinition {
                name: format!("test_{}", i),
                team_id: 2345,
                project_id: 6789,
                last_seen_at: timestamp,
            })
        })
        .collect();

    let first_batch = all_events[0..3].to_vec();
    let second_batch = all_events[0..3].to_vec();

    mock_secondary
        .expect_insert_batch()
        .times(1)
        .with(predicate::eq(first_batch.clone()))
        .returning(|_| Ok(()));

    let cache = LayeredCache::new(memory, mock_secondary);

    cache.insert_batch(first_batch.clone()).await;
    assert_eq!(cache.len(), 3, "Cache should have length 3 after first batch");

    cache.insert_batch(second_batch.clone()).await;
    assert_eq!(cache.len(), 3, "Cache should still have length 3 after second batch");
}

#[tokio::test]
async fn test_layered_cache_remove() {
    let memory = Arc::new(InMemoryCache::new(1000));
    let mut mock_secondary = MockSecondaryCache::new();

    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let events: Vec<Update> = (0..3)
        .map(|i| {
            Update::Event(EventDefinition {
                name: format!("test_{}", i),
                team_id: 1234,
                project_id: 5678,
                last_seen_at: timestamp,
            })
        })
        .collect();

    mock_secondary
        .expect_insert_batch()
        .times(1)
        .with(predicate::eq(events.clone()))
        .returning(|_| Err(CacheError::NotSupported));

    mock_secondary
        .expect_filter_cached_updates()
        .times(2)
        .returning(|_| Err(CacheError::NotSupported));

    let cache = LayeredCache::new(memory, mock_secondary);

    cache.insert_batch(events.clone()).await;
    assert_eq!(cache.len(), 3, "Cache should have length 3 after insertion");

    let not_in_cache = cache.filter_cached_updates(events.clone()).await;
    assert_eq!(not_in_cache.len(), 0, "All events should be in cache");

    cache.remove(&events[1]);
    assert_eq!(cache.len(), 2, "Cache should have length 2 after removing middle event");

    let not_in_cache = cache.filter_cached_updates(vec![events[1].clone()]).await;
    assert_eq!(not_in_cache.len(), 1, "Removed event should not be in cache");

    cache.remove(&events[0]);
    assert_eq!(cache.len(), 1, "Cache should have length 1 after removing first event");

    let not_in_cache = cache.filter_cached_updates(vec![events[0].clone()]).await;
    assert_eq!(not_in_cache.len(), 1, "Removed event should not be in cache");
}
