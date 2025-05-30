use serde::{Deserialize, Serialize};

use crate::properties::property_models::PropertyFilter;

// TRICKY: This cache data is coming from django-redis. If it ever goes out of sync, we'll bork.
// TODO: Add integration tests across repos to ensure this doesn't happen.
pub const TEAM_FLAGS_CACHE_PREFIX: &str = "posthog:1:team_feature_flags_";

#[derive(Debug, Clone, Deserialize, Serialize, Default)]
pub struct FlagPropertyGroup {
    #[serde(default)]
    pub properties: Option<Vec<PropertyFilter>>,
    #[serde(default)]
    pub rollout_percentage: Option<f64>,
    #[serde(default)]
    pub variant: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct MultivariateFlagVariant {
    pub key: String,
    pub name: Option<String>,
    pub rollout_percentage: f64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct MultivariateFlagOptions {
    pub variants: Vec<MultivariateFlagVariant>,
}

#[derive(Debug, Clone, Deserialize, Serialize, Default)]
pub struct FlagFilters {
    #[serde(default)]
    pub groups: Vec<FlagPropertyGroup>,
    #[serde(default)]
    pub multivariate: Option<MultivariateFlagOptions>,
    #[serde(default)]
    pub aggregation_group_type_index: Option<i32>,
    #[serde(default)]
    pub payloads: Option<serde_json::Value>,
    #[serde(default)]
    pub super_groups: Option<Vec<FlagPropertyGroup>>,
    #[serde(default)]
    pub holdout_groups: Option<Vec<FlagPropertyGroup>>,
}

// TODO: see if you can combine these two structs, like we do with cohort models
// this will require not deserializing on read and instead doing it lazily, on-demand
// (which, tbh, is probably a better idea)
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct FeatureFlag {
    pub id: i32,
    pub team_id: i32,
    pub name: Option<String>,
    pub key: String,
    pub filters: FlagFilters,
    #[serde(default)]
    pub deleted: bool,
    #[serde(default)]
    pub active: bool,
    #[serde(default)]
    pub ensure_experience_continuity: bool,
    #[serde(default)]
    pub version: Option<i32>,
    #[serde(default)]
    pub creation_context: Option<String>,
}

#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct FeatureFlagRow {
    pub id: i32,
    pub team_id: i32,
    pub name: Option<String>,
    pub key: String,
    pub filters: serde_json::Value,
    pub deleted: bool,
    pub active: bool,
    pub ensure_experience_continuity: bool,
    pub version: Option<i32>,
    pub creation_context: Option<String>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct FeatureFlagList {
    pub flags: Vec<FeatureFlag>,
}

impl FeatureFlagList {
    pub fn new(flags: Vec<FeatureFlag>) -> Self {
        Self { flags }
    }
}
