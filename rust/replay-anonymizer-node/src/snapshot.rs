//! Anonymize one decompressed replay Kafka payload end-to-end: Rust owns the parse, the scrub, and
//! the serialize (the byte-buffer FFI shape). The TS consumer hands over the raw payload bytes and
//! gets back ready-to-write JSONL block lines plus the envelope/per-event metadata its batching
//! scaffolding needs — no JSON crosses the FFI boundary as a string in either direction.
//!
//! Two implementations produce the output:
//!
//! - **Streaming** (`scan_envelope` + `process_event`): scans the payload bytes for the
//!   `$snapshot_items` spans, memcpys pass-through events verbatim, and parses only the `data` span
//!   of scrub-routed events, splicing the rewritten span back between the untouched bytes. This is
//!   the hot path.
//! - **Tree** (`anonymize_via_tree`): parses the whole payload and walks it. It is the reference the
//!   differential tests check the streaming path against, and the production fallback whenever the
//!   scanner meets something it cannot prove safe (escaped keys, duplicate routing keys) — JSON.parse
//!   semantics like last-duplicate-wins and escape normalization only fall out of a real parse.
//!
//! Both paths share `route_data` (the single routing/scrub implementation) and the meta extraction
//! helpers, so they can only disagree on envelope/iteration mechanics — which is exactly what the
//! differential tests pin down.
//!
//! Fail-closed: any scrub error, or any input the scanner *and* the tree path cannot make sense of,
//! is an error — the caller drops (or DLQs) the message rather than letting un-anonymized bytes
//! through.

use serde::Serialize;
use simd_json::borrowed::Value;
use simd_json::prelude::Writable;

use crate::allow_lists::AllowLists;
use crate::context::Ctx;
use crate::event::{
    route_data, route_event, SOURCE_CANVAS_MUTATION, SOURCE_INPUT, SOURCE_MUTATION, TYPE_CUSTOM,
    TYPE_FULL_SNAPSHOT, TYPE_INCREMENTAL, TYPE_META, TYPE_PLUGIN,
};
use crate::json::{
    as_f64, as_object, as_small_uint, as_str, parse_untrusted, parse_untrusted_with_buffers,
    reject_if_too_deep,
};
use crate::scan::{self, Span};

/// Why a payload could not be anonymized; maps onto the TS pipeline's dlq/drop reasons so the fused
/// step classifies failures exactly like the TS parse step does.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FailKind {
    /// The Kafka message value could not be decompressed (dlq `invalid_compressed_data`).
    InvalidCompressedData,
    /// The outer Kafka payload is not valid JSON (dlq `invalid_json`).
    InvalidJson,
    /// The outer payload parses but lacks `distinct_id`/`data` strings (dlq `invalid_message_payload`).
    InvalidMessagePayload,
    /// The inner event is not a `$snapshot_items` message (dlq `received_non_snapshot_message`).
    NonSnapshotMessage,
    /// Every event was filtered out (drop `message_contained_no_valid_rrweb_events`).
    NoValidEvents,
    /// An event could not be scrubbed — fail closed (drop `anonymize_failed`).
    AnonymizeFailed,
}

impl FailKind {
    pub fn reason(self) -> &'static str {
        match self {
            FailKind::InvalidCompressedData => "invalid_compressed_data",
            FailKind::InvalidJson => "invalid_json",
            FailKind::InvalidMessagePayload => "invalid_message_payload",
            FailKind::NonSnapshotMessage => "received_non_snapshot_message",
            FailKind::NoValidEvents => "message_contained_no_valid_rrweb_events",
            FailKind::AnonymizeFailed => "anonymize_failed",
        }
    }
}

#[derive(Debug)]
pub struct Failure {
    pub kind: FailKind,
    pub detail: String,
}

impl Failure {
    fn new(kind: FailKind, detail: impl Into<String>) -> Self {
        Self {
            kind,
            detail: detail.into(),
        }
    }
}

type SResult<T> = Result<T, Failure>;

// Per-event flags, mirroring `rrweb-types.ts` / `segmentation.ts` predicates.
pub const FLAG_ACTIVE: u8 = 1;
pub const FLAG_CLICK: u8 = 2;
pub const FLAG_KEYPRESS: u8 = 4;
pub const FLAG_MOUSE_ACTIVITY: u8 = 8;

// `DateTime.fromMillis` validity bound (JS Date range: ±8.64e15 ms).
const MAX_JS_DATE_MS: f64 = 8.64e15;

/// Per-emitted-line metadata, in line order.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct EventMeta {
    /// The event's `timestamp` (epoch ms; can be fractional).
    pub ts: f64,
    /// Bitmask of FLAG_ACTIVE / FLAG_CLICK / FLAG_KEYPRESS / FLAG_MOUSE_ACTIVITY.
    pub flags: u8,
    /// Post-scrub `hrefFrom(event)` (`data.href` or `data.payload.href`, trimmed, non-empty).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub href: Option<String>,
}

/// Message envelope + per-event metadata the TS scaffolding needs for routing/batching.
#[derive(Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SnapshotMeta {
    pub distinct_id: String,
    /// Raw `$session_id` (normalization stays in TS).
    pub session_id: String,
    /// `$window_id ?? ''`.
    pub window_id: String,
    pub snapshot_source: Option<String>,
    pub snapshot_library: Option<String>,
    /// Min/max valid-event timestamps (epoch ms).
    pub start_ts: f64,
    pub end_ts: f64,
    /// rrweb/console@1 plugin events by level, for the console-log block metadata counts.
    pub console_log_count: u32,
    pub console_warn_count: u32,
    pub console_error_count: u32,
    pub events: Vec<EventMeta>,
}

/// Which implementation produced the output. Both are differential-tested identical, so routing is
/// free to choose per message; the label feeds the canary metrics that tune the routing threshold.
/// Deliberately not part of [`SnapshotMeta`]: the differential tests assert meta equality across
/// paths.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Route {
    Stream,
    Tree,
}

impl Route {
    pub fn as_str(self) -> &'static str {
        match self {
            Route::Stream => "stream",
            Route::Tree => "tree",
        }
    }
}

/// Options for the anonymize entry points. `Default` is the production configuration.
#[derive(Debug, Clone, Copy)]
pub struct AnonymizeOpts {
    /// Route snapshot-dominated messages through the tree path (one SIMD parse of everything beats
    /// streaming's scan+parse duplication when most bytes get parsed anyway). The differential
    /// tests turn this off so the streaming path is the one being exercised.
    pub adaptive_routing: bool,
    /// Scrub the bulk routes (snapshots, mutations, inputs) with the parse-free byte walk
    /// ([`crate::bytewalk`]) instead of a simd-json tree; anything the walk can't prove safe falls
    /// back to the parse per event.
    pub byte_walk: bool,
}

impl Default for AnonymizeOpts {
    fn default() -> Self {
        Self {
            adaptive_routing: true,
            byte_walk: true,
        }
    }
}

