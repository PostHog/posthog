use std::sync::Arc;

use async_trait::async_trait;
use metrics::counter;

use crate::content_weights::{MutateStage, PipelineStage, StagedRecord};

use super::evaluate::{safe_evaluate_retention_days, CompiledRetentionRuleSet};

pub const RETENTION_STAGE_NAME: &str = "retention";

struct RetentionStage {
    rule_set: Arc<CompiledRetentionRuleSet>,
    team_id: i64,
    default_retention_days: i64,
}

#[async_trait]
impl MutateStage for RetentionStage {
    fn name(&self) -> &str {
        RETENTION_STAGE_NAME
    }

    async fn run(&self, records: &mut Vec<StagedRecord>) -> anyhow::Result<()> {
        let mut matched = 0u64;
        for staged in records.iter_mut() {
            let rule_value =
                safe_evaluate_retention_days(Some(&self.rule_set), &staged.record, self.team_id);
            staged
                .record
                .set_retention_days(rule_value.unwrap_or(self.default_retention_days));
            if rule_value.is_some() {
                matched += 1;
            }
        }
        let team: Arc<str> = Arc::from(self.team_id.to_string());
        if matched > 0 {
            counter!("logs_ingestion_retention_rows_stamped_total", "team_id" => team.clone(), "matched" => "true")
                .increment(matched);
        }
        let defaulted = records.len() as u64 - matched;
        if defaulted > 0 {
            counter!("logs_ingestion_retention_rows_stamped_total", "team_id" => team, "matched" => "false")
                .increment(defaulted);
        }
        Ok(())
    }
}

pub fn make_retention_stage(
    rule_set: Arc<CompiledRetentionRuleSet>,
    team_id: i64,
    default_retention_days: i64,
) -> PipelineStage {
    PipelineStage::Mutate(Box::new(RetentionStage {
        rule_set,
        team_id,
        default_retention_days,
    }))
}
