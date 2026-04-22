/// Rate limiter for the /flags endpoint using token bucket algorithm.
///
/// This module provides per-process, in-memory rate limiting for feature flag requests.
/// It uses the governor crate's token bucket implementation to limit request rates per token.
///
/// The rate limiter supports a two-tier warn-then-enforce model:
/// - **Warn tier**: When a key exceeds the warn capacity, the request proceeds
///   but the caller is informed via `RateLimitResult::Warned` so it can attach
///   a warning header to the response.
/// - **Enforce tier**: When a key exceeds the enforce capacity, the request is
///   blocked with `RateLimitResult::Blocked`.
///
/// The rate limiter is designed to match the behavior of Python's DecideRateThrottle class,
/// which uses the token-bucket library for the /decide endpoint.
use crate::api::rate_parser::parse_rate_string;
use governor::{clock, state::keyed::DefaultKeyedStateStore, Quota, RateLimiter};
use metrics::counter;
use std::collections::HashMap;
use std::num::NonZeroU32;
use std::sync::Arc;

/// Type alias for the governor keyed rate limiter.
type GovernorLimiter =
    Arc<RateLimiter<String, DefaultKeyedStateStore<String>, clock::DefaultClock>>;

/// Result of a rate limit check.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RateLimitResult {
    /// Request is within both warn and enforce thresholds.
    Allowed,
    /// Request exceeds the warn threshold but is below the enforce threshold.
    /// The caller should attach a warning header to the response.
    Warned,
    /// Request exceeds the enforce threshold and should be rejected with 429.
    Blocked,
}

/// Configuration for a keyed rate limiter's metrics and logging.
#[derive(Clone, Debug)]
struct RateLimiterConfig {
    /// Name of the metric to increment on rate limit violations
    metric_name: &'static str,
    /// Name of the label for the key (e.g., "token" or "ip")
    key_label: &'static str,
    /// Error message prefix for validation errors
    error_prefix: &'static str,
}

/// Creates a governor limiter from a replenish rate and burst capacity.
fn build_limiter(
    replenish_rate: f64,
    burst_capacity: u32,
    error_prefix: &str,
) -> anyhow::Result<GovernorLimiter> {
    let burst = NonZeroU32::new(burst_capacity)
        .ok_or_else(|| anyhow::anyhow!("{error_prefix} burst size must be greater than 0"))?;

    let quota = if replenish_rate >= 1.0 {
        let rate = NonZeroU32::new(replenish_rate.round() as u32).ok_or_else(|| {
            anyhow::anyhow!("{error_prefix} replenish rate must be greater than 0")
        })?;
        Quota::per_second(rate).allow_burst(burst)
    } else if replenish_rate > 0.0 {
        let interval_ms = (1000.0 / replenish_rate).round() as u64;
        Quota::with_period(std::time::Duration::from_millis(interval_ms))
            .ok_or_else(|| anyhow::anyhow!("Invalid {error_prefix} rate limit period"))?
            .allow_burst(burst)
    } else {
        return Err(anyhow::anyhow!(
            "{error_prefix} replenish rate must be greater than 0"
        ));
    };

    Ok(Arc::new(RateLimiter::dashmap(quota)))
}

/// Generic keyed rate limiter using token bucket algorithm with two-tier
/// warn-then-enforce support.
///
/// This is the core implementation shared by both FlagsRateLimiter and IpRateLimiter.
/// It provides per-key rate limiting with optional warn and enforce thresholds.
///
/// Governor's `check_key` is all-or-nothing — there's no way to query remaining
/// tokens without consuming one. Two limiters with the same replenish rate but
/// different capacities (warn < enforce) give clean semantics: the warn bucket
/// drains first.
#[derive(Clone, Debug)]
struct KeyedRateLimiter {
    /// Whether rate limiting is enabled
    enabled: bool,
    /// The enforce-tier limiter (always present when enabled)
    enforce_limiter: GovernorLimiter,
    /// The warn-tier limiter (present only when warn capacity is configured)
    warn_limiter: Option<GovernorLimiter>,
    /// When true, enforce rejections become warnings (never returns Blocked).
    /// Used for legacy log-only backwards compatibility.
    warn_only: bool,
    /// Configuration for metrics and logging
    config: RateLimiterConfig,
}

