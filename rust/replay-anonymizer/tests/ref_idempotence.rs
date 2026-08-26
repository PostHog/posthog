//! Re-scrubbing already-mirrored output must preserve its image content refs — but only when the
//! caller vouches for where that input came from.
//!
//! The mirror replaces each inlined image with an `image:<pseudo_team>:<hash>` ref and ships the
//! bytes out of band, so that ref is the only join key back to them. Remote images keep a media
//! placeholder and carry an `imageurl:<hash>` ref in a namespaced sibling attribute.
//! Scrubbing mirrored output a second time must not destroy either join key.
//!
//! The ref format is not a secret, though, so preserving anything `image:`-shaped found in a
//! payload would hand a captured page a way to copy arbitrary text into anonymized output. Two
//! things therefore have to hold, and both are pinned here: refs survive on a path the caller marks
//! trusted, and a forged one never survives on the ingestion path that sees untrusted capture data.

use posthog_replay_anonymizer::{
    anonymize_kafka_payload_opts, anonymize_line_with_ctx, AllowLists, AnonymizeOpts, Ctx,
    ImagePolicy,
};
use serde_json::{json, Value};

const TS0: f64 = 1_700_000_000_000.0;
const REF: &str = "image:0123456789abcdef0123456789abcdef:AAAAAAAAAAAAAAAAAAAAAA";
const URL_REF: &str = "imageurl:AAAAAAAAAAAAAAAAAAAAAA";
const LEGACY_URL_REF: &str = "imageurl:0123456789abcdef0123456789abcdef:AAAAAAAAAAAAAAAAAAAAAA";

fn img_line(value: &str, attr: &str) -> Value {
    json!(["w", { "type": 3, "timestamp": TS0, "data": {
        "source": 0, "adds": [{ "parentId": 1, "nextId": null, "node": {
            "type": 2, "tagName": "img", "id": 42,
            "attributes": { attr: value }, "childNodes": [] } }] } }])
}

fn canvas_line(value: &str) -> Value {
    json!(["w", { "type": 3, "timestamp": TS0, "data": {
        "source": 9, "id": 5, "type": 0, "commands": [{
            "property": "drawImage",
            "args": [{ "rr_type": "ImageBitmap", "args": [{
                "rr_type": "Blob", "type": "image/png",
                "data": [{ "rr_type": "ArrayBuffer", "base64": value }] }] }] }] } }])
}

/// What a caller of the line API actually writes out: the rewritten line, or the input verbatim
/// when the scrub reports nothing changed (which is itself the idempotent outcome).
fn scrub_line(line: &Value, trusted: bool) -> String {
    let allow = AllowLists::default();
    let ctx = if trusted {
        Ctx::new(&allow).preserving_image_refs()
    } else {
        Ctx::new(&allow)
    };
    let original = line.to_string();
    let mut bytes = original.clone().into_bytes();
    anonymize_line_with_ctx(&ctx, &mut bytes)
        .expect("anonymize should succeed")
        .unwrap_or(original)
}

/// The offline re-scrub path (`prepare` and friends), which vouches for its input.
fn scrub_trusted(line: &Value) -> String {
    scrub_line(line, true)
}

/// The same path without the opt-in — what any caller gets by default.
fn scrub_default(line: &Value) -> String {
    scrub_line(line, false)
}

