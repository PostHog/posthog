use anyhow::Result;
use assert_json_diff::assert_json_include;

use reqwest::StatusCode;
use serde_json::{json, Value};

use crate::common::*;

use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::utils::test_utils::{
    insert_flags_for_team_in_redis, insert_new_team_in_pg, insert_new_team_in_redis,
    insert_person_for_team_in_pg, setup_pg_reader_client, setup_redis_client,
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

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

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
            "errorWhileComputingFlags": false,
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
    println!("Response text: {:?}", response_text);

    assert!(
        response_text.contains("Failed to decode request: invalid JSON"),
        "Unexpected error message: {:?}",
        response_text
    );
    Ok(())
}

// TODO: we haven't implemented rate limiting in the new endpoint yet
// #[tokio::test]
// async fn it_handles_rate_limiting() -> Result<()> {
//     let config = DEFAULT_TEST_CONFIG.clone();
//     let client = setup_redis_client(Some(config.redis_url.clone()));
//     let team = insert_new_team_in_redis(client.clone()).await.unwrap();
//     let token = team.api_token;
//     let server = ServerHandle::for_config(config).await;

//     // Simulate multiple requests to trigger rate limiting
//     for _ in 0..100 {
//         let payload = json!({
//             "token": token,
//             "distinct_id": "user1",
//             "groups": {"group1": "group1"}
//         });
//         server.send_flags_request(payload.to_string()).await;
//     }

//     // The next request should be rate limited
//     let payload = json!({
//         "token": token,
//         "distinct_id": "user1",
//         "groups": {"group1": "group1"}
//     });
//     let res = server.send_flags_request(payload.to_string()).await;
//     assert_eq!(StatusCode::TOO_MANY_REQUESTS, res.status());
//     assert_eq!(
//         res.text().await?,
//         "Rate limit exceeded. Please reduce your request frequency and try again later."
//     );
//     Ok(())
// }

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

    insert_flags_for_team_in_redis(client, team.id, Some(flag_json.to_string())).await?;

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
            "errorWhileComputingFlags": false,
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

    let res = server.send_flags_request(payload.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorWhileComputingFlags": false,
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
            "errorWhileComputingFlags": false,
            "featureFlags": {
                "property-flag": false
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn it_handles_flag_with_group_properties() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "user_distinct_id".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone()));
    let pg_client = setup_pg_reader_client(None).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
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

    let res = server.send_flags_request(payload.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let json_data = res.json::<Value>().await?;
    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorWhileComputingFlags": false,
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
            "errorWhileComputingFlags": false,
            "featureFlags": {
                "group-flag": false
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn test_feature_flags_json() -> Result<()> {
    // Clone the default test configuration
    let config = DEFAULT_TEST_CONFIG.clone();

    // Define the distinct ID for the person
    let distinct_id = "example_id".to_string();

    // Setup Redis client
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

    // Create a new person with the specified email and store in PostgreSQL
    insert_person_for_team_in_pg(
        pg_client.clone(),
        team.id,
        distinct_id.clone(),
        Some(json!({"email": "tim@posthog.com"})),
    )
    .await?;

    // Define the feature flag with a property filter on email
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
                    "rollout_percentage": null, // Equivalent to None in Rust
                }
            ],
            "payloads": {
                "true": {
                    "color": "blue"
                }
            },
        },
    }]);

    // Insert the feature flag into Redis for the team
    insert_flags_for_team_in_redis(redis_client, team.id, Some(flag_json.to_string())).await?;

    // Initialize the server with the given configuration
    let server = ServerHandle::for_config(config).await;

    // Define the payload for the flags request, specifying API version 3
    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
    });

    // Send the flags request to the server
    let res = server.send_flags_request(payload.to_string()).await;

    // Assert that the response status is 200 OK
    assert_eq!(StatusCode::OK, res.status());

    // Parse the JSON response
    let json_data = res.json::<Value>().await?;

    println!("json_data: {:?}", json_data);

    // Assert that the featureFlagPayloads contains the expected payload
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
async fn test_feature_flags_json_multivariate() -> Result<()> {
    // Clone the default test configuration
    let config = DEFAULT_TEST_CONFIG.clone();

    // Setup Redis and PostgreSQL clients
    let redis_client = setup_redis_client(Some(config.redis_url.clone()));
    let pg_client = setup_pg_reader_client(None).await;

    // Insert a new team into Redis and update app_urls
    let team = insert_new_team_in_redis(redis_client.clone())
        .await
        .expect("Failed to insert new team in Redis");

    // Update the team in PostgreSQL if necessary
    insert_new_team_in_pg(pg_client.clone(), Some(team.id))
        .await
        .expect("Failed to insert new team in PostgreSQL");

    let token = team.api_token.clone();

    // Create a new person with distinct_ids and properties
    insert_person_for_team_in_pg(
        pg_client.clone(),
        team.id,
        "example_id".to_string(),
        Some(json!({"email": "tim@posthog.com"})),
    )
    .await
    .expect("Failed to insert person in PostgreSQL");

    // Define the feature flags
    let feature_flags = json!([
        {
            "id": 1,
            "key": "beta-feature",
            "name": "Beta feature",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "rollout_percentage": 50,
            "created_by": "user_id", // Adjust as needed
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 50
                    }
                ]
            }
        },
        {
            "id": 2,
            "key": "default-flag",
            "name": "This is a feature flag with default params, no filters.",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "rollout_percentage": null,
            "created_by": "user_id", // Adjust as needed
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": null
                    }
                ]
            }
        },
        {
            "id": 3,
            "key": "multivariate-flag",
            "name": "This is a feature flag with multiple variants.",
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "rollout_percentage": null,
            "created_by": "user_id", // Adjust as needed
            "filters": {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": null
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25
                        }
                    ]
                },
                "payloads": {
                    "first-variant": { "color": "blue" }
                }
            }
        }
    ]);

    // Insert the feature flags into Redis for the team
    insert_flags_for_team_in_redis(redis_client, team.id, Some(feature_flags.to_string()))
        .await
        .expect("Failed to insert feature flags into Redis");

    // Initialize the server with the given configuration
    let server = ServerHandle::for_config(config).await;

    {
        let response = server
            .send_flags_request(
                json!({
                    "token": token,
                    "distinct_id": "example_id",
                })
                .to_string(),
            )
            .await;

        assert_eq!(response.status(), StatusCode::OK, "API v3 request failed");

        let json_data = response.json::<Value>().await?;
        assert!(
            json_data.get("featureFlags").is_some(),
            "featureFlags missing in response"
        );
        assert!(
            json_data.get("featureFlagPayloads").is_some(),
            "featureFlagPayloads missing in response"
        );

        // Check the variant of 'multivariate-flag'
        let variant = json_data["featureFlags"]["multivariate-flag"]
            .as_str()
            .expect("multivariate-flag variant is not a string");
        assert!(
            ["first-variant", "second-variant", "third-variant"].contains(&variant),
            "Unexpected variant for multivariate-flag: {}",
            variant
        );

        // Check the payload for 'multivariate-flag'
        let payload = json_data["featureFlagPayloads"]["multivariate-flag"]
            .as_object()
            .expect("Payload for multivariate-flag is not an object");
        assert_eq!(
            payload.get("color"),
            Some(&Value::String("blue".to_string())),
            "Unexpected payload for multivariate-flag"
        );
    }

    Ok(())
}
