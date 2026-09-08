use std::borrow::Cow;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use crate::config::Config;
use arc_swap::ArcSwap;
use chrono::Utc;
use common_redis::Client;
use limiters::custom_key_source::{CustomKeyThresholdSource, RedisCustomKeyThresholdSource};
use limiters::global_rate_limiter::{
    CustomKeyResolver, EvalResult, GlobalRateLimitResponse,
    GlobalRateLimiter as CommonGlobalRateLimiter, GlobalRateLimiterConfig,
    GlobalRateLimiterImpl as CommonGlobalRateLimiterImpl,
};
use metrics::counter;
use tracing::{error, info, warn};

#[cfg(test)]
use chrono::DateTime;

const MAX_DISTINCT_ID_CHARS: usize = 128;

fn truncate_str(s: &str, max_chars: usize) -> &str {
    match s.char_indices().nth(max_chars) {
        Some((idx, _)) => &s[..idx],
        None => s,
    }
}

pub enum GlobalRateLimitKey<'a> {
    /// Token-only key. Not currently used in production call sites.
    Token(&'a str),
    TokenDistinctId(&'a str, &'a str),
}

impl<'a> GlobalRateLimitKey<'a> {
    pub fn to_cache_key(&self) -> Cow<'a, str> {
        match self {
            Self::Token(t) => Cow::Borrowed(t),
            Self::TokenDistinctId(t, d) => {
                Cow::Owned(format!("{t}:{}", truncate_str(d, MAX_DISTINCT_ID_CHARS)))
            }
        }
    }
}

/// Redis key prefix for the AI lane's byte budget. Unlike the event limiters
/// this deliberately carries no `capture_mode`: AI events reach the AI topic
/// from the capture-ai deployment and from AI traffic diverted on
/// capture-analytics, so one token must draw on one budget across both. Both
/// deployments therefore have to point at the same rate-limiter Redis.
const AI_BYTES_REDIS_KEY_PREFIX: &str = "@ph/grl/capture/ai_bytes";

/// The per-instance knobs that distinguish one capture limiter from another.
/// Named fields rather than positional arguments: several are same-typed (two
/// `&str`, two `bool`) and a swap would silently misconfigure a limiter.
struct LimiterSpec<'a> {
    /// Sliding window this limiter counts over. Sets Redis epoch numbering, so
    /// limiters that share a key prefix must agree on it.
    window_secs: u64,
    /// Env var that supplied `window_secs`, so a zero window names the knob the
    /// operator has to fix rather than the limiter that noticed.
    window_env_var: &'a str,
    /// Default budget per window for keys with no custom override.
    threshold: u64,
    /// Static `key=value` CSV seeding the custom-key map.
    custom_keys_csv: Option<&'a String>,
    /// Multiplier applied to each seeded CSV value, for limiters whose
    /// operator-facing unit is not the window budget: the AI byte limiter is
    /// configured in bytes/second and enforces bytes/window. `1` when the CSV
    /// already carries per-window values.
    custom_key_scale: u64,
    local_cache_max_entries: u64,
    /// Minimum local level before a key earns a Redis sync. The unit is
    /// whatever the limiter counts, so an event limiter's floor is in events
    /// and the AI byte limiter's is in bytes.
    min_sync_floor: u64,
    redis_key_prefix: &'a str,
    metrics_scope: &'a str,
    /// Whether to wire the Redis-backed dynamic threshold source.
    enable_dynamic_source: bool,
    /// Evaluate and report, but never enforce.
    dry_run: bool,
}

/// The window the AI byte budget is enforced over, and the env var that
/// supplied it. `AI_BYTE_LIMIT_WINDOW_INTERVAL_SECS` wins when set; otherwise
/// the shared limiter window applies. Every place that derives the AI byte
/// budget from a window must call this, so the enforced budget and any
/// diagnostic computed from it cannot disagree.
pub fn ai_byte_limit_window(config: &Config) -> (u64, &'static str) {
    match config.ai_byte_limit_window_interval_secs {
        Some(secs) => (secs, "AI_BYTE_LIMIT_WINDOW_INTERVAL_SECS"),
        None => (
            config.global_rate_limit_window_interval_secs,
            "GLOBAL_RATE_LIMIT_WINDOW_INTERVAL_SECS",
        ),
    }
}

pub struct GlobalRateLimiter {
    limiter: Box<dyn CommonGlobalRateLimiter>,
    dry_run: bool,
}

impl GlobalRateLimiter {
    /// Create a per-(token, distinct_id) rate limiter sharing the given Redis instances.
    pub fn new_token_distinct_id(
        config: &Config,
        redis_instances: Vec<Arc<dyn Client + Send + Sync>>,
    ) -> anyhow::Result<Self> {
        let prefix = format!(
            "@ph/grl/capture/tok_distid/{}",
            config.capture_mode.as_tag()
        );
        let metrics_scope = format!("{}_tok_distid", config.capture_mode.as_tag());
        Self::build(
            config,
            redis_instances,
            LimiterSpec {
                window_secs: config.global_rate_limit_window_interval_secs,
                window_env_var: "GLOBAL_RATE_LIMIT_WINDOW_INTERVAL_SECS",
                threshold: config.global_rate_limit_token_distinctid_threshold,
                custom_keys_csv: config
                    .global_rate_limit_token_distinctid_overrides_csv
                    .as_ref(),
                custom_key_scale: 1,
                local_cache_max_entries: config
                    .global_rate_limit_token_distinctid_local_cache_max_entries,
                min_sync_floor: config.global_rate_limit_min_sync_floor,
                redis_key_prefix: &prefix,
                metrics_scope: &metrics_scope,
                enable_dynamic_source: config.global_rate_limit_custom_threshold_key.is_some(),
                dry_run: config.global_rate_limit_dry_run,
            },
        )
    }

