use std::fmt::{Display, Formatter};

use chrono::{DateTime, Utc};
use cymbal_rules::Assignment;
use serde::{Deserialize, Serialize};
use sqlx::encode::IsNull;
use sqlx::error::BoxDynError;
use sqlx::postgres::{PgArgumentBuffer, PgTypeInfo, PgValueRef};
use sqlx::{Decode, Encode, Postgres, Type};
use uuid::Uuid;

use crate::posthog::capture_issue_reopened;

const ISSUE_REOPENED: &str = "cymbal_issue_reopened";

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct IssueFingerprintOverride {
    pub id: Uuid,
    pub team_id: i32,
    pub issue_id: Uuid,
    pub fingerprint: String,
    pub version: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, sqlx::FromRow)]
pub struct Issue {
    pub id: Uuid,
    pub team_id: i32,
    pub status: IssueStatus,
    pub name: Option<String>,
    pub description: Option<String>,
    pub created_at: DateTime<Utc>,
}

#[derive(sqlx::FromRow)]
pub struct IssueWithFirstSeen {
    pub id: Uuid,
    pub team_id: i32,
    pub status: IssueStatus,
    pub name: Option<String>,
    pub description: Option<String>,
    pub created_at: DateTime<Utc>,
    pub fingerprint_first_seen: Option<DateTime<Utc>>,
}

#[derive(sqlx::FromRow)]
struct AssignmentRow {
    id: Uuid,
    issue_id: Uuid,
    user_id: Option<i32>,
    role_id: Option<Uuid>,
    created_at: DateTime<Utc>,
}

impl From<AssignmentRow> for Assignment {
    fn from(row: AssignmentRow) -> Self {
        Self {
            id: row.id,
            issue_id: row.issue_id,
            user_id: row.user_id,
            role_id: row.role_id,
            created_at: row.created_at,
        }
    }
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

fn issue_status_str(status: IssueStatus) -> &'static str {
    match status {
        IssueStatus::Archived => "archived",
        IssueStatus::Active => "active",
        IssueStatus::Resolved => "resolved",
        IssueStatus::PendingRelease => "pending_release",
        IssueStatus::Suppressed => "suppressed",
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IssueStatusParseError {
    status: String,
}

impl IssueStatusParseError {
    fn new(status: &str) -> Self {
        Self {
            status: status.to_string(),
        }
    }
}

impl Display for IssueStatusParseError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "invalid issue status: {}", self.status)
    }
}

impl std::error::Error for IssueStatusParseError {}

impl TryFrom<&str> for IssueStatus {
    type Error = IssueStatusParseError;

    fn try_from(status: &str) -> Result<Self, Self::Error> {
        match status {
            "archived" => Ok(IssueStatus::Archived),
            "active" => Ok(IssueStatus::Active),
            "resolved" => Ok(IssueStatus::Resolved),
            "pending_release" => Ok(IssueStatus::PendingRelease),
            "suppressed" => Ok(IssueStatus::Suppressed),
            status => Err(IssueStatusParseError::new(status)),
        }
    }
}

impl Type<Postgres> for IssueStatus {
    fn type_info() -> PgTypeInfo {
        <&str as Type<Postgres>>::type_info()
    }

    fn compatible(ty: &PgTypeInfo) -> bool {
        <&str as Type<Postgres>>::compatible(ty)
    }
}

impl<'r> Decode<'r, Postgres> for IssueStatus {
    fn decode(value: PgValueRef<'r>) -> Result<Self, BoxDynError> {
        let status = <&str as Decode<Postgres>>::decode(value)?;
        Ok(IssueStatus::try_from(status)?)
    }
}

impl Encode<'_, Postgres> for IssueStatus {
    fn encode_by_ref(&self, buf: &mut PgArgumentBuffer) -> Result<IsNull, BoxDynError> {
        <&str as Encode<Postgres>>::encode(issue_status_str(*self), buf)
    }
}

