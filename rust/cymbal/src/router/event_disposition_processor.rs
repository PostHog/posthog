use std::{panic::AssertUnwindSafe, sync::Arc, time::Duration};

use futures::{stream, FutureExt, StreamExt};
use moka::future::Cache;
use tokio::time::Instant;
use tracing::warn;

use crate::{
    app_context::AppContext,
    error::EventError,
    issue_resolution::Issue,
    metric_consts::{
        DISPOSITION_DEADLINE_FALLBACK_TOTAL, DISPOSITION_DURATION_SECONDS, DISPOSITION_PANIC_TOTAL,
        DISPOSITION_REQUEST_DEADLINE_EXHAUSTED_TOTAL,
    },
    stages::{
        alerting::SpikeAlertInput,
        http_pipeline::{HttpResolvePipeline, HttpResolveResult},
    },
    types::{
        batch::Batch,
        event::{AnyEvent, PropertiesContainer},
        event_disposition::{DropReason, EventDisposition, RetryReason},
        operator::TeamId,
        stage::Stage,
    },
};

pub(super) struct EventResolution {
    pub disposition: EventDisposition,
    pub spike_alert_input: Option<SpikeAlertInput>,
}

impl EventResolution {
    fn without_alert(disposition: EventDisposition) -> Self {
        Self {
            disposition,
            spike_alert_input: None,
        }
    }
}

/// Runs per-event Cymbal processing for `/v2/resolve` and converts each raw
/// result into an `EventDisposition`. The struct owns the request-scoped shared
/// state that must be reused across all isolated `Batch<1>` invocations.
#[derive(Clone)]
pub(super) struct PerEventDispositionProcessor {
    ctx: Arc<AppContext>,
    per_event_budget: Duration,
    batch_issue_cache: Cache<(TeamId, String), Issue>,
}

impl PerEventDispositionProcessor {
    pub(super) fn new(
        ctx: Arc<AppContext>,
        per_event_budget: Duration,
        batch_issue_cache: Cache<(TeamId, String), Issue>,
    ) -> Self {
        Self {
            ctx,
            per_event_budget,
            batch_issue_cache,
        }
    }

    /// Drive every event through its own isolated pipeline invocation and
    /// collect the dispositions. Each event gets the same deadline budget.
    /// Concurrency is capped by `batch_apply_concurrency`, matching the
    /// existing batch-stage fan-out limit so a single request cannot spawn
    /// unbounded DB/S3/Redis-capable work.
    ///
    /// If the request deadline elapses first, completed event dispositions are
    /// preserved and only unfinished positions get a `retry/deadline_exceeded`
    /// fallback.
    pub(super) async fn process_batch(
        &self,
        events: Vec<AnyEvent>,
        request_deadline: Instant,
    ) -> Vec<EventResolution> {
        let event_count = events.len();
        if event_count == 0 {
            return Vec::new();
        }

        let now = Instant::now();
        let concurrency_limit = self.ctx.config.batch_apply_concurrency.max(1);
        let futures = stream::iter(events.into_iter().enumerate().map(|(index, event)| {
            let deadline = (now + self.per_event_budget).min(request_deadline);
            let processor = self.clone();
            async move { (index, processor.process_one(event, deadline).await) }
        }))
        .buffered(concurrency_limit);
        tokio::pin!(futures);

        let mut resolutions: Vec<Option<EventResolution>> =
            std::iter::repeat_with(|| None).take(event_count).collect();
        let mut remaining = event_count;
        let deadline_sleep = tokio::time::sleep_until(request_deadline);
        tokio::pin!(deadline_sleep);

        while remaining > 0 {
            tokio::select! {
                item = futures.next() => {
                    match item {
                        Some((index, resolution)) => {
                            if resolutions[index].is_none() {
                                resolutions[index] = Some(resolution);
                                remaining -= 1;
                            }
                        }
                        None => break,
                    }
                }
                _ = &mut deadline_sleep => {
                    metrics::counter!(DISPOSITION_REQUEST_DEADLINE_EXHAUSTED_TOTAL).increment(1);
                    metrics::counter!(DISPOSITION_DEADLINE_FALLBACK_TOTAL).increment(remaining as u64);
                    break;
                }
            }
        }

        if remaining > 0 {
            warn!(
                event_count,
                unfinished_event_count = remaining,
                "Request deadline exhausted with events still in flight; \
                 filling unfinished positions with retry/deadline_exceeded dispositions"
            );
        }

        resolutions
            .into_iter()
            .map(|resolution| {
                resolution.unwrap_or_else(|| {
                    EventResolution::without_alert(deadline_exceeded_disposition())
                })
            })
            .collect()
    }

