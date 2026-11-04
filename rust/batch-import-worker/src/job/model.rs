use std::{fmt::Display, str::FromStr, sync::Arc, time::Duration as StdDuration};

use crate::metrics;
use anyhow::{Context, Error};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::{PgPool, Row};
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

    pub pending_commit: Option<PendingCommit>,

    // Not actually in the model, but we calculate it on fetch to let us reason about whether
    // we're resuming an interrupted job
    pub was_leased: bool,

    /// The chunk a claim rewound for this worker to send again, kept out of the row so that a stop
    /// before the re-send starts (backoff, shutdown) does not count as another interrupted send.
    pub recovered_commit: Option<PendingCommit>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum JobStatus {
    Running,
    Paused,
    Failed,
    Completed,
}

/// After this many interrupted sends of one chunk, a claim pauses the job for review instead of
/// re-sending, so a chunk that crashes every worker cannot loop forever.
pub const MAX_INTERRUPTED_SENDS: u32 = 3;

/// The chunk a worker is sending; a value left on the row means a worker stopped mid-commit.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PendingCommit {
    pub key: String,
    pub from_offset: u64,
    pub to_offset: u64,
    /// Earlier sends of this chunk that a worker stopped in the middle of.
    #[serde(default)]
    pub interrupted: u32,
    /// Events the chunk added to `events_emitted`, so a rewind can take them back out.
    #[serde(default)]
    pub events: u64,
}

/// The result of a worker write to its job row.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RowWrite {
    /// False when the write required a running row and the row was no longer running.
    pub applied: bool,
    /// The row status after the write; anything but running means the worker must stop.
    pub status: JobStatus,
    /// The sink send rate stored on the row, if the sink has one.
    pub send_rate: Option<u64>,
}

/// A worker-made status change, applied only while the row is running.
struct StatusChange {
    status: JobStatus,
    status_message: Option<String>,
    display_status_message: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub struct JobState {
    // Parts are sorted, and we iterate through them in order, to let us import
    // from oldest to newest
    pub parts: Vec<PartState>,
    // Trial-run progress; None for normal imports. Persisted alongside parts so
    // a trial resumed after backoff or lease loss continues its page numbering
    // and running summary instead of starting over.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub trial: Option<crate::trial::TrialProgress>,
    // Events committed to the sink across all parts. Old states have no value,
    // so it defaults to 0.
    #[serde(default)]
    pub events_emitted: u64,
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
            // `>=` so a part whose stored offset overshot its total (written by a
            // worker version that kept advancing past the end) still completes on
            // resume instead of being permanently un-finishable.
            Some(size) => self.current_offset >= size,
            None => false,
        }
    }
}

impl JobState {
    /// Advance the named part's offset by `consumed` bytes, returning the new offset.
    /// Returns `None` if no part matches `key`.
    pub fn advance_part_offset(&mut self, key: &str, consumed: u64) -> Option<u64> {
        let part = self.parts.iter_mut().find(|p| p.key == key)?;
        part.current_offset = part.current_offset.saturating_add(consumed);
        Some(part.current_offset)
    }

    /// Revert the named part's offset by `consumed` bytes — the inverse of
    /// [`advance_part_offset`](Self::advance_part_offset), saturating at 0. Returns the new
    /// offset, or `None` if no part matches `key`.
    pub fn revert_part_offset(&mut self, key: &str, consumed: u64) -> Option<u64> {
        let part = self.parts.iter_mut().find(|p| p.key == key)?;
        part.current_offset = part.current_offset.saturating_sub(consumed);
        Some(part.current_offset)
    }

    /// Move the part that `pending` names back to the start of its chunk, and take the chunk's
    /// events out of `events_emitted` when the part moves. Returns false and changes nothing when
    /// the part's offset is at neither end of the chunk.
    pub fn rewind_to_commit_start(&mut self, pending: &PendingCommit) -> bool {
        let Some(part) = self.parts.iter_mut().find(|p| p.key == pending.key) else {
            return false;
        };
        if part.current_offset != pending.to_offset && part.current_offset != pending.from_offset {
            return false;
        }
        if part.current_offset != pending.from_offset {
            part.current_offset = pending.from_offset;
            self.events_emitted = self.events_emitted.saturating_sub(pending.events);
        }
        true
    }

