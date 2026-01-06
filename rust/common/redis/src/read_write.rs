use async_trait::async_trait;
use std::sync::Arc;
use std::time::Duration;
use tracing::warn;

use crate::{Client, CompressionConfig, CustomRedisError, RedisClient, RedisValueFormat};

/// Configuration for creating a ReadWriteClient with separate primary and replica URLs.
///
/// This configuration allows you to specify different Redis endpoints for read and write
/// operations (primary for writes, replica for reads), while using the same
/// compression and serialization settings for both.
///
/// # Examples
///
/// ```no_run
/// use common_redis::{ReadWriteClientConfig, CompressionConfig, RedisValueFormat};
///
/// # async fn example() {
/// let config = ReadWriteClientConfig::new(
///     "redis://primary:6379".to_string(),
///     "redis://replica:6379".to_string(),
///     CompressionConfig::default(),
///     RedisValueFormat::Pickle,
///     None, // No response timeout
///     None, // No connection timeout
/// );
///
/// let client = config.build().await.unwrap();
/// # }
/// ```
#[derive(Debug, Clone)]
pub struct ReadWriteClientConfig {
    pub primary_url: String,
    pub replica_url: String,
    pub compression: CompressionConfig,
    pub format: RedisValueFormat,
    pub response_timeout: Option<Duration>,
    pub connection_timeout: Option<Duration>,
}

impl ReadWriteClientConfig {
    /// Create a new ReadWriteClientConfig.
    ///
    /// # Arguments
    /// * `primary_url` - Redis connection string for writes (primary instance)
    /// * `replica_url` - Redis connection string for reads (replica instance)
    /// * `compression` - Compression configuration applied to both connections
    /// * `format` - Serialization format applied to both connections
    /// * `response_timeout` - Optional timeout for Redis command responses. `None` means no timeout.
    /// * `connection_timeout` - Optional timeout for establishing connections. `None` means no timeout.
    pub fn new(
        primary_url: String,
        replica_url: String,
        compression: CompressionConfig,
        format: RedisValueFormat,
        response_timeout: Option<Duration>,
        connection_timeout: Option<Duration>,
    ) -> Self {
        Self {
            primary_url,
            replica_url,
            compression,
            format,
            response_timeout,
            connection_timeout,
        }
    }

    /// Build a ReadWriteClient from this configuration.
    ///
    /// Creates Redis connections for both primary and replica URLs using the
    /// shared compression and format settings.
    pub async fn build(self) -> Result<ReadWriteClient, CustomRedisError> {
        ReadWriteClient::with_config(self).await
    }
}

/// A Redis client that automatically routes read and write operations to separate connections.
///
/// This client wraps two underlying Redis clients:
/// - A reader for read operations (GET, HGET, etc.)
/// - A writer for write operations (SET, DEL, HINCRBY, etc.)
///
/// Read operations automatically fall back to the writer if the reader fails,
/// providing resilience against reader replica failures.
///
/// # Examples
///
/// ```no_run
/// use common_redis::{Client, ReadWriteClient, ReadWriteClientConfig, CompressionConfig, RedisValueFormat};
///
/// # async fn example() {
/// // Create a ReadWriteClient from config
/// let config = ReadWriteClientConfig::new(
///     "redis://primary:6379".to_string(),
///     "redis://replica:6379".to_string(),
///     CompressionConfig::default(),
///     RedisValueFormat::Pickle,
///     None, // No response timeout
///     None, // No connection timeout
/// );
///
/// let client = ReadWriteClient::with_config(config).await.unwrap();
///
/// // Or use the builder pattern:
/// let client = ReadWriteClientConfig::new(
///     "redis://primary:6379".to_string(),
///     "redis://replica:6379".to_string(),
///     CompressionConfig::default(),
///     RedisValueFormat::Pickle,
///     None, // No response timeout
///     None, // No connection timeout
/// )
/// .build()
/// .await
/// .unwrap();
///
/// // Use it like a normal client - routing happens automatically
/// client.set("key".to_string(), "value".to_string()).await.unwrap();  // → primary
/// let value = client.get("key".to_string()).await.unwrap();  // → replica (falls back to primary on error)
/// # }
/// ```
pub struct ReadWriteClient {
    reader: Arc<dyn Client + Send + Sync>,
    writer: Arc<dyn Client + Send + Sync>,
}

