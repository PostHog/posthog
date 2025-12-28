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

/// Benchmark 1: Local cache hit performance (no Redis involved)
/// Measures the hot path when data is already in the local moka cache
fn bench_local_cache_hit(c: &mut Criterion) {
    let Some((rt, redis)) = setup_redis() else {
        eprintln!("Skipping bench_local_cache_hit: Redis unavailable");
        return;
    };

    let config = bench_config();
    let limiter = create_limiter(&rt, config, redis);

    // Pre-populate the local cache by doing an initial evaluation
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
fn bench_redis_cache_miss(c: &mut Criterion) {
    let Some((rt, redis)) = setup_redis() else {
        eprintln!("Skipping bench_redis_cache_miss: Redis unavailable");
        return;
    };

    // Create limiter once, use unique keys to force cache misses
    let config = bench_config();
    let limiter = create_limiter(&rt, config, redis);

    c.bench_function("redis_cache_miss", |b| {
        let mut key_counter = 0u64;
        b.to_async(&rt).iter(|| {
            key_counter += 1;
            let key = format!("miss_key_{key_counter}");
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
fn bench_high_cardinality(c: &mut Criterion) {
    let Some((rt, redis)) = setup_redis() else {
        eprintln!("Skipping bench_high_cardinality: Redis unavailable");
        return;
    };

    let mut group = c.benchmark_group("high_cardinality");

    for num_keys in [1000, 10000].iter() {
        group.throughput(Throughput::Elements(*num_keys as u64));
        group.bench_with_input(BenchmarkId::from_parameter(num_keys), num_keys, |b, &n| {
            let config = bench_config();
            let limiter = create_limiter(&rt, config, redis.clone());

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
    let limiter = create_limiter(&rt, config, redis);

    // Warm up some keys in cache
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

    // Benchmark with cache misses (unique keys)
    group.bench_function("cache_cold", |b| {
        let mut counter = 0u64;
        b.to_async(&rt).iter(|| {
            counter += 1;
            let key = format!("e2e_cold_key_{counter}");
            let limiter_ref = &limiter;
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
    let limiter = create_limiter(&rt, config, redis);

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

    // Registered key - requires full evaluation
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
fn bench_redis_mget_direct(c: &mut Criterion) {
    let Some((rt, redis)) = setup_redis() else {
        eprintln!("Skipping bench_redis_mget_direct: Redis unavailable");
        return;
    };

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
