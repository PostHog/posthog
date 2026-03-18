//! Cache configuration types and cache operation results
//!
//! This module contains the core types used throughout the cache system:
//! - [`CacheConfig`]: Configuration for cache instances (prefix, TTL)
//! - [`CacheSource`]: Enum indicating where a value came from (for observability)
//! - [`CacheResult`]: Wrapper containing a value and its source

use std::fmt;

/// Configuration for cache instances
#[derive(Debug, Clone)]
pub struct CacheConfig {
    /// Redis key prefix for this cache instance (e.g., "team_token:", "feature_flags:")
    pub cache_prefix: String,

    /// Optional TTL in seconds for cached values
    /// If None, values are cached indefinitely
    pub ttl_seconds: Option<u64>,
}

impl CacheConfig {
    /// Create a new cache configuration
    pub fn new(cache_prefix: impl Into<String>, ttl_seconds: Option<u64>) -> Self {
        Self {
            cache_prefix: cache_prefix.into(),
            ttl_seconds,
        }
    }

    /// Create a cache configuration with no TTL (permanent caching)
    pub fn permanent(cache_prefix: impl Into<String>) -> Self {
        Self::new(cache_prefix, None)
    }

    /// Create a cache configuration with a TTL
    pub fn with_ttl(cache_prefix: impl Into<String>, ttl_seconds: u64) -> Self {
        Self::new(cache_prefix, Some(ttl_seconds))
    }
}

/// Indicates where a cached value came from and what operations were performed
///
/// This type implements `Display` for use in logging and metrics:
/// ```
/// # use common_cache::CacheSource;
/// let source = CacheSource::PositiveCache;
/// println!("Cache result: {}", source); // "positive_cache"
/// ```
#[non_exhaustive]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CacheSource {
    // Value found cases
    /// Value was found in Redis cache
    PositiveCache,
    /// Cache miss - value loaded from loader function
    LoaderCacheMiss,
    /// Cache data was corrupted - value loaded from loader function
    LoaderCacheCorrupted,
    /// Redis was unavailable - value loaded from loader function
    LoaderRedisUnavailable,

    // Value not found cases
    /// Key found in negative cache (known to not exist)
    NegativeCache,
    /// Cache miss - loader function indicated value doesn't exist
    LoaderNotFoundCacheMiss,
    /// Cache was corrupted - loader function indicated value doesn't exist
    LoaderNotFoundCacheCorrupted,
    /// Redis was unavailable - loader function indicated value doesn't exist
    LoaderNotFoundRedisUnavailable,
}

impl fmt::Display for CacheSource {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Display implementation for better logging and metrics.
        // This allows `CacheSource` to be used directly in log messages and metric tags
        // without needing to format the Debug representation or manually convert.
        //
        // Example: tracing::info!("Cache result: {}", result.source);
        // Example: metrics::counter!("cache.access", "source" => result.source.to_string());
        match self {
            CacheSource::PositiveCache => write!(f, "positive_cache"),
            CacheSource::NegativeCache => write!(f, "negative_cache"),
            CacheSource::LoaderCacheMiss => write!(f, "loader_cache_miss"),
            CacheSource::LoaderCacheCorrupted => write!(f, "loader_cache_corrupted"),
            CacheSource::LoaderRedisUnavailable => write!(f, "loader_redis_unavailable"),
            CacheSource::LoaderNotFoundCacheMiss => write!(f, "loader_not_found_cache_miss"),
            CacheSource::LoaderNotFoundCacheCorrupted => {
                write!(f, "loader_not_found_cache_corrupted")
            }
            CacheSource::LoaderNotFoundRedisUnavailable => {
                write!(f, "loader_not_found_redis_unavailable")
            }
        }
    }
}

/// Result of a cache operation with detailed source information
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CacheResult<V> {
    /// The value, if found. None indicates the item doesn't exist (negative result)
    pub value: Option<V>,

    /// Where the result came from - provides context for observability
    pub source: CacheSource,
}

impl<V> CacheResult<V> {
    /// Create a cache result with a value
    pub fn found(value: V, source: CacheSource) -> Self {
        Self {
            value: Some(value),
            source,
        }
    }

