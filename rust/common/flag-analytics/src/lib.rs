mod constants;

use common_redis::{Client as RedisClient, CustomRedisError};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

pub use constants::{CACHE_BUCKET_SIZE, SURVEY_TARGETING_FLAG_PREFIX};

/// Type of flag request for analytics tracking
#[derive(Debug, Clone, Copy)]
pub enum FlagRequestType {
    Decide,
    LocalEvaluation,
}

/// Get the Redis key for tracking team requests
pub fn get_team_request_key(team_id: i32, request_type: FlagRequestType) -> String {
    match request_type {
        FlagRequestType::Decide => format!("posthog:decide_requests:{}", team_id),
        FlagRequestType::LocalEvaluation => {
            format!("posthog:local_evaluation_requests:{}", team_id)
        }
    }
}

/// Increment the request count for a team in Redis
/// This is used for billing and usage analytics
///
/// # Arguments
/// * `redis_client` - Redis client for storing the count
/// * `team_id` - The team ID to track usage for
/// * `count` - The number to increment by
/// * `request_type` - The type of request (Decide or LocalEvaluation)
///
/// # Returns
/// * `Ok(())` if the increment was successful
/// * `Err(CustomRedisError)` if there was a Redis error
pub async fn increment_request_count(
    redis_client: Arc<dyn RedisClient + Send + Sync>,
    team_id: i32,
    count: i32,
    request_type: FlagRequestType,
) -> Result<(), CustomRedisError> {
    // Calculate the current time bucket (2-minute intervals)
    let time_bucket = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("System time should be after UNIX epoch")
        .as_secs()
        / CACHE_BUCKET_SIZE;

    let key_name = get_team_request_key(team_id, request_type);

    // Increment the count in Redis hash
    // The hash structure is: key -> { time_bucket -> count }
    redis_client
        .hincrby(key_name, time_bucket.to_string(), Some(count))
        .await?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_team_request_key() {
        assert_eq!(
            get_team_request_key(123, FlagRequestType::Decide),
            "posthog:decide_requests:123"
        );
        assert_eq!(
            get_team_request_key(456, FlagRequestType::LocalEvaluation),
            "posthog:local_evaluation_requests:456"
        );
    }

    // Note: Full integration tests with Redis are in the service-specific test suites
    // since they require Redis setup specific to each service
}
