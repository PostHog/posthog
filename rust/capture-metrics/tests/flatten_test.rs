use capture_metrics::metric_record::flatten_metric;
use chrono::Utc;
use opentelemetry_proto::tonic::{
    common::v1::{any_value, AnyValue, InstrumentationScope, KeyValue},
    metrics::v1::{
        exponential_histogram_data_point::Buckets, metric, number_data_point,
        summary_data_point::ValueAtQuantile, ExponentialHistogram, ExponentialHistogramDataPoint,
        Gauge, Histogram, HistogramDataPoint, Metric, NumberDataPoint, Sum, Summary,
        SummaryDataPoint,
    },
    resource::v1::Resource,
};

fn recent_ts_nano() -> u64 {
    Utc::now().timestamp_nanos_opt().unwrap() as u64
}

fn make_resource(service_name: &str) -> Resource {
    Resource {
        attributes: vec![KeyValue {
            key: "service.name".to_string(),
            value: Some(AnyValue {
                value: Some(any_value::Value::StringValue(service_name.to_string())),
            }),
        }],
        dropped_attributes_count: 0,
    }
}

fn make_scope(name: &str, version: &str) -> InstrumentationScope {
    InstrumentationScope {
        name: name.to_string(),
        version: version.to_string(),
        attributes: vec![],
        dropped_attributes_count: 0,
    }
}

fn make_dp_attributes() -> Vec<KeyValue> {
    vec![
        KeyValue {
            key: "host".to_string(),
            value: Some(AnyValue {
                value: Some(any_value::Value::StringValue("server-1".to_string())),
            }),
        },
        KeyValue {
            key: "region".to_string(),
            value: Some(AnyValue {
                value: Some(any_value::Value::StringValue("us-east-1".to_string())),
            }),
        },
    ]
}

// --- Gauge ---

#[test]
fn test_flatten_gauge_single_data_point() {
    let metric = Metric {
        name: "system.cpu.utilization".to_string(),
        description: String::new(),
        unit: "1".to_string(),
        metadata: vec![],
        data: Some(metric::Data::Gauge(Gauge {
            data_points: vec![NumberDataPoint {
                attributes: make_dp_attributes(),
                time_unix_nano: recent_ts_nano(),
                start_time_unix_nano: 0,
                value: Some(number_data_point::Value::AsDouble(0.85)),
                exemplars: vec![],
                flags: 0,
            }],
        })),
    };

    let resource = make_resource("my-service");
    let scope = make_scope("otel-sdk", "1.0.0");
    let (rows, overridden) = flatten_metric(metric, Some(&resource), Some(&scope)).unwrap();

    assert_eq!(rows.len(), 1);
    assert_eq!(overridden, 0);

    let row = &rows[0];
    assert_eq!(row.metric_name, "system.cpu.utilization");
    assert_eq!(row.metric_type, "gauge");
    assert_eq!(row.value, 0.85);
    assert_eq!(row.unit, "1");
    assert_eq!(row.count, 1);
    assert_eq!(row.service_name, "my-service");
    assert_eq!(row.instrumentation_scope, "otel-sdk@1.0.0");
    assert!(row.histogram_bounds.is_empty());
    assert!(row.histogram_counts.is_empty());
    assert!(row.aggregation_temporality.is_empty());
    assert!(!row.is_monotonic);

    // Check data point attributes
    assert_eq!(row.attributes.get("host").unwrap(), "\"server-1\"");
    assert_eq!(row.attributes.get("region").unwrap(), "\"us-east-1\"");

    // Check resource attributes
    assert!(row.resource_attributes.contains_key("service.name"));
}

#[test]
fn test_flatten_gauge_multiple_data_points() {
    let metric = Metric {
        name: "system.memory.usage".to_string(),
        description: String::new(),
        unit: "bytes".to_string(),
        metadata: vec![],
        data: Some(metric::Data::Gauge(Gauge {
            data_points: vec![
                NumberDataPoint {
                    attributes: vec![KeyValue {
                        key: "state".to_string(),
                        value: Some(AnyValue {
                            value: Some(any_value::Value::StringValue("used".to_string())),
                        }),
                    }],
                    time_unix_nano: recent_ts_nano(),
                    start_time_unix_nano: 0,
                    value: Some(number_data_point::Value::AsInt(4294967296)),
                    exemplars: vec![],
                    flags: 0,
                },
                NumberDataPoint {
                    attributes: vec![KeyValue {
                        key: "state".to_string(),
                        value: Some(AnyValue {
                            value: Some(any_value::Value::StringValue("free".to_string())),
                        }),
                    }],
                    time_unix_nano: recent_ts_nano(),
                    start_time_unix_nano: 0,
                    value: Some(number_data_point::Value::AsInt(8589934592)),
                    exemplars: vec![],
                    flags: 0,
                },
            ],
        })),
    };

    let (rows, _) = flatten_metric(metric, None, None).unwrap();

    assert_eq!(rows.len(), 2);
    assert_eq!(rows[0].value, 4294967296.0);
    assert_eq!(rows[0].attributes.get("state").unwrap(), "\"used\"");
    assert_eq!(rows[1].value, 8589934592.0);
    assert_eq!(rows[1].attributes.get("state").unwrap(), "\"free\"");
}

