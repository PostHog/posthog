use anyhow::Result;
use assert_json_diff::assert_json_include;

use feature_flags::api::types::{FlagsResponse, LegacyFlagsResponse};
use limiters::redis::ServiceName;
use rand::Rng;
use reqwest::StatusCode;
use rstest::rstest;
use serde_json::{json, Value};

use crate::common::*;

use feature_flags::config::{FlexBool, TeamIdCollection, DEFAULT_TEST_CONFIG};
use feature_flags::utils::test_utils::{
    create_group_in_pg, insert_flags_for_team_in_redis, insert_new_team_in_pg,
    insert_new_team_in_redis, insert_person_for_team_in_pg, insert_suppression_rule_in_pg,
    setup_pg_reader_client, setup_redis_client, update_team_autocapture_exceptions,
};

pub mod common;

#[rstest]
#[case(None)]
#[case(Some("1"))]
#[case(Some("banana"))]
#[tokio::test]
async fn it_gets_legacy_response_by_default_or_invalid_version(
    #[case] version: Option<&str>,
) -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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

#[rstest]
#[case("2")]
#[case("3")]
#[tokio::test]
async fn it_get_new_response_when_version_is_2_or_more(#[case] version: &str) -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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
async fn it_rejects_empty_distinct_id() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;
    let distinct_id = "user_distinct_id".to_string();
    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();
    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": "",
        "groups": {"group1": "group1"}
    });
    let res = server
        .send_flags_request(payload.to_string(), None, None)
        .await;
    assert_eq!(StatusCode::BAD_REQUEST, res.status());
    assert_eq!(
        res.text().await?,
        "The distinct_id field cannot be empty. Please provide a valid identifier."
    );
    Ok(())
}

#[tokio::test]
async fn it_rejects_missing_distinct_id() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;
    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "groups": {"group1": "group1"}
    });
    let res = server
        .send_flags_request(payload.to_string(), None, None)
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
        .send_flags_request(payload.to_string(), None, None)
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
        .send_flags_request(payload.to_string(), None, None)
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
        .send_flags_request(payload.to_string(), None, None)
        .await;
    assert_eq!(StatusCode::BAD_REQUEST, res.status());

    let response_text = res.text().await?;

    assert!(
        response_text.contains("Failed to decode request: invalid JSON"),
        "Unexpected error message: {:?}",
        response_text
    );
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
        .send_flags_request(payload.to_string(), None, None)
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), None, None)
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;
    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
        .send_flags_request(payload.to_string(), None, None)
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
        .send_flags_request(payload.to_string(), None, None)
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let team = insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    let token = team.api_token;

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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
        .send_flags_request(payload.to_string(), None, None)
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
        .send_flags_request(payload.to_string(), None, None)
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
    let pg_client = setup_pg_reader_client(None).await;

    // Insert a new team into Redis and retrieve the team details
    let team = insert_new_team_in_redis(redis_client.clone())
        .await
        .unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(
        pg_client.clone(),
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

    insert_flags_for_team_in_redis(
        redis_client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), None, None)
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
    let pg_client = setup_pg_reader_client(None).await;
    let team_id = rand::thread_rng().gen_range(1..10_000_000);
    let team = insert_new_team_in_pg(pg_client.clone(), Some(team_id))
        .await
        .unwrap();

    // need this for the test to work, since we look up the dinstinct_id <-> person_id in from the DB at the beginning
    // of the flag evaluation process
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None).await?;

    let token = team.api_token;

    // Create a group of type "organization" (group_type_index 1) with group_key "foo" and specific properties
    create_group_in_pg(
        pg_client.clone(),
        team.id,
        "organization",
        "foo",
        json!({"email": "posthog@example.com"}),
    )
    .await?;

    // Create a group of type "project" (group_type_index 0) with group_key "bar" and specific properties
    create_group_in_pg(
        pg_client.clone(),
        team.id,
        "project",
        "bar",
        json!({"name": "Project Bar"}),
    )
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
    insert_flags_for_team_in_redis(
        redis_client.clone(),
        team.id,
        team.project_id,
        Some(flags_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    // First Decision: Without specifying any groups
    {
        let payload = json!({
            "token": token,
            "distinct_id": distinct_id
        });

        let res = server
            .send_flags_request(payload.to_string(), None, None)
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
            .send_flags_request(payload.to_string(), None, None)
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
            .send_flags_request(payload.to_string(), None, None)
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    // Test without any person properties - should match since the property doesn't exist
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), None, None)
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;
    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    // Test 1: Without any person properties - should match since properties don't exist
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), None, None)
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
        .send_flags_request(payload.to_string(), None, None)
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
        .send_flags_request(payload.to_string(), None, None)
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_pg(pg_client.clone(), None).await?;
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();
    let token = team.api_token;

    // Create a group with matching name
    create_group_in_pg(
        pg_client.clone(),
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

    insert_flags_for_team_in_redis(
        redis_client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
        .send_flags_request(payload.to_string(), None, None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "complex-flag": "test"  // Should get "test" variant due to name match
            }
        })
    );

    // Test with non-matching name but matching date
    create_group_in_pg(
        pg_client.clone(),
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
        .send_flags_request(payload.to_string(), None, None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    let flag_value = json_data["featureFlags"]["complex-flag"].as_str().unwrap();
    assert!(
        ["control", "test"].contains(&flag_value),
        "Expected either 'control' or 'test' variant, got {}",
        flag_value
    );

    Ok(())
}

#[tokio::test]
async fn test_super_condition_with_complex_request() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "test_user".to_string();
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(redis_client.clone()).await?;
    insert_new_team_in_pg(pg_client.clone(), Some(team.id)).await?;
    let token = team.api_token;

    // Insert person with just their stored properties from the DB
    insert_person_for_team_in_pg(
        pg_client.clone(),
        team.id,
        distinct_id.clone(),
        Some(json!({
            "$feature_enrollment/artificial-hog": true,
            "$feature_enrollment/error-tracking": true,
            "$feature_enrollment/llm-observability": false,
            "$feature_enrollment/messaging-product": true,
            "email": "gtarasov.work@gmail.com"
        })),
    )
    .await?;

    // Create the same flag as in production
    let flag_json = json!([{
        "id": 13651,
        "key": "artificial-hog",
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
                    "key": "$feature_enrollment/artificial-hog",
                    "type": "person",
                    "value": ["true"],
                    "operator": "exact"
                }],
                "rollout_percentage": 100
            }]
        }
    }]);

    insert_flags_for_team_in_redis(
        redis_client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
        .send_flags_request(payload.to_string(), None, None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorsWhileComputingFlags": false,
            "featureFlags": {
                "artificial-hog": true
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_flag_matches_with_no_person_profile() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
        .send_flags_request(payload.to_string(), None, None)
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    // Without config param
    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    if res.status() != StatusCode::OK {
        let text = res.text().await?;
        panic!("Non-200 response \nBody: {}", text);
    }
    let json_data = res.json::<Value>().await?;
    assert!(json_data.get("supportedCompression").is_none());
    assert!(json_data.get("autocapture_opt_out").is_none());

    // With config param
    let res = server
        .send_flags_request(payload.to_string(), Some("2"), Some("true"))
        .await;
    let json_data = res.json::<Value>().await?;
    assert!(json_data.get("supportedCompression").is_some());
    // You can check for other config fields as well

    Ok(())
}

#[tokio::test]
async fn test_config_basic_fields() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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
            "groups": [{"properties": [], "rollout_percentage": 100}],
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

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), Some("true"))
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;

    // Test basic config fields
    assert_eq!(
        json_data["supportedCompression"],
        json!(["gzip", "gzip-js"])
    );
    assert_eq!(json_data["defaultIdentifiedOnly"], json!(true));
    assert_eq!(json_data["isAuthenticated"], json!(false));
    assert_eq!(
        json_data["config"],
        json!({"enable_collect_everything": true})
    );
    assert_eq!(json_data["toolbarParams"], json!({}));

    Ok(())
}

