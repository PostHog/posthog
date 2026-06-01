//! Histogram bucket overrides for `feature-flags` metrics.
//!
//! The default bucket ladder in `common-metrics` tops out at 10s and starts
//! at 1ms — both are wrong for the queue/pre-handler family of metrics
//! (which can spike past 10s during proxy/permit-wait stalls) and for the
//! rate-limit / DB-connection family (which normally completes in well
//! under 1ms and gets bucket-floored otherwise).
//!
//! Wired into the metrics recorder at startup via
//! [`common_metrics::setup_metrics_routes_for_product_with_overrides`].

use common_metrics::Matcher;

// Queue-time class buckets (ms). 30s ceiling = ~6× `request_timeout_ms`
// (4_500 ms) so Envoy retries and proxy stalls remain visible above the
// previous 10s floor used as the "real number" estimate.
const QUEUE_TIME_BUCKETS_MS: &[f64] = &[
    1.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0, 15000.0, 30000.0,
];

// Sub-ms-aware buckets for DB pool acquire, governor rate-limit checks.
// These operations normally complete in < 1ms; the existing 1ms floor
// collapses the entire distribution into a single bucket.
const DB_CONNECTION_BUCKETS_MS: &[f64] = &[
    0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0,
];

const RATE_LIMIT_CHECK_BUCKETS_MS: &[f64] = &[
    0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1000.0,
];

// Token-extract scans the raw POST body. 5s ceiling captures pathological
// inputs without blowing up the bucket count.
const TOKEN_EXTRACT_BUCKETS_MS: &[f64] = &[
    0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 5000.0,
];

/// Returns the bucket-override matrix for the feature-flags recorder.
///
/// `Matcher::Suffix` is used for `_queue_time_ms` / `_pre_handler_time_ms`
/// so future per-component variants pick up the same buckets without an
/// extra entry. Any new metric in the feature-flags binary ending in
/// these suffixes will inherit these bucket boundaries — switch to
/// `Matcher::Full` if that is not desired. The other entries pin a
/// single metric name.
pub fn bucket_overrides() -> Vec<(Matcher, &'static [f64])> {
    vec![
        (
            Matcher::Suffix("_queue_time_ms".into()),
            QUEUE_TIME_BUCKETS_MS,
        ),
        (
            Matcher::Suffix("_pre_handler_time_ms".into()),
            QUEUE_TIME_BUCKETS_MS,
        ),
        (
            Matcher::Full("flags_concurrency_limit_wait_ms".into()),
            QUEUE_TIME_BUCKETS_MS,
        ),
        (
            Matcher::Full("flags_db_connection_time".into()),
            DB_CONNECTION_BUCKETS_MS,
        ),
        (
            Matcher::Full("flags_rate_limit_check_ms".into()),
            RATE_LIMIT_CHECK_BUCKETS_MS,
        ),
        (
            Matcher::Full("flags_token_extract_ms".into()),
            TOKEN_EXTRACT_BUCKETS_MS,
        ),
    ]
}