    /// Create a cache result indicating the value was not found
    pub fn not_found(source: CacheSource) -> Self {
        Self {
            value: None,
            source,
        }
    }

    /// Check if this was a cache hit (from Redis or negative cache)
    pub fn was_cached(&self) -> bool {
        matches!(
            self.source,
            CacheSource::PositiveCache | CacheSource::NegativeCache
        )
    }

    /// Check if the loader function was invoked
    pub fn invoked_loader(&self) -> bool {
        matches!(
            self.source,
            CacheSource::LoaderCacheMiss
                | CacheSource::LoaderCacheCorrupted
                | CacheSource::LoaderRedisUnavailable
                | CacheSource::LoaderNotFoundCacheMiss
                | CacheSource::LoaderNotFoundCacheCorrupted
                | CacheSource::LoaderNotFoundRedisUnavailable
        )
    }

    /// Check if there was a cache infrastructure problem
    pub fn had_cache_problem(&self) -> bool {
        matches!(
            self.source,
            CacheSource::LoaderCacheCorrupted
                | CacheSource::LoaderRedisUnavailable
                | CacheSource::LoaderNotFoundCacheCorrupted
                | CacheSource::LoaderNotFoundRedisUnavailable
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cache_result_helpers() {
        let result: CacheResult<i32> = CacheResult::found(42, CacheSource::PositiveCache);
        assert_eq!(result.value, Some(42));
        assert!(result.was_cached());
        assert!(!result.invoked_loader());
        assert!(!result.had_cache_problem());

        let result: CacheResult<i32> = CacheResult::not_found(CacheSource::LoaderNotFoundCacheMiss);
        assert_eq!(result.value, None);
        assert!(!result.was_cached());
        assert!(result.invoked_loader());
        assert!(!result.had_cache_problem());

        let result: CacheResult<i32> = CacheResult::found(42, CacheSource::LoaderCacheCorrupted);
        assert!(result.had_cache_problem());
        assert!(result.invoked_loader());
        assert!(!result.was_cached());
    }

    #[test]
    fn test_negative_cache_helper() {
        let result: CacheResult<String> = CacheResult::not_found(CacheSource::NegativeCache);
        assert!(result.was_cached());
        assert!(!result.invoked_loader());
        assert!(!result.had_cache_problem());
    }

    #[test]
    fn test_redis_unavailable_helper() {
        let result: CacheResult<i32> = CacheResult::found(42, CacheSource::LoaderRedisUnavailable);
        assert!(result.had_cache_problem());
        assert!(result.invoked_loader());
        assert!(!result.was_cached());

        let result: CacheResult<i32> =
            CacheResult::not_found(CacheSource::LoaderNotFoundRedisUnavailable);
        assert!(result.had_cache_problem());
        assert!(result.invoked_loader());
        assert!(!result.was_cached());
    }

    #[test]
    fn test_cache_source_display() {
        // Test Display implementation for use in logging and metrics
        assert_eq!(CacheSource::PositiveCache.to_string(), "positive_cache");
        assert_eq!(CacheSource::NegativeCache.to_string(), "negative_cache");
        assert_eq!(
            CacheSource::LoaderCacheMiss.to_string(),
            "loader_cache_miss"
        );
        assert_eq!(
            CacheSource::LoaderCacheCorrupted.to_string(),
            "loader_cache_corrupted"
        );
        assert_eq!(
            CacheSource::LoaderRedisUnavailable.to_string(),
            "loader_redis_unavailable"
        );
        assert_eq!(
            CacheSource::LoaderNotFoundCacheMiss.to_string(),
            "loader_not_found_cache_miss"
        );
        assert_eq!(
            CacheSource::LoaderNotFoundCacheCorrupted.to_string(),
            "loader_not_found_cache_corrupted"
        );
        assert_eq!(
            CacheSource::LoaderNotFoundRedisUnavailable.to_string(),
            "loader_not_found_redis_unavailable"
        );

        // Test that it works in format strings (useful for logging)
        let source = CacheSource::PositiveCache;
        assert_eq!(
            format!("Cache hit from: {source}"),
            "Cache hit from: positive_cache"
        );
    }
}
