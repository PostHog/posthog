//! The URL-collection lane, end to end through a real Kafka payload.
//!
//! The unit tests in `url_collect` pin canonicalization and the collector in isolation. These pin
//! the parts only the whole pipeline can show: that a remote `src` stays on the placeholder, that
//! the ref is stashed separately, that the original URL reaches `meta.urls`, and that the scrubbed
//! copy is still stashed alongside.

use posthog_replay_anonymizer::{
    anonymize_kafka_payload_collecting, AllowLists, AnonymizeOpts, ImagePolicy, UrlCollection,
};
use serde_json::{json, Value};

const TS0: f64 = 1_700_000_000_000.0;
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
                url_key: URL_KEY.to_string(),
            }),
        )
        .expect("anonymize should succeed");
        hosts.push(format!("byte_walk={byte_walk}:{}", msg.meta.urls.len()));
    }
    hosts
}

#[test]
fn known_image_fields_are_collected() {
    for (tag, attrs) in [
        ("img", json!({ "src": "https://cdn.example.com/a.png" })),
        ("img", json!({ "rr_src": "https://cdn.example.com/a.png" })),
        ("image", json!({ "href": "https://cdn.example.com/a.png" })),
        (
            "image",
            json!({ "xlink:href": "https://cdn.example.com/a.png" }),
        ),
        (
            "video",
            json!({ "poster": "https://cdn.example.com/a.png" }),
        ),
    ] {
        assert_eq!(
            collect_urls_of(tag, attrs),
            vec!["byte_walk=true:1", "byte_walk=false:1"],
            "{tag} image field should be collected"
        );
    }
}

#[test]
fn fields_that_can_name_non_images_are_not_collected() {
    for (tag, attrs) in [
        (
            "iframe",
            json!({ "rr_src": "https://cdn.example.com/frame.html" }),
        ),
        (
            "video",
            json!({ "src": "https://cdn.example.com/movie.mp4" }),
        ),
        (
            "audio",
            json!({ "src": "https://cdn.example.com/audio.mp3" }),
        ),
        (
            "track",
            json!({ "src": "https://cdn.example.com/subtitles.vtt" }),
        ),
        (
            "source",
            json!({ "srcset": "https://cdn.example.com/a.png 2x" }),
        ),
    ] {
        assert_eq!(
            collect_urls_of(tag, attrs),
            vec!["byte_walk=true:0", "byte_walk=false:0"],
            "{tag} field must not be guessed as an image"
        );
    }
}

