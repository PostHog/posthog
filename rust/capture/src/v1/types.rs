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
    AnalyticsOverflow,
    Dlq,
    Custom(String),
    ExceptionErrorTracking,
    HeatmapMain,
    ClientIngestionWarning,
    AiEvents,
    AiEventsOverflow,
}

impl Destination {
    pub fn pipeline(&self) -> Option<Pipeline> {
        match self {
            Self::AnalyticsMain | Self::AnalyticsHistorical | Self::AnalyticsOverflow => {
                Some(Pipeline::Analytics)
            }
            Self::AiEvents | Self::AiEventsOverflow => Some(Pipeline::Ai),
            Self::ExceptionErrorTracking => Some(Pipeline::ErrorTracking),
            Self::HeatmapMain | Self::ClientIngestionWarning | Self::Dlq | Self::Custom(_) => None,
        }
    }

    pub fn absorbs_hot_keys(&self) -> bool {
        match self {
            Self::AnalyticsMain | Self::AnalyticsOverflow | Self::AiEventsOverflow => true,
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
            Self::AnalyticsMain | Self::AnalyticsHistorical | Self::AnalyticsOverflow => true,
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
            Self::AnalyticsOverflow => lane(pipeline::Pipeline::Analytics, Lane::Overflow),
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

pub trait Publishable: Send + Sync {
    fn uuid(&self) -> Uuid;

    fn should_publish(&self) -> bool;

    fn destination(&self) -> &Destination;

    fn headers(&self, ctx: &RequestContext) -> CapturedEventHeaders;

    fn partition_key(&self, ctx: &RequestContext) -> String;

    fn ordering(&self) -> OrderingGuarantee;

    fn serialize(&self, ctx: &RequestContext) -> anyhow::Result<bytes::Bytes>;
}

#[cfg(test)]
mod destination_tests {
    use super::Destination;
    use crate::event_restrictions::Pipeline;
    use crate::sinks::registry::Destination as V0Destination;

    #[rstest::rstest]
    #[case(Destination::AnalyticsMain, Some(Pipeline::Analytics))]
    #[case(Destination::AnalyticsHistorical, Some(Pipeline::Analytics))]
    #[case(Destination::AnalyticsOverflow, Some(Pipeline::Analytics))]
    #[case(Destination::AiEvents, Some(Pipeline::Ai))]
    #[case(Destination::AiEventsOverflow, Some(Pipeline::Ai))]
    #[case(Destination::ExceptionErrorTracking, Some(Pipeline::ErrorTracking))]
    #[case(Destination::HeatmapMain, None)]
    #[case(Destination::ClientIngestionWarning, None)]
    #[case(Destination::Dlq, None)]
    #[case(Destination::Custom("admin_topic".into()), None)]
    fn pipeline_classifies_every_destination(
        #[case] destination: Destination,
        #[case] expected: Option<Pipeline>,
    ) {
        assert_eq!(destination.pipeline(), expected);
    }

    #[rstest::rstest]
    #[case(Destination::AnalyticsMain, Some(V0Destination::AnalyticsMain))]
    #[case(
        Destination::AnalyticsHistorical,
        Some(V0Destination::AnalyticsHistorical)
    )]
    #[case(Destination::AnalyticsOverflow, Some(V0Destination::AnalyticsOverflow))]
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
