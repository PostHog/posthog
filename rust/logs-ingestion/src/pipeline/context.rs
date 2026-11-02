//! Port of `pipeline/logs-pipeline-context.ts`.

use std::borrow::Cow;
use std::sync::{Arc, Mutex};

use ingestion_framework::{Headers, KafkaMessage, OutputMessage};
use metrics::counter;

use crate::internal_logs::InternalLogsVerifier;
use crate::metric_rules::{MetricRuleSource, MetricSeriesAdmission};
use crate::normalize::LogsSettings;
use crate::property_filter::coerce::{js_parse_int, js_trim};
use crate::rate_limiter::{Clock, LogsRateLimiter};
use crate::sampling::LogsSamplingService;

use super::app_metrics::{iso_timestamp, LogsUsageMetricsQueue};
use super::deps::LogsIngestionConsumerDeps;
use super::errors::{error_message, error_name, retry_on_dependency_unavailable};
use super::types::{
    LogsIngestionMessage, DEFAULT_LOGS_RETENTION_DAYS, DEFAULT_TRACES_RETENTION_DAYS,
};

pub const LOGS_OUTPUT: &str = "logs";
pub const LOGS_DLQ_OUTPUT: &str = "logs_dlq";

pub fn team_id_matches_csv(raw: &str, team_id: i64) -> bool {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return false;
    }
    if trimmed == "*" {
        return true;
    }
    trimmed
        .split(',')
        .map(|s| js_parse_int(js_trim(s), Some(10)))
        .any(|n| n == team_id as f64)
}

/// `parseKafkaHeaders`: assigned onto a plain object, so a repeated key keeps its first
/// position and takes the last value, and `__proto__` is lost.
pub fn parse_kafka_headers(message: &KafkaMessage) -> Headers {
    parse_kafka_headers_except(message, &[], 0)
}

/// `parseKafkaHeaders(message.headers)[name]` without building the map: the last value wins.
pub fn kafka_header<'a>(message: &'a KafkaMessage, name: &str) -> Option<Cow<'a, str>> {
    if name == "__proto__" {
        return None;
    }
    message
        .headers
        .iter()
        .rev()
        .find(|(key, _)| key == name)
        .map(|(_, value)| utf8_lossy(value.as_deref().unwrap_or_default()))
}

pub fn utf8_lossy(bytes: &[u8]) -> Cow<'_, str> {
    match std::str::from_utf8(bytes) {
        Ok(text) => Cow::Borrowed(text),
        Err(_) => String::from_utf8_lossy(bytes),
    }
}

pub fn parse_kafka_headers_except(message: &KafkaMessage, skip: &[&str], extra: usize) -> Headers {
    let mut headers = Headers(Vec::with_capacity(message.headers.len() + extra));
    for (key, value) in &message.headers {
        if key == "__proto__" || skip.contains(&key.as_str()) {
            continue;
        }
        let value = value.as_deref().unwrap_or_default();
        headers.set(key.clone(), utf8_lossy(value).into_owned());
    }
    headers
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AppSource {
    Logs,
    Traces,
}

impl AppSource {
    pub fn as_str(self) -> &'static str {
        match self {
            AppSource::Logs => "logs",
            AppSource::Traces => "traces",
        }
    }
}

/// What differs between the logs and traces consumers. Both bill against `logs_mb_ingested`.
#[derive(Debug, Clone)]
pub struct LogsConsumerIdentity {
    pub name: String,
    pub app_source: AppSource,
    pub quota_resource: String,
    pub metric_rule_source: MetricRuleSource,
    pub retention_rule_source: String,
}

impl LogsConsumerIdentity {
    pub fn logs() -> Self {
        Self {
            name: "LogsIngestionConsumer".to_string(),
            app_source: AppSource::Logs,
            quota_resource: "logs_mb_ingested".to_string(),
            metric_rule_source: MetricRuleSource::Logs,
            retention_rule_source: "logs".to_string(),
        }
    }

