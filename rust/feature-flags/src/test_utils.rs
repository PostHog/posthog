use anyhow::Error;
use axum::async_trait;
use serde_json::{json, Value};
use sqlx::{pool::PoolConnection, postgres::PgRow, Error as SqlxError, PgPool, Postgres};
use std::sync::Arc;
use uuid::Uuid;

use crate::{
    config::{Config, DEFAULT_TEST_CONFIG},
    database::{get_pool, Client, CustomDatabaseError},
    flag_definitions::{self, FeatureFlag, FeatureFlagRow},
    redis::{Client as RedisClientTrait, RedisClient},
    team::{self, Team},
};
use rand::{distributions::Alphanumeric, Rng};

pub fn random_string(prefix: &str, length: usize) -> String {
    let suffix: String = rand::thread_rng()
        .sample_iter(Alphanumeric)
        .take(length)
        .map(char::from)
        .collect();
    format!("{}{}", prefix, suffix)
}

pub async fn insert_new_team_in_redis(client: Arc<RedisClient>) -> Result<Team, Error> {
    let id = rand::thread_rng().gen_range(0..10_000_000);
    let token = random_string("phc_", 12);
    let team = Team {
        id,
        name: "team".to_string(),
        api_token: token,
    };

    let serialized_team = serde_json::to_string(&team)?;
    client
        .set(
            format!(
                "{}{}",
                team::TEAM_TOKEN_CACHE_PREFIX,
                team.api_token.clone()
            ),
            serialized_team,
        )
        .await?;

    Ok(team)
}

pub async fn insert_flags_for_team_in_redis(
    client: Arc<RedisClient>,
    team_id: i32,
    json_value: Option<String>,
) -> Result<(), Error> {
    let payload = match json_value {
        Some(value) => value,
        None => json!([{
            "id": 1,
            "key": "flag1",
            "name": "flag1 description",
            "active": true,
            "deleted": false,
            "team_id": team_id,
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "a@b.com",
                                "type": "person",
                            },
                        ]
                    },
                ],
            },
        }])
        .to_string(),
    };

    client
        .set(
            format!("{}{}", flag_definitions::TEAM_FLAGS_CACHE_PREFIX, team_id),
            payload,
        )
        .await?;

    Ok(())
}

pub fn setup_redis_client(url: Option<String>) -> Arc<RedisClient> {
    let redis_url = match url {
        Some(value) => value,
        None => "redis://localhost:6379/".to_string(),
    };
    let client = RedisClient::new(redis_url).expect("Failed to create redis client");
    Arc::new(client)
}

pub fn create_flag_from_json(json_value: Option<String>) -> Vec<FeatureFlag> {
    let payload = match json_value {
        Some(value) => value,
        None => json!([{
            "id": 1,
            "key": "flag1",
            "name": "flag1 description",
            "active": true,
            "deleted": false,
            "team_id": 1,
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "a@b.com",
                                "type": "person",
                            },
                        ],
                        "rollout_percentage": 50,
                    },
                ],
            },
        }])
        .to_string(),
    };

    let flags: Vec<FeatureFlag> =
        serde_json::from_str(&payload).expect("Failed to parse data to flags list");
    flags
}

pub async fn setup_pg_reader_client(config: Option<&Config>) -> Arc<PgPool> {
    let config = config.unwrap_or(&DEFAULT_TEST_CONFIG);
    Arc::new(
        get_pool(&config.read_database_url, config.max_pg_connections)
            .await
            .expect("Failed to create Postgres client"),
    )
}

