use std::collections::hash_map::DefaultHasher;
use std::collections::HashMap;
use std::hash::{Hash, Hasher};
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use common_redis::Client;
use moka::sync::Cache;
use tokio::sync::mpsc;
use tokio::time::interval;
use tracing::{error, warn};

const GLOBAL_RATE_LIMITER_EVAL_COUNTER: &str = "global_rate_limiter_eval_counts_total";
const GLOBAL_RATE_LIMITER_CACHE_COUNTER: &str = "global_rate_limiter_cache_counts_total";
const GLOBAL_RATE_LIMITER_RECORDS_COUNTER: &str = "global_rate_limiter_records_total";
const GLOBAL_RATE_LIMITER_ERROR_COUNTER: &str = "global_rate_limiter_error_total";
const GLOBAL_RATE_LIMITER_BATCH_WRITE_HISTOGRAM: &str = "global_rate_limiter_batch_write_seconds";
const GLOBAL_RATE_LIMITER_BATCH_READ_HISTOGRAM: &str = "global_rate_limiter_batch_read_seconds";

/// Trait for global rate limiting
#[async_trait]
pub trait GlobalRateLimiter: Send + Sync {
    /// Check if a key is rate limited, recording the count for this request.
    ///
    /// - Consult and refresh the local cache if needed
    /// - Enqueue an update to the key's count for async batch submission
    ///   to the global cache
    /// - Fail open if the local cache is stale or global cache unavailable
    ///
    /// Returns `EvalResult` indicating whether the request is allowed, limited, or failed open
    async fn check_limit(
        &self,
        key: &str,
        count: u64,
        timestamp: Option<DateTime<Utc>>,
    ) -> EvalResult;

    /// Check if a "custom key" is rate limited, recording the count for this request.
    /// The operation is the same as `check_limit`, other than how the key and threshold
    /// are determined:
    ///
    /// - Custom keys are defined in the custom_keys map, associated with an override value
    /// - If the key is present in the map, the override threshold value is applied
    /// - If the key is not present in the map, it is not subject to rate limiting
    ///
    /// Returns `EvalResult` indicating whether the request is allowed, limited, not applicable, or failed open
    async fn check_custom_limit(
        &self,
        key: &str,
        count: u64,
        timestamp: Option<DateTime<Utc>>,
    ) -> EvalResult;

    /// Close the update channel and flush remaining update records to global cache
    fn shutdown(&mut self);
}

/// Configuration for the global rate limiter
#[derive(Clone)]
pub struct GlobalRateLimiterConfig {
    /// Maximum count allowed per window for a given key (default for keys not in custom_keys)
    pub global_threshold: u64,
    /// Sliding window size (e.g., 60 seconds) - note the window is evaluated from the
    /// *previous bucket_interval* boundary relative to "now" so as not to undercount
    pub window_interval: Duration,
    /// Time bucket granularity (e.g., 10 seconds) - keys seen are accumulated into this
    /// granularity of time interval, and evaluated over window_interval for rate limiting
    pub bucket_interval: Duration,
    /// The interval over which a key will be rate limited if it exceeds the threshold
    pub rate_limit_interval: Duration,
    /// Redis key prefix (not including final separator)
    pub redis_key_prefix: String,
    /// How long to cache globally before refreshing from Redis
    pub global_cache_ttl: Duration,
    /// How long to cache locally before refreshing from Redis
    pub local_cache_ttl: Duration,
    /// Timeout for global cache read operations
    pub global_read_timeout: Duration,
    /// Timeout for global cache write operations
    pub global_write_timeout: Duration,
    /// Maximum entries in the local LRU cache
    pub local_cache_max_entries: u64,
    /// Maximum time before flushing current update batch to Redis
    pub batch_interval: Duration,
    /// Maximum update entries to collect prior to global cache flush
    pub batch_max_update_count: usize,
    /// Maximum batch key cardinality prior to global cache flush
    pub batch_max_key_cardinality: usize,
    /// Capacity of the mpsc channel for async global cache updates
    pub channel_capacity: usize,
    /// Per-key custom limits. Overrides the default limit for specific *more granular* keys.
    /// Example: global key API_TOKEN, custom key API_TOKEN:DISTINCT_ID
    pub custom_keys: HashMap<String, u64>,
}

impl Default for GlobalRateLimiterConfig {
    fn default() -> Self {
        Self {
            global_threshold: 100_000,
            window_interval: Duration::from_secs(60),
            bucket_interval: Duration::from_secs(10),
            rate_limit_interval: Duration::from_secs(60),
            redis_key_prefix: "@posthog/global_rate_limiter".to_string(),
            // 10 minutes - long enough to benefit from hot cache under high cardinality
            local_cache_ttl: Duration::from_secs(600),
            // long enough to avoid stale Redis entries piling up
            global_cache_ttl: Duration::from_secs(300),
            global_read_timeout: Duration::from_millis(10),
            global_write_timeout: Duration::from_millis(20),
            local_cache_max_entries: 300_000,
            batch_interval: Duration::from_millis(200),
            batch_max_update_count: 10000,
            batch_max_key_cardinality: 1000,
            channel_capacity: 1_000_000,
            custom_keys: HashMap::new(),
        }
    }
}

/// Internal struct for caching rate limit state
#[derive(Clone)]
struct CacheEntry {
    count: u64,
    window_start: DateTime<Utc>,
    window_end: DateTime<Utc>,
    expires_at: DateTime<Utc>,
}

/// Request to update a rate limit counter
struct UpdateRequest {
    key: String,
    bucket_id: i64,
    count: u64,
}
/// Mode for rate limit checking
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CheckMode {
    /// Use the global default limit for all keys
    Global,
    /// Only check keys present in custom_keys map, using their custom limits
    Custom,
}

