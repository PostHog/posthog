//! The pipeline layer's routing vocabulary: an event's [`Address`] — the
//! **pipeline** it belongs to and the **lane** it leaves through, or an
//! admin-configured **custom redirect** that bypasses the lane model with an
//! inline topic.
//!
//! - [`Pipeline`] is the high-level classification decided at the edge
//!   (endpoint + event name): which product stream is this event part of.
//! - Each pipeline has its own lane type ([`AnalyticsLane`], [`SessionReplayLane`],
//!   [`BasicLane`]), so an invalid pair — a historical heatmap, an
//!   overflowing warning — is unrepresentable rather than merely unreached.
//!   [`resolve`] folds the intent stamped during processing (restrictions,
//!   overflow reasons, the historical flag) through one precedence chain:
//!   dlq > custom topic > historical > overflow > main.
//!
//! [`resolve`] is pure policy over [`ProcessedEventMetadata`] — no counters,
//! no headers, no I/O. The mechanical consequences of a decision (which topic,
//! which headers to stamp, which counters to fire) are applied by the outputs
//! layer, which publishes the event. Nothing below this module makes a
//! routing decision.

use crate::v0_request::{DataType, OverflowReason, ProcessedEventMetadata};

/// The event-name prefix that marks an event as part of the AI pipeline.
/// Shared with the LLM quota predicate so "what is an AI event" has exactly
/// one definition.
pub const AI_EVENT_PREFIX: &str = "$ai_";

/// Which product stream an event belongs to. Decided at the edge; never
/// changes as the event moves through its pipeline.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Pipeline {
    Analytics,
    /// LLM analytics: `$ai_*` events. They ride the analytics data types and
    /// (today) the analytics topics, but are their own product stream — with
    /// their own ingress, quota resource, and cluster-migration story — so
    /// they are addressable as their own pipeline.
    Ai,
    Heatmaps,
    Warnings,
    ErrorTracking,
    SessionReplay,
}

impl Pipeline {
    /// Classify an event's pipeline from its metadata. `DataType` conflates
    /// the pipeline with the historical lane (`AnalyticsMain` vs
    /// `AnalyticsHistorical`) and does not distinguish the AI stream at all
    /// (`$ai_*` events are analytics data types); this extracts the pipeline,
    /// [`resolve`] extracts the lane. Classification is by event name, not
    /// ingress, so `$ai_*` events reaching plain `/capture` land in the AI
    /// pipeline too — consistent with the LLM quota predicate.
    pub fn from_metadata(metadata: &ProcessedEventMetadata) -> Self {
        match metadata.data_type {
            DataType::AnalyticsMain | DataType::AnalyticsHistorical => {
                if metadata.event_name.starts_with(AI_EVENT_PREFIX) {
                    Pipeline::Ai
                } else {
                    Pipeline::Analytics
                }
            }
            DataType::HeatmapMain => Pipeline::Heatmaps,
            DataType::ClientIngestionWarning => Pipeline::Warnings,
            DataType::ExceptionErrorTracking => Pipeline::ErrorTracking,
            DataType::SnapshotMain => Pipeline::SessionReplay,
        }
    }
}

/// The analytics pipeline's lanes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AnalyticsLane {
    Main,
    Overflow,
    Historical,
    Dlq,
}

/// The AI pipeline's lanes: a mirror of [`AnalyticsLane`] because AI events
/// ride the analytics data types (and, today, the analytics topics) —
/// including historical batch migrations. Distinct type so the streams stay
/// independently addressable as their routing diverges.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AiLane {
    Main,
    Overflow,
    Historical,
    Dlq,
}

/// The replay pipeline's lanes: main, its own overflow, and dlq.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionReplayLane {
    Main,
    Overflow,
    Dlq,
}

/// Lanes of the main-only pipelines (heatmaps, warnings, error tracking).
/// Shared because their lane sets are identical today; split the moment one
/// diverges.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BasicLane {
    Main,
    Dlq,
}

/// Where an event is published: a lane of its pipeline, or an
/// admin-configured custom redirect. Lanes are typed per pipeline, so only
/// valid pairs exist; [`resolve`] is the sole constructor on the produce
/// path.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Address {
    Analytics(AnalyticsLane),
    Ai(AiLane),
    Heatmaps(BasicLane),
    Warnings(BasicLane),
    ErrorTracking(BasicLane),
    SessionReplay(SessionReplayLane),
    /// Admin-configured redirect: carries its own topic (borrowed from
    /// `ProcessedEventMetadata::redirect_to_topic`) and sits outside the
    /// lane model — it never registers in the output registry. The pipeline
    /// is carried as provenance: serialization policy (e.g. the replay lz4
    /// envelope) follows the pipeline even on a redirect.
    Custom {
        pipeline: Pipeline,
        topic: String,
    },
}

