#[derive(Debug, Clone)]
pub struct HashKeyOverride {
    pub feature_flag_key: String,
    pub hash_key: String,
}

/// Context for hash key override decisions. Contains the resolved person ID,
/// existing overrides, and which flags already have overrides.
#[derive(Debug, Clone)]
pub struct HashKeyOverrideContext {
    pub person_id: i64,
    pub distinct_id: String,
    pub overrides: Vec<HashKeyOverride>,
    pub existing_feature_flag_keys: Vec<String>,
}

/// Position of the last hash key override row a delete batch reached, ordered by
/// the (team_id, person_id, feature_flag_key) unique index.
#[derive(Debug, Clone)]
pub struct HashKeyOverrideCursor {
    pub team_id: i64,
    pub person_id: i64,
    pub feature_flag_key: String,
}

/// Outcome of one hash key override delete batch.
#[derive(Debug, Clone)]
pub struct HashKeyOverrideDeleteBatch {
    pub deleted_count: i64,
    /// Where the next batch must resume. `None` once nothing is left to delete.
    pub cursor: Option<HashKeyOverrideCursor>,
}
