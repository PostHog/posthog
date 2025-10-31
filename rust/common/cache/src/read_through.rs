//! Read-through cache implementation with Redis backing
//!
//! This module provides the main [`ReadThroughCache`] type that implements the read-through
//! caching pattern with support for:
//! - Redis-based positive caching
//! - Optional in-memory negative caching
//! - Cache corruption handling
//! - Graceful Redis degradation

use crate::{CacheConfig, CacheResult, CacheSource, NegativeCache};
use common_redis::{Client as RedisClient, CustomRedisError};
use serde::{Deserialize, Serialize};
use std::fmt::Display;
use std::future::Future;
use std::sync::Arc;

/// A generic read-through cache that supports:
/// - Redis-based positive caching with configurable TTL
/// - Optional in-memory negative caching to prevent repeated loader invocations for missing keys
/// - Function-based loader API (no trait implementations required)
/// - User-defined error types
/// - Rich return types for observability
/// - Cache corruption handling
///
/// The cache follows the "cache-aside" pattern:
/// 1. Check negative cache first (if enabled)
/// 2. Try to get data from Redis cache
/// 3. On cache miss, call the loader function
/// 4. If loader succeeds, update positive cache and invalidate negative cache
/// 5. If loader returns None, add to negative cache
///
/// # Example
/// ```rust,ignore
/// use common_cache::{ReadThroughCache, CacheConfig, CacheSource};
///
/// let cache = ReadThroughCache::new(
///     redis_reader,
///     redis_writer,
///     CacheConfig::with_ttl("my_data:", 300),
///     None, // no negative cache
/// );
///
/// let result = cache
///     .get_or_load(&key, |key| async {
///         load_from_source(key).await
///     })
///     .await?;
///
/// match result.source {
///     CacheSource::PositiveCache => println!("Cache hit!"),
///     CacheSource::LoaderCacheMiss => println!("Loaded from source"),
///     _ => {}
/// }
/// ```
pub struct ReadThroughCache {
    redis_reader: Arc<dyn RedisClient + Send + Sync>,
    redis_writer: Arc<dyn RedisClient + Send + Sync>,
    config: CacheConfig,
    negative_cache: Option<Arc<NegativeCache>>,
}

impl ReadThroughCache {
    /// Create a new read-through cache instance
    ///
    /// # Arguments
    /// * `redis_reader` - Redis client for reading cached data
    /// * `redis_writer` - Redis client for writing cached data
    /// * `config` - Cache configuration (prefix, TTL)
    /// * `negative_cache` - Optional negative cache to prevent repeated loader invocations for missing keys
    pub fn new(
        redis_reader: Arc<dyn RedisClient + Send + Sync>,
        redis_writer: Arc<dyn RedisClient + Send + Sync>,
        config: CacheConfig,
        negative_cache: Option<Arc<NegativeCache>>,
    ) -> Self {
        Self {
            redis_reader,
            redis_writer,
            config,
            negative_cache,
        }
    }

