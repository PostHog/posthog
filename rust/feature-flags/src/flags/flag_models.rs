#![allow(clippy::needless_update)]

use serde::de::{self, Deserializer};
use serde::ser::{SerializeMap, Serializer};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

use crate::cohorts::cohort_models::Cohort;
use crate::properties::property_models::PropertyFilter;
use crate::utils::mock::{Mock, MockFrom};

/// Deserializes a JSON object with string keys into `HashMap<i32, HashSet<i32>>`.
/// JSON only supports string keys, so Python serializes `{1: [2, 3]}` as `{"1": [2, 3]}`.
fn deserialize_string_keyed_i32_map<'de, D>(
    deserializer: D,
) -> Result<HashMap<i32, HashSet<i32>>, D::Error>
where
    D: Deserializer<'de>,
{
    let raw: HashMap<String, Vec<i32>> = HashMap::deserialize(deserializer)?;
    raw.into_iter()
        .map(|(k, v)| {
            let id = k.parse::<i32>().map_err(de::Error::custom)?;
            Ok((id, v.into_iter().collect()))
        })
        .collect()
}

/// Serializes `HashMap<i32, HashSet<i32>>` back to JSON with string keys.
fn serialize_string_keyed_i32_map<S>(
    map: &HashMap<i32, HashSet<i32>>,
    serializer: S,
) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    let mut ser_map = serializer.serialize_map(Some(map.len()))?;
    let mut keys: Vec<&i32> = map.keys().collect();
    keys.sort_unstable();
    for k in keys {
        let v = &map[k];
        let sorted: Vec<i32> = {
            let mut s: Vec<i32> = v.iter().copied().collect();
            s.sort_unstable();
            s
        };
        ser_map.serialize_entry(&k.to_string(), &sorted)?;
    }
    ser_map.end()
}

/// Pre-computed dependency metadata, built by Django at cache-write time.
/// Shipped as a top-level field alongside the flags array in the hypercache.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, Serialize)]
pub struct EvaluationMetadata {
    /// Flag IDs grouped by evaluation stage. Stage 0 (no deps) first.
    pub dependency_stages: Vec<Vec<i32>>,
    /// Flag IDs with missing, cyclic, or transitively broken dependencies.
    pub flags_with_missing_deps: Vec<i32>,
    /// Flag ID → transitive dependency flag IDs.
    #[serde(
        deserialize_with = "deserialize_string_keyed_i32_map",
        serialize_with = "serialize_string_keyed_i32_map"
    )]
    pub transitive_deps: HashMap<i32, HashSet<i32>>,
}

/// Wrapper struct for deserializing hypercache format: {"flags": [...], "cohorts": [...]}
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HypercacheFlagsWrapper {
    pub flags: Vec<FeatureFlag>,
    #[serde(default)]
    pub evaluation_metadata: Option<EvaluationMetadata>,
    /// Cohort definitions referenced by flags (including transitive deps).
    /// Precomputed by Django at cache-write time so the Rust service can skip
    /// the separate CohortCacheManager PG query.
    #[serde(default)]
    pub cohorts: Option<Vec<Cohort>>,
}

/// New holdout format: `{"id": 42, "exclusion_percentage": 10}`.
/// Replaces the legacy `holdout_groups` array which reused `FlagPropertyGroup` with
/// confusing semantics (rollout_percentage meant exclusion, variant was just "holdout-{id}").
/// See holdout-migration-plan.md for the full migration plan.
#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct Holdout {
    pub id: i64,
    pub exclusion_percentage: f64,
}

#[derive(Debug, Clone, Deserialize, Serialize, Default)]
pub struct FlagPropertyGroup {
    #[serde(default)]
    pub properties: Option<Vec<PropertyFilter>>,
    #[serde(default)]
    pub rollout_percentage: Option<f64>,
    #[serde(default)]
    pub variant: Option<String>,
    /// Per-condition-set aggregation group type index. When present, this condition
    /// set uses the specified group type for hashing and property evaluation. When
    /// absent/null, the condition set uses person-level aggregation (distinct_id).
    #[serde(default)]
    pub aggregation_group_type_index: Option<i32>,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
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
    /// Holdout format: `{"id": 42, "exclusion_percentage": 10}`.
    /// Defines a set of users intentionally excluded from a test or experiment.
    #[serde(default)]
    pub holdout: Option<Holdout>,
}

pub type FeatureFlagId = i32;

/// Defines which identifier is used for bucketing users into rollout and variants
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BucketingIdentifier {
    DistinctId,
    DeviceId,
}

