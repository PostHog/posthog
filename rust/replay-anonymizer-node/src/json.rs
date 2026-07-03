//! Small helpers for mutating `simd_json::BorrowedValue` in place, mirroring the TS scrubbers which
//! treat every rrweb node as a generic `Record<string, unknown>`. Working on a generic value (not
//! typed structs) preserves unknown fields exactly on round-trip, matching the TS in-place mutation.
//! The borrowed tree keeps unchanged strings as zero-copy slices of the input bytes; only scrubbed
//! values allocate (`Cow::Owned`).

use std::borrow::Cow;

use simd_json::borrowed::{Object, Value};
use simd_json::StaticNode;

pub fn as_object_mut<'a, 'v>(v: &'a mut Value<'v>) -> Option<&'a mut Object<'v>> {
    match v {
        Value::Object(o) => Some(o.as_mut()),
        _ => None,
    }
}

pub fn as_array_mut<'a, 'v>(v: &'a mut Value<'v>) -> Option<&'a mut Vec<Value<'v>>> {
    match v {
        Value::Array(a) => Some(a),
        _ => None,
    }
}

pub fn as_object<'a, 'v>(v: &'a Value<'v>) -> Option<&'a Object<'v>> {
    match v {
        Value::Object(o) => Some(o.as_ref()),
        _ => None,
    }
}

pub fn as_array<'a, 'v>(v: &'a Value<'v>) -> Option<&'a Vec<Value<'v>>> {
    match v {
        Value::Array(a) => Some(a),
        _ => None,
    }
}

pub fn as_str<'a>(v: &'a Value<'_>) -> Option<&'a str> {
    match v {
        Value::String(s) => Some(s.as_ref()),
        _ => None,
    }
}

pub fn is_object(v: &Value<'_>) -> bool {
    matches!(v, Value::Object(_))
}

/// A JSON number read as `u32` (accepts an integral float, matching JS `typeof x === 'number'`).
pub fn as_u32(v: &Value<'_>) -> Option<u32> {
    match v {
        Value::Static(StaticNode::I64(n)) => u32::try_from(*n).ok(),
        Value::Static(StaticNode::U64(n)) => u32::try_from(*n).ok(),
        Value::Static(StaticNode::F64(f))
            if f.fract() == 0.0 && *f >= 0.0 && *f <= u32::MAX as f64 =>
        {
            Some(*f as u32)
        }
        _ => None,
    }
}

/// A JSON number read as `usize` (accepts an integral non-negative float).
pub fn as_usize(v: &Value<'_>) -> Option<usize> {
    match v {
        Value::Static(StaticNode::I64(n)) => usize::try_from(*n).ok(),
        Value::Static(StaticNode::U64(n)) => usize::try_from(*n).ok(),
        Value::Static(StaticNode::F64(f)) if f.fract() == 0.0 && *f >= 0.0 => Some(*f as usize),
        _ => None,
    }
}

/// A JSON number read as `f64` (any numeric representation), matching JS number semantics.
pub fn as_f64(v: &Value<'_>) -> Option<f64> {
    match v {
        Value::Static(StaticNode::I64(n)) => Some(*n as f64),
        Value::Static(StaticNode::U64(n)) => Some(*n as f64),
        Value::Static(StaticNode::F64(f)) => Some(*f),
        _ => None,
    }
}

/// Reads a small non-negative integer field (rrweb `type`/`source` enums). Accepts an integral float
/// too (JS `typeof x === 'number'` matches `2.0`), so a float-encoded discriminant still routes to the
/// right scrubber rather than silently passing through unscrubbed.
pub fn as_small_uint(v: &Value<'_>) -> Option<u8> {
    match v {
        Value::Static(StaticNode::F64(f))
            if f.fract() == 0.0 && *f >= 0.0 && *f <= u8::MAX as f64 =>
        {
            Some(*f as u8)
        }
        Value::Static(StaticNode::I64(n)) => u8::try_from(*n).ok(),
        Value::Static(StaticNode::U64(n)) => u8::try_from(*n).ok(),
        _ => None,
    }
}

pub fn is_true(v: &Value<'_>) -> bool {
    matches!(v, Value::Static(StaticNode::Bool(true)))
}

pub fn string_value(s: String) -> Value<'static> {
    Value::String(Cow::Owned(s))
}

