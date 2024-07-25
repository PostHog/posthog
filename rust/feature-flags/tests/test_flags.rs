use anyhow::Result;
use assert_json_diff::assert_json_include;

use reqwest::StatusCode;
use serde_json::{json, Value};

use crate::common::*;

use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::test_utils::{insert_new_team_in_redis, setup_redis_client};

pub mod common;

#[tokio::test]
async fn it_sends_flag_request() -> Result<()> {
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
    let res = server.send_flags_request(payload.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    // We don't want to deserialize the data into a flagResponse struct here,
    // because we want to assert the shape of the raw json data.
    let json_data = res.json::<Value>().await?;

    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorWhileComputingFlags": false,
            "featureFlags": {
                "beta-feature": "variant-1",
                "rollout-flag": "true",
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

    // We don't want to deserialize the data into a flagResponse struct here,
    // because we want to assert the shape of the raw json data.
    let response_text = res.text().await?;

    assert_eq!(
        response_text,
        "failed to decode request: unsupported content type: xyz"
    );

    Ok(())
}
