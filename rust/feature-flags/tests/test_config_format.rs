use std::collections::HashMap;
use std::sync::Arc;

use anyhow::Result;
use common_hypercache::{HyperCacheConfig, HyperCacheReader, KeyType};
use common_s3::MockS3Client;
use feature_flags::cohorts::cohort_cache_manager::CohortCacheManager;
use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::flags::cache_builder::build_flags_cache;
use feature_flags::flags::feature_flag_list::PreparedFlags;
use feature_flags::flags::flag_matching::FeatureFlagMatcher;
use feature_flags::flags::flag_models::{
    EvaluationMetadata, FeatureFlag, FeatureFlagList, FeatureFlagRow, HypercacheFlagsWrapper,
};
use feature_flags::utils::test_utils::{
    flag_list_with_metadata, mock_group_type_cache, setup_redis_client, update_team_in_hypercache,
    write_flags_wire_json_to_redis, TestContext,
};
use rstest::rstest;
use serde_json::{json, Value};
use uuid::Uuid;

pub mod common;

fn documents() -> Vec<(String, Value, bool, bool)> {
    let mut cases = Vec::new();
    let supported: Value = serde_json::from_str(include_str!(
        "fixtures/rules_v2_parser/2.1.0/fixtures/config/valid/boolean_targeted_and_percentage_rollout.json"
    )).unwrap();
    cases.push((
        "evaluated-valid-v2".to_string(),
        supported.clone(),
        true,
        false,
    ));
    let mut rounded = supported.clone();
    rounded["version"] = json!("__rounds_to_two__");
    cases.push(("evaluated-rounded-v2".to_string(), rounded, true, false));
    let mut near_one = supported.clone();
    near_one["version"] = json!("__below_one__");
    cases.push(("rejected-below-one".to_string(), near_one, true, false));
    let mut unsupported = supported.clone();
    unsupported["rules"]
        .as_array_mut()
        .unwrap()
        .push(json!({"rule_type": "experiment"}));
    cases.push((
        "rejected-unsupported-v2".to_string(),
        unsupported,
        true,
        false,
    ));
    let mut overprecise = supported.clone();
    overprecise["rules"][1]["rollout_percentage"] = json!("__overprecise__");
    cases.push((
        "rejected-overprecise-v2".to_string(),
        overprecise,
        true,
        false,
    ));
    cases.push((
        "inactive-valid-v2".to_string(),
        supported.clone(),
        false,
        false,
    ));
    cases.push(("deleted-valid-v2".to_string(), supported, true, true));
    for (key, version) in [
        ("absent", None),
        ("one", Some(json!(1))),
        ("one-float", Some(json!(1.0))),
        ("one-rounded", Some(json!("__rounds_to_one__"))),
    ] {
        let mut filters = json!({"groups": [{"rollout_percentage": 100}], "payloads": {"true": "example-payload"}});
        if let Some(version) = version {
            filters["version"] = version;
        }
        cases.push((key.to_string(), filters, true, false));
    }
    for (index, version) in [
        json!(2),
        json!(2.0),
        json!(3),
        json!(1.5),
        json!("1"),
        json!("2"),
        json!(true),
        json!(false),
        Value::Null,
    ]
    .into_iter()
    .enumerate()
    {
        for (shape, groups) in [json!([{"rollout_percentage": 100}]), json!("not v1 groups")]
            .into_iter()
            .enumerate()
        {
            cases.push((
                format!("rejected-{index}-{shape}"),
                json!({"version": version, "groups": groups, "rules": [], "default_value": true}),
                true,
                false,
            ));
        }
    }
    cases.push((
        "inactive".to_string(),
        json!({"version": 1, "groups": [{"rollout_percentage": 100}]}),
        false,
        false,
    ));
    cases.push((
        "deleted".to_string(),
        json!({"groups": [{"rollout_percentage": 100}]}),
        true,
        true,
    ));
    cases.push((
        "inactive-v2".to_string(),
        json!({"version": 2, "groups": false}),
        false,
        false,
    ));
    cases
}

