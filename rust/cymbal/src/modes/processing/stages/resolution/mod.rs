use std::sync::Arc;

use tokio::sync::{OwnedSemaphorePermit, Semaphore};

pub mod exception;
pub mod frame;
pub mod properties;
pub mod remote;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::RESOLUTION_STAGE,
    stages::pipeline::ExceptionEventPipelineItem,
    stages::resolution::{
        exception::ExceptionResolver,
        frame::FrameResolver,
        properties::PropertiesResolver,
        remote::resolver::{resolve_batch, RemoteResolutionContext},
    },
    symbolication::symbol::SymbolResolver,
    types::{
        batch::Batch,
        stage::{Stage, StageResult},
    },
};

#[derive(Clone)]
pub struct ResolutionStage {
    pub symbol_resolver: Arc<dyn SymbolResolver>,
    pub symbol_resolution_limiter: Arc<Semaphore>,
    /// When `Some`, the resolution stage can route sampled events through the
    /// remote `cymbal.resolution.v1` client path. Unsampled events still use
    /// local exception+frame resolution. There is no local fallback for events
    /// selected for remote processing: if the remote pool can't serve the
    /// request, the orchestration layer surfaces an unhandled error.
    pub remote: Option<RemoteResolutionContext>,
}

impl From<&Arc<AppContext>> for ResolutionStage {
    fn from(app_context: &Arc<AppContext>) -> Self {
        Self {
            symbol_resolver: app_context.as_ref().symbol_resolver.clone(),
            symbol_resolution_limiter: app_context.as_ref().symbol_resolution_limiter.clone(),
            remote: app_context.as_ref().remote_resolution.clone(),
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
        if let Some(remote) = self.remote.clone() {
            // Remote mode: the stage owns orchestration across the incoming
            // batch, including deterministic rollout sampling. Sampled events
            // use grouped exception-level Resolve items, and unsampled events use
            // the local exception/frame operators. PropertiesResolver still
            // runs afterwards because it operates on the resolved exception
            // list shape independently of how exception/frame resolution was
            // performed.
            return resolve_batch(batch, remote, self.clone())
                .await?
                .apply_operator(PropertiesResolver, self.clone())
                .await;
        }

        batch
            .apply_operator(ExceptionResolver, self.clone())
            .await?
            .apply_operator(FrameResolver, self.clone())
            .await?
            .apply_operator(PropertiesResolver, self.clone())
            .await
    }
}
