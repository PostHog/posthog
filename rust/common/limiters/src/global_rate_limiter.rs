use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use chrono::{DateTime, Utc};
use common_redis::Client;
use moka::sync::Cache;
use tokio::sync::mpsc;
use tokio::time::interval;
use tracing::{error, warn};

// multiple of window_duration to limit local cache entry staleness for a given key
// before we fail open if Redis is unavailable for an extended period
const LOCAL_STALENESS_MULTIPLIER: u64 = 5;

/// Mode for rate limit checking
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CheckMode {
    /// Use the global default limit for all keys
    Global,
    /// Only check keys present in custom_keys map, using their custom limits
    Custom,
}

/// Configuration for the global rate limiter
#[derive(Clone)]
pub struct GlobalRateLimiterConfig {
    /// Maximum count allowed per window for a given key (default for keys not in custom_keys)
    pub global_limit: u64,
    /// Sliding window size (e.g., 60 seconds) - note the window is evaluated from the
    /// *previous bucket_interval* boundary relative to "now" so as not to undercount
    pub window_duration: Duration,
    /// Time bucket granularity (e.g., 10 seconds) - keys seen are accumulated into this
    /// granularity of time interval, and evaluated over window_duration for rate limiting
    pub bucket_interval: Duration,
    /// Redis key prefix (not including final separator)
    pub redis_key_prefix: String,
    /// How long to cache globally before refreshing from Redis
    pub global_cache_ttl: Duration,
    /// How long to cache locally before refreshing from Redis
    pub local_cache_ttl: Duration,
    /// Maximum entries in the local LRU cache
    pub local_cache_max_entries: u64,
    /// Maximum time before flushing current update batch to Redis
    pub batch_interval: Duration,
    /// Maximum keys collected in update batch before flushing to Redis.
    /// NOTE: each batch update makes two potentially expensive Redis calls:
    ///     - batch_incr_by_expire_nx call on every (key, count) in batch
    ///     - batch mget call w/N keys (N == num_buckets_in_window * unique_keys_in_batch)
    /// Due to this ^ keep batch_max_size reasonable (1k or less?)
    pub batch_max_size: usize,
    /// Capacity of the mpsc channel for async updates
    ///     - update keys and count sums in Redis scoped to appropriate bucket_interval(s)
    ///     - refresh local cache for affected keys over window_duration starting at previous bucket_interval
    pub channel_capacity: usize,
    /// Per-key custom limits. Overrides the default limit for specific *more granular* keys.
    /// Example: global key API_TOKEN, custom key API_TOKEN:DISTINCT_ID
    pub custom_keys: HashMap<String, u64>,
}

impl Default for GlobalRateLimiterConfig {
    fn default() -> Self {
        Self {
            // global default limit: 100k items per minute (sliding window)
            global_limit: 100_000,
            window_duration: Duration::from_secs(60),
            bucket_interval: Duration::from_secs(10),
            redis_key_prefix: "@posthog/globalratelimit".to_string(),
            // multiple of window duration, since we eval at bucket interval delay
            local_cache_ttl: Duration::from_secs(120),
            // long enough to avoid stale Redis entries piling up
            global_cache_ttl: Duration::from_secs(300),
            local_cache_max_entries: 400_000,
            batch_interval: Duration::from_millis(100),
            batch_max_size: 1000,
            channel_capacity: 10000,
            custom_keys: HashMap::new(),
        }
    }
}

/// Internal struct for caching rate limit state
#[derive(Clone)]
struct CachedEntry {
    count: u64,
    /// The bucket_id of the start of the window we evaluated
    window_start_bucket: i64,
}

/// Request to update a rate limit counter
struct UpdateRequest {
    key: String,
    bucket_id: i64,
    count: u64,
}

/// Computed window parameters for rate limit evaluation
#[derive(Debug, Clone, PartialEq, Eq)]
struct WindowParams {
    /// Size of each bucket in seconds
    bucket_secs: i64,
    /// Number of buckets in the window
    num_buckets: usize,
    /// The current bucket boundary (truncated timestamp)
    current_bucket: i64,
    /// The oldest bucket in the evaluation window
    window_start_bucket: i64,
}

