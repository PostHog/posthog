// prometheus exporter setup

use limiters::redis::QuotaResource;
use metrics::counter;
use metrics_exporter_prometheus::{Matcher, PrometheusBuilder, PrometheusHandle};

use crate::metrics_middleware::METRIC_CAPTURE_REQUEST_SIZE_BYTES;

pub const CAPTURE_EVENTS_DROPPED_TOTAL: &str = "capture_events_dropped_total";

pub fn report_dropped_events(cause: &'static str, quantity: u64) {
    counter!(CAPTURE_EVENTS_DROPPED_TOTAL, "cause" => cause).increment(quantity);
}

pub fn report_overflow_partition(quantity: u64) {
    counter!("capture_partition_key_capacity_exceeded_total").increment(quantity);
}

pub fn report_quota_limit_exceeded(resource: &QuotaResource, quantity: u64) {
    counter!("capture_quota_limit_exceeded", "resource" => resource.as_str()).increment(quantity);
}

pub fn report_internal_error_metrics(
    err_type: &'static str,
    stage_tag: &'static str,
    capture_mode: &'static str,
) {
    let tags = [
        ("error", err_type),
        ("stage", stage_tag),
        ("mode", capture_mode),
    ];
    counter!("capture_error_by_stage_and_type", &tags).increment(1);
}

pub fn setup_metrics_recorder() -> PrometheusHandle {
    // Ok I broke it at the end, but the limit on our ingress is 60 and that's a nicer way of reaching it
    const EXPONENTIAL_SECONDS: &[f64] = &[
        0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0,
    ];
    const BATCH_SIZES: &[f64] = &[
        1.0, 10.0, 25.0, 50.0, 75.0, 100.0, 250.0, 500.0, 750.0, 1000.0,
    ];
    // Buckets for request content-length in bytes (1KB to 20MB)
    const REQUEST_SIZE_BYTES: &[f64] = &[
        1024.0,       // 1 KB
        10_240.0,     // 10 KB
        102_400.0,    // 100 KB
        512_000.0,    // 500 KB
        1_048_576.0,  // 1 MB
        5_242_880.0,  // 5 MB
        10_485_760.0, // 10 MB
        20_971_520.0, // 20 MB
        52_428_800.0, // 50 MB (for edge cases)
    ];

    PrometheusBuilder::new()
        .set_buckets_for_metric(
            Matcher::Full("http_requests_duration_seconds".to_string()),
            EXPONENTIAL_SECONDS,
        )
        .unwrap()
        .set_buckets_for_metric(Matcher::Suffix("_batch_size".to_string()), BATCH_SIZES)
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full(METRIC_CAPTURE_REQUEST_SIZE_BYTES.to_string()),
            REQUEST_SIZE_BYTES,
        )
        .unwrap()
        .install_recorder()
        .unwrap()
}
