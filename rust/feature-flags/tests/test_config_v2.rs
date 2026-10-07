use std::sync::Arc;

use feature_flags::flags::config_v2::{
    Config, Outcome, ParseError, RolloutMiss, MAX_CONFIG_BYTES, MAX_OBJECT_DEPTH, MAX_VARIANTS,
};
use feature_flags::flags::feature_flag_list::PreparedFlags;
use feature_flags::flags::flag_models::{
    EvaluationMetadata, FeatureFlag, FeatureFlagRow, HypercacheFlagsWrapper,
    PreparedFlagDefinitions,
};
use feature_flags::properties::property_models::OperatorType;
use serde_json::{json, Value};

#[path = "test_config_v2/fixtures.rs"]
mod fixtures;

fn config() -> Value {
    json!({
        "version": 2, "return_type": "boolean", "default_value": false,
        "rules": [{
            "id": "11111111-1111-4111-8111-111111111111", "rule_type": "percentage_rollout",
            "targeting": {"properties": []}, "value": true, "rollout_percentage": 33.33,
            "on_rollout_miss": "continue", "assignment_algorithm": "sha1_60_v1", "seed": "example-seed"
        }]
    })
}

fn read(filters: Value) -> FeatureFlag {
    serde_json::from_value(json!({
        "id": 1, "team_id": 1, "key": "example", "active": true, "version": 42, "filters": filters
    }))
    .unwrap()
}

fn read_raw(document: &str) -> FeatureFlag {
    serde_json::from_str(&format!(
        r#"{{"id":1,"team_id":1,"key":"example","active":true,"filters":{document}}}"#
    ))
    .unwrap()
}

fn result(flag: &FeatureFlag) -> &Result<Config, ParseError> {
    flag.filters
        .non_v1
        .as_deref()
        .and_then(|config| config.parsed_v2.as_ref())
        .expect("recognized v2 must retain its parse result")
}

#[test]
fn original_numeric_tokens_control_precision_and_survive_cache_round_trips() {
    for hundredths in 0..=10_000 {
        for number in [
            format!("{}.{:02}", hundredths / 100, hundredths % 100),
            format!("{hundredths}e-2"),
            if hundredths == 0 {
                "0e-27".to_owned()
            } else {
                format!("{hundredths}0000000000000000000000000e-27")
            },
        ] {
            let document = config().to_string().replace("33.33", &number);
            let flag = read_raw(&document);
            let parsed = result(&flag)
                .as_ref()
                .unwrap_or_else(|error| panic!("{number}: {error:?}"));
            match parsed.rules[0].outcome {
                Outcome::PercentageRollout {
                    rollout_percentage, ..
                } => assert_eq!(
                    rollout_percentage,
                    number.parse::<f64>().unwrap(),
                    "{number}"
                ),
                _ => unreachable!(),
            }
        }
    }
    for (number, accepted) in [
        ("33.33", true),
        ("3333e-2", true),
        ("0.0001e2", true),
        ("33.330000000000000000000000000000000000000", true),
        ("33.330000000000000001", false),
        ("100.000000000000000001", false),
        ("1e-400", false),
        ("1e400", false),
    ] {
        let document = config().to_string().replace("33.33", number);
        let flag = read_raw(&document);
        assert_eq!(result(&flag).is_ok(), accepted, "{number}");
        let round_trip = serde_json::to_string(&flag).unwrap();
        assert!(round_trip.contains(number), "{number}");
        let decoded: FeatureFlag = serde_json::from_str(&round_trip).unwrap();
        assert_eq!(result(&decoded).is_ok(), accepted, "{number}");
    }
}

#[test]
fn version_discriminator_rounds_to_binary64() {
    for digits in 15..=80 {
        for number in [
            format!("0.{}", "9".repeat(digits)),
            format!("1.{}1", "0".repeat(digits)),
            format!("1.{}", "9".repeat(digits)),
            format!("2.{}1", "0".repeat(digits)),
        ] {
            let document = config()
                .to_string()
                .replace("\"version\":2", &format!("\"version\":{number}"));
            let flag = read_raw(&document);
            let expected = number.parse::<f64>().unwrap();
            assert_eq!(flag.filters.non_v1.is_none(), expected == 1.0, "{number}");
            if let Some(non_v1) = &flag.filters.non_v1 {
                assert_eq!(non_v1.parsed_v2.is_some(), expected == 2.0, "{number}");
            }
        }
    }
    for (number, recognized_v2) in [
        ("2.0", true),
        ("20e-1", true),
        ("2.0000000000000001", true),
        ("1.0000000000000001", false),
    ] {
        let document = config()
            .to_string()
            .replace("\"version\":2", &format!("\"version\":{number}"));
        let flag = read_raw(&document);
        assert_eq!(flag.filters.non_v1.is_some(), recognized_v2, "{number}");
        if recognized_v2 {
            assert!(result(&flag).is_ok());
            assert!(serde_json::to_string(&flag).unwrap().contains(number));
        }
    }
}