const RAW_NUMBERS: &[(&str, &str, &str)] = &[
    (
        "rejected-overprecise-v2",
        "__overprecise__",
        "33.330000000000000001",
    ),
    ("one-rounded", "__rounds_to_one__", "1.0000000000000001"),
    ("rejected-below-one", "__below_one__", "0.9999999999999999"),
    (
        "evaluated-rounded-v2",
        "__rounds_to_two__",
        "2.0000000000000001",
    ),
];

#[rstest]
#[case::redis(true)]
#[case::postgres_fallback(false)]
#[tokio::test]
async fn config_dispatch_preserves_siblings_and_wire_errors(#[case] cached: bool) -> Result<()> {
    let db = TestContext::new(None).await;
    let team = db.insert_new_team(None).await?;
    let redis = setup_redis_client(Some(DEFAULT_TEST_CONFIG.redis_url.clone())).await;
    update_team_in_hypercache(redis.clone(), &team).await?;
    let docs = documents();
    let mut flags = Vec::new();
    for (key, filters, active, deleted) in docs.clone() {
        if cached {
            flags.push(
                json!({"id": flags.len() + 1, "team_id": team.id, "key": key,
                "active": active, "deleted": deleted, "version": 2, "filters": filters}),
            );
        } else {
            db.insert_flag(
                team.id,
                Some(FeatureFlagRow {
                    deleted,
                    version: Some(2),
                    ..row(team.id, &key, filters, active)
                }),
            )
            .await?;
        }
    }
    if cached {
        let ids: Vec<_> = flags
            .iter()
            .map(|flag| flag["id"].as_i64().unwrap())
            .collect();
        let dependencies: serde_json::Map<_, _> =
            ids.iter().map(|id| (id.to_string(), json!([]))).collect();
        // Value-based cache helpers would round the discriminator under test.
        let mut encoded = json!({"flags": flags, "evaluation_metadata": {
            "dependency_stages": [ids], "flags_with_missing_deps": [], "transitive_deps": dependencies
        }}).to_string();
        for (_, placeholder, number) in RAW_NUMBERS {
            encoded = encoded.replace(&format!("\"{placeholder}\""), number);
        }
        write_flags_wire_json_to_redis(redis.clone(), team.id, encoded).await?;
    } else {
        let mut connection = db.non_persons_writer.get_connection().await?;
        for &(key, placeholder, number) in RAW_NUMBERS {
            let raw = docs
                .iter()
                .find(|(name, ..)| name == key)
                .unwrap()
                .1
                .to_string()
                .replace(&format!("\"{placeholder}\""), number);
            sqlx::query("UPDATE posthog_featureflag SET filters = $1::jsonb WHERE team_id = $2 AND key = $3")
                .bind(raw).bind(team.id).bind(key).execute(&mut *connection).await?;
        }
        drop(connection);
        // The cache builder keeps the supported v2 rows and omits every other non-v1
        // row instead of failing the team; the service's PostgreSQL fallback does the same.
        let mut built: Vec<String> = build_flags_cache(db.non_persons_reader.clone(), team.id)
            .await?
            .flags
            .into_iter()
            .map(|flag| flag.key)
            .collect();
        built.sort();
        assert_eq!(built, EVALUATED);
    }
    let stored = if cached {
        let reader = HyperCacheReader::new_with_s3_client(
            redis.clone(),
            Arc::new(MockS3Client::new()),
            HyperCacheConfig::new(
                "feature_flags".to_owned(),
                "flags.json".to_owned(),
                "us-east-1".to_owned(),
                "test-bucket".to_owned(),
            ),
        );
        reader
            .get_typed_from_redis::<HypercacheFlagsWrapper>(&KeyType::Int(team.id))
            .await?
            .expect("written flags must be present in Redis")
            .flags
    } else {
        FeatureFlagList::from_pg(db.non_persons_reader.clone(), team.id).await?
    };
    for (key, valid) in [
        ("evaluated-valid-v2", true),
        ("evaluated-rounded-v2", true),
        ("rejected-overprecise-v2", false),
    ] {
        let flag = stored.iter().find(|flag| flag.key == key).unwrap();
        assert_eq!(
            flag.filters
                .non_v1
                .as_ref()
                .unwrap()
                .parsed_v2
                .as_ref()
                .unwrap()
                .is_ok(),
            valid
        );
    }
    let server = common::ServerHandle::for_config(DEFAULT_TEST_CONFIG.clone()).await;
    let client = reqwest::Client::new();
    let payload = json!({"token": team.api_token, "distinct_id": "example-person",
        "person_properties": {"account_tier": "preview"}});
    let rejected_rows_reach_matcher = cached;

    for (endpoint, version, has_error_field, shape) in FORMATS {
        let response = client
            .post(format!(
                "http://{}/flags?v={version}&config=false",
                server.addr
            ))
            .header("X-Original-Endpoint", endpoint)
            .json(&payload)
            .send()
            .await?;
        assert_eq!(response.status(), 200, "{endpoint} v{version}");
        assert_eq!(response.headers()["content-type"], "application/json");
        let body: Value = response.json().await?;
        if has_error_field {
            assert_eq!(
                body["errorsWhileComputingFlags"], rejected_rows_reach_matcher,
                "{body}"
            );
        } else {
            assert!(body.get("errorsWhileComputingFlags").is_none(), "{body}");
        }
        match shape {
            Shape::Detailed => {
                for key in EVALUATED {
                    assert_eq!(body["flags"][key]["enabled"], true, "{body}");
                    assert_eq!(body["flags"][key]["metadata"]["version"], 2, "{body}");
                    assert!(body["flags"][key].get("failed").is_none(), "{body}");
                    assert!(body["flags"][key]["variant"].is_null(), "{body}");
                    assert_eq!(body["flags"][key]["reason"]["code"], "condition_match");
                    if key.starts_with("evaluated-") {
                        assert!(body["flags"][key]["metadata"]["payload"].is_null());
                    }
                }
                for (key, _, active, deleted) in &docs {
                    if key.starts_with("rejected-") && !rejected_rows_reach_matcher {
                        assert!(body["flags"].get(key).is_none(), "{body}");
                    } else if key.starts_with("rejected-") {
                        assert_eq!(body["flags"][key]["failed"], true, "{body}");
                        assert_eq!(
                            body["flags"][key]["reason"]["code"],
                            "flag_data_parsing_error"
                        );
                        assert_eq!(
                            body["flags"][key]["reason"]["description"],
                            "Failed to parse flag data: unsupported feature flag configuration format"
                        );
                        assert!(body["flags"][key]["metadata"]["payload"].is_null());
                    } else if !active || *deleted {
                        assert!(body["flags"].get(key).is_none(), "{body}");
                    }
                }
            }
            Shape::EnabledKeys => {
                let mut keys = body["featureFlags"].as_array().unwrap().clone();
                keys.sort_by(|a, b| a.as_str().cmp(&b.as_str()));
                assert_eq!(keys, EVALUATED.map(Value::from));
            }
            Shape::Map { enabled_only } => {
                let mut expected = json!({});
                for key in EVALUATED {
                    expected[key] = json!(true);
                }
                if rejected_rows_reach_matcher && !enabled_only {
                    for (key, _, _, _) in &docs {
                        if key.starts_with("rejected-") {
                            expected[key] = json!(false);
                        }
                    }
                }
                assert_eq!(body["featureFlags"], expected, "{endpoint} v{version}");
            }
        }
    }
    Ok(())
}

