use crate::flags::flag_request::FlagRequestType;
use anyhow::Result;
use common_redis::{Client as RedisClient, CustomRedisError};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

pub const SURVEY_TARGETING_FLAG_PREFIX: &str = "survey-targeting-";
const CACHE_BUCKET_SIZE: u64 = 60 * 2; // duration in seconds

pub fn get_team_request_key(team_id: i32, request_type: FlagRequestType) -> String {
    match request_type {
        FlagRequestType::Decide => format!("posthog:decide_requests:{team_id}"),
        FlagRequestType::LocalEvaluation => {
            format!("posthog:local_evaluation_requests:{team_id}")
        }
    }
}

pub async fn increment_request_count(
    redis_client: Arc<dyn RedisClient + Send + Sync>,
    team_id: i32,
    count: i32,
    request_type: FlagRequestType,
) -> Result<(), CustomRedisError> {
    let time_bucket = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
        / CACHE_BUCKET_SIZE;
    let key_name = get_team_request_key(team_id, request_type);
    redis_client
        .hincrby(key_name, time_bucket.to_string(), Some(count))
        .await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::test_utils::setup_redis_client;

    #[tokio::test]
    async fn test_get_team_request_key() {
        assert_eq!(
            get_team_request_key(123, FlagRequestType::Decide),
            "posthog:decide_requests:123"
        );
        assert_eq!(
            get_team_request_key(456, FlagRequestType::LocalEvaluation),
            "posthog:local_evaluation_requests:456"
        );
    }

    #[tokio::test]
    async fn test_increment_request_count() {
        let redis_client = setup_redis_client(None).await;

        let team_id = 789;
        let count = 5;

        let decide_key = get_team_request_key(team_id, FlagRequestType::Decide);
        let local_eval_key = get_team_request_key(team_id, FlagRequestType::LocalEvaluation);

        // Clean up Redis before the test to ensure no leftover data
        redis_client.del(decide_key.clone()).await.unwrap();
        redis_client.del(local_eval_key.clone()).await.unwrap();

        // Test for Decide request type
        increment_request_count(
            redis_client.clone(),
            team_id,
            count,
            FlagRequestType::Decide,
        )
        .await
        .unwrap();

        // Test for LocalEvaluation request type
        increment_request_count(
            redis_client.clone(),
            team_id,
            count,
            FlagRequestType::LocalEvaluation,
        )
        .await
        .unwrap();

        // Get the current time bucket
        let time_bucket = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
            / CACHE_BUCKET_SIZE;

        // Verify the counts in Redis
        let decide_count: i32 = redis_client
            .hget(decide_key.clone(), time_bucket.to_string())
            .await
            .unwrap()
            .parse()
            .unwrap();
        let local_eval_count: i32 = redis_client
            .hget(local_eval_key.clone(), time_bucket.to_string())
            .await
            .unwrap()
            .parse()
            .unwrap();

        assert_eq!(decide_count, count);
        assert_eq!(local_eval_count, count);

        // Clean up Redis after the test
        redis_client.del(decide_key).await.unwrap();
        redis_client.del(local_eval_key).await.unwrap();
    }
}
