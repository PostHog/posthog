use crate::log_record::KafkaLogRow;
use axum::{
    extract::Query,
    extract::State,
    http::{HeaderMap, StatusCode},
    response::Json,
};
use bytes::Bytes;
use limiters::token_dropper::TokenDropper;
use opentelemetry_proto::tonic::collector::logs::v1::ExportLogsServiceRequest;
use prost::Message;
use serde::Deserialize;
use serde_json::{json, Value};
use std::fs::File;
use std::io::Write;
use std::sync::Arc;

use crate::kafka::KafkaSink;

use tracing::{debug, error, instrument};

// due to a bug in the otel proto rust library we need to patch the json to support (valid) empty Values
// see https://github.com/open-telemetry/opentelemetry-rust/issues/1253
// FIXME: remove once upstream has fixed the issue, OR we should fork upstream and fix the issue ourselves
fn patch_otel_json(v: &mut Value) {
    match v {
        Value::Object(map) => {
            // In OTel, AnyValue is usually a field named "value"
            // If we find "value": {}, change it to "value": null
            if let Some(inner) = map.get_mut("value") {
                if inner.is_object() && inner.as_object().map(|obj| obj.is_empty()).unwrap_or(false)
                {
                    *inner = Value::Null;
                }
            }
            // Recurse through all other keys
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

/// Parse OpenTelemetry log message from JSON bytes.
///
/// Supports both single JSON objects and JSONL format (JSON Lines).
/// For JSONL, multiple ExportLogsServiceRequest objects are parsed and merged
/// into a single request by combining their resource_logs arrays.
pub fn parse_otel_message(json_bytes: &Bytes) -> Result<ExportLogsServiceRequest, anyhow::Error> {
    // First, attempt to parse the entire payload as a single JSON object.
    // If this succeeds, we treat it as a normal ExportLogsServiceRequest.
    if let Ok(mut v) = serde_json::from_slice::<Value>(json_bytes) {
        patch_otel_json(&mut v);
        let result: ExportLogsServiceRequest = serde_json::from_value(v)?;
        return Ok(result);
    }

    // If parsing as a single JSON object fails, fall back to JSONL (JSON Lines)
    // where each non-empty line is expected to be a complete JSON object.
    let json_str = std::str::from_utf8(json_bytes)?;
    let lines: Vec<&str> = json_str
        .lines()
        .filter(|line| !line.trim().is_empty())
        .collect();

    // Handle JSONL format - parse each line and merge them
    let mut merged_request = ExportLogsServiceRequest {
        resource_logs: Vec::new(),
    };

    for line in lines {
        let mut v: Value = serde_json::from_str(line)?;
        patch_otel_json(&mut v);
        let request: ExportLogsServiceRequest = serde_json::from_value(v)?;
        merged_request.resource_logs.extend(request.resource_logs);
    }

    if merged_request.resource_logs.is_empty() {
        return Err(anyhow::anyhow!("No valid log data found in request"));
    }

    Ok(merged_request)
}

#[derive(Clone)]
pub struct Service {
    sink: KafkaSink,
    token_dropper: Arc<TokenDropper>,
}

#[derive(Deserialize)]
pub struct QueryParams {
    token: Option<String>,
}

impl Service {
    pub async fn new(
        kafka_sink: KafkaSink,
        token_dropper: TokenDropper,
    ) -> Result<Self, anyhow::Error> {
        Ok(Self {
            sink: kafka_sink,
            token_dropper: token_dropper.into(),
        })
    }
}

#[instrument(skip_all, fields(
    token = tracing::field::Empty,
    content_type = %headers.get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or(""),
    user_agent = %headers.get("user-agent")
        .and_then(|v| v.to_str().ok())
        .unwrap_or(""),
    content_length = %headers.get("content-length")
        .and_then(|v| v.to_str().ok())
        .unwrap_or(""),
    content_encoding = %headers.get("content-encoding")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")))
]
pub async fn export_logs_http(
    State(service): State<Service>,
    Query(query_params): Query<QueryParams>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    // The Project API key must be passed in as a Bearer token in the Authorization header
    if !headers.contains_key("Authorization") && query_params.token.is_none() {
        error!("No token provided");
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error": format!("No token provided")})),
        ));
    }

    let token = if headers.contains_key("Authorization") {
        match headers["Authorization"]
            .to_str()
            .unwrap_or("")
            .split("Bearer ")
            .last()
        {
            Some(token) if !token.is_empty() => token,
            _ => {
                error!("No token provided");
                return Err((
                    StatusCode::UNAUTHORIZED,
                    Json(json!({"error": format!("No token provided")})),
                ));
            }
        }
    } else {
        match query_params.token {
            Some(ref token) if !token.is_empty() => token,
            _ => {
                error!("No token provided");
                return Err((
                    StatusCode::UNAUTHORIZED,
                    Json(json!({"error": format!("No token provided")})),
                ));
            }
        }
    };
    if service.token_dropper.should_drop(token, "") {
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error": format!("Invalid token")})),
        ));
    }

    tracing::Span::current().record("token", token);

    // Try to decode as Protobuf, if this fails, try JSON.
    // We do this over relying on Content-Type headers to be as permissive as possible in what we accept.
    let export_request = match ExportLogsServiceRequest::decode(body.as_ref()) {
        Ok(request) => request,
        Err(proto_err) => match parse_otel_message(&body) {
            Ok(request) => request,
            Err(json_err) => {
                // Write last failed event to a file
                // To make this super simple, we literally write a single event to /tmp/last_failed_event.txt
                //
                if let Err(e) = File::create("/tmp/last_failed_event.txt").and_then(|mut file|
                    // write the raw message to a file prepended by the token for debugging
                    file.write_all(token.as_bytes()).and_then(|_| file.write_all(&body)))
                {
                    error!("Failed to write last failed event to file: {}", e);
                }
                error!(
                    "Failed to decode JSON: {} or Protobuf: {}",
                    json_err, proto_err
                );
                return Err((
                    StatusCode::BAD_REQUEST,
                    Json(
                        json!({"error": format!("Failed to decode JSON: {} or Protobuf: {}", json_err, proto_err)}),
                    ),
                ));
            }
        },
    };

    let mut rows: Vec<KafkaLogRow> = Vec::new();
    for resource_logs in export_request.resource_logs {
        for scope_logs in resource_logs.scope_logs {
            for log_record in scope_logs.log_records {
                let row = match KafkaLogRow::new(
                    log_record,
                    resource_logs.resource.clone(),
                    scope_logs.scope.clone(),
                ) {
                    Ok(row) => row,
                    Err(e) => {
                        error!("Failed to create LogRow: {e}");
                        return Err((
                            StatusCode::BAD_REQUEST,
                            Json(json!({"error": format!("Bad input format provided")})),
                        ));
                    }
                };
                rows.push(row);
            }
        }
    }

    let row_count = rows.len();
    if let Err(e) = service.sink.write(token, rows, body.len() as u64).await {
        error!("Failed to send logs to Kafka: {}", e);
        return Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error": format!("Internal server error")})),
        ));
    } else {
        debug!("Successfully sent {} logs to Kafka", row_count);
    }

    // Return empty JSON object per OTLP spec
    Ok(Json(json!({})))
}

/// Handle CORS preflight requests (OPTIONS method) for all log endpoints.
///
/// This endpoint supports all preflight requests by returning an empty JSON response.
/// The actual CORS headers are handled by the CorsLayer middleware in main.rs,
/// which provides a very permissive policy allowing all origins, methods, and headers
/// to support various SDK versions and reverse proxy configurations.
pub async fn options_handler(
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    Ok(Json(json!({})))
}
