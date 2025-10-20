use common_hypercache::{CacheSource, HyperCacheConfig, HyperCacheReader, KeyType};
use common_redis::{Client as RedisClientTrait, RedisClient};
use common_types::{TeamId, TeamIdentifier};
use serde_json::Value;
use std::env;
use tokio::time::{sleep, Duration};

#[derive(Debug)]
struct TestTeam {
    id: TeamId,
    token: String,
}

impl TeamIdentifier for TestTeam {
    fn team_id(&self) -> TeamId {
        self.id
    }

    fn api_token(&self) -> &str {
        &self.token
    }
}

struct TestClients {
    hypercache: HyperCacheReader,
    redis_client: RedisClient,
    s3_client: aws_sdk_s3::Client,
    s3_bucket: String,
}

async fn setup_integration_clients() -> anyhow::Result<TestClients> {
    env::set_var("AWS_ACCESS_KEY_ID", "object_storage_root_user");
    env::set_var("AWS_SECRET_ACCESS_KEY", "object_storage_root_password");

    let mut config = HyperCacheConfig::new(
        "integration_test".to_string(),
        "flags".to_string(),
        "us-east-1".to_string(),
        "posthog".to_string(),
    );
    config.s3_endpoint = Some("http://localhost:19000".to_string());

    let redis_client = RedisClient::new("redis://localhost:6379".to_string()).await?;
    let mut aws_config_builder = aws_config::defaults(aws_config::BehaviorVersion::latest())
        .region(aws_config::Region::new(config.s3_region.clone()));

    if let Some(endpoint) = &config.s3_endpoint {
        aws_config_builder = aws_config_builder.endpoint_url(endpoint);
    }

    let aws_config = aws_config_builder.load().await;

    let mut s3_config_builder = aws_sdk_s3::config::Builder::from(&aws_config);
    if config.s3_endpoint.is_some() {
        s3_config_builder = s3_config_builder.force_path_style(true);
    }

    let s3_client = aws_sdk_s3::Client::from_conf(s3_config_builder.build());

    let redis_client_for_cache = RedisClient::new("redis://localhost:6379".to_string()).await?;
    let hypercache =
        HyperCacheReader::new(std::sync::Arc::new(redis_client_for_cache), config.clone()).await?;

    Ok(TestClients {
        hypercache,
        redis_client,
        s3_client,
        s3_bucket: config.s3_bucket,
    })
}

async fn wait_for_services() -> anyhow::Result<()> {
    sleep(Duration::from_millis(100)).await;
    Ok(())
}

/// Set cache data in both Redis and S3
async fn set_cache_value(
    redis_client: &RedisClient,
    s3_client: &aws_sdk_s3::Client,
    s3_bucket: &str,
    redis_cache_key: &str, // Full Redis key with Django prefix
    s3_cache_key: &str,    // S3 key without prefix
    data: &Value,
) -> anyhow::Result<()> {
    let json_str = serde_json::to_string(data)?;

    // Store in Redis using pickle format (Redis client handles the pickling)
    redis_client
        .set(redis_cache_key.to_string(), json_str.clone())
        .await?;
    s3_client
        .put_object()
        .bucket(s3_bucket)
        .key(s3_cache_key)
        .body(json_str.into_bytes().into())
        .send()
        .await
        .map_err(|e| anyhow::anyhow!("Failed to set S3 object: {}", e))?;

    Ok(())
}

/// Clear cache from specific tiers
async fn clear_cache(
    redis_client: &RedisClient,
    s3_client: &aws_sdk_s3::Client,
    s3_bucket: &str,
    redis_cache_key: Option<&str>, // Full Redis key with Django prefix
    s3_cache_key: Option<&str>,    // S3 key without prefix
    kinds: Option<&[&str]>,
) -> anyhow::Result<()> {
    let kinds = kinds.unwrap_or(&["redis", "s3"]);

    if kinds.contains(&"redis") {
        if let Some(redis_key) = redis_cache_key {
            if let Err(e) = redis_client.del(redis_key.to_string()).await {
                tracing::debug!("Redis delete failed (key may not exist): {}", e);
            }
        }
    }

    if kinds.contains(&"s3") {
        if let Some(s3_key) = s3_cache_key {
            if let Err(e) = s3_client
                .delete_object()
                .bucket(s3_bucket)
                .key(s3_key)
                .send()
                .await
            {
                tracing::debug!("S3 delete failed (key may not exist): {}", e);
            }
        }
    }

    Ok(())
}

