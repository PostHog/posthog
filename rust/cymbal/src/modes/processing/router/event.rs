use std::{collections::HashSet, sync::Arc, time::Instant};

use axum::{
    extract::{Json, State},
    http::HeaderMap,
    response::IntoResponse,
};

use common_ingestion_response::{ItemResult, ItemResults};
use reqwest::StatusCode;
use uuid::Uuid;

use serde_json::json;
use tracing::{debug, error, warn};

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::{
        ERRORS, PROCESS_BATCH_EVENTS, PROCESS_IN_FLIGHT, PROCESS_REQUESTS_TOTAL,
        PROCESS_REQUEST_DURATION_MS,
    },
    stages::http_pipeline::HttpEventPipeline,
    types::{
        batch::Batch,
        event::{AnyEvent, ProcessOutcome},
        stage::Stage,
    },
};

struct ProcessInFlightGuard;

impl ProcessInFlightGuard {
    fn start() -> Self {
        metrics::gauge!(PROCESS_IN_FLIGHT).increment(1.0);
        Self
    }
}

impl Drop for ProcessInFlightGuard {
    fn drop(&mut self) {
        metrics::gauge!(PROCESS_IN_FLIGHT).decrement(1.0);
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

pub enum ProcessEventsError {
    Unhandled(Arc<UnhandledError>),
    Backpressure,
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
                    "error": "Too many in-flight /process requests",
                    "details": "Backpressure limit reached, retry later",
                })),
            )
                .into_response(),
        }
    }
}

impl IntoResponse for Batch<Option<AnyEvent>> {
    fn into_response(self) -> axum::response::Response {
        // `Json` serializes straight into the response body, so hand it the events
        // directly rather than first materializing an intermediate `serde_json::Value`.
        (StatusCode::OK, Json(Vec::from(self))).into_response()
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Route {
    /// `POST /process`. A slot is the event or `null`, so one failed event fails the request.
    V1,
    V2,
}

impl Route {
    fn label(self) -> &'static str {
        match self {
            Route::V1 => "v1",
            Route::V2 => "v2",
        }
    }
}

fn first_failure(batch: &Batch<ProcessOutcome>) -> Option<(usize, String)> {
    let failures = batch
        .inner_ref()
        .iter()
        .filter_map(|outcome| match outcome {
            ProcessOutcome::Failed { message, .. } => Some(message),
            _ => None,
        })
        .collect::<Vec<_>>();
    failures
        .first()
        .map(|error| (failures.len(), error.to_string()))
}

#[axum::debug_handler]
pub async fn process_events(
    State(ctx): State<Arc<AppContext>>,
    headers: HeaderMap,
    Json(events): Json<Vec<AnyEvent>>,
) -> Result<Batch<Option<AnyEvent>>, ProcessEventsError> {
    let batch = run_pipeline(ctx, headers, events, Route::V1).await?;
    Ok(batch.map(
        |outcome, ()| match outcome {
            ProcessOutcome::Ok(event) => Some(event),
            ProcessOutcome::Dropped(_) | ProcessOutcome::Failed { .. } => None,
        },
        &mut (),
    ))
}

#[axum::debug_handler]
pub async fn process_events_v2(
    State(ctx): State<Arc<AppContext>>,
    headers: HeaderMap,
    Json(events): Json<Vec<AnyEvent>>,
) -> Result<ItemResults<AnyEvent>, ProcessEventsError> {
    let request_items = events.len();
    let results = Vec::from(run_pipeline(ctx, headers, events, Route::V2).await?)
        .into_iter()
        .map(|outcome| match outcome {
            ProcessOutcome::Ok(event) => ItemResult::ok(event),
            ProcessOutcome::Dropped(reason) => ItemResult::drop(reason),
            ProcessOutcome::Failed { code, message } => ItemResult::fail(code, message),
        })
        .collect();
    ItemResults::new(request_items, results).map_err(|err| {
        ProcessEventsError::Unhandled(Arc::new(UnhandledError::Other(err.to_string())))
    })
}

async fn run_pipeline(
    ctx: Arc<AppContext>,
    headers: HeaderMap,
    events: Vec<AnyEvent>,
    route: Route,
) -> Result<Batch<ProcessOutcome>, ProcessEventsError> {
    let _in_flight = ProcessInFlightGuard::start();
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

    let _permit = ctx
        .process_request_limiter
        .clone()
        .try_acquire_owned()
        .map_err(|_| {
            metrics::counter!(ERRORS, "cause" => "process_backpressure").increment(1);
            metrics::counter!(
                PROCESS_REQUESTS_TOTAL,
                "outcome" => "error",
                "status_class" => "4xx",
                "route" => route.label()
            )
            .increment(1);
            warn!(
                request_id = %request_id,
                batch_event_count,
                team_count,
                "Rejected /process request due to backpressure"
            );
            ProcessEventsError::Backpressure
        })?;

    let slow_log_threshold_ms = ctx.config.process_slow_log_threshold_ms;
    let pipeline = HttpEventPipeline::new(ctx.clone(), route == Route::V2);
    let input = Batch::from(events);
    let output = pipeline.process(input).await;

    let failure = output.as_ref().ok().and_then(first_failure);
    let output = match (route, &failure) {
        (Route::V1, Some((_, error))) => Err(UnhandledError::Other(error.clone())),
        _ => output,
    };

    let duration = started_at.elapsed();
    let duration_ms = duration.as_millis() as u64;
    let is_slow = duration_ms >= slow_log_threshold_ms;

    metrics::histogram!(PROCESS_REQUEST_DURATION_MS).record(duration.as_secs_f64() * 1000.0);

    let capture_context = [
        ("request_id", json!(request_id)),
        ("batch_event_count", json!(batch_event_count)),
        ("team_count", json!(team_count)),
    ];

    match output {
        Ok(batch) => {
            let suppressed_event_count = batch
                .inner_ref()
                .iter()
                .filter(|item| matches!(item, ProcessOutcome::Dropped(_)))
                .count();
            let failed_event_count = failure.as_ref().map_or(0, |(count, _)| *count);
            let output_event_count =
                batch_event_count.saturating_sub(suppressed_event_count + failed_event_count);

            metrics::counter!(
                PROCESS_REQUESTS_TOTAL,
                "outcome" => "success",
                "status_class" => "2xx",
                "route" => route.label()
            )
            .increment(1);

            if let Some((_, first_error)) = failure {
                error!(
                    request_id = %request_id,
                    error = %first_error,
                    duration_ms,
                    batch_event_count,
                    failed_event_count,
                    team_count,
                    "Completed /process request with failed events"
                );
                common_posthog::capture_exception(
                    Arc::new(UnhandledError::Other(first_error)),
                    capture_context,
                );
            } else if is_slow {
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
            Ok(batch)
        }
        Err(err) => {
            metrics::counter!(
                PROCESS_REQUESTS_TOTAL,
                "outcome" => "error",
                "status_class" => "5xx",
                "route" => route.label()
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

            let err = Arc::new(err);
            common_posthog::capture_exception(err.clone(), capture_context);
            Err(ProcessEventsError::Unhandled(err))
        }
    }
}
