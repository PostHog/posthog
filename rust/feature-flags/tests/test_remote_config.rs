//! Integration tests for the remote_config endpoint
//! (`GET /api/projects/:project_id/feature_flags/:key/remote_config`).
//!
//! Mirrors the Django contract in
//! `products/feature_flags/backend/api/test/test_feature_flag.py`: project-secret keys
//! get the redacted marker for encrypted payloads, personal keys get plaintext, and
//! lookups are scoped to the project (cross-team -> 403, cross-project -> 404).

mod common;

use feature_flags::{
    config::Config,
    utils::test_utils::{
        setup_redis_client, update_team_in_hypercache_without_project_id, TestContext,
    },
};
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
    let filters = serde_json::json!({
        "groups": [{"properties": [], "rollout_percentage": 100}],
        "payloads": {"true": payload_true},
    });
    insert_flag_with_filters(
        context,
        team_id,
        key,
        filters,
        is_remote_configuration,
        has_encrypted_payloads,
    )
    .await
}

/// Like `insert_rc_flag` but with full control over the `filters` JSON — used for the rare
/// shape of an encrypted flag whose `payloads` map has no `"true"` entry.
async fn insert_flag_with_filters(
    context: &TestContext,
    team_id: i32,
    key: &str,
    filters: Value,
    is_remote_configuration: bool,
    has_encrypted_payloads: bool,
) -> i32 {
    let mut conn = context.get_non_persons_connection().await.unwrap();
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

/// Poll until `last_used_at` is set for the given PAK, or panic after ~4s. (Replicated from
/// test_flag_definitions.rs — integration test binaries can't share helpers.)
async fn poll_for_pak_last_used_at(context: &TestContext, pak_id: &str, message: &str) {
    use tokio::time::{sleep, Duration};
    let mut conn = context.get_non_persons_connection().await.unwrap();
    for _ in 0..80 {
        let count: (i64,) = sqlx::query_as(
            "SELECT COUNT(*) FROM posthog_personalapikey WHERE id = $1 AND last_used_at IS NOT NULL",
        )
        .bind(pak_id)
        .fetch_one(&mut *conn)
        .await
        .unwrap();
        if count.0 > 0 {
            return;
        }
        sleep(Duration::from_millis(50)).await;
    }
    panic!("{message}");
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
async fn test_remote_config_api_key_alias_resolves_project() {
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    context.populate_cache_for_team(team.id).await.unwrap();
    insert_rc_flag(&context, team.id, "rc-apikey", "plain-payload", true, false).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    // Django accepts ?api_key= as an alias for ?token=.
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/@current/feature_flags/rc-apikey/remote_config?api_key={}",
            server.addr, team.api_token
        ))
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
async fn test_remote_config_empty_token_falls_through_to_numeric_segment() {
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    insert_rc_flag(
        &context,
        team.id,
        "rc-emptytok",
        "plain-payload",
        true,
        false,
    )
    .await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    // Empty ?token= is treated as absent (Django's get_token), so the numeric segment wins.
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/{}/feature_flags/rc-emptytok/remote_config?token=",
            server.addr, team.id
        ))
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
async fn test_remote_config_personal_key_rate_limited_returns_429() {
    let mut config = Config::default_test_config();
    config.remote_config_default_rate_per_minute = 1; // burst of 1, so the 2nd call is limited
    let context = TestContext::new(Some(&config)).await;
    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();
    let user_email = TestContext::generate_test_email("rc_rl");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    let (_pak_id, api_key) = context
        .create_personal_api_key(user_id, "RC RL", vec!["feature_flag:read"], None, None)
        .await
        .unwrap();
    insert_rc_flag(&context, team.id, "rc-rl", "plain", true, false).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();
    let get = || {
        client
            .get(url(&server.addr, team.id, "rc-rl"))
            .header("Authorization", format!("Bearer {api_key}"))
            .send()
    };

    // Django throttles personal-API-key requests, bucketed per credential.
    assert_eq!(get().await.unwrap().status(), 200);
    assert_eq!(get().await.unwrap().status(), 429);
}

