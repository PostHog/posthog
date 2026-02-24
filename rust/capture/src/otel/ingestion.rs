use axum::http::HeaderMap;
use bytes::Bytes;
use flate2::read::GzDecoder;
use opentelemetry_proto::tonic::collector::trace::v1::ExportTraceServiceRequest;
use prost::Message;
use serde_json::Value;
use std::io::Read;
use tracing::warn;

use crate::api::CaptureError;

/// Patch empty `{}` objects in OTEL JSON that should be `null` for proper deserialization.
/// See https://github.com/open-telemetry/opentelemetry-rust/issues/1253
fn patch_otel_json(v: &mut Value) {
    match v {
        Value::Object(map) => {
            if let Some(inner) = map.get_mut("value") {
                if inner.is_object() && inner.as_object().map(|obj| obj.is_empty()).unwrap_or(false)
                {
                    *inner = Value::Null;
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

fn decompress_gzip(compressed: &Bytes) -> Result<Bytes, CaptureError> {
    let mut decoder = GzDecoder::new(&compressed[..]);
    let mut decompressed = Vec::new();
    decoder.read_to_end(&mut decompressed).map_err(|e| {
        warn!("Failed to decompress gzip body: {}", e);
        CaptureError::RequestDecodingError(format!("Failed to decompress gzip body: {e}"))
    })?;
    Ok(Bytes::from(decompressed))
}

pub fn parse_request(
    body: &Bytes,
    headers: &HeaderMap,
) -> Result<ExportTraceServiceRequest, CaptureError> {
    let content_encoding = headers
        .get("content-encoding")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    let body = if content_encoding.eq_ignore_ascii_case("gzip") {
        decompress_gzip(body)?
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
        ExportTraceServiceRequest::decode(&body[..]).map_err(|e| {
            warn!("Failed to decode OTEL protobuf: {}", e);
            CaptureError::RequestParsingError(format!("Invalid protobuf: {e}"))
        })
    } else if is_json {
        let mut json_value: Value = serde_json::from_slice(&body).map_err(|e| {
            warn!("Failed to parse OTEL JSON: {}", e);
            CaptureError::RequestParsingError(format!("Invalid JSON: {e}"))
        })?;

        patch_otel_json(&mut json_value);

        serde_json::from_value(json_value).map_err(|e| {
            warn!("Failed to parse OTEL trace request: {}", e);
            CaptureError::RequestParsingError(format!("Invalid OTLP trace format: {e}"))
        })
    } else {
        warn!(
            "OTEL endpoint received unsupported content type: {}",
            content_type
        );
        Err(CaptureError::RequestDecodingError(
            "Content-Type must be application/x-protobuf or application/json".to_string(),
        ))
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
    fn test_parse_protobuf() {
        let request = make_protobuf_request();
        let body = Bytes::from(request.encode_to_vec());
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/x-protobuf".parse().unwrap());

        let parsed = parse_request(&body, &headers).unwrap();
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

        let parsed = parse_request(&body, &headers).unwrap();
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

        let parsed = parse_request(&body, &headers).unwrap();
        assert_eq!(parsed.resource_spans.len(), 1);
    }

    #[test]
    fn test_parse_malformed_protobuf() {
        let body = Bytes::from(vec![0xFF, 0xFF, 0xFF]);
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/x-protobuf".parse().unwrap());

        assert!(parse_request(&body, &headers).is_err());
    }

    #[test]
    fn test_parse_malformed_json() {
        let body = Bytes::from("not json");
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());

        assert!(parse_request(&body, &headers).is_err());
    }

    #[test]
    fn test_parse_unsupported_content_type() {
        let body = Bytes::from("data");
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "text/plain".parse().unwrap());

        assert!(parse_request(&body, &headers).is_err());
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
}
