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
use crate::json::{as_f64, as_object, as_small_uint, as_str, parse_untrusted, reject_if_too_deep};
use crate::scan::{self, Span};

/// Why a payload could not be anonymized; maps onto the TS pipeline's dlq/drop reasons so the fused
/// step classifies failures exactly like the TS parse step does.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FailKind {
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

#[derive(Debug)]
pub struct AnonymizedMessage {
    /// Scrubbed JSONL: one `["<windowId>",<event>]\n` line per valid event, in input order.
    pub lines: Vec<u8>,
    pub meta: SnapshotMeta,
}

/// Anonymize a decompressed replay Kafka payload (`{"distinct_id": ..., "data": "<event json>"}`).
/// The buffer is scratch space — simd-json unescapes strings in place while parsing the outer object.
pub fn anonymize_kafka_payload(
    allow: &AllowLists,
    payload: &mut [u8],
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
    anonymize_snapshot_data(allow, distinct_id, data.as_bytes())
}

/// Anonymize the inner `$snapshot_items` event JSON (the payload's `data` string).
pub fn anonymize_snapshot_data(
    allow: &AllowLists,
    distinct_id: &str,
    inner: &[u8],
) -> SResult<AnonymizedMessage> {
    // JSON.parse on the TS side dies on pathological nesting too (stack overflow -> caught ->
    // received_non_snapshot_message); the guard keeps the recursive parse/walk off the thread stack.
    reject_if_too_deep(inner, "snapshot event json")
        .map_err(|e| Failure::new(FailKind::NonSnapshotMessage, e.to_string()))?;
    let ctx = Ctx::new(allow);
    match scan_envelope(inner)? {
        Scanned::Envelope(env) => stream_events(&ctx, distinct_id, inner, env),
        // Escaped keys at the envelope level: only a real parse resolves them.
        Scanned::NeedFullParse => anonymize_via_tree(&ctx, distinct_id, inner),
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
    items: Span,
    session_id: String,
    window_id: Option<String>,
    snapshot_source: Option<String>,
    snapshot_library: Option<String>,
}

enum Scanned {
    Envelope(ScannedEnvelope),
    NeedFullParse,
}

/// Locate `$snapshot_items` + the envelope strings by scanning, enforcing the same shape checks the
/// TS zod schemas apply (`EventSchema` + the `$snapshot_items`/`$session_id` presence checks).
fn scan_envelope(inner: &[u8]) -> SResult<Scanned> {
    let root = scan::locate_value(inner, 0).map_err(|e| non_snapshot(e.0))?;
    if scan::skip_ws(inner, root.1) != inner.len() {
        return Err(non_snapshot("trailing bytes after event json"));
    }
    if !scan::is_object(inner, root) {
        return Err(non_snapshot("event json is not an object"));
    }

    // Last occurrence wins, matching JSON.parse duplicate-key semantics.
    let mut event_span: Option<Span> = None;
    let mut props_span: Option<Span> = None;
    for entry in scan::object_entries(inner, root).map_err(|e| non_snapshot(e.0))? {
        let entry = entry.map_err(|e| non_snapshot(e.0))?;
        if entry.key_escaped {
            return Ok(Scanned::NeedFullParse);
        }
        match &inner[entry.key.0..entry.key.1] {
            b"event" => event_span = Some(entry.value),
            b"properties" => props_span = Some(entry.value),
            _ => {}
        }
    }

    let Some(event_span) = event_span.filter(|s| scan::is_string(inner, *s)) else {
        return Err(non_snapshot("missing event name"));
    };
    let event_name = scan::unescape(inner, event_span).map_err(|e| non_snapshot(e.0))?;
    if event_name != "$snapshot_items" {
        return Err(non_snapshot("not a $snapshot_items event"));
    }
    let Some(props_span) = props_span.filter(|s| scan::is_object(inner, *s)) else {
        return Err(non_snapshot("missing properties object"));
    };

    let mut items: Option<Span> = None;
    let mut session_id: Option<Span> = None;
    let mut window_id: Option<Span> = None;
    let mut snapshot_source: Option<Span> = None;
    let mut lib: Option<Span> = None;
    for entry in scan::object_entries(inner, props_span).map_err(|e| non_snapshot(e.0))? {
        let entry = entry.map_err(|e| non_snapshot(e.0))?;
        if entry.key_escaped {
            return Ok(Scanned::NeedFullParse);
        }
        match &inner[entry.key.0..entry.key.1] {
            b"$snapshot_items" => items = Some(entry.value),
            b"$session_id" => session_id = Some(entry.value),
            b"$window_id" => window_id = Some(entry.value),
            b"$snapshot_source" => snapshot_source = Some(entry.value),
            b"$lib" => lib = Some(entry.value),
            _ => {}
        }
    }

    // zod: `$snapshot_items` must be an array when present; the step then requires it present.
    let Some(items) = items else {
        return Err(non_snapshot("missing $snapshot_items"));
    };
    if !scan::is_array(inner, items) {
        return Err(non_snapshot("$snapshot_items is not an array"));
    }
    // zod: `$session_id` must be a string when present; the step then requires it truthy (non-empty).
    let session_id = match session_id {
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
                .map(Some)
                .map_err(|e| non_snapshot(e.0)),
            Some(_) => Err(non_snapshot(format!("{name} is not a string"))),
        }
    };

    Ok(Scanned::Envelope(ScannedEnvelope {
        items,
        session_id,
        window_id: opt_string(window_id, "$window_id")?,
        snapshot_source: opt_string(snapshot_source, "$snapshot_source")?,
        snapshot_library: opt_string(lib, "$lib")?,
    }))
}

