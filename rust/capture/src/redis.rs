use std::collections::HashMap;
use std::time::Duration;

use anyhow::{anyhow, Result};
use async_trait::async_trait;
use redis::AsyncCommands;
use tokio::time::timeout;

// average for all commands is <10ms, check grafana
const REDIS_TIMEOUT_MILLISECS: u64 = 10;

/// A simple redis wrapper
/// I'm currently just exposing the commands we use, for ease of implementation
/// Allows for testing + injecting failures
/// We can also swap it out for alternative implementations in the future
/// I tried using redis-rs Connection/ConnectionLike traits but honestly things just got really
/// awkward to work with.

#[async_trait]
pub trait Client {
    // A very simplified wrapper, but works for our usage
    async fn zrangebyscore(&self, k: String, min: String, max: String) -> Result<Vec<String>>;
}

pub struct RedisClient {
    client: redis::Client,
}

impl RedisClient {
    pub fn new(addr: String) -> Result<RedisClient> {
        let client = redis::Client::open(addr)?;

        Ok(RedisClient { client })
    }
}

#[async_trait]
impl Client for RedisClient {
    async fn zrangebyscore(&self, k: String, min: String, max: String) -> Result<Vec<String>> {
        let mut conn = self.client.get_async_connection().await?;

        let results = conn.zrangebyscore(k, min, max);
        let fut = timeout(Duration::from_secs(REDIS_TIMEOUT_MILLISECS), results).await?;

        Ok(fut?)
    }
}

// mockall got really annoying with async and results so I'm just gonna do my own
#[derive(Clone)]
pub struct MockRedisClient {
    zrangebyscore_ret: HashMap<String, Vec<String>>,
}

impl MockRedisClient {
    pub fn new() -> MockRedisClient {
        MockRedisClient {
            zrangebyscore_ret: HashMap::new(),
        }
    }

    pub fn zrangebyscore_ret(&mut self, key: &str, ret: Vec<String>) -> Self {
        self.zrangebyscore_ret.insert(key.to_owned(), ret);
        self.clone()
    }
}

impl Default for MockRedisClient {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Client for MockRedisClient {
    // A very simplified wrapper, but works for our usage
    async fn zrangebyscore(&self, key: String, _min: String, _max: String) -> Result<Vec<String>> {
        match self.zrangebyscore_ret.get(&key) {
            Some(val) => Ok(val.clone()),
            None => Err(anyhow!("unknown key")),
        }
    }
}
