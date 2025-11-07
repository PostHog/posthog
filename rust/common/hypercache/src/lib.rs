//! Multi-tier cache reader for PostHog, matching Django's HyperCache behavior.
//!
//! Reads from Redis (primary) then S3 (fallback) for flag definitions and similar data.
//!
//! ```rust,no_run
//! use common_hypercache::{HyperCacheConfig, HyperCacheReader, KeyType};
//! use std::sync::Arc;
//!
//! # #[tokio::main]
//! # async fn main() -> Result<(), Box<dyn std::error::Error>> {
//! // Configure the cache
//! let config = HyperCacheConfig::new(
//!     "flags".to_string(),
//!     "definitions".to_string(),
//!     "us-east-1".to_string(),
//!     "my-bucket".to_string()
//! );
//!
//! // Create the cache reader (requires Redis client)
//! # let redis_client = Arc::new(common_redis::MockRedisClient::new());
//! let reader = HyperCacheReader::new(redis_client, config).await?;
//!
//! // Get data from cache (tries Redis first, then S3)
//! let team_key = KeyType::string("team-123");
//! let data = reader.get(&team_key).await?;
//! # Ok(())
//! # }
//! ```

use anyhow::Result;
use aws_config::BehaviorVersion;
use aws_sdk_s3::Client as AwsS3SdkClient;
use common_compression::{decompress_zstd, CompressionError};
use common_metrics::inc;
use common_redis::Client as RedisClient;
#[cfg(all(test, feature = "mock-client"))]
use common_s3::MockS3Client;
use common_s3::{S3Client, S3Error, S3Impl};
use common_types::{TeamId, TeamIdentifier};
#[cfg(all(test, feature = "mock-client"))]
use mockall::predicate;
use serde_json::Value;
use std::fmt::{self, Display};
use std::sync::Arc;
use std::time::Duration;
use thiserror::Error;
use tokio::time::timeout;
use tracing::debug;

/// Metric name for tracking hypercache operations in Prometheus (same one used in Django's HyperCache)
const HYPERCACHE_COUNTER_NAME: &str = "posthog_hypercache_get_from_cache";

/// Tombstone metric for tracking "impossible" failures that should never happen in production
/// Note this is a duplicate of the const in feature_flags::metrics::consts::TOMBSTONE_COUNTER
const TOMBSTONE_COUNTER_NAME: &str = "posthog_tombstone_total";

/// Sentinel value used in Redis to indicate that a cache key exists but has no data
const HYPER_CACHE_EMPTY_VALUE: &str = "__missing__";

/// Cache key type matching Django's KeyType = Team | str | int
#[derive(Debug)]
pub enum KeyType {
    Team(Box<dyn TeamIdentifier>),
    String(String),
    Int(TeamId),
}

impl KeyType {
    pub fn team(team: impl TeamIdentifier + 'static) -> Self {
        KeyType::Team(Box::new(team))
    }

    pub fn string(s: impl Into<String>) -> Self {
        KeyType::String(s.into())
    }

    pub fn int(id: TeamId) -> Self {
        KeyType::Int(id)
    }
}

impl From<&str> for KeyType {
    fn from(s: &str) -> Self {
        KeyType::String(s.to_string())
    }
}

impl From<String> for KeyType {
    fn from(s: String) -> Self {
        KeyType::String(s)
    }
}

impl From<TeamId> for KeyType {
    fn from(id: TeamId) -> Self {
        KeyType::Int(id)
    }
}

// No blanket From<T: TeamIdentifier> to avoid conflicts
impl From<common_types::Team> for KeyType {
    fn from(team: common_types::Team) -> Self {
        KeyType::Team(Box::new(team))
    }
}

impl Display for KeyType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            KeyType::Team(team) => write!(
                f,
                "Team(id: {}, token: {})",
                team.team_id(),
                team.api_token()
            ),
            KeyType::String(s) => write!(f, "String({s})"),
            KeyType::Int(i) => write!(f, "Int({i})"),
        }
    }
}

