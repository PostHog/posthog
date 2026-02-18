use std::sync::Arc;

use sqlx::PgPool;

pub mod fingerprint;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::GROUPING_STAGE,
    stages::{grouping::fingerprint::FingerprintGenerator, pipeline::ExceptionEventPipelineItem},
    teams::TeamManager,
    types::{batch::Batch, stage::Stage},
};

#[derive(Clone)]
pub struct GroupingStage {
    pub connection: PgPool,
    pub team_manager: TeamManager,
}

impl From<&Arc<AppContext>> for GroupingStage {
    fn from(ctx: &Arc<AppContext>) -> Self {
        Self {
            connection: ctx.posthog_pool.clone(),
            team_manager: ctx.team_manager.clone(),
        }
    }
}

impl Stage for GroupingStage {
    type Input = ExceptionEventPipelineItem;
    type Output = ExceptionEventPipelineItem;
    type Error = UnhandledError;

    fn name(&self) -> &'static str {
        GROUPING_STAGE
    }

    async fn process(
        self,
        batch: Batch<Self::Input>,
    ) -> Result<Batch<Self::Output>, UnhandledError> {
        batch.apply_operator(FingerprintGenerator, self).await
    }
}