impl KeyedRateLimiter {
    /// Creates a new KeyedRateLimiter with the specified configuration.
    ///
    /// - `warn_capacity`: If `Some`, a second limiter is created at this (lower) capacity.
    ///   Requests that exceed it return `Warned`. If `None`, there is no warn tier.
    /// - `enforce_capacity`: Hard limit. Requests that exceed it return `Blocked`.
    /// - `warn_only`: When true, enforce rejections become warnings (legacy log-only compat).
    fn new(
        enabled: bool,
        replenish_rate: f64,
        warn_capacity: Option<u32>,
        enforce_capacity: u32,
        warn_only: bool,
        config: RateLimiterConfig,
    ) -> anyhow::Result<Self> {
        let enforce_limiter = build_limiter(replenish_rate, enforce_capacity, config.error_prefix)?;

        let warn_limiter = match warn_capacity {
            Some(0) => {
                tracing::warn!(
                    limiter = %config.error_prefix,
                    "Warn capacity is 0, which is equivalent to no warn tier"
                );
                None
            }
            Some(cap) => Some(build_limiter(replenish_rate, cap, config.error_prefix)?),
            None => None,
        };

        Ok(Self {
            enabled,
            enforce_limiter,
            warn_limiter,
            warn_only,
            config,
        })
    }

    /// The metric `mode` label: `"log_only"` when warn-only, `"enforcing"` otherwise.
    fn mode_label(&self) -> &'static str {
        if self.warn_only {
            "log_only"
        } else {
            "enforcing"
        }
    }

    /// Emits a "blocked" metric and returns `Warned` (if warn_only) or `Blocked`.
    ///
    /// In log_only mode, `action="blocked"` is still emitted to show what _would_
    /// happen if enforcement were enabled, but the request is not actually blocked.
    fn record_block(&self, key_string: String) -> RateLimitResult {
        counter!(
            self.config.metric_name,
            self.config.key_label => key_string,
            "mode" => self.mode_label(),
            "action" => "blocked"
        )
        .increment(1);
        if self.warn_only {
            RateLimitResult::Warned
        } else {
            RateLimitResult::Blocked
        }
    }

    /// Checks if a request should be allowed based on the rate limit.
    ///
    /// Always consumes tokens from both limiters to keep them in sync.
    /// Returns `Blocked` if the enforce limiter rejects, `Warned` if the
    /// warn limiter rejects but enforce allows, and `Allowed` otherwise.
    fn allow_request(&self, key: &str) -> RateLimitResult {
        if !self.enabled {
            return RateLimitResult::Allowed;
        }

        let key_string = key.to_string();

        // Always consume from both limiters so they stay in sync.
        let enforce_ok = self.enforce_limiter.check_key(&key_string).is_ok();
        let warn_ok = self
            .warn_limiter
            .as_ref()
            .is_none_or(|wl| wl.check_key(&key_string).is_ok());

        if !enforce_ok {
            return self.record_block(key_string);
        }

        if !warn_ok {
            counter!(
                self.config.metric_name,
                self.config.key_label => key_string.clone(),
                "mode" => self.mode_label(),
                "action" => "warned"
            )
            .increment(1);
            tracing::debug!(
                key = %key_string,
                limiter = %self.config.error_prefix,
                "Rate limit warning threshold exceeded"
            );
            return RateLimitResult::Warned;
        }

        RateLimitResult::Allowed
    }

    /// Removes stale entries from the rate limiter to prevent unbounded memory growth.
    fn retain_recent(&self) {
        self.enforce_limiter.retain_recent();
        if let Some(ref wl) = self.warn_limiter {
            wl.retain_recent();
        }
    }

    /// Shrinks the capacity of the rate limiter's state store if possible.
    fn shrink_to_fit(&self) {
        self.enforce_limiter.shrink_to_fit();
        if let Some(ref wl) = self.warn_limiter {
            wl.shrink_to_fit();
        }
    }

    /// Returns the number of keys currently tracked in the rate limiter.
    fn len(&self) -> usize {
        self.enforce_limiter.len()
    }
}

