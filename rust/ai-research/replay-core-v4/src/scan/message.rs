//! Reads a replay Kafka message from capture: `{"distinct_id", "data": "<json>"}`, where the inner JSON is
//! `{"event": "$snapshot_items", "properties": {"$session_id", "$window_id", "$snapshot_items": [...]}}`.

use posthog_replay_anonymizer::scan::{self, Span};

use super::cv::Expansion;

/// The one `cv` version the player decompresses (`decompressEvent`). It leaves an event with any other as it is.
pub const CV_VERSION: &str = "2024-10";

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ReadError {
    #[error("malformed message: {0}")]
    Malformed(&'static str),
    /// An escaped or repeated key could alias a key the reader looks for, and byte comparison would miss it.
    #[error("message has an escaped or repeated key")]
    AmbiguousKey,
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
    /// The compressed strings decoded, once per event by [`Message::decode_compressed`]. `None` until then.
    pub expansion: Option<Expansion>,
}

#[derive(Debug)]
pub struct Message {
    /// The inner JSON, unescaped. Event spans index it.
    pub inner: Vec<u8>,
    pub session_id: String,
    pub window_id: Option<String>,
    pub snapshot_source: Option<String>,
    pub library: Option<String>,
    pub events: Vec<Event>,
}

/// Reads a decompressed Kafka payload. The buffer becomes the message's `inner` buffer, so nothing is copied.
pub fn read_message(mut payload: Vec<u8>) -> Result<Message, ReadError> {
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
    read_inner(payload)
}

#[derive(Default)]
struct Properties {
    session_id: Option<Span>,
    window_id: Option<Span>,
    snapshot_source: Option<Span>,
    library: Option<Span>,
    items: Option<Span>,
}

fn read_inner(inner: Vec<u8>) -> Result<Message, ReadError> {
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
    let mut events = Vec::new();
    for item in scan::array_items(&inner, items)? {
        events.push(read_event(&inner, item?)?);
    }
    Ok(Message {
        window_id: string(&inner, found.window_id)?,
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
        expansion: None,
    };
    for entry in scan::object_entries(inner, span)? {
        let entry = entry?;
        if entry.key_escaped {
            return Err(ReadError::AmbiguousKey);
        }
        match &inner[entry.key.0..entry.key.1] {
            b"type" => event.kind = small_uint(inner, entry.value),
            b"timestamp" => event.timestamp_ms = scan::parse_number(inner, entry.value),
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
            if !entry.key_escaped && &inner[entry.key.0..entry.key.1] == b"source" {
                event.source = small_uint(inner, entry.value);
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
    fn refuses_keys_it_could_misread() {
        let items = r#"[{"type":3,"timestamp":1,"data":{"source":1}}]"#;
        let cases = [
            format!(r#"{{"event":"$snapshot_items","properties":{{"$session_id":"a","$session_id":"b","$snapshot_items":{items}}}}}"#),
            format!(r#"{{"event":"$snapshot_items","properties":{{"$session\u005fid":"a","$snapshot_items":{items}}}}}"#),
            r#"{"event":"$snapshot_items","properties":{"$session_id":"a","$snapshot_items":[{"ty\u0070e":2}]}}"#.to_owned(),
        ];
        for inner in cases {
            let payload = json!({"distinct_id": "d1", "data": inner})
                .to_string()
                .into_bytes();
            assert_eq!(
                read_message(payload).unwrap_err(),
                ReadError::AmbiguousKey,
                "{inner}"
            );
        }
    }
}
