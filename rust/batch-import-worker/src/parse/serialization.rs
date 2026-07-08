use serde::{de, Deserialize, Deserializer};
use std::fmt;

/// Deserialize a value of type `T: Default + Deserialize`, treating JSON
/// `null` as `T::default()`.
///
/// Use this on fields where the upstream source emits `null` (rather than
/// omitting the field) when a value is absent — Amplitude exports, for
/// example, include every column on every row and emit `null` for absent
/// object-typed fields like `plan`, `event_properties`, `user_properties`,
/// `group_properties`, `groups`. Bare `#[serde(default)]` only fires when
/// the field is **missing**; if the field is present-and-`null`, serde
/// tries to deserialize `null` into the target type and fails for
/// `HashMap`, structs, and other non-Option types.
///
/// Pair with `#[serde(default, deserialize_with = "deserialize_null_as_default")]`
/// so both shapes — missing **and** explicit-`null` — produce `T::default()`,
/// while real values deserialize normally.
pub fn deserialize_null_as_default<'de, D, T>(deserializer: D) -> Result<T, D::Error>
where
    D: Deserializer<'de>,
    T: Default + Deserialize<'de>,
{
    Ok(Option::<T>::deserialize(deserializer)?.unwrap_or_default())
}

fn parse_bool_from_str<E: de::Error>(value: &str, empty_as_false: bool) -> Result<bool, E> {
    if value.is_empty() {
        return if empty_as_false {
            Ok(false)
        } else {
            Err(de::Error::invalid_value(
                de::Unexpected::Str(value),
                &"non-empty boolean string",
            ))
        };
    }
    match value.to_lowercase().as_str() {
        "true" | "1" | "yes" => Ok(true),
        "false" | "0" | "no" => Ok(false),
        _ => Err(de::Error::invalid_value(
            de::Unexpected::Str(value),
            &"'true', 'false', '1', '0', 'yes', or 'no'",
        )),
    }
}

fn parse_bool_from_i64<E: de::Error>(value: i64) -> Result<bool, E> {
    match value {
        0 => Ok(false),
        1 => Ok(true),
        _ => Err(de::Error::invalid_value(
            de::Unexpected::Signed(value),
            &"0 or 1",
        )),
    }
}

fn parse_bool_from_u64<E: de::Error>(value: u64) -> Result<bool, E> {
    match value {
        0 => Ok(false),
        1 => Ok(true),
        _ => Err(de::Error::invalid_value(
            de::Unexpected::Unsigned(value),
            &"0 or 1",
        )),
    }
}

/// Custom deserializer for boolean values that can also accept string booleans.
/// This is useful when dealing with external data sources that may serialize
/// booleans as strings.
///
/// Accepts:
/// - Actual booleans: true, false
/// - String representations: "true", "false", "1", "0", "yes", "no", "" (empty string = false)
/// - Integer representations: 1 (true), 0 (false) only
pub fn deserialize_flexible_bool<'de, D>(deserializer: D) -> Result<bool, D::Error>
where
    D: Deserializer<'de>,
{
    struct FlexibleBoolVisitor;

    impl<'de> de::Visitor<'de> for FlexibleBoolVisitor {
        type Value = bool;

        fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
            formatter.write_str("a boolean, 0, 1, or a string representing a boolean")
        }

        fn visit_bool<E>(self, value: bool) -> Result<Self::Value, E>
        where
            E: de::Error,
        {
            Ok(value)
        }

        fn visit_str<E>(self, value: &str) -> Result<Self::Value, E>
        where
            E: de::Error,
        {
            parse_bool_from_str(value, true)
        }

        fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E>
        where
            E: de::Error,
        {
            parse_bool_from_i64(value)
        }

        fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E>
        where
            E: de::Error,
        {
            parse_bool_from_u64(value)
        }
    }

    deserializer.deserialize_any(FlexibleBoolVisitor)
}

