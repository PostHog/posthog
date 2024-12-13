pub const RUN_STARTS: &str = "cyclotron_janitor_run_starts";
pub const RUN_TIME: &str = "cyclotron_janitor_total_run_ms";
pub const RUN_ENDS: &str = "cyclotron_janitor_run_ends";

pub const COMPLETED_COUNT: &str = "cyclotron_janitor_completed_jobs";
pub const FAILED_COUNT: &str = "cyclotron_janitor_failed_jobs";
pub const CLEANUP_TIME: &str = "cyclotron_janitor_completed_failed_jobs_cleanup_ms";

pub const POISONED_COUNT: &str = "cyclotron_janitor_poison_pills";
pub const POISONED_TIME: &str = "cyclotron_janitor_poison_pills_cleanup_ms";

pub const STALLED_COUNT: &str = "cyclotron_janitor_stalled_jobs_reset";
pub const STALLED_TIME: &str = "cyclotron_janitor_stalled_jobs_reset_ms";

// The janitor should report some basic shard-level metrics
pub const AVAILABLE_DEPTH: &str = "cyclotron_available_jobs";
pub const AVAILABLE_DEPTH_TIME: &str = "cyclotron_available_jobs_ms";
pub const DLQ_DEPTH: &str = "cyclotron_dead_letter_queue_depth";
pub const DLQ_DEPTH_TIME: &str = "cyclotron_dead_letter_queue_depth_ms";
