use std::collections::hash_map::DefaultHasher;
use std::collections::HashMap;
use std::hash::{Hash, Hasher};
use std::sync::Arc;
use std::time::{Duration, Instant};

use dashmap::DashSet;

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use common_redis::Client;
use moka::sync::Cache;
use tokio::sync::mpsc;
use tracing::{error, warn};

const GLOBAL_RATE_LIMITER_EVAL_COUNTER: &str = "global_rate_limiter_eval_counts_total";
const GLOBAL_RATE_LIMITER_CACHE_COUNTER: &str = "global_rate_limiter_cache_counts_total";
const GLOBAL_RATE_LIMITER_RECORDS_COUNTER: &str = "global_rate_limiter_records_total";
const GLOBAL_RATE_LIMITER_ERROR_COUNTER: &str = "global_rate_limiter_error_total";
const GLOBAL_RATE_LIMITER_PIPELINE_HISTOGRAM: &str = "global_rate_limiter_pipeline_ms";
const GLOBAL_RATE_LIMITER_TICK_HISTOGRAM: &str = "global_rate_limiter_tick_ms";
const GLOBAL_RATE_LIMITER_PIPELINE_SIZE_HISTOGRAM: &str = "global_rate_limiter_pipeline_size";
const GLOBAL_RATE_LIMITER_PENDING_SYNC_SIZE_GAUGE: &str = "global_rate_limiter_pending_sync_size";
const GLOBAL_RATE_LIMITER_SYNC_TIER_GAUGE: &str = "global_rate_limiter_sync_tier_gauge";
const GLOBAL_RATE_LIMITER_TIER_TRANSITIONS_COUNTER: &str =
    "global_rate_limiter_tier_transitions_total";
const GLOBAL_RATE_LIMITER_ESTIMATE_DRIFT_HISTOGRAM: &str = "global_rate_limiter_estimate_drift";
const GLOBAL_RATE_LIMITER_SYNC_STALENESS_HISTOGRAM: &str = "global_rate_limiter_sync_staleness_ms";

/// Pressure tiers for adaptive sync scheduling
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PressureTier {
    /// < 10% capacity: skip sync entirely
    Idle,
    /// 10-50% capacity: sync at 4x sync_interval
    Low,
    /// 50-80% capacity: sync at 1x sync_interval
    Normal,
    /// > 80% capacity: sync at sync_interval / 2
    Hot,
}

impl PressureTier {
    pub fn from_pressure(pressure: f64) -> Self {
        if pressure < 0.1 {
            Self::Idle
        } else if pressure < 0.5 {
            Self::Low
        } else if pressure < 0.8 {
            Self::Normal
        } else {
            Self::Hot
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Idle => "idle",
            Self::Low => "low",
            Self::Normal => "normal",
            Self::Hot => "hot",
        }
    }
}

/// Compute the effective sync interval for a given pressure tier
pub fn tier_sync_interval(pressure: f64, base_sync_interval: Duration) -> Option<Duration> {
    match PressureTier::from_pressure(pressure) {
        PressureTier::Idle => None, // skip sync entirely
        PressureTier::Low => Some(base_sync_interval.mul_f64(4.0)),
        PressureTier::Normal => Some(base_sync_interval),
        PressureTier::Hot => Some(base_sync_interval.div_f64(2.0)),
    }
}

/// Trait for global rate limiting
#[async_trait]
pub trait GlobalRateLimiter: Send + Sync {
    /// Check if a key is rate limited, recording the count for this request.
    ///
    /// - Consult the local cache with leaky bucket decay
    /// - Enqueue an update to the key's count for async batch submission
    /// - Push to pending_sync if sync interval exceeded
    /// - Fail open if the local cache is empty and no prior data exists
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

    /// Returns true if the key is registered in the custom_keys map
    fn is_custom_key(&self, key: &str) -> bool;

    /// Close the update channel and flush remaining update records to global cache
    fn shutdown(&mut self);
}

/// Configuration for the global rate limiter
#[derive(Clone)]
pub struct GlobalRateLimiterConfig {
    /// Maximum count allowed per window for a given key (default for keys not in custom_keys)
    pub global_threshold: u64,
    /// Sliding window size (e.g., 60 seconds) - defines the 2-epoch counter size
    pub window_interval: Duration,
    /// Max staleness before re-sync with Redis (default 15s)
    pub sync_interval: Duration,
    /// Background task cadence for pipeline reads + writes (default 1s)
    pub tick_interval: Duration,
    /// Redis key prefix (not including final separator)
    pub redis_key_prefix: String,
    /// TTL for Redis epoch keys (2 * window_interval)
    pub global_cache_ttl: Duration,
    /// How long to cache locally in the moka LRU
    pub local_cache_ttl: Duration,
    /// Evict entries not accessed within this window. Hot keys are constantly
    /// re-inserted so they never idle-expire; cold keys reclaim slots faster
    /// than waiting for the full TTL.
    pub local_cache_idle_timeout: Duration,
    /// Timeout for global cache read operations
    pub global_read_timeout: Duration,
    /// Timeout for global cache write operations
    pub global_write_timeout: Duration,
    /// Maximum entries in the local LRU cache
    pub local_cache_max_entries: u64,
    /// Capacity of the mpsc channel for async global cache updates
    pub channel_capacity: usize,
    /// Per-key custom limits. Overrides the default limit for specific *more granular* keys.
    pub custom_keys: HashMap<String, u64>,
    /// Tag value applied to all metrics emitted by this limiter instance.
    /// Allows distinguishing multiple limiter instances in the same process.
    pub metrics_scope: String,
}

impl GlobalRateLimiterConfig {
    /// Leak rate: tokens per second that drain from the bucket
    pub fn leak_rate(&self) -> f64 {
        self.global_threshold as f64 / self.window_interval.as_secs_f64()
    }

    /// Leak rate for a custom key threshold
    pub fn leak_rate_for(&self, threshold: u64) -> f64 {
        threshold as f64 / self.window_interval.as_secs_f64()
    }
}

impl Default for GlobalRateLimiterConfig {
    fn default() -> Self {
        let window_interval = Duration::from_secs(60);
        Self {
            global_threshold: 1_000_000,
            window_interval,
            sync_interval: Duration::from_secs(15),
            tick_interval: Duration::from_secs(1),
            redis_key_prefix: "@posthog/global_rate_limiter".to_string(),
            local_cache_ttl: Duration::from_secs(600),
            local_cache_idle_timeout: Duration::from_secs(300),
            global_cache_ttl: window_interval.mul_f64(2.0),
            global_read_timeout: Duration::from_millis(100),
            global_write_timeout: Duration::from_millis(100),
            local_cache_max_entries: 300_000,
            channel_capacity: 1_000_000,
            custom_keys: HashMap::new(),
            metrics_scope: "default".to_string(),
        }
    }
}

