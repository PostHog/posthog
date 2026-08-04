use std::sync::Arc;

use tokio::sync::{OwnedSemaphorePermit, Semaphore};

pub mod exception;
pub mod frame;
pub mod remote;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::RESOLUTION_STAGE,
    stages::pipeline::ParsedPipelineItem,
    stages::resolution::remote::resolver::{resolve_batch, RemoteResolutionContext},
    symbolication::symbol::SymbolResolver,
    types::{
        batch::Batch,
        stage::{Stage, StageResult},
    },
};

#[derive(Clone)]
pub struct ResolutionStage {
    pub remote: RemoteResolutionContext,
}

#[derive(Clone)]
pub struct LocalResolutionContext {
    pub symbol_resolver: Arc<dyn SymbolResolver>,
    pub symbol_resolution_limiter: Arc<Semaphore>,
}

impl From<&Arc<AppContext>> for ResolutionStage {
    fn from(app_context: &Arc<AppContext>) -> Self {
        Self {
            remote: app_context
                .as_ref()
                .remote_resolution
                .clone()
                .expect("processing app context requires remote resolution"),
        }
    }
}

impl LocalResolutionContext {
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
    type Input = ParsedPipelineItem;
    // Frames are resolved in place and events stay Parsed; `EventReleaseStage` owns the
    // Parsed -> Resolved flip so release resolution can read the resolved frames.
    type Output = ParsedPipelineItem;

    fn name(&self) -> &'static str {
        RESOLUTION_STAGE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        resolve_batch(batch, self.remote).await
    }
}
