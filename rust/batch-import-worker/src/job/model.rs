use std::{fmt::Display, sync::Arc, time::Duration as StdDuration};

use crate::metrics;
use anyhow::{Context, Error};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::{postgres::PgQueryResult, PgPool, Row};
use tracing::{info, warn};
use uuid::Uuid;

use crate::context::AppContext;

use super::config::{JobConfig, JobSecrets};

#[derive(Debug, Clone)]
pub struct JobModel {
    pub id: Uuid,
    pub team_id: i32,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,

    pub lease_id: Option<String>,
    pub leased_until: Option<DateTime<Utc>>,

    pub status: JobStatus,
    // Exposed to a developer, not the user
    pub status_message: Option<String>,
    // Exposed to the user
    pub display_status_message: Option<String>,

    pub state: Option<JobState>,
    pub import_config: JobConfig,
    pub secrets: JobSecrets,

    pub backoff_attempt: i32,
    pub backoff_until: Option<DateTime<Utc>>,

    // Not actually in the model, but we calculate it on fetch to let us reason about whether
    // we're resuming an interrupted job
    pub was_leased: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum JobStatus {
    Running,
    Paused,
    Failed,
    Completed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub struct JobState {
    // Parts are sorted, and we iterate through them in order, to let us import
    // from oldest to newest
    pub parts: Vec<PartState>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub struct PartState {
    pub key: String,
    pub current_offset: u64,
    pub total_size: Option<u64>,
}

impl PartState {
    pub fn is_done(&self) -> bool {
        match self.total_size {
            Some(size) => self.current_offset == size,
            None => false,
        }
    }
}

impl JobModel {
    pub async fn claim_next_job(context: Arc<AppContext>) -> Result<Option<JobModel>, Error> {
        // We use select for update to lock a row, then update it, returning the updated row
        let new_lease_id = Uuid::now_v7().to_string();
        let row = sqlx::query_as!(
            JobRow,
            r#"
            WITH next_job AS (
                SELECT *, lease_id as previous_lease_id
                FROM posthog_batchimport
                WHERE status = 'running' AND (leased_until IS NULL OR leased_until <= now())
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE posthog_batchimport
            SET
                status = 'running',
                leased_until = now() + interval '30 minutes', -- We lease for a long time because job init can be quite slow
                lease_id = $1
            FROM next_job
            WHERE posthog_batchimport.id = next_job.id
            RETURNING
                posthog_batchimport.id,
                posthog_batchimport.team_id,
                posthog_batchimport.created_at,
                posthog_batchimport.updated_at,
                posthog_batchimport.status_message,
                posthog_batchimport.display_status_message,
                posthog_batchimport.state,
                posthog_batchimport.import_config,
                posthog_batchimport.secrets,
                posthog_batchimport.backoff_attempt,
                posthog_batchimport.backoff_until,
                next_job.previous_lease_id
            "#,
            new_lease_id
        )
        .fetch_optional(&context.db)
        .await?;

        let Some(row) = row else {
            return Ok(None);
        };

        let id = row.id;

        let parsed: anyhow::Result<JobModel> =
            (row, context.encryption_keys.as_slice(), new_lease_id)
                .try_into()
                .context("Failed to parse job row");

        match parsed {
            Ok(model) => Ok(Some(model)),
            Err(e) => {
                // If we failed to parse a job, we pause it and leave it for manual intervention
                sqlx::query!(
                    r#"
                    UPDATE posthog_batchimport
                    SET
                        lease_id = null,
                        leased_until = null,
                        status = 'paused',
                        status_message = $2,
                        display_status_message = $3
                    WHERE id = $1
                    "#,
                    id,
                    format!("{:?}", e), // We like context
                    "Failed to parse source event data into Posthog event data"
                )
                .execute(&context.db)
                .await?;

                warn!("Failed to parse job {}: {:?}", id, e);

                // We return None here because "failure to parse the job" shouldn't cause the
                // worker to crash (unlike e.g. failures to talk to PG in this function, which
                // should)
                Ok(None)
            }
        }
    }

    /// Schedule the job for a future retry by pushing leased_until forward and updating messages.
    /// Keeps status as 'running' so the main loop can pick it up when the lease expires.
    pub async fn schedule_backoff(
        &mut self,
        pool: &PgPool,
        delay: StdDuration,
        status_message: String,
        display_message: Option<String>,
        next_attempt: i32,
    ) -> Result<(), Error> {
        let Some(current_lease) = self.lease_id.as_ref() else {
            anyhow::bail!("Cannot schedule backoff on a job with no lease")
        };

        // Use DB clock for timestamps; pass delay in whole seconds
        let delay_secs: i64 = std::cmp::min(delay.as_secs(), i64::MAX as u64) as i64;

        let rec = sqlx::query(
            r#"
            UPDATE posthog_batchimport
            SET
                status = 'running',
                status_message = $3,
                display_status_message = $4,
                updated_at = now(),
                leased_until = now() + make_interval(secs => $2),
                backoff_attempt = $5,
                backoff_until = leased_until
            WHERE id = $1 AND lease_id = $6
            RETURNING leased_until, backoff_until, updated_at
            "#,
        )
        .bind(self.id)
        .bind(delay_secs)
        .bind(&status_message)
        .bind(&display_message)
        .bind(next_attempt)
        .bind(current_lease)
        .fetch_one(pool)
        .await?;

        let until: DateTime<Utc> = rec.try_get("leased_until")?;
        let returned_backoff_until: DateTime<Utc> = rec.try_get("backoff_until")?;
        let returned_updated_at: DateTime<Utc> = rec.try_get("updated_at")?;

        self.status = JobStatus::Running;
        self.status_message = Some(status_message);
        self.display_status_message = display_message;
        self.leased_until = Some(until);
        self.backoff_attempt = next_attempt;
        self.backoff_until = Some(returned_backoff_until);
        self.updated_at = returned_updated_at;

        info!(
            job_id = %self.id,
            next_attempt = next_attempt,
            delay_secs = delay.as_secs(),
            until = %until,
            "scheduled backoff for job"
        );
        metrics::backoff_event(delay.as_secs_f64());

        Ok(())
    }

    pub async fn flush(&mut self, pool: &PgPool, extend_lease: bool) -> Result<(), Error> {
        let Some(old_lease) = self.lease_id.take() else {
            anyhow::bail!("Cannot flush a job with no lease")
        };

        if extend_lease {
            self.lease_id = Some(Uuid::now_v7().to_string());
        }

        if extend_lease {
            // We only allow the lease to be set to 5 minutes from now, except in the initial claim
            // case, where we allow it to be set to 30 minutes from now, because job init can be slow
            self.leased_until = Some(Utc::now() + chrono::Duration::minutes(5));
        } else {
            self.leased_until = None;
        };

        let res = sqlx::query!(
            r#"
            UPDATE posthog_batchimport
            SET
                status = $2,
                status_message = $3,
                display_status_message = $4,
                state = $5,
                updated_at = now(),
                lease_id = $6,
                leased_until = $7
            WHERE id = $1 AND lease_id = $8
            "#,
            self.id,
            self.status.to_string(),
            self.status_message,
            self.display_status_message,
            serde_json::to_value(&self.state)?,
            self.lease_id,
            self.leased_until,
            old_lease
        )
        .execute(pool)
        .await?;

        throw_if_no_rows(res)?;

        Ok(())
    }

    pub async fn pause(
        &mut self,
        context: Arc<AppContext>,
        reason: String,
        display_reason: Option<String>,
    ) -> Result<(), Error> {
        self.status = JobStatus::Paused;
        self.status_message = Some(reason);
        self.display_status_message = display_reason;
        self.flush(&context.db, true).await
    }

    pub async fn unpause(&mut self, context: Arc<AppContext>) -> Result<(), Error> {
        self.status = JobStatus::Running;
        self.status_message = None;
        self.display_status_message = None;
        self.backoff_attempt = 0;
        self.backoff_until = None;

        self.flush(&context.db, true).await?;
        let rec = sqlx::query(
            r#"
            UPDATE posthog_batchimport
            SET backoff_attempt = 0, backoff_until = NULL
            WHERE id = $1
            RETURNING updated_at
            "#,
        )
        .bind(self.id)
        .fetch_one(&context.db)
        .await?;

        self.updated_at = rec.try_get("updated_at")?;

        info!(job_id = %self.id, "unpaused job and reset backoff state");
        metrics::unpause_event();

        Ok(())
    }

    /// Reset backoff columns in the database after a successful request and update in-memory fields.
    pub async fn reset_backoff_in_db(&mut self, pool: &PgPool) -> Result<(), Error> {
        sqlx::query(
            r#"
            UPDATE posthog_batchimport
            SET backoff_attempt = 0, backoff_until = NULL
            WHERE id = $1
            "#,
        )
        .bind(self.id)
        .execute(pool)
        .await?;

        self.backoff_attempt = 0;
        self.backoff_until = None;
        Ok(())
    }

    pub async fn fail(
        &mut self,
        pool: &PgPool,
        reason: String,
        display_reason: String,
    ) -> Result<(), Error> {
        self.status = JobStatus::Failed;
        self.status_message = Some(reason);
        self.display_status_message = Some(display_reason);
        self.flush(pool, false).await
    }

    pub async fn complete(&mut self, pool: &PgPool) -> Result<(), Error> {
        self.status = JobStatus::Completed;
        self.display_status_message = None;
        self.flush(pool, false).await
    }
}

impl Display for JobStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            JobStatus::Running => write!(f, "running"),
            JobStatus::Paused => write!(f, "paused"),
            JobStatus::Failed => write!(f, "failed"),
            JobStatus::Completed => write!(f, "completed"),
        }
    }
}

struct JobRow {
    id: Uuid,
    team_id: i32,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
    status_message: Option<String>,
    display_status_message: Option<String>,
    state: Option<serde_json::Value>,
    import_config: serde_json::Value,
    secrets: String,
    backoff_attempt: Option<i32>,
    backoff_until: Option<DateTime<Utc>>,
    previous_lease_id: Option<String>,
}

impl TryFrom<(JobRow, &[String], String)> for JobModel {
    type Error = Error;

