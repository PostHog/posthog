#![cfg(feature = "pg-test-support")]

use std::str::FromStr;
use std::time::Duration;

use anyhow::{bail, ensure, Context, Result};
use cohort_core::filters::CohortId;
use cohort_seeder::chunks::{pg_test_support, ChunkError, ChunkStore, LeaseFailure, ProduceHwms};
use cohort_seeder::ids::{ClaimEpoch, RunId};
use cohort_seeder::pinned::PinnedWarning;
use cohort_seeder::runs::{
    discover_runs, establish_boundary, fail_run, record_run_warning, BoundaryOutcome, RunError,
    RunStatus, RunWarningNote,
};
use common_types::cohort::TeamAllowlist;
use serde_json::json;
use sqlx::postgres::{PgConnectOptions, PgPoolOptions};
use sqlx::types::Json;
use sqlx::{Connection, PgConnection, PgPool};
use uuid::Uuid;

const DDL: &str = include_str!("fixtures/cohort_backfill_0004.sql");
const ACTIVE_HASH: &str = "active0000000000";
const SUPERSEDED_HASH: &str = "superseded000000";

struct TestDatabase {
    admin: PgConnection,
    pool: PgPool,
    schema: String,
}

impl TestDatabase {
    async fn connect(database_url: &str) -> Result<Self> {
        let options = PgConnectOptions::from_str(database_url)?;
        let mut admin = PgConnection::connect_with(&options).await?;
        let schema = format!("cohort_seeder_{}", Uuid::new_v4().simple());
        sqlx::query(&format!("CREATE SCHEMA {schema}"))
            .execute(&mut admin)
            .await?;

        let search_path = format!("SET search_path TO {schema}, public");
        let pool = PgPoolOptions::new()
            .max_connections(8)
            .after_connect(move |connection, _| {
                let search_path = search_path.clone();
                Box::pin(async move {
                    sqlx::query(&search_path).execute(&mut *connection).await?;
                    Ok(())
                })
            })
            .connect_with(options)
            .await?;
        sqlx::raw_sql(DDL).execute(&pool).await?;
        Ok(Self {
            admin,
            pool,
            schema,
        })
    }

    async fn cleanup(mut self) -> Result<()> {
        self.pool.close().await;
        sqlx::query(&format!("DROP SCHEMA {} CASCADE", self.schema))
            .execute(&mut self.admin)
            .await?;
        self.admin.close().await?;
        Ok(())
    }
}

#[tokio::test]
async fn postgres_contract_fences_claims_and_boundaries() -> Result<()> {
    let database_url = std::env::var("DATABASE_URL")
        .context("DATABASE_URL is required when pg-test-support is enabled")?;
    let database = TestDatabase::connect(&database_url).await?;
    let result = exercise_contract(&database.pool).await;
    let cleanup = database.cleanup().await;
    result?;
    cleanup
}

