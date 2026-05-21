//! `/v2/process` request handler. Returns per-event verdicts in a
//! structured response shape that the ingestion pipeline can route on
//! without inference.
//!
//! Isolation model: each input event runs through the existing
//! `HttpEventPipeline` as its own `Batch<1>` in a separate future, wrapped
//! in a per-event timeout and `catch_unwind`. A failure (panic, timeout, or
//! `UnhandledError`) for one event becomes a `retry` verdict for that
//! position only — the request still returns verdicts for every other
//! event in the batch.
//!
//! Per-request shared state restores the cross-event optimizations the
//! legacy single-batch flow gets implicitly:
//!
//! - **Batch issue cache**: a per-request `Cache<(team_id, fingerprint), Issue>`
//!   that all per-event pipeline invocations share, so events with the same
//!   fingerprint within a request resolve their issue exactly once.
//! - **Spike-alert accumulator**: a shared accumulator that collects
//!   `(issue, props)` from every per-event invocation and runs spike
//!   detection **once** at end-of-request with the merged batch — avoiding
//!   the per-event Redis call amplification we'd otherwise see.

use std::{collections::HashSet, sync::Arc, time::Duration};

use axum::{
    extract::{Json, State},
    http::HeaderMap,
};
use futures::future::join_all;
use futures::FutureExt;
use moka::future::Cache;
use std::panic::AssertUnwindSafe;
use tokio::time::Instant;
use tracing::{debug, error, warn};

use crate::{
    app_context::AppContext,
    issue_resolution::Issue,
    metric_consts::{
        ERRORS, PROCESS_BATCH_EVENTS, PROCESS_REQUESTS_TOTAL, PROCESS_REQUEST_DURATION_SECONDS,
        VERDICTS_EMITTED_TOTAL, VERDICT_DEADLINE_FALLBACK_TOTAL, VERDICT_DURATION_SECONDS,
        VERDICT_PANIC_TOTAL, VERDICT_REQUEST_DEADLINE_EXHAUSTED_TOTAL,
    },
    router::event::{get_request_id, ProcessEventsError, ProcessInFlightGuard},
    stages::{
        alerting::{spike_detection::do_spike_detection, SpikeAlertAccumulator},
        http_pipeline::HttpEventPipeline,
        linking::LinkingStage,
    },
    types::{
        batch::Batch,
        event::AnyEvent,
        operator::TeamId,
        stage::Stage,
        verdict::{EventVerdict, RetryReason},
    },
};

