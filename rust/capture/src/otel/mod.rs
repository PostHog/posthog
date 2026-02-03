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
    debug!("Received request to /i/v0/llma_otel endpoint");

    let body_limit = 4 * 1024 * 1024; // 4MB
    let body = extract_body_with_timeout(
        body,
        body_limit,
        state.body_chunk_read_timeout,
        state.body_read_chunk_size_kb,
        "/i/v0/llma_otel",
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

    let request = ingestion::parse_request(&body, &headers)?;

    let span_count = count_spans(&request);
    counter!("capture_otel_llma_spans_received").increment(span_count as u64);

    let received_at = Utc::now();
    let distinct_id = identity::extract_distinct_id(&request);

    let client_ip = ip
        .map(|InsecureClientIp(addr)| addr.to_string())
        .unwrap_or_else(|| "127.0.0.1".to_string());

    let span_events = fan_out::expand_into_events(&request, &distinct_id);

    let processed_events: Vec<ProcessedEvent> = span_events
        .into_iter()
        .map(|span_event| {
            let event_data = json!({
                "event": &span_event.event_name,
                "distinct_id": &span_event.distinct_id,
                "properties": span_event.properties,
            });

            let data = serde_json::to_string(&event_data).expect("SpanEvent is serializable");

            let event_uuid = Uuid::now_v7();
            let captured_event = CapturedEvent {
                uuid: event_uuid,
                distinct_id: span_event.distinct_id,
                session_id: None,
                ip: client_ip.clone(),
                data,
                now: received_at.to_rfc3339(),
                sent_at: None,
                token: token.to_string(),
                event: span_event.event_name.clone(),
                timestamp: span_event.timestamp.unwrap_or(received_at),
                is_cookieless_mode: false,
                historical_migration: false,
            };

            let metadata = ProcessedEventMetadata {
                data_type: DataType::AnalyticsMain,
                session_id: None,
                computed_timestamp: Some(span_event.timestamp.unwrap_or(received_at)),
                event_name: span_event.event_name,
                force_overflow: false,
                skip_person_processing: false,
                redirect_to_dlq: false,
            };

            ProcessedEvent {
                event: captured_event,
                metadata,
            }
        })
        .collect();

    state
        .sink
        .send_batch(processed_events)
        .await
        .map_err(|e| {
            warn!("Failed to send OTel events to Kafka: {:?}", e);
            e
        })?;

    counter!("capture_otel_llma_requests_success").increment(1);

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
