//! Port of the normalize half of `nodejs/src/logs/log-record-avro.ts` (PII scrub, JSON attribute
//! extraction from a selected attribute and from the body) and of `log-record-size.ts`.
//!
//! The flatten keeps or evicts attributes by JavaScript object key order: array-index keys come
//! first in ascending order, then other keys in insertion order. `FlatAttributes` keeps that order.
//!
//! The TypeScript also adds each enrichment skip to an OpenTelemetry counter
//! (`recordJsonEnrichmentSkipped`). This port emits only the Prometheus counter.

use std::collections::{BTreeMap, HashMap};
use std::sync::Arc;

use metrics::counter;
use serde::Deserialize;

use crate::avro::{AvroMap, AvroValue};
use crate::body_parse::{parse_log_body_for_ingestion, LogBodyParseResult};
use crate::js::{
    is_array_index, json_parse, json_stringify, CharOrSurrogate, JsObject, JsString, JsValue,
};
use crate::pii::{scrub_log_record, PiiScrubStats, EMPTY_PII};
use crate::record::LogRecord;

pub const MAX_LOG_RECORD_BYTES: usize = 1024 * 1024;
pub const MAX_JSON_ATTRIBUTES: usize = 50;
pub const MAX_JSON_NODES: usize = 10_000;
pub const MAX_JSON_DEPTH: usize = 128;

/// `LogsSettings` from `nodejs/src/types.ts`. A missing key reads as `undefined`.
#[derive(Debug, Clone, Default, PartialEq, Deserialize)]
pub struct LogsSettings {
    #[serde(default)]
    pub capture_console_logs: Option<bool>,
    #[serde(default)]
    pub json_parse_logs: Option<bool>,
    #[serde(default)]
    pub json_parse_logs_attribute_key: Option<String>,
    #[serde(default)]
    pub pii_scrub_logs: Option<bool>,
    #[serde(default)]
    pub retention_days: Option<f64>,
    #[serde(default)]
    pub retention_last_updated: Option<String>,
}

impl LogsSettings {
    /// `Boolean(settings.json_parse_logs_attribute_key)`: an empty key is off.
    pub fn attribute_key(&self) -> Option<&str> {
        self.json_parse_logs_attribute_key
            .as_deref()
            .filter(|k| !k.is_empty())
    }
}

/// `logRecordSizeBytes`: UTF-8 bytes of the body, the severity text, and each key and value of
/// `attributes` and `resource_attributes`.
pub fn log_record_size_bytes(record: &LogRecord) -> usize {
    let mut bytes = 0;
    for value in [record.body(), record.severity_text()]
        .into_iter()
        .flatten()
    {
        bytes += value.len();
    }
    for attributes in [record.attributes(), record.resource_attributes()]
        .into_iter()
        .flatten()
    {
        for (key, value) in attributes.iter_strings() {
            bytes += key.len() + value.len();
        }
    }
    bytes
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum JsonEnrichmentSource {
    Body,
    SelectedAttribute,
}

impl JsonEnrichmentSource {
    fn as_str(self) -> &'static str {
        match self {
            JsonEnrichmentSource::Body => "body",
            JsonEnrichmentSource::SelectedAttribute => "selected_attribute",
        }
    }
}

fn record_json_enrichment_skip(reason: &'static str, source: JsonEnrichmentSource) {
    counter!(
        "logs_ingestion_json_enrichment_skipped_total",
        "reason" => reason,
        "source" => source.as_str()
    )
    .increment(1);
}

/// The regex `/^[ \t\r\n]*"?(?:[ \t\r\n]|\\[nrt])*[{\[]/` on `value.slice(0, 64)`.
///
/// No piece of the regex can trade characters with another piece, so one forward scan decides
/// it. Every character that the regex consumes is ASCII, so 64 UTF-16 units are 64 bytes up to
/// the point where the scan stops.
fn looks_like_json(value: &str) -> bool {
    let bytes = &value.as_bytes()[..value.len().min(64)];
    let is_space = |b: u8| matches!(b, b' ' | b'\t' | b'\r' | b'\n');
    let mut i = 0;
    while i < bytes.len() && is_space(bytes[i]) {
        i += 1;
    }
    if i < bytes.len() && bytes[i] == b'"' {
        i += 1;
    }
    loop {
        match bytes.get(i) {
            Some(&b) if is_space(b) => i += 1,
            Some(b'\\') if matches!(bytes.get(i + 1), Some(b'n' | b'r' | b't')) => i += 2,
            Some(b'{' | b'[') => return true,
            _ => return false,
        }
    }
}

