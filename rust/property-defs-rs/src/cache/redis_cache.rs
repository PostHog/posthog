use crate::types::Update;
use crate::errors::CacheError;
use redis::RedisError;
use futures::Stream;
use std::pin::Pin;
use tracing::warn;
use super::CacheOperations;

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

        self.client.set_keys(&key_value_pairs, self.ttl).await.map_err(CacheError::from)
    }

    async fn filter_cached_updates(&self, mut updates: Vec<Update>) -> Pin<Box<dyn Stream<Item = Update> + Send + '_>> {
        Box::pin(async_stream::stream! {
            if updates.is_empty() {
                return;
            }

            let to_check_len = if self.batch_fetch_limit > 0 {
                std::cmp::min(updates.len(), self.batch_fetch_limit)
            } else {
                updates.len()
            };

            // First drain and yield updates that won't be checked against Redis
            if to_check_len < updates.len() {
                for update in updates.drain(to_check_len..) {
                    yield update;
                }
            }

            // Now check remaining updates against Redis
            let redis_keys: Vec<String> = updates.iter().map(|u| u.key()).collect();
            if !redis_keys.is_empty() {
                match self.client.get_keys(&redis_keys).await {
                    Ok(values) => {
                        for (update, value) in updates.drain(..).zip(values.iter()) {
                            if value.is_none() {
                                yield update;
                            }
                        }
                    }
                    Err(e) => {
                        warn!("Failed to check Redis cache: {}", e);
                        // On error, treat all updates as not in cache
                        for update in updates.drain(..) {
                            yield update;
                        }
                    }
                }
            }
        })
    }
}
