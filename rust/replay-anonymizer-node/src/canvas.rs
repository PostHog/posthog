//! Scrubs rrweb CanvasMutation events: redacts text drawn via fill/strokeText and blurs drawn images
//! and canvas snapshots. Mirrors `anonymize/canvas.ts`, with the deferred sharp jobs replaced by inline
//! native blur (so the object lands on its final blurred/blanked value directly).

use base64::Engine;
use simd_json::borrowed::{Object, Value};

use crate::blur::{blank_image_data_uri, is_image_data_uri, split_data_uri, BLANK_PNG_BASE64};
use crate::context::Ctx;
use crate::json::{
    as_array, as_array_mut, as_object, as_object_mut, as_str, as_u32, as_usize, key, string_value,
};
use crate::url::scrub_url;

fn b64() -> base64::engine::general_purpose::GeneralPurpose {
    base64::engine::general_purpose::STANDARD
}

/// Scrub a CanvasMutation `data` object in place. Returns whether anything changed.
pub fn scrub_canvas_mutation(ctx: &Ctx<'_>, data: &mut Value<'_>) -> bool {
    let Some(obj) = as_object_mut(data) else {
        return false;
    };
    let has_commands = matches!(obj.get("commands"), Some(Value::Array(_)));
    if has_commands {
        let mut changed = false;
        let commands = obj.get_mut("commands").and_then(as_array_mut).unwrap();
        for cmd in commands.iter_mut() {
            if let Some(c) = as_object_mut(cmd) {
                changed |= scrub_command(ctx, c);
            }
        }
        changed
    } else if obj.get("property").and_then(as_str).is_some() {
        // Flattened single-command form: `data` itself is the command.
        scrub_command(ctx, obj)
    } else {
        false
    }
}

// Canvas API calls whose leading string arguments are user-visible text.
fn is_text_command(property: &str) -> bool {
    matches!(property, "fillText" | "strokeText")
}

fn scrub_command(ctx: &Ctx<'_>, cmd: &mut Object<'_>) -> bool {
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
            if let Value::String(s) = a {
                if let Some(nv) = crate::text::scrub_text(ctx.allow, s) {
                    *a = string_value(nv);
                    changed = true;
                }
            }
        }
    }

    // Images/snapshots can appear anywhere in the (recursive) arg tree.
    for a in args.iter_mut() {
        changed |= blur_canvas_arg(ctx, a);
    }
    changed
}

/// Recursively neutralize+blur image data inside a canvas arg, mutating in place.
fn blur_canvas_arg(ctx: &Ctx<'_>, value: &mut Value<'_>) -> bool {
    match value {
        Value::String(s) => {
            if is_image_data_uri(s) {
                let b = ctx.blur_data_uri(s).unwrap_or_else(blank_image_data_uri);
                *value = string_value(b);
                return true;
            }
            return false;
        }
        Value::Array(arr) => {
            let mut changed = false;
            for item in arr.iter_mut() {
                changed |= blur_canvas_arg(ctx, item);
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
            let b = ctx.blur_data_uri(&src).unwrap_or_else(blank_image_data_uri);
            obj.insert(key("src"), string_value(b));
            return true;
        }
        return match scrub_url(ctx.allow, &src) {
            Some(v) => {
                obj.insert(key("src"), string_value(v));
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
                return blur_blob_image(ctx, obj);
            }
        }
    }

    // Raw pixels: { rr_type: 'ImageData', args: [pixels, width, height] } (putImageData).
    if rr_type.as_deref() == Some("ImageData") {
        return blur_image_data(ctx, obj);
    }

    // Otherwise recurse into nested arg/data arrays (ImageBitmap -> Blob, etc.).
    let mut changed = false;
    if let Some(args) = obj.get_mut("args").and_then(as_array_mut) {
        for it in args.iter_mut() {
            changed |= blur_canvas_arg(ctx, it);
        }
    }
    if let Some(data) = obj.get_mut("data").and_then(as_array_mut) {
        for it in data.iter_mut() {
            changed |= blur_canvas_arg(ctx, it);
        }
    }
    changed
}

/// Blur the encoded image bytes inside an image Blob, neutralizing them first (fail-safe).
fn blur_blob_image(ctx: &Ctx<'_>, blob: &mut Object<'_>) -> bool {
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
    let (new_b64, new_type) = match ctx
        .blur_data_uri(&original)
        .and_then(|b| split_data_uri(&b))
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
        ab.insert(key("base64"), string_value(new_b64));
    }
    blob.insert(key("type"), string_value(new_type));
    true
}

