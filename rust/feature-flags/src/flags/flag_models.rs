use serde::de::{self, Deserializer};
use serde::ser::{SerializeMap, Serializer};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use crate::cohorts::cohort_models::Cohort;
use crate::flags::feature_flag_list::PreparedFlags;
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
/// `{"flags": [...], "evaluation_metadata": {...}, "cohorts": [...] | null}`.
///
/// `evaluation_metadata` is always present in cache entries (written by Django).
/// The PG fallback path constructs this struct with `EvaluationMetadata::single_stage()`,
/// which places all flags in one evaluation stage with empty transitive deps.
///
/// HYPERCACHE CONTRACT: These fields must match the top-level keys returned by
/// `_get_feature_flags_for_service()` in posthog/models/feature_flag/flags_cache.py.
/// Field changes must follow the expand-and-contract pattern — see contract tests in
/// posthog/models/feature_flag/test/test_flags_cache.py.
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
    /// Per-condition-set aggregation group type index. The outer Option distinguishes
    /// "field absent" (legacy flags, should fall back to flag-level) from "field
    /// present but null" (explicit person aggregation). When the inner Option holds
    /// a value, the condition uses that group type for hashing and property evaluation.
    #[serde(default, deserialize_with = "deserialize_double_option")]
    pub aggregation_group_type_index: Option<Option<i32>>,
    /// Captures unknown JSONB keys so the cache round-trip is identity. Without
    /// this, frontend leaks (`description`, `sort_key`), runtime annotations
    /// (`cohort_name`, `group_key_names`), and field typos would be silently
    /// dropped on round-trip and the Python `verify_flags_cache` verifier would
    /// report spurious `FIELD_MISMATCH` against the Django JSONB passthrough.
    /// See plans/verify-flags-cache-loose-comparison.md.
    #[serde(flatten)]
    pub extra: serde_json::Map<String, serde_json::Value>,
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
    /// Early access feature enrollment. When `true`, the flag is evaluated against the
    /// person property `$feature_enrollment/{flag_key}`.
    #[serde(default)]
    pub feature_enrollment: Option<bool>,
    /// Holdout format: `{"id": 42, "exclusion_percentage": 10}`.
    /// Defines a set of users intentionally excluded from a test or experiment.
    #[serde(default)]
    pub holdout: Option<Holdout>,
    /// Captures unknown JSONB keys so the cache round-trip is identity. Without
    /// this, legacy filter keys (`holdout_groups`), top-level stray keys, and
    /// field typos (`multivariant` for `multivariate`, `payload` for `payloads`)
    /// would be silently dropped on round-trip and the Python
    /// `verify_flags_cache` verifier would report spurious `FIELD_MISMATCH`
    /// against the Django JSONB passthrough.
    /// See plans/verify-flags-cache-loose-comparison.md.
    #[serde(flatten)]
    pub extra: serde_json::Map<String, serde_json::Value>,
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
///
/// HYPERCACHE CONTRACT: These fields are deserialized from JSON written by Python's
/// MinimalFeatureFlagSerializer (posthog/api/feature_flag.py). Field changes must
/// follow the expand-and-contract pattern. Golden fixture contract test:
///   cargo test -p feature-flags test_hypercache_contract
///
/// Encrypted-payload flags are excluded at the Python query layer, so this struct
/// has no field for `has_encrypted_payloads`.
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

/// Request-scoped view of flag definitions plus the per-request filter set.
/// All shared fields are `Arc`-backed so `clone()` is a refcount bump rather
/// than a deep copy.
#[derive(Clone, Debug, Default)]
pub struct FeatureFlagList {
    pub flags: PreparedFlags,
    /// Flag IDs to skip during evaluation: inactive, deleted, survey-excluded,
    /// runtime-mismatched, or tag-filtered. Recomputed per request, so it
    /// isn't part of the cached value.
    pub filtered_out_flag_ids: HashSet<i32>,
    /// Pre-computed dependency metadata from Django's hypercache.
    pub evaluation_metadata: Arc<EvaluationMetadata>,
    /// Cohort definitions referenced by flags (including transitive deps),
    /// precomputed by Django. When present, the matcher uses these instead of
    /// querying `CohortCacheManager`. `None` for PG-fallback or pre-cohort-bake
    /// teams.
    pub cohorts: Option<Arc<[Cohort]>>,
}

