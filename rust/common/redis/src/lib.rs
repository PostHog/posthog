use async_trait::async_trait;
use std::sync::Arc;
use thiserror::Error;

// Re-export ErrorKind and RetryMethod so consumers can construct CustomRedisError in tests
// and understand retry behavior
pub use redis::ErrorKind as RedisErrorKind;
pub use redis::RetryMethod;

#[derive(Error, Debug, Clone)]
pub enum CustomRedisError {
    #[error("Not found in redis")]
    NotFound,
    #[error("Invalid configuration: {0}")]
    InvalidConfiguration(String),
    #[error("Parse error: {0}")]
    ParseError(String),
    #[error("Timeout error")]
    Timeout,
    #[error(transparent)]
    Redis(#[from] Arc<redis::RedisError>),
}

impl From<serde_pickle::Error> for CustomRedisError {
    fn from(err: serde_pickle::Error) -> Self {
        CustomRedisError::ParseError(err.to_string())
    }
}

impl From<redis::RedisError> for CustomRedisError {
    fn from(err: redis::RedisError) -> Self {
        if err.is_timeout() {
            CustomRedisError::Timeout
        } else {
            CustomRedisError::Redis(Arc::new(err))
        }
    }
}

impl From<std::string::FromUtf8Error> for CustomRedisError {
    fn from(err: std::string::FromUtf8Error) -> Self {
        CustomRedisError::ParseError(err.to_string())
    }
}

impl CustomRedisError {
    /// Create a Redis error from an ErrorKind (primarily for testing)
    pub fn from_redis_kind(kind: redis::ErrorKind, description: &'static str) -> Self {
        CustomRedisError::Redis(Arc::new(redis::RedisError::from((kind, description))))
    }

    /// Determine if this error is unrecoverable and should not be retried
    ///
    /// Returns `true` for configuration errors and permanent failures.
    /// Returns `false` for transient network/connection issues that may resolve on retry.
    ///
    /// Delegates to redis crate's `is_unrecoverable_error()` for Redis errors.
    pub fn is_unrecoverable_error(&self) -> bool {
        match self {
            // Timeouts are transient - not unrecoverable
            CustomRedisError::Timeout => false,

            // Configuration errors are permanent - unrecoverable
            CustomRedisError::InvalidConfiguration(_) => true,

            // Parse errors are permanent bugs - unrecoverable
            CustomRedisError::ParseError(_) => true,

            // NotFound is permanent - caller should handle this
            CustomRedisError::NotFound => true,

            // For Redis errors, check for specific unrecoverable kinds first
            CustomRedisError::Redis(err) => {
                Self::is_config_error(err) || err.is_unrecoverable_error()
            }
        }
    }

    /// Check if a Redis error is a configuration error that should never be retried
    fn is_config_error(err: &redis::RedisError) -> bool {
        matches!(
            err.kind(),
            redis::ErrorKind::InvalidClientConfig | redis::ErrorKind::AuthenticationFailed
        )
    }

