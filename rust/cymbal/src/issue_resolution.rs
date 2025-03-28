use std::fmt::Display;

use chrono::{DateTime, Utc};
use common_kafka::kafka_messages::internal_events::{InternalEvent, InternalEventEvent};
use common_kafka::kafka_producer::send_iter_to_kafka;

use sqlx::Acquire;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::{ISSUE_CREATED, ISSUE_REOPENED},
    posthog_utils::{capture_issue_created, capture_issue_reopened},
};

#[derive(Debug, Clone)]
pub struct IssueFingerprintOverride {
    pub id: Uuid,
    pub team_id: i32,
    pub issue_id: Uuid,
    pub fingerprint: String,
    pub version: i64,
}

#[derive(Debug, Clone)]
pub struct Issue {
    pub id: Uuid,
    pub team_id: i32,
    pub status: IssueStatus,
    pub name: Option<String>,
    pub description: Option<String>,
}

#[derive(Debug, Clone, Copy)]
pub enum IssueStatus {
    Archived,
    Active,
    Resolved,
    PendingRelease,
    Suppressed,
}

impl Issue {
    pub fn new(team_id: i32, name: String, description: String) -> Self {
        Self {
            id: Uuid::new_v4(),
            team_id,
            status: IssueStatus::Active,
            name: Some(name),
            description: Some(description),
        }
    }

    pub async fn load_by_fingerprint<'c, E>(
        executor: E,
        team_id: i32,
        fingerprint: &str,
    ) -> Result<Option<Self>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        let res = sqlx::query_as!(
            Issue,
            r#"
            SELECT i.id, i.team_id, i.status, i.name, i.description
            FROM posthog_errortrackingissue i
            JOIN posthog_errortrackingissuefingerprintv2 f ON i.id = f.issue_id
            WHERE f.team_id = $1 AND f.fingerprint = $2
            "#,
            team_id,
            fingerprint
        )
        .fetch_optional(executor)
        .await?;

        Ok(res)
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
            ON CONFLICT (id) DO UPDATE SET team_id = EXCLUDED.team_id -- a no-op update to force a returned row
            RETURNING (xmax = 0) AS was_inserted
            "#,
            self.id,
            self.team_id,
            self.status.to_string(),
            self.name,
            self.description
        )
        .fetch_one(executor)
        .await.expect("Got at least one row back")
        // TODO - I'm fairly sure the Option here is a bug in sqlx, so the unwrap will
        // never be hit, but nonetheless I'm not 100% sure the "no rows" case actually
        // means the insert was not done.
        .unwrap_or(false);

        if did_insert {
            metrics::counter!(ISSUE_CREATED).increment(1);
        }

        Ok(did_insert)
    }

    pub async fn maybe_reopen<'c, E>(
        &self,
        executor: E,
        context: &AppContext,
    ) -> Result<(), UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        // If this issue is already active, or permanently suppressed, we don't need to do anything
        if matches!(self.status, IssueStatus::Active | IssueStatus::Suppressed) {
            return Ok(());
        }

        let res = sqlx::query_scalar!(
            r#"
            UPDATE posthog_errortrackingissue
            SET status = 'active'
            WHERE id = $1 AND status != 'active'
            RETURNING id
            "#,
            self.id
        )
        .fetch_all(executor)
        .await?;

        // If we actually updated a row
        if !res.is_empty() {
            metrics::counter!(ISSUE_REOPENED).increment(1);
            capture_issue_reopened(self.team_id, self.id);
            send_issue_reopened_alert(context, self).await?;
        }

        Ok(())
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
        first_seen: DateTime<Utc>,
    ) -> Result<Self, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        // We do an "ON CONFLICT DO NOTHING" here because callers can compare the returned issue id
        // to the passed Issue, to see if the issue was actually inserted or not.
        let res = sqlx::query_as!(
            IssueFingerprintOverride,
            r#"
            INSERT INTO posthog_errortrackingissuefingerprintv2 (id, team_id, issue_id, fingerprint, version, first_seen, created_at)
            VALUES ($1, $2, $3, $4, 0, $5, NOW())
            ON CONFLICT (team_id, fingerprint) DO UPDATE SET team_id = EXCLUDED.team_id -- a no-op update to force a returned row
            RETURNING id, team_id, issue_id, fingerprint, version
            "#,
            Uuid::new_v4(),
            team_id,
            issue.id,
            fingerprint,
            first_seen
        ).fetch_one(executor).await.expect("Got at least one row back");

        Ok(res)
    }
}