    /// Get a value from cache or load it using the loader function
    ///
    /// This is the main API for the cache. It:
    /// 1. Checks negative cache first (if enabled)
    /// 2. Tries Redis cache
    /// 3. On miss, calls loader function with the key
    /// 4. Updates caches based on the result
    ///
    /// The loader function should return `Option<V>` where:
    /// - `Some(value)` indicates the item was found
    /// - `None` indicates the item doesn't exist (will be negative cached)
    ///
    /// # Type Parameters
    /// * `K` - Key type (must be displayable for logging)
    /// * `V` - Value type (must be serializable)
    /// * `E` - Error type (user-defined, for loader errors)
    /// * `F` - Loader function type
    /// * `Fut` - Future returned by loader function
    ///
    /// # Arguments
    /// * `key` - The key to look up
    /// * `loader` - Function to call on cache miss, receives the key as parameter
    ///
    /// # Returns
    /// * `Ok(CacheResult)` - Contains the value (if found) and source information
    /// * `Err(error)` - Error from loader function
    pub async fn get_or_load<K, V, E, F, Fut>(
        &self,
        key: &K,
        loader: F,
    ) -> Result<CacheResult<V>, E>
    where
        K: Serialize + Display + Send + Sync,
        V: Serialize + for<'de> Deserialize<'de> + Send + Sync,
        F: FnOnce(&K) -> Fut,
        Fut: Future<Output = Result<Option<V>, E>>,
        E: Send + Sync,
    {
        let cache_key = self.build_cache_key(key);

        // Check negative cache first
        if let Some(neg_cache) = &self.negative_cache {
            if neg_cache.contains(&cache_key) {
                tracing::debug!("Negative cache hit for key: {}", key);
                return Ok(CacheResult::not_found(CacheSource::NegativeCache));
            }
        }

        // Try to get from Redis cache
        match self.get_from_redis(&cache_key).await {
            Ok(cached_value) => {
                // Positive cache hit
                tracing::debug!("Positive cache hit for key: {}", key);
                Ok(CacheResult::found(cached_value, CacheSource::PositiveCache))
            }
            Err(cache_error) => {
                // Cache miss or error - need to fetch from loader
                self.handle_cache_miss(key, &cache_key, cache_error, loader)
                    .await
            }
        }
    }

    /// Build the full Redis cache key from the user key
    fn build_cache_key<K>(&self, key: &K) -> String
    where
        K: Display,
    {
        format!("{}{}", self.config.cache_prefix, key)
    }

    /// Get a value from Redis cache
    async fn get_from_redis<V>(&self, cache_key: &str) -> Result<V, CustomRedisError>
    where
        V: for<'de> Deserialize<'de>,
    {
        let serialized_value = self.redis_reader.get(cache_key.to_string()).await?;
        let value = serde_json::from_str(&serialized_value).map_err(|e| {
            CustomRedisError::ParseError(format!("Failed to deserialize cached value: {e}"))
        })?;
        Ok(value)
    }

    /// Handle cache miss by calling loader and updating caches
    async fn handle_cache_miss<K, V, E, F, Fut>(
        &self,
        key: &K,
        cache_key: &str,
        cache_error: CustomRedisError,
        loader: F,
    ) -> Result<CacheResult<V>, E>
    where
        K: Display + Send + Sync,
        V: Serialize + Send + Sync,
        F: FnOnce(&K) -> Fut,
        Fut: Future<Output = Result<Option<V>, E>>,
        E: Send + Sync,
    {
        match cache_error {
            CustomRedisError::NotFound => {
                // True cache miss - key doesn't exist in cache
                self.handle_true_cache_miss(key, cache_key, loader).await
            }
            CustomRedisError::ParseError(ref err) => {
                // Corrupted cache data - try loader and refresh cache if successful
                tracing::warn!(
                    "Cache corruption detected for key {}: {}. Will refresh from source.",
                    key,
                    err
                );
                self.handle_corrupted_cache(key, cache_key, loader).await
            }
            CustomRedisError::Timeout | CustomRedisError::Other(_) => {
                // Redis infrastructure issues - use loader without caching
                tracing::warn!(
                    "Redis infrastructure issue for key {}: {:?}. Operating without cache.",
                    key,
                    cache_error
                );
                self.handle_redis_unavailable(key, loader).await
            }
        }
    }

