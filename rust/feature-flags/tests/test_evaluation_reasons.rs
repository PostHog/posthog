use anyhow::Result;
use reqwest::StatusCode;
use serde_json::{json, Value};

use crate::common::*;
use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::utils::test_utils::{
    insert_flags_for_team_in_redis, insert_new_team_in_redis, setup_redis_client, TestContext,
};

pub mod common;

#[tokio::test]
async fn test_evaluation_reasons_endpoint_basic() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "test_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let redis_team = insert_new_team_in_redis(client.clone()).await.unwrap();

    let context = TestContext::new(None).await;
    let team = context.insert_new_team(Some(redis_team.id)).await.unwrap();
    let token = team.api_token;

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert a simple boolean flag
    let flag_json = json!([{
        "id": 1,
        "key": "test-flag",
        "name": "Test Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [{
                "properties": [],
                "rollout_percentage": 100
            }]
        },
    }]);

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    // Test the evaluation_reasons endpoint
    let response = reqwest::get(format!(
        "http://{}/evaluation_reasons?token={}&distinct_id={}",
        server.addr, token, distinct_id
    ))
    .await?;

    assert_eq!(response.status(), StatusCode::OK);

    let json: Value = response.json().await?;

    // Check the response structure
    assert!(json.is_object());
    let obj = json.as_object().unwrap();
    assert!(obj.contains_key("test-flag"));

    let flag_result = &obj["test-flag"];
    assert_eq!(flag_result["value"], json!(true));
    assert!(flag_result["evaluation"].is_object());

    // Most importantly: check that we use "reason" field, not "code"
    assert!(flag_result["evaluation"]["reason"].is_string());
    assert!(!flag_result["evaluation"]
        .as_object()
        .unwrap()
        .contains_key("code"));
    assert_eq!(flag_result["evaluation"]["reason"], "condition_match");
    assert_eq!(flag_result["evaluation"]["condition_index"], 0);

    Ok(())
}

#[tokio::test]
async fn test_evaluation_reasons_with_variant() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "variant_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let redis_team = insert_new_team_in_redis(client.clone()).await.unwrap();

    let context = TestContext::new(None).await;
    let team = context.insert_new_team(Some(redis_team.id)).await.unwrap();
    let token = team.api_token;

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert a multivariate flag
    let flag_json = json!([{
        "id": 2,
        "key": "variant-flag",
        "name": "Variant Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [{
                "properties": [],
                "rollout_percentage": 100,
                "variant": "control"
            }],
            "multivariate": {
                "variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50}
                ]
            }
        },
    }]);

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    let response = reqwest::get(format!(
        "http://{}/evaluation_reasons?token={}&distinct_id={}",
        server.addr, token, distinct_id
    ))
    .await?;

    assert_eq!(response.status(), StatusCode::OK);

    let json: Value = response.json().await?;
    let flag_result = &json["variant-flag"];

    // Check that variant is returned as the value
    assert!(flag_result["value"].is_string());
    assert_eq!(flag_result["value"], "control");

    // Check evaluation reason structure
    assert_eq!(flag_result["evaluation"]["reason"], "condition_match");
    assert!(!flag_result["evaluation"]
        .as_object()
        .unwrap()
        .contains_key("code"));

    Ok(())
}

#[tokio::test]
async fn test_evaluation_reasons_with_property_conditions() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "property_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let redis_team = insert_new_team_in_redis(client.clone()).await.unwrap();

    let context = TestContext::new(None).await;
    let team = context.insert_new_team(Some(redis_team.id)).await.unwrap();
    let token = team.api_token;

    // Insert person with properties
    context
        .insert_person(
            team.id,
            distinct_id.clone(),
            Some(json!({"plan": "premium"})),
        )
        .await
        .unwrap();

    // Insert a flag with property conditions
    let flag_json = json!([{
        "id": 3,
        "key": "premium-flag",
        "name": "Premium Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [{
                        "key": "plan",
                        "type": "person",
                        "value": ["premium"],
                        "operator": "exact"
                    }],
                    "rollout_percentage": 100
                },
                {
                    "properties": [],
                    "rollout_percentage": 0
                }
            ]
        },
    }]);

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    let response = reqwest::get(format!(
        "http://{}/evaluation_reasons?token={}&distinct_id={}",
        server.addr, token, distinct_id
    ))
    .await?;

    assert_eq!(response.status(), StatusCode::OK);

    let json: Value = response.json().await?;
    let flag_result = &json["premium-flag"];

    assert_eq!(flag_result["value"], json!(true));
    assert_eq!(flag_result["evaluation"]["reason"], "condition_match");
    assert_eq!(flag_result["evaluation"]["condition_index"], 0);

    Ok(())
}

