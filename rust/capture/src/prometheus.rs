// prometheus exporter setup

use common_types::timestamp::TimestampSource;
use limiters::redis::QuotaResource;
use metrics::counter;
use metrics_exporter_prometheus::{Matcher, PrometheusBuilder, PrometheusHandle};

pub const CAPTURE_EVENTS_DROPPED_TOTAL: &str = "capture_events_dropped_total";

pub const CAPTURE_TIMESTAMP_PATH_TOTAL: &str = "capture_timestamp_path_total";
pub const CAPTURE_STORED_VS_CLIENT_CAPTURE_SECONDS: &str =
    "capture_stored_vs_client_capture_seconds";
pub const CAPTURE_EDGE_TO_NOW_SECONDS: &str = "capture_edge_to_now_seconds";
pub const CAPTURE_EDGE_TIMESTAMP_REJECTED: &str = "capture_edge_timestamp_rejected_total";

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

pub fn report_clock_skew(skew: chrono::Duration) {
    let skew_seconds = skew.num_milliseconds().saturating_abs() as f64 / 1000.0;
    metrics::histogram!("capture_client_clock_skew_seconds").record(skew_seconds);
}

/// Records the branch, and the gap between the stored timestamp and the device's
/// own capture instant. That gap is delivery delay minus device clock offset,
/// which a single request cannot separate.
pub fn report_timestamp_path(
    source: TimestampSource,
    client_uuid: Option<uuid::Uuid>,
    stored: chrono::DateTime<chrono::Utc>,
) {
    let path_tag = source.as_str();
    counter!(CAPTURE_TIMESTAMP_PATH_TOTAL, "ts_path" => path_tag).increment(1);

    let Some(captured_ms) = client_uuid.and_then(crate::utils::client_capture_millis) else {
        return;
    };
    let Some(delta_ms) = stored.timestamp_millis().checked_sub(captured_ms) else {
        return;
    };
    let direction = if delta_ms < 0 {
        "stored_earlier"
    } else {
        "stored_later"
    };
    metrics::histogram!(
        CAPTURE_STORED_VS_CLIENT_CAPTURE_SECONDS,
        "ts_path" => path_tag,
        "direction" => direction,
    )
    .record(delta_ms.saturating_abs() as f64 / 1000.0);
}

/// Time from an upstream hop stamping the request to capture reading its clock.
/// Neither proxy overwrites a client-supplied value: Envoy appends its own
/// `X-Request-Start` after it, and the ALB keeps a supplied `Root` while putting its
/// own time in `Self`. So read the last one, prefer `Self`, and bound the result.
pub fn report_edge_to_now(headers: &axum::http::HeaderMap, now: chrono::DateTime<chrono::Utc>) {
    let now_ms = now.timestamp_millis();
    if let Some(start_ms) = headers
        .get_all("x-request-start")
        .iter()
        .filter_map(|v| v.to_str().ok())
        .filter_map(parse_request_start_ms)
        .next_back()
    {
        record_edge_delta("envoy", now_ms, start_ms);
    }
    if let Some(start_ms) = headers
        .get("x-amzn-trace-id")
        .and_then(|v| v.to_str().ok())
        .and_then(parse_amzn_trace_epoch_ms)
    {
        record_edge_delta("alb", now_ms, start_ms);
    }
}

/// The Envoy route timeout is 120s and the ALB idle timeout is 300s, so a larger
/// delta is a forged or broken header rather than a slow request.
const EDGE_DELTA_CEILING_MS: i64 = 600_000;

fn record_edge_delta(edge: &'static str, now_ms: i64, start_ms: i64) {
    let Some(delta_ms) = now_ms.checked_sub(start_ms) else {
        counter!(CAPTURE_EDGE_TIMESTAMP_REJECTED, "edge" => edge, "reason" => "implausible")
            .increment(1);
        return;
    };
    if !(0..=EDGE_DELTA_CEILING_MS).contains(&delta_ms) {
        let reason = if delta_ms < 0 {
            "negative"
        } else {
            "implausible"
        };
        counter!(CAPTURE_EDGE_TIMESTAMP_REJECTED, "edge" => edge, "reason" => reason).increment(1);
        return;
    }
    metrics::histogram!(CAPTURE_EDGE_TO_NOW_SECONDS, "edge" => edge)
        .record(delta_ms as f64 / 1000.0);
}

