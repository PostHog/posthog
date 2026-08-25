mod attribution;
mod error_status;
mod fan_out;
mod filtering;
mod identity;
mod ingestion;
mod provenance;
mod providers;

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
use crate::events::ai_byte_limit::drop_ai_byte_limited;
use crate::events::overflow_stamping::stamp_overflow_reason;
use crate::extractors::extract_body_with_timeout;
use crate::ingestion_warnings::otel::{
    emit_no_ai_spans_warning, emit_otel_parse_warning, emit_span_cap_warning,
    emit_span_too_big_warning, SpanCapStage,
};
use crate::prometheus::{report_dropped_events, report_internal_error_metrics};
use crate::router::State as AppState;
use crate::token::validate_token;
use crate::v0_request::exceeds_max_ai_event_bytes;

use self::attribution::otel_request_context;

pub const OTEL_BODY_SIZE: usize = 4 * 1024 * 1024; // 4MB

/// Route this handler serves. Stamped onto warnings so a reader of the v2 table
/// can tell which endpoint produced them.
const OTEL_PATH: &str = "/i/v0/ai/otel";

/// Maximum AI spans accepted after filtering. SDKs receive a 400 (non-retryable)
/// if this is exceeded, so callers must batch sensibly.
const MAX_SPANS_PER_REQUEST: usize = 100;

