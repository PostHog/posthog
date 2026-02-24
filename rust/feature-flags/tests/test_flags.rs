use anyhow::Result;
use assert_json_diff::assert_json_include;
use base64::{engine::general_purpose, Engine as _};

use feature_flags::api::types::{FlagsResponse, LegacyFlagsResponse};
use limiters::redis::ServiceName;
use rand::Rng;
use reqwest::StatusCode;
use rstest::rstest;
use serde_json::{json, Value};

use crate::common::*;

use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::utils::test_utils::{
    insert_config_in_hypercache, insert_flags_for_team_in_redis, insert_new_team_in_redis,
    setup_pg_reader_client, setup_redis_client, TestContext,
};

pub mod common;

#[tokio::test]
async fn it_handles_get_requests_with_minimal_response() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    let server = ServerHandle::for_config(config).await;

    // Test GET request without any body - should return 200 with minimal response
    let get_response = reqwest::get(format!("http://{}/flags?v=2", server.addr)).await?;
    assert_eq!(get_response.status(), StatusCode::OK);

    let json: FlagsResponse = get_response.json().await?;
    assert!(!json.errors_while_computing_flags);
    assert!(json.flags.is_empty());
    assert!(json.quota_limited.is_none());
    assert_eq!(
        json.config.get("supportedCompression"),
        Some(&serde_json::json!(["gzip", "gzip-js"]))
    );

    // Verify evaluated_at field is present and is a valid timestamp
    assert!(json.evaluated_at > 0);

    // Test GET request with token in query params
    let get_response = reqwest::get(format!(
        "http://{}/flags?v=2&api_key={}",
        server.addr, token
    ))
    .await?;
    assert_eq!(get_response.status(), StatusCode::OK);

    // Test legacy version format
    let get_response = reqwest::get(format!("http://{}/flags?v=1", server.addr)).await?;
    assert_eq!(get_response.status(), StatusCode::OK);
    let legacy_json: LegacyFlagsResponse = get_response.json().await?;
    assert!(!legacy_json.errors_while_computing_flags);
    assert!(legacy_json.feature_flags.is_empty());

    Ok(())
}

#[rstest]
#[case(Some("1"))]
#[case(Some("banana"))]
#[tokio::test]
async fn it_gets_legacy_response_for_v1_or_invalid_version(
    #[case] version: Option<&str>,
) -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert a specific flag for the team
    let flag_json = json!([{
        "id": 1,
        "key": "test-flag",
        "name": "Test Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [],
                    "rollout_percentage": 100
                }
            ],
        },
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "groups": {"group1": "group1"}
    });

    let res = server
        .send_flags_request(payload.to_string(), version, None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "test-flag": true
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn it_gets_v2_response_by_default_when_no_params() -> Result<()> {
    // When no version and no config params are provided, we default to v=2 and config=true
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert a specific flag for the team
    let flag_json = json!([{
        "id": 1,
        "key": "test-flag",
        "name": "Test Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [],
                    "rollout_percentage": 100
                }
            ],
        },
    }]);

    insert_flags_for_team_in_redis(client.clone(), team.id, Some(flag_json.to_string())).await?;

    // Insert config into hypercache (required for config=true requests)
    let remote_config = json!({
        "supportedCompression": ["gzip", "gzip-js"],
        "config": {}
    });
    insert_config_in_hypercache(client.clone(), &token, remote_config).await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "groups": {"group1": "group1"}
    });

    let res = server
        .send_flags_request(payload.to_string(), None, None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    // With v=2 default, we get the new response format with config fields
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "test-flag": {
                    "key": "test-flag",
                    "enabled": true,
                    "reason": {
                        "code": "condition_match",
                        "condition_index": 0,
                        "description": "Matched condition set 1"
                    },
                    "metadata": {
                        "id": 1,
                        "version": 0
                    }
                }
            },
            "config": {}
        })
    );

    Ok(())
}

#[rstest]
#[case("2")]
#[case("3")]
#[tokio::test]
async fn it_get_new_response_when_version_is_2_or_more(#[case] version: &str) -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert a specific flag for the team
    let flag_json = json!([{
        "id": 1,
        "key": "test-flag",
        "name": "Test Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [],
                    "rollout_percentage": 100
                }
            ],
        },
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "groups": {"group1": "group1"}
    });

    let res = server
        .send_flags_request(payload.to_string(), Some(version), None)
        .await;

    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "test-flag": {
                    "key": "test-flag",
                    "enabled": true,
                    "reason": {
                        "code": "condition_match",
                        "condition_index": 0,
                        "description": "Matched condition set 1"
                    },
                    "metadata": {
                        "id": 1,
                        "version": 0
                    }
                }
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn it_rejects_invalid_headers_flag_request() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "groups": {"group1": "group1"}
    });
    let res = server
        .send_invalid_header_for_flags_request(payload.to_string())
        .await;
    assert_eq!(StatusCode::BAD_REQUEST, res.status());

    // We don't want to deserialize the data into a FlagsResponse struct here,
    // because we want to assert the shape of the raw json data.
    let response_text = res.text().await?;

    assert_eq!(
        response_text,
        "Failed to decode request: unsupported content type: xyz. Please check your request format and try again."
    );

    Ok(())
}

#[tokio::test]
async fn it_accepts_empty_distinct_id() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();
    let distinct_id = "user_distinct_id".to_string();
    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();
    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": "",
        "groups": {"group1": "group1"}
    });
    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    // Should return a valid response even with empty distinct_id
    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {}
        })
    );
    Ok(())
}

#[tokio::test]
async fn it_rejects_missing_distinct_id() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();
    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "groups": {"group1": "group1"}
    });
    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::BAD_REQUEST, res.status());
    assert_eq!(
        res.text().await?,
        "The distinct_id field is missing from the request. Please include a valid identifier."
    );
    Ok(())
}

#[tokio::test]
async fn it_rejects_missing_token() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "distinct_id": "user1",
        "groups": {"group1": "group1"}
    });
    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::UNAUTHORIZED, res.status());
    assert_eq!(
        res.text().await?,
        "No API token provided. Please include a valid API token in your request."
    );
    Ok(())
}

#[tokio::test]
async fn it_rejects_invalid_token() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": "invalid_token",
        "distinct_id": "user1",
        "groups": {"group1": "group1"}
    });
    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::UNAUTHORIZED, res.status());
    assert_eq!(
        res.text().await?,
        "The provided API key is invalid or has expired. Please check your API key and try again."
    );
    Ok(())
}

#[tokio::test]
async fn it_handles_malformed_json() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let server = ServerHandle::for_config(config).await;

    let payload = "{invalid_json}";
    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::BAD_REQUEST, res.status());

    let response_text = res.text().await?;

    assert!(
        response_text.contains("Failed to decode request: invalid JSON"),
        "Unexpected error message: {response_text:?}"
    );
    Ok(())
}

#[tokio::test]
async fn it_handles_base64_auto_detection_fallback() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    // Set up Redis and PostgreSQL clients
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    let server = ServerHandle::for_config(config).await;

    let json_payload = json!({
        "token": token,
        "distinct_id": "user123",
        "disable_flags": false
    });

    // Test 1: Normal JSON
    let res = server
        .send_flags_request(json_payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    // Test 2: Base64 encoded JSON with compression not specified
    let json_string = json_payload.to_string();
    let base64_payload = general_purpose::STANDARD.encode(json_string.as_bytes());

    let res = server
        .send_flags_request(base64_payload, Some("2"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    // Test 3: Invalid base64 should fail gracefully
    let invalid_base64 = "this is not valid base64 at all!";
    let res = server
        .send_flags_request(invalid_base64.to_string(), Some("2"), None)
        .await;
    assert_eq!(StatusCode::BAD_REQUEST, res.status());

    let response_text = res.text().await?;
    assert!(
        response_text.contains("Failed to decode request: invalid JSON"),
        "Should fail with invalid JSON error for invalid base64: {response_text:?}"
    );

    Ok(())
}

#[tokio::test]
async fn it_handles_disable_flags_without_distinct_id() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    // Set up Redis and PostgreSQL clients
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    insert_flags_for_team_in_redis(client.clone(), team.id, None)
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;

    // Request with disable_flags=true but NO distinct_id should succeed
    let disabled_payload = json!({
        "token": token,
        "disable_flags": true
        // Note: no distinct_id field
    });

    let res = server
        .send_flags_request(disabled_payload.to_string(), Some("2"), None)
        .await;

    assert_eq!(StatusCode::OK, res.status());

    let response_body = res.json::<FlagsResponse>().await?;
    // Should return empty flags since they're disabled
    assert!(response_body.flags.is_empty());

    Ok(())
}

#[tokio::test]
async fn it_handles_quota_limiting() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    // Create a token for testing
    let token = format!("test_token_{}", rand::thread_rng().gen::<u64>());
    let team_id = 12345;

    // Create a server with the limited token
    let server = ServerHandle::for_config_with_mock_redis(
        config.clone(),
        vec![token.clone()],            // Limited tokens
        vec![(token.clone(), team_id)], // Valid tokens with their team IDs
    )
    .await;

    // Test with a limited token
    let payload = json!({
        "token": token,
        "distinct_id": "user1",
        "groups": {"group1": "group1"}
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());
    let response_body = res.json::<LegacyFlagsResponse>().await?;

    // Parse response body and assert that the quota_limited field is present and contains the correct value
    assert!(response_body.quota_limited.is_some());
    assert_eq!(
        vec![ServiceName::FeatureFlags.as_string()],
        response_body.quota_limited.unwrap()
    );

    Ok(())
}

#[tokio::test]
async fn it_handles_quota_limiting_v2() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    // Create a token for testing
    let token = format!("test_token_{}", rand::thread_rng().gen::<u64>());
    let team_id = 12345;

    // Create a server with the limited token
    let server = ServerHandle::for_config_with_mock_redis(
        config.clone(),
        vec![token.clone()],            // Limited tokens
        vec![(token.clone(), team_id)], // Valid tokens with their team IDs
    )
    .await;

    // Test with a limited token
    let payload = json!({
        "token": token,
        "distinct_id": "user1",
        "groups": {"group1": "group1"}
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());
    let response_body = res.json::<FlagsResponse>().await?;

    // Parse response body and assert that the quota_limited field is present and contains the correct value
    assert!(response_body.quota_limited.is_some());
    assert_eq!(
        vec![ServiceName::FeatureFlags.as_string()],
        response_body.quota_limited.unwrap()
    );

    Ok(())
}

#[tokio::test]
async fn it_handles_multivariate_flags() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    let flag_json = json!([{
        "id": 1,
        "key": "multivariate-flag",
        "name": "Multivariate Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [],
                    "rollout_percentage": 100
                }
            ],
            "multivariate": {
                "variants": [
                    {
                        "key": "control",
                        "name": "Control",
                        "rollout_percentage": 0
                    },
                    {
                        "key": "test_a",
                        "name": "Test A",
                        "rollout_percentage": 0
                    },
                    {
                        "key": "test_b",
                        "name": "Test B",
                        "rollout_percentage": 100
                    }
                ]
            }
        },
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "multivariate-flag": "test_b"
            }
        })
    );

    let variant = json_data["featureFlags"]["multivariate-flag"]
        .as_str()
        .unwrap();
    assert!(["control", "test_a", "test_b"].contains(&variant));

    Ok(())
}

