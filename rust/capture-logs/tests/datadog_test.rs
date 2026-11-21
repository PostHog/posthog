use capture_logs::endpoints::datadog::*;
use serde_json::json;
use std::collections::HashMap;

#[test]
fn test_parse_datadog_tags() {
    let result = parse_datadog_tags(Some("env:prod,region:us,version:1.2.3"));
    assert_eq!(result.len(), 3);
    assert_eq!(result.get("env").unwrap(), "\"prod\"");
    assert_eq!(result.get("region").unwrap(), "\"us\"");
    assert_eq!(result.get("version").unwrap(), "\"1.2.3\"");
}

#[test]
fn test_normalize_datadog_severity() {
    assert_eq!(
        normalize_datadog_severity(Some("emergency")),
        ("fatal".to_string(), 21)
    );
    assert_eq!(
        normalize_datadog_severity(Some("CRITICAL")),
        ("fatal".to_string(), 21)
    );
    assert_eq!(
        normalize_datadog_severity(Some("error")),
        ("error".to_string(), 17)
    );
    assert_eq!(
        normalize_datadog_severity(Some("warn")),
        ("warn".to_string(), 13)
    );
    assert_eq!(
        normalize_datadog_severity(Some("info")),
        ("info".to_string(), 9)
    );
    assert_eq!(
        normalize_datadog_severity(Some("debug")),
        ("debug".to_string(), 5)
    );
    assert_eq!(
        normalize_datadog_severity(Some("trace")),
        ("trace".to_string(), 1)
    );
    assert_eq!(normalize_datadog_severity(None), ("info".to_string(), 9));
    assert_eq!(
        normalize_datadog_severity(Some("unknown")),
        ("info".to_string(), 9)
    );
}

#[test]
fn test_parse_datadog_tags_empty() {
    let result = parse_datadog_tags(None);
    assert!(result.is_empty());
}

#[test]
fn test_parse_datadog_tags_key_value() {
    let result = parse_datadog_tags(Some("env:prod,region:us-east-1"));
    assert_eq!(result.len(), 2);
    assert_eq!(result.get("env").unwrap(), "\"prod\"");
    assert_eq!(result.get("region").unwrap(), "\"us-east-1\"");
}

#[test]
fn test_parse_datadog_tags_boolean() {
    let result = parse_datadog_tags(Some("feature,enabled"));
    assert_eq!(result.len(), 2);
    assert_eq!(result.get("feature").unwrap(), "true");
    assert_eq!(result.get("enabled").unwrap(), "true");
}

#[test]
fn test_parse_datadog_tags_mixed() {
    let result = parse_datadog_tags(Some("env:prod,feature,version:1.0.0"));
    assert_eq!(result.len(), 3);
    assert_eq!(result.get("env").unwrap(), "\"prod\"");
    assert_eq!(result.get("feature").unwrap(), "true");
    assert_eq!(result.get("version").unwrap(), "\"1.0.0\"");
}

#[test]
fn test_parse_datadog_tags_with_spaces() {
    let result = parse_datadog_tags(Some("env:prod , region:us-east-1 "));
    assert_eq!(result.len(), 2);
    assert_eq!(result.get("env").unwrap(), "\"prod\"");
    assert_eq!(result.get("region").unwrap(), "\"us-east-1\"");
}

#[test]
fn test_extract_trace_span_ids_with_dd_prefix() {
    let mut extra = HashMap::new();
    // Hex: "abc123" -> Base64: "q8Ej"
    extra.insert("dd.trace_id".to_string(), json!("abc123"));
    // Hex: "def456" -> Base64: "3vRW"
    extra.insert("dd.span_id".to_string(), json!("def456"));

    let (trace_id, span_id) = extract_trace_span_ids(&extra);
    assert_eq!(trace_id, "q8Ej");
    assert_eq!(span_id, "3vRW");
}

#[test]
fn test_extract_trace_span_ids_without_prefix() {
    let mut extra = HashMap::new();
    // Hex: "123abc" -> Base64: "Ejq8"
    extra.insert("trace_id".to_string(), json!("123abc"));
    // Hex: "456def" -> Base64: "RW3v"
    extra.insert("span_id".to_string(), json!("456def"));

    let (trace_id, span_id) = extract_trace_span_ids(&extra);
    assert_eq!(trace_id, "Ejq8");
    assert_eq!(span_id, "RW3v");
}

