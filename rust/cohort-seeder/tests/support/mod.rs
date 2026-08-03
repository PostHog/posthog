//! Shared harness for the PostgreSQL contract tests.
//!
//! `TestDatabase` gives every scenario its own schema (created on connect, dropped on cleanup) so the
//! split `#[tokio::test]`s run in parallel without colliding on the `cohort_backfill_*` tables.
//! [`with_db`] mirrors the original single-test wrapper: connect, run the body, clean up, then
//! surface the body's result *after* the schema drop. The `insert_*`/`*_pinned`/`*_condition`/
//! `behavioral_filter` builders and the `ensure_lease_lost`/`planned_count` helpers are the shared
//! fixtures each scenario composes the minimal state it needs from.
//!
//! Each integration test file is its own crate and pulls this in via `mod support;`, so a helper
//! used by only some of them looks "dead" to the others — hence the crate-wide allow below.
#![allow(dead_code)]

use std::future::Future;
use std::str::FromStr;

use anyhow::{bail, Context, Result};
use cohort_seeder::domain::RunId;
use cohort_seeder::store::chunks::{ChunkStoreError, PlanOutcome};
use cohort_seeder::store::completion::CompletionStoreError;
use serde_json::{json, Value};
use sqlx::postgres::{PgConnectOptions, PgPoolOptions};
use sqlx::types::Json;
use sqlx::{Connection, PgConnection, PgPool};
use uuid::Uuid;

/// The `cohort_backfill_*` DDL (plus a schema-local `posthog_cohort` projection), pinned to Django
/// migration 0009, applied fresh into each test schema.
pub const DDL: &str = include_str!("../fixtures/cohort_backfill_0009.sql");
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

/// Assert an epoch-fenced completion op reported [`CompletionStoreError::CompletionFenceLost`].
pub fn ensure_fence_lost(result: std::result::Result<(), CompletionStoreError>) -> Result<()> {
    if matches!(
        result,
        Err(CompletionStoreError::CompletionFenceLost { .. })
    ) {
        return Ok(());
    }
    bail!("expected CompletionFenceLost, got {result:?}")
}

/// Insert a run already in `reconciling` with its planning proof stamped — the state a dispatch
/// operates against.
pub async fn insert_reconciling_run(pool: &PgPool, team_id: i32) -> Result<RunId> {
    let run_id = insert_run(
        pool,
        team_id,
        "team_enablement",
        "reconciling",
        true,
        empty_pinned(),
    )
    .await?;
    sqlx::query("UPDATE cohort_backfill_runs SET chunks_planned_at = now() WHERE id = $1")
        .bind(run_id)
        .execute(pool)
        .await?;
    Ok(run_id)
}

/// Directly set one participation's observed marker bitmap (the raw BIGINT), bypassing the fenced
/// merge, so a scenario can assert a downstream read or reset.
pub async fn set_marker_bits(
    pool: &PgPool,
    run_id: RunId,
    cohort_id: i32,
    bits: i64,
) -> Result<()> {
    sqlx::query(
        "UPDATE cohort_backfill_run_cohorts SET reconcile_marker_bits = $3 \
         WHERE run_id = $1 AND cohort_id = $2",
    )
    .bind(run_id)
    .bind(cohort_id)
    .bind(bits)
    .execute(pool)
    .await?;
    Ok(())
}

/// Insert a row into the schema-local `posthog_cohort` projection for `load_current_behavioral_hashes`.
pub async fn insert_cohort(
    pool: &PgPool,
    id: i32,
    team_id: i32,
    behavioral_hash: Option<&str>,
    deleted: bool,
) -> Result<()> {
    sqlx::query(
        "INSERT INTO posthog_cohort (id, team_id, behavioral_filters_shape_hash, deleted) \
         VALUES ($1, $2, $3, $4)",
    )
    .bind(id)
    .bind(team_id)
    .bind(behavioral_hash)
    .bind(deleted)
    .execute(pool)
    .await?;
    Ok(())
}

/// Unwrap the inserted-chunk count, failing if the run was unexpectedly not seeding or planned.
pub fn planned_count(outcome: PlanOutcome) -> Result<u64> {
    match outcome {
        PlanOutcome::Planned { inserted } => Ok(inserted),
        PlanOutcome::RunNotSeeding => bail!("run was unexpectedly not seeding"),
        PlanOutcome::AlreadyPlanned => bail!("run was unexpectedly already planned"),
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
            (id, run_id, team_id, cohort_id, filters_shape_hash,
             behavioral_filters_shape_hash, pinned_filters, superseded_at)
        VALUES ($1, $2, $3, $4, 'full-shape', 'behavioral-shape', $5,
                CASE WHEN $6 THEN now() ELSE NULL END)
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

/// Insert a `person_property` run with a pinned `person_scan_since` 30 days back.
pub async fn insert_person_run(
    pool: &PgPool,
    team_id: i32,
    status: &str,
    with_boundary: bool,
    pinned: Value,
) -> Result<RunId> {
    let run_id = RunId(Uuid::now_v7());
    sqlx::query(
        r#"
        INSERT INTO cohort_backfill_runs
            (id, team_id, backfill_kind, trigger_kind, scope, status, timezone, boundary_at,
             person_scan_since, pinned, preconditions, created_at, updated_at)
        VALUES ($1, $2, 'person_property', 'cohort_created', 'cohort', $3, 'UTC',
                CASE WHEN $4 THEN now() ELSE NULL END,
                now() - interval '30 days', $5, '{}'::jsonb, now(), now())
        "#,
    )
    .bind(run_id)
    .bind(team_id)
    .bind(status)
    .bind(with_boundary)
    .bind(Json(pinned))
    .execute(pool)
    .await?;
    Ok(run_id)
}

pub fn empty_pinned() -> Value {
    json!({"schema_version": 1, "conditions": [], "event_names": []})
}

pub fn person_pinned(conditions: &[(i32, &str)]) -> Value {
    let conditions = conditions
        .iter()
        .map(|(cohort_id, hash)| json!({"cohort_id": cohort_id, "condition_hash": hash}))
        .collect::<Vec<_>>();
    json!({"schema_version": 1, "conditions": conditions, "person_horizon_days": 30})
}

pub fn person_filter(hash: &str, key: &str) -> Value {
    json!({
        "properties": {"type": "AND", "values": [{
            "type": "person",
            "key": key,
            "value": "expected",
            "operator": "exact",
            "conditionHash": hash,
            "bytecode": ["_H", 1, 32, "expected", 32, key, 32, "properties", 32, "person", 1, 3, 11],
        }]}
    })
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
