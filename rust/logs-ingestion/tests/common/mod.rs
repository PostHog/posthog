//! Fixtures are read with the crate's `json_parse`, because Node writes lone surrogates as `\udXXX`, which serde_json rejects.
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

/// Keys sorted, then assigned to a plain object, which lists array-index keys first again, as `canonicalizeAvroValue` does.
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

/// The inverse of `canonical` for one schema: a fixture's canonical record back to Avro.
pub fn avro_from_canonical(
    schema: &logs_ingestion::avro::Schema,
    value: &JsValue,
) -> logs_ingestion::avro::AvroValue {
    use logs_ingestion::avro::{AvroMap, AvroValue, Schema};
    use std::sync::Arc;
    let field = |v: &JsValue, k: &str| match v {
        JsValue::Object(o) => o.get(k).cloned().unwrap_or(JsValue::Null),
        _ => JsValue::Null,
    };
    match (schema, value) {
        (Schema::Union(branches), v) => {
            let pick = branches.iter().find(|b| {
                matches!(
                    (b, v),
                    (Schema::Null, JsValue::Null)
                        | (Schema::Boolean, JsValue::Bool(_))
                        | (Schema::String | Schema::Enum(_), JsValue::String(_))
                        | (
                            Schema::Int | Schema::Long | Schema::Float | Schema::Double,
                            JsValue::Number(_)
                        )
                        | (Schema::Array(_), JsValue::Array(_))
                        | (
                            Schema::Bytes | Schema::Fixed(_) | Schema::Map(_) | Schema::Record(_),
                            JsValue::Object(_)
                        )
                )
            });
            avro_from_canonical(pick.unwrap_or_else(|| panic!("no branch for {v:?}")), v)
        }
        (Schema::Null, _) => AvroValue::Null,
        (Schema::Boolean, JsValue::Bool(b)) => AvroValue::Boolean(*b),
        (Schema::Int, JsValue::Number(n)) => AvroValue::Int(*n as i64),
        (Schema::Long, JsValue::Number(n)) => AvroValue::Long(*n as i64),
        (Schema::Float, JsValue::Number(n)) => AvroValue::Float(*n),
        (Schema::Double, JsValue::Number(n)) => AvroValue::Double(*n),
        (Schema::String, JsValue::String(s)) => AvroValue::String(s.to_string()),
        (Schema::Bytes, v) => AvroValue::Bytes(hex::decode(string(&field(v, "$bytes"))).unwrap()),
        (Schema::Array(items), JsValue::Array(a)) => {
            AvroValue::Array(a.iter().map(|v| avro_from_canonical(items, v)).collect())
        }
        (Schema::Map(values), JsValue::Object(o)) => {
            let mut map = AvroMap::new();
            for (k, v) in o.iter() {
                map.assign(k.to_string(), avro_from_canonical(values, v));
            }
            AvroValue::Map(map)
        }
        (Schema::Record(r), v) => AvroValue::Record(
            r.fields
                .iter()
                .map(|f| {
                    (
                        Arc::from(&*f.name),
                        avro_from_canonical(&f.schema, &field(v, &f.name)),
                    )
                })
                .collect(),
        ),
        (s, v) => panic!("cannot rebuild {v:?} as {s:?}"),
    }
}
