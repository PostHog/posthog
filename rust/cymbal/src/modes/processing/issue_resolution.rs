use std::{fmt::Display, str::FromStr};

use chrono::{DateTime, Utc};
use common_kafka::kafka_producer::{
    send_iter_to_kafka, send_keyed_iter_to_kafka, KafkaProduceError,
};
use rdkafka::error::RDKafkaErrorCode;
use serde::{Deserialize, Serialize};
use tracing::warn;
use uuid::Uuid;

use crate::core::types::frames::releases::ReleaseInfo;
use crate::core::types::notification::{
    IngestionNotification, IssueCreated, IssueNotificationContext, IssueReopened, IssueSnapshot,
    IssueSpiking, NotificationMeta, ReopenedByRelease, SeveritySource,
};
use crate::modes::processing::rules::assignment::{Assignee, Assignment};
use crate::types::ProcessedExceptionProperties;
use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::{
        INGESTION_NOTIFICATION_SKIPPED, ISSUE_CREATED_EVENT_PROPERTIES_BYTES,
        ISSUE_CREATED_EVENT_PROPERTIES_STORED, ISSUE_CREATED_EVENT_PROPERTIES_STORE_FAILED,
        ISSUE_CREATED_EVENT_PROPERTIES_STORE_SKIPPED, ISSUE_REOPENED,
    },
};

const ERROR_TRACKING_EVENT_PROPERTIES_KEY_PREFIX: &str = "error_tracking:event_properties:v1";

// Upper bounds on the issue name and description we persist. Exception types and values are
// attacker-controlled and occasionally enormous (crash reporters embedding base64 minidumps,
// serialized blobs, etc.), so we cap both before writing to Postgres and Kafka.
const MAX_ISSUE_NAME_CHARS: usize = 255;
const MAX_ISSUE_DESCRIPTION_CHARS: usize = 255;
// The `resolved_until` value Django writes for an issue resolved until a new release. Any other
// value, or none, reopens a resolved issue on the next exception.
const RESOLVED_UNTIL_NEW_RELEASE: &str = "new_release";

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
    pub resolved_until: Option<String>,
    pub latest_release_id: Option<Uuid>,
    pub latest_release_created_at: Option<DateTime<Utc>>,
}

