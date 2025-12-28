//! Benchmarks for the GlobalRateLimiter implementation
//!
//! Requires Redis running on localhost:6379 (docker-compose.dev.yml)
//!
//! ## Usage
//!
//! ```bash
//! # Start Redis
//! docker-compose -f docker-compose.dev.yml up redis -d
//!
//! # Run all benchmarks
//! cargo bench -p limiters
//!
//! # Run specific benchmark
//! cargo bench -p limiters -- "local_cache_hit"
//!
//! # Quick test mode (validates benchmarks without full measurement)
//! cargo bench -p limiters -- --test
//! ```
//!
//! ## Benchmarks
//!
//! | Benchmark | Description |
//! |-----------|-------------|
//! | `local_cache_hit` | Hot path latency when data is in local moka cache |
//! | `redis_cache_miss` | MGET latency for 6 bucket keys on cache miss |
//! | `batch_write_throughput/{10,100,1000}` | Redis pipeline write performance |
//! | `high_cardinality/{1000,10000}` | Performance under cache pressure |
//! | `e2e_throughput/cache_hot` | Full eval loop with warm cache |
//! | `e2e_throughput/cache_cold` | Full eval loop with cold cache |
//! | `custom_key/unregistered` | Fast path for unregistered custom keys |
//! | `custom_key/registered` | Full eval for registered custom keys |
//! | `redis_mget_direct/{6,12,24}` | Raw Redis MGET baseline |

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use common_redis::Client;
use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use limiters::global_rate_limiter::{
    EvalResult, GlobalRateLimiter, GlobalRateLimiterConfig, GlobalRateLimiterImpl,
};
use tokio::runtime::Runtime;

/// Global counter for tracking fail-opens during benchmarks
static FAIL_OPEN_COUNT: AtomicU64 = AtomicU64::new(0);

/// Track a result and increment fail-open counter if needed
fn track_result(result: EvalResult) -> EvalResult {
    if matches!(result, EvalResult::FailOpen { .. }) {
        FAIL_OPEN_COUNT.fetch_add(1, Ordering::Relaxed);
    }
    result
}

/// Report and reset fail-open count. Call after each benchmark group.
fn report_fail_opens(bench_name: &str) {
    let count = FAIL_OPEN_COUNT.swap(0, Ordering::Relaxed);
    if count > 0 {
        eprintln!(
            "WARNING: {count} fail-opens detected during '{bench_name}' benchmark - results may be skewed!"
        );
    }
}

const REDIS_URL: &str = "redis://localhost:6379/";

fn bench_config() -> GlobalRateLimiterConfig {
    GlobalRateLimiterConfig {
        global_threshold: 100_000,
        window_interval: Duration::from_secs(60),
        bucket_interval: Duration::from_secs(10),
        rate_limit_interval: Duration::from_secs(60),
        redis_key_prefix: "bench:grl".to_string(),
        global_cache_ttl: Duration::from_secs(300),
        local_cache_ttl: Duration::from_secs(120),
        local_cache_max_entries: 100_000,
        batch_interval: Duration::from_millis(100),
        batch_max_update_count: 10000,
        batch_max_key_cardinality: 1000,
        channel_capacity: 100_000,
        custom_keys: HashMap::new(),
        global_read_timeout: Duration::from_millis(50),
        global_write_timeout: Duration::from_millis(50),
    }
}

/// Create a runtime and Redis client, or return None if Redis is unavailable
fn setup_redis() -> Option<(Runtime, Arc<common_redis::RedisClient>)> {
    let rt = Runtime::new().unwrap();
    let redis = rt.block_on(async {
        match common_redis::RedisClient::new(REDIS_URL.to_string()).await {
            Ok(client) => Some(Arc::new(client)),
            Err(e) => {
                eprintln!("Redis unavailable ({e}), skipping Redis benchmarks");
                None
            }
        }
    })?;
    Some((rt, redis))
}

/// Create a limiter within the runtime context (required for background task spawn)
fn create_limiter(
    rt: &Runtime,
    config: GlobalRateLimiterConfig,
    redis: Arc<common_redis::RedisClient>,
) -> GlobalRateLimiterImpl {
    rt.block_on(async { GlobalRateLimiterImpl::new(config, redis) })
}

