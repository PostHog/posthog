// Bench-only verbatim copy of MLHog prep/labeling/src/v2/scan.rs (paths adapted to crate::mlhog).
use std::io::Write;

use memchr::{memchr2, memchr3};

// SIMD JSON skipping. i at opening `"`; returns index past the closing `"`.
pub fn skip_string(b: &[u8], i: usize) -> Option<usize> {
    let mut j = i + 1;
    loop {
        let p = j + memchr2(b'"', b'\\', b.get(j..)?)?;
        if b[p] == b'"' {
            return Some(p + 1);
        }
        j = p + 2; // backslash escape: skip the next byte
    }
}

fn skip_balanced(b: &[u8], i: usize, open: u8, close: u8) -> Option<usize> {
    let mut depth = 0usize;
    let mut j = i;
    loop {
        let p = j + memchr3(b'"', open, close, b.get(j..)?)?;
        let c = b[p];
        if c == b'"' {
            j = skip_string(b, p)?;
        } else if c == open {
            depth += 1;
            j = p + 1;
        } else {
            depth -= 1;
            j = p + 1;
            if depth == 0 {
                return Some(j);
            }
        }
    }
}

fn skip_scalar(b: &[u8], mut i: usize) -> usize {
    while i < b.len() && !matches!(b[i], b',' | b'}' | b']' | b' ' | b'\t' | b'\n' | b'\r') {
        i += 1;
    }
    i
}

pub fn value_end(b: &[u8], pos: usize) -> Option<usize> {
    let i = skip_ws(b, pos);
    match b.get(i)? {
        b'"' => skip_string(b, i),
        b'{' => skip_balanced(b, i, b'{', b'}'),
        b'[' => skip_balanced(b, i, b'[', b']'),
        _ => Some(skip_scalar(b, i)),
    }
}

pub fn copy_value(b: &[u8], pos: usize, out: &mut Vec<u8>) -> Option<usize> {
    let end = value_end(b, pos)?;
    out.extend_from_slice(&b[pos..end]);
    Some(end)
}

// Skip JSON whitespace (input may be pretty-printed, like v1's simd-json parse tolerates).
pub fn skip_ws(b: &[u8], mut i: usize) -> usize {
    while matches!(b.get(i), Some(b' ' | b'\t' | b'\n' | b'\r')) {
        i += 1;
    }
    i
}

pub fn find_member(b: &[u8], obj_pos: usize, key: &[u8]) -> Option<usize> {
    if b.get(obj_pos) != Some(&b'{') {
        return None;
    }
    let mut i = skip_ws(b, obj_pos + 1);
    if b.get(i) == Some(&b'}') {
        return None;
    }
    loop {
        let ke = skip_string(b, i)?;
        let matched = &b[i + 1..ke - 1] == key;
        let c = skip_ws(b, ke);
        if b.get(c) != Some(&b':') {
            return None;
        }
        let vp = skip_ws(b, c + 1);
        if matched {
            return Some(vp);
        }
        i = skip_ws(b, value_end(b, vp)?);
        match b.get(i) {
            Some(b',') => i = skip_ws(b, i + 1),
            _ => return None,
        }
    }
}

/// Position of the `n`th element of the array at `arr_pos` (0-indexed).
pub fn array_elem(b: &[u8], arr_pos: usize, n: usize) -> Option<usize> {
    if b.get(arr_pos) != Some(&b'[') {
        return None;
    }
    let mut i = skip_ws(b, arr_pos + 1);
    for _ in 0..n {
        i = skip_ws(b, value_end(b, i)?);
        if b.get(i) != Some(&b',') {
            return None;
        }
        i = skip_ws(b, i + 1);
    }
    (b.get(i) != Some(&b']')).then_some(i)
}

