use bytes::Bytes;
use capture_metrics::service::{parse_otel_message, patch_otel_json};
use prost::Message;
use serde_json::json;

#[test]
fn test_parse_single_json_gauge_metric() {
    let json_data = r#"{"resourceMetrics":[{"resource":{"attributes":[]},"scopeMetrics":[{"scope":{"name":"test"},"metrics":[{"name":"cpu.usage","unit":"1","gauge":{"dataPoints":[{"timeUnixNano":"1234567890","asDouble":0.75,"attributes":[]}]}}]}]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    assert_eq!(request.resource_metrics.len(), 1);
    assert_eq!(request.resource_metrics[0].scope_metrics.len(), 1);
    assert_eq!(request.resource_metrics[0].scope_metrics[0].metrics.len(), 1);
    assert_eq!(
        request.resource_metrics[0].scope_metrics[0].metrics[0].name,
        "cpu.usage"
    );
}

#[test]
fn test_parse_single_json_with_newlines() {
    let json_data = r#"{"resourceMetrics":
        [{"resource":{"attributes":[]},
        "scopeMetrics":[{"scope":{"name":"test"},"metrics":[{"name":"mem.used","unit":"bytes","gauge":{"dataPoints":[{"timeUnixNano":"1234567890","asDouble":1024.0}]}}]}]}]
    }"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    assert_eq!(request.resource_metrics.len(), 1);
    assert_eq!(request.resource_metrics[0].scope_metrics[0].metrics.len(), 1);
}

