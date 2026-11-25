use std::{collections::HashSet, fmt, sync::Arc, time::Instant};

use axum::{
    extract::{rejection::JsonRejection, FromRequest, Json, Request, State},
    http::HeaderMap,
    response::{IntoResponse, Response},
};

use common_ingestion_response::{codes, ItemResult, ItemResults, PerItemResults, Warning};
use common_ingestion_warnings::WarningType;
use reqwest::StatusCode;
use serde::de::{DeserializeSeed, Deserializer, IgnoredAny, SeqAccess, Visitor};
use uuid::Uuid;

use serde_json::{json, value::RawValue, Map, Value};
use tracing::{debug, error, warn};

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::{
        ERRORS, EVENT_PROCESSING_FAILURES, PROCESS_BATCH_EVENTS, PROCESS_IN_FLIGHT,
        PROCESS_REQUESTS_TOTAL, PROCESS_REQUEST_DURATION_MS,
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
    Rejected(JsonRejection),
    TooManyEvents { events: usize, limit: usize },
    NotEvents(String),
}

impl From<JsonRejection> for ProcessEventsError {
    fn from(rejection: JsonRejection) -> Self {
        Self::Rejected(rejection)
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
                    "error": "Too many in-flight /process requests",
                    "details": "Backpressure limit reached, retry later",
                })),
            )
                .into_response(),
            ProcessEventsError::Rejected(rejection) => rejection.into_response(),
            ProcessEventsError::NotEvents(details) => (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(json!({
                    "error": "The /process body is not an array of events",
                    "details": details,
                })),
            )
                .into_response(),
            ProcessEventsError::TooManyEvents { events, limit } => (
                StatusCode::PAYLOAD_TOO_LARGE,
                Json(json!({
                    "error": "Too many events in /process request",
                    "details": format!("{events} events, the limit is {limit}"),
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

fn first_failure(batch: &Batch<ProcessOutcome>) -> Option<(usize, String)> {
    let failures = batch
        .inner_ref()
        .iter()
        .filter_map(|outcome| match outcome {
            ProcessOutcome::Failed { message, .. } | ProcessOutcome::Retry { message, .. } => {
                Some(message)
            }
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
    PerItemResults(item_results): PerItemResults,
    request: Request,
) -> Result<Response, ProcessEventsError> {
    if !item_results {
        // A slot of this response is the event or `null`, so it cannot report a failed event:
        // a malformed event rejects the body, and a failed event fails the request.
        let Json(events) = Json::<Vec<AnyEvent>>::from_request(request, &()).await?;
        let batch = run_pipeline(ctx, headers, events, false).await?;
        return Ok(batch
            .map(
                |outcome, ()| match outcome {
                    ProcessOutcome::Ok(event) => Some(event),
                    ProcessOutcome::Dropped(_)
                    | ProcessOutcome::Failed { .. }
                    | ProcessOutcome::Retry { .. } => None,
                },
                &mut (),
            )
            .into_response());
    }

    // A raw event is not parsed here, so an event that only its own parse rejects, such as one
    // nested past the recursion limit, fails alone.
    let Json(body) = Json::<Box<RawValue>>::from_request(request, &()).await?;
    let limit = ctx.config.process_max_events_per_request;
    let RawEvents {
        bodies,
        total: request_items,
    } = RawEvents::deserializer(limit)
        .deserialize(&mut serde_json::Deserializer::from_str(body.get()))
        .map_err(|err| ProcessEventsError::NotEvents(err.to_string()))?;
    if request_items > limit {
        metrics::counter!(ERRORS, "cause" => "process_too_many_events").increment(1);
        return Err(ProcessEventsError::TooManyEvents {
            events: request_items,
            limit,
        });
    }
    let mut malformed = Vec::with_capacity(request_items);
    let mut events = Vec::with_capacity(request_items);
    for body in bodies {
        match serde_json::from_str::<AnyEvent>(body.get()) {
            Ok(event) => {
                malformed.push(None);
                events.push(event);
            }
            Err(err) => {
                metrics::counter!(EVENT_PROCESSING_FAILURES, "operator" => "parse_event")
                    .increment(1);
                malformed.push(Some(ProcessOutcome::Failed {
                    code: codes::INVALID_INPUT,
                    message: format!("malformed event: {err}"),
                }));
            }
        }
    }

    let mut processed = Vec::from(run_pipeline(ctx, headers, events, true).await?).into_iter();
    let mut outcomes: Vec<ProcessOutcome> = malformed
        .into_iter()
        .filter_map(|failed| failed.or_else(|| processed.next()))
        .collect();
    // Outcomes the pipeline should not have returned make the length check below fail.
    outcomes.extend(processed);

    let results = outcomes.into_iter().map(to_item_result).collect();
    ItemResults::new(request_items, results)
        .map(IntoResponse::into_response)
        .map_err(|err| {
            ProcessEventsError::Unhandled(Arc::new(UnhandledError::Other(err.to_string())))
        })
}

struct RawEvents {
    bodies: Vec<Box<RawValue>>,
    total: usize,
}

impl RawEvents {
    fn deserializer(limit: usize) -> RawEventsLimit {
        RawEventsLimit(limit)
    }
}

/// Keeps at most the limit of raw events and only counts the rest, so a body of many small
/// items cannot make the parse allocate one value for each of them.
struct RawEventsLimit(usize);

impl<'de> DeserializeSeed<'de> for RawEventsLimit {
    type Value = RawEvents;

    fn deserialize<D: Deserializer<'de>>(self, deserializer: D) -> Result<RawEvents, D::Error> {
        deserializer.deserialize_seq(self)
    }
}

impl<'de> Visitor<'de> for RawEventsLimit {
    type Value = RawEvents;

    fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
        formatter.write_str("an array of events")
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<RawEvents, A::Error> {
        let mut bodies = Vec::new();
        let mut total = 0;
        loop {
            if total < self.0 {
                match seq.next_element::<Box<RawValue>>()? {
                    Some(body) => bodies.push(body),
                    None => break,
                }
            } else if seq.next_element::<IgnoredAny>()?.is_none() {
                break;
            }
            total += 1;
        }
        Ok(RawEvents { bodies, total })
    }
}

fn to_item_result(outcome: ProcessOutcome) -> ItemResult<AnyEvent> {
    match outcome {
        ProcessOutcome::Ok(event) => match processing_errors_warning(&event) {
            Some(warning) => ItemResult::ok(event).with_warning(warning),
            None => ItemResult::ok(event),
        },
        ProcessOutcome::Dropped(reason) => ItemResult::drop(reason),
        ProcessOutcome::Failed { code, message } => ItemResult::fail(code, message),
        ProcessOutcome::Retry { code, message } => ItemResult::retry(code, message),
    }
}

/// Ingestion shows the `$cymbal_errors` of a processed event to its team as this warning.
fn processing_errors_warning(event: &AnyEvent) -> Option<Warning> {
    let errors = event
        .properties
        .get("$cymbal_errors")?
        .as_array()
        .filter(|errors| !errors.is_empty())?;
    let uuid = event.uuid.to_string();
    let details = Map::from_iter([
        ("eventUuid".to_string(), Value::String(uuid.clone())),
        ("errors".to_string(), Value::Array(errors.clone())),
    ]);
    Some(
        Warning::new(
            WarningType::ErrorTrackingExceptionProcessingErrors.as_str(),
            details,
        )
        .with_key(uuid),
    )
}

async fn run_pipeline(
    ctx: Arc<AppContext>,
    headers: HeaderMap,
    mut events: Vec<AnyEvent>,
    item_results: bool,
) -> Result<Batch<ProcessOutcome>, ProcessEventsError> {
    // `$cymbal_errors` reaches the team as a processing diagnostic, so it must only hold
    // errors that processing attached, never text the sender put in the event.
    for event in &mut events {
        if let Some(properties) = event.properties.as_object_mut() {
            properties.remove("$cymbal_errors");
        }
    }
    let item_results_label = if item_results { "true" } else { "false" };
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
                "item_results" => item_results_label
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
    let pipeline = HttpEventPipeline::new(ctx.clone(), item_results);
    let input = Batch::from(events);
    let output = pipeline.process(input).await;

    let failure = output.as_ref().ok().and_then(first_failure);
    let output = match &failure {
        Some((_, error)) if !item_results => Err(UnhandledError::Other(error.clone())),
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
                "item_results" => item_results_label
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
                "item_results" => item_results_label
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
