// Copied (extracted) from MLHog prep/labeling/src/schema.rs — bench-only. Only the items the v2
// byte-scanner needs: the routing enums, the raw-line `scan_event` pass, the byte-skip helpers and
// the cv gzip string codec (libdeflater, as in the original). The v1 typed event tree (serde
// structs, AttrValue, MutationSubScratch consumers, extract_payload/emit_with_payload) is not
// ported. The `serde_repr` derives on the enums are dropped (v2 never (de)serializes them).
#![allow(dead_code)]

use anyhow::{bail, Context, Result};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum EventType {
    DomContentLoaded = 0,
    Load = 1,
    FullSnapshot = 2,
    IncrementalSnapshot = 3,
    Meta = 4,
    Custom = 5,
    Plugin = 6,
}

impl EventType {
    pub const fn from_u8(n: u8) -> Option<Self> {
        Some(match n {
            0 => Self::DomContentLoaded,
            1 => Self::Load,
            2 => Self::FullSnapshot,
            3 => Self::IncrementalSnapshot,
            4 => Self::Meta,
            5 => Self::Custom,
            6 => Self::Plugin,
            _ => return None,
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum IncrementalSource {
    Mutation = 0,
    MouseMove = 1,
    MouseInteraction = 2,
    Scroll = 3,
    ViewportResize = 4,
    Input = 5,
    TouchMove = 6,
    MediaInteraction = 7,
    StyleSheetRule = 8,
    CanvasMutation = 9,
    Font = 10,
    Log = 11,
    Drag = 12,
    StyleDeclaration = 13,
    Selection = 14,
    AdoptedStyleSheet = 15,
    CustomElement = 16,
}

impl IncrementalSource {
    pub const fn from_u8(n: u8) -> Option<Self> {
        Some(match n {
            0 => Self::Mutation,
            1 => Self::MouseMove,
            2 => Self::MouseInteraction,
            3 => Self::Scroll,
            4 => Self::ViewportResize,
            5 => Self::Input,
            6 => Self::TouchMove,
            7 => Self::MediaInteraction,
            8 => Self::StyleSheetRule,
            9 => Self::CanvasMutation,
            10 => Self::Font,
            11 => Self::Log,
            12 => Self::Drag,
            13 => Self::StyleDeclaration,
            14 => Self::Selection,
            15 => Self::AdoptedStyleSheet,
            16 => Self::CustomElement,
            _ => return None,
        })
    }
}

#[derive(Debug, Default)]
pub struct EventScan {
    pub ty: Option<u8>,
    pub source: Option<u8>,
    pub compressed: bool,
    pub data_range: Option<(usize, usize)>,
}

// `event_depth` = depth at which the event object opens. Bare events open
// it at depth 1; the `[window_id, event]` tuple form opens it at depth 2.
// Only matches keys *at* event_depth — nested `"type":` inside `data`
// (e.g. MouseInteractionKind) is correctly ignored.
pub fn scan_event(line: &[u8]) -> EventScan {
    let mut out = EventScan::default();
    let mut pos = 0usize;
    let mut depth = 0u32;
    let mut event_depth: Option<u32> = None;

    while pos < line.len() {
        let b = line[pos];
        match b {
            b'"' => {
                let rest = &line[pos..];
                // `type`, `cv`, `data` are event-object keys (event_depth);
                // `source` lives one level deeper inside `data`. First-match
                // wins handles both cases.
                if event_depth == Some(depth) {
                    if out.ty.is_none() && rest.starts_with(b"\"type\":") {
                        out.ty = read_uint(line, pos + b"\"type\":".len());
                    } else if !out.compressed && rest.starts_with(b"\"cv\":") {
                        // Matches `crate::event::is_compressed_marker`: a null `cv` is not compressed.
                        let mut vp = pos + b"\"cv\":".len();
                        while line.get(vp).is_some_and(|b| b.is_ascii_whitespace()) {
                            vp += 1;
                        }
                        out.compressed = line.get(vp) != Some(&b'n');
                    } else if out.data_range.is_none() && rest.starts_with(b"\"data\":") {
                        out.data_range = locate_value(line, pos + b"\"data\":".len());
                    }
                }
                if out.source.is_none() && rest.starts_with(b"\"source\":") {
                    out.source = read_uint(line, pos + b"\"source\":".len());
                }
                pos = match skip_string(line, pos) {
                    Some(p) => p,
                    None => return out,
                };
            }
            b'{' => {
                depth += 1;
                if event_depth.is_none() {
                    event_depth = Some(depth);
                }
                pos += 1;
            }
            b'[' => {
                depth += 1;
                pos += 1;
            }
            b'}' | b']' => {
                match depth.checked_sub(1) {
                    Some(d) => depth = d,
                    None => return out,
                }
                pos += 1;
            }
            _ => pos += 1,
        }
    }
    out
}

pub fn data_value_range(line: &[u8]) -> Option<(usize, usize)> {
    scan_event(line).data_range
}

pub(crate) fn read_uint(line: &[u8], mut pos: usize) -> Option<u8> {
    while line.get(pos) == Some(&b' ') {
        pos += 1;
    }
    let mut n: u32 = 0;
    let mut saw = false;
    while let Some(&b) = line.get(pos) {
        if b.is_ascii_digit() {
            n = n * 10 + u32::from(b - b'0');
            saw = true;
            pos += 1;
        } else {
            break;
        }
    }
    saw.then_some(n as u8)
}

pub(crate) fn locate_value(line: &[u8], mut start: usize) -> Option<(usize, usize)> {
    while start < line.len() && line[start].is_ascii_whitespace() {
        start += 1;
    }
    let end = match *line.get(start)? {
        b'"' => skip_string(line, start)?,
        b'{' => skip_balanced(line, start, b'{', b'}')?,
        b'[' => skip_balanced(line, start, b'[', b']')?,
        _ => skip_scalar(line, start),
    };
    Some((start, end))
}

pub(crate) fn skip_string(line: &[u8], start: usize) -> Option<usize> {
    debug_assert_eq!(line[start], b'"');
    let mut pos = start + 1;
    while pos < line.len() {
        match line[pos] {
            b'\\' if pos + 1 < line.len() => pos += 2,
            b'"' => return Some(pos + 1),
            _ => pos += 1,
        }
    }
    None
}

pub(crate) fn skip_balanced(line: &[u8], start: usize, open: u8, close: u8) -> Option<usize> {
    debug_assert_eq!(line[start], open);
    let mut depth: u32 = 0;
    let mut pos = start;
    while pos < line.len() {
        let b = line[pos];
        if b == b'"' {
            pos = skip_string(line, pos)?;
            continue;
        }
        if b == open {
            depth += 1;
        } else if b == close {
            depth -= 1;
            if depth == 0 {
                return Some(pos + 1);
            }
        }
        pos += 1;
    }
    None
}

pub(crate) fn skip_scalar(line: &[u8], start: usize) -> usize {
    let mut pos = start;
    while pos < line.len() {
        let b = line[pos];
        if matches!(b, b',' | b'}' | b']') || b.is_ascii_whitespace() {
            return pos;
        }
        pos += 1;
    }
    pos
}

// Wire format: each gzip byte stored as its U+00XX codepoint (latin-1),
// then JSON-string-escaped.
std::thread_local! {
    static RAW: std::cell::RefCell<Vec<u8>> = const { std::cell::RefCell::new(Vec::new()) };
}

// Decode a cv `data` JSON string body (escaped latin-1 gzip codepoints) straight to gzip bytes, in
// one pass — no simd parse, no intermediate String, no per-event clone. `0x80..=0xFF` bytes are
// stored as 2-byte UTF-8; control bytes as `\u00xx`.
fn latin1_from_json(inner: &[u8], dst: &mut Vec<u8>) -> Result<()> {
    dst.reserve(inner.len());
    let mut i = 0;
    while i < inner.len() {
        match inner[i] {
            b'\\' => {
                let e = *inner.get(i + 1).context("truncated escape")?;
                match e {
                    b'"' => dst.push(b'"'),
                    b'\\' => dst.push(b'\\'),
                    b'/' => dst.push(b'/'),
                    b'b' => dst.push(0x08),
                    b'f' => dst.push(0x0c),
                    b'n' => dst.push(b'\n'),
                    b'r' => dst.push(b'\r'),
                    b't' => dst.push(b'\t'),
                    b'u' => {
                        let cp = hex4(inner, i + 2)?;
                        if cp > 0xFF {
                            bail!("codepoint U+{cp:04X} > 0xFF in latin-1 gzip stream");
                        }
                        dst.push(cp as u8);
                        i += 4;
                    }
                    _ => bail!("bad JSON escape"),
                }
                i += 2;
            }
            c @ 0x00..=0x7f => {
                dst.push(c);
                i += 1;
            }
            c @ 0xc0..=0xdf => {
                let c2 = *inner.get(i + 1).context("truncated utf-8")?;
                let cp = ((c as u32 & 0x1f) << 6) | (c2 as u32 & 0x3f);
                if cp > 0xFF {
                    bail!("codepoint U+{cp:04X} > 0xFF in latin-1 gzip stream");
                }
                dst.push(cp as u8);
                i += 2;
            }
            other => bail!("unexpected byte {other:#x} in latin-1 gzip string"),
        }
    }
    Ok(())
}

fn hex4(b: &[u8], i: usize) -> Result<u16> {
    let mut v = 0u16;
    for k in 0..4 {
        let d = (*b.get(i + k).context("truncated \\u")? as char)
            .to_digit(16)
            .context("bad hex digit")?;
        v = v << 4 | d as u16;
    }
    Ok(v)
}

// As in the original: one level-6 gzip member via libdeflate's one-shot compressor.
fn gzip_compress(payload: &[u8]) -> Result<Vec<u8>> {
    let mut enc = libdeflater::Compressor::new(
        libdeflater::CompressionLvl::new(6).expect("6 is a valid deflate level"),
    );
    let mut out = vec![0u8; enc.gzip_compress_bound(payload.len())];
    let n = enc
        .gzip_compress(payload, &mut out)
        .map_err(|e| anyhow::anyhow!("gzip compress: {e:?}"))?;
    out.truncate(n);
    Ok(out)
}

// As in the original: the gzip trailer's ISIZE (uncompressed size mod 2^32, little-endian) sizes
// the one-shot output buffer; output is appended to `dst`.
fn gzip_decompress_into(raw: &[u8], dst: &mut Vec<u8>) -> Result<()> {
    if raw.len() < 4 {
        bail!("gzip stream too short");
    }
    let n = raw.len();
    let out_len = u32::from_le_bytes([raw[n - 4], raw[n - 3], raw[n - 2], raw[n - 1]]) as usize;
    let base = dst.len();
    dst.resize(base + out_len, 0);
    let written = libdeflater::Decompressor::new()
        .gzip_decompress(raw, &mut dst[base..])
        .map_err(|e| anyhow::anyhow!("gunzip: {e:?}"))?;
    dst.truncate(base + written);
    Ok(())
}

pub fn decompress_string_into(quoted: &[u8], dst: &mut Vec<u8>) -> Result<()> {
    if quoted.len() < 2 || quoted[0] != b'"' || quoted[quoted.len() - 1] != b'"' {
        bail!("compressed `data` is not a JSON string");
    }
    let inner = &quoted[1..quoted.len() - 1];
    RAW.with(|cell| {
        let mut raw = cell.borrow_mut();
        raw.clear();
        latin1_from_json(inner, &mut raw)?;
        crate::mlhog::timed!(crate::metrics::GZIP_DEC_NS, gzip_decompress_into(&raw, dst))
            .context("gunzip cv data")
    })
}

pub(crate) fn write_compressed_string(payload: &[u8], out: &mut Vec<u8>) -> Result<()> {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let zipped = crate::mlhog::timed!(crate::metrics::GZIP_ENC_NS, gzip_compress(payload))?;
    out.reserve(zipped.len() * 2 + 2);
    out.push(b'"');
    for &b in &zipped {
        match b {
            b'"' => out.extend_from_slice(b"\\\""),
            b'\\' => out.extend_from_slice(b"\\\\"),
            0x08 => out.extend_from_slice(b"\\b"),
            0x0c => out.extend_from_slice(b"\\f"),
            b'\n' => out.extend_from_slice(b"\\n"),
            b'\r' => out.extend_from_slice(b"\\r"),
            b'\t' => out.extend_from_slice(b"\\t"),
            0x00..=0x1f => {
                out.extend_from_slice(&[b'\\', b'u', b'0', b'0', HEX[(b >> 4) as usize], HEX[(b & 0xf) as usize]]);
            }
            0x80..=0xff => {
                out.push(0xc0 | (b >> 6));
                out.push(0x80 | (b & 0x3f));
            }
            _ => out.push(b),
        }
    }
    out.push(b'"');
    Ok(())
}

pub fn decompress_subfield_into(s: &str, dst: &mut Vec<u8>) -> Result<()> {
    let mut raw: Vec<u8> = Vec::with_capacity(s.len());
    for c in s.chars() {
        let cp = c as u32;
        if cp > 0xFF {
            bail!("codepoint U+{cp:04X} > 0xFF in latin-1 gzip stream");
        }
        raw.push(cp as u8);
    }
    crate::mlhog::timed!(crate::metrics::GZIP_DEC_NS, gzip_decompress_into(&raw, dst))
        .context("gunzip sub-field")?;
    Ok(())
}
