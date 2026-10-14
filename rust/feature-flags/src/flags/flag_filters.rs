use std::collections::HashMap;

use serde_json::Value;

use crate::cohorts::cohort_models::CohortId;
use crate::flags::config_v2::Subject;
use crate::flags::flag_group_type_mapping::GroupTypeIndex;
use crate::flags::flag_models::{FeatureFlagId, FlagFilters};
use crate::properties::property_models::PropertyFilter;

#[derive(Debug, Default, PartialEq, Eq)]
pub struct FlagRequirements {
    pub cohort_ids: Vec<CohortId>,
    pub flag_ids: Vec<FeatureFlagId>,
    pub aggregation_group_type_indexes: Vec<GroupTypeIndex>,
    pub group_property_type_indexes: Vec<GroupTypeIndex>,
}

impl FlagFilters {
    /// An unsupported document references nothing: it fails per flag before evaluation.
    pub fn requirements(&self) -> FlagRequirements {
        let mut requirements = FlagRequirements::default();
        if !self.is_v1() {
            let Some(config) = self.supported_v2() else {
                return requirements;
            };
            requirements
                .aggregation_group_type_indexes
                .extend(config.aggregation_group_type_index);
            for predicate in config.rules.iter().flat_map(|rule| &rule.targeting) {
                match predicate.subject {
                    Subject::Person => {}
                    Subject::Cohort(id) => requirements.cohort_ids.push(id),
                    Subject::Group(index) => requirements.group_property_type_indexes.push(index),
                    Subject::Flag(id) => requirements.flag_ids.push(id),
                }
            }
            return requirements;
        }
        requirements
            .aggregation_group_type_indexes
            .extend(self.aggregation_group_type_index);
        for group in &self.groups {
            requirements
                .aggregation_group_type_indexes
                .extend(group.aggregation_group_type_index.flatten());
            let aggregation = group.effective_aggregation(self.aggregation_group_type_index);
            for property in group.properties.iter().flatten() {
                requirements.cohort_ids.extend(property.get_cohort_id());
                requirements.flag_ids.extend(property.get_feature_flag_id());
                requirements
                    .group_property_type_indexes
                    .extend(property.group_filter_index(aggregation));
            }
        }
        requirements
    }

    /// Flag IDs whose variant this config reads. A v1 `flag_evaluates_to` filter with a string
    /// value reads the variant, and a `true` or `false` value reads only whether the flag
    /// matched. Every v2 flag reference counts, because this method does not inspect v2
    /// predicate values.
    pub fn flag_ids_read_by_variant(&self) -> Vec<FeatureFlagId> {
        if !self.is_v1() {
            return self.requirements().flag_ids;
        }
        self.groups
            .iter()
            .flat_map(|group| group.properties.iter().flatten())
            .filter(|property| matches!(property.value, Some(Value::String(_))))
            .filter_map(|property| property.get_feature_flag_id())
            .collect()
    }

    /// Returns the person property key used for early access feature enrollment.
    pub fn enrollment_key(flag_key: &str) -> String {
        format!("$feature_enrollment/{}", flag_key)
    }

    /// Whether an enrollment property value means "opted in": `"true"` or boolean `true`. Any
    /// other present value means opted out.
    pub fn is_enrolled(value: &Value) -> bool {
        value == "true" || value == &Value::Bool(true)
    }

    pub fn requires_db_properties(
        &self,
        overrides: &HashMap<String, Value>,
        flag_key: &str,
        group_filter_needs_db: &dyn Fn(&PropertyFilter, Option<GroupTypeIndex>) -> bool,
    ) -> bool {
        self.aggregation_group_type_index.is_some()
            || (self.feature_enrollment == Some(true) && {
                !overrides.contains_key(&Self::enrollment_key(flag_key))
            })
            || self
                .groups
                .iter()
                .any(|group| matches!(group.aggregation_group_type_index, Some(Some(_))))
            || self.groups.iter().any(|group| {
                // Group filters resolve their index against the condition's aggregation,
                // so the caller-supplied decision gets the same aggregation matching uses.
                let effective_aggregation =
                    group.effective_aggregation(self.aggregation_group_type_index);
                group.requires_db_properties(overrides, &|prop| {
                    group_filter_needs_db(prop, effective_aggregation)
                })
            })
    }

    pub fn requires_cohort_filters(&self) -> bool {
        self.groups
            .iter()
            .any(|group| group.requires_cohort_filters())
    }
}

#[cfg(test)]
mod tests {
    use rstest::rstest;

    use serde_json::json;

    use crate::flags::config_format::decode_filters;
    use crate::flags::flag_models::FlagPropertyGroup;
    use crate::flags::test_helpers::v2_filters_referencing;
    use crate::mock;
    use crate::properties::property_models::{PropertyFilter, PropertyType};
    use crate::utils::mock::MockInto;

