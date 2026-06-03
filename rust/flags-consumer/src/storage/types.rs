use uuid::Uuid;

pub struct PersonUpdateData {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub properties: serde_json::Value,
    pub version: i64,
}

pub struct PersonDeletionData {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub version: i64,
}

pub struct DistinctIdAssignmentData {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub distinct_id: Box<str>,
    pub version: i64,
}

pub struct DistinctIdDeletionData {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub distinct_id: Box<str>,
    pub version: i64,
}
