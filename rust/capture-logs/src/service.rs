use crate::log_record::KafkaLogRow;
use crate::metric_record::{flatten_metric, KafkaMetricRow};
use crate::trace_record::KafkaTraceRow;
use axum::{
    extract::Query,
    extract::State,
    http::{HeaderMap, StatusCode},
    response::Json,
};
use bytes::Bytes;
use common_compression::{decompress_gzip_capped, has_gzip_magic_header, CompressionError};
use limiters::token_dropper::TokenDropper;
use opentelemetry_proto::tonic::collector::logs::v1::ExportLogsServiceRequest;
use opentelemetry_proto::tonic::collector::metrics::v1::ExportMetricsServiceRequest;
use opentelemetry_proto::tonic::collector::trace::v1::ExportTraceServiceRequest;
use prost::Message;
use serde::Deserialize;
use serde_json::{json, Value};
use std::fs::File;
use std::io::Write;
use std::sync::Arc;

use crate::kafka::KafkaSink;

use tracing::{debug, error, instrument};

// `patch_otel_json` normalises an OTLP/JSON payload so it can be deserialized by
// upstream `opentelemetry-proto`'s generated types. This is a workaround layer
// for three known upstream gaps; each `FIXME` below is independently removable
// once its upstream issue lands. We string-match JSON keys to compensate for type
// system gaps in a third-party crate — it is not elegant. The function is bounded,
// idempotent, and side-effect-free, and the regression tests in tests/metrics_test.rs
// (the `#[ignore]`-d `edge_*_should_error` tests in particular) will surface upstream
// changes — un-ignore them when the silencing pattern is fixed.
//
// FIXME(upstream-1253): empty `value: {}` AnyValue objects fail to deserialize.
//   https://github.com/open-telemetry/opentelemetry-rust/issues/1253
//   Workaround: replace empty `value`/`body` objects with `null`.
//
// FIXME(upstream-3328): several fixed64/uint64/sfixed64 fields in the metrics
//   protos lack the `deserialize_string_to_u64` annotation, so the OTLP/JSON
//   spec-canonical string encoding fails. Combined with the silencing pattern
//   below, affected metrics end up with `data: None` instead of erroring.
//   https://github.com/open-telemetry/opentelemetry-rust/issues/3328
//   https://github.com/open-telemetry/opentelemetry-rust/pull/3329  (stale)
//   Workaround: coerce string-encoded integers to JSON numbers for the affected
//   fields (`count`, `zeroCount`, `asInt`, `bucketCounts[*]`, and timestamp
//   descendants under `exponentialHistogram` / `summary` / `exemplars`).
//
// FIXME(upstream-unreported): `ExponentialHistogram`, `ExponentialHistogramDataPoint`,
//   `SummaryDataPoint`, `Buckets`, and `Exemplar` all lack `#[serde(default)]`
//   upstream, so any missing non-Option proto field hard-errors and trips the
//   silencing pattern. No upstream issue filed yet — open one alongside removing
//   this workaround. Workaround: the `fill_*_defaults` functions inject defaults
//   for every required-by-serde field below.
//
// Silencing pattern (the reason these gaps silently drop metrics rather than
// returning a 400): `Metric` declares `data` as `#[serde(flatten)] Option<Data>`
// on a `#[serde(default)]` struct, so any error deserializing the inner oneof
// variant is swallowed and `data` becomes `None`. `flatten_metric` then emits
// zero rows with no log line. Until upstream changes the silencing structure
// itself, the only defense is to never let the inner deserialization fail.
pub fn patch_otel_json(v: &mut Value) {
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
            // Handle empty body objects - body should be an AnyValue or null
            if let Some(inner) = map.get_mut("body") {
                if inner.is_object() && inner.as_object().map(|obj| obj.is_empty()).unwrap_or(false)
                {
                    *inner = Value::Null;
                }
            }
            // Universal string→integer coercions for u64/i64 fields that have NO custom
            // deserializer in upstream opentelemetry-proto. Safe in any context.
            for key in ["count", "zeroCount", "asInt"] {
                if let Some(inner) = map.get_mut(key) {
                    coerce_string_to_integer(inner);
                }
            }
            if let Some(Value::Array(arr)) = map.get_mut("bucketCounts") {
                for el in arr.iter_mut() {
                    coerce_string_to_integer(el);
                }
            }
            // Context-aware fixes for the metric variants whose data point types lack both
            // the string→u64 deserializer and #[serde(default)] upstream. We coerce
            // timestamp strings to numbers AND inject defaults for every non-Option proto
            // field, since any missing field hard-errors and trips the silencing pattern.
            if let Some(inner) = map.get_mut("exponentialHistogram") {
                coerce_unix_nano_descendants(inner);
                fill_exponential_histogram_defaults(inner);
            }
            if let Some(inner) = map.get_mut("summary") {
                coerce_unix_nano_descendants(inner);
                fill_summary_defaults(inner);
            }
            // Exemplar also lacks #[serde(default)] upstream — missing fields silently drop
            // the parent metric, not just the exemplar. Fill defaults wherever we see one.
            if let Some(Value::Array(arr)) = map.get_mut("exemplars") {
                for el in arr.iter_mut() {
                    fill_exemplar_defaults(el);
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

fn coerce_string_to_integer(v: &mut Value) {
    let Value::String(s) = v else { return };
    if let Ok(n) = s.parse::<i64>() {
        *v = Value::Number(n.into());
    } else if let Ok(n) = s.parse::<u64>() {
        *v = Value::Number(n.into());
    }
}

fn number_u64(n: u64) -> Value {
    Value::Number(n.into())
}

fn number_zero_f64() -> Value {
    // serde_json::Number::from_f64 only fails for NaN/Infinity — never for 0.0.
    Value::Number(serde_json::Number::from_f64(0.0).expect("0.0 is finite"))
}

fn empty_string() -> Value {
    Value::String(String::new())
}

fn empty_array() -> Value {
    Value::Array(Vec::new())
}

fn fill_exponential_histogram_defaults(variant: &mut Value) {
    let Value::Object(map) = variant else { return };
    // ExponentialHistogram itself lacks #[serde(default)].
    map.entry("aggregationTemporality".to_string())
        .or_insert_with(|| number_u64(0));
    map.entry("dataPoints".to_string())
        .or_insert_with(empty_array);
    if let Some(Value::Array(arr)) = map.get_mut("dataPoints") {
        for dp in arr.iter_mut() {
            fill_exponential_histogram_dp_defaults(dp);
        }
    }
}

fn fill_exponential_histogram_dp_defaults(dp: &mut Value) {
    let Value::Object(obj) = dp else { return };
    obj.entry("attributes".to_string())
        .or_insert_with(empty_array);
    obj.entry("startTimeUnixNano".to_string())
        .or_insert_with(|| number_u64(0));
    obj.entry("timeUnixNano".to_string())
        .or_insert_with(|| number_u64(0));
    obj.entry("count".to_string())
        .or_insert_with(|| number_u64(0));
    obj.entry("scale".to_string())
        .or_insert_with(|| number_u64(0));
    obj.entry("zeroCount".to_string())
        .or_insert_with(|| number_u64(0));
    obj.entry("flags".to_string())
        .or_insert_with(|| number_u64(0));
    obj.entry("exemplars".to_string())
        .or_insert_with(empty_array);
    obj.entry("zeroThreshold".to_string())
        .or_insert_with(number_zero_f64);
    if let Some(buckets) = obj.get_mut("positive") {
        fill_buckets_defaults(buckets);
    }
    if let Some(buckets) = obj.get_mut("negative") {
        fill_buckets_defaults(buckets);
    }
}

fn fill_buckets_defaults(buckets: &mut Value) {
    let Value::Object(obj) = buckets else { return };
    obj.entry("offset".to_string())
        .or_insert_with(|| number_u64(0));
    obj.entry("bucketCounts".to_string())
        .or_insert_with(empty_array);
}

fn fill_summary_defaults(variant: &mut Value) {
    // Summary itself has #[serde(default)] upstream, so the variant-level fields
    // (dataPoints, aggregationTemporality if present) are tolerated when missing.
    // SummaryDataPoint is the level that needs help.
    let Value::Object(map) = variant else { return };
    if let Some(Value::Array(arr)) = map.get_mut("dataPoints") {
        for dp in arr.iter_mut() {
            fill_summary_dp_defaults(dp);
        }
    }
}

fn fill_summary_dp_defaults(dp: &mut Value) {
    let Value::Object(obj) = dp else { return };
    obj.entry("attributes".to_string())
        .or_insert_with(empty_array);
    obj.entry("startTimeUnixNano".to_string())
        .or_insert_with(|| number_u64(0));
    obj.entry("timeUnixNano".to_string())
        .or_insert_with(|| number_u64(0));
    obj.entry("count".to_string())
        .or_insert_with(|| number_u64(0));
    obj.entry("sum".to_string()).or_insert_with(number_zero_f64);
    obj.entry("quantileValues".to_string())
        .or_insert_with(empty_array);
    obj.entry("flags".to_string())
        .or_insert_with(|| number_u64(0));
}

fn fill_exemplar_defaults(exemplar: &mut Value) {
    let Value::Object(obj) = exemplar else { return };
    obj.entry("filteredAttributes".to_string())
        .or_insert_with(empty_array);
    obj.entry("timeUnixNano".to_string())
        .or_insert_with(|| number_u64(0));
    obj.entry("spanId".to_string()).or_insert_with(empty_string);
    obj.entry("traceId".to_string())
        .or_insert_with(empty_string);
    if let Some(t) = obj.get_mut("timeUnixNano") {
        coerce_string_to_integer(t);
    }
}

fn coerce_unix_nano_descendants(v: &mut Value) {
    match v {
        Value::Object(map) => {
            for key in ["timeUnixNano", "startTimeUnixNano"] {
                if let Some(inner) = map.get_mut(key) {
                    coerce_string_to_integer(inner);
                }
            }
            for (_, val) in map.iter_mut() {
                coerce_unix_nano_descendants(val);
            }
        }
        Value::Array(arr) => {
            for val in arr.iter_mut() {
                coerce_unix_nano_descendants(val);
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

    Ok(merged_request)
}

#[derive(Clone)]
pub struct Service {
    pub(crate) sink: KafkaSink,
    pub(crate) token_dropper: Arc<TokenDropper>,
    pub(crate) max_request_body_size_bytes: usize,
}

#[derive(Deserialize)]
pub struct QueryParams {
    token: Option<String>,
}

impl Service {
    pub async fn new(
        kafka_sink: KafkaSink,
        token_dropper: Arc<TokenDropper>,
        max_request_body_size_bytes: usize,
    ) -> Result<Self, anyhow::Error> {
        Ok(Self {
            sink: kafka_sink,
            token_dropper,
            max_request_body_size_bytes,
        })
    }
}

pub(crate) fn decode_body_if_gzip_magic(
    body: Bytes,
    max_request_body_size_bytes: usize,
) -> Result<Bytes, (StatusCode, Json<serde_json::Value>)> {
    if !has_gzip_magic_header(&body) {
        return Ok(body);
    }

    match decompress_gzip_capped(&body, max_request_body_size_bytes) {
        Ok(decompressed) => Ok(Bytes::from(decompressed)),
        Err(CompressionError::OutputTooLarge {
            decompressed,
            limit,
        }) => Err((
            StatusCode::PAYLOAD_TOO_LARGE,
            Json(json!({
                "error": format!("Decompressed request body exceeds limit ({decompressed} > {limit} bytes)")
            })),
        )),
        Err(e) => Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"error": format!("Failed to decompress gzip request body: {e}")})),
        )),
    }
}

/// Rejections counted by reason at the moment a request is refused — the edge is
/// the only stage that can see traffic which never reaches Kafka, so this is the
/// first stop for "my logs aren't showing up".
pub(crate) fn count_rejection(endpoint: &'static str, reason: &'static str) {
    metrics::counter!("capture_logs_rejections_total", "endpoint" => endpoint, "reason" => reason)
        .increment(1);
}

/// Records accepted and handed to Kafka, per endpoint — the wire-truth volume
/// before any downstream drop rules or quotas apply.
pub(crate) fn count_ingested_records(endpoint: &'static str, records: u64) {
    metrics::counter!("capture_logs_records_ingested_total", "endpoint" => endpoint)
        .increment(records);
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
    // The project token must be passed in as a Bearer token in the Authorization header
    if !headers.contains_key("Authorization") && query_params.token.is_none() {
        count_rejection("logs", "missing_token");
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
                count_rejection("logs", "missing_token");
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
                count_rejection("logs", "missing_token");
                error!("No token provided");
                return Err((
                    StatusCode::UNAUTHORIZED,
                    Json(json!({"error": format!("No token provided")})),
                ));
            }
        }
    };
    if service.token_dropper.should_drop(token, "") {
        count_rejection("logs", "token_dropped");
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error": format!("Invalid token")})),
        ));
    }

    tracing::Span::current().record("token", token);

    let body = decode_body_if_gzip_magic(body, service.max_request_body_size_bytes)
        .inspect_err(|_| count_rejection("logs", "decompress_failed"))?;

    // Try to decode as Protobuf, if this fails, try JSON.
    // We do this over relying on Content-Type headers to be as permissive as possible in what we accept.
    let export_request = match ExportLogsServiceRequest::decode(body.as_ref()) {
        Ok(request) => request,
        Err(proto_err) => match parse_otel_message(&body) {
            Ok(request) => request,
            Err(json_err) => {
                count_rejection("logs", "decode_failed");
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
    let mut timestamps_overridden: u64 = 0;
    for resource_logs in export_request.resource_logs {
        for scope_logs in resource_logs.scope_logs {
            for log_record in scope_logs.log_records {
                let (row, was_overridden) = match KafkaLogRow::new(
                    log_record,
                    resource_logs.resource.clone(),
                    scope_logs.scope.clone(),
                ) {
                    Ok(result) => result,
                    Err(e) => {
                        count_rejection("logs", "invalid_record");
                        error!("Failed to create LogRow: {e}");
                        return Err((
                            StatusCode::BAD_REQUEST,
                            Json(json!({"error": format!("Bad input format provided")})),
                        ));
                    }
                };
                if was_overridden {
                    timestamps_overridden += 1;
                }
                rows.push(row);
            }
        }
    }

    let row_count = rows.len();
    if let Err(e) = service
        .sink
        .write(token, rows, body.len() as u64, timestamps_overridden)
        .await
    {
        count_rejection("logs", "kafka_error");
        error!("Failed to send logs to Kafka: {}", e);
        return Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error": format!("Internal server error")})),
        ));
    } else {
        count_ingested_records("logs", row_count as u64);
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

/// Parse OpenTelemetry trace message from JSON bytes.
///
/// Supports both single JSON objects and JSONL format (JSON Lines).
/// For JSONL, multiple ExportTraceServiceRequest objects are parsed and merged
/// into a single request by combining their resource_spans arrays.
pub fn parse_otel_traces_message(
    json_bytes: &Bytes,
) -> Result<ExportTraceServiceRequest, anyhow::Error> {
    if let Ok(mut v) = serde_json::from_slice::<Value>(json_bytes) {
        patch_otel_json(&mut v);
        let result: ExportTraceServiceRequest = serde_json::from_value(v)?;
        return Ok(result);
    }

    let json_str = std::str::from_utf8(json_bytes)?;
    let lines: Vec<&str> = json_str
        .lines()
        .filter(|line| !line.trim().is_empty())
        .collect();

    let mut merged_request = ExportTraceServiceRequest {
        resource_spans: Vec::new(),
    };

    for line in lines {
        let mut v: Value = serde_json::from_str(line)?;
        patch_otel_json(&mut v);
        let request: ExportTraceServiceRequest = serde_json::from_value(v)?;
        merged_request.resource_spans.extend(request.resource_spans);
    }

    Ok(merged_request)
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
pub async fn export_traces_http(
    State(service): State<Service>,
    Query(query_params): Query<QueryParams>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    if !headers.contains_key("Authorization") && query_params.token.is_none() {
        count_rejection("traces", "missing_token");
        error!("No token provided");
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error": "No token provided"})),
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
                count_rejection("traces", "missing_token");
                error!("No token provided");
                return Err((
                    StatusCode::UNAUTHORIZED,
                    Json(json!({"error": "No token provided"})),
                ));
            }
        }
    } else {
        match query_params.token {
            Some(ref token) if !token.is_empty() => token,
            _ => {
                count_rejection("traces", "missing_token");
                error!("No token provided");
                return Err((
                    StatusCode::UNAUTHORIZED,
                    Json(json!({"error": "No token provided"})),
                ));
            }
        }
    };

    if service.token_dropper.should_drop(token, "") {
        count_rejection("traces", "token_dropped");
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error": "Invalid token"})),
        ));
    }

    tracing::Span::current().record("token", token);

    let body = decode_body_if_gzip_magic(body, service.max_request_body_size_bytes)
        .inspect_err(|_| count_rejection("traces", "decompress_failed"))?;

    let export_request = match ExportTraceServiceRequest::decode(body.as_ref()) {
        Ok(request) => request,
        Err(proto_err) => match parse_otel_traces_message(&body) {
            Ok(request) => request,
            Err(json_err) => {
                count_rejection("traces", "decode_failed");
                if let Err(e) =
                    File::create("/tmp/last_failed_trace_event.txt").and_then(|mut file| {
                        file.write_all(token.as_bytes())
                            .and_then(|_| file.write_all(&body))
                    })
                {
                    error!("Failed to write last failed trace event to file: {}", e);
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

    let mut rows: Vec<KafkaTraceRow> = Vec::new();
    let mut timestamps_overridden: u64 = 0;
    for resource_spans in export_request.resource_spans {
        for scope_spans in resource_spans.scope_spans {
            for span in scope_spans.spans {
                let (row, was_overridden) = match KafkaTraceRow::new(
                    span,
                    resource_spans.resource.clone(),
                    scope_spans.scope.clone(),
                ) {
                    Ok(result) => result,
                    Err(e) => {
                        count_rejection("traces", "invalid_record");
                        error!("Failed to create TraceRow: {e}");
                        return Err((
                            StatusCode::BAD_REQUEST,
                            Json(json!({"error": "Bad input format provided"})),
                        ));
                    }
                };
                if was_overridden {
                    timestamps_overridden += 1;
                }
                rows.push(row);
            }
        }
    }

    let row_count = rows.len();
    if let Err(e) = service
        .sink
        .write_traces(token, rows, body.len() as u64, timestamps_overridden)
        .await
    {
        count_rejection("traces", "kafka_error");
        error!("Failed to send traces to Kafka: {}", e);
        return Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error": "Internal server error"})),
        ));
    } else {
        count_ingested_records("traces", row_count as u64);
        debug!("Successfully sent {} traces to Kafka", row_count);
    }

    Ok(Json(json!({})))
}

/// Parse OpenTelemetry metric message from JSON bytes.
///
/// Supports both single JSON objects and JSONL format (JSON Lines).
/// For JSONL, multiple ExportMetricsServiceRequest objects are parsed and merged
/// into a single request by combining their resource_metrics arrays.
pub fn parse_otel_metrics_message(
    json_bytes: &Bytes,
) -> Result<ExportMetricsServiceRequest, anyhow::Error> {
    if let Ok(mut v) = serde_json::from_slice::<Value>(json_bytes) {
        patch_otel_json(&mut v);
        let result: ExportMetricsServiceRequest = serde_json::from_value(v)?;
        return Ok(result);
    }

    let json_str = std::str::from_utf8(json_bytes)?;
    let lines: Vec<&str> = json_str
        .lines()
        .filter(|line| !line.trim().is_empty())
        .collect();

    let mut merged_request = ExportMetricsServiceRequest {
        resource_metrics: Vec::new(),
    };

    for line in lines {
        let mut v: Value = serde_json::from_str(line)?;
        patch_otel_json(&mut v);
        let request: ExportMetricsServiceRequest = serde_json::from_value(v)?;
        merged_request
            .resource_metrics
            .extend(request.resource_metrics);
    }

    Ok(merged_request)
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
pub async fn export_metrics_http(
    State(service): State<Service>,
    Query(query_params): Query<QueryParams>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    if !headers.contains_key("Authorization") && query_params.token.is_none() {
        count_rejection("metrics", "missing_token");
        error!("No token provided");
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error": "No token provided"})),
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
                count_rejection("metrics", "missing_token");
                error!("No token provided");
                return Err((
                    StatusCode::UNAUTHORIZED,
                    Json(json!({"error": "No token provided"})),
                ));
            }
        }
    } else {
        match query_params.token {
            Some(ref token) if !token.is_empty() => token,
            _ => {
                count_rejection("metrics", "missing_token");
                error!("No token provided");
                return Err((
                    StatusCode::UNAUTHORIZED,
                    Json(json!({"error": "No token provided"})),
                ));
            }
        }
    };

    if service.token_dropper.should_drop(token, "") {
        count_rejection("metrics", "token_dropped");
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error": "Invalid token"})),
        ));
    }

    tracing::Span::current().record("token", token);

    let body = decode_body_if_gzip_magic(body, service.max_request_body_size_bytes)
        .inspect_err(|_| count_rejection("metrics", "decompress_failed"))?;

    let export_request = match ExportMetricsServiceRequest::decode(body.as_ref()) {
        Ok(request) => request,
        Err(proto_err) => match parse_otel_metrics_message(&body) {
            Ok(request) => request,
            Err(json_err) => {
                count_rejection("metrics", "decode_failed");
                if let Err(e) =
                    File::create("/tmp/last_failed_metric_event.txt").and_then(|mut file| {
                        file.write_all(token.as_bytes())
                            .and_then(|_| file.write_all(&body))
                    })
                {
                    error!("Failed to write last failed metric event to file: {}", e);
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

    let mut rows: Vec<KafkaMetricRow> = Vec::new();
    let mut timestamps_overridden: u64 = 0;

    for resource_metrics in &export_request.resource_metrics {
        for scope_metrics in &resource_metrics.scope_metrics {
            for metric in &scope_metrics.metrics {
                let (metric_rows, overridden) = match flatten_metric(
                    metric.clone(),
                    resource_metrics.resource.as_ref(),
                    scope_metrics.scope.as_ref(),
                ) {
                    Ok(result) => result,
                    Err(e) => {
                        count_rejection("metrics", "invalid_record");
                        error!("Failed to flatten metric: {e}");
                        return Err((
                            StatusCode::BAD_REQUEST,
                            Json(json!({"error": "Bad input format provided"})),
                        ));
                    }
                };
                timestamps_overridden += overridden;
                rows.extend(metric_rows);
            }
        }
    }

    let row_count = rows.len();
    if let Err(e) = service
        .sink
        .write_metrics(token, rows, body.len() as u64, timestamps_overridden)
        .await
    {
        count_rejection("metrics", "kafka_error");
        error!("Failed to send metrics to Kafka: {}", e);
        return Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error": "Internal server error"})),
        ));
    } else {
        count_ingested_records("metrics", row_count as u64);
        debug!(
            "Successfully sent {} metric data points to Kafka",
            row_count
        );
    }

    Ok(Json(json!({})))
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::{write::GzEncoder, Compression};

    fn gzip(data: &[u8]) -> Bytes {
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(data).unwrap();
        Bytes::from(encoder.finish().unwrap())
    }

    #[test]
    fn decode_body_if_gzip_magic_decompresses_without_header() {
        let body = gzip(br#"{"resourceLogs":[]}"#);

        let decoded = decode_body_if_gzip_magic(body, 1024).unwrap();

        assert_eq!(decoded, Bytes::from_static(br#"{"resourceLogs":[]}"#));
    }

    #[test]
    fn decode_body_if_gzip_magic_preserves_plain_body() {
        let body = Bytes::from_static(br#"{"resourceLogs":[]}"#);

        let decoded = decode_body_if_gzip_magic(body.clone(), 1024).unwrap();

        assert_eq!(decoded, body);
    }

    #[test]
    fn decode_body_if_gzip_magic_rejects_oversized_output() {
        let body = gzip(&vec![b'a'; 2048]);

        let err = decode_body_if_gzip_magic(body, 1024).unwrap_err();

        assert_eq!(err.0, StatusCode::PAYLOAD_TOO_LARGE);
    }
}

#[cfg(test)]
mod rejection_metrics_tests {
    use super::*;
    use crate::internal_metrics::InternalMetricsRecorder;
    use crate::kafka::KafkaSink;
    use std::collections::HashMap;

    async fn test_service(drop_tokens: &str) -> Service {
        Service {
            sink: KafkaSink::for_tests().await,
            token_dropper: Arc::new(TokenDropper::new(drop_tokens)),
            max_request_body_size_bytes: 2 * 1024 * 1024,
        }
    }

    fn drained(recorder: &InternalMetricsRecorder) -> HashMap<(String, String, String), f64> {
        recorder
            .drain_rows(&HashMap::new())
            .into_iter()
            .map(|row| {
                (
                    (
                        row.metric_name.clone(),
                        row.attributes.get("endpoint").cloned().unwrap_or_default(),
                        row.attributes.get("reason").cloned().unwrap_or_default(),
                    ),
                    row.value,
                )
            })
            .collect()
    }

    // The edge is the only stage that sees rejected traffic; if a rejection
    // branch stops counting (or mislabels its reason), "where did my logs go"
    // incidents lose their first diagnostic. Each case drives a real handler.
    #[test]
    fn rejection_branches_count_endpoint_and_reason() {
        let recorder = InternalMetricsRecorder::new();
        metrics::with_local_recorder(&recorder, || {
            let rt = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .unwrap();
            rt.block_on(async {
                let service = test_service("dropped-token").await;

                // missing token -> 401
                let res = export_logs_http(
                    State(service.clone()),
                    Query(QueryParams { token: None }),
                    HeaderMap::new(),
                    Bytes::new(),
                )
                .await;
                assert_eq!(res.unwrap_err().0, StatusCode::UNAUTHORIZED);

                // dropped token -> 401
                let mut headers = HeaderMap::new();
                headers.insert("Authorization", "Bearer dropped-token".parse().unwrap());
                let res = export_logs_http(
                    State(service.clone()),
                    Query(QueryParams { token: None }),
                    headers.clone(),
                    Bytes::new(),
                )
                .await;
                assert_eq!(res.unwrap_err().0, StatusCode::UNAUTHORIZED);

                // undecodable body with a valid token -> 400
                let mut ok_headers = HeaderMap::new();
                ok_headers.insert("Authorization", "Bearer good-token".parse().unwrap());
                let res = export_logs_http(
                    State(service.clone()),
                    Query(QueryParams { token: None }),
                    ok_headers.clone(),
                    Bytes::from_static(b"not otlp at all"),
                )
                .await;
                assert_eq!(res.unwrap_err().0, StatusCode::BAD_REQUEST);

                // same taxonomy fires per-endpoint: traces + metrics missing token
                let res = export_traces_http(
                    State(service.clone()),
                    Query(QueryParams { token: None }),
                    HeaderMap::new(),
                    Bytes::new(),
                )
                .await;
                assert_eq!(res.unwrap_err().0, StatusCode::UNAUTHORIZED);
                let res = export_metrics_http(
                    State(service.clone()),
                    Query(QueryParams { token: None }),
                    HeaderMap::new(),
                    Bytes::new(),
                )
                .await;
                assert_eq!(res.unwrap_err().0, StatusCode::UNAUTHORIZED);
            });
        });

        let counts = drained(&recorder);
        let rej = "capture_logs_rejections_total".to_string();
        assert_eq!(
            counts[&(rej.clone(), "logs".into(), "missing_token".into())],
            1.0
        );
        assert_eq!(
            counts[&(rej.clone(), "logs".into(), "token_dropped".into())],
            1.0
        );
        assert_eq!(
            counts[&(rej.clone(), "logs".into(), "decode_failed".into())],
            1.0
        );
        assert_eq!(
            counts[&(rej.clone(), "traces".into(), "missing_token".into())],
            1.0
        );
        assert_eq!(
            counts[&(rej, "metrics".into(), "missing_token".into())],
            1.0
        );
    }
}