impl Clone for ReadWriteClient {
    fn clone(&self) -> Self {
        Self {
            reader: Arc::clone(&self.reader),
            writer: Arc::clone(&self.writer),
        }
    }
}

impl std::fmt::Debug for ReadWriteClient {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ReadWriteClient")
            .field("reader", &"<Redis Client>")
            .field("writer", &"<Redis Client>")
            .finish()
    }
}

impl ReadWriteClient {
    /// Create a new ReadWriteClient from existing reader and writer clients.
    ///
    /// This allows for maximum flexibility when you need custom client instances
    /// or want to compose clients in special ways (e.g., dual-write patterns).
    ///
    /// # Arguments
    /// * `reader` - Client for read operations
    /// * `writer` - Client for write operations
    ///
    /// # Examples
    /// ```no_run
    /// use common_redis::{ReadWriteClient, RedisClient, CompressionConfig, RedisValueFormat};
    /// use std::sync::Arc;
    ///
    /// # async fn example() {
    /// let replica = Arc::new(
    ///     RedisClient::with_config(
    ///         "redis://replica:6379".to_string(),
    ///         CompressionConfig::default(),
    ///         RedisValueFormat::Pickle,
    ///         None, // No response timeout
    ///         None, // No connection timeout
    ///     )
    ///     .await
    ///     .unwrap()
    /// );
    ///
    /// let primary = Arc::new(
    ///     RedisClient::with_config(
    ///         "redis://primary:6379".to_string(),
    ///         CompressionConfig::default(),
    ///         RedisValueFormat::Pickle,
    ///         None, // No response timeout
    ///         None, // No connection timeout
    ///     )
    ///     .await
    ///     .unwrap()
    /// );
    ///
    /// let client = ReadWriteClient::new(replica, primary);
    /// # }
    /// ```
    pub fn new(
        reader: Arc<dyn Client + Send + Sync>,
        writer: Arc<dyn Client + Send + Sync>,
    ) -> Self {
        Self { reader, writer }
    }

    /// Create a new ReadWriteClient from configuration.
    ///
    /// This is the recommended way to create a ReadWriteClient. It creates
    /// Redis connections for both primary and replica URLs using shared
    /// compression and format settings.
    ///
    /// # Arguments
    /// * `config` - Configuration specifying primary/replica URLs and shared settings
    ///
    /// # Examples
    /// ```no_run
    /// use common_redis::{ReadWriteClient, ReadWriteClientConfig, CompressionConfig, RedisValueFormat};
    ///
    /// # async fn example() {
    /// let config = ReadWriteClientConfig::new(
    ///     "redis://primary:6379".to_string(),
    ///     "redis://replica:6379".to_string(),
    ///     CompressionConfig::default(),
    ///     RedisValueFormat::Pickle,
    ///     None, // No response timeout
    ///     None, // No connection timeout
    /// );
    ///
    /// let client = ReadWriteClient::with_config(config).await.unwrap();
    /// # }
    /// ```
    pub async fn with_config(config: ReadWriteClientConfig) -> Result<Self, CustomRedisError> {
        let reader = Arc::new(
            RedisClient::with_config(
                config.replica_url,
                config.compression.clone(),
                config.format,
                config.response_timeout,
                config.connection_timeout,
            )
            .await?,
        );
        let writer = Arc::new(
            RedisClient::with_config(
                config.primary_url,
                config.compression,
                config.format,
                config.response_timeout,
                config.connection_timeout,
            )
            .await?,
        );

        Ok(Self::new(reader, writer))
    }
}

