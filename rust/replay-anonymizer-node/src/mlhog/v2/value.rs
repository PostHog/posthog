// Bench-only verbatim copy of MLHog prep/labeling/src/v2/value.rs (paths adapted to crate::mlhog).
use std::cell::Cell;

use super::scan;
use crate::mlhog::context::Ctx;
use crate::mlhog::scrub::{text, url};

fn looks_like_url(s: &str) -> bool {
    s.starts_with("http://") || s.starts_with("https://")
}

fn leaf(ctx: &Ctx<'_>, s: &str, buf: &mut String) -> bool {
    if looks_like_url(s) {
        url::scrub_into(ctx, s, buf)
    } else {
        text::scrub_into(ctx, s, buf)
    }
}

pub fn scrub_generic(
    ctx: &Ctx<'_>,
    b: &[u8],
    pos: usize,
    out: &mut Vec<u8>,
    changed: &Cell<bool>,
) -> Option<usize> {
    match b.get(pos) {
        Some(b'"') => {
            let (e, c) = scan::scrub_string(b, pos, out, |s, buf| leaf(ctx, s, buf))?;
            changed.set(changed.get() | c);
            Some(e)
        }
        Some(b'{') => scan::walk_members(b, pos, out, |_, vp, o| scrub_generic(ctx, b, vp, o, changed)),
        Some(b'[') => scan::walk_elements(b, pos, out, |_, vp, o| scrub_generic(ctx, b, vp, o, changed)),
        _ => scan::copy_value(b, pos, out),
    }
}

pub fn scrub_network(
    ctx: &Ctx<'_>,
    b: &[u8],
    pos: usize,
    out: &mut Vec<u8>,
    changed: &Cell<bool>,
) -> Option<usize> {
    if b.get(pos) != Some(&b'{') {
        return scrub_generic(ctx, b, pos, out, changed);
    }
    if scan::find_member(b, pos, b"requests").is_none() {
        return scan::copy_value(b, pos, out);
    }
    scan::walk_members(b, pos, out, |key, vp, o| {
        if key == b"requests" {
            scan::walk_elements(b, vp, o, |_, ep, o| scrub_request(ctx, b, ep, o, changed))
        } else {
            scan::copy_value(b, vp, o)
        }
    })
}

fn scrub_request(
    ctx: &Ctx<'_>,
    b: &[u8],
    pos: usize,
    out: &mut Vec<u8>,
    changed: &Cell<bool>,
) -> Option<usize> {
    scan::walk_members(b, pos, out, |key, vp, o| match key {
        b"name" => scrub_leaf_member(b, vp, o, changed, |s, buf| url::scrub_into(ctx, s, buf)),
        b"requestBody" | b"responseBody" => {
            scrub_leaf_member(b, vp, o, changed, |s, buf| text::scrub_into(ctx, s, buf))
        }
        b"requestHeaders" | b"responseHeaders" => {
            if b.get(vp) == Some(&b'{') {
                scan::walk_members(b, vp, o, |_, hvp, o| {
                    scrub_leaf_member(b, hvp, o, changed, |s, buf| text::scrub_into(ctx, s, buf))
                })
            } else {
                scan::copy_value(b, vp, o)
            }
        }
        _ => scan::copy_value(b, vp, o),
    })
}

pub fn scrub_console(
    ctx: &Ctx<'_>,
    b: &[u8],
    pos: usize,
    out: &mut Vec<u8>,
    changed: &Cell<bool>,
) -> Option<usize> {
    if b.get(pos) != Some(&b'{') {
        return scrub_generic(ctx, b, pos, out, changed);
    }
    scan::walk_members(b, pos, out, |key, vp, o| {
        if key == b"payload" || key == b"trace" {
            scan::walk_elements(b, vp, o, |_, ep, o| {
                scrub_leaf_member(b, ep, o, changed, |s, buf| leaf(ctx, s, buf))
            })
        } else {
            scan::copy_value(b, vp, o)
        }
    })
}

fn scrub_leaf_member<F: FnOnce(&str, &mut String) -> bool>(
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
