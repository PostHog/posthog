//! Port of `pipeline/resolve-log-buffer.ts`.

use std::sync::Arc;

use async_trait::async_trait;
use metrics::counter;

use crate::content_weights::{
    BatchContext, DropStats, FilterResult, FilterStage, MutateStage, PipelineStage, StageDropStats,
    StagedRecord,
};
use crate::normalize::{buffer_processing_mode, BufferProcessingMode, LogsSettings};
use crate::pattern::{stamp_pattern_batch, MESSAGE_KEYS};
use crate::pii::PiiScrubStats;
use crate::retention::{can_hold_expired_row, make_retention_expired_stage, make_retention_stage};
use crate::sampling::SAMPLING_STAGE_NAME;

use super::buffer::{process_log_message_buffer, BufferValue, RecordsVisitor};
use super::context::{applies_team_log_rules, team_id_matches_csv, AppSource, LogsPipelineContext};
use super::deps::LogsTransformer;
use super::types::{LogsIngestionMessage, INTERNAL_LOGS_MIN_RETENTION_DAYS};

pub struct ResolvedLogBuffer {
    pub value: Option<BufferValue>,
    pub dropped_reason: Option<String>,
    pub pii: PiiScrubStats,
    pub drops: DropStats,
}

impl ResolvedLogBuffer {
    pub fn records_dropped_by_stage(&self, stage: &str) -> f64 {
        self.drops
            .records_dropped_by_stage
            .get(stage)
            .unwrap_or(0.0)
    }
}

pub fn is_sampling_eval_enabled_for_team(context: &LogsPipelineContext, team_id: i64) -> bool {
    !context.gates.sampling_killswitch
        && team_id_matches_csv(&context.gates.sampling_enabled_teams, team_id)
}

pub fn is_retention_eval_enabled_for_team(context: &LogsPipelineContext, team_id: i64) -> bool {
    !context.gates.retention_killswitch
        && team_id_matches_csv(&context.gates.retention_enabled_teams, team_id)
}

fn is_transformations_enabled_for_team(context: &LogsPipelineContext, team_id: i64) -> bool {
    !context.gates.transformations_killswitch
        && context.deps.logs_transformer.is_some()
        && team_id_matches_csv(&context.gates.transformations_enabled_teams, team_id)
}

/// Logs only: a trace record has no `body`, so masking one measures nothing.
pub fn is_pattern_masking_enabled_for_team(context: &LogsPipelineContext, team_id: i64) -> bool {
    context.identity.app_source == AppSource::Logs
        && team_id_matches_csv(&context.gates.pattern_masking_enabled_teams, team_id)
}

/// Hog transforms mutate the survivors in place and may drop. Partial drops are not credited.
struct TransformStage {
    transformer: Arc<dyn LogsTransformer>,
    team_id: i64,
}

#[async_trait]
impl FilterStage for TransformStage {
    fn name(&self) -> &str {
        "transformations"
    }

    async fn run(
        &self,
        mut records: Vec<StagedRecord>,
        _batch: &BatchContext,
    ) -> anyhow::Result<FilterResult> {
        self.transformer
            .transform_records(self.team_id, &mut records)
            .await?;
        Ok(FilterResult {
            kept: records,
            stats: StageDropStats::default(),
        })
    }
}

struct PatternMaskingStage {
    message_keys: Vec<String>,
}

#[async_trait]
impl MutateStage for PatternMaskingStage {
    fn name(&self) -> &str {
        "pattern_masking"
    }

    async fn run(&self, records: &mut Vec<StagedRecord>) -> anyhow::Result<()> {
        let keys: Vec<&str> = self.message_keys.iter().map(String::as_str).collect();
        for staged in records.iter_mut() {
            stamp_pattern_batch(std::slice::from_mut(&mut staged.record), &keys);
        }
        Ok(())
    }
}

async fn build_transform_stage(
    context: &LogsPipelineContext,
    message: &LogsIngestionMessage,
) -> anyhow::Result<Option<PipelineStage>> {
    let Some(transformer) = context.deps.logs_transformer.clone() else {
        return Ok(None);
    };
    if !applies_team_log_rules(message)
        || !is_transformations_enabled_for_team(context, message.team_id)
    {
        return Ok(None);
    }
    if !transformer
        .team_has_transformations(message.team_id)
        .await?
    {
        return Ok(None);
    }
    Ok(Some(PipelineStage::Filter(Box::new(TransformStage {
        transformer,
        team_id: message.team_id,
    }))))
}