    pub fn traces() -> Self {
        Self {
            name: "TracesIngestionConsumer".to_string(),
            app_source: AppSource::Traces,
            quota_resource: "logs_mb_ingested".to_string(),
            metric_rule_source: MetricRuleSource::Spans,
            retention_rule_source: "spans".to_string(),
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct LogsFeatureGates {
    pub backfill_enabled_teams: String,
    pub sampling_enabled_teams: String,
    pub sampling_killswitch: bool,
    pub billing_prorate_enabled: bool,
    pub metric_rules_enabled_teams: String,
    pub metric_rules_killswitch: bool,
    pub default_metric_rules_enabled_teams: String,
    pub transformations_enabled_teams: String,
    pub transformations_killswitch: bool,
    pub retention_enabled_teams: String,
    pub retention_killswitch: bool,
    pub pattern_masking_enabled_teams: String,
    pub json_attribute_parsing_enabled_teams: String,
    pub json_attribute_extraction_enabled_teams: String,
}

pub struct LogsPipelineContext {
    pub identity: LogsConsumerIdentity,
    pub gates: LogsFeatureGates,
    pub deps: LogsIngestionConsumerDeps,
    pub usage_metrics: LogsUsageMetricsQueue,
    pub rate_limiter: LogsRateLimiter,
    pub sampling_service: Arc<LogsSamplingService>,
    pub internal_logs_verifier: InternalLogsVerifier,
    pub metric_series_admission: Mutex<MetricSeriesAdmission>,
}

impl LogsPipelineContext {
    pub fn now_ms(&self) -> f64 {
        (self.deps.clock)()
    }

    pub fn clock(&self) -> &Clock {
        &self.deps.clock
    }

    pub async fn retry<T, F, Fut>(&self, f: F) -> anyhow::Result<T>
    where
        F: FnMut() -> Fut,
        Fut: std::future::Future<Output = anyhow::Result<T>>,
    {
        retry_on_dependency_unavailable(self.deps.dependency_retry, f).await
    }

    pub async fn default_retention_days(
        &self,
        team_id: i64,
        settings: &LogsSettings,
    ) -> anyhow::Result<f64> {
        match self.identity.app_source {
            AppSource::Logs => Ok(settings
                .retention_days
                .unwrap_or(DEFAULT_LOGS_RETENTION_DAYS)),
            AppSource::Traces => match &self.deps.tracing_config {
                Some(cache) => cache.get_retention_days(team_id).await,
                None => Ok(DEFAULT_TRACES_RETENTION_DAYS),
            },
        }
    }
}

/// Transformations write hog_function logs, which could come back here as internal logs and loop.
pub fn applies_team_log_rules(message: &LogsIngestionMessage) -> bool {
    message
        .internal_logs
        .as_ref()
        .map(|i| i.team_rules)
        .unwrap_or(true)
}

pub fn is_unbilled_internal(message: &LogsIngestionMessage) -> bool {
    message.internal_logs.as_ref().is_some_and(|i| !i.billed)
}

/// `quarantineLogMessage`: the DLQ headers are the replay contract. A failed DLQ write fails.
pub async fn quarantine_log_message(
    context: &LogsPipelineContext,
    message: &KafkaMessage,
    error: &anyhow::Error,
    token: Option<&str>,
    team_id: Option<i64>,
) -> anyhow::Result<()> {
    let message_text = error_message(error);
    let name = error_name(error);
    let team_label = team_id
        .map(|t| t.to_string())
        .unwrap_or_else(|| "unknown".to_string());
    counter!("logs_ingestion_message_dlq_count", "reason" => name.clone(), "team_id" => team_label.clone())
        .increment(1);

    let mut headers = parse_kafka_headers(message);
    if let Some(token) = token {
        headers.set("token", token);
    }
    headers.set("team_id", team_label);
    headers.set("error_message", message_text.clone());
    headers.set("error_name", name);
    headers.set("failed_at", iso_timestamp(context.now_ms()));
    headers.set("source_topic", message.topic.clone());
    headers.set("source_partition", message.partition.to_string());
    headers.set("source_offset", message.offset.to_string());
    let out = OutputMessage {
        value: message.value.clone(),
        key: None,
        headers,
    };
    let result = context
        .retry(|| {
            let out = out.clone();
            async move {
                context
                    .deps
                    .outputs
                    .queue_messages(LOGS_DLQ_OUTPUT, vec![out])
                    .await
            }
        })
        .await;
    if let Err(dlq_error) = &result {
        tracing::error!(error = %dlq_error, original_error = %message_text, partition = message.partition, offset = message.offset, "Failed to produce message to DLQ");
    }
    result
}
