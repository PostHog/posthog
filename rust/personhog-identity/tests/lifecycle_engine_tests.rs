//! Engine tests against a dummy op type: the engine must be generic over op
//! types, so these drive a two-step fake op and assert the
//! create-or-attach, lease, CAS advance, recorded-outcome, and sweeper
//! behaviors that every op type shares.
//!
//! Isolation against the other test binaries sharing this database: the
//! dummy registers under 'merge' (the CHECK constraint allows nothing
//! else), which is safe because this file never sweeps. The suite's
//! single sweep test lives in lifecycle_merge_tests (where the sweeper
//! drives a real merge), and its one-hour-lease scan window cannot reach
//! this file's rows: every op this file inserts directly is live-leased,
//! fresh with a NULL lease, parked, or completed.

mod common;

use std::sync::atomic::{AtomicUsize, Ordering};

use async_trait::async_trait;
use common::TestContext;
use serde_json::json;
use sqlx::postgres::PgPool;
use uuid::Uuid;

use personhog_common::grpc::semantic_refusal;
use personhog_identity::lifecycle::engine::{
    advance_step_in_tx, complete_op_in_tx, OpDriver, OpRow, SagaError, STEP_COMPLETED,
};

/// Two-step dummy op: `started → half → completed`. Counts step executions
/// so tests can prove what did (or did not) re-run.
struct DummyDriver {
    steps_run: AtomicUsize,
}

impl DummyDriver {
    fn new() -> Self {
        Self {
            steps_run: AtomicUsize::new(0),
        }
    }
}

#[async_trait]
impl OpDriver for DummyDriver {
    fn op_type(&self) -> &'static str {
        "merge"
    }

    fn initial_step(&self) -> &'static str {
        "started"
    }

    async fn run_step(&self, pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
        self.steps_run.fetch_add(1, Ordering::SeqCst);
        let mut tx = pool.begin().await.map_err(SagaError::Db)?;
        let advanced = match op.step.as_str() {
            "started" => advance_step_in_tx(&mut tx, op.op_id, "started", "half").await?,
            "half" => {
                complete_op_in_tx(
                    &mut tx,
                    op.op_id,
                    "half",
                    STEP_COMPLETED,
                    &json!({"ok": true}),
                )
                .await?
            }
            other => {
                return Err(SagaError::CorruptState(format!("unknown step {other}")));
            }
        };
        if !advanced {
            tx.rollback().await.map_err(SagaError::Db)?;
            return Ok(());
        }
        tx.commit().await.map_err(SagaError::Db)?;
        Ok(())
    }
}

async fn parked_state(pool: &PgPool, op_id: Uuid) -> (bool, Option<String>) {
    let row: (Option<chrono::DateTime<chrono::Utc>>, Option<String>) =
        sqlx::query_as("SELECT parked_at, parked_reason FROM lifecycle_op WHERE op_id = $1")
            .bind(op_id)
            .fetch_one(pool)
            .await
            .expect("op row exists");
    (row.0.is_some(), row.1)
}

async fn op_row(ctx: &TestContext, op_id: Uuid) -> (String, i32, Option<serde_json::Value>, bool) {
    let row: (
        String,
        i32,
        Option<serde_json::Value>,
        Option<chrono::DateTime<chrono::Utc>>,
    ) = sqlx::query_as(
        "SELECT step, attempt, outcome, completed_at FROM lifecycle_op WHERE op_id = $1",
    )
    .bind(op_id)
    .fetch_one(&ctx.pool)
    .await
    .expect("op row exists");
    (row.0, row.1, row.2, row.3.is_some())
}

