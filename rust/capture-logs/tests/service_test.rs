use bytes::Bytes;
use capture_logs::service::{parse_otel_message, patch_otel_json};
use opentelemetry_proto::tonic::common::v1::any_value::Value;
use prost::Message;
use serde_json::json;

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

#[test]
fn test_parse_otel_message_with_empty_body() {
    let json_data = r#"{"resourceLogs":[{"resource":{"attributes":[]},"scopeLogs":[{"scope":{"name":"test"},"logRecords":[{"timeUnixNano":"1234567890","severityText":"INFO","body":{}}]}]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    assert_eq!(request.resource_logs.len(), 1);
    assert_eq!(request.resource_logs[0].scope_logs.len(), 1);
    assert_eq!(request.resource_logs[0].scope_logs[0].log_records.len(), 1);

    // Body should be None after patching empty object to null
    assert!(request.resource_logs[0].scope_logs[0].log_records[0]
        .body
        .is_none());
}

#[test]
fn test_parse_otel_message_with_empty_value_in_attributes() {
    let json_data = r#"{"resourceLogs":[{"resource":{"attributes":[{"key":"test_key","value":{}}]},"scopeLogs":[{"scope":{"name":"test"},"logRecords":[{"timeUnixNano":"1234567890","severityText":"INFO","body":{"stringValue":"test message"},"attributes":[{"key":"attr_key","value":{}}]}]}]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    assert_eq!(request.resource_logs.len(), 1);
    assert_eq!(request.resource_logs[0].scope_logs.len(), 1);
    assert_eq!(request.resource_logs[0].scope_logs[0].log_records.len(), 1);

    // Resource attribute with empty value should be None after patching
    assert_eq!(
        request.resource_logs[0]
            .resource
            .as_ref()
            .unwrap()
            .attributes
            .len(),
        1
    );
    assert!(request.resource_logs[0]
        .resource
        .as_ref()
        .unwrap()
        .attributes[0]
        .value
        .is_none());

    // Log record attribute with empty value should be None after patching
    assert_eq!(
        request.resource_logs[0].scope_logs[0].log_records[0]
            .attributes
            .len(),
        1
    );
    assert!(
        request.resource_logs[0].scope_logs[0].log_records[0].attributes[0]
            .value
            .is_none()
    );
}

#[test]
fn test_parse_otel_message_with_mixed_empty_and_valid_values() {
    let json_data = r#"{"resourceLogs":[{"resource":{"attributes":[{"key":"valid_key","value":{"stringValue":"valid_value"}},{"key":"empty_key","value":{}}]},"scopeLogs":[{"scope":{"name":"test"},"logRecords":[{"timeUnixNano":"1234567890","severityText":"INFO","body":{},"attributes":[{"key":"valid_attr","value":{"intValue":42}},{"key":"empty_attr","value":{}}]}]}]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    let resource = request.resource_logs[0].resource.as_ref().unwrap();
    let log_record = &request.resource_logs[0].scope_logs[0].log_records[0];

    // Resource attributes: valid one should have value, empty one should be None
    assert_eq!(resource.attributes.len(), 2);
    match resource.attributes[0]
        .value
        .as_ref()
        .unwrap()
        .value
        .as_ref()
        .unwrap()
    {
        Value::StringValue(s) => assert_eq!(s, "valid_value"),
        _ => panic!("Expected string value"),
    }
    assert!(resource.attributes[1].value.is_none());

    // Body should be None after patching
    assert!(log_record.body.is_none());

    // Log record attributes: valid one should have value, empty one should be None
    assert_eq!(log_record.attributes.len(), 2);
    match log_record.attributes[0]
        .value
        .as_ref()
        .unwrap()
        .value
        .as_ref()
        .unwrap()
    {
        Value::IntValue(i) => assert_eq!(*i, 42),
        _ => panic!("Expected int value"),
    }
    assert!(log_record.attributes[1].value.is_none());
}

#[test]
fn test_parse_otel_message_with_nested_empty_values() {
    // Test that empty values in nested structures are also patched
    let json_data = r#"{"resourceLogs":[{"resource":{"attributes":[]},"scopeLogs":[{"scope":{"name":"test"},"logRecords":[{"timeUnixNano":"1234567890","severityText":"INFO","body":{"kvlistValue":{"values":[{"key":"nested_key","value":{}}]}},"attributes":[{"key":"nested_attr","value":{"kvlistValue":{"values":[{"key":"inner_key","value":{}}]}}}]}]}]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    assert_eq!(request.resource_logs.len(), 1);
    assert_eq!(request.resource_logs[0].scope_logs.len(), 1);
    assert_eq!(request.resource_logs[0].scope_logs[0].log_records.len(), 1);

    // The parsing should succeed even with nested empty values that get patched to null
    let log_record = &request.resource_logs[0].scope_logs[0].log_records[0];
    assert!(log_record.body.is_some());
    assert_eq!(log_record.attributes.len(), 1);
}

