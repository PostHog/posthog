use sqlx::postgres::any::AnyConnectionBackend;
use uuid::Uuid;

use crate::error::UnhandledError;

pub struct IssueFingerprintOverride {
    pub id: Uuid,
    pub team_id: i32,
    pub issue_id: Uuid,
    pub fingerprint: String,
    pub version: i64,
}

pub struct Issue {
    pub id: Uuid,
    pub team_id: i32,
    pub status: String,
}

impl Issue {
    pub fn new(team_id: i32) -> Self {
        Self {
            id: Uuid::new_v4(),
            team_id,
            status: "active".to_string(), // TODO - we should at some point use an enum here
        }
    }

    pub async fn load<'c, E>(
        executor: E,
        team_id: i32,
        issue_id: Uuid,
    ) -> Result<Option<Self>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        let res = sqlx::query_as!(
            Issue,
            r#"
            SELECT id, team_id, status FROM posthog_errortrackingissue
            WHERE team_id = $1 AND id = $2
            "#,
            team_id,
            issue_id
        )
        .fetch_optional(executor)
        .await?;

        Ok(res)
    }

    pub async fn insert<'c, E>(&self, executor: E) -> Result<bool, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        let did_insert = sqlx::query_scalar!(
            r#"
            INSERT INTO posthog_errortrackingissue (id, team_id, status, created_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (id) DO NOTHING
            RETURNING (xmax = 0) AS was_inserted
            "#,
            self.id,
            self.team_id,
            self.status
        )
        .fetch_one(executor)
        .await?;

        // TODO - I'm fairly sure the Option here is a bug in sqlx, so the unwrap will
        // never be hit, but nonetheless I'm not 100% sure the "no rows" case actually
        // means the insert was not done.
        Ok(did_insert.unwrap_or(false))
    }
}

impl IssueFingerprintOverride {
    pub async fn load<'c, E>(
        executor: E,
        team_id: i32,
        fingerprint: &str,
    ) -> Result<Option<Self>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        let res = sqlx::query_as!(
            IssueFingerprintOverride,
            r#"
            SELECT id, team_id, issue_id, fingerprint, version FROM posthog_errortrackingissuefingerprintv2
            WHERE team_id = $1 AND fingerprint = $2
            "#,
            team_id,
            fingerprint
        ).fetch_optional(executor).await?;

        Ok(res)
    }

    pub async fn create_or_load<'c, E>(
        executor: E,
        team_id: i32,
        fingerprint: &str,
        issue: &Issue,
    ) -> Result<Self, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        // We do an "ON CONFLICT DO NOTHING" here because callers can compare the returned issue id
        // to the passed Issue, to see if the issue was actually inserted or not.
        let res = sqlx::query_as!(
            IssueFingerprintOverride,
            r#"
            INSERT INTO posthog_errortrackingissuefingerprintv2 (id, team_id, issue_id, fingerprint, version, created_at)
            VALUES ($1, $2, $3, $4, 0, NOW())
            ON CONFLICT (team_id, fingerprint) DO NOTHING
            RETURNING id, team_id, issue_id, fingerprint, version
            "#,
            Uuid::new_v4(),
            team_id,
            issue.id,
            fingerprint
        ).fetch_one(executor).await?;

        Ok(res)
    }
}

pub async fn resolve_issue<'c, A>(
    con: A,
    fingerprint: &str,
    team_id: i32,
) -> Result<IssueFingerprintOverride, UnhandledError>
where
    A: sqlx::Acquire<'c, Database = sqlx::Postgres>,
{
    let mut conn = con.acquire().await?;
    // If an override already exists, just fast-path, skipping the transaction
    if let Some(issue_override) =
        IssueFingerprintOverride::load(&mut *conn, team_id, fingerprint).await?
    {
        return Ok(issue_override);
    }

    // Start a transaction, so we can roll it back on override insert failure
    conn.begin().await?;
    // Insert a new issue
    let issue = Issue::new(team_id);
    // We don't actually care if we insert the issue here or not - conflicts aren't possible at
    // this stage.
    issue.insert(&mut *conn).await?;
    // Insert the fingerprint override
    let issue_override =
        IssueFingerprintOverride::create_or_load(&mut *conn, team_id, fingerprint, &issue).await?;

    // If we actually inserted a new row for the issue override, commit the transaction,
    // saving both the issue and the override. Otherwise, rollback the transaction, and
    // use the retrieved issue override.
    let was_created = issue_override.issue_id == issue.id;
    if !was_created {
        conn.rollback().await?;
    } else {
        conn.commit().await?;
    }

    Ok(issue_override)
}