#[derive(Debug)]
pub struct AnonymizedMessage {
    /// Scrubbed JSONL: one `["<windowId>",<event>]\n` line per valid event, in input order.
    pub lines: Vec<u8>,
    pub meta: SnapshotMeta,
    pub route: Route,
}

/// Decompressed payloads are capped (shared with the gzip codec's bomb cap) so a forged lz4 size
/// prefix (a u32, so up to 4 GiB) cannot force the allocation; real replay payloads decompress to
/// tens of MB at most.
const MAX_DECOMPRESSED_LEN: usize = crate::gzip::MAX_DECOMPRESSED_BYTES;

const GZIP_MAGIC: &[u8; 4] = &[0x1f, 0x8b, 0x08, 0x00];

/// Decompress a raw Kafka message value the way capture wraps it (mirrors the TS
/// `decompressMessageValue`): lz4 block with a 4-byte LE uncompressed-size prefix when the
/// `content-encoding` header says lz4, gzip when the magic bytes say so, else pass through.
pub fn decompress_payload(raw: Vec<u8>, content_encoding: Option<&str>) -> SResult<Vec<u8>> {
    let bad = |detail: &str| Failure::new(FailKind::InvalidCompressedData, detail);
    if content_encoding == Some("lz4") {
        let size_bytes: [u8; 4] = raw
            .get(..4)
            .and_then(|b| b.try_into().ok())
            .ok_or_else(|| bad("lz4 payload too short for size prefix"))?;
        let size = u32::from_le_bytes(size_bytes) as usize;
        if size > MAX_DECOMPRESSED_LEN {
            return Err(bad("lz4 uncompressed size exceeds limit"));
        }
        return lz4::block::decompress(&raw[4..], Some(size as i32))
            .map_err(|e| bad(&format!("lz4 decompress failed: {e}")));
    }
    if raw.starts_with(GZIP_MAGIC) {
        return crate::gzip::gunzip(&raw).map_err(|e| bad(&format!("gzip decompress failed: {e}")));
    }
    Ok(raw)
}

/// Anonymize a decompressed replay Kafka payload (`{"distinct_id": ..., "data": "<event json>"}`).
/// The buffer is scratch space — the fallback parse unescapes strings in place.
///
/// The envelope is scanned, not parsed: a full parse funnels the multi-MB `data` string through
/// simd-json's tape just to unescape it, where the scan locates the two values and unescapes `data`
/// in one memchr-accelerated pass. Anything the scanner can't prove out (escaped or duplicate keys,
/// structural surprises) falls back to the parse, which also owns failure classification — so
/// dlq/drop reasons for malformed payloads come out exactly as before.
pub fn anonymize_kafka_payload(
    allow: &AllowLists,
    payload: &mut [u8],
) -> SResult<AnonymizedMessage> {
    anonymize_kafka_payload_opts(allow, payload, AnonymizeOpts::default())
}

pub fn anonymize_kafka_payload_opts(
    allow: &AllowLists,
    payload: &mut [u8],
    opts: AnonymizeOpts,
) -> SResult<AnonymizedMessage> {
    if let Some((distinct_id_span, data_span)) = scan_outer_envelope(payload) {
        // Resolve distinct_id to an owned string first — the unescape below rewrites the buffer.
        let Ok(distinct_id) = scan::unescape(payload, distinct_id_span) else {
            return anonymize_kafka_payload_via_parse(allow, payload, opts);
        };
        let distinct_id = distinct_id.into_owned();
        // Point of no return: the in-place unescape consumes the buffer, so failures past here are
        // classified directly (as the parse would have: undecodable data -> invalid JSON), never
        // retried against the now-rewritten bytes.
        let (len, ascii) = scan::unescape_in_place(payload, data_span)
            .map_err(|e| Failure::new(FailKind::InvalidJson, format!("data string: {}", e.0)))?;
        let inner = &mut payload[data_span.0 + 1..data_span.0 + 1 + len];
        // The parse it replaces validated the whole payload's UTF-8; the scan path must not let
        // invalid bytes flow through pass-through events into the output. The unescape already
        // proved ASCII output valid; only non-ASCII output needs the real check.
        if !ascii && std::str::from_utf8(inner).is_err() {
            return Err(Failure::new(
                FailKind::InvalidJson,
                "invalid utf-8 in data string",
            ));
        }
        return anonymize_snapshot_data_opts(allow, &distinct_id, inner, opts);
    }
    anonymize_kafka_payload_via_parse(allow, payload, opts)
}

/// Locate the `distinct_id` + `data` string spans by scanning the outer object. `None` means "let
/// the full parse decide": escaped/duplicate/missing keys, non-string values, or any structural
/// anomaly.
///
/// One pass: entries are walked directly (no up-front root-span location, which would scan the
/// multi-MB `data` value a second time).
fn scan_outer_envelope(payload: &[u8]) -> Option<(Span, Span)> {
    let mut pos = scan::skip_ws(payload, 0);
    if payload.get(pos) != Some(&b'{') {
        return None;
    }
    pos += 1;
    let mut distinct_id: Option<Span> = None;
    let mut data: Option<Span> = None;
    let mut first = true;
    loop {
        pos = scan::skip_ws(payload, pos);
        // At an entry boundary a `}` can only be the object's close (a key must start with `"`).
        if payload.get(pos) == Some(&b'}') {
            pos += 1;
            break;
        }
        if !first {
            if payload.get(pos) != Some(&b',') {
                return None;
            }
            pos = scan::skip_ws(payload, pos + 1);
        }
        first = false;
        if payload.get(pos) != Some(&b'"') {
            return None;
        }
        let key_end = scan::skip_string(payload, pos).ok()?;
        let key = &payload[pos + 1..key_end - 1];
        if key.contains(&b'\\') {
            return None;
        }
        pos = scan::skip_ws(payload, key_end);
        if payload.get(pos) != Some(&b':') {
            return None;
        }
        let value = scan::locate_value(payload, pos + 1).ok()?;
        match key {
            // Duplicates bail to the parse so its semantics keep applying.
            b"distinct_id" => {
                if distinct_id.replace(value).is_some() {
                    return None;
                }
            }
            b"data" => {
                if data.replace(value).is_some() {
                    return None;
                }
            }
            _ => {}
        }
        pos = value.1;
    }
    if scan::skip_ws(payload, pos) != payload.len() {
        return None;
    }
    let (distinct_id, data) = (distinct_id?, data?);
    if !scan::is_string(payload, distinct_id) || !scan::is_string(payload, data) {
        return None;
    }
    Some((distinct_id, data))
}

