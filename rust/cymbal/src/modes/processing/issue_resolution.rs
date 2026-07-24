use std::fmt::Display;

use chrono::{DateTime, Utc};
use common_kafka::kafka_producer::{
    send_iter_to_kafka, send_keyed_iter_to_kafka, KafkaProduceError,
};
use serde::{Deserialize, Serialize};
use tracing::warn;
use uuid::Uuid;

use crate::core::types::notification::{
    IngestionNotification, IssueCreated, IssueNotificationContext, IssueReopened, IssueSnapshot,
    IssueSpiking, NotificationMeta,
};
use crate::modes::processing::rules::assignment::{Assignee, Assignment};
use crate::types::ProcessedExceptionProperties;
use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::{
        ISSUE_CREATED_EVENT_PROPERTIES_BYTES, ISSUE_CREATED_EVENT_PROPERTIES_STORED,
        ISSUE_CREATED_EVENT_PROPERTIES_STORE_FAILED, ISSUE_CREATED_EVENT_PROPERTIES_STORE_SKIPPED,
        ISSUE_REOPENED,
    },
};

const ERROR_TRACKING_EVENT_PROPERTIES_KEY_PREFIX: &str = "error_tracking:event_properties:v1";

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
    send_iter_to_kafka(
        &context.immediate_producer,
        &context.config.fingerprint_issue_state_topic,
        &[msg],
    )
    .await
    .into_iter()
    .collect::<Result<Vec<_>, KafkaProduceError>>()
    .map_err(UnhandledError::KafkaProduceError)?;
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
    processed_properties: ProcessedExceptionProperties,
    event_uuid: Uuid,
    event_timestamp: &DateTime<Utc>,
) -> Result<(), UnhandledError> {
    let fingerprint = processed_properties.fingerprint().to_string();
    store_error_tracking_event_properties(
        &*context.issue_buckets_redis_client,
        context.config.event_properties_ttl_seconds,
        context.config.event_properties_max_bytes,
        issue.team_id,
        event_uuid,
        "issue_created",
        &processed_properties,
    )
    .await;
    publish_ingestion_notification(
        context,
        IngestionNotification::IssueCreated(IssueCreated {
            meta: notification_meta(issue),
            issue: issue_notification_context(issue, processed_properties),
            fingerprint,
            event_uuid,
            event_timestamp: event_timestamp.to_rfc3339(),
            assignee: assignment_to_string(assignment)?,
        }),
    )
    .await
}

fn error_tracking_event_properties_key(team_id: i32, event_uuid: Uuid) -> String {
    format!("{ERROR_TRACKING_EVENT_PROPERTIES_KEY_PREFIX}:{team_id}:{event_uuid}")
}

async fn store_error_tracking_event_properties(
    redis: &(dyn common_redis::Client + Send + Sync),
    ttl_seconds: u64,
    max_bytes: usize,
    team_id: i32,
    event_uuid: Uuid,
    notification_type: &'static str,
    processed_properties: &ProcessedExceptionProperties,
) {
    let key = error_tracking_event_properties_key(team_id, event_uuid);
    let payload = match serde_json::to_vec(processed_properties) {
        Ok(payload) => payload,
        Err(error) => {
            metrics::counter!(ISSUE_CREATED_EVENT_PROPERTIES_STORE_FAILED, "reason" => "serialization", "notification_type" => notification_type).increment(1);
            warn!(team_id, event_uuid = %event_uuid, notification_type, error = %error, "failed to serialize lifecycle event properties");
            return;
        }
    };

    metrics::histogram!(ISSUE_CREATED_EVENT_PROPERTIES_BYTES, "notification_type" => notification_type)
        .record(payload.len() as f64);
    if payload.len() > max_bytes {
        metrics::counter!(ISSUE_CREATED_EVENT_PROPERTIES_STORE_SKIPPED, "reason" => "payload_too_large", "notification_type" => notification_type)
            .increment(1);
        return;
    }

    if let Err(error) = redis
        .set_bytes(key.clone(), payload, Some(ttl_seconds))
        .await
    {
        metrics::counter!(ISSUE_CREATED_EVENT_PROPERTIES_STORE_FAILED, "reason" => "redis", "notification_type" => notification_type)
            .increment(1);
        warn!(team_id, event_uuid = %event_uuid, notification_type, error = %error, "failed to store lifecycle event properties");
        return;
    }

    metrics::counter!(ISSUE_CREATED_EVENT_PROPERTIES_STORED, "notification_type" => notification_type)
        .increment(1);
}

pub async fn send_issue_reopened_notification(
    context: &AppContext,
    issue: &Issue,
    assignment: Option<Assignment>,
    processed_properties: ProcessedExceptionProperties,
    event_uuid: Uuid,
    event_timestamp: &DateTime<Utc>,
) -> Result<(), UnhandledError> {
    store_error_tracking_event_properties(
        &*context.issue_buckets_redis_client,
        context.config.event_properties_ttl_seconds,
        context.config.event_properties_max_bytes,
        issue.team_id,
        event_uuid,
        "issue_reopened",
        &processed_properties,
    )
    .await;
    publish_ingestion_notification(
        context,
        IngestionNotification::IssueReopened(IssueReopened {
            meta: notification_meta(issue),
            issue: issue_notification_context(issue, processed_properties),
            event_uuid,
            event_timestamp: event_timestamp.to_rfc3339(),
            assignee: assignment_to_string(assignment)?,
        }),
    )
    .await
}