#[test]
fn test_patch_otel_json_empty_value() {
    let mut json = json!({
        "key": "test",
        "value": {}
    });

    patch_otel_json(&mut json);

    assert_eq!(json["key"], "test");
    assert!(json["value"].is_null());
}

#[test]
fn test_patch_otel_json_empty_body() {
    let mut json = json!({
        "timeUnixNano": "1234567890",
        "body": {}
    });

    patch_otel_json(&mut json);

    assert_eq!(json["timeUnixNano"], "1234567890");
    assert!(json["body"].is_null());
}

#[test]
fn test_patch_otel_json_non_empty_values() {
    let mut json = json!({
        "value": {
            "stringValue": "test"
        },
        "body": {
            "intValue": 42
        }
    });

    patch_otel_json(&mut json);

    // Non-empty values should remain unchanged
    assert_eq!(json["value"]["stringValue"], "test");
    assert_eq!(json["body"]["intValue"], 42);
}

#[test]
fn test_patch_otel_json_nested_empty_values() {
    let mut json = json!({
        "resourceLogs": [{
            "resource": {
                "attributes": [{
                    "key": "test_key",
                    "value": {}
                }]
            },
            "scopeLogs": [{
                "logRecords": [{
                    "body": {},
                    "attributes": [{
                        "key": "attr_key",
                        "value": {}
                    }]
                }]
            }]
        }]
    });

    patch_otel_json(&mut json);

    // All empty values and bodies should be patched to null
    assert!(json["resourceLogs"][0]["resource"]["attributes"][0]["value"].is_null());
    assert!(json["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"].is_null());
    assert!(
        json["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["attributes"][0]["value"]
            .is_null()
    );
}

#[test]
fn test_patch_otel_json_array_with_empty_values() {
    let mut json = json!([
        {
            "value": {}
        },
        {
            "body": {}
        },
        {
            "value": {
                "stringValue": "valid"
            }
        }
    ]);

    patch_otel_json(&mut json);

    // Empty objects should be patched to null
    assert!(json[0]["value"].is_null());
    assert!(json[1]["body"].is_null());
    // Valid values should remain unchanged
    assert_eq!(json[2]["value"]["stringValue"], "valid");
}

#[test]
fn test_patch_otel_json_mixed_empty_and_non_empty() {
    let mut json = json!({
        "logRecord": {
            "body": {},
            "attributes": [
                {
                    "key": "empty_attr",
                    "value": {}
                },
                {
                    "key": "valid_attr",
                    "value": {
                        "stringValue": "test_value"
                    }
                }
            ]
        }
    });

    patch_otel_json(&mut json);

    // Empty body should be null
    assert!(json["logRecord"]["body"].is_null());
    // Empty attribute value should be null
    assert!(json["logRecord"]["attributes"][0]["value"].is_null());
    // Valid attribute value should remain unchanged
    assert_eq!(
        json["logRecord"]["attributes"][1]["value"]["stringValue"],
        "test_value"
    );
}

// Tests for empty request handling - verifying 200 OK with no log records produced

#[test]
fn test_parse_empty_json_otel_message() {
    // Empty resourceLogs array - valid OTEL message with no logs
    let json_data = r#"{"resourceLogs":[]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    assert_eq!(request.resource_logs.len(), 0);
}

#[test]
fn test_parse_empty_scope_logs_otel_message() {
    // Resource with empty scopeLogs array
    let json_data = r#"{"resourceLogs":[{"resource":{"attributes":[]},"scopeLogs":[]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    assert_eq!(request.resource_logs.len(), 1);
    assert_eq!(request.resource_logs[0].scope_logs.len(), 0);
}

#[test]
fn test_parse_empty_log_records_otel_message() {
    // Scope with empty logRecords array
    let json_data = r#"{"resourceLogs":[{"resource":{"attributes":[]},"scopeLogs":[{"scope":{"name":"test"},"logRecords":[]}]}]}"#;
    let bytes = Bytes::from(json_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    assert_eq!(request.resource_logs.len(), 1);
    assert_eq!(request.resource_logs[0].scope_logs.len(), 1);
    assert_eq!(request.resource_logs[0].scope_logs[0].log_records.len(), 0);
}

#[test]
fn test_parse_empty_protobuf_otel_message() {
    // Empty ExportLogsServiceRequest in protobuf format
    use opentelemetry_proto::tonic::collector::logs::v1::ExportLogsServiceRequest;

    let empty_request = ExportLogsServiceRequest {
        resource_logs: vec![],
    };

    let mut buf = Vec::new();
    empty_request.encode(&mut buf).unwrap();
    let bytes = Bytes::from(buf);

    // parse_otel_message tries protobuf first via the endpoint, but here we test JSON parsing
    // So let's verify the protobuf decodes correctly
    let decoded = ExportLogsServiceRequest::decode(bytes.as_ref()).unwrap();
    assert_eq!(decoded.resource_logs.len(), 0);
}

#[test]
fn test_count_log_records_empty_resource_logs() {
    let json_data = r#"{"resourceLogs":[]}"#;
    let bytes = Bytes::from(json_data);

    let request = parse_otel_message(&bytes).unwrap();

    // Simulate the row counting logic from export_logs_http
    let mut row_count = 0;
    for resource_logs in &request.resource_logs {
        for scope_logs in &resource_logs.scope_logs {
            row_count += scope_logs.log_records.len();
        }
    }

    assert_eq!(row_count, 0);
}

#[test]
fn test_count_log_records_empty_scope_logs() {
    let json_data = r#"{"resourceLogs":[{"resource":{"attributes":[]},"scopeLogs":[]}]}"#;
    let bytes = Bytes::from(json_data);

    let request = parse_otel_message(&bytes).unwrap();

    let mut row_count = 0;
    for resource_logs in &request.resource_logs {
        for scope_logs in &resource_logs.scope_logs {
            row_count += scope_logs.log_records.len();
        }
    }

    assert_eq!(row_count, 0);
}

#[test]
fn test_count_log_records_empty_log_records_array() {
    let json_data = r#"{"resourceLogs":[{"resource":{"attributes":[]},"scopeLogs":[{"scope":{"name":"test"},"logRecords":[]}]}]}"#;
    let bytes = Bytes::from(json_data);

    let request = parse_otel_message(&bytes).unwrap();

    let mut row_count = 0;
    for resource_logs in &request.resource_logs {
        for scope_logs in &resource_logs.scope_logs {
            row_count += scope_logs.log_records.len();
        }
    }

    assert_eq!(row_count, 0);
}

#[test]
fn test_count_log_records_multiple_empty_scopes() {
    // Multiple resources and scopes, all with empty log records
    let json_data = r#"{"resourceLogs":[{"resource":{"attributes":[]},"scopeLogs":[{"scope":{"name":"scope1"},"logRecords":[]},{"scope":{"name":"scope2"},"logRecords":[]}]},{"resource":{"attributes":[]},"scopeLogs":[{"scope":{"name":"scope3"},"logRecords":[]}]}]}"#;
    let bytes = Bytes::from(json_data);

    let request = parse_otel_message(&bytes).unwrap();

    assert_eq!(request.resource_logs.len(), 2);
    assert_eq!(request.resource_logs[0].scope_logs.len(), 2);
    assert_eq!(request.resource_logs[1].scope_logs.len(), 1);

    let mut row_count = 0;
    for resource_logs in &request.resource_logs {
        for scope_logs in &resource_logs.scope_logs {
            row_count += scope_logs.log_records.len();
        }
    }

    assert_eq!(row_count, 0);
}

#[test]
fn test_parse_empty_jsonl_otel_message() {
    // Empty lines only - should result in empty resource_logs
    let jsonl_data = "\n\n\n";
    let bytes = Bytes::from(jsonl_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    assert_eq!(request.resource_logs.len(), 0);
}

#[test]
fn test_parse_jsonl_with_empty_resource_logs() {
    // JSONL where each line has empty resourceLogs
    let jsonl_data = r#"{"resourceLogs":[]}
{"resourceLogs":[]}"#;
    let bytes = Bytes::from(jsonl_data);

    let result = parse_otel_message(&bytes);
    assert!(result.is_ok());

    let request = result.unwrap();
    // Both lines have empty resourceLogs, so merged result is also empty
    assert_eq!(request.resource_logs.len(), 0);
}
