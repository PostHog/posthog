use std::sync::Arc;

use feature_flags::flags::config_v2::{Config, Outcome, ParseError, RolloutMiss, MAX_CONFIG_BYTES};
use feature_flags::flags::feature_flag_list::PreparedFlags;
use feature_flags::flags::flag_models::{
    EvaluationMetadata, FeatureFlag, HypercacheFlagsWrapper, PreparedFlagDefinitions,
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
            let encoded = format!(r#"{{"id":1,"team_id":1,"key":"example","filters":{document}}}"#);
            let flag: FeatureFlag = serde_json::from_str(&encoded).unwrap();
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
        let encoded =
            format!(r#"{{"id":1,"team_id":1,"key":"example","active":true,"filters":{document}}}"#);
        let flag: FeatureFlag = serde_json::from_str(&encoded).unwrap();
        assert_eq!(result(&flag).is_ok(), accepted, "{number}");
        let round_trip = serde_json::to_string(&flag).unwrap();
        assert!(round_trip.contains(number), "{number}");
        let decoded: FeatureFlag = serde_json::from_str(&round_trip).unwrap();
        assert_eq!(result(&decoded).is_ok(), accepted, "{number}");
    }
    for (number, recognized_v2) in [
        ("2.0", true),
        ("20e-1", true),
        ("2.0000000000000001", false),
        ("1.0000000000000001", false),
    ] {
        let document = config()
            .to_string()
            .replace("\"version\":2", &format!("\"version\":{number}"));
        let encoded =
            format!(r#"{{"id":1,"team_id":1,"key":"example","active":true,"filters":{document}}}"#);
        let flag: FeatureFlag = serde_json::from_str(&encoded).unwrap();
        assert_eq!(
            flag.filters.non_v1.as_ref().unwrap().parsed_v2.is_some(),
            recognized_v2
        );
        assert!(serde_json::to_string(&flag).unwrap().contains(number));
    }
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
                assert_eq!(parsed.default_value, default.as_bool());
                assert_eq!(parsed.rules.len(), 2);
                assert_eq!(parsed.rules[0].id.to_string(), document["rules"][0]["id"]);
                match &parsed.rules[0].outcome {
                    Outcome::PercentageRollout {
                        value,
                        rollout_percentage,
                        on_rollout_miss,
                        seed,
                    } => {
                        assert!(*value);
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
                    Outcome::TargetedRelease { value: false }
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
    document["rules"][0]["targeting"]["properties"] =
        json!(vec![json!({"key": "tier", "type": "person"}); 100]);
    assert!(result(&read(document.clone())).is_ok());
    document["rules"][0]["targeting"]["properties"]
        .as_array_mut()
        .unwrap()
        .push(json!({"key": "tier", "type": "person"}));
    assert_eq!(
        result(&read(document)).as_ref().unwrap_err(),
        &ParseError::LimitExceeded("properties")
    );
    let mut document = config();
    document["rules"][0]["metadata"] = json!({"display": "x".repeat(MAX_CONFIG_BYTES)});
    let flag = read(document.clone());
    assert_eq!(
        result(&flag).as_ref().unwrap_err(),
        &ParseError::LimitExceeded("filters")
    );
    assert_eq!(serde_json::to_value(flag).unwrap()["filters"], document);

    let mut document = config();
    document["rules"][0]["metadata"] = json!({"display": ""});
    let padding = MAX_CONFIG_BYTES - document.to_string().len();
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
}

#[test]
fn person_properties_are_closed_before_reusing_operator_types() {
    for (operator, value) in [
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
        ("semver_gte", json!("1.2.3")),
        ("semver_lt", json!("1.2.3")),
        ("semver_lte", json!("1.2.3")),
        ("semver_eq", json!("1.2.3")),
        ("semver_neq", json!("1.2.3")),
        ("semver_tilde", json!("1.2")),
        ("semver_caret", json!("1.2.3")),
        ("semver_wildcard", json!("1.2.*")),
    ] {
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
        assert_eq!(serde_json::to_value(property.operator).unwrap(), operator);
        assert!(property.negation);
        assert_eq!(
            property.value,
            if value.is_null() { None } else { Some(value) }
        );
    }
    for property in [
        json!({"key": "tier", "type": "person"}),
        json!({"key": "tier", "type": "person", "operator": null, "value": null}),
    ] {
        let mut document = config();
        document["rules"][0]["targeting"]["properties"] = json!([property]);
        let flag = read(document);
        assert_eq!(
            result(&flag).as_ref().unwrap().rules[0].targeting[0].operator,
            OperatorType::Exact
        );
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
    for (field, value) in [
        ("return_type", json!("string")),
        ("return_type", json!("number")),
        ("return_type", json!("object")),
        ("aggregation_group_type_index", json!(0)),
    ] {
        let mut document = config();
        document[field] = value;
        assert!(matches!(
            result(&read(document)),
            Err(ParseError::Unsupported(_))
        ));
    }
    let mut document = config();
    document["rules"]
        .as_array_mut()
        .unwrap()
        .push(json!({"rule_type": "experiment", "holdout": {"seed": "private-holdout"}}));
    assert_eq!(
        result(&read(document)).as_ref().unwrap_err(),
        &ParseError::Unsupported("rule_type")
    );
    for version in [json!(2), json!(3), json!("private-version")] {
        let mut document = config();
        document["version"] = version;
        document["rules"][0]["seed"] = json!("private-seed");
        document["rules"][0]["metadata"] = json!({"private-metadata": "private-metadata-value"});
        document["rules"][0]["targeting"]["properties"] =
            json!([{"key": "private-key", "type": "person", "value": "private-property-value"}]);
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
}
