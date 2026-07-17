//! Typed-parse (`typed-parse` feature) contract tests: scrub-then-parse returns a typed rrweb
//! AST that is already scrubbed and transparently cv-decompressed. The scrubbing hot path is
//! pinned elsewhere (parity + differential suites); nothing here touches it — the typed module
//! is not even compiled into the addon build (`default-features = false`).
#![cfg(feature = "typed-parse")]

use std::io::Write;
use std::path::Path;

use posthog_replay_anonymizer::typed::{
    AttrValue, Event, EventData, EventType, IncrementalData, SerializedNode,
};
use posthog_replay_anonymizer::{anonymize_line, parse_scrubbed_event, AllowLists};
use serde_json::json;

fn latin1(bytes: &[u8]) -> String {
    bytes.iter().map(|&b| b as char).collect()
}

// The SDK wire format for cv payloads: gzip stored as latin-1 codepoints.
fn gzip_latin1(json: &[u8]) -> String {
    let mut enc = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
    enc.write_all(json).unwrap();
    latin1(&enc.finish().unwrap())
}

fn parse(allow: &AllowLists, line: &str) -> Option<Event> {
    let mut bytes = line.as_bytes().to_vec();
    parse_scrubbed_event(allow, &mut bytes).unwrap()
}

fn allow_hello() -> AllowLists {
    AllowLists::new(["hello"], Vec::<String>::new())
}

fn full_snapshot_data() -> serde_json::Value {
    json!({
        "node": { "type": 0, "id": 1, "childNodes": [
            { "type": 2, "id": 2, "tagName": "html", "attributes": {}, "childNodes": [
                { "type": 2, "id": 3, "tagName": "body", "attributes": { "class": "main" }, "childNodes": [
                    { "type": 3, "id": 4, "textContent": "hello John Fakename" }
                ]}
            ]}
        ]},
        "initialOffset": { "top": 1.0, "left": 2.0 }
    })
}

#[test]
fn full_snapshot_parses_to_a_scrubbed_typed_tree() {
    let allow = allow_hello();
    let line = json!({ "type": 2, "timestamp": 1700000000000i64, "data": full_snapshot_data() })
        .to_string();
    let event = parse(&allow, &line).expect("a full snapshot is recognizable");

    assert_eq!(event.event_type(), Some(EventType::FullSnapshot));
    assert_eq!(event.timestamp, 1700000000000);
    let EventData::FullSnapshot(snap) = &event.data else {
        panic!("expected FullSnapshot data, got {:?}", event.data);
    };
    assert_eq!(snap.initial_offset.top, 1.0);
    assert_eq!(snap.node.id, 1);

    let SerializedNode::Document(doc) = &snap.node.node else {
        panic!("root must be a Document");
    };
    let html = &doc.child_nodes[0];
    let SerializedNode::Element(html_el) = &html.node else {
        panic!("expected the html element");
    };
    assert_eq!((html.id, html_el.tag_name.as_str()), (2, "html"));

    let body = &html_el.child_nodes[0];
    let SerializedNode::Element(body_el) = &body.node else {
        panic!("expected the body element");
    };
    assert_eq!(body_el.tag_name, "body");
    assert_eq!(
        body_el.attributes.get("class"),
        Some(&AttrValue::Str("main".to_string()))
    );

    let SerializedNode::Text(text) = &body_el.child_nodes[0].node else {
        panic!("expected the text node");
    };
    // The typed tree is already scrubbed: no way to reach an unscrubbed AST.
    assert_eq!(text.text_content, "hello **** ********");
}

