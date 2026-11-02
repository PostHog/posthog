//! The interface of `metric-rules-cache.ts`. The Postgres-backed cache is not ported.

use std::sync::Arc;

use async_trait::async_trait;

use super::compile::CompiledMetricRule;

/// Per-team compiled metric rules. The Node `MetricRulesCache` reads enabled rows from
/// `logs_logsmetricrule` ordered by `created_at`, compiles them with `compileMetricRules`,
/// and keeps them for 30 seconds.
#[async_trait]
pub trait MetricRulesSource: Send + Sync {
    async fn get_compiled_rules(
        &self,
        team_id: i64,
    ) -> anyhow::Result<Arc<Vec<CompiledMetricRule>>>;
}
