//! Integration tests for the remote_config endpoint
//! (`GET /api/projects/:project_id/feature_flags/:key/remote_config`).
//!
//! Mirrors the Django contract in
//! `products/feature_flags/backend/api/test/test_feature_flag.py`: project-secret keys
//! get the redacted marker for encrypted payloads, personal keys get plaintext, and
//! lookups are scoped to the project (cross-team -> 403, cross-project -> 404).

mod common;

use feature_flags::{config::Config, utils::test_utils::TestContext};
use serde_json::Value;

// Ciphertext produced by Django's FlagPayloadCodec (see flag_payload_decryptor.rs).
const K1: &str = "ZtTE8u7zKlorOQYJGS8EM2lFggYttXVaqnxWQP-dXEc";
const TOK_PRIMARY: &str = "gAAAAABqKCSqLF1UmKt8anAe6Um8knblGLl8nLyg6qoynbsE398Yl28Nh1xZZmYB8_WKXkO7v3LjHmNOxkYWjLCbLF0gTWR0V7UO4ziqvY43WlYiG1d3ZjQ=";
const PLAINTEXT: &str = r#"{"hello":"world","n":42}"#;
const REDACTED: &str = "\"********* (encrypted)\"";

/// Insert a flag straight into Postgres with full control over the remote-config
/// columns, returning its id. The flag helpers don't expose these columns.
async fn insert_rc_flag(
    context: &TestContext,
    team_id: i32,
    key: &str,
    payload_true: &str,
    is_remote_configuration: bool,
    has_encrypted_payloads: bool,
) -> i32 {
    let mut conn = context.get_non_persons_connection().await.unwrap();
    let filters = serde_json::json!({
        "groups": [{"properties": [], "rollout_percentage": 100}],
        "payloads": {"true": payload_true},
    });
    let row: (i32,) = sqlx::query_as(
        r#"INSERT INTO posthog_featureflag
        (team_id, name, key, filters, deleted, active, ensure_experience_continuity,
         is_remote_configuration, has_encrypted_payloads, created_at)
        VALUES ($1, $2, $3, $4, false, true, false, $5, $6, '2024-06-17')
        RETURNING id"#,
    )
    .bind(team_id)
    .bind(key)
    .bind(key)
    .bind(filters)
    .bind(is_remote_configuration)
    .bind(has_encrypted_payloads)
    .fetch_one(&mut *conn)
    .await
    .unwrap();
    row.0
}

fn url(addr: &std::net::SocketAddr, project_id: i32, key: &str) -> String {
    format!("http://{addr}/api/projects/{project_id}/feature_flags/{key}/remote_config")
}

#[tokio::test]
async fn test_remote_config_project_secret_plaintext_returns_payload() {
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    insert_rc_flag(&context, team.id, "rc-plain", "plain-payload", true, false).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "rc-plain"))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 200);
    assert_eq!(
        response.json::<Value>().await.unwrap(),
        Value::String("plain-payload".to_string())
    );
}

#[tokio::test]
async fn test_remote_config_by_numeric_id_returns_payload() {
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    let flag_id = insert_rc_flag(&context, team.id, "rc-by-id", "plain-payload", true, false).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, &flag_id.to_string()))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 200);
    assert_eq!(
        response.json::<Value>().await.unwrap(),
        Value::String("plain-payload".to_string())
    );
}

#[tokio::test]
async fn test_remote_config_project_secret_encrypted_returns_redacted() {
    let mut config = Config::default_test_config();
    config.flags_secret_keys = K1.to_string();
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    insert_rc_flag(&context, team.id, "rc-enc", TOK_PRIMARY, true, true).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "rc-enc"))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 200);
    // Project-secret callers never get plaintext for encrypted payloads.
    assert_eq!(
        response.json::<Value>().await.unwrap(),
        Value::String(REDACTED.to_string())
    );
}

#[tokio::test]
async fn test_remote_config_personal_key_encrypted_returns_plaintext() {
    let mut config = Config::default_test_config();
    config.flags_secret_keys = K1.to_string();
    let context = TestContext::new(Some(&config)).await;

    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();
    let user_email = TestContext::generate_test_email("rc_pak");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    let (_pak_id, api_key) = context
        .create_personal_api_key(user_id, "RC PAK", vec!["feature_flag:read"], None, None)
        .await
        .unwrap();

    insert_rc_flag(&context, team.id, "rc-enc-pak", TOK_PRIMARY, true, true).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "rc-enc-pak"))
        .header("Authorization", format!("Bearer {api_key}"))
        .send()
        .await
        .unwrap();

    let status = response.status();
    let body = response.json::<Value>().await.unwrap();
    assert_eq!(status, 200, "body: {body}");
    assert_eq!(body, Value::String(PLAINTEXT.to_string()));
}

#[tokio::test]
async fn test_remote_config_cross_team_secret_returns_403() {
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (_team_a, secret_a, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    let (team_b, _secret_b, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    insert_rc_flag(&context, team_b.id, "b-flag", "plain", true, false).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    // team_a's secret key against team_b's project -> team mismatch.
    let response = reqwest::Client::new()
        .get(url(&server.addr, team_b.id, "b-flag"))
        .header("Authorization", format!("Bearer {secret_a}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 403);
}

#[tokio::test]
async fn test_remote_config_cross_project_key_returns_404() {
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team_a, secret_a, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    let (team_b, _secret_b, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    // Flag lives in team_b's project; request it from team_a's project.
    insert_rc_flag(&context, team_b.id, "only-in-b", "plain", true, false).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team_a.id, "only-in-b"))
        .header("Authorization", format!("Bearer {secret_a}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 404);
}

#[tokio::test]
async fn test_remote_config_unknown_flag_returns_404() {
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "does-not-exist"))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 404);
}

#[tokio::test]
async fn test_remote_config_non_remote_config_flag_returns_404() {
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    // A normal (non-remote-config) flag must be invisible here.
    insert_rc_flag(&context, team.id, "normal-flag", "plain", false, false).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "normal-flag"))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 404);
}

#[tokio::test]
async fn test_remote_config_rate_limited_returns_429() {
    let mut config = Config::default_test_config();
    config.remote_config_default_rate_per_minute = 1; // burst of 1, so the 2nd call is limited
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    insert_rc_flag(&context, team.id, "rc-rl", "plain", true, false).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();
    let get = || {
        client
            .get(url(&server.addr, team.id, "rc-rl"))
            .header("Authorization", format!("Bearer {secret_token}"))
            .send()
    };

    assert_eq!(get().await.unwrap().status(), 200);
    assert_eq!(get().await.unwrap().status(), 429);
}

#[tokio::test]
async fn test_remote_config_oversized_project_id_returns_404() {
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (_team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    // project_id > i32::MAX can't name a team: 404 on the secret path too, not 403,
    // matching the personal-key path.
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/99999999999/feature_flags/x/remote_config",
            server.addr
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 404);
}

#[tokio::test]
async fn test_remote_config_oversized_numeric_id_returns_404() {
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    // 20 digits: passes the all-digits check but overflows i64. Must 404, not panic.
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "99999999999999999999"))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 404);
}
