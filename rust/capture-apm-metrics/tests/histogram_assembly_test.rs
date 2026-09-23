use std::collections::HashMap;

use capture_apm_metrics::histogram_assembly::{fold_classic_histograms, normalize_float_label};
use capture_logs::endpoints::prometheus::write_request_to_kafka_rows;
use capture_logs::metric_record::{flatten_metric, KafkaMetricRow};
use chrono::{Duration, Utc};
use opentelemetry_proto::tonic::common::v1::{any_value, AnyValue, KeyValue};
use opentelemetry_proto::tonic::metrics::v1::{
    metric::Data, Histogram, HistogramDataPoint, Metric,
};
use opentelemetry_proto::tonic::resource::v1::Resource;
use prometheus_rw_proto::prometheus::v1::{
    metric_metadata::MetricType, Label, MetricMetadata, Sample, TimeSeries, WriteRequest,
};

fn label(name: &str, value: &str) -> Label {
    Label {
        name: name.to_string(),
        value: value.to_string(),
    }
}

fn sample(value: f64, timestamp: i64) -> Sample {
    Sample { value, timestamp }
}

fn now_ms() -> i64 {
    Utc::now().timestamp_millis()
}

fn labelled(name: &str, extra: &[(&str, &str)], samples: Vec<Sample>) -> TimeSeries {
    let mut labels = vec![label("__name__", name), label("job", "api")];
    labels.extend(extra.iter().map(|(name, value)| label(name, value)));
    TimeSeries { labels, samples }
}

fn bucket(base: &str, extra: &[(&str, &str)], le: &str, samples: Vec<Sample>) -> TimeSeries {
    let mut series = labelled(&format!("{base}_bucket"), extra, samples);
    series.labels.push(label("le", le));
    series
}

fn fold(request: WriteRequest) -> Vec<KafkaMetricRow> {
    let metadata = request.metadata.clone();
    let (rows, _) = write_request_to_kafka_rows(request);
    fold_classic_histograms(rows, &metadata)
}

/// Creates a complete classic histogram with 0.5, 1, and `+Inf` buckets,
/// plus `_count` and `_sum` samples.
fn complete_histogram_request(timestamp: i64) -> WriteRequest {
    let route = &[("route", "/checkout")];
    WriteRequest {
        timeseries: vec![
            bucket(
                "http_req_duration_seconds",
                route,
                "0.5",
                vec![sample(2.0, timestamp)],
            ),
            bucket(
                "http_req_duration_seconds",
                route,
                "1.0",
                vec![sample(5.0, timestamp)],
            ),
            bucket(
                "http_req_duration_seconds",
                route,
                "+Inf",
                vec![sample(10.0, timestamp)],
            ),
            labelled(
                "http_req_duration_seconds_count",
                route,
                vec![sample(10.0, timestamp)],
            ),
            labelled(
                "http_req_duration_seconds_sum",
                route,
                vec![sample(12.5, timestamp)],
            ),
        ],
        metadata: vec![],
    }
}

fn plain_rows(rows: &[KafkaMetricRow]) -> Vec<&KafkaMetricRow> {
    rows.iter()
        .filter(|row| row.metric_type != "histogram")
        .collect()
}

#[test]
fn folds_complete_classic_histogram_into_one_native_row() {
    let timestamp = now_ms();
    let rows = fold(complete_histogram_request(timestamp));

    assert_eq!(rows.len(), 1, "five component rows fold into one: {rows:?}");
    let row = &rows[0];
    assert_eq!(row.metric_name, "http_req_duration_seconds");
    assert_eq!(row.metric_type, "histogram");
    assert_eq!(row.aggregation_temporality, "cumulative");
    assert!(!row.is_monotonic);
    assert!(row.has_labels);
    assert_eq!(row.service_name, "api");
    assert_eq!(row.histogram_bounds, vec![0.5, 1.0]);
    assert_eq!(row.histogram_counts, vec![2, 3, 5]);
    assert_eq!(row.count, 10);
    assert_eq!(row.value, 12.5);
    assert_eq!(row.timestamp.timestamp_millis(), timestamp);
    assert_eq!(row.attributes.get("route").unwrap(), "\"/checkout\"");
    assert!(!row.attributes.contains_key("le"));
    assert_eq!(
        row.resource_attributes.get("service.name").unwrap(),
        "\"api\""
    );
}

