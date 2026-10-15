//! `cv` events: posthog-js compresses a full snapshot's data, and the lists of a mutation or a style sheet rule, as gzip
//! stored one byte per latin-1 codepoint in a JSON string. A v4 block stores these strings expanded, as the JSON the
//! player decompresses them to, so a reader never decompresses them again.

use std::borrow::Cow;

use posthog_replay_anonymizer::compression;
use posthog_replay_anonymizer::scan::{self, Span};
use serde::de::IgnoredAny;

use super::canvas;
use super::images::{extract_images, ImageSink};
use super::message::{Event, Message};

const FULL_SNAPSHOT: u8 = 2;
const INCREMENTAL_SNAPSHOT: u8 = 3;
const MUTATION: u8 = 0;
const STYLE_SHEET_RULE: u8 = 8;

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum CvError {
    #[error("cv string is not latin-1")]
    NotLatin1,
    #[error("cv payload does not decompress: {0}")]
    Decompress(String),
    #[error("malformed cv string: {0}")]
    Malformed(&'static str),
}

/// Decodes the JSON string at `span` to the JSON it compresses.
pub fn decode(bytes: &[u8], span: Span) -> Result<Vec<u8>, CvError> {
    let text = scan::unescape(bytes, span).map_err(|e| CvError::Malformed(e.0))?;
    let mut compressed = Vec::with_capacity(text.len());
    for c in text.chars() {
        compressed.push(u8::try_from(u32::from(c)).map_err(|_| CvError::NotLatin1)?);
    }
    compression::decompress_by_magic(&compressed).map_err(|e| CvError::Decompress(format!("{e:#}")))
}

#[derive(Debug, Clone, PartialEq)]
pub struct Decoded {
    /// The string in [`Message::inner`].
    pub span: Span,
    /// The JSON it decodes to. `None` for an empty string or `null`, which the player reads as absent.
    pub json: Option<Vec<u8>>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Expansion {
    /// Nothing in the event is a string the player decompresses.
    Plain,
    Decoded(Vec<Decoded>),
    /// A compressed string does not decode. The player then drops the event, and the block stores it as it arrived.
    Failed,
    /// The message used up its decode budget before this event. The block stores it as it arrived, and what the
    /// player does with it is not known.
    Skipped,
}

impl Expansion {
    /// The decoded JSON of the compressed string at `span`. `None` when the event has no decoded string there.
    pub fn json(&self, span: Span) -> Option<Option<&[u8]>> {
        match self {
            Expansion::Decoded(fields) => fields
                .iter()
                .find(|field| field.span == span)
                .map(|field| field.json.as_deref()),
            _ => None,
        }
    }

    fn bytes(&self) -> usize {
        match self {
            Expansion::Decoded(fields) => fields
                .iter()
                .filter_map(|f| f.json.as_ref())
                .map(Vec::len)
                .sum(),
            _ => 0,
        }
    }
}

/// The values the player's `decompressEvent` decompresses: a full snapshot's `data`, a mutation's four lists when it
/// has `texts`, and a style sheet rule's `adds` and `removes`. `None` when a key is escaped or repeated.
fn compressed_values(inner: &[u8], event: &Event) -> Option<Vec<Span>> {
    let Some(data) = event.data.filter(|_| event.compressed) else {
        return Some(Vec::new());
    };
    let names: &[&[u8]] = match (event.kind, event.source) {
        (Some(FULL_SNAPSHOT), _) => {
            return Some(
                scan::is_string(inner, data)
                    .then_some(data)
                    .into_iter()
                    .collect(),
            )
        }
        (Some(INCREMENTAL_SNAPSHOT), Some(MUTATION)) => {
            &[b"adds", b"removes", b"texts", b"attributes"]
        }
        (Some(INCREMENTAL_SNAPSHOT), Some(STYLE_SHEET_RULE)) => &[b"adds", b"removes"],
        _ => return Some(Vec::new()),
    };
    let mut values = vec![None; names.len()];
    for entry in scan::object_entries(inner, data).ok()? {
        let entry = entry.ok()?;
        if entry.key_escaped {
            return None;
        }
        if let Some(index) = names
            .iter()
            .position(|&n| n == &inner[entry.key.0..entry.key.1])
        {
            if values[index].replace(entry.value).is_some() {
                return None;
            }
        }
    }
    if event.source == Some(MUTATION) && values[2].is_none() {
        return Some(Vec::new());
    }
    Some(values.into_iter().flatten().collect())
}

/// Decodes an event's compressed strings with the player's rules: an empty string or `null` is absent, and anything
/// that does not decode to one JSON value fails the whole event.
pub fn expand(inner: &[u8], event: &Event) -> Expansion {
    let Some(values) = compressed_values(inner, event) else {
        return Expansion::Failed;
    };
    if values.is_empty() {
        return Expansion::Plain;
    }
    let mut fields = Vec::with_capacity(values.len());
    for span in values {
        let json = if scan::is_null(inner, span) || &inner[span.0..span.1] == b"\"\"" {
            None
        } else {
            match decode(inner, span) {
                // The player's JSON.parse rejects the event when the decoded text is not valid JSON.
                Ok(json) if serde_json::from_slice::<IgnoredAny>(&json).is_ok() => Some(json),
                _ => return Expansion::Failed,
            }
        };
        fields.push(Decoded { span, json });
    }
    Expansion::Decoded(fields)
}

/// The event's expansion: the one [`Message::decode_compressed`] stored, or one decoded now.
pub fn expansion<'e>(inner: &[u8], event: &'e Event) -> Cow<'e, Expansion> {
    match &event.expansion {
        Some(expansion) => Cow::Borrowed(expansion),
        None => Cow::Owned(expand(inner, event)),
    }
}