#[derive(Clone, Copy)]
enum Shape {
    Detailed,
    EnabledKeys,
    Map { enabled_only: bool },
}

const FORMATS: [(&str, &str, bool, Shape); 6] = [
    ("flags", "2", true, Shape::Detailed),
    (
        "flags",
        "1",
        true,
        Shape::Map {
            enabled_only: false,
        },
    ),
    ("decide", "1", false, Shape::EnabledKeys),
    ("decide", "2", false, Shape::Map { enabled_only: true }),
    (
        "decide",
        "3",
        true,
        Shape::Map {
            enabled_only: false,
        },
    ),
    ("decide", "4", true, Shape::Detailed),
];

fn row(team_id: i32, key: &str, filters: Value, active: bool) -> FeatureFlagRow {
    FeatureFlagRow {
        team_id,
        key: key.to_string(),
        name: Some(String::new()),
        filters,
        active,
        ..Default::default()
    }
}

fn matcher(db: &TestContext) -> FeatureFlagMatcher {
    FeatureFlagMatcher::new(
        "example-person".to_string(),
        None,
        1,
        db.create_postgres_router(),
        Arc::new(CohortCacheManager::new(
            db.non_persons_reader.clone(),
            None,
            None,
        )),
        mock_group_type_cache(HashMap::new()),
        None,
    )
}