impl Address {
    /// The pipeline this address belongs to. Total — a custom redirect
    /// carries its provenance.
    pub fn pipeline(&self) -> Pipeline {
        match self {
            Address::Analytics(_) => Pipeline::Analytics,
            Address::Ai(_) => Pipeline::Ai,
            Address::Heatmaps(_) => Pipeline::Heatmaps,
            Address::Warnings(_) => Pipeline::Warnings,
            Address::ErrorTracking(_) => Pipeline::ErrorTracking,
            Address::SessionReplay(_) => Pipeline::SessionReplay,
            Address::Custom { pipeline, .. } => *pipeline,
        }
    }
}

/// How the partition key is derived when the event is published. Decided with
/// the address (overflow without locality drops the key); resolved against
/// the event's own values by the publisher, which owns them.
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
pub struct LaneDecision {
    pub address: Address,
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

/// Every pipeline's dlq lane, in its own lane type.
fn dlq_address(pipeline: Pipeline) -> Address {
    match pipeline {
        Pipeline::Analytics => Address::Analytics(AnalyticsLane::Dlq),
        Pipeline::Ai => Address::Ai(AiLane::Dlq),
        Pipeline::Heatmaps => Address::Heatmaps(BasicLane::Dlq),
        Pipeline::Warnings => Address::Warnings(BasicLane::Dlq),
        Pipeline::ErrorTracking => Address::ErrorTracking(BasicLane::Dlq),
        Pipeline::SessionReplay => Address::SessionReplay(SessionReplayLane::Dlq),
    }
}

/// The analytics data types carry two pipelines (analytics and AI); route a
/// lane to whichever the event classified into.
fn analytics_family(pipeline: Pipeline, lane: AnalyticsLane) -> Address {
    match pipeline {
        Pipeline::Ai => Address::Ai(match lane {
            AnalyticsLane::Main => AiLane::Main,
            AnalyticsLane::Overflow => AiLane::Overflow,
            AnalyticsLane::Historical => AiLane::Historical,
            AnalyticsLane::Dlq => AiLane::Dlq,
        }),
        _ => Address::Analytics(lane),
    }
}

/// The lane decision: one precedence chain over the intent flags stamped
/// upstream. DLQ and custom-topic redirects take priority over per-pipeline
/// and overflow routing.
pub fn resolve(metadata: &ProcessedEventMetadata) -> LaneDecision {
    let pipeline = Pipeline::from_metadata(metadata);

    // redirect_to_dlq takes priority over all other routing.
    if metadata.redirect_to_dlq {
        return LaneDecision {
            address: dlq_address(pipeline),
            key_policy: KeyPolicy::EventKey,
            effect: LaneEffect::Dlq,
        };
    }

    if let Some(ref topic) = metadata.redirect_to_topic {
        return LaneDecision {
            address: Address::Custom {
                pipeline,
                topic: topic.clone(),
            },
            key_policy: KeyPolicy::EventKey,
            effect: LaneEffect::CustomTopic,
        };
    }

    match metadata.data_type {
        DataType::AnalyticsHistorical => LaneDecision {
            // Historical events never overflow — force_overflow and
            // overflow_reason are deliberately ignored here.
            address: analytics_family(pipeline, AnalyticsLane::Historical),
            key_policy: KeyPolicy::EventKey,
            effect: LaneEffect::Standard,
        },
        DataType::AnalyticsMain => {
            // Precedence: force_overflow (restrictions) -> overflow_reason
            // (pipeline-stamped) -> default main-lane routing.
            if metadata.force_overflow {
                LaneDecision {
                    address: analytics_family(pipeline, AnalyticsLane::Overflow),
                    key_policy: person_key_policy(metadata.skip_person_processing),
                    effect: LaneEffect::Standard,
                }
            } else {
                match &metadata.overflow_reason {
                    Some(OverflowReason::ForceLimited) => LaneDecision {
                        address: analytics_family(pipeline, AnalyticsLane::Overflow),
                        key_policy: KeyPolicy::Null,
                        effect: LaneEffect::ForceDisablePersonProcessing,
                    },
                    Some(OverflowReason::RateLimited {
                        preserve_locality: true,
                    }) => LaneDecision {
                        address: analytics_family(pipeline, AnalyticsLane::Overflow),
                        key_policy: KeyPolicy::EventKey,
                        effect: LaneEffect::Standard,
                    },
                    Some(OverflowReason::RateLimited {
                        preserve_locality: false,
                    }) => LaneDecision {
                        address: analytics_family(pipeline, AnalyticsLane::Overflow),
                        key_policy: KeyPolicy::Null,
                        effect: LaneEffect::Standard,
                    },
                    // ReplayLimited never applies to AnalyticsMain; fall through to main.
                    Some(OverflowReason::ReplayLimited) | None => LaneDecision {
                        address: analytics_family(pipeline, AnalyticsLane::Main),
                        key_policy: person_key_policy(metadata.skip_person_processing),
                        effect: LaneEffect::Standard,
                    },
                }
            }
        }
        DataType::ClientIngestionWarning => LaneDecision {
            address: Address::Warnings(BasicLane::Main),
            key_policy: KeyPolicy::EventKey,
            effect: LaneEffect::Standard,
        },
        DataType::HeatmapMain => LaneDecision {
            address: Address::Heatmaps(BasicLane::Main),
            key_policy: KeyPolicy::EventKey,
            effect: LaneEffect::Standard,
        },
        DataType::ExceptionErrorTracking => LaneDecision {
            address: Address::ErrorTracking(BasicLane::Main),
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
                SessionReplayLane::Overflow
            } else {
                SessionReplayLane::Main
            };
            LaneDecision {
                address: Address::SessionReplay(lane),
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
            (DataType::SnapshotMain, Pipeline::SessionReplay),
        ] {
            assert_eq!(
                Pipeline::from_metadata(&meta(dt)),
                pipeline,
                "wrong pipeline for {dt:?}"
            );
        }
    }

    #[test]
    fn ai_events_classify_as_ai_pipeline_by_name() {
        // `$ai_*` events ride the analytics data types but classify as the AI
        // pipeline — through any ingress, and on the historical lane too.
        let mut m = meta(DataType::AnalyticsMain);
        m.event_name = "$ai_generation".to_string();
        assert_eq!(Pipeline::from_metadata(&m), Pipeline::Ai);
        assert_eq!(resolve(&m).address, Address::Ai(AiLane::Main));

        m.overflow_reason = Some(OverflowReason::ForceLimited);
        assert_eq!(resolve(&m).address, Address::Ai(AiLane::Overflow));
        m.overflow_reason = None;

        m.redirect_to_dlq = true;
        assert_eq!(resolve(&m).address, Address::Ai(AiLane::Dlq));
        m.redirect_to_dlq = false;

        m.redirect_to_topic = Some("warpstream_topic".to_string());
        assert_eq!(
            resolve(&m).address,
            Address::Custom {
                pipeline: Pipeline::Ai,
                topic: "warpstream_topic".to_string(),
            }
        );
        m.redirect_to_topic = None;

        m.data_type = DataType::AnalyticsHistorical;
        assert_eq!(resolve(&m).address, Address::Ai(AiLane::Historical));
    }

    #[test]
    fn address_pipeline_projection_is_total() {
        for (address, pipeline) in [
            (
                Address::Analytics(AnalyticsLane::Historical),
                Pipeline::Analytics,
            ),
            (Address::Heatmaps(BasicLane::Main), Pipeline::Heatmaps),
            (Address::Warnings(BasicLane::Dlq), Pipeline::Warnings),
            (
                Address::ErrorTracking(BasicLane::Main),
                Pipeline::ErrorTracking,
            ),
            (
                Address::SessionReplay(SessionReplayLane::Overflow),
                Pipeline::SessionReplay,
            ),
            (
                Address::Custom {
                    pipeline: Pipeline::SessionReplay,
                    topic: "t".to_string(),
                },
                Pipeline::SessionReplay,
            ),
        ] {
            assert_eq!(address.pipeline(), pipeline);
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
                address: Address::Analytics(AnalyticsLane::Dlq),
                key_policy: KeyPolicy::EventKey,
                effect: LaneEffect::Dlq,
            }
        );
    }

