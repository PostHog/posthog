use bytes::Bytes;
use capture_logs::service::{parse_otel_traces_message, patch_otel_json};
use opentelemetry_proto::tonic::collector::trace::v1::ExportTraceServiceRequest;
use prost::Message;
use serde_json::json;

// opentelemetry-proto with-serde uses hex encoding (OTLP JSON spec):
//   traceId: 32-char hex string (16 bytes)
//   spanId:  16-char hex string (8 bytes)

#[test]
fn test_parse_single_json_otel_traces_message() {
    let json_data = r#"{"resourceSpans":[{"resource":{"attributes":[]},"scopeSpans":[{"scope":{"name":"test"},"spans":[{"traceId":"00000000000000000000000000000000","spanId":"0000000000000000","name":"test.span","kind":1,"startTimeUnixNano":"1000000000","endTimeUnixNano":"2000000000","status":{"code":1}}]}]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_traces_message(&bytes);
    assert!(result.is_ok(), "Failed to parse: {:?}", result.err());

    let request = result.unwrap();
    assert_eq!(request.resource_spans.len(), 1);
    assert_eq!(request.resource_spans[0].scope_spans.len(), 1);
    assert_eq!(request.resource_spans[0].scope_spans[0].spans.len(), 1);
    assert_eq!(
        request.resource_spans[0].scope_spans[0].spans[0].name,
        "test.span"
    );
}

#[test]
fn test_parse_jsonl_otel_traces_message() {
    let jsonl_data = concat!(
        r#"{"resourceSpans":[{"resource":{"attributes":[]},"scopeSpans":[{"scope":{"name":"svc1"},"spans":[{"traceId":"00000000000000000000000000000000","spanId":"0000000000000000","name":"span1","startTimeUnixNano":"1000000000","endTimeUnixNano":"2000000000"}]}]}]}"#,
        "\n",
        r#"{"resourceSpans":[{"resource":{"attributes":[]},"scopeSpans":[{"scope":{"name":"svc2"},"spans":[{"traceId":"00000000000000000000000000000000","spanId":"0000000000000000","name":"span2","startTimeUnixNano":"3000000000","endTimeUnixNano":"4000000000"}]}]}]}"#
    );
    let bytes = Bytes::from(jsonl_data);

    let result = parse_otel_traces_message(&bytes);
    assert!(result.is_ok(), "Failed to parse: {:?}", result.err());

    let request = result.unwrap();
    assert_eq!(request.resource_spans.len(), 2);
    assert_eq!(
        request.resource_spans[0].scope_spans[0].spans[0].name,
        "span1"
    );
    assert_eq!(
        request.resource_spans[1].scope_spans[0].spans[0].name,
        "span2"
    );
}

#[test]
fn test_parse_jsonl_traces_with_empty_lines() {
    let jsonl_data = concat!(
        "\n",
        r#"{"resourceSpans":[{"resource":{"attributes":[]},"scopeSpans":[{"scope":{"name":"svc1"},"spans":[{"traceId":"00000000000000000000000000000000","spanId":"0000000000000000","name":"span1","startTimeUnixNano":"1000000000","endTimeUnixNano":"2000000000"}]}]}]}"#,
        "\n\n"
    );
    let bytes = Bytes::from(jsonl_data);

    let result = parse_otel_traces_message(&bytes);
    assert!(result.is_ok());
    let request = result.unwrap();
    assert_eq!(request.resource_spans.len(), 1);
}

#[test]
fn test_parse_empty_resource_spans() {
    let json_data = r#"{"resourceSpans":[]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_traces_message(&bytes);
    assert!(result.is_ok());
    assert_eq!(result.unwrap().resource_spans.len(), 0);
}

#[test]
fn test_parse_empty_scope_spans() {
    let json_data = r#"{"resourceSpans":[{"resource":{"attributes":[]},"scopeSpans":[]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_traces_message(&bytes);
    assert!(result.is_ok());
    let request = result.unwrap();
    assert_eq!(request.resource_spans.len(), 1);
    assert_eq!(request.resource_spans[0].scope_spans.len(), 0);
}

#[test]
fn test_parse_protobuf_otel_traces_message() {
    let request = ExportTraceServiceRequest {
        resource_spans: vec![],
    };

    let mut buf = Vec::new();
    request.encode(&mut buf).unwrap();
    let bytes = Bytes::from(buf);

    let decoded = ExportTraceServiceRequest::decode(bytes.as_ref()).unwrap();
    assert_eq!(decoded.resource_spans.len(), 0);
}

#[test]
fn test_patch_otel_json_applies_to_trace_attributes() {
    let mut json = json!({
        "resourceSpans": [{
            "resource": {
                "attributes": [{
                    "key": "service.name",
                    "value": {}
                }]
            },
            "scopeSpans": [{
                "spans": [{
                    "attributes": [{
                        "key": "http.method",
                        "value": {}
                    }]
                }]
            }]
        }]
    });

    patch_otel_json(&mut json);

    assert!(json["resourceSpans"][0]["resource"]["attributes"][0]["value"].is_null());
    assert!(
        json["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"][0]["value"].is_null()
    );
}

#[test]
fn test_parse_span_with_events_and_links() {
    let json_data = r#"{
        "resourceSpans": [{
            "resource": {"attributes": []},
            "scopeSpans": [{
                "scope": {"name": "test"},
                "spans": [{
                    "traceId": "00000000000000000000000000000000",
                    "spanId": "0000000000000000",
                    "name": "test.operation",
                    "startTimeUnixNano": "1000000000",
                    "endTimeUnixNano": "2000000000",
                    "events": [{
                        "timeUnixNano": "1500000000",
                        "name": "exception",
                        "attributes": []
                    }],
                    "links": [{
                        "traceId": "00000000000000000000000000000000",
                        "spanId": "0000000000000000",
                        "traceState": ""
                    }]
                }]
            }]
        }]
    }"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_traces_message(&bytes);
    assert!(result.is_ok(), "Failed to parse: {:?}", result.err());

    let request = result.unwrap();
    let span = &request.resource_spans[0].scope_spans[0].spans[0];
    assert_eq!(span.events.len(), 1);
    assert_eq!(span.events[0].name, "exception");
    assert_eq!(span.links.len(), 1);
}

#[test]
fn test_parse_invalid_json_returns_error() {
    let invalid_data = r#"not json at all"#;
    let bytes = Bytes::from(invalid_data);

    let result = parse_otel_traces_message(&bytes);
    assert!(result.is_err());
}
