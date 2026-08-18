use axum::http::HeaderMap;
use bytes::{Buf, Bytes};
use opentelemetry_proto::tonic::collector::logs::v1::ExportLogsServiceRequest;
use opentelemetry_proto::tonic::collector::trace::v1::ExportTraceServiceRequest;
use prost::Message;
use serde::de::{DeserializeSeed, MapAccess, SeqAccess, Visitor};
use serde::Deserializer;
use serde_json::Value;

use crate::api::CaptureError;
use crate::payload::decompression::decompress_gzip_to_bytes;

/// Patch OTEL JSON AnyValue objects for proper deserialization into protobuf-derived Rust types.
///
/// Handles two cases:
/// 1. Empty `{}` objects under `"value"` keys become `null` (opentelemetry-rust#1253).
/// 2. Null-valued scalar fields (e.g. `{"doubleValue": null}`) are removed. In protobuf-JSON
///    encoding a missing key is equivalent to an unset scalar, but serde rejects null for
///    non-optional f64/i64/bool/String fields.
fn patch_otel_json(v: &mut Value) {
    match v {
        Value::Object(map) => {
            if let Some(inner) = map.get_mut("value") {
                if let Some(obj) = inner.as_object_mut() {
                    for field in &[
                        "doubleValue",
                        "intValue",
                        "stringValue",
                        "boolValue",
                        "bytesValue",
                    ] {
                        if matches!(obj.get(*field), Some(Value::Null)) {
                            obj.remove(*field);
                        }
                    }
                    if obj.is_empty() {
                        *inner = Value::Null;
                    }
                }
            }
            for (_, val) in map.iter_mut() {
                patch_otel_json(val);
            }
        }
        Value::Array(arr) => {
            for val in arr.iter_mut() {
                patch_otel_json(val);
            }
        }
        _ => {}
    }
}

pub fn parse_request(
    body: &Bytes,
    headers: &HeaderMap,
    body_limit: usize,
) -> Result<ExportTraceServiceRequest, CaptureError> {
    let content_encoding = headers
        .get("content-encoding")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    let body = if content_encoding.eq_ignore_ascii_case("gzip") {
        Bytes::from(decompress_gzip_to_bytes(body, body_limit)?)
    } else if !content_encoding.is_empty() {
        return Err(CaptureError::RequestDecodingError(format!(
            "Unsupported content-encoding: {content_encoding}"
        )));
    } else {
        body.clone()
    };

    let content_type = headers
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    let is_protobuf = content_type.starts_with("application/x-protobuf");
    let is_json = content_type.starts_with("application/json");

    if is_protobuf {
        ExportTraceServiceRequest::decode(&body[..])
            .map_err(|e| CaptureError::RequestParsingError(format!("Invalid protobuf: {e}")))
    } else if is_json {
        let mut json_value: Value = serde_json::from_slice(&body)
            .map_err(|e| CaptureError::RequestParsingError(format!("Invalid JSON: {e}")))?;

        patch_otel_json(&mut json_value);

        serde_json::from_value(json_value).map_err(|e| {
            CaptureError::RequestParsingError(format!("Invalid OTLP trace format: {e}"))
        })
    } else {
        Err(CaptureError::RequestDecodingError(
            "Content-Type must be application/x-protobuf or application/json".to_string(),
        ))
    }
}