#[tokio::test]
async fn a_new_op_is_driven_to_completion_and_records_its_outcome() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = DummyDriver::new();
    let op_id = Uuid::now_v7();

    let row = engine
        .execute(&driver, op_id, ctx.team_id, &json!({"work": 1}))
        .await
        .expect("op completes");

    assert_eq!(row.step, STEP_COMPLETED);
    assert_eq!(row.outcome, Some(json!({"ok": true})));
    assert!(row.completed_at.is_some());
    assert_eq!(driver.steps_run.load(Ordering::SeqCst), 2);

    let (step, attempt, _, completed) = op_row(&ctx, op_id).await;
    assert_eq!(step, STEP_COMPLETED);
    assert_eq!(attempt, 1, "one claim by the driving call");
    assert!(completed);

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_retry_with_the_same_op_id_returns_the_recorded_outcome_without_rerunning() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = DummyDriver::new();
    let op_id = Uuid::now_v7();
    let request = json!({"work": 2});

    engine
        .execute(&driver, op_id, ctx.team_id, &request)
        .await
        .expect("op completes");
    let steps_after_first = driver.steps_run.load(Ordering::SeqCst);

    let row = engine
        .execute(&driver, op_id, ctx.team_id, &request)
        .await
        .expect("retry attaches");

    assert_eq!(row.outcome, Some(json!({"ok": true})));
    assert_eq!(
        driver.steps_run.load(Ordering::SeqCst),
        steps_after_first,
        "a completed op never re-runs"
    );

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn an_op_id_reused_with_a_different_request_is_rejected() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = DummyDriver::new();
    let op_id = Uuid::now_v7();

    engine
        .execute(&driver, op_id, ctx.team_id, &json!({"work": 3}))
        .await
        .expect("op completes");

    let err = engine
        .execute(&driver, op_id, ctx.team_id, &json!({"work": 999}))
        .await
        .expect_err("different request must not attach");
    assert!(matches!(err, SagaError::RequestMismatch(_)));

    let err = engine
        .execute(&driver, op_id, ctx.team_id + 1, &json!({"work": 3}))
        .await
        .expect_err("different team must not attach");
    assert!(matches!(err, SagaError::RequestMismatch(_)));

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_first_call_is_not_compared_against_its_own_normalized_insert() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = DummyDriver::new();
    let op_id = Uuid::now_v7();

    // Postgres renders 1e17 back as an integer, so the reloaded row never
    // equals this request value-for-value. The call that won the insert
    // owns the row by construction and must not verify against its own
    // jsonb-normalized copy.
    let row = engine
        .execute(&driver, op_id, ctx.team_id, &json!({"count": 1e17}))
        .await
        .expect("the inserting call is never a request mismatch");
    assert_eq!(row.step, STEP_COMPLETED);

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn resume_picks_up_an_op_from_its_saved_step() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = DummyDriver::new();
    let op_id = Uuid::now_v7();

    // An op abandoned mid-flight: past its first step, lease released by
    // the crashed driver's error path (NULL, not expired — an expired
    // lease would make this row claimable by the sweep test's engine).
    sqlx::query(
        r#"
        INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request)
        VALUES ($1, 'merge', $2, 'half', '{}'::jsonb)
        "#,
    )
    .bind(op_id)
    .bind(ctx.team_id as i32)
    .execute(&ctx.pool)
    .await
    .expect("insert abandoned op");

    let row = engine
        .resume(&driver, op_id)
        .await
        .expect("resume completes");

    assert_eq!(row.step, STEP_COMPLETED);
    assert_eq!(
        driver.steps_run.load(Ordering::SeqCst),
        1,
        "only the remaining step runs"
    );

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn gc_reaps_completed_ops_past_retention() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = DummyDriver::new();
    let op_id = Uuid::now_v7();

    engine
        .execute(&driver, op_id, ctx.team_id, &json!({}))
        .await
        .expect("op completes");

    // Backdate the completion past retention; GC reaps it (and cascades the
    // per-person rows) without touching other tests' fresh rows.
    sqlx::query(
        "UPDATE lifecycle_op SET completed_at = now() - interval '2 hours' WHERE op_id = $1",
    )
    .bind(op_id)
    .execute(&ctx.pool)
    .await
    .expect("backdate completion");
    engine
        .gc(std::time::Duration::from_secs(3600))
        .await
        .expect("gc runs");
    let gone: Option<(String,)> = sqlx::query_as("SELECT step FROM lifecycle_op WHERE op_id = $1")
        .bind(op_id)
        .fetch_optional(&ctx.pool)
        .await
        .expect("query runs");
    assert!(gone.is_none(), "completed op past retention is deleted");

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_live_lease_blocks_a_second_driver_until_it_lapses() {
    let ctx = TestContext::new().await;
    let driver = DummyDriver::new();
    let op_id = Uuid::now_v7();

    // Held by "another instance" for longer than the test engine's execute
    // timeout would wait — but we assert Busy well before that.
    sqlx::query(
        r#"
        INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request, lease_expires_at)
        VALUES ($1, 'merge', $2, 'started', '{}'::jsonb, now() + interval '1 hour')
        "#,
    )
    .bind(op_id)
    .bind(ctx.team_id as i32)
    .execute(&ctx.pool)
    .await
    .expect("insert leased op");

    let short_engine = personhog_identity::lifecycle::engine::Engine::new(
        ctx.pool.clone(),
        personhog_identity::lifecycle::engine::EngineConfig {
            lease: std::time::Duration::from_secs(5),
            execute_timeout: std::time::Duration::from_millis(200),
            poll_interval: std::time::Duration::from_millis(25),
            attempt_alert_threshold: 5,
        },
    );
    let err = short_engine
        .execute(&driver, op_id, ctx.team_id, &json!({}))
        .await
        .expect_err("cannot steal a live lease");
    assert!(matches!(err, SagaError::Busy));
    assert_eq!(
        driver.steps_run.load(Ordering::SeqCst),
        0,
        "no step ran while another instance held the lease"
    );

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn resume_bails_immediately_when_another_driver_holds_the_lease() {
    let ctx = TestContext::new().await;
    // The default test engine's 10s execute timeout: a resume that waits
    // out a live lease instead of bailing would blow the elapsed assertion.
    let engine = ctx.engine();
    let driver = DummyDriver::new();
    let op_id = Uuid::now_v7();

    sqlx::query(
        r#"
        INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request, lease_expires_at)
        VALUES ($1, 'merge', $2, 'started', '{}'::jsonb, now() + interval '1 hour')
        "#,
    )
    .bind(op_id)
    .bind(ctx.team_id as i32)
    .execute(&ctx.pool)
    .await
    .expect("insert leased op");

    let started = std::time::Instant::now();
    let err = engine
        .resume(&driver, op_id)
        .await
        .expect_err("live lease means not abandoned");

    assert!(matches!(err, SagaError::Busy));
    assert_eq!(driver.steps_run.load(Ordering::SeqCst), 0);
    assert!(
        started.elapsed() < std::time::Duration::from_secs(5),
        "resume must skip a live lease, not poll out the execute timeout"
    );

    ctx.cleanup().await.expect("cleanup");
}