#[test]
fn test_extract_trace_span_ids_dd_prefix_takes_precedence() {
    let mut extra = HashMap::new();
    extra.insert("dd.trace_id".to_string(), json!("aabbcc"));
    extra.insert("trace_id".to_string(), json!("112233"));
    extra.insert("dd.span_id".to_string(), json!("ddeeff"));
    extra.insert("span_id".to_string(), json!("445566"));

    let (trace_id, span_id) = extract_trace_span_ids(&extra);
    // "aabbcc" hex -> base64
    assert_eq!(trace_id, "qrvM");
    // "ddeeff" hex -> base64
    assert_eq!(span_id, "3e7/");
}

#[test]
fn test_extract_trace_span_ids_empty() {
    let extra = HashMap::new();
    let (trace_id, span_id) = extract_trace_span_ids(&extra);
    assert_eq!(trace_id, "");
    assert_eq!(span_id, "");
}

#[test]
fn test_extract_trace_span_ids_non_string_values() {
    let mut extra = HashMap::new();
    extra.insert("dd.trace_id".to_string(), json!(12345));
    extra.insert("dd.span_id".to_string(), json!(true));

    let (trace_id, span_id) = extract_trace_span_ids(&extra);
    assert_eq!(trace_id, "");
    assert_eq!(span_id, "");
}

#[test]
fn test_extract_trace_span_ids_with_0x_prefix() {
    let mut extra = HashMap::new();
    // 0x prefix should be stripped before decoding
    extra.insert("dd.trace_id".to_string(), json!("0xaabbcc"));
    extra.insert("dd.span_id".to_string(), json!("0xddeeff"));

    let (trace_id, span_id) = extract_trace_span_ids(&extra);
    // Same result as without prefix
    assert_eq!(trace_id, "qrvM");
    assert_eq!(span_id, "3e7/");
}

#[test]
fn test_extract_trace_span_ids_invalid_hex() {
    let mut extra = HashMap::new();
    // Invalid hex should return empty strings
    extra.insert("dd.trace_id".to_string(), json!("not-valid-hex"));
    extra.insert("dd.span_id".to_string(), json!("xyz123"));

    let (trace_id, span_id) = extract_trace_span_ids(&extra);
    assert_eq!(trace_id, "");
    assert_eq!(span_id, "");
}

#[test]
fn test_datadog_log_to_kafka_row_basic() {
    let log = DatadogLog {
        ddsource: Some("python".to_string()),
        ddtags: Some("env:prod".to_string()),
        hostname: Some("web-1".to_string()),
        message: Some("Test log message".to_string()),
        service: Some("my-service".to_string()),
        status: Some("info".to_string()),
        timestamp: Some(1234567890000),
        extra: HashMap::new(),
    };

    let query_params = DatadogQueryParams {
        token: Some("test-token".to_string()),
        ddtags: None,
        ddsource: None,
        service: None,
        hostname: None,
        message: None,
        status: None,
        extra: HashMap::new(),
    };

    let (row, _) = datadog_log_to_kafka_row(log, &DatadogRequestDefaults::from(&query_params));

    assert_eq!(row.body, "Test log message");
    assert_eq!(row.service_name, "my-service");
    assert_eq!(row.severity_text, "info");
    assert_eq!(row.severity_number, 9);
    assert!(row.resource_attributes.contains_key("service.name"));
    assert!(row.resource_attributes.contains_key("host.name"));
    assert!(row.resource_attributes.contains_key("ddsource"));
    assert!(row.resource_attributes.contains_key("env"));
}

