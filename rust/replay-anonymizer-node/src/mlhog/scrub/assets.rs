// Copied from MLHog prep/labeling/src/scrub/assets.rs — bench-only. Adapted: `attr_str` and
// `apply_blur` are dropped (they need the v1 typed tree's `schema::AttrValue`, which is not
// ported); v2 only uses the constants and tag/attr predicates below.
#![allow(dead_code)]

// rrweb inlines rendered pixels (toDataURL) here for <canvas>/<img>.
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
    MEDIA_SRC_ATTRS.iter().any(|a| *a == name)
}
