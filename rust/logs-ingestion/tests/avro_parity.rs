//! Compares with avsc's decodes in `tests/fixtures/input-decodes.json`, from `scripts/node-decode-reference.js`.

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

/// The production schema files have the logical types and the record doc first, as capture-logs writes them.
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
        let again = Schema::parse_json(&schema.to_avsc_json())
            .unwrap()
            .to_avsc_json();
        assert_eq!(again, schema.to_avsc_json());
        let _ = json_parse(&again).unwrap();
    }
}

#[test]
fn a_deep_chain_of_named_records_is_rejected_without_overflow() {
    let mut branches =
        vec![r#"{"type":"record","name":"R0","fields":[{"name":"f","type":"int"}]}"#.to_string()];
    for i in 1..20_000 {
        branches.push(format!(
            r#"{{"type":"record","name":"R{i}","fields":[{{"name":"f","type":"R{}"}}]}}"#,
            i - 1
        ));
    }
    assert!(Schema::parse_json(&format!("[{}]", branches.join(","))).is_err());

    // Each redefinition of `R` refers to the previous one, so the chain still grows.
    let mut redefined = vec![r#"{"type":"record","name":"R","fields":[]}"#.to_string()];
    redefined.extend(std::iter::repeat_n(
        r#"{"type":"record","name":"R","fields":[{"name":"a","type":"R"},{"name":"b","type":{"type":"record","name":"R","fields":[]}}]}"#.to_string(),
        20_000,
    ));
    assert!(Schema::parse_json(&format!("[{}]", redefined.join(","))).is_err());

    // A shallow redefinition passes the depth check, so only the duplicate name stops it, as in avsc.
    let duplicate =
        r#"[{"type":"record","name":"R","fields":[]},{"type":"record","name":"R","fields":[]}]"#;
    let err = Schema::parse_json(duplicate).unwrap_err().to_string();
    assert!(err.contains("duplicate type name: R"), "{err}");
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
    // Varints that overflow 2^53 and 2^64, and two past the 10 bytes that avsc reads.
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

fn zstd_container(schema: &[u8], blocks: &[(i64, Vec<u8>)]) -> Vec<u8> {
    let sync = [7u8; 16];
    let mut buf = b"Obj\x01".to_vec();
    buf.extend(encode_long(2));
    for (key, value) in [(&b"avro.schema"[..], schema), (b"avro.codec", b"zstandard")] {
        buf.extend(encode_long(key.len() as i64));
        buf.extend_from_slice(key);
        buf.extend(encode_long(value.len() as i64));
        buf.extend_from_slice(value);
    }
    buf.push(0);
    buf.extend_from_slice(&sync);
    for (count, data) in blocks {
        buf.extend(encode_long(*count));
        buf.extend(encode_long(data.len() as i64));
        buf.extend_from_slice(data);
        buf.extend_from_slice(&sync);
    }
    buf
}

const STRING_RECORD: &[u8] =
    br#"{"type":"record","name":"R","fields":[{"name":"a","type":"string"}]}"#;

#[test]
fn block_counts_do_not_drive_allocation_before_decompression() {
    // About 1 MB of blocks that each claim 4096 records would reserve ~20 GB if counts were trusted.
    let blocks = vec![(4096, Vec::new()); 60_000];
    assert!(decode_container(&zstd_container(STRING_RECORD, &blocks)).is_err());
}

#[test]
fn empty_array_items_share_one_budget_per_container() {
    let schema = br#"{"type":"record","name":"R","fields":[{"name":"a","type":{"type":"array","items":"null"}}]}"#;
    let record = |items: i64| [encode_long(items), encode_long(0)].concat();
    let block = |items: i64| (1, zstd::bulk::compress(&record(items), 1).unwrap());
    assert!(decode_container(&zstd_container(schema, &[block(1000)])).is_ok());
    // Four bytes declare four billion items.
    assert!(decode_container(&zstd_container(schema, &[block(4_000_000_000)])).is_err());
    // Each block stays under the cap, and the two together pass it.
    assert!(decode_container(&zstd_container(schema, &[block(600_000), block(600_000)])).is_err());

    // Each record holds two of the one before, so 31 levels expand one record into 2^31 empty values.
    let mut records = vec![r#"{"type":"record","name":"R0","fields":[]}"#.to_string()];
    for i in 1..=30 {
        records.push(format!(
            r#"{{"type":"record","name":"R{i}","fields":[{{"name":"a","type":"R{p}"}},{{"name":"b","type":"R{p}"}}]}}"#,
            p = i - 1
        ));
    }
    let doubling = format!(
        r#"{{"type":"record","name":"Top","fields":[{{"name":"u","type":[{}]}}]}}"#,
        records.join(",")
    );
    let last_branch = encode_long(30);
    let block = (1, zstd::bulk::compress(&last_branch, 1).unwrap());
    assert!(decode_container(&zstd_container(doubling.as_bytes(), &[block])).is_err());
}

#[test]
fn zstd_frames_above_the_default_window_limit_are_rejected() {
    let mut records = Vec::new();
    for i in 0..300 {
        let value = format!("{i:04}").repeat(250);
        records.extend(encode_long(value.len() as i64));
        records.extend_from_slice(value.as_bytes());
    }
    let frame = zstd::bulk::compress(&records, 1).unwrap();
    // Rewrite the single-segment header as a windowed one that declares a 2^28 window.
    let descriptor = frame[4];
    assert_eq!(
        descriptor & 0x23,
        0x20,
        "expected a single-segment frame without a dictionary"
    );
    let content_size: u64 = match descriptor >> 6 {
        1 => u64::from(u16::from_le_bytes([frame[5], frame[6]])) + 256,
        2 => u64::from(u32::from_le_bytes(frame[5..9].try_into().unwrap())),
        other => panic!("unexpected content size flag {other}"),
    };
    let header_len = 5 + if descriptor >> 6 == 1 { 2 } else { 4 };
    let mut windowed = frame[..4].to_vec();
    windowed.push((2 << 6) | (descriptor & 0x04));
    windowed.push((28 - 10) << 3);
    windowed.extend_from_slice(&(content_size as u32).to_le_bytes());
    windowed.extend_from_slice(&frame[header_len..]);

    let accepted = zstd_container(STRING_RECORD, &[(300, frame)]);
    assert_eq!(decode_container(&accepted).unwrap().records.len(), 300);
    let rejected = zstd_container(STRING_RECORD, &[(300, windowed)]);
    assert!(decode_container(&rejected).is_err());
}
