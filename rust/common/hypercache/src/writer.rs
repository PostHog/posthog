use common_metrics::inc;
use common_redis::Client as RedisClient;
use common_redis::{PipelineCommand, RedisValueFormat};
use common_s3::S3Client;
use sha2::{Digest, Sha256};
use std::fmt::Write;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use tracing::warn;

use crate::{HyperCacheConfig, HyperCacheError, KeyType, HYPER_CACHE_EMPTY_VALUE};

const HYPERCACHE_OPERATION_COUNTER_NAME: &str = "posthog_hypercache_operation";
const ETAG_KEY_SUFFIX: &str = ":etag";
/// HyperCache always writes Redis values in Pickle format for Django compatibility.
const REDIS_FORMAT: RedisValueFormat = RedisValueFormat::Pickle;

/// Multi-tier cache writer for PostHog, matching Django's HyperCache write behavior.
///
/// Writes to Redis (primary, pickle-serialized, optionally zstd-compressed) and S3 (fallback, raw JSON).
/// Uses the same key generation as `HyperCacheReader` via shared `HyperCacheConfig`.
pub struct HyperCacheWriter {
    redis_client: Arc<dyn RedisClient + Send + Sync>,
    s3_client: Arc<dyn S3Client + Send + Sync>,
    config: HyperCacheConfig,
}

impl HyperCacheWriter {
    pub fn new(
        redis_client: Arc<dyn RedisClient + Send + Sync>,
        s3_client: Arc<dyn S3Client + Send + Sync>,
        config: HyperCacheConfig,
    ) -> Self {
        Self {
            redis_client,
            s3_client,
            config,
        }
    }

    /// Write JSON data to both Redis and S3.
    ///
    /// Redis value is pickle-serialized and optionally zstd-compressed (handled by the Redis
    /// client). S3 stores raw JSON.
    pub async fn set(
        &self,
        key: &KeyType,
        json_data: &str,
        ttl_seconds: u64,
    ) -> Result<(), HyperCacheError> {
        let redis_key = self.config.get_redis_cache_key(key);
        let s3_key = self.config.get_s3_cache_key(key);

        let (redis_result, etag_result, s3_result) = tokio::join!(
            self.redis_client.setex_with_format(
                redis_key.clone(),
                json_data.to_string(),
                ttl_seconds,
                REDIS_FORMAT,
            ),
            self.delete_etag(&redis_key),
            self.s3_client
                .put_string(&self.config.s3_bucket, &s3_key, json_data),
        );

        if let Err(e) = etag_result {
            warn!(error = %e, "Failed to delete ETag key during set");
        }

        self.check_results(redis_result, s3_result, "set")?;
        self.track_expiry(key, ttl_seconds).await;
        Ok(())
    }

    /// Mirror Python's `HyperCache._track_expiry`: record the write into the configured
    /// sorted set with `now + ttl_seconds` as the score. Failures are logged but never
    /// propagate — the cache entry itself was already written successfully.
    async fn track_expiry(&self, key: &KeyType, ttl_seconds: u64) {
        let Some(sorted_set_key) = self.config.expiry_sorted_set_key.as_deref() else {
            return;
        };
        let Ok(now) = SystemTime::now().duration_since(UNIX_EPOCH) else {
            warn!("System clock before UNIX_EPOCH; skipping expiry tracking");
            return;
        };
        // Clamp so `as i64` can't wrap to a negative Redis sorted-set score on extreme ttls.
        let raw = now.as_secs().saturating_add(ttl_seconds);
        let expiry_timestamp = i64::try_from(raw).unwrap_or_else(|_| {
            warn!(
                raw_seconds = raw,
                ttl_seconds,
                namespace = %self.config.namespace,
                "Expiry timestamp exceeds i64::MAX; clamping (ttl_seconds likely misinterpreted)",
            );
            i64::MAX
        });
        let identifier = self.config.get_cache_identifier(key);

        if let Err(e) = self
            .redis_client
            .zadd(sorted_set_key.to_string(), identifier, expiry_timestamp)
            .await
        {
            warn!(
                error = %e,
                namespace = %self.config.namespace,
                "Failed to track cache expiry",
            );
        }
    }