impl Issue {
    pub async fn load_by_fingerprint<'c, E>(
        executor: E,
        team_id: i32,
        fingerprint: &str,
    ) -> Result<Option<IssueWithFirstSeen>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query_as::<_, IssueWithFirstSeen>(
            r#"
            SELECT i.id, i.team_id, i.status, i.name, i.description, i.created_at, f.first_seen as fingerprint_first_seen
            FROM posthog_errortrackingissue i
            JOIN posthog_errortrackingissuefingerprintv2 f ON i.id = f.issue_id
            WHERE f.team_id = $1 AND f.fingerprint = $2
            "#,
        )
        .bind(team_id)
        .bind(fingerprint)
        .fetch_optional(executor)
        .await
    }

    pub async fn load<'c, E>(
        executor: E,
        team_id: i32,
        issue_id: Uuid,
    ) -> Result<Option<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query_as::<_, Issue>(
            r#"
            SELECT id, team_id, status, name, description, created_at FROM posthog_errortrackingissue
            WHERE team_id = $1 AND id = $2
            "#,
        )
        .bind(team_id)
        .bind(issue_id)
        .fetch_optional(executor)
        .await
    }

    pub async fn insert_new<'c, E>(
        team_id: i32,
        name: String,
        description: String,
        executor: E,
    ) -> Result<Issue, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        // Truncate the description to 255 characters, we've seen very large exception values.
        let description = description.chars().take(255).collect();
        let issue = Self {
            id: Uuid::now_v7(),
            team_id,
            status: IssueStatus::Active,
            name: Some(name),
            description: Some(description),
            created_at: Utc::now(),
        };

        sqlx::query(
            r#"
            INSERT INTO posthog_errortrackingissue (id, team_id, status, name, description, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            "#,
        )
        .bind(issue.id)
        .bind(issue.team_id)
        .bind(issue.status)
        .bind(&issue.name)
        .bind(&issue.description)
        .bind(issue.created_at)
        .execute(executor)
        .await?;

        Ok(issue)
    }

    pub async fn maybe_reopen<'c, E>(&mut self, executor: E) -> Result<bool, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        // If this issue is already active, or permanently suppressed, we don't need to do anything.
        if matches!(self.status, IssueStatus::Active | IssueStatus::Suppressed) {
            return Ok(false);
        }

        let res = sqlx::query_scalar::<_, Uuid>(
            r#"
            UPDATE posthog_errortrackingissue
            SET status = 'active'
            WHERE id = $1 AND status != 'active'
            RETURNING id
            "#,
        )
        .bind(self.id)
        .fetch_all(executor)
        .await?;

        let reopened = !res.is_empty();
        if reopened {
            // DB row is now active; keep in-memory state in sync so downstream Kafka payloads
            // (fingerprint_issue_state, internal events) are not stale.
            self.status = IssueStatus::Active;
            metrics::counter!(ISSUE_REOPENED).increment(1);
            capture_issue_reopened(self.team_id, self.id);
        }

        Ok(reopened)
    }

    pub async fn get_assignments<'c, E>(&self, executor: E) -> Result<Vec<Assignment>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        Ok(sqlx::query_as::<_, AssignmentRow>(
            r#"
            SELECT id, issue_id, user_id, role_id, created_at FROM posthog_errortrackingissueassignment
            WHERE issue_id = $1
            "#,
        )
        .bind(self.id)
        .fetch_all(executor)
        .await?
        .into_iter()
        .map(Into::into)
        .collect())
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
    let Some(assignment) = assignment else {
        return (None, None);
    };
    if let Some(user_id) = assignment.user_id {
        return (Some(i64::from(user_id)), None);
    }
    if let Some(role_id) = assignment.role_id {
        return (None, Some(role_id.to_string()));
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

impl IssueFingerprintOverride {
    pub async fn load<'c, E>(
        executor: E,
        team_id: i32,
        fingerprint: &str,
    ) -> Result<Option<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query_as::<_, IssueFingerprintOverride>(
            r#"
            SELECT id, team_id, issue_id, fingerprint, version FROM posthog_errortrackingissuefingerprintv2
            WHERE team_id = $1 AND fingerprint = $2
            "#,
        )
        .bind(team_id)
        .bind(fingerprint)
        .fetch_optional(executor)
        .await
    }

    pub async fn create_or_load<'c, E>(
        executor: E,
        team_id: i32,
        fingerprint: &str,
        issue: &Issue,
        first_seen: DateTime<Utc>,
    ) -> Result<Self, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        // We do an "ON CONFLICT DO NOTHING" here because callers can compare the returned issue id
        // to the passed Issue, to see if the issue was actually inserted or not.
        sqlx::query_as::<_, IssueFingerprintOverride>(
            r#"
            INSERT INTO posthog_errortrackingissuefingerprintv2 (id, team_id, issue_id, fingerprint, version, first_seen, created_at)
            VALUES ($1, $2, $3, $4, 0, $5, NOW())
            ON CONFLICT (team_id, fingerprint) DO UPDATE SET team_id = EXCLUDED.team_id -- a no-op update to force a returned row
            RETURNING id, team_id, issue_id, fingerprint, version
            "#,
        )
        .bind(Uuid::new_v4())
        .bind(team_id)
        .bind(issue.id)
        .bind(fingerprint)
        .bind(first_seen)
        .fetch_one(executor)
        .await
    }
}

