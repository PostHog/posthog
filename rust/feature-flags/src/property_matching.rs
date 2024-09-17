use std::collections::HashMap;

use crate::flag_definitions::{OperatorType, PropertyFilter};
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
        return Err(FlagMatchingError::MissingProperty(format!(
            "can't match properties without a value. Missing property: {}",
            property.key
        )));
    }

    let key = &property.key;
    let operator = property.operator.clone().unwrap_or(OperatorType::Exact);
    let value = &property.value;
    let match_value = matching_property_values.get(key);

    match operator {
        OperatorType::Exact | OperatorType::IsNot => {
            let compute_exact_match = |value: &Value, override_value: &Value| -> bool {
                if is_truthy_or_falsy_property_value(value) {
                    // Do boolean handling, such that passing in "true" or "True" or "false" or "False" as matching value is equivalent
                    let truthy = is_truthy_property_value(value);
                    return override_value.to_string().to_lowercase()
                        == truthy.to_string().to_lowercase();
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
                Ok(false)
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
                // TODO: Check eq_ignore_ascii_case and to_ascii_lowercase
                // see https://doc.rust-lang.org/std/string/struct.String.html#method.to_lowercase
                // do we want to lowercase non-ascii stuff?
                let is_contained = to_string_representation(match_value)
                    .to_lowercase()
                    .contains(&to_string_representation(value).to_lowercase());

                if operator == OperatorType::Icontains {
                    Ok(is_contained)
                } else {
                    Ok(!is_contained)
                }
            } else {
                // When value doesn't exist, it's not a match
                Ok(false)
            }
        }
        OperatorType::Regex | OperatorType::NotRegex => {
            if match_value.is_none() {
                return Ok(false);
            }

            let pattern = match Regex::new(&to_string_representation(value)) {
                Ok(pattern) => pattern,
                Err(_) => return Ok(false),
                //TODO: Should we return Err here and handle elsewhere?
                //Err(FlagMatchingError::InvalidRegexPattern)
                // python just returns false here
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

            let parsed_value = match to_f64_representation(match_value.unwrap_or(&Value::Null)) {
                Some(parsed_value) => parsed_value,
                None => {
                    return Err(FlagMatchingError::ValidationError(
                        "value is not a number".to_string(),
                    ))
                }
            };

            if let Some(override_value) = to_f64_representation(value) {
                Ok(compare(parsed_value, override_value, operator))
            } else {
                Err(FlagMatchingError::ValidationError(
                    "override value is not a number".to_string(),
                ))
            }
        }
        OperatorType::IsDateExact | OperatorType::IsDateAfter | OperatorType::IsDateBefore => {
            // TODO: Handle date operators
            Ok(false)
            // let parsed_date = determine_parsed_date_for_property_matching(match_value);

            // if parsed_date.is_none() {
            //     return Ok(false);
            // }

            // if let Some(override_value) = value.as_str() {
            //     let override_date = match parser::parse(override_value) {
            //         Ok(override_date) => override_date,
            //         Err(_) => return Ok(false),
            //     };

            //     match operator {
            //         OperatorType::IsDateBefore => Ok(override_date < parsed_date.unwrap()),
            //         OperatorType::IsDateAfter => Ok(override_date > parsed_date.unwrap()),
            //         _ => Ok(false),
            //     }
            // } else {
            //     Ok(false)
            // }
        }
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

/// Copy of https://github.com/PostHog/posthog/blob/master/posthog/queries/test/test_base.py#L35
/// with some modifications to match Rust's behavior
/// and to test the match_property function
#[cfg(test)]
mod test_match_properties {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_match_properties_exact_with_partial_props() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: json!("value"),
            operator: None,
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("value"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("value2"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );
        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!(""))]),
                true
            )
            .expect("expected match to exist"),
            false
        );
        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!(null))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key2".to_string(), json!("value"))]),
                true
            )
            .is_err(),
            true
        );
        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key2".to_string(), json!("value"))]),
                true
            )
            .err()
            .expect("expected match to exist"),
            FlagMatchingError::MissingProperty(
                "can't match properties without a value. Missing property: key".to_string()
            )
        );
        assert_eq!(
            match_property(&property_a, &HashMap::from([]), true).is_err(),
            true
        );

        let property_b = PropertyFilter {
            key: "key".to_string(),
            value: json!("value"),
            operator: Some(OperatorType::Exact),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!("value"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!("value2"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        let property_c = PropertyFilter {
            key: "key".to_string(),
            value: json!(["value1", "value2", "value3"]),
            operator: Some(OperatorType::Exact),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!("value1"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );
        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!("value2"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );
        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!("value3"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!("value4"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key2".to_string(), json!("value"))]),
                true
            )
            .is_err(),
            true
        );
    }

    #[test]
    fn test_match_properties_is_not() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: json!("value"),
            operator: Some(OperatorType::IsNot),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("value2"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!(""))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!(null))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        // partial mode returns error when key doesn't exist
        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key2".to_string(), json!("value1"))]),
                true
            )
            .is_err(),
            true
        );

        let property_c = PropertyFilter {
            key: "key".to_string(),
            value: json!(["value1", "value2", "value3"]),
            operator: Some(OperatorType::IsNot),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!("value4"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!("value5"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!("value6"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!(""))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!(null))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!("value2"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!("value3"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!("value1"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key2".to_string(), json!("value1"))]),
                true
            )
            .is_err(),
            true
        );
    }

    #[test]
    fn test_match_properties_is_set() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: json!("value"),
            operator: Some(OperatorType::IsSet),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("value"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("value2"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!(""))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!(null))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key2".to_string(), json!("value1"))]),
                true
            )
            .is_err(),
            true
        );

        assert_eq!(
            match_property(&property_a, &HashMap::from([]), true).is_err(),
            true
        );
    }

    #[test]
    fn test_match_properties_icontains() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: json!("valUe"),
            operator: Some(OperatorType::Icontains),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("value"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("value2"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("value3"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("vaLue4"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("343tfvalue5"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("Alakazam"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!(123))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        let property_b = PropertyFilter {
            key: "key".to_string(),
            value: json!("3"),
            operator: Some(OperatorType::Icontains),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!("3"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!(323))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!("val3"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!("three"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );
    }

    #[test]
    fn test_match_properties_regex() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: json!(r"\.com$"),
            operator: Some(OperatorType::Regex),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("value.com"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );
        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("value2.com"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!(".com343tfvalue5"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );
        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("Alakazam"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );
        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!(123))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        let property_b = PropertyFilter {
            key: "key".to_string(),
            value: json!("3"),
            operator: Some(OperatorType::Regex),
            prop_type: "person".to_string(),
            group_type_index: None,
        };
        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!("3"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );
        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!(323))]),
                true
            )
            .expect("expected match to exist"),
            true
        );
        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!("val3"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!("three"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        // invalid regex
        let property_c = PropertyFilter {
            key: "key".to_string(),
            value: json!(r"?*"),
            operator: Some(OperatorType::Regex),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!("value"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );
        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!("value2"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        // non string value
        let property_d = PropertyFilter {
            key: "key".to_string(),
            value: json!(4),
            operator: Some(OperatorType::Regex),
            prop_type: "person".to_string(),
            group_type_index: None,
        };
        assert_eq!(
            match_property(
                &property_d,
                &HashMap::from([("key".to_string(), json!("4"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );
        assert_eq!(
            match_property(
                &property_d,
                &HashMap::from([("key".to_string(), json!(4))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_d,
                &HashMap::from([("key".to_string(), json!("value"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );
    }

    #[test]
    fn test_match_properties_math_operators() {
        let property_a = PropertyFilter {
            key: "key".to_string(),
            value: json!(1),
            operator: Some(OperatorType::Gt),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!(2))]),
                true
            )
            .expect("expected match to exist"),
            true
        );
        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!(3))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!(0))]),
                true
            )
            .expect("expected match to exist"),
            false
        );
        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!(-1))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        // # we handle type mismatches so this should be true
        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("23"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        let property_b = PropertyFilter {
            key: "key".to_string(),
            value: json!(1),
            operator: Some(OperatorType::Lt),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!(0))]),
                true
            )
            .expect("expected match to exist"),
            true
        );
        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!(-1))]),
                true
            )
            .expect("expected match to exist"),
            true
        );
        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!(-3))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!(1))]),
                true
            )
            .expect("expected match to exist"),
            false
        );
        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!("1"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );
        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!("3"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        let property_c = PropertyFilter {
            key: "key".to_string(),
            value: json!(1),
            operator: Some(OperatorType::Gte),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!(1))]),
                true
            )
            .expect("expected match to exist"),
            true
        );
        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!(2))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!(0))]),
                true
            )
            .expect("expected match to exist"),
            false
        );
        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!(-1))]),
                true
            )
            .expect("expected match to exist"),
            false
        );
        // # now we handle type mismatches so this should be true
        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!("3"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        let property_d = PropertyFilter {
            key: "key".to_string(),
            value: json!("43"),
            operator: Some(OperatorType::Lt),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_d,
                &HashMap::from([("key".to_string(), json!("41"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );
        assert_eq!(
            match_property(
                &property_d,
                &HashMap::from([("key".to_string(), json!("42"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );
        assert_eq!(
            match_property(
                &property_d,
                &HashMap::from([("key".to_string(), json!(42))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        assert_eq!(
            match_property(
                &property_d,
                &HashMap::from([("key".to_string(), json!("43"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );
        assert_eq!(
            match_property(
                &property_d,
                &HashMap::from([("key".to_string(), json!("44"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );
        assert_eq!(
            match_property(
                &property_d,
                &HashMap::from([("key".to_string(), json!(44))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        let property_e = PropertyFilter {
            key: "key".to_string(),
            value: json!("30"),
            operator: Some(OperatorType::Lt),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_e,
                &HashMap::from([("key".to_string(), json!("29"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        // # depending on the type of override, we adjust type comparison
        // This is wonky, do we want to continue this behavior? :/
        // TODO: Come back to this
        // assert_eq!(
        //     match_property(
        //         &property_e,
        //         &HashMap::from([("key".to_string(), json!("100"))]),
        //         true
        //     )
        //     .expect("expected match to exist"),
        //     true
        // );
        assert_eq!(
            match_property(
                &property_e,
                &HashMap::from([("key".to_string(), json!(100))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

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
            value: json!("null"),
            operator: Some(OperatorType::IsNot),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!(null))]),
                true
            )
            .expect("expected match to exist"),
            false
        );
        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key".to_string(), json!("non"))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        let property_b = PropertyFilter {
            key: "key".to_string(),
            value: json!(null),
            operator: Some(OperatorType::IsSet),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_b,
                &HashMap::from([("key".to_string(), json!(null))]),
                true
            )
            .expect("expected match to exist"),
            true
        );

        let property_c = PropertyFilter {
            key: "key".to_string(),
            value: json!("nu"),
            operator: Some(OperatorType::Icontains),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!(null))]),
                true
            )
            .expect("expected match to exist"),
            true
        );
        assert_eq!(
            match_property(
                &property_c,
                &HashMap::from([("key".to_string(), json!("smh"))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        let property_d = PropertyFilter {
            key: "key".to_string(),
            value: json!("Nu"),
            operator: Some(OperatorType::Regex),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_d,
                &HashMap::from([("key".to_string(), json!(null))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

        let property_d_upper_case = PropertyFilter {
            key: "key".to_string(),
            value: json!("Nu"),
            operator: Some(OperatorType::Regex),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_d_upper_case,
                &HashMap::from([("key".to_string(), json!(null))]),
                true
            )
            .expect("expected match to exist"),
            false
        );

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
            value: json!("value"),
            operator: None,
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_a,
                &HashMap::from([("key2".to_string(), json!("value"))]),
                false
            )
            .expect("Expected no errors with full props mode for non-existent keys"),
            false
        );
        assert_eq!(
            match_property(&property_a, &HashMap::from([]), false),
            Ok(false)
        );

        let property_exact = PropertyFilter {
            key: "key".to_string(),
            value: json!(["value1", "value2", "value3"]),
            operator: Some(OperatorType::Exact),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_exact,
                &HashMap::from([("key2".to_string(), json!("value"))]),
                false
            )
            .expect("Expected no errors with full props mode"),
            false
        );

        let property_is_set = PropertyFilter {
            key: "key".to_string(),
            value: json!("value"),
            operator: Some(OperatorType::IsSet),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_is_set,
                &HashMap::from([("key2".to_string(), json!("value"))]),
                false
            )
            .expect("Expected no errors with full props mode"),
            false
        );

        let property_is_not_set = PropertyFilter {
            key: "key".to_string(),
            value: json!(null),
            operator: Some(OperatorType::IsNotSet),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_is_not_set,
                &HashMap::from([("key2".to_string(), json!("value"))]),
                false
            )
            .expect("Expected no errors with full props mode"),
            true
        );
        assert_eq!(
            match_property(
                &property_is_not_set,
                &HashMap::from([("key".to_string(), json!("value"))]),
                false
            )
            .expect("Expected no errors with full props mode"),
            false
        );

        // is not set with partial props returns false when key exists
        assert_eq!(
            match_property(
                &property_is_not_set,
                &HashMap::from([("key".to_string(), json!("value"))]),
                true
            )
            .expect("Expected no errors with full props mode"),
            false
        );
        // is not set returns error when key doesn't exist
        assert_eq!(
            match_property(
                &property_is_not_set,
                &HashMap::from([("key2".to_string(), json!("value"))]),
                true
            )
            .is_err(),
            true
        );

        let property_icontains = PropertyFilter {
            key: "key".to_string(),
            value: json!("valUe"),
            operator: Some(OperatorType::Icontains),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_icontains,
                &HashMap::from([("key2".to_string(), json!("value"))]),
                false
            )
            .expect("Expected no errors with full props mode"),
            false
        );

        let property_not_icontains = PropertyFilter {
            key: "key".to_string(),
            value: json!("valUe"),
            operator: Some(OperatorType::NotIcontains),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_not_icontains,
                &HashMap::from([("key2".to_string(), json!("value"))]),
                false
            )
            .expect("Expected no errors with full props mode"),
            false
        );

        let property_regex = PropertyFilter {
            key: "key".to_string(),
            value: json!(r"\.com$"),
            operator: Some(OperatorType::Regex),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_regex,
                &HashMap::from([("key2".to_string(), json!("value.com"))]),
                false
            )
            .expect("Expected no errors with full props mode"),
            false
        );

        let property_not_regex = PropertyFilter {
            key: "key".to_string(),
            value: json!(r"\.com$"),
            operator: Some(OperatorType::NotRegex),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_not_regex,
                &HashMap::from([("key2".to_string(), json!("value.com"))]),
                false
            )
            .expect("Expected no errors with full props mode"),
            false
        );

        let property_gt = PropertyFilter {
            key: "key".to_string(),
            value: json!(1),
            operator: Some(OperatorType::Gt),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_gt,
                &HashMap::from([("key2".to_string(), json!(2))]),
                false
            )
            .expect("Expected no errors with full props mode"),
            false
        );

        let property_gte = PropertyFilter {
            key: "key".to_string(),
            value: json!(1),
            operator: Some(OperatorType::Gte),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_gte,
                &HashMap::from([("key2".to_string(), json!(2))]),
                false
            )
            .expect("Expected no errors with full props mode"),
            false
        );

        let property_lt = PropertyFilter {
            key: "key".to_string(),
            value: json!(1),
            operator: Some(OperatorType::Lt),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_lt,
                &HashMap::from([("key2".to_string(), json!(0))]),
                false
            )
            .expect("Expected no errors with full props mode"),
            false
        );

        let property_lte = PropertyFilter {
            key: "key".to_string(),
            value: json!(1),
            operator: Some(OperatorType::Lte),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_lte,
                &HashMap::from([("key2".to_string(), json!(0))]),
                false
            )
            .expect("Expected no errors with full props mode"),
            false
        );

        // TODO: Handle date operators
        let property_is_date_before = PropertyFilter {
            key: "key".to_string(),
            value: json!("2021-01-01"),
            operator: Some(OperatorType::IsDateBefore),
            prop_type: "person".to_string(),
            group_type_index: None,
        };

        assert_eq!(
            match_property(
                &property_is_date_before,
                &HashMap::from([("key2".to_string(), json!("2021-01-02"))]),
                false
            )
            .expect("Expected no errors with full props mode"),
            false
        );
    }
}
