//! Deletes one team's rows from the Postgres person graph and the personhog
//! writer's temp tables, so a run starts from a clean slate.

use anyhow::{Context, Result};
use sqlx::postgres::PgPoolOptions;
use sqlx::{Executor, PgPool};

/// So one chunk's delete fails fast on a lock instead of hanging the step.
const STATEMENT_TIMEOUT_MS: u64 = 30_000;
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
        // Chunk the delete so millions of rows stay bounded and index-driven.
        let mut total = 0u64;
        loop {
            let deleted = sqlx::query(&format!(
                "DELETE FROM {table} WHERE team_id = $1 AND id IN \
                 (SELECT id FROM {table} WHERE team_id = $1 LIMIT {chunk})"
            ))
            .bind(team_id)
            .execute(pool)
            .await
            .with_context(|| format!("resetting {table}"))?
            .rows_affected();
            total += deleted;
            if (deleted as i64) < chunk {
                break;
            }
        }
        tracing::info!(table, team_id, deleted = total, "reset team rows");
    }
    Ok(())
}