fn find_array_buffer_index(blob: &Object<'_>) -> Option<usize> {
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
fn blur_image_data<'v>(ctx: &Ctx<'_>, image_data: &mut Object<'v>) -> bool {
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
        if w > 0 && h > 0 && pixelate_image_data_arg(ctx, image_data, w, h) {
            return true;
        }
    }
    // Unexpected shape — guarantee no raw-pixel leak by blanking every nested ArrayBuffer.
    let mut v: Value<'v> = Value::Object(Box::new(std::mem::take(image_data)));
    let changed = blank_array_buffers(&mut v);
    if let Value::Object(o) = v {
        *image_data = *o;
    }
    changed
}

/// Locate the RGBA ArrayBuffer behind an ImageData's pixel descriptor (direct or typed-array-wrapped),
/// blank it and merge the pixelated region back. Returns whether it handled the pixels.
fn pixelate_image_data_arg(ctx: &Ctx<'_>, image_data: &mut Object<'_>, w: u32, h: u32) -> bool {
    // `checked_mul`: `w*h*4` on attacker-controlled dims can overflow usize; overflow -> no match.
    let Some(expected) = (w as usize)
        .checked_mul(h as usize)
        .and_then(|wh| wh.checked_mul(4))
    else {
        return false;
    };

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
            return process_raw_buffer(ctx, ab, 0, None, w, h, expected);
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
            return process_raw_buffer(ctx, ab, start, length_opt, w, h, expected);
        }
    }
    false
}

fn process_raw_buffer(
    ctx: &Ctx<'_>,
    ab: &mut Object<'_>,
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
    // `start`/`length` come from untrusted JSON numbers; guard against overflow (release builds don't
    // check arithmetic) so a crafted pair can't produce a reversed/out-of-range slice panic.
    let Some(end) = start.checked_add(length) else {
        return false;
    };
    if length != expected || end > full.len() {
        return false;
    }
    let rgba = b64().encode(&full[start..end]);
    let mut merged = full.clone();
    for b in &mut merged[start..end] {
        *b = 0;
    }
    if let Some(pix) = ctx.pixelate_raw(&rgba, w, h) {
        if let Ok(outbuf) = b64().decode(pix.as_bytes()) {
            if outbuf.len() == length {
                merged[start..end].copy_from_slice(&outbuf);
            }
        }
    }
    ab.insert(key("base64"), string_value(b64().encode(&merged)));
    true
}

