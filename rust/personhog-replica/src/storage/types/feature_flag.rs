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
