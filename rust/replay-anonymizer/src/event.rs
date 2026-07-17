//! Routes each parsed rrweb event to the right scrubber by type/source, and walks a whole parsed
//! message (`{ windowId: Event[] }`).

use anyhow::{bail, Context, Result};
use simd_json::borrowed::{Object, Value};
use simd_json::prelude::Writable;
use simd_json::StaticNode;

use crate::allow_lists::AllowLists;
use crate::canvas::scrub_canvas_mutation;
use crate::context::Ctx;
use crate::css::{scrub_adopted_style_sheet, scrub_style_declaration, scrub_style_sheet_rule};
use crate::cv::{scrub_compressed_full_snapshot, scrub_compressed_mutation};
use crate::dom::{scrub_full_snapshot, scrub_mutation};
use crate::json::{
    as_array_mut, as_object, as_object_mut, as_small_uint, as_str, key, parse_untrusted,
    reject_if_too_deep, string_value,
};
use crate::text::scrub_text;
use crate::url::scrub_url_opts;
use crate::value::{scrub_console_plugin, scrub_generic_field, scrub_network_plugin};

// RRWebEventType
pub const TYPE_FULL_SNAPSHOT: u8 = 2;
pub const TYPE_INCREMENTAL: u8 = 3;
pub const TYPE_META: u8 = 4;
pub const TYPE_CUSTOM: u8 = 5;
pub const TYPE_PLUGIN: u8 = 6;

// RRWebEventSource (incremental)
pub const SOURCE_MUTATION: u8 = 0;
pub const SOURCE_INPUT: u8 = 5;
pub const SOURCE_STYLESHEET_RULE: u8 = 8;
pub const SOURCE_CANVAS_MUTATION: u8 = 9;
pub const SOURCE_STYLE_DECLARATION: u8 = 13;
pub const SOURCE_ADOPTED_STYLESHEET: u8 = 15;

pub const NETWORK_PLUGIN: &str = "rrweb/network@1";
pub const CONSOLE_PLUGIN: &str = "rrweb/console@1";

/// Panic backstop for the anyhow-based entry points (see [`crate::unwind`]).
fn contain_panics<T>(f: impl FnOnce() -> Result<T>) -> Result<T> {
    crate::unwind::contain_unwind(f, |msg| anyhow::anyhow!("panic while anonymizing: {msg}"))
}

/// Anonymizes every event in a parsed message (`{ windowId: Event[] }`) in place. `Ok(None)` means
/// nothing changed (the caller can keep its original). `Err` means an event could not be anonymized —
/// fail closed, the caller must drop the message. A single `Ctx` spans the whole message so its blur
/// memo is shared across every event (an image recurring across events is blurred once).
pub fn anonymize_message(allow: &AllowLists, json: &mut [u8]) -> Result<Option<String>> {
    contain_panics(|| {
        reject_if_too_deep(json, "eventsByWindowId")?;
        let mut root = parse_untrusted(json).context("parse eventsByWindowId json")?;
        let Some(obj) = as_object_mut(&mut root) else {
            bail!("eventsByWindowId is not an object");
        };
        let ctx = Ctx::new(allow);
        let mut changed = false;
        for (_, events) in obj.iter_mut() {
            if let Some(arr) = as_array_mut(events) {
                for event in arr.iter_mut() {
                    changed |= route_event(&ctx, event)?;
                }
            }
        }
        if !changed {
            return Ok(None);
        }
        Ok(Some(root.encode()))
    })
}

/// Scrub one JSONL line: a bare rrweb event object or the PostHog `["window_id", event]` tuple.
/// `Ok(Some(scrubbed))` = the line changed. `Ok(None)` = a recognized event that needed no
/// scrubbing (identical to the input). `Err` = could not anonymize; fail closed, drop the line.
///
/// `line` is scratch — the in-place parse consumes it, so on `Ok(None)` keep a prior copy of the
/// bytes, not this buffer. Tuple lines come back with the wrapper intact and the window id
/// untouched. Anything that is not one of the two recognized shapes — a scalar, or an array that is
/// not a `[string, object]` pair — is an `Err`, not a silent pass-through: a scrubber must fail
/// closed on input it doesn't understand rather than leave the caller to guess whether unrecognized
/// bytes were safe to keep. Invalid JSON is likewise an `Err`.
pub fn anonymize_line(allow: &AllowLists, line: &mut [u8]) -> Result<Option<String>> {
    anonymize_line_with_ctx(&Ctx::new(allow), line)
}

