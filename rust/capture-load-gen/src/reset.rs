//! Deletes one team's rows from the Postgres person graph and the personhog
//! writer's temp tables, so a run starts from a clean slate.

use anyhow::{Context, Result};
use sqlx::postgres::PgPoolOptions;
use sqlx::{Executor, PgPool};

/// So a wedged delete fails the step instead of hanging it.
const STATEMENT_TIMEOUT_MS: u64 = 300_000;
/// Rows deleted per statement.
const RESET_CHUNK: i64 = 10_000;

pub struct ResetConfig {
    pub database_url: String,
    pub team_id: i64,
    pub tmp_person_table: String,
    pub tmp_pdi_table: String,
}

pub async fn reset_team(cfg: &ResetConfig) -> Result<()> {
    let pool = PgPoolOptions::new()
        .max_connections(1)
        .after_connect(|conn, _meta| {
            Box::pin(async move {
                conn.execute(format!("SET statement_timeout = {STATEMENT_TIMEOUT_MS}").as_str())
                    .await?;
                Ok(())
            })
        })
        .connect(&cfg.database_url)
        .await
        .context("connecting to the persons database")?;
    reset_team_on_pool(
        &pool,
        cfg.team_id,
        &cfg.tmp_person_table,
        &cfg.tmp_pdi_table,
        RESET_CHUNK,
    )
    .await
}

pub async fn reset_team_on_pool(
    pool: &PgPool,
    team_id: i64,
    tmp_person_table: &str,
    tmp_pdi_table: &str,
    chunk: i64,
) -> Result<()> {
    // Distinct-id rows reference persons, so delete them first.
    for table in [
        "posthog_persondistinctid",
        tmp_pdi_table,
        "posthog_person",
        tmp_person_table,
    ] {
        // A run seeds millions of rows, and one statement that hits the timeout
        // rolls back whole, so every retry starts from zero. Each chunk commits
        // on its own instead. Read the ids first rather than matching them with
        // a subquery: a subquery on this table plans as a nested loop semi join
        // and rescans once per outer row.
        let mut total = 0u64;
        loop {
            let ids: Vec<i64> = sqlx::query_scalar(&format!(
                "SELECT id FROM {table} WHERE team_id = $1 LIMIT {chunk}"
            ))
            .bind(team_id)
            .fetch_all(pool)
            .await
            .with_context(|| format!("selecting {table} rows to reset"))?;
            if ids.is_empty() {
                break;
            }
            // Person ids are unique per team, so the team must stay in the
            // predicate or another team's colliding rows go too.
            total += sqlx::query(&format!(
                "DELETE FROM {table} WHERE team_id = $1 AND id = ANY($2)"
            ))
            .bind(team_id)
            .bind(&ids)
            .execute(pool)
            .await
            .with_context(|| format!("resetting {table}"))?
            .rows_affected();
        }
        tracing::info!(table, team_id, deleted = total, "reset team rows");
    }
    Ok(())
}
