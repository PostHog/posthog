use uuid::Uuid;

use crate::error::Error;

pub struct ErrorTrackingIssueFingerprint {
    pub id: i32,
    pub team_id: i32,
    pub fingerprint: String,
    pub issue_id: Uuid,
    pub version: i64,
}

pub struct ErrorTrackingGroup {
    pub id: Uuid,
    pub team_id: i32,
    pub fingerprint: String,
}

pub async fn get_fingerprint<'c, E>(
    executor: E,
    team_id: i32,
    fingerprint: String,
) -> Result<Option<ErrorTrackingIssueFingerprint>, Error>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    Ok(sqlx::query_as!(
        ErrorTrackingIssueFingerprint,
        r#"
            SELECT id, team_id, fingerprint, issue_id, version
            FROM posthog_errortrackingissuefingerprint
            WHERE team_id = $1 AND fingerprint = $2
            ORDER BY version DESC
        "#,
        team_id,
        fingerprint
    )
    .fetch_optional(executor)
    .await?)
}

pub async fn create_error_tracking_issue<'c, A>(
    connection: A,
    team_id: i32,
    fingerprint: String,
) -> Result<ErrorTrackingIssueFingerprint, Error>
where
    A: sqlx::Acquire<'c, Database = sqlx::Postgres>,
{
    let issue_id = Uuid::now_v7();

    let mut tx = connection.begin().await?;

    sqlx::query!(
        r#"
            INSERT INTO posthog_errortrackinggroup (id, team_id, fingerprint)
            VALUES ($1, $2, $3)
        "#,
        issue_id,
        team_id,
        &[fingerprint.clone()]
    )
    .execute(&mut *tx)
    .await?;

    // NOTE TO DAVID: I don't know that this version logic makes sense - when are the versions updated? I though
    // the fingerpring was more like a distinct_id, and the version should be on the issue group?
    let res = sqlx::query_as!(
        ErrorTrackingIssueFingerprint,
        r#"
            INSERT INTO posthog_errortrackingissuefingerprint (team_id, fingerprint, issue_id, version)
            VALUES ($1, $2, $3, 0)
            ON CONFLICT (team_id, fingerprint) DO UPDATE SET version = posthog_errortrackingissuefingerprint.version + 1
            RETURNING id, team_id, fingerprint, issue_id, version
        "#,
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