pub async fn setup_pg_writer_client(config: Option<&Config>) -> Arc<PgPool> {
    let config = config.unwrap_or(&DEFAULT_TEST_CONFIG);
    Arc::new(
        get_pool(&config.write_database_url, config.max_pg_connections)
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

pub async fn insert_new_team_in_pg(client: Arc<dyn Client + Send + Sync>) -> Result<Team, Error> {
    const ORG_ID: &str = "019026a4be8000005bf3171d00629163";

    client.run_query(
        r#"INSERT INTO posthog_organization
        (id, name, slug, created_at, updated_at, plugins_access_level, for_internal_metrics, is_member_join_email_enabled, enforce_2fa, is_hipaa, customer_id, available_product_features, personalization, setup_section_2_completed, domain_whitelist) 
        VALUES
        ($1::uuid, 'Test Organization', 'test-organization', '2024-06-17 14:40:49.298579+00:00', '2024-06-17 14:40:49.298593+00:00', 9, false, true, NULL, false, NULL, '{}', '{}', true, '{}')
        ON CONFLICT DO NOTHING"#.to_string(),
        vec![ORG_ID.to_string()],
        Some(2000),
    ).await?;

    client
        .run_query(
            r#"INSERT INTO posthog_project
        (id, organization_id, name, created_at) 
        VALUES
        (1, $1::uuid, 'Test Team', '2024-06-17 14:40:51.329772+00:00')
        ON CONFLICT DO NOTHING"#
                .to_string(),
            vec![ORG_ID.to_string()],
            Some(2000),
        )
        .await?;

    let id = rand::thread_rng().gen_range(0..10_000_000);
    let token = random_string("phc_", 12);
    let team = Team {
        id,
        name: "team".to_string(),
        api_token: token,
    };
    let uuid = Uuid::now_v7();

    let mut conn = client.get_connection().await?;
    let res = sqlx::query(
        r#"INSERT INTO posthog_team 
        (id, uuid, organization_id, project_id, api_token, name, created_at, updated_at, app_urls, anonymize_ips, completed_snippet_onboarding, ingested_event, session_recording_opt_in, is_demo, access_control, test_account_filters, timezone, data_attributes, plugins_opt_in, opt_out_capture, event_names, event_names_with_usage, event_properties, event_properties_with_usage, event_properties_numerical) VALUES
        ($1, $5, $2::uuid, 1, $3, $4, '2024-06-17 14:40:51.332036+00:00', '2024-06-17', '{}', false, false, false, false, false, false, '{}', 'UTC', '["data-attr"]', false, false, '[]', '[]', '[]', '[]', '[]')"#
    ).bind(team.id).bind(ORG_ID).bind(&team.api_token).bind(&team.name).bind(uuid).execute(&mut *conn).await?;

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
            (group_type, group_type_index, name_singular, name_plural, team_id)
            VALUES
            ($1, $2, NULL, NULL, $3)"#,
        )
        .bind(group_type)
        .bind(group_type_index)
        .bind(team.id)
        .execute(&mut *conn)
        .await?;

        assert_eq!(res.rows_affected(), 1);
    }
    Ok(team)
}

pub async fn insert_flag_for_team_in_pg(
    client: Arc<PgPool>,
    team_id: i32,
    flag: Option<FeatureFlagRow>,
) -> Result<FeatureFlagRow, Error> {
    let id = rand::thread_rng().gen_range(0..10_000_000);

    let payload_flag = match flag {
        Some(mut value) => {
            value.id = id;
            value
        }
        None => FeatureFlagRow {
            id,
            key: "flag1".to_string(),
            name: Some("flag1 description".to_string()),
            active: true,
            deleted: false,
            ensure_experience_continuity: false,
            team_id,
            filters: json!({
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "a@b.com",
                                "type": "person",
                            },
                        ],
                        "rollout_percentage": 50,
                    },
                ],
            }),
        },
    };

    let mut conn = client.get_connection().await?;
    let res = sqlx::query(
        r#"INSERT INTO posthog_featureflag
        (id, team_id, name, key, filters, deleted, active, ensure_experience_continuity, created_at) VALUES
        ($1, $2, $3, $4, $5, $6, $7, $8, '2024-06-17')"#
    ).bind(payload_flag.id).bind(team_id).bind(&payload_flag.name).bind(&payload_flag.key).bind(&payload_flag.filters).bind(payload_flag.deleted).bind(payload_flag.active).bind(payload_flag.ensure_experience_continuity).execute(&mut *conn).await?;

    assert_eq!(res.rows_affected(), 1);

    Ok(payload_flag)
}

pub async fn insert_person_for_team_in_pg(
    client: Arc<PgPool>,
    team_id: i32,
    distinct_id: String,
    properties: Option<Value>,
) -> Result<(), Error> {
    let payload = match properties {
        Some(value) => value,
        None => json!({
            "email": "a@b.com",
            "name": "Alice",
        }),
    };

    let uuid = Uuid::now_v7();

    let mut conn = client.get_connection().await?;
    let res = sqlx::query(
        r#"
        WITH inserted_person AS (
            INSERT INTO posthog_person (
                created_at, properties, properties_last_updated_at,
                properties_last_operation, team_id, is_user_id, is_identified, uuid, version
            )
            VALUES ('2023-04-05', $1, '{}', '{}', $2, NULL, true, $3, 0)
            RETURNING *
        )
        INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
        VALUES ($4, (SELECT id FROM inserted_person), $5, 0)
        "#,
    )
    .bind(&payload)
    .bind(team_id)
    .bind(uuid)
    .bind(&distinct_id)
    .bind(team_id)
    .execute(&mut *conn)
    .await?;

    assert_eq!(res.rows_affected(), 1);

    Ok(())
}