/// Maximum number of per-token rate limit overrides allowed.
/// Reuses the config-level constant to keep both checks in sync.
const MAX_CUSTOM_RATE_OVERRIDES: usize = crate::config::MAX_FLAGS_RATE_LIMIT_OVERRIDES;

/// Redacts a token for safe logging, showing only a prefix and suffix.
fn redact_token(token: &str) -> String {
    match (token.get(..4), token.get(token.len().saturating_sub(4)..)) {
        (Some(prefix), Some(suffix)) if token.len() > 8 => format!("{prefix}…{suffix}"),
        _ => "***".to_string(),
    }
}

/// Token bucket rate limiter for feature flag requests.
///
/// Uses the governor crate to implement a per-key (token) rate limiter.
/// This is a per-process limiter (not distributed across pods).
///
/// Supports optional per-token custom rate overrides via `custom_limiters`.
#[derive(Clone, Debug)]
pub struct FlagsRateLimiter {
    inner: KeyedRateLimiter,
    /// Per-token custom rate limiters (enforce-only, no warn tier).
    /// Wrapped in Arc for O(1) clone since the map is immutable after construction.
    custom_limiters: Arc<HashMap<String, GovernorLimiter>>,
}

impl FlagsRateLimiter {
    /// Creates a new FlagsRateLimiter with the specified configuration.
    ///
    /// # Arguments
    ///
    /// * `enabled` - Whether rate limiting is enabled
    /// * `replenish_rate` - Tokens added per second
    /// * `warn_capacity` - Warn threshold bucket size (None = no warn tier)
    /// * `enforce_capacity` - Hard limit bucket size
    /// * `warn_only` - When true, never returns Blocked (legacy log-only compat)
    /// * `custom_rates` - Per-token rate overrides (e.g., `{"phc_abc": "1200/minute"}`)
    ///
    /// # Example
    ///
    /// ```
    /// use feature_flags::api::flags_rate_limiter::{FlagsRateLimiter, RateLimitResult};
    /// use std::collections::HashMap;
    ///
    /// let limiter = FlagsRateLimiter::new(true, 10.0, None, 500, false, HashMap::new()).unwrap();
    /// assert_eq!(limiter.allow_request("my_token"), RateLimitResult::Allowed);
    /// ```
    pub fn new(
        enabled: bool,
        replenish_rate: f64,
        warn_capacity: Option<u32>,
        enforce_capacity: u32,
        warn_only: bool,
        custom_rates: HashMap<String, String>,
    ) -> anyhow::Result<Self> {
        if custom_rates.len() > MAX_CUSTOM_RATE_OVERRIDES {
            return Err(anyhow::anyhow!(
                "Too many custom rate overrides: {} (max {})",
                custom_rates.len(),
                MAX_CUSTOM_RATE_OVERRIDES
            ));
        }

        let config = RateLimiterConfig {
            metric_name: "flags_rate_limit_exceeded_total",
            key_label: "token",
            error_prefix: "Token rate limiter",
        };

        let inner = KeyedRateLimiter::new(
            enabled,
            replenish_rate,
            warn_capacity,
            enforce_capacity,
            warn_only,
            config,
        )?;

        // Parse and create custom per-token limiters (enforce-only).
        let mut custom_map = HashMap::new();
        for (token, rate_string) in &custom_rates {
            match parse_rate_string(rate_string) {
                Ok(quota) => {
                    let limiter = Arc::new(RateLimiter::dashmap(quota));
                    custom_map.insert(token.clone(), limiter);
                    tracing::info!(
                        token = %redact_token(token),
                        rate = %rate_string,
                        "Configured custom flags rate limit for token"
                    );
                }
                Err(e) => {
                    tracing::warn!(
                        token = %redact_token(token),
                        rate = %rate_string,
                        error = %e,
                        "Invalid rate string for token, ignoring custom rate"
                    );
                }
            }
        }

        if !custom_map.is_empty() {
            tracing::info!(
                count = custom_map.len(),
                "Loaded custom rate limit overrides"
            );
        }

        Ok(Self {
            inner,
            custom_limiters: Arc::new(custom_map),
        })
    }

