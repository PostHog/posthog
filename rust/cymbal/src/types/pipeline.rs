use std::{future::Future, sync::Arc};

use crate::{
    app_context::AppContext,
    error::{EventError, UnhandledError},
    stages::{grouping::GroupingStage, linking::LinkingStage, resolution::ResolutionStage},
    types::{batch::Batch, event::ExceptionEvent},
};

pub trait Pipeline {
    type Item;

    fn run(
        &self,
        batch: Batch<Self::Item>,
        app_context: Arc<AppContext>,
    ) -> impl Future<Output = Result<Batch<Self::Item>, UnhandledError>>;
}

pub struct ExceptionEventPipeline {}

pub type ExceptionEventPipelineItem = Result<ExceptionEvent, EventError>;
pub type ValueOperatorResult = Result<ExceptionEventPipelineItem, UnhandledError>;

impl Pipeline for ExceptionEventPipeline {
    type Item = ExceptionEventPipelineItem;

    async fn run(
        &self,
        batch: Batch<Self::Item>,
        app_context: Arc<AppContext>,
    ) -> Result<Batch<Self::Item>, UnhandledError> {
        batch
            // Resolve stack traces
            .apply_stage(ResolutionStage::from(&app_context))
            .await?
            // Group events by fingerprint
            .apply_stage(GroupingStage::from(&app_context))
            .await?
            // Link events to issues
            .apply_stage(LinkingStage::from(&app_context))
            .await
    }
}
