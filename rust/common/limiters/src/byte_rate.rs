//! Byte-rate limiter for the AI capture lane: charges each event's serialized
//! size against the token's budget and DROPS over-budget events (unlike
//! `OverflowLimiter`, which reroutes — a byte flood has to actually shed).
//!
//! Keyed on token alone, not `token:distinct_id`: `distinct_id` is
//! client-controlled, so per-user keying would just be a way to rotate around
//! the cap.
use std::collections::HashMap;
use std::num::NonZeroU32;
use std::sync::Arc;

use governor::{
    clock, state::keyed::DefaultKeyedStateStore, NegativeMultiDecision, Quota, RateLimiter,
};
use metrics::gauge;
use rand::Rng;
use tracing::warn;

type KeyedLimiter = RateLimiter<String, DefaultKeyedStateStore<String>, clock::DefaultClock>;

#[derive(Debug, PartialEq, Eq)]
pub enum ByteLimitDecision {
    Within,
    Exceeded,
}

#[derive(Clone)]
pub struct ByteRateLimiter {
    default: Arc<KeyedLimiter>,
    /// token -> its own limiter, built from a raised quota.
    overrides: HashMap<String, Arc<KeyedLimiter>>,
}

fn build(per_second: NonZeroU32, burst: NonZeroU32) -> Arc<KeyedLimiter> {
    let quota = Quota::per_second(per_second).allow_burst(burst);
    Arc::new(RateLimiter::dashmap(quota))
}

fn parse_overrides(raw: Option<String>) -> HashMap<String, Arc<KeyedLimiter>> {
    let mut map = HashMap::new();
    let Some(raw) = raw else {
        return map;
    };
    for entry in raw.split(',') {
        let entry = entry.trim();
        if entry.is_empty() {
            continue;
        }
        let Some((token, spec)) = entry.split_once('=') else {
            warn!(entry, "AI byte limit override missing '=': skipping");
            continue;
        };
        let Some((ps, burst)) = spec.split_once(':') else {
            warn!(entry, "AI byte limit override missing ':': skipping");
            continue;
        };
        let (Ok(ps), Ok(burst)) = (ps.trim().parse::<u32>(), burst.trim().parse::<u32>()) else {
            warn!(
                entry,
                "AI byte limit override has a non-numeric per_second or burst: skipping"
            );
            continue;
        };
        let (Some(ps), Some(burst)) = (NonZeroU32::new(ps), NonZeroU32::new(burst)) else {
            warn!(
                entry,
                "AI byte limit override has a zero per_second or burst: skipping"
            );
            continue;
        };
        if burst.get() < 8_388_608 {
            warn!(
                entry,
                burst = burst.get(),
                "AI byte limit override burst is below the 8 MiB max AI event size; \
                 large AI events for this token will always be dropped"
            );
        }
        map.insert(token.trim().to_string(), build(ps, burst));
    }
    map
}

impl ByteRateLimiter {
    pub fn new(per_second: NonZeroU32, burst: NonZeroU32, overrides: Option<String>) -> Self {
        ByteRateLimiter {
            default: build(per_second, burst),
            overrides: parse_overrides(overrides),
        }
    }

    /// A weight above the burst capacity can never fit (`InsufficientCapacity`)
    /// and is `Exceeded`.
    pub fn check(&self, token: &str, weight_bytes: u32) -> ByteLimitDecision {
        if token.is_empty() {
            return ByteLimitDecision::Within;
        }
        let Some(weight) = NonZeroU32::new(weight_bytes) else {
            return ByteLimitDecision::Within;
        };
        let limiter = self.overrides.get(token).unwrap_or(&self.default);
        match limiter.check_key_n(&token.to_string(), weight) {
            Ok(()) => ByteLimitDecision::Within,
            Err(NegativeMultiDecision::BatchNonConforming(_, _)) => ByteLimitDecision::Exceeded, // over rate/burst right now
            Err(NegativeMultiDecision::InsufficientCapacity(_)) => ByteLimitDecision::Exceeded, // weight > burst: never fits
        }
    }

    fn all_limiters(&self) -> impl Iterator<Item = &Arc<KeyedLimiter>> {
        std::iter::once(&self.default).chain(self.overrides.values())
    }

    /// Gauges tracked key count (default + overrides); spawn as a task. `lane`
    /// keeps concurrent limiter instances from overwriting each other's series.
    pub async fn report_metrics(&self, lane: &'static str) {
        let mut interval = tokio::time::interval(tokio::time::Duration::from_secs(10));
        loop {
            interval.tick().await;
            let key_count: f64 = self.all_limiters().map(|l| l.len() as f64).sum();
            gauge!("ai_byte_limiter_key_count", "lane" => lane).set(key_count);
        }
    }

    /// Evicts stale per-key state (default + overrides) so memory stays bounded; spawn as a task.
    pub async fn clean_state(&self) {
        // Jitter the interval so replicas don't all lock at once.
        let interval_secs = rand::thread_rng().gen_range(60..70);

        let mut interval = tokio::time::interval(tokio::time::Duration::from_secs(interval_secs));
        loop {
            interval.tick().await;
            self.clean_state_once();
        }
    }

