use std::{fmt::Display, sync::Arc};

use anyhow::{Context, Error};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::{postgres::PgQueryResult, PgPool};
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
                WHERE status = 'running' AND coalesce(leased_until, now()) <= now()
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

        match (row, context.encryption_keys.as_slice(), new_lease_id)
            .try_into()
            .context("Failed to parse job row")
        {
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
        self.flush(&context.db, true).await
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
