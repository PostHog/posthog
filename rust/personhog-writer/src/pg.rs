use async_trait::async_trait;
use std::str::from_utf8;

use chrono::{DateTime, TimeZone, Utc};
use metrics::counter;
use personhog_proto::personhog::types::v1::Person;
use sqlx::postgres::PgPool;
use tracing::error;
use uuid::Uuid;

use crate::error::{WriteError, WriteErrorKind};
use crate::store::PersonDb;

/// Allowed target tables for person upserts.
const ALLOWED_TABLES: &[&str] = &["personhog_person_tmp", "posthog_person"];

/// Low-level Postgres execution layer. Runs single upsert statements and
/// classifies sqlx errors. No batching, no parallelism, no retry — those
/// live in the store layer.
pub struct PgStore {
    pool: PgPool,
    upsert_sql: String,
}

#[async_trait]
impl PersonDb for PgStore {
    async fn execute_chunk(&self, chunk: &[Person]) -> Result<(), WriteError> {
        let arrays = prepare_chunk(chunk)?;
        run_upsert(&self.pool, &self.upsert_sql, &arrays, "chunk").await
    }

    async fn execute_row(&self, person: &Person) -> Result<(), WriteError> {
        let arrays = prepare_single(person)?;
        run_upsert(&self.pool, &self.upsert_sql, &arrays, "row").await
    }
}

impl PgStore {
    pub fn new(pool: PgPool, table_name: String) -> Self {
        assert!(
            ALLOWED_TABLES.contains(&table_name.as_str()),
            "PG_TARGET_TABLE must be one of {:?}, got: {table_name}",
            ALLOWED_TABLES
        );

        let upsert_sql = format!(
            "INSERT INTO {table} (
                id, team_id, uuid, properties, properties_last_updated_at,
                properties_last_operation, created_at, version, is_identified,
                last_seen_at
            )
            SELECT id, team_id, uuid, properties::jsonb,
                   properties_last_updated_at::jsonb, properties_last_operation::jsonb,
                   created_at, version, is_identified, last_seen_at
            FROM UNNEST(
                $1::bigint[], $2::int[], $3::uuid[],
                $4::text[], $5::text[], $6::text[],
                $7::timestamptz[], $8::bigint[], $9::bool[], $10::timestamptz[]
            ) AS u(id, team_id, uuid, properties, properties_last_updated_at,
                   properties_last_operation, created_at, version, is_identified, last_seen_at)
            ON CONFLICT (team_id, id) DO UPDATE SET
                uuid = EXCLUDED.uuid,
                properties = EXCLUDED.properties,
                properties_last_updated_at = EXCLUDED.properties_last_updated_at,
                properties_last_operation = EXCLUDED.properties_last_operation,
                created_at = EXCLUDED.created_at,
                version = EXCLUDED.version,
                is_identified = EXCLUDED.is_identified,
                last_seen_at = EXCLUDED.last_seen_at
            WHERE EXCLUDED.version > COALESCE({table}.version, -1)",
            table = table_name
        );

        Self { pool, upsert_sql }
    }
}

/// Build bind arrays from a slice of persons. Borrows string data directly
/// from each Person's byte buffers; `PreparedArrays` is tied to the slice's
/// lifetime and must not outlive `persons`.
///
/// Any field that cannot be bound losslessly (malformed uuid, team_id
/// beyond the column's `integer` range, non-UTF-8 JSON bytes, timestamp
/// outside chrono's range) is a `Data` error: the record is unapplyable
/// as produced, which post-admission is an invariant violation the caller
/// must halt on. Nothing is ever dropped or substituted here — a silent
/// repair would diverge PG from the cache and changelog.
fn prepare_chunk(persons: &[Person]) -> Result<PreparedArrays<'_>, WriteError> {
    let cap = persons.len();
    let mut arrays = PreparedArrays::with_capacity(cap);
    for person in persons {
        push_person(&mut arrays, person)?;
    }
    Ok(arrays)
}

/// Build a single-row `PreparedArrays` for the per-row path.
fn prepare_single(person: &Person) -> Result<PreparedArrays<'_>, WriteError> {
    let mut arrays = PreparedArrays::with_capacity(1);
    push_person(&mut arrays, person)?;
    Ok(arrays)
}