#[test]
fn equivalent_duplicate_components_fold_into_one_native_row() {
    let timestamp = now_ms();
    let route = &[("route", "/cart")];
    let rows = fold(WriteRequest {
        timeseries: vec![
            bucket("d", route, "+Inf", vec![sample(10.0, timestamp)]),
            labelled(
                "d_count",
                route,
                vec![sample(10.0, timestamp), sample(10.0, timestamp)],
            ),
            labelled(
                "d_sum",
                route,
                vec![sample(12.5, timestamp), sample(12.5, timestamp)],
            ),
        ],
        metadata: vec![],
    });

    assert_eq!(
        rows.len(),
        1,
        "duplicate components must not remain: {rows:?}"
    );
    assert_eq!(rows[0].metric_type, "histogram");
    assert_eq!(rows[0].count, 10);
    assert_eq!(rows[0].value, 12.5);
}

#[test]
fn folded_histogram_shares_identity_with_the_otlp_path() {
    let timestamp = now_ms();
    let mut request = complete_histogram_request(timestamp);
    for series in &mut request.timeseries {
        series.labels.push(label("instance", "10.0.0.1:9100"));
    }
    let rows = fold(request);
    assert_eq!(rows.len(), 1);

    let string_value = |value: &str| AnyValue {
        value: Some(any_value::Value::StringValue(value.to_string())),
    };
    let key_value = |key: &str, value: &str| KeyValue {
        key: key.to_string(),
        value: Some(string_value(value)),
    };
    let resource = Resource {
        attributes: vec![
            key_value("service.name", "api"),
            key_value("service.instance.id", "10.0.0.1:9100"),
        ],
        ..Default::default()
    };
    let metric = Metric {
        name: "http_req_duration_seconds".to_string(),
        description: String::new(),
        unit: String::new(),
        metadata: vec![],
        data: Some(Data::Histogram(Histogram {
            aggregation_temporality: 2,
            data_points: vec![HistogramDataPoint {
                attributes: vec![
                    key_value("route", "/checkout"),
                    key_value("instance", "10.0.0.1:9100"),
                ],
                start_time_unix_nano: 0,
                time_unix_nano: timestamp as u64 * 1_000_000,
                count: 10,
                sum: Some(12.5),
                bucket_counts: vec![2, 3, 5],
                explicit_bounds: vec![0.5, 1.0],
                exemplars: vec![],
                flags: 0,
                min: None,
                max: None,
            }],
        })),
    };
    let (otlp_rows, _) = flatten_metric(metric, Some(&resource), None).expect("flatten_metric ok");

    assert_eq!(otlp_rows.len(), 1);
    assert_eq!(rows[0].series_fingerprint, otlp_rows[0].series_fingerprint);
    assert_eq!(rows[0].attributes, otlp_rows[0].attributes);
    assert_eq!(
        rows[0].resource_attributes,
        otlp_rows[0].resource_attributes
    );
    assert_eq!(rows[0].histogram_bounds, otlp_rows[0].histogram_bounds);
    assert_eq!(rows[0].histogram_counts, otlp_rows[0].histogram_counts);
}

