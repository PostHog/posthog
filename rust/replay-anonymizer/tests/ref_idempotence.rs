//! Re-scrubbing already-mirrored output must preserve its image content refs.
//!
//! The mirror replaces each inlined image with an `image:<pseudo_team>:<hash>` ref and ships the
//! bytes out of band. Anything that scrubs that output a second time — the `prepare` CLI, offline
//! tooling, a backfill — used to destroy those refs: a canvas blob's ref was reassembled into a
//! data URI that cannot decode and failed safe to a blank pixel, and a ref in a media-source
//! attribute took the remote-URL branch and was redacted into the placeholder. Either way the
//! image behind it became unreachable, because the ref is the only join key back to the bytes.
//!
//! A ref carries no content of its own, so preserving it is safe; destroying it is not recoverable.

use posthog_replay_anonymizer::{
    anonymize_kafka_payload_opts, compression, AllowLists, AnonymizeOpts, ImagePolicy,
};
use serde_json::{json, Value};

const TS0: f64 = 1_700_000_000_000.0;
const REF: &str = "image:0123456789abcdef0123456789abcdef:AAAAAAAAAAAAAAAAAAAAAA";

fn snapshot_message(items: Value) -> Value {
    json!({
        "event": "$snapshot_items",
        "properties": { "$session_id": "s", "$window_id": "w", "$snapshot_items": items },
    })
}

fn cv_string(value: &Value) -> String {
    compression::compress_cv(value.to_string().as_bytes())
        .unwrap()
        .iter()
        .map(|&b| b as char)
        .collect()
}

fn scrub(inner: &Value, byte_walk: bool) -> String {
    let payload = serde_json::to_string(&json!({
        "distinct_id": "d",
        "data": serde_json::to_string(inner).unwrap(),
    }))
    .unwrap();
    let mut bytes = payload.into_bytes();
    let out = anonymize_kafka_payload_opts(
        &AllowLists::default(),
        &mut bytes,
        AnonymizeOpts {
            byte_walk,
            image_policy: ImagePolicy::Parallel,
        },
        None,
    )
    .expect("anonymize should succeed");
    // Decode any cv payload so the ref is visible whether or not it was re-compressed.
    let text = String::from_utf8_lossy(&out.lines).into_owned();
    let mut found = text.clone();
    for line in out.lines.split(|&b| b == b'\n') {
        if line.is_empty() {
            continue;
        }
        let Ok(parsed) = serde_json::from_slice::<Value>(line) else {
            continue;
        };
        let event = parsed.get(1).cloned().unwrap_or(parsed);
        let Some(data) = event.get("data") else {
            continue;
        };
        let mut payloads: Vec<String> = Vec::new();
        if let Some(s) = data.as_str() {
            payloads.push(s.to_string());
        } else if let Some(obj) = data.as_object() {
            payloads.extend(obj.values().filter_map(|v| v.as_str()).map(str::to_string));
        }
        for p in payloads {
            let raw: Vec<u8> = p.chars().map(|c| c as u32 as u8).collect();
            if let Ok(plain) = compression::decompress_by_magic(&raw) {
                found.push_str(&String::from_utf8_lossy(&plain));
            }
        }
    }
    found
}