/// Handler for `POST /v2/process`. Accepts a JSON array of events and
/// returns a JSON array of verdicts aligned 1:1 with the input.
#[axum::debug_handler]
pub async fn process_events_v2(
    State(ctx): State<Arc<AppContext>>,
    headers: HeaderMap,
    Json(events): Json<Vec<AnyEvent>>,
) -> Result<Json<Vec<EventVerdict>>, ProcessEventsError> {
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
        "Started /v2/process request"
    );

    // Same backpressure semaphore as /process — when the in-flight limit is
    // hit, this request is rejected with 429. This is the path cymbal uses
    // to tell the client to back off; the inner CB on the client side will
    // pick it up the same way it does for the legacy endpoint.
    let _permit = ctx
        .process_request_limiter
        .clone()
        .try_acquire_owned()
        .map_err(|_| {
            // Mirror legacy `/process` so existing alerts on
            // `cymbal_errors{cause="process_backpressure"}` and
            // `cymbal_process_requests_total{outcome="error", status_class="4xx"}`
            // pick up v2 backpressure too.
            metrics::counter!(ERRORS, "cause" => "process_backpressure").increment(1);
            metrics::counter!(
                PROCESS_REQUESTS_TOTAL,
                "outcome" => "error",
                "status_class" => "4xx",
                "endpoint" => "v2"
            )
            .increment(1);
            warn!(
                request_id = %request_id,
                batch_event_count,
                team_count,
                "Rejected /v2/process request due to backpressure"
            );
            ProcessEventsError::Backpressure
        })?;

    // Deadlines: per-event budget caps how long any single event can take,
    // and the request deadline bounds the whole call. Per-event deadlines
    // ensure that one slow event can't block fast siblings; the request
    // deadline is a safety net in case per-event budgeting has a bug.
    let request_deadline =
        started_at + Duration::from_millis(ctx.config.process_request_deadline_ms);
    let per_event_budget = Duration::from_millis(ctx.config.process_per_event_deadline_ms);

    // Per-request shared state. Both pieces are threaded into every per-event
    // pipeline invocation so the per-event isolation we get for free doesn't
    // come at the cost of losing the legacy flow's cross-event optimizations.
    let shared_batch_issue_cache = LinkingStage::default_batch_issue_cache();
    let spike_alert_accumulator = SpikeAlertAccumulator::new();

    let verdicts = run_isolated_per_event(
        ctx.clone(),
        events,
        request_deadline,
        per_event_budget,
        shared_batch_issue_cache,
        spike_alert_accumulator.clone(),
    )
    .await;

    record_verdict_metrics(&verdicts);

    // Verdict-shape counters useful in completion logs. Computed once so
    // both the slow-log and the success-log can include them.
    let (process_count, drop_count, retry_count, dlq_count) =
        verdicts
            .iter()
            .fold((0, 0, 0, 0), |(p, d, r, dl), v| match v {
                EventVerdict::Process { .. } => (p + 1, d, r, dl),
                EventVerdict::Drop { .. } => (p, d + 1, r, dl),
                EventVerdict::Retry { .. } => (p, d, r + 1, dl),
                EventVerdict::Dlq { .. } => (p, d, r, dl + 1),
            });

    // Run spike detection once with the merged inputs from every per-event
    // invocation. This is what makes the per-event isolation cheap: one
    // Redis call covers the whole request, the same as the legacy flow.
    //
    // Spike detection is a customer-facing alerting feature, not a fire-and-
    // forget side effect: if it fails, we propagate the error and 500 the
    // request so the client retries (matching the legacy `/process` flow).
    // Silently dropping a failure here would mean a customer-visible spike
    // alert never fires — worse than re-symbolicating a batch on retry.
    if let Err(err) = run_deferred_spike_detection(ctx.clone(), spike_alert_accumulator).await {
        let duration_ms = started_at.elapsed().as_millis() as u64;
        metrics::counter!(
            PROCESS_REQUESTS_TOTAL,
            "outcome" => "error",
            "status_class" => "5xx",
            "endpoint" => "v2"
        )
        .increment(1);
        metrics::histogram!(PROCESS_REQUEST_DURATION_SECONDS, "endpoint" => "v2")
            .record(started_at.elapsed().as_secs_f64());
        error!(
            request_id = %request_id,
            error = %err,
            duration_ms,
            batch_event_count,
            team_count,
            "Failed /v2/process request (deferred spike detection error)"
        );
        return Err(ProcessEventsError::Unhandled(err));
    }

    let duration = started_at.elapsed();
    let duration_ms = duration.as_millis() as u64;
    let is_slow = duration_ms >= ctx.config.process_slow_log_threshold_ms;

    metrics::counter!(
        PROCESS_REQUESTS_TOTAL,
        "outcome" => "success",
        "status_class" => "2xx",
        "endpoint" => "v2"
    )
    .increment(1);
    metrics::histogram!(PROCESS_REQUEST_DURATION_SECONDS, "endpoint" => "v2")
        .record(duration.as_secs_f64());

    if is_slow {
        warn!(
            request_id = %request_id,
            duration_ms,
            batch_event_count,
            team_count,
            process_count,
            drop_count,
            retry_count,
            dlq_count,
            "Completed /v2/process request (slow)"
        );
    } else {
        debug!(
            request_id = %request_id,
            duration_ms,
            batch_event_count,
            team_count,
            process_count,
            drop_count,
            retry_count,
            dlq_count,
            "Completed /v2/process request"
        );
    }

    Ok(Json(verdicts))
}