#[tokio::test]
async fn test_hypercache_redis_s3_fallback() -> anyhow::Result<()> {
    wait_for_services().await?;

    let clients = setup_integration_clients().await?;
    let team_key = "test-team-123";
    let key_type = KeyType::string(team_key);
    let redis_cache_key = clients.hypercache.config().get_redis_cache_key(&key_type);
    let s3_cache_key = clients.hypercache.config().get_s3_cache_key(&key_type);
    let test_data = serde_json::json!({"message": "integration test data"});

    set_cache_value(
        &clients.redis_client,
        &clients.s3_client,
        &clients.s3_bucket,
        &redis_cache_key,
        &s3_cache_key,
        &test_data,
    )
    .await?;

    clear_cache(
        &clients.redis_client,
        &clients.s3_client,
        &clients.s3_bucket,
        Some(&redis_cache_key),
        Some(&s3_cache_key),
        Some(&["redis"]),
    )
    .await?;

    let (result, source) = clients.hypercache.get_with_source(&key_type).await?;

    assert_eq!(result, test_data);
    assert_eq!(source, CacheSource::S3);

    clear_cache(
        &clients.redis_client,
        &clients.s3_client,
        &clients.s3_bucket,
        Some(&redis_cache_key),
        Some(&s3_cache_key),
        None,
    )
    .await?;

    Ok(())
}

#[tokio::test]
async fn test_hypercache_missing_value() -> anyhow::Result<()> {
    wait_for_services().await?;

    let clients = setup_integration_clients().await?;
    let team_key = "test-missing-team";
    let key_type = KeyType::string(team_key);
    let redis_cache_key = clients.hypercache.config().get_redis_cache_key(&key_type);
    let s3_cache_key = clients.hypercache.config().get_s3_cache_key(&key_type);

    clear_cache(
        &clients.redis_client,
        &clients.s3_client,
        &clients.s3_bucket,
        Some(&redis_cache_key),
        Some(&s3_cache_key),
        None,
    )
    .await?;

    let result = clients.hypercache.get_with_source(&key_type).await;

    assert!(result.is_err());

    Ok(())
}

#[tokio::test]
async fn test_hypercache_redis_hit() -> anyhow::Result<()> {
    wait_for_services().await?;

    let clients = setup_integration_clients().await?;
    let team_key = "test-redis-hit-team";
    let key_type = KeyType::string(team_key);
    let redis_cache_key = clients.hypercache.config().get_redis_cache_key(&key_type);
    let s3_cache_key = clients.hypercache.config().get_s3_cache_key(&key_type);
    let test_data = serde_json::json!({"message": "redis test data"});

    set_cache_value(
        &clients.redis_client,
        &clients.s3_client,
        &clients.s3_bucket,
        &redis_cache_key,
        &s3_cache_key,
        &test_data,
    )
    .await?;

    let (result, source) = clients.hypercache.get_with_source(&key_type).await?;

    assert_eq!(result, test_data);
    assert_eq!(source, CacheSource::Redis);

    clear_cache(
        &clients.redis_client,
        &clients.s3_client,
        &clients.s3_bucket,
        Some(&redis_cache_key),
        Some(&s3_cache_key),
        None,
    )
    .await?;

    Ok(())
}

