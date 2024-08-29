// Metric names
pub const WORKER_SAT: &str = "cyclotron_fetch_worker_available_permits";
pub const WORKER_DEQUEUED: &str = "cyclotron_fetch_worker_dequeued_jobs";
pub const DEQUEUE_TIME: &str = "cyclotron_fetch_dequeue_ms";
pub const SPAWN_TIME: &str = "cyclotron_fetch_spawn_tasks_ms";
pub const JOB_TOTAL_TIME: &str = "cyclotron_fetch_job_total_run_ms";
pub const JOB_INITIAL_REQUEST_TIME: &str = "cyclotron_fetch_job_initial_request_ms";
pub const BODY_FETCH_TIME: &str = "cyclotron_fetch_body_fetch_ms";
pub const FETCH_JOB_ERRORS: &str = "cyclotron_fetch_job_errors";
pub const FETCH_JOBS_COMPLETED: &str = "cyclotron_fetch_jobs_completed";
pub const FETCH_DEAD_LETTER: &str = "cyclotron_fetch_dead_letter";
pub const RESPONSE_RECEIVED: &str = "cyclotron_fetch_got_response";
pub const BODY_FETCH_FAILED: &str = "cyclotron_fetch_body_fetch_failed";
pub const BODY_FETCH_SUCCEEDED: &str = "cyclotron_fetch_body_fetch_succeeded";

// Label keys
pub const OUTCOME_LABEL: &str = "outcome";
pub const RESPONSE_STATUS_LABEL: &str = "response_status";
