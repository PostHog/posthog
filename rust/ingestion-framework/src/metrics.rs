//! Metric names and labels match the Node side, so one dashboard reads both.

use std::sync::Arc;

pub const SIDE_EFFECT_RESULT_COUNTER: &str = "pipelines_side_effects_total";
pub const PIPELINE_STEP_DURATION_HISTOGRAM: &str = "ingestion_pipeline_step_duration_seconds";
pub const PIPELINE_RETRY_ATTEMPTS_HISTOGRAM: &str = "ingestion_pipeline_retry_attempts";
pub const BATCH_BUDGET_EXHAUSTED_COUNTER: &str = "ingestion_batch_budget_exhausted_total";
pub const BATCH_BUDGET_OVERRUN_HISTOGRAM: &str = "ingestion_batch_budget_overrun_seconds";
pub const BATCH_BUDGET_CHECKPOINT_COUNTER: &str = "ingestion_batch_budget_checkpoint_total";
pub const INGESTION_PIPELINE_RESULTS_COUNTER: &str = "ingestion_pipeline_results";
pub const INGESTION_WARNING_COUNTER: &str = "ingestion_warnings_total";

#[derive(Debug, Clone, Copy)]
pub enum BudgetCheckpoint {
    Step,
    Chunk,
}

impl BudgetCheckpoint {
    fn label(self) -> &'static str {
        match self {
            BudgetCheckpoint::Step => "step",
            BudgetCheckpoint::Chunk => "chunk",
        }
    }
}

pub fn record_budget_checkpoint(checkpoint: BudgetCheckpoint, step_name: Arc<str>) {
    metrics::counter!(
        BATCH_BUDGET_CHECKPOINT_COUNTER,
        "checkpoint" => checkpoint.label(),
        "step_name" => step_name
    )
    .increment(1);
}

pub fn record_step_duration(
    step_name: Arc<str>,
    step_type: &'static str,
    result: &'static str,
    seconds: f64,
) {
    metrics::histogram!(
        PIPELINE_STEP_DURATION_HISTOGRAM,
        "step_name" => step_name,
        "step_type" => step_type,
        "result" => result
    )
    .record(seconds);
}

pub fn record_side_effect_result(ok: bool) {
    metrics::counter!(SIDE_EFFECT_RESULT_COUNTER, "result" => if ok { "ok" } else { "error" })
        .increment(1);
}

pub fn record_retry_attempts(name: Arc<str>, outcome: &'static str, attempts: u32) {
    metrics::histogram!(
        PIPELINE_RETRY_ATTEMPTS_HISTOGRAM,
        "name" => name,
        "outcome" => outcome
    )
    .record(attempts as f64);
}
