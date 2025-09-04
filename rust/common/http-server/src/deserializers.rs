use serde::{de, Deserialize, Deserializer};
use std::fmt;
use std::str::FromStr;

/// Generic deserializer that treats empty strings as None for any type that implements FromStr
///
/// This is useful for HTTP query parameters where empty strings should be treated as missing values.
///
/// # Examples
///
/// ```
/// use serde::{Deserialize, Deserializer};
/// use http_server::empty_string_as_none;
///
/// #[derive(Deserialize)]
/// struct Query {
///     #[serde(default, deserialize_with = "empty_string_as_none")]
///     value: Option<i32>,
/// }
/// ```
pub fn empty_string_as_none<'de, D, T>(de: D) -> Result<Option<T>, D::Error>
where
    D: Deserializer<'de>,
    T: FromStr,
    T::Err: fmt::Display,
{
    let opt = Option::<String>::deserialize(de)?;
    match opt.as_deref() {
        None | Some("") => Ok(None),
        Some(s) => FromStr::from_str(s).map_err(de::Error::custom).map(Some),
    }
}

/// Deserializer for timestamps that handles both strings and integers
///
/// This deserializer can parse timestamp values that come as either:
/// - Integer values (Unix timestamps)
/// - String values (that can be parsed as integers)
/// - Empty strings (treated as None)
/// - Missing values (treated as None)
///
/// # Examples
///
/// ```
/// use serde::{Deserialize, Deserializer};
/// use http_server::deserialize_optional_timestamp;
///
/// #[derive(Deserialize)]
/// struct Event {
///     #[serde(deserialize_with = "deserialize_optional_timestamp")]
///     timestamp: Option<i64>,
/// }
/// ```
pub fn deserialize_optional_timestamp<'de, D>(de: D) -> Result<Option<i64>, D::Error>
where
    D: Deserializer<'de>,
{
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum IntOrString {
        Int(i64),
        String(String),
    }

    let opt = Option::<IntOrString>::deserialize(de)?;
    match opt {
        None => Ok(None),
        Some(IntOrString::Int(i)) => Ok(Some(i)),
        Some(IntOrString::String(s)) if s.is_empty() => Ok(None),
        Some(IntOrString::String(s)) => s.parse().map(Some).map_err(de::Error::custom),
    }
}

/// Deserializer for boolean query parameters that treats presence as true
///
/// This handles the common HTTP query parameter pattern where the presence
/// of a parameter name indicates a true value, regardless of the value.
///
/// Parsing rules:
/// - `?param=` → Some(true) (empty value = present = true)  
/// - `?param=true` → Some(true)
/// - `?param=false` → Some(false)
/// - `?param=1` → Some(true)
/// - `?param=0` → Some(false)
/// - `?param=yes` → Some(true)
/// - `?param=no` → Some(false)
/// - `?param=on` → Some(true)
/// - `?param=off` → Some(false)
/// - `?param=anything_else` → Some(true) (any other value = true, presence indicates true)
/// - missing parameter → None
///
/// Note: `?param` without `=` is not valid URL encoding and won't be parsed correctly by serde_urlencoded
///
/// # Examples
///
/// ```
/// use serde::{Deserialize, Deserializer};
/// use http_server::deserialize_optional_bool;
///
/// #[derive(Deserialize)]
/// struct QueryParams {
///     #[serde(default, deserialize_with = "deserialize_optional_bool")]
///     debug: Option<bool>,
/// }
/// ```
pub fn deserialize_optional_bool<'de, D>(de: D) -> Result<Option<bool>, D::Error>
where
    D: Deserializer<'de>,
{
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum BoolOrString {
        Bool(bool),
        String(String),
    }

    let opt = Option::<BoolOrString>::deserialize(de)?;
    match opt {
        None => Ok(None),
        Some(BoolOrString::Bool(b)) => Ok(Some(b)),
        Some(BoolOrString::String(s)) => {
            match s.to_lowercase().as_str() {
                "" => Ok(Some(true)), // Empty string = present = true
                "true" | "1" | "yes" | "on" => Ok(Some(true)),
                "false" | "0" | "no" | "off" => Ok(Some(false)),
                _ => Ok(Some(true)), // Any other value = true (presence indicates true)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_deserialize_optional_bool() {
        // Test with serde_json for direct deserialization
        assert_eq!(deserialize_optional_bool(json!(true)).unwrap(), Some(true));
        assert_eq!(
            deserialize_optional_bool(json!(false)).unwrap(),
            Some(false)
        );
        assert_eq!(
            deserialize_optional_bool(json!("true")).unwrap(),
            Some(true)
        );
        assert_eq!(
            deserialize_optional_bool(json!("false")).unwrap(),
            Some(false)
        );
        assert_eq!(deserialize_optional_bool(json!("")).unwrap(), Some(true));
        assert_eq!(deserialize_optional_bool(json!("1")).unwrap(), Some(true));
        assert_eq!(deserialize_optional_bool(json!("0")).unwrap(), Some(false));
        assert_eq!(deserialize_optional_bool(json!("yes")).unwrap(), Some(true));
        assert_eq!(deserialize_optional_bool(json!("no")).unwrap(), Some(false));
        assert_eq!(
            deserialize_optional_bool(json!("anything")).unwrap(),
            Some(true)
        );
    }

    #[test]
    fn test_deserialize_optional_bool_with_url_encoded() {
        use serde::Deserialize;

        #[derive(Deserialize, PartialEq, Debug)]
        struct TestQuery {
            #[serde(default, deserialize_with = "deserialize_optional_bool")]
            flag: Option<bool>,
        }

        // Test URL-encoded query parameter patterns
        let tests = vec![
            ("flag=true", Some(true)),
            ("flag=false", Some(false)),
            ("flag=1", Some(true)),
            ("flag=0", Some(false)),
            ("flag=", Some(true)), // Empty value = present = true
            // Note: "flag" without = is not valid URL encoding
            ("other=value", None), // Missing = None
            ("", None),            // Empty query = None
        ];

        for (query, expected) in tests {
            let result: TestQuery = serde_urlencoded::from_str(query).unwrap();
            assert_eq!(result.flag, expected, "Failed for query: {query}");
        }
    }

    #[test]
    fn test_empty_string_as_none() {
        assert_eq!(
            empty_string_as_none::<_, i32>(json!("42")).unwrap(),
            Some(42)
        );
        assert_eq!(empty_string_as_none::<_, i32>(json!("")).unwrap(), None);
        assert!(empty_string_as_none::<_, i32>(json!("invalid")).is_err());
    }

    #[test]
    fn test_deserialize_optional_timestamp() {
        assert_eq!(
            deserialize_optional_timestamp(json!(1234567890)).unwrap(),
            Some(1234567890)
        );
        assert_eq!(
            deserialize_optional_timestamp(json!("1234567890")).unwrap(),
            Some(1234567890)
        );
        assert_eq!(deserialize_optional_timestamp(json!("")).unwrap(), None);
        assert!(deserialize_optional_timestamp(json!("invalid")).is_err());
    }
}
