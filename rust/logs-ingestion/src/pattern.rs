//! Port of `nodejs/src/logs/log-pattern-mask.ts` and the stamping in `log-pattern-stage.ts`.
//!
//! The masking regexes run on RE2 in Node. `pii::translate_re2` gives them the same semantics.
//!
//! node-re2's `String.prototype.replace` rebuilds the result from UTF-8, so it writes each lone
//! surrogate as U+FFFD, also when no rule matches. Node gives `'x\ud800'.replace(re, f)` as
//! `'x�'`. Thus every masked string is valid UTF-8, and this port masks the lossy UTF-8 form
//! of its input. Lengths agree, because U+FFFD and a lone surrogate are both one UTF-16 unit.

use std::borrow::Cow;
use std::sync::LazyLock;
use std::time::Instant;

use metrics::{counter, histogram};

use crate::js::{json_parse_shape, utf16_len, utf16_slice_lossy, JsString, JsonShape};
use crate::pii::RuleRegex;
use crate::record::LogRecord;

pub const PATTERN_VERSION: i64 = 6;

/// `PATTERN_CAPS`. Both caps count UTF-16 units.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PatternCaps {
    pub max_input_chars: usize,
    pub max_output_chars: usize,
}

pub const PATTERN_CAPS: PatternCaps = PatternCaps {
    max_input_chars: 8192,
    max_output_chars: 1024,
};

pub const JSON_ARRAY: &str = "<JSON_ARRAY>";
pub const KEY_SET_MAX_KEYS: usize = 32;
pub const MESSAGE_KEYS: [&str; 3] = ["message", "msg", "event"];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MaskRule {
    pub name: &'static str,
    /// The pattern text exactly as the TypeScript builds it for RE2.
    pub pattern: &'static str,
    pub replacement: &'static str,
}

// The TypeScript builds these from the MONTH, WEEKDAY, DAY_OF_MONTH, TIME_OF_DAY, YEAR and ZONE
// fragments. The text here is that expansion. A test in this file rebuilds it from the fragments.
#[cfg(test)]
const MONTH: &str = "(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)";
#[cfg(test)]
const WEEKDAY: &str = "(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)";
#[cfg(test)]
const DAY_OF_MONTH: &str = r"(?:0?[1-9]|[12]\d|3[01])";
#[cfg(test)]
const TIME_OF_DAY: &str = r"\d{2}:\d{2}:\d{2}";
#[cfg(test)]
const YEAR: &str = r"(?:19|20)\d{2}";
#[cfg(test)]
const ZONE: &str = "(?:UT|UTC|GMT|Z|E[SD]T|C[SD]T|M[SD]T|P[SD]T|AK[SD]T|H[SD]T|A[SD]T|N[SD]T|CES?T|EES?T|WES?T|BST|IST|MSK|JST|KST|HKT|SGT|ICT|AE[SD]T|AC[SD]T|AWST|NZ[SD]T|SAST|WAT|CAT|EAT|BRT|ART|GST|PKT)";

macro_rules! klog_rule {
    ($letter:literal) => {
        MaskRule {
            name: "klogtime",
            pattern: concat!(
                r"\b",
                $letter,
                r"(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]) \d{2}:\d{2}:\d{2}(?:\.\d+)?"
            ),
            replacement: concat!($letter, "<KLOGTIME>"),
        }
    };
}

