//! No anonymizer output may ever carry a deferred-image token.
//!
//! `ImagePolicy::Parallel` substitutes an `xph<marker><id><fallback>` token for each image and
//! relies on `ImageQueue::patch` running wherever those bytes become immutable. A token that
//! reaches output is unrecoverable data loss: the marker is random per process, so nothing
//! downstream can resolve it back to an image, and the pixels are gone.
//!
//! The differential test in `snapshot.rs` compares Inline against Parallel, so it only catches a
//! leak in a shape its fixtures happen to cover. This asserts the invariant directly instead.

use base64::Engine;
use posthog_replay_anonymizer::{
    anonymize_kafka_payload_opts, compression, AllowLists, AnonymizeOpts, ImageCollection,
    ImagePolicy,
};
use serde_json::{json, Value};

const TS0: f64 = 1_700_000_000_000.0;

/// Any `xph` run shaped like a token, in a plain byte buffer.
fn tokens_in(bytes: &[u8]) -> Vec<String> {
    let text = String::from_utf8_lossy(bytes);
    let mut found = Vec::new();
    for (i, _) in text.match_indices("xph") {
        let tail: String = text[i..].chars().take(44).collect();
        if tail.len() == 44
            && tail[3..43].chars().all(|c| c.is_ascii_hexdigit())
            && matches!(tail.as_bytes()[43], b'b' | b'p')
        {
            found.push(tail);
        }
    }
    found
}

/// A latin-1 JSON string back to the bytes it carries (the cv wire encoding).
fn latin1_bytes(s: &str) -> Vec<u8> {
    s.chars().map(|c| c as u32 as u8).collect()
}

/// Tokens anywhere in the output, **including inside compressed cv payloads**.
///
/// Scanning the raw lines is not enough and quietly misses the real bug: a token sealed into a
/// zstd frame does not appear verbatim (its repeated id digits fold into the frame's sequences),
/// so the payloads have to be decompressed before the scan.
fn leaked_tokens(lines: &[u8]) -> Vec<String> {
    let mut found = tokens_in(lines);
    for line in lines.split(|&b| b == b'\n') {
        if line.is_empty() {
            continue;
        }
        let Ok(parsed) = serde_json::from_slice::<Value>(line) else {
            continue;
        };
        let event = parsed.get(1).unwrap_or(&parsed);
        let Some(data) = event.get("data") else {
            continue;
        };
        let mut payloads: Vec<&str> = Vec::new();
        if let Some(s) = data.as_str() {
            payloads.push(s);
        } else if let Some(obj) = data.as_object() {
            payloads.extend(obj.values().filter_map(|v| v.as_str()));
        }
        for payload in payloads {
            let raw = latin1_bytes(payload);
            if let Ok(plain) = compression::decompress_by_magic(&raw) {
                found.extend(tokens_in(&plain));
            }
        }
    }
    found
}

fn png_data_uri() -> String {
    let png = base64::engine::general_purpose::STANDARD
        .decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
        )
        .unwrap();
    format!(
        "data:image/png;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(&png)
    )
}

/// An SVG data URI is deliberately not collectable (a text format's PII has to be scrubbed in
/// place), so with collection on it is the shape that still takes the deferred-token route.
fn svg_data_uri() -> String {
    let svg = "<svg xmlns='http://www.w3.org/2000/svg'><text>hello</text></svg>";
    format!(
        "data:image/svg+xml;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(svg)
    )
}

fn collection() -> ImageCollection {
    ImageCollection {
        pseudo_team: "a".repeat(32),
        content_key: "0123456789abcdef0123456789abcdef".to_string(),
    }
}

fn snapshot_message(items: serde_json::Value) -> serde_json::Value {
    json!({
        "event": "$snapshot_items",
        "properties": { "$session_id": "s", "$window_id": "w", "$snapshot_items": items },
    })
}

fn run(inner: &serde_json::Value, collect: bool, byte_walk: bool) -> Vec<u8> {
    let allow = AllowLists::default();
    let payload = serde_json::to_string(&json!({
        "distinct_id": "d",
        "data": serde_json::to_string(inner).unwrap(),
    }))
    .unwrap();
    let mut bytes = payload.into_bytes();
    anonymize_kafka_payload_opts(
        &allow,
        &mut bytes,
        AnonymizeOpts {
            byte_walk,
            image_policy: ImagePolicy::Parallel,
        },
        collect.then(collection),
    )
    .expect("anonymize should succeed")
    .lines
}

/// A `cv` payload as the SDK sends it: the sub-value compressed and carried as a latin-1 string.
fn cv_string(value: &serde_json::Value) -> String {
    let compressed = compression::compress_cv(value.to_string().as_bytes()).unwrap();
    compressed.iter().map(|&b| b as char).collect()
}

