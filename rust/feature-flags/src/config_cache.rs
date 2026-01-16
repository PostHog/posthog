use crate::api::cached_remote_config::CachedRemoteConfig;
use crate::api::errors::FlagError;
use common_hypercache::{HyperCacheReader, KeyType};
use std::sync::Arc;

/// Special value indicating cache miss
const HYPER_CACHE_EMPTY_VALUE: &str = "__missing__";

/// Read cached config from HyperCache
///
/// Returns:
/// - `Ok(Some(config))` - Cache hit with valid config
/// - `Ok(None)` - Cache miss (HyperCache exhausted all tiers) or Python's explicit miss marker
/// - `Err(FlagError)` - Parse error only
pub async fn get_cached_config(
    reader: &Arc<HyperCacheReader>,
    api_token: &str,
) -> Result<Option<CachedRemoteConfig>, FlagError> {
    let key = KeyType::string(api_token);

    let value = match reader.get(&key).await {
        Ok(v) => v,
        Err(e) => {
            tracing::debug!(
                api_token = %api_token,
                error = ?e,
                "Config not found in HyperCache"
            );
            return Ok(None);
        }
    };

    if value.is_null() {
        return Ok(None);
    }

    // Check for Python's explicit "__missing__" marker
    if let Some(s) = value.as_str() {
        if s == HYPER_CACHE_EMPTY_VALUE {
            return Ok(None);
        }
    }

    match serde_json::from_value::<CachedRemoteConfig>(value) {
        Ok(cached) => Ok(Some(cached)),
        Err(err) => {
            tracing::warn!(
                api_token = %api_token,
                error = %err,
                "Failed to parse cached config"
            );
            Err(FlagError::Internal(format!("Config parse error: {}", err)))
        }
    }
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
