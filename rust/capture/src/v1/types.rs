use common_types::CapturedEventHeaders;
use uuid::Uuid;

use crate::event_restrictions::Pipeline;
use crate::ordering::OrderingGuarantee;
use crate::pipeline::{self, Address, Lane};
use crate::v1::context::RequestContext;

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub enum Destination {
    #[default]
    AnalyticsMain,
    AnalyticsHistorical,
    Overflow,
    Dlq,
    Custom(String),
    ExceptionErrorTracking,
    HeatmapMain,
    ClientIngestionWarning,
    AiEvents,
    AiEventsOverflow,
}

impl Destination {
    pub fn is_analytics_pipeline(&self) -> bool {
        matches!(self, Self::AnalyticsMain | Self::AnalyticsHistorical)
    }

    pub fn pipeline(&self) -> Option<Pipeline> {
        match self {
            Self::AnalyticsMain | Self::AnalyticsHistorical | Self::Overflow => {
                Some(Pipeline::Analytics)
            }
            Self::AiEvents | Self::AiEventsOverflow => Some(Pipeline::Ai),
            Self::ExceptionErrorTracking => Some(Pipeline::ErrorTracking),
            Self::HeatmapMain | Self::ClientIngestionWarning | Self::Dlq | Self::Custom(_) => None,
        }
    }

    /// Whether this destination accepts events without a partition key.
    pub fn absorbs_hot_keys(&self) -> bool {
        match self {
            Self::AnalyticsMain | Self::Overflow | Self::AiEventsOverflow => true,
            // Their consumers rely on per-distinct-id ordering.
            Self::AnalyticsHistorical
            | Self::Dlq
            | Self::Custom(_)
            | Self::ExceptionErrorTracking
            | Self::HeatmapMain
            | Self::ClientIngestionWarning
            | Self::AiEvents => false,
        }
    }

    pub fn writes_persons(&self) -> bool {
        match self {
            Self::AnalyticsMain | Self::AnalyticsHistorical | Self::Overflow => true,
            // Replayed into analytics ingestion.
            Self::Dlq | Self::Custom(_) => true,
            Self::AiEvents
            | Self::AiEventsOverflow
            | Self::ExceptionErrorTracking
            | Self::HeatmapMain
            | Self::ClientIngestionWarning => false,
        }
    }

    pub fn address(&self) -> Address {
        let lane = |pipeline, lane| Address::Lane { pipeline, lane };
        match self {
            Self::AnalyticsMain => lane(pipeline::Pipeline::Analytics, Lane::Main),
            Self::AnalyticsHistorical => lane(pipeline::Pipeline::Analytics, Lane::Historical),
            Self::Overflow => lane(pipeline::Pipeline::Analytics, Lane::Overflow),
            Self::AiEvents => lane(pipeline::Pipeline::Ai, Lane::Main),
            Self::AiEventsOverflow => lane(pipeline::Pipeline::Ai, Lane::Overflow),
            Self::ExceptionErrorTracking => lane(pipeline::Pipeline::ErrorTracking, Lane::Main),
            Self::HeatmapMain => lane(pipeline::Pipeline::Heatmaps, Lane::Main),
            Self::ClientIngestionWarning => lane(pipeline::Pipeline::Warnings, Lane::Main),
            Self::Dlq => Address::Dlq,
            Self::Custom(topic) => Address::Custom(topic.clone()),
        }
    }
}

/// What [`crate::v1::prepare::serialize_batch`] reads from a request event to
/// build its [`PreparedEvent`](crate::outputs::PreparedEvent).
pub trait Publishable: Send + Sync {
    fn uuid(&self) -> Uuid;

    fn should_publish(&self) -> bool;

    fn destination(&self) -> &Destination;

    fn headers(&self, ctx: &RequestContext) -> CapturedEventHeaders;

    /// [`Publishable::ordering`] decides whether the record carries this key.
    fn partition_key(&self, ctx: &RequestContext) -> String;

    fn ordering(&self) -> OrderingGuarantee;

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
    fn address_matches_the_v0_destination(
        #[case] destination: Destination,
        #[case] expected: Option<V0Destination>,
    ) {
        let v0 = V0Destination::for_address(destination.address());
        assert_eq!(v0, expected);
    }
}