/// Shared per-message accumulation state.
struct Sink {
    /// `["<windowId>",` — constant per message.
    prefix: Vec<u8>,
    lines: Vec<u8>,
    events: Vec<EventMeta>,
    console: [u32; 3], // info, warn, error
    scratch: Vec<u8>,
}

impl Sink {
    fn new(window_id: &str, capacity_hint: usize) -> Self {
        let mut prefix = Vec::with_capacity(window_id.len() + 4);
        prefix.push(b'[');
        scan::write_json_string(window_id, &mut prefix);
        prefix.push(b',');
        Self {
            prefix,
            lines: Vec::with_capacity(capacity_hint + capacity_hint / 8),
            events: Vec::new(),
            console: [0; 3],
            scratch: Vec::new(),
        }
    }

    fn open_line(&mut self) {
        self.lines.extend_from_slice(&self.prefix);
    }

    fn close_line(&mut self) {
        self.lines.extend_from_slice(b"]\n");
    }
}

fn stream_events(
    ctx: &Ctx<'_>,
    distinct_id: &str,
    inner: &[u8],
    env: ScannedEnvelope,
) -> SResult<AnonymizedMessage> {
    let window_id = env.window_id.clone().unwrap_or_default();
    let mut sink = Sink::new(&window_id, env.items.1 - env.items.0);

    for item in scan::array_items(inner, env.items).map_err(|e| non_snapshot(e.0))? {
        let span = item.map_err(|e| non_snapshot(e.0))?;
        process_event(ctx, inner, span, &mut sink)?;
    }

    finish(distinct_id, env, sink)
}

