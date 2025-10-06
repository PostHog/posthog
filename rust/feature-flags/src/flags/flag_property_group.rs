use crate::flags::flag_models::FlagPropertyGroup;
use serde_json::Value;
use std::collections::HashMap;

impl FlagPropertyGroup {
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
    #[case(Some(100.0), true)]
    #[case(Some(1.0), true)]
    #[case(Some(0.0), false)]
    #[case(None, true)] // If no rollout percentage is set, we assume it's 100%
    fn test_is_rolled_out_to_some(#[case] rollout_percentage: Option<f64>, #[case] expected: bool) {
        let group = FlagPropertyGroup {
            properties: None,
            rollout_percentage,
            variant: None,
        };
        assert_eq!(group.is_rolled_out_to_some(), expected);
    }

    #[test]
    fn test_does_not_require_db_properties_when_no_properties() {
        let group = FlagPropertyGroup {
            properties: None,
            rollout_percentage: Some(100.0),
            variant: None,
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
        };

        assert!(!group.requires_cohort_filters());
    }
}
