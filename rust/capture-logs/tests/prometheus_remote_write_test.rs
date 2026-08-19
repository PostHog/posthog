use capture_logs::endpoints::prometheus::{decode_write_request, write_request_to_kafka_rows};
use chrono::{Duration, Utc};
use prometheus_rw_proto::prometheus::v1::{
    metric_metadata::MetricType, Label, MetricMetadata, Sample, TimeSeries, WriteRequest,
};
use prost::Message;

const MAX_DECOMPRESSED: usize = 1 << 20;

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

    let decoded =
        decode_write_request(&compressed, MAX_DECOMPRESSED).expect("snappy+protobuf decode");
    let (rows, _) = write_request_to_kafka_rows(decoded);

    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].metric_name, "up");
    assert_eq!(rows[0].service_name, "prometheus");
}

#[test]
fn rejects_non_snappy_garbage() {
    assert!(decode_write_request(b"not snappy at all", MAX_DECOMPRESSED).is_err());
}

/// The raw-snappy length header is sender-controlled: a tiny body can claim a
/// multi-gigabyte decompressed size, and an uncapped decoder would allocate it
/// before finding out the data is short. The claimed length must be checked
/// against the cap before any allocation happens.
#[test]
fn rejects_decompression_bomb_before_allocating() {
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

    // A cap below the (legitimate) decompressed size must reject the payload.
    assert!(decode_write_request(&compressed, encoded.len() - 1).is_err());
    // The same payload passes with an adequate cap, so the rejection above is
    // the cap and not a decode failure.
    assert!(decode_write_request(&compressed, encoded.len()).is_ok());
}

/// The prometheus route is deliberately kept off `RequestDecompressionLayer`, so
/// a `Content-Encoding: snappy` request reaches the handler with the raw body to
/// decode itself — proving the 415 problem is avoided.
#[tokio::test]
async fn snappy_body_reaches_handler_without_decompression_layer() {
    use axum::{body::Body, http::Request, routing::post, Router};
    use bytes::Bytes;
    use tower::ServiceExt;

    async fn echo(body: Bytes) -> Bytes {
        body
    }

    let app = Router::new().route("/i/v1/prometheus/write", post(echo));

    let compressed = snap::raw::Encoder::new().compress_vec(b"hello").unwrap();
    let req = Request::builder()
        .method("POST")
        .uri("/i/v1/prometheus/write")
        .header("content-encoding", "snappy")
        .body(Body::from(compressed.clone()))
        .unwrap();

    let resp = app.oneshot(req).await.unwrap();
    assert!(
        resp.status().is_success(),
        "expected 2xx, got {}",
        resp.status()
    );
    let bytes = axum::body::to_bytes(resp.into_body(), 1 << 20)
        .await
        .unwrap();
    assert_eq!(&bytes[..], compressed.as_slice());
}

/// Regression guard: the layer the OTLP/logs routes use rejects snappy with 415,
/// which is exactly why the prometheus route must not pass through it.
#[tokio::test]
async fn request_decompression_layer_rejects_snappy_with_415() {
    use axum::{body::Body, http::Request, http::StatusCode, routing::post, Router};
    use bytes::Bytes;
    use tower::ServiceExt;
    use tower_http::decompression::RequestDecompressionLayer;

    async fn echo(body: Bytes) -> Bytes {
        body
    }

    let app = Router::new()
        .route("/i/v1/metrics", post(echo))
        .layer(RequestDecompressionLayer::new());

    let compressed = snap::raw::Encoder::new().compress_vec(b"hello").unwrap();
    let req = Request::builder()
        .method("POST")
        .uri("/i/v1/metrics")
        .header("content-encoding", "snappy")
        .body(Body::from(compressed))
        .unwrap();

    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNSUPPORTED_MEDIA_TYPE);
}

/// Series identity is assigned at ingest, exactly as the OTLP path does it:
/// every sample of one series carries the same fingerprint, and any identity
/// field (name, labels, inferred type) changing yields a different one.
#[test]
fn assigns_stable_series_fingerprints_at_ingest() {
    let req = WriteRequest {
        timeseries: vec![
            series(
                vec![
                    label("__name__", "http_requests_total"),
                    label("job", "api"),
                    label("route", "/checkout"),
                ],
                vec![
                    Sample {
                        value: 1.0,
                        timestamp: now_ms(),
                    },
                    Sample {
                        value: 2.0,
                        timestamp: now_ms() + 1,
                    },
                ],
            ),
            series(
                vec![
                    label("__name__", "http_requests_total"),
                    label("job", "api"),
                    label("route", "/cart"),
                ],
                vec![Sample {
                    value: 5.0,
                    timestamp: now_ms(),
                }],
            ),
        ],
        metadata: vec![],
    };

    let (rows, _) = write_request_to_kafka_rows(req);

    assert_eq!(rows.len(), 3);
    assert_ne!(
        rows[0].series_fingerprint, 0,
        "fingerprint must be assigned"
    );
    assert_eq!(
        rows[0].series_fingerprint, rows[1].series_fingerprint,
        "samples of one series share a fingerprint"
    );
    assert_ne!(
        rows[0].series_fingerprint, rows[2].series_fingerprint,
        "a different label set is a different series"
    );
}

/// A clamped timestamp adds $originalTimestamp to the row's attributes but must
/// never split the series: identity is computed before the synthetic attribute.
#[test]
fn overridden_timestamps_do_not_split_series_identity() {
    let req = WriteRequest {
        timeseries: vec![series(
            vec![
                label("__name__", "restore_lag_seconds"),
                label("job", "api"),
            ],
            vec![
                Sample {
                    value: 1.0,
                    timestamp: now_ms(),
                },
                Sample {
                    value: 2.0,
                    // Far outside the accept window: gets clamped + annotated.
                    timestamp: (Utc::now() - Duration::days(30)).timestamp_millis(),
                },
            ],
        )],
        metadata: vec![],
    };

    let (rows, overridden) = write_request_to_kafka_rows(req);

    assert_eq!(rows.len(), 2);
    assert_eq!(overridden, 1);
    assert!(rows[1].attributes.contains_key("$originalTimestamp"));
    assert_eq!(
        rows[0].series_fingerprint, rows[1].series_fingerprint,
        "the synthetic $originalTimestamp attribute must not change identity"
    );
}
