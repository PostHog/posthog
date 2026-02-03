use std::sync::Arc;

pub mod exception;
pub mod exception_list;
pub mod frame;
pub mod properties;
pub mod stack;
pub mod symbol;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    stages::resolution::{
        frame::FrameResolver, properties::PropertiesResolver, symbol::SymbolResolver,
    },
    types::{batch::Batch, event::ExceptionEvent, operator::OperatorContext, stage::Stage},
};

#[derive(Clone)]
pub struct ResolutionStage {
    pub symbol_resolver: Arc<dyn SymbolResolver>,
}

impl OperatorContext for ResolutionStage {}

impl From<&AppContext> for ResolutionStage {
    fn from(app_context: &AppContext) -> Self {
        Self {
            symbol_resolver: app_context.local_symbol_resolver.clone(),
        }
    }
}

impl Stage for ResolutionStage {
    type Item = ExceptionEvent;

    async fn process(
        &self,
        batch: impl Batch<Self::Item>,
    ) -> Result<impl Batch<Self::Item>, UnhandledError> {
        batch
            .map(FrameResolver, self)
            .await?
            .map(PropertiesResolver, self)
            .await
    }
}
