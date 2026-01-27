use crate::log_record::KafkaLogRow;
use crate::service::Service;
use axum::{
    extract::State,
    extract::{Path, Query},
    http::{HeaderMap, StatusCode},
    response::Json,
};
use base64::{engine::general_purpose::STANDARD as base64_standard, Engine};
use bytes::Bytes;
use chrono::{TimeZone, Utc};
use serde::Deserialize;
use serde_json::json;
use std::collections::HashMap;
use tracing::{debug, error, instrument};
use uuid::Uuid;

#[derive(Deserialize, Debug)]
pub struct DatadogLog {
    #[serde(default)]
    pub ddsource: Option<String>,
    #[serde(default)]
    pub ddtags: Option<String>,
    #[serde(default)]
    pub hostname: Option<String>,
    #[serde(default)]
    pub message: Option<String>,
    #[serde(default)]
    pub service: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub timestamp: Option<i64>,
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

pub fn normalize_datadog_severity(status: Option<&str>) -> (String, i32) {
    match status.map(|s| s.to_lowercase()).as_deref() {
        Some("emergency") | Some("emerg") | Some("critical") | Some("crit") | Some("alert") => {
            ("fatal".to_string(), 21)
        }
        Some("error") | Some("err") => ("error".to_string(), 17),
        Some("warning") | Some("warn") => ("warn".to_string(), 13),
        Some("notice") | Some("info") => ("info".to_string(), 9),
        Some("debug") => ("debug".to_string(), 5),
        Some("trace") => ("trace".to_string(), 1),
        _ => ("info".to_string(), 9),
    }
}

pub fn parse_datadog_tags(ddtags: Option<&str>) -> HashMap<String, String> {
    let mut attributes = HashMap::new();
    if let Some(tags) = ddtags {
        for tag in tags.split(',') {
            let tag = tag.trim();
            if let Some((key, value)) = tag.split_once(':') {
                attributes.insert(key.to_string(), json!(value).to_string());
            } else if !tag.is_empty() {
                attributes.insert(tag.to_string(), json!(true).to_string());
            }
        }
    }
    attributes
}

fn extract_token_from_auth_header(headers: &HeaderMap) -> Option<String> {
    headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .map(|auth| {
            // Support both "Bearer <token>" and just "<token>"
            if let Some(token) = auth.strip_prefix("Bearer ") {
                token.trim().to_string()
            } else if let Some(token) = auth.strip_prefix("bearer ") {
                token.trim().to_string()
            } else {
                auth.trim().to_string()
            }
        })
}

fn hex_to_base64(hex_str: &str) -> String {
    // Remove any 0x prefix if present
    let hex_str = hex_str.strip_prefix("0x").unwrap_or(hex_str);

    // Decode hex to bytes
    match hex::decode(hex_str) {
        Ok(bytes) => base64_standard.encode(&bytes),
        Err(_) => {
            // If hex decoding fails, return empty string
            debug!("Failed to decode hex string: {}", hex_str);
            String::new()
        }
    }
}

pub fn extract_trace_span_ids(extra: &HashMap<String, serde_json::Value>) -> (String, String) {
    let trace_id_hex = extra
        .get("dd.trace_id")
        .or_else(|| extra.get("trace_id"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    let span_id_hex = extra
        .get("dd.span_id")
        .or_else(|| extra.get("span_id"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    let trace_id = if trace_id_hex.is_empty() {
        String::new()
    } else {
        hex_to_base64(trace_id_hex)
    };

    let span_id = if span_id_hex.is_empty() {
        String::new()
    } else {
        hex_to_base64(span_id_hex)
    };

    (trace_id, span_id)
}

pub fn datadog_log_to_kafka_row(log: DatadogLog, query_params: &DatadogQueryParams) -> KafkaLogRow {
    // Body values take precedence over query params
    let status = log.status.as_deref().or(query_params.status.as_deref());
    let (severity_text, severity_number) = normalize_datadog_severity(status);

    let timestamp = log
        .timestamp
        .and_then(|ts| {
            // Datadog uses milliseconds since epoch
            Utc.timestamp_millis_opt(ts).single()
        })
        .unwrap_or_else(Utc::now);

    let service = log.service.or_else(|| query_params.service.clone());
    let hostname = log.hostname.or_else(|| query_params.hostname.clone());
    let ddsource = log.ddsource.or_else(|| query_params.ddsource.clone());
    let message = log.message.or_else(|| query_params.message.clone());

    let mut resource_attributes = HashMap::new();
    if let Some(ref service_val) = service {
        resource_attributes.insert("service.name".to_string(), json!(service_val).to_string());
    }
    if let Some(ref hostname_val) = hostname {
        resource_attributes.insert("host.name".to_string(), json!(hostname_val).to_string());
    }
    if let Some(ref source_val) = ddsource {
        resource_attributes.insert("ddsource".to_string(), json!(source_val).to_string());
    }

    // Add query param ddtags to resource_attributes
    let query_tags = parse_datadog_tags(query_params.ddtags.as_deref());
    resource_attributes.extend(query_tags);

    // Add body ddtags to resource_attributes (takes precedence)
    let body_tags = parse_datadog_tags(log.ddtags.as_deref());
    resource_attributes.extend(body_tags);

    // Extract trace and span IDs from body extra attributes
    let (trace_id, span_id) = extract_trace_span_ids(&log.extra);

    // Extract event name and instrumentation scope from body extra attributes
    let event_name = log
        .extra
        .get("event.name")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    let instrumentation_scope = log
        .extra
        .get("otel.scope.name")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    // Merge attributes: query params extra fields, then body extra fields
    // Later values override earlier ones
    let mut attributes = HashMap::new();

    for (key, value) in &query_params.extra {
        attributes.insert(key.clone(), json!(value).to_string());
    }

    for (key, value) in &log.extra {
        attributes.insert(key.clone(), value.to_string());
    }

    KafkaLogRow {
        uuid: Uuid::now_v7().to_string(),
        trace_id,
        span_id,
        trace_flags: 0,
        timestamp,
        observed_timestamp: Utc::now(),
        body: message.unwrap_or_default(),
        severity_text,
        severity_number,
        service_name: service.unwrap_or_default(),
        resource_attributes,
        instrumentation_scope,
        event_name,
        attributes,
    }
}

#[derive(Deserialize, Debug)]
pub struct DatadogQueryParams {
    pub token: Option<String>,
    pub ddtags: Option<String>,
    pub ddsource: Option<String>,
    pub service: Option<String>,
    pub hostname: Option<String>,
    pub message: Option<String>,
    pub status: Option<String>,
    #[serde(flatten)]
    pub extra: HashMap<String, String>,
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
pub async fn export_datadog_logs_http(
    State(service): State<Service>,
    path_token: Option<Path<String>>,
    Query(query_params): Query<DatadogQueryParams>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    // Try to get token from: path, Authorization header, or query param
    let token = match path_token {
        Some(Path(t)) if !t.is_empty() => t,
        _ => match extract_token_from_auth_header(&headers) {
            Some(t) if !t.is_empty() => t,
            _ => match query_params.token.as_deref() {
                Some(t) if !t.is_empty() => t.to_string(),
                _ => {
                    error!("No token provided");
                    return Err((
                        StatusCode::UNAUTHORIZED,
                        Json(json!({"error": "No token provided"})),
                    ));
                }
            },
        },
    };

    if service.token_dropper.should_drop(&token, "") {
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error": "Invalid token"})),
        ));
    }

    tracing::Span::current().record("token", &token);

    let logs: Vec<DatadogLog> = match serde_json::from_slice::<Vec<DatadogLog>>(&body) {
        Ok(logs) => logs,
        Err(_) => match serde_json::from_slice::<DatadogLog>(&body) {
            Ok(log) => vec![log],
            Err(e) => {
                error!("Failed to parse Datadog logs: {}", e);
                return Err((
                    StatusCode::BAD_REQUEST,
                    Json(json!({"error": format!("Failed to parse Datadog logs: {}", e)})),
                ));
            }
        },
    };

    let rows: Vec<KafkaLogRow> = logs
        .into_iter()
        .map(|log| datadog_log_to_kafka_row(log, &query_params))
        .collect();

    let row_count = rows.len();
    if let Err(e) = service.sink.write(&token, rows, body.len() as u64).await {
        error!("Failed to send logs to Kafka: {}", e);
        return Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error": "Internal server error"})),
        ));
    } else {
        debug!("Successfully sent {} Datadog logs to Kafka", row_count);
    }

    // Datadog returns empty JSON object on success
    Ok(Json(json!({})))
}
