use std::sync::Arc;

pub mod issue;
pub mod rule_suppression;
pub mod suppression;

use moka::future::Cache;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    metric_consts::LINKING_STAGE,
    stages::{
        linking::{
            issue::IssueLinker, rule_suppression::RuleSuppression, suppression::IssueSuppression,
        },
        pipeline::ExceptionEventPipelineItem,
    },
    types::{
        batch::Batch,
        operator::TeamId,
        stage::{Stage, StageResult},
    },
};

#[derive(Clone)]
pub struct LinkingStage {
    pub app_context: Arc<AppContext>,
    pub issue_cache: Cache<(TeamId, String), Uuid>,
}

impl Stage for LinkingStage {
    type Input = ExceptionEventPipelineItem;
    type Output = ExceptionEventPipelineItem;

    fn name(&self) -> &'static str {
        LINKING_STAGE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        batch
            .apply_operator(RuleSuppression, self.clone())
            .await?
            .apply_operator(IssueLinker, self.clone())
            .await?
            .apply_operator(IssueSuppression, self.clone())
            .await
    }
}

impl From<&Arc<AppContext>> for LinkingStage {
    fn from(ctx: &Arc<AppContext>) -> Self {
        // The issue cache lives on AppContext so it survives across batches; cloning the
        // moka handle is just a refcount bump on the underlying Arc.
        Self {
            app_context: ctx.clone(),
            issue_cache: ctx.issue_cache.clone(),
        }
    }
}