fn img_add(src: &str) -> serde_json::Value {
    json!([{
        "parentId": 1,
        "nextId": null,
        "node": {
            "type": 2, "tagName": "img", "id": 42,
            "attributes": { "src": src },
            "childNodes": []
        }
    }])
}

fn cases(src: &str, label: &str) -> Vec<(String, serde_json::Value)> {
    vec![
        (
            format!("{label}: plain mutation add"),
            snapshot_message(json!([
                { "type": 3, "timestamp": TS0, "data": { "source": 0, "adds": img_add(src) } }
            ])),
        ),
        (
            format!("{label}: cv mutation add"),
            snapshot_message(json!([
                { "type": 3, "timestamp": TS0, "cv": "2024-10",
                  "data": { "source": 0, "adds": cv_string(&img_add(src)) } }
            ])),
        ),
        (
            format!("{label}: cv mutation attributes"),
            snapshot_message(json!([
                { "type": 3, "timestamp": TS0, "cv": "2024-10",
                  "data": { "source": 0,
                            "attributes": cv_string(&json!([{ "id": 42, "attributes": { "src": src } }])) } }
            ])),
        ),
        (
            format!("{label}: plain full snapshot"),
            snapshot_message(json!([
                { "type": 2, "timestamp": TS0, "data": { "node": {
                    "type": 0, "id": 1, "childNodes": [{
                        "type": 2, "tagName": "img", "id": 42,
                        "attributes": { "src": src }, "childNodes": [] }] },
                    "initialOffset": { "top": 0, "left": 0 } } }
            ])),
        ),
        (
            format!("{label}: cv full snapshot"),
            snapshot_message(json!([
                { "type": 2, "timestamp": TS0, "cv": "2024-10",
                  "data": cv_string(&json!({ "node": {
                    "type": 0, "id": 1, "childNodes": [{
                        "type": 2, "tagName": "img", "id": 42,
                        "attributes": { "src": src }, "childNodes": [] }] },
                    "initialOffset": { "top": 0, "left": 0 } })) }
            ])),
        ),
    ]
}

/// A distinct 1x1 PNG per index, so each one is its own job rather than a dedup hit.
fn distinct_png_data_uri(i: usize) -> String {
    let mut png = base64::engine::general_purpose::STANDARD
        .decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
        )
        .unwrap();
    // Perturb the trailing bytes: still a distinct payload, still decodes as a PNG header.
    let n = png.len();
    png[n - 5] = (i % 251) as u8;
    png[n - 6] = ((i / 251) % 251) as u8;
    format!(
        "data:image/png;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(&png)
    )
}

/// The production shape: one `cv` mutation whose `adds` carries many distinct images.
#[test]
fn no_token_leaks_from_a_cv_mutation_full_of_images() {
    for count in [8usize, 40, 120] {
        for collect in [true, false] {
            for byte_walk in [true, false] {
                let adds: Vec<serde_json::Value> = (0..count)
                    .map(|i| {
                        json!({
                            "parentId": 1, "nextId": null,
                            "node": {
                                "type": 2, "tagName": "img", "id": 100 + i,
                                "attributes": { "src": distinct_png_data_uri(i) },
                                "childNodes": []
                            }
                        })
                    })
                    .collect();
                let inner = snapshot_message(json!([
                    { "type": 3, "timestamp": TS0, "cv": "2024-10",
                      "data": { "source": 0, "adds": cv_string(&json!(adds)) } }
                ]));
                let out = run(&inner, collect, byte_walk);
                let tokens = leaked_tokens(&out);
                assert!(
                    tokens.is_empty(),
                    "{} token(s) leaked from a {count}-image cv mutation \
                     (collect={collect}, byte_walk={byte_walk}), e.g. {}",
                    tokens.len(),
                    tokens[0]
                );
            }
        }
    }
}

#[test]
fn no_deferred_image_token_reaches_output() {
    let mut failures = Vec::new();
    for (src, kind) in [(png_data_uri(), "png"), (svg_data_uri(), "svg")] {
        for (label, inner) in cases(&src, kind) {
            for collect in [true, false] {
                for byte_walk in [true, false] {
                    let out = run(&inner, collect, byte_walk);
                    let tokens = leaked_tokens(&out);
                    if !tokens.is_empty() {
                        failures.push(format!(
                            "{label} (collect={collect}, byte_walk={byte_walk}): {} token(s), e.g. {}",
                            tokens.len(),
                            tokens[0]
                        ));
                    }
                }
            }
        }
    }
    assert!(
        failures.is_empty(),
        "deferred-image tokens reached output:\n  {}",
        failures.join("\n  ")
    );
}
