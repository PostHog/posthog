use std::sync::Arc;

pub mod issue;

use moka::future::{Cache, CacheBuilder};

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    issue_resolution::Issue,
    stages::linking::issue::IssueLinker,
    types::{batch::Batch, operator::TeamId, pipeline::ExceptionEventPipelineItem, stage::Stage},
};

#[derive(Clone)]
pub struct LinkingStage {
    pub app_context: Arc<AppContext>,
    pub issue_cache: Cache<(TeamId, String), Issue>,
}

impl Stage for LinkingStage {
    type Item = ExceptionEventPipelineItem;

    async fn process(self, batch: Batch<Self::Item>) -> Result<Batch<Self::Item>, UnhandledError> {
        batch.apply_operator(IssueLinker, self).await
    }
}

impl From<&Arc<AppContext>> for LinkingStage {
    fn from(ctx: &Arc<AppContext>) -> Self {
        let issue_cache = CacheBuilder::new(1000).build();
        Self {
            app_context: ctx.clone(),
            issue_cache,
        }
    }
}
