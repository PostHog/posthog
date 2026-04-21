use fancy_regex::RegexBuilder;
use serde_json::Value;
use std::collections::HashMap;

use crate::cohorts::cohort_models::CohortId;
use crate::flags::flag_models::FeatureFlagId;
use crate::properties::property_matching::{to_string_representation, REGEX_BACKTRACK_LIMIT};
use crate::properties::property_models::{
    CompiledRegex, OperatorType, PropertyFilter, PropertyType,
};

impl PropertyFilter {
    /// Checks if the filter is a cohort filter
    pub fn is_cohort(&self) -> bool {
        self.prop_type == PropertyType::Cohort
    }

    /// Returns the cohort id if the filter is a cohort filter, or None if it's not a cohort filter
    /// or if the value cannot be parsed as a cohort id.
    /// Handles both JSON number and string representations (Python serializes both).
    pub fn get_cohort_id(&self) -> Option<CohortId> {
        if !self.is_cohort() {
            return None;
        }
        self.value.as_ref().and_then(|value| match value {
            Value::Number(n) => n.as_i64().and_then(|id| CohortId::try_from(id).ok()),
            Value::String(s) => s.parse::<CohortId>().ok(),
            _ => None,
        })
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

    /// Pre-compiles the regex pattern for Regex/NotRegex operators.
    /// - Non-regex operators: no-op (compiled_regex stays None)
    /// - Valid pattern: stores `CompiledRegex::Compiled`
    /// - Invalid pattern: stores `CompiledRegex::InvalidPattern`
    pub fn prepare_regex(&mut self) {
        if self.compiled_regex.is_some() {
            return;
        }
        let operator = self.operator.unwrap_or(OperatorType::Exact);
        if !matches!(operator, OperatorType::Regex | OperatorType::NotRegex) {
            return;
        }
        let pattern_str = match &self.value {
            Some(v) => to_string_representation(v),
            None => return,
        };
        self.compiled_regex = Some(
            match RegexBuilder::new(&pattern_str)
                .backtrack_limit(REGEX_BACKTRACK_LIMIT)
                .build()
            {
                Ok(re) => CompiledRegex::Compiled(re),
                Err(_) => CompiledRegex::InvalidPattern,
            },
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mock;
    use crate::properties::property_models::OperatorType;
    use crate::utils::mock::MockInto;

    #[test]
    fn test_filter_requires_db_property_if_override_not_present() {
        let filter = mock!(crate::properties::property_models::PropertyFilter, key: "some_property".mock_into(), prop_type: PropertyType::Person, operator: Some(OperatorType::Exact));

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
        let filter = mock!(crate::properties::property_models::PropertyFilter, key: "cohort".mock_into(), prop_type: PropertyType::Cohort, operator: Some(OperatorType::Exact));
        assert!(!filter.requires_db_property(&HashMap::new()));

        // Flag filter.
        let filter = mock!(crate::properties::property_models::PropertyFilter, key: "flag".mock_into(), prop_type: PropertyType::Flag, operator: Some(OperatorType::Exact));
        assert!(!filter.requires_db_property(&HashMap::new()));
    }

    #[test]
    fn test_is_cohort() {
        let filter = mock!(crate::properties::property_models::PropertyFilter, key: "cohort".mock_into(), prop_type: PropertyType::Cohort, operator: Some(OperatorType::Exact));
        assert!(filter.is_cohort());

        let filter = mock!(crate::properties::property_models::PropertyFilter, key: "person".mock_into(), prop_type: PropertyType::Person, operator: Some(OperatorType::Exact));
        assert!(!filter.is_cohort());
    }

    #[test]
    fn test_get_cohort_id() {
        let mut filter = mock!(crate::properties::property_models::PropertyFilter, key: "cohort".mock_into(), prop_type: PropertyType::Cohort, operator: Some(OperatorType::Exact));
        filter.value = Some(Value::Number(serde_json::Number::from(123)));

        assert_eq!(filter.get_cohort_id(), Some(123));

        // Non-cohort filter should return None
        let filter = mock!(crate::properties::property_models::PropertyFilter, key: "person".mock_into(), prop_type: PropertyType::Person, operator: Some(OperatorType::Exact));
        assert_eq!(filter.get_cohort_id(), None);

        // Cohort filter with string-encoded numeric value should return the id
        let mut filter = mock!(crate::properties::property_models::PropertyFilter, key: "cohort".mock_into(), prop_type: PropertyType::Cohort, operator: Some(OperatorType::Exact));
        filter.value = Some(Value::String("123".to_string()));
        assert_eq!(filter.get_cohort_id(), Some(123));

        // Cohort filter with non-numeric value should return None
        let mut filter = mock!(crate::properties::property_models::PropertyFilter, key: "cohort".mock_into(), prop_type: PropertyType::Cohort, operator: Some(OperatorType::Exact));
        filter.value = Some(Value::String("not_a_number".to_string()));
        assert_eq!(filter.get_cohort_id(), None);
    }

    #[test]
    fn test_depends_on_feature_flag() {
        let filter = mock!(crate::properties::property_models::PropertyFilter, key: "flag".mock_into(), prop_type: PropertyType::Flag, operator: Some(OperatorType::Exact));
        assert!(filter.depends_on_feature_flag());

        let filter = mock!(crate::properties::property_models::PropertyFilter, key: "person".mock_into(), prop_type: PropertyType::Person, operator: Some(OperatorType::Exact));
        assert!(!filter.depends_on_feature_flag());
    }

    #[test]
    fn test_get_feature_flag_id() {
        let filter = mock!(crate::properties::property_models::PropertyFilter, key: "123".mock_into(), prop_type: PropertyType::Flag, operator: Some(OperatorType::Exact));
        assert_eq!(filter.get_feature_flag_id(), Some(123));

        // Non-flag filter should return None
        let filter = mock!(crate::properties::property_models::PropertyFilter, key: "person".mock_into(), prop_type: PropertyType::Person, operator: Some(OperatorType::Exact));
        assert_eq!(filter.get_feature_flag_id(), None);

        // Flag filter with non-numeric key should return None
        let filter = mock!(crate::properties::property_models::PropertyFilter, key: "not_a_number".mock_into(), prop_type: PropertyType::Flag, operator: Some(OperatorType::Exact));
        assert_eq!(filter.get_feature_flag_id(), None);
    }

    #[test]
    fn test_prepare_regex_compiles_valid_pattern() {
        let mut filter = PropertyFilter {
            key: "email".to_string(),
            value: Some(serde_json::json!(r"^user@.*\.com$")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
        };

        assert!(filter.compiled_regex.is_none());
        filter.prepare_regex();
        assert!(matches!(
            filter.compiled_regex,
            Some(CompiledRegex::Compiled(_))
        ));
    }

    #[test]
    fn test_prepare_regex_stores_invalid_for_bad_pattern() {
        let mut filter = PropertyFilter {
            key: "key".to_string(),
            value: Some(serde_json::json!("?*")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
        };

        filter.prepare_regex();
        assert!(matches!(
            filter.compiled_regex,
            Some(CompiledRegex::InvalidPattern)
        ));
    }

    #[test]
    fn test_prepare_regex_noop_for_non_regex_operator() {
        let mut filter = PropertyFilter {
            key: "key".to_string(),
            value: Some(serde_json::json!("value")),
            operator: Some(OperatorType::Exact),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
        };

        filter.prepare_regex();
        assert!(filter.compiled_regex.is_none());
    }

    #[test]
    fn test_invalid_pattern_returns_false_for_both_regex_and_not_regex() {
        use crate::properties::property_matching::match_property;

        let props = HashMap::from([("email".to_string(), serde_json::json!("user@example.com"))]);

        let mut regex_filter = PropertyFilter {
            key: "email".to_string(),
            value: Some(serde_json::json!("?*")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
        };
        regex_filter.prepare_regex();
        assert!(matches!(
            regex_filter.compiled_regex,
            Some(CompiledRegex::InvalidPattern)
        ));
        assert_eq!(match_property(&regex_filter, &props, false), Ok(false));

        let mut not_regex_filter = PropertyFilter {
            key: "email".to_string(),
            value: Some(serde_json::json!("?*")),
            operator: Some(OperatorType::NotRegex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
        };
        not_regex_filter.prepare_regex();
        assert!(matches!(
            not_regex_filter.compiled_regex,
            Some(CompiledRegex::InvalidPattern)
        ));
        // InvalidPattern returns Ok(false) for NotRegex too — matches existing
        // on-the-fly behavior where a failed compilation returns Ok(false)
        // regardless of operator.
        assert_eq!(match_property(&not_regex_filter, &props, false), Ok(false));
    }

    #[test]
    fn test_prepare_regex_noop_when_value_is_none() {
        let mut filter = PropertyFilter {
            key: "email".to_string(),
            value: None,
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
        };

        filter.prepare_regex();
        // None value means no pattern to compile — compiled_regex stays None,
        // which falls through to the on-the-fly path in match_property().
        assert!(filter.compiled_regex.is_none());
    }

    #[test]
    fn test_prepare_regex_is_idempotent() {
        let mut filter = PropertyFilter {
            key: "email".to_string(),
            value: Some(serde_json::json!(r"^user@.*\.com$")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
        };

        filter.prepare_regex();
        assert!(matches!(
            filter.compiled_regex,
            Some(CompiledRegex::Compiled(_))
        ));

        // Second call should be a no-op (early return on is_some())
        filter.prepare_regex();
        assert!(matches!(
            filter.compiled_regex,
            Some(CompiledRegex::Compiled(_))
        ));
    }

    use test_case::test_case;

    #[test_case(OperatorType::Regex, r"^user@.*\.com$", "user@example.com", Ok(true); "regex match")]
    #[test_case(OperatorType::Regex, r"^admin@", "user@example.com", Ok(false); "regex no match")]
    #[test_case(OperatorType::NotRegex, r"^admin@", "user@example.com", Ok(true); "not_regex match")]
    #[test_case(OperatorType::NotRegex, r"^user@.*\.com$", "user@example.com", Ok(false); "not_regex no match")]
    #[test_case(OperatorType::Regex, r"(a+)+$", "aaaaaaaaaaaaaaaaaaaaaaab", Ok(false); "backtrack-heavy regex")]
    fn test_precompiled_matches_same_as_on_the_fly(
        operator: OperatorType,
        pattern: &str,
        property_value: &str,
        expected: Result<bool, crate::properties::property_matching::FlagMatchingError>,
    ) {
        use crate::properties::property_matching::match_property;

        let props = HashMap::from([("key".to_string(), serde_json::json!(property_value))]);

        let filter_raw = PropertyFilter {
            key: "key".to_string(),
            value: Some(serde_json::json!(pattern)),
            operator: Some(operator),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
            compiled_regex: None,
        };
        let result_raw = match_property(&filter_raw, &props, false);

        let mut filter_compiled = filter_raw.clone();
        filter_compiled.prepare_regex();
        let result_compiled = match_property(&filter_compiled, &props, false);

        assert_eq!(result_raw, result_compiled);
        assert_eq!(result_compiled, expected);
    }
}
