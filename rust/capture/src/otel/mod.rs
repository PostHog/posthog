mod event_name;
mod fan_out;
mod filtering;
mod identity;
mod ingestion;

use axum::body::Body;
use axum::extract::State;
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Json, Response};
use axum_client_ip::InsecureClientIp;
use chrono::Utc;
use metrics::{counter, histogram};
use opentelemetry_proto::tonic::collector::trace::v1::ExportTraceServiceRequest;
use serde_json::json;
use tracing::{debug, instrument, warn, Span};

use crate::api::{CaptureError, CaptureResponse, CaptureResponseCode};
use crate::extractors::extract_body_with_timeout;
use crate::prometheus::{report_dropped_events, report_internal_error_metrics};
use crate::router::State as AppState;
use crate::token::validate_token;

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

/// Return an HTTP 400 with a JSON error message.
///
/// Per the OTLP spec (https://opentelemetry.io/docs/specs/otlp/#failures-1), only
/// 429/502/503/504 are retryable — all other 4xx cause the SDK to permanently drop
/// the data. We use 400 (not 429) for quota/restriction rejections because we don't
/// want SDKs to retry data that will always be rejected.
fn non_retryable_rejection(message: &str) -> Response {
    (StatusCode::BAD_REQUEST, Json(json!({ "error": message }))).into_response()
}

#[instrument(skip(state, body), fields(span_count, body_size))]
pub async fn otel_handler(
    State(state): State<AppState>,
    ip: Option<InsecureClientIp>,
    headers: HeaderMap,
    body: Body,
) -> Result<Json<serde_json::Value>, Response> {
    let body = extract_body_with_timeout(
        body,
        OTEL_BODY_SIZE,
        state.body_chunk_read_timeout,
        state.body_read_chunk_size_kb,
        "/i/v0/ai/otel",
    )
    .await
    .map_err(|e| {
        report_internal_error_metrics(e.to_metric_tag(), "otel_body_read");
        e.into_response()
    })?;

    if body.is_empty() {
        let err = CaptureError::EmptyPayload;
        report_internal_error_metrics(err.to_metric_tag(), "otel_validation");
        return Err(err.into_response());
    }

    let body_len = body.len();
    Span::current().record("body_size", body_len);
    histogram!("capture_ai_otel_body_size_bytes").record(body_len as f64);

    let content_type = headers
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("unknown");
    let format = if content_type.starts_with("application/x-protobuf") {
        "protobuf"
    } else if content_type.starts_with("application/json") {
        "json"
    } else {
        "unknown"
    };
    counter!("capture_ai_otel_requests_total", "format" => format).increment(1);

    let auth_header = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    if !auth_header.starts_with("Bearer ") {
        let err = CaptureError::NoTokenError;
        report_internal_error_metrics(err.to_metric_tag(), "otel_auth");
        return Err(err.into_response());
    }

    let token = &auth_header[7..]; // Remove "Bearer " prefix
    validate_token(token).map_err(|e| {
        let err = CaptureError::from(e);
        report_internal_error_metrics(err.to_metric_tag(), "otel_auth");
        err.into_response()
    })?;

    if state.token_dropper.should_drop(token, "") {
        report_dropped_events("token_dropper", 1);
        return Ok(Json(json!({})));
    }

    let request = ingestion::parse_request(&body, &headers, OTEL_BODY_SIZE).map_err(|e| {
        report_internal_error_metrics(e.to_metric_tag(), "otel_parsing");
        e.into_response()
    })?;

    let span_count = count_spans(&request);
    Span::current().record("span_count", span_count);

    if span_count == 0 {
        return Ok(Json(json!({})));
    }
    if span_count > MAX_SPANS_PER_REQUEST {
        warn!(
            "OTEL request contains {} spans, exceeding limit of {}",
            span_count, MAX_SPANS_PER_REQUEST
        );
        let err = CaptureError::RequestParsingError(format!(
            "Too many spans: {span_count} exceeds limit of {MAX_SPANS_PER_REQUEST}"
        ));
        report_internal_error_metrics(err.to_metric_tag(), "otel_validation");
        return Err(err.into_response());
    }
    counter!("capture_ai_otel_spans_received").increment(span_count as u64);
    histogram!("capture_ai_otel_spans_per_request").record(span_count as f64);

    let received_at = Utc::now();
    let distinct_id = identity::extract_distinct_id(&request);

    let client_ip = ip
        .map(|InsecureClientIp(addr)| addr.to_string())
        .unwrap_or_else(|| "127.0.0.1".to_string());

    let span_events = fan_out::expand_into_events(&request, &distinct_id);
    let token = token.to_string();

    // All-or-nothing quota check: reject the entire batch if any span is over quota
    if let Err(outcome) = filtering::check_quota(&state.quota_limiter, &token, &span_events).await {
        return match outcome {
            filtering::QuotaOutcome::Dropped => Err(non_retryable_rejection("quota exceeded")),
            filtering::QuotaOutcome::Error(e) => {
                report_internal_error_metrics(e.to_metric_tag(), "otel_quota");
                Err(e.into_response())
            }
        };
    }

    let restrictions = match &state.event_restriction_service {
        Some(service) => {
            let now_ts = state.timesource.current_time().timestamp();
            filtering::check_restrictions(service, &token, now_ts, &span_events)
                .await
                .map_err(|_| non_retryable_rejection("event restricted"))?
        }
        None => Default::default(),
    };

    let processed_events =
        filtering::build_events(span_events, &token, &client_ip, received_at, &restrictions)
            .map_err(|e| {
                report_internal_error_metrics(e.to_metric_tag(), "otel_processing");
                e.into_response()
            })?;

    state.sink.send_batch(processed_events).await.map_err(|e| {
        report_internal_error_metrics(e.to_metric_tag(), "otel_sink");
        warn!("Failed to send OTel events to Kafka: {:?}", e);
        e.into_response()
    })?;

    counter!("capture_ai_otel_events_ingested").increment(span_count as u64);
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