    /// Checks if a request should be allowed based on the rate limit.
    ///
    /// Custom per-token limiters take precedence over the default limiter.
    /// Custom limiters honor `warn_only` mode — when active, rejections
    /// become warnings instead of blocks.
    pub fn allow_request(&self, bucket_key: &str) -> RateLimitResult {
        if !self.inner.enabled {
            return RateLimitResult::Allowed;
        }

        // Check for per-token custom limiter first
        if let Some(limiter) = self.custom_limiters.get(bucket_key) {
            let key_string = bucket_key.to_string();
            if limiter.check_key(&key_string).is_err() {
                return self.inner.record_block(key_string);
            }
            return RateLimitResult::Allowed;
        }

        self.inner.allow_request(bucket_key)
    }

    /// Removes stale entries and reclaims memory.
    pub fn cleanup(&self) {
        self.inner.retain_recent();
        self.inner.shrink_to_fit();

        for limiter in self.custom_limiters.values() {
            limiter.retain_recent();
            limiter.shrink_to_fit();
        }
    }

    /// Returns the approximate number of keys currently tracked.
    #[allow(clippy::len_without_is_empty)]
    pub fn len(&self) -> usize {
        let mut total = self.inner.len();
        for limiter in self.custom_limiters.values() {
            total += limiter.len();
        }
        total
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::thread;
    use std::time::Duration;

    fn default_limiter(
        enabled: bool,
        replenish_rate: f64,
        warn_capacity: Option<u32>,
        enforce_capacity: u32,
    ) -> FlagsRateLimiter {
        FlagsRateLimiter::new(
            enabled,
            replenish_rate,
            warn_capacity,
            enforce_capacity,
            false,
            HashMap::new(),
        )
        .unwrap()
    }

    #[test]
    fn test_rate_limiter_disabled() {
        let limiter = default_limiter(false, 1.0, None, 1);

        for _ in 0..100 {
            assert_eq!(
                limiter.allow_request("test_token"),
                RateLimitResult::Allowed
            );
        }
    }

    #[test]
    fn test_rate_limiter_basic_limiting() {
        let limiter = default_limiter(true, 0.1, None, 3);
        let token = "test_token";

        assert_eq!(limiter.allow_request(token), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request(token), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request(token), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request(token), RateLimitResult::Blocked);
    }

    #[test]
    fn test_rate_limiter_replenishes_over_time() {
        let limiter = default_limiter(true, 1.0, None, 1);
        let token = "test_token";

        assert_eq!(limiter.allow_request(token), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request(token), RateLimitResult::Blocked);

        thread::sleep(Duration::from_millis(1100));

        assert_eq!(limiter.allow_request(token), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request(token), RateLimitResult::Blocked);
    }

    #[test]
    fn test_rate_limiter_per_token_isolation() {
        let limiter = default_limiter(true, 0.1, None, 1);

        assert_eq!(limiter.allow_request("token1"), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request("token1"), RateLimitResult::Blocked);

        assert_eq!(limiter.allow_request("token2"), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request("token2"), RateLimitResult::Blocked);
    }

    #[test]
    fn test_rate_limiter_invalid_replenish_rate() {
        let result = FlagsRateLimiter::new(true, 0.0, None, 500, false, HashMap::new());
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("replenish rate must be greater than 0"));
    }