#[test]
fn test_flatten_gauge_int_value() {
    let metric = Metric {
        name: "process.threads".to_string(),
        description: String::new(),
        unit: "1".to_string(),
        metadata: vec![],
        data: Some(metric::Data::Gauge(Gauge {
            data_points: vec![NumberDataPoint {
                attributes: vec![],
                time_unix_nano: recent_ts_nano(),
                start_time_unix_nano: 0,
                value: Some(number_data_point::Value::AsInt(42)),
                exemplars: vec![],
                flags: 0,
            }],
        })),
    };

    let (rows, _) = flatten_metric(metric, None, None).unwrap();
    assert_eq!(rows[0].value, 42.0);
}

// --- Sum ---

#[test]
fn test_flatten_sum_monotonic_cumulative() {
    let metric = Metric {
        name: "http.server.request_count".to_string(),
        description: String::new(),
        unit: "1".to_string(),
        metadata: vec![],
        data: Some(metric::Data::Sum(Sum {
            data_points: vec![NumberDataPoint {
                attributes: vec![KeyValue {
                    key: "http.method".to_string(),
                    value: Some(AnyValue {
                        value: Some(any_value::Value::StringValue("GET".to_string())),
                    }),
                }],
                time_unix_nano: recent_ts_nano(),
                start_time_unix_nano: 0,
                value: Some(number_data_point::Value::AsInt(1500)),
                exemplars: vec![],
                flags: 0,
            }],
            aggregation_temporality: 2, // CUMULATIVE
            is_monotonic: true,
        })),
    };

    let (rows, _) = flatten_metric(metric, None, None).unwrap();

    assert_eq!(rows.len(), 1);
    let row = &rows[0];
    assert_eq!(row.metric_name, "http.server.request_count");
    assert_eq!(row.metric_type, "sum");
    assert_eq!(row.value, 1500.0);
    assert_eq!(row.aggregation_temporality, "cumulative");
    assert!(row.is_monotonic);
}

#[test]
fn test_flatten_sum_delta() {
    let metric = Metric {
        name: "http.server.active_requests".to_string(),
        description: String::new(),
        unit: "1".to_string(),
        metadata: vec![],
        data: Some(metric::Data::Sum(Sum {
            data_points: vec![NumberDataPoint {
                attributes: vec![],
                time_unix_nano: recent_ts_nano(),
                start_time_unix_nano: 0,
                value: Some(number_data_point::Value::AsDouble(3.0)),
                exemplars: vec![],
                flags: 0,
            }],
            aggregation_temporality: 1, // DELTA
            is_monotonic: false,
        })),
    };

    let (rows, _) = flatten_metric(metric, None, None).unwrap();

    let row = &rows[0];
    assert_eq!(row.aggregation_temporality, "delta");
    assert!(!row.is_monotonic);
}

// --- Histogram ---

#[test]
fn test_flatten_histogram() {
    let metric = Metric {
        name: "http.server.duration".to_string(),
        description: String::new(),
        unit: "ms".to_string(),
        metadata: vec![],
        data: Some(metric::Data::Histogram(Histogram {
            data_points: vec![HistogramDataPoint {
                attributes: vec![],
                time_unix_nano: recent_ts_nano(),
                start_time_unix_nano: 0,
                count: 100,
                sum: Some(5432.1),
                bucket_counts: vec![10, 20, 30, 25, 10, 5],
                explicit_bounds: vec![1.0, 5.0, 10.0, 50.0, 100.0],
                exemplars: vec![],
                flags: 0,
                min: None,
                max: None,
            }],
            aggregation_temporality: 2,
        })),
    };

    let (rows, _) = flatten_metric(metric, None, None).unwrap();

    assert_eq!(rows.len(), 1);
    let row = &rows[0];
    assert_eq!(row.metric_name, "http.server.duration");
    assert_eq!(row.metric_type, "histogram");
    assert_eq!(row.value, 5432.1);
    assert_eq!(row.count, 100);
    assert_eq!(row.unit, "ms");
    assert_eq!(row.histogram_bounds, vec![1.0, 5.0, 10.0, 50.0, 100.0]);
    assert_eq!(row.histogram_counts, vec![10, 20, 30, 25, 10, 5]);
    assert_eq!(row.aggregation_temporality, "cumulative");
}

