//! JSON path parsing for AI endpoint external properties.
//!
//! Supports a simple JSON path grammar:
//! - `.property` - access a property
//! - `[index]` - access an array element
//!
//! Valid paths: `$ai_input`, `$ai_input[0]`, `$ai_input[0].content[1].file`
//! Invalid paths: `[0]`, `.foo`, `foo..bar`, `foo[]`, `foo[abc]`, `foo[-1]`

use nom::{
    branch::alt,
    bytes::complete::{tag, take_while1},
    character::complete::digit1,
    combinator::{map, map_res},
    multi::many0,
    sequence::{delimited, preceded},
    IResult,
};
use serde_json::Value;

use crate::api::CaptureError;

/// Parsed JSON path segment
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PathSegment {
    Property(String),
    Index(usize),
}

fn is_property_char(c: char) -> bool {
    c != '.' && c != '[' && c != ']'
}

/// Parse a property name: any characters except `.`, `[`, `]`
fn property(input: &str) -> IResult<&str, PathSegment> {
    map(take_while1(is_property_char), |s: &str| {
        PathSegment::Property(s.to_string())
    })(input)
}

/// Parse an array index: [0-9]+
fn index(input: &str) -> IResult<&str, PathSegment> {
    map_res(delimited(tag("["), digit1, tag("]")), |s: &str| {
        s.parse::<usize>().map(PathSegment::Index)
    })(input)
}

/// Parse a path continuation: .property or [index]
fn continuation(input: &str) -> IResult<&str, PathSegment> {
    alt((preceded(tag("."), property), index))(input)
}

/// Parse a simple JSON path into segments.
///
/// Grammar:
/// ```text
/// path = segment (("." segment) | ("[" index "]"))*
/// segment = [a-zA-Z_$][a-zA-Z0-9_$]*
/// index = [0-9]+
/// ```
pub fn parse_json_path(path: &str) -> Result<Vec<PathSegment>, CaptureError> {
    if path.is_empty() {
        return Err(CaptureError::RequestParsingError(
            "JSON path cannot be empty".to_string(),
        ));
    }

    let (rest, first) = property(path)
        .map_err(|_| CaptureError::RequestParsingError(format!("Invalid JSON path '{path}'")))?;

    let (rest, more) = many0(continuation)(rest)
        .map_err(|_| CaptureError::RequestParsingError(format!("Invalid JSON path '{path}'")))?;

    if !rest.is_empty() {
        return Err(CaptureError::RequestParsingError(format!(
            "Invalid JSON path '{path}': unexpected '{rest}'"
        )));
    }

    Ok([vec![first], more].concat())
}

/// Insert a value at the given path in a JSON object.
/// Creates intermediate objects/arrays as needed.
pub fn insert_at_path(
    root: &mut serde_json::Map<String, Value>,
    path: &[PathSegment],
    value: Value,
) -> Result<(), CaptureError> {
    if path.is_empty() {
        return Err(CaptureError::RequestParsingError(
            "Cannot insert at empty path".to_string(),
        ));
    }

    // Handle the first segment specially since root is a Map
    let first = &path[0];
    let PathSegment::Property(name) = first else {
        return Err(CaptureError::RequestParsingError(
            "Path must start with a property segment".to_string(),
        ));
    };

    if path.len() == 1 {
        root.insert(name.clone(), value);
        return Ok(());
    }

    // Ensure the property exists with appropriate type for next segment
    let next_segment = &path[1];
    let entry = root
        .entry(name.clone())
        .or_insert_with(|| match next_segment {
            PathSegment::Property(_) => Value::Object(serde_json::Map::new()),
            PathSegment::Index(_) => Value::Array(Vec::new()),
        });

    insert_at_path_recursive(entry, &path[1..], value)
}

