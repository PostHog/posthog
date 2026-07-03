// Bench-only verbatim copy of MLHog prep/labeling/src/v2/canvas.rs (paths adapted to crate::mlhog).
//! Byte-scan CanvasMutation events (no simd-json). Mirrors `scrub::canvas`: redact fill/strokeText,
//! blur drawn images. Data is `commands: [...]` or a flattened `property`/`args`; image-bearing arg
//! shapes: `"data:image/…"`, `{rr_type, src}`, `{rr_type:'Blob', type, data:[ab]}`,
//! `{rr_type:'ImageData', args:[pixels, w, h]}`, `{rr_type:'ArrayBuffer', base64}`.

use std::cell::Cell;

use base64::Engine;
use base64::engine::general_purpose::STANDARD;

use super::scan;
use crate::mlhog::context::Ctx;
use crate::mlhog::scrub::{blur, text, url};

pub fn transform(ctx: &Ctx<'_>, b: &[u8], ds: usize, out: &mut Vec<u8>) -> Option<bool> {
    let changed = Cell::new(false);
    let prop = scan::member_string(b, ds, b"property");
    scan::walk_members(b, ds, out, |key, vp, o| match key {
        b"commands" => scan::walk_elements(b, vp, o, |_, ep, o| command(ctx, b, ep, o, &changed)),
        b"args" => args(ctx, b, vp, o, prop.as_deref(), &changed),
        _ => scan::copy_value(b, vp, o),
    })?;
    Some(changed.get())
}

fn command(ctx: &Ctx<'_>, b: &[u8], pos: usize, out: &mut Vec<u8>, changed: &Cell<bool>) -> Option<usize> {
    let prop = scan::member_string(b, pos, b"property");
    scan::walk_members(b, pos, out, |key, vp, o| match key {
        b"args" => args(ctx, b, vp, o, prop.as_deref(), changed),
        _ => scan::copy_value(b, vp, o),
    })
}

fn args(
    ctx: &Ctx<'_>,
    b: &[u8],
    pos: usize,
    out: &mut Vec<u8>,
    property: Option<&str>,
    changed: &Cell<bool>,
) -> Option<usize> {
    let is_text = matches!(property, Some("fillText") | Some("strokeText"));
    scan::walk_elements(b, pos, out, |_, ep, o| {
        if is_text && b.get(ep) == Some(&b'"') {
            scrub(b, ep, o, changed, |s, buf| text::scrub_into(ctx, s, buf))
        } else {
            blur_arg(ctx, b, ep, o, changed)
        }
    })
}

fn blur_arg(ctx: &Ctx<'_>, b: &[u8], pos: usize, out: &mut Vec<u8>, changed: &Cell<bool>) -> Option<usize> {
    match b.get(pos) {
        Some(b'"') => scrub(b, pos, out, changed, image_data_uri_into),
        Some(b'[') => scan::walk_elements(b, pos, out, |_, ep, o| blur_arg(ctx, b, ep, o, changed)),
        Some(b'{') => blur_object(ctx, b, pos, out, changed),
        _ => scan::copy_value(b, pos, out),
    }
}

fn blur_object(ctx: &Ctx<'_>, b: &[u8], pos: usize, out: &mut Vec<u8>, changed: &Cell<bool>) -> Option<usize> {
    // (let-chain flattened: this crate is edition 2021)
    let src_is_string = matches!(scan::find_member(b, pos, b"src"), Some(src_vp) if b.get(src_vp) == Some(&b'"'));
    if src_is_string {
        return scan::walk_members(b, pos, out, |key, vp, o| {
            if key == b"src" {
                scrub(b, vp, o, changed, |s, buf| {
                    if blur::is_image_data_uri(s) {
                        image_data_uri_into(s, buf)
                    } else {
                        url::scrub_into(ctx, s, buf)
                    }
                })
            } else {
                scan::copy_value(b, vp, o)
            }
        });
    }

    let rr = scan::member_string(b, pos, b"rr_type");
    if rr.as_deref() == Some("Blob")
        && scan::member_string(b, pos, b"type").is_some_and(|t| t.starts_with("image/"))
    {
        return blur_blob(b, pos, out, changed);
    }
    if rr.as_deref() == Some("ImageData") {
        return blur_image_data(b, pos, out, changed);
    }

    scan::walk_members(b, pos, out, |key, vp, o| match key {
        b"args" | b"data" => scan::walk_elements(b, vp, o, |_, ep, o| blur_arg(ctx, b, ep, o, changed)),
        _ => scan::copy_value(b, vp, o),
    })
}

