//! Replays the seeded Node corpus in `tests/fixtures/fuzz` (from `scripts/fuzz-generate.ts`).
//! The comparison is semantic, as the parity contract in PORTING.md states: numbers compare as
//! doubles, also inside JSON text, and two errors match whatever their text.

mod common;

use std::collections::HashMap;
use std::sync::Arc;

use base64::Engine;
use common::{array, canonical_text, get, load_json, string, try_get};
use logs_ingestion::attribute_value::{decode_log_attribute_value, encode_log_attribute_value};
use logs_ingestion::avro::{decode_container, AvroMap, AvroValue};
use logs_ingestion::internal_logs::{InternalLogsVerifier, InternalSourcePolicy};
use logs_ingestion::js::{
    date_parse, json_parse, json_stringify, number_to_string, JsObject, JsString, JsValue,
};
use logs_ingestion::metric_rules::{
    build_metric_rules_otlp_payload, compile_metric_rules, tally_records,
    with_default_metric_rules, BatchTallies, MetricRuleRow, MetricRuleSource,
};
use logs_ingestion::normalize::{transform_decoded_log_records_in_place, LogsSettings};
use logs_ingestion::pattern::build_log_pattern;
use logs_ingestion::pii::scrub_plain_string_with_stats;
use logs_ingestion::record::LogRecord;
use logs_ingestion::retention::{
    compile_retention_rule_set, evaluate_retention_days, RetentionRuleRow,
};
use logs_ingestion::sampling::{compile_rule_set, evaluate_log_record, SamplingRuleRow};
use sha2::{Digest, Sha256};

fn cases(name: &str) -> Vec<(JsValue, JsValue)> {
    // `FUZZ_DIR` replays a larger corpus written with `FUZZ_BUDGET=0`.
    let dir = std::env::var("FUZZ_DIR").map_or_else(
        |_| common::repo_path("rust/logs-ingestion/tests/fixtures/fuzz"),
        std::path::PathBuf::from,
    );
    let path = dir.join(format!("{name}.json"));
    let file = load_json(&path);
    let cases: Vec<_> = array(get(&file, "cases"))
        .iter()
        .map(|c| (get(c, "input").clone(), get(c, "output").clone()))
        .collect();
    assert!(!cases.is_empty(), "{name}: no cases");
    cases
}

fn assert_none(area: &str, mismatches: Vec<String>) {
    assert!(
        mismatches.is_empty(),
        "{area}: {} mismatches\n{}",
        mismatches.len(),
        mismatches
            .iter()
            .take(5)
            .cloned()
            .collect::<Vec<_>>()
            .join("\n")
    );
}

fn num(v: &JsValue) -> f64 {
    match v {
        JsValue::Number(n) => *n,
        other => panic!("not a number: {other:?}"),
    }
}

fn opt_string(v: &JsValue) -> Option<String> {
    (*v != JsValue::Null).then(|| string(v))
}

/// Deep equality where numbers compare as doubles and strings also match when both hold JSON
/// that is the same in this sense.
fn same(a: &JsValue, b: &JsValue) -> bool {
    match (a, b) {
        (JsValue::String(x), JsValue::String(y)) => same_text(x, y),
        (JsValue::Array(x), JsValue::Array(y)) => {
            x.len() == y.len() && x.iter().zip(y).all(|(p, q)| same(p, q))
        }
        (JsValue::Object(x), JsValue::Object(y)) => {
            x.len() == y.len()
                && x.iter()
                    .zip(y.iter())
                    .all(|((k1, v1), (k2, v2))| k1 == k2 && same(v1, v2))
        }
        // `JSON.stringify` writes NaN and Infinity as null.
        (JsValue::Number(x), JsValue::Null) | (JsValue::Null, JsValue::Number(x)) => !x.is_finite(),
        _ => a == b,
    }
}

fn same_text(a: &JsString, b: &JsString) -> bool {
    if a == b {
        return true;
    }
    match (a.as_str().map(json_parse), b.as_str().map(json_parse)) {
        (Some(Ok(x)), Some(Ok(y))) => !matches!(x, JsValue::String(_)) && same(&x, &y),
        _ => false,
    }
}

fn same_str(a: &str, b: &str) -> bool {
    same_text(&JsString::from(a), &JsString::from(b))
}

fn avro_from_json(v: &JsValue) -> AvroValue {
    match v {
        JsValue::Null => AvroValue::Null,
        JsValue::Bool(b) => AvroValue::Boolean(*b),
        JsValue::Number(x) if x.fract() == 0.0 => AvroValue::Long(*x as i64),
        JsValue::Number(x) => AvroValue::Double(*x),
        JsValue::String(x) => AvroValue::String(x.to_utf8_lossy().into_owned()),
        JsValue::Object(o) => {
            if let Some(JsValue::String(hex)) = o.get("$bytes") {
                return AvroValue::Bytes(hex::decode(hex.to_string()).unwrap());
            }
            let mut map = AvroMap::new();
            for (k, v) in o.iter() {
                map.assign(k.to_utf8_lossy().into_owned(), avro_from_json(v));
            }
            AvroValue::Map(map)
        }
        JsValue::Array(items) => AvroValue::Array(items.iter().map(avro_from_json).collect()),
    }
}