/// Simulates another instance stealing the op mid-step: bumps `attempt` and
/// takes a one-hour lease, exactly what a concurrent `try_claim` does.
async fn steal_lease(pool: &PgPool, op_id: Uuid) {
    sqlx::query(
        "UPDATE lifecycle_op SET attempt = attempt + 1, lease_expires_at = now() + interval '1 hour' WHERE op_id = $1",
    )
    .bind(op_id)
    .execute(pool)
    .await
    .expect("steal lease");
}

async fn lease_is_live(pool: &PgPool, op_id: Uuid) -> bool {
    sqlx::query_scalar("SELECT lease_expires_at > now() FROM lifecycle_op WHERE op_id = $1")
        .bind(op_id)
        .fetch_one(pool)
        .await
        .ok()
        .flatten()
        .unwrap_or(false)
}

/// Driver whose first step gets its lease stolen mid-run. `fail_after_steal`
/// picks the exit: Err exercises the engine's release path, Ok without
/// advancing (a lost CAS) exercises the renew path.
struct StolenLeaseDriver {
    steps_run: AtomicUsize,
    fail_after_steal: bool,
}

#[async_trait]
impl OpDriver for StolenLeaseDriver {
    fn op_type(&self) -> &'static str {
        "merge"
    }

    fn initial_step(&self) -> &'static str {
        "started"
    }

    async fn run_step(&self, pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
        self.steps_run.fetch_add(1, Ordering::SeqCst);
        steal_lease(pool, op.op_id).await;
        if self.fail_after_steal {
            Err(SagaError::CorruptState("simulated step failure".into()))
        } else {
            Ok(())
        }
    }
}

