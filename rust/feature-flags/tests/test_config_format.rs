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
    let mut flags = Vec::new();
    for (key, filters, active, deleted) in documents() {
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
        insert_flags_for_team_in_redis(redis, team.id, Some(json!(flags).to_string())).await?;
    } else {
        let built = build_flags_cache(db.non_persons_reader.clone(), team.id).await?;
        let serialized = serde_json::to_value(&built)?;
        for (key, filters, active, deleted) in documents() {
            if !active || deleted {
                continue;
            }
            let stored = serialized["flags"]
                .as_array()
                .unwrap()
                .iter()
                .find(|flag| flag["key"] == key)
                .unwrap();
            assert_eq!(stored["filters"].get("version"), filters.get("version"));
            if key.starts_with("rejected-") {
                assert_eq!(stored["filters"], filters);
            }
        }
    }
    let server = common::ServerHandle::for_config(DEFAULT_TEST_CONFIG.clone()).await;
    let client = reqwest::Client::new();
    let payload = json!({"token": team.api_token, "distinct_id": "example-person"});

    for _ in 0..2 {
        for (endpoint, version) in [
            ("flags", "2"),
            ("flags", "1"),
            ("decide", "1"),
            ("decide", "2"),
            ("decide", "3"),
            ("decide", "4"),
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
            if endpoint == "flags" || version == "3" || version == "4" {
                assert_eq!(body["errorsWhileComputingFlags"], true, "{body}");
            } else {
                assert!(body.get("errorsWhileComputingFlags").is_none());
            }
            if endpoint == "flags" && version == "2" || endpoint == "decide" && version == "4" {
                for key in ["absent", "one", "one-float"] {
                    assert_eq!(body["flags"][key]["enabled"], true, "{body}");
                    assert_eq!(
                        body["flags"][key]["metadata"]["version"],
                        if cached { 2 } else { 0 }
                    );
                }
                for (key, _, active, deleted) in documents() {
                    if key.starts_with("rejected-") {
                        assert_eq!(body["flags"][&key]["failed"], true, "{body}");
                        assert_eq!(
                            body["flags"][&key]["reason"]["code"],
                            "flag_data_parsing_error"
                        );
                        assert!(body["flags"][&key]["metadata"]["payload"].is_null());
                    } else if !active || deleted {
                        assert!(body["flags"].get(&key).is_none(), "{body}");
                    }
                }
            } else if endpoint == "decide" && version == "1" {
                let mut keys = body["featureFlags"].as_array().unwrap().clone();
                keys.sort_by(|a, b| a.as_str().cmp(&b.as_str()));
                assert_eq!(
                    keys,
                    vec![json!("absent"), json!("one"), json!("one-float")]
                );
            } else {
                let mut expected = json!({"absent": true, "one": true, "one-float": true});
                if endpoint == "flags" || version == "3" {
                    for (key, _, _, _) in documents() {
                        if key.starts_with("rejected-") {
                            expected[key] = json!(false);
                        }
                    }
                }
                assert_eq!(body["featureFlags"], expected);
            }
        }
    }
    Ok(())
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