#[test]
fn folds_one_histogram_row_per_timestamp() {
    let first = now_ms();
    let second = first + 60_000;
    let route = &[("route", "/cart")];
    let rows = fold(WriteRequest {
        timeseries: vec![
            bucket(
                "d",
                route,
                "1",
                vec![sample(1.0, first), sample(4.0, second)],
            ),
            bucket(
                "d",
                route,
                "+Inf",
                vec![sample(3.0, first), sample(9.0, second)],
            ),
            labelled(
                "d_sum",
                route,
                vec![sample(1.5, first), sample(7.5, second)],
            ),
        ],
        metadata: vec![],
    });

    assert_eq!(rows.len(), 2);
    assert!(rows.iter().all(|row| row.metric_type == "histogram"));
    let by_time: HashMap<i64, &KafkaMetricRow> = rows
        .iter()
        .map(|row| (row.timestamp.timestamp_millis(), row))
        .collect();
    assert_eq!(by_time[&first].histogram_counts, vec![1, 2]);
    assert_eq!(by_time[&second].histogram_counts, vec![4, 5]);
    assert_eq!(
        by_time[&first].series_fingerprint,
        by_time[&second].series_fingerprint
    );
}

#[test]
fn folds_partial_bucket_sets_when_inf_and_sum_are_present() {
    let timestamp = now_ms();
    let route = &[("route", "/cart")];
    let rows = fold(WriteRequest {
        timeseries: vec![
            bucket("d", route, "0.5", vec![sample(2.0, timestamp)]),
            bucket("d", route, "+Inf", vec![sample(10.0, timestamp)]),
            labelled("d_sum", route, vec![sample(12.5, timestamp)]),
        ],
        metadata: vec![],
    });

    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].histogram_bounds, vec![0.5]);
    assert_eq!(rows[0].histogram_counts, vec![2, 8]);
    assert_eq!(rows[0].count, 10);
}

#[test]
fn incomplete_histograms_stay_plain_rows() {
    let timestamp = now_ms();
    let route = &[("route", "/cart")];
    let without_inf = WriteRequest {
        timeseries: vec![
            bucket("d", route, "0.5", vec![sample(2.0, timestamp)]),
            bucket("d", route, "1", vec![sample(5.0, timestamp)]),
            labelled("d_count", route, vec![sample(10.0, timestamp)]),
            labelled("d_sum", route, vec![sample(12.5, timestamp)]),
        ],
        metadata: vec![],
    };
    let without_sum = WriteRequest {
        timeseries: vec![
            bucket("d", route, "0.5", vec![sample(2.0, timestamp)]),
            bucket("d", route, "+Inf", vec![sample(10.0, timestamp)]),
            labelled("d_count", route, vec![sample(10.0, timestamp)]),
        ],
        metadata: vec![],
    };
    for (name, request, want) in [
        ("without +Inf", without_inf, 4),
        ("without _sum", without_sum, 3),
    ] {
        let rows = fold(request);
        assert_eq!(rows.len(), want, "{name}: {rows:?}");
        assert!(rows
            .iter()
            .all(|row| row.metric_type == "sum" && row.count == 1));
    }
}