#[tokio::test]
async fn test_remote_config_secret_key_not_throttled() {
    let mut config = Config::default_test_config();
    config.remote_config_default_rate_per_minute = 1; // would 429 a throttled credential
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    insert_rc_flag(&context, team.id, "rc-sk", "plain", true, false).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();
    let get = || {
        client
            .get(url(&server.addr, team.id, "rc-sk"))
            .header("Authorization", format!("Bearer {secret_token}"))
            .send()
    };

    // Django's RemoteConfigThrottle only throttles personal keys, so secret-key requests are
    // never limited even past the per-minute rate.
    assert_eq!(get().await.unwrap().status(), 200);
    assert_eq!(get().await.unwrap().status(), 200);
    assert_eq!(get().await.unwrap().status(), 200);
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
async fn test_remote_config_nonexistent_project_secret_returns_404() {
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (_team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    // In-range project_id that names no team: 404 (not 403) on the secret path, matching
    // Django and the personal-key path. 2000000000 < i32::MAX and won't collide with a
    // sequence-assigned test team id.
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/2000000000/feature_flags/x/remote_config",
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

#[tokio::test]
async fn test_remote_config_at_current_with_token_resolves_project() {
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    context.populate_cache_for_team(team.id).await.unwrap();
    insert_rc_flag(
        &context,
        team.id,
        "rc-current",
        "plain-payload",
        true,
        false,
    )
    .await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    // How every server SDK calls this: `@current` segment + a `?token=` project key.
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/@current/feature_flags/rc-current/remote_config?token={}",
            server.addr, team.api_token
        ))
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
async fn test_remote_config_at_current_secret_token_resolves_project() {
    // `@current` with no `?token=`, authenticated by a team secret token: the project resolves
    // from the credential's own team (Django: `team_from_request`). This server-SDK shape
    // previously 404'd before auth.
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    insert_rc_flag(
        &context,
        team.id,
        "rc-current-secret",
        "plain-payload",
        true,
        false,
    )
    .await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/@current/feature_flags/rc-current-secret/remote_config",
            server.addr
        ))
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
async fn test_remote_config_at_current_personal_key_resolves_current_team() {
    // `@current` with no `?token=`, authenticated by a personal API key: the project resolves
    // from the key user's current team (Django: `user.current_team`). This is how server SDKs
    // fetch remote config with a personal key, and it previously 404'd before auth.
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();
    let user_email = TestContext::generate_test_email("rc_current_pak");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    let (_pak_id, api_key) = context
        .create_personal_api_key(user_id, "RC Current", vec!["feature_flag:read"], None, None)
        .await
        .unwrap();
    insert_rc_flag(
        &context,
        team.id,
        "rc-current-pak",
        "plain-payload",
        true,
        false,
    )
    .await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/@current/feature_flags/rc-current-pak/remote_config",
            server.addr
        ))
        .header("Authorization", format!("Bearer {api_key}"))
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
async fn test_remote_config_at_current_without_credentials_returns_401() {
    // `@current` with neither a `?token=` nor a bearer credential cannot resolve a project and is
    // unauthenticated (Django: AuthenticationFailed) — resolution must not leak as a 404.
    let config = Config::default_test_config();
    let _context = TestContext::new(Some(&config)).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/@current/feature_flags/whatever/remote_config",
            server.addr
        ))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 401);
}

#[tokio::test]
async fn test_remote_config_at_current_invalid_personal_key_returns_401() {
    // `@current` with a personal-key-shaped bearer that doesn't exist must be 401 (invalid
    // credential), not 404: an unknown key can't resolve a project, but it's an auth failure
    // rather than a missing project, matching the numeric-id path and Django.
    let config = Config::default_test_config();
    let _context = TestContext::new(Some(&config)).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/@current/feature_flags/whatever/remote_config",
            server.addr
        ))
        .header("Authorization", "Bearer phx_nonexistent_key")
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 401);
}

#[tokio::test]
async fn test_remote_config_at_current_resolves_then_404s_missing_flag() {
    // `@current` resolves the project from the credential, then a flag that doesn't exist (or
    // isn't a remote-config flag) still 404s — the resolution must not over-serve.
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (_team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/@current/feature_flags/does-not-exist/remote_config",
            server.addr
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 404);
}

