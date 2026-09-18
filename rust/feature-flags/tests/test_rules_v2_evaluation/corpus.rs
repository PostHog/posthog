use std::collections::HashMap;
use std::path::PathBuf;

use crate::flags::evaluate_v2::{
    Evaluation, EvaluationContext, EvaluationError, MatchedRule, PersonProperties, RuleKind,
};
use crate::flags::flag_models::FeatureFlag;
use serde_json::{json, Value};

pub fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/rules_v2_evaluation/2.2.0")
}

pub fn load(path: &str) -> Value {
    serde_json::from_slice(&std::fs::read(root().join(path)).unwrap()).unwrap()
}

pub fn cases() -> Vec<Value> {
    load("corpus/v2_boolean_evaluation.json")["cases"]
        .as_array()
        .unwrap()
        .clone()
}

pub fn read(case: &Value) -> FeatureFlag {
    serde_json::from_value(json!({
        "id": 1, "team_id": 1, "key": case["flag"]["key"], "name": case["flag"]["name"],
        "active": case["flag"]["active"], "deleted": case["flag"]["deleted"], "filters": case["config"]
    })).unwrap()
}

pub fn properties(case: &Value) -> HashMap<String, Value> {
    case["context"]["properties"]
        .as_object()
        .map(|object| {
            object
                .iter()
                .map(|(key, value)| (key.clone(), value.clone()))
                .collect()
        })
        .unwrap_or_default()
}

pub fn context<'a>(
    case: &'a Value,
    properties: &'a HashMap<String, Value>,
) -> EvaluationContext<'a> {
    let input = &case["context"];
    EvaluationContext {
        person_identifier: input["identifier"].as_str().unwrap(),
        properties: if input["properties"].is_null() {
            PersonProperties::Unavailable
        } else if input["properties_complete"].as_bool().unwrap() {
            PersonProperties::Complete(properties)
        } else {
            PersonProperties::Partial(properties)
        },
        timezone: input["timezone"].as_str().unwrap().parse().unwrap(),
        use_explicit_exact_matching: input["explicit_exact_matching"].as_bool().unwrap(),
        now: input["now"].as_str().unwrap().parse().unwrap(),
    }
}

fn rule_json(rule: MatchedRule) -> Value {
    json!({"id": rule.id.to_string(), "index": rule.index, "rule_type": match rule.kind {
        RuleKind::TargetedRelease => "targeted_release", RuleKind::PercentageRollout => "percentage_rollout",
    }})
}

pub fn result_json(result: Result<Evaluation, EvaluationError>) -> Value {
    match result {
        Ok(Evaluation::TargetingMatch { value, rule }) => {
            json!({"status":"success","value":value,"reason":"targeting_match","rule":rule_json(rule)})
        }
        Ok(Evaluation::RolloutMiss { value, rule }) => {
            json!({"status":"success","value":value,"reason":"rollout_miss","rule":rule_json(rule)})
        }
        Ok(Evaluation::NoRuleMatch { value }) => {
            json!({"status":"success","value":value,"reason":"no_rule_match"})
        }
        Err(error) => json!({"status":"error","error": match error {
            EvaluationError::MissingContext => "missing_context", EvaluationError::InvalidProperty => "invalid_property",
            EvaluationError::InvalidRegex => "invalid_regex", EvaluationError::Hash => "hash",
        }}),
    }
}
