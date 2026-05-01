use std::sync::Arc;

use tokio::sync::{OwnedSemaphorePermit, Semaphore};

pub mod exception;
pub mod frame;
pub mod properties;
pub mod symbol;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::RESOLUTION_STAGE,
    stages::pipeline::ExceptionEventPipelineItem,
    stages::resolution::{
        exception::ExceptionResolver, frame::FrameResolver, properties::PropertiesResolver,
        symbol::SymbolResolver,
    },
    types::{
        batch::Batch,
        stage::{Stage, StageResult},
    },
};

#[derive(Clone)]
pub struct ResolutionStage {
    pub symbol_resolver: Arc<dyn SymbolResolver>,
    pub symbol_resolution_limiter: Arc<Semaphore>,
}

impl From<&Arc<AppContext>> for ResolutionStage {
    fn from(app_context: &Arc<AppContext>) -> Self {
        Self {
            symbol_resolver: app_context.as_ref().symbol_resolver.clone(),
            symbol_resolution_limiter: app_context.as_ref().symbol_resolution_limiter.clone(),
        }
    }
}

impl ResolutionStage {
    pub async fn acquire_symbol_resolution_permit(
        &self,
    ) -> Result<OwnedSemaphorePermit, UnhandledError> {
        self.symbol_resolution_limiter
            .clone()
            .acquire_owned()
            .await
            .map_err(|_| UnhandledError::Other("Symbol resolution limiter is closed".to_string()))
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
            .apply_operator(PropertiesResolver, self.clone())
            .await
    }
}
