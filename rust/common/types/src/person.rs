use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::Postgres;
use uuid::Uuid;

pub type PersonId = i64;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Person {
    pub id: PersonId,
    pub created_at: DateTime<Utc>,
    pub team_id: i32,
    pub uuid: Uuid,
    pub properties: Value,
    pub is_identified: bool,
    pub is_user_id: Option<i32>,
    pub version: Option<i64>,
}

impl Person {
    pub async fn from_distinct_id<'c, E>(
        e: E,
        team_id: i32,
        distinct_id: &str,
    ) -> Result<Option<Person>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        sqlx::query_as!(
            Person,
            r#"
                SELECT pp.id, pp.created_at, pp.team_id, pp.uuid, pp.properties, pp.is_identified, pp.is_user_id, pp.version
                FROM posthog_person pp
                INNER JOIN posthog_persondistinctid
                    ON pp.id = posthog_persondistinctid.person_id
                WHERE
                    posthog_persondistinctid.distinct_id = $1
                    AND posthog_persondistinctid.team_id = $2
                    AND pp.team_id = $2
                LIMIT 1
            "#,
            distinct_id,
            team_id
        )
        .fetch_optional(e)
        .await
    }

    pub async fn from_distinct_id_no_props<'c, E>(
        e: E,
        team_id: i32,
        distinct_id: &str,
    ) -> Result<Option<Person>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        sqlx::query_as!(
            Person,
            r#"
                SELECT pp.id, pp.created_at, pp.team_id, pp.uuid, '{}'::jsonb as properties, pp.is_identified, pp.is_user_id, pp.version
                FROM posthog_person pp
                INNER JOIN posthog_persondistinctid
                    ON pp.id = posthog_persondistinctid.person_id
                WHERE
                    posthog_persondistinctid.distinct_id = $1
                    AND posthog_persondistinctid.team_id = $2
                    AND pp.team_id = $2
                LIMIT 1
            "#,
            distinct_id,
            team_id
        )
        .fetch_optional(e)
        .await
    }
}