#[tokio::test]
async fn it_handles_flag_with_property_filter() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();
    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();
    let flag_json = json!([{
        "id": 1,
        "key": "property-flag",
        "name": "Property Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [
                        {
                            "key": "email",
                            "value": "test@example.com",
                            "operator": "exact",
                            "type": "person"
                        }
                    ],
                    "rollout_percentage": 100
                }
            ],
        },
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Test with matching property
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "person_properties": {
            "email": "test@example.com"
        }
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "property-flag": true
            }
        })
    );

    // Test with non-matching property
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "person_properties": {
            "email": "other@example.com"
        }
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "property-flag": false
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn it_matches_flags_to_a_request_with_group_property_overrides() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(Some(team.id)).await.unwrap();
    let token = team.api_token.clone();

    let flag_json = json!([{
        "id": 1,
        "key": "group-flag",
        "name": "Group Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [
                        {
                            "key": "name",
                            "value": "Test Group",
                            "operator": "exact",
                            "type": "group",
                            "group_type_index": 0
                        }
                    ],
                    "rollout_percentage": 100
                }
            ],
            "aggregation_group_type_index": 0
        },
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Test with matching group property
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "groups": {
            "project": "test_company_id"
        },
        "group_properties": {
            "project": {
                "name": "Test Group"
            }
        }
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "group-flag": true
            }
        })
    );

    // Test with non-matching group property
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "groups": {
            "project": "test_company_id"
        },
        "group_properties": {
            "project": {
                "name": "Other Group"
            }
        }
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "group-flag": false
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_feature_flags_with_json_payloads() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "example_id".to_string();
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;

    // Insert a new team into Redis and retrieve the team details
    let team = insert_new_team_in_redis(redis_client.clone())
        .await
        .unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    context
        .insert_person(
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "tim@posthog.com"})),
        )
        .await?;

    let flag_json = json!([{
        "id": 1,
        "key": "filter-by-property",
        "name": "Filter by property",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [
                        {
                            "key": "email",
                            "value": "tim@posthog.com",
                            "operator": "exact",
                            "type": "person",
                        }
                    ],
                    "rollout_percentage": null,
                }
            ],
            "payloads": {
                "true": {
                    "color": "blue"
                }
            },
        },
    }]);

    insert_flags_for_team_in_redis(redis_client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;

    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;

    assert_json_include!(
        actual: json_data,
        expected: json!({
            "featureFlagPayloads": {
                "filter-by-property": { "color": "blue" }
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_feature_flags_with_group_relationships() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "example_id".to_string();
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team_id = rand::thread_rng().gen_range(1_000_000..100_000_000);
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(Some(team_id)).await.unwrap();

    // need this for the test to work, since we look up the dinstinct_id <-> person_id in from the DB at the beginning
    // of the flag evaluation process
    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await?;

    let token = team.api_token.clone();

    // Create a group of type "organization" (group_type_index 1) with group_key "foo" and specific properties
    context
        .create_group(
            team.id,
            "organization",
            "foo",
            json!({"email": "posthog@example.com"}),
        )
        .await?;

    // Create a group of type "project" (group_type_index 0) with group_key "bar" and specific properties
    context
        .create_group(team.id, "project", "bar", json!({"name": "Project Bar"}))
        .await?;

    // Define feature flags
    let flags_json = json!([
        {
            "id": 1,
            "key": "default-no-prop-group-flag",
            "name": "This is a feature flag with default params, no filters.",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "aggregation_group_type_index": 0,
                "groups": [{"rollout_percentage": null}]
            }
        },
        {
            "id": 2,
            "key": "groups-flag",
            "name": "This is a group-based flag",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "aggregation_group_type_index": 1,
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "posthog",
                                "operator": "icontains",
                                "type": "group",
                                "group_type_index": 1
                            }
                        ],
                        "rollout_percentage": null
                    }
                ]
            }
        }
    ]);

    // Insert the feature flags into Redis
    insert_flags_for_team_in_redis(redis_client.clone(), team.id, Some(flags_json.to_string()))
        .await?;

    let server = ServerHandle::for_config(config).await;

    // First Decision: Without specifying any groups
    {
        let payload = json!({
            "token": token,
            "distinct_id": distinct_id
        });

        let res = server
            .send_flags_request(payload.to_string(), Some("1"), None)
            .await;
        assert_eq!(res.status(), StatusCode::OK);

        let json_data = res.json::<Value>().await?;
        assert_json_include!(
            actual: json_data,
            expected: json!({
                "errorsWhileComputingFlags": false,
                "featureFlags": {
                    "default-no-prop-group-flag": false, // if we don't specify any groups in the request, the flags should be false
                    "groups-flag": false
                }
            })
        );
    }

    // Second Decision: With non-matching group overrides
    {
        let payload = json!({
            "token": token,
            "distinct_id": distinct_id,
            "groups": {
                "organization": "foo2", // Does not match existing group_key "foo"
                "project": "bar"         // Matches existing project group
            }
        });

        let res = server
            .send_flags_request(payload.to_string(), Some("1"), None)
            .await;
        assert_eq!(res.status(), StatusCode::OK);

        let json_data = res.json::<Value>().await?;
        assert_json_include!(
            actual: json_data,
            expected: json!({
                "errorsWhileComputingFlags": false,
                "featureFlags": {
                    "default-no-prop-group-flag": true,
                    "groups-flag": false
                }
            })
        );
    }

    // Third Decision: With matching group
    {
        let payload = json!({
            "token": token,
            "distinct_id": distinct_id,
            "groups": {
                "organization": "foo", // Matches existing group_key for organization "foo"
                "project": "bar"       // Matches existing group_key for project "bar"
            }
        });

        let res = server
            .send_flags_request(payload.to_string(), Some("1"), None)
            .await;
        assert_eq!(res.status(), StatusCode::OK);

        let json_data = res.json::<Value>().await?;
        assert_json_include!(
            actual: json_data,
            expected: json!({
                "errorsWhileComputingFlags": false,
                "featureFlags": {
                    "default-no-prop-group-flag": true,
                    "groups-flag": true
                }
            })
        );
    }

    Ok(())
}

#[tokio::test]
async fn it_handles_not_contains_property_filter() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    let flag_json = json!([{
        "id": 1,
        "key": "not-contains-flag",
        "name": "Not Contains Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [
                        {
                            "key": "email",
                            "value": "@posthog.com",
                            "operator": "not_icontains",
                            "type": "person"
                        }
                    ],
                    "rollout_percentage": 100
                }
            ],
        },
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Test without any person properties - should match since the property doesn't exist
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "not-contains-flag": true
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn it_handles_not_equal_and_not_regex_property_filters() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();
    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    let flag_json = json!([
        {
            "id": 1,
            "key": "not-equal-flag",
            "name": "Not Equal Flag",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "test@posthog.com",
                                "operator": "is_not",
                                "type": "person"
                            }
                        ],
                        "rollout_percentage": 100
                    }
                ],
            },
        },
        {
            "id": 2,
            "key": "not-regex-flag",
            "name": "Not Regex Flag",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": ".*@posthog\\.com$",
                                "operator": "not_regex",
                                "type": "person"
                            }
                        ],
                        "rollout_percentage": 100
                    }
                ],
            },
        }
    ]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Test 1: Without any person properties - should match since properties don't exist
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "not-equal-flag": true,
                "not-regex-flag": true
            }
        })
    );

    // Test 2: With non-matching properties - should match
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "person_properties": {
            "email": "other@example.com"
        }
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "not-equal-flag": true,
                "not-regex-flag": true
            }
        })
    );

    // Test 3: With matching properties - should not match
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "person_properties": {
            "email": "test@posthog.com"
        }
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "not-equal-flag": false,
                "not-regex-flag": false
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_complex_regex_and_name_match_flag() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "example_id".to_string();
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();
    let token = team.api_token.clone();

    // Create a group with matching name
    context
        .create_group(
            team.id,
            "organization",
            "0183ccf3-5efd-0000-1541-bbd96d7d6b7f",
            json!({
                "name": "RaquelMSmith",
                "created_at": "2023-10-16T16:00:00Z"
            }),
        )
        .await?;

    let flag_json = json!([{
        "id": 1,
        "key": "complex-flag",
        "name": "Complex Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [
                        {
                            "key": "created_at",
                            "type": "group",
                            "value": "2023-10-16T(15|16|17|18|19|20|21|22|23)|2023-10-1[7-9]T|2023-10-[2-3][0-9]T|2023-1[1-2]-",
                            "operator": "regex",
                            "group_type_index": 1
                        }
                    ],
                    "rollout_percentage": null
                },
                {
                    "variant": "test",
                    "properties": [
                        {
                            "key": "name",
                            "type": "group",
                            "value": ["RaquelMSmith", "Raquel's Test Org", "Raquel Test Org 3"],
                            "operator": "exact",
                            "group_type_index": 1
                        }
                    ],
                    "rollout_percentage": 100
                }
            ],
            "payloads": {},
            "multivariate": {
                "variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50}
                ]
            },
            "aggregation_group_type_index": 1
        }
    }]);

    insert_flags_for_team_in_redis(redis_client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Test with matching group
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "groups": {
            "organization": "0183ccf3-5efd-0000-1541-bbd96d7d6b7f"
        }
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "complex-flag": "control"  // First condition matches (regex on created_at), gets control from multivariate
            }
        })
    );

    // Test with non-matching name but matching date
    context
        .create_group(
            team.id,
            "organization",
            "other_organization",
            json!({
                "name": "Other Org",
                "created_at": "2023-10-16T16:00:00Z"
            }),
        )
        .await?;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "groups": {
            "organization": "other_organization"
        }
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    let flag_value = json_data["featureFlags"]["complex-flag"].as_str().unwrap();
    assert!(
        ["control", "test"].contains(&flag_value),
        "Expected either 'control' or 'test' variant, got {flag_value}"
    );

    Ok(())
}

#[tokio::test]
async fn test_super_condition_with_complex_request() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "test_user".to_string();
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(redis_client.clone()).await?;
    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await?;
    let token = team.api_token.clone();

    // Insert person with just their stored properties from the DB
    context
        .insert_person(
            team.id,
            distinct_id.clone(),
            Some(json!({
                "$feature_enrollment/my-flag": true,
                "$feature_enrollment/error-tracking": true,
                "$feature_enrollment/messaging-product": true,
                "email": "gtarasov.work@gmail.com"
            })),
        )
        .await?;

    // Create the same flag as in production
    let flag_json = json!([{
        "id": 13651,
        "key": "my-flag",
        "name": "Generate HogQL with AI in Insights",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [{"key": "email", "type": "person", "value": "@storytell.ai", "operator": "icontains"}],
                    "rollout_percentage": 100
                },
                {
                    "properties": [{"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains"}],
                    "rollout_percentage": 100
                }
            ],
            "super_groups": [{
                "properties": [{
                    "key": "$feature_enrollment/my-flag",
                    "type": "person",
                    "value": ["true"],
                    "operator": "exact"
                }],
                "rollout_percentage": 100
            }]
        }
    }]);

    insert_flags_for_team_in_redis(redis_client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Send request with all the property overrides from the API request
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "groups": {
            "project": "01908d8e-a7fe-0000-403d-5de1f5feeb34",
            "organization": "01908d8e-a7ed-0000-5678-bb4cf061a2f6",
            "customer": "cus_IK2DWsWVn2ZM16",
            "instance": "https://us.posthog.com"
        },
        "person_properties": {
            "$initial_referrer": "https://us.posthog.com/admin/posthog/user/106009/change/?_changelist_filters=q%3Dgtarasov.work",
            "$initial_referring_domain": "us.posthog.com",
            "$initial_current_url": "https://us.posthog.com/project/78189/settings/user",
            "$initial_host": "us.posthog.com",
            "$initial_pathname": "/project/78189/settings/user",
            "$initial_utm_source": null,
            "$initial_utm_medium": null,
            "$initial_utm_campaign": null,
            "$initial_utm_content": null,
            "$initial_utm_term": null,
            "email": "gtarasov.work@gmail.com"
        }
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "my-flag": true
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_flag_matches_with_no_person_profile() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    // Create a flag with two conditions:
    // 1. A property filter (which won't match since there's no person)
    // 2. Just a rollout percentage (which should match since it's 100%)
    let flag_json = json!([{
        "id": 1,
        "key": "test-flag",
        "name": "Test Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [{
                        "key": "email",
                        "value": "test@example.com",
                        "type": "person",
                        "operator": "exact"
                    }],
                    "rollout_percentage": 100
                },
                {
                    "properties": [],
                    "rollout_percentage": 100
                }
            ],
        },
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Use a distinct_id that doesn't exist in the database
    let payload = json!({
        "token": token,
        "distinct_id": "nonexistent_user",
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "test-flag": {
                    "key": "test-flag",
                    "enabled": true,
                    "reason": {
                        "code": "condition_match",
                        "condition_index": 1,  // Important: matches on the second condition
                        "description": "Matched condition set 2"
                    }
                }
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn it_sets_quota_limited_in_legacy_and_v2() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let token = format!("test_token_{}", rand::thread_rng().gen::<u64>());
    let team_id = 12345;

    let server = ServerHandle::for_config_with_mock_redis(
        config.clone(),
        vec![token.clone()],
        vec![(token.clone(), team_id)],
    )
    .await;

    let payload = json!({
        "token": token,
        "distinct_id": "user1",
        "groups": {"group1": "group1"}
    });

    // Legacy response (no version param)
    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());
    let legacy: LegacyFlagsResponse = res.json().await?;
    assert_eq!(
        legacy.quota_limited,
        Some(vec![ServiceName::FeatureFlags.as_string()])
    );

    // V2 response (version=2)
    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());
    let v2: FlagsResponse = res.json().await?;
    assert_eq!(
        v2.quota_limited,
        Some(vec![ServiceName::FeatureFlags.as_string()])
    );

    Ok(())
}

