use std::{
    collections::HashSet,
    sync::Arc,
    time::{Duration, Instant},
};

use axum::{
    extract::{Json, State},
    http::HeaderMap,
    response::IntoResponse,
};

use rand::Rng;
use reqwest::StatusCode;
use uuid::Uuid;

use serde_json::json;
use tracing::{debug, error, warn};

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::{
        ERRORS, PROCESS_BATCH_EVENTS, PROCESS_DB_RETRIES, PROCESS_IN_FLIGHT,
        PROCESS_REQUESTS_TOTAL, PROCESS_REQUEST_DURATION_SECONDS,
    },
    stages::http_pipeline::HttpEventPipeline,
    types::{batch::Batch, event::AnyEvent, stage::Stage},
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

#[axum::debug_handler]
pub async fn process_events(
    State(ctx): State<Arc<AppContext>>,
    headers: HeaderMap,
    Json(events): Json<Vec<AnyEvent>>,
) -> Result<Batch<Option<AnyEvent>>, ProcessEventsError> {
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
    let output = run_pipeline_with_db_retries(&ctx, events).await;

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

    match output {
        Ok(batch) => Ok(batch),
        Err(err) => {
            let err = Arc::new(err);
            common_posthog::capture_exception(
                err.clone(),
                [
                    ("request_id", json!(request_id)),
                    ("batch_event_count", json!(batch_event_count)),
                    ("team_count", json!(team_count)),
                ],
            );
            Err(ProcessEventsError::Unhandled(err))
        }
    }
}

/// Runs the event pipeline, retrying the whole batch on a transient database error.
///
/// A pooled connection can be severed after `test_before_acquire` health-checks it or
/// while a query is in flight (Postgres failover/restart, a pgbouncer backend cycling),
/// surfacing as a transient `sqlx::Error` — classically `expected to read N bytes, got 0
/// bytes at EOF`. That cannot be prevented at acquire time, only recovered from: a fresh
/// attempt gets a healthy connection. Non-transient failures return immediately. The
/// pipeline is already safe to re-run (the caller retries the same batch on a 5xx, and
/// issue creation is idempotent), so replaying it in-process just recovers faster and
/// keeps the transient blip out of error tracking.
async fn run_pipeline_with_db_retries(
    ctx: &Arc<AppContext>,
    mut events: Vec<AnyEvent>,
) -> Result<Batch<Option<AnyEvent>>, UnhandledError> {
    let max_retries = ctx.config.process_db_max_retries;
    let base_backoff = Duration::from_millis(ctx.config.process_db_retry_backoff_ms.max(1));
    let max_backoff = Duration::from_millis(
        ctx.config
            .process_db_retry_max_backoff_ms
            .max(ctx.config.process_db_retry_backoff_ms.max(1)),
    );

    let mut attempt: u32 = 0;
    loop {
        // Keep a copy of the input while retries remain so a transient failure can be
        // replayed; on the final attempt move it, since there is nothing left to retry.
        let input = if attempt < max_retries {
            Batch::from(events.clone())
        } else {
            Batch::from(std::mem::take(&mut events))
        };

        let pipeline = HttpEventPipeline::new(ctx.clone());
        match pipeline.process(input).await {
            Ok(batch) => return Ok(batch),
            Err(err) if attempt < max_retries && is_transient_db_error(&err) => {
                attempt += 1;
                let backoff = backoff_with_jitter(base_backoff, max_backoff, attempt);
                metrics::counter!(PROCESS_DB_RETRIES).increment(1);
                warn!(
                    attempt,
                    max_retries,
                    backoff_ms = backoff.as_millis() as u64,
                    error = %err,
                    "Transient database error in /process pipeline, retrying"
                );
                tokio::time::sleep(backoff).await;
            }
            Err(err) => return Err(err),
        }
    }
}

/// A pipeline failure worth retrying: a database error that `common-database` classifies
/// as transient (connection resets, severed-connection EOF, and similar). Anything else —
/// including non-DB failures — is returned to the caller untouched.
fn is_transient_db_error(err: &UnhandledError) -> bool {
    matches!(err, UnhandledError::SqlxError(e) if common_database::is_transient_error(e))
}

/// Exponential backoff capped at `max`, plus up to ~50% jitter so a fleet of pods doesn't
/// retry in lockstep after a shared database blip. `attempt` is 1-based.
fn backoff_with_jitter(base: Duration, max: Duration, attempt: u32) -> Duration {
    let factor = 2u32.saturating_pow(attempt.saturating_sub(1));
    let capped = base.saturating_mul(factor).min(max);
    let max_jitter_ms = (capped.as_millis() as u64) / 2;
    let jitter = if max_jitter_ms == 0 {
        Duration::ZERO
    } else {
        Duration::from_millis(rand::thread_rng().gen_range(0..=max_jitter_ms))
    };
    capped + jitter
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io;

    #[test]
    fn severed_connection_eof_is_retriable() {
        // The exact failure this guards against: a connection severed mid-query surfaces
        // as an io error carrying the "got 0 bytes at EOF" message.
        let eof = sqlx::Error::Io(io::Error::new(
            io::ErrorKind::UnexpectedEof,
            "expected to read 5 bytes, got 0 bytes at EOF",
        ));
        assert!(is_transient_db_error(&UnhandledError::SqlxError(eof)));
    }

    #[test]
    fn non_transient_failures_are_not_retried() {
        // A definitive "no rows" is a real result, not a connection blip.
        assert!(!is_transient_db_error(&UnhandledError::SqlxError(
            sqlx::Error::RowNotFound
        )));
        // Non-DB failures must fall straight through to the caller.
        assert!(!is_transient_db_error(&UnhandledError::Other(
            "boom".to_string()
        )));
    }

    #[test]
    fn backoff_grows_and_stays_within_bounds() {
        let base = Duration::from_millis(50);
        let max = Duration::from_millis(500);
        for attempt in 1..=8 {
            let b = backoff_with_jitter(base, max, attempt);
            let expected_cap = base
                .saturating_mul(2u32.saturating_pow(attempt - 1))
                .min(max);
            // Never below the capped exponential, never more than 50% above it.
            assert!(
                b >= expected_cap,
                "attempt {attempt}: {b:?} < {expected_cap:?}"
            );
            assert!(
                b <= expected_cap + expected_cap / 2,
                "attempt {attempt}: {b:?} exceeds jitter ceiling"
            );
            // The cap itself is honored (plus jitter headroom).
            assert!(b <= max + max / 2);
        }
    }
}
