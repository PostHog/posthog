//! Bench-only full-contract harness around the MLHog v2 walk: Kafka payload in, JSONL lines +
//! `SnapshotMeta` out — the same job as `crate::snapshot::anonymize_kafka_payload`, so the two can
//! be benchmarked and asserted equal with no caveats about envelope/meta/framing work.
//!
//! The envelope/meta machinery mirrors `snapshot.rs` (which is private to its module) using the
//! public `scan` primitives; the per-event scrub is `V2Worker::scrub_line`. The v2 walk re-scans
//! each line's routing keys internally (`schema::scan_event`) — that duplication is the real
//! integration cost of a line-oriented walker in this contract, so it is deliberately kept.
//!
//! Not production code: unlike `snapshot.rs`, per-event scrub failures inside `scrub_line` drop the
//! event silently (v2's contract) rather than failing the message, and raw-newline framing safety
//! is not enforced. The parity test pins output equality on the fixture corpus.

use crate::allow_lists::AllowLists;
use crate::context::Ctx;
use crate::json::reject_if_too_deep;
use crate::mlhog::schema;
use crate::mlhog::v2::V2Worker;
use crate::scan::{self, Span};
use crate::snapshot::{
    AnonymizedMessage, EventMeta, FailKind, Failure, Route, SnapshotMeta, FLAG_ACTIVE, FLAG_CLICK,
    FLAG_KEYPRESS, FLAG_MOUSE_ACTIVITY,
};

const MAX_JS_DATE_MS: f64 = 8.64e15;

fn failure(kind: FailKind, detail: impl Into<String>) -> Failure {
    Failure {
        kind,
        detail: detail.into(),
    }
}

pub fn anonymize_kafka_payload(
    allow: &AllowLists,
    payload: &mut [u8],
) -> Result<AnonymizedMessage, Failure> {
    let (distinct_id_span, data_span) = scan_outer(payload)
        .ok_or_else(|| failure(FailKind::InvalidJson, "outer envelope scan failed"))?;
    let distinct_id = scan::unescape(payload, distinct_id_span)
        .map_err(|e| failure(FailKind::InvalidJson, e.0))?
        .into_owned();
    let (len, ascii) = scan::unescape_in_place(payload, data_span)
        .map_err(|e| failure(FailKind::InvalidJson, e.0))?;
    let inner = &payload[data_span.0 + 1..data_span.0 + 1 + len];
    if !ascii && std::str::from_utf8(inner).is_err() {
        return Err(failure(FailKind::InvalidJson, "invalid utf-8"));
    }
    reject_if_too_deep(inner, "snapshot event json")
        .map_err(|e| failure(FailKind::NonSnapshotMessage, e.to_string()))?;
    anonymize_snapshot_data(allow, &distinct_id, inner)
}

fn non_snapshot(detail: &str) -> Failure {
    failure(FailKind::NonSnapshotMessage, detail)
}