#[tokio::test]
async fn it_only_includes_config_fields_when_requested() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    let flag_json = json!([{
        "id": 1,
        "key": "test-flag",
        "name": "Test Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [],
                    "rollout_percentage": 100
                }
            ],
        },
    }]);

    insert_flags_for_team_in_redis(client.clone(), team.id, Some(flag_json.to_string())).await?;

    // Insert config into hypercache (required for config=true requests)
    let remote_config = json!({
        "supportedCompression": ["gzip", "gzip-js"],
        "autocapture_opt_out": false
    });
    insert_config_in_hypercache(client.clone(), &token, remote_config).await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    // Without config param - should not include config fields
    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    if res.status() != StatusCode::OK {
        let text = res.text().await?;
        panic!("Non-200 response \nBody: {text}");
    }
    let json_data = res.json::<Value>().await?;
    assert!(json_data.get("supportedCompression").is_none());
    assert!(json_data.get("autocapture_opt_out").is_none());

    // With config param - should include config fields from hypercache
    let res = server
        .send_flags_request(payload.to_string(), Some("2"), Some("true"))
        .await;
    let json_data = res.json::<Value>().await?;
    assert!(json_data.get("supportedCompression").is_some());
    assert_eq!(
        json_data.get("supportedCompression"),
        Some(&json!(["gzip", "gzip-js"]))
    );

    Ok(())
}

/// Test config passthrough for an enterprise team with all features enabled.
/// This verifies the response shape matches what SDKs expect when
/// config is populated by Python's RemoteConfig.build_config() and passed through by Rust.
#[tokio::test]
async fn test_config_passthrough_enterprise_team() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "enterprise_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert a flag
    let flag_json = json!([{
        "id": 1,
        "key": "test-flag",
        "name": "Test Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [{"properties": [], "rollout_percentage": 100}],
        },
    }]);
    insert_flags_for_team_in_redis(client.clone(), team.id, Some(flag_json.to_string())).await?;

    // Insert realistic enterprise config that Python's RemoteConfig.build_config() would generate
    // This represents a team with all enterprise features enabled
    let remote_config = json!({
        "supportedCompression": ["gzip", "gzip-js"],
        "autocapture_opt_out": false,
        "config": {
            "enable_collect_everything": true
        },
        "toolbarParams": {},
        "isAuthenticated": false,
        "defaultIdentifiedOnly": true,
        "sessionRecording": {
            "endpoint": "/s/",
            "recorderVersion": "v2",
            "sampleRate": "1.0",
            "consoleLogRecordingEnabled": true,
            "networkPayloadCapture": {"recordBody": true, "recordHeaders": true}
        },
        "surveys": true,
        "heatmaps": true,
        "siteApps": [
            {"id": 1, "url": "/site_app/enterprise_token/"}
        ],
        "analytics": {
            "endpoint": "https://analytics.posthog.com"
        },
        "elementsChainAsString": true,
        "capturePerformance": {
            "network_timing": true,
            "web_vitals": true,
            "web_vitals_allowed_metrics": ["CLS", "FCP", "LCP", "FID", "TTFB"]
        },
        "autocaptureExceptions": {
            "endpoint": "/e/"
        },
        "flagsPersistenceDefault": true,
        "captureDeadClicks": true,
        "errorTracking": {
            "autocaptureExceptions": true,
            "suppressionRules": []
        }
    });
    insert_config_in_hypercache(client.clone(), &token, remote_config).await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    // Test v2 response with config=true
    let res = server
        .send_flags_request(payload.to_string(), Some("2"), Some("true"))
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;

    // Verify flag evaluation still works alongside config
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "test-flag": {
                    "key": "test-flag",
                    "enabled": true
                }
            }
        })
    );

    // Verify all enterprise config fields are passed through correctly
    // These assertions ensure the response shape matches SDK expectations

    // Basic config fields
    assert_eq!(
        json_data["supportedCompression"],
        json!(["gzip", "gzip-js"])
    );
    assert_eq!(json_data["autocapture_opt_out"], json!(false));
    assert_eq!(json_data["defaultIdentifiedOnly"], json!(true));
    assert_eq!(json_data["isAuthenticated"], json!(false));
    assert_eq!(
        json_data["config"],
        json!({"enable_collect_everything": true})
    );
    assert_eq!(json_data["toolbarParams"], json!({}));

    // Analytics endpoint
    assert!(json_data["analytics"].is_object());
    assert_eq!(
        json_data["analytics"]["endpoint"],
        json!("https://analytics.posthog.com")
    );

    // Elements chain as string
    assert_eq!(json_data["elementsChainAsString"], json!(true));

    // Performance capture with web vitals
    let capture_performance = &json_data["capturePerformance"];
    assert!(capture_performance.is_object());
    assert_eq!(capture_performance["network_timing"], json!(true));
    assert_eq!(capture_performance["web_vitals"], json!(true));
    assert_eq!(
        capture_performance["web_vitals_allowed_metrics"],
        json!(["CLS", "FCP", "LCP", "FID", "TTFB"])
    );

    // Autocapture exceptions
    assert_eq!(
        json_data["autocaptureExceptions"],
        json!({"endpoint": "/e/"})
    );

    // Optional team features (all enabled for enterprise)
    assert_eq!(json_data["surveys"], json!(true));
    assert_eq!(json_data["heatmaps"], json!(true));
    assert_eq!(json_data["flagsPersistenceDefault"], json!(true));
    assert_eq!(json_data["captureDeadClicks"], json!(true));

    // Session recording config
    assert!(json_data["sessionRecording"].is_object());
    let session_recording = &json_data["sessionRecording"];
    assert_eq!(session_recording["endpoint"], json!("/s/"));
    assert_eq!(session_recording["recorderVersion"], json!("v2"));
    assert_eq!(session_recording["consoleLogRecordingEnabled"], json!(true));

    // Site apps
    assert!(json_data["siteApps"].is_array());
    let site_apps = json_data["siteApps"].as_array().unwrap();
    assert_eq!(site_apps.len(), 1);
    assert!(site_apps[0]["url"]
        .as_str()
        .unwrap()
        .contains("enterprise_token"));

    // Error tracking
    assert!(json_data["errorTracking"].is_object());
    assert_eq!(
        json_data["errorTracking"]["autocaptureExceptions"],
        json!(true)
    );

    Ok(())
}

/// Test config passthrough for a minimal team (all features disabled).
/// This ensures the response shape is correct even with minimal configuration.
#[tokio::test]
async fn test_config_passthrough_minimal_team() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "minimal_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert minimal config that Python would generate for a basic team
    let remote_config = json!({
        "supportedCompression": ["gzip", "gzip-js"],
        "autocapture_opt_out": true,
        "config": {
            "enable_collect_everything": true
        },
        "toolbarParams": {},
        "isAuthenticated": false,
        "defaultIdentifiedOnly": true,
        "surveys": false,
        "heatmaps": false,
        "siteApps": [],
        "elementsChainAsString": false,
        "capturePerformance": false,
        "autocaptureExceptions": false,
        "flagsPersistenceDefault": false
    });
    insert_config_in_hypercache(client.clone(), &token, remote_config).await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), Some("true"))
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;

    // Verify minimal config fields
    assert_eq!(
        json_data["supportedCompression"],
        json!(["gzip", "gzip-js"])
    );
    assert_eq!(json_data["autocapture_opt_out"], json!(true));
    assert_eq!(json_data["defaultIdentifiedOnly"], json!(true));
    assert_eq!(json_data["isAuthenticated"], json!(false));
    assert_eq!(
        json_data["config"],
        json!({"enable_collect_everything": true})
    );
    assert_eq!(json_data["toolbarParams"], json!({}));

    // All optional features should be disabled
    assert_eq!(json_data["surveys"], json!(false));
    assert_eq!(json_data["heatmaps"], json!(false));
    assert_eq!(json_data["elementsChainAsString"], json!(false));
    assert_eq!(json_data["capturePerformance"], json!(false));
    assert_eq!(json_data["autocaptureExceptions"], json!(false));
    assert_eq!(json_data["flagsPersistenceDefault"], json!(false));

    // Site apps should be empty
    assert_eq!(json_data["siteApps"], json!([]));

    // Analytics and sessionRecording should not be present (not in minimal config)
    assert!(json_data.get("analytics").is_none() || json_data["analytics"].is_null());
    assert!(json_data.get("sessionRecording").is_none() || json_data["sessionRecording"].is_null());

    Ok(())
}

/// Test that unknown fields in config are preserved during passthrough.
/// This ensures forward compatibility when Python adds new config fields.
#[tokio::test]
async fn test_config_passthrough_preserves_unknown_fields() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert config with unknown fields that Rust doesn't know about
    // This simulates Python adding new config fields before Rust is updated
    let remote_config = json!({
        "supportedCompression": ["gzip", "gzip-js"],
        "config": {},
        "futureFeature": {
            "enabled": true,
            "setting": "some_value"
        },
        "anotherNewField": ["item1", "item2"],
        "nestedUnknown": {
            "level1": {
                "level2": "deep_value"
            }
        }
    });
    insert_config_in_hypercache(client.clone(), &token, remote_config).await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), Some("true"))
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;

    // Verify unknown fields are preserved exactly
    assert_eq!(
        json_data["futureFeature"],
        json!({"enabled": true, "setting": "some_value"})
    );
    assert_eq!(json_data["anotherNewField"], json!(["item1", "item2"]));
    assert_eq!(
        json_data["nestedUnknown"]["level1"]["level2"],
        json!("deep_value")
    );

    Ok(())
}

/// Test that config cache miss returns minimal fallback config when config=true is requested.
///
/// On cache miss, the service gracefully degrades by returning a minimal config that
/// disables optional features (session recording, surveys, heatmaps, etc.) rather than
/// failing the entire request. This ensures clients always receive a valid config structure.
#[tokio::test]
async fn test_config_cache_miss_returns_minimal_fallback() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // NOTE: Intentionally NOT inserting config into hypercache

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    // Request with config=true should succeed with minimal fallback config
    let res = server
        .send_flags_request(payload.to_string(), Some("2"), Some("true"))
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;

    // Verify minimal fallback config fields are present
    assert_eq!(json_data.get("token"), Some(&json!(token)));
    assert_eq!(json_data.get("hasFeatureFlags"), Some(&json!(false))); // no flags configured
    assert_eq!(json_data.get("sessionRecording"), Some(&json!(false)));
    assert_eq!(json_data.get("surveys"), Some(&json!(false)));
    assert_eq!(json_data.get("heatmaps"), Some(&json!(false)));
    assert_eq!(json_data.get("capturePerformance"), Some(&json!(false)));
    assert_eq!(json_data.get("autocaptureExceptions"), Some(&json!(false)));
    assert_eq!(json_data.get("isAuthenticated"), Some(&json!(false)));
    assert_eq!(
        json_data.get("supportedCompression"),
        Some(&json!(["gzip", "gzip-js"]))
    );
    assert!(json_data.get("flags").is_some());

    // Request with config=false should succeed (no config needed)
    let res = server
        .send_flags_request(payload.to_string(), Some("2"), Some("false"))
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert!(json_data.get("supportedCompression").is_none());
    assert!(json_data.get("flags").is_some());

    Ok(())
}

