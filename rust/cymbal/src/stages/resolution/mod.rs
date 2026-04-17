use std::sync::Arc;

use tokio::sync::{OwnedSemaphorePermit, Semaphore};

pub mod distributed;
pub mod exception;
pub mod frame;
mod local;
pub mod properties;
pub mod symbol;

use crate::{app_context::AppContext, error::UnhandledError};

pub use distributed::DistributedResolutionStage;

use symbol::SymbolResolver;

#[derive(Clone)]
pub struct LocalResolutionStage {
    pub symbol_resolver: Arc<dyn SymbolResolver>,
    pub symbol_resolution_limiter: Arc<Semaphore>,
}

impl LocalResolutionStage {
    pub fn from_parts(
        symbol_resolver: Arc<dyn SymbolResolver>,
        symbol_resolution_limiter: Arc<Semaphore>,
    ) -> Self {
        Self {
            symbol_resolver,
            symbol_resolution_limiter,
        }
    }

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

impl From<&Arc<AppContext>> for LocalResolutionStage {
    fn from(app_context: &Arc<AppContext>) -> Self {
        Self::from_parts(
            app_context.as_ref().symbol_resolver.clone(),
            app_context.as_ref().symbol_resolution_limiter.clone(),
        )
    }
}
