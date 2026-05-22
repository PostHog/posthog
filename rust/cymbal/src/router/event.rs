use std::{collections::HashSet, sync::Arc, time::Instant};

use axum::{
    extract::{Json, State},
    http::HeaderMap,
    response::IntoResponse,
};

use reqwest::StatusCode;
use uuid::Uuid;

use serde_json::json;
use tokio::sync::OwnedSemaphorePermit;
use tracing::{debug, error, warn};

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::{
        ERRORS, PROCESS_BATCH_EVENTS, PROCESS_IN_FLIGHT, PROCESS_REQUESTS_TOTAL,
        PROCESS_REQUEST_DURATION_SECONDS,
    },
    stages::http_pipeline::HttpEventPipeline,
    types::{batch::Batch, event::AnyEvent, stage::Stage},
};

struct ProcessInFlightGuard {
    event_count: usize,
}

impl ProcessInFlightGuard {
    pub(super) fn start(event_count: usize) -> Self {
        metrics::gauge!(PROCESS_IN_FLIGHT).increment(event_count as f64);
        Self { event_count }
    }
}

impl Drop for ProcessInFlightGuard {
    fn drop(&mut self) {
        metrics::gauge!(PROCESS_IN_FLIGHT).decrement(self.event_count as f64);
    }
}

#[derive(Clone, Copy)]
pub(super) enum ProcessEndpoint {
    LegacyProcess,
    ResolveV2,
}

impl ProcessEndpoint {
    fn path(self) -> &'static str {
        match self {
            Self::LegacyProcess => "/process",
            Self::ResolveV2 => "/v2/resolve",
        }
    }

    fn metric_endpoint(self) -> Option<&'static str> {
        match self {
            Self::LegacyProcess => None,
            Self::ResolveV2 => Some("v2"),
        }
    }
}

pub(super) struct ProcessEventCapacityGuard {
    _in_flight: ProcessInFlightGuard,
    _permit: Option<OwnedSemaphorePermit>,
}

impl ProcessEventCapacityGuard {
    pub(super) fn try_start(
        ctx: &Arc<AppContext>,
        endpoint: ProcessEndpoint,
        request_id: &str,
        batch_event_count: usize,
        team_count: usize,
    ) -> Result<Self, ProcessEventsError> {
        let permit_count = u32::try_from(batch_event_count).unwrap_or(u32::MAX);
        let permit = if permit_count == 0 {
            None
        } else {
            Some(
                ctx.process_event_limiter
                    .clone()
                    .try_acquire_many_owned(permit_count)
                    .map_err(|_| {
                        metrics::counter!(ERRORS, "cause" => "process_backpressure").increment(1);
                        match endpoint.metric_endpoint() {
                            Some(endpoint_label) => {
                                metrics::counter!(
                                    PROCESS_REQUESTS_TOTAL,
                                    "outcome" => "error",
                                    "status_class" => "4xx",
                                    "endpoint" => endpoint_label
                                )
                                .increment(1);
                            }
                            None => {
                                metrics::counter!(
                                    PROCESS_REQUESTS_TOTAL,
                                    "outcome" => "error",
                                    "status_class" => "4xx"
                                )
                                .increment(1);
                            }
                        }
                        warn!(
                            request_id,
                            batch_event_count,
                            team_count,
                            endpoint = endpoint.path(),
                            "Rejected HTTP processing request due to event backpressure"
                        );
                        ProcessEventsError::Backpressure
                    })?,
            )
        };

        Ok(Self {
            _in_flight: ProcessInFlightGuard::start(batch_event_count),
            _permit: permit,
        })
    }
}

pub(super) fn get_request_id(headers: &HeaderMap) -> String {
    headers
        .get("x-request-id")
        .and_then(|v| v.to_str().ok())
        .filter(|v| !v.is_empty())
        .map(ToOwned::to_owned)
        .unwrap_or_else(|| Uuid::now_v7().to_string())
}

pub enum ProcessEventsError {
    Unhandled(UnhandledError),
    Backpressure,
}

impl From<UnhandledError> for ProcessEventsError {
    fn from(value: UnhandledError) -> Self {
        Self::Unhandled(value)
    }
}

impl IntoResponse for ProcessEventsError {
    fn into_response(self) -> axum::response::Response {
        match self {
            ProcessEventsError::Unhandled(err) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({
                    "error": "An unexpected error occurred while processing the events",
                    "details": err.to_string(),
                })),
            )
                .into_response(),
            ProcessEventsError::Backpressure => (
                StatusCode::TOO_MANY_REQUESTS,
                Json(json!({
                    "error": "Too many in-flight /process events",
                    "details": "Event backpressure limit reached, retry later",
                })),
            )
                .into_response(),
        }
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
) -> Result<Batch<Option<AnyEvent>>, ProcessEventsError> {
    let request_id = get_request_id(&headers);
    let started_at = Instant::now();

    let batch_event_count = events.len();
    let team_count = events
        .iter()
        .map(|event| event.team_id)
        .collect::<HashSet<_>>()
        .len();

    metrics::histogram!(PROCESS_BATCH_EVENTS).record(batch_event_count as f64);

    debug!(
        request_id = %request_id,
        batch_event_count,
        team_count,
        "Started /process request"
    );

    let _capacity = ProcessEventCapacityGuard::try_start(
        &ctx,
        ProcessEndpoint::LegacyProcess,
        &request_id,
        batch_event_count,
        team_count,
    )?;

    let slow_log_threshold_ms = ctx.config.process_slow_log_threshold_ms;
    // Legacy /process flow: no shared batch cache (each call gets its own
    // per-batch cache inside LinkingStage) and no spike-alert accumulator
    // (spike detection runs inline at the end of this batch).
    let pipeline = HttpEventPipeline::new(ctx.clone(), None, None);
    let input = Batch::from(events);
    let output = pipeline.process(input).await;

    let duration = started_at.elapsed();
    let duration_ms = duration.as_millis() as u64;
    let duration_s = duration.as_secs_f64();
    let is_slow = duration_ms >= slow_log_threshold_ms;

    metrics::histogram!(PROCESS_REQUEST_DURATION_SECONDS).record(duration_s);

    match &output {
        Ok(batch) => {
            let suppressed_event_count = batch
                .inner_ref()
                .iter()
                .filter(|item| item.is_none())
                .count();
            let output_event_count = batch_event_count.saturating_sub(suppressed_event_count);

            metrics::counter!(
                PROCESS_REQUESTS_TOTAL,
                "outcome" => "success",
                "status_class" => "2xx"
            )
            .increment(1);

            if is_slow {
                warn!(
                    request_id = %request_id,
                    duration_ms,
                    batch_event_count,
                    output_event_count,
                    suppressed_event_count,
                    team_count,
                    "Completed /process request (slow)"
                );
            } else {
                debug!(
                    request_id = %request_id,
                    duration_ms,
                    batch_event_count,
                    output_event_count,
                    suppressed_event_count,
                    team_count,
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
                batch_event_count,
                team_count,
                "Failed /process request"
            );
        }
    }

    output.map_err(ProcessEventsError::from)
}
