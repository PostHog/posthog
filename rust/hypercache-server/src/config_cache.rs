use common_hypercache::{HyperCacheReader, KeyType, HYPER_CACHE_EMPTY_VALUE};
use serde_json::Value;
use std::sync::Arc;

/// Read cached data from HyperCache as raw JSON.
///
/// Returns the data blob as-is without interpreting its structure.
///
/// HyperCache handles infrastructure resilience internally (Redis → S3 fallback),
/// converting operational errors to cache misses. This function only distinguishes:
/// - `Some(value)` - Cache hit with JSON data
/// - `None` - Cache miss (key not found, or infrastructure error handled by HyperCache)
pub async fn get_cached_data(reader: &Arc<HyperCacheReader>, key: &str) -> Option<Value> {
    let cache_key = KeyType::string(key);

    let value = match reader.get(&cache_key).await {
        Ok(v) => v,
        Err(e) => {
            tracing::warn!(key = %key, error = ?e, "HyperCache read failed");
            return None;
        }
    };

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

    fn test_config(namespace: &str, value: &str) -> HyperCacheConfig {
        let mut config = HyperCacheConfig::new(
            namespace.to_string(),
            value.to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        config.token_based = true;
        config
    }

    fn cache_key_for_token(config: &HyperCacheConfig, token: &str) -> String {
        let key = KeyType::string(token);
        config.get_redis_cache_key(&key)
    }

    fn pickle_json(value: &serde_json::Value) -> Vec<u8> {
        let json_str = serde_json::to_string(value).unwrap();
        serde_pickle::to_vec(&json_str, Default::default()).unwrap()
    }

    fn pickle_str(value: &str) -> Vec<u8> {
        serde_pickle::to_vec(&value, Default::default()).unwrap()
    }

    #[tokio::test]
    async fn test_cache_miss_returns_none() {
        let config = test_config("surveys", "surveys.json");
        let mock_redis = MockRedisClient::new();
        let reader = Arc::new(
            HyperCacheReader::new(Arc::new(mock_redis), config)
                .await
                .unwrap(),
        );

        let result = get_cached_data(&reader, "phc_test").await;
        assert!(result.is_none());
    }

    #[tokio::test]
    async fn test_cache_hit_returns_data() {
        let config = test_config("surveys", "surveys.json");
        let token = "phc_test_token";
        let cache_key = cache_key_for_token(&config, token);

        let test_data = serde_json::json!({
            "surveys": [{"id": "1", "name": "test"}],
            "survey_config": {"key": "value"}
        });
        let pickled = pickle_json(&test_data);

        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_raw_bytes_ret(&cache_key, Ok(pickled));

        let reader = Arc::new(
            HyperCacheReader::new(Arc::new(mock_redis), config)
                .await
                .unwrap(),
        );

        let result = get_cached_data(&reader, token).await;
        assert_eq!(result, Some(test_data));
    }

    #[tokio::test]
    async fn test_missing_marker_returns_none() {
        let config = test_config("array", "config.json");
        let token = "phc_test_token";
        let cache_key = cache_key_for_token(&config, token);

        let pickled = pickle_str(HYPER_CACHE_EMPTY_VALUE);

        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_raw_bytes_ret(&cache_key, Ok(pickled));

        let reader = Arc::new(
            HyperCacheReader::new(Arc::new(mock_redis), config)
                .await
                .unwrap(),
        );

        let result = get_cached_data(&reader, token).await;
        assert!(result.is_none());
    }

    #[tokio::test]
    async fn test_config_cache_hit() {
        let config = test_config("array", "config.json");
        let token = "phc_config_test";
        let cache_key = cache_key_for_token(&config, token);

        let test_config_data = serde_json::json!({
            "sessionRecording": {"endpoint": "/s/"},
            "heatmaps": true,
            "surveys": false
        });
        let pickled = pickle_json(&test_config_data);

        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_raw_bytes_ret(&cache_key, Ok(pickled));

        let reader = Arc::new(
            HyperCacheReader::new(Arc::new(mock_redis), config)
                .await
                .unwrap(),
        );

        let result = get_cached_data(&reader, token).await;
        assert_eq!(result, Some(test_config_data));
    }
}