    #[test]
    fn test_rate_limiter_invalid_capacity() {
        let result = FlagsRateLimiter::new(true, 10.0, None, 0, false, HashMap::new());
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("burst size must be greater than 0"));
    }

    #[test]
    fn test_rate_limiter_fractional_replenish_rate() {
        let limiter = default_limiter(true, 0.5, None, 1);

        assert_eq!(
            limiter.allow_request("test_token"),
            RateLimitResult::Allowed
        );
        assert_eq!(
            limiter.allow_request("test_token"),
            RateLimitResult::Blocked
        );
    }

    #[test]
    fn test_rate_limiter_large_burst() {
        let limiter = default_limiter(true, 10.0, None, 500);
        let token = "test_token";

        for _ in 0..500 {
            assert_eq!(limiter.allow_request(token), RateLimitResult::Allowed);
        }
        assert_eq!(limiter.allow_request(token), RateLimitResult::Blocked);
    }

    #[test]
    fn test_warn_then_enforce() {
        // warn_capacity=2, enforce_capacity=5
        let limiter = default_limiter(true, 0.1, Some(2), 5);
        let token = "test_token";

        // First 2 requests: within warn capacity → Allowed
        assert_eq!(limiter.allow_request(token), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request(token), RateLimitResult::Allowed);

        // Requests 3-5: exceed warn but within enforce → Warned
        assert_eq!(limiter.allow_request(token), RateLimitResult::Warned);
        assert_eq!(limiter.allow_request(token), RateLimitResult::Warned);
        assert_eq!(limiter.allow_request(token), RateLimitResult::Warned);

        // Request 6: exceeds enforce → Blocked
        assert_eq!(limiter.allow_request(token), RateLimitResult::Blocked);
    }

    #[test]
    fn test_no_warn_limiter_only_allowed_or_blocked() {
        let limiter = default_limiter(true, 0.1, None, 2);
        let token = "test_token";

        assert_eq!(limiter.allow_request(token), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request(token), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request(token), RateLimitResult::Blocked);
    }

    #[test]
    fn test_custom_rate_overrides_default() {
        let mut custom_rates = HashMap::new();
        custom_rates.insert("custom_token".to_string(), "1/second".to_string());

        let limiter = FlagsRateLimiter::new(true, 0.1, Some(2), 5, false, custom_rates).unwrap();

        // Custom token uses its own limiter (capacity=1)
        assert_eq!(
            limiter.allow_request("custom_token"),
            RateLimitResult::Allowed
        );
        assert_eq!(
            limiter.allow_request("custom_token"),
            RateLimitResult::Blocked
        );

        // Default token uses the default limiter (warn=2, enforce=5)
        assert_eq!(
            limiter.allow_request("default_token"),
            RateLimitResult::Allowed
        );
        assert_eq!(
            limiter.allow_request("default_token"),
            RateLimitResult::Allowed
        );
        assert_eq!(
            limiter.allow_request("default_token"),
            RateLimitResult::Warned
        );
    }

    #[test]
    fn test_invalid_custom_rate_is_ignored() {
        let mut custom_rates = HashMap::new();
        custom_rates.insert("bad_token".to_string(), "invalid".to_string());
        custom_rates.insert("good_token".to_string(), "1/second".to_string());

        let limiter = FlagsRateLimiter::new(true, 0.1, None, 5, false, custom_rates).unwrap();

        // bad_token falls through to default limiter
        assert_eq!(limiter.allow_request("bad_token"), RateLimitResult::Allowed);

        // good_token uses custom limiter
        assert_eq!(
            limiter.allow_request("good_token"),
            RateLimitResult::Allowed
        );
        assert_eq!(
            limiter.allow_request("good_token"),
            RateLimitResult::Blocked
        );
    }

    #[test]
    fn test_warn_only_mode_never_blocks() {
        let limiter = FlagsRateLimiter::new(true, 0.1, Some(2), 5, true, HashMap::new()).unwrap();
        let token = "test_token";

        // First 2: within warn capacity → Allowed
        assert_eq!(limiter.allow_request(token), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request(token), RateLimitResult::Allowed);

        // 3-5: exceed warn → Warned
        assert_eq!(limiter.allow_request(token), RateLimitResult::Warned);
        assert_eq!(limiter.allow_request(token), RateLimitResult::Warned);
        assert_eq!(limiter.allow_request(token), RateLimitResult::Warned);

        // Request 6+: exceed enforce → still Warned (never Blocked in warn_only mode)
        assert_eq!(limiter.allow_request(token), RateLimitResult::Warned);
        assert_eq!(limiter.allow_request(token), RateLimitResult::Warned);
    }

    #[test]
    fn test_warn_only_mode_with_custom_limiter_never_blocks() {
        let mut custom_rates = HashMap::new();
        custom_rates.insert("custom_token".to_string(), "1/second".to_string());

        let limiter = FlagsRateLimiter::new(true, 0.1, Some(2), 5, true, custom_rates).unwrap();

        // Custom token: capacity=1, so second request exceeds it
        assert_eq!(
            limiter.allow_request("custom_token"),
            RateLimitResult::Allowed
        );
        // In warn_only mode, custom limiter rejection should produce Warned, not Blocked
        assert_eq!(
            limiter.allow_request("custom_token"),
            RateLimitResult::Warned
        );
        // Subsequent requests should also be Warned, never Blocked
        assert_eq!(
            limiter.allow_request("custom_token"),
            RateLimitResult::Warned
        );
    }

    #[test]
    fn test_too_many_custom_overrides_rejected() {
        let mut custom_rates = HashMap::new();
        for i in 0..=MAX_CUSTOM_RATE_OVERRIDES {
            custom_rates.insert(format!("token_{i}"), "10/second".to_string());
        }
        let result = FlagsRateLimiter::new(true, 10.0, None, 500, false, custom_rates);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("Too many"));
    }

    #[test]
    fn test_redact_token() {
        assert_eq!(redact_token("short"), "***");
        assert_eq!(redact_token("phc_abcdefghijklmnop"), "phc_…mnop");
        assert_eq!(redact_token("12345678"), "***");
        assert_eq!(redact_token("123456789"), "1234…6789");
    }
}

