//! Replays the Node vectors in `nodejs/src/logs/parity/fixtures/modules` for the rule modules:
//! sampling, retention, the internal-logs verifier and content weights. The inputs mirror
//! `buildCases` in `nodejs/src/logs/parity/logs-module-parity.test.ts`.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use logs_ingestion::avro::{AvroMap, AvroValue};
use logs_ingestion::content_weights::measure_content_weights;
use logs_ingestion::internal_logs::{
    sign_internal_logs, InternalLogsVerifier, InternalSourcePolicy,
};
use logs_ingestion::js::{json_parse, JsValue};
use logs_ingestion::record::LogRecord;
use logs_ingestion::retention::{
    compile_retention_rule_set, evaluate_retention_days, RetentionRuleRow,
};
use logs_ingestion::sampling::{compile_rule_set, evaluate_log_record, SamplingRuleRow};

/// `Date.UTC(2025, 0, 15, 12, 37, 13, 250)`.
const NOW_MS: f64 = 1_736_944_633_250.0;

fn cases(name: &str) -> Vec<(JsValue, JsValue)> {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../nodejs/src/logs/parity/fixtures/modules")
        .join(format!("{name}.json"));
    let file = json_parse(&std::fs::read_to_string(&path).unwrap()).unwrap();
    arr(get(&file, "cases"))
        .iter()
        .map(|c| (get(c, "input").clone(), get(c, "output").clone()))
        .collect()
}

fn get<'a>(v: &'a JsValue, key: &str) -> &'a JsValue {
    match v {
        JsValue::Object(o) => o.get(key).unwrap_or_else(|| panic!("missing {key}")),
        _ => panic!("not an object looking up {key}"),
    }
}

fn arr(v: &JsValue) -> &[JsValue] {
    match v {
        JsValue::Array(a) => a,
        other => panic!("not an array: {other:?}"),
    }
}

fn opt_string(v: &JsValue) -> Option<String> {
    match v {
        JsValue::Null => None,
        JsValue::String(s) => Some(s.to_string()),
        other => panic!("not a string or null: {other:?}"),
    }
}

/// A record in the vectors: bytes as `{ $bytes: hex }`, map key order kept.
fn record_from_json(v: &JsValue) -> LogRecord {
    let JsValue::Object(o) = v else {
        panic!("record is not an object")
    };
    let fields = o
        .iter()
        .map(|(k, v)| (Arc::from(k.to_string().as_str()), avro_from_json(v)))
        .collect();
    LogRecord::from_value(AvroValue::Record(fields))
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
                map.assign(k.to_string(), avro_from_json(v));
            }
            AvroValue::Map(map)
        }
        JsValue::Array(items) => AvroValue::Array(items.iter().map(avro_from_json).collect()),
    }
}

fn sampling_row(r: &JsValue) -> SamplingRuleRow {
    SamplingRuleRow {
        id: opt_string(get(r, "id")).unwrap(),
        rule_type: opt_string(get(r, "rule_type")).unwrap(),
        scope_service: opt_string(get(r, "scope_service")),
        scope_path_pattern: opt_string(get(r, "scope_path_pattern")),
        scope_attribute_filters: get(r, "scope_attribute_filters").clone(),
        config: get(r, "config").clone(),
        version: None,
    }
}

#[test]
fn sampling_evaluate_matches_node() {
    let cases = cases("sampling_evaluate");
    assert_eq!(cases.len(), 360);
    for (i, (input, output)) in cases.iter().enumerate() {
        let rows: Vec<SamplingRuleRow> =
            arr(get(input, "rules")).iter().map(sampling_row).collect();
        let rule_set = compile_rule_set(&rows).unwrap();
        let record = record_from_json(get(input, "record"));
        let result = evaluate_log_record(Some(&rule_set), &record).unwrap();
        assert_eq!(
            result.decision.as_str(),
            opt_string(get(output, "decision")).unwrap(),
            "case {i}"
        );
        assert_eq!(
            result.rule_id,
            opt_string(get(output, "ruleId")),
            "case {i}"
        );
    }
}

#[test]
fn retention_evaluate_matches_node() {
    let cases = cases("retention_evaluate");
    assert_eq!(cases.len(), 475);
    for (i, (input, output)) in cases.iter().enumerate() {
        let rows: Vec<RetentionRuleRow> = arr(get(input, "rules"))
            .iter()
            .map(|r| RetentionRuleRow {
                id: opt_string(get(r, "id")).unwrap(),
                config: get(r, "config").clone(),
                version: None,
            })
            .collect();
        let rule_set = compile_retention_rule_set(&rows).unwrap();
        let record = record_from_json(get(input, "record"));
        let expected = match output {
            JsValue::Null => None,
            JsValue::Number(n) => Some(*n as i64),
            other => panic!("unexpected output {other:?}"),
        };
        assert_eq!(
            evaluate_retention_days(Some(&rule_set), &record).unwrap(),
            expected,
            "case {i}"
        );
    }
}

#[test]
fn content_weights_match_node() {
    let cases = cases("content_weights");
    assert_eq!(cases.len(), 3);
    for (i, (input, output)) in cases.iter().enumerate() {
        let records: Vec<LogRecord> = arr(input).iter().map(record_from_json).collect();
        let expected: Vec<f64> = arr(output)
            .iter()
            .map(|v| match v {
                JsValue::Number(n) => *n,
                other => panic!("not a number: {other:?}"),
            })
            .collect();
        // Exact f64 equality: the shared resource bytes divide into fractional weights.
        assert_eq!(measure_content_weights(&records), expected, "case {i}");
    }
}

#[test]
fn internal_verify_matches_node() {
    let verifier = InternalLogsVerifier::new(
        "k1,k0",
        "1,2",
        HashMap::from([
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
        ]),
    );
    let cases = cases("internal_verify");
    assert_eq!(cases.len(), 16);
    for (i, (input, output)) in cases.iter().enumerate() {
        let signature = opt_string(get(input, "signature"));
        let team_id = match get(input, "team_id") {
            JsValue::Number(n) => *n as i64,
            other => panic!("team_id {other:?}"),
        };
        let created_at = opt_string(get(input, "created_at"));
        let actual = verifier.verify(signature.as_deref(), team_id, created_at.as_deref());
        let expected = match output {
            JsValue::Null => None,
            o => Some((
                opt_string(get(o, "source")).unwrap(),
                get(o, "billed") == &JsValue::Bool(true),
                get(o, "teamRules") == &JsValue::Bool(true),
            )),
        };
        assert_eq!(
            actual.map(|a| (a.source, a.billed, a.team_rules)),
            expected,
            "case {i}: {signature:?}"
        );
    }
    // The signer gives the bytes Node signed for case 1: key k1, team 1, two seconds before NOW.
    let signed = sign_internal_logs("k1", "hog_flow", 1, NOW_MS - 2000.0).unwrap();
    assert_eq!(Some(signed), opt_string(get(&cases[1].0, "signature")));
    let signed_old_key = sign_internal_logs("k0", "hog_flow", 1, NOW_MS - 2000.0).unwrap();
    assert_eq!(
        Some(signed_old_key),
        opt_string(get(&cases[2].0, "signature"))
    );
}