fn blur_blob(b: &[u8], pos: usize, out: &mut Vec<u8>, changed: &Cell<bool>) -> Option<usize> {
    let mime = scan::member_string(b, pos, b"type").unwrap_or_else(|| "image/png".to_string());
    let Some(data_vp) = scan::find_member(b, pos, b"data") else {
        return scan::copy_value(b, pos, out);
    };
    let Some(orig) = first_ab_base64(b, data_vp) else {
        return scan::copy_value(b, pos, out);
    };
    changed.set(true);
    let (new_b64, new_type) =
        match blur::blur_image_data_uri(&format!("data:{mime};base64,{orig}")).and_then(|u| split_data_uri(&u)) {
            Some((m, b64)) => (b64, m),
            None => (blur::BLANK_PNG_BASE64.to_string(), "image/png".to_string()),
        };
    let done = Cell::new(false);
    scan::walk_members(b, pos, out, |key, vp, o| match key {
        b"type" => scan::replace_string(b, vp, o, &new_type),
        b"data" => scan::walk_elements(b, vp, o, |_, ep, o| {
            if !done.get() && is_arraybuffer(b, ep) {
                done.set(true);
                set_base64(b, ep, o, &new_b64)
            } else {
                scan::copy_value(b, ep, o)
            }
        }),
        _ => scan::copy_value(b, vp, o),
    })
}

fn blur_image_data(b: &[u8], pos: usize, out: &mut Vec<u8>, changed: &Cell<bool>) -> Option<usize> {
    changed.set(true);
    let new_b64 = pixelated_buffer_base64(b, pos);
    match new_b64 {
        Some((ab_pos, b64)) => scan::walk_members(b, pos, out, |key, vp, o| {
            if key == b"args" {
                scan::walk_elements(b, vp, o, |_, ep, o| {
                    if ep == ab_pos {
                        set_base64(b, ep, o, &b64)
                    } else if inner_arraybuffer_pos(b, ep) == Some(ab_pos) {
                        // typed-array wrapper holding the target ArrayBuffer
                        scan::walk_members(b, ep, o, |k, vp, o| {
                            if k == b"args" {
                                scan::walk_elements(b, vp, o, |_, ip, o| {
                                    if ip == ab_pos { set_base64(b, ip, o, &b64) } else { scan::copy_value(b, ip, o) }
                                })
                            } else {
                                scan::copy_value(b, vp, o)
                            }
                        })
                    } else {
                        scan::copy_value(b, ep, o)
                    }
                })
            } else {
                scan::copy_value(b, vp, o)
            }
        }),
        // Unknown shape / mismatch: blank every nested ArrayBuffer (fail-safe).
        None => blank_array_buffers(b, pos, out),
    }
}

// Locate the target ArrayBuffer for an ImageData and compute its pixelated (or blanked) base64.
fn pixelated_buffer_base64(b: &[u8], obj_pos: usize) -> Option<(usize, String)> {
    let args_vp = scan::find_member(b, obj_pos, b"args")?;
    let w = scan::array_elem(b, args_vp, 1).and_then(|p| scan::uint_at(b, p))?;
    let h = scan::array_elem(b, args_vp, 2).and_then(|p| scan::uint_at(b, p))?;
    if w == 0 || h == 0 {
        return None;
    }
    let desc = scan::array_elem(b, args_vp, 0)?;
    let (ab_pos, start, length) = if is_arraybuffer(b, desc) {
        (desc, 0usize, None)
    } else {
        let inner = scan::find_member(b, desc, b"args")?;
        let ab = scan::array_elem(b, inner, 0)?;
        if !is_arraybuffer(b, ab) {
            return None;
        }
        let start = scan::array_elem(b, inner, 1).and_then(|p| scan::uint_at(b, p)).unwrap_or(0) as usize;
        let length = scan::array_elem(b, inner, 2).and_then(|p| scan::uint_at(b, p)).map(|n| n as usize);
        (ab, start, length)
    };
    let b64 = scan::member_string(b, ab_pos, b"base64")?;
    let full = STANDARD.decode(b64.as_bytes()).ok()?;
    let length = length.unwrap_or_else(|| full.len().saturating_sub(start));
    if length != (w as usize) * (h as usize) * 4 || start > full.len() || start + length > full.len() {
        return None;
    }
    let rgba = STANDARD.encode(&full[start..start + length]);
    let mut blanked = full.clone();
    blanked[start..start + length].fill(0);
    // (let-chain flattened: this crate is edition 2021)
    if let Some(px) = blur::pixelate_raw_rgba(&rgba, w, h) {
        if let Ok(px) = STANDARD.decode(px.as_bytes()) {
            if px.len() == length {
                blanked[start..start + length].copy_from_slice(&px);
            }
        }
    }
    Some((ab_pos, STANDARD.encode(&blanked)))
}

