//! Metrics wrapper for ReadThroughCache
//!
//! This module provides a wrapper around [`ReadThroughCache`] that automatically
//! emits Prometheus metrics for cache operations, enabling observability without
//! coupling the core cache implementation to metrics.
//!
//! # Example
//!
//! ```rust,ignore
//! use common_cache::{ReadThroughCache, ReadThroughCacheWithMetrics, CacheConfig};
//!
//! let cache = ReadThroughCache::new(
//!     redis_reader,
//!     redis_writer,
//!     CacheConfig::with_ttl("flags:", 300),
//!     None,
//! );
//!
//! // Wrap with metrics
//! let cache_with_metrics = ReadThroughCacheWithMetrics::new(
//!     cache,
//!     "flags",      // namespace for metrics (e.g., "flags", "surveys")
//!     "flag",       // cache_name for metrics (e.g., "flag", "team")
//!     &[("cache_type".to_string(), "dedicated".to_string())],  // additional labels
//! );
//!
//! // Use like regular cache - metrics are emitted automatically
//! let result = cache_with_metrics.get_or_load(&key, loader).await?;
//! ```

use crate::{CacheResult, ReadThroughCache};
use common_metrics::inc;
use serde::{Deserialize, Serialize};
use std::fmt::Display;
use std::future::Future;
use std::sync::Arc;

/// Wrapper around [`ReadThroughCache`] that emits Prometheus metrics
///
/// This wrapper adds observability to cache operations by emitting metrics
/// for cache hits, misses, and errors. It maintains separation of concerns by
/// keeping the core cache logic independent of metrics implementation.
///
/// # Metrics Emitted
///
/// All metrics use the pattern: `read_through_cache_{metric_name}_total`
/// with labels: `namespace`, `cache_name`, plus any additional labels
///
/// - `read_through_cache_reads_total` - Total cache read attempts
/// - `read_through_cache_hit_total{cache_hit="true|false"}` - Cache hit/miss tracking
/// - `read_through_cache_loader_invoked_total` - Times the loader function was called
/// - `read_through_cache_errors_total{reason="..."}` - Cache operation errors
pub struct ReadThroughCacheWithMetrics {
    inner: Arc<ReadThroughCache>,
    namespace: &'static str,
    cache_name: &'static str,
    additional_labels: Vec<(String, String)>,
}

impl ReadThroughCacheWithMetrics {
    /// Create a new metrics-wrapped cache
    ///
    /// # Arguments
    /// * `inner` - The underlying ReadThroughCache to wrap
    /// * `namespace` - Namespace for metrics (e.g., "flags", "surveys")
    /// * `cache_name` - Cache name for metrics (e.g., "flag", "team")
    /// * `additional_labels` - Extra labels to add to all metrics (e.g., cache_type, region)
    pub fn new(
        inner: Arc<ReadThroughCache>,
        namespace: &'static str,
        cache_name: &'static str,
        additional_labels: &[(String, String)],
    ) -> Self {
        Self {
            inner,
            namespace,
            cache_name,
            additional_labels: additional_labels.to_vec(),
        }
    }

    /// Get a value from cache or load it, emitting metrics
    ///
    /// This method wraps the underlying cache's `get_or_load` and automatically
    /// emits appropriate metrics based on the result.
    ///
    /// # Type Parameters
    /// * `K` - Key type (must be serializable and displayable)
    /// * `V` - Value type (must be serializable)
    /// * `E` - Error type from loader function
    /// * `F` - Loader function type
    /// * `Fut` - Future returned by loader
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
        // Call the underlying cache
        let result = self.inner.get_or_load(key, loader).await?;

        // Emit metrics based on result
        self.emit_metrics(&result);

        Ok(result)
    }

    /// Emit metrics based on cache result
    fn emit_metrics<V>(&self, result: &CacheResult<V>) {
        // Build base labels for all metrics
        let mut base_labels = vec![
            ("namespace".to_string(), self.namespace.to_string()),
            ("cache_name".to_string(), self.cache_name.to_string()),
        ];
        base_labels.extend(self.additional_labels.clone());

        // Track total reads
        inc("read_through_cache_reads_total", &base_labels, 1);

        // Track cache hits and misses
        let mut hit_labels = base_labels.clone();
        hit_labels.push(("cache_hit".to_string(), result.was_cached().to_string()));
        inc("read_through_cache_hit_total", &hit_labels, 1);

        // Track loader invocations
        if result.invoked_loader() {
            inc("read_through_cache_loader_invoked_total", &base_labels, 1);
        }

        // Track cache problems
        if result.had_cache_problem() {
            let mut error_labels = base_labels;
            error_labels.push(("reason".to_string(), result.source.to_string()));
            inc("read_through_cache_errors_total", &error_labels, 1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{CacheConfig, CacheSource};
    use common_redis::MockRedisClient;

    #[tokio::test]
    async fn test_metrics_wrapper_passes_through_result() {
        let redis_reader = Arc::new(MockRedisClient::new());
        let redis_writer = Arc::new(MockRedisClient::new());

        let cache = Arc::new(ReadThroughCache::new(
            redis_reader,
            redis_writer,
            CacheConfig::with_ttl("test:", 60),
            None,
        ));

        let cache_with_metrics = ReadThroughCacheWithMetrics::new(
            cache,
            "test_namespace",
            "test_cache",
            &[("cache_type".to_string(), "shared".to_string())],
        );

        // Test that the wrapper passes through results correctly
        let result = cache_with_metrics
            .get_or_load(&"key", |_| async {
                Ok::<Option<String>, ()>(Some("value".to_string()))
            })
            .await
            .unwrap();

        assert_eq!(result.value, Some("value".to_string()));
        // Should be cache miss on first access
        assert!(result.invoked_loader());
    }

    #[tokio::test]
    async fn test_metrics_wrapper_with_cache_hit() {
        let redis_reader = Arc::new(
            MockRedisClient::new().get_ret("test:key", Ok("\"cached_value\"".to_string())),
        );
        let redis_writer = Arc::new(MockRedisClient::new());

        let cache = Arc::new(ReadThroughCache::new(
            redis_reader,
            redis_writer,
            CacheConfig::with_ttl("test:", 60),
            None,
        ));

        let cache_with_metrics = ReadThroughCacheWithMetrics::new(
            cache,
            "test_namespace",
            "test_cache",
            &[("cache_type".to_string(), "dedicated".to_string())],
        );

        let result = cache_with_metrics
            .get_or_load(&"key", |_| async {
                Ok::<Option<String>, ()>(Some("fallback".to_string()))
            })
            .await
            .unwrap();

        assert_eq!(result.value, Some("cached_value".to_string()));
        assert_eq!(result.source, CacheSource::PositiveCache);
        assert!(result.was_cached());
        assert!(!result.invoked_loader());
    }
}