// TODO: see if you can combine these two structs, like we do with cohort models
// this will require not deserializing on read and instead doing it lazily, on-demand
// (which, tbh, is probably a better idea)
#[derive(Debug, Clone, Default, Deserialize, Serialize)]
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
    #[serde(default)]
    pub bucketing_identifier: Option<String>,
}

impl FeatureFlag {
    /// Returns the bucketing identifier for this flag.
    /// Defaults to DistinctId if not specified or if an invalid value is provided.
    pub fn get_bucketing_identifier(&self) -> BucketingIdentifier {
        match self.bucketing_identifier.as_deref() {
            Some("device_id") => BucketingIdentifier::DeviceId,
            _ => BucketingIdentifier::DistinctId,
        }
    }
}

#[derive(Debug, Default, Serialize, sqlx::FromRow)]
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
    #[serde(default)]
    pub bucketing_identifier: Option<String>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct FeatureFlagList {
    pub flags: Vec<FeatureFlag>,
    /// Runtime-only set of flag IDs that should be skipped during evaluation.
    /// Includes inactive, deleted, survey-excluded, runtime-mismatched, and tag-filtered flags.
    /// Not serialized — this is a request-scoped concern, not a cache concern.
    #[serde(skip)]
    pub filtered_out_flag_ids: HashSet<i32>,
    /// Pre-computed dependency metadata from Django's hypercache.
    /// Present when the cache was written by new Django code; absent for PG fallback
    /// or old cache entries.
    #[serde(skip)]
    pub evaluation_metadata: Option<EvaluationMetadata>,
    /// Cohort definitions referenced by flags (including transitive deps),
    /// precomputed by Django at cache-write time.
    /// When present, the matcher uses these instead of querying CohortCacheManager.
    #[serde(skip)]
    pub cohorts: Option<Vec<Cohort>>,
}

// Mock trait implementations

impl Mock for FeatureFlag {
    fn mock() -> Self {
        FeatureFlag {
            id: 1,
            team_id: 1,
            name: Some("Test Flag".to_string()),
            key: "test_flag".to_string(),
            filters: Mock::mock(),
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            ..Default::default()
        }
    }
}

impl Mock for FeatureFlagRow {
    fn mock() -> Self {
        FeatureFlagRow {
            team_id: 1,
            name: Some("Test Flag".to_string()),
            key: "test_flag".to_string(),
            filters: serde_json::json!({
                "groups": [{
                    "properties": [],
                    "rollout_percentage": 100
                }]
            }),
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            ..Default::default()
        }
    }
}

impl Mock for FlagFilters {
    fn mock() -> Self {
        FlagFilters {
            groups: vec![Mock::mock()],
            ..Default::default()
        }
    }
}

impl Mock for FlagPropertyGroup {
    fn mock() -> Self {
        FlagPropertyGroup {
            properties: Some(vec![]),
            rollout_percentage: Some(100.0),
            ..Default::default()
        }
    }
}

impl Mock for Holdout {
    fn mock() -> Self {
        Holdout {
            id: 1,
            exclusion_percentage: 10.0,
            ..Default::default()
        }
    }
}

impl Mock for MultivariateFlagVariant {
    fn mock() -> Self {
        MultivariateFlagVariant {
            key: "control".to_string(),
            name: Some("Control".to_string()),
            rollout_percentage: 100.0,
            ..Default::default()
        }
    }
}

impl MockFrom<FeatureFlag> for FeatureFlagRow {
    fn mock_from(flag: FeatureFlag) -> Self {
        let filters = serde_json::to_value(&flag.filters)
            .expect("Mock: failed to serialize FeatureFlag.filters to JSON");
        FeatureFlagRow {
            id: flag.id,
            team_id: flag.team_id,
            name: flag.name,
            key: flag.key,
            filters,
            deleted: flag.deleted,
            active: flag.active,
            ensure_experience_continuity: flag.ensure_experience_continuity,
            version: flag.version,
            evaluation_runtime: flag.evaluation_runtime,
            evaluation_tags: flag.evaluation_tags,
            bucketing_identifier: flag.bucketing_identifier,
            ..Default::default()
        }
    }
}

/// Single property → `FlagFilters` with one group at 100% rollout.
impl MockFrom<PropertyFilter> for FlagFilters {
    fn mock_from(property: PropertyFilter) -> Self {
        MockFrom::mock_from(vec![property])
    }
}

/// Multiple properties → `FlagFilters` with one group at 100% rollout.
impl MockFrom<Vec<PropertyFilter>> for FlagFilters {
    fn mock_from(properties: Vec<PropertyFilter>) -> Self {
        FlagFilters {
            groups: vec![FlagPropertyGroup {
                properties: Some(properties),
                rollout_percentage: Some(100.0),
                ..Default::default()
            }],
            ..Default::default()
        }
    }
}
