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
        resolution::ResolutionStage,
    },
    types::{
        batch::Batch,
        exception_event::{ExceptionEvent, Fingerprinted, Linked, Raw},
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

/// The carried batch item at each pipeline stage. The stage marker advances
/// Raw -> Fingerprinted -> Linked; a per-item `EventError` rides along as `Err`
/// (suppressed / failed) without aborting the batch.
pub type RawItem = Result<ExceptionEvent<Raw>, EventError>;
pub type FingerprintedItem = Result<ExceptionEvent<Fingerprinted>, EventError>;
pub type LinkedItem = Result<ExceptionEvent<Linked>, EventError>;

impl Stage for ExceptionEventPipeline {
    type Input = RawItem;
    type Output = LinkedItem;

    fn name(&self) -> &'static str {
        EXCEPTION_PROCESSING_PIPELINE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        batch
            // Resolve stack traces (Raw -> Raw)
            .apply_stage(ResolutionStage::from(&self.app_context))
            .await?
            // Group events by fingerprint (Raw -> Fingerprinted)
            .apply_stage(GroupingStage::from(&self.app_context))
            .await?
            // Link events to issues and suppress (Fingerprinted -> Linked)
            .apply_stage(LinkingStage::from(&self.app_context))
            .await?
            // Send internal events for alerting (Linked -> Linked)
            .apply_stage(AlertingStage::from(&self.app_context))
            .await
    }
}

pub fn create_pre_post_processing<
    T: TryInto<ExceptionEvent<Raw>, Error = EventError> + Clone,
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
