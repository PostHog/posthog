#![cfg(feature = "mlhog-bench")]
//! Output parity between the bench-only MLHog v2 byte-scanning walk (`src/mlhog/v2`) and this
//! crate's own tree-walk scrubbers, driven over the same shared fixtures as `tests/parity.rs`.
//! Both implementations now share leaf scrubs, allow lists and blur memoization, so any divergence
//! is a routing/traversal bug in the v2 transforms — there is no acceptable scrub-content drift.
//!
//! Comparison is semantic (`serde_json::Value`), not byte-for-byte: the crate re-serializes the
//! whole event through simd-json while v2 splices bytes in place, so key order and number
//! formatting may differ without being a real divergence. For `cv` events the two sides also gzip
//! independently re-serialized bytes (and v2 recompresses only the sub-fields that changed, while
//! the crate recompresses every gzipped sub-field once any changed), so compressed payloads are
//! gunzipped before comparing.
//!
//! Run: cargo test -p replay-anonymizer-node --features mlhog-bench --test mlhog_parity

use std::io::{Read, Write};
use std::path::Path;

use replay_anonymizer_node::allow_lists::AllowLists;
use replay_anonymizer_node::anonymize_event_str;
use replay_anonymizer_node::context::Ctx;
use replay_anonymizer_node::mlhog::V2Worker;
use serde_json::Value;

fn fixtures(name: &str) -> Vec<Value> {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name);
    let data = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {path:?}: {e}"));
    serde_json::from_str(&data).unwrap_or_else(|e| panic!("parse {path:?}: {e}"))
}

fn allow_of(case: &Value) -> AllowLists {
    let allow = &case["allow"];
    let strings = |key: &str| -> Vec<String> {
        allow[key]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str().map(str::to_string))
                    .collect()
            })
            .unwrap_or_default()
    };
    AllowLists::new(strings("text"), strings("url"))
}

/// Run one event line through the v2 walk. `None` = the walk dropped the line (fail closed).
fn v2_scrub(allow: &AllowLists, event_json: &str) -> Option<Value> {
    let ctx = Ctx::new(allow);
    let mut worker = V2Worker::default();
    let mut out = Vec::new();
    worker.scrub_line(&ctx, event_json.as_bytes(), &mut out);
    if out.is_empty() {
        return None;
    }
    Some(serde_json::from_slice(&out).unwrap_or_else(|e| {
        panic!(
            "v2 emitted invalid JSON: {e}\n{}",
            String::from_utf8_lossy(&out)
        )
    }))
}

fn assert_event_parity(allow: &AllowLists, event_json: &str, label: &str) {
    let crate_out = anonymize_event_str(allow, event_json);
    let v2_out = v2_scrub(allow, event_json);
    match (crate_out, v2_out) {
        (Ok(s), Some(mut actual)) => {
            let mut expected: Value = serde_json::from_str(&s).unwrap();
            normalize_cv(&mut expected);
            normalize_cv(&mut actual);
            assert_eq!(actual, expected, "case: {label}");
        }
        // Both fail closed (the crate errors the message, v2 drops the line) — parity holds.
        (Err(_), None) => {}
        (Ok(s), None) => panic!("case {label}: v2 dropped an event the crate scrubbed to {s}"),
        (Err(e), Some(v)) => panic!("case {label}: crate failed ({e}) but v2 emitted {v}"),
    }
}

#[test]
fn event_fixtures_match_the_crate_scrubbers() {
    for case in fixtures("events.json") {
        let allow = allow_of(&case);
        let event_json = serde_json::to_string(&case["event"]).unwrap();
        assert_event_parity(&allow, &event_json, case["name"].as_str().unwrap_or("?"));
    }
}

#[test]
fn message_fixture_events_match_the_crate_scrubbers() {
    // The message fixtures carry the malformed/edge events (null data, missing type, unknown
    // source); drive each event as its own v2 line against the crate's single-event scrub.
    for case in fixtures("messages.json") {
        let name = case["name"].as_str().unwrap_or("?");
        for (window, events) in case["message"].as_object().expect("message object") {
            for (i, event) in events.as_array().expect("event array").iter().enumerate() {
                let event_json = serde_json::to_string(event).unwrap();
                assert_event_parity(&allow_of(&case), &event_json, &format!("{name} [{window}/{i}]"));
            }
        }
    }
}