/// Drive every event through its own isolated pipeline invocation and
/// collect the verdicts. Each event gets the same deadline budget but runs
/// concurrently with the others.
///
/// The whole join is also bounded by the request deadline: if for any
/// reason events are still in flight when the request deadline elapses,
/// the unfinished ones collapse to a `retry/deadline_exceeded` verdict so
/// the response can return on time.
async fn run_isolated_per_event(
    ctx: Arc<AppContext>,
    events: Vec<AnyEvent>,
    request_deadline: Instant,
    per_event_budget: Duration,
    shared_batch_issue_cache: Cache<(TeamId, String), Issue>,
    spike_alert_accumulator: Arc<SpikeAlertAccumulator>,
) -> Vec<EventVerdict> {
    let event_count = events.len();
    if event_count == 0 {
        return Vec::new();
    }

    let now = Instant::now();
    let per_event_deadlines: Vec<Instant> = (0..event_count)
        .map(|_| (now + per_event_budget).min(request_deadline))
        .collect();

    let futures = events
        .into_iter()
        .zip(per_event_deadlines)
        .map(|(event, deadline)| {
            let ctx = ctx.clone();
            // Cloning the moka cache is a refcount bump on the underlying
            // storage — every per-event invocation sees the same data.
            let cache = shared_batch_issue_cache.clone();
            let acc = spike_alert_accumulator.clone();
            async move { verdict_for_single_event(ctx, event, deadline, cache, acc).await }
        });

    let request_remaining = request_deadline.duration_since(Instant::now());

    match tokio::time::timeout(request_remaining, join_all(futures)).await {
        Ok(verdicts) => verdicts,
        Err(_) => {
            // The request budget elapsed before all per-event futures
            // resolved. This should be rare — per-event deadlines should
            // bring each event home first. Track it explicitly so it's
            // alertable if it starts happening.
            metrics::counter!(VERDICT_REQUEST_DEADLINE_EXHAUSTED_TOTAL).increment(1);
            warn!(
                event_count,
                "Request deadline exhausted with events still in flight; \
                 filling with retry/deadline_exceeded verdicts"
            );
            // We don't have position-level resolution here (the join_all
            // was abandoned). All positions get the same fallback. This is
            // a degraded-mode response.
            std::iter::repeat_with(|| EventVerdict::Retry {
                reason: RetryReason::DeadlineExceeded,
                retry_after_ms: None,
            })
            .take(event_count)
            .collect()
        }
    }
}

/// Run the existing pipeline on a single event (as a `Batch<1>`) with the
/// per-event deadline and panic catching applied, then convert the result
/// to an `EventVerdict`.
async fn verdict_for_single_event(
    ctx: Arc<AppContext>,
    event: AnyEvent,
    deadline: Instant,
    batch_issue_cache: Cache<(TeamId, String), Issue>,
    spike_alert_accumulator: Arc<SpikeAlertAccumulator>,
) -> EventVerdict {
    let started = Instant::now();
    let remaining = match deadline.checked_duration_since(started) {
        Some(d) if !d.is_zero() => d,
        _ => {
            // Already past deadline before we started — emit retry
            // without doing more work. Possible if the request deadline
            // is tighter than the per-event budget for the last events
            // in the batch.
            metrics::counter!(VERDICT_DEADLINE_FALLBACK_TOTAL).increment(1);
            return EventVerdict::Retry {
                reason: RetryReason::DeadlineExceeded,
                retry_after_ms: None,
            };
        }
    };

    let work = async {
        let pipeline =
            HttpEventPipeline::new(ctx, Some(batch_issue_cache), Some(spike_alert_accumulator));
        let input = Batch::from(vec![event]);
        pipeline.process(input).await
    };

    // catch_unwind absorbs panics from inside the pipeline so one event's
    // panic doesn't taint another's verdict.
    let panic_safe = AssertUnwindSafe(work).catch_unwind();

    let verdict = match tokio::time::timeout(remaining, panic_safe).await {
        Ok(Ok(Ok(batch))) => verdict_from_pipeline_output(batch),
        Ok(Ok(Err(unhandled))) => {
            // UnhandledError from the pipeline — classify as retry per the
            // contract. Cymbal does not assert the event is broken; we
            // don't know whether the failure is event-caused or cymbal-side.
            EventVerdict::from(unhandled)
        }
        Ok(Err(panic_payload)) => {
            warn!(
                "Per-event pipeline panicked: {}",
                panic_message(&panic_payload)
            );
            metrics::counter!(VERDICT_PANIC_TOTAL).increment(1);
            EventVerdict::Retry {
                reason: RetryReason::UnhandledProcessingError,
                retry_after_ms: None,
            }
        }
        Err(_elapsed) => {
            metrics::counter!(VERDICT_DEADLINE_FALLBACK_TOTAL).increment(1);
            EventVerdict::Retry {
                reason: RetryReason::DeadlineExceeded,
                retry_after_ms: None,
            }
        }
    };

    metrics::histogram!(VERDICT_DURATION_SECONDS, "status" => verdict.status_label())
        .record(started.elapsed().as_secs_f64());

    verdict
}