    /// Create a per-token rate limiter sharing the given Redis instances.
    /// Not currently wired into production call sites -- retained for future use.
    pub fn new_token(
        config: &Config,
        redis_instances: Vec<Arc<dyn Client + Send + Sync>>,
    ) -> anyhow::Result<Self> {
        let prefix = format!("@ph/grl/capture/token/{}", config.capture_mode.as_tag());
        let metrics_scope = format!("{}_token", config.capture_mode.as_tag());
        Self::build(
            config,
            redis_instances,
            LimiterSpec {
                window_secs: config.global_rate_limit_window_interval_secs,
                window_env_var: "GLOBAL_RATE_LIMIT_WINDOW_INTERVAL_SECS",
                threshold: config.global_rate_limit_token_threshold,
                custom_keys_csv: config.global_rate_limit_token_overrides_csv.as_ref(),
                custom_key_scale: 1,
                local_cache_max_entries: config.global_rate_limit_token_local_cache_max_entries,
                min_sync_floor: config.global_rate_limit_min_sync_floor,
                redis_key_prefix: &prefix,
                metrics_scope: &metrics_scope,
                // The token-only limiter is not wired to the dynamic refresh
                // source. (The hierarchical resolver is still set but is a no-op
                // for bare token keys, which have no `:distinct_id` suffix.)
                enable_dynamic_source: false,
                dry_run: config.global_rate_limit_dry_run,
            },
        )
    }

    /// Create the AI lane's per-token byte budget, sharing the given Redis instances.
    ///
    /// Nothing about the underlying limiter changes: the counts it accumulates
    /// are bytes rather than events, so the same sliding window that caps
    /// events/window elsewhere caps bytes/window here. Callers pass an event's
    /// serialized size as the count.
    ///
    /// Budgets are configured in bytes/second and scaled to the window, so the
    /// knob keeps the same meaning whatever `GLOBAL_RATE_LIMIT_WINDOW_INTERVAL_SECS`
    /// is set to.
    pub fn new_ai_bytes(
        config: &Config,
        redis_instances: Vec<Arc<dyn Client + Send + Sync>>,
    ) -> anyhow::Result<Self> {
        // `build` refuses to boot on a zero window, so this scaling never
        // divides a budget down to nothing.
        let (window_secs, window_env_var) = ai_byte_limit_window(config);
        let metrics_scope = format!("{}_ai_bytes", config.capture_mode.as_tag());
        Self::build(
            config,
            redis_instances,
            LimiterSpec {
                window_secs,
                window_env_var,
                threshold: config.ai_byte_limit_per_second.saturating_mul(window_secs),
                custom_keys_csv: config.ai_byte_limit_overrides_csv.as_ref(),
                custom_key_scale: window_secs,
                local_cache_max_entries: config.ai_byte_limit_local_cache_max_entries,
                // No floor. The shared knob is an event count, and this
                // limiter counts bytes, so inheriting it would be a unit
                // confusion that reads as deliberate. The floor exists to keep
                // an unbounded key space off Redis; this limiter's keys are
                // projects sending AI traffic, few enough that syncing all of
                // them is cheap and accurate enforcement is worth more.
                min_sync_floor: 0,
                redis_key_prefix: AI_BYTES_REDIS_KEY_PREFIX,
                metrics_scope: &metrics_scope,
                // Thresholds come from config only; the Django-written blob
                // holds event-count limits, in different units.
                enable_dynamic_source: false,
                dry_run: config.ai_byte_limit_dry_run,
            },
        )
    }

    /// Hierarchical custom-key resolver. Always applied to capture limiters,
    /// whether thresholds come from the static CSV seed or the dynamic source.
    ///
    /// A lookup key is either `token` or `token:distinct_id` (the limiter's cache
    /// key). Resolution tries the exact key first, then falls back to the token
    /// prefix (everything before the first `:`) so a token-level override applies
    /// to all of that token's `token:distinct_id` keys. Keeps capture's key
    /// structure out of the common crate.
    fn hierarchical_resolver() -> CustomKeyResolver {
        Arc::new(|key: &str, map: &HashMap<String, u64>| {
            if let Some(v) = map.get(key) {
                return Some(*v);
            }
            key.split_once(':')
                .and_then(|(token, _)| map.get(token).copied())
        })
    }