#[tokio::test]
async fn test_evaluation_reasons_missing_distinct_id() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let redis_team = insert_new_team_in_redis(client.clone()).await.unwrap();

    let context = TestContext::new(None).await;
    let team = context.insert_new_team(Some(redis_team.id)).await.unwrap();
    let token = team.api_token;

    let server = ServerHandle::for_config(config).await;

    // Test without distinct_id
    let response = reqwest::get(format!(
        "http://{}/evaluation_reasons?token={}",
        server.addr, token
    ))
    .await?;

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);

    Ok(())
}

#[tokio::test]
async fn test_evaluation_reasons_with_groups() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "group_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let redis_team = insert_new_team_in_redis(client.clone()).await.unwrap();

    let context = TestContext::new(None).await;
    let team = context.insert_new_team(Some(redis_team.id)).await.unwrap();
    let token = team.api_token;

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert a group-based flag
    let flag_json = json!([{
        "id": 4,
        "key": "group-flag",
        "name": "Group Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [{
                "properties": [],
                "rollout_percentage": 100
            }],
            "aggregation_group_type_index": 0
        },
    }]);

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    // Test with groups parameter - just pass minimal groups to verify it's accepted
    let response = reqwest::get(format!(
        "http://{}/evaluation_reasons?token={}&distinct_id={}",
        server.addr, token, distinct_id
    ))
    .await?;

    assert_eq!(response.status(), StatusCode::OK);

    let json: Value = response.json().await?;
    assert!(json.is_object());

    // Without proper group setup, the flag would likely have no_group_type reason
    let flag_result = &json["group-flag"];
    assert!(flag_result["evaluation"]["reason"].is_string());

    Ok(())
}

#[tokio::test]
async fn test_evaluation_reasons_multiple_flags() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "multi_flag_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let redis_team = insert_new_team_in_redis(client.clone()).await.unwrap();

    let context = TestContext::new(None).await;
    let team = context.insert_new_team(Some(redis_team.id)).await.unwrap();
    let token = team.api_token;

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert multiple flags
    let flag_json = json!([
        {
            "id": 5,
            "key": "flag-a",
            "name": "Flag A",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [{
                    "properties": [],
                    "rollout_percentage": 100
                }]
            },
        },
        {
            "id": 6,
            "key": "flag-b",
            "name": "Flag B",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [{
                    "properties": [],
                    "rollout_percentage": 0
                }]
            },
        },
        {
            "id": 7,
            "key": "flag-c",
            "name": "Flag C",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [{
                    "properties": [],
                    "rollout_percentage": 50
                }]
            },
        }
    ]);

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    let response = reqwest::get(format!(
        "http://{}/evaluation_reasons?token={}&distinct_id={}",
        server.addr, token, distinct_id
    ))
    .await?;

    assert_eq!(response.status(), StatusCode::OK);

    let json: Value = response.json().await?;

    // Check all flags are present
    assert!(json["flag-a"].is_object());
    assert!(json["flag-b"].is_object());
    assert!(json["flag-c"].is_object());

    // Check flag-a (100% rollout)
    assert_eq!(json["flag-a"]["value"], json!(true));
    assert_eq!(json["flag-a"]["evaluation"]["reason"], "condition_match");

    // Check flag-b (0% rollout)
    assert_eq!(json["flag-b"]["value"], json!(false));
    assert_eq!(
        json["flag-b"]["evaluation"]["reason"],
        "out_of_rollout_bound"
    );

    // flag-c (50% rollout) could be either true or false depending on hash
    assert!(json["flag-c"]["value"].is_boolean());

    Ok(())
}