#[test]
fn test_datadog_log_to_kafka_row_with_trace_ids() {
    let mut extra = HashMap::new();
    extra.insert("dd.trace_id".to_string(), json!("abcdefaa"));
    extra.insert("dd.span_id".to_string(), json!("abcdefba"));
    extra.insert("custom_field".to_string(), json!("custom_value"));

    let log = DatadogLog {
        ddsource: None,
        ddtags: None,
        hostname: None,
        message: Some("Test".to_string()),
        service: None,
        status: None,
        timestamp: None,
        extra,
    };

    let query_params = DatadogQueryParams {
        token: Some("test-token".to_string()),
        ddtags: None,
        ddsource: None,
        service: None,
        hostname: None,
        message: None,
        status: None,
        extra: HashMap::new(),
    };

    let (row, _) = datadog_log_to_kafka_row(log, &DatadogRequestDefaults::from(&query_params));

    assert_eq!(row.trace_id, "q83vqg==");
    assert_eq!(row.span_id, "q83vug==");
    assert!(row.attributes.contains_key("custom_field"));
}

#[test]
fn test_datadog_log_to_kafka_row_query_params_override() {
    let log = DatadogLog {
        ddsource: None,
        ddtags: None,
        hostname: None,
        message: None,
        service: None,
        status: None,
        timestamp: None,
        extra: HashMap::new(),
    };

    let mut extra_params = HashMap::new();
    extra_params.insert("custom".to_string(), "query_value".to_string());

    let query_params = DatadogQueryParams {
        token: Some("test-token".to_string()),
        ddtags: Some("env:dev".to_string()),
        ddsource: Some("query-source".to_string()),
        service: Some("query-service".to_string()),
        hostname: Some("query-host".to_string()),
        message: Some("Query message".to_string()),
        status: Some("warn".to_string()),
        extra: extra_params,
    };

    let (row, _) = datadog_log_to_kafka_row(log, &DatadogRequestDefaults::from(&query_params));

    assert_eq!(row.body, "Query message");
    assert_eq!(row.service_name, "query-service");
    assert_eq!(row.severity_text, "warn");
    assert!(row.attributes.contains_key("custom"));
    assert!(row.resource_attributes.contains_key("env"));
}

#[test]
fn test_datadog_log_to_kafka_row_body_takes_precedence() {
    let mut extra = HashMap::new();
    extra.insert("custom".to_string(), json!("body_value"));

    let log = DatadogLog {
        ddsource: Some("body-source".to_string()),
        ddtags: Some("env:prod".to_string()),
        hostname: Some("body-host".to_string()),
        message: Some("Body message".to_string()),
        service: Some("body-service".to_string()),
        status: Some("error".to_string()),
        timestamp: None,
        extra,
    };

    let mut extra_params = HashMap::new();
    extra_params.insert("custom".to_string(), "query_value".to_string());

    let query_params = DatadogQueryParams {
        token: Some("test-token".to_string()),
        ddtags: Some("env:dev".to_string()),
        ddsource: Some("query-source".to_string()),
        service: Some("query-service".to_string()),
        hostname: Some("query-host".to_string()),
        message: Some("Query message".to_string()),
        status: Some("warn".to_string()),
        extra: extra_params,
    };

    let (row, _) = datadog_log_to_kafka_row(log, &DatadogRequestDefaults::from(&query_params));

    assert_eq!(row.body, "Body message");
    assert_eq!(row.service_name, "body-service");
    assert_eq!(row.severity_text, "error");
    assert_eq!(row.severity_number, 17);
    // Body extra takes precedence over query extra
    assert_eq!(row.attributes.get("custom").unwrap(), "\"body_value\"");
    // Body ddtags take precedence over query ddtags
    assert_eq!(row.resource_attributes.get("env").unwrap(), "\"prod\"");
}

#[test]
fn test_datadog_log_to_kafka_row_timestamp_default() {
    let log = DatadogLog {
        ddsource: None,
        ddtags: None,
        hostname: None,
        message: None,
        service: None,
        status: None,
        timestamp: None,
        extra: HashMap::new(),
    };

    let query_params = DatadogQueryParams {
        token: Some("test-token".to_string()),
        ddtags: None,
        ddsource: None,
        service: None,
        hostname: None,
        message: None,
        status: None,
        extra: HashMap::new(),
    };

    let (row, _) = datadog_log_to_kafka_row(log, &DatadogRequestDefaults::from(&query_params));

    // Should have a timestamp (current time)
    assert!(row.timestamp.timestamp() > 0);
}