#[tokio::test]
async fn test_hypercache_token_based_cache_key() -> anyhow::Result<()> {
    wait_for_services().await?;

    let clients = setup_integration_clients().await?;
    let api_token = "phc_test_token_abc123";
    let test_data = serde_json::json!({"message": "token-based test data"});
    let mut config = HyperCacheConfig::new(
        "integration_test".to_string(),
        "flags".to_string(),
        "us-east-1".to_string(),
        "posthog".to_string(),
    );
    config.token_based = true;
    config.s3_endpoint = Some("http://localhost:19000".to_string());

    let redis_client_for_cache = RedisClient::new("redis://localhost:6379".to_string()).await?;
    let token_based_hypercache =
        HyperCacheReader::new(std::sync::Arc::new(redis_client_for_cache), config).await?;

    let key_type = KeyType::string(api_token);
    let redis_cache_key = token_based_hypercache
        .config()
        .get_redis_cache_key(&key_type);
    let s3_cache_key = token_based_hypercache.config().get_s3_cache_key(&key_type);

    set_cache_value(
        &clients.redis_client,
        &clients.s3_client,
        &clients.s3_bucket,
        &redis_cache_key,
        &s3_cache_key,
        &test_data,
    )
    .await?;

    let (result, source) = token_based_hypercache.get_with_source(&key_type).await?;

    assert_eq!(result, test_data);
    assert_eq!(source, CacheSource::Redis);

    clear_cache(
        &clients.redis_client,
        &clients.s3_client,
        &clients.s3_bucket,
        Some(&redis_cache_key),
        Some(&s3_cache_key),
        None,
    )
    .await?;

    Ok(())
}

#[tokio::test]
async fn test_hypercache_keytype_variants() -> anyhow::Result<()> {
    wait_for_services().await?;

    let clients = setup_integration_clients().await?;
    let test_data = serde_json::json!({"message": "keytype variants test"});

    // Test integer key
    let int_key = KeyType::int(456);
    let redis_cache_key_int = clients.hypercache.config().get_redis_cache_key(&int_key);
    let s3_cache_key_int = clients.hypercache.config().get_s3_cache_key(&int_key);

    set_cache_value(
        &clients.redis_client,
        &clients.s3_client,
        &clients.s3_bucket,
        &redis_cache_key_int,
        &s3_cache_key_int,
        &test_data,
    )
    .await?;

    let (result, source) = clients.hypercache.get_with_source(&int_key).await?;
    assert_eq!(result, test_data);
    assert_eq!(source, CacheSource::Redis);

    // Test team key with token-based config
    let mut config_token = HyperCacheConfig::new(
        "integration_test".to_string(),
        "flags".to_string(),
        "us-east-1".to_string(),
        "posthog".to_string(),
    );
    config_token.token_based = true;
    config_token.s3_endpoint = Some("http://localhost:19000".to_string());

    let redis_client_token = RedisClient::new("redis://localhost:6379".to_string()).await?;
    let hypercache_token = HyperCacheReader::new(
        std::sync::Arc::new(redis_client_token),
        config_token.clone(),
    )
    .await?;

    let team = TestTeam {
        id: 789,
        token: "phc_integration_test".to_string(),
    };
    let team_key = KeyType::team(team);
    let redis_cache_key_team = hypercache_token.config().get_redis_cache_key(&team_key);
    let s3_cache_key_team = hypercache_token.config().get_s3_cache_key(&team_key);

    set_cache_value(
        &clients.redis_client,
        &clients.s3_client,
        &clients.s3_bucket,
        &redis_cache_key_team,
        &s3_cache_key_team,
        &test_data,
    )
    .await?;

    let (result, source) = hypercache_token.get_with_source(&team_key).await?;
    assert_eq!(result, test_data);
    assert_eq!(source, CacheSource::Redis);

    // Clean up
    clear_cache(
        &clients.redis_client,
        &clients.s3_client,
        &clients.s3_bucket,
        Some(&redis_cache_key_int),
        Some(&s3_cache_key_int),
        None,
    )
    .await?;
    clear_cache(
        &clients.redis_client,
        &clients.s3_client,
        &clients.s3_bucket,
        Some(&redis_cache_key_team),
        Some(&s3_cache_key_team),
        None,
    )
    .await?;

    Ok(())
}
