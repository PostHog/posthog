use anyhow::Result;
use reqwest::StatusCode;
use serde_json::json;

use crate::common::*;
use feature_flags::config::{Config, FlexBool};
use feature_flags::utils::test_utils::{insert_new_team_in_redis, setup_redis_client, TestContext};

pub mod common;

#[tokio::test]
async fn test_rate_limit_basic() -> Result<()> {
    // Create config with very restrictive rate limiting (capacity: 3, replenish: 0.1/sec)
    let mut config = Config::default_test_config();
    config.flags_rate_limit_enabled = FlexBool(true);
    config.flags_rate_limit_log_only = FlexBool(false); // Actually block requests
    config.flags_bucket_capacity = 3;
    config.flags_bucket_replenish_rate = 0.1;

    // Set up team and token in Redis and Postgres
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(redis_client.clone())
        .await
        .unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, "user123".to_string(), None)
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    // Prepare request payload with valid token
    let payload = json!({
        "token": token,
        "distinct_id": "user123",
    });

    // First 3 requests should succeed (burst capacity)
    for i in 1..=3 {
        let response = client
            .post(format!("http://{}/flags", server.addr))
            .header("content-type", "application/json")
            .json(&payload)
            .send()
            .await?;

        assert_eq!(
            response.status(),
            StatusCode::OK,
            "Request {i} should succeed"
        );
    }

    // 4th request should be rate limited
    let rate_limited_response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .json(&payload)
        .send()
        .await?;

    assert_eq!(
        rate_limited_response.status(),
        StatusCode::TOO_MANY_REQUESTS,
        "4th request should be rate limited"
    );

    // Verify response format matches Python's /decide endpoint
    let response_body: serde_json::Value = rate_limited_response.json().await?;
    assert_eq!(response_body["type"], "validation_error");
    assert_eq!(response_body["code"], "rate_limit_exceeded");
    assert_eq!(response_body["detail"], "Rate limit exceeded");
    assert!(response_body["attr"].is_null());

    Ok(())
}

#[tokio::test]
async fn test_rate_limit_disabled() -> Result<()> {
    // Create config with rate limiting disabled (default)
    let config = Config::default_test_config();
    assert!(!*config.flags_rate_limit_enabled);

    // Set up team and token
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(redis_client.clone())
        .await
        .unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, "user123".to_string(), None)
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    let payload = json!({
        "token": token,
        "distinct_id": "user123",
    });

    // When disabled, all requests should succeed
    for i in 1..=10 {
        let response = client
            .post(format!("http://{}/flags", server.addr))
            .header("content-type", "application/json")
            .json(&payload)
            .send()
            .await?;

        assert_eq!(
            response.status(),
            StatusCode::OK,
            "Request {i} should succeed when rate limiting is disabled"
        );
    }

    Ok(())
}

#[tokio::test]
async fn test_rate_limit_per_token_isolation() -> Result<()> {
    // Create config with capacity of 1
    let mut config = Config::default_test_config();
    config.flags_rate_limit_enabled = FlexBool(true);
    config.flags_rate_limit_log_only = FlexBool(false);
    config.flags_bucket_capacity = 1;
    config.flags_bucket_replenish_rate = 0.1;

    // Set up two teams with different tokens
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team1 = insert_new_team_in_redis(redis_client.clone())
        .await
        .unwrap();
    let token1 = team1.api_token.clone();

    let team2 = insert_new_team_in_redis(redis_client.clone())
        .await
        .unwrap();
    let token2 = team2.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team1.id)).await.unwrap();
    context
        .insert_person(team1.id, "user1".to_string(), None)
        .await
        .unwrap();
    context.insert_new_team(Some(team2.id)).await.unwrap();
    context
        .insert_person(team2.id, "user2".to_string(), None)
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    let payload1 = json!({
        "token": token1,
        "distinct_id": "user1",
    });

    let payload2 = json!({
        "token": token2,
        "distinct_id": "user2",
    });

    // First token's first request should succeed
    let response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .json(&payload1)
        .send()
        .await?;

    assert_eq!(response.status(), StatusCode::OK);

    // First token's second request should be rate limited
    let response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .json(&payload1)
        .send()
        .await?;

    assert_eq!(response.status(), StatusCode::TOO_MANY_REQUESTS);

    // Second token's first request should succeed (different bucket)
    let response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .json(&payload2)
        .send()
        .await?;

    assert_eq!(response.status(), StatusCode::OK);

    // Second token's second request should be rate limited
    let response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .json(&payload2)
        .send()
        .await?;

    assert_eq!(response.status(), StatusCode::TOO_MANY_REQUESTS);

    Ok(())
}

