use std::sync::Arc;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    stages::{grouping::GroupingStage, linking::LinkingStage, resolution::ResolutionStage},
    types::{batch::Batch, event::ExceptionEvent},
};

pub struct EventPipeline {}

impl EventPipeline {
    pub async fn run(
        &self,
        batch: impl Batch<ExceptionEvent>,
        app_context: Arc<AppContext>,
    ) -> Result<impl Batch<ExceptionEvent>, UnhandledError> {
        batch
            // Resolve stack traces
            .map_all(ResolutionStage::from(app_context.as_ref()))
            .await?
            // Generate fingerprints
            .apply_stage(GroupingStage::from(app_context.as_ref()))
            .await?
            // Resolve issue ids based on fingerprints
            .apply_stage(LinkingStage::from(app_context))
            .await
    }
}
