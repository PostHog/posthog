//! The URL-collection lane, end to end through a real Kafka payload.
//!
//! The unit tests in `url_collect` pin canonicalization and the collector in isolation. These pin
//! the parts only the whole pipeline can show: that a remote `src` comes out as a ref rather than
//! the placeholder, that the original URL reaches `meta.urls`, that the scrubbed copy is still
//! stashed alongside, and that a caller who does not opt in sees exactly what it saw before.

use posthog_replay_anonymizer::{
    anonymize_kafka_payload_collecting, AllowLists, AnonymizeOpts, ImagePolicy, UrlCollection,
};
use serde_json::{json, Value};

const TS0: f64 = 1_700_000_000_000.0;
const PSEUDO_TEAM: &str = "0123456789abcdef0123456789abcdef";
const URL_KEY: &str = "0123456789abcdef0123456789abcdef";

fn payload_tagged(tag: &str, attrs: Value) -> Vec<u8> {
    let inner = json!({
        "event": "$snapshot_items",
        "properties": {
            "$session_id": "s",
            "$window_id": "w",
            "$snapshot_items": [{
                "type": 3,
                "timestamp": TS0,
                "data": { "source": 0, "adds": [{
                    "parentId": 1,
                    "nextId": null,
                    "node": {
                        "type": 2, "tagName": tag, "id": 42,
                        "attributes": attrs, "childNodes": []
                    }
                }] }
            }]
        }
    });
    json!({ "distinct_id": "d", "data": inner.to_string() })
        .to_string()
        .into_bytes()
}

fn collect_urls_of(tag: &str, attrs: Value) -> Vec<String> {
    let allow = AllowLists::default();
    let mut hosts = Vec::new();
    for byte_walk in [true, false] {
        let mut bytes = payload_tagged(tag, attrs.clone());
        let msg = anonymize_kafka_payload_collecting(
            &allow,
            &mut bytes,
            AnonymizeOpts {
                byte_walk,
                image_policy: ImagePolicy::Inline,
            },
            None,
            None,
            Some(UrlCollection {
                pseudo_team: PSEUDO_TEAM.to_string(),
                url_key: URL_KEY.to_string(),
            }),
        )
        .expect("anonymize should succeed");
        hosts.push(format!("byte_walk={byte_walk}:{}", msg.meta.urls.len()));
    }
    hosts
}

#[test]
fn only_an_image_bearing_tag_has_its_src_collected() {
    // TagKind::Media also covers video, audio and track, whose src is a movie, a sound file, or a
    // WebVTT subtitle document. The fetch lane is sized to download images.
    for tag in ["img", "image", "picture"] {
        assert_eq!(
            collect_urls_of(tag, json!({ "src": "https://cdn.example.com/a.png" })),
            vec!["byte_walk=true:1", "byte_walk=false:1"],
            "{tag} src should be collected"
        );
    }
    for tag in ["video", "audio", "track", "source"] {
        assert_eq!(
            collect_urls_of(tag, json!({ "src": "https://cdn.example.com/movie.mp4" })),
            vec!["byte_walk=true:0", "byte_walk=false:0"],
            "{tag} src is not an image and must not be collected"
        );
    }
}

#[test]
fn a_video_poster_is_still_collected() {
    // poster only exists on a video and always names a still image.
    assert_eq!(
        collect_urls_of(
            "video",
            json!({ "poster": "https://cdn.example.com/poster.jpg" })
        ),
        vec!["byte_walk=true:1", "byte_walk=false:1"]
    );
}

fn payload(attrs: Value) -> Vec<u8> {
    let inner = json!({
        "event": "$snapshot_items",
        "properties": {
            "$session_id": "s",
            "$window_id": "w",
            "$snapshot_items": [{
                "type": 3,
                "timestamp": TS0,
                "data": { "source": 0, "adds": [{
                    "parentId": 1,
                    "nextId": null,
                    "node": {
                        "type": 2, "tagName": "img", "id": 42,
                        "attributes": attrs, "childNodes": []
                    }
                }] }
            }]
        }
    });
    json!({ "distinct_id": "d", "data": inner.to_string() })
        .to_string()
        .into_bytes()
}

