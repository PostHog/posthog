//! Parse-free byte scrub of an event's `data` span (the MLHog-v2 architecture): walk the raw JSON,
//! bulk-copy unchanged values verbatim, and re-emit only the strings a scrubber changes — no tree,
//! no dedupe pass, no re-serialization of untouched bytes.
//!
//! Covers the routes that carry the bulk of replay bytes: uncompressed full snapshots, uncompressed
//! mutations, and inputs. Everything else — `cv`-compressed payloads, canvas, meta/custom/plugin —
//! returns `None` and the caller keeps its parse-based path. The scrub *decisions* are shared with
//! the tree walk (`dom::classify_tag`, the attr predicates, `text::scrub_text`, ...), so the two
//! implementations can only disagree on traversal mechanics — which the differential tests pin.
//!
//! Fail-closed: any escaped key, any duplicate key in any object (a byte walker classifying off the
//! first occurrence would diverge from JSON.parse's last-wins and could route content past a
//! scrubber), any object with more keys than the dup check covers, or any structural surprise makes
//! the whole walk return `None` — the caller falls back to the parse, which resolves those exactly.

use crate::assets::{
    is_media_src_attr, INLINE_IMAGE_ATTR, MEDIA_SRC_ATTRS, PLACEHOLDER_SRC,
};
use crate::blur::{blank_image_data_uri, is_image_data_uri};
use crate::context::Ctx;
use crate::css;
use crate::dom::{
    classify_tag, data_attr_looks_sensitive, is_data_attr, is_url_attr, is_user_text_attr,
    ParentKind, TagKind,
};
use crate::event::{
    SOURCE_INPUT, SOURCE_MUTATION, TYPE_FULL_SNAPSHOT, TYPE_INCREMENTAL,
};
use crate::scan::{self, Span};
use crate::text::{redact_emails, scrub_text};
use crate::url::{scrub_url, scrub_url_opts};

// rrweb NodeType (mirrors dom.rs).
const NODE_DOCUMENT: u8 = 0;
const NODE_ELEMENT: u8 = 2;
const NODE_TEXT: u8 = 3;
const NODE_CDATA: u8 = 4;
const NODE_COMMENT: u8 = 5;

/// Per-object duplicate-key coverage; more keys than this falls back (dup safety can't be proven).
const MAX_OBJECT_KEYS: usize = 32;

/// Marker: this event must be handled by the parse instead.
struct Fallback;

/// First 8 bytes of a key as a comparable word (shorter keys zero-padded).
#[inline]
fn key_prefix(key: &[u8]) -> u64 {
    let mut buf = [0u8; 8];
    let n = key.len().min(8);
    buf[..n].copy_from_slice(&key[..n]);
    u64::from_le_bytes(buf)
}

/// Recursion bound for the walk (one count per nested container; real DOM nesting is ~25). Beyond
/// this the event declines to the parse path, whose own span-local depth guard fails it closed —
/// deliberately far below the parse guard's 1024 because walk frames are larger than parse frames.
const MAX_WALK_DEPTH: usize = 256;

struct Walker<'c, 'a> {
    ctx: &'c Ctx<'c>,
    bytes: &'a [u8],
    changed: bool,
    depth: usize,
    /// Duplicate-key scratch shared across the recursion: each object checks its own frame
    /// (`base..`), so there is no per-object array to zero.
    seen: Vec<(Span, u64)>,
}

type FieldFn<'w, 'c, 'a> = dyn FnMut(&mut Walker<'c, 'a>, Span, usize, &mut Vec<u8>) -> Option<usize> + 'w;

/// Scrub the `data` object span of one event into `out`. `Some(changed)` on success; `None` means
/// "fall back to the parse" — the caller must discard whatever was written.
pub fn scrub_data_bytes(
    ctx: &Ctx<'_>,
    ty: Option<u8>,
    source: Option<u8>,
    compressed: bool,
    bytes: &[u8],
    data: Span,
    out: &mut Vec<u8>,
) -> Option<bool> {
    if compressed || bytes.get(data.0) != Some(&b'{') {
        return None;
    }
    let mut w = Walker {
        ctx,
        bytes,
        changed: false,
        depth: 0,
        seen: Vec::with_capacity(64),
    };
    let end = match (ty, source) {
        (Some(TYPE_FULL_SNAPSHOT), _) => w.walk_object(
            data.0,
            out,
            &mut |w, key, vstart, out| match &w.bytes[key.0..key.1] {
                b"node" => w.walk_node(vstart, ParentKind::Other, out),
                _ => w.copy_value(vstart, out),
            },
        )?,
        (Some(TYPE_INCREMENTAL), Some(SOURCE_MUTATION)) => w.walk_object(
            data.0,
            out,
            &mut |w, key, vstart, out| match &w.bytes[key.0..key.1] {
                b"texts" => w.walk_texts(vstart, out),
                b"attributes" => w.walk_mutation_attributes(vstart, out),
                b"adds" => w.walk_adds(vstart, out),
                _ => w.copy_value(vstart, out),
            },
        )?,
        (Some(TYPE_INCREMENTAL), Some(SOURCE_INPUT)) => w.walk_object(
            data.0,
            out,
            &mut |w, key, vstart, out| match &w.bytes[key.0..key.1] {
                b"text" => w.scrub_string_value(vstart, out, |w, s| scrub_text(w.ctx.allow, s)),
                _ => w.copy_value(vstart, out),
            },
        )?,
        _ => return None,
    };
    debug_assert_eq!(end, data.1);
    Some(w.changed)
}

