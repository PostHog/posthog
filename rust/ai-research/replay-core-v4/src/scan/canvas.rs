//! Canvas frames. posthog-js records a canvas as one frame shape only: clear the canvas, then draw one encoded image
//! of it. The frame's image moves out of the block like an inline image. Every other canvas command stays as it is.

use crate::bytescan::{self as scan, Span};

const CANVAS_MUTATION: u8 = 9;
const CONTEXT_2D: f64 = 0.0;
const FRAME_MIMES: &[&str] = &["image/webp", "image/png", "image/jpeg"];

/// The values of `keys` in the object at `span`. `None` when it is not an object, or a key is escaped or repeated.
fn members<const N: usize>(
    bytes: &[u8],
    span: Span,
    keys: [&[u8]; N],
) -> Option<[Option<Span>; N]> {
    let mut found = [None; N];
    for entry in scan::object_entries(bytes, span).ok()? {
        let entry = entry.ok()?;
        if entry.key_escaped {
            return None;
        }
        let key = &bytes[entry.key.0..entry.key.1];
        if let Some(index) = keys.iter().position(|&k| k == key) {
            if found[index].replace(entry.value).is_some() {
                return None;
            }
        }
    }
    Some(found)
}

/// The items of the array at `span`, when it has at most `max`.
fn items(bytes: &[u8], span: Span, max: usize) -> Option<Vec<Span>> {
    let mut items = Vec::new();
    for item in scan::array_items(bytes, span).ok()? {
        if items.len() == max {
            return None;
        }
        items.push(item.ok()?);
    }
    Some(items)
}

fn is_text(bytes: &[u8], span: Option<Span>, text: &str) -> bool {
    span.filter(|&s| scan::is_string(bytes, s))
        .is_some_and(|s| scan::unescape(bytes, s).is_ok_and(|v| v == text))
}

fn is_number(bytes: &[u8], span: Span) -> bool {
    scan::parse_number(bytes, span).is_some_and(f64::is_finite)
}

fn is_u32(bytes: &[u8], span: Option<Span>) -> bool {
    span.and_then(|s| scan::parse_number(bytes, s))
        .is_some_and(|n| n.fract() == 0.0 && (0.0..=f64::from(u32::MAX)).contains(&n))
}

fn command(bytes: &[u8], span: Span, property: &str, max_args: usize) -> Option<Vec<Span>> {
    let [name, args] = members(bytes, span, [b"property", b"args"])?;
    is_text(bytes, name, property).then_some(())?;
    items(bytes, args?, max_args)
}

/// The base64 string of a posthog-js snapshot frame and its mime type, matched as v3 `canvas.rs` matches it:
/// `{id, type: 2D, commands: [clearRect(4 numbers), drawImage(ImageBitmap(Blob(ArrayBuffer)), 2 or 4 numbers)]}`.
pub fn frame_image(
    bytes: &[u8],
    kind: Option<u8>,
    source: Option<u8>,
    data: Span,
) -> Option<(&'static str, Span)> {
    if kind != Some(3) || source != Some(CANVAS_MUTATION) {
        return None;
    }
    let [id, context, commands, width, height] = members(
        bytes,
        data,
        [
            b"id",
            b"type",
            b"commands",
            b"displayWidth",
            b"displayHeight",
        ],
    )?;
    if !is_u32(bytes, id)
        || context.and_then(|c| scan::parse_number(bytes, c)) != Some(CONTEXT_2D)
        || [width, height]
            .into_iter()
            .flatten()
            .any(|v| !is_number(bytes, v))
    {
        return None;
    }
    let [clear, draw] = items(bytes, commands?, 2)?[..] else {
        return None;
    };
    let clear = command(bytes, clear, "clearRect", 4)?;
    if clear.len() != 4 || !clear.iter().all(|&a| is_number(bytes, a)) {
        return None;
    }
    // posthog-js before 1.391 drew at the origin without a size, so `[bitmap, x, y]`.
    let draw = command(bytes, draw, "drawImage", 5)?;
    if !matches!(draw.len(), 3 | 5) || !draw[1..].iter().all(|&a| is_number(bytes, a)) {
        return None;
    }
    let [bitmap_type, bitmap_args] = members(bytes, draw[0], [b"rr_type", b"args"])?;
    let [blob] = items(bytes, bitmap_args?, 1)?[..] else {
        return None;
    };
    if !is_text(bytes, bitmap_type, "ImageBitmap") {
        return None;
    }
    let [blob_type, mime, blob_data] = members(bytes, blob, [b"rr_type", b"type", b"data"])?;
    let mime = FRAME_MIMES.iter().find(|&&m| is_text(bytes, mime, m))?;
    let [buffer] = items(bytes, blob_data?, 1)?[..] else {
        return None;
    };
    if !is_text(bytes, blob_type, "Blob") {
        return None;
    }
    let [buffer_type, base64] = members(bytes, buffer, [b"rr_type", b"base64"])?;
    let base64 = base64.filter(|&b| scan::is_string(bytes, b))?;
    is_text(bytes, buffer_type, "ArrayBuffer").then_some((mime, base64))
}