#[tokio::test]
async fn test_remote_config_token_override_cross_team_returns_403() {
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
    context.populate_cache_for_team(team_b.id).await.unwrap();
    insert_rc_flag(&context, team_b.id, "b-flag", "plain", true, false).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    // ?token resolves the project to team_b, but the secret key is team_a's -> 403.
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/@current/feature_flags/b-flag/remote_config?token={}",
            server.addr, team_b.api_token
        ))
        .header("Authorization", format!("Bearer {secret_a}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 403);
}

#[tokio::test]
async fn test_remote_config_invalid_token_returns_401() {
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (_team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/@current/feature_flags/x/remote_config?token=phc_does_not_exist",
            server.addr
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 401);
}

#[tokio::test]
async fn test_remote_config_no_auth_returns_401() {
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team, _secret, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    insert_rc_flag(&context, team.id, "rc-noauth", "plain", true, false).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "rc-noauth"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 401);
}

#[tokio::test]
async fn test_remote_config_personal_key_without_flag_scopes_denied() {
    let mut config = Config::default_test_config();
    config.flags_secret_keys = K1.to_string();
    let context = TestContext::new(Some(&config)).await;

    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();
    let user_email = TestContext::generate_test_email("rc_noscope");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    // Key with a non-flag scope: must be denied and never see the decrypted payload.
    let (_pak_id, api_key) = context
        .create_personal_api_key(user_id, "RC NoScope", vec!["dashboard:read"], None, None)
        .await
        .unwrap();
    insert_rc_flag(&context, team.id, "rc-enc-noscope", TOK_PRIMARY, true, true).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "rc-enc-noscope"))
        .header("Authorization", format!("Bearer {api_key}"))
        .send()
        .await
        .unwrap();

    let status = response.status();
    let body = response.text().await.unwrap();
    assert_eq!(status, 403, "body: {body}");
    // The deny path must never leak plaintext (PLAINTEXT is `{"hello":"world",...}`).
    assert!(!body.contains("world"), "leaked plaintext: {body}");
}

#[tokio::test]
async fn test_remote_config_empty_payload_returns_empty_body() {
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    // Empty stored payload is falsy: Django renders `Response(None)` as an empty body.
    insert_rc_flag(&context, team.id, "rc-empty", "", true, false).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "rc-empty"))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 200);
    // Empty body, not the JSON literal "null".
    assert_eq!(response.text().await.unwrap(), "");
}

#[tokio::test]
async fn test_remote_config_head_returns_200() {
    let config = Config::default_test_config();
    let _context = TestContext::new(Some(&config)).await;
    let server = common::ServerHandle::for_config(config.clone()).await;
    // HEAD is handled before auth here (no credential needed). This diverges from Django, which
    // maps HEAD to the GET action and would 401 an unauthenticated HEAD -- but no SDK sends HEAD.
    let response = reqwest::Client::new()
        .head(format!(
            "http://{}/api/projects/1/feature_flags/x/remote_config",
            server.addr
        ))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 200);
}

#[tokio::test]
async fn test_remote_config_options_preflight_returns_200() {
    let config = Config::default_test_config();
    let _context = TestContext::new(Some(&config)).await;
    let server = common::ServerHandle::for_config(config.clone()).await;
    // The service's permissive CORS layer answers an OPTIONS preflight with 200 before the
    // handler runs (so this never reaches `handle_non_get_method`). 200 also matches Django's
    // OPTIONS, so phase 2 won't flag it.
    let response = reqwest::Client::new()
        .request(
            reqwest::Method::OPTIONS,
            format!(
                "http://{}/api/projects/1/feature_flags/x/remote_config",
                server.addr
            ),
        )
        .header("Origin", "https://example.com")
        .header("Access-Control-Request-Method", "GET")
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 200);
    let allow_methods = response
        .headers()
        .get("access-control-allow-methods")
        .and_then(|v| v.to_str().ok())
        .unwrap_or_default();
    assert!(
        allow_methods.contains("GET"),
        "access-control-allow-methods was: {allow_methods:?}"
    );
}

#[tokio::test]
async fn test_remote_config_encrypted_missing_true_returns_empty_body() {
    // An encrypted flag whose payloads map has no "true" entry: Django 500s (KeyError) but we
    // return an empty body. The secret-key path must NOT emit the redacted marker when there is
    // nothing to redact.
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    let filters = serde_json::json!({
        "groups": [{"properties": [], "rollout_percentage": 100}],
        "payloads": {},
    });
    insert_flag_with_filters(&context, team.id, "rc-no-true", filters, true, true).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "rc-no-true"))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 200);
    assert_eq!(response.text().await.unwrap(), "");
}

