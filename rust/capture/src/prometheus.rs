// prometheus exporter setup

use limiters::redis::QuotaResource;
use metrics::counter;
use metrics_exporter_prometheus::{Matcher, PrometheusBuilder, PrometheusHandle};

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
    const PAYLOAD_SIZES: &[f64] = &[
        1024.0,     // 1KB
        5120.0,     // 5KB
        10240.0,    // 10KB
        51200.0,    // 50KB
        102400.0,   // 100KB
        1048576.0,  // 1MB
        10485760.0, // 10MB
        20971520.0, // 20MB (cutoff for dropping analytics event payloads)
                    // backend will include Inf+ bucket
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
            Matcher::Suffix("capture_full_payload_size".to_string()),
            PAYLOAD_SIZES,
        )
        .unwrap()
        .install_recorder()
        .unwrap()
}
