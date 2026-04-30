use crate::api::{errors::FlagError, rate_parser::parse_rate_string};
use common_metrics::inc;
use common_types::TeamId;
use governor::{
    clock, middleware::NoOpMiddleware, state::keyed::DefaultKeyedStateStore, Quota, RateLimiter,
};
use std::collections::{HashMap, HashSet};
use std::fmt::Display;
use std::hash::Hash;
use std::num::NonZeroU32;
use std::sync::{Arc, RwLock};
use std::time::Instant;
use tracing::{info, warn};

/// Type alias for a keyed rate limiter.
///
/// The middleware is parameterized over the clock's `Instant` so the alias works
/// for any clock (real or fake) without falling back to the global default
/// `NoOpMiddleware<QuantaInstant>`.
type KeyedRateLimiterInner<K, C = clock::DefaultClock> =
    Arc<RateLimiter<K, DefaultKeyedStateStore<K>, C, NoOpMiddleware<<C as clock::Clock>::Instant>>>;

/// Type alias for the custom limiters map
type CustomLimitersMap<K, C = clock::DefaultClock> =
    Arc<RwLock<HashMap<K, KeyedRateLimiterInner<K, C>>>>;

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
pub(crate) struct KeyedRateLimiter<K, C = clock::DefaultClock>
where
    K: Hash + Eq + Clone + Display + Send + Sync + 'static,
    C: clock::Clock + Clone,
{
    /// Default rate limiter for keys without custom rates
    default_limiter: KeyedRateLimiterInner<K, C>,

    /// Custom rate limiters for specific keys
    /// Maps key → rate limiter
    /// Wrapped in RwLock for thread-safe access
    custom_limiters: CustomLimitersMap<K, C>,

    /// Keys that bypass rate limiting entirely.
    /// Wrapped in Arc<RwLock<>> so the request handler can update it from the database.
    allowlist: Arc<RwLock<HashSet<K>>>,

    /// Timestamp of the last allowlist refresh from the database.
    /// Used to implement a TTL cache — only re-query when stale.
    allowlist_last_refreshed: Arc<RwLock<Instant>>,

    /// Prometheus metric name for total requests
    request_counter: &'static str,

    /// Prometheus metric name for rate limited requests
    limited_counter: &'static str,

    /// Prometheus metric name for rate limit bypassed requests
    bypassed_counter: &'static str,
}

/// Type alias for flag definitions rate limiting (per-team)
pub(crate) type FlagDefinitionsRateLimiter = KeyedRateLimiter<TeamId>;

impl<K> KeyedRateLimiter<K>
where
    K: Hash + Eq + Clone + Display + Send + Sync + 'static,
{
    /// Create a new KeyedRateLimiter with configurable default and custom rates
    ///
    /// # Arguments
    /// * `default_rate_per_minute` - Default rate limit for keys without custom rates (requests per minute)
    /// * `custom_rates` - HashMap of key → rate string (e.g., "1200/minute")
    /// * `allowlist` - Set of keys that bypass rate limiting entirely
    /// * `request_counter` - Prometheus metric name for total requests
    /// * `limited_counter` - Prometheus metric name for rate limited requests
    /// * `bypassed_counter` - Prometheus metric name for rate limit bypassed requests
    ///
    /// # Returns
    /// A new limiter instance, or an error if any custom rate string is invalid
    pub fn new(
        default_rate_per_minute: u32,
        custom_rates: HashMap<K, String>,
        allowlist: HashSet<K>,
        request_counter: &'static str,
        limited_counter: &'static str,
        bypassed_counter: &'static str,
    ) -> Result<Self, String> {
        Self::new_with_clock(
            default_rate_per_minute,
            custom_rates,
            allowlist,
            request_counter,
            limited_counter,
            bypassed_counter,
            clock::DefaultClock::default(),
        )
    }
}

