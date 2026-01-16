//! Config cache reader for Python's RemoteConfig HyperCache
//!
//! This module reads the pre-computed SDK config from Python's HyperCache.
//! The config is stored at: `cache/team_tokens/{api_token}/array/config.json`
//!
//! HyperCache handles multi-tier lookups (Redis → S3 → Database) internally.
//! This module only handles Python-specific conventions like the "__missing__" marker.

use crate::api::cached_remote_config::CachedRemoteConfig;
use crate::api::errors::FlagError;
use common_hypercache::{HyperCacheReader, KeyType};
use std::sync::Arc;

/// Special value indicating cache miss (matches Python's _HYPER_CACHE_EMPTY_VALUE)
const HYPER_CACHE_EMPTY_VALUE: &str = "__missing__";

/// Read cached config from HyperCache
///
/// Returns:
/// - `Ok(Some(config))` - Cache hit with valid config
/// - `Ok(None)` - Cache miss (HyperCache exhausted all tiers) or Python's explicit miss marker
/// - `Err(FlagError)` - Parse error only (cache errors return Ok(None) to allow fallback)
pub async fn get_cached_config(
    reader: &Arc<HyperCacheReader>,
    api_token: &str,
) -> Result<Option<CachedRemoteConfig>, FlagError> {
    let key = KeyType::string(api_token);

    let value = match reader.get(&key).await {
        Ok(v) => v,
        Err(e) => {
            // HyperCache already tried all tiers (Redis → S3 → Database).
            // Any error here means the data genuinely isn't available.
            tracing::debug!(
                api_token = %api_token,
                error = ?e,
                "Config not found in HyperCache"
            );
            return Ok(None);
        }
    };

    // Handle null values
    if value.is_null() {
        return Ok(None);
    }

    // Check for Python's explicit "__missing__" marker
    // This indicates Python checked and determined the config doesn't exist
    if let Some(s) = value.as_str() {
        if s == HYPER_CACHE_EMPTY_VALUE {
            return Ok(None);
        }
    }

    // Parse the JSON into our struct
    serde_json::from_value::<CachedRemoteConfig>(value.clone())
        .map_err(|e| {
            tracing::warn!(
                api_token = %api_token,
                error = %e,
                raw_value = ?value,
                "Failed to parse cached config"
            );
            FlagError::Internal(format!("Config parse error: {}", e))
        })
        .map(Some)
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_hypercache::HyperCacheConfig;
    use common_redis::MockRedisClient;
    use std::sync::Arc;

    async fn create_test_reader(mock_redis: MockRedisClient) -> Arc<HyperCacheReader> {
        let config = HyperCacheConfig::new(
            "array".to_string(),
            "config.json".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );

        Arc::new(
            HyperCacheReader::new(Arc::new(mock_redis), config)
                .await
                .expect("Failed to create HyperCacheReader"),
        )
    }

    #[tokio::test]
    async fn test_cache_miss_returns_none() {
        let mock_redis = MockRedisClient::new();
        // Default mock returns cache miss
        let reader = create_test_reader(mock_redis).await;

        let result = get_cached_config(&reader, "phc_test").await;
        assert!(result.is_ok());
        assert!(result.unwrap().is_none());
    }
}
