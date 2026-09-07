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
}

/// Outcome of one `delete_persons_batch_for_team` call.
#[derive(Debug, Clone, Copy, Default)]
pub struct DeletedPersonBatch {
    pub deleted_count: i64,
    /// Largest person id the call selected, for the next call's keyset cursor.
    /// 0 when the call selected nothing.
    pub last_id: i64,
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