/// Zero out every nested `{rr_type:'ArrayBuffer', base64}` (same byte length). Last-resort fail-safe.
fn blank_array_buffers(node: &mut Value<'_>) -> bool {
    match node {
        Value::Array(arr) => {
            let mut changed = false;
            for item in arr.iter_mut() {
                changed |= blank_array_buffers(item);
            }
            changed
        }
        Value::Object(obj) => {
            if obj.get("rr_type").and_then(as_str) == Some("ArrayBuffer") {
                if let Some(base64) = obj.get("base64").and_then(as_str) {
                    let len = b64()
                        .decode(base64.as_bytes())
                        .map(|b| b.len())
                        .unwrap_or(0);
                    let zeros = b64().encode(vec![0u8; len]);
                    obj.insert(key("base64"), string_value(zeros));
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::allow_lists::AllowLists;
    use crate::context::Ctx;
    use crate::testkit::{png_base64, png_data_uri, rgba_base64};
    use base64::Engine;
    use simd_json::prelude::Writable;

    // Scrub a CanvasMutation `data` JSON string and return the result as a serde_json Value.
    fn scrub(data_json: &str) -> serde_json::Value {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        let mut bytes = data_json.as_bytes().to_vec();
        let mut data = simd_json::to_borrowed_value(&mut bytes).unwrap();
        scrub_canvas_mutation(&ctx, &mut data);
        serde_json::from_str(&data.encode()).unwrap()
    }

    fn decode(b64: &str) -> Vec<u8> {
        b64_engine().decode(b64).unwrap()
    }
    fn b64_engine() -> base64::engine::general_purpose::GeneralPurpose {
        base64::engine::general_purpose::STANDARD
    }

    #[test]
    fn image_element_data_uri_src_is_neutralized() {
        let uri = png_data_uri(8, 8, [200, 10, 10, 255]);
        let out = scrub(&format!(
            r#"{{"source":9,"id":1,"type":0,"commands":[{{"property":"drawImage","args":[{{"rr_type":"HTMLImageElement","src":"{uri}"}}]}}]}}"#
        ));
        let src = out["commands"][0]["args"][0]["src"].as_str().unwrap();
        assert!(src.starts_with("data:image/"), "still an image: {src}");
        assert_ne!(src, uri, "raw image must not pass through");
    }

    #[test]
    fn blob_image_bytes_are_neutralized() {
        let b64 = png_base64(8, 8, [10, 200, 10, 255]);
        let out = scrub(&format!(
            r#"{{"source":9,"id":1,"type":0,"commands":[{{"property":"drawImage","args":[{{"rr_type":"Blob","type":"image/png","data":[{{"rr_type":"ArrayBuffer","base64":"{b64}"}}]}}]}}]}}"#
        ));
        let new_b64 = out["commands"][0]["args"][0]["data"][0]["base64"]
            .as_str()
            .unwrap();
        assert_ne!(new_b64, b64, "raw blob bytes must not pass through");
    }

    #[test]
    fn image_data_raw_pixels_are_pixelated_preserving_length() {
        let (w, h) = (8u32, 8u32);
        let rgba = rgba_base64(w, h);
        let out = scrub(&format!(
            r#"{{"source":9,"id":1,"type":0,"commands":[{{"property":"putImageData","args":[{{"rr_type":"ImageData","args":[{{"rr_type":"ArrayBuffer","base64":"{rgba}"}},{w},{h}]}}]}}]}}"#
        ));
        let new_b64 = out["commands"][0]["args"][0]["args"][0]["base64"]
            .as_str()
            .unwrap();
        assert_ne!(new_b64, rgba, "raw pixels must not pass through");
        assert_eq!(
            decode(new_b64).len(),
            (w * h * 4) as usize,
            "byte length preserved"
        );
    }

    #[test]
    fn malformed_image_data_blanks_the_array_buffer() {
        // 4x4 buffer (64 bytes) but claims 8x8 (256 expected) → the raw-pixel path bails and the
        // fail-safe zeroes every nested ArrayBuffer rather than shipping the pixels.
        let rgba = rgba_base64(4, 4);
        let out = scrub(&format!(
            r#"{{"source":9,"id":1,"type":0,"commands":[{{"property":"putImageData","args":[{{"rr_type":"ImageData","args":[{{"rr_type":"ArrayBuffer","base64":"{rgba}"}},8,8]}}]}}]}}"#
        ));
        let new_b64 = out["commands"][0]["args"][0]["args"][0]["base64"]
            .as_str()
            .unwrap();
        let bytes = decode(new_b64);
        assert_eq!(bytes.len(), decode(&rgba).len(), "byte length preserved");
        assert!(
            bytes.iter().all(|&b| b == 0),
            "unhandled shape must be blanked"
        );
    }
}
