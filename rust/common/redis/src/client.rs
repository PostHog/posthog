use async_trait::async_trait;
use redis::aio::MultiplexedConnection;
use redis::{AsyncCommands, RedisError};
use std::time::Duration;
use tracing::warn;

use crate::{Client, CompressionConfig, CustomRedisError, RedisValueFormat};

// Error messages for consistent handling of RawBytes format
const ERR_RAWBYTES_GET: &str = "Use get_raw_bytes() for RawBytes format";
const ERR_RAWBYTES_SET: &str =
    "RawBytes format not supported in set_with_format, use set_raw_bytes instead";

pub struct RedisClient {
    connection: MultiplexedConnection,
    compression: CompressionConfig,
    format: RedisValueFormat,
}

impl RedisClient {
    /// Create a new RedisClient with default settings
    ///
    /// Defaults:
    /// - Format: Pickle (Django-compatible)
    /// - Compression: Disabled
    /// - Timeouts: None (blocks indefinitely)
    ///
    /// For timeout configuration, use `with_config()` and specify `response_timeout` and `connection_timeout`.
    pub async fn new(addr: String) -> Result<RedisClient, CustomRedisError> {
        Self::with_config(
            addr,
            CompressionConfig::disabled(),
            RedisValueFormat::default(),
            None, // No response timeout
            None, // No connection timeout
        )
        .await
    }

    /// Create a new RedisClient with full configuration control
    ///
    /// # Arguments
    /// * `addr` - Redis connection string
    /// * `compression` - Compression configuration (see CompressionConfig)
    /// * `format` - Serialization format for values (see RedisValueFormat)
    /// * `response_timeout` - Optional timeout for Redis command responses. `None` means no timeout (blocks indefinitely).
    /// * `connection_timeout` - Optional timeout for establishing connections. `None` means no timeout (blocks indefinitely).
    ///
    /// # Errors
    /// Returns `CustomRedisError::InvalidConfiguration` if `Some(Duration::ZERO)` is passed - use `None` for no timeout instead.
    ///
    /// # Examples
    /// ```no_run
    /// use common_redis::{RedisClient, CompressionConfig, RedisValueFormat};
    /// use std::time::Duration;
    ///
    /// # async fn example() {
    /// // With timeouts (100ms response, 5000ms connection)
    /// let client = RedisClient::with_config(
    ///     "redis://localhost:6379".to_string(),
    ///     CompressionConfig::disabled(),
    ///     RedisValueFormat::default(),
    ///     Some(Duration::from_millis(100)),
    ///     Some(Duration::from_millis(5000)),
    /// ).await.unwrap();
    ///
    /// // No timeouts (blocks indefinitely)
    /// let client = RedisClient::with_config(
    ///     "redis://localhost:6379".to_string(),
    ///     CompressionConfig::disabled(),
    ///     RedisValueFormat::default(),
    ///     None,
    ///     None,
    /// ).await.unwrap();
    ///
    /// // Custom compression with timeouts
    /// let client = RedisClient::with_config(
    ///     "redis://localhost:6379".to_string(),
    ///     CompressionConfig::new(true, 1024, 3),
    ///     RedisValueFormat::default(),
    ///     Some(Duration::from_millis(100)),
    ///     Some(Duration::from_millis(5000)),
    /// ).await.unwrap();
    ///
    /// // Custom format with no timeouts
    /// let client = RedisClient::with_config(
    ///     "redis://localhost:6379".to_string(),
    ///     CompressionConfig::default(),
    ///     RedisValueFormat::Utf8,
    ///     None,
    ///     None,
    /// ).await.unwrap();
    ///
    /// // Full custom configuration with timeouts
    /// let client = RedisClient::with_config(
    ///     "redis://localhost:6379".to_string(),
    ///     CompressionConfig::new(true, 1024, 3),
    ///     RedisValueFormat::Utf8,
    ///     Some(Duration::from_millis(100)),
    ///     Some(Duration::from_millis(5000)),
    /// ).await.unwrap();
    /// # }
    /// ```
    pub async fn with_config(
        addr: String,
        compression: CompressionConfig,
        format: RedisValueFormat,
        response_timeout: Option<Duration>,
        connection_timeout: Option<Duration>,
    ) -> Result<RedisClient, CustomRedisError> {
        let client = redis::Client::open(addr)?;

        // Validate that Duration::ZERO is not passed - use None instead
        if let Some(timeout) = response_timeout {
            if timeout.is_zero() {
                return Err(CustomRedisError::InvalidConfiguration(
                    "Redis response timeout cannot be Duration::ZERO - use None for no timeout"
                        .to_string(),
                ));
            }
        }
        if let Some(timeout) = connection_timeout {
            if timeout.is_zero() {
                return Err(CustomRedisError::InvalidConfiguration(
                    "Redis connection timeout cannot be Duration::ZERO - use None for no timeout"
                        .to_string(),
                ));
            }
        }

        // Use Redis native timeout configuration
        // None means no timeout (blocks indefinitely)
        let mut config = redis::AsyncConnectionConfig::new();

        if let Some(timeout) = response_timeout {
            config = config.set_response_timeout(timeout);
        }

        if let Some(timeout) = connection_timeout {
            config = config.set_connection_timeout(timeout);
        }

        let connection = client
            .get_multiplexed_async_connection_with_config(&config)
            .await?;

        Ok(RedisClient {
            connection,
            compression,
            format,
        })
    }

