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
