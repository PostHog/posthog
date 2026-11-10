use crate::authorizer::Signal;
use crate::log_record::{apply_timestamp_override, datetime_from_millis, KafkaLogRow};
use crate::service::{decode_body_if_gzip_magic, Service};
use axum::{
    extract::{Extension, Path, Query, State},
    http::{HeaderMap, StatusCode},
    response::Json,
};
use base64::{prelude::BASE64_STANDARD, Engine};
use bytes::Bytes;
use chrono::Utc;
use metrics::counter;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use tracing::{debug, error, instrument, warn};
use uuid::Uuid;

const RECORDS_COUNTER: &str = "capture_logs_vercel_records_total";
const REJECTED_COUNTER: &str = "capture_logs_vercel_requests_rejected_total";
/// A drain delivery is at most 1 MB, which is a few thousand real lines. The cap bounds the work a
/// body of tiny entries can cause before any line is converted.
pub const MAX_LINES_PER_DELIVERY: usize = 10_000;

fn lenient<'de, D, T>(deserializer: D) -> Result<Option<T>, D::Error>
where
    D: Deserializer<'de>,
    T: DeserializeOwned,
{
    let value = Option::<Value>::deserialize(deserializer)?;
    Ok(value.and_then(|v| serde_json::from_value(v).ok()))
}

/// One line of a Vercel log drain delivery. Fields follow the drain's logs schema. Unknown fields
/// are ignored and a field of an unexpected type reads as missing, so a schema change on their
/// side loses that attribute, not the line.
#[derive(Deserialize, Debug, Default)]
#[serde(rename_all = "camelCase")]
pub struct VercelLog {
    #[serde(default, deserialize_with = "lenient")]
    pub id: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub deployment_id: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub source: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub host: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub timestamp: Option<i64>,
    #[serde(default, deserialize_with = "lenient")]
    pub project_id: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub project_name: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub level: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub message: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub build_id: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub entrypoint: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub destination: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub path: Option<String>,
    #[serde(rename = "type")]
    #[serde(default, deserialize_with = "lenient")]
    pub log_type: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub status_code: Option<i64>,
    #[serde(default, deserialize_with = "lenient")]
    pub request_id: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub environment: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub custom_environment: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub branch: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub ja3_digest: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub ja4_digest: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub edge_type: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub execution_region: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub trace_id: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub span_id: Option<String>,
    #[serde(rename = "trace.id")]
    #[serde(default, deserialize_with = "lenient")]
    pub trace_id_dotted: Option<String>,
    #[serde(rename = "span.id")]
    #[serde(default, deserialize_with = "lenient")]
    pub span_id_dotted: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub proxy: Option<VercelProxy>,
}

#[derive(Deserialize, Debug, Default)]
#[serde(rename_all = "camelCase")]
pub struct VercelProxy {
    #[serde(default, deserialize_with = "lenient")]
    pub timestamp: Option<i64>,
    #[serde(default, deserialize_with = "lenient")]
    pub method: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub host: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub path: Option<String>,
    // An array of strings per the schema; a bare string is accepted too.
    pub user_agent: Option<Value>,
    #[serde(default, deserialize_with = "lenient")]
    pub region: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub referer: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub status_code: Option<i64>,
    #[serde(default, deserialize_with = "lenient")]
    pub client_ip: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub scheme: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub response_byte_size: Option<i64>,
    #[serde(default, deserialize_with = "lenient")]
    pub cache_id: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub path_type: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub path_type_variant: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub vercel_id: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub vercel_cache: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub lambda_region: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub waf_action: Option<String>,
    #[serde(default, deserialize_with = "lenient")]
    pub waf_rule_id: Option<String>,
}

#[derive(Debug, Default)]
pub struct ParsedDelivery {
    pub logs: Vec<VercelLog>,
    pub invalid: u64,
    pub first_error: Option<String>,
}