/// Parses Envoy's `t=<seconds>.<millis>`. Integer arithmetic, because an f64
/// seconds parse loses milliseconds at epoch magnitude.
fn parse_request_start_ms(value: &str) -> Option<i64> {
    let stripped = value.strip_prefix("t=").unwrap_or(value);
    let (secs, frac) = match stripped.split_once('.') {
        Some((s, f)) => (s, f),
        None => (stripped, ""),
    };
    let secs: i64 = secs.parse().ok()?;
    if secs < 0 {
        return None;
    }
    let mut millis = 0i64;
    if !frac.is_empty() {
        if !frac.bytes().all(|b| b.is_ascii_digit()) {
            return None;
        }
        let mut digits = frac.as_bytes().iter().take(3);
        for place in [100, 10, 1] {
            millis += i64::from(digits.next().map_or(0, |b| b - b'0')) * place;
        }
    }
    secs.checked_mul(1_000)?.checked_add(millis)
}

/// `Self` is present only when the ALB kept a client-supplied `Root`, so it is the
/// trustworthy field when both appear.
fn parse_amzn_trace_epoch_ms(value: &str) -> Option<i64> {
    let field = |name: &str| {
        value
            .split(';')
            .find_map(|part| part.trim().strip_prefix(name))
            .and_then(parse_trace_field_epoch_ms)
    };
    field("Self=").or_else(|| field("Root="))
}

