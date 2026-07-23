use metrics::{counter, histogram};
use personhog_common::properties::rewrite_out_of_range_numbers;
use sqlx::postgres::PgPool;
use sqlx::Row;

use crate::cache::{CachedPerson, PersonCacheKey};

/// A configured PG fallback: the pool and the table it reads. The table
/// must be the one the writer maintains (see FALLBACK_TABLE in
/// config.rs for the pairing rule), so a fallback cannot be constructed
/// without deciding it.
#[derive(Clone)]
pub struct PgFallback {
    pub pool: PgPool,
    pub table: String,
}

/// Validate a configured table identifier before it is interpolated into
/// SQL (identifiers cannot be bound as parameters).
pub fn validate_table_name(table: &str) -> Result<(), String> {
    if table.is_empty() || !table.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        return Err(format!("invalid fallback table name: {table:?}"));
    }
    Ok(())
}

/// Reads a person from the configured fallback table — the table the
/// writer maintains. Used as a fallback when the leader's cache doesn't
/// have the person.
pub async fn load_person_from_pg(
    pool: &PgPool,
    table: &str,
    key: &PersonCacheKey,
) -> Result<Option<CachedPerson>, sqlx::Error> {
    let start = std::time::Instant::now();

    let team_id_i32 = i32::try_from(key.team_id)
        .map_err(|_| sqlx::Error::Protocol(format!("team_id {} exceeds i32 range", key.team_id)))?;

    // properties comes back as text and is parsed here rather than through
    // sqlx's jsonb decode: rows written by other services can hold numerics
    // whose PG-expanded rendering serde_json rejects, and the leniency
    // lives in our parse step (see below). The cost is identical — sqlx's
    // jsonb decode parses the same text under the hood.
    let row = sqlx::query(&format!(
        "SELECT id, team_id, uuid::text, properties::text AS properties, created_at, version, \
         is_identified
         FROM {table}
         WHERE team_id = $1 AND id = $2",
    ))
    .bind(team_id_i32)
    .bind(key.person_id)
    .fetch_optional(pool)
    .await?;

    histogram!("personhog_leader_pg_fallback_duration_seconds")
        .record(start.elapsed().as_secs_f64());

    let Some(row) = row else {
        counter!("personhog_leader_pg_fallback_total", "outcome" => "not_found").increment(1);
        return Ok(None);
    };

    let id: i64 = row.get("id");
    let team_id: i32 = row.get("team_id");
    let uuid: String = row.get("uuid");
    // Borrowed from the row buffer — no copy; parse cost matches what
    // sqlx's own jsonb decode would spend on the same bytes.
    let properties_text: &str = row.get("properties");
    let created_at: chrono::DateTime<chrono::Utc> = row.get("created_at");
    let version: Option<i64> = row.get("version");
    let is_identified: bool = row.get("is_identified");

    let properties = match serde_json::from_str(properties_text) {
        Ok(value) => value,
        // Out-of-range numerics from other writers: rewrite to what
        // JSON.parse would read (rounding, clamping beyond f64) instead
        // of leaving the person permanently unloadable. Admission's
        // sanitizer persists the healed form on the next write-through.
        Err(strict_err) => {
            match serde_json::from_str(&rewrite_out_of_range_numbers(properties_text)) {
                Ok(value) => {
                    counter!("personhog_leader_pg_properties_rewritten_total").increment(1);
                    tracing::warn!(
                        team_id,
                        person_id = id,
                        "rewrote out-of-range numerics in stored person properties"
                    );
                    value
                }
                Err(rewritten_err) => {
                    return Err(sqlx::Error::Protocol(format!(
                        "person properties unparseable (team_id={team_id}, person_id={id}): \
                     {strict_err}; after numeric rewrite: {rewritten_err}"
                    )));
                }
            }
        }
    };

    counter!("personhog_leader_pg_fallback_total", "outcome" => "found").increment(1);

    Ok(Some(CachedPerson {
        id,
        uuid,
        team_id: team_id as i64,
        properties,
        created_at: created_at.timestamp(),
        version: version.unwrap_or(0),
        is_identified,
    }))
}
