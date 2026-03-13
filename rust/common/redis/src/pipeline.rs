//! Redis pipeline support for batching multiple commands into a single round-trip.
//!
//! # Example
//!
//! ```rust,ignore
//! use common_redis::{Client, Pipeline, PipelineResult};
//!
//! async fn example(client: &impl Client) -> Result<(), CustomRedisError> {
//!     let results = client.pipeline()
//!         .set("key1", "value1")
//!         .set("key2", "value2")
//!         .get("key3")
//!         .execute()
//!         .await?;
//!
//!     // results[0] = Ok(PipelineResult::Ok)
//!     // results[1] = Ok(PipelineResult::Ok)
//!     // results[2] = Ok(PipelineResult::String("...")) or Err(NotFound)
//!     Ok(())
//! }
//! ```

use crate::{Client, CustomRedisError, RedisValueFormat};

/// Result type for individual pipeline operations.
///
/// Each variant corresponds to the return type of a Redis command.
#[derive(Debug, Clone, PartialEq)]
pub enum PipelineResult {
    /// Success with no return value (SET, DEL, HINCRBY, etc.)
    Ok,
    /// String value (GET)
    String(String),
    /// Raw bytes (GET raw bytes)
    Bytes(Vec<u8>),
    /// Boolean result (SET NX EX)
    Bool(bool),
    /// Count result (SCARD)
    Count(u64),
    /// List of strings (ZRANGEBYSCORE)
    Strings(Vec<String>),
}

/// Internal representation of a pipeline command.
#[derive(Debug, Clone)]
pub enum PipelineCommand {
    Get {
        key: String,
        format: RedisValueFormat,
    },
    GetRawBytes {
        key: String,
    },
    Set {
        key: String,
        value: String,
        format: RedisValueFormat,
    },
    SetEx {
        key: String,
        value: String,
        seconds: u64,
        format: RedisValueFormat,
    },
    SetNxEx {
        key: String,
        value: String,
        seconds: u64,
        format: RedisValueFormat,
    },
    Del {
        key: String,
    },
    HGet {
        key: String,
        field: String,
    },
    HIncrBy {
        key: String,
        field: String,
        count: i32,
    },
    Scard {
        key: String,
    },
    ZRangeByScore {
        key: String,
        min: String,
        max: String,
    },
}

/// A Redis pipeline that batches multiple commands into a single round-trip.
///
/// Create a pipeline using [`ClientPipelineExt::pipeline()`], add commands using the builder
/// methods, then call [`execute()`](Pipeline::execute) to send all commands at once.
///
/// # Example
///
/// ```rust,ignore
/// let results = client.pipeline()
///     .set("key1", "value1")
///     .set("key2", "value2")
///     .get("key3")
///     .execute()
///     .await?;
/// ```
pub struct Pipeline<C> {
    client: C,
    commands: Vec<PipelineCommand>,
}

impl<C> Pipeline<C> {
    /// Create a new pipeline for the given client.
    pub fn new(client: C) -> Self {
        Self {
            client,
            commands: Vec::new(),
        }
    }

    /// Add a GET command to the pipeline.
    pub fn get(self, key: impl Into<String>) -> Self {
        self.get_with_format(key, RedisValueFormat::default())
    }

    /// Add a GET command with a specific format to the pipeline.
    pub fn get_with_format(mut self, key: impl Into<String>, format: RedisValueFormat) -> Self {
        self.commands.push(PipelineCommand::Get {
            key: key.into(),
            format,
        });
        self
    }

    /// Add a GET command for raw bytes to the pipeline.
    pub fn get_raw_bytes(mut self, key: impl Into<String>) -> Self {
        self.commands
            .push(PipelineCommand::GetRawBytes { key: key.into() });
        self
    }

    /// Add a SET command to the pipeline.
    pub fn set(self, key: impl Into<String>, value: impl Into<String>) -> Self {
        self.set_with_format(key, value, RedisValueFormat::default())
    }

    /// Add a SET command with a specific format to the pipeline.
    pub fn set_with_format(
        mut self,
        key: impl Into<String>,
        value: impl Into<String>,
        format: RedisValueFormat,
    ) -> Self {
        self.commands.push(PipelineCommand::Set {
            key: key.into(),
            value: value.into(),
            format,
        });
        self
    }

    /// Add a SETEX command (SET with expiration) to the pipeline.
    pub fn setex(self, key: impl Into<String>, value: impl Into<String>, seconds: u64) -> Self {
        self.setex_with_format(key, value, seconds, RedisValueFormat::default())
    }

    /// Add a SETEX command with a specific format to the pipeline.
    pub fn setex_with_format(
        mut self,
        key: impl Into<String>,
        value: impl Into<String>,
        seconds: u64,
        format: RedisValueFormat,
    ) -> Self {
        self.commands.push(PipelineCommand::SetEx {
            key: key.into(),
            value: value.into(),
            seconds,
            format,
        });
        self
    }