    use super::*;

    #[test]
    fn requirements_read_every_v1_condition_with_matching_aggregation() {
        let filters = decode_filters(json!({
            "aggregation_group_type_index": 0,
            "groups": [
                {"rollout_percentage": 0, "properties": [
                    {"key": "id", "type": "cohort", "value": 7},
                    {"key": "8", "type": "flag", "value": true, "operator": "flag_evaluates_to"}
                ]},
                {"aggregation_group_type_index": null, "properties": [
                    {"key": "id", "type": "cohort", "value": "9"},
                    {"key": "tier", "type": "group", "value": "pro", "group_type_index": 3},
                    {"key": "plan", "type": "group", "value": "pro"}
                ]},
                {"aggregation_group_type_index": 2, "properties": [
                    {"key": "size", "type": "group", "value": 5}
                ]}
            ]
        }))
        .unwrap();
        assert_eq!(
            filters.requirements(),
            FlagRequirements {
                cohort_ids: vec![7, 9],
                flag_ids: vec![8],
                aggregation_group_type_indexes: vec![0, 2],
                group_property_type_indexes: vec![3, 2],
            }
        );
    }

    #[test]
    fn requirements_read_the_parsed_v2_config() {
        let filters = v2_filters_referencing(
            &[Subject::Cohort(7), Subject::Flag(8), Subject::Group(3)],
            Some(1),
        );
        assert_eq!(
            filters.requirements(),
            FlagRequirements {
                cohort_ids: vec![7],
                flag_ids: vec![8],
                aggregation_group_type_indexes: vec![1],
                group_property_type_indexes: vec![3],
            }
        );
        assert_eq!(
            v2_filters_referencing(&[], None).requirements(),
            FlagRequirements::default()
        );
    }

    #[test]
    fn unsupported_documents_require_nothing() {
        let rule = |property: Value| {
            json!({"id": "00000000-0000-4000-8000-000000000001", "rule_type": "targeted_release",
                "targeting": {"properties": [property]}, "value": true})
        };
        for document in [
            json!({"version": 3, "groups": [{"properties": [{"key": "id", "type": "cohort", "value": 7}]}]}),
            json!({"version": 2, "return_type": "boolean", "default_value": false, "rules": [],
                "aggregation_group_type_index": 1}),
            json!({"version": 2, "return_type": "boolean", "default_value": false,
                "rules": [rule(json!({"key": "id", "type": "cohort", "value": 7}))]}),
            json!({"version": 2, "return_type": "boolean", "default_value": false,
                "rules": [rule(json!({"key": "tier", "type": "group", "value": "pro", "group_type_index": 3}))]}),
        ] {
            let filters = decode_filters(document).unwrap();
            assert!(filters.non_v1.is_some());
            assert_eq!(filters.requirements(), FlagRequirements::default());
        }
    }

    #[rstest]
    #[case(100.0, true)]
    #[case(50.0, true)]
    #[case(0.0, false)]
    fn test_requires_cohort_filters_if_cohort_filter_set_and_rollout_percentage_not_zero(
        #[case] rollout_percentage: f64,
        #[case] expected: bool,
    ) {
        let f = mock!(FlagFilters, groups: vec![
            mock!(FlagPropertyGroup,
                properties: Some(vec![mock!(PropertyFilter,
                    key: "cohort".mock_into(),
                    prop_type: PropertyType::Cohort
                )]),
                rollout_percentage: Some(rollout_percentage)
            )
        ]);

        assert_eq!(f.requires_cohort_filters(), expected);
    }

    #[test]
    fn test_requires_db_properties_when_overrides_not_enough() {
        let f = mock!(FlagFilters, groups: vec![
            mock!(FlagPropertyGroup,
                properties: Some(vec![
                    mock!(PropertyFilter, key: "some_key".mock_into()),
                    mock!(PropertyFilter, key: "another_key".mock_into()),
                ])
            ),
            mock!(FlagPropertyGroup,
                properties: Some(vec![
                    mock!(PropertyFilter, key: "yet_another_key".mock_into()),
                ])
            ),
        ]);

        {
            // Not enough overrides to evaluate locally
            let overrides = HashMap::from([
                ("some_key".to_string(), Value::String("value".to_string())),
                (
                    "another_key".to_string(),
                    Value::String("value".to_string()),
                ),
            ]);

            assert!(f.requires_db_properties(&overrides, "test-flag", &|_, _| true));
        }

        {
            // Enough overrides to evaluate locally
            let overrides = HashMap::from([
                ("some_key".to_string(), Value::String("value".to_string())),
                (
                    "another_key".to_string(),
                    Value::String("value".to_string()),
                ),
                (
                    "yet_another_key".to_string(),
                    Value::String("value".to_string()),
                ),
            ]);

            assert!(!f.requires_db_properties(&overrides, "test-flag", &|_, _| true));
        }
    }