fn record_from_json(v: &JsValue) -> LogRecord {
    let JsValue::Object(o) = v else {
        panic!("record")
    };
    let fields = o
        .iter()
        .map(|(k, v)| (Arc::from(&*k.to_utf8_lossy()), avro_from_json(v)))
        .collect();
    LogRecord::from_value(AvroValue::Record(fields))
}

fn avro_to_js(value: &AvroValue) -> JsValue {
    match value {
        AvroValue::Null => JsValue::Null,
        AvroValue::Boolean(b) => JsValue::Bool(*b),
        AvroValue::Int(n) | AvroValue::Long(n) => JsValue::Number(*n as f64),
        AvroValue::Float(f) | AvroValue::Double(f) => JsValue::Number(*f),
        AvroValue::String(s) | AvroValue::Enum(s) => JsValue::string(s),
        AvroValue::Bytes(b) | AvroValue::Fixed(b) => {
            let mut o = JsObject::new();
            o.insert_str("$bytes", JsValue::string(&hex::encode(b)));
            JsValue::Object(o)
        }
        AvroValue::Map(m) => {
            let mut o = JsObject::new();
            for (k, v) in m.iter() {
                o.insert_str(k, avro_to_js(v));
            }
            JsValue::Object(o)
        }
        AvroValue::Array(a) => JsValue::Array(a.iter().map(avro_to_js).collect()),
        AvroValue::Record(_) => panic!("nested record"),
    }
}

fn record_to_js(record: &LogRecord) -> JsValue {
    let mut o = JsObject::new();
    for (k, v) in record.fields.iter().chain(record.extra.iter()) {
        o.insert_str(k, avro_to_js(v));
    }
    JsValue::Object(o)
}

#[test]
fn json_numbers_and_dates() {
    let mut bad = Vec::new();
    for (input, output) in cases("json") {
        let Some(text) = input.as_js_string().and_then(JsString::as_str) else {
            continue;
        };
        let actual = json_parse(text)
            .ok()
            .map(|v| JsString::from(json_stringify(&v)));
        let ok = match (&actual, get(&output, "ok")) {
            (Some(a), JsValue::Bool(true)) => {
                same_text(a, get(&output, "s").as_js_string().unwrap())
            }
            (None, JsValue::Bool(false)) => true,
            _ => false,
        };
        if !ok {
            bad.push(format!("JSON {text:?}: rust {actual:?}"));
        }
    }
    for (input, output) in cases("numbers") {
        let x = f64::from_bits(u64::from_str_radix(&string(&input), 16).unwrap());
        let actual = number_to_string(x);
        if !same_str(&actual, &string(&output)) && !(x.is_nan() && actual == "NaN") {
            bad.push(format!(
                "String({x:e}): node {} rust {actual}",
                string(&output)
            ));
        }
    }
    for (input, output) in cases("date") {
        let expected = match output {
            JsValue::Number(n) => Some(n),
            _ => None,
        };
        let actual = date_parse(&string(&input));
        if actual != expected {
            bad.push(format!(
                "Date.parse({:?}): node {expected:?} rust {actual:?}",
                string(&input)
            ));
        }
    }
    assert_none("json/numbers/date", bad);
}

