//! Django owns this table: `data` per kind is pinned by
//! `products/error_tracking/backend/tests/fixtures/issue_change_data.json`, and `snapshot` mirrors
//! `IssueSnapshot.to_json` in `products/error_tracking/backend/logic/issue_changes.py`.

use std::collections::HashMap;

use chrono::{DateTime, SecondsFormat, Utc};
use serde::Serialize;
use serde_json::{json, Value};
use sqlx::types::Json;
use uuid::Uuid;

use crate::{
    error::UnhandledError, issue_resolution::Issue,
    modes::processing::rules::assignment::Assignment,
};

const MAX_SNAPSHOT_NAME_CHARS: usize = 500;

#[derive(Debug, Clone, PartialEq)]
pub enum IssueChange {
    Created,
    StatusChanged {
        previous: String,
    },
    Spiking {
        computed_baseline: f64,
        current_bucket_value: i64,
    },
}

impl IssueChange {
    pub fn kind(&self) -> &'static str {
        match self {
            IssueChange::Created => "created",
            IssueChange::StatusChanged { .. } => "status_changed",
            IssueChange::Spiking { .. } => "spiking",
        }
    }

    pub fn data(&self) -> Value {
        match self {
            IssueChange::Created => json!({}),
            IssueChange::StatusChanged { previous } => json!({ "previous": previous }),
            IssueChange::Spiking {
                computed_baseline,
                current_bucket_value,
            } => json!({
                "computed_baseline": computed_baseline,
                "current_bucket_value": current_bucket_value,
            }),
        }
    }
}

#[derive(Debug, Serialize, PartialEq)]
#[serde(tag = "type", content = "id", rename_all = "lowercase")]
enum SnapshotAssignee {
    User(String),
    Role(String),
}

#[derive(Debug, Serialize)]
pub struct IssueSnapshot {
    status: String,
    severity: Option<String>,
    name: Option<String>,
    assignee: Option<SnapshotAssignee>,
    first_seen: String,
}

impl IssueSnapshot {
    pub async fn load(
        connection: &mut sqlx::PgConnection,
        issue: &Issue,
        assignment: Option<&Assignment>,
    ) -> Result<Self, UnhandledError> {
        let first_seen: Option<DateTime<Utc>> = sqlx::query_scalar(
            "SELECT MIN(first_seen) FROM posthog_errortrackingissuefingerprintv2 WHERE team_id = $1 AND issue_id = $2",
        )
        .bind(issue.team_id)
        .bind(issue.id)
        .fetch_one(connection)
        .await?;
        Ok(Self::of(
            issue,
            assignment,
            first_seen.unwrap_or(issue.created_at),
        ))
    }

    pub fn of(issue: &Issue, assignment: Option<&Assignment>, first_seen: DateTime<Utc>) -> Self {
        let assignee =
            assignment.and_then(
                |assignment| match (assignment.user_id, assignment.role_id) {
                    (Some(user_id), _) => Some(SnapshotAssignee::User(user_id.to_string())),
                    (None, Some(role_id)) => Some(SnapshotAssignee::Role(role_id.to_string())),
                    (None, None) => None,
                },
            );
        Self {
            status: issue.status.to_string(),
            severity: issue.severity.clone(),
            name: issue
                .name
                .as_ref()
                .map(|name| name.chars().take(MAX_SNAPSHOT_NAME_CHARS).collect()),
            assignee,
            first_seen: first_seen.to_rfc3339_opts(SecondsFormat::AutoSi, false),
        }
    }
}

pub struct ExceptionRef {
    pub uuid: Uuid,
    pub timestamp: DateTime<Utc>,
}

/// The alert evaluation reads rows by `created_at` with a settle margin, so a row must commit soon
/// after its insert. Postgres aborts a transaction left idle longer than this, so a row commits
/// within this much of its insert or never.
pub async fn cap_idle_time<'c, E>(executor: E) -> Result<(), UnhandledError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    sqlx::query("SET LOCAL idle_in_transaction_session_timeout = '10s'")
        .execute(executor)
        .await?;
    Ok(())
}