/// Immutable, pre-compiled flag definitions cached across requests. The
/// outer `Arc<PreparedFlagDefinitions>` is shared per team; each inner field
/// is independently reference-counted so a request-scoped `FeatureFlagList`
/// can share any subset without copying.
#[derive(Clone, Debug)]
pub struct PreparedFlagDefinitions {
    pub flags: PreparedFlags,
    pub evaluation_metadata: Arc<EvaluationMetadata>,
    pub cohorts: Option<Arc<[Cohort]>>,
}

impl PreparedFlagDefinitions {
    /// Estimates the heap memory footprint of this struct in bytes.
    /// Used by moka's weight-based eviction to enforce cache capacity limits.
    pub fn estimated_size_bytes(&self) -> usize {
        use crate::utils::json_size::estimate_json_size;

        let base = std::mem::size_of::<Self>();

        let flags_size: usize = self
            .flags
            .iter()
            .map(|f| {
                let struct_size = std::mem::size_of::<FeatureFlag>();
                let key_size = f.key.len();
                let name_size = f.name.as_ref().map_or(0, |n| n.len());
                let runtime_size = f.evaluation_runtime.as_ref().map_or(0, |r| r.len());
                let tags_size = f
                    .evaluation_tags
                    .as_ref()
                    .map_or(0, |tags| tags.iter().map(|t| t.len() + 24).sum());
                let bucketing_size = f.bucketing_identifier.as_ref().map_or(0, |b| b.len());
                let group_size = |groups: &[FlagPropertyGroup]| -> usize {
                    groups
                        .iter()
                        .map(|g| {
                            g.properties.as_ref().map_or(0, |props| {
                                props
                                    .iter()
                                    .map(|p| {
                                        let prop_base = std::mem::size_of::<PropertyFilter>();
                                        let prop_key = p.key.len();
                                        let prop_value =
                                            p.value.as_ref().map_or(0, estimate_json_size);
                                        let regex_overhead =
                                            if p.compiled_regex.is_some() { 2048 } else { 0 };
                                        prop_base + prop_key + prop_value + regex_overhead
                                    })
                                    .sum()
                            })
                        })
                        .sum()
                };
                let filters_size: usize = group_size(&f.filters.groups);

                let payloads_size = f.filters.payloads.as_ref().map_or(0, estimate_json_size);

                struct_size
                    + key_size
                    + name_size
                    + runtime_size
                    + tags_size
                    + bucketing_size
                    + filters_size
                    + payloads_size
            })
            .sum();

        let metadata_size = self.evaluation_metadata.dependency_stages.len() * 24
            + self.evaluation_metadata.transitive_deps.len() * 48;

        let cohorts_size = self.cohorts.as_ref().map_or(0, |cohorts| {
            cohorts
                .iter()
                .map(|c| c.estimated_size_bytes())
                .sum::<usize>()
        });

        base + flags_size + metadata_size + cohorts_size
    }
}

#[cfg(test)]
#[allow(clippy::needless_update)]
mod mock_impls {
    use super::*;
    use crate::utils::mock::{Mock, MockFrom};

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

    impl MockFrom<PropertyFilter> for FlagFilters {
        fn mock_from(property: PropertyFilter) -> Self {
            MockFrom::mock_from(vec![property])
        }
    }

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

    impl Mock for FeatureFlagList {
        fn mock() -> Self {
            FeatureFlagList {
                flags: PreparedFlags::seal(vec![<FeatureFlag as Mock>::mock()]),
                ..Default::default()
            }
        }
    }

    impl Mock for MultivariateFlagOptions {
        fn mock() -> Self {
            MultivariateFlagOptions {
                variants: vec![
                    MultivariateFlagVariant {
                        key: "control".to_string(),
                        name: Some("Control".to_string()),
                        rollout_percentage: 50.0,
                        ..Default::default()
                    },
                    MultivariateFlagVariant {
                        key: "test".to_string(),
                        name: Some("Test".to_string()),
                        rollout_percentage: 50.0,
                        ..Default::default()
                    },
                ],
            }
        }
    }

    impl Mock for EvaluationMetadata {
        fn mock() -> Self {
            EvaluationMetadata {
                dependency_stages: vec![],
                flags_with_missing_deps: vec![],
                transitive_deps: HashMap::new(),
            }
        }
    }

