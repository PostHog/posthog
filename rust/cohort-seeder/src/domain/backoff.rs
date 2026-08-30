//! Domain layer (pure): how long a failed chunk waits before it is claimable again. Depends on
//! nothing above `domain`.
//!
//! Without a wait, a chunk that fails for a durable reason (a ClickHouse memory limit, a poisoned
//! row) is re-claimed by the next poll tick and fails the same way, so it burns its whole attempt
//! budget in minutes and takes its run down with it. The policy spends the same budget over a much
//! longer window, which is what gives a transient cause time to clear.

use std::time::Duration;

use rand::Rng;

/// The chunk's `attempts` column, as the claim `RETURNING` reports it. One is the first attempt, so
/// the first retry waits exactly [`RetryBackoffPolicy::base`].
///
/// This tracks claims only while the chunk is under the attempt cap. The claim `CASE` stops
/// incrementing at the cap, so a `produced` chunk that keeps being reclaimed there is claimed more
/// times than this counts — deliberately, since it retries a Kafka write that is already done and
/// must not be spaced out further.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct AttemptCount(u32);

impl AttemptCount {
    /// Read the `attempts` column. The claim UPDATE increments before it returns, so a live value
    /// is always at least one; a zero or negative value can only come from a hand-edited row, and
    /// is read as the first attempt rather than as "no wait at all".
    pub fn from_row(attempts: i32) -> Self {
        Self(u32::try_from(attempts).map_or(1, |count| count.max(1)))
    }

    pub const fn get(self) -> u32 {
        self.0
    }
}

/// Exponential backoff with full jitter, bounded by a cap. Copy, so it threads through the chunk
/// pipeline as a value rather than a shared handle.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RetryBackoffPolicy {
    base: Duration,
    cap: Duration,
}

/// The widest wait the policy accepts. Any real backoff is minutes, so this is not a tuning bound:
/// it keeps the delay inside what `make_interval(secs => …)` can add to a timestamp. A wider value
/// would make the store's `fail` write throw, and a failed `fail` leaves the chunk holding its lease
/// in `scanning` until the poisoned-chunk sweep reaches it at the attempt cap, so every failure
/// fleet-wide would look like a crashed worker.
///
/// A configured cap above 6 hours would collide with the Django inventory's stall detector, which
/// classifies a run untouched for that long as `seeding-stalled` and terminalizes it by default. A
/// run merely waiting out one backoff would then be a cancel target. The shipped 1800s is far
/// inside that; anything approaching 6 h needs the detector's side changed first.
pub const MAX_RETRY_BACKOFF_CAP: Duration = Duration::from_secs(24 * 60 * 60);

impl RetryBackoffPolicy {
    pub fn new(base: Duration, cap: Duration) -> Result<Self, BackoffPolicyError> {
        if base.is_zero() {
            return Err(BackoffPolicyError::ZeroBase);
        }
        if cap < base {
            return Err(BackoffPolicyError::CapBelowBase);
        }
        if cap > MAX_RETRY_BACKOFF_CAP {
            return Err(BackoffPolicyError::CapTooLarge);
        }
        Ok(Self { base, cap })
    }

    pub const fn base(self) -> Duration {
        self.base
    }

    pub const fn cap(self) -> Duration {
        self.cap
    }

    /// The longest a chunk waits after its `attempt`-th claim failed: `base * 2^(attempt - 1)`,
    /// clamped to `cap`.
    ///
    /// The doubling count is itself clamped to the width of the multiplier, so an attempts column
    /// raised to an absurd value cannot wrap the shift into a short wait. That clamp also bounds
    /// the ceiling at `base * 2^31` when `cap` is larger, which no configured cap reaches.
    pub fn ceiling(self, attempt: AttemptCount) -> Duration {
        let doublings = attempt.get().saturating_sub(1).min(u32::BITS - 1);
        self.base.saturating_mul(1 << doublings).min(self.cap)
    }

