use common_cache::{CacheResult, ReadThroughCache, ReadThroughCacheWithMetrics};
use serde::{Deserialize, Serialize};
use std::fmt::Display;
use std::hash::Hash;
use std::sync::Arc;

use crate::api::errors::FlagError;
use crate::config::Config;

/// Wrapper around ReadThroughCache that handles dual-write mode for flags migration
///
/// Three operational modes:
/// 1. No dedicated Redis configured (dedicated_cache=None): Uses shared cache only
/// 2. Dedicated Redis configured, flags_redis_enabled=false: Dual-write mode
///    - Reads from shared cache (source of truth)
///    - Inline writes to dedicated cache (warming) - adds ~1-2ms latency
/// 3. Dedicated Redis configured, flags_redis_enabled=true: Uses dedicated cache only
///
/// This allows us to:
/// - Develop locally without dedicated Redis
/// - Warm up dedicated cache in production before cutover
/// - Cut over to dedicated cache cleanly
pub struct FlagsReadThroughCache {
    shared_cache: Arc<ReadThroughCacheWithMetrics>,
    dedicated_cache: Option<Arc<ReadThroughCacheWithMetrics>>,
    config: Config,
}

impl FlagsReadThroughCache {
    /// Creates a new FlagsReadThroughCache with explicit caches (for testing)
    pub fn new(
        shared_cache: Arc<ReadThroughCache>,
        dedicated_cache: Option<Arc<ReadThroughCache>>,
        config: Config,
    ) -> Self {
        // Wrap caches with metrics
        let shared_cache = Arc::new(ReadThroughCacheWithMetrics::new(
            shared_cache,
            "flags",
            "flag",
            &[("cache_type".to_string(), "shared".to_string())],
        ));
        let dedicated_cache = dedicated_cache.map(|cache| {
            Arc::new(ReadThroughCacheWithMetrics::new(
                cache,
                "flags",
                "flag",
                &[("cache_type".to_string(), "dedicated".to_string())],
            ))
        });

        Self {
            shared_cache,
            dedicated_cache,
            config,
        }
    }

    /// Creates a FlagsReadThroughCache from Redis clients, encapsulating all cache selection logic
    ///
    /// # Cache Selection Strategy
    /// - If dedicated Redis client is provided: Creates both shared and dedicated caches
    /// - If dedicated Redis client is None: Creates only shared cache (Mode 1)
    ///
    /// The `flags_redis_enabled` flag determines which cache is used for reads/writes.
    ///
    /// ReadWriteClient automatically routes reads to replica and writes to primary.
    pub fn from_redis_client(
        shared_redis_client: Arc<dyn common_redis::Client + Send + Sync>,
        dedicated_redis_client: Option<Arc<dyn common_redis::Client + Send + Sync>>,
        flags_cache_ttl_seconds: u64,
        config: Config,
    ) -> Self {
        use crate::flags::flag_models::FeatureFlagList;

        // Always create shared cache and wrap with metrics
        // ReadWriteClient implements Client trait, so we pass it as both reader and writer
        // It will automatically route reads to replica and writes to primary
        let shared_cache_inner = Arc::new(FeatureFlagList::create_cache(
            shared_redis_client.clone(),
            shared_redis_client,
            Some(flags_cache_ttl_seconds),
        ));
        let shared_cache = Arc::new(ReadThroughCacheWithMetrics::new(
            shared_cache_inner,
            "flags",
            "flag",
            &[("cache_type".to_string(), "shared".to_string())],
        ));

        // Create dedicated cache only if dedicated Redis is configured
        let dedicated_cache = dedicated_redis_client.map(|client| {
            let dedicated_cache_inner = Arc::new(FeatureFlagList::create_cache(
                client.clone(),
                client,
                Some(flags_cache_ttl_seconds),
            ));
            Arc::new(ReadThroughCacheWithMetrics::new(
                dedicated_cache_inner,
                "flags",
                "flag",
                &[("cache_type".to_string(), "dedicated".to_string())],
            ))
        });

        Self {
            shared_cache,
            dedicated_cache,
            config,
        }
    }

