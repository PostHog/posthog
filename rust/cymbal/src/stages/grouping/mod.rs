use std::sync::Arc;

use sqlx::PgPool;

pub mod fingerprint;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    stages::grouping::fingerprint::FingerprintGenerator,
    teams::TeamManager,
    types::{batch::Batch, event::ExceptionEvent, stage::Stage},
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
    type Item = ExceptionEvent;

    async fn process(self, batch: Batch<Self::Item>) -> Result<Batch<Self::Item>, UnhandledError> {
        batch.apply_operator(FingerprintGenerator, self).await
    }
}