    /// Write JSON data to both Redis and S3, and store a computed ETag in Redis.
    ///
    /// The ETag is SHA-256 of the JSON bytes, first 16 hex chars (matching Python's
    /// `_compute_etag()`). Data and ETag are written atomically via a Redis pipeline.
    pub async fn set_with_etag(
        &self,
        key: &KeyType,
        json_data: &str,
        ttl_seconds: u64,
    ) -> Result<String, HyperCacheError> {
        let redis_key = self.config.get_redis_cache_key(key);
        let etag_key = format!("{redis_key}{ETAG_KEY_SUFFIX}");
        let s3_key = self.config.get_s3_cache_key(key);
        let etag = compute_etag(json_data);

        let pipeline_commands = vec![
            PipelineCommand::SetEx {
                key: redis_key,
                value: json_data.to_string(),
                seconds: ttl_seconds,
                format: REDIS_FORMAT,
            },
            PipelineCommand::SetEx {
                key: etag_key,
                value: etag.clone(),
                seconds: ttl_seconds,
                format: REDIS_FORMAT,
            },
        ];

        let (pipeline_result, s3_result) = tokio::join!(
            self.redis_client.execute_pipeline(pipeline_commands),
            self.s3_client
                .put_string(&self.config.s3_bucket, &s3_key, json_data),
        );

        // Flatten pipeline result: connection error or first per-command error
        let redis_result = pipeline_result.and_then(|results| {
            results
                .into_iter()
                .find_map(|r| r.err())
                .map_or(Ok(()), Err)
        });

        self.check_results(redis_result, s3_result, "set_with_etag")?;
        self.track_expiry(key, ttl_seconds).await;
        Ok(etag)
    }

    /// Write the "__missing__" sentinel to Redis (for teams with no flags) and delete from S3.
    /// Also removes the ETag key.
    pub async fn set_empty(&self, key: &KeyType, ttl_seconds: u64) -> Result<(), HyperCacheError> {
        let redis_key = self.config.get_redis_cache_key(key);
        let s3_key = self.config.get_s3_cache_key(key);

        let (redis_result, etag_result, s3_result) = tokio::join!(
            self.redis_client.setex_with_format(
                redis_key.clone(),
                HYPER_CACHE_EMPTY_VALUE.to_string(),
                ttl_seconds,
                REDIS_FORMAT,
            ),
            self.delete_etag(&redis_key),
            self.s3_client.delete(&self.config.s3_bucket, &s3_key),
        );

        if let Err(e) = etag_result {
            warn!(error = %e, "Failed to delete ETag key during set_empty");
        }

        self.check_results(redis_result, s3_result, "set_empty")
    }

    /// Remove from both Redis and S3.
    /// Also removes the ETag key.
    pub async fn delete(&self, key: &KeyType) -> Result<(), HyperCacheError> {
        let redis_key = self.config.get_redis_cache_key(key);
        let s3_key = self.config.get_s3_cache_key(key);

        let (redis_result, etag_result, s3_result) = tokio::join!(
            self.redis_client.del(redis_key.clone()),
            self.delete_etag(&redis_key),
            self.s3_client.delete(&self.config.s3_bucket, &s3_key),
        );

        if let Err(e) = etag_result {
            warn!(error = %e, "Failed to delete ETag key during delete");
        }

        self.check_results(redis_result, s3_result, "delete")
    }

    /// Delete the ETag key from Redis unconditionally.
    ///
    /// Always cleans up the ETag key as a safety net, even when `enable_etag` is false,
    /// to prevent stale ETags from causing incorrect 304 responses if the flag was
    /// previously enabled. Matches Python's `_set_cache_value_redis()` behavior.
    async fn delete_etag(&self, redis_key: &str) -> Result<(), common_redis::CustomRedisError> {
        let etag_key = format!("{redis_key}{ETAG_KEY_SUFFIX}");
        self.redis_client.del(etag_key).await
    }