impl ParsedDelivery {
    fn push(&mut self, result: Result<VercelLog, String>) {
        match result {
            Ok(log) => self.logs.push(log),
            Err(e) => {
                self.invalid += 1;
                self.first_error.get_or_insert(e);
            }
        }
    }
}

/// The token from the URL path first, then the `Authorization` header (`Bearer`, `bearer` or a bare
/// token), then `?token=`. A drain can only set its URL and custom headers.
pub fn token_from_request(
    path_token: Option<&str>,
    headers: &HeaderMap,
    query_token: Option<&str>,
) -> Option<String> {
    let header_token = headers
        .get("authorization")
        .and_then(|value| value.to_str().ok())
        .map(|auth| {
            auth.strip_prefix("Bearer ")
                .or_else(|| auth.strip_prefix("bearer "))
                .unwrap_or(auth)
                .trim()
        });
    [path_token, header_token, query_token]
        .into_iter()
        .flatten()
        .find(|token| !token.is_empty())
        .map(str::to_string)
}

fn hex_to_base64(hex_str: &str) -> String {
    let hex_str = hex_str.strip_prefix("0x").unwrap_or(hex_str);
    match hex::decode(hex_str) {
        Ok(bytes) => BASE64_STANDARD.encode(bytes),
        Err(_) => {
            debug!("Failed to decode hex string: {}", hex_str);
            String::new()
        }
    }
}

fn json_type(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "a boolean",
        Value::Number(_) => "a number",
        Value::String(_) => "a string",
        Value::Array(_) => "an array",
        Value::Object(_) => "an object",
    }
}

#[derive(Debug)]
pub enum DeliveryError {
    Json(serde_json::Error),
    TooManyLines,
}

impl std::fmt::Display for DeliveryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            DeliveryError::Json(e) => write!(f, "{e}"),
            DeliveryError::TooManyLines => {
                write!(
                    f,
                    "more than {MAX_LINES_PER_DELIVERY} lines in one delivery"
                )
            }
        }
    }
}

// Every field is optional, so without these checks serde would also turn arrays, scalars and
// unrelated objects into empty rows.
fn log_from_value(value: Value) -> Result<VercelLog, String> {
    match value {
        Value::Object(ref map)
            if !["id", "message", "proxy"]
                .iter()
                .any(|key| map.contains_key(*key)) =>
        {
            Err("expected a log line with an id, message or proxy".to_string())
        }
        Value::Object(_) => serde_json::from_value(value).map_err(|e| e.to_string()),
        // Name the type only: the value itself is customer log content of any size.
        other => Err(format!("expected a JSON object, got {}", json_type(&other))),
    }
}

/// Reads a delivery in either drain format: a JSON array (or one object) or NDJSON. Entries that
/// do not parse are skipped and counted, so one bad line does not make the drain retry the whole
/// batch.
pub fn parse_delivery(body: &[u8]) -> Result<ParsedDelivery, DeliveryError> {
    let text = String::from_utf8_lossy(body);
    let trimmed = text.trim();
    let mut parsed = ParsedDelivery::default();
    if trimmed.is_empty() {
        return Ok(parsed);
    }
    match serde_json::from_str::<Value>(trimmed) {
        Ok(Value::Array(items)) => {
            if items.len() > MAX_LINES_PER_DELIVERY {
                return Err(DeliveryError::TooManyLines);
            }
            for item in items {
                parsed.push(log_from_value(item));
            }
        }
        Ok(item) => parsed.push(log_from_value(item)),
        Err(e) if !trimmed.contains('\n') => return Err(DeliveryError::Json(e)),
        Err(_) => {
            let lines = trimmed.lines().map(str::trim).filter(|l| !l.is_empty());
            if lines.clone().count() > MAX_LINES_PER_DELIVERY {
                return Err(DeliveryError::TooManyLines);
            }
            for line in lines {
                parsed.push(
                    serde_json::from_str(line)
                        .map_err(|e| e.to_string())
                        .and_then(log_from_value),
                );
            }
        }
    }
    Ok(parsed)
}

