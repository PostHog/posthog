//! Shared overflow-reason stamping for analytics + AI + OTEL pipelines.
//!
//! The analytics, AI (`/i/v0/ai`) and OTEL (`/i/v0/ai/otel`) endpoints each
//! build `ProcessedEvent`s of their own, and all three must reach the same
//! overflow verdict for the same event. Triplicating the loop would invite
//! drift; routing the call through one helper keeps the contract testable in
//! one place.

use std::sync::Arc;

use limiters::overflow::{ForcedOverflowKeys, OverflowLimiter, OverflowLimiterResult};
use metrics::counter;

use crate::v0_request::{DataType, OverflowReason, ProcessedEvent};

enum Lane {
    Analytics,
    Ai,
}

/// Stamp `ProcessedEventMetadata::overflow_reason` on every overflowing-lane
/// event in `events`.
///
/// The two lanes are checked differently. `AnalyticsMain` is only ever routed
/// to overflow by the operator-configured forced-key list; a hot key beyond
/// that list is the global rate limiter's business, and it stamps its own
/// verdict upstream. `AiEvents` additionally carries a per-key token bucket,
/// consulted only when its limiter is present — setup builds `ai_limiter`
/// exactly when the AI overflow valve
/// (`CAPTURE_ANALYTICS_AI_EVENTS_OVERFLOW_TOPIC`) is armed and overflow is
/// enabled, so limiter presence IS the valve here.
///
/// `force_overflow` short-circuits both lanes whether or not their check is
/// wired, because the sink honors that flag on its own and restriction
/// rerouting must survive `OVERFLOW_ENABLED=false`. Its counter can
/// over-report in one corner: a forced AI event with the valve unarmed is
/// counted here but ignored by the sink, which is the only layer that knows
/// the valve.
pub fn stamp_overflow_reason(
    events: &mut [ProcessedEvent],
    analytics_forced_keys: Option<&Arc<ForcedOverflowKeys>>,
    ai_limiter: Option<&Arc<OverflowLimiter>>,
) {
    for event in events.iter_mut() {
        let lane = match event.metadata.data_type {
            DataType::AnalyticsMain => Lane::Analytics,
            DataType::AiEvents => Lane::Ai,
            _ => continue,
        };

        if event.metadata.force_overflow {
            counter!(
                "capture_events_rerouted_overflow",
                "reason" => "event_restriction",
            )
            .increment(1);
            continue;
        }

        match lane {
            Lane::Analytics => {
                let Some(forced_keys) = analytics_forced_keys else {
                    continue;
                };
                if forced_keys.is_forced(&event.event.key()) {
                    stamp_force_limited(event);
                }
            }
            Lane::Ai => {
                let Some(limiter) = ai_limiter else {
                    continue;
                };
                match limiter.is_limited(&event.event.key()) {
                    OverflowLimiterResult::ForceLimited => stamp_force_limited(event),
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
    }
}

fn stamp_force_limited(event: &mut ProcessedEvent) {
    counter!(
        "capture_events_rerouted_overflow",
        "reason" => "force_limited",
    )
    .increment(1);
    event.metadata.overflow_reason = Some(OverflowReason::ForceLimited);
    // ForceLimited implies person processing is skipped; the sink derives that
    // from the reason itself (`person_processing_disabled`). The flag is
    // stamped alongside so pipeline-level readers of the flag see the same
    // truth.
    event.metadata.skip_person_processing = true;
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::uuid_v7_from_datetime;
    use crate::v0_request::{ProcessedEvent, ProcessedEventMetadata};
    use common_types::CapturedEvent;
    use std::num::NonZeroU32;

    fn build_event(
        data_type: DataType,
        token: &str,
        distinct_id: &str,
        force_overflow: bool,
    ) -> ProcessedEvent {
        let timestamp = chrono::Utc::now();
        let event = CapturedEvent {
            uuid: uuid_v7_from_datetime(timestamp),
            distinct_id: distinct_id.to_string(),
            session_id: None,
            ip: "127.0.0.1".to_string(),
            data: "{}".to_string(),
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
            force_overflow,
            skip_person_processing: false,
            redirect_to_dlq: false,
            redirect_to_topic: None,
            skip_heatmap_processing: false,
            overflow_reason: None,
            distinct_id_truncated_from: None,
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

    fn build_forced_keys(keys: &str) -> Arc<ForcedOverflowKeys> {
        Arc::new(ForcedOverflowKeys::new(Some(keys.to_string())))
    }

    #[test]
    fn force_overflow_short_circuits_without_consulting_forced_keys() {
        // Use a forced-key list that would otherwise route this event; the
        // short-circuit must skip the check so the stamped reason stays None
        // (force_overflow drives the sink directly without a ForceLimited
        // stamp).
        let forced_keys = build_forced_keys("phc_t:user");
        let mut events = vec![build_event(
            DataType::AnalyticsMain,
            "phc_t",
            "user",
            true, // force_overflow
        )];

        stamp_overflow_reason(&mut events, Some(&forced_keys), None);

        assert_eq!(
            events[0].metadata.overflow_reason, None,
            "force_overflow short-circuits before the forced-key check; reason stays None"
        );
        assert!(
            !events[0].metadata.skip_person_processing,
            "force_overflow alone must not flip skip_person_processing"
        );
    }

    #[test]
    fn force_limited_stamps_reason_and_skip_person_processing() {
        let forced_keys = build_forced_keys("phc_t:user");
        let mut events = vec![build_event(DataType::AnalyticsMain, "phc_t", "user", false)];

        stamp_overflow_reason(&mut events, Some(&forced_keys), None);

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
    fn unforced_analytics_key_is_never_stamped() {
        // Volume alone does not reroute the analytics lane: the global rate
        // limiter stamps hot keys upstream, this check only honors the
        // operator's forced-key list.
        let forced_keys = build_forced_keys("phc_other:u");
        let mut events = vec![
            build_event(DataType::AnalyticsMain, "phc_t", "u", false),
            build_event(DataType::AnalyticsMain, "phc_t", "u", false),
            build_event(DataType::AnalyticsMain, "phc_t", "u", false),
        ];

        stamp_overflow_reason(&mut events, Some(&forced_keys), None);

        for (i, ev) in events.iter().enumerate() {
            assert_eq!(ev.metadata.overflow_reason, None, "event[{i}]");
            assert!(!ev.metadata.skip_person_processing, "event[{i}]");
        }
    }

    #[test]
    fn non_analytics_main_events_are_skipped() {
        // SnapshotMain has its own (replay) overflow path; HeatmapMain,
        // ExceptionErrorTracking, ClientIngestionWarning, AnalyticsHistorical,
        // and AiEvents (with the AI overflow valve unarmed) never overflow.
        // Even with a forced-key list covering their key, the helper must
        // leave them untouched.
        let forced_keys = build_forced_keys("phc_t:u");
        let mut events = vec![
            build_event(DataType::SnapshotMain, "phc_t", "u", false),
            build_event(DataType::HeatmapMain, "phc_t", "u", false),
            build_event(DataType::ExceptionErrorTracking, "phc_t", "u", false),
            build_event(DataType::ClientIngestionWarning, "phc_t", "u", false),
            build_event(DataType::AnalyticsHistorical, "phc_t", "u", false),
            build_event(DataType::AiEvents, "phc_t", "u", false),
        ];

        stamp_overflow_reason(&mut events, Some(&forced_keys), None);

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
    fn absent_forced_keys_are_a_no_op_for_non_force_overflow_events() {
        let mut events = vec![build_event(DataType::AnalyticsMain, "phc_t", "u", false)];

        stamp_overflow_reason(&mut events, None, None);

        assert_eq!(events[0].metadata.overflow_reason, None);
        assert!(!events[0].metadata.skip_person_processing);
    }

    #[test]
    fn absent_forced_keys_still_emit_event_restriction_counter() {
        // force_overflow is independent of the forced-key list, so the
        // event_restriction short-circuit must still fire (and emit its
        // counter) even when the list is absent.
        let mut events = vec![build_event(DataType::AnalyticsMain, "phc_t", "u", true)];

        stamp_overflow_reason(&mut events, None, None);

        assert_eq!(
            events[0].metadata.overflow_reason, None,
            "force_overflow leaves overflow_reason as None"
        );
    }

    #[test]
    fn empty_batch_is_a_no_op() {
        let forced_keys = build_forced_keys("phc_t:u");
        let mut events: Vec<ProcessedEvent> = Vec::new();
        stamp_overflow_reason(&mut events, Some(&forced_keys), None);
    }

    #[test]
    fn mixed_batch_stamps_only_analytics_main_entries() {
        // Realistic OTEL-shaped batch: a few AnalyticsMain spans plus one
        // HeatmapMain that snuck in. Only the forced-key AnalyticsMain
        // entries should be stamped.
        let forced_keys = build_forced_keys("phc_t:user_a");
        let mut events = vec![
            build_event(DataType::AnalyticsMain, "phc_t", "user_a", false),
            build_event(DataType::HeatmapMain, "phc_t", "user_a", false),
            build_event(DataType::AnalyticsMain, "phc_t", "user_b", false),
        ];

        stamp_overflow_reason(&mut events, Some(&forced_keys), None);

        assert_eq!(
            events[0].metadata.overflow_reason,
            Some(OverflowReason::ForceLimited),
            "forced AnalyticsMain key"
        );
        assert_eq!(
            events[1].metadata.overflow_reason, None,
            "HeatmapMain must be skipped regardless of the forced-key list"
        );
        assert_eq!(
            events[2].metadata.overflow_reason, None,
            "unforced AnalyticsMain key"
        );
    }

    /// The AI lane joins overflow stamping only when its limiter is present
    /// (setup builds it exactly when the AI overflow valve is armed); absent
    /// keeps today's never-overflows behavior even for a force-routed key.
    #[rstest::rstest]
    #[case::limiter_present(true, Some(OverflowReason::ForceLimited), true)]
    #[case::limiter_absent(false, None, false)]
    fn ai_events_stamping_gated_on_limiter_presence(
        #[case] ai_limiter_present: bool,
        #[case] expected_reason: Option<OverflowReason>,
        #[case] expected_skip_person: bool,
    ) {
        let limiter = build_limiter(10, 10, Some("phc_t:u".to_string()), false);
        let ai_limiter = ai_limiter_present.then_some(&limiter);
        let mut events = vec![build_event(DataType::AiEvents, "phc_t", "u", false)];

        stamp_overflow_reason(&mut events, None, ai_limiter);

        assert_eq!(events[0].metadata.overflow_reason, expected_reason);
        assert_eq!(
            events[0].metadata.skip_person_processing,
            expected_skip_person
        );
    }

    #[rstest::rstest]
    #[case::preserving(true)]
    #[case::spreading(false)]
    fn ai_events_rate_limited_mirrors_preserve_locality(#[case] preserve_locality: bool) {
        // burst=1 means the second event exceeds the budget; the AI limiter's
        // preserve-partition-locality flag is mirrored onto the stamped reason.
        let limiter = build_limiter(1, 1, None, preserve_locality);
        let mut events = vec![
            build_event(DataType::AiEvents, "phc_t", "u", false),
            build_event(DataType::AiEvents, "phc_t", "u", false),
        ];

        stamp_overflow_reason(&mut events, None, Some(&limiter));

        assert_eq!(
            events[0].metadata.overflow_reason, None,
            "first event within burst must not be stamped"
        );
        assert_eq!(
            events[1].metadata.overflow_reason,
            Some(OverflowReason::RateLimited { preserve_locality })
        );
        assert!(
            !events[1].metadata.skip_person_processing,
            "RateLimited (non-Force) must not flip skip_person_processing"
        );
    }

    #[test]
    fn ai_lane_ignores_analytics_forced_keys_when_own_limiter_absent() {
        // A missing AI limiter means no overflow for the AI lane, even when
        // the analytics forced-key list covers the same key.
        let forced_keys = build_forced_keys("phc_t:u");
        let mut events = vec![build_event(DataType::AiEvents, "phc_t", "u", false)];

        stamp_overflow_reason(&mut events, Some(&forced_keys), None);

        assert_eq!(events[0].metadata.overflow_reason, None);
    }

    #[test]
    fn analytics_lane_ignores_the_ai_limiter() {
        // The AI limiter's per-key budget is its own: an exhausted AI budget
        // must never stamp an analytics event.
        let ai_limiter = build_limiter(1, 1, None, false);
        let mut events = vec![
            build_event(DataType::AnalyticsMain, "phc_t", "u", false),
            build_event(DataType::AnalyticsMain, "phc_t", "u", false),
        ];

        stamp_overflow_reason(&mut events, None, Some(&ai_limiter));

        assert_eq!(events[0].metadata.overflow_reason, None);
        assert_eq!(events[1].metadata.overflow_reason, None);
    }

    #[test]
    fn ai_events_force_overflow_short_circuits_when_armed() {
        // Identical to the analytics lane: a restriction-driven
        // force_overflow bypasses the limiter and leaves the reason unset;
        // the sink routes on the flag alone.
        let limiter = build_limiter(10, 10, Some("phc_t:u".to_string()), false);
        let mut events = vec![build_event(DataType::AiEvents, "phc_t", "u", true)];

        stamp_overflow_reason(&mut events, None, Some(&limiter));

        assert_eq!(events[0].metadata.overflow_reason, None);
        assert!(!events[0].metadata.skip_person_processing);
    }
}
