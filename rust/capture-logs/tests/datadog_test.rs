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

    let row = datadog_log_to_kafka_row(log, &query_params);

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

    let row = datadog_log_to_kafka_row(log, &query_params);

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

    let row = datadog_log_to_kafka_row(log, &query_params);

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

    let row = datadog_log_to_kafka_row(log, &query_params);

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

    let row = datadog_log_to_kafka_row(log, &query_params);

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

    let row = datadog_log_to_kafka_row(log, &query_params);

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

    let row = datadog_log_to_kafka_row(log, &query_params);

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

    let row = datadog_log_to_kafka_row(log, &query_params);

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

    let row = datadog_log_to_kafka_row(log, &query_params);

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

    let row = datadog_log_to_kafka_row(log, &query_params);

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

    let row = datadog_log_to_kafka_row(log, &query_params);

    assert_eq!(row.event_name, "");
    assert_eq!(row.instrumentation_scope, "");
}
