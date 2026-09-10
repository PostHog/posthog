//! Media detection + placeholder/blur dispatch.
//! Blur runs inline (native), so there is no deferred-job/blank-first dance — the attribute lands on
//! its final blurred (or placeholder) value directly.

use std::borrow::Cow;

use simd_json::borrowed::{Object, Value};

use crate::blur::is_image_data_uri;
use crate::collect::is_image_ref_strict;
use crate::context::{Ctx, ImageSource};
use crate::images::ImageFallback;
use crate::json::{as_f64, as_str, string_value};
use crate::srcset::largest_candidate;
use crate::url::scrub_url;

// rrweb inlines rendered pixels (a `toDataURL()` snapshot) into this attribute.
pub const INLINE_IMAGE_ATTR: &str = "rr_dataURL";

pub const PLACEHOLDER_SRC: &str = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 80 80'><rect width='80' height='80' fill='%23f3f4f6'/><rect x='6' y='6' width='68' height='68' fill='none' stroke='%23d1d5db' stroke-width='2' rx='6'/><circle cx='26' cy='26' r='6' fill='%239ca3af'/><path d='M14 60 L34 40 L48 50 L66 32 L66 66 L14 66 Z' fill='%239ca3af'/></svg>";

pub const MEDIA_SRC_ATTRS: &[&str] = &["src", "rr_src", "srcset", "href", "xlink:href", "poster"];
pub(crate) const IMAGE_REF_ATTR_PREFIX: &str = "data-anon-image-ref-";
pub(crate) const CSS_IMAGE_REFS_ATTR_PREFIX: &str = "data-anon-image-refs-";

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
    name.starts_with(IMAGE_REF_ATTR_PREFIX) || name.starts_with(CSS_IMAGE_REFS_ATTR_PREFIX)
}

pub(crate) fn numbered_placeholder(slot: usize) -> String {
    let before_close = PLACEHOLDER_SRC
        .strip_suffix("</svg>")
        .expect("the static image placeholder is SVG");
    format!("{before_close}<metadata id='anon-image-slot-{slot}'/></svg>")
}

pub(crate) fn is_numbered_placeholder(value: &str) -> bool {
    let Some(before_close) = PLACEHOLDER_SRC.strip_suffix("</svg>") else {
        return false;
    };
    let Some(slot) = value
        .strip_prefix(before_close)
        .and_then(|value| value.strip_prefix("<metadata id='anon-image-slot-"))
        .and_then(|value| value.strip_suffix("'/></svg>"))
    else {
        return false;
    };
    !slot.is_empty() && slot.bytes().all(|byte| byte.is_ascii_digit())
}

pub(crate) fn is_fetchable_image_attr(name: &str, tag: &str, parent_is_picture: bool) -> bool {
    match tag.to_ascii_lowercase().as_str() {
        "img" => matches!(name, "src" | "rr_src" | "srcset"),
        "image" => matches!(name, "href" | "xlink:href"),
        "video" => name == "poster",
        "source" => parent_is_picture && name == "srcset",
        _ => false,
    }
}

/// A CSS or HTML length read as pixels. `1`, `1px`, and `1.0` all read as one pixel. A percentage or
/// another unit reads as unknown.
pub(crate) fn px_length(text: &str) -> Option<f64> {
    let text = text.trim().to_ascii_lowercase();
    let number = text.strip_suffix("px").map_or(text.as_str(), str::trim);
    number.parse::<f64>().ok()
}

/// Both dimensions are known and neither is larger than one pixel. A negative length is not a
/// small box: the browser ignores it and renders the natural size.
pub(crate) fn is_at_most_one_pixel(width: Option<f64>, height: Option<f64>) -> bool {
    let at_most_one = |length: f64| (0.0..=1.0).contains(&length);
    matches!((width, height), (Some(width), Some(height)) if at_most_one(width) && at_most_one(height))
}