/// A u32 scalar at `pos` (via the shared reader), if it's a small unsigned integer.
pub fn uint_at(b: &[u8], pos: usize) -> Option<u32> {
    let end = crate::mlhog::schema::skip_scalar(b, pos);
    std::str::from_utf8(&b[pos..end]).ok()?.parse().ok()
}

pub fn member_uint(b: &[u8], obj_pos: usize, key: &[u8]) -> Option<u8> {
    crate::mlhog::schema::read_uint(b, find_member(b, obj_pos, key)?)
}

/// Owned copy of a string member's logical value.
pub fn member_string(b: &[u8], obj_pos: usize, key: &[u8]) -> Option<String> {
    let p = find_member(b, obj_pos, key)?;
    if b.get(p) != Some(&b'"') {
        return None;
    }
    let mut owned = String::new();
    string_str(b, p, &mut owned).map(|(s, _)| s.to_string())
}

/// Replace a JSON string value at `pos` with `val` (emitting `"val"`), returning the end index.
pub fn replace_string(b: &[u8], pos: usize, out: &mut Vec<u8>, val: &str) -> Option<usize> {
    let (end, _) = scrub_string(b, pos, out, |_, buf| {
        buf.push_str(val);
        true
    })?;
    Some(end)
}

pub fn member_is_true(b: &[u8], obj_pos: usize, key: &[u8]) -> bool {
    match find_member(b, obj_pos, key) {
        Some(p) => b[p..].starts_with(b"true"),
        None => false,
    }
}

/// The logical (unescaped) content of a JSON string value at `pos`, plus the index past it.
pub fn string_str<'a>(b: &'a [u8], pos: usize, owned: &'a mut String) -> Option<(&'a str, usize)> {
    let end = skip_string(b, pos)?;
    let raw = &b[pos + 1..end - 1];
    if raw.contains(&b'\\') {
        *owned = unescape(raw)?;
        Some((owned.as_str(), end))
    } else {
        Some((std::str::from_utf8(raw).ok()?, end))
    }
}

std::thread_local! {
    // Reused across calls to avoid a String alloc per scrubbed value. Safe: `scrub_string` is a leaf
    // (its `f` never re-enters `scrub_string`), so the borrow is released before any recursion.
    static SCRUB_BUF: std::cell::RefCell<String> = const { std::cell::RefCell::new(String::new()) };
}

/// Scrub a JSON string value at `pos` with `f(logical, buf) -> changed`, emitting the result.
/// Non-strings are copied verbatim. Returns (end, changed).
pub fn scrub_string<F: FnOnce(&str, &mut String) -> bool>(
    b: &[u8],
    pos: usize,
    out: &mut Vec<u8>,
    f: F,
) -> Option<(usize, bool)> {
    if b.get(pos) != Some(&b'"') {
        return Some((copy_value(b, pos, out)?, false));
    }
    let mut owned = String::new();
    let (logical, end) = string_str(b, pos, &mut owned)?;
    SCRUB_BUF.with(|cell| {
        let mut scrubbed = cell.borrow_mut();
        scrubbed.clear();
        if f(logical, &mut scrubbed) {
            out.push(b'"');
            json_escape_into(&scrubbed, out);
            out.push(b'"');
            Some((end, true))
        } else {
            out.extend_from_slice(&b[pos..end]);
            Some((end, false))
        }
    })
}

pub fn walk_members<H>(b: &[u8], pos: usize, out: &mut Vec<u8>, mut handler: H) -> Option<usize>
where
    H: FnMut(&[u8], usize, &mut Vec<u8>) -> Option<usize>,
{
    if b.get(pos) != Some(&b'{') {
        return copy_value(b, pos, out);
    }
    out.push(b'{');
    let mut i = skip_ws(b, pos + 1);
    if b.get(i) == Some(&b'}') {
        out.push(b'}');
        return Some(i + 1);
    }
    loop {
        let ke = skip_string(b, i)?;
        out.extend_from_slice(&b[i..ke]);
        let c = skip_ws(b, ke);
        if b.get(c) != Some(&b':') {
            return None;
        }
        out.push(b':');
        i = skip_ws(b, handler(&b[i + 1..ke - 1], skip_ws(b, c + 1), out)?);
        match b.get(i) {
            Some(b',') => {
                out.push(b',');
                i = skip_ws(b, i + 1);
            }
            Some(b'}') => {
                out.push(b'}');
                return Some(i + 1);
            }
            _ => return None,
        }
    }
}

