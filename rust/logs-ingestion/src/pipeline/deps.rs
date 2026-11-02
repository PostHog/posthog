//! The dependencies of the consumer, as traits mirroring `LogsIngestionConsumerDeps`.

use std::collections::HashMap;
use std::sync::Arc;

use async_trait::async_trait;
use ingestion_framework::IngestionOutputs;

use crate::content_weights::StagedRecord;
use crate::internal_logs::InternalSourcePolicy;
use crate::metric_rules::{MetricRulesSource, MetricsEmitter};
use crate::normalize::LogsSettings;
use crate::rate_limiter::{Clock, KeyRoot, TokenBucketRedis};
use crate::retention::CompiledRetentionRuleSet;
use crate::sampling::CompiledRuleSet;

use super::errors::DependencyRetry;

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Team {
    pub id: i64,
    pub api_token: String,
    pub logs_settings: Option<LogsSettings>,
}

#[async_trait]
pub trait TeamManager: Send + Sync {
    async fn get_team(&self, team_id: i64) -> anyhow::Result<Option<Team>>;
    async fn get_team_by_token(&self, token: &str) -> anyhow::Result<Option<Team>>;
    async fn set_teams_ingested_data(&self, team_ids: &[i64]) -> anyhow::Result<()>;
}

#[async_trait]
pub trait QuotaLimiting: Send + Sync {
    async fn is_team_token_quota_limited(
        &self,
        token: &str,
        resource: &str,
    ) -> anyhow::Result<bool>;
}

#[async_trait]
pub trait UsageRecordBatch: Send + Sync {
    fn add(&self, team_id: i64, usage_key: &str, record_id: &str, quantity: f64, unit: &str);
    async fn flush(&self) -> anyhow::Result<()>;
}

/// `SamplingRulesCache`. `Err` is a throw, including one from `compileRuleSet`.
#[async_trait]
pub trait SamplingRulesSource: Send + Sync {
    async fn get_compiled_rule_set(&self, team_id: i64) -> anyhow::Result<Arc<CompiledRuleSet>>;
}

#[async_trait]
pub trait RetentionRulesSource: Send + Sync {
    async fn get_compiled_rule_set(
        &self,
        team_id: i64,
        source: &str,
    ) -> anyhow::Result<Arc<CompiledRetentionRuleSet>>;
}

#[async_trait]
pub trait PatternMessageKeysSource: Send + Sync {
    async fn get_message_keys(&self, team_id: i64) -> anyhow::Result<Vec<String>>;
}

#[async_trait]
pub trait TracingConfigSource: Send + Sync {
    async fn get_retention_days(&self, team_id: i64) -> anyhow::Result<f64>;
}

/// The slot for hog log transformations (`LogsTransformerService`). The Rust port does not run
/// hog yet, so no implementation exists; the consumer runs the stage only when one is given.
#[async_trait]
pub trait LogsTransformer: Send + Sync {
    async fn team_has_transformations(&self, team_id: i64) -> anyhow::Result<bool>;
    async fn transform_records(
        &self,
        team_id: i64,
        records: &mut Vec<StagedRecord>,
    ) -> anyhow::Result<()>;
    async fn flush(&self) -> anyhow::Result<()>;
}

/// `LogsIngestionConsumerDeps`. Node builds the Redis client from config; here the caller
/// passes the token-bucket transport, the key root and the clock, so tests can pin all three.
#[derive(Clone)]
pub struct LogsIngestionConsumerDeps {
    pub team_manager: Arc<dyn TeamManager>,
    pub quota_limiting: Arc<dyn QuotaLimiting>,
    pub outputs: Arc<dyn IngestionOutputs>,
    pub usage_batch: Arc<dyn UsageRecordBatch>,
    pub sampling_rules: Option<Arc<dyn SamplingRulesSource>>,
    pub metric_rules: Option<Arc<dyn MetricRulesSource>>,
    pub metrics_emitter: Option<Arc<dyn MetricsEmitter>>,
    pub logs_transformer: Option<Arc<dyn LogsTransformer>>,
    pub retention_rules: Option<Arc<dyn RetentionRulesSource>>,
    pub pattern_message_keys: Option<Arc<dyn PatternMessageKeysSource>>,
    pub tracing_config: Option<Arc<dyn TracingConfigSource>>,
    pub dependency_retry: DependencyRetry,
    pub internal_source_policies: Option<HashMap<String, InternalSourcePolicy>>,
    pub token_bucket_redis: Arc<dyn TokenBucketRedis>,
    pub key_root: KeyRoot,
    /// Epoch milliseconds. Everything that reads `Date.now()` in Node reads this.
    pub clock: Clock,
}
