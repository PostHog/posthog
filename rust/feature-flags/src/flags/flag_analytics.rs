use crate::flags::flag_request::FlagRequestType;
use crate::handler::types::Library;
use anyhow::Result;
use common_redis::{Client as RedisClient, CustomRedisError};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

pub const SURVEY_TARGETING_FLAG_PREFIX: &str = "survey-targeting-";
pub const PRODUCT_TOUR_TARGETING_FLAG_PREFIX: &str = "product-tour-targeting-";

const CACHE_BUCKET_SIZE: u64 = 60 * 2; // duration in seconds

pub fn get_team_request_key(team_id: i32, request_type: FlagRequestType) -> String {
    match request_type {
        FlagRequestType::Decide => format!("posthog:decide_requests:{team_id}"),
        FlagRequestType::FlagDefinitions => {
            format!("posthog:local_evaluation_requests:{team_id}")
        }
    }
}

pub fn get_team_request_library_key(
    team_id: i32,
    request_type: FlagRequestType,
    library: Library,
) -> String {
    match request_type {
        FlagRequestType::Decide => {
            format!("posthog:decide_requests:sdk:{team_id}:{library}")
        }
        FlagRequestType::FlagDefinitions => {
            format!("posthog:local_evaluation_requests:sdk:{team_id}:{library}")
        }
    }
}

