use sqlx::PgPool;

pub mod fingerprint;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    stages::grouping::fingerprint::FingerprintGenerator,
    teams::TeamManager,
    types::{batch::Batch, event::ExceptionEvent, operator::OperatorContext, stage::Stage},
};

#[derive(Clone)]
pub struct GroupingStage {
    pub connection: PgPool,
    pub team_manager: TeamManager,
}

impl OperatorContext for GroupingStage {}

impl From<&AppContext> for GroupingStage {
    fn from(ctx: &AppContext) -> Self {
        Self {
            connection: ctx.posthog_pool.clone(),
            team_manager: ctx.team_manager.clone(),
        }
    }
}

impl Stage for GroupingStage {
    type Item = ExceptionEvent;

    async fn process(
        &self,
        batch: impl Batch<Self::Item>,
    ) -> Result<impl Batch<Self::Item>, UnhandledError> {
        batch.map(FingerprintGenerator, self).await
    }
}
