use axum::http::HeaderMap;
use bytes::{Buf, Bytes};
use opentelemetry_proto::tonic::collector::logs::v1::ExportLogsServiceRequest;
use opentelemetry_proto::tonic::collector::trace::v1::ExportTraceServiceRequest;
use prost::Message;
use serde::de::{DeserializeSeed, IgnoredAny, MapAccess, SeqAccess, Visitor};
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
        if tag == 2 && wire_type == prost::encoding::WireType::LengthDelimited {
            increment_log_node_count(node_count, node_limit)?;
            let mut scope_logs = take_message(resource_logs).map_err(invalid_logs_protobuf)?;
            count_scope_log_records(&mut scope_logs, node_count, node_limit)?;
        } else {
            prost::encoding::skip_field(
                wire_type,
                tag,
                resource_logs,
                prost::encoding::DecodeContext::default(),
            )
            .map_err(invalid_logs_protobuf)?;
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
        if tag == 2 && wire_type == prost::encoding::WireType::LengthDelimited {
            let _ = take_message(scope_logs).map_err(invalid_logs_protobuf)?;
            increment_log_node_count(node_count, node_limit)?;
        } else {
            prost::encoding::skip_field(
                wire_type,
                tag,
                scope_logs,
                prost::encoding::DecodeContext::default(),
            )
            .map_err(invalid_logs_protobuf)?;
        }
    }
    Ok(())
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
    LogsSeed {
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

struct LogsSeed<'a> {
    node_count: &'a mut usize,
    node_limit: usize,
}

impl<'de> DeserializeSeed<'de> for LogsSeed<'_> {
    type Value = ();

    fn deserialize<D>(self, deserializer: D) -> Result<(), D::Error>
    where
        D: Deserializer<'de>,
    {
        deserializer.deserialize_map(LogsVisitor {
            node_count: self.node_count,
            node_limit: self.node_limit,
        })
    }
}

struct LogsVisitor<'a> {
    node_count: &'a mut usize,
    node_limit: usize,
}

impl<'de> Visitor<'de> for LogsVisitor<'_> {
    type Value = ();

    fn expecting(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
        formatter.write_str("an OTLP logs request")
    }

    fn visit_map<A>(self, mut map: A) -> Result<(), A::Error>
    where
        A: MapAccess<'de>,
    {
        while let Some(key) = map.next_key::<String>()? {
            if key == "resourceLogs" {
                map.next_value_seed(NodeSequenceSeed {
                    node_count: self.node_count,
                    node_limit: self.node_limit,
                    child_key: Some("scopeLogs"),
                })?;
            } else {
                map.next_value::<IgnoredAny>()?;
            }
        }
        Ok(())
    }
}

struct NodeSequenceSeed<'a> {
    node_count: &'a mut usize,
    node_limit: usize,
    child_key: Option<&'static str>,
}

impl<'de> DeserializeSeed<'de> for NodeSequenceSeed<'_> {
    type Value = ();

    fn deserialize<D>(self, deserializer: D) -> Result<(), D::Error>
    where
        D: Deserializer<'de>,
    {
        deserializer.deserialize_seq(NodeSequenceVisitor {
            node_count: self.node_count,
            node_limit: self.node_limit,
            child_key: self.child_key,
        })
    }
}

struct NodeSequenceVisitor<'a> {
    node_count: &'a mut usize,
    node_limit: usize,
    child_key: Option<&'static str>,
}

impl<'de> Visitor<'de> for NodeSequenceVisitor<'_> {
    type Value = ();

    fn expecting(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
        formatter.write_str("an OTLP node array")
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<(), A::Error>
    where
        A: SeqAccess<'de>,
    {
        while let Some(()) = sequence.next_element_seed(NodeSeed {
            node_count: self.node_count,
            node_limit: self.node_limit,
            child_key: self.child_key,
        })? {}
        Ok(())
    }
}

struct NodeSeed<'a> {
    node_count: &'a mut usize,
    node_limit: usize,
    child_key: Option<&'static str>,
}

impl<'de> DeserializeSeed<'de> for NodeSeed<'_> {
    type Value = ();

    fn deserialize<D>(self, deserializer: D) -> Result<(), D::Error>
    where
        D: Deserializer<'de>,
    {
        increment_log_node_count(self.node_count, self.node_limit)
            .map_err(serde::de::Error::custom)?;
        match self.child_key {
            Some(child_key) => deserializer.deserialize_map(NodeVisitor {
                node_count: self.node_count,
                node_limit: self.node_limit,
                child_key,
            }),
            None => <IgnoredAny as serde::Deserialize>::deserialize(deserializer).map(|_| ()),
        }
    }
}

struct NodeVisitor<'a> {
    node_count: &'a mut usize,
    node_limit: usize,
    child_key: &'static str,
}

impl<'de> Visitor<'de> for NodeVisitor<'_> {
    type Value = ();

    fn expecting(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
        formatter.write_str("an OTLP container")
    }

    fn visit_map<A>(self, mut map: A) -> Result<(), A::Error>
    where
        A: MapAccess<'de>,
    {
        while let Some(key) = map.next_key::<String>()? {
            if key == self.child_key {
                let next_key = (self.child_key == "scopeLogs").then_some("logRecords");
                map.next_value_seed(NodeSequenceSeed {
                    node_count: self.node_count,
                    node_limit: self.node_limit,
                    child_key: next_key,
                })?;
            } else {
                map.next_value::<IgnoredAny>()?;
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderMap;
    use flate2::write::GzEncoder;
    use flate2::Compression;
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