#[test]
fn mutation_parses_to_scrubbed_typed_subfields() {
    let allow = allow_hello();
    let rr_src = "https://cdn.fake.test/avatars/john.fakename.png";
    let line = json!({ "type": 3, "timestamp": 1.0, "data": {
        "source": 0,
        "texts": [{ "id": 5, "value": "hello secret" }],
        "attributes": [{ "id": 6, "attributes": { "rr_src": rr_src } }],
        "removes": [{ "parentId": 7, "id": 8 }],
        "adds": [{ "parentId": 9, "nextId": null,
                   "node": { "type": 3, "id": 10, "textContent": "hello secret" } }],
    }})
    .to_string();
    let event = parse(&allow, &line).unwrap();

    let EventData::Incremental(IncrementalData::Mutation(m)) = &event.data else {
        panic!("expected Mutation data, got {:?}", event.data);
    };
    assert_eq!(
        (m.texts[0].id, m.texts[0].value.as_deref()),
        (5, Some("hello ******"))
    );

    assert_eq!(m.attributes[0].id, 6);
    let AttrValue::Str(scrubbed_src) = &m.attributes[0].attributes["rr_src"] else {
        panic!("rr_src must stay a string");
    };
    assert_ne!(
        scrubbed_src, rr_src,
        "the rr_src URL must be scrubbed (#68858)"
    );
    assert!(!scrubbed_src.contains("john"), "got: {scrubbed_src}");

    assert_eq!((m.removes[0].parent_id, m.removes[0].id), (7, 8));

    assert_eq!((m.adds[0].parent_id, m.adds[0].next_id), (9, None));
    let SerializedNode::Text(added) = &m.adds[0].node.node else {
        panic!("expected the added text node");
    };
    assert_eq!(added.text_content, "hello ******");
}

#[test]
fn cv_full_snapshot_parses_like_its_uncompressed_twin_gzip_and_zstd() {
    let allow = allow_hello();
    let data = full_snapshot_data();

    let plain = json!({ "type": 2, "timestamp": 1.0, "data": data }).to_string();
    let gzip = json!({ "type": 2, "timestamp": 1.0, "cv": "2024-10",
                       "data": gzip_latin1(data.to_string().as_bytes()) })
    .to_string();
    // The anonymizer re-emits changed cv payloads as zstd — its output IS the zstd twin.
    let zstd = anonymize_line(&allow, &mut gzip.clone().into_bytes())
        .unwrap()
        .expect("the scrub rewrites the cv payload");

    let expected = parse(&allow, &plain).unwrap();
    assert_eq!(
        parse(&allow, &gzip).unwrap(),
        expected,
        "gzip cv twin diverged"
    );
    assert_eq!(
        parse(&allow, &zstd).unwrap(),
        expected,
        "zstd cv twin diverged"
    );
}

#[test]
fn cv_mutation_subfields_parse_like_their_uncompressed_twins_gzip_and_zstd() {
    let allow = allow_hello();
    let texts = json!([{ "id": 5, "value": "hello secret" }]);
    let removes = json!([{ "parentId": 7, "id": 8 }]);

    let plain = json!({ "type": 3, "timestamp": 1.0,
                        "data": { "source": 0, "texts": texts, "removes": removes } })
    .to_string();
    let gzip = json!({ "type": 3, "timestamp": 1.0, "cv": "2024-10", "data": {
        "source": 0,
        "texts": gzip_latin1(texts.to_string().as_bytes()),
        "removes": gzip_latin1(removes.to_string().as_bytes()),
    }})
    .to_string();
    // Re-emitted sub-fields become zstd; `removes` is not scrub-routed and stays gzip, so this
    // twin also covers mixed-format payloads.
    let zstd = anonymize_line(&allow, &mut gzip.clone().into_bytes())
        .unwrap()
        .expect("the scrub rewrites the texts sub-field");

    let expected = parse(&allow, &plain).unwrap();
    assert_eq!(
        parse(&allow, &gzip).unwrap(),
        expected,
        "gzip cv twin diverged"
    );
    assert_eq!(
        parse(&allow, &zstd).unwrap(),
        expected,
        "zstd cv twin diverged"
    );
}