#[tokio::test]
async fn test_rate_limit_with_invalid_tokens() -> Result<()> {
    // Create config with very restrictive rate limiting
    let mut config = Config::default_test_config();
    config.flags_rate_limit_enabled = FlexBool(true);
    config.flags_rate_limit_log_only = FlexBool(false);
    config.flags_bucket_capacity = 3;
    config.flags_bucket_replenish_rate = 0.01;

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    let payload = json!({
        "token": "invalid_token",
        "distinct_id": "user123",
    });

    // First 3 requests with invalid token should return 401 (not rate limited yet)
    for i in 1..=3 {
        let response = client
            .post(format!("http://{}/flags", server.addr))
            .header("content-type", "application/json")
            .json(&payload)
            .send()
            .await?;

        // Rate limiting happens before authentication
        // So the first 3 requests pass rate limit but fail authentication
        assert_eq!(
            response.status(),
            StatusCode::UNAUTHORIZED,
            "Request {i} should fail authentication"
        );
    }

    // 4th request should be rate limited (before authentication)
    let rate_limited_response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .json(&payload)
        .send()
        .await?;

    assert_eq!(
        rate_limited_response.status(),
        StatusCode::TOO_MANY_REQUESTS,
        "4th request should be rate limited before authentication"
    );

    let response_body: serde_json::Value = rate_limited_response.json().await?;
    assert_eq!(response_body["code"], "rate_limit_exceeded");

    Ok(())
}

#[tokio::test]
async fn test_rate_limit_ip_fallback_on_malformed_body() -> Result<()> {
    // Test that IP is used for rate limiting when body parsing fails
    let mut config = Config::default_test_config();
    config.flags_rate_limit_enabled = FlexBool(true);
    config.flags_rate_limit_log_only = FlexBool(false);
    config.flags_bucket_capacity = 2;
    config.flags_bucket_replenish_rate = 0.1;

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    // Send malformed JSON body
    let malformed_body = "not valid json";

    // First 2 requests should pass rate limit (but fail parsing)
    for i in 1..=2 {
        let response = client
            .post(format!("http://{}/flags", server.addr))
            .header("content-type", "application/json")
            .body(malformed_body)
            .send()
            .await?;

        // Should get some error (not rate limited)
        assert_ne!(
            response.status(),
            StatusCode::TOO_MANY_REQUESTS,
            "Request {i} should not be rate limited (falls back to IP)"
        );
    }

    // 3rd request should be rate limited (IP-based bucket exhausted)
    let rate_limited_response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .body(malformed_body)
        .send()
        .await?;

    assert_eq!(
        rate_limited_response.status(),
        StatusCode::TOO_MANY_REQUESTS,
        "3rd request should be rate limited using IP as key"
    );

    Ok(())
}

#[tokio::test]
async fn test_rate_limit_replenishment() -> Result<()> {
    // Test that rate limit replenishes over time
    let mut config = Config::default_test_config();
    config.flags_rate_limit_enabled = FlexBool(true);
    config.flags_rate_limit_log_only = FlexBool(false);
    config.flags_bucket_capacity = 1;
    config.flags_bucket_replenish_rate = 1.0; // 1 token per second

    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(redis_client.clone())
        .await
        .unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, "user123".to_string(), None)
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    let payload = json!({
        "token": token,
        "distinct_id": "user123",
    });

    // First request should succeed
    let response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .json(&payload)
        .send()
        .await?;

    assert_eq!(response.status(), StatusCode::OK, "First request allowed");

    // Second request should be rate limited
    let response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .json(&payload)
        .send()
        .await?;

    assert_eq!(
        response.status(),
        StatusCode::TOO_MANY_REQUESTS,
        "Second request blocked"
    );

    // Wait for token to replenish (1 second + buffer)
    tokio::time::sleep(tokio::time::Duration::from_millis(1100)).await;

    // Third request should succeed after replenishment
    let response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .json(&payload)
        .send()
        .await?;

    assert_eq!(
        response.status(),
        StatusCode::OK,
        "Third request allowed after replenishment"
    );

    Ok(())
}