#[tokio::test]
async fn test_config_analytics_enabled() -> Result<()> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.debug = FlexBool(false);
    config.new_analytics_capture_endpoint = "https://analytics.posthog.com".to_string();
    // default config has new_analytics_capture_excluded_team_ids as All (exclude nobody)

    let distinct_id = "user_distinct_id".to_string();
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

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

    assert!(json_data["analytics"].is_object());
    assert_eq!(
        json_data["analytics"]["endpoint"],
        json!("https://analytics.posthog.com")
    );

    Ok(())
}

#[tokio::test]
async fn test_config_analytics_enabled_by_default() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

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

    assert!(json_data["analytics"].is_object());
    assert_eq!(json_data["analytics"]["endpoint"], json!("/i/v0/e/"));

    Ok(())
}

#[tokio::test]
async fn test_config_analytics_disabled_debug_mode() -> Result<()> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.debug = FlexBool(true); // Debug mode disables analytics
    config.new_analytics_capture_endpoint = "https://analytics.posthog.com".to_string();

    let distinct_id = "user_distinct_id".to_string();
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

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

    assert!(json_data["analytics"].is_null());

    Ok(())
}

#[tokio::test]
async fn test_config_capture_performance_combinations() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;

    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

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

    // With default team settings (None), both should be false
    assert_eq!(json_data["capturePerformance"], json!(false));

    Ok(())
}

#[tokio::test]
async fn test_config_autocapture_exceptions() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

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

    // Default team should have autocapture_exceptions disabled
    assert_eq!(json_data["autocaptureExceptions"], json!(false));

    Ok(())
}

