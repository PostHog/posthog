//! Port of `pipeline/process-log-message-step.ts`.

use std::sync::{Arc, Mutex};

use ingestion_framework::{ok, OutputMessage, ProcessingStep};
use metrics::{counter, histogram};

use crate::internal_logs::{INTERNAL_LOGS_HEADER, INTERNAL_SOURCE_HEADER};
use crate::js::number_to_string;
use crate::metric_rules::{
    tally_records, with_default_metric_rules, BatchTallies, CompiledMetricRule,
};
use crate::normalize::{sniff_json_log_attributes, LogsSettings};
use crate::record::LogRecord;
use crate::retention::RETENTION_EXPIRED_STAGE_NAME;

use super::buffer::{BufferValue, RecordsVisitor};
use super::context::{
    applies_team_log_rules, is_unbilled_internal, parse_kafka_headers_except,
    quarantine_log_message, team_id_matches_csv, AppSource, LogsPipelineContext, LOGS_OUTPUT,
};
use super::errors::{is_dependency_unavailable, kafka_outage_as_dependency};
use super::resolve::resolve_log_buffer;
use super::types::{billing_byte_reduction_for_drops, LogsIngestionMessage, UsageStatsByTeam};

pub struct MetricRuleBatchState {
    pub token: String,
    pub rules: Vec<CompiledMetricRule>,
    pub tallies: BatchTallies,
}

/// A `Map` keyed by team, in insertion order.
pub type MetricTalliesByTeam = Arc<Mutex<Vec<(i64, Arc<Mutex<MetricRuleBatchState>>)>>>;

#[derive(Clone)]
pub struct LogsProcessingPass {
    pub usage: Arc<Mutex<UsageStatsByTeam>>,
    pub metric_tallies: MetricTalliesByTeam,
}

pub struct LogsProcessingInput {
    pub message: LogsIngestionMessage,
    pub pass: LogsProcessingPass,
}

/// A message never fails its pass on its own: a dependency outage or a failed quarantine is
/// carried in `failure`, and the pass fails once every message has settled.
pub struct LogsProcessingOutcome {
    pub message: LogsIngestionMessage,
    pub quarantined: bool,
    pub failure: Option<anyhow::Error>,
}

fn can_emit_metric_rules(context: &LogsPipelineContext) -> bool {
    !context.gates.metric_rules_killswitch
        && context.deps.metric_rules.is_some()
        && context.deps.metrics_emitter.is_some()
}

async fn get_metric_rule_batch_state(
    context: &LogsPipelineContext,
    by_team: &MetricTalliesByTeam,
    message: &LogsIngestionMessage,
) -> Option<Arc<Mutex<MetricRuleBatchState>>> {
    if !applies_team_log_rules(message) {
        return None;
    }
    let team_rules_enabled = can_emit_metric_rules(context)
        && team_id_matches_csv(&context.gates.metric_rules_enabled_teams, message.team_id);
    let default_rules_enabled = can_emit_metric_rules(context)
        && team_id_matches_csv(
            &context.gates.default_metric_rules_enabled_teams,
            message.team_id,
        );
    if !team_rules_enabled && !default_rules_enabled {
        return None;
    }
    let existing = by_team
        .lock()
        .unwrap()
        .iter()
        .find(|(t, _)| *t == message.team_id)
        .map(|(_, s)| s.clone());
    let state = match existing {
        Some(state) => state,
        None => {
            let mut rules: Vec<CompiledMetricRule> = Vec::new();
            if team_rules_enabled {
                match context
                    .deps
                    .metric_rules
                    .as_ref()
                    .unwrap()
                    .get_compiled_rules(message.team_id)
                    .await
                {
                    Ok(all) => {
                        rules = all
                            .iter()
                            .filter(|r| r.source == context.identity.metric_rule_source)
                            .cloned()
                            .collect()
                    }
                    Err(error) => {
                        // Fail open: metric rules must never DLQ or block the log records.
                        tracing::warn!(team_id = message.team_id, error = %error, "[logs-metric-rules] rules fetch failed — skipping metric rules for batch");
                        return None;
                    }
                }
            }
            if default_rules_enabled {
                rules = with_default_metric_rules(rules, context.identity.metric_rule_source);
            }
            // Concurrent messages for the same team race here; keep the first state.
            let mut by_team = by_team.lock().unwrap();
            match by_team.iter().find(|(t, _)| *t == message.team_id) {
                Some((_, state)) => state.clone(),
                None => {
                    let state = Arc::new(Mutex::new(MetricRuleBatchState {
                        token: message.token.clone(),
                        rules,
                        tallies: BatchTallies::new(),
                    }));
                    by_team.push((message.team_id, state.clone()));
                    state
                }
            }
        }
    };
    let has_rules = !state.lock().unwrap().rules.is_empty();
    has_rules.then_some(state)
}