pub fn normalize_vercel_severity(level: Option<&str>) -> (String, i32) {
    match level.map(str::to_lowercase).as_deref() {
        Some("fatal") => ("fatal".to_string(), 21),
        Some("error") => ("error".to_string(), 17),
        Some("warning") | Some("warn") => ("warn".to_string(), 13),
        _ => ("info".to_string(), 9),
    }
}

fn put(map: &mut HashMap<String, String>, key: &str, value: Option<impl Serialize>) {
    if let Some(value) = value {
        map.insert(key.to_string(), json!(value).to_string());
    }
}

fn first_user_agent(user_agent: &Option<Value>) -> Option<String> {
    match user_agent {
        Some(Value::Array(values)) => values.first().and_then(|v| v.as_str()).map(String::from),
        Some(Value::String(value)) => Some(value.clone()),
        _ => None,
    }
}

pub fn vercel_log_to_kafka_row(log: VercelLog, token: &str) -> (KafkaLogRow, bool) {
    // A redelivered batch gets the same row ids, so its duplicates can be told apart.
    let uuid = match log.id.as_deref().filter(|id| !id.is_empty()) {
        Some(id) => Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!("vercel-log:{token}:{id}").as_bytes(),
        ),
        None => Uuid::now_v7(),
    };
    let (severity_text, severity_number) = normalize_vercel_severity(log.level.as_deref());
    let proxy = log.proxy.unwrap_or_default();
    let raw_timestamp = datetime_from_millis(log.timestamp.or(proxy.timestamp));

    let service_name = log
        .project_name
        .clone()
        .or_else(|| log.project_id.clone())
        .unwrap_or_default();

    let mut resource_attributes = HashMap::new();
    if !service_name.is_empty() {
        put(
            &mut resource_attributes,
            "service.name",
            Some(&service_name),
        );
    }
    put(
        &mut resource_attributes,
        "vercel.project.id",
        log.project_id,
    );
    put(
        &mut resource_attributes,
        "vercel.project.name",
        log.project_name,
    );
    put(
        &mut resource_attributes,
        "vercel.deployment.id",
        log.deployment_id,
    );
    put(
        &mut resource_attributes,
        "deployment.environment.name",
        log.environment,
    );
    put(
        &mut resource_attributes,
        "vercel.custom_environment",
        log.custom_environment,
    );
    put(&mut resource_attributes, "vcs.ref.head.name", log.branch);

    let (url_path, url_query) = match proxy.path.as_deref() {
        Some(full) => match full.split_once('?') {
            Some((path, query)) => (Some(path.to_string()), Some(query.to_string())),
            None => (Some(full.to_string()), None),
        },
        None => (None, None),
    };
    // Vercel uses sentinels such as -1 (background revalidation, crashed function), so only a real
    // HTTP status becomes `http.response.status_code`; the raw values stay under `vercel.*`.
    let is_http_status = |code: &i64| (100..=599).contains(code);
    let status_code = proxy
        .status_code
        .filter(is_http_status)
        .or(log.status_code.filter(is_http_status));
    let user_agent = first_user_agent(&proxy.user_agent);

    // A request line from the edge carries no message, so the record gets an access-log style
    // body instead of an empty one.
    let body = match log.message.filter(|m| !m.is_empty()) {
        Some(message) => message,
        None => match (&proxy.method, &proxy.path) {
            (Some(method), Some(path)) => match status_code {
                Some(code) => format!("{method} {path} {code}"),
                None => format!("{method} {path}"),
            },
            _ => String::new(),
        },
    };

    let mut attributes = HashMap::new();
    put(&mut attributes, "vercel.log.id", log.id);
    put(&mut attributes, "vercel.source", log.source);
    put(&mut attributes, "vercel.type", log.log_type);
    put(&mut attributes, "vercel.entrypoint", log.entrypoint);
    put(&mut attributes, "vercel.function.path", log.path);
    put(&mut attributes, "vercel.request.id", log.request_id);
    put(&mut attributes, "vercel.build.id", log.build_id);
    put(&mut attributes, "vercel.destination", log.destination);
    put(&mut attributes, "vercel.edge_type", log.edge_type);
    put(
        &mut attributes,
        "vercel.execution_region",
        log.execution_region,
    );
    put(&mut attributes, "http.request.method", proxy.method);
    put(&mut attributes, "server.address", proxy.host.or(log.host));
    put(&mut attributes, "url.scheme", proxy.scheme);
    put(&mut attributes, "url.path", url_path);
    put(&mut attributes, "url.query", url_query);
    put(&mut attributes, "http.response.status_code", status_code);
    put(
        &mut attributes,
        "vercel.proxy.status_code",
        proxy.status_code.filter(|code| !is_http_status(code)),
    );
    put(
        &mut attributes,
        "vercel.status_code",
        log.status_code.filter(|code| !is_http_status(code)),
    );
    put(
        &mut attributes,
        "http.response.body.size",
        proxy.response_byte_size,
    );
    put(
        &mut attributes,
        "http.request.header.referer",
        proxy.referer,
    );
    put(&mut attributes, "client.address", proxy.client_ip);
    put(&mut attributes, "user_agent.original", user_agent);
    put(&mut attributes, "tls.client.ja3", log.ja3_digest);
    put(&mut attributes, "tls.client.ja4", log.ja4_digest);
    put(&mut attributes, "vercel.proxy.region", proxy.region);
    put(&mut attributes, "vercel.proxy.id", proxy.vercel_id);
    put(&mut attributes, "vercel.cache", proxy.vercel_cache);
    put(&mut attributes, "vercel.cache_id", proxy.cache_id);
    put(&mut attributes, "vercel.path_type", proxy.path_type);
    put(
        &mut attributes,
        "vercel.path_type_variant",
        proxy.path_type_variant,
    );
    put(&mut attributes, "vercel.lambda_region", proxy.lambda_region);
    put(&mut attributes, "vercel.waf.action", proxy.waf_action);
    put(&mut attributes, "vercel.waf.rule_id", proxy.waf_rule_id);

    let trace_id = log
        .trace_id
        .or(log.trace_id_dotted)
        .map(|id| hex_to_base64(&id))
        .unwrap_or_default();
    let span_id = log
        .span_id
        .or(log.span_id_dotted)
        .map(|id| hex_to_base64(&id))
        .unwrap_or_default();

    let (timestamp, was_overridden) = apply_timestamp_override(raw_timestamp, &mut attributes);

    let row = KafkaLogRow {
        uuid: uuid.to_string(),
        trace_id,
        span_id,
        trace_flags: 0,
        timestamp,
        observed_timestamp: Utc::now(),
        body,
        severity_text,
        severity_number,
        service_name,
        resource_attributes,
        instrumentation_scope: String::new(),
        event_name: String::new(),
        attributes,
        bytes_uncompressed: None,
        retention_days: None,
        pattern: None,
        pattern_version: None,
    }
    .with_computed_bytes();
    (row, was_overridden)
}

