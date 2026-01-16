use crate::api::errors::FlagError;
use common_hypercache::{HyperCacheReader, KeyType};
use serde_json::Value;
use std::sync::Arc;

/// Special value indicating cache miss
const HYPER_CACHE_EMPTY_VALUE: &str = "__missing__";

/// Read cached config from HyperCache as raw JSON.
///
/// Returns the config blob as-is without interpreting its structure.
///
/// Returns:
/// - `Ok(Some(value))` - Cache hit with config JSON
/// - `Ok(None)` - Cache miss or Python's explicit miss marker
/// - `Err(FlagError)` - HyperCache error
pub async fn get_cached_config(
    reader: &Arc<HyperCacheReader>,
    api_token: &str,
) -> Result<Option<Value>, FlagError> {
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

    // Handle null values
    if value.is_null() {
        return Ok(None);
    }

    // Check for Python's explicit "__missing__" marker
    if let Some(s) = value.as_str() {
        if s == HYPER_CACHE_EMPTY_VALUE {
            return Ok(None);
        }
    }

    Ok(Some(value))
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_hypercache::HyperCacheConfig;
    use common_redis::MockRedisClient;

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
        let reader = create_test_reader(mock_redis).await;

        let result = get_cached_config(&reader, "phc_test").await;
        assert!(result.is_ok());
        assert!(result.unwrap().is_none());
    }
}