    /// Attempt to decompress data, falling back to original if not compressed
    ///
    /// Mimics Django's ZstdCompressor.decompress() behavior:
    /// - Try to decompress with zstd
    /// - If decompression fails, return original data unchanged
    /// - This allows graceful handling of both compressed and uncompressed data
    ///
    /// Logs a warning if decompression fails and data starts with zstd magic bytes,
    /// which indicates potential corruption rather than uncompressed data.
    pub(crate) fn try_decompress(data: Vec<u8>) -> Vec<u8> {
        match zstd::decode_all(&data[..]) {
            Ok(decompressed) => decompressed,
            Err(e) => {
                // Check if data starts with zstd magic bytes (0x28, 0xB5, 0x2F, 0xFD)
                // If so, this is likely corruption rather than uncompressed data
                if data.len() >= 4 && data[0..4] == [0x28, 0xB5, 0x2F, 0xFD] {
                    warn!(
                        error = %e,
                        data_len = data.len(),
                        "Failed to decompress data with zstd magic bytes - possible corruption"
                    );
                }
                data
            }
        }
    }

    /// Compress data if it exceeds the configured threshold
    ///
    /// Mimics Django's ZstdCompressor.compress() behavior:
    /// - Only compress if enabled and data size > threshold
    /// - Uses configured compression level (default 0 to match Django)
    /// - Returns error if compression fails
    pub(crate) fn maybe_compress(
        data: Vec<u8>,
        config: &CompressionConfig,
    ) -> Result<Vec<u8>, CustomRedisError> {
        if config.enabled && data.len() > config.threshold {
            zstd::encode_all(&data[..], config.level).map_err(|e| e.into())
        } else {
            Ok(data)
        }
    }

    /// Serialize a string value according to the format and apply compression if configured
    ///
    /// This helper consolidates the common pattern of:
    /// 1. Serializing a string value based on the format (Pickle, Utf8, or error for RawBytes)
    /// 2. Applying compression if enabled and above threshold
    ///
    /// Returns an error if RawBytes format is used (should use set_raw_bytes instead)
    fn serialize_and_compress(
        &self,
        value: String,
        format: RedisValueFormat,
    ) -> Result<Vec<u8>, CustomRedisError> {
        let bytes = match format {
            RedisValueFormat::Pickle => serde_pickle::to_vec(&value, Default::default())?,
            RedisValueFormat::Utf8 => value.into_bytes(),
            RedisValueFormat::RawBytes => {
                return Err(CustomRedisError::ParseError(ERR_RAWBYTES_SET.to_string()))
            }
        };

        Self::maybe_compress(bytes, &self.compression)
    }
}