/// `sniffJsonLogAttributes`: counts each record by whether the attribute looks like JSON.
pub fn sniff_json_log_attributes<'a>(
    records: impl IntoIterator<Item = &'a LogRecord>,
    attribute_key: &str,
    team_id: i64,
) {
    let team_id: Arc<str> = Arc::from(team_id.to_string());
    for record in records {
        let outcome = match record.attributes().and_then(|a| a.get(attribute_key)) {
            None => "missing_key",
            Some(value) => match value.as_str() {
                Some(text) if looks_like_json(text) => "looks_like_json",
                _ => "other",
            },
        };
        counter!(
            "logs_ingestion_json_attribute_sniff_total",
            "team_id" => team_id.clone(),
            "outcome" => outcome
        )
        .increment(1);
    }
}

/// `countJsonNodesWithinBudget`.
fn count_json_nodes_within_budget(value: &JsValue, depth: usize, budget: usize) -> Option<usize> {
    let mut stack = vec![(value, depth)];
    let mut nodes = 1usize;
    while let Some((value, depth)) = stack.pop() {
        if nodes > budget || depth > MAX_JSON_DEPTH {
            return None;
        }
        let children: Box<dyn Iterator<Item = &JsValue>> = match value {
            JsValue::Array(items) => Box::new(items.iter()),
            JsValue::Object(object) => Box::new(object.iter().map(|(_, v)| v)),
            _ => continue,
        };
        for child in children {
            nodes += 1;
            if nodes > budget {
                return None;
            }
            stack.push((child, depth + 1));
        }
    }
    Some(nodes)
}

/// Flattened attributes in JavaScript object key order, with values already `JSON.stringify`d.
pub type FlatAttributes = Vec<(JsString, String)>;

#[derive(Debug, Clone, PartialEq)]
pub struct FlattenResult {
    pub values: JsObject,
    pub attributes: FlatAttributes,
}

/// The `result` and `attributes` objects of `flattenJsonWithBudget`, which always hold the same
/// keys. A key is an array index or named, as in a JavaScript object.
#[derive(Default)]
struct FlatObject {
    indexed: BTreeMap<u32, (JsString, JsValue, String)>,
    named: Vec<(JsString, JsValue, String)>,
    named_position: HashMap<JsString, usize>,
}

impl FlatObject {
    fn get(&self, key: &JsString) -> Option<&(JsString, JsValue, String)> {
        match key.as_str().and_then(is_array_index) {
            Some(n) => self.indexed.get(&n),
            None => self.named_position.get(key).map(|&i| &self.named[i]),
        }
    }

    fn set(&mut self, key: JsString, value: JsValue, serialized: String) {
        if let Some(n) = key.as_str().and_then(is_array_index) {
            self.indexed.insert(n, (key, value, serialized));
        } else if let Some(&i) = self.named_position.get(&key) {
            self.named[i] = (key, value, serialized);
        } else {
            self.named_position.insert(key.clone(), self.named.len());
            self.named.push((key, value, serialized));
        }
    }

    fn remove(&mut self, key: &JsString) {
        if let Some(n) = key.as_str().and_then(is_array_index) {
            self.indexed.remove(&n);
        } else if let Some(i) = self.named_position.remove(key) {
            self.named.remove(i);
            for (k, _, _) in &self.named[i..] {
                *self
                    .named_position
                    .get_mut(k)
                    .expect("named key is indexed") -= 1;
            }
        }
    }

    /// `Object.keys(result)[result.length - 1]`.
    fn last_key(&self) -> Option<&JsString> {
        match self.named.last() {
            Some((k, _, _)) => Some(k),
            None => self.indexed.values().next_back().map(|(k, _, _)| k),
        }
    }