    #[test]
    fn every_pipeline_resolves_its_own_dlq_lane() {
        for (dt, expected) in [
            (
                DataType::AnalyticsMain,
                Address::Analytics(AnalyticsLane::Dlq),
            ),
            (
                DataType::AnalyticsHistorical,
                Address::Analytics(AnalyticsLane::Dlq),
            ),
            (DataType::HeatmapMain, Address::Heatmaps(BasicLane::Dlq)),
            (
                DataType::ClientIngestionWarning,
                Address::Warnings(BasicLane::Dlq),
            ),
            (
                DataType::ExceptionErrorTracking,
                Address::ErrorTracking(BasicLane::Dlq),
            ),
            (
                DataType::SnapshotMain,
                Address::SessionReplay(SessionReplayLane::Dlq),
            ),
        ] {
            let mut m = meta(dt);
            m.redirect_to_dlq = true;
            assert_eq!(
                resolve(&m).address,
                expected,
                "wrong dlq address for {dt:?}"
            );
        }
    }

    #[test]
    fn custom_topic_wins_over_datatype() {
        // Custom-topic redirect beats per-datatype/overflow routing (but not
        // DLQ), and carries its pipeline as provenance.
        let mut m = meta(DataType::AnalyticsMain);
        m.redirect_to_topic = Some("my_topic".to_string());
        m.force_overflow = true;
        assert_eq!(
            resolve(&m),
            LaneDecision {
                address: Address::Custom {
                    pipeline: Pipeline::Analytics,
                    topic: "my_topic".to_string(),
                },
                key_policy: KeyPolicy::EventKey,
                effect: LaneEffect::CustomTopic,
            }
        );
    }

