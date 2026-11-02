//! Port of `compile-retention-rules.ts`.

use crate::js::JsValue;
use crate::property_filter::coerce::JsTypeError;
use crate::sampling::parse_filter_group;

use super::evaluate::{is_valid_retention_days, CompiledRetentionRule, CompiledRetentionRuleSet};

/// The most enabled rules compiled for one team; the fetch is ordered by priority first.
pub const MAX_ENABLED_RETENTION_RULES: usize = 100;

#[derive(Debug, Clone)]
pub struct RetentionRuleRow {
    pub id: String,
    pub config: JsValue,
    pub version: Option<i64>,
}

/// `compileRetentionRuleSet`. A `filter_group` with a null child makes the TypeScript throw.
pub fn compile_retention_rule_set(
    rows: &[RetentionRuleRow],
) -> Result<CompiledRetentionRuleSet, JsTypeError> {
    let mut rules = Vec::new();
    for row in rows.iter().take(MAX_ENABLED_RETENTION_RULES) {
        let JsValue::Object(config) = &row.config else {
            continue;
        };
        let Some(JsValue::Number(days)) = config.get("retention_days") else {
            continue;
        };
        if !is_valid_retention_days(*days) {
            continue;
        }
        let filter_group =
            parse_filter_group(config.get("filter_group").unwrap_or(&JsValue::Null))?;
        rules.push(CompiledRetentionRule {
            id: row.id.clone(),
            filter_group,
            retention_days: *days as i64,
        });
    }
    Ok(CompiledRetentionRuleSet { rules })
}
