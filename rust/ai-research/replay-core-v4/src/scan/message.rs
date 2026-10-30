//! Reads a replay Kafka message from capture: `{"distinct_id", "data": "<json>"}`, where the inner JSON is
//! `{"event": "$snapshot_items", "properties": {"$session_id", "$window_id", "$snapshot_items": [...]}}`.

use std::sync::Arc;

use crate::bytescan::{self as scan, Span};

use super::cv::Expansion;

/// The one `cv` version the player decompresses (`decompressEvent`). It leaves an event with any other as it is.
pub const CV_VERSION: &str = "2024-10";

/// A window ID is a UUID from posthog-js, so a much longer one is not real.
pub const MAX_WINDOW_ID_BYTES: usize = 1024;

/// The timestamps a JavaScript `Date` holds, in milliseconds either side of 1970. A timestamp past them is not a real
/// time, and the index's integer columns must stay in the range JavaScript reads exactly.
pub const MAX_TIMESTAMP_MS: f64 = 8.64e15;

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ReadError {
    #[error("malformed message: {0}")]
    Malformed(&'static str),
    /// A repeated key could alias a key the reader looks for, and so could an escaped key that does not decode plainly.
    #[error("message has an escaped or repeated key")]
    AmbiguousKey,
    /// The message holds more events than the caller has room for.
    #[error("message has more events than the reader may hold")]
    TooManyEvents,
}

impl From<scan::ScanError> for ReadError {
    fn from(error: scan::ScanError) -> Self {
        ReadError::Malformed(error.0)
    }
}

/// The fields of one rrweb event that the recorder routes on. Spans index [`Message::inner`].
#[derive(Debug, Clone, PartialEq)]
pub struct Event {
    pub span: Span,
    pub kind: Option<u8>,
    pub timestamp_ms: Option<f64>,
    pub data: Option<Span>,
    /// `data.source` of an incremental snapshot. Only the top level of `data` is read.
    pub source: Option<u8>,
    /// The event carries `cv` [`CV_VERSION`]: parts of its data are gzip or zstd stored as latin-1 codepoints.
    pub compressed: bool,
    /// `data` has a top-level `href` or `payload`, where `hrefFrom` in `rrweb-types.ts` looks for a page URL on any
    /// event, so that an inspector reads a large `data` again only when it can hold one.
    pub may_carry_page_url: bool,
    /// Where `data.positions` starts in [`Message::inner`]. The reader passes it on its way to `source`, so that an
    /// inspector reads a mouse move's positions without scanning its `data` again.
    pub positions_start: Option<u32>,
    /// The compressed strings decoded, once per event by [`Message::decode_compressed`]. `None` until then.
    pub expansion: Option<Expansion>,
}

#[derive(Debug)]
pub struct Message {
    /// The inner JSON, unescaped. Event spans index it.
    pub inner: Vec<u8>,
    pub session_id: String,
    /// Shared, so that what refers to the window does not copy it.
    pub window_id: Option<Arc<str>>,
    pub snapshot_source: Option<String>,
    pub library: Option<String>,
    pub events: Vec<Event>,
}

/// Reads a decompressed Kafka payload. The buffer becomes the message's `inner` buffer, so nothing is copied.
pub fn read_message(payload: Vec<u8>) -> Result<Message, ReadError> {
    read_message_within(payload, usize::MAX)
}

/// As [`read_message`], with at most `max_events` events. The event list is the large allocation of a message of many
/// tiny events, so a caller with a memory budget refuses the message before it grows past that budget.
pub fn read_message_within(mut payload: Vec<u8>, max_events: usize) -> Result<Message, ReadError> {
    let root = scan::locate_value(&payload, 0)?;
    let mut data = None;
    for entry in scan::object_entries(&payload, root)? {
        let entry = entry?;
        if entry.key_escaped {
            return Err(ReadError::AmbiguousKey);
        }
        if &payload[entry.key.0..entry.key.1] == b"data" && data.replace(entry.value).is_some() {
            return Err(ReadError::AmbiguousKey);
        }
    }
    let data = data.ok_or(ReadError::Malformed("message has no data"))?;
    let (length, _) = scan::unescape_in_place(&mut payload, data)?;
    payload.copy_within(data.0 + 1..data.0 + 1 + length, 0);
    payload.truncate(length);
    canonicalize_keys(&mut payload);
    read_inner(payload, max_events)
}

/// Writes each object key that holds an escape as [`scan::write_json_string`] writes it, so that `"\u0073rc"` is
/// `"src"` to each reader that compares key bytes. `JSON.parse` reads both the same, so the JSON keeps its meaning. A
/// key that keeps an escape is not one a reader looks for. A key never grows, so the buffer is rewritten in place.
pub(crate) fn canonicalize_keys(bytes: &mut Vec<u8>) {
    if memchr::memchr(b'\\', bytes).is_none() {
        return;
    }
    let (mut read, mut write) = (0, 0);
    let mut key = Vec::new();
    while let Some(at) = memchr::memchr(b'"', &bytes[read..]) {
        let start = read + at;
        let Ok(end) = scan::skip_string(bytes, start) else {
            break;
        };
        key.clear();
        if bytes.get(scan::skip_ws(bytes, end)) == Some(&b':') && bytes[start..end].contains(&b'\\')
        {
            // `unescape` reads a lone surrogate as U+FFFD, which is another key, so such a key stays as it is.
            if let Ok(text) = scan::unescape(bytes, (start, end)) {
                if !text.contains('\u{fffd}') {
                    scan::write_json_string(&text, &mut key);
                }
            }
        }
        // A raw control character in a key is not JSON, and its escape would be longer.
        if key.is_empty() || key.len() > end - start {
            if write != read {
                bytes.copy_within(read..end, write);
            }
            write += end - read;
        } else {
            bytes.copy_within(read..start, write);
            write += start - read;
            bytes[write..write + key.len()].copy_from_slice(&key);
            write += key.len();
        }
        read = end;
    }
    bytes.copy_within(read.., write);
    let length = write + bytes.len() - read;
    bytes.truncate(length);
}

#[derive(Default)]
struct Properties {
    session_id: Option<Span>,
    window_id: Option<Span>,
    snapshot_source: Option<Span>,
    library: Option<Span>,
    items: Option<Span>,
}

fn read_inner(inner: Vec<u8>, max_events: usize) -> Result<Message, ReadError> {
    let root = scan::locate_value(&inner, 0)?;
    let mut properties = None;
    for entry in scan::object_entries(&inner, root)? {
        let entry = entry?;
        if entry.key_escaped {
            return Err(ReadError::AmbiguousKey);
        }
        if &inner[entry.key.0..entry.key.1] == b"properties"
            && properties.replace(entry.value).is_some()
        {
            return Err(ReadError::AmbiguousKey);
        }
    }
    let properties = properties.ok_or(ReadError::Malformed("message has no properties"))?;
    if !scan::is_object(&inner, properties) {
        return Err(ReadError::Malformed("properties is not an object"));
    }

    let mut found = Properties::default();
    for entry in scan::object_entries(&inner, properties)? {
        let entry = entry?;
        if entry.key_escaped {
            return Err(ReadError::AmbiguousKey);
        }
        let slot = match &inner[entry.key.0..entry.key.1] {
            b"$session_id" => &mut found.session_id,
            b"$window_id" => &mut found.window_id,
            b"$snapshot_source" => &mut found.snapshot_source,
            b"$lib" => &mut found.library,
            b"$snapshot_items" => &mut found.items,
            _ => continue,
        };
        if slot.replace(entry.value).is_some() {
            return Err(ReadError::AmbiguousKey);
        }
    }

    let session_id = string(&inner, found.session_id)?
        .ok_or(ReadError::Malformed("message has no $session_id"))?;
    let items = found
        .items
        .ok_or(ReadError::Malformed("message has no $snapshot_items"))?;
    let window_id = string(&inner, found.window_id)?;
    if window_id
        .as_ref()
        .is_some_and(|id| id.len() > MAX_WINDOW_ID_BYTES)
    {
        return Err(ReadError::Malformed("$window_id is too long"));
    }
    let mut events = Vec::new();
    for item in scan::array_items(&inner, items)? {
        if events.len() >= max_events {
            return Err(ReadError::TooManyEvents);
        }
        events.push(read_event(&inner, item?)?);
    }
    Ok(Message {
        window_id: window_id.map(Arc::from),
        snapshot_source: string(&inner, found.snapshot_source)?,
        library: string(&inner, found.library)?,
        session_id,
        events,
        inner,
    })
}

fn read_event(inner: &[u8], span: Span) -> Result<Event, ReadError> {
    if !scan::is_object(inner, span) {
        return Err(ReadError::Malformed("event is not an object"));
    }
    let mut event = Event {
        span,
        kind: None,
        timestamp_ms: None,
        data: None,
        source: None,
        compressed: false,
        may_carry_page_url: false,
        positions_start: None,
        expansion: None,
    };
    for entry in scan::object_entries(inner, span)? {
        let entry = entry?;
        if entry.key_escaped {
            return Err(ReadError::AmbiguousKey);
        }
        match &inner[entry.key.0..entry.key.1] {
            b"type" => event.kind = small_uint(inner, entry.value),
            b"timestamp" => {
                event.timestamp_ms =
                    scan::parse_number(inner, entry.value).filter(|ts| ts.abs() <= MAX_TIMESTAMP_MS)
            }
            b"data" => event.data = Some(entry.value),
            b"cv" => {
                event.compressed = scan::is_string(inner, entry.value)
                    && scan::unescape(inner, entry.value).is_ok_and(|v| v == CV_VERSION)
            }
            _ => {}
        }
    }
    if let Some(data) = event.data.filter(|&d| scan::is_object(inner, d)) {
        for entry in scan::object_entries(inner, data)? {
            let entry = entry?;
            if entry.key_escaped {
                continue;
            }
            match &inner[entry.key.0..entry.key.1] {
                b"source" => event.source = small_uint(inner, entry.value),
                b"href" | b"payload" => event.may_carry_page_url = true,
                b"positions" => event.positions_start = u32::try_from(entry.value.0).ok(),
                _ => {}
            }
        }
    }
    Ok(event)
}

fn small_uint(bytes: &[u8], span: Span) -> Option<u8> {
    let number = scan::parse_number(bytes, span)?;
    (number.fract() == 0.0 && (0.0..=f64::from(u8::MAX)).contains(&number)).then_some(number as u8)
}

fn string(bytes: &[u8], span: Option<Span>) -> Result<Option<String>, ReadError> {
    match span {
        Some(span) if scan::is_string(bytes, span) => {
            Ok(Some(scan::unescape(bytes, span)?.into_owned()))
        }
        Some(span) if scan::is_null(bytes, span) => Ok(None),
        Some(_) => Err(ReadError::Malformed("expected a string")),
        None => Ok(None),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    /// Wraps an inner message the way capture does: the inner JSON is a string inside `data`.
    fn capture_message(inner: &serde_json::Value) -> Vec<u8> {
        json!({"distinct_id": "d1", "data": inner.to_string()})
            .to_string()
            .into_bytes()
    }

    #[test]
    fn reads_the_envelope_and_each_events_routing_fields() {
        let inner = json!({
            "event": "$snapshot_items",
            "properties": {
                "$session_id": "019a2f3e-8c00-7000-8000-000000000007",
                "$window_id": "w1",
                "$snapshot_source": "web",
                "$lib": "web",
                "$snapshot_items": [
                    {"type": 4, "timestamp": 1000, "data": {"href": "https://example.com/\"quoted\"", "width": 1280}},
                    {"type": 2, "timestamp": 1001, "data": "\u{1f}\u{8b}gzip-as-latin1", "cv": "2024-10"},
                    {"type": 3, "timestamp": 1002.5, "data": {"source": 0, "adds": [{"node": {"source": 9}}]}},
                    {"type": 3, "timestamp": 1003, "data": {"source": 1}, "cv": null}
                ]
            }
        });
        let message = read_message(capture_message(&inner)).unwrap();

        assert_eq!(message.session_id, "019a2f3e-8c00-7000-8000-000000000007");
        assert_eq!(message.window_id.as_deref(), Some("w1"));
        assert_eq!(message.snapshot_source.as_deref(), Some("web"));
        let fields: Vec<_> = message
            .events
            .iter()
            .map(|e| (e.kind, e.timestamp_ms, e.source, e.compressed))
            .collect();
        assert_eq!(
            fields,
            vec![
                (Some(4), Some(1000.0), None, false),
                (Some(2), Some(1001.0), None, true),
                // The nested `source: 9` inside a mutation is not the event's source.
                (Some(3), Some(1002.5), Some(0), false),
                (Some(3), Some(1003.0), Some(1), false),
            ]
        );
        let meta = &message.events[0];
        let event: serde_json::Value =
            serde_json::from_slice(&message.inner[meta.span.0..meta.span.1]).unwrap();
        assert_eq!(event["data"]["href"], "https://example.com/\"quoted\"");
    }

    #[test]
    fn ignores_a_timestamp_no_clock_gives_and_stops_at_the_event_limit() {
        let items = json!([
            {"type": 3, "timestamp": 9_007_199_254_740_992_u64, "data": {"source": 1}},
            {"type": 3, "timestamp": -9_007_199_254_740_992_i64, "data": {"source": 1}},
            {"type": 3, "timestamp": 1e100, "data": {"source": 1}},
            {"type": 3, "timestamp": 1_792_056_600_000_u64, "data": {"source": 1}},
        ]);
        let payload = || {
            capture_message(
                &json!({"event": "$snapshot_items", "properties": {"$session_id": "s", "$snapshot_items": items}}),
            )
        };
        let message = read_message(payload()).unwrap();
        let timestamps: Vec<_> = message.events.iter().map(|e| e.timestamp_ms).collect();
        assert_eq!(timestamps, [None, None, None, Some(1_792_056_600_000.0)]);
        assert_eq!(
            read_message_within(payload(), 3).unwrap_err(),
            ReadError::TooManyEvents
        );
        assert!(read_message_within(payload(), 4).is_ok());
    }

    #[test]
    fn refuses_a_window_id_longer_than_any_real_one() {
        let read = |window_id: String| {
            read_message(capture_message(
                &json!({"event": "$snapshot_items", "properties": {
                    "$session_id": "s", "$window_id": window_id, "$snapshot_items": [],
                }}),
            ))
        };
        assert!(read("w".repeat(MAX_WINDOW_ID_BYTES)).is_ok());
        assert_eq!(
            read("w".repeat(MAX_WINDOW_ID_BYTES + 1)).unwrap_err(),
            ReadError::Malformed("$window_id is too long")
        );
    }

    #[test]
    fn reads_escaped_keys_as_their_text_and_refuses_repeated_ones() {
        let items = r#"[{"type":3,"timestamp":1,"data":{"source":1}}]"#;
        let read = |inner: &str| {
            read_message(
                json!({"distinct_id": "d1", "data": inner})
                    .to_string()
                    .into_bytes(),
            )
        };
        let cases = [
            format!(r#"{{"event":"$snapshot_items","properties":{{"$session_id":"a","$session_id":"b","$snapshot_items":{items}}}}}"#),
            format!(r#"{{"event":"$snapshot_items","properties":{{"$session_id":"a","$session\u005fid":"b","$snapshot_items":{items}}}}}"#),
            r#"{"event":"$snapshot_items","properties":{"$session_id":"a","$snapshot_items":[{"ty\"pe":2}]}}"#.to_owned(),
        ];
        for inner in cases {
            assert_eq!(
                read(&inner).unwrap_err(),
                ReadError::AmbiguousKey,
                "{inner}"
            );
        }

        let message = read(
            r#"{"event":"$snapshot_items","properties":{"$session\u005fid":"a","$snapshot_items":[{"ty\u0070e":3,"timestamp":1,"data":{"\u0073ource":0,"attributes":[{"id":1,"attributes":{"\u0073rc":"https://10.0.0.7/a.png","sr\u0063set":"\u0073rc","a\"b":1}}]}}]}}"#,
        )
        .unwrap();
        assert_eq!(message.session_id, "a");
        let event = &message.events[0];
        assert_eq!((event.kind, event.source), (Some(3), Some(0)));
        assert_eq!(
            std::str::from_utf8(&message.inner[event.span.0..event.span.1]).unwrap(),
            r#"{"type":3,"timestamp":1,"data":{"source":0,"attributes":[{"id":1,"attributes":{"src":"https://10.0.0.7/a.png","srcset":"\u0073rc","a\"b":1}}]}}"#
        );
    }
}
