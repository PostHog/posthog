//! The AI lane's per-project byte budget. The lane is the whole gate: every
//! event on the `AI_EVENT_NAMES` allowlist is bound for the AI Kafka topic on
//! every deployment, stamped `DataType::AiEvents` in v0 and
//! `Destination::AiEvents` in v1. Import deployments are exempt — backfills
//! are never throttled, matching the other limiters — which setup enforces by
//! not building the limiter at all in import mode.
//!
//! The budget is per project token and fleet-wide: the shared global rate
//! limiter is charged an event's payload size instead of `1`, so a token's
//! bytes count against one window no matter which pod, which capture
//! deployment, or which pipeline ingests them.
//!
//! Both pipelines charge through [`charge_ai_bytes`] and act on the verdict in
//! their own idiom — v0 drops the event from the batch here in
//! [`drop_ai_byte_limited`], v1 marks it `EventResult::Drop` in
//! `v1::analytics::process::apply_ai_byte_limits`. Both charge after event
//! restrictions have filtered the batch, so an event a `DropEvent` restriction
//! discards never spends the project's budget.
use std::sync::Arc;

use crate::global_rate_limiter::GlobalRateLimiter;
use crate::prometheus::report_dropped_events;
use crate::v0_request::{DataType, ProcessedEvent};

/// Flat allowance for the `CapturedEvent` envelope fields not in `data`.
const ENVELOPE_WEIGHT_BYTES: usize = 512;

/// Charge `payload_bytes` against `token`'s AI budget and report whether the
/// event is over it.
///
/// Events with an empty token are never charged: keying on `""` would pool
/// unrelated senders into one bucket. Over-budget events are still charged —
/// that sheds a flood, and the bytes crossed the wire whether or not we
/// forward them.
pub async fn charge_ai_bytes(
    limiter: &GlobalRateLimiter,
    token: &str,
    payload_bytes: usize,
) -> bool {
    if token.is_empty() {
        return false;
    }
    // Approximate wire size: the payload plus a flat allowance for the fixed
    // envelope fields and JSON-escaping. The budget is a coarse abuse guard,
    // not an exact byte accountant, so the two pipelines' slightly different
    // payload measures do not need reconciling.
    let weight = (payload_bytes + ENVELOPE_WEIGHT_BYTES) as u64;
    limiter.is_limited(token, weight).await.is_some()
}