#[test]
fn test_datadog_log_to_kafka_row_all_attributes_merged() {
    let mut body_extra = HashMap::new();
    body_extra.insert("body_attr".to_string(), json!("body_val"));

    let log = DatadogLog {
        ddsource: None,
        ddtags: Some("body_tag:val1".to_string()),
        hostname: None,
        message: Some("Test".to_string()),
        service: None,
        status: None,
        timestamp: None,
        extra: body_extra,
    };

    let mut query_extra = HashMap::new();
    query_extra.insert("query_attr".to_string(), "query_val".to_string());

    let query_params = DatadogQueryParams {
        token: Some("test-token".to_string()),
        ddtags: Some("query_tag:val2".to_string()),
        ddsource: None,
        service: None,
        hostname: None,
        message: None,
        status: None,
        extra: query_extra,
    };

    let (row, _) = datadog_log_to_kafka_row(log, &DatadogRequestDefaults::from(&query_params));

    // Should have all attributes from both sources
    assert!(row.attributes.contains_key("query_attr"));
    assert!(row.attributes.contains_key("body_attr"));
    assert!(row.resource_attributes.contains_key("query_tag"));
    assert!(row.resource_attributes.contains_key("body_tag"));
    assert_eq!(row.attributes.len(), 2);
}

#[test]
fn test_datadog_log_to_kafka_row_event_name_extraction() {
    let mut extra = HashMap::new();
    extra.insert("event.name".to_string(), json!("user.signup"));
    extra.insert("other_field".to_string(), json!("value"));

    let log = DatadogLog {
        ddsource: None,
        ddtags: None,
        hostname: None,
        message: Some("Test".to_string()),
        service: None,
        status: None,
        timestamp: None,
        extra,
    };

    let query_params = DatadogQueryParams {
        token: Some("test-token".to_string()),
        ddtags: None,
        ddsource: None,
        service: None,
        hostname: None,
        message: None,
        status: None,
        extra: HashMap::new(),
    };

    let (row, _) = datadog_log_to_kafka_row(log, &DatadogRequestDefaults::from(&query_params));

    assert_eq!(row.event_name, "user.signup");
    assert!(row.attributes.contains_key("other_field"));
}

#[test]
fn test_datadog_log_to_kafka_row_instrumentation_scope_extraction() {
    let mut extra = HashMap::new();
    extra.insert("otel.scope.name".to_string(), json!("my.service.logger"));
    extra.insert("other_field".to_string(), json!("value"));

    let log = DatadogLog {
        ddsource: None,
        ddtags: None,
        hostname: None,
        message: Some("Test".to_string()),
        service: None,
        status: None,
        timestamp: None,
        extra,
    };

    let query_params = DatadogQueryParams {
        token: Some("test-token".to_string()),
        ddtags: None,
        ddsource: None,
        service: None,
        hostname: None,
        message: None,
        status: None,
        extra: HashMap::new(),
    };

    let (row, _) = datadog_log_to_kafka_row(log, &DatadogRequestDefaults::from(&query_params));

    assert_eq!(row.instrumentation_scope, "my.service.logger");
    assert!(row.attributes.contains_key("other_field"));
}

#[test]
fn test_datadog_log_to_kafka_row_event_name_and_scope_extraction() {
    let mut extra = HashMap::new();
    extra.insert("event.name".to_string(), json!("payment.processed"));
    extra.insert("otel.scope.name".to_string(), json!("payment.service"));
    extra.insert("custom_field".to_string(), json!("custom_value"));

    let log = DatadogLog {
        ddsource: None,
        ddtags: None,
        hostname: None,
        message: Some("Payment processed".to_string()),
        service: None,
        status: None,
        timestamp: None,
        extra,
    };

    let query_params = DatadogQueryParams {
        token: Some("test-token".to_string()),
        ddtags: None,
        ddsource: None,
        service: None,
        hostname: None,
        message: None,
        status: None,
        extra: HashMap::new(),
    };

    let (row, _) = datadog_log_to_kafka_row(log, &DatadogRequestDefaults::from(&query_params));

    assert_eq!(row.event_name, "payment.processed");
    assert_eq!(row.instrumentation_scope, "payment.service");
    assert!(row.attributes.contains_key("custom_field"));
}