fn anonymize_kafka_payload_via_parse(
    allow: &AllowLists,
    payload: &mut [u8],
    opts: AnonymizeOpts,
) -> SResult<AnonymizedMessage> {
    reject_if_too_deep(payload, "kafka payload")
        .map_err(|e| Failure::new(FailKind::InvalidJson, e.to_string()))?;
    let outer = simd_json::to_borrowed_value(payload)
        .map_err(|e| Failure::new(FailKind::InvalidJson, e.to_string()))?;
    let Some(obj) = as_object(&outer) else {
        return Err(Failure::new(
            FailKind::InvalidMessagePayload,
            "payload is not an object",
        ));
    };
    let Some(distinct_id) = obj.get("distinct_id").and_then(as_str) else {
        return Err(Failure::new(
            FailKind::InvalidMessagePayload,
            "missing distinct_id string",
        ));
    };
    let Some(data) = obj.get("data").and_then(as_str) else {
        return Err(Failure::new(
            FailKind::InvalidMessagePayload,
            "missing data string",
        ));
    };
    // Rare path (the scanner bailed): one owned copy buys the in-place processing a mutable buffer.
    let mut data_bytes = data.as_bytes().to_vec();
    anonymize_snapshot_data_opts(allow, distinct_id, &mut data_bytes, opts)
}

/// Anonymize the inner `$snapshot_items` event JSON (the payload's `data` string). The buffer is
/// consumed: scrub-routed data spans are parsed in place (each is fully re-serialized from its
/// tree, so nothing reads a consumed span afterwards).
pub fn anonymize_snapshot_data(
    allow: &AllowLists,
    distinct_id: &str,
    inner: &mut [u8],
) -> SResult<AnonymizedMessage> {
    anonymize_snapshot_data_opts(allow, distinct_id, inner, AnonymizeOpts::default())
}

pub fn anonymize_snapshot_data_opts(
    allow: &AllowLists,
    distinct_id: &str,
    inner: &mut [u8],
    opts: AnonymizeOpts,
) -> SResult<AnonymizedMessage> {
    // No whole-message depth pre-pass here: the byte walk bounds its own recursion and declines
    // past its limit, and every recursive parse below is preceded by a span-local
    // reject_if_too_deep — so the common all-walked path never pays a depth scan at all.
    let ctx = Ctx::new(allow);
    match stream_message(&ctx, distinct_id, inner, opts)? {
        StreamOutcome::Done(msg) => Ok(msg),
        // Escaped/duplicate envelope keys (only a real parse resolves them) or a snapshot-dominated
        // message (adaptive routing): nothing was consumed before either signal, so the tree path
        // re-reads (and now consumes) the intact buffer.
        StreamOutcome::Tree => anonymize_via_tree_mut(&ctx, distinct_id, inner),
    }
}

const MAX_FAIL_DETAIL: usize = 200;

fn non_snapshot(detail: impl Into<String>) -> Failure {
    let mut detail: String = detail.into();
    detail.truncate(MAX_FAIL_DETAIL);
    Failure::new(FailKind::NonSnapshotMessage, detail)
}

// ---------------------------------------------------------------------------
// Streaming path
// ---------------------------------------------------------------------------

struct ScannedEnvelope {
    session_id: String,
    window_id: Option<String>,
    snapshot_source: Option<String>,
    snapshot_library: Option<String>,
}

enum StreamOutcome {
    Done(AnonymizedMessage),
    /// Re-process via the tree (escaped/duplicate envelope keys, or adaptive routing). Only ever
    /// returned while the buffer is intact.
    Tree,
}