pub const MASK_RULES: [MaskRule; 22] = [
    MaskRule {
        name: "timestamp",
        pattern: r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?",
        replacement: "<TIMESTAMP>",
    },
    klog_rule!("I"),
    klog_rule!("W"),
    klog_rule!("E"),
    klog_rule!("F"),
    MaskRule {
        name: "clftime",
        pattern: r"\b\d{2}/(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/(?:19|20)\d{2}:\d{2}:\d{2}:\d{2}(?: [+-]\d{4})?",
        replacement: "<TIMESTAMP>",
    },
    MaskRule {
        name: "ctime",
        pattern: r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) {1,2}(?:0?[1-9]|[12]\d|3[01]) \d{2}:\d{2}:\d{2}(?: (?:UT|UTC|GMT|Z|E[SD]T|C[SD]T|M[SD]T|P[SD]T|AK[SD]T|H[SD]T|A[SD]T|N[SD]T|CES?T|EES?T|WES?T|BST|IST|MSK|JST|KST|HKT|SGT|ICT|AE[SD]T|AC[SD]T|AWST|NZ[SD]T|SAST|WAT|CAT|EAT|BRT|ART|GST|PKT))? (?:19|20)\d{2}",
        replacement: "<TIMESTAMP>",
    },
    MaskRule {
        name: "httpdate",
        pattern: r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), (?:0?[1-9]|[12]\d|3[01]) (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (?:19|20)\d{2} \d{2}:\d{2}:\d{2}(?: GMT| UTC| [+-]\d{4})?",
        replacement: "<TIMESTAMP>",
    },
    MaskRule {
        name: "syslogtime",
        pattern: r"\b(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) )?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) {1,2}(?:0?[1-9]|[12]\d|3[01]) \d{2}:\d{2}:\d{2}",
        replacement: "<TIMESTAMP>",
    },
    MaskRule {
        name: "email",
        pattern: r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        replacement: "<EMAIL>",
    },
    MaskRule {
        name: "id",
        pattern: r"\b[a-z]{2,10}_(?:[A-Za-z0-9]*[A-Z][A-Za-z0-9]*[0-9]|[A-Za-z0-9]*[0-9][A-Za-z0-9]*[A-Z])[A-Za-z0-9]*(?:-[A-Za-z0-9]+)*",
        replacement: "<ID>",
    },
    MaskRule {
        name: "stripeid",
        pattern: r"\b(?:cus|sub)_[A-Z][A-Za-z]{13}(?:[A-Za-z]{10})?\b",
        replacement: "<ID>",
    },
    MaskRule {
        name: "snakeuuid",
        pattern: r"_\d{4,}(?:_\d+)*_[0-9a-fA-F]*[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        replacement: "_<N>_<UUID>",
    },
    MaskRule {
        name: "snakeuuid",
        pattern: r"_[0-9a-fA-F]*[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        replacement: "_<UUID>",
    },
    MaskRule {
        name: "uuid",
        pattern: r"[0-9a-fA-F]*[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        replacement: "<UUID>",
    },
    MaskRule {
        name: "snakenum",
        pattern: r"_\d{4,}(?:_\d+)*\b",
        replacement: "_<N>",
    },
    MaskRule {
        name: "host",
        pattern: r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.){1,8}(?:ai|app|aws|bot|cloud|co|com|de|dev|eu|fr|gg|internal|io|jp|local|me|net|nl|org|tv|uk|us|xyz)\b",
        replacement: "<HOST>",
    },
    MaskRule {
        name: "hex0x",
        pattern: r"\b0x[0-9a-fA-F]+\b",
        replacement: "<HEX>",
    },
    MaskRule {
        name: "ipv4",
        pattern: r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
        replacement: "<IP>",
    },
    MaskRule {
        name: "num",
        pattern: r"\b\d+\b",
        replacement: "<N>",
    },
    MaskRule {
        name: "hex",
        pattern: r"\b[0-9a-fA-F]{8,}\b",
        replacement: "<HEX>",
    },
    MaskRule {
        name: "num",
        pattern: r"\b\d+",
        replacement: "<N>",
    },
];

static MASK_RULE_RE: LazyLock<RuleRegex> =
    LazyLock::new(|| RuleRegex::new(MASK_RULES.iter().map(|r| r.pattern)));

pub type RuleFires = [u64; MASK_RULES.len()];