    fn into_result(self) -> FlattenResult {
        let mut values = JsObject::new();
        let mut attributes = Vec::with_capacity(self.indexed.len() + self.named.len());
        for (key, value, serialized) in self.indexed.into_values().chain(self.named) {
            values.insert(key.clone(), value);
            attributes.push((key, serialized));
        }
        FlattenResult { values, attributes }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ArrayMode {
    /// Body arrays become indexed paths.
    Indexed,
    /// Selected-attribute arrays are stored as JSON strings.
    String,
}

enum Node<'a> {
    Borrowed(&'a JsValue),
    Owned(JsValue),
}

impl Node<'_> {
    fn value(&self) -> &JsValue {
        match self {
            Node::Borrowed(v) => v,
            Node::Owned(v) => v,
        }
    }
}

fn is_index_key(key: &JsString) -> Option<u32> {
    key.as_str().and_then(is_array_index)
}

/// `flattenJsonWithBudget`: flattens JSON into dot-notation keys. `None` means a budget ran out.
pub fn flatten_json_with_budget<'a>(
    obj: &'a JsValue,
    prefix: &JsString,
    max_attributes: usize,
    max_bytes: usize,
    array_mode: ArrayMode,
) -> Option<FlattenResult> {
    let mut result = FlatObject::default();
    let mut stack: Vec<(Node<'a>, JsString, usize)> =
        vec![(Node::Borrowed(obj), prefix.clone(), 0)];
    let mut nodes = 1usize;
    let mut path_bytes = prefix.utf8_byte_len();
    let mut attribute_bytes: i64 = 0;
    let mut attribute_count = 0usize;
    let mut last_retained_key = JsString::new();

    while let Some((mut node, entry_prefix, depth)) = stack.pop() {
        if depth > MAX_JSON_DEPTH || path_bytes > max_bytes {
            return None;
        }
        if array_mode == ArrayMode::String {
            if let JsValue::Array(_) = node.value() {
                let array_nodes = count_json_nodes_within_budget(
                    node.value(),
                    depth,
                    MAX_JSON_NODES - nodes + 1,
                )?;
                nodes += array_nodes - 1;
                node = Node::Owned(JsValue::string(&json_stringify(node.value())));
            }
        }

        let container: Option<&'a JsValue> = match &node {
            Node::Borrowed(v) if v.is_object_like() => Some(*v),
            _ => None,
        };
        if let Some(container) = container {
            let children: Vec<(JsString, &'a JsValue)> = match container {
                JsValue::Array(items) => {
                    if items.len() + nodes > MAX_JSON_NODES {
                        return None;
                    }
                    items
                        .iter()
                        .enumerate()
                        .map(|(i, v)| (JsString::from(i.to_string()), v))
                        .collect()
                }
                JsValue::Object(object) => {
                    let mut keys = Vec::with_capacity(object.len());
                    for (key, value) in object.iter() {
                        if nodes + keys.len() >= MAX_JSON_NODES {
                            return None;
                        }
                        keys.push((key, value));
                    }
                    keys
                }
                _ => unreachable!("container is an array or an object"),
            };
            nodes += children.len();
            // Pushed in reverse, so the stack pops the children in key order.
            for (key, value) in children.into_iter().rev() {
                let child_prefix = if entry_prefix.is_empty() {
                    key
                } else {
                    let mut p = entry_prefix.clone();
                    p.push_str(".");
                    p.push_js(&key);
                    p
                };
                path_bytes += child_prefix.utf8_byte_len();
                if path_bytes > max_bytes {
                    return None;
                }
                stack.push((Node::Borrowed(value), child_prefix, depth + 1));
            }
            continue;
        }

        let key = entry_prefix;
        if key.is_empty() || key == "__proto__" || max_attributes == 0 {
            continue;
        }
        let exists = result.get(&key).is_some();
        if !exists && attribute_count >= max_attributes {
            let Some(index) = is_index_key(&key) else {
                continue;
            };
            let last_key = last_retained_key.clone();
            if let Some(last_index) = is_index_key(&last_key) {
                if last_index <= index {
                    continue;
                }
            }
            if let Some((_, _, serialized)) = result.get(&last_key) {
                attribute_bytes -= (last_key.utf8_byte_len() + serialized.len()) as i64;
            }
            result.remove(&last_key);
            attribute_count -= 1;
        }
        let value = match node.value() {
            JsValue::Null => JsValue::string("null"),
            other => other.clone(),
        };
        let serialized = json_stringify(&value);
        let value_bytes = serialized.len() as i64;
        attribute_bytes += match result.get(&key) {
            Some((_, _, previous)) if exists => value_bytes - previous.len() as i64,
            _ => (key.utf8_byte_len() as i64) + value_bytes,
        };
        if attribute_bytes > max_bytes as i64 {
            return None;
        }
        result.set(key, value, serialized);
        if !exists {
            attribute_count += 1;
            if attribute_count == max_attributes {
                last_retained_key = result.last_key().cloned().unwrap_or_default();
            }
        }
    }
    Some(result.into_result())
}

/// `flattenJson` with the default arguments.
pub fn flatten_json(obj: &JsValue) -> Option<JsObject> {
    flatten_json_with_budget(
        obj,
        &JsString::new(),
        MAX_JSON_ATTRIBUTES,
        MAX_LOG_RECORD_BYTES,
        ArrayMode::Indexed,
    )
    .map(|r| r.values)
}