/// One fused walk over the whole message: envelope fields are captured as they pass, and the
/// events are processed inline the moment `$snapshot_items` is reached — the array is never
/// pre-skipped just to finish the envelope first. Because prod key order puts `$window_id` after
/// the items, events emit prefix-less bodies (`Sink.line_starts`) and `finish` frames them once
/// the envelope is complete.
///
/// Error precedence matches the unfused code (envelope validation used to run before any event):
/// event failures are stashed while the envelope walk completes, envelope validation errors win,
/// and only then does a stashed event error surface. Escaped/duplicate envelope keys after events
/// have consumed the buffer in place cannot fall back to the parse — that combination (multi-MB of
/// scrub data plus a mangled envelope key behind the items) fails closed instead.
fn stream_message(
    ctx: &Ctx<'_>,
    distinct_id: &str,
    inner: &mut [u8],
    opts: AnonymizeOpts,
) -> SResult<StreamOutcome> {
    let start = scan::skip_ws(inner, 0);
    if inner.get(start) != Some(&b'{') {
        // Preserve the old classification for non-object roots (including trailing-byte checks).
        let root = scan::locate_value(inner, 0).map_err(|e| non_snapshot(e.0))?;
        if scan::skip_ws(inner, root.1) != inner.len() {
            return Err(non_snapshot("trailing bytes after event json"));
        }
        return Err(non_snapshot("event json is not an object"));
    }

    let mut sink = Sink::new(inner.len() - start);
    let mut event_span: Option<Span> = None;
    let mut saw_props = false;
    let mut session_id_span: Option<Span> = None;
    let mut window_id_span: Option<Span> = None;
    let mut snapshot_source_span: Option<Span> = None;
    let mut lib_span: Option<Span> = None;
    let mut saw_items = false;
    let mut items_not_array = false;
    // First event-processing failure; surfaced only after envelope validation passes.
    let mut deferred: Option<Failure> = None;
    let mut use_tree = false;

    // Escaped or duplicate envelope keys need JSON.parse semantics — the tree run. That is only
    // possible while the buffer is intact.
    macro_rules! need_full_parse {
        () => {{
            if sink.mutated {
                return Err(non_snapshot(
                    "envelope key needs a full parse after events were consumed",
                ));
            }
            return Ok(StreamOutcome::Tree);
        }};
    }

    let mut pos = start + 1;
    let mut first = true;
    let root_end = loop {
        pos = scan::skip_ws(inner, pos);
        if inner.get(pos) == Some(&b'}') {
            break pos + 1;
        }
        if !first {
            if inner.get(pos) != Some(&b',') {
                return Err(non_snapshot("expected ',' between object entries"));
            }
            pos = scan::skip_ws(inner, pos + 1);
        }
        first = false;
        if inner.get(pos) != Some(&b'"') {
            return Err(non_snapshot("expected object key"));
        }
        let key_end = scan::skip_string(inner, pos).map_err(|e| non_snapshot(e.0))?;
        let key_span = (pos + 1, key_end - 1);
        if inner[key_span.0..key_span.1].contains(&b'\\') {
            need_full_parse!();
        }
        pos = scan::skip_ws(inner, key_end);
        if inner.get(pos) != Some(&b':') {
            return Err(non_snapshot("expected ':' after object key"));
        }
        pos += 1;
        let vstart = scan::skip_ws(inner, pos);
        match &inner[key_span.0..key_span.1] {
            b"properties" => {
                if saw_props {
                    need_full_parse!();
                }
                saw_props = true;
                if inner.get(vstart) != Some(&b'{') {
                    // Recorded as present-but-wrong; validation below reports it like before.
                    let vspan = scan::locate_value(inner, vstart).map_err(|e| non_snapshot(e.0))?;
                    pos = vspan.1;
                    session_id_span = None;
                    saw_props = false; // "missing properties object", matching the old filter
                    continue;
                }
                // Inline props walk.
                let mut ppos = vstart + 1;
                let mut pfirst = true;
                pos = loop {
                    ppos = scan::skip_ws(inner, ppos);
                    if inner.get(ppos) == Some(&b'}') {
                        break ppos + 1;
                    }
                    if !pfirst {
                        if inner.get(ppos) != Some(&b',') {
                            return Err(non_snapshot("expected ',' between object entries"));
                        }
                        ppos = scan::skip_ws(inner, ppos + 1);
                    }
                    pfirst = false;
                    if inner.get(ppos) != Some(&b'"') {
                        return Err(non_snapshot("expected object key"));
                    }
                    let pkey_end = scan::skip_string(inner, ppos).map_err(|e| non_snapshot(e.0))?;
                    let pkey = (ppos + 1, pkey_end - 1);
                    if inner[pkey.0..pkey.1].contains(&b'\\') {
                        need_full_parse!();
                    }
                    ppos = scan::skip_ws(inner, pkey_end);
                    if inner.get(ppos) != Some(&b':') {
                        return Err(non_snapshot("expected ':' after object key"));
                    }
                    let pvstart = scan::skip_ws(inner, ppos + 1);
                    match &inner[pkey.0..pkey.1] {
                        b"$snapshot_items" => {
                            if saw_items || items_not_array {
                                need_full_parse!();
                            }
                            saw_items = true;
                            if inner.get(pvstart) != Some(&b'[') {
                                items_not_array = true;
                                let vspan = scan::locate_value(inner, pvstart)
                                    .map_err(|e| non_snapshot(e.0))?;
                                ppos = vspan.1;
                                continue;
                            }
                            // Stream the events right here. After a deferred failure or a routing
                            // abort, the remaining items are only skipped to find the array's end.
                            let mut ipos = pvstart + 1;
                            let mut ifirst = true;
                            loop {
                                ipos = scan::skip_ws(inner, ipos);
                                if inner.get(ipos) == Some(&b']') {
                                    ipos += 1;
                                    break;
                                }
                                if !ifirst {
                                    if inner.get(ipos) != Some(&b',') {
                                        return Err(non_snapshot(
                                            "expected ',' between array items",
                                        ));
                                    }
                                    ipos += 1;
                                }
                                ifirst = false;
                                if deferred.is_some() || use_tree {
                                    let span = scan::locate_value(inner, ipos)
                                        .map_err(|e| non_snapshot(e.0))?;
                                    ipos = span.1;
                                    continue;
                                }
                                match process_event_at(ctx, inner, ipos, &mut sink, opts) {
                                    Ok(EventStep::Next(p)) => ipos = p,
                                    Ok(EventStep::UseTree) => {
                                        use_tree = true;
                                        let span = scan::locate_value(inner, ipos)
                                            .map_err(|e| non_snapshot(e.0))?;
                                        ipos = span.1;
                                    }
                                    Err(e) => {
                                        deferred = Some(e);
                                        let span = scan::locate_value(inner, ipos)
                                            .map_err(|e| non_snapshot(e.0))?;
                                        ipos = span.1;
                                    }
                                }
                            }
                            ppos = ipos;
                        }
                        b"$session_id" => {
                            if session_id_span.replace(scan_prop_value(inner, pvstart, &mut ppos)?).is_some() {
                                need_full_parse!();
                            }
                        }
                        b"$window_id" => {
                            if window_id_span.replace(scan_prop_value(inner, pvstart, &mut ppos)?).is_some() {
                                need_full_parse!();
                            }
                        }
                        b"$snapshot_source" => {
                            if snapshot_source_span.replace(scan_prop_value(inner, pvstart, &mut ppos)?).is_some() {
                                need_full_parse!();
                            }
                        }
                        b"$lib" => {
                            if lib_span.replace(scan_prop_value(inner, pvstart, &mut ppos)?).is_some() {
                                need_full_parse!();
                            }
                        }
                        _ => {
                            let vspan =
                                scan::locate_value(inner, pvstart).map_err(|e| non_snapshot(e.0))?;
                            ppos = vspan.1;
                        }
                    }
                };
            }
            b"event" => {
                let vspan = scan::locate_value(inner, vstart).map_err(|e| non_snapshot(e.0))?;
                if event_span.replace(vspan).is_some() {
                    need_full_parse!();
                }
                pos = vspan.1;
            }
            _ => {
                let vspan = scan::locate_value(inner, vstart).map_err(|e| non_snapshot(e.0))?;
                pos = vspan.1;
            }
        }
    };
    if scan::skip_ws(inner, root_end) != inner.len() {
        return Err(non_snapshot("trailing bytes after event json"));
    }

    // Envelope validation, with the same messages and precedence as when it ran before the events.
    let Some(event_span) = event_span.filter(|s| scan::is_string(inner, *s)) else {
        return Err(non_snapshot("missing event name"));
    };
    let event_name = scan::unescape(inner, event_span).map_err(|e| non_snapshot(e.0))?;
    if event_name != "$snapshot_items" {
        return Err(non_snapshot("not a $snapshot_items event"));
    }
    if !saw_props {
        return Err(non_snapshot("missing properties object"));
    }
    if !saw_items {
        return Err(non_snapshot("missing $snapshot_items"));
    }
    if items_not_array {
        return Err(non_snapshot("$snapshot_items is not an array"));
    }
    let session_id = match session_id_span {
        Some(s) if scan::is_string(inner, s) => {
            scan::unescape(inner, s).map_err(|e| non_snapshot(e.0))?
        }
        Some(_) => return Err(non_snapshot("$session_id is not a string")),
        None => return Err(non_snapshot("missing $session_id")),
    };
    if session_id.is_empty() {
        return Err(non_snapshot("empty $session_id"));
    }
    let opt_string = |span: Option<Span>, name: &str| -> SResult<Option<String>> {
        match span {
            None => Ok(None),
            Some(s) if scan::is_string(inner, s) => scan::unescape(inner, s)
                .map(|c| Some(c.into_owned()))
                .map_err(|e| non_snapshot(e.0)),
            Some(_) => Err(non_snapshot(format!("{name} is not a string"))),
        }
    };
    let env = ScannedEnvelope {
        session_id: session_id.into_owned(),
        window_id: opt_string(window_id_span, "$window_id")?,
        snapshot_source: opt_string(snapshot_source_span, "$snapshot_source")?,
        snapshot_library: opt_string(lib_span, "$lib")?,
    };

    if use_tree {
        return Ok(StreamOutcome::Tree);
    }
    if let Some(e) = deferred {
        return Err(e);
    }
    finish(distinct_id, env, sink, Route::Stream).map(StreamOutcome::Done)
}

