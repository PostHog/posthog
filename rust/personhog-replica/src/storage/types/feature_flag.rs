#[derive(Debug, Clone)]
pub struct HashKeyOverride {
    pub feature_flag_key: String,
    pub hash_key: String,
}

#[derive(Debug, Clone)]
pub struct PersonIdWithOverrides {
    pub person_id: i64,
    pub distinct_id: String,
    pub overrides: Vec<HashKeyOverride>,
}

#[derive(Debug, Clone)]
pub struct PersonIdWithOverrideKeys {
    pub person_id: i64,
    pub existing_feature_flag_keys: Vec<String>,
}
