use anyhow::Result;
use assert_json_diff::assert_json_include;

use feature_flags::api::types::FlagsResponse;
use limiters::redis::ServiceName;
use rand::Rng;
use reqwest::StatusCode;
use serde_json::{json, Value};

use crate::common::*;

use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::utils::test_utils::{
    create_group_in_pg, insert_flags_for_team_in_redis, insert_new_team_in_pg,
    insert_new_team_in_redis, insert_person_for_team_in_pg, setup_pg_reader_client,
    setup_redis_client,
};

pub mod common;

#[tokio::test]
async fn it_sends_flag_request() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone()));
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

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

    let res = server.send_flags_request(payload.to_string()).await;
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
async fn it_rejects_invalid_headers_flag_request() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone()));
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

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
    let client = setup_redis_client(Some(config.redis_url.clone()));
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;
    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": "",
        "groups": {"group1": "group1"}
    });
    let res = server.send_flags_request(payload.to_string()).await;
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
    let client = setup_redis_client(Some(config.redis_url.clone()));
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;
    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "groups": {"group1": "group1"}
    });
    let res = server.send_flags_request(payload.to_string()).await;
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
    let res = server.send_flags_request(payload.to_string()).await;
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
    let res = server.send_flags_request(payload.to_string()).await;
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
    let res = server.send_flags_request(payload.to_string()).await;
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

    let res = server.send_flags_request(payload.to_string()).await;
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

    let client = setup_redis_client(Some(config.redis_url.clone()));
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

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

    let res = server.send_flags_request(payload.to_string()).await;
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

    let client = setup_redis_client(Some(config.redis_url.clone()));
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

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

    let res = server.send_flags_request(payload.to_string()).await;
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

    let res = server.send_flags_request(payload.to_string()).await;
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

    let client = setup_redis_client(Some(config.redis_url.clone()));
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

    let res = server.send_flags_request(payload.to_string()).await;
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

    let res = server.send_flags_request(payload.to_string()).await;
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
    let redis_client = setup_redis_client(Some(config.redis_url.clone()));
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

    let res = server.send_flags_request(payload.to_string()).await;

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
    let redis_client = setup_redis_client(Some(config.redis_url.clone()));
    let pg_client = setup_pg_reader_client(None).await;
    let team_id = rand::thread_rng().gen_range(1..10_000_000);
    let team = insert_new_team_in_pg(pg_client.clone(), Some(team_id))
        .await
        .unwrap();

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

        let res = server.send_flags_request(payload.to_string()).await;
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

        let res = server.send_flags_request(payload.to_string()).await;
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

        let res = server.send_flags_request(payload.to_string()).await;
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

    let client = setup_redis_client(Some(config.redis_url.clone()));
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

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

    let res = server.send_flags_request(payload.to_string()).await;
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

    let client = setup_redis_client(Some(config.redis_url.clone()));
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token;

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

    let res = server.send_flags_request(payload.to_string()).await;
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

    let res = server.send_flags_request(payload.to_string()).await;
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

    let res = server.send_flags_request(payload.to_string()).await;
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