/// Calculate bucket ID from timestamp and interval
fn bucket_from_timestamp(timestamp: DateTime<Utc>, bucket_interval: Duration) -> i64 {
    let unix = timestamp.timestamp();
    let bucket_secs = bucket_interval.as_secs() as i64;
    unix - (unix % bucket_secs)
}

/// Select a Redis client from the pool based on consistent key hashing.
/// Returns (client_ref, index) tuple for metric tagging.
fn select_redis_client(
    key: &str,
    clients: &[Arc<dyn Client + Send + Sync>],
) -> (Arc<dyn Client + Send + Sync>, usize) {
    if clients.len() == 1 {
        return (clients[0].clone(), 0);
    }
    let mut hasher = DefaultHasher::new();
    key.hash(&mut hasher);
    let idx = (hasher.finish() as usize) % clients.len();
    (clients[idx].clone(), idx)
}

/// Computed window parameters for rate limit evaluation from Redis
#[derive(Debug, Clone)]
struct ReadWindowParams {
    /// Start of the evaluated window
    window_start: DateTime<Utc>,
    /// End of the evaluated window
    window_end: DateTime<Utc>,
    /// Pre-computed Redis bucket keys for MGET
    bucket_keys: Vec<String>,
}

impl ReadWindowParams {
    /// Calculate window parameters from config, key, and timestamp
    fn new(config: &GlobalRateLimiterConfig, key: &str, timestamp: DateTime<Utc>) -> Self {
        let bucket_secs = config.bucket_interval.as_secs() as i64;
        let window_secs = config.window_interval.as_secs() as i64;
        let num_buckets = (window_secs / bucket_secs) as usize;
        let current_bucket = bucket_from_timestamp(timestamp, config.bucket_interval);
        let window_start_bucket = current_bucket - (num_buckets as i64 * bucket_secs);

        let window_start =
            DateTime::from_timestamp(window_start_bucket, 0).unwrap_or_else(Utc::now);
        let window_end =
            DateTime::from_timestamp(window_start_bucket + (num_buckets as i64 * bucket_secs), 0)
                .unwrap_or_else(Utc::now);

        let bucket_keys = (1..=num_buckets)
            .map(|i| {
                format!(
                    "{}:{}:{}",
                    config.redis_key_prefix,
                    key,
                    current_bucket - (i as i64 * bucket_secs)
                )
            })
            .collect();

        Self {
            window_start,
            window_end,
            bucket_keys,
        }
    }
}

/// Response returned when a key is rate limited
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GlobalRateLimitResponse {
    /// The key that was rate limited
    pub key: String,
    /// Current count in the window
    pub current_count: u64,
    /// The limit threshold that was exceeded
    pub threshold: u64,
    /// Start of the evaluated window (oldest bucket boundary)
    pub window_start: DateTime<Utc>,
    /// End of the evaluated window (current bucket boundary)
    pub window_end: DateTime<Utc>,
    /// The sliding window interval
    pub window_interval: Duration,
    /// Rate at which the sliding window will be updated
    pub update_interval: Duration,
}

/// Reason for failing open (not enforcing rate limit)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FailOpenReason {
    /// Redis read operation timed out
    RedisTimeout,
    /// Redis returned an error
    RedisError,
}

/// Result of evaluating a rate limit check
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EvalResult {
    /// Request allowed (under threshold)
    Allowed,
    /// Request rate limited, includes response metadata
    Limited(GlobalRateLimitResponse),
    /// Key not subject to rate limiting (custom key mode, unregistered key)
    NotApplicable,
    /// Failed open due to Redis error or timeout
    FailOpen { reason: FailOpenReason },
}

/// A distributed rate limiter using local LRU cache + Redis time-bucketed counters.
///
/// This limiter uses a sliding window algorithm with configurable bucket granularity.
/// Updates are batched and sent to Redis asynchronously via a background task
#[derive(Clone)]
pub struct GlobalRateLimiterImpl {
    config: GlobalRateLimiterConfig,
    redis_instances: Vec<Arc<dyn Client + Send + Sync>>,
    cache: Cache<String, CacheEntry>,
    update_tx: Option<mpsc::Sender<UpdateRequest>>,
}

#[async_trait]
impl GlobalRateLimiter for GlobalRateLimiterImpl {
    async fn check_limit(
        &self,
        key: &str,
        count: u64,
        timestamp: Option<DateTime<Utc>>,
    ) -> EvalResult {
        self.check_limit_internal(CheckMode::Global, key, count, timestamp)
            .await
    }

    async fn check_custom_limit(
        &self,
        key: &str,
        count: u64,
        timestamp: Option<DateTime<Utc>>,
    ) -> EvalResult {
        self.check_limit_internal(CheckMode::Custom, key, count, timestamp)
            .await
    }

    fn shutdown(&mut self) {
        // dropping the update_tx will close the channel and trigger final flush
        let _ = self.update_tx.take();
    }
}

impl GlobalRateLimiterImpl {
    /// Create a new GlobalRateLimiterImpl
    ///
    /// This spawns a background task for batching updates to Redis.
    /// Returns an error if `redis_instances` is empty.
    pub fn new(
        config: GlobalRateLimiterConfig,
        redis_instances: Vec<Arc<dyn Client + Send + Sync>>,
    ) -> anyhow::Result<Self> {
        if redis_instances.is_empty() {
            return Err(anyhow::anyhow!(
                "GlobalRateLimiterImpl requires at least one Redis instance"
            ));
        }

        let cache = Cache::builder()
            .max_capacity(config.local_cache_max_entries)
            .time_to_live(config.local_cache_ttl)
            .build();

        let (update_tx, update_rx) = mpsc::channel(config.channel_capacity);

        let limiter = Self {
            config: config.clone(),
            redis_instances: redis_instances.clone(),
            cache: cache.clone(),
            update_tx: Some(update_tx),
        };

        // Spawn background task
        Self::spawn_background_task(config, redis_instances, update_rx);

        Ok(limiter)
    }

