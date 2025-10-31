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
use sqlx::{pool::PoolConnection, Error as SqlxError, Postgres, Row};
use std::sync::Arc;
use uuid::Uuid;

pub fn random_string(prefix: &str, length: usize) -> String {
    let suffix: String = rand::thread_rng()
        .sample_iter(Alphanumeric)
        .take(length)
        .map(char::from)
        .collect();
    format!("{prefix}{suffix}")
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
        cookieless_server_hash_mode: Some(0),
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
        .set(format!("{TEAM_FLAGS_CACHE_PREFIX}{project_id}"), payload)
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

/// Setup dual database clients for tests that need to work with both persons and non-persons databases.
/// If persons DB routing is not enabled, returns the same client twice.
pub async fn setup_dual_pg_readers(
    config: Option<&Config>,
) -> (Arc<dyn Client + Send + Sync>, Arc<dyn Client + Send + Sync>) {
    let config = config.unwrap_or(&DEFAULT_TEST_CONFIG);

    if config.is_persons_db_routing_enabled() {
        // Separate persons and non-persons databases
        let persons_reader = Arc::new(
            get_pool(
                &config.get_persons_read_database_url(),
                config.max_pg_connections,
            )
            .await
            .expect("Failed to create Postgres persons reader client"),
        );
        let non_persons_reader = Arc::new(
            get_pool(&config.read_database_url, config.max_pg_connections)
                .await
                .expect("Failed to create Postgres client"),
        );
        (persons_reader, non_persons_reader)
    } else {
        // Same database for both
        let client = Arc::new(
            get_pool(&config.read_database_url, config.max_pg_connections)
                .await
                .expect("Failed to create Postgres client"),
        );
        (client.clone(), client)
    }
}

/// Setup dual database writers for tests that need to write to both persons and non-persons databases.
/// If persons DB routing is not enabled, returns the same client twice.
pub async fn setup_dual_pg_writers(
    config: Option<&Config>,
) -> (Arc<dyn Client + Send + Sync>, Arc<dyn Client + Send + Sync>) {
    let config = config.unwrap_or(&DEFAULT_TEST_CONFIG);

    if config.is_persons_db_routing_enabled() {
        // Separate persons and non-persons databases
        let persons_writer = Arc::new(
            get_pool(
                &config.get_persons_write_database_url(),
                config.max_pg_connections,
            )
            .await
            .expect("Failed to create Postgres persons writer client"),
        );
        let non_persons_writer = Arc::new(
            get_pool(&config.write_database_url, config.max_pg_connections)
                .await
                .expect("Failed to create Postgres client"),
        );
        (persons_writer, non_persons_writer)
    } else {
        // Same database for both
        let client = Arc::new(
            get_pool(&config.write_database_url, config.max_pg_connections)
                .await
                .expect("Failed to create Postgres client"),
        );
        (client.clone(), client)
    }
}

pub struct MockPgClient;

#[async_trait]
impl Client for MockPgClient {
    async fn get_connection(&self) -> Result<PoolConnection<Postgres>, CustomDatabaseError> {
        // Simulate a database connection failure
        Err(CustomDatabaseError::Other(SqlxError::PoolTimedOut))
    }

    fn get_pool_stats(&self) -> Option<common_database::PoolStats> {
        // Return None for mock client
        None
    }
}

pub async fn setup_invalid_pg_client() -> Arc<dyn Client + Send + Sync> {
    Arc::new(MockPgClient)
}

/// Inserts an organization if it doesn't exist
/// If slug is not provided, generates one from the org_id
async fn insert_organization_if_not_exists(
    conn: &mut PoolConnection<Postgres>,
    org_id: &str,
    slug: Option<&str>,
) -> Result<(), Error> {
    let org_slug = match slug {
        Some(s) => s.to_string(),
        None => format!("test-org-{}", &org_id[..8]),
    };

    sqlx::query(
        r#"INSERT INTO posthog_organization
        (id, name, slug, created_at, updated_at, plugins_access_level, for_internal_metrics, is_member_join_email_enabled, enforce_2fa, is_hipaa, customer_id, available_product_features, personalization, setup_section_2_completed, domain_whitelist, members_can_use_personal_api_keys, allow_publicly_shared_resources)
        VALUES
        ($1::uuid, 'Test Organization', $2, '2024-06-17 14:40:49.298579+00:00', '2024-06-17 14:40:49.298593+00:00', 9, false, true, NULL, false, NULL, '{}', '{}', true, '{}', true, true)
        ON CONFLICT DO NOTHING"#,
    )
    .bind(org_id)
    .bind(&org_slug)
    .execute(&mut **conn)
    .await?;

    Ok(())
}

/// Inserts group type mappings for a team in the persons database
async fn insert_team_group_mappings(
    persons_client: Arc<dyn Client + Send + Sync>,
    team: &Team,
) -> Result<(), Error> {
    let mut persons_conn = persons_client.get_connection().await?;
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
        .execute(&mut *persons_conn)
        .await?;
        assert_eq!(res.rows_affected(), 1);
    }

    Ok(())
}