#[tokio::test]
async fn a_driver_whose_lease_was_stolen_stops_running_steps_instead_of_renewing() {
    let ctx = TestContext::new().await;
    let driver = StolenLeaseDriver {
        steps_run: AtomicUsize::new(0),
        fail_after_steal: false,
    };
    let op_id = Uuid::now_v7();

    let short_engine = personhog_identity::lifecycle::engine::Engine::new(
        ctx.pool.clone(),
        personhog_identity::lifecycle::engine::EngineConfig {
            lease: std::time::Duration::from_secs(5),
            execute_timeout: std::time::Duration::from_millis(200),
            poll_interval: std::time::Duration::from_millis(25),
            attempt_alert_threshold: 5,
        },
    );
    let err = short_engine
        .execute(&driver, op_id, ctx.team_id, &json!({}))
        .await
        .expect_err("waits on the stealer's lease until the deadline");

    assert!(matches!(err, SagaError::Busy));
    assert_eq!(
        driver.steps_run.load(Ordering::SeqCst),
        1,
        "no step ran after the lease was stolen"
    );
    assert!(
        lease_is_live(&ctx.pool, op_id).await,
        "the displaced driver must not have renewed or cleared the stealer's lease"
    );

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_failing_driver_whose_lease_was_stolen_does_not_release_the_stealers_lease() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = StolenLeaseDriver {
        steps_run: AtomicUsize::new(0),
        fail_after_steal: true,
    };
    let op_id = Uuid::now_v7();

    let err = engine
        .execute(&driver, op_id, ctx.team_id, &json!({}))
        .await
        .expect_err("step failure propagates");

    assert!(matches!(err, SagaError::CorruptState(_)));
    assert!(
        lease_is_live(&ctx.pool, op_id).await,
        "the stale driver's error-path release must not clear the stealer's lease"
    );

    ctx.cleanup().await.expect("cleanup");
}

/// Refuses its first `refusals` steps with a definitive leader refusal
/// (a semantic refusal, as classified by `SagaError::leader`), then
/// completes in one step.
struct RefusingDriver {
    refusals_left: AtomicUsize,
    steps_run: AtomicUsize,
}

impl RefusingDriver {
    fn new(refusals: usize) -> Self {
        Self {
            refusals_left: AtomicUsize::new(refusals),
            steps_run: AtomicUsize::new(0),
        }
    }
}

#[async_trait]
impl OpDriver for RefusingDriver {
    fn op_type(&self) -> &'static str {
        "merge"
    }

    fn initial_step(&self) -> &'static str {
        "started"
    }

    async fn run_step(&self, pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
        self.steps_run.fetch_add(1, Ordering::SeqCst);
        if self
            .refusals_left
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |n| n.checked_sub(1))
            .is_ok()
        {
            return Err(SagaError::leader(semantic_refusal(
                "injected refusal",
                "test-refusal",
            )));
        }
        let mut tx = pool.begin().await.map_err(SagaError::Db)?;
        let advanced =
            complete_op_in_tx(&mut tx, op.op_id, "started", STEP_COMPLETED, &json!({})).await?;
        if !advanced {
            tx.rollback().await.map_err(SagaError::Db)?;
            return Ok(());
        }
        tx.commit().await.map_err(SagaError::Db)?;
        Ok(())
    }
}

#[tokio::test]
async fn a_definitive_leader_refusal_parks_the_op() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = RefusingDriver::new(1);
    let op_id = Uuid::now_v7();

    let err = engine
        .execute(&driver, op_id, ctx.team_id, &json!({}))
        .await
        .expect_err("the refusal surfaces");
    assert!(matches!(err, SagaError::LeaderRefused(_)));

    let (parked, reason) = parked_state(&ctx.pool, op_id).await;
    assert!(parked, "a refused op is parked, not left for the sweeper");
    assert_eq!(reason.as_deref(), Some("test-refusal"));
    assert!(
        !lease_is_live(&ctx.pool, op_id).await,
        "parking drops the lease so an explicit retry need not wait it out"
    );
    let (step, _, _, completed) = op_row(&ctx, op_id).await;
    assert_eq!(step, "started", "the refused step made no progress");
    assert!(!completed);

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn an_explicit_retry_with_the_same_op_id_unparks_and_redrives() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = RefusingDriver::new(1);
    let op_id = Uuid::now_v7();

    engine
        .execute(&driver, op_id, ctx.team_id, &json!({}))
        .await
        .expect_err("first attempt is refused and parks");

    // The driver no longer refuses: an explicit retry with the same
    // op_id claims, un-parks, and completes.
    let row = engine
        .execute(&driver, op_id, ctx.team_id, &json!({}))
        .await
        .expect("explicit retry completes the parked op");
    assert_eq!(row.step, STEP_COMPLETED);

    let (parked, reason) = parked_state(&ctx.pool, op_id).await;
    assert!(!parked, "claiming un-parks");
    assert_eq!(reason, None);
    assert_eq!(driver.steps_run.load(Ordering::SeqCst), 2);

    ctx.cleanup().await.expect("cleanup");
}