    /// Check if a key is rate limited and enqueue a count update to the global cache.
    ///
    /// Returns:
    /// - `EvalResult::Limited(response)` if the key is rate limited, with metadata suitable for 429 responses
    /// - `EvalResult::Allowed` if the key is not currently rate limited
    /// - `EvalResult::NotApplicable` in Custom mode if the key is not in custom_keys map
    /// - `EvalResult::FailOpen { reason }` on Redis error or timeout
    ///
    /// Updates are always queued to the background task regardless of the return value.
    async fn check_limit_internal(
        &self,
        mode: CheckMode,
        key: &str,
        count: u64,
        timestamp: Option<DateTime<Utc>>,
    ) -> EvalResult {
        let threshold = match mode {
            CheckMode::Custom => {
                match self.config.custom_keys.get(key) {
                    Some(&custom_limit) => custom_limit,
                    None => return EvalResult::NotApplicable, // Key not in custom_keys map
                }
            }
            CheckMode::Global => self.config.global_threshold,
        };

        let now = timestamp.unwrap_or_else(Utc::now);

        // Enqueue update to background task
        self.enqueue_update(key, count, now);

        // Check local cache, refresh from Redis if missing/expired
        let entry = match self.check_refresh_entry(key, now).await {
            Ok(entry) => entry,
            Err(reason) => {
                // Redis error or timeout - fail open
                metrics::counter!(
                    GLOBAL_RATE_LIMITER_EVAL_COUNTER,
                    "result" => "fail_open",
                )
                .increment(1);
                return EvalResult::FailOpen { reason };
            }
        };

        // Determine if key is rate limited in the active window
        // Re-evaluate against threshold in case Custom mode has different limit than cached
        let is_limited = entry.count >= threshold;
        if is_limited {
            metrics::counter!(
                GLOBAL_RATE_LIMITER_EVAL_COUNTER,
                "result" => "limited",
            )
            .increment(1);

            EvalResult::Limited(GlobalRateLimitResponse {
                key: key.to_string(),
                current_count: entry.count,
                threshold,
                window_start: entry.window_start,
                window_end: entry.window_end,
                window_interval: self.config.window_interval,
                update_interval: self.config.bucket_interval,
            })
        } else {
            metrics::counter!(
                GLOBAL_RATE_LIMITER_EVAL_COUNTER,
                "result" => "allowed",
            )
            .increment(1);

            EvalResult::Allowed
        }
    }

    /// Calculate bucket ID from timestamp
    fn bucket_from_timestamp(timestamp: DateTime<Utc>, bucket_interval: Duration) -> i64 {
        bucket_from_timestamp(timestamp, bucket_interval)
    }

    /// Queue an update to be batched and sent to Redis
    fn enqueue_update(&self, key: &str, count: u64, now: DateTime<Utc>) {
        if count == 0 {
            return;
        }

        let bucket_id = Self::bucket_from_timestamp(now, self.config.bucket_interval);

        let update = UpdateRequest {
            key: key.to_string(),
            bucket_id,
            count,
        };

        // Non-blocking send - if channel is full, we still continue with the check
        if let Some(Err(e)) = self.update_tx.as_ref().map(|tx| tx.try_send(update)) {
            metrics::counter!(
                GLOBAL_RATE_LIMITER_ERROR_COUNTER,
                "step" => "enqueue_update",
                "result" => "error",
                "cause" => "channel_full",
            )
            .increment(1);
            error!(
                key = key,
                error = %e,
                "Failed to queue rate limit update, channel may be full"
            );
        }
    }

    /// Check local cache for entry, refresh from Redis if missing or expired
    async fn check_refresh_entry(
        &self,
        key: &str,
        timestamp: DateTime<Utc>,
    ) -> Result<CacheEntry, FailOpenReason> {
        // Check local cache first
        if let Some(entry) = self.cache.get(key) {
            // Check if entry is still valid
            if entry.expires_at > timestamp {
                metrics::counter!(
                    GLOBAL_RATE_LIMITER_CACHE_COUNTER,
                    "result" => "hit",
                )
                .increment(1);
                return Ok(entry);
            }
            // Entry expired, fall through to refresh
            metrics::counter!(
                GLOBAL_RATE_LIMITER_CACHE_COUNTER,
                "result" => "stale",
            )
            .increment(1);
        } else {
            metrics::counter!(
                GLOBAL_RATE_LIMITER_CACHE_COUNTER,
                "result" => "miss",
            )
            .increment(1);
        }

        // Fetch from Redis
        let entry = self.fetch_from_global(key, timestamp).await?;

        // Insert into cache
        self.cache.insert(key.to_string(), entry.clone());

        Ok(entry)
    }

