use crate::types::Update;
use crate::errors::CacheError;
use super::CacheOperations;
use redis::RedisError;

#[derive(Clone)]
pub struct RedisCache {
    conn: redis::aio::ConnectionManager,
    ttl: u64,
}

impl RedisCache {
    pub async fn new(client: redis::Client, ttl: u64) -> Result<Self, RedisError> {
        let conn = redis::aio::ConnectionManager::new(client).await?;
        Ok(Self { conn, ttl })
    }
}

#[async_trait::async_trait]
impl CacheOperations for RedisCache {
    async fn insert_batch(&self, updates: &[Update]) -> Result<(), CacheError> {
        if updates.is_empty() {
            return Ok(());
        }

        let mut pipe = redis::pipe();
        for update in updates {
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

        let mut conn = self.conn.clone();
        let redis_keys: Vec<String> = updates.iter().map(|u| u.key()).collect();
        let values: Vec<Option<String>> = redis::cmd("MGET")
            .arg(&redis_keys)
            .query_async(&mut conn)
            .await
            .map_err(CacheError::from)?;

        let mut not_in_cache = Vec::new();
        for (update, value) in updates.iter().zip(values.iter()) {
            if value.is_none() {
                not_in_cache.push(update.clone());
            }
        }

        Ok(not_in_cache)
    }
}