    fn build(
        config: &Config,
        redis_instances: Vec<Arc<dyn Client + Send + Sync>>,
        spec: LimiterSpec<'_>,
    ) -> anyhow::Result<Self> {
        // `leak_rate_for` divides the threshold by the window, so a zero window
        // gives every bucket an infinite leak rate and the limiter admits
        // everything. That is the opposite of what an operator setting a limit
        // asked for, and it fails silently, so refuse to boot on it.
        if spec.window_secs == 0 {
            anyhow::bail!(
                "invalid configuration: {} must be greater than 0 (limiter {}); \
                 a zero window gives every key an infinite leak rate, so no limit is ever enforced",
                spec.window_env_var,
                spec.metrics_scope
            );
        }

        // Seed the (swappable) custom-key map from the static CSV overrides. When a
        // dynamic source is enabled, the common refresh loop replaces this map only
        // from an explicit Redis blob; an absent key or an unreachable Redis is
        // fail-static, so the CSV seed keeps applying until a blob is written.
        let mut seed = Self::format_custom_keys(spec.custom_keys_csv);
        if spec.custom_key_scale != 1 {
            for value in seed.values_mut() {
                *value = value.saturating_mul(spec.custom_key_scale);
            }
        }

        // Build the dynamic source when enabled and its Redis key + URL are set.
        // The source reads the JSON blob from the event-restrictions Redis (a
        // separate store from the traffic-count Redis in `redis_instances`) and
        // owns its own connection/reconnect; the common limiter runs the loop.
        let custom_key_source: Option<Arc<dyn CustomKeyThresholdSource>> = if spec
            .enable_dynamic_source
        {
            match (
                config.global_rate_limit_custom_threshold_key.as_ref(),
                config.event_restrictions_redis_url.as_ref(),
            ) {
                (Some(key), Some(redis_url)) => {
                    let response_timeout = (config.redis_response_timeout_ms != 0)
                        .then(|| Duration::from_millis(config.redis_response_timeout_ms));
                    let connection_timeout = (config.redis_connection_timeout_ms != 0)
                        .then(|| Duration::from_millis(config.redis_connection_timeout_ms));
                    Some(Arc::new(RedisCustomKeyThresholdSource::new(
                        redis_url.clone(),
                        key.clone(),
                        response_timeout,
                        connection_timeout,
                    )))
                }
                _ => {
                    warn!(
                        "Dynamic custom thresholds requested but threshold key or Redis URL is unset; using static CSV seed"
                    );
                    None
                }
            }
        } else {
            None
        };

        let grl_config = GlobalRateLimiterConfig {
            global_threshold: spec.threshold,
            window_interval: Duration::from_secs(spec.window_secs),
            sync_interval: Duration::from_secs(config.global_rate_limit_sync_interval_secs),
            tick_interval: Duration::from_millis(config.global_rate_limit_tick_interval_ms),
            redis_key_prefix: spec.redis_key_prefix.to_string(),
            custom_keys: Arc::new(ArcSwap::from_pointee(seed)),
            // Capture keys are always `token` or `token:distinct_id`, so the
            // hierarchical resolver is always the correct policy — a token-level
            // override applies to all of that token's `token:distinct_id` keys,
            // for both the CSV seed and the dynamic map.
            custom_key_resolver: Some(Self::hierarchical_resolver()),
            custom_key_source,
            custom_key_refresh_interval: Duration::from_secs(
                config.global_rate_limit_custom_threshold_refresh_secs,
            ),
            local_cache_max_entries: spec.local_cache_max_entries,
            metrics_scope: spec.metrics_scope.to_string(),
            min_sync_floor: spec.min_sync_floor,
            max_sync_keys_per_tick: config.global_rate_limit_max_sync_keys_per_tick,
            max_keys_per_command: config.global_rate_limit_max_keys_per_command,
            max_concurrent_commands: config.global_rate_limit_max_concurrent_commands,
            max_write_batch_entries: config.global_rate_limit_max_write_batch_entries,
            max_pending_sync_entries: config.global_rate_limit_max_pending_sync_entries,
            global_read_timeout: Duration::from_millis(config.global_rate_limit_read_timeout_ms),
            global_write_timeout: Duration::from_millis(config.global_rate_limit_write_timeout_ms),
            local_cache_ttl: Duration::from_secs(config.global_rate_limit_local_cache_ttl_secs),
            local_cache_idle_timeout: Duration::from_secs(
                config.global_rate_limit_local_cache_idle_timeout_secs,
            ),
            ..Default::default()
        };

        let dry_run = spec.dry_run;

        let limiter = match CommonGlobalRateLimiterImpl::new(grl_config, redis_instances) {
            Ok(l) => l,
            Err(e) => {
                error!(error = %e, "Failed to initialize GlobalRateLimiter");
                return Err(e);
            }
        };

        if dry_run {
            info!(
                scope = spec.metrics_scope,
                "GlobalRateLimiter initialized in dry-run mode (evaluating but not enforcing)"
            );
        }

        Ok(Self {
            limiter: Box::new(limiter),
            dry_run,
        })
    }

