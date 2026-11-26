//! The parsers accept any JSON shape. A null `config` or a null `filter_group` child throws in `compileRuleSet`, so both are errors here.

use std::sync::Arc;

use crate::filter_group::{FilterGroupNode, FilterNode, GroupType, MAX_FILTER_GROUP_DEPTH};

// A filter group past this depth is rejected before any value that `json_parse` did not build.
const _: () = assert!(MAX_FILTER_GROUP_DEPTH < crate::js::MAX_BUILT_DEPTH);
use crate::js::{JsString, JsValue};
use crate::property_filter::coerce::{js_trim, JsTypeError};
use crate::property_filter::re2::Re2;
use crate::property_filter::PropertyFilterLeaf;

use super::evaluate::{
    AlwaysKeep, AttributePredicate, CompiledRuleSet, CompiledSamplingRule, CostUnit, RateLimit,
    RuleType, SeverityAction,
};

pub const MAX_FILTER_GROUP_NODES: usize = 256;
/// An array value counts as its length.
pub const MAX_FILTER_GROUP_LEAF_VALUES: usize = 256;

const MAX_LOGS_PER_SECOND: f64 = 1_000_000.0;
const MAX_BURST_LOGS: f64 = 10_000_000.0;
const MAX_KB_PER_SECOND: f64 = 1_000_000.0;
const MAX_BURST_KB: f64 = 10_000_000.0;
/// Decimal KB, the unit of the drop-rule form and the API validator.
const BYTES_PER_KB: f64 = 1000.0;

#[derive(Debug, Clone)]
pub struct SamplingRuleRow {
    pub id: String,
    pub rule_type: String,
    pub scope_service: Option<String>,
    pub scope_path_pattern: Option<String>,
    pub scope_attribute_filters: JsValue,
    pub config: JsValue,
    pub version: Option<i64>,
}

/// Primitives read as `undefined`, because their properties are never these names.
fn prop<'a>(value: &'a JsValue, name: &str) -> Option<&'a JsValue> {
    match value {
        JsValue::Object(o) => o.get(name),
        _ => None,
    }
}

fn number(value: Option<&JsValue>) -> Option<f64> {
    match value {
        Some(JsValue::Number(n)) => Some(*n),
        _ => None,
    }
}

fn is_group(value: &JsValue) -> bool {
    matches!(prop(value, "values"), Some(JsValue::Array(_)))
        && matches!(prop(value, "type"), Some(JsValue::String(t)) if t == "AND" || t == "OR")
}

fn children(value: &JsValue) -> &[JsValue] {
    match prop(value, "values") {
        Some(JsValue::Array(items)) => items,
        _ => &[],
    }
}

/// Reading `.values` of a null child throws at any depth. A heap stack keeps a deep rule off the thread stack.
fn group_depth(node: &JsValue, depth: usize) -> Result<usize, JsTypeError> {
    let mut max_depth = depth;
    let mut stack = vec![(node, depth)];
    while let Some((node, depth)) = stack.pop() {
        if matches!(node, JsValue::Null) {
            return Err(JsTypeError(
                "Cannot read properties of null (reading 'values')",
            ));
        }
        max_depth = max_depth.max(depth);
        if is_group(node) {
            stack.extend(children(node).iter().map(|child| (child, depth + 1)));
        }
    }
    Ok(max_depth)
}

fn node_count(node: &JsValue) -> usize {
    if !is_group(node) {
        return 1;
    }
    1 + children(node).iter().map(node_count).sum::<usize>()
}

fn leaf_value_count(node: &JsValue) -> usize {
    if !is_group(node) {
        return match prop(node, "value") {
            Some(JsValue::Array(items)) => items.len(),
            None | Some(JsValue::Null) => 0,
            Some(_) => 1,
        };
    }
    children(node).iter().map(leaf_value_count).sum()
}

fn to_node(node: &JsValue) -> FilterNode {
    if is_group(node) {
        FilterNode::Group(to_group(node))
    } else {
        FilterNode::Leaf(Box::new(PropertyFilterLeaf::from_json(node)))
    }
}

fn to_group(node: &JsValue) -> FilterGroupNode {
    let group_type = match prop(node, "type") {
        Some(JsValue::String(t)) if t == "OR" => GroupType::Or,
        _ => GroupType::And,
    };
    FilterGroupNode {
        group_type,
        values: children(node).iter().map(to_node).collect(),
    }
}

