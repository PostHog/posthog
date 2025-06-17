use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_metrics::inc;
use tracing::{info, warn};

use crate::metrics::consts::{
    CIRCUIT_BREAKER_CLOSED_COUNTER, CIRCUIT_BREAKER_HALF_OPEN_COUNTER, CIRCUIT_BREAKER_OPEN_COUNTER,
};

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum CircuitBreakerState {
    Closed,
    Open,
    HalfOpen,
}

#[derive(Debug, Clone, Copy)]
pub struct CircuitBreakerConfig {
    pub failure_threshold: usize,
    pub success_threshold: usize,
    pub timeout: Duration,
    pub max_calls_in_half_open: usize,
}

impl Default for CircuitBreakerConfig {
    fn default() -> Self {
        Self {
            failure_threshold: 10,
            success_threshold: 3,
            timeout: Duration::from_secs(60),
            max_calls_in_half_open: 5,
        }
    }
}

pub struct CircuitBreaker {
    config: CircuitBreakerConfig,
    state: AtomicUsize, // 0 = Closed, 1 = Open, 2 = HalfOpen
    failure_count: AtomicUsize,
    success_count: AtomicUsize,
    last_failure_time: AtomicU64,
    half_open_calls: AtomicUsize,
    name: String,
}

impl CircuitBreaker {
    pub fn new(name: String, config: CircuitBreakerConfig) -> Self {
        Self {
            config,
            state: AtomicUsize::new(0), // Start in Closed state
            failure_count: AtomicUsize::new(0),
            success_count: AtomicUsize::new(0),
            last_failure_time: AtomicU64::new(0),
            half_open_calls: AtomicUsize::new(0),
            name,
        }
    }

    pub fn can_execute(&self) -> bool {
        let current_state = self.get_state();

        match current_state {
            CircuitBreakerState::Closed => {
                inc(
                    CIRCUIT_BREAKER_CLOSED_COUNTER,
                    &[("name".to_string(), self.name.clone())],
                    1,
                );
                true
            }
            CircuitBreakerState::Open => {
                inc(
                    CIRCUIT_BREAKER_OPEN_COUNTER,
                    &[("name".to_string(), self.name.clone())],
                    1,
                );

                // Check if we should transition to half-open
                let last_failure = self.last_failure_time.load(Ordering::Relaxed);
                let now = Instant::now().elapsed().as_secs();

                if now - last_failure >= self.config.timeout.as_secs() {
                    self.state.store(2, Ordering::Relaxed); // Transition to HalfOpen
                    self.half_open_calls.store(0, Ordering::Relaxed);
                    info!(
                        "Circuit breaker '{}' transitioning from Open to Half-Open",
                        self.name
                    );
                    inc(
                        CIRCUIT_BREAKER_HALF_OPEN_COUNTER,
                        &[("name".to_string(), self.name.clone())],
                        1,
                    );
                    true
                } else {
                    false
                }
            }
            CircuitBreakerState::HalfOpen => {
                inc(
                    CIRCUIT_BREAKER_HALF_OPEN_COUNTER,
                    &[("name".to_string(), self.name.clone())],
                    1,
                );

                let current_calls = self.half_open_calls.load(Ordering::Relaxed);
                if current_calls < self.config.max_calls_in_half_open {
                    self.half_open_calls.fetch_add(1, Ordering::Relaxed);
                    true
                } else {
                    false
                }
            }
        }
    }

    pub fn record_success(&self) {
        let current_state = self.get_state();

        match current_state {
            CircuitBreakerState::Closed => {
                // Reset failure count on success
                self.failure_count.store(0, Ordering::Relaxed);
            }
            CircuitBreakerState::HalfOpen => {
                let success_count = self.success_count.fetch_add(1, Ordering::Relaxed) + 1;

                if success_count >= self.config.success_threshold {
                    // Transition back to Closed
                    self.state.store(0, Ordering::Relaxed);
                    self.failure_count.store(0, Ordering::Relaxed);
                    self.success_count.store(0, Ordering::Relaxed);
                    self.half_open_calls.store(0, Ordering::Relaxed);
                    info!(
                        "Circuit breaker '{}' transitioning from Half-Open to Closed",
                        self.name
                    );
                }
            }
            CircuitBreakerState::Open => {
                // Ignore successes in Open state
            }
        }
    }