/// Prime Redis with bucket data for a key so MGET returns real values.
/// This simulates a key that has been actively receiving traffic.
///
/// Primes buckets covering several minutes into the future to handle timing drift
/// during benchmark execution. The limiter uses Utc::now() at eval time and reads
/// buckets from (current_bucket - bucket_interval) going back for window_interval.
/// As time advances during benchmarks, we need buckets primed ahead of time.
async fn prime_redis_buckets(
    redis: &common_redis::RedisClient,
    config: &GlobalRateLimiterConfig,
    key: &str,
    count_per_bucket: i64,
) {
    let bucket_secs = config.bucket_interval.as_secs() as i64;
    let window_secs = config.window_interval.as_secs() as i64;
    let num_buckets = (window_secs / bucket_secs) as usize;

    // Use a long TTL so primed data survives the entire benchmark suite
    let ttl_secs = 900; // 15 minutes

    // Current bucket boundary
    let now_ts = Utc::now().timestamp();
    let current_bucket = now_ts - (now_ts % bucket_secs);

    // Prime buckets covering:
    // - Past: num_buckets back (the window the limiter reads)
    // - Future: 10 minutes ahead to handle benchmark timing drift
    // The MGET reads buckets (current - 1*bucket) to (current - num_buckets*bucket),
    // so as time advances we need those future buckets ready.
    let extra_future_buckets = 60; // 600s = 10 minutes with 10s buckets
    let bucket_ids: Vec<i64> = (-(extra_future_buckets as i64)..=(num_buckets as i64))
        .map(|i| current_bucket - (i * bucket_secs))
        .collect();

    // Batch the priming for efficiency
    let items: Vec<(String, i64)> = bucket_ids
        .iter()
        .map(|bucket_id| {
            let bucket_key = format!("{}:{}:{}", config.redis_key_prefix, key, bucket_id);
            (bucket_key, count_per_bucket)
        })
        .collect();

    if let Err(e) = redis.batch_incr_by_expire(items, ttl_secs).await {
        eprintln!("Failed to prime Redis buckets for key {key}: {e}");
    }
}

/// Benchmark 1: Local cache hit performance (no Redis involved)
/// Measures the hot path when data is already in the local moka cache
fn bench_local_cache_hit(c: &mut Criterion) {
    let Some((rt, redis)) = setup_redis() else {
        eprintln!("Skipping bench_local_cache_hit: Redis unavailable");
        return;
    };

    let config = bench_config();

    // Pre-prime Redis so the cache warmup reads real data
    rt.block_on(async {
        prime_redis_buckets(&redis, &config, "cache_hit_key", 100).await;
    });

    let limiter = create_limiter(&rt, config, redis);

    // Pre-populate the local cache by doing an initial evaluation (reads from Redis)
    rt.block_on(async {
        let _ = limiter.update_eval_key("cache_hit_key", 1, None).await;
        tokio::time::sleep(Duration::from_millis(10)).await;
    });

    c.bench_function("local_cache_hit", |b| {
        b.to_async(&rt).iter(|| async {
            black_box(track_result(
                limiter.update_eval_key("cache_hit_key", 1, None).await,
            ))
        });
    });

    report_fail_opens("local_cache_hit");
}

/// Benchmark 2: Redis cache miss - measures MGET latency for sliding window reads
/// Each evaluation fetches 6 bucket keys from Redis (60s window / 10s bucket)
///
/// Keys are pre-primed in Redis so MGET returns actual data (not empty).
fn bench_redis_cache_miss(c: &mut Criterion) {
    let Some((rt, redis)) = setup_redis() else {
        eprintln!("Skipping bench_redis_cache_miss: Redis unavailable");
        return;
    };

    let config = bench_config();

    // Pre-prime Redis with bucket data for a pool of keys
    // Using a pool so we can cycle through and avoid local cache hits
    const PRIMED_KEY_COUNT: u64 = 1000;
    rt.block_on(async {
        for i in 0..PRIMED_KEY_COUNT {
            let key = format!("primed_miss_key_{i}");
            prime_redis_buckets(&redis, &config, &key, 100).await;
        }
    });

    // Create limiter with very short local cache TTL to force Redis reads
    let mut short_cache_config = config.clone();
    short_cache_config.local_cache_ttl = Duration::from_millis(1);
    let limiter = create_limiter(&rt, short_cache_config, redis);

    c.bench_function("redis_cache_miss", |b| {
        let mut key_counter = 0u64;
        b.to_async(&rt).iter(|| {
            // Cycle through primed keys to force cache misses
            key_counter = (key_counter + 1) % PRIMED_KEY_COUNT;
            let key = format!("primed_miss_key_{key_counter}");
            let limiter_ref = &limiter;
            async move {
                black_box(track_result(
                    limiter_ref.update_eval_key(&key, 1, None).await,
                ))
            }
        });
    });

    report_fail_opens("redis_cache_miss");
}

