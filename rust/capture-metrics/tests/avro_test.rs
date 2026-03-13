use std::collections::HashMap;

use apache_avro::{Codec, Reader, Schema, Writer, ZstandardSettings};
use capture_metrics::avro_schema::AVRO_SCHEMA;
use capture_metrics::metric_record::KafkaMetricRow;
use chrono::{DateTime, Utc};

fn make_row(overrides: impl FnOnce(&mut KafkaMetricRow)) -> KafkaMetricRow {
    let mut row = KafkaMetricRow {
        uuid: "01234567-89ab-cdef-0123-456789abcdef".to_string(),
        trace_id: String::new(),
        span_id: String::new(),
        trace_flags: 0,
        timestamp: Utc::now(),
        observed_timestamp: Utc::now(),
        service_name: "test-service".to_string(),
        metric_name: "cpu.usage".to_string(),
        metric_type: "gauge".to_string(),
        value: 0.75,
        count: 1,
        histogram_bounds: vec![],
        histogram_counts: vec![],
        unit: "1".to_string(),
        aggregation_temporality: String::new(),
        is_monotonic: false,
        resource_attributes: HashMap::new(),
        instrumentation_scope: String::new(),
        attributes: HashMap::new(),
    };
    overrides(&mut row);
    row
}

fn avro_round_trip(rows: &[KafkaMetricRow]) -> Vec<apache_avro::types::Value> {
    let schema = Schema::parse_str(AVRO_SCHEMA).expect("schema parses");
    let mut writer = Writer::with_codec(
        &schema,
        Vec::new(),
        Codec::Zstandard(ZstandardSettings::new(1)),
    );
    for row in rows {
        writer.append_ser(row).expect("append_ser succeeds");
    }
    let payload = writer.into_inner().expect("flush succeeds");

    let reader = Reader::new(&payload[..]).expect("reader opens");
    reader.map(|r| r.expect("record decodes")).collect()
}

fn get_str(val: &apache_avro::types::Value, field: &str) -> String {
    match val {
        apache_avro::types::Value::Record(fields) => {
            for (name, v) in fields {
                if name == field {
                    return match v {
                        apache_avro::types::Value::Union(_, inner) => match inner.as_ref() {
                            apache_avro::types::Value::String(s) => s.clone(),
                            apache_avro::types::Value::Null => String::new(),
                            other => panic!("expected string, got {other:?}"),
                        },
                        apache_avro::types::Value::String(s) => s.clone(),
                        other => panic!("expected string, got {other:?}"),
                    };
                }
            }
            panic!("field {field} not found");
        }
        _ => panic!("expected record"),
    }
}

fn get_double(val: &apache_avro::types::Value, field: &str) -> f64 {
    match val {
        apache_avro::types::Value::Record(fields) => {
            for (name, v) in fields {
                if name == field {
                    return match v {
                        apache_avro::types::Value::Union(_, inner) => match inner.as_ref() {
                            apache_avro::types::Value::Double(d) => *d,
                            apache_avro::types::Value::Null => 0.0,
                            other => panic!("expected double, got {other:?}"),
                        },
                        apache_avro::types::Value::Double(d) => *d,
                        other => panic!("expected double, got {other:?}"),
                    };
                }
            }
            panic!("field {field} not found");
        }
        _ => panic!("expected record"),
    }
}

fn get_long(val: &apache_avro::types::Value, field: &str) -> i64 {
    match val {
        apache_avro::types::Value::Record(fields) => {
            for (name, v) in fields {
                if name == field {
                    return match v {
                        apache_avro::types::Value::Union(_, inner) => match inner.as_ref() {
                            apache_avro::types::Value::Long(l) => *l,
                            apache_avro::types::Value::TimestampMicros(l) => *l,
                            apache_avro::types::Value::Null => 0,
                            other => panic!("expected long, got {other:?}"),
                        },
                        apache_avro::types::Value::Long(l) => *l,
                        other => panic!("expected long, got {other:?}"),
                    };
                }
            }
            panic!("field {field} not found");
        }
        _ => panic!("expected record"),
    }
}

fn get_bool(val: &apache_avro::types::Value, field: &str) -> bool {
    match val {
        apache_avro::types::Value::Record(fields) => {
            for (name, v) in fields {
                if name == field {
                    return match v {
                        apache_avro::types::Value::Union(_, inner) => match inner.as_ref() {
                            apache_avro::types::Value::Boolean(b) => *b,
                            apache_avro::types::Value::Null => false,
                            other => panic!("expected bool, got {other:?}"),
                        },
                        apache_avro::types::Value::Boolean(b) => *b,
                        other => panic!("expected bool, got {other:?}"),
                    };
                }
            }
            panic!("field {field} not found");
        }
        _ => panic!("expected record"),
    }
}

