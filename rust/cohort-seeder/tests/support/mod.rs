//! Shared harness for the PostgreSQL contract tests.
//!
//! `TestDatabase` gives every scenario its own schema (created on connect, dropped on cleanup) so the
//! split `#[tokio::test]`s run in parallel without colliding on the `cohort_backfill_*` tables.
//! [`with_db`] mirrors the original single-test wrapper: connect, run the body, clean up, then
//! surface the body's result *after* the schema drop. The `insert_*`/`*_pinned`/`*_condition`/
//! `behavioral_filter` builders and the `ensure_lease_lost`/`planned_count` helpers are the shared
//! fixtures each scenario composes the minimal state it needs from.

use std::future::Future;
use std::str::FromStr;

use anyhow::{bail, Context, Result};
use cohort_seeder::domain::RunId;
use cohort_seeder::store::chunks::{ChunkStoreError, PlanOutcome};
use serde_json::{json, Value};
use sqlx::postgres::{PgConnectOptions, PgPoolOptions};
use sqlx::types::Json;
use sqlx::{Connection, PgConnection, PgPool};
use uuid::Uuid;

/// The `cohort_backfill_*` DDL, pinned to the Django migration, applied fresh into each test schema.
pub const DDL: &str = include_str!("../fixtures/cohort_backfill_0004.sql");
/// A live cohort condition hash used by the superseded-load fixtures.
pub const ACTIVE_HASH: &str = "active0000000000";
/// A superseded cohort condition hash used by the superseded-load fixtures.
pub const SUPERSEDED_HASH: &str = "superseded000000";

/// A private schema plus a search-path-scoped pool, torn down on [`TestDatabase::cleanup`].
pub struct TestDatabase {
    admin: PgConnection,
    pool: PgPool,
    schema: String,
}

impl TestDatabase {
    pub async fn connect(database_url: &str) -> Result<Self> {
        let options = PgConnectOptions::from_str(database_url)?;
        let mut admin = PgConnection::connect_with(&options).await?;
        let schema = format!("cohort_seeder_{}", Uuid::new_v4().simple());
        sqlx::query(&format!("CREATE SCHEMA {schema}"))
            .execute(&mut admin)
            .await?;

        let search_path = format!("SET search_path TO {schema}, public");
        let pool = PgPoolOptions::new()
            .max_connections(4)
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

    pub async fn cleanup(mut self) -> Result<()> {
        self.pool.close().await;
        sqlx::query(&format!("DROP SCHEMA {} CASCADE", self.schema))
            .execute(&mut self.admin)
            .await?;
        self.admin.close().await?;
        Ok(())
    }
}

/// Connect a fresh schema-scoped database, run `body` against its pool, then drop the schema. The
/// body's result is surfaced only after cleanup so a failing assertion never leaks a schema.
pub async fn with_db<F, Fut>(body: F) -> Result<()>
where
    F: FnOnce(PgPool) -> Fut,
    Fut: Future<Output = Result<()>>,
{
    let database_url = std::env::var("DATABASE_URL")
        .context("DATABASE_URL is required when pg-test-support is enabled")?;
    let database = TestDatabase::connect(&database_url).await?;
    let result = body(database.pool.clone()).await;
    let cleanup = database.cleanup().await;
    result?;
    cleanup
}

/// Assert a lease-fenced store op reported [`ChunkStoreError::LeaseLost`] rather than any other error.
pub fn ensure_lease_lost(result: std::result::Result<(), ChunkStoreError>) -> Result<()> {
    if matches!(result, Err(ChunkStoreError::LeaseLost { .. })) {
        return Ok(());
    }
    bail!("expected LeaseLost, got {result:?}")
}

/// Unwrap the inserted-chunk count, failing if the run was unexpectedly not seeding.
pub fn planned_count(outcome: PlanOutcome) -> Result<u64> {
    match outcome {
        PlanOutcome::Planned { inserted } => Ok(inserted),
        PlanOutcome::RunNotSeeding => bail!("run was unexpectedly not seeding"),
    }
}

pub async fn insert_run(
    pool: &PgPool,
    team_id: i32,
    trigger_kind: &str,
    status: &str,
    with_boundary: bool,
    pinned: Value,
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

pub async fn insert_participation(
    pool: &PgPool,
    run_id: RunId,
    team_id: i32,
    cohort_id: i32,
    superseded: bool,
    filters: Value,
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

pub fn empty_pinned() -> Value {
    json!({"schema_version": 1, "conditions": [], "event_names": []})
}

pub fn pinned_condition(cohort_id: i32, hash: &str, event_name: &str) -> Value {
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

pub fn behavioral_filter(hash: &str, event_name: &str) -> Value {
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