/// Benchmark 3: Batch write throughput with varying batch sizes
/// Measures Redis pipeline write performance for different batch cardinalities
fn bench_batch_write_throughput(c: &mut Criterion) {
    let Some((rt, redis)) = setup_redis() else {
        eprintln!("Skipping bench_batch_write_throughput: Redis unavailable");
        return;
    };

    let mut group = c.benchmark_group("batch_write_throughput");

    for batch_size in [10, 100, 1000].iter() {
        group.throughput(Throughput::Elements(*batch_size as u64));
        group.bench_with_input(
            BenchmarkId::from_parameter(batch_size),
            batch_size,
            |b, &size| {
                b.to_async(&rt).iter(|| {
                    let redis_clone = redis.clone();
                    async move {
                        let items: Vec<(String, i64)> = (0..size)
                            .map(|i| (format!("bench:batch_key_{i}"), 1i64))
                            .collect();

                        black_box(redis_clone.batch_incr_by_expire_nx(items, 300).await.ok())
                    }
                });
            },
        );
    }
    group.finish();
}

/// Benchmark 4: High-cardinality key scenario
/// Simulates real traffic patterns with many distinct keys causing cache pressure
///
/// Keys are pre-primed in Redis so MGET returns actual data.
fn bench_high_cardinality(c: &mut Criterion) {
    let Some((rt, redis)) = setup_redis() else {
        eprintln!("Skipping bench_high_cardinality: Redis unavailable");
        return;
    };

    let config = bench_config();

    // Pre-prime Redis with bucket data for the largest key count we'll test
    const MAX_KEYS: usize = 10000;
    rt.block_on(async {
        for i in 0..MAX_KEYS {
            let key = format!("hc_key_{i}");
            prime_redis_buckets(&redis, &config, &key, 100).await;
        }
    });

    let mut group = c.benchmark_group("high_cardinality");

    for num_keys in [1000, 10000].iter() {
        group.throughput(Throughput::Elements(*num_keys as u64));
        group.bench_with_input(BenchmarkId::from_parameter(num_keys), num_keys, |b, &n| {
            let limiter = create_limiter(&rt, config.clone(), redis.clone());

            b.to_async(&rt).iter(|| {
                let limiter_ref = &limiter;
                async move {
                    for i in 0..n {
                        let key = format!("hc_key_{i}");
                        black_box(track_result(
                            limiter_ref.update_eval_key(&key, 1, None).await,
                        ));
                    }
                }
            });
        });
    }
    group.finish();

    report_fail_opens("high_cardinality");
}

