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
use std::sync::{Arc, OnceLock};
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
        local_cache_ttl: Duration::from_secs(1200), // 20 minutes for hot cache simulation
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
    rt.block_on(async {
        GlobalRateLimiterImpl::new(config, vec![redis])
            .expect("failed to create limiter for benchmark")
    })
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
    let ttl_secs = 1800; // 30 minutes

    // Current bucket boundary
    let now_ts = Utc::now().timestamp();
    let current_bucket = now_ts - (now_ts % bucket_secs);

    // Prime buckets covering:
    // - Past: num_buckets back (the window the limiter reads)
    // - Future: 20 minutes ahead to handle benchmark timing drift
    // The MGET reads buckets (current - 1*bucket) to (current - num_buckets*bucket),
    // so as time advances we need those future buckets ready.
    let extra_future_buckets = 120; // 1200s = 20 minutes with 10s buckets
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
        let _ = limiter.check_limit("cache_hit_key", 1, None).await;
        tokio::time::sleep(Duration::from_millis(10)).await;
    });

    c.bench_function("local_cache_hit", |b| {
        b.to_async(&rt).iter(|| async {
            black_box(track_result(
                limiter.check_limit("cache_hit_key", 1, None).await,
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
            async move { black_box(track_result(limiter_ref.check_limit(&key, 1, None).await)) }
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
                        black_box(track_result(limiter_ref.check_limit(&key, 1, None).await));
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
            let _ = limiter.check_limit(&format!("e2e_key_{i}"), 1, None).await;
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
            async move { black_box(track_result(limiter_ref.check_limit(&key, 1, None).await)) }
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
            async move { black_box(track_result(limiter_ref.check_limit(&key, 1, None).await)) }
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
                .check_custom_limit(&format!("registered_key_{i}"), 1, None)
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
                        .check_custom_limit("unregistered_key", 1, None)
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
                    limiter_ref.check_custom_limit(&key, 1, None).await,
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

/// Simulation: 20 processes × 1000 req/sec, 100k key cardinality, random distribution
///
/// Tests three cache warmth scenarios:
/// - Cold (0%): All caches empty, every request hits Redis
/// - Warm (50%): Half of keys pre-cached, mixed Redis/cache hits
/// - Hot (100%): All keys pre-cached, minimal Redis reads
///
/// Uses metrics-util's DebuggingRecorder to capture accurate cache and eval metrics
/// from the limiter implementation.
fn bench_high_cardinality_simulation(c: &mut Criterion) {
    use metrics_util::debugging::{DebugValue, DebuggingRecorder, Snapshotter};
    use rand::rngs::StdRng;
    use rand::{Rng, SeedableRng};

    // Install a global debugging recorder once per benchmark process.
    static SNAPSHOTTER: OnceLock<Snapshotter> = OnceLock::new();
    let snapshotter = SNAPSHOTTER.get_or_init(|| {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        drop(recorder.install());
        snapshotter
    });

    // Helper to get counter value for a metric with a specific label
    let get_counter_value = |metric_name: &str, label_key: &str, label_value: &str| -> u64 {
        snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .find(|(key, _, _, _)| {
                key.key().name() == metric_name
                    && key
                        .key()
                        .labels()
                        .any(|l| l.key() == label_key && l.value() == label_value)
            })
            .map(|(_, _, _, value)| {
                if let DebugValue::Counter(v) = value {
                    v
                } else {
                    0
                }
            })
            .unwrap_or(0)
    };

    let Some((rt, redis)) = setup_redis() else {
        eprintln!("Skipping bench_high_cardinality_simulation: Redis unavailable");
        return;
    };

    const NUM_PROCESSES: usize = 20;
    const KEYS_CARDINALITY: u64 = 100_000;
    const REQUESTS_PER_PROCESS: usize = 1000;

    let config = bench_config();

    // Prime Redis with bucket data for all keys once at the start
    eprintln!("Priming {KEYS_CARDINALITY} keys in Redis...");
    rt.block_on(async {
        for batch_start in (0..KEYS_CARDINALITY).step_by(1000) {
            let batch_end = (batch_start + 1000).min(KEYS_CARDINALITY);
            for i in batch_start..batch_end {
                let key = format!("sim_key_{i}");
                prime_redis_buckets(&redis, &config, &key, 100).await;
            }
            if batch_start % 10000 == 0 {
                eprintln!("  Primed {batch_start}/{KEYS_CARDINALITY} keys...");
            }
        }
    });
    eprintln!("Priming complete.");

    // Cache warmth scenarios: (name, percentage of keys to pre-cache, fresh_each_iter)
    let scenarios: &[(&str, u64, bool)] = &[
        ("cold_fresh", 0, true),    // Fresh limiters each iteration - true cold start
        ("warm_50pct", 50, false),  // Persistent limiters, 50% pre-warmed
        ("hot_100pct", 100, false), // Persistent limiters, 100% pre-warmed
    ];

    let mut group = c.benchmark_group("simulation_20proc_100k_keys");
    group.sample_size(10);
    group.measurement_time(Duration::from_secs(30));
    group.throughput(Throughput::Elements(
        (NUM_PROCESSES * REQUESTS_PER_PROCESS) as u64,
    ));

    for (scenario_name, cache_warmth_pct, fresh_each_iter) in scenarios {
        if *fresh_each_iter {
            // Capture baseline before benchmark (no warming phase for fresh limiters)
            let baseline_cache_hit =
                get_counter_value("global_rate_limiter_cache_counts_total", "result", "hit");
            let baseline_cache_miss =
                get_counter_value("global_rate_limiter_cache_counts_total", "result", "miss");
            let baseline_cache_stale =
                get_counter_value("global_rate_limiter_cache_counts_total", "result", "stale");
            let baseline_eval_allowed =
                get_counter_value("global_rate_limiter_eval_counts_total", "result", "allowed");
            let baseline_eval_limited =
                get_counter_value("global_rate_limiter_eval_counts_total", "result", "limited");
            let baseline_eval_fail_open = get_counter_value(
                "global_rate_limiter_eval_counts_total",
                "result",
                "fail_open",
            );
            // TRUE COLD START: Create fresh limiters each iteration
            // This measures worst-case latency when all caches are empty
            eprintln!("Running '{scenario_name}': fresh limiters each iteration (true cold start)");

            group.bench_function(*scenario_name, |b| {
                b.to_async(&rt).iter(|| {
                    let redis_clone = redis.clone();
                    let config_clone = config.clone();
                    async move {
                        // Create fresh limiters with empty caches
                        let limiters: Vec<_> = (0..NUM_PROCESSES)
                            .map(|_| {
                                GlobalRateLimiterImpl::new(
                                    config_clone.clone(),
                                    vec![redis_clone.clone()],
                                )
                                .expect("failed to create limiter")
                            })
                            .collect();

                        let handles: Vec<_> = limiters
                            .into_iter()
                            .enumerate()
                            .map(|(proc_id, limiter)| {
                                tokio::spawn(async move {
                                    let mut rng = StdRng::seed_from_u64(proc_id as u64);
                                    for _ in 0..REQUESTS_PER_PROCESS {
                                        let key_id: u64 = rng.gen_range(0..KEYS_CARDINALITY);
                                        let key = format!("sim_key_{key_id}");
                                        let _ = black_box(limiter.check_limit(&key, 1, None).await);
                                    }
                                })
                            })
                            .collect();

                        for handle in handles {
                            let _ = handle.await;
                        }
                    }
                });
            });
            // Report results for fresh_each_iter scenario
            let cache_hit =
                get_counter_value("global_rate_limiter_cache_counts_total", "result", "hit")
                    - baseline_cache_hit;
            let cache_miss =
                get_counter_value("global_rate_limiter_cache_counts_total", "result", "miss")
                    - baseline_cache_miss;
            let cache_stale =
                get_counter_value("global_rate_limiter_cache_counts_total", "result", "stale")
                    - baseline_cache_stale;
            let eval_allowed =
                get_counter_value("global_rate_limiter_eval_counts_total", "result", "allowed")
                    - baseline_eval_allowed;
            let eval_limited =
                get_counter_value("global_rate_limiter_eval_counts_total", "result", "limited")
                    - baseline_eval_limited;
            let eval_fail_open = get_counter_value(
                "global_rate_limiter_eval_counts_total",
                "result",
                "fail_open",
            ) - baseline_eval_fail_open;

            let total_cache = cache_hit + cache_miss + cache_stale;
            let total_eval = eval_allowed + eval_limited + eval_fail_open;

            if total_cache > 0 || total_eval > 0 {
                eprintln!("\n=== {scenario_name} Results ===");
                if total_cache > 0 {
                    eprintln!(
                        "Cache: hit={} ({:.1}%) miss={} ({:.1}%) stale={} ({:.1}%)",
                        cache_hit,
                        cache_hit as f64 / total_cache as f64 * 100.0,
                        cache_miss,
                        cache_miss as f64 / total_cache as f64 * 100.0,
                        cache_stale,
                        cache_stale as f64 / total_cache as f64 * 100.0
                    );
                }
                if total_eval > 0 {
                    eprintln!(
                        "Eval:  allowed={} ({:.1}%) limited={} ({:.1}%) fail_open={} ({:.1}%)",
                        eval_allowed,
                        eval_allowed as f64 / total_eval as f64 * 100.0,
                        eval_limited,
                        eval_limited as f64 / total_eval as f64 * 100.0,
                        eval_fail_open,
                        eval_fail_open as f64 / total_eval as f64 * 100.0
                    );
                }
                eprintln!("================================\n");
            }
        } else {
            // PERSISTENT LIMITERS: Create once, pre-warm, reuse across iterations
            let limiters: Vec<_> = rt.block_on(async {
                (0..NUM_PROCESSES)
                    .map(|_| {
                        GlobalRateLimiterImpl::new(config.clone(), vec![redis.clone()])
                            .expect("failed to create limiter")
                    })
                    .collect()
            });

            // Pre-warm the local caches
            if *cache_warmth_pct > 0 {
                let keys_to_warm = (KEYS_CARDINALITY * cache_warmth_pct / 100) as usize;
                eprintln!(
                    "Warming caches for '{scenario_name}': {keys_to_warm} keys ({cache_warmth_pct}%)..."
                );
                rt.block_on(async {
                    for (proc_idx, limiter) in limiters.iter().enumerate() {
                        for i in (proc_idx..keys_to_warm).step_by(NUM_PROCESSES) {
                            let key = format!("sim_key_{i}");
                            let _ = limiter.check_limit(&key, 1, None).await;
                        }
                    }
                });
                eprintln!("Cache warming complete.");
            }

            // Capture baseline AFTER warming so warming misses aren't counted
            let baseline_cache_hit =
                get_counter_value("global_rate_limiter_cache_counts_total", "result", "hit");
            let baseline_cache_miss =
                get_counter_value("global_rate_limiter_cache_counts_total", "result", "miss");
            let baseline_cache_stale =
                get_counter_value("global_rate_limiter_cache_counts_total", "result", "stale");
            let baseline_eval_allowed =
                get_counter_value("global_rate_limiter_eval_counts_total", "result", "allowed");
            let baseline_eval_limited =
                get_counter_value("global_rate_limiter_eval_counts_total", "result", "limited");
            let baseline_eval_fail_open = get_counter_value(
                "global_rate_limiter_eval_counts_total",
                "result",
                "fail_open",
            );

            let limiters = Arc::new(limiters);

            group.bench_function(*scenario_name, |b| {
                b.to_async(&rt).iter(|| {
                    let limiters = limiters.clone();
                    async move {
                        let handles: Vec<_> = limiters
                            .iter()
                            .enumerate()
                            .map(|(proc_id, limiter)| {
                                let limiter = limiter.clone();
                                tokio::spawn(async move {
                                    let mut rng = StdRng::seed_from_u64(proc_id as u64);
                                    for _ in 0..REQUESTS_PER_PROCESS {
                                        let key_id: u64 = rng.gen_range(0..KEYS_CARDINALITY);
                                        let key = format!("sim_key_{key_id}");
                                        let _ = black_box(limiter.check_limit(&key, 1, None).await);
                                    }
                                })
                            })
                            .collect();

                        for handle in handles {
                            let _ = handle.await;
                        }
                    }
                });
            });

            // Report results for persistent limiter scenario
            let cache_hit =
                get_counter_value("global_rate_limiter_cache_counts_total", "result", "hit")
                    - baseline_cache_hit;
            let cache_miss =
                get_counter_value("global_rate_limiter_cache_counts_total", "result", "miss")
                    - baseline_cache_miss;
            let cache_stale =
                get_counter_value("global_rate_limiter_cache_counts_total", "result", "stale")
                    - baseline_cache_stale;
            let eval_allowed =
                get_counter_value("global_rate_limiter_eval_counts_total", "result", "allowed")
                    - baseline_eval_allowed;
            let eval_limited =
                get_counter_value("global_rate_limiter_eval_counts_total", "result", "limited")
                    - baseline_eval_limited;
            let eval_fail_open = get_counter_value(
                "global_rate_limiter_eval_counts_total",
                "result",
                "fail_open",
            ) - baseline_eval_fail_open;

            let total_cache = cache_hit + cache_miss + cache_stale;
            let total_eval = eval_allowed + eval_limited + eval_fail_open;

            if total_cache > 0 || total_eval > 0 {
                eprintln!("\n=== {scenario_name} Results ===");
                if total_cache > 0 {
                    eprintln!(
                        "Cache: hit={} ({:.1}%) miss={} ({:.1}%) stale={} ({:.1}%)",
                        cache_hit,
                        cache_hit as f64 / total_cache as f64 * 100.0,
                        cache_miss,
                        cache_miss as f64 / total_cache as f64 * 100.0,
                        cache_stale,
                        cache_stale as f64 / total_cache as f64 * 100.0
                    );
                }
                if total_eval > 0 {
                    eprintln!(
                        "Eval:  allowed={} ({:.1}%) limited={} ({:.1}%) fail_open={} ({:.1}%)",
                        eval_allowed,
                        eval_allowed as f64 / total_eval as f64 * 100.0,
                        eval_limited,
                        eval_limited as f64 / total_eval as f64 * 100.0,
                        eval_fail_open,
                        eval_fail_open as f64 / total_eval as f64 * 100.0
                    );
                }
                eprintln!("================================\n");
            }
        }
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
        bench_redis_mget_direct,
        bench_high_cardinality_simulation
);

criterion_main!(benches);
