use error::EventError;

use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::Value;
use tracing::warn;

use uuid::Uuid;

pub mod app_context;
pub mod assignment_rules;
pub mod config;
pub mod error;
pub mod fingerprinting;
pub mod frames;
pub mod issue_resolution;
pub mod langs;
pub mod metric_consts;
pub mod pipeline;
pub mod posthog_utils;
pub mod symbol_store;
pub mod teams;
pub mod types;

pub fn recursively_sanitize_properties(
    id: Uuid,
    value: &mut Value,
    depth: usize,
) -> Result<(), EventError> {
    if depth > 64 {
        // We don't want to recurse too deeply, in case we have a circular reference or something.
        return Err(EventError::InvalidProperties(
            id,
            "Recursion limit exceeded".to_string(),
        ));
    }
    match value {
        Value::Object(map) => {
            for (_, v) in map.iter_mut() {
                recursively_sanitize_properties(id, v, depth + 1)?;
            }
        }
        Value::Array(arr) => {
            for v in arr.iter_mut() {
                recursively_sanitize_properties(id, v, depth + 1)?;
            }
        }
        Value::String(s) => {
            if needs_sanitization(s) {
                warn!("Sanitizing null bytes from string in event {}", id);
                *s = sanitize_string(s.clone());
            }
        }
        _ => {}
    }
    Ok(())
}

static WHITESPACE_REGEX: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s{50,}").unwrap());

// Postgres doesn't like nulls (u0000) in strings, so we replace them with uFFFD. We also replace all 50-or-more whitespace sequences with "<ws trimmed>".
pub fn sanitize_string(s: String) -> String {
    let no_nulls = s.replace('\u{0000}', "\u{FFFD}");
    WHITESPACE_REGEX
        .replace_all(&no_nulls, "<ws trimmed>")
        .to_string()
}

pub fn needs_sanitization(s: &str) -> bool {
    s.contains('\u{0000}') || s.len() > 512
}

struct WithIndices<T> {
    indices: Vec<usize>,
    inner: T,
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn test_sanitize_string_null_bytes() {
        let input = "hello\u{0000}world".to_string();
        let result = sanitize_string(input);
        assert_eq!(result, "hello\u{FFFD}world");
    }

    #[test]
    fn test_sanitize_string_long_whitespace() {
        let mut input = "hello".to_string();
        input.push_str(&"\n".repeat(60));
        input.push_str("world");
        let result = sanitize_string(input);
        assert_eq!(result, "hello<ws trimmed>world");
    }

    #[test]
    fn test_sanitize_string_short_whitespace() {
        let input = "hello     world".to_string();
        let result = sanitize_string(input);
        assert_eq!(result, "hello     world");
    }

    #[test]
    fn test_sanitize_string_both_issues() {
        let mut input = "hello\u{0000}".to_string();
        input.push_str(&"\n".repeat(60));
        input.push_str("world");
        let result = sanitize_string(input);
        assert_eq!(result, "hello\u{FFFD}<ws trimmed>world");
    }
}
