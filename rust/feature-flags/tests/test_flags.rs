use anyhow::Result;
use assert_json_diff::assert_json_include;

use feature_flags::api::types::{FlagsResponse, LegacyFlagsResponse};
use limiters::redis::ServiceName;
use rand::Rng;
use reqwest::StatusCode;
use rstest::rstest;
use serde_json::{json, Value};

use crate::common::*;

use common_models::test_utils::{
    insert_new_team_in_pg, insert_new_team_in_redis, setup_redis_client,
};
use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::utils::test_utils::{
    create_group_in_pg, insert_flags_for_team_in_redis, insert_person_for_team_in_pg,
    setup_pg_reader_client,
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

    let client = setup_redis_client(Some(config.redis_url.clone()));
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
        .send_flags_request(payload.to_string(), version)
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

    let client = setup_redis_client(Some(config.redis_url.clone()));
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
        .send_flags_request(payload.to_string(), Some(version))
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

    let client = setup_redis_client(Some(config.redis_url.clone()));
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
    let client = setup_redis_client(Some(config.redis_url.clone()));
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
    let res = server.send_flags_request(payload.to_string(), None).await;
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
    let res = server.send_flags_request(payload.to_string(), None).await;
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
    let res = server.send_flags_request(payload.to_string(), None).await;
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
    let res = server.send_flags_request(payload.to_string(), None).await;
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
    let res = server.send_flags_request(payload.to_string(), None).await;
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

    let res = server.send_flags_request(payload.to_string(), None).await;
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
        .send_flags_request(payload.to_string(), Some("2"))
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

    let client = setup_redis_client(Some(config.redis_url.clone()));
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

    let res = server.send_flags_request(payload.to_string(), None).await;
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

    let res = server.send_flags_request(payload.to_string(), None).await;
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

    let res = server.send_flags_request(payload.to_string(), None).await;
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

    let res = server.send_flags_request(payload.to_string(), None).await;
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

    let res = server.send_flags_request(payload.to_string(), None).await;
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

    let res = server.send_flags_request(payload.to_string(), None).await;

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

        let res = server.send_flags_request(payload.to_string(), None).await;
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

        let res = server.send_flags_request(payload.to_string(), None).await;
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

        let res = server.send_flags_request(payload.to_string(), None).await;
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

    let res = server.send_flags_request(payload.to_string(), None).await;
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

    let res = server.send_flags_request(payload.to_string(), None).await;
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

    let res = server.send_flags_request(payload.to_string(), None).await;
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

    let res = server.send_flags_request(payload.to_string(), None).await;
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
    let redis_client = setup_redis_client(Some(config.redis_url.clone()));
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

    let res = server.send_flags_request(payload.to_string(), None).await;
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

    let res = server.send_flags_request(payload.to_string(), None).await;
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
    let redis_client = setup_redis_client(Some(config.redis_url.clone()));
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

    let res = server.send_flags_request(payload.to_string(), None).await;
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
    let client = setup_redis_client(Some(config.redis_url.clone()));
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
        .send_flags_request(payload.to_string(), Some("3"))
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