/// Benchmark 5: End-to-end update_eval_key throughput
/// Full evaluation loop with mixed cache behavior
fn bench_update_eval_key_e2e(c: &mut Criterion) {
    let Some((rt, redis)) = setup_redis() else {
        eprintln!("Skipping bench_update_eval_key_e2e: Redis unavailable");
        return;
    };

    let config = bench_config();

    // Pre-prime Redis with bucket data for cache_hot keys
    rt.block_on(async {
        for i in 0..100 {
            let key = format!("e2e_key_{i}");
            prime_redis_buckets(&redis, &config, &key, 100).await;
        }
    });

    let limiter = create_limiter(&rt, config.clone(), redis.clone());

    // Warm up local cache for cache_hot keys
    rt.block_on(async {
        for i in 0..100 {
            let _ = limiter
                .update_eval_key(&format!("e2e_key_{i}"), 1, None)
                .await;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    });

    let mut group = c.benchmark_group("e2e_throughput");
    group.throughput(Throughput::Elements(1));

    // Benchmark with mostly cache hits (repeated keys)
    group.bench_function("cache_hot", |b| {
        let mut counter = 0u64;
        b.to_async(&rt).iter(|| {
            counter = (counter + 1) % 100;
            let key = format!("e2e_key_{counter}");
            let limiter_ref = &limiter;
            async move {
                black_box(track_result(
                    limiter_ref.update_eval_key(&key, 1, None).await,
                ))
            }
        });
    });

    // Pre-prime Redis with bucket data for cache_cold keys
    const COLD_KEY_COUNT: u64 = 1000;
    rt.block_on(async {
        for i in 0..COLD_KEY_COUNT {
            let key = format!("e2e_cold_key_{i}");
            prime_redis_buckets(&redis, &config, &key, 100).await;
        }
    });

    // Create new limiter with short cache TTL to force Redis reads
    let mut short_cache_config = config;
    short_cache_config.local_cache_ttl = Duration::from_millis(1);
    let cold_limiter = create_limiter(&rt, short_cache_config, redis);

    // Benchmark with cache misses (cycling through primed keys)
    group.bench_function("cache_cold", |b| {
        let mut counter = 0u64;
        b.to_async(&rt).iter(|| {
            counter = (counter + 1) % COLD_KEY_COUNT;
            let key = format!("e2e_cold_key_{counter}");
            let limiter_ref = &cold_limiter;
            async move {
                black_box(track_result(
                    limiter_ref.update_eval_key(&key, 1, None).await,
                ))
            }
        });
    });

    group.finish();

    report_fail_opens("e2e_throughput");
}

/// Benchmark 6: Custom key evaluation
/// Compares registered vs unregistered custom key performance
fn bench_custom_key_evaluation(c: &mut Criterion) {
    let Some((rt, redis)) = setup_redis() else {
        eprintln!("Skipping bench_custom_key_evaluation: Redis unavailable");
        return;
    };

    // Config with some registered custom keys
    let mut config = bench_config();
    for i in 0..100 {
        config
            .custom_keys
            .insert(format!("registered_key_{i}"), 50_000);
    }

    // Pre-prime Redis with bucket data for registered keys
    rt.block_on(async {
        for i in 0..100 {
            let key = format!("registered_key_{i}");
            prime_redis_buckets(&redis, &config, &key, 100).await;
        }
    });

    let limiter = create_limiter(&rt, config, redis);

    // Warm up local cache for registered keys
    rt.block_on(async {
        for i in 0..100 {
            let _ = limiter
                .update_eval_custom_key(&format!("registered_key_{i}"), 1, None)
                .await;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    });

    let mut group = c.benchmark_group("custom_key");

    // Unregistered key - should return NotApplicable immediately (fast path)
    group.bench_function("unregistered", |b| {
        b.to_async(&rt).iter(|| {
            let limiter_ref = &limiter;
            async move {
                black_box(track_result(
                    limiter_ref
                        .update_eval_custom_key("unregistered_key", 1, None)
                        .await,
                ))
            }
        });
    });

    // Registered key - requires full evaluation (cache hit path)
    group.bench_function("registered", |b| {
        let mut counter = 0u64;
        b.to_async(&rt).iter(|| {
            counter = (counter + 1) % 100;
            let key = format!("registered_key_{counter}");
            let limiter_ref = &limiter;
            async move {
                black_box(track_result(
                    limiter_ref.update_eval_custom_key(&key, 1, None).await,
                ))
            }
        });
    });

    group.finish();

    report_fail_opens("custom_key");
}

/// Benchmark: Redis MGET latency directly (bypasses limiter)
/// Measures raw Redis read performance for comparison
///
/// Keys are pre-populated so MGET returns actual data.
fn bench_redis_mget_direct(c: &mut Criterion) {
    let Some((rt, redis)) = setup_redis() else {
        eprintln!("Skipping bench_redis_mget_direct: Redis unavailable");
        return;
    };

    // Pre-populate keys with actual data
    const MAX_KEYS: usize = 24;
    rt.block_on(async {
        let items: Vec<(String, i64)> = (0..MAX_KEYS)
            .map(|i| (format!("mget_key_{i}"), 1000i64))
            .collect();
        let _ = redis.batch_incr_by_expire_nx(items, 300).await;
    });

    let mut group = c.benchmark_group("redis_mget_direct");

    for num_keys in [6, 12, 24].iter() {
        group.bench_with_input(BenchmarkId::from_parameter(num_keys), num_keys, |b, &n| {
            let keys: Vec<String> = (0..n).map(|i| format!("mget_key_{i}")).collect();
            b.to_async(&rt).iter(|| {
                let keys_clone = keys.clone();
                let redis_clone = redis.clone();
                async move { black_box(redis_clone.mget(keys_clone).await.ok()) }
            });
        });
    }
    group.finish();
}

criterion_group!(
    name = benches;
    config = Criterion::default()
        .sample_size(100)
        .measurement_time(Duration::from_secs(5));
    targets =
        bench_local_cache_hit,
        bench_redis_cache_miss,
        bench_batch_write_throughput,
        bench_high_cardinality,
        bench_update_eval_key_e2e,
        bench_custom_key_evaluation,
        bench_redis_mget_direct
);

criterion_main!(benches);
