use std::sync::Arc;

use sqlx::postgres::any::AnyConnectionBackend;
use uuid::Uuid;

use redis::{RedisError, AsyncCommands};
use tracing::error;

use crate::{
    error::UnhandledError,
    types::{FingerprintedErrProps, OutputErrProps},
};

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
    pub name: Option<String>,
    pub description: Option<String>,
}

impl Issue {
    pub fn new(team_id: i32, name: String, description: String) -> Self {
        Self {
            id: Uuid::new_v4(),
            team_id,
            status: "active".to_string(), // TODO - we should at some point use an enum here
            name: Some(name),
            description: Some(description),
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
            SELECT id, team_id, status, name, description FROM posthog_errortrackingissue
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
            INSERT INTO posthog_errortrackingissue (id, team_id, status, name, description, created_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (id) DO NOTHING
            RETURNING (xmax = 0) AS was_inserted
            "#,
            self.id,
            self.team_id,
            self.status,
            self.name,
            self.description
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
    team_id: i32,
    fingerprinted: FingerprintedErrProps,
) -> Result<OutputErrProps, UnhandledError>
where
    A: sqlx::Acquire<'c, Database = sqlx::Postgres>,
{
    let mut conn = con.acquire().await?;
    // If an override already exists, just fast-path, skipping the transaction
    if let Some(issue_override) =
        IssueFingerprintOverride::load(&mut *conn, team_id, &fingerprinted.fingerprint).await?
    {
        return Ok(fingerprinted.to_output(issue_override.issue_id));
    }

    // UNWRAP: We never resolve an issue for an exception with no exception list
    let first = fingerprinted.exception_list.first().unwrap();
    let new_name = first.exception_type.clone();
    let new_description = first.exception_message.clone();

    // Start a transaction, so we can roll it back on override insert failure
    conn.begin().await?;
    // Insert a new issue
    let issue = Issue::new(team_id, new_name, new_description);
    // We don't actually care if we insert the issue here or not - conflicts aren't possible at
    // this stage.
    issue.insert(&mut *conn).await?;
    // Insert the fingerprint override
    let issue_override = IssueFingerprintOverride::create_or_load(
        &mut *conn,
        team_id,
        &fingerprinted.fingerprint,
        &issue,
    )
    .await?;

    // If we actually inserted a new row for the issue override, commit the transaction,
    // saving both the issue and the override. Otherwise, rollback the transaction, and
    // use the retrieved issue override.
    let was_created = issue_override.issue_id == issue.id;
    if !was_created {
        conn.rollback().await?;
    } else {
        conn.commit().await?;
    }

    Ok(fingerprinted.to_output(issue_override.issue_id))
}

pub async fn track_issue_metadata(
    team_id: i32,
    issue_id: Uuid,
    redis: Arc<redis::Client>,
    // TODO: Confirm timestamp format
    timestamp: String,
) -> Result<(), UnhandledError>
{

    let mut conn = match redis.get_multiplexed_async_connection().await {
        Ok(conn) => conn,
        Err(e) => {
            error!("Error tracking issue metadata: {:?}", e);
            return Ok(());
        }
    };

    let redis_key = format!("issue_metadata:{}:{}", team_id, issue_id);

    let res: Result<(), RedisError> = redis::pipe()
        .hset(redis_key.clone(), "last_seen", timestamp)
        .hincr(redis_key, "occurrences", 1)
        .query_async(&mut conn)
        .await;

    // on error, log the error but don't propagate it
    if let Err(e) = res {
        error!("Error tracking issue metadata: {:?}", e);
    }

    Ok(())
}