use common_cache::{CacheResult, ReadThroughCache};
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
///    - Fire-and-forget writes to dedicated cache (warming)
/// 3. Dedicated Redis configured, flags_redis_enabled=true: Uses dedicated cache only
///
/// This allows us to:
/// - Develop locally without dedicated Redis
/// - Warm up dedicated cache in production before cutover
/// - Cut over to dedicated cache cleanly
pub struct FlagsReadThroughCache {
    shared_cache: Arc<ReadThroughCache>,
    dedicated_cache: Option<Arc<ReadThroughCache>>,
    config: Config,
}

impl FlagsReadThroughCache {
    /// Creates a new FlagsReadThroughCache with explicit caches (for testing)
    pub fn new(
        shared_cache: Arc<ReadThroughCache>,
        dedicated_cache: Option<Arc<ReadThroughCache>>,
        config: Config,
    ) -> Self {
        Self {
            shared_cache,
            dedicated_cache,
            config,
        }
    }

    /// Creates a FlagsReadThroughCache from Redis clients, encapsulating all cache selection logic
    ///
    /// # Cache Selection Strategy
    /// - If dedicated Redis URLs are configured: Creates both shared and dedicated caches
    /// - If dedicated Redis URLs are empty: Creates only shared cache (Mode 1)
    ///
    /// The `flags_redis_enabled` flag determines which cache is used for reads/writes.
    pub fn from_redis_clients(
        shared_redis_reader: Arc<dyn common_redis::Client + Send + Sync>,
        shared_redis_writer: Arc<dyn common_redis::Client + Send + Sync>,
        flags_redis_reader: Option<Arc<dyn common_redis::Client + Send + Sync>>,
        flags_redis_writer: Option<Arc<dyn common_redis::Client + Send + Sync>>,
        flags_cache_ttl_seconds: u64,
        config: Config,
    ) -> Self {
        use crate::flags::flag_models::FeatureFlagList;

        // Always create shared cache
        let shared_cache = Arc::new(FeatureFlagList::create_cache(
            shared_redis_reader,
            shared_redis_writer,
            Some(flags_cache_ttl_seconds),
        ));

        // Create dedicated cache only if dedicated Redis is configured
        let dedicated_cache = match (flags_redis_reader, flags_redis_writer) {
            (Some(reader), Some(writer)) => Some(Arc::new(FeatureFlagList::create_cache(
                reader,
                writer,
                Some(flags_cache_ttl_seconds),
            ))),
            _ => None,
        };

        Self {
            shared_cache,
            dedicated_cache,
            config,
        }
    }

    /// Returns the Redis clients that should be used for the team cache (critical path)
    ///
    /// Strategy:
    /// - If dedicated cache exists: Use dedicated Redis (critical path isolation)
    /// - Otherwise: Use shared Redis (fallback)
    pub fn get_team_cache_clients(
        shared_redis_reader: Arc<dyn common_redis::Client + Send + Sync>,
        shared_redis_writer: Arc<dyn common_redis::Client + Send + Sync>,
        flags_redis_reader: Option<Arc<dyn common_redis::Client + Send + Sync>>,
        flags_redis_writer: Option<Arc<dyn common_redis::Client + Send + Sync>>,
    ) -> (
        Arc<dyn common_redis::Client + Send + Sync>,
        Arc<dyn common_redis::Client + Send + Sync>,
    ) {
        match (flags_redis_reader, flags_redis_writer) {
            (Some(reader), Some(writer)) => (reader, writer),
            _ => (shared_redis_reader, shared_redis_writer),
        }
    }

    /// Get value from cache or load it, handling three operational modes
    ///
    /// # Behavior
    /// 1. No dedicated cache: Uses shared cache only
    /// 2. Dedicated cache exists, flags_redis_enabled=false: Dual-write mode
    ///    - Reads from shared cache (source of truth)
    ///    - Background writes to dedicated cache (warming)
    /// 3. Dedicated cache exists, flags_redis_enabled=true: Uses dedicated cache only
    ///
    /// # Type Parameters
    /// - `K`: Cache key type (must be Display + Clone + Send + Sync + Hash + Serialize + for<'de> Deserialize<'de> + 'static)
    /// - `V`: Cache value type (must be Clone + Send + Sync + Serialize + for<'de> Deserialize<'de> + 'static)
    /// - `F`: Async loader function type
    /// - `Fut`: Future returned by loader
    pub async fn get_or_load<K, V, F, Fut>(
        &self,
        key: &K,
        load: F,
    ) -> Result<CacheResult<V>, FlagError>
    where
        K: Display + Clone + Send + Sync + Hash + Serialize + for<'de> Deserialize<'de> + 'static,
        V: Clone + Send + Sync + Serialize + for<'de> Deserialize<'de> + 'static,
        F: FnOnce(&K) -> Fut + Clone + Send + 'static,
        Fut: std::future::Future<Output = Result<Option<V>, FlagError>> + Send + 'static,
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

                // Fire-and-forget: warm up dedicated cache in background
                let cached_value = cache_result.value.clone();
                let dedicated_cache = Arc::clone(dedicated_cache);
                let key_clone = key.clone();

