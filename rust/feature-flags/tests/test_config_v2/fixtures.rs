use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use super::{read, result};
use feature_flags::flags::config_v2::ParseError;
use feature_flags::flags::flag_models::FeatureFlag;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/rules_v2_parser/1.6.0")
}

fn load(path: &str) -> Value {
    serde_json::from_slice(&std::fs::read(root().join(path)).unwrap()).unwrap()
}

#[test]
fn released_parser_artifacts_are_intact() {
    let source = load("SOURCE.json");
    assert_eq!(
        source["source_revision"],
        "c32f4959240967f1ee89e58490fc9d3beaa1401f"
    );
    let index = std::fs::read(root().join("SHA256SUMS")).unwrap();
    assert_eq!(
        hex::encode(Sha256::digest(&index)),
        source["upstream_index_sha256"]
    );
    let text = std::str::from_utf8(&index).unwrap();
    let digests: BTreeMap<_, _> = text
        .lines()
        .map(|line| {
            let (digest, path) = line.split_once("  ").unwrap();
            (path, digest)
        })
        .collect();
    let files: BTreeSet<_> = source["files"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| p.as_str().unwrap())
        .collect();
    assert_eq!(files.len(), source["files"].as_array().unwrap().len());
    for path in files {
        let bytes = std::fs::read(root().join(path)).unwrap();
        assert_eq!(hex::encode(Sha256::digest(bytes)), digests[path], "{path}");
    }
    let manifest = load("manifest.json");
    assert_eq!(manifest["contract"]["version"], "2.1.0");
    assert_eq!(manifest["corpus"]["version"], "1.1.0");
}

#[test]
fn released_config_cases_distinguish_schema_expectations_from_supported_families() {
    let manifest = load("manifest.json");
    let mut totals = [0; 5];
    for fixture in manifest["artifacts"].as_array().unwrap() {
        let path = fixture["path"].as_str().unwrap();
        if !path.starts_with("fixtures/config/") {
            continue;
        }
        let document = load(path);
        let flag = read(document.clone());
        let parsed = flag.filters.non_v1.as_ref().unwrap().parsed_v2.as_ref();
        if fixture["expected"] == "valid" {
            if path.ends_with("version_float_literal.json")
                || path.ends_with("boolean_targeted_and_percentage_rollout.json")
            {
                assert!(parsed.unwrap().is_ok(), "{path}: {parsed:?}");
                assert!(result(&read(document.clone())).is_ok());
                totals[0] += 1;
            } else {
                assert!(
                    matches!(parsed, Some(Err(ParseError::Unsupported(_)))),
                    "{path}: {parsed:?}"
                );
                totals[1] += 1;
            }
        } else {
            let name = PathBuf::from(path)
                .file_stem()
                .unwrap()
                .to_str()
                .unwrap()
                .to_owned();
            let expected = invalid_fixture_error(&name);
            assert_eq!(
                parsed.map(|result| *result.as_ref().unwrap_err()),
                expected,
                "{path}"
            );
            match expected {
                Some(ParseError::Malformed(_)) => {
                    totals[2] += 1;
                    let repaired = repair_supported_fixture(&name, document.clone());
                    assert!(
                        result(&read(repaired)).is_ok(),
                        "repair must make {path} supported"
                    );
                }
                Some(ParseError::Unsupported(_)) => totals[3] += 1,
                None => totals[4] += 1,
                other => panic!("unexpected fixture classification: {other:?}"),
            }
        }
        assert_eq!(
            serde_json::to_value(flag).unwrap()["filters"],
            document,
            "{path}"
        );
    }
    assert_eq!(totals, [2, 6, 18, 11, 3]);
}

fn invalid_fixture_error(name: &str) -> Option<ParseError> {
    use ParseError::{Malformed, Unsupported};
    Some(match name {
        "assign_by_not_person" => Malformed("assign_by"),
        "default_value_type_mismatch" => Malformed("default_value"),
        "empty_seed" | "missing_rollout_seed" => Malformed("seed"),
        "missing_on_rollout_miss" => Malformed("on_rollout_miss"),
        "non_uuid_rule_id" => Malformed("rule.id"),
        "null_rule_value" | "return_value_type_mismatch" => Malformed("value"),
        "rollout_percentage_above_maximum" | "rollout_percentage_below_minimum" => {
            Malformed("rollout_percentage")
        }
        "targeted_release_with_rollout_fields" | "unknown_rule_field" => Malformed("rule"),
        "unknown_assignment_algorithm" => Malformed("assignment_algorithm"),
        "unknown_config_field" => Malformed("filters"),
        "unknown_property_field" => Malformed("property"),
        "unknown_property_operator" => Malformed("property.operator"),
        "unknown_property_type" => Malformed("property.type"),
        "unknown_rollout_miss_policy" => Malformed("on_rollout_miss"),
        "empty_string_value" | "object_value_too_deep" => Unsupported("return_type"),
        "group_experiment_with_assign_by" | "group_percentage_rollout_with_assign_by" => {
            Unsupported("aggregation_group_type_index")
        }
        "missing_experiment_paused"
        | "null_experiment_id"
        | "seed_too_long"
        | "too_few_variants"
        | "too_many_variants"
        | "variant_key_invalid_characters"
        | "variant_value_type_mismatch" => Unsupported("rule_type"),
        "unknown_config_version" | "version_boolean" | "version_string" => return None,
        _ => panic!("unclassified released fixture: {name}"),
    })
}

