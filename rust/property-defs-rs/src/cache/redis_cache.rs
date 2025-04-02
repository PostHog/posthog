use crate::types::Update;
use super::secondary_cache::SecondaryCache;
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
impl SecondaryCache for RedisCache {
    async fn insert_batch(&self, updates: &[Update]) -> Result<(), RedisError> {
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
        let _: () = pipe.query_async(&mut conn).await?;
        Ok(())
    }

    async fn get_batch(&self, updates: &[Update]) -> Result<Vec<Update>, RedisError> {
        if updates.is_empty() {
            return Ok(Vec::new());
        }

        let mut conn = self.conn.clone();
        let redis_keys: Vec<String> = updates.iter().map(|u| u.key()).collect();
        let values: Vec<Option<String>> = redis::cmd("MGET")
            .arg(&redis_keys)
            .query_async(&mut conn)
            .await?;

        Ok(values
            .into_iter()
            .filter_map(|opt_str| {
                opt_str.and_then(|s| serde_json::from_str(&s).ok())
            })
            .collect())
    }
}
