use crate::{
    metric_consts::RESOLUTION_STAGE,
    stages::{
        pipeline::ExceptionEventPipelineItem,
        resolution::{
            exception::ExceptionResolver, frame::FrameResolver, properties::PropertiesResolver,
            LocalResolutionStage,
        },
    },
    types::{
        batch::Batch,
        stage::{Stage, StageResult},
    },
};

impl Stage for LocalResolutionStage {
    type Input = ExceptionEventPipelineItem;
    type Output = ExceptionEventPipelineItem;

    fn name(&self) -> &'static str {
        RESOLUTION_STAGE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        batch
            .apply_operator(ExceptionResolver, self.clone())
            .await?
            .apply_operator(FrameResolver, self.clone())
            .await?
            .apply_operator(PropertiesResolver, self.clone())
            .await
    }
}