                tokio::spawn(async move {
                    let _unused = dedicated_cache
                        .get_or_load(&key_clone, move |_| async move {
                            // Return the same value we got from the shared cache
                            Ok::<Option<V>, FlagError>(cached_value)
                        })
                        .await;
                });

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
        let shared_reader = Arc::new(MockRedisClient::new());
        let shared_writer = Arc::new(MockRedisClient::new());

        let shared_cache = Arc::new(FeatureFlagList::create_cache(
            shared_reader.clone(),
            shared_writer.clone(),
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
        let shared_reader_calls = shared_reader.get_calls();
        let shared_writer_calls = shared_writer.get_calls();

        // Should have attempted to read from shared cache
        assert!(
            !shared_reader_calls.is_empty()
                && shared_reader_calls.iter().any(|call| call.op == "get"),
            "Expected shared cache read. Calls: {shared_reader_calls:?}"
        );

        // Should have written to shared cache
        assert!(
            !shared_writer_calls.is_empty()
                && shared_writer_calls.iter().any(|call| call.op == "setex"),
            "Expected shared cache write. Calls: {shared_writer_calls:?}"
        );
    }

    #[tokio::test]
    async fn test_mode_2_reads_shared_writes_both() {
        // Mode 2: Dedicated cache configured but not enabled - dual-write mode
        let shared_reader = Arc::new(MockRedisClient::new());
        let shared_writer = Arc::new(MockRedisClient::new());
        let dedicated_reader = Arc::new(MockRedisClient::new());
        let dedicated_writer = Arc::new(MockRedisClient::new());

        let shared_cache = Arc::new(FeatureFlagList::create_cache(
            shared_reader.clone(),
            shared_writer.clone(),
            Some(60),
        ));

        let dedicated_cache = Arc::new(FeatureFlagList::create_cache(
            dedicated_reader.clone(),
            dedicated_writer.clone(),
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

        // Give background task a moment to complete
        tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;

        // Verify read came from shared cache (source of truth)
        let shared_reader_calls = shared_reader.get_calls();
        let dedicated_reader_calls = dedicated_reader.get_calls();

        assert!(
            !shared_reader_calls.is_empty()
                && shared_reader_calls.iter().any(|call| call.op == "get"),
            "Expected read from shared cache. Calls: {shared_reader_calls:?}"
        );

        // Note: Dedicated cache reader IS accessed in dual-write mode (to check if value exists)
        // but the result is not used - shared cache is still the source of truth
        assert!(
            !dedicated_reader_calls.is_empty()
                && dedicated_reader_calls.iter().any(|call| call.op == "get"),
            "Expected read attempt from dedicated cache (background warming). Calls: {dedicated_reader_calls:?}"
        );

        // Verify writes went to BOTH caches
        let shared_writer_calls = shared_writer.get_calls();
        let dedicated_writer_calls = dedicated_writer.get_calls();

        assert!(
            !shared_writer_calls.is_empty()
                && shared_writer_calls.iter().any(|call| call.op == "setex"),
            "Expected write to shared cache. Calls: {shared_writer_calls:?}"
        );

        assert!(
            !dedicated_writer_calls.is_empty()
                && dedicated_writer_calls.iter().any(|call| call.op == "setex"),
            "Expected write to dedicated cache (background dual-write). Calls: {dedicated_writer_calls:?}"
        );
    }

    #[tokio::test]
    async fn test_mode_3_only_uses_dedicated_cache() {
        // Mode 3: Dedicated cache configured and enabled - uses dedicated only
        let shared_reader = Arc::new(MockRedisClient::new());
        let shared_writer = Arc::new(MockRedisClient::new());
        let dedicated_reader = Arc::new(MockRedisClient::new());
        let dedicated_writer = Arc::new(MockRedisClient::new());

        let shared_cache = Arc::new(FeatureFlagList::create_cache(
            shared_reader.clone(),
            shared_writer.clone(),
            Some(60),
        ));

        let dedicated_cache = Arc::new(FeatureFlagList::create_cache(
            dedicated_reader.clone(),
            dedicated_writer.clone(),
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
        let shared_reader_calls = shared_reader.get_calls();
        let shared_writer_calls = shared_writer.get_calls();

        assert!(
            shared_reader_calls.is_empty(),
            "Expected NO reads from shared cache in dedicated-only mode. Calls: {shared_reader_calls:?}"
        );

        assert!(
            shared_writer_calls.is_empty(),
            "Expected NO writes to shared cache in dedicated-only mode. Calls: {shared_writer_calls:?}"
        );

        // Verify only dedicated cache was accessed
        let dedicated_reader_calls = dedicated_reader.get_calls();
        let dedicated_writer_calls = dedicated_writer.get_calls();

        assert!(
            !dedicated_reader_calls.is_empty()
                && dedicated_reader_calls.iter().any(|call| call.op == "get"),
            "Expected read from dedicated cache. Calls: {dedicated_reader_calls:?}"
        );

        assert!(
            !dedicated_writer_calls.is_empty()
                && dedicated_writer_calls.iter().any(|call| call.op == "setex"),
            "Expected write to dedicated cache. Calls: {dedicated_writer_calls:?}"
        );
    }
}
