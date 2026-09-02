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
use rand::Rng;
use serde_json::Value;
use sqlx::postgres::PgPool;
use tonic::Status;
use uuid::Uuid;

/// Terminal step: the op ran to the end.
pub const STEP_COMPLETED: &str = "completed";
/// Terminal step: the op backed out before mutating anything.
pub const STEP_ABORTED: &str = "aborted";

const OPS_COMPLETED_TOTAL: &str = "personhog_lifecycle_ops_completed_total";
const OP_DURATION_MS: &str = "personhog_lifecycle_op_duration_ms";
const SWEEPER_RESUMED_TOTAL: &str = "personhog_lifecycle_sweeper_resumed_total";
const STEP_FAILURES_TOTAL: &str = "personhog_lifecycle_step_failures_total";
const OPS_PARKED_TOTAL: &str = "personhog_lifecycle_ops_parked_total";
const OPS_PARKED: &str = "personhog_lifecycle_ops_parked";

/// How many abandoned ops one sweep pass will pick up.
const SWEEP_BATCH_SIZE: i64 = 100;

/// Pause before re-driving a step that lost a database conflict. Long
/// enough for the competing statement (typically a writer flush) to finish;
/// the execute deadline still bounds the total retry time.
const DB_CONFLICT_BACKOFF: Duration = Duration::from_millis(50);

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
    /// A leader RPC (fence, release, fold) failed transiently. The step made
    /// no durable progress; a retry with the same op_id re-drives it. Boxed
    /// so the rare failure does not widen every step's Result.
    #[error("leader call failed: {0}")]
    Leader(Box<Status>),
    /// A leader RPC was refused definitively: the request itself failed
    /// the leader's verification, so retries cannot succeed. Drivers
    /// unwind where they still can (the merge driver aborts before the
    /// flip); a refusal that reaches the engine parks the op.
    #[error("leader refused: {0}")]
    LeaderRefused(Box<Status>),
    /// State this engine or driver cannot interpret.
    #[error("corrupt saga state: {0}")]
    CorruptState(String),
}

impl SagaError {
    /// Classify a leader RPC failure: a semantic refusal is definitive
    /// and never retried; everything else is transient and retried.
    pub fn leader(status: Status) -> Self {
        if personhog_common::grpc::is_semantic_refusal(&status) {
            SagaError::LeaderRefused(Box::new(status))
        } else {
            SagaError::Leader(Box::new(status))
        }
    }

    /// A database conflict Postgres asks callers to retry: deadlock victim
    /// (40P01), serialization failure (40001), or a cancelled statement
    /// (57014, the statement timeout under lock contention). Steps commit
    /// their work and their step advance together, so re-driving one is
    /// always safe — the engine retries these instead of surfacing them.
    pub fn is_db_conflict(&self) -> bool {
        let SagaError::Db(sqlx::Error::Database(db)) = self else {
            return false;
        };
        matches!(db.code().as_deref(), Some("40P01" | "40001" | "57014"))
    }

    /// The Postgres error detail for a database conflict. For a deadlock it
    /// names the processes, lock targets, and relations in the cycle — the
    /// only place that evidence surfaces when server-side error logging is
    /// disabled (dev RDS logs no ERROR lines).
    pub fn db_detail(&self) -> Option<&str> {
        let SagaError::Db(sqlx::Error::Database(db)) = self else {
            return None;
        };
        db.try_downcast_ref::<sqlx::postgres::PgDatabaseError>()
            .and_then(|e| e.detail())
    }
}

