//! Person-property size enforcement, shared by the leader (admission-time
//! trimming and rejection) and anything that needs to reason about the
//! Postgres row the writer will eventually produce.
//!
//! The authority on "too big" is the `check_properties_size` constraint on
//! `posthog_person`: `pg_column_size(properties) <= 655360`. That measures
//! the JSONB *binary encoding*, not the raw JSON text — per-element entry
//! headers, PG's base-10000 numeric format, and alignment padding all
//! count. `jsonb_column_size` reproduces that number exactly so admission
//! enforces the real constraint rather than a proxy with a hoped-for
//! margin; a property test compares it against a live Postgres
//! (`pg_column_size($1::jsonb)`) so any drift from PG's encoding fails
//! loudly. The JSONB on-disk format is stable across PG versions by
//! design (pg_upgrade compatibility), which is what makes reimplementing
//! it sound.

use std::collections::HashSet;
use std::sync::LazyLock;

use serde_json::Value;

/// Properties that must never be trimmed, matching the Node.js ingestion
/// pipeline's `ALL_PROTECTED_PROPERTIES` in `person-property-utils.ts`.
static PROTECTED_PROPERTIES: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    HashSet::from([
        // Core person properties
        "email",
        "name",
        // Event-to-person properties (mobile)
        "$app_build",
        "$app_name",
        "$app_namespace",
        "$app_version",
        // Event-to-person properties (web)
        "$browser",
        "$browser_version",
        "$device_type",
        "$current_url",
        "$pathname",
        "$os",
        "$os_name",
        "$os_version",
        "$referring_domain",
        "$referrer",
        "$screen_height",
        "$screen_width",
        "$viewport_height",
        "$viewport_width",
        "$raw_user_agent",
        // UTM and campaign tracking
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_name",
        "utm_term",
        "gclid",
        "gad_source",
        "gclsrc",
        "dclid",
        "gbraid",
        "wbraid",
        "fbclid",
        "msclkid",
        "twclid",
        "li_fat_id",
        "mc_cid",
        "igshid",
        "ttclid",
        "rdt_cid",
        "irclid",
        "_kx",
        "epik",
        "qclid",
        "sccid",
        // Session and page tracking
        "$session_id",
        "$window_id",
        "$pageview_id",
        "$host",
        // Identity and device tracking
        "$user_id",
        "$device_id",
        "$anon_distinct_id",
        // Initial/first-touch properties
        "$initial_referrer",
        "$initial_referring_domain",
        "$initial_utm_source",
        "$initial_utm_medium",
        "$initial_utm_campaign",
        "$initial_utm_content",
        "$initial_utm_term",
    ])
});

/// Returns true if the property can be trimmed (is not protected).
pub fn can_trim_property(name: &str) -> bool {
    !PROTECTED_PROPERTIES.contains(name)
}

/// Floats at or above this magnitude are clamped by [`sanitize_for_jsonb`].
/// Postgres renders jsonb numerics in expanded decimal notation (never
/// e-notation), and serde_json's parser overflows on integer expansions of
/// ~1e308 and beyond — so a number in the window [1e308, f64::MAX] applies
/// to PG but can never be read back by a Rust consumer (including the
/// leader's own PG fallback load). 1e307 expands to 308 digits, which
/// parses back exactly.
pub const MAX_JSONB_SAFE_MAGNITUDE: f64 = 1e307;

/// What [`sanitize_for_jsonb`] rewrote, for the caller's counters.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct SanitizeStats {
    /// Strings (keys or values) that contained `\u{0000}`.
    pub nul_strings: u64,
    /// Floats clamped to ±[`MAX_JSONB_SAFE_MAGNITUDE`].
    pub clamped_numbers: u64,
}

impl SanitizeStats {
    pub fn changed(&self) -> bool {
        self.nul_strings > 0 || self.clamped_numbers > 0
    }
}

/// Rewrite the merged state so that it both applies to Postgres jsonb and
/// round-trips back out of it, at any depth:
///
/// * `\u{0000}` (NUL) becomes `\u{FFFD}` in every string — keys and
///   values — mirroring the Node.js pipeline's `sanitizeJsonbValue`;
///   Postgres refuses NUL outright. A sanitized key can collide with an
///   existing key; the later entry wins, matching what Postgres itself
///   does when parsing JSON text with duplicate keys.
/// * Floats beyond ±[`MAX_JSONB_SAFE_MAGNITUDE`] are clamped to it, so
///   Postgres's expanded numeric rendering stays parseable on the way
///   back (see the constant's doc).
pub fn sanitize_for_jsonb(value: &mut Value) -> SanitizeStats {
    let mut stats = SanitizeStats::default();
    sanitize_value(value, &mut stats);
    stats
}

