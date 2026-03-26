use std::collections::HashMap;

use serde_json::Value;

use crate::flags::flag_models::FlagFilters;

impl FlagFilters {
    /// Returns the person property key used for early access feature enrollment.
    pub fn enrollment_key(flag_key: &str) -> String {
        format!("$feature_enrollment/{}", flag_key)
    }

    pub fn requires_db_properties(
        &self,
        overrides: &HashMap<String, Value>,
        flag_key: &str,
    ) -> bool {
        self.aggregation_group_type_index.is_some()
            || (self.feature_enrollment == Some(true) && {
                !overrides.contains_key(&Self::enrollment_key(flag_key))
            })
            || self
                .super_groups
                .as_ref()
                .is_some_and(|groups| groups.iter().any(|g| g.requires_db_properties(overrides)))
            || self
                .groups
                .iter()
                .any(|group| group.requires_db_properties(overrides))
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

    use crate::flags::flag_models::FlagPropertyGroup;
    use crate::mock;
    use crate::properties::property_models::{OperatorType, PropertyType};
    use crate::utils::mock::MockInto;

    use super::*;

    fn pf(key: &str, prop_type: PropertyType, operator: OperatorType) -> crate::properties::property_models::PropertyFilter {
        mock!(crate::properties::property_models::PropertyFilter,
            key: key.mock_into(),
            prop_type: prop_type,
            operator: Some(operator)
        )
    }

    fn group(props: Vec<crate::properties::property_models::PropertyFilter>, rollout: f64) -> FlagPropertyGroup {
        mock!(FlagPropertyGroup,
            properties: Some(props),
            rollout_percentage: Some(rollout)
        )
    }

    fn filters(groups: Vec<FlagPropertyGroup>) -> FlagFilters {
        mock!(FlagFilters, groups: groups)
    }

    #[rstest]
    #[case(100.0, true)]
    #[case(50.0, true)]
    #[case(0.0, false)]
    fn test_requires_cohort_filters_if_cohort_filter_set_and_rollout_percentage_not_zero(
        #[case] rollout_percentage: f64,
        #[case] expected: bool,
    ) {
        let f = filters(vec![group(
            vec![pf("cohort", PropertyType::Cohort, OperatorType::Exact)],
            rollout_percentage,
        )]);

        assert_eq!(f.requires_cohort_filters(), expected);
    }

    #[test]
    fn test_requires_db_properties_when_overrides_not_enough() {
        let f = filters(vec![
            group(
                vec![
                    pf("some_key", PropertyType::Person, OperatorType::Exact),
                    pf("another_key", PropertyType::Person, OperatorType::Exact),
                ],
                100.0,
            ),
            group(
                vec![pf("yet_another_key", PropertyType::Person, OperatorType::Exact)],
                100.0,
            ),
        ]);

        {
            // Not enough overrides to evaluate locally
            let overrides = HashMap::from([
                ("some_key".to_string(), Value::String("value".to_string())),
                ("another_key".to_string(), Value::String("value".to_string())),
            ]);

            assert!(f.requires_db_properties(&overrides, "test-flag"));
        }

        {
            // Enough overrides to evaluate locally
            let overrides = HashMap::from([
                ("some_key".to_string(), Value::String("value".to_string())),
                ("another_key".to_string(), Value::String("value".to_string())),
                ("yet_another_key".to_string(), Value::String("value".to_string())),
            ]);

            assert!(!f.requires_db_properties(&overrides, "test-flag"));
        }
    }

    #[test]
    fn test_requires_cohorts_when_groups_have_cohorts() {
        let f = filters(vec![group(
            vec![pf("some_key", PropertyType::Cohort, OperatorType::Exact)],
            100.0,
        )]);

        assert!(f.requires_cohort_filters());
    }

    #[test]
    fn test_holdout_does_not_require_cohorts() {
        use crate::flags::flag_models::Holdout;
        let mut f = filters(vec![]);
        f.holdout = Some(Holdout {
            id: 1,
            exclusion_percentage: 10.0,
        });

        assert!(!f.requires_cohort_filters());
    }

    #[test]
    fn test_requires_db_properties_when_aggregation_group_type_index_set() {
        let mut f = filters(vec![]);
        f.aggregation_group_type_index = Some(1);

        // Even though there are no properties, we still need to evaluate the DB properties
        // because the group type index is set.
        assert!(f.requires_db_properties(&HashMap::new(), "test-flag"));
    }

    #[test]
    fn test_super_groups_require_db_properties_when_overrides_insufficient() {
        let mut f = filters(vec![]);
        f.super_groups = Some(vec![group(
            vec![pf(
                "$feature_enrollment/feature-flags-flag-dependency",
                PropertyType::Person,
                OperatorType::Exact,
            )],
            100.0,
        )]);

        {
            // Without overrides, DB lookup is required
            assert!(f.requires_db_properties(&HashMap::new(), "test-flag"));
        }

        {
            // With sufficient overrides, DB lookup is not required
            let overrides = HashMap::from([(
                "$feature_enrollment/feature-flags-flag-dependency".to_string(),
                Value::String("value".to_string()),
            )]);
            assert!(!f.requires_db_properties(&overrides, "test-flag"));
        }
    }

    #[test]
    fn test_feature_enrollment_requires_db_properties_when_override_missing() {
        let mut f = filters(vec![]);
        f.feature_enrollment = Some(true);

        assert!(f.requires_db_properties(&HashMap::new(), "my-flag"));
    }

    #[test]
    fn test_feature_enrollment_skips_db_when_override_present() {
        let mut f = filters(vec![]);
        f.feature_enrollment = Some(true);

        let overrides = HashMap::from([(
            FlagFilters::enrollment_key("my-flag"),
            Value::String("true".to_string()),
        )]);
        assert!(!f.requires_db_properties(&overrides, "my-flag"));
    }

    #[test]
    fn test_does_not_require_db_properties_when_super_groups_empty() {
        let mut f = filters(vec![]);
        f.super_groups = Some(vec![]);

        // Empty super_groups don't require DB properties
        assert!(!f.requires_db_properties(&HashMap::new(), "test-flag"));
    }

    #[test]
    fn test_does_not_require_db_properties_when_holdout_set() {
        use crate::flags::flag_models::Holdout;
        let mut f = filters(vec![]);
        f.holdout = Some(Holdout {
            id: 1,
            exclusion_percentage: 10.0,
        });

        // Holdouts don't require DB properties.
        assert!(!f.requires_db_properties(&HashMap::new(), "test-flag"));
    }

    #[test]
    fn test_requires_db_properties_when_not_enough_overrides_single_group() {
        let f = filters(vec![group(
            vec![
                pf("some_key", PropertyType::Person, OperatorType::Exact),
                pf("another_key", PropertyType::Person, OperatorType::Exact),
            ],
            100.0,
        )]);

        {
            let overrides =
                HashMap::from([("some_key".to_string(), Value::String("value".to_string()))]);
            assert!(f.requires_db_properties(&overrides, "test-flag"));
        }

        {
            let overrides = HashMap::from([
                ("some_key".to_string(), Value::String("value".to_string())),
                ("another_key".to_string(), Value::String("value".to_string())),
                ("yet_another_key".to_string(), Value::String("value".to_string())),
            ]);
            assert!(!f.requires_db_properties(&overrides, "test-flag"));
        }
    }

    #[test]
    fn test_requires_db_properties_when_overrides_not_enough_for_multiple_groups() {
        let f = filters(vec![
            group(
                vec![
                    pf("some_key", PropertyType::Person, OperatorType::Exact),
                    pf("another_key", PropertyType::Person, OperatorType::Exact),
                ],
                100.0,
            ),
            group(
                vec![pf("yet_another_key", PropertyType::Person, OperatorType::Exact)],
                100.0,
            ),
        ]);

        {
            // Not enough overrides to evaluate locally
            let overrides = HashMap::from([
                ("some_key".to_string(), Value::String("value".to_string())),
                ("another_key".to_string(), Value::String("value".to_string())),
            ]);

            assert!(f.requires_db_properties(&overrides, "test-flag"));
        }

        {
            // Enough overrides to evaluate locally
            let overrides = HashMap::from([
                ("some_key".to_string(), Value::String("value".to_string())),
                ("another_key".to_string(), Value::String("value".to_string())),
                ("yet_another_key".to_string(), Value::String("value".to_string())),
            ]);

            assert!(!f.requires_db_properties(&overrides, "test-flag"));
        }
    }
}
