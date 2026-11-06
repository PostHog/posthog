use std::sync::Arc;

use async_trait::async_trait;

use super::compile::CompiledMetricRule;

/// Node reads enabled rows ordered by `created_at` and keeps the compiled rules for 30 seconds.
#[async_trait]
pub trait MetricRulesSource: Send + Sync {
    async fn get_compiled_rules(
        &self,
        team_id: i64,
    ) -> anyhow::Result<Arc<Vec<CompiledMetricRule>>>;
}
