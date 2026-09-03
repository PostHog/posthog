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

/// Prometheus marks a series stale with a specific NaN payload
/// (`0x7ff0000000000002`) and remote-write forwards it. It must not become a
/// metric value: NaN survives the storage `ifNull` and corrupts rate/aggregate
/// queries. Non-finite samples are dropped before a row is built.
#[test]
fn drops_stale_marker_nan_samples() {
    const STALE_NAN_BITS: u64 = 0x7ff0000000000002;
    let req = WriteRequest {
        timeseries: vec![series(
            vec![
                label("__name__", "http_requests_total"),
                label("job", "api"),
            ],
            vec![
                Sample {
                    value: 7.0,
                    timestamp: now_ms(),
                },
                Sample {
                    value: f64::from_bits(STALE_NAN_BITS),
                    timestamp: now_ms() + 1,
                },
                Sample {
                    value: f64::INFINITY,
                    timestamp: now_ms() + 2,
                },
            ],
        )],
        metadata: vec![],
    };

    let (rows, _) = write_request_to_kafka_rows(req);

    // Only the finite sample survives; the stale marker and the infinity are dropped.
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].value, 7.0);
    assert!(rows.iter().all(|r| r.value.is_finite()));
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

    let (decoded, _) =
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

/// Quota and rate limiting charge the payload size the handler reports. This
/// route bypasses `RequestDecompressionLayer`, so that size has to come from the
/// decoder: reporting the request body length charges the snappy-compressed
/// size, while the OTLP and logs paths charge the decompressed size.
#[test]
fn reports_decompressed_payload_size() {
    let req = WriteRequest {
        timeseries: vec![series(
            vec![label("__name__", "up"), label("job", "prometheus")],
            (0..200)
                .map(|i| Sample {
                    value: 1.0,
                    timestamp: now_ms() + i,
                })
                .collect(),
        )],
        metadata: vec![],
    };
    let mut encoded = Vec::new();
    req.encode(&mut encoded).unwrap();
    let compressed = snap::raw::Encoder::new().compress_vec(&encoded).unwrap();

    let (_, uncompressed_bytes) =
        decode_write_request(&compressed, MAX_DECOMPRESSED).expect("snappy+protobuf decode");

    assert_eq!(uncompressed_bytes, encoded.len() as u64);
    // Keeps the assertion above from passing vacuously: a payload that did not
    // compress would satisfy it whichever size the decoder reported.
    assert!(
        uncompressed_bytes > compressed.len() as u64,
        "fixture did not compress: {uncompressed_bytes} decompressed vs {} compressed",
        compressed.len()
    );
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

/// Declared metadata units must reach the row, including on decomposed
/// component series that look up their family by stripped suffix.
#[test]
fn metadata_unit_reaches_rows() {
    let req = WriteRequest {
        timeseries: vec![
            series(
                vec![label("__name__", "req_duration"), label("job", "api")],
                vec![Sample {
                    value: 0.2,
                    timestamp: now_ms(),
                }],
            ),
            series(
                vec![
                    label("__name__", "req_duration_bucket"),
                    label("job", "api"),
                    label("le", "0.5"),
                ],
                vec![Sample {
                    value: 3.0,
                    timestamp: now_ms(),
                }],
            ),
        ],
        metadata: vec![MetricMetadata {
            r#type: MetricType::Histogram as i32,
            metric_family_name: "req_duration".to_string(),
            help: String::new(),
            unit: "seconds".to_string(),
        }],
    };

    let (rows, _) = write_request_to_kafka_rows(req);

    assert_eq!(rows.len(), 2);
    assert_eq!(rows[0].unit, "seconds");
    assert_eq!(rows[1].unit, "seconds", "suffix fallback carries the unit");
}

#[test]
fn rows_without_metadata_have_empty_unit() {
    let req = WriteRequest {
        timeseries: vec![series(
            vec![label("__name__", "up"), label("job", "api")],
            vec![Sample {
                value: 1.0,
                timestamp: now_ms(),
            }],
        )],
        metadata: vec![],
    };

    let (rows, _) = write_request_to_kafka_rows(req);

    assert_eq!(rows[0].unit, "");
}

/// A size-compliant body can still decode into a huge number of samples (a
/// zero-valued Sample is 2 wire bytes), each of which becomes a row cloning
/// the series label map — and the whole batch is one Kafka message. The
/// expansion estimate must flag such payloads before any row is built.
#[test]
fn estimates_expansion_of_many_samples_and_fat_labels() {
    use capture_logs::endpoints::prometheus::estimate_expanded_bytes;

    // A realistic vmagent-sized batch stays far under a 16x cap on a 2 MiB body.
    let realistic = WriteRequest {
        timeseries: (0..1000)
            .map(|i| {
                series(
                    vec![
                        label("__name__", &format!("some_metric_{i}_total")),
                        label("job", "api"),
                        label("instance", "10.0.0.1:9100"),
                        label("route", "/checkout/step/confirm"),
                    ],
                    (0..10)
                        .map(|_| Sample {
                            value: 1.0,
                            timestamp: now_ms(),
                        })
                        .collect(),
                )
            })
            .collect(),
        metadata: vec![],
    };
    assert!(estimate_expanded_bytes(&realistic) < 16 * 2 * 1024 * 1024);

    // One series, one million empty samples: tiny on the wire, enormous expanded.
    let sample_bomb = WriteRequest {
        timeseries: vec![series(
            vec![label("__name__", "m")],
            vec![
                Sample {
                    value: 0.0,
                    timestamp: 0,
                };
                1_000_000
            ],
        )],
        metadata: vec![],
    };
    assert!(estimate_expanded_bytes(&sample_bomb) > 16 * 2 * 1024 * 1024);

    // Fat label value cloned into tens of thousands of rows.
    let label_bomb = WriteRequest {
        timeseries: vec![series(
            vec![
                label("__name__", "m"),
                label("blob", &"x".repeat(1024 * 1024)),
            ],
            vec![
                Sample {
                    value: 0.0,
                    timestamp: 0,
                };
                50_000
            ],
        )],
        metadata: vec![],
    };
    assert!(estimate_expanded_bytes(&label_bomb) > 16 * 2 * 1024 * 1024);
}

/// A fat declared `MetricMetadata.unit` is cloned into every row, so it must
/// count toward the expansion estimate. Without it, ~100k compact samples plus
/// a ~1 MiB unit estimate to only ~28 MiB (under the 16x * 2 MiB cap) yet blow
/// up to hundreds of GB at row-build time.
#[test]
fn estimates_expansion_of_fat_metadata_unit() {
    use capture_logs::endpoints::prometheus::estimate_expanded_bytes;

    let compact_samples: Vec<Sample> = (0..100_000)
        .map(|_| Sample {
            value: 1.0,
            timestamp: 0,
        })
        .collect();
    let req = WriteRequest {
        timeseries: vec![series(
            vec![label("__name__", "requests_total"), label("job", "api")],
            compact_samples,
        )],
        metadata: vec![MetricMetadata {
            r#type: MetricType::Counter as i32,
            metric_family_name: "requests_total".to_string(),
            help: String::new(),
            unit: "u".repeat(1024 * 1024),
        }],
    };

    assert!(estimate_expanded_bytes(&req) > 16 * 2 * 1024 * 1024);
}

/// Pins the row builder's name resolution: its label loop reassigns on every
/// `__name__`, so the *last* one wins. The expansion estimate must agree, which
/// the next test guards.
#[test]
fn builder_resolves_unit_from_the_last_metric_name_label() {
    let req = WriteRequest {
        timeseries: vec![series(
            vec![label("__name__", "first"), label("__name__", "second")],
            vec![Sample {
                value: 1.0,
                timestamp: now_ms(),
            }],
        )],
        metadata: vec![
            MetricMetadata {
                r#type: MetricType::Gauge as i32,
                metric_family_name: "first".to_string(),
                help: String::new(),
                unit: "bytes".to_string(),
            },
            MetricMetadata {
                r#type: MetricType::Gauge as i32,
                metric_family_name: "second".to_string(),
                help: String::new(),
                unit: "seconds".to_string(),
            },
        ],
    };

    let (rows, _) = write_request_to_kafka_rows(req);

    assert_eq!(rows[0].metric_name, "second");
    assert_eq!(rows[0].unit, "seconds");
}

/// A duplicate `__name__` must not hide a fat unit from the expansion cap. The
/// builder clones the unit of the *last* name into every row, so an estimate
/// that resolves only the first name under-counts by an attacker-chosen amount
/// and lets the payload through to explode at row-build time.
/// Estimate-only on purpose: actually building these rows is the OOM.
#[test]
fn duplicate_metric_name_cannot_hide_a_fat_unit_from_the_cap() {
    use capture_logs::endpoints::prometheus::estimate_expanded_bytes;

    const SAMPLES: usize = 10_000;
    let fat_unit = "u".repeat(512 * 1024);
    let req = WriteRequest {
        timeseries: vec![series(
            vec![label("__name__", "unmatched"), label("__name__", "fat")],
            vec![
                Sample {
                    value: 0.0,
                    timestamp: 0,
                };
                SAMPLES
            ],
        )],
        metadata: vec![MetricMetadata {
            r#type: MetricType::Gauge as i32,
            metric_family_name: "fat".to_string(),
            help: String::new(),
            unit: fat_unit.clone(),
        }],
    };

    assert!(
        estimate_expanded_bytes(&req) >= (SAMPLES * fat_unit.len()) as u64,
        "estimate must include the unit the builder will clone per row"
    );
}