    /// Fetch rate limit data for a single key from Redis global cache
    async fn fetch_from_global(
        &self,
        key: &str,
        timestamp: DateTime<Utc>,
    ) -> Result<CacheEntry, FailOpenReason> {
        let wp = ReadWindowParams::new(&self.config, key, timestamp);
        let (redis, redis_idx) = select_redis_client(key, &self.redis_instances);
        let redis_idx_str = redis_idx.to_string();

        // MGET with timeout
        let read_start = Instant::now();
        let counts = match tokio::time::timeout(
            self.config.global_read_timeout,
            redis.mget(wp.bucket_keys.clone()),
        )
        .await
        {
            Ok(Ok(counts)) => {
                metrics::counter!(
                    GLOBAL_RATE_LIMITER_RECORDS_COUNTER,
                    "op" => "redis_read",
                    "redis_idx" => redis_idx_str.clone(),
                )
                .increment(counts.len() as u64);
                metrics::histogram!(
                    GLOBAL_RATE_LIMITER_BATCH_READ_HISTOGRAM,
                    "redis_idx" => redis_idx_str.clone(),
                )
                .record(read_start.elapsed().as_millis() as f64);
                counts
            }
            Ok(Err(e)) => {
                metrics::counter!(
                    GLOBAL_RATE_LIMITER_ERROR_COUNTER,
                    "step" => "fetch_from_global",
                    "cause" => "redis_error",
                    "redis_idx" => redis_idx_str.clone(),
                )
                .increment(1);
                warn!(key = key, redis_idx = redis_idx, error = %e, "Failed to fetch rate limit from Redis");
                return Err(FailOpenReason::RedisError);
            }
            Err(_) => {
                metrics::counter!(
                    GLOBAL_RATE_LIMITER_ERROR_COUNTER,
                    "step" => "fetch_from_global",
                    "cause" => "timeout",
                    "redis_idx" => redis_idx_str.clone(),
                )
                .increment(1);
                warn!(
                    key = key,
                    redis_idx = redis_idx,
                    "Redis read timeout in fetch_from_global"
                );
                return Err(FailOpenReason::RedisTimeout);
            }
        };

        // Sum counts from all buckets, parsing bytes to u64
        let count: u64 = counts
            .iter()
            .filter_map(|c| {
                c.as_ref().and_then(|bytes| {
                    std::str::from_utf8(bytes)
                        .ok()
                        .and_then(|s| s.parse::<u64>().ok())
                })
            })
            .sum();

        // expires_at = timestamp + (bucket_interval / 2)
        let half_bucket =
            chrono::Duration::milliseconds(self.config.bucket_interval.as_millis() as i64 / 2);
        let expires_at = timestamp + half_bucket;

        Ok(CacheEntry {
            count,
            window_start: wp.window_start,
            window_end: wp.window_end,
            expires_at,
        })
    }

    /// Spawn the background task that batches updates to Redis
    ///
    /// The task terminates gracefully when the channel is closed (i.e., when
    /// the GlobalRateLimiter is dropped), flushing any remaining batch first.
    fn spawn_background_task(
        config: GlobalRateLimiterConfig,
        redis_instances: Vec<Arc<dyn Client + Send + Sync>>,
        mut update_rx: mpsc::Receiver<UpdateRequest>,
    ) {
        tokio::spawn(async move {
            // Pre-aggregate updates by (key, bucket_id) to avoid duplicate entries
            let mut key_counter: usize = 0;
            let mut batch: HashMap<(String, i64), u64> = HashMap::new();
            let mut flush_interval = interval(config.batch_interval);

            loop {
                tokio::select! {
                    result = update_rx.recv() => {
                        match result {
                            Some(req) => {
                                // Accumulate count for this (key, bucket_id) pair
                                key_counter += 1;
                                *batch.entry((req.key, req.bucket_id)).or_insert(0) += req.count;
                                if key_counter >= config.batch_max_update_count || batch.len() >= config.batch_max_key_cardinality {
                                    Self::flush_batch(&config, &redis_instances, &mut key_counter, &mut batch).await;
                                }
                            }
                            None => {
                                // Channel closed (sender dropped), flush remaining and exit
                                if !batch.is_empty() {
                                    Self::flush_batch(&config, &redis_instances, &mut key_counter, &mut batch).await;
                                }
                                break;
                            }
                        }
                    }
                    _ = flush_interval.tick() => {
                        if !batch.is_empty() {
                            Self::flush_batch(&config, &redis_instances, &mut key_counter, &mut batch).await;
                        }
                    }
                }
            }
        });
    }