pub async fn insert_new_team_in_pg(
    persons_client: Arc<dyn Client + Send + Sync>,
    non_persons_client: Arc<dyn Client + Send + Sync>,
    team_id: Option<i32>,
    org_id: Option<&str>,
) -> Result<Team, Error> {
    let org_id = org_id.unwrap_or("019026a4be8000005bf3171d00629163");

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
        cookieless_server_hash_mode: Some(0),
        timezone: "UTC".to_string(),
        ..Default::default()
    };

    // Insert organization and project
    let mut non_persons_conn = non_persons_client.get_connection().await?;
    insert_organization_if_not_exists(&mut non_persons_conn, org_id, None).await?;

    let uuid = Uuid::now_v7();
    let res = sqlx::query(
        r#"INSERT INTO posthog_project
        (id, organization_id, name, created_at) VALUES
        ($1, $2::uuid, $3, '2024-06-17 14:40:51.332036+00:00')"#,
    )
    .bind(team.project_id)
    .bind(org_id)
    .bind(&team.name)
    .execute(&mut *non_persons_conn)
    .await?;
    assert_eq!(res.rows_affected(), 1);

    // Insert team without secret tokens
    let res = sqlx::query(
        r#"INSERT INTO posthog_team
        (id, uuid, organization_id, project_id, api_token, name, created_at, updated_at, app_urls, anonymize_ips, completed_snippet_onboarding, ingested_event, session_recording_opt_in, is_demo, access_control, test_account_filters, timezone, data_attributes, plugins_opt_in, opt_out_capture, event_names, event_names_with_usage, event_properties, event_properties_with_usage, event_properties_numerical, cookieless_server_hash_mode, base_currency, session_recording_retention_period, web_analytics_pre_aggregated_tables_enabled) VALUES
        ($1, $2, $3::uuid, $4, $5, $6, '2024-06-17 14:40:51.332036+00:00', '2024-06-17', '{}', false, false, false, false, false, false, '{}', 'UTC', '["data-attr"]', false, false, '[]', '[]', '[]', '[]', '[]', $7, 'USD', '30d', false)"#
    ).bind(team.id).bind(uuid).bind(org_id).bind(team.project_id).bind(&team.api_token).bind(&team.name).bind(team.cookieless_server_hash_mode.unwrap_or(0)).execute(&mut *non_persons_conn).await?;
    assert_eq!(res.rows_affected(), 1);

    // Insert group type mappings
    insert_team_group_mappings(persons_client, &team).await?;

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
            ensure_experience_continuity: Some(false),
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
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
        },
    };

    let mut conn = client.get_connection().await?;
    let res = sqlx::query(
        r#"INSERT INTO posthog_featureflag
        (id, team_id, name, key, filters, deleted, active, ensure_experience_continuity, evaluation_runtime, created_at) VALUES
        ($1, $2, $3, $4, $5, $6, $7, $8, $9, '2024-06-17')"#
    ).bind(payload_flag.id).bind(team_id).bind(&payload_flag.name).bind(&payload_flag.key).bind(&payload_flag.filters).bind(payload_flag.deleted).bind(payload_flag.active).bind(payload_flag.ensure_experience_continuity).bind(&payload_flag.evaluation_runtime).execute(&mut *conn).await?;

    assert_eq!(res.rows_affected(), 1);

    Ok(payload_flag)
}

