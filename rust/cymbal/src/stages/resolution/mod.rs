use std::sync::Arc;

use sqlx::PgPool;

pub mod exception;
pub mod frame;
pub mod properties;
pub mod release;
pub mod symbol;

use crate::{
    app_context::AppContext,
    metric_consts::RESOLUTION_STAGE,
    stages::pipeline::ExceptionEventPipelineItem,
    stages::resolution::{
        exception::ExceptionResolver, frame::FrameResolver, properties::PropertiesResolver,
        release::ReleaseResolver, symbol::SymbolResolver,
    },
    types::{
        batch::Batch,
        stage::{Stage, StageResult},
    },
};

#[derive(Clone)]
pub struct ResolutionStage {
    pub symbol_resolver: Arc<dyn SymbolResolver>,
    pub pool: PgPool,
}

impl From<&Arc<AppContext>> for ResolutionStage {
    fn from(app_context: &Arc<AppContext>) -> Self {
        Self {
            symbol_resolver: app_context.as_ref().symbol_resolver.clone(),
            pool: app_context.posthog_pool.clone(),
        }
    }
}

impl Stage for ResolutionStage {
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
            .apply_operator(ReleaseResolver, self.clone())
            .await?
            .apply_operator(PropertiesResolver, self.clone())
            .await
    }
}