    /// Add a SET NX EX command (SET if not exists with expiration) to the pipeline.
    pub fn set_nx_ex(self, key: impl Into<String>, value: impl Into<String>, seconds: u64) -> Self {
        self.set_nx_ex_with_format(key, value, seconds, RedisValueFormat::default())
    }

    /// Add a SET NX EX command with a specific format to the pipeline.
    pub fn set_nx_ex_with_format(
        mut self,
        key: impl Into<String>,
        value: impl Into<String>,
        seconds: u64,
        format: RedisValueFormat,
    ) -> Self {
        self.commands.push(PipelineCommand::SetNxEx {
            key: key.into(),
            value: value.into(),
            seconds,
            format,
        });
        self
    }

    /// Add a DEL command to the pipeline.
    pub fn del(mut self, key: impl Into<String>) -> Self {
        self.commands.push(PipelineCommand::Del { key: key.into() });
        self
    }

    /// Add an HGET command to the pipeline.
    pub fn hget(mut self, key: impl Into<String>, field: impl Into<String>) -> Self {
        self.commands.push(PipelineCommand::HGet {
            key: key.into(),
            field: field.into(),
        });
        self
    }

    /// Add an HINCRBY command to the pipeline.
    pub fn hincrby(mut self, key: impl Into<String>, field: impl Into<String>, count: i32) -> Self {
        self.commands.push(PipelineCommand::HIncrBy {
            key: key.into(),
            field: field.into(),
            count,
        });
        self
    }

    /// Add an SCARD command to the pipeline.
    pub fn scard(mut self, key: impl Into<String>) -> Self {
        self.commands
            .push(PipelineCommand::Scard { key: key.into() });
        self
    }

    /// Add a ZRANGEBYSCORE command to the pipeline.
    pub fn zrangebyscore(
        mut self,
        key: impl Into<String>,
        min: impl Into<String>,
        max: impl Into<String>,
    ) -> Self {
        self.commands.push(PipelineCommand::ZRangeByScore {
            key: key.into(),
            min: min.into(),
            max: max.into(),
        });
        self
    }

    /// Get the commands in this pipeline.
    pub fn into_commands(self) -> (C, Vec<PipelineCommand>) {
        (self.client, self.commands)
    }

    /// Check if the pipeline is empty.
    pub fn is_empty(&self) -> bool {
        self.commands.is_empty()
    }

    /// Get the number of commands in the pipeline.
    pub fn len(&self) -> usize {
        self.commands.len()
    }
}

impl<C: Client> Pipeline<C> {
    /// Execute all commands in the pipeline as a single batch.
    ///
    /// Returns a vector of results in the same order as commands were added.
    /// Each result is either `Ok(PipelineResult)` or `Err(CustomRedisError)`.
    ///
    /// # Errors
    ///
    /// Returns an error if the connection fails. Individual command failures
    /// are returned as `Err` in the result vector.
    pub async fn execute(
        self,
    ) -> Result<Vec<Result<PipelineResult, CustomRedisError>>, CustomRedisError> {
        let (client, commands) = self.into_commands();
        // Handle empty pipelines here to avoid unnecessary round-trips.
        // This is the single check point - implementations can assume non-empty.
        if commands.is_empty() {
            return Ok(Vec::new());
        }
        client.execute_pipeline(commands).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pipeline_builder_commands() {
        // Create a dummy pipeline to test the builder
        struct DummyClient;

        let pipeline = Pipeline::new(DummyClient)
            .set("key1", "value1")
            .set("key2", "value2")
            .get("key3");

        assert_eq!(pipeline.len(), 3);
        assert!(!pipeline.is_empty());

        let (_, commands) = pipeline.into_commands();
        assert_eq!(commands.len(), 3);

        assert!(
            matches!(&commands[0], PipelineCommand::Set { key, value, .. } if key == "key1" && value == "value1")
        );
        assert!(
            matches!(&commands[1], PipelineCommand::Set { key, value, .. } if key == "key2" && value == "value2")
        );
        assert!(matches!(&commands[2], PipelineCommand::Get { key, .. } if key == "key3"));
    }

    #[test]
    fn test_pipeline_empty() {
        struct DummyClient;
        let pipeline = Pipeline::new(DummyClient);
        assert!(pipeline.is_empty());
        assert_eq!(pipeline.len(), 0);
    }

    #[test]
    fn test_pipeline_all_commands() {
        struct DummyClient;

        let pipeline = Pipeline::new(DummyClient)
            .get("k1")
            .get_with_format("k2", RedisValueFormat::Utf8)
            .get_raw_bytes("k3")
            .set("k4", "v4")
            .set_with_format("k5", "v5", RedisValueFormat::Utf8)
            .setex("k6", "v6", 60)
            .setex_with_format("k7", "v7", 60, RedisValueFormat::Utf8)
            .set_nx_ex("k8", "v8", 60)
            .set_nx_ex_with_format("k9", "v9", 60, RedisValueFormat::Utf8)
            .del("k10")
            .hget("k11", "f11")
            .hincrby("k12", "f12", 5)
            .scard("k13")
            .zrangebyscore("k14", "0", "100");

        assert_eq!(pipeline.len(), 14);
    }

    #[test]
    fn test_pipeline_result_equality() {
        assert_eq!(PipelineResult::Ok, PipelineResult::Ok);
        assert_eq!(
            PipelineResult::String("test".to_string()),
            PipelineResult::String("test".to_string())
        );
        assert_ne!(
            PipelineResult::String("test1".to_string()),
            PipelineResult::String("test2".to_string())
        );
    }
}

#[cfg(test)]
mod integration_tests {
    use super::*;
    use crate::{ClientPipelineExt, CustomRedisError, MockRedisClient};

