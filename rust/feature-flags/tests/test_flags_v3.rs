use anyhow::Result;
use serde_json::{json, Value};

use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::utils::test_utils::{
    insert_flags_for_team_in_redis, insert_new_team_in_redis, setup_redis_client, TestContext,
};

use crate::common::*;

pub mod common;
#[path = "test_rules_v2_evaluation/corpus.rs"]
#[allow(dead_code)]
mod corpus;
#[path = "test_rules_v2_evaluation/wire.rs"]
#[allow(dead_code)]
mod wire;

const RULE_A: &str = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const RULE_B: &str = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const INTERNAL_TOKEN: &str = "internal-test-token";
const DECIDE: &[(&str, &str)] = &[("X-Original-Endpoint", "decide")];
const INTERNAL: &[(&str, &str)] = &[("Authorization", "Bearer internal-test-token")];

fn v2(key: &str, id: i32, default_value: Value, rules: Value) -> Value {
    json!({
        "id": id, "team_id": 0, "key": key, "name": key, "active": true, "deleted": false,
        "version": 3, "has_experiment": false,
        "filters": {"version": 2, "return_type": "boolean", "default_value": default_value, "rules": rules},
    })
}

fn targeted(id: &str, value: bool, properties: Value) -> Value {
    json!({"id": id, "rule_type": "targeted_release", "targeting": {"properties": properties}, "value": value})
}

fn rollout(id: &str, percentage: u8, on_rollout_miss: &str) -> Value {
    json!({
        "id": id, "rule_type": "percentage_rollout", "targeting": {"properties": []}, "value": true,
        "rollout_percentage": percentage, "on_rollout_miss": on_rollout_miss,
        "assignment_algorithm": "sha1_60_v1", "seed": "seed-for-tests",
    })
}

fn email(pattern: &str) -> Value {
    json!([{"key": "email", "type": "person", "operator": "icontains", "value": pattern}])
}

/// A team with one person, three v1 flags and six v2 flags covering every boolean outcome.
async fn server() -> Result<(ServerHandle, String)> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.internal_request_token = Some(INTERNAL_TOKEN.to_string());
    let redis = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(redis.clone()).await?;
    let db = TestContext::new(None).await;
    db.insert_new_team(Some(team.id)).await?;
    db.insert_person(
        team.id,
        "ann".to_string(),
        Some(json!({"email": "ann@example.com"})),
    )
    .await?;
    let mut flags = vec![
        json!({
            "id": 1, "team_id": team.id, "key": "v1-on", "name": "v1-on", "active": true,
            "deleted": false, "version": 5, "has_experiment": false,
            "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
        }),
        json!({
            "id": 2, "team_id": team.id, "key": "v1-variant", "name": "v1-variant", "active": true,
            "deleted": false, "version": 6, "has_experiment": false,
            "filters": {
                "groups": [{"properties": [], "rollout_percentage": 100, "variant": "compact"}],
                "multivariate": {"variants": [{"key": "compact", "name": "Compact", "rollout_percentage": 100}]},
                "payloads": {"compact": "{\"columns\":2}"},
            },
        }),
        json!({
            "id": 9, "team_id": team.id, "key": "v1-free-key", "name": "v1-free-key", "active": true,
            "deleted": false, "version": 7, "has_experiment": false,
            "filters": {
                "groups": [{"properties": [], "rollout_percentage": 100, "variant": "provider/model-1.2 beta"}],
                "multivariate": {"variants": [{"key": "provider/model-1.2 beta", "name": "Free key", "rollout_percentage": 100}]},
            },
        }),
        v2(
            "v2-true",
            3,
            json!(false),
            json!([targeted(RULE_A, true, email("@example.com"))]),
        ),
        v2(
            "v2-false",
            4,
            json!(true),
            json!([targeted(RULE_A, false, json!([]))]),
        ),
        v2(
            "v2-null-default",
            5,
            Value::Null,
            json!([targeted(RULE_A, true, email("@nowhere"))]),
        ),
        v2(
            "v2-rollout-return-default",
            6,
            json!(false),
            json!([rollout(RULE_B, 0, "return_default")]),
        ),
        v2(
            "v2-rollout-continue",
            7,
            json!(true),
            json!([rollout(RULE_B, 0, "continue")]),
        ),
        v2(
            "v2-error",
            8,
            json!(false),
            json!([targeted(
                RULE_A,
                true,
                json!([
                    {"key": "email", "type": "person", "operator": "regex", "value": "[", "negation": false}
                ])
            )]),
        ),
    ];
    for flag in &mut flags {
        flag["team_id"] = json!(team.id);
    }
    insert_flags_for_team_in_redis(redis, team.id, Some(json!(flags).to_string())).await?;
    Ok((ServerHandle::for_config(config).await, team.api_token))
}