async fn exercise_contract(pool: &PgPool) -> Result<()> {
    let pinned = json!({
        "schema_version": 1,
        "conditions": [
            pinned_condition(10, ACTIVE_HASH, "active-event"),
            pinned_condition(11, SUPERSEDED_HASH, "superseded-event"),
        ],
        "event_names": ["active-event", "superseded-event"],
    });
    let self_run_id = insert_run(
        pool,
        2,
        "team_enablement",
        "awaiting_boundary",
        false,
        pinned,
    )
    .await?;
    insert_participation(
        pool,
        self_run_id,
        2,
        10,
        false,
        behavioral_filter(ACTIVE_HASH, "active-event"),
    )
    .await?;
    insert_participation(
        pool,
        self_run_id,
        2,
        11,
        true,
        behavioral_filter(SUPERSEDED_HASH, "superseded-event"),
    )
    .await?;
    let other_team_run_id = insert_run(
        pool,
        3,
        "team_enablement",
        "awaiting_boundary",
        false,
        empty_pinned(),
    )
    .await?;

    let only_team_two: TeamAllowlist = "2".parse().map_err(anyhow::Error::msg)?;
    let discovered = discover_runs(pool, &only_team_two).await?;
    ensure!(discovered.len() == 1);
    ensure!(discovered[0].run_id == self_run_id);

    let left = discovered[0].clone();
    let right = discovered[0].clone();
    let (left, right) = tokio::join!(
        establish_boundary(pool, left),
        establish_boundary(pool, right)
    );
    let outcomes = [left?, right?];
    ensure!(
        outcomes
            .iter()
            .filter(|outcome| matches!(outcome, BoundaryOutcome::Established(_)))
            .count()
            == 1
    );

    sqlx::query("UPDATE cohort_backfill_runs SET error = repeat('x', 5000) WHERE id = $1")
        .bind(self_run_id)
        .execute(pool)
        .await?;
    ensure!(record_run_warning(pool, self_run_id, RunWarningNote::ConditionsDropped).await?);
    ensure!(!record_run_warning(pool, self_run_id, RunWarningNote::ConditionsDropped).await?);
    ensure!(record_run_warning(pool, self_run_id, RunWarningNote::LookbackTruncated).await?);
    let run_warnings: String =
        sqlx::query_scalar("SELECT error FROM cohort_backfill_runs WHERE id = $1")
            .bind(self_run_id)
            .fetch_one(pool)
            .await?;
    ensure!(run_warnings.len() == 4_096);
    ensure!(
        run_warnings
            .matches(RunWarningNote::ConditionsDropped.as_str())
            .count()
            == 1
    );
    ensure!(
        run_warnings
            .matches(RunWarningNote::LookbackTruncated.as_str())
            .count()
            == 1
    );
    let established = outcomes
        .iter()
        .find_map(|outcome| match outcome {
            BoundaryOutcome::Established(run) | BoundaryOutcome::AlreadyEstablished(run) => {
                Some(run)
            }
            BoundaryOutcome::NoLongerSeedable { .. } => None,
        })
        .context("boundary promotion produced no seedable run")?;
    let validated = established.load_pinned(pool).await?;
    ensure!(validated.run.conditions.len() == 1);
    ensure!(validated.run.conditions[0].cohort_id == CohortId(10));
    ensure!(validated.run.event_names == ["active-event"]);
    ensure!(validated
        .run
        .filters
        .behavioral_by_event_name
        .contains_key("active-event"));
    ensure!(!validated
        .run
        .filters
        .behavioral_by_event_name
        .contains_key("superseded-event"));
    ensure!(validated.warnings.iter().any(|warning| matches!(
        warning,
        PinnedWarning::ConditionSuperseded { cohort_id, .. } if *cohort_id == CohortId(11)
    )));
    ensure!(
        outcomes
            .iter()
            .filter(|outcome| matches!(outcome, BoundaryOutcome::AlreadyEstablished(_)))
            .count()
            == 1
    );

    let dr_run_id = insert_run(
        pool,
        4,
        "disaster_recovery",
        "awaiting_boundary",
        false,
        empty_pinned(),
    )
    .await?;
    let cross_team_run_id =
        insert_run(pool, 5, "team_enablement", "seeding", true, empty_pinned()).await?;
    insert_participation(
        pool,
        cross_team_run_id,
        999,
        50,
        true,
        json!({"properties": {"type": "AND", "values": []}}),
    )
    .await?;
    let all_runs = discover_runs(pool, &TeamAllowlist::All).await?;
    ensure!(all_runs.iter().any(|run| run.run_id == other_team_run_id));
    let cross_team_run = all_runs
        .iter()
        .find(|run| run.run_id == cross_team_run_id)
        .context("cross-team run was not discovered")?;
    ensure!(matches!(
        cross_team_run.load_pinned(pool).await,
        Err(RunError::CrossTeamParticipation {
            actual_team_id: 999,
            ..
        })
    ));
    let dr_run = all_runs
        .into_iter()
        .find(|run| run.run_id == dr_run_id)
        .context("DR run was not discovered")?;
    ensure!(matches!(
        establish_boundary(pool, dr_run).await,
        Err(RunError::DisasterRecoveryBoundaryMissing(id)) if id == dr_run_id
    ));

    let store = ChunkStore::new(pool.clone());
    ensure!(store.plan_chunks(self_run_id, [100, 101]).await? == 2);
    ensure!(store.plan_chunks(self_run_id, [100, 101]).await? == 0);
    let chunk_teams_match: bool = sqlx::query_scalar(
        "SELECT bool_and(team_id = 2) FROM cohort_backfill_chunks WHERE run_id = $1",
    )
    .bind(self_run_id)
    .fetch_one(pool)
    .await?;
    ensure!(chunk_teams_match);

    let first_store = store.clone();
    let second_store = store.clone();
    let run_ids = [self_run_id];
    let (first, second) = tokio::join!(
        first_store.claim_next(&run_ids, "worker-a", Duration::from_secs(60), 5),
        second_store.claim_next(&run_ids, "worker-b", Duration::from_secs(60), 5),
    );
    let first = first?.context("first claimant found no chunk")?;
    let second = second?.context("second claimant found no chunk")?;
    ensure!(first.lease().chunk_id() != second.lease().chunk_id());

    let stale = first.lease();
    let stale_claimant = first.claimed_by().to_string();
    drop(first);
    sqlx::query(
        "UPDATE cohort_backfill_chunks SET lease_expires_at = now() - interval '1 second' WHERE id = $1",
    )
    .bind(stale.chunk_id())
    .execute(pool)
    .await?;
    let reclaimed = store
        .claim_next(&run_ids, "worker-c", Duration::from_secs(60), 5)
        .await?
        .context("expired chunk was not reclaimed")?;
    ensure!(reclaimed.lease().chunk_id() == stale.chunk_id());
    ensure!(reclaimed.lease().epoch() == ClaimEpoch(stale.epoch().0 + 1));

    ensure_lease_lost(
        pg_test_support::heartbeat(&store, stale, &stale_claimant, Duration::from_secs(60)).await,
    )?;
    ensure_lease_lost(pg_test_support::mark_produced(&store, stale, 1).await)?;
    ensure_lease_lost(pg_test_support::confirm(&store, stale, &ProduceHwms::default()).await)?;
    ensure_lease_lost(pg_test_support::fail(&store, stale, "stale failure").await)?;
    ensure_lease_lost(pg_test_support::unclaim(&store, stale).await)?;

    let mut hwms = ProduceHwms::default();
    hwms.observe(3, 41);
    pg_test_support::mark_produced(&store, reclaimed.lease(), 0).await?;
    pg_test_support::confirm(&store, reclaimed.lease(), &hwms).await?;
    drop(reclaimed);

    let second_id = second.lease().chunk_id();
    sqlx::query("UPDATE cohort_backfill_chunks SET attempts = 5 WHERE id = $1")
        .bind(second_id)
        .execute(pool)
        .await?;
    second.unclaim().await?;
    let (pending_status, refunded_attempts): (String, i32) =
        sqlx::query_as("SELECT status, attempts FROM cohort_backfill_chunks WHERE id = $1")
            .bind(second_id)
            .fetch_one(pool)
            .await?;
    ensure!(pending_status == "pending");
    ensure!(refunded_attempts == 4);

    let retry = store
        .claim_next(&run_ids, "worker-d", Duration::from_secs(60), 5)
        .await?
        .context("unclaimed chunk was not claimable")?;
    let retry_id = retry.lease().chunk_id();
    let reclaimed_attempts: i32 =
        sqlx::query_scalar("SELECT attempts FROM cohort_backfill_chunks WHERE id = $1")
            .bind(retry_id)
            .fetch_one(pool)
            .await?;
    ensure!(reclaimed_attempts == 5);
    retry.fail(&"x".repeat(5_000)).await?;
    let (failed_status, error_length): (String, i32) = sqlx::query_as(
        "SELECT status, length(last_error)::integer FROM cohort_backfill_chunks WHERE id = $1",
    )
    .bind(retry_id)
    .fetch_one(pool)
    .await?;
    ensure!(failed_status == "failed");
    ensure!(error_length == 4_096);
    ensure!(store
        .claim_next(&run_ids, "worker-terminal", Duration::from_secs(60), 5)
        .await?
        .is_none());

    ensure!(store.plan_chunks(self_run_id, [102]).await? == 1);
    let final_attempt = store
        .claim_next(&run_ids, "worker-e", Duration::from_secs(1), 5)
        .await?
        .context("final-attempt producer found no chunk")?;
    let final_attempt_lease = final_attempt.lease();
    pg_test_support::mark_produced(&store, final_attempt_lease, 1).await?;
    drop(final_attempt);
    sqlx::query(
        "UPDATE cohort_backfill_chunks SET attempts = 5, lease_expires_at = now() - interval '1 second' WHERE id = $1",
    )
    .bind(final_attempt_lease.chunk_id())
    .execute(pool)
    .await?;

    let observed = store
        .claim_next(&run_ids, "worker-f", Duration::from_secs(1), 5)
        .await?
        .context("expired produced chunk at the attempt limit was not reclaimed")?;
    ensure!(observed.lease().chunk_id() == final_attempt_lease.chunk_id());
    ensure!(observed.lease().epoch() == ClaimEpoch(final_attempt_lease.epoch().0 + 1));
    let active_reclaim_attempts: i32 =
        sqlx::query_scalar("SELECT attempts FROM cohort_backfill_chunks WHERE id = $1")
            .bind(observed.lease().chunk_id())
            .fetch_one(pool)
            .await?;
    ensure!(active_reclaim_attempts == 5);
    let cancelled = observed.cancellation_token();
    sqlx::query(
        "UPDATE cohort_backfill_runs SET status = 'cancelled', updated_at = now() WHERE id = $1",
    )
    .bind(self_run_id)
    .execute(pool)
    .await?;
    let failure = tokio::time::timeout(Duration::from_secs(3), observed.lease_failure()).await?;
    ensure!(matches!(
        failure,
        LeaseFailure::Heartbeat(ChunkError::LeaseLost { .. })
    ));
    ensure!(cancelled.is_cancelled());

    fail_run(pool, dr_run_id, &"y".repeat(5_000)).await?;
    ensure!(!record_run_warning(pool, dr_run_id, RunWarningNote::ConditionsDropped).await?);
    let (run_status, run_error_length): (String, i32) = sqlx::query_as(
        "SELECT status, length(error)::integer FROM cohort_backfill_runs WHERE id = $1",
    )
    .bind(dr_run_id)
    .fetch_one(pool)
    .await?;
    ensure!(run_status == RunStatus::Failed.as_str());
    ensure!(run_error_length == 4_096);
    Ok(())
}

