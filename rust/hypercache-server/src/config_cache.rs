use common_cache::NegativeCache;
use common_hypercache::{HyperCacheError, HyperCacheReader, KeyType, HYPER_CACHE_EMPTY_VALUE};
use common_metrics::inc;
use serde_json::Value;
use std::sync::{Arc, LazyLock};

const NEGATIVE_CACHE_HIT_METRIC: &str = "hypercache_server_negative_cache_hit_total";
const NEGATIVE_CACHE_INSERT_METRIC: &str = "hypercache_server_negative_cache_insert_total";

/// Namespaces served by the hypercache-server, used to partition negative
/// caches and label metrics.
#[derive(Debug, Clone, Copy)]
pub enum CacheNamespace {
    Surveys,
    Array,
}

impl CacheNamespace {
    fn metric_labels(self) -> &'static [(String, String)] {
        static SURVEYS: LazyLock<Vec<(String, String)>> =
            LazyLock::new(|| vec![("namespace".to_string(), "surveys".to_string())]);
        static ARRAY: LazyLock<Vec<(String, String)>> =
            LazyLock::new(|| vec![("namespace".to_string(), "array".to_string())]);

        match self {
            CacheNamespace::Surveys => &SURVEYS,
            CacheNamespace::Array => &ARRAY,
        }
    }
}

/// Read cached data from HyperCache as raw JSON.
///
/// Returns `Some(value)` on cache hit, `None` on miss or infrastructure error.
///
/// When `negative_cache` is provided, confirmed misses are tombstoned so that
/// repeated lookups return `None` without re-querying Redis or S3. Infrastructure
/// errors are not tombstoned to avoid cache poisoning during outages.
pub async fn get_cached_data(
    reader: &Arc<HyperCacheReader>,
    negative_cache: Option<&NegativeCache>,
    namespace: CacheNamespace,
    key: &str,
) -> Option<Value> {
    if let Some(nc) = negative_cache {
        if nc.contains(key) {
            inc(NEGATIVE_CACHE_HIT_METRIC, namespace.metric_labels(), 1);
            return None;
        }
    }

    let cache_key = KeyType::string(key);

    // Only confirmed misses are tombstoned; infrastructure errors return None
    // without poisoning the negative cache.
    let value = match reader.get(&cache_key).await {
        Ok(v) => v,
        Err(HyperCacheError::CacheMiss) => {
            insert_negative_cache(negative_cache, namespace, key);
            return None;
        }
        Err(e) => {
            tracing::warn!(key = %key, error = ?e, "HyperCache read failed");
            return None;
        }
    };

    // HyperCacheReader converts the Python __missing__ sentinel to Value::Null,
    // but we also check the string form defensively in case S3 returns it un-converted.
    let is_missing =
        value.is_null() || value.as_str().is_some_and(|s| s == HYPER_CACHE_EMPTY_VALUE);

    if is_missing {
        insert_negative_cache(negative_cache, namespace, key);
        return None;
    }

    Some(value)
}