    /// Check if a key is rate limited. The key is resolved against the custom-key
    /// map exactly once: `check_custom_limit` returns `NotApplicable` for keys
    /// without a custom override, and only then do we fall back to the global
    /// threshold check. Routing and threshold therefore come from a single map
    /// snapshot, so a concurrent custom-map swap can't misroute a request (a
    /// prior `is_custom_key` probe + separate check made two independent loads
    /// that could straddle a swap). Exactly one enforcing check fires — the
    /// `NotApplicable` probe returns before touching the cache or Redis batch
    /// channel, so there's no double-enqueue.
    ///
    /// In dry-run mode the underlying limiter is still evaluated (counts are
    /// tracked, Redis is synced) but the result is suppressed: metrics and a
    /// warn log are emitted, then `None` is returned so callers never enforce.
    pub async fn is_limited(&self, key: &str, count: u64) -> Option<GlobalRateLimitResponse> {
        let result = match self
            .limiter
            .check_custom_limit(key, count, Some(Utc::now()))
            .await
        {
            // No custom override for this key: enforce the global threshold.
            EvalResult::NotApplicable => self.is_global_key_limited(key, count).await,
            EvalResult::Limited(response) => Some(response),
            // Allowed / FailOpen on a key that HAS a custom override: not limited,
            // and we must not re-check it against the global threshold.
            _ => None,
        };

        match (result, self.dry_run) {
            (Some(response), true) => {
                counter!(
                    "capture_global_rate_limiter_dry_run",
                    "key_type" => if response.is_custom_limited { "custom" } else { "global" },
                )
                .increment(1);
                warn!(
                    key = key,
                    current_count = response.current_count,
                    threshold = response.threshold,
                    is_custom_limited = response.is_custom_limited,
                    dry_run = true,
                    "global rate limiter would have limited (dry run)"
                );
                None
            }
            (result, _) => result,
        }
    }

    async fn is_global_key_limited(
        &self,
        key: &str,
        count: u64,
    ) -> Option<GlobalRateLimitResponse> {
        match self.limiter.check_limit(key, count, Some(Utc::now())).await {
            EvalResult::Limited(response) => Some(response),
            _ => None,
        }
    }

    // trigger shutdown and stop pushing updates to global cache. Also stops the
    // common custom-key refresh loop, if one was spawned.
    pub fn shutdown(&mut self) {
        self.limiter.shutdown();
    }

    /// Returns true if the key resolves to a custom threshold (exact match, or
    /// token-prefix fallback via the hierarchical resolver).
    pub fn is_custom_key(&self, key: &str) -> bool {
        self.limiter.is_custom_key(key)
    }

    pub async fn build_redis_client(
        config: &Config,
        shared_redis: Arc<dyn Client + Send + Sync>,
    ) -> anyhow::Result<Arc<dyn Client + Send + Sync>> {
        let Some(ref writer_url) = config.global_rate_limit_redis_url else {
            return Ok(shared_redis);
        };

        let response_timeout = config
            .global_rate_limit_redis_response_timeout_ms
            .unwrap_or(config.redis_response_timeout_ms);
        let connection_timeout = config
            .global_rate_limit_redis_connection_timeout_ms
            .unwrap_or(config.redis_connection_timeout_ms);
        let response_timeout = if response_timeout == 0 {
            None
        } else {
            Some(Duration::from_millis(response_timeout))
        };
        let connection_timeout = if connection_timeout == 0 {
            None
        } else {
            Some(Duration::from_millis(connection_timeout))
        };

        if let Some(ref reader_url) = config.global_rate_limit_redis_reader_url {
            info!("Global rate limiter using read/write split Redis client");
            let rw_config = common_redis::ReadWriteClientConfig::new(
                writer_url.clone(),
                reader_url.clone(),
                common_redis::CompressionConfig::disabled(),
                common_redis::RedisValueFormat::default(),
                response_timeout,
                connection_timeout,
            );
            Ok(Arc::new(rw_config.build().await?))
        } else {
            Ok(Arc::new(
                common_redis::RedisClient::with_config(
                    writer_url.clone(),
                    common_redis::CompressionConfig::disabled(),
                    common_redis::RedisValueFormat::default(),
                    response_timeout,
                    connection_timeout,
                )
                .await?,
            ))
        }
    }

    #[cfg(test)]
    pub(crate) fn new_with(limiter: impl CommonGlobalRateLimiter + 'static) -> Self {
        Self {
            limiter: Box::new(limiter),
            dry_run: false,
        }
    }

    /// Test helper: build a real limiter with the hierarchical resolver and its
    /// custom-key map seeded from `csv` (no dynamic source), backed by a mock
    /// Redis client. Exercises the static-CSV path with hierarchical resolution.
    #[cfg(test)]
    pub(crate) fn for_test_hierarchical_seeded(csv: Option<&str>) -> Self {
        let csv_owned = csv.map(|s| s.to_string());
        let grl_config = GlobalRateLimiterConfig {
            global_threshold: 300_000,
            redis_key_prefix: "test:grl".to_string(),
            custom_keys: Arc::new(ArcSwap::from_pointee(Self::format_custom_keys(
                csv_owned.as_ref(),
            ))),
            custom_key_resolver: Some(Self::hierarchical_resolver()),
            metrics_scope: "test".to_string(),
            ..Default::default()
        };
        let limiter = CommonGlobalRateLimiterImpl::new(
            grl_config,
            vec![Arc::new(common_redis::MockRedisClient::new())],
        )
        .expect("failed to build test limiter");
        Self {
            limiter: Box::new(limiter),
            dry_run: false,
        }
    }

