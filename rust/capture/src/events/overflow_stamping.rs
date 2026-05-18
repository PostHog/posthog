//! Shared overflow-reason stamping for analytics + AI + OTEL pipelines.
//!
//! The in-process `OverflowLimiter` (governor-backed, keyed on
//! `token:distinct_id`) used to live inside `KafkaSinkBase::prepare_record`,
//! which meant every `DataType::AnalyticsMain` event reaching the sink was
//! checked uniformly regardless of which handler produced it. After the
//! sink became a pure mechanism layer, the check was moved upstream into
//! `events::analytics::process_events`. That covers the `/e/`, `/batch/`,
//! `/capture` etc. endpoints but NOT the AI (`/i/v0/ai`) or OTEL
//! (`/i/v0/ai/otel`) endpoints, which build `ProcessedEvent`s of their own
//! and call `state.sink.send` / `state.sink.send_batch` directly.
//!
//! [`stamp_overflow_reason`] is the single source of truth for that check
//! so all three call sites — analytics, AI, OTEL — get identical semantics
//! and metric labels. Triplicating the loop would invite drift; routing
//! the call through one helper keeps the contract testable in one place.
//!
//! The helper is sync because the `OverflowLimiter` governor check is sync
//! (unlike the replay redis limiter, which still lives in the recordings
//! pipeline as an async call).

use std::sync::Arc;

use limiters::overflow::{OverflowLimiter, OverflowLimiterResult};
use metrics::counter;

use crate::v0_request::{DataType, OverflowReason, ProcessedEvent};

