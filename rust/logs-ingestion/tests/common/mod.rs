//! Helpers shared by the parity tests. Fixtures are read with the crate's own `json_parse`,
//! because Node writes lone surrogates as `\udXXX`, which serde_json rejects.
#![allow(dead_code)]

use std::cmp::Ordering;
use std::path::PathBuf;

use logs_ingestion::avro::AvroValue;
use logs_ingestion::js::{json_parse, json_stringify, JsObject, JsString, JsValue};

pub fn repo_path(relative: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(relative)
}

pub fn modules_dir() -> PathBuf {
    repo_path("nodejs/src/logs/parity/fixtures/modules")
}

pub fn scenarios_dir() -> PathBuf {
    repo_path("nodejs/src/logs/parity/fixtures/scenarios")
}

pub fn load_json(path: &PathBuf) -> JsValue {
    let text = std::fs::read_to_string(path).unwrap_or_else(|e| panic!("read {path:?}: {e}"));
    // Fixtures split secret-shaped test tokens with U+E000 so secret scanners skip them.
    json_parse(&text.replace('\u{E000}', "")).unwrap_or_else(|e| panic!("parse {path:?}: {e}"))
}

pub fn get<'a>(value: &'a JsValue, key: &str) -> &'a JsValue {
    match value {
        JsValue::Object(o) => o.get(key).unwrap_or_else(|| panic!("missing key {key}")),
        _ => panic!("not an object looking up {key}"),
    }
}

pub fn try_get<'a>(value: &'a JsValue, key: &str) -> Option<&'a JsValue> {
    match value {
        JsValue::Object(o) => o.get(key),
        _ => None,
    }
}

pub fn array(value: &JsValue) -> &[JsValue] {
    match value {
        JsValue::Array(items) => items,
        other => panic!("not an array: {other:?}"),
    }
}

pub fn string(value: &JsValue) -> String {
    match value {
        JsValue::String(s) => s.to_string(),
        other => panic!("not a string: {other:?}"),
    }
}

/// `{ cases: [{ input, output }] }` from a module vector file.
pub fn cases(name: &str) -> Vec<(JsValue, JsValue)> {
    let file = load_json(&modules_dir().join(format!("{name}.json")));
    array(get(&file, "cases"))
        .iter()
        .map(|c| (get(c, "input").clone(), get(c, "output").clone()))
        .collect()
}

/// The default JavaScript sort: by UTF-16 code units.
pub fn js_sort_cmp(a: &str, b: &str) -> Ordering {
    a.encode_utf16().cmp(b.encode_utf16())
}

/// The Node harness's `canonicalizeAvroValue`: keys sorted, then assigned to a plain object
/// (which lists array-index keys first again), bytes as `{ $bytes: hex }`.
pub fn canonical(value: &AvroValue) -> JsValue {
    let object = |entries: Vec<(String, JsValue)>| {
        let mut entries = entries;
        entries.sort_by(|(a, _), (b, _)| js_sort_cmp(a, b));
        let mut o = JsObject::new();
        for (k, v) in entries {
            o.insert(JsString::from(k), v);
        }
        JsValue::Object(o)
    };
    let bytes = |b: &[u8]| {
        let hex: String = b.iter().map(|x| format!("{x:02x}")).collect();
        object(vec![("$bytes".to_string(), JsValue::string(&hex))])
    };
    match value {
        AvroValue::Null => JsValue::Null,
        AvroValue::Boolean(b) => JsValue::Bool(*b),
        AvroValue::Int(n) | AvroValue::Long(n) => JsValue::Number(*n as f64),
        AvroValue::Float(f) | AvroValue::Double(f) => JsValue::Number(*f),
        AvroValue::Bytes(b) | AvroValue::Fixed(b) => bytes(b),
        AvroValue::String(s) | AvroValue::Enum(s) => JsValue::string(s),
        AvroValue::Array(items) => JsValue::Array(items.iter().map(canonical).collect()),
        AvroValue::Map(m) => object(
            m.iter()
                .map(|(k, v)| (k.to_string(), canonical(v)))
                .collect(),
        ),
        AvroValue::Record(fields) => object(
            fields
                .iter()
                .map(|(k, v)| (k.to_string(), canonical(v)))
                .collect(),
        ),
    }
}

pub fn canonical_text(records: &[AvroValue]) -> String {
    json_stringify(&JsValue::Array(records.iter().map(canonical).collect()))
}