#[test]
fn raw_v2_constraints_reject_duplicates_and_underflow_only_in_the_affected_flag() {
    for (raw, field) in [
        (r#"{"version":2,"version":2,"return_type":"boolean","default_value":null,"rules":[]}"#.to_owned(), "json_keys_unique"),
        (config().to_string().replace("\"value\":true", "\"value\":false,\"value\":true"), "json_keys_unique"),
        (config().to_string().replace("\"properties\":[]", r#""properties":[{"key":"example","key":"other","type":"person"}]"#), "json_keys_unique"),
        (config().to_string().replace("\"properties\":[]", r#""properties":[{"key":"example","type":"person","value":{"items":[{"x":1,"\u0078":2}]}}]"#), "json_keys_unique"),
        (config().to_string().replace("\"seed\":", r#""metadata":{"nested":{"x":1,"x":2}},"seed":"#), "json_keys_unique"),
    ] {
        let flag = read_raw(&raw);
        assert_eq!(result(&flag).as_ref().unwrap_err(), &ParseError::Malformed(field), "{raw}");
        let encoded = serde_json::to_string(&flag).unwrap();
        assert!(encoded.contains(&raw));
        let wrapper = format!(r#"{{"flags":[{encoded},{{"id":2,"team_id":1,"key":"healthy","filters":{{"groups":[{{"rollout_percentage":100}}]}}}}],"evaluation_metadata":{{"dependency_stages":[[1,2]],"flags_with_missing_deps":[],"transitive_deps":{{}}}}}}"#);
        let wrapper: HypercacheFlagsWrapper = serde_json::from_str(&wrapper).unwrap();
        assert!(result(&wrapper.flags[0]).is_err());
        assert_eq!(wrapper.flags[1].filters.groups.len(), 1);
    }
    for (number, valid) in [
        ("1e-400", false),
        ("-1e-400", false),
        ("1e400", false),
        ("-1e400", false),
        ("5e-324", true),
        ("-5e-324", true),
        ("0e-400", true),
        ("-0.0", true),
    ] {
        for property in [
            format!(r#"{{"key":"example","type":"person","operator":"gt","value":{number}}}"#),
            format!(r#"{{"key":"example","type":"person","value":{{"nested":[{number}]}}}}"#),
        ] {
            let raw = config()
                .to_string()
                .replace("\"properties\":[]", &format!("\"properties\":[{property}]"));
            let flag = read_raw(&raw);
            assert_eq!(result(&flag).is_ok(), valid, "{number}");
            if !valid {
                assert_eq!(
                    result(&flag).as_ref().unwrap_err(),
                    &ParseError::Malformed("number_is_binary64")
                );
            }
        }
    }
    let mut document = config();
    document["rules"][0]["metadata"] = json!({"rollout_percentage": 0.001, "text": "\"duplicate\":1,\"duplicate\":1e-400 \\ braces{}[]", "distinct": [{"same":1},{"same":2}]});
    assert!(result(&read(document)).is_ok());
    let legacy = read_raw(r#"{"groups":[],"extra":{"key":1,"key":2,"tiny":1e-400}}"#);
    assert!(legacy.filters.non_v1.is_none());
    assert_eq!(legacy.filters.extra["extra"]["key"], 2);
    assert_eq!(legacy.filters.extra["extra"]["tiny"].as_f64(), Some(0.0));
}

#[test]
fn supported_values_and_order_survive_the_reader() {
    for default in [json!(true), json!(false), Value::Null] {
        for percentage in [0.0, 0.01, 1.01, 33.33, 99.99, 100.0] {
            for policy in ["continue", "return_default"] {
                let mut document = config();
                document["default_value"] = default.clone();
                document["rules"][0]["rollout_percentage"] = json!(percentage);
                document["rules"][0]["on_rollout_miss"] = json!(policy);
                document["rules"].as_array_mut().unwrap().push(json!({
                    "id": "22222222-2222-4222-8222-222222222222", "rule_type": "targeted_release",
                    "targeting": {"properties": []}, "value": false,
                    "description": "Example display text", "metadata": {"opaque": [null, {"anything": true}]}
                }));
                let flag = read(document.clone());
                let parsed = result(&flag).as_ref().unwrap();
                assert_eq!(
                    parsed.default_value,
                    (!default.is_null()).then(|| default.clone())
                );
                assert_eq!(parsed.rules.len(), 2);
                assert_eq!(parsed.rules[0].id.to_string(), document["rules"][0]["id"]);
                match &parsed.rules[0].outcome {
                    Outcome::PercentageRollout {
                        value,
                        rollout_percentage,
                        on_rollout_miss,
                        seed,
                    } => {
                        assert_eq!(*value, json!(true));
                        assert_eq!(*rollout_percentage, percentage);
                        assert_eq!(
                            *on_rollout_miss,
                            if policy == "continue" {
                                RolloutMiss::Continue
                            } else {
                                RolloutMiss::ReturnDefault
                            }
                        );
                        assert_eq!(seed, "example-seed");
                    }
                    other => panic!("unexpected outcome {other:?}"),
                }
                assert!(matches!(
                    parsed.rules[1].outcome,
                    Outcome::TargetedRelease {
                        value: Value::Bool(false)
                    }
                ));
                assert_eq!(serde_json::to_value(&flag).unwrap()["filters"], document);
            }
        }
        let flag = read(
            json!({"version": 2.0, "return_type": "boolean", "default_value": default, "rules": []}),
        );
        assert!(result(&flag).as_ref().unwrap().rules.is_empty());
        assert_eq!(flag.version, Some(42));
    }
}

#[test]
fn required_and_closed_fields_fail_without_losing_the_original_document() {
    for pointer in [
        "/return_type",
        "/default_value",
        "/rules",
        "/rules/0/id",
        "/rules/0/rule_type",
        "/rules/0/targeting",
        "/rules/0/targeting/properties",
        "/rules/0/value",
        "/rules/0/rollout_percentage",
        "/rules/0/on_rollout_miss",
        "/rules/0/assignment_algorithm",
        "/rules/0/seed",
    ] {
        let mut document = config();
        let (parent, key) = pointer.rsplit_once('/').unwrap();
        document
            .pointer_mut(parent)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .remove(key);
        let flag = read(document.clone());
        assert!(
            matches!(result(&flag), Err(ParseError::Malformed(_))),
            "{pointer}"
        );
        assert!(serde_json::to_string(&flag)
            .unwrap()
            .contains(&format!("\"filters\":{document}")));
    }
    for (pointer, value) in [
        ("/groups", json!(false)),
        ("/multivariate", json!("bad-v1")),
        ("/unknown", json!(true)),
        ("/rules/0/unknown", json!(true)),
        ("/rules/0/targeting/unknown", json!(true)),
        ("/default_value", json!(0)),
        ("/default_value", json!("false")),
        ("/rules", Value::Null),
        ("/rules", json!({})),
        ("/rules/0", Value::Null),
        ("/rules/0/targeting", json!([])),
        ("/rules/0/targeting/properties", Value::Null),
        ("/rules/0/value", Value::Null),
        ("/rules/0/value", json!(1)),
        ("/rules/0/id", json!("11111111111141118111111111111111")),
        (
            "/rules/0/id",
            json!("urn:uuid:11111111-1111-4111-8111-111111111111"),
        ),
        ("/rules/0/id", json!("zzzzzzzz-1111-4111-8111-111111111111")),
        ("/rules/0/seed", json!("")),
        ("/rules/0/seed", json!("é".repeat(401))),
        ("/rules/0/seed", Value::Null),
        ("/rules/0/description", Value::Null),
        ("/rules/0/metadata", json!([])),
        ("/rules/0/assign_by", json!("device_id")),
        ("/rules/0/assign_by", Value::Null),
        ("/rules/0/assignment_algorithm", json!("future")),
        ("/rules/0/on_rollout_miss", json!("ignore")),
        ("/rules/0/on_rollout_miss", Value::Null),
        ("/rules/0/rule_type", json!("variant_rollout")),
        ("/aggregation_group_type_index", Value::Null),
        ("/rules/0/rollout_percentage", json!(-0.01)),
        ("/rules/0/rollout_percentage", json!(100.01)),
        ("/rules/0/rollout_percentage", json!(33.333)),
        ("/rules/0/rollout_percentage", json!(33.33000000000001)),
        ("/rules/0/rollout_percentage", json!(1e-30)),
        ("/rules/0/rollout_percentage", json!(true)),
        ("/rules/0/rollout_percentage", json!("33.33")),
    ] {
        let mut document = config();
        let (parent, key) = pointer.rsplit_once('/').unwrap();
        if let Some(map) = document.pointer_mut(parent).unwrap().as_object_mut() {
            map.insert(key.to_owned(), value);
        } else {
            *document.pointer_mut(pointer).unwrap() = value;
        }
        let flag = read(document.clone());
        assert!(
            matches!(result(&flag), Err(ParseError::Malformed(_))),
            "{pointer}"
        );
        assert!(serde_json::to_string(&flag)
            .unwrap()
            .contains(&format!("\"filters\":{document}")));
    }
}

#[test]
fn semantic_limits_and_duplicate_ids_are_enforced() {
    let mut document = config();
    document["rules"][0]["seed"] = json!("é".repeat(400));
    assert!(result(&read(document.clone())).is_ok());
    let repeated = document["rules"][0].clone();
    document["rules"].as_array_mut().unwrap().push(repeated);
    assert_eq!(
        result(&read(document.clone())).as_ref().unwrap_err(),
        &ParseError::Malformed("rule.id")
    );
    let mut document = config();
    document["rules"] = Value::Array(
        (0..100)
            .map(|n| {
                let mut rule = config()["rules"][0].clone();
                rule["id"] = json!(format!("{n:08x}-1111-4111-8111-111111111111"));
                rule
            })
            .collect(),
    );
    assert!(result(&read(document.clone())).is_ok());
    let rule = document["rules"][0].clone();
    document["rules"].as_array_mut().unwrap().push(rule);
    assert_eq!(
        result(&read(document)).as_ref().unwrap_err(),
        &ParseError::LimitExceeded("rules")
    );
    let mut document = config();
    document["rules"][0]["targeting"]["properties"] = Value::Array(
        (0..100)
            .map(|n| json!({"key": format!("tier-{n}"), "type": "person"}))
            .collect(),
    );
    let flag = read(document.clone());
    let predicates = &result(&flag).as_ref().unwrap().rules[0].targeting;
    assert_eq!(predicates.len(), 100);
    for (n, predicate) in predicates.iter().enumerate() {
        assert_eq!(predicate.key, format!("tier-{n}"));
    }
    document["rules"][0]["targeting"]["properties"]
        .as_array_mut()
        .unwrap()
        .push(json!({"key": "tier", "type": "person"}));
    assert_eq!(
        result(&read(document)).as_ref().unwrap_err(),
        &ParseError::LimitExceeded("properties")
    );
    let mut document = config();
    document["rules"][0]["metadata"] = json!({"display": "x".repeat(*MAX_CONFIG_BYTES)});
    let flag = read(document.clone());
    assert_eq!(
        result(&flag).as_ref().unwrap_err(),
        &ParseError::LimitExceeded("filters")
    );
    assert_eq!(serde_json::to_value(flag).unwrap()["filters"], document);

    let mut document = config();
    document["rules"][0]["metadata"] = json!({"display": ""});
    let padding = *MAX_CONFIG_BYTES - document.to_string().len();
    document["rules"][0]["metadata"]["display"] = json!("x".repeat(padding));
    let raw = serde_json::to_string_pretty(&document).unwrap();
    let encoded = format!(r#"{{"id":1,"team_id":1,"key":"example","filters":{raw}}}"#);
    let flag: FeatureFlag = serde_json::from_str(&encoded).unwrap();
    assert!(result(&flag).is_ok());
    document["rules"][0]["metadata"]["display"] = json!("x".repeat(padding + 1));
    assert_eq!(
        result(&read(document)).as_ref().unwrap_err(),
        &ParseError::LimitExceeded("filters")
    );

    // Arrays count toward the object depth, and numbers inside them keep the safe range.
    let mut deepest = json!("leaf");
    for _ in 1..MAX_OBJECT_DEPTH {
        deepest = json!([deepest]);
    }
    for (value, accepted) in [
        (json!({"list": deepest.clone()}), true),
        (json!({"list": [deepest]}), false),
        (json!({"limits": [9_007_199_254_740_991_u64]}), true),
        (json!({"limits": [9_007_199_254_740_992_u64]}), false),
        (json!({"limits": [-9_007_199_254_740_992_i64]}), false),
    ] {
        let mut document = config();
        document["return_type"] = json!("object");
        document["default_value"] = Value::Null;
        document["rules"][0]["value"] = value;
        let flag = read(document);
        if accepted {
            assert!(result(&flag).is_ok());
        } else {
            assert_eq!(
                result(&flag).as_ref().unwrap_err(),
                &ParseError::Malformed("value")
            );
        }
    }
}

fn person_property_cases() -> Vec<(&'static str, Value)> {
    vec![
        ("exact", json!(["preview"])),
        ("is_not", json!(false)),
        ("is_set", Value::Null),
        ("is_not_set", Value::Null),
        ("regex", json!("^preview$")),
        ("not_regex", json!("[")),
        ("icontains", json!("view")),
        ("not_icontains", json!("view")),
        ("starts_with", json!("pre")),
        ("not_starts_with", json!("pre")),
        ("ends_with", json!("view")),
        ("not_ends_with", json!("view")),
        ("icontains_multi", json!(["a", "b"])),
        ("not_icontains_multi", json!([])),
        ("gt", json!(2)),
        ("gte", json!("2")),
        ("lt", json!(3.5)),
        ("lte", json!("3.5")),
        ("is_date_exact", json!("2024-01-01")),
        ("is_date_after", json!("-7d")),
        ("is_date_before", json!("2024-01-01T00:00:00Z")),
        ("semver_gt", json!("1.2.3")),
        ("semver_eq", json!(" 1.2.3 ")),
        ("semver_gte", json!("1.2.3")),
        ("semver_lt", json!("1.2.3")),
        ("semver_lte", json!("1.2.3")),
        ("semver_eq", json!("1.2.3")),
        ("semver_neq", json!("1.2.3")),
        ("semver_tilde", json!("1.2")),
        ("semver_caret", json!("1.2.3")),
        ("semver_wildcard", json!("1.2.*")),
        ("semver_eq", json!("01.2.3-rc.1")),
        ("semver_eq", json!("1.2.3-alpha+build.01")),
        ("semver_eq", json!("18446744073709551615.0.0")),
    ]
}

#[test]
fn person_properties_are_closed_before_reusing_operator_types() {
    for (operator, value) in person_property_cases() {
        let mut document = config();
        document["rules"][0]["targeting"]["properties"] = json!([{
            "key": "example", "type": "person", "operator": operator, "value": value,
            "negation": true, "group_type_index": null, "label": "Display", "cohort_name": null,
            "group_key_names": {"0": "Display only"}
        }]);
        let flag = read(document);
        let parsed = result(&flag)
            .as_ref()
            .unwrap_or_else(|error| panic!("{operator}: {error:?}"));
        let property = &parsed.rules[0].targeting[0];
        assert_eq!(property.key, "example");
        assert_eq!(serde_json::to_value(property.operator).unwrap(), operator);
        assert!(property.negation);
        assert_eq!(
            property.value,
            if value.is_null() { None } else { Some(value) }
        );
    }
    for property in [
        json!({"key": "tier", "type": "person"}),
        json!({"key": "tier", "type": "person", "operator": null, "value": null, "negation": null}),
    ] {
        let mut document = config();
        document["rules"][0]["targeting"]["properties"] = json!([property]);
        let flag = read(document);
        let predicate = &result(&flag).as_ref().unwrap().rules[0].targeting[0];
        assert_eq!(predicate.operator, OperatorType::Exact);
        assert!(!predicate.negation);
    }
    for (field, value) in [
        ("key", json!(42)),
        ("key", json!("")),
        ("type", json!("person_metadata")),
        ("operator", json!("min")),
        ("operator", json!("max")),
        ("operator", json!("between")),
        ("operator", json!("in")),
        ("operator", json!("not_in")),
        ("operator", json!("flag_evaluates_to")),
        ("operator", json!("unknown")),
        ("operator", json!(true)),
        ("negation", json!("false")),
        ("group_type_index", json!(0)),
        ("label", json!(false)),
        ("cohort_name", json!([])),
        ("group_key_names", json!({"0": false})),
        ("extra", json!(true)),
    ] {
        let mut document = config();
        let mut property = json!({"key": "tier", "type": "person", "value": "preview"});
        property[field] = value;
        document["rules"][0]["targeting"]["properties"] = json!([property]);
        assert!(
            matches!(result(&read(document)), Err(ParseError::Malformed(_))),
            "{field}"
        );
    }
    for (operator, value) in [
        ("regex", json!(1)),
        ("icontains_multi", json!("x")),
        ("gt", json!(false)),
        ("is_date_exact", json!("not-a-date")),
        ("is_date_exact", json!("-10000d")),
        ("semver_gt", json!("not-a-version")),
        ("semver_gt", json!(123)),
        ("semver_eq", json!("1.2.3+meta")),
        ("semver_eq", json!("v1.2.3")),
        ("semver_eq", json!("+1.2.3")),
        ("semver_eq", json!("1. 2.3")),
        ("semver_eq", json!("1.+2.3")),
        ("semver_eq", json!("1.2.3.4")),
        ("semver_tilde", json!("1.2.3.4")),
        ("semver_wildcard", json!("1.2.3.4.*")),
        ("semver_eq", json!("1.2.3-")),
        ("semver_eq", json!("1.2.3-01")),
        ("semver_eq", json!("1.2.3-a_b")),
        ("semver_eq", json!("1_0.2.3")),
        ("semver_eq", json!("18446744073709551616.0.0")),
    ] {
        let mut document = config();
        document["rules"][0]["targeting"]["properties"] =
            json!([{"key": "example", "type": "person", "operator": operator, "value": value}]);
        assert_eq!(
            result(&read(document)).as_ref().unwrap_err(),
            &ParseError::Malformed("property.value")
        );
    }
}

#[test]
fn unsupported_members_reject_the_whole_flag_and_debug_redacts_config() {
    for property_type in ["cohort", "group", "flag"] {
        let mut document = config();
        document["rules"][0]["targeting"]["properties"] = json!([
            {"key": "tier", "type": "person", "value": "preview"},
            {"key": "id", "type": property_type, "value": "private-property-value"}
        ]);
        assert_eq!(
            result(&read(document)).as_ref().unwrap_err(),
            &ParseError::Unsupported("property.type")
        );
    }
    let mut document = config();
    document["aggregation_group_type_index"] = json!(0);
    assert_eq!(
        result(&read(document)).as_ref().unwrap_err(),
        &ParseError::Unsupported("aggregation_group_type_index")
    );
    let mut document = config();
    document["rules"]
        .as_array_mut()
        .unwrap()
        .push(json!({"rule_type": "experiment", "experiment_id": 42, "holdout": {"seed": "private-holdout"}}));
    assert_eq!(
        result(&read(document)).as_ref().unwrap_err(),
        &ParseError::Unsupported("experiment_id")
    );
    for version in [json!(2), json!(3), json!("private-version")] {
        let mut document = config();
        document["version"] = version;
        document["rules"][0]["seed"] = json!("private-seed");
        document["rules"][0]["metadata"] = json!({"private-metadata": "private-metadata-value"});
        document["rules"][0]["targeting"]["properties"] =
            json!([{"key": "private-key", "type": "person", "value": "private-property-value"}]);
        let row = FeatureFlagRow {
            id: 1,
            team_id: 2,
            key: "example".to_owned(),
            active: true,
            version: Some(42),
            filters: document.clone(),
            ..Default::default()
        };
        let debug = format!("{row:?}");
        assert!(debug.contains("key: \"example\""));
        assert!(debug.contains("active: true"));
        assert!(debug.contains("version: Some(42)"));
        assert!(!debug.contains("private-"), "{debug}");
        let flag = read(document);
        let debug = format!("{flag:?}");
        assert!(!debug.contains("private-"), "{debug}");
        if let Some(Ok(parsed)) = flag
            .filters
            .non_v1
            .as_deref()
            .and_then(|config| config.parsed_v2.as_ref())
        {
            assert!(!format!("{:?}", parsed.rules).contains("private-"));
            assert!(!format!("{:?}", parsed.rules[0].targeting).contains("private-"));
        }
    }
}

#[test]
fn preparation_reuses_parsing_and_accounts_for_raw_and_typed_data() {
    let mut document = config();
    document["rules"][0]["metadata"] = json!({"display": "x".repeat(8192)});
    document["rules"][0]["targeting"]["properties"] =
        json!([{"key": "tier", "type": "person", "value": "preview"}]);
    let flag = read(document.clone());
    let parsed = Arc::clone(flag.filters.non_v1.as_ref().unwrap());
    let mut raw_only = flag.clone();
    Arc::make_mut(raw_only.filters.non_v1.as_mut().unwrap()).parsed_v2 = None;
    let prepared = |flag| PreparedFlagDefinitions {
        flags: PreparedFlags::seal(vec![flag]),
        evaluation_metadata: Arc::new(EvaluationMetadata::default()),
        cohorts: None,
    };
    let parsed_flags = prepared(flag);
    let raw_flags = prepared(raw_only);
    assert!(parsed_flags.estimated_size_bytes() > raw_flags.estimated_size_bytes());
    assert!(raw_flags.estimated_size_bytes() > 8192);
    assert!(Arc::ptr_eq(
        &parsed,
        parsed_flags.flags[0].filters.non_v1.as_ref().unwrap()
    ));
    assert!(parsed_flags.flags[0].filters.groups.is_empty());
    assert_eq!(
        serde_json::to_value(&parsed_flags.flags[0]).unwrap()["filters"],
        document
    );
    let wrapper: HypercacheFlagsWrapper = serde_json::from_value(json!({
        "flags": [serde_json::to_value(&parsed_flags.flags[0]).unwrap(), {
            "id": 2, "team_id": 1, "key": "healthy", "active": true,
            "filters": {"groups": [{"rollout_percentage": 100}]}
        }], "evaluation_metadata": {"dependency_stages": [[1, 2]], "flags_with_missing_deps": [], "transitive_deps": {"1": [], "2": []}}
    })).unwrap();
    assert!(result(&wrapper.flags[0]).is_ok());
    assert!(wrapper.flags[1].filters.non_v1.is_none());
    assert_eq!(wrapper.flags[1].filters.groups.len(), 1);

    let values = vec![json!({"items": vec![Value::Null; 1000]}); 50];
    let mut document = config();
    document["rules"][0]["targeting"]["properties"] =
        json!([{"key": "example", "type": "person", "value": values}]);
    let flag = read(document.clone());
    assert!(result(&flag).is_ok());
    let weighted = prepared(flag).estimated_size_bytes();
    assert!(weighted > document.to_string().len() + 50_000 * std::mem::size_of::<Value>());

    // The parsed default and each rule value count, not only their raw text.
    let object = json!({"items": vec![Value::Null; 1000]});
    let mut document = config();
    document["return_type"] = json!("object");
    document["default_value"] = object.clone();
    document["rules"][0]["value"] = object;
    let flag = read(document.clone());
    assert!(result(&flag).is_ok());
    let weighted = prepared(flag).estimated_size_bytes();
    assert!(weighted > document.to_string().len() + 2000 * std::mem::size_of::<Value>());
}

fn experiment() -> Value {
    json!({
        "version": 2, "return_type": "string", "default_value": "standard",
        "rules": [{
            "id": "11111111-1111-4111-8111-111111111111", "rule_type": "experiment",
            "targeting": {"properties": []}, "experiment_id": null, "paused": false,
            "rollout_percentage": 80.5, "on_rollout_miss": "return_default",
            "assignment_algorithm": "sha1_60_v1", "seed": "example-seed", "assign_by": "person",
            "variants": [
                {"key": "control", "weight": 33.33, "value": "standard"},
                {"key": "test", "weight": 33.33, "value": "compact"},
                {"key": "test-copy", "weight": 33.34, "value": "compact"}
            ],
            "holdout": {"id": null, "seed": "example-holdout", "exclusion_percentage": 10.25}
        }]
    })
}

#[test]
fn experiment_rules_without_an_experiment_parse_into_a_weighted_split() {
    let document = experiment();
    let flag = read(document.clone());
    let parsed = result(&flag).as_ref().unwrap();
    let Outcome::Experiment {
        paused,
        rollout_percentage,
        on_rollout_miss,
        seed,
        variants,
        holdout,
    } = &parsed.rules[0].outcome
    else {
        panic!("unexpected outcome {:?}", parsed.rules[0].outcome);
    };
    assert!(!paused);
    assert_eq!(*rollout_percentage, 80.5);
    assert_eq!(*on_rollout_miss, RolloutMiss::ReturnDefault);
    assert_eq!(seed, "example-seed");
    let summary: Vec<_> = variants
        .iter()
        .map(|v| (v.key.as_str(), v.weight, v.value.clone()))
        .collect();
    assert_eq!(
        summary,
        [
            ("control", 33.33, json!("standard")),
            ("test", 33.33, json!("compact")),
            ("test-copy", 33.34, json!("compact"))
        ]
    );
    let holdout = holdout.as_ref().unwrap();
    assert_eq!(
        (holdout.seed.as_str(), holdout.exclusion_percentage),
        ("example-holdout", 10.25)
    );
    assert_eq!(serde_json::to_value(&flag).unwrap()["filters"], document);
    let debug = format!("{:?}", parsed.rules);
    assert!(
        !debug.contains("example-") && !debug.contains("compact"),
        "{debug}"
    );

    let mut without_holdout = experiment();
    let rule = without_holdout["rules"][0].as_object_mut().unwrap();
    rule.remove("holdout");
    rule.remove("assign_by");
    assert!(result(&read(without_holdout)).is_ok());

    // `weight` and percentages inside values and metadata are not contract percentages.
    let mut nested = experiment();
    nested["return_type"] = json!("object");
    nested["default_value"] = json!({"weight": 0.125});
    for (index, variant) in nested["rules"][0]["variants"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .enumerate()
    {
        variant["value"] = json!({"weight": 0.001, "rank": index});
    }
    nested["rules"][0]["metadata"] = json!({"exclusion_percentage": 0.001});
    assert!(result(&read(nested)).is_ok());
}

#[test]
fn experiment_rule_contract_violations_reject_the_whole_flag() {
    let cases: Vec<(&str, Value, ParseError)> = vec![
        (
            "/rules/0/experiment_id",
            json!(42),
            ParseError::Unsupported("experiment_id"),
        ),
        (
            "/rules/0/experiment_id",
            json!(42.0),
            ParseError::Unsupported("experiment_id"),
        ),
        (
            "/rules/0/experiment_id",
            json!(4.5),
            ParseError::Malformed("experiment_id"),
        ),
        (
            "/rules/0/experiment_id",
            json!("42"),
            ParseError::Malformed("experiment_id"),
        ),
        (
            "/rules/0/paused",
            json!("false"),
            ParseError::Malformed("paused"),
        ),
        (
            "/rules/0/holdout/id",
            json!(7),
            ParseError::Malformed("holdout.id"),
        ),
        (
            "/rules/0/holdout/seed",
            json!(""),
            ParseError::Malformed("seed"),
        ),
        (
            "/rules/0/holdout/exclusion_percentage",
            json!(100.5),
            ParseError::Malformed("exclusion_percentage"),
        ),
        (
            "/rules/0/holdout/exclusion_percentage",
            json!(5.555),
            ParseError::Malformed("exclusion_percentage"),
        ),
        (
            "/rules/0/variants/1/key",
            json!("control"),
            ParseError::Malformed("variant.key"),
        ),
        (
            "/rules/0/variants/1/key",
            json!("test.v2"),
            ParseError::Malformed("variant.key"),
        ),
        (
            "/rules/0/variants/1/key",
            json!(""),
            ParseError::Malformed("variant.key"),
        ),
        (
            "/rules/0/variants/1/weight",
            json!(33.32),
            ParseError::Malformed("variants"),
        ),
        (
            "/rules/0/variants/1/weight",
            json!(33.34),
            ParseError::Malformed("variants"),
        ),
        (
            "/rules/0/variants/1/weight",
            json!(33.333),
            ParseError::Malformed("weight"),
        ),
        (
            "/rules/0/variants/1/weight",
            json!(-1),
            ParseError::Malformed("weight"),
        ),
        (
            "/rules/0/variants/1/value",
            json!(true),
            ParseError::Malformed("value"),
        ),
        (
            "/rules/0/variants/1/value",
            Value::Null,
            ParseError::Malformed("value"),
        ),
        (
            "/rules/0/variants/1/value",
            json!(""),
            ParseError::Malformed("value"),
        ),
        (
            "/rules/0/variants/1/label",
            json!("x"),
            ParseError::Malformed("variant"),
        ),
        (
            "/rules/0/holdout/name",
            json!("x"),
            ParseError::Malformed("holdout"),
        ),
        (
            "/rules/0/value",
            json!("compact"),
            ParseError::Malformed("rule"),
        ),
        (
            "/rules/0/variants",
            json!([{"key": "control", "weight": 100, "value": "standard"}]),
            ParseError::Malformed("variants"),
        ),
    ];
    for (pointer, value, expected) in cases {
        let mut document = experiment();
        let (parent, key) = pointer.rsplit_once('/').unwrap();
        document
            .pointer_mut(parent)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .insert(key.to_owned(), value.clone());
        let flag = read(document.clone());
        assert_eq!(
            result(&flag).as_ref().unwrap_err(),
            &expected,
            "{pointer} = {value}"
        );
        assert_eq!(serde_json::to_value(&flag).unwrap()["filters"], document);
    }
    for (pointer, expected) in [
        (
            "/rules/0/experiment_id",
            ParseError::Malformed("experiment_id"),
        ),
        ("/rules/0/paused", ParseError::Malformed("paused")),
        ("/rules/0/variants", ParseError::Malformed("variants")),
        ("/rules/0/holdout/id", ParseError::Malformed("id")),
    ] {
        let mut document = experiment();
        let (parent, key) = pointer.rsplit_once('/').unwrap();
        document
            .pointer_mut(parent)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .remove(key);
        assert_eq!(
            result(&read(document)).as_ref().unwrap_err(),
            &expected,
            "{pointer}"
        );
    }
    let mut document = experiment();
    document["rules"][0]["variants"] = json!((0..=MAX_VARIANTS)
        .map(|i| json!({"key": format!("arm_{i}"), "weight": 5, "value": "standard"}))
        .collect::<Vec<_>>());
    assert_eq!(
        result(&read(document)).as_ref().unwrap_err(),
        &ParseError::LimitExceeded("variants")
    );
    // Hundredths are summed exactly, so binary64 accumulation cannot round 99.99 up to 100.
    let mut document = experiment();
    document["rules"][0]["variants"] = json!([
        {"key": "a", "weight": 33.33, "value": "standard"},
        {"key": "b", "weight": 33.33, "value": "standard"},
        {"key": "c", "weight": 33.33, "value": "standard"}
    ]);
    assert_eq!(
        result(&read(document)).as_ref().unwrap_err(),
        &ParseError::Malformed("variants")
    );
}