pub async fn resolve_log_buffer(
    context: &LogsPipelineContext,
    message: &LogsIngestionMessage,
    settings: &LogsSettings,
    default_retention_days: f64,
    visitor: Option<RecordsVisitor<'_>>,
) -> anyhow::Result<ResolvedLogBuffer> {
    let deps = &context.deps;
    let team_id = message.team_id;

    let mut rule_set = None;
    if let Some(cache) = &deps.sampling_rules {
        if is_sampling_eval_enabled_for_team(context, team_id) && applies_team_log_rules(message) {
            rule_set = Some(cache.get_compiled_rule_set(team_id).await?);
        }
    }
    let use_sampling = rule_set.as_ref().is_some_and(|r| !r.rules.is_empty());
    let transform_stage = build_transform_stage(context, message).await?;

    let mut retention_rules = None;
    if let Some(cache) = &deps.retention_rules {
        if is_retention_eval_enabled_for_team(context, team_id) && applies_team_log_rules(message) {
            retention_rules = Some(
                cache
                    .get_compiled_rule_set(team_id, &context.identity.retention_rule_source)
                    .await?,
            );
        }
    }
    let use_retention = retention_rules
        .as_ref()
        .is_some_and(|r| !r.rules.is_empty());

    let mut stages: Vec<PipelineStage> = Vec::new();
    if use_sampling {
        stages.push(context.sampling_service.make_sampling_stage(
            rule_set.clone().unwrap(),
            Some(team_id),
            message.bytes_uncompressed,
        ));
    }
    if let Some(stage) = transform_stage {
        stages.push(stage);
    }
    let mut shortest_retention_days = if message.internal_logs.is_some() {
        INTERNAL_LOGS_MIN_RETENTION_DAYS
    } else {
        default_retention_days
    };
    if let Some(rules) = retention_rules.filter(|_| use_retention) {
        shortest_retention_days = rules
            .rules
            .iter()
            .map(|r| r.retention_days as f64)
            .fold(default_retention_days, f64::min);
        stages.push(make_retention_stage(
            rules,
            team_id,
            default_retention_days as i64,
        ));
    }

    // Checking rows for expiry needs a decode, which only backdated imports need.
    let now_micros = context.now_ms() * 1000.0;
    if can_hold_expired_row(
        message.min_timestamp_micros,
        shortest_retention_days,
        now_micros,
    ) {
        stages.push(make_retention_expired_stage(
            team_id,
            default_retention_days,
            now_micros,
        ));
    }

    if is_pattern_masking_enabled_for_team(context, team_id) {
        let mode_without_masking =
            buffer_processing_mode(settings, stages.len(), visitor.is_some());
        if mode_without_masking != BufferProcessingMode::DecodeAndReencode {
            let from = match mode_without_masking {
                BufferProcessingMode::Passthrough => "passthrough",
                _ => "decode_only",
            };
            counter!("logs_ingestion_pattern_forced_decode_total", "from" => from).increment(1);
        }
        let message_keys = match &deps.pattern_message_keys {
            Some(cache) => context.retry(|| cache.get_message_keys(team_id)).await?,
            None => MESSAGE_KEYS.iter().map(|k| k.to_string()).collect(),
        };
        stages.push(PipelineStage::Mutate(Box::new(PatternMaskingStage {
            message_keys,
        })));
    }

    let buffer = message.message.value.as_deref().unwrap_or_default();
    let processed = process_log_message_buffer(buffer, settings, visitor, &stages).await?;

    let team_label = team_id.to_string();
    let by_sampling = processed
        .drops
        .records_dropped_by_stage
        .get(SAMPLING_STAGE_NAME)
        .unwrap_or(0.0);
    if by_sampling > 0.0 {
        counter!("logs_ingestion_sampling_records_dropped_total", "team_id" => team_label.clone())
            .increment(by_sampling as u64);
    }
    if processed.drops.stage.bytes_dropped > 0.0 {
        counter!("logs_ingestion_bytes_dropped_by_rule_total", "team_id" => team_label)
            .increment(processed.drops.stage.bytes_dropped as u64);
    }

    match processed.value {
        BufferValue::Dropped => {
            let reason = match &processed.drops.dropped_by {
                Some(stage) => format!("{stage}_all_dropped"),
                None => "empty_batch".to_string(),
            };
            Ok(ResolvedLogBuffer {
                value: None,
                dropped_reason: Some(reason),
                pii: processed.pii,
                drops: processed.drops,
            })
        }
        value => Ok(ResolvedLogBuffer {
            value: Some(value),
            dropped_reason: None,
            pii: processed.pii,
            drops: processed.drops,
        }),
    }
}
