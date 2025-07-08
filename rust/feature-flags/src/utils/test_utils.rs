use crate::{
    api::types::FlagValue,
    cohorts::cohort_models::{Cohort, CohortId},
    config::{Config, DEFAULT_TEST_CONFIG},
    flags::flag_models::{
        FeatureFlag, FeatureFlagRow, FlagFilters, FlagPropertyGroup, TEAM_FLAGS_CACHE_PREFIX,
    },
    properties::property_models::{OperatorType, PropertyFilter, PropertyType},
    team::team_models::{Team, TEAM_TOKEN_CACHE_PREFIX},
};
use anyhow::Error;
use axum::async_trait;
use common_database::{get_pool, Client, CustomDatabaseError};
use common_redis::{Client as RedisClientTrait, RedisClient};
use common_types::{PersonId, TeamId};
use rand::{distributions::Alphanumeric, Rng};
use serde_json::{json, Value};
use sqlx::{pool::PoolConnection, postgres::PgRow, Error as SqlxError, Postgres, Row};
use std::sync::Arc;
use uuid::Uuid;

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

pub async fn insert_flags_for_team_in_redis(
    client: Arc<dyn RedisClientTrait + Send + Sync>,
    team_id: i32,
    project_id: i64,
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
            "team_id": team_id,  // generate this?
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
            format!("{}{}", TEAM_FLAGS_CACHE_PREFIX, project_id),
            payload,
        )
        .await?;

    Ok(())
}