async fn post(
    server: &ServerHandle,
    query: &str,
    headers: &[(&str, &str)],
    body: Value,
) -> Result<Value> {
    let mut request = reqwest::Client::new()
        .post(format!("http://{}/flags?{query}", server.addr))
        .header("Content-Type", "application/json")
        .body(body.to_string());
    for (name, value) in headers {
        request = request.header(*name, *value);
    }
    let response = request.send().await?;
    assert_eq!(response.status(), 200);
    Ok(response.json().await?)
}

fn keys(value: &Value) -> Vec<&str> {
    let mut keys: Vec<_> = value
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect();
    keys.sort_unstable();
    keys
}

#[tokio::test]
async fn v3_returns_the_typed_record_for_v1_and_v2_flags() -> Result<()> {
    let (server, token) = server().await?;
    let body = json!({"token": token, "distinct_id": "ann"});

    let v3 = post(&server, "v=3&config=false", &[], body.clone()).await?;
    wire::validate_v3(&v3).unwrap_or_else(|error| panic!("{error:?}"));
    assert_eq!(v3["errorsWhileComputingFlags"], true);
    let flags = &v3["flags"];
    assert_eq!(flags.as_object().unwrap().len(), 9);

    let expected = [
        (
            "v1-on",
            json!(true),
            "condition_match",
            json!(0),
            1,
            None,
            None,
        ),
        (
            "v1-variant",
            json!("compact"),
            "condition_match",
            json!(0),
            1,
            None,
            None,
        ),
        (
            "v1-free-key",
            json!("provider/model-1.2 beta"),
            "condition_match",
            json!(0),
            1,
            None,
            None,
        ),
        (
            "v2-true",
            json!(true),
            "targeting_match",
            json!(0),
            2,
            Some("targeted_release"),
            Some(RULE_A),
        ),
        (
            "v2-false",
            json!(false),
            "targeting_match",
            json!(0),
            2,
            Some("targeted_release"),
            Some(RULE_A),
        ),
        (
            "v2-null-default",
            Value::Null,
            "no_rule_match",
            Value::Null,
            2,
            None,
            None,
        ),
        (
            "v2-rollout-return-default",
            json!(false),
            "rollout_miss",
            json!(0),
            2,
            Some("percentage_rollout"),
            Some(RULE_B),
        ),
        (
            "v2-rollout-continue",
            json!(true),
            "no_rule_match",
            Value::Null,
            2,
            None,
            None,
        ),
        ("v2-error", Value::Null, "error", Value::Null, 2, None, None),
    ];
    for (key, value, code, condition_index, config_version, rule_type, rule_id) in expected {
        let record = &flags[key];
        assert_eq!(record["key"], key, "{key}");
        assert_eq!(record["value"], value, "{key}");
        assert_eq!(record["reason"]["code"], code, "{key}");
        assert_eq!(
            record["reason"]["condition_index"], condition_index,
            "{key}"
        );
        assert_eq!(
            record["metadata"]["config_version"], config_version,
            "{key}"
        );
        assert_eq!(
            record["metadata"].get("rule_type"),
            rule_type.map(Value::from).as_ref(),
            "{key}"
        );
        assert_eq!(
            record["metadata"].get("rule_id"),
            rule_id.map(Value::from).as_ref(),
            "{key}"
        );
        assert_eq!(
            record.get("failed"),
            (key == "v2-error").then_some(&json!(true)),
            "{key}"
        );
        assert!(
            record.get("enabled").is_none() && record.get("variant").is_none(),
            "{key}"
        );
        if config_version == 2 {
            assert_eq!(record["metadata"]["payload"], Value::Null, "{key}");
        }
    }
    for (key, description) in [
        ("v2-true", "Matched rule 1"),
        ("v2-rollout-return-default", "Rule 1 rollout miss"),
        ("v2-null-default", "No rule matched"),
    ] {
        assert_eq!(flags[key]["reason"]["description"], description, "{key}");
    }
    assert_eq!(flags["v1-variant"]["metadata"]["variant_key"], "compact");
    assert_eq!(
        flags["v1-free-key"]["metadata"]["variant_key"],
        "provider/model-1.2 beta"
    );
    assert_eq!(
        flags["v1-variant"]["metadata"]["payload"],
        "{\"columns\":2}"
    );
    assert_eq!(flags["v1-on"]["metadata"].get("variant_key"), None);
    assert_eq!(flags["v1-on"]["metadata"]["version"], 5);
    assert_eq!(flags["v2-true"]["metadata"]["version"], 3);

    let v99 = post(&server, "v=99&config=false", &[], body.clone()).await?;
    assert_eq!(v99["flags"], v3["flags"]);

    let subset = post(
        &server,
        "v=3&config=false",
        &[],
        json!({"token": token, "distinct_id": "ann", "flag_keys": ["v2-true", "missing"]}),
    )
    .await?;
    assert_eq!(keys(&subset["flags"]), ["v2-true"]);
    wire::validate_v3(&subset).unwrap();

    let detailed = post(
        &server,
        "v=3&config=false&detailed_analysis=true",
        INTERNAL,
        body,
    )
    .await?;
    wire::validate_v3(&detailed).unwrap();
    assert_eq!(
        detailed["flags"]["v1-on"]["conditions"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert_eq!(detailed["flags"]["v2-true"]["conditions"], json!([]));
    Ok(())
}

#[tokio::test]
async fn v2_legacy_and_decide_shapes_are_unchanged() -> Result<()> {
    let (server, token) = server().await?;
    let body = json!({"token": token, "distinct_id": "ann"});

    let v2 = post(&server, "v=2&config=false", &[], body.clone()).await?;
    for (key, record) in v2["flags"].as_object().unwrap() {
        let mut expected = vec!["enabled", "key", "metadata", "reason", "variant"];
        if key == "v2-error" {
            expected.insert(1, "failed");
        }
        assert_eq!(keys(record), expected, "{key}");
        assert_eq!(
            keys(&record["metadata"]),
            ["description", "has_experiment", "id", "payload", "version"],
            "{key}"
        );
    }
    assert_eq!(v2["flags"]["v2-true"]["enabled"], true);
    assert_eq!(v2["flags"]["v2-true"]["reason"]["code"], "condition_match");
    assert_eq!(v2["flags"]["v2-null-default"]["enabled"], false);
    assert_eq!(v2["flags"]["v1-variant"]["variant"], "compact");

    for query in ["v=1&config=false", "v=abc&config=false"] {
        let legacy = post(&server, query, &[], body.clone()).await?;
        assert_eq!(legacy.get("flags"), None, "{query}");
        assert_eq!(legacy["featureFlags"]["v2-true"], true, "{query}");
        assert_eq!(legacy["featureFlags"]["v1-variant"], "compact", "{query}");
    }

    let decide_v3 = post(&server, "v=3&config=false", DECIDE, body.clone()).await?;
    assert_eq!(decide_v3.get("flags"), None);
    assert_eq!(decide_v3["featureFlags"]["v2-true"], true);
    let decide_v4 = post(&server, "v=4&config=false", DECIDE, body).await?;
    assert_eq!(decide_v4["flags"]["v2-true"]["enabled"], true);
    assert_eq!(decide_v4["flags"]["v2-true"].get("value"), None);

    let minimal: Value = reqwest::get(format!("http://{}/flags?v=3", server.addr))
        .await?
        .json()
        .await?;
    assert_eq!(minimal["flags"], json!({}));
    assert_eq!(minimal["supportedCompression"], json!(["gzip", "gzip-js"]));
    wire::validate_v3(&minimal).unwrap();
    Ok(())
}