fn ensure_lease_lost(result: std::result::Result<(), ChunkError>) -> Result<()> {
    if matches!(result, Err(ChunkError::LeaseLost { .. })) {
        return Ok(());
    }
    bail!("expected LeaseLost, got {result:?}")
}

async fn insert_run(
    pool: &PgPool,
    team_id: i32,
    trigger_kind: &str,
    status: &str,
    with_boundary: bool,
    pinned: serde_json::Value,
) -> Result<RunId> {
    let run_id = RunId(Uuid::now_v7());
    sqlx::query(
        r#"
        INSERT INTO cohort_backfill_runs
            (id, team_id, backfill_kind, trigger_kind, scope, status, timezone, boundary_at,
             pinned, preconditions, created_at, updated_at)
        VALUES ($1, $2, 'behavioral', $3, 'team', $4, 'UTC',
                CASE WHEN $5 THEN now() ELSE NULL END,
                $6, '{}'::jsonb, now(), now())
        "#,
    )
    .bind(run_id)
    .bind(team_id)
    .bind(trigger_kind)
    .bind(status)
    .bind(with_boundary)
    .bind(Json(pinned))
    .execute(pool)
    .await?;
    Ok(run_id)
}

async fn insert_participation(
    pool: &PgPool,
    run_id: RunId,
    team_id: i32,
    cohort_id: i32,
    superseded: bool,
    filters: serde_json::Value,
) -> Result<()> {
    sqlx::query(
        r#"
        INSERT INTO cohort_backfill_run_cohorts
            (id, run_id, team_id, cohort_id, filters_shape_hash, pinned_filters, superseded_at)
        VALUES ($1, $2, $3, $4, 'shape', $5, CASE WHEN $6 THEN now() ELSE NULL END)
        "#,
    )
    .bind(Uuid::now_v7())
    .bind(run_id)
    .bind(team_id)
    .bind(cohort_id)
    .bind(Json(filters))
    .bind(superseded)
    .execute(pool)
    .await?;
    Ok(())
}

fn empty_pinned() -> serde_json::Value {
    json!({"schema_version": 1, "conditions": [], "event_names": []})
}

fn pinned_condition(cohort_id: i32, hash: &str, event_name: &str) -> serde_json::Value {
    json!({
        "cohort_id": cohort_id,
        "condition_hash": hash,
        "value": "performed_event",
        "time_value": 7,
        "time_interval": "day",
        "explicit_datetime": null,
        "explicit_datetime_to": null,
        "operator": null,
        "operator_value": null,
        "window_days": 7,
        "event_name": event_name,
        "is_action": false,
    })
}

fn behavioral_filter(hash: &str, event_name: &str) -> serde_json::Value {
    json!({
        "properties": {"type": "AND", "values": [{
            "type": "behavioral",
            "value": "performed_event",
            "key": event_name,
            "conditionHash": hash,
            "time_value": 7,
            "time_interval": "day",
            "bytecode": ["_H", 1, 32, event_name, 32, "event", 1, 1, 11],
        }]}
    })
}