fn mask_into(input: &str, rule_fires: &mut RuleFires) -> String {
    let mut out = String::with_capacity(input.len());
    let mut copied_up_to = 0;
    for (start, end, rule) in MASK_RULE_RE.matches(input) {
        rule_fires[rule] += 1;
        out.push_str(&input[copied_up_to..start]);
        out.push_str(MASK_RULES[rule].replacement);
        copied_up_to = end;
    }
    out.push_str(&input[copied_up_to..]);
    out
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MaskResult {
    pub masked: String,
    pub rule_fires: RuleFires,
}

pub fn mask_string(input: &str) -> MaskResult {
    let mut rule_fires = [0; MASK_RULES.len()];
    let masked = mask_into(input, &mut rule_fires);
    MaskResult { masked, rule_fires }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PatternBodyKind {
    Empty,
    Plaintext,
    JsonObjectOrArray,
    JsonString,
    Primitive,
}

impl PatternBodyKind {
    pub fn as_str(self) -> &'static str {
        match self {
            PatternBodyKind::Empty => "empty",
            PatternBodyKind::Plaintext => "plaintext",
            PatternBodyKind::JsonObjectOrArray => "json_object_or_array",
            PatternBodyKind::JsonString => "json_string",
            PatternBodyKind::Primitive => "primitive",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LogPatternResult {
    pub pattern: String,
    pub body_kind: PatternBodyKind,
    pub input_capped: bool,
    /// UTF-16 length of the pattern before the output cap.
    pub masked_length: usize,
    pub json_key_count: Option<usize>,
    pub rule_fires: RuleFires,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PatternInputSelection {
    Empty {
        body_kind: PatternBodyKind,
        input_capped: bool,
    },
    Mask {
        input: String,
        body_kind: PatternBodyKind,
        input_capped: bool,
    },
    Pattern {
        pattern: String,
        body_kind: PatternBodyKind,
        input_capped: bool,
        rule_fires: RuleFires,
        json_key_count: Option<usize>,
    },
}

fn cap_output(pattern: &str) -> String {
    if utf16_len(pattern) > PATTERN_CAPS.max_output_chars {
        utf16_slice_lossy(pattern, 0, PATTERN_CAPS.max_output_chars)
    } else {
        pattern.to_string()
    }
}

fn utf16_order(a: &str, b: &str) -> std::cmp::Ordering {
    if a.is_ascii() && b.is_ascii() {
        a.cmp(b)
    } else {
        a.encode_utf16().cmp(b.encode_utf16())
    }
}

/// `jsonKeySetPattern`: masks each key, dedupes, then sorts by UTF-16 units. Sorting first and
/// then dropping repeats gives the same list as the TypeScript's dedupe in insertion order.
fn json_key_set_pattern(raw_keys: impl Iterator<Item = String>) -> (String, RuleFires) {
    let mut rule_fires = [0; MASK_RULES.len()];
    let mut keys: Vec<String> = raw_keys
        .map(|key| mask_into(&key, &mut rule_fires))
        .collect();
    keys.sort_by(|a, b| utf16_order(a, b));
    keys.dedup();
    let kept = keys.len().min(KEY_SET_MAX_KEYS);
    let overflow = keys.len() - kept;
    let mut pattern = format!("<JSON:{}", keys[..kept].join(","));
    if overflow > 0 {
        pattern.push_str(&format!(",+{overflow}"));
    }
    pattern.push('>');
    (pattern, rule_fires)
}

pub fn select_pattern_input(body: Option<&str>, message_keys: &[&str]) -> PatternInputSelection {
    let body = match body {
        None | Some("") => {
            return PatternInputSelection::Empty {
                body_kind: PatternBodyKind::Empty,
                input_capped: false,
            }
        }
        Some(body) => body,
    };

    let input_capped = utf16_len(body) > PATTERN_CAPS.max_input_chars;
    // A cut through a surrogate pair leaves a lone high surrogate at the end. That text is
    // never valid JSON, and the mask writes it as U+FFFD, so the lossy slice gives the same result.
    let capped_body: Cow<'_, str> = if input_capped {
        Cow::Owned(utf16_slice_lossy(body, 0, PATTERN_CAPS.max_input_chars))
    } else {
        Cow::Borrowed(body)
    };
    // `parseLogBodyForIngestion`, reading only what the selection needs.
    let shape = json_parse_shape(&capped_body, |key| message_keys.iter().any(|m| *key == *m));
    let mask = |input: String, body_kind| PatternInputSelection::Mask {
        input,
        body_kind,
        input_capped,
    };

    match shape {
        Err(_) => mask(capped_body.into_owned(), PatternBodyKind::Plaintext),
        Ok(JsonShape::Primitive) => mask(capped_body.into_owned(), PatternBodyKind::Primitive),
        Ok(JsonShape::String(value)) => mask(
            value.to_utf8_lossy().into_owned(),
            PatternBodyKind::JsonString,
        ),
        Ok(JsonShape::Array) => PatternInputSelection::Pattern {
            pattern: JSON_ARRAY.to_string(),
            body_kind: PatternBodyKind::JsonObjectOrArray,
            input_capped,
            rule_fires: [0; MASK_RULES.len()],
            json_key_count: None,
        },
        Ok(JsonShape::Object(entries)) => {
            // `extractJsonMessage`: the first message key whose value is a string. A repeated
            // key holds its last value. A key lookup in JavaScript also reads
            // `Object.prototype`, but no inherited property there is a string.
            let message = message_keys.iter().find_map(|key| {
                match entries.iter().rev().find(|(k, _)| *k == **key) {
                    Some((_, Some(value))) => Some(value.to_utf8_lossy().into_owned()),
                    _ => None,
                }
            });
            if let Some(message) = message {
                return mask(message, PatternBodyKind::JsonObjectOrArray);
            }
            let mut keys: Vec<&JsString> = entries.iter().map(|(k, _)| k).collect();
            keys.sort_unstable_by(|a, b| a.bytes_wtf8().cmp(b.bytes_wtf8()));
            keys.dedup();
            let (pattern, rule_fires) =
                json_key_set_pattern(keys.iter().map(|k| k.to_utf8_lossy().into_owned()));
            PatternInputSelection::Pattern {
                pattern,
                body_kind: PatternBodyKind::JsonObjectOrArray,
                input_capped,
                rule_fires,
                json_key_count: Some(keys.len()),
            }
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MaskedPattern {
    pub pattern: String,
    pub masked_length: usize,
    pub rule_fires: RuleFires,
}

pub fn compute_log_pattern(input: &str) -> MaskedPattern {
    let MaskResult { masked, rule_fires } = mask_string(input);
    MaskedPattern {
        pattern: cap_output(&masked),
        masked_length: utf16_len(&masked),
        rule_fires,
    }
}

pub fn build_log_pattern(body: Option<&str>, message_keys: &[&str]) -> LogPatternResult {
    match select_pattern_input(body, message_keys) {
        PatternInputSelection::Empty {
            body_kind,
            input_capped,
        } => LogPatternResult {
            pattern: String::new(),
            body_kind,
            input_capped,
            masked_length: 0,
            json_key_count: None,
            rule_fires: [0; MASK_RULES.len()],
        },
        PatternInputSelection::Pattern {
            pattern,
            body_kind,
            input_capped,
            rule_fires,
            json_key_count,
        } => LogPatternResult {
            masked_length: utf16_len(&pattern),
            pattern: cap_output(&pattern),
            body_kind,
            input_capped,
            json_key_count,
            rule_fires,
        },
        PatternInputSelection::Mask {
            input,
            body_kind,
            input_capped,
        } => {
            let masked = compute_log_pattern(&input);
            LogPatternResult {
                pattern: masked.pattern,
                body_kind,
                input_capped,
                masked_length: masked.masked_length,
                json_key_count: None,
                rule_fires: masked.rule_fires,
            }
        }
    }
}

/// The TypeScript catches a throw and counts `logs_ingestion_pattern_stage_error_total`. Nothing
/// here can fail, so this port has no such path.
pub fn stamp_pattern_batch(records: &mut [LogRecord], message_keys: &[&str]) {
    let mut kind_counts: Vec<(PatternBodyKind, u64)> = Vec::new();
    let mut rule_fires = [0u64; MASK_RULES.len()];
    let mut input_capped = 0u64;

    for record in records.iter_mut() {
        let start = Instant::now();
        let result = build_log_pattern(record.body(), message_keys);
        record.set_pattern(result.pattern, PATTERN_VERSION);
        histogram!("logs_ingestion_pattern_masking_duration_seconds")
            .record(start.elapsed().as_secs_f64());

        histogram!("logs_ingestion_pattern_masked_length_chars")
            .record(result.masked_length as f64);
        if let Some(count) = result.json_key_count {
            histogram!("logs_ingestion_pattern_keyset_keys").record(count as f64);
        }
        match kind_counts.iter_mut().find(|(k, _)| *k == result.body_kind) {
            Some((_, n)) => *n += 1,
            None => kind_counts.push((result.body_kind, 1)),
        }
        for (total, fires) in rule_fires.iter_mut().zip(result.rule_fires) {
            *total += fires;
        }
        if result.input_capped {
            input_capped += 1;
        }
    }

    for (kind, count) in kind_counts {
        counter!("logs_ingestion_pattern_body_kind_total", "kind" => kind.as_str())
            .increment(count);
    }
    for (rule, fires) in MASK_RULES.iter().zip(rule_fires) {
        if fires > 0 {
            counter!("logs_ingestion_pattern_rule_fired_total", "rule" => rule.name)
                .increment(fires);
        }
    }
    if input_capped > 0 {
        counter!("logs_ingestion_pattern_input_capped_total").increment(input_capped);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rule_text_matches_the_typescript_fragments() {
        let klog = |l: &str| {
            format!(r"\b{l}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]) {TIME_OF_DAY}(?:\.\d+)?")
        };
        let expected = [
            (
                0,
                format!(
                    r"\b\d{{4}}-\d{{2}}-\d{{2}}[T ]{TIME_OF_DAY}(?:[.,]\d+)?(?:Z|[+-]\d{{2}}:?\d{{2}})?"
                ),
            ),
            (1, klog("I")),
            (2, klog("W")),
            (3, klog("E")),
            (4, klog("F")),
            (
                5,
                format!(r"\b\d{{2}}/{MONTH}/{YEAR}:{TIME_OF_DAY}(?: [+-]\d{{4}})?"),
            ),
            (
                6,
                format!(
                    r"\b{WEEKDAY} {MONTH} {{1,2}}{DAY_OF_MONTH} {TIME_OF_DAY}(?: {ZONE})? {YEAR}"
                ),
            ),
            (
                7,
                format!(
                    r"\b{WEEKDAY}, {DAY_OF_MONTH} {MONTH} {YEAR} {TIME_OF_DAY}(?: GMT| UTC| [+-]\d{{4}})?"
                ),
            ),
            (
                8,
                format!(r"\b(?:{WEEKDAY} )?{MONTH} {{1,2}}{DAY_OF_MONTH} {TIME_OF_DAY}"),
            ),
        ];
        for (i, text) in expected {
            assert_eq!(MASK_RULES[i].pattern, text, "rule {i}");
        }
    }

    #[test]
    fn a_split_pair_at_the_output_cap_becomes_replacement_character() {
        let body = format!("{}{}", "z".repeat(1023), "🚀");
        let result = build_log_pattern(Some(&body), &MESSAGE_KEYS);
        assert_eq!(result.masked_length, 1025);
        assert_eq!(result.pattern, format!("{}\u{FFFD}", "z".repeat(1023)));
    }

    /// node-re2 writes each lone surrogate as U+FFFD, so keys that differ only by a lone
    /// surrogate merge into one key after the mask.
    #[test]
    fn lone_surrogate_keys_merge_after_the_mask() {
        let result = build_log_pattern(Some(r#"{"\ud800":1,"\ud801":2,"b":3}"#), &MESSAGE_KEYS);
        assert_eq!(result.pattern, "<JSON:b,\u{FFFD}>");
        assert_eq!(result.json_key_count, Some(3));
    }
}
