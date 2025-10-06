use std::fmt::Display;
use std::sync::Arc;

use chrono::{DateTime, Utc};
use common_kafka::kafka_messages::internal_events::{InternalEvent, InternalEventEvent};
use common_kafka::kafka_producer::{send_iter_to_kafka, KafkaProduceError};

use common_types::error_tracking::NewFingerprintEvent;
use rdkafka::types::RDKafkaErrorCode;
use sqlx::{Acquire, PgConnection};
use uuid::Uuid;

use crate::assignment_rules::{try_assignment_rules, Assignee, Assignment};
use crate::teams::TeamManager;
use crate::types::{FingerprintedErrProps, OutputErrProps};
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

impl IssueStatus {
    fn as_str(&self) -> &'static str {
        match self {
            IssueStatus::Archived => "Archived",
            IssueStatus::Active => "Active",
            IssueStatus::Resolved => "Resolved",
            IssueStatus::PendingRelease => "Pending Release",
            IssueStatus::Suppressed => "Suppressed",
        }
    }
}

impl Issue {
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
            -- the "eligible_for_assignment!" forces sqlx to assume not null, which is correct in this case, but
            -- generally a risky override of sqlx's normal type checking
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

    pub async fn insert_new<'c, E>(
        team_id: i32,
        name: String,
        description: String,
        executor: E,
    ) -> Result<Issue, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        // Truncate the description to 255 characters, we've seen very large exception values
        let description = description.chars().take(255).collect();
        let issue = Self {
            id: Uuid::now_v7(),
            team_id,
            status: IssueStatus::Active,
            name: Some(name),
            description: Some(description),
        };

        sqlx::query!(
            r#"
            INSERT INTO posthog_errortrackingissue (id, team_id, status, name, description, created_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            "#,
            issue.id,
            issue.team_id,
            issue.status.to_string(),
            issue.name,
            issue.description
        )
        .execute(executor)
        .await?;

        Ok(issue)
    }

    pub async fn maybe_reopen<'c, E>(&mut self, executor: E) -> Result<bool, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        // If this issue is already active, or permanently suppressed, we don't need to do anything
        if matches!(self.status, IssueStatus::Active | IssueStatus::Suppressed) {
            return Ok(false);
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

        let reopened = !res.is_empty();
        if reopened {
            metrics::counter!(ISSUE_REOPENED).increment(1);
            capture_issue_reopened(self.team_id, self.id);
        }

        Ok(reopened)
    }

    pub async fn get_assignments<'c, E>(
        &self,
        executor: E,
    ) -> Result<Vec<Assignment>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        let assignments = sqlx::query_as!(
            Assignment,
            r#"
            SELECT id, issue_id, user_id, role_id, created_at FROM posthog_errortrackingissueassignment
            WHERE issue_id = $1
            "#,
            self.id
        )
        .fetch_all(executor)
        .await?;

        Ok(assignments)
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
    context: Arc<AppContext>,
    team_id: i32,
    name: String,
    description: String,
    event_timestamp: DateTime<Utc>,
    event_properties: FingerprintedErrProps,
) -> Result<Issue, UnhandledError> {
    let mut conn = context.pool.acquire().await?;
    // Fast path - just fetch the issue directly, and then reopen it if needed
    let existing_issue =
        Issue::load_by_fingerprint(&mut *conn, team_id, &event_properties.fingerprint.value)
            .await?;
    if let Some(mut issue) = existing_issue {
        if issue.maybe_reopen(&mut *conn).await? {
            let assignment = process_assignment(
                &mut conn,
                &context.team_manager,
                &issue,
                event_properties.clone(),
            )
            .await?;
            let output_props: OutputErrProps = event_properties.clone().to_output(issue.id);
            send_issue_reopened_alert(&context, &issue, assignment, output_props, &event_timestamp)
                .await?;
        }
        return Ok(issue);
    }

    // Slow path - insert a new issue, and then insert the fingerprint override, rolling
    // back the transaction if the override insert fails (since that indicates someone else
    // beat us to creating this new issue). Then, possibly reopen the issue.

    // Start a transaction, so we can roll it back on override insert failure
    let mut txn = conn.begin().await?;
    // Insert a new issue
    let issue = Issue::insert_new(
        team_id,
        name.to_string(),
        description.to_string(),
        &mut *txn,
    )
    .await?;

    // Insert the fingerprint override
    let issue_override = IssueFingerprintOverride::create_or_load(
        &mut *txn,
        team_id,
        &event_properties.fingerprint.value,
        &issue,
        event_timestamp,
    )
    .await?;

    // If we actually inserted a new row for the issue override, commit the transaction,
    // saving both the issue and the override. Otherwise, rollback the transaction, and
    // use the retrieved issue override.
    let was_created = issue_override.issue_id == issue.id;
    let mut issue = issue;
    if !was_created {
        txn.rollback().await?;
        // Replace the attempt issue with the existing one
        issue = Issue::load(&mut *conn, team_id, issue_override.id)
            .await?
            .unwrap_or(issue);

        // Since we just loaded an issue, check if it needs to be reopened
        if issue.maybe_reopen(&mut *conn).await? {
            let assignment = process_assignment(
                &mut conn,
                &context.team_manager,
                &issue,
                event_properties.clone(),
            )
            .await?;
            let output_props: OutputErrProps = event_properties.clone().to_output(issue.id);
            send_issue_reopened_alert(&context, &issue, assignment, output_props, &event_timestamp)
                .await?;
        }
    } else {
        metrics::counter!(ISSUE_CREATED).increment(1);
        let assignment = process_assignment(
            &mut txn,
            &context.team_manager,
            &issue,
            event_properties.clone(),
        )
        .await?;

        let output_props = event_properties.clone().to_output(issue.id);
        if context.config.embedding_enabled_team_id == Some(issue.team_id) {
            send_new_fingerprint_event(&context, &issue, &output_props).await?;
        }
        send_issue_created_alert(&context, &issue, assignment, output_props, &event_timestamp)
            .await?;
        txn.commit().await?;
        capture_issue_created(team_id, issue_override.issue_id);
    };

    Ok(issue)
}