pub async fn record_issue_change<'c, E>(
    executor: E,
    issue: &Issue,
    change: &IssueChange,
    snapshot: &IssueSnapshot,
    exception: &ExceptionRef,
) -> Result<(), UnhandledError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    record_issue_change_with_id(executor, Uuid::now_v7(), issue, change, snapshot, exception).await
}

pub async fn record_issue_change_with_id<'c, E>(
    executor: E,
    id: Uuid,
    issue: &Issue,
    change: &IssueChange,
    snapshot: &IssueSnapshot,
    exception: &ExceptionRef,
) -> Result<(), UnhandledError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    sqlx::query(
        r#"
        INSERT INTO posthog_errortrackingissuechange
            (id, team_id, issue_id, kind, data, snapshot, operation_id, actor_type, event_uuid, event_timestamp)
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'ingestion', $8, $9)
        ON CONFLICT (id) DO NOTHING
        "#,
    )
    .bind(id)
    .bind(issue.team_id)
    .bind(issue.id)
    .bind(change.kind())
    .bind(Json(change.data()))
    .bind(Json(snapshot))
    // One event makes one change, so each row is its own operation.
    .bind(Uuid::now_v7())
    .bind(exception.uuid)
    .bind(exception.timestamp)
    .execute(executor)
    .await?;
    Ok(())
}

pub async fn load_assignments<'c, E>(
    executor: E,
    issue_ids: &[Uuid],
) -> Result<HashMap<Uuid, Assignment>, UnhandledError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let rows: Vec<Assignment> = sqlx::query_as(
        r#"
        SELECT id, issue_id, user_id, role_id, created_at
        FROM posthog_errortrackingissueassignment
        WHERE issue_id = ANY($1)
        "#,
    )
    .bind(issue_ids)
    .fetch_all(executor)
    .await?;
    Ok(rows.into_iter().map(|row| (row.issue_id, row)).collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::issue_resolution::IssueStatus;

    const CHANGE_DATA_FIXTURES: &str = include_str!(
        "../../../../../products/error_tracking/backend/tests/fixtures/issue_change_data.json"
    );

    #[test]
    fn change_data_matches_the_shared_fixtures() {
        let fixtures: Vec<Value> = serde_json::from_str(CHANGE_DATA_FIXTURES).unwrap();
        for change in [
            IssueChange::Created,
            IssueChange::StatusChanged {
                previous: "resolved".to_string(),
            },
            IssueChange::Spiking {
                computed_baseline: 12.5,
                current_bucket_value: 140,
            },
        ] {
            let written = json!({ "kind": change.kind(), "data": change.data() });
            assert!(
                fixtures.contains(&written),
                "{written} is not in the shared fixtures"
            );
        }
    }

    #[test]
    fn snapshot_matches_the_django_shape() {
        let issue = Issue {
            id: Uuid::now_v7(),
            team_id: 1,
            status: IssueStatus::Active,
            severity: Some("high".to_string()),
            name: Some("TypeError".to_string()),
            description: None,
            created_at: Utc::now(),
        };
        let assignment = Assignment {
            id: Uuid::now_v7(),
            issue_id: issue.id,
            user_id: Some(42),
            role_id: None,
            created_at: Utc::now(),
        };
        let first_seen = DateTime::parse_from_rfc3339("2026-11-01T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc);

        let snapshot =
            serde_json::to_value(IssueSnapshot::of(&issue, Some(&assignment), first_seen)).unwrap();

        assert_eq!(
            snapshot,
            json!({
                "status": "active",
                "severity": "high",
                "name": "TypeError",
                "assignee": {"type": "user", "id": "42"},
                "first_seen": "2026-11-01T00:00:00+00:00",
            })
        );
    }
}
