use std::sync::Arc;

pub mod issue;
pub mod rule_suppression;
pub mod suppression;

use moka::future::{Cache, CacheBuilder};
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    issue_resolution::Issue,
    metric_consts::LINKING_STAGE,
    stages::{
        linking::{
            issue::IssueLinker, rule_suppression::RuleSuppression, suppression::IssueSuppression,
        },
        pipeline::{FingerprintedPipelineItem, LinkedPipelineItem},
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
    // Cross-batch `(team_id, fingerprint) -> issue_id` mapping cache. Owned by AppContext.
    pub issue_cache: Cache<(TeamId, String), Uuid>,
    // Per-batch fingerprints -> resolved issue dedup. Built fresh per batch (LinkingStage is
    // constructed per batch via `From`), so events sharing candidate fingerprints within a
    // single batch resolve the Issue exactly once. moka's `try_get_with` also deduplicates
    // concurrent misses for the same key inside the same batch.
    pub batch_issue_cache: Cache<(TeamId, String), Issue>,
}

impl Stage for LinkingStage {
    type Input = FingerprintedPipelineItem;
    type Output = LinkedPipelineItem;

    fn name(&self) -> &'static str {
        LINKING_STAGE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        let fingerprinted = batch.apply_operator(RuleSuppression, self.clone()).await?;
        let linker = IssueLinker;
        let timing = common_metrics::timing_guard(linker.name(), &[]);
        let linked = fingerprinted
            .apply_func(
                move |item, context| {
                    let linker = linker.clone();
                    async move { linker.execute(item, context).await }
                },
                self.clone(),
            )
            .await?;
        timing.label("outcome", "success");
        linked.apply_operator(IssueSuppression, self.clone()).await
    }
}

impl From<&Arc<AppContext>> for LinkingStage {
    fn from(ctx: &Arc<AppContext>) -> Self {
        // `issue_cache` lives on AppContext so it survives across batches; cloning the
        // moka handle is just a refcount bump on the underlying Arc.
        // `batch_issue_cache` is built fresh per batch — capacity is generous because
        // `MAX_EVENTS_PER_BATCH` is 1000 today; the cache is dropped when the stage is.
        Self {
            app_context: ctx.clone(),
            issue_cache: ctx.issue_cache.clone(),
            batch_issue_cache: CacheBuilder::new(10_000).build(),
        }
    }
}