#[test]
fn test_datadog_log_to_kafka_row_missing_event_name_and_scope() {
    let log = DatadogLog {
        ddsource: None,
        ddtags: None,
        hostname: None,
        message: Some("Test".to_string()),
        service: None,
        status: None,
        timestamp: None,
        extra: HashMap::new(),
    };

    let query_params = DatadogQueryParams {
        token: Some("test-token".to_string()),
        ddtags: None,
        ddsource: None,
        service: None,
        hostname: None,
        message: None,
        status: None,
        extra: HashMap::new(),
    };

    let (row, _) = datadog_log_to_kafka_row(log, &DatadogRequestDefaults::from(&query_params));

    assert_eq!(row.event_name, "");
    assert_eq!(row.instrumentation_scope, "");
}

#[test]
fn test_datadog_log_to_kafka_row_non_string_event_name_and_scope() {
    let mut extra = HashMap::new();
    extra.insert("event.name".to_string(), json!(12345));
    extra.insert("otel.scope.name".to_string(), json!(true));

    let log = DatadogLog {
        ddsource: None,
        ddtags: None,
        hostname: None,
        message: Some("Test".to_string()),
        service: None,
        status: None,
        timestamp: None,
        extra,
    };

    let query_params = DatadogQueryParams {
        token: Some("test-token".to_string()),
        ddtags: None,
        ddsource: None,
        service: None,
        hostname: None,
        message: None,
        status: None,
        extra: HashMap::new(),
    };

    let (row, _) = datadog_log_to_kafka_row(log, &DatadogRequestDefaults::from(&query_params));

    assert_eq!(row.event_name, "");
    assert_eq!(row.instrumentation_scope, "");
}

// Tests for empty request handling - verifying empty arrays produce no kafka rows

#[test]
fn test_parse_empty_datadog_logs_array() {
    // Empty array should parse successfully
    let json_data = r#"[]"#;
    let logs: Vec<DatadogLog> = serde_json::from_str(json_data).unwrap();

    assert_eq!(logs.len(), 0);
}

#[test]
fn test_empty_datadog_logs_produce_no_kafka_rows() {
    // Simulates the logic in export_datadog_logs_http
    let logs: Vec<DatadogLog> = vec![];

    let query_params = DatadogQueryParams {
        token: Some("test_token".to_string()),
        ddtags: None,
        ddsource: None,
        service: None,
        hostname: None,
        message: None,
        status: None,
        extra: HashMap::new(),
    };

    let rows: Vec<_> = logs
        .into_iter()
        .map(|log| datadog_log_to_kafka_row(log, &DatadogRequestDefaults::from(&query_params)))
        .collect();

    assert_eq!(rows.len(), 0);
}

#[test]
fn test_parse_datadog_logs_single_vs_array() {
    // Test that both single object and array formats work
    let single_log = r#"{"message":"test"}"#;
    let array_logs = r#"[{"message":"test"}]"#;
    let empty_array = r#"[]"#;

    // Single log parses as DatadogLog
    let single: DatadogLog = serde_json::from_str(single_log).unwrap();
    assert_eq!(single.message, Some("test".to_string()));

    // Array parses as Vec<DatadogLog>
    let array: Vec<DatadogLog> = serde_json::from_str(array_logs).unwrap();
    assert_eq!(array.len(), 1);
    assert_eq!(array[0].message, Some("test".to_string()));

    // Empty array parses as empty Vec
    let empty: Vec<DatadogLog> = serde_json::from_str(empty_array).unwrap();
    assert_eq!(empty.len(), 0);
}

#[test]
fn test_datadog_log_minimal_fields() {
    // Test that a log with all optional fields missing still parses
    let json_data = r#"{}"#;
    let log: DatadogLog = serde_json::from_str(json_data).unwrap();

    assert!(log.ddsource.is_none());
    assert!(log.ddtags.is_none());
    assert!(log.hostname.is_none());
    assert!(log.message.is_none());
    assert!(log.service.is_none());
    assert!(log.status.is_none());
    assert!(log.timestamp.is_none());
    assert!(log.extra.is_empty());
}

