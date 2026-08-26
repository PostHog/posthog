use std::collections::hash_map::DefaultHasher;
use std::collections::HashMap;
use std::hash::{Hash, Hasher};
use std::sync::Arc;
use std::time::{Duration, Instant};

use arc_swap::ArcSwap;
use dashmap::DashSet;

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use common_redis::Client;
use moka::sync::Cache;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

use crate::custom_key_source::CustomKeyThresholdSource;

/// Resolver for custom-key thresholds. Given a lookup key and a snapshot of the
/// current custom-key map, returns the threshold to apply (or `None` if the key
/// is not subject to a custom limit).
///
/// The default resolver (when `custom_key_resolver` is `None`) is an exact map
/// lookup. Callers can inject a closure to implement richer policies (e.g. a
/// hierarchical `token:distinct_id` -> `token` fallback) without leaking their
/// key structure into this crate. The closure receives the authoritative map by
/// reference so it always resolves against the latest swapped-in thresholds.
pub type CustomKeyResolver = Arc<dyn Fn(&str, &HashMap<String, u64>) -> Option<u64> + Send + Sync>;

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
const GLOBAL_RATE_LIMITER_CACHE_SIZE_GAUGE: &str = "global_rate_limiter_cache_size";
const GLOBAL_RATE_LIMITER_EVICTION_COUNTER: &str = "global_rate_limiter_eviction_total";
/// Keys still queued for sync after a tick took its bounded slice.
const GLOBAL_RATE_LIMITER_SYNC_DEFERRED_GAUGE: &str = "global_rate_limiter_sync_deferred_size";
/// (key, epoch) write entries still batched after a tick took its bounded slice.
const GLOBAL_RATE_LIMITER_WRITE_DEFERRED_GAUGE: &str = "global_rate_limiter_write_deferred_size";
/// Syncs not queued because the key's level is below `min_sync_floor`.
const GLOBAL_RATE_LIMITER_SYNC_SKIPPED_COUNTER: &str = "global_rate_limiter_sync_skipped_total";
/// Redis commands issued per tick, after chunking.
const GLOBAL_RATE_LIMITER_COMMANDS_HISTOGRAM: &str = "global_rate_limiter_commands_per_tick";
/// Number of custom-key thresholds applied at the last successful refresh.
const CUSTOM_THRESHOLDS_LOADED_GAUGE: &str = "global_rate_limiter_custom_thresholds_loaded";
/// Unix timestamp of the last successful custom-key threshold refresh.
const CUSTOM_THRESHOLDS_LAST_REFRESH_GAUGE: &str =
    "global_rate_limiter_custom_thresholds_last_refresh_timestamp";

/// Full-cache scan cadence (ticks) for the per-tier distribution gauges. The
/// distribution moves slowly and prod metrics dedup to 60s, so a periodic scan
/// keeps these gauges fresh enough without scanning the cache every tick.
const TIER_SCAN_INTERVAL_TICKS: u64 = 30;
/// Tier label order, indexed by `PressureTier::index()`.
const TIER_LABELS: [&str; 4] = ["idle", "low", "normal", "hot"];

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

    /// Index into the per-tier scan tally array (see `TIER_LABELS`).
    pub fn index(&self) -> usize {
        match self {
            Self::Idle => 0,
            Self::Low => 1,
            Self::Normal => 2,
            Self::Hot => 3,
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
    /// Minimum effective level before a key is worth a Redis round trip.
    ///
    /// A key far below its threshold cannot be limited no matter what the other
    /// nodes report, so syncing it buys nothing and costs two Redis keys per
    /// tick. With an unbounded key space (e.g. keyed on distinct_id) the
    /// one-shot keys dominate, so this floor is what keeps the pipeline sized to
    /// the keys that can actually be enforced rather than to total traffic.
    ///
    /// The level is per-node, so the ceiling on a safe value is
    /// `global_threshold / node_count` -- above that, a key sitting exactly at
    /// the threshold but spread evenly across the fleet would never sync and so
    /// could never be limited. Keep well under that: the saving is dominated by
    /// the single-event keys, so a small floor captures nearly all of it.
    ///
    /// Set to 0 to sync every key, restoring the pre-floor behavior.
    pub min_sync_floor: u64,
    /// Maximum keys drained from `pending_sync` per tick. The remainder stays
    /// queued for the next tick, so a backlog degrades into staleness instead of
    /// a tick loop that overruns its own interval.
    pub max_sync_keys_per_tick: usize,
    /// Maximum Redis keys per individual command. Reads cost two keys per entity
    /// (current + previous epoch), so an entity chunk is half this. Bounds how
    /// long any single command can take, which is what the per-command timeout
    /// is actually budgeting for.
    pub max_keys_per_command: usize,
    /// How many chunked commands may be in flight at once against one instance.
    /// Trades tick wall-clock against instantaneous Redis load.
    pub max_concurrent_commands: usize,
    /// Maximum distinct (key, epoch) entries held in the deferred write batch.
    /// Merges into existing entries are always accepted (they add no memory);
    /// at the cap, updates for new keys are dropped and counted. Without this,
    /// unique-key inflow faster than the per-tick drain grows the batch without
    /// bound -- the update channel's capacity does not help, because the
    /// receiver moves entries into this map as fast as they arrive.
    pub max_write_batch_entries: usize,
    /// Maximum keys held in the pending-sync set. At the cap, new sync
    /// requests are dropped and counted; the key's next request re-queues it
    /// once the backlog drains. Mirrors `max_write_batch_entries`: without a
    /// cap, keys clearing the sync floor faster than the per-tick drain grow
    /// the set without bound.
    pub max_pending_sync_entries: usize,
    /// Per-key custom limits. Overrides the default limit for specific *more granular* keys.
    ///
    /// Wrapped in `Arc<ArcSwap<_>>` so the map can be atomically replaced at
    /// runtime (by the refresh task via `custom_keys.store(...)`) without locking
    /// hot-path readers. Every clone of the config shares the same underlying
    /// `ArcSwap`, so a swap through any clone (e.g. the copy held by the
    /// background task) is visible everywhere.
    pub custom_keys: Arc<ArcSwap<HashMap<String, u64>>>,
    /// Optional policy for resolving a lookup key to a custom threshold. When
    /// `None`, resolution is an exact lookup in `custom_keys`. When set, the
    /// closure is consulted with the key and a snapshot of the current map.
    pub custom_key_resolver: Option<CustomKeyResolver>,
    /// Optional source of dynamically-refreshed custom-key thresholds. When set,
    /// `GlobalRateLimiterImpl::new` spawns a background task that fetches the map
    /// every `custom_key_refresh_interval` and atomically swaps it into
    /// `custom_keys`. When `None`, `custom_keys` is static (e.g. seeded once from
    /// config) and no refresh task runs.
    pub custom_key_source: Option<Arc<dyn CustomKeyThresholdSource>>,
    /// Cadence for the custom-key refresh task. Ignored when `custom_key_source`
    /// is `None`.
    pub custom_key_refresh_interval: Duration,
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

    /// Resolve a lookup key to its custom threshold, if any.
    ///
    /// Snapshots the current custom-key map once (lock-free) and applies the
    /// configured resolver, falling back to an exact lookup when no resolver is
    /// injected. Returns `None` when the key is not subject to a custom limit.
    pub fn resolve_custom(&self, key: &str) -> Option<u64> {
        let guard = self.custom_keys.load();
        let map: &HashMap<String, u64> = &guard;
        match &self.custom_key_resolver {
            Some(resolver) => resolver(key, map),
            None => map.get(key).copied(),
        }
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
            global_read_timeout: Duration::from_millis(250),
            global_write_timeout: Duration::from_millis(250),
            local_cache_max_entries: 300_000,
            channel_capacity: 1_000_000,
            min_sync_floor: 10,
            max_sync_keys_per_tick: 20_000,
            max_keys_per_command: 2_000,
            max_concurrent_commands: 4,
            max_write_batch_entries: 200_000,
            max_pending_sync_entries: 200_000,
            custom_keys: Arc::new(ArcSwap::from_pointee(HashMap::new())),
            custom_key_resolver: None,
            custom_key_source: None,
            custom_key_refresh_interval: Duration::from_secs(60),
            metrics_scope: "default".to_string(),
        }
    }
}