// ---- cv (compressed) events: not covered by the shared fixtures (the TS suite covers cv through
// its own unit tests), so parity is asserted on synthesized events here. ----

fn gzip_latin1(json: &str) -> String {
    let mut gz = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
    gz.write_all(json.as_bytes()).unwrap();
    gz.finish().unwrap().iter().map(|&b| b as char).collect()
}

fn gunzip_latin1(s: &str) -> Value {
    let raw: Vec<u8> = s
        .chars()
        .map(|c| u8::try_from(c as u32).expect("latin-1 gzip byte"))
        .collect();
    let mut json = Vec::new();
    flate2::read::GzDecoder::new(&raw[..])
        .read_to_end(&mut json)
        .expect("gunzip cv payload");
    serde_json::from_slice(&json).expect("cv payload is JSON")
}

/// Replace gzipped `cv` payloads with their decoded JSON so the comparison is semantic. The two
/// implementations compress independently serialized bytes (and v2 skips recompressing unchanged
/// mutation sub-fields), so the gzip strings legitimately differ byte-wise.
fn normalize_cv(event: &mut Value) {
    let compressed = event.get("cv").is_some_and(|v| !v.is_null());
    if !compressed {
        return;
    }
    match event.get("type").and_then(Value::as_u64) {
        Some(2) => {
            if let Some(s) = event["data"].as_str().map(str::to_string) {
                event["data"] = gunzip_latin1(&s);
            }
        }
        Some(3) => {
            let Some(data) = event.get_mut("data").and_then(Value::as_object_mut) else {
                return;
            };
            for key in ["texts", "attributes", "adds"] {
                let decoded = data
                    .get(key)
                    .and_then(Value::as_str)
                    .filter(|s| !s.is_empty())
                    .map(gunzip_latin1);
                if let Some(d) = decoded {
                    data[key] = d;
                }
            }
        }
        _ => {}
    }
}

#[test]
fn compressed_full_snapshot_matches_the_crate_scrubbers() {
    let allow = AllowLists::new(["keep"], Vec::<String>::new());
    let payload = r#"{"node":{"type":0,"childNodes":[{"type":3,"textContent":"keep secret"}]},"initialOffset":{"top":0,"left":0}}"#;
    let event = serde_json::json!({
        "type": 2,
        "timestamp": 1_700_000_000_000u64,
        "cv": "2024-10",
        "data": gzip_latin1(payload),
    });
    assert_event_parity(
        &allow,
        &serde_json::to_string(&event).unwrap(),
        "compressed full snapshot",
    );
}

#[test]
fn compressed_mutation_subfields_match_the_crate_scrubbers() {
    let allow = AllowLists::new(["keep"], Vec::<String>::new());
    // texts changes; attributes decompresses but is untouched (v2 keeps its original gzip bytes,
    // the crate recompresses it — normalize_cv makes both comparable); adds is an empty string and
    // must be kept verbatim.
    let event = serde_json::json!({
        "type": 3,
        "timestamp": 1_700_000_000_000u64,
        "cv": "2024-10",
        "data": {
            "source": 0,
            "texts": gzip_latin1(r#"[{"id":5,"value":"keep secret"}]"#),
            "attributes": gzip_latin1(r#"[{"id":6,"attributes":{"class":"btn"}}]"#),
            "adds": "",
            "removes": [],
        },
    });
    assert_event_parity(
        &allow,
        &serde_json::to_string(&event).unwrap(),
        "compressed mutation",
    );
}

#[test]
fn null_cv_marker_routes_as_uncompressed() {
    // `cv: null` means "not compressed" (crate::event::is_compressed_marker); both sides must scrub
    // the object data in place rather than treating it as a gzip string.
    let allow = AllowLists::new(["keep"], Vec::<String>::new());
    let event = serde_json::json!({
        "type": 3,
        "cv": null,
        "data": {
            "source": 0,
            "texts": [{"id": 5, "value": "keep secret"}],
        },
    });
    assert_event_parity(
        &allow,
        &serde_json::to_string(&event).unwrap(),
        "null cv marker",
    );
}
