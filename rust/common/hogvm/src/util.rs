use std::sync::Arc;

use once_cell::sync::Lazy;
use quick_cache::sync::Cache;
use regex::{Regex, RegexBuilder};
use serde_json::Value;

use crate::{
    error::VmError,
    values::{HogValue, Num},
    vm::HogVM,
};

// Compiling a regex is orders of magnitude more expensive than matching against an already-compiled
// one, and rule patterns are constant across the events they run on — so compile once and reuse.
// The cache is bounded so dynamically constructed patterns can't grow it without limit, and global
// (rather than per-VM) so a pattern is compiled at most once fleet-wide instead of once per worker.
static REGEX_CACHE: Lazy<Cache<(String, bool), Arc<Regex>>> = Lazy::new(|| Cache::new(8192));

fn compiled_regex(pattern: &str, case_insensitive: bool) -> Result<Arc<Regex>, VmError> {
    let key = (pattern.to_owned(), case_insensitive);
    if let Some(regex) = REGEX_CACHE.get(&key) {
        return Ok(regex);
    }
    let regex = Arc::new(
        RegexBuilder::new(pattern)
            .case_insensitive(case_insensitive)
            .build()
            .map_err(|e| VmError::InvalidRegex(pattern.to_string(), e.to_string()))?,
    );
    REGEX_CACHE.insert(key, regex.clone());
    Ok(regex)
}

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
    let regex = compiled_regex(pattern.as_ref(), !case_sensitive)?;
    Ok(regex.is_match(val.as_ref()))
}

pub fn regex_extract(
    haystack: impl AsRef<str>,
    pattern: impl AsRef<str>,
) -> Result<String, VmError> {
    let regex = compiled_regex(pattern.as_ref(), false)?;
    let Some(captures) = regex.captures(haystack.as_ref()) else {
        return Ok(String::new());
    };
    let result = if regex.captures_len() > 1 {
        captures.get(1).map(|m| m.as_str()).unwrap_or("")
    } else {
        captures.get(0).map(|m| m.as_str()).unwrap_or("")
    };
    Ok(result.to_string())
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

    #[test]
    fn test_compiled_regex_is_cached() {
        // Same (pattern, case) must hand back the same compiled regex instead of recompiling.
        let a = compiled_regex("foo.*bar", false).unwrap();
        let b = compiled_regex("foo.*bar", false).unwrap();
        assert!(Arc::ptr_eq(&a, &b));

        // Case variants are distinct cache entries, not aliases.
        let insensitive = compiled_regex("foo.*bar", true).unwrap();
        assert!(!Arc::ptr_eq(&a, &insensitive));
    }

    #[test]
    fn test_regex_match_case_sensitivity() {
        assert!(regex_match("Hello", "hello", false).unwrap()); // case-insensitive matches
        assert!(!regex_match("Hello", "hello", true).unwrap()); // case-sensitive does not
    }

    #[test]
    fn test_invalid_regex_errors() {
        assert!(matches!(
            regex_match("anything", "(unclosed", true),
            Err(VmError::InvalidRegex(..))
        ));
    }

    #[test]
    fn test_regex_extract_uses_cache() {
        assert_eq!(regex_extract("id=42;", r"id=(\d+)").unwrap(), "42");
        // Second call exercises the cached compilation path and stays correct.
        assert_eq!(regex_extract("id=7;", r"id=(\d+)").unwrap(), "7");
    }
}
