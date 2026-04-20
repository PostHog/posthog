use async_trait::async_trait;
use metrics::counter;
use personhog_proto::personhog::types::v1::Person;
use tracing::warn;

use crate::pg::PgStore;
use crate::properties;

/// Classification of write errors, used across the pg, store, and writer layers.
#[derive(Debug, Clone, Copy)]
pub enum WriteErrorKind {
    /// Retrying the same operation may succeed.
    Transient,
    /// Properties exceed the DB size constraint. Trimming may help.
    PropertiesSizeViolation,
    /// Unrecoverable data error. Skip this record.
    Data,
}

/// Error from a batch write operation.
#[derive(Debug)]
pub struct WriteError {
    pub message: String,
    pub kind: WriteErrorKind,
}

impl std::fmt::Display for WriteError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

/// Outcome of writing a single person.
#[derive(Debug)]
pub enum RowResult {
    Written,
    Trimmed(IngestionWarning),
    Skipped(IngestionWarning),
}

/// Information needed to emit an ingestion warning.
#[derive(Debug)]
pub struct IngestionWarning {
    pub team_id: i64,
    pub person_id: i64,
    pub message: String,
}

/// Trait for the person write store. Mockable for testing the writer task.
#[async_trait]
pub trait PersonStore: Send + Sync {
    async fn upsert_batch(&self, persons: &[Person]) -> Result<(), WriteError>;
    async fn upsert_row(&self, person: &Person) -> RowResult;
}

/// Production person write store. Wraps the PG execution layer and adds
/// business logic: size violation handling with property trimming.
pub struct PersonWriteStore {
    db: PgStore,
}

impl PersonWriteStore {
    pub fn new(db: PgStore) -> Self {
        Self { db }
    }
}

#[async_trait]
impl PersonStore for PersonWriteStore {
    async fn upsert_batch(&self, persons: &[Person]) -> Result<(), WriteError> {
        self.db.execute_batch(persons).await
    }

    async fn upsert_row(&self, person: &Person) -> RowResult {
        match self.db.execute_row(person, None).await {
            Ok(()) => return RowResult::Written,
            Err(e) if matches!(e.kind, WriteErrorKind::PropertiesSizeViolation) => {
                // Fall through to trim logic
            }
            Err(e) => {
                counter!("personhog_writer_rows_skipped_total").increment(1);
                warn!(
                    team_id = person.team_id,
                    person_id = person.id,
                    error = %e.message,
                    "per-row upsert failed, skipping"
                );
                return RowResult::Skipped(IngestionWarning {
                    team_id: person.team_id,
                    person_id: person.id,
                    message: format!("Person upsert failed: {}", e.message),
                });
            }
        }

        // Size violation: trim and retry
        let props: serde_json::Value = if person.properties.is_empty() {
            serde_json::Value::Object(serde_json::Map::new())
        } else {
            serde_json::from_slice(&person.properties)
                .unwrap_or(serde_json::Value::Object(serde_json::Map::new()))
        };
        let Some(trimmed) =
            properties::trim_properties_to_fit_size(&props, person.team_id, person.id)
        else {
            counter!("personhog_writer_rows_skipped_total").increment(1);
            return RowResult::Skipped(IngestionWarning {
                team_id: person.team_id,
                person_id: person.id,
                message: "Person properties exceeds size limit and was rejected".to_string(),
            });
        };

        let trimmed_str = serde_json::to_string(&trimmed).unwrap_or_default();
        match self.db.execute_row(person, Some(&trimmed_str)).await {
            Ok(()) => {
                counter!("personhog_writer_properties_trimmed_writes_total").increment(1);
                RowResult::Trimmed(IngestionWarning {
                    team_id: person.team_id,
                    person_id: person.id,
                    message: "Person properties exceeded size limit and were trimmed".to_string(),
                })
            }
            Err(_) => {
                counter!("personhog_writer_rows_skipped_total").increment(1);
                RowResult::Skipped(IngestionWarning {
                    team_id: person.team_id,
                    person_id: person.id,
                    message: "Person properties exceeds size limit and was rejected".to_string(),
                })
            }
        }
    }
}
