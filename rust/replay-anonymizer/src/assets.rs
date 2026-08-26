//! Media detection + placeholder/blur dispatch.
//! Blur runs inline (native), so there is no deferred-job/blank-first dance — the attribute lands on
//! its final blurred (or placeholder) value directly.

use std::borrow::Cow;

use simd_json::borrowed::{Object, Value};

use crate::blur::is_image_data_uri;
use crate::collect::is_image_ref_strict;
use crate::context::Ctx;
use crate::images::ImageFallback;
use crate::json::{as_str, string_value};
use crate::url::scrub_url;

// rrweb inlines rendered pixels (a `toDataURL()` snapshot) into this attribute.
pub const INLINE_IMAGE_ATTR: &str = "rr_dataURL";

pub const PLACEHOLDER_SRC: &str = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 80 80'><rect width='80' height='80' fill='%23f3f4f6'/><rect x='6' y='6' width='68' height='68' fill='none' stroke='%23d1d5db' stroke-width='2' rx='6'/><circle cx='26' cy='26' r='6' fill='%239ca3af'/><path d='M14 60 L34 40 L48 50 L66 32 L66 66 L14 66 Z' fill='%239ca3af'/></svg>";

pub const MEDIA_SRC_ATTRS: &[&str] = &["src", "rr_src", "srcset", "href", "xlink:href", "poster"];
pub(crate) const IMAGE_REF_ATTR_PREFIX: &str = "data-anon-image-ref-";

pub fn is_media_tag(tag: &str) -> bool {
    matches!(
        tag.to_ascii_lowercase().as_str(),
        "img" | "image" | "video" | "audio" | "source" | "track" | "picture"
    )
}

pub fn is_media_src_attr(name: &str) -> bool {
    MEDIA_SRC_ATTRS.contains(&name)
}

pub(crate) fn is_image_ref_attr(name: &str) -> bool {
    name.starts_with(IMAGE_REF_ATTR_PREFIX)
}

/// True for a tag whose `src` names an image.
///
/// `TagKind::Media` is too broad to decide this. It also covers `video`, `audio`, `track` and
/// `source`. Their `src` is a movie, a sound file, or a WebVTT subtitle document.
///
/// `source` is excluded because its meaning depends on its parent, and the walk does not carry
/// one.
pub(crate) fn tag_src_is_image(tag: &str) -> bool {
    matches!(
        tag.to_ascii_lowercase().as_str(),
        "img" | "image" | "picture"
    )
}

/// Whether the fetch lane may collect the URL in this attribute.
///
/// A subset of [`MEDIA_SRC_ATTRS`], because the rest do not name one fetchable image.
///
/// `src` needs the tag as well as the name.
///
/// Without the tag check, the lane collects the `src` of a `<video>`, an `<audio>` or a `<track>`.
/// The mutation path is worse: rrweb sends attributes with no tag, so any `src` passes, including
/// one from an `<iframe>` or a `<script>`.
///
/// The fetch lane is sized to download images. Video, subtitle text and third-party JavaScript are
/// a different workload and a different data-classification question. `tag_src_is_image` is false
/// on the tagless mutation path, so that path declines rather than guesses.
///
/// The other media attributes remain out of scope until the fetcher specification includes them.
pub(crate) fn is_fetchable_src_attr(name: &str, tag_src_is_image: bool) -> bool {
    name == "src" && tag_src_is_image
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
    let blurred = ctx.scrub_image(&value, ImageFallback::Blank);
    attrs.insert(Cow::Owned(name.to_string()), string_value(blurred));
    true
}

/// Replace a media element's source attrs with the blurred image (data URIs) or placeholder (remote
/// URLs). A collected remote URL's ref and scrubbed original are stashed under separate namespaced
/// attrs. Returns whether it changed any attribute — a media tag with no source attrs (e.g. a bare
/// `<img>`) is left untouched.
pub fn apply_blur(ctx: &Ctx<'_>, attrs: &mut Object<'_>, tag_src_is_image: bool) -> bool {
    let mut acted = false;
    for key in MEDIA_SRC_ATTRS {
        let Some(existing) = attrs.get(*key).and_then(as_str).map(str::to_string) else {
            continue;
        };
        // A content ref from an earlier pass over already-mirrored output: opaque, carrying no
        // content of its own, with its bytes scrubbed out of band. Re-scrubbing would redact it
        // into the placeholder and strand that image beyond recovery, so a caller re-scrubbing
        // mirrored output opts into keeping it. Gated on the caller's own assertion of
        // provenance, never on the shape alone — the format is forgeable by a captured page.
        if ctx.keeps_image_refs() && is_image_ref_strict(&existing) {
            continue;
        }
        acted = true;
        if is_image_data_uri(&existing) {
            let blurred = ctx.scrub_image(&existing, ImageFallback::Placeholder);
            attrs.insert(Cow::Borrowed(*key), string_value(blurred));
        } else {
            let collected = is_fetchable_src_attr(key, tag_src_is_image)
                .then(|| ctx.collect_url(&existing))
                .flatten();
            let scrubbed = scrub_url(ctx, &existing).unwrap_or(existing);
            // Fetch completion must not change how an ordinary replay renders this element.
            attrs.insert(
                Cow::Borrowed(*key),
                Value::String(Cow::Borrowed(PLACEHOLDER_SRC)),
            );
            if let Some(url_ref) = collected {
                attrs.insert(
                    Cow::Owned(format!("{IMAGE_REF_ATTR_PREFIX}{key}")),
                    string_value(url_ref),
                );
            }
            attrs.insert(
                Cow::Owned(format!("data-anon-original-{key}")),
                string_value(scrubbed),
            );
        }
    }
    acted
}
