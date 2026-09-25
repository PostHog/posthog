//! Amazon Data Firehose HTTP endpoint destination for CloudWatch Logs:
//! https://docs.aws.amazon.com/firehose/latest/dev/httpdeliveryrequestresponse.html
//!
//! Every response, errors included, must be JSON with the request id, or Firehose treats it as a
//! 500 and retries with the same request id (only 413 is permanent), so delivery is at-least-once.
//! Records are decoded one at a time under a request-wide decoded-size budget, and rows are chunked
//! into Kafka messages sized against the producer's message cap, because one Firehose request can
//! decode to many megabytes.

use crate::authorizer::Signal;
use crate::log_record::{
    apply_timestamp_override, convert_severity_text_to_number, datetime_from_millis,
    severity_alias, try_extract_severity, KafkaLogRow,
};
use crate::service::{gunzip_if_magic, Service};
use axum::{
    extract::{Path, Request, State},
    http::{header::CONTENT_TYPE, HeaderMap, StatusCode},
    middleware::Next,
    response::{IntoResponse, Json, Response},
};
use bytes::Bytes;
use chrono::{DateTime, Utc};
use common_compression::decode_base64;
use metrics::counter;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use tokio::task::JoinSet;
use tracing::{debug, error, instrument, warn};
use uuid::Uuid;

const ACCESS_KEY_HEADER: &str = "x-amz-firehose-access-key";
const REQUEST_ID_HEADER: &str = "x-amz-firehose-request-id";
const SOURCE_ARN_HEADER: &str = "x-amz-firehose-source-arn";
const COMMON_ATTRIBUTES_HEADER: &str = "x-amz-firehose-common-attributes";

const RECORDS_COUNTER: &str = "capture_logs_firehose_records_total";
const EVENTS_COUNTER: &str = "capture_logs_firehose_events_total";

/// Decoded bytes one request may produce across all its records, as a multiple of the body cap.
/// CloudWatch envelopes gzip at roughly 5-15x, so 8x admits real traffic and bounds a deflate bomb.
const DECODED_BUDGET_FACTOR: usize = 8;

/// Fraction of the producer's message cap a batch of rows may fill before zstd; the Avro framing
/// plus attribute strings compress well enough that half is a safe budget.
const KAFKA_BATCH_BUDGET_DIVISOR: usize = 2;

type Rejection = (StatusCode, Json<Value>);

#[derive(Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct FirehoseRequest {
    pub request_id: String,
    #[serde(default)]
    pub records: Vec<FirehoseRecord>,
}

#[derive(Deserialize, Debug)]
pub struct FirehoseRecord {
    pub data: String,
}

/// The payload CloudWatch Logs writes for a subscription filter, after gunzip.
#[derive(Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct CloudWatchEnvelope {
    #[serde(default)]
    pub message_type: String,
    #[serde(default)]
    pub owner: String,
    #[serde(default)]
    pub log_group: String,
    #[serde(default)]
    pub log_stream: String,
    #[serde(default)]
    pub subscription_filters: Vec<String>,
    #[serde(default)]
    pub log_events: Vec<CloudWatchLogEvent>,
}

#[derive(Deserialize, Debug)]
pub struct CloudWatchLogEvent {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub timestamp: Option<i64>,
    #[serde(default)]
    pub message: String,
}

#[derive(Debug, Default)]
pub struct FirehoseContext {
    pub source_id: Option<String>,
    pub region: Option<String>,
    pub common_attributes: HashMap<String, Value>,
}

#[derive(Debug)]
pub enum DecodedRecord {
    CloudWatch(CloudWatchEnvelope),
    /// Not a CloudWatch envelope: VPC flow logs, WAF, or anything else put on the stream
    /// directly. Treated as newline-separated lines.
    Raw(String),
}

/// Rows from one record, each paired with whether its timestamp was clamped.
pub type DecodedRows = Vec<(KafkaLogRow, bool)>;

fn contract_body(request_id: &str, error_message: Option<&str>) -> Json<Value> {
    let mut body = json!({
        "requestId": request_id,
        "timestamp": Utc::now().timestamp_millis(),
    });
    if let Some(message) = error_message {
        body["errorMessage"] = json!(message);
    }
    Json(body)
}

fn rejection(status: StatusCode, request_id: &str, message: &str) -> Rejection {
    (status, contract_body(request_id, Some(message)))
}

