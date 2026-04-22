use async_trait::async_trait;
use chrono::{DateTime, TimeZone, Utc};
use metrics::counter;
use personhog_proto::personhog::types::v1::Person;
use sqlx::postgres::PgPool;
use tracing::{error, warn};

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
        let arrays = prepare_chunk(chunk);
        run_upsert(&self.pool, &self.upsert_sql, &arrays, "chunk").await
    }

    async fn execute_row(
        &self,
        person: &Person,
        properties_override: Option<&str>,
    ) -> Result<(), WriteError> {
        let Some(arrays) = prepare_single(person, properties_override) else {
            return Ok(()); // Invalid input, already logged
        };
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
fn prepare_chunk(persons: &[Person]) -> PreparedArrays<'_> {
    let cap = persons.len();
    let mut arrays = PreparedArrays::with_capacity(cap);

    for p in persons {
        let uuid = match uuid::Uuid::parse_str(&p.uuid) {
            Ok(u) => u,
            Err(e) => {
                counter!("personhog_writer_invalid_uuid_total").increment(1);
                warn!(
                    team_id = p.team_id,
                    person_id = p.id,
                    uuid = %p.uuid,
                    error = %e,
                    "skipping person with invalid UUID"
                );
                continue;
            }
        };

        let team_id = match i32::try_from(p.team_id) {
            Ok(t) => t,
            Err(_) => {
                counter!("personhog_writer_invalid_team_id_total").increment(1);
                warn!(
                    team_id = p.team_id,
                    person_id = p.id,
                    "skipping person with out-of-range team_id (exceeds i32)"
                );
                continue;
            }
        };

        arrays.push(
            p.id,
            team_id,
            uuid,
            bytes_to_json_str(&p.properties, "{}"),
            bytes_to_optional_json_str(&p.properties_last_updated_at),
            bytes_to_optional_json_str(&p.properties_last_operation),
            epoch_secs_to_datetime(p.created_at),
            Some(p.version),
            p.is_identified,
            p.last_seen_at.map(epoch_secs_to_datetime),
        );
    }

    arrays
}

/// Build a single-row PreparedArrays for the per-row path. Returns None if
/// the person has an invalid UUID (already logged).
fn prepare_single<'a>(
    person: &'a Person,
    properties_override: Option<&'a str>,
) -> Option<PreparedArrays<'a>> {
    let uuid = match uuid::Uuid::parse_str(&person.uuid) {
        Ok(u) => u,
        Err(e) => {
            counter!("personhog_writer_invalid_uuid_total").increment(1);
            warn!(
                team_id = person.team_id,
                person_id = person.id,
                uuid = %person.uuid,
                error = %e,
                "skipping person with invalid UUID"
            );
            return None;
        }
    };

    let team_id = match i32::try_from(person.team_id) {
        Ok(t) => t,
        Err(_) => {
            counter!("personhog_writer_invalid_team_id_total").increment(1);
            warn!(
                team_id = person.team_id,
                person_id = person.id,
                "skipping person with out-of-range team_id (exceeds i32)"
            );
            return None;
        }
    };

    let properties = match properties_override {
        Some(s) => s,
        None => bytes_to_json_str(&person.properties, "{}"),
    };

    let mut arrays = PreparedArrays::with_capacity(1);
    arrays.push(
        person.id,
        team_id,
        uuid,
        properties,
        bytes_to_optional_json_str(&person.properties_last_updated_at),
        bytes_to_optional_json_str(&person.properties_last_operation),
        epoch_secs_to_datetime(person.created_at),
        Some(person.version),
        person.is_identified,
        person.last_seen_at.map(epoch_secs_to_datetime),
    );
    Some(arrays)
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
struct PreparedArrays<'a> {
    ids: Vec<i64>,
    team_ids: Vec<i32>,
    uuids: Vec<uuid::Uuid>,
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
        uuid: uuid::Uuid,
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

/// Interpret proto bytes as a JSON string. The leader serializes via
/// serde_json::RawValue, so these are already valid JSON UTF-8. We pass
/// them through to PG as text and let the `::jsonb` cast validate. Returns
/// a borrow into `bytes`; on invalid UTF-8 or empty input, the static
/// default (coerces to any lifetime).
fn bytes_to_json_str<'a>(bytes: &'a [u8], default: &'static str) -> &'a str {
    if bytes.is_empty() {
        return default;
    }
    match std::str::from_utf8(bytes) {
        Ok(s) => s,
        Err(e) => {
            counter!("personhog_writer_invalid_json_total").increment(1);
            warn!(error = %e, "non-UTF8 in JSON field, using default");
            default
        }
    }
}

fn bytes_to_optional_json_str(bytes: &[u8]) -> Option<&str> {
    if bytes.is_empty() {
        return None;
    }
    match std::str::from_utf8(bytes) {
        Ok(s) => Some(s),
        Err(e) => {
            counter!("personhog_writer_invalid_json_total").increment(1);
            warn!(error = %e, "non-UTF8 in optional JSON field, treating as null");
            None
        }
    }
}

fn epoch_secs_to_datetime(epoch_secs: i64) -> DateTime<Utc> {
    Utc.timestamp_opt(epoch_secs, 0)
        .single()
        .unwrap_or_default()
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
        let s = bytes_to_json_str(b"{\"email\":\"test@example.com\"}", "{}");
        assert_eq!(s, "{\"email\":\"test@example.com\"}");
    }

    #[test]
    fn bytes_to_json_str_empty_returns_default() {
        let s = bytes_to_json_str(b"", "{}");
        assert_eq!(s, "{}");
    }

    #[test]
    fn bytes_to_optional_json_str_empty_returns_none() {
        assert!(bytes_to_optional_json_str(b"").is_none());
    }

    #[test]
    fn bytes_to_optional_json_str_valid() {
        let s = bytes_to_optional_json_str(b"{\"key\":\"val\"}");
        assert_eq!(s.unwrap(), "{\"key\":\"val\"}");
    }

    #[test]
    fn epoch_secs_conversion() {
        let dt = epoch_secs_to_datetime(1700000000);
        assert_eq!(dt.timestamp(), 1700000000);
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
            uuid: uuid::Uuid::new_v4().to_string(),
            version: 1,
            ..Default::default()
        }
    }

    #[test]
    fn prepare_chunk_skips_out_of_range_team_id() {
        let good = person_with(1, 42);
        let bad = person_with(2, (i32::MAX as i64) + 1);

        let persons = [good, bad];
        let arrays = prepare_chunk(&persons);
        // Only the in-range person made it into the bind arrays.
        assert_eq!(arrays.ids, vec![1]);
        assert_eq!(arrays.team_ids, vec![42]);
    }

    #[test]
    fn prepare_single_rejects_out_of_range_team_id() {
        let bad = person_with(1, (i32::MAX as i64) + 1);
        assert!(prepare_single(&bad, None).is_none());
    }
}
