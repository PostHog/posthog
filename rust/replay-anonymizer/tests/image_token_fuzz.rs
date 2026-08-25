//! Randomized hunt for the deferred-image token leak.
//!
//! Sweeps the axes the hand-written invariant test does not: the gzip wire format the SDK actually
//! sends (not just the anonymizer's own zstd re-emit), images too large for the collection lane,
//! several image-bearing events sharing one message (and so one `ImageQueue`), canvas blobs, and
//! repeated URIs that dedup to a single job.

use base64::Engine;
use posthog_replay_anonymizer::{
    anonymize_kafka_payload_opts, compression, AllowLists, AnonymizeOpts, ImageCollection,
    ImagePolicy,
};
use serde_json::{json, Value};

const TS0: f64 = 1_700_000_000_000.0;

struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }
    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }
    fn chance(&mut self, one_in: u64) -> bool {
        self.below(one_in) == 0
    }
}

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

/// Tokens anywhere in the output, including inside compressed cv payloads — a token sealed into a
/// zstd frame does not appear verbatim, so the payloads have to be decompressed before scanning.
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
            let raw: Vec<u8> = payload.chars().map(|c| c as u32 as u8).collect();
            if let Ok(plain) = compression::decompress_by_magic(&raw) {
                found.extend(tokens_in(&plain));
            }
        }
    }
    found
}

fn png_of(width: u32, height: u32, seed: u8) -> String {
    let mut img = image::RgbaImage::new(width, height);
    for (x, y, px) in img.enumerate_pixels_mut() {
        // Noise, so the encoder cannot collapse it — a large image has to stay large enough to
        // exceed the collection lane's per-image cap.
        let v = ((x * 7 + y * 13) as u8).wrapping_mul(seed | 1);
        *px = image::Rgba([v, v.wrapping_add(seed), v ^ seed, 255]);
    }
    let mut buf = Vec::new();
    image::DynamicImage::ImageRgba8(img)
        .write_to(&mut std::io::Cursor::new(&mut buf), image::ImageFormat::Png)
        .expect("png encode");
    format!(
        "data:image/png;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(&buf)
    )
}

fn svg_uri(seed: u8) -> String {
    let svg = format!("<svg xmlns='http://www.w3.org/2000/svg'><text>t{seed}</text></svg>");
    format!(
        "data:image/svg+xml;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(svg)
    )
}

/// The image shapes that can reach the deferred path, by whether the collection lane takes them.
fn image_uri(rng: &mut Rng, small: &[String], large: &[String]) -> String {
    match rng.below(5) {
        // Collectable when collection is on; deferred token otherwise.
        0 | 1 => small[rng.below(small.len() as u64) as usize].clone(),
        // Over the collection lane's per-image cap, so deferred even with collection on.
        2 => large[rng.below(large.len() as u64) as usize].clone(),
        // A text format: never collectable, and unblurrable, so it exercises the fallback.
        3 => svg_uri(rng.below(4) as u8),
        // Decodes as base64 but is not an image.
        _ => "data:image/png;base64,bm90IGFuIGltYWdl".to_string(),
    }
}

fn cv_wire(rng: &mut Rng, value: &Value) -> String {
    let json = value.to_string();
    let raw = if rng.chance(2) {
        // What the SDK actually sends.
        compression::gzip(json.as_bytes()).expect("gzip")
    } else {
        compression::compress_cv(json.as_bytes()).expect("zstd")
    };
    raw.iter().map(|&b| b as char).collect()
}

fn img_node(id: u64, src: &str) -> Value {
    json!({
        "parentId": 1, "nextId": null,
        "node": { "type": 2, "tagName": "img", "id": id,
                  "attributes": { "src": src }, "childNodes": [] }
    })
}

