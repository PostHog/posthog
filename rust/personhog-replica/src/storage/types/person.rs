use uuid::Uuid;

pub use personhog_common::persons::Person;

/// Which of the person jsonb property columns a read must load from Postgres.
///
/// Each column is detoasted separately, and a row may hold hundreds of kilobytes, so a read
/// that wants `properties` must not also pull the two audit columns off disk.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PersonPropertyColumns {
    pub properties: bool,
    pub properties_last_updated_at: bool,
    pub properties_last_operation: bool,
}

impl PersonPropertyColumns {
    pub const ALL: Self = Self {
        properties: true,
        properties_last_updated_at: true,
        properties_last_operation: true,
    };

    pub const NONE: Self = Self {
        properties: false,
        properties_last_updated_at: false,
        properties_last_operation: false,
    };
}

#[derive(Debug, Clone)]
pub struct DistinctIdMapping {
    pub person_id: i64,
    pub distinct_id: String,
    pub version: Option<i64>,
}

#[derive(Debug, Clone)]
pub struct DistinctIdWithVersion {
    pub distinct_id: String,
    pub version: Option<i64>,
    pub id: i64,
}

/// Outcome of one bounded DeleteTombstonedPersons call. Every requested uuid lands in at most
/// one bucket; a uuid with no Postgres row, or whose person is live again, lands in none.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct TombstonedDeleteOutcome {
    /// Persons hard-deleted together with their dependent rows.
    pub deleted: i64,
    /// Persons found with is_deleted = false, so revived after the caller queued them. Untouched.
    pub skipped_live: i64,
    /// Persons still tombstoned but referenced by a live distinct id. Untouched. Ingestion never
    /// produces this state, so the caller should surface it rather than retry blindly.
    pub blocked_uuids: Vec<Uuid>,
    /// Persons not finished within the row budget; the caller sends them again.
    pub pending_uuids: Vec<Uuid>,
    /// Dependent rows deleted by this call.
    pub rows_deleted: i64,
}

#[derive(Debug, Clone)]
pub struct SplitResult {
    pub distinct_id: String,
    pub new_person_uuid: Uuid,
    pub new_person_version: i64,
    pub pdi_version: i64,
    /// For pre-existing persons (idempotent re-split) this is the original
    /// created_at, preserved by the upsert — not the time of this request.
    pub new_person_created_at: chrono::DateTime<chrono::Utc>,
}