    /// Determine the appropriate retry strategy for this error
    ///
    /// Returns a `RetryMethod` indicating how (if at all) this request should be retried.
    /// Delegates to redis crate's `retry_method()` for Redis errors.
    ///
    /// # Retry Methods
    /// - `NoRetry` - Permanent error, don't retry
    /// - `RetryImmediately` - Temporary issue, retry right away
    /// - `WaitAndRetry` - Sleep first to avoid overload
    /// - `Reconnect` - Create fresh connection (current is broken)
    /// - `MovedRedirect` / `AskRedirect` - Cluster-specific redirections
    pub fn retry_method(&self) -> RetryMethod {
        match self {
            // Timeouts: wait before retrying to avoid hammering the service
            CustomRedisError::Timeout => RetryMethod::WaitAndRetry,

            // Configuration errors are permanent - don't retry
            CustomRedisError::InvalidConfiguration(_) => RetryMethod::NoRetry,

            // Parse errors are permanent bugs - don't retry
            CustomRedisError::ParseError(_) => RetryMethod::NoRetry,

            // NotFound is permanent - caller should handle this
            CustomRedisError::NotFound => RetryMethod::NoRetry,

            // For Redis errors, check for specific non-retryable kinds first
            CustomRedisError::Redis(err) => {
                if Self::is_config_error(err) {
                    RetryMethod::NoRetry
                } else {
                    err.retry_method()
                }
            }
        }
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

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum RedisValueFormat {
    #[default]
    Pickle,
    Utf8,
    RawBytes,
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
    /// Set raw bytes directly without any serialization or compression.
    /// Used primarily for tests that need to write pickle-formatted data.
    async fn set_bytes(
        &self,
        k: String,
        v: Vec<u8>,
        ttl_seconds: Option<u64>,
    ) -> Result<(), CustomRedisError>;
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
    async fn batch_incr_by_expire_nx(
        &self,
        items: Vec<(String, i64)>,
        ttl_seconds: usize,
    ) -> Result<(), CustomRedisError>;

    /// Like batch_incr_by_expire_nx but always sets the TTL (no NX flag).
    /// Compatible with Redis 6.x which doesn't support EXPIRE ... NX.
    async fn batch_incr_by_expire(
        &self,
        items: Vec<(String, i64)>,
        ttl_seconds: usize,
    ) -> Result<(), CustomRedisError>;

    async fn del(&self, k: String) -> Result<(), CustomRedisError>;
    async fn hget(&self, k: String, field: String) -> Result<String, CustomRedisError>;
    async fn scard(&self, k: String) -> Result<u64, CustomRedisError>;
    async fn mget(&self, keys: Vec<String>) -> Result<Vec<Option<Vec<u8>>>, CustomRedisError>;
    async fn scard_multiple(&self, keys: Vec<String>) -> Result<Vec<u64>, CustomRedisError>;
    async fn batch_sadd_expire(
        &self,
        items: Vec<(String, String)>,
        ttl_seconds: usize,
    ) -> Result<(), CustomRedisError>;
    async fn batch_set_nx_ex(
        &self,
        items: Vec<(String, String)>,
        ttl_seconds: usize,
    ) -> Result<Vec<bool>, CustomRedisError>;
    async fn batch_del(&self, keys: Vec<String>) -> Result<(), CustomRedisError>;
}

// Module declarations
mod client;
mod mock;
mod read_write;

// Re-export public APIs
pub use client::RedisClient;
pub use mock::{MockRedisCall, MockRedisClient, MockRedisValue};
pub use read_write::{ReadWriteClient, ReadWriteClientConfig};

#[cfg(test)]
mod tests {
    use super::*;

    mod error_transience {
        use super::*;

        // Tests for our custom error variants
        #[test]
        fn test_timeout_is_recoverable() {
            let err = CustomRedisError::Timeout;
            assert!(!err.is_unrecoverable_error());
        }

        #[test]
        fn test_parse_error_is_unrecoverable() {
            let err = CustomRedisError::ParseError("invalid data".to_string());
            assert!(err.is_unrecoverable_error());
        }

        #[test]
        fn test_not_found_is_unrecoverable() {
            let err = CustomRedisError::NotFound;
            assert!(err.is_unrecoverable_error());
        }

        #[test]
        fn test_invalid_configuration_is_unrecoverable() {
            let err = CustomRedisError::InvalidConfiguration("test config error".to_string());
            assert!(err.is_unrecoverable_error());
        }

        // Smoke test: verify we delegate to redis::RedisError instead of reimplementing
        #[test]
        fn test_redis_error_delegation() {
            let custom_err = CustomRedisError::Redis(Arc::new(redis::RedisError::from((
                redis::ErrorKind::IoError,
                "test error",
            ))));
            let redis_err = redis::RedisError::from((redis::ErrorKind::IoError, "test error"));

            // Verify delegation works by comparing with direct redis::RedisError behavior
            assert_eq!(
                custom_err.is_unrecoverable_error(),
                redis_err.is_unrecoverable_error()
            );
        }
    }

    mod retry_methods {
        use super::*;

        // Tests for our custom error variants
        #[test]
        fn test_timeout_wait_and_retry() {
            let err = CustomRedisError::Timeout;
            assert!(matches!(err.retry_method(), RetryMethod::WaitAndRetry));
        }

        #[test]
        fn test_parse_error_no_retry() {
            let err = CustomRedisError::ParseError("invalid data".to_string());
            assert!(matches!(err.retry_method(), RetryMethod::NoRetry));
        }

        #[test]
        fn test_not_found_no_retry() {
            let err = CustomRedisError::NotFound;
            assert!(matches!(err.retry_method(), RetryMethod::NoRetry));
        }

        #[test]
        fn test_invalid_configuration_no_retry() {
            let err = CustomRedisError::InvalidConfiguration("test config error".to_string());
            assert!(matches!(err.retry_method(), RetryMethod::NoRetry));
        }

        // Smoke test: verify we delegate to redis::RedisError instead of reimplementing
        #[test]
        fn test_redis_error_delegation() {
            let custom_err = CustomRedisError::Redis(Arc::new(redis::RedisError::from((
                redis::ErrorKind::IoError,
                "test error",
            ))));
            let redis_err = redis::RedisError::from((redis::ErrorKind::IoError, "test error"));

            // Verify delegation works by comparing with direct redis::RedisError behavior
            let custom_retry = custom_err.retry_method();
            let redis_retry = redis_err.retry_method();

            // Compare by matching both - they should be the same variant
            match (custom_retry, redis_retry) {
                (RetryMethod::NoRetry, RetryMethod::NoRetry) => {}
                (RetryMethod::Reconnect, RetryMethod::Reconnect) => {}
                (RetryMethod::WaitAndRetry, RetryMethod::WaitAndRetry) => {}
                (RetryMethod::RetryImmediately, RetryMethod::RetryImmediately) => {}
                (RetryMethod::MovedRedirect, RetryMethod::MovedRedirect) => {}
                (RetryMethod::AskRedirect, RetryMethod::AskRedirect) => {}
                _ => panic!("Delegation failed: retry methods don't match"),
            }
        }

        #[test]
        fn test_invalid_client_config_is_unrecoverable() {
            let err = CustomRedisError::Redis(Arc::new(redis::RedisError::from((
                redis::ErrorKind::InvalidClientConfig,
                "Redis URL did not parse",
            ))));

            assert!(
                err.is_unrecoverable_error(),
                "InvalidClientConfig should be unrecoverable"
            );
            assert!(
                matches!(err.retry_method(), RetryMethod::NoRetry),
                "InvalidClientConfig should not be retried"
            );
        }

        #[test]
        fn test_authentication_failed_is_unrecoverable() {
            let err = CustomRedisError::Redis(Arc::new(redis::RedisError::from((
                redis::ErrorKind::AuthenticationFailed,
                "WRONGPASS invalid username-password pair",
            ))));

            assert!(
                err.is_unrecoverable_error(),
                "AuthenticationFailed should be unrecoverable"
            );
            assert!(
                matches!(err.retry_method(), RetryMethod::NoRetry),
                "AuthenticationFailed should not be retried"
            );
        }

        #[test]
        fn test_io_error_is_retryable() {
            let err = CustomRedisError::Redis(Arc::new(redis::RedisError::from((
                redis::ErrorKind::IoError,
                "Connection refused",
            ))));

            // IoError is retryable (transient network issue)
            assert!(
                !err.is_unrecoverable_error(),
                "IoError should be recoverable"
            );
            // The exact retry method depends on redis crate implementation,
            // but it should not be NoRetry
            assert!(
                !matches!(err.retry_method(), RetryMethod::NoRetry),
                "IoError should be retried"
            );
        }
    }
}
