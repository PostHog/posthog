use std::collections::HashSet;
use std::sync::{Arc, Mutex};

use ingestion_framework::{drop, ok, ChunkProcessingStep, PipelineResult};
use metrics::counter;

use crate::rate_limiter::RateLimitedMessage;

use super::context::{is_unbilled_internal, team_id_matches_csv, LogsPipelineContext};
use super::types::{LogsIngestionMessage, UsageStatsByTeam};

/// Only billed messages reach it.
pub type LogsBatchUsage = Arc<Mutex<UsageStatsByTeam>>;

pub struct LogsAdmissionInput {
    pub message: LogsIngestionMessage,
    pub usage: LogsBatchUsage,
}

fn record_allowed(usage: &LogsBatchUsage, m: &LogsIngestionMessage) {
    let mut usage = usage.lock().unwrap();
    let stats = usage.row(m.team_id);
    stats.bytes_received += m.bytes_uncompressed;
    stats.records_received += m.record_count;
    stats.bytes_allowed += m.bytes_uncompressed;
    stats.records_allowed += m.record_count;
    stats.bytes_allowed_records += m.bytes_uncompressed_records;
}

fn record_dropped(usage: &LogsBatchUsage, m: &LogsIngestionMessage) {
    let mut usage = usage.lock().unwrap();
    let stats = usage.row(m.team_id);
    stats.bytes_received += m.bytes_uncompressed;
    stats.records_received += m.record_count;
    stats.bytes_dropped += m.bytes_uncompressed;
    stats.records_dropped += m.record_count;
}

/// Counts in first-seen order, like a `Map`.
#[derive(Default)]
struct TeamCounts(Vec<(i64, u64)>);

impl TeamCounts {
    fn add(&mut self, team_id: i64) {
        match self.0.iter_mut().find(|(t, _)| *t == team_id) {
            Some(entry) => entry.1 += 1,
            None => self.0.push((team_id, 1)),
        }
    }

    fn report(&self, reason: &'static str) {
        for (team_id, count) in &self.0 {
            counter!("logs_ingestion_message_dropped_count", "reason" => reason, "team_id" => team_id.to_string())
                .increment(*count);
        }
    }
}

type AdmissionStep = ChunkProcessingStep<LogsAdmissionInput, LogsAdmissionInput>;

/// Verified internal logs are never quota or rate limited, so counting them would show as drops.
pub fn create_track_incoming_traffic_step() -> AdmissionStep {
    ChunkProcessingStep::sync(
        "trackIncomingTrafficStep",
        |values: Vec<LogsAdmissionInput>| {
            let (bytes, records) = values
                .iter()
                .filter(|v| !is_unbilled_internal(&v.message))
                .fold((0.0, 0.0), |(b, r), v| {
                    (b + v.message.bytes_uncompressed, r + v.message.record_count)
                });
            counter!("logs_ingestion_bytes_received_total").increment(bytes as u64);
            counter!("logs_ingestion_records_received_total").increment(records as u64);
            Ok(values.into_iter().map(ok).collect())
        },
    )
}

pub fn create_backfill_gate_step(context: Arc<LogsPipelineContext>) -> AdmissionStep {
    ChunkProcessingStep::sync(
        "backfillGateStep",
        move |values: Vec<LogsAdmissionInput>| {
            // (team, messages, records, billed) in first-seen order.
            let mut dropped: Vec<(i64, u64, f64, bool)> = Vec::new();
            let results = values
                .into_iter()
                .map(|v| {
                    let m = &v.message;
                    if !m.backfill_requested
                        || team_id_matches_csv(&context.gates.backfill_enabled_teams, m.team_id)
                    {
                        return ok(v);
                    }
                    let i = match dropped.iter().position(|d| d.0 == m.team_id) {
                        Some(i) => i,
                        None => {
                            dropped.push((m.team_id, 0, 0.0, false));
                            dropped.len() - 1
                        }
                    };
                    dropped[i].1 += 1;
                    if !is_unbilled_internal(m) {
                        dropped[i].2 += m.record_count;
                        dropped[i].3 = true;
                        record_dropped(&v.usage, m);
                    }
                    drop("backfill_not_enabled")
                })
                .collect();
            for (team_id, messages, records, billed) in dropped {
                counter!("logs_ingestion_message_dropped_count", "reason" => "backfill_not_enabled", "team_id" => team_id.to_string())
                .increment(messages);
                if billed {
                    context.usage_metrics.queue_usage_metric(
                        team_id,
                        "records_dropped_backfill_not_enabled",
                        records,
                    );
                }
            }
            Ok(results)
        },
    )
}

