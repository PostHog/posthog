use common_types::CapturedEventHeaders;
use uuid::Uuid;

use crate::event_restrictions::Pipeline;
use crate::ordering::OrderingGuarantee;
use crate::pipeline::{self, Address, Lane};
use crate::v1::context::RequestContext;

/// Where a processed event goes. The outputs layer resolves it to a topic
/// through [`Destination::address`].
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub enum Destination {
    #[default]
    AnalyticsMain,
    AnalyticsHistorical,
    Overflow,
    Dlq,
    Custom(String),
    /// Never published.
    Drop,
    ExceptionErrorTracking,
    HeatmapMain,
    ClientIngestionWarning,
    AiEvents,
    AiEventsOverflow,
}

impl Destination {
    /// Whether analytics-scoped restrictions and overflow routing apply.
    pub fn is_analytics_pipeline(&self) -> bool {
        matches!(self, Self::AnalyticsMain | Self::AnalyticsHistorical)
    }

    /// The restriction pipeline whose restrictions apply, or `None` when no
    /// restriction applies. Matches v0's `DataType::pipeline`.
    pub fn pipeline(&self) -> Option<Pipeline> {
        match self {
            Self::AnalyticsMain | Self::AnalyticsHistorical | Self::Overflow => {
                Some(Pipeline::Analytics)
            }
            Self::AiEvents | Self::AiEventsOverflow => Some(Pipeline::Ai),
            Self::ExceptionErrorTracking => Some(Pipeline::ErrorTracking),
            // Their consumers share no restriction config with another pipeline.
            Self::HeatmapMain | Self::ClientIngestionWarning => None,
            // Already the outcome of a restriction, or never published.
            Self::Dlq | Self::Custom(_) | Self::Drop => None,
        }
    }

    /// Whether this lane exists to absorb hot keys, and so may publish without
    /// a partition key to spread load across partitions.
    pub fn absorbs_hot_keys(&self) -> bool {
        // No wildcard: a new destination has to state which side it is on
        // instead of inheriting "keeps its key".
        match self {
            Self::AnalyticsMain | Self::Overflow | Self::AiEventsOverflow => true,
            // These keep their key even when person processing is off, because
            // their consumers rely on per-distinct-id ordering.
            Self::AnalyticsHistorical
            | Self::Dlq
            | Self::Custom(_)
            | Self::ExceptionErrorTracking
            | Self::HeatmapMain
            | Self::ClientIngestionWarning
            | Self::AiEvents => false,
            Self::Drop => false,
        }
    }

    /// Whether this lane's consumer writes persons. On such a lane a spread
    /// decision takes effect only once person processing is off, because
    /// spreading one distinct id across partitions turns a hot key into
    /// contended person-row updates.
    pub fn writes_persons(&self) -> bool {
        // No wildcard, for the same reason as in `absorbs_hot_keys`.
        match self {
            Self::AnalyticsMain | Self::AnalyticsHistorical | Self::Overflow => true,
            // Replayed into analytics ingestion.
            Self::Dlq | Self::Custom(_) => true,
            Self::AiEvents
            | Self::AiEventsOverflow
            | Self::ExceptionErrorTracking
            | Self::HeatmapMain
            | Self::ClientIngestionWarning => false,
            Self::Drop => false,
        }
    }

    /// The output address this destination publishes to, or `None` when it is
    /// never published.
    pub fn address(&self) -> Option<Address> {
        let lane = |pipeline, lane| Some(Address::Lane { pipeline, lane });
        match self {
            Self::AnalyticsMain => lane(pipeline::Pipeline::Analytics, Lane::Main),
            Self::AnalyticsHistorical => lane(pipeline::Pipeline::Analytics, Lane::Historical),
            Self::Overflow => lane(pipeline::Pipeline::Analytics, Lane::Overflow),
            Self::AiEvents => lane(pipeline::Pipeline::Ai, Lane::Main),
            Self::AiEventsOverflow => lane(pipeline::Pipeline::Ai, Lane::Overflow),
            Self::ExceptionErrorTracking => lane(pipeline::Pipeline::ErrorTracking, Lane::Main),
            Self::HeatmapMain => lane(pipeline::Pipeline::Heatmaps, Lane::Main),
            Self::ClientIngestionWarning => lane(pipeline::Pipeline::Warnings, Lane::Main),
            Self::Dlq => Some(Address::Dlq),
            Self::Custom(topic) => Some(Address::Custom(topic.clone())),
            Self::Drop => None,
        }
    }

    /// Low-cardinality metric label value.
    pub fn as_tag(&self) -> &'static str {
        match self {
            Self::AnalyticsMain => "analytics_main",
            Self::AnalyticsHistorical => "analytics_historical",
            Self::Overflow => "overflow",
            Self::Dlq => "dlq",
            // Admin-configured topic names never become label values.
            Self::Custom(_) => "custom",
            Self::Drop => "drop",
            Self::ExceptionErrorTracking => "exception_error_tracking",
            Self::HeatmapMain => "heatmap_main",
            Self::ClientIngestionWarning => "client_ingestion_warning",
            Self::AiEvents => "ai_events",
            Self::AiEventsOverflow => "ai_events_overflow",
        }
    }
}

