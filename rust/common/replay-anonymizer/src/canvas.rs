//! Scrubs rrweb CanvasMutation events: redacts text drawn via fill/strokeText and blurs drawn images
//! and canvas snapshots. Mirrors `anonymize/canvas.ts`, with the deferred sharp jobs replaced by inline
//! native blur (so the object lands on its final blurred/blanked value directly).

use base64::Engine;
use simd_json::value::owned::Object;
use simd_json::OwnedValue;

use crate::allow_lists::AllowLists;
use crate::blur::{
    blank_image_data_uri, blur_image_data_uri, is_image_data_uri, pixelate_raw_rgba,
    split_data_uri, BLANK_PNG_BASE64,
};
use crate::json::{as_array, as_array_mut, as_object, as_object_mut, as_str, as_u32, as_usize};
use crate::url::scrub_url;

fn b64() -> base64::engine::general_purpose::GeneralPurpose {
    base64::engine::general_purpose::STANDARD
}

/// Scrub a CanvasMutation `data` object in place. Returns whether anything changed.
pub fn scrub_canvas_mutation(allow: &AllowLists, data: &mut OwnedValue) -> bool {
    let Some(obj) = as_object_mut(data) else {
        return false;
    };
    let has_commands = matches!(obj.get("commands"), Some(OwnedValue::Array(_)));
    if has_commands {
        let mut changed = false;
        let commands = obj.get_mut("commands").and_then(as_array_mut).unwrap();
        for cmd in commands.iter_mut() {
            if let Some(c) = as_object_mut(cmd) {
                changed |= scrub_command(allow, c);
            }
        }
        changed
    } else if obj.get("property").and_then(as_str).is_some() {
        // Flattened single-command form: `data` itself is the command.
        scrub_command(allow, obj)
    } else {
        false
    }
}

// Canvas API calls whose leading string arguments are user-visible text.
fn is_text_command(property: &str) -> bool {
    matches!(property, "fillText" | "strokeText")
}

fn scrub_command(allow: &AllowLists, cmd: &mut Object) -> bool {
    let is_text = cmd
        .get("property")
        .and_then(as_str)
        .map(is_text_command)
        .unwrap_or(false);
    let Some(args) = cmd.get_mut("args").and_then(as_array_mut) else {
        return false;
    };
    let mut changed = false;

    // Text drawn onto the canvas: fillText/strokeText take the text as leading string args.
    if is_text {
        for a in args.iter_mut() {
            if let OwnedValue::String(s) = a {
                if let Some(nv) = crate::text::scrub_text(allow, s) {
                    *a = OwnedValue::String(nv);
                    changed = true;
                }
            }
        }
    }

    // Images/snapshots can appear anywhere in the (recursive) arg tree.
    for a in args.iter_mut() {
        changed |= blur_canvas_arg(allow, a);
    }
    changed
}

/// Recursively neutralize+blur image data inside a canvas arg, mutating in place.
fn blur_canvas_arg(allow: &AllowLists, value: &mut OwnedValue) -> bool {
    match value {
        OwnedValue::String(s) => {
            if is_image_data_uri(s) {
                let b = blur_image_data_uri(s).unwrap_or_else(blank_image_data_uri);
                *value = OwnedValue::String(b);
                return true;
            }
            return false;
        }
        OwnedValue::Array(arr) => {
            let mut changed = false;
            for item in arr.iter_mut() {
                changed |= blur_canvas_arg(allow, item);
            }
            return changed;
        }
        _ => {}
    }

    let Some(obj) = as_object_mut(value) else {
        return false;
    };

    // Serialized image element: { rr_type, src }. Data-URI src is an embedded image; a remote src is a
    // URL that may itself carry PII.
    if let Some(src) = obj.get("src").and_then(as_str).map(str::to_string) {
        if is_image_data_uri(&src) {
            let b = blur_image_data_uri(&src).unwrap_or_else(blank_image_data_uri);
            obj.insert("src".to_string(), OwnedValue::String(b));
            return true;
        }
        return match scrub_url(allow, &src) {
            Some(v) => {
                obj.insert("src".to_string(), OwnedValue::String(v));
                true
            }
            None => false,
        };
    }

    let rr_type = obj.get("rr_type").and_then(as_str).map(str::to_string);

    // Encoded image snapshot: { rr_type: 'Blob', type: 'image/...', data: [ {rr_type:'ArrayBuffer', base64} ] }.
    if rr_type.as_deref() == Some("Blob") {
        if let Some(t) = obj.get("type").and_then(as_str) {
            if t.starts_with("image/") {
                return blur_blob_image(obj);
            }
        }
    }

    // Raw pixels: { rr_type: 'ImageData', args: [pixels, width, height] } (putImageData).
    if rr_type.as_deref() == Some("ImageData") {
        return blur_image_data(obj);
    }

    // Otherwise recurse into nested arg/data arrays (ImageBitmap -> Blob, etc.).
    let mut changed = false;
    if let Some(args) = obj.get_mut("args").and_then(as_array_mut) {
        for it in args.iter_mut() {
            changed |= blur_canvas_arg(allow, it);
        }
    }
    if let Some(data) = obj.get_mut("data").and_then(as_array_mut) {
        for it in data.iter_mut() {
            changed |= blur_canvas_arg(allow, it);
        }
    }
    changed
}

