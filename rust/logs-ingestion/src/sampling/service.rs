//! Port of `nodejs/src/logs/sampling/logs-sampling.service.ts`: the sampling `filter` stage, with
//! per-rule drop accounting and Redis token buckets for `rate_limit` rules.

use std::sync::Arc;

use async_trait::async_trait;
use metrics::counter;

use crate::content_weights::{
    BatchContext, FilterResult, FilterStage, PipelineStage, StageDropStats, StagedRecord,
};
use crate::rate_limiter::{
    Clock, KeyRoot, KeyedRateLimitRequest, KeyedRateLimiter, KeyedRateLimiterConfig, ScriptVersion,
    TokenBucketRedis,
};
use crate::record::LogRecord;

use super::evaluate::{
    classify_sampling_record, evaluate_log_record, CompiledRuleSet, CostUnit, EvaluateResult,
    SamplingClassifyResult, SamplingDecision,
};

pub const SAMPLING_STAGE_NAME: &str = "sampling";
pub const SAMPLING_RATE_LIMITER_NAME: &str = "logs-sampling-rate";

fn record_bytes(record: &LogRecord) -> f64 {
    record.bytes_uncompressed().map_or(0.0, |n| n as f64)
}

fn count_eval_error(team_id: i64, phase: &'static str, error: &dyn std::fmt::Display) {
    let team: Arc<str> = Arc::from(team_id.to_string());
    counter!("logs_ingestion_sampling_eval_error_total", "team_id" => team, "phase" => phase)
        .increment(1);
    tracing::warn!(team_id, %error, "[logs-sampling] rule evaluation threw, keeping record");
}

/// `safeClassifySamplingRecord`: an evaluation error keeps the record.
fn safe_classify(
    rule_set: &CompiledRuleSet,
    record: &LogRecord,
    team_id: i64,
) -> SamplingClassifyResult {
    classify_sampling_record(Some(rule_set), record).unwrap_or_else(|e| {
        count_eval_error(team_id, "classify", &e);
        SamplingClassifyResult::Resolved {
            decision: SamplingDecision::Keep,
            rule_id: None,
        }
    })
}

fn safe_evaluate(rule_set: &CompiledRuleSet, record: &LogRecord, team_id: i64) -> EvaluateResult {
    evaluate_log_record(Some(rule_set), record).unwrap_or_else(|e| {
        count_eval_error(team_id, "evaluate", &e);
        EvaluateResult {
            decision: SamplingDecision::Keep,
            rule_id: None,
        }
    })
}

pub struct LogsSamplingService {
    rate_limiter: KeyedRateLimiter,
}

impl LogsSamplingService {
    pub fn new(
        redis: Arc<dyn TokenBucketRedis>,
        ttl_seconds: f64,
        key_root: KeyRoot,
        clock: Clock,
    ) -> Self {
        let mut config = KeyedRateLimiterConfig::new(SAMPLING_RATE_LIMITER_NAME, key_root);
        config.ttl_seconds = Some(ttl_seconds);
        config.script_version = ScriptVersion::V3;
        LogsSamplingService {
            rate_limiter: KeyedRateLimiter::with_clock(config, redis, clock),
        }
    }

    pub async fn sample_records(
        &self,
        records: Vec<StagedRecord>,
        rule_set: &CompiledRuleSet,
        batch: &BatchContext,
        team_id: Option<i64>,
        header_bytes_uncompressed: f64,
    ) -> anyhow::Result<FilterResult> {
        let mut kept = Vec::with_capacity(records.len());
        let mut stats = StageDropStats::default();
        let drop = |stats: &mut StageDropStats, staged: &StagedRecord, rule_id: Option<&str>| {
            let rb = record_bytes(&staged.record);
            stats.records_dropped += 1.0;
            stats.bytes_dropped += rb;
            stats.content_bytes_dropped += batch.content_bytes_of(staged);
            if let Some(id) = rule_id {
                stats.records_dropped_by_rule_id.add(id, 1.0);
                stats.bytes_dropped_by_rule_id.add(id, rb);
            }
        };

        match team_id.filter(|_| rule_set.has_rate_limit_rules) {
            Some(team_id) => {
                let classifications: Vec<SamplingClassifyResult> = records
                    .iter()
                    .map(|r| safe_classify(rule_set, &r.record, team_id))
                    .collect();
                let mut pending: Vec<(String, Vec<usize>)> = Vec::new();
                for (i, c) in classifications.iter().enumerate() {
                    if let SamplingClassifyResult::RateLimit { rule_id } = c {
                        match pending.iter_mut().find(|(id, _)| id == rule_id) {
                            Some((_, list)) => list.push(i),
                            None => pending.push((rule_id.clone(), vec![i])),
                        }
                    }
                }
                let rate_keep = self
                    .apply_rate_limits(
                        team_id,
                        rule_set,
                        &pending,
                        &records,
                        header_bytes_uncompressed,
                        batch,
                    )
                    .await?;
                for (i, (staged, c)) in records.into_iter().zip(classifications).enumerate() {
                    match c {
                        SamplingClassifyResult::RateLimit { rule_id } => {
                            if rate_keep[i] == Some(false) {
                                drop(&mut stats, &staged, Some(&rule_id));
                                continue;
                            }
                            kept.push(staged);
                        }
                        SamplingClassifyResult::Resolved { decision, rule_id } => {
                            if decision.drops() {
                                drop(&mut stats, &staged, rule_id.as_deref());
                                continue;
                            }
                            kept.push(staged);
                        }
                    }
                }
            }
            None => {
                for staged in records {
                    let result = safe_evaluate(rule_set, &staged.record, team_id.unwrap_or(0));
                    if result.decision.drops() {
                        drop(&mut stats, &staged, result.rule_id.as_deref());
                        continue;
                    }
                    kept.push(staged);
                }
            }
        }
        Ok(FilterResult { kept, stats })
    }

