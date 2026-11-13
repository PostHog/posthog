//! Replays the `pii_scrub`, `pattern` and `normalize` vectors that Node recorded in
//! `nodejs/src/logs/parity/fixtures/modules` (see `logs-module-parity.test.ts`).

mod common;

use std::sync::Arc;

use common::{array, cases, get, string, try_get};
use logs_ingestion::avro::{AvroMap, AvroValue};
use logs_ingestion::js::{JsObject, JsString, JsValue};
use logs_ingestion::normalize::{transform_decoded_log_records_in_place, LogsSettings};
use logs_ingestion::pattern::build_log_pattern;
use logs_ingestion::pii::scrub_plain_string_with_stats;
use logs_ingestion::record::LogRecord;

fn number(value: &JsValue) -> f64 {
    match value {
        JsValue::Number(n) => *n,
        other => panic!("not a number: {other:?}"),
    }
}

fn short(text: &str) -> String {
    text.chars().take(80).collect()
}

#[test]
fn pii_scrub_matches_node() {
    let cases = cases("pii_scrub");
    assert_eq!(cases.len(), 44);
    for (input, output) in cases {
        let input = string(&input);
        let (scrubbed, n) = scrub_plain_string_with_stats(&input);
        assert_eq!(
            scrubbed,
            string(get(&output, "output")),
            "{:?}",
            short(&input)
        );
        assert_eq!(
            n as f64,
            number(get(&output, "piiReplacements")),
            "{:?}",
            short(&input)
        );
    }
}

#[test]
fn pattern_matches_node() {
    let cases = cases("pattern");
    assert_eq!(cases.len(), 132);
    for (input, output) in cases {
        let body = string(get(&input, "body"));
        let keys: Vec<String> = array(get(&input, "keys")).iter().map(string).collect();
        let keys: Vec<&str> = keys.iter().map(String::as_str).collect();
        let result = build_log_pattern(Some(&body), &keys);
        let ctx = format!("{:?} keys {keys:?}", short(&body));

        assert_eq!(
            JsString::from(result.pattern.as_str()),
            *get(&output, "pattern").as_js_string().unwrap(),
            "pattern {ctx}"
        );
        assert_eq!(
            result.body_kind.as_str(),
            string(get(&output, "bodyKind")),
            "kind {ctx}"
        );
        assert_eq!(
            JsValue::Bool(result.input_capped),
            *get(&output, "inputCapped"),
            "capped {ctx}"
        );
        assert_eq!(
            result.masked_length as f64,
            number(get(&output, "maskedLength")),
            "len {ctx}"
        );
        assert_eq!(
            result.json_key_count.map(|n| n as f64),
            try_get(&output, "jsonKeyCount").map(number),
            "key count {ctx}"
        );
        let fires: Vec<f64> = array(get(&output, "ruleFires"))
            .iter()
            .map(number)
            .collect();
        let actual: Vec<f64> = result.rule_fires.iter().map(|&n| n as f64).collect();
        assert_eq!(actual, fires, "rule fires {ctx}");
    }
}

fn settings_from_js(value: &JsValue) -> LogsSettings {
    let bool_of = |key: &str| match try_get(value, key) {
        Some(JsValue::Bool(b)) => Some(*b),
        None => None,
        other => panic!("{key}: {other:?}"),
    };
    LogsSettings {
        json_parse_logs: bool_of("json_parse_logs"),
        pii_scrub_logs: bool_of("pii_scrub_logs"),
        json_parse_logs_attribute_key: try_get(value, "json_parse_logs_attribute_key").map(string),
        ..LogsSettings::default()
    }
}

fn hex_decode(text: &str) -> Vec<u8> {
    (0..text.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&text[i..i + 2], 16).unwrap())
        .collect()
}

fn avro_from_js(value: &JsValue) -> AvroValue {
    match value {
        JsValue::Null => AvroValue::Null,
        JsValue::Bool(b) => AvroValue::Boolean(*b),
        JsValue::Number(n) => AvroValue::Long(*n as i64),
        JsValue::String(s) => AvroValue::String(s.to_string()),
        JsValue::Object(o) => {
            if let Some(JsValue::String(hex)) = o.get("$bytes") {
                return AvroValue::Bytes(hex_decode(&hex.to_string()));
            }
            let mut map = AvroMap::new();
            for (k, v) in o.iter() {
                map.define(k.to_string(), avro_from_js(v));
            }
            AvroValue::Map(map)
        }
        JsValue::Array(_) => panic!("records hold no arrays"),
    }
}

/// The harness's `recordToJson`: bytes as `{ $bytes: hex }`, map key order kept.
fn avro_to_js(value: &AvroValue) -> JsValue {
    match value {
        AvroValue::Null => JsValue::Null,
        AvroValue::Boolean(b) => JsValue::Bool(*b),
        AvroValue::Int(n) | AvroValue::Long(n) => JsValue::Number(*n as f64),
        AvroValue::Float(f) | AvroValue::Double(f) => JsValue::Number(*f),
        AvroValue::String(s) | AvroValue::Enum(s) => JsValue::string(s),
        AvroValue::Bytes(b) | AvroValue::Fixed(b) => {
            let mut o = JsObject::new();
            let hex: String = b.iter().map(|x| format!("{x:02x}")).collect();
            o.insert_str("$bytes", JsValue::string(&hex));
            JsValue::Object(o)
        }
        AvroValue::Map(m) => {
            let mut o = JsObject::new();
            for (k, v) in m.iter() {
                o.insert_str(k, avro_to_js(v));
            }
            JsValue::Object(o)
        }
        other => panic!("unexpected record value {other:?}"),
    }
}

fn record_from_js(value: &JsValue) -> LogRecord {
    let JsValue::Object(o) = value else {
        panic!("record is not an object");
    };
    let fields = o
        .iter()
        .map(|(k, v)| (Arc::from(k.to_string().as_str()), avro_from_js(v)))
        .collect();
    LogRecord::from_value(AvroValue::Record(fields))
}

fn record_to_js(record: &LogRecord) -> JsValue {
    let mut o = JsObject::new();
    for (k, v) in record.fields.iter().chain(record.extra.iter()) {
        o.insert_str(k, avro_to_js(v));
    }
    JsValue::Object(o)
}

#[test]
fn normalize_matches_node() {
    let cases = cases("normalize");
    assert_eq!(cases.len(), 209);
    for (i, (input, output)) in cases.into_iter().enumerate() {
        let settings = settings_from_js(get(&input, "settings"));
        let mut records = vec![record_from_js(get(&input, "record"))];
        let pii = transform_decoded_log_records_in_place(&mut records, &settings);
        // Compared with key order: the attribute order is what flatten eviction depends on.
        assert_eq!(
            record_to_js(&records[0]),
            *get(&output, "record"),
            "case {i} settings {settings:?}"
        );
        assert_eq!(
            pii.pii_replacements as f64,
            number(get(&output, "pii_replacements")),
            "case {i}"
        );
    }
}