#[test]
fn test_empty_datadog_log_produces_valid_kafka_row() {
    // Even an empty log should produce a valid KafkaLogRow with defaults
    let log = DatadogLog {
        ddsource: None,
        ddtags: None,
        hostname: None,
        message: None,
        service: None,
        status: None,
        timestamp: None,
        extra: HashMap::new(),
    };

    let query_params = DatadogQueryParams {
        token: Some("test_token".to_string()),
        ddtags: None,
        ddsource: None,
        service: None,
        hostname: None,
        message: None,
        status: None,
        extra: HashMap::new(),
    };

    let (row, _) = datadog_log_to_kafka_row(log, &DatadogRequestDefaults::from(&query_params));

    // Should have default values
    assert_eq!(row.body, "");
    assert_eq!(row.service_name, "");
    assert_eq!(row.severity_text, "info");
    assert_eq!(row.severity_number, 9);
    assert!(!row.uuid.is_empty()); // UUID should be generated
}

#[test]
fn test_datadog_log_overridden_timestamp_tracking() {
    use chrono::Utc;

    // Test with a timestamp far in the past (should be overridden)
    let far_past = Utc::now().timestamp_millis() - (48 * 3600 * 1000); // 48 hours ago
    let log_overridden = DatadogLog {
        ddsource: None,
        ddtags: None,
        hostname: None,
        message: Some("Test".to_string()),
        service: None,
        status: None,
        timestamp: Some(far_past),
        extra: HashMap::new(),
    };

    let query_params = DatadogQueryParams {
        token: Some("test-token".to_string()),
        ddtags: None,
        ddsource: None,
        service: None,
        hostname: None,
        message: None,
        status: None,
        extra: HashMap::new(),
    };

    let (row_overridden, was_overridden) =
        datadog_log_to_kafka_row(log_overridden, &DatadogRequestDefaults::from(&query_params));
    assert!(was_overridden);
    assert!(row_overridden
        .attributes
        .contains_key("posthog.original_timestamp"));

    // Test with a recent timestamp (should not be overridden)
    let recent = Utc::now().timestamp_millis() - (3600 * 1000); // 1 hour ago
    let log_recent = DatadogLog {
        ddsource: None,
        ddtags: None,
        hostname: None,
        message: Some("Test".to_string()),
        service: None,
        status: None,
        timestamp: Some(recent),
        extra: HashMap::new(),
    };

    let (row_recent, was_not_overridden) =
        datadog_log_to_kafka_row(log_recent, &DatadogRequestDefaults::from(&query_params));
    assert!(!was_not_overridden);
    assert!(!row_recent
        .attributes
        .contains_key("posthog.original_timestamp"));

    // Test with user-provided originalTimestamp attribute (should not affect override detection)
    let mut extra = HashMap::new();
    extra.insert(
        "originalTimestamp".to_string(),
        json!("2020-01-01T00:00:00Z"),
    );
    let log_with_user_attr = DatadogLog {
        ddsource: None,
        ddtags: None,
        hostname: None,
        message: Some("Test".to_string()),
        service: None,
        status: None,
        timestamp: Some(recent),
        extra,
    };

    let (row_user_attr, was_not_overridden_2) = datadog_log_to_kafka_row(
        log_with_user_attr,
        &DatadogRequestDefaults::from(&query_params),
    );
    assert!(!was_not_overridden_2);
    // User's originalTimestamp should still be in attributes
    assert!(row_user_attr.attributes.contains_key("originalTimestamp"));
}

#[test]
fn test_datadog_log_timestamp_as_numeric_string() {
    let json_data = r#"{"timestamp": "1700000000000", "message": "hello"}"#;
    let log: DatadogLog = serde_json::from_str(json_data).unwrap();
    assert_eq!(log.timestamp, Some(1700000000000));
}

#[test]
fn test_datadog_log_timestamp_as_rfc3339_string() {
    let json_data = r#"{"timestamp": "2024-01-15T10:30:00Z", "message": "hello"}"#;
    let log: DatadogLog = serde_json::from_str(json_data).unwrap();
    // 2024-01-15T10:30:00Z in milliseconds
    assert_eq!(log.timestamp, Some(1705314600000));
}

