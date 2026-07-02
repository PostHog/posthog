//! Routes each parsed rrweb event to the right scrubber by type/source, and walks a whole parsed
//! message (`{ windowId: Event[] }`). Mirrors `anonymize/anonymize-event.ts` (`routeEvent`).

use anyhow::{bail, Context, Result};
use simd_json::prelude::Writable;
use simd_json::value::owned::Object;
use simd_json::{OwnedValue, StaticNode};

use crate::allow_lists::AllowLists;
use crate::canvas::scrub_canvas_mutation;
use crate::cv::{scrub_compressed_full_snapshot, scrub_compressed_mutation};
use crate::dom::{scrub_full_snapshot, scrub_mutation};
use crate::json::{as_array_mut, as_object, as_object_mut, as_small_uint, as_str};
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

// Untrusted rrweb can nest arbitrarily deep; both the JSON parse and the recursive scrub walk one
// stack frame per level, so a crafted payload could overflow the worker-thread stack (an abort, not a
// catchable error). Reject over-deep input up front. Legitimate DOM/canvas nesting is well under this.
const MAX_JSON_DEPTH: usize = 1024;

/// Anonymizes every event in a parsed message (`{ windowId: Event[] }`) in place. `Ok(None)` means
/// nothing changed (the caller can keep its original). `Err` means an event could not be anonymized —
/// fail closed, the caller must drop the message.
pub fn anonymize_message(allow: &AllowLists, json: &mut [u8]) -> Result<Option<String>> {
    let depth = max_bracket_depth(json);
    if depth > MAX_JSON_DEPTH {
        bail!("eventsByWindowId nested too deep ({depth} > {MAX_JSON_DEPTH})");
    }
    let mut root = simd_json::to_owned_value(json).context("parse eventsByWindowId json")?;
    let Some(obj) = as_object_mut(&mut root) else {
        bail!("eventsByWindowId is not an object");
    };
    let mut changed = false;
    for (_, events) in obj.iter_mut() {
        if let Some(arr) = as_array_mut(events) {
            for event in arr.iter_mut() {
                changed |= anonymize_event(allow, event)?;
            }
        }
    }
    if !changed {
        return Ok(None);
    }
    Ok(Some(root.encode()))
}

/// Max `{`/`[` nesting depth in raw JSON, ignoring bracket bytes inside strings. Linear, no recursion.
fn max_bracket_depth(json: &[u8]) -> usize {
    let mut depth = 0usize;
    let mut max = 0usize;
    let mut in_string = false;
    let mut escaped = false;
    for &b in json {
        if in_string {
            if escaped {
                escaped = false;
            } else if b == b'\\' {
                escaped = true;
            } else if b == b'"' {
                in_string = false;
            }
            continue;
        }
        match b {
            b'"' => in_string = true,
            b'{' | b'[' => {
                depth += 1;
                max = max.max(depth);
            }
            b'}' | b']' => depth = depth.saturating_sub(1),
            _ => {}
        }
    }
    max
}

/// Convenience for tests/callers holding a single event as a JSON string: parse, scrub, re-serialize.
pub fn anonymize_event_str(allow: &AllowLists, event_json: &str) -> Result<String> {
    let mut bytes = event_json.as_bytes().to_vec();
    let mut value = simd_json::to_owned_value(&mut bytes).context("parse event json")?;
    anonymize_event(allow, &mut value)?;
    Ok(value.encode())
}

/// Scrubs a single event in place, returning whether it changed. `Err` = "could not anonymize".
pub fn anonymize_event(allow: &AllowLists, event: &mut OwnedValue) -> Result<bool> {
    let Some(obj) = as_object_mut(event) else {
        return Ok(false);
    };
    let compressed =
        matches!(obj.get("cv"), Some(v) if !matches!(v, OwnedValue::Static(StaticNode::Null)));

    match obj.get("type").and_then(as_small_uint) {
        Some(TYPE_FULL_SNAPSHOT) => {
            if compressed {
                scrub_compressed_full_snapshot(allow, obj)
            } else {
                match obj.get_mut("data") {
                    Some(data) => Ok(scrub_full_snapshot(allow, data)),
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
                        scrub_compressed_mutation(allow, obj)
                    } else {
                        Ok(scrub_mutation(allow, obj.get_mut("data").unwrap()))
                    }
                }
                Some(SOURCE_INPUT) => Ok(scrub_text_field(
                    allow,
                    obj.get_mut("data").and_then(as_object_mut).unwrap(),
                    "text",
                )),
                Some(SOURCE_CANVAS_MUTATION) => {
                    Ok(scrub_canvas_mutation(allow, obj.get_mut("data").unwrap()))
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
            match scrub_url_opts(allow, &href, true) {
                Some(v) => {
                    data.insert("href".to_string(), OwnedValue::String(v));
                    Ok(true)
                }
                None => Ok(false),
            }
        }
        Some(TYPE_CUSTOM) => match obj.get_mut("data").and_then(as_object_mut) {
            Some(data) => Ok(scrub_generic_field(allow, data, "payload")),
            None => Ok(false),
        },
        Some(TYPE_PLUGIN) => {
            let Some(data) = obj.get_mut("data").and_then(as_object_mut) else {
                return Ok(false);
            };
            let plugin = data.get("plugin").and_then(as_str).map(str::to_string);
            Ok(match plugin.as_deref() {
                Some(NETWORK_PLUGIN) => scrub_network_plugin(allow, data, "payload"),
                Some(CONSOLE_PLUGIN) => scrub_console_plugin(allow, data, "payload"),
                _ => scrub_generic_field(allow, data, "payload"),
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
