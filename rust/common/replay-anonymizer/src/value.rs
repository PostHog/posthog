//! Generic / network / console value scrubs over parsed JSON (Custom and Plugin payloads).
//! Mirrors `anonymize/value.ts`.

use simd_json::value::owned::Object;
use simd_json::OwnedValue;

use crate::allow_lists::AllowLists;
use crate::json::{as_array_mut, as_object_mut, is_object};
use crate::text::scrub_text;
use crate::url::scrub_url;

fn looks_like_url(s: &str) -> bool {
    s.starts_with("http://") || s.starts_with("https://")
}

fn scrub_string_leaf(allow: &AllowLists, s: &str) -> Option<String> {
    if looks_like_url(s) {
        scrub_url(allow, s)
    } else {
        scrub_text(allow, s)
    }
}

/// Scrub `slot`: a string leaf (with writeback), otherwise recurse into it.
fn scrub_child(allow: &AllowLists, slot: &mut OwnedValue) -> bool {
    if let OwnedValue::String(s) = slot {
        match scrub_string_leaf(allow, s) {
            Some(v) => {
                *slot = OwnedValue::String(v);
                true
            }
            None => false,
        }
    } else {
        scrub_value_in_place(allow, slot)
    }
}

/// Recursively scrub string leaves inside an array/object, mutating in place.
pub fn scrub_value_in_place(allow: &AllowLists, value: &mut OwnedValue) -> bool {
    let mut changed = false;
    match value {
        OwnedValue::Array(arr) => {
            for item in arr.iter_mut() {
                changed |= scrub_child(allow, item);
            }
        }
        OwnedValue::Object(obj) => {
            for (_, val) in obj.iter_mut() {
                changed |= scrub_child(allow, val);
            }
        }
        _ => {}
    }
    changed
}

/// Generic scrub of `owner[key]`, handling both a string leaf and a container.
pub fn scrub_generic_field(allow: &AllowLists, owner: &mut Object, key: &str) -> bool {
    match owner.get_mut(key) {
        Some(slot) => scrub_child(allow, slot),
        None => false,
    }
}

fn scrub_field_with(
    allow: &AllowLists,
    obj: &mut Object,
    key: &str,
    scrub: fn(&AllowLists, &str) -> Option<String>,
) -> bool {
    let Some(cur) = obj
        .get(key)
        .and_then(crate::json::as_str)
        .map(str::to_string)
    else {
        return false;
    };
    match scrub(allow, &cur) {
        Some(v) => {
            obj.insert(key.to_string(), OwnedValue::String(v));
            true
        }
        None => false,
    }
}

/// rrweb/network@1 payload: `{ requests: CapturedNetworkRequest[] }`. Per request: `name` is a
/// Resource Timing URL (URL-scrub); request/response bodies and every header value are free text.
pub fn scrub_network_plugin(allow: &AllowLists, owner: &mut Object, key: &str) -> bool {
    if !owner.get(key).map(is_object).unwrap_or(false) {
        return scrub_generic_field(allow, owner, key);
    }
    let Some(payload) = owner.get_mut(key).and_then(as_object_mut) else {
        return false;
    };
    let Some(reqs) = payload.get_mut("requests").and_then(as_array_mut) else {
        return false;
    };
    let mut changed = false;
    for req in reqs.iter_mut() {
        let Some(robj) = as_object_mut(req) else {
            continue;
        };
        changed |= scrub_field_with(allow, robj, "name", scrub_url);
        for field in ["requestBody", "responseBody"] {
            changed |= scrub_field_with(allow, robj, field, scrub_text);
        }
        for field in ["requestHeaders", "responseHeaders"] {
            if let Some(hdrs) = robj.get_mut(field).and_then(as_object_mut) {
                for (_, v) in hdrs.iter_mut() {
                    if let OwnedValue::String(s) = v {
                        if let Some(nv) = scrub_text(allow, s) {
                            *v = OwnedValue::String(nv);
                            changed = true;
                        }
                    }
                }
            }
        }
    }
    changed
}

/// rrweb/console@1 payload: `{ level, payload: string[], trace: string[] }`.
pub fn scrub_console_plugin(allow: &AllowLists, owner: &mut Object, key: &str) -> bool {
    if !owner.get(key).map(is_object).unwrap_or(false) {
        return scrub_generic_field(allow, owner, key);
    }
    let Some(payload) = owner.get_mut(key).and_then(as_object_mut) else {
        return false;
    };
    let mut changed = false;
    for field in ["payload", "trace"] {
        if let Some(arr) = payload.get_mut(field).and_then(as_array_mut) {
            for v in arr.iter_mut() {
                // Console frames can hold URLs (stack traces); scrub URL-aware, not as plain text.
                if let OwnedValue::String(s) = v {
                    if let Some(nv) = scrub_string_leaf(allow, s) {
                        *v = OwnedValue::String(nv);
                        changed = true;
                    }
                }
            }
        }
    }
    changed
}