#[test]
fn text_stages() {
    let mut bad = Vec::new();
    for (input, output) in cases("pii") {
        let (out, n) = scrub_plain_string_with_stats(&string(&input));
        if out != string(get(&output, "output")) || n as f64 != num(get(&output, "piiReplacements"))
        {
            bad.push(format!("pii {:?}", string(&input)));
        }
    }
    for (input, output) in cases("pattern") {
        let body = opt_string(get(&input, "body"));
        let keys: Vec<String> = array(get(&input, "keys")).iter().map(string).collect();
        let keys: Vec<&str> = keys.iter().map(String::as_str).collect();
        let res = build_log_pattern(body.as_deref(), &keys);
        let fires: Vec<f64> = array(get(&output, "ruleFires")).iter().map(num).collect();
        let ok = res.pattern
            == get(&output, "pattern")
                .as_js_string()
                .unwrap()
                .to_utf8_lossy()
            && res.body_kind.as_str() == string(get(&output, "bodyKind"))
            && JsValue::Bool(res.input_capped) == *get(&output, "inputCapped")
            && res.masked_length as f64 == num(get(&output, "maskedLength"))
            && res.json_key_count.map(|n| n as f64) == try_get(&output, "jsonKeyCount").map(num)
            && res.rule_fires.iter().map(|&n| n as f64).collect::<Vec<_>>() == fires;
        if !ok {
            bad.push(format!("pattern {body:?}"));
        }
    }
    for (input, output) in cases("attribute_value") {
        let text = string(&input);
        let decoded = decode_log_attribute_value(&text);
        let encoded = encode_log_attribute_value(&text);
        if !same_text(&decoded, get(&output, "decoded").as_js_string().unwrap())
            || !same_str(&encoded, &string(get(&output, "encoded")))
        {
            bad.push(format!("attribute value {text:?}"));
        }
    }
    let policies = HashMap::from([
        (
            "hog_flow".to_string(),
            InternalSourcePolicy {
                billed: false,
                team_rules: false,
            },
        ),
        (
            "billed_src".to_string(),
            InternalSourcePolicy {
                billed: true,
                team_rules: true,
            },
        ),
    ]);
    for (input, output) in cases("internal") {
        let verifier = InternalLogsVerifier::new(
            &string(get(&input, "keys")),
            &string(get(&input, "teams")),
            policies.clone(),
        );
        let actual = verifier
            .verify(
                opt_string(get(&input, "signature")).as_deref(),
                num(get(&input, "team_id")) as i64,
                opt_string(get(&input, "created_at")).as_deref(),
            )
            .map(|a| (a.source, a.billed, a.team_rules));
        let expected = (output != JsValue::Null).then(|| {
            (
                string(get(&output, "source")),
                *get(&output, "billed") == JsValue::Bool(true),
                *get(&output, "teamRules") == JsValue::Bool(true),
            )
        });
        if actual != expected {
            bad.push(format!(
                "internal {}: node {expected:?} rust {actual:?}",
                json_stringify(&input)
            ));
        }
    }
    assert_none("text stages", bad);
}

#[test]
fn normalize() {
    let mut bad = Vec::new();
    for (i, (input, output)) in cases("normalize").into_iter().enumerate() {
        // Keys that merge once lossy are a documented gap.
        if *get(&output, "gap") == JsValue::Bool(true) {
            continue;
        }
        let settings = get(&input, "settings");
        let flag = |key: &str| match try_get(settings, key) {
            Some(JsValue::Bool(b)) => Some(*b),
            _ => None,
        };
        let settings = LogsSettings {
            json_parse_logs: flag("json_parse_logs"),
            pii_scrub_logs: flag("pii_scrub_logs"),
            json_parse_logs_attribute_key: try_get(settings, "json_parse_logs_attribute_key")
                .map(string),
            ..LogsSettings::default()
        };
        let mut records = vec![record_from_json(get(&input, "record"))];
        let pii = transform_decoded_log_records_in_place(&mut records, &settings);
        if !same(&record_to_js(&records[0]), get(&output, "record"))
            || pii.pii_replacements as f64 != num(get(&output, "pii_replacements"))
        {
            bad.push(format!("normalize case {i}"));
        }
    }
    assert_none("normalize", bad);
}

#[test]
fn sampling_and_retention() {
    let mut bad = Vec::new();
    for (i, (input, output)) in cases("sampling").into_iter().enumerate() {
        let rows: Vec<SamplingRuleRow> = array(get(&input, "rules"))
            .iter()
            .map(|v| SamplingRuleRow {
                id: string(get(v, "id")),
                rule_type: string(get(v, "rule_type")),
                scope_service: opt_string(get(v, "scope_service")),
                scope_path_pattern: opt_string(get(v, "scope_path_pattern")),
                scope_attribute_filters: get(v, "scope_attribute_filters").clone(),
                config: get(v, "config").clone(),
                version: None,
            })
            .collect();
        let compiled = compile_rule_set(&rows);
        let Ok(compiled) = compiled else {
            if try_get(&output, "compile_error").is_none() {
                bad.push(format!("sampling case {i}: rust compile error"));
            }
            continue;
        };
        if try_get(&output, "compile_error").is_some() {
            bad.push(format!("sampling case {i}: node compile error"));
            continue;
        }
        for (rec, out) in array(get(&input, "records")).iter().zip(array(&output)) {
            let actual = match evaluate_log_record(Some(&compiled), &record_from_json(rec)) {
                Ok(res) => format!("{}/{:?}", res.decision.as_str(), res.rule_id),
                Err(_) => "threw".to_string(),
            };
            let expected = match try_get(out, "threw") {
                Some(_) => "threw".to_string(),
                None => format!(
                    "{}/{:?}",
                    string(get(out, "decision")),
                    opt_string(get(out, "ruleId"))
                ),
            };
            if actual != expected {
                bad.push(format!("sampling case {i}: node {expected} rust {actual}"));
            }
        }
    }
    for (i, (input, output)) in cases("retention").into_iter().enumerate() {
        let rows: Vec<RetentionRuleRow> = array(get(&input, "rules"))
            .iter()
            .map(|v| RetentionRuleRow {
                id: string(get(v, "id")),
                config: get(v, "config").clone(),
                version: None,
            })
            .collect();
        let compiled = compile_retention_rule_set(&rows);
        let Ok(compiled) = compiled else {
            if try_get(&output, "compile_error").is_none() {
                bad.push(format!("retention case {i}: rust compile error"));
            }
            continue;
        };
        if try_get(&output, "compile_error").is_some() {
            bad.push(format!("retention case {i}: node compile error"));
            continue;
        }
        for (rec, out) in array(get(&input, "records")).iter().zip(array(&output)) {
            let actual = match evaluate_retention_days(Some(&compiled), &record_from_json(rec)) {
                Ok(d) => format!("{d:?}"),
                Err(_) => "threw".to_string(),
            };
            let expected = match out {
                JsValue::Null => "None".to_string(),
                JsValue::Number(n) => format!("Some({n})"),
                _ => "threw".to_string(),
            };
            if actual != expected {
                bad.push(format!("retention case {i}: node {expected} rust {actual}"));
            }
        }
    }
    assert_none("sampling/retention", bad);
}

