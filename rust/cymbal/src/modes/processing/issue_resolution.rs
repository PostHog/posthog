use std::{
    fmt::Display,
    str::FromStr,
    time::{Duration, Instant},
};

use chrono::{DateTime, Utc};
use common_kafka::kafka_producer::{
    send_iter_to_kafka, send_keyed_iter_to_kafka, KafkaProduceError,
};
use moka::future::Cache;
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

// Django adds this interval to its inactivity cutoff because cached receipts skip writes.
pub const ISSUE_RECEIPT_CACHE_TTL: Duration = Duration::from_secs(60);
pub type IssueReceiptCache = Cache<(i32, Uuid), Instant>;

#[derive(sqlx::FromRow)]
struct RecordedIssueReceipt {
    status: String,
    previous_status: String,
}

const ERROR_TRACKING_EVENT_PROPERTIES_KEY_PREFIX: &str = "error_tracking:event_properties:v1";

// Upper bounds on the issue name and description we persist. Exception types and values are
// attacker-controlled and occasionally enormous (crash reporters embedding base64 minidumps,
// serialized blobs, etc.), so we cap both before writing to Postgres and Kafka.
const MAX_ISSUE_NAME_CHARS: usize = 255;
const MAX_ISSUE_DESCRIPTION_CHARS: usize = 255;

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
    pub severity: Option<String>,
    pub name: Option<String>,
    pub description: Option<String>,
    pub created_at: DateTime<Utc>,
}

pub struct IssueWithFirstSeen {
    pub id: Uuid,
    pub team_id: i32,
    pub status: IssueStatus,
    pub severity: Option<String>,
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
                severity: self.severity,
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

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum IssueSeverity {
    Low,
    Medium,
    High,
    Critical,
}

impl FromStr for IssueSeverity {
    type Err = ();

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        if value.eq_ignore_ascii_case("low") {
            Ok(Self::Low)
        } else if value.eq_ignore_ascii_case("medium") {
            Ok(Self::Medium)
        } else if value.eq_ignore_ascii_case("high") {
            Ok(Self::High)
        } else if value.eq_ignore_ascii_case("critical") {
            Ok(Self::Critical)
        } else {
            Err(())
        }
    }
}

