//! Per-(token:distinct_id) BYTE-rate limiter for the AI capture lane.
//!
//! Unlike `OverflowLimiter` (which reroutes over-budget events to an overflow
//! topic), this limiter's decision drives a hard DROP upstream: the AI lane's
//! 8 MiB events make byte throughput, not event count, the resource to bound.
//! It wraps the same `governor` keyed rate limiter but charges the event's
//! serialized byte size via the weighted `check_key_n`, and supports a
//! per-token override map so a heavy multimodal customer's ceiling can be
//! raised without loosening the global default.
use std::collections::HashMap;
use std::num::NonZeroU32;
use std::sync::Arc;

use governor::{
    clock, state::keyed::DefaultKeyedStateStore, NegativeMultiDecision, Quota, RateLimiter,
};

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
            continue;
        };
        let Some((ps, burst)) = spec.split_once(':') else {
            continue;
        };
        let (Ok(ps), Ok(burst)) = (ps.trim().parse::<u32>(), burst.trim().parse::<u32>()) else {
            continue;
        };
        let (Some(ps), Some(burst)) = (NonZeroU32::new(ps), NonZeroU32::new(burst)) else {
            continue;
        };
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

    /// Charge `weight_bytes` against the key's budget. An empty key or zero
    /// weight is always `Within` (nothing to charge). A weight larger than the
    /// burst capacity can never fit (`InsufficientCapacity`) and is `Exceeded`.
    pub fn check(&self, event_key: &str, token: &str, weight_bytes: u32) -> ByteLimitDecision {
        if event_key.is_empty() {
            return ByteLimitDecision::Within;
        }
        let Some(weight) = NonZeroU32::new(weight_bytes) else {
            return ByteLimitDecision::Within;
        };
        let limiter = self.overrides.get(token).unwrap_or(&self.default);
        match limiter.check_key_n(&event_key.to_string(), weight) {
            Ok(()) => ByteLimitDecision::Within,
            Err(NegativeMultiDecision::BatchNonConforming(_, _)) => ByteLimitDecision::Exceeded, // over rate/burst right now
            Err(NegativeMultiDecision::InsufficientCapacity(_)) => ByteLimitDecision::Exceeded, // weight > burst: never fits
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
        assert_eq!(l.check("tok:user", "tok", 500), ByteLimitDecision::Within);
    }

    #[test]
    fn exceeding_burst_in_one_shot_is_limited() {
        // A single event heavier than the whole burst can never fit:
        // governor returns InsufficientCapacity, which we map to Exceeded.
        let l = limiter(1_000, 10_000, None);
        assert_eq!(
            l.check("tok:user", "tok", 20_000),
            ByteLimitDecision::Exceeded
        );
    }

    #[test]
    fn sustained_bytes_exhaust_the_budget() {
        // burst=10_000 bytes; two 6_000-byte events in the same instant:
        // the first fits, the second exceeds the remaining budget.
        let l = limiter(1_000, 10_000, None);
        assert_eq!(l.check("tok:user", "tok", 6_000), ByteLimitDecision::Within);
        assert_eq!(
            l.check("tok:user", "tok", 6_000),
            ByteLimitDecision::Exceeded
        );
    }

    #[test]
    fn budget_is_per_key_not_global() {
        let l = limiter(1_000, 10_000, None);
        assert_eq!(l.check("tok:a", "tok", 9_000), ByteLimitDecision::Within);
        // Different distinct_id => different key => own budget.
        assert_eq!(l.check("tok:b", "tok", 9_000), ByteLimitDecision::Within);
    }

    #[test]
    fn empty_key_is_allowed() {
        let l = limiter(1_000, 10_000, None);
        assert_eq!(l.check("", "", 5_000), ByteLimitDecision::Within);
    }

    #[test]
    fn zero_weight_is_allowed() {
        let l = limiter(1_000, 10_000, None);
        assert_eq!(l.check("tok:user", "tok", 0), ByteLimitDecision::Within);
    }

    #[test]
    fn override_raises_a_specific_tokens_ceiling() {
        // Default burst 10_000; override "big" to burst 1_000_000.
        let l = limiter(1_000, 10_000, Some("big=1000000:1000000"));
        // Default token limited by the small burst.
        assert_eq!(
            l.check("tok:user", "tok", 20_000),
            ByteLimitDecision::Exceeded
        );
        // Overridden token admits the same weight.
        assert_eq!(
            l.check("big:user", "big", 20_000),
            ByteLimitDecision::Within
        );
    }

    #[test]
    fn malformed_override_entries_are_skipped() {
        // "bad" has no '='; "x=notnum" has a non-numeric spec; both ignored,
        // "ok=15:15" parsed. No panic.
        let l = limiter(1_000, 10_000, Some("bad,x=notnum,ok=15:15, "));
        assert_eq!(l.check("ok:user", "ok", 10), ByteLimitDecision::Within);
        assert_eq!(l.check("ok:user", "ok", 10), ByteLimitDecision::Exceeded);
    }
}
