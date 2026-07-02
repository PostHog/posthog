//! Walks parsed rrweb serialized nodes, scrubbing text content and attributes in place.
//! Mirrors `anonymize/dom.ts`, operating on `simd_json::OwnedValue` (generic objects) so unknown
//! fields survive the round-trip exactly, matching the TS in-place mutation.

use simd_json::value::owned::Object;
use simd_json::OwnedValue;

use crate::allow_lists::AllowLists;
use crate::assets::{
    apply_blur, blur_inline_image_attr, has_media_src_attr, is_media_src_attr, is_media_tag,
    INLINE_IMAGE_ATTR,
};
use crate::css::scrub_css_images;
use crate::json::{as_array_mut, as_object_mut, as_small_uint, as_str, is_object, is_true};
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

pub fn scrub_full_snapshot(allow: &AllowLists, data: &mut OwnedValue) -> bool {
    let Some(obj) = as_object_mut(data) else {
        return false;
    };
    match obj.get_mut("node") {
        Some(node) if is_object(node) => walk_node(allow, node, ParentKind::Other),
        _ => false,
    }
}

pub fn scrub_mutation(allow: &AllowLists, data: &mut OwnedValue) -> bool {
    let Some(obj) = as_object_mut(data) else {
        return false;
    };
    let mut changed = false;

    if let Some(texts) = obj.get_mut("texts").and_then(as_array_mut) {
        for t in texts.iter_mut() {
            if let Some(tobj) = as_object_mut(t) {
                let cur = tobj.get("value").and_then(as_str).map(str::to_string);
                if let Some(v) = cur {
                    if let Some(nv) = scrub_text(allow, &v) {
                        tobj.insert("value".to_string(), OwnedValue::String(nv));
                        changed = true;
                    }
                }
            }
        }
    }

    if let Some(attributes) = obj.get_mut("attributes").and_then(as_array_mut) {
        for a in attributes.iter_mut() {
            if let Some(aobj) = as_object_mut(a) {
                if let Some(attrs) = aobj.get_mut("attributes").and_then(as_object_mut) {
                    let kind = if has_media_src_attr(attrs) {
                        TagKind::Media
                    } else {
                        TagKind::Other
                    };
                    changed |= scrub_attrs(allow, attrs, kind);
                }
            }
        }
    }

    if let Some(adds) = obj.get_mut("adds").and_then(as_array_mut) {
        for added in adds.iter_mut() {
            if let Some(aobj) = as_object_mut(added) {
                if let Some(node) = aobj.get_mut("node") {
                    if is_object(node) {
                        changed |= walk_node(allow, node, ParentKind::Other);
                    }
                }
            }
        }
    }

    changed
}

fn walk_node(allow: &AllowLists, node: &mut OwnedValue, parent: ParentKind) -> bool {
    let Some(obj) = as_object_mut(node) else {
        return false;
    };
    let mut changed = false;

    match obj.get("type").and_then(as_small_uint) {
        Some(NODE_ELEMENT) => {
            let tag = obj
                .get("tagName")
                .and_then(as_str)
                .unwrap_or("")
                .to_string();
            let kind = classify_tag(&tag);
            if let Some(attrs) = obj.get_mut("attributes").and_then(as_object_mut) {
                changed |= scrub_attrs(allow, attrs, kind);
            }
            let child_parent = match kind {
                TagKind::Script => ParentKind::Script,
                TagKind::Style => ParentKind::Style,
                TagKind::Media | TagKind::Other => ParentKind::Other,
            };
            if let Some(children) = obj.get_mut("childNodes").and_then(as_array_mut) {
                for child in children.iter_mut() {
                    if is_object(child) {
                        changed |= walk_node(allow, child, child_parent);
                    }
                }
            }
        }
        Some(NODE_DOCUMENT) => {
            if let Some(children) = obj.get_mut("childNodes").and_then(as_array_mut) {
                for child in children.iter_mut() {
                    if is_object(child) {
                        changed |= walk_node(allow, child, ParentKind::Other);
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
                return scrub_css_images(obj, "textContent");
            }
            changed |= scrub_text_content(allow, obj);
        }
        Some(NODE_COMMENT) | Some(NODE_CDATA) => {
            changed |= scrub_text_content(allow, obj);
        }
        _ => {} // DocumentType or unknown: nothing.
    }

    changed
}

fn scrub_text_content(allow: &AllowLists, obj: &mut Object) -> bool {
    let Some(cur) = obj.get("textContent").and_then(as_str).map(str::to_string) else {
        return false;
    };
    match scrub_text(allow, &cur) {
        Some(v) => {
            obj.insert("textContent".to_string(), OwnedValue::String(v));
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

fn scrub_attrs(allow: &AllowLists, attrs: &mut Object, kind: TagKind) -> bool {
    let mut changed = false;
    let names: Vec<String> = attrs.keys().cloned().collect();

    for name in names {
        if kind == TagKind::Media && is_media_src_attr(&name) {
            continue;
        }
        // Inlined rendered pixels (`rr_dataURL`): blur the image, on any tag.
        if name == INLINE_IMAGE_ATTR {
            changed |= blur_inline_image_attr(attrs, &name);
            continue;
        }
        // Only string attribute values are scrubbed.
        let Some(value) = attrs
            .get(name.as_str())
            .and_then(as_str)
            .map(str::to_string)
        else {
            continue;
        };
        let result = if is_url_attr(&name) {
            scrub_url(allow, &value)
        } else if name == "style" {
            changed |= scrub_css_images(attrs, &name);
            continue;
        } else if is_user_text_attr(&name) {
            scrub_text(allow, &value)
        } else if is_data_attr(&name) {
            if data_attr_looks_sensitive(&value) {
                scrub_text(allow, &value)
            } else {
                redact_emails(&value)
            }
        } else {
            continue;
        };
        if let Some(v) = result {
            attrs.insert(name.clone(), OwnedValue::String(v));
            changed = true;
        }
    }

    if kind == TagKind::Media {
        apply_blur(allow, attrs);
        changed = true;
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
