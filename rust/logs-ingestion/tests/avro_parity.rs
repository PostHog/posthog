//! Decodes the corpus inputs and crafted edge containers, and compares with what Node's avsc
//! decodes (`tests/fixtures/input-decodes.json`, from `scripts/node-decode-reference.js`).

mod common;

use base64::Engine;
use common::{array, canonical_text, get, load_json, repo_path, scenarios_dir, string, try_get};
use logs_ingestion::avro::{decode_container, encode_container, Schema};
use logs_ingestion::js::{json_parse, json_stringify, JsValue};
use sha2::{Digest, Sha256};

fn sha256_hex(text: &str) -> String {
    Sha256::digest(text.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

fn check(label: &str, bytes: &[u8], expected: &JsValue) {
    let result = decode_container(bytes);
    match try_get(expected, "error") {
        Some(error) => {
            let err = result
                .err()
                .unwrap_or_else(|| panic!("{label}: expected error {error:?}"));
            assert_eq!(err.to_string(), string(error), "{label}");
        }
        None => {
            let container = result.unwrap_or_else(|e| panic!("{label}: {e}"));
            assert_eq!(container.codec, string(get(expected, "codec")), "{label}");
            assert_eq!(
                container.records.len() as f64,
                match get(expected, "count") {
                    JsValue::Number(n) => *n,
                    _ => panic!(),
                },
                "{label}"
            );
            assert_eq!(
                sha256_hex(&canonical_text(&container.records)),
                string(get(expected, "sha256")),
                "{label}: canonical records differ"
            );
            // Decode, encode, decode again gives the same records.
            let encoded =
                encode_container(&container.schema, "zstandard", &container.records).unwrap();
            let again = decode_container(&encoded).unwrap();
            assert_eq!(again.records, container.records, "{label}: round trip");
        }
    }
}

fn reference() -> JsValue {
    load_json(&repo_path(
        "rust/logs-ingestion/tests/fixtures/input-decodes.json",
    ))
}

#[test]
fn corpus_inputs_decode_like_avsc() {
    let reference = reference();
    let mut checked = 0;
    for entry in std::fs::read_dir(scenarios_dir()).unwrap() {
        let path = entry.unwrap().path();
        let file = path.file_name().unwrap().to_string_lossy().to_string();
        let fixture = load_json(&path);
        let expected = array(get(&reference, &file));
        let messages: Vec<&JsValue> = array(get(get(&fixture, "scenario"), "batches"))
            .iter()
            .flat_map(|b| array(b).iter())
            .collect();
        assert_eq!(
            messages.len(),
            expected.len(),
            "{file}: rerun the reference script"
        );
        for (i, (message, expected)) in messages.iter().zip(expected).enumerate() {
            let JsValue::String(b64) = get(message, "value_b64") else {
                continue;
            };
            let bytes = base64::engine::general_purpose::STANDARD
                .decode(b64.to_string())
                .unwrap();
            check(&format!("{file}[{i}]"), &bytes, expected);
            checked += 1;
        }
    }
    assert!(checked > 300, "only {checked} inputs");
}

#[test]
fn edge_containers_decode_like_avsc() {
    let reference = reference();
    let edges = array(get(&reference, "edges"));
    assert!(edges.len() >= 15);
    for edge in edges {
        let name = string(get(edge, "name"));
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(string(get(edge, "value_b64")))
            .unwrap();
        check(&name, &bytes, get(edge, "result"));
    }
}

fn as_serde(value: &JsValue) -> serde_json::Value {
    serde_json::from_str(&json_stringify(value)).unwrap()
}

/// avsc writes the schema it read back with its own export rules. The production schema files
/// have the logical types and the record doc first, as capture-logs writes them.
#[test]
fn schema_export_matches_avsc_for_the_production_schemas() {
    let mut expected_by_name = std::collections::HashMap::new();
    for entry in std::fs::read_dir(scenarios_dir()).unwrap() {
        let fixture = load_json(&entry.unwrap().path());
        for output in array(get(get(&fixture, "expected"), "outputs")) {
            let value = get(output, "value");
            if string(get(value, "kind")) == "avro" {
                let schema = get(value, "schema");
                expected_by_name.insert(string(get(schema, "name")), as_serde(schema));
            }
        }
    }
    for name in ["logs", "traces"] {
        let path = repo_path(&format!(
            "nodejs/src/logs/parity/fixtures/schemas/{name}.avsc.json"
        ));
        let text = std::fs::read_to_string(path).unwrap();
        let schema = Schema::parse_json(&text).unwrap();
        let exported: serde_json::Value = serde_json::from_str(&schema.to_avsc_json()).unwrap();
        let record_name = exported["name"].as_str().unwrap().to_string();
        assert_eq!(
            Some(&exported),
            expected_by_name.get(&record_name),
            "{name}: exported schema differs from what avsc wrote"
        );
        // The export is stable when read back, as avsc's is.
        let again = Schema::parse_json(&schema.to_avsc_json())
            .unwrap()
            .to_avsc_json();
        assert_eq!(again, schema.to_avsc_json());
        let _ = json_parse(&again).unwrap();
    }
}

#[test]
fn decode_never_panics_on_corrupt_containers() {
    let schema = Schema::parse_json(
        r#"{"type":"record","name":"R","fields":[
            {"name":"s","type":["null","string"]},{"name":"b","type":"bytes"},
            {"name":"l","type":"long"},{"name":"i","type":"int"},
            {"name":"m","type":{"type":"map","values":"string"}},
            {"name":"a","type":{"type":"array","items":"long"}},
            {"name":"e","type":{"type":"enum","name":"E","symbols":["x","y"]}},
            {"name":"f","type":{"type":"fixed","name":"F","size":4}},
            {"name":"d","type":"double"},{"name":"g","type":"float"}]}"#,
    )
    .unwrap();
    let mut state = 0x9e37_79b9_7f4a_7c15u64;
    let mut next = move || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state
    };
    let valid = encode_container(&schema, "zstandard", &[]).unwrap();
    // Varints that overflow 2^53, 2^64 and f64, and one that decodes to NaN.
    let huge: [&[u8]; 4] = [
        &[0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x20],
        &[0xfe, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x7f],
        &[0xff; 160],
        &[[0x80; 150].as_slice(), &[0]].concat(),
    ];
    for i in 0..4000 {
        let mut payload = Vec::new();
        for _ in 0..next() % 64 {
            match next() % 4 {
                0 => payload.extend_from_slice(huge[(next() % 4) as usize]),
                1 => payload.push((next() % 256) as u8),
                _ => payload.extend_from_slice(&[0x02, (next() % 4) as u8 * 2]),
            }
        }
        let block = zstd::stream::encode_all(payload.as_slice(), 1).unwrap();
        let mut bytes = valid.clone();
        let sync = valid[valid.len() - 16..].to_vec();
        let count = huge[(next() % 4) as usize];
        bytes.extend_from_slice(if i % 3 == 0 { count } else { &[0x02] });
        bytes.extend_from_slice(&encode_long(block.len() as i64));
        bytes.extend_from_slice(&block);
        bytes.extend_from_slice(&sync);
        for _ in 0..next() % 3 {
            let at = (next() as usize) % bytes.len();
            bytes[at] ^= 1 << (next() % 8);
        }
        if i % 5 == 0 {
            bytes.truncate((next() as usize) % (bytes.len() + 1));
        }
        let result = std::panic::catch_unwind(|| decode_container(&bytes));
        assert!(result.is_ok(), "panic on case {i}");
    }
}

fn encode_long(n: i64) -> Vec<u8> {
    let mut z = ((n << 1) ^ (n >> 63)) as u64;
    let mut out = Vec::new();
    while z >= 0x80 {
        out.push((z as u8) | 0x80);
        z >>= 7;
    }
    out.push(z as u8);
    out
}
