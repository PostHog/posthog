use std::collections::HashMap;

use crate::properties::property_models::{OperatorType, PropertyFilter};
use crate::properties::relative_date;
use chrono::{DateTime, Utc};
use dateparser::parse as parse_date;
use regex::Regex;
use serde_json::Value;

#[derive(Debug, PartialEq, Eq)]
pub enum FlagMatchingError {
    ValidationError(String),
    MissingProperty(String),
    InconclusiveOperatorMatch,
    InvalidRegexPattern,
}

pub fn to_string_representation(value: &Value) -> String {
    if value.is_string() {
        return value
            .as_str()
            .expect("string slice should always exist for string value")
            .to_string();
    }
    value.to_string()
}

pub fn to_f64_representation(value: &Value) -> Option<f64> {
    if value.is_number() {
        return value.as_f64();
    }
    to_string_representation(value).parse::<f64>().ok()
}

pub fn match_property(
    property: &PropertyFilter,
    matching_property_values: &HashMap<String, Value>,
    partial_props: bool,
) -> Result<bool, FlagMatchingError> {
    // only looks for matches where key exists in override_property_values
    // doesn't support operator is_not_set with partial_props
    if partial_props && !matching_property_values.contains_key(&property.key) {
        tracing::warn!("Missing property for matching: {}", property.key);
        return Err(FlagMatchingError::MissingProperty(format!(
            "can't match properties without a value. Missing property: {}",
            property.key
        )));
    }

    let key = &property.key;
    let operator = property.operator.unwrap_or(OperatorType::Exact);
    let match_value = matching_property_values.get(key);

    // first match operators that don't require a value
    match operator {
        OperatorType::IsSet => return Ok(matching_property_values.contains_key(key)),
        OperatorType::IsNotSet => {
            return if partial_props {
                if matching_property_values.contains_key(key) {
                    Ok(false)
                } else {
                    Err(FlagMatchingError::InconclusiveOperatorMatch)
                }
            } else {
                Ok(!matching_property_values.contains_key(key))
            }
        }
        _ => {}
    }

    // For all other operators, we need a value
    let value = match &property.value {
        Some(v) => v,
        None => return Ok(false), // No value means no match for value-requiring operators
    };

    match operator {
        OperatorType::Exact | OperatorType::IsNot => {
            let compute_exact_match = |value: &Value, override_value: &Value| -> bool {
                if is_truthy_or_falsy_property_value(value) {
                    // Do boolean handling, such that passing in "true" or "True" or "false" or "False" as matching value is equivalent
                    let (truthy_value, truthy_override_value) = (
                        is_truthy_property_value(value),
                        is_truthy_property_value(override_value),
                    );
                    return truthy_override_value.to_string().to_lowercase()
                        == truthy_value.to_string().to_lowercase();
                }

                if value.is_array() {
                    return value
                        .as_array()
                        .expect("expected array value")
                        .iter()
                        .map(|v| to_string_representation(v).to_lowercase())
                        .collect::<Vec<String>>()
                        .contains(&to_string_representation(override_value).to_lowercase());
                }
                to_string_representation(value).to_lowercase()
                    == to_string_representation(override_value).to_lowercase()
            };

            if let Some(match_value) = match_value {
                if operator == OperatorType::Exact {
                    Ok(compute_exact_match(value, match_value))
                } else {
                    Ok(!compute_exact_match(value, match_value))
                }
            } else {
                // When value doesn't exist:
                // - for Exact: it's not a match (false)
                // - for IsNot: it is a match (true)
                Ok(operator == OperatorType::IsNot)
            }
        }
        OperatorType::IsSet => Ok(matching_property_values.contains_key(key)),
        OperatorType::IsNotSet => {
            if partial_props {
                if matching_property_values.contains_key(key) {
                    Ok(false)
                } else {
                    Err(FlagMatchingError::InconclusiveOperatorMatch)
                }
            } else {
                Ok(!matching_property_values.contains_key(key))
            }
        }
        OperatorType::Icontains | OperatorType::NotIcontains => {
            if let Some(match_value) = match_value {
                // Using to_ascii_lowercase() since we only care about ASCII case insensitivity
                // This is more performant than to_lowercase() which handles full Unicode
                let is_contained = to_string_representation(match_value)
                    .to_ascii_lowercase()
                    .contains(&to_string_representation(value).to_ascii_lowercase());

                if operator == OperatorType::Icontains {
                    Ok(is_contained)
                } else {
                    Ok(!is_contained)
                }
            } else {
                // When value doesn't exist:
                // - for Icontains: it's not a match (false)
                // - for NotIcontains: it is a match (true)
                Ok(operator == OperatorType::NotIcontains)
            }
        }
        OperatorType::Regex | OperatorType::NotRegex => {
            if match_value.is_none() {
                // When value doesn't exist:
                // - for Regex: it's not a match (false)
                // - for NotRegex: it is a match (true)
                return Ok(operator == OperatorType::NotRegex);
            }
            let pattern = match Regex::new(&to_string_representation(value)) {
                Ok(pattern) => pattern,
                Err(_) => {
                    return Ok(false);
                }
            };
            let haystack = to_string_representation(match_value.unwrap_or(&Value::Null));
            let match_ = pattern.find(&haystack);

            if operator == OperatorType::Regex {
                Ok(match_.is_some())
            } else {
                Ok(match_.is_none())
            }
        }
        OperatorType::Gt | OperatorType::Gte | OperatorType::Lt | OperatorType::Lte => {
            if match_value.is_none() {
                // When value doesn't exist:
                // - for Gt/Gte/Lt/Lte: it's not a match (false)
                return Ok(false);
            }
            // TODO: Move towards only numeric matching of these operators???

            let compare = |lhs: f64, rhs: f64, operator: OperatorType| -> bool {
                match operator {
                    OperatorType::Gt => lhs > rhs,
                    OperatorType::Gte => lhs >= rhs,
                    OperatorType::Lt => lhs < rhs,
                    OperatorType::Lte => lhs <= rhs,
                    _ => false,
                }
            };

            let parsed_value = match to_f64_representation(
                match_value.unwrap_or(&serde_json::Value::Null),
            ) {
                Some(parsed_value) => parsed_value,
                None => {
                    tracing::debug!(
                        "Failed to parse property value '{}' for key '{}' as number for operator {:?}",
                        match_value.unwrap_or(&serde_json::Value::Null),
                        key,
                        operator
                    );
                    return Err(FlagMatchingError::ValidationError(
                        "value is not a number".to_string(),
                    ));
                }
            };

            if let Some(override_value) = to_f64_representation(value) {
                Ok(compare(parsed_value, override_value, operator))
            } else {
                tracing::debug!(
                    "Failed to parse filter value '{}' for key '{}' as number for operator {:?}",
                    value,
                    key,
                    operator
                );
                Err(FlagMatchingError::ValidationError(
                    "override value is not a number".to_string(),
                ))
            }
        }
        OperatorType::IsDateExact | OperatorType::IsDateAfter | OperatorType::IsDateBefore => {
            let parsed_date = determine_parsed_date_for_property_matching(match_value);

            if parsed_date.is_none() {
                // When value doesn't exist:
                // - for IsDateExact/IsDateAfter/IsDateBefore: it's not a match (false)
                return Ok(false);
            }

            if let Some(override_value) = value.as_str() {
                let override_date = match parse_date_string(override_value) {
                    Some(date) => date,
                    None => {
                        return Ok(false);
                    }
                };

                match operator {
                    OperatorType::IsDateBefore => Ok(parsed_date.unwrap() < override_date),
                    OperatorType::IsDateAfter => Ok(parsed_date.unwrap() > override_date),
                    OperatorType::IsDateExact => Ok(parsed_date.unwrap() == override_date),
                    _ => Ok(false),
                }
            } else {
                Ok(false)
            }
        }
        // NB: In/NotIn operators are only for Cohorts,
        // and should be handled by cohort matching code because
        // by the time we match properties, we've already decomposed the cohort
        // filter into multiple property filters
        OperatorType::In | OperatorType::NotIn => Err(FlagMatchingError::ValidationError(
            "In/NotIn operators should be handled by cohort matching".to_string(),
        )),
        OperatorType::FlagEvaluatesTo => Err(FlagMatchingError::ValidationError(
            "FlagEvaluatesTo operator should be handled by flag dependency matching".to_string(),
        )),
    }
}

