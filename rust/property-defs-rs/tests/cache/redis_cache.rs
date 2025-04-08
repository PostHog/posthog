use property_defs_rs::cache::redis_cache::{RedisCache, RedisClientOperations};
use property_defs_rs::cache::CacheOperations;
use property_defs_rs::types::{Update, EventDefinition};
use redis::RedisError;
use chrono::{Utc, DateTime};
use mockall::mock;
use predicates::prelude::*;

mock! {
    pub RedisClient {}

    #[async_trait::async_trait]
    impl RedisClientOperations for RedisClient {
        async fn get_keys(&self, keys: &[String]) -> Result<Vec<Option<String>>, RedisError>;
        async fn set_keys(&self, updates: &[(String, String)], ttl: u64) -> Result<(), RedisError>;
    }

    impl Clone for RedisClient {
        fn clone(&self) -> Self;
    }
}

#[tokio::test]
async fn test_insert_single_update() {
    let mut mock_client = MockRedisClient::new();
    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let event = Update::Event(EventDefinition {
        name: "test_0".to_string(),
        team_id: 1234,
        project_id: 5678,
        last_seen_at: timestamp,
    });

    mock_client
        .expect_set_keys()
        .times(1)
        .with(
            predicate::eq(vec![(event.key(), String::new())]),
            predicate::eq(3600)
        )
        .returning(|_, _| Ok(()));

    let cache = RedisCache::new(mock_client, 3600, 1000, 1000);
    cache.insert_batch(&[event]).await.unwrap();
}

#[tokio::test]
async fn test_insert_multiple_within_limit() {
    let mut mock_client = MockRedisClient::new();
    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let events: Vec<Update> = (0..3)
        .map(|i| Update::Event(EventDefinition {
            name: format!("test_{}", i),
            team_id: 1234,
            project_id: 5678,
            last_seen_at: timestamp,
        }))
        .collect();

    let key_value_pairs: Vec<(String, String)> = events.iter()
        .map(|e| (e.key(), String::new()))
        .collect();

    mock_client
        .expect_set_keys()
        .times(1)
        .with(predicate::eq(key_value_pairs), predicate::eq(3600))
        .returning(|_, _| Ok(()));

    let cache = RedisCache::new(mock_client, 3600, 1000, 5);
    cache.insert_batch(&events).await.unwrap();
}

#[tokio::test]
async fn test_insert_exceeds_batch_limit() {
    let mut mock_client = MockRedisClient::new();
    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let events: Vec<Update> = (0..5)
        .map(|i| Update::Event(EventDefinition {
            name: format!("test_{}", i),
            team_id: 1234,
            project_id: 5678,
            last_seen_at: timestamp,
        }))
        .collect();

    let first_three_pairs: Vec<(String, String)> = events[..3].iter()
        .map(|e| (e.key(), String::new()))
        .collect();

    mock_client
        .expect_set_keys()
        .times(1)
        .with(predicate::eq(first_three_pairs), predicate::eq(3600))
        .returning(|_, _| Ok(()));

    let cache = RedisCache::new(mock_client, 3600, 1000, 3);
    cache.insert_batch(&events).await.unwrap();
}

#[tokio::test]
async fn test_insert_custom_ttl() {
    let mut mock_client = MockRedisClient::new();
    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let event = Update::Event(EventDefinition {
        name: "test_0".to_string(),
        team_id: 1234,
        project_id: 5678,
        last_seen_at: timestamp,
    });

    mock_client
        .expect_set_keys()
        .times(1)
        .with(
            predicate::eq(vec![(event.key(), String::new())]),
            predicate::eq(7200)
        )
        .returning(|_, _| Ok(()));

    let cache = RedisCache::new(mock_client, 7200, 1000, 1000);
    cache.insert_batch(&[event]).await.unwrap();
}

#[tokio::test]
async fn test_filter_all_missing() {
    let mut mock_client = MockRedisClient::new();
    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let events: Vec<Update> = (0..3)
        .map(|i| Update::Event(EventDefinition {
            name: format!("test_{}", i),
            team_id: 1234,
            project_id: 5678,
            last_seen_at: timestamp,
        }))
        .collect();

    let keys: Vec<String> = events.iter().map(|e| e.key()).collect();

    mock_client
        .expect_get_keys()
        .times(1)
        .with(predicate::eq(keys))
        .returning(|keys| Ok(vec![None; keys.len()]));

    let cache = RedisCache::new(mock_client, 3600, 1000, 1000);
    let not_in_cache = cache.filter_cached_updates(events.clone()).await;
    assert_eq!(not_in_cache, events, "All events should be returned as missing");
}