/// One-pass scan of the outer `{distinct_id, data}` object (mirrors snapshot.rs).
fn scan_outer(payload: &[u8]) -> Option<(Span, Span)> {
    let mut pos = scan::skip_ws(payload, 0);
    if payload.get(pos) != Some(&b'{') {
        return None;
    }
    pos += 1;
    let (mut distinct_id, mut data) = (None, None);
    let mut first = true;
    loop {
        pos = scan::skip_ws(payload, pos);
        if payload.get(pos) == Some(&b'}') {
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
        pos = scan::skip_ws(payload, key_end);
        if payload.get(pos) != Some(&b':') {
            return None;
        }
        let vspan = scan::locate_value(payload, pos + 1).ok()?;
        match key {
            b"distinct_id" => distinct_id = Some(vspan),
            b"data" => data = Some(vspan),
            _ => {}
        }
        pos = vspan.1;
    }
    match (distinct_id, data) {
        (Some(d), Some(v)) if scan::is_string(payload, d) && scan::is_string(payload, v) => {
            Some((d, v))
        }
        _ => None,
    }
}

fn anonymize_snapshot_data(
    allow: &AllowLists,
    distinct_id: &str,
    inner: &[u8],
) -> Result<AnonymizedMessage, Failure> {
    let env = scan_envelope(inner)?;
    let window_id = env.window_id.clone().unwrap_or_default();
    let mut prefix = Vec::with_capacity(window_id.len() + 4);
    prefix.push(b'[');
    scan::write_json_string(&window_id, &mut prefix);
    prefix.push(b',');

    let ctx = Ctx::new(allow);
    let mut worker = V2Worker::default();
    let mut lines: Vec<u8> = Vec::with_capacity(env.items.1 - env.items.0);
    let mut events: Vec<EventMeta> = Vec::new();
    let mut console = [0u32; 3];

    let mut pos = env.items.0 + 1;
    let mut first = true;
    loop {
        pos = scan::skip_ws(inner, pos);
        if inner.get(pos) == Some(&b']') {
            break;
        }
        if !first {
            if inner.get(pos) != Some(&b',') {
                return Err(non_snapshot("expected ',' between array items"));
            }
            pos += 1;
        }
        first = false;
        let start = scan::skip_ws(inner, pos);
        if inner.get(start) != Some(&b'{') {
            let span = scan::locate_value(inner, start).map_err(|e| non_snapshot(e.0))?;
            pos = span.1;
            continue; // non-object events are filtered, like the TS parse step
        }
        let ev = scan_event(inner, start).ok_or_else(|| non_snapshot("event scan failed"))?;
        pos = ev.end;
        let Some(ts) = ev
            .ts
            .and_then(|s| scan::parse_number(inner, s))
            .filter(|t| *t > 0.0 && *t <= MAX_JS_DATE_MS)
        else {
            continue; // invalid/missing timestamp: filtered out
        };

        let ty = ev.ty.and_then(|s| small_uint(inner, s));
        let source = ev.source.and_then(|s| small_uint(inner, s));
        // Hand the walker the scan this loop already did (span discovery + meta) instead of letting
        // scrub_line re-derive it: v2's routing scan is redundant work in this contract.
        let scan = schema::EventScan {
            ty,
            source,
            compressed: ev.cv.map(|s| !scan::is_null(inner, s)).unwrap_or(false),
            data_range: ev.data.map(|d| (d.0 - start, d.1 - start)),
        };
        lines.extend_from_slice(&prefix);
        let mark = lines.len();
        worker.scrub_line_scanned(&ctx, &inner[start..ev.end], scan, &mut lines);
        if lines.len() == mark {
            // v2 dropped the line (its internal fail mode); drop the framing prefix too.
            lines.truncate(mark - prefix.len());
            continue;
        }
        let emitted = (mark, lines.len());
        let interaction = ev.interaction.and_then(|s| small_uint(inner, s));
        // href must be post-scrub (meta/plugin scrubs rewrite it); scrubs never add one, so the
        // emitted-bytes lookup only runs when the original had href/payload at all.
        let href = if ev.href.is_some() || ev.payload.is_some() {
            href_of_event(&lines[emitted.0..emitted.1])
        } else {
            None
        };
        if ty == Some(6) {
            if let Some(level) = console_level(inner, ev.data) {
                match level.as_str() {
                    "warn" | "countReset" => console[1] += 1,
                    "error" | "assert" => console[2] += 1,
                    _ => console[0] += 1,
                }
            }
        }
        lines.extend_from_slice(b"]\n");
        events.push(EventMeta {
            ts,
            flags: flags_of(ty, source, interaction),
            href,
        });
    }

    if events.is_empty() {
        return Err(failure(
            FailKind::NoValidEvents,
            "message contained no valid rrweb events",
        ));
    }
    let start_ts = events.iter().map(|e| e.ts).fold(f64::MAX, f64::min);
    let end_ts = events.iter().map(|e| e.ts).fold(f64::MIN, f64::max);
    Ok(AnonymizedMessage {
        lines,
        route: Route::Stream,
        meta: SnapshotMeta {
            distinct_id: distinct_id.to_string(),
            session_id: env.session_id,
            window_id: env.window_id.unwrap_or_default(),
            snapshot_source: env.snapshot_source,
            snapshot_library: env.snapshot_library,
            start_ts,
            end_ts,
            console_log_count: console[0],
            console_warn_count: console[1],
            console_error_count: console[2],
            events,
        },
    })
}

struct Envelope {
    items: Span,
    session_id: String,
    window_id: Option<String>,
    snapshot_source: Option<String>,
    snapshot_library: Option<String>,
}

/// One-pass envelope scan (mirrors snapshot.rs's; no fallback path — the bench corpus is clean).
fn scan_envelope(inner: &[u8]) -> Result<Envelope, Failure> {
    let root = scan::locate_value(inner, 0).map_err(|e| non_snapshot(e.0))?;
    if !scan::is_object(inner, root) {
        return Err(non_snapshot("event json is not an object"));
    }
    let mut event_span = None;
    let mut props_span = None;
    for entry in scan::object_entries(inner, root).map_err(|e| non_snapshot(e.0))? {
        let entry = entry.map_err(|e| non_snapshot(e.0))?;
        match &inner[entry.key.0..entry.key.1] {
            b"event" => event_span = Some(entry.value),
            b"properties" => props_span = Some(entry.value),
            _ => {}
        }
    }
    let event_span = event_span
        .filter(|s| scan::is_string(inner, *s))
        .ok_or_else(|| non_snapshot("missing event name"))?;
    if scan::unescape(inner, event_span).map_err(|e| non_snapshot(e.0))? != "$snapshot_items" {
        return Err(non_snapshot("not a $snapshot_items event"));
    }
    let props_span = props_span
        .filter(|s| scan::is_object(inner, *s))
        .ok_or_else(|| non_snapshot("missing properties object"))?;
    let mut items = None;
    let mut session_id = None;
    let mut window_id = None;
    let mut snapshot_source = None;
    let mut lib = None;
    for entry in scan::object_entries(inner, props_span).map_err(|e| non_snapshot(e.0))? {
        let entry = entry.map_err(|e| non_snapshot(e.0))?;
        match &inner[entry.key.0..entry.key.1] {
            b"$snapshot_items" => items = Some(entry.value),
            b"$session_id" => session_id = Some(entry.value),
            b"$window_id" => window_id = Some(entry.value),
            b"$snapshot_source" => snapshot_source = Some(entry.value),
            b"$lib" => lib = Some(entry.value),
            _ => {}
        }
    }
    let items = items
        .filter(|s| scan::is_array(inner, *s))
        .ok_or_else(|| non_snapshot("missing $snapshot_items"))?;
    let opt = |span: Option<Span>| -> Option<String> {
        span.filter(|s| scan::is_string(inner, *s))
            .and_then(|s| scan::unescape(inner, s).ok())
            .map(|c| c.into_owned())
    };
    let session_id = opt(session_id).filter(|s| !s.is_empty()).ok_or_else(|| {
        non_snapshot("missing $session_id")
    })?;
    Ok(Envelope {
        items,
        session_id,
        window_id: opt(window_id),
        snapshot_source: opt(snapshot_source),
        snapshot_library: opt(lib),
    })
}

#[derive(Default)]
struct Ev {
    end: usize,
    ty: Option<Span>,
    ts: Option<Span>,
    cv: Option<Span>,
    data: Option<Span>,
    // Depth-1 of data:
    source: Option<Span>,
    interaction: Option<Span>,
    href: Option<Span>,
    payload: Option<Span>,
}

/// One-pass depth-1 event scan capturing the span end + routing/meta fields (mirrors
/// snapshot.rs's `scan_event`, via the public scan primitives).
fn scan_event(inner: &[u8], start: usize) -> Option<Ev> {
    let mut ev = Ev::default();
    let mut pos = start + 1;
    let mut first = true;
    loop {
        pos = scan::skip_ws(inner, pos);
        if inner.get(pos) == Some(&b'}') {
            ev.end = pos + 1;
            return Some(ev);
        }
        if !first {
            if inner.get(pos) != Some(&b',') {
                return None;
            }
            pos = scan::skip_ws(inner, pos + 1);
        }
        first = false;
        if inner.get(pos) != Some(&b'"') {
            return None;
        }
        let key_end = scan::skip_string(inner, pos).ok()?;
        let key = &inner[pos + 1..key_end - 1];
        pos = scan::skip_ws(inner, key_end);
        if inner.get(pos) != Some(&b':') {
            return None;
        }
        let vstart = scan::skip_ws(inner, pos + 1);
        if key == b"data" && inner.get(vstart) == Some(&b'{') && ev.data.is_none() {
            let dend = scan_data(inner, vstart, &mut ev)?;
            ev.data = Some((vstart, dend));
            pos = dend;
            continue;
        }
        let vspan = scan::locate_value(inner, vstart).ok()?;
        match key {
            b"type" => ev.ty = Some(vspan),
            b"timestamp" => ev.ts = Some(vspan),
            b"cv" => ev.cv = Some(vspan),
            b"data" => ev.data = Some(vspan),
            _ => {}
        }
        pos = vspan.1;
    }
}

fn scan_data(inner: &[u8], start: usize, ev: &mut Ev) -> Option<usize> {
    let mut pos = start + 1;
    let mut first = true;
    loop {
        pos = scan::skip_ws(inner, pos);
        if inner.get(pos) == Some(&b'}') {
            return Some(pos + 1);
        }
        if !first {
            if inner.get(pos) != Some(&b',') {
                return None;
            }
            pos = scan::skip_ws(inner, pos + 1);
        }
        first = false;
        if inner.get(pos) != Some(&b'"') {
            return None;
        }
        let key_end = scan::skip_string(inner, pos).ok()?;
        let key = &inner[pos + 1..key_end - 1];
        pos = scan::skip_ws(inner, key_end);
        if inner.get(pos) != Some(&b':') {
            return None;
        }
        let vspan = scan::locate_value(inner, pos + 1).ok()?;
        match key {
            b"source" => ev.source = Some(vspan),
            b"type" => ev.interaction = Some(vspan),
            b"href" => ev.href = Some(vspan),
            b"payload" => ev.payload = Some(vspan),
            _ => {}
        }
        pos = vspan.1;
    }
}

fn small_uint(inner: &[u8], span: Span) -> Option<u8> {
    let n = scan::parse_number(inner, span)?;
    (n.fract() == 0.0 && (0.0..=u8::MAX as f64).contains(&n)).then_some(n as u8)
}

/// `hrefFrom` over an emitted (post-scrub) event: `data.href` else `data.payload.href`.
fn href_of_event(event: &[u8]) -> Option<String> {
    let root = scan::locate_value(event, 0).ok()?;
    let mut data = None;
    for entry in scan::object_entries(event, root).ok()? {
        let entry = entry.ok()?;
        if &event[entry.key.0..entry.key.1] == b"data" {
            data = Some(entry.value);
        }
    }
    let data = data.filter(|d| scan::is_object(event, *d))?;
    let mut href = None;
    let mut payload = None;
    for entry in scan::object_entries(event, data).ok()? {
        let entry = entry.ok()?;
        match &event[entry.key.0..entry.key.1] {
            b"href" => href = Some(entry.value),
            b"payload" => payload = Some(entry.value),
            _ => {}
        }
    }
    let read = |span: Span| -> Option<String> {
        if !scan::is_string(event, span) {
            return None;
        }
        let s = scan::unescape(event, span).ok()?;
        let t = s.trim();
        (!t.is_empty()).then(|| t.to_string())
    };
    if let Some(h) = href.and_then(read) {
        return Some(h);
    }
    let payload = payload.filter(|p| scan::is_object(event, *p))?;
    let mut ph = None;
    for entry in scan::object_entries(event, payload).ok()? {
        let entry = entry.ok()?;
        if &event[entry.key.0..entry.key.1] == b"href" {
            ph = Some(entry.value);
        }
    }
    ph.and_then(read)
}

/// `rrweb/console@1` level of a plugin event's data (level strings survive the scrub untouched).
fn console_level(inner: &[u8], data: Option<Span>) -> Option<String> {
    let data = data.filter(|d| scan::is_object(inner, *d))?;
    let mut plugin = None;
    let mut payload = None;
    for entry in scan::object_entries(inner, data).ok()? {
        let entry = entry.ok()?;
        match &inner[entry.key.0..entry.key.1] {
            b"plugin" => plugin = Some(entry.value),
            b"payload" => payload = Some(entry.value),
            _ => {}
        }
    }
    let plugin = plugin.filter(|p| scan::is_string(inner, *p))?;
    if scan::unescape(inner, plugin).ok()? != "rrweb/console@1" {
        return None;
    }
    // Console counting mirrors `push_meta_from_data`: any console plugin event counts; absent or
    // non-string levels land in the log bucket.
    let level = payload
        .filter(|p| scan::is_object(inner, *p))
        .and_then(|p| {
            let mut level = None;
            for entry in scan::object_entries(inner, p).ok()? {
                let entry = entry.ok()?;
                if &inner[entry.key.0..entry.key.1] == b"level" {
                    level = Some(entry.value);
                }
            }
            level
        })
        .filter(|l| scan::is_string(inner, *l))
        .and_then(|l| scan::unescape(inner, l).ok())
        .map(|c| c.into_owned());
    Some(level.unwrap_or_default())
}

fn flags_of(ty: Option<u8>, source: Option<u8>, interaction: Option<u8>) -> u8 {
    if ty != Some(3) {
        return 0;
    }
    let Some(s) = source else {
        return 0;
    };
    let mut flags = 0u8;
    if matches!(s, 1..=7 | 12) {
        flags |= FLAG_ACTIVE;
    }
    if s == 2 && matches!(interaction, Some(2) | Some(3) | Some(4) | Some(9)) {
        flags |= FLAG_CLICK;
    }
    if s == 5 {
        flags |= FLAG_KEYPRESS;
    }
    if matches!(s, 1 | 2 | 6) {
        flags |= FLAG_MOUSE_ACTIVITY;
    }
    flags
}
