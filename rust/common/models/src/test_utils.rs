use crate::team_models::{Team, TEAM_TOKEN_CACHE_PREFIX};
use anyhow::Error;
use axum::async_trait;
use common_database::{get_pool, Client, CustomDatabaseError};
use common_redis::{Client as RedisClientTrait, RedisClient};
use rand::{distributions::Alphanumeric, Rng};
use sqlx::{pool::PoolConnection, postgres::PgRow, Error as SqlxError, Postgres};
use std::sync::Arc;
use uuid::Uuid;

pub const DEFAULT_TEST_READ_DATABASE_URL: &str =
    "postgres://posthog:posthog@localhost:5432/test_posthog";
pub const DEFAULT_TEST_MAX_PG_CONNECTIONS: u32 = 10;

pub fn random_string(prefix: &str, length: usize) -> String {
    let suffix: String = rand::thread_rng()
        .sample_iter(Alphanumeric)
        .take(length)
        .map(char::from)
        .collect();
    format!("{}{}", prefix, suffix)
}

pub async fn insert_new_team_in_redis(
    client: Arc<dyn RedisClientTrait + Send + Sync>,
) -> Result<Team, Error> {
    let id = rand::thread_rng().gen_range(1..10_000_000);
    let token = random_string("phc_", 12);
    let team = Team {
        id,
        project_id: i64::from(id),
        name: "team".to_string(),
        api_token: token,
        cookieless_server_hash_mode: 0,
        timezone: "UTC".to_string(),
        ..Default::default()
    };

    let serialized_team = serde_json::to_string(&team)?;
    client
        .set(
            format!("{}{}", TEAM_TOKEN_CACHE_PREFIX, team.api_token.clone()),
            serialized_team,
        )
        .await?;

    Ok(team)
}

pub fn setup_redis_client(url: Option<String>) -> Arc<dyn RedisClientTrait + Send + Sync> {
    let redis_url = match url {
        Some(value) => value,
        None => "redis://localhost:6379/".to_string(),
    };
    let client = RedisClient::new(redis_url).expect("Failed to create redis client");
    Arc::new(client)
}

pub async fn setup_pg_reader_client_with_database_url_and_max_connections(
    read_database_url: Option<String>,
    max_pg_connections: Option<u32>,
) -> Arc<dyn Client + Send + Sync> {
    let read_database_url = read_database_url.unwrap_or(DEFAULT_TEST_READ_DATABASE_URL.to_string());
    let max_pg_connections = max_pg_connections.unwrap_or(DEFAULT_TEST_MAX_PG_CONNECTIONS);
    Arc::new(
        get_pool(&read_database_url, max_pg_connections)
            .await
            .expect("Failed to create Postgres client"),
    )
}

pub struct MockPgClient;

#[async_trait]
impl Client for MockPgClient {
    async fn run_query(
        &self,
        _query: String,
        _parameters: Vec<String>,
        _timeout_ms: Option<u64>,
    ) -> Result<Vec<PgRow>, CustomDatabaseError> {
        // Simulate a database connection failure
        Err(CustomDatabaseError::Other(SqlxError::PoolTimedOut))
    }

    async fn get_connection(&self) -> Result<PoolConnection<Postgres>, CustomDatabaseError> {
        // Simulate a database connection failure
        Err(CustomDatabaseError::Other(SqlxError::PoolTimedOut))
    }
}

pub async fn setup_invalid_pg_client() -> Arc<dyn Client + Send + Sync> {
    Arc::new(MockPgClient)
}

pub async fn insert_new_team_in_pg(
    client: Arc<dyn Client + Send + Sync>,
    team_id: Option<i32>,
) -> Result<Team, Error> {
    const ORG_ID: &str = "019026a4be8000005bf3171d00629163";

    // Create new organization from scratch
    client.run_query(
        r#"INSERT INTO posthog_organization
        (id, name, slug, created_at, updated_at, plugins_access_level, for_internal_metrics, is_member_join_email_enabled, enforce_2fa, is_hipaa, customer_id, available_product_features, personalization, setup_section_2_completed, domain_whitelist) 
        VALUES
        ($1::uuid, 'Test Organization', 'test-organization', '2024-06-17 14:40:49.298579+00:00', '2024-06-17 14:40:49.298593+00:00', 9, false, true, NULL, false, NULL, '{}', '{}', true, '{}')
        ON CONFLICT DO NOTHING"#.to_string(),
        vec![ORG_ID.to_string()],
        Some(2000),
    ).await?;

    // Create team model
    let id = match team_id {
        Some(value) => value,
        None => rand::thread_rng().gen_range(0..10_000_000),
    };
    let token = random_string("phc_", 12);
    let team = Team {
        id,
        project_id: id as i64,
        name: "Test Team".to_string(),
        api_token: token.clone(),
        cookieless_server_hash_mode: 0,
        timezone: "UTC".to_string(),
        ..Default::default()
    };
    let uuid = Uuid::now_v7();

    let mut conn = client.get_connection().await?;

    // Insert a project for the team
    let res = sqlx::query(
        r#"INSERT INTO posthog_project
        (id, organization_id, name, created_at) VALUES
        ($1, $2::uuid, $3, '2024-06-17 14:40:51.332036+00:00')"#,
    )
    .bind(team.project_id)
    .bind(ORG_ID)
    .bind(&team.name)
    .execute(&mut *conn)
    .await?;
    assert_eq!(res.rows_affected(), 1);

    // Insert a team with the correct team-project relationship
    let res = sqlx::query(
        r#"INSERT INTO posthog_team 
        (id, uuid, organization_id, project_id, api_token, name, created_at, updated_at, app_urls, anonymize_ips, completed_snippet_onboarding, ingested_event, session_recording_opt_in, is_demo, access_control, test_account_filters, timezone, data_attributes, plugins_opt_in, opt_out_capture, event_names, event_names_with_usage, event_properties, event_properties_with_usage, event_properties_numerical, cookieless_server_hash_mode) VALUES
        ($1, $2, $3::uuid, $4, $5, $6, '2024-06-17 14:40:51.332036+00:00', '2024-06-17', '{}', false, false, false, false, false, false, '{}', 'UTC', '["data-attr"]', false, false, '[]', '[]', '[]', '[]', '[]', $7)"#
    ).bind(team.id).bind(uuid).bind(ORG_ID).bind(team.project_id).bind(&team.api_token).bind(&team.name).bind(team.cookieless_server_hash_mode).execute(&mut *conn).await?;
    assert_eq!(res.rows_affected(), 1);

    // Insert group type mappings
    let group_types = vec![
        ("project", 0),
        ("organization", 1),
        ("instance", 2),
        ("customer", 3),
        ("team", 4),
    ];

    for (group_type, group_type_index) in group_types {
        let res = sqlx::query(
            r#"INSERT INTO posthog_grouptypemapping
            (group_type, group_type_index, name_singular, name_plural, team_id, project_id)
            VALUES
            ($1, $2, NULL, NULL, $3, $4)"#,
        )
        .bind(group_type)
        .bind(group_type_index)
        .bind(team.id)
        .bind(team.project_id)
        .execute(&mut *conn)
        .await?;
        assert_eq!(res.rows_affected(), 1);
    }
    Ok(team)
}