/// IP-based rate limiter for the /flags endpoint.
///
/// Similar to FlagsRateLimiter but rate limits by IP address instead of token.
/// This provides defense-in-depth against DDoS attacks with rotating fake tokens.
#[derive(Clone, Debug)]
pub struct IpRateLimiter {
    inner: KeyedRateLimiter,
}

impl IpRateLimiter {
    /// Creates a new IpRateLimiter with the specified configuration.
    ///
    /// # Arguments
    ///
    /// * `enabled` - Whether IP rate limiting is enabled
    /// * `replenish_rate` - Requests per second per IP
    /// * `warn_capacity` - Warn threshold (None = no warn tier)
    /// * `enforce_capacity` - Hard limit burst size per IP
    /// * `warn_only` - When true, never returns Blocked (legacy log-only compat)
    ///
    /// # Example
    ///
    /// ```
    /// use feature_flags::api::flags_rate_limiter::{IpRateLimiter, RateLimitResult};
    ///
    /// let limiter = IpRateLimiter::new(true, 20.0, None, 100, false).unwrap();
    /// assert_eq!(limiter.allow_request("192.168.1.1"), RateLimitResult::Allowed);
    /// ```
    pub fn new(
        enabled: bool,
        replenish_rate: f64,
        warn_capacity: Option<u32>,
        enforce_capacity: u32,
        warn_only: bool,
    ) -> anyhow::Result<Self> {
        let config = RateLimiterConfig {
            metric_name: "flags_ip_rate_limit_exceeded_total",
            key_label: "ip",
            error_prefix: "IP rate limiter",
        };

        let inner = KeyedRateLimiter::new(
            enabled,
            replenish_rate,
            warn_capacity,
            enforce_capacity,
            warn_only,
            config,
        )?;

        Ok(Self { inner })
    }