    fn clean_state_once(&self) {
        for limiter in self.all_limiters() {
            limiter.retain_recent();
            limiter.shrink_to_fit();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::num::NonZeroU32;

    fn limiter(per_second: u32, burst: u32, overrides: Option<&str>) -> ByteRateLimiter {
        ByteRateLimiter::new(
            NonZeroU32::new(per_second).unwrap(),
            NonZeroU32::new(burst).unwrap(),
            overrides.map(String::from),
        )
    }

    #[test]
    fn within_budget_is_allowed() {
        let l = limiter(1_000, 10_000, None);
        assert_eq!(l.check("tok", 500), ByteLimitDecision::Within);
    }

    #[test]
    fn exceeding_burst_in_one_shot_is_limited() {
        // A single event heavier than the whole burst can never fit:
        // governor returns InsufficientCapacity, which we map to Exceeded.
        let l = limiter(1_000, 10_000, None);
        assert_eq!(l.check("tok", 20_000), ByteLimitDecision::Exceeded);
    }

    #[test]
    fn sustained_bytes_exhaust_the_budget() {
        // burst=10_000 bytes; two 6_000-byte events in the same instant:
        // the first fits, the second exceeds the remaining budget.
        let l = limiter(1_000, 10_000, None);
        assert_eq!(l.check("tok", 6_000), ByteLimitDecision::Within);
        assert_eq!(l.check("tok", 6_000), ByteLimitDecision::Exceeded);
    }

    #[test]
    fn different_tokens_get_independent_budgets() {
        let l = limiter(1_000, 10_000, None);
        assert_eq!(l.check("tok_a", 9_000), ByteLimitDecision::Within);
        // A different token is a different project, with its own budget.
        assert_eq!(l.check("tok_b", 9_000), ByteLimitDecision::Within);
    }

    #[test]
    fn same_token_shares_one_budget_across_distinct_ids() {
        // The budget is per-token: two events under the same token exhaust
        // one shared budget regardless of which distinct_id produced them.
        let l = limiter(1_000, 10_000, None);
        assert_eq!(l.check("tok", 6_000), ByteLimitDecision::Within);
        assert_eq!(l.check("tok", 6_000), ByteLimitDecision::Exceeded);
    }

    #[test]
    fn empty_token_is_allowed() {
        let l = limiter(1_000, 10_000, None);
        assert_eq!(l.check("", 5_000), ByteLimitDecision::Within);
    }

    #[test]
    fn zero_weight_is_allowed() {
        let l = limiter(1_000, 10_000, None);
        assert_eq!(l.check("tok", 0), ByteLimitDecision::Within);
    }

    #[test]
    fn override_raises_a_specific_tokens_ceiling() {
        // Default burst 10_000; override "big" to burst 1_000_000.
        let l = limiter(1_000, 10_000, Some("big=1000000:1000000"));
        // Default token limited by the small burst.
        assert_eq!(l.check("tok", 20_000), ByteLimitDecision::Exceeded);
        // Overridden token admits the same weight.
        assert_eq!(l.check("big", 20_000), ByteLimitDecision::Within);
    }

    #[test]
    fn malformed_override_entries_are_skipped() {
        // "bad" has no '='; "x=notnum" has a non-numeric spec; both ignored,
        // "ok=15:15" parsed. No panic.
        let l = limiter(1_000, 10_000, Some("bad,x=notnum,ok=15:15, "));
        assert_eq!(l.check("ok", 10), ByteLimitDecision::Within);
        assert_eq!(l.check("ok", 10), ByteLimitDecision::Exceeded);
    }

    #[test]
    fn override_burst_below_the_8mib_floor_still_parses() {
        // Below the floor is a footgun (large AI events for this token will
        // always be dropped) but not a parse error: the override still
        // builds, it just warns.
        let l = limiter(1_000, 10_000, Some("small=1000:100"));
        assert_eq!(l.check("small", 50), ByteLimitDecision::Within);
        assert_eq!(l.check("small", 100), ByteLimitDecision::Exceeded);
    }

    #[test]
    fn clean_state_covers_default_and_overrides_without_dropping_recent_entries() {
        // A slow per_second refill relative to the burst means a key charged
        // close to its full burst stays well below "fresh" (fully recovered)
        // for long enough that retain_recent must not evict it, regardless of
        // scheduling jitter in this test.
        let l = limiter(1, 10_000, Some("big=1:1000000"));
        // Populate both the default limiter and the override limiter's dashmap.
        assert_eq!(l.check("tok", 9_000), ByteLimitDecision::Within);
        assert_eq!(l.check("big", 900_000), ByteLimitDecision::Within);

        l.clean_state_once();

        // Still-recent entries must survive retain_recent: the budget already
        // spent should still be reflected, on both the default and override
        // limiter.
        assert_eq!(l.check("tok", 9_000), ByteLimitDecision::Exceeded);
        assert_eq!(l.check("big", 900_000), ByteLimitDecision::Exceeded);
    }

    #[tokio::test]
    async fn report_metrics_and_clean_state_do_not_panic_when_polled_once() {
        let l = limiter(1_000, 10_000, Some("big=1000000:1000000"));
        assert_eq!(l.check("tok", 500), ByteLimitDecision::Within);
        assert_eq!(l.check("big", 500), ByteLimitDecision::Within);

        let key_count: f64 = l.all_limiters().map(|lim| lim.len() as f64).sum();
        assert_eq!(key_count, 2.0);

        l.clean_state_once();
    }
}
