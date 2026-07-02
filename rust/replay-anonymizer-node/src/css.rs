//! Blur inline `url(data:image/...;base64,...)` backgrounds in CSS. Mirrors `anonymize/css.ts`, but the
//! regex `URL_DATA_IMAGE_RE` is replaced with a single linear left-to-right scan (no backtracking).
//! `None` means "unchanged".

use simd_json::value::owned::Object;
use simd_json::OwnedValue;

use crate::blur::{blank_image_data_uri, is_image_data_uri};
use crate::context::Ctx;
use crate::json::as_str;

/// Scrub `container[key]` if it is a CSS string; returns whether it changed.
pub fn scrub_css_images(ctx: &Ctx<'_>, container: &mut Object, key: &str) -> bool {
    let Some(css) = container.get(key).and_then(as_str).map(str::to_string) else {
        return false;
    };
    match rewrite(ctx, &css) {
        Some(v) => {
            container.insert(key.to_string(), OwnedValue::String(v));
            true
        }
        None => false,
    }
}

fn rewrite(ctx: &Ctx<'_>, css: &str) -> Option<String> {
    let bytes = css.as_bytes();
    let mut out = String::new();
    let mut last = 0usize;
    let mut i = 0usize;
    let mut changed = false;
    while let Some(start) = find_url_open(bytes, i) {
        if let Some(m) = parse_url_data_image(bytes, start) {
            out.push_str(&css[last..start]);
            // Blur (or fall back to a blank pixel) and re-wrap; no async placeholder needed since we
            // resolve the image inline, so the final string matches the TS post-blur state.
            let replacement = ctx
                .blur_data_uri(&css[m.data_start..m.data_end])
                .unwrap_or_else(blank_image_data_uri);
            out.push_str("url(");
            if let Some(q) = m.quote {
                out.push(q as char);
            }
            out.push_str(&replacement);
            if let Some(q) = m.quote {
                out.push(q as char);
            }
            out.push(')');
            last = m.end;
            i = m.end;
            changed = true;
        } else {
            i = start + 1;
        }
    }
    if !changed {
        return None;
    }
    out.push_str(&css[last..]);
    Some(out)
}

struct Match {
    end: usize,
    quote: Option<u8>,
    data_start: usize,
    data_end: usize,
}

fn find_url_open(bytes: &[u8], from: usize) -> Option<usize> {
    let mut i = from;
    while i + 4 <= bytes.len() {
        if bytes[i].eq_ignore_ascii_case(&b'u')
            && bytes[i + 1].eq_ignore_ascii_case(&b'r')
            && bytes[i + 2].eq_ignore_ascii_case(&b'l')
            && bytes[i + 3] == b'('
        {
            return Some(i);
        }
        i += 1;
    }
    None
}

fn parse_url_data_image(bytes: &[u8], start: usize) -> Option<Match> {
    let mut pos = start + 4; // past "url("
    skip_ws(bytes, &mut pos);
    let quote = match bytes.get(pos) {
        Some(&c) if c == b'\'' || c == b'"' => {
            pos += 1;
            Some(c)
        }
        _ => None,
    };
    let data_start = pos;
    if !starts_with_ci(bytes, pos, b"data:image/") {
        return None;
    }
    pos += b"data:image/".len();
    // subtype: [a-z0-9.+-]+ (case-insensitive)
    let subtype_start = pos;
    while matches!(bytes.get(pos), Some(&c) if c.is_ascii_alphanumeric() || matches!(c, b'.' | b'+' | b'-'))
    {
        pos += 1;
    }
    if pos == subtype_start {
        return None;
    }
    if !starts_with_ci(bytes, pos, b";base64,") {
        return None;
    }
    pos += b";base64,".len();
    // base64 body: [A-Za-z0-9+/=]+
    let b64_start = pos;
    while matches!(bytes.get(pos), Some(&c) if c.is_ascii_alphanumeric() || matches!(c, b'+' | b'/' | b'='))
    {
        pos += 1;
    }
    if pos == b64_start {
        return None;
    }
    let data_end = pos;
    if let Some(q) = quote {
        if bytes.get(pos) != Some(&q) {
            return None;
        }
        pos += 1;
    }
    skip_ws(bytes, &mut pos);
    if bytes.get(pos) != Some(&b')') {
        return None;
    }
    pos += 1;
    // Only images (data URIs); guaranteed by the `data:image/` prefix above.
    debug_assert!(is_image_data_uri(
        std::str::from_utf8(&bytes[data_start..data_end]).unwrap_or("")
    ));
    Some(Match {
        end: pos,
        quote,
        data_start,
        data_end,
    })
}

fn skip_ws(bytes: &[u8], pos: &mut usize) {
    while matches!(bytes.get(*pos), Some(&c) if c.is_ascii_whitespace() || c == 0x0b) {
        *pos += 1;
    }
}

fn starts_with_ci(bytes: &[u8], pos: usize, needle: &[u8]) -> bool {
    bytes
        .get(pos..pos + needle.len())
        .is_some_and(|s| s.eq_ignore_ascii_case(needle))
}
