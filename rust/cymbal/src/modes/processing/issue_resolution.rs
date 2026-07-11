use std::fmt::Display;

use chrono::{DateTime, Utc};
use common_kafka::kafka_producer::{
    send_iter_to_kafka, send_keyed_iter_to_kafka, KafkaProduceError,
};
use rdkafka::error::RDKafkaErrorCode;
use serde::{Deserialize, Serialize};
use tracing::warn;
use uuid::Uuid;

use crate::core::types::notification::{
    IngestionNotification, IssueCreated, IssueNotificationContext, IssueReopened, IssueSnapshot,
    IssueSpiking, NotificationMeta,
};
use crate::metric_consts::KAFKA_MESSAGE_SIZE_TOO_LARGE_DROPPED;
use crate::modes::processing::rules::assignment::{Assignee, Assignment};
use crate::types::OutputErrProps;
use crate::{app_context::AppContext, error::UnhandledError, metric_consts::ISSUE_REOPENED};

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
    pub created_at: DateTime<Utc>,
}

pub struct IssueWithFirstSeen {
    pub id: Uuid,
    pub team_id: i32,
    pub status: IssueStatus,
    pub name: Option<String>,
    pub description: Option<String>,
    pub created_at: DateTime<Utc>,
    pub fingerprint_first_seen: Option<DateTime<Utc>>,
}

