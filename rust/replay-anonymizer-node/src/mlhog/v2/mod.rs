// Ported from MLHog prep/labeling/src/v2/mod.rs — bench-only. Adapted: leaf scrubs go through
// `crate::mlhog::leaf` (this crate's parity-locked scrubbers); routing is aligned with
// `crate::event::route_data` (missing `data` passes through, the `cv` marker gates compressed
// handling, canvas honors the commands-vs-flattened split); the `#[cfg(test)] mod tests` v1↔v2
// parity suite is not ported (parity is asserted against this crate in tests/mlhog_parity.rs).

//! Parse-free byte-scanning anonymizer. Scans the raw JSON (and decompressed cv payloads), splices
//! scrubbed values in place, and never builds a struct tree. Routing and leaf scrubs match
//! `crate::event::route_data`; only the traversal architecture differs.

mod canvas;
mod dom;
mod scan;
mod value;

use std::cell::Cell;

use crate::context::Ctx;
use crate::mlhog::leaf;
use crate::mlhog::schema::{self, EventType as E, IncrementalSource as S};

#[derive(Default)]
pub struct V2Worker {
    tmp: Vec<u8>,
    dec: Vec<u8>,
    dec2: Vec<u8>,
    tmp2: Vec<u8>,
}

impl V2Worker {
    pub fn scrub_line(&mut self, ctx: &Ctx<'_>, line: &[u8], out: &mut Vec<u8>) {
        self.scrub_line_scanned(ctx, line, schema::scan_event(line), out)
    }

    /// [`Self::scrub_line`] with the routing scan supplied by the caller — an integration that has
    /// already scanned the event (for span discovery or metadata) hands its results over instead of
    /// paying `schema::scan_event` a second time.
    pub fn scrub_line_scanned(
        &mut self,
        ctx: &Ctx<'_>,
        line: &[u8],
        scan: schema::EventScan,
        out: &mut Vec<u8>,
    ) {
        let mark = out.len();
        if self.dispatch(ctx, line, scan, out).is_none() {
            out.truncate(mark);
        }
    }

    fn dispatch(
        &mut self,
        ctx: &Ctx<'_>,
        line: &[u8],
        scan: schema::EventScan,
        out: &mut Vec<u8>,
    ) -> Option<()> {
        let ty = scan.ty.and_then(E::from_u8);
        let source = scan.source.and_then(S::from_u8);

        // route_data: an event without a `data` member is passed through unchanged.
        if scan.data_range.is_none() {
            out.extend_from_slice(line);
            return Some(());
        }

        match (ty, source) {
            (Some(E::IncrementalSnapshot), Some(S::CanvasMutation)) => {
                self.splice(line, scan, out, |b, ds, o| canvas::transform(ctx, b, ds, o))
            }
            (Some(E::FullSnapshot), _) => self.full_snapshot(ctx, line, scan, out),
            (Some(E::IncrementalSnapshot), Some(S::Mutation)) => self.mutation(ctx, line, scan, out),
            (Some(E::IncrementalSnapshot), Some(S::Input)) => {
                self.splice(line, scan, out, |b, ds, o| transform_input(ctx, b, ds, o))
            }
            (Some(E::Meta), _) => {
                self.splice(line, scan, out, |b, ds, o| transform_meta(ctx, b, ds, o))
            }
            (Some(E::Custom), _) => {
                self.splice(line, scan, out, |b, ds, o| transform_custom(ctx, b, ds, o))
            }
            (Some(E::Plugin), _) => {
                self.splice(line, scan, out, |b, ds, o| transform_plugin(ctx, b, ds, o))
            }
            _ => {
                out.extend_from_slice(line);
                Some(())
            }
        }
    }

    // Transform the object `data` value into `self.tmp`; emit the line verbatim if unchanged, else
    // `line[..ds] + tmp + line[de..]`.
    fn splice<T: FnOnce(&[u8], usize, &mut Vec<u8>) -> Option<bool>>(
        &mut self,
        line: &[u8],
        scan: schema::EventScan,
        out: &mut Vec<u8>,
        transform: T,
    ) -> Option<()> {
        let (ds, de) = scan.data_range?;
        self.tmp.clear();
        if transform(line, ds, &mut self.tmp)? {
            out.extend_from_slice(&line[..ds]);
            out.extend_from_slice(&self.tmp);
            out.extend_from_slice(&line[de..]);
        } else {
            out.extend_from_slice(line);
        }
        Some(())
    }

