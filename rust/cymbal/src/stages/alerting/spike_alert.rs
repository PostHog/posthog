use std::sync::Arc;

use crate::{
    app_context::AppContext,
    metric_consts::SPIKE_ALERT_STAGE,
    stages::{
        alerting::{run_spike_detection_for_inputs, SpikeAlertInput},
        pipeline::ExceptionEventPipelineItem,
    },
    types::{
        batch::Batch,
        stage::{Stage, StageResult},
    },
};

use tracing::error;

#[derive(Clone)]
pub struct SpikeAlertStage {
    context: Arc<AppContext>,
}

impl SpikeAlertStage {
    pub fn new(context: Arc<AppContext>) -> Self {
        Self { context }
    }
}

impl Stage for SpikeAlertStage {
    type Input = ExceptionEventPipelineItem;
    type Output = ExceptionEventPipelineItem;

    fn name(&self) -> &'static str {
        SPIKE_ALERT_STAGE
    }

    async fn process(self, batch: Batch<ExceptionEventPipelineItem>) -> StageResult<Self> {
        let mut inputs: Vec<SpikeAlertInput> = Vec::new();

        for res in batch.inner_ref() {
            let Ok(evt) = res else { continue };
            let Some(issue) = &evt.issue else {
                error!("no issue associated with event");
                continue;
            };
            inputs.push(SpikeAlertInput {
                issue: issue.clone(),
                props: evt.to_output(issue.id).ok(),
            });
        }

        run_spike_detection_for_inputs(self.context, inputs).await?;

        Ok(batch)
    }
}
