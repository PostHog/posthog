use std::time::Instant;

use metrics::{counter, histogram};
use personhog_common::properties::parse_stored_properties;
use sqlx::pool::PoolConnection;
use sqlx::postgres::PgPool;
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

/// Reads a person from the configured fallback table — the table the
/// writer maintains. Used as a fallback when the leader's cache doesn't
/// have the person.
pub async fn load_person_from_pg(
    pool: &PgPool,
    table: &str,
    key: &PersonCacheKey,
) -> Result<Option<CachedPerson>, sqlx::Error> {
    load_person_row(pool, table, key, "properties::text").await
}

pub async fn load_person_stub_from_pg(
    pool: &PgPool,
    table: &str,
    key: &PersonCacheKey,
) -> Result<Option<CachedPerson>, sqlx::Error> {
    load_person_row(pool, table, key, "'{}'::text").await
}

async fn load_person_row(
    pool: &PgPool,
    table: &str,
    key: &PersonCacheKey,
    properties_expr: &str,
) -> Result<Option<CachedPerson>, sqlx::Error> {
    let start = Instant::now();
    let mut conn = acquire_timed(pool, "load_person").await?;

    let team_id_i32 = i32::try_from(key.team_id)
        .map_err(|_| sqlx::Error::Protocol(format!("team_id {} exceeds i32 range", key.team_id)))?;

    // properties comes back as text and is parsed here rather than through
    // sqlx's jsonb decode: rows written by other services can hold numerics
    // whose PG-expanded rendering serde_json rejects, and the leniency
    // lives in our parse step (see below). The cost is identical — sqlx's
    // jsonb decode parses the same text under the hood.
    // A tombstoned person must not be re-served on a cache miss; not-found
    // is the truthful answer for a deleted person.
    let row = sqlx::query(&format!(
        "SELECT id, team_id, uuid::text, {properties_expr} AS properties, created_at, version, \
         is_identified, last_seen_at
         FROM {table}
         WHERE team_id = $1 AND id = $2 AND is_deleted = false",
    ))
    .bind(team_id_i32)
    .bind(key.person_id)
    .fetch_optional(&mut *conn)
    .await?;
    // The row is owned; parsing its properties must not hold the pool slot.
    drop(conn);

    histogram!("personhog_leader_pg_fallback_duration_ms")
        .record(start.elapsed().as_secs_f64() * 1000.0);

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
    let last_seen_at: Option<chrono::DateTime<chrono::Utc>> = row.get("last_seen_at");

    // Out-of-range numerics are rewritten to what JSON.parse reads, so the person stays loadable.
    let parsed = parse_stored_properties(properties_text).map_err(|e| {
        sqlx::Error::Protocol(format!(
            "person properties unparseable (team_id={team_id}, person_id={id}): {e}"
        ))
    })?;
    if parsed.rewritten {
        counter!("personhog_leader_pg_properties_rewritten_total").increment(1);
        tracing::warn!(
            team_id,
            person_id = id,
            "rewrote out-of-range numerics in stored person properties"
        );
    }
    let properties = parsed.value;

    counter!("personhog_leader_pg_fallback_total", "outcome" => "found").increment(1);

    let properties_bytes = serde_json::to_vec(&properties).map_err(|e| {
        sqlx::Error::Protocol(format!(
            "person properties reserialize failed (team_id={team_id}, person_id={id}): {e}"
        ))
    })?;
    Ok(Some(CachedPerson {
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
    }))
}
