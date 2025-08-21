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
    /// The group type index is used to determine which group type to use for the flag.
    ///
    /// Typical group type mappings are:
    /// - 0 → "project"
    /// - 1 → "organization"
    /// - 2 → "instance"
    /// - 3 → "customer"
    /// - 4 → "team"
    #[serde(default)]
    pub aggregation_group_type_index: Option<i32>,
    #[serde(default)]
    pub payloads: Option<serde_json::Value>,
    /// Super groups are a special group of feature flag conditions that act as a gate that must be
    /// satisfied before any other conditions are evaluated. Currently, we only ever evaluate the first
    /// super group. This is used for early access features which is a key and a boolean like so:
    /// {
    ///   "key": "$feature_enrollment/feature-flags-flag-dependency",
    ///   "type": "person",
    ///   "value": [
    ///     "true"
    ///   ],
    ///   "operator": "exact"
    /// }
    /// If they match, the flag is enabled and no other conditions are evaluated. If they don't match,
    /// fallback to regular conditions.
    #[serde(default)]
    pub super_groups: Option<Vec<FlagPropertyGroup>>,
    /// The holdout group (though the type can hold multiple, we only evaluate the first one)
    /// is a condition that defines a set of users intentionally excluded from a test or
    /// experiment to serve as a baseline or control group. The group is defined as a percentage
    /// which is held back by hashing the distinct identifier of the user. Here's an example:
    /// "holdout_groups": [
    /// {
    ///     "variant": "holdout-1",
    ///     "properties": [],
    ///     "rollout_percentage": 10
    ///   }
    /// ]
    #[serde(default)]
    pub holdout_groups: Option<Vec<FlagPropertyGroup>>,
}

pub type FeatureFlagId = i32;

// TODO: see if you can combine these two structs, like we do with cohort models
// this will require not deserializing on read and instead doing it lazily, on-demand
// (which, tbh, is probably a better idea)
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct FeatureFlag {
    pub id: FeatureFlagId,
    pub team_id: i32,
    pub name: Option<String>,
    pub key: String,
    pub filters: FlagFilters,
    #[serde(default)]
    pub deleted: bool,
    #[serde(default)]
    pub active: bool,
    #[serde(default)]
    pub ensure_experience_continuity: Option<bool>,
    #[serde(default)]
    pub version: Option<i32>,
    #[serde(default)]
    pub evaluation_runtime: Option<String>,
    #[serde(default)]
    pub evaluation_tags: Option<Vec<String>>,
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
    pub ensure_experience_continuity: Option<bool>,
    pub version: Option<i32>,
    #[serde(default)]
    pub evaluation_runtime: Option<String>,
    #[serde(default)]
    pub evaluation_tags: Option<Vec<String>>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct FeatureFlagList {
    pub flags: Vec<FeatureFlag>,
}