fn sanitize_value(value: &mut Value, stats: &mut SanitizeStats) {
    match value {
        Value::String(s) => {
            if s.contains('\u{0000}') {
                *s = s.replace('\u{0000}', "\u{FFFD}");
                stats.nul_strings += 1;
            }
        }
        Value::Number(n) => {
            // Only floats can exceed the safe magnitude: i64/u64 top out
            // around 1.8e19.
            if let Some(f) = n.as_f64() {
                if n.is_f64() && f.abs() > MAX_JSONB_SAFE_MAGNITUDE {
                    let clamped = MAX_JSONB_SAFE_MAGNITUDE.copysign(f);
                    *value = Value::from(clamped);
                    stats.clamped_numbers += 1;
                }
            }
        }
        Value::Array(items) => {
            for item in items {
                sanitize_value(item, stats);
            }
        }
        Value::Object(map) => {
            if map.keys().any(|k| k.contains('\u{0000}')) {
                let entries: Vec<(String, Value)> = std::mem::take(map).into_iter().collect();
                for (key, mut val) in entries {
                    sanitize_value(&mut val, stats);
                    let key = if key.contains('\u{0000}') {
                        stats.nul_strings += 1;
                        key.replace('\u{0000}', "\u{FFFD}")
                    } else {
                        key
                    };
                    map.insert(key, val);
                }
            } else {
                for val in map.values_mut() {
                    sanitize_value(val, stats);
                }
            }
        }
        _ => {}
    }
}

/// The size Postgres will report for this value as a `jsonb` column —
/// `pg_column_size(value::jsonb)` — computed without touching Postgres.
pub fn jsonb_column_size(value: &Value) -> usize {
    // 4-byte varlena header, then the root container. Scalars at the root
    // are wrapped in a one-element pseudo-array container.
    let mut offset = 4usize;
    offset = match value {
        Value::Object(_) | Value::Array(_) => container_size(value, offset),
        scalar => scalar_container_size(scalar, offset),
    };
    offset
}

/// A root-level scalar is stored as a one-element array container with the
/// scalar flag; the layout matches a one-element array.
fn scalar_container_size(scalar: &Value, offset: usize) -> usize {
    // Container header + one JEntry.
    let mut offset = offset + 4 + 4;
    offset += element_size(scalar, offset);
    offset
}

/// Size contribution of a container (object or array) starting at
/// `offset` bytes from the start of the varlena datum. Returns the offset
/// just past the container. `offset` matters because numerics and nested
/// containers are padded to 4-byte alignment relative to the datum start.
fn container_size(value: &Value, offset: usize) -> usize {
    match value {
        Value::Object(map) => {
            // Header + one JEntry per key and per value, then all key
            // bytes, then all values. Keys are processed in PG's storage
            // order (length, then bytewise) because alignment padding for
            // numeric/container values depends on the running offset.
            let mut offset = offset + 4 + 8 * map.len();
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort_by(|a, b| {
                a.len()
                    .cmp(&b.len())
                    .then_with(|| a.as_bytes().cmp(b.as_bytes()))
            });
            for key in &keys {
                offset += key.len();
            }
            for key in &keys {
                offset += element_size(&map[key.as_str()], offset);
            }
            offset
        }
        Value::Array(items) => {
            let mut offset = offset + 4 + 4 * items.len();
            for item in items {
                offset += element_size(item, offset);
            }
            offset
        }
        _ => unreachable!("container_size only called for objects and arrays"),
    }
}

/// Data-section size of one element whose data begins at `offset` from
/// the datum start (its JEntry is accounted for by the parent container).
fn element_size(value: &Value, offset: usize) -> usize {
    match value {
        Value::Null | Value::Bool(_) => 0,
        Value::String(s) => s.len(),
        Value::Number(n) => {
            // Numerics are stored as a full numeric datum, padded to
            // 4-byte alignment from the datum start.
            let padding = (4 - offset % 4) % 4;
            padding + numeric_datum_size(&n.to_string())
        }
        Value::Object(_) | Value::Array(_) => {
            let padding = (4 - offset % 4) % 4;
            padding + (container_size(value, offset + padding) - (offset + padding))
        }
    }
}

