use std::sync::Arc;

use common_types::ClickHouseEvent;

use crate::{
    app_context::AppContext,
    error::EventError,
    metric_consts::EXCEPTION_PROCESSING_PIPELINE,
    stages::{
        alerting::AlertingStage,
        grouping::GroupingStage,
        linking::LinkingStage,
        post_processing::{PostProcessingHandler, PostProcessingStage},
        pre_processing::{PreProcessingContext, PreProcessingStage},
        rate_limiting::RateLimitingStage,
        resolution::ResolutionStage,
    },
    types::{
        batch::Batch,
        exception_event::{
            ExceptionEvent, Finalized, Fingerprinted, Linked, Parsed, PipelineItem, RateChecked,
            Resolved,
        },
        stage::{Stage, StageResult},
    },
};

pub struct ExceptionEventPipeline {
    app_context: Arc<AppContext>,
}

impl ExceptionEventPipeline {
    pub fn new(app_context: Arc<AppContext>) -> Self {
        Self { app_context }
    }
}

pub type EventPipelineItem = Result<ClickHouseEvent, EventError>;
pub type HandledError = EventError;

pub type ParsedPipelineItem = PipelineItem<Parsed>;
pub type ResolvedPipelineItem = PipelineItem<Resolved>;
pub type FingerprintedPipelineItem = PipelineItem<Fingerprinted>;
pub type LinkedPipelineItem = PipelineItem<Linked>;
pub type RateCheckedPipelineItem = PipelineItem<RateChecked>;
pub type FinalizedPipelineItem = PipelineItem<Finalized>;

impl Stage for ExceptionEventPipeline {
    type Input = ParsedPipelineItem;
    type Output = FinalizedPipelineItem;

    fn name(&self) -> &'static str {
        EXCEPTION_PROCESSING_PIPELINE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        batch
            // Resolve stack traces
            .apply_stage(ResolutionStage::from(&self.app_context))
            .await?
            // Group events by fingerprint
            .apply_stage(GroupingStage::from(&self.app_context))
            .await?
            // Link events to issues and suppress
            .apply_stage(LinkingStage::from(&self.app_context))
            .await?
            // Drop rate-limited events as soon as issue_id is known — before
            // alerting/enrichment, so spike detection never counts them.
            .apply_stage(RateLimitingStage::from(&self.app_context))
            .await?
            // Send internal events for alerting
            .apply_stage(AlertingStage::from(&self.app_context))
            .await
    }
}

pub fn create_pre_post_processing<
    T: TryInto<ExceptionEvent<Parsed>, Error = EventError> + Clone,
    O,
>(
    capacity: usize,
    handler: PostProcessingHandler<T, O>,
) -> (PreProcessingStage<T>, PostProcessingStage<T, O>) {
    let preprocess_ctx = PreProcessingContext::new(capacity);
    let preprocessing_stage = PreProcessingStage::new(preprocess_ctx.clone());
    let postprocessing_stage = PostProcessingStage::new(preprocess_ctx.clone(), handler);
    (preprocessing_stage, postprocessing_stage)
}
