use crate::api::{errors::FlagError, rate_parser::parse_rate_string};
use common_metrics::inc;
use common_types::TeamId;
use governor::{clock, state::keyed::DefaultKeyedStateStore, Quota, RateLimiter};
use std::collections::HashMap;
use std::fmt::Display;
use std::hash::Hash;
use std::num::NonZeroU32;
use std::sync::{Arc, RwLock};
use tracing::{info, warn};

/// Type alias for a keyed rate limiter
type KeyedRateLimiterInner<K> = Arc<RateLimiter<K, DefaultKeyedStateStore<K>, clock::DefaultClock>>;

/// Type alias for the custom limiters map
type CustomLimitersMap<K> = Arc<RwLock<HashMap<K, KeyedRateLimiterInner<K>>>>;

/// Generic keyed rate limiter with default and per-key custom rate overrides
///
/// This limiter supports:
/// - A configurable default rate limit for all keys
/// - Custom per-key rate limits
/// - Thread-safe concurrent access via Arc and RwLock
/// - Configurable Prometheus metrics
///
/// # Type Parameters
/// * `K` - The key type (e.g., TeamId, UserId, etc.)
///
/// # Algorithm
/// Uses the GCRA (Generic Cell Rate Algorithm) via the `governor` crate,
/// which is functionally equivalent to a leaky bucket but more efficient.
#[derive(Clone)]
pub struct KeyedRateLimiter<K>
where
    K: Hash + Eq + Clone + Display + Send + Sync + 'static,
{
    /// Default rate limiter for keys without custom rates
    default_limiter: KeyedRateLimiterInner<K>,

    /// Custom rate limiters for specific keys
    /// Maps key → rate limiter
    /// Wrapped in RwLock for thread-safe access
    custom_limiters: CustomLimitersMap<K>,

    /// Prometheus metric name for total requests
    request_counter: &'static str,

    /// Prometheus metric name for rate limited requests
    limited_counter: &'static str,
}

/// Type alias for flag definitions rate limiting (per-team)
pub type FlagDefinitionsRateLimiter = KeyedRateLimiter<TeamId>;

