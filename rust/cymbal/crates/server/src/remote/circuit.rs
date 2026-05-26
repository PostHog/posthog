//! Per-endpoint circuit breaker wrapper for remote stages.
//!
//! Generic circuit state and decisions live in `cymbal-core`. This module keeps
//! the server-specific side effects: remote metric names, tracing labels, and
//! endpoint-target labeling.

use std::time::Instant;

use cymbal_core::{
    deterministic_retry_after_ms, CircuitBreaker, CircuitBreakerConfig, CircuitDecision,
    CircuitRecordResult, CircuitState,
};

use crate::observability::{REMOTE_CIRCUIT_OPENED, REMOTE_CIRCUIT_STATE};

pub(super) const CIRCUIT_WINDOW_SIZE: usize = cymbal_core::DEFAULT_CIRCUIT_WINDOW_SIZE;
pub(super) const CIRCUIT_MIN_REQUESTS: usize = cymbal_core::DEFAULT_CIRCUIT_MIN_REQUESTS;
pub(super) const CIRCUIT_FAILURE_RATIO_TO_OPEN: f64 =
    cymbal_core::DEFAULT_CIRCUIT_FAILURE_RATIO_TO_OPEN;
pub(super) const CIRCUIT_OPEN_DURATION: std::time::Duration =
    cymbal_core::DEFAULT_CIRCUIT_OPEN_DURATION;

#[derive(Debug, Clone)]
pub(super) struct RemoteTargetCircuit {
    circuit: CircuitBreaker,
}

impl RemoteTargetCircuit {
    pub(super) fn new() -> Self {
        Self {
            circuit: CircuitBreaker::new(CircuitBreakerConfig {
                window_size: CIRCUIT_WINDOW_SIZE,
                min_requests: CIRCUIT_MIN_REQUESTS,
                failure_ratio_to_open: CIRCUIT_FAILURE_RATIO_TO_OPEN,
                open_duration: CIRCUIT_OPEN_DURATION,
            }),
        }
    }

    pub(super) fn retry_after_ms(&mut self, target_name: &str) -> Option<u64> {
        let check = self.circuit.check(Instant::now(), target_name);
        if check.transition.is_some() {
            self.record_state(target_name);
        }

        match check.decision {
            CircuitDecision::Allow => None,
            CircuitDecision::Reject { retry_after_ms } => Some(retry_after_ms),
        }
    }

    pub(super) fn record_success(&mut self, target_name: &str) {
        self.circuit.record_success();
        self.record_state(target_name);
    }

    pub(super) fn record_failure(&mut self, target_name: &str, reason: &'static str) {
        let result = self.circuit.record_failure(Instant::now());
        if result.opened {
            self.record_opened(target_name, reason, result);
            return;
        }

        self.record_state(target_name);
    }

    fn record_opened(&self, target_name: &str, reason: &'static str, result: CircuitRecordResult) {
        self.record_state(target_name);
        metrics::counter!(REMOTE_CIRCUIT_OPENED, "target" => target_name.to_string(), "reason" => reason)
            .increment(1);
        tracing::warn!(
            target = target_name,
            reason,
            window = result.window_len,
            failures = result.failures,
            "remote stage circuit opened"
        );
    }

    pub(super) fn record_state(&self, target_name: &str) {
        metrics::gauge!(REMOTE_CIRCUIT_STATE, "target" => target_name.to_string())
            .set(metric_value(self.circuit.state()));
    }
}

fn metric_value(state: CircuitState) -> f64 {
    match state {
        CircuitState::Closed => 0.0,
        CircuitState::Open { .. } => 1.0,
        CircuitState::HalfOpen => 2.0,
    }
}

pub(crate) fn jittered_retry_after_ms(item_id: &str, reason: &str) -> u64 {
    deterministic_retry_after_ms(item_id, reason)
}
