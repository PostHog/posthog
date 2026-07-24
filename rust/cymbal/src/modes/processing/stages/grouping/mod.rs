use std::sync::Arc;

use moka::future::Cache;
use sqlx::PgPool;
use uuid::Uuid;

pub mod fingerprint;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::GROUPING_STAGE,
    stages::{
        grouping::fingerprint::FingerprintGenerator,
        pipeline::{FingerprintedPipelineItem, ResolvedPipelineItem},
    },
    teams::TeamManager,
    types::{batch::Batch, operator::TeamId, stage::Stage},
};

#[derive(Clone)]
pub struct GroupingStage {
    pub connection: PgPool,
    pub team_manager: TeamManager,
    pub issue_cache: Cache<(TeamId, String), Uuid>,
}

impl From<&Arc<AppContext>> for GroupingStage {
    fn from(ctx: &Arc<AppContext>) -> Self {
        Self {
            connection: ctx.posthog_pool.clone(),
            team_manager: ctx.team_manager.clone(),
            issue_cache: ctx.issue_cache.clone(),
        }
    }
}

impl Stage for GroupingStage {
    type Input = ResolvedPipelineItem;
    type Output = FingerprintedPipelineItem;

    fn name(&self) -> &'static str {
        GROUPING_STAGE
    }

    async fn process(
        self,
        batch: Batch<Self::Input>,
    ) -> Result<Batch<Self::Output>, UnhandledError> {
        let operator = FingerprintGenerator;
        let timing = common_metrics::timing_guard(operator.name(), &[]);
        let output = batch
            .apply_func(
                move |item, context| {
                    let operator = operator.clone();
                    async move { operator.execute(item, context).await }
                },
                self,
            )
            .await?;
        timing.label("outcome", "success");
        Ok(output)
    }
}
