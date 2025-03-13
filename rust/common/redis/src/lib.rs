use std::collections::HashMap;
use std::time::Duration;

use async_trait::async_trait;
use redis::{AsyncCommands, RedisError};
use thiserror::Error;
use tokio::time::timeout;

const REDIS_TIMEOUT_MILLISECS: u64 = 10;

#[derive(Error, Debug, Clone)]
pub enum CustomRedisError {
    #[error("Not found in redis")]
    NotFound,
    #[error("Pickle error: {0}")]
    PickleError(String),
    #[error("Redis error: {0}")]
    Other(String),
    #[error("Timeout error")]
    Timeout,
}

impl From<serde_pickle::Error> for CustomRedisError {
    fn from(err: serde_pickle::Error) -> Self {
        CustomRedisError::PickleError(err.to_string())
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
    async fn set(&self, k: String, v: String) -> Result<(), CustomRedisError>;
    async fn del(&self, k: String) -> Result<(), CustomRedisError>;
    async fn hget(&self, k: String, field: String) -> Result<String, CustomRedisError>;
}

pub struct RedisClient {
    client: redis::Client,
}

impl RedisClient {
    pub fn new(addr: String) -> Result<RedisClient, CustomRedisError> {
        let client = redis::Client::open(addr)?;
        Ok(RedisClient { client })
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
        let mut conn = self.client.get_async_connection().await?;
        let results = conn.zrangebyscore(k, min, max);
        let fut = timeout(Duration::from_millis(REDIS_TIMEOUT_MILLISECS), results).await?;
        Ok(fut?)
    }

    async fn hincrby(
        &self,
        k: String,
        v: String,
        count: Option<i32>,
    ) -> Result<(), CustomRedisError> {
        let mut conn = self.client.get_async_connection().await?;
        let count = count.unwrap_or(1);
        let results = conn.hincr(k, v, count);
        let fut = timeout(Duration::from_millis(REDIS_TIMEOUT_MILLISECS), results).await?;
        fut.map_err(|e| CustomRedisError::Other(e.to_string()))
    }

    async fn get(&self, k: String) -> Result<String, CustomRedisError> {
        let mut conn = self.client.get_async_connection().await?;
        let results = conn.get(k);
        let fut: Result<Vec<u8>, RedisError> =
            timeout(Duration::from_millis(REDIS_TIMEOUT_MILLISECS), results).await?;

        // return NotFound error when empty
        if matches!(&fut, Ok(v) if v.is_empty()) {
            return Err(CustomRedisError::NotFound);
        }

        let raw_bytes = fut?;
        let string_response: String = serde_pickle::from_slice(&raw_bytes, Default::default())?;
        Ok(string_response)
    }

    async fn set(&self, k: String, v: String) -> Result<(), CustomRedisError> {
        let bytes = serde_pickle::to_vec(&v, Default::default())?;
        let mut conn = self.client.get_async_connection().await?;
        let results = conn.set(k, bytes);
        let fut = timeout(Duration::from_millis(REDIS_TIMEOUT_MILLISECS), results).await?;
        Ok(fut?)
    }

    async fn del(&self, k: String) -> Result<(), CustomRedisError> {
        let mut conn = self.client.get_async_connection().await?;
        let results = conn.del(k);
        let fut = timeout(Duration::from_millis(REDIS_TIMEOUT_MILLISECS), results).await?;
        fut.map_err(|e| CustomRedisError::Other(e.to_string()))
    }

    async fn hget(&self, k: String, field: String) -> Result<String, CustomRedisError> {
        let mut conn = self.client.get_async_connection().await?;
        let results = conn.hget(k, field);
        let fut: Result<Option<String>, RedisError> =
            timeout(Duration::from_millis(REDIS_TIMEOUT_MILLISECS), results).await?;

        match fut? {
            Some(value) => Ok(value),
            None => Err(CustomRedisError::NotFound),
        }
    }
}

#[derive(Clone, Default)]
pub struct MockRedisClient {
    zrangebyscore_ret: HashMap<String, Vec<String>>,
    hincrby_ret: HashMap<String, Result<(), CustomRedisError>>,
    get_ret: HashMap<String, Result<String, CustomRedisError>>,
    set_ret: HashMap<String, Result<(), CustomRedisError>>,
    del_ret: HashMap<String, Result<(), CustomRedisError>>,
    hget_ret: HashMap<String, Result<String, CustomRedisError>>,
}

impl MockRedisClient {
    pub fn new() -> Self {
        Self::default()
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
}

#[async_trait]
impl Client for MockRedisClient {
    async fn zrangebyscore(
        &self,
        key: String,
        _min: String,
        _max: String,
    ) -> Result<Vec<String>, CustomRedisError> {
        match self.zrangebyscore_ret.get(&key) {
            Some(val) => Ok(val.clone()),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn hincrby(
        &self,
        key: String,
        _field: String,
        _count: Option<i32>,
    ) -> Result<(), CustomRedisError> {
        match self.hincrby_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn get(&self, key: String) -> Result<String, CustomRedisError> {
        match self.get_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn set(&self, key: String, _value: String) -> Result<(), CustomRedisError> {
        match self.set_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn del(&self, key: String) -> Result<(), CustomRedisError> {
        match self.del_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn hget(&self, key: String, _field: String) -> Result<String, CustomRedisError> {
        match self.hget_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }
}