/// Steals the lease mid-step, then returns a definitive refusal: the
/// displaced driver's park must lose the `attempt` compare-and-swap.
struct StolenLeaseRefusingDriver;

#[async_trait]
impl OpDriver for StolenLeaseRefusingDriver {
    fn op_type(&self) -> &'static str {
        "merge"
    }

    fn initial_step(&self) -> &'static str {
        "started"
    }

    async fn run_step(&self, pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
        steal_lease(pool, op.op_id).await;
        Err(SagaError::leader(semantic_refusal(
            "injected refusal",
            "test-refusal",
        )))
    }
}

#[tokio::test]
async fn a_displaced_drivers_refusal_does_not_park_the_stealers_op() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let op_id = Uuid::now_v7();

    let err = engine
        .execute(&StolenLeaseRefusingDriver, op_id, ctx.team_id, &json!({}))
        .await
        .expect_err("the displaced driver cannot answer for the op");
    // Not the refusal: the stealer may re-drive the step against fresh
    // state and complete the op, so a displaced driver's refusal is
    // stale; the caller gets the retriable answer.
    assert!(matches!(err, SagaError::Busy));

    let (parked, _) = parked_state(&ctx.pool, op_id).await;
    assert!(
        !parked,
        "a displaced driver must not park an op another driver is actively driving"
    );
    assert!(
        lease_is_live(&ctx.pool, op_id).await,
        "the stealer's lease survives the displaced driver's park attempt"
    );

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn step_once_rejects_a_foreign_teams_op() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = DummyDriver::new();
    let op_id = Uuid::now_v7();

    engine
        .create_or_attach(&driver, op_id, ctx.team_id, &json!({}))
        .await
        .expect("create op");

    let err = engine
        .step_once(&driver, op_id, ctx.team_id + 1)
        .await
        .expect_err("a mismatched team cannot drive the op");
    assert!(matches!(err, SagaError::RequestMismatch(_)));
    assert_eq!(driver.steps_run.load(Ordering::SeqCst), 0);

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn resume_does_not_unpark() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = RefusingDriver::new(1);
    let op_id = Uuid::now_v7();

    engine
        .execute(&driver, op_id, ctx.team_id, &json!({}))
        .await
        .expect_err("first attempt is refused and parks");

    // The sweeper's entry point must not claim and un-park a parked op,
    // even reaching it directly as a scan-then-park race would; that
    // signal is reserved for an explicit retry.
    let err = engine
        .resume(&driver, op_id)
        .await
        .expect_err("resume cannot claim a parked op");
    assert!(matches!(err, SagaError::Busy));
    let (parked, _) = parked_state(&ctx.pool, op_id).await;
    assert!(parked, "the op stays parked");
    assert_eq!(
        driver.steps_run.load(Ordering::SeqCst),
        1,
        "resume ran no step"
    );

    ctx.cleanup().await.expect("cleanup");
}

/// A concocted Postgres error carrying just a SQLSTATE, so tests can hand
/// the engine the exact errors Postgres emits for lock conflicts without
/// manufacturing a real deadlock.
#[derive(Debug)]
struct FakePgError(&'static str);

impl std::fmt::Display for FakePgError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "fake database error ({})", self.0)
    }
}

impl std::error::Error for FakePgError {}