    /// `applyRateLimits`: per record index, `Some(true)` to keep, `Some(false)` to drop, `None`
    /// when no decision was made (the record is kept).
    async fn apply_rate_limits(
        &self,
        team_id: i64,
        rule_set: &CompiledRuleSet,
        pending: &[(String, Vec<usize>)],
        records: &[StagedRecord],
        header_bytes_uncompressed: f64,
        batch: &BatchContext,
    ) -> anyhow::Result<Vec<Option<bool>>> {
        let mut keep: Vec<Option<bool>> = vec![None; records.len()];
        if pending.is_empty() {
            return Ok(keep);
        }
        let pro_rata_scale = if header_bytes_uncompressed > 0.0 && batch.content_bytes_total > 0.0 {
            header_bytes_uncompressed / batch.content_bytes_total
        } else {
            0.0
        };
        let byte_cost = |idx: usize| -> f64 {
            if pro_rata_scale > 0.0 {
                batch.content_bytes_of(&records[idx]) * pro_rata_scale
            } else {
                record_bytes(&records[idx].record)
            }
        };
        // `new Map(rules.map(r => [r.id, r]))`: the last rule with an id wins.
        let rule_by_id = |id: &str| rule_set.rules.iter().rev().find(|r| r.id == id);

        let mut entries: Vec<(&[usize], Vec<f64>)> = Vec::new();
        let mut requests: Vec<KeyedRateLimitRequest> = Vec::new();
        for (rule_id, indices) in pending {
            let Some(rl) = rule_by_id(rule_id).and_then(|r| r.rate_limit) else {
                continue;
            };
            if indices.is_empty() {
                continue;
            }
            let costs: Vec<f64> = match rl.cost_unit {
                CostUnit::Bytes => indices.iter().map(|&i| byte_cost(i)).collect(),
                CostUnit::Records => vec![1.0; indices.len()],
            };
            let total_cost = costs.iter().fold(0.0, |a, b| a + b);
            requests.push(KeyedRateLimitRequest {
                id: format!("{team_id}/{rule_id}"),
                cost: total_cost,
                bucket_size: Some(rl.pool_max),
                refill_rate: Some(rl.refill_per_second),
                ttl_seconds: None,
                now: None,
            });
            entries.push((indices, costs));
        }

        if entries.is_empty() {
            for (_, indices) in pending {
                for &i in indices {
                    keep[i] = Some(true);
                }
            }
            return Ok(keep);
        }

        let results = self.rate_limiter.rate_limit_many(&requests).await?;
        for (i, (indices, costs)) in entries.iter().enumerate() {
            let tokens_before = results.get(i).map_or(0.0, |(_, r)| r.tokens_before);
            let budget = tokens_before.floor().max(0.0);
            let mut spent = 0.0;
            for (j, &idx) in indices.iter().enumerate() {
                let next = spent + costs[j];
                let admit = next <= budget;
                keep[idx] = Some(admit);
                if admit {
                    spent = next;
                }
            }
        }
        Ok(keep)
    }

    pub fn make_sampling_stage(
        self: &Arc<Self>,
        rule_set: Arc<CompiledRuleSet>,
        team_id: Option<i64>,
        header_bytes_uncompressed: f64,
    ) -> PipelineStage {
        PipelineStage::Filter(Box::new(SamplingStage {
            service: self.clone(),
            rule_set,
            team_id,
            header_bytes_uncompressed,
        }))
    }
}

struct SamplingStage {
    service: Arc<LogsSamplingService>,
    rule_set: Arc<CompiledRuleSet>,
    team_id: Option<i64>,
    header_bytes_uncompressed: f64,
}

#[async_trait]
impl FilterStage for SamplingStage {
    fn name(&self) -> &str {
        SAMPLING_STAGE_NAME
    }

    async fn run(
        &self,
        records: Vec<StagedRecord>,
        batch: &BatchContext,
    ) -> anyhow::Result<FilterResult> {
        self.service
            .sample_records(
                records,
                &self.rule_set,
                batch,
                self.team_id,
                self.header_bytes_uncompressed,
            )
            .await
    }
}