    /// Check Redis and S3 results, emit metrics, and return the first error (logging the
    /// second if both fail so no failure is silently dropped).
    fn check_results(
        &self,
        redis_result: Result<(), common_redis::CustomRedisError>,
        s3_result: Result<(), common_s3::S3Error>,
        operation: &str,
    ) -> Result<(), HyperCacheError> {
        let redis_err = redis_result.err();
        let s3_err = s3_result.err();

        match (&redis_err, &s3_err) {
            (Some(re), Some(se)) => {
                self.emit_operation_metric(operation, "redis_and_s3_error");
                warn!(
                    redis_error = %re,
                    s3_error = %se,
                    namespace = %self.config.namespace,
                    "HyperCache write failed in both Redis and S3"
                );
                Err(HyperCacheError::Redis(re.clone()))
            }
            (Some(e), None) => {
                self.emit_operation_metric(operation, "redis_error");
                Err(HyperCacheError::Redis(e.clone()))
            }
            (None, Some(e)) => {
                self.emit_operation_metric(operation, "s3_error");
                Err(HyperCacheError::S3(e.clone()))
            }
            (None, None) => {
                self.emit_operation_metric(operation, "success");
                Ok(())
            }
        }
    }

    fn emit_operation_metric(&self, operation: &str, result: &str) {
        inc(
            HYPERCACHE_OPERATION_COUNTER_NAME,
            &[
                ("operation".to_string(), operation.to_string()),
                ("result".to_string(), result.to_string()),
                ("namespace".to_string(), self.config.namespace.clone()),
                ("value".to_string(), self.config.object_name.clone()),
            ],
            1,
        );
    }
}

