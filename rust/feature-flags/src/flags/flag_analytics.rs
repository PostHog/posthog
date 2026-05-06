use crate::flags::flag_request::FlagRequestType;
use crate::handler::types::Library;
use anyhow::Result;
use common_redis::{Client as RedisClient, CustomRedisError, PipelineCommand};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

pub const SURVEY_TARGETING_FLAG_PREFIX: &str = "survey-targeting-";
pub const PRODUCT_TOUR_TARGETING_FLAG_PREFIX: &str = "product-tour-targeting-";

pub fn is_billable_flag_key(key: &str) -> bool {
    !key.starts_with(SURVEY_TARGETING_FLAG_PREFIX)
        && !key.starts_with(PRODUCT_TOUR_TARGETING_FLAG_PREFIX)
}

pub const CACHE_BUCKET_SIZE: u64 = 60 * 2; // duration in seconds

/// Current 2-minute bucket, expressed as `unix_seconds / CACHE_BUCKET_SIZE`.
pub fn current_bucket() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() / CACHE_BUCKET_SIZE)
        .unwrap_or(0)
}

pub fn get_team_request_key(team_id: i32, request_type: FlagRequestType) -> String {
    match request_type {
        FlagRequestType::Decide => format!("posthog:decide_requests:{team_id}"),
        FlagRequestType::FlagDefinitions => format!("posthog:local_evaluation_requests:{team_id}"),
    }
}

pub fn get_team_request_library_key(
    team_id: i32,
    request_type: FlagRequestType,
    library: Library,
) -> String {
    match request_type {
        FlagRequestType::Decide => format!("posthog:decide_requests:sdk:{team_id}:{library}"),
        FlagRequestType::FlagDefinitions => {
            format!("posthog:local_evaluation_requests:sdk:{team_id}:{library}")
        }
    }
}

/// Suffix appended to a production key to obtain its shadow-keyspace mirror.
/// The `BillingAggregator` writes to shadow keys so its counts can be
/// reconciled against the authoritative synchronous path without affecting
/// billing.
pub const SHADOW_KEY_SUFFIX: &str = ":shadow";

pub fn get_team_request_shadow_key(team_id: i32, request_type: FlagRequestType) -> String {
    format!(
        "{}{SHADOW_KEY_SUFFIX}",
        get_team_request_key(team_id, request_type)
    )
}

pub fn get_team_request_library_shadow_key(
    team_id: i32,
    request_type: FlagRequestType,
    library: Library,
) -> String {
    format!(
        "{}{SHADOW_KEY_SUFFIX}",
        get_team_request_library_key(team_id, request_type, library)
    )
}

/// Synchronous, per-request HINCRBY into the production billing keyspace.
/// This is the authoritative billing write — see `crate::billing` for the
/// dual-write contract.
pub async fn increment_request_count(
    redis_client: Arc<dyn RedisClient + Send + Sync>,
    team_id: i32,
    count: i64,
    request_type: FlagRequestType,
    library: Option<Library>,
) -> Result<(), CustomRedisError> {
    let time_bucket_str = current_bucket().to_string();
    let key_name = get_team_request_key(team_id, request_type);

    // Build pipeline commands for a single Redis round-trip
    let mut commands = vec![PipelineCommand::HIncrBy {
        key: key_name,
        field: time_bucket_str.clone(),
        count,
    }];

    if let Some(lib) = library {
        let library_key = get_team_request_library_key(team_id, request_type, lib);
        commands.push(PipelineCommand::HIncrBy {
            key: library_key,
            field: time_bucket_str,
            count,
        });
    }

    // Execute all commands in a single round-trip
    redis_client.execute_pipeline(commands).await?;

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
        // Test new SDK variants
        assert_eq!(
            get_team_request_library_key(100, FlagRequestType::Decide, Library::PosthogDotnet),
            "posthog:decide_requests:sdk:100:posthog-dotnet"
        );
        assert_eq!(
            get_team_request_library_key(
                101,
                FlagRequestType::FlagDefinitions,
                Library::PosthogElixir
            ),
            "posthog:local_evaluation_requests:sdk:101:posthog-elixir"
        );
        // Test Other variant
        assert_eq!(
            get_team_request_library_key(102, FlagRequestType::Decide, Library::Other),
            "posthog:decide_requests:sdk:102:other"
        );
    }

    #[test]
    fn test_get_team_request_shadow_key() {
        assert_eq!(
            get_team_request_shadow_key(123, FlagRequestType::Decide),
            "posthog:decide_requests:123:shadow"
        );
        assert_eq!(
            get_team_request_shadow_key(456, FlagRequestType::FlagDefinitions),
            "posthog:local_evaluation_requests:456:shadow"
        );
    }

    #[test]
    fn test_get_team_request_library_shadow_key() {
        assert_eq!(
            get_team_request_library_shadow_key(123, FlagRequestType::Decide, Library::PosthogNode),
            "posthog:decide_requests:sdk:123:posthog-node:shadow"
        );
        assert_eq!(
            get_team_request_library_shadow_key(
                456,
                FlagRequestType::FlagDefinitions,
                Library::PosthogJs
            ),
            "posthog:local_evaluation_requests:sdk:456:posthog-js:shadow"
        );
    }

    #[test]
    fn test_shadow_keys_never_collide_with_production_keys() {
        // The reconciliation strategy depends on the two keyspaces being
        // disjoint — a shared key would corrupt the production count.
        for team_id in [1, 100_000, i32::MAX] {
            for rt in [FlagRequestType::Decide, FlagRequestType::FlagDefinitions] {
                assert_ne!(
                    get_team_request_key(team_id, rt),
                    get_team_request_shadow_key(team_id, rt)
                );
                for lib in [Library::PosthogNode, Library::PosthogJs, Library::Other] {
                    assert_ne!(
                        get_team_request_library_key(team_id, rt, lib),
                        get_team_request_library_shadow_key(team_id, rt, lib)
                    );
                }
            }
        }
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
        let decide_count: i64 = redis_client
            .hget(decide_key.clone(), time_bucket.to_string())
            .await
            .unwrap()
            .parse()
            .unwrap();
        let flag_definitions_count: i64 = redis_client
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

        let decide_count: i64 = redis_client
            .hget(decide_key.clone(), time_bucket.to_string())
            .await
            .unwrap()
            .parse()
            .unwrap();
        let library_count: i64 = redis_client
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
        // Use a sample library key to verify it doesn't get created
        let library_key =
            get_team_request_library_key(team_id, FlagRequestType::Decide, Library::PosthogNode);

        redis_client.del(decide_key.clone()).await.unwrap();
        redis_client.del(library_key.clone()).await.unwrap();

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

        let decide_count: i64 = redis_client
            .hget(decide_key.clone(), time_bucket.to_string())
            .await
            .unwrap()
            .parse()
            .unwrap();

        assert_eq!(decide_count, count);

        // Verify no library key was created when None was passed
        // hget returns empty string for non-existent keys in this implementation
        let library_value: String = redis_client
            .hget(library_key.clone(), time_bucket.to_string())
            .await
            .unwrap_or_default();
        assert!(
            library_value.is_empty(),
            "Library key should not exist when None is passed"
        );

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

        let decide_count: i64 = redis_client
            .hget(decide_key.clone(), time_bucket.to_string())
            .await
            .unwrap()
            .parse()
            .unwrap();
        let js_count: i64 = redis_client
            .hget(js_key.clone(), time_bucket.to_string())
            .await
            .unwrap()
            .parse()
            .unwrap();
        let node_count: i64 = redis_client
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