    /// Handle a true cache miss (key not in Redis)
    async fn handle_true_cache_miss<K, V, E, F, Fut>(
        &self,
        key: &K,
        cache_key: &str,
        loader: F,
    ) -> Result<CacheResult<V>, E>
    where
        K: Display + Send + Sync,
        V: Serialize + Send + Sync,
        F: FnOnce(&K) -> Fut,
        Fut: Future<Output = Result<Option<V>, E>>,
        E: Send + Sync,
    {
        match loader(key).await? {
            Some(value) => {
                // Value found - update positive cache and invalidate negative cache
                if let Some(neg_cache) = &self.negative_cache {
                    neg_cache.invalidate(cache_key);
                }

                // Update positive cache
                if let Err(redis_err) = self.set_in_redis(cache_key, &value).await {
                    tracing::warn!("Failed to update cache for key {}: {:?}", key, redis_err);
                }

                Ok(CacheResult::found(value, CacheSource::LoaderCacheMiss))
            }
            None => {
                // Value not found - add to negative cache
                if let Some(neg_cache) = &self.negative_cache {
                    neg_cache.insert(cache_key.to_string());
                }

                Ok(CacheResult::not_found(CacheSource::LoaderNotFoundCacheMiss))
            }
        }
    }

    /// Handle corrupted cache data
    async fn handle_corrupted_cache<K, V, E, F, Fut>(
        &self,
        key: &K,
        cache_key: &str,
        loader: F,
    ) -> Result<CacheResult<V>, E>
    where
        K: Display + Send + Sync,
        V: Serialize + Send + Sync,
        F: FnOnce(&K) -> Fut,
        Fut: Future<Output = Result<Option<V>, E>>,
        E: Send + Sync,
    {
        match loader(key).await? {
            Some(value) => {
                // Loader success - refresh cache with valid data
                if let Some(neg_cache) = &self.negative_cache {
                    neg_cache.invalidate(cache_key);
                }

                // Update cache with fresh data
                if let Err(redis_err) = self.set_in_redis(cache_key, &value).await {
                    tracing::warn!(
                        "Failed to refresh corrupted cache for key {}: {:?}",
                        key,
                        redis_err
                    );
                }

                Ok(CacheResult::found(value, CacheSource::LoaderCacheCorrupted))
            }
            None => {
                // Value not found - add to negative cache
                if let Some(neg_cache) = &self.negative_cache {
                    neg_cache.insert(cache_key.to_string());
                }

                Ok(CacheResult::not_found(
                    CacheSource::LoaderNotFoundCacheCorrupted,
                ))
            }
        }
    }

    /// Handle Redis being unavailable
    async fn handle_redis_unavailable<K, V, E, F, Fut>(
        &self,
        _key: &K,
        loader: F,
    ) -> Result<CacheResult<V>, E>
    where
        K: Display + Send + Sync,
        V: Serialize + Send + Sync,
        F: FnOnce(&K) -> Fut,
        Fut: Future<Output = Result<Option<V>, E>>,
        E: Send + Sync,
    {
        // Don't update any caches when Redis is having issues
        match loader(_key).await? {
            Some(value) => Ok(CacheResult::found(
                value,
                CacheSource::LoaderRedisUnavailable,
            )),
            None => Ok(CacheResult::not_found(
                CacheSource::LoaderNotFoundRedisUnavailable,
            )),
        }
    }

    /// Write a value to Redis cache
    async fn set_in_redis<V>(&self, cache_key: &str, value: &V) -> Result<(), CustomRedisError>
    where
        V: Serialize,
    {
        let serialized_value = serde_json::to_string(value).map_err(|e| {
            CustomRedisError::ParseError(format!("Failed to serialize value for cache: {e}"))
        })?;

        match self.config.ttl_seconds {
            Some(ttl) => {
                self.redis_writer
                    .setex(cache_key.to_string(), serialized_value, ttl)
                    .await
            }
            None => {
                self.redis_writer
                    .set(cache_key.to_string(), serialized_value)
                    .await
            }
        }
    }

