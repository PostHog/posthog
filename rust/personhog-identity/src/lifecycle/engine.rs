//! The saga engine: op persistence, lease, and the drive loop. Generic over
//! op type — an [`OpDriver`] supplies the step handlers, the engine supplies
//! everything an op type shares: create-or-attach by op_id, lease
//! claim/renew/steal by `lease_expires_at`, the run loop, the sweeper scan,
//! and GC. Delete registers one driver; merge later registers another
//! without engine changes.
//!
//! Correctness model: the lease is a throttle, not a lock — an expired lease
//! can be stolen while the old driver is still running, so two drivers may
//! run the same step concurrently. Steps stay correct anyway because every
//! step commits its work and its step advance (a compare-and-swap on
//! `lifecycle_op.step`) in one transaction: the loser's CAS fails, its
//! transaction rolls back, and its work evaporates. A saved step therefore
//! always means "everything up to and including this step really happened,
//! exactly once". A claim's bumped `attempt` doubles as a fencing token:
//! renew/release match only while `attempt` is unchanged, so a displaced
//! driver cannot extend or clear a stealer's lease.

use std::time::Duration;

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde_json::Value;
use sqlx::postgres::PgPool;
use tonic::Status;
use uuid::Uuid;

/// Terminal step: the op ran to the end.
pub const STEP_COMPLETED: &str = "completed";
/// Terminal step: the op backed out before mutating anything.
pub const STEP_ABORTED: &str = "aborted";

const OPS_COMPLETED_TOTAL: &str = "personhog_lifecycle_ops_completed_total";
const SWEEPER_RESUMED_TOTAL: &str = "personhog_lifecycle_sweeper_resumed_total";

/// How many abandoned ops one sweep pass will pick up.
const SWEEP_BATCH_SIZE: i64 = 100;

pub type Tx<'a> = sqlx::Transaction<'a, sqlx::Postgres>;

#[derive(Debug, thiserror::Error)]
pub enum SagaError {
    #[error("database error: {0}")]
    Db(#[from] sqlx::Error),
    /// The op_id already exists with a different op type, team, or request.
    #[error("op_id reused with a different request: {0}")]
    RequestMismatch(String),
    /// Another instance held the lease past our deadline.
    #[error("another instance is driving this operation")]
    Busy,
    /// State this engine or driver cannot interpret.
    #[error("corrupt saga state: {0}")]
    CorruptState(String),
}

impl From<SagaError> for Status {
    fn from(err: SagaError) -> Status {
        match err {
            SagaError::Db(e) => Status::internal(format!("database error: {e}")),
            SagaError::RequestMismatch(msg) => Status::failed_precondition(msg),
            SagaError::Busy => Status::unavailable(
                "another instance is driving this operation; retry with the same op_id",
            ),
            SagaError::CorruptState(msg) => Status::internal(msg),
        }
    }
}

/// One row of `lifecycle_op`: the complete checkpoint of an operation.
#[derive(Debug, Clone)]
pub struct OpRow {
    pub op_id: Uuid,
    pub op_type: String,
    pub team_id: i64,
    pub step: String,
    pub attempt: i32,
    pub request: Value,
    pub outcome: Option<Value>,
    pub completed_at: Option<DateTime<Utc>>,
}

/// Step handlers for one op type. The engine calls [`run_step`] with the
/// current row until the row reaches a terminal step.
///
/// Contract for `run_step`: do the current step's work and, in the same
/// transaction as that work, advance `lifecycle_op.step` with
/// [`advance_step_in_tx`] (or finish with [`complete_op_in_tx`]). If the
/// advance reports the step already moved, roll the transaction back and
/// return Ok — the engine reloads and continues from the fresh row. Every
/// step must be safe to repeat.
///
/// [`run_step`]: OpDriver::run_step
#[async_trait]
pub trait OpDriver: Send + Sync {
    fn op_type(&self) -> &'static str;
    /// The step a freshly created op row starts on.
    fn initial_step(&self) -> &'static str;
    async fn run_step(&self, pool: &PgPool, op: &OpRow) -> Result<(), SagaError>;
}

#[derive(Clone, Debug)]
pub struct EngineConfig {
    /// How long one claim of an op lasts before another instance may steal it.
    pub lease: Duration,
    /// How long `execute`/`resume` keeps driving (or waiting on another
    /// driver's lease) before giving up with `Busy`.
    pub execute_timeout: Duration,
    /// How often a non-owning driver re-checks a leased op for completion.
    pub poll_interval: Duration,
    /// Log a warning when an op's attempt counter reaches this value.
    pub attempt_alert_threshold: i32,
}

pub struct Engine {
    pool: PgPool,
    config: EngineConfig,
}

impl Engine {
    pub fn new(pool: PgPool, config: EngineConfig) -> Self {
        Self { pool, config }
    }

    pub fn pool(&self) -> &PgPool {
        &self.pool
    }