/// `Ok(None)` for a missing or malformed group, or one past the bounds. Pass `JsValue::Null` for `undefined`.
pub fn parse_filter_group(raw: &JsValue) -> Result<Option<FilterGroupNode>, JsTypeError> {
    if !matches!(raw, JsValue::Object(_)) || !is_group(raw) {
        return Ok(None);
    }
    let mut parsed = raw;
    if let [inner] = children(raw) {
        if matches!(inner, JsValue::Object(_)) && is_group(inner) {
            parsed = inner;
        }
    }
    if group_depth(parsed, 0)? > MAX_FILTER_GROUP_DEPTH {
        return Ok(None);
    }
    if node_count(parsed) > MAX_FILTER_GROUP_NODES {
        return Ok(None);
    }
    if leaf_value_count(parsed) > MAX_FILTER_GROUP_LEAF_VALUES {
        return Ok(None);
    }
    Ok(Some(to_group(parsed)))
}

fn parse_severity_actions(raw: &JsValue) -> [SeverityAction; 4] {
    let mut out = [SeverityAction::Keep; 4];
    if !raw.is_object_like() {
        return out;
    }
    let Some(actions) = prop(raw, "actions") else {
        return out;
    };
    if !actions.is_object_like() {
        return out;
    }
    for (i, level) in ["DEBUG", "INFO", "WARN", "ERROR"].iter().enumerate() {
        let Some(action) = prop(actions, level) else {
            continue;
        };
        let Some(JsValue::String(kind)) = prop(action, "type") else {
            continue;
        };
        out[i] = if kind == "drop" {
            SeverityAction::Drop
        } else if let (true, Some(rate)) = (kind == "sample", number(prop(action, "rate"))) {
            SeverityAction::Sample(rate.clamp(0.0, 1.0))
        } else {
            SeverityAction::Keep
        };
    }
    out
}

fn parse_rate_limit(config: &JsValue) -> Option<RateLimit> {
    let finite = |v: Option<f64>| v.filter(|n| n.is_finite());
    if let Some(kbps) = finite(number(prop(config, "kb_per_second"))) {
        if (1.0..=MAX_KB_PER_SECOND).contains(&kbps) {
            let refill_kb = kbps.floor();
            let burst_kb = match finite(number(prop(config, "burst_kb"))) {
                Some(b) if b >= refill_kb => b.floor().min(MAX_BURST_KB),
                _ => (refill_kb * 3.0).min(MAX_BURST_KB),
            };
            return Some(RateLimit {
                refill_per_second: refill_kb * BYTES_PER_KB,
                pool_max: burst_kb * BYTES_PER_KB,
                cost_unit: CostUnit::Bytes,
            });
        }
    }
    let lps = finite(number(prop(config, "logs_per_second")))?;
    if !(1.0..=MAX_LOGS_PER_SECOND).contains(&lps) {
        return None;
    }
    let refill = lps.floor();
    let pool_max = match finite(number(prop(config, "burst_logs"))) {
        Some(b) if b >= refill => b.floor().min(MAX_BURST_LOGS),
        _ => (refill * 3.0).min(MAX_BURST_LOGS),
    };
    Some(RateLimit {
        refill_per_second: refill,
        pool_max,
        cost_unit: CostUnit::Records,
    })
}

fn parse_always_keep(config: &JsValue) -> Result<Option<AlwaysKeep>, JsTypeError> {
    if matches!(config, JsValue::Null) {
        return Err(JsTypeError(
            "Cannot read properties of null (reading 'always_keep')",
        ));
    }
    let Some(ak) = prop(config, "always_keep") else {
        return Ok(None);
    };
    if !ak.is_object_like() {
        return Ok(None);
    }
    let status_gte = number(prop(ak, "status_gte"));
    let latency_ms_gt = number(prop(ak, "latency_ms_gt"));
    let mut attribute_predicates = Vec::new();
    if let Some(JsValue::Array(preds)) = prop(ak, "attribute_predicates") {
        for p in preds {
            let (Some(JsValue::String(key)), Some(JsValue::String(op))) =
                (prop(p, "key"), prop(p, "op"))
            else {
                continue;
            };
            let value = match prop(p, "value") {
                Some(JsValue::String(v)) => Some(v.clone()),
                _ => None,
            };
            attribute_predicates.push(AttributePredicate {
                key: key.clone(),
                op: op.clone(),
                value,
            });
        }
    }
    if status_gte.is_none() && latency_ms_gt.is_none() && attribute_predicates.is_empty() {
        return Ok(None);
    }
    Ok(Some(AlwaysKeep {
        status_gte,
        latency_ms_gt,
        attribute_predicates,
    }))
}