pub async fn resolve_issue(
    context: &AppContext,
    team_id: i32,
    fingerprint: &str,
    name: String,
    description: String,
    event_timestamp: DateTime<Utc>,
) -> Result<Issue, UnhandledError> {
    let mut conn = context.pool.acquire().await?;

    // Fast path - just fetch the issue directly, and then reopen it if needed
    let existing_issue = Issue::load_by_fingerprint(&mut *conn, team_id, fingerprint).await?;
    if let Some(issue) = existing_issue {
        issue.maybe_reopen(&mut *conn, context).await?;
        return Ok(issue);
    }

    // Slow path - insert a new issue, and then insert the fingerprint override, rolling
    // back the transaction if the override insert fails (since that indicates someone else
    // beat us to creating this new issue). Then, possibly reopen the issue.

    // Start a transaction, so we can roll it back on override insert failure
    let mut txn = conn.begin().await?;
    // Insert a new issue
    let issue = Issue::new(team_id, name.to_string(), description.to_string());
    // We don't actually care if we insert the issue here or not - conflicts aren't possible at
    // this stage.
    issue.insert(&mut *txn).await?;
    // Insert the fingerprint override
    let issue_override = IssueFingerprintOverride::create_or_load(
        &mut *txn,
        team_id,
        fingerprint,
        &issue,
        event_timestamp,
    )
    .await?;

    // If we actually inserted a new row for the issue override, commit the transaction,
    // saving both the issue and the override. Otherwise, rollback the transaction, and
    // use the retrieved issue override.
    let was_created = issue_override.issue_id == issue.id;
    if !was_created {
        txn.rollback().await?;
    } else {
        send_issue_created_alert(context, &issue).await?;
        txn.commit().await?;
        capture_issue_created(team_id, issue_override.issue_id);
    }

    // This being None is /almost/ impossible, unless between the transaction above finishing and
    // this point, someone merged the issue and deleted the old one, but if that happens,
    // we don't care about this reopen failing (since this issue is irrelevant anyway). IT would be
    // more efficient to fetch the entire Issue struct above along with the fingerprint, but we're
    // in the slow path anyway, so one extra DB hit is not a big deal.
    if let Some(issue) = Issue::load(&mut *conn, team_id, issue_override.issue_id).await? {
        issue.maybe_reopen(&mut *conn, context).await?;
    }

    Ok(issue)
}

async fn send_issue_created_alert(
    context: &AppContext,
    issue: &Issue,
) -> Result<(), UnhandledError> {
    send_internal_event(context, "$error_tracking_issue_created", issue).await
}

async fn send_issue_reopened_alert(
    context: &AppContext,
    issue: &Issue,
) -> Result<(), UnhandledError> {
    send_internal_event(context, "$error_tracking_issue_reopened", issue).await
}

async fn send_internal_event(
    context: &AppContext,
    event: &str,
    issue: &Issue,
) -> Result<(), UnhandledError> {
    let mut event = InternalEventEvent::new(event, issue.id, Utc::now(), None);
    event
        .insert_prop("name", issue.name.clone())
        .expect("Strings are serializable");
    event
        .insert_prop("description", issue.description.clone())
        .expect("Strings are serializable");

    send_iter_to_kafka(
        &context.immediate_producer,
        &context.config.internal_events_topic,
        &[InternalEvent {
            team_id: issue.team_id,
            event,
            person: None,
        }],
    )
    .await
    .into_iter()
    .collect::<Result<Vec<_>, _>>()?;

    Ok(())
}

impl From<String> for IssueStatus {
    fn from(s: String) -> Self {
        match s.as_str() {
            "archived" => IssueStatus::Archived,
            "active" => IssueStatus::Active,
            "resolved" => IssueStatus::Resolved,
            "pending_release" => IssueStatus::PendingRelease,
            "suppressed" => IssueStatus::Suppressed,
            s => unreachable!("Invalid issue status: {}", s),
        }
    }
}

impl Display for IssueStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            IssueStatus::Archived => write!(f, "archived"),
            IssueStatus::Active => write!(f, "active"),
            IssueStatus::Resolved => write!(f, "resolved"),
            IssueStatus::PendingRelease => write!(f, "pending_release"),
            IssueStatus::Suppressed => write!(f, "suppressed"),
        }
    }
}

#[cfg(test)]
mod test {
    use crate::sanitize_string;

    #[test]
    fn it_replaces_null_characters() {
        let content = sanitize_string("\u{0000} is not valid JSON".to_string());
        assert_eq!(content, "� is not valid JSON");
    }
}