impl From<SagaError> for Status {
    fn from(err: SagaError) -> Status {
        match err {
            SagaError::Db(e) => Status::internal(format!("database error: {e}")),
            // A definitive refusal (the op_id belongs to a different
            // request), marked so callers branch on the reason instead of
            // the message and retry layers never loop on it.
            SagaError::RequestMismatch(msg) => {
                personhog_common::grpc::semantic_refusal(msg, "op_id_reused")
            }
            SagaError::Busy => Status::unavailable(
                "another instance is driving this operation; retry with the same op_id",
            ),
            SagaError::Leader(status) => Status::unavailable(format!(
                "leader call failed ({}: {}); retry with the same op_id",
                status.code(),
                status.message()
            )),
            // Passed through verbatim so the caller sees a definitive
            // refusal, not a retriable error to loop on.
            SagaError::LeaderRefused(status) => *status,
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
    pub created_at: DateTime<Utc>,
    pub completed_at: Option<DateTime<Utc>>,
    /// Whether another driver's lease was live when this row was read — a
    /// read-time fact for the claim precheck, not part of the checkpoint.
    pub lease_live: bool,
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
        self.create_or_attach(driver, op_id, team_id, request)
            .await?;
        self.drive(driver, op_id, true).await
    }

    /// The create-or-attach half of [`execute`], without driving: create
    /// the op if it is new, verify an existing op matches the request, and
    /// return the current row. Lets tests and tooling walk an op step by
    /// step with [`step_once`].
    ///
    /// [`execute`]: Engine::execute
    /// [`step_once`]: Engine::step_once
    pub async fn create_or_attach(
        &self,
        driver: &dyn OpDriver,
        op_id: Uuid,
        team_id: i64,
        request: &Value,
    ) -> Result<OpRow, SagaError> {
        let inserted = sqlx::query!(
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
        .await?
        .rows_affected()
            > 0;

        let row = self.load(op_id).await?.ok_or_else(|| {
            SagaError::CorruptState(format!("op {op_id} vanished right after create-or-attach"))
        })?;
        // Only a genuine attach is verified: the reloaded copy of our own
        // insert has been through jsonb normalization (number rewriting,
        // key ordering), so comparing it against the caller's request
        // would reject a first call whose request isn't normalization-
        // stable — and its retries with it, forever.
        if !inserted
            && (row.op_type != driver.op_type()
                || row.team_id != team_id
                || row.request != *request)
        {
            return Err(SagaError::RequestMismatch(format!(
                "op {op_id} already exists with a different request"
            )));
        }
        Ok(row)
    }

    /// Run exactly one step of an existing op and return the reloaded row;
    /// a terminal row is returned as-is. Skips the lease machinery — the
    /// lease is a throttle, not a lock (see the module docs), so a
    /// concurrent driver stays correct either way. This is the walkthrough
    /// entry point for tests and tooling that assert state between steps;
    /// `team_id` must match the op's.
    pub async fn step_once(
        &self,
        driver: &dyn OpDriver,
        op_id: Uuid,
        team_id: i64,
    ) -> Result<OpRow, SagaError> {
        let Some(row) = self.load(op_id).await? else {
            return Err(SagaError::CorruptState(format!(
                "op {op_id} does not exist"
            )));
        };
        if row.team_id != team_id {
            return Err(SagaError::RequestMismatch(format!(
                "op {op_id} belongs to a different team"
            )));
        }
        if row.completed_at.is_some() {
            return Ok(row);
        }
        driver.run_step(&self.pool, &row).await?;
        self.load(op_id).await?.ok_or_else(|| {
            SagaError::CorruptState(format!("op {op_id} vanished while being driven"))
        })
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
            if let Some(completed_at) = row.completed_at {
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
                    // Creation to terminal commit, so a sweeper-resumed op
                    // reports its full lifetime, not the last drive's.
                    common_metrics::histogram(
                        OP_DURATION_MS,
                        &[("op_type".to_string(), row.op_type.clone())],
                        (completed_at - row.created_at).num_milliseconds() as f64,
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
                None => {
                    // A live lease means the claim below cannot succeed, so
                    // don't issue it: claim attempts are writes, and a herd
                    // of pollers writing to a row its owner keeps renewing
                    // and advancing serializes on the row's tuple lock.
                    if row.lease_live {
                        if !wait_for_lease {
                            return Err(SagaError::Busy);
                        }
                        self.poll_pause().await;
                        continue;
                    }
                    match self.try_claim(op_id, wait_for_lease).await? {
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
                            self.poll_pause().await;
                            continue;
                        }
                    }
                }
            }

            if let Err(err) = driver.run_step(&self.pool, &row).await {
                // Attributable escalation: a persistently failing op (a
                // corrupt row, a wedged leader call) shows up as this
                // counter climbing for one op_type/kind, not as generic
                // retry noise. Alert on it — a wedged op can hold fences.
                let kind = match &err {
                    SagaError::Db(_) if err.is_db_conflict() => "db_conflict",
                    SagaError::Db(_) => "db",
                    SagaError::Leader(_) => "leader",
                    SagaError::LeaderRefused(_) => "leader_refused",
                    SagaError::CorruptState(_) => "corrupt_state",
                    // Not constructed by drivers; collapsed so dashboards
                    // never chase dead labels.
                    SagaError::RequestMismatch(_) | SagaError::Busy => "other",
                };
                common_metrics::inc(
                    STEP_FAILURES_TOTAL,
                    &[
                        ("op_type".to_string(), row.op_type.clone()),
                        ("kind".to_string(), kind.to_string()),
                    ],
                    1,
                );
                if err.is_db_conflict() {
                    // Concurrent multi-row writers (a writer flush, another
                    // saga) can deadlock or time out against a step's
                    // transaction; the loser rolls back whole and the step
                    // is safe to repeat. Keep the lease and re-drive after a
                    // pause instead of surfacing an error the caller would
                    // retry anyway; the execute deadline bounds the loop.
                    tracing::warn!(
                        op_id = %op_id,
                        op_type = %row.op_type,
                        step = %row.step,
                        error = %err,
                        detail = %err.db_detail().unwrap_or(""),
                        "lifecycle step lost a database conflict; retrying"
                    );
                    tokio::time::sleep(DB_CONFLICT_BACKOFF).await;
                    continue;
                }
                if let SagaError::LeaderRefused(status) = &err {
                    // Retrying a refusal cannot succeed, and the sweeper
                    // looping on it would hold this op's fences forever.
                    // Park it; only an explicit retry with the same op_id
                    // resumes a parked op.
                    if let Some(attempt) = claim_attempt {
                        match self.park(op_id, attempt, &row, status).await {
                            Ok(true) => {}
                            // The park lost its compare-and-swap: another
                            // driver claimed or completed the op, so this
                            // refusal is stale. Answer Busy, never a
                            // definitive refusal for an op that may yet
                            // complete.
                            Ok(false) => return Err(SagaError::Busy),
                            // Parking failed: drop the lease anyway; the
                            // sweeper will re-drive into the refusal and
                            // park then.
                            Err(_) => {
                                self.release_lease(op_id, attempt).await.ok();
                            }
                        }
                    }
                    return Err(err);
                }
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
                   request as "request: Value", outcome as "outcome: Value",
                   created_at, completed_at,
                   (lease_expires_at IS NOT NULL AND lease_expires_at >= now())
                       as "lease_live!"
            FROM lifecycle_op
            WHERE op_id = $1
            "#,
            op_id
        )
        .fetch_optional(&self.pool)
        .await
    }

    /// Sleep one poll interval, jittered to 0.5–1.5× so waiters released by
    /// the same lease event spread out instead of re-claiming in lockstep.
    async fn poll_pause(&self) {
        let jitter = rand::thread_rng().gen_range(0.5..1.5);
        tokio::time::sleep(self.config.poll_interval.mul_f64(jitter)).await;
    }

    /// Claim the op if its lease is free or lapsed. Returns the new attempt
    /// count on success, None when another instance holds a live lease.
    /// Only an explicit retry (`unpark`, the execute path) may claim a
    /// parked op; the sweeper cannot, even when a park lands after its
    /// scan.
    ///
    /// `SKIP LOCKED` keeps a claim from queueing behind whoever is writing
    /// the row right now (a renew, a step advance, a rival claim): the row
    /// being locked means the lease answer is about to change, so polling
    /// again beats joining a tuple-lock queue. A skipped row reads as None,
    /// the same as losing the claim outright.
    async fn try_claim(&self, op_id: Uuid, unpark: bool) -> Result<Option<i32>, sqlx::Error> {
        sqlx::query_scalar!(
            r#"
            UPDATE lifecycle_op
            SET lease_expires_at = now() + make_interval(secs => $2),
                attempt = attempt + 1,
                parked_at = NULL,
                parked_reason = NULL
            WHERE op_id IN (
                SELECT op_id FROM lifecycle_op
                WHERE op_id = $1 AND completed_at IS NULL
                  AND (lease_expires_at IS NULL OR lease_expires_at < now())
                  AND (parked_at IS NULL OR $3)
                FOR UPDATE SKIP LOCKED
            )
            RETURNING attempt
            "#,
            op_id,
            self.config.lease.as_secs_f64(),
            unpark,
        )
        .fetch_optional(&self.pool)
        .await
    }

    /// Park an op after a definitive leader refusal: record when and why,
    /// and drop the lease so an explicit retry need not wait it out.
    /// Guarded by `attempt` like renew/release, so a displaced driver
    /// cannot park a stealer's op. Returns whether the park won.
    async fn park(
        &self,
        op_id: Uuid,
        attempt: i32,
        row: &OpRow,
        status: &Status,
    ) -> Result<bool, sqlx::Error> {
        // The reason becomes a metric label; cap it so a misbehaving
        // peer cannot mint unbounded label cardinality.
        let reason = personhog_common::grpc::semantic_refusal_reason(status)
            .filter(|r| {
                r.len() <= 64
                    && r.chars()
                        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_'))
            })
            .unwrap_or("unknown")
            .to_string();
        let parked = sqlx::query!(
            r#"
            UPDATE lifecycle_op
            SET parked_at = now(), parked_reason = $3, lease_expires_at = NULL
            WHERE op_id = $1 AND completed_at IS NULL AND attempt = $2
            "#,
            op_id,
            attempt,
            reason,
        )
        .execute(&self.pool)
        .await?
        .rows_affected()
            > 0;
        if parked {
            tracing::error!(
                op_id = %op_id,
                op_type = %row.op_type,
                step = %row.step,
                reason = %reason,
                message = %status.message(),
                "leader definitively refused a lifecycle op step; op parked until explicitly retried"
            );
            common_metrics::inc(
                OPS_PARKED_TOTAL,
                &[
                    ("op_type".to_string(), row.op_type.clone()),
                    ("reason".to_string(), reason),
                ],
                1,
            );
        }
        Ok(parked)
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

    /// One sweeper pass: resume abandoned ops, meaning incomplete, not
    /// parked, and either with a lapsed lease or never claimed for longer
    /// than one lease (so a freshly created op isn't stolen from the RPC
    /// about to claim it). Returns how many ops reached a terminal step.
    pub async fn sweep(&self, drivers: &[&dyn OpDriver]) -> Result<u32, SagaError> {
        let abandoned = sqlx::query!(
            r#"
            SELECT op_id, op_type
            FROM lifecycle_op
            WHERE completed_at IS NULL
              AND parked_at IS NULL
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
                // Claimed by another driver (or parked) between our scan
                // and now, so it is no longer ours to drive.
                Err(SagaError::Busy) => {}
                Err(err @ SagaError::LeaderRefused(_)) => {
                    tracing::warn!(op_id = %op.op_id, error = %err,
                        "sweeper resume was definitively refused; op is parked until explicitly retried");
                }
                Err(err) => {
                    tracing::warn!(op_id = %op.op_id, error = %err,
                        "sweeper failed to resume op; will retry next pass");
                }
            }
        }

        // The park counter dies with the process, so a gauge refreshed
        // every pass keeps parked ops visible across restarts. Telemetry
        // only: a failure must not fail a pass whose resumes succeeded.
        match sqlx::query_scalar!(
            r#"SELECT count(*) AS "count!" FROM lifecycle_op WHERE completed_at IS NULL AND parked_at IS NOT NULL"#
        )
        .fetch_one(&self.pool)
        .await
        {
            Ok(parked) => common_metrics::gauge(OPS_PARKED, &[], parked as f64),
            Err(e) => tracing::warn!(error = %e, "failed to refresh the parked-ops gauge"),
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