pub fn compile_rule_set(rows: &[SamplingRuleRow]) -> Result<CompiledRuleSet, JsTypeError> {
    let mut rules = Vec::with_capacity(rows.len());
    let mut has_rate_limit_rules = false;
    for row in rows {
        let path_regex = match row.scope_path_pattern.as_deref() {
            Some(p) if !p.is_empty() => {
                Some(Arc::new(Re2::without_flags(p).unwrap_or_else(|_| {
                    // An invalid pattern scopes the rule to empty paths only, so it never over-scopes.
                    Re2::without_flags("^$").expect("static pattern")
                })))
            }
            _ => None,
        };
        let config = &row.config;
        let mut path_drop_patterns = None;
        let mut path_drop_match_attribute_key = None;
        let mut filter_group = None;
        if row.rule_type == "path_drop" {
            if matches!(config, JsValue::Null) {
                return Err(JsTypeError(
                    "Cannot read properties of null (reading 'patterns')",
                ));
            }
            let mut patterns = Vec::new();
            if let Some(JsValue::Array(items)) = prop(config, "patterns") {
                for p in items {
                    if let JsValue::String(text) = p {
                        if let Ok(rx) = Re2::new(text.bytes_wtf8(), "") {
                            patterns.push(Arc::new(rx));
                        }
                    }
                }
            }
            path_drop_patterns = Some(patterns);
            if let Some(JsValue::String(key)) = prop(config, "match_attribute_key") {
                let text = key.to_utf8_lossy();
                let trimmed = js_trim(&text);
                if !trimmed.is_empty() {
                    path_drop_match_attribute_key = Some(trimmed_js(key, trimmed));
                }
            }
            filter_group =
                parse_filter_group(prop(config, "filter_group").unwrap_or(&JsValue::Null))?;
        }
        let rule_type = match row.rule_type.as_str() {
            "rate_limit" => RuleType::RateLimit,
            "severity_sampling" => RuleType::SeveritySampling,
            _ => RuleType::PathDrop,
        };
        let mut rate_limit = None;
        if rule_type == RuleType::RateLimit {
            rate_limit = parse_rate_limit(config);
            if rate_limit.is_some() {
                has_rate_limit_rules = true;
            }
            filter_group =
                parse_filter_group(prop(config, "filter_group").unwrap_or(&JsValue::Null))?;
        }
        let severity_actions = parse_severity_actions(config);
        let always_keep = parse_always_keep(config)?;
        rules.push(CompiledSamplingRule {
            id: row.id.clone(),
            rule_type,
            scope_service: row.scope_service.clone(),
            path_regex,
            path_drop_patterns,
            path_drop_match_attribute_key,
            filter_group,
            severity_actions,
            always_keep,
            rate_limit,
        });
    }
    Ok(CompiledRuleSet {
        rules,
        has_rate_limit_rules,
    })
}

/// A key with a lone surrogate keeps it, so it can never equal a map key.
fn trimmed_js(original: &JsString, trimmed: &str) -> JsString {
    if original.as_str().is_some() {
        JsString::from(trimmed)
    } else {
        original.clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::js::json_parse;

    // Node walks the whole tree: a deep group is rejected, and a null child at any depth throws.
    #[test]
    fn a_deep_filter_group_is_rejected_without_overflow() {
        let n = 50_000;
        let deep = |leaf: &str| {
            let open = r#"{"type":"AND","values":["#.repeat(n);
            let close = "]}".repeat(n);
            json_parse(&format!(
                r#"{{"type":"AND","values":[{open}{leaf}{close}]}}"#
            ))
            .unwrap()
        };
        assert!(matches!(
            parse_filter_group(&deep(r#"{"key":"a"}"#)),
            Ok(None)
        ));
        let shallow_null = json_parse(r#"{"type":"AND","values":[{"type":"OR","values":[null]}]}"#);
        assert!(parse_filter_group(&shallow_null.unwrap()).is_err());
    }
}