impl<'c, 'a> Walker<'c, 'a> {
    /// Emit-walk the object at `start`: keys verbatim, values via `field`. Detects escaped and
    /// duplicate keys (fallback). Returns the position just past the closing `}`.
    fn walk_object(
        &mut self,
        start: usize,
        out: &mut Vec<u8>,
        field: &mut FieldFn<'_, 'c, 'a>,
    ) -> Option<usize> {
        if self.depth >= MAX_WALK_DEPTH {
            return None;
        }
        self.depth += 1;
        let base = self.seen.len();
        let result = self.walk_object_inner(base, start, out, field);
        self.seen.truncate(base);
        self.depth -= 1;
        result
    }

    fn walk_object_inner(
        &mut self,
        base: usize,
        start: usize,
        out: &mut Vec<u8>,
        field: &mut FieldFn<'_, 'c, 'a>,
    ) -> Option<usize> {
        let bytes = self.bytes;
        if bytes.get(start) != Some(&b'{') {
            return None;
        }
        out.push(b'{');
        let mut nkeys = 0usize;
        let mut pos = start + 1;
        let mut first = true;
        loop {
            pos = scan::skip_ws(bytes, pos);
            if bytes.get(pos) == Some(&b'}') {
                out.push(b'}');
                return Some(pos + 1);
            }
            if !first {
                if bytes.get(pos) != Some(&b',') {
                    return None;
                }
                pos = scan::skip_ws(bytes, pos + 1);
            }
            first = false;
            if bytes.get(pos) != Some(&b'"') {
                return None;
            }
            let key_end = scan::skip_string(bytes, pos).ok()?;
            let key = (pos + 1, key_end - 1);
            let raw_key = &bytes[key.0..key.1];
            if raw_key.contains(&b'\\') || nkeys >= MAX_OBJECT_KEYS {
                return None;
            }
            // Duplicate detection compares (len, 8-byte prefix) first — rrweb keys are short, so
            // the full memcmp only runs for same-length same-prefix pairs.
            let prefix = key_prefix(raw_key);
            if self.seen[base..].iter().any(|(prior, prior_prefix)| {
                *prior_prefix == prefix
                    && prior.1 - prior.0 == raw_key.len()
                    && (raw_key.len() <= 8 || &bytes[prior.0..prior.1] == raw_key)
            }) {
                return None;
            }
            self.seen.push((key, prefix));
            nkeys += 1;
            if nkeys > 1 {
                out.push(b',');
            }
            out.extend_from_slice(&bytes[pos..key_end]); // key incl quotes, verbatim
            out.push(b':');
            pos = scan::skip_ws(bytes, key_end);
            if bytes.get(pos) != Some(&b':') {
                return None;
            }
            let vstart = scan::skip_ws(bytes, pos + 1);
            pos = field(self, key, vstart, out)?;
        }
    }

    /// Emit-walk the array at `start`, items via `item`. Returns the position past the `]`.
    fn walk_array(
        &mut self,
        start: usize,
        out: &mut Vec<u8>,
        item: &mut dyn FnMut(&mut Walker<'c, 'a>, usize, &mut Vec<u8>) -> Option<usize>,
    ) -> Option<usize> {
        if self.depth >= MAX_WALK_DEPTH {
            return None;
        }
        self.depth += 1;
        let result = self.walk_array_inner(start, out, item);
        self.depth -= 1;
        result
    }

