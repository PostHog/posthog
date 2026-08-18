use chrono::{DateTime, Utc};
use common_types::CapturedEvent;
use limiters::redis::QuotaResource;
use serde_json::json;
use tracing::error;
use uuid::Uuid;

use crate::api::CaptureError;
use crate::event_restrictions::{
    AppliedRestrictions, EventContext, EventRestrictionService, Pipeline,
};
use crate::prometheus::report_dropped_events;
use crate::quota_limiters::CaptureQuotaLimiter;
use crate::v0_request::{DataType, ProcessedEvent, ProcessedEventMetadata};

use super::fan_out::SpanEvent;

pub enum QuotaOutcome {
    Dropped,
    Error(CaptureError),
}

pub async fn apply_quota(
    limiter: &CaptureQuotaLimiter,
    token: &str,
    span_events: Vec<SpanEvent>,
) -> Result<Vec<SpanEvent>, QuotaOutcome> {
    let mut unverified = Vec::with_capacity(span_events.len());
    let mut verified = Vec::new();
    for event in span_events {
        if event
            .properties
            .get("$ai_gateway_verified")
            .and_then(serde_json::Value::as_bool)
            .unwrap_or(false)
        {
            verified.push(event);
        } else {
            unverified.push(event);
        }
    }

    if !verified.is_empty()
        && limiter
            .is_quota_limited_v1(token, &QuotaResource::Events)
            .await
    {
        report_dropped_events(
            "otel_quota_drop",
            verified.len() as u64 + unverified.len() as u64,
        );
        return Err(QuotaOutcome::Dropped);
    }
    if unverified.is_empty() {
        return Ok(verified);
    }

    let count = unverified.len();

    match limiter.check_and_filter(token, unverified).await {
        Ok(mut retained) => {
            let dropped = count - retained.len();
            if dropped > 0 {
                report_dropped_events("otel_quota_drop", dropped as u64);
            }
            verified.append(&mut retained);
            Ok(verified)
        }
        Err(CaptureError::BillingLimit) if !verified.is_empty() => {
            report_dropped_events("otel_quota_drop", count as u64);
            Ok(verified)
        }
        Err(CaptureError::BillingLimit) => {
            report_dropped_events("otel_quota_drop", count as u64);
            Err(QuotaOutcome::Dropped)
        }
        Err(e) => Err(QuotaOutcome::Error(e)),
    }
}

pub async fn apply_restrictions(
    service: &EventRestrictionService,
    token: &str,
    now_ts: i64,
    span_events: Vec<SpanEvent>,
) -> Vec<(SpanEvent, AppliedRestrictions)> {
    let mut retained = Vec::with_capacity(span_events.len());
    for span in span_events {
        let ctx = EventContext {
            event_name: Some(&span.event_name),
            distinct_id: Some(&span.distinct_id),
            now_ts,
            ..Default::default()
        };
        let applied = service.get_restrictions(token, &ctx, Pipeline::Ai).await;
        if applied.should_drop() {
            report_dropped_events("otel_restriction_drop", 1);
        } else {
            retained.push((span, applied));
        }
    }
    retained
}

pub fn build_events(
    span_events: Vec<(SpanEvent, AppliedRestrictions)>,
    token: &str,
    client_ip: &str,
    received_at: DateTime<Utc>,
) -> Result<Vec<ProcessedEvent>, CaptureError> {
    let now_rfc3339 = received_at.to_rfc3339();
    let mut processed = Vec::with_capacity(span_events.len());

    for (span_event, restrictions) in span_events {
        let event_data = json!({
            "event": &span_event.event_name,
            "distinct_id": &span_event.distinct_id,
            "properties": span_event.properties,
        });

        let data = serde_json::to_string(&event_data).map_err(|e| {
            error!("Failed to serialize OTel event data: {}", e);
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
            skip_heatmap_processing: false,
            overflow_reason: None,
            distinct_id_truncated_from: None,
        };

        processed.push(ProcessedEvent {
            event: captured_event,
            metadata,
        });
    }

    Ok(processed)
}