    #[tokio::test]
    async fn test_mock_pipeline_set_and_get() {
        let mut client = MockRedisClient::new();
        client.set_ret("key1", Ok(()));
        client.set_ret("key2", Ok(()));
        client.get_ret("key3", Ok("value3".to_string()));

        let results = client
            .pipeline()
            .set("key1", "value1")
            .set("key2", "value2")
            .get("key3")
            .execute()
            .await
            .unwrap();

        assert_eq!(results.len(), 3);
        assert!(matches!(results[0], Ok(PipelineResult::Ok)));
        assert!(matches!(results[1], Ok(PipelineResult::Ok)));
        assert!(matches!(&results[2], Ok(PipelineResult::String(s)) if s == "value3"));
    }

    #[tokio::test]
    async fn test_mock_pipeline_partial_failure() {
        let mut client = MockRedisClient::new();
        client.set_ret("key1", Ok(()));
        // key2 not configured, will return NotFound
        client.get_ret("key3", Ok("value3".to_string()));

        let results = client
            .pipeline()
            .set("key1", "value1")
            .get("key2") // This will fail
            .get("key3")
            .execute()
            .await
            .unwrap();

        assert_eq!(results.len(), 3);
        assert!(matches!(results[0], Ok(PipelineResult::Ok)));
        assert!(matches!(results[1], Err(CustomRedisError::NotFound)));
        assert!(matches!(&results[2], Ok(PipelineResult::String(s)) if s == "value3"));
    }

    #[tokio::test]
    async fn test_mock_pipeline_empty() {
        let client = MockRedisClient::new();

        let results = client.pipeline().execute().await.unwrap();

        assert!(results.is_empty());
    }

    #[tokio::test]
    async fn test_mock_pipeline_records_calls() {
        let mut client = MockRedisClient::new();
        client.set_ret("key1", Ok(()));
        client.get_ret("key2", Ok("value2".to_string()));

        let _results = client
            .pipeline()
            .set("key1", "value1")
            .get("key2")
            .execute()
            .await
            .unwrap();

        let calls = client.get_calls();
        assert_eq!(calls.len(), 2);
        assert_eq!(calls[0].op, "pipeline_set");
        assert_eq!(calls[0].key, "key1");
        assert_eq!(calls[1].op, "pipeline_get");
        assert_eq!(calls[1].key, "key2");
    }

    #[tokio::test]
    async fn test_mock_pipeline_all_result_types() {
        let mut client = MockRedisClient::new();
        client.get_ret("get_key", Ok("string_value".to_string()));
        client.set_ret("set_key", Ok(()));
        client.del_ret("del_key", Ok(()));
        client.set_nx_ex_ret("nx_key", Ok(true));
        client.scard_ret("scard_key", Ok(42));
        client.zrangebyscore_ret("zset_key", vec!["a".to_string(), "b".to_string()]);

        let results = client
            .pipeline()
            .get("get_key")
            .set("set_key", "value")
            .del("del_key")
            .set_nx_ex("nx_key", "value", 60)
            .scard("scard_key")
            .zrangebyscore("zset_key", "0", "100")
            .execute()
            .await
            .unwrap();

        assert_eq!(results.len(), 6);
        assert!(matches!(&results[0], Ok(PipelineResult::String(s)) if s == "string_value"));
        assert!(matches!(results[1], Ok(PipelineResult::Ok)));
        assert!(matches!(results[2], Ok(PipelineResult::Ok)));
        assert!(matches!(results[3], Ok(PipelineResult::Bool(true))));
        assert!(matches!(results[4], Ok(PipelineResult::Count(42))));
        assert!(
            matches!(&results[5], Ok(PipelineResult::Strings(v)) if v == &vec!["a".to_string(), "b".to_string()])
        );
    }
}
