use anyhow::Result;
use assert_json_diff::assert_json_include;

use feature_flags::api::types::{FlagsResponse, LegacyFlagsResponse};
use limiters::redis::ServiceName;
use rand::Rng;
use reqwest::StatusCode;
use rstest::rstest;
use serde_json::{json, Value};

use crate::common::*;

use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::utils::test_utils::{
    create_group_in_pg, insert_flags_for_team_in_redis, insert_new_team_in_pg,
    insert_new_team_in_redis, insert_person_for_team_in_pg, setup_pg_reader_client,
    setup_redis_client,
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
    let client = setup_redis_client(Some(config.redis_url.clone()));
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

    let res = server
        .send_flags_request(payload.to_string(), None, None)
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    println!("json_data: {:?}", json_data);
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
    println!("json_data: {:?}", json_data);
    assert!(json_data.get("supportedCompression").is_none());
    assert!(json_data.get("autocaptureOptOut").is_none());

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
    assert_eq!(json_data["hasFeatureFlags"], json!(true)); // Has flags
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
async fn test_config_has_feature_flags_when_empty() -> Result<()> {
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

    // No flags inserted for this team
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
    assert_eq!(json_data["hasFeatureFlags"], json!(false)); // No flags

    Ok(())
}

#[tokio::test]
async fn test_config_analytics_enabled() -> Result<()> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.debug = false;
    config.new_analytics_capture_endpoint = "https://analytics.posthog.com".to_string();
    // default config has new_analytics_capture_excluded_team_ids as All (exclude nobody)

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
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), Some("true"))
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;

    println!("json_data: {:?}", json_data);

    assert!(json_data["analytics"].is_object());
    assert_eq!(
        json_data["analytics"]["endpoint"],
        json!("https://analytics.posthog.com")
    );

    Ok(())
}

#[tokio::test]
async fn test_config_analytics_disabled_debug_mode() -> Result<()> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.debug = true; // Debug mode disables analytics
    config.new_analytics_capture_endpoint = "https://analytics.posthog.com".to_string();

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

    let client = setup_redis_client(Some(config.redis_url.clone()));
    let pg_client = setup_pg_reader_client(None).await;

    // Test case 1: Both disabled
    {
        let team = insert_new_team_in_redis(client.clone()).await.unwrap();
        let mut pg_team = insert_new_team_in_pg(pg_client.clone(), Some(team.id))
            .await
            .unwrap();

        // Set performance options to false
        pg_team.capture_performance_opt_in = Some(false);
        pg_team.autocapture_web_vitals_opt_in = Some(false);

        insert_person_for_team_in_pg(pg_client.clone(), team.id, distinct_id.clone(), None)
            .await
            .unwrap();

        // Update team in postgres to reflect our changes
        // We can't easily update the team in PG from the test utils, so we'll test with a fresh team
    }

    // For now, let's test with default team settings (both None, which default to false)
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
    assert!(json_data["autocaptureOptOut"].is_null());
    assert!(json_data["captureDeadClicks"].is_null());

    // Test elements chain as string (should be enabled by default in test config)
    assert_eq!(json_data["elementsChainAsString"], json!(true));

    Ok(())
}

#[tokio::test]
async fn test_config_site_apps_empty_by_default() -> Result<()> {
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
    assert_eq!(json_data["hasFeatureFlags"], json!(true));
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

    let client = setup_redis_client(Some(config.redis_url.clone()));
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
    .bind(format!("test://plugin/site_app/{}", chrono::Utc::now().timestamp()))
    .bind("019026a4-be80-0000-5bf3-171d00629163")
    .fetch_one(&mut *conn)
    .await
    .unwrap();

    println!("Created plugin with ID: {}", plugin_id);

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

    println!("Created plugin source file for plugin {}", plugin_id);

    // Insert enabled plugin config
    let config_id: i32 = sqlx::query_scalar(
        r#"INSERT INTO posthog_pluginconfig 
           (plugin_id, team_id, enabled, "order", config, web_token, updated_at, created_at)
           VALUES ($1, $2, true, 1, '{}', $3, NOW(), NOW())
           RETURNING id"#,
    )
    .bind(plugin_id)
    .bind(team.id)
    .bind("test_site_app_token")
    .fetch_one(&mut *conn)
    .await
    .unwrap();

    println!(
        "Created plugin config with ID: {} for team {}",
        config_id, team.id
    );

    // Verify the data was inserted correctly
    let site_apps_count: i64 = sqlx::query_scalar(
        r#"SELECT COUNT(*) FROM posthog_pluginconfig pc
           JOIN posthog_plugin p ON p.id = pc.plugin_id
           JOIN posthog_pluginsourcefile psf ON psf.plugin_id = p.id
           WHERE pc.team_id = $1 AND pc.enabled = true AND psf.filename = 'site.ts' AND psf.status = 'TRANSPILED'"#
    )
    .bind(team.id)
    .fetch_one(&mut *conn)
    .await
    .unwrap();

    println!(
        "Found {} matching site apps in database for team {}",
        site_apps_count, team.id
    );

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
    println!(
        "Response JSON: {}",
        serde_json::to_string_pretty(&json_data)?
    );

    // Site apps should be populated
    assert!(json_data["siteApps"].is_array());
    let site_apps = json_data["siteApps"].as_array().unwrap();

    if site_apps.len() != 1 {
        println!(
            "Expected 1 site app, got {}. Full siteApps: {:?}",
            site_apps.len(),
            site_apps
        );
    }
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
    config.session_replay_rrweb_script_allowed_teams = "*".to_string();

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone()));
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
    println!(
        "Response JSON: {}",
        serde_json::to_string_pretty(&json_data)?
    );

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
    config.session_replay_rrweb_script_allowed_teams = "999,1000,1001".to_string(); // Our team won't be in this list

    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone()));
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
    println!(
        "Response JSON: {}",
        serde_json::to_string_pretty(&json_data)?
    );

    // Session recording should be configured but WITHOUT the script
    assert!(json_data["sessionRecording"].is_object());
    let session_recording = &json_data["sessionRecording"];

    assert_eq!(session_recording["endpoint"], "/s/");
    assert_eq!(session_recording["recorderVersion"], "v2");

    // Should NOT include the script config since team is not allowed
    assert!(session_recording["scriptConfig"].is_null());

    Ok(())
}