/// Test that cache miss + quota limited scenario returns consistent response.
///
/// This verifies that when config cache misses AND session recordings are quota limited,
/// the response includes both `sessionRecording: false` (from fallback) AND `quotaLimited: ["recordings"]`.
/// The original implementation would have failed this test because cache miss returned early
/// without checking quota limits, causing an inconsistent response.
#[tokio::test]
async fn test_config_cache_miss_with_recordings_quota_limited() -> Result<()> {
    let token = "phc_test_cache_miss_quota".to_string();
    let team_id = 12345;

    // Enable session replay quota check
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.flags_session_replay_quota_check = true;

    // Set up server with mock Redis:
    // - Token is recordings-limited
    // - NO config in hypercache (will cause cache miss)
    let server = ServerHandle::for_config_with_mock_redis_and_recordings(
        config,
        vec![],              // no feature flags limited
        vec![token.clone()], // recordings limited for this token
        vec![(token.clone(), team_id)],
    )
    .await;

    let payload = json!({
        "token": token,
        "distinct_id": "user123",
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), Some("true"))
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;

    // Verify fallback config fields are present (cache miss behavior)
    assert_eq!(json_data.get("token"), Some(&json!(token)));
    assert_eq!(json_data.get("sessionRecording"), Some(&json!(false)));

    // Critical assertion: quota_limited must include "recordings"
    // This would have failed on the original implementation where cache miss
    // returned early without applying quota limits
    assert_eq!(
        json_data.get("quotaLimited"),
        Some(&json!(["recordings"])),
        "Expected quotaLimited to contain 'recordings' on cache miss + quota limited scenario"
    );

    Ok(())
}

/// Test that empty config from HyperCache is handled correctly.
#[tokio::test]
async fn test_config_cache_empty_config() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert empty config
    let remote_config = json!({});
    insert_config_in_hypercache(client.clone(), &token, remote_config).await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    // Request with config=true and empty config should succeed
    let res = server
        .send_flags_request(payload.to_string(), Some("2"), Some("true"))
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    // Empty config means no config fields, but response should still be valid
    assert!(json_data.get("flags").is_some());
    assert!(json_data.get("errorsWhileComputingFlags").is_some());

    Ok(())
}

#[tokio::test]
async fn test_disable_flags_returns_empty_response() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert a flag that would normally match
    let flag_json = json!([{
        "id": 1,
        "key": "test-flag",
        "name": "Test Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [],
                    "rollout_percentage": 100
                }
            ],
        },
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Request with disable_flags: true
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "disable_flags": true
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {},
            "featureFlagPayloads": {}
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_disable_flags_returns_empty_response_v2() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert a flag that would normally match
    let flag_json = json!([{
        "id": 1,
        "key": "test-flag",
        "name": "Test Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [],
                    "rollout_percentage": 100
                }
            ],
        },
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Request with disable_flags: true using v2 API
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "disable_flags": true
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {}
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_disable_flags_false_still_returns_flags() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert a flag that should match
    let flag_json = json!([{
        "id": 1,
        "key": "test-flag",
        "name": "Test Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [],
                    "rollout_percentage": 100
                }
            ],
        },
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Request with disable_flags: false (should still return flags)
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "disable_flags": false
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "test-flag": true
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_disable_flags_with_config_still_returns_config_data() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert a flag that would normally match
    let flag_json = json!([{
        "id": 1,
        "key": "test-flag",
        "name": "Test Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [],
                    "rollout_percentage": 100
                }
            ],
        },
    }]);

    insert_flags_for_team_in_redis(client.clone(), team.id, Some(flag_json.to_string())).await?;

    // Insert config into hypercache (required for config=true requests)
    let remote_config = json!({
        "supportedCompression": ["gzip", "gzip-js"],
        "autocapture_opt_out": false,
        "config": {
            "enable_collect_everything": true
        },
        "toolbarParams": {},
        "isAuthenticated": false,
        "defaultIdentifiedOnly": true
    });
    insert_config_in_hypercache(client.clone(), &token, remote_config).await?;

    let server = ServerHandle::for_config(config).await;

    // Request with disable_flags: true AND config: true
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "disable_flags": true
    });

    let res = server
        .send_flags_request(payload.to_string(), None, Some("true"))
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;

    // Verify flags are empty (due to disable_flags)
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {},
            "featureFlagPayloads": {}
        })
    );

    // Verify config data is still present (due to config=true)
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "supportedCompression": ["gzip", "gzip-js"],
            "autocapture_opt_out": false,
            "config": {
                "enable_collect_everything": true
            },
            "toolbarParams": {},
            "isAuthenticated": false,
            "defaultIdentifiedOnly": true
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_disable_flags_with_config_v2_still_returns_config_data() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert a flag that would normally match
    let flag_json = json!([{
        "id": 1,
        "key": "test-flag",
        "name": "Test Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [],
                    "rollout_percentage": 100
                }
            ],
        },
    }]);

    insert_flags_for_team_in_redis(client.clone(), team.id, Some(flag_json.to_string())).await?;

    // Insert config into hypercache (required for config=true requests)
    let remote_config = json!({
        "supportedCompression": ["gzip", "gzip-js"],
        "autocapture_opt_out": false,
        "config": {
            "enable_collect_everything": true
        },
        "toolbarParams": {},
        "isAuthenticated": false,
        "defaultIdentifiedOnly": true
    });
    insert_config_in_hypercache(client.clone(), &token, remote_config).await?;

    let server = ServerHandle::for_config(config).await;

    // Request with disable_flags: true AND config: true using v2 API
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "disable_flags": true
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), Some("true"))
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;

    // Verify flags are empty (due to disable_flags)
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {}
        })
    );

    // Verify config data is still present (due to config=true)
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "supportedCompression": ["gzip", "gzip-js"],
            "autocapture_opt_out": false,
            "config": {
                "enable_collect_everything": true
            },
            "toolbarParams": {},
            "isAuthenticated": false,
            "defaultIdentifiedOnly": true
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_disable_flags_without_config_param_has_minimal_response() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert a flag that would normally match
    let flag_json = json!([{
        "id": 1,
        "key": "test-flag",
        "name": "Test Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [],
                    "rollout_percentage": 100
                }
            ],
        },
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Request with disable_flags: true but NO config parameter
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "disable_flags": true
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;

    // Verify flags are empty (due to disable_flags)
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {}
        })
    );

    // Verify minimal config data (since config=true was not requested)
    // Should NOT have the full config fields like supportedCompression, etc.
    assert!(json_data.get("supportedCompression").is_none());
    assert!(json_data.get("config").is_none());
    assert!(json_data.get("toolbarParams").is_none());

    Ok(())
}

#[tokio::test]
async fn test_numeric_group_ids_work_correctly() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_with_numeric_group".to_string();
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team_id = rand::thread_rng().gen_range(1_000_000..100_000_000);
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(Some(team_id)).await.unwrap();

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await?;

    let token = team.api_token.clone();

    // Create a group with a numeric group_key (as a string in DB, but represents a number)
    context
        .create_group(
            team.id,
            "organization",
            "123",
            json!({"name": "Organization 123", "size": "large"}),
        )
        .await?;

    // Define a group-based flag with simple rollout (no property filters)
    let flags_json = json!([
        {
            "id": 1,
            "key": "numeric-group-flag",
            "name": "Flag targeting numeric group ID",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "aggregation_group_type_index": 1,
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100
                    }
                ]
            }
        }
    ]);

    insert_flags_for_team_in_redis(redis_client.clone(), team.id, Some(flags_json.to_string()))
        .await?;

    let server = ServerHandle::for_config(config).await;

    // Test with numeric group ID (integer in JSON, not string)
    {
        let payload = json!({
            "token": token,
            "distinct_id": distinct_id,
            "groups": {
                "organization": 123  // This is a JSON number, not a string
            }
        });

        let res = server
            .send_flags_request(payload.to_string(), Some("1"), None)
            .await;
        assert_eq!(res.status(), StatusCode::OK);

        let json_data = res.json::<Value>().await?;
        assert_json_include!(
            actual: json_data,
            expected: json!({
                "errorsWhileComputingFlags": false,
                "featureFlags": {
                    "numeric-group-flag": true
                }
            })
        );
    }

    // Test with string group ID (should also work)
    {
        let payload = json!({
            "token": token,
            "distinct_id": distinct_id,
            "groups": {
                "organization": "123"  // This is a JSON string
            }
        });

        let res = server
            .send_flags_request(payload.to_string(), Some("1"), None)
            .await;
        assert_eq!(res.status(), StatusCode::OK);

        let json_data = res.json::<Value>().await?;
        assert_json_include!(
            actual: json_data,
            expected: json!({
                "errorsWhileComputingFlags": false,
                "featureFlags": {
                    "numeric-group-flag": true
                }
            })
        );
    }

    // Test with different numeric group ID (should still match since we have 100% rollout)
    {
        let payload = json!({
            "token": token,
            "distinct_id": distinct_id,
            "groups": {
                "organization": 456  // Different number, but should still match due to 100% rollout
            }
        });

        let res = server
            .send_flags_request(payload.to_string(), Some("1"), None)
            .await;
        assert_eq!(res.status(), StatusCode::OK);

        let json_data = res.json::<Value>().await?;
        assert_json_include!(
            actual: json_data,
            expected: json!({
                "errorsWhileComputingFlags": false,
                "featureFlags": {
                    "numeric-group-flag": true
                }
            })
        );
    }

    // Test with float number (should also work since we convert numbers to strings)
    {
        let payload = json!({
            "token": token,
            "distinct_id": distinct_id,
            "groups": {
                "organization": 123.0  // Float that equals our integer group key
            }
        });

        let res = server
            .send_flags_request(payload.to_string(), Some("1"), None)
            .await;
        assert_eq!(res.status(), StatusCode::OK);

        let json_data = res.json::<Value>().await?;
        assert_json_include!(
            actual: json_data,
            expected: json!({
                "errorsWhileComputingFlags": false,
                "featureFlags": {
                    "numeric-group-flag": true
                }
            })
        );
    }

    Ok(())
}

#[tokio::test]
async fn test_super_condition_property_overrides_bug_fix() -> Result<()> {
    // This test specifically addresses the bug where super condition property overrides
    // were ignored when evaluating flags. The bug was that if you sent:
    // "$feature_enrollment/discussions": false
    // as an override, it would be ignored if the flag's super_groups checked for that property.

    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "super_condition_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    // Insert person with the super condition property set to true in the database
    context
        .insert_person(
            team.id,
            distinct_id.clone(),
            Some(json!({
                "$feature_enrollment/discussions": true,  // DB has it as true
                "email": "user@example.com"
            })),
        )
        .await
        .unwrap();

    // Create a flag with a super condition that checks the enrollment property
    let flag_json = json!([{
        "id": 1,
        "key": "discussions-flag",
        "name": "Discussions Feature Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [],
                    "rollout_percentage": 100
                }
            ],
            "super_groups": [{
                "properties": [{
                    "key": "$feature_enrollment/discussions",
                    "type": "person",
                    "value": ["true"],
                    "operator": "exact"
                }],
                "rollout_percentage": 100
            }]
        }
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // First, test without overrides - should be true (DB value is true)
    let payload_no_override = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload_no_override.to_string(), Some("2"), None)
        .await;

    if res.status() != StatusCode::OK {
        let status = res.status();
        let text = res.text().await?;
        panic!("Non-200 response: {status}\nBody: {text}");
    }

    let json_data = res.json::<Value>().await?;

    // Should be enabled because DB has $feature_enrollment/discussions = true
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "discussions-flag": {
                    "key": "discussions-flag",
                    "enabled": true,
                    "reason": {
                        "code": "super_condition_value"
                    }
                }
            }
        })
    );

    // Now test the key bug: override the super condition property to false
    // This should make the flag evaluate to false, respecting the override
    let payload_with_override = json!({
        "token": token,
        "distinct_id": distinct_id,
        "person_properties": {
            "$feature_enrollment/discussions": false  // Override to false
        }
    });

    let res_override = server
        .send_flags_request(payload_with_override.to_string(), Some("2"), None)
        .await;

    if res_override.status() != StatusCode::OK {
        let status = res_override.status();
        let text = res_override.text().await?;
        panic!("Non-200 response: {status}\nBody: {text}");
    }

    let json_override = res_override.json::<Value>().await?;

    // This is the key test: the flag should now be false because we overrode
    // the super condition property. Before our fix, this would incorrectly be true
    // because the override was ignored.
    assert_json_include!(
        actual: json_override,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "discussions-flag": {
                    "key": "discussions-flag",
                    "enabled": false  // Should be false due to the override
                }
            }
        })
    );

    // Test the reverse: override to true when DB has false
    // First update DB to have false
    context
        .insert_person(
            team.id,
            "another_user".to_string(),
            Some(json!({
                "$feature_enrollment/discussions": false,  // DB has it as false
                "email": "another@example.com"
            })),
        )
        .await
        .unwrap();

    let payload_reverse_override = json!({
        "token": token,
        "distinct_id": "another_user",
        "person_properties": {
            "$feature_enrollment/discussions": true  // Override to true
        }
    });

    let res_reverse = server
        .send_flags_request(payload_reverse_override.to_string(), Some("2"), None)
        .await;

    if res_reverse.status() != StatusCode::OK {
        let status = res_reverse.status();
        let text = res_reverse.text().await?;
        panic!("Non-200 response: {status}\nBody: {text}");
    }

    let json_reverse = res_reverse.json::<Value>().await?;

    // Should be enabled because we overrode the property to true
    assert_json_include!(
        actual: json_reverse,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "discussions-flag": {
                    "key": "discussions-flag",
                    "enabled": true,  // Should be true due to the override
                    "reason": {
                        "code": "super_condition_value"
                    }
                }
            }
        })
    );

    // This test verifies that our fix properly merges super condition property overrides
    // with cached properties, ensuring that overrides take precedence over DB values.

    Ok(())
}

