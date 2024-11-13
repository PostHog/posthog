use uuid::Uuid;

use crate::error::UnhandledError;

pub struct IssueFingerprintOverride {
    pub id: Uuid,
    pub team_id: i32,
    pub fingerprint: String,
    pub issue_id: Uuid,
    pub version: i64,
}

#[derive(Debug, sqlx::FromRow)]
pub struct Issue {
    pub id: Uuid,
    pub team_id: i32,
    pub fingerprint: String,
}

pub async fn load_issue_override<'c, E>(
    executor: E,
    team_id: i32,
    fingerprint: &str,
) -> Result<Option<IssueFingerprintOverride>, UnhandledError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    Ok(sqlx::query_as!(
        IssueFingerprintOverride,
        r#"
            SELECT id, team_id, fingerprint, issue_id, version
            FROM posthog_errortrackingissuefingerprintv2
            WHERE team_id = $1 AND fingerprint = $2
        "#,
        team_id,
        fingerprint
    )
    .fetch_optional(executor)
    .await?)
}

pub async fn create_issue<'c, A>(
    connection: A,
    team_id: i32,
    fingerprint: &str,
) -> Result<IssueFingerprintOverride, UnhandledError>
where
    A: sqlx::Acquire<'c, Database = sqlx::Postgres>,
{
    let issue_id = Uuid::now_v7();

    let mut tx = connection.begin().await?;

    sqlx::query!(
        r#"
            INSERT INTO posthog_errortrackingissue (id, team_id)
            VALUES ($1, $2)
        "#,
        issue_id,
        team_id
    )
    .execute(&mut *tx)
    .await?;

    let res = sqlx::query_as!(
        IssueFingerprintOverride,
        r#"
            INSERT INTO posthog_errortrackingissuefingerprintv2 (id, team_id, fingerprint, issue_id, version)
            VALUES ($1, $2, $3, $4, 0)
            ON CONFLICT (team_id, fingerprint) DO UPDATE SET version = posthog_errortrackingissuefingerprintv2.version + 1
            RETURNING id, team_id, fingerprint, issue_id, version
        "#,
        Uuid::now_v7(),
        team_id,
        fingerprint,
        issue_id
    )
    .fetch_one(&mut *tx)
    .await?;

    tx.commit().await?;

    // TODO: write to Kafka

    Ok(res)
}