/// AWS writes `1-<8 hex epoch seconds>-<24 hex id>`. A truncated epoch would read as
/// 1970 and land every request in the top bucket.
fn parse_trace_field_epoch_ms(field: &str) -> Option<i64> {
    let mut parts = field.split('-');
    if parts.next()? != "1" {
        return None;
    }
    let epoch = parts.next()?;
    let id = parts.next()?;
    if parts.next().is_some()
        || epoch.len() != 8
        || id.len() != 24
        || !id.bytes().all(|b| b.is_ascii_hexdigit())
    {
        return None;
    }
    i64::from_str_radix(epoch, 16).ok()?.checked_mul(1_000)
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
    // Redis read/write pipeline round-trip (milliseconds). Dense around the
    // 100ms read/write timeout so p99 is readable below it.
    const GLOBAL_RATE_LIMITER_PIPELINE_MS: &[f64] = &[
        0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 50.0, 75.0, 100.0, 150.0, 250.0, 500.0, 1000.0,
    ];
    // Full background tick (milliseconds). Dense around the 1s tick_interval so
    // we can see how close ticks run to the budget (e.g. reconcile ticks).
    const GLOBAL_RATE_LIMITER_TICK_MS: &[f64] = &[
        5.0, 10.0, 25.0, 50.0, 100.0, 150.0, 250.0, 400.0, 600.0, 800.0, 1000.0, 1500.0, 2000.0,
        4000.0,
    ];
    // Global rate limiter pipeline batch sizes (entity counts)
    const GLOBAL_RATE_LIMITER_PIPELINE_SIZES: &[f64] =
        &[1.0, 10.0, 50.0, 100.0, 500.0, 1000.0, 5000.0, 10000.0];
    // Global rate limiter estimate drift (ratio of threshold)
    const GLOBAL_RATE_LIMITER_DRIFT_RATIOS: &[f64] =
        &[0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0];
    // Global rate limiter sync staleness (milliseconds)
    const GLOBAL_RATE_LIMITER_STALENESS_MS: &[f64] = &[
        100.0, 500.0, 1000.0, 5000.0, 10000.0, 15000.0, 30000.0, 60000.0,
    ];

    // Absolute client clock skew buckets (in seconds).
    // Fine granularity near zero for finding the right skew correction threshold.
    const CLOCK_SKEW_SECONDS: &[f64] = &[
        0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 300.0, 3600.0, 86400.0,
    ];

    // Coarse on purpose, because every extra bucket multiplies by the label
    // combinations. 150 is the largest offset that could plausibly be transit
    // delay rather than a wrong clock.
    const DISPLACEMENT_SECONDS: &[f64] = &[0.05, 0.25, 1.0, 5.0, 30.0, 150.0, 3600.0];

    // Kafka produce ack duration (milliseconds), measured app-side from
    // `send_result()` returning to broker ack / error / cancellation.
    // Dense at low end where healthy acks live; widens into seconds / minutes
    // to capture the long tail (retries, broker stalls, acks=all replication).
    // Final bucket is 5 minutes; anything slower lands in +Inf.
    const KAFKA_PRODUCE_ACK_MS: &[f64] = &[
        0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 25.0, 50.0, 75.0, 100.0, 150.0, 250.0, 500.0, 1000.0,
        2500.0, 5000.0, 10000.0, 30000.0, 60000.0, 120000.0, 300000.0,
    ];

    // Same shape as KAFKA_PRODUCE_ACK_MS, but in seconds for the v1 sink's
    // `capture_v1_kafka_ack_duration_seconds` histogram.
    const KAFKA_PRODUCE_ACK_SECONDS: &[f64] = &[
        0.0005, 0.001, 0.002, 0.005, 0.01, 0.015, 0.025, 0.05, 0.075, 0.1, 0.15, 0.25, 0.5, 1.0,
        2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0,
    ];

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
            Matcher::Full("capture_ai_otel_body_size_bytes".to_string()),
            PAYLOAD_SIZES,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("capture_ai_otel_spans_per_request".to_string()),
            BATCH_SIZES,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("global_rate_limiter_pipeline_ms".to_string()),
            GLOBAL_RATE_LIMITER_PIPELINE_MS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("global_rate_limiter_tick_ms".to_string()),
            GLOBAL_RATE_LIMITER_TICK_MS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("global_rate_limiter_pipeline_size".to_string()),
            GLOBAL_RATE_LIMITER_PIPELINE_SIZES,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("global_rate_limiter_estimate_drift".to_string()),
            GLOBAL_RATE_LIMITER_DRIFT_RATIOS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("global_rate_limiter_sync_staleness_ms".to_string()),
            GLOBAL_RATE_LIMITER_STALENESS_MS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("capture_client_clock_skew_seconds".to_string()),
            CLOCK_SKEW_SECONDS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("capture_kafka_produce_ack_duration_ms".to_string()),
            KAFKA_PRODUCE_ACK_MS,
        )
        .unwrap()
        // v1 pipeline histograms: without explicit buckets these fall back to
        // the metrics-exporter-prometheus defaults, which are too coarse for
        // meaningful percentile queries in Grafana.
        .set_buckets_for_metric(
            Matcher::Full("capture_v1_response_time_seconds".to_string()),
            EXPONENTIAL_SECONDS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("capture_v1_kafka_ack_duration_seconds".to_string()),
            KAFKA_PRODUCE_ACK_SECONDS,
        )
        .unwrap()
        // capture_v1_event_batch_size is covered by the Suffix("_batch_size")
        // matcher above; only the payload-size and clock-skew histograms need
        // explicit entries.
        .set_buckets_for_metric(
            Matcher::Full("capture_v1_payload_size_bytes".to_string()),
            PAYLOAD_SIZES,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full("capture_v1_clock_skew_seconds".to_string()),
            CLOCK_SKEW_SECONDS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full(CAPTURE_STORED_VS_CLIENT_CAPTURE_SECONDS.to_string()),
            DISPLACEMENT_SECONDS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full(CAPTURE_EDGE_TO_NOW_SECONDS.to_string()),
            DISPLACEMENT_SECONDS,
        )
        .unwrap()
        .install_recorder()
        .unwrap()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::{client_capture_millis, uuid_v7};
    use uuid::Uuid;

    #[test]
    fn request_start_keeps_millisecond_resolution() {
        // An f64 seconds parse rounds these away into the first bucket.
        assert_eq!(
            parse_request_start_ms("t=1789599946.571"),
            Some(1789599946571)
        );
        assert_eq!(
            parse_request_start_ms("1789599946.571"),
            Some(1789599946571)
        );
        assert_eq!(parse_request_start_ms("t=1789599946"), Some(1789599946000));
        assert_eq!(
            parse_request_start_ms("t=1789599946.5"),
            Some(1789599946500)
        );
        assert_eq!(
            parse_request_start_ms("t=1789599946.571999"),
            Some(1789599946571)
        );
    }

    #[test]
    fn request_start_rejects_rather_than_guesses() {
        for bad in [
            "",
            "t=",
            "t=abc",
            "t=1789599946.5x1",
            "t=-5.0",
            "  t=1789599946.571",
        ] {
            assert_eq!(parse_request_start_ms(bad), None, "{bad}");
        }
    }

    #[test]
    fn alb_trace_prefers_the_field_the_load_balancer_controls() {
        // Reading `Root` first would report a client's number as ours.
        assert_eq!(
            parse_amzn_trace_epoch_ms(
                "Self=1-6aab488c-7f773a4636e043286963f18e;Root=1-3b9aca00-forgedforgedforgedforg"
            ),
            Some(1789610124000)
        );
        assert_eq!(
            parse_amzn_trace_epoch_ms("Root=1-6aab20ca-7499b34d351523a60de25e91"),
            Some(1789599946000)
        );
    }

    #[test]
    fn alb_trace_rejects_every_non_aws_shape() {
        for bad in [
            "",
            "Root=",
            "Root=1-5",
            "Root=1-6aab20ca",
            "Root=1-6aab20ca-short",
            "Root=1-6aab20ca-7499b34d351523a60de25e91-extra",
            "Root=1-6aab20ca-zzzzzzzzzzzzzzzzzzzzzzzz",
            "Root=2-6aab20ca-7499b34d351523a60de25e91",
            "Root=1-zzzzzzzz-7499b34d351523a60de25e91",
        ] {
            assert_eq!(parse_amzn_trace_epoch_ms(bad), None, "{bad}");
        }
    }

    #[test]
    fn envoy_request_start_wins_over_a_client_supplied_one() {
        // Envoy appends, so `HeaderMap::get` would return the forged first value.
        let mut headers = axum::http::HeaderMap::new();
        headers.append("x-request-start", "t=1000000000.000".parse().unwrap());
        headers.append("x-request-start", "t=1789610124.697".parse().unwrap());
        let chosen = headers
            .get_all("x-request-start")
            .iter()
            .filter_map(|v| v.to_str().ok())
            .filter_map(parse_request_start_ms)
            .next_back();
        assert_eq!(chosen, Some(1789610124697));
    }

    #[test]
    fn hostile_input_never_panics_on_either_entry_point() {
        // These run on every capture request. A panic here would take a request
        // down, so the contract is that any input is observed or skipped.
        let hostile = [
            "",
            "t=",
            "t=.",
            "t=-",
            "t=9223372036854775807",
            "t=9223372036854775807.999",
            "t=99999999999999999999999999999999999999",
            "t=-9223372036854775808",
            "t=0.000000000000000000000000",
            "Root=1-ffffffff-ffffffffffffffffffffffff",
            "Self=1-00000000-000000000000000000000000",
            "Root=1--",
            "Self=;Root=;Self=",
            "\u{1f600}\u{1f600}\u{1f600}",
            "t=1e999",
            "t=+1789610124.697",
        ];
        for value in hostile {
            let mut headers = axum::http::HeaderMap::new();
            if let Ok(hv) = axum::http::HeaderValue::from_str(value) {
                headers.append("x-request-start", hv.clone());
                headers.append("x-amzn-trace-id", hv);
            }
            for now in [
                chrono::Utc::now(),
                chrono::DateTime::<chrono::Utc>::MIN_UTC,
                chrono::DateTime::<chrono::Utc>::MAX_UTC,
            ] {
                report_edge_to_now(&headers, now);
            }
        }

        // A v7 UUID carrying the largest representable 48-bit instant, against the
        // widest stored timestamps chrono can hold.
        let max_v7 = Uuid::from_u128((0xFFFF_FFFF_FFFFu128 << 80) | (7u128 << 76));
        for uuid in [None, Some(max_v7), Some(uuid_v7(0)), Some(Uuid::new_v4())] {
            for stored in [
                chrono::DateTime::<chrono::Utc>::MIN_UTC,
                chrono::DateTime::<chrono::Utc>::MAX_UTC,
                chrono::Utc::now(),
            ] {
                for source in [
                    TimestampSource::Offset,
                    TimestampSource::SentAtSkew,
                    TimestampSource::ClientTimestamp,
                    TimestampSource::Now,
                ] {
                    report_timestamp_path(source, uuid, stored);
                }
            }
        }
    }

    #[test]
    fn only_a_v7_uuid_reports_a_capture_instant() {
        assert_eq!(
            client_capture_millis(uuid_v7(1_700_000_000_123)),
            Some(1_700_000_000_123)
        );
        assert_eq!(client_capture_millis(Uuid::new_v4()), None);
        assert_eq!(client_capture_millis(Uuid::nil()), None);
    }
}