#[tokio::test]
async fn test_config_optional_team_features() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

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

    // Test default values for optional team features
    assert_eq!(json_data["surveys"], json!(false));
    assert_eq!(json_data["heatmaps"], json!(false));
    assert_eq!(json_data["flagsPersistenceDefault"], json!(false));

    // Test fields that should be null when not set
    assert!(json_data["captureDeadClicks"].is_null());

    // Test elements chain as string (should be enabled by default in test config)
    assert_eq!(json_data["elementsChainAsString"], json!(true));

    Ok(())
}

#[tokio::test]
async fn test_config_site_apps_empty_by_default() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

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

    // Site apps should be empty array by default (inject_web_apps is false/None)
    assert_eq!(json_data["siteApps"], json!([]));

    Ok(())
}

#[tokio::test]
async fn test_config_included_in_legacy_response() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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
            "groups": [{"properties": [], "rollout_percentage": 100}],
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

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    // Test legacy response (no version) with config=true
    let res = server
        .send_flags_request(payload.to_string(), None, Some("true"))
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;

    // Legacy response SHOULD include config fields when requested
    assert_eq!(
        json_data["supportedCompression"],
        json!(["gzip", "gzip-js"])
    );
    assert_eq!(json_data["autocapture_opt_out"], json!(false));
    assert_eq!(json_data["defaultIdentifiedOnly"], json!(true));
    assert_eq!(json_data["isAuthenticated"], json!(false));

    // And should include legacy flag format
    assert!(json_data.get("featureFlags").is_some());
    assert_eq!(json_data["featureFlags"]["test-flag"], json!(true));
    assert_eq!(json_data["errorsWhileComputingFlags"], json!(false));

    Ok(())
}

#[tokio::test]
async fn test_config_site_apps_with_actual_plugins() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let mut team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    // Enable inject_web_apps on the team object
    team.inject_web_apps = Some(true);

    // Update the team in Redis with inject_web_apps enabled
    let serialized_team = serde_json::to_string(&team).unwrap();
    client
        .set(
            format!(
                "{}{}",
                feature_flags::team::team_models::TEAM_TOKEN_CACHE_PREFIX,
                team.api_token.clone()
            ),
            serialized_team,
        )
        .await
        .unwrap();

    // Insert team in PG
    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Insert a plugin
    let mut conn = pg_client.get_connection().await.unwrap();
    let plugin_id: i32 = sqlx::query_scalar(
        r#"INSERT INTO posthog_plugin 
           (name, description, url, config_schema, tag, source, plugin_type, is_global, is_preinstalled, is_stateless, capabilities, from_json, from_web, organization_id, updated_at, created_at)
           VALUES ($1, 'Test Site App', $2, '[]', '', '', 'source', false, false, false, '{}', false, false, $3::uuid, NOW(), NOW())
           RETURNING id"#,
    )
    .bind("Test Site App")
    .bind(format!("test://plugin/site_app/{}", uuid::Uuid::new_v4()))
    .bind("019026a4-be80-0000-5bf3-171d00629163")
    .fetch_one(&mut *conn)
    .await
    .unwrap();

    // Insert plugin source file (site.ts with TRANSPILED status)
    let source_uuid = uuid::Uuid::new_v4().to_string();
    sqlx::query(
        r#"INSERT INTO posthog_pluginsourcefile 
           (id, plugin_id, filename, source, transpiled, status, updated_at)
           VALUES ($1::uuid, $2, 'site.ts', 'function test(){}', 'function test(){}', 'TRANSPILED', NOW())"#,
    )
    .bind(source_uuid)
    .bind(plugin_id)
    .execute(&mut *conn)
    .await
    .unwrap();

    // Insert plugin config to connect the plugin to the team
    sqlx::query(
        r#"INSERT INTO posthog_pluginconfig 
           (plugin_id, team_id, enabled, "order", config, web_token, updated_at, created_at)
           VALUES ($1, $2, true, 1, '{}', 'test_site_app_token', NOW(), NOW())"#,
    )
    .bind(plugin_id)
    .bind(team.id)
    .execute(&mut *conn)
    .await
    .unwrap();

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

    // Site apps should be populated
    assert!(json_data["siteApps"].is_array());
    let site_apps = json_data["siteApps"].as_array().unwrap();

    assert_eq!(site_apps.len(), 1);

    let site_app = &site_apps[0];
    assert!(site_app["url"].as_str().unwrap().starts_with("/site_app/"));
    assert!(site_app["url"]
        .as_str()
        .unwrap()
        .contains("test_site_app_token"));
    assert_eq!(site_app["type"], "site_app");

    Ok(())
}