/// Every shape the mirror can leave a ref in, across both walk engines.
#[test]
fn a_ref_survives_a_second_scrub() {
    let canvas = json!([{
        "type": 3, "timestamp": TS0,
        "data": { "source": 9, "id": 5, "type": 0, "commands": [{
            "property": "drawImage",
            "args": [{ "rr_type": "ImageBitmap", "args": [{
                "rr_type": "Blob", "type": "image/png",
                "data": [{ "rr_type": "ArrayBuffer", "base64": REF }] }] }] }] }
    }]);

    let cases: Vec<(&str, Value)> = vec![
        (
            "img src, plain",
            snapshot_message(json!([{ "type": 3, "timestamp": TS0, "data": {
                "source": 0, "adds": [{ "parentId": 1, "nextId": null, "node": {
                    "type": 2, "tagName": "img", "id": 42,
                    "attributes": { "src": REF }, "childNodes": [] } }] } }])),
        ),
        (
            "img xlink:href, plain",
            snapshot_message(json!([{ "type": 3, "timestamp": TS0, "data": {
                "source": 0, "adds": [{ "parentId": 1, "nextId": null, "node": {
                    "type": 2, "tagName": "img", "id": 42,
                    "attributes": { "xlink:href": REF }, "childNodes": [] } }] } }])),
        ),
        (
            "img rr_dataURL, plain",
            snapshot_message(json!([{ "type": 3, "timestamp": TS0, "data": {
                "source": 0, "adds": [{ "parentId": 1, "nextId": null, "node": {
                    "type": 2, "tagName": "img", "id": 42,
                    "attributes": { "rr_dataURL": REF }, "childNodes": [] } }] } }])),
        ),
        (
            "img src, cv mutation",
            snapshot_message(
                json!([{ "type": 3, "timestamp": TS0, "cv": "2024-10", "data": {
                "source": 0, "adds": cv_string(&json!([{ "parentId": 1, "nextId": null, "node": {
                    "type": 2, "tagName": "img", "id": 42,
                    "attributes": { "src": REF }, "childNodes": [] } }])) } }]),
            ),
        ),
        (
            "img src, cv full snapshot",
            snapshot_message(json!([{ "type": 2, "timestamp": TS0, "cv": "2024-10",
                "data": cv_string(&json!({ "node": { "type": 0, "id": 1, "childNodes": [{
                    "type": 2, "tagName": "img", "id": 42,
                    "attributes": { "src": REF }, "childNodes": [] }] },
                    "initialOffset": { "top": 0, "left": 0 } })) }])),
        ),
        ("canvas blob", snapshot_message(canvas)),
    ];

    let mut lost = Vec::new();
    for (label, inner) in &cases {
        for byte_walk in [true, false] {
            if !scrub(inner, byte_walk).contains(REF) {
                lost.push(format!("{label} (byte_walk={byte_walk})"));
            }
        }
    }
    assert!(
        lost.is_empty(),
        "refs destroyed by a second scrub:\n  {}",
        lost.join("\n  ")
    );
}

/// The ref must not merely survive — a media attribute holding one must come out untouched, with
/// no placeholder and no `data-anon-original-*` stash invented for it.
#[test]
fn a_ref_attribute_is_left_exactly_as_it_was() {
    let inner = snapshot_message(json!([{ "type": 3, "timestamp": TS0, "data": {
        "source": 0, "adds": [{ "parentId": 1, "nextId": null, "node": {
            "type": 2, "tagName": "img", "id": 42,
            "attributes": { "src": REF }, "childNodes": [] } }] } }]));
    for byte_walk in [true, false] {
        let out = scrub(&inner, byte_walk);
        assert!(out.contains(REF), "ref missing (byte_walk={byte_walk})");
        assert!(
            !out.contains("data-anon-original-src"),
            "a stash was invented for a ref (byte_walk={byte_walk})"
        );
        assert!(
            !out.contains("data:image/svg+xml"),
            "the ref was replaced by the placeholder (byte_walk={byte_walk})"
        );
    }
}

/// A real image alongside a ref must still be scrubbed — the guard must not become a bypass.
#[test]
fn the_ref_guard_does_not_let_a_real_image_through() {
    use base64::Engine;
    let png = base64::engine::general_purpose::STANDARD
        .decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        .unwrap();
    let src = format!(
        "data:image/png;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(&png)
    );
    let inner = snapshot_message(json!([{ "type": 3, "timestamp": TS0, "data": {
        "source": 0, "adds": [
            { "parentId": 1, "nextId": null, "node": { "type": 2, "tagName": "img", "id": 42,
              "attributes": { "src": REF }, "childNodes": [] } },
            { "parentId": 1, "nextId": null, "node": { "type": 2, "tagName": "img", "id": 43,
              "attributes": { "src": src }, "childNodes": [] } }] } }]));
    for byte_walk in [true, false] {
        let out = scrub(&inner, byte_walk);
        assert!(out.contains(REF), "ref lost (byte_walk={byte_walk})");
        assert!(
            !out.contains(&src),
            "the real image passed through unscrubbed (byte_walk={byte_walk})"
        );
    }
}

/// A string that merely starts with `image:` but is not a well-formed ref must not be trusted —
/// the guard keys on the producer's own predicate, so this pins what that predicate admits.
#[test]
fn a_remote_url_is_still_placeholdered() {
    let inner = snapshot_message(json!([{ "type": 3, "timestamp": TS0, "data": {
        "source": 0, "adds": [{ "parentId": 1, "nextId": null, "node": {
            "type": 2, "tagName": "img", "id": 42,
            "attributes": { "src": "https://cdn.example.com/logo.png" }, "childNodes": [] } }] } }]));
    for byte_walk in [true, false] {
        let out = scrub(&inner, byte_walk);
        assert!(
            out.contains("data:image/svg+xml"),
            "a remote URL should still become the placeholder (byte_walk={byte_walk})"
        );
    }
}
