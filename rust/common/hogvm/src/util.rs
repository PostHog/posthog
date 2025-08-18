use regex::RegexBuilder;
use serde_json::Value;

use crate::{
    error::VmError,
    values::{HogValue, Num},
    vm::HogVM,
};

pub fn like(
    val: impl AsRef<str>,
    pattern: impl AsRef<str>,
    case_sensitive: bool,
) -> Result<bool, VmError> {
    let pattern = like_to_regex(pattern.as_ref());
    regex_match(val, pattern, case_sensitive)
}

pub fn regex_match(
    val: impl AsRef<str>,
    pattern: impl AsRef<str>,
    case_sensitive: bool,
) -> Result<bool, VmError> {
    let mut builder = RegexBuilder::new(pattern.as_ref());
    // TODO - this is expensive, but I'm not keen on optimizing it right now
    let regex = builder
        .case_insensitive(!case_sensitive)
        .build()
        .map_err(|e| VmError::InvalidRegex(pattern.as_ref().to_string(), e.to_string()))?;
    Ok(regex.is_match(val.as_ref()))
}

fn like_to_regex(pattern: &str) -> String {
    let mut result = String::from("^");
    let mut escape = false;

    for c in pattern.chars() {
        if escape {
            // Handle escaped character
            match c {
                '%' | '_' | '\\' => {
                    result.push_str(&regex::escape(&c.to_string()));
                }
                _ => {
                    // Backslash loses special meaning if not escaping a metacharacter
                    result.push_str(&regex::escape(&format!("\\{c}")));
                }
            }
            escape = false;
        } else if c == '\\' {
            escape = true;
        } else if c == '%' {
            result.push_str(".*");
        } else if c == '_' {
            result.push('.');
        } else {
            // Escape regular regex metacharacters
            result.push_str(&regex::escape(&c.to_string()));
        }
    }

    // Handle trailing backslash
    if escape {
        result.push_str(&regex::escape("\\"));
    }

    result.push('$');
    result
}

pub fn get_json_nested(
    haystack: &Value,
    mut chain: &[HogValue],
    vm: &HogVM,
) -> Result<Option<Value>, VmError> {
    let mut current = Some(haystack);

    while let Some(val) = current {
        if chain.is_empty() {
            // We found a value pointed to by the last element in the chain
            return Ok(Some(val.clone()));
        }

        let next_key = chain.first().unwrap().deref(&vm.heap)?;

        match val {
            Value::Array(values) => {
                let key: &Num = next_key.try_as()?;
                if key.is_float() || key.to_integer() < 1 {
                    return Err(VmError::InvalidIndex);
                }
                let key = (key.to_integer() as usize) - 1; // Hog indices are 1 based
                let Some(found) = values.get(key) else {
                    return Ok(None);
                };
                current = Some(found);
            }
            Value::Object(map) => {
                let key: &str = next_key.try_as()?;
                let Some(found) = map.get(key) else {
                    return Ok(None);
                };
                current = Some(found);
            }
            _ => return Ok(None),
        }
        chain = &chain[1..];
    }

    Ok(None)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_basic_matching() {
        assert!(like("hello", "hello", true).unwrap());
        assert!(!like("hello", "world", true).unwrap());
    }

    #[test]
    fn test_percent_wildcard() {
        assert!(like("hello", "%ello", true).unwrap());
        assert!(like("hello", "h%", true).unwrap());
        assert!(like("hello", "%ell%", true).unwrap());
        assert!(like("hello", "%", true).unwrap());
        assert!(!like("hello", "world%", true).unwrap());
    }

    #[test]
    fn test_underscore_wildcard() {
        assert!(like("hello", "h_llo", true).unwrap());
        assert!(like("hello", "_ello", true).unwrap());
        assert!(like("hello", "hell_", true).unwrap());
        assert!(like("hello", "h__lo", true).unwrap());
        assert!(!like("hello", "_", true).unwrap());
    }

    #[test]
    fn test_escaping() {
        assert!(like("100% sure", "100\\% sure", true).unwrap());
        assert!(like("hello_world", "hello\\_world", true).unwrap());
        assert!(like("hello\\world", "hello\\\\world", true).unwrap());
        assert!(like("100%sad sure", "100% sure", true).unwrap());
    }

    #[test]
    fn test_combined_wildcards() {
        assert!(like("hello world", "h%_o%", true).unwrap());
        assert!(like("hello world", "%o_ld", true).unwrap());
        assert!(like("hello world", "h%ld", true).unwrap());
    }

    #[test]
    fn test_utf8_handling() {
        assert!(like("こんにちは", "こ%は", true).unwrap());
        assert!(like("こんにちは", "こ_にちは", true).unwrap());
        assert!(like("¥100", "_100", true).unwrap());
    }

    #[test]
    fn test_optimization_for_contains() {
        // Tests the optimization for %needle% patterns
        assert!(like("hello world", "%llo wo%", true).unwrap());
        assert!(!like("hello world", "%xyz%", true).unwrap());
    }

    #[test]
    fn test_edge_cases() {
        assert!(like("", "", true).unwrap());
        assert!(like("", "%", true).unwrap());
        assert!(!like("", "_", true).unwrap());
        assert!(like("\\", "\\\\", true).unwrap());
        assert!(like("%", "\\%", true).unwrap());
        assert!(like("_", "\\_", true).unwrap());
    }

    #[test]
    fn test_backslash_without_metachar() {
        // Backslash loses special meaning if not escaping a metacharacter
        assert!(like("hello\\there", "hello\\there", true).unwrap());
        assert!(like("hello\\x", "hello\\x", true).unwrap());
    }
}