#[tokio::test]
async fn test_filter_all_present() {
    let mut mock_client = MockRedisClient::new();
    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let events: Vec<Update> = (0..3)
        .map(|i| Update::Event(EventDefinition {
            name: format!("test_{}", i),
            team_id: 1234,
            project_id: 5678,
            last_seen_at: timestamp,
        }))
        .collect();

    let keys: Vec<String> = events.iter().map(|e| e.key()).collect();

    mock_client
        .expect_get_keys()
        .times(1)
        .with(predicate::eq(keys))
        .returning(|keys| Ok(vec![Some(String::new()); keys.len()]));

    let cache = RedisCache::new(mock_client, 3600, 1000, 1000);
    let not_in_cache = cache.filter_cached_updates(events).await;
    assert_eq!(not_in_cache.len(), 0, "No events should be returned as all are present");
}

#[tokio::test]
async fn test_filter_partial_hits() {
    let mut mock_client = MockRedisClient::new();
    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let events: Vec<Update> = (0..3)
        .map(|i| Update::Event(EventDefinition {
            name: format!("test_{}", i),
            team_id: 1234,
            project_id: 5678,
            last_seen_at: timestamp,
        }))
        .collect();

    let keys: Vec<String> = events.iter().map(|e| e.key()).collect();

    mock_client
        .expect_get_keys()
        .times(1)
        .with(predicate::eq(keys))
        .returning(|_| Ok(vec![Some(String::new()), None, Some(String::new())]));

    let cache = RedisCache::new(mock_client, 3600, 1000, 1000);
    let not_in_cache = cache.filter_cached_updates(events.clone()).await;
    assert_eq!(not_in_cache.len(), 1, "One event should be missing");
    assert_eq!(not_in_cache[0].key(), events[1].key(), "Middle event should be missing");
}

#[tokio::test]
async fn test_filter_batch_limit() {
    let mut mock_client = MockRedisClient::new();
    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let events: Vec<Update> = (0..5)
        .map(|i| Update::Event(EventDefinition {
            name: format!("test_{}", i),
            team_id: 1234,
            project_id: 5678,
            last_seen_at: timestamp,
        }))
        .collect();

    let last_three_keys: Vec<String> = events[2..].iter().map(|e| e.key()).collect();

    mock_client
        .expect_get_keys()
        .times(1)
        .with(predicate::eq(last_three_keys))
        .returning(|_| Ok(vec![Some(String::new()), None, Some(String::new())]));

    let cache = RedisCache::new(mock_client, 3600, 3, 1000);
    let not_in_cache = cache.filter_cached_updates(events.clone()).await;
    assert_eq!(not_in_cache.len(), 3, "First two events and one uncached event should be returned");
    assert_eq!(not_in_cache[0].key(), events[0].key(), "First event should be returned");
    assert_eq!(not_in_cache[1].key(), events[1].key(), "Second event should be returned");
    assert_eq!(not_in_cache[2].key(), events[3].key(), "Fourth event should be returned as uncached");
}

#[tokio::test]
async fn test_filter_connection_error_fails_open() {
    let mut mock_client = MockRedisClient::new();
    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let events: Vec<Update> = (0..3)
        .map(|i| Update::Event(EventDefinition {
            name: format!("test_{}", i),
            team_id: 1234,
            project_id: 5678,
            last_seen_at: timestamp,
        }))
        .collect();

    let keys: Vec<String> = events.iter().map(|e| e.key()).collect();

    mock_client
        .expect_get_keys()
        .times(1)
        .with(predicate::eq(keys))
        .returning(|_| Err(RedisError::from((redis::ErrorKind::IoError, "Connection refused"))));

    let cache = RedisCache::new(mock_client, 3600, 1000, 1000);
    let not_in_cache = cache.filter_cached_updates(events.clone()).await;
    assert_eq!(not_in_cache, events, "All events should be returned on connection error");
}

#[tokio::test]
async fn test_insert_redis_error() {
    let mut mock_client = MockRedisClient::new();
    let timestamp = DateTime::parse_from_rfc3339("2024-03-15T10:30:00Z").unwrap().with_timezone(&Utc);
    let events: Vec<Update> = (0..3)
        .map(|i| Update::Event(EventDefinition {
            name: format!("test_{}", i),
            team_id: 1234,
            project_id: 5678,
            last_seen_at: timestamp,
        }))
        .collect();

    let key_value_pairs: Vec<(String, String)> = events.iter()
        .map(|e| (e.key(), String::new()))
        .collect();

    mock_client
        .expect_set_keys()
        .times(1)
        .with(predicate::eq(key_value_pairs), predicate::eq(3600))
        .returning(|_, _| Err(RedisError::from((redis::ErrorKind::ResponseError, "Mock error"))));

    let cache = RedisCache::new(mock_client, 3600, 1000, 1000);
    let result = cache.insert_batch(&events).await;
    assert!(result.is_err(), "Insert should return error on Redis failure");
}