#[tokio::test]
async fn test_config_session_recording_with_rrweb_script() -> Result<()> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    // Configure rrweb script for all teams
    config.session_replay_rrweb_script =
        "console.log('Custom session recording script')".to_string();
    config.session_replay_rrweb_script_allowed_teams = "*".parse().unwrap();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let mut team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    // Enable session recording on the team object
    team.session_recording_opt_in = true;

    // Update the team in Redis with session recording enabled
    let serialized_team = serde_json::to_string(&team).unwrap();
    client
        .set(
            format!(
                "{}{}",
                feature_flags::team::team_models::TEAM_TOKEN_CACHE_PREFIX,
                team.api_token.clone()
            ),
            serialized_team,
        )
        .await
        .unwrap();

    // Insert team in PG
    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

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

    // Session recording should be configured
    assert!(json_data["sessionRecording"].is_object());
    let session_recording = &json_data["sessionRecording"];

    assert_eq!(session_recording["endpoint"], "/s/");
    assert_eq!(session_recording["recorderVersion"], "v2");

    // Should include the custom rrweb script
    assert!(session_recording["scriptConfig"].is_object());
    assert_eq!(
        session_recording["scriptConfig"]["script"],
        "console.log('Custom session recording script')"
    );

    Ok(())
}

#[tokio::test]
async fn test_config_session_recording_team_not_allowed_for_script() -> Result<()> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    // Configure rrweb script only for specific teams (not including our test team)
    config.session_replay_rrweb_script = "console.log('Restricted script')".to_string();
    config.session_replay_rrweb_script_allowed_teams = "999,1000,1001".parse().unwrap(); // Our team won't be in this list

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let mut team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    // Enable session recording on the team object
    team.session_recording_opt_in = true;

    // Update the team in Redis with session recording enabled
    let serialized_team = serde_json::to_string(&team).unwrap();
    client
        .set(
            format!(
                "{}{}",
                feature_flags::team::team_models::TEAM_TOKEN_CACHE_PREFIX,
                team.api_token.clone()
            ),
            serialized_team,
        )
        .await
        .unwrap();

    // Insert team in PG
    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

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

    // Session recording should be configured but WITHOUT the script
    assert!(json_data["sessionRecording"].is_object());
    let session_recording = &json_data["sessionRecording"];

    assert_eq!(session_recording["endpoint"], "/s/");
    assert_eq!(session_recording["recorderVersion"], "v2");

    // Should NOT include the script config since team is not allowed
    assert!(session_recording["scriptConfig"].is_null());

    Ok(())
}

#[tokio::test]
async fn test_config_comprehensive_enterprise_team() -> Result<()> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.debug = FlexBool(false);
    config.new_analytics_capture_endpoint = "https://analytics.posthog.com".to_string();
    config.new_analytics_capture_excluded_team_ids = TeamIdCollection::None;
    config.element_chain_as_string_excluded_teams = TeamIdCollection::None;
    config.session_replay_rrweb_script = "console.log('Enterprise script')".to_string();
    config.session_replay_rrweb_script_allowed_teams = "*".parse().unwrap();

    let distinct_id = "enterprise_user".to_string();
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let mut team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    // Configure team with all enterprise features enabled
    team.session_recording_opt_in = true;
    team.inject_web_apps = Some(true);
    team.autocapture_exceptions_opt_in = Some(true);
    team.autocapture_web_vitals_opt_in = Some(true);
    team.capture_performance_opt_in = Some(true);
    team.surveys_opt_in = Some(true);
    team.heatmaps_opt_in = Some(true);
    team.flags_persistence_default = Some(true);
    team.capture_dead_clicks = Some(true);
    team.autocapture_opt_out = Some(false);

    // Set allowed web vitals metrics
    team.autocapture_web_vitals_allowed_metrics = Some(sqlx::types::Json(json!([
        "CLS", "FCP", "LCP", "FID", "TTFB"
    ])));

    // Update team in Redis
    let serialized_team = serde_json::to_string(&team).unwrap();
    client
        .set(
            format!(
                "{}{}",
                feature_flags::team::team_models::TEAM_TOKEN_CACHE_PREFIX,
                team.api_token.clone()
            ),
            serialized_team,
        )
        .await
        .unwrap();

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Add a site app plugin
    let mut conn = pg_client.get_connection().await.unwrap();
    let plugin_id: i32 = sqlx::query_scalar(
        r#"INSERT INTO posthog_plugin 
           (name, description, url, config_schema, tag, source, plugin_type, is_global, is_preinstalled, is_stateless, capabilities, from_json, from_web, organization_id, updated_at, created_at)
           VALUES ($1, 'Enterprise Site App', $2, '[]', '', '', 'source', false, false, false, '{}', false, false, $3::uuid, NOW(), NOW())
           RETURNING id"#,
    )
    .bind("Enterprise Site App")
    .bind(format!("test://plugin/site_app/{}", uuid::Uuid::new_v4()))
    .bind("019026a4-be80-0000-5bf3-171d00629163")
    .fetch_one(&mut *conn)
    .await
    .unwrap();

    let source_uuid = uuid::Uuid::new_v4().to_string();
    sqlx::query(
        r#"INSERT INTO posthog_pluginsourcefile 
           (id, plugin_id, filename, source, transpiled, status, updated_at)
           VALUES ($1::uuid, $2, 'site.ts', 'function enterpriseFeature(){}', 'function enterpriseFeature(){}', 'TRANSPILED', NOW())"#,
    )
    .bind(source_uuid)
    .bind(plugin_id)
    .execute(&mut *conn)
    .await
    .unwrap();

    sqlx::query(
        r#"INSERT INTO posthog_pluginconfig 
           (plugin_id, team_id, enabled, "order", config, web_token, updated_at, created_at)
           VALUES ($1, $2, true, 1, '{}', 'enterprise_site_app_token', NOW(), NOW())"#,
    )
    .bind(plugin_id)
    .bind(team.id)
    .execute(&mut *conn)
    .await
    .unwrap();

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

    // Verify all enterprise features are enabled
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

    // Analytics should be enabled
    assert!(json_data["analytics"].is_object());
    assert_eq!(
        json_data["analytics"]["endpoint"],
        json!("https://analytics.posthog.com")
    );

    // Elements chain as string should be enabled
    assert_eq!(json_data["elementsChainAsString"], json!(true));

    // Performance capture should have both features enabled
    let capture_performance = &json_data["capturePerformance"];
    assert!(capture_performance.is_object());
    assert_eq!(capture_performance["network_timing"], json!(true));
    assert_eq!(capture_performance["web_vitals"], json!(true));
    assert_eq!(
        capture_performance["web_vitals_allowed_metrics"],
        json!(["CLS", "FCP", "LCP", "FID", "TTFB"])
    );

    // Autocapture exceptions should be enabled
    assert_eq!(
        json_data["autocaptureExceptions"],
        json!({"endpoint": "/e/"})
    );

    // Optional features should all be enabled
    assert_eq!(json_data["surveys"], json!(true));
    assert_eq!(json_data["heatmaps"], json!(true));
    assert_eq!(json_data["flagsPersistenceDefault"], json!(true));
    assert_eq!(json_data["captureDeadClicks"], json!(true));

    // Session recording should be fully configured with script
    assert!(json_data["sessionRecording"].is_object());
    let session_recording = &json_data["sessionRecording"];
    assert_eq!(session_recording["endpoint"], "/s/");
    assert_eq!(session_recording["recorderVersion"], "v2");
    assert!(session_recording["scriptConfig"].is_object());
    assert_eq!(
        session_recording["scriptConfig"]["script"],
        "console.log('Enterprise script')"
    );

    // Site apps should be populated
    assert!(json_data["siteApps"].is_array());
    let site_apps = json_data["siteApps"].as_array().unwrap();
    assert_eq!(site_apps.len(), 1);
    assert!(site_apps[0]["url"]
        .as_str()
        .unwrap()
        .contains("enterprise_site_app_token"));

    Ok(())
}

