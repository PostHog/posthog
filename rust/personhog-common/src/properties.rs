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

/// Rewrite number tokens that serde_json refuses so the document parses,
/// mimicking `JSON.parse`'s rounding. Postgres renders jsonb numerics in
/// expanded decimal (never e-notation), and serde_json rejects expansions
/// near `f64::MAX` even when the value itself is representable — while
/// every JS consumer reads the same bytes fine, because `JSON.parse`
/// rounds to the nearest double instead of erroring. Legacy and
/// Node-written rows can therefore hold numerics the leader's strict
/// parser chokes on.
///
/// Tokens serde_json accepts are copied verbatim (no precision change);
/// rejected tokens whose value fits a double are rewritten to its
/// shortest representation — the exact value `JSON.parse` yields — and
/// magnitudes beyond `f64::MAX` (unreachable from JS; Python bigints and
/// raw SQL) are clamped to ±[`MAX_JSONB_SAFE_MAGNITUDE`], where today's
/// pipeline reads `Infinity` and rewrites it as `null`. String content is
/// copied verbatim, so digits inside strings are never touched. Intended
/// for the rare failure path only: callers parse normally first and
/// rewrite only when that fails.
pub fn rewrite_out_of_range_numbers(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = String::with_capacity(text.len());
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'"' => {
                // Copy the whole string token verbatim, escape-aware.
                let start = i;
                i += 1;
                while i < bytes.len() {
                    match bytes[i] {
                        b'\\' => i = (i + 2).min(bytes.len()),
                        b'"' => {
                            i += 1;
                            break;
                        }
                        _ => i += 1,
                    }
                }
                out.push_str(&text[start..i]);
            }
            b'-' | b'0'..=b'9' => {
                let start = i;
                while i < bytes.len()
                    && matches!(bytes[i], b'0'..=b'9' | b'.' | b'e' | b'E' | b'+' | b'-')
                {
                    i += 1;
                }
                let token = &text[start..i];
                if token.parse::<serde_json::Number>().is_ok() {
                    out.push_str(token);
                } else {
                    match token.parse::<f64>() {
                        // std's parser rounds to nearest like JSON.parse,
                        // so a finite result is the double JS reads.
                        Ok(f) if f.is_finite() => out.push_str(
                            &serde_json::Number::from_f64(f)
                                .expect("finite float converts")
                                .to_string(),
                        ),
                        _ => {
                            let sign = if token.starts_with('-') { "-" } else { "" };
                            out.push_str(&format!("{sign}{MAX_JSONB_SAFE_MAGNITUDE:e}"));
                        }
                    }
                }
            }
            _ => {
                // Structural bytes and whitespace; non-ASCII only occurs
                // inside strings, which the arm above copies as slices.
                let start = i;
                while i < bytes.len() && !matches!(bytes[i], b'"' | b'-' | b'0'..=b'9') {
                    i += 1;
                }
                out.push_str(&text[start..i]);
            }
        }
    }
    out
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
/// 7-bit signed weight; it fits when dscale <= 63 and weight is in
/// [-64, 63] base-10000 units (NUMERIC_SHORT_WEIGHT_MIN/MAX in numeric.c).
fn short_header_fits(weight: i32, dscale: u32) -> bool {
    dscale <= 0x3F && (-64..=63).contains(&weight)
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
    let mut current = jsonb_column_size(properties);
    if current <= target_bytes {
        return TrimResult::Fits;
    }
    let Some(map) = properties.as_object() else {
        return TrimResult::CannotFit;
    };

    // Removal runs in batches sized by each pair's estimated contribution
    // (two 4-byte JEntries, the key bytes, and the value's content measured
    // at offset 0), with one exact re-measure per batch. Alignment padding
    // makes per-pair contributions position-dependent, so the estimate can
    // be off by a few bytes per numeric — the re-measure keeps the result
    // exact and the deficit shrinks geometrically, bounding the total cost
    // at O(document) per pass for a handful of passes. This can remove a
    // key or two more than the strict minimum in padding-heavy edge cases.
    // Removal order stays alphabetical, matching the pipeline's trim.
    let mut trimmed = map.clone();
    let mut candidates: Vec<String> = map
        .keys()
        .filter(|k| can_trim_property(k))
        .cloned()
        .collect();
    candidates.sort();
    let mut candidates = candidates.into_iter();

    while current > target_bytes {
        let deficit = current - target_bytes;
        let mut estimated_freed = 0usize;
        let mut removed_any = false;
        for key in candidates.by_ref() {
            let Some(value) = trimmed.remove(&key) else {
                continue;
            };
            estimated_freed += 8 + key.len() + element_size(&value, 0);
            removed_any = true;
            if estimated_freed >= deficit {
                break;
            }
        }
        if !removed_any {
            return TrimResult::CannotFit;
        }
        // Measure the map without cloning it: wrap, measure, unwrap.
        let wrapped = Value::Object(std::mem::take(&mut trimmed));
        current = jsonb_column_size(&wrapped);
        let Value::Object(unwrapped) = wrapped else {
            unreachable!("wrapped as an object above");
        };
        trimmed = unwrapped;
    }

    TrimResult::Trimmed(Value::Object(trimmed))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn trim_of_many_small_keys_is_not_quadratic() {
        // ~1.3MB document of 20k tiny trimmable keys plus protected state.
        // The former per-removal clone-and-remeasure loop needs billions of
        // operations here and effectively never finishes in a debug build;
        // the batched trim completes in well under a second. Completion IS
        // the assertion of linearity; correctness is asserted on the result.
        let mut map = serde_json::Map::new();
        map.insert("email".to_string(), json!("keep@example.com"));
        for i in 0..20_000 {
            map.insert(format!("k{i:05}"), json!("v".repeat(40)));
        }
        let value = Value::Object(map);
        let TrimResult::Trimmed(trimmed) = trim_properties_to_fit_size(&value, 524_288) else {
            panic!("a document of trimmable keys must trim");
        };
        assert!(jsonb_column_size(&trimmed) <= 524_288);
        assert_eq!(trimmed["email"], "keep@example.com");
    }

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

    /// PG's expanded rendering of JS `Number.MAX_VALUE`: the mantissa
    /// digits followed by 292 zeros — serde_json rejects it, JSON.parse
    /// rounds it to exactly `f64::MAX`.
    fn max_value_expansion() -> String {
        format!("17976931348623157{}", "0".repeat(292))
    }

    #[test]
    fn rewrite_rounds_representable_expansions_to_the_double_js_reads() {
        let text = format!("{{\"x\": {}}}", max_value_expansion());
        assert!(serde_json::from_str::<Value>(&text).is_err());
        let parsed: Value = serde_json::from_str(&rewrite_out_of_range_numbers(&text)).unwrap();
        assert_eq!(parsed["x"].as_f64().unwrap(), f64::MAX);
    }

    #[test]
    fn rewrite_clamps_beyond_f64_preserving_sign() {
        // 2e308 and a Python-bigint-scale integer, positive and negative.
        let text = format!(
            "{{\"a\": 2{z308}, \"b\": -2{z308}, \"c\": 1{z400}}}",
            z308 = "0".repeat(308),
            z400 = "0".repeat(400),
        );
        assert!(serde_json::from_str::<Value>(&text).is_err());
        let parsed: Value = serde_json::from_str(&rewrite_out_of_range_numbers(&text)).unwrap();
        assert_eq!(parsed["a"].as_f64().unwrap(), MAX_JSONB_SAFE_MAGNITUDE);
        assert_eq!(parsed["b"].as_f64().unwrap(), -MAX_JSONB_SAFE_MAGNITUDE);
        assert_eq!(parsed["c"].as_f64().unwrap(), MAX_JSONB_SAFE_MAGNITUDE);
    }

    #[test]
    fn rewrite_never_touches_strings_or_parseable_numbers() {
        // Digit runs inside strings — including one shaped exactly like
        // an offending token, behind an escaped quote — plus in-range
        // numbers, must all pass through byte-identical.
        let text = format!(
            "{{\"note\": \"big: 2{z}\", \"esc\": \"say \\\"1{z}\\\" loud\", \
             \"n\": 1e307, \"tiny\": 0.000123, \"neg\": -42}}",
            z = "0".repeat(308),
        );
        assert_eq!(rewrite_out_of_range_numbers(&text), text);
    }

    #[test]
    fn rewrite_output_reparses_for_every_probe_shape() {
        // The PG probe fixtures that motivated the rewriter, as one doc.
        let text = format!(
            "[{max}, 2{z308}, 1{z400}, 1e-308, 0.5, \"x\"]",
            max = max_value_expansion(),
            z308 = "0".repeat(308),
            z400 = "0".repeat(400),
        );
        let parsed: Value = serde_json::from_str(&rewrite_out_of_range_numbers(&text)).unwrap();
        let items = parsed.as_array().unwrap();
        assert_eq!(items[0].as_f64().unwrap(), f64::MAX);
        assert_eq!(items[1].as_f64().unwrap(), MAX_JSONB_SAFE_MAGNITUDE);
        assert_eq!(items[2].as_f64().unwrap(), MAX_JSONB_SAFE_MAGNITUDE);
        assert_eq!(items[3].as_f64().unwrap(), 1e-308);
        assert_eq!(items[4].as_f64().unwrap(), 0.5);
        assert_eq!(items[5], "x");
    }
}