fn is_truthy_or_falsy_property_value(value: &Value) -> bool {
    if value.is_boolean() {
        return true;
    }

    if value.is_string() {
        let parsed_value = value
            .as_str()
            .expect("expected string value")
            .to_lowercase();
        return parsed_value == "true" || parsed_value == "false";
    }

    if value.is_array() {
        return value
            .as_array()
            .expect("expected array value")
            .iter()
            .all(is_truthy_or_falsy_property_value);
    }

    false
}

fn is_truthy_property_value(value: &Value) -> bool {
    if value.is_boolean() {
        return value.as_bool().expect("expected boolean value");
    }

    if value.is_string() {
        let parsed_value = value
            .as_str()
            .expect("expected string value")
            .to_lowercase();
        return parsed_value == "true";
    }

    if value.is_array() {
        return value
            .as_array()
            .expect("expected array value")
            .iter()
            .all(is_truthy_property_value);
    }

    false
}

fn parse_date_string(date_str: &str) -> Option<DateTime<Utc>> {
    // Try relative date parsing first
    if let Some(date) = relative_date::parse_relative_date(date_str) {
        return Some(date);
    }
    // Fall back to dateparser for other formats
    parse_date(date_str).ok()
}

fn determine_parsed_date_for_property_matching(value: Option<&Value>) -> Option<DateTime<Utc>> {
    let value = value?;

    if let Some(date_str) = value.as_str() {
        // First try parsing as a float timestamp
        if let Ok(num) = date_str.parse::<f64>() {
            return parse_float_timestamp(num);
        }
        // Then try relative date parsing
        return parse_date_string(date_str);
    }

    if let Some(num) = value.as_number() {
        // Unix timestamps are the number of seconds since epoch (January 1, 1970, at 00:00:00 UTC)
        let seconds_f = num.as_f64()?;
        return parse_float_timestamp(seconds_f);
    }

    None
}

