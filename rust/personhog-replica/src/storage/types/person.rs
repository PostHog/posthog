use uuid::Uuid;

#[derive(Debug, Clone)]
pub struct Person {
    pub id: i64,
    pub uuid: Uuid,
    pub team_id: i64,
    pub properties: serde_json::Value,
    pub properties_last_updated_at: Option<serde_json::Value>,
    pub properties_last_operation: Option<serde_json::Value>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub version: Option<i64>,
    pub is_identified: bool,
    pub is_user_id: Option<bool>,
}

#[derive(Debug, Clone)]
pub struct DistinctIdMapping {
    pub person_id: i64,
    pub distinct_id: String,
}

#[derive(Debug, Clone)]
pub struct DistinctIdWithVersion {
    pub distinct_id: String,
    pub version: Option<i64>,
}