impl WindowParams {
    /// Calculate window parameters from config and current unix timestamp
    fn new(config: &GlobalRateLimiterConfig, unix_timestamp: i64) -> Self {
        let bucket_secs = config.bucket_interval.as_secs() as i64;
        let window_secs = config.window_duration.as_secs() as i64;
        let num_buckets = (window_secs / bucket_secs) as usize;
        let current_bucket = unix_timestamp - (unix_timestamp % bucket_secs);
        let window_start_bucket = current_bucket - (num_buckets as i64 * bucket_secs);

        Self {
            bucket_secs,
            num_buckets,
            current_bucket,
            window_start_bucket,
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
    /// Duration of the sliding window
    pub window_duration: Duration,
    /// Start of the evaluated window (oldest bucket boundary)
    pub window_start: DateTime<Utc>,
    /// End of the evaluated window (current bucket boundary)
    pub window_end: DateTime<Utc>,
}

/// A distributed rate limiter using local LRU cache + Redis time-bucketed counters.
///
/// This limiter uses a sliding window algorithm with configurable bucket granularity.
/// Updates are batched and sent to Redis asynchronously via a background task.
pub struct GlobalRateLimiter {
    config: GlobalRateLimiterConfig,
    cache: Cache<String, CachedEntry>,
    #[allow(dead_code)] // Retained for potential future synchronous Redis queries
    redis: Arc<dyn Client + Send + Sync>,
    update_tx: mpsc::Sender<UpdateRequest>,
}

impl GlobalRateLimiter {
    /// Create a new GlobalRateLimiter
    ///
    /// This spawns a background task for batching updates to Redis.
    pub fn new(
        config: GlobalRateLimiterConfig,
        redis: Arc<dyn Client + Send + Sync>,
    ) -> anyhow::Result<Self> {
        let cache = Cache::builder()
            .max_capacity(config.local_cache_max_entries)
            .time_to_live(config.local_cache_ttl)
            .build();

        let (update_tx, update_rx) = mpsc::channel(config.channel_capacity);

        let limiter = Self {
            config: config.clone(),
            cache: cache.clone(),
            redis: redis.clone(),
            update_tx,
        };

        // Spawn background task
        Self::spawn_background_task(config, redis, cache, update_rx);

        Ok(limiter)
    }

    /// Check if a key is rate limited
    ///
    /// Returns:
    /// - `Ok(Some(message))` if the key is rate limited, with a message suitable for 429 responses
    /// - `Ok(None)` if the key is not currently rate limited
    /// - `Err(_)` if an error occurred (caller should decide how to handle, e.g., fail open)
    ///
    /// In `Custom` mode, returns `Ok(None)` immediately if the key is not in the custom_keys map.
    /// Updates are always queued to the background task regardless of the return value.
    pub async fn check_rate_limit(
        &self,
        mode: CheckMode,
        key: &str,
        count: u64,
        timestamp: Option<DateTime<Utc>>,
    ) -> anyhow::Result<Option<GlobalRateLimitResponse>> {
        // In Custom mode, check if key is in custom_keys map
        let limit = match mode {
            CheckMode::Custom => {
                match self.config.custom_keys.get(key) {
                    Some(&custom_limit) => custom_limit,
                    None => return Ok(None), // Key not in custom_keys, not rate limited
                }
            }
            CheckMode::Global => self.config.global_limit,
        };

        let now = timestamp.unwrap_or_else(Utc::now);
        let bucket_id = Self::bucket_id(now, self.config.bucket_interval);

        // Always queue the update first
        let update = UpdateRequest {
            key: key.to_string(),
            bucket_id,
            count,
        };

        // Non-blocking send - if channel is full, we still continue with the check
        if let Err(e) = self.update_tx.try_send(update) {
            // TODO(eli): stat this also!
            error!(
                key = key,
                error = %e,
                "Failed to queue rate limit update, channel may be full"
            );
        }

        // Check cache first
        let (current_count, window_start_bucket) = if let Some(entry) = self.cache.get(key) {
            // Cache hit - use cached count and window info
            (entry.count, entry.window_start_bucket)
        } else {
            // Cache miss - fail open and await background task to populate cache.
            // Since we evaluate for the "active window" prior to this bucket interval, we
            // will promptly see rate limit results for subsequent requests w/same key
            return Ok(None);
        };

        // Staleness check: if cached window is too old, fail open, await the
        // async update to eval the next time we see this key
        let max_age = (self.config.window_duration.as_secs() * LOCAL_STALENESS_MULTIPLIER) as i64;
        if now.timestamp() - window_start_bucket > max_age {
            // TODO(eli): stat this also!
            return Ok(None);
        }

        // Determine if key is rate limited in the active window
        if current_count >= limit {
            let num_buckets =
                self.config.window_duration.as_secs() / self.config.bucket_interval.as_secs();
            let bucket_secs = self.config.bucket_interval.as_secs() as i64;
            // Use the cached window boundaries
            let window_start = DateTime::from_timestamp(window_start_bucket, 0).unwrap_or(now);
            let window_end = DateTime::from_timestamp(
                window_start_bucket + (num_buckets as i64 * bucket_secs),
                0,
            )
            .unwrap_or(now);

            Ok(Some(GlobalRateLimitResponse {
                key: key.to_string(),
                current_count,
                threshold: limit,
                window_duration: self.config.window_duration,
                window_start,
                window_end,
            }))
        } else {
            Ok(None)
        }
    }

    /// Calculate bucket ID from timestamp
    fn bucket_id(timestamp: DateTime<Utc>, bucket_interval: Duration) -> i64 {
        let unix = timestamp.timestamp();
        let bucket_secs = bucket_interval.as_secs() as i64;
        unix - (unix % bucket_secs)
    }

    /// Spawn the background task that batches updates to Redis
    ///
    /// The task terminates gracefully when the channel is closed (i.e., when
    /// the GlobalRateLimiter is dropped), flushing any remaining batch first.
    fn spawn_background_task(
        config: GlobalRateLimiterConfig,
        redis: Arc<dyn Client + Send + Sync>,
        cache: Cache<String, CachedEntry>,
        mut update_rx: mpsc::Receiver<UpdateRequest>,
    ) {
        tokio::spawn(async move {
            // Pre-aggregate updates by (key, bucket_id) to avoid duplicate entries
            let mut batch: HashMap<(String, i64), u64> = HashMap::new();
            let mut flush_interval = interval(config.batch_interval);

            loop {
                tokio::select! {
                    result = update_rx.recv() => {
                        match result {
                            Some(req) => {
                                // Accumulate count for this (key, bucket_id) pair
                                *batch.entry((req.key, req.bucket_id)).or_insert(0) += req.count;
                                if batch.len() >= config.batch_max_size {
                                    Self::flush_batch(&config, &redis, &cache, &mut batch).await;
                                }
                            }
                            None => {
                                // Channel closed (sender dropped), flush remaining and exit
                                if !batch.is_empty() {
                                    Self::flush_batch(&config, &redis, &cache, &mut batch).await;
                                }
                                break;
                            }
                        }
                    }
                    _ = flush_interval.tick() => {
                        if !batch.is_empty() {
                            Self::flush_batch(&config, &redis, &cache, &mut batch).await;
                        }
                    }
                }
            }
        });
    }

    /// Flush a batch of updates to Redis
    async fn flush_batch(
        config: &GlobalRateLimiterConfig,
        redis: &Arc<dyn Client + Send + Sync>,
        cache: &Cache<String, CachedEntry>,
        batch: &mut HashMap<(String, i64), u64>,
    ) {
        if batch.is_empty() {
            return;
        }

        // Take ownership of batch, leaving empty HashMap in place
        let aggregated = std::mem::take(batch);

        // Prepare items for batch_incr_by_expire_nx
        let items: Vec<(String, i64)> = aggregated
            .iter()
            .map(|((key, bucket_id), count)| {
                let redis_key = format!("{}:{}:{}", config.redis_key_prefix, key, bucket_id);
                (redis_key, *count as i64)
            })
            .collect();

        // Send batch to Redis with TTL dependent on window duration
        if let Err(e) = redis
            .batch_incr_by_expire_nx(items, config.global_cache_ttl.as_secs() as usize)
            .await
        {
            // TODO(eli): stat this also!
            warn!(error = %e, "Failed to flush rate limit batch to Redis");
            return;
        }

        // Refresh cache for affected keys with a single batched MGET
        let now = Utc::now();
        let unique_keys: Vec<String> = aggregated
            .keys()
            .map(|(k, _)| k.clone())
            .collect::<std::collections::HashSet<_>>()
            .into_iter()
            .collect();

        if unique_keys.is_empty() {
            return;
        }

        let wp = WindowParams::new(config, now.timestamp());

        // Build all bucket keys for all unique keys in one vector
        // Layout: [key0_bucket1, key0_bucket2, ..., key0_bucketN, key1_bucket1, ...]
        let all_bucket_keys: Vec<String> = unique_keys
            .iter()
            .flat_map(|key| {
                (1..=wp.num_buckets).map(move |i| {
                    format!(
                        "{}:{}:{}",
                        config.redis_key_prefix,
                        key,
                        wp.current_bucket - (i as i64 * wp.bucket_secs)
                    )
                })
            })
            .collect();

        // Single MGET for all keys
        let all_counts = match redis.mget(all_bucket_keys).await {
            Ok(counts) => counts,
            Err(e) => {
                // TODO(eli): stat this also!
                warn!(error = %e, "Failed to refresh cache after batch flush");
                return;
            }
        };

        // Partition results back to keys and sum counts, insert into cache
        for (i, key) in unique_keys.into_iter().enumerate() {
            let start = i * wp.num_buckets;
            let end = start + wp.num_buckets;
            let count: u64 = all_counts[start..end]
                .iter()
                .filter_map(|c| c.map(|v| v.max(0) as u64))
                .sum();

            cache.insert(
                key,
                CachedEntry {
                    count,
                    window_start_bucket: wp.window_start_bucket,
                },
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::MockRedisClient;

    fn test_config() -> GlobalRateLimiterConfig {
        GlobalRateLimiterConfig {
            global_limit: 10,
            window_duration: Duration::from_secs(60),
            bucket_interval: Duration::from_secs(10),
            redis_key_prefix: "test:".to_string(),
            global_cache_ttl: Duration::from_secs(300),
            local_cache_ttl: Duration::from_secs(1),
            local_cache_max_entries: 100,
            batch_interval: Duration::from_millis(50),
            batch_max_size: 5,
            channel_capacity: 100,
            custom_keys: HashMap::new(),
        }
    }

    #[test]
    fn test_bucket_id_calculation() {
        let bucket_interval = Duration::from_secs(10);

        // Test exact bucket boundary
        let ts = DateTime::from_timestamp(1735000040, 0).unwrap();
        assert_eq!(
            GlobalRateLimiter::bucket_id(ts, bucket_interval),
            1735000040
        );

        // Test mid-bucket
        let ts = DateTime::from_timestamp(1735000047, 0).unwrap();
        assert_eq!(
            GlobalRateLimiter::bucket_id(ts, bucket_interval),
            1735000040
        );

        // Test end of bucket
        let ts = DateTime::from_timestamp(1735000049, 0).unwrap();
        assert_eq!(
            GlobalRateLimiter::bucket_id(ts, bucket_interval),
            1735000040
        );

        // Test next bucket
        let ts = DateTime::from_timestamp(1735000050, 0).unwrap();
        assert_eq!(
            GlobalRateLimiter::bucket_id(ts, bucket_interval),
            1735000050
        );
    }

    #[test]
    fn test_window_params_calculation() {
        let config = test_config(); // window=60s, bucket=10s

        // Test at exact bucket boundary
        let wp = WindowParams::new(&config, 1735000050);
        assert_eq!(wp.bucket_secs, 10);
        assert_eq!(wp.num_buckets, 6); // 60s / 10s = 6 buckets
        assert_eq!(wp.current_bucket, 1735000050);
        // window_start = current - (6 * 10) = 1735000050 - 60 = 1734999990
        assert_eq!(wp.window_start_bucket, 1734999990);
    }

    #[test]
    fn test_window_params_mid_bucket() {
        let config = test_config();

        // Test mid-bucket (should truncate to bucket boundary)
        let wp = WindowParams::new(&config, 1735000057);
        assert_eq!(wp.current_bucket, 1735000050); // Truncated
        assert_eq!(wp.window_start_bucket, 1734999990);
    }

    #[test]
    fn test_window_params_different_config() {
        // Custom config: 30s window, 5s buckets
        let config = GlobalRateLimiterConfig {
            window_duration: Duration::from_secs(30),
            bucket_interval: Duration::from_secs(5),
            ..test_config()
        };

        let wp = WindowParams::new(&config, 1735000050);
        assert_eq!(wp.bucket_secs, 5);
        assert_eq!(wp.num_buckets, 6); // 30s / 5s = 6 buckets
        assert_eq!(wp.current_bucket, 1735000050);
        // window_start = 1735000050 - (6 * 5) = 1735000050 - 30 = 1735000020
        assert_eq!(wp.window_start_bucket, 1735000020);
    }

    #[test]
    fn test_window_params_bucket_keys_range() {
        let config = test_config();
        let wp = WindowParams::new(&config, 1735000050);

        // Verify the bucket keys we'd generate for MGET
        // We use buckets 1..=num_buckets (previous buckets, not current)
        let bucket_ids: Vec<i64> = (1..=wp.num_buckets)
            .map(|i| wp.current_bucket - (i as i64 * wp.bucket_secs))
            .collect();

        // Should be: [1735000040, 1735000030, 1735000020, 1735000010, 1735000000, 1734999990]
        assert_eq!(
            bucket_ids,
            vec![1735000040, 1735000030, 1735000020, 1735000010, 1735000000, 1734999990]
        );

        // The oldest bucket should match window_start_bucket
        assert_eq!(*bucket_ids.last().unwrap(), wp.window_start_bucket);
    }

    #[tokio::test]
    async fn test_not_limited_when_under_threshold() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let config = test_config();

        let limiter =
            GlobalRateLimiter::new(config, client).expect("Failed to create rate limiter");

        // Should not be limited when count is under limit
        let result = limiter
            .check_rate_limit(CheckMode::Global, "test_key", 5, None)
            .await
            .expect("check_rate_limit failed");

        assert!(
            result.is_none(),
            "Should not be limited when under threshold"
        );
    }

    #[tokio::test]
    async fn test_limited_when_at_threshold() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let config = test_config(); // limit = 10

        let limiter =
            GlobalRateLimiter::new(config, client).expect("Failed to create rate limiter");

        // Pre-populate cache with count at the limit (use recent window_start_bucket)
        let recent_bucket = Utc::now().timestamp() - 30;
        limiter.cache.insert(
            "test_key".to_string(),
            CachedEntry {
                count: 10,
                window_start_bucket: recent_bucket,
            },
        );

        let result = limiter
            .check_rate_limit(CheckMode::Global, "test_key", 1, None)
            .await
            .expect("check_rate_limit failed");

        assert!(result.is_some(), "Should be limited when at/over threshold");
    }

    #[tokio::test]
    async fn test_rate_limit_response_fields() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let config = test_config(); // limit=10, window=60s, bucket=10s

        let limiter =
            GlobalRateLimiter::new(config, client).expect("Failed to create rate limiter");

        // Use recent window_start_bucket to pass staleness check
        let window_start_bucket = Utc::now().timestamp() - 30;
        limiter.cache.insert(
            "test_key".to_string(),
            CachedEntry {
                count: 15,
                window_start_bucket,
            },
        );

        let result = limiter
            .check_rate_limit(CheckMode::Global, "test_key", 1, None)
            .await
            .expect("check_rate_limit failed");

        let response = result.expect("Should be rate limited");

        assert_eq!(response.key, "test_key");
        assert_eq!(response.current_count, 15);
        assert_eq!(response.threshold, 10);
        assert_eq!(response.window_duration, Duration::from_secs(60));
        // window_start comes from cached window_start_bucket
        assert_eq!(
            response.window_start,
            DateTime::from_timestamp(window_start_bucket, 0).unwrap()
        );
        // window_end = window_start_bucket + (num_buckets * bucket_secs) = window_start_bucket + 60
        assert_eq!(
            response.window_end,
            DateTime::from_timestamp(window_start_bucket + 60, 0).unwrap()
        );
    }

    #[tokio::test]
    async fn test_cache_miss_fails_open() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let config = test_config();

        let limiter =
            GlobalRateLimiter::new(config, client).expect("Failed to create rate limiter");

        // Don't populate cache - cache miss should fail open (return Ok(None))
        let result = limiter
            .check_rate_limit(CheckMode::Global, "unknown_key", 1000, None)
            .await
            .expect("check_rate_limit failed");

        assert!(
            result.is_none(),
            "Cache miss should fail open and return None"
        );
    }

    #[tokio::test]
    async fn test_cache_hit_avoids_redis() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let config = test_config();

        let limiter = GlobalRateLimiter::new(config.clone(), client.clone())
            .expect("Failed to create rate limiter");

        // Manually populate cache
        limiter.cache.insert(
            "cached_key".to_string(),
            CachedEntry {
                count: 5,
                window_start_bucket: 0,
            },
        );

        // This should use cache and not hit Redis
        let result = limiter
            .check_rate_limit(CheckMode::Global, "cached_key", 1, None)
            .await
            .expect("check_rate_limit failed");

        assert!(
            result.is_none(),
            "Should not be limited with cached count of 5"
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

        let limiter =
            GlobalRateLimiter::new(config, client.clone()).expect("Failed to create rate limiter");

        // Manually set cache to be at limit (use recent window_start_bucket)
        let recent_bucket = Utc::now().timestamp() - 30;
        limiter.cache.insert(
            "limited_key".to_string(),
            CachedEntry {
                count: 10,
                window_start_bucket: recent_bucket,
            },
        );

        // This should be limited but still queue an update
        let result = limiter
            .check_rate_limit(CheckMode::Global, "limited_key", 1, None)
            .await
            .expect("check_rate_limit failed");

        assert!(result.is_some(), "Should be limited");

        // Give background task time to process
        tokio::time::sleep(Duration::from_millis(100)).await;

        // Verify batch_incr_by_expire_nx was called
        let calls = client.get_calls();
        let batch_calls: Vec<_> = calls
            .iter()
            .filter(|c| c.op == "batch_incr_by_expire_nx")
            .collect();
        assert!(
            !batch_calls.is_empty(),
            "Should have queued update to Redis"
        );
    }

    #[test]
    fn test_config_defaults() {
        let config = GlobalRateLimiterConfig::default();
        assert_eq!(config.global_limit, 100_000);
        assert_eq!(config.window_duration, Duration::from_secs(60));
        assert_eq!(config.bucket_interval, Duration::from_secs(10));
        assert_eq!(config.redis_key_prefix, "@posthog/globalratelimit");
        assert_eq!(config.global_cache_ttl, Duration::from_secs(300));
        assert_eq!(config.local_cache_ttl, Duration::from_secs(120));
        assert_eq!(config.local_cache_max_entries, 400_000);
        assert_eq!(config.batch_interval, Duration::from_millis(100));
        assert_eq!(config.batch_max_size, 1000);
        assert_eq!(config.channel_capacity, 10000);
        assert!(config.custom_keys.is_empty());
    }

    #[tokio::test]
    async fn test_custom_mode_unknown_key_returns_none() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let mut config = test_config();
        config.custom_keys.insert("known_key".to_string(), 5);

        let limiter =
            GlobalRateLimiter::new(config, client).expect("Failed to create rate limiter");

        // Unknown key in Custom mode should return Ok(None) immediately
        let result = limiter
            .check_rate_limit(CheckMode::Custom, "unknown_key", 100, None)
            .await
            .expect("check_rate_limit failed");

        assert!(
            result.is_none(),
            "Custom mode should return None for unknown keys"
        );
    }