pub async fn drop_ai_byte_limited(
    events: &mut Vec<ProcessedEvent>,
    limiter: Option<&Arc<GlobalRateLimiter>>,
) {
    let Some(limiter) = limiter else {
        return;
    };

    // The limiter is async, so this can't be a `retain`. Rebuilding the batch
    // keeps one allocation for the whole pass rather than shifting elements.
    let mut kept = Vec::with_capacity(events.len());
    let mut dropped: u64 = 0;

    for event in events.drain(..) {
        if event.metadata.data_type != DataType::AiEvents {
            kept.push(event);
            continue;
        }
        if charge_ai_bytes(limiter, &event.event.token, event.event.data.len()).await {
            dropped += 1;
            continue;
        }
        kept.push(event);
    }

    if dropped > 0 {
        report_dropped_events("ai_byte_rate_limited", dropped);
    }
    *events = kept;
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::uuid_v7_from_datetime;
    use crate::v0_request::{DataType, ProcessedEvent, ProcessedEventMetadata};
    use common_types::CapturedEvent;
    use std::sync::Arc;

    fn event_of(data_type: DataType, token: &str, data: &str) -> ProcessedEvent {
        let timestamp = chrono::Utc::now();
        let event = CapturedEvent {
            uuid: uuid_v7_from_datetime(timestamp),
            distinct_id: "u".to_string(),
            session_id: None,
            ip: "127.0.0.1".to_string(),
            data: data.to_string(),
            now: "2026-04-20T00:00:00Z".to_string(),
            sent_at: None,
            token: token.to_string(),
            event: "test".to_string(),
            timestamp,
            is_cookieless_mode: false,
            historical_migration: false,
        };
        let metadata = ProcessedEventMetadata {
            data_type,
            session_id: None,
            computed_timestamp: None,
            event_name: "test".to_string(),
            force_overflow: false,
            skip_person_processing: false,
            redirect_to_dlq: false,
            redirect_to_topic: None,
            skip_heatmap_processing: false,
            overflow_reason: None,
            distinct_id_truncated_from: None,
        };
        ProcessedEvent { event, metadata }
    }

    /// A budget of `bytes` for every token, charged the same weights the
    /// production call site charges. A token's first event is always admitted,
    /// as it is against the real limiter's cold cache, so a test that expects a
    /// drop has to send at least two.
    fn limiter(bytes: u64) -> Arc<GlobalRateLimiter> {
        Arc::new(GlobalRateLimiter::mock_budget(bytes))
    }

    /// One enveloped event of this size weighs ~517 B, so a 1000-byte budget
    /// admits the first and rejects the second.
    fn small_ai_event(token: &str) -> ProcessedEvent {
        event_of(DataType::AiEvents, token, &"x".repeat(5))
    }

    #[tokio::test]
    async fn none_limiter_is_a_no_op() {
        let mut events = vec![event_of(DataType::AiEvents, "t", "xxxxxxxxxx")];
        drop_ai_byte_limited(&mut events, None).await;
        assert_eq!(events.len(), 1);
    }

    #[tokio::test]
    async fn under_budget_ai_events_are_kept() {
        let l = limiter(1_000_000);
        let mut events = vec![small_ai_event("t"), small_ai_event("t")];
        drop_ai_byte_limited(&mut events, Some(&l)).await;
        assert_eq!(events.len(), 2);
    }

    #[tokio::test]
    async fn over_budget_ai_events_are_dropped() {
        let l = limiter(1_000);
        let mut events = vec![small_ai_event("t"), small_ai_event("t")];
        drop_ai_byte_limited(&mut events, Some(&l)).await;
        assert_eq!(events.len(), 1, "the over-budget AI event must be dropped");
    }

    #[tokio::test]
    async fn non_ai_lanes_are_never_dropped_by_this_helper() {
        let l = limiter(1);
        let mut events = vec![
            event_of(DataType::AnalyticsMain, "t", &"x".repeat(40)),
            event_of(DataType::AnalyticsMain, "t", &"x".repeat(40)),
        ];
        drop_ai_byte_limited(&mut events, Some(&l)).await;
        assert_eq!(events.len(), 2, "AnalyticsMain must not be touched");
    }

    #[tokio::test]
    async fn tokenless_events_are_kept() {
        // An empty token is not a budget: keying on it would pool unrelated
        // senders into one bucket.
        let l = limiter(1);
        let mut events = vec![
            event_of(DataType::AiEvents, "", &"x".repeat(40)),
            event_of(DataType::AiEvents, "", &"x".repeat(40)),
        ];
        drop_ai_byte_limited(&mut events, Some(&l)).await;
        assert_eq!(events.len(), 2);
    }

    #[tokio::test]
    async fn the_budget_is_charged_in_bytes_not_events() {
        // Three events, each ~517 B, against a 1000-byte budget: an
        // event-counting limiter of the same size would admit all three.
        let l = limiter(1_000);
        let mut events = vec![
            small_ai_event("t"),
            small_ai_event("t"),
            small_ai_event("t"),
        ];
        drop_ai_byte_limited(&mut events, Some(&l)).await;
        assert_eq!(events.len(), 1);
    }

    #[tokio::test]
    async fn each_token_draws_on_its_own_budget() {
        // tok_a exhausts its budget; tok_b's events are unaffected.
        let l = limiter(1_000);
        let mut events = vec![
            small_ai_event("tok_a"),
            small_ai_event("tok_a"),
            small_ai_event("tok_b"),
            small_ai_event("tok_b"),
        ];
        drop_ai_byte_limited(&mut events, Some(&l)).await;
        assert_eq!(events.len(), 2);
    }

    #[tokio::test]
    async fn mixed_batch_drops_only_over_budget_ai_events() {
        let l = limiter(1_000);
        let mut events = vec![
            small_ai_event("t"),                                     // first: admitted
            event_of(DataType::AnalyticsMain, "t", &"x".repeat(99)), // untouched
            small_ai_event("t"),                                     // exceeds remaining
        ];
        drop_ai_byte_limited(&mut events, Some(&l)).await;
        assert_eq!(events.len(), 2);
        assert!(events
            .iter()
            .any(|e| e.metadata.data_type == DataType::AnalyticsMain));
    }
}