fn finish(distinct_id: &str, env: ScannedEnvelope, sink: Sink) -> SResult<AnonymizedMessage> {
    if sink.events.is_empty() {
        return Err(Failure::new(
            FailKind::NoValidEvents,
            "message contained no valid rrweb events",
        ));
    }
    let start_ts = sink.events.iter().map(|e| e.ts).fold(f64::MAX, f64::min);
    let end_ts = sink.events.iter().map(|e| e.ts).fold(f64::MIN, f64::max);
    Ok(AnonymizedMessage {
        lines: sink.lines,
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

/// Depth-1 scan of an event's `data` object for the fields the router and the meta need.
#[derive(Default)]
struct DataScan {
    source: Option<Span>,
    ty: Option<Span>,
    href: Option<Span>,
    payload: Option<Span>,
    fallback: bool, // escaped or duplicate key -> full event parse
}

fn scan_data(inner: &[u8], data: Span) -> SResult<DataScan> {
    let mut out = DataScan::default();
    let mut seen = [false; 4];
    for entry in scan::object_entries(inner, data).map_err(|e| non_snapshot(e.0))? {
        let entry = entry.map_err(|e| non_snapshot(e.0))?;
        if entry.key_escaped {
            out.fallback = true;
            return Ok(out);
        }
        let (slot, idx) = match &inner[entry.key.0..entry.key.1] {
            b"source" => (&mut out.source, 0),
            b"type" => (&mut out.ty, 1),
            b"href" => (&mut out.href, 2),
            b"payload" => (&mut out.payload, 3),
            _ => continue,
        };
        if seen[idx] {
            // A duplicate routing key means the raw bytes hold content JSON.parse would discard;
            // only a real parse (which dedupes) is safe to emit.
            out.fallback = true;
            return Ok(out);
        }
        seen[idx] = true;
        *slot = Some(entry.value);
    }
    Ok(out)
}

fn process_event(ctx: &Ctx<'_>, inner: &[u8], span: Span, sink: &mut Sink) -> SResult<()> {
    // Non-object events fail SnapshotEventSchema and are silently skipped, like the TS parse step.
    if !scan::is_object(inner, span) {
        return Ok(());
    }

    // Raw newlines between an event's tokens (pretty-printed input) would break the one-record-per-
    // line block framing if memcpy'd; re-serializing through a parse collapses them.
    if inner[span.0..span.1]
        .iter()
        .any(|b| matches!(b, b'\n' | b'\r'))
    {
        return process_event_via_tree(ctx, inner, span, sink);
    }

    let mut ty_span: Option<Span> = None;
    let mut ts_span: Option<Span> = None;
    let mut data_span: Option<Span> = None;
    let mut cv_span: Option<Span> = None;
    let mut seen = [false; 4];
    for entry in scan::object_entries(inner, span).map_err(|e| non_snapshot(e.0))? {
        let entry = entry.map_err(|e| non_snapshot(e.0))?;
        if entry.key_escaped {
            return process_event_via_tree(ctx, inner, span, sink);
        }
        let (slot, idx) = match &inner[entry.key.0..entry.key.1] {
            b"type" => (&mut ty_span, 0),
            b"timestamp" => (&mut ts_span, 1),
            b"data" => (&mut data_span, 2),
            b"cv" => (&mut cv_span, 3),
            _ => continue,
        };
        if seen[idx] {
            return process_event_via_tree(ctx, inner, span, sink);
        }
        seen[idx] = true;
        *slot = Some(entry.value);
    }

    let Some(ts) = valid_timestamp(ts_span.and_then(|s| scan::parse_number(inner, s))) else {
        return Ok(()); // invalid/missing timestamp: the event is filtered out
    };
    let ty = ty_span
        .and_then(|s| scan::parse_number(inner, s))
        .and_then(to_small_uint);
    let compressed = cv_span.map(|s| !scan::is_null(inner, s)).unwrap_or(false);

    // Everything the scrubbers touch lives inside `data`; events with no data object (or whose
    // type/source never routes to a scrubber) pass through byte-identical.
    let data_is_object = data_span
        .map(|s| scan::is_object(inner, s))
        .unwrap_or(false);
    let data = match data_span {
        Some(d) => d,
        None => {
            pass_through(inner, span, ts, ty, None, sink);
            return Ok(());
        }
    };

    let needs_parse = match ty {
        Some(TYPE_FULL_SNAPSHOT) => true,
        Some(TYPE_INCREMENTAL) | Some(TYPE_META) | Some(TYPE_CUSTOM) | Some(TYPE_PLUGIN) => {
            data_is_object
        }
        _ => false,
    };
    if !needs_parse {
        let dscan = if data_is_object {
            let d = scan_data(inner, data)?;
            if d.fallback {
                return process_event_via_tree(ctx, inner, span, sink);
            }
            Some(d)
        } else {
            None
        };
        pass_through(inner, span, ts, ty, dscan.map(|d| (d, data)), sink);
        return Ok(());
    }

    // Incremental events only route to a scrubber for mutation/input/canvas sources.
    if ty == Some(TYPE_INCREMENTAL) {
        let dscan = scan_data(inner, data)?;
        if dscan.fallback {
            return process_event_via_tree(ctx, inner, span, sink);
        }
        let source = dscan
            .source
            .and_then(|s| scan::parse_number(inner, s))
            .and_then(to_small_uint);
        if !matches!(
            source,
            Some(SOURCE_MUTATION) | Some(SOURCE_INPUT) | Some(SOURCE_CANVAS_MUTATION)
        ) {
            pass_through(inner, span, ts, ty, Some((dscan, data)), sink);
            return Ok(());
        }
    }

    // Scrub route: parse only the data span (own scratch — simd-json mutates its input) and splice
    // the re-serialized value back between the untouched surrounding bytes. The splice happens even
    // when nothing changed: JSON.parse dedupes duplicate keys, so re-serializing from the parsed tree
    // guarantees no shadowed duplicate content inside `data` survives in the raw bytes.
    sink.scratch.clear();
    sink.scratch.extend_from_slice(&inner[data.0..data.1]);
    let mut scratch = std::mem::take(&mut sink.scratch);
    let result = (|| -> SResult<()> {
        let mut value =
            parse_untrusted(&mut scratch).map_err(|e| non_snapshot(format!("event data: {e}")))?;
        route_data(ctx, ty, compressed, &mut value)
            .map_err(|e| Failure::new(FailKind::AnonymizeFailed, e.to_string()))?;
        sink.open_line();
        sink.lines.extend_from_slice(&inner[span.0..data.0]);
        value
            .write(&mut sink.lines)
            .expect("writing json to a Vec cannot fail");
        sink.lines.extend_from_slice(&inner[data.1..span.1]);
        sink.close_line();
        push_meta_from_data(ty, ts, Some(&value), sink);
        Ok(())
    })();
    sink.scratch = scratch;
    sink.scratch.clear();
    result
}

/// Emit a pass-through event: memcpy the span, derive meta from the scans.
fn pass_through(
    inner: &[u8],
    span: Span,
    ts: f64,
    ty: Option<u8>,
    data: Option<(DataScan, Span)>,
    sink: &mut Sink,
) {
    sink.open_line();
    sink.lines.extend_from_slice(&inner[span.0..span.1]);
    sink.close_line();

    let (source, interaction, href) = match &data {
        Some((d, _)) => (
            d.source
                .and_then(|s| scan::parse_number(inner, s))
                .and_then(to_small_uint),
            d.ty.and_then(|s| scan::parse_number(inner, s))
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
fn scanned_href(inner: &[u8], d: &DataScan) -> Option<String> {
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

    sink.open_line();
    event
        .write(&mut sink.lines)
        .expect("writing json to a Vec cannot fail");
    sink.close_line();

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
    let mut root =
        parse_untrusted(&mut buf).map_err(|e| non_snapshot(format!("event json: {e}")))?;

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

    let mut sink = Sink::new(window_id.as_deref().unwrap_or(""), inner.len());
    for event in items.iter_mut() {
        tree_event(ctx, event, &mut sink)?;
    }

    finish(
        distinct_id,
        ScannedEnvelope {
            items: (0, 0), // unused by finish
            session_id,
            window_id,
            snapshot_source,
            snapshot_library,
        },
        sink,
    )
}