    /// Return why the job must not complete, or `None` when it can. The read loop
    /// decides completion from its in-memory parts, so this checks the stored parts
    /// as well: a job must never report success for a part it did not finish, or
    /// for a source that listed no parts at all.
    pub fn completion_blocker(&self) -> Option<String> {
        if self.parts.is_empty() {
            return Some("job has no parts to import".to_string());
        }
        let unfinished: Vec<&PartState> = self.parts.iter().filter(|p| !p.is_done()).collect();
        let first = unfinished.first()?;
        Some(format!(
            "{} of {} parts are not finished in the stored state, first is {} at offset {} of {:?}",
            unfinished.len(),
            self.parts.len(),
            first.key,
            first.current_offset,
            first.total_size
        ))
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
                posthog_batchimport.secrets as "secrets?",
                posthog_batchimport.backoff_attempt,
                posthog_batchimport.backoff_until,
                posthog_batchimport.pending_commit,
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

        let parsed: anyhow::Result<JobModel> = (
            row,
            context.encryption_keys.as_slice(),
            new_lease_id.clone(),
        )
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
                    WHERE id = $1 AND lease_id = $4 AND status = 'running'
                    "#,
                    id,
                    format!("{:?}", e), // We like context
                    "Failed to parse source event data into Posthog event data",
                    new_lease_id
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

    /// Count jobs that still need a worker: everything in `running` status, whether
    /// queued (unleased) or in-flight (leased). This is the autoscaling signal — one
    /// worker processes one job, so the count maps directly to the desired replica count.
    pub async fn count_active_jobs(pool: &PgPool) -> Result<i64, Error> {
        let count: i64 =
            sqlx::query_scalar("SELECT count(*) FROM posthog_batchimport WHERE status = 'running'")
                .fetch_one(pool)
                .await?;
        Ok(count)
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
                status_message = $3,
                display_status_message = $4,
                updated_at = now(),
                leased_until = now() + make_interval(secs => $2),
                backoff_attempt = $5,
                backoff_until = leased_until
            WHERE id = $1 AND lease_id = $6 AND status = 'running'
            RETURNING leased_until, backoff_until, updated_at
            "#,
        )
        .bind(self.id)
        .bind(delay_secs)
        .bind(&status_message)
        .bind(&display_message)
        .bind(next_attempt)
        .bind(current_lease)
        .fetch_optional(pool)
        .await?;

        let Some(rec) = rec else {
            let current_lease = current_lease.clone();
            let status = self.explain_missed_write(pool, &current_lease).await?;
            info!(job_id = %self.id, %status, "job is no longer running, skipping backoff");
            self.status = status;
            return Ok(());
        };

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

    /// Save worker-owned progress without touching the status. With `only_if_running`, a stopped
    /// row refuses the write, so use it before a send.
    pub async fn save_progress(
        &mut self,
        pool: &PgPool,
        extend_lease: bool,
        only_if_running: bool,
    ) -> Result<RowWrite, Error> {
        self.write(pool, None, extend_lease, only_if_running).await
    }

    /// Save progress after a sink commit, clearing backoff and stale messages while the row runs.
    pub async fn save_committed(&mut self, pool: &PgPool) -> Result<RowWrite, Error> {
        self.backoff_attempt = 0;
        self.backoff_until = None;
        let change = StatusChange {
            status: JobStatus::Running,
            status_message: None,
            display_status_message: None,
        };
        let written = self.write(pool, Some(change), true, false).await?;
        metrics::unpause_event();
        Ok(written)
    }

    pub async fn pause(
        &mut self,
        context: Arc<AppContext>,
        reason: String,
        display_reason: Option<String>,
    ) -> Result<(), Error> {
        let change = StatusChange {
            status: JobStatus::Paused,
            status_message: Some(reason),
            display_status_message: display_reason,
        };
        self.write(&context.db, Some(change), true, false).await?;
        Ok(())
    }

    /// Rewind a part a worker left mid-commit so this worker sends the chunk again, or pause for
    /// review at the cap or on an offset mismatch. Returns true when this worker must skip the job.
    pub async fn recover_interrupted_commit(
        &mut self,
        context: Arc<AppContext>,
    ) -> Result<bool, Error> {
        let Some(pending) = self.pending_commit.clone() else {
            return Ok(false);
        };
        let interrupted = pending.interrupted.saturating_add(1);
        let rewound = interrupted < MAX_INTERRUPTED_SENDS
            && self
                .state
                .as_mut()
                .is_some_and(|state| state.rewind_to_commit_start(&pending));
        if !rewound {
            return self
                .pause_interrupted_commit(context, &pending, interrupted)
                .await;
        }

        self.pending_commit = None;
        if !self.save_recovered_commit(&context.db).await? {
            self.release_lease(&context.db).await?;
            return Ok(true);
        }
        self.recovered_commit = Some(PendingCommit {
            interrupted,
            ..pending.clone()
        });
        warn!(
            job_id = %self.id,
            key = %pending.key,
            from_offset = pending.from_offset,
            to_offset = pending.to_offset,
            interrupted,
            "job was interrupted mid-commit, re-sending the chunk"
        );
        metrics::interrupted_commit_resent();
        Ok(false)
    }

    async fn pause_interrupted_commit(
        &mut self,
        context: Arc<AppContext>,
        pending: &PendingCommit,
        interrupted: u32,
    ) -> Result<bool, Error> {
        warn!(
            job_id = %self.id,
            key = %pending.key,
            from_offset = pending.from_offset,
            to_offset = pending.to_offset,
            interrupted,
            "job was interrupted mid-commit, pausing for review"
        );
        metrics::interrupted_commit_paused();
        let chunk = format!(
            "part {} (offsets {} to {})",
            pending.key, pending.from_offset, pending.to_offset
        );
        let reason = if interrupted >= MAX_INTERRUPTED_SENDS {
            format!("Workers stopped {interrupted} times while committing {chunk}.")
        } else {
            format!("A worker stopped while committing {chunk}, and the saved offset does not match that chunk.")
        };
        self.pause(
            context.clone(),
            format!("{reason} The chunk may not have reached the sink."),
            Some("Job paused after an interrupted commit. Resume it to continue.".to_string()),
        )
        .await?;
        self.release_lease(&context.db).await?;
        Ok(true)
    }

    /// Save a rewound part and clear its marker without changing the claim lease, which stays
    /// long because job init is slow. Returns false when the row is no longer running.
    async fn save_recovered_commit(&mut self, pool: &PgPool) -> Result<bool, Error> {
        let Some(lease) = self.lease_id.clone() else {
            anyhow::bail!("Cannot write a job with no lease")
        };
        let result = sqlx::query(
            r#"
            UPDATE posthog_batchimport
            SET state = $2, pending_commit = NULL, updated_at = now()
            WHERE id = $1 AND lease_id = $3 AND status = 'running'
            "#,
        )
        .bind(self.id)
        .bind(serde_json::to_value(&self.state)?)
        .bind(&lease)
        .execute(pool)
        .await?;
        if result.rows_affected() == 1 {
            return Ok(true);
        }
        self.status = self.explain_missed_write(pool, &lease).await?;
        Ok(false)
    }

    /// Give up the lease so the row shows that no worker holds it.
    pub async fn release_lease(&mut self, pool: &PgPool) -> Result<(), Error> {
        let Some(lease) = self.lease_id.take() else {
            return Ok(());
        };
        self.leased_until = None;
        sqlx::query!(
            r#"
            UPDATE posthog_batchimport
            SET lease_id = NULL, leased_until = NULL
            WHERE id = $1 AND lease_id = $2
            "#,
            self.id,
            lease
        )
        .execute(pool)
        .await?;
        Ok(())
    }

    /// Reset backoff columns in the database after a successful request and update in-memory fields.
    pub async fn reset_backoff_in_db(&mut self, pool: &PgPool) -> Result<(), Error> {
        sqlx::query(
            r#"
            UPDATE posthog_batchimport
            SET backoff_attempt = 0, backoff_until = NULL
            WHERE id = $1 AND lease_id = $2
            "#,
        )
        .bind(self.id)
        .bind(&self.lease_id)
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
        let change = StatusChange {
            status: JobStatus::Failed,
            status_message: Some(reason),
            display_status_message: Some(display_reason),
        };
        self.write(pool, Some(change), false, false).await?;
        Ok(())
    }

    /// Mark the job completed, unless an operator changed its status. Returns the row status.
    pub async fn complete(&mut self, pool: &PgPool) -> Result<JobStatus, Error> {
        let change = StatusChange {
            status: JobStatus::Completed,
            status_message: self.status_message.clone(),
            display_status_message: None,
        };
        Ok(self.write(pool, Some(change), false, false).await?.status)
    }

    /// Every worker write to the job row goes through here: it needs this worker's lease, and
    /// `change` applies only while the row is running. A lost lease is an error.
    async fn write(
        &mut self,
        pool: &PgPool,
        change: Option<StatusChange>,
        extend_lease: bool,
        only_if_running: bool,
    ) -> Result<RowWrite, Error> {
        let Some(old_lease) = self.lease_id.clone() else {
            anyhow::bail!("Cannot write a job with no lease")
        };

        // A claim leases for 30 minutes because job init is slow; later writes extend it by 5.
        let (new_lease, new_leased_until) = if extend_lease {
            (
                Some(Uuid::now_v7().to_string()),
                Some(Utc::now() + chrono::Duration::minutes(5)),
            )
        } else {
            (None, None)
        };
        let (new_status, new_message, new_display_message) = match &change {
            Some(change) => (
                Some(change.status.to_string()),
                change.status_message.clone(),
                change.display_status_message.clone(),
            ),
            None => (None, None, None),
        };

        let row = sqlx::query!(
            r#"
            UPDATE posthog_batchimport
            SET
                status = CASE WHEN $2::text IS NOT NULL AND status = 'running' THEN $2 ELSE status END,
                status_message = CASE WHEN $2::text IS NOT NULL AND status = 'running' THEN $3 ELSE status_message END,
                display_status_message = CASE WHEN $2::text IS NOT NULL AND status = 'running' THEN $4 ELSE display_status_message END,
                state = $5,
                pending_commit = $6,
                backoff_attempt = $7,
                backoff_until = $8,
                updated_at = now(),
                lease_id = $9,
                leased_until = $10
            WHERE id = $1 AND lease_id = $11 AND (NOT $12 OR status = 'running')
            RETURNING status, import_config->'sink'->>'send_rate' AS send_rate
            "#,
            self.id,
            new_status,
            new_message,
            new_display_message,
            serde_json::to_value(&self.state)?,
            self.pending_commit
                .as_ref()
                .map(serde_json::to_value)
                .transpose()?,
            self.backoff_attempt,
            self.backoff_until,
            new_lease,
            new_leased_until,
            old_lease,
            only_if_running
        )
        .fetch_optional(pool)
        .await?;

        let Some(row) = row else {
            let status = self.explain_missed_write(pool, &old_lease).await?;
            self.status = status;
            return Ok(RowWrite {
                applied: false,
                status,
                send_rate: None,
            });
        };

        let status = JobStatus::from_str(&row.status)?;
        self.lease_id = new_lease;
        self.leased_until = new_leased_until;
        if let Some(change) = change {
            if status == change.status {
                self.status_message = change.status_message;
                self.display_status_message = change.display_status_message;
            }
        }
        self.status = status;

        Ok(RowWrite {
            applied: true,
            status,
            send_rate: row
                .send_rate
                .and_then(|rate| rate.parse::<u64>().ok())
                .filter(|rate| *rate > 0),
        })
    }

    /// Explain a write that matched no row: a lost lease is an error, otherwise return the status
    /// an operator or a customer set.
    async fn explain_missed_write(&self, pool: &PgPool, lease: &str) -> Result<JobStatus, Error> {
        let row = sqlx::query!(
            r#"SELECT status, lease_id FROM posthog_batchimport WHERE id = $1"#,
            self.id
        )
        .fetch_optional(pool)
        .await?;
        let Some(row) = row else {
            anyhow::bail!("Job {} no longer exists", self.id)
        };
        if row.lease_id.as_deref() != Some(lease) {
            anyhow::bail!(
                "Lost the lease on job {}: another worker or a resume took it",
                self.id
            )
        }
        JobStatus::from_str(&row.status)
    }
}

impl FromStr for JobStatus {
    type Err = Error;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "running" => Ok(JobStatus::Running),
            "paused" => Ok(JobStatus::Paused),
            "failed" => Ok(JobStatus::Failed),
            "completed" => Ok(JobStatus::Completed),
            other => anyhow::bail!("Unknown job status {other:?}"),
        }
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
    secrets: Option<String>,
    backoff_attempt: Option<i32>,
    backoff_until: Option<DateTime<Utc>>,
    pending_commit: Option<serde_json::Value>,
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
                trial: None,
                events_emitted: 0,
            },
        };

        let import_config = serde_json::from_value(row.import_config).context("Parsing config")?;
        let pending_commit = row
            .pending_commit
            .map(serde_json::from_value)
            .transpose()
            .context("Parsing pending commit")?;

        // Jobs authenticating via IAM role have no secrets — the column is NULL.
        let secrets = match row.secrets.as_deref() {
            Some(data) if !data.is_empty() => {
                JobSecrets::decrypt(data, keys).context("Decrypting secrets")?
            }
            _ => JobSecrets::empty(),
        };

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
            pending_commit,
            was_leased: row.previous_lease_id.is_some(),
            recovered_commit: None,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::super::test_db;
    use super::*;
    use chrono::Utc;
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
            pending_commit: None,
            was_leased: false,
            recovered_commit: None,
        }
    }

    fn make_job_state(parts: &[(&str, u64)]) -> JobState {
        JobState {
            parts: parts
                .iter()
                .map(|(key, offset)| PartState {
                    key: key.to_string(),
                    current_offset: *offset,
                    total_size: None,
                })
                .collect(),
            trial: None,
            events_emitted: 0,
        }
    }

    fn make_job_row(secrets: Option<String>) -> JobRow {
        JobRow {
            id: Uuid::now_v7(),
            team_id: 1,
            created_at: Utc::now(),
            updated_at: Utc::now(),
            status_message: None,
            display_status_message: None,
            state: None,
            import_config: serde_json::to_value(
                make_dummy_job_model(Uuid::now_v7(), "lease", 1).import_config,
            )
            .unwrap(),
            secrets,
            backoff_attempt: None,
            backoff_until: None,
            pending_commit: None,
            previous_lease_id: None,
        }
    }

    // Jobs using IAM role auth store NULL secrets - parsing must skip decryption
    // instead of failing (a parse failure pauses the job).
    #[test]
    fn test_null_and_empty_secrets_parse_as_empty() {
        let keys = vec!["0".repeat(32)];
        for secrets in [None, Some(String::new())] {
            let model =
                JobModel::try_from((make_job_row(secrets), keys.as_slice(), "l".to_string()))
                    .unwrap();
            assert!(model.secrets.secrets.is_empty());
        }
    }

    #[test]
    fn test_undecryptable_secrets_still_fail_parsing() {
        let keys = vec!["0".repeat(32)];
        let row = make_job_row(Some("not-a-fernet-token".to_string()));
        assert!(JobModel::try_from((row, keys.as_slice(), "l".to_string())).is_err());
    }

    #[test]
    fn test_part_is_done() {
        // (offset, total, expected). Overshot offsets (recorded by worker versions
        // that advanced past the end of a part) must still count as done, or the
        // part can never complete on resume.
        let cases: [(u64, Option<u64>, bool); 5] = [
            (0, None, false),
            (99, Some(100), false),
            (100, Some(100), true),
            (101, Some(100), true),
            (0, Some(0), true),
        ];
        for (offset, total, expected) in cases {
            let part = PartState {
                key: "k".to_string(),
                current_offset: offset,
                total_size: total,
            };
            assert_eq!(part.is_done(), expected, "offset {offset}, total {total:?}");
        }
    }

    #[test]
    fn test_completion_blocker() {
        let part = |offset: u64, total: Option<u64>| PartState {
            key: "k".to_string(),
            current_offset: offset,
            total_size: total,
        };
        let cases: [(&str, Vec<PartState>, bool); 5] = [
            ("no parts", vec![], true),
            (
                "all done",
                vec![part(10, Some(10)), part(0, Some(0))],
                false,
            ),
            ("overshot counts as done", vec![part(11, Some(10))], false),
            (
                "one part behind",
                vec![part(10, Some(10)), part(4, Some(10))],
                true,
            ),
            ("unknown size", vec![part(10, None)], true),
        ];
        for (name, parts, blocked) in cases {
            let state = JobState {
                parts,
                trial: None,
                events_emitted: 0,
            };
            assert_eq!(
                state.completion_blocker().is_some(),
                blocked,
                "case '{name}'"
            );
        }
    }

    #[test]
    fn test_advance_part_offset_increments_and_returns_new_offset() {
        let mut state = make_job_state(&[("a", 100), ("b", 0)]);
        assert_eq!(state.advance_part_offset("a", 50), Some(150));
        assert_eq!(state.parts[0].current_offset, 150);
        assert_eq!(state.parts[1].current_offset, 0, "other parts untouched");
    }

    #[test]
    fn test_revert_part_offset_is_inverse_of_advance() {
        let mut state = make_job_state(&[("a", 100)]);
        let advanced = state.advance_part_offset("a", 4242).unwrap();
        assert_eq!(state.revert_part_offset("a", 4242), Some(advanced - 4242));
        assert_eq!(state.parts[0].current_offset, 100);
    }

    #[test]
    fn test_revert_part_offset_saturates_at_zero() {
        let mut state = make_job_state(&[("a", 10)]);
        assert_eq!(state.revert_part_offset("a", 999), Some(0));
        assert_eq!(state.parts[0].current_offset, 0);
    }

    #[test]
    fn test_offset_helpers_return_none_for_unknown_key() {
        let mut state = make_job_state(&[("a", 0)]);
        assert_eq!(state.advance_part_offset("missing", 1), None);
        assert_eq!(state.revert_part_offset("missing", 1), None);
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

    fn fixture(
        status: JobStatus,
        pending_commit: Option<serde_json::Value>,
    ) -> test_db::JobRowFixture {
        test_db::JobRowFixture {
            status,
            lease_id: "lease-from-claim",
            state: make_job_state(&[("part-1", 0)]),
            sink: serde_json::json!({"type": "noop"}),
            pending_commit,
        }
    }

    #[derive(Debug, Clone, Copy)]
    enum WorkerAction {
        Pause,
        Fail,
        Complete,
        Backoff,
        Committed,
    }

    impl WorkerAction {
        async fn run(self, model: &mut JobModel, context: Arc<AppContext>) {
            match self {
                WorkerAction::Pause => model
                    .pause(context, "worker pause".to_string(), None)
                    .await
                    .unwrap(),
                WorkerAction::Fail => model
                    .fail(&context.db, "worker fail".to_string(), "failed".to_string())
                    .await
                    .unwrap(),
                WorkerAction::Complete => {
                    model.complete(&context.db).await.unwrap();
                }
                WorkerAction::Backoff => model
                    .schedule_backoff(
                        &context.db,
                        StdDuration::from_secs(60),
                        "rate limited".to_string(),
                        Some("retrying".to_string()),
                        1,
                    )
                    .await
                    .unwrap(),
                WorkerAction::Committed => {
                    model.save_committed(&context.db).await.unwrap();
                }
            }
        }

        fn status_on_running_row(self) -> &'static str {
            match self {
                WorkerAction::Pause => "paused",
                WorkerAction::Fail => "failed",
                WorkerAction::Complete => "completed",
                WorkerAction::Backoff | WorkerAction::Committed => "running",
            }
        }
    }

    #[tokio::test]
    async fn test_worker_status_changes_never_override_operator_status() {
        let context = test_db::context().await;
        let actions = [
            WorkerAction::Pause,
            WorkerAction::Fail,
            WorkerAction::Complete,
            WorkerAction::Backoff,
            WorkerAction::Committed,
        ];
        let row_statuses = [
            JobStatus::Running,
            JobStatus::Paused,
            JobStatus::Completed,
            JobStatus::Failed,
        ];
        for action in actions {
            for row_status in row_statuses {
                let row = fixture(JobStatus::Running, None);
                let id = test_db::insert_job(&context.db, &row).await;
                let mut model = test_db::claimed_model(id, &row);
                test_db::operator_sets(&context.db, id, row_status).await;
                model.state = Some(make_job_state(&[("part-1", 42)]));

                action.run(&mut model, context.clone()).await;

                let stored = test_db::read_job(&context.db, id).await;
                let expected = match row_status {
                    JobStatus::Running => action.status_on_running_row().to_string(),
                    operator_status => operator_status.to_string(),
                };
                assert_eq!(stored.status, expected, "{action:?} on a {row_status} row");
                if row_status != JobStatus::Running {
                    assert_eq!(
                        stored.status_message.as_deref(),
                        Some(test_db::OPERATOR_MESSAGE),
                        "{action:?} must keep the operator's message on a {row_status} row"
                    );
                }
                if matches!(action, WorkerAction::Backoff) {
                    assert_eq!(
                        stored.backoff_until.is_some(),
                        row_status == JobStatus::Running,
                        "a backoff on a {row_status} row"
                    );
                } else {
                    assert_eq!(
                        stored.state.parts[0].current_offset, 42,
                        "{action:?} on a {row_status} row must still save progress"
                    );
                }
                test_db::delete_job(&context.db, id).await;
            }
        }
    }

    struct RecoveryCase {
        name: &'static str,
        part_offset: u64,
        pending: Option<serde_json::Value>,
        operator: Option<JobStatus>,
        skipped: bool,
        status: &'static str,
        offset: u64,
        stored_pending: Option<serde_json::Value>,
        recovered_interrupted: Option<u32>,
        events_emitted: u64,
        message: Option<&'static str>,
    }

    #[tokio::test]
    async fn test_claim_recovers_an_interrupted_commit() {
        let context = test_db::context().await;
        let marker = |key: &str, interrupted: u32| {
            Some(serde_json::json!(
                {"key": key, "from_offset": 100, "to_offset": 250, "interrupted": interrupted, "events": 40}
            ))
        };
        let resent = |name, part_offset, interrupted| RecoveryCase {
            name,
            part_offset,
            pending: marker("part-1", interrupted),
            operator: None,
            skipped: false,
            status: "running",
            offset: 100,
            stored_pending: None,
            recovered_interrupted: Some(interrupted + 1),
            events_emitted: if part_offset == 250 { 60 } else { 100 },
            message: None,
        };
        let paused =
            |name, part_offset, pending: Option<serde_json::Value>, message| RecoveryCase {
                name,
                part_offset,
                pending: pending.clone(),
                operator: None,
                skipped: true,
                status: "paused",
                offset: part_offset,
                stored_pending: pending,
                recovered_interrupted: None,
                events_emitted: 100,
                message: Some(message),
            };
        let cases = [
            RecoveryCase {
                pending: None,
                offset: 250,
                recovered_interrupted: None,
                events_emitted: 100,
                ..resent("no marker", 250, 0)
            },
            resent("first crash re-sends", 250, 0),
            resent("part already at the chunk start", 100, 1),
            paused("cap pauses", 250, marker("part-1", 2), "3 times"),
            paused(
                "offset mismatch pauses",
                300,
                marker("part-1", 0),
                "does not match",
            ),
            paused(
                "unknown part pauses",
                250,
                marker("part-9", 0),
                "does not match",
            ),
            RecoveryCase {
                operator: Some(JobStatus::Paused),
                ..paused(
                    "operator stopped it after the claim",
                    250,
                    marker("part-1", 0),
                    test_db::OPERATOR_MESSAGE,
                )
            },
        ];
        for case in cases {
            let name = case.name;
            let row = test_db::JobRowFixture {
                state: JobState {
                    events_emitted: 100,
                    ..make_job_state(&[("part-1", case.part_offset)])
                },
                ..fixture(JobStatus::Running, case.pending)
            };
            let id = test_db::insert_job(&context.db, &row).await;
            let mut model = test_db::claimed_model(id, &row);
            if let Some(operator_status) = case.operator {
                test_db::operator_sets(&context.db, id, operator_status).await;
            }
            let claimed = test_db::read_job(&context.db, id).await;

            let skipped = model
                .recover_interrupted_commit(context.clone())
                .await
                .unwrap();

            let stored = test_db::read_job(&context.db, id).await;
            assert_eq!(skipped, case.skipped, "case '{name}'");
            assert_eq!(stored.status, case.status, "case '{name}'");
            assert_eq!(
                stored.state.parts[0].current_offset, case.offset,
                "case '{name}'"
            );
            assert_eq!(
                stored.state.events_emitted, case.events_emitted,
                "case '{name}': only a part that moves back gives up its chunk's events"
            );
            assert_eq!(
                stored.pending_commit, case.stored_pending,
                "case '{name}': a re-send clears the marker, so a stop before it starts adds no interruption"
            );
            assert_eq!(
                model.recovered_commit.as_ref().map(|r| r.interrupted),
                case.recovered_interrupted,
                "case '{name}'"
            );
            if case.skipped {
                assert_eq!(
                    stored.lease_id, None,
                    "case '{name}': a skipped job frees the row"
                );
            } else {
                assert_eq!(
                    (stored.lease_id, stored.leased_until),
                    (claimed.lease_id, claimed.leased_until),
                    "case '{name}': the worker keeps its claim lease while job init runs"
                );
            }
            if let Some(message) = case.message {
                let stored_message = stored.status_message.unwrap();
                assert!(
                    stored_message.contains(message),
                    "case '{name}': {stored_message}"
                );
            }
            assert_eq!(
                stored.display_status_message.is_some(),
                case.skipped && case.operator.is_none(),
                "case '{name}': only a review pause tells the customer to resume"
            );
            test_db::delete_job(&context.db, id).await;
        }
    }

    #[tokio::test]
    async fn test_send_rate_from_the_row_is_a_positive_integer_or_nothing() {
        let context = test_db::context().await;
        let cases: [(&str, serde_json::Value, Option<u64>); 5] = [
            ("integer", serde_json::json!(250), Some(250)),
            ("zero", serde_json::json!(0), None),
            ("decimal", serde_json::json!(1000.5), None),
            ("beyond bigint", serde_json::json!(1e20), None),
            ("string", serde_json::json!("fast"), None),
        ];
        for (name, send_rate, expected) in cases {
            let row = test_db::JobRowFixture {
                sink: serde_json::json!({"type": "noop", "send_rate": send_rate}),
                ..fixture(JobStatus::Running, None)
            };
            let id = test_db::insert_job(&context.db, &row).await;
            let mut model = test_db::claimed_model(id, &row);

            let written = model
                .save_progress(&context.db, true, false)
                .await
                .unwrap_or_else(|e| {
                    panic!("case '{name}': a bad send rate must not fail the write: {e:#}")
                });

            assert!(written.applied, "case '{name}'");
            assert_eq!(written.send_rate, expected, "case '{name}'");
            test_db::delete_job(&context.db, id).await;
        }
    }

    #[test]
    fn test_claimed_row_carries_pending_commit() {
        let keys = vec!["0".repeat(32)];
        let mut row = make_job_row(None);
        row.pending_commit =
            Some(serde_json::json!({"key": "k", "from_offset": 1, "to_offset": 2}));

        let model = JobModel::try_from((row, keys.as_slice(), "l".to_string())).unwrap();

        assert_eq!(
            model.pending_commit,
            Some(PendingCommit {
                key: "k".to_string(),
                from_offset: 1,
                to_offset: 2,
                interrupted: 0,
                events: 0,
            })
        );
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
