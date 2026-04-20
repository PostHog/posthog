use chrono::{DateTime, TimeZone, Utc};
use metrics::{counter, histogram};
use personhog_proto::personhog::types::v1::Person;
use sqlx::postgres::PgPool;
use tracing::{error, warn};

use crate::store::{WriteError, WriteErrorKind};

/// Allowed target tables for person upserts.
const ALLOWED_TABLES: &[&str] = &["personhog_person_tmp", "posthog_person"];

/// Low-level Postgres execution layer. Runs queries, converts types,
/// classifies errors. No business logic, no retry, no trimming.
pub struct PgStore {
    pool: PgPool,
    upsert_batch_size: usize,
    upsert_sql: String,
}

impl PgStore {
    pub fn new(pool: PgPool, upsert_batch_size: usize, table_name: String) -> Self {
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

        Self {
            pool,
            upsert_batch_size,
            upsert_sql,
        }
    }

    /// Execute a batch upsert, chunking as needed.
    pub async fn execute_batch(&self, persons: &[Person]) -> Result<(), WriteError> {
        let start = std::time::Instant::now();

        for chunk in persons.chunks(self.upsert_batch_size) {
            self.execute_chunk(chunk).await?;
        }

        histogram!("personhog_writer_flush_duration_seconds").record(start.elapsed().as_secs_f64());
        histogram!("personhog_writer_flush_rows").record(persons.len() as f64);

        Ok(())
    }

    /// Execute a single-row upsert. If `properties_override` is provided,
    /// uses that JSON string instead of the person's proto bytes.
    pub async fn execute_row(
        &self,
        person: &Person,
        properties_override: Option<&str>,
    ) -> Result<(), WriteError> {
        let Some(mut prepared) = PreparedPerson::try_from(person) else {
            return Ok(()); // Invalid input, already logged
        };

        if let Some(props) = properties_override {
            prepared.properties = props.to_owned();
        }

        let arrays = PreparedArrays::from_single(&prepared);
        self.run_upsert(&arrays).await.map_err(|e| {
            let kind = classify_error(&e);
            WriteError {
                message: e.to_string(),
                kind,
            }
        })?;

        Ok(())
    }

    async fn execute_chunk(&self, persons: &[Person]) -> Result<(), WriteError> {
        if persons.is_empty() {
            return Ok(());
        }

        let prepared: Vec<PreparedPerson> = persons
            .iter()
            .filter_map(PreparedPerson::try_from)
            .collect();

        if prepared.is_empty() {
            return Ok(());
        }

        let arrays = PreparedArrays::from_batch(&prepared);
        let chunk_size = prepared.len() as u64;

        match self.run_upsert(&arrays).await {
            Ok(affected) => {
                counter!("personhog_writer_rows_upserted_total").increment(affected);
                let skipped = chunk_size.saturating_sub(affected);
                if skipped > 0 {
                    counter!("personhog_writer_rows_version_skipped_total").increment(skipped);
                }
                Ok(())
            }
            Err(e) => {
                let kind = classify_error(&e);
                counter!("personhog_writer_upsert_errors_total").increment(1);
                error!(error = %e, error_kind = ?kind, "batch upsert failed");
                Err(WriteError {
                    message: e.to_string(),
                    kind,
                })
            }
        }
    }

