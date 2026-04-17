use chrono::{DateTime, TimeZone, Utc};
use metrics::{counter, histogram};
use personhog_proto::personhog::types::v1::Person;
use sqlx::postgres::PgPool;
use sqlx::QueryBuilder;
use tracing::error;

pub struct PgWriter {
    pool: PgPool,
    upsert_batch_size: usize,
}

impl PgWriter {
    pub fn new(pool: PgPool, upsert_batch_size: usize) -> Self {
        Self {
            pool,
            upsert_batch_size,
        }
    }

    /// Batch upsert persons into the personhog_person table.
    /// Chunks the input to stay within Postgres parameter limits.
    pub async fn batch_upsert(&self, persons: &[Person]) -> Result<(), sqlx::Error> {
        let start = std::time::Instant::now();

        for chunk in persons.chunks(self.upsert_batch_size) {
            self.upsert_chunk(chunk).await?;
        }

        histogram!("personhog_writer_flush_duration_seconds").record(start.elapsed().as_secs_f64());
        histogram!("personhog_writer_flush_rows").record(persons.len() as f64);

        Ok(())
    }

    async fn upsert_chunk(&self, persons: &[Person]) -> Result<(), sqlx::Error> {
        if persons.is_empty() {
            return Ok(());
        }

        let mut qb: QueryBuilder<sqlx::Postgres> = QueryBuilder::new(
            "INSERT INTO personhog_person (
                id, team_id, uuid, properties, properties_last_updated_at,
                properties_last_operation, created_at, version, is_identified,
                last_seen_at
            ) ",
        );

        qb.push_values(persons, |mut b, person| {
            let uuid = parse_uuid(&person.uuid);
            let properties = parse_jsonb(&person.properties);
            let properties_last_updated_at =
                parse_optional_jsonb(&person.properties_last_updated_at);
            let properties_last_operation = parse_optional_jsonb(&person.properties_last_operation);
            let created_at = epoch_secs_to_datetime(person.created_at);
            let last_seen_at = person.last_seen_at.map(epoch_secs_to_datetime);

            b.push_bind(person.id)
                .push_bind(person.team_id as i32)
                .push_bind(uuid)
                .push_bind(properties)
                .push_bind(properties_last_updated_at)
                .push_bind(properties_last_operation)
                .push_bind(created_at)
                .push_bind(person.version)
                .push_bind(person.is_identified)
                .push_bind(last_seen_at);
        });

        qb.push(
            " ON CONFLICT (team_id, id) DO UPDATE SET
                uuid = EXCLUDED.uuid,
                properties = EXCLUDED.properties,
                properties_last_updated_at = EXCLUDED.properties_last_updated_at,
                properties_last_operation = EXCLUDED.properties_last_operation,
                created_at = EXCLUDED.created_at,
                version = EXCLUDED.version,
                is_identified = EXCLUDED.is_identified,
                last_seen_at = EXCLUDED.last_seen_at
            WHERE EXCLUDED.version > personhog_person.version",
        );

        let query = qb.build();
        match query.execute(&self.pool).await {
            Ok(result) => {
                counter!("personhog_writer_rows_upserted_total").increment(result.rows_affected());
                Ok(())
            }
            Err(e) => {
                counter!("personhog_writer_upsert_errors_total").increment(1);
                error!(error = %e, chunk_size = persons.len(), "batch upsert failed");
                Err(e)
            }
        }
    }
}

fn parse_uuid(s: &str) -> uuid::Uuid {
    uuid::Uuid::parse_str(s).unwrap_or_default()
}

fn parse_jsonb(bytes: &[u8]) -> serde_json::Value {
    if bytes.is_empty() {
        return serde_json::Value::Object(serde_json::Map::new());
    }
    serde_json::from_slice(bytes).unwrap_or(serde_json::Value::Object(serde_json::Map::new()))
}

fn parse_optional_jsonb(bytes: &[u8]) -> Option<serde_json::Value> {
    if bytes.is_empty() {
        return None;
    }
    serde_json::from_slice(bytes).ok()
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
    fn parse_uuid_valid() {
        let uuid = parse_uuid("00000000-0000-0000-0000-000000000042");
        assert_eq!(uuid.to_string(), "00000000-0000-0000-0000-000000000042");
    }

    #[test]
    fn parse_uuid_invalid_returns_nil() {
        let uuid = parse_uuid("not-a-uuid");
        assert_eq!(uuid, uuid::Uuid::nil());
    }

    #[test]
    fn parse_jsonb_valid() {
        let val = parse_jsonb(b"{\"email\":\"test@example.com\"}");
        assert_eq!(val["email"], "test@example.com");
    }

    #[test]
    fn parse_jsonb_empty_returns_empty_object() {
        let val = parse_jsonb(b"");
        assert!(val.is_object());
        assert_eq!(val.as_object().unwrap().len(), 0);
    }

    #[test]
    fn parse_optional_jsonb_empty_returns_none() {
        assert!(parse_optional_jsonb(b"").is_none());
    }

    #[test]
    fn parse_optional_jsonb_valid() {
        let val = parse_optional_jsonb(b"{\"key\":\"val\"}");
        assert!(val.is_some());
        assert_eq!(val.unwrap()["key"], "val");
    }

    #[test]
    fn epoch_secs_conversion() {
        let dt = epoch_secs_to_datetime(1700000000);
        assert_eq!(dt.timestamp(), 1700000000);
    }
}
