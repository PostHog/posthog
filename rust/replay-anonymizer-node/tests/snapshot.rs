//! Tests for the byte-buffer snapshot pipeline (`snapshot.rs`).
//!
//! The streaming path is a byte scanner that must reproduce JSON.parse semantics without parsing;
//! its failure modes are *divergence* bugs (mis-spliced spans, scanner-visible vs parser-visible
//! keys, wrong dlq/drop classification), so the suite centers on a differential check against the
//! tree path plus targeted leak/contract cases.

use replay_anonymizer_node::allow_lists::AllowLists;
use replay_anonymizer_node::snapshot::{
    anonymize_kafka_payload, anonymize_kafka_payload_opts, anonymize_via_tree, AnonymizeOpts,
    AnonymizedMessage, FailKind, Failure, FLAG_ACTIVE, FLAG_CLICK, FLAG_KEYPRESS,
    FLAG_MOUSE_ACTIVITY,
};
use replay_anonymizer_node::Ctx;
use serde_json::{json, Value};
use std::path::Path;

fn run(allow: &AllowLists, payload: &str) -> Result<AnonymizedMessage, Failure> {
    let mut bytes = payload.as_bytes().to_vec();
    anonymize_kafka_payload(allow, &mut bytes)
}

fn payload_of(inner: &Value) -> String {
    serde_json::to_string(&json!({
        "distinct_id": "d-1",
        "data": serde_json::to_string(inner).unwrap(),
    }))
    .unwrap()
}

fn snapshot_message(events: Value) -> Value {
    json!({
        "event": "$snapshot_items",
        "properties": {
            "$snapshot_items": events,
            "$session_id": "s-1",
            "$window_id": "w-1",
            "$snapshot_source": "web",
            "$lib": "posthog-js",
        }
    })
}

/// Parse the output JSONL into `[windowId, event]` pairs.
fn parse_lines(lines: &[u8]) -> Vec<Value> {
    lines
        .split(|b| *b == b'\n')
        .filter(|l| !l.is_empty())
        .map(|l| serde_json::from_slice(l).expect("output line must be valid json"))
        .collect()
}

const TS0: f64 = 1_700_000_000_000.0;

#[test]
fn end_to_end_contract() {
    let allow = AllowLists::new(["hello"], Vec::<String>::new());
    let inner = snapshot_message(json!([
        // Meta: href scrubbed (authority collapsed), no flags.
        { "type": 4, "timestamp": TS0, "data": { "href": "https://foo.corp.com/path", "width": 1, "height": 1 } },
        // Input: text scrubbed; keypress + active.
        { "type": 3, "timestamp": TS0 + 1000.0, "data": { "source": 5, "id": 1, "text": "hello secret", "isChecked": false } },
        // MouseInteraction click (pass-through): click + active + mouse.
        { "type": 3, "timestamp": TS0 + 2000.5, "data": { "source": 2, "type": 2, "id": 5, "x": 1, "y": 2 } },
        // Console warn plugin: counted, payload scrubbed.
        { "type": 6, "timestamp": TS0 + 3000.0, "data": { "plugin": "rrweb/console@1", "payload": { "level": "warn", "payload": ["secret"], "trace": [] } } },
        // Filtered out: no timestamp, non-object, non-positive timestamp.
        { "type": 3, "data": { "source": 1 } },
        "junk",
        { "type": 3, "timestamp": -5, "data": { "source": 1 } },
    ]));
    let out = run(&allow, &payload_of(&inner)).expect("message anonymizes");

    let lines = parse_lines(&out.lines);
    assert_eq!(lines.len(), 4, "invalid events are filtered out");
    for line in &lines {
        assert_eq!(line[0], "w-1");
    }
    assert_eq!(
        lines[0][1]["data"]["href"],
        "https://example.com/[redacted]"
    );
    assert_eq!(lines[1][1]["data"]["text"], "hello ******");
    assert_eq!(
        lines[2][1]["data"],
        json!({ "source": 2, "type": 2, "id": 5, "x": 1, "y": 2 })
    );
    assert_eq!(lines[3][1]["data"]["payload"]["payload"][0], "******");

    let meta = &out.meta;
    assert_eq!(meta.distinct_id, "d-1");
    assert_eq!(meta.session_id, "s-1");
    assert_eq!(meta.window_id, "w-1");
    assert_eq!(meta.snapshot_source.as_deref(), Some("web"));
    assert_eq!(meta.snapshot_library.as_deref(), Some("posthog-js"));
    assert_eq!(meta.start_ts, TS0);
    assert_eq!(meta.end_ts, TS0 + 3000.0);
    assert_eq!(
        (
            meta.console_log_count,
            meta.console_warn_count,
            meta.console_error_count
        ),
        (0, 1, 0)
    );

    let flags: Vec<u8> = meta.events.iter().map(|e| e.flags).collect();
    assert_eq!(
        flags,
        vec![
            0,
            FLAG_ACTIVE | FLAG_KEYPRESS,
            FLAG_ACTIVE | FLAG_CLICK | FLAG_MOUSE_ACTIVITY,
            0,
        ]
    );
    assert_eq!(
        meta.events[0].href.as_deref(),
        Some("https://example.com/[redacted]"),
        "href meta must be the post-scrub value"
    );
    assert_eq!(meta.events[1].href, None);
    assert_eq!(
        meta.events[2].ts,
        TS0 + 2000.5,
        "fractional timestamps survive"
    );
}

