use std::sync::Arc;

use common_types::ClickHouseEvent;

use crate::{
    app_context::AppContext,
    error::{EventError, UnhandledError},
    metric_consts::EXCEPTION_PROCESSING_PIPELINE,
    stages::{
        alerting::AlertingStage,
        grouping::GroupingStage,
        linking::LinkingStage,
        post_processing::{PostProcessingHandler, PostProcessingStage},
        pre_processing::{PreProcessingContext, PreProcessingStage},
        resolution::ResolutionStage,
    },
    types::{batch::Batch, exception_properties::ExceptionProperties, stage::Stage},
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

pub type ExceptionEventPipelineItem = Result<ExceptionProperties, EventError>;

impl Stage for ExceptionEventPipeline {
    type Input = ExceptionEventPipelineItem;
    type Output = ExceptionEventPipelineItem;
    type Error = UnhandledError;

    fn name(&self) -> &'static str {
        EXCEPTION_PROCESSING_PIPELINE
    }

    async fn process(
        self,
        batch: Batch<Self::Input>,
    ) -> Result<Batch<Self::Output>, UnhandledError> {
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
            // Send internal events for alerting
            .apply_stage(AlertingStage::from(&self.app_context))
            .await
    }
}

pub fn create_pre_post_processing<
    T: TryInto<ExceptionProperties, Error = EventError> + Clone,
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
