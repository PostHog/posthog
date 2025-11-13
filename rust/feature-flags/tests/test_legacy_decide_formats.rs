use anyhow::Result;
use serde_json::{json, Value};

use crate::common::*;

use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::utils::test_utils::{
    insert_flags_for_team_in_redis, insert_new_team_in_redis, setup_redis_client,
};

pub mod common;

/// Integration test for legacy decide v1 format
/// Tests that when X-Original-Endpoint: decide header is present and v=1 query param is passed,
/// the response contains featureFlags as an array of strings (active flag keys only)
#[tokio::test]
async fn test_legacy_decide_v1_format() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    // Insert test flags - one enabled, one with variant, one disabled
    let flags_json = json!([
        {
            "id": 1,
            "team_id": team.id,
            "name": "Enabled Flag",
            "key": "enabled-flag",
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100
                    }
                ],
            },
            "deleted": false,
            "active": true,
            "ensure_experience_continuity": false
        },
        {
            "id": 2,
            "team_id": team.id,
            "name": "Flag with Variant",
            "key": "variant-flag",
            "filters": {
                "groups": [
                    {
                        "variant": "control",
                        "properties": [],
                        "rollout_percentage": 100
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control",
                            "rollout_percentage": 50
                        },
                        {
                            "key": "test",
                            "name": "Test",
                            "rollout_percentage": 50
                        }
                    ]
                }
            },
            "deleted": false,
            "active": true,
            "ensure_experience_continuity": false
        },
        {
            "id": 3,
            "team_id": team.id,
            "name": "Disabled Flag",
            "key": "disabled-flag",
            "filters": {
                "groups": [],
            },
            "deleted": false,
            "active": false,
            "ensure_experience_continuity": false
        }
    ]);

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id(),
        Some(flags_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    // Make request with X-Original-Endpoint header and v=1 query param
    let client = reqwest::Client::new();
    let res = client
        .post(format!("http://{}/flags?v=1", server.addr))
        .header("X-Original-Endpoint", "decide")
        .json(&payload)
        .send()
        .await?;

    assert_eq!(res.status(), 200);

    let response_json: Value = res.json().await?;

    // Verify decide v1 format: featureFlags is an array of strings
    assert!(
        response_json["featureFlags"].is_array(),
        "featureFlags should be an array for decide v1, got: {response_json:?}"
    );

    let flags = response_json["featureFlags"].as_array().unwrap();

    // Should only contain enabled flags (not disabled ones)
    assert_eq!(flags.len(), 2, "Should have 2 enabled flags");

    // Check that all items in the array are strings
    for flag in flags {
        assert!(
            flag.is_string(),
            "Each flag should be a string in decide v1, got: {flag:?}"
        );
    }

    // Check specific flags are included
    let flag_strings: Vec<String> = flags
        .iter()
        .map(|f| f.as_str().unwrap().to_string())
        .collect();
    assert!(flag_strings.contains(&"enabled-flag".to_string()));
    assert!(flag_strings.contains(&"variant-flag".to_string()));
    assert!(!flag_strings.contains(&"disabled-flag".to_string())); // disabled flag not included

    // Should not have featureFlagPayloads or flags fields
    assert!(
        !response_json
            .as_object()
            .unwrap()
            .contains_key("featureFlagPayloads"),
        "decide v1 should not have featureFlagPayloads"
    );
    assert!(
        !response_json.as_object().unwrap().contains_key("flags"),
        "decide v1 should not have flags field"
    );

    Ok(())
}

/// Integration test for legacy decide v2 format
/// Tests that when X-Original-Endpoint: decide header is present and v=2 query param is passed,
/// the response contains featureFlags as an object with flag values (booleans or strings)
#[tokio::test]
async fn test_legacy_decide_v2_format() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    // Insert test flags
    let flags_json = json!([
        {
            "id": 1,
            "team_id": team.id,
            "name": "Boolean Flag",
            "key": "boolean-flag",
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100
                    }
                ],
            },
            "deleted": false,
            "active": true,
            "ensure_experience_continuity": false
        },
        {
            "id": 2,
            "team_id": team.id,
            "name": "Variant Flag",
            "key": "variant-flag",
            "filters": {
                "groups": [
                    {
                        "variant": "control",
                        "properties": [],
                        "rollout_percentage": 100
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control",
                            "rollout_percentage": 100
                        }
                    ]
                }
            },
            "deleted": false,
            "active": true,
            "ensure_experience_continuity": false
        }
    ]);

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id(),
        Some(flags_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    // Make request with X-Original-Endpoint header and v=2 query param
    let client = reqwest::Client::new();
    let res = client
        .post(format!("http://{}/flags?v=2", server.addr))
        .header("X-Original-Endpoint", "decide")
        .json(&payload)
        .send()
        .await?;

    assert_eq!(res.status(), 200);

    let response_json: Value = res.json().await?;

    // Verify decide v2 format: featureFlags is an object with values
    assert!(
        response_json["featureFlags"].is_object(),
        "featureFlags should be an object for decide v2, got: {response_json:?}"
    );

    let flags = response_json["featureFlags"].as_object().unwrap();

    // Check specific flag values
    assert_eq!(flags.get("boolean-flag").unwrap(), &json!(true));
    assert_eq!(flags.get("variant-flag").unwrap(), &json!("control"));

    // Check that values are either booleans or strings (variants)
    for (key, value) in flags {
        assert!(
            value.is_boolean() || value.is_string(),
            "Flag '{key}' value should be boolean or string in decide v2, got: {value:?}"
        );
    }

    // Should not have featureFlagPayloads or flags fields
    assert!(
        !response_json
            .as_object()
            .unwrap()
            .contains_key("featureFlagPayloads"),
        "decide v2 should not have featureFlagPayloads"
    );
    assert!(
        !response_json.as_object().unwrap().contains_key("flags"),
        "decide v2 should not have flags field"
    );

    Ok(())
}

/// Test that X-Original-Endpoint: decide header changes how v query parameter is interpreted
#[tokio::test]
async fn test_decide_header_changes_version_interpretation() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let flags_json = json!([
        {
            "id": 1,
            "team_id": team.id,
            "name": "Test Flag",
            "key": "test-flag",
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100
                    }
                ],
            },
            "deleted": false,
            "active": true,
            "ensure_experience_continuity": false
        }
    ]);

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id(),
        Some(flags_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    // Request with v=1 query param and X-Original-Endpoint header
    // With decide endpoint, v=1 should map to DecideV1
    let client = reqwest::Client::new();
    let res = client
        .post(format!("http://{}/flags?v=1", server.addr))
        .header("X-Original-Endpoint", "decide")
        .json(&payload)
        .send()
        .await?;

    assert_eq!(res.status(), 200);

    let response_json: Value = res.json().await?;

    // Should return decide v1 format (array) not flags v2 format
    assert!(
        response_json["featureFlags"].is_array(),
        "Should return decide v1 format when X-Original-Endpoint: decide is present with v=1"
    );
    assert!(
        !response_json.as_object().unwrap().contains_key("flags"),
        "Should not have 'flags' field when X-Original-Endpoint: decide with v=1"
    );

    Ok(())
}