/// Runs both engines, because the byte walk and the tree parse have separate media-attribute
/// paths and only a differential check keeps them writing the same thing.
fn run(attrs: Value, collect: bool) -> Vec<(String, Value)> {
    let allow = AllowLists::default();
    let mut out = Vec::new();
    for byte_walk in [true, false] {
        let mut bytes = payload(attrs.clone());
        let collection = collect.then(|| UrlCollection {
            pseudo_team: PSEUDO_TEAM.to_string(),
            url_key: URL_KEY.to_string(),
        });
        let msg = anonymize_kafka_payload_collecting(
            &allow,
            &mut bytes,
            AnonymizeOpts {
                byte_walk,
                image_policy: ImagePolicy::Inline,
            },
            None,
            None,
            collection,
        )
        .expect("anonymize should succeed");
        let line: Value = serde_json::from_slice(
            msg.lines
                .split(|b| *b == b'\n')
                .next()
                .expect("at least one line"),
        )
        .expect("line is json");
        let meta = serde_json::to_value(&msg.meta).expect("meta serializes");
        out.push((format!("byte_walk={byte_walk}"), json!([line, meta])));
    }
    out
}

fn attrs_of(line: &Value) -> &Value {
    &line[1]["data"]["adds"][0]["node"]["attributes"]
}

#[test]
fn a_remote_src_becomes_a_ref_and_its_url_reaches_meta() {
    for (engine, result) in run(
        json!({ "src": "https://cdn.example.com/hero.png?w=200" }),
        true,
    ) {
        let (line, meta) = (&result[0], &result[1]);
        let src = attrs_of(line)["src"].as_str().expect("src is a string");
        assert!(
            src.starts_with(&format!("imageurl:{PSEUDO_TEAM}:")),
            "{engine}: expected a url ref, got {src}"
        );

        let urls = meta["urls"].as_array().expect("meta.urls present");
        assert_eq!(urls.len(), 1, "{engine}");
        assert_eq!(urls[0]["url"], "https://cdn.example.com/hero.png?w=200");
        assert_eq!(urls[0]["host"], "cdn.example.com");
        assert!(
            src.ends_with(urls[0]["hash"].as_str().expect("hash is a string")),
            "{engine}: the ref must carry the hash meta reports"
        );

        // The scrubbed copy still rides along, so a reader that never resolves the ref keeps what
        // it has today.
        assert!(
            attrs_of(line)["data-anon-original-src"].is_string(),
            "{engine}: the scrubbed original should still be stashed"
        );
    }
}

#[test]
fn without_a_collection_a_remote_src_is_still_the_placeholder() {
    for (engine, result) in run(json!({ "src": "https://cdn.example.com/hero.png" }), false) {
        let (line, meta) = (&result[0], &result[1]);
        let src = attrs_of(line)["src"].as_str().expect("src is a string");
        assert!(
            src.starts_with("data:image/svg+xml"),
            "{engine}: expected the placeholder, got {src}"
        );
        assert!(
            meta.get("urls").is_none(),
            "{engine}: meta.urls should be absent when nothing was collected"
        );
    }
}

#[test]
fn an_inlined_image_is_untouched_by_the_url_lane() {
    // The two lanes must not fight over one attribute: a data URI has no URL to fetch, so it stays
    // on the image path even with URL collection on.
    let inlined = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
    for (engine, result) in run(json!({ "src": inlined }), true) {
        let (line, meta) = (&result[0], &result[1]);
        let src = attrs_of(line)["src"].as_str().expect("src is a string");
        assert!(
            !src.starts_with("imageurl:"),
            "{engine}: an inlined image must not take the URL lane, got {src}"
        );
        assert!(meta.get("urls").is_none(), "{engine}");
    }
}