fn query_params(
    ddtags: Option<&str>,
    service: Option<&str>,
    extra: &[(&str, &str)],
) -> DatadogQueryParams {
    DatadogQueryParams {
        token: Some("test-token".to_string()),
        ddtags: ddtags.map(str::to_string),
        ddsource: Some("query-source".to_string()),
        service: service.map(str::to_string),
        hostname: Some("query-host".to_string()),
        message: Some("query message".to_string()),
        status: Some("warn".to_string()),
        extra: extra
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect(),
    }
}

fn log_from_json(value: serde_json::Value) -> DatadogLog {
    serde_json::from_value(value).unwrap()
}

/// The attribute merge as it was when every row re-read the query parameters.
fn per_row_query_merge(
    log: &DatadogLog,
    query: &DatadogQueryParams,
) -> (HashMap<String, String>, HashMap<String, String>) {
    let mut resource_attributes = HashMap::new();
    if let Some(service) = log.service.as_ref().or(query.service.as_ref()) {
        resource_attributes.insert("service.name".to_string(), json!(service).to_string());
    }
    if let Some(hostname) = log.hostname.as_ref().or(query.hostname.as_ref()) {
        resource_attributes.insert("host.name".to_string(), json!(hostname).to_string());
    }
    if let Some(ddsource) = log.ddsource.as_ref().or(query.ddsource.as_ref()) {
        resource_attributes.insert("ddsource".to_string(), json!(ddsource).to_string());
    }
    resource_attributes.extend(parse_datadog_tags(query.ddtags.as_deref()));
    resource_attributes.extend(parse_datadog_tags(log.ddtags.as_deref()));

    let mut attributes = HashMap::new();
    for (key, value) in &query.extra {
        attributes.insert(key.clone(), json!(value).to_string());
    }
    for (key, value) in &log.extra {
        attributes.insert(key.clone(), value.to_string());
    }
    (resource_attributes, attributes)
}

#[rstest::rstest]
#[case::empty_log_no_query(json!({}), query_params(None, None, &[]))]
#[case::empty_log_full_query(
    json!({}),
    query_params(Some("env:prod,flag, region:us"), Some("svc"), &[("team", "core"), ("quote", "a\"b")])
)]
#[case::body_overrides_query(
    json!({"service": "body-svc", "hostname": "body-host", "ddsource": "body-src", "ddtags": "env:staging,service.name:tagged", "team": "body-team", "message": "hi", "status": "error"}),
    query_params(Some("env:prod,host.name:from-tag"), Some("svc"), &[("team", "core"), ("other", "x")])
)]
#[case::query_tag_overrides_resource_field(
    json!({"message": "hi"}),
    query_params(Some("service.name:from-tag,ddsource:tag-src"), Some("svc"), &[])
)]
#[case::body_extra_non_string_values(
    json!({"count": 3, "nested": {"a": [1, 2]}, "flag": true}),
    query_params(None, None, &[("count", "7")])
)]
fn shared_query_defaults_match_per_row_parsing(
    #[case] log_json: serde_json::Value,
    #[case] query: DatadogQueryParams,
) {
    let expected = per_row_query_merge(&log_from_json(log_json.clone()), &query);
    let defaults = DatadogRequestDefaults::from(&query);

    let (row, _) = datadog_log_to_kafka_row(log_from_json(log_json.clone()), &defaults);
    let (second_row, _) = datadog_log_to_kafka_row(log_from_json(log_json), &defaults);

    assert_eq!(
        (row.resource_attributes.clone(), row.attributes.clone()),
        expected
    );
    assert_eq!(
        (second_row.resource_attributes, second_row.attributes),
        expected
    );
    assert_eq!(row.service_name, second_row.service_name);
    assert_eq!(row.body, second_row.body);
    assert_eq!(row.severity_text, second_row.severity_text);
}

#[test]
fn query_fallbacks_fill_fields_missing_from_the_body() {
    let defaults = DatadogRequestDefaults::from(&query_params(None, Some("svc"), &[]));

    let (row, _) = datadog_log_to_kafka_row(log_from_json(json!({})), &defaults);

    assert_eq!(row.service_name, "svc");
    assert_eq!(row.body, "query message");
    assert_eq!(row.severity_text, "warn");
}
