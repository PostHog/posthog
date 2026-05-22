use std::sync::Arc;

use common_types::ClickHouseEvent;
use moka::future::Cache;

use crate::{
    app_context::AppContext,
    error::EventError,
    issue_resolution::Issue,
    metric_consts::EXCEPTION_PROCESSING_PIPELINE,
    stages::{
        alerting::{AlertingStage, SpikeAlertAccumulator},
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

pub struct ExceptionEventPipeline {
    app_context: Arc<AppContext>,
    /// Optional override for `LinkingStage::batch_issue_cache`. When `Some`,
    /// the supplied cache is reused; when `None`, the linking stage allocates
    /// a fresh per-batch cache. The `/v2/resolve` handler creates one cache
    /// per request and threads it through so every per-event invocation
    /// shares the same fingerprint -> Issue dedup.
    batch_issue_cache: Option<Cache<(TeamId, String), Issue>>,
    /// Optional accumulator for deferring spike-alert work. When `Some`, the
    /// alerting stage records events into shared state instead of calling
    /// Redis; the `/v2` handler runs spike detection once at end-of-request
    /// with the merged inputs. When `None`, spike detection runs inline at
    /// the end of this batch (legacy `/process` behaviour).
    spike_alert_accumulator: Option<Arc<SpikeAlertAccumulator>>,
}

impl ExceptionEventPipeline {
    pub fn new(
        app_context: Arc<AppContext>,
        batch_issue_cache: Option<Cache<(TeamId, String), Issue>>,
        spike_alert_accumulator: Option<Arc<SpikeAlertAccumulator>>,
    ) -> Self {
        Self {
            app_context,
            batch_issue_cache,
            spike_alert_accumulator,
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
            .await?
            // Send internal events for alerting (deferred if accumulator is Some)
            .apply_stage(AlertingStage::new(
                self.app_context,
                self.spike_alert_accumulator,
            ))
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
