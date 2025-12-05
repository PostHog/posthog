/// Rate limiter for the /flags endpoint using token bucket algorithm.
///
/// This module provides per-process, in-memory rate limiting for feature flag requests.
/// It uses the governor crate's token bucket implementation to limit request rates per token.
///
/// The rate limiter is designed to match the behavior of Python's DecideRateThrottle class,
/// which uses the token-bucket library for the /decide endpoint.
use governor::{clock, state::keyed::DefaultKeyedStateStore, Quota, RateLimiter};
use metrics::counter;
use std::num::NonZeroU32;
use std::sync::Arc;

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

/// Generic keyed rate limiter using token bucket algorithm.
///
/// This is the core implementation shared by both FlagsRateLimiter and IpRateLimiter.
/// It provides per-key rate limiting with support for log-only mode.
#[derive(Clone, Debug)]
struct KeyedRateLimiter {
    /// Whether rate limiting is enabled
    enabled: bool,
    /// Whether to log rate limit violations without blocking requests
    log_only: bool,
    /// The underlying token bucket rate limiter
    limiter: Arc<RateLimiter<String, DefaultKeyedStateStore<String>, clock::DefaultClock>>,
    /// Configuration for metrics and logging
    config: RateLimiterConfig,
}

impl KeyedRateLimiter {
    /// Creates a new KeyedRateLimiter with the specified configuration.
    fn new(
        enabled: bool,
        log_only: bool,
        replenish_rate: f64,
        burst_size: u32,
        config: RateLimiterConfig,
    ) -> anyhow::Result<Self> {
        let burst = NonZeroU32::new(burst_size).ok_or_else(|| {
            anyhow::anyhow!("{} burst size must be greater than 0", config.error_prefix)
        })?;

        // Handle fractional replenish rates by using per-interval quotas
        let quota = if replenish_rate >= 1.0 {
            let rate = NonZeroU32::new(replenish_rate.round() as u32).ok_or_else(|| {
                anyhow::anyhow!(
                    "{} replenish rate must be greater than 0",
                    config.error_prefix
                )
            })?;
            Quota::per_second(rate).allow_burst(burst)
        } else if replenish_rate > 0.0 {
            let interval_ms = (1000.0 / replenish_rate).round() as u64;
            Quota::with_period(std::time::Duration::from_millis(interval_ms))
                .ok_or_else(|| {
                    anyhow::anyhow!("Invalid {} rate limit period", config.error_prefix)
                })?
                .allow_burst(burst)
        } else {
            return Err(anyhow::anyhow!(
                "{} replenish rate must be greater than 0",
                config.error_prefix
            ));
        };

        let limiter = Arc::new(RateLimiter::dashmap(quota));

        Ok(Self {
            enabled,
            log_only,
            limiter,
            config,
        })
    }

    /// Checks if a request should be allowed based on the rate limit.
    fn allow_request(&self, key: &str) -> bool {
        // If rate limiting is disabled, always allow
        if !self.enabled {
            return true;
        }

        // Check if this request is allowed by the token bucket
        // Note: We allocate a String here since governor's check_key requires owned String
        let key_string = key.to_string();
        let allowed = self.limiter.check_key(&key_string).is_ok();

        // Track rate limit violations in metrics
        if !allowed {
            let mode = if self.log_only {
                "log_only"
            } else {
                "enforced"
            };
            counter!(
                self.config.metric_name,
                self.config.key_label => key_string.clone(),
                "mode" => mode
            )
            .increment(1);

            // In log-only mode, log warning and allow the request to proceed
            if self.log_only {
                tracing::warn!(
                    key = %key_string,
                    limiter = %self.config.error_prefix,
                    "Rate limit exceeded (log-only mode: request allowed)"
                );
                return true;
            }
        }

        allowed
    }
}

/// Token bucket rate limiter for feature flag requests.
///
/// Uses the governor crate to implement a per-key (token) rate limiter.
/// This is a per-process limiter (not distributed across pods).
#[derive(Clone, Debug)]
pub struct FlagsRateLimiter {
    inner: KeyedRateLimiter,
}

