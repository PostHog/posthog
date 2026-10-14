use common_types::CapturedEventHeaders;
use uuid::Uuid;

use crate::ordering::OrderingGuarantee;
use crate::pipeline::{Address, Lane};
use crate::v1::context::RequestContext;

pub trait Publishable: Send + Sync {
    type Lane: Lane;

    fn uuid(&self) -> Uuid;

    fn should_publish(&self) -> bool;

    /// `None` for an event the deployment does not accept, which never
    /// publishes.
    fn destination(&self) -> Option<&Address<Self::Lane>>;

    fn headers(&self, ctx: &RequestContext) -> CapturedEventHeaders;

    fn partition_key(&self, ctx: &RequestContext) -> String;

    fn ordering(&self) -> OrderingGuarantee;

    fn serialize(&self, ctx: &RequestContext) -> anyhow::Result<bytes::Bytes>;
}

#[cfg(test)]
mod destination_tests {
    use crate::event_restrictions::Pipeline;
    use crate::v1::test_utils::Destination;

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
}