#[test]
fn picture_source_srcset_is_collected_when_its_parent_is_known() {
    let inner = json!({
        "event": "$snapshot_items",
        "properties": {
            "$session_id": "s",
            "$window_id": "w",
            "$snapshot_items": [{
                "type": 2,
                "timestamp": TS0,
                "data": {
                    "node": {
                        "type": 0,
                        "childNodes": [{
                            "type": 2,
                            "tagName": "picture",
                            "attributes": {},
                            "childNodes": [{
                                "type": 2,
                                "tagName": "source",
                                "attributes": {
                                    "srcset": "https://cdn.example.com/a.png 1x, https://cdn.example.com/b.png 2x"
                                },
                                "childNodes": []
                            }]
                        }]
                    },
                    "initialOffset": { "top": 0, "left": 0 }
                }
            }]
        }
    });
    let payload = json!({ "distinct_id": "d", "data": inner.to_string() })
        .to_string()
        .into_bytes();

    for byte_walk in [true, false] {
        let mut bytes = payload.clone();
        let message = anonymize_kafka_payload_collecting(
            &AllowLists::default(),
            &mut bytes,
            AnonymizeOpts {
                byte_walk,
                image_policy: ImagePolicy::Inline,
            },
            None,
            None,
            Some(UrlCollection {
                url_key: URL_KEY.to_string(),
            }),
        )
        .expect("anonymize should succeed");
        assert_eq!(message.meta.urls.len(), 1, "byte_walk={byte_walk}");
        assert_eq!(
            message.meta.urls[0].url, "https://cdn.example.com/b.png",
            "byte_walk={byte_walk}"
        );
    }
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
fn a_remote_src_keeps_its_placeholder_and_stashes_the_ref() {
    for (engine, result) in run(
        json!({ "src": "https://cdn.example.com/hero.png?w=200" }),
        true,
    ) {
        let (line, meta) = (&result[0], &result[1]);
        let src = attrs_of(line)["src"].as_str().expect("src is a string");
        assert!(
            src.starts_with("data:image/svg+xml"),
            "{engine}: expected the placeholder, got {src}"
        );
        let url_ref = attrs_of(line)["data-anon-image-ref-src"]
            .as_str()
            .expect("the URL ref is stashed");
        assert!(url_ref.starts_with("imageurl:"), "{engine}: got {url_ref}");

        let urls = meta["urls"].as_array().expect("meta.urls present");
        assert_eq!(urls.len(), 1, "{engine}");
        assert_eq!(urls[0]["url"], "https://cdn.example.com/hero.png?w=200");
        assert_eq!(urls[0]["host"], "cdn.example.com");
        assert_eq!(
            meta["imageSources"],
            json!([{
                "source": "html",
                "property": "src",
                "kind": "url",
                "count": 1
            }]),
            "{engine}"
        );
        assert!(
            url_ref
                == format!(
                    "imageurl:{}",
                    urls[0]["hash"].as_str().expect("hash is a string")
                ),
            "{engine}: the ref must equal the hash meta reports"
        );

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
        assert!(
            attrs_of(line).get("data-anon-image-ref-src").is_none(),
            "{engine}: no ref should be stashed when nothing was collected"
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
        assert!(
            attrs_of(line).get("data-anon-image-ref-src").is_none(),
            "{engine}: an inlined image must not take the URL lane"
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
        assert!(attrs_of(line).get("data-anon-image-ref-src").is_none());
        assert!(meta.get("urls").is_none(), "{engine}");
    }
}

#[test]
fn srcset_collects_only_the_largest_candidate() {
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
        assert!(
            attrs_of(line)["data-anon-image-ref-srcset"]
                .as_str()
                .is_some_and(|reference| reference.starts_with("imageurl:")),
            "{engine}"
        );
        assert_eq!(meta["urls"].as_array().map(Vec::len), Some(1), "{engine}");
        assert_eq!(meta["urls"][0]["url"], "https://cdn.example.com/b.png");
    }
}

#[test]
fn srcset_routes_an_inlined_largest_candidate_to_the_image_scrubber() {
    let small = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
    let large = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/l5hJxAAAAABJRU5ErkJggg==";
    for (engine, result) in run(json!({ "srcset": format!("{small} 1x, {large} 2x") }), true) {
        let (line, meta) = (&result[0], &result[1]);
        let srcset = attrs_of(line)["srcset"]
            .as_str()
            .expect("srcset is a string");
        assert!(!srcset.contains(large), "{engine}");
        assert!(srcset.starts_with("data:image/"), "{engine}: {srcset}");
        assert!(meta.get("urls").is_none(), "{engine}");
    }
}

#[test]
fn css_image_urls_use_numbered_placeholders_and_a_reference_map() {
    let css = "background-image:url('https://cdn.example.com/a.png');mask-image:url(https://cdn.example.com/b.png)";
    for (engine, result) in run(json!({ "style": css }), true) {
        let (line, meta) = (&result[0], &result[1]);
        let attrs = attrs_of(line);
        let style = attrs["style"].as_str().expect("style is a string");
        assert!(!style.contains("cdn.example.com"), "{engine}: {style}");
        assert!(style.contains("anon-image-slot-0"), "{engine}: {style}");
        assert!(style.contains("anon-image-slot-1"), "{engine}: {style}");

        let refs: serde_json::Map<String, Value> = serde_json::from_str(
            attrs["data-anon-image-refs-style"]
                .as_str()
                .expect("CSS references are present"),
        )
        .expect("CSS references are JSON");
        assert_eq!(refs.len(), 2, "{engine}");
        assert!(refs.values().all(|reference| {
            reference
                .as_str()
                .is_some_and(|reference| reference.starts_with("imageurl:"))
        }));
        assert_eq!(meta["urls"].as_array().map(Vec::len), Some(2), "{engine}");
    }
}

#[test]
fn signed_urls_produce_no_ref_or_fetch_candidate() {
    for (engine, result) in run(
        json!({ "src": "https://cdn.example.com/a.png?X-Amz-Signature=aaa" }),
        true,
    ) {
        let (line, meta) = (&result[0], &result[1]);
        assert!(
            attrs_of(line).get("data-anon-image-ref-src").is_none(),
            "{engine}: signed URLs must not produce a global ref"
        );
        assert!(meta.get("urls").is_none(), "{engine}");
        assert_eq!(meta["urlDeclines"][0]["reason"], "credential", "{engine}");
        assert_eq!(meta["urlDeclines"][0]["count"], 1, "{engine}");
    }
}

#[test]
fn a_refusal_is_counted_with_a_reason() {
    // A silent decline makes the lane look like the traffic carries fewer images than it does,
    // which is exactly the number the measurement phase exists to produce.
    let allow = AllowLists::default();
    let mut bytes = payload_tagged(
        "img",
        json!({
            "src": "https://169.254.169.254/meta.png"
        }),
    );
    let msg = anonymize_kafka_payload_collecting(
        &allow,
        &mut bytes,
        AnonymizeOpts::default(),
        None,
        None,
        Some(UrlCollection {
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
}