    #[test]
    fn per_datatype_addresses() {
        for (dt, address) in [
            (
                DataType::AnalyticsMain,
                Address::Analytics(AnalyticsLane::Main),
            ),
            (
                DataType::AnalyticsHistorical,
                Address::Analytics(AnalyticsLane::Historical),
            ),
            (
                DataType::ClientIngestionWarning,
                Address::Warnings(BasicLane::Main),
            ),
            (DataType::HeatmapMain, Address::Heatmaps(BasicLane::Main)),
            (
                DataType::ExceptionErrorTracking,
                Address::ErrorTracking(BasicLane::Main),
            ),
            (
                DataType::SnapshotMain,
                Address::SessionReplay(SessionReplayLane::Main),
            ),
        ] {
            let m = meta(dt);
            let d = resolve(&m);
            assert_eq!(d.address, address, "wrong address for {dt:?}");
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
        assert_eq!(
            resolve(&m).address,
            Address::Analytics(AnalyticsLane::Overflow)
        );
    }

    #[test]
    fn analytics_main_overflow_reason_precedence() {
        let base = meta(DataType::AnalyticsMain);

        let mut force_limited = base.clone();
        force_limited.overflow_reason = Some(OverflowReason::ForceLimited);
        assert_eq!(
            resolve(&force_limited),
            LaneDecision {
                address: Address::Analytics(AnalyticsLane::Overflow),
                key_policy: KeyPolicy::Null,
                effect: LaneEffect::ForceDisablePersonProcessing,
            }
        );

        let mut preserve = base.clone();
        preserve.overflow_reason = Some(OverflowReason::RateLimited {
            preserve_locality: true,
        });
        assert_eq!(resolve(&preserve).key_policy, KeyPolicy::EventKey);
        assert_eq!(
            resolve(&preserve).address,
            Address::Analytics(AnalyticsLane::Overflow)
        );

        let mut no_preserve = base.clone();
        no_preserve.overflow_reason = Some(OverflowReason::RateLimited {
            preserve_locality: false,
        });
        assert_eq!(resolve(&no_preserve).key_policy, KeyPolicy::Null);
        assert_eq!(
            resolve(&no_preserve).address,
            Address::Analytics(AnalyticsLane::Overflow)
        );

        // ReplayLimited never applies to AnalyticsMain: falls through to main.
        let mut replay = base;
        replay.overflow_reason = Some(OverflowReason::ReplayLimited);
        assert_eq!(
            resolve(&replay).address,
            Address::Analytics(AnalyticsLane::Main)
        );
    }

    #[test]
    fn snapshot_routing_uses_session_id_key() {
        let mut m = meta(DataType::SnapshotMain);
        assert_eq!(
            resolve(&m),
            LaneDecision {
                address: Address::SessionReplay(SessionReplayLane::Main),
                key_policy: KeyPolicy::SessionId,
                effect: LaneEffect::Standard,
            }
        );

        m.force_overflow = true;
        assert_eq!(
            resolve(&m).address,
            Address::SessionReplay(SessionReplayLane::Overflow)
        );
        assert_eq!(resolve(&m).key_policy, KeyPolicy::SessionId);

        m.force_overflow = false;
        m.overflow_reason = Some(OverflowReason::ReplayLimited);
        assert_eq!(
            resolve(&m).address,
            Address::SessionReplay(SessionReplayLane::Overflow)
        );
    }
}
