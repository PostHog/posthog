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

type Key = (String, crate::registry::WarningType);

/// Keyed governor rate limiter over `(token, WarningType)`.
pub struct WarningThrottle {
    limiter: RateLimiter<Key, DefaultKeyedStateStore<Key>, clock::DefaultClock>,
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
        }
    }

    /// Returns `true` when this `(token, type)` still has budget; consuming a
    /// permit. `false` means the caller should drop the warning.
    pub fn check(&self, token: &str, warning: crate::registry::WarningType) -> bool {
        self.limiter
            .check_key(&(token.to_string(), warning))
            .is_ok()
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

        assert!(throttle.check("tok_a", WarningType::MissingEventName));
        assert!(
            !throttle.check("tok_a", WarningType::MissingEventName),
            "same (token, type) within the period must be throttled"
        );

        // Different type and different token are independent buckets.
        assert!(throttle.check("tok_a", WarningType::EmptyBatch));
        assert!(throttle.check("tok_b", WarningType::MissingEventName));
    }

    #[test]
    fn permits_refill_after_the_period() {
        let throttle = WarningThrottle::new(Duration::from_millis(50), NonZeroU32::MIN);
        assert!(throttle.check("tok", WarningType::InvalidBatch));
        assert!(!throttle.check("tok", WarningType::InvalidBatch));
        std::thread::sleep(Duration::from_millis(80));
        assert!(
            throttle.check("tok", WarningType::InvalidBatch),
            "permit must refill after the period elapses"
        );
    }

    #[test]
    fn sweep_evicts_refilled_keys() {
        let throttle = WarningThrottle::new(Duration::from_millis(10), NonZeroU32::MIN);
        assert!(throttle.check("tok", WarningType::MissingDistinctId));
        assert_eq!(throttle.tracked_keys(), 1);
        std::thread::sleep(Duration::from_millis(30));
        throttle.sweep();
        assert_eq!(
            throttle.tracked_keys(),
            0,
            "fully refilled keys are evicted"
        );
    }
}