/// Locate a props value span and advance the cursor past it.
fn scan_prop_value(inner: &[u8], vstart: usize, ppos: &mut usize) -> SResult<Span> {
    let vspan = scan::locate_value(inner, vstart).map_err(|e| non_snapshot(e.0))?;
    *ppos = vspan.1;
    Ok(vspan)
}

/// Shared per-message accumulation state. Lines accumulate as prefix-less event bodies with their
/// start offsets recorded; `finish` frames them (`["<windowId>",` ... `]\n`) once the envelope —
/// which may complete after the events in prod key order — is known.
struct Sink {
    lines: Vec<u8>,
    /// Start offset of each emitted body in `lines` (one per entry in `events`).
    line_starts: Vec<usize>,
    events: Vec<EventMeta>,
    console: [u32; 3], // info, warn, error
    /// simd-json scratch reused across the per-event parses.
    buffers: simd_json::Buffers,
    /// Whether an in-place parse has consumed a span yet — routing to the tree path is only sound
    /// while the buffer is intact.
    mutated: bool,
    /// Copy-parse budget for early scrub events (real messages open with a small Meta event before
    /// the full snapshot; consuming it in place would foreclose adaptive routing). Small events
    /// parse from `scratch` until the budget runs out; everything after parses in place.
    scratch_budget: usize,
    scratch: Vec<u8>,
}

impl Sink {
    fn new(capacity_hint: usize) -> Self {
        Self {
            lines: Vec::with_capacity(capacity_hint + capacity_hint / 8),
            line_starts: Vec::new(),
            events: Vec::new(),
            console: [0; 3],
            buffers: simd_json::Buffers::default(),
            mutated: false,
            scratch_budget: SCRATCH_BUDGET,
            scratch: Vec::new(),
        }
    }

    /// Record that a body was emitted starting at `start` — call only once the emission is final
    /// (declined attempts truncate `lines` and must leave no marker behind).
    fn open_line_at(&mut self, start: usize) {
        self.line_starts.push(start);
    }
}

fn finish(
    distinct_id: &str,
    env: ScannedEnvelope,
    sink: Sink,
    route: Route,
) -> SResult<AnonymizedMessage> {
    if sink.events.is_empty() {
        return Err(Failure::new(
            FailKind::NoValidEvents,
            "message contained no valid rrweb events",
        ));
    }
    let start_ts = sink.events.iter().map(|e| e.ts).fold(f64::MAX, f64::min);
    let end_ts = sink.events.iter().map(|e| e.ts).fold(f64::MIN, f64::max);
    // Frame the prefix-less bodies into `["<windowId>",<event>]\n` lines.
    let window_id_str = env.window_id.clone().unwrap_or_default();
    let mut prefix = Vec::with_capacity(window_id_str.len() + 4);
    prefix.push(b'[');
    scan::write_json_string(&window_id_str, &mut prefix);
    prefix.push(b',');
    let n = sink.line_starts.len();
    // An unpaired body/event mis-frames every later line, so fail closed rather than emit misaligned
    // output (hard error, not a debug_assert).
    if n != sink.events.len() {
        return Err(Failure::new(
            FailKind::AnonymizeFailed,
            "internal: line/event count mismatch",
        ));
    }
    let mut lines = Vec::with_capacity(sink.lines.len() + n * (prefix.len() + 2));
    for i in 0..n {
        let body_end = sink.line_starts.get(i + 1).copied().unwrap_or(sink.lines.len());
        lines.extend_from_slice(&prefix);
        lines.extend_from_slice(&sink.lines[sink.line_starts[i]..body_end]);
        lines.extend_from_slice(b"]\n");
    }
    Ok(AnonymizedMessage {
        lines,
        route,
        meta: SnapshotMeta {
            distinct_id: distinct_id.to_string(),
            session_id: env.session_id,
            window_id: env.window_id.unwrap_or_default(),
            snapshot_source: env.snapshot_source,
            snapshot_library: env.snapshot_library,
            start_ts,
            end_ts,
            console_log_count: sink.console[0],
            console_warn_count: sink.console[1],
            console_error_count: sink.console[2],
            events: sink.events,
        },
    })
}

/// `SnapshotEventSchema` validity: an object with a numeric, positive, in-JS-`Date`-range timestamp.
fn valid_timestamp(ts: Option<f64>) -> Option<f64> {
    ts.filter(|t| *t > 0.0 && *t <= MAX_JS_DATE_MS)
}

fn to_small_uint(n: f64) -> Option<u8> {
    (n.fract() == 0.0 && (0.0..=u8::MAX as f64).contains(&n)).then_some(n as u8)
}

/// Everything the router and the meta need from one event, captured in a single walk.
#[derive(Default)]
struct EventScan {
    ty: Option<Span>,
    ts: Option<Span>,
    data: Option<Span>,
    cv: Option<Span>,
    data_is_object: bool,
    // Depth-1 spans inside `data` (only set when `data_is_object`).
    source: Option<Span>,
    interaction: Option<Span>, // data.type
    href: Option<Span>,
    payload: Option<Span>,
    /// Escaped or duplicate keys anywhere routing-relevant: only a real parse is safe.
    fallback: bool,
}

/// Walk the event object starting at `start` (must be at `{`), capturing routing fields and the
/// event's end position in one pass. A `data` object gets its depth-1 fields read by the same walk
/// that discovers its end — the span skip `locate_value` would do reads the routing keys instead.
fn scan_event(inner: &[u8], start: usize) -> SResult<(EventScan, usize)> {
    let mut es = EventScan::default();
    let mut seen = [false; 4];
    let mut pos = start + 1;
    let mut first = true;
    loop {
        pos = scan::skip_ws(inner, pos);
        // At an entry boundary `}` can only close the object (keys must start with `"`).
        if inner.get(pos) == Some(&b'}') {
            return Ok((es, pos + 1));
        }
        if !first {
            if inner.get(pos) != Some(&b',') {
                return Err(non_snapshot("expected ',' between object entries"));
            }
            pos = scan::skip_ws(inner, pos + 1);
        }
        first = false;
        if inner.get(pos) != Some(&b'"') {
            return Err(non_snapshot("expected object key"));
        }
        let key_end = scan::skip_string(inner, pos).map_err(|e| non_snapshot(e.0))?;
        let key = &inner[pos + 1..key_end - 1];
        if key.contains(&b'\\') {
            es.fallback = true;
        }
        pos = scan::skip_ws(inner, key_end);
        if inner.get(pos) != Some(&b':') {
            return Err(non_snapshot("expected ':' after object key"));
        }
        pos += 1;
        let vstart = scan::skip_ws(inner, pos);
        if key == b"data" && !seen[2] && inner.get(vstart) == Some(&b'{') {
            seen[2] = true;
            let dend = scan_event_data(inner, vstart, &mut es)?;
            es.data = Some((vstart, dend));
            es.data_is_object = true;
            pos = dend;
            continue;
        }
        let vspan = scan::locate_value(inner, vstart).map_err(|e| non_snapshot(e.0))?;
        let (slot, idx) = match key {
            b"type" => (&mut es.ty, 0),
            b"timestamp" => (&mut es.ts, 1),
            b"data" => (&mut es.data, 2),
            b"cv" => (&mut es.cv, 3),
            _ => {
                pos = vspan.1;
                continue;
            }
        };
        if seen[idx] {
            // A duplicate key means the raw bytes hold content JSON.parse would discard; only a
            // real parse (which dedupes) is safe to emit.
            es.fallback = true;
        }
        seen[idx] = true;
        *slot = Some(vspan);
        pos = vspan.1;
    }
}

