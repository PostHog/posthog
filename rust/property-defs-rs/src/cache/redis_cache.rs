use crate::types::Update;
use crate::errors::CacheError;
use super::CacheOperations;
use redis::RedisError;

#[derive(Clone)]
pub struct RedisCache {
    conn: redis::aio::ConnectionManager,
    ttl: u64,
    batch_fetch_limit: usize,
    batch_update_limit: usize,
}

impl RedisCache {
    pub async fn new(client: redis::Client, ttl: u64, batch_fetch_limit: usize, batch_update_limit: usize) -> Result<Self, RedisError> {
        let conn = redis::aio::ConnectionManager::new(client).await?;
        Ok(Self {
            conn,
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

        let mut pipe = redis::pipe();
        for update in updates_to_process {
            let key = update.key();
            pipe.set_ex(
                key,
                serde_json::to_string(&update).unwrap_or_default(),
                self.ttl,
            );
        }

        let mut conn = self.conn.clone();
        let _: () = pipe.query_async(&mut conn).await.map_err(CacheError::from)?;
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

        let mut conn = self.conn.clone();
        let redis_keys: Vec<String> = updates_to_check.iter().map(|u| u.key()).collect();
        let values: Vec<Option<String>> = redis::cmd("MGET")
            .arg(&redis_keys)
            .query_async(&mut conn)
            .await
            .map_err(CacheError::from)?;

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