    /// Flush a batch of updates to Redis, partitioned by target instance
    async fn flush_batch(
        config: &GlobalRateLimiterConfig,
        redis_instances: &[Arc<dyn Client + Send + Sync>],
        key_counter: &mut usize,
        batch: &mut HashMap<(String, i64), u64>,
    ) {
        *key_counter = 0_usize;
        if batch.is_empty() {
            return;
        }

        // Take ownership of batch, leaving empty HashMap in place
        let aggregated = std::mem::take(batch);

        // Partition items by target Redis instance
        let mut partitions: Vec<Vec<(String, i64)>> = vec![Vec::new(); redis_instances.len()];
        for ((key, bucket_id), count) in aggregated {
            let (_, idx) = select_redis_client(&key, redis_instances);
            let redis_key = format!("{}:{}:{}", config.redis_key_prefix, key, bucket_id);
            partitions[idx].push((redis_key, count as i64));
        }

        // Flush partitions in parallel
        let futures: Vec<_> = partitions
            .into_iter()
            .enumerate()
            .filter(|(_, items)| !items.is_empty())
            .map(|(idx, items)| {
                let redis = redis_instances[idx].clone();
                let ttl = config.global_cache_ttl.as_secs() as usize;
                let timeout = config.global_write_timeout;
                let redis_idx_str = idx.to_string();
                let write_records_count = items.len();

                async move {
                    let write_batch_start = Instant::now();
                    match tokio::time::timeout(timeout, redis.batch_incr_by_expire(items, ttl)).await
                    {
                        Ok(Ok(_)) => {
                            metrics::counter!(
                                GLOBAL_RATE_LIMITER_RECORDS_COUNTER,
                                "op" => "redis_write",
                                "redis_idx" => redis_idx_str.clone(),
                            )
                            .increment(write_records_count as u64);

                            metrics::histogram!(
                                GLOBAL_RATE_LIMITER_BATCH_WRITE_HISTOGRAM,
                                "redis_idx" => redis_idx_str.clone(),
                            )
                            .record(write_batch_start.elapsed().as_millis() as f64);
                        }
                        Ok(Err(e)) => {
                            metrics::counter!(
                                GLOBAL_RATE_LIMITER_ERROR_COUNTER,
                                "step" => "flush_batch",
                                "cause" => "redis_write",
                                "redis_idx" => redis_idx_str.clone(),
                            )
                            .increment(1);
                            warn!(error = %e, records = write_records_count, redis_idx = idx, "Failed to write rate limit batch to Redis");
                        }
                        Err(_) => {
                            metrics::counter!(
                                GLOBAL_RATE_LIMITER_ERROR_COUNTER,
                                "step" => "flush_batch",
                                "cause" => "timeout",
                                "redis_idx" => redis_idx_str.clone(),
                            )
                            .increment(1);
                            warn!(
                                records = write_records_count,
                                redis_idx = idx,
                                "Redis write timeout in flush_batch"
                            );
                        }
                    }
                }
            })
            .collect();

        futures::future::join_all(futures).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::MockRedisClient;

    fn test_config() -> GlobalRateLimiterConfig {
        GlobalRateLimiterConfig {
            global_threshold: 10,
            window_interval: Duration::from_secs(60),
            bucket_interval: Duration::from_secs(10),
            rate_limit_interval: Duration::from_secs(60),
            redis_key_prefix: "test:".to_string(),
            global_cache_ttl: Duration::from_secs(300),
            local_cache_ttl: Duration::from_secs(1),
            local_cache_max_entries: 100,
            batch_interval: Duration::from_millis(50),
            batch_max_update_count: 5,
            batch_max_key_cardinality: 10,
            channel_capacity: 100,
            custom_keys: HashMap::new(),
            global_read_timeout: Duration::from_millis(5),
            global_write_timeout: Duration::from_millis(10),
        }
    }

    #[test]
    fn test_bucket_from_timestamp_calculation() {
        let bucket_interval = Duration::from_secs(10);

        // Test exact bucket boundary
        let ts = DateTime::from_timestamp(1735000040, 0).unwrap();
        assert_eq!(
            GlobalRateLimiterImpl::bucket_from_timestamp(ts, bucket_interval),
            1735000040
        );

        // Test mid-bucket
        let ts = DateTime::from_timestamp(1735000047, 0).unwrap();
        assert_eq!(
            GlobalRateLimiterImpl::bucket_from_timestamp(ts, bucket_interval),
            1735000040
        );

        // Test end of bucket
        let ts = DateTime::from_timestamp(1735000049, 0).unwrap();
        assert_eq!(
            GlobalRateLimiterImpl::bucket_from_timestamp(ts, bucket_interval),
            1735000040
        );

        // Test next bucket
        let ts = DateTime::from_timestamp(1735000050, 0).unwrap();
        assert_eq!(
            GlobalRateLimiterImpl::bucket_from_timestamp(ts, bucket_interval),
            1735000050
        );
    }

    #[test]
    fn test_read_window_params_calculation() {
        let config = test_config(); // window=60s, bucket=10s

        // Test at exact bucket boundary
        let ts = DateTime::from_timestamp(1735000050, 0).unwrap();
        let wp = ReadWindowParams::new(&config, "test_key", ts);
        // 60s / 10s = 6 buckets
        assert_eq!(wp.bucket_keys.len(), 6);
        // window_start = current - (6 * 10) = 1735000050 - 60 = 1734999990
        assert_eq!(
            wp.window_start,
            DateTime::from_timestamp(1734999990, 0).unwrap()
        );
        // window_end = window_start + (6 * 10) = 1734999990 + 60 = 1735000050
        assert_eq!(
            wp.window_end,
            DateTime::from_timestamp(1735000050, 0).unwrap()
        );
    }

    #[test]
    fn test_read_window_params_mid_bucket() {
        let config = test_config();

        // Test mid-bucket (should truncate to bucket boundary)
        let ts = DateTime::from_timestamp(1735000057, 0).unwrap();
        let wp = ReadWindowParams::new(&config, "test_key", ts);
        // Bucket keys should be based on truncated current_bucket (1735000050)
        assert!(wp.bucket_keys[0].ends_with(":1735000040"));
        assert_eq!(
            wp.window_start,
            DateTime::from_timestamp(1734999990, 0).unwrap()
        );
    }

    #[test]
    fn test_read_window_params_different_config() {
        // Custom config: 30s window, 5s buckets
        let config = GlobalRateLimiterConfig {
            window_interval: Duration::from_secs(30),
            bucket_interval: Duration::from_secs(5),
            ..test_config()
        };

        let ts = DateTime::from_timestamp(1735000050, 0).unwrap();
        let wp = ReadWindowParams::new(&config, "test_key", ts);
        // 30s / 5s = 6 buckets
        assert_eq!(wp.bucket_keys.len(), 6);
        // window_start = 1735000050 - (6 * 5) = 1735000050 - 30 = 1735000020
        assert_eq!(
            wp.window_start,
            DateTime::from_timestamp(1735000020, 0).unwrap()
        );
    }

    #[test]
    fn test_read_window_params_bucket_keys() {
        let config = test_config();
        let ts = DateTime::from_timestamp(1735000050, 0).unwrap();
        let wp = ReadWindowParams::new(&config, "test_key", ts);

        // Should be 6 keys (num_buckets) for buckets going back from current
        assert_eq!(wp.bucket_keys.len(), 6);
        assert_eq!(wp.bucket_keys[0], "test::test_key:1735000040");
        assert_eq!(wp.bucket_keys[1], "test::test_key:1735000030");
        assert_eq!(wp.bucket_keys[2], "test::test_key:1735000020");
        assert_eq!(wp.bucket_keys[3], "test::test_key:1735000010");
        assert_eq!(wp.bucket_keys[4], "test::test_key:1735000000");
        assert_eq!(wp.bucket_keys[5], "test::test_key:1734999990");
    }

    #[tokio::test]
    async fn test_not_limited_when_under_threshold() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let config = test_config(); // limit = 10

        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        // Pre-populate cache with count under the limit
        let now = Utc::now();
        limiter.cache.insert(
            "test_key".to_string(),
            CacheEntry {
                count: 5,
                window_start: now - chrono::Duration::seconds(60),
                window_end: now,
                expires_at: now + chrono::Duration::seconds(120),
            },
        );

        // Should not be limited when count is under limit
        let result = limiter.check_limit("test_key", 1, None).await;

        assert!(
            matches!(result, EvalResult::Allowed),
            "Should return Allowed when under threshold, got {result:?}"
        );
    }