    /// Checks if a request from the given IP should be allowed.
    pub fn allow_request(&self, ip: &str) -> RateLimitResult {
        self.inner.allow_request(ip)
    }

    /// Removes stale entries and reclaims memory.
    pub fn cleanup(&self) {
        self.inner.retain_recent();
        self.inner.shrink_to_fit();
    }

    /// Returns the approximate number of keys currently tracked.
    #[allow(clippy::len_without_is_empty)]
    pub fn len(&self) -> usize {
        self.inner.len()
    }
}

#[cfg(test)]
mod ip_rate_limiter_tests {
    use super::*;
    use std::thread;
    use std::time::Duration;

    #[test]
    fn test_ip_rate_limiter_disabled() {
        let limiter = IpRateLimiter::new(false, 1.0, None, 1, false).unwrap();

        for _ in 0..100 {
            assert_eq!(
                limiter.allow_request("192.168.1.1"),
                RateLimitResult::Allowed
            );
        }
    }

    #[test]
    fn test_ip_rate_limiter_basic_limiting() {
        let limiter = IpRateLimiter::new(true, 0.1, None, 3, false).unwrap();
        let ip = "192.168.1.1";

        assert_eq!(limiter.allow_request(ip), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request(ip), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request(ip), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request(ip), RateLimitResult::Blocked);
    }

    #[test]
    fn test_ip_rate_limiter_per_ip_isolation() {
        let limiter = IpRateLimiter::new(true, 0.1, None, 1, false).unwrap();

        assert_eq!(
            limiter.allow_request("192.168.1.1"),
            RateLimitResult::Allowed
        );
        assert_eq!(
            limiter.allow_request("192.168.1.1"),
            RateLimitResult::Blocked
        );

        assert_eq!(
            limiter.allow_request("192.168.1.2"),
            RateLimitResult::Allowed
        );
        assert_eq!(
            limiter.allow_request("192.168.1.2"),
            RateLimitResult::Blocked
        );
    }

    #[test]
    fn test_ip_rate_limiter_replenishes() {
        let limiter = IpRateLimiter::new(true, 1.0, None, 1, false).unwrap();
        let ip = "192.168.1.1";

        assert_eq!(limiter.allow_request(ip), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request(ip), RateLimitResult::Blocked);

        thread::sleep(Duration::from_millis(1100));

        assert_eq!(limiter.allow_request(ip), RateLimitResult::Allowed);
    }

    #[test]
    fn test_ip_rate_limiter_warn_then_enforce() {
        let limiter = IpRateLimiter::new(true, 0.1, Some(2), 4, false).unwrap();
        let ip = "192.168.1.1";

        assert_eq!(limiter.allow_request(ip), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request(ip), RateLimitResult::Allowed);
        assert_eq!(limiter.allow_request(ip), RateLimitResult::Warned);
        assert_eq!(limiter.allow_request(ip), RateLimitResult::Warned);
        assert_eq!(limiter.allow_request(ip), RateLimitResult::Blocked);
    }

    #[test]
    fn test_ip_rate_limiter_invalid_burst_size() {
        let result = IpRateLimiter::new(true, 10.0, None, 0, false);
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("burst size must be greater than 0"));
    }

    #[test]
    fn test_ip_rate_limiter_invalid_replenish_rate() {
        let result = IpRateLimiter::new(true, 0.0, None, 100, false);
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("replenish rate must be greater than 0"));
    }
}