#[tokio::test]
async fn test_property_override_bug_real_scenario() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "test_real_bug".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    // Insert person with TWO properties in the database
    context
        .insert_person(
            team.id,
            distinct_id.clone(),
            Some(json!({
                "plan": "premium",  // Flag will check this property
                "$feature_enrollment/discussions": true,  // We'll override this property
                "email": "user@example.com"
            })),
        )
        .await
        .unwrap();

    // Create two flags:
    // 1. Flag that checks "plan" property (should be true with DB value)
    // 2. Flag that checks "$feature_enrollment/discussions" property (should respect override)
    let flag_json = json!([
        {
            "id": 1,
            "key": "plan-flag",
            "name": "Flag that checks plan",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "plan",
                                "value": "premium",
                                "operator": "exact",
                                "type": "person"
                            }
                        ],
                        "rollout_percentage": 100
                    }
                ],
            },
        },
        {
            "id": 2,
            "key": "discussions-flag",
            "name": "Flag that checks discussions enrollment",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "$feature_enrollment/discussions",
                                "value": "true",
                                "operator": "exact",
                                "type": "person"
                            }
                        ],
                        "rollout_percentage": 100
                    }
                ],
            },
        }
    ]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Send override for ONLY the discussions property, not the plan property
    // This is the real bug scenario: overriding a property that only ONE flag checks
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "person_properties": {
            "$feature_enrollment/discussions": false  // Override to false, but flag expects true
        }
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;

    if res.status() != StatusCode::OK {
        let status = res.status();
        let text = res.text().await?;
        panic!("Non-200 response: {status}\nBody: {text}");
    }

    let json_data = res.json::<Value>().await?;

    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "plan-flag": {
                    "key": "plan-flag",
                    "enabled": true,  // Should be true from DB value
                    "reason": {
                        "code": "condition_match",
                        "condition_index": 0
                    }
                },
                "discussions-flag": {
                    "key": "discussions-flag",
                    "enabled": false,  // Should be false from override
                    "reason": {
                        "code": "no_condition_match"
                    }
                }
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_super_condition_with_cohort_filters() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "super_condition_cohort_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    // Insert person with the super condition property
    context
        .insert_person(
            team.id,
            distinct_id.clone(),
            Some(json!({
                "$feature_enrollment/discussions": false,  // Super condition property in DB
                "email": "user@example.com"
            })),
        )
        .await
        .unwrap();

    // Create a flag that matches your production example:
    // - Has a super condition that checks "$feature_enrollment/discussions"
    // - Has a regular condition with a cohort filter
    let flag_json = json!([{
        "id": 1,
        "key": "discussions-with-cohort",
        "name": "Discussions with Cohort Filter",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [{
                "variant": null,
                "properties": [{
                    "key": "id",
                    "type": "cohort",
                    "value": 98  // Cohort filter that requires DB lookup
                }],
                "rollout_percentage": 100
            }],
            "payloads": {},
            "multivariate": null,
            "super_groups": [{
                "properties": [{
                    "key": "$feature_enrollment/discussions",
                    "type": "person",
                    "value": ["true"],
                    "operator": "exact"
                }],
                "rollout_percentage": 100
            }]
        }
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Test WITHOUT overrides first - should evaluate super condition using DB value (false)
    let payload_no_override = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload_no_override.to_string(), Some("2"), None)
        .await;

    if res.status() != StatusCode::OK {
        let status = res.status();
        let text = res.text().await?;
        panic!("Non-200 response: {status}\nBody: {text}");
    }

    let json_data = res.json::<Value>().await?;

    // Should be disabled because DB has $feature_enrollment/discussions = false
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "discussions-with-cohort": {
                    "key": "discussions-with-cohort",
                    "enabled": false
                }
            }
        })
    );

    // Now test WITH override - this is the key scenario that was broken
    // We override the super condition property to true, but the flag also has cohort filters
    // Before the fix: super condition evaluation would see the cohort filter and fall back to DB
    // After the fix: super condition evaluation only looks at super condition properties
    let payload_with_override = json!({
        "token": token,
        "distinct_id": distinct_id,
        "person_properties": {
            "$feature_enrollment/discussions": true  // Override super condition property to true
        }
    });

    let res_override = server
        .send_flags_request(payload_with_override.to_string(), Some("2"), None)
        .await;

    if res_override.status() != StatusCode::OK {
        let status = res_override.status();
        let text = res_override.text().await?;
        panic!("Non-200 response: {status}\nBody: {text}");
    }

    let json_override = res_override.json::<Value>().await?;

    // This is the key test: the flag should now be enabled because:
    // 1. Super condition can be evaluated from override (discussions = true)
    // 2. Super condition matches, so we return early with super_condition_value
    // 3. We don't even need to evaluate the cohort filter in the regular condition
    assert_json_include!(
        actual: json_override,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "discussions-with-cohort": {
                    "key": "discussions-with-cohort",
                    "enabled": true,
                    "reason": {
                        "code": "super_condition_value"
                    }
                }
            }
        })
    );

    // Test the reverse: override to false
    let payload_false_override = json!({
        "token": token,
        "distinct_id": distinct_id,
        "person_properties": {
            "$feature_enrollment/discussions": false  // Override to false
        }
    });

    let res_false = server
        .send_flags_request(payload_false_override.to_string(), Some("2"), None)
        .await;

    if res_false.status() != StatusCode::OK {
        let status = res_false.status();
        let text = res_false.text().await?;
        panic!("Non-200 response: {status}\nBody: {text}");
    }

    let json_false = res_false.json::<Value>().await?;

    // Should be disabled because super condition doesn't match
    assert_json_include!(
        actual: json_false,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "discussions-with-cohort": {
                    "key": "discussions-with-cohort",
                    "enabled": false
                }
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_returns_empty_flags_when_no_active_flags_configured() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert flags that should be filtered out (deleted and inactive)
    let flag_json = json!([
        {
            "id": 1,
            "key": "deleted_flag",
            "name": "Deleted Flag",
            "active": true,
            "deleted": true,  // This flag should be filtered out
            "team_id": team.id,
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100
                    }
                ],
            },
        },
        {
            "id": 2,
            "key": "inactive_flag",
            "name": "Inactive Flag",
            "active": false,  // This flag should be filtered out
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100
                    }
                ],
            },
        },
        {
            "id": 3,
            "key": "both_inactive_and_deleted",
            "name": "Both Inactive and Deleted Flag",
            "active": false,  // This flag should be filtered out
            "deleted": true,  // This flag should be filtered out
            "team_id": team.id,
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100
                    }
                ],
            },
        }
    ]);

    insert_flags_for_team_in_redis(client.clone(), team.id, Some(flag_json.to_string())).await?;

    // Insert config into hypercache (required for config=true requests)
    let remote_config = json!({
        "supportedCompression": ["gzip", "gzip-js"],
        "autocapture_opt_out": false,
        "config": {
            "enable_collect_everything": true
        },
        "toolbarParams": {},
        "isAuthenticated": false,
        "defaultIdentifiedOnly": true
    });
    insert_config_in_hypercache(client.clone(), &token, remote_config).await?;

    let server = ServerHandle::for_config(config).await;

    // Test legacy response (no version param)
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {}
        })
    );

    // Test v2 response (version=2)
    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {}
        })
    );

    // Test with config=true to ensure config is still returned
    let res = server
        .send_flags_request(payload.to_string(), Some("2"), Some("true"))
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {},
            "supportedCompression": ["gzip", "gzip-js"],
            "autocapture_opt_out": false,
            "config": {
                "enable_collect_everything": true
            },
            "toolbarParams": {},
            "isAuthenticated": false,
            "defaultIdentifiedOnly": true
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_group_key_property_matching() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(Some(team.id)).await.unwrap();
    let token = team.api_token.clone();

    // Create a flag that filters on $group_key property
    let flag_json = json!([{
        "id": 1,
        "key": "group-key-flag",
        "name": "Group Key Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "properties": [
                        {
                            "key": "$group_key",
                            "value": "test_company_id",
                            "operator": "exact",
                            "type": "group",
                            "group_type_index": 0
                        }
                    ],
                    "rollout_percentage": 100
                }
            ],
            "aggregation_group_type_index": 0
        },
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Test with group_key that should match the filter
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "groups": {
            "project": "test_company_id"
        }
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;

    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "group-key-flag": true
            }
        })
    );

    // Test with non-matching group key
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "groups": {
            "project": "wrong_company_id"
        }
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;

    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "group-key-flag": false
            }
        })
    );

    // Test with missing groups entirely
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;

    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "group-key-flag": false
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_cohort_filter_with_regex_and_negation() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "test.user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None);
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    // Insert person with the target email that should match the cohort
    context
        .insert_person(
            team.id,
            distinct_id.clone(),
            Some(json!({"email": "test.user@example.com"})),
        )
        .await
        .unwrap();

    // Create the cohort with the specified filters:
    // OR condition with AND group that checks:
    // - email matches regex ^.*@example.com$ (ends with @example.com)
    // - email does NOT contain "excluded.user@example.com" (negation: true)
    let cohort_filters = json!({
        "properties": {
            "type": "OR",
            "values": [{
                "type": "AND",
                "values": [
                    {
                        "key": "email",
                        "type": "person",
                        "value": "^.*@example.com$",
                        "negation": false,
                        "operator": "regex"
                    },
                    {
                        "key": "email",
                        "type": "person",
                        "value": "excluded.user@example.com",
                        "negation": true,
                        "operator": "icontains"
                    }
                ]
            }]
        }
    });

    // Create the cohort in the database
    let mut conn = pg_client.get_connection().await.unwrap();
    let cohort_id: i32 = sqlx::query_scalar(
        r#"INSERT INTO posthog_cohort
           (name, description, team_id, deleted, filters, is_calculating, created_by_id, created_at, is_static, last_calculation, errors_calculating, groups, version)
           VALUES ($1, $2, $3, false, $4, false, NULL, NOW(), false, NOW(), 0, '[]', NULL)
           RETURNING id"#,
    )
    .bind("Example Domain (excluding specific user)")
    .bind("Test cohort for regex and negation conditions")
    .bind(team.id)
    .bind(cohort_filters)
    .fetch_one(&mut *conn)
    .await
    .unwrap();

    // Create flag with cohort filter exactly as specified
    let flag_json = json!([{
        "id": 1,
        "key": "example-cohort-flag",
        "name": "Example Cohort Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [{
                "variant": null,
                "properties": [{
                    "key": "id",
                    "type": "cohort",
                    "value": cohort_id,
                    "operator": "in",
                    "cohort_name": "Example Domain (excluding specific user)"
                }],
                "rollout_percentage": 100
            }],
            "payloads": {},
            "multivariate": null
        }
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Test with test.user@example.com - should match cohort and return true
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "example-cohort-flag": {
                    "key": "example-cohort-flag",
                    "enabled": true,
                    "reason": {
                        "code": "condition_match",
                        "condition_index": 0
                    }
                }
            }
        })
    );

    // Test with excluded.user@example.com - should NOT match cohort due to negation condition
    let excluded_distinct_id = "excluded.user".to_string();
    context
        .insert_person(
            team.id,
            excluded_distinct_id.clone(),
            Some(json!({"email": "excluded.user@example.com"})),
        )
        .await
        .unwrap();

    let payload_excluded = json!({
        "token": token,
        "distinct_id": excluded_distinct_id,
    });

    let res_excluded = server
        .send_flags_request(payload_excluded.to_string(), Some("2"), None)
        .await;
    assert_eq!(StatusCode::OK, res_excluded.status());

    let json_excluded = res_excluded.json::<Value>().await?;
    assert_json_include!(
        actual: json_excluded,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "example-cohort-flag": {
                    "key": "example-cohort-flag",
                    "enabled": false,
                    "reason": {
                        "code": "no_condition_match"
                    }
                }
            }
        })
    );

    // Test with non-example.com email - should NOT match cohort due to regex condition
    let non_example_distinct_id = "other.user".to_string();
    context
        .insert_person(
            team.id,
            non_example_distinct_id.clone(),
            Some(json!({"email": "other.user@other.com"})),
        )
        .await
        .unwrap();

    let payload_non_example = json!({
        "token": token,
        "distinct_id": non_example_distinct_id,
    });

    let res_non_example = server
        .send_flags_request(payload_non_example.to_string(), Some("2"), None)
        .await;
    assert_eq!(StatusCode::OK, res_non_example.status());

    let json_non_example = res_non_example.json::<Value>().await?;
    assert_json_include!(
        actual: json_non_example,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "example-cohort-flag": {
                    "key": "example-cohort-flag",
                    "enabled": false,
                    "reason": {
                        "code": "no_condition_match"
                    }
                }
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_flag_keys_should_include_dependency_graph() -> Result<()> {
    // This test is to ensure that when flag_keys is specified, the dependency graph is included in the response
    // For example, if parent_flag -> intermediate_flag -> leaf_flag, and we only request parent_flag,
    // we should get the response for parent_flag, intermediate_flag, and leaf_flag otherwise parent_flag can't be evaluated.

    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    const LEAF_FLAG_ID: i32 = 1;
    const INTERMEDIATE_FLAG_ID: i32 = 2;
    const PARENT_FLAG_ID: i32 = 3;
    const INDEPENDENT_FLAG_ID: i32 = 4;

    // Create a dependency chain: parent_flag -> intermediate_flag -> leaf_flag
    // parent_flag depends on intermediate_flag being true
    // intermediate_flag depends on leaf_flag being true
    let flag_json = json!([
        {
            "id": LEAF_FLAG_ID,
            "key": "leaf_flag",
            "name": "Leaf Flag",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "test@example.com",
                                "operator": "exact",
                                "type": "person"
                            }
                        ],
                        "rollout_percentage": 100
                    }
                ]
            }
        },
        {
            "id": INTERMEDIATE_FLAG_ID,
            "key": "intermediate_flag",
            "name": "Intermediate Flag",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": LEAF_FLAG_ID.to_string(),
                                "value": true,
                                "operator": "flag_evaluates_to",
                                "type": "flag"
                            }
                        ],
                        "rollout_percentage": 100
                    }
                ]
            }
        },
        {
            "id": PARENT_FLAG_ID,
            "key": "parent_flag",
            "name": "Parent Flag",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": INTERMEDIATE_FLAG_ID.to_string(),
                                "value": true,
                                "operator": "flag_evaluates_to",
                                "type": "flag"
                            }
                        ],
                        "rollout_percentage": 100
                    }
                ]
            }
        },
        {
            "id": INDEPENDENT_FLAG_ID,
            "key": "independent_flag",
            "name": "Independent Flag",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 50
                    }
                ]
            }
        }
    ]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Test 1: Request only parent_flag with flag_keys where the whole chain evaluates to true because the leaf_flag is true
    {
        let payload = json!({
            "token": token,
            "distinct_id": distinct_id,
            "flag_keys": ["parent_flag"],
            "person_properties": {
                "email": "test@example.com"
            }
        });
        let res = server
            .send_flags_request(payload.to_string(), Some("2"), None)
            .await;
        assert_eq!(StatusCode::OK, res.status());
        let json_data = res.json::<Value>().await?;
        println!(
            "Test 1 - Actual response: {}",
            serde_json::to_string_pretty(&json_data).unwrap()
        );
        assert_json_include!(
            actual: json_data,
            expected: json!({
                "errorsWhileComputingFlags": false,
                "flags": {
                    "parent_flag": {
                        "key": "parent_flag",
                        "enabled": true,
                        "reason": {
                            "code": "condition_match",
                            "condition_index": 0
                        }
                    },
                    "intermediate_flag": {
                        "key": "intermediate_flag",
                        "enabled": true,
                        "reason": {
                            "code": "condition_match",
                            "condition_index": 0
                        }
                    },
                    "leaf_flag": {
                        "key": "leaf_flag",
                        "enabled": true,
                        "reason": {
                            "code": "condition_match",
                            "condition_index": 0
                        }
                    }
                }
            })
        );
    }

    // Test 2: Request only parent_flag with flag_keys where the whole chain evaluates to false because the leaf_flag is false
    {
        let payload = json!({
            "token": token,
            "distinct_id": distinct_id,
            "flag_keys": ["parent_flag"],
            "person_properties": {
                "email": "not-test@example.com"
            }
        });
        let res = server
            .send_flags_request(payload.to_string(), Some("2"), None)
            .await;
        assert_eq!(StatusCode::OK, res.status());
        let json_data = res.json::<Value>().await?;
        println!(
            "Test 2 - Actual response: {}",
            serde_json::to_string_pretty(&json_data).unwrap()
        );
        assert_json_include!(
            actual: json_data,
            expected: json!({
                "errorsWhileComputingFlags": false,
                "flags": {
                    "parent_flag": {
                        "key": "parent_flag",
                        "enabled": false,
                        "reason": {
                            "code": "no_condition_match",
                            "condition_index": 0
                        }
                    },
                    "intermediate_flag": {
                        "key": "intermediate_flag",
                        "enabled": false,
                        "reason": {
                            "code": "no_condition_match",
                            "condition_index": 0
                        }
                    },
                    "leaf_flag": {
                        "key": "leaf_flag",
                        "enabled": false,
                        "reason": {
                            "code": "no_condition_match",
                            "condition_index": 0
                        }
                    }
                }
            })
        );
    }

    Ok(())
}

