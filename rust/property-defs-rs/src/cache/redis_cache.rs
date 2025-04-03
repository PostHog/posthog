use crate::types::Update;
use crate::errors::CacheError;
use super::CacheOperations;
use redis::RedisError;

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
pub struct RedisCache {
    client: RedisCacheClient,
    ttl: u64,
    batch_fetch_limit: usize,
    batch_update_limit: usize,
}

impl RedisCache {
    pub async fn new(client: redis::Client, ttl: u64, batch_fetch_limit: usize, batch_update_limit: usize) -> Result<Self, RedisError> {
        let redis_client = RedisCacheClient::new(client).await?;
        Ok(Self {
            client: redis_client,
            ttl,
            batch_fetch_limit,
            batch_update_limit,
        })
    }
}

#[async_trait::async_trait]
impl CacheOperations for RedisCache {
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

        self.client.set_keys(&key_value_pairs, self.ttl).await.map_err(CacheError::from)?;
        Ok(())
    }

    async fn filter_cached_updates(&self, updates: &[Update]) -> Result<Vec<Update>, CacheError> {
        if updates.is_empty() {
            return Ok(Vec::new());
        }

        let limit = if self.batch_fetch_limit > 0 {
            std::cmp::min(updates.len(), self.batch_fetch_limit)
        } else {
            updates.len()
        };
        let (updates_to_check, remaining_updates) = updates.split_at(limit);

        let redis_keys: Vec<String> = updates_to_check.iter().map(|u| u.key()).collect();
        let values: Vec<Option<String>> = self.client.get_keys(&redis_keys).await.map_err(CacheError::from)?;

        let mut not_in_cache = Vec::new();
        for (update, value) in updates_to_check.iter().zip(values.iter()) {
            if value.is_none() {
                not_in_cache.push(update.clone());
            }
        }

        // Add all remaining updates that weren't checked
        not_in_cache.extend(remaining_updates.iter().cloned());

        Ok(not_in_cache)
    }
}
