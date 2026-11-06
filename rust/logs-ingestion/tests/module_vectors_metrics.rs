use std::cmp::Ordering;
use std::path::PathBuf;
use std::sync::Arc;

use logs_ingestion::avro::{AvroMap, AvroValue};
use logs_ingestion::js::{json_parse, json_stringify, JsObject, JsString, JsValue};
use logs_ingestion::metric_rules::{
    build_metric_rules_otlp_payload, compile_metric_rules, id_to_hex, resolve_label_value,
    tally_records, with_default_metric_rules, BatchTallies, LabelValue, MetricRuleRow,
    MetricRuleSource, MetricSeriesAdmission,
};
use logs_ingestion::record::LogRecord;

fn load(path: PathBuf) -> JsValue {
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {path:?}: {e}"));
    json_parse(&text).unwrap_or_else(|e| panic!("parse {path:?}: {e}"))
}

fn get<'a>(value: &'a JsValue, key: &str) -> &'a JsValue {
    match value {
        JsValue::Object(o) => o.get(key).unwrap_or_else(|| panic!("missing key {key}")),
        _ => panic!("not an object looking up {key}"),
    }
}

fn array(value: &JsValue) -> &[JsValue] {
    match value {
        JsValue::Array(items) => items,
        other => panic!("not an array: {other:?}"),
    }
}

fn object(value: &JsValue) -> &JsObject {
    match value {
        JsValue::Object(o) => o,
        other => panic!("not an object: {other:?}"),
    }
}

fn number(value: &JsValue) -> f64 {
    match value {
        JsValue::Number(n) => *n,
        other => panic!("not a number: {other:?}"),
    }
}

fn js_string(value: &JsValue) -> JsString {
    value.as_js_string().expect("a string").clone()
}

/// The default JavaScript sort: by UTF-16 code units.
fn js_sort_cmp(a: &JsString, b: &JsString) -> Ordering {
    let units = |s: &JsString| -> Vec<u16> {
        let mut out = Vec::new();
        for unit in s.chars_or_surrogates() {
            match unit.as_char() {
                Ok(c) => {
                    let mut buf = [0u16; 2];
                    out.extend_from_slice(c.encode_utf16(&mut buf));
                }
                Err(surrogate) => out.push(surrogate),
            }
        }
        out
    };
    units(a).cmp(&units(b))
}

/// Keys sorted, then assigned to a new object, which lists array-index keys first again.
fn canonicalize(value: &JsValue) -> JsValue {
    match value {
        JsValue::Array(items) => JsValue::Array(items.iter().map(canonicalize).collect()),
        JsValue::Object(o) => {
            let mut keys: Vec<JsString> = o.keys().collect();
            keys.sort_by(js_sort_cmp);
            let mut out = JsObject::new();
            for key in keys {
                let v = canonicalize(o.get(&key.to_utf8_lossy()).expect("own key"));
                out.insert(key, v);
            }
            JsValue::Object(out)
        }
        other => other.clone(),
    }
}

fn record_from_json(value: &JsValue) -> LogRecord {
    let to_avro = |v: &JsValue| -> AvroValue {
        match v {
            JsValue::Null => AvroValue::Null,
            JsValue::Bool(b) => AvroValue::Boolean(*b),
            JsValue::Number(n) => AvroValue::Long(*n as i64),
            JsValue::String(s) => AvroValue::String(s.to_utf8_lossy().into_owned()),
            JsValue::Object(o) => match o.get("$bytes") {
                Some(JsValue::String(hex)) => {
                    AvroValue::Bytes(hex::decode(hex.to_utf8_lossy().as_bytes()).unwrap())
                }
                _ => {
                    let mut map = AvroMap::new();
                    for (k, v) in o.iter() {
                        let JsValue::String(s) = v else {
                            panic!("map value {v:?}")
                        };
                        map.assign(
                            k.to_utf8_lossy().into_owned(),
                            AvroValue::String(s.to_utf8_lossy().into_owned()),
                        );
                    }
                    AvroValue::Map(map)
                }
            },
            JsValue::Array(_) => panic!("unexpected array in a record"),
        }
    };
    let fields = object(value)
        .iter()
        .map(|(k, v)| (Arc::from(&*k.to_utf8_lossy()), to_avro(v)))
        .collect();
    LogRecord::from_value(AvroValue::Record(fields))
}

