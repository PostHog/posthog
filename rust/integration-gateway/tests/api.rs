//! Seeded-DB HTTP integration test for the credential-fetch API.
//!
//! Boots the axum app against the shared test Postgres (the same DB the feature-flags rust tests
//! use — created by `manage.py setup_test_environment` in CI), seeds an org/project/team +
//! `posthog_integration` row with a Fernet-encrypted `sensitive_config`, then exercises the real
//! request path: scoped-JWT verification, per-row team-scope isolation, and per-leaf decryption.
//!
//! Requires a running Postgres with the Django schema migrated. `DATABASE_URL` overrides the
//! default local dev DSN. Team seeding mirrors `rust/feature-flags`' `insert_new_team_in_pg`.

use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use base64::{prelude::BASE64_URL_SAFE, Engine};
use fernet::Fernet;
use jsonwebtoken::{encode, Algorithm, EncodingKey, Header};
use serde::Serialize;
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use tokio::net::TcpListener;
use uuid::Uuid;

use integration_gateway::app_context::AppState;
use integration_gateway::auth::JWT_AUDIENCE;
use integration_gateway::cache;
use integration_gateway::crypto::IntegrationDecryptor;
use integration_gateway::integrations::IntegrationService;
use integration_gateway::router as gw_router;

// 32 bytes — matches the dev default of ENCRYPTION_SALT_KEYS.
const SALT_KEY_32: &str = "00beef0000beef0000beef0000beef00";
const JWT_SECRET: &str = "test-secret";
// Reused across teams; org rows are inserted ON CONFLICT DO NOTHING.
const TEST_ORG_ID: &str = "019026a4be8000005bf3171d00629163";

fn database_url() -> String {
    std::env::var("DATABASE_URL")
        .unwrap_or_else(|_| "postgres://posthog:posthog@localhost:5432/posthog".to_string())
}

async fn pool() -> PgPool {
    PgPoolOptions::new()
        .max_connections(2)
        .connect(&database_url())
        .await
        .expect("connect to test Postgres")
}

async fn spawn_app(pool: PgPool) -> String {
    let decryptor = IntegrationDecryptor::build(&[SALT_KEY_32.to_string()], &[], &[]).unwrap();
    let cache = cache::build(30, 1000);
    // No RefreshManager: these tests exercise the read path (pass-through).
    let service = Arc::new(IntegrationService::new(pool, decryptor, cache, None));
    let state = AppState {
        service,
        jwt_secrets: Arc::new(vec![JWT_SECRET.to_string()]),
        max_batch_size: 100,
    };
    let app = gw_router::merge_api_routes(axum::Router::new(), state);

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    format!("http://{addr}")
}

#[derive(Serialize)]
struct Claims {
    team_id: i64,
    caller: String,
    aud: String,
    exp: usize,
}

fn mint(team_id: i64) -> String {
    let exp = (SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
        + 300) as usize;
    let claims = Claims {
        team_id,
        caller: "test".to_string(),
        aud: JWT_AUDIENCE.to_string(),
        exp,
    };
    encode(
        &Header::new(Algorithm::HS256),
        &claims,
        &EncodingKey::from_secret(JWT_SECRET.as_bytes()),
    )
    .unwrap()
}

fn encrypt_leaf(plaintext: &str) -> String {
    Fernet::new(&BASE64_URL_SAFE.encode(SALT_KEY_32.as_bytes()))
        .unwrap()
        .encrypt(plaintext.as_bytes())
}

/// Seed an org/project/team, returning a fresh team id. Mirrors feature-flags' insert_new_team_in_pg
/// (minus the persons-DB group mappings, which the gateway doesn't need).
async fn seed_team(pool: &PgPool) -> i64 {
    let (team_id,): (i32,) = sqlx::query_as("SELECT nextval('posthog_team_id_seq')::int")
        .fetch_one(pool)
        .await
        .unwrap();

    sqlx::query(
        r#"INSERT INTO posthog_organization
        (id, name, slug, created_at, updated_at, plugins_access_level, for_internal_metrics, is_member_join_email_enabled, enforce_2fa, is_hipaa, customer_id, available_product_features, personalization, setup_section_2_completed, domain_whitelist, members_can_use_personal_api_keys, allow_publicly_shared_resources, default_anonymize_ips)
        VALUES
        ($1::uuid, 'Test Organization', $2, NOW(), NOW(), 9, false, true, NULL, false, NULL, '{}', '{}', true, '{}', true, true, false)
        ON CONFLICT DO NOTHING"#,
    )
    .bind(TEST_ORG_ID)
    .bind(format!("test-org-{}", &TEST_ORG_ID[..8]))
    .execute(pool)
    .await
    .unwrap();

    sqlx::query(
        r#"INSERT INTO posthog_project (id, organization_id, name, created_at) VALUES ($1, $2::uuid, 'Test Team', NOW())"#,
    )
    .bind(team_id)
    .bind(TEST_ORG_ID)
    .execute(pool)
    .await
    .unwrap();

    sqlx::query(
        r#"INSERT INTO posthog_team
        (id, uuid, organization_id, project_id, api_token, name, created_at, updated_at, app_urls, anonymize_ips, completed_snippet_onboarding, ingested_event, session_recording_opt_in, is_demo, access_control, test_account_filters, timezone, data_attributes, plugins_opt_in, opt_out_capture, event_names, event_names_with_usage, event_properties, event_properties_with_usage, event_properties_numerical, cookieless_server_hash_mode, base_currency, session_recording_retention_period, web_analytics_pre_aggregated_tables_enabled) VALUES
        ($1, $2, $3::uuid, $4, $5, 'Test Team', NOW(), NOW(), '{}', false, false, false, false, false, false, '{}', 'UTC', '["data-attr"]', false, false, '[]', '[]', '[]', '[]', '[]', 0, 'USD', '30d', false)"#,
    )
    .bind(team_id)
    .bind(Uuid::new_v4())
    .bind(TEST_ORG_ID)
    .bind(team_id)
    .bind(format!("phc_test_{team_id}"))
    .execute(pool)
    .await
    .unwrap();

    team_id as i64
}