/// The decoded bytes one message may hold, as in v3. Each field has its own cap, but a small message can carry many.
const MESSAGE_DECODE_BUDGET: usize = 256 * 1024 * 1024;

impl Message {
    /// Decodes every compressed string once, so that the inspector and the block writer share the work.
    pub fn decode_compressed(&mut self) {
        self.decode_within(MESSAGE_DECODE_BUDGET);
    }

    /// An event that does not fit in what is left of `budget` stays as it arrived.
    fn decode_within(&mut self, mut budget: usize) {
        for event in &mut self.events {
            if event.expansion.is_some() {
                continue;
            }
            let expansion = if event.compressed && budget == 0 {
                Expansion::Skipped
            } else {
                expand(&self.inner, event)
            };
            event.expansion = Some(match budget.checked_sub(expansion.bytes()) {
                Some(left) => {
                    budget = left;
                    expansion
                }
                None => {
                    budget = 0;
                    Expansion::Skipped
                }
            });
        }
    }

    /// The bytes the message holds: its inner JSON and the decoded strings.
    pub fn buffered_bytes(&self) -> usize {
        self.inner.len()
            + self
                .events
                .iter()
                .filter_map(|e| e.expansion.as_ref())
                .map(Expansion::bytes)
                .sum::<usize>()
    }
}

/// Builds the output of one event, copying unchanged bytes only once something changes.
struct Output<'b> {
    bytes: &'b [u8],
    start: usize,
    end: usize,
    copied_to: usize,
    out: Option<Vec<u8>>,
}

impl<'b> Output<'b> {
    fn new(bytes: &'b [u8], span: Span) -> Self {
        Self {
            bytes,
            start: span.0,
            end: span.1,
            copied_to: span.0,
            out: None,
        }
    }

    fn changed(&mut self) -> &mut Vec<u8> {
        let (bytes, start, end, copied_to) = (self.bytes, self.start, self.end, self.copied_to);
        self.out.get_or_insert_with(|| {
            let mut out = Vec::with_capacity(end - start);
            out.extend_from_slice(&bytes[start..copied_to]);
            out
        })
    }