impl Display for IssueStatus {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(issue_status_str(*self))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn issue_status_display_matches_database_values() {
        assert_eq!(IssueStatus::Archived.to_string(), "archived");
        assert_eq!(IssueStatus::Active.to_string(), "active");
        assert_eq!(IssueStatus::Resolved.to_string(), "resolved");
        assert_eq!(IssueStatus::PendingRelease.to_string(), "pending_release");
        assert_eq!(IssueStatus::Suppressed.to_string(), "suppressed");
    }

    #[test]
    fn issue_status_parser_rejects_unknown_database_values() {
        assert_eq!(IssueStatus::try_from("active"), Ok(IssueStatus::Active));
        assert_eq!(
            IssueStatus::try_from("snoozed").unwrap_err().to_string(),
            "invalid issue status: snoozed"
        );
    }

    #[test]
    fn fingerprint_issue_state_formats_clickhouse_payload() {
        let issue = Issue {
            id: Uuid::nil(),
            team_id: 42,
            status: IssueStatus::Resolved,
            name: Some("name".to_string()),
            description: Some("description".to_string()),
            created_at: Utc::now(),
        };
        let first_seen = DateTime::parse_from_rfc3339("2024-01-02T03:04:05.006Z")
            .unwrap()
            .with_timezone(&Utc);

        let state = FingerprintIssueState::new(&issue, "fingerprint", None, first_seen);

        assert_eq!(state.team_id, 42);
        assert_eq!(state.fingerprint, "fingerprint");
        assert_eq!(state.issue_status, "resolved");
        assert_eq!(state.first_seen, "2024-01-02 03:04:05.006");
        assert_eq!(state.is_deleted, 0);
    }

    #[test]
    fn fingerprint_issue_state_with_user_assignment_sets_assigned_user_id() {
        let issue = Issue {
            id: Uuid::nil(),
            team_id: 1,
            status: IssueStatus::Active,
            name: None,
            description: None,
            created_at: Utc::now(),
        };
        let first_seen = Utc::now();
        let assignment = Assignment {
            id: Uuid::new_v4(),
            issue_id: issue.id,
            user_id: Some(99),
            role_id: None,
            created_at: Utc::now(),
        };

        let state = FingerprintIssueState::new(&issue, "fp", Some(&assignment), first_seen);

        assert_eq!(state.assigned_user_id, Some(99));
        assert_eq!(state.assigned_role_id, None);
    }

    #[test]
    fn fingerprint_issue_state_with_role_assignment_sets_assigned_role_id() {
        let role_uuid = Uuid::new_v4();
        let issue = Issue {
            id: Uuid::nil(),
            team_id: 1,
            status: IssueStatus::Active,
            name: None,
            description: None,
            created_at: Utc::now(),
        };
        let first_seen = Utc::now();
        let assignment = Assignment {
            id: Uuid::new_v4(),
            issue_id: issue.id,
            user_id: None,
            role_id: Some(role_uuid),
            created_at: Utc::now(),
        };

        let state = FingerprintIssueState::new(&issue, "fp", Some(&assignment), first_seen);

        assert_eq!(state.assigned_user_id, None);
        assert_eq!(state.assigned_role_id, Some(role_uuid.to_string()));
    }

    #[sqlx::test(migrations = "../../tests/test_migrations")]
    async fn issue_insert_new_creates_active_issue(db: sqlx::PgPool) {
        let issue = Issue::insert_new(
            7,
            "NullPointerException".to_string(),
            "at com.example.Foo.bar".to_string(),
            &db,
        )
        .await
        .unwrap();

        assert_eq!(issue.team_id, 7);
        assert_eq!(issue.status, IssueStatus::Active);
        assert_eq!(issue.name.as_deref(), Some("NullPointerException"));
        assert_eq!(issue.description.as_deref(), Some("at com.example.Foo.bar"));
    }