/// Blur the encoded image bytes inside an image Blob, neutralizing them first (fail-safe).
fn blur_blob_image(blob: &mut Object) -> bool {
    let mime = blob
        .get("type")
        .and_then(as_str)
        .unwrap_or("image/png")
        .to_string();
    let Some(idx) = find_array_buffer_index(blob) else {
        return false;
    };
    let base64 = match blob
        .get("data")
        .and_then(as_array)
        .and_then(|d| d.get(idx))
        .and_then(as_object)
        .and_then(|o| o.get("base64"))
        .and_then(as_str)
    {
        Some(s) => s.to_string(),
        None => return false,
    };
    let original = format!("data:{mime};base64,{base64}");
    let (new_b64, new_type) = match blur_image_data_uri(&original).and_then(|b| split_data_uri(&b))
    {
        Some((m, b64)) => (b64, m),
        // Fail-safe: a blank pixel (matches the TS synchronous neutralization).
        None => (BLANK_PNG_BASE64.to_string(), "image/png".to_string()),
    };
    if let Some(ab) = blob
        .get_mut("data")
        .and_then(as_array_mut)
        .and_then(|d| d.get_mut(idx))
        .and_then(as_object_mut)
    {
        ab.insert("base64".to_string(), OwnedValue::String(new_b64));
    }
    blob.insert("type".to_string(), OwnedValue::String(new_type));
    true
}

fn find_array_buffer_index(blob: &Object) -> Option<usize> {
    blob.get("data").and_then(as_array).and_then(|data| {
        data.iter().position(|d| {
            as_object(d)
                .map(|o| {
                    o.get("rr_type").and_then(as_str) == Some("ArrayBuffer")
                        && o.get("base64").and_then(as_str).is_some()
                })
                .unwrap_or(false)
        })
    })
}

/// Pixelate raw ImageData pixels in place (blanked, with the downsampled-and-restored region merged
/// back in on success). Falls back to blanking every nested ArrayBuffer for an unexpected shape.
fn blur_image_data(image_data: &mut Object) -> bool {
    let width = image_data
        .get("args")
        .and_then(as_array)
        .and_then(|a| a.get(1))
        .and_then(as_u32);
    let height = image_data
        .get("args")
        .and_then(as_array)
        .and_then(|a| a.get(2))
        .and_then(as_u32);
    if let (Some(w), Some(h)) = (width, height) {
        if w > 0 && h > 0 && pixelate_image_data_arg(image_data, w, h) {
            return true;
        }
    }
    // Unexpected shape — guarantee no raw-pixel leak by blanking every nested ArrayBuffer.
    let mut v = OwnedValue::Object(Box::new(std::mem::take(image_data)));
    let changed = blank_array_buffers(&mut v);
    if let OwnedValue::Object(o) = v {
        *image_data = *o;
    }
    changed
}

