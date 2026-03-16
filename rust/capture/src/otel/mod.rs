mod event_name;
mod fan_out;
mod identity;
mod ingestion;

use axum::body::Body;
use axum::extract::State;
use axum::http::HeaderMap;
use axum::response::Json;
use axum_client_ip::InsecureClientIp;
use chrono::Utc;
use common_types::CapturedEvent;
use metrics::counter;
use opentelemetry_proto::tonic::collector::trace::v1::ExportTraceServiceRequest;
use serde_json::json;
use tracing::{debug, warn};
use uuid::Uuid;

use crate::api::{CaptureError, CaptureResponse, CaptureResponseCode};
use crate::extractors::extract_body_with_timeout;
use crate::prometheus::report_dropped_events;
use crate::router::State as AppState;
use crate::token::validate_token;
use crate::v0_request::{DataType, ProcessedEvent, ProcessedEventMetadata};

pub const OTEL_BODY_SIZE: usize = 4 * 1024 * 1024; // 4MB
const MAX_SPANS_PER_REQUEST: usize = 100;

fn count_spans(request: &ExportTraceServiceRequest) -> usize {
    request
        .resource_spans
        .iter()
        .flat_map(|rs| &rs.scope_spans)
        .map(|ss| ss.spans.len())
        .sum()
}

pub async fn otel_handler(
    State(state): State<AppState>,
    ip: Option<InsecureClientIp>,
    headers: HeaderMap,
    body: Body,
) -> Result<Json<serde_json::Value>, CaptureError> {
    debug!("Received request to /i/v0/ai/otel endpoint");

    let body = extract_body_with_timeout(
        body,
        OTEL_BODY_SIZE,
        state.body_chunk_read_timeout,
        state.body_read_chunk_size_kb,
        "/i/v0/ai/otel",
    )
    .await?;

    if body.is_empty() {
        warn!("OTEL endpoint received empty body");
        return Err(CaptureError::EmptyPayload);
    }

    let auth_header = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    if !auth_header.starts_with("Bearer ") {
        warn!("OTEL endpoint missing or invalid Authorization header");
        return Err(CaptureError::NoTokenError);
    }

    let token = &auth_header[7..]; // Remove "Bearer " prefix
    validate_token(token)?;

    if state.token_dropper.should_drop(token, "") {
        report_dropped_events("token_dropper", 1);
        return Ok(Json(json!({})));
    }

    // TODO: Add quota limiter check (needs HasEventName impl for OTel events)
    // TODO: Add event restriction checks

    let request = ingestion::parse_request(&body, &headers, OTEL_BODY_SIZE)?;

    let span_count = count_spans(&request);
    if span_count == 0 {
        return Ok(Json(json!({})));
    }
    if span_count > MAX_SPANS_PER_REQUEST {
        warn!(
            "OTEL request contains {} spans, exceeding limit of {}",
            span_count, MAX_SPANS_PER_REQUEST
        );
        return Err(CaptureError::RequestParsingError(format!(
            "Too many spans: {span_count} exceeds limit of {MAX_SPANS_PER_REQUEST}"
        )));
    }
    counter!("capture_ai_otel_spans_received").increment(span_count as u64);

    let received_at = Utc::now();
    let distinct_id = identity::extract_distinct_id(&request);

    let client_ip = ip
        .map(|InsecureClientIp(addr)| addr.to_string())
        .unwrap_or_else(|| "127.0.0.1".to_string());

    let span_events = fan_out::expand_into_events(&request, &distinct_id);
    let now_rfc3339 = received_at.to_rfc3339();
    let token = token.to_string();

    let mut processed_events = Vec::with_capacity(span_events.len());
    for span_event in span_events {
        let event_data = json!({
            "event": &span_event.event_name,
            "distinct_id": &span_event.distinct_id,
            "properties": span_event.properties,
        });

        let data = serde_json::to_string(&event_data).map_err(|e| {
            warn!("Failed to serialize OTel event data: {}", e);
            CaptureError::InternalError(format!("failed to serialize event data: {e}"))
        })?;

        let timestamp = span_event.timestamp.unwrap_or(received_at);
        let captured_event = CapturedEvent {
            uuid: Uuid::now_v7(),
            distinct_id: span_event.distinct_id,
            session_id: None,
            ip: client_ip.clone(),
            data,
            now: now_rfc3339.clone(),
            sent_at: None,
            token: token.clone(),
            event: span_event.event_name.clone(),
            timestamp,
            is_cookieless_mode: false,
            historical_migration: false,
        };

        let metadata = ProcessedEventMetadata {
            data_type: DataType::AnalyticsMain,
            session_id: None,
            computed_timestamp: Some(timestamp),
            event_name: span_event.event_name,
            force_overflow: false,
            skip_person_processing: false,
            redirect_to_dlq: false,
            redirect_to_topic: None,
        };

        processed_events.push(ProcessedEvent {
            event: captured_event,
            metadata,
        });
    }

    state.sink.send_batch(processed_events).await.map_err(|e| {
        warn!("Failed to send OTel events to Kafka: {:?}", e);
        e
    })?;

    counter!("capture_ai_otel_requests_success").increment(1);

    debug!(
        "OTEL endpoint request processed successfully: {} spans",
        span_count
    );

    // Return empty JSON object per OTLP spec
    Ok(Json(json!({})))
}

pub async fn options() -> Result<CaptureResponse, CaptureError> {
    Ok(CaptureResponse {
        status: CaptureResponseCode::Ok,
        quota_limited: None,
    })
}
