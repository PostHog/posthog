use std::sync::{Arc, Mutex};

use futures::future::BoxFuture;
use futures::FutureExt;
use ingestion_framework::KafkaMessage;

use crate::internal_logs::{default_internal_source_policies, InternalLogsVerifier};
use crate::metric_rules::{
    MetricSeriesAdmission, MAX_ADMITTED_LABEL_SETS, MAX_ADMITTED_LABEL_SETS_PER_TEAM,
    MAX_LABEL_SETS_PER_RULE,
};
use crate::rate_limiter::{LogsRateLimiter, LogsRateLimiterConfig};
use crate::sampling::LogsSamplingService;

use super::admission::{report_dropped_usage, LogsAdmissionInput, LogsBatchUsage};
use super::app_metrics::{AppMetricsAggregator, LogsUsageMetricsQueue};
use super::config::LogsIngestionConsumerConfig;
use super::context::{
    is_unbilled_internal, LogsConsumerIdentity, LogsFeatureGates, LogsPipelineContext,
};
use super::deps::LogsIngestionConsumerDeps;
use super::finalize::{emit_metric_rule_tallies, emit_usage_metrics, queue_internal_logs_usage};
use super::pipelines::{
    create_logs_admission_pipeline, create_logs_parse_pipeline, create_logs_processing_pipeline,
    run_chunk_pipeline,
};
use super::process::{LogsProcessingInput, LogsProcessingPass};
use super::types::{describe_batch_position, LogsIngestionMessage, UsageStatsByTeam};

pub type BackgroundTask = BoxFuture<'static, anyhow::Result<()>>;

pub struct ProcessedBatch {
    pub messages: Vec<LogsIngestionMessage>,
    pub background_task: Option<BackgroundTask>,
}

pub struct LogsIngestionConsumer {
    context: Arc<LogsPipelineContext>,
}

impl LogsIngestionConsumer {
    pub fn new(
        identity: LogsConsumerIdentity,
        config: LogsIngestionConsumerConfig,
        deps: LogsIngestionConsumerDeps,
    ) -> Self {
        let limiter_name = match identity.app_source {
            super::context::AppSource::Logs => "logs-rate-limiter",
            super::context::AppSource::Traces => "traces-rate-limiter",
        };
        let rate_limiter = LogsRateLimiter::new(
            LogsRateLimiterConfig {
                team_bucket_size_kb: config.limiter_team_bucket_size_kb.clone(),
                team_refill_rate_kb_per_second: config
                    .limiter_team_refill_rate_kb_per_second
                    .clone(),
                disabled_for_teams: config.limiter_disabled_for_teams.clone(),
                enabled_teams: config.limiter_enabled_teams.clone(),
                bucket_size_kb: config.limiter_bucket_size_kb,
                refill_rate_kb_per_second: config.limiter_refill_rate_kb_per_second,
                ttl_seconds: config.limiter_ttl_seconds,
            },
            deps.token_bucket_redis.clone(),
            limiter_name,
            deps.key_root,
            deps.clock.clone(),
        );
        let sampling_service = Arc::new(LogsSamplingService::new(
            deps.token_bucket_redis.clone(),
            config.limiter_ttl_seconds,
            deps.key_root,
            deps.clock.clone(),
        ));
        let internal_logs_verifier = InternalLogsVerifier::new(
            &config.internal_ingestion_signing_keys,
            &config.internal_ingestion_enabled_teams,
            deps.internal_source_policies
                .clone()
                .unwrap_or_else(default_internal_source_policies),
        );
        let usage_metrics = LogsUsageMetricsQueue::new(
            AppMetricsAggregator::new(deps.outputs.clone(), deps.clock.clone()),
            identity.app_source.as_str(),
            deps.clock.clone(),
        );
        let gates = LogsFeatureGates {
            backfill_enabled_teams: config.backfill_enabled_teams,
            sampling_enabled_teams: config.sampling_enabled_teams,
            sampling_killswitch: config.sampling_killswitch,
            billing_prorate_enabled: config.billing_prorate_enabled,
            metric_rules_enabled_teams: config.metrics_rules_enabled_teams,
            metric_rules_killswitch: config.metrics_rules_killswitch,
            default_metric_rules_enabled_teams: config.default_metric_rules_enabled_teams,
            transformations_enabled_teams: config.transformations_enabled_teams,
            transformations_killswitch: config.transformations_killswitch,
            retention_enabled_teams: config.retention_enabled_teams,
            retention_killswitch: config.retention_killswitch,
            pattern_masking_enabled_teams: config.pattern_masking_enabled_teams,
            json_attribute_parsing_enabled_teams: config.json_attribute_parsing_enabled_teams,
            json_attribute_extraction_enabled_teams: config.json_attribute_extraction_enabled_teams,
        };
        let context = LogsPipelineContext {
            identity,
            gates,
            deps,
            usage_metrics,
            rate_limiter,
            sampling_service,
            internal_logs_verifier,
            metric_series_admission: Mutex::new(MetricSeriesAdmission::new(
                MAX_LABEL_SETS_PER_RULE,
                MAX_ADMITTED_LABEL_SETS_PER_TEAM,
                MAX_ADMITTED_LABEL_SETS,
            )),
        };
        Self {
            context: Arc::new(context),
        }
    }

