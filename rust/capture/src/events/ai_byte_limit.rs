//! Drops over-budget events on whichever `DataType` carries `$ai_*` traffic to
//! the AI Kafka topic for this deployment's `CaptureMode`. Under `Ai` the main
//! topic *is* the AI topic, so `$ai_*` isn't diverted and rides `AnalyticsMain`
//! — that's the lane to limit there; under `Events` it's the diverted
//! `AiEvents` (leaving `AnalyticsMain` as untouched analytics). `Import` and
//! the rest are exempt: backfills are never throttled, matching the other
//! limiters.
use std::sync::Arc;

use limiters::byte_rate::{ByteLimitDecision, ByteRateLimiter};

use crate::config::CaptureMode;
use crate::prometheus::report_dropped_events;
use crate::v0_request::{DataType, ProcessedEvent};

/// Flat allowance for the `CapturedEvent` envelope fields not in `data`.
const ENVELOPE_WEIGHT_BYTES: usize = 512;

/// The `DataType` this helper should charge bytes against for `mode`, or
/// `None` if `mode` should never be byte-limited (see module doc).
fn ai_lane_target(mode: CaptureMode) -> Option<DataType> {
    match mode {
        CaptureMode::Ai => Some(DataType::AnalyticsMain),
        CaptureMode::Events => Some(DataType::AiEvents),
        CaptureMode::Recordings | CaptureMode::Import => None,
    }
}

pub fn drop_ai_byte_limited(
    events: &mut Vec<ProcessedEvent>,
    limiter: Option<&Arc<ByteRateLimiter>>,
    capture_mode: CaptureMode,
) {
    let Some(limiter) = limiter else {
        return;
    };
    let Some(target) = ai_lane_target(capture_mode) else {
        return;
    };
    events.retain(|e| {
        if e.metadata.data_type != target {
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
        drop_ai_byte_limited(&mut events, None, CaptureMode::Events);
        assert_eq!(events.len(), 1);
    }

    #[test]
    fn under_budget_ai_events_are_kept() {
        let l = limiter(1_000, 1_000_000);
        let mut events = vec![event_of(DataType::AiEvents, "t", "u", "small")];
        drop_ai_byte_limited(&mut events, Some(&l), CaptureMode::Events);
        assert_eq!(events.len(), 1);
    }

    #[test]
    fn over_budget_ai_events_are_dropped() {
        let l = limiter(10, 10);
        let mut events = vec![event_of(DataType::AiEvents, "t", "u", &"x".repeat(40))];
        drop_ai_byte_limited(&mut events, Some(&l), CaptureMode::Events);
        assert!(events.is_empty(), "over-budget AI event must be dropped");
    }

    #[test]
    fn non_ai_events_are_never_dropped_by_this_helper_under_events_mode() {
        let l = limiter(10, 10);
        let mut events = vec![event_of(DataType::AnalyticsMain, "t", "u", &"x".repeat(40))];
        drop_ai_byte_limited(&mut events, Some(&l), CaptureMode::Events);
        assert_eq!(events.len(), 1, "AnalyticsMain must not be touched");
    }

    #[test]
    fn mixed_batch_drops_only_over_budget_ai_events_under_events_mode() {
        // Burst 600 admits one enveloped AI event (~517 B) but not two.
        let l = limiter(10, 600);
        let mut events = vec![
            event_of(DataType::AiEvents, "t", "u", &"x".repeat(5)), // fits
            event_of(DataType::AnalyticsMain, "t", "u", &"x".repeat(99)), // untouched
            event_of(DataType::AiEvents, "t", "u", &"x".repeat(50)), // exceeds remaining
        ];
        drop_ai_byte_limited(&mut events, Some(&l), CaptureMode::Events);
        assert_eq!(events.len(), 2);
        assert!(events
            .iter()
            .any(|e| e.metadata.data_type == DataType::AnalyticsMain));
    }

    #[test]
    fn ai_mode_limits_analytics_main_not_ai_events() {
        // The gate is keyed on CaptureMode, so AiEvents (which can't occur here) stays untouched.
        let l = limiter(10, 10);
        let mut events = vec![
            event_of(DataType::AnalyticsMain, "t", "u", &"x".repeat(40)), // over budget
            event_of(DataType::AiEvents, "t", "u", &"x".repeat(40)),      // untouched
        ];
        drop_ai_byte_limited(&mut events, Some(&l), CaptureMode::Ai);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].metadata.data_type, DataType::AiEvents);
    }

    #[test]
    fn ai_mode_keeps_small_analytics_main_events() {
        let l = limiter(1_000, 1_000_000);
        let mut events = vec![event_of(DataType::AnalyticsMain, "t", "u", "small")];
        drop_ai_byte_limited(&mut events, Some(&l), CaptureMode::Ai);
        assert_eq!(events.len(), 1);
    }

    #[test]
    fn import_mode_never_throttles() {
        let l = limiter(10, 10);
        let mut events = vec![
            event_of(DataType::AiEvents, "t", "u", &"x".repeat(40)),
            event_of(DataType::AnalyticsMain, "t", "u", &"x".repeat(40)),
        ];
        drop_ai_byte_limited(&mut events, Some(&l), CaptureMode::Import);
        assert_eq!(events.len(), 2, "import mode must never drop events");
    }

    #[test]
    fn recordings_mode_never_throttles() {
        let l = limiter(10, 10);
        let mut events = vec![event_of(DataType::AnalyticsMain, "t", "u", &"x".repeat(40))];
        drop_ai_byte_limited(&mut events, Some(&l), CaptureMode::Recordings);
        assert_eq!(events.len(), 1);
    }
}
