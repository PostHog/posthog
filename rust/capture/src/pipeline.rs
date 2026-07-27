//! The pipeline layer's routing vocabulary: an event's address is the
//! **pipeline** it belongs to and the **lane** it leaves through.
//!
//! - [`Pipeline`] is the high-level classification decided at the edge
//!   (endpoint + event name): which product stream is this event part of.
//! - [`Lane`] is decided once per event by [`resolve`], which folds the intent
//!   stamped during processing (restrictions, overflow reasons, the historical
//!   flag) through one precedence chain: dlq > custom topic > historical >
//!   overflow > main.
//!
//! [`resolve`] is pure policy over [`ProcessedEventMetadata`] — no counters,
//! no headers, no I/O. The mechanical consequences of a decision (which topic,
//! which headers to stamp, which counters to fire) are applied by whoever
//! publishes the event: today the Kafka sink's prepare path, and the outputs
//! layer once it exists. Nothing below this module makes a routing decision.

use crate::v0_request::{DataType, OverflowReason, ProcessedEventMetadata};

/// Which product stream an event belongs to. Decided at the edge; never
/// changes as the event moves through its pipeline.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Pipeline {
    Analytics,
    Heatmaps,
    Warnings,
    ErrorTracking,
    Replay,
}

impl Pipeline {
    /// The pipeline half of a `DataType`. `DataType` conflates the pipeline
    /// with the historical lane (`AnalyticsMain` vs `AnalyticsHistorical`);
    /// this extracts the pipeline, [`resolve`] extracts the lane.
    pub fn from_data_type(data_type: DataType) -> Self {
        match data_type {
            DataType::AnalyticsMain | DataType::AnalyticsHistorical => Pipeline::Analytics,
            DataType::HeatmapMain => Pipeline::Heatmaps,
            DataType::ClientIngestionWarning => Pipeline::Warnings,
            DataType::ExceptionErrorTracking => Pipeline::ErrorTracking,
            DataType::SnapshotMain => Pipeline::Replay,
        }
    }
}

/// Which lane of its pipeline an event leaves through. Lanes are shared
/// vocabulary across pipelines; not every pipeline reaches every lane
/// ([`resolve`] is the sole constructor and only produces valid pairs).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Lane<'a> {
    Main,
    Overflow,
    Historical,
    Dlq,
    /// Admin-configured redirect topic, borrowed from
    /// `ProcessedEventMetadata::redirect_to_topic`.
    Custom(&'a str),
}

/// How the partition key is derived when the event is published. Decided with
/// the lane (overflow without locality drops the key); resolved against the
/// event's own values by the publisher, which owns them.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeyPolicy {
    /// Partition on the event's `token:distinct_id` key.
    EventKey,
    /// No partition key — round-robin; person locality is intentionally dropped.
    Null,
    /// Partition on the replay `session_id` (missing id is a publish-time reject).
    SessionId,
}

/// Side effects the lane decision implies — headers to stamp and counters to
/// fire. Carried as data so the decision stays pure; applied mechanically by
/// the publisher.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LaneEffect {
    /// Normal routing: no extra headers or counters.
    Standard,
    /// Event-restriction DLQ redirect: stamp DLQ headers + fire the DLQ counter.
    Dlq,
    /// Event-restriction custom-topic redirect: fire the custom-topic counter.
    CustomTopic,
    /// Force-limited overflow: disable person processing downstream. Redundant
    /// with the generic `skip_person_processing` path (the pipeline stamps
    /// `skip_person_processing = true` alongside `OverflowReason::ForceLimited`),
    /// but kept as defense against a future caller that stamps the reason without
    /// the side effect.
    ForceDisablePersonProcessing,
}

/// The resolved address of an event plus the key policy and effects that come
/// with it. Everything the publisher needs; nothing it may second-guess.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LaneDecision<'a> {
    pub pipeline: Pipeline,
    pub lane: Lane<'a>,
    pub key_policy: KeyPolicy,
    pub effect: LaneEffect,
}

/// Partition key policy shared by the analytics main and force-overflow lanes:
/// null the key when person processing is skipped, otherwise partition on the
/// event key.
fn person_key_policy(skip_person_processing: bool) -> KeyPolicy {
    if skip_person_processing {
        KeyPolicy::Null
    } else {
        KeyPolicy::EventKey
    }
}

