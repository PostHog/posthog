use crate::flags::flag_models::FlagPropertyGroup;
use serde_json::Value;
use std::collections::HashMap;

impl FlagPropertyGroup {
    /// Resolves the effective aggregation group type index for this condition,
    /// falling back to the flag-level value for backwards compatibility with
    /// flags that haven't been re-saved through the new API.
    ///
    /// The double option on the field distinguishes three states:
    /// - `None` — field absent (legacy), falls back to `flag_level`
    /// - `Some(None)` — explicit person aggregation (JSON `null`)
    /// - `Some(Some(idx))` — explicit group aggregation
    pub fn effective_aggregation(&self, flag_level: Option<i32>) -> Option<i32> {
        match self.aggregation_group_type_index {
            Some(inner) => inner,
            None => flag_level,
        }
    }

    /// Returns true if the group is rolled out to some percentage greater than 0.0
    pub fn is_rolled_out_to_some(&self) -> bool {
        self.rollout_percentage_unwrapped() > 0.0
    }

    /// Gets and unwraps the rollout percentage, defaulting to 100.0 if not set.
    pub fn rollout_percentage_unwrapped(&self) -> f64 {
        self.rollout_percentage.unwrap_or(100.0)
    }

    /// Returns true if the overrides are not enough to evaluate the group locally.
    ///
    /// This is true if the group is rolled out to some percentage greater than 0.0
    /// and all the properties in the group require DB properties to be evaluated.
    pub fn requires_db_properties(&self, overrides: &HashMap<String, Value>) -> bool {
        self.is_rolled_out_to_some()
            && self.properties.as_ref().is_some_and(|properties| {
                properties
                    .iter()
                    .any(|prop| prop.requires_db_property(overrides))
            })
    }

    /// Returns true if the group has any cohort filters.
    pub fn has_cohort_filters(&self) -> bool {
        self.properties
            .as_ref()
            .is_some_and(|properties| properties.iter().any(|prop| prop.is_cohort()))
    }