    #[test]
    fn test_requires_cohorts_when_groups_have_cohorts() {
        let f = mock!(FlagFilters, groups: vec![
            mock!(FlagPropertyGroup,
                properties: Some(vec![
                    mock!(PropertyFilter, key: "some_key".mock_into(), prop_type: PropertyType::Cohort),
                ])
            )
        ]);

        assert!(f.requires_cohort_filters());
    }

    #[test]
    fn test_holdout_does_not_require_cohorts() {
        use crate::flags::flag_models::Holdout;
        let mut f = mock!(FlagFilters, groups: vec![]);
        f.holdout = Some(mock!(Holdout));

        assert!(!f.requires_cohort_filters());
    }

    #[test]
    fn test_requires_db_properties_when_aggregation_group_type_index_set() {
        let mut f = mock!(FlagFilters, groups: vec![]);
        f.aggregation_group_type_index = Some(1);

        // Even though there are no properties, we still need to evaluate the DB properties
        // because the group type index is set.
        assert!(f.requires_db_properties(&HashMap::new(), "test-flag", &|_, _| true));
    }

    #[test]
    fn test_feature_enrollment_requires_db_properties_when_override_missing() {
        let mut f = mock!(FlagFilters, groups: vec![]);
        f.feature_enrollment = Some(true);

        assert!(f.requires_db_properties(&HashMap::new(), "my-flag", &|_, _| true));
    }

    #[test]
    fn test_feature_enrollment_skips_db_when_override_present() {
        let mut f = mock!(FlagFilters, groups: vec![]);
        f.feature_enrollment = Some(true);

        let overrides = HashMap::from([(
            FlagFilters::enrollment_key("my-flag"),
            Value::String("true".to_string()),
        )]);
        assert!(!f.requires_db_properties(&overrides, "my-flag", &|_, _| true));
    }

    #[test]
    fn test_does_not_require_db_properties_when_holdout_set() {
        use crate::flags::flag_models::Holdout;
        let mut f = mock!(FlagFilters, groups: vec![]);
        f.holdout = Some(mock!(Holdout));

        // Holdouts don't require DB properties.
        assert!(!f.requires_db_properties(&HashMap::new(), "test-flag", &|_, _| true));
    }

    #[test]
    fn test_requires_db_properties_when_not_enough_overrides_single_group() {
        let f = mock!(FlagFilters, groups: vec![
            mock!(FlagPropertyGroup,
                properties: Some(vec![
                    mock!(PropertyFilter, key: "some_key".mock_into()),
                    mock!(PropertyFilter, key: "another_key".mock_into()),
                ])
            )
        ]);

        {
            let overrides =
                HashMap::from([("some_key".to_string(), Value::String("value".to_string()))]);
            assert!(f.requires_db_properties(&overrides, "test-flag", &|_, _| true));
        }

        {
            let overrides = HashMap::from([
                ("some_key".to_string(), Value::String("value".to_string())),
                (
                    "another_key".to_string(),
                    Value::String("value".to_string()),
                ),
                (
                    "yet_another_key".to_string(),
                    Value::String("value".to_string()),
                ),
            ]);
            assert!(!f.requires_db_properties(&overrides, "test-flag", &|_, _| true));
        }
    }

    #[test]
    fn test_requires_db_properties_when_overrides_not_enough_for_multiple_groups() {
        let f = mock!(FlagFilters, groups: vec![
            mock!(FlagPropertyGroup,
                properties: Some(vec![
                    mock!(PropertyFilter, key: "some_key".mock_into()),
                    mock!(PropertyFilter, key: "another_key".mock_into()),
                ])
            ),
            mock!(FlagPropertyGroup,
                properties: Some(vec![
                    mock!(PropertyFilter, key: "yet_another_key".mock_into()),
                ])
            ),
        ]);

        {
            // Not enough overrides to evaluate locally
            let overrides = HashMap::from([
                ("some_key".to_string(), Value::String("value".to_string())),
                (
                    "another_key".to_string(),
                    Value::String("value".to_string()),
                ),
            ]);

            assert!(f.requires_db_properties(&overrides, "test-flag", &|_, _| true));
        }

        {
            // Enough overrides to evaluate locally
            let overrides = HashMap::from([
                ("some_key".to_string(), Value::String("value".to_string())),
                (
                    "another_key".to_string(),
                    Value::String("value".to_string()),
                ),
                (
                    "yet_another_key".to_string(),
                    Value::String("value".to_string()),
                ),
            ]);

            assert!(!f.requires_db_properties(&overrides, "test-flag", &|_, _| true));
        }
    }
}
