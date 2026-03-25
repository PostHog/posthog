use crate::cohorts::cohort_models::Cohort;
use crate::flags::flag_models::{
    FeatureFlag, FeatureFlagRow, FlagFilters, FlagPropertyGroup, Holdout, MultivariateFlagVariant,
};
use crate::properties::property_models::{OperatorType, PropertyFilter, PropertyType};
use serde_json::json;

/// Like `Default`, but for test contexts. Provides sensible test defaults
/// (non-zero IDs, descriptive names, 100% rollout, etc.).
///
/// Unlike `Default`, `Mock` values are designed to be "obviously test data" --
/// for instance, `FeatureFlag::mock()` returns a flag with `key: "test_flag"`
/// and `active: true` rather than zero values.
pub trait Mock {
    fn mock() -> Self;
}

/// Create a mock of `Self` seeded from a value of type `T`.
///
/// Useful for converting between related types (e.g., building a
/// `FeatureFlagRow` from a `FeatureFlag` for database insertion tests).
pub trait MockFrom<T> {
    fn mock_from(source: &T) -> Self;
}

/// Creates a mock instance of a type implementing [`Mock`], with optional field overrides.
///
/// # Usage
///
/// ```rust,ignore
/// // No overrides -- pure defaults
/// let flag = mock!(FeatureFlag);
///
/// // With field overrides
/// let flag = mock!(FeatureFlag, team_id: 42, key: "my_flag".to_string());
///
/// // Nested mocks
/// let flag = mock!(FeatureFlag,
///     filters: mock_flag_filters_with_property(mock!(PropertyFilter))
/// );
///
/// // MockFrom -- create from another type
/// let row = mock!(FeatureFlagRow, from: &flag);
///
/// // MockFrom with additional overrides
/// let row = mock!(FeatureFlagRow, from: &flag, key: "override".to_string());
/// ```
#[macro_export]
macro_rules! mock {
    // No overrides
    ($T:path) => {
        <$T as $crate::utils::mock::Mock>::mock()
    };
    // MockFrom, no extra overrides (must precede the generic field-override arm)
    ($T:path, from: $source:expr) => {
        <$T as $crate::utils::mock::MockFrom<_>>::mock_from($source)
    };
    // MockFrom with field overrides
    ($T:path, from: $source:expr, $($field:ident : $value:expr),+ $(,)?) => {{
        let base = <$T as $crate::utils::mock::MockFrom<_>>::mock_from($source);
        $T { $($field: $value),+, ..base }
    }};
    // With field overrides via struct update syntax
    ($T:path, $($field:ident : $value:expr),+ $(,)?) => {{
        let base = <$T as $crate::utils::mock::Mock>::mock();
        $T { $($field: $value),+, ..base }
    }};
}

// ---------------------------------------------------------------------------
// Mock implementations
// ---------------------------------------------------------------------------

impl Mock for FeatureFlag {
    fn mock() -> Self {
        FeatureFlag {
            id: 1,
            team_id: 1,
            name: Some("Test Flag".to_string()),
            key: "test_flag".to_string(),
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                ..Default::default()
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: None,
        }
    }
}

impl Mock for FeatureFlagRow {
    fn mock() -> Self {
        FeatureFlagRow {
            id: 0,
            team_id: 1,
            name: Some("Test Flag".to_string()),
            key: "test_flag".to_string(),
            filters: json!({
                "groups": [{
                    "properties": [],
                    "rollout_percentage": 100
                }]
            }),
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: None,
        }
    }
}

impl Mock for PropertyFilter {
    fn mock() -> Self {
        PropertyFilter {
            key: "test_prop".to_string(),
            value: Some(json!("test_value")),
            operator: Some(OperatorType::Exact),
            prop_type: PropertyType::Person,
            negation: None,
            group_type_index: None,
        }
    }
}

impl Mock for Cohort {
    fn mock() -> Self {
        Cohort {
            id: 1,
            name: Some("Test Cohort".to_string()),
            description: Some("Test cohort description".to_string()),
            team_id: 1,
            deleted: false,
            filters: None,
            query: None,
            version: Some(1),
            pending_version: None,
            count: None,
            is_calculating: false,
            is_static: false,
            errors_calculating: 0,
            groups: json!({}),
            created_by_id: None,
            cohort_type: None,
            last_backfill_person_properties_at: None,
        }
    }
}