#[async_trait]
impl Client for RedisClient {
    async fn zrangebyscore(
        &self,
        k: String,
        min: String,
        max: String,
    ) -> Result<Vec<String>, CustomRedisError> {
        let mut conn = self.connection.clone();
        let results = conn.zrangebyscore(k, min, max).await?;
        Ok(results)
    }

    async fn hincrby(
        &self,
        k: String,
        v: String,
        count: Option<i32>,
    ) -> Result<(), CustomRedisError> {
        let mut conn = self.connection.clone();
        let count = count.unwrap_or(1);
        conn.hincr::<_, _, _, ()>(k, v, count).await?;
        Ok(())
    }

    async fn get(&self, k: String) -> Result<String, CustomRedisError> {
        self.get_with_format(k, self.format).await
    }

    async fn get_with_format(
        &self,
        k: String,
        format: RedisValueFormat,
    ) -> Result<String, CustomRedisError> {
        let mut conn = self.connection.clone();
        let raw_bytes: Vec<u8> = conn.get(k).await?;

        // return NotFound error when empty
        if raw_bytes.is_empty() {
            return Err(CustomRedisError::NotFound);
        }

        // Always attempt decompression - handles both compressed and uncompressed data gracefully
        // This ensures clients can read data regardless of compression settings used when writing
        let decompressed = Self::try_decompress(raw_bytes);

        match format {
            RedisValueFormat::Pickle => {
                let string_response: String =
                    serde_pickle::from_slice(&decompressed, Default::default())?;
                Ok(string_response)
            }
            RedisValueFormat::Utf8 => {
                let string_response = String::from_utf8(decompressed)?;
                Ok(string_response)
            }
            RedisValueFormat::RawBytes => {
                Err(CustomRedisError::ParseError(ERR_RAWBYTES_GET.to_string()))
            }
        }
    }

    async fn get_raw_bytes(&self, k: String) -> Result<Vec<u8>, CustomRedisError> {
        let mut conn = self.connection.clone();
        let raw_bytes: Vec<u8> = conn.get(k).await?;

        // return NotFound error when empty
        if raw_bytes.is_empty() {
            return Err(CustomRedisError::NotFound);
        }

        // Always attempt decompression - handles both compressed and uncompressed data gracefully
        // This ensures clients can read data regardless of compression settings used when writing
        Ok(Self::try_decompress(raw_bytes))
    }

    async fn set(&self, k: String, v: String) -> Result<(), CustomRedisError> {
        self.set_with_format(k, v, self.format).await
    }

    async fn set_with_format(
        &self,
        k: String,
        v: String,
        format: RedisValueFormat,
    ) -> Result<(), CustomRedisError> {
        let final_bytes = self.serialize_and_compress(v, format)?;

        let mut conn = self.connection.clone();
        conn.set::<_, _, ()>(k, final_bytes).await?;
        Ok(())
    }

    async fn setex(&self, k: String, v: String, seconds: u64) -> Result<(), CustomRedisError> {
        let final_bytes = self.serialize_and_compress(v, self.format)?;

        let mut conn = self.connection.clone();
        conn.set_ex::<_, _, ()>(k, final_bytes, seconds).await?;
        Ok(())
    }

    async fn set_nx_ex(
        &self,
        k: String,
        v: String,
        seconds: u64,
    ) -> Result<bool, CustomRedisError> {
        self.set_nx_ex_with_format(k, v, seconds, self.format).await
    }