#[tokio::test]
async fn test_flag_keys_to_evaluate_parameter() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert multiple flags for the team
    let flags = json!([
        {
            "id": 1,
            "key": "flag1",
            "name": "Flag 1",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100
                    }
                ]
            }
        },
        {
            "id": 2,
            "key": "flag2",
            "name": "Flag 2",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100
                    }
                ]
            }
        },
        {
            "id": 3,
            "key": "flag3",
            "name": "Flag 3",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100
                    }
                ]
            }
        }
    ]);

    insert_flags_for_team_in_redis(client.clone(), team.id, Some(flags.to_string()))
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;

    // Test 1: Using flag_keys parameter (currently works)
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "flag_keys": ["flag1", "flag3"]
    });

    let response = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;

    assert_eq!(response.status(), StatusCode::OK);
    let response_json: LegacyFlagsResponse = response.json().await?;

    assert_eq!(response_json.feature_flags.len(), 2);
    assert!(response_json.feature_flags.contains_key("flag1"));
    assert!(response_json.feature_flags.contains_key("flag3"));
    assert!(!response_json.feature_flags.contains_key("flag2"));

    // Test 2: Using flag_keys_to_evaluate parameter (should work after fix)
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "flag_keys_to_evaluate": ["flag2", "flag3"]
    });

    let response = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;

    assert_eq!(response.status(), StatusCode::OK);
    let response_json: LegacyFlagsResponse = response.json().await?;

    // This test should fail until we add the alias
    assert_eq!(
        response_json.feature_flags.len(),
        2,
        "flag_keys_to_evaluate should filter flags"
    );
    assert!(response_json.feature_flags.contains_key("flag2"));
    assert!(response_json.feature_flags.contains_key("flag3"));
    assert!(!response_json.feature_flags.contains_key("flag1"));

    Ok(())
}

#[tokio::test]
async fn it_handles_empty_query_parameters() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert config into hypercache (required for default config=true requests)
    let remote_config = json!({
        "supportedCompression": ["gzip", "gzip-js"],
        "config": {}
    });
    insert_config_in_hypercache(client.clone(), &token, remote_config).await?;

    let server = ServerHandle::for_config(config).await;

    // Create a request with empty query parameters
    let reqwest_client = reqwest::Client::new();
    let response = reqwest_client
        .post(format!(
            "http://{}/flags/?v=&ip=&_=&ver=&compression=",
            server.addr
        ))
        .header("Content-Type", "application/json")
        .body(format!(
            r#"{{"token": "{token}", "distinct_id": "{distinct_id}"}}"#
        ))
        .send()
        .await?;

    assert_eq!(
        response.status(),
        200,
        "Empty query params should be handled gracefully"
    );

    let response_text = response.text().await?;
    let response_json: serde_json::Value = serde_json::from_str(&response_text)?;

    assert!(
        response_json.get("flags").is_some(),
        "Response should contain flags field"
    );

    Ok(())
}

#[tokio::test]
async fn it_handles_boolean_query_params_as_truthy() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    context
        .insert_person(team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert config into hypercache (required for config=true requests)
    let remote_config = json!({
        "supportedCompression": ["gzip", "gzip-js"],
        "config": {}
    });
    insert_config_in_hypercache(client.clone(), &token, remote_config).await?;

    let server = ServerHandle::for_config(config).await;

    // Test various boolean parameter formats
    let test_cases = vec![
        ("config=", "config with empty value should be truthy"),
        ("config=true", "config=true should be truthy"),
        ("config=1", "config=1 should be truthy"),
    ];

    for (query_param, description) in test_cases {
        let reqwest_client = reqwest::Client::new();
        let response = reqwest_client
            .post(format!("http://{}/flags/?{query_param}", server.addr))
            .header("Content-Type", "application/json")
            .body(format!(
                r#"{{"token": "{token}", "distinct_id": "{distinct_id}"}}"#
            ))
            .send()
            .await?;

        assert_eq!(
            response.status(),
            200,
            "{description}: request should succeed"
        );

        let response_json: serde_json::Value = response.json().await?;

        // When config=true or config=, we should get config fields in response
        if query_param.starts_with("config") {
            assert!(
                response_json.get("config").is_some(),
                "{description}: config field should be present"
            );
        }
    }

    // Test config=false should NOT include config fields
    let reqwest_client = reqwest::Client::new();
    let response = reqwest_client
        .post(format!("http://{}/flags/?config=false", server.addr))
        .header("Content-Type", "application/json")
        .body(format!(
            r#"{{"token": "{token}", "distinct_id": "{distinct_id}"}}"#
        ))
        .send()
        .await?;

    assert_eq!(
        response.status(),
        200,
        "config=false request should succeed"
    );
    let response_json: serde_json::Value = response.json().await?;

    // Config fields should not be present when config=false
    assert!(
        response_json.get("config").is_none(),
        "config fields should not be present when config=false"
    );

    Ok(())
}