#[tokio::test]
async fn test_remote_config_at_current_token_personal_key_returns_plaintext() {
    // The SDK hot path for encrypted flags: `@current` + a `?token=` project key + a personal
    // API key. The token resolves the project and the resolved team is threaded into auth, so
    // this exercises the personal-key branch of the `?token=` path (untested by the others).
    let mut config = Config::default_test_config();
    config.flags_secret_keys = K1.to_string();
    let context = TestContext::new(Some(&config)).await;

    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();
    let user_email = TestContext::generate_test_email("rc_current_pak");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    let (_pak_id, api_key) = context
        .create_personal_api_key(
            user_id,
            "RC Current PAK",
            vec!["feature_flag:read"],
            None,
            None,
        )
        .await
        .unwrap();
    insert_rc_flag(&context, team.id, "rc-current-pak", TOK_PRIMARY, true, true).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/@current/feature_flags/rc-current-pak/remote_config?token={}",
            server.addr, team.api_token
        ))
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
async fn test_remote_config_cross_org_personal_key_denied() {
    // A personal key from another org must not read (or decrypt) a flag in a project it can't
    // access, even via `?token=`. The org-membership check rejects it before any payload is
    // returned, pinning that auth validates against the token-resolved team, not the key's own.
    let mut config = Config::default_test_config();
    config.flags_secret_keys = K1.to_string();
    let context = TestContext::new(Some(&config)).await;

    // Team A holds the encrypted flag; the caller's key belongs to org B.
    let team_a = context.insert_new_team(None).await.unwrap();
    let team_b = context
        .insert_new_team_with_org(None, "0b0b0b0b-0000-0000-0000-0000000b0002")
        .await
        .unwrap();
    let org_b = context.get_organization_id_for_team(&team_b).await.unwrap();
    let user_email = TestContext::generate_test_email("rc_xorg");
    let user_id = context
        .create_user(&user_email, &org_b, team_b.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_b, 15)
        .await
        .unwrap();
    let (_pak_id, api_key) = context
        .create_personal_api_key(user_id, "RC XOrg", vec!["feature_flag:read"], None, None)
        .await
        .unwrap();
    insert_rc_flag(&context, team_a.id, "rc-xorg", TOK_PRIMARY, true, true).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/@current/feature_flags/rc-xorg/remote_config?token={}",
            server.addr, team_a.api_token
        ))
        .header("Authorization", format!("Bearer {api_key}"))
        .send()
        .await
        .unwrap();

    let status = response.status();
    let body = response.text().await.unwrap();
    // Not a member of team A's org -> PersonalApiKeyInvalid -> 401, and the body must never leak
    // the decrypted plaintext (`{"hello":"world",...}`).
    assert_eq!(status, 401, "body: {body}");
    assert!(!body.contains("world"), "leaked plaintext: {body}");
}

#[tokio::test]
async fn test_remote_config_personal_key_updates_last_used_at() {
    // A key used only for remote config must still get last_used_at set, or it looks dormant and
    // could be rotated as unused (Django tracks this; flag_definitions ports it too).
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();
    let user_email = TestContext::generate_test_email("rc_lastused");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    let (pak_id, api_key) = context
        .create_personal_api_key(
            user_id,
            "RC LastUsed",
            vec!["feature_flag:read"],
            None,
            None,
        )
        .await
        .unwrap();
    insert_rc_flag(&context, team.id, "rc-lastused", "plain", true, false).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "rc-lastused"))
        .header("Authorization", format!("Bearer {api_key}"))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);

    poll_for_pak_last_used_at(
        &context,
        &pak_id,
        "Timed out waiting for last_used_at to be set for the remote_config PAK",
    )
    .await;
}

#[tokio::test]
async fn test_remote_config_skip_writes_does_not_update_last_used_at() {
    // The shared State::record_pak_last_used helper must honor skip_writes: with it on, a
    // personal-key request still authenticates (200) but records no last_used_at. Complements
    // test_remote_config_personal_key_updates_last_used_at, which covers the write path.
    let mut config = Config::default_test_config();
    config.skip_writes = feature_flags::config::FlexBool(true);
    let context = TestContext::new(Some(&config)).await;

    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();
    let user_email = TestContext::generate_test_email("rc_skipwrites");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    let (pak_id, api_key) = context
        .create_personal_api_key(
            user_id,
            "RC SkipWrites",
            vec!["feature_flag:read"],
            None,
            None,
        )
        .await
        .unwrap();
    insert_rc_flag(&context, team.id, "rc-skipwrites", "plain", true, false).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "rc-skipwrites"))
        .header("Authorization", format!("Bearer {api_key}"))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);

    // skip_writes returns before any write is scheduled, so last_used_at stays NULL. A brief
    // settle window guards against a stray async write sneaking in.
    tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    let mut conn = context.get_non_persons_connection().await.unwrap();
    let count: (i64,) = sqlx::query_as(
        "SELECT COUNT(*) FROM posthog_personalapikey WHERE id = $1 AND last_used_at IS NOT NULL",
    )
    .bind(&pak_id)
    .fetch_one(&mut *conn)
    .await
    .unwrap();
    assert_eq!(
        count.0, 0,
        "last_used_at must stay NULL when skip_writes is on"
    );
}

