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

pub fn report_internal_error_metrics(err_type: &'static str, stage_tag: &'static str) {
    let tags = [("error", err_type), ("stage", stage_tag)];
    counter!("capture_error_by_stage_and_type", &tags).increment(1);
}

pub fn setup_metrics_recorder(role: String, capture_mode: &'static str) -> PrometheusHandle {
    // Ok I broke it at the end, but the limit on our ingress is 60 and that's a nicer way of reaching it
    const EXPONENTIAL_SECONDS: &[f64] = &[
        0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0,
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
    // S3 upload latency buckets (in seconds, 2x increments)
    const S3_LATENCY_SECONDS: &[f64] = &[
        0.01,  // 10ms
        0.02,  // 20ms
        0.04,  // 40ms
        0.08,  // 80ms
        0.16,  // 160ms
        0.32,  // 320ms
        0.64,  // 640ms
        1.28,  // 1.28s
        2.56,  // 2.56s
        5.12,  // 5.12s
        10.24, // 10.24s
    ];
    // S3 upload body size buckets (in bytes, 2x increments)
    const S3_BODY_SIZES: &[f64] = &[
        1024.0,     // 1KB
        2048.0,     // 2KB
        4096.0,     // 4KB
        8192.0,     // 8KB
        16384.0,    // 16KB
        32768.0,    // 32KB
        65536.0,    // 64KB
        131072.0,   // 128KB
        262144.0,   // 256KB
        524288.0,   // 512KB
        1048576.0,  // 1MB
        2097152.0,  // 2MB
        4194304.0,  // 4MB
        8388608.0,  // 8MB
        16777216.0, // 16MB
        33554432.0, // 32MB
    ];
    // Blob count per event (2x increments)
    const BLOB_COUNTS: &[f64] = &[1.0, 2.0, 4.0, 8.0, 16.0, 32.0];

    PrometheusBuilder::new()
        .add_global_label("role", role)
        .add_global_label("capture_mode", capture_mode)
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
        .set_buckets_for_metric(
            Matcher::Full("capture_s3_upload_duration_seconds".to_string()),
            S3_LATENCY_SECONDS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("capture_s3_upload_body_size_bytes".to_string()),
            S3_BODY_SIZES,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("capture_ai_blob_count_per_event".to_string()),
            BLOB_COUNTS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("capture_ai_blob_size_bytes".to_string()),
            S3_BODY_SIZES, // Reuse same buckets as S3 body sizes
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("capture_ai_blob_total_bytes_per_event".to_string()),
            S3_BODY_SIZES, // Reuse same buckets as S3 body sizes
        )
        .unwrap()
        .install_recorder()
        .unwrap()
}
