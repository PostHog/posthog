//! Pipeline and lane — an event's address, and the one place it is decided.
//!
//! [`resolve`] folds the intent stamped on [`ProcessedEventMetadata`] during
//! processing (restrictions, overflow reasons, the historical flag) through
//! one precedence chain — dlq > custom > historical > overflow > main — and
//! returns an [`AddressDecision`]: the [`Address`] the event publishes to and
//! the customer-facing [`OrderingGuarantee`] the sink realizes as a partition
//! key. The decision is pure — no counters, no headers, no I/O; side effects
//! are implied by the address and applied by the layer that realizes it.

use crate::api::CaptureError;
use crate::ordering::{person_ordering, OrderingGuarantee};
use crate::v0_request::{DataType, OverflowReason, ProcessedEventMetadata};

/// Pipeline from [`DataType`], lane from [`resolve`]. Each pipeline names only
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
/// upstream by the pipeline) and the AI overflow valve — the one piece of
/// deployment config that changes a routing decision rather than a topic
/// name. Side effects are not part of the decision: the dlq header set and
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

/// Decide an event's address from its metadata. Consulted by the sink, which
/// resolves the address to a topic string and the ordering guarantee to a
/// partition key, and applies the address-implied side effects. A replay
/// event with no session id is rejected here, so every returned decision is
/// realizable by the sink.
pub fn resolve(
    metadata: &ProcessedEventMetadata,
    ai_events_overflow_armed: bool,
) -> Result<AddressDecision, CaptureError> {
    match metadata.data_type {
        DataType::SnapshotMain => resolve_session_replay(metadata),
        DataType::AnalyticsMain
        | DataType::AnalyticsHistorical
        | DataType::ClientIngestionWarning
        | DataType::HeatmapMain
        | DataType::ExceptionErrorTracking
        | DataType::AiEvents => Ok(resolve_analytics(metadata, ai_events_overflow_armed)),
    }
}

/// DLQ and custom-topic redirects take priority over every lane decision, and
/// both key on the event key.
fn redirect(metadata: &ProcessedEventMetadata) -> Option<AddressDecision> {
    let address = if metadata.redirect_to_dlq {
        Address::Dlq
    } else {
        Address::Custom(metadata.redirect_to_topic.clone()?)
    };
    Some(AddressDecision::redirect(address))
}