#[test]
fn test_flatten_histogram_no_sum() {
    let metric = Metric {
        name: "request.size".to_string(),
        description: String::new(),
        unit: "bytes".to_string(),
        metadata: vec![],
        data: Some(metric::Data::Histogram(Histogram {
            data_points: vec![HistogramDataPoint {
                attributes: vec![],
                time_unix_nano: recent_ts_nano(),
                start_time_unix_nano: 0,
                count: 50,
                sum: None,
                bucket_counts: vec![5, 15, 20, 10],
                explicit_bounds: vec![100.0, 500.0, 1000.0],
                exemplars: vec![],
                flags: 0,
                min: None,
                max: None,
            }],
            aggregation_temporality: 1,
        })),
    };

    let (rows, _) = flatten_metric(metric, None, None).unwrap();

    let row = &rows[0];
    assert_eq!(row.value, 0.0); // No sum provided
    assert_eq!(row.count, 50);
}

// --- Exponential Histogram ---

#[test]
fn test_flatten_exponential_histogram() {
    let metric = Metric {
        name: "http.request.duration".to_string(),
        description: String::new(),
        unit: "s".to_string(),
        metadata: vec![],
        data: Some(metric::Data::ExponentialHistogram(ExponentialHistogram {
            data_points: vec![ExponentialHistogramDataPoint {
                attributes: vec![],
                time_unix_nano: recent_ts_nano(),
                start_time_unix_nano: 0,
                count: 200,
                sum: Some(150.5),
                scale: 2,
                zero_count: 5,
                positive: Some(Buckets {
                    offset: 0,
                    bucket_counts: vec![10, 20, 30],
                }),
                negative: Some(Buckets {
                    offset: 0,
                    bucket_counts: vec![3, 2],
                }),
                flags: 0,
                exemplars: vec![],
                min: None,
                max: None,
                zero_threshold: 0.0,
            }],
            aggregation_temporality: 2,
        })),
    };

    let (rows, _) = flatten_metric(metric, None, None).unwrap();

    assert_eq!(rows.len(), 1);
    let row = &rows[0];
    assert_eq!(row.metric_name, "http.request.duration");
    assert_eq!(row.metric_type, "exponential_histogram");
    assert_eq!(row.value, 150.5);
    assert_eq!(row.count, 200);
    assert_eq!(row.aggregation_temporality, "cumulative");

    // Should have flattened buckets: zero_count(1) + negative(2) + positive(3)
    assert_eq!(row.histogram_bounds.len(), 6);
    assert_eq!(row.histogram_counts.len(), 6);

    // Zero bucket
    assert_eq!(row.histogram_bounds[0], 0.0);
    assert_eq!(row.histogram_counts[0], 5);
}

// --- Summary ---

#[test]
fn test_flatten_summary() {
    let metric = Metric {
        name: "rpc.server.duration".to_string(),
        description: String::new(),
        unit: "ms".to_string(),
        metadata: vec![],
        data: Some(metric::Data::Summary(Summary {
            data_points: vec![SummaryDataPoint {
                attributes: vec![],
                time_unix_nano: recent_ts_nano(),
                start_time_unix_nano: 0,
                count: 500,
                sum: 25000.0,
                quantile_values: vec![
                    ValueAtQuantile {
                        quantile: 0.5,
                        value: 45.0,
                    },
                    ValueAtQuantile {
                        quantile: 0.95,
                        value: 120.0,
                    },
                    ValueAtQuantile {
                        quantile: 0.99,
                        value: 250.0,
                    },
                ],
                flags: 0,
            }],
        })),
    };

    let (rows, _) = flatten_metric(metric, None, None).unwrap();

    assert_eq!(rows.len(), 1);
    let row = &rows[0];
    assert_eq!(row.metric_name, "rpc.server.duration");
    assert_eq!(row.metric_type, "summary");
    assert_eq!(row.value, 25000.0);
    assert_eq!(row.count, 500);

    // Quantiles stored in histogram_bounds
    assert_eq!(row.histogram_bounds, vec![0.5, 0.95, 0.99]);
}

// --- Edge cases ---

#[test]
fn test_flatten_metric_no_data() {
    let metric = Metric {
        name: "empty.metric".to_string(),
        description: String::new(),
        unit: String::new(),
        metadata: vec![],
        data: None,
    };

    let (rows, overridden) = flatten_metric(metric, None, None).unwrap();
    assert_eq!(rows.len(), 0);
    assert_eq!(overridden, 0);
}

