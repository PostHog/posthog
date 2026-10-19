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
use personhog_identity::config::OutboxWrites;
use personhog_identity::lifecycle::detach::DetachedDrives;
use personhog_identity::lifecycle::engine::{
    abort_op_in_tx, advance_step_in_tx, complete_op_in_tx, OpDriver, OpRow, SagaError,
    STEP_ABORTED, STEP_COMPLETED,
};
use personhog_identity::pools::IdentityPools;

/// Two-step dummy op: `started → half → <final step>`. Counts step
/// executions so tests can prove what did (or did not) re-run.
struct DummyDriver {
    steps_run: AtomicUsize,
    pause: std::time::Duration,
    final_step: &'static str,
    outbox_writes: OutboxWrites,
}

impl DummyDriver {
    fn new() -> Self {
        Self::with(
            std::time::Duration::ZERO,
            STEP_COMPLETED,
            OutboxWrites::Disabled,
        )
    }

    fn paced(pause: std::time::Duration) -> Self {
        Self::with(pause, STEP_COMPLETED, OutboxWrites::Disabled)
    }

    fn settling(final_step: &'static str, outbox_writes: OutboxWrites) -> Self {
        Self::with(std::time::Duration::ZERO, final_step, outbox_writes)
    }

    fn with(
        pause: std::time::Duration,
        final_step: &'static str,
        outbox_writes: OutboxWrites,
    ) -> Self {
        Self {
            steps_run: AtomicUsize::new(0),
            pause,
            final_step,
            outbox_writes,
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

    async fn run_step(&self, pools: &IdentityPools, op: &OpRow) -> Result<(), SagaError> {
        self.steps_run.fetch_add(1, Ordering::SeqCst);
        tokio::time::sleep(self.pause).await;
        let mut tx = pools.heavy().begin().await.map_err(SagaError::Db)?;
        let advanced = match op.step.as_str() {
            "started" => {
                advance_step_in_tx(
                    &mut tx,
                    &common::default_tables(),
                    op.op_id,
                    "started",
                    "half",
                )
                .await?
            }
            "half" if self.final_step == STEP_COMPLETED => {
                complete_op_in_tx(
                    &mut tx,
                    &common::default_tables(),
                    op.op_id,
                    "half",
                    &json!({"ok": true}),
                    self.outbox_writes,
                )
                .await?
            }
            "half" => {
                abort_op_in_tx(
                    &mut tx,
                    &common::default_tables(),
                    op.op_id,
                    "half",
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

async fn pointer_kinds(ctx: &TestContext, op_id: Uuid) -> Vec<String> {
    sqlx::query_scalar("SELECT kind FROM person_publish_outbox WHERE op_id = $1")
        .bind(op_id)
        .fetch_all(&ctx.pool)
        .await
        .expect("query runs")
}

#[tokio::test]
async fn only_a_completed_op_with_outbox_writes_enabled_enqueues_a_publish_pointer() {
    let ctx = TestContext::new().await;
    // The pointers this test asserts on are pending rows a draining test
    // in another process would otherwise claim and delete.
    let _drain_lock = ctx.hold_drain_lock().await;
    let engine = ctx.engine();
    let cases = [
        (
            OutboxWrites::Enabled,
            STEP_COMPLETED,
            vec!["merge_op".to_string()],
        ),
        (OutboxWrites::Enabled, STEP_ABORTED, vec![]),
        (OutboxWrites::Disabled, STEP_COMPLETED, vec![]),
    ];
    for (outbox_writes, final_step, expected) in cases {
        let driver = DummyDriver::settling(final_step, outbox_writes);
        let op_id = Uuid::now_v7();
        engine
            .execute(&driver, op_id, ctx.team_id, &json!({}))
            .await
            .expect("op settles");
        assert_eq!(
            pointer_kinds(&ctx, op_id).await,
            expected,
            "{outbox_writes:?} {final_step}"
        );
    }

    // The pointer rides the compare-and-swap: a completion that loses it
    // (the row is not on `from`) commits nothing, pointer included.
    let driver = DummyDriver::settling(STEP_COMPLETED, OutboxWrites::Enabled);
    let op_id = Uuid::now_v7();
    engine
        .create_or_attach(&driver, op_id, ctx.team_id, &json!({}))
        .await
        .expect("op created");
    let mut tx = ctx.pool.begin().await.expect("begin");
    let advanced = complete_op_in_tx(
        &mut tx,
        &common::default_tables(),
        op_id,
        "half",
        &json!({}),
        OutboxWrites::Enabled,
    )
    .await
    .expect("statement runs");
    tx.commit().await.expect("commit");
    assert!(!advanced, "the row is on 'started', not 'half'");
    assert!(pointer_kinds(&ctx, op_id).await.is_empty());

    ctx.cleanup().await.expect("cleanup");
}

async fn remaining_ops(ctx: &TestContext, op_ids: &[Uuid]) -> Vec<Uuid> {
    sqlx::query_scalar("SELECT op_id FROM lifecycle_op WHERE op_id = ANY($1) ORDER BY op_id")
        .bind(op_ids)
        .fetch_all(&ctx.pool)
        .await
        .expect("query runs")
}

#[tokio::test]
async fn gc_reaps_completed_ops_past_retention_unless_a_publish_pointer_remains() {
    let ctx = TestContext::new().await;
    // The pending pointer must survive until GC has seen it, so no
    // draining test in another process may claim it meanwhile.
    let _drain_lock = ctx.hold_drain_lock().await;
    let engine = ctx.engine();
    let driver = DummyDriver::new();
    // Three completed ops: no outbox row, a pending pointer, a given-up pointer.
    let plain = Uuid::now_v7();
    let pending = Uuid::now_v7();
    let given_up = Uuid::now_v7();
    let all = [plain, pending, given_up];

    for op_id in all {
        engine
            .execute(&driver, op_id, ctx.team_id, &json!({}))
            .await
            .expect("op completes");
    }
    sqlx::query(
        r#"
        INSERT INTO person_publish_outbox (team_id, kind, op_id, given_up_at, last_error)
        VALUES ($1, 'merge_op', $2, NULL, NULL), ($1, 'merge_op', $3, now(), 'poison')
        "#,
    )
    .bind(ctx.team_id as i32)
    .bind(pending)
    .bind(given_up)
    .execute(&ctx.pool)
    .await
    .expect("queue pointers");

    // Backdate the completions past retention; GC reaps only the op nobody
    // still has to publish, and cascades its per-person rows, without
    // touching other tests' fresh rows.
    sqlx::query(
        "UPDATE lifecycle_op SET completed_at = now() - interval '2 hours' WHERE op_id = ANY($1)",
    )
    .bind(&all[..])
    .execute(&ctx.pool)
    .await
    .expect("backdate completions");
    engine
        .gc(std::time::Duration::from_secs(3600))
        .await
        .expect("gc runs");
    assert_eq!(
        remaining_ops(&ctx, &all).await,
        vec![pending, given_up],
        "ops with a pointer survive, the plain op is deleted"
    );

    // Once the pointers are gone (published, or cleared by an operator), the
    // next pass reaps the ops.
    sqlx::query("DELETE FROM person_publish_outbox WHERE op_id = ANY($1)")
        .bind(&all[..])
        .execute(&ctx.pool)
        .await
        .expect("clear pointers");
    engine
        .gc(std::time::Duration::from_secs(3600))
        .await
        .expect("gc runs");
    assert!(remaining_ops(&ctx, &all).await.is_empty());

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
        ctx.pools.clone(),
        personhog_identity::lifecycle::engine::EngineConfig {
            lease: std::time::Duration::from_secs(5),
            execute_timeout: std::time::Duration::from_millis(200),
            poll_interval: std::time::Duration::from_millis(25),
            attempt_alert_threshold: 5,
            gc_batch_limit: 10_000,
        },
        ctx.tables.clone(),
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

/// Sleeps through the execute deadline without ever advancing, modeling
/// a wedged step under a held claim.
struct SlowDriver;

#[async_trait]
impl OpDriver for SlowDriver {
    fn op_type(&self) -> &'static str {
        "merge"
    }

    fn initial_step(&self) -> &'static str {
        "started"
    }

    async fn run_step(&self, _pools: &IdentityPools, _op: &OpRow) -> Result<(), SagaError> {
        tokio::time::sleep(std::time::Duration::from_millis(400)).await;
        Ok(())
    }
}

#[tokio::test]
async fn a_drive_that_runs_out_its_own_deadline_says_so_and_releases_the_lease() {
    let ctx = TestContext::new().await;
    let op_id = Uuid::now_v7();

    let short_engine = personhog_identity::lifecycle::engine::Engine::new(
        ctx.pools.clone(),
        personhog_identity::lifecycle::engine::EngineConfig {
            lease: std::time::Duration::from_secs(5),
            execute_timeout: std::time::Duration::from_millis(200),
            poll_interval: std::time::Duration::from_millis(25),
            attempt_alert_threshold: 5,
            gc_batch_limit: 10_000,
        },
        ctx.tables.clone(),
    );

    // The claim was ours the whole time, so the answer must not blame a
    // contending instance that does not exist; and the lease releases so
    // the retry is not locked out for a lease term on top.
    let err = short_engine
        .execute(&SlowDriver, op_id, ctx.team_id, &json!({}))
        .await
        .expect_err("the slow drive runs out its deadline");
    assert!(matches!(err, SagaError::DeadlineElapsed));
    let lease_live: bool = sqlx::query_scalar(
        "SELECT lease_expires_at IS NOT NULL AND lease_expires_at >= now() FROM lifecycle_op WHERE op_id = $1",
    )
    .bind(op_id)
    .fetch_one(&ctx.pool)
    .await
    .expect("op row exists");
    assert!(!lease_live, "the deadline return released the lease");

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
/// advancing (a lost CAS) exercises the attempt check on the reloaded row.
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

    async fn run_step(&self, pools: &IdentityPools, op: &OpRow) -> Result<(), SagaError> {
        self.steps_run.fetch_add(1, Ordering::SeqCst);
        steal_lease(pools.fast(), op.op_id).await;
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
        ctx.pools.clone(),
        personhog_identity::lifecycle::engine::EngineConfig {
            lease: std::time::Duration::from_secs(5),
            execute_timeout: std::time::Duration::from_millis(200),
            poll_interval: std::time::Duration::from_millis(25),
            attempt_alert_threshold: 5,
            gc_batch_limit: 10_000,
        },
        ctx.tables.clone(),
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

/// The two-step dummy op, recording the op's lease expiry as each step
/// starts and pausing its first step for `first_step_pause`.
struct LeaseRecordingDriver {
    inner: DummyDriver,
    first_step_pause: std::time::Duration,
    expiries: std::sync::Mutex<Vec<chrono::DateTime<chrono::Utc>>>,
}

#[async_trait]
impl OpDriver for LeaseRecordingDriver {
    fn op_type(&self) -> &'static str {
        "merge"
    }

    fn initial_step(&self) -> &'static str {
        "started"
    }

    async fn run_step(&self, pools: &IdentityPools, op: &OpRow) -> Result<(), SagaError> {
        let expiry: chrono::DateTime<chrono::Utc> =
            sqlx::query_scalar("SELECT lease_expires_at FROM lifecycle_op WHERE op_id = $1")
                .bind(op.op_id)
                .fetch_one(pools.fast())
                .await
                .map_err(SagaError::Db)?;
        self.expiries.lock().unwrap().push(expiry);
        if op.step == "started" {
            tokio::time::sleep(self.first_step_pause).await;
        }
        self.inner.run_step(pools, op).await
    }
}

/// Lease expiries seen by the dummy op's two steps under a `lease`-long lease.
async fn step_lease_expiries(
    ctx: &TestContext,
    lease: std::time::Duration,
    first_step_pause: std::time::Duration,
) -> Vec<chrono::DateTime<chrono::Utc>> {
    let driver = LeaseRecordingDriver {
        inner: DummyDriver::new(),
        first_step_pause,
        expiries: std::sync::Mutex::new(Vec::new()),
    };
    let engine = personhog_identity::lifecycle::engine::Engine::new(
        ctx.pools.clone(),
        personhog_identity::lifecycle::engine::EngineConfig {
            lease,
            execute_timeout: std::time::Duration::from_secs(10),
            poll_interval: std::time::Duration::from_millis(25),
            attempt_alert_threshold: 5,
            gc_batch_limit: 10_000,
        },
        ctx.tables.clone(),
    );
    engine
        .execute(&driver, Uuid::now_v7(), ctx.team_id, &json!({}))
        .await
        .expect("the op completes");
    assert_eq!(driver.inner.steps_run.load(Ordering::SeqCst), 2);
    driver.expiries.into_inner().unwrap()
}

#[tokio::test]
async fn steps_that_finish_inside_a_third_of_the_lease_run_on_the_claim_without_renewing() {
    let ctx = TestContext::new().await;

    let expiries = step_lease_expiries(
        &ctx,
        std::time::Duration::from_secs(30),
        std::time::Duration::ZERO,
    )
    .await;

    assert_eq!(
        expiries[0], expiries[1],
        "the second step ran on the claim's lease"
    );

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_step_that_starts_after_a_third_of_the_lease_renews_it_first() {
    let ctx = TestContext::new().await;

    let expiries = step_lease_expiries(
        &ctx,
        std::time::Duration::from_secs(3),
        std::time::Duration::from_millis(1_200),
    )
    .await;

    assert!(
        expiries[1] > expiries[0],
        "the second step ran on a renewed lease"
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

    async fn run_step(&self, pools: &IdentityPools, op: &OpRow) -> Result<(), SagaError> {
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
        let mut tx = pools.heavy().begin().await.map_err(SagaError::Db)?;
        let advanced = complete_op_in_tx(
            &mut tx,
            &common::default_tables(),
            op.op_id,
            "started",
            &json!({}),
            OutboxWrites::Disabled,
        )
        .await?;
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

    async fn run_step(&self, pools: &IdentityPools, op: &OpRow) -> Result<(), SagaError> {
        steal_lease(pools.fast(), op.op_id).await;
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

fn connection_lost() -> SagaError {
    SagaError::Db(sqlx::Error::Io(std::io::Error::new(
        std::io::ErrorKind::UnexpectedEof,
        "expected to read 5 bytes, got 0 bytes at EOF",
    )))
}

#[test]
fn lost_connections_classify_as_retriable_and_unavailable() {
    for err in [
        connection_lost(),
        db_error("08006"),
        db_error("57P01"),
        db_error("57P02"),
    ] {
        assert!(
            err.is_db_connection_lost(),
            "{err} must be a lost connection"
        );
        assert!(!err.is_db_conflict());
        assert_eq!(tonic::Status::from(err).code(), tonic::Code::Unavailable);
    }
    for err in [db_error("23505"), db_error("40P01"), SagaError::Busy] {
        assert!(
            !err.is_db_connection_lost(),
            "{err} is not a lost connection"
        );
    }
}

type FailStep = fn() -> SagaError;

/// Driver whose first attempts fail with `error`; every later attempt
/// behaves like [`DummyDriver`]. Failing more than once exercises the
/// repeated backoff passes of the retry loop, not just the first.
struct DeadlockingDriver {
    inner: DummyDriver,
    fail_first: usize,
    attempts: AtomicUsize,
    error: FailStep,
}

#[async_trait]
impl OpDriver for DeadlockingDriver {
    fn op_type(&self) -> &'static str {
        "merge"
    }

    fn initial_step(&self) -> &'static str {
        "started"
    }

    async fn run_step(&self, pools: &IdentityPools, op: &OpRow) -> Result<(), SagaError> {
        if self.attempts.fetch_add(1, Ordering::SeqCst) < self.fail_first {
            return Err((self.error)());
        }
        self.inner.run_step(pools, op).await
    }
}

#[tokio::test]
async fn a_step_that_loses_a_database_conflict_or_its_connection_is_retried_not_surfaced() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let failures: [(&str, FailStep); 2] = [
        ("deadlock", || db_error("40P01")),
        ("lost connection", connection_lost),
    ];
    for (name, error) in failures {
        let driver = DeadlockingDriver {
            inner: DummyDriver::new(),
            fail_first: 3,
            attempts: AtomicUsize::new(0),
            error,
        };
        let op_id = Uuid::now_v7();

        let row = engine
            .execute(&driver, op_id, ctx.team_id, &json!({"work": 1}))
            .await
            .unwrap_or_else(|err| panic!("{name}: retried inside the engine, not surfaced: {err}"));

        assert_eq!(row.step, STEP_COMPLETED, "{name}");
        assert_eq!(
            driver.inner.steps_run.load(Ordering::SeqCst),
            2,
            "{name}: both real steps ran after the failed attempts"
        );
        let (_, attempt, _, completed) = op_row(&ctx, op_id).await;
        assert!(completed, "{name}");
        assert_eq!(
            attempt, 1,
            "{name}: the retry re-drives under the original claim"
        );
    }

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

async fn wait_until_completed(ctx: &TestContext, op_id: Uuid) -> bool {
    for _ in 0..200 {
        if let Ok(row) = sqlx::query_scalar::<_, Option<chrono::DateTime<chrono::Utc>>>(
            "SELECT completed_at FROM lifecycle_op WHERE op_id = $1",
        )
        .bind(op_id)
        .fetch_one(&ctx.pool)
        .await
        {
            if row.is_some() {
                return true;
            }
        }
        tokio::time::sleep(std::time::Duration::from_millis(25)).await;
    }
    false
}

#[tokio::test]
async fn a_retry_attaches_to_a_detached_drive_instead_of_waiting_out_the_lease() {
    let ctx = TestContext::new().await;
    let engine = std::sync::Arc::new(ctx.engine());
    let driver = std::sync::Arc::new(DummyDriver::paced(std::time::Duration::from_millis(150)));
    let drives = DetachedDrives::new(4);
    let op_id = Uuid::now_v7();

    let detached_engine = engine.clone();
    let detached_driver = driver.clone();
    let hung_up = tokio::time::timeout(
        std::time::Duration::from_millis(1),
        drives.run(async move {
            detached_engine
                .execute(detached_driver.as_ref(), op_id, ctx.team_id, &json!({}))
                .await
        }),
    )
    .await;
    assert!(
        hung_up.is_err(),
        "the caller gave up before the drive finished"
    );
    assert_eq!(drives.in_flight(), 1);

    let started = std::time::Instant::now();
    let row = engine
        .execute(driver.as_ref(), op_id, ctx.team_id, &json!({}))
        .await
        .expect("the retry attaches and returns the terminal row");
    assert_eq!(row.step, STEP_COMPLETED);
    assert!(
        started.elapsed() < std::time::Duration::from_secs(5),
        "the retry waited on the live driver, not on the lease"
    );
    assert_eq!(
        driver.steps_run.load(Ordering::SeqCst),
        2,
        "the retry polled behind the detached drive instead of re-running steps"
    );

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn with_detaching_disabled_a_dropped_caller_abandons_the_op() {
    let ctx = TestContext::new().await;
    let engine = std::sync::Arc::new(ctx.engine());
    let driver = std::sync::Arc::new(DummyDriver::paced(std::time::Duration::from_millis(50)));
    let drives = DetachedDrives::new(0);
    let op_id = Uuid::now_v7();

    let created = std::sync::Arc::new(tokio::sync::Notify::new());
    let inline_engine = engine.clone();
    let inline_driver = driver.clone();
    let inline_created = created.clone();
    {
        let call = drives.run(async move {
            inline_engine
                .create_or_attach(inline_driver.as_ref(), op_id, ctx.team_id, &json!({}))
                .await
                .expect("create the op");
            inline_created.notify_one();
            inline_engine
                .execute(inline_driver.as_ref(), op_id, ctx.team_id, &json!({}))
                .await
        });
        tokio::pin!(call);
        tokio::select! {
            _ = &mut call => panic!("the drive finished before the caller hung up"),
            _ = created.notified() => {}
        }
    }

    tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    let (step, _, _, completed) = op_row(&ctx, op_id).await;
    assert_eq!(
        step, "started",
        "an inline drive stops where its caller dropped it"
    );
    assert!(!completed);
    assert_eq!(drives.in_flight(), 0);

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_detached_drive_finishes_after_its_caller_is_gone() {
    let ctx = TestContext::new().await;
    let engine = std::sync::Arc::new(ctx.engine());
    let driver = std::sync::Arc::new(DummyDriver::paced(std::time::Duration::from_millis(50)));
    let drives = DetachedDrives::new(4);
    let op_id = Uuid::now_v7();

    let hung_up = tokio::time::timeout(
        std::time::Duration::from_millis(1),
        drives.run(async move {
            engine
                .execute(driver.as_ref(), op_id, ctx.team_id, &json!({}))
                .await
        }),
    )
    .await;
    assert!(hung_up.is_err());

    assert!(
        wait_until_completed(&ctx, op_id).await,
        "the detached drive completed the op without its caller"
    );
    let (step, _, outcome, completed) = op_row(&ctx, op_id).await;
    assert_eq!(step, STEP_COMPLETED);
    assert!(completed);
    assert_eq!(outcome, Some(json!({"ok": true})));
    drives.shutdown().await;
    assert_eq!(drives.in_flight(), 0);

    ctx.cleanup().await.expect("cleanup");
}

async fn insert_leased_op(ctx: &TestContext, op_id: Uuid, lease: &str) {
    sqlx::query(&format!(
        "INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request, lease_expires_at) VALUES ($1, 'merge', $2, 'started', '{{}}'::jsonb, {lease})"
    ))
    .bind(op_id)
    .bind(ctx.team_id as i32)
    .execute(&ctx.pool)
    .await
    .expect("insert leased op");
}

#[tokio::test]
async fn waiting_for_a_lease_lapse_returns_at_once_for_a_missing_or_finished_op() {
    let ctx = TestContext::new().await;
    let engine = ctx.engine();
    let driver = DummyDriver::new();

    let missing = Uuid::now_v7();
    assert!(!engine
        .wait_for_lease_lapse(missing, engine.execute_deadline())
        .await
        .expect("a missing op is claimable"));

    let finished = Uuid::now_v7();
    engine
        .execute(&driver, finished, ctx.team_id, &json!({}))
        .await
        .expect("drive to completion");
    assert!(engine
        .wait_for_lease_lapse(finished, engine.execute_deadline())
        .await
        .expect("a finished op is reported terminal"));

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn waiting_for_a_lease_lapse_polls_until_it_lapses_and_gives_up_at_the_deadline() {
    let ctx = TestContext::new().await;
    let short_engine = personhog_identity::lifecycle::engine::Engine::new(
        ctx.pools.clone(),
        personhog_identity::lifecycle::engine::EngineConfig {
            lease: std::time::Duration::from_secs(5),
            execute_timeout: std::time::Duration::from_millis(300),
            poll_interval: std::time::Duration::from_millis(25),
            attempt_alert_threshold: 5,
            gc_batch_limit: 10_000,
        },
        ctx.tables.clone(),
    );

    let lapsing = Uuid::now_v7();
    insert_leased_op(&ctx, lapsing, "now() + interval '150 milliseconds'").await;
    let started = std::time::Instant::now();
    assert!(!short_engine
        .wait_for_lease_lapse(lapsing, short_engine.execute_deadline())
        .await
        .expect("the lease lapses"));
    assert!(started.elapsed() >= std::time::Duration::from_millis(100));

    let held = Uuid::now_v7();
    insert_leased_op(&ctx, held, "now() + interval '1 hour'").await;
    let err = short_engine
        .wait_for_lease_lapse(held, short_engine.execute_deadline())
        .await
        .expect_err("a lease held past the deadline is reported as busy");
    assert!(matches!(err, SagaError::Busy));

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_shared_deadline_bounds_the_lease_wait_and_the_drive_together() {
    let ctx = TestContext::new().await;
    let engine = personhog_identity::lifecycle::engine::Engine::new(
        ctx.pools.clone(),
        personhog_identity::lifecycle::engine::EngineConfig {
            lease: std::time::Duration::from_secs(5),
            execute_timeout: std::time::Duration::from_millis(200),
            poll_interval: std::time::Duration::from_millis(10),
            attempt_alert_threshold: 5,
            gc_batch_limit: 10_000,
        },
        ctx.tables.clone(),
    );
    let driver = DummyDriver::paced(std::time::Duration::from_millis(100));
    let op_id = Uuid::now_v7();
    insert_leased_op(&ctx, op_id, "now() + interval '150 milliseconds'").await;

    let started = std::time::Instant::now();
    let deadline = engine.execute_deadline();
    assert!(!engine
        .wait_for_lease_lapse(op_id, deadline)
        .await
        .expect("the lease lapses inside the budget"));
    let err = engine
        .execute_by(&driver, op_id, ctx.team_id, &json!({}), deadline)
        .await
        .expect_err("the drive inherits what is left of the budget");
    assert!(matches!(err, SagaError::DeadlineElapsed));
    assert!(
        started.elapsed() < std::time::Duration::from_millis(400),
        "the two phases shared one budget instead of taking one each"
    );
    let (_, _, _, completed) = op_row(&ctx, op_id).await;
    assert!(!completed);

    ctx.cleanup().await.expect("cleanup");
}
