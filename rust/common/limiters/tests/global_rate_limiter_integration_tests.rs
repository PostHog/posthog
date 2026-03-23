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
const POLL_INTERVAL: Duration = Duration::from_millis(100);
const POLL_TIMEOUT: Duration = Duration::from_secs(3);

macro_rules! poll_assert {
    ($msg:expr, $body:expr) => {{
        let deadline = tokio::time::Instant::now() + POLL_TIMEOUT;
        loop {
            if $body {
                break;
            }
            assert!(tokio::time::Instant::now() < deadline, "{}", $msg);
            tokio::time::sleep(POLL_INTERVAL).await;
        }
    }};
}

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

fn parse_redis_count(bytes: &Option<Vec<u8>>) -> u64 {
    bytes
        .as_ref()
        .and_then(|b| std::str::from_utf8(b).ok())
        .and_then(|s| s.parse().ok())
        .unwrap_or(0)
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

    let now = Utc::now();
    let epoch = epoch_from_timestamp(now, config.window_interval);
    let redis_key = epoch_key(&config.redis_key_prefix, "key_a", epoch);

    poll_assert!("expected ≥40 events in Redis", {
        let results = redis.mget(vec![redis_key.clone()]).await.unwrap();
        parse_redis_count(&results[0]) >= 40
    });
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

    let now = Utc::now();
    let epoch = epoch_from_timestamp(now, config.window_interval);
    let redis_key = epoch_key(&config.redis_key_prefix, "ttl_key", epoch);

    poll_assert!("key should exist after write flush", {
        let results = redis.mget(vec![redis_key.clone()]).await.unwrap();
        results[0].is_some()
    });

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

    let now = Utc::now();
    let epoch = epoch_from_timestamp(now, config.window_interval);
    let redis_keys: Vec<String> = keys
        .iter()
        .map(|k| epoch_key(&config.redis_key_prefix, k, epoch))
        .collect();

    poll_assert!("all entities should reach expected counts", {
        let results = redis.mget(redis_keys.clone()).await.unwrap();
        results
            .iter()
            .zip(counts.iter())
            .all(|(r, expected)| parse_redis_count(r) >= *expected)
    });
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

    // 500 + 1 = 501, threshold is 1000 => allowed
    poll_assert!("expected Allowed after sync (501/1000)", {
        matches!(
            limiter.check_limit("sync_ent", 0, None).await,
            EvalResult::Allowed
        )
    });
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

    let now = Utc::now();
    let epoch = epoch_from_timestamp(now, config.window_interval);
    let redis_key = epoch_key(&config.redis_key_prefix, "ck", epoch);
    let expected_total = (num_tasks * events_per_task) as u64;

    poll_assert!("expected ≥80% of events in Redis", {
        let results = redis.mget(vec![redis_key.clone()]).await.unwrap();
        parse_redis_count(&results[0]) >= expected_total * 80 / 100
    });
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

    let now = Utc::now();
    let epoch = epoch_from_timestamp(now, config.window_interval);
    let redis_keys: Vec<String> = (0..entity_count)
        .map(|i| epoch_key(&config.redis_key_prefix, &format!("e{i}"), epoch))
        .collect();

    poll_assert!("expected ≥90/100 entities written", {
        let results = redis.mget(redis_keys.clone()).await.unwrap();
        let found = results
            .iter()
            .enumerate()
            .filter(|(i, r)| parse_redis_count(r) == (*i + 1) as u64)
            .count();
        found >= 90
    });
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

    poll_assert!("should be Allowed after initial sync at 50% capacity", {
        matches!(
            limiter.check_limit("drift", 0, None).await,
            EvalResult::Allowed
        )
    });

    // Wait for one sync_interval then verify re-sync still allows
    tokio::time::sleep(config.sync_interval).await;

    poll_assert!("should be Allowed after re-sync at 50% capacity", {
        matches!(
            limiter.check_limit("drift", 0, None).await,
            EvalResult::Allowed
        )
    });
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

    poll_assert!(
        "should be Limited after sync reveals count over threshold",
        {
            matches!(
                limiter.check_limit("over", 1, None).await,
                EvalResult::Limited(_)
            )
        }
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

    poll_assert!("custom key at 50k/100k should be Allowed", {
        matches!(
            limiter.check_custom_limit(&key, 1, None).await,
            EvalResult::Allowed
        )
    });

    redis
        .batch_incr_by_expire(vec![(curr_key, 100_000)], 120)
        .await
        .unwrap();

    // Wait for sync_interval so limiter picks up the new count
    tokio::time::sleep(config.sync_interval).await;

    poll_assert!("custom key at 150k/100k should be Limited after sync", {
        let _ = limiter.check_custom_limit(&key, 0, None).await;
        matches!(
            limiter.check_custom_limit(&key, 1, None).await,
            EvalResult::Limited(_)
        )
    });
}
