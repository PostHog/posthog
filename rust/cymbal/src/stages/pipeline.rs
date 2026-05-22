use std::sync::Arc;

use common_types::ClickHouseEvent;
use moka::future::Cache;

use crate::{
    app_context::AppContext,
    error::EventError,
    issue_resolution::Issue,
    metric_consts::EXCEPTION_PROCESSING_PIPELINE,
    stages::{
        grouping::GroupingStage,
        linking::LinkingStage,
        post_processing::{PostProcessingHandler, PostProcessingStage},
        pre_processing::{PreProcessingContext, PreProcessingStage},
        resolution::ResolutionStage,
    },
    types::{
        batch::Batch,
        exception_properties::ExceptionProperties,
        operator::TeamId,
        stage::{Stage, StageResult},
    },
};

/// Core exception processing pipeline shared by HTTP endpoints. It resolves,
/// groups, and links events while preserving handled `EventError`s in-band.
/// Endpoint-specific pipelines decide how to adapt results and when to run
/// alerting.
pub struct ExceptionEventPipeline {
    app_context: Arc<AppContext>,
    /// Optional override for `LinkingStage::batch_issue_cache`. When `Some`,
    /// the supplied cache is reused; when `None`, the linking stage allocates
    /// a fresh per-batch cache. The `/v2/resolve` handler creates one cache
    /// per request and threads it through so every per-event invocation
    /// shares the same fingerprint -> Issue dedup.
    batch_issue_cache: Option<Cache<(TeamId, String), Issue>>,
}

impl ExceptionEventPipeline {
    pub fn new(
        app_context: Arc<AppContext>,
        batch_issue_cache: Option<Cache<(TeamId, String), Issue>>,
    ) -> Self {
        Self {
            app_context,
            batch_issue_cache,
        }
    }
}

pub type EventPipelineItem = Result<ClickHouseEvent, EventError>;
pub type HandledError = EventError;

pub type ExceptionEventPipelineItem = Result<ExceptionProperties, EventError>;

impl Stage for ExceptionEventPipeline {
    type Input = ExceptionEventPipelineItem;
    type Output = ExceptionEventPipelineItem;

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
            .apply_stage(LinkingStage::new(&self.app_context, self.batch_issue_cache))
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