#[test]
fn a_non_fetchable_scheme_keeps_the_placeholder() {
    for (engine, result) in run(json!({ "src": "ftp://files.example.com/hero.png" }), true) {
        let (line, meta) = (&result[0], &result[1]);
        let src = attrs_of(line)["src"].as_str().expect("src is a string");
        assert!(
            src.starts_with("data:image/svg+xml"),
            "{engine}: expected the placeholder, got {src}"
        );
        assert!(meta.get("urls").is_none(), "{engine}");
    }
}

#[test]
fn srcset_stays_out_of_scope_and_keeps_the_placeholder() {
    // srcset holds several candidates with descriptors, so it needs a parse and a choice this lane
    // deliberately does not make yet. Pinned so adding it is a decision rather than an accident.
    for (engine, result) in run(
        json!({ "srcset": "https://cdn.example.com/a.png 1x, https://cdn.example.com/b.png 2x" }),
        true,
    ) {
        let (line, meta) = (&result[0], &result[1]);
        let srcset = attrs_of(line)["srcset"]
            .as_str()
            .expect("srcset is a string");
        assert!(
            srcset.starts_with("data:image/svg+xml"),
            "{engine}: expected the placeholder, got {srcset}"
        );
        assert!(meta.get("urls").is_none(), "{engine}");
    }
}

#[test]
fn one_url_under_two_signatures_collects_once() {
    // The whole reason canonicalization splits the dedup URL from the fetch URL.
    let allow = AllowLists::default();
    let mut bytes = json!({
        "distinct_id": "d",
        "data": json!({
            "event": "$snapshot_items",
            "properties": {
                "$session_id": "s",
                "$window_id": "w",
                "$snapshot_items": [
                    {"type": 3, "timestamp": TS0, "data": {"source": 0, "adds": [
                        {"parentId": 1, "nextId": null, "node": {"type": 2, "tagName": "img", "id": 1,
                          "attributes": {"src": "https://cdn.example.com/a.png?X-Amz-Signature=aaa"}, "childNodes": []}},
                        {"parentId": 1, "nextId": null, "node": {"type": 2, "tagName": "img", "id": 2,
                          "attributes": {"src": "https://cdn.example.com/a.png?X-Amz-Signature=bbb"}, "childNodes": []}}
                    ]}}
                ]
            }
        }).to_string()
    })
    .to_string()
    .into_bytes();

    let msg = anonymize_kafka_payload_collecting(
        &allow,
        &mut bytes,
        AnonymizeOpts::default(),
        None,
        None,
        Some(UrlCollection {
            pseudo_team: PSEUDO_TEAM.to_string(),
            url_key: URL_KEY.to_string(),
        }),
    )
    .expect("anonymize should succeed");

    assert_eq!(
        msg.meta.urls.len(),
        1,
        "two signatures of one image are one URL to fetch"
    );
}

#[test]
fn every_refusal_is_counted_with_a_reason() {
    // A silent decline makes the lane look like the traffic carries fewer images than it does,
    // which is exactly the number the measurement phase exists to produce.
    let allow = AllowLists::default();
    let mut bytes = payload_tagged(
        "img",
        json!({
            // https, so this refusal counts as an address refusal. The scheme check runs first, so
            // over http it would count as a scheme refusal instead.
            "src": "https://169.254.169.254/meta.png",
            "rr_src": "ftp://files.example.com/a.png",
            "poster": "/relative/a.png"
        }),
    );
    let msg = anonymize_kafka_payload_collecting(
        &allow,
        &mut bytes,
        AnonymizeOpts::default(),
        None,
        None,
        Some(UrlCollection {
            pseudo_team: PSEUDO_TEAM.to_string(),
            url_key: URL_KEY.to_string(),
        }),
    )
    .expect("anonymize should succeed");

    assert!(msg.meta.urls.is_empty(), "none of these are fetchable");
    let reasons: Vec<&str> = msg
        .meta
        .url_declines
        .iter()
        .map(|d| d.reason.as_str())
        .collect();
    assert!(reasons.contains(&"non_public_host"), "{reasons:?}");
    assert!(reasons.contains(&"bad_scheme"), "{reasons:?}");
    assert!(reasons.contains(&"not_absolute"), "{reasons:?}");
}
