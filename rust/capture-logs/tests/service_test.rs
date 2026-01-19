use bytes::Bytes;
use capture_logs::service::parse_otel_message;
use opentelemetry_proto::tonic::common::v1::any_value::Value;

#[test]
fn test_parse_single_json_otel_message() {
    let json_data = r#"{"resourceLogs":[{"resource":{"attributes":[]},"scopeLogs":[{"scope":{"name":"test"},"logRecords":[{"timeUnixNano":"1234567890","severityText":"INFO","body":{"stringValue":"test message"}}]}]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    assert_eq!(request.resource_logs.len(), 1);
    assert_eq!(request.resource_logs[0].scope_logs.len(), 1);
    assert_eq!(request.resource_logs[0].scope_logs[0].log_records.len(), 1);
}

#[test]
fn test_parse_single_json_otel_message_with_newlines() {
    let json_data = r#"{"resourceLogs":
        [{"resource":{"attributes":[]},
        "scopeLogs":[{"scope":{"name":"test"},"logRecords":[{"timeUnixNano":"1234567890","severityText":"INFO","body":{"stringValue":"test message"}}]}]}]
    }"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    assert_eq!(request.resource_logs.len(), 1);
    assert_eq!(request.resource_logs[0].scope_logs.len(), 1);
    assert_eq!(request.resource_logs[0].scope_logs[0].log_records.len(), 1);
}

#[test]
fn test_parse_jsonl_otel_message() {
    let jsonl_data = r#"{"resourceLogs":[{"resource":{"attributes":[]},"scopeLogs":[{"scope":{"name":"test1"},"logRecords":[{"timeUnixNano":"1234567890","severityText":"INFO","body":{"stringValue":"message 1"}}]}]}]}
{"resourceLogs":[{"resource":{"attributes":[]},"scopeLogs":[{"scope":{"name":"test2"},"logRecords":[{"timeUnixNano":"1234567891","severityText":"WARN","body":{"stringValue":"message 2"}}]}]}]}
{"resourceLogs":[{"resource":{"attributes":[]},"scopeLogs":[{"scope":{"name":"test3"},"logRecords":[{"timeUnixNano":"1234567892","severityText":"ERROR","body":{"stringValue":"message 3"}}]}]}]}"#;
    let bytes = Bytes::from(jsonl_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    // Should have merged all 3 resource logs
    assert_eq!(request.resource_logs.len(), 3);

    // Verify each resource log has the expected content
    assert_eq!(
        request.resource_logs[0].scope_logs[0]
            .scope
            .as_ref()
            .unwrap()
            .name,
        "test1"
    );
    assert_eq!(
        request.resource_logs[1].scope_logs[0]
            .scope
            .as_ref()
            .unwrap()
            .name,
        "test2"
    );
    assert_eq!(
        request.resource_logs[2].scope_logs[0]
            .scope
            .as_ref()
            .unwrap()
            .name,
        "test3"
    );

    // Verify log records content
    match request.resource_logs[0].scope_logs[0].log_records[0]
        .body
        .as_ref()
        .unwrap()
        .value
        .as_ref()
        .unwrap()
    {
        Value::StringValue(s) => assert_eq!(s, "message 1"),
        _ => panic!("Expected string value"),
    }
    match request.resource_logs[1].scope_logs[0].log_records[0]
        .body
        .as_ref()
        .unwrap()
        .value
        .as_ref()
        .unwrap()
    {
        Value::StringValue(s) => assert_eq!(s, "message 2"),
        _ => panic!("Expected string value"),
    }
    match request.resource_logs[2].scope_logs[0].log_records[0]
        .body
        .as_ref()
        .unwrap()
        .value
        .as_ref()
        .unwrap()
    {
        Value::StringValue(s) => assert_eq!(s, "message 3"),
        _ => panic!("Expected string value"),
    }
}

#[test]
fn test_parse_jsonl_with_empty_lines() {
    let jsonl_data = r#"
{"resourceLogs":[{"resource":{"attributes":[]},"scopeLogs":[{"scope":{"name":"test1"},"logRecords":[{"timeUnixNano":"1234567890","severityText":"INFO","body":{"stringValue":"message 1"}}]}]}]}

{"resourceLogs":[{"resource":{"attributes":[]},"scopeLogs":[{"scope":{"name":"test2"},"logRecords":[{"timeUnixNano":"1234567891","severityText":"WARN","body":{"stringValue":"message 2"}}]}]}]}

"#;
    let bytes = Bytes::from(jsonl_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    // Should have merged both resource logs, ignoring empty lines
    assert_eq!(request.resource_logs.len(), 2);
}

#[test]
fn test_parse_invalid_jsonl() {
    let invalid_jsonl = r#"{"resourceLogs":[]}
invalid json line
{"resourceLogs":[]}"#;
    let bytes = Bytes::from(invalid_jsonl);

    let result = parse_otel_message(&bytes);
    assert!(result.is_err());
}