#[test]
fn test_parse_jsonl_metrics() {
    let jsonl_data = r#"{"resourceMetrics":[{"resource":{"attributes":[]},"scopeMetrics":[{"scope":{"name":"scope1"},"metrics":[{"name":"metric1","gauge":{"dataPoints":[{"timeUnixNano":"1234567890","asDouble":1.0}]}}]}]}]}
{"resourceMetrics":[{"resource":{"attributes":[]},"scopeMetrics":[{"scope":{"name":"scope2"},"metrics":[{"name":"metric2","gauge":{"dataPoints":[{"timeUnixNano":"1234567891","asDouble":2.0}]}}]}]}]}
{"resourceMetrics":[{"resource":{"attributes":[]},"scopeMetrics":[{"scope":{"name":"scope3"},"metrics":[{"name":"metric3","gauge":{"dataPoints":[{"timeUnixNano":"1234567892","asDouble":3.0}]}}]}]}]}"#;
    let bytes = Bytes::from(jsonl_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    assert_eq!(request.resource_metrics.len(), 3);
    assert_eq!(
        request.resource_metrics[0].scope_metrics[0].metrics[0].name,
        "metric1"
    );
    assert_eq!(
        request.resource_metrics[1].scope_metrics[0].metrics[0].name,
        "metric2"
    );
    assert_eq!(
        request.resource_metrics[2].scope_metrics[0].metrics[0].name,
        "metric3"
    );
}

#[test]
fn test_parse_jsonl_with_empty_lines() {
    let jsonl_data = r#"
{"resourceMetrics":[{"resource":{"attributes":[]},"scopeMetrics":[{"scope":{"name":"test1"},"metrics":[{"name":"m1","gauge":{"dataPoints":[{"asDouble":1.0}]}}]}]}]}

{"resourceMetrics":[{"resource":{"attributes":[]},"scopeMetrics":[{"scope":{"name":"test2"},"metrics":[{"name":"m2","gauge":{"dataPoints":[{"asDouble":2.0}]}}]}]}]}

"#;
    let bytes = Bytes::from(jsonl_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());
    assert_eq!(result.unwrap().resource_metrics.len(), 2);
}

#[test]
fn test_parse_invalid_jsonl() {
    let invalid_jsonl = r#"{"resourceMetrics":[]}
invalid json line
{"resourceMetrics":[]}"#;
    let bytes = Bytes::from(invalid_jsonl);

    let result = parse_otel_message(&bytes);
    assert!(result.is_err());
}

#[test]
fn test_parse_empty_resource_metrics() {
    let json_data = r#"{"resourceMetrics":[]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());
    assert_eq!(result.unwrap().resource_metrics.len(), 0);
}

#[test]
fn test_parse_empty_scope_metrics() {
    let json_data =
        r#"{"resourceMetrics":[{"resource":{"attributes":[]},"scopeMetrics":[]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    assert_eq!(request.resource_metrics.len(), 1);
    assert_eq!(request.resource_metrics[0].scope_metrics.len(), 0);
}

#[test]
fn test_parse_empty_metrics_array() {
    let json_data = r#"{"resourceMetrics":[{"resource":{"attributes":[]},"scopeMetrics":[{"scope":{"name":"test"},"metrics":[]}]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    assert_eq!(request.resource_metrics[0].scope_metrics[0].metrics.len(), 0);
}

#[test]
fn test_parse_empty_jsonl() {
    let jsonl_data = "\n\n\n";
    let bytes = Bytes::from(jsonl_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());
    assert_eq!(result.unwrap().resource_metrics.len(), 0);
}

#[test]
fn test_parse_protobuf_empty_request() {
    use opentelemetry_proto::tonic::collector::metrics::v1::ExportMetricsServiceRequest;

    let empty_request = ExportMetricsServiceRequest {
        resource_metrics: vec![],
    };

    let mut buf = Vec::new();
    empty_request.encode(&mut buf).unwrap();
    let bytes = Bytes::from(buf);

    let decoded = ExportMetricsServiceRequest::decode(bytes.as_ref()).unwrap();
    assert_eq!(decoded.resource_metrics.len(), 0);
}

#[test]
fn test_parse_protobuf_gauge_metric() {
    use opentelemetry_proto::tonic::{
        collector::metrics::v1::ExportMetricsServiceRequest,
        common::v1::{any_value, AnyValue, KeyValue},
        metrics::v1::{
            metric, Gauge, Metric, NumberDataPoint, ResourceMetrics, ScopeMetrics,
            number_data_point,
        },
        resource::v1::Resource,
    };

    let request = ExportMetricsServiceRequest {
        resource_metrics: vec![ResourceMetrics {
            resource: Some(Resource {
                attributes: vec![KeyValue {
                    key: "service.name".to_string(),
                    value: Some(AnyValue {
                        value: Some(any_value::Value::StringValue("my-service".to_string())),
                    }),
                }],
                dropped_attributes_count: 0,
            }),
            scope_metrics: vec![ScopeMetrics {
                scope: None,
                metrics: vec![Metric {
                    name: "system.cpu.utilization".to_string(),
                    description: "CPU utilization".to_string(),
                    unit: "1".to_string(),
                    metadata: vec![],
                    data: Some(metric::Data::Gauge(Gauge {
                        data_points: vec![NumberDataPoint {
                            attributes: vec![KeyValue {
                                key: "cpu".to_string(),
                                value: Some(AnyValue {
                                    value: Some(any_value::Value::StringValue(
                                        "cpu0".to_string(),
                                    )),
                                }),
                            }],
                            time_unix_nano: 1700000000000000000,
                            start_time_unix_nano: 0,
                            value: Some(number_data_point::Value::AsDouble(0.85)),
                            exemplars: vec![],
                            flags: 0,
                        }],
                    })),
                }],
                schema_url: String::new(),
            }],
            schema_url: String::new(),
        }],
    };

    let mut buf = Vec::new();
    request.encode(&mut buf).unwrap();
    let bytes = Bytes::from(buf);

    let decoded = ExportMetricsServiceRequest::decode(bytes.as_ref()).unwrap();
    assert_eq!(decoded.resource_metrics.len(), 1);

    let metric = &decoded.resource_metrics[0].scope_metrics[0].metrics[0];
    assert_eq!(metric.name, "system.cpu.utilization");
    assert_eq!(metric.unit, "1");

    match metric.data.as_ref().unwrap() {
        metric::Data::Gauge(gauge) => {
            assert_eq!(gauge.data_points.len(), 1);
            match gauge.data_points[0].value.as_ref().unwrap() {
                number_data_point::Value::AsDouble(v) => assert_eq!(*v, 0.85),
                _ => panic!("Expected double value"),
            }
        }
        _ => panic!("Expected gauge metric"),
    }
}

#[test]
fn test_parse_json_sum_metric() {
    let json_data = r#"{"resourceMetrics":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"web-server"}}]},"scopeMetrics":[{"scope":{"name":"otel-sdk"},"metrics":[{"name":"http.server.request.count","unit":"1","sum":{"dataPoints":[{"timeUnixNano":"1700000000000000000","asInt":"42","attributes":[{"key":"http.method","value":{"stringValue":"GET"}}]}],"aggregationTemporality":2,"isMonotonic":true}}]}]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    let metric = &request.resource_metrics[0].scope_metrics[0].metrics[0];
    assert_eq!(metric.name, "http.server.request.count");

    match metric.data.as_ref().unwrap() {
        opentelemetry_proto::tonic::metrics::v1::metric::Data::Sum(sum) => {
            assert!(sum.is_monotonic);
            assert_eq!(sum.aggregation_temporality, 2); // CUMULATIVE
            assert_eq!(sum.data_points.len(), 1);
        }
        _ => panic!("Expected sum metric"),
    }
}

#[test]
fn test_parse_json_histogram_metric() {
    let json_data = r#"{"resourceMetrics":[{"resource":{"attributes":[]},"scopeMetrics":[{"scope":{"name":"test"},"metrics":[{"name":"http.server.duration","unit":"ms","histogram":{"dataPoints":[{"timeUnixNano":"1700000000000000000","count":"100","sum":5432.1,"bucketCounts":["10","20","30","25","10","5"],"explicitBounds":[1.0,5.0,10.0,50.0,100.0]}],"aggregationTemporality":2}}]}]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    let metric = &request.resource_metrics[0].scope_metrics[0].metrics[0];
    assert_eq!(metric.name, "http.server.duration");

    match metric.data.as_ref().unwrap() {
        opentelemetry_proto::tonic::metrics::v1::metric::Data::Histogram(hist) => {
            assert_eq!(hist.data_points.len(), 1);
            let dp = &hist.data_points[0];
            assert_eq!(dp.count, 100);
            assert_eq!(dp.sum, Some(5432.1));
            assert_eq!(dp.explicit_bounds, vec![1.0, 5.0, 10.0, 50.0, 100.0]);
            assert_eq!(dp.bucket_counts, vec![10, 20, 30, 25, 10, 5]);
        }
        _ => panic!("Expected histogram metric"),
    }
}

#[test]
fn test_parse_json_with_empty_attribute_values() {
    let json_data = r#"{"resourceMetrics":[{"resource":{"attributes":[{"key":"test_key","value":{}}]},"scopeMetrics":[{"scope":{"name":"test"},"metrics":[{"name":"m1","gauge":{"dataPoints":[{"timeUnixNano":"1234567890","asDouble":1.0,"attributes":[{"key":"dp_key","value":{}}]}]}}]}]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    // Resource attribute with empty value should be None after patching
    assert!(request.resource_metrics[0]
        .resource
        .as_ref()
        .unwrap()
        .attributes[0]
        .value
        .is_none());

    // Data point attribute with empty value should be None after patching
    match request.resource_metrics[0].scope_metrics[0].metrics[0]
        .data
        .as_ref()
        .unwrap()
    {
        opentelemetry_proto::tonic::metrics::v1::metric::Data::Gauge(gauge) => {
            assert!(gauge.data_points[0].attributes[0].value.is_none());
        }
        _ => panic!("Expected gauge"),
    }
}

#[test]
fn test_parse_multiple_metrics_in_one_scope() {
    let json_data = r#"{"resourceMetrics":[{"resource":{"attributes":[]},"scopeMetrics":[{"scope":{"name":"test"},"metrics":[{"name":"cpu","gauge":{"dataPoints":[{"asDouble":0.5}]}},{"name":"mem","gauge":{"dataPoints":[{"asDouble":1024.0}]}},{"name":"disk","gauge":{"dataPoints":[{"asDouble":50.0}]}}]}]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    let metrics = &request.resource_metrics[0].scope_metrics[0].metrics;
    assert_eq!(metrics.len(), 3);
    assert_eq!(metrics[0].name, "cpu");
    assert_eq!(metrics[1].name, "mem");
    assert_eq!(metrics[2].name, "disk");
}

// patch_otel_json tests

#[test]
fn test_patch_otel_json_empty_value() {
    let mut json = json!({"key": "test", "value": {}});
    patch_otel_json(&mut json);
    assert_eq!(json["key"], "test");
    assert!(json["value"].is_null());
}

#[test]
fn test_patch_otel_json_non_empty_values() {
    let mut json = json!({"value": {"stringValue": "test"}});
    patch_otel_json(&mut json);
    assert_eq!(json["value"]["stringValue"], "test");
}

#[test]
fn test_patch_otel_json_nested_empty_values() {
    let mut json = json!({
        "resourceMetrics": [{
            "resource": {
                "attributes": [{"key": "k", "value": {}}]
            },
            "scopeMetrics": [{
                "metrics": [{
                    "gauge": {
                        "dataPoints": [{
                            "attributes": [{"key": "dp_k", "value": {}}]
                        }]
                    }
                }]
            }]
        }]
    });

    patch_otel_json(&mut json);

    assert!(json["resourceMetrics"][0]["resource"]["attributes"][0]["value"].is_null());
    assert!(json["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]["gauge"]["dataPoints"][0]["attributes"][0]["value"].is_null());
}

#[test]
fn test_patch_otel_json_array_with_empty_values() {
    let mut json = json!([{"value": {}}, {"value": {"stringValue": "valid"}}]);
    patch_otel_json(&mut json);
    assert!(json[0]["value"].is_null());
    assert_eq!(json[1]["value"]["stringValue"], "valid");
}
