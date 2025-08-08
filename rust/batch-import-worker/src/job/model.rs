use std::{fmt::Display, sync::Arc, time::Duration as StdDuration};

use anyhow::{Context, Error};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::{postgres::PgQueryResult, PgPool, Row};
use tracing::warn;
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

    // Backoff (DB columns to be added via migration):
    // - backoff_attempt INTEGER NOT NULL DEFAULT 0
    // - backoff_until TIMESTAMPTZ NULL
    // For now these are populated with defaults and will be wired once columns exist
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
    #[serde(default)]
    pub backoff_attempt: u32,
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

        let parsed: anyhow::Result<JobModel> = (row, context.encryption_keys.as_slice(), new_lease_id)
            .try_into()
            .context("Failed to parse job row");

        match parsed {
            Ok(mut model) => {
                // Optionally load DB backoff columns if enabled (requires migration)
                if context.config.backoff_db_columns_enabled {
                    // Best-effort: if columns not present yet in test/dev, ignore errors
                    if let Ok(rec) = sqlx::query(
                        r#"SELECT backoff_attempt, backoff_until FROM posthog_batchimport WHERE id = $1"#,
                    )
                    .bind(id)
                    .fetch_one(&context.db)
                    .await
                    {
                        // Annotate types for clarity
                        let attempt: Result<i32, sqlx::Error> = rec.try_get("backoff_attempt");
                        if let Ok(a) = attempt { model.backoff_attempt = a; }

                        let until: Result<Option<DateTime<Utc>>, sqlx::Error> = rec.try_get("backoff_until");
                        if let Ok(u) = until { model.backoff_until = u; }
                    }
                }

                Ok(Some(model))
            }
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
        db_columns_enabled: bool,
    ) -> Result<(), Error> {
        let Some(current_lease) = self.lease_id.as_ref() else {
            anyhow::bail!("Cannot schedule backoff on a job with no lease")
        };

        let until = Utc::now()
            + chrono::Duration::from_std(delay)
                .map_err(|_| anyhow::Error::msg("Invalid backoff duration"))?;

        // Increment and persist backoff attempt in state JSON as a temporary persistence mechanism
        if let Some(state) = &mut self.state {
            state.backoff_attempt = state.backoff_attempt.saturating_add(1);
        } else {
            self.state = Some(JobState {
                parts: vec![],
                backoff_attempt: 1,
            });
        }

        let state_json = serde_json::to_value(&self.state)?;

        let res = if db_columns_enabled {
            // Write DB backoff columns too
            sqlx::query(
                r#"
                UPDATE posthog_batchimport
                SET
                    status = 'running',
                    status_message = $3,
                    display_status_message = $4,
                    updated_at = now(),
                    leased_until = $2,
                    state = $5,
                    backoff_attempt = $6,
                    backoff_until = $2
                WHERE id = $1 AND lease_id = $7
                "#,
            )
            .bind(self.id)
            .bind(until)
            .bind(&status_message)
            .bind(&display_message)
            .bind(state_json)
            .bind(next_attempt)
            .bind(current_lease)
            .execute(pool)
            .await?
        } else {
            sqlx::query(
                r#"
                UPDATE posthog_batchimport
                SET
                    status = 'running',
                    status_message = $3,
                    display_status_message = $4,
                    updated_at = now(),
                    leased_until = $2,
                    state = $5
                WHERE id = $1 AND lease_id = $6
                "#,
            )
            .bind(self.id)
            .bind(until)
            .bind(&status_message)
            .bind(&display_message)
            .bind(state_json)
            .bind(current_lease)
            .execute(pool)
            .await?
        };

        throw_if_no_rows(res)?;

        // Update in-memory representation
        self.status = JobStatus::Running;
        self.status_message = Some(status_message);
        self.display_status_message = display_message;
        self.leased_until = Some(until);
        self.backoff_attempt = next_attempt;
        self.backoff_until = Some(until);

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
        // Reset in-memory backoff state
        self.backoff_attempt = 0;
        self.backoff_until = None;

        // Persist regular fields
        self.flush(&context.db, true).await?;

        // Optionally reset DB backoff columns
        if context.config.backoff_db_columns_enabled {
            let _ = sqlx::query(
                r#"
                UPDATE posthog_batchimport
                SET backoff_attempt = 0, backoff_until = NULL
                WHERE id = $1
                "#,
            )
            .bind(self.id)
            .execute(&context.db)
            .await?;
        }

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
    previous_lease_id: Option<String>,
}

impl TryFrom<(JobRow, &[String], String)> for JobModel {
    type Error = Error;

    fn try_from(input: (JobRow, &[String], String)) -> Result<Self, Self::Error> {
        let (row, keys, lease_id) = input;
        let state = match row.state {
            Some(s) => serde_json::from_value(s).context("Parsing state")?,
            None => JobState {
                parts: vec![],
                backoff_attempt: 0,
            },
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
            backoff_attempt: 0,
            backoff_until: None,
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
