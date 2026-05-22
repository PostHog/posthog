//! `/v2/resolve` request handler. Returns per-event dispositions in a
//! structured response shape that the ingestion pipeline can route on
//! without inference.
//!
//! Isolation model: each input event runs through the core HTTP processing
//! pipeline as its own `Batch<1>` in a separate future, wrapped
//! in a per-event timeout and `catch_unwind`. A failure (panic, timeout, or
//! `UnhandledError`) for one event becomes a `retry` disposition for that
//! position only — the request still returns dispositions for every other
//! event in the batch.
//!
//! Per-request shared state restores the cross-event optimizations the
//! legacy single-batch flow gets implicitly:
//!
//! - **Batch issue cache**: a per-request `Cache<(team_id, fingerprint), Issue>`
//!   that all per-event pipeline invocations share, so events with the same
//!   fingerprint within a request resolve their issue exactly once.
//! - **Spike-alert inputs**: each per-event invocation returns any alerting
//!   candidate it produced, and the handler runs spike detection **once** at
//!   end-of-request with the merged batch — avoiding per-event Redis call
//!   amplification without hidden shared state.

use std::{collections::HashSet, sync::Arc, time::Duration};

use axum::{
    extract::{Json, State},
    http::HeaderMap,
};
use tokio::time::Instant;
use tracing::{debug, error, warn};

use crate::{
    app_context::AppContext,
    metric_consts::{
        DISPOSITIONS_EMITTED_TOTAL, PROCESS_BATCH_EVENTS, PROCESS_REQUESTS_TOTAL,
        PROCESS_REQUEST_DURATION_SECONDS,
    },
    router::{
        event::{get_request_id, ProcessEndpoint, ProcessEventCapacityGuard, ProcessEventsError},
        event_disposition_processor::PerEventDispositionProcessor,
    },
    stages::{
        alerting::{run_spike_detection_for_inputs, SpikeAlertInput},
        linking::LinkingStage,
    },
    types::{event::AnyEvent, event_disposition::EventDisposition},
};

/// Handler for `POST /v2/resolve`. Accepts a JSON array of events and
/// returns a JSON array of dispositions aligned 1:1 with the input.
#[axum::debug_handler]
pub async fn resolve_events_v2(
    State(ctx): State<Arc<AppContext>>,
    headers: HeaderMap,
    Json(events): Json<Vec<AnyEvent>>,
) -> Result<Json<Vec<EventDisposition>>, ProcessEventsError> {
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
        "Started /v2/resolve request"
    );

    let _capacity = ProcessEventCapacityGuard::try_start(
        &ctx,
        ProcessEndpoint::ResolveV2,
        &request_id,
        batch_event_count,
        team_count,
    )?;

    // Deadlines: per-event budget caps how long any single event can take,
    // and the request deadline bounds the whole call. Per-event deadlines
    // ensure that one slow event can't block fast siblings; the request
    // deadline is a safety net in case per-event budgeting has a bug.
    let request_deadline =
        started_at + Duration::from_millis(ctx.config.process_request_deadline_ms);
    let per_event_budget = Duration::from_millis(ctx.config.process_per_event_deadline_ms);

    // Per-request issue cache is threaded into every per-event pipeline
    // invocation so per-event isolation doesn't lose the legacy flow's
    // cross-event issue lookup deduplication.
    let shared_batch_issue_cache = LinkingStage::default_batch_issue_cache();

    let processor =
        PerEventDispositionProcessor::new(ctx.clone(), per_event_budget, shared_batch_issue_cache);
    let resolutions = processor.process_batch(events, request_deadline).await;
    let spike_alert_inputs = resolutions
        .iter()
        .filter_map(|resolution| resolution.spike_alert_input.clone())
        .collect::<Vec<_>>();
    let dispositions = resolutions
        .into_iter()
        .map(|resolution| resolution.disposition)
        .collect::<Vec<_>>();
    let disposition_counts = DispositionCounts::from_dispositions(&dispositions);

    // Run spike detection once with the merged inputs from every per-event
    // invocation. This is what makes the per-event isolation cheap: one
    // Redis call covers the whole request, the same as the legacy flow.
    //
    // Spike detection is a customer-facing alerting feature, not a fire-and-
    // forget side effect: if it fails, we propagate the error and 500 the
    // request so the client retries (matching the legacy `/process` flow).
    // Silently dropping a failure here would mean a customer-visible spike
    // alert never fires — worse than re-symbolicating a batch on retry.
    if let Err(err) = run_deferred_spike_detection(ctx.clone(), spike_alert_inputs).await {
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
            "Failed /v2/resolve request (deferred spike detection error)"
        );
        return Err(ProcessEventsError::Unhandled(err));
    }

    record_disposition_metrics(&dispositions);

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
            forward_count = disposition_counts.forward,
            drop_count = disposition_counts.drop,
            retry_count = disposition_counts.retry,
            dlq_count = disposition_counts.dlq,
            "Completed /v2/resolve request (slow)"
        );
    } else {
        debug!(
            request_id = %request_id,
            duration_ms,
            batch_event_count,
            team_count,
            forward_count = disposition_counts.forward,
            drop_count = disposition_counts.drop,
            retry_count = disposition_counts.retry,
            dlq_count = disposition_counts.dlq,
            "Completed /v2/resolve request"
        );
    }

    Ok(Json(dispositions))
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
    inputs: Vec<SpikeAlertInput>,
) -> Result<(), crate::error::UnhandledError> {
    run_spike_detection_for_inputs(ctx, inputs).await
}

fn record_disposition_metrics(dispositions: &[EventDisposition]) {
    for disposition in dispositions {
        metrics::counter!(
            DISPOSITIONS_EMITTED_TOTAL,
            "action" => disposition.action_label(),
            "reason" => disposition.reason_label(),
        )
        .increment(1);
    }
}

struct DispositionCounts {
    forward: usize,
    drop: usize,
    retry: usize,
    dlq: usize,
}

impl DispositionCounts {
    fn from_dispositions(dispositions: &[EventDisposition]) -> Self {
        dispositions.iter().fold(
            Self {
                forward: 0,
                drop: 0,
                retry: 0,
                dlq: 0,
            },
            |mut counts, disposition| {
                match disposition {
                    EventDisposition::Forward { .. } => counts.forward += 1,
                    EventDisposition::Drop { .. } => counts.drop += 1,
                    EventDisposition::Retry { .. } => counts.retry += 1,
                    EventDisposition::Dlq { .. } => counts.dlq += 1,
                }
                counts
            },
        )
    }
}