/// Convert a successful pipeline output (a `Batch<Option<AnyEvent>>` from
/// the existing pipeline) into an `EventVerdict`. The pipeline returns
/// `Some(event)` for events it processed and `None` for suppressed events
/// (the legacy "drop" signal). Per-event isolation guarantees the input
/// was a `Batch<1>`, so the output must also be length 1.
fn verdict_from_pipeline_output(batch: Batch<Option<AnyEvent>>) -> EventVerdict {
    let mut iter = Vec::from(batch).into_iter();
    match iter.next() {
        Some(Some(event)) => EventVerdict::Process {
            event: Box::new(event),
        },
        // The existing pipeline returns None for suppressed events. We
        // don't have visibility into whether it was issue-status or
        // rule-based suppression from the pipeline output alone, so we
        // emit a generic "issue_suppressed" drop reason. The pipeline's
        // own EventError variants distinguish the cases at the metric
        // layer (SuppressionRules vs IssueSuppression operators).
        Some(None) => EventVerdict::Drop {
            reason: crate::types::verdict::DropReason::IssueSuppressed,
        },
        // The pipeline returned an empty batch for a Batch<1> input.
        // This is a contract violation by the pipeline itself; treat as
        // retry so the pipeline can be debugged without dropping events.
        None => EventVerdict::Retry {
            reason: RetryReason::UnhandledProcessingError,
            retry_after_ms: None,
        },
    }
}

/// Run spike detection once at end-of-request with the merged inputs from
/// every per-event invocation. Equivalent to `SpikeAlertStage`'s inline
/// call in the legacy flow, just deferred so a single Redis call covers
/// the whole request rather than one per event.
///
/// Errors propagate to the caller — matching the legacy semantics where a
/// spike-detection failure 500s the request and the client retries. Spike
/// alerts are a customer-facing feature, not a fire-and-forget side
/// effect; silently dropping a failure here would mean missed alerts.
async fn run_deferred_spike_detection(
    ctx: Arc<AppContext>,
    accumulator: Arc<SpikeAlertAccumulator>,
) -> Result<(), crate::error::UnhandledError> {
    let state = accumulator.take().await;
    if state.issues.is_empty() {
        return Ok(());
    }

    let counts = state.issues_count_by_id();
    let props = state.issue_props_by_id.clone();
    let by_id = state.issues_by_id();

    do_spike_detection(ctx, by_id, props, counts).await
}

fn record_verdict_metrics(verdicts: &[EventVerdict]) {
    for verdict in verdicts {
        metrics::counter!(
            VERDICTS_EMITTED_TOTAL,
            "status" => verdict.status_label(),
            "reason" => verdict.reason_label(),
        )
        .increment(1);
    }
}

