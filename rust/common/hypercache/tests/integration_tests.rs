use common_hypercache::writer::{compute_etag, HyperCacheWriter};
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

    let redis_client_for_cache = RedisClient::with_config(
        "redis://localhost:6379".to_string(),
        common_redis::CompressionConfig::disabled(),
        common_redis::RedisValueFormat::default(),
        Some(Duration::from_millis(1000)),
        Some(Duration::from_millis(5000)),
    )
    .await?;
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
        .map_err(|e| anyhow::anyhow!("Failed to set S3 object: {e}"))?;

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

    let redis_client_for_cache = RedisClient::with_config(
        "redis://localhost:6379".to_string(),
        common_redis::CompressionConfig::disabled(),
        common_redis::RedisValueFormat::default(),
        Some(Duration::from_millis(1000)),
        Some(Duration::from_millis(5000)),
    )
    .await?;
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

    let redis_client_token = RedisClient::with_config(
        "redis://localhost:6379".to_string(),
        common_redis::CompressionConfig::disabled(),
        common_redis::RedisValueFormat::default(),
        Some(Duration::from_millis(1000)),
        Some(Duration::from_millis(5000)),
    )
    .await?;
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

// --- HyperCacheWriter integration tests ---

async fn setup_writer_and_reader(
) -> anyhow::Result<(HyperCacheWriter, HyperCacheReader, HyperCacheConfig)> {
    env::set_var("AWS_ACCESS_KEY_ID", "object_storage_root_user");
    env::set_var("AWS_SECRET_ACCESS_KEY", "object_storage_root_password");

    let mut config = HyperCacheConfig::new(
        "writer_test".to_string(),
        "flags".to_string(),
        "us-east-1".to_string(),
        "posthog".to_string(),
    );
    config.s3_endpoint = Some("http://localhost:19000".to_string());

    // Writer uses default Redis client (pickle format, compression disabled)
    let writer_redis = common_redis::RedisClient::new("redis://localhost:6379".to_string()).await?;

    // Build S3 client
    let aws_config = aws_config::defaults(aws_config::BehaviorVersion::latest())
        .endpoint_url("http://localhost:19000")
        .region(aws_config::Region::new("us-east-1"))
        .load()
        .await;
    let mut s3_config_builder = aws_sdk_s3::config::Builder::from(&aws_config);
    s3_config_builder = s3_config_builder.force_path_style(true);
    let aws_s3_client = aws_sdk_s3::Client::from_conf(s3_config_builder.build());
    let s3_impl = common_s3::S3Impl::new(aws_s3_client);
    let s3_arc: std::sync::Arc<dyn common_s3::S3Client + Send + Sync> =
        std::sync::Arc::new(s3_impl);

    let writer = HyperCacheWriter::new(
        std::sync::Arc::new(writer_redis),
        s3_arc.clone(),
        config.clone(),
    );

    // Reader uses disabled compression, matching existing test pattern
    let reader_redis = common_redis::RedisClient::with_config(
        "redis://localhost:6379".to_string(),
        common_redis::CompressionConfig::disabled(),
        common_redis::RedisValueFormat::default(),
        Some(Duration::from_millis(1000)),
        Some(Duration::from_millis(5000)),
    )
    .await?;
    let reader = HyperCacheReader::new_with_s3_client(
        std::sync::Arc::new(reader_redis),
        s3_arc,
        config.clone(),
    );

    Ok((writer, reader, config))
}

#[tokio::test]
async fn test_writer_set_then_reader_get_roundtrip() -> anyhow::Result<()> {
    wait_for_services().await?;

    let (writer, reader, _config) = setup_writer_and_reader().await?;
    let key = KeyType::string("writer-roundtrip-test");
    let json_data = r#"{"flags":[{"id":1,"key":"test-flag","active":true}]}"#;

    writer.set(&key, json_data, 300).await?;

    let (result, source) = reader.get_with_source(&key).await?;
    assert_eq!(source, CacheSource::Redis);

    let expected: Value = serde_json::from_str(json_data)?;
    assert_eq!(result, expected);

    // Cleanup
    writer.delete(&key).await?;
    Ok(())
}

#[tokio::test]
async fn test_writer_set_large_payload_roundtrip() -> anyhow::Result<()> {
    wait_for_services().await?;

    let (writer, reader, _config) = setup_writer_and_reader().await?;
    let key = KeyType::string("writer-large-payload-test");

    let flags: Vec<serde_json::Value> = (0..50)
        .map(|i| {
            serde_json::json!({
                "id": i,
                "key": format!("flag-{i}"),
                "active": true,
                "filters": {"groups": [{"properties": []}]}
            })
        })
        .collect();
    let json_data = serde_json::to_string(&serde_json::json!({"flags": flags}))?;

    writer.set(&key, &json_data, 300).await?;

    let (result, source) = reader.get_with_source(&key).await?;
    assert_eq!(source, CacheSource::Redis);

    let expected: Value = serde_json::from_str(&json_data)?;
    assert_eq!(result, expected);

    // Cleanup
    writer.delete(&key).await?;
    Ok(())
}

#[tokio::test]
async fn test_writer_set_empty_then_reader_gets_sentinel() -> anyhow::Result<()> {
    wait_for_services().await?;

    let (writer, reader, _config) = setup_writer_and_reader().await?;
    let key = KeyType::string("writer-empty-test");

    writer.set_empty(&key, 300).await?;

    let (result, source) = reader.get_with_source(&key).await?;
    assert_eq!(source, CacheSource::Redis);
    // The reader converts "__missing__" sentinel to Null
    assert_eq!(result, Value::Null);

    // Cleanup
    writer.delete(&key).await?;
    Ok(())
}

#[tokio::test]
async fn test_writer_delete_then_reader_cache_miss() -> anyhow::Result<()> {
    wait_for_services().await?;

    let (writer, reader, _config) = setup_writer_and_reader().await?;
    let key = KeyType::string("writer-delete-test");

    // Write then delete
    writer.set(&key, r#"{"flags":[]}"#, 300).await?;
    writer.delete(&key).await?;

    let result = reader.get_with_source(&key).await;
    assert!(result.is_err(), "Should be a cache miss after delete");

    Ok(())
}

#[tokio::test]
async fn test_writer_set_with_etag_roundtrip() -> anyhow::Result<()> {
    wait_for_services().await?;

    let (writer, reader, _config) = setup_writer_and_reader().await?;
    let key = KeyType::string("writer-etag-test");
    let json_data = r#"{"flags":[{"id":42}]}"#;

    let etag = writer.set_with_etag(&key, json_data, 300).await?;

    // Verify ETag matches compute_etag
    assert_eq!(etag, compute_etag(json_data));
    assert_eq!(etag.len(), 16);

    // Verify data is readable
    let (result, _) = reader.get_with_source(&key).await?;
    let expected: Value = serde_json::from_str(json_data)?;
    assert_eq!(result, expected);

    // Cleanup
    writer.delete(&key).await?;
    Ok(())
}