pub async fn insert_evaluation_tags_for_flag_in_pg(
    client: Arc<dyn Client + Send + Sync>,
    flag_id: i32,
    team_id: i32,
    tag_names: Vec<&str>,
) -> Result<(), Error> {
    let mut conn = client.get_connection().await?;

    for tag_name in tag_names {
        // First, insert the tag if it doesn't exist
        let tag_uuid = Uuid::now_v7();
        let tag_id: Uuid = sqlx::query_scalar(
            r#"
            INSERT INTO posthog_tag (id, name, team_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (name, team_id) DO UPDATE 
            SET name = EXCLUDED.name
            RETURNING id
            "#,
        )
        .bind(tag_uuid)
        .bind(tag_name)
        .bind(team_id)
        .fetch_one(&mut *conn)
        .await?;

        // Then, create the association
        sqlx::query(
            r#"
            INSERT INTO posthog_featureflagevaluationtag (feature_flag_id, tag_id, created_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (feature_flag_id, tag_id) DO NOTHING
            "#,
        )
        .bind(flag_id)
        .bind(tag_id)
        .execute(&mut *conn)
        .await?;
    }

    Ok(())
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
        ensure_experience_continuity: Some(ensure_experience_continuity.unwrap_or(false)),
        version: Some(1),
        evaluation_runtime: Some("all".to_string()),
        evaluation_tags: None,
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
            operator: Some(OperatorType::FlagEvaluatesTo),
            prop_type: PropertyType::Flag,
            group_type_index: None,
            negation: None,
        },
    )
}

/// Test context that encapsulates all database connections needed for testing
/// This struct manages the proper routing of database operations to the correct
/// database (persons vs non-persons) based on the configuration
pub struct TestContext {
    pub persons_reader: Arc<dyn Client + Send + Sync>,
    pub persons_writer: Arc<dyn Client + Send + Sync>,
    pub non_persons_reader: Arc<dyn Client + Send + Sync>,
    pub non_persons_writer: Arc<dyn Client + Send + Sync>,
    config: Config,
}

impl TestContext {
    pub async fn new(config: Option<&Config>) -> Self {
        let config = config.unwrap_or(&DEFAULT_TEST_CONFIG).clone();

        let (persons_reader, non_persons_reader) = setup_dual_pg_readers(Some(&config)).await;
        let (persons_writer, non_persons_writer) = setup_dual_pg_writers(Some(&config)).await;

        Self {
            persons_reader,
            persons_writer,
            non_persons_reader,
            non_persons_writer,
            config,
        }
    }

    pub fn create_postgres_router(&self) -> crate::database::PostgresRouter {
        crate::database::PostgresRouter::new(
            self.persons_reader.clone(),
            self.persons_writer.clone(),
            self.non_persons_reader.clone(),
            self.non_persons_writer.clone(),
        )
    }

    pub async fn insert_new_team(&self, team_id: Option<i32>) -> Result<Team, Error> {
        insert_new_team_in_pg(
            self.persons_writer.clone(),
            self.non_persons_writer.clone(),
            team_id,
            None,
        )
        .await
    }

    pub async fn insert_new_team_with_org(
        &self,
        team_id: Option<i32>,
        org_id: &str,
    ) -> Result<Team, Error> {
        insert_new_team_in_pg(
            self.persons_writer.clone(),
            self.non_persons_writer.clone(),
            team_id,
            Some(org_id),
        )
        .await
    }

    pub async fn insert_flag(
        &self,
        team_id: i32,
        flag: Option<FeatureFlagRow>,
    ) -> Result<FeatureFlagRow, Error> {
        insert_flag_for_team_in_pg(self.non_persons_writer.clone(), team_id, flag).await
    }

    pub async fn insert_person(
        &self,
        team_id: i32,
        distinct_id: String,
        properties: Option<Value>,
    ) -> Result<PersonId, Error> {
        insert_person_for_team_in_pg(
            self.persons_writer.clone(),
            team_id,
            distinct_id,
            properties,
        )
        .await
    }

    pub async fn insert_cohort(
        &self,
        team_id: i32,
        name: Option<String>,
        filters: serde_json::Value,
        is_static: bool,
    ) -> Result<Cohort, Error> {
        insert_cohort_for_team_in_pg(
            self.non_persons_writer.clone(),
            team_id,
            name,
            filters,
            is_static,
        )
        .await
    }