#[derive(Clone, Debug, Default)]
pub struct VercelDrainGate {
    allow_all: bool,
    tokens: Arc<HashSet<String>>,
}

impl VercelDrainGate {
    pub fn new(enabled_tokens: &str) -> Self {
        let tokens: HashSet<String> = enabled_tokens
            .split(',')
            .map(str::trim)
            .filter(|t| !t.is_empty())
            .map(String::from)
            .collect();
        Self {
            allow_all: tokens.contains("*"),
            tokens: Arc::new(tokens),
        }
    }

    pub fn allows(&self, token: &str) -> bool {
        self.allow_all || self.tokens.contains(token)
    }
}

#[derive(Deserialize, Debug)]
pub struct VercelQueryParams {
    pub token: Option<String>,
}

#[instrument(skip_all, fields(
    token = tracing::field::Empty,
    content_type = %headers.get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or(""),
    content_length = %headers.get("content-length")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")))
]
pub async fn export_vercel_logs_http(
    State(service): State<Service>,
    Extension(gate): Extension<VercelDrainGate>,
    path_token: Option<Path<String>>,
    Query(query_params): Query<VercelQueryParams>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let Some(token) = token_from_request(
        path_token.as_ref().map(|Path(token)| token.as_str()),
        &headers,
        query_params.token.as_deref(),
    ) else {
        error!("No token provided");
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error": "No token provided"})),
        ));
    };

    service.authorizer.authorize_token(&token, Signal::Logs)?;
    tracing::Span::current().record("token", &token);

    if !gate.allows(&token) {
        debug!("Vercel drain route is not enabled for this token");
        counter!(REJECTED_COUNTER, "reason" => "gate_closed").increment(1);
        return Err((StatusCode::NOT_FOUND, Json(json!({"error": "Not found"}))));
    }

    let body = decode_body_if_gzip_magic(body, service.max_request_body_size_bytes)?;

    let parsed = match parse_delivery(&body) {
        Ok(parsed) => parsed,
        Err(e @ DeliveryError::TooManyLines) => {
            counter!(REJECTED_COUNTER, "reason" => "too_many_lines").increment(1);
            warn!("Rejected Vercel delivery: {}", e);
            return Err((
                StatusCode::PAYLOAD_TOO_LARGE,
                Json(json!({"error": format!("Failed to parse Vercel logs: {}", e)})),
            ));
        }
        Err(e) => {
            error!("Failed to parse Vercel logs: {}", e);
            return Err((
                StatusCode::BAD_REQUEST,
                Json(json!({"error": format!("Failed to parse Vercel logs: {}", e)})),
            ));
        }
    };
    if parsed.invalid > 0 {
        counter!(RECORDS_COUNTER, "kind" => "invalid").increment(parsed.invalid);
        warn!(
            invalid = parsed.invalid,
            first_error = parsed.first_error.as_deref().unwrap_or(""),
            "Skipped Vercel log lines that do not parse"
        );
    }

    // The drain sends a test request when it is created; an empty delivery acknowledges it. A
    // delivery with no usable line gets a 400, so a malformed batch is not acknowledged as stored.
    if parsed.logs.is_empty() {
        if parsed.invalid > 0 {
            return Err((
                StatusCode::BAD_REQUEST,
                Json(json!({"error": format!(
                    "No valid Vercel log lines: {}",
                    parsed.first_error.as_deref().unwrap_or("")
                )})),
            ));
        }
        return Ok(Json(json!({})));
    }

    // A missing or mistyped timestamp falls back to the ingest time; count it so drift is visible.
    let without_timestamp = parsed
        .logs
        .iter()
        .filter(|log| {
            log.timestamp.is_none() && log.proxy.as_ref().and_then(|p| p.timestamp).is_none()
        })
        .count() as u64;
    if without_timestamp > 0 {
        counter!(RECORDS_COUNTER, "kind" => "no_timestamp").increment(without_timestamp);
    }

    let results: Vec<(KafkaLogRow, bool)> = parsed
        .logs
        .into_iter()
        .map(|log| vercel_log_to_kafka_row(log, &token))
        .collect();
    let row_count = results.len();
    let timestamps_overridden = results.iter().filter(|(_, overridden)| *overridden).count() as u64;
    let rows: Vec<KafkaLogRow> = results.into_iter().map(|(row, _)| row).collect();

    if let Err(e) = service
        .sink
        .write(
            &token,
            rows,
            body.len() as u64,
            timestamps_overridden,
            None,
            None,
        )
        .await
    {
        error!("Failed to send Vercel logs to Kafka: {}", e);
        return Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error": "Internal server error"})),
        ));
    }
    counter!(RECORDS_COUNTER, "kind" => "valid").increment(row_count as u64);
    debug!("Successfully sent {} Vercel logs to Kafka", row_count);

    Ok(Json(json!({})))
}