    #[cfg(test)]
    pub(crate) fn new_with_dry_run(limiter: impl CommonGlobalRateLimiter + 'static) -> Self {
        Self {
            limiter: Box::new(limiter),
            dry_run: true,
        }
    }

    /// Test helper: build a `GlobalRateLimiter` that returns `Limited` for any
    /// key in `limited_keys` and `Allowed` otherwise. Custom limits always
    /// return `NotApplicable`. Shared across capture pipeline tests that need
    /// to simulate per-key global rate limiting.
    #[cfg(test)]
    pub(crate) fn mock_limiting(limited_keys: &[&str]) -> Self {
        use async_trait::async_trait;
        use std::collections::HashSet;

        struct MockLimitingLimiter {
            limited_keys: HashSet<String>,
        }

        #[async_trait]
        impl CommonGlobalRateLimiter for MockLimitingLimiter {
            async fn check_limit(
                &self,
                key: &str,
                _count: u64,
                _timestamp: Option<DateTime<Utc>>,
            ) -> EvalResult {
                if self.limited_keys.contains(key) {
                    EvalResult::Limited(GlobalRateLimitResponse {
                        key: key.to_string(),
                        current_count: 100.0,
                        threshold: 10,
                        window_interval: std::time::Duration::from_secs(60),
                        sync_interval: std::time::Duration::from_secs(15),
                        is_custom_limited: false,
                    })
                } else {
                    EvalResult::Allowed
                }
            }

            async fn check_custom_limit(
                &self,
                _key: &str,
                _count: u64,
                _timestamp: Option<DateTime<Utc>>,
            ) -> EvalResult {
                EvalResult::NotApplicable
            }

            fn is_custom_key(&self, _key: &str) -> bool {
                false
            }

            fn shutdown(&mut self) {}
        }

        let limited_keys: HashSet<String> = limited_keys.iter().map(|k| k.to_string()).collect();
        Self::new_with(MockLimitingLimiter { limited_keys })
    }

    /// Test helper: build a `GlobalRateLimiter` that tallies the counts charged
    /// per key and limits once a key's running total reaches `threshold`, with
    /// the charge for the current call included. Lets weight-charging call sites
    /// (the AI byte budget) be tested without Redis.
    ///
    /// Accounting is strict: a key is limited as soon as its total crosses the
    /// threshold, including on its very first charge. Tests then say what they
    /// mean — an event drops because of arithmetic a reader can check, not
    /// because of a seam-specific exemption.
    ///
    /// The real limiter also admits a key whose cache entry is missing, which
    /// recurs on every eviction and every new pod.
    /// [`Self::mock_budget_admitting_cold_keys`] models that, and one test pins
    /// it rather than every test inheriting it.
    ///
    /// Neither models the local cache's leaky-bucket decay, so a key never
    /// recovers here.
    #[cfg(test)]
    pub(crate) fn mock_budget(threshold: u64) -> Self {
        Self::mock_budget_with(threshold, false)
    }

    /// Test helper: [`Self::mock_budget`], plus the real limiter's fail-open on
    /// a cache miss — a key's first charge is admitted however far over the
    /// threshold it is.
    #[cfg(test)]
    pub(crate) fn mock_budget_admitting_cold_keys(threshold: u64) -> Self {
        Self::mock_budget_with(threshold, true)
    }

    #[cfg(test)]
    fn mock_budget_with(threshold: u64, admit_cold_keys: bool) -> Self {
        use async_trait::async_trait;
        use std::sync::Mutex;

        struct MockBudgetLimiter {
            threshold: u64,
            admit_cold_keys: bool,
            charged: Mutex<HashMap<String, u64>>,
        }

        #[async_trait]
        impl CommonGlobalRateLimiter for MockBudgetLimiter {
            async fn check_limit(
                &self,
                key: &str,
                count: u64,
                _timestamp: Option<DateTime<Utc>>,
            ) -> EvalResult {
                let mut charged = self.charged.lock().unwrap();
                let cold_key = !charged.contains_key(key);
                let total = charged.entry(key.to_string()).or_insert(0);
                *total += count;
                let exempt = cold_key && self.admit_cold_keys;
                if !exempt && *total >= self.threshold {
                    EvalResult::Limited(GlobalRateLimitResponse {
                        key: key.to_string(),
                        current_count: *total as f64,
                        threshold: self.threshold,
                        window_interval: std::time::Duration::from_secs(60),
                        sync_interval: std::time::Duration::from_secs(15),
                        is_custom_limited: false,
                    })
                } else {
                    EvalResult::Allowed
                }
            }

            async fn check_custom_limit(
                &self,
                _key: &str,
                _count: u64,
                _timestamp: Option<DateTime<Utc>>,
            ) -> EvalResult {
                EvalResult::NotApplicable
            }

            fn is_custom_key(&self, _key: &str) -> bool {
                false
            }

            fn shutdown(&mut self) {}
        }

        Self::new_with(MockBudgetLimiter {
            threshold,
            admit_cold_keys,
            charged: Mutex::new(HashMap::new()),
        })
    }