impl<K> KeyedRateLimiter<K>
where
    K: Hash + Eq + Clone + Display + Send + Sync + 'static,
{
    /// Create a new KeyedRateLimiter with configurable default and custom rates
    ///
    /// # Arguments
    /// * `default_rate_per_minute` - Default rate limit for keys without custom rates (requests per minute)
    /// * `custom_rates` - HashMap of key → rate string (e.g., "1200/minute")
    /// * `request_counter` - Prometheus metric name for total requests
    /// * `limited_counter` - Prometheus metric name for rate limited requests
    ///
    /// # Returns
    /// A new limiter instance, or an error if any custom rate string is invalid
    pub fn new(
        default_rate_per_minute: u32,
        custom_rates: HashMap<K, String>,
        request_counter: &'static str,
        limited_counter: &'static str,
    ) -> Result<Self, String> {
        // Create default limiter using configured rate
        let default_quota = Quota::per_minute(
            NonZeroU32::new(default_rate_per_minute)
                .ok_or_else(|| "default_rate_per_minute must be non-zero".to_string())?,
        );
        let default_limiter = Arc::new(RateLimiter::dashmap(default_quota));

        // Parse and create custom rate limiters
        let mut custom_limiters_map = HashMap::new();

        for (key, rate_string) in custom_rates {
            match parse_rate_string(&rate_string) {
                Ok(quota) => {
                    let limiter = Arc::new(RateLimiter::dashmap(quota));
                    custom_limiters_map.insert(key.clone(), limiter);
                    info!(
                        key = %key,
                        rate = %rate_string,
                        "Configured custom rate limit for key"
                    );
                }
                Err(e) => {
                    warn!(
                        key = %key,
                        rate = %rate_string,
                        error = %e,
                        "Invalid rate string for key, ignoring custom rate"
                    );
                    // Continue with default rate for this key instead of failing
                }
            }
        }

        let custom_limiters = Arc::new(RwLock::new(custom_limiters_map));

        Ok(KeyedRateLimiter {
            default_limiter,
            custom_limiters,
            request_counter,
            limited_counter,
        })
    }

    /// Check if a request from the given key should be rate limited
    ///
    /// # Arguments
    /// * `key` - The key (e.g., team ID, user ID) making the request
    ///
    /// # Returns
    /// Ok(()) if request is allowed, Err(FlagError::ClientFacing(ClientFacingError::RateLimited)) if rate limited
    pub fn check_rate_limit(&self, key: K) -> Result<(), FlagError> {
        // Check if key has a custom rate limiter
        let custom_limiters = self.custom_limiters.read().unwrap();
        let is_rate_limited = if let Some(custom_limiter) = custom_limiters.get(&key) {
            // Use custom rate limiter
            custom_limiter.check_key(&key).is_err()
        } else {
            // Use default rate limiter
            self.default_limiter.check_key(&key).is_err()
        };

        // Track all requests
        inc(
            self.request_counter,
            &[("key".to_string(), key.to_string())],
            1,
        );

        if is_rate_limited {
            // Track rate-limited requests
            inc(
                self.limited_counter,
                &[("key".to_string(), key.to_string())],
                1,
            );

            // Log rate limit event with key context
            warn!(key = %key, "Request rate limited");

            return Err(FlagError::ClientFacing(
                crate::api::errors::ClientFacingError::RateLimited,
            ));
        }

        Ok(())
    }

    /// Get the number of keys with custom rate limits configured
    pub fn custom_rate_count(&self) -> usize {
        self.custom_limiters.read().unwrap().len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::metrics::consts::{
        FLAG_DEFINITIONS_RATE_LIMITED_COUNTER, FLAG_DEFINITIONS_REQUESTS_COUNTER,
    };
    use std::collections::HashMap;
    use tokio::time::{sleep, Duration};

    #[test]
    fn test_new_limiter_with_no_custom_rates() {
        let limiter = FlagDefinitionsRateLimiter::new(
            600,
            HashMap::new(),
            FLAG_DEFINITIONS_REQUESTS_COUNTER,
            FLAG_DEFINITIONS_RATE_LIMITED_COUNTER,
        )
        .unwrap();
        assert_eq!(limiter.custom_rate_count(), 0);
    }

    #[test]
    fn test_new_limiter_with_valid_custom_rates() {
        let mut custom_rates = HashMap::new();
        custom_rates.insert(123, "1200/minute".to_string());
        custom_rates.insert(456, "2400/hour".to_string());

        let limiter = FlagDefinitionsRateLimiter::new(
            600,
            custom_rates,
            FLAG_DEFINITIONS_REQUESTS_COUNTER,
            FLAG_DEFINITIONS_RATE_LIMITED_COUNTER,
        )
        .unwrap();
        assert_eq!(limiter.custom_rate_count(), 2);
    }

    #[test]
    fn test_new_limiter_with_invalid_rate_string() {
        let mut custom_rates = HashMap::new();
        custom_rates.insert(123, "invalid".to_string());
        custom_rates.insert(456, "1200/minute".to_string());

        // Should succeed but only configure the valid rate
        let limiter = FlagDefinitionsRateLimiter::new(
            600,
            custom_rates,
            FLAG_DEFINITIONS_REQUESTS_COUNTER,
            FLAG_DEFINITIONS_RATE_LIMITED_COUNTER,
        )
        .unwrap();
        assert_eq!(limiter.custom_rate_count(), 1);
    }

    #[tokio::test]
    async fn test_default_rate_limit_allows_requests() {
        let limiter = FlagDefinitionsRateLimiter::new(
            600,
            HashMap::new(),
            FLAG_DEFINITIONS_REQUESTS_COUNTER,
            FLAG_DEFINITIONS_RATE_LIMITED_COUNTER,
        )
        .unwrap();

        // First request should succeed
        assert!(limiter.check_rate_limit(999).is_ok());
    }

    #[tokio::test]
    async fn test_custom_rate_limit_applies() {
        let mut custom_rates = HashMap::new();
        // Very low limit for testing: 1 per second
        custom_rates.insert(123, "1/second".to_string());

        let limiter = FlagDefinitionsRateLimiter::new(
            600,
            custom_rates,
            FLAG_DEFINITIONS_REQUESTS_COUNTER,
            FLAG_DEFINITIONS_RATE_LIMITED_COUNTER,
        )
        .unwrap();

        // First request should succeed
        assert!(limiter.check_rate_limit(123).is_ok());

        // Second request should be rate limited
        assert!(limiter.check_rate_limit(123).is_err());
    }

    #[tokio::test]
    async fn test_different_teams_independent_limits() {
        let mut custom_rates = HashMap::new();
        custom_rates.insert(123, "1/second".to_string());

        let limiter = FlagDefinitionsRateLimiter::new(
            600,
            custom_rates,
            FLAG_DEFINITIONS_REQUESTS_COUNTER,
            FLAG_DEFINITIONS_RATE_LIMITED_COUNTER,
        )
        .unwrap();

        // Team 123 first request succeeds
        assert!(limiter.check_rate_limit(123).is_ok());

        // Team 123 second request fails (rate limited)
        assert!(limiter.check_rate_limit(123).is_err());

        // Team 999 (using default rate) still succeeds
        assert!(limiter.check_rate_limit(999).is_ok());
    }

    #[tokio::test]
    async fn test_rate_limit_resets_after_window() {
        let mut custom_rates = HashMap::new();
        // 1 per second - should reset after 1 second
        custom_rates.insert(123, "1/second".to_string());

        let limiter = FlagDefinitionsRateLimiter::new(
            600,
            custom_rates,
            FLAG_DEFINITIONS_REQUESTS_COUNTER,
            FLAG_DEFINITIONS_RATE_LIMITED_COUNTER,
        )
        .unwrap();

        // First request succeeds
        assert!(limiter.check_rate_limit(123).is_ok());

        // Second request immediately fails
        assert!(limiter.check_rate_limit(123).is_err());

        // Wait for rate limit window to reset
        sleep(Duration::from_millis(1100)).await;

        // Should succeed again after reset
        assert!(limiter.check_rate_limit(123).is_ok());
    }

    #[tokio::test]
    async fn test_concurrent_access() {
        let limiter = FlagDefinitionsRateLimiter::new(
            600,
            HashMap::new(),
            FLAG_DEFINITIONS_REQUESTS_COUNTER,
            FLAG_DEFINITIONS_RATE_LIMITED_COUNTER,
        )
        .unwrap();
        let limiter_clone = limiter.clone();

        // Spawn multiple tasks checking rate limits concurrently
        let handle1 = tokio::spawn(async move {
            for _ in 0..10 {
                drop(limiter_clone.check_rate_limit(123));
            }
        });

        let limiter_clone2 = limiter.clone();
        let handle2 = tokio::spawn(async move {
            for _ in 0..10 {
                drop(limiter_clone2.check_rate_limit(456));
            }
        });

        // Should complete without panicking
        handle1.await.unwrap();
        handle2.await.unwrap();
    }

    #[tokio::test]
    async fn test_check_rate_limit_returns_correct_error() {
        let mut custom_rates = HashMap::new();
        custom_rates.insert(123, "1/second".to_string());

        let limiter = FlagDefinitionsRateLimiter::new(
            600,
            custom_rates,
            FLAG_DEFINITIONS_REQUESTS_COUNTER,
            FLAG_DEFINITIONS_RATE_LIMITED_COUNTER,
        )
        .unwrap();

        // Use up the rate limit
        drop(limiter.check_rate_limit(123));

        // Next request should return RateLimited error
        let result = limiter.check_rate_limit(123);
        assert!(result.is_err());

        match result {
            Err(FlagError::ClientFacing(crate::api::errors::ClientFacingError::RateLimited)) => {
                // Expected error type
            }
            _ => panic!("Expected RateLimited error"),
        }
    }
}
