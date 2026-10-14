//! Pipeline and lane — an event's address, and the one place it is decided.
//!
//! Each kind's [`Route::resolve`](crate::kind::Route::resolve) folds the intent
//! stamped on [`ProcessedEventMetadata`] during processing (restrictions,
//! overflow reasons, the event's kind) through
//! one precedence chain — dlq > custom > historical > overflow > main — and
//! returns an [`AddressDecision`]: the [`Address`] the event publishes to and
//! the customer-facing [`OrderingGuarantee`] the sink realizes as a partition
//! key. The decision is pure — no counters, no headers, no I/O; side effects
//! are implied by the address and applied by the layer that realizes it.

use crate::api::CaptureError;
use crate::kind::{AiKind, AnalyticsKind, AnalyticsVariant, SnapshotKind};
use crate::ordering::{person_ordering, OrderingGuarantee};
use crate::v0_request::{OverflowReason, ProcessedEventMetadata};

/// Pipeline from the event kind, lane from its resolve. Each pipeline names only
/// the lanes it has, so an address no output backs cannot be built.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum PipelineLane {
    Analytics(AnalyticsLane),
    Ai(AiLane),
    Heatmaps(BasicLane),
    Warnings(BasicLane),
    ErrorTracking(BasicLane),
    Replay(SessionReplayLane),
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum AnalyticsLane {
    Main,
    Overflow,
    Historical,
}

/// No historical lane: the AI divert wins over historical rerouting.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum AiLane {
    Main,
    Overflow,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum SessionReplayLane {
    Main,
    Overflow,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum BasicLane {
    Main,
}

/// Where an event publishes: a lane of its pipeline, or an admin redirect
/// outside the pipeline-lane model. A redirect carries no pipeline: every
/// pipeline shares one dlq output, and a custom redirect names its own topic.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Address {
    Lane(PipelineLane),
    Dlq,
    Custom(String),
}

/// The pure routing decision for a single event: which address, and which
/// ordering guarantee. Depends only on [`ProcessedEventMetadata`] (stamped
/// upstream by the pipeline) and whether the deployment has an AI overflow
/// lane — the one piece of deployment config that changes a routing decision
/// rather than a topic name. Side effects are not part of the decision: the dlq header set and
/// the reroute counters follow from the address, and the person-processing
/// header follows from
/// [`ProcessedEventMetadata::person_processing_disabled`] — the stamped flag,
/// or a `ForceLimited` reason, which implies the skip on its own.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AddressDecision {
    pub address: Address,
    pub ordering: OrderingGuarantee,
}

impl AddressDecision {
    fn lane(lane: PipelineLane, ordering: OrderingGuarantee) -> Self {
        Self {
            address: Address::Lane(lane),
            ordering,
        }
    }

    /// Both admin redirects key on the event key.
    fn redirect(address: Address) -> Self {
        Self {
            address,
            ordering: OrderingGuarantee::PerDistinctId,
        }
    }
}

/// DLQ and custom-topic redirects take priority over every lane decision, and
/// both key on the event key.
fn redirect<K>(metadata: &ProcessedEventMetadata<K>) -> Option<AddressDecision> {
    let address = if metadata.redirect_to_dlq {
        Address::Dlq
    } else {
        Address::Custom(metadata.redirect_to_topic.clone()?)
    };
    Some(AddressDecision::redirect(address))
}

/// A restriction's `force_overflow` takes priority over a stamped
/// `overflow_reason`.
fn analytics_main<K>(metadata: &ProcessedEventMetadata<K>) -> (AnalyticsLane, OrderingGuarantee) {
    if metadata.force_overflow {
        return (
            AnalyticsLane::Overflow,
            person_ordering(metadata.person_processing_disabled()),
        );
    }
    match &metadata.overflow_reason {
        Some(OverflowReason::ForceLimited) => (AnalyticsLane::Overflow, OrderingGuarantee::None),
        // The person flag alone decides the key here, in both directions. A
        // burst keeps its key while person processing is on — the overflow
        // consumer updates persons keyed on distinct id, so spreading one
        // distinct id across partitions turns a hot key into contended
        // person-row updates — which makes the locality preference irrelevant
        // on this lane. And a key whose person processing is already off (the
        // global rate limiter stamps its verdict before the overflow limiter
        // overwrites the reason) must not get its partition back.
        Some(OverflowReason::RateLimited { .. }) => (
            AnalyticsLane::Overflow,
            person_ordering(metadata.person_processing_disabled()),
        ),
        // ReplayLimited is stamped only by the recordings pipeline, so an
        // analytics event cannot carry it — the shared OverflowReason enum
        // forces the arm, which treats the impossible stamp as unstamped.
        Some(OverflowReason::ReplayLimited) | None => (
            AnalyticsLane::Main,
            person_ordering(metadata.person_processing_disabled()),
        ),
    }
}