    /// Create the op if it is new, then drive it to a terminal step and
    /// return the terminal row. A retry with the same op_id attaches to the
    /// existing op: completed → returns the recorded row without running
    /// anything; live → waits for or steals the lease and resumes from the
    /// saved step.
    pub async fn execute(
        &self,
        driver: &dyn OpDriver,
        op_id: Uuid,
        team_id: i64,
        request: &Value,
    ) -> Result<OpRow, SagaError> {
        sqlx::query!(
            r#"
            INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (op_id) DO NOTHING
            "#,
            op_id,
            driver.op_type(),
            team_id as i32,
            driver.initial_step(),
            request,
        )
        .execute(&self.pool)
        .await?;

        let row = self.load(op_id).await?.ok_or_else(|| {
            SagaError::CorruptState(format!("op {op_id} vanished right after create-or-attach"))
        })?;
        if row.op_type != driver.op_type() || row.team_id != team_id || row.request != *request {
            return Err(SagaError::RequestMismatch(format!(
                "op {op_id} already exists with a different request"
            )));
        }

        self.drive(driver, op_id, true).await
    }

    /// Drive an existing op (sweeper entry point — no create, no request
    /// verification). Does not wait on another driver's live lease: to the
    /// sweeper a live lease means "not abandoned", so this bails with `Busy`
    /// instead of polling out the execute timeout.
    pub async fn resume(&self, driver: &dyn OpDriver, op_id: Uuid) -> Result<OpRow, SagaError> {
        self.drive(driver, op_id, false).await
    }

    async fn drive(
        &self,
        driver: &dyn OpDriver,
        op_id: Uuid,
        wait_for_lease: bool,
    ) -> Result<OpRow, SagaError> {
        let deadline = tokio::time::Instant::now() + self.config.execute_timeout;
        // The attempt number returned by our claim, used as a fencing token:
        // renew/release only touch the lease while `attempt` still matches,
        // so a driver whose lease was stolen (the stealer bumped `attempt`)
        // cannot extend or clear the stealer's lease.
        let mut claim_attempt: Option<i32> = None;

        loop {
            let Some(row) = self.load(op_id).await? else {
                return Err(SagaError::CorruptState(format!(
                    "op {op_id} vanished while being driven"
                )));
            };
            if row.completed_at.is_some() {
                if claim_attempt.is_some() {
                    // We drove it over the line (vs attaching to an op that
                    // was already done).
                    common_metrics::inc(
                        OPS_COMPLETED_TOTAL,
                        &[
                            ("op_type".to_string(), row.op_type.clone()),
                            ("final_step".to_string(), row.step.clone()),
                        ],
                        1,
                    );
                }
                return Ok(row);
            }
            if tokio::time::Instant::now() >= deadline {
                if let Some(attempt) = claim_attempt {
                    self.release_lease(op_id, attempt).await.ok();
                }
                return Err(SagaError::Busy);
            }

            match claim_attempt {
                Some(attempt) => {
                    if !self.renew_lease(op_id, attempt).await? {
                        // Another driver stole the lease; go back to
                        // claiming instead of running a step we would lose.
                        claim_attempt = None;
                        continue;
                    }
                }
                None => match self.try_claim(op_id).await? {
                    Some(attempt) => {
                        claim_attempt = Some(attempt);
                        if attempt >= self.config.attempt_alert_threshold {
                            tracing::warn!(
                                op_id = %op_id,
                                op_type = %row.op_type,
                                step = %row.step,
                                attempt,
                                "lifecycle op has been claimed unusually often; it may be stuck"
                            );
                        }
                    }
                    None => {
                        if !wait_for_lease {
                            return Err(SagaError::Busy);
                        }
                        // Someone else holds the lease; wait for them to
                        // finish or for the lease to lapse.
                        tokio::time::sleep(self.config.poll_interval).await;
                        continue;
                    }
                },
            }

            if let Err(err) = driver.run_step(&self.pool, &row).await {
                // Drop the lease so an immediate retry doesn't wait it out.
                if let Some(attempt) = claim_attempt {
                    self.release_lease(op_id, attempt).await.ok();
                }
                return Err(err);
            }
        }
    }

    async fn load(&self, op_id: Uuid) -> Result<Option<OpRow>, sqlx::Error> {
        sqlx::query_as!(
            OpRow,
            r#"
            SELECT op_id, op_type, team_id::bigint as "team_id!", step, attempt,
                   request as "request: Value", outcome as "outcome: Value", completed_at
            FROM lifecycle_op
            WHERE op_id = $1
            "#,
            op_id
        )
        .fetch_optional(&self.pool)
        .await
    }

    /// Claim the op if its lease is free or lapsed. Returns the new attempt
    /// count on success, None when another instance holds a live lease.
    async fn try_claim(&self, op_id: Uuid) -> Result<Option<i32>, sqlx::Error> {
        sqlx::query_scalar!(
            r#"
            UPDATE lifecycle_op
            SET lease_expires_at = now() + make_interval(secs => $2),
                attempt = attempt + 1
            WHERE op_id = $1 AND completed_at IS NULL
              AND (lease_expires_at IS NULL OR lease_expires_at < now())
            RETURNING attempt
            "#,
            op_id,
            self.config.lease.as_secs_f64(),
        )
        .fetch_optional(&self.pool)
        .await
    }

