use std::sync::Arc;

pub mod issue;
pub mod suppression;

use moka::future::{Cache, CacheBuilder};

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    issue_resolution::Issue,
    metric_consts::LINKING_STAGE,
    stages::{
        linking::{issue::IssueLinker, suppression::IssueSuppression},
        pipeline::ExceptionEventPipelineItem,
    },
    types::{batch::Batch, operator::TeamId, stage::Stage},
};

#[derive(Clone)]
pub struct LinkingStage {
    pub app_context: Arc<AppContext>,
    pub issue_cache: Cache<(TeamId, String), Issue>,
}

impl Stage for LinkingStage {
    type Input = ExceptionEventPipelineItem;
    type Output = ExceptionEventPipelineItem;
    type Error = UnhandledError;

    fn name(&self) -> &'static str {
        LINKING_STAGE
    }

    async fn process(self, batch: Batch<Self::Input>) -> Result<Batch<Self::Output>, Self::Error> {
        batch
            .apply_operator(IssueLinker, self.clone())
            .await?
            .apply_operator(IssueSuppression, self.clone())
            .await
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