    fn full_snapshot(
        &mut self,
        ctx: &Ctx<'_>,
        line: &[u8],
        scan: schema::EventScan,
        out: &mut Vec<u8>,
    ) -> Option<()> {
        let (ds, de) = scan.data_range?;
        // route_data: only a string `data` under a non-null `cv` marker is whole-blob compressed;
        // anything else scrubs as a plain object.
        if !scan.compressed || line.get(ds) != Some(&b'"') {
            return self.splice(line, scan, out, |b, ds, o| transform_full_payload(ctx, b, ds, o));
        }
        let V2Worker { dec, tmp, .. } = &mut *self;
        dec.clear();
        schema::decompress_string_into(&line[ds..de], dec).ok()?;
        tmp.clear();
        if transform_full_payload(ctx, dec, 0, tmp)? {
            out.extend_from_slice(&line[..ds]);
            schema::write_compressed_string(tmp, out).ok()?;
            out.extend_from_slice(&line[de..]);
        } else {
            out.extend_from_slice(line);
        }
        Some(())
    }

    fn mutation(
        &mut self,
        ctx: &Ctx<'_>,
        line: &[u8],
        scan: schema::EventScan,
        out: &mut Vec<u8>,
    ) -> Option<()> {
        let (ds, de) = scan.data_range?;
        let compressed = scan.compressed;
        let V2Worker { tmp, dec, dec2, tmp2, .. } = &mut *self;
        tmp.clear();
        let changed = Cell::new(false);
        scan::walk_members(line, ds, tmp, |key, vp, o| {
            let field = match key {
                b"texts" => Field::Texts,
                b"attributes" => Field::Attrs,
                b"adds" => Field::Adds,
                _ => return scan::copy_value(line, vp, o),
            };
            transform_subfield(ctx, line, vp, o, field, &changed, compressed, dec, dec2, tmp2)
        })?;
        if changed.get() {
            out.extend_from_slice(&line[..ds]);
            out.extend_from_slice(tmp);
            out.extend_from_slice(&line[de..]);
        } else {
            out.extend_from_slice(line);
        }
        Some(())
    }
}

#[derive(Clone, Copy)]
enum Field {
    Texts,
    Attrs,
    Adds,
}

// A Mutation sub-field: a gzipped string (cv, only when the event carries the `cv` marker —
// matching `route_data`) or a plain array. Decompress if needed, transform the array, recompress if
// it arrived compressed. Without the marker a string sub-field is copied verbatim, like
// `crate::dom::scrub_mutation`.
#[allow(clippy::too_many_arguments)]
fn transform_subfield(
    ctx: &Ctx<'_>,
    b: &[u8],
    vp: usize,
    out: &mut Vec<u8>,
    field: Field,
    changed: &Cell<bool>,
    compressed: bool,
    dec: &mut Vec<u8>,
    _dec2: &mut Vec<u8>,
    tmp2: &mut Vec<u8>,
) -> Option<usize> {
    if !compressed || b.get(vp) != Some(&b'"') {
        return transform_field_array(ctx, b, vp, out, field, changed);
    }
    let mut owned = String::new();
    let (s, end) = scan::string_str(b, vp, &mut owned)?;
    if s.is_empty() {
        out.extend_from_slice(&b[vp..end]);
        return Some(end);
    }
    dec.clear();
    schema::decompress_subfield_into(s, dec).ok()?;
    tmp2.clear();
    let sub_changed = Cell::new(false);
    transform_field_array(ctx, dec, 0, tmp2, field, &sub_changed)?;
    if sub_changed.get() {
        changed.set(true);
        schema::write_compressed_string(tmp2, out).ok()?;
    } else {
        out.extend_from_slice(&b[vp..end]);
    }
    Some(end)
}