#[test]
fn tuple_lines_carry_the_window_id_and_bare_lines_do_not() {
    let allow = allow_hello();
    let event_json = json!({ "type": 3, "timestamp": 2.5,
                             "data": { "source": 3, "id": 4, "x": 1.0, "y": 2.0 } });

    let tuple = parse(&allow, &json!(["w-1", event_json]).to_string()).unwrap();
    assert_eq!(tuple.window_id.as_deref(), Some("w-1"));
    assert_eq!(tuple.event_type(), Some(EventType::IncrementalSnapshot));
    assert_eq!(tuple.timestamp, 2, "fractional timestamps truncate");
    let EventData::Incremental(IncrementalData::Scroll(scroll)) = &tuple.data else {
        panic!("expected Scroll data, got {:?}", tuple.data);
    };
    assert_eq!((scroll.id, scroll.x, scroll.y), (4, 1.0, 2.0));

    let bare = parse(&allow, &event_json.to_string()).unwrap();
    assert_eq!(bare.window_id, None);
    assert_eq!(bare.data, tuple.data);

    // A wrong top-level shape fails closed (same policy as `anonymize_line`); an object with no
    // event envelope (missing type/timestamp) has nothing typed to return, so it is `Ok(None)`.
    let mut wrong_shape = br#"["w-1","not an event"]"#.to_vec();
    assert!(parse_scrubbed_event(&allow, &mut wrong_shape).is_err());
    assert!(
        parse(&allow, r#"{"type":2}"#).is_none(),
        "missing timestamp"
    );
}

#[test]
fn mutation_with_null_subfields_parses_as_empty() {
    // Both scrub paths keep a `null` mutation sub-field verbatim, so it is valid data the typed
    // parse must accept (as empty), not fail on.
    let allow = allow_hello();
    let line = json!({ "type": 3, "timestamp": 1.0, "data": {
        "source": 0,
        "texts": null,
        "attributes": null,
        "removes": null,
        "adds": null,
    }})
    .to_string();
    let event = parse(&allow, &line).unwrap();
    let EventData::Incremental(IncrementalData::Mutation(m)) = &event.data else {
        panic!("expected Mutation data, got {:?}", event.data);
    };
    assert!(
        m.texts.is_empty() && m.attributes.is_empty() && m.removes.is_empty() && m.adds.is_empty()
    );
}

#[test]
fn unknown_enum_discriminant_is_a_loud_error() {
    // A MouseInteraction kind newer than this crate knows must surface as `Err` (extend the crate),
    // not silently downgrade or mis-type. `source: 2` routes to the typed MouseInteraction model.
    let allow = allow_hello();
    let mut line = json!({ "type": 3, "timestamp": 1.0,
                           "data": { "source": 2, "type": 99, "id": 4 } })
    .to_string()
    .into_bytes();
    assert!(parse_scrubbed_event(&allow, &mut line).is_err());
}

#[test]
fn unmodeled_types_and_sources_pass_through_as_scrubbed_generic_json() {
    let allow = allow_hello();

    // Unknown incremental source (selection, 14) stays generic.
    let line = json!({ "type": 3, "timestamp": 1.0,
                       "data": { "source": 14, "ranges": [] } })
    .to_string();
    let event = parse(&allow, &line).unwrap();
    let EventData::Incremental(IncrementalData::Other(v)) = &event.data else {
        panic!("expected Other incremental data, got {:?}", event.data);
    };
    assert_eq!(v["source"], 14);

    // Custom event (type 5) payload is generic but still scrubbed.
    let line = json!({ "type": 5, "timestamp": 1.0,
                       "data": { "tag": "note", "payload": "hello secret" } })
    .to_string();
    let event = parse(&allow, &line).unwrap();
    assert_eq!(event.event_type(), Some(EventType::Custom));
    let EventData::Other(v) = &event.data else {
        panic!("expected Other event data, got {:?}", event.data);
    };
    assert_eq!(v["payload"], "hello ******");
}

/// Every shared scrub fixture must round-trip the typed parse without an error — the typed
/// surface may downgrade an event to `Other`, but it must never fail on payloads the scrubbers
/// accept.
#[test]
fn every_shared_event_fixture_parses() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/events.json");
    let cases: Vec<serde_json::Value> =
        serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    assert!(!cases.is_empty());
    for case in &cases {
        let strings = |key: &str| -> Vec<String> {
            case["allow"][key]
                .as_array()
                .map(|a| {
                    a.iter()
                        .filter_map(|v| v.as_str().map(String::from))
                        .collect()
                })
                .unwrap_or_default()
        };
        let allow = AllowLists::new(strings("text"), strings("url"));
        let mut line = serde_json::to_vec(&case["event"]).unwrap();
        parse_scrubbed_event(&allow, &mut line)
            .unwrap_or_else(|e| panic!("fixture {} failed the typed parse: {e:#}", case["name"]));
    }
}