    fn walk_array_inner(
        &mut self,
        start: usize,
        out: &mut Vec<u8>,
        item: &mut dyn FnMut(&mut Walker<'c, 'a>, usize, &mut Vec<u8>) -> Option<usize>,
    ) -> Option<usize> {
        let bytes = self.bytes;
        if bytes.get(start) != Some(&b'[') {
            // Not an array: the tree walk leaves it untouched.
            return self.copy_value(start, out);
        }
        out.push(b'[');
        let mut pos = start + 1;
        let mut first = true;
        loop {
            pos = scan::skip_ws(bytes, pos);
            if bytes.get(pos) == Some(&b']') {
                out.push(b']');
                return Some(pos + 1);
            }
            if !first {
                if bytes.get(pos) != Some(&b',') {
                    return None;
                }
                out.push(b',');
                pos = scan::skip_ws(bytes, pos + 1);
            }
            first = false;
            pos = item(self, pos, out)?;
        }
    }

    /// Copy the value at `start` verbatim; returns the position past it.
    fn copy_value(&mut self, start: usize, out: &mut Vec<u8>) -> Option<usize> {
        let span = scan::locate_value(self.bytes, start).ok()?;
        out.extend_from_slice(&self.bytes[span.0..span.1]);
        Some(span.1)
    }

    /// The value at `start`, if it is a string: unescape, apply `scrub`; changed strings re-emit
    /// escaped, unchanged strings copy verbatim (original escapes preserved). Non-strings copy
    /// verbatim (the tree walk only scrubs string values).
    fn scrub_string_value(
        &mut self,
        start: usize,
        out: &mut Vec<u8>,
        scrub: impl FnOnce(&Walker<'c, 'a>, &str) -> Option<String>,
    ) -> Option<usize> {
        let bytes = self.bytes;
        if bytes.get(start) != Some(&b'"') {
            return self.copy_value(start, out);
        }
        let end = scan::skip_string(bytes, start).ok()?;
        let decoded = scan::unescape(bytes, (start, end)).ok()?;
        match scrub(self, &decoded) {
            Some(replacement) => {
                scan::write_json_string(&replacement, out);
                self.changed = true;
            }
            None => out.extend_from_slice(&bytes[start..end]),
        }
        Some(end)
    }

    /// Shallow scan for a member's value span without emitting (order-independent field lookup,
    /// e.g. `type`/`tagName` before deciding how to walk). First occurrence; duplicate keys make
    /// the emit-walk fall back before its result could ever be used.
    ///
    /// Budgeted: real capture bytes put the routing keys (`type`, `tagName`) ahead of the heavy
    /// subtrees (JSON.stringify insertion order), so this normally reads a few dozen bytes. A
    /// producer that reorders keys behind a large container would otherwise make every node's
    /// pre-scan skip its whole subtree — O(depth x size) — so past the budget the event falls back
    /// to the parse instead (`Err`), which is merely slower, never wrong.
    fn find_member(&self, obj_start: usize, name: &[u8]) -> Result<Option<Span>, Fallback> {
        const PRESCAN_BUDGET: usize = 4096;
        let bytes = self.bytes;
        let budget_end = obj_start.saturating_add(PRESCAN_BUDGET);
        let mut pos = obj_start + 1;
        let mut first = true;
        loop {
            pos = scan::skip_ws(bytes, pos);
            if bytes.get(pos) == Some(&b'}') {
                return Ok(None);
            }
            if pos >= budget_end {
                return Err(Fallback);
            }
            if !first {
                if bytes.get(pos) != Some(&b',') {
                    return Ok(None);
                }
                pos = scan::skip_ws(bytes, pos + 1);
            }
            first = false;
            if bytes.get(pos) != Some(&b'"') {
                return Ok(None);
            }
            let key_end = scan::skip_string(bytes, pos).map_err(|_| Fallback)?;
            let key = &bytes[pos + 1..key_end - 1];
            pos = scan::skip_ws(bytes, key_end);
            if bytes.get(pos) != Some(&b':') {
                return Ok(None);
            }
            let vspan = scan::locate_value(bytes, pos + 1).map_err(|_| Fallback)?;
            if key == name {
                return Ok(Some(vspan));
            }
            pos = vspan.1;
        }
    }

    fn find_uint_member(&self, obj_start: usize, name: &[u8]) -> Result<Option<u8>, Fallback> {
        let Some(span) = self.find_member(obj_start, name)? else {
            return Ok(None);
        };
        Ok(scan::parse_number(self.bytes, span)
            .and_then(|n| (n.fract() == 0.0 && (0.0..=u8::MAX as f64).contains(&n)).then_some(n as u8)))
    }