/// [`anonymize_line`] with a caller-owned [`Ctx`], so one blur memo spans a whole session file
/// (an image recurring across lines is decoded and blurred once, like `anonymize_message` does
/// across a message's events). The cumulative cv decompression budget is per line — it resets on
/// every call, so a long session cannot starve later lines.
pub fn anonymize_line_with_ctx(ctx: &Ctx<'_>, line: &mut [u8]) -> Result<Option<String>> {
    contain_panics(|| {
        reject_if_too_deep(line, "jsonl line")?;
        let mut root = parse_untrusted(line).context("parse jsonl line")?;
        ctx.reset_cv_budget();
        let changed = match &mut root {
            Value::Object(_) => route_event(ctx, &mut root)?,
            Value::Array(items) => match items.as_mut_slice() {
                [Value::String(_), event @ Value::Object(_)] => route_event(ctx, event)?,
                _ => bail!("jsonl line is an array but not a [window_id, event] tuple"),
            },
            _ => {
                bail!("jsonl line is neither an rrweb event object nor a [window_id, event] tuple")
            }
        };
        if !changed {
            return Ok(None);
        }
        Ok(Some(root.encode()))
    })
}

/// Convenience for tests/callers holding a single event as a JSON string: parse, scrub, re-serialize.
pub fn anonymize_event_str(allow: &AllowLists, event_json: &str) -> Result<String> {
    contain_panics(|| {
        let mut bytes = event_json.as_bytes().to_vec();
        let mut value = parse_untrusted(&mut bytes).context("parse event json")?;
        route_event(&Ctx::new(allow), &mut value)?;
        Ok(value.encode())
    })
}

/// Scrubs a single event in place, returning whether it changed. `Err` = "could not anonymize".
/// Builds its own `Ctx` (single-event scope); the message path uses [`anonymize_message`] instead so
/// the blur memo is shared across events.
pub fn anonymize_event(allow: &AllowLists, event: &mut Value<'_>) -> Result<bool> {
    contain_panics(|| route_event(&Ctx::new(allow), event))
}

/// True when the event's `cv` marker means "compressed" (present and non-null).
#[doc(hidden)]
pub fn is_compressed_marker(v: Option<&Value<'_>>) -> bool {
    matches!(v, Some(v) if !matches!(v, Value::Static(StaticNode::Null)))
}

/// Internal routing shared by the entry points — consume [`anonymize_event`] or
/// [`anonymize_line`] instead; this may change signature in any release.
#[doc(hidden)]
pub fn route_event(ctx: &Ctx<'_>, event: &mut Value<'_>) -> Result<bool> {
    let Some(obj) = as_object_mut(event) else {
        return Ok(false);
    };
    let compressed = is_compressed_marker(obj.get("cv"));
    let ty = obj.get("type").and_then(as_small_uint);
    let Some(data) = obj.get_mut("data") else {
        return Ok(false);
    };
    route_data(ctx, ty, compressed, data)
}

/// Scrubs an event's `data` value in place given its routing shape (`type` + `cv` marker). This is the
/// single routing implementation shared by the tree walk and the streaming span-splice path: everything
/// the anonymizer changes lives inside `data`, so both paths agree by construction.
#[doc(hidden)]
pub fn route_data(
    ctx: &Ctx<'_>,
    ty: Option<u8>,
    compressed: bool,
    data: &mut Value<'_>,
) -> Result<bool> {
    match ty {
        Some(TYPE_FULL_SNAPSHOT) => {
            if compressed && matches!(data, Value::String(_)) {
                scrub_compressed_full_snapshot(ctx, data)
            } else {
                // Not actually whole-blob compressed — scrub as a plain object.
                Ok(scrub_full_snapshot(ctx, data))
            }
        }
        Some(TYPE_INCREMENTAL) => {
            let source = match as_object(data) {
                Some(d) => d.get("source").and_then(as_small_uint),
                None => return Ok(false),
            };
            match source {
                Some(SOURCE_MUTATION) => {
                    if compressed {
                        scrub_compressed_mutation(ctx, as_object_mut(data).unwrap())
                    } else {
                        Ok(scrub_mutation(ctx, data))
                    }
                }
                Some(SOURCE_INPUT) => Ok(scrub_text_field(
                    ctx.allow,
                    as_object_mut(data).unwrap(),
                    "text",
                )),
                Some(SOURCE_CANVAS_MUTATION) => Ok(scrub_canvas_mutation(ctx, data)),
                Some(SOURCE_STYLESHEET_RULE) => {
                    Ok(scrub_style_sheet_rule(ctx, as_object_mut(data).unwrap()))
                }
                Some(SOURCE_STYLE_DECLARATION) => {
                    Ok(scrub_style_declaration(ctx, as_object_mut(data).unwrap()))
                }
                Some(SOURCE_ADOPTED_STYLESHEET) => {
                    Ok(scrub_adopted_style_sheet(ctx, as_object_mut(data).unwrap()))
                }
                _ => Ok(false),
            }
        }
        Some(TYPE_META) => {
            // Meta `href` is the page URL — strip the authority and rewrite the host to example.com.
            let Some(data) = as_object_mut(data) else {
                return Ok(false);
            };
            let Some(href) = data.get("href").and_then(as_str) else {
                return Ok(false);
            };
            match scrub_url_opts(ctx, href, true) {
                Some(v) => {
                    data.insert(key("href"), string_value(v));
                    Ok(true)
                }
                None => Ok(false),
            }
        }
        Some(TYPE_CUSTOM) => match as_object_mut(data) {
            Some(data) => Ok(scrub_generic_field(ctx, data, "payload")),
            None => Ok(false),
        },
        Some(TYPE_PLUGIN) => {
            let Some(data) = as_object_mut(data) else {
                return Ok(false);
            };
            let plugin = data.get("plugin").and_then(as_str).map(str::to_string);
            Ok(match plugin.as_deref() {
                Some(NETWORK_PLUGIN) => scrub_network_plugin(ctx, data, "payload"),
                Some(CONSOLE_PLUGIN) => scrub_console_plugin(ctx, data, "payload"),
                _ => scrub_generic_field(ctx, data, "payload"),
            })
        }
        // DomContentLoaded, Load, unknown types: pass-through.
        _ => Ok(false),
    }
}