/// Depth-1 walk of an event's `data` object: captures the router/meta fields and returns the
/// object's end position.
fn scan_event_data(inner: &[u8], start: usize, es: &mut EventScan) -> SResult<usize> {
    let mut seen = [false; 4];
    let mut pos = start + 1;
    let mut first = true;
    loop {
        pos = scan::skip_ws(inner, pos);
        if inner.get(pos) == Some(&b'}') {
            return Ok(pos + 1);
        }
        if !first {
            if inner.get(pos) != Some(&b',') {
                return Err(non_snapshot("expected ',' between object entries"));
            }
            pos = scan::skip_ws(inner, pos + 1);
        }
        first = false;
        if inner.get(pos) != Some(&b'"') {
            return Err(non_snapshot("expected object key"));
        }
        let key_end = scan::skip_string(inner, pos).map_err(|e| non_snapshot(e.0))?;
        let key = &inner[pos + 1..key_end - 1];
        if key.contains(&b'\\') {
            es.fallback = true;
        }
        pos = scan::skip_ws(inner, key_end);
        if inner.get(pos) != Some(&b':') {
            return Err(non_snapshot("expected ':' after object key"));
        }
        let vspan = scan::locate_value(inner, pos + 1).map_err(|e| non_snapshot(e.0))?;
        let (slot, idx) = match key {
            b"source" => (&mut es.source, 0),
            b"type" => (&mut es.interaction, 1),
            b"href" => (&mut es.href, 2),
            b"payload" => (&mut es.payload, 3),
            _ => {
                pos = vspan.1;
                continue;
            }
        };
        if seen[idx] {
            es.fallback = true;
        }
        seen[idx] = true;
        *slot = Some(vspan);
        pos = vspan.1;
    }
}

enum EventStep {
    /// Continue with the next array item at this position.
    Next(usize),
    /// Abort streaming and route the whole message through the tree path.
    UseTree,
}

/// A scrub-routed data span holding most of the message means the tree path's single SIMD parse of
/// everything beats streaming's scan-then-parse duplication. Tuned from the canary's route-labelled
/// duration metrics.
const TREE_ROUTE_MIN_DATA_FRACTION: usize = 2; // data > inner.len() / 2

/// How many scrub-routed bytes may copy-parse via scratch before switching to in-place parses.
const SCRATCH_BUDGET: usize = 64 * 1024;