fn parse_float_timestamp(value: f64) -> Option<DateTime<Utc>> {
    let whole_seconds = value.floor() as i64;
    let nanos = ((value % 1.0) * 1_000_000_000.0).round() as u32;
    DateTime::from_timestamp(whole_seconds, nanos)
}

/// Copy of https://github.com/PostHog/posthog/blob/master/posthog/queries/test/test_base.py#L35
/// with some modifications to match Rust's behavior
/// and to test the match_property function
#[cfg(test)]
mod test_match_properties {
    use crate::properties::property_models::PropertyType;

    use super::*;
    use serde_json::json;
    use test_case::test_case;

    #[test]
    fn test_match_properties_exact_with_partial_props() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("value")),
            operator: None,
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(""))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            true
        )
        .is_err());
        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key2".to_string(), json!("value"))]),
                true
            )
            .expect_err("expected match to exist"),
            FlagMatchingError::MissingProperty(
                "can't match properties without a value. Missing property: key".to_string()
            )
        );
        assert!(match_property(&property_a, &HashMap::from([]), true).is_err());

        let property_b = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("value")),
            operator: Some(OperatorType::Exact),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("value"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));

        let property_c = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(["value1", "value2", "value3"])),
            operator: Some(OperatorType::Exact),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value1"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value3"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value4"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_c,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            true
        )
        .is_err());
    }

    #[test]
    fn test_match_properties_is_not() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("value")),
            operator: Some(OperatorType::IsNot),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(""))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        // partial mode returns error when key doesn't exist
        assert!(match_property(
            &property_a,
            &HashMap::from([("key2".to_string(), json!("value1"))]),
            true
        )
        .is_err());

        let property_c = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(["value1", "value2", "value3"])),
            operator: Some(OperatorType::IsNot),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value4"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value5"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value6"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!(""))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value3"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value1"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_c,
            &HashMap::from([("key2".to_string(), json!("value1"))]),
            true
        )
        .is_err());
    }

    #[test]
    fn test_match_properties_is_set() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("value")),
            operator: Some(OperatorType::IsSet),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(""))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key2".to_string(), json!("value1"))]),
            true
        )
        .is_err());

        assert!(match_property(&property_a, &HashMap::from([]), true).is_err());
    }

    #[test]
    fn test_match_properties_icontains() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("valUe")),
            operator: Some(OperatorType::Icontains),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value3"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("vaLue4"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("343tfvalue5"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("Alakazam"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(123))]),
            true
        )
        .expect("expected match to exist"));

        let property_b = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("3")),
            operator: Some(OperatorType::Icontains),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("3"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!(323))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("val3"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("three"))]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_match_properties_regex() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(r"\.com$")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value.com"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("value2.com"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(".com343tfvalue5"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("Alakazam"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(123))]),
            true
        )
        .expect("expected match to exist"));

        let property_b = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("3")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };
        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("3"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!(323))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("val3"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("three"))]),
            true
        )
        .expect("expected match to exist"));

        // invalid regex
        let property_c = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(r"?*")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("value2"))]),
            true
        )
        .expect("expected match to exist"));

        // non string value
        let property_d = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(4)),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };
        assert!(match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!("4"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!(4))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!("value"))]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_match_properties_math_operators() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(1)),
            operator: Some(OperatorType::Gt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(2))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(3))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(0))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(-1))]),
            true
        )
        .expect("expected match to exist"));

        // # we handle type mismatches so this should be true
        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("23"))]),
            true
        )
        .expect("expected match to exist"));

        let property_b = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(1)),
            operator: Some(OperatorType::Lt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!(0))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!(-1))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!(-3))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!(1))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("1"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!("3"))]),
            true
        )
        .expect("expected match to exist"));

        let property_c = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(1)),
            operator: Some(OperatorType::Gte),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!(1))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!(2))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!(0))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!(-1))]),
            true
        )
        .expect("expected match to exist"));
        // # now we handle type mismatches so this should be true
        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("3"))]),
            true
        )
        .expect("expected match to exist"));

        let property_d = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("43")),
            operator: Some(OperatorType::Lt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!("41"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!("42"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!(42))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!("43"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!("44"))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!(44))]),
            true
        )
        .expect("expected match to exist"));

        let property_e = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("30")),
            operator: Some(OperatorType::Lt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_e,
            &HashMap::from([("key".to_string(), json!("29"))]),
            true
        )
        .expect("expected match to exist"));

        // # depending on the type of override, we adjust type comparison
        // This is wonky, do we want to continue this behavior? :/
        // TODO: Come back to this
        // TODO: Fix
        // assert_eq!(
        //     match_property(
        //         &property_e,
        //         &HashMap::from([("key".to_string(), json!("100"))]),
        //         true
        //     )
        //     .expect("expected match to exist"),
        //     true
        // );
        assert!(!match_property(
            &property_e,
            &HashMap::from([("key".to_string(), json!(100))]),
            true
        )
        .expect("expected match to exist"));

        // let property_f = PropertyFilter {
        //     key: "key".to_string(),
        //     value: json!("123aloha"),
        //     operator: Some(OperatorType::Gt),
        //     prop_type: "person".to_string(),
        //     group_type_index: None,
        // };

        // TODO: This test fails because 123aloha is not a number
        // and currently we don't support string comparison..
        // assert_eq!(
        //     match_property(
        //         &property_f,
        //         &HashMap::from([("key".to_string(), json!("123"))]),
        //         true
        //     )
        //     .expect("expected match to exist"),
        //     false
        // );
        // assert_eq!(
        //     match_property(
        //         &property_f,
        //         &HashMap::from([("key".to_string(), json!(122))]),
        //         true
        //     )
        //     .expect("expected match to exist"),
        //     false
        // );

        // # this turns into a string comparison
        // TODO: Fix
        // assert_eq!(
        //     match_property(
        //         &property_f,
        //         &HashMap::from([("key".to_string(), json!(129))]),
        //         true
        //     )
        //     .expect("expected match to exist"),
        //     true
        // );
    }

    #[test]
    fn test_none_property_value_with_all_operators() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("null")),
            operator: Some(OperatorType::IsNot),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(!match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));
        assert!(match_property(
            &property_a,
            &HashMap::from([("key".to_string(), json!("non"))]),
            true
        )
        .expect("expected match to exist"));

        let property_b = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(null)),
            operator: Some(OperatorType::IsSet),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_b,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        let property_c = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("nu")),
            operator: Some(OperatorType::Icontains),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));
        assert!(!match_property(
            &property_c,
            &HashMap::from([("key".to_string(), json!("smh"))]),
            true
        )
        .expect("expected match to exist"));

        let property_d = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("Nu")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(!match_property(
            &property_d,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        let property_d_upper_case = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("Nu")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(!match_property(
            &property_d_upper_case,
            &HashMap::from([("key".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        // TODO: Fails because not a number
        // let property_e = PropertyFilter {
        //     key: "key".to_string(),
        //     value: json!(1),
        //     operator: Some(OperatorType::Gt),
        //     prop_type: "person".to_string(),
        //     group_type_index: None,
        // };

        // assert_eq!(
        //     match_property(&property_e, &HashMap::from([("key".to_string(), json!(null))]), true)
        //         .expect("expected match to exist"),
        //     true
        // );
    }

    #[test]
    fn test_match_properties_all_operators_with_full_props() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("value")),
            operator: None,
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(!match_property(
            &property_a,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            false
        )
        .expect("Expected no errors with full props mode for non-existent keys"));
        assert_eq!(
            match_property(&property_a, &HashMap::from([]), false),
            Ok(false)
        );

        let property_exact = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(["value1", "value2", "value3"])),
            operator: Some(OperatorType::Exact),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(!match_property(
            &property_exact,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_is_set = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("value")),
            operator: Some(OperatorType::IsSet),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(!match_property(
            &property_is_set,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_is_not_set = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(null)),
            operator: Some(OperatorType::IsNotSet),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_is_not_set,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            false
        )
        .expect("Expected no errors with full props mode"));
        assert!(!match_property(
            &property_is_not_set,
            &HashMap::from([("key".to_string(), json!("value"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        // is not set with partial props returns false when key exists
        assert!(!match_property(
            &property_is_not_set,
            &HashMap::from([("key".to_string(), json!("value"))]),
            true
        )
        .expect("Expected no errors with full props mode"));
        // is not set returns error when key doesn't exist
        assert!(match_property(
            &property_is_not_set,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            true
        )
        .is_err());

        let property_icontains = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("valUe")),
            operator: Some(OperatorType::Icontains),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(!match_property(
            &property_icontains,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_not_icontains = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("valUe")),
            operator: Some(OperatorType::NotIcontains),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_not_icontains,
            &HashMap::from([("key2".to_string(), json!("value"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_regex = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(r"\.com$")),
            operator: Some(OperatorType::Regex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(!match_property(
            &property_regex,
            &HashMap::from([("key2".to_string(), json!("value.com"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_not_regex = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(r"\.com$")),
            operator: Some(OperatorType::NotRegex),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_not_regex,
            &HashMap::from([("key2".to_string(), json!("value.com"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_gt = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(1)),
            operator: Some(OperatorType::Gt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(!match_property(
            &property_gt,
            &HashMap::from([("key2".to_string(), json!(2))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_gte = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(1)),
            operator: Some(OperatorType::Gte),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(!match_property(
            &property_gte,
            &HashMap::from([("key2".to_string(), json!(2))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_lt = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(1)),
            operator: Some(OperatorType::Lt),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(!match_property(
            &property_lt,
            &HashMap::from([("key2".to_string(), json!(0))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        let property_lte = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!(1)),
            operator: Some(OperatorType::Lte),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(!match_property(
            &property_lte,
            &HashMap::from([("key2".to_string(), json!(0))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        // TODO: Handle date operators
        let property_is_date_before = PropertyFilter {
            key: "key".to_string(),
            value: Some(json!("2021-01-01")),
            operator: Some(OperatorType::IsDateBefore),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(!match_property(
            &property_is_date_before,
            &HashMap::from([("key2".to_string(), json!("2021-01-02"))]),
            false
        )
        .expect("Expected no errors with full props mode"));

        // Test IsDateAfter with different date formats
        let property_is_date_after = PropertyFilter {
            key: "joined_at".to_string(),
            value: Some(json!("2023-06-04")), // Simple date format in filter
            operator: Some(OperatorType::IsDateAfter),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        // Test with ISO8601 format in person properties
        assert!(match_property(
            &property_is_date_after,
            &HashMap::from([(
                "joined_at".to_string(),
                json!("2025-01-24T23:20:24.865148+00:00")
            )]),
            true
        )
        .expect("expected match to exist"));

        // Test with a date before the filter date (should not match)
        assert!(!match_property(
            &property_is_date_after,
            &HashMap::from([(
                "joined_at".to_string(),
                json!("2023-01-24T23:20:24.865148+00:00")
            )]),
            true
        )
        .expect("expected match to exist"));
    }

    #[test]
    fn test_match_properties_exact_date() {
        let exact_date = "2024-03-21T00:00:00Z"; // Define the exact date we want to test
        let property_exact = PropertyFilter {
            key: "date".to_string(),
            value: Some(json!(exact_date)),
            operator: Some(OperatorType::IsDateExact),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        assert!(match_property(
            &property_exact,
            &HashMap::from([("date".to_string(), json!(exact_date))]),
            true
        )
        .expect("expected match to exist"));

        assert!(!match_property(
            &property_exact,
            &HashMap::from([("date".to_string(), json!("2024-03-22T00:00:00Z"))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_exact,
            &HashMap::from([("date".to_string(), json!(1710979200))]),
            true
        )
        .expect("expected match to exist"));

        assert!(match_property(
            &property_exact,
            &HashMap::from([("date".to_string(), json!("1710979200"))]),
            true
        )
        .expect("expected match to exist"));

        // Test with invalid date format
        assert!(!match_property(
            &property_exact,
            &HashMap::from([("date".to_string(), json!("invalid-date"))]),
            true
        )
        .expect("expected match to exist"));

        // Test with timestamp
        assert!(match_property(
            &property_exact,
            &HashMap::from([("date".to_string(), json!(1710979200.0))]), // 2024-03-21 00:00:00 UTC
            true
        )
        .expect("expected match to exist"));
    }

    #[test_case(json!(1836277747) => true; "numeric timestamp after target date")] // 2028-03-10 05:09:07
    #[test_case(json!("1836277747") => true; "string timestamp after target date")] // 2028-03-10 05:09:07
    #[test_case(json!(1747793088) => false; "numeric timestamp before target date")] // 2025-05-21 02:04:48
    #[test_case(json!("1747793088") => false; "string timestamp before target date")] // 2025-05-21 02:04:48
    fn test_match_properties_date_after_with_timestamp(input_value: Value) -> bool {
        let target_date = "2027-03-21T00:00:00Z";
        let property = PropertyFilter {
            key: "date".to_string(),
            value: Some(json!(target_date)),
            operator: Some(OperatorType::IsDateAfter),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        match_property(
            &property,
            &HashMap::from([("date".to_string(), input_value)]),
            true,
        )
        .expect("expected match to exist")
    }

    #[test]
    fn test_match_properties_relative_date() {
        let property_relative = PropertyFilter {
            key: "joined_at".to_string(),
            value: Some(json!("-3d")),
            operator: Some(OperatorType::IsDateBefore),
            prop_type: PropertyType::Person,
            group_type_index: None,
            negation: None,
        };

        // Get current time and 3 days ago
        let now = chrono::Utc::now();
        let four_days_ago = now - chrono::Duration::days(4);
        let two_days_ago = now - chrono::Duration::days(2);

        // Test with date 4 days ago (should match)
        assert!(match_property(
            &property_relative,
            &HashMap::from([("joined_at".to_string(), json!(four_days_ago.to_rfc3339()))]),
            true
        )
        .expect("expected match to exist"));

        // Test with date 2 days ago (should not match)
        assert!(!match_property(
            &property_relative,
            &HashMap::from([("joined_at".to_string(), json!(two_days_ago.to_rfc3339()))]),
            true
        )
        .expect("expected match to exist"));

        // Test with timestamp format
        assert!(match_property(
            &property_relative,
            &HashMap::from([(
                "joined_at".to_string(),
                json!(four_days_ago.timestamp() as f64)
            )]),
            true
        )
        .expect("expected match to exist"));

        // Test with invalid date
        assert!(!match_property(
            &property_relative,
            &HashMap::from([("joined_at".to_string(), json!("invalid-date"))]),
            true
        )
        .expect("expected match to exist"));

        // Test with null value
        assert!(!match_property(
            &property_relative,
            &HashMap::from([("joined_at".to_string(), json!(null))]),
            true
        )
        .expect("expected match to exist"));

        // Test with missing property
        assert!(match_property(&property_relative, &HashMap::from([]), true).is_err());
    }

    #[test]
    fn test_parse_timestamp_in_seconds_as_date() {
        let expected_date = DateTime::parse_from_rfc3339("2028-03-10T05:09:07Z")
            .unwrap()
            .with_timezone(&Utc);
        let timestamp_number = 1836277747;
        let timestamp_string = timestamp_number.to_string();
        let date = determine_parsed_date_for_property_matching(Some(&json!(timestamp_number)));
        assert_eq!(date, Some(expected_date));
        let date = determine_parsed_date_for_property_matching(Some(&json!(timestamp_string)));
        assert_eq!(date, Some(expected_date));
    }

    #[test]
    fn test_parse_timestamp_with_fractional_milliseconds_as_date() {
        let expected_date = DateTime::parse_from_rfc3339("2028-03-10T05:09:07.867530107Z")
            .unwrap()
            .with_timezone(&Utc);
        let timestamp_number = 1836277747.86753;
        let date = determine_parsed_date_for_property_matching(Some(&json!(timestamp_number)));
        assert_eq!(date, Some(expected_date));

        let timestamp_string = "1836277747.86753";
        let date = determine_parsed_date_for_property_matching(Some(&json!(timestamp_string)));
        assert_eq!(date, Some(expected_date));
    }
}
