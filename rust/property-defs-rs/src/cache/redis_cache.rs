use redis::Client;
use crate::types::Update;
use super::secondary_cache::SecondaryCache;

pub struct RedisCache {
    client: Client,
    ttl: u64,
}

impl RedisCache {
    pub fn new(redis_url: &str, ttl: u64) -> Result<Self, redis::RedisError> {
        let client = Client::open(redis_url)?;
        Ok(Self { client, ttl })
    }
}

impl SecondaryCache for RedisCache {
    fn insert_batch(&self, updates: &[Update]) -> Result<(), redis::RedisError> {
        if updates.is_empty() {
            return Ok(());
        }

        let mut conn = self.client.get_connection()?;
        let mut pipe = redis::pipe();

        for update in updates {
            let key = update.key();
            pipe.set_ex(
                key,
                serde_json::to_string(&update).unwrap_or_default(),
                self.ttl,
            );
        }

        let _: () = pipe.query(&mut conn)?;
        Ok(())
    }

    fn get_batch(&self, updates: &[Update]) -> Result<Vec<Update>, redis::RedisError> {
        if updates.is_empty() {
            return Ok(Vec::new());
        }

        let mut conn = self.client.get_connection()?;
        let redis_keys: Vec<String> = updates.iter().map(|u| u.key()).collect();
        let values: Vec<Option<String>> = redis::cmd("MGET").arg(&redis_keys).query(&mut conn)?;

        Ok(values
            .into_iter()
            .filter_map(|opt_str| {
                opt_str.and_then(|s| serde_json::from_str(&s).ok())
            })
            .collect())
    }
}