pub struct IssueWithFirstSeen {
    pub id: Uuid,
    pub team_id: i32,
    pub status: IssueStatus,
    pub severity: Option<String>,
    pub name: Option<String>,
    pub description: Option<String>,
    pub created_at: DateTime<Utc>,
    pub resolved_until: Option<String>,
    pub latest_release_id: Option<Uuid>,
    pub latest_release_created_at: Option<DateTime<Utc>>,
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
                resolved_until: self.resolved_until,
                latest_release_id: self.latest_release_id,
                latest_release_created_at: self.latest_release_created_at,
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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReleaseCheck {
    Unchanged,
    StaysResolved,
    RecordRelease,
    Reopen,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Reopened {
    pub previous_status: String,
    pub cause: ReopenCause,
}

/// The issue row as `apply_release` locked it, before its own write.
#[derive(sqlx::FromRow)]
struct LockedIssue {
    status: String,
    name: Option<String>,
    severity: Option<String>,
    resolved_until: Option<String>,
    latest_release_id: Option<Uuid>,
    latest_release_created_at: Option<DateTime<Utc>>,
    reopen: bool,
    record_release: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReopenCause {
    NewOccurrence,
    NewRelease(ReopenedByRelease),
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
            SELECT i.id, i.team_id, i.status, i.severity, i.name, i.description, i.created_at, i.resolved_until, i.latest_release_id, i.latest_release_created_at, f.first_seen as fingerprint_first_seen
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
            SELECT id, team_id, status, severity, name, description, created_at, resolved_until, latest_release_id, latest_release_created_at FROM posthog_errortrackingissue
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
        release: Option<&ReleaseInfo>,
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
            resolved_until: None,
            latest_release_id: release.map(ReleaseInfo::id),
            latest_release_created_at: release.map(ReleaseInfo::created_at),
        };

        sqlx::query!(
            r#"
            INSERT INTO posthog_errortrackingissue (id, team_id, status, severity, name, description, created_at, latest_release_id, latest_release_created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            "#,
            issue.id,
            issue.team_id,
            issue.status.to_string(),
            issue.severity,
            issue.name,
            issue.description,
            issue.created_at,
            issue.latest_release_id,
            issue.latest_release_created_at
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

    fn resolved_until_new_release(&self) -> bool {
        self.resolved_until.as_deref() == Some(RESOLVED_UNTIL_NEW_RELEASE)
    }

    pub fn release_check(&self, release_created_at: Option<DateTime<Utc>>) -> ReleaseCheck {
        let newer = release_created_at.is_some_and(|created_at| {
            self.latest_release_created_at
                .is_none_or(|latest| created_at > latest)
        });
        match self.status {
            IssueStatus::Suppressed => ReleaseCheck::Unchanged,
            IssueStatus::Active if newer => ReleaseCheck::RecordRelease,
            IssueStatus::Active => ReleaseCheck::Unchanged,
            IssueStatus::Resolved
                if self.resolved_until_new_release() && release_created_at.is_some() && !newer =>
            {
                ReleaseCheck::StaysResolved
            }
            _ => ReleaseCheck::Reopen,
        }
    }

    /// Refreshes this copy from the locked row, and returns the reopen if there was one.
    pub async fn apply_release<'c, E>(
        &mut self,
        executor: E,
        release: Option<&ReleaseInfo>,
    ) -> Result<Option<Reopened>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        let release_created_at = release.map(ReleaseInfo::created_at);
        if !matches!(
            self.release_check(release_created_at),
            ReleaseCheck::RecordRelease | ReleaseCheck::Reopen
        ) {
            return Ok(None);
        }

        // Decided again on the locked row, because a person can resolve the issue after this worker
        // loaded it. A resolved issue's latest release then moves only with the reopen.
        let locked: Option<LockedIssue> = sqlx::query_as(
            r#"
            WITH locked AS (
                SELECT
                    id, status, name, severity, resolved_until, latest_release_id,
                    latest_release_created_at,
                    status NOT IN ('active', 'suppressed') AND (
                        status != 'resolved'
                        OR resolved_until IS DISTINCT FROM 'new_release'
                        OR latest_release_created_at IS NULL
                        OR $3::timestamptz IS NULL
                        OR $3::timestamptz > latest_release_created_at
                    ) AS reopen,
                    $3::timestamptz IS NOT NULL AND (
                        latest_release_created_at IS NULL
                        OR $3::timestamptz > latest_release_created_at
                    ) AS newer
                FROM posthog_errortrackingissue
                WHERE id = $1
                FOR UPDATE
            ),
            decided AS (
                SELECT *, newer AND (status = 'active' OR reopen) AS record_release FROM locked
            ),
            updated AS (
                UPDATE posthog_errortrackingissue AS issue
                SET
                    status = CASE WHEN decided.reopen THEN 'active' ELSE issue.status END,
                    resolved_at = CASE WHEN decided.reopen THEN NULL ELSE issue.resolved_at END,
                    resolved_until = CASE WHEN decided.reopen THEN NULL ELSE issue.resolved_until END,
                    latest_release_id = CASE
                        WHEN decided.record_release THEN $2::uuid ELSE issue.latest_release_id
                    END,
                    latest_release_created_at = CASE
                        WHEN decided.record_release THEN $3::timestamptz
                        ELSE issue.latest_release_created_at
                    END
                FROM decided
                WHERE issue.id = decided.id AND (decided.reopen OR decided.record_release)
            )
            SELECT
                status, name, severity, resolved_until, latest_release_id, latest_release_created_at,
                reopen, record_release
            FROM decided
            "#,
        )
        .bind(self.id)
        .bind(release.map(ReleaseInfo::id))
        .bind(release_created_at)
        .fetch_optional(executor)
        .await?;

        let Some(locked) = locked else {
            return Ok(None);
        };
        self.name = locked.name;
        self.severity = locked.severity;
        self.status = if locked.reopen {
            IssueStatus::Active
        } else {
            IssueStatus::from(locked.status.clone())
        };
        self.resolved_until = if locked.reopen {
            None
        } else {
            locked.resolved_until.clone()
        };
        (self.latest_release_id, self.latest_release_created_at) = if locked.record_release {
            (release.map(ReleaseInfo::id), release_created_at)
        } else {
            (locked.latest_release_id, locked.latest_release_created_at)
        };
        if !locked.reopen {
            return Ok(None);
        }
        metrics::counter!(ISSUE_REOPENED).increment(1);

        let cause = match (
            locked.status.as_str(),
            locked.resolved_until.as_deref(),
            locked.latest_release_created_at,
            release,
        ) {
            ("resolved", Some(RESOLVED_UNTIL_NEW_RELEASE), Some(_), Some(release)) => {
                ReopenCause::NewRelease(release.into())
            }
            _ => ReopenCause::NewOccurrence,
        };
        Ok(Some(Reopened {
            previous_status: locked.status,
            cause,
        }))
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
            latest_release_id: None,
            latest_release_created_at: None,
            resolved_until: None,
        };

        let state = FingerprintIssueState::new(&issue, "fingerprint", None, Utc::now());
        let payload = serde_json::to_value(state).unwrap();

        assert_eq!(payload["issue_severity"], "high");
    }

    #[test]
    fn only_an_oversized_produce_is_skipped() {
        let produce_error = |code| KafkaProduceError::KafkaProduceError {
            error: rdkafka::error::KafkaError::MessageProduction(code),
        };
        assert!(is_message_too_large(&produce_error(
            RDKafkaErrorCode::MessageSizeTooLarge
        )));
        assert!(!is_message_too_large(&produce_error(
            RDKafkaErrorCode::QueueFull
        )));
        assert!(!is_message_too_large(
            &KafkaProduceError::KafkaProduceCanceled
        ));
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
    severity_source: Option<SeveritySource>,
) -> Result<(), UnhandledError> {
    let fingerprint = processed_properties.fingerprint().to_string();
    store_error_tracking_event_properties(
        &*context.issue_buckets_redis_client,
        EventPropertiesLimits {
            ttl_seconds: context.config.event_properties_ttl_seconds,
            max_bytes: context.config.event_properties_max_bytes,
        },
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
            severity_source,
        }),
    )
    .await
}