    pub async fn insert_evaluation_tags_for_flag(
        &self,
        flag_id: i32,
        team_id: i32,
        tag_names: Vec<&str>,
    ) -> Result<(), Error> {
        insert_evaluation_tags_for_flag_in_pg(
            self.non_persons_writer.clone(),
            flag_id,
            team_id,
            tag_names,
        )
        .await
    }

    pub async fn add_person_to_cohort(
        &self,
        cohort_id: CohortId,
        person_id: PersonId,
    ) -> Result<(), Error> {
        add_person_to_cohort(self.persons_writer.clone(), person_id, cohort_id).await
    }

    pub async fn get_feature_flag_hash_key_overrides(
        &self,
        team_id: i32,
        distinct_ids: Vec<String>,
    ) -> Result<std::collections::HashMap<String, String>, super::super::api::errors::FlagError>
    {
        super::super::flags::flag_matching_utils::get_feature_flag_hash_key_overrides(
            self.persons_reader.clone(),
            team_id,
            distinct_ids,
        )
        .await
    }

    pub async fn get_persons_connection(
        &self,
    ) -> Result<PoolConnection<Postgres>, CustomDatabaseError> {
        self.persons_writer.get_connection().await
    }

    pub async fn get_non_persons_connection(
        &self,
    ) -> Result<PoolConnection<Postgres>, CustomDatabaseError> {
        self.non_persons_writer.get_connection().await
    }

    pub async fn create_group(
        &self,
        team_id: i32,
        group_type: &str,
        group_key: &str,
        group_properties: Value,
    ) -> Result<Group, Error> {
        create_group_in_pg(
            self.persons_writer.clone(),
            team_id,
            group_type,
            group_key,
            group_properties,
        )
        .await
    }

    pub async fn insert_suppression_rule(
        &self,
        team_id: i32,
        filters: serde_json::Value,
    ) -> Result<uuid::Uuid, Error> {
        insert_suppression_rule_in_pg(self.non_persons_writer.clone(), team_id, filters).await
    }

    pub async fn update_team_autocapture_exceptions(
        &self,
        team_id: i32,
        enabled: bool,
    ) -> Result<(), Error> {
        update_team_autocapture_exceptions(self.non_persons_writer.clone(), team_id, enabled).await
    }

    pub async fn get_person_id_by_distinct_id(
        &self,
        team_id: i32,
        distinct_id: &str,
    ) -> Result<PersonId, Error> {
        get_person_id_by_distinct_id(self.persons_reader.clone(), team_id, distinct_id).await
    }

