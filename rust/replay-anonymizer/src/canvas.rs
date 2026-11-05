//! Scrubs rrweb CanvasMutation events.
//!
//! posthog-js records a canvas in one way only: a snapshot frame that clears the canvas and draws one
//! encoded image of it. That frame is rebuilt from its known fields, and its image goes to the image
//! scrub. Any other canvas mutation (drawing commands, text, raw pixels, WebGL) cannot be scrubbed as
//! an image, so the event keeps only its identity and an empty command list.

use simd_json::borrowed::{Object, Value};

use crate::collect::{is_image_ref, is_image_ref_strict, normalize_collected_mime};
use crate::context::Ctx;
use crate::data_uri::ImageFallback;
use crate::data_uri::{split_data_uri, BLANK_PNG_BASE64};
use crate::json::{
    as_array, as_array_mut, as_f64, as_object, as_object_mut, as_str, as_u32, key, string_value,
};

const FRAME_MIMES: &[&str] = &["image/webp", "image/png", "image/jpeg"];
const CONTEXT_2D: u32 = 0;
const DATA_KEYS: &[&str] = &[
    "source",
    "id",
    "type",
    "commands",
    "displayWidth",
    "displayHeight",
];
pub(crate) const REJECTED_CANVAS_MUTATION: &str = "canvas_mutation_not_snapshot_frame";

/// Scrub a CanvasMutation `data` object in place. Returns whether anything changed.
pub fn scrub_canvas_mutation(ctx: &Ctx<'_>, data: &mut Value<'_>) -> bool {
    let Some(obj) = as_object_mut(data) else {
        return false;
    };
    if is_snapshot_frame(obj) {
        let mut changed = prune_to_frame(obj);
        if let Some(blob) = frame_blob_mut(obj) {
            changed |= scrub_frame_blob(ctx, blob);
        }
        changed
    } else {
        let changed = empty_mutation(obj);
        if changed {
            ctx.record_scrub_drop(REJECTED_CANVAS_MUTATION);
        }
        changed
    }
}

fn is_number(v: &Value<'_>) -> bool {
    as_f64(v).is_some_and(f64::is_finite)
}

fn is_property(cmd: &Object<'_>, name: &str) -> bool {
    cmd.get("property").and_then(as_str) == Some(name)
}

fn rr_type_is(obj: &Object<'_>, name: &str) -> bool {
    obj.get("rr_type").and_then(as_str) == Some(name)
}