#[test]
fn metric_rules() {
    let mut bad = Vec::new();
    for (i, (input, output)) in cases("metrics").into_iter().enumerate() {
        let rows: Vec<MetricRuleRow> = array(get(&input, "rules"))
            .iter()
            .map(|v| match v {
                JsValue::Object(o) => MetricRuleRow::from_js(o),
                _ => panic!("rule row"),
            })
            .collect();
        let Ok(mut rules) = compile_metric_rules(&rows) else {
            if try_get(&output, "compile_error").is_none() {
                bad.push(format!("metrics case {i}: rust compile error"));
            }
            continue;
        };
        if try_get(&output, "compile_error").is_some() {
            bad.push(format!("metrics case {i}: node compile error"));
            continue;
        }
        match get(&input, "defaults") {
            JsValue::String(d) if *d == "logs" => {
                rules = with_default_metric_rules(rules, MetricRuleSource::Logs)
            }
            JsValue::String(_) => rules = with_default_metric_rules(rules, MetricRuleSource::Spans),
            _ => {}
        }
        let records: Vec<LogRecord> = array(get(&input, "records"))
            .iter()
            .map(record_from_json)
            .collect();
        let now = num(get(&input, "now_ms"));
        let mut tallies = BatchTallies::new();
        let mut admit = |_: &str, label_key: &str| !label_key.contains("deny");
        let threw = tally_records(&rules, &records, &mut tallies, now, Some(&mut admit)).is_err();
        let payload = build_metric_rules_otlp_payload(&rules, &tallies, now);
        let payload_ok = match (payload, get(&output, "payload_json")) {
            (None, JsValue::Null) => true,
            (Some(p), JsValue::String(text)) => text
                .as_str()
                .and_then(|t| json_parse(t).ok())
                .is_some_and(|n| same(&p, &n)),
            _ => false,
        };
        let mut overflow = JsObject::new();
        for (rule_id, count) in tallies.series_overflow.iter() {
            overflow.insert_str(rule_id, JsValue::Number(*count as f64));
        }
        if !payload_ok
            || threw != (*get(&output, "threw") != JsValue::Null)
            || tallies.value_skipped as f64 != num(get(&output, "value_skipped"))
            || tallies.eval_errors as f64 != num(get(&output, "eval_errors"))
            || JsValue::Object(overflow) != *get(&output, "series_overflow")
        {
            bad.push(format!("metrics case {i}"));
        }
    }
    assert_none("metrics", bad);
}

#[test]
fn avro_decode() {
    let mut bad = Vec::new();
    for (i, (input, output)) in cases("avro").into_iter().enumerate() {
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(string(get(&input, "b64")))
            .unwrap();
        let schema_intact = *get(&input, "schema_intact") == JsValue::Bool(true);
        let ok = match (decode_container(&bytes), try_get(&output, "error")) {
            (Err(_), Some(_)) => true,
            (Ok(c), None) => {
                c.codec == string(get(&output, "codec"))
                    && c.records.len() as f64 == num(get(&output, "count"))
                    && hex::encode(Sha256::digest(canonical_text(&c.records).as_bytes()))
                        == string(get(&output, "sha256"))
            }
            // avsc's writer-schema validation is a documented gap.
            _ => !schema_intact,
        };
        if !ok {
            bad.push(format!("avro case {i} ({})", string(get(&input, "label"))));
        }
    }
    assert_none("avro", bad);
}