    /// Creates a user with configurable options
    pub async fn create_user_with_options(
        &self,
        email: &str,
        org_id: &uuid::Uuid,
        team_id: Option<i32>,
        is_active: bool,
    ) -> Result<i32, Error> {
        let mut conn = self.non_persons_writer.get_connection().await?;
        let user_uuid = uuid::Uuid::new_v4();

        let user_id: i32 = if let Some(team_id) = team_id {
            sqlx::query(
                "INSERT INTO posthog_user (
                    password, last_login, email, first_name, last_name, is_active, is_staff, date_joined,
                    events_column_config, current_organization_id, current_team_id, uuid
                 )
                 VALUES ('', NULL, $1, 'Test', 'User', $2, false, NOW(), '{\"active\": \"DEFAULT\"}'::jsonb, $3, $4, $5)
                 RETURNING id",
            )
            .bind(email)
            .bind(is_active)
            .bind(org_id)
            .bind(team_id)
            .bind(user_uuid)
            .fetch_one(&mut *conn)
            .await?
            .get(0)
        } else {
            sqlx::query(
                "INSERT INTO posthog_user (
                    password, last_login, email, first_name, last_name, is_active, is_staff, date_joined,
                    events_column_config, current_organization_id, current_team_id, uuid
                 )
                 VALUES ('', NULL, $1, 'Test', 'User', $2, false, NOW(), '{\"active\": \"DEFAULT\"}'::jsonb, $3, NULL, $4)
                 RETURNING id",
            )
            .bind(email)
            .bind(is_active)
            .bind(org_id)
            .bind(user_uuid)
            .fetch_one(&mut *conn)
            .await?
            .get(0)
        };

        Ok(user_id)
    }

    /// Creates an active user with a team (common case)
    pub async fn create_user(
        &self,
        email: &str,
        org_id: &uuid::Uuid,
        team_id: i32,
    ) -> Result<i32, Error> {
        self.create_user_with_options(email, org_id, Some(team_id), true)
            .await
    }

    /// Creates a personal API key with hashed value (SHA256 mode)
    pub async fn create_personal_api_key(
        &self,
        user_id: i32,
        label: &str,
        scopes: Vec<&str>,
        scoped_teams: Option<Vec<i32>>,
        scoped_organizations: Option<Vec<String>>,
    ) -> Result<(String, String), Error> {
        // Generate unique PAK ID and value
        let pak_id = format!("test_pak_{}", &uuid::Uuid::new_v4().to_string()[..8]);
        let api_key_value = format!("phx_{}", &uuid::Uuid::new_v4().to_string()[..12]);

        // Hash the key using SHA256
        use sha2::{Digest, Sha256};
        let mut hasher = Sha256::new();
        hasher.update(api_key_value.as_bytes());
        let hash_result = hasher.finalize();
        let secure_value = format!("sha256${}", hex::encode(hash_result));

        let mut conn = self.non_persons_writer.get_connection().await?;

        // Convert scopes to Vec<String>
        let scopes_vec: Vec<String> = scopes.iter().map(|s| s.to_string()).collect();

        let mut query = sqlx::QueryBuilder::new(
            "INSERT INTO posthog_personalapikey (id, user_id, label, secure_value, created_at, scopes",
        );

        if scoped_teams.is_some() {
            query.push(", scoped_teams");
        }
        if scoped_organizations.is_some() {
            query.push(", scoped_organizations");
        }

        query.push(") VALUES (");
        query.push_bind(&pak_id);
        query.push(", ");
        query.push_bind(user_id);
        query.push(", ");
        query.push_bind(label);
        query.push(", ");
        query.push_bind(&secure_value);
        query.push(", NOW(), ");
        query.push_bind(&scopes_vec);

        if let Some(teams) = scoped_teams {
            query.push(", ");
            query.push_bind(teams);
        }
        if let Some(orgs) = scoped_organizations {
            query.push(", ");
            query.push_bind(orgs);
        }

        query.push(")");

        query.build().execute(&mut *conn).await?;

        Ok((pak_id, api_key_value))
    }

    /// Creates a team with both public token and secret API token
    /// Optionally accepts a backup secret token
    pub async fn create_team_with_secret_token(
        &self,
        public_token: Option<&str>,
        secret_token: Option<&str>,
        backup_secret_token: Option<&str>,
    ) -> Result<(Team, String, Option<String>), Error> {
        // Generate unique tokens if not provided
        let public_token = public_token
            .map(|s| s.to_string())
            .unwrap_or_else(|| random_string("phc_", 12));
        let secret_token = secret_token
            .map(|s| s.to_string())
            .unwrap_or_else(|| random_string("phs_", 12));
        let backup_secret_token = backup_secret_token.map(|s| s.to_string());

        const ORG_ID: &str = "019026a4be8000005bf3171d00629163";

        // Create team model
        let id = rand::thread_rng().gen_range(0..10_000_000);
        let team = Team {
            id,
            project_id: id as i64,
            name: "Test Team".to_string(),
            api_token: public_token.clone(),
            cookieless_server_hash_mode: Some(0),
            timezone: "UTC".to_string(),
            ..Default::default()
        };

        // Insert organization and project
        let mut conn = self.non_persons_writer.get_connection().await?;
        insert_organization_if_not_exists(&mut conn, ORG_ID, None).await?;

        let uuid = Uuid::now_v7();
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

        // Insert team with secret tokens
        let mut query_str = String::from(
            "INSERT INTO posthog_team (id, uuid, organization_id, project_id, api_token, secret_api_token"
        );

        // Add secret_api_token_backup column if provided
        if backup_secret_token.is_some() {
            query_str.push_str(", secret_api_token_backup");
        }

        query_str.push_str(", name, created_at, updated_at, app_urls, anonymize_ips, completed_snippet_onboarding, ingested_event, session_recording_opt_in, is_demo, access_control, test_account_filters, timezone, data_attributes, plugins_opt_in, opt_out_capture, event_names, event_names_with_usage, event_properties, event_properties_with_usage, event_properties_numerical, cookieless_server_hash_mode, base_currency, session_recording_retention_period, web_analytics_pre_aggregated_tables_enabled) VALUES ($1, $2, $3::uuid, $4, $5, $6");

        // Add backup token parameter placeholder if provided
        if backup_secret_token.is_some() {
            query_str.push_str(", $7");
            query_str.push_str(", $8, '2024-06-17 14:40:51.332036+00:00', '2024-06-17', '{}', false, false, false, false, false, false, '{}', 'UTC', '[\"data-attr\"]', false, false, '[]', '[]', '[]', '[]', '[]', $9, 'USD', '30d', false)");
        } else {
            query_str.push_str(", $7, '2024-06-17 14:40:51.332036+00:00', '2024-06-17', '{}', false, false, false, false, false, false, '{}', 'UTC', '[\"data-attr\"]', false, false, '[]', '[]', '[]', '[]', '[]', $8, 'USD', '30d', false)");
        }

        let mut query = sqlx::query(&query_str)
            .bind(team.id)
            .bind(uuid)
            .bind(ORG_ID)
            .bind(team.project_id)
            .bind(&team.api_token)
            .bind(&secret_token);

        if let Some(ref backup) = backup_secret_token {
            query = query.bind(backup);
        }

        query = query
            .bind(&team.name)
            .bind(team.cookieless_server_hash_mode.unwrap_or(0));

        let res = query.execute(&mut *conn).await?;
        assert_eq!(res.rows_affected(), 1);

        // Insert group type mappings
        insert_team_group_mappings(self.persons_writer.clone(), &team).await?;

        Ok((team, secret_token, backup_secret_token))
    }

    /// Populates the HyperCache with flag definitions for flag_definitions endpoint
    /// Uses the same cache key format that Django's cache warming uses
    pub async fn populate_flag_definitions_cache(
        &self,
        redis: Arc<dyn RedisClientTrait + Send + Sync>,
        team_id: i32,
    ) -> Result<(), Error> {
        // Cache key format: posthog:1:cache/teams/{team_id}/feature_flags/flags_with_cohorts.json
        let cache_key =
            format!("posthog:1:cache/teams/{team_id}/feature_flags/flags_with_cohorts.json");

        // Create minimal valid flag definitions response
        let flags_data = json!({
            "flags": [],
            "group_type_mapping": {},
            "cohorts": {}
        });

        let payload = serde_json::to_string(&flags_data)?;

        redis
            .set(cache_key, payload)
            .await
            .map_err(|e| anyhow::anyhow!("Failed to set cache: {}", e))?;

        Ok(())
    }

    /// Gets the organization_id for a team by querying the project table
    pub async fn get_organization_id_for_team(&self, team: &Team) -> Result<uuid::Uuid, Error> {
        let mut conn = self.non_persons_reader.get_connection().await?;
        let org_id: uuid::Uuid =
            sqlx::query_scalar("SELECT organization_id FROM posthog_project WHERE id = $1")
                .bind(team.project_id)
                .fetch_one(&mut *conn)
                .await?;
        Ok(org_id)
    }

    /// Simplified helper to populate cache for a team
    /// Handles Redis client setup internally
    pub async fn populate_cache_for_team(&self, team_id: i32) -> Result<(), Error> {
        let redis_client = setup_redis_client(Some(self.config.redis_url.clone())).await;
        self.populate_flag_definitions_cache(redis_client, team_id)
            .await
    }

    /// Generates a unique test email address with an optional prefix
    pub fn generate_test_email(prefix: &str) -> String {
        let unique_id = &uuid::Uuid::new_v4().to_string()[..8];
        format!("{prefix}_{unique_id}@posthog.com")
    }

    /// Adds a user to an organization with a specified membership level
    pub async fn add_user_to_organization(
        &self,
        user_id: i32,
        org_id: &uuid::Uuid,
        level: i16,
    ) -> Result<(), Error> {
        let mut conn = self.non_persons_writer.get_connection().await?;
        sqlx::query(
            "INSERT INTO posthog_organizationmembership (id, organization_id, user_id, level, joined_at, updated_at)
             VALUES ($1, $2, $3, $4, NOW(), NOW())",
        )
        .bind(uuid::Uuid::new_v4())
        .bind(org_id)
        .bind(user_id)
        .bind(level)
        .execute(&mut *conn)
        .await?;
        Ok(())
    }
}