pub fn parse_logs_request(
    body: &Bytes,
    headers: &HeaderMap,
    body_limit: usize,
    record_limit: usize,
) -> Result<ExportLogsServiceRequest, CaptureError> {
    let content_encoding = headers
        .get("content-encoding")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    let body = if content_encoding.eq_ignore_ascii_case("gzip") {
        Bytes::from(decompress_gzip_to_bytes(body, body_limit)?)
    } else if !content_encoding.is_empty() {
        return Err(CaptureError::RequestDecodingError(format!(
            "Unsupported content-encoding: {content_encoding}"
        )));
    } else {
        body.clone()
    };

    let content_type = headers
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    if content_type.starts_with("application/x-protobuf") {
        ensure_protobuf_log_record_limit(&body, record_limit)?;
        ExportLogsServiceRequest::decode(&body[..])
            .map_err(|e| CaptureError::RequestParsingError(format!("Invalid protobuf: {e}")))
    } else if content_type.starts_with("application/json") {
        ensure_json_log_record_limit(&body, record_limit)?;
        let mut json_value: Value = serde_json::from_slice(&body)
            .map_err(|e| CaptureError::RequestParsingError(format!("Invalid JSON: {e}")))?;

        patch_otel_json(&mut json_value);

        serde_json::from_value(json_value).map_err(|e| {
            CaptureError::RequestParsingError(format!("Invalid OTLP logs format: {e}"))
        })
    } else {
        Err(CaptureError::RequestDecodingError(
            "Content-Type must be application/x-protobuf or application/json".to_string(),
        ))
    }
}

fn ensure_protobuf_log_record_limit(
    mut request: &[u8],
    node_limit: usize,
) -> Result<(), CaptureError> {
    let mut node_count = 0;
    while request.has_remaining() {
        let (tag, wire_type) =
            prost::encoding::decode_key(&mut request).map_err(invalid_logs_protobuf)?;
        if tag == 1 && wire_type == prost::encoding::WireType::LengthDelimited {
            increment_log_node_count(&mut node_count, node_limit)?;
            let mut resource_logs = take_message(&mut request).map_err(invalid_logs_protobuf)?;
            count_resource_log_records(&mut resource_logs, &mut node_count, node_limit)?;
        } else {
            prost::encoding::skip_field(
                wire_type,
                tag,
                &mut request,
                prost::encoding::DecodeContext::default(),
            )
            .map_err(invalid_logs_protobuf)?;
        }
    }
    Ok(())
}

fn count_resource_log_records(
    resource_logs: &mut &[u8],
    node_count: &mut usize,
    node_limit: usize,
) -> Result<(), CaptureError> {
    while resource_logs.has_remaining() {
        let (tag, wire_type) =
            prost::encoding::decode_key(resource_logs).map_err(invalid_logs_protobuf)?;
        match (tag, wire_type) {
            (1, prost::encoding::WireType::LengthDelimited) => {
                increment_log_node_count(node_count, node_limit)?;
                let mut resource = take_message(resource_logs).map_err(invalid_logs_protobuf)?;
                count_resource_nodes(&mut resource, node_count, node_limit)?;
            }
            (2, prost::encoding::WireType::LengthDelimited) => {
                increment_log_node_count(node_count, node_limit)?;
                let mut scope_logs = take_message(resource_logs).map_err(invalid_logs_protobuf)?;
                count_scope_log_records(&mut scope_logs, node_count, node_limit)?;
            }
            _ => skip_protobuf_field(wire_type, tag, resource_logs)?,
        }
    }
    Ok(())
}

fn count_scope_log_records(
    scope_logs: &mut &[u8],
    node_count: &mut usize,
    node_limit: usize,
) -> Result<(), CaptureError> {
    while scope_logs.has_remaining() {
        let (tag, wire_type) =
            prost::encoding::decode_key(scope_logs).map_err(invalid_logs_protobuf)?;
        match (tag, wire_type) {
            (1, prost::encoding::WireType::LengthDelimited) => {
                increment_log_node_count(node_count, node_limit)?;
                let mut scope = take_message(scope_logs).map_err(invalid_logs_protobuf)?;
                count_instrumentation_scope_nodes(&mut scope, node_count, node_limit)?;
            }
            (2, prost::encoding::WireType::LengthDelimited) => {
                increment_log_node_count(node_count, node_limit)?;
                let mut record = take_message(scope_logs).map_err(invalid_logs_protobuf)?;
                count_log_record_nodes(&mut record, node_count, node_limit)?;
            }
            _ => skip_protobuf_field(wire_type, tag, scope_logs)?,
        }
    }
    Ok(())
}