    fn scan_to(&mut self, end: usize, sink: &mut ImageSink<'_>) {
        match extract_images(&self.bytes[self.copied_to..end], sink) {
            Cow::Owned(extracted) => self.changed().extend_from_slice(&extracted),
            Cow::Borrowed(same) => {
                if let Some(out) = self.out.as_mut() {
                    out.extend_from_slice(same);
                }
            }
        }
        self.copied_to = end;
    }

    fn replace(&mut self, span: Span, with: &[u8], sink: &mut ImageSink<'_>) {
        self.scan_to(span.0, sink);
        self.changed().extend_from_slice(with);
        self.copied_to = span.1;
    }
}

/// The event as a v4 block stores it, or `None` when that is the event as it arrived. Inline images become references,
/// and the compressed strings of a `cv` event are expanded to JSON, without the `cv` marker. An event whose strings
/// do not decode stays as it arrived, `cv` and images included.
pub fn extract_event_images(
    inner: &[u8],
    event: &Event,
    sink: &mut ImageSink<'_>,
) -> Option<Vec<u8>> {
    match &*expansion(inner, event) {
        Expansion::Failed | Expansion::Skipped => None,
        Expansion::Decoded(fields) => Some(expanded(inner, event, fields, sink)),
        Expansion::Plain => {
            let mut output = Output::new(inner, event.span);
            let frame = event
                .data
                .and_then(|data| canvas::frame_image(inner, event.kind, event.source, data));
            if let Some((mime, span)) = frame {
                let payload = scan::unescape(inner, span).ok();
                match payload.and_then(|p| sink.take(mime, p.as_bytes())) {
                    Some(reference) => {
                        let mut quoted = Vec::with_capacity(reference.len() + 2);
                        scan::write_json_string(&reference, &mut quoted);
                        output.replace(span, &quoted, sink);
                    }
                    None => sink.left_inline += 1,
                }
            }
            output.scan_to(event.span.1, sink);
            output.out
        }
    }
}