impl FlagsRateLimiter {
    /// Creates a new FlagsRateLimiter with the specified configuration.
    ///
    /// # Arguments
    ///
    /// * `enabled` - Whether rate limiting is enabled
    /// * `log_only` - Whether to log violations without blocking (for safe rollout)
    /// * `replenish_rate` - Tokens added per second (matches Python's replenish_rate)
    /// * `capacity` - Maximum burst size (matches Python's bucket_capacity)
    ///
    /// # Returns
    ///
    /// Returns an error if the replenish rate or capacity are invalid (zero or negative).
    ///
    /// # Example
    ///
    /// ```
    /// use feature_flags::api::flags_rate_limiter::FlagsRateLimiter;
    ///
    /// let limiter = FlagsRateLimiter::new(true, false, 10.0, 500).unwrap();
    /// assert!(limiter.allow_request("my_token"));
    /// ```
    pub fn new(
        enabled: bool,
        log_only: bool,
        replenish_rate: f64,
        capacity: u32,
    ) -> anyhow::Result<Self> {
        let config = RateLimiterConfig {
            metric_name: "flags_rate_limit_exceeded_total",
            key_label: "token",
            error_prefix: "Token rate limiter",
        };

        let inner = KeyedRateLimiter::new(enabled, log_only, replenish_rate, capacity, config)?;

        Ok(Self { inner })
    }

    /// Checks if a request should be allowed based on the rate limit.
    ///
    /// Matches Python's DecideRateThrottle.allow_request() behavior with log-only mode support.
    ///
    /// # Arguments
    ///
    /// * `bucket_key` - The key to rate limit by (typically the token)
    ///
    /// # Returns
    ///
    /// Returns `true` if the request should be allowed, `false` if it should be rate limited.
    ///
    /// # Behavior
    ///
    /// - If rate limiting is disabled, always returns `true`
    /// - Otherwise, checks the token bucket for the given key
    /// - If rate limited and log-only mode:
    ///   - Increments the `flags_rate_limit_exceeded_total` metric
    ///   - Returns `true` (allows request to proceed)
    /// - If rate limited and NOT log-only mode:
    ///   - Increments the `flags_rate_limit_exceeded_total` metric
    ///   - Returns `false` (blocks request)
    ///
    /// # Example
    ///
    /// ```
    /// use feature_flags::api::flags_rate_limiter::FlagsRateLimiter;
    ///
    /// let limiter = FlagsRateLimiter::new(true, false, 1.0, 1).unwrap();
    /// assert!(limiter.allow_request("token1"));  // First request allowed
    /// assert!(!limiter.allow_request("token1")); // Second request blocked
    /// assert!(limiter.allow_request("token2"));  // Different token allowed
    /// ```
    pub fn allow_request(&self, bucket_key: &str) -> bool {
        self.inner.allow_request(bucket_key)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread;
    use std::time::Duration;

    #[test]
    fn test_rate_limiter_disabled() {
        let limiter = FlagsRateLimiter::new(false, false, 1.0, 1).unwrap();

        // When disabled, all requests should be allowed
        for _ in 0..100 {
            assert!(limiter.allow_request("test_token"));
        }
    }

    #[test]
    fn test_rate_limiter_basic_limiting() {
        // Create limiter with capacity of 3
        let limiter = FlagsRateLimiter::new(true, false, 0.1, 3).unwrap();

        let token = "test_token";

        // First 3 requests should be allowed (burst capacity)
        assert!(limiter.allow_request(token));
        assert!(limiter.allow_request(token));
        assert!(limiter.allow_request(token));

        // 4th request should be blocked
        assert!(!limiter.allow_request(token));
    }

    #[test]
    fn test_rate_limiter_replenishes_over_time() {
        // Create limiter with 1 token/sec replenish rate and capacity of 1
        let limiter = FlagsRateLimiter::new(true, false, 1.0, 1).unwrap();

        let token = "test_token";

        // First request should be allowed
        assert!(limiter.allow_request(token));

        // Second request should be blocked
        assert!(!limiter.allow_request(token));

        // Wait for token to replenish (add buffer for timing)
        thread::sleep(Duration::from_millis(1100));

        // Third request should be allowed after replenish
        assert!(limiter.allow_request(token));

        // Fourth request should be blocked again
        assert!(!limiter.allow_request(token));
    }

    #[test]
    fn test_rate_limiter_per_token_isolation() {
        // Create limiter with capacity of 1
        let limiter = FlagsRateLimiter::new(true, false, 0.1, 1).unwrap();

        // First token should be allowed
        assert!(limiter.allow_request("token1"));
        // First token second request should be blocked
        assert!(!limiter.allow_request("token1"));

        // Second token should be allowed (different bucket)
        assert!(limiter.allow_request("token2"));
        // Second token second request should be blocked
        assert!(!limiter.allow_request("token2"));
    }

    #[test]
    fn test_rate_limiter_invalid_replenish_rate() {
        let result = FlagsRateLimiter::new(true, false, 0.0, 500);
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("replenish rate must be greater than 0"));
    }

