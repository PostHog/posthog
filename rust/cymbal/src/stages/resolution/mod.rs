use std::sync::Arc;

pub mod exception;
pub mod frame;
pub mod properties;
pub mod symbol;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    stages::resolution::{
        exception::ExceptionResolver, frame::FrameResolver, properties::PropertiesResolver,
        symbol::SymbolResolver,
    },
    types::{batch::Batch, pipeline::ExceptionEventPipelineItem, stage::Stage},
};

#[derive(Clone)]
pub struct ResolutionStage {
    pub symbol_resolver: Arc<dyn SymbolResolver>,
}

impl From<&Arc<AppContext>> for ResolutionStage {
    fn from(app_context: &Arc<AppContext>) -> Self {
        Self {
            symbol_resolver: app_context.as_ref().symbol_resolver.clone(),
        }
    }
}

impl Stage for ResolutionStage {
    type Item = ExceptionEventPipelineItem;

    async fn process(self, batch: Batch<Self::Item>) -> Result<Batch<Self::Item>, UnhandledError> {
        batch
            .apply_operator(ExceptionResolver, self.clone())
            .await?
            .apply_operator(FrameResolver, self.clone())
            .await?
            .apply_operator(PropertiesResolver, self.clone())
            .await
    }
}