#[test]
fn test_avro_round_trip_gauge() {
    let row = make_row(|r| {
        r.metric_name = "system.cpu.utilization".to_string();
        r.metric_type = "gauge".to_string();
        r.value = 0.85;
        r.unit = "1".to_string();
        r.service_name = "my-service".to_string();
    });

    let results = avro_round_trip(&[row]);
    assert_eq!(results.len(), 1);

    let val = &results[0];
    assert_eq!(get_str(val, "metric_name"), "system.cpu.utilization");
    assert_eq!(get_str(val, "metric_type"), "gauge");
    assert_eq!(get_double(val, "value"), 0.85);
    assert_eq!(get_str(val, "unit"), "1");
    assert_eq!(get_str(val, "service_name"), "my-service");
    assert_eq!(get_long(val, "count"), 1);
    assert_eq!(get_bool(val, "is_monotonic"), false);
}

#[test]
fn test_avro_round_trip_sum_monotonic() {
    let row = make_row(|r| {
        r.metric_name = "http.requests.total".to_string();
        r.metric_type = "sum".to_string();
        r.value = 42.0;
        r.aggregation_temporality = "cumulative".to_string();
        r.is_monotonic = true;
    });

    let results = avro_round_trip(&[row]);
    assert_eq!(results.len(), 1);

    let val = &results[0];
    assert_eq!(get_str(val, "metric_type"), "sum");
    assert_eq!(get_double(val, "value"), 42.0);
    assert_eq!(get_str(val, "aggregation_temporality"), "cumulative");
    assert_eq!(get_bool(val, "is_monotonic"), true);
}

#[test]
fn test_avro_round_trip_histogram() {
    let row = make_row(|r| {
        r.metric_name = "http.duration".to_string();
        r.metric_type = "histogram".to_string();
        r.value = 5432.1;
        r.count = 100;
        r.histogram_bounds = vec![1.0, 5.0, 10.0, 50.0, 100.0];
        r.histogram_counts = vec![10, 20, 30, 25, 10, 5];
        r.aggregation_temporality = "delta".to_string();
    });

    let results = avro_round_trip(&[row]);
    assert_eq!(results.len(), 1);

    let val = &results[0];
    assert_eq!(get_str(val, "metric_type"), "histogram");
    assert_eq!(get_double(val, "value"), 5432.1);
    assert_eq!(get_long(val, "count"), 100);
    assert_eq!(get_str(val, "aggregation_temporality"), "delta");
}

#[test]
fn test_avro_round_trip_with_attributes() {
    let mut resource_attrs = HashMap::new();
    resource_attrs.insert("service.name".to_string(), "\"web-server\"".to_string());
    resource_attrs.insert("host.name".to_string(), "\"prod-01\"".to_string());

    let mut attrs = HashMap::new();
    attrs.insert("http.method".to_string(), "\"GET\"".to_string());
    attrs.insert("http.status_code".to_string(), "200".to_string());

    let row = make_row(|r| {
        r.resource_attributes = resource_attrs.clone();
        r.attributes = attrs.clone();
        r.instrumentation_scope = "otel-sdk@1.0.0".to_string();
    });

    let results = avro_round_trip(&[row]);
    assert_eq!(results.len(), 1);

    let val = &results[0];
    assert_eq!(get_str(val, "instrumentation_scope"), "otel-sdk@1.0.0");
}

#[test]
fn test_avro_round_trip_multiple_rows() {
    let rows: Vec<KafkaMetricRow> = (0..5)
        .map(|i| {
            make_row(|r| {
                r.metric_name = format!("metric_{i}");
                r.value = i as f64;
            })
        })
        .collect();

    let results = avro_round_trip(&rows);
    assert_eq!(results.len(), 5);

    for (i, val) in results.iter().enumerate() {
        assert_eq!(get_str(val, "metric_name"), format!("metric_{i}"));
        assert_eq!(get_double(val, "value"), i as f64);
    }
}

#[test]
fn test_avro_round_trip_preserves_timestamp() {
    let ts = DateTime::parse_from_rfc3339("2025-01-15T10:30:00Z")
        .unwrap()
        .with_timezone(&Utc);

    let row = make_row(|r| {
        r.timestamp = ts;
        r.observed_timestamp = ts;
    });

    let results = avro_round_trip(&[row]);
    assert_eq!(results.len(), 1);

    let val = &results[0];
    let ts_micros = ts.timestamp_micros();
    assert_eq!(get_long(val, "timestamp"), ts_micros);
    assert_eq!(get_long(val, "observed_timestamp"), ts_micros);
}

#[test]
fn test_avro_round_trip_empty_fields() {
    let row = make_row(|_| {});

    let results = avro_round_trip(&[row]);
    assert_eq!(results.len(), 1);

    let val = &results[0];
    // trace_id and span_id are bytes in avro schema, so they round-trip as bytes not strings
    assert_eq!(get_str(val, "aggregation_temporality"), "");
    assert_eq!(get_str(val, "instrumentation_scope"), "");
}

#[test]
fn test_avro_schema_is_valid() {
    let schema = Schema::parse_str(AVRO_SCHEMA);
    assert!(
        schema.is_ok(),
        "AVRO schema should parse: {:?}",
        schema.err()
    );
}