/// The lane decision: one precedence chain over the intent flags stamped
/// upstream. DLQ and custom-topic redirects take priority over per-pipeline
/// and overflow routing.
pub fn resolve(metadata: &ProcessedEventMetadata) -> LaneDecision<'_> {
    let pipeline = Pipeline::from_data_type(metadata.data_type);

    // redirect_to_dlq takes priority over all other routing.
    if metadata.redirect_to_dlq {
        return LaneDecision {
            pipeline,
            lane: Lane::Dlq,
            key_policy: KeyPolicy::EventKey,
            effect: LaneEffect::Dlq,
        };
    }

    if let Some(ref topic) = metadata.redirect_to_topic {
        return LaneDecision {
            pipeline,
            lane: Lane::Custom(topic),
            key_policy: KeyPolicy::EventKey,
            effect: LaneEffect::CustomTopic,
        };
    }

    match metadata.data_type {
        DataType::AnalyticsHistorical => LaneDecision {
            // Historical events never overflow — force_overflow and
            // overflow_reason are deliberately ignored here.
            pipeline,
            lane: Lane::Historical,
            key_policy: KeyPolicy::EventKey,
            effect: LaneEffect::Standard,
        },
        DataType::AnalyticsMain => {
            // Precedence: force_overflow (restrictions) -> overflow_reason
            // (pipeline-stamped) -> default main-lane routing.
            if metadata.force_overflow {
                LaneDecision {
                    pipeline,
                    lane: Lane::Overflow,
                    key_policy: person_key_policy(metadata.skip_person_processing),
                    effect: LaneEffect::Standard,
                }
            } else {
                match &metadata.overflow_reason {
                    Some(OverflowReason::ForceLimited) => LaneDecision {
                        pipeline,
                        lane: Lane::Overflow,
                        key_policy: KeyPolicy::Null,
                        effect: LaneEffect::ForceDisablePersonProcessing,
                    },
                    Some(OverflowReason::RateLimited {
                        preserve_locality: true,
                    }) => LaneDecision {
                        pipeline,
                        lane: Lane::Overflow,
                        key_policy: KeyPolicy::EventKey,
                        effect: LaneEffect::Standard,
                    },
                    Some(OverflowReason::RateLimited {
                        preserve_locality: false,
                    }) => LaneDecision {
                        pipeline,
                        lane: Lane::Overflow,
                        key_policy: KeyPolicy::Null,
                        effect: LaneEffect::Standard,
                    },
                    // ReplayLimited never applies to AnalyticsMain; fall through to main.
                    Some(OverflowReason::ReplayLimited) | None => LaneDecision {
                        pipeline,
                        lane: Lane::Main,
                        key_policy: person_key_policy(metadata.skip_person_processing),
                        effect: LaneEffect::Standard,
                    },
                }
            }
        }
        DataType::ClientIngestionWarning
        | DataType::HeatmapMain
        | DataType::ExceptionErrorTracking => LaneDecision {
            pipeline,
            lane: Lane::Main,
            key_policy: KeyPolicy::EventKey,
            effect: LaneEffect::Standard,
        },
        DataType::SnapshotMain => {
            // Precedence: force_overflow (restrictions) -> overflow_reason
            // (pipeline-stamped ReplayLimited) -> default main-lane routing.
            // Partition key is always session_id for replay to keep per-session
            // ordering on the overflow lane.
            let lane = if metadata.force_overflow
                || matches!(
                    metadata.overflow_reason,
                    Some(OverflowReason::ReplayLimited)
                ) {
                Lane::Overflow
            } else {
                Lane::Main
            };
            LaneDecision {
                pipeline,
                lane,
                key_policy: KeyPolicy::SessionId,
                effect: LaneEffect::Standard,
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
        }
    }

    #[test]
    fn pipeline_classification_per_data_type() {
        for (dt, pipeline) in [
            (DataType::AnalyticsMain, Pipeline::Analytics),
            (DataType::AnalyticsHistorical, Pipeline::Analytics),
            (DataType::ClientIngestionWarning, Pipeline::Warnings),
            (DataType::HeatmapMain, Pipeline::Heatmaps),
            (DataType::ExceptionErrorTracking, Pipeline::ErrorTracking),
            (DataType::SnapshotMain, Pipeline::Replay),
        ] {
            assert_eq!(
                Pipeline::from_data_type(dt),
                pipeline,
                "wrong pipeline for {dt:?}"
            );
        }
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
            resolve(&m),
            LaneDecision {
                pipeline: Pipeline::Analytics,
                lane: Lane::Dlq,
                key_policy: KeyPolicy::EventKey,
                effect: LaneEffect::Dlq,
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
            resolve(&m),
            LaneDecision {
                pipeline: Pipeline::Analytics,
                lane: Lane::Custom("my_topic"),
                key_policy: KeyPolicy::EventKey,
                effect: LaneEffect::CustomTopic,
            }
        );
    }

    #[test]
    fn per_datatype_lanes() {
        for (dt, pipeline, lane) in [
            (DataType::AnalyticsMain, Pipeline::Analytics, Lane::Main),
            (
                DataType::AnalyticsHistorical,
                Pipeline::Analytics,
                Lane::Historical,
            ),
            (
                DataType::ClientIngestionWarning,
                Pipeline::Warnings,
                Lane::Main,
            ),
            (DataType::HeatmapMain, Pipeline::Heatmaps, Lane::Main),
            (
                DataType::ExceptionErrorTracking,
                Pipeline::ErrorTracking,
                Lane::Main,
            ),
            (DataType::SnapshotMain, Pipeline::Replay, Lane::Main),
        ] {
            let m = meta(dt);
            let d = resolve(&m);
            assert_eq!(d.pipeline, pipeline, "wrong pipeline for {dt:?}");
            assert_eq!(d.lane, lane, "wrong lane for {dt:?}");
            assert_eq!(d.effect, LaneEffect::Standard, "wrong effect for {dt:?}");
        }
    }

    #[test]
    fn analytics_main_overflow_key_policy() {
        // force_overflow -> overflow lane; key policy follows skip_person.
        let mut m = meta(DataType::AnalyticsMain);
        m.force_overflow = true;
        assert_eq!(resolve(&m).key_policy, KeyPolicy::EventKey);
        m.skip_person_processing = true;
        assert_eq!(resolve(&m).key_policy, KeyPolicy::Null);
        assert_eq!(resolve(&m).lane, Lane::Overflow);
    }

    #[test]
    fn analytics_main_overflow_reason_precedence() {
        let base = meta(DataType::AnalyticsMain);

        let mut force_limited = base.clone();
        force_limited.overflow_reason = Some(OverflowReason::ForceLimited);
        assert_eq!(
            resolve(&force_limited),
            LaneDecision {
                pipeline: Pipeline::Analytics,
                lane: Lane::Overflow,
                key_policy: KeyPolicy::Null,
                effect: LaneEffect::ForceDisablePersonProcessing,
            }
        );

        let mut preserve = base.clone();
        preserve.overflow_reason = Some(OverflowReason::RateLimited {
            preserve_locality: true,
        });
        assert_eq!(resolve(&preserve).key_policy, KeyPolicy::EventKey);
        assert_eq!(resolve(&preserve).lane, Lane::Overflow);

        let mut no_preserve = base.clone();
        no_preserve.overflow_reason = Some(OverflowReason::RateLimited {
            preserve_locality: false,
        });
        assert_eq!(resolve(&no_preserve).key_policy, KeyPolicy::Null);
        assert_eq!(resolve(&no_preserve).lane, Lane::Overflow);

        // ReplayLimited never applies to AnalyticsMain: falls through to main.
        let mut replay = base;
        replay.overflow_reason = Some(OverflowReason::ReplayLimited);
        assert_eq!(resolve(&replay).lane, Lane::Main);
    }

    #[test]
    fn snapshot_routing_uses_session_id_key() {
        let mut m = meta(DataType::SnapshotMain);
        assert_eq!(
            resolve(&m),
            LaneDecision {
                pipeline: Pipeline::Replay,
                lane: Lane::Main,
                key_policy: KeyPolicy::SessionId,
                effect: LaneEffect::Standard,
            }
        );

        m.force_overflow = true;
        assert_eq!(resolve(&m).lane, Lane::Overflow);
        assert_eq!(resolve(&m).key_policy, KeyPolicy::SessionId);

        m.force_overflow = false;
        m.overflow_reason = Some(OverflowReason::ReplayLimited);
        assert_eq!(resolve(&m).lane, Lane::Overflow);
    }
}