/// Process the array item starting at (or after whitespace from) `item_pos`; returns the position
/// just past the event.
fn process_event_at(
    ctx: &Ctx<'_>,
    inner: &mut [u8],
    item_pos: usize,
    sink: &mut Sink,
    opts: AnonymizeOpts,
) -> SResult<EventStep> {
    let start = scan::skip_ws(inner, item_pos);
    // Non-object events fail SnapshotEventSchema and are silently skipped, like the TS parse step.
    if inner.get(start) != Some(&b'{') {
        let span = scan::locate_value(inner, start).map_err(|e| non_snapshot(e.0))?;
        return Ok(EventStep::Next(span.1));
    }

    let (es, end) = scan_event(inner, start)?;
    let span = (start, end);

    // Raw C0 controls route to the tree, which normalizes/rejects them like JSON.parse: `\n`/`\r`
    // would break line framing if memcpy'd, the rest are invalid JSON the stream path would splice
    // through verbatim (a stream-vs-tree divergence). The `< 0x20` scan autovectorizes.
    if es.fallback || inner[span.0..span.1].iter().any(|&b| b < 0x20) {
        process_event_via_tree(ctx, inner, span, sink)?;
        return Ok(EventStep::Next(end));
    }

    let Some(ts) = valid_timestamp(es.ts.and_then(|s| scan::parse_number(inner, s))) else {
        return Ok(EventStep::Next(end)); // invalid/missing timestamp: the event is filtered out
    };
    let ty = es
        .ty
        .and_then(|s| scan::parse_number(inner, s))
        .and_then(to_small_uint);
    let compressed = es.cv.map(|s| !scan::is_null(inner, s)).unwrap_or(false);

    // Everything the scrubbers touch lives inside `data`; events with no data object (or whose
    // type/source never routes to a scrubber) pass through byte-identical.
    let Some(data) = es.data else {
        pass_through(inner, span, ts, ty, None, sink);
        return Ok(EventStep::Next(end));
    };

    let needs_parse = match ty {
        Some(TYPE_FULL_SNAPSHOT) => true,
        Some(TYPE_INCREMENTAL) | Some(TYPE_META) | Some(TYPE_CUSTOM) | Some(TYPE_PLUGIN) => {
            es.data_is_object
        }
        _ => false,
    };
    if !needs_parse {
        pass_through(inner, span, ts, ty, es.data_is_object.then_some(&es), sink);
        return Ok(EventStep::Next(end));
    }

    // Incremental events only route to a scrubber for mutation/input/canvas sources.
    let source = es
        .source
        .and_then(|s| scan::parse_number(inner, s))
        .and_then(to_small_uint);
    if ty == Some(TYPE_INCREMENTAL)
        && !matches!(
            source,
            Some(SOURCE_MUTATION) | Some(SOURCE_INPUT) | Some(SOURCE_CANVAS_MUTATION)
        )
    {
        pass_through(inner, span, ts, ty, Some(&es), sink);
        return Ok(EventStep::Next(end));
    }

    // Parse-free byte walk first: the bulk routes get scrubbed straight from the bytes, with
    // unchanged values copied verbatim. The walk proves every object duplicate-key-free as it goes,
    // which is what makes emitting original bytes safe (no shadowed duplicate content can survive);
    // anything it can't prove — escaped keys, cv payloads, canvas/meta/custom/plugin routes — is
    // declined and handled by the parse below. The walk never mutates the buffer, so falling
    // through (and adaptive routing) stay sound.
    if opts.byte_walk {
        let mark = sink.lines.len();
        sink.lines.extend_from_slice(&inner[span.0..data.0]);
        let data_mark = sink.lines.len();
        match crate::bytewalk::scrub_data_bytes(ctx, ty, source, compressed, inner, data, &mut sink.lines)
        {
            Some(changed) => {
                if !changed {
                    // Nothing changed and the span is proven dup-free: keep the original bytes.
                    sink.lines.truncate(data_mark);
                    sink.lines.extend_from_slice(&inner[data.0..data.1]);
                }
                sink.lines.extend_from_slice(&inner[data.1..span.1]);
                sink.open_line_at(mark);
                // These routes never scrub data.href/source/type, so the scanned (pre-scrub)
                // values equal what the tree path reads post-scrub.
                let interaction = es
                    .interaction
                    .and_then(|s| scan::parse_number(inner, s))
                    .and_then(to_small_uint);
                sink.events.push(EventMeta {
                    ts,
                    flags: flags_of(ty, source, interaction),
                    href: scanned_href(inner, &es),
                });
                return Ok(EventStep::Next(end));
            }
            None => sink.lines.truncate(mark),
        }
    }

    // Adaptive routing: only while nothing has been consumed — the tree run re-reads the buffer.
    // The scratch budget below keeps the buffer intact through the small Meta/input events that
    // ordinarily precede a full snapshot, so the dominant case still aborts at zero cost.
    if opts.adaptive_routing
        && !sink.mutated
        && (data.1 - data.0) > inner.len() / TREE_ROUTE_MIN_DATA_FRACTION
    {
        return Ok(EventStep::UseTree);
    }

    // Scrub route: parse the data span — in place for the bulk (simd-json only mutates within the
    // span, and the splice reads only the disjoint prefix/suffix), via a bounded scratch copy for
    // small early events (see `scratch_budget`) — then splice the re-serialized value back between
    // the untouched surrounding bytes. The splice happens even when nothing changed: JSON.parse
    // dedupes duplicate keys, so re-serializing from the parsed tree guarantees no shadowed
    // duplicate content inside `data` survives in the raw bytes. Later events sit entirely past
    // `end`, so a consumed span is never re-read.
    reject_if_too_deep(&inner[data.0..data.1], "snapshot event json")
        .map_err(|e| Failure::new(FailKind::NonSnapshotMessage, e.to_string()))?;
    let use_scratch = !sink.mutated && (data.1 - data.0) <= sink.scratch_budget;
    if use_scratch {
        sink.scratch_budget -= data.1 - data.0;
    } else {
        sink.mutated = true;
    }
    let mut buffers = std::mem::take(&mut sink.buffers);
    let mut scratch = std::mem::take(&mut sink.scratch);
    let result = (|| -> SResult<()> {
        let (prefix, data_bytes, suffix): (&[u8], &mut [u8], &[u8]) = if use_scratch {
            scratch.clear();
            scratch.extend_from_slice(&inner[data.0..data.1]);
            (
                &inner[span.0..data.0],
                &mut scratch[..],
                &inner[data.1..span.1],
            )
        } else {
            let (before, rest) = inner.split_at_mut(data.0);
            let (data_bytes, after) = rest.split_at_mut(data.1 - data.0);
            (&before[span.0..], data_bytes, &after[..span.1 - data.1])
        };
        let mut value = parse_untrusted_with_buffers(data_bytes, &mut buffers)
            .map_err(|e| non_snapshot(format!("event data: {e}")))?;
        route_data(ctx, ty, compressed, &mut value)
            .map_err(|e| Failure::new(FailKind::AnonymizeFailed, e.to_string()))?;
        let line_start = sink.lines.len();
        sink.lines.extend_from_slice(prefix);
        value
            .write(&mut sink.lines)
            .expect("writing json to a Vec cannot fail");
        sink.lines.extend_from_slice(suffix);
        sink.open_line_at(line_start);
        push_meta_from_data(ty, ts, Some(&value), sink);
        Ok(())
    })();
    sink.buffers = buffers;
    scratch.clear();
    sink.scratch = scratch;
    result?;
    Ok(EventStep::Next(end))
}

/// Emit a pass-through event: memcpy the span, derive meta from the scans.
fn pass_through(
    inner: &[u8],
    span: Span,
    ts: f64,
    ty: Option<u8>,
    data: Option<&EventScan>,
    sink: &mut Sink,
) {
    let line_start = sink.lines.len();
    sink.lines.extend_from_slice(&inner[span.0..span.1]);
    sink.open_line_at(line_start);

    let (source, interaction, href) = match data {
        Some(d) => (
            d.source
                .and_then(|s| scan::parse_number(inner, s))
                .and_then(to_small_uint),
            d.interaction
                .and_then(|s| scan::parse_number(inner, s))
                .and_then(to_small_uint),
            scanned_href(inner, d),
        ),
        None => (None, None, None),
    };
    sink.events.push(EventMeta {
        ts,
        flags: flags_of(ty, source, interaction),
        href,
    });
}

/// `hrefFrom` over scanned spans: `data.href` (string, trimmed, non-empty) falling back to
/// `data.payload.href`.
fn scanned_href(inner: &[u8], d: &EventScan) -> Option<String> {
    let read = |span: Span| -> Option<String> {
        if !scan::is_string(inner, span) {
            return None;
        }
        let s = scan::unescape(inner, span).ok()?;
        let t = s.trim();
        (!t.is_empty()).then(|| t.to_string())
    };
    if let Some(h) = d.href.and_then(read) {
        return Some(h);
    }
    let payload = d.payload.filter(|p| scan::is_object(inner, *p))?;
    let mut href: Option<Span> = None;
    for entry in scan::object_entries(inner, payload).ok()? {
        let entry = entry.ok()?;
        if entry.key_escaped {
            return None; // vanishingly rare; href meta is best-effort here
        }
        if &inner[entry.key.0..entry.key.1] == b"href" {
            href = Some(entry.value);
        }
    }
    href.and_then(read)
}

fn flags_of(ty: Option<u8>, source: Option<u8>, interaction: Option<u8>) -> u8 {
    if ty != Some(TYPE_INCREMENTAL) {
        return 0;
    }
    let Some(s) = source else {
        return 0;
    };
    let mut flags = 0u8;
    // activeSources: MouseMove, MouseInteraction, Scroll, ViewportResize, Input, TouchMove,
    // MediaInteraction, Drag.
    if matches!(s, 1..=7 | 12) {
        flags |= FLAG_ACTIVE;
    }
    // CLICK_TYPES: Click, ContextMenu, DblClick, TouchEnd.
    if s == 2 && matches!(interaction, Some(2) | Some(3) | Some(4) | Some(9)) {
        flags |= FLAG_CLICK;
    }
    if s == SOURCE_INPUT {
        flags |= FLAG_KEYPRESS;
    }
    // MOUSE_ACTIVITY_SOURCES: MouseInteraction, MouseMove, TouchMove.
    if matches!(s, 1 | 2 | 6) {
        flags |= FLAG_MOUSE_ACTIVITY;
    }
    flags
}