/// Internal struct for caching rate limit state with leaky bucket decay
#[derive(Clone, Debug)]
pub struct CacheEntry {
    /// Weighted count from last Redis sync (decays over time via leak_rate)
    pub estimated_count: f64,
    /// When we last read from Redis
    pub synced_at: Instant,
    /// Events counted locally since last sync
    pub local_pending: u64,
    /// effective_level / threshold at last sync, determines adaptive sync tier
    pub pressure: f64,
}

/// Compute the effective level of a cache entry with leaky bucket decay.
///
/// The estimate decays the last-known global count by the leak rate and adds
/// locally observed events. This keeps the estimate conservative (includes all
/// local events) while allowing the global contribution to drain away.
pub fn effective_level(entry: &CacheEntry, leak_rate: f64, now: Instant) -> f64 {
    let elapsed = now.duration_since(entry.synced_at).as_secs_f64();
    let drained = leak_rate * elapsed;
    (entry.estimated_count - drained).max(0.0) + entry.local_pending as f64
}

/// Compute the epoch number from a unix timestamp and window interval.
/// epoch = floor(unix_secs / window_interval_secs)
pub fn epoch_from_timestamp(timestamp: DateTime<Utc>, window_interval: Duration) -> i64 {
    let unix = timestamp.timestamp();
    let window_secs = window_interval.as_secs() as i64;
    unix / window_secs
}

/// Build the Redis key for a given entity key and epoch
pub fn epoch_key(prefix: &str, key: &str, epoch: i64) -> String {
    format!("{prefix}:{key}:{epoch}")
}

/// Build the current and previous epoch Redis keys for a given entity
pub fn epoch_keys(
    prefix: &str,
    key: &str,
    timestamp: DateTime<Utc>,
    window_interval: Duration,
) -> (String, String) {
    let epoch = epoch_from_timestamp(timestamp, window_interval);
    (
        epoch_key(prefix, key, epoch),
        epoch_key(prefix, key, epoch - 1),
    )
}

/// Compute the sliding window counter estimate from two epoch counts.
///
/// progress = fraction of the way through the current epoch (0.0..1.0)
/// estimated_count = prev_count * (1.0 - progress) + current_count
pub fn weighted_count(
    prev_count: u64,
    current_count: u64,
    timestamp: DateTime<Utc>,
    window_interval: Duration,
) -> f64 {
    let window_secs = window_interval.as_secs_f64();
    let unix = timestamp.timestamp() as f64;
    let progress = (unix % window_secs) / window_secs;
    prev_count as f64 * (1.0 - progress) + current_count as f64
}

/// Request to update a rate limit counter (queued to background task)
struct UpdateRequest {
    key: String,
    count: u64,
    timestamp: DateTime<Utc>,
}