/// Internal struct for caching rate limit state with leaky bucket decay
#[derive(Clone, Debug)]
pub struct CacheEntry {
    /// Weighted count from last Redis sync (decays over time via leak_rate)
    pub estimated_count: f64,
    /// When we last read from Redis. `None` until the first read lands, which
    /// keeps "created just now" distinct from "synced just now". They decide
    /// opposite things: a never-synced entry is due for a sync as soon as it
    /// clears the floor, where a freshly synced one must wait out its tier.
    pub synced_at: Option<Instant>,
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
    // Never synced, so `estimated_count` is still 0 and there is nothing to
    // decay. The level is whatever this node has counted on its own.
    let Some(synced_at) = entry.synced_at else {
        return entry.local_pending as f64;
    };
    let elapsed = now.duration_since(synced_at).as_secs_f64();
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
    /// Drop-to-stop signal for the custom-key refresh task (mirrors `update_tx`).
    /// `None` when no `custom_key_source` was configured.
    custom_key_refresh_stop: Option<mpsc::Sender<()>>,
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
        self.config.resolve_custom(key).is_some()
    }

    fn shutdown(&mut self) {
        let _ = self.update_tx.take();
        // Dropping the sender closes the refresh task's stop channel.
        let _ = self.custom_key_refresh_stop.take();
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

        let scope: &'static str = Box::leak(config.metrics_scope.clone().into_boxed_str());

        // An idle timeout shorter than the window would expire entries inside the
        // very window they are accumulating counts for, silently under-enforcing.
        // Clamp rather than error: this is deploy-time config, and taking capture
        // down over a tuning value is worse than running with a corrected one.
        let mut config = config;
        if config.local_cache_idle_timeout < config.window_interval {
            warn!(
                scope,
                idle_timeout = ?config.local_cache_idle_timeout,
                window_interval = ?config.window_interval,
                "local_cache_idle_timeout below window_interval would drop counts \
                 inside the enforcement window; clamping to window_interval"
            );
            config.local_cache_idle_timeout = config.window_interval;
        }
        // Same hazard for the hard TTL: an entry evicted mid-window discards the
        // counts it was accumulating, and the next request follows the always-
        // allowed miss path.
        if config.local_cache_ttl < config.window_interval {
            warn!(
                scope,
                ttl = ?config.local_cache_ttl,
                window_interval = ?config.window_interval,
                "local_cache_ttl below window_interval would drop counts inside \
                 the enforcement window; clamping to window_interval"
            );
            config.local_cache_ttl = config.window_interval;
        }
        // Reads consult the current and the previous epoch, so the previous
        // epoch's Redis key is still needed for a full window after its last
        // write. A TTL below 2 x window_interval expires that key while it is
        // still being read, and `weighted_count` then takes `prev_count` as 0.
        // That understates the fleet estimate for the rest of the window and
        // under-enforces. `global_cache_ttl` has a default derived from the
        // default window, so any caller that changes the window without
        // changing the TTL lands here.
        let min_global_cache_ttl = config.window_interval * 2;
        if config.global_cache_ttl < min_global_cache_ttl {
            warn!(
                scope,
                global_cache_ttl = ?config.global_cache_ttl,
                window_interval = ?config.window_interval,
                "global_cache_ttl below 2x window_interval expires the previous \
                 epoch key while reads still need it; clamping to 2x window_interval"
            );
            config.global_cache_ttl = min_global_cache_ttl;
        }
        let config = config;

        let cache = Cache::builder()
            .max_capacity(config.local_cache_max_entries)
            .time_to_live(config.local_cache_ttl)
            .time_to_idle(config.local_cache_idle_timeout)
            .eviction_listener(move |_key, _entry: CacheEntry, cause| {
                // MUST stay panic-free: moka permanently disables a listener that
                // panics. Replaced is an in-place update, not a removal.
                if cause != moka::notification::RemovalCause::Replaced {
                    metrics::counter!(
                        GLOBAL_RATE_LIMITER_EVICTION_COUNTER,
                        "scope" => scope,
                        "cause" => removal_cause_str(cause),
                    )
                    .increment(1);
                }
            })
            .build();

        let (update_tx, update_rx) = mpsc::channel(config.channel_capacity);
        let pending_sync = Arc::new(DashSet::new());

        // Spawn the custom-key refresh task when a source is configured. The
        // source owns its own reconnect; we only hold a drop-to-stop signal,
        // mirroring how `update_tx` closes the tick loop on shutdown.
        let custom_key_refresh_stop = config.custom_key_source.clone().map(|source| {
            let (stop_tx, stop_rx) = mpsc::channel::<()>(1);
            Self::spawn_custom_key_refresh_task(
                config.clone(),
                source,
                config.custom_key_refresh_interval,
                stop_rx,
                scope,
            );
            stop_tx
        });

        let limiter = Self {
            config: config.clone(),
            cache: cache.clone(),
            update_tx: Some(update_tx),
            pending_sync: pending_sync.clone(),
            scope,
            custom_key_refresh_stop,
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
            CheckMode::Custom => match self.config.resolve_custom(key) {
                Some(custom_limit) => custom_limit,
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

            // Record staleness for observability. A never-synced entry has no
            // staleness to report; it is covered by the sync decision below.
            if let Some(synced_at) = entry.synced_at {
                let staleness_ms = now_instant.duration_since(synced_at).as_millis() as f64;
                metrics::histogram!(GLOBAL_RATE_LIMITER_SYNC_STALENESS_HISTOGRAM, "scope" => self.scope).record(staleness_ms);
            }

            // Sync decision. The absolute floor is checked first: a key this far
            // under its threshold cannot be limited whatever the other nodes
            // report, so the round trip buys nothing and the key space is large
            // enough that those round trips are the dominant cost. Above the
            // floor the pressure tier sets the cadence, and a key that clears the
            // floor while still idle-tier syncs on the Low cadence rather than
            // never -- otherwise a key that is hot across the fleet but cold on
            // any single node would never be discovered.
            if self.sync_floor_blocks(level, threshold) {
                metrics::counter!(GLOBAL_RATE_LIMITER_CACHE_COUNTER, "scope" => self.scope, "result" => "hit")
                    .increment(1);
            } else {
                let effective_pressure = (level / threshold as f64).max(entry.pressure);
                let tier_interval =
                    tier_sync_interval(effective_pressure, self.config.sync_interval)
                        .unwrap_or_else(|| self.config.sync_interval.mul_f64(4.0));

                // A never-synced entry is due immediately. Its level is local
                // only, so the fleet count behind it is unknown, and waiting a
                // tier interval to find out delays every verdict on the key by
                // that long. Keys below the floor never reach this branch, so
                // this does not sync the long tail of one-off keys.
                let due = match entry.synced_at {
                    None => true,
                    Some(synced_at) => now_instant.duration_since(synced_at) > tier_interval,
                };
                if due {
                    self.queue_sync(key);
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
                synced_at: None,
                local_pending: count,
                pressure: 0.0,
            };
            self.cache.insert(key.to_string(), entry);
            if !self.sync_floor_blocks(count as f64, threshold) {
                self.queue_sync(key);
            }

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

    /// True when `level` sits below the sync floor for this key's threshold,
    /// meaning a Redis round trip cannot change any enforcement decision.
    /// Records the skip so the saving is visible next to `cache_counts_total`.
    ///
    /// The configured floor is capped at 1% of the key's own threshold. The
    /// floor is a per-node level, so a fleet of N nodes can hide at most
    /// N * floor events from Redis; the cap keeps that bypass under N% of the
    /// threshold regardless of configuration. Without it, a custom threshold
    /// far below the global one (the exact keys overrides exist to clamp) could
    /// sit entirely below a floor tuned for the global threshold and never
    /// sync, making the override unenforceable.
    ///
    /// A configured floor of 0 disables the check entirely.
    fn sync_floor_blocks(&self, level: f64, threshold: u64) -> bool {
        if self.config.min_sync_floor == 0 {
            return false;
        }
        let effective_floor = self.config.min_sync_floor.min((threshold / 100).max(1));
        if level >= effective_floor as f64 {
            return false;
        }
        metrics::counter!(
            GLOBAL_RATE_LIMITER_SYNC_SKIPPED_COUNTER,
            "scope" => self.scope,
            "reason" => "below_floor",
        )
        .increment(1);
        true
    }

    /// Queue a key for background Redis sync, bounded by
    /// `max_pending_sync_entries`. A dropped request fails open for one round:
    /// the key's next request re-queues it once the backlog drains, and its
    /// counts keep flowing to Redis regardless -- only the read is delayed.
    fn queue_sync(&self, key: &str) {
        if self.pending_sync.len() >= self.config.max_pending_sync_entries
            && !self.pending_sync.contains(key)
        {
            metrics::counter!(
                GLOBAL_RATE_LIMITER_ERROR_COUNTER,
                "scope" => self.scope,
                "step" => "queue_sync",
                "cause" => "pending_sync_full",
            )
            .increment(1);
            return;
        }
        self.pending_sync.insert(key.to_string());
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

    /// Spawn the background task that periodically refreshes custom-key thresholds.
    ///
    /// `tokio::time::interval` fires immediately, so the first fetch happens
    /// without delay. The task exits when `stop_rx` closes (all senders dropped
    /// via `shutdown`, or when the limiter is dropped).
    fn spawn_custom_key_refresh_task(
        config: GlobalRateLimiterConfig,
        source: Arc<dyn CustomKeyThresholdSource>,
        refresh_interval: Duration,
        mut stop_rx: mpsc::Receiver<()>,
        scope: &'static str,
    ) {
        tokio::spawn(async move {
            // `tokio::time::interval` panics on a zero period. A misconfigured
            // interval must not kill this (detached) task and silently freeze
            // dynamic refreshes, so clamp to a 1s floor and warn instead.
            let period = refresh_interval.max(Duration::from_secs(1));
            if period != refresh_interval {
                warn!(
                    scope,
                    ?refresh_interval,
                    "Custom-key refresh interval below 1s floor; clamping to 1s"
                );
            }
            let mut tick = tokio::time::interval(period);
            loop {
                tokio::select! {
                    _ = stop_rx.recv() => {
                        info!(scope, "Custom-key threshold refresh task shutting down");
                        break;
                    }
                    _ = tick.tick() => {
                        Self::refresh_custom_keys_once(&config, source.as_ref(), scope).await;
                    }
                }
            }
        });
    }

    /// Fetch custom-key thresholds once and atomically swap them into the config.
    ///
    /// Only an explicit Redis blob is authoritative: `Ok(Some)` replaces the map
    /// (an empty blob — `{}` — is the deliberate clear signal). An absent key
    /// (`Ok(None)`) is ambiguous — fresh rollout before the writer runs, an
    /// eviction, or an accidental delete — so it is treated as fail-static, the
    /// same as `Err`: the current map is kept rather than silently wiping the
    /// (fail-open) hot overrides. The source handles its own reconnect, so the
    /// next tick retries.
    async fn refresh_custom_keys_once(
        config: &GlobalRateLimiterConfig,
        source: &dyn CustomKeyThresholdSource,
        scope: &'static str,
    ) {
        match source.fetch().await {
            Ok(Some(map)) => {
                let count = map.len();
                config.custom_keys.store(Arc::new(map));
                metrics::gauge!(CUSTOM_THRESHOLDS_LOADED_GAUGE, "scope" => scope).set(count as f64);
                metrics::gauge!(CUSTOM_THRESHOLDS_LAST_REFRESH_GAUGE, "scope" => scope)
                    .set(Utc::now().timestamp() as f64);
            }
            Ok(None) => {
                // Absent key: keep the current map (fail-static). A deliberate
                // clear arrives as an explicit empty blob via the `Ok(Some)` arm;
                // the `not_found` counter is already emitted by the source's
                // fetch(), so we neither touch the map nor stomp the gauges here.
            }
            Err(e) => {
                error!(
                    scope,
                    error = %e,
                    "Failed to refresh custom-key thresholds, keeping current values"
                );
            }
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
            let mut tick_n: u64 = 0;

            loop {
                tokio::select! {
                    result = update_rx.recv() => {
                        match result {
                            Some(req) => {
                                let epoch = epoch_from_timestamp(req.timestamp, config.window_interval);
                                Self::absorb_update(
                                    &mut write_batch,
                                    req.key,
                                    epoch,
                                    req.count,
                                    config.max_write_batch_entries,
                                    scope,
                                );
                            }
                            None => {
                                // Channel closed, do final flush and exit
                                if !write_batch.is_empty() {
                                    Self::tick(
                                        &config, &redis_instances, &cache,
                                        &pending_sync, &mut write_batch, scope, tick_n,
                                    ).await;
                                }
                                break;
                            }
                        }
                    }
                    _ = tick.tick() => {
                        tick_n = tick_n.wrapping_add(1);
                        Self::tick(
                            &config, &redis_instances, &cache,
                            &pending_sync, &mut write_batch, scope, tick_n,
                        ).await;
                    }
                }
            }
        });
    }

    /// Merge one update into the deferred write batch, enforcing the entry cap.
    ///
    /// Merges never grow the map, so they are always accepted; only a brand-new
    /// (key, epoch) entry can be refused. A refused update undercounts the
    /// global tally for that key -- under-enforcement, consistent with every
    /// other overload path here failing open -- and is counted so the loss is
    /// visible. No log line: at the inflow rates that reach the cap, per-drop
    /// logging would itself be a problem.
    fn absorb_update(
        write_batch: &mut HashMap<(String, i64), u64>,
        key: String,
        epoch: i64,
        count: u64,
        max_entries: usize,
        scope: &'static str,
    ) {
        let at_cap = write_batch.len() >= max_entries;
        match write_batch.entry((key, epoch)) {
            std::collections::hash_map::Entry::Occupied(mut entry) => {
                *entry.get_mut() += count;
            }
            std::collections::hash_map::Entry::Vacant(slot) => {
                if at_cap {
                    metrics::counter!(
                        GLOBAL_RATE_LIMITER_ERROR_COUNTER,
                        "scope" => scope,
                        "step" => "enqueue_update",
                        "cause" => "write_batch_full",
                    )
                    .increment(1);
                } else {
                    slot.insert(count);
                }
            }
        }
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
        tick_n: u64,
    ) {
        let tick_start = Instant::now();

        // Cache-size gauge every tick (O(1)); per-tier distribution via a
        // throttled full scan (slow-moving, see TIER_SCAN_INTERVAL_TICKS).
        Self::emit_cache_gauges(cache, scope, tick_n);

        // Take a bounded slice of the pending set rather than all of it. The
        // remainder stays queued, so a backlog surfaces as sync staleness instead
        // of a tick that overruns its own interval and starves every other key.
        // `collect` drops the iterator before the removals, which keeps us off
        // dashmap's held-shard-lock path.
        let sync_keys: Vec<String> = pending_sync
            .iter()
            .take(config.max_sync_keys_per_tick)
            .map(|r| r.key().clone())
            .collect();
        for key in &sync_keys {
            pending_sync.remove(key);
        }
        metrics::gauge!(GLOBAL_RATE_LIMITER_SYNC_DEFERRED_GAUGE, "scope" => scope)
            .set(pending_sync.len() as f64);

        // Deferred entries whose epoch has aged out of the readable window can
        // no longer affect any decision: reads consult only the current and
        // previous epochs. Purge them instead of spending write commands (and
        // deferral slots) on counts nothing will ever read.
        let min_live_epoch = epoch_from_timestamp(Utc::now(), config.window_interval) - 1;
        let before_purge = write_batch.len();
        write_batch.retain(|(_, epoch), _| *epoch >= min_live_epoch);
        let purged = before_purge - write_batch.len();
        if purged > 0 {
            metrics::counter!(
                GLOBAL_RATE_LIMITER_ERROR_COUNTER,
                "scope" => scope,
                "step" => "pipeline",
                "cause" => "stale_epoch_purged",
            )
            .increment(purged as u64);
        }

        // Bound the write drain the same way. The deferred remainder stays in
        // `write_batch`, where new arrivals merge into it by (key, epoch), so no
        // count is lost -- it lands in the same epoch key up to a few ticks late.
        // Without the bound, a high-cardinality burst produces a write batch
        // whose waves consume the whole tick before reads run.
        let writes: HashMap<(String, i64), u64> =
            if write_batch.len() <= config.max_sync_keys_per_tick {
                std::mem::take(write_batch)
            } else {
                let drain_keys: Vec<(String, i64)> = write_batch
                    .keys()
                    .take(config.max_sync_keys_per_tick)
                    .cloned()
                    .collect();
                drain_keys
                    .into_iter()
                    .filter_map(|k| write_batch.remove_entry(&k))
                    .collect()
            };
        metrics::gauge!(GLOBAL_RATE_LIMITER_WRITE_DEFERRED_GAUGE, "scope" => scope)
            .set(write_batch.len() as f64);

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
    #[allow(clippy::too_many_arguments)]
    async fn tick_single_instance(
        config: &GlobalRateLimiterConfig,
        redis: &Arc<dyn Client + Send + Sync>,
        redis_idx: usize,
        cache: &Cache<String, CacheEntry>,
        sync_keys: &[String],
        writes: &HashMap<(String, i64), u64>,
        scope: &'static str,
    ) {
        let redis_idx_str: Arc<str> = Arc::from(redis_idx.to_string().as_str());
        let now = Utc::now();
        let ttl = config.global_cache_ttl.as_secs() as usize;

        // Writes first, then reads. A read result zeroes each synced key's
        // `local_pending`, so the read must already include this tick's write
        // batch -- reads-first would discard up to a tick of a key's counts
        // until its next sync. Writes-first is safe to wait on now that the
        // write batch is bounded and chunked: the read delay is capped at a few
        // command timeouts, where the old unbounded batch could consume whole
        // ticks. Counts deferred past the write cap are still cleared by the
        // read before they land; that loss is bounded by the cap and fails
        // open, like every other overload path here.
        let writes_issued =
            Self::run_writes(config, redis, &redis_idx_str, writes, ttl, scope).await;
        let reads_issued =
            Self::run_reads(config, redis, &redis_idx_str, cache, sync_keys, now, scope).await;

        metrics::histogram!(GLOBAL_RATE_LIMITER_COMMANDS_HISTOGRAM, "scope" => scope, "op" => "write")
            .record(writes_issued as f64);
        metrics::histogram!(GLOBAL_RATE_LIMITER_COMMANDS_HISTOGRAM, "scope" => scope, "op" => "read")
            .record(reads_issued as f64);
    }

    /// Issue the write half of a tick as size-bounded, concurrently-executed
    /// commands. Returns how many commands were issued.
    ///
    /// One oversized command is the failure mode this exists to prevent: the
    /// per-command timeout can only be a meaningful budget if the command's size
    /// is bounded, otherwise a growing key space silently converts a working
    /// timeout into a guaranteed one.
    async fn run_writes(
        config: &GlobalRateLimiterConfig,
        redis: &Arc<dyn Client + Send + Sync>,
        redis_idx_str: &Arc<str>,
        writes: &HashMap<(String, i64), u64>,
        ttl: usize,
        scope: &'static str,
    ) -> usize {
        if writes.is_empty() {
            return 0;
        }

        let write_items: Vec<(String, i64)> = writes
            .iter()
            .map(|((key, epoch), count)| {
                let redis_key = epoch_key(&config.redis_key_prefix, key, *epoch);
                (redis_key, *count as i64)
            })
            .collect();

        let chunks: Vec<Vec<(String, i64)>> = write_items
            .chunks(config.max_keys_per_command.max(1))
            .map(|chunk| chunk.to_vec())
            .collect();
        let issued = chunks.len();

        // Waves of `max_concurrent_commands` rather than a `buffer_unordered`
        // stream: the stream combinator forces a higher-ranked `Send` bound the
        // spawned tick task cannot satisfy, and this keeps the same bound on
        // in-flight commands.
        for wave in chunks.chunks(config.max_concurrent_commands.max(1)) {
            let futures = wave.iter().map(|chunk| {
                let redis_idx_str = redis_idx_str.clone();
                async move {
                    let chunk_len = chunk.len();
                    let started = Instant::now();
                    match tokio::time::timeout(
                        config.global_write_timeout,
                        redis.batch_incr_by_expire(chunk.clone(), ttl),
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
                            .increment(chunk_len as u64);
                            metrics::histogram!(
                                GLOBAL_RATE_LIMITER_PIPELINE_HISTOGRAM,
                                "scope" => scope,
                                "redis_idx" => redis_idx_str.clone(),
                            )
                            .record(started.elapsed().as_micros() as f64 / 1000.0);
                        }
                        Ok(Err(e)) => {
                            Self::record_pipeline_error(scope, &redis_idx_str, "redis_write");
                            warn!(error = %e, records = chunk_len, "Failed to write rate limit batch to Redis");
                            // A dead MultiplexedConnection never recovers on its
                            // own; ask the client to rebuild. Timeouts are
                            // transient and never route here.
                            if e.is_unrecoverable_error() {
                                redis.heal().await;
                            }
                        }
                        Err(_) => {
                            Self::record_pipeline_error(scope, &redis_idx_str, "write_timeout");
                            warn!(records = chunk_len, "Redis write timeout in pipeline");
                        }
                    }
                }
            });
            futures::future::join_all(futures).await;
        }

        issued
    }

    /// Issue the read half of a tick as size-bounded, concurrently-executed
    /// commands, applying each chunk's results as it lands. Returns how many
    /// commands were issued.
    #[allow(clippy::too_many_arguments)]
    async fn run_reads(
        config: &GlobalRateLimiterConfig,
        redis: &Arc<dyn Client + Send + Sync>,
        redis_idx_str: &Arc<str>,
        cache: &Cache<String, CacheEntry>,
        sync_keys: &[String],
        now: DateTime<Utc>,
        scope: &'static str,
    ) -> usize {
        if sync_keys.is_empty() {
            return 0;
        }

        // Each entity costs two Redis keys (current + previous epoch), so the
        // entity chunk is half the per-command key budget.
        let entities_per_chunk = (config.max_keys_per_command / 2).max(1);
        let chunks: Vec<&[String]> = sync_keys.chunks(entities_per_chunk).collect();
        let issued = chunks.len();

        // See `run_writes` for why this is waves of `join_all` rather than a
        // `buffer_unordered` stream.
        for wave in chunks.chunks(config.max_concurrent_commands.max(1)) {
            let futures = wave.iter().map(|chunk| {
                let redis_idx_str = redis_idx_str.clone();
                async move {
                    let mut mget_keys: Vec<String> = Vec::with_capacity(chunk.len() * 2);
                    for key in chunk.iter() {
                        let (curr, prev) =
                            epoch_keys(&config.redis_key_prefix, key, now, config.window_interval);
                        mget_keys.push(curr);
                        mget_keys.push(prev);
                    }

                    let started = Instant::now();
                    match tokio::time::timeout(config.global_read_timeout, redis.mget(mget_keys))
                        .await
                    {
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
                            .record(started.elapsed().as_micros() as f64 / 1000.0);

                            Self::process_read_results(config, cache, chunk, &results, now, scope);
                        }
                        Ok(Err(e)) => {
                            Self::record_pipeline_error(scope, &redis_idx_str, "redis_error");
                            warn!(keys = chunk.len(), error = %e, "Failed to read rate limits from Redis");
                            if e.is_unrecoverable_error() {
                                redis.heal().await;
                            }
                        }
                        Err(_) => {
                            Self::record_pipeline_error(scope, &redis_idx_str, "read_timeout");
                            warn!(keys = chunk.len(), "Redis read timeout in pipeline");
                        }
                    }
                }
            });
            futures::future::join_all(futures).await;
        }

        issued
    }

    /// Record a pipeline-step failure. `cause` distinguishes read from write so
    /// a saturating side is identifiable from the metric alone.
    fn record_pipeline_error(scope: &'static str, redis_idx_str: &Arc<str>, cause: &'static str) {
        metrics::counter!(
            GLOBAL_RATE_LIMITER_ERROR_COUNTER,
            "scope" => scope,
            "step" => "pipeline",
            "cause" => cause,
            "redis_idx" => redis_idx_str.clone(),
        )
        .increment(1);
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
                .resolve_custom(key)
                .unwrap_or(config.global_threshold);

            let pressure = estimated / threshold as f64;
            let new_tier = PressureTier::from_pressure(pressure);

            // Single lookup: emit estimate drift + tier transition for the prior entry.
            if let Some(old_entry) = cache.get(key) {
                let leak_rate = config.leak_rate_for(threshold);
                let local_estimate = effective_level(&old_entry, leak_rate, now_instant);
                let drift = (local_estimate - estimated).abs() / threshold as f64;
                metrics::histogram!(GLOBAL_RATE_LIMITER_ESTIMATE_DRIFT_HISTOGRAM, "scope" => scope)
                    .record(drift);

                let old_tier = PressureTier::from_pressure(old_entry.pressure);
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
                    synced_at: Some(now_instant),
                    local_pending: 0,
                    pressure,
                },
            );
        }
    }

    /// Emit cache observability gauges from the background task (off the hot path).
    ///
    /// `cache_size` is cheap (`entry_count`) so it emits every tick. The per-tier
    /// distribution needs a full `cache.iter()` scan, so it runs only every
    /// `TIER_SCAN_INTERVAL_TICKS`: the distribution moves slowly and prod metrics
    /// dedup to 60s, so scanning every tick would be wasted work under load.
    fn emit_cache_gauges(cache: &Cache<String, CacheEntry>, scope: &'static str, tick_n: u64) {
        metrics::gauge!(GLOBAL_RATE_LIMITER_CACHE_SIZE_GAUGE, "scope" => scope)
            .set(cache.entry_count() as f64);

        if tick_n.is_multiple_of(TIER_SCAN_INTERVAL_TICKS) {
            let tier_counts = Self::scan_tier_counts(cache);
            for i in 0..4 {
                metrics::gauge!(GLOBAL_RATE_LIMITER_SYNC_TIER_GAUGE, "scope" => scope, "tier" => TIER_LABELS[i])
                    .set(tier_counts[i] as f64);
            }
        }
    }

    /// Full O(n) scan tallying live entries per pressure tier (indexed by
    /// `PressureTier::index()`). Off the hot path; see `TIER_SCAN_INTERVAL_TICKS`.
    fn scan_tier_counts(cache: &Cache<String, CacheEntry>) -> [u64; 4] {
        let mut tier_counts = [0u64; 4];
        for (_, entry) in cache.iter() {
            tier_counts[PressureTier::from_pressure(entry.pressure).index()] += 1;
        }
        tier_counts
    }
}

