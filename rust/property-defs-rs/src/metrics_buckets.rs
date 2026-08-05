//! Histogram bucket overrides for `property-defs-rs`.
//!
//! `common-metrics`' default ladder is millisecond-shaped and tops out at 10s, which suits the
//! per-chunk write timings. It does not suit `prop_defs_batch_acquire_time_ms`, which measures how
//! long the consumer waits for a batch to fill and is therefore bounded by `max_issue_period`
//! (500s in production), not by any database operation. Left on the default ladder its whole
//! distribution lands in the overflow bucket and no quantile over it is meaningful.
//!
//! Wired in at startup via `common_metrics::setup_metrics_routes_with_overrides`.
//!
//! One unit trap to know about: `http_requests_duration_seconds`, recorded by the
//! `common_metrics` axum middleware, observes seconds while the default ladder is
//! millisecond-shaped, so every sub-second request collapses into the first bucket. That is
//! harmless while this service's HTTP surface is only `/metrics` and the probes, but if a real
//! API endpoint ever ships here it needs a seconds-shaped override in this list.

use common_metrics::Matcher;

use crate::metrics_consts::{
    BATCH_ACQUIRE_TIME, V2_EVENT_DEFS_BATCH_WRITE_TIME, V2_EVENT_PROPS_BATCH_WRITE_TIME,
    V2_PROP_DEFS_BATCH_WRITE_TIME,
};

// Batch-acquire spans "the channel already had a full batch waiting" to "we sat here until
// max_issue_period expired", so the ladder has to cover sub-millisecond through the 500s
// production timeout. Coarse at the top: past a minute the only question is which order of
// magnitude.
const BATCH_ACQUIRE_BUCKETS_MS: &[f64] = &[
    1.0, 10.0, 100.0, 500.0, 1_000.0, 5_000.0, 10_000.0, 30_000.0, 60_000.0, 120_000.0, 300_000.0,
    600_000.0,
];

// Per-chunk write times run in the hundreds of milliseconds normally. The 30s ceiling leaves room
// for a stalled Postgres plus this path's three retries and their backoff, which the default 10s
// ceiling would swallow.
const BATCH_WRITE_BUCKETS_MS: &[f64] = &[
    1.0, 5.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1_000.0, 2_000.0, 5_000.0, 10_000.0, 30_000.0,
];

pub fn bucket_overrides() -> Vec<(Matcher, &'static [f64])> {
    vec![
        (
            Matcher::Full(BATCH_ACQUIRE_TIME.to_string()),
            BATCH_ACQUIRE_BUCKETS_MS,
        ),
        (
            Matcher::Full(V2_EVENT_DEFS_BATCH_WRITE_TIME.to_string()),
            BATCH_WRITE_BUCKETS_MS,
        ),
        (
            Matcher::Full(V2_EVENT_PROPS_BATCH_WRITE_TIME.to_string()),
            BATCH_WRITE_BUCKETS_MS,
        ),
        (
            Matcher::Full(V2_PROP_DEFS_BATCH_WRITE_TIME.to_string()),
            BATCH_WRITE_BUCKETS_MS,
        ),
    ]
}
