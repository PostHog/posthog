use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use common_redis::{Client, RedisClient};
use limiters::global_rate_limiter::{
    epoch_from_timestamp, epoch_key, weighted_count, EvalResult, GlobalRateLimiter,
    GlobalRateLimiterConfig, GlobalRateLimiterImpl,
};

const REDIS_URL: &str = "redis://localhost:6379/";

async fn setup_redis() -> Option<RedisClient> {
    match RedisClient::new(REDIS_URL.to_string()).await {
        Ok(client) => Some(client),
        Err(_) => {
            eprintln!("Skipping integration test: Redis not available at {REDIS_URL}");
            None
        }
    }
}

fn test_config(test_name: &str) -> GlobalRateLimiterConfig {
    GlobalRateLimiterConfig {
        global_threshold: 1000,
        window_interval: Duration::from_secs(60),
        sync_interval: Duration::from_secs(2),
        tick_interval: Duration::from_millis(100),
        redis_key_prefix: format!("test:grl:{test_name}"),
        global_cache_ttl: Duration::from_secs(120),
        local_cache_ttl: Duration::from_secs(60),
        local_cache_idle_timeout: Duration::from_secs(30),
        local_cache_max_entries: 1000,
        channel_capacity: 10_000,
        custom_keys: HashMap::new(),
        global_read_timeout: Duration::from_millis(500),
        global_write_timeout: Duration::from_millis(500),
        metrics_scope: "integration_test".to_string(),
    }
}

#[tokio::test]
async fn test_write_then_read_epoch_keys() {
    let Some(redis) = setup_redis().await else {
        return;
    };

    let config = test_config("write_read");
    let redis_arc: Arc<dyn Client + Send + Sync> = Arc::new(redis.clone());
    let limiter = GlobalRateLimiterImpl::new(config.clone(), vec![redis_arc]).unwrap();

    for _ in 0..50 {
        let _ = limiter.check_limit("key_a", 1, None).await;
    }

    tokio::time::sleep(Duration::from_millis(300)).await;

    let now = Utc::now();
    let epoch = epoch_from_timestamp(now, config.window_interval);
    let redis_key = epoch_key(&config.redis_key_prefix, "key_a", epoch);

    let results = redis.mget(vec![redis_key]).await.unwrap();
    let count: u64 = results[0]
        .as_ref()
        .and_then(|b| std::str::from_utf8(b).ok())
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);

    assert!(
        count >= 40,
        "Expected at least 40 events written to Redis, got {count}"
    );
}

#[tokio::test]
async fn test_epoch_key_ttl_expiry() {
    let Some(redis) = setup_redis().await else {
        return;
    };

    let mut config = test_config("ttl_expiry");
    config.global_cache_ttl = Duration::from_secs(2);
    let redis_arc: Arc<dyn Client + Send + Sync> = Arc::new(redis.clone());
    let limiter = GlobalRateLimiterImpl::new(config.clone(), vec![redis_arc]).unwrap();

    let _ = limiter.check_limit("ttl_key", 10, None).await;
    tokio::time::sleep(Duration::from_millis(300)).await;

    let now = Utc::now();
    let epoch = epoch_from_timestamp(now, config.window_interval);
    let redis_key = epoch_key(&config.redis_key_prefix, "ttl_key", epoch);

    let results = redis.mget(vec![redis_key.clone()]).await.unwrap();
    assert!(
        results[0].is_some(),
        "Key should exist immediately after write"
    );

    tokio::time::sleep(Duration::from_secs(3)).await;

    let results = redis.mget(vec![redis_key]).await.unwrap();
    assert!(results[0].is_none(), "Key should have expired after TTL");
}

#[tokio::test]
async fn test_background_task_flushes_writes() {
    let Some(redis) = setup_redis().await else {
        return;
    };

    let config = test_config("flush_writes");
    let redis_arc: Arc<dyn Client + Send + Sync> = Arc::new(redis.clone());
    let limiter = GlobalRateLimiterImpl::new(config.clone(), vec![redis_arc]).unwrap();

    let keys = ["fa", "fb", "fc"];
    let counts = [10u64, 20, 30];

    for (key, count) in keys.iter().zip(counts.iter()) {
        let _ = limiter.check_limit(key, *count, None).await;
    }

    tokio::time::sleep(Duration::from_millis(300)).await;

    let now = Utc::now();
    let epoch = epoch_from_timestamp(now, config.window_interval);
    let redis_keys: Vec<String> = keys
        .iter()
        .map(|k| epoch_key(&config.redis_key_prefix, k, epoch))
        .collect();

    let results = redis.mget(redis_keys).await.unwrap();

    for (i, (key, expected)) in keys.iter().zip(counts.iter()).enumerate() {
        let actual: u64 = results[i]
            .as_ref()
            .and_then(|b| std::str::from_utf8(b).ok())
            .and_then(|s| s.parse().ok())
            .unwrap_or(0);
        assert!(
            actual >= *expected,
            "Entity {key}: expected at least {expected}, got {actual}"
        );
    }
}

