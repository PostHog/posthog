//! Port of `tally.ts`, except `MetricSeriesAdmission` (see `admission`).

use super::compile::CompiledMetricRule;
use super::ordered::InsertionMap;
use super::parse_float::js_parse_float;
use crate::attribute_value::decode_log_attribute_value;
use crate::avro::AvroMap;
use crate::filter_group::{lookup_attribute, AttrLookup};
use crate::js::{number_to_string, quote_js_string, JsObject, JsString, JsValue};
use crate::property_filter::coerce::JsTypeError;
use crate::record::LogRecord;

pub const MAX_LABEL_SETS_PER_RULE: usize = 1000;

/// Not valid JSON, so no real label set (always a JSON array) can collide with it.
pub const OVERFLOW_LABEL_KEY: &str = "__overflow__";

/// The OTel SDK default explicit bucket bounds.
pub const DEFAULT_HISTOGRAM_BOUNDS: [f64; 15] = [
    0.0, 5.0, 10.0, 25.0, 50.0, 75.0, 100.0, 250.0, 500.0, 750.0, 1000.0, 2500.0, 5000.0, 7500.0,
    10000.0,
];

/// In UTF-16 code units, as `str.length` counts.
pub const MAX_LABEL_VALUE_LENGTH: usize = 256;

/// Older records never feed a metric, so a backfill cannot distort the current data point.
pub const MAX_RECORD_AGE_MS: f64 = 20.0 * 60.0 * 1000.0;

/// Pseudo value-attribute key for a span's `end_time - timestamp`, in milliseconds.
pub const SPAN_VALUE_DURATION_MS: &str = "duration_ms";

const ATTRIBUTES_PREFIX: &str = "attributes.";
const RESOURCE_ATTRIBUTES_PREFIX: &str = "resource_attributes.";

fn span_status_code_label(code: i64) -> Option<&'static str> {
    match code {
        0 => Some("UNSET"),
        1 => Some("OK"),
        2 => Some("ERROR"),
        _ => None,
    }
}

fn span_kind_label(kind: i64) -> Option<&'static str> {
    match kind {
        1 => Some("INTERNAL"),
        2 => Some("SERVER"),
        3 => Some("CLIENT"),
        4 => Some("PRODUCER"),
        5 => Some("CONSUMER"),
        _ => None,
    }
}

/// A label value. Attribute maps are plain objects in Node, so `attributes.constructor` reads an
/// `Object.prototype` member, and the label is that member instead of a string.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum LabelValue {
    String(JsString),
    /// A prototype method: `JSON.stringify` writes it as `null` in an array and omits it as a property.
    Function,
    /// `Object.prototype`, from `attributes.__proto__`: `JSON.stringify` writes `{}`.
    PrototypeObject,
}

impl LabelValue {
    pub fn empty() -> Self {
        LabelValue::String(JsString::new())
    }

    /// The value as `JSON.stringify` sees it. `None` is a function.
    pub fn to_json(&self) -> Option<JsValue> {
        match self {
            LabelValue::String(s) => Some(JsValue::String(s.clone())),
            LabelValue::Function => None,
            LabelValue::PrototypeObject => Some(JsValue::Object(JsObject::new())),
        }
    }