    /// Returns true if the group is rolled out to some percentage greater than 0.0 and has a cohort filter.
    pub fn requires_cohort_filters(&self) -> bool {
        self.is_rolled_out_to_some() && self.has_cohort_filters()
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use crate::{
        flags::test_helpers::create_simple_property_filter,
        properties::property_models::{OperatorType, PropertyType},
    };

    use super::*;
    use rstest::rstest;
    use serde_json::Value;

    #[rstest]
    // Field absent (legacy) with flag-level group → falls back to flag-level
    #[case(None, Some(1), Some(1))]
    // Field absent (legacy) with flag-level person → falls back to person
    #[case(None, None, None)]
    // Explicit person (JSON null) with flag-level group → person wins
    #[case(Some(None), Some(1), None)]
    // Explicit group with flag-level person → group wins
    #[case(Some(Some(2)), None, Some(2))]
    // Explicit group with flag-level group → condition wins
    #[case(Some(Some(2)), Some(1), Some(2))]
    fn test_effective_aggregation(
        #[case] condition_level: Option<Option<i32>>,
        #[case] flag_level: Option<i32>,
        #[case] expected: Option<i32>,
    ) {
        let group = FlagPropertyGroup {
            properties: None,
            rollout_percentage: None,
            variant: None,
            aggregation_group_type_index: condition_level,
        };
        assert_eq!(group.effective_aggregation(flag_level), expected);
    }

    #[rstest]
    #[case(Some(100.0), true)]
    #[case(Some(1.0), true)]
    #[case(Some(0.0), false)]
    #[case(None, true)] // If no rollout percentage is set, we assume it's 100%
    fn test_is_rolled_out_to_some(#[case] rollout_percentage: Option<f64>, #[case] expected: bool) {
        let group = FlagPropertyGroup {
            properties: None,
            rollout_percentage,
            variant: None,
            ..Default::default()
        };
        assert_eq!(group.is_rolled_out_to_some(), expected);
    }

    #[test]
    fn test_does_not_require_db_properties_when_no_properties() {
        let group = FlagPropertyGroup {
            properties: None,
            rollout_percentage: Some(100.0),
            variant: None,
            ..Default::default()
        };
        assert!(!group.requires_db_properties(&HashMap::new()));
    }

    #[test]
    fn test_requires_db_properties_when_overrides_for_every_condition_not_present() {
        let group = FlagPropertyGroup {
            properties: Some(vec![
                create_simple_property_filter("key", PropertyType::Person, OperatorType::Exact),
                create_simple_property_filter(
                    "another_key",
                    PropertyType::Person,
                    OperatorType::Exact,
                ),
            ]),
            rollout_percentage: Some(100.0),
            variant: None,
            ..Default::default()
        };

        {
            // Not enough overrides to evaluate locally
            let overrides = HashMap::from([(
                "another_key".to_string(),
                Value::String("another_value".to_string()),
            )]);
            assert!(group.requires_db_properties(&overrides));
        }

        {
            // Enough overrides to evaluate locally
            let overrides = HashMap::from([
                ("key".to_string(), Value::String("value".to_string())),
                (
                    "another_key".to_string(),
                    Value::String("another_value".to_string()),
                ),
            ]);
            assert!(!group.requires_db_properties(&overrides));
        }
    }

    #[test]
    fn test_does_not_require_db_properties_when_not_rolled_out() {
        let group = FlagPropertyGroup {
            properties: Some(vec![
                create_simple_property_filter("key", PropertyType::Person, OperatorType::Exact),
                create_simple_property_filter(
                    "another_key",
                    PropertyType::Person,
                    OperatorType::Exact,
                ),
            ]),
            rollout_percentage: Some(0.0),
            variant: None,
            ..Default::default()
        };

        assert!(!group.requires_db_properties(&HashMap::new()));
    }

    #[test]
    fn test_has_cohort_filters_when_cohort_filter_present() {
        let group = FlagPropertyGroup {
            properties: Some(vec![create_simple_property_filter(
                "cohort",
                PropertyType::Cohort,
                OperatorType::Exact,
            )]),
            rollout_percentage: Some(100.0),
            variant: None,
            ..Default::default()
        };

        assert!(group.has_cohort_filters());
    }

    #[test]
    fn test_does_not_have_cohort_filters_when_no_cohort_filter_present() {
        let group = FlagPropertyGroup {
            properties: Some(vec![create_simple_property_filter(
                "key",
                PropertyType::Person,
                OperatorType::Exact,
            )]),
            rollout_percentage: Some(100.0),
            variant: None,
            ..Default::default()
        };

        assert!(!group.has_cohort_filters());
    }

    #[test]
    fn test_requires_cohort_filters_when_rolled_out_and_cohort_filter_present() {
        let group = FlagPropertyGroup {
            properties: Some(vec![create_simple_property_filter(
                "cohort",
                PropertyType::Cohort,
                OperatorType::Exact,
            )]),
            rollout_percentage: Some(100.0),
            variant: None,
            ..Default::default()
        };

        assert!(group.requires_cohort_filters());
    }

    #[test]
    fn test_does_not_require_cohort_filters_when_not_rolled_out() {
        let group = FlagPropertyGroup {
            properties: Some(vec![create_simple_property_filter(
                "cohort",
                PropertyType::Cohort,
                OperatorType::Exact,
            )]),
            rollout_percentage: Some(0.0),
            variant: None,
            ..Default::default()
        };

        assert!(!group.requires_cohort_filters());
    }

    #[test]
    fn test_serde_double_option_field_absent() {
        let json = r#"{"properties": [], "rollout_percentage": 100.0}"#;
        let group: FlagPropertyGroup = serde_json::from_str(json).unwrap();
        assert_eq!(group.aggregation_group_type_index, None);
    }

    #[test]
    fn test_serde_double_option_field_null() {
        let json = r#"{"properties": [], "rollout_percentage": 100.0, "aggregation_group_type_index": null}"#;
        let group: FlagPropertyGroup = serde_json::from_str(json).unwrap();
        assert_eq!(group.aggregation_group_type_index, Some(None));
    }

    #[test]
    fn test_serde_double_option_field_value() {
        let json =
            r#"{"properties": [], "rollout_percentage": 100.0, "aggregation_group_type_index": 1}"#;
        let group: FlagPropertyGroup = serde_json::from_str(json).unwrap();
        assert_eq!(group.aggregation_group_type_index, Some(Some(1)));
    }
}
