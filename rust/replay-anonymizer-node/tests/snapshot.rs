//! Tests for the byte-buffer snapshot pipeline (`snapshot.rs`).
//!
//! The streaming path is a byte scanner that must reproduce JSON.parse semantics without parsing;
//! its failure modes are *divergence* bugs (mis-spliced spans, scanner-visible vs parser-visible
//! keys, wrong dlq/drop classification), so the suite centers on a differential check against the
//! tree path plus targeted leak/contract cases.

use replay_anonymizer_node::allow_lists::AllowLists;
use replay_anonymizer_node::snapshot::{
    anonymize_kafka_payload, anonymize_kafka_payload_opts, anonymize_via_tree, AnonymizeOpts,
    AnonymizedMessage, FailKind, Failure, Route, FLAG_ACTIVE, FLAG_CLICK, FLAG_KEYPRESS,
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
fn adaptive_routing_only_takes_the_tree_before_any_in_place_parse() {
    let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
    // A full snapshot big enough to dominate the message (> half the inner bytes).
    let big_snapshot = json!({ "type": 2, "timestamp": TS0, "data": {
        "node": { "type": 0, "childNodes": [
            { "type": 2, "tagName": "div", "attributes": {}, "childNodes": [
                { "type": 3, "textContent": "x".repeat(200_000) }
            ]}
        ]},
        "initialOffset": { "top": 0, "left": 0 }
    }});
    // The realistic message shape: a small scrub-routed Meta event precedes the snapshot. It must
    // parse from scratch (not in place), or adaptive routing could never fire in production.
    let meta_event =
        json!({ "type": 4, "timestamp": TS0, "data": { "href": "https://x.example.com/p", "width": 1, "height": 1 } });
    let dominated = payload_of(&snapshot_message(json!([meta_event, big_snapshot])));
    let out = run(&allow, &dominated).expect("anonymizes");
    assert_eq!(out.route, Route::Tree, "snapshot-dominated routes to tree");

    // A scrub-routed event too big for the scratch budget has already consumed its span in place —
    // the buffer is no longer intact, so aborting to the tree would re-parse garbage and drop a
    // valid message. Routing must stay on the streaming path and still succeed.
    let big_input = json!({ "type": 3, "timestamp": TS0, "data": {
        "source": 5, "id": 1, "text": "y ".repeat(50_000)
    }});
    let mutated_first =
        payload_of(&snapshot_message(json!([big_input, big_snapshot.clone()])));
    let out = run(&allow, &mutated_first).expect("must not abort after an in-place parse");
    assert_eq!(out.route, Route::Stream, "mutated buffer stays on stream");
    assert_eq!(parse_lines(&out.lines).len(), 2);
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
    let mut bytes = payload.as_bytes().to_vec();
    // Adaptive routing off: the differential must pin the *streaming* path against the tree, not
    // let snapshot-dominated cases silently compare the tree against itself.
    let stream = anonymize_kafka_payload_opts(
        allow,
        &mut bytes,
        AnonymizeOpts {
            adaptive_routing: false,
        },
    );

    let ctx = Ctx::new(allow);
    let tree = anonymize_via_tree(&ctx, "d", inner_json.as_bytes());

    match (stream, tree) {
        (Ok(s), Ok(t)) => {
            let s_lines = parse_lines(&s.lines);
            let t_lines = parse_lines(&t.lines);
            assert_eq!(s_lines, t_lines, "lines diverged: {label}");
            assert_eq!(s.meta, t.meta, "meta diverged: {label}");
        }
        (Err(s), Err(t)) => {
            assert_eq!(s.kind, t.kind, "failure kind diverged: {label}");
        }
        (s, t) => panic!(
            "outcome diverged for {label}: stream={:?} tree={:?}",
            s.map(|m| parse_lines(&m.lines)),
            t.map(|m| parse_lines(&m.lines)),
        ),
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
