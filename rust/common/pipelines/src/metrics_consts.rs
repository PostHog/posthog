//! Metric name constants, kept in one place so the vocabulary stays aligned
//! with the Node framework's `ingestion_pipeline_results` family.

/// Per-verdict counter emitted by the built-in metrics observer.
/// Labels: `result` (ok/drop/dlq/redirect), `last_step_name`, `details`.
pub const PIPELINE_RESULTS: &str = "ingestion_pipeline_results";

/// Incremented when a `fail_open`-wrapped step swallows an error/panic and
/// passes the event through unchanged. Label: `step_name`.
pub const STEP_FAIL_OPEN: &str = "pipeline_step_fail_open_total";

/// Counter for DLQ produce failures in result handling (best-effort path).
pub const DLQ_PRODUCE_ERRORS: &str = "ingestion_pipeline_dlq_produce_errors_total";

/// Counter for redirect produce failures in result handling.
pub const REDIRECT_PRODUCE_ERRORS: &str = "ingestion_pipeline_redirect_produce_errors_total";
