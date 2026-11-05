use metrics::counter;
use uuid::Uuid;

use crate::metric_rules::build_metric_rules_otlp_payload;

use super::context::{AppSource, LogsPipelineContext};
use super::process::MetricTalliesByTeam;
use super::types::{
    retention_bytes_metric_name, LogsIngestionMessage, UsageStatsByTeam,
    DEFAULT_LOGS_RETENTION_DAYS,
};

/// The usage report matches `bytes_ingested` exactly, so these names never reach billing.
pub fn queue_internal_logs_usage(context: &LogsPipelineContext, internal: &[LogsIngestionMessage]) {
    for m in internal {
        context.usage_metrics.queue_usage_metric(
            m.team_id,
            "bytes_ingested_internal",
            m.bytes_uncompressed,
        );
        context.usage_metrics.queue_usage_metric(
            m.team_id,
            "records_ingested_internal",
            m.record_count,
        );
        let team = m.team_id.to_string();
        counter!("logs_ingestion_internal_bytes_total", "team_id" => team.clone())
            .increment(m.bytes_uncompressed as u64);
        counter!("logs_ingestion_internal_records_total", "team_id" => team)
            .increment(m.record_count as u64);
    }
}

pub async fn emit_metric_rule_tallies(
    context: &LogsPipelineContext,
    by_team: &MetricTalliesByTeam,
) {
    let states: Vec<_> = by_team.lock().unwrap().clone();
    for (team_id, state) in states {
        let (token, payload) = {
            let state = state.lock().unwrap();
            let team = team_id.to_string();
            let tallies = &state.tallies;
            if tallies.value_skipped > 0 {
                counter!("logs_metrics_rules_value_skipped_total", "team_id" => team.clone())
                    .increment(tallies.value_skipped);
            }
            if tallies.eval_errors > 0 {
                counter!("logs_metrics_rules_eval_error_total", "team_id" => team.clone())
                    .increment(tallies.eval_errors);
            }
            let overflow: u64 = tallies.series_overflow.values().sum();
            if overflow > 0 {
                counter!("logs_metrics_rules_series_overflow_total", "team_id" => team.clone())
                    .increment(overflow);
            }
            let matched: u64 = tallies
                .by_rule
                .values()
                .flat_map(|m| m.values())
                .map(|e| e.count)
                .sum();
            if matched > 0 {
                counter!("logs_metrics_rules_records_matched_total", "team_id" => team)
                    .increment(matched);
            }
            (
                state.token.clone(),
                build_metric_rules_otlp_payload(&state.rules, tallies, context.now_ms()),
            )
        };
        let Some(payload) = payload else {
            continue;
        };
        if let Some(emitter) = &context.deps.metrics_emitter {
            emitter.emit(&token, team_id, &payload).await;
        }
    }
}

pub async fn emit_usage_metrics(context: &LogsPipelineContext, usage: &UsageStatsByTeam) {
    let metrics = &context.usage_metrics;
    for (team_id, stats) in &usage.0 {
        let team_id = *team_id;
        metrics.queue_usage_metric(team_id, "bytes_received", stats.bytes_received);
        metrics.queue_usage_metric(team_id, "records_received", stats.records_received);
        metrics.queue_usage_metric(team_id, "bytes_ingested", stats.bytes_allowed);
        metrics.queue_usage_metric(
            team_id,
            "bytes_ingested_records",
            stats.bytes_allowed_records,
        );
        metrics.queue_usage_metric(team_id, "records_ingested", stats.records_allowed);
        metrics.queue_usage_metric(team_id, "bytes_dropped", stats.bytes_dropped);
        metrics.queue_usage_metric(team_id, "records_dropped", stats.records_dropped);
        metrics.queue_usage_metric(team_id, "pii_replacements", stats.pii_replacements);
        if let Some(name) = retention_bytes_metric_name(stats.retention_days) {
            metrics.queue_usage_metric(team_id, &name, stats.bytes_allowed);
        }
        if stats.retention_days != DEFAULT_LOGS_RETENTION_DAYS {
            metrics.queue_retention_byte_days(team_id, stats.bytes_allowed, stats.retention_days);
        }
        let traces = context.identity.app_source == AppSource::Traces;
        let source = if traces { "apm_traces" } else { "logs" };
        // A fresh id per flush keeps two pods flushing the same team from collapsing rows.
        let flush_id = Uuid::now_v7().to_string();
        let batch = &context.deps.usage_batch;
        batch.add(
            team_id,
            &format!("{source}_bytes"),
            &flush_id,
            stats.bytes_allowed,
            "bytes",
        );
        let records_key = if traces {
            "apm_traces_spans"
        } else {
            "logs_records"
        };
        batch.add(
            team_id,
            records_key,
            &flush_id,
            stats.records_allowed,
            "records",
        );
    }
    let (a, b) = futures::join!(metrics.flush(), context.deps.usage_batch.flush());
    if let Err(error) = a {
        tracing::error!(error = %error, "Failed to emit usage metrics - billing data may be lost");
    }
    if let Err(error) = b {
        tracing::error!(error = %error, "Failed to emit usage records - billing data may be lost");
    }
}