/// Record a key as missing in the negative cache and emit the insertion metric.
fn insert_negative_cache(
    negative_cache: Option<&NegativeCache>,
    namespace: CacheNamespace,
    key: &str,
) {
    if let Some(nc) = negative_cache {
        nc.insert(key.to_string());
        inc(NEGATIVE_CACHE_INSERT_METRIC, namespace.metric_labels(), 1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_utils::helpers::dummy_s3_client;
    use common_hypercache::HyperCacheConfig;
    use common_redis::MockRedisClient;
    use common_s3::{MockS3Client, S3Error};

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

    fn make_reader(mock_redis: MockRedisClient, config: HyperCacheConfig) -> Arc<HyperCacheReader> {
        Arc::new(HyperCacheReader::new_with_s3_client(
            Arc::new(mock_redis),
            dummy_s3_client(),
            config,
        ))
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
        let reader = make_reader(mock_redis, config);

        let result = get_cached_data(&reader, None, CacheNamespace::Surveys, "phc_test").await;
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

        let reader = make_reader(mock_redis, config);

        let result = get_cached_data(&reader, None, CacheNamespace::Surveys, token).await;
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

        let reader = make_reader(mock_redis, config);

        let result = get_cached_data(&reader, None, CacheNamespace::Array, token).await;
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

        let reader = make_reader(mock_redis, config);

        let result = get_cached_data(&reader, None, CacheNamespace::Array, token).await;
        assert_eq!(result, Some(test_config_data));
    }

    #[tokio::test]
    async fn test_negative_cache_short_circuits_on_second_miss() {
        // Mock Redis returns CustomRedisError::NotFound for unknown keys by default,
        // so the first miss should populate the negative cache, and the second
        // should return None without hitting the reader.
        let config = test_config("surveys", "surveys.json");
        let mock_redis = MockRedisClient::new();
        let reader = make_reader(mock_redis, config);
        let negative_cache = NegativeCache::new(100, 300);

        let token = "phc_does_not_exist";
        assert!(!negative_cache.contains(token));

        let first = get_cached_data(
            &reader,
            Some(&negative_cache),
            CacheNamespace::Surveys,
            token,
        )
        .await;
        assert!(first.is_none());
        assert!(
            negative_cache.contains(token),
            "miss should populate the negative cache"
        );

        // Second call still returns None.
        let second = get_cached_data(
            &reader,
            Some(&negative_cache),
            CacheNamespace::Surveys,
            token,
        )
        .await;
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

        let reader = make_reader(mock_redis, config);
        let negative_cache = NegativeCache::new(100, 300);

        let result =
            get_cached_data(&reader, Some(&negative_cache), CacheNamespace::Array, token).await;
        assert!(result.is_none());
        assert!(
            negative_cache.contains(token),
            "__missing__ marker should populate the negative cache"
        );
    }

    #[tokio::test]
    async fn test_positive_hit_does_not_populate_negative_cache() {
        let config = test_config("surveys", "surveys.json");
        let token = "phc_exists";
        let cache_key = cache_key_for_token(&config, token);

        let test_data = serde_json::json!({
            "surveys": [{"id": "s1"}],
            "survey_config": null
        });
        let pickled = pickle_json(&test_data);

        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_raw_bytes_ret(&cache_key, Ok(pickled));

        let reader = make_reader(mock_redis, config);
        let negative_cache = NegativeCache::new(100, 300);

        let result = get_cached_data(
            &reader,
            Some(&negative_cache),
            CacheNamespace::Surveys,
            token,
        )
        .await;
        assert_eq!(result, Some(test_data));
        assert!(
            !negative_cache.contains(token),
            "positive hit must not insert into the negative cache"
        );
    }

    #[tokio::test]
    async fn test_negative_cache_tombstone_short_circuits_positive_data() {
        // Once a key is tombstoned, the negative cache short-circuits all lookups
        // until TTL expires — even if the underlying data has since been populated.
        // This is the expected trade-off: stale negatives resolve on TTL expiry.
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

        let reader = make_reader(mock_redis, config);
        let negative_cache = NegativeCache::new(100, 300);

        // Pre-seed a tombstone for a key that now has data in Redis.
        negative_cache.insert(token.to_string());

        // The negative cache short-circuits: returns None despite Redis having data.
        let result = get_cached_data(
            &reader,
            Some(&negative_cache),
            CacheNamespace::Surveys,
            token,
        )
        .await;
        assert!(
            result.is_none(),
            "tombstone should short-circuit even when Redis has data"
        );
        assert!(negative_cache.contains(token));
    }

    #[tokio::test]
    async fn test_infrastructure_failure_does_not_tombstone() {
        // When Redis returns a transient error (timeout, connection refused, etc.)
        // and S3 also fails, HyperCacheReader surfaces the infrastructure error
        // (not CacheMiss). The get_cached_data function's Err(e) arm returns None
        // without inserting into the negative cache, preventing cache poisoning
        // during outages. Both Redis and S3 must return infra errors.
        let config = test_config("surveys", "surveys.json");
        let token = "phc_infra_error";
        let cache_key = cache_key_for_token(&config, token);

        let mut mock_redis = MockRedisClient::new();
        mock_redis =
            mock_redis.get_raw_bytes_ret(&cache_key, Err(common_redis::CustomRedisError::Timeout));

        let mut mock_s3 = MockS3Client::new();
        mock_s3.expect_get_string().returning(|_, _| {
            Box::pin(async { Err(S3Error::OperationFailed("simulated S3 outage".to_string())) })
        });

        let reader = Arc::new(HyperCacheReader::new_with_s3_client(
            Arc::new(mock_redis),
            Arc::new(mock_s3),
            config,
        ));
        let negative_cache = NegativeCache::new(100, 300);

        let result = get_cached_data(
            &reader,
            Some(&negative_cache),
            CacheNamespace::Surveys,
            token,
        )
        .await;
        assert!(result.is_none(), "infra error should return None");
        assert!(
            !negative_cache.contains(token),
            "infrastructure failure must NOT insert into the negative cache"
        );
    }
}