    pub fn context(&self) -> &Arc<LogsPipelineContext> {
        &self.context
    }

    pub async fn parse_kafka_batch(
        &self,
        messages: Vec<KafkaMessage>,
    ) -> anyhow::Result<Vec<LogsIngestionMessage>> {
        run_chunk_pipeline(
            create_logs_parse_pipeline(self.context.clone()),
            messages.into_iter().map(Arc::new).collect(),
        )
        .await
    }

    pub async fn process_batch(
        &self,
        messages: Vec<LogsIngestionMessage>,
    ) -> anyhow::Result<ProcessedBatch> {
        if messages.is_empty() {
            return Ok(ProcessedBatch {
                messages: Vec::new(),
                background_task: None,
            });
        }
        let usage: LogsBatchUsage = Arc::new(Mutex::new(UsageStatsByTeam::default()));
        let admitted = run_chunk_pipeline(
            create_logs_admission_pipeline(self.context.clone()),
            messages
                .into_iter()
                .map(|message| LogsAdmissionInput {
                    message,
                    usage: usage.clone(),
                })
                .collect(),
        )
        .await?;
        report_dropped_usage(&usage);

        let mut billed = Vec::with_capacity(admitted.len());
        let mut internal = Vec::new();
        for message in admitted.into_iter().map(|a| a.message) {
            if is_unbilled_internal(&message) {
                internal.push(message);
            } else {
                billed.push(message);
            }
        }
        let context = self.context.clone();
        let task_billed = billed.clone();
        let task_internal = internal.clone();
        let background_task =
            async move { process_admitted(context, task_billed, task_internal, usage).await }
                .boxed();
        billed.extend(internal);
        Ok(ProcessedBatch {
            messages: billed,
            background_task: Some(background_task),
        })
    }

    /// A batch failure is returned, not quarantined, because everything on this path is infrastructure-scoped.
    pub async fn process_kafka_batch(
        &self,
        messages: Vec<KafkaMessage>,
    ) -> anyhow::Result<ProcessedBatch> {
        let size = messages.len();
        let offsets = describe_batch_position(&messages);
        let result = async {
            let events = self.parse_kafka_batch(messages).await?;
            self.process_batch(events).await
        }
        .await;
        if let Err(error) = &result {
            tracing::error!(error = %error, size, offsets = ?offsets, "{} - batch failed", self.context.identity.name);
        }
        result
    }
}

async fn run_processing_pass(
    context: &Arc<LogsPipelineContext>,
    messages: Vec<LogsIngestionMessage>,
    pass: LogsProcessingPass,
) -> anyhow::Result<()> {
    run_chunk_pipeline(
        create_logs_processing_pipeline(context.clone()),
        messages
            .into_iter()
            .map(|message| LogsProcessingInput {
                message,
                pass: pass.clone(),
            })
            .collect(),
    )
    .await?;
    Ok(())
}

async fn process_admitted(
    context: Arc<LogsPipelineContext>,
    billed: Vec<LogsIngestionMessage>,
    internal: Vec<LogsIngestionMessage>,
    usage: LogsBatchUsage,
) -> anyhow::Result<()> {
    let team_ids: Vec<i64> = billed.iter().map(|m| m.team_id).collect();
    let billed_pass = LogsProcessingPass {
        usage: usage.clone(),
        metric_tallies: Default::default(),
    };
    run_processing_pass(&context, billed, billed_pass.clone()).await?;
    // Rows that are never emitted keep internal stats off the team's billed usage.
    run_processing_pass(
        &context,
        internal.clone(),
        LogsProcessingPass {
            usage: Default::default(),
            metric_tallies: Default::default(),
        },
    )
    .await?;
    // Metric rules and internal usage emit deltas, so they wait until no pass can fail.
    queue_internal_logs_usage(&context, &internal);
    emit_metric_rule_tallies(&context, &billed_pass.metric_tallies).await;
    context
        .deps
        .team_manager
        .set_teams_ingested_data(&team_ids)
        .await?;
    let usage = usage.lock().unwrap().clone();
    emit_usage_metrics(&context, &usage).await;
    if let Some(transformer) = &context.deps.logs_transformer {
        if let Err(error) = transformer.flush().await {
            tracing::error!(error = %error, "Failed to flush logs transformer monitoring");
        }
    }
    Ok(())
}