    /// Extend our lease. Returns false when the lease is no longer ours
    /// (another driver claimed the op and bumped `attempt`).
    async fn renew_lease(&self, op_id: Uuid, attempt: i32) -> Result<bool, sqlx::Error> {
        let result = sqlx::query!(
            r#"
            UPDATE lifecycle_op
            SET lease_expires_at = now() + make_interval(secs => $2)
            WHERE op_id = $1 AND completed_at IS NULL AND attempt = $3
            "#,
            op_id,
            self.config.lease.as_secs_f64(),
            attempt,
        )
        .execute(&self.pool)
        .await?;
        Ok(result.rows_affected() > 0)
    }

    async fn release_lease(&self, op_id: Uuid, attempt: i32) -> Result<(), sqlx::Error> {
        sqlx::query!(
            "UPDATE lifecycle_op SET lease_expires_at = NULL WHERE op_id = $1 AND completed_at IS NULL AND attempt = $2",
            op_id,
            attempt,
        )
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    /// One sweeper pass: resume abandoned ops — incomplete, and either never
    /// claimed (older than one lease, so a freshly created op isn't stolen
    /// from the RPC that is about to claim it) or with a lapsed lease.
    /// Returns how many ops reached a terminal step.
    pub async fn sweep(&self, drivers: &[&dyn OpDriver]) -> Result<u32, SagaError> {
        let abandoned = sqlx::query!(
            r#"
            SELECT op_id, op_type
            FROM lifecycle_op
            WHERE completed_at IS NULL
              AND ((lease_expires_at IS NULL AND created_at < now() - make_interval(secs => $1))
                   OR lease_expires_at < now())
            ORDER BY created_at
            LIMIT $2
            "#,
            self.config.lease.as_secs_f64(),
            SWEEP_BATCH_SIZE,
        )
        .fetch_all(&self.pool)
        .await?;

        let mut resumed = 0u32;
        for op in abandoned {
            let Some(driver) = drivers.iter().find(|d| d.op_type() == op.op_type) else {
                tracing::error!(op_id = %op.op_id, op_type = %op.op_type,
                    "sweeper found an op with no registered driver");
                continue;
            };
            match self.resume(*driver, op.op_id).await {
                Ok(_) => {
                    resumed += 1;
                    common_metrics::inc(SWEEPER_RESUMED_TOTAL, &[], 1);
                }
                // Claimed by another driver between our scan and now, so it
                // is live, not abandoned — leave it to its owner.
                Err(SagaError::Busy) => {}
                Err(err) => {
                    tracing::warn!(op_id = %op.op_id, error = %err,
                        "sweeper failed to resume op; will retry next pass");
                }
            }
        }
        Ok(resumed)
    }

    /// Delete completed op rows past retention (per-person rows cascade).
    /// The retention window exists only for op_id idempotency — the durable
    /// deletion shield is the person tombstone row, not the op row.
    pub async fn gc(&self, retention: Duration) -> Result<u64, SagaError> {
        let result = sqlx::query!(
            r#"
            DELETE FROM lifecycle_op
            WHERE completed_at IS NOT NULL
              AND completed_at < now() - make_interval(secs => $1)
            "#,
            retention.as_secs_f64(),
        )
        .execute(&self.pool)
        .await?;
        Ok(result.rows_affected())
    }
}

/// Compare-and-swap the op's step inside the step's own transaction, so the
/// work and the advance commit together. Returns false when the row is no
/// longer on `from` — another driver already advanced it; the caller must
/// roll back its transaction and let the engine reload.
pub async fn advance_step_in_tx(
    tx: &mut Tx<'_>,
    op_id: Uuid,
    from: &str,
    to: &str,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query!(
        "UPDATE lifecycle_op SET step = $3 WHERE op_id = $1 AND step = $2",
        op_id,
        from,
        to
    )
    .execute(&mut **tx)
    .await?;
    Ok(result.rows_affected() == 1)
}

/// Terminal flavor of [`advance_step_in_tx`]: record the outcome, stamp
/// `completed_at`, and drop the lease in the same compare-and-swap.
pub async fn complete_op_in_tx(
    tx: &mut Tx<'_>,
    op_id: Uuid,
    from: &str,
    final_step: &str,
    outcome: &Value,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query!(
        r#"
        UPDATE lifecycle_op
        SET step = $3, outcome = $4, completed_at = now(), lease_expires_at = NULL
        WHERE op_id = $1 AND step = $2
        "#,
        op_id,
        from,
        final_step,
        outcome,
    )
    .execute(&mut **tx)
    .await?;
    Ok(result.rows_affected() == 1)
}