    async fn set_nx_ex_with_format(
        &self,
        k: String,
        v: String,
        seconds: u64,
        format: RedisValueFormat,
    ) -> Result<bool, CustomRedisError> {
        let final_bytes = self.serialize_and_compress(v, format)?;

        let mut conn = self.connection.clone();
        let seconds_usize = seconds as usize;

        // Use SET with both NX and EX options
        let result: Result<Option<String>, RedisError> = redis::cmd("SET")
            .arg(&k)
            .arg(&final_bytes)
            .arg("EX")
            .arg(seconds_usize)
            .arg("NX")
            .query_async(&mut conn)
            .await;

        match result {
            Ok(Some(_)) => Ok(true), // Key was set successfully
            Ok(None) => Ok(false),   // Key already existed
            Err(e) => Err(e.into()),
        }
    }

    async fn batch_incr_by_expire_nx(
        &self,
        items: Vec<(String, i64)>,
        ttl_seconds: usize,
    ) -> Result<(), CustomRedisError> {
        let mut pipe = redis::pipe();
        for (k, by) in items {
            pipe.cmd("INCRBY").arg(&k).arg(by).ignore();
            pipe.cmd("EXPIRE")
                .arg(&k)
                .arg(ttl_seconds)
                .arg("NX")
                .ignore();
        }

        let mut conn = self.connection.clone();
        pipe.query_async::<()>(&mut conn).await?;
        Ok(())
    }

    async fn batch_incr_by_expire(
        &self,
        items: Vec<(String, i64)>,
        ttl_seconds: usize,
    ) -> Result<(), CustomRedisError> {
        let mut pipe = redis::pipe();
        for (k, by) in items {
            pipe.cmd("INCRBY").arg(&k).arg(by).ignore();
            pipe.cmd("EXPIRE").arg(&k).arg(ttl_seconds).ignore();
        }

        let mut conn = self.connection.clone();
        pipe.query_async::<()>(&mut conn).await?;
        Ok(())
    }

    async fn del(&self, k: String) -> Result<(), CustomRedisError> {
        let mut conn = self.connection.clone();
        conn.del::<_, ()>(k).await?;
        Ok(())
    }