pub fn create_quota_limit_step(context: Arc<LogsPipelineContext>) -> AdmissionStep {
    ChunkProcessingStep::new("quotaLimitStep", move |values: Vec<LogsAdmissionInput>| {
        let context = context.clone();
        async move {
            let mut tokens: Vec<String> = Vec::new();
            for v in values.iter().filter(|v| !is_unbilled_internal(&v.message)) {
                if !tokens.contains(&v.message.token) {
                    tokens.push(v.message.token.clone());
                }
            }
            let resource = context.identity.quota_resource.clone();
            let checks = futures::future::join_all(tokens.iter().map(|t| {
                context
                    .deps
                    .quota_limiting
                    .is_team_token_quota_limited(t, &resource)
            }))
            .await;
            let mut limited = Vec::new();
            for (token, check) in tokens.iter().zip(checks) {
                if check? {
                    limited.push(token.clone());
                }
            }
            let mut counts = TeamCounts::default();
            let results: Vec<PipelineResult<LogsAdmissionInput>> = values
                .into_iter()
                .map(|v| {
                    if is_unbilled_internal(&v.message) || !limited.contains(&v.message.token) {
                        return ok(v);
                    }
                    counts.add(v.message.team_id);
                    record_dropped(&v.usage, &v.message);
                    drop("quota_limited")
                })
                .collect();
            counts.report("quota_limited");
            Ok(results)
        }
    })
}

struct Indexed<'a>(usize, &'a LogsIngestionMessage);

impl RateLimitedMessage for Indexed<'_> {
    fn team_id(&self) -> i64 {
        self.1.team_id
    }
    fn bytes_uncompressed(&self) -> f64 {
        self.1.bytes_uncompressed
    }
    fn created_at_header(&self) -> Option<&[u8]> {
        self.1.created_at_header()
    }
}

pub fn create_rate_limit_step(context: Arc<LogsPipelineContext>) -> AdmissionStep {
    ChunkProcessingStep::new("rateLimitStep", move |values: Vec<LogsAdmissionInput>| {
        let context = context.clone();
        async move {
            let dropped_indexes: HashSet<usize> = {
                let billed: Vec<Indexed<'_>> = values
                    .iter()
                    .enumerate()
                    .filter(|(_, v)| !is_unbilled_internal(&v.message))
                    .map(|(i, v)| Indexed(i, &v.message))
                    .collect();
                let filtered = context.rate_limiter.filter_messages(billed).await?;
                filtered.dropped.iter().map(|m| m.0).collect()
            };
            let mut counts = TeamCounts::default();
            let results: Vec<PipelineResult<LogsAdmissionInput>> = values
                .into_iter()
                .enumerate()
                .map(|(i, v)| {
                    if !dropped_indexes.contains(&i) {
                        return ok(v);
                    }
                    counts.add(v.message.team_id);
                    record_dropped(&v.usage, &v.message);
                    drop("rate_limited")
                })
                .collect();
            counts.report("rate_limited");
            Ok(results)
        }
    })
}

/// Allowed is gross here, because processing takes off the drop-rule credit.
pub fn create_record_allowed_usage_step() -> AdmissionStep {
    ChunkProcessingStep::sync(
        "recordAllowedUsageStep",
        |values: Vec<LogsAdmissionInput>| {
            let (mut bytes, mut records, mut bytes_records) = (0.0, 0.0, 0.0);
            for v in values.iter().filter(|v| !is_unbilled_internal(&v.message)) {
                record_allowed(&v.usage, &v.message);
                bytes += v.message.bytes_uncompressed;
                bytes_records += v.message.bytes_uncompressed_records;
                records += v.message.record_count;
            }
            counter!("logs_ingestion_bytes_allowed_records_total").increment(bytes_records as u64);
            counter!("logs_ingestion_bytes_allowed_total").increment(bytes as u64);
            counter!("logs_ingestion_records_allowed_total").increment(records as u64);
            Ok(values.into_iter().map(ok).collect())
        },
    )
}

/// Runs after admission even when every message was dropped, which no chunk step does.
pub fn report_dropped_usage(usage: &LogsBatchUsage) {
    for (team_id, stats) in &usage.lock().unwrap().0 {
        let team = team_id.to_string();
        if stats.bytes_dropped > 0.0 {
            counter!("logs_ingestion_bytes_dropped_total", "team_id" => team.clone())
                .increment(stats.bytes_dropped as u64);
        }
        if stats.records_dropped > 0.0 {
            counter!("logs_ingestion_records_dropped_total", "team_id" => team)
                .increment(stats.records_dropped as u64);
        }
    }
}