/// Re-shape a `{"error": ...}` rejection from the shared helpers into the Firehose contract.
fn into_firehose_rejection((status, Json(body)): Rejection, request_id: &str) -> Rejection {
    let message = body
        .get("error")
        .and_then(Value::as_str)
        .unwrap_or("request rejected");
    rejection(status, request_id, message)
}

fn header_str<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    headers
        .get(name)
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|v| !v.is_empty())
}

/// Outermost layer on the Firehose router. The body-size limit and the decompression layer answer
/// with plain-text errors before the handler runs; Firehose needs the contract body on every
/// status, and 413 in particular is the one it treats as permanent.
pub async fn shape_layer_rejections(request: Request, next: Next) -> Response {
    let request_id = header_str(request.headers(), REQUEST_ID_HEADER)
        .unwrap_or("")
        .to_string();
    let response = next.run(request).await;
    let status = response.status();
    let is_json = response
        .headers()
        .get(CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .is_some_and(|v| v.starts_with("application/json"));
    if status.is_success() || is_json {
        return response;
    }
    let message = match status {
        StatusCode::PAYLOAD_TOO_LARGE => {
            "request body exceeds the size limit; lower the Firehose buffer size"
        }
        StatusCode::UNSUPPORTED_MEDIA_TYPE => "unsupported Content-Encoding; use GZIP or none",
        _ => "request rejected",
    };
    (status, contract_body(&request_id, Some(message))).into_response()
}

/// `arn:aws:firehose:us-east-1:123456789012:deliverystream/name` → `us-east-1`.
pub fn region_from_source_arn(arn: &str) -> Option<String> {
    arn.split(':')
        .nth(3)
        .filter(|region| !region.is_empty())
        .map(str::to_string)
}

/// `X-Amz-Firehose-Common-Attributes` is `{"commonAttributes": {"k": "v"}}`; a flat object is
/// also accepted.
pub fn parse_common_attributes(raw: Option<&str>) -> HashMap<String, Value> {
    let Some(raw) = raw else {
        return HashMap::new();
    };
    let Ok(mut value) = serde_json::from_str::<Value>(raw) else {
        warn!("Ignoring unparseable {COMMON_ATTRIBUTES_HEADER} header");
        return HashMap::new();
    };
    let object = match value.get_mut("commonAttributes") {
        Some(inner) => inner.take(),
        None => value,
    };
    match object {
        Value::Object(map) => map.into_iter().collect(),
        _ => HashMap::new(),
    }
}

/// The log group name is the best signal CloudWatch gives for which service wrote a line.
/// AWS-managed groups follow `/aws/<service>/<name>`; anything else is used as-is.
pub fn infer_service_name(log_group: &str) -> String {
    let parts: Vec<&str> = log_group.trim_matches('/').split('/').collect();
    let named = |idx: usize| {
        parts
            .get(idx)
            .filter(|s| !s.is_empty())
            .map(|s| s.to_string())
    };

    if parts.first() != Some(&"aws") {
        return log_group.to_string();
    }
    match parts.get(1).copied() {
        Some("lambda" | "eks" | "codebuild" | "apigateway" | "api-gateway" | "http-api") => {
            named(2)
        }
        Some("rds") => named(3),
        Some("ecs") if parts.get(2) == Some(&"containerinsights") => named(3),
        Some("ecs") => named(2),
        Some("vpc") => Some("vpc-flow-logs".to_string()),
        _ => None,
    }
    .unwrap_or_else(|| log_group.to_string())
}

/// A JSON body is checked for the usual level keys first; otherwise a leading `ERROR`, `[WARN]`
/// or `<timestamp> INFO` token is used, because CloudWatch lines carry no severity of their own.
pub fn infer_severity(message: &str) -> (String, i32) {
    let text = try_extract_severity(message).or_else(|| {
        // Look at the first three whitespace-separated tokens so a timestamp or request-id prefix
        // does not hide the level.
        message
            .split_whitespace()
            .take(3)
            .map(|token| token.trim_matches(|c: char| !c.is_ascii_alphabetic()))
            .find_map(severity_alias)
    });
    let text = text.unwrap_or("info");
    (text.to_string(), convert_severity_text_to_number(text))
}

/// Attribute values travel as JSON-encoded strings; this is the one place that encodes them.
fn put(map: &mut HashMap<String, String>, key: &str, value: impl Serialize) {
    if let Ok(encoded) = serde_json::to_string(&value) {
        map.insert(key.to_string(), encoded);
    }
}

/// Attributes shared by every row in one record, computed once instead of per event.
struct RowTemplate {
    service_name: String,
    resource_attributes: HashMap<String, String>,
    attributes: HashMap<String, String>,
}

impl FirehoseContext {
    fn template(&self, envelope: Option<&CloudWatchEnvelope>) -> RowTemplate {
        let mut resource_attributes = HashMap::new();
        for (key, value) in &self.common_attributes {
            put(&mut resource_attributes, key, value);
        }
        // A customer-set service.name wins over inference; the AWS facts below win over everything.
        let service_name = match self.common_attributes.get("service.name") {
            Some(Value::String(name)) if !name.is_empty() => name.clone(),
            _ => envelope
                .map(|env| infer_service_name(&env.log_group))
                .unwrap_or_else(|| "aws-firehose".to_string()),
        };
        put(&mut resource_attributes, "service.name", &service_name);
        put(&mut resource_attributes, "cloud.provider", "aws");
        if let Some(region) = &self.region {
            put(&mut resource_attributes, "cloud.region", region);
        }

        let mut attributes = HashMap::new();
        if let Some(source_id) = &self.source_id {
            put(&mut attributes, "posthog.source_id", source_id);
        }

        if let Some(env) = envelope {
            if !env.owner.is_empty() {
                put(&mut resource_attributes, "cloud.account.id", &env.owner);
            }
            put(
                &mut resource_attributes,
                "aws.log.group.name",
                &env.log_group,
            );
            put(
                &mut resource_attributes,
                "aws.log.stream.name",
                &env.log_stream,
            );
            if !env.subscription_filters.is_empty() {
                put(
                    &mut attributes,
                    "aws.subscription_filters",
                    env.subscription_filters.join(","),
                );
            }
        }

        RowTemplate {
            service_name,
            resource_attributes,
            attributes,
        }
    }
}

fn build_row(
    template: &RowTemplate,
    body: String,
    raw_timestamp: DateTime<Utc>,
    event_id: Option<&str>,
    now: DateTime<Utc>,
) -> (KafkaLogRow, bool) {
    let mut attributes = template.attributes.clone();
    if let Some(id) = event_id {
        put(&mut attributes, "aws.log.event.id", id);
    }
    let (timestamp, was_overridden) = apply_timestamp_override(raw_timestamp, &mut attributes);
    let (severity_text, severity_number) = infer_severity(&body);

    let row = KafkaLogRow {
        uuid: Uuid::now_v7().to_string(),
        trace_id: String::new(),
        span_id: String::new(),
        trace_flags: 0,
        timestamp,
        observed_timestamp: now,
        body,
        severity_text,
        severity_number,
        service_name: template.service_name.clone(),
        resource_attributes: template.resource_attributes.clone(),
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

pub fn cloudwatch_envelope_to_rows(
    envelope: CloudWatchEnvelope,
    ctx: &FirehoseContext,
) -> DecodedRows {
    let template = ctx.template(Some(&envelope));
    let now = Utc::now();
    envelope
        .log_events
        .into_iter()
        .map(
            |CloudWatchLogEvent {
                 id,
                 timestamp,
                 message,
             }| {
                let event_id = (!id.is_empty()).then_some(id.as_str());
                build_row(
                    &template,
                    message,
                    datetime_from_millis(timestamp),
                    event_id,
                    now,
                )
            },
        )
        .collect()
}

/// Lines from a record that is not a CloudWatch envelope. There is no per-line timestamp, so
/// every row gets the request's observed time.
pub fn raw_record_to_rows(text: &str, ctx: &FirehoseContext) -> DecodedRows {
    let template = ctx.template(None);
    let now = Utc::now();
    text.lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| build_row(&template, line.to_string(), now, None, now))
        .collect()
}

/// Base64-decode a Firehose record, gunzip it when CloudWatch compressed it, and classify it.
/// Returns the decoded byte count alongside, for the request-wide budget. The error carries the
/// status Firehose should see: 413 for an oversized record, else 400.
pub fn decode_record(
    data: &str,
    max_bytes: usize,
) -> Result<(DecodedRecord, usize), (StatusCode, String)> {
    let bytes = decode_base64(data.trim()).map_err(|e| {
        (
            StatusCode::BAD_REQUEST,
            format!("record is not valid base64: {e}"),
        )
    })?;
    let bytes = gunzip_if_magic(&bytes, max_bytes)?.unwrap_or(bytes);
    let decoded_len = bytes.len();

    if let Ok(envelope) = serde_json::from_slice::<CloudWatchEnvelope>(&bytes) {
        if !envelope.log_group.is_empty() || !envelope.log_events.is_empty() {
            return Ok((DecodedRecord::CloudWatch(envelope), decoded_len));
        }
    }

    String::from_utf8(bytes)
        .map(|text| (DecodedRecord::Raw(text), decoded_len))
        .map_err(|_| {
            (
                StatusCode::BAD_REQUEST,
                "record is neither a CloudWatch envelope nor UTF-8 text".to_string(),
            )
        })
}

fn decoded_record_to_rows(decoded: DecodedRecord, ctx: &FirehoseContext) -> Option<DecodedRows> {
    match decoded {
        DecodedRecord::CloudWatch(envelope) if envelope.message_type == "CONTROL_MESSAGE" => {
            counter!(RECORDS_COUNTER, "kind" => "control").increment(1);
            None
        }
        DecodedRecord::CloudWatch(envelope) => {
            counter!(RECORDS_COUNTER, "kind" => "data").increment(1);
            Some(cloudwatch_envelope_to_rows(envelope, ctx))
        }
        DecodedRecord::Raw(text) => {
            counter!(RECORDS_COUNTER, "kind" => "raw").increment(1);
            Some(raw_record_to_rows(&text, ctx))
        }
    }
}

/// Accumulates rows into Kafka batches of at most `budget` bytes (by each row's own byte count),
/// so no batch exceeds the producer cap and a single oversized record is split rather than failed.
pub struct BatchBuilder {
    budget: u64,
    rows: Vec<KafkaLogRow>,
    bytes: u64,
    timestamps_overridden: u64,
}

pub struct Batch {
    pub rows: Vec<KafkaLogRow>,
    pub bytes: u64,
    pub timestamps_overridden: u64,
}

impl BatchBuilder {
    pub fn new(budget: u64) -> Self {
        Self {
            budget,
            rows: Vec::new(),
            bytes: 0,
            timestamps_overridden: 0,
        }
    }

    /// Add a row; returns a full batch to produce when this row did not fit alongside the pending
    /// ones. A single row larger than the budget still goes out on its own.
    pub fn push(&mut self, row: KafkaLogRow, overridden: bool) -> Option<Batch> {
        let row_bytes = row.byte_count();
        let full = if !self.rows.is_empty() && self.bytes + row_bytes > self.budget {
            self.take()
        } else {
            None
        };
        self.rows.push(row);
        self.bytes += row_bytes;
        self.timestamps_overridden += u64::from(overridden);
        full
    }

    pub fn finish(mut self) -> Option<Batch> {
        self.take()
    }

    fn take(&mut self) -> Option<Batch> {
        if self.rows.is_empty() {
            return None;
        }
        Some(Batch {
            rows: std::mem::take(&mut self.rows),
            bytes: std::mem::take(&mut self.bytes),
            timestamps_overridden: std::mem::take(&mut self.timestamps_overridden),
        })
    }
}

fn spawn_write(
    writes: &mut JoinSet<anyhow::Result<()>>,
    service: &Service,
    token: &str,
    ctx: &FirehoseContext,
    batch: Batch,
) {
    let sink = service.sink.clone();
    let token = token.to_string();
    let source_id = ctx.source_id.clone();
    writes.spawn(async move {
        sink.write(
            &token,
            batch.rows,
            batch.bytes,
            batch.timestamps_overridden,
            source_id.as_deref(),
        )
        .await
    });
}

#[instrument(skip_all, fields(
    token = tracing::field::Empty,
    source_id = tracing::field::Empty,
    firehose_request_id = %header_str(&headers, REQUEST_ID_HEADER).unwrap_or(""),
    content_length = %header_str(&headers, "content-length").unwrap_or(""),
    content_encoding = %header_str(&headers, "content-encoding").unwrap_or("")))
]
pub async fn export_aws_firehose_logs_http(
    State(service): State<Service>,
    path_source_id: Option<Path<String>>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<Value>, Rejection> {
    // The header is the only request id available before the body is parsed, and Firehose keeps
    // it stable across retries, so it is what every early rejection echoes.
    let header_request_id = header_str(&headers, REQUEST_ID_HEADER)
        .unwrap_or("")
        .to_string();

    let token = service
        .authorizer
        .authorize_from_header_or_bearer(&headers, ACCESS_KEY_HEADER, Signal::Logs)
        .map_err(|rej| into_firehose_rejection(rej, &header_request_id))?
        .to_string();
    tracing::Span::current().record("token", token.as_str());

    let source_id = match path_source_id {
        Some(Path(raw)) if !raw.is_empty() => Some(
            Uuid::parse_str(&raw)
                .map_err(|_| {
                    rejection(
                        StatusCode::BAD_REQUEST,
                        &header_request_id,
                        "source id in the URL path is not a UUID",
                    )
                })?
                .to_string(),
        ),
        _ => None,
    };
    if let Some(id) = &source_id {
        tracing::Span::current().record("source_id", id.as_str());
    }

    let body_cap = service.firehose_max_request_body_size_bytes;
    let body = match gunzip_if_magic(&body, body_cap) {
        Ok(None) => body,
        Ok(Some(decompressed)) => Bytes::from(decompressed),
        Err((status, message)) => return Err(rejection(status, &header_request_id, &message)),
    };

    let request: FirehoseRequest = serde_json::from_slice(&body).map_err(|e| {
        error!("Failed to parse Firehose request: {e}");
        rejection(
            StatusCode::BAD_REQUEST,
            &header_request_id,
            &format!("body is not a Firehose HTTP endpoint request: {e}"),
        )
    })?;
    let request_id = if request.request_id.is_empty() {
        header_request_id
    } else {
        request.request_id.clone()
    };
    drop(body);

    let ctx = FirehoseContext {
        source_id,
        region: header_str(&headers, SOURCE_ARN_HEADER).and_then(region_from_source_arn),
        common_attributes: parse_common_attributes(header_str(&headers, COMMON_ATTRIBUTES_HEADER)),
    };

    let decoded_budget = body_cap.saturating_mul(DECODED_BUDGET_FACTOR);
    let mut decoded_total: usize = 0;
    let mut invalid_records: usize = 0;
    let mut total_events: u64 = 0;
    let mut batches = BatchBuilder::new(
        (service.sink.logs_message_max_bytes() / KAFKA_BATCH_BUDGET_DIVISOR) as u64,
    );
    let mut writes: JoinSet<anyhow::Result<()>> = JoinSet::new();
    let record_count = request.records.len();

    for (index, record) in request.records.into_iter().enumerate() {
        let (decoded, decoded_len) = match decode_record(&record.data, body_cap) {
            Ok(decoded) => decoded,
            Err((StatusCode::PAYLOAD_TOO_LARGE, message)) => {
                writes.abort_all();
                return Err(rejection(
                    StatusCode::PAYLOAD_TOO_LARGE,
                    &request_id,
                    &format!("record {index}: {message}"),
                ));
            }
            Err((_, message)) => {
                // A record that can never decode would otherwise make Firehose retry the whole
                // request for its retry window, taking the good records down with it.
                counter!(RECORDS_COUNTER, "kind" => "invalid").increment(1);
                warn!("Skipping undecodable Firehose record {index}: {message}");
                invalid_records += 1;
                continue;
            }
        };
        decoded_total += decoded_len;
        if decoded_total > decoded_budget {
            writes.abort_all();
            return Err(rejection(
                StatusCode::PAYLOAD_TOO_LARGE,
                &request_id,
                &format!(
                    "decoded records exceed {decoded_budget} bytes; lower the Firehose buffer size"
                ),
            ));
        }

        let Some(decoded_rows) = decoded_record_to_rows(decoded, &ctx) else {
            continue;
        };
        total_events += decoded_rows.len() as u64;
        for (row, overridden) in decoded_rows {
            if let Some(batch) = batches.push(row, overridden) {
                spawn_write(&mut writes, &service, &token, &ctx, batch);
            }
        }
    }
    if let Some(batch) = batches.finish() {
        spawn_write(&mut writes, &service, &token, &ctx, batch);
    }

    if invalid_records > 0 && invalid_records == record_count {
        return Err(rejection(
            StatusCode::BAD_REQUEST,
            &request_id,
            "no record could be decoded as a CloudWatch envelope or text",
        ));
    }

    while let Some(joined) = writes.join_next().await {
        let failed = match joined {
            Ok(Ok(())) => None,
            Ok(Err(e)) => Some(e.to_string()),
            Err(e) => Some(e.to_string()),
        };
        if let Some(e) = failed {
            writes.abort_all();
            error!("Failed to send Firehose batch to Kafka: {e}");
            return Err(rejection(
                StatusCode::INTERNAL_SERVER_ERROR,
                &request_id,
                "Internal server error",
            ));
        }
    }

    counter!(EVENTS_COUNTER).increment(total_events);
    debug!(
        "Accepted Firehose request with {} records ({} invalid) and {} log events",
        record_count, invalid_records, total_events
    );
    Ok(contract_body(&request_id, None))
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use common_compression::{compress_gzip, encode_base64};

    fn gzip_b64(data: &[u8]) -> String {
        encode_base64(&compress_gzip(data).unwrap())
    }

    fn envelope_json(message_type: &str) -> String {
        json!({
            "messageType": message_type,
            "owner": "123456789012",
            "logGroup": "/aws/lambda/checkout-api",
            "logStream": "2026/09/16/[$LATEST]abc",
            "subscriptionFilters": ["posthog"],
            "logEvents": [
                {"id": "1", "timestamp": Utc::now().timestamp_millis(), "message": "ERROR payment declined"},
                {"id": "2", "timestamp": Utc::now().timestamp_millis(), "message": "{\"level\":\"warning\",\"msg\":\"slow\"}"}
            ]
        })
        .to_string()
    }

    fn envelope() -> CloudWatchEnvelope {
        serde_json::from_str(&envelope_json("DATA_MESSAGE")).unwrap()
    }

    fn context() -> FirehoseContext {
        FirehoseContext {
            source_id: Some("6f1a2b3c-0000-4000-8000-000000000001".to_string()),
            region: Some("us-east-1".to_string()),
            common_attributes: HashMap::from([("env".to_string(), json!("prod"))]),
        }
    }

    #[test]
    fn decode_record_reads_cloudwatch_envelopes_gzipped_or_plain() {
        let json = envelope_json("DATA_MESSAGE");
        for data in [gzip_b64(json.as_bytes()), encode_base64(json.as_bytes())] {
            let (decoded, len) = decode_record(&data, 1 << 20).unwrap();
            assert_eq!(len, json.len());
            match decoded {
                DecodedRecord::CloudWatch(env) => {
                    assert_eq!(env.log_group, "/aws/lambda/checkout-api");
                    assert_eq!(env.log_events.len(), 2);
                }
                DecodedRecord::Raw(_) => panic!("expected a CloudWatch envelope"),
            }
        }
    }

    #[test]
    fn decode_record_falls_back_to_raw_lines() {
        let data = encode_base64(b"2 123 eni-1 10.0.0.1 10.0.0.2 ACCEPT OK\nline two\n");
        match decode_record(&data, 1 << 20).unwrap().0 {
            DecodedRecord::Raw(text) => assert!(text.starts_with("2 123")),
            DecodedRecord::CloudWatch(_) => panic!("expected raw"),
        }
    }

    #[test]
    fn decode_record_maps_failures_to_firehose_statuses() {
        let big = vec![b'a'; 4096];
        assert_eq!(
            decode_record(&gzip_b64(&big), 1024).unwrap_err().0,
            StatusCode::PAYLOAD_TOO_LARGE
        );
        assert_eq!(
            decode_record("not base64!!", 1024).unwrap_err().0,
            StatusCode::BAD_REQUEST
        );
    }

    #[test]
    fn service_name_inference_table() {
        let cases = [
            ("/aws/lambda/checkout-api", "checkout-api"),
            ("/aws/rds/instance/prod-db/postgresql", "prod-db"),
            ("/aws/rds/cluster/prod-cluster/error", "prod-cluster"),
            (
                "/aws/ecs/containerinsights/web-cluster/performance",
                "web-cluster",
            ),
            ("/aws/ecs/web-cluster", "web-cluster"),
            ("/aws/eks/main/cluster", "main"),
            ("/aws/apigateway/abc123", "abc123"),
            ("/aws/codebuild/frontend", "frontend"),
            ("/aws/vpc/flowlogs", "vpc-flow-logs"),
            ("/aws/unknown", "/aws/unknown"),
            ("/aws/lambda/", "/aws/lambda/"),
            ("my-app-logs", "my-app-logs"),
        ];
        for (group, expected) in cases {
            assert_eq!(infer_service_name(group), expected, "{group}");
        }
    }

    #[test]
    fn severity_inference_table() {
        let cases = [
            ("ERROR payment declined", "error", 17),
            ("[WARN] slow query", "warn", 13),
            ("2026-09-16T10:00:00Z INFO started", "info", 9),
            ("abc-123 DEBUG cache miss", "debug", 5),
            ("FATAL: out of memory", "fatal", 21),
            ("CRIT disk full", "fatal", 21),
            ("{\"level\":\"warn\",\"msg\":\"x\"}", "warn", 13),
            ("{\"level\":\"warning\",\"msg\":\"x\"}", "warn", 13),
            ("{\"severity\":\"CRITICAL\"}", "fatal", 21),
            ("plain line with error later in it", "info", 9),
            ("Errors: 0", "info", 9),
            ("", "info", 9),
        ];
        for (message, text, number) in cases {
            assert_eq!(
                infer_severity(message),
                (text.to_string(), number),
                "{message}"
            );
        }
    }

    #[test]
    fn region_is_parsed_from_source_arn() {
        assert_eq!(
            region_from_source_arn("arn:aws:firehose:eu-central-1:123456789012:deliverystream/x"),
            Some("eu-central-1".to_string())
        );
        assert_eq!(region_from_source_arn("garbage"), None);
    }

    #[test]
    fn common_attributes_keep_json_types_and_accept_both_shapes() {
        let wrapped = parse_common_attributes(Some(
            r#"{"commonAttributes":{"env":"prod","team":"payments"}}"#,
        ));
        assert_eq!(wrapped["env"], json!("prod"));
        let flat = parse_common_attributes(Some(r#"{"env":"staging","count":3}"#));
        assert_eq!(flat["count"], json!(3));
        assert!(parse_common_attributes(Some("not json")).is_empty());
        assert!(parse_common_attributes(None).is_empty());

        let ctx = FirehoseContext {
            common_attributes: flat,
            ..FirehoseContext::default()
        };
        let template = ctx.template(None);
        assert_eq!(template.resource_attributes["count"], "3");
        assert_eq!(template.resource_attributes["env"], "\"staging\"");
    }

    #[test]
    fn cloudwatch_envelope_maps_to_rows_with_aws_attributes() {
        let mut env = envelope();
        env.log_events.push(CloudWatchLogEvent {
            id: String::new(),
            timestamp: Some(Utc::now().timestamp_millis() - 72 * 3600 * 1000),
            message: "old".to_string(),
        });

        let decoded = cloudwatch_envelope_to_rows(env, &context());

        assert_eq!(decoded.len(), 3);
        assert_eq!(decoded.iter().filter(|(_, clamped)| *clamped).count(), 1);
        let row = &decoded[0].0;
        assert_eq!(row.body, "ERROR payment declined");
        assert_eq!(row.service_name, "checkout-api");
        assert_eq!(row.severity_text, "error");
        assert_eq!(row.severity_number, 17);
        assert_eq!(row.resource_attributes["cloud.provider"], "\"aws\"");
        assert_eq!(
            row.resource_attributes["cloud.account.id"],
            "\"123456789012\""
        );
        assert_eq!(row.resource_attributes["cloud.region"], "\"us-east-1\"");
        assert_eq!(
            row.resource_attributes["aws.log.group.name"],
            "\"/aws/lambda/checkout-api\""
        );
        assert_eq!(row.resource_attributes["service.name"], "\"checkout-api\"");
        assert_eq!(row.resource_attributes["env"], "\"prod\"");
        assert_eq!(row.attributes["aws.log.event.id"], "\"1\"");
        assert_eq!(row.attributes["aws.subscription_filters"], "\"posthog\"");
        assert_eq!(
            row.attributes["posthog.source_id"],
            "\"6f1a2b3c-0000-4000-8000-000000000001\""
        );
        assert!(row.bytes_uncompressed.is_some());
        assert_eq!(decoded[1].0.severity_text, "warn");
        let old = &decoded[2].0;
        assert!(old.attributes.contains_key("$originalTimestamp"));
        assert!(!old.attributes.contains_key("aws.log.event.id"));
    }

    #[test]
    fn a_common_attribute_service_name_wins_for_column_and_attribute() {
        let ctx = FirehoseContext {
            common_attributes: HashMap::from([("service.name".to_string(), json!("payments"))]),
            ..FirehoseContext::default()
        };
        let decoded = cloudwatch_envelope_to_rows(envelope(), &ctx);
        assert_eq!(decoded[0].0.service_name, "payments");
        assert_eq!(
            decoded[0].0.resource_attributes["service.name"],
            "\"payments\""
        );
        // AWS facts are never overridden by common attributes.
        let ctx = FirehoseContext {
            common_attributes: HashMap::from([(
                "aws.log.group.name".to_string(),
                json!("spoofed"),
            )]),
            ..FirehoseContext::default()
        };
        let decoded = cloudwatch_envelope_to_rows(envelope(), &ctx);
        assert_eq!(
            decoded[0].0.resource_attributes["aws.log.group.name"],
            "\"/aws/lambda/checkout-api\""
        );
    }

    #[test]
    fn raw_record_yields_one_row_per_non_empty_line() {
        let decoded = raw_record_to_rows("a\n\nb\n", &FirehoseContext::default());
        assert_eq!(decoded.len(), 2);
        assert_eq!(decoded[0].0.service_name, "aws-firehose");
        assert!(!decoded[0].0.attributes.contains_key("posthog.source_id"));
    }

    #[test]
    fn batch_builder_splits_by_row_bytes_and_never_drops_rows() {
        let one_row = || {
            raw_record_to_rows(&"x".repeat(50), &FirehoseContext::default())
                .remove(0)
                .0
        };
        let row_bytes = one_row().bytes_uncompressed.unwrap() as u64;
        let mut builder = BatchBuilder::new(row_bytes * 3);
        let mut batches = Vec::new();
        for _ in 0..7 {
            if let Some(batch) = builder.push(one_row(), false) {
                batches.push(batch);
            }
        }
        batches.extend(builder.finish());
        let sizes: Vec<usize> = batches.iter().map(|b| b.rows.len()).collect();
        assert_eq!(sizes, vec![3, 3, 1]);
        assert!(batches.iter().all(|b| b.bytes <= row_bytes * 3));

        // One row above the budget still goes out alone rather than being dropped.
        let mut small = BatchBuilder::new(1);
        assert!(small.push(one_row(), false).is_none());
        assert_eq!(small.finish().unwrap().rows.len(), 1);
    }

    #[test]
    fn contract_bodies_carry_request_id_and_timestamp() {
        let (status, Json(body)) = rejection(StatusCode::UNAUTHORIZED, "req-1", "nope");
        assert_eq!(status, StatusCode::UNAUTHORIZED);
        assert_eq!(body["requestId"], "req-1");
        assert!(body["timestamp"].is_i64());
        assert_eq!(body["errorMessage"], "nope");

        let converted = into_firehose_rejection(
            (
                StatusCode::PAYLOAD_TOO_LARGE,
                Json(json!({"error": "too big"})),
            ),
            "req-2",
        );
        assert_eq!(converted.0, StatusCode::PAYLOAD_TOO_LARGE);
        assert_eq!(converted.1 .0["errorMessage"], "too big");

        let Json(ok) = contract_body("req-3", None);
        assert_eq!(ok["requestId"], "req-3");
        assert!(ok.get("errorMessage").is_none());
    }

    #[tokio::test]
    async fn layer_rejections_are_reshaped_into_the_contract() {
        use axum::{routing::post, Router};
        use tower::ServiceExt;

        async fn too_large() -> Response {
            (StatusCode::PAYLOAD_TOO_LARGE, "length limit exceeded").into_response()
        }
        let app = Router::new()
            .route("/", post(too_large))
            .layer(axum::middleware::from_fn(shape_layer_rejections));
        let request = Request::builder()
            .method("POST")
            .uri("/")
            .header(REQUEST_ID_HEADER, "req-9")
            .body(Body::empty())
            .unwrap();

        let response = app.oneshot(request).await.unwrap();

        assert_eq!(response.status(), StatusCode::PAYLOAD_TOO_LARGE);
        let bytes = axum::body::to_bytes(response.into_body(), 4096)
            .await
            .unwrap();
        let body: Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(body["requestId"], "req-9");
        assert!(body["errorMessage"]
            .as_str()
            .unwrap()
            .contains("buffer size"));
    }

    #[test]
    fn firehose_request_defaults_records_to_empty() {
        let request: FirehoseRequest = serde_json::from_str(r#"{"requestId":"abc"}"#).unwrap();
        assert_eq!(request.request_id, "abc");
        assert!(request.records.is_empty());
    }
}