    async fn hget(&self, k: String, field: String) -> Result<String, CustomRedisError> {
        let mut conn = self.connection.clone();
        let result: Option<String> = conn.hget(k, field).await?;

        match result {
            Some(value) => Ok(value),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn scard(&self, k: String) -> Result<u64, CustomRedisError> {
        let mut conn = self.connection.clone();
        let result = conn.scard(k).await?;
        Ok(result)
    }

    async fn mget(&self, keys: Vec<String>) -> Result<Vec<Option<Vec<u8>>>, CustomRedisError> {
        if keys.is_empty() {
            return Ok(vec![]);
        }
        let mut conn = self.connection.clone();
        let results: Vec<Option<Vec<u8>>> = conn.mget(&keys).await?;
        Ok(results)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Test helper functions to reduce duplication
    mod helpers {
        use super::*;

        pub(super) fn serialize_value(value: &str, format: RedisValueFormat) -> Vec<u8> {
            match format {
                RedisValueFormat::Pickle => {
                    serde_pickle::to_vec(&value, Default::default()).unwrap()
                }
                RedisValueFormat::Utf8 => value.as_bytes().to_vec(),
                RedisValueFormat::RawBytes => {
                    panic!("RawBytes not supported for string serialization")
                }
            }
        }

        pub(super) fn deserialize_value(bytes: &[u8], format: RedisValueFormat) -> String {
            match format {
                RedisValueFormat::Pickle => {
                    serde_pickle::from_slice(bytes, Default::default()).unwrap()
                }
                RedisValueFormat::Utf8 => String::from_utf8(bytes.to_vec()).unwrap(),
                RedisValueFormat::RawBytes => {
                    panic!("RawBytes not supported for string deserialization")
                }
            }
        }

        pub(super) fn assert_compression_applied(
            original: &[u8],
            processed: &[u8],
            config: &CompressionConfig,
        ) {
            if config.enabled && original.len() > config.threshold {
                assert!(
                    processed.len() < original.len(),
                    "Expected compression for {} bytes (threshold: {})",
                    original.len(),
                    config.threshold
                );
                let decompressed = RedisClient::try_decompress(processed.to_vec());
                assert_eq!(decompressed, original);
            } else {
                assert_eq!(processed, original, "Expected no compression");
            }
        }
    }

    mod redis_client_config {
        use super::*;

        #[test]
        fn test_default_configuration_is_backwards_compatible() {
            // Documents default behavior and prevents accidental changes
            let default_compression = CompressionConfig::disabled();
            assert!(!default_compression.enabled);

            let default_format = RedisValueFormat::default();
            assert_eq!(default_format, RedisValueFormat::Pickle);
        }

        #[test]
        fn test_compression_config_default_is_django_compatible() {
            // CompressionConfig::default() provides Django-compatible settings
            let config = CompressionConfig::default();
            assert!(config.enabled);
            assert_eq!(config.threshold, 512);
            assert_eq!(config.level, 0);
        }

        #[tokio::test]
        async fn test_zero_response_timeout_returns_error() {
            let result = RedisClient::with_config(
                "redis://localhost:6379".to_string(),
                CompressionConfig::disabled(),
                RedisValueFormat::Pickle,
                Some(Duration::ZERO),
                None,
            )
            .await;

            assert!(matches!(
                result,
                Err(CustomRedisError::InvalidConfiguration(_))
            ));
            if let Err(CustomRedisError::InvalidConfiguration(msg)) = result {
                assert!(msg.contains("response timeout"));
            }
        }

        #[tokio::test]
        async fn test_zero_connection_timeout_returns_error() {
            let result = RedisClient::with_config(
                "redis://localhost:6379".to_string(),
                CompressionConfig::disabled(),
                RedisValueFormat::Pickle,
                None,
                Some(Duration::ZERO),
            )
            .await;

            assert!(matches!(
                result,
                Err(CustomRedisError::InvalidConfiguration(_))
            ));
            if let Err(CustomRedisError::InvalidConfiguration(msg)) = result {
                assert!(msg.contains("connection timeout"));
            }
        }
    }

    mod compression_behavior {
        use super::*;

        #[test]
        fn test_try_decompress_uncompressed() {
            let original = b"Hello, World!".to_vec();
            let result = RedisClient::try_decompress(original.clone());
            assert_eq!(result, original);
        }

        #[test]
        fn test_try_decompress_compressed() {
            let original = b"Hello, World!".to_vec();
            let compressed = zstd::encode_all(&original[..], 0).unwrap();
            let result = RedisClient::try_decompress(compressed);
            assert_eq!(result, original);
        }

        #[test]
        fn test_disabled() {
            let data = vec![0u8; 1000];
            let config = CompressionConfig::disabled();
            let result = RedisClient::maybe_compress(data.clone(), &config).unwrap();
            assert_eq!(result, data);
        }

        #[test]
        fn test_below_threshold() {
            let data = vec![0u8; 100];
            let config = CompressionConfig::default();
            let result = RedisClient::maybe_compress(data.clone(), &config).unwrap();
            assert_eq!(result, data);
        }

        #[test]
        fn test_above_threshold() {
            let data = vec![0u8; 1000];
            let config = CompressionConfig::default();
            let result = RedisClient::maybe_compress(data.clone(), &config).unwrap();
            helpers::assert_compression_applied(&data, &result, &config);
        }

        #[test]
        fn test_exactly_at_threshold() {
            let data = vec![0u8; 512];
            let config = CompressionConfig::default();
            let result = RedisClient::maybe_compress(data.clone(), &config).unwrap();
            assert_eq!(result, data); // Should NOT compress (> threshold, not >=)
        }

        #[test]
        fn test_one_byte_over_threshold() {
            let data = vec![0u8; 513];
            let config = CompressionConfig::default();
            let result = RedisClient::maybe_compress(data.clone(), &config).unwrap();
            helpers::assert_compression_applied(&data, &result, &config);
        }

        #[test]
        fn test_roundtrip() {
            let data = vec![42u8; 1000];
            let config = CompressionConfig::default();
            let compressed = RedisClient::maybe_compress(data.clone(), &config).unwrap();
            let decompressed = RedisClient::try_decompress(compressed);
            assert_eq!(decompressed, data);
        }

        #[test]
        fn test_custom_threshold() {
            let data = vec![0u8; 256];
            let config = CompressionConfig::new(true, 128, 0);
            let result = RedisClient::maybe_compress(data.clone(), &config).unwrap();
            helpers::assert_compression_applied(&data, &result, &config);
        }

        #[test]
        fn test_custom_level() {
            let data = vec![42u8; 1000];
            let config_level1 = CompressionConfig::new(true, 512, 1);
            let config_level10 = CompressionConfig::new(true, 512, 10);

            let compressed_level1 =
                RedisClient::maybe_compress(data.clone(), &config_level1).unwrap();
            let compressed_level10 =
                RedisClient::maybe_compress(data.clone(), &config_level10).unwrap();

            assert!(compressed_level10.len() <= compressed_level1.len());

            let decompressed1 = RedisClient::try_decompress(compressed_level1);
            let decompressed10 = RedisClient::try_decompress(compressed_level10);
            assert_eq!(decompressed1, data);
            assert_eq!(decompressed10, data);
        }
    }

    mod serialization_formats {
        use super::*;

        #[test]
        fn test_default_format() {
            let format = RedisValueFormat::default();
            assert_eq!(format, RedisValueFormat::Pickle);
        }

        #[test]
        fn test_pickle_without_compression() {
            let test_value = "test_string";
            let config = CompressionConfig::disabled();

            let serialized = helpers::serialize_value(test_value, RedisValueFormat::Pickle);
            let processed = RedisClient::maybe_compress(serialized.clone(), &config).unwrap();

            helpers::assert_compression_applied(&serialized, &processed, &config);

            let decompressed = RedisClient::try_decompress(processed);
            let deserialized = helpers::deserialize_value(&decompressed, RedisValueFormat::Pickle);
            assert_eq!(deserialized, test_value);
        }

        #[test]
        fn test_pickle_with_compression() {
            let test_value = "x".repeat(600); // Above 512 threshold
            let config = CompressionConfig::default();

            let serialized = helpers::serialize_value(&test_value, RedisValueFormat::Pickle);
            let processed = RedisClient::maybe_compress(serialized.clone(), &config).unwrap();

            helpers::assert_compression_applied(&serialized, &processed, &config);

            let decompressed = RedisClient::try_decompress(processed);
            let deserialized = helpers::deserialize_value(&decompressed, RedisValueFormat::Pickle);
            assert_eq!(deserialized, test_value);
        }

        #[test]
        fn test_utf8_without_compression() {
            let test_value = "test_string";
            let config = CompressionConfig::disabled();

            let serialized = helpers::serialize_value(test_value, RedisValueFormat::Utf8);
            let processed = RedisClient::maybe_compress(serialized.clone(), &config).unwrap();

            helpers::assert_compression_applied(&serialized, &processed, &config);

            let decompressed = RedisClient::try_decompress(processed);
            let deserialized = helpers::deserialize_value(&decompressed, RedisValueFormat::Utf8);
            assert_eq!(deserialized, test_value);
        }

        #[test]
        fn test_utf8_with_compression() {
            let test_value = "x".repeat(600); // Above 512 threshold
            let config = CompressionConfig::default();

            let serialized = helpers::serialize_value(&test_value, RedisValueFormat::Utf8);
            let processed = RedisClient::maybe_compress(serialized.clone(), &config).unwrap();

            helpers::assert_compression_applied(&serialized, &processed, &config);

            let decompressed = RedisClient::try_decompress(processed);
            let deserialized = helpers::deserialize_value(&decompressed, RedisValueFormat::Utf8);
            assert_eq!(deserialized, test_value);
        }

        #[test]
        fn test_pickle_vs_utf8_different_output() {
            let test_value = "test";

            let pickle_bytes = helpers::serialize_value(test_value, RedisValueFormat::Pickle);
            let utf8_bytes = helpers::serialize_value(test_value, RedisValueFormat::Utf8);

            assert_ne!(pickle_bytes, utf8_bytes);

            let pickle_result = helpers::deserialize_value(&pickle_bytes, RedisValueFormat::Pickle);
            let utf8_result = helpers::deserialize_value(&utf8_bytes, RedisValueFormat::Utf8);

            assert_eq!(pickle_result, test_value);
            assert_eq!(utf8_result, test_value);
        }

        #[test]
        fn test_compression_applied_to_both_formats() {
            let large_value = "x".repeat(1000);
            let config = CompressionConfig::default();

            let pickle_serialized =
                helpers::serialize_value(&large_value, RedisValueFormat::Pickle);
            let pickle_compressed =
                RedisClient::maybe_compress(pickle_serialized.clone(), &config).unwrap();
            helpers::assert_compression_applied(&pickle_serialized, &pickle_compressed, &config);

            let utf8_serialized = helpers::serialize_value(&large_value, RedisValueFormat::Utf8);
            let utf8_compressed =
                RedisClient::maybe_compress(utf8_serialized.clone(), &config).unwrap();
            helpers::assert_compression_applied(&utf8_serialized, &utf8_compressed, &config);

            let pickle_decompressed = RedisClient::try_decompress(pickle_compressed);
            let pickle_result =
                helpers::deserialize_value(&pickle_decompressed, RedisValueFormat::Pickle);

            let utf8_decompressed = RedisClient::try_decompress(utf8_compressed);
            let utf8_result =
                helpers::deserialize_value(&utf8_decompressed, RedisValueFormat::Utf8);

            assert_eq!(pickle_result, large_value);
            assert_eq!(utf8_result, large_value);
        }

        #[test]
        fn test_try_decompress_handles_both_compressed_and_uncompressed() {
            let uncompressed = b"hello world".to_vec();
            let result = RedisClient::try_decompress(uncompressed.clone());
            assert_eq!(result, uncompressed);

            let large_data = "x".repeat(1000);
            let compressed = zstd::encode_all(large_data.as_bytes(), 0).unwrap();
            let decompressed = RedisClient::try_decompress(compressed);
            assert_eq!(decompressed, large_data.as_bytes());
        }

        #[test]
        fn test_cross_compression_compatibility() {
            // Data written with compression can be read regardless of reader's compression config
            let test_value = "x".repeat(1000);

            let compressed_config = CompressionConfig::default();
            let serialized = helpers::serialize_value(&test_value, RedisValueFormat::Pickle);
            let compressed = RedisClient::maybe_compress(serialized, &compressed_config).unwrap();

            assert!(compressed.len() < test_value.len());

            let decompressed = RedisClient::try_decompress(compressed);
            let result = helpers::deserialize_value(&decompressed, RedisValueFormat::Pickle);

            assert_eq!(result, test_value);
        }
    }

    mod compression_config {
        use super::*;

        #[test]
        fn test_default() {
            let config = CompressionConfig::default();
            assert!(config.enabled);
            assert_eq!(config.threshold, 512);
            assert_eq!(config.level, 0);
        }

        #[test]
        fn test_disabled() {
            let config = CompressionConfig::disabled();
            assert!(!config.enabled);
            assert_eq!(config.threshold, 0);
            assert_eq!(config.level, 0);
        }

        #[test]
        fn test_new() {
            let config = CompressionConfig::new(true, 1024, 3);
            assert!(config.enabled);
            assert_eq!(config.threshold, 1024);
            assert_eq!(config.level, 3);
        }
    }
}
