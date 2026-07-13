use sqlx::{PgPool, Row};

use super::model::IntegrationRow;

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