impl Mock for Holdout {
    fn mock() -> Self {
        Holdout {
            id: 1,
            exclusion_percentage: 10.0,
        }
    }
}

impl Mock for MultivariateFlagVariant {
    fn mock() -> Self {
        MultivariateFlagVariant {
            key: "control".to_string(),
            name: Some("Control".to_string()),
            rollout_percentage: 100.0,
        }
    }
}

impl Mock for FlagPropertyGroup {
    fn mock() -> Self {
        FlagPropertyGroup {
            properties: Some(vec![]),
            rollout_percentage: Some(100.0),
            variant: None,
            ..Default::default()
        }
    }
}

impl Mock for FlagFilters {
    fn mock() -> Self {
        FlagFilters {
            groups: vec![FlagPropertyGroup {
                properties: Some(vec![]),
                rollout_percentage: Some(100.0),
                variant: None,
                ..Default::default()
            }],
            ..Default::default()
        }
    }
}

// ---------------------------------------------------------------------------
// MockFrom implementations
// ---------------------------------------------------------------------------

impl MockFrom<FeatureFlag> for FeatureFlagRow {
    fn mock_from(flag: &FeatureFlag) -> Self {
        FeatureFlagRow {
            id: flag.id,
            team_id: flag.team_id,
            name: flag.name.clone(),
            key: flag.key.clone(),
            filters: serde_json::to_value(&flag.filters)
                .expect("Mock: failed to serialize FeatureFlag.filters to JSON"),
            deleted: flag.deleted,
            active: flag.active,
            ensure_experience_continuity: flag.ensure_experience_continuity,
            version: flag.version,
            evaluation_runtime: flag.evaluation_runtime.clone(),
            evaluation_tags: flag.evaluation_tags.clone(),
            bucketing_identifier: flag.bucketing_identifier.clone(),
        }
    }
}

// ---------------------------------------------------------------------------
// Convenience helpers
// ---------------------------------------------------------------------------

/// Creates `FlagFilters` with a single group containing the given properties at 100% rollout.
pub fn mock_flag_filters_with_properties(properties: Vec<PropertyFilter>) -> FlagFilters {
    FlagFilters {
        groups: vec![FlagPropertyGroup {
            properties: Some(properties),
            rollout_percentage: Some(100.0),
            ..Default::default()
        }],
        ..Default::default()
    }
}