#[tokio::test]
async fn test_config_comprehensive_minimal_team() -> Result<()> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.debug = FlexBool(true); // Debug mode disables analytics
    config.new_analytics_capture_endpoint = "https://analytics.posthog.com".to_string();
    config.new_analytics_capture_excluded_team_ids = TeamIdCollection::All; // Exclude all teams
    config.element_chain_as_string_excluded_teams = TeamIdCollection::All; // Exclude all teams
    config.session_replay_rrweb_script = "".to_string(); // No script

    let distinct_id = "minimal_user".to_string();
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let mut team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    // Configure team with minimal features (everything disabled/None)
    team.session_recording_opt_in = false;
    team.inject_web_apps = Some(false);
    team.autocapture_exceptions_opt_in = Some(false);
    team.autocapture_web_vitals_opt_in = Some(false);
    team.capture_performance_opt_in = Some(false);
    team.surveys_opt_in = Some(false);
    team.heatmaps_opt_in = Some(false);
    team.flags_persistence_default = Some(false);
    team.capture_dead_clicks = Some(false);
    team.autocapture_opt_out = Some(true);
    team.autocapture_web_vitals_allowed_metrics = None;

    // Update team in Redis
    let serialized_team = serde_json::to_string(&team).unwrap();
    client
        .set(
            format!(
                "{}{}",
                feature_flags::team::team_models::TEAM_TOKEN_CACHE_PREFIX,
                team.api_token.clone()
            ),
            serialized_team,
        )
        .await
        .unwrap();

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

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

    // Verify minimal configuration
    assert_eq!(
        json_data["supportedCompression"],
        json!(["gzip", "gzip-js"])
    );
    assert_eq!(json_data["autocapture_opt_out"], json!(true)); // Explicitly enabled
    assert_eq!(json_data["defaultIdentifiedOnly"], json!(true));
    assert_eq!(json_data["isAuthenticated"], json!(false));
    assert_eq!(
        json_data["config"],
        json!({"enable_collect_everything": true})
    );
    assert_eq!(json_data["toolbarParams"], json!({}));

    // Analytics should be disabled (debug mode + excluded)
    assert!(json_data["analytics"].is_null());

    // Elements chain as string should be disabled (excluded)
    assert!(json_data["elementsChainAsString"].is_null());

    // Performance capture should be disabled
    assert_eq!(json_data["capturePerformance"], json!(false));

    // Autocapture exceptions should be disabled
    assert_eq!(json_data["autocaptureExceptions"], json!(false));

    // Optional features should all be disabled
    assert_eq!(json_data["surveys"], json!(false));
    assert_eq!(json_data["heatmaps"], json!(false));
    assert_eq!(json_data["flagsPersistenceDefault"], json!(false));
    assert_eq!(json_data["captureDeadClicks"], json!(false));

    // Session recording should be disabled
    assert_eq!(json_data["sessionRecording"], json!(false));

    // Site apps should be empty (inject_web_apps is false)
    assert_eq!(json_data["siteApps"], json!([]));

    Ok(())
}

