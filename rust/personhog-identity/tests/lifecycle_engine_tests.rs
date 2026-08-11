//! Engine tests against a dummy op type: the engine must be generic over op
//! types, so these drive a two-step fake op (registered under 'merge', the
//! other op_type the schema's CHECK constraint allows — the real merge
//! driver does not exist yet) and assert the create-or-attach, lease, CAS
//! advance, recorded-outcome, and sweeper behaviors that every op type
//! shares.

mod common;

use std::sync::atomic::{AtomicUsize, Ordering};

use async_trait::async_trait;
use common::TestContext;
use serde_json::json;
use sqlx::postgres::PgPool;
use uuid::Uuid;

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
async fn resume_picks_up_an_op_from_its_saved_step() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = DummyDriver::new();
    let op_id = Uuid::now_v7();

    // An op abandoned mid-flight: past its first step, lease lapsed.
    sqlx::query(
        r#"
        INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request, lease_expires_at)
        VALUES ($1, 'merge', $2, 'half', '{}'::jsonb, now() - interval '1 minute')
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
async fn the_sweeper_resumes_abandoned_ops_and_gc_reaps_completed_ones() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = DummyDriver::new();
    let op_id = Uuid::now_v7();

    sqlx::query(
        r#"
        INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request, lease_expires_at)
        VALUES ($1, 'merge', $2, 'started', '{}'::jsonb, now() - interval '1 minute')
        "#,
    )
    .bind(op_id)
    .bind(ctx.team_id as i32)
    .execute(&ctx.pool)
    .await
    .expect("insert abandoned op");

    let resumed = engine.sweep(&[&driver]).await.expect("sweep runs");
    assert!(resumed >= 1, "the abandoned op was resumed");
    let (step, _, _, completed) = op_row(&ctx, op_id).await;
    assert_eq!(step, STEP_COMPLETED);
    assert!(completed);

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
