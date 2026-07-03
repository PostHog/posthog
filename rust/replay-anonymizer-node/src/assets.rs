//! Media detection + placeholder/blur dispatch. Mirrors `anonymize/assets.ts`.
//! Blur runs inline (native), so there is no deferred-job/blank-first dance — the attribute lands on
//! its final blurred (or placeholder) value directly.

use std::borrow::Cow;

use simd_json::borrowed::{Object, Value};

use crate::blur::{blank_image_data_uri, is_image_data_uri};
use crate::context::Ctx;
use crate::json::{as_str, string_value};
use crate::url::scrub_url_opts;

// rrweb inlines rendered pixels (a `toDataURL()` snapshot) into this attribute.
pub const INLINE_IMAGE_ATTR: &str = "rr_dataURL";

pub const PLACEHOLDER_SRC: &str = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 80 80'><rect width='80' height='80' fill='%23f3f4f6'/><rect x='6' y='6' width='68' height='68' fill='none' stroke='%23d1d5db' stroke-width='2' rx='6'/><circle cx='26' cy='26' r='6' fill='%239ca3af'/><path d='M14 60 L34 40 L48 50 L66 32 L66 66 L14 66 Z' fill='%239ca3af'/></svg>";

pub const MEDIA_SRC_ATTRS: &[&str] = &["src", "srcset", "href", "xlink:href", "poster"];

pub fn is_media_tag(tag: &str) -> bool {
    matches!(
        tag.to_ascii_lowercase().as_str(),
        "img" | "image" | "video" | "audio" | "source" | "track" | "picture"
    )
}

pub fn is_media_src_attr(name: &str) -> bool {
    MEDIA_SRC_ATTRS.contains(&name)
}

/// True if an attribute map contains any media-source attribute.
pub fn has_media_src_attr(attrs: &Object<'_>) -> bool {
    MEDIA_SRC_ATTRS.iter().any(|name| attrs.contains_key(*name))
}

/// Blur an inlined-image data URI held in an attribute (a `<canvas>`/`<img>` `rr_dataURL`).
/// Returns whether it acted.
pub fn blur_inline_image_attr(ctx: &Ctx<'_>, attrs: &mut Object<'_>, name: &str) -> bool {
    let Some(value) = attrs.get(name).and_then(as_str).map(str::to_string) else {
        return false;
    };
    if !is_image_data_uri(&value) {
        return false;
    }
    let blurred = ctx
        .blur_data_uri(&value)
        .unwrap_or_else(blank_image_data_uri);
    attrs.insert(Cow::Owned(name.to_string()), string_value(blurred));
    true
}

/// Replace a media element's source attrs with the blurred image (data URIs) or placeholder (remote
/// URLs, whose scrubbed original is stashed under a namespaced attr). Returns whether it changed any
/// attribute — a media tag with no source attrs (e.g. a bare `<img>`) is left untouched.
pub fn apply_blur(ctx: &Ctx<'_>, attrs: &mut Object<'_>) -> bool {
    let mut acted = false;
    for key in MEDIA_SRC_ATTRS {
        let Some(existing) = attrs.get(*key).and_then(as_str).map(str::to_string) else {
            continue;
        };
        acted = true;
        if is_image_data_uri(&existing) {
            let blurred = ctx
                .blur_data_uri(&existing)
                .unwrap_or_else(|| PLACEHOLDER_SRC.to_string());
            attrs.insert(Cow::Borrowed(*key), string_value(blurred));
        } else {
            // Host-scrubbed too so a CDN host can't leak; stashed under a namespaced attr that won't
            // collide with an app `data-original-*`.
            let scrubbed = scrub_url_opts(ctx.allow, &existing, true).unwrap_or(existing);
            attrs.insert(
                Cow::Borrowed(*key),
                Value::String(Cow::Borrowed(PLACEHOLDER_SRC)),
            );
            attrs.insert(
                Cow::Owned(format!("data-anon-original-{key}")),
                string_value(scrubbed),
            );
        }
    }
    acted
}
