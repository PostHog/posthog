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
}

impl RedisClient {
    pub async fn new(addr: String) -> Result<RedisClient, CustomRedisError> {
        let client = redis::Client::open(addr)?;
        let connection = client.get_multiplexed_async_connection().await?;
        Ok(RedisClient { connection })
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

        match format {
            RedisValueFormat::Pickle => {
                let string_response: String =
                    serde_pickle::from_slice(&raw_bytes, Default::default())?;
                Ok(string_response)
            }
            RedisValueFormat::Utf8 => {
                let string_response = String::from_utf8(raw_bytes)?;
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
        let mut conn = self.connection.clone();
        let results = conn.set(k, bytes);
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
        let mut conn = self.connection.clone();
        let seconds_usize = seconds as usize;

        // Use SET with both NX and EX options
        let result: Result<Option<String>, RedisError> = timeout(
            Duration::from_millis(get_redis_timeout_ms()),
            redis::cmd("SET")
                .arg(&k)
                .arg(&bytes)
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