/// Compute an ETag from a JSON string, matching Python's `_compute_etag()`.
///
/// Returns the first 16 hex characters of the SHA-256 hash of the UTF-8 bytes.
pub fn compute_etag(json_data: &str) -> String {
    let hash = Sha256::digest(json_data.as_bytes());
    let mut etag = String::with_capacity(16);
    for byte in &hash[..8] {
        let _ = write!(etag, "{byte:02x}");
    }
    etag
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::HyperCacheConfig;
    #[cfg(feature = "mock-client")]
    use common_redis::{MockRedisClient, MockRedisValue, RedisValueFormat};
    #[cfg(feature = "mock-client")]
    use common_s3::MockS3Client;

    fn create_test_config() -> HyperCacheConfig {
        HyperCacheConfig::new(
            "feature_flags".to_string(),
            "flags.json".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        )
    }

    #[cfg(feature = "mock-client")]
    fn create_test_writer(
        redis_client: MockRedisClient,
        s3_client: MockS3Client,
    ) -> HyperCacheWriter {
        HyperCacheWriter::new(
            Arc::new(redis_client),
            Arc::new(s3_client),
            create_test_config(),
        )
    }

    #[cfg(feature = "mock-client")]
    fn mock_s3_put_ok() -> MockS3Client {
        let mut s3 = MockS3Client::new();
        s3.expect_put_string()
            .returning(|_, _, _| Box::pin(async { Ok(()) }));
        s3
    }

    #[cfg(feature = "mock-client")]
    fn mock_s3_delete_ok() -> MockS3Client {
        let mut s3 = MockS3Client::new();
        s3.expect_delete()
            .returning(|_, _| Box::pin(async { Ok(()) }));
        s3
    }

    #[test]
    fn test_compute_etag_matches_python() {
        // Verified against Python:
        // >>> import hashlib
        // >>> hashlib.sha256('{"flags":[]}'.encode("utf-8")).hexdigest()[:16]
        // 'ccbb299897f0a689'
        assert_eq!(compute_etag(r#"{"flags":[]}"#), "ccbb299897f0a689");
    }

    #[test]
    fn test_compute_etag_deterministic() {
        // Verified against Python:
        // >>> hashlib.sha256('{"key":"value","nested":{"a":1}}'.encode("utf-8")).hexdigest()[:16]
        // 'faddcca5ffda22dc'
        let data = r#"{"key":"value","nested":{"a":1}}"#;
        assert_eq!(compute_etag(data), "faddcca5ffda22dc");
    }

    #[test]
    fn test_compute_etag_empty_string() {
        // >>> hashlib.sha256(b"").hexdigest()[:16]
        // 'e3b0c44298fc1c14'
        assert_eq!(compute_etag(""), "e3b0c44298fc1c14");
    }

    #[cfg(feature = "mock-client")]
    #[tokio::test]
    async fn test_set_writes_to_redis_and_s3() {
        let key = KeyType::int(123);
        let json_data = r#"{"flags":[{"id":1}]}"#;

        let mut redis = MockRedisClient::new();
        redis.set_ret("posthog:1:cache/teams/123/feature_flags/flags.json", Ok(()));
        redis.del_ret(
            "posthog:1:cache/teams/123/feature_flags/flags.json:etag",
            Ok(()),
        );

        let mut s3 = MockS3Client::new();
        s3.expect_put_string()
            .withf(|bucket, key, value| {
                bucket == "test-bucket"
                    && key == "cache/teams/123/feature_flags/flags.json"
                    && value == r#"{"flags":[{"id":1}]}"#
            })
            .times(1)
            .returning(|_, _, _| Box::pin(async { Ok(()) }));

        let redis = Arc::new(redis);
        let writer = HyperCacheWriter::new(redis.clone(), Arc::new(s3), create_test_config());
        writer.set(&key, json_data, 604800).await.unwrap();

        let calls = redis.get_calls();
        let setex_call = calls
            .iter()
            .find(|c| c.op == "setex_with_format")
            .expect("expected setex_with_format call");
        match &setex_call.value {
            MockRedisValue::StringWithTTLAndFormat(val, ttl, format) => {
                assert_eq!(val, json_data);
                assert_eq!(*ttl, 604800);
                assert_eq!(*format, RedisValueFormat::Pickle);
            }
            other => panic!("expected StringWithTTLAndFormat, got {other:?}"),
        }
        // set() always cleans up ETag as a safety net (matching Python behavior)
        let etag_del = calls
            .iter()
            .find(|c| c.op == "del" && c.key.ends_with(":etag"))
            .expect("expected del call for etag key");
        assert_eq!(
            etag_del.key,
            "posthog:1:cache/teams/123/feature_flags/flags.json:etag"
        );
        // No expiry tracking when `expiry_sorted_set_key` is None.
        assert!(calls.iter().all(|c| c.op != "zadd"));
    }

    #[cfg(feature = "mock-client")]
    fn assert_zadd_tracked_expiry(
        calls: &[common_redis::MockRedisCall],
        sorted_set_key: &str,
        member: &str,
        ttl_seconds: i64,
        captured_before_write: i64,
    ) {
        let zadd_call = calls
            .iter()
            .find(|c| c.op == "zadd")
            .expect("expected zadd call for expiry tracking");
        assert_eq!(zadd_call.key, sorted_set_key);
        match &zadd_call.value {
            MockRedisValue::MemberScore(m, score) => {
                assert_eq!(m, member);
                // Verify score ≈ now + ttl_seconds (not just now — a regression that forgot
                // to add ttl would still pass a `score > ttl_seconds` check because unix
                // timestamps dwarf any reasonable ttl). Allow a small upper tolerance for
                // test scheduling jitter between the capture and the write.
                let expected_lower = captured_before_write + ttl_seconds;
                let expected_upper = expected_lower + 60;
                assert!(
                    *score >= expected_lower && *score <= expected_upper,
                    "score {score} outside expected window [{expected_lower}, {expected_upper}]",
                );
            }
            other => panic!("expected MemberScore, got {other:?}"),
        }
    }

    #[cfg(feature = "mock-client")]
    fn unix_now_secs() -> i64 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("system clock before UNIX_EPOCH")
            .as_secs() as i64
    }

    #[cfg(feature = "mock-client")]
    #[tokio::test]
    async fn test_set_tracks_expiry_when_sorted_set_configured() {
        let key = KeyType::int(123);
        let json_data = r#"{"flags":[]}"#;

        let mut redis = MockRedisClient::new();
        redis.set_ret("posthog:1:cache/teams/123/feature_flags/flags.json", Ok(()));
        redis.del_ret(
            "posthog:1:cache/teams/123/feature_flags/flags.json:etag",
            Ok(()),
        );

        let redis = Arc::new(redis);
        let mut config = create_test_config();
        config.expiry_sorted_set_key = Some("flags_cache_expiry".to_string());
        let writer = HyperCacheWriter::new(redis.clone(), Arc::new(mock_s3_put_ok()), config);
        let before = unix_now_secs();
        writer.set(&key, json_data, 604800).await.unwrap();

        assert_zadd_tracked_expiry(
            &redis.get_calls(),
            "flags_cache_expiry",
            "123",
            604800,
            before,
        );
    }

    #[cfg(feature = "mock-client")]
    #[tokio::test]
    async fn test_track_expiry_clamps_to_i64_max_on_overflow() {
        let key = KeyType::int(123);

        let mut redis = MockRedisClient::new();
        redis.set_ret("posthog:1:cache/teams/123/feature_flags/flags.json", Ok(()));
        redis.del_ret(
            "posthog:1:cache/teams/123/feature_flags/flags.json:etag",
            Ok(()),
        );

        let redis = Arc::new(redis);
        let mut config = create_test_config();
        config.expiry_sorted_set_key = Some("flags_cache_expiry".to_string());
        let writer = HyperCacheWriter::new(redis.clone(), Arc::new(mock_s3_put_ok()), config);

        // Any ttl whose sum with the current unix time exceeds i64::MAX must clamp.
        writer.set(&key, "{}", u64::MAX).await.unwrap();

        let calls = redis.get_calls();
        let zadd = calls
            .iter()
            .find(|c| c.op == "zadd")
            .expect("expected zadd call for expiry tracking");
        match &zadd.value {
            MockRedisValue::MemberScore(member, score) => {
                assert_eq!(member, "123");
                assert_eq!(*score, i64::MAX, "expected score clamped to i64::MAX");
            }
            other => panic!("expected MemberScore, got {other:?}"),
        }
    }

    #[cfg(feature = "mock-client")]
    #[tokio::test]
    async fn test_set_s3_key_format() {
        let key = KeyType::int(789);
        let mut redis = MockRedisClient::new();
        redis.set_ret("posthog:1:cache/teams/789/feature_flags/flags.json", Ok(()));
        redis.del_ret(
            "posthog:1:cache/teams/789/feature_flags/flags.json:etag",
            Ok(()),
        );

        let mut s3 = MockS3Client::new();
        s3.expect_put_string()
            .withf(|_bucket, key, _value| key == "cache/teams/789/feature_flags/flags.json")
            .times(1)
            .returning(|_, _, _| Box::pin(async { Ok(()) }));

        let writer = create_test_writer(redis, s3);
        writer.set(&key, "{}", 604800).await.unwrap();
    }

    #[cfg(feature = "mock-client")]
    #[tokio::test]
    async fn test_set_with_etag_writes_data_and_etag() {
        let key = KeyType::int(123);
        let json_data = r#"{"flags":[]}"#;

        let mut redis = MockRedisClient::new();
        // Pipeline uses set_ret for both keys
        redis.set_ret("posthog:1:cache/teams/123/feature_flags/flags.json", Ok(()));
        redis.set_ret(
            "posthog:1:cache/teams/123/feature_flags/flags.json:etag",
            Ok(()),
        );

        let writer = create_test_writer(redis, mock_s3_put_ok());
        let etag = writer.set_with_etag(&key, json_data, 604800).await.unwrap();

        assert_eq!(etag, compute_etag(json_data));
    }

    #[cfg(feature = "mock-client")]
    #[tokio::test]
    async fn test_set_with_etag_tracks_expiry_when_sorted_set_configured() {
        let key = KeyType::int(123);
        let json_data = r#"{"flags":[]}"#;

        let mut redis = MockRedisClient::new();
        redis.set_ret("posthog:1:cache/teams/123/feature_flags/flags.json", Ok(()));
        redis.set_ret(
            "posthog:1:cache/teams/123/feature_flags/flags.json:etag",
            Ok(()),
        );

        let redis = Arc::new(redis);
        let mut config = create_test_config();
        config.expiry_sorted_set_key = Some("flags_cache_expiry".to_string());
        let writer = HyperCacheWriter::new(redis.clone(), Arc::new(mock_s3_put_ok()), config);
        let before = unix_now_secs();
        writer.set_with_etag(&key, json_data, 604800).await.unwrap();

        assert_zadd_tracked_expiry(
            &redis.get_calls(),
            "flags_cache_expiry",
            "123",
            604800,
            before,
        );
    }

    #[cfg(feature = "mock-client")]
    #[tokio::test]
    async fn test_set_with_etag_returns_correct_etag() {
        let key = KeyType::int(1);
        let json_data = r#"{"test":"data"}"#;

        let mut redis = MockRedisClient::new();
        redis.set_ret("posthog:1:cache/teams/1/feature_flags/flags.json", Ok(()));
        redis.set_ret(
            "posthog:1:cache/teams/1/feature_flags/flags.json:etag",
            Ok(()),
        );

        let writer = create_test_writer(redis, mock_s3_put_ok());
        let etag = writer.set_with_etag(&key, json_data, 604800).await.unwrap();

        assert_eq!(etag, compute_etag(json_data));
        assert_eq!(etag.len(), 16);
        assert!(etag.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[cfg(feature = "mock-client")]
    #[tokio::test]
    async fn test_set_empty_writes_sentinel() {
        let key = KeyType::int(123);

        let mut redis = MockRedisClient::new();
        redis.set_ret("posthog:1:cache/teams/123/feature_flags/flags.json", Ok(()));
        redis.del_ret(
            "posthog:1:cache/teams/123/feature_flags/flags.json:etag",
            Ok(()),
        );

        let redis = Arc::new(redis);
        let writer = HyperCacheWriter::new(
            redis.clone(),
            Arc::new(mock_s3_delete_ok()),
            create_test_config(),
        );
        writer.set_empty(&key, 86400).await.unwrap();

        let calls = redis.get_calls();
        let setex_call = calls
            .iter()
            .find(|c| c.op == "setex_with_format")
            .expect("expected setex_with_format call");
        match &setex_call.value {
            MockRedisValue::StringWithTTLAndFormat(val, ttl, format) => {
                assert_eq!(val, HYPER_CACHE_EMPTY_VALUE);
                assert_eq!(*ttl, 86400);
                assert_eq!(*format, RedisValueFormat::Pickle);
            }
            other => panic!("expected StringWithTTLAndFormat, got {other:?}"),
        }
        // ETag is always cleaned up as a safety net
        let etag_del = calls
            .iter()
            .find(|c| c.op == "del" && c.key.ends_with(":etag"))
            .expect("expected del call for etag key");
        assert_eq!(
            etag_del.key,
            "posthog:1:cache/teams/123/feature_flags/flags.json:etag"
        );
    }

    #[cfg(feature = "mock-client")]
    #[tokio::test]
    async fn test_delete_removes_from_both() {
        let key = KeyType::int(123);

        let mut redis = MockRedisClient::new();
        redis.del_ret("posthog:1:cache/teams/123/feature_flags/flags.json", Ok(()));
        redis.del_ret(
            "posthog:1:cache/teams/123/feature_flags/flags.json:etag",
            Ok(()),
        );

        let mut s3 = MockS3Client::new();
        s3.expect_delete()
            .withf(|bucket, key| {
                bucket == "test-bucket" && key == "cache/teams/123/feature_flags/flags.json"
            })
            .times(1)
            .returning(|_, _| Box::pin(async { Ok(()) }));

        let redis = Arc::new(redis);
        let writer = HyperCacheWriter::new(redis.clone(), Arc::new(s3), create_test_config());
        writer.delete(&key).await.unwrap();

        // ETag is always cleaned up as a safety net
        let calls = redis.get_calls();
        let etag_del = calls
            .iter()
            .find(|c| c.op == "del" && c.key.ends_with(":etag"))
            .expect("expected del call for etag key");
        assert_eq!(
            etag_del.key,
            "posthog:1:cache/teams/123/feature_flags/flags.json:etag"
        );
    }

    #[cfg(feature = "mock-client")]
    #[tokio::test]
    async fn test_redis_error_propagates() {
        let key = KeyType::int(123);

        let mut redis = MockRedisClient::new();
        redis.set_ret(
            "posthog:1:cache/teams/123/feature_flags/flags.json",
            Err(common_redis::CustomRedisError::Timeout),
        );

        let writer = create_test_writer(redis, mock_s3_put_ok());
        let result = writer.set(&key, "{}", 604800).await;

        assert!(matches!(result, Err(HyperCacheError::Redis(_))));
    }

    #[cfg(feature = "mock-client")]
    #[tokio::test]
    async fn test_s3_error_propagates() {
        let key = KeyType::int(123);

        let mut redis = MockRedisClient::new();
        redis.set_ret("posthog:1:cache/teams/123/feature_flags/flags.json", Ok(()));

        let mut s3 = MockS3Client::new();
        s3.expect_put_string().returning(|_, _, _| {
            Box::pin(async { Err(common_s3::S3Error::OperationFailed("timeout".to_string())) })
        });

        let writer = create_test_writer(redis, s3);
        let result = writer.set(&key, "{}", 604800).await;

        assert!(matches!(result, Err(HyperCacheError::S3(_))));
    }

    #[cfg(feature = "mock-client")]
    #[tokio::test]
    async fn test_both_redis_and_s3_error_returns_redis_error() {
        let key = KeyType::int(123);

        let mut redis = MockRedisClient::new();
        redis.set_ret(
            "posthog:1:cache/teams/123/feature_flags/flags.json",
            Err(common_redis::CustomRedisError::Timeout),
        );

        let mut s3 = MockS3Client::new();
        s3.expect_put_string().returning(|_, _, _| {
            Box::pin(async { Err(common_s3::S3Error::OperationFailed("s3 down".to_string())) })
        });

        let writer = create_test_writer(redis, s3);
        let result = writer.set(&key, "{}", 604800).await;

        assert!(matches!(result, Err(HyperCacheError::Redis(_))));
    }

    #[cfg(feature = "mock-client")]
    #[tokio::test]
    async fn test_set_with_etag_pipeline_error_propagates() {
        let key = KeyType::int(123);

        let mut redis = MockRedisClient::new();
        redis.set_ret("posthog:1:cache/teams/123/feature_flags/flags.json", Ok(()));
        redis.set_ret(
            "posthog:1:cache/teams/123/feature_flags/flags.json:etag",
            Err(common_redis::CustomRedisError::Timeout),
        );

        let writer = create_test_writer(redis, mock_s3_put_ok());
        let result = writer.set_with_etag(&key, r#"{"flags":[]}"#, 604800).await;

        assert!(matches!(result, Err(HyperCacheError::Redis(_))));
    }
}
