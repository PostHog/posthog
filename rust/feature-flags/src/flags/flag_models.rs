use std::sync::Arc;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::FromRow;

use crate::{
    clients::database::Client, flags::flag_match_reason::FeatureFlagMatchReason,
    properties::property_models::PropertyFilter,
};

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

pub type TeamId = i32;
pub type GroupTypeIndex = i32;
pub type PostgresReader = Arc<dyn Client + Send + Sync>;
pub type PostgresWriter = Arc<dyn Client + Send + Sync>;

#[derive(Debug)]
pub struct SuperConditionEvaluation {
    pub should_evaluate: bool,
    pub is_match: bool,
    pub reason: FeatureFlagMatchReason,
}

#[derive(Debug, PartialEq, Eq)]
pub struct FeatureFlagMatch {
    pub matches: bool,
    pub variant: Option<String>,
    pub reason: FeatureFlagMatchReason,
    pub condition_index: Option<usize>,
    pub payload: Option<Value>,
}

#[derive(Debug, FromRow)]
pub struct GroupTypeMapping {
    pub group_type: String,
    pub group_type_index: GroupTypeIndex,
}