fn count_resource_nodes(
    resource: &mut &[u8],
    node_count: &mut usize,
    node_limit: usize,
) -> Result<(), CaptureError> {
    count_repeated_key_values(resource, 1, node_count, node_limit)
}

fn count_instrumentation_scope_nodes(
    scope: &mut &[u8],
    node_count: &mut usize,
    node_limit: usize,
) -> Result<(), CaptureError> {
    count_repeated_key_values(scope, 3, node_count, node_limit)
}

fn count_log_record_nodes(
    record: &mut &[u8],
    node_count: &mut usize,
    node_limit: usize,
) -> Result<(), CaptureError> {
    while record.has_remaining() {
        let (tag, wire_type) =
            prost::encoding::decode_key(record).map_err(invalid_logs_protobuf)?;
        match (tag, wire_type) {
            (5, prost::encoding::WireType::LengthDelimited) => {
                increment_log_node_count(node_count, node_limit)?;
                let mut body = take_message(record).map_err(invalid_logs_protobuf)?;
                count_any_value_nodes(&mut body, node_count, node_limit)?;
            }
            (6, prost::encoding::WireType::LengthDelimited) => {
                count_key_value_field(record, node_count, node_limit)?;
            }
            _ => skip_protobuf_field(wire_type, tag, record)?,
        }
    }
    Ok(())
}

fn count_repeated_key_values(
    message: &mut &[u8],
    attribute_tag: u32,
    node_count: &mut usize,
    node_limit: usize,
) -> Result<(), CaptureError> {
    while message.has_remaining() {
        let (tag, wire_type) =
            prost::encoding::decode_key(message).map_err(invalid_logs_protobuf)?;
        if tag == attribute_tag && wire_type == prost::encoding::WireType::LengthDelimited {
            count_key_value_field(message, node_count, node_limit)?;
        } else {
            skip_protobuf_field(wire_type, tag, message)?;
        }
    }
    Ok(())
}

fn count_key_value_field(
    message: &mut &[u8],
    node_count: &mut usize,
    node_limit: usize,
) -> Result<(), CaptureError> {
    increment_log_node_count(node_count, node_limit)?;
    let mut key_value = take_message(message).map_err(invalid_logs_protobuf)?;
    while key_value.has_remaining() {
        let (tag, wire_type) =
            prost::encoding::decode_key(&mut key_value).map_err(invalid_logs_protobuf)?;
        if tag == 2 && wire_type == prost::encoding::WireType::LengthDelimited {
            let mut value = take_message(&mut key_value).map_err(invalid_logs_protobuf)?;
            count_any_value_nodes(&mut value, node_count, node_limit)?;
        } else {
            skip_protobuf_field(wire_type, tag, &mut key_value)?;
        }
    }
    Ok(())
}

fn count_any_value_nodes(
    value: &mut &[u8],
    node_count: &mut usize,
    node_limit: usize,
) -> Result<(), CaptureError> {
    while value.has_remaining() {
        let (tag, wire_type) = prost::encoding::decode_key(value).map_err(invalid_logs_protobuf)?;
        match (tag, wire_type) {
            (5, prost::encoding::WireType::LengthDelimited) => {
                let mut array = take_message(value).map_err(invalid_logs_protobuf)?;
                count_repeated_any_values(&mut array, node_count, node_limit)?;
            }
            (6, prost::encoding::WireType::LengthDelimited) => {
                let mut list = take_message(value).map_err(invalid_logs_protobuf)?;
                count_repeated_key_values(&mut list, 1, node_count, node_limit)?;
            }
            _ => skip_protobuf_field(wire_type, tag, value)?,
        }
    }
    Ok(())
}

fn count_repeated_any_values(
    array: &mut &[u8],
    node_count: &mut usize,
    node_limit: usize,
) -> Result<(), CaptureError> {
    while array.has_remaining() {
        let (tag, wire_type) = prost::encoding::decode_key(array).map_err(invalid_logs_protobuf)?;
        if tag == 1 && wire_type == prost::encoding::WireType::LengthDelimited {
            increment_log_node_count(node_count, node_limit)?;
            let mut value = take_message(array).map_err(invalid_logs_protobuf)?;
            count_any_value_nodes(&mut value, node_count, node_limit)?;
        } else {
            skip_protobuf_field(wire_type, tag, array)?;
        }
    }
    Ok(())
}

