use std::sync::Arc;

use sqlx::PgPool;
use tokio::sync::{OwnedSemaphorePermit, Semaphore};

pub mod event_release;
pub mod exception;
pub mod frame;
pub mod remote;
pub mod rendezvous;
pub mod repo_paths;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::RESOLUTION_STAGE,
    stages::pipeline::{ParsedPipelineItem, ResolvedPipelineItem},
    stages::resolution::event_release::{EventReleaseResolver, ReleaseCache},
    stages::resolution::remote::resolver::{resolve_batch, RemoteResolutionContext},
    stages::resolution::repo_paths::{RawPaths, RepoPathContext, RepoPathResolver},
    symbolication::symbol::SymbolResolver,
    types::{
        batch::Batch,
        stage::{Stage, StageResult},
    },
};

#[derive(Clone)]
pub struct ResolutionStage {
    pub remote: RemoteResolutionContext,
    pub posthog_pool: PgPool,
    pub release_cache: ReleaseCache,
    pub repo_paths: Option<Arc<RepoPathContext>>,
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
            posthog_pool: app_context.posthog_pool.clone(),
            release_cache: app_context.release_cache.clone(),
            repo_paths: app_context.repo_paths.clone(),
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
    type Output = ResolvedPipelineItem;

    fn name(&self) -> &'static str {
        RESOLUTION_STAGE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        // Release resolution runs after resolve_batch so it can later fall back to the resolved
        // frames' symbol sets for legacy events.
        let repo_paths = self.repo_paths.clone();
        // Remote resolution drops the raw frames, so their runtime paths are read first.
        let raw_paths: Option<Vec<RawPaths>> = repo_paths.as_ref().map(|_| {
            batch
                .inner_ref()
                .iter()
                .map(|item| {
                    item.as_ref()
                        .map(|evt| RawPaths::collect(evt.exception_list()))
                        .unwrap_or_default()
                })
                .collect()
        });

        let resolved = resolve_batch(batch, self.remote.clone()).await?;
        let resolved = resolved.apply_operator(EventReleaseResolver, self).await?;
        let resolved = match raw_paths {
            Some(raw_paths) => resolved.map(
                |mut item, raw_paths| {
                    if let (Ok(evt), Some(paths)) = (&mut item, raw_paths.next()) {
                        paths.attach(evt.exception_list_mut());
                    }
                    item
                },
                &mut raw_paths.into_iter(),
            ),
            None => resolved,
        };
        let resolved = resolved
            .apply_operator(RepoPathResolver, repo_paths)
            .await?;
        Ok(resolved.map(|item, ()| item.map(|event| event.into_resolved()), &mut ()))
    }
}
