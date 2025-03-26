use chrono::{DateTime, Utc};
use sqlx::Postgres;
use uuid::Uuid;

// Actually an "environment"
#[derive(Debug, Clone)]
pub struct Team {
    pub id: i32,
    pub project_id: Option<i64>,
    pub organization_id: Uuid,
    pub uuid: Uuid,
    pub api_token: String,
    pub name: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub anonymize_ips: bool,
    pub person_processing_opt_out: Option<bool>,
}

impl Team {
    pub async fn load<'c, E>(e: E, id: i32) -> Result<Option<Team>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        sqlx::query_as!(
            Team,
            r#"
                SELECT
                    id,
                    project_id,
                    organization_id,
                    uuid,
                    api_token,
                    name,
                    created_at,
                    updated_at,
                    anonymize_ips,
                    person_processing_opt_out
                FROM posthog_team
                WHERE id = $1
                LIMIT 1
            "#,
            id
        )
        .fetch_optional(e)
        .await
    }

    pub async fn load_by_token<'c, E>(e: E, token: &str) -> Result<Option<Team>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        sqlx::query_as!(
            Team,
            r#"
                SELECT
                    id,
                    project_id,
                    organization_id,
                    uuid,
                    api_token,
                    name,
                    created_at,
                    updated_at,
                    anonymize_ips,
                    person_processing_opt_out
                FROM posthog_team
                WHERE api_token = $1
                LIMIT 1
            "#,
            token
        )
        .fetch_optional(e)
        .await
    }
}
