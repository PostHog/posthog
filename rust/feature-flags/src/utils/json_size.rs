/// Estimates the serialized size of a JSON value with minimal allocation.
///
/// Walks the JSON tree and approximates the byte length of the serialized
/// form. Close to `value.to_string().len()` but avoids the large allocation
/// of serializing the entire structure. Numbers still allocate a small
/// temporary string for accuracy, as they're typically only a few bytes.
///
/// **Conservative on JSON escapes:** strings and object keys account for the
/// bytes JSON adds when serializing `"`, `\`, `\b`, `\f`, `\n`, `\r`, `\t`
/// (one extra byte each) and other control characters in `0x00..=0x1F`
/// (six bytes total — `\u00XX`). Underestimating here lets the moka weigher
/// silently exceed the cache's configured byte budget for teams with control-
/// character-laden cohort filters or escaped quotes inside `PropertyFilter.value`.
pub fn estimate_json_size(value: &serde_json::Value) -> usize {
    match value {
        serde_json::Value::Null => 4, // "null"
        serde_json::Value::Bool(b) => {
            if *b {
                4
            } else {
                5
            }
        } // "true" or "false"
        serde_json::Value::Number(n) => n.to_string().len(),
        serde_json::Value::String(s) => 2 + escaped_bytes(s),
        serde_json::Value::Array(arr) => {
            if arr.is_empty() {
                2 // "[]"
            } else {
                2 + arr.iter().map(estimate_json_size).sum::<usize>() + arr.len().saturating_sub(1)
            }
        }
        serde_json::Value::Object(map) => {
            if map.is_empty() {
                2 // "{}"
            } else {
                2 + map
                    .iter()
                    .map(|(k, v)| 2 + escaped_bytes(k) + 1 + estimate_json_size(v))
                    .sum::<usize>()
                    + map.len().saturating_sub(1)
            }
        }
    }
}

/// Returns the byte length of `s` after JSON-style escape expansion. Mirrors
/// `serde_json::ser::format_escaped_str_contents`'s handling of the named
/// escapes (`\"`, `\\`, `\b`, `\f`, `\n`, `\r`, `\t` → 1 extra byte each)
/// and the generic `\u00XX` form for other control bytes (5 extra bytes).
fn escaped_bytes(s: &str) -> usize {
    let mut extra = 0usize;
    for b in s.bytes() {
        match b {
            b'"' | b'\\' | 0x08 | 0x09 | 0x0A | 0x0C | 0x0D => extra += 1,
            0x00..=0x1F => extra += 5,
            _ => {}
        }
    }
    s.len() + extra
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// Plain ASCII (no escapes) — estimate equals `value.to_string().len()`
    /// exactly. Sanity check that the conservative path doesn't over-count
    /// when there's nothing to escape.
    #[test]
    fn test_plain_ascii_string_matches_serialization() {
        let v = json!("hello world");
        assert_eq!(estimate_json_size(&v), v.to_string().len());
    }

    /// Embedded `"` becomes `\"` — 1 extra byte. Without escape accounting
    /// this string would be reported as 12 bytes when it actually serializes
    /// to 13 (`"a\"b"`).
    #[test]
    fn test_embedded_quote_adds_one_byte_per_quote() {
        let v = json!("a\"b\"c");
        assert_eq!(estimate_json_size(&v), v.to_string().len());
    }

    /// `\n` and `\t` each cost one extra byte over the raw payload.
    #[test]
    fn test_named_escapes_add_one_byte_each() {
        let v = json!("line1\nline2\tend");
        assert_eq!(estimate_json_size(&v), v.to_string().len());
    }

    /// Unprintable control chars in `0x00..=0x1F` (excluding the named ones)
    /// serialize as `\u00XX` — 6 bytes for a 1-byte source. Pin the +5
    /// accounting so a future "tighten the bound" change doesn't quietly
    /// lower the estimate back below the real serialized size.
    #[test]
    fn test_generic_control_char_adds_five_bytes() {
        let v = json!("\u{0001}");
        assert_eq!(estimate_json_size(&v), v.to_string().len());
    }

    /// Mixed payload with all four cases at once. This is the realistic shape
    /// for cohort/group filter values that flow into the weigher.
    #[test]
    fn test_mixed_escapes_match_serialization() {
        let v = json!("plain\"quote\nctrl\u{0007}end");
        assert_eq!(estimate_json_size(&v), v.to_string().len());
    }

    /// Object keys must escape too. A key with embedded `"` would otherwise
    /// undercount object weight under teams that use unusual property names.
    #[test]
    fn test_object_keys_account_for_escapes() {
        let v = json!({ "k\"ey": "v" });
        assert_eq!(estimate_json_size(&v), v.to_string().len());
    }

    /// The nested-shape sanity check the original implementation was anchored
    /// to: object containing array containing primitives still matches exact
    /// serialization length when there are no escapes anywhere.
    #[test]
    fn test_nested_no_escapes_matches_serialization() {
        let v = json!({"a": [1, 2, 3], "b": null, "c": true});
        assert_eq!(estimate_json_size(&v), v.to_string().len());
    }
}
