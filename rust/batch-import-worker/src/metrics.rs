pub const BACKOFF_EVENTS_TOTAL: &str = "batch_import_backoff_events_total";
pub const BACKOFF_DELAY_SECONDS: &str = "batch_import_backoff_delay_seconds";
pub const UNPAUSE_TOTAL: &str = "batch_import_unpause_total";
pub const STAGING_SWEEP_REMOVED: &str = "batch_import_staging_sweep_removed_total";
pub const STAGING_DIR_BYTES: &str = "batch_import_staging_dir_bytes";
pub const STAGING_GUARD_TRIPPED: &str = "batch_import_staging_guard_tripped_total";
pub const ACTIVE_JOBS: &str = "batch_import_active_jobs";
pub const TEMP_BUCKET_STAGE_BYTES: &str = "batch_import_temp_bucket_stage_bytes";
pub const TEMP_BUCKET_STAGE_DURATION_SECONDS: &str =
    "batch_import_temp_bucket_stage_duration_seconds";
pub const TEMP_BUCKET_READ_DURATION_SECONDS: &str =
    "batch_import_temp_bucket_read_duration_seconds";
pub const STAGED_PLAINTEXT_CEILING_TRIPPED: &str =
    "batch_import_staged_plaintext_ceiling_tripped_total";
pub const PART_CLEANUP_TOTAL: &str = "batch_import_part_cleanup_total";

use metrics::{counter, gauge, histogram};

pub fn backoff_event(delay_secs: f64) {
    counter!(BACKOFF_EVENTS_TOTAL).increment(1);
    histogram!(BACKOFF_DELAY_SECONDS).record(delay_secs);
}

pub fn unpause_event() {
    counter!(UNPAUSE_TOTAL).increment(1);
}

pub fn staging_sweep_removed(count: u64) {
    counter!(STAGING_SWEEP_REMOVED).increment(count);
}

pub fn staging_dir_bytes(bytes: f64) {
    gauge!(STAGING_DIR_BYTES).set(bytes);
}

pub fn staging_guard_tripped() {
    counter!(STAGING_GUARD_TRIPPED).increment(1);
}

/// Number of batch import jobs currently needing a worker (queued and in-flight).
/// Reported by every replica off the shared Postgres queue; the KEDA autoscaler
/// collapses the per-pod duplicates with `max()` to drive replica count.
pub fn active_jobs(count: f64) {
    gauge!(ACTIVE_JOBS).set(count);
}

/// Record a completed temp-bucket part upload: total bytes staged and wall-clock duration.
pub fn temp_bucket_part_staged(bytes: u64, duration_secs: f64) {
    histogram!(TEMP_BUCKET_STAGE_BYTES).record(bytes as f64);
    histogram!(TEMP_BUCKET_STAGE_DURATION_SECONDS).record(duration_secs);
}

/// Record the latency of a single ranged GET against the temp bucket.
pub fn temp_bucket_read(duration_secs: f64) {
    histogram!(TEMP_BUCKET_READ_DURATION_SECONDS).record(duration_secs);
}

/// Count a part that breached STAGED_PLAINTEXT_MAX_BYTES and paused the job.
pub fn staged_plaintext_ceiling_tripped() {
    counter!(STAGED_PLAINTEXT_CEILING_TRIPPED).increment(1);
}

/// Count post-commit staging cleanup of a completed part, by outcome ("ok" / "error").
/// A failed cleanup leaks only transient storage (reclaimed by job cleanup / bucket TTL).
pub fn part_cleanup(outcome: &'static str) {
    counter!(PART_CLEANUP_TOTAL, "outcome" => outcome).increment(1);
}