/// Seed a `posthog_integration` row with the given (already-encrypted) sensitive_config, returning id.
async fn seed_integration(pool: &PgPool, team_id: i64, kind: &str, sensitive_config: Value) -> i64 {
    let (id,): (i64,) = sqlx::query_as(
        r#"INSERT INTO posthog_integration
        (team_id, kind, integration_id, config, sensitive_config, repository_cache, errors, created_at)
        VALUES ($1, $2, NULL, $3, $4, '[]'::jsonb, '', NOW())
        RETURNING id::bigint"#,
    )
    .bind(team_id as i32)
    .bind(kind)
    .bind(json!({ "team": "T-1234" }))
    .bind(sensitive_config)
    .fetch_one(pool)
    .await
    .unwrap();
    id
}

#[tokio::test]
async fn fetches_and_decrypts_for_owning_team() {
    let pool = pool().await;
    let team_id = seed_team(&pool).await;
    let integration_id = seed_integration(
        &pool,
        team_id,
        "slack",
        json!({ "access_token": encrypt_leaf("xoxb-secret-token"), "not_encrypted": "plain" }),
    )
    .await;

    let base = spawn_app(pool).await;
    let resp = reqwest::Client::new()
        .post(format!("{base}/api/v1/credentials/fetch"))
        .bearer_auth(mint(team_id))
        .json(&json!({ "integration_ids": [integration_id] }))
        .send()
        .await
        .unwrap();
    assert_eq!(resp.status().as_u16(), 200);

    let body: Value = resp.json().await.unwrap();
    let got = &body["integrations"][integration_id.to_string()];
    assert_eq!(got["team_id"], json!(team_id));
    assert_eq!(got["kind"], json!("slack"));
    // sensitive_config is decrypted pass-through; the undecryptable leaf survives unchanged.
    assert_eq!(got["sensitive_config"]["access_token"], json!("xoxb-secret-token"));
    assert_eq!(got["sensitive_config"]["not_encrypted"], json!("plain"));
    // config is returned verbatim (not encrypted).
    assert_eq!(got["config"]["team"], json!("T-1234"));
}

#[tokio::test]
async fn wrong_team_is_indistinguishable_from_not_found() {
    let pool = pool().await;
    let owner = seed_team(&pool).await;
    let other = seed_team(&pool).await;
    let integration_id =
        seed_integration(&pool, owner, "slack", json!({ "access_token": encrypt_leaf("x") })).await;

    let base = spawn_app(pool).await;
    let resp = reqwest::Client::new()
        .post(format!("{base}/api/v1/credentials/fetch"))
        // token scoped to a DIFFERENT team than the one that owns the row
        .bearer_auth(mint(other))
        .json(&json!({ "integration_ids": [integration_id] }))
        .send()
        .await
        .unwrap();
    assert_eq!(resp.status().as_u16(), 200);

    let body: Value = resp.json().await.unwrap();
    // present in the response map, but null — a wrong-team id reads exactly like a missing one.
    assert!(body["integrations"]
        .as_object()
        .unwrap()
        .contains_key(&integration_id.to_string()));
    assert_eq!(body["integrations"][integration_id.to_string()], Value::Null);
}

#[tokio::test]
async fn rejects_bad_and_missing_tokens() {
    let base = spawn_app(pool().await).await;
    let client = reqwest::Client::new();
    let url = format!("{base}/api/v1/credentials/fetch");

    let bad = client
        .post(&url)
        .bearer_auth("not-a-jwt")
        .json(&json!({ "integration_ids": [1] }))
        .send()
        .await
        .unwrap();
    assert_eq!(bad.status().as_u16(), 401);

    let missing = client
        .post(&url)
        .json(&json!({ "integration_ids": [1] }))
        .send()
        .await
        .unwrap();
    assert_eq!(missing.status().as_u16(), 401);
}