pub fn walk_elements<H>(b: &[u8], pos: usize, out: &mut Vec<u8>, mut handler: H) -> Option<usize>
where
    H: FnMut(usize, usize, &mut Vec<u8>) -> Option<usize>,
{
    if b.get(pos) != Some(&b'[') {
        return copy_value(b, pos, out);
    }
    out.push(b'[');
    let mut i = skip_ws(b, pos + 1);
    if b.get(i) == Some(&b']') {
        out.push(b']');
        return Some(i + 1);
    }
    let mut idx = 0;
    loop {
        i = skip_ws(b, handler(idx, i, out)?);
        idx += 1;
        match b.get(i) {
            Some(b',') => {
                out.push(b',');
                i = skip_ws(b, i + 1);
            }
            Some(b']') => {
                out.push(b']');
                return Some(i + 1);
            }
            _ => return None,
        }
    }
}

/// Emit `s` as a JSON string literal (`"..."`, escaped).
pub fn emit_str(s: &str, out: &mut Vec<u8>) {
    out.push(b'"');
    json_escape_into(s, out);
    out.push(b'"');
}

fn json_escape_into(s: &str, out: &mut Vec<u8>) {
    for &c in s.as_bytes() {
        match c {
            b'"' => out.extend_from_slice(b"\\\""),
            b'\\' => out.extend_from_slice(b"\\\\"),
            0x08 => out.extend_from_slice(b"\\b"),
            0x0c => out.extend_from_slice(b"\\f"),
            b'\n' => out.extend_from_slice(b"\\n"),
            b'\r' => out.extend_from_slice(b"\\r"),
            b'\t' => out.extend_from_slice(b"\\t"),
            0x00..=0x1f => {
                let _ = write!(out, "\\u{c:04x}");
            }
            _ => out.push(c),
        }
    }
}

fn unescape(b: &[u8]) -> Option<String> {
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] != b'\\' {
            out.push(b[i]);
            i += 1;
            continue;
        }
        i += 1;
        match *b.get(i)? {
            b'"' => out.push(b'"'),
            b'\\' => out.push(b'\\'),
            b'/' => out.push(b'/'),
            b'b' => out.push(0x08),
            b'f' => out.push(0x0c),
            b'n' => out.push(b'\n'),
            b'r' => out.push(b'\r'),
            b't' => out.push(b'\t'),
            b'u' => {
                let hi = hex4(b, i + 1)?;
                i += 4;
                let ch = if (0xD800..=0xDBFF).contains(&hi) {
                    if b.get(i + 1) == Some(&b'\\') && b.get(i + 2) == Some(&b'u') {
                        let lo = hex4(b, i + 3)?;
                        i += 6;
                        let c = 0x10000 + (((hi - 0xD800) as u32) << 10) + (lo - 0xDC00) as u32;
                        char::from_u32(c)?
                    } else {
                        return None;
                    }
                } else {
                    char::from_u32(hi as u32)?
                };
                let mut buf = [0u8; 4];
                out.extend_from_slice(ch.encode_utf8(&mut buf).as_bytes());
            }
            _ => return None,
        }
        i += 1;
    }
    String::from_utf8(out).ok()
}

fn hex4(b: &[u8], i: usize) -> Option<u16> {
    let mut v: u16 = 0;
    for k in 0..4 {
        v = v << 4 | (b.get(i + k)?.to_ascii_lowercase() as char).to_digit(16)? as u16;
    }
    Some(v)
}
