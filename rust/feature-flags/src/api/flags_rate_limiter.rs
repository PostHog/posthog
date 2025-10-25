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

/// Token bucket rate limiter for feature flag requests.
///
/// Uses the governor crate to implement a per-key (token) rate limiter.
/// This is a per-process limiter (not distributed across pods).
#[derive(Clone, Debug)]
pub struct FlagsRateLimiter {
    /// Whether rate limiting is enabled
    enabled: bool,
    /// The underlying token bucket rate limiter
    limiter: Arc<RateLimiter<String, DefaultKeyedStateStore<String>, clock::DefaultClock>>,
}

impl FlagsRateLimiter {
    /// Creates a new FlagsRateLimiter with the specified configuration.
    ///
    /// # Arguments
    ///
    /// * `enabled` - Whether rate limiting is enabled
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
    /// let limiter = FlagsRateLimiter::new(true, 10.0, 500).unwrap();
    /// assert!(limiter.allow_request("my_token"));
    /// ```
    pub fn new(enabled: bool, replenish_rate: f64, capacity: u32) -> anyhow::Result<Self> {
        let burst = NonZeroU32::new(capacity)
            .ok_or_else(|| anyhow::anyhow!("Bucket capacity must be greater than 0"))?;

        // Handle fractional replenish rates by using per-interval quotas
        // For rates < 1, we use larger time intervals (e.g., rate 0.1 = 1 per 10 seconds)
        let quota = if replenish_rate >= 1.0 {
            // For rates >= 1, use per-second quota
            let rate = NonZeroU32::new(replenish_rate.round() as u32)
                .ok_or_else(|| anyhow::anyhow!("Replenish rate must be greater than 0"))?;
            Quota::per_second(rate).allow_burst(burst)
        } else if replenish_rate > 0.0 {
            // For fractional rates, calculate the interval in milliseconds
            // e.g., rate 0.1 = 1 token per 10 seconds = 1 token per 10000ms
            let interval_ms = (1000.0 / replenish_rate).round() as u64;
            Quota::with_period(std::time::Duration::from_millis(interval_ms))
                .ok_or_else(|| anyhow::anyhow!("Invalid rate limit period"))?
                .allow_burst(burst)
        } else {
            return Err(anyhow::anyhow!("Replenish rate must be greater than 0"));
        };

        // Use DashMap-backed rate limiter for thread-safe keyed rate limiting
        let limiter = Arc::new(RateLimiter::dashmap(quota));

        Ok(Self { enabled, limiter })
    }

    /// Checks if a request should be allowed based on the rate limit.
    ///
    /// Matches Python's DecideRateThrottle.allow_request() behavior.
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
    /// - If the bucket_key is empty, always returns `true`
    /// - Otherwise, checks the token bucket for the given key
    /// - If rate limited, increments the `flags_rate_limit_exceeded_total` metric
    ///
    /// # Example
    ///
    /// ```
    /// use feature_flags::api::flags_rate_limiter::FlagsRateLimiter;
    ///
    /// let limiter = FlagsRateLimiter::new(true, 1.0, 1).unwrap();
    /// assert!(limiter.allow_request("token1"));  // First request allowed
    /// assert!(!limiter.allow_request("token1")); // Second request blocked
    /// assert!(limiter.allow_request("token2"));  // Different token allowed
    /// ```
    pub fn allow_request(&self, bucket_key: &str) -> bool {
        // If rate limiting is disabled, always allow
        if !self.enabled {
            return true;
        }

        // Empty bucket keys are always allowed
        if bucket_key.is_empty() {
            return true;
        }

        // Check if this request is allowed by the token bucket
        let allowed = self.limiter.check_key(&bucket_key.to_string()).is_ok();

        // Track rate limit violations in metrics
        if !allowed {
            counter!(
                "flags_rate_limit_exceeded_total",
                "token" => bucket_key.to_string()
            )
            .increment(1);
        }

        allowed
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread;
    use std::time::Duration;

    #[test]
    fn test_rate_limiter_disabled() {
        let limiter = FlagsRateLimiter::new(false, 1.0, 1).unwrap();

        // When disabled, all requests should be allowed
        for _ in 0..100 {
            assert!(limiter.allow_request("test_token"));
        }
    }

    #[test]
    fn test_rate_limiter_empty_key() {
        let limiter = FlagsRateLimiter::new(true, 1.0, 1).unwrap();

        // Empty keys should always be allowed
        for _ in 0..100 {
            assert!(limiter.allow_request(""));
        }
    }

    #[test]
    fn test_rate_limiter_basic_limiting() {
        // Create limiter with capacity of 3
        let limiter = FlagsRateLimiter::new(true, 0.1, 3).unwrap();

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
        let limiter = FlagsRateLimiter::new(true, 1.0, 1).unwrap();

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
        let limiter = FlagsRateLimiter::new(true, 0.1, 1).unwrap();

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
        let result = FlagsRateLimiter::new(true, 0.0, 500);
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Replenish rate must be greater than 0"));
    }

    #[test]
    fn test_rate_limiter_invalid_capacity() {
        let result = FlagsRateLimiter::new(true, 10.0, 0);
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Bucket capacity must be greater than 0"));
    }

    #[test]
    fn test_rate_limiter_fractional_replenish_rate() {
        // Test that fractional rates are properly rounded
        let limiter = FlagsRateLimiter::new(true, 0.5, 1).unwrap();

        // With 0.5 rounded to 1 token/sec, first request should be allowed
        assert!(limiter.allow_request("test_token"));
        // Second request should be blocked
        assert!(!limiter.allow_request("test_token"));
    }

    #[test]
    fn test_rate_limiter_large_burst() {
        // Test with larger burst capacity matching Python defaults
        let limiter = FlagsRateLimiter::new(true, 10.0, 500).unwrap();

        let token = "test_token";

        // Should allow up to 500 requests (burst capacity)
        for _ in 0..500 {
            assert!(limiter.allow_request(token));
        }

        // 501st request should be blocked
        assert!(!limiter.allow_request(token));
    }
}