impl sqlx::error::DatabaseError for FakePgError {
    fn message(&self) -> &str {
        "fake database error"
    }

    fn code(&self) -> Option<std::borrow::Cow<'_, str>> {
        Some(std::borrow::Cow::Borrowed(self.0))
    }

    fn as_error(&self) -> &(dyn std::error::Error + Send + Sync + 'static) {
        self
    }

    fn as_error_mut(&mut self) -> &mut (dyn std::error::Error + Send + Sync + 'static) {
        self
    }

    fn into_error(self: Box<Self>) -> Box<dyn std::error::Error + Send + Sync + 'static> {
        self
    }

    fn kind(&self) -> sqlx::error::ErrorKind {
        sqlx::error::ErrorKind::Other
    }
}

fn db_error(code: &'static str) -> SagaError {
    SagaError::Db(sqlx::Error::Database(Box::new(FakePgError(code))))
}

#[test]
fn database_conflicts_classify_as_retriable() {
    for code in ["40P01", "40001", "57014"] {
        assert!(db_error(code).is_db_conflict(), "{code} must be a conflict");
    }
    assert!(
        !db_error("23505").is_db_conflict(),
        "a unique violation is not a conflict"
    );
    assert!(!SagaError::Busy.is_db_conflict());
}

/// Driver whose first attempts lose a deadlock; every later attempt
/// behaves like [`DummyDriver`]. Failing more than once exercises the
/// repeated backoff-and-renew passes of the retry loop, not just the
/// first.
struct DeadlockingDriver {
    inner: DummyDriver,
    fail_first: usize,
    attempts: AtomicUsize,
}

#[async_trait]
impl OpDriver for DeadlockingDriver {
    fn op_type(&self) -> &'static str {
        "merge"
    }

    fn initial_step(&self) -> &'static str {
        "started"
    }

    async fn run_step(&self, pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
        if self.attempts.fetch_add(1, Ordering::SeqCst) < self.fail_first {
            return Err(db_error("40P01"));
        }
        self.inner.run_step(pool, op).await
    }
}

#[tokio::test]
async fn a_step_that_loses_a_database_conflict_is_retried_not_surfaced() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = DeadlockingDriver {
        inner: DummyDriver::new(),
        fail_first: 3,
        attempts: AtomicUsize::new(0),
    };
    let op_id = Uuid::now_v7();

    let row = engine
        .execute(&driver, op_id, ctx.team_id, &json!({"work": 1}))
        .await
        .expect("the conflict is retried inside the engine, not surfaced");

    assert_eq!(row.step, STEP_COMPLETED);
    assert_eq!(
        driver.inner.steps_run.load(Ordering::SeqCst),
        2,
        "both real steps ran after the deadlocked attempts"
    );
    let (_, attempt, _, completed) = op_row(&ctx, op_id).await;
    assert!(completed);
    assert_eq!(attempt, 1, "the retry re-drives under the original claim");

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_claim_skips_a_row_a_concurrent_writer_holds_instead_of_queueing() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = DummyDriver::new();
    let op_id = Uuid::now_v7();

    // Created but not driven: the lease is free, so only the row lock below
    // stands between resume and a successful claim.
    engine
        .create_or_attach(&driver, op_id, ctx.team_id, &json!({"work": 7}))
        .await
        .expect("create");

    // Hold the row lock the way any concurrent writer would (a renew, a
    // step advance, a rival claim mid-flight).
    let mut tx = ctx.pool.begin().await.expect("begin");
    sqlx::query("SELECT 1 FROM lifecycle_op WHERE op_id = $1 FOR UPDATE")
        .bind(op_id)
        .execute(&mut *tx)
        .await
        .expect("lock the op row");

    // The claim must answer Busy promptly rather than queueing on the tuple
    // until the lock holder commits.
    let result = tokio::time::timeout(
        std::time::Duration::from_secs(5),
        engine.resume(&driver, op_id),
    )
    .await
    .expect("resume must not wait out a concurrent writer's row lock");
    assert!(matches!(result, Err(SagaError::Busy)));
    assert_eq!(driver.steps_run.load(Ordering::SeqCst), 0);

    tx.rollback().await.expect("rollback");
    ctx.cleanup().await.expect("cleanup");
}
