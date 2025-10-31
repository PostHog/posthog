use async_trait::async_trait;
use redis::aio::MultiplexedConnection;
use redis::{AsyncCommands, RedisError};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use thiserror::Error;
use tokio::time::timeout;

const DEFAULT_REDIS_TIMEOUT_MILLISECS: u64 = 100;

fn get_redis_timeout_ms() -> u64 {
    std::env::var("REDIS_TIMEOUT_MS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(DEFAULT_REDIS_TIMEOUT_MILLISECS)
}

#[derive(Error, Debug, Clone, PartialEq, Eq)]
pub enum CustomRedisError {
    #[error("Not found in redis")]
    NotFound,
    #[error("Parse error: {0}")]
    ParseError(String),
    #[error("Redis error: {0}")]
    Other(String),
    #[error("Timeout error")]
    Timeout,
}

impl From<serde_pickle::Error> for CustomRedisError {
    fn from(err: serde_pickle::Error) -> Self {
        CustomRedisError::ParseError(err.to_string())
    }
}

impl From<RedisError> for CustomRedisError {
    fn from(err: RedisError) -> Self {
        CustomRedisError::Other(err.to_string())
    }
}

impl From<tokio::time::error::Elapsed> for CustomRedisError {
    fn from(_: tokio::time::error::Elapsed) -> Self {
        CustomRedisError::Timeout
    }
}

impl From<std::string::FromUtf8Error> for CustomRedisError {
    fn from(err: std::string::FromUtf8Error) -> Self {
        CustomRedisError::ParseError(err.to_string())
    }
}

impl From<std::io::Error> for CustomRedisError {
    fn from(err: std::io::Error) -> Self {
        CustomRedisError::ParseError(format!("Compression error: {err}"))
    }
}

/// Configuration for zstd compression behavior
///
/// Mimics Django's ZstdCompressor configuration:
/// - Compresses values larger than threshold (default 512 bytes)
/// - Uses zstd compression level 0 (default preset, equivalent to level 3)
/// - Gracefully handles both compressed and uncompressed data on read
#[derive(Debug, Clone)]
pub struct CompressionConfig {
    /// Whether compression is enabled
    pub enabled: bool,
    /// Minimum size in bytes before compression is applied
    /// Django default: 512 bytes (ZstdCompressor.min_length)
    pub threshold: usize,
    /// Zstd compression level (1-22, or 0 for default)
    /// - Level 0: Use default preset (typically level 3) - Django default
    /// - Level 1-3: Fast compression, lower ratio
    /// - Level 4-9: Balanced compression
    /// - Level 10-15: High compression, slower
    /// - Level 16-22: Maximum compression, very slow
    pub level: i32,
}

impl Default for CompressionConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            threshold: 512, // Match Django's ZstdCompressor.min_length
            level: 0,       // Match Django's zstd_preset (default)
        }
    }
}

impl CompressionConfig {
    /// Create a new compression configuration
    pub fn new(enabled: bool, threshold: usize, level: i32) -> Self {
        Self {
            enabled,
            threshold,
            level,
        }
    }

