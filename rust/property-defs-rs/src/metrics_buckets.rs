//! Histogram bucket overrides for `property-defs-rs`.
//!
//! `common-metrics`' default ladder is millisecond-shaped and tops out at 10s, which suits the
//! per-chunk write timings. It does not suit `prop_defs_batch_acquire_time_ms`, which measures how
//! long the consumer waits for a batch to fill and is therefore bounded by `max_issue_period`,
//! not by any database operation. Deploys raise that well above the in-code default, so the
//! ceiling here is sized against the deployed value rather than the default. Left on the default
//! ladder its whole distribution lands in the overflow bucket and no quantile over it is
//! meaningful.
//!
//! Wired in at startup via `common_metrics::setup_metrics_routes_with_overrides`.
//!
//! One unit trap to know about: `http_requests_duration_seconds`, recorded by the
//! `common_metrics` axum middleware, observes seconds while the default ladder is
//! millisecond-shaped, so every sub-second request collapses into the first bucket. This already
//! applies to the `/api/v1/projects/:project_id/property_definitions` route mounted in `main`, so
//! any quantile over that endpoint is meaningless until a seconds-shaped override is added here.
//! It has not mattered so far because the endpoint serves no production traffic.

use common_metrics::Matcher;

use crate::metrics_consts::{
    BATCH_ACQUIRE_TIME, UPDATES_PER_EVENT, V2_EVENT_DEFS_BATCH_WRITE_TIME,
    V2_EVENT_PROPS_BATCH_WRITE_TIME, V2_PROP_DEFS_BATCH_WRITE_TIME,
};

// Batch-acquire spans "the channel already had a full batch waiting" to "we sat here until
// max_issue_period expired", so the ladder has to cover milliseconds through that timeout.
// Boundaries step by roughly 2x rather than clustering anywhere, because this wait tracks arrival
// rate and consumer lag: it moves by an order of magnitude between quiet and backlogged periods,
// so a ladder centered on any one operating point loses resolution as soon as load shifts.
// It does not resolve below a millisecond: `timing_guard` truncates to integer milliseconds, so
// a wait shorter than that records 0.0 regardless of the first boundary.
const BATCH_ACQUIRE_BUCKETS_MS: &[f64] = &[
    100.0, 250.0, 500.0, 1_000.0, 2_000.0, 4_000.0, 8_000.0, 15_000.0, 25_000.0, 40_000.0,
    60_000.0, 120_000.0, 300_000.0, 600_000.0,
];

// Per-chunk write times run in the hundreds of milliseconds normally. The 30s ceiling leaves room
// for a stalled Postgres plus this path's three retries and their backoff, which the default 10s
// ceiling would swallow.
const BATCH_WRITE_BUCKETS_MS: &[f64] = &[
    1.0, 5.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1_000.0, 2_000.0, 5_000.0, 10_000.0, 30_000.0,
];

// Updates per event is a count, not a duration, so the millisecond ladder does not fit it.
// An event fans out to roughly two updates per property, so the bulk of the distribution sits in
// the low hundreds and the tail runs into the thousands for property-heavy senders. Resolution is
// concentrated there rather than in the single digits, which only a near-empty event reaches.
// The top boundary matches update_count_skip_threshold (10000 by default). An event above that
// threshold yields no updates at all, and the histogram records that as a zero rather than a
// large value, so no sample ever lands above the top boundary.
const UPDATES_PER_EVENT_BUCKETS: &[f64] = &[
    1.0, 5.0, 25.0, 50.0, 100.0, 150.0, 200.0, 300.0, 500.0, 750.0, 1_000.0, 2_000.0, 3_000.0,
    5_000.0, 10_000.0,
];

pub fn bucket_overrides() -> Vec<(Matcher, &'static [f64])> {
    vec![
        (
            Matcher::Full(BATCH_ACQUIRE_TIME.to_string()),
            BATCH_ACQUIRE_BUCKETS_MS,
        ),
        (
            Matcher::Full(UPDATES_PER_EVENT.to_string()),
            UPDATES_PER_EVENT_BUCKETS,
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
