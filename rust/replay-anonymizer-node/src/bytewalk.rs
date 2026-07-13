//! Parse-free byte scrub of an event's `data` span: walk the raw JSON,
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

use crate::assets::{is_media_src_attr, INLINE_IMAGE_ATTR, MEDIA_SRC_ATTRS, PLACEHOLDER_SRC};
use crate::blur::{blank_image_data_uri, is_image_data_uri};
use crate::context::Ctx;
use crate::css;
use crate::dom::{
    classify_tag, data_attr_looks_sensitive, is_data_attr, is_url_attr, is_user_text_attr,
    ParentKind, TagKind,
};
use crate::event::{SOURCE_INPUT, SOURCE_MUTATION, TYPE_FULL_SNAPSHOT, TYPE_INCREMENTAL};
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

/// Emit a deferred member's key (with its quotes) plus separators into `out`.
fn emit_deferred_key(bytes: &[u8], key: Span, emitted: &mut usize, out: &mut Vec<u8>) {
    if *emitted > 0 {
        out.push(b',');
    }
    *emitted += 1;
    out.extend_from_slice(&bytes[key.0 - 1..key.1 + 1]);
    out.push(b':');
}

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

type FieldFn<'w, 'c, 'a> =
    dyn FnMut(&mut Walker<'c, 'a>, Span, usize, &mut Vec<u8>) -> Option<usize> + 'w;
type ItemFn<'c, 'a> = dyn FnMut(&mut Walker<'c, 'a>, usize, &mut Vec<u8>) -> Option<usize>;

