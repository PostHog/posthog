use std::sync::Arc;

use anyhow::{Error, Result};
use chrono::Utc;
use common_database::{get_pool, Client};
use common_redis::{Client as RedisClientTrait, RedisClient};
use common_types::{ProjectId, TeamId};
use once_cell::sync::Lazy;
use rand::{distributions::Alphanumeric, Rng};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use sqlx::types::Json;
use uuid::Uuid;

use crate::{config::Config, redirect::models::LinkRow};

pub static DEFAULT_TEST_CONFIG: Lazy<Config> = Lazy::new(Config::default_for_test);

pub async fn setup_pg_client(config: Option<&Config>) -> Arc<dyn Client + Send + Sync> {
    let config = config.unwrap_or(&DEFAULT_TEST_CONFIG);
    Arc::new(
        get_pool(&config.read_database_url, config.max_pg_connections)
            .await
            .expect("Failed to create Postgres client"),
    )
}

pub async fn setup_redis_client(
    config: Option<&Config>,
) -> Arc<dyn RedisClientTrait + Send + Sync> {
    let config = config.unwrap_or(&DEFAULT_TEST_CONFIG);
    Arc::new(
        RedisClient::new(config.internal_link_redis_url.clone())
            .await
            .expect("Failed to create Redis client"),
    )
}

pub async fn insert_new_link_in_pg(
    db_client: Arc<dyn Client + Send + Sync>,
    short_link_domain: &str,
    short_code: &str,
    redirect_url: &str,
    team_id: i32,
) -> Result<LinkRow, Error> {
    let link_row = LinkRow {
        id: uuid::Uuid::new_v4(),
        redirect_url: redirect_url.into(),
        short_code: short_code.into(),
        short_link_domain: short_link_domain.into(),
        created_at: Utc::now(),
        description: "".into(),
        team: team_id,
    };
    let mut conn = db_client.get_connection().await.unwrap();
    let row: (Uuid,) = sqlx::query_as(
        r#"INSERT INTO posthog_link 
        (id, redirect_url, short_code, short_link_domain, created_at, description, team_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id"#,
    )
    .bind(link_row.id)
    .bind(&link_row.redirect_url)
    .bind(&link_row.short_code)
    .bind(&link_row.short_link_domain)
    .bind(link_row.created_at)
    .bind(&link_row.description)
    .bind(link_row.team)
    .fetch_one(&mut *conn)
    .await?;

    Ok(LinkRow {
        id: row.0,
        ..link_row
    })
}

pub async fn insert_new_team_in_pg(
    client: Arc<dyn Client + Send + Sync>,
    team_id: Option<i32>,
) -> Result<Team, Error> {
    const ORG_ID: &str = "019026a4be8000005bf3171d00629163";

    // Create new organization from scratch
    client.run_query(
        r#"INSERT INTO posthog_organization
        (id, name, slug, created_at, updated_at, plugins_access_level, for_internal_metrics, is_member_join_email_enabled, enforce_2fa, members_can_invite, is_hipaa, customer_id, available_product_features, personalization, setup_section_2_completed, domain_whitelist, members_can_use_personal_api_keys) 
        VALUES
        ($1::uuid, 'Test Organization', 'test-organization', '2024-06-17 14:40:49.298579+00:00', '2024-06-17 14:40:49.298593+00:00', 9, false, true, NULL, true, false, NULL, '{}', '{}', true, '{}', true)
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
        (id, uuid, organization_id, project_id, api_token, name, created_at, updated_at, app_urls, anonymize_ips, completed_snippet_onboarding, ingested_event, session_recording_opt_in, is_demo, access_control, test_account_filters, timezone, data_attributes, plugins_opt_in, opt_out_capture, event_names, event_names_with_usage, event_properties, event_properties_with_usage, event_properties_numerical, cookieless_server_hash_mode, base_currency) VALUES
        ($1, $2, $3::uuid, $4, $5, $6, '2024-06-17 14:40:51.332036+00:00', '2024-06-17', '{}', false, false, false, false, false, false, '{}', 'UTC', '["data-attr"]', false, false, '[]', '[]', '[]', '[]', '[]', $7, 'USD')"#
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

#[derive(Clone, Debug, Default, Deserialize, Serialize, sqlx::FromRow)]
pub struct Team {
    pub id: TeamId,
    pub name: String,
    pub api_token: String,
    /// Project ID. This field is not present in Redis cache before Dec 2025, but this is not a problem at all,
    /// because we know all Teams created before Dec 2025 have `project_id` = `id`. To handle this case gracefully,
    /// we use 0 as a fallback value in deserialization here, and handle this in `Team::from_redis`.
    /// Thanks to this default-base approach, we avoid invalidating the whole cache needlessly.
    pub project_id: ProjectId,
    pub uuid: Uuid,
    pub autocapture_opt_out: Option<bool>,
    pub autocapture_exceptions_opt_in: Option<bool>,
    pub autocapture_web_vitals_opt_in: Option<bool>,
    pub capture_performance_opt_in: Option<bool>,
    pub capture_console_log_opt_in: Option<bool>,
    #[serde(default)]
    pub session_recording_opt_in: bool, // Not nullable in schema, so needs to be handled in deserialization
    pub inject_web_apps: Option<bool>,
    pub surveys_opt_in: Option<bool>,
    pub heatmaps_opt_in: Option<bool>,
    pub capture_dead_clicks: Option<bool>,
    pub flags_persistence_default: Option<bool>,
    pub session_recording_sample_rate: Option<Decimal>, // numeric(3,2) in postgres, see https://docs.rs/sqlx/latest/sqlx/postgres/types/index.html#rust_decimal
    pub session_recording_minimum_duration_milliseconds: Option<i32>,
    pub autocapture_web_vitals_allowed_metrics: Option<Json<serde_json::Value>>,
    pub autocapture_exceptions_errors_to_ignore: Option<Json<serde_json::Value>>,
    pub session_recording_linked_flag: Option<Json<serde_json::Value>>,
    pub session_recording_network_payload_capture_config: Option<Json<serde_json::Value>>,
    pub session_recording_masking_config: Option<Json<serde_json::Value>>,
    pub session_replay_config: Option<Json<serde_json::Value>>,
    pub survey_config: Option<Json<serde_json::Value>>,
    pub session_recording_url_trigger_config: Option<Vec<Json<serde_json::Value>>>, // jsonb[] in postgres
    pub session_recording_url_blocklist_config: Option<Vec<Json<serde_json::Value>>>, // jsonb[] in postgres
    pub session_recording_event_trigger_config: Option<Vec<String>>, // text[] in postgres
    pub recording_domains: Option<Vec<String>>, // character varying(200)[] in postgres
    #[serde(with = "option_i16_as_i16")]
    pub cookieless_server_hash_mode: i16,
    #[serde(default = "default_timezone")]
    pub timezone: String,
}

fn default_timezone() -> String {
    "UTC".to_string()
}

mod option_i16_as_i16 {
    use serde::{Deserialize, Deserializer, Serializer};

    pub fn serialize<S>(value: &i16, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_i16(*value)
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<i16, D::Error>
    where
        D: Deserializer<'de>,
    {
        Option::<i16>::deserialize(deserializer).map(|opt| opt.unwrap_or(0))
    }
}

pub fn random_string(prefix: &str, length: usize) -> String {
    let suffix: String = rand::thread_rng()
        .sample_iter(Alphanumeric)
        .take(length)
        .map(char::from)
        .collect();
    format!("{}{}", prefix, suffix)
}