/// The last value an inline style gives one property, lowercased and without `!important`.
fn inline_style_declaration(style: &str, property: &str) -> Option<String> {
    style
        .split(';')
        .filter_map(|declaration| declaration.split_once(':'))
        .filter(|(name, _)| name.trim().eq_ignore_ascii_case(property))
        .map(|(_, value)| without_important(&value.trim().to_ascii_lowercase()).to_string())
        .next_back()
}

/// CSS allows white space between the `!` and `important`.
fn without_important(value: &str) -> &str {
    let Some(before_keyword) = value.strip_suffix("important") else {
        return value;
    };
    match before_keyword.trim_end().strip_suffix('!') {
        Some(declared_value) => declared_value.trim_end(),
        None => value,
    }
}

/// The inline style wins over the `width` and `height` attributes, as it does in the browser, so
/// a declared style that is not a pixel length leaves the dimension unknown.
fn dimension_px(attrs: &Object<'_>, style: Option<&str>, name: &str) -> Option<f64> {
    if let Some(declared) = style.and_then(|style| inline_style_declaration(style, name)) {
        return px_length(&declared);
    }
    let attribute = attrs.get(name)?;
    as_str(attribute).map_or_else(|| as_f64(attribute), px_length)
}

/// An `img` nobody can see: hidden by the `hidden` attribute or by `display: none`, or a box of
/// at most one pixel on each side. Such an element is a tracking pixel or a spacer, so its URL has
/// no value to the fetch lane, and a fetch of it reports a visit to whoever serves it. The byte
/// walker mirrors the attribute half of this rule in `bytewalk::attrs_hide_pixel`.
pub(crate) fn is_hidden_pixel(attrs: &Object<'_>) -> bool {
    if attrs.contains_key("hidden") {
        return true;
    }
    let style = attrs.get("style").and_then(as_str);
    let display = style.and_then(|style| inline_style_declaration(style, "display"));
    if display.as_deref() == Some("none") {
        return true;
    }
    is_at_most_one_pixel(
        dimension_px(attrs, style, "width"),
        dimension_px(attrs, style, "height"),
    )
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
    let blurred = ctx.scrub_image_from(
        &value,
        ImageFallback::Blank,
        ImageSource::HtmlAttribute(INLINE_IMAGE_ATTR),
    );
    attrs.insert(Cow::Owned(name.to_string()), string_value(blurred));
    true
}

/// Replace a media element's source attrs with the blurred image (data URIs) or placeholder (remote
/// URLs). A collected remote URL's ref and scrubbed original are stashed under separate namespaced
/// attrs. Returns whether it changed any attribute — a media tag with no source attrs (e.g. a bare
/// `<img>`) is left untouched.
pub fn apply_blur(
    ctx: &Ctx<'_>,
    attrs: &mut Object<'_>,
    tag: &str,
    parent_is_picture: bool,
) -> bool {
    let mut acted = false;
    // Computed only when a remote image is about to be collected, because the inline style is
    // parsed for it and most elements never reach that branch.
    let mut hidden_pixel: Option<bool> = None;
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
        let selected = if *key == "srcset" {
            largest_candidate(&existing).map(str::to_string)
        } else {
            Some(existing.clone())
        };
        let Some(selected) = selected else {
            attrs.insert(
                Cow::Borrowed(*key),
                Value::String(Cow::Borrowed(PLACEHOLDER_SRC)),
            );
            continue;
        };
        if is_image_data_uri(&selected) {
            let blurred = ctx.scrub_image_from(
                &selected,
                ImageFallback::Placeholder,
                ImageSource::HtmlAttribute(key),
            );
            attrs.insert(Cow::Borrowed(*key), string_value(blurred));
        } else {
            let collected =
                if !ctx.collects_urls() || !is_fetchable_image_attr(key, tag, parent_is_picture) {
                    None
                } else if *hidden_pixel.get_or_insert_with(|| {
                    tag.eq_ignore_ascii_case("img") && is_hidden_pixel(attrs)
                }) {
                    ctx.decline_url(&selected, "hidden_pixel");
                    None
                } else {
                    ctx.collect_url_from(&selected, ImageSource::HtmlAttribute(key))
                };
            let scrubbed = scrub_url(ctx, &selected).unwrap_or_else(|| selected.clone());
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
