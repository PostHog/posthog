pub const BACKOFF_EVENTS_TOTAL: &str = "batch_import_backoff_events_total";
pub const BACKOFF_DELAY_SECONDS: &str = "batch_import_backoff_delay_seconds";
pub const UNPAUSE_TOTAL: &str = "batch_import_unpause_total";
pub const STAGING_SWEEP_REMOVED: &str = "batch_import_staging_sweep_removed_total";
pub const STAGING_DIR_BYTES: &str = "batch_import_staging_dir_bytes";
pub const STAGING_GUARD_TRIPPED: &str = "batch_import_staging_guard_tripped_total";

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