/// Maximum raw spans accepted before filtering. Set well above MAX_SPANS_PER_REQUEST
/// to accommodate mixed-content batches (e.g. Next.js sending HTTP + AI spans together)
/// while still bounding the cost of attribute scanning.
const MAX_RAW_SPANS_PER_REQUEST: usize = 1000;

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
        OTEL_PATH,
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
    let normalized_content_type = match format {
        "protobuf" => "application/x-protobuf",
        "json" => "application/json",
        _ => "unknown",
    };
    let content_encoding = headers
        .get("content-encoding")
        .and_then(|value| value.to_str().ok())
        .map(str::trim)
        .unwrap_or("")
        .to_ascii_lowercase();
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

    let gateway_provenance = provenance::verify(
        &headers,
        state.ai_gateway_signing_secret.as_deref(),
        token,
        normalized_content_type,
        &content_encoding,
        &body,
        state.timesource.current_time(),
    );

    let request = ingestion::parse_request(&body, &headers, OTEL_BODY_SIZE).map_err(|e| {
        report_internal_error_metrics(e.to_metric_tag(), "otel_parsing");
        // No parsed request to attribute from: the SDK identity lives inside the
        // body we couldn't read.
        emit_otel_parse_warning(
            state.ingestion_warning_emitter.as_deref(),
            &otel_request_context(token, OTEL_PATH, None),
            &e,
            format,
        );
        e.into_response()
    })?;

    let raw_span_count = count_spans(&request);

    if raw_span_count == 0 {
        counter!("capture_ai_otel_requests_success").increment(1);
        return Ok(Json(json!({})));
    }

    // Cap raw spans before doing any expensive attribute conversion. The body
    // size limit (4 MB) bounds the absolute maximum, but compact protobuf can
    // pack many spans into that budget.
    if raw_span_count > MAX_RAW_SPANS_PER_REQUEST {
        let err = CaptureError::RequestParsingError(format!(
            "Too many spans: {raw_span_count} exceeds limit of {MAX_RAW_SPANS_PER_REQUEST}"
        ));
        report_internal_error_metrics(err.to_metric_tag(), "otel_validation");
        emit_span_cap_warning(
            state.ingestion_warning_emitter.as_deref(),
            &otel_request_context(token, OTEL_PATH, Some(&request)),
            SpanCapStage::Raw,
            raw_span_count,
            MAX_RAW_SPANS_PER_REQUEST,
        );
        return Err(err.into_response());
    }

    let received_at = Utc::now();
    let request_fallback_distinct_id = identity::request_fallback_distinct_id();
    let mut span_events = fan_out::expand_into_events(&request, &request_fallback_distinct_id);
    provenance::apply(
        &mut span_events,
        gateway_provenance,
        headers.contains_key(crate::gateway_provenance::SIGNATURE_HEADER),
        headers
            .get(crate::gateway_provenance::REQUEST_ID_HEADER)
            .and_then(|value| value.to_str().ok()),
    );
    let span_count = span_events.len();
    let dropped_span_count = raw_span_count.saturating_sub(span_count);

    Span::current().record("span_count", span_count);

    if dropped_span_count > 0 {
        counter!("capture_ai_otel_spans_filtered").increment(dropped_span_count as u64);
    }

    if span_count == 0 {
        // Reached only with raw_span_count > 0 (the zero-span export returned
        // above), so the customer sent spans and none of them landed. The OTLP
        // contract has no way to say that in the response, which is why this
        // 200 gets a warning and the mixed-batch case above does not.
        emit_no_ai_spans_warning(
            state.ingestion_warning_emitter.as_deref(),
            &otel_request_context(token, OTEL_PATH, Some(&request)),
            raw_span_count,
        );
        counter!("capture_ai_otel_requests_success").increment(1);
        return Ok(Json(json!({})));
    }
    if span_count > MAX_SPANS_PER_REQUEST {
        let err = CaptureError::RequestParsingError(format!(
            "Too many AI spans: {span_count} exceeds limit of {MAX_SPANS_PER_REQUEST}"
        ));
        report_internal_error_metrics(err.to_metric_tag(), "otel_validation");
        emit_span_cap_warning(
            state.ingestion_warning_emitter.as_deref(),
            &otel_request_context(token, OTEL_PATH, Some(&request)),
            SpanCapStage::Ai,
            span_count,
            MAX_SPANS_PER_REQUEST,
        );
        return Err(err.into_response());
    }

    counter!("capture_ai_otel_spans_accepted").increment(span_count as u64);
    histogram!("capture_ai_otel_spans_per_request").record(span_count as f64);

    let client_ip = ip
        .map(|InsecureClientIp(addr)| addr.to_string())
        .unwrap_or_else(|| "127.0.0.1".to_string());
    let token = token.to_string();

    // All-or-nothing quota check: reject the entire batch if any span is over quota
    if let Err(outcome) = filtering::check_quota(
        &state.quota_limiter,
        &token,
        &span_events,
        gateway_provenance == provenance::Provenance::Verified,
    )
    .await
    {
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

    let mut processed_events =
        filtering::build_events(span_events, &token, &client_ip, received_at, &restrictions)
            .map_err(|e| {
                report_internal_error_metrics(e.to_metric_tag(), "otel_processing");
                e.into_response()
            })?;

    // Shed spans past the deployment's per-event ceiling rather than refusing
    // the export.
    //
    // Every other AI path answers an oversize event with an error: the legacy
    // batch path 413s the request and v1 marks the single event dropped. OTEL
    // diverges because a collector retries a rejected export, so a span that
    // can never fit would stall every span queued behind it, indefinitely. The
    // span cap on this endpoint sheds spans for the same reason.
    //
    // The cost is that the loss cannot be seen in the response, so it is
    // reported twice: on `capture_events_dropped_total` for us, and as a
    // `MessageSizeTooLarge` ingestion warning for whoever owns the project.
    let before = processed_events.len();
    processed_events
        .retain(|e| !exceeds_max_ai_event_bytes(e.event.data.len(), state.ai_max_event_bytes));
    let dropped = before - processed_events.len();
    if dropped > 0 {
        report_dropped_events("ai_event_too_big", dropped as u64);
        emit_span_too_big_warning(
            state.ingestion_warning_emitter.as_deref(),
            &otel_request_context(&token, OTEL_PATH, Some(&request)),
            dropped,
            state.ai_max_event_bytes,
        );
    }

    // Charge the AI lane's per-project byte budget, shedding the spans that
    // take the project past it. This endpoint builds its events at the handler
    // and reaches the sink through neither analytics pipeline, so without this
    // call a sender could spend an unbounded number of bytes here while the
    // same bytes on `/i/v0/ai/batch` are capped.
    //
    // Shedding rather than refusing, for the reason the size ceiling above
    // sheds: a collector retries a rejected export, so refusing would stall
    // every span behind the ones over budget. Unlike the size ceiling this
    // raises no ingestion warning — a rate drop is ops-imposed, and capture
    // surfaces those through billing and ops channels rather than the
    // customer-facing warnings table, which `warning_for_capture_error` pins.
    //
    // It runs after the ceiling so an event too big to publish spends none of
    // the budget, matching the order both analytics pipelines use.
    drop_ai_byte_limited(&mut processed_events, state.ai_byte_rate_limiter.as_ref()).await;

    // Apply the in-process OverflowLimiter governor to every AnalyticsMain
    // span in the batch before handing off to the sink. OTEL bypasses
    // `events::analytics::process_events`, so this call is what preserves
    // OverflowLimiter parity on `capture-ai-*` deploys (where
    // `OVERFLOW_ENABLED=true`). Per-span key evaluation matches the analytics
    // batch path: spans with different `token:distinct_id` keys can land
    // with different `overflow_reason` stamps in the same batch.
    stamp_overflow_reason(
        &mut processed_events,
        state.overflow_limiter.as_ref(),
        state.ai_events_overflow_limiter.as_ref(),
    );

    // Count what the sink was handed, not what arrived: `span_count` predates
    // the size ceiling and the byte budget, either of which may have shed spans.
    let ingested = processed_events.len() as u64;

    state.sink.send_batch(processed_events).await.map_err(|e| {
        report_internal_error_metrics(e.to_metric_tag(), "otel_sink");
        warn!("Failed to send OTel events to Kafka: {:?}", e);
        e.into_response()
    })?;

    counter!("capture_ai_otel_events_ingested").increment(ingested);
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