#[tokio::test]
async fn test_ip_rate_limit_basic() -> Result<()> {
    // Create config with IP rate limiting enabled
    let mut config = Config::default_test_config();
    config.flags_ip_rate_limit_enabled = FlexBool(true);
    config.flags_ip_rate_limit_log_only = FlexBool(false);
    config.flags_ip_burst_size = 3;
    config.flags_ip_replenish_rate = 0.1;

    // Set up team and token
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(redis_client.clone())
        .await
        .unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, "user123".to_string(), None)
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    let payload = json!({
        "token": token,
        "distinct_id": "user123",
    });

    // First 3 requests should succeed (IP burst capacity)
    for i in 1..=3 {
        let response = client
            .post(format!("http://{}/flags", server.addr))
            .header("content-type", "application/json")
            .json(&payload)
            .send()
            .await?;

        assert_eq!(
            response.status(),
            StatusCode::OK,
            "Request {i} should succeed"
        );
    }

    // 4th request should be rate limited by IP
    let rate_limited_response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .json(&payload)
        .send()
        .await?;

    assert_eq!(
        rate_limited_response.status(),
        StatusCode::TOO_MANY_REQUESTS,
        "4th request should be rate limited by IP"
    );

    // Verify JSON response format matches token-based rate limiter
    let error_json: serde_json::Value = rate_limited_response.json().await?;
    assert_eq!(error_json["type"], "validation_error");
    assert_eq!(error_json["code"], "rate_limit_exceeded");
    assert_eq!(error_json["detail"], "Rate limit exceeded");

    Ok(())
}

#[tokio::test]
async fn test_ip_rate_limit_with_rotating_tokens() -> Result<()> {
    // Test that IP rate limiting prevents DDoS with rotating fake tokens
    let mut config = Config::default_test_config();
    config.flags_ip_rate_limit_enabled = FlexBool(true);
    config.flags_ip_rate_limit_log_only = FlexBool(false);
    config.flags_ip_burst_size = 5;
    config.flags_ip_replenish_rate = 0.1;

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    // Send 5 requests with different fake tokens (all from same IP)
    for i in 1..=5 {
        let payload = json!({
            "token": format!("fake_token_{i}"),
            "distinct_id": "user123",
        });

        let response = client
            .post(format!("http://{}/flags", server.addr))
            .header("content-type", "application/json")
            .json(&payload)
            .send()
            .await?;

        // These will fail authentication, but should pass IP rate limit
        assert_ne!(
            response.status(),
            StatusCode::TOO_MANY_REQUESTS,
            "Request {i} with fake token should not be IP rate limited yet"
        );
    }

    // 6th request should be IP rate limited (regardless of token)
    let payload = json!({
        "token": "fake_token_6",
        "distinct_id": "user123",
    });

    let rate_limited_response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .json(&payload)
        .send()
        .await?;

    assert_eq!(
        rate_limited_response.status(),
        StatusCode::TOO_MANY_REQUESTS,
        "6th request should be IP rate limited despite different token"
    );

    Ok(())
}

#[tokio::test]
async fn test_both_rate_limiters_together() -> Result<()> {
    // Test that both token-based and IP-based rate limiting work together
    let mut config = Config::default_test_config();
    config.flags_rate_limit_enabled = FlexBool(true);
    config.flags_rate_limit_log_only = FlexBool(false);
    config.flags_bucket_capacity = 2;
    config.flags_bucket_replenish_rate = 0.1;
    config.flags_ip_rate_limit_enabled = FlexBool(true);
    config.flags_ip_rate_limit_log_only = FlexBool(false);
    config.flags_ip_burst_size = 10;
    config.flags_ip_replenish_rate = 1.0;

    // Set up team and token
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(redis_client.clone())
        .await
        .unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, "user123".to_string(), None)
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    let payload = json!({
        "token": token,
        "distinct_id": "user123",
    });

    // First 2 requests should succeed (token bucket capacity)
    for i in 1..=2 {
        let response = client
            .post(format!("http://{}/flags", server.addr))
            .header("content-type", "application/json")
            .json(&payload)
            .send()
            .await?;

        assert_eq!(
            response.status(),
            StatusCode::OK,
            "Request {i} should succeed"
        );
    }

    // 3rd request should be rate limited by token (not IP, since IP limit is 10)
    let rate_limited_response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .json(&payload)
        .send()
        .await?;

    assert_eq!(
        rate_limited_response.status(),
        StatusCode::TOO_MANY_REQUESTS,
        "3rd request should be rate limited by token"
    );

    // Response should be the token-based rate limit error format
    let response_body: serde_json::Value = rate_limited_response.json().await?;
    assert_eq!(response_body["type"], "validation_error");
    assert_eq!(response_body["code"], "rate_limit_exceeded");

    Ok(())
}