/// The size of the numeric datum PG builds from this JSON number literal:
/// 4-byte varlena header, a 2-byte short (or 4-byte long) numeric header,
/// and two bytes per base-10000 digit group, mirroring `numeric_in`.
fn numeric_datum_size(literal: &str) -> usize {
    let (weight, groups, dscale) = parse_numeric(literal);
    let header = if short_header_fits(weight, dscale) {
        2
    } else {
        4
    };
    4 + header + 2 * groups
}

/// PG's short numeric header packs the sign, a 6-bit display scale, and a
/// signed weight; it fits when dscale <= 63 and weight is in [-44, 83]
/// base-10000 units (NUMERIC_SHORT_WEIGHT_MIN/MAX in numeric.c).
fn short_header_fits(weight: i32, dscale: u32) -> bool {
    dscale <= 0x3F && (-44..=83).contains(&weight)
}

/// Parse a JSON number literal the way `numeric_in` does, returning the
/// base-10000 weight, the count of stored base-10000 digit groups (with
/// zero groups stripped from both ends, as PG does), and the display
/// scale (count of decimal fraction digits after expanding any exponent).
fn parse_numeric(literal: &str) -> (i32, usize, u32) {
    let s = literal.strip_prefix('-').unwrap_or(literal);
    let (mantissa, exponent) = match s.find(['e', 'E']) {
        Some(pos) => (&s[..pos], s[pos + 1..].parse::<i64>().unwrap_or(0)),
        None => (s, 0),
    };
    let (int_part, frac_part) = match mantissa.find('.') {
        Some(pos) => (&mantissa[..pos], &mantissa[pos + 1..]),
        None => (mantissa, ""),
    };

    // Expand the exponent into a plain decimal digit string with a point
    // position. `digits` is the full significand; `point` is how many of
    // those digits sit before the decimal point (may be <= 0).
    let mut digits: Vec<u8> = int_part.bytes().chain(frac_part.bytes()).collect();
    let mut point = int_part.len() as i64 + exponent;

    // Strip leading zeros (they only shift the logical point position
    // bookkeeping below, which works on the trimmed significand).
    let leading = digits.iter().take_while(|&&b| b == b'0').count();
    digits.drain(..leading);
    point -= leading as i64;
    // dscale is the number of decimal fraction digits PG displays: digits
    // after the point, floored at zero, including trailing zeros as
    // written.
    let dscale = (digits.len() as i64 - point).max(0) as u32;
    // Trailing zeros do not become stored digits (PG strips zero groups),
    // but they already counted toward dscale above.
    while digits.last() == Some(&b'0') {
        digits.pop();
    }

    if digits.is_empty() {
        // Zero: no digit groups; weight 0.
        return (0, 0, dscale);
    }

    // Group into base-10000 digits aligned to the decimal point: the
    // first group holds ((point - 1) mod 4) + 1 leading decimal digits.
    let first_group_len = (((point - 1).rem_euclid(4)) + 1) as usize;
    let weight = ((point - first_group_len as i64) / 4) as i32;
    let mut groups = 0usize;
    let mut index = 0usize;
    let mut group_len = first_group_len.min(digits.len());
    let mut leading_zero_groups = 0usize;
    let mut seen_nonzero = false;
    while index < digits.len() {
        let group = &digits[index..(index + group_len).min(digits.len())];
        let is_zero = group.iter().all(|&b| b == b'0');
        if is_zero && !seen_nonzero {
            leading_zero_groups += 1;
        } else {
            seen_nonzero = true;
        }
        groups += 1;
        index += group_len;
        group_len = 4;
    }
    // Strip leading zero groups (weight shrinks with them) and trailing
    // zero groups (partially-filled last groups pad with zeros, and fully
    // zero tails are not stored).
    let weight = weight - leading_zero_groups as i32;
    groups -= leading_zero_groups;
    // Trailing zero groups: recompute by walking backwards over the
    // grouped digits. A trailing group is zero only if every digit in it
    // is zero; digits had trailing zeros stripped already, so only a
    // group that lies entirely past the last stored digit is zero — which
    // cannot happen after the strip. Nothing further to remove.
    (weight, groups, dscale)
}

/// Trim person properties under `target_bytes` (measured as
/// `jsonb_column_size`, the constraint's own metric) by removing
/// non-protected properties in alphabetical order, matching the Node.js
/// `trimPropertiesToFitSize` algorithm. Returns `None` when the value
/// already fits (no trimming needed) — and also when trimming every
/// non-protected property still cannot fit, which callers distinguish by
/// re-checking the size; see `TrimResult` for the ergonomic wrapper.
pub enum TrimResult {
    /// Already within the target; nothing to do.
    Fits,
    /// Trimming non-protected properties got it under the target.
    Trimmed(Value),
    /// Protected properties alone exceed the target; nothing to trim.
    CannotFit,
}

