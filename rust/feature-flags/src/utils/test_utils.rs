use crate::{
    cohorts::cohort_models::{Cohort, CohortId},
    config::{Config, DEFAULT_TEST_CONFIG},
    flags::flag_models::{
        FeatureFlag, FeatureFlagRow, FlagFilters, FlagPropertyGroup, TEAM_FLAGS_CACHE_PREFIX,
    },
};
use anyhow::Error;
use common_database::{get_pool, Client};
use common_models::test_utils::setup_pg_reader_client_with_database_url_and_max_connections;
use common_redis::Client as RedisClientTrait;
use common_types::{PersonId, TeamId};
use rand::Rng;
use serde_json::{json, Value};
use sqlx::Row;
use std::sync::Arc;
use uuid::Uuid;

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
    let database_url = config.read_database_url.clone();
    let max_pg_connections = config.max_pg_connections;
    setup_pg_reader_client_with_database_url_and_max_connections(
        Some(database_url),
        Some(max_pg_connections),
    )
    .await
}

pub async fn setup_pg_writer_client(config: Option<&Config>) -> Arc<dyn Client + Send + Sync> {
    let config = config.unwrap_or(&DEFAULT_TEST_CONFIG);
    Arc::new(
        get_pool(&config.write_database_url, config.max_pg_connections)
            .await
            .expect("Failed to create Postgres client"),
    )
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
