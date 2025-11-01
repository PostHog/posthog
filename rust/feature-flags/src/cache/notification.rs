use common_metrics::inc;
use common_redis::Client as RedisClient;
use once_cell::sync::Lazy;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tracing::{info, warn};

use crate::metrics::consts::{
    FLAG_CACHE_MISS_NOTIFICATION_DROPPED_COUNTER, FLAG_CACHE_MISS_NOTIFICATION_ERROR_COUNTER,
    FLAG_CACHE_MISS_NOTIFICATION_SENT_COUNTER,
};

pub const CACHE_MISS_QUEUE_KEY: &str = "posthog:flag_cache_miss_queue";

// Maximum queue depth before dropping notifications
static MAX_QUEUE_DEPTH: Lazy<u64> = Lazy::new(|| {
    std::env::var("FLAG_CACHE_MISS_MAX_QUEUE_DEPTH")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(10000)
});

#[derive(Debug, Serialize, Deserialize)]
pub struct CacheMissNotification {
    pub team_id: i32,
    pub timestamp: i64,
}

/// Notifies the Django/Celery system about a cache miss by pushing a message to a Redis list.
///
/// This is a fire-and-forget operation that does not block the request. If the notification
/// fails, it logs a warning but does not return an error to avoid failing the entire request.
///
/// # Arguments
///
/// * `redis` - Redis client (should be redis_writer for write operations)
/// * `team_id` - The team ID that experienced the cache miss
///
/// # Returns
///
/// Returns `Ok(())` on success or if notification fails (fire-and-forget pattern)
pub async fn notify_cache_miss(
    redis: Arc<dyn RedisClient + Send + Sync>,
    team_id: i32,
) -> Result<(), Box<dyn std::error::Error>> {
    // Check queue depth to prevent unbounded growth
    let queue_size = redis
        .llen(CACHE_MISS_QUEUE_KEY.to_string())
        .await
        .unwrap_or(0);

    if queue_size >= *MAX_QUEUE_DEPTH {
        warn!(
            team_id = team_id,
            queue_size = queue_size,
            max_depth = *MAX_QUEUE_DEPTH,
            "Cache miss queue overflow, dropping notification"
        );
        inc(FLAG_CACHE_MISS_NOTIFICATION_DROPPED_COUNTER, &[], 1);
        return Ok(());
    }

    let notification = CacheMissNotification {
        team_id,
        timestamp: chrono::Utc::now().timestamp(),
    };

    let message = serde_json::to_string(&notification)?;

    match redis.lpush(CACHE_MISS_QUEUE_KEY.to_string(), message).await {
        Ok(_) => {
            info!(team_id = team_id, "Queued cache rebuild notification");
            inc(FLAG_CACHE_MISS_NOTIFICATION_SENT_COUNTER, &[], 1);
            Ok(())
        }
        Err(e) => {
            warn!(
                team_id = team_id,
                error = %e,
                "Failed to queue cache rebuild notification"
            );
            inc(FLAG_CACHE_MISS_NOTIFICATION_ERROR_COUNTER, &[], 1);
            // Don't fail the request if notification fails
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::MockRedisClient;

    #[tokio::test]
    async fn test_notify_cache_miss_sends_to_redis() {
        let mut mock_redis = MockRedisClient::new();
        mock_redis.llen_ret(CACHE_MISS_QUEUE_KEY, Ok(0)); // Queue is empty
        mock_redis.lpush_ret(CACHE_MISS_QUEUE_KEY, Ok(()));
        let redis = Arc::new(mock_redis.clone());

        let result = notify_cache_miss(redis.clone(), 123).await;

        assert!(result.is_ok());

        let calls = mock_redis.get_calls();
        assert_eq!(calls.len(), 2);
        assert_eq!(calls[0].op, "llen");
        assert_eq!(calls[0].key, CACHE_MISS_QUEUE_KEY);
        assert_eq!(calls[1].op, "lpush");
        assert_eq!(calls[1].key, CACHE_MISS_QUEUE_KEY);
    }

    #[tokio::test]
    async fn test_notify_cache_miss_serializes_notification() {
        let mut mock_redis = MockRedisClient::new();
        mock_redis.llen_ret(CACHE_MISS_QUEUE_KEY, Ok(0)); // Queue is empty
        mock_redis.lpush_ret(CACHE_MISS_QUEUE_KEY, Ok(()));
        let redis = Arc::new(mock_redis.clone());

        notify_cache_miss(redis.clone(), 456).await.unwrap();

        let calls = mock_redis.get_calls();
        let message = match &calls[1].value {
            // calls[1] is lpush, calls[0] is llen
            common_redis::MockRedisValue::String(s) => s,
            _ => panic!("Expected string value"),
        };

        // Verify it's valid JSON
        let parsed: CacheMissNotification = serde_json::from_str(message).unwrap();
        assert_eq!(parsed.team_id, 456);
        assert!(parsed.timestamp > 0);
    }

    #[tokio::test]
    async fn test_notify_cache_miss_handles_redis_failure() {
        let mut mock_redis = MockRedisClient::new();
        mock_redis.llen_ret(CACHE_MISS_QUEUE_KEY, Ok(0)); // Queue is empty
        mock_redis.lpush_ret(
            CACHE_MISS_QUEUE_KEY,
            Err(common_redis::CustomRedisError::Other(
                "Connection failed".to_string(),
            )),
        );
        let redis = Arc::new(mock_redis);

        // Should not fail even if Redis fails (fire-and-forget)
        let result = notify_cache_miss(redis, 789).await;
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_notify_cache_miss_drops_when_queue_full() {
        let mut mock_redis = MockRedisClient::new();
        mock_redis.llen_ret(CACHE_MISS_QUEUE_KEY, Ok(*MAX_QUEUE_DEPTH)); // Queue is at max
        let redis = Arc::new(mock_redis.clone());

        let result = notify_cache_miss(redis.clone(), 999).await;

        assert!(result.is_ok());

        // Should only call llen, not lpush (notification was dropped)
        let calls = mock_redis.get_calls();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].op, "llen");
    }
}
