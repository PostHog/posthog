use std::{sync::Arc, time::Duration};

use common_redis::{Client as RedisClientTrait, RedisClient};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RedisBackedStateConfig {
    pub issue_buckets_redis_url: String,
    pub redis_response_timeout_ms: u64,
    pub redis_connection_timeout_ms: u64,
}

impl RedisBackedStateConfig {
    fn response_timeout(&self) -> Option<Duration> {
        duration_from_millis(self.redis_response_timeout_ms)
    }

    fn connection_timeout(&self) -> Option<Duration> {
        duration_from_millis(self.redis_connection_timeout_ms)
    }
}

pub async fn new_issue_buckets_redis_client(
    config: &RedisBackedStateConfig,
) -> Result<Arc<dyn RedisClientTrait + Send + Sync>, common_redis::CustomRedisError> {
    let client = RedisClient::with_config(
        config.issue_buckets_redis_url.clone(),
        common_redis::CompressionConfig::disabled(),
        common_redis::RedisValueFormat::default(),
        config.response_timeout(),
        config.connection_timeout(),
    )
    .await?;

    Ok(Arc::new(client))
}

fn duration_from_millis(milliseconds: u64) -> Option<Duration> {
    if milliseconds == 0 {
        return None;
    }

    Some(Duration::from_millis(milliseconds))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zero_redis_timeouts_disable_timeouts() {
        let config = RedisBackedStateConfig {
            issue_buckets_redis_url: "redis://localhost:6379/".to_string(),
            redis_response_timeout_ms: 0,
            redis_connection_timeout_ms: 0,
        };

        assert_eq!(config.response_timeout(), None);
        assert_eq!(config.connection_timeout(), None);
    }

    #[test]
    fn non_zero_redis_timeouts_are_preserved() {
        let config = RedisBackedStateConfig {
            issue_buckets_redis_url: "redis://localhost:6379/".to_string(),
            redis_response_timeout_ms: 100,
            redis_connection_timeout_ms: 250,
        };

        assert_eq!(config.response_timeout(), Some(Duration::from_millis(100)));
        assert_eq!(
            config.connection_timeout(),
            Some(Duration::from_millis(250))
        );
    }
}