/// The AI lanes route overflow like analytics, except that a burst may spread
/// while person processing is on — the AI consumer reads persons without
/// writing them, so keyless person-on records cause no person-update
/// contention there. Without an overflow lane AI events never overflow, and
/// the default route keeps the event key regardless of skip_person_processing.
fn ai<K>(
    metadata: &ProcessedEventMetadata<K>,
    has_ai_overflow_lane: bool,
) -> (AiLane, OrderingGuarantee) {
    if !has_ai_overflow_lane {
        return (AiLane::Main, OrderingGuarantee::PerDistinctId);
    }
    if metadata.force_overflow {
        return (
            AiLane::Overflow,
            person_ordering(metadata.person_processing_disabled()),
        );
    }
    match &metadata.overflow_reason {
        Some(OverflowReason::ForceLimited) => (AiLane::Overflow, OrderingGuarantee::None),
        Some(OverflowReason::RateLimited {
            preserve_locality: true,
        }) => (
            AiLane::Overflow,
            // Same precedence as the analytics overflow lane above.
            person_ordering(metadata.person_processing_disabled()),
        ),
        Some(OverflowReason::RateLimited {
            preserve_locality: false,
        }) => (AiLane::Overflow, OrderingGuarantee::None),
        // ReplayLimited cannot be stamped on the AI lane either; treated as
        // unstamped, as above.
        Some(OverflowReason::ReplayLimited) | None => {
            (AiLane::Main, OrderingGuarantee::PerDistinctId)
        }
    }
}

pub(crate) fn resolve_analytics<A: AnalyticsVariant>(
    metadata: &ProcessedEventMetadata<AnalyticsKind<A>>,
    has_ai_overflow_lane: bool,
) -> AddressDecision {
    if let Some(decision) = redirect(metadata) {
        return decision;
    }
    match metadata.kind {
        // Historical events never overflow — force_overflow and
        // overflow_reason are deliberately ignored here.
        AnalyticsKind::Analytics(analytics) if analytics.is_historical() => AddressDecision::lane(
            PipelineLane::Analytics(AnalyticsLane::Historical),
            OrderingGuarantee::PerDistinctId,
        ),
        AnalyticsKind::Analytics(_) => {
            let (lane, ordering) = analytics_main(metadata);
            AddressDecision::lane(PipelineLane::Analytics(lane), ordering)
        }
        AnalyticsKind::Ai => {
            let (lane, ordering) = ai(metadata, has_ai_overflow_lane);
            AddressDecision::lane(PipelineLane::Ai(lane), ordering)
        }
        // A ForceOverflow restriction can stamp `force_overflow` on these
        // events. Their lane type has no overflow, so the stamp is ignored and
        // the event publishes to main.
        AnalyticsKind::ClientWarning => AddressDecision::lane(
            PipelineLane::Warnings(BasicLane::Main),
            OrderingGuarantee::PerDistinctId,
        ),
        AnalyticsKind::Heatmap => AddressDecision::lane(
            PipelineLane::Heatmaps(BasicLane::Main),
            OrderingGuarantee::PerDistinctId,
        ),
        AnalyticsKind::Exception => AddressDecision::lane(
            PipelineLane::ErrorTracking(BasicLane::Main),
            OrderingGuarantee::PerDistinctId,
        ),
    }
}

pub(crate) fn resolve_ai(
    metadata: &ProcessedEventMetadata<AiKind>,
    has_ai_overflow_lane: bool,
) -> AddressDecision {
    if let Some(decision) = redirect(metadata) {
        return decision;
    }
    let (lane, ordering) = ai(metadata, has_ai_overflow_lane);
    AddressDecision::lane(PipelineLane::Ai(lane), ordering)
}