#[tokio::test]
async fn test_ip_rate_limit_disabled() -> Result<()> {
    // Verify IP rate limiting is disabled by default
    let mut config = Config::default_test_config();
    config.flags_ip_rate_limit_enabled = FlexBool(false);

    // Set up team and token
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(redis_client.clone())
        .await
        .unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, "user123".to_string(), None)
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    let payload = json!({
        "token": token,
        "distinct_id": "user123",
    });

    // Should be able to make many requests without IP rate limiting
    for i in 1..=20 {
        let response = client
            .post(format!("http://{}/flags", server.addr))
            .header("content-type", "application/json")
            .json(&payload)
            .send()
            .await?;

        assert_eq!(
            response.status(),
            StatusCode::OK,
            "Request {i} should succeed when IP rate limiting is disabled"
        );
    }

    Ok(())
}

#[tokio::test]
async fn test_ip_rate_limit_respects_x_forwarded_for() -> Result<()> {
    // Test that IP rate limiting uses X-Forwarded-For header (production scenario)
    let mut config = Config::default_test_config();
    config.flags_ip_rate_limit_enabled = FlexBool(true);
    config.flags_ip_rate_limit_log_only = FlexBool(false);
    config.flags_ip_burst_size = 2;
    config.flags_ip_replenish_rate = 0.1;

    // Set up team and token
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(redis_client.clone())
        .await
        .unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, "user123".to_string(), None)
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    let payload = json!({
        "token": token,
        "distinct_id": "user123",
    });

    // Simulate requests from two different client IPs via X-Forwarded-For
    let client_ip_1 = "203.0.113.1"; // Test IP 1
    let client_ip_2 = "203.0.113.2"; // Test IP 2

    // Client IP 1: First 2 requests should succeed
    for i in 1..=2 {
        let response = client
            .post(format!("http://{}/flags", server.addr))
            .header("content-type", "application/json")
            .header("X-Forwarded-For", client_ip_1)
            .json(&payload)
            .send()
            .await?;

        assert_eq!(
            response.status(),
            StatusCode::OK,
            "Client IP 1 request {i} should succeed"
        );
    }

    // Client IP 1: 3rd request should be rate limited
    let response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .header("X-Forwarded-For", client_ip_1)
        .json(&payload)
        .send()
        .await?;

    assert_eq!(
        response.status(),
        StatusCode::TOO_MANY_REQUESTS,
        "Client IP 1 should be rate limited after 2 requests"
    );

    // Client IP 2: Should have its own separate rate limit bucket
    for i in 1..=2 {
        let response = client
            .post(format!("http://{}/flags", server.addr))
            .header("content-type", "application/json")
            .header("X-Forwarded-For", client_ip_2)
            .json(&payload)
            .send()
            .await?;

        assert_eq!(
            response.status(),
            StatusCode::OK,
            "Client IP 2 request {i} should succeed (separate bucket)"
        );
    }

    // Client IP 2: 3rd request should be rate limited
    let response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .header("X-Forwarded-For", client_ip_2)
        .json(&payload)
        .send()
        .await?;

    assert_eq!(
        response.status(),
        StatusCode::TOO_MANY_REQUESTS,
        "Client IP 2 should be rate limited after 2 requests"
    );

    Ok(())
}