/// The production ingestion path, which sees untrusted capture input.
fn scrub_ingestion(line: &Value, byte_walk: bool) -> String {
    let inner = json!({
        "event": "$snapshot_items",
        "properties": { "$session_id": "s", "$window_id": "w", "$snapshot_items": [line[1]] },
    });
    let payload = serde_json::to_string(&json!({
        "distinct_id": "d",
        "data": serde_json::to_string(&inner).unwrap(),
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
    String::from_utf8_lossy(&out.lines).into_owned()
}

#[test]
fn a_ref_survives_a_trusted_rescrub() {
    for attr in ["src", "xlink:href", "rr_src", "poster", "rr_dataURL"] {
        assert!(
            scrub_trusted(&img_line(REF, attr)).contains(REF),
            "ref destroyed in {attr}"
        );
    }
    assert!(
        scrub_trusted(&canvas_line(REF)).contains(REF),
        "ref destroyed in a canvas blob"
    );
}

#[test]
fn a_namespaced_url_ref_survives_only_a_trusted_rescrub() {
    for url_ref in [URL_REF, LEGACY_URL_REF] {
        let line = img_line(url_ref, "data-anon-image-ref-src");
        assert!(scrub_trusted(&line).contains(url_ref));
        assert!(!scrub_default(&line).contains("data-anon-image-ref-src"));
        for byte_walk in [true, false] {
            assert!(
                !scrub_ingestion(&line, byte_walk).contains("data-anon-image-ref-src"),
                "a captured internal ref attribute survived ingestion (byte_walk={byte_walk})"
            );
        }
    }
}

#[test]
fn a_trusted_rescrub_leaves_a_ref_attribute_exactly_as_it_was() {
    let out = scrub_trusted(&img_line(REF, "src"));
    assert!(out.contains(REF));
    assert!(
        !out.contains("data-anon-original-src"),
        "a stash was invented for a ref"
    );
    assert!(
        !out.contains("data:image/svg+xml"),
        "the ref was replaced by the placeholder"
    );
}

/// The bypass this guard must not become: the ref format is forgeable, so a value that merely
/// looks ref-ish must still be scrubbed on any path that has not opted in.
#[test]
fn a_forged_ref_is_scrubbed_on_the_untrusted_path() {
    let forged = "image:this is a secret the page wants to smuggle out";
    for byte_walk in [true, false] {
        let out = scrub_ingestion(&img_line(forged, "src"), byte_walk);
        assert!(
            !out.contains("secret the page wants"),
            "attacker-controlled value survived ingestion (byte_walk={byte_walk})"
        );
    }
    assert!(
        !scrub_default(&img_line(forged, "src")).contains("secret the page wants"),
        "attacker-controlled value survived a default re-scrub"
    );
}

/// Even a *well-formed* ref must not be preserved by a caller that has not vouched for its input:
/// provenance is the caller's assertion, never inferred from the value.
#[test]
fn a_well_formed_ref_is_still_scrubbed_without_the_opt_in() {
    for byte_walk in [true, false] {
        assert!(
            !scrub_ingestion(&img_line(REF, "src"), byte_walk).contains(REF),
            "a ref was preserved on the ingestion path (byte_walk={byte_walk})"
        );
    }
    assert!(
        !scrub_default(&img_line(REF, "src")).contains(REF),
        "a ref was preserved without the opt-in"
    );
}

/// Malformed refs are scrubbed even on the trusted path — the opt-in relaxes provenance, not shape.
#[test]
fn a_malformed_ref_is_scrubbed_even_when_trusted() {
    let cases = [
        "image:short:AAAAAAAAAAAAAAAAAAAAAA",
        "imageurl:short:AAAAAAAAAAAAAAAAAAAAAA",
        "image:0123456789ABCDEF0123456789ABCDEF:AAAAAAAAAAAAAAAAAAAAAA", // uppercase team
        "image:0123456789abcdef0123456789abcdef:tooshort",
        "image:0123456789abcdef0123456789abcdef:has spaces in the hash!",
        "image:0123456789abcdef0123456789abcdef",
        "image:",
    ];
    for case in cases {
        for attr in ["src", "data-anon-image-ref-src"] {
            let out = scrub_trusted(&img_line(case, attr));
            assert!(
                !out.contains(case),
                "malformed ref preserved in {attr}: {case}"
            );
        }
    }
}

/// A real image sitting next to a ref must still be scrubbed — the guard is not a bypass.
#[test]
fn the_guard_does_not_let_a_real_image_through() {
    use base64::Engine;
    let png = base64::engine::general_purpose::STANDARD
        .decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        .unwrap();
    let src = format!(
        "data:image/png;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(&png)
    );
    let line = json!(["w", { "type": 3, "timestamp": TS0, "data": {
        "source": 0, "adds": [
            { "parentId": 1, "nextId": null, "node": { "type": 2, "tagName": "img", "id": 42,
              "attributes": { "src": REF }, "childNodes": [] } },
            { "parentId": 1, "nextId": null, "node": { "type": 2, "tagName": "img", "id": 43,
              "attributes": { "src": src }, "childNodes": [] } }] } }]);
    let out = scrub_trusted(&line);
    assert!(out.contains(REF), "ref lost");
    assert!(
        !out.contains(&src),
        "a real image passed through unscrubbed"
    );
}

/// A remote URL is still placeholdered on every path.
#[test]
fn a_remote_url_is_still_placeholdered() {
    let line = img_line("https://cdn.example.com/logo.png", "src");
    assert!(scrub_trusted(&line).contains("data:image/svg+xml"));
    for byte_walk in [true, false] {
        assert!(scrub_ingestion(&line, byte_walk).contains("data:image/svg+xml"));
    }
}