pub async fn setup_redis_client(url: Option<String>) -> Arc<dyn RedisClientTrait + Send + Sync> {
    let redis_url = match url {
        Some(value) => value,
        None => "redis://localhost:6379/".to_string(),
    };
    let client = RedisClient::new(redis_url)
        .await
        .expect("Failed to create redis client");
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

pub async fn setup_pg_reader_client(config: Option<&Config>) -> Arc<dyn Client + Send + Sync> {
    let config = config.unwrap_or(&DEFAULT_TEST_CONFIG);
    Arc::new(
        get_pool(&config.read_database_url, config.max_pg_connections)
            .await
            .expect("Failed to create Postgres client"),
    )
}

pub async fn setup_pg_writer_client(config: Option<&Config>) -> Arc<dyn Client + Send + Sync> {
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

pub async fn insert_new_team_in_pg(
    client: Arc<dyn Client + Send + Sync>,
    team_id: Option<i32>,
) -> Result<Team, Error> {
    const ORG_ID: &str = "019026a4be8000005bf3171d00629163";

    // Create new organization from scratch
    client.run_query(
        r#"INSERT INTO posthog_organization
        (id, name, slug, created_at, updated_at, plugins_access_level, for_internal_metrics, is_member_join_email_enabled, enforce_2fa, is_hipaa, customer_id, available_product_features, personalization, setup_section_2_completed, domain_whitelist, members_can_use_personal_api_keys) 
        VALUES
        ($1::uuid, 'Test Organization', 'test-organization', '2024-06-17 14:40:49.298579+00:00', '2024-06-17 14:40:49.298593+00:00', 9, false, true, NULL, false, NULL, '{}', '{}', true, '{}', true)
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

pub async fn insert_flag_for_team_in_pg(
    client: Arc<dyn Client + Send + Sync>,
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
            version: None,
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
    client: Arc<dyn Client + Send + Sync>,
    team_id: i32,
    distinct_id: String,
    properties: Option<Value>,
) -> Result<PersonId, Error> {
    let payload = match properties {
        Some(value) => value,
        None => json!({
            "email": "a@b.com",
            "name": "Alice",
        }),
    };

    let uuid = Uuid::now_v7();

    let mut conn = client.get_connection().await?;
    let row = sqlx::query(
        r#"
        WITH inserted_person AS (
            INSERT INTO posthog_person (
                created_at, properties, properties_last_updated_at,
                properties_last_operation, team_id, is_user_id, is_identified, uuid, version
            )
            VALUES ('2023-04-05', $1, '{}', '{}', $2, NULL, true, $3, 0)
            RETURNING id
        )
        INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
        VALUES ($4, (SELECT id FROM inserted_person), $5, 0)
        RETURNING person_id
        "#,
    )
    .bind(&payload)
    .bind(team_id)
    .bind(uuid)
    .bind(&distinct_id)
    .bind(team_id)
    .fetch_one(&mut *conn)
    .await?;

    let person_id: PersonId = row.get::<PersonId, _>("person_id");
    Ok(person_id)
}

pub async fn insert_cohort_for_team_in_pg(
    client: Arc<dyn Client + Send + Sync>,
    team_id: i32,
    name: Option<String>,
    filters: serde_json::Value,
    is_static: bool,
) -> Result<Cohort, Error> {
    let cohort = Cohort {
        id: 0, // Placeholder, will be updated after insertion
        name,
        description: Some("Description for cohort".to_string()),
        team_id,
        deleted: false,
        filters: Some(filters),
        query: None,
        version: Some(1),
        pending_version: None,
        count: None,
        is_calculating: false,
        is_static,
        errors_calculating: 0,
        groups: serde_json::json!([]),
        created_by_id: None,
    };

    let mut conn = client.get_connection().await?;
    let row: (i32,) = sqlx::query_as(
        r#"INSERT INTO posthog_cohort
        (name, description, team_id, deleted, filters, query, version, pending_version, count, is_calculating, is_static, errors_calculating, groups, created_by_id) VALUES
        ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        RETURNING id"#,
    )
    .bind(&cohort.name)
    .bind(&cohort.description)
    .bind(cohort.team_id)
    .bind(cohort.deleted)
    .bind(&cohort.filters)
    .bind(&cohort.query)
    .bind(cohort.version)
    .bind(cohort.pending_version)
    .bind(cohort.count)
    .bind(cohort.is_calculating)
    .bind(cohort.is_static)
    .bind(cohort.errors_calculating)
    .bind(&cohort.groups)
    .bind(cohort.created_by_id)
    .fetch_one(&mut *conn)
    .await?;

    // Update the cohort_row with the actual id generated by sqlx
    let id = row.0;

    Ok(Cohort { id, ..cohort })
}

pub async fn get_person_id_by_distinct_id(
    client: Arc<dyn Client + Send + Sync>,
    team_id: i32,
    distinct_id: &str,
) -> Result<PersonId, Error> {
    let mut conn = client.get_connection().await?;
    let row: (PersonId,) = sqlx::query_as(
        r#"SELECT id FROM posthog_person
           WHERE team_id = $1 AND id = (
               SELECT person_id FROM posthog_persondistinctid
               WHERE team_id = $1 AND distinct_id = $2
               LIMIT 1
           )
           LIMIT 1"#,
    )
    .bind(team_id)
    .bind(distinct_id)
    .fetch_one(&mut *conn)
    .await
    .map_err(|_| anyhow::anyhow!("Person not found"))?;

    Ok(row.0)
}

pub async fn add_person_to_cohort(
    client: Arc<dyn Client + Send + Sync>,
    person_id: PersonId,
    cohort_id: CohortId,
) -> Result<(), Error> {
    let mut conn = client.get_connection().await?;
    let res = sqlx::query(
        r#"INSERT INTO posthog_cohortpeople (cohort_id, person_id)
           VALUES ($1, $2)
           ON CONFLICT DO NOTHING"#,
    )
    .bind(cohort_id)
    .bind(person_id)
    .execute(&mut *conn)
    .await?;

    assert!(res.rows_affected() > 0, "Failed to add person to cohort");

    Ok(())
}

#[derive(Debug)]
pub struct Group {
    pub id: i32,
    pub team_id: i32,
    pub group_type_index: i32,
    pub group_key: String,
    pub group_properties: Value,
}

pub async fn create_group_in_pg(
    client: Arc<dyn Client + Send + Sync>,
    team_id: i32,
    group_type: &str,
    group_key: &str,
    group_properties: Value,
) -> Result<Group, Error> {
    // First, retrieve the group_type_index from grouptypemapping
    let mut conn = client.get_connection().await?;
    let row = sqlx::query(
        r#"SELECT group_type_index FROM posthog_grouptypemapping
           WHERE team_id = $1 AND group_type = $2"#,
    )
    .bind(team_id)
    .bind(group_type)
    .fetch_one(&mut *conn)
    .await?;
    let group_type_index: i32 = row.get("group_type_index");

    // Insert the group with all non-nullable fields
    let res = sqlx::query(
        r#"INSERT INTO posthog_group
           (team_id, group_type_index, group_key, group_properties, created_at, properties_last_updated_at, properties_last_operation, version)
           VALUES ($1, $2, $3, $4, '2024-06-17', '{}'::jsonb, '{}'::jsonb, 0)
           RETURNING id"#,
    )
    .bind(team_id)
    .bind(group_type_index)
    .bind(group_key)
    .bind(group_properties.clone())
    .fetch_one(&mut *conn)
    .await?;
    let group_id: i32 = res.get("id");

    Ok(Group {
        id: group_id,
        team_id,
        group_type_index,
        group_key: group_key.to_string(),
        group_properties,
    })
}

#[allow(clippy::too_many_arguments)]
pub fn create_test_flag(
    id: Option<i32>,
    team_id: Option<TeamId>,
    name: Option<String>,
    key: Option<String>,
    filters: Option<FlagFilters>,
    deleted: Option<bool>,
    active: Option<bool>,
    ensure_experience_continuity: Option<bool>,
) -> FeatureFlag {
    FeatureFlag {
        id: id.unwrap_or(1),
        team_id: team_id.unwrap_or(1),
        name: name.or(Some("Test Flag".to_string())),
        key: key.unwrap_or_else(|| "test_flag".to_string()),
        filters: filters.unwrap_or_else(|| FlagFilters {
            groups: vec![FlagPropertyGroup {
                properties: Some(vec![]),
                rollout_percentage: Some(100.0),
                variant: None,
            }],
            multivariate: None,
            aggregation_group_type_index: None,
            payloads: None,
            super_groups: None,
            holdout_groups: None,
        }),
        deleted: deleted.unwrap_or(false),
        active: active.unwrap_or(true),
        ensure_experience_continuity: ensure_experience_continuity.unwrap_or(false),
        version: Some(1),
    }
}

/// Insert a suppression rule for error tracking into the database
pub async fn insert_suppression_rule_in_pg(
    client: Arc<dyn Client + Send + Sync>,
    team_id: i32,
    filters: serde_json::Value,
) -> Result<uuid::Uuid, Error> {
    let mut conn = client.get_connection().await?;
    let rule_id = uuid::Uuid::new_v4();
    sqlx::query(
        r#"INSERT INTO posthog_errortrackingsuppressionrule 
           (id, team_id, filters, created_at, updated_at, order_key)
           VALUES ($1, $2, $3, NOW(), NOW(), 0)"#,
    )
    .bind(rule_id)
    .bind(team_id)
    .bind(filters)
    .execute(&mut *conn)
    .await?;
    Ok(rule_id)
}

/// Update autocapture exceptions setting for a team in the database
pub async fn update_team_autocapture_exceptions(
    client: Arc<dyn Client + Send + Sync>,
    team_id: i32,
    enabled: bool,
) -> Result<(), Error> {
    let mut conn = client.get_connection().await?;
    sqlx::query("UPDATE posthog_team SET autocapture_exceptions_opt_in = $1 WHERE id = $2")
        .bind(enabled)
        .bind(team_id)
        .execute(&mut *conn)
        .await?;
    Ok(())
}

/// Create a test flag with multiple property filters
pub fn create_test_flag_with_properties(
    id: i32,
    team_id: TeamId,
    key: &str,
    filters: Vec<PropertyFilter>,
) -> FeatureFlag {
    create_test_flag(
        Some(id),
        Some(team_id),
        None,
        Some(key.to_string()),
        Some(FlagFilters {
            groups: vec![FlagPropertyGroup {
                properties: Some(filters),
                rollout_percentage: Some(100.0),
                variant: None,
            }],
            multivariate: None,
            aggregation_group_type_index: None,
            payloads: None,
            super_groups: None,
            holdout_groups: None,
        }),
        None,
        None,
        None,
    )
}

/// Create a test flag with a single property filter
pub fn create_test_flag_with_property(
    id: i32,
    team_id: TeamId,
    key: &str,
    filter: PropertyFilter,
) -> FeatureFlag {
    create_test_flag_with_properties(id, team_id, key, vec![filter])
}

/// Create a test flag that depends on another flag
pub fn create_test_flag_that_depends_on_flag(
    id: i32,
    team_id: TeamId,
    key: &str,
    depends_on_flag_id: i32,
    depends_on_flag_value: FlagValue,
) -> FeatureFlag {
    create_test_flag_with_property(
        id,
        team_id,
        key,
        PropertyFilter {
            key: depends_on_flag_id.to_string(),
            value: Some(json!(depends_on_flag_value)),
            operator: Some(OperatorType::Exact),
            prop_type: PropertyType::Flag,
            group_type_index: None,
            negation: None,
        },
    )
}