#[tokio::test]
async fn test_token_rate_limit_log_only_mode() -> Result<()> {
    // Test that token-based rate limiting in log-only mode allows requests through
    let mut config = Config::default_test_config();
    config.flags_rate_limit_enabled = FlexBool(true);
    config.flags_rate_limit_log_only = FlexBool(true); // Log-only mode
    config.flags_bucket_capacity = 2;
    config.flags_bucket_replenish_rate = 0.1;

    // Set up team and token
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(redis_client.clone())
        .await
        .unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, "user123".to_string(), None)
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    let payload = json!({
        "token": token,
        "distinct_id": "user123",
    });

    // First 2 requests should succeed (within capacity)
    for i in 1..=2 {
        let response = client
            .post(format!("http://{}/flags", server.addr))
            .header("content-type", "application/json")
            .json(&payload)
            .send()
            .await?;

        assert_eq!(
            response.status(),
            StatusCode::OK,
            "Request {i} should succeed"
        );
    }

    // Requests 3-5 should also succeed despite exceeding rate limit (log-only mode)
    for i in 3..=5 {
        let response = client
            .post(format!("http://{}/flags", server.addr))
            .header("content-type", "application/json")
            .json(&payload)
            .send()
            .await?;

        assert_eq!(
            response.status(),
            StatusCode::OK,
            "Request {i} should succeed in log-only mode despite exceeding rate limit"
        );
    }

    Ok(())
}

#[tokio::test]
async fn test_ip_rate_limit_log_only_mode() -> Result<()> {
    // Test that IP-based rate limiting in log-only mode allows requests through
    let mut config = Config::default_test_config();
    config.flags_ip_rate_limit_enabled = FlexBool(true);
    config.flags_ip_rate_limit_log_only = FlexBool(true); // Log-only mode
    config.flags_ip_burst_size = 2;
    config.flags_ip_replenish_rate = 0.1;

    // Set up team and token
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(redis_client.clone())
        .await
        .unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, "user123".to_string(), None)
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    let payload = json!({
        "token": token,
        "distinct_id": "user123",
    });

    // First 2 requests should succeed (within capacity)
    for i in 1..=2 {
        let response = client
            .post(format!("http://{}/flags", server.addr))
            .header("content-type", "application/json")
            .json(&payload)
            .send()
            .await?;

        assert_eq!(
            response.status(),
            StatusCode::OK,
            "Request {i} should succeed"
        );
    }

    // Requests 3-5 should also succeed despite exceeding IP rate limit (log-only mode)
    for i in 3..=5 {
        let response = client
            .post(format!("http://{}/flags", server.addr))
            .header("content-type", "application/json")
            .json(&payload)
            .send()
            .await?;

        assert_eq!(
            response.status(),
            StatusCode::OK,
            "Request {i} should succeed in log-only mode despite exceeding IP rate limit"
        );
    }

    Ok(())
}

#[tokio::test]
async fn test_mixed_log_only_modes() -> Result<()> {
    // Test IP rate limiting in enforced mode while token rate limiting is in log-only mode
    let mut config = Config::default_test_config();
    config.flags_rate_limit_enabled = FlexBool(true);
    config.flags_rate_limit_log_only = FlexBool(true); // Token: log-only
    config.flags_bucket_capacity = 1;
    config.flags_bucket_replenish_rate = 0.1;
    config.flags_ip_rate_limit_enabled = FlexBool(true);
    config.flags_ip_rate_limit_log_only = FlexBool(false); // IP: enforced
    config.flags_ip_burst_size = 3;
    config.flags_ip_replenish_rate = 0.1;

    // Set up team and token
    let redis_client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(redis_client.clone())
        .await
        .unwrap();
    let token = team.api_token.clone();

    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(team.id, "user123".to_string(), None)
        .await
        .unwrap();

    let server = ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    let payload = json!({
        "token": token,
        "distinct_id": "user123",
    });

    // First 3 requests should succeed (within IP burst capacity)
    for i in 1..=3 {
        let response = client
            .post(format!("http://{}/flags", server.addr))
            .header("content-type", "application/json")
            .json(&payload)
            .send()
            .await?;

        assert_eq!(
            response.status(),
            StatusCode::OK,
            "Request {i} should succeed (within IP limit)"
        );
    }

    // 4th request should be rate limited by IP (enforced mode)
    // even though token rate limiting is in log-only mode
    let response = client
        .post(format!("http://{}/flags", server.addr))
        .header("content-type", "application/json")
        .json(&payload)
        .send()
        .await?;

    assert_eq!(
        response.status(),
        StatusCode::TOO_MANY_REQUESTS,
        "4th request should be IP rate limited (enforced mode takes precedence)"
    );

    Ok(())
}
