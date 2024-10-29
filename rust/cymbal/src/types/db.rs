use uuid::Uuid;

pub struct ErrorTrackingIssueFingerprint {
    pub id: Uuid,
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

pub async fn error_tracking_issue_for_fingerprint<'c, E>(
    executor: E,
    team_id: i32,
    fingerprint: String,
) -> Uuid
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let res = sqlx::query_as!(
        ErrorTrackingIssueFingerprint,
        r#"
            SELECT *
            FROM posthog_errortrackingissuefingerprint
            WHERE team_id = $1 AND fingerprint = $2
            ORDER BY version DESC
        "#,
        team_id,
        fingerprint
    )
    .fetch_one(executor)
    .await;

    match res {
        Ok(issue_fingerprint) => issue_fingerprint.issue_id,
        Err(_) => {
            return create_error_tracking_issue(executor, team_id, fingerprint).await;
        }
    }
}

pub async fn create_error_tracking_issue<'c, E>(
    executor: E,
    team_id: i32,
    fingerprint: String,
) -> Uuid
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let issue_id = Uuid::now_v7();

    sqlx::query!(
        r#"
            INSERT INTO posthog_errortrackinggroup (id, team_id, fingerprint)
            VALUES ($1, $2, $3)
        "#,
        issue_id,
        team_id,
        fingerprint
    )
    .execute(executor)
    .await;

    sqlx::query!(
        r#"
            INSERT INTO posthog_errortrackingissuefingerprint (team_id, fingerprint, issue_id)
            VALUES ($1, $2, $3)
        "#,
        team_id,
        fingerprint,
        issue_id
    )
    .execute(executor)
    .await;

    // TODO: write to Kafka

    issue_id
}
