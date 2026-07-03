//! Walks parsed rrweb serialized nodes, scrubbing text content and attributes in place.
//! Mirrors `anonymize/dom.ts`, operating on `simd_json::BorrowedValue` (generic objects) so unknown
//! fields survive the round-trip exactly, matching the TS in-place mutation.

use simd_json::borrowed::{Object, Value};

use crate::assets::{
    apply_blur, blur_inline_image_attr, has_media_src_attr, is_media_src_attr, is_media_tag,
    INLINE_IMAGE_ATTR,
};
use crate::context::Ctx;
use crate::css::scrub_css_images;
use crate::json::{
    as_array_mut, as_object_mut, as_small_uint, as_str, is_object, is_true, key, string_value,
};
use crate::text::{redact_emails, scrub_text};
use crate::url::scrub_url;

// rrweb NodeType
const NODE_DOCUMENT: u8 = 0;
const NODE_ELEMENT: u8 = 2;
const NODE_TEXT: u8 = 3;
const NODE_CDATA: u8 = 4;
const NODE_COMMENT: u8 = 5;

#[derive(Clone, Copy, PartialEq, Eq)]
enum ParentKind {
    Script,
    Style,
    Other,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum TagKind {
    Script,
    Style,
    Media,
    Other,
}

pub fn scrub_full_snapshot(ctx: &Ctx<'_>, data: &mut Value<'_>) -> bool {
    let Some(obj) = as_object_mut(data) else {
        return false;
    };
    match obj.get_mut("node") {
        Some(node) if is_object(node) => walk_node(ctx, node, ParentKind::Other),
        _ => false,
    }
}

pub fn scrub_mutation(ctx: &Ctx<'_>, data: &mut Value<'_>) -> bool {
    let Some(obj) = as_object_mut(data) else {
        return false;
    };
    let mut changed = false;

    if let Some(texts) = obj.get_mut("texts").and_then(as_array_mut) {
        changed |= scrub_mutation_texts(ctx, texts);
    }
    if let Some(attributes) = obj.get_mut("attributes").and_then(as_array_mut) {
        changed |= scrub_mutation_attributes(ctx, attributes);
    }
    if let Some(adds) = obj.get_mut("adds").and_then(as_array_mut) {
        changed |= scrub_mutation_adds(ctx, adds);
    }

    changed
}

// The three sub-scrubs are exposed separately so the `cv` path can run each decompressed sub-field as
// its own borrowed tree (each borrows a different scratch buffer).

pub fn scrub_mutation_texts(ctx: &Ctx<'_>, texts: &mut Vec<Value<'_>>) -> bool {
    let mut changed = false;
    for t in texts.iter_mut() {
        if let Some(tobj) = as_object_mut(t) {
            let cur = tobj.get("value").and_then(as_str);
            if let Some(v) = cur {
                if let Some(nv) = scrub_text(ctx.allow, v) {
                    tobj.insert(key("value"), string_value(nv));
                    changed = true;
                }
            }
        }
    }
    changed
}

pub fn scrub_mutation_attributes(ctx: &Ctx<'_>, attributes: &mut Vec<Value<'_>>) -> bool {
    let mut changed = false;
    for a in attributes.iter_mut() {
        if let Some(aobj) = as_object_mut(a) {
            if let Some(attrs) = aobj.get_mut("attributes").and_then(as_object_mut) {
                let kind = if has_media_src_attr(attrs) {
                    TagKind::Media
                } else {
                    TagKind::Other
                };
                changed |= scrub_attrs(ctx, attrs, kind);
            }
        }
    }
    changed
}

pub fn scrub_mutation_adds(ctx: &Ctx<'_>, adds: &mut Vec<Value<'_>>) -> bool {
    let mut changed = false;
    for added in adds.iter_mut() {
        if let Some(aobj) = as_object_mut(added) {
            if let Some(node) = aobj.get_mut("node") {
                if is_object(node) {
                    changed |= walk_node(ctx, node, ParentKind::Other);
                }
            }
        }
    }
    changed
}

fn walk_node(ctx: &Ctx<'_>, node: &mut Value<'_>, parent: ParentKind) -> bool {
    let Some(obj) = as_object_mut(node) else {
        return false;
    };
    let mut changed = false;

    match obj.get("type").and_then(as_small_uint) {
        Some(NODE_ELEMENT) => {
            let kind = classify_tag(obj.get("tagName").and_then(as_str).unwrap_or(""));
            if let Some(attrs) = obj.get_mut("attributes").and_then(as_object_mut) {
                changed |= scrub_attrs(ctx, attrs, kind);
            }
            let child_parent = match kind {
                TagKind::Script => ParentKind::Script,
                TagKind::Style => ParentKind::Style,
                TagKind::Media | TagKind::Other => ParentKind::Other,
            };
            if let Some(children) = obj.get_mut("childNodes").and_then(as_array_mut) {
                for child in children.iter_mut() {
                    if is_object(child) {
                        changed |= walk_node(ctx, child, child_parent);
                    }
                }
            }
        }
        Some(NODE_DOCUMENT) => {
            if let Some(children) = obj.get_mut("childNodes").and_then(as_array_mut) {
                for child in children.iter_mut() {
                    if is_object(child) {
                        changed |= walk_node(ctx, child, ParentKind::Other);
                    }
                }
            }
        }
        Some(NODE_TEXT) => {
            // Script is code — never touch it.
            if parent == ParentKind::Script {
                return false;
            }
            let is_style = obj.get("isStyle").map(is_true).unwrap_or(false);
            if parent == ParentKind::Style || is_style {
                return scrub_css_images(ctx, obj, "textContent");
            }
            changed |= scrub_text_content(ctx, obj);
        }
        Some(NODE_COMMENT) | Some(NODE_CDATA) => {
            changed |= scrub_text_content(ctx, obj);
        }
        _ => {} // DocumentType or unknown: nothing.
    }

    changed
}

fn scrub_text_content(ctx: &Ctx<'_>, obj: &mut Object<'_>) -> bool {
    let Some(cur) = obj.get("textContent").and_then(as_str) else {
        return false;
    };
    match scrub_text(ctx.allow, cur) {
        Some(v) => {
            obj.insert(key("textContent"), string_value(v));
            true
        }
        None => false,
    }
}

fn classify_tag(tag: &str) -> TagKind {
    if tag.eq_ignore_ascii_case("script") {
        TagKind::Script
    } else if tag.eq_ignore_ascii_case("style") {
        TagKind::Style
    } else if is_media_tag(tag) {
        TagKind::Media
    } else {
        TagKind::Other
    }
}

fn scrub_attrs(ctx: &Ctx<'_>, attrs: &mut Object<'_>, kind: TagKind) -> bool {
    let mut changed = false;
    let names: Vec<String> = attrs.keys().map(|k| k.to_string()).collect();

    for name in names {
        if kind == TagKind::Media && is_media_src_attr(&name) {
            continue;
        }
        // Inlined rendered pixels (`rr_dataURL`): blur the image, on any tag.
        if name == INLINE_IMAGE_ATTR {
            changed |= blur_inline_image_attr(ctx, attrs, &name);
            continue;
        }
        // Only string attribute values are scrubbed.
        let Some(value) = attrs.get(name.as_str()).and_then(as_str) else {
            continue;
        };
        let result = if is_url_attr(&name) {
            scrub_url(ctx.allow, value)
        } else if name == "style" {
            changed |= scrub_css_images(ctx, attrs, &name);
            continue;
        } else if is_user_text_attr(&name) {
            scrub_text(ctx.allow, value)
        } else if is_data_attr(&name) {
            if data_attr_looks_sensitive(value) {
                scrub_text(ctx.allow, value)
            } else {
                redact_emails(value)
            }
        } else {
            continue;
        };
        if let Some(v) = result {
            attrs.insert(name.into(), string_value(v));
            changed = true;
        }
    }

    if kind == TagKind::Media {
        changed |= apply_blur(ctx, attrs);
    }

    changed
}

fn is_user_text_attr(name: &str) -> bool {
    matches!(
        name,
        "alt"
            | "title"
            | "placeholder"
            | "aria-label"
            | "aria-description"
            | "aria-roledescription"
            | "aria-valuetext"
            | "aria-placeholder"
            | "value"
            | "label"
            | "summary"
    )
}

fn is_data_attr(name: &str) -> bool {
    name.starts_with("data-") && !name.starts_with("data-anon-original-")
}

fn data_attr_looks_sensitive(value: &str) -> bool {
    // Free text (whitespace) or an email-ish token — not a single enum/state/id token.
    value.contains('@') || value.chars().any(char::is_whitespace)
}

fn is_url_attr(name: &str) -> bool {
    matches!(
        name,
        "href"
            | "src"
            | "srcset"
            | "action"
            | "formaction"
            | "cite"
            | "data"
            | "poster"
            | "background"
            | "xlink:href"
            | "manifest"
            | "longdesc"
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::allow_lists::AllowLists;
    use crate::context::Ctx;
    use crate::testkit::png_data_uri;
    use simd_json::prelude::Writable;

    fn scrub_snapshot(data_json: &str) -> serde_json::Value {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        let mut bytes = data_json.as_bytes().to_vec();
        let mut data = simd_json::to_borrowed_value(&mut bytes).unwrap();
        scrub_full_snapshot(&ctx, &mut data);
        serde_json::from_str(&data.encode()).unwrap()
    }

    #[test]
    fn inline_rr_dataurl_image_is_neutralized() {
        let uri = png_data_uri(8, 8, [10, 10, 200, 255]);
        let data = format!(
            r#"{{"node":{{"type":0,"childNodes":[{{"type":2,"tagName":"div","attributes":{{"rr_dataURL":"{uri}"}},"childNodes":[]}}]}},"initialOffset":{{"top":0,"left":0}}}}"#
        );
        let out = scrub_snapshot(&data);
        let v = out["node"]["childNodes"][0]["attributes"]["rr_dataURL"]
            .as_str()
            .unwrap();
        assert!(v.starts_with("data:image/"), "still an image: {v}");
        assert_ne!(v, uri, "raw inline image must not pass through");
    }

    #[test]
    fn css_data_image_background_is_neutralized() {
        let uri = png_data_uri(8, 8, [200, 200, 10, 255]);
        let style = serde_json::to_string(&format!("background:url({uri})")).unwrap();
        let data = format!(
            r#"{{"node":{{"type":0,"childNodes":[{{"type":2,"tagName":"div","attributes":{{"style":{style}}},"childNodes":[]}}]}},"initialOffset":{{"top":0,"left":0}}}}"#
        );
        let out = scrub_snapshot(&data);
        let scrubbed = out["node"]["childNodes"][0]["attributes"]["style"]
            .as_str()
            .unwrap();
        assert!(!scrubbed.contains(&uri), "the original image must be gone");
        assert!(
            scrubbed.contains("url(data:image/png"),
            "replaced with a data image: {scrubbed}"
        );
    }

    #[test]
    fn media_tag_without_source_attrs_is_not_marked_changed() {
        // A bare <img> (media tag, but no src/href/etc. to blur) must report "unchanged" so the whole
        // message isn't needlessly re-serialized just because a media element was present.
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        let mut bytes = br#"{"node":{"type":0,"childNodes":[{"type":2,"tagName":"img","attributes":{"class":"logo"},"childNodes":[]}]},"initialOffset":{"top":0,"left":0}}"#.to_vec();
        let mut data = simd_json::to_borrowed_value(&mut bytes).unwrap();
        assert!(
            !scrub_full_snapshot(&ctx, &mut data),
            "a media tag with nothing to blur should not count as a change"
        );
    }
}