#[tokio::test]
async fn test_background_task_processes_pending_sync() {
    let Some(redis) = setup_redis().await else {
        return;
    };

    let config = test_config("pending_sync");
    let now = Utc::now();
    let epoch = epoch_from_timestamp(now, config.window_interval);
    let redis_key = epoch_key(&config.redis_key_prefix, "sync_ent", epoch);

    redis
        .batch_incr_by_expire(vec![(redis_key, 500)], 120)
        .await
        .unwrap();

    let redis_arc: Arc<dyn Client + Send + Sync> = Arc::new(redis.clone());
    let limiter = GlobalRateLimiterImpl::new(config.clone(), vec![redis_arc]).unwrap();

    let _ = limiter.check_limit("sync_ent", 1, None).await;

    tokio::time::sleep(Duration::from_millis(500)).await;

    // 500 + 1 = 501, threshold is 1000 => allowed
    let result = limiter.check_limit("sync_ent", 0, None).await;
    assert!(
        matches!(result, EvalResult::Allowed),
        "Expected Allowed after sync (501/1000), got {result:?}"
    );
}

#[tokio::test]
async fn test_concurrent_access_same_entity() {
    let Some(redis) = setup_redis().await else {
        return;
    };

    let config = test_config("concurrent");
    let redis_arc: Arc<dyn Client + Send + Sync> = Arc::new(redis.clone());
    let limiter = Arc::new(GlobalRateLimiterImpl::new(config.clone(), vec![redis_arc]).unwrap());

    let num_tasks = 10;
    let events_per_task = 50;

    let mut handles = Vec::new();
    for _ in 0..num_tasks {
        let limiter = limiter.clone();
        handles.push(tokio::spawn(async move {
            for _ in 0..events_per_task {
                let _ = limiter.check_limit("ck", 1, None).await;
            }
        }));
    }

    for handle in handles {
        handle.await.unwrap();
    }

    tokio::time::sleep(Duration::from_millis(500)).await;

    let now = Utc::now();
    let epoch = epoch_from_timestamp(now, config.window_interval);
    let redis_key = epoch_key(&config.redis_key_prefix, "ck", epoch);

    let results = redis.mget(vec![redis_key]).await.unwrap();
    let total: u64 = results[0]
        .as_ref()
        .and_then(|b| std::str::from_utf8(b).ok())
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);

    let expected_total = (num_tasks * events_per_task) as u64;
    assert!(
        total >= expected_total * 80 / 100,
        "Expected at least 80% of {expected_total} events in Redis, got {total}"
    );
}

#[tokio::test]
async fn test_pipeline_100_entities() {
    let Some(redis) = setup_redis().await else {
        return;
    };

    let config = test_config("pipeline100");
    let redis_arc: Arc<dyn Client + Send + Sync> = Arc::new(redis.clone());
    let limiter = GlobalRateLimiterImpl::new(config.clone(), vec![redis_arc]).unwrap();

    let entity_count = 100;
    for i in 0..entity_count {
        let key = format!("e{i}");
        let _ = limiter.check_limit(&key, (i + 1) as u64, None).await;
    }

    tokio::time::sleep(Duration::from_millis(500)).await;

    let now = Utc::now();
    let epoch = epoch_from_timestamp(now, config.window_interval);
    let redis_keys: Vec<String> = (0..entity_count)
        .map(|i| epoch_key(&config.redis_key_prefix, &format!("e{i}"), epoch))
        .collect();

    let results = redis.mget(redis_keys).await.unwrap();

    let mut found_count = 0;
    for (i, result) in results.iter().enumerate() {
        if let Some(bytes) = result {
            if let Ok(count) = std::str::from_utf8(bytes).unwrap_or("0").parse::<u64>() {
                if count > 0 {
                    found_count += 1;
                    assert_eq!(
                        count,
                        (i + 1) as u64,
                        "Entity e{i} should have count {}, got {count}",
                        i + 1
                    );
                }
            }
        }
    }

    assert!(
        found_count >= 90,
        "Expected at least 90 out of {entity_count} entities written, got {found_count}"
    );
}

#[tokio::test]
async fn test_sliding_window_accuracy_uniform() {
    let Some(redis) = setup_redis().await else {
        return;
    };

    let config = test_config("accuracy");
    let now = Utc::now();
    let epoch = epoch_from_timestamp(now, config.window_interval);

    let curr_key = epoch_key(&config.redis_key_prefix, "uniform", epoch);
    let prev_key = epoch_key(&config.redis_key_prefix, "uniform", epoch - 1);

    redis
        .batch_incr_by_expire(vec![(curr_key, 500), (prev_key, 300)], 120)
        .await
        .unwrap();

    let estimate = weighted_count(300, 500, now, config.window_interval);

    // Weighted count should be between 500 (current only) and 800 (full prev + current)
    assert!(
        (500.0..=800.0).contains(&estimate),
        "Weighted count {estimate} should be in [500, 800] for uniform traffic"
    );
}