/// Custom deserializer for optional boolean values that can also accept string booleans.
/// Handles null, missing values, and empty strings as None.
pub fn deserialize_flexible_option_bool<'de, D>(deserializer: D) -> Result<Option<bool>, D::Error>
where
    D: Deserializer<'de>,
{
    struct FlexibleOptionBoolVisitor;

    impl<'de> de::Visitor<'de> for FlexibleOptionBoolVisitor {
        type Value = Option<bool>;

        fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
            formatter.write_str("a boolean, 0, 1, string representing a boolean, or null")
        }

        fn visit_none<E>(self) -> Result<Self::Value, E>
        where
            E: de::Error,
        {
            Ok(None)
        }

        fn visit_unit<E>(self) -> Result<Self::Value, E>
        where
            E: de::Error,
        {
            Ok(None)
        }

        fn visit_str<E>(self, value: &str) -> Result<Self::Value, E>
        where
            E: de::Error,
        {
            if value.is_empty() {
                return Ok(None);
            }
            parse_bool_from_str(value, false).map(Some)
        }

        fn visit_bool<E>(self, value: bool) -> Result<Self::Value, E>
        where
            E: de::Error,
        {
            Ok(Some(value))
        }

        fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E>
        where
            E: de::Error,
        {
            parse_bool_from_i64(value).map(Some)
        }

        fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E>
        where
            E: de::Error,
        {
            parse_bool_from_u64(value).map(Some)
        }
    }

    deserializer.deserialize_any(FlexibleOptionBoolVisitor)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;

    #[derive(Deserialize, Debug, PartialEq)]
    struct TestStruct {
        #[serde(deserialize_with = "deserialize_flexible_bool")]
        flag: bool,
    }

    #[test]
    fn test_deserialize_actual_bool() {
        let json = r#"{"flag": true}"#;
        let result: TestStruct = serde_json::from_str(json).unwrap();
        assert!(result.flag);

        let json = r#"{"flag": false}"#;
        let result: TestStruct = serde_json::from_str(json).unwrap();
        assert!(!result.flag);
    }

    #[test]
    fn test_deserialize_string_bool() {
        let json = r#"{"flag": "true"}"#;
        let result: TestStruct = serde_json::from_str(json).unwrap();
        assert!(result.flag);

        let json = r#"{"flag": "false"}"#;
        let result: TestStruct = serde_json::from_str(json).unwrap();
        assert!(!result.flag);
    }

    #[test]
    fn test_deserialize_string_bool_case_insensitive() {
        let json = r#"{"flag": "TRUE"}"#;
        let result: TestStruct = serde_json::from_str(json).unwrap();
        assert!(result.flag);

        let json = r#"{"flag": "False"}"#;
        let result: TestStruct = serde_json::from_str(json).unwrap();
        assert!(!result.flag);
    }

    #[test]
    fn test_deserialize_numeric_string() {
        let json = r#"{"flag": "1"}"#;
        let result: TestStruct = serde_json::from_str(json).unwrap();
        assert!(result.flag);

        let json = r#"{"flag": "0"}"#;
        let result: TestStruct = serde_json::from_str(json).unwrap();
        assert!(!result.flag);
    }

    #[test]
    fn test_deserialize_yes_no() {
        let json = r#"{"flag": "yes"}"#;
        let result: TestStruct = serde_json::from_str(json).unwrap();
        assert!(result.flag);

        let json = r#"{"flag": "no"}"#;
        let result: TestStruct = serde_json::from_str(json).unwrap();
        assert!(!result.flag);
    }

    #[test]
    fn test_deserialize_empty_string() {
        let json = r#"{"flag": ""}"#;
        let result: TestStruct = serde_json::from_str(json).unwrap();
        assert!(!result.flag);
    }

    #[test]
    fn test_deserialize_integer_0_and_1() {
        let json = r#"{"flag": 1}"#;
        let result: TestStruct = serde_json::from_str(json).unwrap();
        assert!(result.flag);

        let json = r#"{"flag": 0}"#;
        let result: TestStruct = serde_json::from_str(json).unwrap();
        assert!(!result.flag);
    }

    #[test]
    fn test_deserialize_invalid_integer() {
        let json = r#"{"flag": 42}"#;
        let result: Result<TestStruct, _> = serde_json::from_str(json);
        assert!(result.is_err());

        let json = r#"{"flag": -1}"#;
        let result: Result<TestStruct, _> = serde_json::from_str(json);
        assert!(result.is_err());
    }

    #[test]
    fn test_deserialize_invalid_string() {
        let json = r#"{"flag": "invalid"}"#;
        let result: Result<TestStruct, _> = serde_json::from_str(json);
        assert!(result.is_err());
    }

    #[derive(Deserialize, Debug, PartialEq)]
    struct TestOptionalStruct {
        #[serde(default, deserialize_with = "deserialize_flexible_option_bool")]
        flag: Option<bool>,
    }

    #[test]
    fn test_deserialize_option_bool_some_true() {
        let json = r#"{"flag": true}"#;
        let result: TestOptionalStruct = serde_json::from_str(json).unwrap();
        assert_eq!(result.flag, Some(true));

        let json = r#"{"flag": "true"}"#;
        let result: TestOptionalStruct = serde_json::from_str(json).unwrap();
        assert_eq!(result.flag, Some(true));

        let json = r#"{"flag": "1"}"#;
        let result: TestOptionalStruct = serde_json::from_str(json).unwrap();
        assert_eq!(result.flag, Some(true));

        let json = r#"{"flag": 1}"#;
        let result: TestOptionalStruct = serde_json::from_str(json).unwrap();
        assert_eq!(result.flag, Some(true));
    }

    #[test]
    fn test_deserialize_option_bool_some_false() {
        let json = r#"{"flag": false}"#;
        let result: TestOptionalStruct = serde_json::from_str(json).unwrap();
        assert_eq!(result.flag, Some(false));

        let json = r#"{"flag": "false"}"#;
        let result: TestOptionalStruct = serde_json::from_str(json).unwrap();
        assert_eq!(result.flag, Some(false));

        let json = r#"{"flag": "0"}"#;
        let result: TestOptionalStruct = serde_json::from_str(json).unwrap();
        assert_eq!(result.flag, Some(false));

        let json = r#"{"flag": 0}"#;
        let result: TestOptionalStruct = serde_json::from_str(json).unwrap();
        assert_eq!(result.flag, Some(false));
    }

    #[test]
    fn test_deserialize_option_bool_none() {
        let json = r#"{"flag": null}"#;
        let result: TestOptionalStruct = serde_json::from_str(json).unwrap();
        assert_eq!(result.flag, None);

        let json = r#"{}"#;
        let result: TestOptionalStruct = serde_json::from_str(json).unwrap();
        assert_eq!(result.flag, None);
    }

    #[test]
    fn test_deserialize_option_bool_empty_string() {
        let json = r#"{"flag": ""}"#;
        let result: TestOptionalStruct = serde_json::from_str(json).unwrap();
        assert_eq!(result.flag, None);
    }

    #[test]
    fn test_deserialize_option_bool_invalid() {
        let json = r#"{"flag": "invalid"}"#;
        let result: Result<TestOptionalStruct, _> = serde_json::from_str(json);
        assert!(result.is_err());

        let json = r#"{"flag": 42}"#;
        let result: Result<TestOptionalStruct, _> = serde_json::from_str(json);
        assert!(result.is_err());
    }

    #[derive(Deserialize, Debug, PartialEq, Default)]
    struct TestNullableMapStruct {
        #[serde(default, deserialize_with = "deserialize_null_as_default")]
        bag: std::collections::HashMap<String, serde_json::Value>,
    }

    #[test]
    fn test_deserialize_null_as_default_with_real_object() {
        let json = r#"{"bag": {"a": 1, "b": "two"}}"#;
        let result: TestNullableMapStruct = serde_json::from_str(json).unwrap();
        assert_eq!(result.bag.len(), 2);
        assert_eq!(result.bag.get("a"), Some(&serde_json::json!(1)));
        assert_eq!(result.bag.get("b"), Some(&serde_json::json!("two")));
    }

    #[test]
    fn test_deserialize_null_as_default_with_explicit_null() {
        // The whole point of this helper: present-and-null must produce
        // the default value rather than failing. Bare #[serde(default)] alone
        // would fail here because null can't deserialize into a HashMap.
        let json = r#"{"bag": null}"#;
        let result: TestNullableMapStruct = serde_json::from_str(json).unwrap();
        assert!(result.bag.is_empty());
    }

    #[test]
    fn test_deserialize_null_as_default_with_missing_field() {
        let json = r#"{}"#;
        let result: TestNullableMapStruct = serde_json::from_str(json).unwrap();
        assert!(result.bag.is_empty());
    }

    #[test]
    fn test_deserialize_null_as_default_propagates_non_null_type_errors() {
        // Defaulting only kicks in for null; other invalid shapes still fail
        // so we don't silently swallow real schema breakage.
        let json = r#"{"bag": "not-an-object"}"#;
        let result: Result<TestNullableMapStruct, _> = serde_json::from_str(json);
        assert!(result.is_err());

        let json = r#"{"bag": [1, 2, 3]}"#;
        let result: Result<TestNullableMapStruct, _> = serde_json::from_str(json);
        assert!(result.is_err());
    }
}
