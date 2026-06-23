use std::sync::Arc;

use sqlx::PgPool;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    fingerprinting::Fingerprint,
    metric_consts::GROUPING_STAGE,
    modes::processing::rules::grouping::evaluate_grouping_rules,
    stages::pipeline::{FingerprintedItem, RawItem},
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
    type Input = RawItem;
    type Output = FingerprintedItem;

    fn name(&self) -> &'static str {
        GROUPING_STAGE
    }

    async fn process(
        self,
        batch: Batch<Self::Input>,
    ) -> Result<Batch<Self::Output>, UnhandledError> {
        batch
            .apply_func(
                move |item, ctx: GroupingStage| async move {
                    let raw = match item {
                        Ok(raw) => raw,
                        Err(e) => return Ok::<FingerprintedItem, UnhandledError>(Err(e)),
                    };

                    // Evaluate grouping rules against the resolved event properties, falling
                    // back to a stack-derived fingerprint. The client-fingerprint override is
                    // applied inside `into_fingerprinted`.
                    let props = raw.to_grouping_value();
                    let mut conn = ctx.connection.acquire().await?;
                    let fingerprint = match evaluate_grouping_rules(
                        &mut conn,
                        raw.team_id,
                        &ctx.team_manager,
                        props,
                    )
                    .await?
                    {
                        Some(rule) => Fingerprint::from_rule(rule),
                        None => Fingerprint::from_exception_list(&raw.exception_list),
                    };

                    Ok(Ok(raw.into_fingerprinted(fingerprint)))
                },
                self,
            )
            .await
    }
}