    /// Invalidate a key from both positive and negative caches
    ///
    /// # Arguments
    /// * `key` - The key to invalidate
    pub async fn invalidate<K>(&self, key: &K) -> Result<(), CustomRedisError>
    where
        K: Display,
    {
        let cache_key = self.build_cache_key(key);

        // Remove from Redis
        if let Err(e) = self.redis_writer.del(cache_key.clone()).await {
            tracing::warn!("Failed to delete cache key {}: {:?}", cache_key, e);
        }

        // Remove from negative cache
        if let Some(neg_cache) = &self.negative_cache {
            neg_cache.invalidate(&cache_key);
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::MockRedisClient;
    use serde::{Deserialize, Serialize};
    use std::sync::Arc;

    #[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
    struct TestData {
        id: i32,
        name: String,
    }

    fn setup_cache(
        reader: MockRedisClient,
        writer: MockRedisClient,
        negative_cache: Option<Arc<NegativeCache>>,
    ) -> ReadThroughCache {
        let config = CacheConfig::with_ttl("test:", 300);
        ReadThroughCache::new(Arc::new(reader), Arc::new(writer), config, negative_cache)
    }

    #[tokio::test]
    async fn test_positive_cache_hit() {
        let data = TestData {
            id: 1,
            name: "test".to_string(),
        };
        let serialized = serde_json::to_string(&data).unwrap();

        let mut reader = MockRedisClient::new();
        reader.get_ret("test:key1", Ok(serialized));

        let cache = setup_cache(reader, MockRedisClient::new(), None);

        let result = cache
            .get_or_load(&"key1", |_key| async {
                Ok::<Option<TestData>, String>(None)
            })
            .await
            .unwrap();

        assert_eq!(result.value, Some(data));
        assert_eq!(result.source, CacheSource::PositiveCache);
        assert!(result.was_cached());
        assert!(!result.invoked_loader());
    }

    #[tokio::test]
    async fn test_cache_miss_loads_and_caches() {
        let mut reader = MockRedisClient::new();
        reader.get_ret("test:key1", Err(CustomRedisError::NotFound));

        let mut writer = MockRedisClient::new();
        writer.set_ret("test:key1", Ok(()));

        let cache = setup_cache(reader, writer.clone(), None);

        let data = TestData {
            id: 1,
            name: "loaded".to_string(),
        };
        let expected_data = data.clone();

        let result = cache
            .get_or_load(&"key1", |_key| async move {
                Ok::<Option<TestData>, String>(Some(expected_data))
            })
            .await
            .unwrap();

        assert_eq!(result.value, Some(data));
        assert_eq!(result.source, CacheSource::LoaderCacheMiss);
        assert!(!result.was_cached());
        assert!(result.invoked_loader());

        // Verify cache was written to
        let calls = writer.get_calls();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].op, "setex");
        assert_eq!(calls[0].key, "test:key1");
    }

    #[tokio::test]
    async fn test_cache_miss_not_found_returns_none() {
        let mut reader = MockRedisClient::new();
        reader.get_ret("test:key1", Err(CustomRedisError::NotFound));

        let cache = setup_cache(reader, MockRedisClient::new(), None);

        let result = cache
            .get_or_load(&"key1", |_key| async {
                Ok::<Option<TestData>, String>(None)
            })
            .await
            .unwrap();

        assert_eq!(result.value, None);
        assert_eq!(result.source, CacheSource::LoaderNotFoundCacheMiss);
        assert!(!result.was_cached());
        assert!(result.invoked_loader());
    }

