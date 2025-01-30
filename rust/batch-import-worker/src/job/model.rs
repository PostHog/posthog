use std::{fmt::Display, sync::Arc};

use anyhow::{Context, Error};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::PgPool;
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
    pub status_message: Option<String>,

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
    pub current_offset: usize,
    pub total_size: usize,
}

impl PartState {
    pub fn is_done(&self) -> bool {
        self.current_offset == self.total_size
    }
}

impl JobModel {
    pub async fn claim_next_job(context: Arc<AppContext>) -> Result<Option<JobModel>, Error> {
        // We use select for update to lock a row, then update it, returning the updated row
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
                leased_until = now() + interval '5 minutes'
            FROM next_job
            WHERE posthog_batchimport.id = next_job.id
            RETURNING
                posthog_batchimport.id,
                posthog_batchimport.team_id,
                posthog_batchimport.created_at,
                posthog_batchimport.updated_at,
                posthog_batchimport.status_message,
                posthog_batchimport.state,
                posthog_batchimport.import_config,
                posthog_batchimport.secrets,
                next_job.previous_lease_id
            "#,
        )
        .fetch_optional(&context.db)
        .await?;

        let Some(row) = row else {
            return Ok(None);
        };

        let id = row.id;

        match (row, context.encryption_keys.as_slice())
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
                        status_message = $2
                    WHERE id = $1
                    "#,
                    id,
                    format!("{:?}", e) // We like context
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
        if extend_lease {
            self.lease_id = Some(Uuid::now_v7().to_string());
        } else {
            self.lease_id = None;
        };

        if extend_lease {
            self.leased_until =
                Some(self.leased_until.unwrap_or_else(Utc::now) + chrono::Duration::minutes(5));
        } else {
            self.leased_until = None;
        };

        sqlx::query!(
            r#"
            UPDATE posthog_batchimport
            SET
                status = $2,
                status_message = $3,
                state = $4,
                updated_at = now(),
                lease_id = $5,
                leased_until = $6
            WHERE id = $1
            "#,
            self.id,
            self.status.to_string(),
            self.status_message,
            serde_json::to_value(&self.state)?,
            self.lease_id,
            self.leased_until
        )
        .execute(pool)
        .await?;

        Ok(())
    }

    pub async fn pause(&mut self, context: Arc<AppContext>, reason: String) -> Result<(), Error> {
        self.status = JobStatus::Paused;
        self.status_message = Some(reason);
        self.flush(&context.db, false).await
    }

    pub async fn unpause(&mut self, context: Arc<AppContext>) -> Result<(), Error> {
        self.status = JobStatus::Running;
        self.status_message = None;
        self.flush(&context.db, true).await
    }

    pub async fn fail(&mut self, pool: &PgPool, reason: String) -> Result<(), Error> {
        self.status = JobStatus::Failed;
        self.status_message = Some(reason);
        self.flush(pool, false).await
    }

    pub async fn complete(&mut self, pool: &PgPool) -> Result<(), Error> {
        self.status = JobStatus::Completed;
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
    state: Option<serde_json::Value>,
    import_config: serde_json::Value,
    secrets: String,
    previous_lease_id: Option<String>,
}

impl TryFrom<(JobRow, &[String])> for JobModel {
    type Error = Error;

    fn try_from(input: (JobRow, &[String])) -> Result<Self, Self::Error> {
        let (row, keys) = input;
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
            lease_id: None,
            leased_until: None,
            status: JobStatus::Running,
            status_message: row.status_message,
            state: Some(state),
            import_config,
            secrets,
            was_leased: row.previous_lease_id.is_some(),
        })
    }
}
