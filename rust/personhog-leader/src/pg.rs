use std::sync::Arc;
use std::time::Instant;

use metrics::{counter, histogram};
use personhog_common::properties::rewrite_out_of_range_numbers;
use sqlx::pool::PoolConnection;
use sqlx::postgres::{PgPool, PgRow};
use sqlx::{Postgres, Row};

use crate::cache::{CachedPerson, PersonCacheKey};

/// A configured PG fallback: the pool and the table it reads. The table
/// must be the one the writer maintains (see FALLBACK_TABLE in
/// config.rs for the pairing rule), so a fallback cannot be constructed
/// without deciding it.
#[derive(Clone)]
pub struct PgFallback {
    pub pool: PgPool,
    pub table: String,
    pub lifecycle: LifecycleTables,
}

/// The saga tables the fence checks read. Must be the pair identity
/// writes its marks to, or every committed release fails closed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LifecycleTables {
    pub op: String,
    pub op_person: String,
}

impl LifecycleTables {
    pub fn new(op: &str, op_person: &str) -> Self {
        Self {
            op: op.to_string(),
            op_person: op_person.to_string(),
        }
    }
}

/// Take a fallback-pool connection, recording the wait: the pool is small
/// and shared by cache-miss loads and the sagas' mark checks.
pub async fn acquire_timed(
    pool: &PgPool,
    caller: &'static str,
) -> Result<PoolConnection<Postgres>, sqlx::Error> {
    let start = Instant::now();
    let conn = pool.acquire().await;
    histogram!("personhog_leader_fallback_pool_acquire_ms", "caller" => caller)
        .record(start.elapsed().as_secs_f64() * 1000.0);
    conn
}

/// Validate a configured table identifier before it is interpolated into
/// SQL (identifiers cannot be bound as parameters).
pub fn validate_table_name(table: &str) -> Result<(), String> {
    if table.is_empty() || !table.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        return Err(format!("invalid fallback table name: {table:?}"));
    }
    Ok(())
}

#[derive(Debug)]
pub enum LoadError {
    /// Shared, because one failed statement answers every load it carried.
    Query(Arc<sqlx::Error>),
    /// A retry reads the same bytes.
    UnprocessableProperties {
        reason: String,
        /// The row without its properties.
        row: Box<CachedPerson>,
    },
}

impl std::fmt::Display for LoadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Query(e) => e.fmt(f),
            Self::UnprocessableProperties { reason, .. } => f.write_str(reason),
        }
    }
}

impl From<sqlx::Error> for LoadError {
    fn from(e: sqlx::Error) -> Self {
        Self::Query(Arc::new(e))
    }
}

fn parse_stored_properties(
    properties_text: &str,
    team_id: i32,
    id: i64,
) -> Result<serde_json::Value, String> {
    match serde_json::from_str(properties_text) {
        Ok(value) => Ok(value),
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
                    Ok(value)
                }
                Err(rewritten_err) => Err(format!(
                    "person properties unparseable (team_id={team_id}, person_id={id}): \
                     {strict_err}; after numeric rewrite: {rewritten_err}"
                )),
            }
        }
    }
}

/// properties comes back as text and is parsed here rather than through
/// sqlx's jsonb decode: rows written by other services can hold numerics
/// whose PG-expanded rendering serde_json rejects, and the leniency
/// lives in our parse step (see `parse_stored_properties`). The cost is
/// identical — sqlx's jsonb decode parses the same text under the hood.
pub(crate) const PERSON_ROW_COLUMNS: &str = "p.id, p.team_id, p.uuid::text AS uuid, \
     p.properties::text AS properties, p.created_at, p.version, p.is_identified, p.last_seen_at";

pub(crate) fn decode_person_row(
    row: &PgRow,
    key: &PersonCacheKey,
) -> Result<CachedPerson, LoadError> {
    let id: i64 = row.try_get("id")?;
    let team_id: i32 = row.try_get("team_id")?;
    // One statement serves many loads, and a misrouted row would serve
    // one person's state as another's.
    if id != key.person_id || i64::from(team_id) != key.team_id {
        return Err(sqlx::Error::Protocol(format!(
            "loaded row (team_id={team_id}, person_id={id}) is not the requested person \
             (team_id={}, person_id={})",
            key.team_id, key.person_id
        ))
        .into());
    }
    let uuid: String = row.try_get("uuid")?;
    // Borrowed from the row buffer — no copy; parse cost matches what
    // sqlx's own jsonb decode would spend on the same bytes.
    let properties_text: &str = row.try_get("properties")?;
    let created_at: chrono::DateTime<chrono::Utc> = row.try_get("created_at")?;
    let version: Option<i64> = row.try_get("version")?;
    let is_identified: bool = row.try_get("is_identified")?;
    let last_seen_at: Option<chrono::DateTime<chrono::Utc>> = row.try_get("last_seen_at")?;

    let properties = parse_stored_properties(properties_text, team_id, id).map_err(|reason| {
        LoadError::UnprocessableProperties {
            reason,
            row: Box::new(CachedPerson {
                id,
                uuid: uuid.clone(),
                team_id: team_id as i64,
                properties: Vec::new(),
                created_at: created_at.timestamp_millis(),
                version: version.unwrap_or(0),
                is_identified,
                is_deleted: false,
                last_seen_at: last_seen_at.map(|t| t.timestamp_millis()),
            }),
        }
    })?;

    let properties_bytes = serde_json::to_vec(&properties).map_err(|e| {
        LoadError::from(sqlx::Error::Protocol(format!(
            "person properties reserialize failed (team_id={team_id}, person_id={id}): {e}"
        )))
    })?;
    Ok(CachedPerson {
        id,
        uuid,
        team_id: team_id as i64,
        properties: properties_bytes,
        created_at: created_at.timestamp_millis(),
        version: version.unwrap_or(0),
        is_identified,
        // The query filters is_deleted = false; a tombstoned row is
        // answered as not-found above, never loaded.
        is_deleted: false,
        last_seen_at: last_seen_at.map(|t| t.timestamp_millis()),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn properties_nested_past_the_parser_limit_are_unprocessable() {
        let nested = format!("{{\"a\":{}1{}}}", "[".repeat(200), "]".repeat(200));
        assert!(parse_stored_properties(&nested, 1, 1).is_err());
    }
}