fn skip_protobuf_field(
    wire_type: prost::encoding::WireType,
    tag: u32,
    message: &mut &[u8],
) -> Result<(), CaptureError> {
    prost::encoding::skip_field(
        wire_type,
        tag,
        message,
        prost::encoding::DecodeContext::default(),
    )
    .map_err(invalid_logs_protobuf)
}

fn take_message<'a>(buf: &mut &'a [u8]) -> Result<&'a [u8], prost::DecodeError> {
    let len = prost::encoding::decode_varint(buf)? as usize;
    if len > buf.len() {
        return Err(prost::DecodeError::new("buffer underflow"));
    }
    let (message, rest) = buf.split_at(len);
    *buf = rest;
    Ok(message)
}

fn invalid_logs_protobuf(error: prost::DecodeError) -> CaptureError {
    CaptureError::RequestParsingError(format!("Invalid protobuf: {error}"))
}

fn ensure_json_log_record_limit(body: &[u8], node_limit: usize) -> Result<(), CaptureError> {
    let mut node_count = 0;
    let mut deserializer = serde_json::Deserializer::from_slice(body);
    JsonBudgetSeed {
        node_count: &mut node_count,
        node_limit,
    }
    .deserialize(&mut deserializer)
    .map_err(|error| CaptureError::RequestParsingError(format!("Invalid JSON: {error}")))?;
    deserializer
        .end()
        .map_err(|error| CaptureError::RequestParsingError(format!("Invalid JSON: {error}")))
}

fn increment_log_node_count(node_count: &mut usize, node_limit: usize) -> Result<(), CaptureError> {
    *node_count += 1;
    if *node_count > node_limit {
        return Err(CaptureError::RequestParsingError(format!(
            "Too many OTLP log nodes: {} exceeds limit of {node_limit}",
            *node_count
        )));
    }
    Ok(())
}

struct JsonBudgetSeed<'a> {
    node_count: &'a mut usize,
    node_limit: usize,
}

impl<'de> DeserializeSeed<'de> for JsonBudgetSeed<'_> {
    type Value = ();

    fn deserialize<D>(self, deserializer: D) -> Result<(), D::Error>
    where
        D: Deserializer<'de>,
    {
        deserializer.deserialize_any(JsonBudgetVisitor {
            node_count: self.node_count,
            node_limit: self.node_limit,
        })
    }
}

struct JsonBudgetVisitor<'a> {
    node_count: &'a mut usize,
    node_limit: usize,
}