pub(crate) fn infer_issue_severity(
    exception_level: Option<&str>,
    handled: Option<bool>,
) -> Option<IssueSeverity> {
    match exception_level.map(str::to_ascii_lowercase).as_deref() {
        Some("fatal" | "critical") => Some(IssueSeverity::Critical),
        Some("warning" | "warn") => Some(IssueSeverity::Medium),
        Some("info" | "log" | "debug" | "trace") => Some(IssueSeverity::Low),
        Some("error") => handled.map(|handled| {
            if handled {
                IssueSeverity::Medium
            } else {
                IssueSeverity::High
            }
        }),
        _ => None,
    }
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
            SELECT i.id, i.team_id, i.status, i.severity, i.name, i.description, i.created_at, f.first_seen as fingerprint_first_seen
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
            SELECT id, team_id, status, severity, name, description, created_at FROM posthog_errortrackingissue
            WHERE team_id = $1 AND id = $2
            "#,
            team_id,
            issue_id
        )
        .fetch_optional(executor)
        .await?;

        Ok(res)
    }

    pub(crate) async fn insert_new<'c, E>(
        team_id: i32,
        name: String,
        description: String,
        severity: Option<IssueSeverity>,
        executor: E,
    ) -> Result<Issue, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        // Truncate name and description, we've seen very large exception values (e.g. crash
        // reporters that stuff an entire base64-encoded minidump into the exception type).
        // An unbounded name also produces oversized fingerprint-issue-state Kafka messages,
        // which fail the produce with MessageSizeTooLarge.
        let name = name.chars().take(MAX_ISSUE_NAME_CHARS).collect();
        let description = description
            .chars()
            .take(MAX_ISSUE_DESCRIPTION_CHARS)
            .collect();
        let issue = Self {
            id: Uuid::now_v7(),
            team_id,
            status: IssueStatus::Active,
            severity: severity.map(|severity| severity.to_string()),
            name: Some(name),
            description: Some(description),
            created_at: Utc::now(),
        };

        sqlx::query!(
            r#"
            INSERT INTO posthog_errortrackingissue (id, team_id, status, severity, name, description, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            "#,
            issue.id,
            issue.team_id,
            issue.status.to_string(),
            issue.severity,
            issue.name,
            issue.description,
            issue.created_at
        )
        .execute(executor)
        .await?;

        Ok(issue)
    }

    pub async fn apply_initial_severity<'c, E>(
        &mut self,
        severity: String,
        executor: E,
    ) -> Result<(), sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query("UPDATE posthog_errortrackingissue SET severity = $1 WHERE id = $2")
            .bind(&severity)
            .bind(self.id)
            .execute(executor)
            .await?;
        self.severity = Some(severity);
        Ok(())
    }

    pub async fn has_recent_receipt(&self, receipts: &IssueReceiptCache) -> bool {
        receipts
            .get(&(self.team_id, self.id))
            .await
            .is_some_and(|started_at| started_at.elapsed() < ISSUE_RECEIPT_CACHE_TTL)
    }

    pub async fn maybe_reopen<'c, E>(
        &mut self,
        executor: E,
        receipts: &IssueReceiptCache,
    ) -> Result<bool, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        if matches!(self.status, IssueStatus::Active | IssueStatus::Suppressed)
            && self.has_recent_receipt(receipts).await
        {
            return Ok(false);
        }

        // Start the cache window before the write so a slow response cannot extend it.
        let started_at = Instant::now();
        // The sweep locks this same row. Read the status under that lock because a
        // cached active issue may have been resolved while this occurrence was in flight.
        let receipt = sqlx::query_as::<_, RecordedIssueReceipt>(
            r#"
            WITH locked_issue AS MATERIALIZED (
                SELECT id, status
                FROM posthog_errortrackingissue
                WHERE id = $1 AND team_id = $2
                FOR UPDATE
            )
            UPDATE posthog_errortrackingissue AS issue
            SET last_received_at = GREATEST(issue.last_received_at, clock_timestamp()),
                auto_resolve_sync_requested_at = CASE
                    WHEN locked_issue.status IN ('active', 'suppressed') THEN issue.auto_resolve_sync_requested_at
                    ELSE clock_timestamp()
                END,
                status = CASE
                    WHEN locked_issue.status IN ('active', 'suppressed') THEN locked_issue.status
                    ELSE 'active'
                END
            FROM locked_issue
            WHERE issue.id = locked_issue.id AND issue.team_id = $2
            RETURNING issue.status, locked_issue.status AS previous_status
            "#,
        )
        .bind(self.id)
        .bind(self.team_id)
        .fetch_optional(executor)
        .await?
        .ok_or_else(|| {
            UnhandledError::Other("issue disappeared while recording receipt".to_string())
        })?;

        self.status = IssueStatus::from(receipt.status);
        let reopened = !matches!(
            IssueStatus::from(receipt.previous_status),
            IssueStatus::Active | IssueStatus::Suppressed
        );
        receipts.insert((self.team_id, self.id), started_at).await;
        if reopened {
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
    pub issue_severity: Option<String>,
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
            issue_severity: issue.severity.clone(),
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fingerprint_issue_state_serializes_severity() {
        let issue = Issue {
            id: Uuid::now_v7(),
            team_id: 1,
            status: IssueStatus::Active,
            severity: Some("high".to_string()),
            name: Some("Issue".to_string()),
            description: None,
            created_at: Utc::now(),
        };

        let state = FingerprintIssueState::new(&issue, "fingerprint", None, Utc::now());
        let payload = serde_json::to_value(state).unwrap();

        assert_eq!(payload["issue_severity"], "high");
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

    pub async fn create_or_load(
        conn: &mut sqlx::PgConnection,
        team_id: i32,
        fingerprint: &str,
        issue: &Issue,
        first_seen: DateTime<Utc>,
    ) -> Result<Self, UnhandledError> {
        // We do an "ON CONFLICT DO NOTHING" here because callers can compare the returned issue id
        // to the passed Issue, to see if the issue was actually inserted or not. DO NOTHING takes
        // no row lock and writes no dead tuple on a losing racer, unlike a self-assigning DO UPDATE.
        let inserted = sqlx::query_as!(
            IssueFingerprintOverride,
            r#"
            INSERT INTO posthog_errortrackingissuefingerprintv2 (id, team_id, issue_id, fingerprint, version, first_seen, created_at)
            VALUES ($1, $2, $3, $4, 0, $5, NOW())
            ON CONFLICT (team_id, fingerprint) DO NOTHING
            RETURNING id, team_id, issue_id, fingerprint, version
            "#,
            Uuid::new_v4(),
            team_id,
            issue.id,
            fingerprint,
            first_seen
        ).fetch_optional(&mut *conn).await?;

        if let Some(inserted) = inserted {
            return Ok(inserted);
        }

        // Someone else won the insert, so DO NOTHING returned no row. Read the existing one back.
        Self::load(&mut *conn, team_id, fingerprint)
            .await?
            .ok_or_else(|| {
                UnhandledError::Other(
                    "fingerprint override conflict but existing row not found".to_string(),
                )
            })
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
        severity: issue.severity.clone(),
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

impl Display for IssueSeverity {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            IssueSeverity::Low => write!(f, "low"),
            IssueSeverity::Medium => write!(f, "medium"),
            IssueSeverity::High => write!(f, "high"),
            IssueSeverity::Critical => write!(f, "critical"),
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

    #[test]
    fn infers_issue_severity_only_from_confident_signals() {
        for (level, handled, expected) in [
            (Some("fatal"), Some(true), Some("critical")),
            (Some("critical"), Some(false), Some("critical")),
            (Some("error"), Some(false), Some("high")),
            (Some("error"), Some(true), Some("medium")),
            (Some("error"), None, None),
            (Some("warning"), Some(false), Some("medium")),
            (Some("warn"), None, Some("medium")),
            (Some("info"), Some(false), Some("low")),
            (Some("log"), Some(true), Some("low")),
            (Some("debug"), None, Some("low")),
            (Some("trace"), Some(true), Some("low")),
            (None, Some(false), None),
            (None, Some(true), None),
            (Some("custom"), Some(false), None),
            (Some("CUSTOM"), Some(true), None),
        ] {
            assert_eq!(
                super::infer_issue_severity(level, handled).map(|severity| severity.to_string()),
                expected.map(str::to_string)
            );
        }
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn initial_severity_update_reaches_state_and_notification_payloads(pool: sqlx::PgPool) {
        let mut issue = super::Issue::insert_new(
            1,
            "TypeError".to_string(),
            "Example".to_string(),
            None,
            &pool,
        )
        .await
        .unwrap();

        issue
            .apply_initial_severity("critical".to_string(), &pool)
            .await
            .unwrap();

        let state =
            super::FingerprintIssueState::new(&issue, "fingerprint", None, chrono::Utc::now());
        let snapshot = super::issue_snapshot(&issue);
        assert_eq!(state.issue_severity.as_deref(), Some("critical"));
        assert_eq!(snapshot.severity.as_deref(), Some("critical"));
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn receipt_refresh_uses_locked_status_and_preserves_suppression(pool: sqlx::PgPool) {
        let receipts = super::IssueReceiptCache::new(10);
        for status in ["active", "resolved", "suppressed"] {
            let mut issue =
                super::Issue::insert_new(1, "Error".into(), "Example".into(), None, &pool)
                    .await
                    .unwrap();
            sqlx::query("UPDATE posthog_errortrackingissue SET status = $1, last_received_at = NULL WHERE id = $2")
                .bind(status).bind(issue.id).execute(&pool).await.unwrap();

            let reopened = issue.maybe_reopen(&pool, &receipts).await.unwrap();
            assert_eq!(reopened, status == "resolved");
            assert_eq!(
                issue.status.to_string(),
                if status == "suppressed" {
                    "suppressed"
                } else {
                    "active"
                }
            );
            let (recent, pending): (bool, bool) = sqlx::query_as(
                "SELECT last_received_at >= now() - interval '1 minute', auto_resolve_sync_requested_at IS NOT NULL FROM posthog_errortrackingissue WHERE id = $1",
            )
            .bind(issue.id)
            .fetch_one(&pool)
            .await
            .unwrap();
            assert!(recent);
            assert_eq!(pending, status == "resolved");

            sqlx::query("UPDATE posthog_errortrackingissue SET auto_resolve_sync_requested_at = now() - interval '1 day' WHERE id = $1")
                .bind(issue.id).execute(&pool).await.unwrap();
            receipts.invalidate(&(issue.team_id, issue.id)).await;
            assert!(!issue.maybe_reopen(&pool, &receipts).await.unwrap());
            let preserved: bool = sqlx::query_scalar(
                "SELECT auto_resolve_sync_requested_at < now() - interval '23 hours' FROM posthog_errortrackingissue WHERE id = $1",
            )
            .bind(issue.id)
            .fetch_one(&pool)
            .await
            .unwrap();
            assert!(preserved);
        }
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn receipt_waiting_for_resolve_lock_reopens_committed_status(pool: sqlx::PgPool) {
        let receipts = super::IssueReceiptCache::new(10);
        let mut issue = super::Issue::insert_new(1, "Error".into(), "Example".into(), None, &pool)
            .await
            .unwrap();
        let issue_id = issue.id;
        let mut receipt_connection = pool.acquire().await.unwrap();
        let receipt_pid: i32 = sqlx::query_scalar("SELECT pg_backend_pid()")
            .fetch_one(&mut *receipt_connection)
            .await
            .unwrap();
        let mut resolving = pool.begin().await.unwrap();
        sqlx::query("UPDATE posthog_errortrackingissue SET status = 'resolved' WHERE id = $1")
            .bind(issue_id)
            .execute(&mut *resolving)
            .await
            .unwrap();

        let receipt = tokio::spawn(async move {
            let reopened = issue
                .maybe_reopen(&mut *receipt_connection, &receipts)
                .await
                .unwrap();
            (issue, reopened)
        });
        // Confirm the receipt is waiting on the resolver's lock before it commits.
        tokio::time::timeout(std::time::Duration::from_secs(5), async {
            loop {
                let waiting: bool = sqlx::query_scalar(
                    "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid = $1 AND NOT granted)",
                )
                .bind(receipt_pid)
                .fetch_one(&pool)
                .await
                .unwrap();
                if waiting {
                    break;
                }
                tokio::task::yield_now().await;
            }
        })
        .await
        .expect("receipt query must wait for the issue lock");
        resolving.commit().await.unwrap();

        let (issue, reopened) = receipt.await.unwrap();
        assert!(reopened);
        assert_eq!(issue.status, super::IssueStatus::Active);
        let (recent, pending): (bool, bool) = sqlx::query_as(
            "SELECT last_received_at >= now() - interval '1 minute', auto_resolve_sync_requested_at IS NOT NULL FROM posthog_errortrackingissue WHERE id = $1",
        )
        .bind(issue_id)
        .fetch_one(&pool)
        .await
        .unwrap();
        assert!(recent);
        assert!(pending);
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn receipt_cache_throttles_successful_writes_and_expired_receipts_refresh(
        pool: sqlx::PgPool,
    ) {
        let receipts = super::IssueReceiptCache::new(10);
        let mut issue = super::Issue::insert_new(1, "Error".into(), "Example".into(), None, &pool)
            .await
            .unwrap();
        assert!(!issue.maybe_reopen(&pool, &receipts).await.unwrap());
        let first: chrono::DateTime<chrono::Utc> = sqlx::query_scalar(
            "SELECT last_received_at FROM posthog_errortrackingissue WHERE id = $1",
        )
        .bind(issue.id)
        .fetch_one(&pool)
        .await
        .unwrap();
        assert!(!issue.maybe_reopen(&pool, &receipts).await.unwrap());
        let second: chrono::DateTime<chrono::Utc> = sqlx::query_scalar(
            "SELECT last_received_at FROM posthog_errortrackingissue WHERE id = $1",
        )
        .bind(issue.id)
        .fetch_one(&pool)
        .await
        .unwrap();
        assert_eq!(first, second);

        receipts
            .insert(
                (issue.team_id, issue.id),
                std::time::Instant::now() - super::ISSUE_RECEIPT_CACHE_TTL,
            )
            .await;
        sqlx::query("UPDATE posthog_errortrackingissue SET last_received_at = now() - interval '2 days' WHERE id = $1")
            .bind(issue.id).execute(&pool).await.unwrap();
        assert!(!issue.maybe_reopen(&pool, &receipts).await.unwrap());
        let recent: bool = sqlx::query_scalar("SELECT last_received_at >= now() - interval '1 minute' FROM posthog_errortrackingissue WHERE id = $1")
            .bind(issue.id).fetch_one(&pool).await.unwrap();
        assert!(recent);
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn failed_receipt_write_is_not_cached(pool: sqlx::PgPool) {
        let receipts = super::IssueReceiptCache::new(10);
        let mut issue = super::Issue::insert_new(1, "Error".into(), "Example".into(), None, &pool)
            .await
            .unwrap();
        issue.team_id = 2;
        assert!(issue.maybe_reopen(&pool, &receipts).await.is_err());
        assert!(!issue.has_recent_receipt(&receipts).await);
        issue.team_id = 1;
        assert!(!issue.maybe_reopen(&pool, &receipts).await.unwrap());
        assert!(issue.has_recent_receipt(&receipts).await);
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