fn transform_field_array(
    ctx: &Ctx<'_>,
    b: &[u8],
    pos: usize,
    out: &mut Vec<u8>,
    field: Field,
    changed: &Cell<bool>,
) -> Option<usize> {
    scan::walk_elements(b, pos, out, |_, ep, o| match field {
        Field::Texts => scan::walk_members(b, ep, o, |k, vp, o| {
            if k == b"value" {
                let (e, c) = scan::scrub_string(b, vp, o, |s, buf| leaf::text_into(ctx, s, buf))?;
                changed.set(changed.get() | c);
                Some(e)
            } else {
                scan::copy_value(b, vp, o)
            }
        }),
        Field::Attrs => scan::walk_members(b, ep, o, |k, vp, o| {
            if k == b"attributes" {
                let media = dom::has_media_src_attr(b, vp);
                dom::walk_attrs(ctx, b, vp, o, media, changed)
            } else {
                scan::copy_value(b, vp, o)
            }
        }),
        Field::Adds => scan::walk_members(b, ep, o, |k, vp, o| {
            if k == b"node" {
                dom::walk_node(ctx, b, vp, o, dom::Parent::Other, changed)
            } else {
                scan::copy_value(b, vp, o)
            }
        }),
    })
}

fn transform_meta(ctx: &Ctx<'_>, b: &[u8], ds: usize, out: &mut Vec<u8>) -> Option<bool> {
    let changed = Cell::new(false);
    scan::walk_members(b, ds, out, |key, vp, o| {
        if key == b"href" {
            let (e, c) = scan::scrub_string(b, vp, o, |s, buf| leaf::url_authority_into(ctx, s, buf))?;
            changed.set(changed.get() | c);
            Some(e)
        } else {
            scan::copy_value(b, vp, o)
        }
    })?;
    Some(changed.get())
}

fn transform_input(ctx: &Ctx<'_>, b: &[u8], ds: usize, out: &mut Vec<u8>) -> Option<bool> {
    let changed = Cell::new(false);
    scan::walk_members(b, ds, out, |key, vp, o| {
        if key == b"text" {
            let (e, c) = scan::scrub_string(b, vp, o, |s, buf| leaf::text_into(ctx, s, buf))?;
            changed.set(changed.get() | c);
            Some(e)
        } else {
            scan::copy_value(b, vp, o)
        }
    })?;
    Some(changed.get())
}

fn transform_full_payload(ctx: &Ctx<'_>, b: &[u8], ds: usize, out: &mut Vec<u8>) -> Option<bool> {
    let changed = Cell::new(false);
    scan::walk_members(b, ds, out, |key, vp, o| {
        if key == b"node" {
            dom::walk_node(ctx, b, vp, o, dom::Parent::Other, &changed)
        } else {
            scan::copy_value(b, vp, o)
        }
    })?;
    Some(changed.get())
}

fn transform_custom(ctx: &Ctx<'_>, b: &[u8], ds: usize, out: &mut Vec<u8>) -> Option<bool> {
    let changed = Cell::new(false);
    scan::walk_members(b, ds, out, |key, vp, o| {
        if key == b"payload" {
            value::scrub_generic(ctx, b, vp, o, &changed)
        } else {
            scan::copy_value(b, vp, o)
        }
    })?;
    Some(changed.get())
}

fn transform_plugin(ctx: &Ctx<'_>, b: &[u8], ds: usize, out: &mut Vec<u8>) -> Option<bool> {
    let plugin = scan::find_member(b, ds, b"plugin").and_then(|p| {
        let mut owned = String::new();
        scan::string_str(b, p, &mut owned).map(|(s, _)| s.to_string())
    });
    let changed = Cell::new(false);
    scan::walk_members(b, ds, out, |key, vp, o| {
        if key == b"payload" {
            match plugin.as_deref() {
                Some("rrweb/network@1") => value::scrub_network(ctx, b, vp, o, &changed),
                Some("rrweb/console@1") => value::scrub_console(ctx, b, vp, o, &changed),
                _ => value::scrub_generic(ctx, b, vp, o, &changed),
            }
        } else {
            scan::copy_value(b, vp, o)
        }
    })?;
    Some(changed.get())
}
