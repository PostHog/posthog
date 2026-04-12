use uuid::Uuid;

/// Data needed for a person property upsert.
pub struct PersonUpdateData {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub properties: serde_json::Value,
    pub version: i64,
}

/// Data needed for a person deletion.
pub struct PersonDeletionData {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub version: i64,
}

/// Data needed for a distinct-ID assignment (add to new owner, remove from old).
pub struct DistinctIdAssignmentData {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub distinct_id: Box<str>,
    pub version: i64,
}

/// Data needed for a distinct-ID deletion (remove from owner).
pub struct DistinctIdDeletionData {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub distinct_id: Box<str>,
    pub version: i64,
}