    #[tokio::test]
    async fn test_cache_corruption_reloads_and_refreshes() {
        let mut reader = MockRedisClient::new();
        reader.get_ret("test:key1", Ok("invalid json{".to_string()));

        let mut writer = MockRedisClient::new();
        writer.set_ret("test:key1", Ok(()));

        let cache = setup_cache(reader, writer.clone(), None);

        let data = TestData {
            id: 1,
            name: "refreshed".to_string(),
        };
        let expected_data = data.clone();

        let result = cache
            .get_or_load(&"key1", |_key| async move {
                Ok::<Option<TestData>, String>(Some(expected_data))
            })
            .await
            .unwrap();

        assert_eq!(result.value, Some(data));
        assert_eq!(result.source, CacheSource::LoaderCacheCorrupted);
        assert!(!result.was_cached());
        assert!(result.invoked_loader());
        assert!(result.had_cache_problem());

        // Verify cache was refreshed
        let calls = writer.get_calls();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].op, "setex");
    }

    #[tokio::test]
    async fn test_cache_corruption_not_found() {
        let mut reader = MockRedisClient::new();
        reader.get_ret("test:key1", Ok("invalid json{".to_string()));

        let cache = setup_cache(reader, MockRedisClient::new(), None);

        let result = cache
            .get_or_load(&"key1", |_key| async {
                Ok::<Option<TestData>, String>(None)
            })
            .await
            .unwrap();

        assert_eq!(result.value, None);
        assert_eq!(result.source, CacheSource::LoaderNotFoundCacheCorrupted);
        assert!(result.had_cache_problem());
    }

    async fn test_redis_infrastructure_error_skips_cache_write_impl(redis_error: CustomRedisError) {
        let mut reader = MockRedisClient::new();
        reader.get_ret("test:key1", Err(redis_error));

        let writer = MockRedisClient::new();

        let cache = setup_cache(reader, writer.clone(), None);

        let data = TestData {
            id: 1,
            name: "from_loader".to_string(),
        };
        let expected_data = data.clone();

        let result = cache
            .get_or_load(&"key1", |_key| async move {
                Ok::<Option<TestData>, String>(Some(expected_data))
            })
            .await
            .unwrap();

        assert_eq!(result.value, Some(data));
        assert_eq!(result.source, CacheSource::LoaderRedisUnavailable);
        assert!(result.had_cache_problem());
        assert!(result.invoked_loader());

        // Verify NO cache write occurred
        let calls = writer.get_calls();
        assert_eq!(calls.len(), 0);
    }

    #[tokio::test]
    async fn test_redis_timeout_skips_cache_write() {
        test_redis_infrastructure_error_skips_cache_write_impl(CustomRedisError::Timeout).await;
    }

    #[tokio::test]
    async fn test_redis_other_error_skips_cache_write() {
        test_redis_infrastructure_error_skips_cache_write_impl(CustomRedisError::Other(
            "connection refused".to_string(),
        ))
        .await;
    }

    async fn test_redis_infrastructure_error_not_found_impl(redis_error: CustomRedisError) {
        let mut reader = MockRedisClient::new();
        reader.get_ret("test:key1", Err(redis_error));

        let negative_cache = Arc::new(NegativeCache::new(100, 300));
        let cache = setup_cache(reader, MockRedisClient::new(), Some(negative_cache.clone()));

        let result = cache
            .get_or_load(&"key1", |_key| async {
                Ok::<Option<TestData>, String>(None)
            })
            .await
            .unwrap();

        assert_eq!(result.value, None);
        assert_eq!(result.source, CacheSource::LoaderNotFoundRedisUnavailable);
        assert!(result.had_cache_problem());

        // Verify negative cache was NOT updated (don't poison cache when Redis is down)
        assert!(!negative_cache.contains("test:key1"));
    }

    #[tokio::test]
    async fn test_redis_timeout_not_found() {
        test_redis_infrastructure_error_not_found_impl(CustomRedisError::Timeout).await;
    }

    #[tokio::test]
    async fn test_redis_other_error_not_found() {
        test_redis_infrastructure_error_not_found_impl(CustomRedisError::Other(
            "network error".to_string(),
        ))
        .await;
    }

    #[tokio::test]
    async fn test_negative_cache_hit() {
        let mut reader = MockRedisClient::new();
        reader.get_ret("test:key1", Err(CustomRedisError::NotFound));

        let negative_cache = Arc::new(NegativeCache::new(100, 300));
        let cache = setup_cache(reader, MockRedisClient::new(), Some(negative_cache.clone()));

        // First call - cache miss, loader returns None
        let result = cache
            .get_or_load(&"key1", |_key| async {
                Ok::<Option<TestData>, String>(None)
            })
            .await
            .unwrap();

        assert_eq!(result.value, None);
        assert_eq!(result.source, CacheSource::LoaderNotFoundCacheMiss);

        // Second call - should hit negative cache without invoking loader
        let result: CacheResult<TestData> = cache
            .get_or_load(&"key1", |_key| async {
                panic!("Loader should not be called for negative cache hit");
                #[allow(unreachable_code)]
                Ok::<Option<TestData>, String>(None)
            })
            .await
            .unwrap();

        assert_eq!(result.value, None);
        assert_eq!(result.source, CacheSource::NegativeCache);
        assert!(result.was_cached());
        assert!(!result.invoked_loader());
    }

    #[tokio::test]
    async fn test_negative_cache_invalidated_on_found() {
        let mut reader = MockRedisClient::new();
        reader.get_ret("test:key1", Err(CustomRedisError::NotFound));

        let mut writer = MockRedisClient::new();
        writer.set_ret("test:key1", Ok(()));

        let negative_cache = Arc::new(NegativeCache::new(100, 300));
        let cache = setup_cache(reader, writer, Some(negative_cache.clone()));

        // First call - loader returns None, should add to negative cache
        let result = cache
            .get_or_load(&"key1", |_key| async {
                Ok::<Option<TestData>, String>(None)
            })
            .await
            .unwrap();

        assert_eq!(result.value, None);
        assert_eq!(result.source, CacheSource::LoaderNotFoundCacheMiss);
        assert!(negative_cache.contains("test:key1"));

        // Second call - this time loader would return Some if called
        // But negative cache will return early
        let result: CacheResult<TestData> = cache
            .get_or_load(&"key1", |_key| async {
                Ok::<Option<TestData>, String>(Some(TestData {
                    id: 1,
                    name: "found".to_string(),
                }))
            })
            .await
            .unwrap();

        // Should hit negative cache
        assert_eq!(result.value, None);
        assert_eq!(result.source, CacheSource::NegativeCache);

        // Now invalidate the cache entry
        cache.invalidate(&"key1").await.unwrap();
        assert!(!negative_cache.contains("test:key1"));

        // Third call - after invalidation, loader should be invoked
        let data = TestData {
            id: 1,
            name: "found".to_string(),
        };
        let expected_data = data.clone();

        let result = cache
            .get_or_load(&"key1", |_key| async move {
                Ok::<Option<TestData>, String>(Some(expected_data))
            })
            .await
            .unwrap();

        assert_eq!(result.value, Some(data));
        assert_eq!(result.source, CacheSource::LoaderCacheMiss);

        // Verify negative cache was NOT re-added (since we found a value)
        assert!(!negative_cache.contains("test:key1"));
    }

    #[tokio::test]
    async fn test_invalidate_clears_both_caches() {
        let mut reader = MockRedisClient::new();
        reader.get_ret("test:key1", Ok(serde_json::to_string(&"cached").unwrap()));

        let mut writer = MockRedisClient::new();
        writer.del_ret("test:key1", Ok(()));

        let negative_cache = Arc::new(NegativeCache::new(100, 300));
        negative_cache.insert("test:key1".to_string());

        let cache = setup_cache(reader, writer.clone(), Some(negative_cache.clone()));

        cache.invalidate(&"key1").await.unwrap();

        // Verify Redis delete was called
        let calls = writer.get_calls();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].op, "del");
        assert_eq!(calls[0].key, "test:key1");

        // Verify negative cache was cleared
        assert!(!negative_cache.contains("test:key1"));
    }

    #[tokio::test]
    async fn test_loader_error_propagates() {
        let mut reader = MockRedisClient::new();
        reader.get_ret("test:key1", Err(CustomRedisError::NotFound));

        let cache = setup_cache(reader, MockRedisClient::new(), None);

        let result = cache
            .get_or_load(&"key1", |_key| async {
                Err::<Option<TestData>, String>("loader error".to_string())
            })
            .await;

        assert!(result.is_err());
        assert_eq!(result.unwrap_err(), "loader error");
    }
}