/// Map a Moka removal cause to a stable metric label (Replaced is filtered out
/// before this is called).
fn removal_cause_str(cause: moka::notification::RemovalCause) -> &'static str {
    use moka::notification::RemovalCause;
    match cause {
        RemovalCause::Expired => "expired",
        RemovalCause::Explicit => "explicit",
        RemovalCause::Size => "size",
        RemovalCause::Replaced => "replaced",
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
    use crate::custom_key_source::testing::MockCustomKeyThresholdSource;
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
            custom_keys: Arc::new(ArcSwap::from_pointee(HashMap::new())),
            custom_key_resolver: None,
            custom_key_source: None,
            custom_key_refresh_interval: Duration::from_secs(60),
            global_read_timeout: Duration::from_millis(5),
            global_write_timeout: Duration::from_millis(10),
            metrics_scope: "test".to_string(),
            // Tests drive a threshold of 10, so a production-sized floor would
            // suppress every sync. 0 keeps the pre-floor behavior; the floor's
            // own behavior is covered by the dedicated tests below.
            min_sync_floor: 0,
            max_sync_keys_per_tick: 20_000,
            max_keys_per_command: 2_000,
            max_concurrent_commands: 4,
            max_write_batch_entries: 200_000,
            max_pending_sync_entries: 200_000,
        }
    }

    /// Seed a config's custom-key map (whole-map swap), mirroring how the
    /// dynamic refresh path replaces thresholds at runtime.
    fn set_custom_keys(config: &GlobalRateLimiterConfig, pairs: &[(&str, u64)]) {
        let map: HashMap<String, u64> = pairs.iter().map(|(k, v)| (k.to_string(), *v)).collect();
        config.custom_keys.store(Arc::new(map));
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
            // (estimated_count, elapsed_secs, local_pending, leak_rate, synced, expected)
            (100.0, 0.0, 0, 10.0, true, 100.0), // no elapsed: full count
            (100.0, 10.0, 0, 10.0, true, 0.0),  // full drain
            (100.0, 5.0, 0, 10.0, true, 50.0),  // partial drain
            (100.0, 0.0, 50, 10.0, true, 150.0), // local_pending adds
            (100.0, 5.0, 30, 10.0, true, 80.0), // drain + pending: (100-50)+30
            (10.0, 20.0, 0, 10.0, true, 0.0),   // over-drain floors at 0
            (10.0, 20.0, 5, 10.0, true, 5.0),   // over-drain + pending
            // Never synced: no fleet estimate exists yet, so nothing decays and
            // the level is the local count alone, whatever the other fields say.
            (100.0, 10.0, 7, 10.0, false, 7.0),
            (0.0, 0.0, 0, 10.0, false, 0.0),
        ];

        for (est, elapsed, pending, rate, synced, expected) in cases {
            let entry = CacheEntry {
                estimated_count: est,
                synced_at: synced.then_some(base),
                local_pending: pending,
                pressure: 0.0,
            };
            let now = base + Duration::from_secs_f64(elapsed);
            let result = effective_level(&entry, rate, now);
            assert!(
                (result - expected).abs() < 0.01,
                "effective_level(est={est}, elapsed={elapsed}s, pending={pending}, rate={rate}, synced={synced}) = {result}, expected {expected}"
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
        assert_eq!(config.global_read_timeout, Duration::from_millis(250));
        assert_eq!(config.global_write_timeout, Duration::from_millis(250));
        assert_eq!(config.local_cache_max_entries, 300_000);
        assert_eq!(config.channel_capacity, 1_000_000);
        assert_eq!(config.min_sync_floor, 10);
        assert_eq!(config.max_sync_keys_per_tick, 20_000);
        assert_eq!(config.max_keys_per_command, 2_000);
        assert_eq!(config.max_concurrent_commands, 4);
        assert_eq!(config.max_write_batch_entries, 200_000);
        assert_eq!(config.max_pending_sync_entries, 200_000);
        assert!(config.custom_keys.load().is_empty());
        assert!(config.custom_key_resolver.is_none());
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
                synced_at: Some(Instant::now()),
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
                synced_at: Some(Instant::now()),
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
                synced_at: Some(Instant::now()),
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
                synced_at: Some(Instant::now()),
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
                synced_at: Some(Instant::now()),
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
                synced_at: Some(Instant::now()),
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
        let config = test_config();
        set_custom_keys(&config, &[("known_key", 5)]);
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
        let config = test_config();
        set_custom_keys(&config, &[("custom_key", 5)]);
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        limiter.cache.insert(
            "custom_key".to_string(),
            CacheEntry {
                estimated_count: 5.0,
                synced_at: Some(Instant::now()),
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
        let config = test_config();
        set_custom_keys(&config, &[("custom_key", 10)]);
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        limiter.cache.insert(
            "custom_key".to_string(),
            CacheEntry {
                estimated_count: 5.0,
                synced_at: Some(Instant::now()),
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
        let config = test_config();
        set_custom_keys(&config, &[("registered", 42)]);
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
        let config = test_config();
        set_custom_keys(&config, &[("custom_a", 5), ("custom_b", 10)]);
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        limiter.cache.insert(
            "custom_a".to_string(),
            CacheEntry {
                estimated_count: 10.0,
                synced_at: Some(Instant::now()),
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
                synced_at: Some(Instant::now() - Duration::from_secs(60)),
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
                synced_at: Some(Instant::now()),
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

    /// `test_config` with the sync floor set and the background drain parked, so
    /// `pending_sync` assertions observe only what `check_limit` queued.
    fn config_with_floor(floor: u64) -> GlobalRateLimiterConfig {
        GlobalRateLimiterConfig {
            min_sync_floor: floor,
            tick_interval: Duration::from_secs(3600),
            ..test_config()
        }
    }

    #[tokio::test]
    async fn test_min_sync_floor_gates_cold_miss_sync() {
        // (floor, count, expect_queued)
        let cases = vec![
            (0, 1, true),  // floor disabled: every miss syncs (pre-floor behavior)
            (5, 1, false), // below floor: no round trip for a key that cannot be limited
            (5, 5, true),  // exactly at the floor
            (5, 9, true),  // above the floor
        ];

        for (floor, count, expect_queued) in cases {
            let client = Arc::new(MockRedisClient::new());
            // Threshold large enough (floor * 100 or more) that the 1% cap does
            // not reduce the configured floor; the cap has its own test below.
            let config = GlobalRateLimiterConfig {
                global_threshold: 1000,
                ..config_with_floor(floor)
            };
            let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();
            let key = format!("cold_{floor}_{count}");

            limiter.check_limit(&key, count, None).await;

            assert_eq!(
                limiter.pending_sync.contains(&key),
                expect_queued,
                "floor={floor} count={count} should queue sync = {expect_queued}"
            );
        }
    }

    #[tokio::test]
    async fn test_sync_due_immediately_only_when_never_synced() {
        // (label, synced_at, expect_queued)
        let cases = vec![
            ("never synced", None, true),
            ("synced just now", Some(Instant::now()), false),
        ];

        for (label, synced_at, expect_queued) in cases {
            let client = Arc::new(MockRedisClient::new());
            let config = GlobalRateLimiterConfig {
                // 1% of the threshold is 10, so the configured floor of 5 applies.
                global_threshold: 1000,
                min_sync_floor: 5,
                // Park the background drain so pending_sync shows only what
                // check_limit queued.
                tick_interval: Duration::from_secs(3600),
                ..test_config()
            };
            let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

            // local_pending is above the floor, so the sync decision comes down
            // to synced_at alone. Pressure stays Idle, whose tier interval is
            // 4 x sync_interval = 60s, far longer than this test takes.
            limiter.cache.insert(
                "above_floor".to_string(),
                CacheEntry {
                    estimated_count: 0.0,
                    synced_at,
                    local_pending: 11,
                    pressure: 0.0,
                },
            );

            let _ = limiter.check_limit("above_floor", 1, None).await;

            assert_eq!(
                limiter.pending_sync.contains("above_floor"),
                expect_queued,
                "an entry {label} and above the floor should queue a sync={expect_queued} -- \
                 a never-synced entry has no fleet count behind it, so making it wait out a \
                 tier interval hides the key from the limiter for that long"
            );
        }
    }

    #[tokio::test]
    async fn test_idle_timeout_clamped_up_to_window_interval() {
        // (idle_timeout_secs, expected_secs)
        let cases = vec![
            (10, 60),   // below the 60s window: clamped up
            (59, 60),   // just below: clamped up
            (60, 60),   // exactly at the window: untouched
            (300, 300), // above: untouched
        ];

        for (idle_secs, expected_secs) in cases {
            let client = Arc::new(MockRedisClient::new());
            let config = GlobalRateLimiterConfig {
                local_cache_idle_timeout: Duration::from_secs(idle_secs),
                ..test_config()
            };
            let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

            assert_eq!(
                limiter.config.local_cache_idle_timeout,
                Duration::from_secs(expected_secs),
                "idle_timeout={idle_secs}s against a 60s window should resolve to {expected_secs}s -- \
                 an idle timeout inside the window expires entries mid-window and silently under-enforces"
            );
        }
    }

    #[tokio::test]
    async fn test_global_cache_ttl_clamped_up_to_two_windows() {
        // (configured_ttl_secs, expected_secs) against test_config()'s 60s window
        let cases = vec![
            (30, 120),  // below one window
            (60, 120),  // one window: still expires the previous epoch early
            (119, 120), // just below the bound
            (120, 120), // exactly at the bound: untouched
            (600, 600), // above: untouched
        ];

        for (ttl_secs, expected_secs) in cases {
            let client = Arc::new(MockRedisClient::new());
            let config = GlobalRateLimiterConfig {
                global_cache_ttl: Duration::from_secs(ttl_secs),
                ..test_config()
            };
            let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

            assert_eq!(
                limiter.config.global_cache_ttl,
                Duration::from_secs(expected_secs),
                "global_cache_ttl={ttl_secs}s against a 60s window should resolve to {expected_secs}s -- \
                 a TTL under 2x the window expires the previous epoch key while reads still \
                 need it, so weighted_count takes prev_count as 0 and under-enforces"
            );
        }
    }

    #[tokio::test]
    async fn test_sync_floor_capped_at_one_percent_of_threshold() {
        // (configured_floor, threshold, count, expect_queued)
        let cases = vec![
            // Custom-style low threshold: cap = max(1, 100/100) = 1, so any
            // counted event syncs. A floor tuned for the global threshold must
            // not make a low custom override unenforceable.
            (10, 100, 1, true),
            // Threshold 500: cap = 5. The configured 10 is reduced to 5.
            (10, 500, 4, false),
            (10, 500, 5, true),
            // Large threshold: cap = 150 leaves the configured 10 in charge.
            (10, 15_000, 9, false),
            (10, 15_000, 10, true),
        ];

        for (floor, threshold, count, expect_queued) in cases {
            let client = Arc::new(MockRedisClient::new());
            let config = GlobalRateLimiterConfig {
                global_threshold: threshold,
                ..config_with_floor(floor)
            };
            let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();
            let key = format!("cap_{floor}_{threshold}_{count}");

            limiter.check_limit(&key, count, None).await;

            assert_eq!(
                limiter.pending_sync.contains(&key),
                expect_queued,
                "floor={floor} threshold={threshold} count={count} should queue sync = {expect_queued}"
            );
        }
    }

    #[tokio::test]
    async fn test_ttl_clamped_up_to_window_interval() {
        let client = Arc::new(MockRedisClient::new());
        let config = GlobalRateLimiterConfig {
            local_cache_ttl: Duration::from_secs(1),
            ..test_config() // 60s window
        };
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        assert_eq!(
            limiter.config.local_cache_ttl,
            Duration::from_secs(60),
            "a TTL below the window evicts entries mid-window; the next request \
             takes the always-allowed miss path and the limiter under-enforces"
        );
    }

    #[tokio::test]
    async fn test_tick_runs_writes_before_reads() {
        let mock = Arc::new(MockRedisClient::new());
        let client: Arc<dyn Client + Send + Sync> = mock.clone();
        let config = config_with_floor(0);
        let cache: Cache<String, CacheEntry> = Cache::builder().max_capacity(100).build();
        let pending: Arc<DashSet<String>> = Arc::new(DashSet::new());
        pending.insert("read_key".to_string());
        let mut writes: HashMap<(String, i64), u64> = HashMap::new();
        // Current epoch: a stale epoch would be purged before the write runs.
        let epoch = epoch_from_timestamp(Utc::now(), config.window_interval);
        writes.insert(("write_key".to_string(), epoch), 5);

        GlobalRateLimiterImpl::tick(
            &config,
            std::slice::from_ref(&client),
            &cache,
            &pending,
            &mut writes,
            "test",
            1,
        )
        .await;

        let calls = mock.get_calls();
        let first_read = calls.iter().position(|c| c.op == "mget");
        let first_write = calls.iter().position(|c| c.op.starts_with("batch_incr"));
        assert!(
            first_read.is_some() && first_write.is_some(),
            "tick should issue both a read and a write"
        );
        assert!(
            first_write < first_read,
            "writes must land before reads: the read result zeroes each synced \
             key's local_pending, so a read that predates this tick's writes \
             silently discards those counts until the next sync. calls={calls:?}"
        );
    }

    #[tokio::test]
    async fn test_pending_sync_cap_drops_new_keys() {
        // Keys clearing the sync floor faster than the per-tick drain must not
        // grow pending_sync without bound; at the cap, new sync requests drop
        // (the key re-queues on its next request) while known keys stay queued.
        let client = Arc::new(MockRedisClient::new());
        let config = GlobalRateLimiterConfig {
            max_pending_sync_entries: 2,
            ..config_with_floor(0)
        };
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        for key in ["a", "b", "c", "d"] {
            limiter.check_limit(key, 1, None).await;
        }

        assert_eq!(
            limiter.pending_sync.len(),
            2,
            "pending_sync must stop growing at max_pending_sync_entries"
        );
    }

    #[tokio::test]
    async fn test_write_batch_cap_drops_new_keys_but_merges_existing() {
        // At the cap, an update for a brand-new key is dropped (bounded memory
        // beats an unbounded map under unique-key floods), while an update for
        // a key already in the batch still merges -- merging costs no memory
        // and dropping it would silently undercount a key we are tracking.
        let mut batch: HashMap<(String, i64), u64> = HashMap::new();
        batch.insert(("k1".to_string(), 1), 5);
        batch.insert(("k2".to_string(), 1), 5);

        GlobalRateLimiterImpl::absorb_update(&mut batch, "k3".to_string(), 1, 7, 2, "test");
        assert_eq!(batch.len(), 2, "new key at cap must be dropped");
        assert!(!batch.contains_key(&("k3".to_string(), 1)));

        GlobalRateLimiterImpl::absorb_update(&mut batch, "k1".to_string(), 1, 7, 2, "test");
        assert_eq!(
            batch.get(&("k1".to_string(), 1)),
            Some(&12),
            "existing key at cap must still merge"
        );
    }

    #[tokio::test]
    async fn test_tick_purges_stale_epochs_instead_of_writing_them() {
        let mock = Arc::new(MockRedisClient::new());
        let client: Arc<dyn Client + Send + Sync> = mock.clone();
        let config = config_with_floor(0); // 60s window
        let cache: Cache<String, CacheEntry> = Cache::builder().max_capacity(100).build();
        let pending: Arc<DashSet<String>> = Arc::new(DashSet::new());

        let current_epoch = epoch_from_timestamp(Utc::now(), config.window_interval);
        let mut writes: HashMap<(String, i64), u64> = HashMap::new();
        writes.insert(("live".to_string(), current_epoch), 1);
        writes.insert(("stale".to_string(), current_epoch - 5), 1);

        GlobalRateLimiterImpl::tick(
            &config,
            std::slice::from_ref(&client),
            &cache,
            &pending,
            &mut writes,
            "test",
            1,
        )
        .await;

        let write_calls: Vec<String> = mock
            .get_calls()
            .into_iter()
            .filter(|c| c.op == "batch_incr_by_expire")
            .map(|c| c.key)
            .collect();
        assert_eq!(
            write_calls,
            vec![format!("items=1;ttl={}", config.global_cache_ttl.as_secs())],
            "only the readable-epoch entry may be written; a stale epoch can              never be read (reads consult current + previous only) and must              not spend write commands"
        );
        assert!(
            writes.is_empty(),
            "stale entry must be purged, not deferred"
        );
    }

    #[tokio::test]
    async fn test_tick_bounds_write_drain_and_carries_remainder() {
        let client: Arc<dyn Client + Send + Sync> = Arc::new(MockRedisClient::new());
        let config = GlobalRateLimiterConfig {
            max_sync_keys_per_tick: 10,
            ..config_with_floor(0)
        };
        let cache: Cache<String, CacheEntry> = Cache::builder().max_capacity(100).build();
        let pending: Arc<DashSet<String>> = Arc::new(DashSet::new());
        let mut writes: HashMap<(String, i64), u64> = HashMap::new();
        let epoch = epoch_from_timestamp(Utc::now(), config.window_interval);
        for i in 0..25 {
            writes.insert((format!("w{i}"), epoch), 1);
        }

        GlobalRateLimiterImpl::tick(
            &config,
            std::slice::from_ref(&client),
            &cache,
            &pending,
            &mut writes,
            "test",
            1,
        )
        .await;

        assert_eq!(
            writes.len(),
            15,
            "tick must drain at most max_sync_keys_per_tick write entries and \
             leave the remainder batched -- deferring keeps counts (they merge by \
             key+epoch and land a tick late), dropping them would lose counts"
        );
    }

    #[tokio::test]
    async fn test_idle_tier_key_above_floor_still_syncs() {
        let client = Arc::new(MockRedisClient::new());
        let config = GlobalRateLimiterConfig {
            global_threshold: 1000,
            ..config_with_floor(10)
        };
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        // Locally accumulated events don't decay, so this entry sits at level 50:
        // idle by pressure (0.05 < 0.1) but well above the absolute floor, and
        // last synced longer ago than the Low cadence (4 * 15s).
        limiter.cache.insert(
            "fleet_hot".to_string(),
            CacheEntry {
                estimated_count: 0.0,
                synced_at: Some(Instant::now() - Duration::from_secs(120)),
                local_pending: 50,
                pressure: 0.05,
            },
        );

        limiter.check_limit("fleet_hot", 1, None).await;

        assert!(
            limiter.pending_sync.contains("fleet_hot"),
            "an idle-tier key above the floor must still sync, else a key hot across \
             the fleet but cold on any single node is never discovered and never limited"
        );
    }

    #[tokio::test]
    async fn test_tick_bounds_drain_and_chunks_reads() {
        let mock = Arc::new(MockRedisClient::new());
        let client: Arc<dyn Client + Send + Sync> = mock.clone();
        let config = GlobalRateLimiterConfig {
            max_sync_keys_per_tick: 10,
            // 2 entities per read command (two epoch keys each).
            max_keys_per_command: 4,
            ..config_with_floor(0)
        };
        let cache: Cache<String, CacheEntry> = Cache::builder().max_capacity(1000).build();
        let pending: Arc<DashSet<String>> = Arc::new(DashSet::new());
        for i in 0..25 {
            pending.insert(format!("k{i}"));
        }
        let mut writes: HashMap<(String, i64), u64> = HashMap::new();

        GlobalRateLimiterImpl::tick(
            &config,
            std::slice::from_ref(&client),
            &cache,
            &pending,
            &mut writes,
            "test",
            1,
        )
        .await;

        assert_eq!(
            pending.len(),
            15,
            "tick must take at most max_sync_keys_per_tick and leave the remainder \
             queued -- deferring keeps the tick inside its interval, dropping them \
             would silently lose syncs"
        );

        let mget_calls = mock
            .get_calls()
            .into_iter()
            .filter(|c| c.op == "mget")
            .count();
        assert_eq!(
            mget_calls, 5,
            "10 drained keys at 2 entities per command must issue 5 bounded MGETs, \
             not one oversized command that cannot fit the per-command timeout"
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
                synced_at: Some(Instant::now() - Duration::from_secs(60)),
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
                synced_at: Some(Instant::now() - Duration::from_secs(30)),
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
        let config = test_config();
        set_custom_keys(&config, &[("custom_entity", 100)]);
        let cache = Cache::builder()
            .max_capacity(100)
            .time_to_live(Duration::from_secs(60))
            .time_to_idle(Duration::from_secs(30))
            .build();

        cache.insert(
            "custom_entity".to_string(),
            CacheEntry {
                estimated_count: 0.0,
                synced_at: Some(Instant::now() - Duration::from_secs(30)),
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
                    synced_at: Some(Instant::now() - Duration::from_secs(30)),
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

    // --- Tier distribution scan tests ---

    fn seed_entry(pressure: f64) -> CacheEntry {
        CacheEntry {
            estimated_count: 0.0,
            synced_at: Some(Instant::now() - Duration::from_secs(30)),
            local_pending: 0,
            pressure,
        }
    }

    #[test]
    fn test_scan_tier_counts_tallies_distribution() {
        let cache = Cache::builder().max_capacity(100).build();
        cache.insert("a".to_string(), seed_entry(0.0)); // idle
        cache.insert("b".to_string(), seed_entry(0.05)); // idle
        cache.insert("c".to_string(), seed_entry(0.3)); // low
        cache.insert("d".to_string(), seed_entry(0.6)); // normal
        cache.insert("e".to_string(), seed_entry(0.9)); // hot
        cache.insert("f".to_string(), seed_entry(0.95)); // hot
        cache.run_pending_tasks();

        let counts = GlobalRateLimiterImpl::scan_tier_counts(&cache);

        assert_eq!(counts[PressureTier::Idle.index()], 2);
        assert_eq!(counts[PressureTier::Low.index()], 1);
        assert_eq!(counts[PressureTier::Normal.index()], 1);
        assert_eq!(counts[PressureTier::Hot.index()], 2);
        assert_eq!(counts.iter().sum::<u64>(), cache.entry_count());
    }

    #[test]
    fn test_scan_tier_counts_excludes_evicted_entries() {
        // Size-based eviction: only the surviving entries should be tallied,
        // and the total must match entry_count after maintenance.
        let cache = Cache::builder().max_capacity(3).build();
        for i in 0..10 {
            cache.insert(format!("k{i}"), seed_entry(0.9)); // all hot
        }
        cache.run_pending_tasks();

        let counts = GlobalRateLimiterImpl::scan_tier_counts(&cache);

        assert_eq!(counts.iter().sum::<u64>(), cache.entry_count());
        assert!(cache.entry_count() <= 3);
    }

    #[test]
    fn test_scan_tier_counts_empty_cache() {
        let cache: Cache<String, CacheEntry> = Cache::builder().max_capacity(100).build();
        cache.run_pending_tasks();

        let counts = GlobalRateLimiterImpl::scan_tier_counts(&cache);

        assert_eq!(counts, [0, 0, 0, 0]);
    }

    #[test]
    fn test_parse_redis_count() {
        assert_eq!(parse_redis_count(&Some(b"42".to_vec())), 42);
        assert_eq!(parse_redis_count(&Some(b"0".to_vec())), 0);
        assert_eq!(parse_redis_count(&None), 0);
        assert_eq!(parse_redis_count(&Some(b"not_a_number".to_vec())), 0);
        assert_eq!(parse_redis_count(&Some(vec![])), 0);
    }

    // --- Dynamic custom-key map tests (ArcSwap + resolver) ---

    #[test]
    fn test_resolve_custom_default_exact_match() {
        let config = test_config();
        set_custom_keys(&config, &[("tok:did", 5), ("tok2", 9)]);

        assert_eq!(config.resolve_custom("tok:did"), Some(5));
        assert_eq!(config.resolve_custom("tok2"), Some(9));
        assert_eq!(config.resolve_custom("missing"), None);
        // Default resolver is exact: a token prefix must not match a token:did entry.
        assert_eq!(config.resolve_custom("tok"), None);
    }

    #[test]
    fn test_resolve_custom_injected_resolver_hierarchical() {
        let mut config = test_config();
        // Hierarchical policy: exact key first, then the token prefix before ':'.
        config.custom_key_resolver = Some(Arc::new(|key: &str, map: &HashMap<String, u64>| {
            if let Some(v) = map.get(key) {
                return Some(*v);
            }
            key.split_once(':')
                .and_then(|(tok, _)| map.get(tok).copied())
        }));
        set_custom_keys(&config, &[("tok", 7), ("tok:vip", 100)]);

        assert_eq!(config.resolve_custom("tok:vip"), Some(100)); // exact wins
        assert_eq!(config.resolve_custom("tok:other"), Some(7)); // falls back to token
        assert_eq!(config.resolve_custom("tok"), Some(7)); // token itself
        assert_eq!(config.resolve_custom("nope:x"), None); // no match at any level
    }

    #[tokio::test]
    async fn test_custom_keys_swap_visible_to_running_limiter() {
        let client = Arc::new(MockRedisClient::new());
        let config = test_config();
        // The refresh task swaps through a clone of the config; hold one here to
        // drive the same shared ArcSwap the running limiter reads.
        let cfg_handle = config.clone();
        let limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        assert!(!limiter.is_custom_key("dyn_key"));
        let result = limiter.check_custom_limit("dyn_key", 1, None).await;
        assert!(matches!(result, EvalResult::NotApplicable));

        cfg_handle
            .custom_keys
            .store(Arc::new(HashMap::from([("dyn_key".to_string(), 42u64)])));

        assert!(limiter.is_custom_key("dyn_key"));
        // Now subject to a custom limit: a fresh key is Allowed (cache miss), not NotApplicable.
        let result = limiter.check_custom_limit("dyn_key", 1, None).await;
        assert!(
            matches!(result, EvalResult::Allowed),
            "swapped-in custom key should be evaluated, got {result:?}"
        );
    }

    #[test]
    fn test_custom_keys_swap_shared_across_config_clones() {
        // The background task holds a *clone* of the config; a swap through the
        // clone must be visible to the original (shared ArcSwap).
        let config = test_config();
        let bg_clone = config.clone();

        assert_eq!(config.resolve_custom("k"), None);
        bg_clone
            .custom_keys
            .store(Arc::new(HashMap::from([("k".to_string(), 3u64)])));
        assert_eq!(config.resolve_custom("k"), Some(3));
    }

    #[test]
    fn test_custom_keys_concurrent_read_is_consistent() {
        // Readers never observe a torn map: each load sees either the fully-old
        // or fully-new map, never a missing/partial value.
        use std::sync::atomic::{AtomicBool, Ordering};

        let config = Arc::new(test_config());
        set_custom_keys(&config, &[("k", 1)]);

        let stop = Arc::new(AtomicBool::new(false));
        let reader = {
            let config = config.clone();
            let stop = stop.clone();
            std::thread::spawn(move || {
                while !stop.load(Ordering::Relaxed) {
                    let v = config.resolve_custom("k");
                    assert!(matches!(v, Some(1) | Some(100)), "torn read: {v:?}");
                }
            })
        };

        for i in 0..10_000 {
            let v = if i % 2 == 0 { 1u64 } else { 100u64 };
            config
                .custom_keys
                .store(Arc::new(HashMap::from([("k".to_string(), v)])));
        }
        stop.store(true, Ordering::Relaxed);
        reader.join().unwrap();
    }

    // --- Refresh path tests (refresh_custom_keys_once via a mock source) ---

    #[tokio::test]
    async fn test_refresh_once_applies_thresholds() {
        let config = test_config();
        set_custom_keys(&config, &[("seed", 1)]);

        let source = MockCustomKeyThresholdSource::with_thresholds(Some(HashMap::from([(
            "dyn".to_string(),
            99u64,
        )])));
        GlobalRateLimiterImpl::refresh_custom_keys_once(&config, &source, "test").await;

        // Fetched map replaces the seed wholesale (Redis is authoritative).
        assert_eq!(config.resolve_custom("dyn"), Some(99));
        assert_eq!(config.resolve_custom("seed"), None);
    }

    #[tokio::test]
    async fn test_refresh_once_absent_key_is_fail_static() {
        let config = test_config();
        set_custom_keys(&config, &[("seed", 1)]);

        let source = MockCustomKeyThresholdSource::with_thresholds(None);
        GlobalRateLimiterImpl::refresh_custom_keys_once(&config, &source, "test").await;

        // Absent key is ambiguous (fresh rollout / eviction / accidental delete),
        // not an authoritative clear: the current thresholds must survive.
        assert_eq!(config.resolve_custom("seed"), Some(1));
    }

    #[tokio::test]
    async fn test_refresh_once_empty_blob_clears_thresholds() {
        let config = test_config();
        set_custom_keys(&config, &[("seed", 1)]);

        // An explicit empty blob (`{}` in Redis) is the deliberate clear signal,
        // distinct from an absent key: it replaces the map with an empty one.
        let source = MockCustomKeyThresholdSource::with_thresholds(Some(HashMap::new()));
        GlobalRateLimiterImpl::refresh_custom_keys_once(&config, &source, "test").await;

        assert_eq!(config.resolve_custom("seed"), None);
    }

    #[tokio::test]
    async fn test_refresh_once_error_is_fail_static() {
        let config = test_config();
        set_custom_keys(&config, &[("keep", 7)]);

        let source =
            MockCustomKeyThresholdSource::with_error(common_redis::CustomRedisError::Timeout);
        GlobalRateLimiterImpl::refresh_custom_keys_once(&config, &source, "test").await;

        // A failed fetch must not disturb the current thresholds.
        assert_eq!(config.resolve_custom("keep"), Some(7));
    }

    // --- Refresh task lifecycle (spawn on new(), stop on shutdown()) ---

    /// Poll `cond`, driving the paused clock forward so the interval-based refresh
    /// task gets a chance to tick, up to a bounded number of iterations.
    async fn wait_until<F: Fn() -> bool>(cond: F) -> bool {
        for _ in 0..50 {
            if cond() {
                return true;
            }
            tokio::time::advance(Duration::from_secs(60)).await;
            tokio::task::yield_now().await;
        }
        cond()
    }

    #[tokio::test(start_paused = true)]
    async fn test_refresh_task_spawns_ticks_and_stops_on_shutdown() {
        let mock = Arc::new(MockCustomKeyThresholdSource::with_thresholds(Some(
            HashMap::from([("first".to_string(), 11u64)]),
        )));
        let mut config = test_config();
        // Hold the shared ArcSwap so we can observe swaps the spawned task makes.
        let observed = config.custom_keys.clone();
        config.custom_key_source = Some(mock.clone() as Arc<dyn CustomKeyThresholdSource>);
        config.custom_key_refresh_interval = Duration::from_secs(60);

        let client = Arc::new(MockRedisClient::new());
        let mut limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        // The task ticks immediately on spawn and applies the initial map.
        assert!(
            wait_until(|| observed.load().get("first") == Some(&11)).await,
            "refresh task should apply the initial map after spawn"
        );

        // A subsequent Redis-side change is picked up on the next tick.
        mock.set_thresholds(Some(HashMap::from([("second".to_string(), 22u64)])))
            .await;
        assert!(
            wait_until(|| observed.load().get("second") == Some(&22)).await,
            "refresh task should apply an updated map on a later tick"
        );

        // After shutdown the task must exit: let it observe the closed stop channel.
        limiter.shutdown();
        for _ in 0..20 {
            tokio::task::yield_now().await;
        }

        // A change made after shutdown must never be applied.
        mock.set_thresholds(Some(HashMap::from([("third".to_string(), 33u64)])))
            .await;
        for _ in 0..10 {
            tokio::time::advance(Duration::from_secs(120)).await;
            tokio::task::yield_now().await;
        }
        assert!(
            observed.load().get("third").is_none(),
            "refresh task must not apply changes after shutdown"
        );
        // The last pre-shutdown value is still in place.
        assert_eq!(observed.load().get("second"), Some(&22));
    }

    #[tokio::test(start_paused = true)]
    async fn test_zero_refresh_interval_is_clamped_not_panicking() {
        // A zero interval would panic `tokio::time::interval` and kill the
        // detached refresh task; the clamp must keep it running and ticking.
        let mock = Arc::new(MockCustomKeyThresholdSource::with_thresholds(Some(
            HashMap::from([("only".to_string(), 9u64)]),
        )));
        let mut config = test_config();
        let observed = config.custom_keys.clone();
        config.custom_key_source = Some(mock.clone() as Arc<dyn CustomKeyThresholdSource>);
        config.custom_key_refresh_interval = Duration::ZERO;

        let client = Arc::new(MockRedisClient::new());
        let _limiter = GlobalRateLimiterImpl::new(config, vec![client]).unwrap();

        assert!(
            wait_until(|| observed.load().get("only") == Some(&9)).await,
            "clamped refresh task should still apply the initial map"
        );
    }
}