    /// Create a configuration with compression disabled
    pub fn disabled() -> Self {
        Self {
            enabled: false,
            threshold: 0,
            level: 0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RedisValueFormat {
    Pickle,
    Utf8,
    RawBytes,
}

impl Default for RedisValueFormat {
    fn default() -> Self {
        Self::Pickle
    }
}

#[async_trait]
pub trait Client {
    async fn zrangebyscore(
        &self,
        k: String,
        min: String,
        max: String,
    ) -> Result<Vec<String>, CustomRedisError>;

    async fn hincrby(
        &self,
        k: String,
        v: String,
        count: Option<i32>,
    ) -> Result<(), CustomRedisError>;

    async fn get(&self, k: String) -> Result<String, CustomRedisError>;
    async fn get_with_format(
        &self,
        k: String,
        format: RedisValueFormat,
    ) -> Result<String, CustomRedisError>;
    async fn get_raw_bytes(&self, k: String) -> Result<Vec<u8>, CustomRedisError>;
    async fn set(&self, k: String, v: String) -> Result<(), CustomRedisError>;
    async fn set_with_format(
        &self,
        k: String,
        v: String,
        format: RedisValueFormat,
    ) -> Result<(), CustomRedisError>;
    async fn setex(&self, k: String, v: String, seconds: u64) -> Result<(), CustomRedisError>;
    async fn set_nx_ex(&self, k: String, v: String, seconds: u64)
        -> Result<bool, CustomRedisError>;
    async fn set_nx_ex_with_format(
        &self,
        k: String,
        v: String,
        seconds: u64,
        format: RedisValueFormat,
    ) -> Result<bool, CustomRedisError>;
    async fn del(&self, k: String) -> Result<(), CustomRedisError>;
    async fn hget(&self, k: String, field: String) -> Result<String, CustomRedisError>;
    async fn scard(&self, k: String) -> Result<u64, CustomRedisError>;
}

pub struct RedisClient {
    connection: MultiplexedConnection,
    compression: CompressionConfig,
}

impl RedisClient {
    /// Create a new RedisClient with default compression settings
    ///
    /// Default compression matches Django behavior:
    /// - Enabled by default
    /// - Threshold: 512 bytes
    /// - Level: 0 (default preset)
    pub async fn new(addr: String) -> Result<RedisClient, CustomRedisError> {
        Self::with_compression(addr, CompressionConfig::default()).await
    }

    /// Create a new RedisClient with custom compression configuration
    ///
    /// # Arguments
    /// * `addr` - Redis connection string
    /// * `compression` - Compression configuration (see CompressionConfig)
    pub async fn with_compression(
        addr: String,
        compression: CompressionConfig,
    ) -> Result<RedisClient, CustomRedisError> {
        let client = redis::Client::open(addr)?;
        let connection = client.get_multiplexed_async_connection().await?;
        Ok(RedisClient {
            connection,
            compression,
        })
    }

    /// Attempt to decompress data, falling back to original if not compressed
    ///
    /// Mimics Django's ZstdCompressor.decompress() behavior:
    /// - Try to decompress with zstd
    /// - If decompression fails, return original data unchanged
    /// - This allows graceful handling of both compressed and uncompressed data
    fn try_decompress(data: Vec<u8>) -> Vec<u8> {
        zstd::decode_all(&data[..]).unwrap_or(data)
    }

    /// Compress data if it exceeds the configured threshold
    ///
    /// Mimics Django's ZstdCompressor.compress() behavior:
    /// - Only compress if enabled and data size > threshold
    /// - Uses configured compression level (default 0 to match Django)
    /// - Returns error if compression fails
    fn maybe_compress(
        data: Vec<u8>,
        config: &CompressionConfig,
    ) -> Result<Vec<u8>, CustomRedisError> {
        if config.enabled && data.len() > config.threshold {
            zstd::encode_all(&data[..], config.level).map_err(|e| e.into())
        } else {
            Ok(data)
        }
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
        let results = conn.zrangebyscore(k, min, max);
        let fut = timeout(Duration::from_millis(get_redis_timeout_ms()), results).await?;
        Ok(fut?)
    }

    async fn hincrby(
        &self,
        k: String,
        v: String,
        count: Option<i32>,
    ) -> Result<(), CustomRedisError> {
        let mut conn = self.connection.clone();
        let count = count.unwrap_or(1);
        let results = conn.hincr(k, v, count);
        let fut = timeout(Duration::from_millis(get_redis_timeout_ms()), results).await?;
        fut.map_err(|e| CustomRedisError::Other(e.to_string()))
    }

    async fn get(&self, k: String) -> Result<String, CustomRedisError> {
        self.get_with_format(k, RedisValueFormat::Pickle).await
    }

    async fn get_with_format(
        &self,
        k: String,
        format: RedisValueFormat,
    ) -> Result<String, CustomRedisError> {
        let mut conn = self.connection.clone();
        let results = conn.get(k);
        let fut: Result<Vec<u8>, RedisError> =
            timeout(Duration::from_millis(get_redis_timeout_ms()), results).await?;

        // return NotFound error when empty
        if matches!(&fut, Ok(v) if v.is_empty()) {
            return Err(CustomRedisError::NotFound);
        }

        let raw_bytes = fut?;

        // Decompress if compression is enabled (graceful fallback if not compressed)
        let decompressed = if self.compression.enabled {
            Self::try_decompress(raw_bytes)
        } else {
            raw_bytes
        };

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
            RedisValueFormat::RawBytes => Err(CustomRedisError::ParseError(
                "Use get_raw_bytes() for RawBytes format".to_string(),
            )),
        }
    }

    async fn get_raw_bytes(&self, k: String) -> Result<Vec<u8>, CustomRedisError> {
        let mut conn = self.connection.clone();
        let results = conn.get(k);
        let fut: Result<Vec<u8>, RedisError> =
            timeout(Duration::from_millis(get_redis_timeout_ms()), results).await?;

        // return NotFound error when empty
        if matches!(&fut, Ok(v) if v.is_empty()) {
            return Err(CustomRedisError::NotFound);
        }

        Ok(fut?)
    }

    async fn set(&self, k: String, v: String) -> Result<(), CustomRedisError> {
        self.set_with_format(k, v, RedisValueFormat::Pickle).await
    }

    async fn set_with_format(
        &self,
        k: String,
        v: String,
        format: RedisValueFormat,
    ) -> Result<(), CustomRedisError> {
        let bytes = match format {
            RedisValueFormat::Pickle => serde_pickle::to_vec(&v, Default::default())?,
            RedisValueFormat::Utf8 => v.into_bytes(),
            RedisValueFormat::RawBytes => {
                return Err(CustomRedisError::ParseError(
                    "RawBytes format not supported for setting strings".to_string(),
                ))
            }
        };

        // Compress if enabled and above threshold
        let final_bytes = Self::maybe_compress(bytes, &self.compression)?;

        let mut conn = self.connection.clone();
        let results = conn.set(k, final_bytes);
        let fut = timeout(Duration::from_millis(get_redis_timeout_ms()), results).await?;
        Ok(fut?)
    }

    async fn setex(&self, k: String, v: String, seconds: u64) -> Result<(), CustomRedisError> {
        let bytes = serde_pickle::to_vec(&v, Default::default())?;
        let mut conn = self.connection.clone();
        let results = conn.set_ex(k, bytes, seconds);
        let fut = timeout(Duration::from_millis(get_redis_timeout_ms()), results).await?;
        Ok(fut?)
    }

    async fn set_nx_ex(
        &self,
        k: String,
        v: String,
        seconds: u64,
    ) -> Result<bool, CustomRedisError> {
        self.set_nx_ex_with_format(k, v, seconds, RedisValueFormat::Pickle)
            .await
    }

    async fn set_nx_ex_with_format(
        &self,
        k: String,
        v: String,
        seconds: u64,
        format: RedisValueFormat,
    ) -> Result<bool, CustomRedisError> {
        let bytes = match format {
            RedisValueFormat::Pickle => serde_pickle::to_vec(&v, Default::default())?,
            RedisValueFormat::Utf8 => v.into_bytes(),
            RedisValueFormat::RawBytes => {
                return Err(CustomRedisError::ParseError(
                    "RawBytes format not supported for setting strings".to_string(),
                ))
            }
        };

        // Compress if enabled and above threshold
        let final_bytes = Self::maybe_compress(bytes, &self.compression)?;

        let mut conn = self.connection.clone();
        let seconds_usize = seconds as usize;

        // Use SET with both NX and EX options
        let result: Result<Option<String>, RedisError> = timeout(
            Duration::from_millis(get_redis_timeout_ms()),
            redis::cmd("SET")
                .arg(&k)
                .arg(&final_bytes)
                .arg("EX")
                .arg(seconds_usize)
                .arg("NX")
                .query_async(&mut conn),
        )
        .await?;

        match result {
            Ok(Some(_)) => Ok(true), // Key was set successfully
            Ok(None) => Ok(false),   // Key already existed
            Err(e) => Err(CustomRedisError::Other(e.to_string())),
        }
    }

    async fn del(&self, k: String) -> Result<(), CustomRedisError> {
        let mut conn = self.connection.clone();
        let results = conn.del(k);
        let fut = timeout(Duration::from_millis(get_redis_timeout_ms()), results).await?;
        fut.map_err(|e| CustomRedisError::Other(e.to_string()))
    }

    async fn hget(&self, k: String, field: String) -> Result<String, CustomRedisError> {
        let mut conn = self.connection.clone();
        let results = conn.hget(k, field);
        let fut: Result<Option<String>, RedisError> =
            timeout(Duration::from_millis(get_redis_timeout_ms()), results).await?;

        match fut? {
            Some(value) => Ok(value),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn scard(&self, k: String) -> Result<u64, CustomRedisError> {
        let mut conn = self.connection.clone();
        let results = conn.scard(k);
        timeout(Duration::from_millis(get_redis_timeout_ms()), results)
            .await?
            .map_err(|e| CustomRedisError::Other(e.to_string()))
    }
}

#[derive(Clone)]
pub struct MockRedisClient {
    zrangebyscore_ret: HashMap<String, Vec<String>>,
    hincrby_ret: HashMap<String, Result<(), CustomRedisError>>,
    get_ret: HashMap<String, Result<String, CustomRedisError>>,
    get_raw_bytes_ret: HashMap<String, Result<Vec<u8>, CustomRedisError>>,
    set_ret: HashMap<String, Result<(), CustomRedisError>>,
    set_nx_ex_ret: HashMap<String, Result<bool, CustomRedisError>>,
    del_ret: HashMap<String, Result<(), CustomRedisError>>,
    hget_ret: HashMap<String, Result<String, CustomRedisError>>,
    scard_ret: HashMap<String, Result<u64, CustomRedisError>>,
    calls: Arc<Mutex<Vec<MockRedisCall>>>,
    #[allow(dead_code)]
    compression: CompressionConfig,
}

impl Default for MockRedisClient {
    fn default() -> Self {
        Self {
            zrangebyscore_ret: HashMap::new(),
            hincrby_ret: HashMap::new(),
            get_ret: HashMap::new(),
            get_raw_bytes_ret: HashMap::new(),
            set_ret: HashMap::new(),
            set_nx_ex_ret: HashMap::new(),
            del_ret: HashMap::new(),
            hget_ret: HashMap::new(),
            scard_ret: HashMap::new(),
            calls: Arc::new(Mutex::new(Vec::new())),
            compression: CompressionConfig::default(),
        }
    }
}

impl MockRedisClient {
    pub fn new() -> Self {
        Self::default()
    }

    // Helper method to safely lock the calls mutex
    fn lock_calls(&self) -> std::sync::MutexGuard<Vec<MockRedisCall>> {
        match self.calls.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        }
    }

    pub fn zrangebyscore_ret(&mut self, key: &str, ret: Vec<String>) -> Self {
        self.zrangebyscore_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn hincrby_ret(&mut self, key: &str, ret: Result<(), CustomRedisError>) -> Self {
        self.hincrby_ret.insert(key.to_owned(), ret);

        self.clone()
    }

    pub fn get_ret(&mut self, key: &str, ret: Result<String, CustomRedisError>) -> Self {
        self.get_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn get_raw_bytes_ret(&mut self, key: &str, ret: Result<Vec<u8>, CustomRedisError>) -> Self {
        self.get_raw_bytes_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn set_ret(&mut self, key: &str, ret: Result<(), CustomRedisError>) -> Self {
        self.set_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn del_ret(&mut self, key: &str, ret: Result<(), CustomRedisError>) -> Self {
        self.del_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn hget_ret(&mut self, key: &str, ret: Result<String, CustomRedisError>) -> Self {
        self.hget_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn scard_ret(&mut self, key: &str, ret: Result<u64, CustomRedisError>) -> Self {
        self.scard_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn get_calls(&self) -> Vec<MockRedisCall> {
        self.lock_calls().clone()
    }

    pub fn set_nx_ex_ret(&mut self, key: &str, ret: Result<bool, CustomRedisError>) -> Self {
        self.set_nx_ex_ret.insert(key.to_owned(), ret);
        self.clone()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MockRedisValue {
    None,
    Error(CustomRedisError),
    String(String),
    StringWithTTL(String, u64),
    VecString(Vec<String>),
    I32(i32),
    I64(i64),
    MinMax(String, String),
    StringWithFormat(String, RedisValueFormat),
    StringWithTTLAndFormat(String, u64, RedisValueFormat),
}

#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct MockRedisCall {
    pub op: String,
    pub key: String,
    pub value: MockRedisValue,
}

#[async_trait]
impl Client for MockRedisClient {
    async fn zrangebyscore(
        &self,
        key: String,
        min: String,
        max: String,
    ) -> Result<Vec<String>, CustomRedisError> {
        // Record the call
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "zrangebyscore".to_string(),
            key: key.clone(),
            value: MockRedisValue::MinMax(min, max),
        });

        match self.zrangebyscore_ret.get(&key) {
            Some(val) => Ok(val.clone()),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn hincrby(
        &self,
        key: String,
        field: String,
        count: Option<i32>,
    ) -> Result<(), CustomRedisError> {
        // Record the call
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "hincrby".to_string(),
            key: format!("{key}:{field}"),
            value: match count {
                None => MockRedisValue::None,
                Some(v) => MockRedisValue::I32(v),
            },
        });

        match self.hincrby_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn get(&self, key: String) -> Result<String, CustomRedisError> {
        // Record the call
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "get".to_string(),
            key: key.clone(),
            value: MockRedisValue::None,
        });

        match self.get_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn get_with_format(
        &self,
        key: String,
        format: RedisValueFormat,
    ) -> Result<String, CustomRedisError> {
        self.lock_calls().push(MockRedisCall {
            op: "get_with_format".to_string(),
            key: key.clone(),
            value: MockRedisValue::StringWithFormat("".to_string(), format),
        });

        self.get_ret
            .get(&key)
            .cloned()
            .unwrap_or(Err(CustomRedisError::NotFound))
    }

    async fn get_raw_bytes(&self, key: String) -> Result<Vec<u8>, CustomRedisError> {
        self.lock_calls().push(MockRedisCall {
            op: "get_raw_bytes".to_string(),
            key: key.clone(),
            value: MockRedisValue::String("".to_string()),
        });

        // First try the dedicated raw bytes storage
        if let Some(result) = self.get_raw_bytes_ret.get(&key) {
            return result.clone();
        }

        // Fall back to string conversion for backward compatibility
        match self
            .get_ret
            .get(&key)
            .cloned()
            .unwrap_or(Err(CustomRedisError::NotFound))
        {
            Ok(string_data) => Ok(string_data.into_bytes()),
            Err(e) => Err(e),
        }
    }

    async fn set(&self, key: String, value: String) -> Result<(), CustomRedisError> {
        // Record the call
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "set".to_string(),
            key: key.clone(),
            value: MockRedisValue::String(value.clone()),
        });

        match self.set_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn set_with_format(
        &self,
        key: String,
        value: String,
        format: RedisValueFormat,
    ) -> Result<(), CustomRedisError> {
        self.lock_calls().push(MockRedisCall {
            op: "set_with_format".to_string(),
            key: key.clone(),
            value: MockRedisValue::StringWithFormat(value.clone(), format),
        });

        self.set_ret.get(&key).cloned().unwrap_or(Ok(()))
    }

    async fn setex(
        &self,
        key: String,
        value: String,
        seconds: u64,
    ) -> Result<(), CustomRedisError> {
        self.lock_calls().push(MockRedisCall {
            op: "setex".to_string(),
            key: key.clone(),
            value: MockRedisValue::StringWithTTL(value.clone(), seconds),
        });

        self.set_ret.get(&key).cloned().unwrap_or(Ok(()))
    }

    async fn set_nx_ex(
        &self,
        key: String,
        value: String,
        seconds: u64,
    ) -> Result<bool, CustomRedisError> {
        // Record the call
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "set_nx_ex".to_string(),
            key: key.clone(),
            value: MockRedisValue::StringWithTTL(value.clone(), seconds),
        });

        match self.set_nx_ex_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn set_nx_ex_with_format(
        &self,
        key: String,
        value: String,
        seconds: u64,
        format: RedisValueFormat,
    ) -> Result<bool, CustomRedisError> {
        self.lock_calls().push(MockRedisCall {
            op: "set_nx_ex_with_format".to_string(),
            key: key.clone(),
            value: MockRedisValue::StringWithTTLAndFormat(value.clone(), seconds, format),
        });

        self.set_nx_ex_ret
            .get(&key)
            .cloned()
            .unwrap_or(Err(CustomRedisError::NotFound))
    }

    async fn del(&self, key: String) -> Result<(), CustomRedisError> {
        // Record the call
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "del".to_string(),
            key: key.clone(),
            value: MockRedisValue::None,
        });

        match self.del_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn hget(&self, key: String, field: String) -> Result<String, CustomRedisError> {
        // Record the call
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "hget".to_string(),
            key: format!("{key}:{field}"),
            value: MockRedisValue::None,
        });

        match self.hget_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn scard(&self, key: String) -> Result<u64, CustomRedisError> {
        // Record the call
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "scard".to_string(),
            key: key.to_string(),
            value: MockRedisValue::None,
        });

        match self.scard_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compression_config_default() {
        let config = CompressionConfig::default();
        assert!(config.enabled);
        assert_eq!(config.threshold, 512);
        assert_eq!(config.level, 0);
    }

    #[test]
    fn test_compression_config_disabled() {
        let config = CompressionConfig::disabled();
        assert!(!config.enabled);
        assert_eq!(config.threshold, 0);
        assert_eq!(config.level, 0);
    }

    #[test]
    fn test_compression_config_new() {
        let config = CompressionConfig::new(true, 1024, 3);
        assert!(config.enabled);
        assert_eq!(config.threshold, 1024);
        assert_eq!(config.level, 3);
    }

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
    fn test_maybe_compress_disabled() {
        let data = vec![0u8; 1000];
        let config = CompressionConfig::disabled();

        let result = RedisClient::maybe_compress(data.clone(), &config).unwrap();
        assert_eq!(result, data);
    }

    #[test]
    fn test_maybe_compress_below_threshold() {
        let data = vec![0u8; 100];
        let config = CompressionConfig::default();

        let result = RedisClient::maybe_compress(data.clone(), &config).unwrap();
        assert_eq!(result, data);
    }

    #[test]
    fn test_maybe_compress_above_threshold() {
        let data = vec![0u8; 1000];
        let config = CompressionConfig::default();

        let result = RedisClient::maybe_compress(data.clone(), &config).unwrap();
        assert_ne!(result, data);
        assert!(result.len() < data.len());

        let decompressed = zstd::decode_all(&result[..]).unwrap();
        assert_eq!(decompressed, data);
    }

    #[test]
    fn test_maybe_compress_exactly_at_threshold() {
        let data = vec![0u8; 512];
        let config = CompressionConfig::default();

        let result = RedisClient::maybe_compress(data.clone(), &config).unwrap();
        assert_eq!(result, data);
    }

    #[test]
    fn test_maybe_compress_one_byte_over_threshold() {
        let data = vec![0u8; 513];
        let config = CompressionConfig::default();

        let result = RedisClient::maybe_compress(data.clone(), &config).unwrap();
        assert_ne!(result, data);

        let decompressed = zstd::decode_all(&result[..]).unwrap();
        assert_eq!(decompressed, data);
    }

    #[test]
    fn test_compression_roundtrip() {
        let data = vec![42u8; 1000];
        let config = CompressionConfig::default();

        let compressed = RedisClient::maybe_compress(data.clone(), &config).unwrap();
        assert!(compressed.len() < data.len());

        let decompressed = RedisClient::try_decompress(compressed);
        assert_eq!(decompressed, data);
    }

    #[test]
    fn test_compression_with_custom_threshold() {
        let data = vec![0u8; 256];
        let config = CompressionConfig::new(true, 128, 0);

        let result = RedisClient::maybe_compress(data.clone(), &config).unwrap();
        assert_ne!(result, data);

        let decompressed = RedisClient::try_decompress(result);
        assert_eq!(decompressed, data);
    }

    #[test]
    fn test_compression_with_custom_level() {
        let data = vec![42u8; 1000];

        let config_level1 = CompressionConfig::new(true, 512, 1);
        let config_level10 = CompressionConfig::new(true, 512, 10);

        let compressed_level1 = RedisClient::maybe_compress(data.clone(), &config_level1).unwrap();
        let compressed_level10 =
            RedisClient::maybe_compress(data.clone(), &config_level10).unwrap();

        assert!(compressed_level10.len() <= compressed_level1.len());

        let decompressed1 = RedisClient::try_decompress(compressed_level1);
        let decompressed10 = RedisClient::try_decompress(compressed_level10);
        assert_eq!(decompressed1, data);
        assert_eq!(decompressed10, data);
    }

    #[test]
    fn test_mock_redis_client_default_has_compression() {
        let client = MockRedisClient::default();
        assert!(client.compression.enabled);
        assert_eq!(client.compression.threshold, 512);
        assert_eq!(client.compression.level, 0);
    }
}