#[tokio::test]
async fn test_config_mixed_feature_combinations() -> Result<()> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.debug = FlexBool(false);
    config.new_analytics_capture_endpoint = "https://analytics.posthog.com".to_string();
    config.new_analytics_capture_excluded_team_ids = TeamIdCollection::None;
    config.element_chain_as_string_excluded_teams = TeamIdCollection::TeamIds(vec![999]); // Different team excluded
    config.session_replay_rrweb_script = "console.log('Mixed script')".to_string();

    let distinct_id = "mixed_user".to_string();
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let mut team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    // Configure team with mixed features (some enabled, some disabled)
    team.session_recording_opt_in = true;
    team.inject_web_apps = Some(false); // Disabled
    team.autocapture_exceptions_opt_in = Some(true); // Enabled
    team.autocapture_web_vitals_opt_in = Some(false); // Disabled
    team.capture_performance_opt_in = Some(true); // Enabled (only network timing)
    team.surveys_opt_in = None; // Default (should be false)
    team.heatmaps_opt_in = Some(true); // Enabled
    team.flags_persistence_default = None; // Default (should be false)
    team.capture_dead_clicks = None; // Default (should be null)
    team.autocapture_opt_out = None; // Default (should be false)

    // Only allow script for specific teams (include our team)
    config.session_replay_rrweb_script_allowed_teams = format!("{},5,10", team.id).parse().unwrap();

    // Update team in Redis
    let serialized_team = serde_json::to_string(&team).unwrap();
    client
        .set(
            format!(
                "{}{}",
                feature_flags::team::team_models::TEAM_TOKEN_CACHE_PREFIX,
                team.api_token.clone()
            ),
            serialized_team,
        )
        .await
        .unwrap();

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

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

    // Analytics should be enabled (not in debug, not excluded, has endpoint)
    assert!(json_data["analytics"].is_object());
    assert_eq!(
        json_data["analytics"]["endpoint"],
        json!("https://analytics.posthog.com")
    );

    // Elements chain as string should be enabled (team not in exclusion list)
    assert_eq!(json_data["elementsChainAsString"], json!(true));

    // Performance capture should have network timing only
    let capture_performance = &json_data["capturePerformance"];
    assert!(capture_performance.is_object());
    assert_eq!(capture_performance["network_timing"], json!(true));
    assert_eq!(capture_performance["web_vitals"], json!(false));
    assert!(capture_performance["web_vitals_allowed_metrics"].is_null());

    // Autocapture exceptions should be enabled
    assert_eq!(
        json_data["autocaptureExceptions"],
        json!({"endpoint": "/e/"})
    );

    // Mixed optional features
    assert_eq!(json_data["surveys"], json!(false)); // None -> false
    assert_eq!(json_data["heatmaps"], json!(true)); // Explicitly enabled
    assert_eq!(json_data["flagsPersistenceDefault"], json!(false)); // None -> false
    assert!(json_data["captureDeadClicks"].is_null()); // None -> null
    assert_eq!(json_data["autocapture_opt_out"], json!(false)); // None -> false

    // Session recording should be enabled with script (team is allowed)
    assert!(json_data["sessionRecording"].is_object());
    let session_recording = &json_data["sessionRecording"];
    assert_eq!(session_recording["endpoint"], "/s/");
    assert_eq!(session_recording["recorderVersion"], "v2");
    assert!(session_recording["scriptConfig"].is_object());
    assert_eq!(
        session_recording["scriptConfig"]["script"],
        "console.log('Mixed script')"
    );

    // Site apps should be empty (inject_web_apps is false)
    assert_eq!(json_data["siteApps"], json!([]));

    Ok(())
}

