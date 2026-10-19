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

use std::collections::HashMap;
use std::num::NonZeroU32;
use std::sync::{Mutex, PoisonError};
use std::time::{Duration, Instant};

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

/// Per-type token bucket: `burst` permits, one refilled per `period`. Not a
/// governor limiter because [`WarningThrottle::check`] must know whether a
/// permit is available before it tracks a new key, and governor can only
/// take one.
struct TypeBudget {
    period: Duration,
    burst: f64,
    buckets: Mutex<HashMap<crate::registry::WarningType, Bucket>>,
}

struct Bucket {
    permits: f64,
    refilled_at: Instant,
}

impl TypeBudget {
    fn new(period: Duration, burst: NonZeroU32) -> Self {
        assert!(!period.is_zero(), "type budget period must be non-zero");
        Self {
            period,
            burst: f64::from(burst.get()),
            buckets: Mutex::new(HashMap::new()),
        }
    }

    fn give_back(&self, warning: crate::registry::WarningType, now: Instant) {
        self.with_permits(warning, now, |permits| *permits += 1.0);
    }

    fn take_permit(&self, warning: crate::registry::WarningType, now: Instant) -> bool {
        self.with_permits(warning, now, |permits| {
            if *permits < 1.0 {
                return false;
            }
            *permits -= 1.0;
            true
        })
    }

    fn with_permits<T>(
        &self,
        warning: crate::registry::WarningType,
        now: Instant,
        f: impl FnOnce(&mut f64) -> T,
    ) -> T {
        let mut buckets = self.buckets.lock().unwrap_or_else(PoisonError::into_inner);
        let bucket = buckets.entry(warning).or_insert(Bucket {
            permits: self.burst,
            refilled_at: now,
        });
        let refilled =
            now.duration_since(bucket.refilled_at).as_secs_f64() / self.period.as_secs_f64();
        bucket.permits = (bucket.permits + refilled).min(self.burst);
        bucket.refilled_at = now;
        f(&mut bucket.permits)
    }
}

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
        self.type_budget = Some(TypeBudget::new(period, burst));
        self
    }

    /// Consume a type budget permit if one is set, then the `(token, type)`
    /// key's own permit if the key map has room. Anything but
    /// [`ThrottleDecision::Emit`] means the caller should drop the warning.
    pub fn check(&self, token: &str, warning: crate::registry::WarningType) -> ThrottleDecision {
        self.check_at(token, warning, Instant::now())
    }

    /// [`Self::check`] as of `now`, so a test can advance the type budget
    /// without sleeping. The per-key limiter keeps its own clock.
    pub fn check_at(
        &self,
        token: &str,
        warning: crate::registry::WarningType,
        now: Instant,
    ) -> ThrottleDecision {
        // Governor's keyed limiter inserts on lookup, so the cap must gate
        // every check — including keys already tracked — to stay O(1).
        if self.limiter.len() >= self.max_tracked_keys {
            return ThrottleDecision::CardinalityCapped;
        }
        // The budget permit is held before the per-key check, so a token the
        // budget refuses neither takes a slot in the map nor spends its own
        // hourly permit, and two racing checks cannot both pass on one
        // permit. A repeat gives the permit back, so a token that repeats a
        // warning cannot use up the budget of every other token.
        if self
            .type_budget
            .as_ref()
            .is_some_and(|budget| !budget.take_permit(warning, now))
        {
            return ThrottleDecision::TypeBudgetExhausted;
        }
        if self
            .limiter
            .check_key(&(token.to_string(), warning))
            .is_err()
        {
            if let Some(budget) = &self.type_budget {
                budget.give_back(warning, now);
            }
            return ThrottleDecision::Throttled;
        }
        ThrottleDecision::Emit
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
                ThrottleDecision::TypeBudgetExhausted,
                // Each type has its own budget.
                ThrottleDecision::Emit,
            ]
        );
        assert_eq!(
            throttle.tracked_keys(),
            3,
            "the refused tok_c checks must not take key-map slots"
        );
    }

    // Racing checks on the last permit: before the permit was taken first,
    // every racer passed the peek, spent its hourly key slot, and the losers
    // then stayed silent for the hour.
    #[test]
    fn a_budget_loser_keeps_its_hourly_permit() {
        let throttle =
            WarningThrottle::default().with_type_budget(DEFAULT_THROTTLE_PERIOD, NonZeroU32::MIN);
        let racers = 16;
        let barrier = std::sync::Barrier::new(racers);
        let decisions: Vec<(String, ThrottleDecision)> = std::thread::scope(|scope| {
            let handles: Vec<_> = (0..racers)
                .map(|n| {
                    let token = format!("tok_{n}");
                    let barrier = &barrier;
                    let throttle = &throttle;
                    scope.spawn(move || {
                        barrier.wait();
                        let decision = throttle.check(&token, WarningType::InvalidOptions);
                        (token, decision)
                    })
                })
                .collect();
            handles.into_iter().map(|h| h.join().unwrap()).collect()
        });
        let emitted = decisions
            .iter()
            .filter(|(_, d)| *d == ThrottleDecision::Emit)
            .count();
        assert_eq!(emitted, 1, "{decisions:?}");
        assert!(decisions.iter().all(|(_, d)| matches!(
            d,
            ThrottleDecision::Emit | ThrottleDecision::TypeBudgetExhausted
        )));
        assert_eq!(
            throttle.tracked_keys(),
            1,
            "only the emitted key holds a slot"
        );

        let (loser, _) = decisions
            .iter()
            .find(|(_, d)| *d == ThrottleDecision::TypeBudgetExhausted)
            .unwrap();
        let refilled = Instant::now() + DEFAULT_THROTTLE_PERIOD;
        assert_eq!(
            throttle.check_at(loser, WarningType::InvalidOptions, refilled),
            ThrottleDecision::Emit,
            "a loser is not throttled once the budget refills"
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
        let later = Instant::now() + Duration::from_millis(80);
        assert_eq!(
            throttle.check_at("tok_c", WarningType::InvalidOptions, later),
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
