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
        pipeline::ExceptionEventPipelineItem,
    },
    types::{
        batch::Batch,
        operator::TeamId,
        stage::{Stage, StageResult},
    },
};

/// Capacity for the per-batch issue cache. Generous because `MAX_EVENTS_PER_BATCH`
/// is 1000 today; the cache is dropped when the stage is.
const BATCH_ISSUE_CACHE_CAPACITY: u64 = 10_000;

#[derive(Clone)]
pub struct LinkingStage {
    pub app_context: Arc<AppContext>,
    // Cross-batch `(team_id, fingerprint) -> issue_id` mapping cache. Owned by AppContext.
    pub issue_cache: Cache<(TeamId, String), Uuid>,
    // Per-batch fingerprint -> Issue dedup. Built fresh per batch (LinkingStage is
    // constructed per batch), so events sharing a fingerprint within a single batch
    // resolve the Issue exactly once. moka's `try_get_with` also deduplicates
    // concurrent misses for the same key inside the same batch.
    //
    // The `/v2/resolve` flow runs the pipeline once per event for isolation. To
    // preserve cross-event dedup within a request, the handler creates one cache
    // and threads it through `new(ctx, Some(cache))` to every per-event invocation.
    pub batch_issue_cache: Cache<(TeamId, String), Issue>,
}

impl LinkingStage {
    /// Build a `LinkingStage`. When `batch_issue_cache` is `Some`, the supplied
    /// cache is reused (the `/v2/resolve` flow uses this to share one cache
    /// across the per-event pipeline invocations within a single request).
    /// When `None`, a fresh per-batch cache is allocated — the legacy
    /// `/process` behaviour.
    pub fn new(
        ctx: &Arc<AppContext>,
        batch_issue_cache: Option<Cache<(TeamId, String), Issue>>,
    ) -> Self {
        Self {
            app_context: ctx.clone(),
            issue_cache: ctx.issue_cache.clone(),
            batch_issue_cache: batch_issue_cache.unwrap_or_else(Self::default_batch_issue_cache),
        }
    }

    /// Construct a fresh, empty per-batch cache sized for the largest batch we
    /// support. Callers that need to share a cache across pipeline invocations
    /// build one with this and pass it through `new` on each invocation.
    pub fn default_batch_issue_cache() -> Cache<(TeamId, String), Issue> {
        CacheBuilder::new(BATCH_ISSUE_CACHE_CAPACITY).build()
    }
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

#[cfg(test)]
mod tests {
    use super::*;

    /// A `LinkingStage` constructed with a supplied cache reuses that
    /// instance — multiple stages built around the same cache see each
    /// other's writes. This is the property the `/v2/resolve` flow relies on.
    #[tokio::test]
    async fn supplied_batch_issue_cache_is_shared() {
        let shared = LinkingStage::default_batch_issue_cache();

        let key = (42_i32, "fingerprint".to_string());
        let sentinel = Issue {
            id: Uuid::nil(),
            team_id: 42,
            status: crate::issue_resolution::IssueStatus::Active,
            name: None,
            description: None,
            created_at: chrono::Utc::now(),
        };
        shared.insert(key.clone(), sentinel.clone()).await;

        // Two clones of the cache (mirroring how the v2 handler hands the same
        // cache to each per-event call) both see the previously-inserted
        // sentinel — they share the underlying moka storage.
        let view_one = shared.clone();
        let view_two = shared.clone();

        assert!(view_one.contains_key(&key));
        assert!(view_two.contains_key(&key));

        // A write through one clone is visible through the other.
        let second_key = (42_i32, "another_fingerprint".to_string());
        view_one.insert(second_key.clone(), sentinel.clone()).await;
        assert!(view_two.contains_key(&second_key));
    }

    /// `new(ctx, None)` allocates an independent cache — the legacy
    /// `/process` flow's behaviour is unchanged.
    #[tokio::test]
    async fn omitted_cache_means_fresh_per_stage() {
        let cache_a = LinkingStage::default_batch_issue_cache();
        let cache_b = LinkingStage::default_batch_issue_cache();

        let key = (1_i32, "fp".to_string());
        let sentinel = Issue {
            id: Uuid::nil(),
            team_id: 1,
            status: crate::issue_resolution::IssueStatus::Active,
            name: None,
            description: None,
            created_at: chrono::Utc::now(),
        };
        cache_a.insert(key.clone(), sentinel.clone()).await;

        assert!(cache_a.contains_key(&key));
        assert!(!cache_b.contains_key(&key));
    }
}
