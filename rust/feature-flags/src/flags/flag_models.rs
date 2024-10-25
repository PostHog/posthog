use serde::{Deserialize, Serialize};

use crate::properties::property_models::PropertyFilter;

// TRICKY: This cache data is coming from django-redis. If it ever goes out of sync, we'll bork.
// TODO: Add integration tests across repos to ensure this doesn't happen.
pub const TEAM_FLAGS_CACHE_PREFIX: &str = "posthog:1:team_feature_flags_";

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct FlagGroupType {
    pub properties: Option<Vec<PropertyFilter>>,
    pub rollout_percentage: Option<f64>,
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

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct FlagFilters {
    pub groups: Vec<FlagGroupType>,
    pub multivariate: Option<MultivariateFlagOptions>,
    pub aggregation_group_type_index: Option<i32>,
    pub payloads: Option<serde_json::Value>,
    pub super_groups: Option<Vec<FlagGroupType>>,
}

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
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct FeatureFlagList {
    pub flags: Vec<FeatureFlag>,
}
