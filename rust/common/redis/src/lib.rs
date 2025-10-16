use async_trait::async_trait;
use redis::aio::MultiplexedConnection;
use redis::{AsyncCommands, RedisError};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use thiserror::Error;
use tokio::time::timeout;
use tracing::warn;

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

// Error messages for consistent handling of RawBytes format
const ERR_RAWBYTES_GET: &str = "Use get_raw_bytes() for RawBytes format";
const ERR_RAWBYTES_SET: &str =
    "RawBytes format not supported in set_with_format, use set_raw_bytes instead";

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
    async fn lpush(&self, k: String, v: String) -> Result<(), CustomRedisError>;
    async fn rpop(&self, k: String) -> Result<Option<String>, CustomRedisError>;
    async fn llen(&self, k: String) -> Result<u64, CustomRedisError>;
}

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
    ///
    /// For Django-compatible compression, use `with_config()` with `CompressionConfig::default()`
    pub async fn new(addr: String) -> Result<RedisClient, CustomRedisError> {
        Self::with_config(
            addr,
            CompressionConfig::disabled(),
            RedisValueFormat::default(),
        )
        .await
    }

    /// Create a new RedisClient with full configuration control
    ///
    /// # Arguments
    /// * `addr` - Redis connection string
    /// * `compression` - Compression configuration (see CompressionConfig)
    /// * `format` - Serialization format for values (see RedisValueFormat)
    ///
    /// # Examples
    /// ```no_run
    /// use common_redis::{RedisClient, CompressionConfig, RedisValueFormat};
    ///
    /// # async fn example() {
    /// // Default settings
    /// let client = RedisClient::new("redis://localhost:6379".to_string()).await.unwrap();
    ///
    /// // Custom compression only
    /// let client = RedisClient::with_config(
    ///     "redis://localhost:6379".to_string(),
    ///     CompressionConfig::new(true, 1024, 3),
    ///     RedisValueFormat::default(),
    /// ).await.unwrap();
    ///
    /// // Custom format only
    /// let client = RedisClient::with_config(
    ///     "redis://localhost:6379".to_string(),
    ///     CompressionConfig::default(),
    ///     RedisValueFormat::Utf8,
    /// ).await.unwrap();
    ///
    /// // Full custom configuration
    /// let client = RedisClient::with_config(
    ///     "redis://localhost:6379".to_string(),
    ///     CompressionConfig::new(true, 1024, 3),
    ///     RedisValueFormat::Utf8,
    /// ).await.unwrap();
    /// # }
    /// ```
    pub async fn with_config(
        addr: String,
        compression: CompressionConfig,
        format: RedisValueFormat,
    ) -> Result<RedisClient, CustomRedisError> {
        let client = redis::Client::open(addr)?;
        let connection = client.get_multiplexed_async_connection().await?;
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
    fn try_decompress(data: Vec<u8>) -> Vec<u8> {
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
        self.get_with_format(k, self.format).await
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
        let results = conn.get(k);
        let fut: Result<Vec<u8>, RedisError> =
            timeout(Duration::from_millis(get_redis_timeout_ms()), results).await?;

        // return NotFound error when empty
        if matches!(&fut, Ok(v) if v.is_empty()) {
            return Err(CustomRedisError::NotFound);
        }

        let raw_bytes = fut?;

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
        let results = conn.set(k, final_bytes);
        let fut = timeout(Duration::from_millis(get_redis_timeout_ms()), results).await?;
        Ok(fut?)
    }

    async fn setex(&self, k: String, v: String, seconds: u64) -> Result<(), CustomRedisError> {
        let final_bytes = self.serialize_and_compress(v, self.format)?;

        let mut conn = self.connection.clone();
        let results = conn.set_ex(k, final_bytes, seconds);
        let fut = timeout(Duration::from_millis(get_redis_timeout_ms()), results).await?;
        Ok(fut?)
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

    async fn lpush(&self, k: String, v: String) -> Result<(), CustomRedisError> {
        let mut conn = self.connection.clone();
        let results = conn.lpush(k, v);
        let fut = timeout(Duration::from_millis(get_redis_timeout_ms()), results).await?;
        fut.map_err(|e| CustomRedisError::Other(e.to_string()))
    }

    async fn rpop(&self, k: String) -> Result<Option<String>, CustomRedisError> {
        let mut conn = self.connection.clone();
        let results = conn.rpop(k, None);
        let fut = timeout(Duration::from_millis(get_redis_timeout_ms()), results).await?;
        Ok(fut?)
    }

    async fn llen(&self, k: String) -> Result<u64, CustomRedisError> {
        let mut conn = self.connection.clone();
        let results = conn.llen(k);
        let fut = timeout(Duration::from_millis(get_redis_timeout_ms()), results).await?;
        Ok(fut?)
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
    lpush_ret: HashMap<String, Result<(), CustomRedisError>>,
    rpop_ret: HashMap<String, Result<Option<String>, CustomRedisError>>,
    llen_ret: HashMap<String, Result<u64, CustomRedisError>>,
    calls: Arc<Mutex<Vec<MockRedisCall>>>,
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
            lpush_ret: HashMap::new(),
            rpop_ret: HashMap::new(),
            llen_ret: HashMap::new(),
            calls: Arc::new(Mutex::new(Vec::new())),
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

    pub fn lpush_ret(&mut self, key: &str, ret: Result<(), CustomRedisError>) -> Self {
        self.lpush_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn rpop_ret(&mut self, key: &str, ret: Result<Option<String>, CustomRedisError>) -> Self {
        self.rpop_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn llen_ret(&mut self, key: &str, ret: Result<u64, CustomRedisError>) -> Self {
        self.llen_ret.insert(key.to_owned(), ret);
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

    async fn lpush(&self, key: String, value: String) -> Result<(), CustomRedisError> {
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "lpush".to_string(),
            key: key.clone(),
            value: MockRedisValue::String(value),
        });

        match self.lpush_ret.get(&key) {
            Some(result) => result.clone(),
            None => Ok(()),
        }
    }

    async fn rpop(&self, key: String) -> Result<Option<String>, CustomRedisError> {
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "rpop".to_string(),
            key: key.clone(),
            value: MockRedisValue::None,
        });

        match self.rpop_ret.get(&key) {
            Some(result) => result.clone(),
            None => Ok(None),
        }
    }

    async fn llen(&self, key: String) -> Result<u64, CustomRedisError> {
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "llen".to_string(),
            key: key.clone(),
            value: MockRedisValue::None,
        });

        match self.llen_ret.get(&key) {
            Some(result) => result.clone(),
            None => Ok(0),
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
            // Verify that RedisClient::new() defaults are backwards compatible
            // This test documents the default behavior and prevents accidental changes

            // Default compression should be DISABLED for backwards compatibility
            let default_compression = CompressionConfig::disabled();
            assert!(!default_compression.enabled);

            // Default format should be Pickle (existing behavior)
            let default_format = RedisValueFormat::default();
            assert_eq!(default_format, RedisValueFormat::Pickle);
        }

        #[test]
        fn test_compression_config_default_is_django_compatible() {
            // CompressionConfig::default() provides Django-compatible settings
            // This is used when explicitly opting into compression via with_config()
            let config = CompressionConfig::default();
            assert!(config.enabled);
            assert_eq!(config.threshold, 512); // Match Django's ZstdCompressor.min_length
            assert_eq!(config.level, 0); // Match Django's zstd_preset default
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

            // Higher level should compress better
            assert!(compressed_level10.len() <= compressed_level1.len());

            // Both should decompress correctly
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

            // Formats should produce different byte representations
            assert_ne!(pickle_bytes, utf8_bytes);

            // Both should deserialize correctly
            let pickle_result = helpers::deserialize_value(&pickle_bytes, RedisValueFormat::Pickle);
            let utf8_result = helpers::deserialize_value(&utf8_bytes, RedisValueFormat::Utf8);

            assert_eq!(pickle_result, test_value);
            assert_eq!(utf8_result, test_value);
        }

        #[test]
        fn test_compression_applied_to_both_formats() {
            let large_value = "x".repeat(1000);
            let config = CompressionConfig::default();

            // Test Pickle format with compression
            let pickle_serialized =
                helpers::serialize_value(&large_value, RedisValueFormat::Pickle);
            let pickle_compressed =
                RedisClient::maybe_compress(pickle_serialized.clone(), &config).unwrap();
            helpers::assert_compression_applied(&pickle_serialized, &pickle_compressed, &config);

            // Test Utf8 format with compression
            let utf8_serialized = helpers::serialize_value(&large_value, RedisValueFormat::Utf8);
            let utf8_compressed =
                RedisClient::maybe_compress(utf8_serialized.clone(), &config).unwrap();
            helpers::assert_compression_applied(&utf8_serialized, &utf8_compressed, &config);

            // Both should decompress back to original value
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
            // Test that try_decompress gracefully handles uncompressed data
            let uncompressed = b"hello world".to_vec();
            let result = RedisClient::try_decompress(uncompressed.clone());
            assert_eq!(result, uncompressed);

            // Test that try_decompress successfully decompresses compressed data
            let large_data = "x".repeat(1000);
            let compressed = zstd::encode_all(large_data.as_bytes(), 0).unwrap();
            let decompressed = RedisClient::try_decompress(compressed);
            assert_eq!(decompressed, large_data.as_bytes());
        }

        #[test]
        fn test_cross_compression_compatibility() {
            // Verify that data written with compression can be read without compression enabled
            // This is the key feature that makes compression settings flexible

            let test_value = "x".repeat(1000); // Large enough to trigger compression

            // Simulate writing with compression enabled
            let compressed_config = CompressionConfig::default();
            let serialized = helpers::serialize_value(&test_value, RedisValueFormat::Pickle);
            let compressed = RedisClient::maybe_compress(serialized, &compressed_config).unwrap();

            // Verify data is actually compressed
            assert!(compressed.len() < test_value.len());

            // Simulate reading with try_decompress (which always runs regardless of config)
            let decompressed = RedisClient::try_decompress(compressed);
            let result = helpers::deserialize_value(&decompressed, RedisValueFormat::Pickle);

            assert_eq!(result, test_value);
        }
    }
}