const EVALUATED: [&str; 6] = [
    "absent",
    "evaluated-rounded-v2",
    "evaluated-valid-v2",
    "one",
    "one-float",
    "one-rounded",
];

#[tokio::test]
async fn non_v1_rejects_before_preparation_and_missing_dependency_default() {
    let db = TestContext::new(None).await;
    let mut matcher = matcher(&db);
    let flag: FeatureFlag = serde_json::from_value(json!({
        "id": 1, "team_id": 1, "key": "rejected", "active": true,
        "ensure_experience_continuity": true,
        "filters": {"version": 2, "groups": [{"properties": [{"type": "cohort", "key": "id", "value": 123}]}], "feature_enrollment": true, "aggregation_group_type_index": 99}
    })).unwrap();
    assert!(matcher.get_match(&flag, None, None, None, &None).is_err());
    let response = matcher
        .evaluate_all_feature_flags(
            FeatureFlagList {
                flags: PreparedFlags::seal(vec![flag]),
                evaluation_metadata: Arc::new(EvaluationMetadata {
                    dependency_stages: vec![vec![1]],
                    flags_with_missing_deps: vec![1],
                    ..Default::default()
                }),
                ..Default::default()
            },
            None,
            None,
            None,
            Uuid::new_v4(),
            None,
            false,
        )
        .await
        .unwrap();
    assert!(response.errors_while_computing_flags);
    assert!(response.flags["rejected"].failed);
    assert_eq!(
        response.flags["rejected"].reason.code,
        "flag_data_parsing_error"
    );
}

#[tokio::test]
async fn a_dependent_v1_flag_still_matches_against_a_non_v1_dependency() {
    let db = TestContext::new(None).await;
    let mut matcher = matcher(&db);
    let flags: Vec<FeatureFlag> = serde_json::from_value(json!([
        {"id": 1, "team_id": 1, "key": "blocker", "active": true,
         "filters": {"version": 2, "groups": [{"rollout_percentage": 100}]}},
        {"id": 2, "team_id": 1, "key": "dependent", "active": true,
         "filters": {"groups": [{"rollout_percentage": 100, "properties": [
            {"type": "flag", "key": "1", "value": false, "operator": "flag_evaluates_to"}]}]}}
    ]))
    .unwrap();
    let response = matcher
        .evaluate_all_feature_flags(
            FeatureFlagList {
                flags: PreparedFlags::seal(flags),
                evaluation_metadata: Arc::new(EvaluationMetadata {
                    dependency_stages: vec![vec![1], vec![2]],
                    ..Default::default()
                }),
                ..Default::default()
            },
            None,
            None,
            None,
            Uuid::new_v4(),
            None,
            false,
        )
        .await
        .unwrap();
    assert!(response.flags["blocker"].failed);
    assert!(response.flags["dependent"].enabled);
    assert!(response.errors_while_computing_flags);
}