    /// One serialized rrweb node (mirrors `dom::walk_node`).
    fn walk_node(&mut self, start: usize, parent: ParentKind, out: &mut Vec<u8>) -> Option<usize> {
        let bytes = self.bytes;
        if bytes.get(start) != Some(&b'{') {
            // Non-object nodes are left untouched by the tree walk.
            return self.copy_value(start, out);
        }
        let node_type = self.find_uint_member(start, b"type").ok()?;
        match node_type {
            Some(NODE_ELEMENT) => {
                // `tagName` sits before `childNodes` in rrweb output, so this pre-scan is cheap.
                let kind = match self.find_member(start, b"tagName").ok()? {
                    Some(span) if scan::is_string(bytes, span) => {
                        classify_tag(&scan::unescape(bytes, span).ok()?)
                    }
                    _ => classify_tag(""),
                };
                let child_parent = match kind {
                    TagKind::Script => ParentKind::Script,
                    TagKind::Style => ParentKind::Style,
                    TagKind::Media | TagKind::Other => ParentKind::Other,
                };
                self.walk_object(start, out, &mut |w, key, vstart, out| {
                    match &w.bytes[key.0..key.1] {
                        b"attributes" => w.walk_attrs(vstart, kind, out),
                        b"childNodes" => w.walk_array(vstart, out, &mut |w, pos, out| {
                            w.walk_node(pos, child_parent, out)
                        }),
                        _ => w.copy_value(vstart, out),
                    }
                })
            }
            Some(NODE_DOCUMENT) => self.walk_object(start, out, &mut |w, key, vstart, out| {
                match &w.bytes[key.0..key.1] {
                    b"childNodes" => w.walk_array(vstart, out, &mut |w, pos, out| {
                        w.walk_node(pos, ParentKind::Other, out)
                    }),
                    _ => w.copy_value(vstart, out),
                }
            }),
            Some(NODE_TEXT) => {
                // Script content is code — never touched (emit the whole node verbatim).
                if parent == ParentKind::Script {
                    return self.copy_value(start, out);
                }
                let is_style = self
                    .find_member(start, b"isStyle")
                    .ok()?
                    .map(|s| self.bytes.get(s.0..s.1) == Some(b"true"))
                    .unwrap_or(false);
                let styled = parent == ParentKind::Style || is_style;
                self.walk_object(start, out, &mut |w, key, vstart, out| {
                    match &w.bytes[key.0..key.1] {
                        b"textContent" if styled => w.scrub_string_value(vstart, out, |w, s| {
                            css::rewrite(w.ctx, s)
                        }),
                        b"textContent" => {
                            w.scrub_string_value(vstart, out, |w, s| scrub_text(w.ctx.allow, s))
                        }
                        _ => w.copy_value(vstart, out),
                    }
                })
            }
            Some(NODE_COMMENT) | Some(NODE_CDATA) => {
                self.walk_object(start, out, &mut |w, key, vstart, out| {
                    match &w.bytes[key.0..key.1] {
                        b"textContent" => {
                            w.scrub_string_value(vstart, out, |w, s| scrub_text(w.ctx.allow, s))
                        }
                        _ => w.copy_value(vstart, out),
                    }
                })
            }
            // DocumentType or unknown: nothing to scrub.
            _ => self.copy_value(start, out),
        }
    }

    /// An element's `attributes` object (mirrors `dom::scrub_attrs`, including the media blur).
    /// Stash attrs (`data-anon-original-*`) are appended before the closing brace; the tree path
    /// inserts them into the map instead, which is the same object semantically.
    fn walk_attrs(&mut self, start: usize, kind: TagKind, out: &mut Vec<u8>) -> Option<usize> {
        if self.bytes.get(start) != Some(&b'{') {
            return self.copy_value(start, out);
        }
        let mut stashes: Vec<(String, String)> = Vec::new();
        let end = {
            let stashes = &mut stashes;
            self.walk_object(start, out, &mut |w, key, vstart, out| {
                let name = std::str::from_utf8(&w.bytes[key.0..key.1]).ok()?;
                if kind == TagKind::Media && is_media_src_attr(name) {
                    return w.blur_media_src(name, vstart, out, stashes);
                }
                if name == INLINE_IMAGE_ATTR {
                    return w.scrub_string_value(vstart, out, |w, s| {
                        if !is_image_data_uri(s) {
                            return None;
                        }
                        Some(w.ctx.blur_data_uri(s).unwrap_or_else(blank_image_data_uri))
                    });
                }
                if name == "style" {
                    return w.scrub_string_value(vstart, out, |w, s| css::rewrite(w.ctx, s));
                }
                if is_url_attr(name) {
                    return w.scrub_string_value(vstart, out, |w, s| scrub_url(w.ctx.allow, s));
                }
                if is_user_text_attr(name) {
                    return w.scrub_string_value(vstart, out, |w, s| scrub_text(w.ctx.allow, s));
                }
                if is_data_attr(name) {
                    return w.scrub_string_value(vstart, out, |w, s| {
                        if data_attr_looks_sensitive(s) {
                            scrub_text(w.ctx.allow, s)
                        } else {
                            redact_emails(s)
                        }
                    });
                }
                w.copy_value(vstart, out)
            })?
        };
        if !stashes.is_empty() {
            // `end` emission just closed with '}'; reopen to append the stash members.
            debug_assert_eq!(out.last(), Some(&b'}'));
            out.pop();
            for (name, value) in stashes {
                if out.last() != Some(&b'{') {
                    out.push(b',');
                }
                scan::write_json_string(&name, out);
                out.push(b':');
                scan::write_json_string(&value, out);
            }
            out.push(b'}');
        }
        Some(end)
    }