#[tokio::test]
async fn test_nested_cohort_targeting_with_days_since_paid_plan() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "test_user_with_77_days".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None);
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    // Insert person with production-like data - should match via days_since_paid_plan_start condition
    context
        .insert_person(
            team.id,
            distinct_id.clone(),
            Some(json!({
                "name": "Test User",
                "email": "test@example.com",
                "org_id": "test-org-123", // Not in the allowed org list
                "user_id": "test-user-456",
                "days_since_paid_plan_start": 77, // < 365, should match this condition
                "created_at_timestamp": 1747758893, // Set, would match this condition
                "upgraded_at_timestamp": 1749058908, // Has upgrade timestamp - fails the not_regex condition in cohort 128293
                "paid_plan_start_date": "2025-06-04",
                "trial_start_date": "2025-05-20"
            })),
        )
        .await
        .unwrap();

    let mut conn = pg_client.get_connection().await.unwrap();

    // Create first cohort (ID 128293) - users without upgraded_at_timestamp but with created_at_timestamp
    let cohort_128293_filters = json!({
        "properties": {
            "type": "AND",
            "values": [
                {
                    "type": "OR",
                    "values": [{
                        "key": "upgraded_at_timestamp",
                        "type": "person",
                        "value": ".+",
                        "negation": false,
                        "operator": "not_regex"
                    }]
                },
                {
                    "type": "AND",
                    "values": [{
                        "key": "created_at_timestamp",
                        "type": "person",
                        "value": ".+",
                        "negation": false,
                        "operator": "is_set"
                    }]
                }
            ]
        }
    });

    let cohort_128293_id: i32 = sqlx::query_scalar(
        r#"INSERT INTO posthog_cohort
           (name, description, team_id, deleted, filters, is_calculating, created_by_id, created_at, is_static, last_calculation, errors_calculating, groups, version)
           VALUES ($1, $2, $3, false, $4, false, NULL, NOW(), false, NOW(), 0, '[]', NULL)
           RETURNING id"#,
    )
    .bind("Base Cohort 128293")
    .bind("Users without upgraded_at_timestamp but with created_at_timestamp")
    .bind(team.id)
    .bind(cohort_128293_filters)
    .fetch_one(&mut *conn)
    .await
    .unwrap();

    // Create second cohort (ID 128397) - Session Recordings Enabled cohort that references the first cohort
    let cohort_128397_filters = json!({
        "properties": {
            "type": "OR",
            "values": [
                {
                    "type": "OR",
                    "values": [{
                        "key": "org_id",
                        "type": "person",
                        "value": ["67756", "67454", "56258", "59205", "36297"],
                        "negation": false,
                        "operator": "exact"
                    }]
                },
                {
                    "type": "OR",
                    "values": [{
                        "key": "days_since_paid_plan_start",
                        "type": "person",
                        "value": "365",
                        "negation": false,
                        "operator": "lt"
                    }]
                },
                {
                    "type": "OR",
                    "values": [{
                        "key": "id",
                        "type": "cohort",
                        "value": cohort_128293_id,
                        "negation": false
                    }]
                }
            ]
        }
    });

    let cohort_128397_id: i32 = sqlx::query_scalar(
        r#"INSERT INTO posthog_cohort
           (name, description, team_id, deleted, filters, is_calculating, created_by_id, created_at, is_static, last_calculation, errors_calculating, groups, version)
           VALUES ($1, $2, $3, false, $4, false, NULL, NOW(), false, NOW(), 0, '[]', NULL)
           RETURNING id"#,
    )
    .bind("Session Recordings Enabled")
    .bind("Cohort with multiple OR conditions including nested cohort reference")
    .bind(team.id)
    .bind(cohort_128397_filters)
    .fetch_one(&mut *conn)
    .await
    .unwrap();

    // Create feature flag (ID 124068) that targets the Session Recordings Enabled cohort
    let flag_json = json!([{
        "id": 124068,
        "key": "session-recordings-flag",
        "name": "Session Recordings Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [{
                "variant": null,
                "properties": [{
                    "key": "id",
                    "type": "cohort",
                    "value": cohort_128397_id,
                    "operator": "in",
                    "cohort_name": "Session Recordings Enabled"
                }],
                "rollout_percentage": 100
            }],
            "payloads": {},
            "multivariate": null
        }
    }]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Test with production-like user data - SHOULD match because days_since_paid_plan_start = 77 < 365 (OR condition)
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "session-recordings-flag": {
                    "key": "session-recordings-flag",
                    "enabled": true,
                    "reason": {
                        "code": "condition_match",
                        "condition_index": 0
                    }
                }
            }
        })
    );

    // Test with user who SHOULD match - has low days_since_paid_plan_start and no upgraded_at_timestamp
    let matching_distinct_id = "matching_user".to_string();
    context
        .insert_person(
            team.id,
            matching_distinct_id.clone(),
            Some(json!({
                "days_since_paid_plan_start": 200, // < 365, matches this condition
                "created_at_timestamp": 1747758893,
                "org_id": "12345" // Not in special list, but should match via days condition
                // No upgraded_at_timestamp - this allows them to match base cohort 128293
            })),
        )
        .await
        .unwrap();

    let matching_payload = json!({
        "token": token,
        "distinct_id": matching_distinct_id,
    });

    let matching_res = server
        .send_flags_request(matching_payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(StatusCode::OK, matching_res.status());

    let matching_json = matching_res.json::<Value>().await?;
    assert_json_include!(
        actual: matching_json,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "session-recordings-flag": {
                    "key": "session-recordings-flag",
                    "enabled": true,
                    "reason": {
                        "code": "condition_match",
                        "condition_index": 0
                    }
                }
            }
        })
    );

    // Test with user who should NOT match the cohort - high days_since_paid_plan_start and has upgraded_at_timestamp
    let failing_distinct_id = "failing_user".to_string();
    context
        .insert_person(
            team.id,
            failing_distinct_id.clone(),
            Some(json!({
                "days_since_paid_plan_start": "500", // > 365, fails the lt condition
                "created_at_timestamp": "2024-01-01T00:00:00Z",
                "upgraded_at_timestamp": "2024-02-01T00:00:00Z", // has upgrade timestamp, fails the not_regex condition
                "org_id": "99999" // not in the specific org_id list
            })),
        )
        .await
        .unwrap();

    let failing_payload = json!({
        "token": token,
        "distinct_id": failing_distinct_id,
    });

    let failing_res = server
        .send_flags_request(failing_payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(StatusCode::OK, failing_res.status());

    let failing_json = failing_res.json::<Value>().await?;
    assert_json_include!(
        actual: failing_json,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "session-recordings-flag": {
                    "key": "session-recordings-flag",
                    "enabled": false,
                    "reason": {
                        "code": "no_condition_match"
                    }
                }
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_empty_distinct_id_flag_matching() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    // Create multiple flags with different matching conditions
    let flags_json = json!([
        {
            "id": 1,
            "key": "always-on-flag",
            "name": "Always On Flag",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [{
                    "properties": [],
                    "rollout_percentage": 100
                }]
            }
        },
        {
            "id": 2,
            "key": "property-match-flag",
            "name": "Property Match Flag",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [{
                    "properties": [{
                        "key": "country",
                        "type": "person",
                        "value": "US",
                        "operator": "exact"
                    }],
                    "rollout_percentage": 100
                }]
            }
        },
        {
            "id": 3,
            "key": "email-regex-flag",
            "name": "Email Regex Flag",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [{
                    "properties": [{
                        "key": "email",
                        "type": "person",
                        "value": "@example.com",
                        "operator": "regex"
                    }],
                    "rollout_percentage": 100
                }]
            }
        },
        {
            "id": 4,
            "key": "premium-user-flag",
            "name": "Premium User Flag",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [{
                    "properties": [{
                        "key": "premium_user",
                        "type": "person",
                        "value": true,
                        "operator": "exact"
                    }],
                    "rollout_percentage": 100
                }]
            }
        },
        {
            "id": 5,
            "key": "rollout-percentage-flag",
            "name": "50% Rollout Flag",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [{
                    "properties": [],
                    "rollout_percentage": 50
                }]
            }
        },
        {
            "id": 6,
            "key": "multivariate-flag",
            "name": "Multivariate Flag",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [{
                    "properties": [],
                    "rollout_percentage": 100
                }],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control",
                            "rollout_percentage": 33
                        },
                        {
                            "key": "test",
                            "name": "Test",
                            "rollout_percentage": 33
                        },
                        {
                            "key": "other",
                            "name": "Other",
                            "rollout_percentage": 34
                        }
                    ]
                }
            }
        }
    ]);

    insert_flags_for_team_in_redis(client.clone(), team.id, Some(flags_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Test with empty string distinct ID
    let payload = json!({
        "token": token,
        "distinct_id": "",  // Empty distinct ID in the request
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;

    assert_eq!(res.status(), StatusCode::OK);
    let json_data = res.json::<Value>().await?;

    // Verify that flags are actually evaluated, not just all returning false
    // For empty distinct IDs with no person properties, only non-property-based flags should match
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                // Always-on flag should be true for everyone, even empty distinct IDs
                "always-on-flag": {
                    "key": "always-on-flag",
                    "enabled": true
                },
                // Property match flags should be false (no person properties)
                "property-match-flag": {
                    "key": "property-match-flag",
                    "enabled": false  // No person properties
                },
                "email-regex-flag": {
                    "key": "email-regex-flag",
                    "enabled": false  // No email property
                },
                "premium-user-flag": {
                    "key": "premium-user-flag",
                    "enabled": false  // No premium_user property
                }
            }
        })
    );

    // Check that rollout percentage flag returns a consistent result
    // (should be deterministic based on the empty distinct ID hash)
    let rollout_flag = json_data["flags"]["rollout-percentage-flag"]["enabled"].as_bool();
    assert!(
        rollout_flag.is_some(),
        "Rollout flag should have a boolean value"
    );

    // Check that multivariate flag returns a variant
    let multivariate_flag = &json_data["flags"]["multivariate-flag"];
    assert!(
        multivariate_flag["enabled"].as_bool().unwrap_or(false),
        "Multivariate flag should be enabled"
    );
    assert!(
        multivariate_flag["variant"].is_string(),
        "Multivariate flag should return a variant for empty distinct ID"
    );

    // Test consistency: Make the same request again and verify we get the same results
    let res2 = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;

    assert_eq!(res2.status(), StatusCode::OK);
    let json_data2 = res2.json::<Value>().await?;

    // Rollout percentage should be consistent
    assert_eq!(
        json_data["flags"]["rollout-percentage-flag"]["enabled"],
        json_data2["flags"]["rollout-percentage-flag"]["enabled"],
        "Rollout percentage should be consistent for the same (empty) distinct ID"
    );

    // Multivariate variant should be consistent
    assert_eq!(
        json_data["flags"]["multivariate-flag"]["variant"],
        json_data2["flags"]["multivariate-flag"]["variant"],
        "Multivariate variant should be consistent for the same (empty) distinct ID"
    );

    // Test with empty distinct ID but with person properties provided in the request
    let payload_with_props = json!({
        "token": token,
        "distinct_id": "",  // Still empty distinct ID
        // Include some person properties in the request
        "person_properties": {
            "country": "US",
            "email": "user@test.org",
            "premium_user": false
        }
    });

    let res3 = server
        .send_flags_request(payload_with_props.to_string(), Some("2"), None)
        .await;

    assert_eq!(res3.status(), StatusCode::OK);
    let json_data3 = res3.json::<Value>().await?;

    // Always-on flag should still work
    assert_json_include!(
        actual: json_data3,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "always-on-flag": {
                    "key": "always-on-flag",
                    "enabled": true
                },
                // Property flags should evaluate based on provided properties
                "property-match-flag": {
                    "key": "property-match-flag",
                    "enabled": true
                },
                "premium-user-flag": {
                    "key": "premium-user-flag",
                    "enabled": false  // premium_user is false
                }
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_cohort_with_and_negated_cohort_condition() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "test_user_and_cohort".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None);
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    // Insert person with email matching our target pattern
    context
        .insert_person(
            team.id,
            distinct_id.clone(),
            Some(json!({
                "email": "engineer@posthog.com"
            })),
        )
        .await
        .unwrap();

    let mut conn = pg_client.get_connection().await.unwrap();

    // Create cohort 1001: matches "admin@posthog.com" (for exclusion)
    let excluded_cohort_filters = json!({
        "properties": {
            "type": "OR",
            "values": [{
                "type": "OR",
                "values": [{
                    "key": "email",
                    "type": "person",
                    "value": "admin@posthog.com",
                    "negation": false,
                    "operator": "exact"
                }]
            }]
        }
    });

    let excluded_cohort_id: i32 = sqlx::query_scalar(
        r#"INSERT INTO posthog_cohort
           (name, description, team_id, deleted, filters, is_calculating, created_by_id, created_at, is_static, last_calculation, errors_calculating, groups, version)
           VALUES ($1, $2, $3, false, $4, false, NULL, NOW(), false, NOW(), 0, '[]', NULL)
           RETURNING id"#,
    )
    .bind("Admin Users")
    .bind("Matches admin@posthog.com")
    .bind(team.id)
    .bind(excluded_cohort_filters)
    .fetch_one(&mut *conn)
    .await?;

    // Create cohort 1002: matches "@posthog.com" AND NOT in excluded cohort
    let main_cohort_filters = json!({
        "properties": {
            "type": "OR",
            "values": [{
                "type": "AND",
                "values": [
                    {
                        "key": "email",
                        "type": "person",
                        "value": "@posthog.com",
                        "negation": false,
                        "operator": "regex"
                    },
                    {
                        "key": "id",
                        "type": "cohort",
                        "value": excluded_cohort_id,
                        "negation": true
                    }
                ]
            }]
        }
    });

    let main_cohort_id: i32 = sqlx::query_scalar(
        r#"INSERT INTO posthog_cohort
           (name, description, team_id, deleted, filters, is_calculating, created_by_id, created_at, is_static, last_calculation, errors_calculating, groups, version)
           VALUES ($1, $2, $3, false, $4, false, NULL, NOW(), false, NOW(), 0, '[]', NULL)
           RETURNING id"#,
    )
    .bind("Non-Admin PostHog Users")
    .bind("Matches @posthog.com but NOT admin")
    .bind(team.id)
    .bind(main_cohort_filters)
    .fetch_one(&mut *conn)
    .await?;

    // Create flag that matches the main cohort
    let flag_json = json!([{
        "id": 1,
        "key": "non-admin-flag",
        "name": "Non-Admin Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [{
                "properties": [{
                    "key": "id",
                    "type": "cohort",
                    "value": main_cohort_id,
                    "operator": "in"
                }],
                "rollout_percentage": 100
            }]
        }
    }]);

    insert_flags_for_team_in_redis(client.clone(), team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Test 1: User with engineer@posthog.com should match
    // (matches @posthog.com regex AND is NOT in admin cohort)
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;

    assert_eq!(res.status(), StatusCode::OK);
    let json_data = res.json::<Value>().await?;

    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "non-admin-flag": {
                    "key": "non-admin-flag",
                    "enabled": true
                }
            }
        })
    );

    // Test 2: User with admin@posthog.com should NOT match
    // (matches @posthog.com regex BUT is in admin cohort)
    let admin_distinct_id = "admin_user".to_string();
    context
        .insert_person(
            team.id,
            admin_distinct_id.clone(),
            Some(json!({
                "email": "admin@posthog.com"
            })),
        )
        .await
        .unwrap();

    let admin_payload = json!({
        "token": token,
        "distinct_id": admin_distinct_id,
    });

    let admin_res = server
        .send_flags_request(admin_payload.to_string(), Some("2"), None)
        .await;

    assert_eq!(admin_res.status(), StatusCode::OK);
    let admin_json = admin_res.json::<Value>().await?;

    assert_json_include!(
        actual: admin_json,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "non-admin-flag": {
                    "key": "non-admin-flag",
                    "enabled": false
                }
            }
        })
    );

    // Test 3: User without @posthog.com should NOT match
    // (doesn't match regex, regardless of admin status)
    let external_distinct_id = "external_user".to_string();
    context
        .insert_person(
            team.id,
            external_distinct_id.clone(),
            Some(json!({
                "email": "user@example.com"
            })),
        )
        .await
        .unwrap();

    let external_payload = json!({
        "token": token,
        "distinct_id": external_distinct_id,
    });

    let external_res = server
        .send_flags_request(external_payload.to_string(), Some("2"), None)
        .await;

    assert_eq!(external_res.status(), StatusCode::OK);
    let external_json = external_res.json::<Value>().await?;

    assert_json_include!(
        actual: external_json,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "non-admin-flag": {
                    "key": "non-admin-flag",
                    "enabled": false
                }
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_date_string_property_matching_with_is_date_after() -> Result<()> {
    // This test reproduces the issue where a date string stored in DB like "2024-03-15T19:17:07.083Z"
    // is compared against a filter value like "2024-03-15 19:37:00" using the is_date_after operator.
    // The flag should NOT match since 19:17:07 is before 19:37:00 on the same day.

    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "test_user_123".to_string();

    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(redis_client.clone())
        .await
        .unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    // Insert person with last_active_date as a string date
    context
        .insert_person(
            team.id,
            distinct_id.clone(),
            Some(json!({
                "user_id": "test_123",
                "last_active_date": "2024-03-15T19:17:07.083Z",
                "segment": null  // This ensures the segment filter won't match
            })),
        )
        .await
        .unwrap();

    // Insert flag with filter configuration
    let flag_json = json!([{
        "id": 1,
        "key": "date-comparison-flag",
        "name": "Date Comparison Flag",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [
                {
                    "variant": null,
                    "properties": [],
                    "rollout_percentage": 100
                },
                {
                    "variant": "experimental",
                    "properties": [{
                        "key": "segment",
                        "type": "person",
                        "value": ["premium"],
                        "operator": "exact"
                    }],
                    "rollout_percentage": 100
                },
                {
                    "variant": "experimental",
                    "properties": [{
                        "key": "last_active_date",
                        "type": "person",
                        "value": "2024-03-15 19:37:00",  // 20 minutes after the person's actual time
                        "operator": "is_date_after"
                    }],
                    "rollout_percentage": 100
                }
            ],
            "payloads": {},
            "multivariate": {
                "variants": [
                    {
                        "key": "control",
                        "name": "Control variant",
                        "rollout_percentage": 50
                    },
                    {
                        "key": "experimental",
                        "name": "Experimental variant",
                        "rollout_percentage": 50
                    }
                ]
            }
        }
    }]);

    insert_flags_for_team_in_redis(redis_client.clone(), team.id, Some(flag_json.to_string()))
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_response = res.json::<Value>().await?;

    // Check the response
    let flags = &json_response["flags"];
    let test_flag = &flags["date-comparison-flag"];

    // The flag should NOT match the date condition since:
    // - last_active_date: 2024-03-15T19:17:07.083Z (person's value)
    // - is NOT after: 2024-03-15 19:37:00 (filter value)
    // The person's time (19:17) is BEFORE the filter time (19:37)

    // First group matches (100% rollout, no conditions), so flag should be enabled
    // but with the base variant (null or control based on rollout)
    assert_eq!(
        test_flag["enabled"], true,
        "Flag should be enabled from first group"
    );

    // The variant should be control or null, NOT "experimental"
    // since the date condition shouldn't match
    let variant = test_flag["variant"].as_str();
    assert!(
        variant.is_none() || variant == Some("control"),
        "Variant should be control or null, not 'experimental'. Got: {variant:?}",
    );

    Ok(())
}

