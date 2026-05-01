use chrono::{DateTime, Utc};
use common_types::CapturedEvent;
use serde_json::json;
use tracing::warn;
use uuid::Uuid;

use crate::api::CaptureError;
use crate::event_restrictions::{AppliedRestrictions, EventContext, EventRestrictionService};
use crate::prometheus::report_dropped_events;
use crate::quota_limiters::CaptureQuotaLimiter;
use crate::v0_request::{DataType, ProcessedEvent, ProcessedEventMetadata};

use super::fan_out::SpanEvent;

pub enum QuotaOutcome {
    Dropped,
    Error(CaptureError),
}

/// All-or-nothing quota check: if ANY span would be dropped by quota, reject the entire batch.
pub async fn check_quota(
    limiter: &CaptureQuotaLimiter,
    token: &str,
    span_events: &[SpanEvent],
) -> Result<(), QuotaOutcome> {
    let refs: Vec<&SpanEvent> = span_events.iter().collect();
    let count = refs.len();

    match limiter.check_and_filter(token, refs).await {
        Ok(filtered) if filtered.len() == count => Ok(()),
        Ok(filtered) => {
            let dropped = count - filtered.len();
            report_dropped_events("otel_quota_drop", dropped as u64);
            report_dropped_events("otel_all_or_nothing_drop", filtered.len() as u64);
            Err(QuotaOutcome::Dropped)
        }
        Err(CaptureError::BillingLimit) => {
            report_dropped_events("otel_quota_drop", count as u64);
            Err(QuotaOutcome::Dropped)
        }
        Err(e) => Err(QuotaOutcome::Error(e)),
    }
}

/// Per-span restriction checks with all-or-nothing semantics: if ANY span would be dropped,
/// reject the entire batch. Non-drop flags are OR'd across all spans — if any span triggers
/// a flag, it applies to the whole batch.
///
/// Returns `Err(())` if any span has a drop restriction (entire batch should be rejected).
pub async fn check_restrictions(
    service: &EventRestrictionService,
    token: &str,
    now_ts: i64,
    span_events: &[SpanEvent],
) -> Result<AppliedRestrictions, ()> {
    let mut merged = AppliedRestrictions::default();

    for span in span_events {
        let ctx = EventContext {
            event_name: Some(&span.event_name),
            distinct_id: Some(&span.distinct_id),
            now_ts,
            ..Default::default()
        };
        let applied = service.get_restrictions(token, &ctx).await;
        merged = merged.merge(applied);
    }

    if merged.should_drop() {
        report_dropped_events("otel_restriction_drop", span_events.len() as u64);
        return Err(());
    }

    Ok(merged)
}

/// Build ProcessedEvents from SpanEvents, applying restriction flags uniformly to all events.
pub fn build_events(
    span_events: Vec<SpanEvent>,
    token: &str,
    client_ip: &str,
    received_at: DateTime<Utc>,
    restrictions: &AppliedRestrictions,
) -> Result<Vec<ProcessedEvent>, CaptureError> {
    let now_rfc3339 = received_at.to_rfc3339();
    let mut processed = Vec::with_capacity(span_events.len());

    for span_event in span_events {
        let event_data = json!({
            "event": &span_event.event_name,
            "distinct_id": &span_event.distinct_id,
            "properties": span_event.properties,
        });

        let data = serde_json::to_string(&event_data).map_err(|e| {
            warn!("Failed to serialize OTel event data: {}", e);
            CaptureError::InternalError(format!("failed to serialize event data: {e}"))
        })?;

        let timestamp = span_event.timestamp.unwrap_or(received_at);
        let captured_event = CapturedEvent {
            uuid: Uuid::now_v7(),
            distinct_id: span_event.distinct_id,
            session_id: None,
            ip: client_ip.to_string(),
            data,
            now: now_rfc3339.clone(),
            sent_at: None,
            token: token.to_string(),
            event: span_event.event_name.clone(),
            timestamp,
            is_cookieless_mode: false,
            historical_migration: false,
        };

        let metadata = ProcessedEventMetadata {
            data_type: DataType::AnalyticsMain,
            session_id: None,
            computed_timestamp: Some(timestamp),
            event_name: span_event.event_name,
            force_overflow: restrictions.force_overflow(),
            skip_person_processing: restrictions.skip_person_processing(),
            redirect_to_dlq: restrictions.redirect_to_dlq(),
            redirect_to_topic: restrictions.redirect_to_topic().map(|s| s.to_string()),
            overflow_reason: None,
        };

        processed.push(ProcessedEvent {
            event: captured_event,
            metadata,
        });
    }

    Ok(processed)
}