/// A `'static` object key, so inserts don't tie the map's lifetime to a local.
pub fn key(name: &'static str) -> Cow<'static, str> {
    Cow::Borrowed(name)
}

/// Restore `JSON.parse` duplicate-key semantics on a parsed tree: simd-json's object builder keeps
/// *every* entry for a duplicated key (`get` returns the first, serialization emits all of them),
/// while `JSON.parse` keeps only the last. Left alone, that both diverges from the TS scrubbers and
/// leaks: the walk would scrub the first copy and re-serialize the raw second copy verbatim. Objects
/// with duplicates are rebuilt keeping the last occurrence, recursively.
///
/// Errs on objects too large to dedupe deterministically: halfbrown switches to hash storage past its
/// vec threshold, where the original insertion order (and so "last") is unrecoverable — fail closed.
pub fn dedupe_in_place(v: &mut Value<'_>) -> anyhow::Result<()> {
    match v {
        Value::Array(arr) => {
            for item in arr.iter_mut() {
                dedupe_in_place(item)?;
            }
        }
        Value::Object(obj) => {
            if has_duplicate_keys(obj) {
                // Past halfbrown's vec-mode limit iteration order is no longer insertion order, so
                // "last occurrence wins" cannot be reproduced — reject rather than guess.
                if obj.len() > 32 {
                    anyhow::bail!("cannot dedupe duplicate keys in a large object");
                }
                let entries: Vec<(Cow<'_, str>, Value<'_>)> =
                    std::mem::take(obj.as_mut()).into_iter().collect();
                let rebuilt = obj.as_mut();
                for (k, val) in entries {
                    rebuilt.insert(k, val);
                }
            }
            for (_, val) in obj.iter_mut() {
                dedupe_in_place(val)?;
            }
        }
        _ => {}
    }
    Ok(())
}

fn has_duplicate_keys(obj: &Object<'_>) -> bool {
    let n = obj.len();
    if n < 2 {
        return false;
    }
    if n <= 16 {
        // Allocation-free quadratic check: this runs for every object in every parsed span, so a
        // scratch Vec here would dominate the dedupe cost on DOM-sized trees.
        for (i, key) in obj.keys().enumerate().skip(1) {
            if obj.keys().take(i).any(|prior| prior == key) {
                return true;
            }
        }
        false
    } else {
        let mut seen = ahash::AHashSet::with_capacity(n);
        obj.keys().any(|k| !seen.insert(k.as_ref()))
    }
}

/// Parse untrusted JSON bytes to a borrowed tree with `JSON.parse` semantics (duplicate keys deduped,
/// last occurrence wins). All event-content parses must go through this, not `to_borrowed_value`.
pub fn parse_untrusted<'v>(bytes: &'v mut [u8]) -> anyhow::Result<Value<'v>> {
    let mut value = simd_json::to_borrowed_value(bytes)?;
    dedupe_in_place(&mut value)?;
    Ok(value)
}

/// [`parse_untrusted`] with caller-owned simd-json scratch buffers, so a loop parsing many small
/// spans (the streaming per-event path) doesn't re-allocate the parser's internal buffers per call.
pub fn parse_untrusted_with_buffers<'v>(
    bytes: &'v mut [u8],
    buffers: &mut simd_json::Buffers,
) -> anyhow::Result<Value<'v>> {
    let mut value = simd_json::value::borrowed::to_value_with_buffers(bytes, buffers)?;
    dedupe_in_place(&mut value)?;
    Ok(value)
}

// Untrusted rrweb can nest arbitrarily deep. Both the simd-json parse and the recursive scrub walk one
// stack frame per level, so a crafted payload could overflow the worker-thread stack — an abort, which
// `catch_unwind` cannot contain. Reject over-deep input up front (before parsing). Legitimate DOM/canvas
// nesting is well under this. Applies to the outer message *and* to every gunzipped `cv` payload.
pub const MAX_JSON_DEPTH: usize = 1024;

/// Max `{`/`[` nesting depth in raw JSON, ignoring bracket bytes inside strings. Linear, no
/// recursion; string content (the bulk of replay bytes) is skipped with memchr jumps.
pub fn max_bracket_depth(json: &[u8]) -> usize {
    let mut depth = 0usize;
    let mut max = 0usize;
    let mut pos = 0usize;
    while pos < json.len() {
        match json[pos] {
            b'"' => {
                pos += 1;
                // Bytewise prefix before memchr, same rationale as `scan::skip_string`: most DOM
                // strings are shorter than memchr's per-call setup is worth.
                let fast_end = (pos + 24).min(json.len());
                let mut closed = false;
                while pos < fast_end {
                    match json[pos] {
                        b'"' => {
                            closed = true;
                            break;
                        }
                        b'\\' => pos += 2,
                        _ => pos += 1,
                    }
                }
                while !closed && pos < json.len() {
                    let Some(i) = memchr::memchr2(b'\\', b'"', &json[pos..]) else {
                        pos = json.len();
                        break;
                    };
                    let at = pos + i;
                    if json[at] == b'"' {
                        pos = at;
                        break;
                    }
                    pos = at + 2; // skip the escape and its payload byte
                }
                pos += 1;
            }
            b'{' | b'[' => {
                depth += 1;
                max = max.max(depth);
                pos += 1;
            }
            b'}' | b']' => {
                depth = depth.saturating_sub(1);
                pos += 1;
            }
            _ => pos += 1,
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
