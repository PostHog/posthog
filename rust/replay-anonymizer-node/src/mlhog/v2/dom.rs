// Ported from MLHog prep/labeling/src/v2/dom.rs — bench-only. Adapted: leaf scrubs go through
// `crate::mlhog::leaf` / the crate's `assets`/`blur` modules (shared with the tree walk), and blur
// runs through the shared `Ctx` memo. Traversal mechanics are unchanged.
use std::cell::Cell;

use super::scan;
use crate::assets::{MEDIA_SRC_ATTRS, PLACEHOLDER_SRC};
use crate::blur::is_image_data_uri;
use crate::context::Ctx;
use crate::mlhog::leaf;

#[derive(Clone, Copy, PartialEq)]
pub enum Parent {
    Script,
    Style,
    Other,
}

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Script,
    Style,
    Media,
    Other,
}

const T_ELEMENT: u8 = 2;
const T_TEXT: u8 = 3;
const T_CDATA: u8 = 4;
const T_COMMENT: u8 = 5;

pub fn walk_node(
    ctx: &Ctx<'_>,
    b: &[u8],
    pos: usize,
    out: &mut Vec<u8>,
    parent: Parent,
    changed: &Cell<bool>,
) -> Option<usize> {
    // Context is looked up order-independently (rrweb key order isn't guaranteed — `isStyle` follows
    // `textContent`). `type` is first (cheap); `tagName` sits before `childNodes`; `isStyle` is only
    // fetched for text nodes, which have no `childNodes`, so none of these scan a subtree.
    let ty = scan::member_uint(b, pos, b"type");
    let (kind, is_style) = match ty {
        Some(T_ELEMENT) => (node_kind(b, pos), false),
        Some(T_TEXT) => (Kind::Other, scan::member_is_true(b, pos, b"isStyle")),
        _ => (Kind::Other, false),
    };

    scan::walk_members(b, pos, out, |key, vp, o| match key {
        b"textContent" => text_content(ctx, b, vp, o, ty, parent, is_style, changed),
        b"attributes" if ty == Some(T_ELEMENT) => {
            walk_attrs(ctx, b, vp, o, kind == Kind::Media, changed)
        }
        b"childNodes" => {
            let cp = child_parent(ty, kind);
            scan::walk_elements(b, vp, o, |_, ep, o| walk_node(ctx, b, ep, o, cp, changed))
        }
        _ => scan::copy_value(b, vp, o),
    })
}

fn child_parent(ty: Option<u8>, kind: Kind) -> Parent {
    if ty != Some(T_ELEMENT) {
        return Parent::Other;
    }
    match kind {
        Kind::Script => Parent::Script,
        Kind::Style => Parent::Style,
        _ => Parent::Other,
    }
}

#[allow(clippy::too_many_arguments)]
fn text_content(
    ctx: &Ctx<'_>,
    b: &[u8],
    vp: usize,
    out: &mut Vec<u8>,
    ty: Option<u8>,
    parent: Parent,
    is_style: bool,
    changed: &Cell<bool>,
) -> Option<usize> {
    match ty {
        Some(T_TEXT) => {
            if parent == Parent::Script {
                scan::copy_value(b, vp, out)
            } else if parent == Parent::Style || is_style {
                scrub(b, vp, out, changed, |s, buf| leaf::css_into(ctx, s, buf))
            } else {
                scrub(b, vp, out, changed, |s, buf| leaf::text_into(ctx, s, buf))
            }
        }
        Some(T_CDATA) | Some(T_COMMENT) => {
            scrub(b, vp, out, changed, |s, buf| leaf::text_into(ctx, s, buf))
        }
        _ => scan::copy_value(b, vp, out),
    }
}

pub fn has_media_src_attr(b: &[u8], obj_pos: usize) -> bool {
    MEDIA_SRC_ATTRS
        .iter()
        .any(|a| scan::find_member(b, obj_pos, a.as_bytes()).is_some())
}

fn is_media_src_attr(name: &[u8]) -> bool {
    MEDIA_SRC_ATTRS.iter().any(|a| a.as_bytes() == name)
}

pub fn walk_attrs(
    ctx: &Ctx<'_>,
    b: &[u8],
    pos: usize,
    out: &mut Vec<u8>,
    is_media: bool,
    changed: &Cell<bool>,
) -> Option<usize> {
    if !is_media {
        return scan::walk_members(b, pos, out, |name, vp, o| attr_scrub(ctx, b, name, vp, o, changed));
    }
    // Media: media-src attrs → placeholder/blur (+ stash); other attrs → normal rules; then append
    // the stashed `data-anon-original-*`.
    if b.get(pos) != Some(&b'{') {
        return scan::copy_value(b, pos, out);
    }
    out.push(b'{');
    let mut stash: Vec<(String, String)> = Vec::new();
    let mut i = scan::skip_ws(b, pos + 1);
    let mut first = true;
    if b.get(i) != Some(&b'}') {
        loop {
            let ke = scan::skip_string(b, i)?;
            let name = &b[i + 1..ke - 1];
            let c = scan::skip_ws(b, ke);
            if b.get(c) != Some(&b':') {
                return None;
            }
            if !first {
                out.push(b',');
            }
            first = false;
            out.extend_from_slice(&b[i..ke]);
            out.push(b':');
            let vp = scan::skip_ws(b, c + 1);
            i = scan::skip_ws(
                b,
                if is_media_src_attr(name) && b.get(vp) == Some(&b'"') {
                    // Matches `crate::assets::apply_blur`: acting on a media-src attr is a change.
                    changed.set(true);
                    media_src(ctx, b, name, vp, out, &mut stash)?
                } else {
                    attr_scrub(ctx, b, name, vp, out, changed)?
                },
            );
            match b.get(i) {
                Some(b',') => i = scan::skip_ws(b, i + 1),
                Some(b'}') => break,
                _ => return None,
            }
        }
    }
    for (k, v) in stash {
        if !first {
            out.push(b',');
        }
        first = false;
        scan::emit_str(&k, out);
        out.push(b':');
        scan::emit_str(&v, out);
    }
    out.push(b'}');
    Some(i + 1)
}

