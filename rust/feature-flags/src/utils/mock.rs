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
/// `FeatureFlagRow` from a `FeatureFlag` for database insertion tests)
/// or for ergonomic type coercions (e.g., `&str` → `Option<String>`).
pub trait MockFrom<T> {
    fn mock_from(value: T) -> Self;
}

/// The reciprocal of [`MockFrom`].
pub trait MockInto<T> {
    fn mock_into(self) -> T;
}

impl<T, U: MockFrom<T>> MockInto<U> for T {
    fn mock_into(self) -> U {
        U::mock_from(self)
    }
}

impl<T> MockFrom<T> for T {
    fn mock_from(value: T) -> Self {
        value
    }
}

// Primitive / standard-library conversions

impl MockFrom<&str> for String {
    fn mock_from(value: &str) -> Self {
        value.to_owned()
    }
}

impl<X> MockFrom<X> for Option<String>
where
    String: MockFrom<X>,
{
    fn mock_from(value: X) -> Self {
        Some(String::mock_from(value))
    }
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
/// let flag = mock!(FeatureFlag, team_id: 42, key: "my_flag".mock_into());
///
/// // Nested mocks via MockInto
/// let flag = mock!(FeatureFlag,
///     filters: mock!(PropertyFilter, key: "country".mock_into()).mock_into()
/// );
///
/// // MockFrom -- create from another type
/// let row = mock!(FeatureFlagRow, from: flag.clone());
///
/// // MockFrom with additional overrides
/// let row = mock!(FeatureFlagRow, from: flag, key: "override".mock_into());
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

#[cfg(test)]
mod tests {
    use crate::cohorts::cohort_models::Cohort;
    use crate::flags::flag_models::{
        FeatureFlag, FeatureFlagRow, FlagFilters, FlagPropertyGroup, Holdout,
        MultivariateFlagVariant,
    };
    use crate::mock;
    use crate::properties::property_models::{OperatorType, PropertyType};
    use crate::utils::mock::MockInto;
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
    fn test_mock_feature_flag_with_overrides() {
        let flag = mock!(FeatureFlag,
            id: 42,
            team_id: 7,
            key: "custom_flag".mock_into(),
            active: false
        );

        assert_eq!(flag.id, 42);
        assert_eq!(flag.team_id, 7);
        assert_eq!(flag.key, "custom_flag");
        assert!(!flag.active);
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
        let pf = mock!(crate::properties::property_models::PropertyFilter);

        assert_eq!(pf.key, "test_prop");
        assert_eq!(pf.value, Some(json!("test_value")));
        assert_eq!(pf.operator, Some(OperatorType::Exact));
        assert_eq!(pf.prop_type, PropertyType::Person);
        assert!(pf.negation.is_none());
        assert!(pf.group_type_index.is_none());
    }

    #[test]
    fn test_mock_property_filter_with_overrides() {
        let pf = mock!(crate::properties::property_models::PropertyFilter,
            key: "email".mock_into(),
            value: Some(json!("test@example.com")),
            prop_type: PropertyType::Group,
            group_type_index: Some(0)
        );

        assert_eq!(pf.key, "email");
        assert_eq!(pf.value, Some(json!("test@example.com")));
        assert_eq!(pf.prop_type, PropertyType::Group);
        assert_eq!(pf.group_type_index, Some(0));
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
    fn test_mock_differs_from_default() {
        let mock_group = mock!(FlagPropertyGroup);
        let default_group = FlagPropertyGroup::default();
        assert_eq!(mock_group.rollout_percentage, Some(100.0));
        assert!(mock_group.properties.as_ref().unwrap().is_empty());
        assert_eq!(default_group.rollout_percentage, None);
        assert!(default_group.properties.is_none());

        let mock_filters = mock!(FlagFilters);
        let default_filters = FlagFilters::default();
        assert_eq!(mock_filters.groups.len(), 1);
        assert!(default_filters.groups.is_empty());
    }

    #[test]
    fn test_mock_from_feature_flag_to_row() {
        let flag = mock!(FeatureFlag,
            id: 5,
            team_id: 10,
            key: "converted_flag".mock_into(),
            active: false
        );
        let row = mock!(FeatureFlagRow, from: flag);

        assert_eq!(row.id, 5);
        assert_eq!(row.team_id, 10);
        assert_eq!(row.key, "converted_flag");
        assert!(!row.active);
        assert!(row.filters.is_object());
        assert!(row.filters.get("groups").is_some());
    }

    #[test]
    fn test_mock_from_with_overrides() {
        let flag = mock!(FeatureFlag, key: "original".mock_into());
        let row = mock!(FeatureFlagRow, from: flag.clone(), key: "overridden".mock_into());

        assert_eq!(row.key, "overridden");
        assert_eq!(row.id, flag.id);
        assert_eq!(row.team_id, flag.team_id);
    }

    #[test]
    fn test_mock_into_option_string() {
        let flag = mock!(FeatureFlag, name: "Custom Name".mock_into());
        assert_eq!(flag.name, Some("Custom Name".to_string()));

        let flag = mock!(FeatureFlag, bucketing_identifier: "device_id".mock_into());
        assert_eq!(flag.bucketing_identifier, Some("device_id".to_string()));
    }

    #[test]
    fn test_mock_into_property_filter_to_filters() {
        let filters: FlagFilters =
            mock!(crate::properties::property_models::PropertyFilter, key: "country".mock_into())
                .mock_into();

        assert_eq!(filters.groups.len(), 1);
        assert_eq!(filters.groups[0].rollout_percentage, Some(100.0));
        let props = filters.groups[0].properties.as_ref().unwrap();
        assert_eq!(props.len(), 1);
        assert_eq!(props[0].key, "country");
    }

    #[test]
    fn test_mock_into_vec_properties_to_filters() {
        let filters: FlagFilters = vec![
            mock!(crate::properties::property_models::PropertyFilter, key: "a".mock_into()),
            mock!(crate::properties::property_models::PropertyFilter, key: "b".mock_into()),
        ]
        .mock_into();

        assert_eq!(filters.groups.len(), 1);
        let props = filters.groups[0].properties.as_ref().unwrap();
        assert_eq!(props.len(), 2);
        assert_eq!(props[0].key, "a");
        assert_eq!(props[1].key, "b");
    }

    #[test]
    fn test_nested_mock_composition() {
        let flag = mock!(FeatureFlag,
            team_id: 42,
            filters: mock!(crate::properties::property_models::PropertyFilter,
                key: "country".mock_into(),
                value: Some(json!("US"))
            ).mock_into()
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
        let manual_flag = FeatureFlag {
            name: Some("Test Flag".to_string()),
            id: 1,
            key: "test_flag".to_string(),
            active: true,
            deleted: false,
            team_id: 99,
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![crate::properties::property_models::PropertyFilter {
                        key: "country".to_string(),
                        value: Some(json!("US")),
                        operator: Some(OperatorType::Exact),
                        prop_type: PropertyType::Person,
                        group_type_index: None,
                        negation: None,
                        compiled_regex: None,
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                feature_enrollment: None,
                holdout: None,
            },
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: None,
        };

        let mock_flag = mock!(FeatureFlag,
            team_id: 99,
            filters: mock!(crate::properties::property_models::PropertyFilter,
                key: "country".mock_into(),
                value: Some(json!("US"))
            ).mock_into()
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
    }

    #[test]
    fn test_mock_cohort_matches_manual_instantiation() {
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

        let mock_cohort = mock!(Cohort,
            description: "A test cohort".mock_into(),
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
        let flag = mock!(FeatureFlag, id: 99,);
        assert_eq!(flag.id, 99);

        let pf = mock!(crate::properties::property_models::PropertyFilter, key: "x".mock_into(),);
        assert_eq!(pf.key, "x");
    }
}