    #[test]
    fn test_rate_limiter_invalid_capacity() {
        let result = FlagsRateLimiter::new(true, false, 10.0, 0);
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("burst size must be greater than 0"));
    }

    #[test]
    fn test_rate_limiter_fractional_replenish_rate() {
        // Test that fractional rates are properly rounded
        let limiter = FlagsRateLimiter::new(true, false, 0.5, 1).unwrap();

        // With 0.5 rounded to 1 token/sec, first request should be allowed
        assert!(limiter.allow_request("test_token"));
        // Second request should be blocked
        assert!(!limiter.allow_request("test_token"));
    }

    #[test]
    fn test_rate_limiter_large_burst() {
        // Test with larger burst capacity matching Python defaults
        let limiter = FlagsRateLimiter::new(true, false, 10.0, 500).unwrap();

        let token = "test_token";

        // Should allow up to 500 requests (burst capacity)
        for _ in 0..500 {
            assert!(limiter.allow_request(token));
        }

        // 501st request should be blocked
        assert!(!limiter.allow_request(token));
    }

    #[test]
    fn test_rate_limiter_log_only_mode() {
        // Create limiter with log-only mode enabled
        let limiter = FlagsRateLimiter::new(true, true, 0.1, 2).unwrap();

        let token = "test_token";

        // First 2 requests should be allowed (burst capacity)
        assert!(limiter.allow_request(token));
        assert!(limiter.allow_request(token));

        // 3rd and 4th requests should also be allowed due to log-only mode
        // (normally these would be blocked)
        assert!(limiter.allow_request(token));
        assert!(limiter.allow_request(token));
    }

    #[test]
    fn test_rate_limiter_log_only_consumes_tokens() {
        // Verify that log-only mode still consumes tokens from the bucket
        let limiter = FlagsRateLimiter::new(true, true, 1.0, 1).unwrap();

        let token = "test_token";

        // First request consumes the token
        assert!(limiter.allow_request(token));

        // Second request would be blocked normally, but log-only allows it
        assert!(limiter.allow_request(token));

        // Wait for replenishment
        thread::sleep(Duration::from_millis(1100));

        // After replenishment, we have 1 token again
        assert!(limiter.allow_request(token));

        // This would be blocked normally, but log-only allows it
        assert!(limiter.allow_request(token));
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
    /// * `log_only` - Whether to log violations without blocking (for safe rollout)
    /// * `replenish_rate` - Requests per second per IP
    /// * `burst_size` - Maximum burst size per IP
    ///
    /// # Returns
    ///
    /// Returns an error if the replenish rate or burst size are invalid.
    ///
    /// # Example
    ///
    /// ```
    /// use feature_flags::api::flags_rate_limiter::IpRateLimiter;
    ///
    /// let limiter = IpRateLimiter::new(true, false, 20.0, 100).unwrap();
    /// assert!(limiter.allow_request("192.168.1.1"));
    /// ```
    pub fn new(
        enabled: bool,
        log_only: bool,
        replenish_rate: f64,
        burst_size: u32,
    ) -> anyhow::Result<Self> {
        let config = RateLimiterConfig {
            metric_name: "flags_ip_rate_limit_exceeded_total",
            key_label: "ip",
            error_prefix: "IP rate limiter",
        };

        let inner = KeyedRateLimiter::new(enabled, log_only, replenish_rate, burst_size, config)?;

        Ok(Self { inner })
    }

    /// Checks if a request from the given IP should be allowed.
    ///
    /// # Arguments
    ///
    /// * `ip` - The IP address to rate limit by
    ///
    /// # Returns
    ///
    /// Returns `true` if the request should be allowed, `false` if it should be rate limited.
    ///
    /// # Behavior
    ///
    /// - If IP rate limiting is disabled, always returns `true`
    /// - Otherwise, checks the token bucket for the given IP
    /// - If rate limited and log-only mode:
    ///   - Increments the `flags_ip_rate_limit_exceeded_total` metric
    ///   - Returns `true` (allows request to proceed)
    /// - If rate limited and NOT log-only mode:
    ///   - Increments the `flags_ip_rate_limit_exceeded_total` metric
    ///   - Returns `false` (blocks request)
    ///
    /// # Example
    ///
    /// ```
    /// use feature_flags::api::flags_rate_limiter::IpRateLimiter;
    ///
    /// let limiter = IpRateLimiter::new(true, false, 10.0, 5).unwrap();
    /// assert!(limiter.allow_request("192.168.1.1"));
    /// ```
    pub fn allow_request(&self, ip: &str) -> bool {
        self.inner.allow_request(ip)
    }
}

