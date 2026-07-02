//! Small helpers for mutating `simd_json::OwnedValue` in place, mirroring the TS scrubbers which treat
//! every rrweb node as a generic `Record<string, unknown>`. Working on a generic value (not typed
//! structs) preserves unknown fields exactly on round-trip, matching the TS in-place mutation.

use simd_json::value::owned::Object;
use simd_json::{OwnedValue, StaticNode};

pub fn as_object_mut(v: &mut OwnedValue) -> Option<&mut Object> {
    match v {
        OwnedValue::Object(o) => Some(o.as_mut()),
        _ => None,
    }
}

pub fn as_array_mut(v: &mut OwnedValue) -> Option<&mut Vec<OwnedValue>> {
    match v {
        OwnedValue::Array(a) => Some(a),
        _ => None,
    }
}

pub fn as_object(v: &OwnedValue) -> Option<&Object> {
    match v {
        OwnedValue::Object(o) => Some(o.as_ref()),
        _ => None,
    }
}

pub fn as_array(v: &OwnedValue) -> Option<&Vec<OwnedValue>> {
    match v {
        OwnedValue::Array(a) => Some(a),
        _ => None,
    }
}

pub fn as_str(v: &OwnedValue) -> Option<&str> {
    match v {
        OwnedValue::String(s) => Some(s.as_str()),
        _ => None,
    }
}

pub fn is_object(v: &OwnedValue) -> bool {
    matches!(v, OwnedValue::Object(_))
}

/// A JSON number read as `u32` (accepts an integral float, matching JS `typeof x === 'number'`).
pub fn as_u32(v: &OwnedValue) -> Option<u32> {
    match v {
        OwnedValue::Static(StaticNode::I64(n)) => u32::try_from(*n).ok(),
        OwnedValue::Static(StaticNode::U64(n)) => u32::try_from(*n).ok(),
        OwnedValue::Static(StaticNode::F64(f))
            if f.fract() == 0.0 && *f >= 0.0 && *f <= u32::MAX as f64 =>
        {
            Some(*f as u32)
        }
        _ => None,
    }
}

/// A JSON number read as `usize` (accepts an integral non-negative float).
pub fn as_usize(v: &OwnedValue) -> Option<usize> {
    match v {
        OwnedValue::Static(StaticNode::I64(n)) => usize::try_from(*n).ok(),
        OwnedValue::Static(StaticNode::U64(n)) => usize::try_from(*n).ok(),
        OwnedValue::Static(StaticNode::F64(f)) if f.fract() == 0.0 && *f >= 0.0 => {
            Some(*f as usize)
        }
        _ => None,
    }
}

/// Reads a small non-negative integer field (rrweb `type`/`source` enums). Accepts an integral float
/// too (JS `typeof x === 'number'` matches `2.0`), so a float-encoded discriminant still routes to the
/// right scrubber rather than silently passing through unscrubbed.
pub fn as_small_uint(v: &OwnedValue) -> Option<u8> {
    match v {
        OwnedValue::Static(StaticNode::F64(f))
            if f.fract() == 0.0 && *f >= 0.0 && *f <= u8::MAX as f64 =>
        {
            Some(*f as u8)
        }
        OwnedValue::Static(StaticNode::I64(n)) => u8::try_from(*n).ok(),
        OwnedValue::Static(StaticNode::U64(n)) => u8::try_from(*n).ok(),
        _ => None,
    }
}

pub fn is_true(v: &OwnedValue) -> bool {
    matches!(v, OwnedValue::Static(StaticNode::Bool(true)))
}

pub fn string_value(s: String) -> OwnedValue {
    OwnedValue::String(s)
}

// Untrusted rrweb can nest arbitrarily deep. Both the simd-json parse and the recursive scrub walk one
// stack frame per level, so a crafted payload could overflow the worker-thread stack — an abort, which
// `catch_unwind` cannot contain. Reject over-deep input up front (before parsing). Legitimate DOM/canvas
// nesting is well under this. Applies to the outer message *and* to every gunzipped `cv` payload.
pub const MAX_JSON_DEPTH: usize = 1024;

/// Max `{`/`[` nesting depth in raw JSON, ignoring bracket bytes inside strings. Linear, no recursion.
pub fn max_bracket_depth(json: &[u8]) -> usize {
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

/// Rejects raw JSON bytes that nest past [`MAX_JSON_DEPTH`], failing closed before any recursive parse.
pub fn reject_if_too_deep(json: &[u8], context: &str) -> anyhow::Result<()> {
    let depth = max_bracket_depth(json);
    if depth > MAX_JSON_DEPTH {
        anyhow::bail!("{context} nested too deep ({depth} > {MAX_JSON_DEPTH})");
    }
    Ok(())
}