    /// One media source attribute (mirrors `assets::apply_blur` for a single key): data images are
    /// blurred; remote URLs become the placeholder with the host-scrubbed original stashed.
    fn blur_media_src(
        &mut self,
        name: &str,
        vstart: usize,
        out: &mut Vec<u8>,
        stashes: &mut Vec<(String, String)>,
    ) -> Option<usize> {
        let bytes = self.bytes;
        if bytes.get(vstart) != Some(&b'"') {
            // Non-string media source: apply_blur skips it.
            return self.copy_value(vstart, out);
        }
        let end = scan::skip_string(bytes, vstart).ok()?;
        let existing = scan::unescape(bytes, (vstart, end)).ok()?;
        if is_image_data_uri(&existing) {
            let blurred = self
                .ctx
                .blur_data_uri(&existing)
                .unwrap_or_else(|| PLACEHOLDER_SRC.to_string());
            scan::write_json_string(&blurred, out);
        } else {
            let scrubbed =
                scrub_url_opts(self.ctx.allow, &existing, true).unwrap_or_else(|| existing.into_owned());
            scan::write_json_string(PLACEHOLDER_SRC, out);
            stashes.push((format!("data-anon-original-{name}"), scrubbed));
        }
        self.changed = true;
        Some(end)
    }

    /// Mutation `texts`: `[{ id, value }]` — scrub each `value` (mirrors `scrub_mutation_texts`).
    fn walk_texts(&mut self, start: usize, out: &mut Vec<u8>) -> Option<usize> {
        self.walk_array(start, out, &mut |w, pos, out| {
            if w.bytes.get(pos) != Some(&b'{') {
                return w.copy_value(pos, out);
            }
            w.walk_object(pos, out, &mut |w, key, vstart, out| {
                match &w.bytes[key.0..key.1] {
                    b"value" => w.scrub_string_value(vstart, out, |w, s| scrub_text(w.ctx.allow, s)),
                    _ => w.copy_value(vstart, out),
                }
            })
        })
    }

    /// Mutation `attributes`: `[{ id, attributes: {...} }]` (mirrors `scrub_mutation_attributes` —
    /// the media decision comes from the attr names, there is no tag here).
    fn walk_mutation_attributes(&mut self, start: usize, out: &mut Vec<u8>) -> Option<usize> {
        self.walk_array(start, out, &mut |w, pos, out| {
            if w.bytes.get(pos) != Some(&b'{') {
                return w.copy_value(pos, out);
            }
            w.walk_object(pos, out, &mut |w, key, vstart, out| {
                match &w.bytes[key.0..key.1] {
                    b"attributes" if w.bytes.get(vstart) == Some(&b'{') => {
                        let kind = if MEDIA_SRC_ATTRS
                            .iter()
                            .any(|a| matches!(w.find_member(vstart, a.as_bytes()), Ok(Some(_))))
                        {
                            TagKind::Media
                        } else {
                            TagKind::Other
                        };
                        w.walk_attrs(vstart, kind, out)
                    }
                    _ => w.copy_value(vstart, out),
                }
            })
        })
    }

    /// Mutation `adds`: `[{ parentId, nextId, node }]` (mirrors `scrub_mutation_adds`).
    fn walk_adds(&mut self, start: usize, out: &mut Vec<u8>) -> Option<usize> {
        self.walk_array(start, out, &mut |w, pos, out| {
            if w.bytes.get(pos) != Some(&b'{') {
                return w.copy_value(pos, out);
            }
            w.walk_object(pos, out, &mut |w, key, vstart, out| {
                match &w.bytes[key.0..key.1] {
                    b"node" => w.walk_node(vstart, ParentKind::Other, out),
                    _ => w.copy_value(vstart, out),
                }
            })
        })
    }
}