fn scrub_text_field(allow: &AllowLists, obj: &mut Object<'_>, field: &'static str) -> bool {
    let Some(cur) = obj.get(field).and_then(as_str) else {
        return false;
    };
    match scrub_text(allow, cur) {
        Some(v) => {
            obj.insert(key(field), string_value(v));
            true
        }
        None => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn message_scrubs_every_window() {
        let allow = AllowLists::new(["hello", "here"], Vec::<String>::new());
        let mut json = br#"{"w1":[{"type":3,"data":{"source":5,"id":1,"text":"hello secret","isChecked":false}}],"w2":[{"type":3,"data":{"source":5,"id":2,"text":"world here","isChecked":false}}]}"#.to_vec();
        let out = anonymize_message(&allow, &mut json)
            .unwrap()
            .expect("something changed");
        let v: serde_json::Value = serde_json::from_str(&out).unwrap();
        assert_eq!(v["w1"][0]["data"]["text"], "hello ******");
        assert_eq!(v["w2"][0]["data"]["text"], "***** here");
    }

    #[test]
    fn unchanged_message_returns_none() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        // A Load event (type 1) is pass-through; the caller keeps its original parse.
        let mut json = br#"{"w1":[{"type":1,"data":{}}]}"#.to_vec();
        assert!(anonymize_message(&allow, &mut json).unwrap().is_none());
    }

    #[test]
    fn line_scrubs_a_tuple_keeping_the_wrapper_and_window_id() {
        let allow = AllowLists::new(["keep"], Vec::<String>::new());
        let mut line =
            br#"["w-1",{"type":3,"data":{"source":5,"id":1,"text":"keep secret","isChecked":false}}]"#
                .to_vec();
        let out = anonymize_line(&allow, &mut line)
            .unwrap()
            .expect("the text changes");
        assert!(out.starts_with(r#"["w-1","#), "wrapper intact: {out}");
        let v: serde_json::Value = serde_json::from_str(&out).unwrap();
        assert_eq!(v[1]["data"]["text"], "keep ******");
    }

    #[test]
    fn line_scrubs_a_bare_event_like_its_tuple_twin() {
        let allow = AllowLists::new(["keep"], Vec::<String>::new());
        let event =
            r#"{"type":3,"data":{"source":5,"id":1,"text":"keep secret","isChecked":false}}"#;

        let mut bare = event.as_bytes().to_vec();
        let bare_out = anonymize_line(&allow, &mut bare).unwrap().unwrap();

        let mut tuple = format!(r#"["w-1",{event}]"#).into_bytes();
        let tuple_out = anonymize_line(&allow, &mut tuple).unwrap().unwrap();

        let tuple_v: serde_json::Value = serde_json::from_str(&tuple_out).unwrap();
        let bare_v: serde_json::Value = serde_json::from_str(&bare_out).unwrap();
        assert_eq!(bare_v, tuple_v[1]);
    }

    #[test]
    fn line_returns_none_only_for_unchanged_recognized_events() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        // Recognized events that need no scrubbing (type 1 is pass-through), bare and tuple-wrapped.
        for line in [
            br#"{"type":1,"data":{}}"#.as_slice(),
            br#"["w-1",{"type":1,"data":{}}]"#.as_slice(),
        ] {
            let mut bytes = line.to_vec();
            assert!(
                anonymize_line(&allow, &mut bytes).unwrap().is_none(),
                "expected Ok(None) for {}",
                String::from_utf8_lossy(line)
            );
        }
    }

    #[test]
    fn line_fails_closed_on_unrecognized_shapes_and_invalid_json() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        // A scrubber must not silently pass through input it doesn't recognize as an event.
        for line in [
            br#"["w-1","not an event"]"#.as_slice(), // tuple with a non-object second element
            br#"[{"type":1},{"type":1}]"#.as_slice(), // array of events, not a [window_id, event] pair
            br#"["w-1",{"type":1},{"extra":1}]"#.as_slice(), // three-element array
            br#"42"#.as_slice(),                      // scalar
            br#""just a string""#.as_slice(),         // scalar
            br#"{not json"#.as_slice(),               // invalid JSON
        ] {
            let mut bytes = line.to_vec();
            assert!(
                anonymize_line(&allow, &mut bytes).is_err(),
                "expected Err for {}",
                String::from_utf8_lossy(line)
            );
        }
    }

    #[test]
    fn line_streaming_shares_the_blur_memo_across_lines() {
        use crate::testkit::png_data_uri;
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        let uri = png_data_uri(40, 40, [12, 34, 56, 255]);
        let line = serde_json::to_string(&serde_json::json!({
            "type": 2,
            "data": {
                "node": { "type": 0, "childNodes": [
                    { "type": 2, "tagName": "div", "attributes": { "rr_dataURL": uri }, "childNodes": [] }
                ]},
                "initialOffset": { "top": 0, "left": 0 }
            }
        }))
        .unwrap();

        let mut first = line.clone().into_bytes();
        let mut second = line.into_bytes();
        let first_out = anonymize_line_with_ctx(&ctx, &mut first).unwrap().unwrap();
        let second_out = anonymize_line_with_ctx(&ctx, &mut second).unwrap().unwrap();
        assert_eq!(
            first_out, second_out,
            "a recurring image must blur identically through the shared memo"
        );
    }

    #[test]
    fn line_resets_the_cv_budget_per_call() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        let texts_gz = crate::cv::bytes_to_latin1(
            &crate::gzip::gzip(br#"[{"id":5,"value":"topsecret stuff"}]"#).unwrap(),
        );
        let line = serde_json::to_string(&serde_json::json!(
            { "type": 3, "cv": "2024-10", "data": { "source": 0, "texts": texts_gz } }
        ))
        .unwrap();

        // A prior line exhausted the budget; the next call must start from a fresh one.
        ctx.cv_budget.set(0);
        let mut bytes = line.into_bytes();
        let out = anonymize_line_with_ctx(&ctx, &mut bytes)
            .unwrap()
            .expect("the cv payload decompresses and scrubs");
        assert!(out.contains("source"), "still a mutation event: {out}");
    }

    #[test]
    fn recurring_inline_image_is_neutralized_across_windows() {
        // An inline image can recur across events/windows in one message (the case the per-message blur
        // memo targets). Every occurrence must be neutralized to a data-image — never the raw original —
        // and identical inputs must yield identical output. This drives the real `anonymize_message`
        // entry (route -> full snapshot -> dom -> blur), which the deterministic JSON fixtures can't
        // cover (blurred bytes differ from the TS `sharp` output, so image parity is Rust-only).
        use crate::testkit::png_data_uri;
        use serde_json::json;
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let uri = png_data_uri(40, 40, [12, 34, 56, 255]);
        let snapshot = json!({
            "type": 2,
            "data": {
                "node": { "type": 0, "childNodes": [
                    { "type": 2, "tagName": "div", "attributes": { "rr_dataURL": uri.clone() }, "childNodes": [] }
                ]},
                "initialOffset": { "top": 0, "left": 0 }
            }
        });
        let message = json!({ "w1": [snapshot.clone()], "w2": [snapshot] });
        let mut bytes = serde_json::to_vec(&message).unwrap();
        let out = anonymize_message(&allow, &mut bytes)
            .unwrap()
            .expect("the image should change");
        let v: serde_json::Value = serde_json::from_str(&out).unwrap();
        let img = |w: &str| {
            v[w][0]["data"]["node"]["childNodes"][0]["attributes"]["rr_dataURL"]
                .as_str()
                .unwrap()
                .to_string()
        };
        assert!(img("w1").starts_with("data:image/"), "still an image");
        assert_ne!(img("w1"), uri, "raw inline image must not pass through");
        assert_eq!(
            img("w1"),
            img("w2"),
            "a recurring image must be neutralized consistently"
        );
    }
}