fn push_person<'a>(arrays: &mut PreparedArrays<'a>, p: &'a Person) -> Result<(), WriteError> {
    let unbindable = |field: &str, detail: String| {
        counter!("personhog_writer_unbindable_field_total", "field" => field.to_string())
            .increment(1);
        WriteError {
            message: format!(
                "unbindable {field} for team_id={} person_id={}: {detail}",
                p.team_id, p.id
            ),
            kind: WriteErrorKind::Data,
        }
    };

    let uuid = Uuid::parse_str(&p.uuid).map_err(|e| unbindable("uuid", e.to_string()))?;
    let team_id = i32::try_from(p.team_id)
        .map_err(|_| unbindable("team_id", "exceeds the column's integer range".to_string()))?;
    let properties =
        bytes_to_json_str(&p.properties, "{}").map_err(|e| unbindable("properties", e))?;
    let properties_last_updated_at = bytes_to_optional_json_str(&p.properties_last_updated_at)
        .map_err(|e| unbindable("properties_last_updated_at", e))?;
    let properties_last_operation = bytes_to_optional_json_str(&p.properties_last_operation)
        .map_err(|e| unbindable("properties_last_operation", e))?;
    let created_at = epoch_secs_to_datetime(p.created_at)
        .ok_or_else(|| unbindable("created_at", format!("epoch {} out of range", p.created_at)))?;
    let last_seen_at = match p.last_seen_at {
        None => None,
        Some(secs) => Some(
            epoch_secs_to_datetime(secs)
                .ok_or_else(|| unbindable("last_seen_at", format!("epoch {secs} out of range")))?,
        ),
    };

    arrays.push(
        p.id,
        team_id,
        uuid,
        properties,
        properties_last_updated_at,
        properties_last_operation,
        created_at,
        Some(p.version),
        p.is_identified,
        last_seen_at,
    );
    Ok(())
}

async fn run_upsert(
    pool: &PgPool,
    sql: &str,
    arrays: &PreparedArrays<'_>,
    mode: &'static str,
) -> Result<(), WriteError> {
    let chunk_size = arrays.ids.len() as u64;
    if chunk_size == 0 {
        return Ok(());
    }

    match sqlx::query(sql)
        .bind(&arrays.ids)
        .bind(&arrays.team_ids)
        .bind(&arrays.uuids)
        .bind(&arrays.properties)
        .bind(&arrays.properties_last_updated_at)
        .bind(&arrays.properties_last_operation)
        .bind(&arrays.created_at)
        .bind(&arrays.versions)
        .bind(&arrays.is_identified)
        .bind(&arrays.last_seen_at)
        .execute(pool)
        .await
    {
        Ok(result) => {
            let affected = result.rows_affected();
            counter!("personhog_writer_rows_upserted_total", "mode" => mode).increment(affected);
            let skipped = chunk_size.saturating_sub(affected);
            if skipped > 0 {
                counter!("personhog_writer_rows_version_skipped_total", "mode" => mode)
                    .increment(skipped);
            }
            Ok(())
        }
        Err(e) => {
            let kind = classify_error(&e);
            counter!("personhog_writer_upsert_errors_total", "mode" => mode).increment(1);
            error!(error = %e, error_kind = ?kind, mode, "upsert failed");
            Err(WriteError {
                message: e.to_string(),
                kind,
            })
        }
    }
}

fn classify_error(e: &sqlx::Error) -> WriteErrorKind {
    match e {
        sqlx::Error::Io(_)
        | sqlx::Error::PoolTimedOut
        | sqlx::Error::PoolClosed
        | sqlx::Error::WorkerCrashed => WriteErrorKind::Transient,

        sqlx::Error::Database(db_err) => {
            if let Some(code) = db_err.code() {
                let code_str = code.as_ref();
                if code_str == "23514" {
                    if let Some(constraint) = db_err.constraint() {
                        if constraint.contains("check_properties_size") {
                            return WriteErrorKind::PropertiesSizeViolation;
                        }
                    }
                }
                if code_str.starts_with("08")
                    || code_str.starts_with("53")
                    || code_str.starts_with("57")
                    || code_str == "40P01"
                {
                    return WriteErrorKind::Transient;
                }
            }
            WriteErrorKind::Data
        }

        _ => WriteErrorKind::Data,
    }
}

// ── Bind arrays ─────────────────────────────────────────────────

/// Column-oriented bind arrays for the upsert statement. String fields
/// borrow from each Person's byte buffer to avoid per-row allocations; the
/// struct's lifetime is tied to the source slice.
#[derive(Debug)]
struct PreparedArrays<'a> {
    ids: Vec<i64>,
    team_ids: Vec<i32>,
    uuids: Vec<Uuid>,
    properties: Vec<&'a str>,
    properties_last_updated_at: Vec<Option<&'a str>>,
    properties_last_operation: Vec<Option<&'a str>>,
    created_at: Vec<DateTime<Utc>>,
    versions: Vec<Option<i64>>,
    is_identified: Vec<bool>,
    last_seen_at: Vec<Option<DateTime<Utc>>>,
}

