use std::io;
use std::time::{Duration, Instant};

use metrics::{counter, histogram};
use personhog_common::properties::rewrite_out_of_range_numbers;
use personhog_common::query_tag;
use sqlx::pool::PoolConnection;
use sqlx::postgres::{PgPool, PgRow};
use sqlx::{Connection, Postgres, Row};
use tokio::time::error::Elapsed;
use tokio::time::timeout_at;

use crate::cache::{CachedPerson, PersonCacheKey};

pub const STATEMENT_TIMEOUT_MS: u64 = 5_000;

/// Past the statement timeout, so only a query on a socket that never answers reaches it.
pub const QUERY_DEADLINE: Duration = Duration::from_millis(STATEMENT_TIMEOUT_MS + 1_000);

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

/// The error a pooled connection returns after its pgbouncer pod closed it. Excludes the
/// `TimedOut` that `release_or_discard` returns, so a load never retries after its deadline.
pub fn is_severed(e: &sqlx::Error) -> bool {
    matches!(
        e,
        sqlx::Error::Io(io) if matches!(
            io.kind(),
            io::ErrorKind::UnexpectedEof
                | io::ErrorKind::ConnectionReset
                | io::ErrorKind::ConnectionAborted
                | io::ErrorKind::BrokenPipe
                | io::ErrorKind::NotConnected
        )
    )
}

/// A connection whose query timed out may sit on a socket that never answers. sqlx pings a
/// connection it takes back, and that ping would wait on the same socket while it holds the
/// pool slot, so a timed-out connection leaves the pool instead.
pub fn release_or_discard<T>(
    conn: PoolConnection<Postgres>,
    outcome: Result<Result<T, sqlx::Error>, Elapsed>,
    caller: &'static str,
) -> Result<T, sqlx::Error> {
    match outcome {
        Ok(Err(e)) if is_severed(&e) => {
            drop(conn.detach());
            Err(e)
        }
        Ok(result) => result,
        Err(_) => {
            counter!("personhog_leader_fallback_query_timeouts_total", "caller" => caller)
                .increment(1);
            drop(conn.detach());
            Err(deadline_error(caller))
        }
    }
}

fn deadline_error(caller: &str) -> sqlx::Error {
    sqlx::Error::Io(io::Error::new(
        io::ErrorKind::TimedOut,
        format!("{caller} got no answer before its deadline"),
    ))
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
    Query(sqlx::Error),
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
        Self::Query(e)
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

/// Reads a person from the configured fallback table — the table the
/// writer maintains. Used as a fallback when the leader's cache doesn't
/// have the person.
pub async fn load_person_from_pg(
    pool: &PgPool,
    table: &str,
    key: &PersonCacheKey,
) -> Result<Option<CachedPerson>, LoadError> {
    let start = Instant::now();

    let team_id_i32 = i32::try_from(key.team_id)
        .map_err(|_| sqlx::Error::Protocol(format!("team_id {} exceeds i32 range", key.team_id)))
        .map_err(LoadError::Query)?;

    // properties comes back as text and is parsed here rather than through
    // sqlx's jsonb decode: rows written by other services can hold numerics
    // whose PG-expanded rendering serde_json rejects, and the leniency
    // lives in our parse step (see below). The cost is identical — sqlx's
    // jsonb decode parses the same text under the hood.
    // A tombstoned person must not be re-served on a cache miss; not-found
    // is the truthful answer for a deleted person.
    let sql = query_tag!(
        "load_person",
        format!(
            "SELECT id, team_id, uuid::text, properties::text AS properties, created_at, version, \
             is_identified, last_seen_at
             FROM {table}
             WHERE team_id = $1 AND id = $2 AND is_deleted = false",
        )
    );
    let row = match fetch_person_row(pool, &sql, team_id_i32, key.person_id).await {
        Err(e) if is_severed(&e) => {
            counter!("personhog_leader_fallback_reconnects_total", "caller" => "load_person")
                .increment(1);
            refetch_on_live_connection(pool, &sql, team_id_i32, key.person_id).await?
        }
        result => result?,
    };

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

    counter!("personhog_leader_pg_fallback_total", "outcome" => "found").increment(1);

    let properties_bytes = serde_json::to_vec(&properties).map_err(|e| {
        LoadError::Query(sqlx::Error::Protocol(format!(
            "person properties reserialize failed (team_id={team_id}, person_id={id}): {e}"
        )))
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

/// The row is owned, so the caller parses its properties after the pool slot is free.
async fn fetch_person_row(
    pool: &PgPool,
    sql: &str,
    team_id: i32,
    person_id: i64,
) -> Result<Option<PgRow>, sqlx::Error> {
    let mut conn = acquire_timed(pool, "load_person").await?;
    let query = sqlx::query(sql).bind(team_id).bind(person_id);
    let outcome = tokio::time::timeout(QUERY_DEADLINE, query.fetch_optional(&mut *conn)).await;
    release_or_discard(conn, outcome, "load_person")
}

/// The pool skips the ping on recently used connections, and a leaving pgbouncer pod closes many
/// at once. One deadline covers the whole retry, so the caller's per-key lock waits one deadline.
async fn refetch_on_live_connection(
    pool: &PgPool,
    sql: &str,
    team_id: i32,
    person_id: i64,
) -> Result<Option<PgRow>, sqlx::Error> {
    let deadline = tokio::time::Instant::now() + QUERY_DEADLINE;
    let mut conn = loop {
        let Ok(acquired) = timeout_at(deadline, acquire_timed(pool, "load_person")).await else {
            return Err(deadline_error("load_person"));
        };
        let mut conn = acquired?;
        match timeout_at(deadline, conn.ping()).await {
            Ok(Ok(())) => break conn,
            Ok(Err(e)) if is_severed(&e) => drop(conn.detach()),
            outcome => return release_or_discard(conn, outcome, "load_person").map(|()| None),
        }
    };
    let query = sqlx::query(sql).bind(team_id).bind(person_id);
    let outcome = timeout_at(deadline, query.fetch_optional(&mut *conn)).await;
    release_or_discard(conn, outcome, "load_person")
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