fn error_tracking_event_properties_key(team_id: i32, event_uuid: Uuid) -> String {
    format!("{ERROR_TRACKING_EVENT_PROPERTIES_KEY_PREFIX}:{team_id}:{event_uuid}")
}

struct EventPropertiesLimits {
    ttl_seconds: u64,
    max_bytes: usize,
}

async fn store_error_tracking_event_properties(
    redis: &(dyn common_redis::Client + Send + Sync),
    limits: EventPropertiesLimits,
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
    if payload.len() > limits.max_bytes {
        metrics::counter!(ISSUE_CREATED_EVENT_PROPERTIES_STORE_SKIPPED, "reason" => "payload_too_large", "notification_type" => notification_type)
            .increment(1);
        return;
    }

    if let Err(error) = redis
        .set_bytes(key, payload, Some(limits.ttl_seconds))
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
    reopened: Reopened,
) -> Result<(), UnhandledError> {
    store_error_tracking_event_properties(
        &*context.issue_buckets_redis_client,
        EventPropertiesLimits {
            ttl_seconds: context.config.event_properties_ttl_seconds,
            max_bytes: context.config.event_properties_max_bytes,
        },
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
            reopened_by_release: match reopened.cause {
                ReopenCause::NewRelease(release) => Some(release),
                ReopenCause::NewOccurrence => None,
            },
            previous_status: Some(reopened.previous_status),
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
        EventPropertiesLimits {
            ttl_seconds: context.config.event_properties_ttl_seconds,
            max_bytes: context.config.event_properties_max_bytes,
        },
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
    let partition_key = notification.partition_key();
    let results = send_keyed_iter_to_kafka(
        &context.immediate_producer,
        &context.config.ingestion_notifications_topic,
        |notification| Some(notification.partition_key()),
        std::iter::once(notification),
    )
    .await;
    for result in results {
        match result {
            Ok(()) => {}
            Err(error) if is_message_too_large(&error) => {
                metrics::counter!(INGESTION_NOTIFICATION_SKIPPED, "reason" => "message_too_large")
                    .increment(1);
                warn!(partition_key = %partition_key, error = %error, "skipped an ingestion notification too large to produce");
            }
            Err(error) => return Err(UnhandledError::KafkaProduceError(error)),
        }
    }
    Ok(())
}

/// The notification embeds the event's processed properties, which have no size bound. A
/// message too large to produce fails on every retry, so failing the request on it stalls
/// ingestion for the whole partition.
fn is_message_too_large(error: &KafkaProduceError) -> bool {
    matches!(
        error,
        KafkaProduceError::KafkaProduceError { error }
            if error.rdkafka_error_code() == Some(RDKafkaErrorCode::MessageSizeTooLarge)
    )
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
    use chrono::{DateTime, Duration, Utc};
    use common_redis::{MockRedisClient, MockRedisValue};
    use uuid::Uuid;

    use super::{Issue, IssueStatus, ReleaseCheck, ReopenCause, RESOLVED_UNTIL_NEW_RELEASE};
    use crate::{
        core::types::frames::releases::{ReleaseInfo, ReleaseRecord},
        modes::processing::rules::assignment::Assignee,
        sanitize_string,
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
    async fn a_reopen_returns_the_status_it_replaced_once(pool: sqlx::PgPool) {
        let mut issue =
            super::Issue::insert_new(1, "TypeError".to_string(), String::new(), None, None, &pool)
                .await
                .unwrap();
        sqlx::query("UPDATE posthog_errortrackingissue SET status = 'resolved', name = 'Updated issue', severity = 'high' WHERE id = $1")
            .bind(issue.id)
            .execute(&pool)
            .await
            .unwrap();
        issue.status = super::IssueStatus::Resolved;
        // A second writer that read the issue before the first reopened it.
        let stale = issue.clone();

        assert_eq!(
            issue.apply_release(&pool, None).await.unwrap(),
            Some(super::Reopened {
                previous_status: "resolved".to_string(),
                cause: super::ReopenCause::NewOccurrence,
            })
        );
        assert_eq!(issue.status, super::IssueStatus::Active);
        assert_eq!(issue.name.as_deref(), Some("Updated issue"));
        assert_eq!(issue.severity.as_deref(), Some("high"));
        assert_eq!(
            stale.clone().apply_release(&pool, None).await.unwrap(),
            None
        );

        sqlx::query("UPDATE posthog_errortrackingissue SET status = 'suppressed' WHERE id = $1")
            .bind(issue.id)
            .execute(&pool)
            .await
            .unwrap();
        assert_eq!(
            stale.clone().apply_release(&pool, None).await.unwrap(),
            None
        );
        let status: String =
            sqlx::query_scalar("SELECT status FROM posthog_errortrackingissue WHERE id = $1")
                .bind(issue.id)
                .fetch_one(&pool)
                .await
                .unwrap();
        assert_eq!(status, "suppressed");
    }

    fn release_at(created_at: DateTime<Utc>) -> ReleaseInfo {
        ReleaseRecord {
            id: Uuid::now_v7(),
            team_id: 1,
            hash_id: "hash".to_string(),
            created_at,
            version: format!("1.0.{}", created_at.timestamp()),
            project: "my-app".to_string(),
            metadata: None,
        }
        .to_info()
    }

    type IssueRow = (String, Option<Uuid>, Option<DateTime<Utc>>, String);

    async fn issue_row(pool: &sqlx::PgPool, id: Uuid) -> IssueRow {
        sqlx::query_as(
            "SELECT status, latest_release_id, resolved_at, xmin::text || ':' || xmax::text FROM posthog_errortrackingissue WHERE id = $1",
        )
        .bind(id)
        .fetch_one(pool)
        .await
        .unwrap()
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn a_release_is_applied_against_the_locked_row(pool: sqlx::PgPool) {
        let base: DateTime<Utc> = "2026-03-01T12:00:00Z".parse().unwrap();
        let (r1, r2, r3) = (
            release_at(base),
            release_at(base + Duration::hours(1)),
            release_at(base + Duration::hours(2)),
        );
        let resolved_between_r2_and_r3 = base + Duration::minutes(90);
        let any = Some(ReopenCause::NewOccurrence);
        let by = |release: &ReleaseInfo| Some(ReopenCause::NewRelease(release.into()));
        let active = IssueStatus::Active;

        let cases = [
            (
                "active, first release",
                "active",
                None,
                None,
                Some(&r1),
                None,
                Some(&r1),
            ),
            (
                "active, newer release",
                "active",
                Some(&r1),
                None,
                Some(&r2),
                None,
                Some(&r2),
            ),
            (
                "active, older release",
                "active",
                Some(&r2),
                None,
                Some(&r1),
                None,
                Some(&r2),
            ),
            (
                "active, no release",
                "active",
                Some(&r1),
                None,
                None,
                None,
                Some(&r1),
            ),
            (
                "suppressed",
                "suppressed",
                None,
                None,
                Some(&r1),
                None,
                None,
            ),
            (
                "no release history",
                "resolved",
                None,
                None,
                Some(&r1),
                any.clone(),
                Some(&r1),
            ),
            (
                "no release",
                "resolved",
                Some(&r1),
                None,
                None,
                any.clone(),
                Some(&r1),
            ),
            (
                "older release",
                "resolved",
                Some(&r2),
                None,
                Some(&r1),
                None,
                Some(&r2),
            ),
            (
                "same release",
                "resolved",
                Some(&r1),
                None,
                Some(&r1),
                None,
                Some(&r1),
            ),
            (
                "newer, created before the resolve",
                "resolved",
                Some(&r1),
                None,
                Some(&r2),
                by(&r2),
                Some(&r2),
            ),
            (
                "archived",
                "archived",
                Some(&r2),
                None,
                Some(&r1),
                any.clone(),
                Some(&r2),
            ),
            (
                "pending release",
                "pending_release",
                None,
                None,
                None,
                any.clone(),
                None,
            ),
            (
                "resolved after load, newer",
                "resolved",
                Some(&r1),
                Some((active, Some(&r1))),
                Some(&r2),
                by(&r2),
                Some(&r2),
            ),
            (
                "resolved after load, older than stored",
                "resolved",
                Some(&r3),
                Some((active, Some(&r1))),
                Some(&r2),
                None,
                Some(&r3),
            ),
            (
                "resolved after load, same as stored",
                "resolved",
                Some(&r2),
                Some((active, Some(&r1))),
                Some(&r2),
                None,
                Some(&r2),
            ),
        ];

        for (case, status, latest, loaded_before_resolve, release, expected, expected_latest) in
            cases
        {
            let created = Issue::insert_new(
                1,
                "TypeError".to_string(),
                String::new(),
                None,
                latest,
                &pool,
            )
            .await
            .unwrap();
            let stored_resolved_at = (status == "resolved").then_some(resolved_between_r2_and_r3);
            sqlx::query(
                "UPDATE posthog_errortrackingissue SET status = $2, resolved_at = $3, resolved_until = $4 WHERE id = $1",
            )
            .bind(created.id)
            .bind(status)
            .bind(stored_resolved_at)
            .bind((status == "resolved").then_some(RESOLVED_UNTIL_NEW_RELEASE))
            .execute(&pool)
            .await
            .unwrap();
            let mut issue = Issue::load(&pool, 1, created.id).await.unwrap().unwrap();
            if let Some((loaded_status, loaded_latest)) = loaded_before_resolve {
                issue.status = loaded_status;
                issue.latest_release_id = loaded_latest.map(ReleaseInfo::id);
                issue.latest_release_created_at = loaded_latest.map(ReleaseInfo::created_at);
            }
            let before = issue_row(&pool, created.id).await;

            let reopened = issue.apply_release(&pool, release).await.unwrap();

            let after = issue_row(&pool, created.id).await;
            assert_eq!(
                reopened.as_ref().map(|r| r.cause.clone()),
                expected,
                "{case}"
            );
            if let Some(reopened) = &reopened {
                assert_eq!(reopened.previous_status, status, "{case}");
            }
            let expected_status = if expected.is_some() { "active" } else { status };
            let expected_resolved_at = stored_resolved_at.filter(|_| expected.is_none());
            let expected_latest = expected_latest.map(ReleaseInfo::id);
            assert_eq!(
                (after.0.as_str(), after.1, after.2),
                (expected_status, expected_latest, expected_resolved_at),
                "{case}"
            );
            let touched = loaded_before_resolve.is_some()
                || expected.is_some()
                || expected_latest != latest.map(ReleaseInfo::id);
            assert_eq!(after.3 != before.3, touched, "{case}: touched the row");
            assert_eq!(
                (issue.status.to_string(), issue.latest_release_id),
                (after.0, after.1),
                "{case}: the copy matches the row"
            );
        }
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn an_issue_resolved_until_the_next_occurrence_reopens_on_any_release(
        pool: sqlx::PgPool,
    ) {
        let base: DateTime<Utc> = "2026-03-01T12:00:00Z".parse().unwrap();
        let (older, latest) = (release_at(base), release_at(base + Duration::hours(1)));

        for resolved_until in [Some("next_occurrence"), None] {
            let created = Issue::insert_new(
                1,
                "TypeError".to_string(),
                String::new(),
                None,
                Some(&latest),
                &pool,
            )
            .await
            .unwrap();
            sqlx::query(
                "UPDATE posthog_errortrackingissue SET status = 'resolved', resolved_at = NOW(), resolved_until = $2 WHERE id = $1",
            )
            .bind(created.id)
            .bind(resolved_until)
            .execute(&pool)
            .await
            .unwrap();
            let mut issue = Issue::load(&pool, 1, created.id).await.unwrap().unwrap();

            assert_eq!(
                issue.release_check(Some(older.created_at())),
                ReleaseCheck::Reopen,
                "{resolved_until:?}"
            );
            let reopened = issue.apply_release(&pool, Some(&older)).await.unwrap();

            assert_eq!(
                reopened.map(|reopened| reopened.cause),
                Some(ReopenCause::NewOccurrence),
                "{resolved_until:?}"
            );
            let row: (String, Option<String>, Option<Uuid>) = sqlx::query_as(
                "SELECT status, resolved_until, latest_release_id FROM posthog_errortrackingissue WHERE id = $1",
            )
            .bind(created.id)
            .fetch_one(&pool)
            .await
            .unwrap();
            assert_eq!(
                row,
                ("active".to_string(), None, Some(latest.id())),
                "{resolved_until:?}"
            );
            assert_eq!(issue.resolved_until, None, "{resolved_until:?}");
        }
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn initial_severity_update_reaches_state_and_notification_payloads(pool: sqlx::PgPool) {
        let mut issue = super::Issue::insert_new(
            1,
            "TypeError".to_string(),
            "Example".to_string(),
            None,
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
            super::EventPropertiesLimits {
                ttl_seconds: 172_800,
                max_bytes: 1_048_576,
            },
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
            super::EventPropertiesLimits {
                ttl_seconds: 172_800,
                max_bytes: 128,
            },
            42,
            Uuid::parse_str("01982721-5e00-7000-8000-000000000001").unwrap(),
            "issue_created",
            &properties,
        )
        .await;

        assert!(redis.get_calls().is_empty());
    }
}