/// Locate the RGBA ArrayBuffer behind an ImageData's pixel descriptor (direct or typed-array-wrapped),
/// blank it and merge the pixelated region back. Returns whether it handled the pixels.
fn pixelate_image_data_arg(image_data: &mut Object, w: u32, h: u32) -> bool {
    let expected = (w as usize) * (h as usize) * 4;

    // Shape A: args[0] is the ArrayBuffer directly.
    let direct = image_data
        .get("args")
        .and_then(as_array)
        .and_then(|a| a.first())
        .and_then(as_object)
        .map(|o| {
            o.get("rr_type").and_then(as_str) == Some("ArrayBuffer")
                && o.get("base64").and_then(as_str).is_some()
        })
        .unwrap_or(false);
    if direct {
        if let Some(ab) = image_data
            .get_mut("args")
            .and_then(as_array_mut)
            .and_then(|a| a.first_mut())
            .and_then(as_object_mut)
        {
            return process_raw_buffer(ab, 0, None, w, h, expected);
        }
    }

    // Shape B: typed-array wrapper { args: [ {ArrayBuffer}, byteOffset?, length? ] }.
    let (start, length_opt, wrapped) = {
        let inner = image_data
            .get("args")
            .and_then(as_array)
            .and_then(|a| a.first())
            .and_then(as_object)
            .and_then(|o| o.get("args"))
            .and_then(as_array);
        match inner {
            Some(args) => {
                let is_ab = args
                    .first()
                    .and_then(as_object)
                    .map(|o| {
                        o.get("rr_type").and_then(as_str) == Some("ArrayBuffer")
                            && o.get("base64").and_then(as_str).is_some()
                    })
                    .unwrap_or(false);
                (
                    args.get(1).and_then(as_usize).unwrap_or(0),
                    args.get(2).and_then(as_usize),
                    is_ab,
                )
            }
            None => (0, None, false),
        }
    };
    if wrapped {
        if let Some(ab) = image_data
            .get_mut("args")
            .and_then(as_array_mut)
            .and_then(|a| a.first_mut())
            .and_then(as_object_mut)
            .and_then(|o| o.get_mut("args"))
            .and_then(as_array_mut)
            .and_then(|a| a.first_mut())
            .and_then(as_object_mut)
        {
            return process_raw_buffer(ab, start, length_opt, w, h, expected);
        }
    }
    false
}

fn process_raw_buffer(
    ab: &mut Object,
    start: usize,
    length_opt: Option<usize>,
    w: u32,
    h: u32,
    expected: usize,
) -> bool {
    let Some(base64) = ab.get("base64").and_then(as_str).map(str::to_string) else {
        return false;
    };
    let Ok(full) = b64().decode(base64.as_bytes()) else {
        return false;
    };
    let length = length_opt.unwrap_or_else(|| full.len().saturating_sub(start));
    if length != expected || start + length > full.len() {
        return false;
    }
    let rgba = b64().encode(&full[start..start + length]);
    let mut merged = full.clone();
    for b in &mut merged[start..start + length] {
        *b = 0;
    }
    if let Some(pix) = pixelate_raw_rgba(&rgba, w, h) {
        if let Ok(outbuf) = b64().decode(pix.as_bytes()) {
            if outbuf.len() == length {
                merged[start..start + length].copy_from_slice(&outbuf);
            }
        }
    }
    ab.insert(
        "base64".to_string(),
        OwnedValue::String(b64().encode(&merged)),
    );
    true
}

/// Zero out every nested `{rr_type:'ArrayBuffer', base64}` (same byte length). Last-resort fail-safe.
fn blank_array_buffers(node: &mut OwnedValue) -> bool {
    match node {
        OwnedValue::Array(arr) => {
            let mut changed = false;
            for item in arr.iter_mut() {
                changed |= blank_array_buffers(item);
            }
            changed
        }
        OwnedValue::Object(obj) => {
            if obj.get("rr_type").and_then(as_str) == Some("ArrayBuffer") {
                if let Some(base64) = obj.get("base64").and_then(as_str) {
                    let len = b64()
                        .decode(base64.as_bytes())
                        .map(|b| b.len())
                        .unwrap_or(0);
                    let zeros = b64().encode(vec![0u8; len]);
                    obj.insert("base64".to_string(), OwnedValue::String(zeros));
                    return true;
                }
            }
            let mut changed = false;
            for (_, val) in obj.iter_mut() {
                changed |= blank_array_buffers(val);
            }
            changed
        }
        _ => false,
    }
}