fn json_attributes_from_body_parse(body_parse: &LogBodyParseResult) -> FlatAttributes {
    let LogBodyParseResult::JsonObjectOrArray { value } = body_parse else {
        return Vec::new();
    };
    match flatten_json_with_budget(
        value,
        &JsString::new(),
        MAX_JSON_ATTRIBUTES,
        MAX_LOG_RECORD_BYTES,
        ArrayMode::Indexed,
    ) {
        Some(flattened) => flattened.attributes,
        None => {
            record_json_enrichment_skip("flatten_budget", JsonEnrichmentSource::Body);
            Vec::new()
        }
    }
}

/// `extractJsonAttributesFromBody`.
pub fn extract_json_attributes_from_body(body: Option<&str>) -> FlatAttributes {
    if let Some(body) = body {
        if body.len() > MAX_LOG_RECORD_BYTES {
            record_json_enrichment_skip("input_size", JsonEnrichmentSource::Body);
            return Vec::new();
        }
    }
    json_attributes_from_body_parse(&parse_log_body_for_ingestion(body))
}

/// `addJsonAttributes`: `{ ...jsonAttributes, ...record.attributes }` unless the record would
/// pass the size limit.
///
/// A key with a lone surrogate is a distinct key in JavaScript, and avsc writes it as U+FFFD. An
/// `AvroMap` key is a Rust string, so such a key merges with a U+FFFD key here. See PORTING.md.
fn add_json_attributes(
    record: &mut LogRecord,
    json_attributes: FlatAttributes,
    mut record_bytes: usize,
    source: JsonEnrichmentSource,
) {
    if json_attributes.is_empty() {
        return;
    }
    let existing = record.attributes();
    for (key, value) in &json_attributes {
        let present = match (existing, key.as_str()) {
            (Some(attributes), Some(key)) => attributes.contains_key(key),
            _ => false,
        };
        if !present {
            record_bytes += key.utf8_byte_len() + value.len();
            if record_bytes > MAX_LOG_RECORD_BYTES {
                record_json_enrichment_skip("output_size", source);
                return;
            }
        }
    }
    let mut merged = AvroMap::new();
    for (key, value) in json_attributes {
        merged.define(key.into_string_lossy(), AvroValue::String(value));
    }
    if let Some(attributes) = existing {
        for (key, value) in attributes.iter() {
            merged.define(key.to_string(), value.clone());
        }
    }
    record.set("attributes", AvroValue::Map(merged));
}

/// `enrichLogRecordWithJsonAttributes`. Pass `body_parse` to reuse a parse of the same body.
pub fn enrich_log_record_with_json_attributes(
    record: &mut LogRecord,
    body_parse: Option<&LogBodyParseResult>,
) {
    let Some(body) = record.body().filter(|b| !b.is_empty()) else {
        return;
    };
    if body.len() > MAX_LOG_RECORD_BYTES {
        record_json_enrichment_skip("input_size", JsonEnrichmentSource::Body);
        return;
    }
    let owned;
    let parse = match body_parse {
        Some(parse) => parse,
        None => {
            owned = parse_log_body_for_ingestion(Some(body));
            &owned
        }
    };
    if !matches!(parse, LogBodyParseResult::JsonObjectOrArray { .. }) {
        return;
    }
    let record_bytes = log_record_size_bytes(record);
    if record_bytes > MAX_LOG_RECORD_BYTES {
        record_json_enrichment_skip("input_size", JsonEnrichmentSource::Body);
        return;
    }
    let json_attributes = json_attributes_from_body_parse(parse);
    add_json_attributes(
        record,
        json_attributes,
        record_bytes,
        JsonEnrichmentSource::Body,
    );
}

/// `JSON.parse` of a JavaScript string that can hold a lone surrogate.
///
/// A raw lone surrogate is valid only inside a JSON string literal, and there it means the same
/// as its `\uXXXX` escape. So the text is rewritten with escapes. After an odd run of
/// backslashes the raw surrogate would follow an escape, which `JSON.parse` rejects.
fn json_parse_js(text: &JsString) -> Option<JsValue> {
    if let Some(text) = text.as_str() {
        return json_parse(text).ok();
    }
    let mut rewritten = String::new();
    let mut backslashes = 0usize;
    for unit in text.chars_or_surrogates() {
        match unit {
            CharOrSurrogate::Char(c) => {
                backslashes = if c == '\\' { backslashes + 1 } else { 0 };
                rewritten.push(c);
            }
            CharOrSurrogate::Surrogate(s) => {
                if backslashes % 2 == 1 {
                    return None;
                }
                backslashes = 0;
                rewritten.push_str(&format!("\\u{s:04x}"));
            }
        }
    }
    json_parse(&rewritten).ok()
}