pub fn trim_properties_to_fit_size(properties: &Value, target_bytes: usize) -> TrimResult {
    if jsonb_column_size(properties) <= target_bytes {
        return TrimResult::Fits;
    }
    let Some(map) = properties.as_object() else {
        return TrimResult::CannotFit;
    };

    let mut trimmed = map.clone();
    let mut keys: Vec<String> = map.keys().cloned().collect();
    keys.sort();

    for key in keys {
        if !can_trim_property(&key) {
            continue;
        }
        trimmed.remove(&key);
        if jsonb_column_size(&Value::Object(trimmed.clone())) <= target_bytes {
            return TrimResult::Trimmed(Value::Object(trimmed));
        }
    }

    TrimResult::CannotFit
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn protected_properties_are_not_trimmable() {
        assert!(!can_trim_property("email"));
        assert!(!can_trim_property("$browser"));
        assert!(!can_trim_property("utm_source"));
        assert!(!can_trim_property("$user_id"));
        assert!(!can_trim_property("$initial_referrer"));
        assert!(can_trim_property("custom_field"));
    }

    #[test]
    fn empty_containers_have_known_jsonb_sizes() {
        // varlena header (4) + container header (4).
        assert_eq!(jsonb_column_size(&json!({})), 8);
        assert_eq!(jsonb_column_size(&json!([])), 8);
    }

    #[test]
    fn trim_removes_custom_properties_alphabetically() {
        let target = 1024;
        let mut map = serde_json::Map::new();
        map.insert("email".to_string(), json!("test@example.com"));
        map.insert("$browser".to_string(), json!("Chrome"));
        let big_value = "x".repeat(500);
        map.insert("aaa_custom".to_string(), json!(big_value.clone()));
        map.insert("bbb_custom".to_string(), json!(big_value.clone()));
        map.insert("ccc_custom".to_string(), json!(big_value));

        match trim_properties_to_fit_size(&Value::Object(map), target) {
            TrimResult::Trimmed(trimmed) => {
                let trimmed = trimmed.as_object().unwrap();
                assert!(trimmed.contains_key("email"));
                assert!(trimmed.contains_key("$browser"));
                assert!(!trimmed.contains_key("aaa_custom"));
            }
            _ => panic!("expected a trim"),
        }
    }

    #[test]
    fn trim_reports_fits_and_cannot_fit() {
        let small = json!({"email": "a@b.c"});
        assert!(matches!(
            trim_properties_to_fit_size(&small, 1024),
            TrimResult::Fits
        ));

        let protected_oversized = json!({"email": "x".repeat(2_000)});
        assert!(matches!(
            trim_properties_to_fit_size(&protected_oversized, 1024),
            TrimResult::CannotFit
        ));
    }

    #[test]
    fn sanitize_replaces_nul_in_values_keys_and_nested_structures() {
        let mut value = serde_json::json!({
            "clean": "ok",
            "bad\u{0000}key": "still\u{0000}bad",
            "nested": {"inner": ["a\u{0000}b", 1, null]},
        });
        let stats = sanitize_for_jsonb(&mut value);
        assert_eq!(stats.nul_strings, 3);
        let map = value.as_object().unwrap();
        assert_eq!(map["bad\u{FFFD}key"], "still\u{FFFD}bad");
        assert_eq!(map["nested"]["inner"][0], "a\u{FFFD}b");
        assert_eq!(map["clean"], "ok");
    }

    #[test]
    fn sanitize_clamps_floats_beyond_the_safe_magnitude() {
        let mut value = serde_json::json!({
            "huge": 1.7976931348623157e308,
            "neg_huge": [-1.5e308],
            "fine": 1e306,
            "int": u64::MAX,
        });
        let stats = sanitize_for_jsonb(&mut value);
        assert_eq!(stats.clamped_numbers, 2);
        assert_eq!(value["huge"], 1e307);
        assert_eq!(value["neg_huge"][0], -1e307);
        assert_eq!(value["fine"], 1e306);
        assert_eq!(value["int"], u64::MAX);
    }

    #[test]
    fn sanitize_leaves_clean_values_untouched() {
        let mut value = serde_json::json!({"a": "b", "n": [1, 2.5, "x"]});
        let before = value.clone();
        assert!(!sanitize_for_jsonb(&mut value).changed());
        assert_eq!(value, before);
    }
}