fn repair_supported_fixture(name: &str, mut document: Value) -> Value {
    match name {
        "assign_by_not_person" => document["rules"][0]["assign_by"] = json!("person"),
        "default_value_type_mismatch" => document["default_value"] = json!(false),
        "empty_seed" | "missing_rollout_seed" => {
            document["rules"][0]["seed"] = json!("example-seed")
        }
        "missing_on_rollout_miss" | "unknown_rollout_miss_policy" => {
            document["rules"][0]["on_rollout_miss"] = json!("continue")
        }
        "non_uuid_rule_id" => {
            document["rules"][0]["id"] = json!("11111111-1111-4111-8111-111111111111")
        }
        "null_rule_value" | "return_value_type_mismatch" => {
            document["rules"][0]["value"] = json!(false)
        }
        "rollout_percentage_above_maximum" | "rollout_percentage_below_minimum" => {
            document["rules"][0]["rollout_percentage"] = json!(33.33)
        }
        "targeted_release_with_rollout_fields" => {
            for field in [
                "assign_by",
                "assignment_algorithm",
                "on_rollout_miss",
                "rollout_percentage",
                "seed",
            ] {
                document["rules"][0].as_object_mut().unwrap().remove(field);
            }
        }
        "unknown_rule_field" => {
            document["rules"][0]
                .as_object_mut()
                .unwrap()
                .remove("implicit_default");
        }
        "unknown_assignment_algorithm" => {
            document["rules"][0]["assignment_algorithm"] = json!("sha1_60_v1")
        }
        "unknown_config_field" => {
            document.as_object_mut().unwrap().remove("groups");
        }
        "unknown_property_field" => document["rules"][0]["targeting"]["properties"][0]
            .as_object_mut()
            .unwrap()
            .retain(|key, _| ["key", "type", "operator", "value"].contains(&key.as_str())),
        "unknown_property_operator" => {
            document["rules"][0]["targeting"]["properties"][0]["operator"] = json!("exact")
        }
        "unknown_property_type" => {
            document["rules"][0]["targeting"]["properties"][0]["type"] = json!("person")
        }
        _ => panic!("no focused repair for {name}"),
    }
    document
}

#[test]
fn definitions_filters_use_the_same_parser_without_replacing_the_service_envelope() {
    let fixtures = load("fixtures/wire/definitions.json");
    let mut exercised = 0;
    for case in fixtures["cases"].as_array().unwrap() {
        let mut entry = fixtures["templates"][case["template"].as_str().unwrap()].clone();
        for path in case["remove"].as_array().into_iter().flatten() {
            let (parent, key) = path.as_str().unwrap().rsplit_once('/').unwrap();
            entry
                .pointer_mut(parent)
                .unwrap()
                .as_object_mut()
                .unwrap()
                .remove(key);
        }
        for (path, value) in case["set"].as_object().into_iter().flatten() {
            let (parent, key) = path.rsplit_once('/').unwrap();
            entry
                .pointer_mut(parent)
                .unwrap()
                .as_object_mut()
                .unwrap()
                .insert(key.to_owned(), value.clone());
        }
        // The service reader gets its team identity from the service cache/PG row;
        // the canonical definitions entry can omit it. This is only a test adapter.
        entry["team_id"] = json!(1);
        let decoded = serde_json::from_value::<FeatureFlag>(entry.clone());
        if case["expected"] == "valid" {
            let flag = decoded.unwrap();
            if case["template"] == "v2" {
                assert!(matches!(
                    result(&flag),
                    Err(ParseError::Unsupported("rule_type"))
                ))
            } else {
                assert!(flag.filters.non_v1.is_none());
            }
            assert_eq!(
                flag.version,
                entry
                    .get("version")
                    .and_then(Value::as_i64)
                    .map(|n| n as i32)
            );
        } else if case["expected_failure"]["instance_path"]
            .as_str()
            .unwrap()
            .starts_with("/filters/")
        {
            let flag = decoded.unwrap();
            assert!(flag
                .filters
                .non_v1
                .as_deref()
                .unwrap()
                .parsed_v2
                .as_ref()
                .is_none_or(Result::is_err));
        }
        exercised += 1;
    }
    assert_eq!(exercised, 23);
    let mut entry = fixtures["templates"]["v2"].clone();
    entry["filters"] = load("fixtures/config/valid/boolean_targeted_and_percentage_rollout.json");
    entry["team_id"] = json!(1);
    let flag: FeatureFlag = serde_json::from_value(entry.clone()).unwrap();
    assert!(result(&flag).is_ok());
    assert_eq!(
        serde_json::to_value(flag).unwrap()["filters"],
        entry["filters"]
    );
}