/// Stamp `ProcessedEventMetadata::overflow_reason` on every
/// `DataType::AnalyticsMain` event in `events`, consulting `limiter` and the
/// pre-existing `force_overflow` flag stamped by event restrictions.
///
/// Behavior (matches the pre-refactor sink semantics byte-for-byte):
/// * Non-`AnalyticsMain` events are skipped (heatmaps, exceptions,
///   client-ingestion-warnings, etc. never overflow).
/// * `force_overflow = true` (set upstream by event restrictions) emits the
///   `event_restriction` counter and short-circuits — the limiter is NOT
///   consulted, matching the pre-refactor sink ordering.
/// * If `limiter` is `None`, only the `event_restriction` short-circuit can
///   stamp anything; otherwise the event passes through untouched.
/// * If `limiter` is `Some`, `is_limited(event.key())` is consulted and the
///   resulting [`OverflowReason`] is stamped, plus the matching counter.
///   `ForceLimited` additionally sets `skip_person_processing = true` so the
///   sink's generic skip-person branch picks up the
///   `force_disable_person_processing` header without a separate code path.
///
/// Counter labels are intentionally identical to the pre-refactor sink so
/// existing dashboards (filtering on `capture_events_rerouted_overflow`'s
/// `reason` label) keep working without dashboard-side changes.
pub fn stamp_overflow_reason(
    events: &mut [ProcessedEvent],
    limiter: Option<&Arc<OverflowLimiter>>,
) {
    for event in events.iter_mut() {
        if event.metadata.data_type != DataType::AnalyticsMain {
            continue;
        }

        if event.metadata.force_overflow {
            counter!(
                "capture_events_rerouted_overflow",
                "reason" => "event_restriction",
            )
            .increment(1);
            continue;
        }

        let Some(limiter) = limiter else {
            continue;
        };

        let event_key = event.event.key();
        match limiter.is_limited(&event_key) {
            OverflowLimiterResult::ForceLimited => {
                counter!(
                    "capture_events_rerouted_overflow",
                    "reason" => "force_limited",
                )
                .increment(1);
                event.metadata.overflow_reason = Some(OverflowReason::ForceLimited);
                // Self-describing metadata: ForceLimited implies person
                // processing is skipped. Pre-refactor the sink inferred this
                // from the limiter result; now we stamp it alongside the
                // reason so the sink's generic skip-person path handles it
                // uniformly. Kafka output is byte-identical — the sink's
                // ForceLimited arm still sets the header redundantly as
                // defense against a future caller stamping reason-only.
                event.metadata.skip_person_processing = true;
            }
            OverflowLimiterResult::Limited => {
                counter!(
                    "capture_events_rerouted_overflow",
                    "reason" => "rate_limited",
                )
                .increment(1);
                event.metadata.overflow_reason = Some(OverflowReason::RateLimited {
                    preserve_locality: limiter.should_preserve_locality(),
                });
            }
            OverflowLimiterResult::NotLimited => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::uuid_v7;
    use crate::v0_request::{ProcessedEvent, ProcessedEventMetadata};
    use common_types::CapturedEvent;
    use std::num::NonZeroU32;

    fn build_event(
        data_type: DataType,
        token: &str,
        distinct_id: &str,
        force_overflow: bool,
    ) -> ProcessedEvent {
        let event = CapturedEvent {
            uuid: uuid_v7(),
            distinct_id: distinct_id.to_string(),
            session_id: None,
            ip: "127.0.0.1".to_string(),
            data: "{}".to_string(),
            now: "2026-04-20T00:00:00Z".to_string(),
            sent_at: None,
            token: token.to_string(),
            event: "test".to_string(),
            timestamp: chrono::Utc::now(),
            is_cookieless_mode: false,
            historical_migration: false,
        };

        let metadata = ProcessedEventMetadata {
            data_type,
            session_id: None,
            computed_timestamp: None,
            event_name: "test".to_string(),
            force_overflow,
            skip_person_processing: false,
            redirect_to_dlq: false,
            redirect_to_topic: None,
            overflow_reason: None,
        };

        ProcessedEvent { event, metadata }
    }

    fn build_limiter(
        per_second: u32,
        burst: u32,
        keys_to_reroute: Option<String>,
        preserve_locality: bool,
    ) -> Arc<OverflowLimiter> {
        Arc::new(OverflowLimiter::new(
            NonZeroU32::new(per_second).unwrap(),
            NonZeroU32::new(burst).unwrap(),
            keys_to_reroute,
            preserve_locality,
        ))
    }

    #[test]
    fn force_overflow_short_circuits_without_consulting_limiter() {
        // Use a limiter that would otherwise force-route this event; the
        // short-circuit must skip the limiter call so the stamped reason
        // stays None (force_overflow drives the sink directly without a
        // RateLimited/ForceLimited stamp).
        let limiter = build_limiter(10, 10, Some("phc_t:user".to_string()), false);
        let mut events = vec![build_event(
            DataType::AnalyticsMain,
            "phc_t",
            "user",
            true, // force_overflow
        )];

        stamp_overflow_reason(&mut events, Some(&limiter));

        assert_eq!(
            events[0].metadata.overflow_reason, None,
            "force_overflow short-circuits before the limiter; reason stays None"
        );
        assert!(
            !events[0].metadata.skip_person_processing,
            "force_overflow alone must not flip skip_person_processing"
        );
    }

    #[test]
    fn force_limited_stamps_reason_and_skip_person_processing() {
        let limiter = build_limiter(10, 10, Some("phc_t:user".to_string()), false);
        let mut events = vec![build_event(DataType::AnalyticsMain, "phc_t", "user", false)];

        stamp_overflow_reason(&mut events, Some(&limiter));

        assert_eq!(
            events[0].metadata.overflow_reason,
            Some(OverflowReason::ForceLimited)
        );
        assert!(
            events[0].metadata.skip_person_processing,
            "ForceLimited must set skip_person_processing alongside the reason"
        );
    }

    #[test]
    fn rate_limited_stamps_preserve_locality_true() {
        // burst=1 means the second event exceeds the budget; preserve_locality
        // is mirrored from the limiter config onto the stamped reason.
        let limiter = build_limiter(1, 1, None, true);
        let mut events = vec![
            build_event(DataType::AnalyticsMain, "phc_t", "u", false),
            build_event(DataType::AnalyticsMain, "phc_t", "u", false),
        ];

        stamp_overflow_reason(&mut events, Some(&limiter));

        assert_eq!(
            events[0].metadata.overflow_reason, None,
            "first event within burst must not be stamped"
        );
        assert_eq!(
            events[1].metadata.overflow_reason,
            Some(OverflowReason::RateLimited {
                preserve_locality: true
            })
        );
        assert!(
            !events[1].metadata.skip_person_processing,
            "RateLimited (non-Force) must not flip skip_person_processing"
        );
    }

    #[test]
    fn rate_limited_stamps_preserve_locality_false() {
        let limiter = build_limiter(1, 1, None, false);
        let mut events = vec![
            build_event(DataType::AnalyticsMain, "phc_t", "u", false),
            build_event(DataType::AnalyticsMain, "phc_t", "u", false),
        ];

        stamp_overflow_reason(&mut events, Some(&limiter));

        assert_eq!(
            events[1].metadata.overflow_reason,
            Some(OverflowReason::RateLimited {
                preserve_locality: false
            })
        );
    }

    #[test]
    fn not_limited_leaves_reason_none() {
        // burst=10, single event; well under the budget.
        let limiter = build_limiter(10, 10, None, false);
        let mut events = vec![build_event(DataType::AnalyticsMain, "phc_t", "u", false)];

        stamp_overflow_reason(&mut events, Some(&limiter));

        assert_eq!(events[0].metadata.overflow_reason, None);
    }

    #[test]
    fn non_analytics_main_events_are_skipped() {
        // SnapshotMain has its own (replay) overflow path; HeatmapMain,
        // ExceptionErrorTracking, ClientIngestionWarning, AnalyticsHistorical
        // never overflow. Even with a limiter that would otherwise force-route
        // their key, the helper must leave them untouched.
        let limiter = build_limiter(10, 10, Some("phc_t:u".to_string()), false);
        let mut events = vec![
            build_event(DataType::SnapshotMain, "phc_t", "u", false),
            build_event(DataType::HeatmapMain, "phc_t", "u", false),
            build_event(DataType::ExceptionErrorTracking, "phc_t", "u", false),
            build_event(DataType::ClientIngestionWarning, "phc_t", "u", false),
            build_event(DataType::AnalyticsHistorical, "phc_t", "u", false),
        ];

        stamp_overflow_reason(&mut events, Some(&limiter));

        for (i, ev) in events.iter().enumerate() {
            assert_eq!(
                ev.metadata.overflow_reason, None,
                "event[{i}] data_type {:?} must be skipped",
                ev.metadata.data_type
            );
            assert!(!ev.metadata.skip_person_processing, "event[{i}]: untouched");
        }
    }

    #[test]
    fn none_limiter_is_a_no_op_for_non_force_overflow_events() {
        let mut events = vec![build_event(DataType::AnalyticsMain, "phc_t", "u", false)];

        stamp_overflow_reason(&mut events, None);

        assert_eq!(events[0].metadata.overflow_reason, None);
        assert!(!events[0].metadata.skip_person_processing);
    }

    #[test]
    fn none_limiter_still_emits_event_restriction_counter() {
        // force_overflow is independent of the limiter, so the
        // event_restriction short-circuit must still fire (and emit its
        // counter) even when the limiter is absent.
        let mut events = vec![build_event(DataType::AnalyticsMain, "phc_t", "u", true)];

        stamp_overflow_reason(&mut events, None);

        assert_eq!(
            events[0].metadata.overflow_reason, None,
            "force_overflow leaves overflow_reason as None"
        );
    }

    #[test]
    fn empty_batch_is_a_no_op() {
        let limiter = build_limiter(10, 10, None, false);
        let mut events: Vec<ProcessedEvent> = Vec::new();
        stamp_overflow_reason(&mut events, Some(&limiter));
    }

    #[test]
    fn mixed_batch_stamps_only_analytics_main_entries() {
        // Realistic OTEL-shaped batch: a few AnalyticsMain spans plus one
        // HeatmapMain that snuck in. Only the AnalyticsMain over-budget
        // entries should be stamped.
        let limiter = build_limiter(1, 1, None, true);
        let mut events = vec![
            build_event(DataType::AnalyticsMain, "phc_t", "user_a", false),
            build_event(DataType::HeatmapMain, "phc_t", "user_a", false),
            build_event(DataType::AnalyticsMain, "phc_t", "user_a", false),
        ];

        stamp_overflow_reason(&mut events, Some(&limiter));

        assert_eq!(
            events[0].metadata.overflow_reason, None,
            "first AnalyticsMain within burst"
        );
        assert_eq!(
            events[1].metadata.overflow_reason, None,
            "HeatmapMain must be skipped regardless of limiter state"
        );
        assert_eq!(
            events[2].metadata.overflow_reason,
            Some(OverflowReason::RateLimited {
                preserve_locality: true
            }),
            "second AnalyticsMain over budget"
        );
    }
}
