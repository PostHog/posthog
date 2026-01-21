use async_trait::async_trait;
use redis::aio::MultiplexedConnection;
use redis::{AsyncCommands, RedisError};
use std::time::Duration;
use tracing::warn;

use crate::pipeline::{PipelineCommand, PipelineResult};
use crate::{Client, CompressionConfig, CustomRedisError, RedisValueFormat};

// Error messages for consistent handling of RawBytes format
const ERR_RAWBYTES_GET: &str = "Use get_raw_bytes() for RawBytes format";
const ERR_RAWBYTES_SET: &str =
    "RawBytes format not supported in set_with_format, use set_raw_bytes instead";

#[derive(Clone)]
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

    async fn set_bytes(
        &self,
        k: String,
        v: Vec<u8>,
        ttl_seconds: Option<u64>,
    ) -> Result<(), CustomRedisError> {
        let mut conn = self.connection.clone();
        match ttl_seconds {
            Some(ttl) => conn.set_ex::<_, _, ()>(k, v, ttl).await?,
            None => conn.set::<_, _, ()>(k, v).await?,
        }
        Ok(())
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

    async fn scard_multiple(&self, keys: Vec<String>) -> Result<Vec<u64>, CustomRedisError> {
        if keys.is_empty() {
            return Ok(vec![]);
        }
        let mut pipe = redis::pipe();
        for k in &keys {
            pipe.scard(k);
        }
        let mut conn = self.connection.clone();
        let results: Vec<u64> = pipe.query_async(&mut conn).await?;
        Ok(results)
    }

    async fn batch_sadd_expire(
        &self,
        items: Vec<(String, String)>,
        ttl_seconds: usize,
    ) -> Result<(), CustomRedisError> {
        if items.is_empty() {
            return Ok(());
        }
        let mut pipe = redis::pipe();
        for (k, member) in items {
            pipe.sadd(&k, &member).ignore();
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

    async fn batch_set_nx_ex(
        &self,
        items: Vec<(String, String)>,
        ttl_seconds: usize,
    ) -> Result<Vec<bool>, CustomRedisError> {
        if items.is_empty() {
            return Ok(vec![]);
        }
        let mut pipe = redis::pipe();
        for (k, v) in &items {
            pipe.cmd("SET")
                .arg(k)
                .arg(v)
                .arg("NX")
                .arg("EX")
                .arg(ttl_seconds);
        }
        let mut conn = self.connection.clone();
        let results: Vec<Option<String>> = pipe.query_async(&mut conn).await?;
        Ok(results.into_iter().map(|r| r.is_some()).collect())
    }

    async fn batch_del(&self, keys: Vec<String>) -> Result<(), CustomRedisError> {
        if keys.is_empty() {
            return Ok(());
        }
        let mut conn = self.connection.clone();
        redis::cmd("DEL")
            .arg(&keys)
            .query_async::<()>(&mut conn)
            .await?;
        Ok(())
    }

    async fn execute_pipeline(
        &self,
        commands: Vec<PipelineCommand>,
    ) -> Result<Vec<Result<PipelineResult, CustomRedisError>>, CustomRedisError> {
        let mut pipe = redis::pipe();

        // Track commands for result processing
        let mut metas: Vec<PipelineCommand> = Vec::with_capacity(commands.len());

        // Build the pipeline
        for cmd in commands {
            match &cmd {
                PipelineCommand::Get { key, .. } | PipelineCommand::GetRawBytes { key } => {
                    pipe.cmd("GET").arg(key);
                }
                PipelineCommand::Set { key, value, format } => {
                    let bytes = self.serialize_and_compress(value.clone(), *format)?;
                    pipe.cmd("SET").arg(key).arg(&bytes);
                }
                PipelineCommand::SetEx {
                    key,
                    value,
                    seconds,
                    format,
                } => {
                    let bytes = self.serialize_and_compress(value.clone(), *format)?;
                    pipe.cmd("SETEX").arg(key).arg(*seconds).arg(&bytes);
                }
                PipelineCommand::SetNxEx {
                    key,
                    value,
                    seconds,
                    format,
                } => {
                    let bytes = self.serialize_and_compress(value.clone(), *format)?;
                    pipe.cmd("SET")
                        .arg(key)
                        .arg(&bytes)
                        .arg("EX")
                        .arg(*seconds)
                        .arg("NX");
                }
                PipelineCommand::Del { key } => {
                    pipe.cmd("DEL").arg(key);
                }
                PipelineCommand::HGet { key, field } => {
                    pipe.cmd("HGET").arg(key).arg(field);
                }
                PipelineCommand::HIncrBy { key, field, count } => {
                    pipe.cmd("HINCRBY").arg(key).arg(field).arg(*count);
                }
                PipelineCommand::Scard { key } => {
                    pipe.cmd("SCARD").arg(key);
                }
                PipelineCommand::ZRangeByScore { key, min, max } => {
                    pipe.cmd("ZRANGEBYSCORE").arg(key).arg(min).arg(max);
                }
            }
            metas.push(cmd);
        }

        // Execute the pipeline
        let mut conn = self.connection.clone();
        let raw_results: Vec<redis::Value> = pipe.query_async(&mut conn).await?;

        // Process results
        let mut results = Vec::with_capacity(raw_results.len());
        for (i, raw) in raw_results.into_iter().enumerate() {
            let cmd = &metas[i];
            let result = self.process_pipeline_result(raw, cmd);
            results.push(result);
        }

        Ok(results)
    }
}

impl RedisClient {
    /// Process a single pipeline result based on the command type.
    fn process_pipeline_result(
        &self,
        raw: redis::Value,
        command: &PipelineCommand,
    ) -> Result<PipelineResult, CustomRedisError> {
        match command {
            PipelineCommand::Get { format, .. } => {
                let bytes: Vec<u8> = redis::from_redis_value(&raw)?;
                if bytes.is_empty() {
                    return Err(CustomRedisError::NotFound);
                }
                let decompressed = Self::try_decompress(bytes);
                let string = match format {
                    RedisValueFormat::Pickle => {
                        serde_pickle::from_slice(&decompressed, Default::default())?
                    }
                    RedisValueFormat::Utf8 => String::from_utf8(decompressed)?,
                    RedisValueFormat::RawBytes => {
                        return Err(CustomRedisError::ParseError(ERR_RAWBYTES_GET.to_string()))
                    }
                };
                Ok(PipelineResult::String(string))
            }
            PipelineCommand::GetRawBytes { .. } => {
                let bytes: Vec<u8> = redis::from_redis_value(&raw)?;
                if bytes.is_empty() {
                    return Err(CustomRedisError::NotFound);
                }
                let decompressed = Self::try_decompress(bytes);
                Ok(PipelineResult::Bytes(decompressed))
            }
            PipelineCommand::Set { .. }
            | PipelineCommand::SetEx { .. }
            | PipelineCommand::Del { .. }
            | PipelineCommand::HIncrBy { .. } => Ok(PipelineResult::Ok),
            PipelineCommand::SetNxEx { .. } => {
                // SET NX returns OK if set, nil if key existed
                match raw {
                    redis::Value::Okay | redis::Value::SimpleString(_) => {
                        Ok(PipelineResult::Bool(true))
                    }
                    redis::Value::Nil => Ok(PipelineResult::Bool(false)),
                    _ => Ok(PipelineResult::Bool(false)),
                }
            }
            PipelineCommand::HGet { .. } => {
                let result: Option<String> = redis::from_redis_value(&raw)?;
                match result {
                    Some(value) => Ok(PipelineResult::String(value)),
                    None => Err(CustomRedisError::NotFound),
                }
            }
            PipelineCommand::Scard { .. } => {
                let count: u64 = redis::from_redis_value(&raw)?;
                Ok(PipelineResult::Count(count))
            }
            PipelineCommand::ZRangeByScore { .. } => {
                let strings: Vec<String> = redis::from_redis_value(&raw)?;
                Ok(PipelineResult::Strings(strings))
            }
        }
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

/// Integration tests using a real Redis instance via testcontainers.
///
/// These tests verify the actual Redis protocol implementation works correctly,
/// complementing the mock-based unit tests.
///
/// # Requirements
/// - Docker must be running and accessible
/// - The `redis:7-alpine` image will be pulled if not present
///
/// # Running the tests
/// These tests are ignored by default because they require Docker and are slower.
/// Run them explicitly with:
/// ```sh
/// cargo test client::integration_tests -- --ignored --test-threads=1
/// ```
///
/// The `--test-threads=1` flag is recommended to avoid container conflicts.
#[cfg(test)]
mod integration_tests {
    use super::*;
    use crate::{ClientPipelineExt, PipelineResult};
    use testcontainers::core::{IntoContainerPort, WaitFor};
    use testcontainers::runners::AsyncRunner;
    use testcontainers::GenericImage;

    async fn create_test_client() -> (RedisClient, testcontainers::ContainerAsync<GenericImage>) {
        let container = GenericImage::new("redis", "7-alpine")
            .with_exposed_port(6379.tcp())
            .with_wait_for(WaitFor::message_on_stdout("Ready to accept connections"))
            .start()
            .await
            .unwrap();

        let host = container.get_host().await.unwrap();
        let port = container.get_host_port_ipv4(6379).await.unwrap();
        let url = format!("redis://{host}:{port}");

        let client = RedisClient::with_config(
            url,
            CompressionConfig::disabled(),
            RedisValueFormat::Utf8,
            None,
            None,
        )
        .await
        .unwrap();

        (client, container)
    }

    #[tokio::test]
    #[ignore] // Requires Docker; run with: cargo test integration_tests -- --ignored
    async fn test_pipeline_set_and_get() {
        let (client, _container) = create_test_client().await;

        let results = client
            .pipeline()
            .set("key1", "value1")
            .set("key2", "value2")
            .get("key1")
            .get("key2")
            .execute()
            .await
            .unwrap();

        assert_eq!(results.len(), 4);
        assert!(matches!(results[0], Ok(PipelineResult::Ok)));
        assert!(matches!(results[1], Ok(PipelineResult::Ok)));
        assert!(matches!(&results[2], Ok(PipelineResult::String(s)) if s == "value1"));
        assert!(matches!(&results[3], Ok(PipelineResult::String(s)) if s == "value2"));
    }

    #[tokio::test]
    #[ignore] // Requires Docker; run with: cargo test integration_tests -- --ignored
    async fn test_pipeline_get_nonexistent_key() {
        let (client, _container) = create_test_client().await;

        let results = client
            .pipeline()
            .get("nonexistent_key")
            .execute()
            .await
            .unwrap();

        assert_eq!(results.len(), 1);
        assert!(matches!(results[0], Err(CustomRedisError::NotFound)));
    }

    #[tokio::test]
    #[ignore] // Requires Docker; run with: cargo test integration_tests -- --ignored
    async fn test_pipeline_setex_with_ttl() {
        let (client, _container) = create_test_client().await;

        let results = client
            .pipeline()
            .setex("expiring_key", "temp_value", 3600)
            .get("expiring_key")
            .execute()
            .await
            .unwrap();

        assert_eq!(results.len(), 2);
        assert!(matches!(results[0], Ok(PipelineResult::Ok)));
        assert!(matches!(&results[1], Ok(PipelineResult::String(s)) if s == "temp_value"));
    }

    #[tokio::test]
    #[ignore] // Requires Docker; run with: cargo test integration_tests -- --ignored
    async fn test_pipeline_set_nx_ex() {
        let (client, _container) = create_test_client().await;

        // First set should succeed (key doesn't exist)
        let results = client
            .pipeline()
            .set_nx_ex("nx_key", "first_value", 3600)
            .execute()
            .await
            .unwrap();

        assert_eq!(results.len(), 1);
        assert!(matches!(results[0], Ok(PipelineResult::Bool(true))));

        // Second set should fail (key exists)
        let results = client
            .pipeline()
            .set_nx_ex("nx_key", "second_value", 3600)
            .get("nx_key")
            .execute()
            .await
            .unwrap();

        assert_eq!(results.len(), 2);
        assert!(matches!(results[0], Ok(PipelineResult::Bool(false))));
        // Value should still be the first one
        assert!(matches!(&results[1], Ok(PipelineResult::String(s)) if s == "first_value"));
    }

    #[tokio::test]
    #[ignore] // Requires Docker; run with: cargo test integration_tests -- --ignored
    async fn test_pipeline_del() {
        let (client, _container) = create_test_client().await;

        let results = client
            .pipeline()
            .set("to_delete", "value")
            .del("to_delete")
            .get("to_delete")
            .execute()
            .await
            .unwrap();

        assert_eq!(results.len(), 3);
        assert!(matches!(results[0], Ok(PipelineResult::Ok)));
        assert!(matches!(results[1], Ok(PipelineResult::Ok)));
        assert!(matches!(results[2], Err(CustomRedisError::NotFound)));
    }

    #[tokio::test]
    #[ignore] // Requires Docker; run with: cargo test integration_tests -- --ignored
    async fn test_pipeline_empty() {
        let (client, _container) = create_test_client().await;

        let results = client.pipeline().execute().await.unwrap();

        assert!(results.is_empty());
    }

    #[tokio::test]
    #[ignore] // Requires Docker; run with: cargo test integration_tests -- --ignored
    async fn test_pipeline_result_order_preserved() {
        let (client, _container) = create_test_client().await;

        // Set up keys with different values
        client
            .pipeline()
            .set("order_a", "1")
            .set("order_b", "2")
            .set("order_c", "3")
            .execute()
            .await
            .unwrap();

        // Get them back in a different order
        let results = client
            .pipeline()
            .get("order_c")
            .get("order_a")
            .get("order_b")
            .execute()
            .await
            .unwrap();

        assert_eq!(results.len(), 3);
        assert!(matches!(&results[0], Ok(PipelineResult::String(s)) if s == "3"));
        assert!(matches!(&results[1], Ok(PipelineResult::String(s)) if s == "1"));
        assert!(matches!(&results[2], Ok(PipelineResult::String(s)) if s == "2"));
    }

    #[tokio::test]
    #[ignore] // Requires Docker; run with: cargo test integration_tests -- --ignored
    async fn test_pipeline_large_batch() {
        let (client, _container) = create_test_client().await;

        // Build a pipeline with 100 operations
        let mut pipeline = client.pipeline();
        for i in 0..100 {
            pipeline = pipeline.set(format!("batch_key_{i}"), format!("value_{i}"));
        }
        let results = pipeline.execute().await.unwrap();
        assert_eq!(results.len(), 100);
        assert!(results.iter().all(|r| matches!(r, Ok(PipelineResult::Ok))));

        // Verify all keys were set correctly
        let mut pipeline = client.pipeline();
        for i in 0..100 {
            pipeline = pipeline.get(format!("batch_key_{i}"));
        }
        let results = pipeline.execute().await.unwrap();
        assert_eq!(results.len(), 100);

        for (i, result) in results.iter().enumerate() {
            let expected = format!("value_{i}");
            assert!(
                matches!(result, Ok(PipelineResult::String(s)) if s == &expected),
                "Mismatch at index {i}: expected {expected:?}, got {result:?}"
            );
        }
    }

    /// Helper to create a test client with compression enabled.
    /// Uses a low threshold (100 bytes) to ensure compression triggers for test values.
    async fn create_test_client_with_compression(
    ) -> (RedisClient, testcontainers::ContainerAsync<GenericImage>) {
        let container = GenericImage::new("redis", "7-alpine")
            .with_exposed_port(6379.tcp())
            .with_wait_for(WaitFor::message_on_stdout("Ready to accept connections"))
            .start()
            .await
            .unwrap();

        let host = container.get_host().await.unwrap();
        let port = container.get_host_port_ipv4(6379).await.unwrap();
        let url = format!("redis://{host}:{port}");

        let client = RedisClient::with_config(
            url,
            CompressionConfig::new(true, 100, 0), // threshold: 100 bytes, level: default
            RedisValueFormat::Utf8,
            None,
            None,
        )
        .await
        .unwrap();

        (client, container)
    }

    #[tokio::test]
    #[ignore] // Requires Docker; run with: cargo test integration_tests -- --ignored
    async fn test_pipeline_with_compression_enabled() {
        let (client, _container) = create_test_client_with_compression().await;

        // Create values that exceed the compression threshold (100 bytes)
        let large_value = "x".repeat(500); // 500 bytes > 100 byte threshold

        let results = client
            .pipeline()
            .set("compressed_key1", large_value.clone())
            .set("compressed_key2", large_value.clone())
            .get("compressed_key1")
            .get("compressed_key2")
            .execute()
            .await
            .unwrap();

        assert_eq!(results.len(), 4);
        assert!(matches!(results[0], Ok(PipelineResult::Ok)));
        assert!(matches!(results[1], Ok(PipelineResult::Ok)));
        assert!(
            matches!(&results[2], Ok(PipelineResult::String(s)) if s == &large_value),
            "Expected large_value, got {:?}",
            results[2]
        );
        assert!(
            matches!(&results[3], Ok(PipelineResult::String(s)) if s == &large_value),
            "Expected large_value, got {:?}",
            results[3]
        );
    }

    #[tokio::test]
    #[ignore] // Requires Docker; run with: cargo test integration_tests -- --ignored
    async fn test_pipeline_compression_mixed_sizes() {
        let (client, _container) = create_test_client_with_compression().await;

        // Mix of small (no compression) and large (compressed) values
        let small_value = "tiny"; // 4 bytes < 100 byte threshold
        let large_value = "y".repeat(200); // 200 bytes > 100 byte threshold

        let results = client
            .pipeline()
            .set("small_key", small_value)
            .set("large_key", large_value.clone())
            .get("small_key")
            .get("large_key")
            .execute()
            .await
            .unwrap();

        assert_eq!(results.len(), 4);
        assert!(matches!(results[0], Ok(PipelineResult::Ok)));
        assert!(matches!(results[1], Ok(PipelineResult::Ok)));
        assert!(
            matches!(&results[2], Ok(PipelineResult::String(s)) if s == small_value),
            "Expected small_value, got {:?}",
            results[2]
        );
        assert!(
            matches!(&results[3], Ok(PipelineResult::String(s)) if s == &large_value),
            "Expected large_value, got {:?}",
            results[3]
        );
    }
}
