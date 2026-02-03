use std::sync::Arc;

pub mod issue;

use moka::future::{Cache, CacheBuilder};

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    issue_resolution::Issue,
    stages::linking::issue::IssueLinker,
    types::{
        batch::Batch,
        event::ExceptionEvent,
        operator::{OperatorContext, TeamId},
        stage::Stage,
    },
};

#[derive(Clone)]
pub struct LinkingStage {
    pub app_context: Arc<AppContext>,
    pub issue_cache: Cache<(TeamId, String), Issue>,
}

impl OperatorContext for LinkingStage {}

impl Stage for LinkingStage {
    type Item = ExceptionEvent;

    async fn process(
        &self,
        batch: Batch<ExceptionEvent>,
    ) -> Result<Batch<ExceptionEvent>, UnhandledError> {
        batch.spawn(IssueLinker, self).await
    }
}

impl From<Arc<AppContext>> for LinkingStage {
    fn from(ctx: Arc<AppContext>) -> Self {
        let issue_cache = CacheBuilder::new(1000).build();
        Self {
            app_context: ctx.clone(),
            issue_cache,
        }
    }
}
