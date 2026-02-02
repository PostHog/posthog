#[derive(Debug, Clone)]
pub struct HashKeyOverride {
    pub feature_flag_key: String,
    pub hash_key: String,
}

/// Input for upserting a hash key override.
/// The hash_key is specified separately at the batch level since all overrides
/// share the same hash key (for experience continuity).
#[derive(Debug, Clone)]
pub struct HashKeyOverrideInput {
    pub person_id: i64,
    pub feature_flag_key: String,
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