/// A restriction's `force_overflow` takes priority over a stamped
/// `overflow_reason`.
fn analytics_main(metadata: &ProcessedEventMetadata) -> (AnalyticsLane, OrderingGuarantee) {
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

/// Valve armed: the AI lanes route overflow like analytics, except that a
/// burst may spread while person processing is on — the AI consumer reads
/// persons without writing them, so keyless person-on records cause no
/// person-update contention there. Valve unarmed: AI events never overflow —
/// force_overflow and stamped reasons are deliberately ignored. The default
/// route keeps the event key regardless of skip_person_processing.
fn ai(metadata: &ProcessedEventMetadata, armed: bool) -> (AiLane, OrderingGuarantee) {
    if !armed {
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

fn resolve_analytics(
    metadata: &ProcessedEventMetadata,
    ai_events_overflow_armed: bool,
) -> AddressDecision {
    if let Some(decision) = redirect(metadata) {
        return decision;
    }
    match metadata.data_type {
        // Historical events never overflow — force_overflow and
        // overflow_reason are deliberately ignored here.
        DataType::AnalyticsHistorical => AddressDecision::lane(
            PipelineLane::Analytics(AnalyticsLane::Historical),
            OrderingGuarantee::PerDistinctId,
        ),
        DataType::AnalyticsMain => {
            let (lane, ordering) = analytics_main(metadata);
            AddressDecision::lane(PipelineLane::Analytics(lane), ordering)
        }
        DataType::AiEvents => {
            let (lane, ordering) = ai(metadata, ai_events_overflow_armed);
            AddressDecision::lane(PipelineLane::Ai(lane), ordering)
        }
        // A ForceOverflow restriction can stamp `force_overflow` on these
        // events. Their lane type has no overflow, so the stamp is ignored and
        // the event publishes to main.
        DataType::ClientIngestionWarning => AddressDecision::lane(
            PipelineLane::Warnings(BasicLane::Main),
            OrderingGuarantee::PerDistinctId,
        ),
        DataType::HeatmapMain => AddressDecision::lane(
            PipelineLane::Heatmaps(BasicLane::Main),
            OrderingGuarantee::PerDistinctId,
        ),
        DataType::ExceptionErrorTracking => AddressDecision::lane(
            PipelineLane::ErrorTracking(BasicLane::Main),
            OrderingGuarantee::PerDistinctId,
        ),
        DataType::SnapshotMain => unreachable!("snapshots resolve as session replay"),
    }
}

fn resolve_session_replay(
    metadata: &ProcessedEventMetadata,
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
    use rstest::rstest;

    fn meta(data_type: DataType) -> ProcessedEventMetadata {
        ProcessedEventMetadata {
            data_type,
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
        let mut m = meta(DataType::AnalyticsMain);
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
        let mut m = meta(DataType::AnalyticsMain);
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
    #[case(DataType::AnalyticsMain, PipelineLane::Analytics(AnalyticsLane::Main))]
    #[case(
        DataType::AnalyticsHistorical,
        PipelineLane::Analytics(AnalyticsLane::Historical)
    )]
    #[case(
        DataType::ClientIngestionWarning,
        PipelineLane::Warnings(BasicLane::Main)
    )]
    #[case(DataType::HeatmapMain, PipelineLane::Heatmaps(BasicLane::Main))]
    #[case(
        DataType::ExceptionErrorTracking,
        PipelineLane::ErrorTracking(BasicLane::Main)
    )]
    #[case(DataType::AiEvents, PipelineLane::Ai(AiLane::Main))]
    #[case(DataType::SnapshotMain, PipelineLane::Replay(SessionReplayLane::Main))]
    fn per_datatype_addresses(#[case] data_type: DataType, #[case] expected_lane: PipelineLane) {
        let m = meta(data_type);
        let d = resolve(&m, false).unwrap();
        assert_eq!(
            d.address,
            lane(expected_lane),
            "wrong address for {data_type:?}"
        );
    }

    #[rstest]
    #[case(
        DataType::ClientIngestionWarning,
        PipelineLane::Warnings(BasicLane::Main)
    )]
    #[case(DataType::HeatmapMain, PipelineLane::Heatmaps(BasicLane::Main))]
    #[case(
        DataType::ExceptionErrorTracking,
        PipelineLane::ErrorTracking(BasicLane::Main)
    )]
    fn single_lane_pipelines_ignore_overflow_intent(
        #[case] data_type: DataType,
        #[case] main: PipelineLane,
    ) {
        let mut m = meta(data_type);
        m.force_overflow = true;
        m.overflow_reason = Some(OverflowReason::ForceLimited);
        assert_eq!(
            resolve(&m, true).unwrap().address,
            lane(main),
            "overflow intent must not move {data_type:?} off its main lane"
        );
    }

    #[test]
    fn analytics_main_overflow_ordering() {
        // force_overflow -> overflow lane; key policy follows skip_person.
        let mut m = meta(DataType::AnalyticsMain);
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
        let base = meta(DataType::AnalyticsMain);

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
        DataType::AnalyticsMain,
        PipelineLane::Analytics(AnalyticsLane::Overflow)
    )]
    #[case::ai(DataType::AiEvents, PipelineLane::Ai(AiLane::Overflow))]
    fn person_processing_off_outranks_preserve_locality(
        #[case] data_type: DataType,
        #[case] overflow: PipelineLane,
    ) {
        let armed = data_type == DataType::AiEvents;
        let mut m = meta(data_type);
        m.overflow_reason = Some(OverflowReason::RateLimited {
            preserve_locality: true,
        });

        assert_eq!(
            resolve(&m, armed).unwrap().ordering,
            OrderingGuarantee::PerDistinctId,
            "locality is preserved while person processing is on"
        );

        m.skip_person_processing = true;
        assert_eq!(
            resolve(&m, armed).unwrap(),
            AddressDecision {
                address: lane(overflow),
                ordering: OrderingGuarantee::None,
            }
        );
    }

    #[test]
    fn ai_events_overflow_gated_on_valve() {
        // Valve unarmed: force_overflow and stamped reasons are ignored — the
        // AI lane never overflows and keeps its event key.
        let mut m = meta(DataType::AiEvents);
        m.force_overflow = true;
        assert_eq!(
            resolve(&m, false).unwrap(),
            AddressDecision {
                address: lane(PipelineLane::Ai(AiLane::Main)),
                ordering: OrderingGuarantee::PerDistinctId,
            }
        );

        // Valve armed: mirrors the analytics main lane's overflow handling.
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

        let mut force_limited = meta(DataType::AiEvents);
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
        let mut m = meta(DataType::AiEvents);
        m.skip_person_processing = true;
        for armed in [false, true] {
            assert_eq!(
                resolve(&m, armed).unwrap(),
                AddressDecision {
                    address: lane(PipelineLane::Ai(AiLane::Main)),
                    ordering: OrderingGuarantee::PerDistinctId,
                },
                "armed={armed}"
            );
        }
    }

    #[test]
    fn snapshot_routing_keeps_per_session_ordering() {
        let mut m = meta(DataType::SnapshotMain);
        assert_eq!(
            resolve(&m, false).unwrap(),
            AddressDecision {
                address: lane(PipelineLane::Replay(SessionReplayLane::Main)),
                ordering: OrderingGuarantee::PerSession,
            }
        );

        m.force_overflow = true;
        assert_eq!(
            resolve(&m, false).unwrap().address,
            lane(PipelineLane::Replay(SessionReplayLane::Overflow))
        );
        assert_eq!(
            resolve(&m, false).unwrap().ordering,
            OrderingGuarantee::PerSession
        );

        m.force_overflow = false;
        m.overflow_reason = Some(OverflowReason::ReplayLimited);
        assert_eq!(
            resolve(&m, false).unwrap().address,
            lane(PipelineLane::Replay(SessionReplayLane::Overflow))
        );
    }

    /// A replay event with no session id has no realizable address — the
    /// decision itself rejects, rather than handing the sink a `PerSession`
    /// guarantee it cannot key.
    #[test]
    fn snapshot_without_session_id_is_rejected() {
        let mut m = meta(DataType::SnapshotMain);
        m.session_id = None;
        assert!(matches!(
            resolve(&m, false),
            Err(CaptureError::MissingSessionId)
        ));

        // A dlq redirect keys on the event key, so it stays realizable
        // without a session id.
        m.redirect_to_dlq = true;
        assert_eq!(resolve(&m, false).unwrap().address, Address::Dlq);
    }
}
