//! App layer: the per-run breaker that stops claiming a run's chunks while ClickHouse keeps refusing
//! its scans for lack of resources.
//!
//! The chunk retry backoff delays only the failed chunk, so without this a run's pending chunks
//! refill every freed slot with a scan that fails the same way. The state is process-local, so a
//! restart closes every breaker.

use std::collections::HashMap;
use std::num::NonZeroU32;
use std::time::{Duration, Instant};

use crate::domain::RunId;

/// Keeps `Instant + cooldown` far from overflow.
pub const MAX_BREAKER_COOLDOWN: Duration = Duration::from_secs(24 * 60 * 60);

/// Not shorter than any cooldown, so an open breaker is never dropped before it would close.
const IDLE_EXPIRY: Duration = MAX_BREAKER_COOLDOWN;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BreakerPolicy {
    threshold: NonZeroU32,
    cooldown_base: Duration,
    cooldown_cap: Duration,
    max_trips: NonZeroU32,
}

impl BreakerPolicy {
    /// `threshold` resource failures in a row open the breaker for `cooldown_base × 2^(trip - 1)`,
    /// capped at `cooldown_cap`. The `max_trips`-th opening without a confirmed chunk fails the run.
    pub fn new(
        threshold: u32,
        cooldown_base: Duration,
        cooldown_cap: Duration,
        max_trips: u32,
    ) -> Result<Self, BreakerPolicyError> {
        let threshold = NonZeroU32::new(threshold).ok_or(BreakerPolicyError::ZeroThreshold)?;
        let max_trips = NonZeroU32::new(max_trips).ok_or(BreakerPolicyError::ZeroMaxTrips)?;
        if cooldown_base.is_zero() {
            return Err(BreakerPolicyError::ZeroCooldown);
        }
        if cooldown_cap < cooldown_base {
            return Err(BreakerPolicyError::CapBelowBase);
        }
        if cooldown_cap > MAX_BREAKER_COOLDOWN {
            return Err(BreakerPolicyError::CapTooLarge);
        }
        Ok(Self {
            threshold,
            cooldown_base,
            cooldown_cap,
            max_trips,
        })
    }

