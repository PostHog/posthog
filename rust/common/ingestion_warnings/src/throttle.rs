//! Cross-request throttle for warning emission — the outage guard.
//!
//! Mirrors the Node.js `IngestionWarningLimiter` semantics: by default at most
//! one warning per `(token, type)` key per hour (burst 1), enforced per pod.
//! Combined with per-batch dedup at the emit site, steady-state volume is
//! bounded at roughly `affected tokens × warning types` messages per hour per
//! pod regardless of traffic.
//!
//! An optional per-type budget ([`WarningThrottle::with_type_budget`]) also
//! caps how many warnings of one type a pod sends, whatever the number of
//! tokens.

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
type TypeBudget = RateLimiter<
    crate::registry::WarningType,
    DefaultKeyedStateStore<crate::registry::WarningType>,
    clock::DefaultClock,
>;

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
    /// This warning type used up its per-pod budget, so drop.
    TypeBudgetExhausted,
}

impl ThrottleDecision {
    /// The metric `outcome` label for a dropped warning, or `None` for
    /// [`ThrottleDecision::Emit`].
    pub fn drop_outcome(self) -> Option<&'static str> {
        match self {
            Self::Emit => None,
            Self::Throttled => Some("throttled"),
            Self::CardinalityCapped => Some("cardinality_capped"),
            Self::TypeBudgetExhausted => Some("type_budget_exhausted"),
        }
    }
}

/// Keyed governor rate limiter over `(token, WarningType)`.
pub struct WarningThrottle {
    limiter: RateLimiter<Key, DefaultKeyedStateStore<Key>, clock::DefaultClock>,
    max_tracked_keys: usize,
    type_budget: Option<TypeBudget>,
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
            type_budget: None,
        }
    }

    /// Override the tracked-key cap (tests use small values).
    pub fn with_max_tracked_keys(mut self, max_tracked_keys: usize) -> Self {
        self.max_tracked_keys = max_tracked_keys;
        self
    }

    /// Cap the warnings of each type that pass the per-`(token, type)` check
    /// at `burst`, refilling one permit per `period`. This bounds what one
    /// failure that hits many tokens at once can send. Off by default.
    pub fn with_type_budget(mut self, period: Duration, burst: NonZeroU32) -> Self {
        let quota = Quota::with_period(period)
            .expect("type budget period must be non-zero")
            .allow_burst(burst);
        self.type_budget = Some(RateLimiter::dashmap(quota));
        self
    }

    /// Consume a permit for this `(token, type)` if the key map has room and
    /// the key has budget, then a permit of the type budget if one is set.
    /// Anything but [`ThrottleDecision::Emit`] means the caller should drop the
    /// warning.
    pub fn check(&self, token: &str, warning: crate::registry::WarningType) -> ThrottleDecision {
        // Governor's keyed limiter inserts on lookup, so the cap must gate
        // every check — including keys already tracked — to stay O(1).
        if self.limiter.len() >= self.max_tracked_keys {
            return ThrottleDecision::CardinalityCapped;
        }
        if self
            .limiter
            .check_key(&(token.to_string(), warning))
            .is_err()
        {
            return ThrottleDecision::Throttled;
        }
        // The type budget comes second, so a token that repeats a warning
        // spends at most one budget permit per period and cannot use up the
        // budget of every other token.
        match &self.type_budget {
            Some(budget) if budget.check_key(&warning).is_err() => {
                ThrottleDecision::TypeBudgetExhausted
            }
            _ => ThrottleDecision::Emit,
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

    #[test]
    fn type_budget_counts_only_warnings_that_pass_the_per_token_check() {
        let throttle = WarningThrottle::default()
            .with_type_budget(DEFAULT_THROTTLE_PERIOD, NonZeroU32::new(2).unwrap());
        let decisions: Vec<_> = [
            ("tok_a", WarningType::InvalidOptions),
            ("tok_a", WarningType::InvalidOptions),
            ("tok_b", WarningType::InvalidOptions),
            ("tok_c", WarningType::InvalidOptions),
            ("tok_c", WarningType::InvalidOptions),
            ("tok_c", WarningType::MissingEventName),
        ]
        .into_iter()
        .map(|(token, warning)| throttle.check(token, warning))
        .collect();
        assert_eq!(
            decisions,
            vec![
                ThrottleDecision::Emit,
                // A repeat is stopped per token and leaves the budget alone.
                ThrottleDecision::Throttled,
                ThrottleDecision::Emit,
                ThrottleDecision::TypeBudgetExhausted,
                // The refused check still spent tok_c's per-token permit.
                ThrottleDecision::Throttled,
                // Each type has its own budget.
                ThrottleDecision::Emit,
            ]
        );
    }

    #[test]
    fn type_budget_refills_after_the_period() {
        let throttle =
            WarningThrottle::default().with_type_budget(Duration::from_millis(50), NonZeroU32::MIN);
        assert_eq!(
            throttle.check("tok_a", WarningType::InvalidOptions),
            ThrottleDecision::Emit
        );
        assert_eq!(
            throttle.check("tok_b", WarningType::InvalidOptions),
            ThrottleDecision::TypeBudgetExhausted
        );
        std::thread::sleep(Duration::from_millis(80));
        assert_eq!(
            throttle.check("tok_c", WarningType::InvalidOptions),
            ThrottleDecision::Emit
        );
    }

    #[test]
    fn default_throttle_has_no_type_budget() {
        let throttle = WarningThrottle::default();
        for i in 0..1_000 {
            assert_eq!(
                throttle.check(&format!("tok_{i}"), WarningType::InvalidOptions),
                ThrottleDecision::Emit
            );
        }
    }
}