// Emit a JSON value, zeroing the base64 of every nested `{rr_type:'ArrayBuffer', base64}`.
fn blank_array_buffers(b: &[u8], pos: usize, out: &mut Vec<u8>) -> Option<usize> {
    match b.get(pos) {
        Some(b'[') => scan::walk_elements(b, pos, out, |_, ep, o| blank_array_buffers(b, ep, o)),
        Some(b'{') => {
            if is_arraybuffer(b, pos) {
                let n = scan::member_string(b, pos, b"base64")
                    .and_then(|s| STANDARD.decode(s.as_bytes()).ok())
                    .map(|d| d.len())
                    .unwrap_or(0);
                let zeros = STANDARD.encode(vec![0u8; n]);
                scan::walk_members(b, pos, out, |k, vp, o| {
                    if k == b"base64" { scan::replace_string(b, vp, o, &zeros) } else { scan::copy_value(b, vp, o) }
                })
            } else {
                scan::walk_members(b, pos, out, |_, vp, o| blank_array_buffers(b, vp, o))
            }
        }
        _ => scan::copy_value(b, pos, out),
    }
}

fn image_data_uri_into(s: &str, buf: &mut String) -> bool {
    if blur::is_image_data_uri(s) {
        buf.push_str(&blur::blur_image_data_uri(s).unwrap_or_else(blur::blank_image_data_uri));
        true
    } else {
        false
    }
}

fn is_arraybuffer(b: &[u8], pos: usize) -> bool {
    scan::member_string(b, pos, b"rr_type").as_deref() == Some("ArrayBuffer")
        && scan::find_member(b, pos, b"base64").is_some()
}

fn inner_arraybuffer_pos(b: &[u8], desc_pos: usize) -> Option<usize> {
    let inner = scan::find_member(b, desc_pos, b"args")?;
    let ab = scan::array_elem(b, inner, 0)?;
    is_arraybuffer(b, ab).then_some(ab)
}

fn first_ab_base64(b: &[u8], arr_pos: usize) -> Option<String> {
    if b.get(arr_pos) != Some(&b'[') {
        return None;
    }
    let mut i = scan::skip_ws(b, arr_pos + 1);
    if b.get(i) == Some(&b']') {
        return None;
    }
    loop {
        if is_arraybuffer(b, i) {
            return scan::member_string(b, i, b"base64");
        }
        i = scan::skip_ws(b, scan::value_end(b, i)?);
        match b.get(i) {
            Some(b',') => i = scan::skip_ws(b, i + 1),
            _ => return None,
        }
    }
}

fn set_base64(b: &[u8], obj_pos: usize, out: &mut Vec<u8>, new_b64: &str) -> Option<usize> {
    scan::walk_members(b, obj_pos, out, |k, vp, o| {
        if k == b"base64" { scan::replace_string(b, vp, o, new_b64) } else { scan::copy_value(b, vp, o) }
    })
}

fn split_data_uri(uri: &str) -> Option<(String, String)> {
    let rest = uri.strip_prefix("data:")?;
    let comma = uri.find(',')?;
    let mime = rest.split(';').next().filter(|m| !m.is_empty()).unwrap_or("image/png");
    Some((mime.to_string(), uri[comma + 1..].to_string()))
}

fn scrub<F: FnOnce(&str, &mut String) -> bool>(
    b: &[u8],
    pos: usize,
    out: &mut Vec<u8>,
    changed: &Cell<bool>,
    f: F,
) -> Option<usize> {
    let (e, c) = scan::scrub_string(b, pos, out, f)?;
    changed.set(changed.get() | c);
    Some(e)
}
