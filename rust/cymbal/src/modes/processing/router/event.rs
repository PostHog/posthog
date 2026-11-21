use std::{collections::HashSet, sync::Arc, time::Instant};

use axum::{
    extract::{Json, State},
    http::HeaderMap,
    response::{IntoResponse, Response},
};
use common_ingestion_response::{codes, ItemResult, ItemResults, PerItemResults, Warning};
use common_ingestion_warnings::WarningType;
use reqwest::StatusCode;
use serde_json::{json, Map, Value};
use tracing::{debug, error, warn};
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::{EventFailure, UnhandledError},
    metric_consts::{
        ERRORS, PROCESS_BATCH_EVENTS, PROCESS_EVENT_FAILURES, PROCESS_IN_FLIGHT,
        PROCESS_REQUESTS_TOTAL, PROCESS_REQUEST_DURATION_MS,
    },
    stages::http_pipeline::{HttpEventPipeline, ProcessedEvent},
    types::{batch::Batch, event::AnyEvent, stage::Stage},
};

const LOGGED_FAILURE_SAMPLE: usize = 5;

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
    InvalidBody(String),
}

impl IntoResponse for ProcessEventsError {
    fn into_response(self) -> Response {
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
            ProcessEventsError::InvalidBody(message) => {
                (StatusCode::UNPROCESSABLE_ENTITY, message).into_response()
            }
        }
    }
}

struct InputEvent {
    uuid: Option<Uuid>,
    team_id: Option<i64>,
    parsed: Result<AnyEvent, serde_json::Error>,
}

impl InputEvent {
    fn parse(value: Value) -> Self {
        let uuid = value
            .get("uuid")
            .and_then(Value::as_str)
            .and_then(|uuid| Uuid::parse_str(uuid).ok());
        let team_id = value.get("team_id").and_then(Value::as_i64);
        Self {
            uuid,
            team_id,
            parsed: serde_json::from_value(value),
        }
    }
}

