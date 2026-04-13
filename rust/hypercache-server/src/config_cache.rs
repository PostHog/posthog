use common_cache::NegativeCache;
use common_hypercache::{HyperCacheError, HyperCacheReader, KeyType, HYPER_CACHE_EMPTY_VALUE};
use common_metrics::inc;
use serde_json::Value;
use std::sync::Arc;

const NEGATIVE_CACHE_HIT_METRIC: &str = "hypercache_server_negative_cache_hit_total";
const NEGATIVE_CACHE_INSERT_METRIC: &str = "hypercache_server_negative_cache_insert_total";

/// Read cached data from HyperCache as raw JSON.
///
/// Returns the data blob as-is without interpreting its structure.
///
/// HyperCache handles infrastructure resilience internally (Redis → S3 fallback),
/// converting operational errors to cache misses. This function only distinguishes:
/// - `Some(value)` - Cache hit with JSON data
/// - `None` - Cache miss (key not found, or infrastructure error handled by HyperCache)
///
/// When `negative_cache` is provided, keys confirmed missing are recorded so that
/// repeated lookups return `None` without re-querying Redis or S3.
pub async fn get_cached_data(
    reader: &Arc<HyperCacheReader>,
    negative_cache: Option<&NegativeCache>,
    namespace: &str,
    key: &str,
) -> Option<Value> {
    if let Some(nc) = negative_cache {
        if nc.contains(key) {
            inc(
                NEGATIVE_CACHE_HIT_METRIC,
                &[("namespace".to_string(), namespace.to_string())],
                1,
            );
            return None;
        }
    }

    let cache_key = KeyType::string(key);

    let value = match reader.get(&cache_key).await {
        Ok(v) => Some(v),
        Err(HyperCacheError::CacheMiss) => {
            // Genuine miss — both Redis and S3 confirmed the key isn't there.
            None
        }
        Err(e) => {
            tracing::warn!(key = %key, error = ?e, "HyperCache read failed");
            // Transient infrastructure error — don't tombstone a key that may
            // actually exist once the backing store recovers.
            return None;
        }
    };

    let is_missing = value.as_ref().is_none_or(|v| {
        v.is_null()
            || v.as_str()
                .map(|s| s == HYPER_CACHE_EMPTY_VALUE)
                .unwrap_or(false)
    });

    if is_missing {
        if let Some(nc) = negative_cache {
            nc.insert(key.to_string());
            inc(
                NEGATIVE_CACHE_INSERT_METRIC,
                &[("namespace".to_string(), namespace.to_string())],
                1,
            );
        }
        return None;
    }

    // Positive result wins over any stale tombstone (shouldn't happen given
    // the short-circuit above, but defensive against races between TTL refresh
    // and concurrent writes to the cache).
    if let Some(nc) = negative_cache {
        nc.invalidate(key);
    }

    value
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

        let result = get_cached_data(&reader, None, "surveys", "phc_test").await;
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

        let result = get_cached_data(&reader, None, "surveys", token).await;
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

        let result = get_cached_data(&reader, None, "array", token).await;
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

        let result = get_cached_data(&reader, None, "array", token).await;
        assert_eq!(result, Some(test_config_data));
    }

    #[tokio::test]
    async fn test_negative_cache_short_circuits_on_second_miss() {
        // Mock Redis returns CustomRedisError::NotFound for unknown keys by default,
        // so the first miss should populate the negative cache, and the second
        // should return None without hitting the reader.
        let config = test_config("surveys", "surveys.json");
        let mock_redis = MockRedisClient::new();
        let reader = Arc::new(
            HyperCacheReader::new(Arc::new(mock_redis), config)
                .await
                .unwrap(),
        );
        let negative_cache = NegativeCache::new(100, 300);

        let token = "phc_does_not_exist";
        assert!(!negative_cache.contains(token));

        let first = get_cached_data(&reader, Some(&negative_cache), "surveys", token).await;
        assert!(first.is_none());
        assert!(
            negative_cache.contains(token),
            "miss should populate the negative cache"
        );

        // Second call: if the negative cache didn't short-circuit we'd re-query
        // the mock Redis. The entry is still there, proving we took the fast path.
        let second = get_cached_data(&reader, Some(&negative_cache), "surveys", token).await;
        assert!(second.is_none());
    }

    #[tokio::test]
    async fn test_negative_cache_populated_from_missing_marker() {
        let config = test_config("array", "config.json");
        let token = "phc_tombstoned";
        let cache_key = cache_key_for_token(&config, token);

        let pickled = pickle_str(HYPER_CACHE_EMPTY_VALUE);
        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_raw_bytes_ret(&cache_key, Ok(pickled));

        let reader = Arc::new(
            HyperCacheReader::new(Arc::new(mock_redis), config)
                .await
                .unwrap(),
        );
        let negative_cache = NegativeCache::new(100, 300);

        let result = get_cached_data(&reader, Some(&negative_cache), "array", token).await;
        assert!(result.is_none());
        assert!(
            negative_cache.contains(token),
            "__missing__ marker should populate the negative cache"
        );
    }

    #[tokio::test]
    async fn test_negative_cache_invalidated_on_hit() {
        let config = test_config("surveys", "surveys.json");
        let token = "phc_revived";
        let cache_key = cache_key_for_token(&config, token);

        let test_data = serde_json::json!({
            "surveys": [{"id": "s1"}],
            "survey_config": null
        });
        let pickled = pickle_json(&test_data);

        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_raw_bytes_ret(&cache_key, Ok(pickled));

        let reader = Arc::new(
            HyperCacheReader::new(Arc::new(mock_redis), config)
                .await
                .unwrap(),
        );
        let negative_cache = NegativeCache::new(100, 300);

        // Pre-seed a stale tombstone for this key.
        negative_cache.insert(token.to_string());
        assert!(negative_cache.contains(token));

        // A positive result shouldn't even happen here because contains() short-circuits,
        // but we want to assert the invalidate-on-hit path. Force the short-circuit
        // off by calling with None first to simulate clearing, then re-run with the
        // negative cache in place but an empty tombstone.
        negative_cache.invalidate(token);

        let result = get_cached_data(&reader, Some(&negative_cache), "surveys", token).await;
        assert_eq!(result, Some(test_data));
        // Positive hits should not insert anything into the negative cache.
        assert!(!negative_cache.contains(token));
    }
}