#[tokio::test]
async fn test_config_team_exclusions_and_overrides() -> Result<()> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.debug = FlexBool(false);
    config.new_analytics_capture_endpoint = "https://analytics.posthog.com".to_string();

    let distinct_id = "exclusion_test_user".to_string();
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let mut team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    // Configure team
    team.session_recording_opt_in = true;
    team.autocapture_exceptions_opt_in = Some(true);
    team.autocapture_web_vitals_opt_in = Some(true);
    team.capture_performance_opt_in = Some(true);

    // Set up exclusions that include our team
    config.new_analytics_capture_excluded_team_ids =
        TeamIdCollection::TeamIds(vec![team.id, 999, 1000]);
    config.element_chain_as_string_excluded_teams =
        TeamIdCollection::TeamIds(vec![team.id, 999, 1000]);
    config.session_replay_rrweb_script = "console.log('Excluded script')".to_string();
    config.session_replay_rrweb_script_allowed_teams = "999,1000,1001".parse().unwrap(); // Team not allowed

    // Update team in Redis
    let serialized_team = serde_json::to_string(&team).unwrap();
    client
        .set(
            format!(
                "{}{}",
                feature_flags::team::team_models::TEAM_TOKEN_CACHE_PREFIX,
                team.api_token.clone()
            ),
            serialized_team,
        )
        .await
        .unwrap();

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

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

    // Analytics should be disabled (team is excluded)
    assert!(json_data["analytics"].is_null());

    // Elements chain as string should be disabled (team is excluded)
    assert!(json_data["elementsChainAsString"].is_null());

    // Performance capture should still work (not affected by exclusions)
    let capture_performance = &json_data["capturePerformance"];
    assert!(capture_performance.is_object());
    assert_eq!(capture_performance["network_timing"], json!(true));
    assert_eq!(capture_performance["web_vitals"], json!(true));

    // Autocapture exceptions should still work (not affected by exclusions)
    assert_eq!(
        json_data["autocaptureExceptions"],
        json!({"endpoint": "/e/"})
    );

    // Session recording should be enabled but without script (team not allowed for script)
    assert!(json_data["sessionRecording"].is_object());
    let session_recording = &json_data["sessionRecording"];
    assert_eq!(session_recording["endpoint"], "/s/");
    assert_eq!(session_recording["recorderVersion"], "v2");
    assert!(session_recording["scriptConfig"].is_null()); // No script for excluded team

    Ok(())
}

#[tokio::test]
async fn test_config_legacy_vs_v2_consistency() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "consistency_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let mut team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    // Configure team with some features enabled
    team.autocapture_exceptions_opt_in = Some(true);
    team.surveys_opt_in = Some(true);
    team.heatmaps_opt_in = Some(true);

    // Update team in Redis
    let serialized_team = serde_json::to_string(&team).unwrap();
    client
        .set(
            format!(
                "{}{}",
                feature_flags::team::team_models::TEAM_TOKEN_CACHE_PREFIX,
                team.api_token.clone()
            ),
            serialized_team,
        )
        .await
        .unwrap();

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    // Test legacy response with config
    let res = server
        .send_flags_request(payload.to_string(), None, Some("true"))
        .await;
    assert_eq!(StatusCode::OK, res.status());
    let legacy_data = res.json::<Value>().await?;

    // Test v2 response with config
    let v2_res = server
        .send_flags_request(payload.to_string(), Some("2"), Some("true"))
        .await;
    assert_eq!(StatusCode::OK, v2_res.status());
    let v2_data = v2_res.json::<Value>().await?;

    // Config fields should be identical between legacy and v2
    assert_eq!(
        legacy_data["supportedCompression"],
        v2_data["supportedCompression"]
    );
    assert_eq!(
        legacy_data["autocapture_opt_out"],
        v2_data["autocapture_opt_out"]
    );
    assert_eq!(
        legacy_data["defaultIdentifiedOnly"],
        v2_data["defaultIdentifiedOnly"]
    );
    assert_eq!(legacy_data["isAuthenticated"], v2_data["isAuthenticated"]);
    assert_eq!(legacy_data["config"], v2_data["config"]);
    assert_eq!(legacy_data["toolbarParams"], v2_data["toolbarParams"]);
    assert_eq!(
        legacy_data["autocaptureExceptions"],
        v2_data["autocaptureExceptions"]
    );
    assert_eq!(legacy_data["surveys"], v2_data["surveys"]);
    assert_eq!(legacy_data["heatmaps"], v2_data["heatmaps"]);
    assert_eq!(legacy_data["sessionRecording"], v2_data["sessionRecording"]);
    assert_eq!(legacy_data["siteApps"], v2_data["siteApps"]);

    // But flag format should be different
    assert!(legacy_data.get("featureFlags").is_some());
    assert!(legacy_data.get("flags").is_none());
    assert!(v2_data.get("flags").is_some());
    assert!(v2_data.get("featureFlags").is_none());

    Ok(())
}