/// Best-effort extraction of a string description from a `catch_unwind`
/// payload. Falls back to a fixed label when the payload isn't a string.
fn panic_message(payload: &Box<dyn std::any::Any + Send>) -> String {
    if let Some(s) = payload.downcast_ref::<&'static str>() {
        return (*s).to_string();
    }
    if let Some(s) = payload.downcast_ref::<String>() {
        return s.clone();
    }
    "<non-string panic payload>".to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::issue_resolution::{Issue, IssueStatus};
    use crate::stages::alerting::SpikeAlertAccumulatorState;
    use crate::types::verdict::DlqReason;
    use crate::types::verdict::DropReason;
    use uuid::Uuid;

    fn make_event() -> AnyEvent {
        AnyEvent {
            uuid: Uuid::nil(),
            event: "$exception".to_string(),
            team_id: 1,
            timestamp: "2026-05-21T00:00:00Z".to_string(),
            properties: serde_json::json!({}),
            others: Default::default(),
        }
    }

    #[test]
    fn verdict_from_pipeline_output_maps_some_to_process() {
        let event = make_event();
        let batch = Batch::from(vec![Some(event.clone())]);

        let verdict = verdict_from_pipeline_output(batch);
        match verdict {
            EventVerdict::Process { event: returned } => {
                assert_eq!(returned.uuid, event.uuid);
            }
            other => panic!("expected Process, got {:?}", other),
        }
    }

    #[test]
    fn verdict_from_pipeline_output_maps_none_to_drop() {
        let batch: Batch<Option<AnyEvent>> = Batch::from(vec![None]);

        let verdict = verdict_from_pipeline_output(batch);
        assert!(matches!(
            verdict,
            EventVerdict::Drop {
                reason: DropReason::IssueSuppressed,
            }
        ));
    }

    #[test]
    fn verdict_from_pipeline_output_maps_empty_to_retry() {
        // A pipeline that returns an empty batch for a Batch<1> input is
        // a contract violation. Emit Retry so the pipeline can be debugged
        // without silently dropping events.
        let batch: Batch<Option<AnyEvent>> = Batch::from(Vec::<Option<AnyEvent>>::new());

        let verdict = verdict_from_pipeline_output(batch);
        assert!(matches!(
            verdict,
            EventVerdict::Retry {
                reason: RetryReason::UnhandledProcessingError,
                ..
            }
        ));
    }

    /// Reference test for the From<EventError> conversion. The actual
    /// `From<EventError>` lives in `types::verdict`; this is here to keep
    /// the v2 handler's intended verdict shape under regression coverage —
    /// if a stage starts emitting an EventError that maps differently, this
    /// test will need updating along with `From<EventError>`.
    #[test]
    fn invalid_properties_event_error_becomes_dlq_via_existing_from_impl() {
        use crate::error::EventError;
        let err = EventError::InvalidProperties(Uuid::nil(), "bad properties".to_string());
        let verdict: EventVerdict = err.into();
        assert!(matches!(
            verdict,
            EventVerdict::Dlq {
                reason: DlqReason::InvalidProperties,
            }
        ));
    }

    /// The deferred spike-detection inputs are aggregated by
    /// `SpikeAlertAccumulatorState`. This is the unit that the request
    /// handler hands to `do_spike_detection` once at end-of-request, so
    /// its shape is what makes the deferred Redis call single-shot.
    #[test]
    fn accumulator_state_counts_and_maps_issues() {
        let issue_alpha = Issue {
            id: Uuid::from_u128(1),
            team_id: 7,
            status: IssueStatus::Active,
            name: None,
            description: None,
            created_at: chrono::Utc::now(),
        };
        let issue_beta = Issue {
            id: Uuid::from_u128(2),
            team_id: 7,
            status: IssueStatus::Active,
            name: None,
            description: None,
            created_at: chrono::Utc::now(),
        };

        // Simulate 3 per-event pipelines contributing: 2 for alpha, 1 for
        // beta. In production this is built up by `record_batch` calls
        // from each AlertingStage invocation; for the aggregation unit
        // test we construct the state directly.
        let state = SpikeAlertAccumulatorState {
            issues: vec![issue_alpha.clone(), issue_alpha.clone(), issue_beta.clone()],
            issue_props_by_id: Default::default(),
        };

        let counts = state.issues_count_by_id();
        assert_eq!(counts.get(&issue_alpha.id), Some(&2));
        assert_eq!(counts.get(&issue_beta.id), Some(&1));
        assert_eq!(counts.len(), 2);

        let by_id = state.issues_by_id();
        assert_eq!(by_id.len(), 2);
        assert!(by_id.contains_key(&issue_alpha.id));
        assert!(by_id.contains_key(&issue_beta.id));
    }
}