    pub fn record_failure(&self) {
        let current_state = self.get_state();

        match current_state {
            CircuitBreakerState::Closed => {
                let failure_count = self.failure_count.fetch_add(1, Ordering::Relaxed) + 1;

                if failure_count >= self.config.failure_threshold {
                    // Transition to Open
                    self.state.store(1, Ordering::Relaxed);
                    self.last_failure_time
                        .store(Instant::now().elapsed().as_secs(), Ordering::Relaxed);
                    warn!(
                        "Circuit breaker '{}' transitioning from Closed to Open after {} failures",
                        self.name, failure_count
                    );
                }
            }
            CircuitBreakerState::HalfOpen => {
                // Any failure in half-open immediately goes back to open
                self.state.store(1, Ordering::Relaxed);
                self.failure_count.fetch_add(1, Ordering::Relaxed);
                self.success_count.store(0, Ordering::Relaxed);
                self.half_open_calls.store(0, Ordering::Relaxed);
                self.last_failure_time
                    .store(Instant::now().elapsed().as_secs(), Ordering::Relaxed);
                warn!(
                    "Circuit breaker '{}' transitioning from Half-Open to Open due to failure",
                    self.name
                );
            }
            CircuitBreakerState::Open => {
                // Count additional failures but stay open
                self.failure_count.fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    pub fn get_state(&self) -> CircuitBreakerState {
        match self.state.load(Ordering::Relaxed) {
            0 => CircuitBreakerState::Closed,
            1 => CircuitBreakerState::Open,
            2 => CircuitBreakerState::HalfOpen,
            _ => CircuitBreakerState::Closed, // Default fallback
        }
    }

    pub fn get_metrics(&self) -> CircuitBreakerMetrics {
        CircuitBreakerMetrics {
            state: self.get_state(),
            failure_count: self.failure_count.load(Ordering::Relaxed),
            success_count: self.success_count.load(Ordering::Relaxed),
            half_open_calls: self.half_open_calls.load(Ordering::Relaxed),
        }
    }
}

#[derive(Debug)]
pub struct CircuitBreakerMetrics {
    pub state: CircuitBreakerState,
    pub failure_count: usize,
    pub success_count: usize,
    pub half_open_calls: usize,
}

/// Wrapper for database operations with circuit breaker protection
pub struct DatabaseCircuitBreaker {
    person_query_breaker: Arc<CircuitBreaker>,
    group_query_breaker: Arc<CircuitBreaker>,
    cohort_query_breaker: Arc<CircuitBreaker>,
}

impl DatabaseCircuitBreaker {
    pub fn new() -> Self {
        let config = CircuitBreakerConfig {
            failure_threshold: 5,
            success_threshold: 3,
            timeout: Duration::from_secs(30),
            max_calls_in_half_open: 3,
        };

        Self {
            person_query_breaker: Arc::new(CircuitBreaker::new("person_query".to_string(), config)),
            group_query_breaker: Arc::new(CircuitBreaker::new("group_query".to_string(), config)),
            cohort_query_breaker: Arc::new(CircuitBreaker::new("cohort_query".to_string(), config)),
        }
    }

    pub fn person_query_breaker(&self) -> &Arc<CircuitBreaker> {
        &self.person_query_breaker
    }

    pub fn group_query_breaker(&self) -> &Arc<CircuitBreaker> {
        &self.group_query_breaker
    }

    pub fn cohort_query_breaker(&self) -> &Arc<CircuitBreaker> {
        &self.cohort_query_breaker
    }
}

impl Default for DatabaseCircuitBreaker {
    fn default() -> Self {
        Self::new()
    }
}