#[tokio::test]
async fn test_decay_drift_over_sync_interval() {
    let Some(redis) = setup_redis().await else {
        return;
    };

    let config = test_config("decay_drift");
    let now = Utc::now();
    let epoch = epoch_from_timestamp(now, config.window_interval);

    let prime_count = config.global_threshold / 2;
    let curr_key = epoch_key(&config.redis_key_prefix, "drift", epoch);
    redis
        .batch_incr_by_expire(vec![(curr_key, prime_count as i64)], 120)
        .await
        .unwrap();

    let redis_arc: Arc<dyn Client + Send + Sync> = Arc::new(redis.clone());
    let limiter = GlobalRateLimiterImpl::new(config.clone(), vec![redis_arc]).unwrap();

    let _ = limiter.check_limit("drift", 0, None).await;
    tokio::time::sleep(Duration::from_millis(500)).await;

    // Wait for roughly one sync_interval
    tokio::time::sleep(config.sync_interval).await;

    // Access again to trigger re-sync
    let _ = limiter.check_limit("drift", 0, None).await;
    tokio::time::sleep(Duration::from_millis(500)).await;

    // At 50% capacity, should still be allowed after re-sync
    let result = limiter.check_limit("drift", 0, None).await;
    assert!(
        matches!(result, EvalResult::Allowed),
        "Entity at 50% capacity should be Allowed after re-sync, got {result:?}"
    );
}

#[tokio::test]
async fn test_limiter_correctly_limits_at_threshold() {
    let Some(redis) = setup_redis().await else {
        return;
    };

    let mut config = test_config("limits_at_threshold");
    config.global_threshold = 100;

    let now = Utc::now();
    let epoch = epoch_from_timestamp(now, config.window_interval);
    let curr_key = epoch_key(&config.redis_key_prefix, "over", epoch);

    redis
        .batch_incr_by_expire(vec![(curr_key, 150)], 120)
        .await
        .unwrap();

    let redis_arc: Arc<dyn Client + Send + Sync> = Arc::new(redis.clone());
    let limiter = GlobalRateLimiterImpl::new(config.clone(), vec![redis_arc]).unwrap();

    // Cache miss => allowed (fail open)
    let result = limiter.check_limit("over", 1, None).await;
    assert!(
        matches!(result, EvalResult::Allowed),
        "First access (cache miss) should be Allowed"
    );

    tokio::time::sleep(Duration::from_millis(500)).await;

    // After sync, should be limited
    let result = limiter.check_limit("over", 1, None).await;
    assert!(
        matches!(result, EvalResult::Limited(_)),
        "Should be Limited after sync reveals count over threshold, got {result:?}"
    );
}

#[tokio::test]
async fn test_custom_key_high_threshold_sync_and_limit() {
    let Some(redis) = setup_redis().await else {
        return;
    };

    let key = format!("high_limit_{}", Utc::now().timestamp());
    let mut config = test_config("custom_high");
    config.global_threshold = 1000;
    config.custom_keys.insert(key.clone(), 100_000);

    let now = Utc::now();
    let epoch = epoch_from_timestamp(now, config.window_interval);
    let curr_key = epoch_key(&config.redis_key_prefix, &key, epoch);
    let prev_key = epoch_key(&config.redis_key_prefix, &key, epoch - 1);

    redis
        .batch_incr_by_expire(vec![(curr_key.clone(), 50_000), (prev_key, 0)], 120)
        .await
        .unwrap();

    let redis_arc: Arc<dyn Client + Send + Sync> = Arc::new(redis.clone());
    let limiter = GlobalRateLimiterImpl::new(config.clone(), vec![redis_arc]).unwrap();

    let _ = limiter.check_custom_limit(&key, 0, None).await;
    tokio::time::sleep(Duration::from_millis(500)).await;

    let result = limiter.check_custom_limit(&key, 1, None).await;
    assert!(
        matches!(result, EvalResult::Allowed),
        "Custom key at 50k/100k should be Allowed, got {result:?}"
    );

    redis
        .batch_incr_by_expire(vec![(curr_key, 100_000)], 120)
        .await
        .unwrap();

    tokio::time::sleep(config.sync_interval + Duration::from_millis(300)).await;
    let _ = limiter.check_custom_limit(&key, 0, None).await;
    tokio::time::sleep(Duration::from_millis(300)).await;

    let result = limiter.check_custom_limit(&key, 1, None).await;
    assert!(
        matches!(result, EvalResult::Limited(_)),
        "Custom key at 150k/100k should be Limited after sync, got {result:?}"
    );
}
