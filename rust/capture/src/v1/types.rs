use common_types::CapturedEventHeaders;
use uuid::Uuid;

use crate::event_restrictions::Pipeline;
use crate::ordering::OrderingGuarantee;
use crate::pipeline::{Address, AiLane, AnalyticsLane, BasicLane, PipelineLane};
use crate::v1::context::RequestContext;

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub enum Destination {
    #[default]
    AnalyticsMain,
    AnalyticsHistorical,
    AnalyticsOverflow,
    Dlq,
    Custom(String),
    ErrorTrackingMain,
    HeatmapsMain,
    ClientWarningsMain,
    AiMain,
    AiOverflow,
}

impl Destination {
    pub fn pipeline(&self) -> Option<Pipeline> {
        match self {
            Self::AnalyticsMain | Self::AnalyticsHistorical | Self::AnalyticsOverflow => {
                Some(Pipeline::Analytics)
            }
            Self::AiMain | Self::AiOverflow => Some(Pipeline::Ai),
            Self::ErrorTrackingMain => Some(Pipeline::ErrorTracking),
            Self::HeatmapsMain => Some(Pipeline::Heatmaps),
            Self::ClientWarningsMain => Some(Pipeline::ClientWarnings),
            Self::Dlq | Self::Custom(_) => None,
        }
    }

    pub fn absorbs_hot_keys(&self) -> bool {
        match self {
            Self::AnalyticsMain | Self::AnalyticsOverflow | Self::AiOverflow => true,
            Self::AnalyticsHistorical
            | Self::Dlq
            | Self::Custom(_)
            | Self::ErrorTrackingMain
            | Self::HeatmapsMain
            | Self::ClientWarningsMain
            | Self::AiMain => false,
        }
    }

    pub fn writes_persons(&self) -> bool {
        match self {
            Self::AnalyticsMain | Self::AnalyticsHistorical | Self::AnalyticsOverflow => true,
            Self::Dlq | Self::Custom(_) => true,
            Self::AiMain
            | Self::AiOverflow
            | Self::ErrorTrackingMain
            | Self::HeatmapsMain
            | Self::ClientWarningsMain => false,
        }
    }

    pub fn address(&self) -> Address {
        match self {
            Self::AnalyticsMain => Address::Lane(PipelineLane::Analytics(AnalyticsLane::Main)),
            Self::AnalyticsHistorical => {
                Address::Lane(PipelineLane::Analytics(AnalyticsLane::Historical))
            }
            Self::AnalyticsOverflow => {
                Address::Lane(PipelineLane::Analytics(AnalyticsLane::Overflow))
            }
            Self::AiMain => Address::Lane(PipelineLane::Ai(AiLane::Main)),
            Self::AiOverflow => Address::Lane(PipelineLane::Ai(AiLane::Overflow)),
            Self::ErrorTrackingMain => Address::Lane(PipelineLane::ErrorTracking(BasicLane::Main)),
            Self::HeatmapsMain => Address::Lane(PipelineLane::Heatmaps(BasicLane::Main)),
            Self::ClientWarningsMain => Address::Lane(PipelineLane::Warnings(BasicLane::Main)),
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
    #[case(Destination::AiMain, Some(Pipeline::Ai))]
    #[case(Destination::AiOverflow, Some(Pipeline::Ai))]
    #[case(Destination::ErrorTrackingMain, Some(Pipeline::ErrorTracking))]
    #[case(Destination::HeatmapsMain, Some(Pipeline::Heatmaps))]
    #[case(Destination::ClientWarningsMain, Some(Pipeline::ClientWarnings))]
    #[case(Destination::Dlq, None)]
    #[case(Destination::Custom("admin_topic".into()), None)]
    fn pipeline_classifies_every_destination(
        #[case] destination: Destination,
        #[case] expected: Option<Pipeline>,
    ) {
        assert_eq!(destination.pipeline(), expected);
    }

    #[rstest::rstest]
    #[case(Destination::AnalyticsMain, V0Destination::AnalyticsMain)]
    #[case(Destination::AnalyticsHistorical, V0Destination::AnalyticsHistorical)]
    #[case(Destination::AnalyticsOverflow, V0Destination::AnalyticsOverflow)]
    #[case(Destination::Dlq, V0Destination::Dlq)]
    #[case(Destination::Custom("admin_topic".into()), V0Destination::Custom("admin_topic".into()))]
    #[case(Destination::ErrorTrackingMain, V0Destination::ErrorTrackingMain)]
    #[case(Destination::HeatmapsMain, V0Destination::HeatmapsMain)]
    #[case(Destination::ClientWarningsMain, V0Destination::ClientWarningsMain)]
    #[case(Destination::AiMain, V0Destination::AiMain)]
    #[case(Destination::AiOverflow, V0Destination::AiOverflow)]
    fn address_matches_the_v0_destination(
        #[case] destination: Destination,
        #[case] expected: V0Destination,
    ) {
        let v0 = V0Destination::for_address(destination.address());
        assert_eq!(v0, expected);
    }
}