#[test]
fn metric_tally_matches_node() {
    let file = load(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../nodejs/src/logs/parity/fixtures/modules/metric_tally.json"),
    );
    let cases = array(get(&file, "cases"));
    assert!(!cases.is_empty());
    let mut passed = 0;
    for (index, case) in cases.iter().enumerate() {
        let input = get(case, "input");
        let expected = get(case, "output");
        let rows: Vec<MetricRuleRow> = array(get(input, "rules"))
            .iter()
            .map(|r| MetricRuleRow::from_js(object(r)))
            .collect();
        let with_defaults = matches!(get(input, "with_default_rules"), JsValue::Bool(true));
        let now_ms = number(get(input, "now_ms"));
        let records: Vec<LogRecord> = array(get(input, "records"))
            .iter()
            .map(record_from_json)
            .collect();

        let mut rules = compile_metric_rules(&rows).expect("compiles");
        if with_defaults {
            rules = with_default_metric_rules(rules, MetricRuleSource::Logs);
        }
        let mut tallies = BatchTallies::new();
        let mut admit = |_: &str, _: &str| true;
        tally_records(&rules, &records, &mut tallies, now_ms, Some(&mut admit)).expect("no throw");
        let overflow: u64 = tallies.series_overflow.values().sum();

        let mut actual = JsObject::new();
        let payload = build_metric_rules_otlp_payload(&rules, &tallies, now_ms);
        actual.insert_str(
            "payload",
            payload.as_ref().map(canonicalize).unwrap_or(JsValue::Null),
        );
        actual.insert_str(
            "value_skipped",
            JsValue::Number(tallies.value_skipped as f64),
        );
        actual.insert_str("eval_errors", JsValue::Number(tallies.eval_errors as f64));
        actual.insert_str("series_overflow", JsValue::Number(overflow as f64));
        let actual = JsValue::Object(actual);
        assert_eq!(
            json_stringify(&actual),
            json_stringify(expected),
            "case {index} (rules {}, defaults {with_defaults})",
            json_stringify(get(input, "rules"))
        );
        passed += 1;
    }
    assert_eq!(passed, cases.len());
}

fn reference() -> JsValue {
    load(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests/fixtures/metric-rules-reference.json"),
    )
}

#[test]
fn label_truncation_matches_node() {
    let fixture = reference();
    let cases = array(get(&fixture, "labels"));
    assert!(!cases.is_empty());
    for case in cases {
        let attribute = js_string(get(case, "attribute"));
        let mut map = AvroMap::new();
        map.assign(
            "v".to_string(),
            AvroValue::String(attribute.to_utf8_lossy().into_owned()),
        );
        let record = LogRecord::from_value(AvroValue::Record(vec![(
            Arc::from("attributes"),
            AvroValue::Map(map),
        )]));
        let label = resolve_label_value(&JsString::from("attributes.v"), &record).unwrap();
        let LabelValue::String(label) = label else {
            panic!("not a string label")
        };
        assert_eq!(label.utf16_len() as f64, number(get(case, "length")));
        // The label key is what reaches JSON, so compare it as Node wrote it.
        let key = json_stringify(&JsValue::Array(vec![JsValue::String(label)]));
        assert_eq!(
            key,
            js_string(get(case, "label_key")).to_utf8_lossy(),
            "{attribute:?}"
        );
    }
}

#[test]
fn id_to_hex_matches_node() {
    let fixture = reference();
    for case in array(get(&fixture, "id_to_hex")) {
        let input =
            hex::decode(js_string(get(case, "input_hex")).to_utf8_lossy().as_bytes()).unwrap();
        let expected_bytes = number(get(case, "expected_bytes")) as usize;
        let expected = match get(case, "output") {
            JsValue::Null => None,
            v => Some(js_string(v).to_utf8_lossy().into_owned()),
        };
        let buffer = if input.is_empty() {
            None
        } else {
            Some(&input[..])
        };
        assert_eq!(id_to_hex(buffer, expected_bytes), expected, "{input:02x?}");
    }
}

fn hash_key(fixture: &JsValue) -> [u8; 32] {
    let bytes = hex::decode(
        js_string(get(fixture, "hmac_key_hex"))
            .to_utf8_lossy()
            .as_bytes(),
    )
    .unwrap();
    bytes.try_into().unwrap()
}

#[test]
fn label_hash_matches_node() {
    let fixture = reference();
    let admission = MetricSeriesAdmission::with_hash_key(1, 1, 1, hash_key(&fixture));
    for case in array(get(&fixture, "label_hashes")) {
        let label_key = js_string(get(case, "label_key"))
            .to_utf8_lossy()
            .into_owned();
        assert_eq!(
            admission.hash_label_key(&label_key) as f64,
            number(get(case, "hash")),
            "{label_key}"
        );
    }
}