fn insert_at_path_recursive(
    current: &mut Value,
    path: &[PathSegment],
    value: Value,
) -> Result<(), CaptureError> {
    if path.is_empty() {
        *current = value;
        return Ok(());
    }

    let segment = &path[0];

    if path.len() == 1 {
        // Last segment - insert the value
        match segment {
            PathSegment::Property(name) => {
                if !current.is_object() {
                    *current = Value::Object(serde_json::Map::new());
                }
                current
                    .as_object_mut()
                    .unwrap()
                    .insert(name.clone(), value);
            }
            PathSegment::Index(idx) => {
                if !current.is_array() {
                    *current = Value::Array(Vec::new());
                }
                let arr = current.as_array_mut().unwrap();
                // Extend array with nulls if needed
                while arr.len() <= *idx {
                    arr.push(Value::Null);
                }
                arr[*idx] = value;
            }
        }
        return Ok(());
    }

    // Navigate/create intermediate structure
    let next_segment = &path[1];

    match segment {
        PathSegment::Property(name) => {
            if !current.is_object() {
                *current = Value::Object(serde_json::Map::new());
            }
            let obj = current.as_object_mut().unwrap();

            let entry = obj.entry(name.clone()).or_insert_with(|| match next_segment {
                PathSegment::Property(_) => Value::Object(serde_json::Map::new()),
                PathSegment::Index(_) => Value::Array(Vec::new()),
            });

            insert_at_path_recursive(entry, &path[1..], value)
        }
        PathSegment::Index(idx) => {
            if !current.is_array() {
                *current = Value::Array(Vec::new());
            }
            let arr = current.as_array_mut().unwrap();

            // Extend array if needed
            while arr.len() <= *idx {
                arr.push(Value::Null);
            }

            // Initialize the element with appropriate type for next segment
            if arr[*idx].is_null() {
                arr[*idx] = match next_segment {
                    PathSegment::Property(_) => Value::Object(serde_json::Map::new()),
                    PathSegment::Index(_) => Value::Array(Vec::new()),
                };
            }

            insert_at_path_recursive(&mut arr[*idx], &path[1..], value)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    // ========================================================================
    // parse_json_path tests
    // ========================================================================

    #[test]
    fn test_simple_property() {
        let result = parse_json_path("$ai_input").unwrap();
        assert_eq!(result, vec![PathSegment::Property("$ai_input".to_string())]);
    }

    #[test]
    fn test_property_with_index() {
        let result = parse_json_path("$ai_input[0]").unwrap();
        assert_eq!(
            result,
            vec![
                PathSegment::Property("$ai_input".to_string()),
                PathSegment::Index(0)
            ]
        );
    }

    #[test]
    fn test_nested_path() {
        let result = parse_json_path("$ai_input[0].content").unwrap();
        assert_eq!(
            result,
            vec![
                PathSegment::Property("$ai_input".to_string()),
                PathSegment::Index(0),
                PathSegment::Property("content".to_string())
            ]
        );
    }

    #[test]
    fn test_complex_path() {
        let result = parse_json_path("$ai_input[0].content[1].file").unwrap();
        assert_eq!(
            result,
            vec![
                PathSegment::Property("$ai_input".to_string()),
                PathSegment::Index(0),
                PathSegment::Property("content".to_string()),
                PathSegment::Index(1),
                PathSegment::Property("file".to_string())
            ]
        );
    }

    #[test]
    fn test_simple_identifier() {
        let result = parse_json_path("foo").unwrap();
        assert_eq!(result, vec![PathSegment::Property("foo".to_string())]);
    }

    #[test]
    fn test_underscore_prefix() {
        let result = parse_json_path("_private").unwrap();
        assert_eq!(result, vec![PathSegment::Property("_private".to_string())]);
    }

    #[test]
    fn test_multi_digit_index() {
        let result = parse_json_path("arr[123]").unwrap();
        assert_eq!(
            result,
            vec![
                PathSegment::Property("arr".to_string()),
                PathSegment::Index(123)
            ]
        );
    }

    #[test]
    fn test_hyphenated_property() {
        let result = parse_json_path("my-property").unwrap();
        assert_eq!(
            result,
            vec![PathSegment::Property("my-property".to_string())]
        );
    }

    #[test]
    fn test_hyphenated_nested() {
        let result = parse_json_path("$ai-input[0].content-type").unwrap();
        assert_eq!(
            result,
            vec![
                PathSegment::Property("$ai-input".to_string()),
                PathSegment::Index(0),
                PathSegment::Property("content-type".to_string())
            ]
        );
    }

    #[test]
    fn test_numeric_property() {
        let result = parse_json_path("123").unwrap();
        assert_eq!(result, vec![PathSegment::Property("123".to_string())]);
    }

    #[test]
    fn test_spaces_in_property() {
        let result = parse_json_path("my property").unwrap();
        assert_eq!(
            result,
            vec![PathSegment::Property("my property".to_string())]
        );
    }

    #[test]
    fn test_invalid_starts_with_bracket() {
        let result = parse_json_path("[0]");
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_starts_with_dot() {
        let result = parse_json_path(".foo");
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_empty_segment() {
        let result = parse_json_path("foo..bar");
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_empty_index() {
        let result = parse_json_path("foo[]");
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_non_numeric_index() {
        let result = parse_json_path("foo[abc]");
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_negative_index() {
        let result = parse_json_path("foo[-1]");
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_unclosed_bracket() {
        let result = parse_json_path("foo[0");
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_trailing_dot() {
        let result = parse_json_path("foo.");
        assert!(result.is_err());
    }

    #[test]
    fn test_empty_path() {
        let result = parse_json_path("");
        assert!(result.is_err());
    }

    // ========================================================================
    // insert_at_path tests
    // ========================================================================

    #[test]
    fn test_insert_simple_property() {
        let mut root = serde_json::Map::new();
        let path = parse_json_path("$ai_input").unwrap();

        insert_at_path(&mut root, &path, json!("placeholder")).unwrap();

        assert_eq!(root.get("$ai_input").unwrap(), &json!("placeholder"));
    }

    #[test]
    fn test_insert_with_index() {
        let mut root = serde_json::Map::new();
        let path = parse_json_path("$ai_input[0]").unwrap();

        insert_at_path(&mut root, &path, json!("placeholder")).unwrap();

        assert_eq!(root.get("$ai_input").unwrap(), &json!(["placeholder"]));
    }

    #[test]
    fn test_insert_nested() {
        let mut root = serde_json::Map::new();
        let path = parse_json_path("$ai_input[0].content").unwrap();

        insert_at_path(&mut root, &path, json!("placeholder")).unwrap();

        assert_eq!(
            root.get("$ai_input").unwrap(),
            &json!([{ "content": "placeholder" }])
        );
    }

    #[test]
    fn test_insert_extends_array() {
        let mut root = serde_json::Map::new();
        root.insert("$ai_input".to_string(), json!(["a"]));

        let path = parse_json_path("$ai_input[2]").unwrap();
        insert_at_path(&mut root, &path, json!("c")).unwrap();

        assert_eq!(root.get("$ai_input").unwrap(), &json!(["a", null, "c"]));
    }

    #[test]
    fn test_insert_replaces_existing() {
        let mut root = serde_json::Map::new();
        root.insert("$ai_input".to_string(), json!("old"));

        let path = parse_json_path("$ai_input").unwrap();
        insert_at_path(&mut root, &path, json!("new")).unwrap();

        assert_eq!(root.get("$ai_input").unwrap(), &json!("new"));
    }

    #[test]
    fn test_insert_deeply_nested() {
        let mut root = serde_json::Map::new();
        let path = parse_json_path("a[0].b[1].c").unwrap();

        insert_at_path(&mut root, &path, json!("deep")).unwrap();

        assert_eq!(
            root.get("a").unwrap(),
            &json!([{ "b": [null, { "c": "deep" }] }])
        );
    }

    #[test]
    fn test_insert_multiple_paths() {
        let mut root = serde_json::Map::new();

        let path1 = parse_json_path("$ai_input[0].content").unwrap();
        insert_at_path(&mut root, &path1, json!("input0")).unwrap();

        let path2 = parse_json_path("$ai_input[1].content").unwrap();
        insert_at_path(&mut root, &path2, json!("input1")).unwrap();

        assert_eq!(
            root.get("$ai_input").unwrap(),
            &json!([{ "content": "input0" }, { "content": "input1" }])
        );
    }

    #[test]
    fn test_insert_empty_path_fails() {
        let mut root = serde_json::Map::new();
        let result = insert_at_path(&mut root, &[], json!("value"));
        assert!(result.is_err());
    }
}