/// Creates `FlagFilters` with a single group containing one `PropertyFilter` at 100% rollout.
pub fn mock_flag_filters_with_property(property: PropertyFilter) -> FlagFilters {
    mock_flag_filters_with_properties(vec![property])
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mock;
    use serde_json::json;

    #[test]
    fn test_mock_feature_flag_defaults() {
        let flag = mock!(FeatureFlag);

        assert_eq!(flag.id, 1);
        assert_eq!(flag.team_id, 1);
        assert_eq!(flag.name, Some("Test Flag".to_string()));
        assert_eq!(flag.key, "test_flag");
        assert!(flag.active);
        assert!(!flag.deleted);
        assert_eq!(flag.ensure_experience_continuity, Some(false));
        assert_eq!(flag.version, Some(1));
        assert_eq!(flag.evaluation_runtime, Some("all".to_string()));
        assert!(flag.evaluation_tags.is_none());
        assert!(flag.bucketing_identifier.is_none());
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(flag.filters.groups[0].rollout_percentage, Some(100.0));
    }

    #[test]
    fn test_mock_feature_flag_defaults_match_create_test_flag() {
        // Verify mock defaults match what create_test_flag(None x8) produces.
        // This is the original create_test_flag output, inlined for comparison.
        let expected = FeatureFlag {
            id: 1,
            team_id: 1,
            name: Some("Test Flag".to_string()),
            key: "test_flag".to_string(),
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout: None,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: None,
        };

        let actual = mock!(FeatureFlag);

        assert_eq!(actual.id, expected.id);
        assert_eq!(actual.team_id, expected.team_id);
        assert_eq!(actual.name, expected.name);
        assert_eq!(actual.key, expected.key);
        assert_eq!(actual.deleted, expected.deleted);
        assert_eq!(actual.active, expected.active);
        assert_eq!(
            actual.ensure_experience_continuity,
            expected.ensure_experience_continuity
        );
        assert_eq!(actual.version, expected.version);
        assert_eq!(actual.evaluation_runtime, expected.evaluation_runtime);
        assert_eq!(actual.evaluation_tags, expected.evaluation_tags);
        assert_eq!(actual.bucketing_identifier, expected.bucketing_identifier);
        assert_eq!(actual.filters.groups.len(), expected.filters.groups.len());
        assert_eq!(
            actual.filters.groups[0].rollout_percentage,
            expected.filters.groups[0].rollout_percentage
        );
        assert_eq!(
            actual.filters.groups[0]
                .properties
                .as_ref()
                .map(|v| v.len()),
            expected.filters.groups[0]
                .properties
                .as_ref()
                .map(|v| v.len())
        );
    }

    #[test]
    fn test_mock_feature_flag_with_overrides() {
        let flag = mock!(FeatureFlag,
            id: 42,
            team_id: 7,
            key: "custom_flag".to_string(),
            active: false
        );

        assert_eq!(flag.id, 42);
        assert_eq!(flag.team_id, 7);
        assert_eq!(flag.key, "custom_flag");
        assert!(!flag.active);
        // Non-overridden fields retain defaults
        assert_eq!(flag.name, Some("Test Flag".to_string()));
        assert!(!flag.deleted);
        assert_eq!(flag.version, Some(1));
    }

    #[test]
    fn test_mock_feature_flag_row_defaults() {
        let row = mock!(FeatureFlagRow);

        assert_eq!(row.id, 0);
        assert_eq!(row.team_id, 1);
        assert_eq!(row.key, "test_flag");
        assert!(row.active);
        assert!(!row.deleted);
        assert!(row.filters.is_object());
    }

    #[test]
    fn test_mock_property_filter_defaults() {
        let pf = mock!(PropertyFilter);

        assert_eq!(pf.key, "test_prop");
        assert_eq!(pf.value, Some(json!("test_value")));
        assert_eq!(pf.operator, Some(OperatorType::Exact));
        assert_eq!(pf.prop_type, PropertyType::Person);
        assert!(pf.negation.is_none());
        assert!(pf.group_type_index.is_none());
    }

    #[test]
    fn test_mock_property_filter_with_overrides() {
        let pf = mock!(PropertyFilter,
            key: "email".to_string(),
            value: Some(json!("test@example.com")),
            prop_type: PropertyType::Group,
            group_type_index: Some(0)
        );

        assert_eq!(pf.key, "email");
        assert_eq!(pf.value, Some(json!("test@example.com")));
        assert_eq!(pf.prop_type, PropertyType::Group);
        assert_eq!(pf.group_type_index, Some(0));
        // Non-overridden
        assert_eq!(pf.operator, Some(OperatorType::Exact));
    }

    #[test]
    fn test_mock_cohort_defaults() {
        let cohort = mock!(Cohort);

        assert_eq!(cohort.id, 1);
        assert_eq!(cohort.team_id, 1);
        assert_eq!(cohort.name, Some("Test Cohort".to_string()));
        assert!(!cohort.deleted);
        assert!(!cohort.is_static);
        assert!(!cohort.is_calculating);
        assert_eq!(cohort.errors_calculating, 0);
    }

    #[test]
    fn test_mock_holdout_defaults() {
        let holdout = mock!(Holdout);

        assert_eq!(holdout.id, 1);
        assert_eq!(holdout.exclusion_percentage, 10.0);
    }

    #[test]
    fn test_mock_multivariate_flag_variant_defaults() {
        let variant = mock!(MultivariateFlagVariant);

        assert_eq!(variant.key, "control");
        assert_eq!(variant.name, Some("Control".to_string()));
        assert_eq!(variant.rollout_percentage, 100.0);
    }

    #[test]
    fn test_mock_flag_property_group_differs_from_default() {
        let mock_group = mock!(FlagPropertyGroup);
        let default_group = FlagPropertyGroup::default();

        // Mock provides useful test defaults; Default gives all None
        assert_eq!(mock_group.rollout_percentage, Some(100.0));
        assert!(mock_group.properties.as_ref().unwrap().is_empty());
        assert_eq!(default_group.rollout_percentage, None);
        assert!(default_group.properties.is_none());
    }

    #[test]
    fn test_mock_flag_filters_differs_from_default() {
        let mock_filters = mock!(FlagFilters);
        let default_filters = FlagFilters::default();

        // Mock provides one group at 100%; Default gives empty groups
        assert_eq!(mock_filters.groups.len(), 1);
        assert!(default_filters.groups.is_empty());
    }

    #[test]
    fn test_mock_from_feature_flag_to_row() {
        let flag = mock!(FeatureFlag,
            id: 5,
            team_id: 10,
            key: "converted_flag".to_string(),
            active: false
        );

        let row = mock!(FeatureFlagRow, from: &flag);

        assert_eq!(row.id, 5);
        assert_eq!(row.team_id, 10);
        assert_eq!(row.key, "converted_flag");
        assert!(!row.active);
        assert_eq!(row.name, flag.name);
        assert_eq!(row.deleted, flag.deleted);
        assert_eq!(
            row.ensure_experience_continuity,
            flag.ensure_experience_continuity
        );
        assert_eq!(row.version, flag.version);
        assert_eq!(row.evaluation_runtime, flag.evaluation_runtime);
        // Filters should be serialized to JSON
        assert!(row.filters.is_object());
        assert!(row.filters.get("groups").is_some());
    }

    #[test]
    fn test_mock_from_with_overrides() {
        let flag = mock!(FeatureFlag, key: "original".to_string());

        let row = mock!(FeatureFlagRow, from: &flag, key: "overridden".to_string());

        assert_eq!(row.key, "overridden");
        // Other fields still come from the source flag
        assert_eq!(row.id, flag.id);
        assert_eq!(row.team_id, flag.team_id);
    }

    #[test]
    fn test_nested_mock_composition() {
        let flag = mock!(FeatureFlag,
            team_id: 42,
            filters: mock_flag_filters_with_property(
                mock!(PropertyFilter,
                    key: "country".to_string(),
                    value: Some(json!("US"))
                )
            )
        );

        assert_eq!(flag.team_id, 42);
        assert_eq!(flag.filters.groups.len(), 1);
        let props = flag.filters.groups[0].properties.as_ref().unwrap();
        assert_eq!(props.len(), 1);
        assert_eq!(props[0].key, "country");
        assert_eq!(props[0].value, Some(json!("US")));
        assert_eq!(props[0].operator, Some(OperatorType::Exact));
    }

    #[test]
    fn test_nested_mock_matches_manual_instantiation() {
        // The original manual code from handler/tests.rs:182-215
        let manual_flag = FeatureFlag {
            name: Some("Test Flag".to_string()),
            id: 1,
            key: "test_flag".to_string(),
            active: true,
            deleted: false,
            team_id: 99,
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "country".to_string(),
                        value: Some(json!("US")),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout: None,
            },
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: None,
        };

        // The equivalent mock! version
        let mock_flag = mock!(FeatureFlag,
            team_id: 99,
            filters: mock_flag_filters_with_property(
                mock!(PropertyFilter,
                    key: "country".to_string(),
                    value: Some(json!("US"))
                )
            )
        );

        assert_eq!(mock_flag.id, manual_flag.id);
        assert_eq!(mock_flag.team_id, manual_flag.team_id);
        assert_eq!(mock_flag.name, manual_flag.name);
        assert_eq!(mock_flag.key, manual_flag.key);
        assert_eq!(mock_flag.active, manual_flag.active);
        assert_eq!(mock_flag.deleted, manual_flag.deleted);
        assert_eq!(
            mock_flag.ensure_experience_continuity,
            manual_flag.ensure_experience_continuity
        );
        assert_eq!(mock_flag.version, manual_flag.version);
        assert_eq!(mock_flag.evaluation_runtime, manual_flag.evaluation_runtime);
        assert_eq!(mock_flag.evaluation_tags, manual_flag.evaluation_tags);
        assert_eq!(
            mock_flag.bucketing_identifier,
            manual_flag.bucketing_identifier
        );
        // Filters structure
        assert_eq!(
            mock_flag.filters.groups.len(),
            manual_flag.filters.groups.len()
        );
        assert_eq!(
            mock_flag.filters.groups[0].rollout_percentage,
            manual_flag.filters.groups[0].rollout_percentage
        );
        let mock_props = mock_flag.filters.groups[0].properties.as_ref().unwrap();
        let manual_props = manual_flag.filters.groups[0].properties.as_ref().unwrap();
        assert_eq!(mock_props.len(), manual_props.len());
        assert_eq!(mock_props[0].key, manual_props[0].key);
        assert_eq!(mock_props[0].value, manual_props[0].value);
        assert_eq!(mock_props[0].operator, manual_props[0].operator);
        assert_eq!(mock_props[0].prop_type, manual_props[0].prop_type);
        assert_eq!(mock_props[0].negation, manual_props[0].negation);
        assert_eq!(
            mock_props[0].group_type_index,
            manual_props[0].group_type_index
        );
    }

    #[test]
    fn test_mock_flag_filters_with_properties_helper() {
        let props = vec![
            mock!(PropertyFilter, key: "a".to_string()),
            mock!(PropertyFilter, key: "b".to_string()),
        ];
        let filters = mock_flag_filters_with_properties(props);

        assert_eq!(filters.groups.len(), 1);
        let group_props = filters.groups[0].properties.as_ref().unwrap();
        assert_eq!(group_props.len(), 2);
        assert_eq!(group_props[0].key, "a");
        assert_eq!(group_props[1].key, "b");
        assert_eq!(filters.groups[0].rollout_percentage, Some(100.0));
        assert!(filters.multivariate.is_none());
        assert!(filters.holdout.is_none());
    }

    #[test]
    fn test_mock_cohort_matches_manual_instantiation() {
        // The original manual code from cohort_models.rs:159-183
        let manual_cohort = Cohort {
            id: 1,
            name: Some("Test Cohort".to_string()),
            description: Some("A test cohort".to_string()),
            team_id: 1,
            deleted: false,
            filters: Some(json!({"type": "AND", "values": []})),
            query: None,
            version: Some(1),
            pending_version: None,
            count: Some(100),
            is_calculating: false,
            is_static: false,
            errors_calculating: 0,
            groups: json!({}),
            created_by_id: Some(1),
            cohort_type: None,
            last_backfill_person_properties_at: None,
        };

        // Equivalent mock! version -- only override the fields that differ from mock defaults
        let mock_cohort = mock!(Cohort,
            description: Some("A test cohort".to_string()),
            filters: Some(json!({"type": "AND", "values": []})),
            count: Some(100),
            created_by_id: Some(1)
        );

        assert_eq!(mock_cohort.id, manual_cohort.id);
        assert_eq!(mock_cohort.team_id, manual_cohort.team_id);
        assert_eq!(mock_cohort.name, manual_cohort.name);
        assert_eq!(mock_cohort.deleted, manual_cohort.deleted);
        assert_eq!(mock_cohort.filters, manual_cohort.filters);
        assert_eq!(mock_cohort.query, manual_cohort.query);
        assert_eq!(mock_cohort.version, manual_cohort.version);
        assert_eq!(mock_cohort.pending_version, manual_cohort.pending_version);
        assert_eq!(mock_cohort.count, manual_cohort.count);
        assert_eq!(mock_cohort.is_calculating, manual_cohort.is_calculating);
        assert_eq!(mock_cohort.is_static, manual_cohort.is_static);
        assert_eq!(
            mock_cohort.errors_calculating,
            manual_cohort.errors_calculating
        );
        assert_eq!(mock_cohort.groups, manual_cohort.groups);
        assert_eq!(mock_cohort.created_by_id, manual_cohort.created_by_id);
        assert_eq!(mock_cohort.cohort_type, manual_cohort.cohort_type);
    }

    #[test]
    fn test_trailing_comma_in_macro() {
        // Trailing commas should be accepted
        let flag = mock!(FeatureFlag, id: 99,);
        assert_eq!(flag.id, 99);

        let pf = mock!(PropertyFilter, key: "x".to_string(),);
        assert_eq!(pf.key, "x");
    }
}
