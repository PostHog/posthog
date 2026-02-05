use std::sync::Arc;
mod spike_alert;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    stages::alerting::spike_alert::SpikeAlertStage,
    types::{
        batch::Batch,
        pipeline::ExceptionEventPipelineItem,
        stage::{Stage, StageResult},
    },
};

#[derive(Clone)]
pub struct AlertingStage {
    context: Arc<AppContext>,
}

impl From<&Arc<AppContext>> for AlertingStage {
    fn from(app_context: &Arc<AppContext>) -> Self {
        Self {
            context: app_context.clone(),
        }
    }
}

impl Stage for AlertingStage {
    type Input = ExceptionEventPipelineItem;
    type Output = ExceptionEventPipelineItem;
    type Error = UnhandledError;

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        batch.apply_stage(SpikeAlertStage::new(self.context)).await
    }
}