fn numbers(args: &[Value<'_>]) -> bool {
    args.iter().all(is_number)
}

/// `{ id, type: 2D, commands: [clearRect(4 numbers), drawImage(ImageBitmap(Blob), 4 numbers)] }`,
/// with any display size given as numbers.
fn is_snapshot_frame(obj: &Object<'_>) -> bool {
    if obj.get("id").and_then(as_u32).is_none()
        || obj.get("type").and_then(as_u32) != Some(CONTEXT_2D)
    {
        return false;
    }
    if ["displayWidth", "displayHeight"]
        .iter()
        .any(|name| obj.get(*name).is_some_and(|v| !is_number(v)))
    {
        return false;
    }
    let Some([clear, draw]) = obj.get("commands").and_then(as_array).map(Vec::as_slice) else {
        return false;
    };
    let (Some(clear), Some(draw)) = (as_object(clear), as_object(draw)) else {
        return false;
    };
    let clear_ok = is_property(clear, "clearRect")
        && clear
            .get("args")
            .and_then(as_array)
            .is_some_and(|args| args.len() == 4 && numbers(args));
    let draw_ok = is_property(draw, "drawImage")
        && draw.get("args").and_then(as_array).is_some_and(|args| {
            // posthog-js before 1.391 drew at the origin without a size, so `[bitmap, x, y]`.
            matches!(args.len(), 3 | 5)
                && numbers(&args[1..])
                && as_object(&args[0]).is_some_and(is_frame_bitmap)
        });
    clear_ok && draw_ok
}

fn is_frame_bitmap(bitmap: &Object<'_>) -> bool {
    rr_type_is(bitmap, "ImageBitmap")
        && matches!(
            bitmap.get("args").and_then(as_array).map(Vec::as_slice),
            Some([blob]) if as_object(blob).is_some_and(is_frame_blob)
        )
}

fn is_frame_blob(blob: &Object<'_>) -> bool {
    rr_type_is(blob, "Blob")
        && blob
            .get("type")
            .and_then(as_str)
            .is_some_and(|mime| FRAME_MIMES.contains(&mime))
        && matches!(
            blob.get("data").and_then(as_array).map(Vec::as_slice),
            Some([buffer]) if as_object(buffer).is_some_and(|b| {
                rr_type_is(b, "ArrayBuffer") && b.get("base64").and_then(as_str).is_some()
            })
        )
}

fn prune_to_frame(obj: &mut Object<'_>) -> bool {
    let mut changed = retain_keys(obj, DATA_KEYS);
    let Some(commands) = obj.get_mut("commands").and_then(as_array_mut) else {
        return changed;
    };
    for command in commands.iter_mut() {
        let Some(command) = as_object_mut(command) else {
            continue;
        };
        changed |= retain_keys(command, &["property", "args"]);
    }
    if let Some(bitmap) = commands
        .get_mut(1)
        .and_then(as_object_mut)
        .and_then(|draw| draw.get_mut("args"))
        .and_then(as_array_mut)
        .and_then(|args| args.first_mut())
        .and_then(as_object_mut)
    {
        changed |= retain_keys(bitmap, &["rr_type", "args"]);
        if let Some(blob) = bitmap
            .get_mut("args")
            .and_then(as_array_mut)
            .and_then(|args| args.first_mut())
            .and_then(as_object_mut)
        {
            changed |= retain_keys(blob, &["rr_type", "type", "data"]);
            if let Some(buffer) = blob
                .get_mut("data")
                .and_then(as_array_mut)
                .and_then(|data| data.first_mut())
                .and_then(as_object_mut)
            {
                changed |= retain_keys(buffer, &["rr_type", "base64"]);
            }
        }
    }
    changed
}

fn retain_keys(obj: &mut Object<'_>, keep: &[&str]) -> bool {
    let before = obj.len();
    obj.retain(|name, _| keep.contains(&name.as_ref()));
    obj.len() != before
}

fn frame_blob_mut<'a, 'v>(obj: &'a mut Object<'v>) -> Option<&'a mut Object<'v>> {
    obj.get_mut("commands")
        .and_then(as_array_mut)?
        .get_mut(1)
        .and_then(as_object_mut)?
        .get_mut("args")
        .and_then(as_array_mut)?
        .first_mut()
        .and_then(as_object_mut)?
        .get_mut("args")
        .and_then(as_array_mut)?
        .first_mut()
        .and_then(as_object_mut)
}

fn empty_mutation(obj: &mut Object<'_>) -> bool {
    let already_empty = obj
        .get("commands")
        .and_then(as_array)
        .is_some_and(Vec::is_empty);
    let mut changed = !already_empty;
    changed |= retain_keys(obj, &["source", "id", "type", "commands"]);
    for name in ["id", "type"] {
        if obj.get(name).is_some_and(|v| as_u32(v).is_none()) {
            obj.remove(name);
            changed = true;
        }
    }
    obj.insert(key("commands"), Value::Array(Box::default()));
    changed
}

fn scrub_frame_blob(ctx: &Ctx<'_>, blob: &mut Object<'_>) -> bool {
    let mime = blob
        .get("type")
        .and_then(as_str)
        .unwrap_or("image/png")
        .to_string();
    let Some(base64) = blob
        .get("data")
        .and_then(as_array)
        .and_then(|data| data.first())
        .and_then(as_object)
        .and_then(|buffer| buffer.get("base64"))
        .and_then(as_str)
        .map(str::to_string)
    else {
        return false;
    };
    // A content ref left by an earlier pass. Reassembling it into `data:{mime};base64,image:...`
    // yields a URI that cannot decode, which `scrub_image` fails safe to a blank pixel — destroying
    // the join key and stranding the image. Left alone only on an explicitly trusted re-scrub, and
    // only when fully well-formed: see `assets::scrub_media_sources`.
    if ctx.keeps_image_refs() && is_image_ref_strict(&base64) {
        return false;
    }
    let scrubbed = ctx.scrub_image(
        &format!("data:{mime};base64,{base64}"),
        ImageFallback::Blank,
    );
    // The collection lane's ref replaces the payload wholesale, and the mime survives only through
    // the raster allowlist, so no client string reaches the output through this field.
    let (new_b64, new_type) = if is_image_ref(&scrubbed) {
        (scrubbed, normalize_collected_mime(&mime).to_string())
    } else {
        match split_data_uri(&scrubbed) {
            Some((m, b64)) => (b64, m),
            None => (BLANK_PNG_BASE64.to_string(), "image/png".to_string()),
        }
    };
    if let Some(buffer) = blob
        .get_mut("data")
        .and_then(as_array_mut)
        .and_then(|data| data.first_mut())
        .and_then(as_object_mut)
    {
        buffer.insert(key("base64"), string_value(new_b64));
    }
    blob.insert(key("type"), string_value(new_type));
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::allow_lists::AllowLists;
    use crate::collect::ImageCollection;
    use crate::context::Ctx;
    use crate::testkit::png_base64;
    use serde_json::json;
    use simd_json::prelude::Writable;

    fn frame(mime: &str, base64: &str) -> serde_json::Value {
        json!({ "source": 9, "id": 1, "type": 0,
            "commands": [
                { "property": "clearRect", "args": [0, 0, 8, 8] },
                { "property": "drawImage", "args": [
                    { "rr_type": "ImageBitmap", "args": [
                        { "rr_type": "Blob", "type": mime,
                          "data": [{ "rr_type": "ArrayBuffer", "base64": base64 }] }] },
                    0, 0, 8, 8] }],
            "displayWidth": 8, "displayHeight": 8 })
    }

    fn scrub_with(ctx: &Ctx<'_>, data: &serde_json::Value) -> (bool, serde_json::Value) {
        let mut bytes = data.to_string().into_bytes();
        let mut value = simd_json::to_borrowed_value(&mut bytes).unwrap();
        let changed = scrub_canvas_mutation(ctx, &mut value);
        (changed, serde_json::from_str(&value.encode()).unwrap())
    }

    fn blob(out: &serde_json::Value) -> &serde_json::Value {
        &out["commands"][1]["args"][0]["args"][0]
    }

    #[test]
    fn snapshot_frame_image_never_passes_through() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let b64 = png_base64(8, 8, [10, 200, 10, 255]);
        let sized = frame("image/png", &b64);
        let mut unsized_frame = sized.clone();
        unsized_frame["commands"][1]["args"]
            .as_array_mut()
            .unwrap()
            .truncate(3);
        for data in [sized, unsized_frame] {
            let ctx = Ctx::new(&allow);
            let (changed, out) = scrub_with(&ctx, &data);
            assert!(changed);
            assert_ne!(blob(&out)["data"][0]["base64"], b64.as_str());
            assert_eq!(out["commands"][0]["property"], "clearRect");
            let rejected = ctx
                .take_scrub_drops()
                .into_iter()
                .any(|(reason, _)| reason == REJECTED_CANVAS_MUTATION);
            assert!(!rejected, "a frame is kept: {data}");
        }
    }

    #[test]
    fn snapshot_frame_image_becomes_a_ref_on_the_collection_lane() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let ctx = Ctx::with_image_collection(
            &allow,
            Some(ImageCollection::new("0".repeat(32), "k".repeat(32))),
        );
        let (_, out) = scrub_with(
            &ctx,
            &frame("image/webp", &png_base64(8, 8, [10, 200, 10, 255])),
        );
        assert_eq!(blob(&out)["type"], "image/webp");
        assert!(blob(&out)["data"][0]["base64"]
            .as_str()
            .unwrap()
            .starts_with("image:"));
        assert!(ctx.take_scrub_drops().is_empty());
    }

    #[test]
    fn snapshot_frame_keeps_only_its_known_keys() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let mut data = frame("image/png", &png_base64(8, 8, [1, 2, 3, 255]));
        data["secret"] = json!("x");
        data["commands"][0]["secret"] = json!("x");
        data["commands"][1]["args"][0]["secret"] = json!("x");
        data["commands"][1]["args"][0]["args"][0]["secret"] = json!("x");
        data["commands"][1]["args"][0]["args"][0]["data"][0]["secret"] = json!("x");
        let (_, out) = scrub_with(&Ctx::new(&allow), &data);
        assert!(!out.to_string().contains("secret"), "{out}");
    }

    #[test]
    fn anything_but_a_snapshot_frame_keeps_only_its_identity() {
        let png = png_base64(8, 8, [10, 200, 10, 255]);
        let mut extra_command = frame("image/png", &png);
        extra_command["commands"]
            .as_array_mut()
            .unwrap()
            .push(json!({ "property": "fillText", "args": ["secret", 1, 2] }));
        let mut webgl = frame("image/png", &png);
        webgl["type"] = json!(1);
        let cases = [
            (
                "text",
                json!({ "source": 9, "id": 1, "type": 0,
                "commands": [{ "property": "fillText", "args": ["Hello secret", 10, 20] }] }),
            ),
            (
                "flattened command",
                json!({ "source": 9, "id": 1, "type": 0,
                "property": "strokeText", "args": ["Hi secret", 1, 2] }),
            ),
            (
                "raw pixels",
                json!({ "source": 9, "id": 1, "type": 0,
                "commands": [{ "property": "putImageData", "args": [{ "rr_type": "ImageData",
                    "args": [{ "rr_type": "ArrayBuffer", "base64": "AAAA" }, 1, 1] }, 0, 0] }] }),
            ),
            (
                "image element",
                json!({ "source": 9, "id": 1, "type": 0,
                "commands": [{ "property": "drawImage", "args": [
                    { "rr_type": "HTMLImageElement", "src": format!("data:image/png;base64,{png}") }] }] }),
            ),
            (
                "unwrapped blob",
                json!({ "source": 9, "id": 1, "type": 0,
                "commands": [{ "property": "drawImage", "args": [{ "rr_type": "Blob", "type": "image/png",
                    "data": [{ "rr_type": "ArrayBuffer", "base64": png }] }] }] }),
            ),
            ("svg frame", frame("image/svg+xml", &png)),
            ("extra command", extra_command),
            ("webgl context", webgl),
        ];
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        for (name, data) in cases {
            let ctx = Ctx::new(&allow);
            let (changed, out) = scrub_with(&ctx, &data);
            let context = if name == "webgl context" {
                json!(1)
            } else {
                json!(0)
            };
            assert!(changed, "{name}");
            assert_eq!(
                out,
                json!({ "source": 9, "id": 1, "type": context, "commands": [] }),
                "{name}"
            );
            assert_eq!(
                ctx.take_scrub_drops(),
                vec![(REJECTED_CANVAS_MUTATION, 1)],
                "{name}"
            );
        }
    }

    #[test]
    fn an_emptied_mutation_is_left_alone() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let empty = json!({ "source": 9, "id": 1, "type": 0, "commands": [] });
        let ctx = Ctx::new(&allow);
        let (changed, out) = scrub_with(&ctx, &empty);
        assert!(!changed);
        assert_eq!(out, empty);
        assert!(
            ctx.take_scrub_drops().is_empty(),
            "nothing was dropped this time"
        );
    }
}
