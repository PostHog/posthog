use serde_json::Value;
use std::collections::HashMap;

use crate::cohorts::cohort_models::CohortId;
use crate::flags::flag_models::FeatureFlagId;
use crate::properties::property_models::{PropertyFilter, PropertyType};

impl PropertyFilter {
    /// Checks if the filter is a cohort filter
    pub fn is_cohort(&self) -> bool {
        self.prop_type == PropertyType::Cohort
    }

    /// Returns the cohort id if the filter is a cohort filter, or None if it's not a cohort filter
    /// or if the value cannot be parsed as a cohort id
    pub fn get_cohort_id(&self) -> Option<CohortId> {
        if !self.is_cohort() {
            return None;
        }
        self.value
            .as_ref()
            .and_then(|value| value.as_i64())
            .map(|id| id as CohortId)
    }

    /// Checks if the filter depends on a feature flag
    pub fn depends_on_feature_flag(&self) -> bool {
        self.prop_type == PropertyType::Flag
    }

    /// Returns the feature flag id if the filter depends on a feature flag, or None if it's not a feature flag filter
    /// or if the value cannot be parsed as a feature flag id
    pub fn get_feature_flag_id(&self) -> Option<FeatureFlagId> {
        if !self.depends_on_feature_flag() {
            return None;
        }
        self.key.parse::<FeatureFlagId>().ok()
    }

    /// Returns true if the filter requires DB properties to be evaluated.
    ///
    /// This is true if the filter key is not in the overrides, but only for non cohort and non flag filters
    pub fn requires_db_property(&self, overrides: &HashMap<String, Value>) -> bool {
        !self.is_cohort() && !self.depends_on_feature_flag() && !overrides.contains_key(&self.key)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::test_helpers::create_simple_property_filter;
    use crate::properties::property_models::OperatorType;

    #[test]
    fn test_filter_requires_db_property_if_override_not_present() {
        let filter = create_simple_property_filter(
            "some_property",
            PropertyType::Person,
            OperatorType::Exact,
        );

        {
            // Wrong override.
            let overrides =
                HashMap::from([("not_cohort".to_string(), Value::String("value".to_string()))]);

            assert!(filter.requires_db_property(&overrides));
        }

        {
            // Correct override.
            let overrides = HashMap::from([(
                "some_property".to_string(),
                Value::String("value".to_string()),
            )]);

            assert!(!filter.requires_db_property(&overrides));
        }
    }

    #[test]
    fn test_filter_does_not_require_db_property_if_cohort_or_flag_filter() {
        // Cohort filter.
        let filter =
            create_simple_property_filter("cohort", PropertyType::Cohort, OperatorType::Exact);
        assert!(!filter.requires_db_property(&HashMap::new()));

        // Flag filter.
        let filter = create_simple_property_filter("flag", PropertyType::Flag, OperatorType::Exact);
        assert!(!filter.requires_db_property(&HashMap::new()));
    }

    #[test]
    fn test_is_cohort() {
        let filter =
            create_simple_property_filter("cohort", PropertyType::Cohort, OperatorType::Exact);
        assert!(filter.is_cohort());

        let filter =
            create_simple_property_filter("person", PropertyType::Person, OperatorType::Exact);
        assert!(!filter.is_cohort());
    }

    #[test]
    fn test_get_cohort_id() {
        let mut filter =
            create_simple_property_filter("cohort", PropertyType::Cohort, OperatorType::Exact);
        filter.value = Some(Value::Number(serde_json::Number::from(123)));

        assert_eq!(filter.get_cohort_id(), Some(123));

        // Non-cohort filter should return None
        let filter =
            create_simple_property_filter("person", PropertyType::Person, OperatorType::Exact);
        assert_eq!(filter.get_cohort_id(), None);

        // Cohort filter with non-numeric value should return None
        let mut filter =
            create_simple_property_filter("cohort", PropertyType::Cohort, OperatorType::Exact);
        filter.value = Some(Value::String("not_a_number".to_string()));
        assert_eq!(filter.get_cohort_id(), None);
    }

    #[test]
    fn test_depends_on_feature_flag() {
        let filter = create_simple_property_filter("flag", PropertyType::Flag, OperatorType::Exact);
        assert!(filter.depends_on_feature_flag());

        let filter =
            create_simple_property_filter("person", PropertyType::Person, OperatorType::Exact);
        assert!(!filter.depends_on_feature_flag());
    }

    #[test]
    fn test_get_feature_flag_id() {
        let filter = create_simple_property_filter("123", PropertyType::Flag, OperatorType::Exact);
        assert_eq!(filter.get_feature_flag_id(), Some(123));

        // Non-flag filter should return None
        let filter =
            create_simple_property_filter("person", PropertyType::Person, OperatorType::Exact);
        assert_eq!(filter.get_feature_flag_id(), None);

        // Flag filter with non-numeric key should return None
        let filter =
            create_simple_property_filter("not_a_number", PropertyType::Flag, OperatorType::Exact);
        assert_eq!(filter.get_feature_flag_id(), None);
    }
}