    // In capture deploys, the custom keys and rate limit thresholds should be
    // supplied as a CSV list of <string_key>=<u64_value> elements. malformed
    // elements will be logged and skipped during limiter initialization
    fn format_custom_keys(custom_keys_csv: Option<&String>) -> HashMap<String, u64> {
        let mut custom_keys = HashMap::new();

        if custom_keys_csv.is_none() || custom_keys_csv.unwrap().is_empty() {
            return custom_keys;
        }

        for elem in custom_keys_csv.unwrap().split(',') {
            let (key, limit) = match elem.split_once('=') {
                Some((k, l)) => (k, l),
                None => {
                    error!(
                        input = elem,
                        "Global rate limiter: failed to split custom key-value pair"
                    );
                    continue;
                }
            };
            let key = key.trim();
            match limit.trim().parse::<u64>() {
                Ok(value) => custom_keys.insert(key.to_string(), value),
                Err(e) => {
                    error!(
                        error = e.to_string(),
                        key, limit, "Global rate limiter: failed to parse custom key value"
                    );
                    continue;
                }
            };
        }

        custom_keys
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use rstest::rstest;
    use std::collections::HashSet;
    use std::sync::Mutex;
    use std::time::Duration;

    type CallLog = Arc<Mutex<Vec<&'static str>>>;

    struct MockLimiter {
        custom_keys: HashSet<String>,
        check_limit_result: EvalResult,
        check_custom_limit_result: EvalResult,
        calls: CallLog,
    }

    impl MockLimiter {
        fn new(
            custom_keys: HashSet<String>,
            check_limit_result: EvalResult,
            check_custom_limit_result: EvalResult,
        ) -> (Self, CallLog) {
            let calls: CallLog = Arc::new(Mutex::new(Vec::new()));
            let mock = Self {
                custom_keys,
                check_limit_result,
                check_custom_limit_result,
                calls: calls.clone(),
            };
            (mock, calls)
        }
    }

    #[async_trait]
    impl CommonGlobalRateLimiter for MockLimiter {
        async fn check_limit(
            &self,
            _key: &str,
            _count: u64,
            _timestamp: Option<DateTime<Utc>>,
        ) -> EvalResult {
            self.calls.lock().unwrap().push("check_limit");
            self.check_limit_result.clone()
        }

        async fn check_custom_limit(
            &self,
            _key: &str,
            _count: u64,
            _timestamp: Option<DateTime<Utc>>,
        ) -> EvalResult {
            self.calls.lock().unwrap().push("check_custom_limit");
            self.check_custom_limit_result.clone()
        }

        fn is_custom_key(&self, key: &str) -> bool {
            self.calls.lock().unwrap().push("is_custom_key");
            self.custom_keys.contains(key)
        }

        fn shutdown(&mut self) {}
    }

    fn make_limited_response(is_custom: bool) -> EvalResult {
        EvalResult::Limited(GlobalRateLimitResponse {
            key: "test".to_string(),
            current_count: 100.0,
            threshold: 10,
            window_interval: Duration::from_secs(60),
            sync_interval: Duration::from_secs(15),
            is_custom_limited: is_custom,
        })
    }

    #[tokio::test]
    async fn test_is_limited_routes_to_global_for_unknown_key() {
        let (mock, calls) = MockLimiter::new(
            HashSet::new(),
            make_limited_response(false),
            EvalResult::NotApplicable,
        );
        let wrapper = GlobalRateLimiter::new_with(mock);

        let result = wrapper.is_limited("unknown_key", 1).await;

        assert!(result.is_some());
        assert!(!result.unwrap().is_custom_limited);
        assert_eq!(
            *calls.lock().unwrap(),
            vec!["check_custom_limit", "check_limit"],
            "no custom override (NotApplicable) must fall back to the global check"
        );
    }

    #[tokio::test]
    async fn test_is_limited_routes_to_custom_for_registered_key() {
        let (mock, calls) = MockLimiter::new(
            HashSet::from(["registered".to_string()]),
            EvalResult::Allowed,
            make_limited_response(true),
        );
        let wrapper = GlobalRateLimiter::new_with(mock);

        let result = wrapper.is_limited("registered", 1).await;

        assert!(result.is_some());
        assert!(result.unwrap().is_custom_limited);
        assert_eq!(
            *calls.lock().unwrap(),
            vec!["check_custom_limit"],
            "a custom Limited result must not trigger a second global check"
        );
    }

    #[tokio::test]
    async fn test_is_limited_custom_key_allowed_does_not_fall_through_to_global() {
        let (mock, calls) = MockLimiter::new(
            HashSet::from(["custom".to_string()]),
            EvalResult::Allowed,
            EvalResult::Allowed,
        );
        let wrapper = GlobalRateLimiter::new_with(mock);

        let result = wrapper.is_limited("custom", 1).await;

        assert!(result.is_none());
        assert_eq!(
            *calls.lock().unwrap(),
            vec!["check_custom_limit"],
            "an Allowed custom key must NOT fall through to the global check"
        );
    }

    #[test]
    fn test_global_rate_limit_key_to_cache_key() {
        let cases: Vec<(GlobalRateLimitKey, &str, bool)> = vec![
            (GlobalRateLimitKey::Token("abc"), "abc", true),
            (GlobalRateLimitKey::Token(""), "", true),
            (
                GlobalRateLimitKey::TokenDistinctId("abc", "xyz"),
                "abc:xyz",
                false,
            ),
            (
                GlobalRateLimitKey::TokenDistinctId("abc", ""),
                "abc:",
                false,
            ),
        ];

        for (key, expected, expect_borrowed) in cases {
            let result = key.to_cache_key();
            assert_eq!(&*result, expected, "key={expected}");
            assert_eq!(
                matches!(result, Cow::Borrowed(_)),
                expect_borrowed,
                "key={expected}: expected borrowed={expect_borrowed}"
            );
        }
    }

    #[test]
    fn test_truncate_str() {
        let short = "hello";
        let exactly_128 = "a".repeat(128);
        let over_128 = "b".repeat(200);
        let truncated_128 = "b".repeat(128);
        // Multi-byte: é is 2 bytes in UTF-8
        let multibyte_at_boundary = format!("{}{}", "x".repeat(127), "é");

        let cases: Vec<(&str, usize, &str)> = vec![
            ("", 128, ""),
            (short, 128, short),
            (&exactly_128, 128, &exactly_128),
            (&over_128, 128, &truncated_128),
            (&multibyte_at_boundary, 128, &multibyte_at_boundary),
        ];

        for (input, max, expected) in &cases {
            let result = truncate_str(input, *max);
            assert_eq!(
                result,
                *expected,
                "truncate_str({:?}, {max}) = {:?}, expected {:?}",
                &input[..input.len().min(20)],
                result,
                expected
            );
        }
    }

    #[test]
    fn test_token_distinct_id_cache_key_truncates_long_distinct_id() {
        let token = "phc_abc";
        let long_id = "d".repeat(300);
        let key = GlobalRateLimitKey::TokenDistinctId(token, &long_id);
        let result = key.to_cache_key();

        let expected = format!("{token}:{}", &"d".repeat(MAX_DISTINCT_ID_CHARS));
        assert_eq!(&*result, &expected);
        assert_eq!(
            result.len(),
            token.len() + 1 + MAX_DISTINCT_ID_CHARS,
            "cache key should be token + ':' + 128 chars"
        );
    }

    #[test]
    fn test_token_distinct_id_cache_key_preserves_short_distinct_id() {
        let key = GlobalRateLimitKey::TokenDistinctId("tok", "short");
        assert_eq!(&*key.to_cache_key(), "tok:short");
    }

    #[test]
    fn test_token_distinct_id_truncation_utf8_safe() {
        // 127 ASCII chars + a 2-byte UTF-8 char = 128 chars, 129 bytes
        let prefix = "x".repeat(127);
        let distinct_id = format!("{}é", prefix);
        assert_eq!(distinct_id.chars().count(), 128);

        let key = GlobalRateLimitKey::TokenDistinctId("t", &distinct_id);
        let result = key.to_cache_key();
        // Should keep all 128 chars (not split the é)
        assert_eq!(&*result, &format!("t:{distinct_id}"));

        // Now 128 ASCII + é = 129 chars, should truncate to 128
        let prefix_129 = "x".repeat(128);
        let distinct_id_129 = format!("{}é", prefix_129);
        assert_eq!(distinct_id_129.chars().count(), 129);

        let key2 = GlobalRateLimitKey::TokenDistinctId("t", &distinct_id_129);
        let result2 = key2.to_cache_key();
        assert_eq!(&*result2, &format!("t:{prefix_129}"));
    }

    // --- dry-run mode tests ---

    #[tokio::test]
    async fn test_dry_run_global_limited_returns_none() {
        let (mock, calls) = MockLimiter::new(
            HashSet::new(),
            make_limited_response(false),
            EvalResult::NotApplicable,
        );
        let wrapper = GlobalRateLimiter::new_with_dry_run(mock);

        let result = wrapper.is_limited("some_key", 1).await;

        assert!(
            result.is_none(),
            "dry-run should suppress Limited → None, got {result:?}"
        );
        assert_eq!(
            *calls.lock().unwrap(),
            vec!["check_custom_limit", "check_limit"],
            "underlying limiter must still be called in dry-run mode"
        );
    }

    #[tokio::test]
    async fn test_dry_run_custom_limited_returns_none() {
        let (mock, calls) = MockLimiter::new(
            HashSet::from(["custom_key".to_string()]),
            EvalResult::Allowed,
            make_limited_response(true),
        );
        let wrapper = GlobalRateLimiter::new_with_dry_run(mock);

        let result = wrapper.is_limited("custom_key", 1).await;

        assert!(
            result.is_none(),
            "dry-run should suppress custom Limited → None, got {result:?}"
        );
        assert_eq!(
            *calls.lock().unwrap(),
            vec!["check_custom_limit"],
            "underlying limiter must still be called in dry-run mode"
        );
    }

    #[tokio::test]
    async fn test_dry_run_allowed_stays_none() {
        let (mock, _calls) = MockLimiter::new(
            HashSet::new(),
            EvalResult::Allowed,
            EvalResult::NotApplicable,
        );
        let wrapper = GlobalRateLimiter::new_with_dry_run(mock);

        let result = wrapper.is_limited("some_key", 1).await;

        assert!(
            result.is_none(),
            "allowed result should remain None in dry-run mode"
        );
    }

    #[tokio::test]
    async fn test_non_dry_run_limited_still_returns_some() {
        let (mock, _calls) = MockLimiter::new(
            HashSet::new(),
            make_limited_response(false),
            EvalResult::NotApplicable,
        );
        let wrapper = GlobalRateLimiter::new_with(mock);

        let result = wrapper.is_limited("some_key", 1).await;

        assert!(
            result.is_some(),
            "non-dry-run should return Some(response) when limited"
        );
    }

    // --- Hierarchical custom-key resolver ---
    //
    // The resolver is capture's key-resolution policy, injected into the common
    // limiter. A lookup key is `token` or `token:distinct_id`. Resolution: exact
    // match first, then the token prefix (everything before the first `:`). It is
    // colon-delimited, NOT a string prefix match.

    fn resolver_map(pairs: &[(&str, u64)]) -> HashMap<String, u64> {
        pairs.iter().map(|(k, v)| (k.to_string(), *v)).collect()
    }

    #[rstest]
    // Token-scope override: applies to the token and ALL of its token:distinct_id keys.
    #[case::token_scope_exact(&[("phc_tok", 10)], "phc_tok", Some(10))]
    #[case::token_scope_matches_any_distinct_id(&[("phc_tok", 10)], "phc_tok:alice", Some(10))]
    #[case::token_scope_matches_other_distinct_id(&[("phc_tok", 10)], "phc_tok:bob", Some(10))]
    #[case::token_scope_other_token_unmatched(&[("phc_tok", 10)], "other:alice", None)]
    #[case::token_scope_other_bare_token_unmatched(&[("phc_tok", 10)], "other", None)]
    // token:distinct_id-scope override: applies to that exact pair only.
    #[case::distinct_scope_exact(&[("phc_tok:alice", 5)], "phc_tok:alice", Some(5))]
    #[case::distinct_scope_other_distinct_unmatched(&[("phc_tok:alice", 5)], "phc_tok:bob", None)]
    #[case::distinct_scope_bare_token_unmatched(&[("phc_tok:alice", 5)], "phc_tok", None)]
    // Exact match wins over the token-prefix fallback.
    #[case::exact_wins_over_fallback(&[("phc_tok", 10), ("phc_tok:vip", 100)], "phc_tok:vip", Some(100))]
    #[case::fallback_when_no_exact(&[("phc_tok", 10), ("phc_tok:vip", 100)], "phc_tok:other", Some(10))]
    #[case::bare_token_with_both(&[("phc_tok", 10), ("phc_tok:vip", 100)], "phc_tok", Some(10))]
    // Safety: fallback is colon-delimited, never a raw string prefix.
    #[case::not_string_prefix_bare(&[("phc_tok", 10)], "phc_tokEXTRA", None)]
    #[case::not_string_prefix_with_distinct(&[("phc_tok", 10)], "phc_tokEXTRA:alice", None)]
    // Corner cases: empty distinct_id, extra colons, empty token, utf8.
    #[case::empty_distinct_id_falls_back(&[("phc_tok", 10)], "phc_tok:", Some(10))]
    #[case::only_first_colon_splits(&[("phc_tok", 10)], "phc_tok:a:b", Some(10))]
    #[case::empty_token_key(&[("", 3)], ":alice", Some(3))]
    #[case::utf8_distinct_id_falls_back(&[("phc_tok", 10)], "phc_tok:ünïcödé", Some(10))]
    #[case::empty_map_no_match(&[], "phc_tok:alice", None)]
    fn test_hierarchical_resolver(
        #[case] pairs: &[(&str, u64)],
        #[case] key: &str,
        #[case] expected: Option<u64>,
    ) {
        let resolver = GlobalRateLimiter::hierarchical_resolver();
        let map = resolver_map(pairs);
        assert_eq!(resolver(key, &map), expected, "key={key}");
    }

    #[tokio::test]
    async fn test_static_csv_seed_resolves_hierarchically() {
        // Gap fix vs master: a static-CSV token-level override (dynamic source
        // OFF) now applies to that token's token:distinct_id keys too, because
        // the hierarchical resolver is always set — not just on the dynamic path.
        let limiter = GlobalRateLimiter::for_test_hierarchical_seeded(Some("phc_seed=7"));

        assert!(limiter.is_custom_key("phc_seed"), "exact token override");
        assert!(
            limiter.is_custom_key("phc_seed:any_user"),
            "token override must apply to token:distinct_id (master only did exact match)"
        );
        assert!(
            !limiter.is_custom_key("other_tok:any_user"),
            "unrelated token must not match"
        );
    }
}
