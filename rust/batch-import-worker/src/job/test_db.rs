//! Real-Postgres fixtures for tests of how the worker shares the job row with operators. They fail
//! instead of skipping without a database, because CI builds `test_posthog` before the Rust tests.

use std::sync::Arc;

use chrono::{DateTime, Duration, Utc};
use envconfig::Envconfig;
use serde_json::Value;
use sqlx::{PgPool, Row};
use uuid::Uuid;

use crate::{config::Config, context::AppContext};

use super::model::{JobModel, JobState, JobStatus};

const DEFAULT_TEST_DATABASE_URL: &str = "postgres://posthog:posthog@localhost:5432/test_posthog";

pub async fn context() -> Arc<AppContext> {
    let mut config = Config::init_from_env().expect("worker config from env");
    config.database_url =
        std::env::var("DATABASE_URL").unwrap_or_else(|_| DEFAULT_TEST_DATABASE_URL.to_string());
    let context = AppContext::new(&config).await.unwrap_or_else(|e| {
        panic!(
            "these tests need the Django test database at {}: {e:?}",
            config.database_url
        )
    });
    Arc::new(context)
}

/// A job row as a worker sees it right after its claim.
pub struct JobRowFixture {
    pub status: JobStatus,
    pub lease_id: &'static str,
    pub state: JobState,
    pub sink: Value,
    pub pending_commit: Option<Value>,
}

pub async fn insert_job(pool: &PgPool, row: &JobRowFixture) -> Uuid {
    let id = Uuid::now_v7();
    let mut conn = pool.acquire().await.expect("connection");
    // Replica mode skips the foreign key check for this session, because the test database has no
    // team for the row and worker writes never change team_id.
    sqlx::query("SET session_replication_role = replica")
        .execute(&mut *conn)
        .await
        .expect("replica role needs a superuser, like the dev and CI postgres user");
    sqlx::query(
        r#"
        INSERT INTO posthog_batchimport
            (id, team_id, created_at, updated_at, status, import_config, secrets, state,
             lease_id, leased_until, backoff_attempt, pending_commit)
        VALUES ($1, 1, now(), now(), $2, $3, '', $4, $5, now() + interval '30 minutes', 0, $6)
        "#,
    )
    .bind(id)
    .bind(row.status.to_string())
    .bind(serde_json::json!({
        "source": {"type": "folder", "path": "/tmp"},
        "data_format": {"type": "json_lines", "skip_blanks": true, "content": {"type": "captured"}},
        "sink": row.sink,
    }))
    .bind(serde_json::to_value(&row.state).unwrap())
    .bind(row.lease_id)
    .bind(&row.pending_commit)
    .execute(&mut *conn)
    .await
    .expect("insert job row");
    sqlx::query("SET session_replication_role = DEFAULT")
        .execute(&mut *conn)
        .await
        .expect("reset replica role");
    id
}

/// What the tests assert about a job row.
#[derive(Debug)]
pub struct StoredJob {
    pub status: String,
    pub status_message: Option<String>,
    pub display_status_message: Option<String>,
    pub lease_id: Option<String>,
    pub leased_until: Option<DateTime<Utc>>,
    pub state: JobState,
    pub pending_commit: Option<Value>,
    pub backoff_until: Option<DateTime<Utc>>,
}

pub async fn read_job(pool: &PgPool, id: Uuid) -> StoredJob {
    let row = sqlx::query(
        r#"
        SELECT status, status_message, display_status_message, lease_id, leased_until, state,
               pending_commit, backoff_until
        FROM posthog_batchimport WHERE id = $1
        "#,
    )
    .bind(id)
    .fetch_one(pool)
    .await
    .expect("read job row");
    StoredJob {
        status: row.get("status"),
        status_message: row.get("status_message"),
        display_status_message: row.get("display_status_message"),
        lease_id: row.get("lease_id"),
        leased_until: row.get("leased_until"),
        state: serde_json::from_value(row.get("state")).expect("state json"),
        pending_commit: row.get("pending_commit"),
        backoff_until: row.get("backoff_until"),
    }
}

pub const OPERATOR_MESSAGE: &str = "set by an operator";

/// Change the row the way an operator does in Django admin or a customer does through the API.
pub async fn operator_sets(pool: &PgPool, id: Uuid, status: JobStatus) {
    sqlx::query("UPDATE posthog_batchimport SET status = $2, status_message = $3 WHERE id = $1")
        .bind(id)
        .bind(status.to_string())
        .bind(OPERATOR_MESSAGE)
        .execute(pool)
        .await
        .expect("operator status change");
}

/// Resume the job elsewhere: Django clears the lease, so this worker no longer owns the row.
pub async fn resume_elsewhere(pool: &PgPool, id: Uuid) {
    sqlx::query(
        "UPDATE posthog_batchimport SET lease_id = NULL, leased_until = NULL WHERE id = $1",
    )
    .bind(id)
    .execute(pool)
    .await
    .expect("clear lease");
}

pub async fn set_send_rate(pool: &PgPool, id: Uuid, send_rate: u64) {
    sqlx::query(
        "UPDATE posthog_batchimport SET import_config = jsonb_set(import_config, '{sink,send_rate}', to_jsonb($2::bigint)) WHERE id = $1",
    )
    .bind(id)
    .bind(send_rate as i64)
    .execute(pool)
    .await
    .expect("set send rate");
}

pub async fn delete_job(pool: &PgPool, id: Uuid) {
    sqlx::query("DELETE FROM posthog_batchimport WHERE id = $1")
        .bind(id)
        .execute(pool)
        .await
        .expect("delete job row");
}

/// The in-memory model a worker holds for `row` after claiming it.
pub fn claimed_model(id: Uuid, row: &JobRowFixture) -> JobModel {
    JobModel {
        id,
        team_id: 1,
        created_at: Utc::now(),
        updated_at: Utc::now(),
        lease_id: Some(row.lease_id.to_string()),
        leased_until: Some(Utc::now() + Duration::minutes(30)),
        status: JobStatus::Running,
        status_message: None,
        display_status_message: None,
        state: Some(row.state.clone()),
        import_config: serde_json::from_value(serde_json::json!({
            "source": {"type": "folder", "path": "/tmp"},
            "data_format": {"type": "json_lines", "skip_blanks": true, "content": {"type": "captured"}},
            "sink": row.sink,
        }))
        .expect("import config"),
        secrets: super::config::JobSecrets::empty(),
        backoff_attempt: 0,
        backoff_until: None,
        pending_commit: row
            .pending_commit
            .clone()
            .map(|v| serde_json::from_value(v).expect("pending commit")),
        was_leased: false,
        recovered_commit: None,
    }
}