/// What [`crate::v1::prepare::serialize_batch`] reads from a request event to
/// build its [`PreparedEvent`](crate::outputs::PreparedEvent).
pub trait Publishable: Send + Sync {
    /// Matches the event's serialize failure or publish result back to it.
    fn uuid(&self) -> Uuid;

    /// `false` skips the event: it gets no prepared record and no result.
    fn should_publish(&self) -> bool;

    fn destination(&self) -> &Destination;

    /// `ctx` supplies the batch-scoped headers: token, now and
    /// historical_migration.
    fn headers(&self, ctx: &RequestContext) -> CapturedEventHeaders;

    /// [`Publishable::ordering`] decides whether the record carries this key.
    /// The person-processing header never does, because it instructs
    /// ingestion to skip identity resolution and is not a partitioning signal.
    fn partition_key(&self, ctx: &RequestContext) -> String;

    /// The ordering guarantee this event's destination must preserve. The Kafka sink
    /// realizes [`OrderingGuarantee::None`] by publishing without a partition
    /// key so the broker round-robins; every other guarantee uses
    /// [`Publishable::partition_key`], which supplies the value that preserves it.
    fn ordering(&self) -> OrderingGuarantee;

    /// `Bytes` so binary payloads such as replay fit, and so a failover output
    /// can hold the payload without re-encoding it.
    fn serialize(&self, ctx: &RequestContext) -> anyhow::Result<bytes::Bytes>;
}

#[cfg(test)]
mod destination_tests {
    use super::Destination;
    use crate::sinks::registry::Destination as V0Destination;

    #[test]
    fn is_analytics_pipeline_true_for_main_and_historical() {
        assert!(Destination::AnalyticsMain.is_analytics_pipeline());
        assert!(Destination::AnalyticsHistorical.is_analytics_pipeline());
    }

    #[test]
    fn is_analytics_pipeline_false_for_non_analytics() {
        assert!(!Destination::ExceptionErrorTracking.is_analytics_pipeline());
        assert!(!Destination::HeatmapMain.is_analytics_pipeline());
        assert!(!Destination::ClientIngestionWarning.is_analytics_pipeline());
        assert!(!Destination::AiEvents.is_analytics_pipeline());
        assert!(!Destination::AiEventsOverflow.is_analytics_pipeline());
        assert!(!Destination::Overflow.is_analytics_pipeline());
        assert!(!Destination::Dlq.is_analytics_pipeline());
        assert!(!Destination::Drop.is_analytics_pipeline());
        assert!(!Destination::Custom("foo".into()).is_analytics_pipeline());
    }

    /// Each v1 destination names the same routed slot as its v0 counterpart.
    #[rstest::rstest]
    #[case(Destination::AnalyticsMain, Some(V0Destination::AnalyticsMain))]
    #[case(
        Destination::AnalyticsHistorical,
        Some(V0Destination::AnalyticsHistorical)
    )]
    #[case(Destination::Overflow, Some(V0Destination::AnalyticsOverflow))]
    #[case(Destination::Dlq, Some(V0Destination::Dlq))]
    #[case(Destination::Custom("admin_topic".into()), Some(V0Destination::Custom("admin_topic".into())))]
    #[case(
        Destination::ExceptionErrorTracking,
        Some(V0Destination::ErrorTrackingMain)
    )]
    #[case(Destination::HeatmapMain, Some(V0Destination::HeatmapsMain))]
    #[case(
        Destination::ClientIngestionWarning,
        Some(V0Destination::ClientWarningsMain)
    )]
    #[case(Destination::AiEvents, Some(V0Destination::AiMain))]
    #[case(Destination::AiEventsOverflow, Some(V0Destination::AiOverflow))]
    #[case(Destination::Drop, None)]
    fn address_matches_the_v0_destination(
        #[case] destination: Destination,
        #[case] expected: Option<V0Destination>,
    ) {
        let v0 = destination.address().and_then(V0Destination::for_address);
        assert_eq!(v0, expected);
    }

    #[test]
    fn as_tag_exhaustive_stable_and_unique() {
        // One representative per variant.
        let expected: &[(Destination, &str)] = &[
            (Destination::AnalyticsMain, "analytics_main"),
            (Destination::AnalyticsHistorical, "analytics_historical"),
            (Destination::Overflow, "overflow"),
            (Destination::Dlq, "dlq"),
            (Destination::Custom("topic_a".into()), "custom"),
            (Destination::Drop, "drop"),
            (
                Destination::ExceptionErrorTracking,
                "exception_error_tracking",
            ),
            (Destination::HeatmapMain, "heatmap_main"),
            (
                Destination::ClientIngestionWarning,
                "client_ingestion_warning",
            ),
            (Destination::AiEvents, "ai_events"),
            (Destination::AiEventsOverflow, "ai_events_overflow"),
        ];

        let mut seen = std::collections::HashSet::new();
        for (dest, tag) in expected {
            assert_eq!(dest.as_tag(), *tag, "tag changed for {dest:?}");
            assert!(!tag.is_empty(), "tag for {dest:?} must be non-empty");
            assert!(seen.insert(*tag), "tag {tag} is not unique across variants");
        }

        assert_eq!(Destination::Custom("topic_b".into()).as_tag(), "custom");
        assert_eq!(
            Destination::Custom("topic_a".into()).as_tag(),
            Destination::Custom("topic_b".into()).as_tag()
        );
    }
}