#[rstest]
#[case::redis(true)]
#[case::postgres_fallback(false)]
#[tokio::test]
async fn mixed_team_projects_supported_v2_beside_v1(#[case] cached: bool) -> Result<()> {
    let db = TestContext::new(None).await;
    let team = db.insert_new_team(None).await?;
    let redis = setup_redis_client(Some(DEFAULT_TEST_CONFIG.redis_url.clone())).await;
    update_team_in_hypercache(redis.clone(), &team).await?;
    for (distinct_id, tier) in [("example-person", "preview"), ("other-person", "standard")] {
        db.insert_person(
            team.id,
            distinct_id.to_string(),
            Some(json!({"account_tier": tier})),
        )
        .await?;
    }
    let v2 = |default_value: Value, rules: Value| json!({"version": 2, "return_type": "boolean", "default_value": default_value, "rules": rules});
    let targeted = json!([{"id": "a1a1a1a1-a1a1-4a1a-8a1a-a1a1a1a1a1a1", "rule_type": "targeted_release",
        "targeting": {"properties": [{"key": "account_tier", "type": "person", "operator": "exact", "value": "preview"}]},
        "value": true}]);
    let malformed = db
        .insert_flag(
            team.id,
            Some(row(
                team.id,
                "v2-malformed",
                json!({"version": 2, "groups": [{"rollout_percentage": 100}]}),
                true,
            )),
        )
        .await?;
    for (key, filters, active) in [
        (
            "v1-on",
            json!({"groups": [{"rollout_percentage": 100}]}),
            true,
        ),
        (
            "v1-off",
            json!({"groups": [{"rollout_percentage": 0}]}),
            true,
        ),
        ("v2-targeted", v2(json!(false), targeted), true),
        ("v2-default-null", v2(Value::Null, json!([])), true),
        ("v2-inactive", v2(json!(true), json!([])), false),
        (
            "v1-depends-on-malformed",
            json!({"groups": [{"rollout_percentage": 100, "properties": [
                {"type": "flag", "key": malformed.id.to_string(), "value": false, "operator": "flag_evaluates_to"}]}]}),
            true,
        ),
        (
            "unsupported-version",
            json!({"version": 3, "groups": [{"rollout_percentage": 100}]}),
            true,
        ),
    ] {
        db.insert_flag(team.id, Some(row(team.id, key, filters, active)))
            .await?;
    }
    let wrapper = build_flags_cache(db.non_persons_reader.clone(), team.id).await?;
    let mut built: Vec<&str> = wrapper.flags.iter().map(|flag| flag.key.as_str()).collect();
    built.sort();
    assert_eq!(built, ["v1-off", "v1-on", "v2-default-null", "v2-targeted"]);
    if cached {
        write_flags_wire_json_to_redis(redis.clone(), team.id, serde_json::to_string(&wrapper)?)
            .await?;
    }

    let server = common::ServerHandle::for_config(DEFAULT_TEST_CONFIG.clone()).await;
    let client = reqwest::Client::new();
    for (distinct_id, targeted_value) in [("example-person", true), ("other-person", false)] {
        let payload = json!({"token": team.api_token, "distinct_id": distinct_id});
        let expected = json!({"v1-on": true, "v1-off": false,
            "v2-targeted": targeted_value, "v2-default-null": false});
        let enabled_keys = || {
            let mut keys: Vec<Value> = expected
                .as_object()
                .unwrap()
                .iter()
                .filter(|(_, value)| **value == true)
                .map(|(key, _)| json!(key))
                .collect();
            keys.sort_by(|a, b| a.as_str().cmp(&b.as_str()));
            keys
        };
        for (endpoint, version, has_error_field, shape) in FORMATS {
            let body: Value = client
                .post(format!(
                    "http://{}/flags?v={version}&config=false",
                    server.addr
                ))
                .header("X-Original-Endpoint", endpoint)
                .json(&payload)
                .send()
                .await?
                .error_for_status()?
                .json()
                .await?;
            if has_error_field {
                assert_eq!(body["errorsWhileComputingFlags"], false, "{body}");
            }
            match shape {
                Shape::Detailed => {
                    let flags = body["flags"].as_object().unwrap();
                    assert_eq!(flags.len(), 4, "{body}");
                    for (key, value) in expected.as_object().unwrap() {
                        assert_eq!(flags[key]["enabled"], *value, "{body}");
                        assert!(flags[key].get("failed").is_none(), "{body}");
                        assert!(flags[key]["variant"].is_null(), "{body}");
                        assert!(flags[key]["metadata"]["payload"].is_null(), "{body}");
                    }
                    assert_eq!(
                        flags["v2-default-null"]["reason"]["code"],
                        "no_condition_match"
                    );
                    assert_eq!(
                        flags["v2-targeted"]["reason"]["code"],
                        if targeted_value {
                            "condition_match"
                        } else {
                            "no_condition_match"
                        }
                    );
                }
                Shape::EnabledKeys => {
                    let mut keys = body["featureFlags"].as_array().unwrap().clone();
                    keys.sort_by(|a, b| a.as_str().cmp(&b.as_str()));
                    assert_eq!(keys, enabled_keys(), "{body}");
                }
                Shape::Map { enabled_only } => {
                    let mut map = expected.clone();
                    if enabled_only {
                        map.as_object_mut()
                            .unwrap()
                            .retain(|_, value| value == true);
                    } else {
                        assert_eq!(body["featureFlagPayloads"], json!({}), "{body}");
                    }
                    assert_eq!(body["featureFlags"], map, "{endpoint} v{version}");
                }
            }
        }
        let single: Value = client
            .post(format!("http://{}/flags?v=2&config=false", server.addr))
            .json(&json!({"token": team.api_token, "distinct_id": distinct_id, "flag_keys": ["v2-targeted"]}))
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        assert_eq!(single["flags"].as_object().unwrap().len(), 1, "{single}");
        assert_eq!(single["flags"]["v2-targeted"]["enabled"], targeted_value);
        assert_eq!(single["errorsWhileComputingFlags"], false);
    }
    Ok(())
}

