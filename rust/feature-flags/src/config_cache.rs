use common_hypercache::{HyperCacheReader, KeyType, HYPER_CACHE_EMPTY_VALUE};
use serde_json::Value;
use std::sync::Arc;

/// Read cached config from HyperCache as raw JSON.
///
/// Returns the config blob as-is without interpreting its structure.
///
/// HyperCache handles infrastructure resilience internally (Redis → S3 fallback),
/// converting operational errors to cache misses. This function only distinguishes:
/// - `Some(value)` - Cache hit with config JSON
/// - `None` - Cache miss (key not found, or infrastructure error handled by HyperCache)
pub async fn get_cached_config(reader: &Arc<HyperCacheReader>, api_token: &str) -> Option<Value> {
    let key = KeyType::string(api_token);

    let value = match reader.get(&key).await {
        Ok(v) => v,
        Err(_) => {
            // Cache miss or internal op error, common-hypercache treats both the same
            // TODO: standardize hypercache crate miss/error handling
            return None;
        }
    };

    // Handle null values
    if value.is_null() {
        return None;
    }

    // Check for Python's explicit "__missing__" marker
    if let Some(s) = value.as_str() {
        if s == HYPER_CACHE_EMPTY_VALUE {
            return None;
        }
    }

    Some(value)
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_hypercache::HyperCacheConfig;
    use common_redis::MockRedisClient;

    fn test_config() -> HyperCacheConfig {
        HyperCacheConfig::new(
            "array".to_string(),
            "config.json".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        )
    }

    fn cache_key_for_token(config: &HyperCacheConfig, token: &str) -> String {
        let key = KeyType::string(token);
        config.get_redis_cache_key(&key)
    }

    async fn create_test_reader(mock_redis: MockRedisClient) -> Arc<HyperCacheReader> {
        let config = test_config();
        Arc::new(
            HyperCacheReader::new(Arc::new(mock_redis), config)
                .await
                .expect("Failed to create HyperCacheReader"),
        )
    }

    #[tokio::test]
    async fn test_cache_miss_returns_none() {
        // Empty mock returns NotFound, which HyperCache converts to CacheMiss
        let mock_redis = MockRedisClient::new();
        let reader = create_test_reader(mock_redis).await;

        let result = get_cached_config(&reader, "phc_test").await;

        assert!(result.is_none());
    }

    #[tokio::test]
    async fn test_cache_hit_returns_config() {
        let config = test_config();
        let token = "phc_test_token";
        let cache_key = cache_key_for_token(&config, token);

        let test_config = serde_json::json!({
            "sessionRecording": true,
            "surveys": false
        });
        let config_str = serde_json::to_string(&test_config).unwrap();
        let pickled = serde_pickle::to_vec(&config_str, Default::default()).unwrap();

        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_raw_bytes_ret(&cache_key, Ok(pickled));

        let reader = Arc::new(
            HyperCacheReader::new(Arc::new(mock_redis), config)
                .await
                .unwrap(),
        );

        let result = get_cached_config(&reader, token).await;

        assert!(result.is_some());
        assert_eq!(result.unwrap(), test_config);
    }

    #[tokio::test]
    async fn test_missing_marker_returns_none() {
        let config = test_config();
        let token = "phc_test_token";
        let cache_key = cache_key_for_token(&config, token);

        // Python writes "__missing__" marker when config doesn't exist
        let pickled = serde_pickle::to_vec(&HYPER_CACHE_EMPTY_VALUE, Default::default()).unwrap();

        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_raw_bytes_ret(&cache_key, Ok(pickled));

        let reader = Arc::new(
            HyperCacheReader::new(Arc::new(mock_redis), config)
                .await
                .unwrap(),
        );

        let result = get_cached_config(&reader, token).await;

        assert!(result.is_none());
    }
}