impl<K, C> KeyedRateLimiter<K, C>
where
    K: Hash + Eq + Clone + Display + Send + Sync + 'static,
    C: clock::Clock + Clone,
{
    /// Same as [`Self::new`], but with an injected `Clock` for deterministic testing.
    pub fn new_with_clock(
        default_rate_per_minute: u32,
        custom_rates: HashMap<K, String>,
        allowlist: HashSet<K>,
        request_counter: &'static str,
        limited_counter: &'static str,
        bypassed_counter: &'static str,
        clock: C,
    ) -> Result<Self, String> {
        // Create default limiter using configured rate
        let default_quota = Quota::per_minute(
            NonZeroU32::new(default_rate_per_minute)
                .ok_or_else(|| "default_rate_per_minute must be non-zero".to_string())?,
        );
        let default_limiter = Arc::new(RateLimiter::dashmap_with_clock(default_quota, &clock));

        // Parse and create custom rate limiters
        let mut custom_limiters_map = HashMap::new();

        for (key, rate_string) in custom_rates {
            match parse_rate_string(&rate_string) {
                Ok(quota) => {
                    let limiter = Arc::new(RateLimiter::dashmap_with_clock(quota, &clock));
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

        if !allowlist.is_empty() {
            info!(count = allowlist.len(), "Configured rate limit allowlist");
        }

        Ok(KeyedRateLimiter {
            default_limiter,
            custom_limiters,
            allowlist: Arc::new(RwLock::new(allowlist)),
            // Start stale so the first request triggers a DB refresh
            allowlist_last_refreshed: Arc::new(RwLock::new(
                Instant::now() - std::time::Duration::from_secs(3600),
            )),
            request_counter,
            limited_counter,
            bypassed_counter,
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
            // Allowlisted keys bypass rate limiting when they would be limited.
            // Matches Django's behavior: the bypassed counter only fires for
            // requests that exceed the limit but are allowed through.
            let allowlist = self.allowlist.read().unwrap();
            if allowlist.contains(&key) {
                inc(
                    self.bypassed_counter,
                    &[("key".to_string(), key.to_string())],
                    1,
                );
                return Ok(());
            }

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
    #[cfg(test)]
    pub fn custom_rate_count(&self) -> usize {
        self.custom_limiters.read().unwrap().len()
    }

    /// Get the number of keys in the rate limit allowlist
    #[cfg(test)]
    pub fn allowlist_count(&self) -> usize {
        self.allowlist.read().unwrap().len()
    }

    /// Replace the allowlist with a new set of keys and mark it as freshly refreshed.
    /// Called by the request handler when the cached DB value is stale.
    pub fn update_allowlist(&self, new_allowlist: HashSet<K>) {
        let (old_count, new_count) = {
            let mut allowlist = self.allowlist.write().unwrap();
            let old_count = allowlist.len();
            *allowlist = new_allowlist;
            (old_count, allowlist.len())
        }; // allowlist lock dropped here
        if old_count != new_count {
            info!(old_count, new_count, "Rate limit allowlist updated");
        }
        *self.allowlist_last_refreshed.write().unwrap() = Instant::now();
    }

    /// Returns true if the allowlist cache is stale and should be refreshed from the database.
    #[cfg(test)]
    pub fn is_allowlist_stale(&self, ttl_secs: u64) -> bool {
        self.allowlist_last_refreshed
            .read()
            .unwrap()
            .elapsed()
            .as_secs()
            >= ttl_secs
    }

    /// Atomically checks if the allowlist is stale and marks it as refreshed if so.
    /// Returns true if this caller should perform the refresh (won the race).
    /// Prevents stampeding: only the first caller at the TTL boundary proceeds.
    pub fn claim_allowlist_refresh(&self, ttl_secs: u64) -> bool {
        let mut last_refreshed = self.allowlist_last_refreshed.write().unwrap();
        if last_refreshed.elapsed().as_secs() >= ttl_secs {
            *last_refreshed = Instant::now();
            true
        } else {
            false
        }
    }

    /// Mark the allowlist refresh timestamp without changing the allowlist contents.
    /// Used when the DB query fails — avoids retrying on every request.
    #[cfg(test)]
    pub fn mark_allowlist_refreshed(&self) {
        *self.allowlist_last_refreshed.write().unwrap() = Instant::now();
    }

    /// Force the allowlist to be considered stale, triggering a DB refresh on the next request.
    #[cfg(test)]
    pub fn invalidate_allowlist(&self) {
        *self.allowlist_last_refreshed.write().unwrap() =
            Instant::now() - std::time::Duration::from_secs(3600);
    }

    /// Removes stale entries and reclaims memory across all limiters.
    ///
    /// This should be called periodically (e.g., every 60 seconds) by a background task.
    /// Keys that haven't been used within the rate limit window are removed from both
    /// the default limiter and all custom limiters.
    pub fn cleanup(&self) {
        // Clean up the default limiter
        self.default_limiter.retain_recent();
        self.default_limiter.shrink_to_fit();

        // Clean up all custom limiters
        let custom_limiters = self.custom_limiters.read().unwrap();
        for limiter in custom_limiters.values() {
            limiter.retain_recent();
            limiter.shrink_to_fit();
        }
    }

    /// Returns the total number of keys currently tracked across all limiters.
    ///
    /// Note: This may return an approximate value.
    /// Note: is_empty() intentionally omitted - use len() == 0 if needed.
    #[allow(clippy::len_without_is_empty)]
    pub fn len(&self) -> usize {
        let mut total = self.default_limiter.len();

        let custom_limiters = self.custom_limiters.read().unwrap();
        for limiter in custom_limiters.values() {
            total += limiter.len();
        }

        total
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::metrics::consts::{
        FLAG_DEFINITIONS_RATE_LIMITED_COUNTER, FLAG_DEFINITIONS_RATE_LIMIT_BYPASSED_COUNTER,
        FLAG_DEFINITIONS_REQUESTS_COUNTER,
    };
    use governor::clock::FakeRelativeClock;
    use std::collections::{HashMap, HashSet};
    use std::time::Duration;

    fn make_limiter_with_clock(
        default_rate: u32,
        custom_rates: HashMap<TeamId, String>,
        allowlist: HashSet<TeamId>,
        clock: FakeRelativeClock,
    ) -> KeyedRateLimiter<TeamId, FakeRelativeClock> {
        KeyedRateLimiter::new_with_clock(
            default_rate,
            custom_rates,
            allowlist,
            FLAG_DEFINITIONS_REQUESTS_COUNTER,
            FLAG_DEFINITIONS_RATE_LIMITED_COUNTER,
            FLAG_DEFINITIONS_RATE_LIMIT_BYPASSED_COUNTER,
            clock,
        )
        .unwrap()
    }

    fn make_limiter(
        default_rate: u32,
        custom_rates: HashMap<TeamId, String>,
        allowlist: HashSet<TeamId>,
    ) -> FlagDefinitionsRateLimiter {
        FlagDefinitionsRateLimiter::new(
            default_rate,
            custom_rates,
            allowlist,
            FLAG_DEFINITIONS_REQUESTS_COUNTER,
            FLAG_DEFINITIONS_RATE_LIMITED_COUNTER,
            FLAG_DEFINITIONS_RATE_LIMIT_BYPASSED_COUNTER,
        )
        .unwrap()
    }

    #[test]
    fn test_new_limiter_with_no_custom_rates() {
        let limiter = make_limiter(600, HashMap::new(), HashSet::new());
        assert_eq!(limiter.custom_rate_count(), 0);
    }

    #[test]
    fn test_new_limiter_with_valid_custom_rates() {
        let mut custom_rates = HashMap::new();
        custom_rates.insert(123, "1200/minute".to_string());
        custom_rates.insert(456, "2400/hour".to_string());

        let limiter = make_limiter(600, custom_rates, HashSet::new());
        assert_eq!(limiter.custom_rate_count(), 2);
    }

    #[test]
    fn test_new_limiter_with_invalid_rate_string() {
        let mut custom_rates = HashMap::new();
        custom_rates.insert(123, "invalid".to_string());
        custom_rates.insert(456, "1200/minute".to_string());

        // Should succeed but only configure the valid rate
        let limiter = make_limiter(600, custom_rates, HashSet::new());
        assert_eq!(limiter.custom_rate_count(), 1);
    }

    #[tokio::test]
    async fn test_default_rate_limit_allows_requests() {
        let limiter = make_limiter(600, HashMap::new(), HashSet::new());

        // First request should succeed
        assert!(limiter.check_rate_limit(999).is_ok());
    }

    #[tokio::test]
    async fn test_custom_rate_limit_applies() {
        let mut custom_rates = HashMap::new();
        // Very low limit for testing: 1 per second
        custom_rates.insert(123, "1/second".to_string());

        let limiter = make_limiter(600, custom_rates, HashSet::new());

        // First request should succeed
        assert!(limiter.check_rate_limit(123).is_ok());

        // Second request should be rate limited
        assert!(limiter.check_rate_limit(123).is_err());
    }

    #[tokio::test]
    async fn test_different_teams_independent_limits() {
        let mut custom_rates = HashMap::new();
        custom_rates.insert(123, "1/second".to_string());

        let limiter = make_limiter(600, custom_rates, HashSet::new());

        // Team 123 first request succeeds
        assert!(limiter.check_rate_limit(123).is_ok());

        // Team 123 second request fails (rate limited)
        assert!(limiter.check_rate_limit(123).is_err());

        // Team 999 (using default rate) still succeeds
        assert!(limiter.check_rate_limit(999).is_ok());
    }

    #[tokio::test]
    async fn test_rate_limit_resets_after_window() {
        let clock = FakeRelativeClock::default();
        let mut custom_rates = HashMap::new();
        // 1 per second - should reset after 1 second
        custom_rates.insert(123, "1/second".to_string());

        let limiter = make_limiter_with_clock(600, custom_rates, HashSet::new(), clock.clone());

        // First request succeeds
        assert!(limiter.check_rate_limit(123).is_ok());

        // Second request immediately fails
        assert!(limiter.check_rate_limit(123).is_err());

        // Wait for rate limit window to reset
        clock.advance(Duration::from_millis(1100));

        // Should succeed again after reset
        assert!(limiter.check_rate_limit(123).is_ok());
    }

    #[tokio::test]
    async fn test_concurrent_access() {
        let limiter = make_limiter(600, HashMap::new(), HashSet::new());
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

        let limiter = make_limiter(600, custom_rates, HashSet::new());

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

    #[test]
    fn test_len_returns_zero_for_new_limiter() {
        let limiter = make_limiter(600, HashMap::new(), HashSet::new());
        assert_eq!(limiter.len(), 0);
    }

    #[tokio::test]
    async fn test_allowlisted_team_bypasses_rate_limit() {
        let mut custom_rates = HashMap::new();
        custom_rates.insert(123, "1/second".to_string());

        let limiter = make_limiter(600, custom_rates, HashSet::from([123]));

        // Even with 1/second rate, allowlisted team is never rate limited
        for _ in 0..100 {
            assert!(limiter.check_rate_limit(123).is_ok());
        }
    }

    #[tokio::test]
    async fn test_non_allowlisted_team_still_rate_limited() {
        let mut custom_rates = HashMap::new();
        custom_rates.insert(456, "1/second".to_string());

        let limiter = make_limiter(600, custom_rates, HashSet::from([123]));

        // Non-allowlisted team 456 is still rate limited
        assert!(limiter.check_rate_limit(456).is_ok());
        assert!(limiter.check_rate_limit(456).is_err());
    }

    #[test]
    fn test_allowlist_count() {
        let limiter = make_limiter(600, HashMap::new(), HashSet::from([123, 456]));
        assert_eq!(limiter.allowlist_count(), 2);
    }

    #[test]
    fn test_empty_allowlist() {
        let limiter = make_limiter(600, HashMap::new(), HashSet::new());
        assert_eq!(limiter.allowlist_count(), 0);
    }

    #[test]
    fn test_allowlist_starts_stale() {
        let limiter = make_limiter(600, HashMap::new(), HashSet::new());
        assert!(limiter.is_allowlist_stale(60));
    }

    #[test]
    fn test_update_allowlist_marks_as_fresh() {
        let limiter = make_limiter(600, HashMap::new(), HashSet::new());
        limiter.update_allowlist(HashSet::from([123]));
        assert!(!limiter.is_allowlist_stale(60));
        assert_eq!(limiter.allowlist_count(), 1);
    }

    #[test]
    fn test_mark_allowlist_refreshed_without_changing_data() {
        let limiter = make_limiter(600, HashMap::new(), HashSet::new());
        assert!(limiter.is_allowlist_stale(60));
        limiter.mark_allowlist_refreshed();
        assert!(!limiter.is_allowlist_stale(60));
        assert_eq!(limiter.allowlist_count(), 0);
    }

    #[test]
    fn test_claim_allowlist_refresh_only_first_caller_wins() {
        let limiter = make_limiter(600, HashMap::new(), HashSet::new());
        // First claim should succeed (starts stale)
        assert!(limiter.claim_allowlist_refresh(60));
        // Second claim should fail (just marked as fresh)
        assert!(!limiter.claim_allowlist_refresh(60));
    }

    #[test]
    fn test_invalidate_allowlist_makes_stale() {
        let limiter = make_limiter(600, HashMap::new(), HashSet::new());
        limiter.mark_allowlist_refreshed();
        assert!(!limiter.is_allowlist_stale(60));
        limiter.invalidate_allowlist();
        assert!(limiter.is_allowlist_stale(60));
    }
}