/// Writes the object at `span` entry by entry. `value` writes an entry's value, or returns false to leave the entry out.
fn write_object(
    bytes: &[u8],
    span: Span,
    out: &mut Vec<u8>,
    sink: &mut ImageSink<'_>,
    mut value: impl FnMut(&[u8], Span, &mut Vec<u8>, &mut ImageSink<'_>) -> bool,
) {
    out.push(b'{');
    let mut first = true;
    for entry in scan::object_entries(bytes, span)
        .into_iter()
        .flatten()
        .flatten()
    {
        let mark = out.len();
        if !first {
            out.push(b',');
        }
        out.extend_from_slice(&bytes[entry.key.0 - 1..entry.key.1 + 1]);
        out.push(b':');
        if value(&bytes[entry.key.0..entry.key.1], entry.value, out, sink) {
            first = false;
        } else {
            out.truncate(mark);
        }
    }
    out.push(b'}');
}

fn expanded(inner: &[u8], event: &Event, fields: &[Decoded], sink: &mut ImageSink<'_>) -> Vec<u8> {
    let mut out = Vec::with_capacity(event.span.1 - event.span.0);
    let json = |span: Span| {
        fields
            .iter()
            .find(|f| f.span == span)
            .map(|f| f.json.as_deref())
    };
    write_object(
        inner,
        event.span,
        &mut out,
        sink,
        |key, value, out, sink| {
            if key == b"cv" {
                return false;
            }
            if key == b"data" {
                if let Some(decoded) = json(value) {
                    // A full snapshot whose data is empty has no data, as in the player.
                    let Some(decoded) = decoded else { return false };
                    out.extend_from_slice(&extract_images(decoded, sink));
                    return true;
                }
                if scan::is_object(inner, value) {
                    write_object(inner, value, out, sink, |_, value, out, sink| {
                        match json(value) {
                            Some(Some(decoded)) => {
                                out.extend_from_slice(&extract_images(decoded, sink))
                            }
                            Some(None) => return false,
                            None => out
                                .extend_from_slice(&extract_images(&inner[value.0..value.1], sink)),
                        }
                        true
                    });
                    return true;
                }
            }
            out.extend_from_slice(&extract_images(&inner[value.0..value.1], sink));
            true
        },
    );
    out
}

#[cfg(test)]
mod tests {
    use base64::engine::general_purpose::STANDARD;
    use base64::Engine;
    use serde_json::{json, Value};

    use super::*;
    use crate::scan::images::ImageLimits;
    use crate::scan::message::read_message;

    const KEY: [u8; 32] = [3; 32];

    /// The posthog-js wire form: gzip, one byte per latin-1 codepoint.
    fn sdk_cv(value: &Value) -> String {
        sdk_cv_text(&value.to_string())
    }

    fn sdk_cv_text(text: &str) -> String {
        compression::gzip(text.as_bytes())
            .unwrap()
            .iter()
            .map(|&b| char::from(b))
            .collect()
    }

    fn message_with(events: Value) -> Message {
        let inner = json!({"event": "$snapshot_items", "properties": {"$session_id": "s", "$snapshot_items": events}});
        read_message(
            json!({"distinct_id": "d", "data": inner.to_string()})
                .to_string()
                .into_bytes(),
        )
        .unwrap()
    }

    fn sink() -> ImageSink<'static> {
        ImageSink::new(&KEY, 7, "2026-10-15", ImageLimits::default())
    }

    #[test]
    fn stores_cv_events_expanded_with_their_images_moved_out() {
        let image = format!("data:image/png;base64,{}", STANDARD.encode(b"png bytes"));
        let snapshot = json!({"node": {"attributes": {"src": image}}, "initialOffset": {"top": 0}});
        let adds = json!([{"parentId": 1, "node": {"attributes": {"src": image}}}]);
        let mut message = message_with(json!([
            {"type": 2, "timestamp": 1, "data": sdk_cv(&snapshot), "cv": "2024-10"},
            // The player reads an empty `removes` as absent.
            {"type": 3, "timestamp": 2, "cv": "2024-10", "data": {"source": 0, "adds": sdk_cv(&adds), "removes": "",
                "texts": sdk_cv(&json!([{"id": 2, "value": "kept"}])), "attributes": sdk_cv(&json!([{"id": 3, "attributes": {"src": image}}]))}},
        ]));
        message.decode_compressed();
        let mut sink = sink();
        let stored: Vec<Value> = message
            .events
            .iter()
            .map(|e| {
                serde_json::from_slice(&extract_event_images(&message.inner, e, &mut sink).unwrap())
                    .unwrap()
            })
            .collect();

        let reference = sink.images[0].reference.clone();
        assert_eq!(sink.images.len(), 1);
        assert_eq!(
            stored[0],
            json!({"type": 2, "timestamp": 1, "data": {"node": {"attributes": {"src": reference}}, "initialOffset": {"top": 0}}})
        );
        assert_eq!(
            stored[1],
            json!({"type": 3, "timestamp": 2, "data": {"source": 0, "adds": [{"parentId": 1, "node": {"attributes": {"src": reference}}}],
                "texts": [{"id": 2, "value": "kept"}], "attributes": [{"id": 3, "attributes": {"src": reference}}]}})
        );
    }

    #[test]
    fn leaves_the_events_past_the_message_budget_as_they_arrived() {
        let data = json!({"node": {"type": 0, "childNodes": [], "id": 1}});
        let size = data.to_string().len();
        let mut message = message_with(json!([
            {"type": 2, "timestamp": 1, "data": sdk_cv(&data), "cv": "2024-10"},
            {"type": 2, "timestamp": 2, "data": sdk_cv(&data), "cv": "2024-10"},
            {"type": 3, "timestamp": 3, "data": {"source": 1}},
        ]));
        message.decode_within(size + size / 2);
        let expansions: Vec<_> = message
            .events
            .iter()
            .map(|e| e.expansion.as_ref().unwrap())
            .collect();
        assert!(matches!(expansions[0], Expansion::Decoded(_)));
        assert_eq!(expansions[1], &Expansion::Skipped);
        assert_eq!(expansions[2], &Expansion::Plain);
        let mut sink = sink();
        assert_eq!(
            extract_event_images(&message.inner, &message.events[1], &mut sink),
            None
        );
    }

    #[test]
    fn leaves_a_cv_event_that_does_not_decode_as_it_arrived() {
        let image = format!("data:image/png;base64,{}", STANDARD.encode(b"png bytes"));
        let message = message_with(json!([
            {"type": 2, "timestamp": 1, "data": format!("not gzip {image}"), "cv": "2024-10"},
            // One list that does not decode fails the whole event, as in the player. So does a list sent uncompressed.
            {"type": 3, "timestamp": 2, "cv": "2024-10", "data": {"source": 0, "adds": sdk_cv(&json!([])), "texts": "not gzip"}},
            {"type": 3, "timestamp": 3, "cv": "2024-10", "data": {"source": 0, "adds": sdk_cv(&json!([])), "texts": sdk_cv(&json!([])),
                "attributes": [{"id": 3, "attributes": {"src": image}}]}},
            // Valid gzip of text that JSON.parse rejects.
            {"type": 2, "timestamp": 4, "data": sdk_cv_text(&format!(r#"{{"node":undefined,"src":"{image}"}}"#)), "cv": "2024-10"},
        ]));
        let mut sink = sink();
        for event in &message.events {
            assert_eq!(extract_event_images(&message.inner, event, &mut sink), None);
        }
        assert!(sink.images.is_empty());
    }

    #[test]
    fn moves_only_the_posthog_js_canvas_frame() {
        let frame = |draw_args: Value| {
            json!({"type": 3, "timestamp": 1, "data": {"source": 9, "id": 4, "type": 0, "commands": [
                {"property": "clearRect", "args": [0, 0, 8, 8]},
                {"property": "drawImage", "args": draw_args},
            ]}})
        };
        let bitmap = |mime: &str, buffer: &str| {
            json!({"rr_type": "ImageBitmap", "args": [{"rr_type": "Blob", "type": mime,
                "data": [{"rr_type": buffer, "base64": STANDARD.encode(b"frame bytes")}]}]})
        };
        let cases = [
            (
                frame(json!([bitmap("image/webp", "ArrayBuffer"), 0, 0, 8, 8])),
                true,
            ),
            (
                frame(json!([bitmap("image/png", "ArrayBuffer"), 0, 0])),
                true,
            ),
            (
                frame(json!([bitmap("image/gif", "ArrayBuffer"), 0, 0])),
                false,
            ),
            (
                frame(json!([bitmap("image/png", "Uint8Array"), 0, 0])),
                false,
            ),
            (frame(json!([bitmap("image/png", "ArrayBuffer"), 0])), false),
            (
                json!({"type": 3, "timestamp": 1, "data": {"source": 9, "id": 4, "type": 0, "commands": [
                    {"property": "putImageData", "args": [{"rr_type": "ArrayBuffer", "base64": STANDARD.encode(b"pixels")}, 0, 0]},
                ]}}),
                false,
            ),
        ];
        for (event, moved) in cases {
            let message = message_with(json!([event]));
            let mut sink = sink();
            let stored = extract_event_images(&message.inner, &message.events[0], &mut sink);
            assert_eq!(stored.is_some(), moved, "{event}");
            if let Some(stored) = stored {
                let stored: Value = serde_json::from_slice(&stored).unwrap();
                let blob = &stored["data"]["commands"][1]["args"][0]["args"][0];
                assert_eq!(blob["data"][0]["base64"], sink.images[0].reference.as_str());
                assert_eq!(blob["type"], sink.images[0].mime.as_str());
            }
        }
    }
}