    #[tokio::test]
    async fn test_limited_when_at_threshold() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let config = test_config(); // limit = 10

        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        // Pre-populate cache with count at the limit
        let now = Utc::now();
        limiter.cache.insert(
            "test_key".to_string(),
            CacheEntry {
                count: 10,
                window_start: now - chrono::Duration::seconds(60),
                window_end: now,
                expires_at: now + chrono::Duration::seconds(120),
            },
        );

        let result = limiter.check_limit("test_key", 1, None).await;

        assert!(
            matches!(result, EvalResult::Limited(_)),
            "Should be Limited when at/over threshold, got {result:?}"
        );
    }

    #[tokio::test]
    async fn test_rate_limit_response_fields() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let config = test_config(); // limit=10, window=60s, bucket=10s

        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        let now = Utc::now();
        let window_start = now - chrono::Duration::seconds(60);
        limiter.cache.insert(
            "test_key".to_string(),
            CacheEntry {
                count: 15,
                window_start,
                window_end: now,
                expires_at: now + chrono::Duration::seconds(120),
            },
        );

        let result = limiter.check_limit("test_key", 1, None).await;

        let response = match result {
            EvalResult::Limited(r) => r,
            other => panic!("Expected Limited, got {other:?}"),
        };

        assert_eq!(response.key, "test_key");
        assert_eq!(response.current_count, 15);
        assert_eq!(response.threshold, 10);
        // window_start/window_end come from cached entry
        assert_eq!(response.window_start, window_start);
        assert_eq!(response.window_end, now);
        // window_interval is the sliding window size
        assert_eq!(response.window_interval, Duration::from_secs(60));
        // update_interval is bucket_interval (rate at which window updates)
        assert_eq!(response.update_interval, Duration::from_secs(10));
    }

    #[tokio::test]
    async fn test_cache_miss_with_empty_redis_returns_allowed() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let config = test_config();

        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        // Don't populate cache - cache miss triggers Redis fetch which returns empty data
        // Empty Redis response means count=0 which is under threshold (Allowed)
        let result = limiter.check_limit("unknown_key", 1000, None).await;

        assert!(
            matches!(result, EvalResult::Allowed),
            "Empty Redis response should return Allowed (count=0 < threshold), got {result:?}"
        );
    }

    #[tokio::test]
    async fn test_cache_hit_avoids_redis() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let config = test_config();

        let limiter = GlobalRateLimiterImpl::new(config.clone(), vec![client.clone()]).unwrap();

        // Manually populate cache
        let now = Utc::now();
        limiter.cache.insert(
            "cached_key".to_string(),
            CacheEntry {
                count: 5,
                window_start: now - chrono::Duration::seconds(60),
                window_end: now,
                expires_at: now + chrono::Duration::seconds(120),
            },
        );

        // This should use cache and not hit Redis
        let result = limiter.check_limit("cached_key", 1, None).await;

        assert!(
            matches!(result, EvalResult::Allowed),
            "Should return Allowed with cached count of 5, got {result:?}"
        );

        // Verify no mget calls were made (cache was used)
        let calls = client.get_calls();
        let mget_calls: Vec<_> = calls.iter().filter(|c| c.op == "mget").collect();
        assert!(
            mget_calls.is_empty(),
            "Should not have called mget when cache hit"
        );
    }

    #[tokio::test]
    async fn test_update_queued_even_when_limited() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let config = test_config();

        let limiter = GlobalRateLimiterImpl::new(config, vec![client.clone()]).unwrap();

        // Manually set cache to be at limit
        let now = Utc::now();
        limiter.cache.insert(
            "limited_key".to_string(),
            CacheEntry {
                count: 10,
                window_start: now - chrono::Duration::seconds(60),
                window_end: now,
                expires_at: now + chrono::Duration::seconds(120),
            },
        );

        // This should be limited but still queue an update
        let result = limiter.check_limit("limited_key", 1, None).await;

        assert!(
            matches!(result, EvalResult::Limited(_)),
            "Should be Limited, got {result:?}"
        );

        // Give background task time to process
        tokio::time::sleep(Duration::from_millis(100)).await;

        // Verify batch_incr_by_expire was called
        let calls = client.get_calls();
        let batch_calls: Vec<_> = calls
            .iter()
            .filter(|c| c.op == "batch_incr_by_expire")
            .collect();
        assert!(
            !batch_calls.is_empty(),
            "Should have queued update to Redis"
        );
    }

    #[test]
    fn test_config_defaults() {
        let config = GlobalRateLimiterConfig::default();
        assert_eq!(config.global_threshold, 100_000);
        assert_eq!(config.window_interval, Duration::from_secs(60));
        assert_eq!(config.bucket_interval, Duration::from_secs(10));
        assert_eq!(config.redis_key_prefix, "@posthog/global_rate_limiter");
        assert_eq!(config.global_cache_ttl, Duration::from_secs(300));
        assert_eq!(config.local_cache_ttl, Duration::from_secs(600));
        assert_eq!(config.global_read_timeout, Duration::from_millis(10));
        assert_eq!(config.global_write_timeout, Duration::from_millis(20));
        assert_eq!(config.local_cache_max_entries, 300_000);
        assert_eq!(config.batch_interval, Duration::from_millis(200));
        assert_eq!(config.batch_max_update_count, 10000);
        assert_eq!(config.batch_max_key_cardinality, 1000);
        assert_eq!(config.channel_capacity, 1_000_000);
        assert!(config.custom_keys.is_empty());
    }

    #[tokio::test]
    async fn test_custom_mode_unknown_key_returns_not_applicable() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let mut config = test_config();
        config.custom_keys.insert("known_key".to_string(), 5);

        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        // Unknown key in Custom mode should return NotApplicable immediately
        let result = limiter.check_custom_limit("unknown_key", 100, None).await;

        assert!(
            matches!(result, EvalResult::NotApplicable),
            "Custom mode should return NotApplicable for unknown keys, got {result:?}"
        );
    }

    #[tokio::test]
    async fn test_custom_mode_uses_custom_limit() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let mut config = test_config();
        // Set a custom limit of 5 for this key (global limit is 10)
        config.custom_keys.insert("custom_key".to_string(), 5);

        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        // Manually set cache to 5 (at custom limit of 5)
        let now = Utc::now();
        limiter.cache.insert(
            "custom_key".to_string(),
            CacheEntry {
                count: 5,
                window_start: now - chrono::Duration::seconds(60),
                window_end: now,
                expires_at: now + chrono::Duration::seconds(120),
            },
        );

        // count 5 >= limit 5, should be limited
        let result = limiter.check_custom_limit("custom_key", 1, None).await;

        assert!(
            matches!(result, EvalResult::Limited(_)),
            "Should be Limited when reaching custom limit, got {result:?}"
        );
    }

    #[tokio::test]
    async fn test_custom_mode_under_custom_limit() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let mut config = test_config();
        // Set a custom limit of 10 for this key
        config.custom_keys.insert("custom_key".to_string(), 10);

        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        // Manually set cache to 5 (under custom limit of 10)
        let now = Utc::now();
        limiter.cache.insert(
            "custom_key".to_string(),
            CacheEntry {
                count: 5,
                window_start: now - chrono::Duration::seconds(60),
                window_end: now,
                expires_at: now + chrono::Duration::seconds(120),
            },
        );

        // count 5 < limit 10, should not be limited
        let result = limiter.check_custom_limit("custom_key", 1, None).await;

        assert!(
            matches!(result, EvalResult::Allowed),
            "Should return Allowed when under custom limit, got {result:?}"
        );
    }

    #[tokio::test]
    async fn test_custom_key_behavior() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let mut config = test_config();
        config.custom_keys.insert("custom_a".to_string(), 5);
        config.custom_keys.insert("custom_b".to_string(), 10);

        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        // Pre-populate cache so we get deterministic results
        let now = Utc::now();
        limiter.cache.insert(
            "custom_a".to_string(),
            CacheEntry {
                count: 10, // over limit of 5
                window_start: now - chrono::Duration::seconds(60),
                window_end: now,
                expires_at: now + chrono::Duration::seconds(120),
            },
        );

        // custom_a is in custom_keys, should be evaluated and limited (count 10 >= limit 5)
        let result = limiter.check_custom_limit("custom_a", 1, None).await;
        assert!(
            matches!(result, EvalResult::Limited(_)),
            "custom_a should be Limited, got {result:?}"
        );

        // unknown_key is NOT in custom_keys, should return NotApplicable immediately
        let result = limiter.check_custom_limit("unknown_key", 1, None).await;
        assert!(
            matches!(result, EvalResult::NotApplicable),
            "unknown_key should return NotApplicable (not in custom_keys), got {result:?}"
        );

        // empty key is NOT in custom_keys, should return NotApplicable immediately
        let result = limiter.check_custom_limit("", 1, None).await;
        assert!(
            matches!(result, EvalResult::NotApplicable),
            "empty key should return NotApplicable (not in custom_keys), got {result:?}"
        );
    }

    #[tokio::test]
    async fn test_batch_flush_on_max_update_count() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let mut config = test_config();
        // Low update count threshold, high key cardinality threshold
        config.batch_max_update_count = 3;
        config.batch_max_key_cardinality = 100;
        config.batch_interval = Duration::from_secs(60); // Long interval so it won't trigger

        let limiter = GlobalRateLimiterImpl::new(config, vec![client.clone()]).unwrap();

        // Pre-populate cache so update_eval_key_internal doesn't block on Redis fetch
        let now = Utc::now();
        limiter.cache.insert(
            "key_a".to_string(),
            CacheEntry {
                count: 1,
                window_start: now - chrono::Duration::seconds(60),
                window_end: now,
                expires_at: now + chrono::Duration::seconds(120),
            },
        );

        // Send 3 updates to the same key - should trigger flush on update count
        for _ in 0..3 {
            let _ = limiter.check_limit("key_a", 1, None).await;
        }

        // Give background task time to process
        tokio::time::sleep(Duration::from_millis(50)).await;

        let calls = client.get_calls();
        let batch_calls: Vec<_> = calls
            .iter()
            .filter(|c| c.op == "batch_incr_by_expire")
            .collect();
        assert!(
            !batch_calls.is_empty(),
            "Should have flushed batch after reaching max update count"
        );
    }

    #[tokio::test]
    async fn test_batch_flush_on_max_key_cardinality() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let mut config = test_config();
        // High update count threshold, low key cardinality threshold
        config.batch_max_update_count = 100;
        config.batch_max_key_cardinality = 3;
        config.batch_interval = Duration::from_secs(60); // Long interval so it won't trigger

        let limiter = GlobalRateLimiterImpl::new(config, vec![client.clone()]).unwrap();

        // Pre-populate cache for multiple keys
        let now = Utc::now();
        for i in 0..3 {
            limiter.cache.insert(
                format!("key_{i}"),
                CacheEntry {
                    count: 1,
                    window_start: now - chrono::Duration::seconds(60),
                    window_end: now,
                    expires_at: now + chrono::Duration::seconds(120),
                },
            );
        }

        // Send updates to 3 different keys - should trigger flush on key cardinality
        for i in 0..3 {
            let _ = limiter.check_limit(&format!("key_{i}"), 1, None).await;
        }

        // Give background task time to process
        tokio::time::sleep(Duration::from_millis(50)).await;

        let calls = client.get_calls();
        let batch_calls: Vec<_> = calls
            .iter()
            .filter(|c| c.op == "batch_incr_by_expire")
            .collect();
        assert!(
            !batch_calls.is_empty(),
            "Should have flushed batch after reaching max key cardinality"
        );
    }

    #[tokio::test]
    async fn test_batch_flush_update_count_before_cardinality() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let mut config = test_config();
        // Update count threshold lower than cardinality threshold
        config.batch_max_update_count = 5;
        config.batch_max_key_cardinality = 10;
        config.batch_interval = Duration::from_secs(60);

        let limiter = GlobalRateLimiterImpl::new(config, vec![client.clone()]).unwrap();

        // Pre-populate cache
        let now = Utc::now();
        for i in 0..3 {
            limiter.cache.insert(
                format!("key_{i}"),
                CacheEntry {
                    count: 1,
                    window_start: now - chrono::Duration::seconds(60),
                    window_end: now,
                    expires_at: now + chrono::Duration::seconds(120),
                },
            );
        }

        // Send 5 updates across 3 keys (under cardinality limit, at update count limit)
        let _ = limiter.check_limit("key_0", 1, None).await;
        let _ = limiter.check_limit("key_0", 1, None).await;
        let _ = limiter.check_limit("key_1", 1, None).await;
        let _ = limiter.check_limit("key_1", 1, None).await;
        let _ = limiter.check_limit("key_2", 1, None).await;

        // Give background task time to process
        tokio::time::sleep(Duration::from_millis(50)).await;

        let calls = client.get_calls();
        let batch_calls: Vec<_> = calls
            .iter()
            .filter(|c| c.op == "batch_incr_by_expire")
            .collect();
        assert!(
            !batch_calls.is_empty(),
            "Should have flushed batch when update count reached before cardinality"
        );
    }

    #[test]
    fn test_new_returns_error_for_empty_redis_instances() {
        let config = test_config();
        let result = GlobalRateLimiterImpl::new(config, vec![]);
        assert!(result.is_err());
        let err = match result {
            Err(e) => e,
            Ok(_) => panic!("Expected error for empty redis_instances"),
        };
        assert!(
            err.to_string()
                .contains("requires at least one Redis instance"),
            "Error message should mention Redis instance requirement, got: {err}"
        );
    }

    #[test]
    fn test_select_redis_client_single_instance() {
        let client = Arc::new(MockRedisClient::new()) as Arc<dyn Client + Send + Sync>;
        let clients = vec![client];

        let (_, idx) = select_redis_client("any_key", &clients);
        assert_eq!(idx, 0, "Single instance should always return index 0");

        let (_, idx) = select_redis_client("another_key", &clients);
        assert_eq!(idx, 0, "Single instance should always return index 0");
    }

    #[test]
    fn test_select_redis_client_consistent_mapping() {
        let clients: Vec<Arc<dyn Client + Send + Sync>> = (0..3)
            .map(|_| Arc::new(MockRedisClient::new()) as Arc<dyn Client + Send + Sync>)
            .collect();

        let key = "test_key_for_consistency";

        // Call multiple times with same key
        let (_, idx1) = select_redis_client(key, &clients);
        let (_, idx2) = select_redis_client(key, &clients);
        let (_, idx3) = select_redis_client(key, &clients);

        assert_eq!(idx1, idx2, "Same key should always map to same instance");
        assert_eq!(idx2, idx3, "Same key should always map to same instance");
    }

    #[test]
    fn test_select_redis_client_distributes_keys() {
        let clients: Vec<Arc<dyn Client + Send + Sync>> = (0..3)
            .map(|_| Arc::new(MockRedisClient::new()) as Arc<dyn Client + Send + Sync>)
            .collect();

        let mut indices = std::collections::HashSet::new();
        // Try enough keys that we should hit multiple instances
        for i in 0..100 {
            let key = format!("key_{i}");
            let (_, idx) = select_redis_client(&key, &clients);
            indices.insert(idx);
        }

        // With 100 keys and 3 instances, we should hit all 3
        assert!(
            indices.len() > 1,
            "Multiple keys should distribute across instances"
        );
    }
}
