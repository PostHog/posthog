//! Replays `tests/fixtures/re2-reference.json`, which `scripts/node-re2-reference.js` records from
//! node-re2: whether each pattern compiles, and `test` on each input.

use std::path::PathBuf;

use logs_ingestion::js::{json_parse, JsValue};
use logs_ingestion::property_filter::re2::Re2;

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

#[test]
fn re2_port_matches_node_re2() {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/re2-reference.json");
    let fixture = json_parse(&std::fs::read_to_string(path).unwrap()).unwrap();
    // node-re2 writes a lone surrogate in the input as U+FFFD.
    let inputs: Vec<String> = arr(get(&fixture, "inputs"))
        .iter()
        .map(|v| v.as_js_string().unwrap().to_utf8_lossy().into_owned())
        .collect();
    let mut failures = Vec::new();
    let cases = arr(get(&fixture, "cases"));
    for case in cases {
        let pattern = get(case, "pattern").as_js_string().unwrap();
        let flags = get(case, "flags").as_js_string().unwrap().to_string();
        let compiles = get(case, "compiles") == &JsValue::Bool(true);
        let re = Re2::new(pattern.bytes_wtf8(), &flags);
        if re.is_ok() != compiles {
            failures.push(format!(
                "{pattern:?}/{flags}: compiles {} in Rust, {compiles} in node-re2 ({:?})",
                re.is_ok(),
                re.err()
            ));
            continue;
        }
        let Ok(re) = re else { continue };
        for (input, expected) in inputs.iter().zip(arr(get(case, "results"))) {
            let actual = re.test(input);
            if JsValue::Bool(actual) != *expected {
                failures.push(format!("{pattern:?}/{flags} on {input:?}: Rust {actual}"));
            }
        }
    }
    assert!(cases.len() > 300);
    assert!(
        failures.is_empty(),
        "{} mismatches:\n{}",
        failures.len(),
        failures.join("\n")
    );
}