/// Scrub the `data` span of one event into `out`. `Some(changed)` on success; `None` means
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
    if compressed {
        // Mirrors `route_data`'s cv dispatch: only a snapshot's data string and a mutation's
        // sub-fields are blob-compressed. Snapshot-with-object-data and input fall through to the
        // plain walk (the marker changes nothing there); routes the walk doesn't carry decline.
        match (ty, source) {
            (Some(TYPE_FULL_SNAPSHOT), _) if bytes.get(data.0) == Some(&b'"') => {
                return scrub_cv_snapshot_value(ctx, bytes, data, out);
            }
            (Some(TYPE_INCREMENTAL), Some(SOURCE_MUTATION)) => {
                return scrub_cv_mutation_data(ctx, bytes, data, out);
            }
            (Some(TYPE_FULL_SNAPSHOT), _) | (Some(TYPE_INCREMENTAL), Some(SOURCE_INPUT)) => {}
            _ => return None,
        }
    }
    if bytes.get(data.0) != Some(&b'{') {
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

/// Which gzipped mutation sub-field a decompressed cv payload came from.
#[derive(Clone, Copy)]
pub enum CvMutationField {
    Texts,
    Attributes,
    Adds,
}

/// Scrub a decompressed cv FullSnapshot payload (`bytes` is the whole `data` object) into `out`.
/// `Some(changed)` on success; `None` means "fall back to the parse path" — `out` then holds a
/// partial emission the caller must discard.
pub fn scrub_cv_snapshot(ctx: &Ctx<'_>, bytes: &[u8], out: &mut Vec<u8>) -> Option<bool> {
    let mut w = Walker {
        ctx,
        bytes,
        changed: false,
        depth: 0,
        seen: Vec::with_capacity(64),
    };
    let start = scan::skip_ws(bytes, 0);
    let end = w.walk_object(
        start,
        out,
        &mut |w, key, vstart, out| match &w.bytes[key.0..key.1] {
            b"node" => w.walk_node(vstart, ParentKind::Other, out),
            _ => w.copy_value(vstart, out),
        },
    )?;
    (scan::skip_ws(bytes, end) == bytes.len()).then_some(w.changed)
}

/// Scrub one decompressed cv mutation sub-field (`bytes` is the whole array) into `out`.
/// `Some(changed)` on success; `None` declines to the parse. A non-`[` payload must decline (the
/// parse fails non-arrays closed) rather than hit `walk_array`'s copy-verbatim branch.
pub fn scrub_cv_mutation_field(
    ctx: &Ctx<'_>,
    field: CvMutationField,
    bytes: &[u8],
    out: &mut Vec<u8>,
) -> Option<bool> {
    let start = scan::skip_ws(bytes, 0);
    if bytes.get(start) != Some(&b'[') {
        return None;
    }
    let mut w = Walker {
        ctx,
        bytes,
        changed: false,
        depth: 0,
        seen: Vec::with_capacity(64),
    };
    let end = match field {
        CvMutationField::Texts => w.walk_texts(start, out),
        CvMutationField::Attributes => w.walk_mutation_attributes(start, out),
        CvMutationField::Adds => w.walk_adds(start, out),
    }?;
    (scan::skip_ws(bytes, end) == bytes.len()).then_some(w.changed)
}

/// Scrub a cv-compressed FullSnapshot data string from its still-escaped wire span, skipping the
/// tree path's simd tape and intermediate UTF-8 `String`. Declines (`None`) on anything unexpected;
/// the parse fallback fails malformed streams closed.
fn scrub_cv_snapshot_value(
    ctx: &Ctx<'_>,
    bytes: &[u8],
    data: Span,
    out: &mut Vec<u8>,
) -> Option<bool> {
    if data.1 - data.0 < 2 || bytes.get(data.1 - 1) != Some(&b'"') {
        return None;
    }
    let raw = latin1_from_wire(&bytes[data.0 + 1..data.1 - 1])?;
    let decompressed = ctx.gunzip_cv(&raw).ok()?;
    let mut walked = Vec::with_capacity(decompressed.len() + 64);
    // Unchanged payloads re-emit too: the whole output is zstd, never mixed-format blocks.
    let content = if scrub_cv_snapshot(ctx, &decompressed, &mut walked)? {
        &walked
    } else {
        &decompressed
    };
    let zs = crate::gzip::compress_cv(content).ok()?;
    write_latin1_json_string(&zs, out);
    Some(true)
}

/// The mutation counterpart of [`scrub_cv_snapshot_value`]: envelope keys walk plainly, each
/// gzipped sub-field re-emits per the codec mode.
fn scrub_cv_mutation_data(
    ctx: &Ctx<'_>,
    bytes: &[u8],
    data: Span,
    out: &mut Vec<u8>,
) -> Option<bool> {
    let mut w = Walker {
        ctx,
        bytes,
        changed: false,
        depth: 0,
        seen: Vec::with_capacity(64),
    };
    let end = w.walk_object(
        data.0,
        out,
        &mut |w, key, vstart, out| match &w.bytes[key.0..key.1] {
            b"texts" => w.walk_cv_sub(CvMutationField::Texts, vstart, out),
            b"attributes" => w.walk_cv_sub(CvMutationField::Attributes, vstart, out),
            b"adds" => w.walk_cv_sub(CvMutationField::Adds, vstart, out),
            _ => w.copy_value(vstart, out),
        },
    )?;
    debug_assert_eq!(end, data.1);
    Some(w.changed)
}

/// Decode still-escaped JSON-string bytes of a cv value into latin-1 (compressed) bytes — the
/// wire-side counterpart of `cv::latin1_to_bytes` without the intermediate UTF-8 `String`. `None`
/// on anything outside latin-1-in-JSON (codepoint > 0xFF, bad escape, raw control): the caller
/// declines to the parse, which fails malformed streams closed.
fn latin1_from_wire(wire: &[u8]) -> Option<Vec<u8>> {
    let mut out = Vec::with_capacity(wire.len());
    let mut i = 0;
    while i < wire.len() {
        match wire[i] {
            b'\\' => {
                i += 1;
                match *wire.get(i)? {
                    b'u' => {
                        let (c, used) = scan::decode_unicode(wire, i + 1).ok()?;
                        let cp = c as u32;
                        if cp > 0xFF {
                            return None;
                        }
                        out.push(cp as u8);
                        i += 1 + used;
                    }
                    b'"' => {
                        out.push(b'"');
                        i += 1;
                    }
                    b'\\' => {
                        out.push(b'\\');
                        i += 1;
                    }
                    b'/' => {
                        out.push(b'/');
                        i += 1;
                    }
                    b'b' => {
                        out.push(0x08);
                        i += 1;
                    }
                    b'f' => {
                        out.push(0x0C);
                        i += 1;
                    }
                    b'n' => {
                        out.push(b'\n');
                        i += 1;
                    }
                    b'r' => {
                        out.push(b'\r');
                        i += 1;
                    }
                    b't' => {
                        out.push(b'\t');
                        i += 1;
                    }
                    _ => return None,
                }
            }
            0x00..=0x1F => return None,
            c @ 0x20..=0x7F => {
                out.push(c);
                i += 1;
            }
            lead @ (0xC2 | 0xC3) => {
                let cont = *wire.get(i + 1)?;
                if !(0x80..=0xBF).contains(&cont) {
                    return None;
                }
                out.push(((lead & 0x03) << 6) | (cont & 0x3F));
                i += 2;
            }
            _ => return None,
        }
    }
    Some(out)
}

/// Write-side inverse of [`latin1_from_wire`]: emit compressed bytes as a JSON latin-1 string.
fn write_latin1_json_string(bytes: &[u8], out: &mut Vec<u8>) {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    out.push(b'"');
    for &b in bytes {
        match b {
            b'"' => out.extend_from_slice(b"\\\""),
            b'\\' => out.extend_from_slice(b"\\\\"),
            0x00..=0x1F => {
                out.extend_from_slice(b"\\u00");
                out.push(HEX[(b >> 4) as usize]);
                out.push(HEX[(b & 0xF) as usize]);
            }
            0x20..=0x7F => out.push(b),
            _ => {
                out.push(0xC0 | (b >> 6));
                out.push(0x80 | (b & 0x3F));
            }
        }
    }
    out.push(b'"');
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
        item: &mut ItemFn<'c, 'a>,
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
        item: &mut ItemFn<'c, 'a>,
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

    /// One serialized rrweb node (mirrors `dom::walk_node`), order-independently: capture's
    /// serde round-trip alphabetizes keys, putting `tagName`/`type` AFTER the `childNodes` subtree,
    /// so pre-scanning for them would re-skip every subtree at every level (O(depth x size) — the
    /// profiled 3x collapse). Instead the walk defers the small order-sensitive members as spans
    /// (scalars, `textContent`, the `attributes` object) and emits them once the routing fields are
    /// known — output key order may differ from the input, which the contract (semantic JSON)
    /// permits. `childNodes` is too big to defer, so children emit optimistically as parent=Other;
    /// the rare late script/style discovery splices that segment (those subtrees are tiny), and
    /// shapes the assumptions can't hold for redo the node through the tree scrub locally.
    fn walk_node(&mut self, start: usize, parent: ParentKind, out: &mut Vec<u8>) -> Option<usize> {
        let bytes = self.bytes;
        if bytes.get(start) != Some(&b'{') {
            // Non-object nodes are left untouched by the tree walk.
            return self.copy_value(start, out);
        }
        if self.depth >= MAX_WALK_DEPTH {
            return None;
        }
        self.depth += 1;
        let base = self.seen.len();
        let node_mark = out.len();
        let changed_before = self.changed;
        let result = self.walk_node_inner(base, start, parent, node_mark, changed_before, out);
        self.seen.truncate(base);
        self.depth -= 1;
        result
    }

    #[allow(clippy::too_many_arguments)]
    fn walk_node_inner(
        &mut self,
        base: usize,
        start: usize,
        parent: ParentKind,
        node_mark: usize,
        changed_before: bool,
        out: &mut Vec<u8>,
    ) -> Option<usize> {
        let bytes = self.bytes;
        out.push(b'{');
        let mut emitted = 0usize;
        // Deferred member spans (key span, value span).
        let mut ty_m: Option<(Span, Span)> = None;
        let mut tag_m: Option<(Span, Span)> = None;
        let mut is_style_m: Option<(Span, Span)> = None;
        let mut text_m: Option<(Span, Span)> = None;
        let mut attrs_m: Option<(Span, Span)> = None;
        // childNodes: emitted range in `out` + source span, for the rare late splice.
        let mut children: Option<((usize, usize), Span, Span)> = None;

        let mut pos = start + 1;
        let mut first = true;
        let end = loop {
            pos = scan::skip_ws(bytes, pos);
            if bytes.get(pos) == Some(&b'}') {
                break pos + 1;
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
            // The key cap bounds the per-key duplicate scan below (quadratic in keys otherwise).
            if raw_key.contains(&b'\\') || self.seen.len() - base >= MAX_OBJECT_KEYS {
                return None;
            }
            let prefix = key_prefix(raw_key);
            if self.seen[base..].iter().any(|(prior, prior_prefix)| {
                *prior_prefix == prefix
                    && prior.1 - prior.0 == raw_key.len()
                    && (raw_key.len() <= 8 || &bytes[prior.0..prior.1] == raw_key)
            }) {
                return None;
            }
            self.seen.push((key, prefix));
            pos = scan::skip_ws(bytes, key_end);
            if bytes.get(pos) != Some(&b':') {
                return None;
            }
            let vstart = scan::skip_ws(bytes, pos + 1);
            match raw_key {
                b"type" | b"tagName" | b"isStyle" | b"textContent" | b"attributes" => {
                    let vspan = scan::locate_value(bytes, vstart).ok()?;
                    let slot = match raw_key {
                        b"type" => &mut ty_m,
                        b"tagName" => &mut tag_m,
                        b"isStyle" => &mut is_style_m,
                        b"textContent" => &mut text_m,
                        _ => &mut attrs_m,
                    };
                    *slot = Some((key, vspan));
                    pos = vspan.1;
                }
                b"childNodes" if bytes.get(vstart) == Some(&b'[') => {
                    if emitted > 0 {
                        out.push(b',');
                    }
                    emitted += 1;
                    out.extend_from_slice(&bytes[key.0 - 1..key_end]);
                    out.push(b':');
                    let seg_start = out.len();
                    let vend = self.walk_array(vstart, out, &mut |w, p, o| {
                        w.walk_node(p, ParentKind::Other, o)
                    })?;
                    children = Some(((seg_start, out.len()), (key.0 - 1, key_end), (vstart, vend)));
                    pos = vend;
                }
                _ => {
                    if emitted > 0 {
                        out.push(b',');
                    }
                    emitted += 1;
                    out.extend_from_slice(&bytes[key.0 - 1..key_end]);
                    out.push(b':');
                    pos = self.copy_value(vstart, out)?;
                }
            }
        };

        // Routing fields resolved; decide how the deferred members are treated.
        let ty = ty_m.and_then(|(_, v)| {
            scan::parse_number(bytes, v)
                .and_then(|n| (n.fract() == 0.0 && (0.0..=255.0).contains(&n)).then_some(n as u8))
        });
        let kind = match tag_m {
            Some((_, v)) if scan::is_string(bytes, v) => {
                classify_tag(&scan::unescape(bytes, v).ok()?)
            }
            _ => classify_tag(""),
        };
        let node_changed = self.changed != changed_before;

        match ty {
            Some(NODE_ELEMENT) => {
                if let (TagKind::Script, Some((seg, _, src))) = (kind, children) {
                    // Script content is code — the tree leaves the children untouched.
                    let verbatim = &bytes[src.0..src.1];
                    out.splice(seg.0..seg.1, verbatim.iter().copied());
                }
                if let (TagKind::Style, Some((seg, _, src))) = (kind, children) {
                    // Style children are CSS text: rebuild that segment with the style parent.
                    let mut tmp = Vec::with_capacity(src.1 - src.0);
                    self.walk_array(src.0, &mut tmp, &mut |w, p, o| {
                        w.walk_node(p, ParentKind::Style, o)
                    })?;
                    out.splice(seg.0..seg.1, tmp.iter().copied());
                }
                // Attributes with the real tag kind (media blur vs plain scrubs).
                if let Some((key, v)) = attrs_m {
                    emit_deferred_key(bytes, key, &mut emitted, out);
                    self.walk_attrs(v.0, kind, out)?;
                }
                for (key, v) in [ty_m, tag_m, is_style_m, text_m].into_iter().flatten() {
                    emit_deferred_key(bytes, key, &mut emitted, out);
                    out.extend_from_slice(&bytes[v.0..v.1]);
                }
            }
            Some(NODE_TEXT) if parent == ParentKind::Script => {
                // The tree never touches script text nodes: undo and re-emit verbatim.
                out.truncate(node_mark);
                out.extend_from_slice(&bytes[start..end]);
                self.changed = changed_before;
                return Some(end);
            }
            Some(NODE_TEXT) | Some(NODE_COMMENT) | Some(NODE_CDATA) => {
                if children.map(|(seg, ..)| seg.0 != seg.1).unwrap_or(false) && node_changed {
                    // A text-ish node with scrubbed childNodes has no tree equivalent: redo.
                    return self.redo_node(start, end, parent, node_mark, out);
                }
                let styled = ty == Some(NODE_TEXT)
                    && (parent == ParentKind::Style
                        || is_style_m
                            .map(|(_, v)| bytes.get(v.0..v.1) == Some(b"true"))
                            .unwrap_or(false));
                if let Some((key, v)) = text_m {
                    emit_deferred_key(bytes, key, &mut emitted, out);
                    if styled {
                        self.scrub_string_value(v.0, out, |w, s| css::rewrite(w.ctx, s))?;
                    } else {
                        self.scrub_string_value(v.0, out, |w, s| scrub_text(w.ctx.allow, s))?;
                    }
                }
                for (key, v) in [ty_m, tag_m, is_style_m, attrs_m].into_iter().flatten() {
                    emit_deferred_key(bytes, key, &mut emitted, out);
                    out.extend_from_slice(&bytes[v.0..v.1]);
                }
            }
            Some(NODE_DOCUMENT) => {
                if attrs_m.is_some() {
                    // The tree ignores document attributes but still scrubs the children — no
                    // optimistic emission matches that; let the tree do this node.
                    return self.redo_node(start, end, parent, node_mark, out);
                }
                // Children stay as walked (documents parent as Other); scalars verbatim.
                for (key, v) in [ty_m, tag_m, is_style_m, text_m].into_iter().flatten() {
                    emit_deferred_key(bytes, key, &mut emitted, out);
                    out.extend_from_slice(&bytes[v.0..v.1]);
                }
            }
            // DocumentType/unknown/incompatible shapes: the tree scrubs nothing here. If the
            // optimistic walk changed anything, put the original bytes back; the deferred members
            // re-emit verbatim either way.
            _ => {
                out.truncate(node_mark);
                out.extend_from_slice(&bytes[start..end]);
                self.changed = changed_before;
                return Some(end);
            }
        }
        out.push(b'}');
        Some(end)
    }

    /// Node-local tree fallback: parse just this node's span, scrub it with the real parent kind,
    /// and serialize it over whatever the optimistic walk emitted. Rare (odd node shapes).
    fn redo_node(
        &mut self,
        start: usize,
        end: usize,
        parent: ParentKind,
        node_mark: usize,
        out: &mut Vec<u8>,
    ) -> Option<usize> {
        use simd_json::prelude::Writable;
        out.truncate(node_mark);
        let span = &self.bytes[start..end];
        crate::json::reject_if_too_deep(span, "node").ok()?;
        let mut scratch = span.to_vec();
        let mut value = crate::json::parse_untrusted(&mut scratch).ok()?;
        let changed = crate::dom::walk_node(self.ctx, &mut value, parent);
        self.changed |= changed;
        let mut serialized = Vec::with_capacity(span.len());
        value.write(&mut serialized).ok()?;
        out.extend_from_slice(&serialized);
        Some(end)
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
                if name == "style" || name == css::INLINED_STYLESHEET_ATTR {
                    return w.scrub_string_value(vstart, out, |w, s| css::rewrite(w.ctx, s));
                }
                if is_url_attr(name) {
                    return w.scrub_string_value(vstart, out, |w, s| scrub_url(w.ctx, s));
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
                scrub_url_opts(self.ctx, &existing, true).unwrap_or_else(|| existing.into_owned());
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
            w.walk_object(
                pos,
                out,
                &mut |w, key, vstart, out| match &w.bytes[key.0..key.1] {
                    b"value" => {
                        w.scrub_string_value(vstart, out, |w, s| scrub_text(w.ctx.allow, s))
                    }
                    _ => w.copy_value(vstart, out),
                },
            )
        })
    }

    /// Mutation `attributes`: `[{ id, attributes: {...} }]` (mirrors `scrub_mutation_attributes` —
    /// the media decision comes from the attr names, there is no tag here).
    fn walk_mutation_attributes(&mut self, start: usize, out: &mut Vec<u8>) -> Option<usize> {
        self.walk_array(start, out, &mut |w, pos, out| {
            if w.bytes.get(pos) != Some(&b'{') {
                return w.copy_value(pos, out);
            }
            w.walk_object(
                pos,
                out,
                &mut |w, key, vstart, out| match &w.bytes[key.0..key.1] {
                    b"attributes" if w.bytes.get(vstart) == Some(&b'{') => {
                        // `find_member`'s `Err(Fallback)` (prescan budget / structural surprise)
                        // must decline to the parse, not silently classify as non-media.
                        let mut is_media = false;
                        for a in MEDIA_SRC_ATTRS {
                            if w.find_member(vstart, a.as_bytes()).ok()?.is_some() {
                                is_media = true;
                                break;
                            }
                        }
                        let kind = if is_media {
                            TagKind::Media
                        } else {
                            TagKind::Other
                        };
                        w.walk_attrs(vstart, kind, out)
                    }
                    _ => w.copy_value(vstart, out),
                },
            )
        })
    }

    /// One cv-marked mutation sub-field from the wire: a gzipped string is decoded/walked, a plain
    /// array walks uncompressed, `null`/empty-string keep verbatim, anything else declines.
    fn walk_cv_sub(
        &mut self,
        field: CvMutationField,
        vstart: usize,
        out: &mut Vec<u8>,
    ) -> Option<usize> {
        match self.bytes.get(vstart)? {
            b'[' => match field {
                CvMutationField::Texts => self.walk_texts(vstart, out),
                CvMutationField::Attributes => self.walk_mutation_attributes(vstart, out),
                CvMutationField::Adds => self.walk_adds(vstart, out),
            },
            b'n' => self.copy_value(vstart, out),
            b'"' => {
                let send = scan::skip_string(self.bytes, vstart).ok()?;
                let wire = &self.bytes[vstart + 1..send - 1];
                if wire.is_empty() {
                    out.extend_from_slice(&self.bytes[vstart..send]);
                    return Some(send);
                }
                let raw = latin1_from_wire(wire)?;
                let decompressed = self.ctx.gunzip_cv(&raw).ok()?;
                let mut walked = Vec::with_capacity(decompressed.len() + 64);
                let content =
                    if scrub_cv_mutation_field(self.ctx, field, &decompressed, &mut walked)? {
                        &walked
                    } else {
                        &decompressed
                    };
                let zs = crate::gzip::compress_cv(content).ok()?;
                write_latin1_json_string(&zs, out);
                self.changed = true;
                Some(send)
            }
            _ => None,
        }
    }

    /// Mutation `adds`: `[{ parentId, nextId, node }]` (mirrors `scrub_mutation_adds`).
    fn walk_adds(&mut self, start: usize, out: &mut Vec<u8>) -> Option<usize> {
        self.walk_array(start, out, &mut |w, pos, out| {
            if w.bytes.get(pos) != Some(&b'{') {
                return w.copy_value(pos, out);
            }
            w.walk_object(
                pos,
                out,
                &mut |w, key, vstart, out| match &w.bytes[key.0..key.1] {
                    b"node" => w.walk_node(vstart, ParentKind::Other, out),
                    _ => w.copy_value(vstart, out),
                },
            )
        })
    }
}

#[cfg(test)]
mod tests {
    use super::{latin1_from_wire, write_latin1_json_string};

    #[test]
    fn latin1_wire_codec_round_trips_every_byte() {
        let all: Vec<u8> = (0..=255).collect();
        let mut wire = Vec::new();
        write_latin1_json_string(&all, &mut wire);
        // Strip the quotes the writer adds; the decoder takes the inner span.
        let decoded = latin1_from_wire(&wire[1..wire.len() - 1]).expect("own output decodes");
        assert_eq!(decoded, all);
    }

    #[test]
    fn latin1_wire_decoder_declines_non_latin1() {
        // Codepoint > 0xFF, escaped and raw.
        assert!(latin1_from_wire(br"\u0100").is_none());
        assert!(latin1_from_wire("π".as_bytes()).is_none());
        // Raw control byte: invalid JSON, the parse path must be the one to reject it.
        assert!(latin1_from_wire(b"\x1f").is_none());
        // Truncated escape and truncated two-byte sequence.
        assert!(latin1_from_wire(br"\u00").is_none());
        assert!(latin1_from_wire(b"\xc2").is_none());
    }
}
