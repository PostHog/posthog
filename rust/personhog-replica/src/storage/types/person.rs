use uuid::Uuid;

pub use personhog_common::persons::Person;

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

/// How DeletePersons removes rows. A caller that publishes ClickHouse tombstones
/// asks for `Tombstone` and reads the versions back; everything else hard-deletes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeletePersonsMode {
    Hard,
    Tombstone,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TombstonedDistinctId {
    pub distinct_id: String,
    pub version: i64,
}

/// The versions a tombstone wrote for one person, for the caller's ClickHouse
/// tombstones.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TombstonedPerson {
    pub uuid: Uuid,
    pub version: i64,
    pub distinct_ids: Vec<TombstonedDistinctId>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct DeletePersonsOutcome {
    pub deleted: i64,
    /// Set only when the rows were tombstoned.
    pub tombstones: Option<Vec<TombstonedPerson>>,
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