#[tokio::test]
async fn it_includes_evaluated_at_timestamp_in_response() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    let server = ServerHandle::for_config(config).await;

    // Test v2 response format
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let before_request = chrono::Utc::now().timestamp_millis();
    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    let after_request = chrono::Utc::now().timestamp_millis();

    assert_eq!(StatusCode::OK, res.status());

    let v2_response = res.json::<FlagsResponse>().await?;

    // Verify evaluated_at field exists and is a valid timestamp
    assert!(
        v2_response.evaluated_at >= before_request,
        "evaluated_at should be >= request time: {} >= {}",
        v2_response.evaluated_at,
        before_request
    );
    assert!(
        v2_response.evaluated_at <= after_request,
        "evaluated_at should be <= after request time: {} <= {}",
        v2_response.evaluated_at,
        after_request
    );

    // Also test with raw JSON to ensure it's serialized in the response
    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    let json_value: Value = res.json().await?;

    assert!(
        json_value.get("evaluatedAt").is_some(),
        "evaluatedAt field should be present in JSON response"
    );
    assert!(
        json_value["evaluatedAt"].is_i64(),
        "evaluatedAt should be an integer"
    );

    // Test v1 legacy response format also includes evaluatedAt
    let res = server
        .send_flags_request(payload.to_string(), Some("1"), None)
        .await;
    let legacy_json: Value = res.json().await?;

    assert!(
        legacy_json.get("evaluatedAt").is_some(),
        "evaluatedAt field should be present in v1 legacy response"
    );

    Ok(())
}

#[tokio::test]
async fn test_cohort_date_matching_with_milliseconds_format() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let client = setup_redis_client(Some(config.redis_url.clone())).await;

    let distinct_id = "test_user".to_string();
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    // Create a cohort with date comparison using is_date_after operator
    let cohort_filters = json!({
        "properties": {
            "type": "OR",
            "values": [{
                "type": "AND",
                "values": [
                    {
                        "key": "signup_date",
                        "type": "person",
                        "value": "2025-12-01",
                        "operator": "is_date_after"
                    }
                ]
            }]
        }
    });

    // Insert cohort and get the actual ID
    let cohort = context
        .insert_cohort(
            team.id,
            Some("Test Date with Milliseconds".to_string()),
            cohort_filters,
            false,
        )
        .await
        .unwrap();

    // Create a feature flag using the cohort's actual ID
    let flag_json = json!([{
        "id": 1,
        "key": "test-date-with-milliseconds",
        "name": "Test Date with Milliseconds",
        "active": true,
        "deleted": false,
        "team_id": team.id,
        "filters": {
            "groups": [{
                "properties": [{
                    "key": "id",
                    "type": "cohort",
                    "value": cohort.id,
                    "operator": "in"
                }],
                "rollout_percentage": 100
            }]
        }
    }]);

    insert_flags_for_team_in_redis(client.clone(), team.id, Some(flag_json.to_string())).await?;

    // Insert person with date in ISO 8601 format with milliseconds (no timezone)
    // This format fails to parse in the Rust dateparser library
    context
        .insert_person(
            team.id,
            distinct_id.clone(),
            Some(json!({
                "signup_date": "2025-12-19T00:00:00.000",
            })),
        )
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;

    assert_eq!(res.status(), StatusCode::OK);
    let json_data = res.json::<Value>().await?;

    // The flag should be enabled because 2025-12-19 is after 2025-12-01
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "test-date-with-milliseconds": {
                    "key": "test-date-with-milliseconds",
                    "enabled": true
                }
            }
        })
    );

    Ok(())
}

/// Tests that $initial_ properties are populated from overrides only when DB doesn't have them.
///
/// When a request sends `$browser: "Chrome"` as an override:
/// - If DB has `$initial_browser: "Safari"`, that value should be preserved
/// - If DB has no `$initial_browser`, it should be populated from the override's `$browser`
#[rstest]
#[case::db_has_initial_browser_preserves_it(
    // DB has $initial_browser, override has $browser - DB value should win
    Some(json!({"$initial_browser": "Safari", "$browser": "Firefox"})),
    json!({"$browser": "Chrome"}),
    true       // Flag checking $initial_browser = Safari should match
)]
#[case::db_missing_initial_browser_populates_from_override(
    // DB has no $initial_browser, override has $browser - should populate from override
    Some(json!({"$browser": "Firefox"})),
    json!({"$browser": "Chrome"}),
    false      // Flag checking $initial_browser = Safari should NOT match
)]
#[case::db_empty_populates_from_override(
    // DB has nothing, override has $browser - should populate from override
    None,
    json!({"$browser": "Chrome"}),
    false      // Flag checking $initial_browser = Safari should NOT match
)]
#[tokio::test]
async fn test_initial_property_population_respects_db_values(
    #[case] db_properties: Option<Value>,
    #[case] override_properties: Value,
    #[case] flag_should_match: bool,
) -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = format!("test_initial_props_{}", rand::thread_rng().gen::<u32>());

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();

    // Insert person with specified DB properties
    context
        .insert_person(team.id, distinct_id.clone(), db_properties)
        .await
        .unwrap();

    // Create a flag that checks $initial_browser = "Safari"
    let flag_json = json!([
        {
            "id": 1,
            "key": "initial-browser-flag",
            "name": "Flag checking initial browser",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "$initial_browser",
                                "value": "Safari",
                                "operator": "exact",
                                "type": "person"
                            }
                        ],
                        "rollout_percentage": 100
                    }
                ],
            },
        }
    ]);

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

    let server = ServerHandle::for_config(config).await;

    // Send request with property overrides
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "person_properties": override_properties
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;

    if res.status() != StatusCode::OK {
        let status = res.status();
        let text = res.text().await?;
        panic!("Non-200 response: {status}\nBody: {text}");
    }

    let json_data = res.json::<Value>().await?;

    // The flag checks $initial_browser = "Safari"
    // - If DB had $initial_browser: "Safari", flag should match
    // - If $initial_browser was populated from override's $browser: "Chrome", flag should NOT match
    let expected_enabled = flag_should_match;
    let expected_reason = if flag_should_match {
        "condition_match"
    } else {
        "no_condition_match"
    };

    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "flags": {
                "initial-browser-flag": {
                    "key": "initial-browser-flag",
                    "enabled": expected_enabled,
                    "reason": {
                        "code": expected_reason
                    }
                }
            }
        })
    );

    Ok(())
}
