use std::{
    collections::HashSet,
    sync::{
        atomic::{AtomicI64, Ordering},
        Arc,
    },
    time::Instant,
};

use axum::{
    extract::{Json, State},
    http::HeaderMap,
    response::IntoResponse,
};

use reqwest::StatusCode;
use uuid::Uuid;

use serde_json::json;
use tracing::{debug, error, warn};

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::{
        PROCESS_BATCH_EVENTS, PROCESS_IN_FLIGHT, PROCESS_REQUESTS_TOTAL,
        PROCESS_REQUEST_DURATION_SECONDS, PROCESS_REQUEST_SIZE_KB, PROCESS_RESPONSE_SIZE_KB,
    },
    stages::http_pipeline::HttpEventPipeline,
    types::{batch::Batch, event::AnyEvent, stage::Stage},
};

static PROCESS_IN_FLIGHT_COUNT: AtomicI64 = AtomicI64::new(0);

struct ProcessInFlightGuard;

impl ProcessInFlightGuard {
    fn start() -> Self {
        let current = PROCESS_IN_FLIGHT_COUNT.fetch_add(1, Ordering::Relaxed) + 1;
        metrics::gauge!(PROCESS_IN_FLIGHT).set(current as f64);
        Self
    }
}

impl Drop for ProcessInFlightGuard {
    fn drop(&mut self) {
        let previous = PROCESS_IN_FLIGHT_COUNT.fetch_sub(1, Ordering::Relaxed);
        let current = (previous - 1).max(0);
        metrics::gauge!(PROCESS_IN_FLIGHT).set(current as f64);
    }
}

fn get_request_id(headers: &HeaderMap) -> String {
    headers
        .get("x-request-id")
        .and_then(|v| v.to_str().ok())
        .filter(|v| !v.is_empty())
        .map(ToOwned::to_owned)
        .unwrap_or_else(|| Uuid::now_v7().to_string())
}

impl IntoResponse for UnhandledError {
    fn into_response(self) -> axum::response::Response {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({
                "error": "An unexpected error occurred while processing the events",
                "details": self.to_string(),
            })),
        )
            .into_response()
    }
}

impl IntoResponse for Batch<Option<AnyEvent>> {
    fn into_response(self) -> axum::response::Response {
        match serde_json::to_value(Vec::from(self)) {
            Ok(value) => (StatusCode::OK, Json(value)).into_response(),
            Err(e) => {
                warn!("Failed to serialize response: {}", e);
                (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    Json(json!({
                        "error": "Failed to serialize response",
                        "details": e.to_string()
                    })),
                )
                    .into_response()
            }
        }
    }
}

#[axum::debug_handler]
pub async fn process_events(
    State(ctx): State<Arc<AppContext>>,
    headers: HeaderMap,
    Json(events): Json<Vec<AnyEvent>>,
) -> Result<Batch<Option<AnyEvent>>, UnhandledError> {
    let _in_flight = ProcessInFlightGuard::start();
    let request_id = get_request_id(&headers);
    let started_at = Instant::now();

    let batch_events = events.len();
    let team_count = events
        .iter()
        .map(|event| event.team_id)
        .collect::<HashSet<_>>()
        .len();

    let estimated_request_bytes = match serde_json::to_vec(&events) {
        Ok(bytes) => bytes.len(),
        Err(err) => {
            warn!(request_id = %request_id, error = %err, "Failed to estimate request JSON size");
            0
        }
    };

    metrics::histogram!(PROCESS_BATCH_EVENTS).record(batch_events as f64);
    metrics::histogram!(PROCESS_REQUEST_SIZE_KB).record(estimated_request_bytes as f64 / 1024.0);

    debug!(
        request_id = %request_id,
        batch_events,
        team_count,
        request_size_bytes = estimated_request_bytes,
        "Started /process request"
    );

    let slow_log_threshold_ms = ctx.config.process_slow_log_threshold_ms;
    let pipeline = HttpEventPipeline::new(ctx.clone());
    let input = Batch::from(events);
    let output = pipeline.process(input).await;

    let duration = started_at.elapsed();
    let duration_ms = duration.as_millis() as u64;
    let duration_s = duration.as_secs_f64();
    let is_slow = duration_ms >= slow_log_threshold_ms;

    metrics::histogram!(PROCESS_REQUEST_DURATION_SECONDS).record(duration_s);

    match &output {
        Ok(batch) => {
            let suppressed_events = batch
                .inner_ref()
                .iter()
                .filter(|item| item.is_none())
                .count();
            let output_events = batch_events.saturating_sub(suppressed_events);

            metrics::counter!(
                PROCESS_REQUESTS_TOTAL,
                "outcome" => "success",
                "status_class" => "2xx"
            )
            .increment(1);

            let estimated_response_bytes = match serde_json::to_vec(batch.inner_ref()) {
                Ok(bytes) => {
                    let bytes_len = bytes.len();
                    metrics::histogram!(PROCESS_RESPONSE_SIZE_KB).record(bytes_len as f64 / 1024.0);
                    bytes_len
                }
                Err(err) => {
                    warn!(request_id = %request_id, error = %err, "Failed to estimate response JSON size");
                    0
                }
            };

            if is_slow {
                warn!(
                    request_id = %request_id,
                    duration_ms,
                    batch_events,
                    output_events,
                    suppressed_events,
                    team_count,
                    request_size_bytes = estimated_request_bytes,
                    response_size_bytes = estimated_response_bytes,
                    "Completed /process request (slow)"
                );
            } else {
                debug!(
                    request_id = %request_id,
                    duration_ms,
                    batch_events,
                    output_events,
                    suppressed_events,
                    team_count,
                    request_size_bytes = estimated_request_bytes,
                    response_size_bytes = estimated_response_bytes,
                    "Completed /process request"
                );
            }
        }
        Err(err) => {
            metrics::counter!(
                PROCESS_REQUESTS_TOTAL,
                "outcome" => "error",
                "status_class" => "5xx"
            )
            .increment(1);

            error!(
                request_id = %request_id,
                error = %err,
                duration_ms,
                batch_events,
                team_count,
                request_size_bytes = estimated_request_bytes,
                "Failed /process request"
            );
        }
    }

    output
}
