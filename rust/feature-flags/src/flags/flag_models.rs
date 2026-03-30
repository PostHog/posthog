use serde::de::{self, Deserializer};
use serde::ser::{SerializeMap, Serializer};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

use crate::cohorts::cohort_models::Cohort;
use crate::properties::property_models::PropertyFilter;

// NOTE: The `evaluation_tags` field was renamed to `evaluation_contexts` in the Python
// serializer (PR #52186). The Rust field keeps the old name for internal compatibility,
// but uses `#[serde(rename = "evaluation_contexts")]` to match the JSON key.

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

/// Deserializes a field into `Option<Option<T>>` to distinguish "absent" from "null":
/// - Field absent → `None` (outer)
/// - Field present, value `null` → `Some(None)`
/// - Field present, value `v` → `Some(Some(v))`
fn deserialize_double_option<'de, T, D>(deserializer: D) -> Result<Option<Option<T>>, D::Error>
where
    T: Deserialize<'de>,
    D: Deserializer<'de>,
{
    // When serde calls this, the field was present in JSON. Absent fields
    // never reach the deserializer — #[serde(default)] yields None instead.
    Ok(Some(Option::deserialize(deserializer)?))
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

impl EvaluationMetadata {
    /// Builds metadata that places all flags in a single evaluation stage
    /// with no dependency ordering. Used by the PG fallback path.
    pub fn single_stage(flags: &[FeatureFlag]) -> Self {
        Self {
            dependency_stages: vec![flags.iter().map(|f| f.id).collect()],
            transitive_deps: flags.iter().map(|f| (f.id, HashSet::new())).collect(),
            ..Default::default()
        }
    }
}

/// Wrapper struct for deserializing hypercache format:
/// `{"flags": [...], "evaluation_metadata": {...}, "cohorts": [...]}`
///
/// `evaluation_metadata` is always present in cache entries (written by Django).
/// The PG fallback path constructs this struct with `EvaluationMetadata::single_stage()`,
/// which places all flags in one evaluation stage with empty transitive deps.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HypercacheFlagsWrapper {
    pub flags: Vec<FeatureFlag>,
    pub evaluation_metadata: EvaluationMetadata,
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
#[derive(Debug, Clone, Deserialize, Serialize)]
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
    /// Per-condition-set aggregation group type index. The outer Option distinguishes
    /// "field absent" (legacy flags, should fall back to flag-level) from "field
    /// present but null" (explicit person aggregation). When the inner Option holds
    /// a value, the condition uses that group type for hashing and property evaluation.
    #[serde(default, deserialize_with = "deserialize_double_option")]
    pub aggregation_group_type_index: Option<Option<i32>>,
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
    /// New format for early access feature enrollment. When `true`, the flag is evaluated
    /// against the person property `$feature_enrollment/{flag_key}`. Takes precedence over
    /// `super_groups` when both are present.
    #[serde(default)]
    pub feature_enrollment: Option<bool>,
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
    /// Evaluation context tags for this flag. JSON key is `evaluation_contexts`,
    /// but Rust field remains `evaluation_tags` for internal compatibility.
    #[serde(default, rename = "evaluation_contexts")]
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

/// Row struct for PostgreSQL queries via sqlx. The `evaluation_tags` column is
/// always named `evaluation_tags` in the SQL query, so no alias is needed.
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
    #[serde(skip)]
    pub evaluation_metadata: EvaluationMetadata,
    /// Cohort definitions referenced by flags (including transitive deps),
    /// precomputed by Django at cache-write time.
    /// When present, the matcher uses these instead of querying CohortCacheManager.
    #[serde(skip)]
    pub cohorts: Option<Vec<Cohort>>,
}
