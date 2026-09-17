use std::collections::HashMap;
use std::sync::Arc;

use anyhow::Result;
use feature_flags::cohorts::cohort_cache_manager::CohortCacheManager;
use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::flags::cache_builder::build_flags_cache;
use feature_flags::flags::feature_flag_list::PreparedFlags;
use feature_flags::flags::flag_matching::FeatureFlagMatcher;
use feature_flags::flags::flag_models::{
    EvaluationMetadata, FeatureFlag, FeatureFlagList, FeatureFlagRow,
};
use feature_flags::utils::test_utils::{
    insert_flags_for_team_in_redis, mock_group_type_cache, setup_redis_client,
    update_team_in_hypercache, TestContext,
};
use rstest::rstest;
use serde_json::{json, Value};
use uuid::Uuid;

pub mod common;

fn documents() -> Vec<(String, Value, bool, bool)> {
    let mut cases = Vec::new();
    let supported: Value = serde_json::from_str(include_str!(
        "fixtures/rules_v2_parser/1.6.0/fixtures/config/valid/boolean_targeted_and_percentage_rollout.json"
    )).unwrap();
    cases.push((
        "rejected-valid-v2".to_string(),
        supported.clone(),
        true,
        false,
    ));
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
                    team_id: team.id,
                    key,
                    name: Some(String::new()),
                    filters,
                    active,
                    deleted,
                    version: Some(2),
                    ..Default::default()
                }),
            )
            .await?;
        }
    }
    if cached {
        let encoded = json!(flags)
            .to_string()
            .replace("\"__overprecise__\"", "33.330000000000000001");
        insert_flags_for_team_in_redis(redis, team.id, Some(encoded)).await?;
    } else {
        let raw = docs
            .iter()
            .find(|(key, ..)| key == "rejected-overprecise-v2")
            .unwrap()
            .1
            .to_string()
            .replace("\"__overprecise__\"", "33.330000000000000001");
        let mut connection = db.non_persons_writer.get_connection().await?;
        sqlx::query("UPDATE posthog_featureflag SET filters = $1::jsonb WHERE team_id = $2 AND key = 'rejected-overprecise-v2'")
            .bind(raw).bind(team.id).execute(&mut *connection).await?;
        drop(connection);
        let stored = FeatureFlagList::from_pg(db.non_persons_reader.clone(), team.id).await?;
        for (key, valid) in [
            ("rejected-valid-v2", true),
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
        assert!(build_flags_cache(db.non_persons_reader.clone(), team.id)
            .await
            .is_err());
    }
    let server = common::ServerHandle::for_config(DEFAULT_TEST_CONFIG.clone()).await;
    let client = reqwest::Client::new();
    let payload = json!({"token": team.api_token, "distinct_id": "example-person"});

    for (endpoint, version, errors_reported, shape) in [
        ("flags", "2", true, Shape::Detailed),
        (
            "flags",
            "1",
            true,
            Shape::Map {
                keeps_rejected_as_false: true,
            },
        ),
        ("decide", "1", false, Shape::EnabledKeys),
        (
            "decide",
            "2",
            false,
            Shape::Map {
                keeps_rejected_as_false: false,
            },
        ),
        (
            "decide",
            "3",
            true,
            Shape::Map {
                keeps_rejected_as_false: true,
            },
        ),
        ("decide", "4", true, Shape::Detailed),
    ] {
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
        if errors_reported {
            assert_eq!(body["errorsWhileComputingFlags"], true, "{body}");
        } else {
            assert!(body.get("errorsWhileComputingFlags").is_none(), "{body}");
        }
        match shape {
            Shape::Detailed => {
                for key in ["absent", "one", "one-float"] {
                    assert_eq!(body["flags"][key]["enabled"], true, "{body}");
                    assert_eq!(body["flags"][key]["metadata"]["version"], 2, "{body}");
                }
                for (key, _, active, deleted) in &docs {
                    if key.starts_with("rejected-") {
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
                assert_eq!(
                    keys,
                    vec![json!("absent"), json!("one"), json!("one-float")]
                );
            }
            Shape::Map {
                keeps_rejected_as_false,
            } => {
                let mut expected = json!({"absent": true, "one": true, "one-float": true});
                if keeps_rejected_as_false {
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
    Map { keeps_rejected_as_false: bool },
}

#[tokio::test]
async fn non_v1_rejects_before_preparation_and_missing_dependency_default() {
    let db = TestContext::new(None).await;
    let cohort_cache = Arc::new(CohortCacheManager::new(
        db.non_persons_reader.clone(),
        None,
        None,
    ));
    let mut matcher = FeatureFlagMatcher::new(
        "example-person".to_string(),
        None,
        1,
        db.create_postgres_router(),
        cohort_cache,
        mock_group_type_cache(HashMap::new()),
        None,
    );
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
    let cohort_cache = Arc::new(CohortCacheManager::new(
        db.non_persons_reader.clone(),
        None,
        None,
    ));
    let mut matcher = FeatureFlagMatcher::new(
        "example-person".to_string(),
        None,
        1,
        db.create_postgres_router(),
        cohort_cache,
        mock_group_type_cache(HashMap::new()),
        None,
    );
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
