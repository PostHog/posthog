//! A time budget for each `/process` batch, measured in `shadow` mode.
//!
//! The exception pipeline runs each stage over the whole batch before the next stage starts, so a
//! check at each stage boundary finds the stage that was running when the budget ran out. Linking
//! counts the events that get an issue after the budget ran out. An enforcing budget would return
//! the ones that had not yet taken their database connection to Node for a retry.

use std::time::{Duration, Instant};

use crate::{
    error::UnhandledError,
    metric_consts::{MAIN_LANE_BUDGET_EXCEEDED, MAIN_LANE_BUDGET_UNFINISHED_EVENTS},
    modes::processing::config::{shadow_enabled, ProcessingConfig},
};

pub fn budget_from_config(config: &ProcessingConfig) -> Result<Option<Duration>, UnhandledError> {
    if !shadow_enabled(
        "CYMBAL_MAIN_LANE_BUDGET_MODE",
        &config.main_lane_budget_mode,
    )? {
        return Ok(None);
    }
    if config.main_lane_budget_ms == 0 {
        return Err(UnhandledError::Other(
            "CYMBAL_MAIN_LANE_BUDGET_MS must be at least 1".to_string(),
        ));
    }
    Ok(Some(Duration::from_millis(config.main_lane_budget_ms)))
}

pub struct BatchBudget {
    deadline: Option<Instant>,
    exceeded: bool,
}

impl BatchBudget {
    pub fn start(budget: Option<Duration>) -> Self {
        Self::start_at(budget, Instant::now())
    }

    fn start_at(budget: Option<Duration>, now: Instant) -> Self {
        Self {
            deadline: budget.map(|budget| now + budget),
            exceeded: false,
        }
    }

    pub fn deadline(&self) -> Option<Instant> {
        self.deadline
    }

    pub fn end_stage(&mut self, stage: &'static str) {
        if self.deadline.is_some() && !self.exceeded && self.ran_out_at(Instant::now()) {
            metrics::counter!(MAIN_LANE_BUDGET_EXCEEDED, "stage" => stage).increment(1);
        }
    }

    /// True only at the first stage boundary after the deadline.
    fn ran_out_at(&mut self, now: Instant) -> bool {
        if self.exceeded || !is_spent(self.deadline, now) {
            return false;
        }
        self.exceeded = true;
        true
    }
}

pub fn record_linked_event(deadline: Option<Instant>) {
    if deadline.is_some() && is_spent(deadline, Instant::now()) {
        metrics::counter!(MAIN_LANE_BUDGET_UNFINISHED_EVENTS).increment(1);
    }
}

fn is_spent(deadline: Option<Instant>, now: Instant) -> bool {
    deadline.is_some_and(|deadline| now >= deadline)
}

#[cfg(test)]
mod tests {
    use super::*;

    const BUDGET: Duration = Duration::from_millis(100);

    #[test]
    fn the_first_boundary_after_the_deadline_names_the_stage_once() {
        let start = Instant::now();
        let mut budget = BatchBudget::start_at(Some(BUDGET), start);

        assert!(!budget.ran_out_at(start + BUDGET / 2));
        assert!(budget.ran_out_at(start + BUDGET));
        assert!(
            !budget.ran_out_at(start + BUDGET * 2),
            "a batch reported its budget twice"
        );
    }

    #[test]
    fn a_batch_without_a_budget_never_reports() {
        let start = Instant::now();
        let mut budget = BatchBudget::start_at(None, start);

        assert!(!budget.ran_out_at(start + BUDGET * 100));
    }
}