impl<'de> Visitor<'de> for JsonBudgetVisitor<'_> {
    type Value = ();

    fn expecting(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
        formatter.write_str("valid JSON")
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<(), A::Error>
    where
        A: SeqAccess<'de>,
    {
        while let Some(()) = sequence.next_element_seed(JsonBudgetSeed {
            node_count: self.node_count,
            node_limit: self.node_limit,
        })? {
            increment_log_node_count(self.node_count, self.node_limit)
                .map_err(serde::de::Error::custom)?;
        }
        Ok(())
    }

    fn visit_map<A>(self, mut map: A) -> Result<(), A::Error>
    where
        A: MapAccess<'de>,
    {
        while map.next_key::<String>()?.is_some() {
            increment_log_node_count(self.node_count, self.node_limit)
                .map_err(serde::de::Error::custom)?;
            map.next_value_seed(JsonBudgetSeed {
                node_count: self.node_count,
                node_limit: self.node_limit,
            })?;
        }
        Ok(())
    }

    fn visit_bool<E>(self, _value: bool) -> Result<(), E> {
        Ok(())
    }

    fn visit_i64<E>(self, _value: i64) -> Result<(), E> {
        Ok(())
    }

    fn visit_u64<E>(self, _value: u64) -> Result<(), E> {
        Ok(())
    }

    fn visit_f64<E>(self, _value: f64) -> Result<(), E> {
        Ok(())
    }

    fn visit_str<E>(self, _value: &str) -> Result<(), E> {
        Ok(())
    }

    fn visit_string<E>(self, _value: String) -> Result<(), E> {
        Ok(())
    }

    fn visit_none<E>(self) -> Result<(), E> {
        Ok(())
    }

    fn visit_unit<E>(self) -> Result<(), E> {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderMap;
    use flate2::write::GzEncoder;
    use flate2::Compression;
    use opentelemetry_proto::tonic::common::v1::{
        any_value, AnyValue, ArrayValue, KeyValue, KeyValueList,
    };
    use opentelemetry_proto::tonic::logs::v1::{ResourceLogs, ScopeLogs};
    use opentelemetry_proto::tonic::resource::v1::Resource;
    use opentelemetry_proto::tonic::trace::v1::{ResourceSpans, ScopeSpans, Span};
    use std::io::Write;

    fn make_protobuf_request() -> ExportTraceServiceRequest {
        ExportTraceServiceRequest {
            resource_spans: vec![ResourceSpans {
                resource: None,
                scope_spans: vec![ScopeSpans {
                    scope: None,
                    spans: vec![Span {
                        trace_id: vec![1; 16],
                        span_id: vec![2; 8],
                        ..Default::default()
                    }],
                    schema_url: String::new(),
                }],
                schema_url: String::new(),
            }],
        }
    }

    #[test]
    fn test_parse_logs_json() {
        let body = Bytes::from(
            serde_json::to_vec(&serde_json::json!({
                "resourceLogs": [{
                    "scopeLogs": [{
                        "logRecords": [{
                            "timeUnixNano": "1704067200000000000",
                            "traceId": "01010101010101010101010101010101",
                            "spanId": "0202020202020202",
                            "eventName": "gen_ai.evaluation.result",
                            "attributes": [{
                                "key": "gen_ai.evaluation.name",
                                "value": {"stringValue": "correctness"}
                            }]
                        }]
                    }]
                }]
            }))
            .unwrap(),
        );
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());

        let request = parse_logs_request(&body, &headers, 1024, 1000).unwrap();

        let record = &request.resource_logs[0].scope_logs[0].log_records[0];
        assert_eq!(record.event_name, "gen_ai.evaluation.result");
        assert_eq!(record.trace_id, vec![1; 16]);
        assert_eq!(record.span_id, vec![2; 8]);
    }

    #[test]
    fn test_parse_logs_json_rejects_too_many_raw_records() {
        let body = Bytes::from(
            serde_json::to_vec(&serde_json::json!({
                "resourceLogs": [{
                    "scopeLogs": [{
                        "logRecords": vec![serde_json::json!({}); 1001]
                    }]
                }]
            }))
            .unwrap(),
        );
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());

        let error = parse_logs_request(&body, &headers, 1024 * 1024, 1000).unwrap_err();

        assert!(error.to_string().contains("Too many OTLP log nodes"));
    }

    #[test]
    fn test_parse_logs_json_rejects_too_many_empty_resource_containers() {
        let body = Bytes::from(
            serde_json::to_vec(&serde_json::json!({
                "resourceLogs": vec![serde_json::json!({}); 1001]
            }))
            .unwrap(),
        );
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());

        let error = parse_logs_request(&body, &headers, 1024 * 1024, 1000).unwrap_err();

        assert!(error.to_string().contains("Too many OTLP log nodes"));
    }

    #[test]
    fn test_parse_logs_json_rejects_too_many_resource_attributes() {
        let body = Bytes::from(
            serde_json::to_vec(&serde_json::json!({
                "resourceLogs": [{
                    "resource": {"attributes": vec![serde_json::json!({}); 1001]}
                }]
            }))
            .unwrap(),
        );
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());

        let error = parse_logs_request(&body, &headers, 1024 * 1024, 1000).unwrap_err();

        assert!(error.to_string().contains("Too many OTLP log nodes"));
    }

    #[test]
    fn test_parse_logs_json_rejects_too_many_flat_object_entries() {
        let object = (0..1001)
            .map(|index| (format!("key-{index}"), serde_json::Value::Null))
            .collect::<serde_json::Map<_, _>>();
        let body = Bytes::from(serde_json::to_vec(&object).unwrap());
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());

        let error = parse_logs_request(&body, &headers, 1024 * 1024, 1000).unwrap_err();

        assert!(error.to_string().contains("Too many OTLP log nodes"));
    }

    #[test]
    fn test_parse_logs_protobuf_rejects_truncated_message() {
        let body = Bytes::from_static(&[0x0a, 0x05, 0x01]);
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/x-protobuf".parse().unwrap());

        let error = parse_logs_request(&body, &headers, 1024, 1000).unwrap_err();

        assert!(error.to_string().contains("buffer underflow"));
    }

    #[test]
    fn test_parse_logs_json_rejects_too_many_nested_any_values() {
        let body = Bytes::from(
            serde_json::to_vec(&serde_json::json!({
                "resourceLogs": [{
                    "resource": {"attributes": [{
                        "key": "nested",
                        "value": {"arrayValue": {"values": vec![serde_json::json!({}); 1001]}}
                    }]}
                }]
            }))
            .unwrap(),
        );
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());

        let error = parse_logs_request(&body, &headers, 1024 * 1024, 1000).unwrap_err();

        assert!(error.to_string().contains("Too many OTLP log nodes"));
    }

    #[test]
    fn test_parse_logs_json_rejects_too_many_nested_key_values() {
        let body = Bytes::from(
            serde_json::to_vec(&serde_json::json!({
                "resourceLogs": [{
                    "resource": {"attributes": [{
                        "key": "nested",
                        "value": {"kvlistValue": {"values": vec![serde_json::json!({}); 1001]}}
                    }]}
                }]
            }))
            .unwrap(),
        );
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());

        let error = parse_logs_request(&body, &headers, 1024 * 1024, 1000).unwrap_err();

        assert!(error.to_string().contains("Too many OTLP log nodes"));
    }

    #[test]
    fn test_parse_logs_json_rejects_too_many_empty_scope_containers() {
        let body = Bytes::from(
            serde_json::to_vec(&serde_json::json!({
                "resourceLogs": [{
                    "scopeLogs": vec![serde_json::json!({}); 1000]
                }]
            }))
            .unwrap(),
        );
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());

        let error = parse_logs_request(&body, &headers, 1024 * 1024, 1000).unwrap_err();

        assert!(error.to_string().contains("Too many OTLP log nodes"));
    }

    #[test]
    fn test_parse_logs_protobuf_rejects_too_many_empty_resource_containers() {
        let request = ExportLogsServiceRequest {
            resource_logs: vec![Default::default(); 1001],
        };
        let body = Bytes::from(request.encode_to_vec());
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/x-protobuf".parse().unwrap());

        let error = parse_logs_request(&body, &headers, 1024 * 1024, 1000).unwrap_err();

        assert!(error.to_string().contains("Too many OTLP log nodes"));
    }

    #[test]
    fn test_parse_logs_protobuf_rejects_too_many_empty_scope_containers() {
        let request = ExportLogsServiceRequest {
            resource_logs: vec![opentelemetry_proto::tonic::logs::v1::ResourceLogs {
                scope_logs: vec![Default::default(); 1000],
                ..Default::default()
            }],
        };
        let body = Bytes::from(request.encode_to_vec());
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/x-protobuf".parse().unwrap());

        let error = parse_logs_request(&body, &headers, 1024 * 1024, 1000).unwrap_err();

        assert!(error.to_string().contains("Too many OTLP log nodes"));
    }

    #[test]
    fn test_parse_logs_protobuf_rejects_too_many_resource_attributes() {
        let request = ExportLogsServiceRequest {
            resource_logs: vec![ResourceLogs {
                resource: Some(Resource {
                    attributes: vec![KeyValue::default(); 1001],
                    ..Default::default()
                }),
                ..Default::default()
            }],
        };
        let body = Bytes::from(request.encode_to_vec());
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/x-protobuf".parse().unwrap());

        let error = parse_logs_request(&body, &headers, 1024 * 1024, 1000).unwrap_err();

        assert!(error.to_string().contains("Too many OTLP log nodes"));
    }

    #[test]
    fn test_parse_logs_protobuf_rejects_too_many_record_attributes() {
        let request = ExportLogsServiceRequest {
            resource_logs: vec![ResourceLogs {
                scope_logs: vec![ScopeLogs {
                    log_records: vec![opentelemetry_proto::tonic::logs::v1::LogRecord {
                        attributes: vec![KeyValue::default(); 1001],
                        ..Default::default()
                    }],
                    ..Default::default()
                }],
                ..Default::default()
            }],
        };
        let body = Bytes::from(request.encode_to_vec());
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/x-protobuf".parse().unwrap());

        let error = parse_logs_request(&body, &headers, 1024 * 1024, 1000).unwrap_err();

        assert!(error.to_string().contains("Too many OTLP log nodes"));
    }

    #[test]
    fn test_parse_logs_protobuf_rejects_too_many_nested_any_values() {
        let request = ExportLogsServiceRequest {
            resource_logs: vec![ResourceLogs {
                resource: Some(Resource {
                    attributes: vec![KeyValue {
                        key: "nested".to_string(),
                        value: Some(AnyValue {
                            value: Some(any_value::Value::ArrayValue(ArrayValue {
                                values: vec![AnyValue::default(); 1001],
                            })),
                        }),
                    }],
                    ..Default::default()
                }),
                scope_logs: vec![ScopeLogs::default()],
                ..Default::default()
            }],
        };
        let body = Bytes::from(request.encode_to_vec());
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/x-protobuf".parse().unwrap());

        let error = parse_logs_request(&body, &headers, 1024 * 1024, 1000).unwrap_err();

        assert!(error.to_string().contains("Too many OTLP log nodes"));
    }

    #[test]
    fn test_parse_logs_protobuf_rejects_too_many_nested_key_values() {
        let request = ExportLogsServiceRequest {
            resource_logs: vec![ResourceLogs {
                resource: Some(Resource {
                    attributes: vec![KeyValue {
                        key: "nested".to_string(),
                        value: Some(AnyValue {
                            value: Some(any_value::Value::KvlistValue(KeyValueList {
                                values: vec![KeyValue::default(); 1001],
                            })),
                        }),
                    }],
                    ..Default::default()
                }),
                scope_logs: vec![ScopeLogs::default()],
                ..Default::default()
            }],
        };
        let body = Bytes::from(request.encode_to_vec());
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/x-protobuf".parse().unwrap());

        let error = parse_logs_request(&body, &headers, 1024 * 1024, 1000).unwrap_err();

        assert!(error.to_string().contains("Too many OTLP log nodes"));
    }

    #[test]
    fn test_parse_protobuf() {
        let request = make_protobuf_request();
        let body = Bytes::from(request.encode_to_vec());
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/x-protobuf".parse().unwrap());

        let parsed = parse_request(&body, &headers, 4 * 1024 * 1024).unwrap();
        assert_eq!(parsed.resource_spans.len(), 1);
        assert_eq!(
            parsed.resource_spans[0].scope_spans[0].spans[0].trace_id,
            vec![1; 16]
        );
    }

    #[test]
    fn test_parse_json() {
        let json = r#"{"resourceSpans":[{"scopeSpans":[{"spans":[{"traceId":"","spanId":""}]}]}]}"#;
        let body = Bytes::from(json);
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());

        let parsed = parse_request(&body, &headers, 4 * 1024 * 1024).unwrap();
        assert_eq!(parsed.resource_spans.len(), 1);
    }

    #[test]
    fn test_parse_gzip_protobuf() {
        let request = make_protobuf_request();
        let encoded = request.encode_to_vec();

        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(&encoded).unwrap();
        let compressed = encoder.finish().unwrap();

        let body = Bytes::from(compressed);
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/x-protobuf".parse().unwrap());
        headers.insert("content-encoding", "gzip".parse().unwrap());

        let parsed = parse_request(&body, &headers, 4 * 1024 * 1024).unwrap();
        assert_eq!(parsed.resource_spans.len(), 1);
    }

    #[test]
    fn test_parse_malformed_protobuf() {
        let body = Bytes::from(vec![0xFF, 0xFF, 0xFF]);
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/x-protobuf".parse().unwrap());

        assert!(parse_request(&body, &headers, 4 * 1024 * 1024).is_err());
    }

    #[test]
    fn test_parse_malformed_json() {
        let body = Bytes::from("not json");
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());

        assert!(parse_request(&body, &headers, 4 * 1024 * 1024).is_err());
    }

    #[test]
    fn test_parse_unsupported_content_type() {
        let body = Bytes::from("data");
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "text/plain".parse().unwrap());

        assert!(parse_request(&body, &headers, 4 * 1024 * 1024).is_err());
    }

    #[test]
    fn test_unsupported_content_encoding() {
        let body = Bytes::from("data");
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/x-protobuf".parse().unwrap());
        headers.insert("content-encoding", "deflate".parse().unwrap());

        assert!(parse_request(&body, &headers, 4 * 1024 * 1024).is_err());
    }

    #[test]
    fn test_patch_otel_json_empty_value() {
        let mut v = serde_json::json!({"value": {}});
        patch_otel_json(&mut v);
        assert_eq!(v["value"], Value::Null);
    }

    #[test]
    fn test_patch_otel_json_nested() {
        let mut v = serde_json::json!({
            "attributes": [
                {"key": "test", "value": {}},
                {"key": "other", "value": {"stringValue": "hello"}}
            ]
        });
        patch_otel_json(&mut v);
        assert_eq!(v["attributes"][0]["value"], Value::Null);
        assert_eq!(v["attributes"][1]["value"]["stringValue"], "hello");
    }

    #[test]
    fn test_patch_otel_json_deeply_nested() {
        let mut v = serde_json::json!({
            "resourceSpans": [{
                "scopeSpans": [{
                    "spans": [{
                        "attributes": [
                            {"key": "empty", "value": {}},
                            {"key": "string", "value": {"stringValue": "test"}}
                        ]
                    }]
                }]
            }]
        });
        patch_otel_json(&mut v);
        assert_eq!(
            v["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"][0]["value"],
            Value::Null
        );
    }

    #[test]
    fn test_patch_otel_json_null_scalar_attrs() {
        for field in &[
            "doubleValue",
            "intValue",
            "stringValue",
            "boolValue",
            "bytesValue",
        ] {
            let mut v = serde_json::json!({"value": {}});
            v["value"]
                .as_object_mut()
                .unwrap()
                .insert(field.to_string(), Value::Null);
            patch_otel_json(&mut v);
            assert_eq!(
                v["value"],
                Value::Null,
                "field `{field}` with null should be stripped"
            );
        }

        // Non-null scalar must be preserved.
        let mut v = serde_json::json!({"value": {"stringValue": "gpt-4"}});
        patch_otel_json(&mut v);
        assert_eq!(v["value"]["stringValue"], "gpt-4");
    }

    #[test]
    fn test_parse_json_with_null_double_attr() {
        let json = r#"{"resourceSpans":[{"scopeSpans":[{"spans":[{
            "traceId":"","spanId":"",
            "attributes":[{"key":"cost","value":{"doubleValue":null}}]
        }]}]}]}"#;
        let body = Bytes::from(json);
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());

        let parsed = parse_request(&body, &headers, 4 * 1024 * 1024).unwrap();
        assert_eq!(parsed.resource_spans.len(), 1);
    }
}