#[tokio::test]
async fn test_config_error_tracking_with_suppression_rules() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "error_tracking_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let mut team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    // Enable autocapture exceptions for the team
    team.autocapture_exceptions_opt_in = Some(true);

    // Update team in Redis
    let serialized_team = serde_json::to_string(&team).unwrap();
    client
        .set(
            format!(
                "{}{}",
                feature_flags::team::team_models::TEAM_TOKEN_CACHE_PREFIX,
                team.api_token.clone()
            ),
            serialized_team,
        )
        .await
        .unwrap();

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Enable autocapture exceptions in the database too
    update_team_autocapture_exceptions(pg_client.clone(), team.id, true)
        .await
        .unwrap();

    // Insert some suppression rules
    let filter1 = json!({"errorType": "TypeError", "message": "Cannot read property"});
    let filter2 = json!({"stackTrace": {"contains": "node_modules"}});

    insert_suppression_rule_in_pg(pg_client.clone(), team.id, filter1.clone())
        .await
        .unwrap();
    insert_suppression_rule_in_pg(pg_client.clone(), team.id, filter2.clone())
        .await
        .unwrap();

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

    // Error tracking should be enabled with suppression rules
    assert!(json_data["errorTracking"].is_object());
    let error_tracking = &json_data["errorTracking"];
    assert_eq!(error_tracking["autocaptureExceptions"], json!(true));

    let suppression_rules = &error_tracking["suppressionRules"];
    assert!(suppression_rules.is_array());
    let rules_array = suppression_rules.as_array().unwrap();
    assert_eq!(rules_array.len(), 2);
    assert!(rules_array.contains(&filter1));
    assert!(rules_array.contains(&filter2));

    Ok(())
}

#[tokio::test]
async fn test_config_error_tracking_disabled() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "error_tracking_disabled_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
        .await
        .unwrap();

    // Explicitly disable autocapture exceptions for the team
    update_team_autocapture_exceptions(pg_client.clone(), team.id, false)
        .await
        .unwrap();

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

    // Error tracking should be disabled with empty suppression rules
    assert!(json_data["errorTracking"].is_object());
    let error_tracking = &json_data["errorTracking"];
    assert_eq!(error_tracking["autocaptureExceptions"], json!(false));

    let suppression_rules = &error_tracking["suppressionRules"];
    assert!(suppression_rules.is_array());
    assert_eq!(suppression_rules.as_array().unwrap().len(), 0);

    Ok(())
}

#[tokio::test]
async fn test_disable_flags_returns_empty_response() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    // Request with disable_flags: true
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "disable_flags": true
    });

    let res = server
        .send_flags_request(payload.to_string(), None, None)
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    // Request with disable_flags: false (should still return flags)
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "disable_flags": false
    });

    let res = server
        .send_flags_request(payload.to_string(), None, None)
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
    let pg_client = setup_pg_reader_client(None).await;
    let team_id = rand::thread_rng().gen_range(1..10_000_000);
    let team = insert_new_team_in_pg(pg_client.clone(), Some(team_id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None).await?;

    let token = team.api_token;

    // Create a group with a numeric group_key (as a string in DB, but represents a number)
    create_group_in_pg(
        pg_client.clone(),
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

    insert_flags_for_team_in_redis(
        redis_client.clone(),
        team.id,
        team.project_id,
        Some(flags_json.to_string()),
    )
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
            .send_flags_request(payload.to_string(), None, None)
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
            .send_flags_request(payload.to_string(), None, None)
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
            .send_flags_request(payload.to_string(), None, None)
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
            .send_flags_request(payload.to_string(), None, None)
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    // Insert person with the super condition property set to true in the database
    insert_person_for_team_in_pg(
        pg_client.clone(),
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
        panic!("Non-200 response: {}\nBody: {}", status, text);
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
        panic!("Non-200 response: {}\nBody: {}", status, text);
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
    insert_person_for_team_in_pg(
        pg_client.clone(),
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
        panic!("Non-200 response: {}\nBody: {}", status, text);
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    // Insert person with TWO properties in the database
    insert_person_for_team_in_pg(
        pg_client.clone(),
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
        panic!("Non-200 response: {}\nBody: {}", status, text);
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    // Insert person with the super condition property
    insert_person_for_team_in_pg(
        pg_client.clone(),
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
        panic!("Non-200 response: {}\nBody: {}", status, text);
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
        panic!("Non-200 response: {}\nBody: {}", status, text);
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
        panic!("Non-200 response: {}\nBody: {}", status, text);
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    // Test legacy response (no version param)
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), None, None)
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let team = insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();
    let token = team.api_token;

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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
        .send_flags_request(payload.to_string(), None, None)
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
        .send_flags_request(payload.to_string(), None, None)
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
        .send_flags_request(payload.to_string(), None, None)
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    // Insert person with the target email that should match the cohort
    insert_person_for_team_in_pg(
        pg_client.clone(),
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
    insert_person_for_team_in_pg(
        pg_client.clone(),
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
    insert_person_for_team_in_pg(
        pg_client.clone(),
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
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .unwrap();

    insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
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
                                "operator": "exact",
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
                                "operator": "exact",
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

    insert_flags_for_team_in_redis(
        client,
        team.id,
        team.project_id,
        Some(flag_json.to_string()),
    )
    .await?;

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
