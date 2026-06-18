use capture_logs::prometheus_remote_write::{decode_write_request, write_request_to_kafka_rows};
use chrono::{Duration, Utc};
use prometheus_rw_proto::prometheus::v1::{
    metric_metadata::MetricType, Label, MetricMetadata, Sample, TimeSeries, WriteRequest,
};
use prost::Message;

fn label(name: &str, value: &str) -> Label {
    Label {
        name: name.to_string(),
        value: value.to_string(),
    }
}

fn series(labels: Vec<Label>, samples: Vec<Sample>) -> TimeSeries {
    TimeSeries { labels, samples }
}

/// A timestamp comfortably within the ±24h window so it is not clamped.
fn now_ms() -> i64 {
    Utc::now().timestamp_millis()
}

#[test]
fn maps_labels_to_name_service_and_attributes() {
    let req = WriteRequest {
        timeseries: vec![series(
            vec![
                label("__name__", "node_cpu_seconds"),
                label("job", "node-exporter"),
                label("instance", "10.0.0.1:9100"),
                label("mode", "idle"),
            ],
            vec![Sample {
                value: 12.5,
                timestamp: now_ms(),
            }],
        )],
        metadata: vec![],
    };

    let (rows, overridden) = write_request_to_kafka_rows(req);

    assert_eq!(rows.len(), 1);
    assert_eq!(overridden, 0);
    let row = &rows[0];
    assert_eq!(row.metric_name, "node_cpu_seconds");
    assert_eq!(row.service_name, "node-exporter");
    assert_eq!(row.metric_type, "gauge");
    assert!(!row.is_monotonic);
    assert_eq!(row.value, 12.5);
    assert_eq!(row.count, 1);
    // Map values are JSON-encoded to match the OTLP/Datadog paths, since the
    // ClickHouse MV applies JSONExtractString to them.
    assert_eq!(
        row.resource_attributes.get("service.name").unwrap(),
        "\"node-exporter\""
    );
    assert_eq!(
        row.resource_attributes.get("service.instance.id").unwrap(),
        "\"10.0.0.1:9100\""
    );
    assert_eq!(row.attributes.get("mode").unwrap(), "\"idle\"");
    // __name__/job/instance are not duplicated into the attributes map.
    assert!(!row.attributes.contains_key("__name__"));
    assert!(!row.attributes.contains_key("job"));
}

#[test]
fn infers_counter_from_total_suffix() {
    let req = WriteRequest {
        timeseries: vec![series(
            vec![
                label("__name__", "http_requests_total"),
                label("job", "api"),
            ],
            vec![Sample {
                value: 99.0,
                timestamp: now_ms(),
            }],
        )],
        metadata: vec![],
    };

    let (rows, _) = write_request_to_kafka_rows(req);

    assert_eq!(rows[0].metric_type, "sum");
    assert!(rows[0].is_monotonic);
    assert_eq!(rows[0].aggregation_temporality, "cumulative");
}

#[test]
fn types_histogram_bucket_as_cumulative_sum() {
    let req = WriteRequest {
        timeseries: vec![series(
            vec![
                label("__name__", "http_req_duration_bucket"),
                label("job", "api"),
                label("le", "0.5"),
            ],
            vec![Sample {
                value: 10.0,
                timestamp: now_ms(),
            }],
        )],
        metadata: vec![],
    };

    let (rows, _) = write_request_to_kafka_rows(req);

    assert_eq!(rows[0].metric_type, "sum");
    assert!(rows[0].is_monotonic);
    assert_eq!(rows[0].aggregation_temporality, "cumulative");
    // The bucket boundary label is preserved so PromQL can reconstruct quantiles.
    assert_eq!(rows[0].attributes.get("le").unwrap(), "\"0.5\"");
}

#[test]
fn metadata_counter_overrides_default_gauge() {
    // A bare name (no _total suffix) would default to gauge, but declared
    // metadata says COUNTER and must win.
    let req = WriteRequest {
        timeseries: vec![series(
            vec![label("__name__", "requests"), label("job", "api")],
            vec![Sample {
                value: 1.0,
                timestamp: now_ms(),
            }],
        )],
        metadata: vec![MetricMetadata {
            r#type: MetricType::Counter as i32,
            metric_family_name: "requests".to_string(),
            help: String::new(),
            unit: String::new(),
        }],
    };

    let (rows, _) = write_request_to_kafka_rows(req);

    assert_eq!(rows[0].metric_type, "sum");
    assert!(rows[0].is_monotonic);
    assert_eq!(rows[0].aggregation_temporality, "cumulative");
}

#[test]
fn emits_one_row_per_sample() {
    let req = WriteRequest {
        timeseries: vec![series(
            vec![label("__name__", "g"), label("job", "j")],
            vec![
                Sample {
                    value: 1.0,
                    timestamp: now_ms(),
                },
                Sample {
                    value: 2.0,
                    timestamp: now_ms(),
                },
                Sample {
                    value: 3.0,
                    timestamp: now_ms(),
                },
            ],
        )],
        metadata: vec![],
    };

    let (rows, _) = write_request_to_kafka_rows(req);

    assert_eq!(rows.len(), 3);
    assert_eq!(
        rows.iter().map(|r| r.value).collect::<Vec<_>>(),
        vec![1.0, 2.0, 3.0]
    );
}

#[test]
fn clamps_far_past_timestamp_and_counts_override() {
    let two_days_ago = (Utc::now() - Duration::hours(48)).timestamp_millis();
    let req = WriteRequest {
        timeseries: vec![series(
            vec![label("__name__", "g"), label("job", "j")],
            vec![Sample {
                value: 1.0,
                timestamp: two_days_ago,
            }],
        )],
        metadata: vec![],
    };

    let (rows, overridden) = write_request_to_kafka_rows(req);

    assert_eq!(overridden, 1);
    assert!(rows[0].attributes.contains_key("$originalTimestamp"));
    // Clamped forward to ~now.
    assert!((Utc::now() - rows[0].timestamp).num_seconds().abs() < 5);
}

#[test]
fn skips_series_without_metric_name() {
    let req = WriteRequest {
        timeseries: vec![series(
            vec![label("job", "j")],
            vec![Sample {
                value: 1.0,
                timestamp: now_ms(),
            }],
        )],
        metadata: vec![],
    };

    let (rows, _) = write_request_to_kafka_rows(req);

    assert!(rows.is_empty());
}

#[test]
fn snappy_round_trip_decodes_and_maps() {
    let req = WriteRequest {
        timeseries: vec![series(
            vec![label("__name__", "up"), label("job", "prometheus")],
            vec![Sample {
                value: 1.0,
                timestamp: now_ms(),
            }],
        )],
        metadata: vec![],
    };

    let mut encoded = Vec::new();
    req.encode(&mut encoded).unwrap();
    let compressed = snap::raw::Encoder::new().compress_vec(&encoded).unwrap();

    let decoded = decode_write_request(&compressed).expect("snappy+protobuf decode");
    let (rows, _) = write_request_to_kafka_rows(decoded);

    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].metric_name, "up");
    assert_eq!(rows[0].service_name, "prometheus");
}

#[test]
fn rejects_non_snappy_garbage() {
    assert!(decode_write_request(b"not snappy at all").is_err());
}