#[async_trait]
impl Client for ReadWriteClient {
    async fn get(&self, k: String) -> Result<String, CustomRedisError> {
        match self.reader.get(k.clone()).await {
            Ok(value) => Ok(value),
            Err(err) if !err.is_unrecoverable_error() => {
                warn!(
                    "Replica read failed for key '{}', falling back to primary: {}",
                    k, err
                );
                self.writer.get(k).await
            }
            Err(err) => Err(err),
        }
    }

    async fn get_with_format(
        &self,
        k: String,
        format: RedisValueFormat,
    ) -> Result<String, CustomRedisError> {
        match self.reader.get_with_format(k.clone(), format).await {
            Ok(value) => Ok(value),
            Err(err) if !err.is_unrecoverable_error() => {
                warn!(
                    "Replica read failed for key '{}', falling back to primary: {}",
                    k, err
                );
                self.writer.get_with_format(k, format).await
            }
            Err(err) => Err(err),
        }
    }

    async fn get_raw_bytes(&self, k: String) -> Result<Vec<u8>, CustomRedisError> {
        match self.reader.get_raw_bytes(k.clone()).await {
            Ok(value) => Ok(value),
            Err(err) if !err.is_unrecoverable_error() => {
                warn!(
                    "Replica read failed for key '{}', falling back to primary: {}",
                    k, err
                );
                self.writer.get_raw_bytes(k).await
            }
            Err(err) => Err(err),
        }
    }

    async fn hget(&self, k: String, field: String) -> Result<String, CustomRedisError> {
        match self.reader.hget(k.clone(), field.clone()).await {
            Ok(value) => Ok(value),
            Err(err) if !err.is_unrecoverable_error() => {
                warn!(
                    "Replica read failed for key '{}' field '{}', falling back to primary: {}",
                    k, field, err
                );
                self.writer.hget(k, field).await
            }
            Err(err) => Err(err),
        }
    }

    async fn zrangebyscore(
        &self,
        k: String,
        min: String,
        max: String,
    ) -> Result<Vec<String>, CustomRedisError> {
        match self
            .reader
            .zrangebyscore(k.clone(), min.clone(), max.clone())
            .await
        {
            Ok(value) => Ok(value),
            Err(err) if !err.is_unrecoverable_error() => {
                warn!(
                    "Replica zrangebyscore failed for key '{}', falling back to primary: {}",
                    k, err
                );
                self.writer.zrangebyscore(k, min, max).await
            }
            Err(err) => Err(err),
        }
    }

    async fn scard(&self, k: String) -> Result<u64, CustomRedisError> {
        match self.reader.scard(k.clone()).await {
            Ok(value) => Ok(value),
            Err(err) if !err.is_unrecoverable_error() => {
                warn!(
                    "Replica scard failed for key '{}', falling back to primary: {}",
                    k, err
                );
                self.writer.scard(k).await
            }
            Err(err) => Err(err),
        }
    }

    async fn set(&self, k: String, v: String) -> Result<(), CustomRedisError> {
        self.writer.set(k, v).await
    }

    async fn set_with_format(
        &self,
        k: String,
        v: String,
        format: RedisValueFormat,
    ) -> Result<(), CustomRedisError> {
        self.writer.set_with_format(k, v, format).await
    }

    async fn setex(&self, k: String, v: String, seconds: u64) -> Result<(), CustomRedisError> {
        self.writer.setex(k, v, seconds).await
    }

    async fn set_nx_ex(
        &self,
        k: String,
        v: String,
        seconds: u64,
    ) -> Result<bool, CustomRedisError> {
        self.writer.set_nx_ex(k, v, seconds).await
    }

    async fn set_nx_ex_with_format(
        &self,
        k: String,
        v: String,
        seconds: u64,
        format: RedisValueFormat,
    ) -> Result<bool, CustomRedisError> {
        self.writer
            .set_nx_ex_with_format(k, v, seconds, format)
            .await
    }