#[axum::debug_handler]
pub async fn process_events(
    State(ctx): State<Arc<AppContext>>,
    headers: HeaderMap,
    PerItemResults(item_results): PerItemResults,
    Json(events): Json<Vec<Value>>,
) -> Result<Response, ProcessEventsError> {
    let _in_flight = ProcessInFlightGuard::start();
    let request_id = get_request_id(&headers);
    let started_at = Instant::now();

    let inputs: Vec<InputEvent> = events.into_iter().map(InputEvent::parse).collect();
    // A caller without item results cannot take a per-event failure, so a malformed event
    // rejects the whole body.
    if !item_results {
        if let Some((index, err)) = inputs
            .iter()
            .enumerate()
            .find_map(|(index, input)| input.parsed.as_ref().err().map(|err| (index, err)))
        {
            return Err(ProcessEventsError::InvalidBody(format!(
                "Failed to deserialize the JSON body into the target type: [{index}]: {err}"
            )));
        }
    }

    let batch_event_count = inputs.len();
    let team_count = inputs
        .iter()
        .filter_map(|input| input.team_id)
        .collect::<HashSet<_>>()
        .len();

    metrics::histogram!(PROCESS_BATCH_EVENTS).record(batch_event_count as f64);

    debug!(
        request_id = %request_id,
        batch_event_count,
        team_count,
        item_results,
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
                "status_class" => "4xx"
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
    let mut ids = Vec::with_capacity(batch_event_count);
    let mut slots: Vec<Option<ProcessedEvent>> = Vec::with_capacity(batch_event_count);
    let mut valid = Vec::with_capacity(batch_event_count);
    for input in inputs {
        ids.push((input.uuid, input.team_id));
        match input.parsed {
            Ok(event) => {
                slots.push(None);
                valid.push(event);
            }
            Err(err) => slots.push(Some(ProcessedEvent::Failed(EventFailure::fail(
                codes::INVALID_INPUT,
                format!("invalid event: {err}"),
            )))),
        }
    }

    let output = HttpEventPipeline::new(ctx.clone(), item_results)
        .process(Batch::from(valid))
        .await
        .and_then(|batch| merge_into_slots(slots, batch));

    let duration = started_at.elapsed();
    let duration_ms = duration.as_millis() as u64;
    let is_slow = duration_ms >= slow_log_threshold_ms;

    metrics::histogram!(PROCESS_REQUEST_DURATION_MS).record(duration.as_secs_f64() * 1000.0);

    let output = match output {
        Ok(results) => results,
        Err(err) => {
            return Err(fail_request(
                err,
                &request_id,
                batch_event_count,
                team_count,
                duration_ms,
            ))
        }
    };

    let dropped_event_count = output
        .iter()
        .filter(|item| matches!(item, ProcessedEvent::Dropped(_)))
        .count();
    let failures: Vec<(usize, &EventFailure)> = output
        .iter()
        .enumerate()
        .filter_map(|(index, item)| match item {
            ProcessedEvent::Failed(failure) => Some((index, failure)),
            _ => None,
        })
        .collect();
    for (_, failure) in &failures {
        let retriable = if failure.retriable { "true" } else { "false" };
        metrics::counter!(PROCESS_EVENT_FAILURES, "code" => failure.code, "retriable" => retriable)
            .increment(1);
    }
    if !failures.is_empty() {
        let sample = failures
            .iter()
            .take(LOGGED_FAILURE_SAMPLE)
            .map(|(index, failure)| {
                let (uuid, team_id) = ids[*index];
                let uuid = uuid.map(|uuid| uuid.to_string()).unwrap_or_default();
                let team_id = team_id
                    .map(|team_id| team_id.to_string())
                    .unwrap_or_default();
                format!("{uuid}@{team_id} {failure}")
            })
            .collect::<Vec<_>>()
            .join("; ");
        warn!(
            request_id = %request_id,
            batch_event_count,
            failed_event_count = failures.len(),
            item_results,
            failed_events = %sample,
            "Events failed in /process request"
        );
    }

    if !item_results {
        if let Some((_, failure)) = failures.first() {
            let err = UnhandledError::Other(failure.to_string());
            return Err(fail_request(
                err,
                &request_id,
                batch_event_count,
                team_count,
                duration_ms,
            ));
        }
    }
    let failed_event_count = failures.len();

    let response = if item_results {
        let results = output.into_iter().map(to_item_result).collect();
        match ItemResults::new(batch_event_count, results) {
            Ok(results) => results.into_response(),
            Err(err) => {
                return Err(fail_request(
                    UnhandledError::Other(err.to_string()),
                    &request_id,
                    batch_event_count,
                    team_count,
                    duration_ms,
                ))
            }
        }
    } else {
        // `Json` serializes straight into the response body, so hand it the events
        // directly rather than first materializing an intermediate `serde_json::Value`.
        let events: Vec<Option<AnyEvent>> = output
            .into_iter()
            .map(|item| match item {
                ProcessedEvent::Event(event) => Some(event),
                ProcessedEvent::Dropped(_) | ProcessedEvent::Failed(_) => None,
            })
            .collect();
        (StatusCode::OK, Json(events)).into_response()
    };

    metrics::counter!(
        PROCESS_REQUESTS_TOTAL,
        "outcome" => "success",
        "status_class" => "2xx"
    )
    .increment(1);

    let output_event_count = batch_event_count - dropped_event_count - failed_event_count;
    if is_slow {
        warn!(
            request_id = %request_id,
            duration_ms,
            batch_event_count,
            output_event_count,
            dropped_event_count,
            team_count,
            "Completed /process request (slow)"
        );
    } else {
        debug!(
            request_id = %request_id,
            duration_ms,
            batch_event_count,
            output_event_count,
            dropped_event_count,
            team_count,
            "Completed /process request"
        );
    }

    Ok(response)
}

fn merge_into_slots(
    slots: Vec<Option<ProcessedEvent>>,
    processed: Batch<ProcessedEvent>,
) -> Result<Vec<ProcessedEvent>, UnhandledError> {
    let mut processed = Vec::from(processed).into_iter();
    let merged = slots
        .into_iter()
        .map(|slot| {
            slot.or_else(|| processed.next()).ok_or_else(|| {
                UnhandledError::Other("/process pipeline returned too few events".to_string())
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    if processed.next().is_some() {
        return Err(UnhandledError::Other(
            "/process pipeline returned too many events".to_string(),
        ));
    }
    Ok(merged)
}

fn to_item_result(item: ProcessedEvent) -> ItemResult<AnyEvent> {
    match item {
        ProcessedEvent::Event(event) => match processing_errors_warning(&event) {
            Some(warning) => ItemResult::ok(event).with_warning(warning),
            None => ItemResult::ok(event),
        },
        ProcessedEvent::Dropped(reason) => ItemResult::drop(reason),
        ProcessedEvent::Failed(failure) if failure.retriable => {
            ItemResult::retry(failure.code, failure.message)
        }
        ProcessedEvent::Failed(failure) => ItemResult::fail(failure.code, failure.message),
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

fn fail_request(
    err: UnhandledError,
    request_id: &str,
    batch_event_count: usize,
    team_count: usize,
    duration_ms: u64,
) -> ProcessEventsError {
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

    let err = Arc::new(err);
    common_posthog::capture_exception(
        err.clone(),
        [
            ("request_id", json!(request_id)),
            ("batch_event_count", json!(batch_event_count)),
            ("team_count", json!(team_count)),
        ],
    );
    ProcessEventsError::Unhandled(err)
}

#[cfg(test)]
mod tests {
    use common_ingestion_response::Outcome;

    use super::*;

    #[test]
    fn an_event_failure_becomes_retry_or_fail_by_whether_it_can_clear() {
        let retry = to_item_result(ProcessedEvent::Failed(EventFailure::retry(
            codes::DEADLINE_EXCEEDED,
            "slow",
        )));
        let fail = to_item_result(ProcessedEvent::Failed(EventFailure::fail(
            codes::INVALID_INPUT,
            "bad",
        )));

        assert!(
            matches!(&retry.outcome, Outcome::Retry { error } if error.code == codes::DEADLINE_EXCEEDED),
            "{retry:?}"
        );
        assert!(
            matches!(&fail.outcome, Outcome::Fail { error } if error.code == codes::INVALID_INPUT),
            "{fail:?}"
        );
    }
}
