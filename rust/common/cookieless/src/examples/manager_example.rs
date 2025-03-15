use std::sync::Arc;

use common_redis::MockRedisClient;

use crate::{CookielessConfig, CookielessManager, HashParams};

/// Example of how to use the CookielessManager
pub async fn manager_example() -> Result<(), Box<dyn std::error::Error>> {
    // Create a mock Redis client
    let mut mock_redis = MockRedisClient::new();

    // Set up the mock Redis client to return a salt
    let today = chrono::Utc::now().format("%Y-%m-%d").to_string();
    let redis_key = format!("cookieless_salt:{}", today);
    let salt_base64 = "AAAAAAAAAAAAAAAAAAAAAA=="; // 16 bytes of zeros
    mock_redis = mock_redis.get_ret(&redis_key, Ok(salt_base64.to_string()));

    // Create a Redis client
    let redis_client = Arc::new(mock_redis);

    // Create a CookielessManager with default config
    let config = CookielessConfig::default();
    let manager = CookielessManager::new(config, redis_client);

    // Get a hash for a specific day
    let timestamp_ms = chrono::Utc::now().timestamp_millis() as u64;
    let hash = manager
        .do_hash_for_day(HashParams {
            timestamp_ms,
            event_time_zone: Some("Europe/London"),
            team_time_zone: "UTC",
            team_id: 42,
            ip: "127.0.0.1",
            host: "example.com",
            user_agent: "Mozilla/5.0",
            n: 0,
            hash_extra: "",
        })
        .await?;

    // Convert the hash to a distinct ID
    let distinct_id = CookielessManager::hash_to_distinct_id(&hash);
    println!("Distinct ID: {}", distinct_id);

    Ok(())
}