/// `enrichLogRecordFromJsonAttribute`: flattens the JSON object in `attributes[key]` (or in a
/// JSON string that holds it) under the prefix `key`.
pub fn enrich_log_record_from_json_attribute(record: &mut LogRecord, key: &str) {
    let Some(raw) = record.attributes().and_then(|a| a.get(key)) else {
        return;
    };
    let Some(raw) = raw.as_str() else {
        return;
    };
    let record_bytes = log_record_size_bytes(record);
    if record_bytes > MAX_LOG_RECORD_BYTES {
        record_json_enrichment_skip("input_size", JsonEnrichmentSource::SelectedAttribute);
        return;
    }
    let mut parsed = match json_parse(raw) {
        Ok(parsed) => parsed,
        Err(_) => return,
    };
    if let JsValue::String(inner) = &parsed {
        parsed = match json_parse_js(inner) {
            Some(parsed) => parsed,
            None => return,
        };
    }
    if !matches!(parsed, JsValue::Object(_)) {
        return;
    }
    match flatten_json_with_budget(
        &parsed,
        &JsString::from(key),
        MAX_JSON_ATTRIBUTES,
        MAX_LOG_RECORD_BYTES,
        ArrayMode::String,
    ) {
        Some(flattened) => add_json_attributes(
            record,
            flattened.attributes,
            record_bytes,
            JsonEnrichmentSource::SelectedAttribute,
        ),
        None => {
            record_json_enrichment_skip("flatten_budget", JsonEnrichmentSource::SelectedAttribute)
        }
    }
}

/// `transformDecodedLogRecordsInPlace`: scrub first, then enrich from the selected attribute,
/// then from the body. So sender attributes win over selected-attribute fields, and those win
/// over body fields.
pub fn transform_decoded_log_records_in_place(
    records: &mut [LogRecord],
    settings: &LogsSettings,
) -> PiiScrubStats {
    let mut pii = EMPTY_PII;
    if settings.pii_scrub_logs.unwrap_or(false) {
        for record in records.iter_mut() {
            pii.pii_replacements += scrub_log_record(record).pii_replacements;
        }
    }
    if let Some(key) = settings.attribute_key() {
        for record in records.iter_mut() {
            enrich_log_record_from_json_attribute(record, key);
        }
    }
    if settings.json_parse_logs.unwrap_or(false) {
        // Node parses every body before it enriches any record. No enrichment changes a body,
        // so one parse per record in the same loop gives the same result.
        for record in records.iter_mut() {
            let parse = parse_log_body_for_ingestion(
                record.body().filter(|b| b.len() <= MAX_LOG_RECORD_BYTES),
            );
            enrich_log_record_with_json_attributes(record, Some(&parse));
        }
    }
    pii
}

/// `BufferProcessingMode`, cheapest first.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BufferProcessingMode {
    Passthrough,
    DecodeOnly,
    DecodeAndReencode,
}

/// `bufferProcessingMode`. Pass the current stage count of the buffer.
pub fn buffer_processing_mode(
    settings: &LogsSettings,
    stage_count: usize,
    has_visitor: bool,
) -> BufferProcessingMode {
    let normalize_active = settings.json_parse_logs.unwrap_or(false)
        || settings.pii_scrub_logs.unwrap_or(false)
        || settings.attribute_key().is_some();
    if normalize_active || stage_count > 0 {
        BufferProcessingMode::DecodeAndReencode
    } else if has_visitor {
        BufferProcessingMode::DecodeOnly
    } else {
        BufferProcessingMode::Passthrough
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sniff_matches_the_regex() {
        for (value, expected) in [
            ("{", true),
            ("  \"{", true),
            ("\"\\n\\t [", true),
            ("\\n{", true),
            ("\"\"{", false),
            ("x{", false),
            ("\u{000B}{", false),
            ("\\x{", false),
            ("", false),
        ] {
            assert_eq!(looks_like_json(value), expected, "{value:?}");
        }
        let far = format!("{}{{", " ".repeat(64));
        assert!(!looks_like_json(&far));
    }

    #[test]
    fn a_raw_lone_surrogate_parses_as_its_escape() {
        let mut text = JsString::from("{\"a\":\"");
        text.push_code_unit(0xD800);
        text.push_str("\"}");
        let JsValue::Object(o) = json_parse_js(&text).unwrap() else {
            panic!("not an object");
        };
        assert_eq!(json_stringify(o.get("a").unwrap()), "\"\\ud800\"");

        let mut escaped = JsString::from("\"\\");
        escaped.push_code_unit(0xD800);
        escaped.push_str("\"");
        assert!(json_parse_js(&escaped).is_none());
    }
}
