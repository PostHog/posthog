//! Routes each parsed rrweb event to the right scrubber by type/source, and walks a whole parsed
//! message (`{ windowId: Event[] }`). Mirrors `anonymize/anonymize-event.ts` (`routeEvent`).

use anyhow::{bail, Context, Result};
use simd_json::prelude::Writable;
use simd_json::value::owned::Object;
use simd_json::{OwnedValue, StaticNode};

use crate::allow_lists::AllowLists;
use crate::canvas::scrub_canvas_mutation;
use crate::context::Ctx;
use crate::cv::{scrub_compressed_full_snapshot, scrub_compressed_mutation};
use crate::dom::{scrub_full_snapshot, scrub_mutation};
use crate::json::{
    as_array_mut, as_object, as_object_mut, as_small_uint, as_str, reject_if_too_deep,
};
use crate::text::scrub_text;
use crate::url::scrub_url_opts;
use crate::value::{scrub_console_plugin, scrub_generic_field, scrub_network_plugin};

// RRWebEventType
const TYPE_FULL_SNAPSHOT: u8 = 2;
const TYPE_INCREMENTAL: u8 = 3;
const TYPE_META: u8 = 4;
const TYPE_CUSTOM: u8 = 5;
const TYPE_PLUGIN: u8 = 6;

// RRWebEventSource (incremental)
const SOURCE_MUTATION: u8 = 0;
const SOURCE_INPUT: u8 = 5;
const SOURCE_CANVAS_MUTATION: u8 = 9;

const NETWORK_PLUGIN: &str = "rrweb/network@1";
const CONSOLE_PLUGIN: &str = "rrweb/console@1";

/// Anonymizes every event in a parsed message (`{ windowId: Event[] }`) in place. `Ok(None)` means
/// nothing changed (the caller can keep its original). `Err` means an event could not be anonymized —
/// fail closed, the caller must drop the message. A single `Ctx` spans the whole message so its blur
/// memo is shared across every event (an image recurring across events is blurred once).
pub fn anonymize_message(allow: &AllowLists, json: &mut [u8]) -> Result<Option<String>> {
    reject_if_too_deep(json, "eventsByWindowId")?;
    let mut root = simd_json::to_owned_value(json).context("parse eventsByWindowId json")?;
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
}

/// Convenience for tests/callers holding a single event as a JSON string: parse, scrub, re-serialize.
pub fn anonymize_event_str(allow: &AllowLists, event_json: &str) -> Result<String> {
    let mut bytes = event_json.as_bytes().to_vec();
    let mut value = simd_json::to_owned_value(&mut bytes).context("parse event json")?;
    anonymize_event(allow, &mut value)?;
    Ok(value.encode())
}

/// Scrubs a single event in place, returning whether it changed. `Err` = "could not anonymize".
/// Builds its own `Ctx` (single-event scope); the message path uses [`anonymize_message`] instead so
/// the blur memo is shared across events.
pub fn anonymize_event(allow: &AllowLists, event: &mut OwnedValue) -> Result<bool> {
    route_event(&Ctx::new(allow), event)
}

fn route_event(ctx: &Ctx<'_>, event: &mut OwnedValue) -> Result<bool> {
    let Some(obj) = as_object_mut(event) else {
        return Ok(false);
    };
    let compressed =
        matches!(obj.get("cv"), Some(v) if !matches!(v, OwnedValue::Static(StaticNode::Null)));

    match obj.get("type").and_then(as_small_uint) {
        Some(TYPE_FULL_SNAPSHOT) => {
            if compressed {
                scrub_compressed_full_snapshot(ctx, obj)
            } else {
                match obj.get_mut("data") {
                    Some(data) => Ok(scrub_full_snapshot(ctx, data)),
                    None => Ok(false),
                }
            }
        }
        Some(TYPE_INCREMENTAL) => {
            let source = obj
                .get("data")
                .and_then(as_object)
                .and_then(|d| d.get("source"))
                .and_then(as_small_uint);
            if obj.get("data").and_then(as_object).is_none() {
                return Ok(false);
            }
            match source {
                Some(SOURCE_MUTATION) => {
                    if compressed {
                        scrub_compressed_mutation(ctx, obj)
                    } else {
                        Ok(scrub_mutation(ctx, obj.get_mut("data").unwrap()))
                    }
                }
                Some(SOURCE_INPUT) => Ok(scrub_text_field(
                    ctx.allow,
                    obj.get_mut("data").and_then(as_object_mut).unwrap(),
                    "text",
                )),
                Some(SOURCE_CANVAS_MUTATION) => {
                    Ok(scrub_canvas_mutation(ctx, obj.get_mut("data").unwrap()))
                }
                _ => Ok(false),
            }
        }
        Some(TYPE_META) => {
            // Meta `href` is the page URL — strip the authority and rewrite the host to example.com.
            let Some(data) = obj.get_mut("data").and_then(as_object_mut) else {
                return Ok(false);
            };
            let Some(href) = data.get("href").and_then(as_str).map(str::to_string) else {
                return Ok(false);
            };
            match scrub_url_opts(ctx.allow, &href, true) {
                Some(v) => {
                    data.insert("href".to_string(), OwnedValue::String(v));
                    Ok(true)
                }
                None => Ok(false),
            }
        }
        Some(TYPE_CUSTOM) => match obj.get_mut("data").and_then(as_object_mut) {
            Some(data) => Ok(scrub_generic_field(ctx.allow, data, "payload")),
            None => Ok(false),
        },
        Some(TYPE_PLUGIN) => {
            let Some(data) = obj.get_mut("data").and_then(as_object_mut) else {
                return Ok(false);
            };
            let plugin = data.get("plugin").and_then(as_str).map(str::to_string);
            Ok(match plugin.as_deref() {
                Some(NETWORK_PLUGIN) => scrub_network_plugin(ctx.allow, data, "payload"),
                Some(CONSOLE_PLUGIN) => scrub_console_plugin(ctx.allow, data, "payload"),
                _ => scrub_generic_field(ctx.allow, data, "payload"),
            })
        }
        // DomContentLoaded, Load, unknown types: pass-through.
        _ => Ok(false),
    }
}

fn scrub_text_field(allow: &AllowLists, obj: &mut Object, key: &str) -> bool {
    let Some(cur) = obj.get(key).and_then(as_str).map(str::to_string) else {
        return false;
    };
    match scrub_text(allow, &cur) {
        Some(v) => {
            obj.insert(key.to_string(), OwnedValue::String(v));
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