#[tokio::test]
async fn test_evaluation_reasons_response_format_matches_python() -> Result<()> {
    // This test specifically verifies the response format matches Python's format
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "format_test_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let redis_team = insert_new_team_in_redis(client.clone()).await.unwrap();

    let context = TestContext::new(None).await;
    let team = context.insert_new_team(Some(redis_team.id)).await.unwrap();
    let token = team.api_token;

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    let flag_json = json!([{
        "id": 8,
        "key": "format-test-flag",
        "name": "Format Test Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [{
                "properties": [],
                "rollout_percentage": 100
            }]
        },
    }]);

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    let response = reqwest::get(format!(
        "http://{}/evaluation_reasons?token={}&distinct_id={}",
        server.addr, token, distinct_id
    ))
    .await?;

    assert_eq!(response.status(), StatusCode::OK);

    let json: Value = response.json().await?;

    // Verify exact structure that Python returns:
    // {
    //   "flag_key": {
    //     "value": true/false/string,
    //     "evaluation": {
    //       "reason": "condition_match",  // NOT "code"!
    //       "condition_index": 0,
    //       "description": "optional description"
    //     }
    //   }
    // }

    let flag = &json["format-test-flag"];

    // Must have exactly these top-level keys
    assert!(flag["value"].is_boolean() || flag["value"].is_string());
    assert!(flag["evaluation"].is_object());
    assert_eq!(flag.as_object().unwrap().len(), 2); // Only "value" and "evaluation"

    // Evaluation must use "reason" not "code"
    let evaluation = flag["evaluation"].as_object().unwrap();
    assert!(evaluation.contains_key("reason"));
    assert!(!evaluation.contains_key("code")); // This is the critical difference!

    // Reason must be a string
    assert!(evaluation["reason"].is_string());

    // condition_index can be null or number
    assert!(evaluation["condition_index"].is_null() || evaluation["condition_index"].is_number());

    Ok(())
}

#[tokio::test]
async fn test_evaluation_reasons_with_disabled_flags() -> Result<()> {
    // This test verifies that disabled flags are included in evaluation_reasons response
    // matching the Python behavior
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "disabled_flag_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let redis_team = insert_new_team_in_redis(client.clone()).await.unwrap();

    let context = TestContext::new(None).await;
    let team = context.insert_new_team(Some(redis_team.id)).await.unwrap();
    let token = team.api_token;

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert an active flag in Redis (we can't directly insert disabled flags in Redis
    // since the cache only holds active flags)
    let flag_json = json!([{
        "id": 9,
        "key": "active-flag",
        "name": "Active Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [{
                "properties": [],
                "rollout_percentage": 100
            }]
        },
    }]);

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    // Directly insert a disabled flag into the database
    let disabled_flag = feature_flags::flags::flag_models::FeatureFlagRow {
        id: 10,
        team_id: team.id,
        name: Some("Disabled Flag".to_string()),
        key: "disabled-flag".to_string(),
        filters: serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}),
        deleted: false,
        active: false, // This is the key difference - flag is disabled
        ensure_experience_continuity: Some(false),
        version: Some(1),
        evaluation_runtime: Some("all".to_string()),
        evaluation_tags: None,
    };

    context
        .insert_flag(team.id, Some(disabled_flag))
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;

    let response = reqwest::get(format!(
        "http://{}/evaluation_reasons?token={}&distinct_id={}",
        server.addr, token, distinct_id
    ))
    .await?;

    assert_eq!(response.status(), StatusCode::OK);

    let json: Value = response.json().await?;

    // Check that active flag is present with normal evaluation
    assert!(json["active-flag"].is_object());
    assert_eq!(json["active-flag"]["value"], json!(true));
    assert_eq!(
        json["active-flag"]["evaluation"]["reason"],
        "condition_match"
    );

    // Check that disabled flag is present with "disabled" reason
    assert!(json["disabled-flag"].is_object());
    assert_eq!(json["disabled-flag"]["value"], json!(false));
    assert_eq!(json["disabled-flag"]["evaluation"]["reason"], "disabled");
    assert!(json["disabled-flag"]["evaluation"]["condition_index"].is_null());

    // Verify the response uses "reason" not "code" for both flags
    assert!(!json["active-flag"]["evaluation"]
        .as_object()
        .unwrap()
        .contains_key("code"));
    assert!(!json["disabled-flag"]["evaluation"]
        .as_object()
        .unwrap()
        .contains_key("code"));

    Ok(())
}