    /// A uniformly random wait in the closed interval `[0, ceiling]`. Full jitter, not a fixed
    /// ceiling: several replicas that failed the same chunk from one shared cause would otherwise
    /// become claimable at the same instant and collide again on every retry. The expected wait is
    /// half the ceiling, so the spacing still doubles per attempt.
    pub fn delay_after(self, attempt: AttemptCount) -> Duration {
        // The ceiling is bounded by `MAX_RETRY_BACKOFF_CAP`, so the millisecond narrowing is always
        // in range. It saturates rather than panicking anyway, because a panic here would take down
        // a chunk worker over a configuration value.
        let ceiling_ms = u64::try_from(self.ceiling(attempt).as_millis()).unwrap_or(u64::MAX);
        Duration::from_millis(rand::thread_rng().gen_range(0..=ceiling_ms))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum BackoffPolicyError {
    #[error("retry backoff base must be greater than zero")]
    ZeroBase,
    #[error("retry backoff cap must be at least the base")]
    CapBelowBase,
    #[error("retry backoff cap must be at most 24 hours")]
    CapTooLarge,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn policy() -> RetryBackoffPolicy {
        RetryBackoffPolicy::new(Duration::from_secs(30), Duration::from_secs(1800)).unwrap()
    }

    #[test]
    fn the_ceiling_doubles_each_attempt_until_it_reaches_the_cap() {
        let policy = policy();
        let ceiling = |attempt| policy.ceiling(AttemptCount::from_row(attempt));
        assert_eq!(ceiling(1), Duration::from_secs(30));
        assert_eq!(ceiling(2), Duration::from_secs(60));
        assert_eq!(ceiling(3), Duration::from_secs(120));
        assert_eq!(ceiling(6), Duration::from_secs(960));
        // 30s * 2^6 is 1920s, past the 1800s cap.
        assert_eq!(ceiling(7), Duration::from_secs(1800));
        assert_eq!(ceiling(8), Duration::from_secs(1800));
    }

    /// An attempts column raised far past the cap must still land on `cap`. A multiplier that
    /// wrapped would hand a wedged chunk a near-zero wait, which is the storm this policy exists to
    /// stop.
    #[test]
    fn an_absurd_attempt_count_saturates_onto_the_cap() {
        let policy = policy();
        for attempts in [31, 32, 33, 64, 1_000, i32::MAX] {
            assert_eq!(
                policy.ceiling(AttemptCount::from_row(attempts)),
                Duration::from_secs(1800),
                "attempt {attempts} escaped the cap"
            );
        }
    }

    #[test]
    fn the_attempt_count_reads_a_non_positive_column_as_the_first_attempt() {
        assert_eq!(AttemptCount::from_row(0).get(), 1);
        assert_eq!(AttemptCount::from_row(-4).get(), 1);
        assert_eq!(AttemptCount::from_row(1).get(), 1);
        assert_eq!(AttemptCount::from_row(9).get(), 9);
    }

    #[test]
    fn every_sampled_delay_lands_inside_its_attempt_ceiling() {
        let policy = policy();
        for attempts in 1..=10 {
            let attempt = AttemptCount::from_row(attempts);
            let ceiling = policy.ceiling(attempt);
            for _ in 0..64 {
                let delay = policy.delay_after(attempt);
                assert!(
                    delay <= ceiling,
                    "attempt {attempts} drew {delay:?} past its {ceiling:?} ceiling"
                );
            }
        }
    }

    /// Full jitter draws from `[0, ceiling]`, so short waits are common. The half-jitter variant
    /// (`ceiling/2 + random(ceiling/2)`) never draws below half the ceiling, and would leave every
    /// replica that failed together still bunched into the same half-window. Over 512 draws the
    /// chance that none lands in the bottom tenth is about 1e-24, so this does not flake.
    #[test]
    fn the_jitter_reaches_down_to_short_waits_rather_than_only_the_top_half() {
        let policy = policy();
        let attempt = AttemptCount::from_row(4);
        let ceiling = policy.ceiling(attempt);
        let shortest = (0..512)
            .map(|_| policy.delay_after(attempt))
            .min()
            .expect("512 draws are not empty");
        assert!(
            shortest <= ceiling / 10,
            "the shortest of 512 draws was {shortest:?}, never near the bottom of {ceiling:?}"
        );
    }

    /// The cap has an upper bound, and every accepted policy produces a wait Postgres can add to a
    /// timestamp. Without the bound, `fail` would throw on the interval, and a failed `fail` leaves
    /// the chunk holding its lease in `scanning` rather than releasing it for retry.
    #[test]
    fn a_cap_wider_than_postgres_can_add_to_a_timestamp_is_refused() {
        for cap in [
            MAX_RETRY_BACKOFF_CAP + Duration::from_secs(1),
            Duration::from_secs(u64::MAX),
            Duration::MAX,
        ] {
            assert_eq!(
                RetryBackoffPolicy::new(Duration::from_secs(30), cap),
                Err(BackoffPolicyError::CapTooLarge),
                "{cap:?} was accepted"
            );
        }
        let widest =
            RetryBackoffPolicy::new(Duration::from_secs(30), MAX_RETRY_BACKOFF_CAP).unwrap();
        assert!(widest.delay_after(AttemptCount::from_row(64)) <= MAX_RETRY_BACKOFF_CAP);
    }

    #[test]
    fn a_policy_that_could_not_space_retries_is_rejected() {
        assert_eq!(
            RetryBackoffPolicy::new(Duration::ZERO, Duration::from_secs(1)),
            Err(BackoffPolicyError::ZeroBase)
        );
        assert_eq!(
            RetryBackoffPolicy::new(Duration::from_secs(30), Duration::from_secs(29)),
            Err(BackoffPolicyError::CapBelowBase)
        );
        // A cap equal to the base is a deliberate constant wait, not a misconfiguration.
        assert!(RetryBackoffPolicy::new(Duration::from_secs(30), Duration::from_secs(30)).is_ok());
    }
}
