pub const BACKOFF_EVENTS_TOTAL: &str = "batch_import_backoff_events_total";
pub const BACKOFF_DELAY_SECONDS: &str = "batch_import_backoff_delay_seconds";
pub const UNPAUSE_TOTAL: &str = "batch_import_unpause_total";

use metrics::{counter, histogram};

pub fn backoff_event(delay_secs: f64) {
    counter!(BACKOFF_EVENTS_TOTAL).increment(1);
    histogram!(BACKOFF_DELAY_SECONDS).record(delay_secs);
}

pub fn unpause_event() {
    counter!(UNPAUSE_TOTAL).increment(1);
}