/// Meta + console counts from a parsed (post-scrub) `data` value.
fn push_meta_from_data(ty: Option<u8>, ts: f64, data: Option<&Value<'_>>, sink: &mut Sink) {
    let dobj = data.and_then(as_object);
    let source = dobj.and_then(|d| d.get("source")).and_then(as_small_uint);
    let interaction = dobj.and_then(|d| d.get("type")).and_then(as_small_uint);
    let href = dobj.and_then(|d| {
        let read = |v: &Value<'_>| -> Option<String> {
            let t = as_str(v)?.trim();
            (!t.is_empty()).then(|| t.to_string())
        };
        d.get("href").and_then(read).or_else(|| {
            d.get("payload")
                .and_then(as_object)
                .and_then(|p| p.get("href"))
                .and_then(read)
        })
    });
    sink.events.push(EventMeta {
        ts,
        flags: flags_of(ty, source, interaction),
        href,
    });

    // rrweb/console@1 counts by level (mirrors `session-console-log-recorder.ts` safeLevel).
    if ty == Some(TYPE_PLUGIN) {
        if let Some(d) = dobj {
            if d.get("plugin").and_then(as_str) == Some("rrweb/console@1") {
                let level = d
                    .get("payload")
                    .and_then(as_object)
                    .and_then(|p| p.get("level"))
                    .and_then(as_str);
                match level {
                    Some("warn") | Some("countReset") => sink.console[1] += 1,
                    Some("error") | Some("assert") => sink.console[2] += 1,
                    _ => sink.console[0] += 1,
                }
            }
        }
    }
}

/// Full-parse fallback for a single event whose bytes the scanner cannot prove safe (escaped or
/// duplicate keys): parse, scrub, and re-serialize the whole event, normalizing like JSON.parse.
fn process_event_via_tree(ctx: &Ctx<'_>, inner: &[u8], span: Span, sink: &mut Sink) -> SResult<()> {
    reject_if_too_deep(&inner[span.0..span.1], "snapshot event json")
        .map_err(|e| Failure::new(FailKind::NonSnapshotMessage, e.to_string()))?;
    let mut scratch = inner[span.0..span.1].to_vec();
    let mut event =
        parse_untrusted(&mut scratch).map_err(|e| non_snapshot(format!("event: {e}")))?;
    tree_event(ctx, &mut event, sink)
}

/// Scrub + emit one parsed event (shared by the per-event fallback and the whole-payload tree path).
/// Always re-serializes from the tree, so JSON.parse normalization (duplicate keys, escapes) holds.
fn tree_event(ctx: &Ctx<'_>, event: &mut Value<'_>, sink: &mut Sink) -> SResult<()> {
    let Some(obj) = as_object(&*event) else {
        return Ok(());
    };
    let Some(ts) = valid_timestamp(obj.get("timestamp").and_then(as_f64)) else {
        return Ok(());
    };
    let ty = obj.get("type").and_then(as_small_uint);

    route_event(ctx, event).map_err(|e| Failure::new(FailKind::AnonymizeFailed, e.to_string()))?;

    let line_start = sink.lines.len();
    event
        .write(&mut sink.lines)
        .expect("writing json to a Vec cannot fail");
    sink.open_line_at(line_start);

    let data = as_object(&*event).and_then(|o| o.get("data"));
    push_meta_from_data(ty, ts, data, sink);
    Ok(())
}

// ---------------------------------------------------------------------------
// Tree path: the reference implementation and the streaming path's fallback.
// ---------------------------------------------------------------------------

/// Parse the whole inner event JSON and produce the output via the tree walk. Differential tests
/// assert the streaming path agrees with this on semantics.
pub fn anonymize_via_tree(
    ctx: &Ctx<'_>,
    distinct_id: &str,
    inner: &[u8],
) -> SResult<AnonymizedMessage> {
    let mut buf = inner.to_vec();
    anonymize_via_tree_mut(ctx, distinct_id, &mut buf)
}

/// [`anonymize_via_tree`] parsing the buffer in place (it is consumed).
fn anonymize_via_tree_mut(
    ctx: &Ctx<'_>,
    distinct_id: &str,
    inner: &mut [u8],
) -> SResult<AnonymizedMessage> {
    // JSON.parse on the TS side dies on pathological nesting too (stack overflow -> caught ->
    // received_non_snapshot_message); the guard keeps the recursive parse/walk off the thread stack.
    reject_if_too_deep(inner, "snapshot event json")
        .map_err(|e| Failure::new(FailKind::NonSnapshotMessage, e.to_string()))?;
    let inner_len = inner.len();
    let mut root =
        parse_untrusted(inner).map_err(|e| non_snapshot(format!("event json: {e}")))?;

    let (session_id, window_id, snapshot_source, snapshot_library) = {
        let Some(obj) = as_object(&root) else {
            return Err(non_snapshot("event json is not an object"));
        };
        match obj.get("event").map(|v| as_str(v)) {
            Some(Some("$snapshot_items")) => {}
            Some(Some(_)) => return Err(non_snapshot("not a $snapshot_items event")),
            Some(None) | None => return Err(non_snapshot("missing event name")),
        }
        let Some(props) = obj.get("properties").and_then(as_object) else {
            return Err(non_snapshot("missing properties object"));
        };
        let opt_string = |name: &str| -> SResult<Option<String>> {
            match props.get(name) {
                None => Ok(None),
                Some(v) => match as_str(v) {
                    Some(s) => Ok(Some(s.to_string())),
                    None => Err(non_snapshot(format!("{name} is not a string"))),
                },
            }
        };
        let session_id = match props.get("$session_id") {
            Some(v) => match as_str(v) {
                Some(s) if !s.is_empty() => s.to_string(),
                Some(_) => return Err(non_snapshot("empty $session_id")),
                None => return Err(non_snapshot("$session_id is not a string")),
            },
            None => return Err(non_snapshot("missing $session_id")),
        };
        match props.get("$snapshot_items") {
            Some(Value::Array(_)) => {}
            Some(_) => return Err(non_snapshot("$snapshot_items is not an array")),
            None => return Err(non_snapshot("missing $snapshot_items")),
        }
        (
            session_id,
            opt_string("$window_id")?,
            opt_string("$snapshot_source")?,
            opt_string("$lib")?,
        )
    };

    let items = crate::json::as_object_mut(&mut root)
        .and_then(|o| o.get_mut("properties"))
        .and_then(crate::json::as_object_mut)
        .and_then(|p| p.get_mut("$snapshot_items"))
        .and_then(crate::json::as_array_mut)
        .expect("validated above");

    let mut sink = Sink::new(inner_len);
    for event in items.iter_mut() {
        tree_event(ctx, event, &mut sink)?;
    }

    finish(
        distinct_id,
        ScannedEnvelope {
            session_id,
            window_id,
            snapshot_source,
            snapshot_library,
        },
        sink,
        Route::Tree,
    )
}
