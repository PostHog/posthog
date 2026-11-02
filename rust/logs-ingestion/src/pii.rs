//! Port of `nodejs/src/logs/log-pii-scrub.ts`: the lossy redaction of secrets and emails in
//! `body` and in each `attributes` value.
//!
//! Node runs these rules with RE2 (`createTrackedRE2`), not with the JavaScript regex engine.
//! `translate_re2` gives the Rust `regex` crate the same semantics. See its comment.

use std::sync::LazyLock;

use regex::Regex;

use crate::avro::{AvroMap, AvroValue};
use crate::js::{json_stringify, JsValue};
use crate::record::LogRecord;

pub const PII_REDACTED: &str = "{{REDACTED}}";

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct PiiScrubStats {
    pub pii_replacements: u64,
}

pub const EMPTY_PII: PiiScrubStats = PiiScrubStats {
    pii_replacements: 0,
};

/// `encodeAttributeCell`: `JSON.stringify(semantic)`.
pub fn encode_attribute_cell(semantic: &str) -> String {
    json_stringify(&JsValue::string(semantic))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PiiRule {
    pub name: &'static str,
    /// The pattern text exactly as the TypeScript gives it to RE2.
    pub pattern: &'static str,
    pub replacement: &'static str,
}

/// One capture group per rule, in this order. The scrub loop reads the fired rule from the group
/// index, and the earlier alternative wins a tie at one offset.
pub const PII_RULES: [PiiRule; 7] = [
    PiiRule {
        name: "bearer",
        pattern: r"(?i:Bearer\s+[-A-Za-z0-9._~+/]+=*)",
        replacement: "Bearer {{REDACTED}}",
    },
    PiiRule {
        name: "stripe",
        pattern: r"\bsk_(?:live|test)_[a-zA-Z0-9]{20,}\b",
        replacement: PII_REDACTED,
    },
    PiiRule {
        name: "github",
        pattern: r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
        replacement: PII_REDACTED,
    },
    PiiRule {
        name: "slack",
        pattern: r"\bxox[abeprs]-[A-Za-z0-9-]{10,}\b",
        replacement: PII_REDACTED,
    },
    PiiRule {
        name: "aws_access_key_id",
        pattern: r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
        replacement: PII_REDACTED,
    },
    PiiRule {
        name: "jwt",
        pattern: r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*",
        replacement: PII_REDACTED,
    },
    PiiRule {
        name: "email",
        pattern: r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        replacement: PII_REDACTED,
    },
];

/// Rewrites an RE2 pattern so that the `regex` crate matches the same text.
///
/// Both engines use leftmost-first alternation, so only the character classes differ.
/// node-re2 matches in UTF-8 mode, and RE2 keeps its Perl classes ASCII there:
/// - `\d` is `[0-9]`, and `\w` is `[0-9A-Za-z_]`.
/// - `\s` is `[\t\n\f\r ]`. It excludes `\v`, which the `regex` crate's ASCII `\s` includes.
/// - `\b` is an ASCII word boundary, so a non-ASCII letter is a non-word character.
///
/// `(?i:` keeps Unicode simple case folding in both engines. For example, `(?i:[a-z])` also
/// matches U+017F and U+212A. The `regex` crate does the same in its default Unicode mode.
///
/// The rules use none of these escapes inside a bracket class, so the rewrite does not
/// track classes. A test checks the class membership against values recorded from node-re2.
pub fn translate_re2(pattern: &str) -> String {
    let mut out = String::with_capacity(pattern.len() + 16);
    let mut chars = pattern.chars();
    while let Some(c) = chars.next() {
        if c != '\\' {
            out.push(c);
            continue;
        }
        match chars.next() {
            Some('d') => out.push_str("[0-9]"),
            Some('w') => out.push_str("[0-9A-Za-z_]"),
            Some('s') => out.push_str(r"[\t\n\f\r ]"),
            Some('b') => out.push_str(r"(?-u:\b)"),
            Some(other) => {
                out.push('\\');
                out.push(other);
            }
            None => out.push('\\'),
        }
    }
    out
}

/// Joins the rules as `(p1)|(p2)|...`, as the TypeScript does for its combined regex.
pub fn combined_regex(patterns: impl IntoIterator<Item = &'static str>) -> Regex {
    let joined = patterns
        .into_iter()
        .map(|p| format!("({})", translate_re2(p)))
        .collect::<Vec<_>>()
        .join("|");
    regex::RegexBuilder::new(&joined)
        .size_limit(64 << 20)
        .dfa_size_limit(64 << 20)
        .build()
        .expect("combined rule regex compiles")
}

static PII_COMBINED_RE: LazyLock<Regex> =
    LazyLock::new(|| combined_regex(PII_RULES.iter().map(|r| r.pattern)));

/// `scrubPlainStringWithStats`: one pass over the string. The count includes only matches
/// that a rule group claims.
///
/// The TypeScript skips an empty match, but no rule can match an empty string.
pub fn scrub_plain_string_with_stats(input: &str) -> (String, u64) {
    let mut replacements = 0u64;
    let mut out: Option<String> = None;
    let mut copied_up_to = 0;
    for caps in PII_COMBINED_RE.captures_iter(input) {
        let whole = caps.get(0).expect("group 0 is always set");
        if whole.is_empty() {
            continue;
        }
        let Some(rule) = (0..PII_RULES.len()).find(|&i| caps.get(i + 1).is_some()) else {
            continue;
        };
        replacements += 1;
        let buf = out.get_or_insert_with(|| String::with_capacity(input.len()));
        buf.push_str(&input[copied_up_to..whole.start()]);
        buf.push_str(PII_RULES[rule].replacement);
        copied_up_to = whole.end();
    }
    match out {
        None => (input.to_string(), replacements),
        Some(mut buf) => {
            buf.push_str(&input[copied_up_to..]);
            (buf, replacements)
        }
    }
}

/// `scrubPlainString`.
pub fn scrub_plain_string(input: &str) -> String {
    scrub_plain_string_with_stats(input).0
}

/// `scrubLogRecord`: scrubs `body` and each `attributes` value in place.
///
/// Decoded record strings are valid UTF-8, because the Avro decoder writes U+FFFD for invalid
/// bytes. So this port does not need the lone-surrogate handling of `JsString`.
pub fn scrub_log_record(record: &mut LogRecord) -> PiiScrubStats {
    let mut total = 0u64;

    if let Some(body) = record.body() {
        let (output, n) = scrub_plain_string_with_stats(body);
        total += n;
        if n > 0 {
            record.set("body", AvroValue::String(output));
        }
    }

    if let Some(attributes) = record.attributes_mut() {
        let mut changed = false;
        let mut scrubbed = AvroMap::new();
        for (key, value) in attributes.iter() {
            let value = match value {
                AvroValue::String(s) => {
                    let (output, n) = scrub_plain_string_with_stats(s);
                    total += n;
                    changed |= n > 0;
                    AvroValue::String(output)
                }
                other => other.clone(),
            };
            // `define` keeps the key order, because the keys arrive in the map's own order.
            scrubbed.define(key.to_string(), value);
        }
        if changed {
            *attributes = scrubbed;
        }
    }

    PiiScrubStats {
        pii_replacements: total,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn members(pattern: &str, range: std::ops::Range<u32>) -> Vec<u32> {
        let re = Regex::new(&format!("^(?:{})$", translate_re2(pattern))).unwrap();
        let mut buf = [0u8; 4];
        range
            .filter_map(char::from_u32)
            .filter(|c| re.is_match(c.encode_utf8(&mut buf)))
            .map(|c| c as u32)
            .collect()
    }

    fn non_ascii_members(pattern: &str) -> Vec<u32> {
        members(pattern, 0x80..0x110000)
    }

    /// node-re2 1.22.1 gives these memberships when it enumerates every code point.
    /// `(?i:[-A-Za-z0-9._~+/])` adds U+017F and U+212A, `\s` is five ASCII characters, and
    /// `\d`, `\w` and `[Bbear]` under `(?i:` add nothing outside ASCII.
    #[test]
    fn class_membership_matches_node_re2() {
        assert_eq!(non_ascii_members("(?i:[-A-Za-z0-9._~+/])"), [0x17F, 0x212A]);
        assert!(non_ascii_members(r"(?i:[Bbear])").is_empty());
        assert!(non_ascii_members(r"\d").is_empty());
        assert!(non_ascii_members(r"\w").is_empty());
        assert!(non_ascii_members(r"\s").is_empty());
        let ascii_space = members(r"\s", 0..0x80);
        assert_eq!(ascii_space, [0x09, 0x0A, 0x0C, 0x0D, 0x20]);
    }

    /// Node gives `X` for `'bearer \u212Aabc'`, `'éX Xé'` for `\bab\b` on `'éab abé'`, and keeps
    /// `'Bearer\vab'` unchanged.
    #[test]
    fn re2_edge_cases_match_node() {
        assert_eq!(
            scrub_plain_string("bearer \u{212A}abc").as_str(),
            "Bearer {{REDACTED}}"
        );
        assert_eq!(scrub_plain_string("Bearer\u{000B}ab"), "Bearer\u{000B}ab");
        let re = Regex::new(&translate_re2(r"\bab\b")).unwrap();
        assert_eq!(re.replace_all("éab abé", "X"), "éX Xé");
    }
}
