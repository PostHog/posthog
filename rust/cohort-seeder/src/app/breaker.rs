//! App layer: the per-run breaker that stops claiming a run's chunks while ClickHouse keeps refusing
//! its scans for lack of resources.
//!
//! The chunk retry backoff delays only the failed chunk, so without this a run's pending chunks
//! refill every freed slot with a scan that fails the same way. The state is process-local, so a
//! restart closes every breaker.

use std::collections::HashMap;
use std::num::NonZeroU32;
use std::time::{Duration, Instant};

use crate::domain::backoff::MAX_RETRY_BACKOFF_CAP;
use crate::domain::{AttemptCount, BackoffPolicyError, RetryBackoffPolicy, RunId};

/// Not shorter than any cooldown, so an open breaker is never dropped before it would close.
const IDLE_EXPIRY: Duration = MAX_RETRY_BACKOFF_CAP;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BreakerPolicy {
    threshold: NonZeroU32,
    cooldown: RetryBackoffPolicy,
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
        Ok(Self {
            threshold: NonZeroU32::new(threshold).ok_or(BreakerPolicyError::ZeroThreshold)?,
            cooldown: RetryBackoffPolicy::new(cooldown_base, cooldown_cap)
                .map_err(BreakerPolicyError::Cooldown)?,
            max_trips: NonZeroU32::new(max_trips).ok_or(BreakerPolicyError::ZeroMaxTrips)?,
        })
    }

    fn cooldown(self, trip: u32) -> Duration {
        self.cooldown.ceiling(AttemptCount::new(trip))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum BreakerPolicyError {
    #[error("the breaker failure threshold must be greater than zero")]
    ZeroThreshold,
    #[error("the breaker trip limit must be greater than zero")]
    ZeroMaxTrips,
    #[error("invalid breaker cooldown: {0}")]
    Cooldown(BackoffPolicyError),
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
    /// The caller fails the run. [`RunBreakers::retry_exhausted`] admits one more probe when that
    /// write does not apply.
    Exhausted,
}

#[derive(Debug, Clone, Copy)]
struct Entry {
    state: State,
    touched: Instant,
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

    /// The breaker turns half-open only once none of the run's chunks is in flight, so the one
    /// probe it then admits is the only chunk whose result the half-open state counts.
    pub fn admits(&mut self, run_id: RunId, now: Instant, run_in_flight: bool) -> bool {
        let Some(entry) = self.entries.get_mut(&run_id) else {
            return true;
        };
        match entry.state {
            State::Closed { .. } => true,
            State::Open { until, trips } if now >= until && !run_in_flight => {
                entry.state = State::HalfOpen { trips };
                true
            }
            State::Open { .. } | State::Exhausted => false,
            State::HalfOpen { .. } => !run_in_flight,
        }
    }

    /// While open or exhausted, every chunk in flight was claimed before the breaker opened, so its
    /// confirmation says nothing about whether ClickHouse has recovered.
    pub fn record_success(&mut self, run_id: RunId) {
        if self.entries.get(&run_id).is_some_and(|entry| {
            matches!(entry.state, State::Closed { .. } | State::HalfOpen { .. })
        }) {
            self.entries.remove(&run_id);
        }
    }

    /// Failing the run did not apply. The next probe's resource failure exhausts the breaker again,
    /// so the caller retries the write, and a confirmed probe closes it.
    pub fn retry_exhausted(&mut self, run_id: RunId) {
        let retry = State::HalfOpen {
            trips: self.policy.max_trips.get() - 1,
        };
        if let Some(entry) = self
            .entries
            .get_mut(&run_id)
            .filter(|entry| entry.state == State::Exhausted)
        {
            entry.state = retry;
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
        assert!(breakers.admits(run(), start, true));
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
        assert!(!breakers.admits(run(), start + BASE / 2, false));

        assert!(breakers.admits(run(), start + BASE, false));
        assert!(
            !breakers.admits(run(), start + BASE, true),
            "a second probe was admitted beside the first"
        );
        assert_eq!(
            breakers.record_resource_failure(run(), start + BASE),
            BreakerEvent::Tripped {
                trips: 2,
                cooldown: BASE * 2
            },
            "a failed probe waited for the threshold again"
        );
        assert!(!breakers.admits(run(), start + BASE * 2, false));

        assert!(breakers.admits(run(), start + BASE * 3, false));
        assert_eq!(
            breakers.record_resource_failure(run(), start + BASE * 3),
            BreakerEvent::Exhausted { trips: 3 }
        );
        assert!(
            !breakers.admits(run(), start + BASE * 100, false),
            "an exhausted run went back to full concurrency"
        );

        breakers.retry_exhausted(run());
        assert!(
            breakers.admits(run(), start + BASE * 100, false),
            "a run whose failure did not apply stayed refused for good"
        );
        assert_eq!(
            breakers.record_resource_failure(run(), start + BASE * 100),
            BreakerEvent::Exhausted { trips: 3 }
        );
    }

    #[test]
    fn chunks_claimed_before_the_trip_neither_count_nor_close_it() {
        let mut breakers = breakers(1, 2);
        let start = Instant::now();
        breakers.record_resource_failure(run(), start);

        assert!(
            !breakers.admits(run(), start + BASE, true),
            "a probe was admitted beside a chunk claimed before the trip"
        );
        assert_eq!(
            breakers.record_resource_failure(run(), start + BASE),
            BreakerEvent::Unchanged,
            "a chunk claimed before the trip counted as a failed probe"
        );
        breakers.record_success(run());
        assert!(
            breakers.is_open(run()),
            "a chunk claimed before the trip closed the breaker"
        );

        assert!(breakers.admits(run(), start + BASE, false));
        assert_eq!(
            breakers.record_resource_failure(run(), start + BASE),
            BreakerEvent::Exhausted { trips: 2 }
        );
    }

    #[test]
    fn a_confirmed_chunk_resets_the_failures_in_a_row() {
        let mut breakers = breakers(3, 4);
        let start = Instant::now();
        breakers.record_resource_failure(run(), start);
        breakers.record_resource_failure(run(), start);
        breakers.record_success(run());

        assert_eq!(
            breakers.record_resource_failure(run(), start),
            BreakerEvent::Unchanged
        );
        assert_eq!(
            breakers.record_resource_failure(run(), start),
            BreakerEvent::Unchanged
        );
        assert!(!breakers.is_open(run()));
    }

    #[test]
    fn a_confirmed_chunk_closes_the_breaker_and_resets_the_trip_count() {
        let mut breakers = breakers(1, 2);
        let start = Instant::now();
        assert!(matches!(
            breakers.record_resource_failure(run(), start),
            BreakerEvent::Tripped { trips: 1, .. }
        ));
        assert!(breakers.admits(run(), start + BASE, false));

        breakers.record_success(run());

        assert!(breakers.admits(run(), start + BASE, true));
        assert!(matches!(
            breakers.record_resource_failure(run(), start + BASE),
            BreakerEvent::Tripped { trips: 1, .. }
        ));
    }

    #[test]
    fn an_open_breaker_outlives_the_idle_expiry_until_its_cooldown_ends() {
        let mut breakers = RunBreakers::new(
            BreakerPolicy::new(1, MAX_RETRY_BACKOFF_CAP, MAX_RETRY_BACKOFF_CAP, 2).unwrap(),
        );
        let start = Instant::now();
        breakers.record_resource_failure(run(), start);

        breakers.expire_idle(start + IDLE_EXPIRY - Duration::from_secs(1));
        assert!(breakers.is_open(run()));

        breakers.expire_idle(start + IDLE_EXPIRY + Duration::from_secs(1));
        assert!(!breakers.is_open(run()));
    }
}
