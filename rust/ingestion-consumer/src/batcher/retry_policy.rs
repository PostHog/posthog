//! When each kind of retry fires.

use std::time::{Duration, Instant};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RetryReason {
    Fault,
    Busy,
    /// Nothing signals a worker joining the pool, so placement polls for one.
    NoWorker,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RetryPolicy {
    fault: Duration,
    busy: Duration,
    no_worker: Duration,
}

impl RetryPolicy {
    pub fn new(fault: Duration, busy: Duration, no_worker: Duration) -> Result<Self, String> {
        // Zero would wake the state machine on every action.
        if no_worker.is_zero() {
            return Err("the no-worker retry delay must be > 0".to_string());
        }
        Ok(Self {
            fault,
            busy,
            no_worker,
        })
    }

    pub fn uniform(delay: Duration) -> Result<Self, String> {
        Self::new(delay, delay, delay)
    }

    pub fn retry_at(&self, now: Instant, reason: RetryReason) -> Instant {
        let delay = match reason {
            RetryReason::Fault => self.fault,
            RetryReason::Busy => self.busy,
            RetryReason::NoWorker => self.no_worker,
        };
        now + delay
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_zero_no_worker_delay_is_rejected() {
        assert!(RetryPolicy::uniform(Duration::ZERO).is_err());
    }
}
