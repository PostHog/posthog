//! Generic circuit-breaker state machine primitives.
//!
//! This module intentionally contains only reusable state and decisions. It has
//! no endpoint storage, server transport code, metrics, or tracing labels; callers
//! own those concerns and can emit side effects from the returned transition data.

use std::collections::hash_map::DefaultHasher;
use std::collections::VecDeque;
use std::hash::{Hash, Hasher};
use std::time::{Duration, Instant};

pub const DEFAULT_CIRCUIT_WINDOW_SIZE: usize = 10;
pub const DEFAULT_CIRCUIT_MIN_REQUESTS: usize = 5;
pub const DEFAULT_CIRCUIT_FAILURE_RATIO_TO_OPEN: f64 = 0.5;
pub const DEFAULT_CIRCUIT_OPEN_DURATION: Duration = Duration::from_secs(10);

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CircuitBreakerConfig {
    pub window_size: usize,
    pub min_requests: usize,
    pub failure_ratio_to_open: f64,
    pub open_duration: Duration,
}

impl Default for CircuitBreakerConfig {
    fn default() -> Self {
        Self {
            window_size: DEFAULT_CIRCUIT_WINDOW_SIZE,
            min_requests: DEFAULT_CIRCUIT_MIN_REQUESTS,
            failure_ratio_to_open: DEFAULT_CIRCUIT_FAILURE_RATIO_TO_OPEN,
            open_duration: DEFAULT_CIRCUIT_OPEN_DURATION,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CircuitState {
    Closed,
    Open { opened_at: Instant },
    HalfOpen,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CircuitDecision {
    Allow,
    Reject { retry_after_ms: u64 },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CircuitTransition {
    pub previous: CircuitState,
    pub current: CircuitState,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CircuitCheckResult {
    pub decision: CircuitDecision,
    pub transition: Option<CircuitTransition>,
    pub state: CircuitState,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CircuitRecordResult {
    pub transition: Option<CircuitTransition>,
    pub state: CircuitState,
    pub opened: bool,
    pub window_len: usize,
    pub failures: usize,
}

#[derive(Debug, Clone)]
pub struct CircuitBreaker {
    config: CircuitBreakerConfig,
    state: CircuitState,
    outcomes: VecDeque<bool>,
}

impl CircuitBreaker {
    pub fn new(config: CircuitBreakerConfig) -> Self {
        Self {
            config,
            state: CircuitState::Closed,
            outcomes: VecDeque::with_capacity(config.window_size),
        }
    }

    pub fn state(&self) -> CircuitState {
        self.state
    }

    pub fn window_len(&self) -> usize {
        self.outcomes.len()
    }

    pub fn failures(&self) -> usize {
        self.failure_count()
    }

    pub fn check(&mut self, now: Instant, retry_key: &str) -> CircuitCheckResult {
        let transition = match self.state {
            CircuitState::Closed => None,
            CircuitState::HalfOpen => {
                return CircuitCheckResult {
                    decision: CircuitDecision::Reject {
                        retry_after_ms: deterministic_retry_after_ms(retry_key, "half_open"),
                    },
                    transition: None,
                    state: self.state,
                };
            }
            CircuitState::Open { opened_at } => {
                if now.saturating_duration_since(opened_at) >= self.config.open_duration {
                    self.transition_to(CircuitState::HalfOpen)
                } else {
                    return CircuitCheckResult {
                        decision: CircuitDecision::Reject {
                            retry_after_ms: deterministic_retry_after_ms(retry_key, "open"),
                        },
                        transition: None,
                        state: self.state,
                    };
                }
            }
        };

        CircuitCheckResult {
            decision: CircuitDecision::Allow,
            transition,
            state: self.state,
        }
    }

    pub fn record_success(&mut self) -> CircuitRecordResult {
        self.push_outcome(false);
        let transition = if matches!(self.state, CircuitState::HalfOpen) {
            let transition = self.transition_to(CircuitState::Closed);
            self.outcomes.clear();
            transition
        } else {
            None
        };

        self.record_result(transition, false)
    }

    pub fn record_failure(&mut self, now: Instant) -> CircuitRecordResult {
        self.push_outcome(true);
        if matches!(self.state, CircuitState::HalfOpen) {
            let transition = self.transition_to(CircuitState::Open { opened_at: now });
            return self.record_result(transition, true);
        }

        if matches!(self.state, CircuitState::Closed) && self.should_open() {
            let transition = self.transition_to(CircuitState::Open { opened_at: now });
            return self.record_result(transition, true);
        }

        self.record_result(None, false)
    }

    fn push_outcome(&mut self, failed: bool) {
        if self.config.window_size == 0 {
            return;
        }
        if self.outcomes.len() == self.config.window_size {
            self.outcomes.pop_front();
        }
        self.outcomes.push_back(failed);
    }

    fn should_open(&self) -> bool {
        if self.config.min_requests == 0 || self.outcomes.len() < self.config.min_requests {
            return false;
        }
        let failures = self.failure_count();
        failures as f64 / self.outcomes.len() as f64 >= self.config.failure_ratio_to_open
    }

    fn failure_count(&self) -> usize {
        self.outcomes.iter().filter(|failed| **failed).count()
    }

    fn transition_to(&mut self, current: CircuitState) -> Option<CircuitTransition> {
        let previous = self.state;
        if previous == current {
            return None;
        }
        self.state = current;
        Some(CircuitTransition { previous, current })
    }

    fn record_result(
        &self,
        transition: Option<CircuitTransition>,
        opened: bool,
    ) -> CircuitRecordResult {
        CircuitRecordResult {
            transition,
            state: self.state,
            opened,
            window_len: self.outcomes.len(),
            failures: self.failure_count(),
        }
    }
}

impl Default for CircuitBreaker {
    fn default() -> Self {
        Self::new(CircuitBreakerConfig::default())
    }
}

pub fn deterministic_retry_after_ms(item_id: &str, reason: &str) -> u64 {
    let mut hasher = DefaultHasher::new();
    item_id.hash(&mut hasher);
    reason.hash(&mut hasher);
    1_000 + (hasher.finish() % 1_000)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config() -> CircuitBreakerConfig {
        CircuitBreakerConfig {
            window_size: 4,
            min_requests: 4,
            failure_ratio_to_open: 0.5,
            open_duration: Duration::from_secs(10),
        }
    }

    #[test]
    fn closed_opens_half_opens_and_closes_without_sleeping() {
        let start = Instant::now();
        let mut circuit = CircuitBreaker::new(config());

        assert_eq!(circuit.record_success().state, CircuitState::Closed);
        assert_eq!(circuit.record_failure(start).state, CircuitState::Closed);
        assert_eq!(circuit.record_success().state, CircuitState::Closed);
        let opened = circuit.record_failure(start);

        assert!(opened.opened);
        assert_eq!(opened.failures, 2);
        assert!(matches!(opened.state, CircuitState::Open { .. }));
        assert!(matches!(
            circuit
                .check(start + Duration::from_secs(1), "endpoint")
                .decision,
            CircuitDecision::Reject { .. }
        ));

        let half_open = circuit.check(start + Duration::from_secs(10), "endpoint");
        assert_eq!(half_open.decision, CircuitDecision::Allow);
        assert_eq!(half_open.state, CircuitState::HalfOpen);
        assert!(matches!(
            half_open.transition,
            Some(CircuitTransition {
                previous: CircuitState::Open { .. },
                current: CircuitState::HalfOpen,
            })
        ));

        let closed = circuit.record_success();
        assert_eq!(closed.state, CircuitState::Closed);
        assert_eq!(closed.window_len, 0);
        assert!(matches!(
            closed.transition,
            Some(CircuitTransition {
                previous: CircuitState::HalfOpen,
                current: CircuitState::Closed,
            })
        ));
    }

    #[test]
    fn half_open_failure_reopens() {
        let start = Instant::now();
        let mut circuit = CircuitBreaker::new(config());
        for _ in 0..4 {
            circuit.record_failure(start);
        }
        assert!(matches!(circuit.state(), CircuitState::Open { .. }));
        assert_eq!(
            circuit
                .check(start + Duration::from_secs(10), "endpoint")
                .decision,
            CircuitDecision::Allow
        );

        let reopened = circuit.record_failure(start + Duration::from_secs(11));

        assert!(reopened.opened);
        assert!(matches!(reopened.state, CircuitState::Open { .. }));
        assert!(matches!(
            reopened.transition,
            Some(CircuitTransition {
                previous: CircuitState::HalfOpen,
                current: CircuitState::Open { .. },
            })
        ));
    }

    #[test]
    fn retry_after_is_deterministic_and_reason_scoped() {
        assert_eq!(
            deterministic_retry_after_ms("endpoint", "open"),
            deterministic_retry_after_ms("endpoint", "open")
        );
        assert_ne!(
            deterministic_retry_after_ms("endpoint", "open"),
            deterministic_retry_after_ms("endpoint", "half_open")
        );
    }

    #[test]
    fn open_and_half_open_rejections_include_retry_after() {
        let start = Instant::now();
        let mut circuit = CircuitBreaker::new(config());
        for _ in 0..4 {
            circuit.record_failure(start);
        }

        assert_eq!(
            circuit.check(start + Duration::from_secs(1), "endpoint"),
            CircuitCheckResult {
                decision: CircuitDecision::Reject {
                    retry_after_ms: deterministic_retry_after_ms("endpoint", "open"),
                },
                transition: None,
                state: circuit.state(),
            }
        );
        assert_eq!(
            circuit
                .check(start + Duration::from_secs(10), "endpoint")
                .decision,
            CircuitDecision::Allow
        );
        assert_eq!(
            circuit.check(start + Duration::from_secs(10), "endpoint"),
            CircuitCheckResult {
                decision: CircuitDecision::Reject {
                    retry_after_ms: deterministic_retry_after_ms("endpoint", "half_open"),
                },
                transition: None,
                state: CircuitState::HalfOpen,
            }
        );
    }
}