    fn cooldown(self, trip: u32) -> Duration {
        let doublings = trip.saturating_sub(1).min(u32::BITS - 1);
        self.cooldown_base
            .saturating_mul(1 << doublings)
            .min(self.cooldown_cap)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum BreakerPolicyError {
    #[error("the breaker failure threshold must be greater than zero")]
    ZeroThreshold,
    #[error("the breaker trip limit must be greater than zero")]
    ZeroMaxTrips,
    #[error("the breaker cooldown must be greater than zero")]
    ZeroCooldown,
    #[error("the breaker cooldown cap must be at least the base")]
    CapBelowBase,
    #[error("the breaker cooldown cap must be at most 24 hours")]
    CapTooLarge,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum State {
    Closed {
        consecutive: u32,
    },
    /// A failure that arrives while open came from a chunk claimed before the trip, so it does not
    /// count.
    Open {
        until: Instant,
        trips: u32,
    },
    HalfOpen {
        trips: u32,
    },
    /// Keeps refusing claims in case failing the run in Postgres did not apply.
    Exhausted,
}

#[derive(Debug, Clone, Copy)]
struct Entry {
    state: State,
    touched: Instant,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Admission {
    Admit,
    /// Admit only while none of the run's chunks is in flight.
    Probe,
    Refuse,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BreakerEvent {
    Unchanged,
    Tripped {
        trips: u32,
        cooldown: Duration,
    },
    /// The caller fails the run.
    Exhausted {
        trips: u32,
    },
}

#[derive(Debug)]
pub struct RunBreakers {
    policy: BreakerPolicy,
    entries: HashMap<RunId, Entry>,
}

impl RunBreakers {
    pub fn new(policy: BreakerPolicy) -> Self {
        Self {
            policy,
            entries: HashMap::new(),
        }
    }

    pub fn admission(&mut self, run_id: RunId, now: Instant) -> Admission {
        let Some(entry) = self.entries.get_mut(&run_id) else {
            return Admission::Admit;
        };
        match entry.state {
            State::Closed { .. } => Admission::Admit,
            State::Open { until, trips } if now >= until => {
                entry.state = State::HalfOpen { trips };
                Admission::Probe
            }
            State::Open { .. } | State::Exhausted => Admission::Refuse,
            State::HalfOpen { .. } => Admission::Probe,
        }
    }

    /// An exhausted run stays refused, because a chunk claimed before it failed can still confirm.
    pub fn record_success(&mut self, run_id: RunId) {
        if self
            .entries
            .get(&run_id)
            .is_some_and(|entry| entry.state != State::Exhausted)
        {
            self.entries.remove(&run_id);
        }
    }

    pub fn record_resource_failure(&mut self, run_id: RunId, now: Instant) -> BreakerEvent {
        let entry = self.entries.entry(run_id).or_insert(Entry {
            state: State::Closed { consecutive: 0 },
            touched: now,
        });
        entry.touched = now;
        let trips_before = match entry.state {
            State::Closed { consecutive } => {
                let consecutive = consecutive.saturating_add(1);
                if consecutive < self.policy.threshold.get() {
                    entry.state = State::Closed { consecutive };
                    return BreakerEvent::Unchanged;
                }
                0
            }
            State::Open { .. } | State::Exhausted => return BreakerEvent::Unchanged,
            State::HalfOpen { trips } => trips,
        };
        let trips = trips_before.saturating_add(1);
        if trips >= self.policy.max_trips.get() {
            entry.state = State::Exhausted;
            return BreakerEvent::Exhausted { trips };
        }
        let cooldown = self.policy.cooldown(trips);
        entry.state = State::Open {
            until: now + cooldown,
            trips,
        };
        BreakerEvent::Tripped { trips, cooldown }
    }

    pub fn is_open(&self, run_id: RunId) -> bool {
        self.entries
            .get(&run_id)
            .is_some_and(|entry| !matches!(entry.state, State::Closed { .. }))
    }

    /// Keyed on age rather than on the eligible-run set, because a discovery error yields an empty
    /// set and would reset every breaker.
    pub fn expire_idle(&mut self, now: Instant) {
        self.entries.retain(|_, entry| {
            let open_until_future = matches!(entry.state, State::Open { until, .. } if until > now);
            open_until_future || now.duration_since(entry.touched) < IDLE_EXPIRY
        });
    }
}

#[cfg(test)]
mod tests {
    use uuid::Uuid;

    use super::*;

    const BASE: Duration = Duration::from_secs(300);

    fn breakers(threshold: u32, max_trips: u32) -> RunBreakers {
        RunBreakers::new(
            BreakerPolicy::new(threshold, BASE, Duration::from_secs(1800), max_trips).unwrap(),
        )
    }

    fn run() -> RunId {
        RunId(Uuid::from_u128(1))
    }

    #[test]
    fn consecutive_resource_failures_trip_then_probe_then_exhaust() {
        let mut breakers = breakers(3, 3);
        let start = Instant::now();

        assert_eq!(
            breakers.record_resource_failure(run(), start),
            BreakerEvent::Unchanged
        );
        assert_eq!(
            breakers.record_resource_failure(run(), start),
            BreakerEvent::Unchanged
        );
        assert_eq!(breakers.admission(run(), start), Admission::Admit);
        assert_eq!(
            breakers.record_resource_failure(run(), start),
            BreakerEvent::Tripped {
                trips: 1,
                cooldown: BASE
            }
        );
        assert_eq!(
            breakers.record_resource_failure(run(), start),
            BreakerEvent::Unchanged,
            "a straggler claimed before the trip counted as new evidence"
        );
        assert_eq!(
            breakers.admission(run(), start + BASE / 2),
            Admission::Refuse
        );

        assert_eq!(breakers.admission(run(), start + BASE), Admission::Probe);
        assert_eq!(
            breakers.record_resource_failure(run(), start + BASE),
            BreakerEvent::Tripped {
                trips: 2,
                cooldown: BASE * 2
            },
            "a failed probe waited for the threshold again"
        );
        assert_eq!(
            breakers.admission(run(), start + BASE * 2),
            Admission::Refuse
        );

        assert_eq!(
            breakers.admission(run(), start + BASE * 3),
            Admission::Probe
        );
        assert_eq!(
            breakers.record_resource_failure(run(), start + BASE * 3),
            BreakerEvent::Exhausted { trips: 3 }
        );
        assert_eq!(
            breakers.admission(run(), start + BASE * 100),
            Admission::Refuse,
            "an exhausted run went back to full concurrency"
        );
    }

    #[test]
    fn a_confirmed_chunk_closes_the_breaker_and_resets_the_trip_count() {
        let mut breakers = breakers(1, 2);
        let start = Instant::now();
        assert!(matches!(
            breakers.record_resource_failure(run(), start),
            BreakerEvent::Tripped { trips: 1, .. }
        ));
        assert_eq!(breakers.admission(run(), start + BASE), Admission::Probe);

        breakers.record_success(run());

        assert_eq!(breakers.admission(run(), start + BASE), Admission::Admit);
        assert!(matches!(
            breakers.record_resource_failure(run(), start + BASE),
            BreakerEvent::Tripped { trips: 1, .. }
        ));
    }

    #[test]
    fn an_open_breaker_outlives_the_idle_expiry_until_its_cooldown_ends() {
        let mut breakers = RunBreakers::new(
            BreakerPolicy::new(1, MAX_BREAKER_COOLDOWN, MAX_BREAKER_COOLDOWN, 2).unwrap(),
        );
        let start = Instant::now();
        breakers.record_resource_failure(run(), start);

        breakers.expire_idle(start + IDLE_EXPIRY - Duration::from_secs(1));
        assert!(breakers.is_open(run()));

        breakers.expire_idle(start + IDLE_EXPIRY + Duration::from_secs(1));
        assert!(!breakers.is_open(run()));
    }
}