fn make_event(rng: &mut Rng, small: &[String], large: &[String], ts: f64) -> Value {
    let n = 1 + rng.below(4);
    let adds: Vec<Value> = (0..n)
        .map(|i| img_node(100 + i, &image_uri(rng, small, large)))
        .collect();

    match rng.below(5) {
        0 => json!({ "type": 3, "timestamp": ts, "data": { "source": 0, "adds": adds } }),
        1 => {
            let attr_src = image_uri(rng, small, large);
            let attrs = json!([{ "id": 42, "attributes": { "src": attr_src } }]);
            json!({ "type": 3, "timestamp": ts, "cv": "2024-10", "data": {
                "source": 0,
                "adds": cv_wire(rng, &json!(adds)),
                "texts": cv_wire(rng, &json!([{ "id": 3, "value": "hello" }])),
                "attributes": cv_wire(rng, &attrs),
                "removes": cv_wire(rng, &json!([{ "parentId": 1, "id": 9 }])),
            }})
        }
        2 => {
            let node = json!({ "node": { "type": 0, "id": 1, "childNodes": adds.iter()
                .map(|a| a["node"].clone()).collect::<Vec<_>>() },
                "initialOffset": { "top": 0, "left": 0 } });
            json!({ "type": 2, "timestamp": ts, "cv": "2024-10", "data": cv_wire(rng, &node) })
        }
        3 => json!({ "type": 2, "timestamp": ts, "data": { "node": { "type": 0, "id": 1,
            "childNodes": adds.iter().map(|a| a["node"].clone()).collect::<Vec<_>>() },
            "initialOffset": { "top": 0, "left": 0 } } }),
        // Canvas blob: the other `scrub_image` caller, with the Blank fallback.
        _ => json!({ "type": 3, "timestamp": ts, "data": { "source": 9, "id": 5, "type": 0,
            "commands": [{ "property": "drawImage", "args": [{
                "rr_type": "ImageBitmap", "args": [{ "rr_type": "Blob", "type": "image/png",
                "data": [{ "rr_type": "ArrayBuffer", "base64":
                    image_uri(rng, small, large).split(',').nth(1).unwrap_or("").to_string() }] }] }] }] } }),
    }
}

#[test]
fn fuzz_no_deferred_image_token_reaches_output() {
    let allow = AllowLists::default();
    let small: Vec<String> = (0..4).map(|i| png_of(8, 8, i as u8 + 1)).collect();
    // Comfortably over the collection lane's 900 KB per-image cap.
    let large: Vec<String> = (0..2).map(|i| png_of(900, 900, i as u8 + 7)).collect();

    let mut rng = Rng(0xDEAD_BEEF_1234_5678);
    let mut failures: Vec<String> = Vec::new();
    let mut messages = 0usize;

    for round in 0..240 {
        let events: Vec<Value> = (0..(1 + rng.below(4)))
            .map(|i| make_event(&mut rng, &small, &large, TS0 + i as f64 * 100.0))
            .collect();
        let message = json!({
            "event": "$snapshot_items",
            "properties": { "$session_id": "s", "$window_id": "w", "$snapshot_items": events },
        });
        let payload = serde_json::to_string(&json!({
            "distinct_id": "d",
            "data": serde_json::to_string(&message).unwrap(),
        }))
        .unwrap();

        let collect = rng.chance(2);
        let byte_walk = rng.chance(2);
        let mut bytes = payload.into_bytes();
        let out = anonymize_kafka_payload_opts(
            &allow,
            &mut bytes,
            AnonymizeOpts {
                byte_walk,
                image_policy: ImagePolicy::Parallel,
            },
            collect.then(|| ImageCollection {
                pseudo_team: "a".repeat(32),
                content_key: "0123456789abcdef0123456789abcdef".to_string(),
            }),
        );
        messages += 1;
        let Ok(msg) = out else { continue };
        let tokens = leaked_tokens(&msg.lines);
        if !tokens.is_empty() {
            failures.push(format!(
                "round {round} (collect={collect}, byte_walk={byte_walk}): {} token(s), e.g. {}",
                tokens.len(),
                tokens[0]
            ));
        }
    }

    assert!(
        failures.is_empty(),
        "deferred-image tokens reached output in {}/{messages} messages:\n  {}",
        failures.len(),
        failures.join("\n  ")
    );
}