impl<'a> PreparedArrays<'a> {
    fn with_capacity(cap: usize) -> Self {
        Self {
            ids: Vec::with_capacity(cap),
            team_ids: Vec::with_capacity(cap),
            uuids: Vec::with_capacity(cap),
            properties: Vec::with_capacity(cap),
            properties_last_updated_at: Vec::with_capacity(cap),
            properties_last_operation: Vec::with_capacity(cap),
            created_at: Vec::with_capacity(cap),
            versions: Vec::with_capacity(cap),
            is_identified: Vec::with_capacity(cap),
            last_seen_at: Vec::with_capacity(cap),
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn push(
        &mut self,
        id: i64,
        team_id: i32,
        uuid: Uuid,
        properties: &'a str,
        properties_last_updated_at: Option<&'a str>,
        properties_last_operation: Option<&'a str>,
        created_at: DateTime<Utc>,
        version: Option<i64>,
        is_identified: bool,
        last_seen_at: Option<DateTime<Utc>>,
    ) {
        self.ids.push(id);
        self.team_ids.push(team_id);
        self.uuids.push(uuid);
        self.properties.push(properties);
        self.properties_last_updated_at
            .push(properties_last_updated_at);
        self.properties_last_operation
            .push(properties_last_operation);
        self.created_at.push(created_at);
        self.versions.push(version);
        self.is_identified.push(is_identified);
        self.last_seen_at.push(last_seen_at);
    }
}

/// Interpret proto bytes as a JSON string. The leader serializes a parsed
/// `serde_json::Value`, so these are valid JSON UTF-8 by construction; the
/// `::jsonb` cast in the statement re-validates at PG. Empty bytes are the
/// proto default and decode to `default`. Invalid UTF-8 is an error, never
/// a substitution.
fn bytes_to_json_str<'a>(bytes: &'a [u8], default: &'static str) -> Result<&'a str, String> {
    if bytes.is_empty() {
        return Ok(default);
    }
    from_utf8(bytes).map_err(|e| format!("non-UTF-8 JSON bytes: {e}"))
}

fn bytes_to_optional_json_str(bytes: &[u8]) -> Result<Option<&str>, String> {
    if bytes.is_empty() {
        return Ok(None);
    }
    from_utf8(bytes)
        .map(Some)
        .map_err(|e| format!("non-UTF-8 JSON bytes: {e}"))
}

fn epoch_secs_to_datetime(epoch_secs: i64) -> Option<DateTime<Utc>> {
    Utc.timestamp_opt(epoch_secs, 0).single()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classify_pool_timeout_as_transient() {
        assert!(matches!(
            classify_error(&sqlx::Error::PoolTimedOut),
            WriteErrorKind::Transient
        ));
    }

    #[test]
    fn classify_io_error_as_transient() {
        let err = sqlx::Error::Io(std::io::Error::new(
            std::io::ErrorKind::ConnectionReset,
            "connection reset",
        ));
        assert!(matches!(classify_error(&err), WriteErrorKind::Transient));
    }

    #[test]
    fn bytes_to_json_str_valid() {
        let s = bytes_to_json_str(b"{\"email\":\"test@example.com\"}", "{}").unwrap();
        assert_eq!(s, "{\"email\":\"test@example.com\"}");
    }

    #[test]
    fn bytes_to_json_str_empty_returns_default() {
        assert_eq!(bytes_to_json_str(b"", "{}").unwrap(), "{}");
    }

    #[test]
    fn bytes_to_json_str_rejects_invalid_utf8() {
        assert!(bytes_to_json_str(&[0xff, 0xfe], "{}").is_err());
    }

    #[test]
    fn bytes_to_optional_json_str_empty_returns_none() {
        assert!(bytes_to_optional_json_str(b"").unwrap().is_none());
    }

    #[test]
    fn bytes_to_optional_json_str_valid() {
        let s = bytes_to_optional_json_str(b"{\"key\":\"val\"}").unwrap();
        assert_eq!(s.unwrap(), "{\"key\":\"val\"}");
    }

    #[test]
    fn epoch_secs_conversion() {
        let dt = epoch_secs_to_datetime(1700000000).unwrap();
        assert_eq!(dt.timestamp(), 1700000000);
        assert!(epoch_secs_to_datetime(i64::MAX).is_none());
    }

    #[tokio::test]
    async fn table_name_allowlist_accepts_valid() {
        let pool = PgPool::connect_lazy("postgres://localhost/test").unwrap();
        let _store = PgStore::new(pool.clone(), "personhog_person_tmp".to_string());
        let _store = PgStore::new(pool, "posthog_person".to_string());
    }

    #[tokio::test]
    #[should_panic(expected = "PG_TARGET_TABLE must be one of")]
    async fn table_name_allowlist_rejects_invalid() {
        let pool = PgPool::connect_lazy("postgres://localhost/test").unwrap();
        let _store = PgStore::new(pool, "evil_table; DROP TABLE posthog_person".to_string());
    }

    fn person_with(id: i64, team_id: i64) -> Person {
        Person {
            id,
            team_id,
            uuid: Uuid::new_v4().to_string(),
            version: 1,
            ..Default::default()
        }
    }

    #[test]
    fn prepare_chunk_errors_on_out_of_range_team_id() {
        // One unbindable row fails the whole chunk: silently dropping it
        // would permanently diverge PG from the cache and changelog.
        let good = person_with(1, 42);
        let bad = person_with(2, (i32::MAX as i64) + 1);

        let persons = [good, bad];
        let err = prepare_chunk(&persons).expect_err("unbindable row must error");
        assert!(matches!(err.kind, WriteErrorKind::Data));
        assert!(err.message.contains("team_id"));
    }

    #[test]
    fn prepare_single_errors_on_malformed_uuid() {
        let mut bad = person_with(1, 42);
        bad.uuid = "not-a-uuid".to_string();
        let err = prepare_single(&bad).expect_err("malformed uuid must error");
        assert!(matches!(err.kind, WriteErrorKind::Data));
        assert!(err.message.contains("uuid"));
    }
}