    async fn batch_incr_by_expire_nx(
        &self,
        items: Vec<(String, i64)>,
        ttl_seconds: usize,
    ) -> Result<(), CustomRedisError> {
        self.writer
            .batch_incr_by_expire_nx(items, ttl_seconds)
            .await
    }

    async fn batch_incr_by_expire(
        &self,
        items: Vec<(String, i64)>,
        ttl_seconds: usize,
    ) -> Result<(), CustomRedisError> {
        self.writer.batch_incr_by_expire(items, ttl_seconds).await
    }

    async fn del(&self, k: String) -> Result<(), CustomRedisError> {
        self.writer.del(k).await
    }

    async fn hincrby(
        &self,
        k: String,
        v: String,
        count: Option<i32>,
    ) -> Result<(), CustomRedisError> {
        self.writer.hincrby(k, v, count).await
    }

    async fn mget(&self, keys: Vec<String>) -> Result<Vec<Option<Vec<u8>>>, CustomRedisError> {
        match self.reader.mget(keys.clone()).await {
            Ok(value) => Ok(value),
            Err(err) if !err.is_unrecoverable_error() => {
                warn!(
                    "Replica mget failed for {} keys, falling back to primary: {}",
                    keys.len(),
                    err
                );
                self.writer.mget(keys).await
            }
            Err(err) => Err(err),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::MockRedisClient;

    fn create_test_client(
        reader_setup: impl FnOnce(&mut MockRedisClient),
        writer_setup: impl FnOnce(&mut MockRedisClient),
    ) -> ReadWriteClient {
        let mut reader = MockRedisClient::new();
        reader_setup(&mut reader);

        let mut writer = MockRedisClient::new();
        writer_setup(&mut writer);

        ReadWriteClient::new(Arc::new(reader), Arc::new(writer))
    }

    #[tokio::test]
    async fn test_read_operations_use_reader() {
        let client = create_test_client(
            |reader| {
                reader.get_ret("test_key", Ok("reader_value".to_string()));
                reader.get_raw_bytes_ret("raw_key", Ok(vec![1, 2, 3]));
                reader.hget_ret("hash_key", Ok("field_value".to_string()));
                reader.zrangebyscore_ret("zset_key", vec!["item1".to_string()]);
                reader.scard_ret("set_key", Ok(5));
            },
            |_writer| {},
        );

        let result = client.get("test_key".to_string()).await;
        assert_eq!(result.unwrap(), "reader_value");

        let result = client.get_raw_bytes("raw_key".to_string()).await;
        assert_eq!(result.unwrap(), vec![1, 2, 3]);

        let result = client
            .hget("hash_key".to_string(), "field".to_string())
            .await;
        assert_eq!(result.unwrap(), "field_value");

        let result = client
            .zrangebyscore("zset_key".to_string(), "0".to_string(), "10".to_string())
            .await;
        assert_eq!(result.unwrap(), vec!["item1".to_string()]);

        let result = client.scard("set_key".to_string()).await;
        assert_eq!(result.unwrap(), 5);
    }

    #[tokio::test]
    async fn test_write_operations_use_writer() {
        let client = create_test_client(
            |_reader| {},
            |writer| {
                writer.set_ret("test_key", Ok(()));
                writer.set_ret("test_key_format", Ok(()));
                writer.set_ret("test_key_ex", Ok(()));
                writer.set_nx_ex_ret("test_key_nx", Ok(true));
                writer.set_nx_ex_ret("test_key_nx_format", Ok(false));
                writer.del_ret("del_key", Ok(()));
                writer.hincrby_ret("counter", Ok(()));
            },
        );

        let result = client
            .set("test_key".to_string(), "value".to_string())
            .await;
        assert!(result.is_ok());

        let result = client
            .set_with_format(
                "test_key_format".to_string(),
                "value".to_string(),
                RedisValueFormat::Utf8,
            )
            .await;
        assert!(result.is_ok());

        let result = client
            .setex("test_key_ex".to_string(), "value".to_string(), 60)
            .await;
        assert!(result.is_ok());

        let result = client
            .set_nx_ex("test_key_nx".to_string(), "value".to_string(), 60)
            .await;
        assert!(result.unwrap());

        let result = client
            .set_nx_ex_with_format(
                "test_key_nx_format".to_string(),
                "value".to_string(),
                60,
                RedisValueFormat::Utf8,
            )
            .await;
        assert!(!result.unwrap());

        let result = client.del("del_key".to_string()).await;
        assert!(result.is_ok());

        let result = client
            .hincrby("counter".to_string(), "field".to_string(), Some(5))
            .await;
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_fallback_on_transient_error() {
        let client = create_test_client(
            |reader| {
                reader.get_ret("test_key", Err(CustomRedisError::Timeout));
            },
            |writer| {
                writer.get_ret("test_key", Ok("writer_value".to_string()));
            },
        );

        let result = client.get("test_key".to_string()).await;
        assert_eq!(result.unwrap(), "writer_value");
    }

    #[tokio::test]
    async fn test_fallback_on_io_error() {
        let client = create_test_client(
            |reader| {
                reader.get_ret(
                    "test_key",
                    Err(CustomRedisError::from_redis_kind(
                        crate::RedisErrorKind::IoError,
                        "Connection refused",
                    )),
                );
            },
            |writer| {
                writer.get_ret("test_key", Ok("writer_value".to_string()));
            },
        );

        let result = client.get("test_key".to_string()).await;
        assert_eq!(result.unwrap(), "writer_value");
    }

    #[tokio::test]
    async fn test_no_fallback_on_unrecoverable_error() {
        let client = create_test_client(
            |reader| {
                reader.get_ret("test_key", Err(CustomRedisError::NotFound));
            },
            |writer| {
                writer.get_ret("test_key", Ok("writer_value".to_string()));
            },
        );

        let result = client.get("test_key".to_string()).await;
        assert!(matches!(result, Err(CustomRedisError::NotFound)));
    }

    #[tokio::test]
    async fn test_no_fallback_on_parse_error() {
        let client = create_test_client(
            |reader| {
                reader.get_ret(
                    "test_key",
                    Err(CustomRedisError::ParseError("bad data".to_string())),
                );
            },
            |writer| {
                writer.get_ret("test_key", Ok("writer_value".to_string()));
            },
        );

        let result = client.get("test_key".to_string()).await;
        assert!(matches!(result, Err(CustomRedisError::ParseError(_))));
    }

    #[tokio::test]
    async fn test_fallback_works_for_all_read_operations() {
        // MockRedisClient's zrangebyscore_ret doesn't support error returns
        let client = create_test_client(
            |reader| {
                reader.get_ret("get_key", Err(CustomRedisError::Timeout));
                reader.get_raw_bytes_ret("raw_key", Err(CustomRedisError::Timeout));
                reader.hget_ret("hash_key", Err(CustomRedisError::Timeout));
                reader.scard_ret("set_key", Err(CustomRedisError::Timeout));
            },
            |writer| {
                writer.get_ret("get_key", Ok("fallback".to_string()));
                writer.get_raw_bytes_ret("raw_key", Ok(vec![4, 5, 6]));
                writer.hget_ret("hash_key", Ok("fallback_field".to_string()));
                writer.scard_ret("set_key", Ok(10));
            },
        );

        assert_eq!(client.get("get_key".to_string()).await.unwrap(), "fallback");
        assert_eq!(
            client.get_raw_bytes("raw_key".to_string()).await.unwrap(),
            vec![4, 5, 6]
        );
        assert_eq!(
            client
                .hget("hash_key".to_string(), "field".to_string())
                .await
                .unwrap(),
            "fallback_field"
        );
        assert_eq!(client.scard("set_key".to_string()).await.unwrap(), 10);
    }

    #[tokio::test]
    async fn test_zrangebyscore_routing() {
        let client = create_test_client(
            |reader| {
                reader.zrangebyscore_ret("zset_key", vec!["reader_item".to_string()]);
            },
            |_writer| {},
        );

        let result = client
            .zrangebyscore("zset_key".to_string(), "0".to_string(), "10".to_string())
            .await;
        assert_eq!(result.unwrap(), vec!["reader_item".to_string()]);
    }

    #[tokio::test]
    async fn test_reader_success_writer_never_called() {
        let client = create_test_client(
            |reader| {
                reader.get_ret("test_key", Ok("reader_value".to_string()));
            },
            |writer| {
                // Writer error ensures test fails if writer is called
                writer.get_ret("test_key", Err(CustomRedisError::NotFound));
            },
        );

        let result = client.get("test_key".to_string()).await;
        assert_eq!(result.unwrap(), "reader_value");
    }

    #[tokio::test]
    async fn test_get_with_format_routing() {
        let client = create_test_client(
            |reader| {
                reader.get_ret("test_key", Ok("reader_value".to_string()));
            },
            |_writer| {},
        );

        let result = client
            .get_with_format("test_key".to_string(), RedisValueFormat::Utf8)
            .await;
        assert_eq!(result.unwrap(), "reader_value");
    }

    #[tokio::test]
    async fn test_get_with_format_fallback() {
        let client = create_test_client(
            |reader| {
                reader.get_ret("test_key", Err(CustomRedisError::Timeout));
            },
            |writer| {
                writer.get_ret("test_key", Ok("writer_fallback".to_string()));
            },
        );

        let result = client
            .get_with_format("test_key".to_string(), RedisValueFormat::Utf8)
            .await;
        assert_eq!(result.unwrap(), "writer_fallback");
    }

    #[test]
    fn test_clone_implementation() {
        let client = create_test_client(
            |reader| {
                reader.get_ret("test_key", Ok("value".to_string()));
            },
            |_writer| {},
        );

        let cloned = client.clone();

        // Arc cloning doesn't deep copy - both references point to same clients
        drop(client);
        assert!(format!("{cloned:?}").contains("ReadWriteClient"));
    }

    #[test]
    fn test_debug_implementation() {
        let client = create_test_client(|_reader| {}, |_writer| {});

        let debug_output = format!("{client:?}");
        assert!(debug_output.contains("ReadWriteClient"));
        assert!(debug_output.contains("reader"));
        assert!(debug_output.contains("writer"));
        assert!(debug_output.contains("<Redis Client>"));
    }

    #[tokio::test]
    async fn test_mget_uses_reader() {
        let client = create_test_client(
            |reader| {
                reader.mget_ret("key1", Some(b"value1".to_vec()));
                reader.mget_ret("key2", Some(b"value2".to_vec()));
            },
            |_writer| {},
        );

        let result = client
            .mget(vec!["key1".to_string(), "key2".to_string()])
            .await;
        assert_eq!(
            result.unwrap(),
            vec![Some(b"value1".to_vec()), Some(b"value2".to_vec())]
        );
    }

    #[tokio::test]
    async fn test_mget_fallback_on_transient_error() {
        let client = create_test_client(
            |reader| {
                reader.mget_error(CustomRedisError::Timeout);
            },
            |writer| {
                writer.mget_ret("key1", Some(b"fallback1".to_vec()));
                writer.mget_ret("key2", Some(b"fallback2".to_vec()));
            },
        );

        let result = client
            .mget(vec!["key1".to_string(), "key2".to_string()])
            .await;
        assert_eq!(
            result.unwrap(),
            vec![Some(b"fallback1".to_vec()), Some(b"fallback2".to_vec())]
        );
    }

    #[tokio::test]
    async fn test_mget_no_fallback_on_unrecoverable_error() {
        let client = create_test_client(
            |reader| {
                reader.mget_error(CustomRedisError::ParseError("bad data".to_string()));
            },
            |writer| {
                writer.mget_ret("key1", Some(b"fallback".to_vec()));
            },
        );

        let result = client.mget(vec!["key1".to_string()]).await;
        assert!(matches!(result, Err(CustomRedisError::ParseError(_))));
    }
}
