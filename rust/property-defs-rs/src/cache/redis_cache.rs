use crate::types::Update;
use crate::errors::CacheError;
use redis::RedisError;
use tracing::warn;
use super::CacheOperations;

#[async_trait::async_trait]
pub trait RedisClientOperations {
    async fn get_keys(&self, keys: &[String]) -> Result<Vec<Option<String>>, RedisError>;
    async fn set_keys(&self, updates: &[(String, String)], ttl: u64) -> Result<(), RedisError>;
}

#[derive(Clone)]
pub struct RedisCacheClient {
    conn: redis::aio::ConnectionManager,
}

impl RedisCacheClient {
    async fn new(client: redis::Client) -> Result<Self, RedisError> {
        let conn = redis::aio::ConnectionManager::new(client).await?;
        Ok(Self {
            conn,
        })
    }
}

#[async_trait::async_trait]
impl RedisClientOperations for RedisCacheClient {
    async fn get_keys(&self, keys: &[String]) -> Result<Vec<Option<String>>, RedisError> {
        let mut conn = self.conn.clone();
        redis::cmd("MGET")
            .arg(keys)
            .query_async(&mut conn)
            .await
    }

    async fn set_keys(&self, updates: &[(String, String)], ttl: u64) -> Result<(), RedisError> {
        if updates.is_empty() {
            return Ok(());
        }

        let mut pipe = redis::pipe();
        for (key, value) in updates {
            pipe.set_ex(key, value, ttl);
        }

        let mut conn = self.conn.clone();
        let _: () = pipe.query_async(&mut conn).await?;
        Ok(())
    }
}

#[derive(Clone)]
pub struct RedisCache<T: RedisClientOperations + Clone = RedisCacheClient> {
    client: T,
    ttl: u64,
    batch_fetch_limit: usize,
    batch_update_limit: usize,
}

impl<T: RedisClientOperations + Clone> RedisCache<T> {
    pub fn new(client: T, ttl: u64, batch_fetch_limit: usize, batch_update_limit: usize) -> Self {
        Self {
            client,
            ttl,
            batch_fetch_limit,
            batch_update_limit,
        }
    }
}

// Add a constructor specifically for RedisCacheClient since it needs async initialization
impl RedisCache<RedisCacheClient> {
    pub async fn new_redis(client: redis::Client, ttl: u64, batch_fetch_limit: usize, batch_update_limit: usize) -> Result<Self, RedisError> {
        let redis_client = RedisCacheClient::new(client).await?;
        Ok(Self::new(redis_client, ttl, batch_fetch_limit, batch_update_limit))
    }
}

#[async_trait::async_trait]
impl<T: RedisClientOperations + Clone + Send + Sync> CacheOperations for RedisCache<T> {
    async fn insert_batch(&self, updates: &[Update]) -> Result<(), CacheError> {
        if updates.is_empty() {
            return Ok(());
        }

        let updates_to_process = if self.batch_update_limit > 0 {
            &updates[..std::cmp::min(updates.len(), self.batch_update_limit)]
        } else {
            updates
        };

        let key_value_pairs: Vec<(String, String)> = updates_to_process
            .iter()
            .map(|update| (update.key(), String::new()))
            .collect();

        self.client.set_keys(&key_value_pairs, self.ttl).await.map_err(CacheError::from)
    }

    async fn filter_cached_updates(&self, mut updates: Vec<Update>) -> Vec<Update> {
        if updates.is_empty() {
            return updates;
        }

        let to_check_len = if self.batch_fetch_limit > 0 {
            std::cmp::min(updates.len(), self.batch_fetch_limit)
        } else {
            updates.len()
        };

        // Split off the last batch_fetch_limit elements to check with Redis
        let to_check = updates.split_off(updates.len() - to_check_len);

        // Check the last elements against Redis
        let redis_keys: Vec<String> = to_check.iter().map(|u| u.key()).collect();
        if !redis_keys.is_empty() {
            match self.client.get_keys(&redis_keys).await {
                Ok(values) => {
                    for (update, value) in to_check.into_iter().zip(values.iter()) {
                        if value.is_none() {
                            updates.push(update);
                        }
                    }
                }
                Err(e) => {
                    warn!("Failed to check Redis cache: {}", e);
                    // On error, treat all updates as not in cache
                    updates.extend(to_check);
                }
            }
        }

        updates
    }
}
