use std::sync::Arc;

use common_types::ClickHouseEvent;

use crate::{
    app_context::AppContext,
    error::EventError,
    metric_consts::EXCEPTION_PROCESSING_PIPELINE,
    modes::processing::batch_budget::BatchBudget,
    stages::{
        adaptive_ingestion::AdaptiveIngestionStage,
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
        let ctx = &self.app_context;
        let mut budget = BatchBudget::start(ctx.main_lane_budget);
        let budget_deadline = budget.deadline();

        // Resolve stack traces and the event-level release
        let batch = budget.end_stage(
            "resolution",
            batch.apply_stage(ResolutionStage::from(ctx)).await,
        )?;
        // Group events by fingerprint
        let batch = budget.end_stage(
            "grouping",
            batch.apply_stage(GroupingStage::from(ctx)).await,
        )?;
        // Link events to issues and suppress
        let linking = LinkingStage {
            budget_deadline,
            ..LinkingStage::from(ctx)
        };
        let batch = budget.end_stage("linking", batch.apply_stage(linking).await)?;
        // Drop rate-limited events as soon as issue_id is known — before
        // alerting/enrichment, so spike detection never counts them.
        let batch = budget.end_stage(
            "rate_limiting",
            batch.apply_stage(RateLimitingStage::from(ctx)).await,
        )?;
        let batch = budget.end_stage(
            "adaptive_ingestion",
            batch.apply_stage(AdaptiveIngestionStage::from(ctx)).await,
        )?;
        // Send internal events for alerting
        budget.end_stage(
            "alerting",
            batch.apply_stage(AlertingStage::from(ctx)).await,
        )
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