    #[tokio::test]
    async fn test_custom_mode_uses_custom_limit() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let mut config = test_config();
        // Set a custom limit of 5 for this key (global limit is 10)
        config.custom_keys.insert("custom_key".to_string(), 5);

        let limiter =
            GlobalRateLimiter::new(config, client).expect("Failed to create rate limiter");

        // Manually set cache to 5 (at custom limit of 5, with recent window)
        let recent_bucket = Utc::now().timestamp() - 30;
        limiter.cache.insert(
            "custom_key".to_string(),
            CachedEntry {
                count: 5,
                window_start_bucket: recent_bucket,
            },
        );

        // count 5 >= limit 5, should be limited
        let result = limiter
            .check_rate_limit(CheckMode::Custom, "custom_key", 1, None)
            .await
            .expect("check_rate_limit failed");

        assert!(
            result.is_some(),
            "Should be limited when reaching custom limit"
        );
    }

    #[tokio::test]
    async fn test_custom_mode_under_custom_limit() {
        let client = MockRedisClient::new();
        let client = Arc::new(client);
        let mut config = test_config();
        // Set a custom limit of 10 for this key
        config.custom_keys.insert("custom_key".to_string(), 10);

        let limiter =
            GlobalRateLimiter::new(config, client).expect("Failed to create rate limiter");

        // Manually set cache to 5 (under custom limit of 10)
        limiter.cache.insert(
            "custom_key".to_string(),
            CachedEntry {
                count: 5,
                window_start_bucket: 0,
            },
        );

        // count 5 < limit 10, should not be limited
        let result = limiter
            .check_rate_limit(CheckMode::Custom, "custom_key", 1, None)
            .await
            .expect("check_rate_limit failed");

        assert!(
            result.is_none(),
            "Should not be limited when under custom limit"
        );
    }
}