    fn try_from(input: (JobRow, &[String], String)) -> Result<Self, Self::Error> {
        let (row, keys, lease_id) = input;
        let state = match row.state {
            Some(s) => serde_json::from_value(s).context("Parsing state")?,
            None => JobState { parts: vec![] },
        };

        let import_config = serde_json::from_value(row.import_config).context("Parsing config")?;

        let secrets = JobSecrets::decrypt(&row.secrets, keys).context("Parsing keys")?;

        Ok(JobModel {
            id: row.id,
            team_id: row.team_id,
            created_at: row.created_at,
            updated_at: row.updated_at,
            lease_id: Some(lease_id),
            leased_until: None,
            status: JobStatus::Running,
            status_message: row.status_message,
            display_status_message: row.display_status_message,
            state: Some(state),
            import_config,
            secrets,
            backoff_attempt: row.backoff_attempt.unwrap_or(0),
            backoff_until: row.backoff_until,
            was_leased: row.previous_lease_id.is_some(),
        })
    }
}

// Returns an InvalidLock error if the query run did not affect any rows.
pub fn throw_if_no_rows(res: PgQueryResult) -> Result<(), Error> {
    if res.rows_affected() == 0 {
        anyhow::bail!("No update done")
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use envconfig::Envconfig;
    use sqlx::Row;

    async fn get_pool() -> Option<PgPool> {
        let url = std::env::var("DATABASE_URL").ok()?;
        PgPool::connect(&url).await.ok()
    }

    fn make_dummy_job_model(id: Uuid, lease: &str, team_id: i32) -> JobModel {
        JobModel {
            id,
            team_id,
            created_at: Utc::now(),
            updated_at: Utc::now(),
            lease_id: Some(lease.to_string()),
            leased_until: None,
            status: JobStatus::Running,
            status_message: None,
            display_status_message: None,
            state: None,
            import_config: crate::job::config::JobConfig {
                source: crate::job::config::SourceConfig::Folder(
                    crate::job::config::FolderSourceConfig {
                        path: "/tmp".to_string(),
                    },
                ),
                data_format: crate::parse::format::FormatConfig::JsonLines {
                    skip_blanks: true,
                    content: crate::parse::content::ContentType::Captured,
                },
                sink: crate::job::config::SinkConfig::NoOp,
                import_events: true,
                generate_identify_events: false,
                generate_group_identify_events: false,
            },
            secrets: crate::job::config::JobSecrets {
                secrets: std::collections::HashMap::new(),
            },
            backoff_attempt: 0,
            backoff_until: None,
            was_leased: false,
        }
    }

    #[tokio::test]
    async fn test_schedule_backoff_persists_db() -> Result<(), anyhow::Error> {
        let Some(pool) = get_pool().await else {
            return Ok(());
        };

        // Start a transaction to avoid side effects
        let mut tx = pool.begin().await?;

        // Insert a minimal batch import row
        let id = Uuid::now_v7();
        let team_id = 1;
        let lease = "test-lease";
        // Best-effort: if FK constraints fail in local env, skip test
        let inserted = sqlx::query(
            r#"
            INSERT INTO posthog_batchimport (id, team_id, status, import_config, secrets, lease_id, backoff_attempt)
            VALUES ($1, $2, 'running', '{}'::jsonb, '', $3, 0)
            "#,
        )
        .bind(id)
        .bind(team_id)
        .bind(lease)
        .execute(&mut *tx)
        .await;
        if inserted.is_err() {
            return Ok(());
        }

        let mut model = make_dummy_job_model(id, lease, team_id);
        let delay = StdDuration::from_secs(60);
        model
            .schedule_backoff(
                &pool,
                delay,
                "rate limited".to_string(),
                Some("retrying".to_string()),
                3,
            )
            .await?;

        let rec = sqlx::query(
            r#"SELECT leased_until, backoff_attempt, backoff_until, status_message, display_status_message
               FROM posthog_batchimport WHERE id = $1"#,
        )
        .bind(id)
        .fetch_one(&mut *tx)
        .await?;

        let leased_until: Option<DateTime<Utc>> = rec.try_get("leased_until")?;
        let backoff_attempt: Option<i32> = rec.try_get("backoff_attempt")?;
        let backoff_until: Option<DateTime<Utc>> = rec.try_get("backoff_until")?;
        let status_message: Option<String> = rec.try_get("status_message")?;
        let display_status_message: Option<String> = rec.try_get("display_status_message")?;

        assert_eq!(backoff_attempt.unwrap_or_default(), 3);
        assert!(leased_until.is_some());
        assert_eq!(backoff_until, leased_until);
        assert_eq!(status_message.as_deref(), Some("rate limited"));
        assert_eq!(display_status_message.as_deref(), Some("retrying"));

        tx.rollback().await?;
        Ok(())
    }

    #[tokio::test]
    async fn test_unpause_resets_backoff_db() -> Result<(), anyhow::Error> {
        let Some(pool) = get_pool().await else {
            return Ok(());
        };
        let cfg = crate::config::Config::init_from_env().unwrap();
        let context = Arc::new(crate::context::AppContext::new(&cfg).await?);

        let mut tx = pool.begin().await?;

        let id = Uuid::now_v7();
        let team_id = 1;
        let lease = "test-lease";
        let inserted = sqlx::query(
            r#"
            INSERT INTO posthog_batchimport (id, team_id, status, import_config, secrets, lease_id, backoff_attempt, backoff_until)
            VALUES ($1, $2, 'running', '{}'::jsonb, '', $3, 5, now())
            "#,
        )
        .bind(id)
        .bind(team_id)
        .bind(lease)
        .execute(&mut *tx)
        .await;
        if inserted.is_err() {
            return Ok(());
        }

        let mut model = make_dummy_job_model(id, lease, team_id);
        model.backoff_attempt = 5;
        model.backoff_until = Some(Utc::now());

        model.unpause(context.clone()).await?;

        let rec = sqlx::query(
            r#"SELECT backoff_attempt, backoff_until FROM posthog_batchimport WHERE id = $1"#,
        )
        .bind(id)
        .fetch_one(&mut *tx)
        .await?;

        let backoff_attempt: Option<i32> = rec.try_get("backoff_attempt")?;
        let backoff_until: Option<DateTime<Utc>> = rec.try_get("backoff_until")?;
        assert_eq!(backoff_attempt.unwrap_or_default(), 0);
        assert!(backoff_until.is_none());

        tx.rollback().await?;
        Ok(())
    }

    #[tokio::test]
    async fn test_reset_backoff_in_db_resets_columns() -> Result<(), anyhow::Error> {
        let Some(pool) = get_pool().await else {
            return Ok(());
        };

        let mut tx = pool.begin().await?;

        let id = Uuid::now_v7();
        let team_id = 1;
        let lease = "test-lease";
        let inserted = sqlx::query(
            r#"
            INSERT INTO posthog_batchimport (id, team_id, status, import_config, secrets, lease_id, backoff_attempt, backoff_until)
            VALUES ($1, $2, 'running', '{}'::jsonb, '', $3, 5, now())
            "#,
        )
        .bind(id)
        .bind(team_id)
        .bind(lease)
        .execute(&mut *tx)
        .await;
        if inserted.is_err() {
            return Ok(());
        }

        let mut model = make_dummy_job_model(id, lease, team_id);
        model.backoff_attempt = 5;
        model.backoff_until = Some(Utc::now());

        model.reset_backoff_in_db(&pool).await?;

        let rec = sqlx::query(
            r#"SELECT backoff_attempt, backoff_until FROM posthog_batchimport WHERE id = $1"#,
        )
        .bind(id)
        .fetch_one(&mut *tx)
        .await?;

        let backoff_attempt: Option<i32> = rec.try_get("backoff_attempt")?;
        let backoff_until: Option<DateTime<Utc>> = rec.try_get("backoff_until")?;
        assert_eq!(backoff_attempt.unwrap_or_default(), 0);
        assert!(backoff_until.is_none());

        tx.rollback().await?;
        Ok(())
    }
}