    async fn run_upsert(&self, arrays: &PreparedArrays) -> Result<u64, sqlx::Error> {
        let result = sqlx::query(&self.upsert_sql)
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
            .execute(&self.pool)
            .await?;

        Ok(result.rows_affected())
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

// ── Type conversion ─────────────────────────────────────────────

struct PreparedPerson {
    id: i64,
    team_id: i32,
    uuid: uuid::Uuid,
    properties: String,
    properties_last_updated_at: Option<String>,
    properties_last_operation: Option<String>,
    created_at: DateTime<Utc>,
    version: Option<i64>,
    is_identified: bool,
    last_seen_at: Option<DateTime<Utc>>,
}

impl PreparedPerson {
    fn try_from(person: &Person) -> Option<Self> {
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

        Some(Self {
            id: person.id,
            team_id: person.team_id as i32,
            uuid,
            properties: bytes_to_json_string(&person.properties, "{}"),
            properties_last_updated_at: bytes_to_optional_json_string(
                &person.properties_last_updated_at,
            ),
            properties_last_operation: bytes_to_optional_json_string(
                &person.properties_last_operation,
            ),
            created_at: epoch_secs_to_datetime(person.created_at),
            version: Some(person.version),
            is_identified: person.is_identified,
            last_seen_at: person.last_seen_at.map(epoch_secs_to_datetime),
        })
    }
}

struct PreparedArrays {
    ids: Vec<i64>,
    team_ids: Vec<i32>,
    uuids: Vec<uuid::Uuid>,
    properties: Vec<String>,
    properties_last_updated_at: Vec<Option<String>>,
    properties_last_operation: Vec<Option<String>>,
    created_at: Vec<DateTime<Utc>>,
    versions: Vec<Option<i64>>,
    is_identified: Vec<bool>,
    last_seen_at: Vec<Option<DateTime<Utc>>>,
}

impl PreparedArrays {
    fn from_batch(persons: &[PreparedPerson]) -> Self {
        let mut arrays = Self {
            ids: Vec::with_capacity(persons.len()),
            team_ids: Vec::with_capacity(persons.len()),
            uuids: Vec::with_capacity(persons.len()),
            properties: Vec::with_capacity(persons.len()),
            properties_last_updated_at: Vec::with_capacity(persons.len()),
            properties_last_operation: Vec::with_capacity(persons.len()),
            created_at: Vec::with_capacity(persons.len()),
            versions: Vec::with_capacity(persons.len()),
            is_identified: Vec::with_capacity(persons.len()),
            last_seen_at: Vec::with_capacity(persons.len()),
        };

        for p in persons {
            arrays.ids.push(p.id);
            arrays.team_ids.push(p.team_id);
            arrays.uuids.push(p.uuid);
            arrays.properties.push(p.properties.clone());
            arrays
                .properties_last_updated_at
                .push(p.properties_last_updated_at.clone());
            arrays
                .properties_last_operation
                .push(p.properties_last_operation.clone());
            arrays.created_at.push(p.created_at);
            arrays.versions.push(p.version);
            arrays.is_identified.push(p.is_identified);
            arrays.last_seen_at.push(p.last_seen_at);
        }

        arrays
    }

    fn from_single(person: &PreparedPerson) -> Self {
        Self {
            ids: vec![person.id],
            team_ids: vec![person.team_id],
            uuids: vec![person.uuid],
            properties: vec![person.properties.clone()],
            properties_last_updated_at: vec![person.properties_last_updated_at.clone()],
            properties_last_operation: vec![person.properties_last_operation.clone()],
            created_at: vec![person.created_at],
            versions: vec![person.version],
            is_identified: vec![person.is_identified],
            last_seen_at: vec![person.last_seen_at],
        }
    }
}

/// Interpret proto bytes as a JSON string. The leader serializes via
/// serde_json::RawValue, so these are already valid JSON UTF-8. We pass
/// them through to PG as text and let the `::jsonb` cast validate.
fn bytes_to_json_string(bytes: &[u8], default: &str) -> String {
    if bytes.is_empty() {
        return default.to_owned();
    }
    match std::str::from_utf8(bytes) {
        Ok(s) => s.to_owned(),
        Err(e) => {
            counter!("personhog_writer_invalid_json_total").increment(1);
            warn!(error = %e, "non-UTF8 in JSON field, using default");
            default.to_owned()
        }
    }
}

fn bytes_to_optional_json_string(bytes: &[u8]) -> Option<String> {
    if bytes.is_empty() {
        return None;
    }
    match std::str::from_utf8(bytes) {
        Ok(s) => Some(s.to_owned()),
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
    fn bytes_to_json_string_valid() {
        let s = bytes_to_json_string(b"{\"email\":\"test@example.com\"}", "{}");
        assert_eq!(s, "{\"email\":\"test@example.com\"}");
    }

    #[test]
    fn bytes_to_json_string_empty_returns_default() {
        let s = bytes_to_json_string(b"", "{}");
        assert_eq!(s, "{}");
    }

    #[test]
    fn bytes_to_optional_json_string_empty_returns_none() {
        assert!(bytes_to_optional_json_string(b"").is_none());
    }

    #[test]
    fn bytes_to_optional_json_string_valid() {
        let s = bytes_to_optional_json_string(b"{\"key\":\"val\"}");
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
        let _store = PgStore::new(pool.clone(), 500, "personhog_person_tmp".to_string());
        let _store = PgStore::new(pool, 500, "posthog_person".to_string());
    }

    #[tokio::test]
    #[should_panic(expected = "PG_TARGET_TABLE must be one of")]
    async fn table_name_allowlist_rejects_invalid() {
        let pool = PgPool::connect_lazy("postgres://localhost/test").unwrap();
        let _store = PgStore::new(
            pool,
            500,
            "evil_table; DROP TABLE posthog_person".to_string(),
        );
    }
}
