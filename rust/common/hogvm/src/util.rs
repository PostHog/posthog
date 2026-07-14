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

// Patterns longer than this are compiled fresh on every call instead of being cached. A Hog program
// can build a regex from event properties, so without this an attacker could ingest many unique
// large patterns and retain them all in the process-wide cache (bounded by entry count, not bytes).
// Real rule patterns are far shorter than this.
const MAX_CACHEABLE_PATTERN_LEN: usize = 1024;

fn compiled_regex(pattern: &str, case_insensitive: bool) -> Result<Arc<Regex>, VmError> {
    let compile = || {
        RegexBuilder::new(pattern)
            .case_insensitive(case_insensitive)
            .build()
            .map(Arc::new)
            .map_err(|e| VmError::InvalidRegex(pattern.to_string(), e.to_string()))
    };

    if pattern.len() > MAX_CACHEABLE_PATTERN_LEN {
        return compile();
    }

    // `get_or_insert_with` computes at most once per key even under concurrent first access, so two
    // threads racing the same cold pattern don't both compile, and a failed compile isn't cached.
    REGEX_CACHE.get_or_insert_with(&(pattern.to_owned(), case_insensitive), compile)
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
            // `%` matches any run of characters, newline included (as in ClickHouse and the
            // reference VM's unanchored matcher). The regex crate's `.` excludes `\n`, so `.*` would
            // make `elements_chain ilike '%foo%'` miss when the chain wraps across lines. `_` stays
            // `.` (single non-newline char) to match the reference's `_` -> `.`.
            result.push_str("[\\s\\S]*");
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

/// Walk `chain` into `haystack`, returning a borrow tied to `haystack` (a caller needing an owned
/// value clones only the final subtree). On the hot path of every `GET_GLOBAL`.
pub fn get_json_nested<'h>(
    haystack: &'h Value,
    mut chain: &[HogValue],
    vm: &HogVM,
) -> Result<Option<&'h Value>, VmError> {
    let mut current = Some(haystack);

    while let Some(val) = current {
        if chain.is_empty() {
            // We found a value pointed to by the last element in the chain
            return Ok(Some(val));
        }

        let next_key = chain.first().unwrap().deref(&vm.heap)?;

        match val {
            Value::Array(values) => {
                let key: &Num = next_key.try_as()?;
                if key.is_float() {
                    return Err(VmError::InvalidIndex);
                }
                // Hog JSON-path indices are 1-based; the reference also allows negatives counting
                // from the end. Index 0 and out-of-range yield "not found" (None), not an error.
                let raw = key.to_integer();
                let len = values.len() as i64;
                let idx = match raw {
                    0 => return Ok(None),
                    r if r > 0 && r <= len => (r - 1) as usize,
                    r if r < 0 && -r <= len => (len + r) as usize,
                    _ => return Ok(None),
                };
                let Some(found) = values.get(idx) else {
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
    fn test_oversized_patterns_are_not_cached() {
        // Patterns past the length cap still compile and match correctly, but are recompiled each
        // call rather than retained — so large attacker-controlled patterns can't accumulate.
        let big = "x".repeat(MAX_CACHEABLE_PATTERN_LEN + 1);
        let a = compiled_regex(&big, false).unwrap();
        let b = compiled_regex(&big, false).unwrap();
        assert!(!Arc::ptr_eq(&a, &b), "oversized pattern must not be cached");
        assert!(regex_match(&big, &big, true).unwrap()); // the literal still matches itself
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
