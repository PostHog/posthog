//! Cross-request throttle for warning emission — the outage guard.
//!
//! Mirrors the Node.js `IngestionWarningLimiter` semantics: by default at most
//! one warning per `(token, type)` key per hour (burst 1), enforced per pod.
//! Combined with per-batch dedup at the emit site, steady-state volume is
//! bounded at roughly `affected tokens × warning types` messages per hour per
//! pod regardless of traffic.

use std::num::NonZeroU32;
use std::time::Duration;

use governor::{clock, state::keyed::DefaultKeyedStateStore, Quota, RateLimiter};

/// Default refill period: one permit per (token, type) per hour.
pub const DEFAULT_THROTTLE_PERIOD: Duration = Duration::from_secs(3600);

/// Default bound on tracked `(token, type)` keys. Capture cannot verify
/// tokens, so a flood of spoofed tokens would otherwise grow the key map
/// without limit until the hourly sweep; legit steady-state cardinality
/// (tokens with drops in the last hour × types) sits orders of magnitude
/// below this, so hitting the cap means abuse, and the cheap fail-open
/// response is to stop emitting until the sweep evicts refilled keys.
pub const DEFAULT_MAX_TRACKED_KEYS: usize = 100_000;

type Key = (String, crate::registry::WarningType);

/// Outcome of a throttle check; names align with the emission metric's
/// `outcome` label values.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ThrottleDecision {
    /// Budget available — emit the warning.
    Emit,
    /// This `(token, type)` already emitted within the period — drop.
    Throttled,
    /// The key map is at capacity (token-flood guard) — drop without
    /// consulting or growing the limiter.
    CardinalityCapped,
}

/// Keyed governor rate limiter over `(token, WarningType)`.
pub struct WarningThrottle {
    limiter: RateLimiter<Key, DefaultKeyedStateStore<Key>, clock::DefaultClock>,
    max_tracked_keys: usize,
}

impl WarningThrottle {
    /// `period` is the refill interval per permit; `burst` is the bucket size.
    /// Production callers use [`WarningThrottle::default`]; the parameters
    /// exist so tests can exercise refill without waiting an hour.
    pub fn new(period: Duration, burst: NonZeroU32) -> Self {
        let quota = Quota::with_period(period)
            .expect("throttle period must be non-zero")
            .allow_burst(burst);
        Self {
            limiter: RateLimiter::dashmap(quota),
            max_tracked_keys: DEFAULT_MAX_TRACKED_KEYS,
        }
    }

    /// Override the tracked-key cap (tests use small values).
    pub fn with_max_tracked_keys(mut self, max_tracked_keys: usize) -> Self {
        self.max_tracked_keys = max_tracked_keys;
        self
    }

    /// Consume a permit for this `(token, type)` if the key map has room and
    /// the key has budget. Anything but [`ThrottleDecision::Emit`] means the
    /// caller should drop the warning.
    pub fn check(&self, token: &str, warning: crate::registry::WarningType) -> ThrottleDecision {
        // Governor's keyed limiter inserts on lookup, so the cap must gate
        // every check — including keys already tracked — to stay O(1).
        if self.limiter.len() >= self.max_tracked_keys {
            return ThrottleDecision::CardinalityCapped;
        }
        match self.limiter.check_key(&(token.to_string(), warning)) {
            Ok(()) => ThrottleDecision::Emit,
            Err(_) => ThrottleDecision::Throttled,
        }
    }

    /// Drop per-key state that has fully refilled, bounding memory. Call
    /// periodically from a maintenance task (see `OverflowLimiter::clean_state`
    /// for the established capture pattern).
    pub fn sweep(&self) {
        self.limiter.retain_recent();
        self.limiter.shrink_to_fit();
    }

    /// Number of currently tracked keys (for metrics/tests).
    pub fn tracked_keys(&self) -> usize {
        self.limiter.len()
    }
}

impl Default for WarningThrottle {
    fn default() -> Self {
        Self::new(DEFAULT_THROTTLE_PERIOD, NonZeroU32::MIN)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::registry::WarningType;

    #[test]
    fn burst_one_allows_first_and_blocks_repeat_per_key() {
        let throttle = WarningThrottle::default();

        assert_eq!(
            throttle.check("tok_a", WarningType::MissingEventName),
            ThrottleDecision::Emit
        );
        assert_eq!(
            throttle.check("tok_a", WarningType::MissingEventName),
            ThrottleDecision::Throttled,
            "same (token, type) within the period must be throttled"
        );

        // Different type and different token are independent buckets.
        assert_eq!(
            throttle.check("tok_a", WarningType::EmptyBatch),
            ThrottleDecision::Emit
        );
        assert_eq!(
            throttle.check("tok_b", WarningType::MissingEventName),
            ThrottleDecision::Emit
        );
    }

    #[test]
    fn permits_refill_after_the_period() {
        let throttle = WarningThrottle::new(Duration::from_millis(50), NonZeroU32::MIN);
        assert_eq!(
            throttle.check("tok", WarningType::InvalidBatch),
            ThrottleDecision::Emit
        );
        assert_eq!(
            throttle.check("tok", WarningType::InvalidBatch),
            ThrottleDecision::Throttled
        );
        std::thread::sleep(Duration::from_millis(80));
        assert_eq!(
            throttle.check("tok", WarningType::InvalidBatch),
            ThrottleDecision::Emit,
            "permit must refill after the period elapses"
        );
    }

    #[test]
    fn sweep_evicts_refilled_keys() {
        let throttle = WarningThrottle::new(Duration::from_millis(10), NonZeroU32::MIN);
        assert_eq!(
            throttle.check("tok", WarningType::MissingDistinctId),
            ThrottleDecision::Emit
        );
        assert_eq!(throttle.tracked_keys(), 1);
        std::thread::sleep(Duration::from_millis(30));
        throttle.sweep();
        assert_eq!(
            throttle.tracked_keys(),
            0,
            "fully refilled keys are evicted"
        );
    }

    #[test]
    fn cardinality_cap_stops_emission_until_sweep_frees_keys() {
        let throttle = WarningThrottle::new(Duration::from_millis(10), NonZeroU32::MIN)
            .with_max_tracked_keys(2);
        assert_eq!(
            throttle.check("tok_a", WarningType::MissingEventName),
            ThrottleDecision::Emit
        );
        assert_eq!(
            throttle.check("tok_b", WarningType::MissingEventName),
            ThrottleDecision::Emit
        );
        // Map is at capacity: new AND existing keys are capped (fail open).
        assert_eq!(
            throttle.check("tok_c", WarningType::MissingEventName),
            ThrottleDecision::CardinalityCapped
        );
        assert_eq!(
            throttle.check("tok_a", WarningType::EmptyBatch),
            ThrottleDecision::CardinalityCapped
        );

        std::thread::sleep(Duration::from_millis(30));
        throttle.sweep();
        assert_eq!(
            throttle.check("tok_c", WarningType::MissingEventName),
            ThrottleDecision::Emit,
            "sweep must free capacity for new keys"
        );
    }
}
