//! Replays the `pii_scrub`, `pattern` and `normalize` vectors that Node recorded in
//! `nodejs/src/logs/parity/fixtures/modules` (see `logs-module-parity.test.ts`).

mod common;

use common::{array, cases, get, record_from_js, record_to_js, string, try_get};
use logs_ingestion::js::{JsString, JsValue};
use logs_ingestion::normalize::{transform_decoded_log_records_in_place, LogsSettings};
use logs_ingestion::pattern::build_log_pattern;
use logs_ingestion::pii::scrub_plain_string_with_stats;

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