/// Mode for rate limit checking
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CheckMode {
    /// Use the global default limit for all keys
    Global,
    /// Only check keys present in custom_keys map, using their custom limits
    Custom,
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

/// Response returned when a key is rate limited
#[derive(Debug, Clone, PartialEq)]
pub struct GlobalRateLimitResponse {
    /// The key that was rate limited
    pub key: String,
    /// Current effective level (decayed estimate + local pending)
    pub current_count: f64,
    /// The limit threshold that was exceeded
    pub threshold: u64,
    /// The sliding window interval
    pub window_interval: Duration,
    /// Sync interval (how often we re-read from Redis)
    pub sync_interval: Duration,
    /// Whether this limit was applied via a custom key override
    pub is_custom_limited: bool,
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
#[derive(Debug, Clone, PartialEq)]
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

/// A distributed rate limiter using local LRU cache with leaky bucket decay,
/// 2-epoch sliding window counters in Redis, and a unified background pipeline
/// for batched reads + writes.
#[derive(Clone)]
pub struct GlobalRateLimiterImpl {
    config: GlobalRateLimiterConfig,
    cache: Cache<String, CacheEntry>,
    update_tx: Option<mpsc::Sender<UpdateRequest>>,
    pending_sync: Arc<DashSet<String>>,
    scope: &'static str,
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

    fn is_custom_key(&self, key: &str) -> bool {
        self.config.custom_keys.contains_key(key)
    }

    fn shutdown(&mut self) {
        let _ = self.update_tx.take();
    }
}

impl GlobalRateLimiterImpl {
    /// Create a new GlobalRateLimiterImpl
    ///
    /// This spawns a background task for the unified tick loop (reads + writes).
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
            .time_to_idle(config.local_cache_idle_timeout)
            .build();

        let (update_tx, update_rx) = mpsc::channel(config.channel_capacity);
        let pending_sync = Arc::new(DashSet::new());
        let scope: &'static str = Box::leak(config.metrics_scope.clone().into_boxed_str());

        let limiter = Self {
            config: config.clone(),
            cache: cache.clone(),
            update_tx: Some(update_tx),
            pending_sync: pending_sync.clone(),
            scope,
        };

        Self::spawn_background_task(
            config,
            redis_instances,
            update_rx,
            cache,
            pending_sync,
            scope,
        );

        Ok(limiter)
    }

    /// Check if a key is rate limited and enqueue a count update.
    ///
    /// The hot path never touches Redis. Decision is based on local decay estimate.
    /// If sync is needed, the entity is pushed to pending_sync for background processing.
    async fn check_limit_internal(
        &self,
        mode: CheckMode,
        key: &str,
        count: u64,
        timestamp: Option<DateTime<Utc>>,
    ) -> EvalResult {
        let threshold = match mode {
            CheckMode::Custom => match self.config.custom_keys.get(key) {
                Some(&custom_limit) => custom_limit,
                None => return EvalResult::NotApplicable,
            },
            CheckMode::Global => self.config.global_threshold,
        };

        let leak_rate = self.config.leak_rate_for(threshold);
        let now_instant = Instant::now();

        // Enqueue write update to background task
        if count > 0 {
            let ts = timestamp.unwrap_or_else(Utc::now);
            self.enqueue_update(key, count, ts);
        }

        // Check local cache
        let (level, entry_exists) = if let Some(mut entry) = self.cache.get(key) {
            let level = effective_level(&entry, leak_rate, now_instant);

            // Record staleness for observability
            let staleness_ms = now_instant.duration_since(entry.synced_at).as_millis() as f64;
            metrics::histogram!(GLOBAL_RATE_LIMITER_SYNC_STALENESS_HISTOGRAM, "scope" => self.scope).record(staleness_ms);

            // Check if sync is needed based on pressure tier
            let current_pressure = level / threshold as f64;
            let effective_pressure = current_pressure.max(entry.pressure);
            if let Some(tier_interval) =
                tier_sync_interval(effective_pressure, self.config.sync_interval)
            {
                if now_instant.duration_since(entry.synced_at) > tier_interval {
                    self.pending_sync.insert(key.to_string());
                    metrics::counter!(GLOBAL_RATE_LIMITER_CACHE_COUNTER, "scope" => self.scope, "result" => "sync_queued")
                        .increment(1);
                } else {
                    metrics::counter!(GLOBAL_RATE_LIMITER_CACHE_COUNTER, "scope" => self.scope, "result" => "hit")
                        .increment(1);
                }
            } else {
                // Idle tier: only queue sync if local traffic has pushed us above idle threshold
                if current_pressure >= 0.1 {
                    self.pending_sync.insert(key.to_string());
                    metrics::counter!(GLOBAL_RATE_LIMITER_CACHE_COUNTER, "scope" => self.scope, "result" => "sync_queued")
                        .increment(1);
                } else {
                    metrics::counter!(GLOBAL_RATE_LIMITER_CACHE_COUNTER, "scope" => self.scope, "result" => "hit")
                        .increment(1);
                }
            }

            // Increment local_pending and recompute level with this request included
            entry.local_pending += count;
            let level = effective_level(&entry, leak_rate, now_instant);
            self.cache.insert(key.to_string(), entry);

            (level, true)
        } else {
            // Cache miss: no prior data, allow through and queue sync
            metrics::counter!(GLOBAL_RATE_LIMITER_CACHE_COUNTER, "scope" => self.scope, "result" => "miss").increment(1);

            // Insert a fresh entry so subsequent requests have local_pending tracked
            let entry = CacheEntry {
                estimated_count: 0.0,
                synced_at: now_instant,
                local_pending: count,
                pressure: 0.0,
            };
            self.cache.insert(key.to_string(), entry);
            self.pending_sync.insert(key.to_string());

            (count as f64, false)
        };

        // Determine if key is rate limited
        let is_limited = entry_exists && level >= threshold as f64;
        if is_limited {
            metrics::counter!(GLOBAL_RATE_LIMITER_EVAL_COUNTER, "scope" => self.scope, "result" => "limited").increment(1);

            EvalResult::Limited(GlobalRateLimitResponse {
                key: key.to_string(),
                current_count: level,
                threshold,
                window_interval: self.config.window_interval,
                sync_interval: self.config.sync_interval,
                is_custom_limited: mode == CheckMode::Custom,
            })
        } else {
            metrics::counter!(GLOBAL_RATE_LIMITER_EVAL_COUNTER, "scope" => self.scope, "result" => "allowed").increment(1);

            EvalResult::Allowed
        }
    }

    /// Queue an update to be batched and sent to Redis
    fn enqueue_update(&self, key: &str, count: u64, timestamp: DateTime<Utc>) {
        let update = UpdateRequest {
            key: key.to_string(),
            count,
            timestamp,
        };

        if let Some(Err(e)) = self.update_tx.as_ref().map(|tx| tx.try_send(update)) {
            metrics::counter!(
                GLOBAL_RATE_LIMITER_ERROR_COUNTER,
                "scope" => self.scope,
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

    /// Spawn the unified background tick loop that handles both reads and writes.
    ///
    /// Every tick_interval:
    /// 1. Drain pending_sync (entities needing Redis read)
    /// 2. Drain pending_writes from channel (entities with local increments)
    /// 3. Build single Redis pipeline with reads + writes
    /// 4. Execute pipeline
    /// 5. Process read responses to update cache entries
    fn spawn_background_task(
        config: GlobalRateLimiterConfig,
        redis_instances: Vec<Arc<dyn Client + Send + Sync>>,
        mut update_rx: mpsc::Receiver<UpdateRequest>,
        cache: Cache<String, CacheEntry>,
        pending_sync: Arc<DashSet<String>>,
        scope: &'static str,
    ) {
        tokio::spawn(async move {
            let mut tick = tokio::time::interval(config.tick_interval);
            // Pre-aggregate writes by (key, epoch)
            let mut write_batch: HashMap<(String, i64), u64> = HashMap::new();

            loop {
                tokio::select! {
                    result = update_rx.recv() => {
                        match result {
                            Some(req) => {
                                let epoch = epoch_from_timestamp(req.timestamp, config.window_interval);
                                *write_batch.entry((req.key, epoch)).or_insert(0) += req.count;
                            }
                            None => {
                                // Channel closed, do final flush and exit
                                if !write_batch.is_empty() {
                                    Self::tick(
                                        &config, &redis_instances, &cache,
                                        &pending_sync, &mut write_batch, scope,
                                    ).await;
                                }
                                break;
                            }
                        }
                    }
                    _ = tick.tick() => {
                        Self::tick(
                            &config, &redis_instances, &cache,
                            &pending_sync, &mut write_batch, scope,
                        ).await;
                    }
                }
            }
        });
    }

    /// Execute one tick of the background pipeline.
    ///
    /// Drains pending reads + writes, builds a single pipeline, executes it,
    /// and processes read responses to update cache entries.
    async fn tick(
        config: &GlobalRateLimiterConfig,
        redis_instances: &[Arc<dyn Client + Send + Sync>],
        cache: &Cache<String, CacheEntry>,
        pending_sync: &Arc<DashSet<String>>,
        write_batch: &mut HashMap<(String, i64), u64>,
        scope: &'static str,
    ) {
        let tick_start = Instant::now();

        // Drain pending sync set (lock-free: iterate then clear)
        let sync_keys: Vec<String> = pending_sync.iter().map(|r| r.key().clone()).collect();
        pending_sync.clear();

        // Take ownership of write batch
        let writes = std::mem::take(write_batch);

        let read_count = sync_keys.len();
        let write_count = writes.len();

        if read_count == 0 && write_count == 0 {
            return;
        }

        metrics::histogram!(GLOBAL_RATE_LIMITER_PIPELINE_SIZE_HISTOGRAM, "scope" => scope, "op" => "read")
            .record(read_count as f64);
        metrics::histogram!(GLOBAL_RATE_LIMITER_PIPELINE_SIZE_HISTOGRAM, "scope" => scope, "op" => "write")
            .record(write_count as f64);
        metrics::gauge!(GLOBAL_RATE_LIMITER_PENDING_SYNC_SIZE_GAUGE, "scope" => scope)
            .set(read_count as f64);

        // Partition work by Redis instance
        // For simplicity with single-instance (common case), skip partitioning
        if redis_instances.len() == 1 {
            Self::tick_single_instance(
                config,
                &redis_instances[0],
                0,
                cache,
                &sync_keys,
                &writes,
                scope,
            )
            .await;
        } else {
            Self::tick_multi_instance(config, redis_instances, cache, &sync_keys, &writes, scope)
                .await;
        }

        metrics::histogram!(GLOBAL_RATE_LIMITER_TICK_HISTOGRAM, "scope" => scope)
            .record(tick_start.elapsed().as_micros() as f64 / 1000.0);
    }

    /// Execute a tick against a single Redis instance (the common case).
    async fn tick_single_instance(
        config: &GlobalRateLimiterConfig,
        redis: &Arc<dyn Client + Send + Sync>,
        redis_idx: usize,
        cache: &Cache<String, CacheEntry>,
        sync_keys: &[String],
        writes: &HashMap<(String, i64), u64>,
        scope: &'static str,
    ) {
        let redis_idx_str = redis_idx.to_string();
        let now = Utc::now();
        let ttl = config.global_cache_ttl.as_secs() as usize;

        // --- WRITES ---
        if !writes.is_empty() {
            let write_items: Vec<(String, i64)> = writes
                .iter()
                .map(|((key, epoch), count)| {
                    let redis_key = epoch_key(&config.redis_key_prefix, key, *epoch);
                    (redis_key, *count as i64)
                })
                .collect();

            let write_count = write_items.len();
            let pipeline_start = Instant::now();

            match tokio::time::timeout(
                config.global_write_timeout,
                redis.batch_incr_by_expire(write_items, ttl),
            )
            .await
            {
                Ok(Ok(_)) => {
                    metrics::counter!(
                        GLOBAL_RATE_LIMITER_RECORDS_COUNTER,
                        "scope" => scope,
                        "op" => "redis_write",
                        "redis_idx" => redis_idx_str.clone(),
                    )
                    .increment(write_count as u64);
                    metrics::histogram!(
                        GLOBAL_RATE_LIMITER_PIPELINE_HISTOGRAM,
                        "scope" => scope,
                        "redis_idx" => redis_idx_str.clone(),
                    )
                    .record(pipeline_start.elapsed().as_micros() as f64 / 1000.0);
                }
                Ok(Err(e)) => {
                    metrics::counter!(
                        GLOBAL_RATE_LIMITER_ERROR_COUNTER,
                        "scope" => scope,
                        "step" => "pipeline",
                        "cause" => "redis_write",
                        "redis_idx" => redis_idx_str.clone(),
                    )
                    .increment(1);
                    warn!(error = %e, records = write_count, redis_idx = redis_idx, "Failed to write rate limit batch to Redis");
                }
                Err(_) => {
                    metrics::counter!(
                        GLOBAL_RATE_LIMITER_ERROR_COUNTER,
                        "scope" => scope,
                        "step" => "pipeline",
                        "cause" => "timeout",
                        "redis_idx" => redis_idx_str.clone(),
                    )
                    .increment(1);
                    warn!(
                        records = write_count,
                        redis_idx = redis_idx,
                        "Redis write timeout in pipeline"
                    );
                }
            }
        }

        // --- READS ---
        if !sync_keys.is_empty() {
            // Build MGET key list: for each entity, we need current + prev epoch key
            let mut mget_keys: Vec<String> = Vec::with_capacity(sync_keys.len() * 2);
            for key in sync_keys {
                let (curr, prev) =
                    epoch_keys(&config.redis_key_prefix, key, now, config.window_interval);
                mget_keys.push(curr);
                mget_keys.push(prev);
            }

            let pipeline_start = Instant::now();
            match tokio::time::timeout(config.global_read_timeout, redis.mget(mget_keys)).await {
                Ok(Ok(results)) => {
                    metrics::counter!(
                        GLOBAL_RATE_LIMITER_RECORDS_COUNTER,
                        "scope" => scope,
                        "op" => "redis_read",
                        "redis_idx" => redis_idx_str.clone(),
                    )
                    .increment(results.len() as u64);
                    metrics::histogram!(
                        GLOBAL_RATE_LIMITER_PIPELINE_HISTOGRAM,
                        "scope" => scope,
                        "redis_idx" => redis_idx_str.clone(),
                    )
                    .record(pipeline_start.elapsed().as_micros() as f64 / 1000.0);

                    Self::process_read_results(config, cache, sync_keys, &results, now, scope);
                }
                Ok(Err(e)) => {
                    metrics::counter!(
                        GLOBAL_RATE_LIMITER_ERROR_COUNTER,
                        "scope" => scope,
                        "step" => "pipeline",
                        "cause" => "redis_error",
                        "redis_idx" => redis_idx_str.clone(),
                    )
                    .increment(1);
                    warn!(keys = sync_keys.len(), redis_idx = redis_idx, error = %e, "Failed to read rate limits from Redis");
                }
                Err(_) => {
                    metrics::counter!(
                        GLOBAL_RATE_LIMITER_ERROR_COUNTER,
                        "scope" => scope,
                        "step" => "pipeline",
                        "cause" => "timeout",
                        "redis_idx" => redis_idx_str.clone(),
                    )
                    .increment(1);
                    warn!(
                        keys = sync_keys.len(),
                        redis_idx = redis_idx,
                        "Redis read timeout in pipeline"
                    );
                }
            }
        }
    }

    /// Execute a tick partitioned across multiple Redis instances.
    async fn tick_multi_instance(
        config: &GlobalRateLimiterConfig,
        redis_instances: &[Arc<dyn Client + Send + Sync>],
        cache: &Cache<String, CacheEntry>,
        sync_keys: &[String],
        writes: &HashMap<(String, i64), u64>,
        scope: &'static str,
    ) {
        // Partition reads by Redis instance
        let mut read_partitions: Vec<Vec<String>> = vec![Vec::new(); redis_instances.len()];
        for key in sync_keys {
            let (_, idx) = select_redis_client(key, redis_instances);
            read_partitions[idx].push(key.clone());
        }

        // Partition writes by Redis instance
        let mut write_partitions: Vec<HashMap<(String, i64), u64>> =
            vec![HashMap::new(); redis_instances.len()];
        for ((key, epoch), count) in writes {
            let (_, idx) = select_redis_client(key, redis_instances);
            write_partitions[idx].insert((key.clone(), *epoch), *count);
        }

        // Execute each partition in parallel
        let active_indices: Vec<usize> = (0..redis_instances.len())
            .filter(|idx| !read_partitions[*idx].is_empty() || !write_partitions[*idx].is_empty())
            .collect();

        let futures: Vec<_> = active_indices
            .into_iter()
            .map(|idx| {
                let config = config.clone();
                let redis = redis_instances[idx].clone();
                let cache = cache.clone();
                let reads = std::mem::take(&mut read_partitions[idx]);
                let writes_partition = std::mem::take(&mut write_partitions[idx]);

                async move {
                    Self::tick_single_instance(
                        &config,
                        &redis,
                        idx,
                        &cache,
                        &reads,
                        &writes_partition,
                        scope,
                    )
                    .await;
                }
            })
            .collect();

        futures::future::join_all(futures).await;
    }

    /// Process MGET results from a read pipeline, updating cache entries.
    ///
    /// Results come in pairs: [current_epoch_value, prev_epoch_value] for each entity.
    fn process_read_results(
        config: &GlobalRateLimiterConfig,
        cache: &Cache<String, CacheEntry>,
        sync_keys: &[String],
        results: &[Option<Vec<u8>>],
        now: DateTime<Utc>,
        scope: &'static str,
    ) {
        let now_instant = Instant::now();

        for (i, key) in sync_keys.iter().enumerate() {
            let base_idx = i * 2;
            if base_idx + 1 >= results.len() {
                break;
            }

            let current_count = parse_redis_count(&results[base_idx]);
            let prev_count = parse_redis_count(&results[base_idx + 1]);

            let estimated = weighted_count(prev_count, current_count, now, config.window_interval);

            let threshold = config
                .custom_keys
                .get(key)
                .copied()
                .unwrap_or(config.global_threshold);

            // Compute drift before updating (for observability)
            if let Some(old_entry) = cache.get(key) {
                let leak_rate = config.leak_rate_for(threshold);
                let local_estimate = effective_level(&old_entry, leak_rate, now_instant);
                let drift = (local_estimate - estimated).abs() / threshold as f64;
                metrics::histogram!(GLOBAL_RATE_LIMITER_ESTIMATE_DRIFT_HISTOGRAM, "scope" => scope)
                    .record(drift);
            }
            let pressure = estimated / threshold as f64;

            // Track tier transitions
            if let Some(old_entry) = cache.get(key) {
                let old_tier = PressureTier::from_pressure(old_entry.pressure);
                let new_tier = PressureTier::from_pressure(pressure);
                if old_tier != new_tier {
                    metrics::counter!(
                        GLOBAL_RATE_LIMITER_TIER_TRANSITIONS_COUNTER,
                        "scope" => scope,
                        "from" => old_tier.as_str(),
                        "to" => new_tier.as_str(),
                    )
                    .increment(1);
                }
            }

            // estimated_count from Redis already includes events this node wrote
            // across prior ticks. Reset local_pending to avoid double-counting.
            // Events arriving during the MGET window (~100ms) are lost from the
            // local estimate but will be written to Redis on the next tick.
            cache.insert(
                key.clone(),
                CacheEntry {
                    estimated_count: estimated,
                    synced_at: now_instant,
                    local_pending: 0,
                    pressure,
                },
            );
        }

        // Update tier gauge counts
        let mut tier_counts = [0u64; 4];
        for (_, entry) in cache.iter() {
            let tier = PressureTier::from_pressure(entry.pressure);
            match tier {
                PressureTier::Idle => tier_counts[0] += 1,
                PressureTier::Low => tier_counts[1] += 1,
                PressureTier::Normal => tier_counts[2] += 1,
                PressureTier::Hot => tier_counts[3] += 1,
            }
        }
        metrics::gauge!(GLOBAL_RATE_LIMITER_SYNC_TIER_GAUGE, "scope" => scope, "tier" => "idle")
            .set(tier_counts[0] as f64);
        metrics::gauge!(GLOBAL_RATE_LIMITER_SYNC_TIER_GAUGE, "scope" => scope, "tier" => "low")
            .set(tier_counts[1] as f64);
        metrics::gauge!(GLOBAL_RATE_LIMITER_SYNC_TIER_GAUGE, "scope" => scope, "tier" => "normal")
            .set(tier_counts[2] as f64);
        metrics::gauge!(GLOBAL_RATE_LIMITER_SYNC_TIER_GAUGE, "scope" => scope, "tier" => "hot")
            .set(tier_counts[3] as f64);
    }
}

/// Parse a Redis byte response into a u64 count, defaulting to 0
fn parse_redis_count(value: &Option<Vec<u8>>) -> u64 {
    value
        .as_ref()
        .and_then(|bytes| std::str::from_utf8(bytes).ok())
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::MockRedisClient;

    fn test_config() -> GlobalRateLimiterConfig {
        GlobalRateLimiterConfig {
            global_threshold: 10,
            window_interval: Duration::from_secs(60),
            sync_interval: Duration::from_secs(15),
            tick_interval: Duration::from_millis(50),
            redis_key_prefix: "test:".to_string(),
            global_cache_ttl: Duration::from_secs(120),
            local_cache_ttl: Duration::from_secs(1),
            local_cache_idle_timeout: Duration::from_millis(500),
            local_cache_max_entries: 100,
            channel_capacity: 100,
            custom_keys: HashMap::new(),
            global_read_timeout: Duration::from_millis(5),
            global_write_timeout: Duration::from_millis(10),
            metrics_scope: "test".to_string(),
        }
    }

    // --- Epoch calculation tests (parameterized) ---

    #[test]
    fn test_epoch_from_timestamp() {
        let cases = vec![
            // (unix_secs, window_secs, expected_epoch)
            (60, 60, 1),                // exact boundary
            (90, 60, 1),                // mid-epoch
            (119, 60, 1),               // end of epoch
            (120, 60, 2),               // next epoch
            (0, 60, 0),                 // zero
            (1735000080, 60, 28916668), // large timestamp
            (30, 30, 1),                // different window
        ];

        for (unix, window_secs, expected) in cases {
            let ts = DateTime::from_timestamp(unix, 0).unwrap();
            let window = Duration::from_secs(window_secs);
            assert_eq!(
                epoch_from_timestamp(ts, window),
                expected,
                "epoch_from_timestamp({unix}, {window_secs}s) should be {expected}"
            );
        }
    }

    #[test]
    fn test_epoch_key_format() {
        assert_eq!(epoch_key("prefix", "mykey", 42), "prefix:mykey:42");
    }

    #[test]
    fn test_epoch_keys_returns_current_and_prev() {
        let ts = DateTime::from_timestamp(120, 0).unwrap(); // epoch 2 with 60s window
        let (curr, prev) = epoch_keys("p", "k", ts, Duration::from_secs(60));
        assert_eq!(curr, "p:k:2");
        assert_eq!(prev, "p:k:1");
    }

    // --- Weighted count estimation tests (parameterized) ---

    #[test]
    fn test_weighted_count_estimation() {
        let cases = vec![
            // (prev, current, unix_secs, window_secs, expected_approx)
            (100, 0, 60, 60, 100.0),   // progress=0.0: full prev weight
            (100, 0, 90, 60, 50.0),    // progress=0.5: half prev weight
            (100, 50, 90, 60, 100.0),  // progress=0.5: 50 + 50
            (0, 100, 90, 60, 100.0),   // prev=0, all current
            (0, 0, 90, 60, 0.0),       // both zero
            (100, 100, 60, 60, 200.0), // progress=0.0: full prev + current
        ];

        for (prev, current, unix, window_secs, expected) in cases {
            let ts = DateTime::from_timestamp(unix, 0).unwrap();
            let window = Duration::from_secs(window_secs);
            let result = weighted_count(prev, current, ts, window);
            assert!(
                (result - expected).abs() < 0.01,
                "weighted_count({prev}, {current}, t={unix}, w={window_secs}) = {result}, expected {expected}"
            );
        }
    }

    // --- Leaky bucket decay tests (parameterized) ---

    #[test]
    fn test_effective_level_decay() {
        let base = Instant::now();
        let cases = vec![
            // (estimated_count, elapsed_secs, local_pending, leak_rate, expected)
            (100.0, 0.0, 0, 10.0, 100.0),  // no elapsed: full count
            (100.0, 10.0, 0, 10.0, 0.0),   // full drain
            (100.0, 5.0, 0, 10.0, 50.0),   // partial drain
            (100.0, 0.0, 50, 10.0, 150.0), // local_pending adds
            (100.0, 5.0, 30, 10.0, 80.0),  // drain + pending: (100-50)+30
            (10.0, 20.0, 0, 10.0, 0.0),    // over-drain floors at 0
            (10.0, 20.0, 5, 10.0, 5.0),    // over-drain + pending
        ];

        for (est, elapsed, pending, rate, expected) in cases {
            let entry = CacheEntry {
                estimated_count: est,
                synced_at: base,
                local_pending: pending,
                pressure: 0.0,
            };
            let now = base + Duration::from_secs_f64(elapsed);
            let result = effective_level(&entry, rate, now);
            assert!(
                (result - expected).abs() < 0.01,
                "effective_level(est={est}, elapsed={elapsed}s, pending={pending}, rate={rate}) = {result}, expected {expected}"
            );
        }
    }

    // --- Pressure tier tests (parameterized) ---

    #[test]
    fn test_pressure_tier_from_pressure() {
        let cases = vec![
            (0.0, PressureTier::Idle),
            (0.05, PressureTier::Idle),
            (0.09, PressureTier::Idle),
            (0.1, PressureTier::Low),
            (0.25, PressureTier::Low),
            (0.49, PressureTier::Low),
            (0.5, PressureTier::Normal),
            (0.75, PressureTier::Normal),
            (0.79, PressureTier::Normal),
            (0.8, PressureTier::Hot),
            (0.95, PressureTier::Hot),
            (1.0, PressureTier::Hot),
            (1.5, PressureTier::Hot),
        ];

        for (pressure, expected) in cases {
            assert_eq!(
                PressureTier::from_pressure(pressure),
                expected,
                "PressureTier::from_pressure({pressure}) should be {expected:?}"
            );
        }
    }

    #[test]
    fn test_tier_sync_interval() {
        let base = Duration::from_secs(15);
        let cases = vec![
            // (pressure, expected_multiplier_of_base)
            (0.05, None),                             // Idle: skip
            (0.25, Some(Duration::from_secs(60))),    // Low: 4x
            (0.65, Some(Duration::from_secs(15))),    // Normal: 1x
            (0.9, Some(Duration::from_millis(7500))), // Hot: 0.5x
        ];

        for (pressure, expected) in cases {
            let result = tier_sync_interval(pressure, base);
            assert_eq!(
                result, expected,
                "tier_sync_interval({pressure}, 15s) should be {expected:?}, got {result:?}"
            );
        }
    }

    // --- Config tests ---

    #[test]
    fn test_config_defaults() {
        let config = GlobalRateLimiterConfig::default();
        assert_eq!(config.global_threshold, 1_000_000);
        assert_eq!(config.window_interval, Duration::from_secs(60));
        assert_eq!(config.sync_interval, Duration::from_secs(15));
        assert_eq!(config.tick_interval, Duration::from_secs(1));
        assert_eq!(config.redis_key_prefix, "@posthog/global_rate_limiter");
        assert_eq!(config.global_cache_ttl, Duration::from_secs(120));
        assert_eq!(config.local_cache_ttl, Duration::from_secs(600));
        assert_eq!(config.local_cache_idle_timeout, Duration::from_secs(300));
        assert_eq!(config.global_read_timeout, Duration::from_millis(100));
        assert_eq!(config.global_write_timeout, Duration::from_millis(100));
        assert_eq!(config.local_cache_max_entries, 300_000);
        assert_eq!(config.channel_capacity, 1_000_000);
        assert!(config.custom_keys.is_empty());
        assert_eq!(config.metrics_scope, "default");
    }

    #[test]
    fn test_leak_rate() {
        let config = test_config(); // threshold=10, window=60s
        assert!((config.leak_rate() - 10.0 / 60.0).abs() < 0.0001);
        assert!((config.leak_rate_for(100) - 100.0 / 60.0).abs() < 0.0001);
    }

    // --- Limiter behavior tests ---

    #[tokio::test]
    async fn test_not_limited_when_under_threshold() {
        let client = Arc::new(MockRedisClient::new());
        let config = test_config();
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        limiter.cache.insert(
            "test_key".to_string(),
            CacheEntry {
                estimated_count: 5.0,
                synced_at: Instant::now(),
                local_pending: 0,
                pressure: 0.5,
            },
        );

        let result = limiter.check_limit("test_key", 1, None).await;
        assert!(
            matches!(result, EvalResult::Allowed),
            "Should return Allowed when under threshold, got {result:?}"
        );
    }

    #[tokio::test]
    async fn test_limited_when_at_threshold() {
        let client = Arc::new(MockRedisClient::new());
        let config = test_config(); // threshold = 10
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        limiter.cache.insert(
            "test_key".to_string(),
            CacheEntry {
                estimated_count: 10.0,
                synced_at: Instant::now(),
                local_pending: 0,
                pressure: 1.0,
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
        let client = Arc::new(MockRedisClient::new());
        let config = test_config();
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        limiter.cache.insert(
            "test_key".to_string(),
            CacheEntry {
                estimated_count: 15.0,
                synced_at: Instant::now(),
                local_pending: 0,
                pressure: 1.5,
            },
        );

        let result = limiter.check_limit("test_key", 1, None).await;
        let response = match result {
            EvalResult::Limited(r) => r,
            other => panic!("Expected Limited, got {other:?}"),
        };

        assert_eq!(response.key, "test_key");
        assert!(response.current_count >= 15.0);
        assert_eq!(response.threshold, 10);
        assert_eq!(response.window_interval, Duration::from_secs(60));
        assert_eq!(response.sync_interval, Duration::from_secs(15));
        assert!(!response.is_custom_limited);
    }

    #[tokio::test]
    async fn test_cache_miss_returns_allowed() {
        let client = Arc::new(MockRedisClient::new());
        let config = test_config();
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        // No cache entry: first request should be allowed and entity queued for sync
        let result = limiter.check_limit("unknown_key", 1, None).await;
        assert!(
            matches!(result, EvalResult::Allowed),
            "Cache miss should return Allowed, got {result:?}"
        );

        // Verify entity was queued for sync
        assert!(
            limiter.pending_sync.contains("unknown_key"),
            "Should have queued entity for sync"
        );
    }

    #[tokio::test]
    async fn test_cache_hit_no_redis_calls() {
        let client = Arc::new(MockRedisClient::new());
        let config = test_config();
        let limiter = GlobalRateLimiterImpl::new(config.clone(), vec![client.clone()]).unwrap();

        // Fresh cache entry (synced_at = now, well within sync_interval)
        limiter.cache.insert(
            "cached_key".to_string(),
            CacheEntry {
                estimated_count: 5.0,
                synced_at: Instant::now(),
                local_pending: 0,
                pressure: 0.5,
            },
        );

        let result = limiter.check_limit("cached_key", 1, None).await;
        assert!(
            matches!(result, EvalResult::Allowed),
            "Should return Allowed with cached count of 5, got {result:?}"
        );

        // No mget calls should have been made (decision was local)
        let calls = client.get_calls();
        let mget_calls: Vec<_> = calls.iter().filter(|c| c.op == "mget").collect();
        assert!(
            mget_calls.is_empty(),
            "Should not have called mget when cache hit"
        );
    }

    #[tokio::test]
    async fn test_local_pending_incremented_on_check() {
        let client = Arc::new(MockRedisClient::new());
        let config = test_config();
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        limiter.cache.insert(
            "key_a".to_string(),
            CacheEntry {
                estimated_count: 1.0,
                synced_at: Instant::now(),
                local_pending: 0,
                pressure: 0.1,
            },
        );

        let _ = limiter.check_limit("key_a", 5, None).await;

        let entry = limiter.cache.get("key_a").unwrap();
        assert_eq!(
            entry.local_pending, 5,
            "local_pending should be incremented by count"
        );
    }

    #[tokio::test]
    async fn test_update_queued_even_when_limited() {
        let client = Arc::new(MockRedisClient::new());
        let config = test_config();
        let limiter = GlobalRateLimiterImpl::new(config, vec![client.clone()]).unwrap();

        limiter.cache.insert(
            "limited_key".to_string(),
            CacheEntry {
                estimated_count: 10.0,
                synced_at: Instant::now(),
                local_pending: 0,
                pressure: 1.0,
            },
        );

        let result = limiter.check_limit("limited_key", 1, None).await;
        assert!(
            matches!(result, EvalResult::Limited(_)),
            "Should be Limited, got {result:?}"
        );

        // Give background task time to process the tick
        tokio::time::sleep(Duration::from_millis(100)).await;

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

    // --- Custom key tests ---

    #[tokio::test]
    async fn test_custom_mode_unknown_key_returns_not_applicable() {
        let client = Arc::new(MockRedisClient::new());
        let mut config = test_config();
        config.custom_keys.insert("known_key".to_string(), 5);
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        let result = limiter.check_custom_limit("unknown_key", 100, None).await;
        assert!(
            matches!(result, EvalResult::NotApplicable),
            "Custom mode should return NotApplicable for unknown keys, got {result:?}"
        );
    }

    #[tokio::test]
    async fn test_custom_mode_uses_custom_limit() {
        let client = Arc::new(MockRedisClient::new());
        let mut config = test_config();
        config.custom_keys.insert("custom_key".to_string(), 5);
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        limiter.cache.insert(
            "custom_key".to_string(),
            CacheEntry {
                estimated_count: 5.0,
                synced_at: Instant::now(),
                local_pending: 0,
                pressure: 1.0,
            },
        );

        let result = limiter.check_custom_limit("custom_key", 1, None).await;
        let response = match result {
            EvalResult::Limited(r) => r,
            other => panic!("Should be Limited when reaching custom limit, got {other:?}"),
        };
        assert!(response.is_custom_limited);
    }

    #[tokio::test]
    async fn test_custom_mode_under_custom_limit() {
        let client = Arc::new(MockRedisClient::new());
        let mut config = test_config();
        config.custom_keys.insert("custom_key".to_string(), 10);
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        limiter.cache.insert(
            "custom_key".to_string(),
            CacheEntry {
                estimated_count: 5.0,
                synced_at: Instant::now(),
                local_pending: 0,
                pressure: 0.5,
            },
        );

        let result = limiter.check_custom_limit("custom_key", 1, None).await;
        assert!(
            matches!(result, EvalResult::Allowed),
            "Should return Allowed when under custom limit, got {result:?}"
        );
    }

    #[tokio::test]
    async fn test_is_custom_key() {
        let client = Arc::new(MockRedisClient::new()) as Arc<dyn Client + Send + Sync>;
        let mut config = test_config();
        config.custom_keys.insert("registered".to_string(), 42);
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        assert!(limiter.is_custom_key("registered"));
        assert!(!limiter.is_custom_key("unknown"));
        assert!(!limiter.is_custom_key(""));
    }

    #[tokio::test]
    async fn test_is_custom_key_empty_map() {
        let client = Arc::new(MockRedisClient::new()) as Arc<dyn Client + Send + Sync>;
        let config = test_config();
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        assert!(!limiter.is_custom_key("anything"));
    }

    #[tokio::test]
    async fn test_custom_key_behavior() {
        let client = Arc::new(MockRedisClient::new());
        let mut config = test_config();
        config.custom_keys.insert("custom_a".to_string(), 5);
        config.custom_keys.insert("custom_b".to_string(), 10);
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        limiter.cache.insert(
            "custom_a".to_string(),
            CacheEntry {
                estimated_count: 10.0,
                synced_at: Instant::now(),
                local_pending: 0,
                pressure: 2.0,
            },
        );

        let result = limiter.check_custom_limit("custom_a", 1, None).await;
        assert!(
            matches!(result, EvalResult::Limited(_)),
            "custom_a should be Limited, got {result:?}"
        );

        let result = limiter.check_custom_limit("unknown_key", 1, None).await;
        assert!(
            matches!(result, EvalResult::NotApplicable),
            "unknown_key should return NotApplicable, got {result:?}"
        );

        let result = limiter.check_custom_limit("", 1, None).await;
        assert!(
            matches!(result, EvalResult::NotApplicable),
            "empty key should return NotApplicable, got {result:?}"
        );
    }

    // --- Sync scheduling tests ---

    #[tokio::test]
    async fn test_sync_queued_when_interval_exceeded() {
        let client = Arc::new(MockRedisClient::new());
        let config = test_config();
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        // Entry synced long ago: should trigger sync
        limiter.cache.insert(
            "stale_key".to_string(),
            CacheEntry {
                estimated_count: 5.0,
                synced_at: Instant::now() - Duration::from_secs(60),
                local_pending: 0,
                pressure: 0.5,
            },
        );

        let _ = limiter.check_limit("stale_key", 1, None).await;
        assert!(
            limiter.pending_sync.contains("stale_key"),
            "Should have queued stale entity for sync"
        );
    }

    #[tokio::test]
    async fn test_sync_not_queued_when_fresh() {
        let client = Arc::new(MockRedisClient::new());
        let config = test_config();
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        // Freshly synced, normal pressure
        limiter.cache.insert(
            "fresh_key".to_string(),
            CacheEntry {
                estimated_count: 5.0,
                synced_at: Instant::now(),
                local_pending: 0,
                pressure: 0.5,
            },
        );

        let _ = limiter.check_limit("fresh_key", 1, None).await;
        assert!(
            !limiter.pending_sync.contains("fresh_key"),
            "Should NOT have queued fresh entity for sync"
        );
    }

    #[tokio::test]
    async fn test_sync_dedup() {
        let client = Arc::new(MockRedisClient::new());
        let config = test_config();
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        // Stale entry: will trigger sync
        limiter.cache.insert(
            "dedup_key".to_string(),
            CacheEntry {
                estimated_count: 5.0,
                synced_at: Instant::now() - Duration::from_secs(60),
                local_pending: 0,
                pressure: 0.5,
            },
        );

        // Call twice, should only appear once in pending_sync
        let _ = limiter.check_limit("dedup_key", 1, None).await;
        let _ = limiter.check_limit("dedup_key", 1, None).await;

        let count = limiter
            .pending_sync
            .iter()
            .filter(|r| r.key() == "dedup_key")
            .count();
        assert_eq!(count, 1, "pending_sync should deduplicate entries");
    }

    // --- Redis client selection tests ---

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
        for i in 0..100 {
            let key = format!("key_{i}");
            let (_, idx) = select_redis_client(&key, &clients);
            indices.insert(idx);
        }

        assert!(
            indices.len() > 1,
            "Multiple keys should distribute across instances"
        );
    }

    // --- Process read results tests ---

    #[test]
    fn test_process_read_results_updates_cache() {
        let config = test_config();
        let cache = Cache::builder()
            .max_capacity(100)
            .time_to_live(Duration::from_secs(60))
            .time_to_idle(Duration::from_secs(30))
            .build();

        // Seed cache with an old entry
        cache.insert(
            "entity_a".to_string(),
            CacheEntry {
                estimated_count: 0.0,
                synced_at: Instant::now() - Duration::from_secs(30),
                local_pending: 3,
                pressure: 0.0,
            },
        );

        let sync_keys = vec!["entity_a".to_string()];
        // Results: current_epoch=7, prev_epoch=3
        let results: Vec<Option<Vec<u8>>> = vec![Some(b"7".to_vec()), Some(b"3".to_vec())];

        let now = DateTime::from_timestamp(90, 0).unwrap(); // progress = 0.5 in 60s window
        GlobalRateLimiterImpl::process_read_results(
            &config, &cache, &sync_keys, &results, now, "test",
        );

        let entry = cache.get("entity_a").unwrap();
        // weighted = 3 * 0.5 + 7 = 8.5
        assert!(
            (entry.estimated_count - 8.5).abs() < 0.01,
            "estimated_count should be ~8.5, got {}",
            entry.estimated_count
        );
        // pressure = 8.5 / 10 = 0.85
        assert!(
            (entry.pressure - 0.85).abs() < 0.01,
            "pressure should be ~0.85, got {}",
            entry.pressure
        );
        // local_pending reset to 0 on sync (avoids double-counting)
        assert_eq!(entry.local_pending, 0);
    }

    #[test]
    fn test_process_read_results_custom_key_pressure() {
        let mut config = test_config();
        config.custom_keys.insert("custom_entity".to_string(), 100);
        let cache = Cache::builder()
            .max_capacity(100)
            .time_to_live(Duration::from_secs(60))
            .time_to_idle(Duration::from_secs(30))
            .build();

        cache.insert(
            "custom_entity".to_string(),
            CacheEntry {
                estimated_count: 0.0,
                synced_at: Instant::now() - Duration::from_secs(30),
                local_pending: 3,
                pressure: 0.0,
            },
        );

        let sync_keys = vec!["custom_entity".to_string()];
        let results: Vec<Option<Vec<u8>>> = vec![Some(b"7".to_vec()), Some(b"3".to_vec())];
        let now = DateTime::from_timestamp(90, 0).unwrap();
        GlobalRateLimiterImpl::process_read_results(
            &config, &cache, &sync_keys, &results, now, "test",
        );

        let entry = cache.get("custom_entity").unwrap();
        assert!(
            (entry.estimated_count - 8.5).abs() < 0.01,
            "estimated_count should be ~8.5, got {}",
            entry.estimated_count
        );
        // pressure = 8.5 / 100 (custom threshold) = 0.085
        assert!(
            (entry.pressure - 0.085).abs() < 0.01,
            "pressure should be ~0.085 for custom threshold 100, got {}",
            entry.pressure
        );
        assert_eq!(entry.local_pending, 0);
    }

    #[test]
    fn test_process_read_results_zeroes_local_pending() {
        let config = test_config();
        let now = DateTime::from_timestamp(90, 0).unwrap();

        for prior_pending in [0u64, 1, 5, 100, 10_000] {
            let cache = Cache::builder()
                .max_capacity(100)
                .time_to_live(Duration::from_secs(60))
                .time_to_idle(Duration::from_secs(30))
                .build();

            cache.insert(
                "key".to_string(),
                CacheEntry {
                    estimated_count: 0.0,
                    synced_at: Instant::now() - Duration::from_secs(30),
                    local_pending: prior_pending,
                    pressure: 0.0,
                },
            );

            let sync_keys = vec!["key".to_string()];
            let results: Vec<Option<Vec<u8>>> = vec![Some(b"5".to_vec()), Some(b"2".to_vec())];
            GlobalRateLimiterImpl::process_read_results(
                &config, &cache, &sync_keys, &results, now, "test",
            );

            let entry = cache.get("key").unwrap();
            assert_eq!(
                entry.local_pending, 0,
                "local_pending should be 0 after sync regardless of prior value ({prior_pending})"
            );
        }
    }

    #[test]
    fn test_parse_redis_count() {
        assert_eq!(parse_redis_count(&Some(b"42".to_vec())), 42);
        assert_eq!(parse_redis_count(&Some(b"0".to_vec())), 0);
        assert_eq!(parse_redis_count(&None), 0);
        assert_eq!(parse_redis_count(&Some(b"not_a_number".to_vec())), 0);
        assert_eq!(parse_redis_count(&Some(vec![])), 0);
    }
}
