use uuid::Uuid;

#[derive(Debug, Clone)]
pub struct Person {
    pub id: i64,
    pub uuid: Uuid,
    pub team_id: i64,
    pub properties: Option<String>,
    pub properties_last_updated_at: Option<String>,
    pub properties_last_operation: Option<String>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub version: Option<i64>,
    pub is_identified: bool,
    pub is_user_id: Option<bool>,
    pub last_seen_at: Option<chrono::DateTime<chrono::Utc>>,
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