#[test]
fn series_admission_matches_node() {
    let fixture = reference();
    let scenarios = array(get(&fixture, "admission"));
    assert!(!scenarios.is_empty());
    for scenario in scenarios {
        let caps: Vec<usize> = array(get(scenario, "caps"))
            .iter()
            .map(|c| number(c) as usize)
            .collect();
        let mut admission =
            MetricSeriesAdmission::with_hash_key(caps[0], caps[1], caps[2], hash_key(&fixture));
        let calls = array(get(scenario, "calls"));
        let results = array(get(scenario, "results"));
        for (i, call) in calls.iter().enumerate() {
            let call = array(call);
            let team_id = number(&call[0]) as i64;
            let rule_id = js_string(&call[1]).to_utf8_lossy().into_owned();
            let label_key = js_string(&call[2]).to_utf8_lossy().into_owned();
            let now_ms = number(&call[3]);
            let actual = admission.admit(team_id, &rule_id, &label_key, now_ms);
            assert_eq!(
                JsValue::Bool(actual),
                results[i],
                "{} call {i}: {team_id} {rule_id} {label_key} {now_ms}",
                json_stringify(get(scenario, "name"))
            );
        }
    }
}

#[test]
fn payload_bytes_match_node() {
    let fixture = reference();
    let cases = array(get(&fixture, "payloads"));
    assert!(!cases.is_empty());
    for (index, case) in cases.iter().enumerate() {
        let rows: Vec<MetricRuleRow> = array(get(case, "rows"))
            .iter()
            .map(|r| MetricRuleRow::from_js(object(r)))
            .collect();
        let mut rules = compile_metric_rules(&rows).expect("compiles");
        match get(case, "defaults") {
            JsValue::String(s) if *s == "logs" => {
                rules = with_default_metric_rules(rules, MetricRuleSource::Logs)
            }
            JsValue::String(_) => rules = with_default_metric_rules(rules, MetricRuleSource::Spans),
            _ => {}
        }
        let records: Vec<LogRecord> = array(get(case, "records"))
            .iter()
            .map(record_from_json)
            .collect();
        let now_ms = number(get(case, "now_ms"));
        let mut tallies = BatchTallies::new();
        let mut admit = |_: &str, label_key: &str| !label_key.contains("deny");
        let threw = tally_records(&rules, &records, &mut tallies, now_ms, Some(&mut admit))
            .err()
            .map(|e| JsValue::string(&e.to_string()))
            .unwrap_or(JsValue::Null);
        assert_eq!(threw, *get(case, "threw"), "threw {index}");

        let payload =
            build_metric_rules_otlp_payload(&rules, &tallies, now_ms).map(|p| json_stringify(&p));
        let expected = match get(case, "payload_json") {
            JsValue::Null => None,
            v => Some(js_string(v).to_utf8_lossy().into_owned()),
        };
        assert_eq!(payload, expected, "payload {index}");
        assert_eq!(
            tallies.value_skipped as f64,
            number(get(case, "value_skipped")),
            "value_skipped {index}"
        );
        assert_eq!(
            tallies.eval_errors as f64,
            number(get(case, "eval_errors")),
            "eval_errors {index}"
        );
        let mut overflow = JsObject::new();
        for (rule_id, count) in tallies.series_overflow.iter() {
            overflow.insert_str(rule_id, JsValue::Number(*count as f64));
        }
        assert_eq!(
            JsValue::Object(overflow),
            *get(case, "series_overflow"),
            "series_overflow {index}"
        );
    }
}

#[test]
fn compile_row_validation_matches_node() {
    let fixture = reference();
    let rows: Vec<MetricRuleRow> = array(get(&fixture, "compile_rows"))
        .iter()
        .map(|r| MetricRuleRow::from_js(object(r)))
        .collect();
    let compiled: Vec<JsValue> = compile_metric_rules(&rows)
        .unwrap()
        .into_iter()
        .map(|r| {
            let mut o = JsObject::new();
            o.insert_str("id", JsValue::string(&r.id));
            o.insert_str("metric_name", JsValue::String(r.metric_name));
            o.insert_str("source", JsValue::string(r.source.as_str()));
            o.insert_str(
                "value_attribute",
                r.value_attribute.map_or(JsValue::Null, JsValue::String),
            );
            o.insert_str(
                "group_by",
                JsValue::Array(r.group_by.into_iter().map(JsValue::String).collect()),
            );
            JsValue::Object(o)
        })
        .collect();
    assert_eq!(JsValue::Array(compiled), *get(&fixture, "compile"));
}
