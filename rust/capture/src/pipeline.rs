//! Pipeline and lane — an event's address, and the one place it is decided.
//!
//! [`resolve`] folds the intent stamped on [`ProcessedEventMetadata`] during
//! processing (restrictions, overflow reasons, the historical flag) through
//! one precedence chain — dlq > custom > historical > overflow > main — and
//! returns a [`LaneDecision`]: which [`Pipeline`] the event belongs to, which
//! [`Lane`] of that pipeline it publishes to, and the customer-facing
//! [`OrderingGuarantee`] the sink realizes as a partition key. The decision is
//! pure — no counters, no headers, no I/O; side effects are implied by the
//! address and applied by the layer that realizes it.
//!
//! The sink still invokes `resolve` from its prep path and bridges the
//! decision to its configured topics; the invocation site moves up when the
//! outputs layer exists to own it (see the plan doc).

use crate::api::CaptureError;
use crate::ordering::{person_ordering, OrderingGuarantee};
use crate::v0_request::{DataType, OverflowReason, ProcessedEventMetadata};

/// The high-level "which product stream is this" classification, decided at
/// the edge (endpoint + event name) and stamped as the pipeline half of
/// [`DataType`]. AI membership is stamp-based, not name-based: an undiverted
/// `$ai_*` event is a plain analytics event.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum Pipeline {
    Analytics,
    Ai,
    Heatmaps,
    Warnings,
    ErrorTracking,
    Replay,
}

impl Pipeline {
    /// Extract the pipeline half of a [`DataType`]. The lane half
    /// (main vs historical) is [`resolve`]'s job.
    pub fn from_data_type(data_type: DataType) -> Self {
        match data_type {
            DataType::AnalyticsMain | DataType::AnalyticsHistorical => Pipeline::Analytics,
            DataType::AiEvents => Pipeline::Ai,
            DataType::HeatmapMain => Pipeline::Heatmaps,
            DataType::ClientIngestionWarning => Pipeline::Warnings,
            DataType::ExceptionErrorTracking => Pipeline::ErrorTracking,
            DataType::SnapshotMain => Pipeline::Replay,
        }
    }
}

/// A lane of a pipeline. Flat for now — every pipeline shares this shape, and
/// `resolve` only ever pairs a pipeline with the lanes it actually has (the
/// typed-per-pipeline lanes step makes invalid pairs unrepresentable).
/// `Dlq` and `Custom` are admin redirects that cut across the per-pipeline
/// routing; `Custom` carries its own topic outside the lane model.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Lane {
    Main,
    Overflow,
    Historical,
    Dlq,
    Custom(String),
}

/// The pure routing decision for a single event: which pipeline, which lane,
/// and which ordering guarantee. Depends only on [`ProcessedEventMetadata`]
/// (stamped upstream by the pipeline) and the AI overflow valve — the one
/// piece of deployment config that changes a routing decision rather than a
/// topic name. Side effects are not part of the decision: the dlq header set
/// and the reroute counters follow from the address, and the
/// person-processing header follows from
/// [`ProcessedEventMetadata::person_processing_disabled`] — the stamped flag,
/// or a `ForceLimited` reason, which implies the skip on its own.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LaneDecision {
    pub pipeline: Pipeline,
    pub lane: Lane,
    pub ordering: OrderingGuarantee,
}

impl LaneDecision {
    fn new(pipeline: Pipeline, lane: Lane, ordering: OrderingGuarantee) -> Self {
        Self {
            pipeline,
            lane,
            ordering,
        }
    }
}