pub async fn increment_request_count(
    redis_client: Arc<dyn RedisClient + Send + Sync>,
    team_id: i32,
    count: i32,
    request_type: FlagRequestType,
    library: Option<Library>,
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

    if let Some(lib) = library {
        let library_key = get_team_request_library_key(team_id, request_type, lib);
        redis_client
            .hincrby(library_key, time_bucket.to_string(), Some(count))
            .await?;
    }

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
            get_team_request_key(456, FlagRequestType::FlagDefinitions),
            "posthog:local_evaluation_requests:456"
        );
    }

    #[tokio::test]
    async fn test_get_team_request_library_key() {
        assert_eq!(
            get_team_request_library_key(123, FlagRequestType::Decide, Library::PosthogNode),
            "posthog:decide_requests:sdk:123:posthog-node"
        );
        assert_eq!(
            get_team_request_library_key(456, FlagRequestType::FlagDefinitions, Library::PosthogJs),
            "posthog:local_evaluation_requests:sdk:456:posthog-js"
        );
        assert_eq!(
            get_team_request_library_key(789, FlagRequestType::Decide, Library::PosthogAndroid),
            "posthog:decide_requests:sdk:789:posthog-android"
        );
    }

    #[tokio::test]
    async fn test_increment_request_count() {
        let redis_client = setup_redis_client(None).await;

        let team_id = 789;
        let count = 5;

        let decide_key = get_team_request_key(team_id, FlagRequestType::Decide);
        let flag_definitions_key = get_team_request_key(team_id, FlagRequestType::FlagDefinitions);

        // Clean up Redis before the test to ensure no leftover data
        redis_client.del(decide_key.clone()).await.unwrap();
        redis_client
            .del(flag_definitions_key.clone())
            .await
            .unwrap();

        // Test for Decide request type
        increment_request_count(
            redis_client.clone(),
            team_id,
            count,
            FlagRequestType::Decide,
            None,
        )
        .await
        .unwrap();

        // Test for FlagDefinitions request type
        increment_request_count(
            redis_client.clone(),
            team_id,
            count,
            FlagRequestType::FlagDefinitions,
            None,
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
        let flag_definitions_count: i32 = redis_client
            .hget(flag_definitions_key.clone(), time_bucket.to_string())
            .await
            .unwrap()
            .parse()
            .unwrap();

        assert_eq!(decide_count, count);
        assert_eq!(flag_definitions_count, count);

        // Clean up Redis after the test
        redis_client.del(decide_key).await.unwrap();
        redis_client.del(flag_definitions_key).await.unwrap();
    }

    #[tokio::test]
    async fn test_increment_request_count_with_sdk() {
        let redis_client = setup_redis_client(None).await;

        let team_id = 999;
        let count = 10;

        let decide_key = get_team_request_key(team_id, FlagRequestType::Decide);
        let library_key =
            get_team_request_library_key(team_id, FlagRequestType::Decide, Library::PosthogNode);

        redis_client.del(decide_key.clone()).await.unwrap();
        redis_client.del(library_key.clone()).await.unwrap();

        increment_request_count(
            redis_client.clone(),
            team_id,
            count,
            FlagRequestType::Decide,
            Some(Library::PosthogNode),
        )
        .await
        .unwrap();

        let time_bucket = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
            / CACHE_BUCKET_SIZE;

        let decide_count: i32 = redis_client
            .hget(decide_key.clone(), time_bucket.to_string())
            .await
            .unwrap()
            .parse()
            .unwrap();
        let library_count: i32 = redis_client
            .hget(library_key.clone(), time_bucket.to_string())
            .await
            .unwrap()
            .parse()
            .unwrap();

        assert_eq!(decide_count, count);
        assert_eq!(library_count, count);

        redis_client.del(decide_key).await.unwrap();
        redis_client.del(library_key).await.unwrap();
    }

    #[tokio::test]
    async fn test_increment_request_count_without_library() {
        let redis_client = setup_redis_client(None).await;

        let team_id = 888;
        let count = 7;

        let decide_key = get_team_request_key(team_id, FlagRequestType::Decide);

        redis_client.del(decide_key.clone()).await.unwrap();

        increment_request_count(
            redis_client.clone(),
            team_id,
            count,
            FlagRequestType::Decide,
            None,
        )
        .await
        .unwrap();

        let time_bucket = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
            / CACHE_BUCKET_SIZE;

        let decide_count: i32 = redis_client
            .hget(decide_key.clone(), time_bucket.to_string())
            .await
            .unwrap()
            .parse()
            .unwrap();

        assert_eq!(decide_count, count);

        redis_client.del(decide_key).await.unwrap();
    }

    #[tokio::test]
    async fn test_multiple_libraries_same_team() {
        let redis_client = setup_redis_client(None).await;

        let team_id = 777;
        let count = 3;

        let decide_key = get_team_request_key(team_id, FlagRequestType::Decide);
        let js_key =
            get_team_request_library_key(team_id, FlagRequestType::Decide, Library::PosthogJs);
        let node_key =
            get_team_request_library_key(team_id, FlagRequestType::Decide, Library::PosthogNode);

        redis_client.del(decide_key.clone()).await.unwrap();
        redis_client.del(js_key.clone()).await.unwrap();
        redis_client.del(node_key.clone()).await.unwrap();

        increment_request_count(
            redis_client.clone(),
            team_id,
            count,
            FlagRequestType::Decide,
            Some(Library::PosthogJs),
        )
        .await
        .unwrap();

        increment_request_count(
            redis_client.clone(),
            team_id,
            count,
            FlagRequestType::Decide,
            Some(Library::PosthogNode),
        )
        .await
        .unwrap();

        let time_bucket = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
            / CACHE_BUCKET_SIZE;

        let decide_count: i32 = redis_client
            .hget(decide_key.clone(), time_bucket.to_string())
            .await
            .unwrap()
            .parse()
            .unwrap();
        let js_count: i32 = redis_client
            .hget(js_key.clone(), time_bucket.to_string())
            .await
            .unwrap()
            .parse()
            .unwrap();
        let node_count: i32 = redis_client
            .hget(node_key.clone(), time_bucket.to_string())
            .await
            .unwrap()
            .parse()
            .unwrap();

        assert_eq!(decide_count, count * 2);
        assert_eq!(js_count, count);
        assert_eq!(node_count, count);

        redis_client.del(decide_key).await.unwrap();
        redis_client.del(js_key).await.unwrap();
        redis_client.del(node_key).await.unwrap();
    }
}
