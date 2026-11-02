//! Port of `compile-metric-rules.ts`.

use std::sync::Arc;

use super::filter::{parse_filter_group, FilterGroupMatcher, FilterGroupParser};
use super::tally::SPAN_VALUE_DURATION_MS;
use crate::js::{JsObject, JsString, JsValue};
use crate::property_filter::coerce::JsTypeError;

/// Mirrors `MAX_METRIC_RULE_GROUP_BY_KEYS` in `products/logs/backend/models.py`.
pub const MAX_GROUP_BY_KEYS: usize = 5;

pub const SPAN_GROUP_BY_TOP_LEVEL_KEYS: [&str; 4] = ["service_name", "name", "status_code", "kind"];

pub const LOG_GROUP_BY_TOP_LEVEL_KEYS: [&str; 3] = ["service_name", "severity_text", "event_name"];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum MetricRuleSource {
    Logs,
    Spans,
}

impl MetricRuleSource {
    pub fn as_str(self) -> &'static str {
        match self {
            MetricRuleSource::Logs => "logs",
            MetricRuleSource::Spans => "spans",
        }
    }
}

/// A raw `logs_logsmetricrule` row. The untyped columns stay `JsValue`, because the
/// TypeScript checks their runtime type. `JsValue::Null` stands for both null and a
/// missing property: every check treats the two the same.
#[derive(Debug, Clone, PartialEq)]
pub struct MetricRuleRow {
    pub id: String,
    pub metric_name: JsValue,
    pub filter_group: JsValue,
    pub value_attribute: JsValue,
    pub group_by: JsValue,
    pub source: JsValue,
}

impl MetricRuleRow {
    pub fn from_js(row: &JsObject) -> Self {
        let field = |name: &str| row.get(name).cloned().unwrap_or(JsValue::Null);
        let id = match row.get("id") {
            Some(JsValue::String(s)) => s.to_utf8_lossy().into_owned(),
            Some(JsValue::Number(n)) => crate::js::number_to_string(*n),
            _ => String::new(),
        };
        Self {
            id,
            metric_name: field("metric_name"),
            filter_group: field("filter_group"),
            value_attribute: field("value_attribute"),
            group_by: field("group_by"),
            source: field("source"),
        }
    }
}

#[derive(Debug, Clone)]
pub struct CompiledMetricRule {
    pub id: String,
    pub metric_name: JsString,
    pub source: MetricRuleSource,
    /// `None` means every ingested record matches.
    pub filter_group: Option<Arc<dyn FilterGroupMatcher>>,
    /// The key that holds the numeric value to aggregate. `None` counts records.
    pub value_attribute: Option<JsString>,
    pub group_by: Vec<JsString>,
}

pub(crate) fn starts_with(s: &JsString, prefix: &str) -> bool {
    s.bytes_wtf8().starts_with(prefix.as_bytes())
}

fn is_attribute_key(k: &JsString) -> bool {
    starts_with(k, "attributes.") || starts_with(k, "resource_attributes.")
}

fn is_one_of(k: &JsString, keys: &[&str]) -> bool {
    k.as_str().is_some_and(|k| keys.contains(&k))
}

/// `compileMetricRules`. `Err` is a throw from `parseFilterGroup`, which rejects the whole call.
pub fn compile_metric_rules(
    rows: &[MetricRuleRow],
) -> Result<Vec<CompiledMetricRule>, JsTypeError> {
    compile_metric_rules_with(rows, parse_filter_group)
}

pub fn compile_metric_rules_with(
    rows: &[MetricRuleRow],
    parse: FilterGroupParser,
) -> Result<Vec<CompiledMetricRule>, JsTypeError> {
    let mut out = Vec::new();
    for row in rows {
        let metric_name = match &row.metric_name {
            JsValue::String(s) if !s.is_empty() => s.clone(),
            _ => continue,
        };
        let source = match &row.source {
            JsValue::String(s) if *s == "spans" => MetricRuleSource::Spans,
            _ => MetricRuleSource::Logs,
        };
        let mut filter_group = None;
        if !matches!(row.filter_group, JsValue::Null) {
            match parse(&row.filter_group)? {
                Some(group) => filter_group = Some(group),
                // A null filter counts everything, so an unparseable filter skips the rule.
                None => continue,
            }
        }
        let group_by: Vec<JsString> = match &row.group_by {
            JsValue::Array(items) => items
                .iter()
                .filter_map(|k| match k {
                    JsValue::String(s) if !s.is_empty() => Some(s.clone()),
                    _ => None,
                })
                .take(MAX_GROUP_BY_KEYS)
                .collect(),
            _ => Vec::new(),
        };
        let value_attribute = match &row.value_attribute {
            JsValue::String(s) if !s.is_empty() => Some(s.clone()),
            _ => None,
        };
        let allowed_top_level: &[&str] = match source {
            MetricRuleSource::Spans => &SPAN_GROUP_BY_TOP_LEVEL_KEYS,
            MetricRuleSource::Logs => &LOG_GROUP_BY_TOP_LEVEL_KEYS,
        };
        // A key that the source does not have gives an empty label on every series.
        if group_by
            .iter()
            .any(|k| !is_one_of(k, allowed_top_level) && !is_attribute_key(k))
        {
            continue;
        }
        // A log record has no end_time, so the span duration pseudo-key never applies to it.
        if source == MetricRuleSource::Logs
            && value_attribute
                .as_ref()
                .is_some_and(|v| *v == SPAN_VALUE_DURATION_MS)
        {
            continue;
        }
        out.push(CompiledMetricRule {
            id: row.id.clone(),
            metric_name,
            source,
            filter_group,
            value_attribute,
            group_by,
        });
    }
    Ok(out)
}