/// Decide an event's address from its metadata. DLQ and custom-topic
/// redirects take priority over per-datatype and overflow routing. Consulted
/// by the sink, which resolves the address to a topic string and the ordering
/// guarantee to a partition key, and applies the address-implied side
/// effects. A replay event with no session id is rejected here, so every
/// returned decision is realizable by the sink.
pub fn resolve(
    metadata: &ProcessedEventMetadata,
    ai_events_overflow_armed: bool,
) -> Result<LaneDecision, CaptureError> {
    let pipeline = Pipeline::from_data_type(metadata.data_type);

    // redirect_to_dlq takes priority over all other routing.
    if metadata.redirect_to_dlq {
        return Ok(LaneDecision::new(
            pipeline,
            Lane::Dlq,
            OrderingGuarantee::PerDistinctId,
        ));
    }

    if let Some(ref topic) = metadata.redirect_to_topic {
        return Ok(LaneDecision::new(
            pipeline,
            Lane::Custom(topic.clone()),
            OrderingGuarantee::PerDistinctId,
        ));
    }

    Ok(match metadata.data_type {
        DataType::AnalyticsHistorical => LaneDecision::new(
            pipeline,
            // Historical events never overflow — force_overflow and
            // overflow_reason are deliberately ignored here.
            Lane::Historical,
            OrderingGuarantee::PerDistinctId,
        ),
        DataType::AnalyticsMain => {
            // Precedence: force_overflow (restrictions) -> overflow_reason
            // (pipeline-stamped) -> default main-lane routing.
            if metadata.force_overflow {
                LaneDecision::new(
                    pipeline,
                    Lane::Overflow,
                    person_ordering(metadata.person_processing_disabled()),
                )
            } else {
                match &metadata.overflow_reason {
                    Some(OverflowReason::ForceLimited) => {
                        LaneDecision::new(pipeline, Lane::Overflow, OrderingGuarantee::None)
                    }
                    // The person flag alone decides the key here, in both
                    // directions. A burst keeps its key while person processing
                    // is on — the overflow consumer updates persons keyed on
                    // distinct id, so spreading one distinct id across
                    // partitions turns a hot key into contended person-row
                    // updates — which makes the locality preference irrelevant
                    // on this lane. And a key whose person processing is
                    // already off (the global rate limiter stamps its verdict
                    // before the overflow limiter overwrites the reason) must
                    // not get its partition back.
                    Some(OverflowReason::RateLimited { .. }) => LaneDecision::new(
                        pipeline,
                        Lane::Overflow,
                        person_ordering(metadata.person_processing_disabled()),
                    ),
                    // ReplayLimited is stamped only by the recordings pipeline,
                    // so an analytics event cannot carry it — the shared
                    // OverflowReason enum forces the arm, which treats the
                    // impossible stamp as unstamped.
                    Some(OverflowReason::ReplayLimited) | None => LaneDecision::new(
                        pipeline,
                        Lane::Main,
                        person_ordering(metadata.person_processing_disabled()),
                    ),
                }
            }
        }
        DataType::AiEvents => {
            // Valve armed: the AI lanes route overflow like analytics, except
            // that a burst may spread while person processing is on — the AI
            // consumer reads persons without writing them, so keyless
            // person-on records cause no person-update contention there.
            // Valve unarmed: AI events never overflow —
            // force_overflow and stamped reasons are deliberately ignored
            // (the pipeline never stamps a reason on this lane anyway). The
            // default route keeps the event key regardless of
            // skip_person_processing (v1 only nulls keys for
            // Main/Overflow-shaped destinations). AI events never reroute
            // historical.
            if ai_events_overflow_armed && metadata.force_overflow {
                LaneDecision::new(
                    pipeline,
                    Lane::Overflow,
                    person_ordering(metadata.person_processing_disabled()),
                )
            } else if ai_events_overflow_armed {
                match &metadata.overflow_reason {
                    Some(OverflowReason::ForceLimited) => {
                        LaneDecision::new(pipeline, Lane::Overflow, OrderingGuarantee::None)
                    }
                    Some(OverflowReason::RateLimited {
                        preserve_locality: true,
                    }) => LaneDecision::new(
                        pipeline,
                        Lane::Overflow,
                        // Same precedence as the analytics overflow lane above.
                        person_ordering(metadata.person_processing_disabled()),
                    ),
                    Some(OverflowReason::RateLimited {
                        preserve_locality: false,
                    }) => LaneDecision::new(pipeline, Lane::Overflow, OrderingGuarantee::None),
                    // ReplayLimited cannot be stamped on the AI lane either;
                    // treated as unstamped, as above.
                    Some(OverflowReason::ReplayLimited) | None => {
                        LaneDecision::new(pipeline, Lane::Main, OrderingGuarantee::PerDistinctId)
                    }
                }
            } else {
                LaneDecision::new(pipeline, Lane::Main, OrderingGuarantee::PerDistinctId)
            }
        }
        DataType::ClientIngestionWarning
        | DataType::HeatmapMain
        | DataType::ExceptionErrorTracking => {
            LaneDecision::new(pipeline, Lane::Main, OrderingGuarantee::PerDistinctId)
        }
        DataType::SnapshotMain => {
            // Precedence: force_overflow (restrictions) -> overflow_reason
            // (pipeline-stamped ReplayLimited) -> default main-lane routing.
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
                Lane::Overflow
            } else {
                Lane::Main
            };
            LaneDecision::new(pipeline, lane, OrderingGuarantee::PerSession)
        }
    })
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

    #[rstest]
    #[case(DataType::AnalyticsMain, Pipeline::Analytics)]
    #[case(DataType::AnalyticsHistorical, Pipeline::Analytics)]
    #[case(DataType::AiEvents, Pipeline::Ai)]
    #[case(DataType::ClientIngestionWarning, Pipeline::Warnings)]
    #[case(DataType::HeatmapMain, Pipeline::Heatmaps)]
    #[case(DataType::ExceptionErrorTracking, Pipeline::ErrorTracking)]
    #[case(DataType::SnapshotMain, Pipeline::Replay)]
    fn pipeline_classification(#[case] data_type: DataType, #[case] expected: Pipeline) {
        assert_eq!(Pipeline::from_data_type(data_type), expected);
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
            LaneDecision {
                pipeline: Pipeline::Analytics,
                lane: Lane::Dlq,
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
            LaneDecision {
                pipeline: Pipeline::Analytics,
                lane: Lane::Custom("my_topic".to_string()),
                ordering: OrderingGuarantee::PerDistinctId,
            }
        );
    }

    #[rstest]
    #[case(DataType::AnalyticsMain, Pipeline::Analytics, Lane::Main)]
    #[case(DataType::AnalyticsHistorical, Pipeline::Analytics, Lane::Historical)]
    #[case(DataType::ClientIngestionWarning, Pipeline::Warnings, Lane::Main)]
    #[case(DataType::HeatmapMain, Pipeline::Heatmaps, Lane::Main)]
    #[case(DataType::ExceptionErrorTracking, Pipeline::ErrorTracking, Lane::Main)]
    #[case(DataType::AiEvents, Pipeline::Ai, Lane::Main)]
    #[case(DataType::SnapshotMain, Pipeline::Replay, Lane::Main)]
    fn per_datatype_addresses(
        #[case] data_type: DataType,
        #[case] pipeline: Pipeline,
        #[case] lane: Lane,
    ) {
        let m = meta(data_type);
        let d = resolve(&m, false).unwrap();
        assert_eq!(d.pipeline, pipeline, "wrong pipeline for {data_type:?}");
        assert_eq!(d.lane, lane, "wrong lane for {data_type:?}");
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
        assert_eq!(resolve(&m, false).unwrap().lane, Lane::Overflow);
    }

    #[test]
    fn analytics_main_overflow_reason_precedence() {
        let base = meta(DataType::AnalyticsMain);

        let mut force_limited = base.clone();
        force_limited.overflow_reason = Some(OverflowReason::ForceLimited);
        assert_eq!(
            resolve(&force_limited, false).unwrap(),
            LaneDecision {
                pipeline: Pipeline::Analytics,
                lane: Lane::Overflow,
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
        assert_eq!(resolve(&preserve, false).unwrap().lane, Lane::Overflow);

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
        assert_eq!(resolve(&no_preserve, false).unwrap().lane, Lane::Overflow);
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
        assert_eq!(resolve(&replay, false).unwrap().lane, Lane::Main);
    }

    /// The global rate limiter stamps `skip_person_processing` before the
    /// overflow limiter runs, and the overflow limiter overwrites the reason it
    /// stamped. Without this precedence a key the rate limiter declared too hot
    /// would go back to hashing onto a single overflow partition whenever the
    /// limiter preserves locality, which is how prod-US is configured.
    #[rstest]
    #[case::analytics(DataType::AnalyticsMain, Pipeline::Analytics)]
    #[case::ai(DataType::AiEvents, Pipeline::Ai)]
    fn person_processing_off_outranks_preserve_locality(
        #[case] data_type: DataType,
        #[case] expected_pipeline: Pipeline,
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
            LaneDecision {
                pipeline: expected_pipeline,
                lane: Lane::Overflow,
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
            LaneDecision {
                pipeline: Pipeline::Ai,
                lane: Lane::Main,
                ordering: OrderingGuarantee::PerDistinctId,
            }
        );

        // Valve armed: mirrors the analytics main lane's overflow handling.
        assert_eq!(resolve(&m, true).unwrap().lane, Lane::Overflow);
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
            LaneDecision {
                pipeline: Pipeline::Ai,
                lane: Lane::Overflow,
                ordering: OrderingGuarantee::None,
            }
        );
        assert_eq!(resolve(&force_limited, false).unwrap().lane, Lane::Main);
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
                LaneDecision {
                    pipeline: Pipeline::Ai,
                    lane: Lane::Main,
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
            LaneDecision {
                pipeline: Pipeline::Replay,
                lane: Lane::Main,
                ordering: OrderingGuarantee::PerSession,
            }
        );

        m.force_overflow = true;
        assert_eq!(resolve(&m, false).unwrap().lane, Lane::Overflow);
        assert_eq!(
            resolve(&m, false).unwrap().ordering,
            OrderingGuarantee::PerSession
        );

        m.force_overflow = false;
        m.overflow_reason = Some(OverflowReason::ReplayLimited);
        assert_eq!(resolve(&m, false).unwrap().lane, Lane::Overflow);
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
        assert_eq!(resolve(&m, false).unwrap().lane, Lane::Dlq);
    }
}