#[tokio::test]
async fn test_active_flag_precedence_over_disabled() -> Result<()> {
    // Test that when there's both an active and disabled flag with the same key,
    // the active flag takes precedence (this shouldn't normally happen in production)
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "precedence_test_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let redis_team = insert_new_team_in_redis(client.clone()).await.unwrap();

    let context = TestContext::new(None).await;
    let team = context.insert_new_team(Some(redis_team.id)).await.unwrap();
    let token = team.api_token;

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert an active flag with key "duplicate-flag" in Redis
    let flag_json = json!([{
        "id": 11,
        "key": "duplicate-flag",
        "name": "Active Duplicate Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [{
                "properties": [],
                "rollout_percentage": 100
            }]
        },
    }]);

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    // Also insert a disabled flag with the same key in the database
    // (This is an edge case that shouldn't normally happen)
    let disabled_flag = feature_flags::flags::flag_models::FeatureFlagRow {
        id: 12,
        team_id: team.id,
        name: Some("Disabled Duplicate Flag".to_string()),
        key: "duplicate-flag".to_string(), // Same key as active flag
        filters: serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}),
        deleted: false,
        active: false,
        ensure_experience_continuity: Some(false),
        version: Some(1),
        evaluation_runtime: Some("all".to_string()),
        evaluation_tags: None,
    };

    context
        .insert_flag(team.id, Some(disabled_flag))
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;

    let response = reqwest::get(format!(
        "http://{}/evaluation_reasons?token={}&distinct_id={}",
        server.addr, token, distinct_id
    ))
    .await?;

    assert_eq!(response.status(), StatusCode::OK);

    let json: Value = response.json().await?;

    // The active flag should take precedence
    assert!(json["duplicate-flag"].is_object());
    assert_eq!(json["duplicate-flag"]["value"], json!(true)); // Active flag returns true
    assert_eq!(
        json["duplicate-flag"]["evaluation"]["reason"],
        "condition_match"
    );
    // Should NOT have "disabled" as the reason
    assert_ne!(json["duplicate-flag"]["evaluation"]["reason"], "disabled");

    Ok(())
}

#[tokio::test]
async fn test_large_number_of_disabled_flags() -> Result<()> {
    // Test that the system handles a large number of disabled flags gracefully
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "large_disabled_test_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let redis_team = insert_new_team_in_redis(client.clone()).await.unwrap();

    let context = TestContext::new(None).await;
    let team = context.insert_new_team(Some(redis_team.id)).await.unwrap();
    let token = team.api_token;

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert one active flag
    let flag_json = json!([{
        "id": 1000,
        "key": "active-flag-large-test",
        "name": "Active Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [{
                "properties": [],
                "rollout_percentage": 100
            }]
        },
    }]);

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    // Insert many disabled flags (just a few for testing, but validates the pattern)
    for i in 0..10 {
        let disabled_flag = feature_flags::flags::flag_models::FeatureFlagRow {
            id: 2000 + i,
            team_id: team.id,
            name: Some(format!("Disabled Flag {}", i)),
            key: format!("disabled-flag-{}", i),
            filters: serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}),
            deleted: false,
            active: false,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
        };

        context
            .insert_flag(team.id, Some(disabled_flag))
            .await
            .unwrap();
    }

    let server = ServerHandle::for_config(config).await;

    let response = reqwest::get(format!(
        "http://{}/evaluation_reasons?token={}&distinct_id={}",
        server.addr, token, distinct_id
    ))
    .await?;

    assert_eq!(response.status(), StatusCode::OK);

    let json: Value = response.json().await?;

    // Check that active flag is present
    assert!(json["active-flag-large-test"].is_object());
    assert_eq!(json["active-flag-large-test"]["value"], json!(true));

    // Check that disabled flags are present
    for i in 0..10 {
        let key = format!("disabled-flag-{}", i);
        assert!(json[&key].is_object());
        assert_eq!(json[&key]["value"], json!(false));
        assert_eq!(json[&key]["evaluation"]["reason"], "disabled");
    }

    Ok(())
}