#[tokio::test]
async fn detailed_analysis_is_empty_for_a_v2_flag_and_kept_for_v1() {
    let db = TestContext::new(None).await;
    let mut matcher = matcher(&db).with_detailed_analysis(true);
    let flags: Vec<FeatureFlag> = serde_json::from_value(json!([
        {"id": 1, "team_id": 1, "key": "v1", "active": true,
         "filters": {"groups": [{"rollout_percentage": 100}]}},
        {"id": 2, "team_id": 1, "key": "v2", "active": true,
         "filters": {"version": 2, "return_type": "boolean", "default_value": false, "rules": [
            {"id": "a1a1a1a1-a1a1-4a1a-8a1a-a1a1a1a1a1a1", "rule_type": "targeted_release",
             "targeting": {"properties": []}, "value": true}]}}
    ]))
    .unwrap();
    let response = matcher
        .evaluate_all_feature_flags(
            flag_list_with_metadata(flags),
            None,
            None,
            None,
            Uuid::new_v4(),
            None,
            false,
        )
        .await
        .unwrap();
    assert!(!response.errors_while_computing_flags);
    assert_eq!(
        response.flags["v1"].conditions.as_ref().map(Vec::len),
        Some(1)
    );
    assert!(response.flags["v2"].enabled);
    assert_eq!(
        response.flags["v2"].conditions.as_ref().map(Vec::len),
        Some(0)
    );
}
