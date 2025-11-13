use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::PgConnection;
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
    pub async fn from_distinct_id(
        e: &mut PgConnection,
        team_id: i32,
        distinct_id: &str,
    ) -> Result<Option<Person>, sqlx::Error> {
        if let Some(res) = sqlx::query_as!(
            Person,
            r#"
                SELECT ppn.id, ppn.created_at, ppn.team_id, ppn.uuid, ppn.properties, ppn.is_identified, ppn.is_user_id, ppn.version
                FROM posthog_person_new ppn
                INNER JOIN posthog_persondistinctid
                    ON ppn.id = posthog_persondistinctid.person_id
                WHERE
                    posthog_persondistinctid.distinct_id = $1
                    AND posthog_persondistinctid.team_id = $2
                    AND ppn.team_id = $2
                LIMIT 1
            "#,
            distinct_id,
            team_id
        )
        .fetch_optional(&mut *e)
        .await? {
            return Ok(Some(res));
        }

        Self::from_distinct_id_legacy(e, team_id, distinct_id).await
    }

    pub async fn from_distinct_id_no_props(
        e: &mut PgConnection,
        team_id: i32,
        distinct_id: &str,
    ) -> Result<Option<Person>, sqlx::Error> {
        if let Some(res) = sqlx::query_as!(
            Person,
            r#"
                SELECT ppn.id, ppn.created_at, ppn.team_id, ppn.uuid, '{}'::jsonb as properties, ppn.is_identified, ppn.is_user_id, ppn.version
                FROM posthog_person_new ppn
                INNER JOIN posthog_persondistinctid
                    ON ppn.id = posthog_persondistinctid.person_id
                WHERE
                    posthog_persondistinctid.distinct_id = $1
                    AND posthog_persondistinctid.team_id = $2
                    AND ppn.team_id = $2
                LIMIT 1
            "#,
            distinct_id,
            team_id
        )
        .fetch_optional(&mut *e)
        .await? {
            return Ok(Some(res));
        }

        Self::from_distinct_id_no_props_legacy(e, team_id, distinct_id).await
    }

    async fn from_distinct_id_legacy(
        e: &mut PgConnection,
        team_id: i32,
        distinct_id: &str,
    ) -> Result<Option<Person>, sqlx::Error> {
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

    async fn from_distinct_id_no_props_legacy(
        e: &mut PgConnection,
        team_id: i32,
        distinct_id: &str,
    ) -> Result<Option<Person>, sqlx::Error> {
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