#[test]
fn inconsistent_histograms_stay_plain_rows() {
    let timestamp = now_ms();
    let route = &[("route", "/cart")];
    let count_mismatch = WriteRequest {
        timeseries: vec![
            bucket("d", route, "+Inf", vec![sample(10.0, timestamp)]),
            labelled("d_count", route, vec![sample(11.0, timestamp)]),
            labelled("d_sum", route, vec![sample(12.5, timestamp)]),
        ],
        metadata: vec![],
    };
    let decreasing = WriteRequest {
        timeseries: vec![
            bucket("d", route, "0.5", vec![sample(6.0, timestamp)]),
            bucket("d", route, "1", vec![sample(5.0, timestamp)]),
            bucket("d", route, "+Inf", vec![sample(10.0, timestamp)]),
            labelled("d_sum", route, vec![sample(12.5, timestamp)]),
        ],
        metadata: vec![],
    };
    let fractional = WriteRequest {
        timeseries: vec![
            bucket("d", route, "+Inf", vec![sample(10.5, timestamp)]),
            labelled("d_sum", route, vec![sample(12.5, timestamp)]),
        ],
        metadata: vec![],
    };
    let declared_summary = WriteRequest {
        timeseries: vec![
            labelled("latency_count", route, vec![sample(10.0, timestamp)]),
            labelled("latency_sum", route, vec![sample(12.5, timestamp)]),
        ],
        metadata: vec![MetricMetadata {
            r#type: MetricType::Summary as i32,
            metric_family_name: "latency".to_string(),
            help: String::new(),
            unit: String::new(),
        }],
    };
    for (name, request) in [
        ("count mismatch", count_mismatch),
        ("decreasing buckets", decreasing),
        ("fractional count", fractional),
        ("declared summary", declared_summary),
    ] {
        let rows = fold(request);
        assert!(!rows.is_empty(), "{name}");
        assert_eq!(plain_rows(&rows).len(), rows.len(), "{name}: {rows:?}");
    }

    for (name, count_values, sum_values) in [
        (
            "conflicting duplicate count",
            &[11.0, 10.0][..],
            &[12.5][..],
        ),
        ("conflicting duplicate sum", &[10.0][..], &[13.5, 12.5][..]),
    ] {
        let rows = fold(WriteRequest {
            timeseries: vec![
                bucket("d", route, "+Inf", vec![sample(10.0, timestamp)]),
                labelled(
                    "d_count",
                    route,
                    count_values
                        .iter()
                        .map(|value| sample(*value, timestamp))
                        .collect(),
                ),
                labelled(
                    "d_sum",
                    route,
                    sum_values
                        .iter()
                        .map(|value| sample(*value, timestamp))
                        .collect(),
                ),
            ],
            metadata: vec![],
        });

        assert_eq!(
            rows.len(),
            1 + count_values.len() + sum_values.len(),
            "{name}: {rows:?}"
        );
        assert_eq!(plain_rows(&rows).len(), rows.len(), "{name}: {rows:?}");
    }
}

#[test]
fn different_label_sets_fold_separately() {
    let timestamp = now_ms();
    let mut request = complete_histogram_request(timestamp);
    let other = &[("route", "/cart")];
    request.timeseries.extend(vec![
        bucket(
            "http_req_duration_seconds",
            other,
            "+Inf",
            vec![sample(4.0, timestamp)],
        ),
        labelled(
            "http_req_duration_seconds_sum",
            other,
            vec![sample(1.0, timestamp)],
        ),
    ]);

    let rows = fold(request);

    assert_eq!(rows.len(), 2);
    assert!(rows.iter().all(|row| row.metric_type == "histogram"));
    assert_ne!(rows[0].series_fingerprint, rows[1].series_fingerprint);
    let cart = rows
        .iter()
        .find(|row| row.attributes.get("route").unwrap() == "\"/cart\"")
        .unwrap();
    assert!(cart.histogram_bounds.is_empty());
    assert_eq!(cart.histogram_counts, vec![4]);
}

#[test]
fn stale_component_samples_do_not_block_other_timestamps() {
    let first = now_ms();
    let second = first + 60_000;
    let route = &[("route", "/cart")];
    let rows = fold(WriteRequest {
        timeseries: vec![
            bucket(
                "d",
                route,
                "+Inf",
                vec![sample(3.0, first), sample(f64::NAN, second)],
            ),
            labelled(
                "d_sum",
                route,
                vec![sample(1.5, first), sample(2.5, second)],
            ),
        ],
        metadata: vec![],
    });

    assert_eq!(rows.len(), 2, "{rows:?}");
    assert_eq!(rows[0].metric_type, "histogram");
    assert_eq!(rows[0].timestamp.timestamp_millis(), first);
    assert_eq!(rows[1].metric_type, "sum");
    assert_eq!(rows[1].metric_name, "d_sum");
    assert_eq!(rows[1].timestamp.timestamp_millis(), second);
}