    pub fn as_js_string(&self) -> Option<&JsString> {
        match self {
            LabelValue::String(s) => Some(s),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct MetricTallyEntry {
    pub label_values: Vec<LabelValue>,
    pub count: u64,
    pub sum: f64,
    pub bucket_counts: Option<Vec<u64>>,
    pub overflow: bool,
    pub exemplar_trace_id: Option<String>,
    pub exemplar_span_id: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct BatchTallies {
    pub by_rule: InsertionMap<InsertionMap<MetricTallyEntry>>,
    pub series_overflow: InsertionMap<u64>,
    pub value_skipped: u64,
    /// Filter evaluations that failed. The record is skipped for that rule only.
    pub eval_errors: u64,
}

impl BatchTallies {
    pub fn new() -> Self {
        Self::default()
    }
}

fn record_string(record: &LogRecord, name: &str) -> Option<LabelValue> {
    record
        .get_str(name)
        .map(|s| LabelValue::String(JsString::from(s)))
}

fn enum_label(value: i64, label: Option<&str>) -> LabelValue {
    LabelValue::String(JsString::from(
        label
            .map(str::to_string)
            .unwrap_or_else(|| number_to_string(value as f64)),
    ))
}

fn lookup_key(key: &JsString, record: &LogRecord) -> Result<Option<LabelValue>, JsTypeError> {
    // Every literal key, map key and prototype member is valid UTF-8, so a lone surrogate matches none.
    let Some(key) = key.as_str() else {
        return Ok(None);
    };
    Ok(match key {
        "service_name" | "severity_text" | "event_name" | "name" => record_string(record, key),
        // Labels use the OTel enum name. Filter matching keeps the number.
        "status_code" => record
            .status_code()
            .map(|code| enum_label(code, span_status_code_label(code))),
        "kind" => record
            .kind()
            .map(|kind| enum_label(kind, span_kind_label(kind))),
        _ => {
            if let Some(attr) = key.strip_prefix(ATTRIBUTES_PREFIX) {
                decoded_attr(record.attributes(), attr)?
            } else if let Some(attr) = key.strip_prefix(RESOURCE_ATTRIBUTES_PREFIX) {
                decoded_attr(record.resource_attributes(), attr)?
            } else {
                None
            }
        }
    })
}

/// `decodedAttr`: attribute values are JSON-encoded on the wire, so a label reads the decoded value.
fn decoded_attr(map: Option<&AvroMap>, key: &str) -> Result<Option<LabelValue>, JsTypeError> {
    let Some(map) = map else {
        return Ok(None);
    };
    Ok(match lookup_attribute(map, key) {
        None => None,
        Some(AttrLookup::Own(raw)) => Some(LabelValue::String(decode_log_attribute_value(raw))),
        Some(AttrLookup::Inherited(member)) => match member.length {
            // `value.length >= 2 && value.startsWith(...)`: a function has no `startsWith`.
            Some(n) if n >= 2 => return Err(JsTypeError("value.startsWith is not a function")),
            Some(_) => Some(LabelValue::Function),
            None => Some(LabelValue::PrototypeObject),
        },
    })
}

/// `resolveLabelValue`: missing is `''`, and a string is cut at 256 UTF-16 units. The cut can
/// split a surrogate pair; `JSON.stringify` then writes the lone half as `\udxxx`.
pub fn resolve_label_value(key: &JsString, record: &LogRecord) -> Result<LabelValue, JsTypeError> {
    Ok(match lookup_key(key, record)? {
        Some(LabelValue::String(value)) if value.utf16_len() > MAX_LABEL_VALUE_LENGTH => {
            LabelValue::String(value.utf16_slice(0, MAX_LABEL_VALUE_LENGTH))
        }
        // A function's `length` and `Object.prototype.length` never pass the cap.
        Some(value) => value,
        None => LabelValue::empty(),
    })
}

fn label_key(label_values: &[LabelValue]) -> String {
    let mut out = String::from("[");
    for (i, value) in label_values.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        match value {
            LabelValue::String(s) => quote_js_string(s, &mut out),
            LabelValue::Function => out.push_str("null"),
            LabelValue::PrototypeObject => out.push_str("{}"),
        }
    }
    out.push(']');
    out
}

fn histogram_bucket_index(value: f64) -> usize {
    DEFAULT_HISTOGRAM_BOUNDS
        .iter()
        .position(|bound| value <= *bound)
        .unwrap_or(DEFAULT_HISTOGRAM_BOUNDS.len())
}

fn new_tally_entry(
    label_values: Vec<LabelValue>,
    with_buckets: bool,
    overflow: bool,
) -> MetricTallyEntry {
    MetricTallyEntry {
        label_values,
        count: 0,
        sum: 0.0,
        bucket_counts: with_buckets.then(|| vec![0; DEFAULT_HISTOGRAM_BOUNDS.len() + 1]),
        overflow,
        exemplar_trace_id: None,
        exemplar_span_id: None,
    }
}

fn resolve_numeric_value(key: &JsString, record: &LogRecord) -> Result<Option<f64>, JsTypeError> {
    if *key == SPAN_VALUE_DURATION_MS {
        let (Some(start), Some(end)) = (record.timestamp(), record.end_time()) else {
            return Ok(None);
        };
        // Both are below 2^53, so the conversions are exact, as the JavaScript numbers are.
        let duration_ms = (end as f64 - start as f64) / 1000.0;
        return Ok((duration_ms.is_finite() && duration_ms >= 0.0).then_some(duration_ms));
    }
    let raw = match lookup_key(key, record)? {
        None => return Ok(None),
        Some(LabelValue::String(raw)) => raw,
        // `String(member)` starts with `function` or `[object`, so `parseFloat` gives NaN.
        Some(_) => return Ok(None),
    };
    if raw.is_empty() {
        return Ok(None);
    }
    let parsed = js_parse_float(&raw);
    Ok(parsed.is_finite().then_some(parsed))
}

/// Node's base64 decoder (`Buffer.from(s, 'base64')`): it skips characters outside the
/// alphabet, accepts the URL-safe alphabet too, and stops at the first `=`.
fn node_base64_decode(input: &[u8]) -> Vec<u8> {
    fn sextet(c: u8) -> Option<u32> {
        Some(match c {
            b'A'..=b'Z' => c - b'A',
            b'a'..=b'z' => c - b'a' + 26,
            b'0'..=b'9' => c - b'0' + 52,
            b'+' | b'-' => 62,
            b'/' | b'_' => 63,
            _ => return None,
        } as u32)
    }
    let mut out = Vec::with_capacity(input.len() / 4 * 3 + 2);
    let mut acc = 0u32;
    let mut n = 0;
    for &c in input {
        if c == b'=' {
            break;
        }
        let Some(v) = sextet(c) else { continue };
        acc = (acc << 6) | v;
        n += 1;
        if n == 4 {
            out.extend_from_slice(&[(acc >> 16) as u8, (acc >> 8) as u8, acc as u8]);
            acc = 0;
            n = 0;
        }
    }
    match n {
        2 => out.push((acc >> 4) as u8),
        3 => out.extend_from_slice(&[(acc >> 10) as u8, (acc >> 2) as u8]),
        _ => {}
    }
    out
}

/// `idToHex`: lowercase hex of a trace or span id, or `None` when absent, all zero, or
/// unparseable. capture-logs writes the ids as base64 text, so a length mismatch decodes it.
pub fn id_to_hex(buffer: Option<&[u8]>, expected_bytes: usize) -> Option<String> {
    let buffer = buffer.filter(|b| !b.is_empty())?;
    let decoded;
    let bytes = if buffer.len() != expected_bytes {
        // `buffer.toString('ascii')` clears the high bit of each byte.
        let ascii: Vec<u8> = buffer.iter().map(|b| b & 0x7f).collect();
        decoded = node_base64_decode(&ascii);
        if decoded.len() != expected_bytes {
            return None;
        }
        &decoded[..]
    } else {
        buffer
    };
    if bytes.iter().all(|b| *b == 0) {
        return None;
    }
    Some(hex::encode(bytes))
}

pub type AdmitLabelSet<'a> = &'a mut dyn FnMut(&str, &str) -> bool;

/// `Err` is a throw that Node does not catch: a label or value read of a prototype member such as
/// `attributes.__defineGetter__`. The tallies keep what the earlier records added, as in Node.
pub fn tally_records(
    rules: &[CompiledMetricRule],
    records: &[LogRecord],
    tallies: &mut BatchTallies,
    now_ms: f64,
    mut admit_label_set: Option<AdmitLabelSet<'_>>,
) -> Result<(), JsTypeError> {
    if rules.is_empty() || records.is_empty() {
        return Ok(());
    }
    for record in records {
        // A span's timestamp is its start, so gate on end_time to keep long spans.
        // A null timestamp means "now" to ingestion, so it passes.
        let observed_at_micros = record.end_time().or_else(|| record.timestamp());
        if let Some(micros) = observed_at_micros {
            if now_ms - micros as f64 / 1000.0 > MAX_RECORD_AGE_MS {
                continue;
            }
        }
        for rule in rules {
            if let Some(group) = &rule.filter_group {
                match group.matches(record) {
                    Ok(true) => {}
                    Ok(false) => continue,
                    Err(_) => {
                        tallies.eval_errors += 1;
                        continue;
                    }
                }
            }
            let mut value = 1.0;
            if let Some(key) = &rule.value_attribute {
                match resolve_numeric_value(key, record)? {
                    Some(parsed) => value = parsed,
                    None => {
                        tallies.value_skipped += 1;
                        continue;
                    }
                }
            }

            let label_values = rule
                .group_by
                .iter()
                .map(|key| resolve_label_value(key, record))
                .collect::<Result<Vec<_>, _>>()?;
            let label_key = label_key(&label_values);

            let rule_tallies = tallies
                .by_rule
                .get_or_insert_with(&rule.id, InsertionMap::new);
            let entry_key = if rule_tallies.contains_key(&label_key) {
                label_key
            } else {
                let has_overflow = rule_tallies.contains_key(OVERFLOW_LABEL_KEY);
                let real_label_sets = rule_tallies.len() - usize::from(has_overflow);
                let admitted = real_label_sets < MAX_LABEL_SETS_PER_RULE
                    && admit_label_set
                        .as_mut()
                        .is_none_or(|admit| admit(&rule.id, &label_key));
                if admitted {
                    let entry =
                        new_tally_entry(label_values, rule.value_attribute.is_some(), false);
                    rule_tallies.insert(&label_key, entry);
                    label_key
                } else {
                    // Past the cap the record still counts, on one shared series.
                    *tallies.series_overflow.get_or_insert_with(&rule.id, || 0) += 1;
                    if !has_overflow {
                        let entry = new_tally_entry(
                            vec![LabelValue::empty(); rule.group_by.len()],
                            rule.value_attribute.is_some(),
                            true,
                        );
                        rule_tallies.insert(OVERFLOW_LABEL_KEY, entry);
                    }
                    OVERFLOW_LABEL_KEY.to_string()
                }
            };
            let entry = rule_tallies
                .get_mut(&entry_key)
                .expect("entry was found or inserted");
            entry.count += 1;
            entry.sum += value;
            if let Some(buckets) = &mut entry.bucket_counts {
                buckets[histogram_bucket_index(value)] += 1;
            }
            if entry.exemplar_trace_id.is_none() {
                if let Some(trace_id) = id_to_hex(record.trace_id(), 16) {
                    entry.exemplar_trace_id = Some(trace_id);
                    entry.exemplar_span_id = id_to_hex(record.span_id(), 8);
                }
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn histogram_buckets_are_upper_inclusive() {
        assert_eq!(histogram_bucket_index(-1.0), 0);
        assert_eq!(histogram_bucket_index(0.0), 0);
        assert_eq!(histogram_bucket_index(5.0), 1);
        assert_eq!(histogram_bucket_index(5.5), 2);
        assert_eq!(histogram_bucket_index(10000.0), 14);
        assert_eq!(histogram_bucket_index(10000.1), 15);
    }
}
