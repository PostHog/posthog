//! Drops over-budget events on the AI lane. `DataType::AiEvents` carries every
//! `$ai_*` event bound for the AI Kafka topic, on every deployment, so the lane
//! is the whole gate. Import deployments are exempt — backfills are never
//! throttled, matching the other limiters — which setup enforces by not
//! building the limiter at all in import mode.
use std::sync::Arc;

use limiters::byte_rate::{ByteLimitDecision, ByteRateLimiter};

use crate::prometheus::report_dropped_events;
use crate::v0_request::{DataType, ProcessedEvent};

/// Flat allowance for the `CapturedEvent` envelope fields not in `data`.
const ENVELOPE_WEIGHT_BYTES: usize = 512;

pub fn drop_ai_byte_limited(
    events: &mut Vec<ProcessedEvent>,
    limiter: Option<&Arc<ByteRateLimiter>>,
) {
    let Some(limiter) = limiter else {
        return;
    };
    events.retain(|e| {
        if e.metadata.data_type != DataType::AiEvents {
            return true;
        }
        // Approximate wire size: the serialized payload plus a flat allowance
        // for the `CapturedEvent` envelope and JSON-escaping of `data`. The
        // budget is a coarse abuse guard, not an exact byte accountant.
        let weight = e
            .event
            .data
            .len()
            .saturating_add(ENVELOPE_WEIGHT_BYTES)
            .min(u32::MAX as usize) as u32;
        match limiter.check(&e.event.token, weight) {
            ByteLimitDecision::Within => true,
            ByteLimitDecision::Exceeded => {
                report_dropped_events("ai_byte_rate_limited", 1);
                false
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::uuid_v7_from_datetime;
    use crate::v0_request::{DataType, ProcessedEvent, ProcessedEventMetadata};
    use common_types::CapturedEvent;
    use std::num::NonZeroU32;
    use std::sync::Arc;

    fn event_of(data_type: DataType, token: &str, distinct_id: &str, data: &str) -> ProcessedEvent {
        let timestamp = chrono::Utc::now();
        let event = CapturedEvent {
            uuid: uuid_v7_from_datetime(timestamp),
            distinct_id: distinct_id.to_string(),
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

    fn limiter(per_second: u32, burst: u32) -> Arc<ByteRateLimiter> {
        Arc::new(ByteRateLimiter::new(
            NonZeroU32::new(per_second).unwrap(),
            NonZeroU32::new(burst).unwrap(),
            None,
        ))
    }

    #[test]
    fn none_limiter_is_a_no_op() {
        let mut events = vec![event_of(DataType::AiEvents, "t", "u", "xxxxxxxxxx")];
        drop_ai_byte_limited(&mut events, None);
        assert_eq!(events.len(), 1);
    }

    #[test]
    fn under_budget_ai_events_are_kept() {
        let l = limiter(1_000, 1_000_000);
        let mut events = vec![event_of(DataType::AiEvents, "t", "u", "small")];
        drop_ai_byte_limited(&mut events, Some(&l));
        assert_eq!(events.len(), 1);
    }

    #[test]
    fn over_budget_ai_events_are_dropped() {
        let l = limiter(10, 10);
        let mut events = vec![event_of(DataType::AiEvents, "t", "u", &"x".repeat(40))];
        drop_ai_byte_limited(&mut events, Some(&l));
        assert!(events.is_empty(), "over-budget AI event must be dropped");
    }

    #[test]
    fn non_ai_lanes_are_never_dropped_by_this_helper() {
        let l = limiter(10, 10);
        let mut events = vec![event_of(DataType::AnalyticsMain, "t", "u", &"x".repeat(40))];
        drop_ai_byte_limited(&mut events, Some(&l));
        assert_eq!(events.len(), 1, "AnalyticsMain must not be touched");
    }

    #[test]
    fn mixed_batch_drops_only_over_budget_ai_events() {
        // Burst 600 admits one enveloped AI event (~517 B) but not two.
        let l = limiter(10, 600);
        let mut events = vec![
            event_of(DataType::AiEvents, "t", "u", &"x".repeat(5)), // fits
            event_of(DataType::AnalyticsMain, "t", "u", &"x".repeat(99)), // untouched
            event_of(DataType::AiEvents, "t", "u", &"x".repeat(50)), // exceeds remaining
        ];
        drop_ai_byte_limited(&mut events, Some(&l));
        assert_eq!(events.len(), 2);
        assert!(events
            .iter()
            .any(|e| e.metadata.data_type == DataType::AnalyticsMain));
    }
}