#[tokio::test]
async fn test_remote_config_token_without_auth_returns_401() {
    // A public ?token= with no bearer is rejected at auth (401). The project/flag DB lookups are
    // deferred until after auth, so an unauthenticated caller can't drive reads off a public token.
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team, _secret, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    insert_rc_flag(&context, team.id, "rc-tok-noauth", "plain", true, false).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/@current/feature_flags/rc-tok-noauth/remote_config?token={}",
            server.addr, team.api_token
        ))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 401);
}

#[tokio::test]
async fn test_remote_config_personal_key_no_decryptor_returns_500() {
    // With no FLAGS_SECRET_KEYS/SECRET_KEY the decryptor is None; an encrypted-flag decrypt
    // request must 500 (FlagError::Internal), never leak ciphertext.
    let mut config = Config::default_test_config();
    config.flags_secret_keys = String::new();
    config.secret_key = String::new();
    let context = TestContext::new(Some(&config)).await;

    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();
    let user_email = TestContext::generate_test_email("rc_nodecryptor");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    let (_pak_id, api_key) = context
        .create_personal_api_key(
            user_id,
            "RC NoDecryptor",
            vec!["feature_flag:read"],
            None,
            None,
        )
        .await
        .unwrap();
    insert_rc_flag(&context, team.id, "rc-nodecryptor", TOK_PRIMARY, true, true).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "rc-nodecryptor"))
        .header("Authorization", format!("Bearer {api_key}"))
        .send()
        .await
        .unwrap();

    let status = response.status();
    let body = response.text().await.unwrap();
    assert_eq!(status, 500, "body: {body}");
    assert!(!body.contains("world"), "leaked plaintext: {body}");
}

