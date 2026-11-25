use chrono::{DateTime, TimeDelta, Utc};
use parking_lot::RwLock;

/// Time source shared by topic transitions, workers and schedules.
pub trait Clock: Send + Sync {
    /// Current UTC time.
    fn now(&self) -> DateTime<Utc>;
    /// Whether to drive workers automatically. Manual clocks advance through `Engine::tick`.
    fn automatic(&self) -> bool {
        true
    }
}

/// Real UTC time with automatic worker ticks.
#[derive(Default)]
pub struct SystemClock;
impl Clock for SystemClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
}

/// Explicit time for deterministic, sleep-free worker and schedule tests.
pub struct ManualClock(RwLock<DateTime<Utc>>);
impl ManualClock {
    /// Starts time at the given instant.
    pub fn new(now: DateTime<Utc>) -> Self {
        Self(RwLock::new(now))
    }
    /// Advances the observed time. Call `Engine::tick` to run due work.
    pub fn advance(&self, by: TimeDelta) {
        *self.0.write() += by;
    }
}
impl Clock for ManualClock {
    fn now(&self) -> DateTime<Utc> {
        *self.0.read()
    }
    fn automatic(&self) -> bool {
        false
    }
}
