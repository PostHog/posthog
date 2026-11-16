//! The flatten keeps or evicts attributes by JavaScript key order: array-index keys first, then insertion order.
//! Only the Prometheus counter counts enrichment skips, where the TypeScript also adds an OpenTelemetry counter.

use std::collections::BTreeMap;
use std::sync::Arc;

use hashbrown::HashTable;

use metrics::counter;
use serde::Deserialize;

use crate::avro::{AvroMap, AvroValue};
use crate::body_parse::{parse_log_body_for_ingestion, LogBodyParseResult};
use crate::js::object::hash_key;
use crate::js::{
    is_array_index, json_parse, json_stringify, json_stringify_into, quote_js_string,
    CharOrSurrogate, JsKey, JsObject, JsString, JsValue,
};
use crate::pii::{scrub_log_record, PiiScrubStats, EMPTY_PII};
use crate::record::LogRecord;

pub const MAX_LOG_RECORD_BYTES: usize = 1024 * 1024;
pub const MAX_JSON_ATTRIBUTES: usize = 50;
pub const MAX_JSON_NODES: usize = 10_000;
pub const MAX_JSON_DEPTH: usize = 128;
// The flatten must stop before it can reach a value that `json_parse` did not build.
const _: () = assert!(MAX_JSON_DEPTH < crate::js::MAX_BUILT_DEPTH);

/// A missing key reads as `undefined`.
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
    /// An empty key is off, as `Boolean(key)` is.
    pub fn attribute_key(&self) -> Option<&str> {
        self.json_parse_logs_attribute_key
            .as_deref()
            .filter(|k| !k.is_empty())
    }
}

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

/// Every character the regex consumes is ASCII, so 64 UTF-16 units are 64 bytes up to where the scan stops.
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

pub type FlatAttributes = Vec<(JsString, String)>;

#[derive(Debug, Clone, PartialEq)]
pub struct FlattenResult {
    pub values: JsObject,
    pub attributes: FlatAttributes,
}

/// `result` and `attributes` always hold the same keys, so one entry holds both.
struct FlatEntry {
    key: JsString,
    value: Option<JsValue>,
    serialized: String,
}

#[derive(Clone, Copy)]
enum FlatPos {
    Index(u32),
    Named(Option<usize>),
}

#[derive(Default)]
struct FlatObject {
    indexed: BTreeMap<u32, FlatEntry>,
    named: Vec<FlatEntry>,
    named_position: HashTable<usize>,
}

impl FlatObject {
    fn named_index(&self, key: &JsString) -> Option<usize> {
        self.named_position
            .find(hash_key(key), |&i| self.named[i].key == *key)
            .copied()
    }

    fn get(&self, key: &JsString) -> Option<&FlatEntry> {
        self.at(self.locate(key))
    }

    fn locate(&self, key: &JsString) -> FlatPos {
        match is_index_key(key) {
            Some(n) => FlatPos::Index(n),
            None => FlatPos::Named(self.named_index(key)),
        }
    }

    fn at(&self, pos: FlatPos) -> Option<&FlatEntry> {
        match pos {
            FlatPos::Index(n) => self.indexed.get(&n),
            FlatPos::Named(i) => i.map(|i| &self.named[i]),
        }
    }

    /// Stores `entry` at `pos`, which `locate` gave for its key with no removal since.
    fn set_at(&mut self, pos: FlatPos, entry: FlatEntry) {
        match pos {
            FlatPos::Index(n) => {
                self.indexed.insert(n, entry);
            }
            FlatPos::Named(Some(i)) => self.named[i] = entry,
            FlatPos::Named(None) => {
                let named = &self.named;
                self.named_position
                    .insert_unique(hash_key(&entry.key), named.len(), |&j| {
                        hash_key(&named[j].key)
                    });
                self.named.push(entry);
            }
        }
    }

    fn remove(&mut self, key: &JsString) {
        if let Some(n) = is_index_key(key) {
            self.indexed.remove(&n);
        } else if let Some(i) = self.named_index(key) {
            self.named.remove(i);
            self.named_position.clear();
            let named = &self.named;
            for (j, entry) in named.iter().enumerate() {
                self.named_position
                    .insert_unique(hash_key(&entry.key), j, |&k| hash_key(&named[k].key));
            }
        }
    }

    fn last_key(&self) -> Option<&JsString> {
        match self.named.last() {
            Some(entry) => Some(&entry.key),
            None => self.indexed.values().next_back().map(|entry| &entry.key),
        }
    }