impl IssueWithFirstSeen {
    pub fn into_issue(self) -> (Issue, Option<DateTime<Utc>>) {
        (
            Issue {
                id: self.id,
                team_id: self.team_id,
                status: self.status,
                name: self.name,
                description: self.description,
                created_at: self.created_at,
            },
            self.fingerprint_first_seen,
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IssueStatus {
    Archived,
    Active,
    Resolved,
    PendingRelease,
    Suppressed,
}

impl Issue {
    pub async fn load_by_fingerprint<'c, E>(
        executor: E,
        team_id: i32,
        fingerprint: &str,
    ) -> Result<Option<IssueWithFirstSeen>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        let res = sqlx::query_as!(
            IssueWithFirstSeen,
            r#"
            SELECT i.id, i.team_id, i.status, i.name, i.description, i.created_at, f.first_seen as fingerprint_first_seen
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
            SELECT id, team_id, status, name, description, created_at FROM posthog_errortrackingissue
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
            created_at: Utc::now(),
        };

        sqlx::query!(
            r#"
            INSERT INTO posthog_errortrackingissue (id, team_id, status, name, description, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            "#,
            issue.id,
            issue.team_id,
            issue.status.to_string(),
            issue.name,
            issue.description,
            issue.created_at
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
            // DB row is now active; keep in-memory state in sync so downstream Kafka payloads
            // (fingerprint_issue_state, internal events) are not stale.
            self.status = IssueStatus::Active;
            metrics::counter!(ISSUE_REOPENED).increment(1);
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

#[derive(Debug, Clone, Serialize)]
pub struct FingerprintIssueState {
    pub team_id: i32,
    pub fingerprint: String,
    pub issue_id: Uuid,
    pub issue_name: Option<String>,
    pub issue_description: Option<String>,
    pub issue_status: String,
    pub assigned_user_id: Option<i64>,
    pub assigned_role_id: Option<String>,
    pub first_seen: String,
    pub is_deleted: i8,
    pub version: i64,
}

fn assignment_user_role_from_assignment(
    assignment: Option<&Assignment>,
) -> (Option<i64>, Option<String>) {
    let Some(a) = assignment else {
        return (None, None);
    };
    if let Some(uid) = a.user_id {
        return (Some(i64::from(uid)), None);
    }
    if let Some(rid) = a.role_id {
        return (None, Some(rid.to_string()));
    }
    (None, None)
}

impl FingerprintIssueState {
    pub fn new(
        issue: &Issue,
        fingerprint: &str,
        assignment: Option<&Assignment>,
        first_seen: DateTime<Utc>,
    ) -> Self {
        let now = Utc::now().timestamp_millis();
        let (assigned_user_id, assigned_role_id) = assignment_user_role_from_assignment(assignment);
        Self {
            team_id: issue.team_id,
            fingerprint: fingerprint.to_string(),
            issue_id: issue.id,
            issue_name: issue.name.clone(),
            issue_description: issue.description.clone(),
            issue_status: issue.status.to_string(),
            assigned_user_id,
            assigned_role_id,
            first_seen: first_seen.format("%Y-%m-%d %H:%M:%S%.3f").to_string(),
            is_deleted: 0,
            version: now,
        }
    }
}

pub async fn send_fingerprint_issue_state(
    context: &AppContext,
    issue: &Issue,
    fingerprint: &str,
    assignment: Option<&Assignment>,
    first_seen: DateTime<Utc>,
) -> Result<(), UnhandledError> {
    let msg = FingerprintIssueState::new(issue, fingerprint, assignment, first_seen);
    let results = send_iter_to_kafka(
        &context.immediate_producer,
        &context.config.fingerprint_issue_state_topic,
        &[msg],
    )
    .await;
    handle_produce_results(results, "fingerprint_issue_state")
}

// A `MessageSizeTooLarge` produce error is neither retriable nor recoverable: the payload is
// simply larger than the broker will accept. Mirroring the Node ingestion path, we drop the
// oversized message (log plus metric) instead of bubbling it up as an `UnhandledError`, which
// would fail the whole `/process` batch as a 5xx and report itself back into error tracking.
fn handle_produce_results(
    results: Vec<Result<(), KafkaProduceError>>,
    site: &'static str,
) -> Result<(), UnhandledError> {
    for result in results {
        match result {
            Ok(()) => {}
            Err(KafkaProduceError::KafkaProduceError { error })
                if matches!(
                    error.rdkafka_error_code(),
                    Some(RDKafkaErrorCode::MessageSizeTooLarge)
                ) =>
            {
                metrics::counter!(KAFKA_MESSAGE_SIZE_TOO_LARGE_DROPPED, "site" => site)
                    .increment(1);
                warn!(site, "Dropping oversized Kafka message: {error}");
            }
            Err(e) => return Err(UnhandledError::KafkaProduceError(e)),
        }
    }
    Ok(())
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

    // Batch variant of `load` for fingerprint-version selection: one round-trip
    // for all candidate values instead of one per version.
    pub async fn load_many<'c, E>(
        executor: E,
        team_id: i32,
        fingerprints: &[String],
    ) -> Result<Vec<Self>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        let res = sqlx::query_as!(
            IssueFingerprintOverride,
            r#"
            SELECT id, team_id, issue_id, fingerprint, version FROM posthog_errortrackingissuefingerprintv2
            WHERE team_id = $1 AND fingerprint = ANY($2)
            "#,
            team_id,
            fingerprints
        ).fetch_all(executor).await?;

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

pub async fn send_issue_created_notification(
    context: &AppContext,
    issue: &Issue,
    assignment: Option<Assignment>,
    output_props: OutputErrProps,
    event_uuid: Uuid,
    event_timestamp: &DateTime<Utc>,
) -> Result<(), UnhandledError> {
    let fingerprint = output_props.fingerprint.clone();
    publish_ingestion_notification(
        context,
        IngestionNotification::IssueCreated(IssueCreated {
            meta: notification_meta(issue),
            issue: issue_notification_context(issue, output_props),
            fingerprint,
            event_uuid,
            event_timestamp: event_timestamp.to_rfc3339(),
            assignee: assignment_to_string(assignment)?,
        }),
    )
    .await
}

pub async fn send_issue_reopened_notification(
    context: &AppContext,
    issue: &Issue,
    assignment: Option<Assignment>,
    output_props: OutputErrProps,
    event_timestamp: &DateTime<Utc>,
) -> Result<(), UnhandledError> {
    publish_ingestion_notification(
        context,
        IngestionNotification::IssueReopened(IssueReopened {
            meta: notification_meta(issue),
            issue: issue_notification_context(issue, output_props),
            event_timestamp: event_timestamp.to_rfc3339(),
            assignee: assignment_to_string(assignment)?,
        }),
    )
    .await
}

pub async fn send_issue_spiking_notification(
    context: &AppContext,
    issue: &Issue,
    output_props: OutputErrProps,
    computed_baseline: f64,
    current_bucket_value: f64,
) -> Result<(), UnhandledError> {
    publish_ingestion_notification(
        context,
        IngestionNotification::IssueSpiking(IssueSpiking {
            meta: notification_meta(issue),
            issue: issue_notification_context(issue, output_props),
            computed_baseline,
            current_bucket_value,
        }),
    )
    .await
}

fn notification_meta(issue: &Issue) -> NotificationMeta {
    NotificationMeta {
        notification_id: Uuid::now_v7(),
        team_id: issue.team_id,
    }
}

fn issue_notification_context(
    issue: &Issue,
    output_props: OutputErrProps,
) -> IssueNotificationContext {
    IssueNotificationContext {
        issue_id: issue.id,
        issue: issue_snapshot(issue),
        event_properties: output_props,
    }
}

fn issue_snapshot(issue: &Issue) -> IssueSnapshot {
    IssueSnapshot {
        name: issue.name.clone(),
        description: issue.description.clone(),
        status: issue.status.to_string(),
        created_at: issue.created_at,
    }
}

async fn publish_ingestion_notification(
    context: &AppContext,
    notification: IngestionNotification,
) -> Result<(), UnhandledError> {
    let results = send_keyed_iter_to_kafka(
        &context.immediate_producer,
        &context.config.ingestion_notifications_topic,
        |notification| Some(notification.partition_key()),
        std::iter::once(notification),
    )
    .await;
    handle_produce_results(results, "ingestion_notification")
}

fn assignment_to_string(assignment: Option<Assignment>) -> Result<Option<String>, UnhandledError> {
    let Some(assignment) = assignment else {
        return Ok(None);
    };

    let assignee = Assignee::try_from(&assignment)?;
    Ok(Some(serde_json::to_string(&assignee)?))
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
    use common_kafka::kafka_producer::KafkaProduceError;
    use rdkafka::error::{KafkaError, RDKafkaErrorCode};

    use super::handle_produce_results;
    use crate::{
        error::UnhandledError, modes::processing::rules::assignment::Assignee, sanitize_string,
    };

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

    #[test]
    fn it_drops_message_size_too_large_produce_errors() {
        let results = vec![Err(KafkaProduceError::KafkaProduceError {
            error: KafkaError::MessageProduction(RDKafkaErrorCode::MessageSizeTooLarge),
        })];
        assert!(handle_produce_results(results, "test").is_ok());
    }

    #[test]
    fn it_bubbles_up_other_produce_errors() {
        let results = vec![Err(KafkaProduceError::KafkaProduceCanceled)];
        assert!(matches!(
            handle_produce_results(results, "test"),
            Err(UnhandledError::KafkaProduceError(_))
        ));
    }
}