fn settings_of(team: Option<&super::deps::Team>) -> LogsSettings {
    team.and_then(|t| t.logs_settings.clone())
        .unwrap_or_default()
}

async fn process_log_message(
    context: &LogsPipelineContext,
    input: &LogsProcessingInput,
) -> anyhow::Result<()> {
    let message = &input.message;
    let pass = &input.pass;
    let team_id = message.team_id;
    let team = context
        .retry(|| context.deps.team_manager.get_team(team_id))
        .await?;
    let settings = settings_of(team.as_ref());
    let json_parse = settings.json_parse_logs.unwrap_or(false);
    let retention_days = context
        .retry(|| context.default_retention_days(team_id, &settings))
        .await?;

    if let Some(stats) = pass.usage.lock().unwrap().get_mut(team_id) {
        stats.retention_days = retention_days;
    }

    if message.message.value.is_none() {
        return Ok(());
    }

    let metric_state = get_metric_rule_batch_state(context, &pass.metric_tallies, message).await;
    let is_logs = context.identity.app_source == AppSource::Logs;
    let json_attribute_key = settings.json_parse_logs_attribute_key.clone().filter(|_| {
        is_logs && team_id_matches_csv(&context.gates.json_attribute_parsing_enabled_teams, team_id)
    });
    let visitor: Option<RecordsVisitor<'_>> =
        if metric_state.is_some() || json_attribute_key.is_some() {
            Some(Box::new(move |records: &[LogRecord]| {
                if let Some(state) = &metric_state {
                    let now_ms = context.now_ms();
                    let mut state = state.lock().unwrap();
                    let MetricRuleBatchState { rules, tallies, .. } = &mut *state;
                    let mut admission = context.metric_series_admission.lock().unwrap();
                    let mut admit = |rule_id: &str, label_key: &str| {
                        admission.admit(team_id, rule_id, label_key, now_ms)
                    };
                    tally_records(rules, records, tallies, now_ms, Some(&mut admit))?;
                }
                if let Some(key) = &json_attribute_key {
                    sniff_json_log_attributes(records.iter(), key, team_id);
                }
                Ok(())
            }))
        } else {
            None
        };

    let mut buffer_settings = settings.clone();
    if !(is_logs
        && team_id_matches_csv(
            &context.gates.json_attribute_extraction_enabled_teams,
            team_id,
        ))
    {
        buffer_settings.json_parse_logs_attribute_key = None;
    }
    let resolved =
        resolve_log_buffer(context, message, &buffer_settings, retention_days, visitor).await?;

    context.usage_metrics.queue_usage_metric(
        team_id,
        "records_dropped_retention_expired",
        resolved.records_dropped_by_stage(RETENTION_EXPIRED_STAGE_NAME),
    );

    let mut override_uncompressed = None;
    let mut override_compressed = None;
    let mut override_record_count = None;
    let drops = &resolved.drops;
    let records_dropped = drops.stage.records_dropped;
    if records_dropped > 0.0 {
        let header = message.bytes_uncompressed;
        let content_credit = billing_byte_reduction_for_drops(
            header,
            drops.stage.content_bytes_dropped,
            drops.content_bytes_total,
        );
        let record_credit =
            billing_byte_reduction_for_drops(header, records_dropped, message.record_count);
        let team_label = team_id.to_string();
        if !is_unbilled_internal(message) {
            if content_credit > 0.0 {
                counter!("logs_ingestion_billing_bytes_credited_total", "team_id" => team_label.clone())
                    .increment(content_credit as u64);
            }
            counter!("logs_ingestion_billing_records_credited_total", "team_id" => team_label)
                .increment(records_dropped as u64);
        }
        if message.record_count > 0.0 {
            histogram!("logs_ingestion_drop_batch_rows").record(message.record_count);
        }
        if drops.content_bytes_total > 0.0 {
            histogram!("logs_ingestion_drop_fraction")
                .record((drops.stage.content_bytes_dropped / drops.content_bytes_total).min(1.0));
        }
        if header > 0.0 {
            histogram!("logs_ingestion_billing_prorate_divergence")
                .record((content_credit - record_credit).abs() / header);
        }
        if context.gates.billing_prorate_enabled {
            if let Some(row) = pass.usage.lock().unwrap().get_mut(team_id) {
                row.bytes_allowed = (row.bytes_allowed - content_credit).max(0.0);
                row.records_allowed = (row.records_allowed - records_dropped).max(0.0);
            }
            let compressed_credit = billing_byte_reduction_for_drops(
                message.bytes_compressed,
                drops.stage.content_bytes_dropped,
                drops.content_bytes_total,
            );
            override_uncompressed = Some((header - content_credit).max(0.0));
            override_compressed = Some((message.bytes_compressed - compressed_credit).max(0.0));
            override_record_count = Some((message.record_count - records_dropped).max(0.0));
        }
    }

    if resolved.pii.pii_replacements > 0 {
        let mut usage = pass.usage.lock().unwrap();
        usage.row(team_id).pii_replacements += resolved.pii.pii_replacements as f64;
    }
    let usage_metrics = &context.usage_metrics;
    usage_metrics.queue_by_rule(
        team_id,
        "sampling_records_dropped_by_rule",
        &drops.stage.records_dropped_by_rule_id,
    );
    usage_metrics.queue_by_rule(
        team_id,
        "bytes_dropped_by_rule",
        &drops.stage.bytes_dropped_by_rule_id,
    );

    let value = match resolved.value {
        None => {
            let reason = resolved.dropped_reason.unwrap_or_default();
            counter!("logs_ingestion_message_dropped_count", "reason" => reason, "team_id" => team_id.to_string())
                .increment(1);
            return Ok(());
        }
        Some(BufferValue::Encoded(bytes)) => Some(bytes.into()),
        Some(_) => message.message.value.clone(),
    };

    // Built per attempt, so the first attempt needs no copy of the message.
    let output = || {
        let mut headers = parse_kafka_headers_except(
            &message.message,
            &[INTERNAL_LOGS_HEADER, INTERNAL_SOURCE_HEADER],
            10,
        );
        if let Some(internal) = &message.internal_logs {
            headers.set(INTERNAL_SOURCE_HEADER, internal.source.clone());
        }
        headers.set("token", message.token.clone());
        headers.set("team_id", team_id.to_string());
        headers.set("json-parse", json_parse.to_string());
        headers.set("retention-days", number_to_string(retention_days));
        headers.set("source_topic", message.message.topic.clone());
        headers.set("source_partition", message.message.partition.to_string());
        if let Some(n) = override_uncompressed {
            headers.set("bytes_uncompressed", number_to_string(n));
        }
        if let Some(n) = override_compressed {
            headers.set("bytes_compressed", number_to_string(n));
        }
        if let Some(n) = override_record_count {
            headers.set("record_count", number_to_string(n));
        }
        OutputMessage {
            value: value.clone(),
            key: None,
            headers,
        }
    };
    context
        .retry(|| {
            let out = output();
            async move {
                context
                    .deps
                    .outputs
                    .queue_messages(LOGS_OUTPUT, vec![out])
                    .await
                    .map_err(kafka_outage_as_dependency)
            }
        })
        .await
}

pub fn create_process_log_message_step(
    context: Arc<LogsPipelineContext>,
) -> ProcessingStep<LogsProcessingInput, LogsProcessingOutcome> {
    ProcessingStep::new(
        "processLogMessageStep",
        move |input: LogsProcessingInput| {
            let context = context.clone();
            async move {
                let outcome = match process_log_message(&context, &input).await {
                    Ok(()) => LogsProcessingOutcome {
                        message: input.message,
                        quarantined: false,
                        failure: None,
                    },
                    Err(error) if is_dependency_unavailable(&error) => LogsProcessingOutcome {
                        message: input.message,
                        quarantined: false,
                        failure: Some(error),
                    },
                    Err(error) => {
                        let m = &input.message;
                        match quarantine_log_message(
                            &context,
                            &m.message,
                            &error,
                            Some(&m.token),
                            Some(m.team_id),
                        )
                        .await
                        {
                            Ok(()) => LogsProcessingOutcome {
                                message: input.message,
                                quarantined: true,
                                failure: None,
                            },
                            Err(dlq_error) => LogsProcessingOutcome {
                                message: input.message,
                                quarantined: false,
                                failure: Some(dlq_error),
                            },
                        }
                    }
                };
                Ok(ok(outcome))
            }
        },
    )
}