    fn into_entries(self) -> impl Iterator<Item = FlatEntry> {
        self.indexed.into_values().chain(self.named)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ArrayMode {
    Indexed,
    String,
}

fn is_index_key(key: &JsString) -> Option<u32> {
    key.as_str().and_then(is_array_index)
}

enum Leaf<'a> {
    Value(&'a JsValue),
    Stringified(String),
}

/// Recurses in the TypeScript stack order with the same budget updates per node, so it evicts exactly where the TypeScript does.
struct Flattener {
    max_attributes: usize,
    max_bytes: usize,
    array_mode: ArrayMode,
    keep_values: bool,
    nodes: usize,
    path_bytes: usize,
    attribute_bytes: i64,
    attribute_count: usize,
    last_retained_key: JsString,
    result: FlatObject,
}

impl Flattener {
    /// `None` means a budget ran out.
    fn visit(&mut self, node: &JsValue, path: &mut JsString, depth: usize) -> Option<()> {
        if depth > MAX_JSON_DEPTH || self.path_bytes > self.max_bytes {
            return None;
        }
        match node {
            JsValue::Array(_) if self.array_mode == ArrayMode::String => {
                let array_nodes =
                    count_json_nodes_within_budget(node, depth, MAX_JSON_NODES - self.nodes + 1)?;
                self.nodes += array_nodes - 1;
                self.leaf(path, Leaf::Stringified(json_stringify(node)))
            }
            JsValue::Array(items) => {
                if items.len() + self.nodes > MAX_JSON_NODES {
                    return None;
                }
                self.nodes += items.len();
                let keys = (0..items.len()).map(|i| JsKey::Index(i as u32));
                self.add_child_paths(path, keys)?;
                self.visit_children(
                    path,
                    depth,
                    items
                        .iter()
                        .enumerate()
                        .map(|(i, v)| (JsKey::Index(i as u32), v)),
                )
            }
            JsValue::Object(object) => {
                let n = object.len();
                if n > 0 && self.nodes + n > MAX_JSON_NODES {
                    return None;
                }
                self.nodes += n;
                self.add_child_paths(path, object.entries().map(|(k, _)| k))?;
                self.visit_children(path, depth, object.entries())
            }
            _ => self.leaf(path, Leaf::Value(node)),
        }
    }

    /// Adds the byte length of every child path, as the TypeScript does before it descends.
    fn add_child_paths<'k>(
        &mut self,
        path: &JsString,
        keys: impl Iterator<Item = JsKey<'k>>,
    ) -> Option<()> {
        let base = path.utf8_byte_len();
        for key in keys {
            self.path_bytes += if base == 0 {
                key.utf8_byte_len()
            } else {
                base + 1 + key.utf8_byte_len()
            };
            if self.path_bytes > self.max_bytes {
                return None;
            }
        }
        Some(())
    }

    fn visit_children<'v>(
        &mut self,
        path: &mut JsString,
        depth: usize,
        children: impl Iterator<Item = (JsKey<'v>, &'v JsValue)>,
    ) -> Option<()> {
        let base = path.utf8_byte_len();
        let base_surrogates = path.lone_surrogate_count();
        for (key, child) in children {
            if base > 0 {
                path.push_str(".");
            }
            key.push_onto(path);
            self.visit(child, path, depth + 1)?;
            path.truncate_to(base, base_surrogates);
        }
        Some(())
    }

    fn leaf(&mut self, key: &JsString, leaf: Leaf<'_>) -> Option<()> {
        if key.is_empty() || *key == "__proto__" || self.max_attributes == 0 {
            return Some(());
        }
        let pos = self.result.locate(key);
        let exists = self.result.at(pos).is_some();
        if !exists && self.attribute_count >= self.max_attributes {
            let Some(index) = is_index_key(key) else {
                return Some(());
            };
            let last_key = self.last_retained_key.clone();
            if let Some(last_index) = is_index_key(&last_key) {
                if last_index <= index {
                    return Some(());
                }
            }
            if let Some(entry) = self.result.get(&last_key) {
                self.attribute_bytes -= (last_key.utf8_byte_len() + entry.serialized.len()) as i64;
            }
            self.result.remove(&last_key);
            self.attribute_count -= 1;
        }
        let (serialized, value) = match leaf {
            Leaf::Value(JsValue::Null) => (
                "\"null\"".to_string(),
                self.keep_values.then(|| JsValue::string("null")),
            ),
            Leaf::Value(v) => {
                let mut serialized = String::new();
                if let JsValue::String(s) = v {
                    serialized.reserve(s.utf8_byte_len() + 2);
                }
                json_stringify_into(v, &mut serialized);
                (serialized, self.keep_values.then(|| v.clone()))
            }
            Leaf::Stringified(text) => {
                let text = JsString::from(text);
                let mut serialized = String::with_capacity(text.utf8_byte_len() + 2);
                quote_js_string(&text, &mut serialized);
                (serialized, self.keep_values.then(|| JsValue::String(text)))
            }
        };
        let value_bytes = serialized.len() as i64;
        // An eviction above removes another key only when this key is absent, so `pos` holds.
        self.attribute_bytes += match self.result.at(pos) {
            Some(previous) => value_bytes - previous.serialized.len() as i64,
            None => (key.utf8_byte_len() as i64) + value_bytes,
        };
        if self.attribute_bytes > self.max_bytes as i64 {
            return None;
        }
        self.result.set_at(
            pos,
            FlatEntry {
                key: key.clone(),
                value,
                serialized,
            },
        );
        if !exists {
            self.attribute_count += 1;
            if self.attribute_count == self.max_attributes {
                self.last_retained_key = self.result.last_key().cloned().unwrap_or_default();
            }
        }
        Some(())
    }
}