pub async fn process_assignment(
    conn: &mut PgConnection,
    team_manager: &TeamManager,
    issue: &Issue,
    props: FingerprintedErrProps,
) -> Result<Option<Assignment>, UnhandledError> {
    let new_assignment = if let Some(new) = props.fingerprint.assignment.clone() {
        Some(new)
    } else {
        try_assignment_rules(conn, team_manager, issue.clone(), props.to_output(issue.id)).await?
    };

    let assignment = if let Some(new_assignment) = new_assignment {
        Some(new_assignment.apply(&mut *conn, issue.id).await?)
    } else {
        issue.get_assignments(&mut *conn).await?.first().cloned()
    };

    Ok(assignment)
}

async fn send_issue_created_alert(
    context: &AppContext,
    issue: &Issue,
    assignment: Option<Assignment>,
    output_props: OutputErrProps,
    event_timestamp: &DateTime<Utc>,
) -> Result<(), UnhandledError> {
    send_internal_event(
        context,
        "$error_tracking_issue_created",
        issue,
        assignment,
        output_props,
        event_timestamp,
    )
    .await
}

async fn send_new_fingerprint_event(
    context: &AppContext,
    issue: &Issue,
    output_props: &OutputErrProps,
) -> Result<(), UnhandledError> {
    let event = NewFingerprintEvent {
        team_id: issue.team_id,
        fingerprint: output_props.fingerprint.clone(),
        models: context.config.embedding_models.0.clone(),
        exception_list: (&output_props.exception_list).into(),
    };

    let res = send_iter_to_kafka(
        &context.immediate_producer,
        &context.config.new_fingerprints_topic,
        &[event],
    )
    .await
    .into_iter()
    .collect::<Result<Vec<_>, _>>();
    if let Err(err) = res {
        return Err(UnhandledError::KafkaProduceError(err));
    }
    Ok(())
}

async fn send_issue_reopened_alert(
    context: &AppContext,
    issue: &Issue,
    assignment: Option<Assignment>,
    output_props: OutputErrProps,
    event_timestamp: &DateTime<Utc>,
) -> Result<(), UnhandledError> {
    send_internal_event(
        context,
        "$error_tracking_issue_reopened",
        issue,
        assignment,
        output_props,
        event_timestamp,
    )
    .await
}

async fn send_internal_event(
    context: &AppContext,
    event: &str,
    issue: &Issue,
    new_assignment: Option<Assignment>,
    output_props: OutputErrProps,
    event_timestamp: &DateTime<Utc>,
) -> Result<(), UnhandledError> {
    let mut event = InternalEventEvent::new(event, issue.id, Utc::now(), None);
    event
        .insert_prop("name", issue.name.clone())
        .expect("Strings are serializable");
    event
        .insert_prop("description", issue.description.clone())
        .expect("Strings are serializable");
    event.insert_prop("status", issue.status.as_str())?;
    event.insert_prop("fingerprint", &output_props.fingerprint)?;
    event.insert_prop("exception_timestamp", event_timestamp)?;
    event.insert_prop("exception_props", output_props)?;

    if let Some(assignment) = new_assignment {
        let assignee = Assignee::try_from(&assignment)?;
        let stringified_assignee = serde_json::to_string(&assignee)?;

        event
            .insert_prop("assignee", stringified_assignee)
            .expect("Strings are serializable");
    }

    let iter = [InternalEvent {
        team_id: issue.team_id,
        event,
        person: None,
    }];

    let res = send_iter_to_kafka(
        &context.immediate_producer,
        &context.config.internal_events_topic,
        &iter,
    )
    .await
    .into_iter()
    .collect::<Result<Vec<_>, _>>();

    match res {
        Ok(_) => Ok(()),
        Err(KafkaProduceError::KafkaProduceError { error })
            if matches!(
                error.rdkafka_error_code(),
                Some(RDKafkaErrorCode::MessageSizeTooLarge)
            ) =>
        {
            let mut iter = iter;
            iter[0].event.properties.remove("exception_props");
            iter[0].event.insert_prop("message_was_too_large", true)?;
            send_iter_to_kafka(
                &context.immediate_producer,
                &context.config.internal_events_topic,
                &iter,
            )
            .await
            .into_iter()
            .collect::<Result<Vec<_>, _>>()?;
            Ok(())
        }
        Err(e) => Err(e.into()),
    }
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
    use crate::{assignment_rules::Assignee, sanitize_string};

    #[test]
    fn it_replaces_null_characters() {
        let content = sanitize_string("\u{0000} is not valid JSON".to_string());
        assert_eq!(content, "� is not valid JSON");
    }

    #[test]
    fn it_correctly_orders_stringified_assignee_keys() {
        let assignee = Assignee::User(1234);
        let stringified_assignee = serde_json::to_string(&assignee).unwrap();
        assert_eq!(stringified_assignee, "{\"type\":\"user\",\"id\":1234}");
    }
}
