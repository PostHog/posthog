//! Port of `retention-expired-stage.ts`: drops rows whose timestamp plus retention is already past.

use std::sync::Arc;

use async_trait::async_trait;
use metrics::counter;

use crate::content_weights::{
    BatchContext, FilterResult, FilterStage, PipelineStage, StageDropStats, StagedRecord,
};
use crate::record::LogRecord;

const MICROS_PER_DAY: f64 = 86_400_000_000.0;

pub const RETENTION_EXPIRED_STAGE_NAME: &str = "retention_expired";

fn is_past_retention(timestamp_micros: f64, retention_days: f64, now_micros: f64) -> bool {
    timestamp_micros + retention_days * MICROS_PER_DAY <= now_micros
}

pub fn can_hold_expired_row(
    min_timestamp_micros: Option<f64>,
    shortest_retention_days: f64,
    now_micros: f64,
) -> bool {
    min_timestamp_micros
        .is_some_and(|ts| is_past_retention(ts, shortest_retention_days, now_micros))
}

/// `isExpired`: the row's `retention_days` when above 0, else the team default, as ClickHouse's
/// `original_expiry_timestamp` does.
pub fn is_expired(record: &LogRecord, default_retention_days: f64, now_micros: f64) -> bool {
    let Some(timestamp) = record.timestamp() else {
        return false;
    };
    let row_days = record.retention_days().unwrap_or(0) as f64;
    let days = if row_days > 0.0 {
        row_days
    } else {
        default_retention_days
    };
    is_past_retention(timestamp as f64, days, now_micros)
}

struct RetentionExpiredStage {
    team_id: i64,
    default_retention_days: f64,
    now_micros: f64,
}

#[async_trait]
impl FilterStage for RetentionExpiredStage {
    fn name(&self) -> &str {
        RETENTION_EXPIRED_STAGE_NAME
    }

    async fn run(
        &self,
        records: Vec<StagedRecord>,
        batch: &BatchContext,
    ) -> anyhow::Result<FilterResult> {
        let mut stats = StageDropStats::default();
        let mut kept = Vec::with_capacity(records.len());
        for staged in records {
            if is_expired(&staged.record, self.default_retention_days, self.now_micros) {
                stats.records_dropped += 1.0;
                stats.content_bytes_dropped += batch.content_bytes_of(&staged);
            } else {
                kept.push(staged);
            }
        }
        if stats.records_dropped > 0.0 {
            let team: Arc<str> = Arc::from(self.team_id.to_string());
            counter!("logs_ingestion_retention_expired_rows_dropped_total", "team_id" => team)
                .increment(stats.records_dropped as u64);
        }
        Ok(FilterResult { kept, stats })
    }
}

pub fn make_retention_expired_stage(
    team_id: i64,
    default_retention_days: f64,
    now_micros: f64,
) -> PipelineStage {
    PipelineStage::Filter(Box::new(RetentionExpiredStage {
        team_id,
        default_retention_days,
        now_micros,
    }))
}