#[test]
fn clamped_timestamps_are_not_folded() {
    let old = (Utc::now() - Duration::days(30)).timestamp_millis();
    let route = &[("route", "/cart")];
    let request = WriteRequest {
        timeseries: vec![
            bucket("d", route, "0.5", vec![sample(2.0, old)]),
            bucket("d", route, "+Inf", vec![sample(10.0, old)]),
            labelled("d_sum", route, vec![sample(12.5, old)]),
        ],
        metadata: vec![],
    };
    let (library_rows, overridden) = write_request_to_kafka_rows(request.clone());
    let rows = fold(request);

    assert_eq!(overridden, 3);
    assert_eq!(rows.len(), 3);
    assert_eq!(plain_rows(&rows).len(), 3);
    assert!(rows
        .iter()
        .all(|row| row.attributes.contains_key("$originalTimestamp")));
    let fingerprints = |rows: &[KafkaMetricRow]| -> Vec<i64> {
        rows.iter().map(|row| row.series_fingerprint).collect()
    };
    assert_eq!(fingerprints(&rows), fingerprints(&library_rows));
}

#[test]
fn normalizes_le_and_quantile_labels_and_refreshes_fingerprints() {
    let timestamp = now_ms();
    let request = WriteRequest {
        timeseries: vec![
            bucket("d", &[], "1.0", vec![sample(2.0, timestamp)]),
            bucket("d", &[], "1e+06", vec![sample(2.0, timestamp)]),
            bucket("d", &[], "1000000", vec![sample(2.0, timestamp)]),
            bucket("d", &[], "+inf", vec![sample(2.0, timestamp)]),
            labelled(
                "latency",
                &[("quantile", "0.50")],
                vec![sample(2.0, timestamp)],
            ),
            bucket("e", &[], "1", vec![sample(2.0, timestamp)]),
        ],
        metadata: vec![],
    };
    let (library_rows, _) = write_request_to_kafka_rows(request.clone());
    let rows = fold(request);

    assert_eq!(rows.len(), 6);
    let le_values: Vec<&str> = rows[..4]
        .iter()
        .map(|row| row.attributes.get("le").unwrap().as_str())
        .collect();
    assert_eq!(
        le_values,
        vec!["\"1\"", "\"1e+06\"", "\"1e+06\"", "\"+Inf\""]
    );
    assert_eq!(rows[4].attributes.get("quantile").unwrap(), "\"0.5\"");
    assert_eq!(
        rows[1].series_fingerprint, rows[2].series_fingerprint,
        "normalized le values share a series"
    );
    assert_ne!(
        rows[0].series_fingerprint, library_rows[0].series_fingerprint,
        "a changed le label gets a new fingerprint"
    );
    assert_eq!(
        rows[5].series_fingerprint, library_rows[5].series_fingerprint,
        "an unchanged le label keeps its fingerprint"
    );
    let (canonical_rows, _) = write_request_to_kafka_rows(WriteRequest {
        timeseries: vec![bucket("d", &[], "1", vec![sample(2.0, timestamp)])],
        metadata: vec![],
    });
    assert_eq!(
        rows[0].series_fingerprint, canonical_rows[0].series_fingerprint,
        "le=1.0 and le=1 are one series"
    );
}

#[test]
fn float_label_normalization_matches_go_shortest_formatting() {
    for (input, want) in [
        ("0.005", "0.005"),
        ("0.5", "0.5"),
        ("1", "1"),
        ("1.0", "1"),
        ("2.5", "2.5"),
        ("10", "10"),
        ("100000", "100000"),
        ("999999.5", "999999.5"),
        ("123456.789", "123456.789"),
        ("1000000", "1e+06"),
        ("1234567.89", "1.23456789e+06"),
        ("1e7", "1e+07"),
        ("1e15", "1e+15"),
        ("1e20", "1e+20"),
        ("1e21", "1e+21"),
        ("0.0001", "0.0001"),
        ("0.00012", "0.00012"),
        ("0.00005", "5e-05"),
        ("7.5e-5", "7.5e-05"),
        ("1.5e-7", "1.5e-07"),
        ("3.0000000000000004", "3.0000000000000004"),
        ("-2.5", "-2.5"),
        ("0", "0"),
        ("+Inf", "+Inf"),
        ("inf", "+Inf"),
        ("-Inf", "-Inf"),
        ("NaN", "NaN"),
        ("not a number", "not a number"),
        ("", ""),
    ] {
        assert_eq!(normalize_float_label(input), want, "input {input:?}");
    }
}
