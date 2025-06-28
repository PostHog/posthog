use std::collections::HashMap;

use serde_json::Value;

use crate::flags::flag_models::{FlagFilters, FlagPropertyGroup};

impl FlagFilters {
    pub fn requires_db_properties(&self, overrides: &HashMap<String, Value>) -> bool {
        self.aggregation_group_type_index.is_some()
            || any_group_requires_db_properties(Some(&self.groups), overrides)
            || any_group_requires_db_properties(self.super_groups.as_ref(), overrides)
            || any_group_requires_db_properties(self.holdout_groups.as_ref(), overrides)
    }

    pub fn requires_cohort_filters(&self) -> bool {
        any_group_requires_cohort_filters(Some(&self.groups))
            || any_group_requires_cohort_filters(self.super_groups.as_ref())
            || any_group_requires_cohort_filters(self.holdout_groups.as_ref())
    }
}

fn any_group_requires_db_properties(
    groups: Option<&Vec<FlagPropertyGroup>>,
    overrides: &HashMap<String, Value>,
) -> bool {
    groups.map_or(false, |groups| {
        groups
            .iter()
            .any(|group| group.requires_db_properties(overrides))
    })
}

fn any_group_requires_cohort_filters(groups: Option<&Vec<FlagPropertyGroup>>) -> bool {
    groups.map_or(false, |groups| {
        groups.iter().any(|group| group.requires_cohort_filters())
    })
}

#[cfg(test)]
mod tests {
    use rstest::rstest;

    use crate::{
        flags::test_helpers::{
            create_simple_flag_filters, create_simple_flag_property_group,
            create_simple_property_filter,
        },
        properties::property_models::{OperatorType, PropertyType},
    };

    use super::*;

    #[rstest]
    #[case(100.0, true)]
    #[case(50.0, true)]
    #[case(0.0, false)]
    fn test_requires_cohort_filters_if_cohort_filter_set_and_rollout_percentage_not_zero(
        #[case] rollout_percentage: f64,
        #[case] expected: bool,
    ) {
        let filters = create_simple_flag_filters(vec![create_simple_flag_property_group(
            vec![create_simple_property_filter(
                "cohort",
                PropertyType::Cohort,
                OperatorType::Exact,
            )],
            rollout_percentage,
        )]);

        assert_eq!(filters.requires_cohort_filters(), expected);
    }

    #[test]
    fn test_requires_db_properties_when_overrides_not_enough() {
        let filters = create_simple_flag_filters(vec![
            create_simple_flag_property_group(
                vec![
                    create_simple_property_filter(
                        "some_key",
                        PropertyType::Person,
                        OperatorType::Exact,
                    ),
                    create_simple_property_filter(
                        "another_key",
                        PropertyType::Person,
                        OperatorType::Exact,
                    ),
                ],
                100.0,
            ),
            create_simple_flag_property_group(
                vec![create_simple_property_filter(
                    "yet_another_key",
                    PropertyType::Person,
                    OperatorType::Exact,
                )],
                100.0,
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

            assert!(filters.requires_db_properties(&overrides));
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

            assert!(!filters.requires_db_properties(&overrides));
        }
    }

    #[test]
    fn test_requires_cohorts_when_groups_have_cohorts() {
        let filters = create_simple_flag_filters(vec![create_simple_flag_property_group(
            vec![create_simple_property_filter(
                "some_key",
                PropertyType::Cohort,
                OperatorType::Exact,
            )],
            100.0,
        )]);

        assert!(filters.requires_cohort_filters());
    }

    #[test]
    fn test_requires_db_properties_when_aggregation_group_type_index_set() {
        let mut filters = create_simple_flag_filters(vec![]);
        filters.aggregation_group_type_index = Some(1);

        // Even though there are no properties, we still need to evaluate the DB properties
        // because the group type index is set.
        assert!(filters.requires_db_properties(&HashMap::new()));
    }

    #[test]
    fn test_requires_db_properties_when_not_enough_overrides_single_group() {
        let groups = vec![create_simple_flag_property_group(
            vec![
                create_simple_property_filter(
                    "some_key",
                    PropertyType::Person,
                    OperatorType::Exact,
                ),
                create_simple_property_filter(
                    "another_key",
                    PropertyType::Person,
                    OperatorType::Exact,
                ),
            ],
            100.0,
        )];

        {
            let overrides =
                HashMap::from([("some_key".to_string(), Value::String("value".to_string()))]);
            assert!(any_group_requires_db_properties(Some(&groups), &overrides));
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
            assert!(!any_group_requires_db_properties(Some(&groups), &overrides));
        }
    }

    #[test]
    fn test_requires_db_properties_when_overrides_not_enough_for_multiple_groups() {
        let groups = vec![
            create_simple_flag_property_group(
                vec![
                    create_simple_property_filter(
                        "some_key",
                        PropertyType::Person,
                        OperatorType::Exact,
                    ),
                    create_simple_property_filter(
                        "another_key",
                        PropertyType::Person,
                        OperatorType::Exact,
                    ),
                ],
                100.0,
            ),
            create_simple_flag_property_group(
                vec![create_simple_property_filter(
                    "yet_another_key",
                    PropertyType::Person,
                    OperatorType::Exact,
                )],
                100.0,
            ),
        ];

        {
            // Not enough overrides to evaluate locally
            let overrides = HashMap::from([
                ("some_key".to_string(), Value::String("value".to_string())),
                (
                    "another_key".to_string(),
                    Value::String("value".to_string()),
                ),
            ]);

            assert!(any_group_requires_db_properties(Some(&groups), &overrides));
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

            assert!(!any_group_requires_db_properties(Some(&groups), &overrides));
        }
    }
}
