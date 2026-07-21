use serde_json::Value;
use sqlx::{PgPool, Row};

use super::model::IntegrationRow;

/// Sole `errors` sentinel, matching Django's `ERROR_TOKEN_REFRESH_FAILED` (posthog/models/integration.py).
pub const ERROR_TOKEN_REFRESH_FAILED: &str = "TOKEN_REFRESH_FAILED";

/// Fetch integration rows by id. Read-only (SELECT). `config`/`sensitive_config` are `jsonb`
/// and decode straight into `serde_json::Value` (sqlx `json` feature).
///
/// `id`/`team_id` are cast to `bigint` so decoding as `i64` is reliable whether the underlying
/// columns are `int4` (Django `AutoField`) or `int8` (`BigAutoField`).
pub async fn fetch_by_ids(pool: &PgPool, ids: &[i64]) -> Result<Vec<IntegrationRow>, sqlx::Error> {
    if ids.is_empty() {
        return Ok(Vec::new());
    }

    let rows = sqlx::query(
        "SELECT id::bigint AS id, team_id::bigint AS team_id, kind, config, sensitive_config \
         FROM posthog_integration WHERE id = ANY($1)",
    )
    .bind(ids)
    .fetch_all(pool)
    .await?;

    let mut out = Vec::with_capacity(rows.len());
    for row in rows {
        out.push(IntegrationRow {
            id: row.try_get("id")?,
            team_id: row.try_get("team_id")?,
            kind: row.try_get("kind")?,
            config: row.try_get("config")?,
            sensitive_config: row.try_get("sensitive_config")?,
        });
    }
    Ok(out)
}

/// Fetch a single row by id (used to re-read under the refresh lock so we don't refresh a token a
/// concurrent head already rotated). Returns `None` if the row no longer exists.
pub async fn fetch_one(pool: &PgPool, id: i64) -> Result<Option<IntegrationRow>, sqlx::Error> {
    Ok(fetch_by_ids(pool, &[id]).await?.into_iter().next())
}

/// Persist a successful refresh: new plaintext `config` and re-encrypted `sensitive_config`, and
/// clear any prior refresh error. Mirrors Django's `refresh_access_token` write.
pub async fn update_after_refresh(
    pool: &PgPool,
    id: i64,
    config: &Value,
    sensitive_config: &Value,
) -> Result<(), sqlx::Error> {
    sqlx::query(
        "UPDATE posthog_integration SET config = $1, sensitive_config = $2, errors = '' WHERE id = $3",
    )
    .bind(config)
    .bind(sensitive_config)
    .bind(id)
    .execute(pool)
    .await?;
    Ok(())
}

/// Record a failed refresh so the app surfaces "reconnect this integration" (same sentinel Django
/// sets). Leaves the stored tokens untouched.
pub async fn mark_refresh_failed(pool: &PgPool, id: i64) -> Result<(), sqlx::Error> {
    sqlx::query("UPDATE posthog_integration SET errors = $1 WHERE id = $2")
        .bind(ERROR_TOKEN_REFRESH_FAILED)
        .bind(id)
        .execute(pool)
        .await?;
    Ok(())
}
