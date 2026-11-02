use uuid::Uuid;

use super::DistinctIdRow;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RaiseOutcome {
    Raised,
    AtOrAbove,
    NotLive,
    Missing,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RaiseResult {
    pub uuid: Uuid,
    pub outcome: RaiseOutcome,
    /// The version the row holds after the call; 0 when missing.
    pub version: i64,
}

/// A person to insert from its ClickHouse copy.
#[derive(Debug, Clone, PartialEq)]
pub struct RestoredPerson {
    pub uuid: Uuid,
    pub properties: serde_json::Value,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub is_identified: bool,
    pub version: i64,
    /// Distinct ids and versions to insert on the person in the same transaction.
    pub distinct_ids: Vec<(String, i64)>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RestoreOutcome {
    Inserted,
    ExistsLive,
    ExistsTombstoned,
    NoDistinctId,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RestoreResult {
    pub uuid: Uuid,
    pub outcome: RestoreOutcome,
    pub person_id: i64,
    pub version: i64,
    pub restored_distinct_ids: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DistinctIdWriteAction {
    Insert,
    Raise,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DistinctIdWrite {
    pub distinct_id: String,
    pub action: DistinctIdWriteAction,
    /// The insert target, or the row's expected owner for raise.
    pub person_uuid: Uuid,
    pub min_version: i64,
    pub expected_version: Option<i64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DistinctIdWriteOutcome {
    Applied,
    Unchanged,
    PreconditionFailed,
    PersonNotLive,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DistinctIdWriteResult {
    pub distinct_id: String,
    pub outcome: DistinctIdWriteOutcome,
    /// The row after the call, when one exists.
    pub row: Option<DistinctIdRow>,
}