    #[sqlx::test(migrations = "../../tests/test_migrations")]
    async fn issue_insert_new_truncates_long_description(db: sqlx::PgPool) {
        let long_description = "x".repeat(512);
        let issue = Issue::insert_new(7, "E".to_string(), long_description, &db)
            .await
            .unwrap();

        let stored = issue.description.unwrap();
        assert_eq!(
            stored.len(),
            255,
            "description must be truncated to 255 chars"
        );
        assert!(stored.chars().all(|c| c == 'x'));
    }

    #[sqlx::test(migrations = "../../tests/test_migrations")]
    async fn issue_load_by_fingerprint_returns_issue_with_first_seen(db: sqlx::PgPool) {
        let first_seen: DateTime<Utc> = DateTime::parse_from_rfc3339("2024-06-01T10:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let issue = Issue::insert_new(3, "TypeError".to_string(), "msg".to_string(), &db)
            .await
            .unwrap();

        IssueFingerprintOverride::create_or_load(&db, 3, "fp-abc", &issue, first_seen)
            .await
            .unwrap();

        let result = Issue::load_by_fingerprint(&db, 3, "fp-abc")
            .await
            .unwrap()
            .expect("should find issue by fingerprint");

        let (loaded, seen) = result.into_issue();
        assert_eq!(loaded.id, issue.id);
        assert_eq!(loaded.team_id, 3);
        let seen_ts = seen.expect("first_seen should be present");
        // Allow ±1 second for DB round-trip precision
        assert!((seen_ts - first_seen).num_seconds().abs() <= 1);
    }

    #[sqlx::test(migrations = "../../tests/test_migrations")]
    async fn issue_load_by_fingerprint_is_scoped_to_team(db: sqlx::PgPool) {
        let first_seen = Utc::now();
        let issue_team1 = Issue::insert_new(1, "Err".to_string(), "d".to_string(), &db)
            .await
            .unwrap();
        let issue_team2 = Issue::insert_new(2, "Err".to_string(), "d".to_string(), &db)
            .await
            .unwrap();

        IssueFingerprintOverride::create_or_load(&db, 1, "shared-fp", &issue_team1, first_seen)
            .await
            .unwrap();
        IssueFingerprintOverride::create_or_load(&db, 2, "shared-fp", &issue_team2, first_seen)
            .await
            .unwrap();

        let found1 = Issue::load_by_fingerprint(&db, 1, "shared-fp")
            .await
            .unwrap();
        let found2 = Issue::load_by_fingerprint(&db, 2, "shared-fp")
            .await
            .unwrap();
        let missing = Issue::load_by_fingerprint(&db, 99, "shared-fp")
            .await
            .unwrap();

        assert_eq!(found1.map(|r| r.into_issue().0.id), Some(issue_team1.id));
        assert_eq!(found2.map(|r| r.into_issue().0.id), Some(issue_team2.id));
        assert!(missing.is_none());
    }

    #[sqlx::test(migrations = "../../tests/test_migrations")]
    async fn fingerprint_create_or_load_returns_existing_on_conflict(db: sqlx::PgPool) {
        let first_seen = Utc::now();
        let original_issue = Issue::insert_new(5, "Err".to_string(), "d".to_string(), &db)
            .await
            .unwrap();
        let competing_issue = Issue::insert_new(5, "Err".to_string(), "d".to_string(), &db)
            .await
            .unwrap();

        // First insert wins.
        let first = IssueFingerprintOverride::create_or_load(
            &db,
            5,
            "race-fp",
            &original_issue,
            first_seen,
        )
        .await
        .unwrap();

        // Second call with a different issue simulates the losing side of a race.
        let second = IssueFingerprintOverride::create_or_load(
            &db,
            5,
            "race-fp",
            &competing_issue,
            first_seen,
        )
        .await
        .unwrap();

        assert_eq!(
            first.issue_id, original_issue.id,
            "first insert should keep original issue"
        );
        assert_eq!(
            second.issue_id, original_issue.id,
            "conflicting insert should return original issue, not competing one"
        );
        assert_ne!(competing_issue.id, original_issue.id);
    }

    #[sqlx::test(migrations = "../../tests/test_migrations")]
    async fn maybe_reopen_transitions_resolved_to_active(db: sqlx::PgPool) {
        let mut issue = Issue::insert_new(1, "Err".to_string(), "d".to_string(), &db)
            .await
            .unwrap();

        // Manually set status to resolved in DB.
        sqlx::query("UPDATE posthog_errortrackingissue SET status='resolved' WHERE id=$1")
            .bind(issue.id)
            .execute(&db)
            .await
            .unwrap();
        issue.status = IssueStatus::Resolved;

        let reopened = issue.maybe_reopen(&db).await.unwrap();

        assert!(reopened, "resolved issue should transition to active");
        assert_eq!(
            issue.status,
            IssueStatus::Active,
            "in-memory status must be updated"
        );

        let reloaded = Issue::load(&db, 1, issue.id).await.unwrap().unwrap();
        assert_eq!(
            reloaded.status,
            IssueStatus::Active,
            "DB status must be active"
        );
    }

    #[sqlx::test(migrations = "../../tests/test_migrations")]
    async fn maybe_reopen_keeps_active_issue_unchanged(db: sqlx::PgPool) {
        let mut issue = Issue::insert_new(1, "Err".to_string(), "d".to_string(), &db)
            .await
            .unwrap();
        // issue starts as Active
        let reopened = issue.maybe_reopen(&db).await.unwrap();

        assert!(!reopened, "active issue must not be 'reopened'");
        assert_eq!(issue.status, IssueStatus::Active);
    }

    #[sqlx::test(migrations = "../../tests/test_migrations")]
    async fn maybe_reopen_keeps_suppressed_issue_unchanged(db: sqlx::PgPool) {
        let mut issue = Issue::insert_new(1, "Err".to_string(), "d".to_string(), &db)
            .await
            .unwrap();

        sqlx::query("UPDATE posthog_errortrackingissue SET status='suppressed' WHERE id=$1")
            .bind(issue.id)
            .execute(&db)
            .await
            .unwrap();
        issue.status = IssueStatus::Suppressed;

        let reopened = issue.maybe_reopen(&db).await.unwrap();

        assert!(!reopened, "suppressed issue must not reopen");
        assert_eq!(
            issue.status,
            IssueStatus::Suppressed,
            "suppressed status must be preserved"
        );
    }

    #[sqlx::test(migrations = "../../tests/test_migrations")]
    async fn maybe_reopen_transitions_pending_release_to_active(db: sqlx::PgPool) {
        let mut issue = Issue::insert_new(1, "Err".to_string(), "d".to_string(), &db)
            .await
            .unwrap();

        sqlx::query("UPDATE posthog_errortrackingissue SET status='pending_release' WHERE id=$1")
            .bind(issue.id)
            .execute(&db)
            .await
            .unwrap();
        issue.status = IssueStatus::PendingRelease;

        let reopened = issue.maybe_reopen(&db).await.unwrap();

        assert!(reopened);
        assert_eq!(issue.status, IssueStatus::Active);
    }

    #[sqlx::test(migrations = "../../tests/test_migrations")]
    async fn issue_get_assignments_returns_user_assignment(db: sqlx::PgPool) {
        let issue = Issue::insert_new(1, "Err".to_string(), "d".to_string(), &db)
            .await
            .unwrap();

        sqlx::query(
            "INSERT INTO posthog_errortrackingissueassignment \
             (id, issue_id, user_id, role_id, created_at) \
             VALUES ($1, $2, $3, NULL, NOW())",
        )
        .bind(Uuid::new_v4())
        .bind(issue.id)
        .bind(42i32)
        .execute(&db)
        .await
        .unwrap();

        let assignments = issue.get_assignments(&db).await.unwrap();
        assert_eq!(assignments.len(), 1);
        assert_eq!(assignments[0].user_id, Some(42));
        assert_eq!(assignments[0].role_id, None);
        assert_eq!(assignments[0].issue_id, issue.id);
    }

    #[sqlx::test(migrations = "../../tests/test_migrations")]
    async fn issue_get_assignments_returns_role_assignment(db: sqlx::PgPool) {
        let role_id = Uuid::new_v4();
        let issue = Issue::insert_new(1, "Err".to_string(), "d".to_string(), &db)
            .await
            .unwrap();

        sqlx::query(
            "INSERT INTO posthog_errortrackingissueassignment \
             (id, issue_id, user_id, role_id, created_at) \
             VALUES ($1, $2, NULL, $3, NOW())",
        )
        .bind(Uuid::new_v4())
        .bind(issue.id)
        .bind(role_id)
        .execute(&db)
        .await
        .unwrap();

        let assignments = issue.get_assignments(&db).await.unwrap();
        assert_eq!(assignments.len(), 1);
        assert_eq!(assignments[0].user_id, None);
        assert_eq!(assignments[0].role_id, Some(role_id));
    }
}
