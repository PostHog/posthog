// Copied from MLHog prep/labeling/src/scrub/css.rs — bench-only. Adapted: the let-chain in
// `scrub_css_images` is rewritten as a nested `if let` (this crate is edition 2021).

//! Blur inline `url(data:image/...)` CSS backgrounds.

use super::blur;

pub fn scrub_css_images(css: &str) -> Option<String> {
    let b = css.as_bytes();
    let mut out = String::new();
    let mut last = 0;
    let mut i = 0;
    let mut changed = false;
    while i < b.len() {
        if starts_with_ci(b, i, b"url(") {
            if let Some(m) = match_url_data_image(b, i) {
                out.push_str(&css[last..i]);
                let blurred = blur::blur_image_data_uri(&css[m.data_start..m.data_end])
                    .unwrap_or_else(blur::blank_image_data_uri);
                out.push_str("url(");
                if let Some(q) = m.quote {
                    out.push(q as char);
                }
                out.push_str(&blurred);
                if let Some(q) = m.quote {
                    out.push(q as char);
                }
                out.push(')');
                changed = true;
                i = m.end;
                last = m.end;
                continue;
            }
        }
        i += 1;
    }
    if !changed {
        return None;
    }
    out.push_str(&css[last..]);
    Some(out)
}

struct UrlMatch {
    end: usize,
    data_start: usize,
    data_end: usize,
    quote: Option<u8>,
}

// Hand-rolled match of `url\(\s*(['"]?)(data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=]+)\1\s*\)`.
fn match_url_data_image(b: &[u8], start: usize) -> Option<UrlMatch> {
    let mut j = start + 4;
    j = skip_ws(b, j);
    let quote = match b.get(j) {
        Some(&c) if c == b'\'' || c == b'"' => {
            j += 1;
            Some(c)
        }
        _ => None,
    };
    if !starts_with_ci(b, j, b"data:image/") {
        return None;
    }
    let data_start = j;
    j += b"data:image/".len();
    let subtype_start = j;
    while j < b.len() && is_subtype_char(b[j]) {
        j += 1;
    }
    if j == subtype_start || !starts_with_ci(b, j, b";base64,") {
        return None;
    }
    j += b";base64,".len();
    let payload_start = j;
    while j < b.len() && is_base64_char(b[j]) {
        j += 1;
    }
    if j == payload_start {
        return None;
    }
    let data_end = j;
    if let Some(q) = quote {
        if b.get(j) != Some(&q) {
            return None;
        }
        j += 1;
    }
    j = skip_ws(b, j);
    if b.get(j) != Some(&b')') {
        return None;
    }
    Some(UrlMatch {
        end: j + 1,
        data_start,
        data_end,
        quote,
    })
}

fn skip_ws(b: &[u8], mut i: usize) -> usize {
    while i < b.len() && b[i].is_ascii_whitespace() {
        i += 1;
    }
    i
}

fn starts_with_ci(b: &[u8], i: usize, needle: &[u8]) -> bool {
    b.len() >= i + needle.len() && b[i..i + needle.len()].eq_ignore_ascii_case(needle)
}

fn is_subtype_char(b: u8) -> bool {
    b.is_ascii_alphanumeric() || matches!(b, b'.' | b'+' | b'-')
}

fn is_base64_char(b: u8) -> bool {
    b.is_ascii_alphanumeric() || matches!(b, b'+' | b'/' | b'=')
}