#[test]
fn failure_classification_matches_the_ts_parse_step() {
    let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
    let ok_items = r#"[{"type":3,"timestamp":1700000000000,"data":{"source":1}}]"#;
    let cases: Vec<(String, FailKind)> = vec![
        ("not json".into(), FailKind::InvalidJson),
        (r#"["array"]"#.into(), FailKind::InvalidMessagePayload),
        (r#"{"data":"{}"}"#.into(), FailKind::InvalidMessagePayload),
        (r#"{"distinct_id":"d","data":5}"#.into(), FailKind::InvalidMessagePayload),
        (
            payload_of(&json!({"event": "other", "properties": {"$snapshot_items": [], "$session_id": "s"}})),
            FailKind::NonSnapshotMessage,
        ),
        (
            r#"{"distinct_id":"d","data":"not json"}"#.into(),
            FailKind::NonSnapshotMessage,
        ),
        (
            payload_of(&json!({"event": "$snapshot_items", "properties": {"$snapshot_items": []}})),
            FailKind::NonSnapshotMessage, // missing $session_id
        ),
        (
            payload_of(&json!({"event": "$snapshot_items", "properties": {"$snapshot_items": [], "$session_id": ""}})),
            FailKind::NonSnapshotMessage, // empty $session_id is falsy in the TS check
        ),
        (
            payload_of(&json!({"event": "$snapshot_items", "properties": {"$snapshot_items": {}, "$session_id": "s"}})),
            FailKind::NonSnapshotMessage, // zod: $snapshot_items must be an array
        ),
        (
            payload_of(&json!({"event": "$snapshot_items", "properties": {"$session_id": "s"}})),
            FailKind::NonSnapshotMessage, // missing $snapshot_items
        ),
        (
            serde_json::to_string(&json!({
                "distinct_id": "d",
                "data": format!(r#"{{"event":"$snapshot_items","properties":{{"$snapshot_items":{ok_items},"$session_id":"s","$window_id":7}}}}"#),
            }))
            .unwrap(),
            FailKind::NonSnapshotMessage, // zod: $window_id must be a string
        ),
        (
            payload_of(&snapshot_message(json!([]))),
            FailKind::NoValidEvents,
        ),
        (
            payload_of(&snapshot_message(json!(["junk", {"type": 3}]))),
            FailKind::NoValidEvents,
        ),
    ];
    for (payload, expected) in cases {
        let err = run(&allow, &payload).expect_err(&format!("should fail: {payload}"));
        assert_eq!(err.kind, expected, "payload: {payload}");
    }
}

#[test]
fn scrub_errors_fail_closed_for_the_whole_message() {
    let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
    // A cv event whose gzip stream is not latin-1 cannot be safely scrubbed: the message must drop,
    // including its valid sibling event — never "emit what we could".
    let inner = snapshot_message(json!([
        { "type": 3, "timestamp": TS0, "data": { "source": 1 } },
        { "type": 2, "timestamp": TS0 + 1.0, "cv": "2024-10", "data": "\u{100}bad" },
    ]));
    let err = run(&allow, &payload_of(&inner)).expect_err("must fail closed");
    assert_eq!(err.kind, FailKind::AnonymizeFailed);

    // Pathological nesting inside the event json fails closed before any recursive parse.
    let nested = format!("{}{}", "[".repeat(2000), "]".repeat(2000));
    let deep = format!(
        r#"{{"event":"$snapshot_items","properties":{{"$session_id":"s","$snapshot_items":[{{"type":2,"timestamp":1700000000000,"data":{nested}}}]}}}}"#
    );
    let payload = serde_json::to_string(&json!({"distinct_id": "d", "data": deep})).unwrap();
    let err = run(&allow, &payload).expect_err("must fail closed");
    assert_eq!(err.kind, FailKind::NonSnapshotMessage);

    // Mismatched brackets in an event's `data` (`[}`) are structurally invalid JSON; the scanner's
    // span-locator must reject them (route to the tree) rather than close the wrong container and
    // splice the invalid bytes through. The whole message fails closed, matching JSON.parse.
    let mismatched = r#"{"event":"$snapshot_items","properties":{"$session_id":"s","$snapshot_items":[{"type":3,"timestamp":1700000000000,"data":{"source":1,"x":[}]}]}}"#;
    let payload = serde_json::to_string(&json!({"distinct_id": "d", "data": mismatched})).unwrap();
    run(&allow, &payload).expect_err("mismatched brackets must fail closed");
}

#[test]
fn escaped_keys_cannot_smuggle_data_past_the_scanner() {
    let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
    // `data` parses to the key `data` — the scanner can't see that, so it must fall back to a
    // real parse and still scrub. A byte-compare router would pass the PII through verbatim.
    let inner = r#"{"event":"$snapshot_items","properties":{"$session_id":"s","$window_id":"w","$snapshot_items":[{"type":3,"timestamp":1700000000000,"\u0064ata":{"source":5,"id":1,"text":"topsecret","isChecked":false}}]}}"#;
    let payload = serde_json::to_string(&json!({"distinct_id": "d", "data": inner})).unwrap();
    let out = run(&allow, &payload).expect("anonymizes via the tree fallback");
    let lines = parse_lines(&out.lines);
    assert_eq!(lines.len(), 1);
    assert_eq!(lines[0][1]["data"]["text"], "*********");
    assert!(
        !out.lines.windows(9).any(|w| w == b"topsecret"),
        "raw PII must not survive anywhere in the output bytes"
    );

    // Escaped keys at the envelope level route the whole message through the tree path.
    let inner = r#"{"\u0065vent":"$snapshot_items","properties":{"$session_id":"s","$snapshot_items":[{"type":3,"timestamp":1700000000000,"data":{"source":5,"id":1,"text":"topsecret","isChecked":false}}]}}"#;
    let payload = serde_json::to_string(&json!({"distinct_id": "d", "data": inner})).unwrap();
    let out = run(&allow, &payload).expect("anonymizes via the tree fallback");
    assert_eq!(parse_lines(&out.lines)[0][1]["data"]["text"], "*********");
}

#[test]
fn duplicate_keys_cannot_shadow_pii_into_the_output() {
    let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
    // JSON.parse keeps the *last* duplicate; the earlier one exists only in the raw bytes. The
    // output must never contain it — a naive span memcpy would ship it to the unencrypted bucket.
    let inner = r#"{"event":"$snapshot_items","properties":{"$session_id":"s","$snapshot_items":[{"type":3,"timestamp":1700000000000,"data":{"source":5,"id":1,"text":"leakyPII","isChecked":false},"data":{"source":5,"id":1,"text":"fine","isChecked":false}}]}}"#;
    let payload = serde_json::to_string(&json!({"distinct_id": "d", "data": inner})).unwrap();
    let out = run(&allow, &payload).expect("anonymizes");
    let lines = parse_lines(&out.lines);
    assert_eq!(lines[0][1]["data"]["text"], "****");
    assert!(
        !out.lines.windows(8).any(|w| w == b"leakyPII"),
        "duplicate-key shadowed content must not survive"
    );
}

#[test]
fn pass_through_events_are_emitted_byte_exact() {
    let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
    // A scroll event never routes to a scrubber; its bytes must be memcpy'd, not re-serialized —
    // `1.50` would normalize to `1.5` through any parse/serialize round-trip.
    let inner = r#"{"event":"$snapshot_items","properties":{"$session_id":"s","$window_id":"w","$snapshot_items":[{"type":3,"timestamp":1700000000000,"data":{"source":3,"id":7,"x":1.50,"y":0}}]}}"#;
    let payload = serde_json::to_string(&json!({"distinct_id": "d", "data": inner})).unwrap();
    let out = run(&allow, &payload).expect("anonymizes");
    let text = String::from_utf8(out.lines.clone()).unwrap();
    assert!(
        text.contains(r#""x":1.50"#),
        "pass-through span must keep its original bytes: {text}"
    );
}

#[test]
fn node_objects_with_too_many_keys_decline_to_the_parse() {
    let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
    // A node with >MAX_OBJECT_KEYS unique keys must hand the event to the parse instead of running
    // the per-key duplicate scan quadratically. The parse re-serializes numbers (`1.50` -> `1.5`),
    // so the original bytes surviving means the walk handled it.
    let junk: String = (0..33).map(|i| format!(r#""k{i}":1.50,"#)).collect();
    let inner = format!(
        r#"{{"event":"$snapshot_items","properties":{{"$session_id":"s","$window_id":"w","$snapshot_items":[{{"type":2,"timestamp":1700000000000,"data":{{"node":{{{junk}"type":3,"textContent":"reach me at alice@example.com"}},"initialOffset":{{"left":0,"top":0}}}}}}]}}}}"#
    );
    let payload = serde_json::to_string(&json!({"distinct_id": "d", "data": inner})).unwrap();
    let out = run(&allow, &payload).expect("anonymizes");
    let text = String::from_utf8(out.lines.clone()).unwrap();
    assert!(
        !text.contains("1.50"),
        "many-key node must decline to the parse (which normalizes 1.50 -> 1.5): {text}"
    );
    assert!(
        !text.contains("alice@example.com"),
        "text still scrubbed: {text}"
    );
}

#[test]
fn decompress_payload_matches_the_capture_producer_format() {
    use replay_anonymizer_node::snapshot::decompress_payload;
    let body = br#"{"distinct_id":"d","data":"{}"}"#.to_vec();

    // lz4: capture writes `block::compress` output behind a 4-byte LE uncompressed-size prefix,
    // signalled by the content-encoding header.
    let compressed = lz4::block::compress(&body, None, false).unwrap();
    let mut framed = (body.len() as u32).to_le_bytes().to_vec();
    framed.extend_from_slice(&compressed);
    assert_eq!(decompress_payload(framed, Some("lz4")).unwrap(), body);

    // gzip: detected by magic bytes, no header needed.
    {
        use std::io::Write;
        let mut enc = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
        enc.write_all(&body).unwrap();
        let zipped = enc.finish().unwrap();
        assert_eq!(decompress_payload(zipped, None).unwrap(), body);
    }

    // Uncompressed passes through untouched.
    assert_eq!(decompress_payload(body.clone(), None).unwrap(), body);

    // Corrupt lz4 fails closed with the TS parse step's classification.
    let err = decompress_payload(vec![9, 0, 0, 0, 0xff, 0xff], Some("lz4")).unwrap_err();
    assert_eq!(err.kind.reason(), "invalid_compressed_data");
}

// ---------------------------------------------------------------------------
// Differential: streaming vs tree on the shared fixtures plus seeded variations.
// ---------------------------------------------------------------------------

fn fixtures(name: &str) -> Vec<Value> {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name);
    let data = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {path:?}: {e}"));
    serde_json::from_str(&data).unwrap_or_else(|e| panic!("parse {path:?}: {e}"))
}

fn allow_of(case: &Value) -> AllowLists {
    let strings = |key: &str| -> Vec<String> {
        case["allow"][key]
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

/// Deterministic xorshift64* so the fuzz corpus is reproducible.
struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545F4914F6CDD1D)
    }
    fn pick<'a, T>(&mut self, items: &'a [T]) -> &'a T {
        &items[(self.next() % items.len() as u64) as usize]
    }
    fn chance(&mut self, one_in: u64) -> bool {
        self.next().is_multiple_of(one_in)
    }
}

fn assert_stream_matches_tree(allow: &AllowLists, inner_json: &str, label: &str) {
    let payload = serde_json::to_string(&json!({"distinct_id": "d", "data": inner_json})).unwrap();
    let ctx = Ctx::new(allow);
    let tree = anonymize_via_tree(&ctx, "d", inner_json.as_bytes());

    // Both scrub engines are pinned: the parse-free byte walk (with its per-event fallbacks) and
    // the simd path.
    for byte_walk in [true, false] {
        let mut bytes = payload.as_bytes().to_vec();
        let stream = anonymize_kafka_payload_opts(
            allow,
            &mut bytes,
            AnonymizeOpts { byte_walk },
            Vec::new(),
        );
        match (&stream, &tree) {
            (Ok(s), Ok(t)) => {
                let s_lines = parse_lines(&s.lines);
                let t_lines = parse_lines(&t.lines);
                assert_eq!(
                    s_lines, t_lines,
                    "lines diverged (walk={byte_walk}): {label}"
                );
                assert_eq!(s.meta, t.meta, "meta diverged (walk={byte_walk}): {label}");
            }
            (Err(s), Err(t)) => {
                assert_eq!(
                    s.kind, t.kind,
                    "failure kind diverged (walk={byte_walk}): {label}"
                );
            }
            (s, t) => panic!(
                "outcome diverged (walk={byte_walk}) for {label}: stream={:?} tree={:?}",
                s.as_ref().map(|m| parse_lines(&m.lines)),
                t.as_ref().map(|m| parse_lines(&m.lines)),
            ),
        }
    }
}

#[test]
fn differential_stream_vs_tree() {
    // Event templates: every shared fixture event (scrub-routed shapes) plus pass-through shapes the
    // fixtures don't cover. Timestamps are injected since the scrub fixtures don't carry them.
    let event_cases = fixtures("events.json");
    let message_cases = fixtures("messages.json");

    let window_ids: &[&str] = &["w1", "", "π😀", "w\"quote\\back", "line\u{2028}sep", "\t"];
    let pass_through: &[Value] = &[
        json!({ "type": 3, "data": { "source": 1, "positions": [{"x": 1.5, "y": 2, "id": 3, "timeOffset": -20}] } }),
        json!({ "type": 3, "data": { "source": 3, "id": 7, "x": 0, "y": 142.25 } }),
        json!({ "type": 3, "data": { "source": 2, "type": 9, "id": 4, "x": 1, "y": 2 } }),
        json!({ "type": 0, "data": {} }),
        json!({ "type": 1, "data": {} }),
        json!({ "type": 3, "data": { "source": 8, "id": 1, "adds": [{"rule": "body { color: red }"}] } }),
        // Unknown/absent discriminants and odd extras.
        json!({ "type": 99, "data": { "anything": ["x", 1, null] } }),
        json!({ "data": { "source": 5, "text": "no type at all" } }),
        json!({ "type": 3, "data": "not an object" }),
        json!({ "type": 4, "data": { "href": "  https://pad.example.io/x  " } }),
    ];
    let junk_strings: &[&str] = &[
        "plain",
        "with \"quotes\" and \\backslashes\\",
        "unicode π😀\u{2028}\u{2029}",
        "control\u{1}\u{1f}",
        "email bob@example.com inside",
    ];

    let mut rng = Rng(0x5EED_CAFE_F00D_1234);
    let mut checked = 0usize;

    for case in event_cases.iter() {
        let allow = allow_of(case);
        let base_event = &case["event"];
        for round in 0..6 {
            // A message mixing the fixture event with random pass-through shapes and junk fields.
            let mut events: Vec<Value> = Vec::new();
            for i in 0..(1 + (rng.next() % 4)) {
                let mut ev = if rng.chance(2) {
                    base_event.clone()
                } else {
                    rng.pick(pass_through).clone()
                };
                if let Some(obj) = ev.as_object_mut() {
                    if !rng.chance(10) {
                        // Mostly-valid timestamps: integers and fractionals; occasionally missing.
                        let ts = TS0 + (i as f64) * 250.0 + if rng.chance(3) { 0.25 } else { 0.0 };
                        obj.insert("timestamp".into(), json!(ts));
                    }
                    if rng.chance(3) {
                        obj.insert("delay".into(), json!((rng.next() % 100) as i64));
                    }
                    if rng.chance(4) {
                        obj.insert("junk".into(), json!(*rng.pick(junk_strings)));
                    }
                    if rng.chance(5) {
                        // Float-encoded discriminant, e.g. `"type": 3.0` — must route identically.
                        if let Some(t) = obj.get("type").and_then(Value::as_i64) {
                            obj.insert("type".into(), json!(t as f64 + 0.0));
                        }
                    }
                }
                events.push(ev);
            }
            let mut message = snapshot_message(Value::Array(events));
            message["properties"]["$window_id"] = json!(*rng.pick(window_ids));
            if rng.chance(3) {
                message["properties"]["extra"] = json!(*rng.pick(junk_strings));
            }
            if rng.chance(4) {
                let obj = message["properties"].as_object_mut().unwrap();
                obj.remove("$snapshot_source");
                obj.remove("$lib");
            }
            let inner = if rng.chance(3) {
                serde_json::to_string_pretty(&message).unwrap()
            } else {
                serde_json::to_string(&message).unwrap()
            };
            assert_stream_matches_tree(
                &allow,
                &inner,
                &format!("case {} round {round}", case["name"]),
            );
            checked += 1;
        }
    }

    // Whole-message fixtures: run each window's events as one payload.
    for case in &message_cases {
        let allow = allow_of(case);
        for (window_id, events) in case["message"].as_object().unwrap() {
            let mut events = events.clone();
            if let Some(arr) = events.as_array_mut() {
                for (i, ev) in arr.iter_mut().enumerate() {
                    if let Some(obj) = ev.as_object_mut() {
                        obj.insert("timestamp".into(), json!(TS0 + i as f64));
                    }
                }
            }
            let mut message = snapshot_message(events);
            message["properties"]["$window_id"] = json!(window_id);
            let inner = serde_json::to_string(&message).unwrap();
            assert_stream_matches_tree(
                &allow,
                &inner,
                &format!("message case {} window {window_id}", case["name"]),
            );
            checked += 1;
        }
    }

    assert!(
        checked > 100,
        "the differential corpus should stay meaningful, got {checked}"
    );
}

#[test]
fn differential_cv_stream_vs_tree() {
    // Compressed with flate2 (an independent codec from the libdeflate legs under test); latin-1
    // encoding matches the SDK (each gzip byte as its U+00XX codepoint). serde's serialization of
    // these strings exercises every wire arm of the walker's latin-1 decoder: \u00XX and shorthand
    // escapes for control bytes, raw two-byte UTF-8 for 0x80..=0xFF.
    fn gz_latin1(json: &[u8]) -> String {
        use std::io::Write;
        let mut enc = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
        enc.write_all(json).unwrap();
        enc.finish().unwrap().iter().map(|&b| b as char).collect()
    }

    let allow = AllowLists::new(["keep"], Vec::<String>::new());

    let scrubbed_snapshot = gz_latin1(
        br#"{"node":{"childNodes":[{"attributes":{"src":"https://cdn.corp.com/a.png","title":"keep secret"},"childNodes":[],"id":4,"tagName":"img","type":2},{"id":5,"textContent":"keep secret words","type":3}],"id":1,"type":0},"initialOffset":{"left":0,"top":0}}"#,
    );
    let unchanged_snapshot = gz_latin1(
        br#"{"node":{"childNodes":[{"id":5,"textContent":"keep keep","type":3}],"id":1,"type":0}}"#,
    );
    // Escaped key: the walker declines both the wire walk and the decompressed walk; the parse
    // fallback (which sees the key as `textContent`) must still scrub it.
    let escaped_key_snapshot =
        gz_latin1(br#"{"node":{"id":5,"\u0074extContent":"keep secret","type":3}}"#);
    let texts_gz = gz_latin1(br#"[{"id":5,"value":"keep secret"}]"#);
    let adds_unchanged_gz = gz_latin1(
        br#"[{"nextId":null,"node":{"childNodes":[],"id":9,"tagName":"div","type":2},"parentId":1}]"#,
    );
    let attrs_gz = gz_latin1(br#"[{"attributes":{"src":"https://cdn.corp.com/img.png"},"id":3}]"#);
    let non_array_gz = gz_latin1(br#"{"a":1}"#);

    let ok_cases: Vec<(Value, &str)> = vec![
        (
            json!({ "type": 2, "timestamp": TS0, "cv": "2024-10", "data": scrubbed_snapshot }),
            "cv snapshot scrubbed",
        ),
        (
            json!({ "type": 2, "timestamp": TS0, "cv": "2024-10", "data": unchanged_snapshot }),
            "cv snapshot unchanged",
        ),
        (
            json!({ "type": 2, "timestamp": TS0, "cv": "2024-10", "data": escaped_key_snapshot }),
            "cv snapshot with escaped key (parse fallback)",
        ),
        (
            json!({ "type": 2, "timestamp": TS0, "cv": "2024-10", "data": { "node": { "id": 5, "textContent": "keep secret", "type": 3 } } }),
            "cv marker with object data scrubs plain",
        ),
        (
            json!({ "type": 3, "timestamp": TS0, "cv": "2024-10", "data": { "source": 0, "adds": adds_unchanged_gz, "attributes": null, "texts": texts_gz } }),
            "cv mutation: texts change, adds don't, attributes null",
        ),
        (
            json!({ "type": 3, "timestamp": TS0, "cv": "2024-10", "data": { "source": 0, "attributes": attrs_gz, "texts": "" } }),
            "cv mutation: attributes change, texts empty string",
        ),
        (
            json!({ "type": 3, "timestamp": TS0, "cv": "2024-10", "data": { "source": 0, "texts": [{ "id": 5, "value": "keep secret" }] } }),
            "cv mutation: plain-array sub-field",
        ),
        (
            json!({ "type": 3, "timestamp": TS0, "cv": "2024-10", "data": { "id": 1, "source": 5, "text": "keep secret" } }),
            "cv marker on input scrubs plain",
        ),
        (
            json!({ "type": 2, "timestamp": TS0, "cv": null, "data": { "node": { "id": 5, "textContent": "keep secret", "type": 3 } } }),
            "null cv marker is not compressed",
        ),
    ];

    for (event, label) in &ok_cases {
        let inner = serde_json::to_string(&snapshot_message(json!([event]))).unwrap();
        assert_stream_matches_tree(&allow, &inner, label);
    }

    // All succeeding shapes in one message: exercises sink sequencing around re-emitted cv spans.
    let all: Vec<Value> = ok_cases.iter().map(|(e, _)| e.clone()).collect();
    let inner = serde_json::to_string(&snapshot_message(json!(all))).unwrap();
    assert_stream_matches_tree(&allow, &inner, "all cv shapes in one message");

    // Failing shapes must fail identically through both paths.
    for (event, label) in [
        (
            json!({ "type": 3, "timestamp": TS0, "cv": "2024-10", "data": { "source": 0, "texts": non_array_gz } }),
            "cv mutation: non-array payload",
        ),
        (
            json!({ "type": 2, "timestamp": TS0, "cv": "2024-10", "data": "not gzip" }),
            "cv snapshot: non-gzip string",
        ),
    ] {
        let inner = serde_json::to_string(&snapshot_message(json!([event]))).unwrap();
        assert_stream_matches_tree(&allow, &inner, label);
    }
}

#[test]
fn mutation_media_attr_past_the_prescan_budget_declines_to_the_parse() {
    // A media `src` positioned past the byte walk's 4 KB attribute prescan budget: the walk's
    // media probe hits its fallback there, which must decline to the tree (not silently classify
    // the attributes as non-media and scrub the src as a plain URL). The differential fails on the
    // stream-vs-tree divergence if that decline is dropped.
    let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
    let padding = "x".repeat(5000);
    let inner = snapshot_message(json!([{
        "type": 3,
        "timestamp": TS0,
        "data": { "source": 0, "attributes": [
            { "id": 1, "attributes": { "data-pad": padding, "src": "https://cdn.corp.com/a.png" } }
        ]}
    }]));
    let inner_json = serde_json::to_string(&inner).unwrap();
    assert_stream_matches_tree(
        &allow,
        &inner_json,
        "media src past the attribute prescan budget",
    );
}