#[test]
fn test_flatten_metric_no_resource() {
    let metric = Metric {
        name: "test.metric".to_string(),
        description: String::new(),
        unit: "1".to_string(),
        metadata: vec![],
        data: Some(metric::Data::Gauge(Gauge {
            data_points: vec![NumberDataPoint {
                attributes: vec![],
                time_unix_nano: recent_ts_nano(),
                start_time_unix_nano: 0,
                value: Some(number_data_point::Value::AsDouble(1.0)),
                exemplars: vec![],
                flags: 0,
            }],
        })),
    };

    let (rows, _) = flatten_metric(metric, None, None).unwrap();

    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].service_name, "");
    assert!(rows[0].resource_attributes.is_empty());
    assert_eq!(rows[0].instrumentation_scope, "");
}

#[test]
fn test_flatten_metric_no_value() {
    let metric = Metric {
        name: "null.value".to_string(),
        description: String::new(),
        unit: "1".to_string(),
        metadata: vec![],
        data: Some(metric::Data::Gauge(Gauge {
            data_points: vec![NumberDataPoint {
                attributes: vec![],
                time_unix_nano: recent_ts_nano(),
                start_time_unix_nano: 0,
                value: None,
                exemplars: vec![],
                flags: 0,
            }],
        })),
    };

    let (rows, _) = flatten_metric(metric, None, None).unwrap();
    assert_eq!(rows[0].value, 0.0);
}

#[test]
fn test_flatten_metric_zero_timestamp_uses_now() {
    let metric = Metric {
        name: "no.timestamp".to_string(),
        description: String::new(),
        unit: "1".to_string(),
        metadata: vec![],
        data: Some(metric::Data::Gauge(Gauge {
            data_points: vec![NumberDataPoint {
                attributes: vec![],
                time_unix_nano: 0,
                start_time_unix_nano: 0,
                value: Some(number_data_point::Value::AsDouble(1.0)),
                exemplars: vec![],
                flags: 0,
            }],
        })),
    };

    let (rows, overridden) = flatten_metric(metric, None, None).unwrap();

    assert_eq!(rows.len(), 1);
    assert_eq!(overridden, 0); // zero timestamp uses now(), not overridden
                               // Timestamp should be close to now
    let now = chrono::Utc::now();
    let diff = (now - rows[0].timestamp).num_seconds().abs();
    assert!(diff < 5, "Timestamp should be close to now, diff: {diff}s");
}

#[test]
fn test_flatten_metric_old_timestamp_overridden() {
    use chrono::{TimeDelta, Utc};

    let far_past = (Utc::now() - TimeDelta::hours(48))
        .timestamp_nanos_opt()
        .unwrap() as u64;

    let metric = Metric {
        name: "old.metric".to_string(),
        description: String::new(),
        unit: "1".to_string(),
        metadata: vec![],
        data: Some(metric::Data::Gauge(Gauge {
            data_points: vec![NumberDataPoint {
                attributes: vec![],
                time_unix_nano: far_past,
                start_time_unix_nano: 0,
                value: Some(number_data_point::Value::AsDouble(1.0)),
                exemplars: vec![],
                flags: 0,
            }],
        })),
    };

    let (rows, overridden) = flatten_metric(metric, None, None).unwrap();

    assert_eq!(overridden, 1);
    assert!(rows[0].attributes.contains_key("$originalTimestamp"));
}

#[test]
fn test_flatten_each_row_gets_unique_uuid() {
    let metric = Metric {
        name: "multi.point".to_string(),
        description: String::new(),
        unit: "1".to_string(),
        metadata: vec![],
        data: Some(metric::Data::Gauge(Gauge {
            data_points: vec![
                NumberDataPoint {
                    attributes: vec![],
                    time_unix_nano: recent_ts_nano(),
                    start_time_unix_nano: 0,
                    value: Some(number_data_point::Value::AsDouble(1.0)),
                    exemplars: vec![],
                    flags: 0,
                },
                NumberDataPoint {
                    attributes: vec![],
                    time_unix_nano: recent_ts_nano(),
                    start_time_unix_nano: 0,
                    value: Some(number_data_point::Value::AsDouble(2.0)),
                    exemplars: vec![],
                    flags: 0,
                },
            ],
        })),
    };

    let (rows, _) = flatten_metric(metric, None, None).unwrap();
    assert_eq!(rows.len(), 2);
    assert_ne!(rows[0].uuid, rows[1].uuid);
}
