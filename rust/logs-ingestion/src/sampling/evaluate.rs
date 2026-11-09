//! `getAttribute` reads the raw JSON-encoded value, unlike the filter-group lookup, and a key that names an `Object.prototype` member reads it.

use std::sync::Arc;

use sha2::{Digest, Sha256};

use crate::filter_group::{lookup_attribute, match_filter_group, AttrLookup, FilterGroupNode};
use crate::js::JsString;
use crate::property_filter::coerce::{js_parse_float, js_parse_int, JsTypeError};
use crate::property_filter::re2::Re2;
use crate::record::LogRecord;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SamplingDecision {
    Keep,
    Drop,
    SampleKept,
    SampleDropped,
}

impl SamplingDecision {
    pub fn as_str(&self) -> &'static str {
        match self {
            SamplingDecision::Keep => "keep",
            SamplingDecision::Drop => "drop",
            SamplingDecision::SampleKept => "sample_kept",
            SamplingDecision::SampleDropped => "sample_dropped",
        }
    }

    pub fn drops(&self) -> bool {
        matches!(
            self,
            SamplingDecision::Drop | SamplingDecision::SampleDropped
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum SeverityAction {
    Keep,
    Drop,
    Sample(f64),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuleType {
    SeveritySampling,
    PathDrop,
    RateLimit,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CostUnit {
    Records,
    Bytes,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RateLimit {
    pub refill_per_second: f64,
    pub pool_max: f64,
    pub cost_unit: CostUnit,
}

#[derive(Debug, Clone, PartialEq)]
pub struct AttributePredicate {
    pub key: JsString,
    pub op: JsString,
    pub value: Option<JsString>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct AlwaysKeep {
    pub status_gte: Option<f64>,
    pub latency_ms_gt: Option<f64>,
    pub attribute_predicates: Vec<AttributePredicate>,
}

#[derive(Debug, Clone)]
pub struct CompiledSamplingRule {
    pub id: String,
    pub rule_type: RuleType,
    pub scope_service: Option<String>,
    pub path_regex: Option<Arc<Re2>>,
    pub path_drop_patterns: Option<Vec<Arc<Re2>>>,
    pub path_drop_match_attribute_key: Option<JsString>,
    pub filter_group: Option<FilterGroupNode>,
    pub severity_actions: [SeverityAction; 4],
    pub always_keep: Option<AlwaysKeep>,
    pub rate_limit: Option<RateLimit>,
}

#[derive(Debug, Clone, Default)]
pub struct CompiledRuleSet {
    pub rules: Vec<CompiledSamplingRule>,
    pub has_rate_limit_rules: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EvaluateResult {
    pub decision: SamplingDecision,
    pub rule_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SamplingClassifyResult {
    Resolved {
        decision: SamplingDecision,
        rule_id: Option<String>,
    },
    RateLimit {
        rule_id: String,
    },
}

const SEV_ORD_DEBUG: usize = 0;
const SEV_ORD_INFO: usize = 1;
const SEV_ORD_WARN: usize = 2;
const SEV_ORD_ERROR: usize = 3;

pub fn severity_ordinal_from_record(record: &LogRecord) -> usize {
    let text = record.severity_text().unwrap_or("").to_lowercase();
    match text.as_str() {
        "trace" | "debug" => return SEV_ORD_DEBUG,
        "info" => return SEV_ORD_INFO,
        "warn" | "warning" => return SEV_ORD_WARN,
        "error" | "fatal" => return SEV_ORD_ERROR,
        _ => {}
    }
    match record.severity_number() {
        None => SEV_ORD_INFO,
        Some(n) if n >= 17 => SEV_ORD_ERROR,
        Some(n) if n >= 13 => SEV_ORD_WARN,
        Some(n) if n >= 9 => SEV_ORD_INFO,
        Some(_) => SEV_ORD_DEBUG,
    }
}

/// With no trace id Node uses `Math.random()`, which no vector can pin, so this uses `rand` and tests check only its range.
pub fn hash01_from_trace_id(trace_id: Option<&[u8]>) -> f64 {
    match trace_id {
        Some(id) if !id.is_empty() => {
            let digest = Sha256::digest(id);
            let n = u32::from_be_bytes([digest[0], digest[1], digest[2], digest[3]]);
            n as f64 / 0xffff_ffffu32 as f64
        }
        _ => rand::random::<f64>(),
    }
}

fn get_attribute<'a>(record: &'a LogRecord, key: &str) -> Option<AttrLookup<'a>> {
    lookup_attribute(record.attributes()?, key)
}

/// A key with a lone surrogate finds nothing.
fn get_attribute_js<'a>(record: &'a LogRecord, key: &JsString) -> Option<AttrLookup<'a>> {
    get_attribute(record, key.as_str()?)
}

fn truthy<'a>(v: Option<AttrLookup<'a>>) -> Option<AttrLookup<'a>> {
    v.filter(|a| !matches!(a, AttrLookup::Own("")))
}

fn path_for_matching(record: &LogRecord) -> &str {
    for key in ["url.path", "http.path", "http.route", "path"] {
        if let Some(v) = truthy(get_attribute(record, key)) {
            return match v {
                AttrLookup::Own(s) => s,
                AttrLookup::Inherited(m) => m.text,
            };
        }
    }
    ""
}

fn always_keep_matches(rule: &CompiledSamplingRule, record: &LogRecord) -> bool {
    let Some(ak) = &rule.always_keep else {
        return false;
    };
    if let Some(status_gte) = ak.status_gte {
        let code_str = truthy(get_attribute(record, "http.status_code"))
            .or_else(|| truthy(get_attribute(record, "http.response.status_code")));
        let code = code_str.map_or(f64::NAN, |s| js_parse_int(s.text(), Some(10)));
        if !code.is_nan() && code >= status_gte {
            return true;
        }
    }
    if let Some(latency_ms_gt) = ak.latency_ms_gt {
        let lat_str = truthy(get_attribute(record, "http.server.duration_ms"))
            .or_else(|| truthy(get_attribute(record, "duration_ms")));
        let lat = lat_str.map_or(f64::NAN, |s| js_parse_float(&JsString::from(s.text())));
        if !lat.is_nan() && lat > latency_ms_gt {
            return true;
        }
    }
    for p in &ak.attribute_predicates {
        let v = get_attribute_js(record, &p.key);
        let op = p.op.as_str();
        if op == Some("exists") && v.is_some() {
            return true;
        }
        if let Some(value) = &p.value {
            let equals = matches!(v, Some(AttrLookup::Own(s)) if value == s);
            if op == Some("eq") && equals {
                return true;
            }
            if op == Some("ne") && v.is_some() && !equals {
                return true;
            }
        }
    }
    false
}

fn path_drop_matches(rule: &CompiledSamplingRule, record: &LogRecord) -> Result<bool, JsTypeError> {
    if let Some(patterns) = rule.path_drop_patterns.as_ref().filter(|p| !p.is_empty()) {
        let path = match &rule.path_drop_match_attribute_key {
            Some(key) => get_attribute_js(record, key).map_or("", |v| match v {
                AttrLookup::Own(s) => s,
                AttrLookup::Inherited(m) => m.text,
            }),
            None => path_for_matching(record),
        };
        if patterns.iter().any(|rx| rx.test(path)) {
            return Ok(true);
        }
    }
    if let Some(group) = &rule.filter_group {
        if match_filter_group(group, record)? {
            return Ok(true);
        }
    }
    Ok(false)
}

fn matches_scope(rule: &CompiledSamplingRule, record: &LogRecord) -> bool {
    if let Some(scope) = rule.scope_service.as_deref().filter(|s| !s.is_empty()) {
        if record.service_name().unwrap_or("") != scope {
            return false;
        }
    }
    if let Some(rx) = &rule.path_regex {
        if !rx.test(path_for_matching(record)) {
            return false;
        }
    }
    true
}

fn severity_decision(action: SeverityAction, record: &LogRecord) -> SamplingDecision {
    match action {
        SeverityAction::Keep => SamplingDecision::Keep,
        SeverityAction::Drop => SamplingDecision::Drop,
        SeverityAction::Sample(rate) => {
            if hash01_from_trace_id(record.trace_id()) < rate {
                SamplingDecision::SampleKept
            } else {
                SamplingDecision::SampleDropped
            }
        }
    }
}

/// Deterministic rules win over `rate_limit` in any order. The first applicable `rate_limit` applies only when none resolves the record.
pub fn classify_sampling_record(
    rule_set: Option<&CompiledRuleSet>,
    record: &LogRecord,
) -> Result<SamplingClassifyResult, JsTypeError> {
    let resolved = |decision, rule_id: Option<&str>| SamplingClassifyResult::Resolved {
        decision,
        rule_id: rule_id.map(str::to_string),
    };
    let Some(rule_set) = rule_set.filter(|r| !r.rules.is_empty()) else {
        return Ok(resolved(SamplingDecision::Keep, None));
    };
    let ord = severity_ordinal_from_record(record);
    let mut pending_rate_limit: Option<&str> = None;
    for rule in &rule_set.rules {
        if !matches_scope(rule, record) {
            continue;
        }
        if always_keep_matches(rule, record) {
            return Ok(resolved(SamplingDecision::Keep, Some(&rule.id)));
        }
        match rule.rule_type {
            RuleType::PathDrop => {
                if path_drop_matches(rule, record)? {
                    return Ok(resolved(SamplingDecision::Drop, Some(&rule.id)));
                }
            }
            RuleType::SeveritySampling => {
                let decision = severity_decision(rule.severity_actions[ord], record);
                return Ok(resolved(decision, Some(&rule.id)));
            }
            RuleType::RateLimit => {
                if rule.rate_limit.is_none() {
                    continue;
                }
                if let Some(group) = &rule.filter_group {
                    if !match_filter_group(group, record)? {
                        continue;
                    }
                }
                if pending_rate_limit.is_none() {
                    pending_rate_limit = Some(&rule.id);
                }
            }
        }
    }
    Ok(match pending_rate_limit {
        Some(id) => SamplingClassifyResult::RateLimit {
            rule_id: id.to_string(),
        },
        None => resolved(SamplingDecision::Keep, None),
    })
}

pub fn evaluate_log_record(
    rule_set: Option<&CompiledRuleSet>,
    record: &LogRecord,
) -> Result<EvaluateResult, JsTypeError> {
    let result = |decision, rule_id: Option<&str>| EvaluateResult {
        decision,
        rule_id: rule_id.map(str::to_string),
    };
    let Some(rule_set) = rule_set.filter(|r| !r.rules.is_empty()) else {
        return Ok(result(SamplingDecision::Keep, None));
    };
    let ord = severity_ordinal_from_record(record);
    for rule in &rule_set.rules {
        if !matches_scope(rule, record) {
            continue;
        }
        if always_keep_matches(rule, record) {
            return Ok(result(SamplingDecision::Keep, Some(&rule.id)));
        }
        match rule.rule_type {
            RuleType::PathDrop => {
                if path_drop_matches(rule, record)? {
                    return Ok(result(SamplingDecision::Drop, Some(&rule.id)));
                }
            }
            RuleType::SeveritySampling => {
                let decision = severity_decision(rule.severity_actions[ord], record);
                return Ok(result(decision, Some(&rule.id)));
            }
            RuleType::RateLimit => {}
        }
    }
    Ok(result(SamplingDecision::Keep, None))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hash_without_a_trace_id_is_random_in_range() {
        for _ in 0..100 {
            let u = hash01_from_trace_id(None);
            assert!((0.0..1.0).contains(&u));
        }
        assert!(hash01_from_trace_id(Some(&[])) >= 0.0);
    }

    #[test]
    fn hash_of_a_trace_id_reads_the_digest_prefix() {
        let digest = Sha256::digest(b"x");
        let expected =
            u32::from_be_bytes([digest[0], digest[1], digest[2], digest[3]]) as f64 / 4294967295.0;
        assert_eq!(hash01_from_trace_id(Some(b"x")), expected);
    }
}
