//! Validates a `/flags?v=3` response the way the harness does.

use std::sync::LazyLock;

use jsonschema::{Retrieve, Uri, Validator};
use serde_json::Value;

use crate::corpus;

const PRODUCER_ID: &str =
    "https://posthog.com/contracts/feature_flag_rules_v2/flags_response_v3.schema.json";

struct Vendored;

impl Retrieve for Vendored {
    fn retrieve(
        &self,
        uri: &Uri<String>,
    ) -> Result<Value, Box<dyn std::error::Error + Send + Sync>> {
        if uri.as_str() == PRODUCER_ID {
            Ok(corpus::load("schemas/flags_response_v3.schema.json"))
        } else {
            Err(format!("unexpected $ref {uri}").into())
        }
    }
}

fn validator(path: &str) -> Validator {
    jsonschema::options()
        .with_retriever(Vendored)
        .should_validate_formats(true)
        .build(&corpus::load(path))
        .unwrap()
}

static PRODUCER: LazyLock<Validator> =
    LazyLock::new(|| validator("schemas/flags_response_v3.schema.json"));
static PRESENCE: LazyLock<Validator> =
    LazyLock::new(|| validator("schemas/flags_response_v3_presence.schema.json"));

fn first_error(validator: &Validator, instance: &Value) -> Option<String> {
    validator
        .iter_errors(instance)
        .next()
        .map(|error| format!("{} at {}", error, error.instance_path()))
}

/// The harness's spelling rule: `assignmentSeed`, `holdout-seed` and `$seed` all count.
fn seed_key(key: &str) -> bool {
    let mut normalized = String::new();
    let mut after_lower_or_digit = false;
    for c in key.trim_start_matches('$').chars() {
        if c.is_ascii_uppercase() && after_lower_or_digit {
            normalized.push('_');
        }
        after_lower_or_digit = c.is_ascii_lowercase() || c.is_ascii_digit();
        normalized.push(if c == '-' {
            '_'
        } else {
            c.to_ascii_lowercase()
        });
    }
    normalized == "seed" || normalized.ends_with("_seed")
}

fn first_seed(value: &Value, path: &str) -> Option<String> {
    match value {
        Value::Object(map) => map.iter().find_map(|(key, child)| {
            let child_path = format!("{path}/{key}");
            if path != "/flags" && seed_key(key) {
                return Some(child_path);
            }
            first_seed(child, &child_path)
        }),
        Value::Array(items) => items
            .iter()
            .enumerate()
            .find_map(|(i, child)| first_seed(child, &format!("{path}/{i}"))),
        _ => None,
    }
}

/// `Err((layer, detail))` names the first failing layer.
pub fn validate_v3(response: &Value) -> Result<(), (&'static str, String)> {
    if let Some(error) = first_error(&PRODUCER, response) {
        return Err(("schema", error));
    }
    if let Some(error) = first_error(&PRESENCE, response) {
        return Err(("presence", error));
    }
    for (key, record) in response["flags"].as_object().into_iter().flatten() {
        if record["key"] != *key {
            return Err(("semantic", format!("/flags/{key}/key")));
        }
    }
    if let Some(path) = first_seed(response, "") {
        return Err(("seed", path));
    }
    Ok(())
}

pub fn fixture_case(fixtures: &Value, case: &Value) -> Value {
    let mut instance = fixtures["templates"][case["template"].as_str().unwrap()].clone();
    for pointer in case["remove"].as_array().into_iter().flatten() {
        let (parent, key) = pointer.as_str().unwrap().rsplit_once('/').unwrap();
        instance
            .pointer_mut(parent)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .remove(key);
    }
    for (pointer, value) in case["set"].as_object().into_iter().flatten() {
        let (parent, key) = pointer.rsplit_once('/').unwrap();
        instance
            .pointer_mut(parent)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .insert(key.to_string(), value.clone());
    }
    instance
}

#[test]
fn seed_scan_matches_the_harness_spellings() {
    let response = serde_json::json!({"flags": {"seed": {"key": "seed"}}});
    assert_eq!(first_seed(&response, ""), None);
    for key in [
        "seed",
        "assignmentSeed",
        "holdout-seed",
        "$feature_flag_seed",
    ] {
        let response = serde_json::json!({"flags": {}, key: 1});
        assert_eq!(first_seed(&response, ""), Some(format!("/{key}")), "{key}");
    }
    assert_eq!(first_seed(&serde_json::json!({"seeds": 1}), ""), None);
}