/// A replay event with no session id is rejected here, so every returned
/// decision is realizable by the sink.
pub(crate) fn resolve_session_replay(
    metadata: &ProcessedEventMetadata<SnapshotKind>,
) -> Result<AddressDecision, CaptureError> {
    if let Some(decision) = redirect(metadata) {
        return Ok(decision);
    }
    // Partition key is always session_id for replay to keep per-session
    // ordering on the overflow lane; a missing id makes the decision
    // unrealizable, so it is rejected as part of the decision.
    if metadata.session_id.is_none() {
        return Err(CaptureError::MissingSessionId);
    }
    let lane = if metadata.force_overflow
        || matches!(
            metadata.overflow_reason,
            Some(OverflowReason::ReplayLimited)
        ) {
        SessionReplayLane::Overflow
    } else {
        SessionReplayLane::Main
    };
    Ok(AddressDecision::lane(
        PipelineLane::Replay(lane),
        OrderingGuarantee::PerSession,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kind::MainOrHistorical;
    use rstest::rstest;

    const MAIN: AnalyticsKind<MainOrHistorical> = AnalyticsKind::Analytics(MainOrHistorical::Main);

    fn resolve(
        m: &ProcessedEventMetadata<AnalyticsKind<MainOrHistorical>>,
        has_ai_overflow_lane: bool,
    ) -> Result<AddressDecision, CaptureError> {
        Ok(resolve_analytics(m, has_ai_overflow_lane))
    }

    fn meta<K>(kind: K) -> ProcessedEventMetadata<K> {
        ProcessedEventMetadata {
            kind,
            session_id: Some("session123".to_string()),
            computed_timestamp: None,
            event_name: "test_event".to_string(),
            force_overflow: false,
            skip_person_processing: false,
            redirect_to_dlq: false,
            redirect_to_topic: None,
            skip_heatmap_processing: false,
            overflow_reason: None,
            distinct_id_truncated_from: None,
        }
    }

    fn lane(lane: PipelineLane) -> Address {
        Address::Lane(lane)
    }

    #[test]
    fn dlq_wins_over_custom_topic_and_datatype() {
        // redirect_to_dlq set alongside redirect_to_topic and an overflow
        // reason: DLQ still wins, keyed on the event key, with the DLQ effect.
        let mut m = meta(MAIN);
        m.redirect_to_dlq = true;
        m.redirect_to_topic = Some("custom".to_string());
        m.force_overflow = true;
        assert_eq!(
            resolve(&m, false).unwrap(),
            AddressDecision {
                address: Address::Dlq,
                ordering: OrderingGuarantee::PerDistinctId,
            }
        );
    }

    #[test]
    fn custom_topic_wins_over_datatype() {
        // Custom-topic redirect beats per-datatype/overflow routing (but not DLQ).
        let mut m = meta(MAIN);
        m.redirect_to_topic = Some("my_topic".to_string());
        m.force_overflow = true;
        assert_eq!(
            resolve(&m, false).unwrap(),
            AddressDecision {
                address: Address::Custom("my_topic".to_string()),
                ordering: OrderingGuarantee::PerDistinctId,
            }
        );
    }

    #[rstest]
    #[case(
        AnalyticsKind::Analytics(MainOrHistorical::Main),
        PipelineLane::Analytics(AnalyticsLane::Main)
    )]
    #[case(
        AnalyticsKind::Analytics(MainOrHistorical::Historical),
        PipelineLane::Analytics(AnalyticsLane::Historical)
    )]
    #[case(AnalyticsKind::ClientWarning, PipelineLane::Warnings(BasicLane::Main))]
    #[case(AnalyticsKind::Heatmap, PipelineLane::Heatmaps(BasicLane::Main))]
    #[case(AnalyticsKind::Exception, PipelineLane::ErrorTracking(BasicLane::Main))]
    #[case(AnalyticsKind::Ai, PipelineLane::Ai(AiLane::Main))]
    fn per_datatype_addresses(
        #[case] kind: AnalyticsKind<MainOrHistorical>,
        #[case] expected_lane: PipelineLane,
    ) {
        let m = meta(kind);
        let d = resolve(&m, false).unwrap();
        assert_eq!(d.address, lane(expected_lane), "wrong address for {kind:?}");
    }

    #[rstest]
    #[case(AnalyticsKind::ClientWarning, PipelineLane::Warnings(BasicLane::Main))]
    #[case(AnalyticsKind::Heatmap, PipelineLane::Heatmaps(BasicLane::Main))]
    #[case(AnalyticsKind::Exception, PipelineLane::ErrorTracking(BasicLane::Main))]
    fn single_lane_pipelines_ignore_overflow_intent(
        #[case] kind: AnalyticsKind<MainOrHistorical>,
        #[case] main: PipelineLane,
    ) {
        let mut m = meta(kind);
        m.force_overflow = true;
        m.overflow_reason = Some(OverflowReason::ForceLimited);
        assert_eq!(
            resolve(&m, true).unwrap().address,
            lane(main),
            "overflow intent must not move {kind:?} off its main lane"
        );
    }

    #[test]
    fn analytics_main_overflow_ordering() {
        // force_overflow -> overflow lane; key policy follows skip_person.
        let mut m = meta(MAIN);
        m.force_overflow = true;
        assert_eq!(
            resolve(&m, false).unwrap().ordering,
            OrderingGuarantee::PerDistinctId
        );
        m.skip_person_processing = true;
        assert_eq!(
            resolve(&m, false).unwrap().ordering,
            OrderingGuarantee::None
        );
        assert_eq!(
            resolve(&m, false).unwrap().address,
            lane(PipelineLane::Analytics(AnalyticsLane::Overflow))
        );
    }

    #[test]
    fn analytics_main_overflow_reason_precedence() {
        let base = meta(MAIN);

        let mut force_limited = base.clone();
        force_limited.overflow_reason = Some(OverflowReason::ForceLimited);
        assert_eq!(
            resolve(&force_limited, false).unwrap(),
            AddressDecision {
                address: lane(PipelineLane::Analytics(AnalyticsLane::Overflow)),
                ordering: OrderingGuarantee::None,
            }
        );

        let mut preserve = base.clone();
        preserve.overflow_reason = Some(OverflowReason::RateLimited {
            preserve_locality: true,
        });
        assert_eq!(
            resolve(&preserve, false).unwrap().ordering,
            OrderingGuarantee::PerDistinctId
        );
        assert_eq!(
            resolve(&preserve, false).unwrap().address,
            lane(PipelineLane::Analytics(AnalyticsLane::Overflow))
        );

        // The locality preference is irrelevant on the analytics lane: a
        // person-on burst keeps its key either way, because the overflow
        // consumer writes persons keyed on distinct id.
        let mut no_preserve = base.clone();
        no_preserve.overflow_reason = Some(OverflowReason::RateLimited {
            preserve_locality: false,
        });
        assert_eq!(
            resolve(&no_preserve, false).unwrap().ordering,
            OrderingGuarantee::PerDistinctId
        );
        assert_eq!(
            resolve(&no_preserve, false).unwrap().address,
            lane(PipelineLane::Analytics(AnalyticsLane::Overflow))
        );
        no_preserve.skip_person_processing = true;
        assert_eq!(
            resolve(&no_preserve, false).unwrap().ordering,
            OrderingGuarantee::None
        );

        // ReplayLimited cannot be stamped on analytics events (only the
        // recordings pipeline produces it); the impossible combination is
        // treated as unstamped.
        let mut replay = base;
        replay.overflow_reason = Some(OverflowReason::ReplayLimited);
        assert_eq!(
            resolve(&replay, false).unwrap().address,
            lane(PipelineLane::Analytics(AnalyticsLane::Main))
        );
    }

    /// The global rate limiter stamps `skip_person_processing` before the
    /// overflow limiter runs, and the overflow limiter overwrites the reason it
    /// stamped. Without this precedence a key the rate limiter declared too hot
    /// would go back to hashing onto a single overflow partition whenever the
    /// limiter preserves locality.
    #[rstest]
    #[case::analytics(
        AnalyticsKind::Analytics(MainOrHistorical::Main),
        PipelineLane::Analytics(AnalyticsLane::Overflow)
    )]
    #[case::ai(AnalyticsKind::Ai, PipelineLane::Ai(AiLane::Overflow))]
    fn person_processing_off_outranks_preserve_locality(
        #[case] kind: AnalyticsKind<MainOrHistorical>,
        #[case] overflow: PipelineLane,
    ) {
        let has_ai_overflow_lane = kind == AnalyticsKind::Ai;
        let mut m = meta(kind);
        m.overflow_reason = Some(OverflowReason::RateLimited {
            preserve_locality: true,
        });

        assert_eq!(
            resolve(&m, has_ai_overflow_lane).unwrap().ordering,
            OrderingGuarantee::PerDistinctId,
            "locality is preserved while person processing is on"
        );

        m.skip_person_processing = true;
        assert_eq!(
            resolve(&m, has_ai_overflow_lane).unwrap(),
            AddressDecision {
                address: lane(overflow),
                ordering: OrderingGuarantee::None,
            }
        );
    }

    #[test]
    fn ai_events_overflow_needs_an_overflow_lane() {
        // Without the lane, force_overflow and stamped reasons are ignored:
        // the AI lane never overflows and keeps its event key.
        let mut m = meta(AnalyticsKind::Ai);
        m.force_overflow = true;
        assert_eq!(
            resolve(&m, false).unwrap(),
            AddressDecision {
                address: lane(PipelineLane::Ai(AiLane::Main)),
                ordering: OrderingGuarantee::PerDistinctId,
            }
        );

        // With the lane: mirrors the analytics main lane's overflow handling.
        assert_eq!(
            resolve(&m, true).unwrap().address,
            lane(PipelineLane::Ai(AiLane::Overflow))
        );
        assert_eq!(
            resolve(&m, true).unwrap().ordering,
            OrderingGuarantee::PerDistinctId
        );
        m.skip_person_processing = true;
        assert_eq!(resolve(&m, true).unwrap().ordering, OrderingGuarantee::None);

        let mut force_limited = meta(AnalyticsKind::Ai);
        force_limited.overflow_reason = Some(OverflowReason::ForceLimited);
        assert_eq!(
            resolve(&force_limited, true).unwrap(),
            AddressDecision {
                address: lane(PipelineLane::Ai(AiLane::Overflow)),
                ordering: OrderingGuarantee::None,
            }
        );
        assert_eq!(
            resolve(&force_limited, false).unwrap().address,
            lane(PipelineLane::Ai(AiLane::Main))
        );
    }

    #[test]
    fn ai_events_default_route_keeps_event_key() {
        // skip_person_processing must not null the key on the AI default
        // route: v1 only nulls keys for Main/Overflow-shaped destinations.
        let mut m = meta(AnalyticsKind::Ai);
        m.skip_person_processing = true;
        for has_ai_overflow_lane in [false, true] {
            assert_eq!(
                resolve(&m, has_ai_overflow_lane).unwrap(),
                AddressDecision {
                    address: lane(PipelineLane::Ai(AiLane::Main)),
                    ordering: OrderingGuarantee::PerDistinctId,
                },
                "has_ai_overflow_lane={has_ai_overflow_lane}"
            );
        }
    }

    #[test]
    fn snapshot_routing_keeps_per_session_ordering() {
        let mut m = meta(SnapshotKind);
        assert_eq!(
            resolve_session_replay(&m).unwrap(),
            AddressDecision {
                address: lane(PipelineLane::Replay(SessionReplayLane::Main)),
                ordering: OrderingGuarantee::PerSession,
            }
        );

        m.force_overflow = true;
        assert_eq!(
            resolve_session_replay(&m).unwrap().address,
            lane(PipelineLane::Replay(SessionReplayLane::Overflow))
        );
        assert_eq!(
            resolve_session_replay(&m).unwrap().ordering,
            OrderingGuarantee::PerSession
        );

        m.force_overflow = false;
        m.overflow_reason = Some(OverflowReason::ReplayLimited);
        assert_eq!(
            resolve_session_replay(&m).unwrap().address,
            lane(PipelineLane::Replay(SessionReplayLane::Overflow))
        );
    }

    /// A replay event with no session id has no realizable address — the
    /// decision itself rejects, rather than handing the sink a `PerSession`
    /// guarantee it cannot key.
    #[test]
    fn snapshot_without_session_id_is_rejected() {
        let mut m = meta(SnapshotKind);
        m.session_id = None;
        assert!(matches!(
            resolve_session_replay(&m),
            Err(CaptureError::MissingSessionId)
        ));

        // A dlq redirect keys on the event key, so it stays realizable
        // without a session id.
        m.redirect_to_dlq = true;
        assert_eq!(resolve_session_replay(&m).unwrap().address, Address::Dlq);
    }
}