#[derive(Error, Debug)]
pub enum HyperCacheError {
    #[error("Redis error: {0}")]
    Redis(#[from] common_redis::CustomRedisError),

    #[error("S3 error: {0}")]
    S3(#[from] S3Error),

    #[error("JSON parsing error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("Compression error: {0}")]
    Compression(#[from] CompressionError),

    #[error("Cache miss - data not found in any tier")]
    CacheMiss,

    #[error("Timeout error: {0}")]
    Timeout(String),
}

#[derive(Debug, Clone, PartialEq)]
pub enum CacheSource {
    Redis,
    S3,
    Fallback,
}

#[derive(Debug, Clone)]
pub struct HyperCacheConfig {
    pub s3_bucket: String,
    pub s3_region: String,
    pub s3_endpoint: Option<String>,
    pub redis_timeout: Duration,
    pub s3_timeout: Duration,
    pub namespace: String,
    pub value: String,
    pub token_based: bool,
    pub django_cache_version: String,
}

impl HyperCacheConfig {
    /// Create config with explicit settings (defaults django_cache_version to "1")
    pub fn new(namespace: String, value: String, s3_region: String, s3_bucket: String) -> Self {
        Self {
            s3_bucket,
            s3_region,
            s3_endpoint: None,
            redis_timeout: Duration::from_millis(500),
            s3_timeout: Duration::from_secs(3),
            namespace,
            value,
            token_based: false,
            django_cache_version: "1".to_string(),
        }
    }

    /// Create config with custom django cache version
    pub fn with_django_cache_version(
        namespace: String,
        value: String,
        s3_region: String,
        s3_bucket: String,
        django_cache_version: String,
    ) -> Self {
        Self {
            s3_bucket,
            s3_region,
            s3_endpoint: None,
            redis_timeout: Duration::from_millis(500),
            s3_timeout: Duration::from_secs(3),
            namespace,
            value,
            token_based: false,
            django_cache_version,
        }
    }

    /// Generate cache key for Redis (includes Django's posthog:version: prefix)
    pub fn get_redis_cache_key(&self, key: &KeyType) -> String {
        let base_key = self.get_base_cache_key(key);
        format!("posthog:{}:{}", self.django_cache_version, base_key)
    }

    /// Generate cache key for S3 (no prefix, matches Django's object_storage keys)
    pub fn get_s3_cache_key(&self, key: &KeyType) -> String {
        self.get_base_cache_key(key)
    }

    /// Generate base cache key (used by both Redis and S3, but Redis adds prefix)
    fn get_base_cache_key(&self, key: &KeyType) -> String {
        let key_str = if self.token_based {
            match key {
                KeyType::Team(team) => team.api_token().to_string(),
                KeyType::String(s) => s.clone(),
                KeyType::Int(i) => i.to_string(),
            }
        } else {
            match key {
                KeyType::Team(team) => team.team_id().to_string(),
                KeyType::String(s) => s.clone(),
                KeyType::Int(i) => i.to_string(),
            }
        };

        if self.token_based {
            format!(
                "cache/team_tokens/{}/{}/{}",
                key_str, self.namespace, self.value
            )
        } else {
            format!("cache/teams/{}/{}/{}", key_str, self.namespace, self.value)
        }
    }
}

pub struct HyperCacheReader {
    redis_client: Arc<dyn RedisClient + Send + Sync>,
    s3_client: Arc<dyn S3Client + Send + Sync>,
    config: HyperCacheConfig,
}

impl HyperCacheReader {
    pub async fn new(
        redis_client: Arc<dyn RedisClient + Send + Sync>,
        config: HyperCacheConfig,
    ) -> Result<Self> {
        let mut aws_config_builder = aws_config::defaults(BehaviorVersion::latest())
            .region(aws_config::Region::new(config.s3_region.clone()));

        if let Some(endpoint) = &config.s3_endpoint {
            aws_config_builder = aws_config_builder.endpoint_url(endpoint);
        }

        let aws_config = aws_config_builder.load().await;

        let mut s3_config_builder = aws_sdk_s3::config::Builder::from(&aws_config);
        if config.s3_endpoint.is_some() {
            s3_config_builder = s3_config_builder.force_path_style(true);
        }

        let aws_s3_client = AwsS3SdkClient::from_conf(s3_config_builder.build());
        let s3_client = Arc::new(S3Impl::new(aws_s3_client)) as Arc<dyn S3Client + Send + Sync>;

        Ok(Self {
            redis_client,
            s3_client,
            config,
        })
    }

    /// Create a new HyperCacheReader with a custom S3 client (useful for testing)
    pub fn new_with_s3_client(
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

    pub async fn get_with_source(
        &self,
        key: &KeyType,
    ) -> Result<(Value, CacheSource), HyperCacheError> {
        let redis_cache_key = self.config.get_redis_cache_key(key);

        // Try Redis first
        match timeout(
            self.config.redis_timeout,
            self.try_get_from_redis(&redis_cache_key),
        )
        .await
        {
            Ok(Ok(data)) => {
                inc(
                    HYPERCACHE_COUNTER_NAME,
                    &[
                        ("result".to_string(), "hit_redis".to_string()),
                        ("namespace".to_string(), self.config.namespace.clone()),
                        ("value".to_string(), self.config.value.clone()),
                    ],
                    1,
                );

                if let Value::String(s) = &data {
                    if s == HYPER_CACHE_EMPTY_VALUE {
                        return Ok((Value::Null, CacheSource::Redis));
                    }
                }
                return Ok((data, CacheSource::Redis));
            }
            Ok(Err(_)) | Err(_) => {
                // Continue to S3 fallback
            }
        }

        // Try S3 fallback
        let s3_cache_key = self.config.get_s3_cache_key(key);
        match timeout(self.config.s3_timeout, self.try_get_from_s3(&s3_cache_key)).await {
            Ok(Ok(data)) => {
                inc(
                    HYPERCACHE_COUNTER_NAME,
                    &[
                        ("result".to_string(), "hit_s3".to_string()),
                        ("namespace".to_string(), self.config.namespace.clone()),
                        ("value".to_string(), self.config.value.clone()),
                    ],
                    1,
                );
                return Ok((data, CacheSource::S3));
            }
            Ok(Err(_)) | Err(_) => {
                // Both sources failed
            }
        }

        inc(
            HYPERCACHE_COUNTER_NAME,
            &[
                ("result".to_string(), "missing".to_string()),
                ("namespace".to_string(), self.config.namespace.clone()),
                ("value".to_string(), self.config.value.clone()),
            ],
            1,
        );

        // Also increment the tombstone counter for hypercache misses - this should never happen
        inc(
            TOMBSTONE_COUNTER_NAME,
            &[
                ("failure_type".to_string(), "hypercache_miss".to_string()),
                ("namespace".to_string(), self.config.namespace.clone()),
                ("value".to_string(), self.config.value.clone()),
            ],
            1,
        );

        Err(HyperCacheError::CacheMiss)
    }

    pub async fn get(&self, key: &KeyType) -> Result<Value, HyperCacheError> {
        let (data, _source) = self.get_with_source(key).await?;
        Ok(data)
    }

    /// Get a value from cache with fallback support
    ///
    /// This method tries to get data from cache (Redis first, then S3), and if both
    /// cache tiers miss, calls the provided fallback function to retrieve the data
    /// from an alternative source (e.g., database, API, computation, etc.).
    ///
    /// Unlike a read-through cache pattern, this method does NOT write the fallback
    /// result back to the cache. This is intentional to handle catastrophic cache
    /// miss scenarios without potentially corrupting the cache with data that may
    /// not match the expected format or freshness requirements.
    ///
    /// # Arguments
    /// * `key` - The key to look up
    /// * `fallback` - Function to call if both cache tiers miss
    ///
    /// # Returns
    /// * `Ok((Value, CacheSource))` - The value and its source (Redis, S3, or Fallback)
    /// * `Err(E)` - Error from the fallback function, or HyperCacheError if fallback returns None
    pub async fn get_with_source_or_fallback<F, Fut, E>(
        &self,
        key: &KeyType,
        fallback: F,
    ) -> Result<(Value, CacheSource), E>
    where
        F: FnOnce() -> Fut,
        Fut: std::future::Future<Output = Result<Option<Value>, E>>,
        E: From<HyperCacheError>,
    {
        // First try to get from cache (Redis then S3)
        match self.get_with_source(key).await {
            Ok((data, source)) => {
                // Cache hit - return the cached data
                Ok((data, source))
            }
            Err(HyperCacheError::CacheMiss) => {
                // Both cache tiers missed - try the fallback
                debug!("Cache miss for key {}, trying fallback", key);

                match fallback().await? {
                    Some(value) => {
                        inc(
                            HYPERCACHE_COUNTER_NAME,
                            &[
                                ("result".to_string(), "hit_fallback".to_string()),
                                ("namespace".to_string(), self.config.namespace.clone()),
                                ("value".to_string(), self.config.value.clone()),
                            ],
                            1,
                        );
                        Ok((value, CacheSource::Fallback))
                    }
                    None => {
                        // Tombstone metric - cache and database both miss is really unusual
                        inc(
                            TOMBSTONE_COUNTER_NAME,
                            &[
                                (
                                    "failure_type".to_string(),
                                    "hypercache_fallback_miss".to_string(),
                                ),
                                ("namespace".to_string(), self.config.namespace.clone()),
                                ("value".to_string(), self.config.value.clone()),
                            ],
                            1,
                        );
                        Err(HyperCacheError::CacheMiss.into())
                    }
                }
            }
            Err(e) => {
                // Other cache errors - propagate them
                Err(e.into())
            }
        }
    }

    /// Get access to the configuration (useful for testing)
    pub fn config(&self) -> &HyperCacheConfig {
        &self.config
    }

    async fn try_get_from_redis(&self, cache_key: &str) -> Result<Value, HyperCacheError> {
        // Try raw bytes (Django compresses data > 512 bytes with Zstd)
        match self.redis_client.get_raw_bytes(cache_key.to_string()).await {
            Ok(raw_bytes) => {
                // Try Zstd(Pickle(JSON)) decompression pipeline
                match decompress_zstd(&raw_bytes) {
                    Ok(decompressed_bytes) => {
                        match serde_pickle::from_slice::<String>(
                            &decompressed_bytes,
                            Default::default(),
                        ) {
                            Ok(json_string) => {
                                if json_string == HYPER_CACHE_EMPTY_VALUE {
                                    return Ok(Value::String(json_string));
                                }
                                match serde_json::from_str(&json_string) {
                                    Ok(value) => return Ok(value),
                                    Err(e) => {
                                        debug!("Failed to parse JSON from compressed Redis data for key '{}': {}", cache_key, e);
                                    }
                                }
                            }
                            Err(e) => {
                                debug!("Failed to deserialize pickle from compressed Redis data for key '{}': {}", cache_key, e);
                            }
                        }
                    }
                    Err(e) => {
                        debug!(
                            "Failed to decompress Redis data for key '{}': {}",
                            cache_key, e
                        );
                    }
                }

                // Try Pickle(JSON) without compression
                match serde_pickle::from_slice::<String>(&raw_bytes, Default::default()) {
                    Ok(json_string) => {
                        if json_string == HYPER_CACHE_EMPTY_VALUE {
                            return Ok(Value::String(json_string));
                        }
                        match serde_json::from_str(&json_string) {
                            Ok(value) => return Ok(value),
                            Err(e) => {
                                debug!("Failed to parse JSON from uncompressed Redis data for key '{}': {}", cache_key, e);
                            }
                        }
                    }
                    Err(e) => {
                        debug!("Failed to deserialize pickle from uncompressed Redis data for key '{}': {}", cache_key, e);
                    }
                }
            }
            Err(e) => {
                debug!(
                    "Failed to get raw bytes from Redis for key '{}': {}",
                    cache_key, e
                );
            }
        }

        Err(HyperCacheError::CacheMiss)
    }

    pub(crate) async fn try_get_from_s3(&self, cache_key: &str) -> Result<Value, HyperCacheError> {
        match self
            .s3_client
            .get_string(&self.config.s3_bucket, cache_key)
            .await
        {
            Ok(body_str) => match serde_json::from_str(&body_str) {
                Ok(value) => Ok(value),
                Err(e) => {
                    debug!(
                        "Failed to parse JSON from S3 data for key '{}': {}",
                        cache_key, e
                    );
                    Err(HyperCacheError::Json(e))
                }
            },
            Err(e) => {
                debug!("Failed to get data from S3 for key '{}': {}", cache_key, e);
                Err(HyperCacheError::S3(e))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::{CustomRedisError, MockRedisClient};
    use serde_json::json;

    // Test helper functions
    fn create_test_config() -> HyperCacheConfig {
        HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        )
    }

    #[cfg(test)]
    fn create_dummy_s3_client() -> Arc<dyn S3Client + Send + Sync> {
        #[cfg(feature = "mock-client")]
        {
            // Create a dummy mock S3 client for tests that don't actually use S3
            let mut mock_s3 = MockS3Client::new();
            mock_s3.expect_get_string().returning(|_, key| {
                let key_owned = key.to_string();
                Box::pin(async move { Err(S3Error::NotFound(key_owned)) })
            });
            Arc::new(mock_s3)
        }

        #[cfg(not(feature = "mock-client"))]
        {
            // Create a real S3 client when mock-client feature is not enabled
            use aws_config::BehaviorVersion;
            use aws_sdk_s3::config::Region;

            let config = aws_sdk_s3::Config::builder()
                .behavior_version(BehaviorVersion::latest())
                .region(Region::new("us-east-1"))
                .build();
            let s3_client = AwsS3SdkClient::from_conf(config);
            Arc::new(S3Impl::new(s3_client))
        }
    }

    fn create_test_reader_with_mocks(
        mock_redis: MockRedisClient,
        mock_s3: Arc<dyn S3Client + Send + Sync>,
    ) -> HyperCacheReader {
        HyperCacheReader::new_with_s3_client(
            Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            mock_s3,
            create_test_config(),
        )
    }

    #[test]
    fn test_hypercache_config_new() {
        let config = HyperCacheConfig::new(
            "test_namespace".to_string(),
            "test_value".to_string(),
            "eu-west-1".to_string(),
            "custom-bucket".to_string(),
        );
        assert_eq!(config.s3_bucket, "custom-bucket");
        assert_eq!(config.s3_region, "eu-west-1");
        assert_eq!(config.s3_endpoint, None);
        assert_eq!(config.namespace, "test_namespace");
        assert_eq!(config.value, "test_value");
        assert_eq!(config.django_cache_version, "1"); // Default value
    }

    #[test]
    fn test_hypercache_config_with_custom_django_cache_version() {
        let config = HyperCacheConfig::with_django_cache_version(
            "test_namespace".to_string(),
            "test_value".to_string(),
            "eu-west-1".to_string(),
            "custom-bucket".to_string(),
            "3".to_string(),
        );
        assert_eq!(config.django_cache_version, "3");

        // Test that cache keys use the custom version
        let redis_key = config.get_redis_cache_key(&KeyType::string("123"));
        assert_eq!(
            redis_key,
            "posthog:3:cache/teams/123/test_namespace/test_value"
        );
    }

    #[test]
    fn test_cache_key_generation() {
        // Test ID-based cache keys
        let config = HyperCacheConfig::new(
            "flags".to_string(),
            "definitions".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        assert!(!config.token_based);

        let redis_cache_key = config.get_redis_cache_key(&KeyType::string("123"));
        assert_eq!(
            redis_cache_key,
            "posthog:1:cache/teams/123/flags/definitions"
        );

        let s3_cache_key = config.get_s3_cache_key(&KeyType::string("123"));
        assert_eq!(s3_cache_key, "cache/teams/123/flags/definitions");

        // Test token-based cache keys
        let mut token_config = config.clone();
        token_config.token_based = true;

        let redis_cache_key = token_config.get_redis_cache_key(&KeyType::string("phc_abc123"));
        assert_eq!(
            redis_cache_key,
            "posthog:1:cache/team_tokens/phc_abc123/flags/definitions"
        );

        let s3_cache_key = token_config.get_s3_cache_key(&KeyType::string("phc_abc123"));
        assert_eq!(
            s3_cache_key,
            "cache/team_tokens/phc_abc123/flags/definitions"
        );
    }

    #[test]
    fn test_keytype_int_key() {
        let config = HyperCacheConfig::new(
            "flags".to_string(),
            "definitions".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let int_key = KeyType::int(999);

        // Test Redis cache key (includes Django prefix)
        let redis_cache_key = config.get_redis_cache_key(&int_key);
        assert_eq!(
            redis_cache_key,
            "posthog:1:cache/teams/999/flags/definitions"
        );

        // Test S3 cache key (no prefix)
        let s3_cache_key = config.get_s3_cache_key(&int_key);
        assert_eq!(s3_cache_key, "cache/teams/999/flags/definitions");
    }

    #[test]
    fn test_keytype_from_conversions() {
        let str_key: KeyType = "test_string".into();
        let string_key: KeyType = "test_string".to_string().into();
        let team_id_key: KeyType = 123i32.into();
        let i32_key: KeyType = 456i32.into();

        match str_key {
            KeyType::String(s) => assert_eq!(s, "test_string"),
            _ => panic!("Expected String variant"),
        }

        match string_key {
            KeyType::String(s) => assert_eq!(s, "test_string"),
            _ => panic!("Expected String variant"),
        }

        match team_id_key {
            KeyType::Int(i) => assert_eq!(i, 123),
            _ => panic!("Expected Int variant"),
        }

        match i32_key {
            KeyType::Int(i) => assert_eq!(i, 456),
            _ => panic!("Expected Int variant"),
        }
    }

    #[tokio::test]
    async fn test_get_with_source_empty_value() {
        let team_key = KeyType::string("123");
        let expected_data = "__missing__";

        let config = HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let expected_cache_key = config.get_redis_cache_key(&team_key);

        let mut mock_redis = MockRedisClient::new();
        // Simulate Django's pickle format for empty value
        let pickled_bytes = serde_pickle::to_vec(&expected_data, Default::default()).unwrap();
        mock_redis = mock_redis.get_raw_bytes_ret(&expected_cache_key, Ok(pickled_bytes));

        let reader = HyperCacheReader {
            redis_client: Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            s3_client: create_dummy_s3_client(),
            config,
        };

        let (result, source) = reader.get_with_source(&team_key).await.unwrap();
        assert_eq!(source, CacheSource::Redis);
        assert_eq!(result, Value::Null);
    }

    #[tokio::test]
    async fn test_try_get_from_redis_success() {
        let mut mock_redis = MockRedisClient::new();
        let test_data = json!({"flags": [], "group_type_mapping": {}});
        let test_data_str = serde_json::to_string(&test_data).unwrap();

        // Simulate Django's pickle format (uncompressed)
        let pickled_bytes = serde_pickle::to_vec(&test_data_str, Default::default()).unwrap();
        mock_redis = mock_redis.get_raw_bytes_ret("test_key", Ok(pickled_bytes));

        let config = HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let reader = HyperCacheReader {
            redis_client: Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            s3_client: create_dummy_s3_client(),
            config,
        };

        let result = reader.try_get_from_redis("test_key").await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), test_data);
    }

    #[tokio::test]
    async fn test_try_get_from_redis_compressed_data() {
        use common_compression::compress_zstd;

        let mut mock_redis = MockRedisClient::new();
        let test_data = json!({"flags": [], "group_type_mapping": {}});
        let test_data_str = serde_json::to_string(&test_data).unwrap();

        // Simulate Django's compression pipeline: JSON string -> Pickle -> Zstd
        let pickled_bytes = serde_pickle::to_vec(&test_data_str, Default::default()).unwrap();
        let compressed_bytes = compress_zstd(&pickled_bytes).unwrap();

        mock_redis = mock_redis.get_raw_bytes_ret("test_key", Ok(compressed_bytes));

        let config = HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let reader = HyperCacheReader {
            redis_client: Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            s3_client: create_dummy_s3_client(),
            config,
        };

        let result = reader.try_get_from_redis("test_key").await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), test_data);
    }

    #[tokio::test]
    async fn test_try_get_from_redis_pickled_uncompressed_data() {
        let mut mock_redis = MockRedisClient::new();
        let test_data = json!({"small": "data"});
        let test_data_str = serde_json::to_string(&test_data).unwrap();

        // Simulate Django's pipeline for small data: JSON string -> Pickle (no compression)
        let pickled_bytes = serde_pickle::to_vec(&test_data_str, Default::default()).unwrap();

        // Use the raw bytes method to provide the pickled (but uncompressed) bytes
        mock_redis = mock_redis.get_raw_bytes_ret("test_key", Ok(pickled_bytes));

        let config = HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let reader = HyperCacheReader {
            redis_client: Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            s3_client: create_dummy_s3_client(),
            config,
        };

        let result = reader.try_get_from_redis("test_key").await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), test_data);
    }

    #[tokio::test]
    async fn test_try_get_from_redis_not_found() {
        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_ret("test_key", Err(CustomRedisError::NotFound));

        let config = HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let reader = HyperCacheReader {
            redis_client: Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            s3_client: create_dummy_s3_client(),
            config,
        };

        let result = reader.try_get_from_redis("test_key").await;
        assert!(matches!(result, Err(HyperCacheError::CacheMiss)));
    }

    #[test]
    fn test_hypercache_error_conversion() {
        let cache_miss = HyperCacheError::CacheMiss;
        let redis_error = HyperCacheError::Redis(CustomRedisError::NotFound);
        let s3_error = HyperCacheError::S3(S3Error::OperationFailed("S3 error".to_string()));
        let json_error =
            HyperCacheError::Json(serde_json::from_str::<Value>("invalid").unwrap_err());
        let timeout_error = HyperCacheError::Timeout("Timeout".to_string());

        assert!(matches!(cache_miss, HyperCacheError::CacheMiss));
        assert!(matches!(redis_error, HyperCacheError::Redis(_)));
        assert!(matches!(s3_error, HyperCacheError::S3(_)));
        assert!(matches!(json_error, HyperCacheError::Json(_)));
        assert!(matches!(timeout_error, HyperCacheError::Timeout(_)));
    }

    #[tokio::test]
    async fn test_get_with_source_redis_hit() {
        let team_key = KeyType::string("123");
        let test_data = json!({"key": "value", "nested": {"data": "test"}});
        let test_data_str = serde_json::to_string(&test_data).unwrap();

        let config = HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let expected_cache_key = config.get_redis_cache_key(&team_key);

        let mut mock_redis = MockRedisClient::new();
        // Simulate Django's pickle format (uncompressed)
        let pickled_bytes = serde_pickle::to_vec(&test_data_str, Default::default()).unwrap();
        mock_redis = mock_redis.get_raw_bytes_ret(&expected_cache_key, Ok(pickled_bytes));

        let reader = HyperCacheReader {
            redis_client: Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            s3_client: create_dummy_s3_client(),
            config,
        };

        let (result, source) = reader.get_with_source(&team_key).await.unwrap();
        assert_eq!(source, CacheSource::Redis);
        assert_eq!(result, test_data);
    }

    #[tokio::test]
    #[cfg(feature = "mock-client")]
    async fn test_get_with_source_redis_miss_s3_hit() {
        let team_key = KeyType::string("123");
        let test_data = json!({"key": "value", "nested": {"data": "test"}});
        let test_data_str = serde_json::to_string(&test_data).unwrap();

        let config = HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let expected_cache_key = config.get_redis_cache_key(&team_key);
        let expected_s3_key = config.get_s3_cache_key(&team_key);

        // Redis returns NotFound
        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_ret(&expected_cache_key, Err(CustomRedisError::NotFound));
        // S3 returns data
        let mut mock_s3 = MockS3Client::new();
        mock_s3
            .expect_get_string()
            .with(
                predicate::eq("test-bucket"),
                predicate::eq(expected_s3_key.clone()),
            )
            .returning({
                let test_data_str = test_data_str.clone();
                move |_, _| {
                    let data = test_data_str.clone();
                    Box::pin(async move { Ok(data) })
                }
            });
        let mock_s3 = Arc::new(mock_s3);

        let reader = HyperCacheReader {
            redis_client: Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            s3_client: mock_s3,
            config,
        };

        // Both Redis and S3 miss should result in CacheMiss error
        let (result, source) = reader.get_with_source(&team_key).await.unwrap();
        assert_eq!(source, CacheSource::S3);
        assert_eq!(result, test_data);
    }

    #[tokio::test]
    async fn test_get_with_source_complete_miss() {
        let team_key = KeyType::string("123");

        let config = HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let expected_cache_key = config.get_redis_cache_key(&team_key);

        // Redis returns NotFound
        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_ret(&expected_cache_key, Err(CustomRedisError::NotFound));

        let reader = HyperCacheReader {
            redis_client: Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            s3_client: create_dummy_s3_client(),
            config,
        };

        // Both Redis and S3 miss should result in CacheMiss error
        let result = reader.get_with_source(&team_key).await;
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), HyperCacheError::CacheMiss));
    }

    #[tokio::test]
    async fn test_redis_json_parsing_error() {
        let cache_key = "cache/teams/123/test_namespace/test_value";
        let invalid_json = "invalid json data";

        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_ret(cache_key, Ok(invalid_json.to_string()));

        let config = HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let reader = HyperCacheReader {
            redis_client: Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            s3_client: create_dummy_s3_client(),
            config,
        };

        let result = reader.try_get_from_redis(cache_key).await;
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), HyperCacheError::CacheMiss));
    }

    #[tokio::test]
    async fn test_compression_error_handling() {
        let mut mock_redis = MockRedisClient::new();
        // Provide invalid compressed data that will fail decompression
        let invalid_compressed_bytes = vec![0xFF, 0xFE, 0xFD, 0xFC]; // Invalid zstd data
        mock_redis = mock_redis.get_raw_bytes_ret("test_key", Ok(invalid_compressed_bytes));

        let reader = create_test_reader_with_mocks(mock_redis, create_dummy_s3_client());

        let result = reader.try_get_from_redis("test_key").await;
        // Should fail gracefully and return CacheMiss since we try multiple decompression approaches
        assert!(matches!(result, Err(HyperCacheError::CacheMiss)));
    }

    #[tokio::test]
    async fn test_get_with_source_or_fallback_cache_hit_redis() {
        // Test that fallback is not called when Redis cache hits
        let team_key = KeyType::string("123");
        let test_data = json!({"key": "value", "nested": {"data": "test"}});
        let test_data_str = serde_json::to_string(&test_data).unwrap();

        let config = HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let expected_cache_key = config.get_redis_cache_key(&team_key);

        let mut mock_redis = MockRedisClient::new();
        // Simulate Django's pickle format (uncompressed)
        let pickled_bytes = serde_pickle::to_vec(&test_data_str, Default::default()).unwrap();
        mock_redis = mock_redis.get_raw_bytes_ret(&expected_cache_key, Ok(pickled_bytes));

        let reader = HyperCacheReader {
            redis_client: Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            s3_client: create_dummy_s3_client(),
            config,
        };

        let result: Result<(Value, CacheSource), HyperCacheError> = reader
            .get_with_source_or_fallback(&team_key, || async {
                // If this is called, the test should fail because we expect cache hit
                panic!("Fallback should not be called when cache hits!");
            })
            .await;

        assert!(result.is_ok());
        let (data, source) = result.unwrap();
        assert_eq!(source, CacheSource::Redis);
        assert_eq!(data, test_data);
    }

    #[tokio::test]
    #[cfg(feature = "mock-client")]
    async fn test_get_with_source_or_fallback_cache_hit_s3() {
        // Test that fallback is not called when S3 cache hits (after Redis miss)
        let team_key = KeyType::string("123");
        let test_data = json!({"key": "value", "nested": {"data": "test"}});
        let test_data_str = serde_json::to_string(&test_data).unwrap();

        let config = HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let expected_cache_key = config.get_redis_cache_key(&team_key);
        let expected_s3_key = config.get_s3_cache_key(&team_key);

        // Redis returns NotFound
        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_ret(&expected_cache_key, Err(CustomRedisError::NotFound));

        // S3 returns data
        let mut mock_s3 = MockS3Client::new();
        mock_s3
            .expect_get_string()
            .with(
                predicate::eq("test-bucket"),
                predicate::eq(expected_s3_key.clone()),
            )
            .returning({
                let test_data_str = test_data_str.clone();
                move |_, _| {
                    let data = test_data_str.clone();
                    Box::pin(async move { Ok(data) })
                }
            });
        let mock_s3 = Arc::new(mock_s3);

        let reader = HyperCacheReader {
            redis_client: Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            s3_client: mock_s3,
            config,
        };

        let result: Result<(Value, CacheSource), HyperCacheError> = reader
            .get_with_source_or_fallback(&team_key, || async {
                // If this is called, the test should fail because we expect cache hit
                panic!("Fallback should not be called when S3 cache hits!");
            })
            .await;

        assert!(result.is_ok());
        let (data, source) = result.unwrap();
        assert_eq!(source, CacheSource::S3);
        assert_eq!(data, test_data);
    }

    #[tokio::test]
    async fn test_get_with_source_or_fallback_uses_fallback() {
        // Test that fallback is called when both cache tiers miss
        let team_key = KeyType::string("123");
        let fallback_data = json!({"fallback": "data", "from": "database"});

        let config = HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let expected_cache_key = config.get_redis_cache_key(&team_key);

        // Redis returns NotFound
        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_ret(&expected_cache_key, Err(CustomRedisError::NotFound));

        let reader = HyperCacheReader {
            redis_client: Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            s3_client: create_dummy_s3_client(), // S3 will also return NotFound
            config,
        };

        let fallback_data_clone = fallback_data.clone();
        let result = reader
            .get_with_source_or_fallback(&team_key, || {
                let data = fallback_data_clone.clone();
                async move { Ok::<Option<Value>, HyperCacheError>(Some(data)) }
            })
            .await;

        assert!(result.is_ok());
        let (data, source) = result.unwrap();
        assert_eq!(source, CacheSource::Fallback);
        assert_eq!(data, fallback_data);
    }

    #[tokio::test]
    async fn test_get_with_source_or_fallback_fallback_returns_none() {
        // Test when fallback returns None (data doesn't exist in database either)
        let team_key = KeyType::string("123");

        let config = HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let expected_cache_key = config.get_redis_cache_key(&team_key);

        // Redis returns NotFound
        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_ret(&expected_cache_key, Err(CustomRedisError::NotFound));

        let reader = HyperCacheReader {
            redis_client: Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            s3_client: create_dummy_s3_client(),
            config,
        };

        let result = reader
            .get_with_source_or_fallback(&team_key, || async {
                Ok::<Option<Value>, HyperCacheError>(None)
            })
            .await;

        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), HyperCacheError::CacheMiss));
    }

    #[tokio::test]
    async fn test_get_with_source_or_fallback_fallback_error() {
        // Test when fallback returns an error
        let team_key = KeyType::string("123");

        let config = HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let expected_cache_key = config.get_redis_cache_key(&team_key);

        // Redis returns NotFound
        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_ret(&expected_cache_key, Err(CustomRedisError::NotFound));

        let reader = HyperCacheReader {
            redis_client: Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            s3_client: create_dummy_s3_client(),
            config,
        };

        #[derive(Debug)]
        struct CustomError(String);
        impl From<HyperCacheError> for CustomError {
            fn from(e: HyperCacheError) -> Self {
                CustomError(format!("Cache error: {e}"))
            }
        }

        let result = reader
            .get_with_source_or_fallback(&team_key, || async {
                Err::<Option<Value>, CustomError>(CustomError(
                    "Database connection failed".to_string(),
                ))
            })
            .await;

        assert!(result.is_err());
        match result.unwrap_err() {
            CustomError(msg) => assert!(msg.contains("Database connection failed")),
        }
    }

    #[tokio::test]
    async fn test_get_with_source_or_fallback_no_cache_write() {
        // Verify that fallback data is NOT written to cache
        let team_key = KeyType::string("123");
        let fallback_data = json!({"fallback": "data"});

        let config = HyperCacheConfig::new(
            "test".to_string(),
            "test".to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        let expected_cache_key = config.get_redis_cache_key(&team_key);

        // Redis returns NotFound initially
        let mut mock_redis = MockRedisClient::new();
        mock_redis = mock_redis.get_ret(&expected_cache_key, Err(CustomRedisError::NotFound));

        // Important: mock_redis should NOT receive any set/setex calls
        // If it did, the test would panic due to unexpected method calls

        let reader = HyperCacheReader {
            redis_client: Arc::new(mock_redis) as Arc<dyn RedisClient + Send + Sync>,
            s3_client: create_dummy_s3_client(),
            config,
        };

        let fallback_data_clone = fallback_data.clone();
        let result = reader
            .get_with_source_or_fallback(&team_key, || {
                let data = fallback_data_clone.clone();
                async move { Ok::<Option<Value>, HyperCacheError>(Some(data)) }
            })
            .await;

        assert!(result.is_ok());
        let (data, source) = result.unwrap();
        assert_eq!(source, CacheSource::Fallback);
        assert_eq!(data, fallback_data);

        // If we got here without panicking, it means no cache write was attempted
        // (MockRedisClient would panic on unexpected method calls)
    }
}