    impl MockFrom<Vec<FeatureFlag>> for FeatureFlagList {
        fn mock_from(flags: Vec<FeatureFlag>) -> Self {
            let evaluation_metadata = Arc::new(EvaluationMetadata::single_stage(&flags));
            FeatureFlagList {
                flags: PreparedFlags::seal(flags),
                evaluation_metadata,
                ..Default::default()
            }
        }
    }
}

#[cfg(test)]
mod unknown_key_passthrough_tests {
    //! Verify that unknown JSONB keys round-trip through deserialize/serialize
    //! unchanged via the `extra` field on `FlagFilters`, `FlagPropertyGroup`,
    //! and `PropertyFilter`.
    //!
    //! Without this passthrough, the Python `verify_flags_cache` verifier reports
    //! spurious `FIELD_MISMATCH` against the Django JSONB passthrough because Rust
    //! drops keys its structs don't enumerate (frontend leaks like `description`
    //! and `sort_key`, runtime annotations like `cohort_name`, legacy keys like
    //! `holdout_groups`, and field typos). See
    //! plans/verify-flags-cache-loose-comparison.md.
    use super::*;

    fn round_trip(json: serde_json::Value) -> serde_json::Value {
        let group: FlagPropertyGroup = serde_json::from_value(json)
            .expect("FlagPropertyGroup should deserialize cleanly with flatten extra");
        serde_json::to_value(&group).expect("FlagPropertyGroup should serialize cleanly")
    }

    #[test]
    fn flag_property_group_preserves_unknown_keys() {
        let input = serde_json::json!({
            "properties": [],
            "rollout_percentage": 100,
            "variant": null,
            "description": "rollout to enterprise",
            "sort_key": "abc-123"
        });

        let output = round_trip(input);

        assert_eq!(output["description"], "rollout to enterprise");
        assert_eq!(output["sort_key"], "abc-123");
    }

    #[test]
    fn flag_filters_preserves_holdout_groups_legacy_key() {
        let input = serde_json::json!({
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "holdout_groups": [
                {"properties": [], "rollout_percentage": 5, "variant": "holdout-42"}
            ]
        });

        let filters: FlagFilters = serde_json::from_value(input)
            .expect("FlagFilters should deserialize cleanly with flatten extra");
        let output = serde_json::to_value(&filters).expect("FlagFilters should serialize cleanly");

        let holdout_groups = output
            .get("holdout_groups")
            .expect("holdout_groups must survive the round-trip");
        assert!(holdout_groups.is_array());
        assert_eq!(holdout_groups[0]["variant"], "holdout-42");
    }

    #[test]
    fn property_filter_preserves_cohort_name_annotation() {
        let input = serde_json::json!({
            "key": "id",
            "value": 5,
            "type": "cohort",
            "operator": "in",
            "cohort_name": "QA users"
        });

        let property: PropertyFilter = serde_json::from_value(input)
            .expect("PropertyFilter should deserialize cleanly with flatten extra");
        let output =
            serde_json::to_value(&property).expect("PropertyFilter should serialize cleanly");

        assert_eq!(output["cohort_name"], "QA users");
    }

    #[test]
    fn aggregation_group_type_index_null_survives_flatten() {
        // Serde processes declared fields before `#[serde(flatten)]`, so the
        // explicit-null marker on the inner Option<Option<i32>> must round-trip
        // cleanly even with the new `extra` field in place. The matcher relies
        // on this distinction ("field present but null" = explicit person
        // aggregation; "field absent" = fall back to flag-level).
        let input = serde_json::json!({
            "properties": [],
            "rollout_percentage": 100,
            "aggregation_group_type_index": null
        });

        let group: FlagPropertyGroup = serde_json::from_value(input.clone())
            .expect("FlagPropertyGroup should deserialize cleanly");

        assert_eq!(
            group.aggregation_group_type_index,
            Some(None),
            "explicit null must deserialize as Some(None), not None"
        );
        // The flatten extra must not capture aggregation_group_type_index.
        assert!(!group.extra.contains_key("aggregation_group_type_index"));

        let output =
            serde_json::to_value(&group).expect("FlagPropertyGroup should serialize cleanly");

        assert!(
            output["aggregation_group_type_index"].is_null(),
            "explicit null must survive the round-trip, not be dropped or moved into extra"
        );
    }
}
