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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PersonTombstoneQueueEntry {
    pub team_id: i64,
    pub person_uuid: Uuid,
    pub person_version: i64,
    pub tombstoned_at_ms: i64,
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

/// The stored version of a person row, tombstones included.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PersonVersionHead {
    pub uuid: Uuid,
    pub version: i64,
    pub is_deleted: bool,
}

/// The stored version of a distinct id row, tombstones included.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DistinctIdVersionHead {
    pub distinct_id: String,
    pub version: i64,
    pub is_deleted: bool,
    /// None when the row points at a person that has no row.
    pub person_uuid: Option<Uuid>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VersionFloorOutcome {
    TombstoneInserted,
    TombstoneRaised,
    TombstoneAtFloor,
    Live,
}

impl VersionFloorOutcome {
    /// Classify a row that existed before the call, from its state then.
    pub fn for_existing(is_deleted: bool, version: i64, min_version: i64) -> Self {
        match (is_deleted, version < min_version) {
            (false, _) => Self::Live,
            (true, true) => Self::TombstoneRaised,
            (true, false) => Self::TombstoneAtFloor,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PersonVersionFloorResult {
    pub uuid: Uuid,
    pub outcome: VersionFloorOutcome,
    pub version: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DistinctIdVersionFloor {
    pub distinct_id: String,
    pub min_version: i64,
    pub person_uuid: Uuid,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DistinctIdVersionFloorResult {
    pub distinct_id: String,
    pub outcome: VersionFloorOutcome,
    pub version: i64,
    /// None when the row points at a person that has no row.
    pub person_uuid: Option<Uuid>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DistinctIdTombstoneOutcome {
    Tombstoned,
    AlreadyTombstoned,
    Absent,
    /// A live row whose person row exists. Left unchanged.
    NotOrphaned,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DistinctIdTombstoneResult {
    pub distinct_id: String,
    pub outcome: DistinctIdTombstoneOutcome,
    /// 0 when the outcome is Absent.
    pub version: i64,
    /// None when the row points at a person that has no row, or the outcome is Absent.
    pub person_uuid: Option<Uuid>,
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