    /// Run the core processing pipeline on a single event (as a `Batch<1>`)
    /// with the per-event deadline and panic catching applied, then convert
    /// the result to an `EventDisposition`.
    async fn process_one(&self, event: AnyEvent, deadline: Instant) -> EventResolution {
        let started = Instant::now();
        let remaining = match deadline.checked_duration_since(started) {
            Some(d) if !d.is_zero() => d,
            _ => {
                // Already past deadline before we started — emit retry
                // without doing more work. Possible if the request deadline
                // is tighter than the per-event budget for the last events
                // in the batch.
                metrics::counter!(DISPOSITION_DEADLINE_FALLBACK_TOTAL).increment(1);
                return EventResolution::without_alert(deadline_exceeded_disposition());
            }
        };

        let ctx = self.ctx.clone();
        // Cloning the moka cache is a refcount bump on the underlying
        // storage — every per-event invocation sees the same data.
        let batch_issue_cache = self.batch_issue_cache.clone();

        let work = async move {
            let pipeline = HttpResolvePipeline::new(ctx, Some(batch_issue_cache));
            let input = Batch::from(vec![event]);
            pipeline.process(input).await
        };

        // catch_unwind absorbs panics from inside the pipeline so one event's
        // panic doesn't taint another's disposition.
        let panic_safe = AssertUnwindSafe(work).catch_unwind();

        let resolution = match tokio::time::timeout(remaining, panic_safe).await {
            Ok(Ok(Ok(batch))) => match disposition_from_pipeline_output(batch) {
                Ok(resolution) => resolution,
                Err(unhandled) => EventResolution::without_alert(
                    EventDisposition::from_unhandled_error(unhandled),
                ),
            },
            Ok(Ok(Err(unhandled))) => {
                // UnhandledError from the pipeline — classify as retry per the
                // contract. Cymbal does not assert the event is broken; we
                // don't know whether the failure is event-caused or cymbal-side.
                EventResolution::without_alert(EventDisposition::from_unhandled_error(unhandled))
            }
            Ok(Err(panic_payload)) => {
                warn!(
                    "Per-event pipeline panicked: {}",
                    panic_message(&panic_payload)
                );
                metrics::counter!(DISPOSITION_PANIC_TOTAL).increment(1);
                EventResolution::without_alert(EventDisposition::Retry {
                    reason: RetryReason::UnhandledProcessingError,
                    retry_after_ms: None,
                })
            }
            Err(_elapsed) => {
                metrics::counter!(DISPOSITION_DEADLINE_FALLBACK_TOTAL).increment(1);
                EventResolution::without_alert(deadline_exceeded_disposition())
            }
        };

        metrics::histogram!(DISPOSITION_DURATION_SECONDS, "action" => resolution.disposition.action_label())
            .record(started.elapsed().as_secs_f64());

        resolution
    }
}

/// Convert a successful core pipeline output into an `EventDisposition`.
/// Per-event isolation guarantees the input was a `Batch<1>`, so the output
/// must also be length 1.
fn disposition_from_pipeline_output(
    batch: Batch<HttpResolveResult>,
) -> Result<EventResolution, crate::error::UnhandledError> {
    let mut iter = Vec::from(batch).into_iter();
    match iter.next() {
        Some(result) => disposition_from_processing_result(result),
        // The pipeline returned an empty batch for a Batch<1> input.
        // This is a contract violation by the pipeline itself; treat as
        // retry so the pipeline can be debugged without dropping events.
        None => Ok(EventResolution::without_alert(EventDisposition::Retry {
            reason: RetryReason::UnhandledProcessingError,
            retry_after_ms: None,
        })),
    }
}