#[tokio::test]
async fn test_remote_config_personal_key_decrypt_failure_returns_500() {
    // A stored value that is not valid ciphertext under the configured keys must 500, not leak.
    let mut config = Config::default_test_config();
    config.flags_secret_keys = K1.to_string();
    let context = TestContext::new(Some(&config)).await;

    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();
    let user_email = TestContext::generate_test_email("rc_decryptfail");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    let (_pak_id, api_key) = context
        .create_personal_api_key(
            user_id,
            "RC DecryptFail",
            vec!["feature_flag:read"],
            None,
            None,
        )
        .await
        .unwrap();
    insert_rc_flag(
        &context,
        team.id,
        "rc-decryptfail",
        "not-a-fernet-token",
        true,
        true,
    )
    .await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "rc-decryptfail"))
        .header("Authorization", format!("Bearer {api_key}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 500);
}

#[tokio::test]
async fn test_remote_config_project_secret_api_key_encrypted_returns_redacted() {
    // A `phs_` project-secret API key (distinct from the team secret token) takes the redact path
    // and the project_secret_api_key auth-counter branch — never decrypts.
    let mut config = Config::default_test_config();
    config.flags_secret_keys = K1.to_string();
    let context = TestContext::new(Some(&config)).await;
    let team = context.insert_new_team(None).await.unwrap();
    let psak = context
        .create_project_secret_api_key(team.id, "RC PSAK", Some(vec!["feature_flag:read"]))
        .await
        .unwrap();
    insert_rc_flag(&context, team.id, "rc-psak-enc", TOK_PRIMARY, true, true).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "rc-psak-enc"))
        .header("Authorization", format!("Bearer {psak}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 200);
    assert_eq!(
        response.json::<Value>().await.unwrap(),
        Value::String(REDACTED.to_string())
    );
}

#[tokio::test]
async fn test_remote_config_falsy_payloads_return_empty_body() {
    // Django's `payloads["true"] or None` nulls out falsy values; each must render as an empty
    // body (not the JSON literal) through the handler, mirroring is_falsy.
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    let cases = [
        ("rc-falsy-false", serde_json::json!(false)),
        ("rc-falsy-zero", serde_json::json!(0)),
        ("rc-falsy-arr", serde_json::json!([])),
        ("rc-falsy-obj", serde_json::json!({})),
    ];
    for (key, value) in &cases {
        let filters = serde_json::json!({
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "payloads": {"true": value},
        });
        insert_flag_with_filters(&context, team.id, key, filters, true, false).await;
    }

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();
    for (key, _) in &cases {
        let response = client
            .get(url(&server.addr, team.id, key))
            .header("Authorization", format!("Bearer {secret_token}"))
            .send()
            .await
            .unwrap();
        assert_eq!(response.status(), 200, "key {key}");
        assert_eq!(
            response.text().await.unwrap(),
            "",
            "key {key} should return an empty body"
        );
    }
}

#[tokio::test]
async fn test_remote_config_allowlisted_team_not_throttled() {
    // An allowlisted team bypasses the per-credential throttle even past the per-minute rate.
    let mut config = Config::default_test_config();
    config.remote_config_default_rate_per_minute = 1; // would 429 the 2nd call otherwise
    let context = TestContext::new(Some(&config)).await;
    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();
    let user_email = TestContext::generate_test_email("rc_allow");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    let (_pak_id, api_key) = context
        .create_personal_api_key(user_id, "RC Allow", vec!["feature_flag:read"], None, None)
        .await
        .unwrap();
    insert_rc_flag(&context, team.id, "rc-allow", "plain", true, false).await;
    // Allowlist this team so the limiter is skipped (parsed via RateLimitingAllowList::from_str).
    config.rate_limiting_allow_list_teams = format!("{}", team.id).parse().unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();
    let get = || {
        client
            .get(url(&server.addr, team.id, "rc-allow"))
            .header("Authorization", format!("Bearer {api_key}"))
            .send()
    };
    assert_eq!(get().await.unwrap().status(), 200);
    assert_eq!(get().await.unwrap().status(), 200);
}

#[tokio::test]
async fn test_remote_config_personal_key_encrypted_missing_true_returns_empty_body() {
    // Personal-key decrypt path with an encrypted flag that has no "true" entry: empty body
    // (resolve_decrypted_payload returns None), not 500 and not the marker. Django 500s here.
    let mut config = Config::default_test_config();
    config.flags_secret_keys = K1.to_string();
    let context = TestContext::new(Some(&config)).await;
    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();
    let user_email = TestContext::generate_test_email("rc_pak_notrue");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    let (_pak_id, api_key) = context
        .create_personal_api_key(
            user_id,
            "RC PAK NoTrue",
            vec!["feature_flag:read"],
            None,
            None,
        )
        .await
        .unwrap();
    let filters = serde_json::json!({
        "groups": [{"properties": [], "rollout_percentage": 100}],
        "payloads": {},
    });
    insert_flag_with_filters(&context, team.id, "rc-pak-notrue", filters, true, true).await;

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(url(&server.addr, team.id, "rc-pak-notrue"))
        .header("Authorization", format!("Bearer {api_key}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 200);
    assert_eq!(response.text().await.unwrap(), "");
}

#[tokio::test]
async fn test_remote_config_token_path_resolves_project_id_from_db_when_cache_lacks_it() {
    // The project_id fallback (cached team has no project_id -> project_id_for_team's
    // `SELECT project_id::bigint`) is otherwise never hit: every `?token=` test resolves the team
    // via Team::from_pg, which always populates project_id. Seed a raw team-cache entry that omits
    // project_id (a pre-field entry) so verify_token_and_get_team returns project_id=None, forcing
    // the fallback query. A wrong column or cast there would 404 the flag.
    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    insert_rc_flag(
        &context,
        team.id,
        "rc-stale-cache",
        "plain-payload",
        true,
        false,
    )
    .await;

    // Cache the team WITHOUT project_id so the handler must fall back to the DB query.
    let redis = setup_redis_client(Some(config.redis_url.clone())).await;
    update_team_in_hypercache_without_project_id(redis, &team)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/api/projects/@current/feature_flags/rc-stale-cache/remote_config?token={}",
            server.addr, team.api_token
        ))
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