pub async fn send_issue_spiking_notification(
    context: &AppContext,
    issue: &Issue,
    processed_properties: ProcessedExceptionProperties,
    event_uuid: Uuid,
    event_timestamp: &str,
    computed_baseline: f64,
    current_bucket_value: f64,
) -> Result<(), UnhandledError> {
    store_error_tracking_event_properties(
        &*context.issue_buckets_redis_client,
        context.config.event_properties_ttl_seconds,
        context.config.event_properties_max_bytes,
        issue.team_id,
        event_uuid,
        "issue_spiking",
        &processed_properties,
    )
    .await;
    let assignment = issue
        .get_assignments(&context.posthog_pool)
        .await?
        .into_iter()
        .next();

    publish_ingestion_notification(
        context,
        IngestionNotification::IssueSpiking(IssueSpiking {
            meta: notification_meta(issue),
            issue: issue_notification_context(issue, processed_properties),
            event_uuid,
            event_timestamp: event_timestamp.to_string(),
            computed_baseline,
            current_bucket_value,
            assignee: assignment_to_string(assignment)?,
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
    processed_properties: ProcessedExceptionProperties,
) -> IssueNotificationContext {
    IssueNotificationContext {
        issue_id: issue.id,
        issue: issue_snapshot(issue),
        event_properties: processed_properties,
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
    send_keyed_iter_to_kafka(
        &context.immediate_producer,
        &context.config.ingestion_notifications_topic,
        |notification| Some(notification.partition_key()),
        std::iter::once(notification),
    )
    .await
    .into_iter()
    .collect::<Result<Vec<_>, KafkaProduceError>>()
    .map_err(UnhandledError::KafkaProduceError)?;
    Ok(())
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
    use common_redis::{MockRedisClient, MockRedisValue};
    use uuid::Uuid;

    use crate::{
        modes::processing::rules::assignment::Assignee, sanitize_string,
        types::ProcessedExceptionProperties,
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
    fn error_tracking_event_properties_keys_are_tenant_scoped_and_deterministic() {
        let event_uuid = Uuid::parse_str("01982721-5e00-7000-8000-000000000001").unwrap();

        assert_eq!(
            super::error_tracking_event_properties_key(42, event_uuid),
            "error_tracking:event_properties:v1:42:01982721-5e00-7000-8000-000000000001"
        );
    }

    #[tokio::test]
    async fn stores_full_event_properties_as_raw_json_with_a_ttl() {
        let redis = MockRedisClient::new();
        let event_uuid = Uuid::parse_str("01982721-5e00-7000-8000-000000000001").unwrap();
        let properties_json = serde_json::json!({
            "$exception_list": [{"type": "Error", "value": "boom 💥"}],
            "$exception_fingerprint": "abc",
            "$exception_fingerprint_record": [{"type": "manual"}],
            "$exception_issue_id": Uuid::nil(),
            "$exception_handled": false,
            "$exception_types": ["Error"],
            "$exception_values": ["boom 💥"],
            "$exception_sources": [],
            "$exception_functions": [],
            "custom": {"nested": [1, null, true]},
        });
        let properties: ProcessedExceptionProperties =
            serde_json::from_value(properties_json.clone()).unwrap();

        super::store_error_tracking_event_properties(
            &redis,
            172_800,
            1_048_576,
            42,
            event_uuid,
            "issue_created",
            &properties,
        )
        .await;

        let calls = redis.get_calls();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].op, "set_bytes");
        match &calls[0].value {
            MockRedisValue::Bytes(payload, Some(172_800)) => {
                assert_eq!(
                    serde_json::from_slice::<serde_json::Value>(payload).unwrap(),
                    properties_json
                );
            }
            value => panic!("unexpected Redis value: {value:?}"),
        }
    }

    #[tokio::test]
    async fn skips_event_properties_that_exceed_the_size_limit() {
        let redis = MockRedisClient::new();
        let properties_json = serde_json::json!({
            "$exception_list": [{"type": "Error", "value": "boom"}],
            "$exception_fingerprint": "abc",
            "$exception_fingerprint_record": [{"type": "manual"}],
            "$exception_issue_id": Uuid::nil(),
            "$exception_handled": false,
            "$exception_types": ["Error"],
            "$exception_values": ["boom"],
            "$exception_sources": [],
            "$exception_functions": [],
            "custom": "x".repeat(1024),
        });
        let properties: ProcessedExceptionProperties =
            serde_json::from_value(properties_json).unwrap();

        super::store_error_tracking_event_properties(
            &redis,
            172_800,
            128,
            42,
            Uuid::parse_str("01982721-5e00-7000-8000-000000000001").unwrap(),
            "issue_created",
            &properties,
        )
        .await;

        assert!(redis.get_calls().is_empty());
    }
}