#[cfg(test)]
mod ip_rate_limiter_tests {
    use super::*;
    use std::thread;
    use std::time::Duration;

    #[test]
    fn test_ip_rate_limiter_disabled() {
        let limiter = IpRateLimiter::new(false, false, 1.0, 1).unwrap();

        // When disabled, all requests should be allowed
        for _ in 0..100 {
            assert!(limiter.allow_request("192.168.1.1"));
        }
    }

    #[test]
    fn test_ip_rate_limiter_basic_limiting() {
        let limiter = IpRateLimiter::new(true, false, 0.1, 3).unwrap();
        let ip = "192.168.1.1";

        // First 3 requests should be allowed (burst size)
        assert!(limiter.allow_request(ip));
        assert!(limiter.allow_request(ip));
        assert!(limiter.allow_request(ip));

        // 4th request should be blocked
        assert!(!limiter.allow_request(ip));
    }

    #[test]
    fn test_ip_rate_limiter_per_ip_isolation() {
        let limiter = IpRateLimiter::new(true, false, 0.1, 1).unwrap();

        // First IP should be allowed
        assert!(limiter.allow_request("192.168.1.1"));
        // First IP second request should be blocked
        assert!(!limiter.allow_request("192.168.1.1"));

        // Second IP should be allowed (different bucket)
        assert!(limiter.allow_request("192.168.1.2"));
        // Second IP second request should be blocked
        assert!(!limiter.allow_request("192.168.1.2"));
    }

    #[test]
    fn test_ip_rate_limiter_replenishes() {
        let limiter = IpRateLimiter::new(true, false, 1.0, 1).unwrap();
        let ip = "192.168.1.1";

        // First request allowed
        assert!(limiter.allow_request(ip));

        // Second request blocked
        assert!(!limiter.allow_request(ip));

        // Wait for replenishment
        thread::sleep(Duration::from_millis(1100));

        // Third request allowed after replenishment
        assert!(limiter.allow_request(ip));
    }

    #[test]
    fn test_ip_rate_limiter_log_only_mode() {
        let limiter = IpRateLimiter::new(true, true, 0.1, 2).unwrap();
        let ip = "192.168.1.1";

        // First 2 requests allowed (burst size)
        assert!(limiter.allow_request(ip));
        assert!(limiter.allow_request(ip));

        // 3rd and 4th requests also allowed due to log-only mode
        assert!(limiter.allow_request(ip));
        assert!(limiter.allow_request(ip));
    }

    #[test]
    fn test_ip_rate_limiter_invalid_burst_size() {
        let result = IpRateLimiter::new(true, false, 10.0, 0);
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("burst size must be greater than 0"));
    }

    #[test]
    fn test_ip_rate_limiter_invalid_replenish_rate() {
        let result = IpRateLimiter::new(true, false, 0.0, 100);
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("replenish rate must be greater than 0"));
    }
}