fn disposition_from_processing_result(
    processing_result: HttpResolveResult,
) -> Result<EventResolution, crate::error::UnhandledError> {
    let mut original = processing_result.original_event;
    match processing_result.result {
        Ok(props) => {
            let spike_alert_input = props.issue.as_ref().map(|issue| SpikeAlertInput {
                issue: issue.clone(),
                props: props.to_output(issue.id).ok(),
            });
            original.set_properties(props)?;
            Ok(EventResolution {
                disposition: EventDisposition::Forward {
                    event: Box::new(original),
                },
                spike_alert_input,
            })
        }
        Err(EventError::Suppressed(_)) => {
            Ok(EventResolution::without_alert(EventDisposition::Drop {
                reason: DropReason::IssueSuppressed,
            }))
        }
        Err(EventError::SuppressedByRule(_)) => {
            Ok(EventResolution::without_alert(EventDisposition::Drop {
                reason: DropReason::SuppressedByRule,
            }))
        }
        Err(err) => {
            original.attach_error(err.to_string())?;
            Ok(EventResolution::without_alert(EventDisposition::Forward {
                event: Box::new(original),
            }))
        }
    }
}

fn deadline_exceeded_disposition() -> EventDisposition {
    EventDisposition::Retry {
        reason: RetryReason::DeadlineExceeded,
        retry_after_ms: None,
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
    use crate::types::exception_properties::ExceptionProperties;
    use uuid::Uuid;

    fn make_event() -> AnyEvent {
        AnyEvent {
            uuid: Uuid::nil(),
            event: "$exception".to_string(),
            team_id: 1,
            timestamp: "2026-05-21T00:00:00Z".to_string(),
            properties: serde_json::json!({
                "$exception_list": [{"type": "Error", "value": "test"}],
            }),
            others: Default::default(),
        }
    }

    #[test]
    fn disposition_from_pipeline_output_maps_processed_event_to_forward() {
        let event = make_event();
        let props = ExceptionProperties::try_from(event.clone()).unwrap();
        let batch = Batch::from(vec![HttpResolveResult {
            original_event: event.clone(),
            result: Ok(props),
        }]);

        let resolution = disposition_from_pipeline_output(batch).unwrap();
        match resolution.disposition {
            EventDisposition::Forward { event: returned } => {
                assert_eq!(returned.uuid, event.uuid);
            }
            other => panic!("expected Forward, got {:?}", other),
        }
    }

    #[test]
    fn disposition_from_pipeline_output_maps_suppressed_error_to_drop() {
        let event = make_event();
        let batch: Batch<HttpResolveResult> = Batch::from(vec![HttpResolveResult {
            original_event: event,
            result: Err(crate::error::EventError::Suppressed(Uuid::nil())),
        }]);

        let resolution = disposition_from_pipeline_output(batch).unwrap();
        assert!(matches!(
            resolution.disposition,
            EventDisposition::Drop {
                reason: DropReason::IssueSuppressed,
            }
        ));
    }

    #[test]
    fn disposition_from_pipeline_output_attaches_handled_error_to_forwarded_event() {
        let event = make_event();
        let batch: Batch<HttpResolveResult> = Batch::from(vec![HttpResolveResult {
            original_event: event,
            result: Err(crate::error::EventError::EmptyExceptionList(Uuid::nil())),
        }]);

        let resolution = disposition_from_pipeline_output(batch).unwrap();
        let EventDisposition::Forward { event } = resolution.disposition else {
            panic!("expected Forward disposition");
        };
        let errors = event
            .properties
            .get("$cymbal_errors")
            .and_then(|value| value.as_array())
            .expect("forwarded event should carry cymbal errors");
        assert!(errors.iter().any(|error| error
            .as_str()
            .is_some_and(|error| error.contains("Empty exception list"))));
    }

    #[test]
    fn disposition_from_pipeline_output_maps_empty_to_retry() {
        // A pipeline that returns an empty batch for a Batch<1> input is
        // a contract violation. Emit Retry so the pipeline can be debugged
        // without silently dropping events.
        let batch: Batch<HttpResolveResult> = Batch::from(Vec::new());

        let resolution = disposition_from_pipeline_output(batch).unwrap();
        assert!(matches!(
            resolution.disposition,
            EventDisposition::Retry {
                reason: RetryReason::UnhandledProcessingError,
                ..
            }
        ));
    }
}