fn flatten_entries(
    obj: &JsValue,
    prefix: &JsString,
    max_attributes: usize,
    max_bytes: usize,
    array_mode: ArrayMode,
    keep_values: bool,
) -> Option<FlatObject> {
    let mut flattener = Flattener {
        max_attributes,
        max_bytes,
        array_mode,
        keep_values,
        nodes: 1,
        path_bytes: prefix.utf8_byte_len(),
        attribute_bytes: 0,
        attribute_count: 0,
        last_retained_key: JsString::new(),
        result: FlatObject::default(),
    };
    let mut path = prefix.clone();
    flattener.visit(obj, &mut path, 0)?;
    Some(flattener.result)
}

pub fn flatten_json_with_budget(
    obj: &JsValue,
    prefix: &JsString,
    max_attributes: usize,
    max_bytes: usize,
    array_mode: ArrayMode,
) -> Option<FlattenResult> {
    let result = flatten_entries(obj, prefix, max_attributes, max_bytes, array_mode, true)?;
    let mut values = JsObject::new();
    let mut attributes = Vec::new();
    for entry in result.into_entries() {
        values.insert(entry.key.clone(), entry.value.expect("values are kept"));
        attributes.push((entry.key, entry.serialized));
    }
    Some(FlattenResult { values, attributes })
}

fn flatten_attributes(
    obj: &JsValue,
    prefix: &JsString,
    array_mode: ArrayMode,
) -> Option<FlatAttributes> {
    let result = flatten_entries(
        obj,
        prefix,
        MAX_JSON_ATTRIBUTES,
        MAX_LOG_RECORD_BYTES,
        array_mode,
        false,
    )?;
    Some(
        result
            .into_entries()
            .map(|entry| (entry.key, entry.serialized))
            .collect(),
    )
}

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
    match flatten_attributes(value, &JsString::new(), ArrayMode::Indexed) {
        Some(attributes) => attributes,
        None => {
            record_json_enrichment_skip("flatten_budget", JsonEnrichmentSource::Body);
            Vec::new()
        }
    }
}

pub fn extract_json_attributes_from_body(body: Option<&str>) -> FlatAttributes {
    if let Some(body) = body {
        if body.len() > MAX_LOG_RECORD_BYTES {
            record_json_enrichment_skip("input_size", JsonEnrichmentSource::Body);
            return Vec::new();
        }
    }
    json_attributes_from_body_parse(&parse_log_body_for_ingestion(body))
}

/// A key with a lone surrogate merges here with a U+FFFD key, where JavaScript keeps two keys. See PORTING.md.
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
    if let Some(AvroValue::Map(attributes)) = record.get_mut("attributes") {
        for (key, value) in std::mem::take(attributes).into_entries() {
            merged.define(key, value);
        }
    }
    record.set("attributes", AvroValue::Map(merged));
}

/// Pass `body_parse` to reuse a parse of the same body.
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

/// A raw lone surrogate inside a string literal means its `\uXXXX` escape, so the text is rewritten with escapes.
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
    match flatten_attributes(&parsed, &JsString::from(key), ArrayMode::String) {
        Some(attributes) => add_json_attributes(
            record,
            attributes,
            record_bytes,
            JsonEnrichmentSource::SelectedAttribute,
        ),
        None => {
            record_json_enrichment_skip("flatten_budget", JsonEnrichmentSource::SelectedAttribute)
        }
    }
}

/// Sender attributes win over selected-attribute fields, and those win over body fields.
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
        // No enrichment changes a body, so one parse per record in this loop equals Node's parse-all-first order.
        for record in records.iter_mut() {
            let parse = parse_log_body_for_ingestion(
                record.body().filter(|b| b.len() <= MAX_LOG_RECORD_BYTES),
            );
            enrich_log_record_with_json_attributes(record, Some(&parse));
        }
    }
    pii
}

/// Cheapest first.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BufferProcessingMode {
    Passthrough,
    DecodeOnly,
    DecodeAndReencode,
}

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
