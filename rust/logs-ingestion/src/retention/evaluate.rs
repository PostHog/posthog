use std::sync::Arc;

use metrics::counter;

use crate::filter_group::{match_filter_group, FilterGroupNode};
use crate::property_filter::coerce::JsTypeError;
use crate::record::LogRecord;

pub const DEFAULT_RETENTION_DAYS: i64 = 14;
pub const RETENTION_MONTH_DAYS: i64 = 30;
pub const MAX_RETENTION_DAYS: i64 = RETENTION_MONTH_DAYS * 86;

pub fn is_valid_retention_days(days: f64) -> bool {
    if !days.is_finite() || days.fract() != 0.0 {
        return false;
    }
    if days == DEFAULT_RETENTION_DAYS as f64 {
        return true;
    }
    days > 0.0 && days <= MAX_RETENTION_DAYS as f64 && days % RETENTION_MONTH_DAYS as f64 == 0.0
}

#[derive(Debug, Clone)]
pub struct CompiledRetentionRule {
    pub id: String,
    pub filter_group: Option<FilterGroupNode>,
    pub retention_days: i64,
}

#[derive(Debug, Clone, Default)]
pub struct CompiledRetentionRuleSet {
    pub rules: Vec<CompiledRetentionRule>,
}

pub fn evaluate_retention_days(
    rule_set: Option<&CompiledRetentionRuleSet>,
    record: &LogRecord,
) -> Result<Option<i64>, JsTypeError> {
    let Some(rule_set) = rule_set else {
        return Ok(None);
    };
    for rule in &rule_set.rules {
        if let Some(group) = &rule.filter_group {
            if match_filter_group(group, record)? {
                return Ok(Some(rule.retention_days));
            }
        }
    }
    Ok(None)
}

pub fn safe_evaluate_retention_days(
    rule_set: Option<&CompiledRetentionRuleSet>,
    record: &LogRecord,
    team_id: i64,
) -> Option<i64> {
    evaluate_retention_days(rule_set, record).unwrap_or_else(|error| {
        let team: Arc<str> = Arc::from(team_id.to_string());
        counter!("logs_ingestion_retention_eval_error_total", "team_id" => team).increment(1);
        tracing::warn!(team_id, %error, "[logs-retention] rule evaluation threw, using the team default");
        None
    })
}