fn media_src(
    ctx: &Ctx<'_>,
    b: &[u8],
    name: &[u8],
    vp: usize,
    out: &mut Vec<u8>,
    stash: &mut Vec<(String, String)>,
) -> Option<usize> {
    let mut owned = String::new();
    let (s, end) = scan::string_str(b, vp, &mut owned)?;
    if is_image_data_uri(s) {
        let v = ctx
            .blur_data_uri(s)
            .unwrap_or_else(|| PLACEHOLDER_SRC.to_string());
        scan::emit_str(&v, out);
    } else {
        scan::emit_str(PLACEHOLDER_SRC, out);
        // Host-scrubbed too so a CDN host can't leak (crate::assets::apply_blur).
        let stashed =
            crate::url::scrub_url_opts(ctx.allow, s, true).unwrap_or_else(|| s.to_string());
        let key = format!("data-anon-original-{}", std::str::from_utf8(name).ok()?);
        stash.push((key, stashed));
    }
    Some(end)
}

fn attr_scrub(
    ctx: &Ctx<'_>,
    b: &[u8],
    name: &[u8],
    vp: usize,
    out: &mut Vec<u8>,
    changed: &Cell<bool>,
) -> Option<usize> {
    if b.get(vp) != Some(&b'"') {
        return scan::copy_value(b, vp, out);
    }
    if name == b"rr_dataURL" {
        return scrub(b, vp, out, changed, |s, buf| leaf::inline_image_into(ctx, s, buf));
    }
    if is_url_attr(name) {
        return scrub(b, vp, out, changed, |s, buf| leaf::url_into(ctx, s, buf));
    }
    if name == b"style" {
        return scrub(b, vp, out, changed, |s, buf| leaf::css_into(ctx, s, buf));
    }
    if is_user_text_attr(name) {
        return scrub(b, vp, out, changed, |s, buf| leaf::text_into(ctx, s, buf));
    }
    if is_data_attr(name) {
        return scrub(b, vp, out, changed, |s, buf| {
            if data_attr_sensitive(s) {
                leaf::text_into(ctx, s, buf)
            } else {
                leaf::redact_emails_into(s, buf)
            }
        });
    }
    scan::copy_value(b, vp, out)
}

fn scrub<F: FnOnce(&str, &mut String) -> bool>(
    b: &[u8],
    vp: usize,
    out: &mut Vec<u8>,
    changed: &Cell<bool>,
    f: F,
) -> Option<usize> {
    let (e, c) = scan::scrub_string(b, vp, out, f)?;
    changed.set(changed.get() | c);
    Some(e)
}

fn node_kind(b: &[u8], pos: usize) -> Kind {
    match scan::find_member(b, pos, b"tagName") {
        Some(vp) if b.get(vp) == Some(&b'"') => match scan::skip_string(b, vp) {
            Some(end) => classify_bytes(&b[vp + 1..end - 1]),
            None => Kind::Other,
        },
        _ => Kind::Other,
    }
}

fn classify_bytes(tag: &[u8]) -> Kind {
    if tag.eq_ignore_ascii_case(b"script") {
        Kind::Script
    } else if tag.eq_ignore_ascii_case(b"style") {
        Kind::Style
    } else if is_media_tag(tag) {
        Kind::Media
    } else {
        Kind::Other
    }
}

fn is_media_tag(tag: &[u8]) -> bool {
    [
        b"img".as_slice(),
        b"image",
        b"video",
        b"audio",
        b"source",
        b"track",
        b"picture",
    ]
    .iter()
    .any(|t| tag.eq_ignore_ascii_case(t))
}

fn is_url_attr(name: &[u8]) -> bool {
    matches!(
        name,
        b"href"
            | b"src"
            | b"srcset"
            | b"action"
            | b"formaction"
            | b"cite"
            | b"data"
            | b"poster"
            | b"background"
            | b"xlink:href"
            | b"manifest"
            | b"longdesc"
    )
}

fn is_user_text_attr(name: &[u8]) -> bool {
    matches!(
        name,
        b"alt"
            | b"title"
            | b"placeholder"
            | b"aria-label"
            | b"aria-description"
            | b"aria-roledescription"
            | b"aria-valuetext"
            | b"aria-placeholder"
            | b"value"
            | b"label"
            | b"summary"
    )
}

fn is_data_attr(name: &[u8]) -> bool {
    name.starts_with(b"data-") && !name.starts_with(b"data-anon-original-")
}

fn data_attr_sensitive(value: &str) -> bool {
    value.contains('@') || value.chars().any(char::is_whitespace)
}