    /// Get value from cache or load it, handling three operational modes
    ///
    /// # Behavior
    /// 1. No dedicated cache: Uses shared cache only
    /// 2. Dedicated cache exists, flags_redis_enabled=false: Dual-write mode
    ///    - Reads from shared cache (source of truth)
    ///    - Inline writes to dedicated cache (warming) - adds ~1-2ms latency
    /// 3. Dedicated cache exists, flags_redis_enabled=true: Uses dedicated cache only
    pub async fn get_or_load<K, V, F, Fut>(
        &self,
        key: &K,
        load: F,
    ) -> Result<CacheResult<V>, FlagError>
    where
        K: Display + Send + Sync + Hash + Serialize + for<'de> Deserialize<'de>,
        V: Clone + Send + Sync + Serialize + for<'de> Deserialize<'de>,
        F: FnOnce(&K) -> Fut,
        Fut: std::future::Future<Output = Result<Option<V>, FlagError>>,
    {
        match (&self.dedicated_cache, *self.config.flags_redis_enabled) {
            // Mode 3: Dedicated cache enabled, use it exclusively
            (Some(dedicated_cache), true) => {
                let cache_result = dedicated_cache.get_or_load(key, load).await?;
                Ok(cache_result)
            }
            // Mode 2: Dedicated cache exists but not enabled yet - dual-write mode
            (Some(dedicated_cache), false) => {
                // Read from shared cache (source of truth)
                let cache_result = self.shared_cache.get_or_load(key, load).await?;

                // Warm dedicated cache inline to avoid unbounded task spawning
                // This adds ~1-2ms latency but provides natural backpressure
                let cached_value = cache_result.value.clone();
                if let Err(e) = dedicated_cache
                    .get_or_load(key, move |_| async move {
                        // Return the same value we got from the shared cache
                        Ok::<Option<V>, FlagError>(cached_value)
                    })
                    .await
                {
                    tracing::warn!("Dedicated cache warming failed for key {}: {:?}", key, e);
                }

                Ok(cache_result)
            }
            // Mode 1: No dedicated cache configured - use shared cache only
            (None, _) => {
                let cache_result = self.shared_cache.get_or_load(key, load).await?;
                Ok(cache_result)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::DEFAULT_TEST_CONFIG;
    use crate::flags::flag_models::FeatureFlagList;
    use common_redis::MockRedisClient;
    use std::sync::Arc;

    #[tokio::test]
    async fn test_mode_1_only_uses_shared_cache() {
        // Mode 1: No dedicated cache configured - uses shared cache only
        let shared_client = Arc::new(MockRedisClient::new());

        let shared_cache = Arc::new(FeatureFlagList::create_cache(
            shared_client.clone(),
            shared_client.clone(),
            Some(60),
        ));

        let config = DEFAULT_TEST_CONFIG.clone();
        let flags_cache = FlagsReadThroughCache::new(shared_cache.clone(), None, config);

        // Make a request that will miss cache and trigger load
        let result = flags_cache
            .get_or_load(&123i64, |_| async {
                Ok::<Option<Vec<String>>, FlagError>(Some(vec!["test".to_string()]))
            })
            .await;

        assert!(result.is_ok());
        let cache_result = result.unwrap();
        assert_eq!(cache_result.value, Some(vec!["test".to_string()]));

        // Verify only shared cache was accessed
        let shared_client_calls = shared_client.get_calls();

        // Should have attempted to read from shared cache
        assert!(
            !shared_client_calls.is_empty()
                && shared_client_calls.iter().any(|call| call.op == "get"),
            "Expected shared cache read. Calls: {shared_client_calls:?}"
        );

        // Should have written to shared cache
        assert!(
            !shared_client_calls.is_empty()
                && shared_client_calls.iter().any(|call| call.op == "setex"),
            "Expected shared cache write. Calls: {shared_client_calls:?}"
        );
    }

    #[tokio::test]
    async fn test_mode_2_reads_shared_writes_both() {
        // Mode 2: Dedicated cache configured but not enabled - dual-write mode
        let shared_client = Arc::new(MockRedisClient::new());
        let dedicated_client = Arc::new(MockRedisClient::new());

        let shared_cache = Arc::new(FeatureFlagList::create_cache(
            shared_client.clone(),
            shared_client.clone(),
            Some(60),
        ));

        let dedicated_cache = Arc::new(FeatureFlagList::create_cache(
            dedicated_client.clone(),
            dedicated_client.clone(),
            Some(60),
        ));

        // flags_redis_enabled = false (dual-write mode)
        let config = DEFAULT_TEST_CONFIG.clone();
        // Note: DEFAULT_TEST_CONFIG has flags_redis_enabled=false by default

        let flags_cache =
            FlagsReadThroughCache::new(shared_cache.clone(), Some(dedicated_cache.clone()), config);

        // Make a request - should read from shared, write to both
        let result = flags_cache
            .get_or_load(&456i64, |_| async {
                Ok::<Option<Vec<String>>, FlagError>(Some(vec!["dual_write_test".to_string()]))
            })
            .await;

        assert!(result.is_ok());
        let cache_result = result.unwrap();
        assert_eq!(
            cache_result.value,
            Some(vec!["dual_write_test".to_string()])
        );

        // Verify read came from shared cache (source of truth)
        let shared_client_calls = shared_client.get_calls();
        let dedicated_client_calls = dedicated_client.get_calls();

        assert!(
            !shared_client_calls.is_empty()
                && shared_client_calls.iter().any(|call| call.op == "get"),
            "Expected read from shared cache. Calls: {shared_client_calls:?}"
        );

        // Note: Dedicated cache IS accessed in dual-write mode (to check if value exists)
        // but the result is not used - shared cache is still the source of truth
        assert!(
            !dedicated_client_calls.is_empty()
                && dedicated_client_calls.iter().any(|call| call.op == "get"),
            "Expected read attempt from dedicated cache (inline warming). Calls: {dedicated_client_calls:?}"
        );

        // Verify writes went to BOTH caches
        assert!(
            !shared_client_calls.is_empty()
                && shared_client_calls.iter().any(|call| call.op == "setex"),
            "Expected write to shared cache. Calls: {shared_client_calls:?}"
        );

        assert!(
            !dedicated_client_calls.is_empty()
                && dedicated_client_calls.iter().any(|call| call.op == "setex"),
            "Expected write to dedicated cache (inline dual-write). Calls: {dedicated_client_calls:?}"
        );
    }

    #[tokio::test]
    async fn test_mode_3_only_uses_dedicated_cache() {
        // Mode 3: Dedicated cache configured and enabled - uses dedicated only
        let shared_client = Arc::new(MockRedisClient::new());
        let dedicated_client = Arc::new(MockRedisClient::new());

        let shared_cache = Arc::new(FeatureFlagList::create_cache(
            shared_client.clone(),
            shared_client.clone(),
            Some(60),
        ));

        let dedicated_cache = Arc::new(FeatureFlagList::create_cache(
            dedicated_client.clone(),
            dedicated_client.clone(),
            Some(60),
        ));

        // flags_redis_enabled = true (dedicated-only mode)
        let mut config = DEFAULT_TEST_CONFIG.clone();
        config.flags_redis_enabled = crate::config::FlexBool(true);

        let flags_cache =
            FlagsReadThroughCache::new(shared_cache.clone(), Some(dedicated_cache.clone()), config);

        // Make a request - should only use dedicated cache
        let result = flags_cache
            .get_or_load(&789i64, |_| async {
                Ok::<Option<Vec<String>>, FlagError>(Some(vec!["dedicated_only_test".to_string()]))
            })
            .await;

        assert!(result.is_ok());
        let cache_result = result.unwrap();
        assert_eq!(
            cache_result.value,
            Some(vec!["dedicated_only_test".to_string()])
        );

        // Verify shared cache was NOT accessed at all
        let shared_client_calls = shared_client.get_calls();

        assert!(
            shared_client_calls.is_empty(),
            "Expected NO access to shared cache in dedicated-only mode. Calls: {shared_client_calls:?}"
        );

        // Verify only dedicated cache was accessed
        let dedicated_client_calls = dedicated_client.get_calls();

        assert!(
            !dedicated_client_calls.is_empty()
                && dedicated_client_calls.iter().any(|call| call.op == "get"),
            "Expected read from dedicated cache. Calls: {dedicated_client_calls:?}"
        );

        assert!(
            !dedicated_client_calls.is_empty()
                && dedicated_client_calls.iter().any(|call| call.op == "setex"),
            "Expected write to dedicated cache. Calls: {dedicated_client_calls:?}"
        );
    }
}
