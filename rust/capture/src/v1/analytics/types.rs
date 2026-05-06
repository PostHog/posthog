use std::io;
use std::ops::Not;

use chrono::{DateTime, SecondsFormat, Utc};
use common_types::{CapturedEventHeaders, HasEventName};
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use uuid::Uuid;

/// Safe adapter for writing serde_json output into a `String` buffer.
/// `from_utf8` on serde_json output is essentially free (JSON mandates UTF-8).
struct StringWriter<'a>(&'a mut String);

impl io::Write for StringWriter<'_> {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        let s = std::str::from_utf8(buf).map_err(io::Error::other)?;
        self.0.push_str(s);
        Ok(buf.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

use crate::v1::context::Context;
use crate::v1::sinks::event::Event as SinkEvent;
use crate::v1::sinks::Destination;

fn empty_raw_object() -> Box<RawValue> {
    RawValue::from_string("{}".to_owned()).unwrap()
}

/// Per-event outcome in the batch response.
/// Maps to HTTP semantics: Ok (2xx), Drop (4xx), Limited (429), Retry (5xx).
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EventResult {
    #[default]
    Ok,
    Drop,
    Limited,
    Retry,
}

#[derive(Debug, Deserialize)]
pub struct Batch {
    pub created_at: String,
    #[serde(default)]
    pub historical_migration: bool,
    #[serde(default)]
    pub capture_internal: Option<bool>,
    pub batch: Vec<Event>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Options {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cookieless_mode: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub disable_skew_adjustment: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub product_tour_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub process_person_profile: Option<bool>,
}

#[derive(Debug, Deserialize)]
pub struct Event {
    pub event: String,
    pub uuid: String,
    pub distinct_id: String,
    pub timestamp: String,
    pub session_id: Option<String>,
    pub window_id: Option<String>,
    pub options: Options,
    #[serde(default = "empty_raw_object")]
    pub properties: Box<RawValue>,
}

impl Event {
    /// Trimmed accessor for the raw UUID string. Prefer this over direct
    /// field access so callers are insulated from client-submitted whitespace.
    pub fn uuid(&self) -> &str {
        self.uuid.trim()
    }
}

#[derive(Debug)]
pub struct WrappedEvent {
    pub event: Event,
    /// Pre-parsed UUID from Event.uuid, set once during validate_events.
    pub uuid: Uuid,
    // Post-skew-adjustment timestamp for Kafka export, None if event is malformed
    pub adjusted_timestamp: Option<DateTime<Utc>>,
    pub result: EventResult,
    pub details: Option<&'static str>,
    pub destination: Destination,
    pub force_disable_person_processing: bool,
}

impl SinkEvent for WrappedEvent {
    // Pre-parsed UUID for result correlation. By the Sink stage,
    // we know ALL well-formed incoming events have a valid UUID.
    fn uuid(&self) -> Uuid {
        self.uuid
    }

    // Helps the Sink implementations filter events that were marked
    // as ineligible for publishing in the request preprocessing step.
    fn should_publish(&self) -> bool {
        self.result == EventResult::Ok && self.destination != Destination::Drop
    }

    // Resolve the storage-agnostic Destination scope for this event.
    // The config for each Sink implementation knows how to resolve
    // these to topics (etc.) depending on the sink type
    fn destination(&self) -> &Destination {
        &self.destination
    }

    // Returns the full typed header set for this event, combining per-request
    // context fields (token, now, historical_migration) with event-owned
    // fields. Sinks convert the returned CapturedEventHeaders to their
    // backend-specific format (e.g. OwnedHeaders for Kafka) via the From impl
    // in common_types — same conversion legacy capture uses.
    fn headers(&self, ctx: &Context) -> CapturedEventHeaders {
        // v0 compat: downstream consumers key on "force_disable_person_processing".
        // v1 decouples overflow routing from person-processing (unlike v0 where
        // overflow ForceLimited unconditionally sets this); operators configure
        // this flag alongside ForceOverflow when needed.
        let force_disable_person_processing = if self.force_disable_person_processing {
            Some(true)
        } else {
            None
        };

        // historical_migration header follows legacy CapturedEvent::to_headers()
        // convention: emitted only when enabled for the batch.
        let historical_migration = if ctx.historical_migration {
            Some(true)
        } else {
            None
        };

        let (dlq_reason, dlq_step, dlq_timestamp) = if self.destination == Destination::Dlq {
            (
                Some("event_restriction".to_string()),
                Some("capture".to_string()),
                Some(Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true)),
            )
        } else {
            (None, None, None)
        };

        CapturedEventHeaders {
            token: Some(ctx.api_token.clone()),
            distinct_id: Some(self.event.distinct_id.clone()),
            session_id: self.event.session_id.clone(),
            timestamp: self
                .adjusted_timestamp
                .map(|ts| ts.timestamp_millis().to_string()),
            event: Some(self.event.event.clone()),
            uuid: Some(self.event.uuid().to_owned()),
            now: Some(
                ctx.server_received_at
                    .to_rfc3339_opts(SecondsFormat::AutoSi, true),
            ),
            force_disable_person_processing,
            historical_migration,
            dlq_reason,
            dlq_step,
            dlq_timestamp,
        }
    }

    fn partition_key<'buf>(&self, ctx: &Context, buf: &'buf mut String) -> Option<&'buf str> {
        use std::fmt::Write;
        // v0 parity: only drop partition key for main/overflow analytics.
        // DLQ, Historical, and Custom destinations always retain their key
        // even when person processing is disabled via event restrictions.
        if self.force_disable_person_processing
            && matches!(
                self.destination,
                Destination::AnalyticsMain | Destination::Overflow
            )
        {
            return None;
        }
        match (
            self.event.options.cookieless_mode == Some(true),
            ctx.capture_internal,
        ) {
            (true, true) => {
                let _ = write!(buf, "{}:127.0.0.1", ctx.api_token);
            }
            (true, false) => {
                let _ = write!(buf, "{}:{}", ctx.api_token, ctx.client_ip);
            }
            (false, _) => {
                let _ = write!(buf, "{}:{}", ctx.api_token, self.event.distinct_id);
            }
        }
        Some(buf.as_str())
    }

    fn serialize_into(&self, ctx: &Context, buf: &mut String) -> anyhow::Result<()> {
        let spliced = self.build_spliced_properties()?;
        let properties: &RawValue = spliced.as_deref().unwrap_or(&self.event.properties);
        let ingestion_data = IngestionData {
            event: &self.event.event,
            distinct_id: Some(&self.event.distinct_id),
            uuid: Some(self.uuid),
            properties,
            timestamp: Some(&self.event.timestamp),
        };
        let data = serde_json::to_string(&ingestion_data)
            .map_err(|e| anyhow::anyhow!("serializing IngestionData: {e:#}"))?;

        let ip;
        let ip_ref: &str = if ctx.capture_internal {
            "127.0.0.1"
        } else {
            ip = ctx.client_ip.to_string();
            &ip
        };
        let timestamp = self.adjusted_timestamp.ok_or_else(|| {
            anyhow::anyhow!("serialize_into called on event without adjusted_timestamp")
        })?;
        let now = ctx
            .server_received_at
            .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true);
        let ie = IngestionEvent {
            uuid: self.uuid,
            distinct_id: &self.event.distinct_id,
            ip: ip_ref,
            data: &data,
            now: &now,
            sent_at: Some(ctx.client_timestamp),
            token: &ctx.api_token,
            event: &self.event.event,
            timestamp,
            is_cookieless_mode: self.event.options.cookieless_mode.unwrap_or(false),
            historical_migration: ctx.historical_migration,
        };

        serde_json::to_string(&ie)
            .map(|s| buf.push_str(&s))
            .map_err(|e| anyhow::anyhow!("serializing IngestionEvent: {e:#}"))
    }
}

impl WrappedEvent {
    #[allow(unused_assignments)]
    fn build_property_injections(&self) -> anyhow::Result<String> {
        let mut buf = String::with_capacity(256);
        let mut first = true;

        macro_rules! inject {
            ($buf:expr, $first:expr, $key:expr, $val:expr) => {{
                if !$first {
                    $buf.push(',');
                }
                $first = false;
                $buf.push('"');
                $buf.push_str($key);
                $buf.push_str("\":");
                serde_json::to_writer(StringWriter(&mut $buf), $val)
                    .map_err(|e| anyhow::anyhow!("injecting {}: {e:#}", $key))?;
            }};
        }

        if let Some(ref sid) = self.event.session_id {
            inject!(buf, first, "$session_id", sid);
        }
        if let Some(ref wid) = self.event.window_id {
            inject!(buf, first, "$window_id", wid);
        }
        if let Some(cm) = self.event.options.cookieless_mode {
            inject!(buf, first, "$cookieless_mode", &cm);
        }
        if let Some(dsa) = self.event.options.disable_skew_adjustment {
            inject!(buf, first, "$ignore_sent_at", &dsa);
        }
        if let Some(ref pti) = self.event.options.product_tour_id {
            inject!(buf, first, "$product_tour_id", pti);
        }
        if let Some(ppp) = self.event.options.process_person_profile {
            inject!(buf, first, "$process_person_profile", &ppp);
        }

        Ok(buf)
    }

    /// Build spliced properties if injection is needed, or return None
    /// to signal the caller should borrow `self.event.properties` directly.
    fn build_spliced_properties(&self) -> anyhow::Result<Option<Box<RawValue>>> {
        let injection = self.build_property_injections()?;
        if injection.is_empty() {
            return Ok(None);
        }

        let raw = self.event.properties.get();
        if !raw.starts_with('{') {
            return Err(anyhow::anyhow!(
                "properties must be a JSON object for injection, got: {:.32}",
                raw,
            ));
        }
        if raw.len() < 2 {
            return Err(anyhow::anyhow!(
                "properties too short ({} bytes) for JSON object",
                raw.len()
            ));
        }
        let prefix = &raw[..raw.len() - 1];
        let has_existing = !raw[1..].trim_start().starts_with('}');

        let mut buf = String::with_capacity(raw.len() + injection.len() + 2);
        buf.push_str(prefix);
        if has_existing {
            buf.push(',');
        }
        buf.push_str(&injection);
        buf.push('}');

        RawValue::from_string(buf)
            .map(Some)
            .map_err(|e| anyhow::anyhow!("property surgery produced invalid JSON: {e:#}"))
    }
}

/// Shim implementation of HasEventName for CaptureQuotaLimiter compatibility.
///
/// The v1 capture pipeline does not deserialize event.properties -- they are
/// forwarded as raw JSON to Kafka. Property checks here are limited to fields
/// that have been promoted to the typed Event::Options struct. If a new quota
/// limiter predicate needs a property not in Options, add it there first.
impl HasEventName for WrappedEvent {
    fn event_name(&self) -> &str {
        &self.event.event
    }

    fn has_property(&self, key: &str) -> bool {
        match key {
            "product_tour_id" => self.event.options.product_tour_id.is_some(),
            _ => false,
        }
    }
}

/// The Kafka payload produced by `WrappedEvent::serialize_into`.
///
/// Field order matches `CapturedEvent` from `common_types` so that serde's
/// derived `Serialize` emits JSON keys in the same order as v0. Serde
/// annotations (`skip_serializing_if`) also match CapturedEvent exactly.
///
/// Borrows from `WrappedEvent` and `Context` to avoid per-event heap
/// allocations -- the struct is created, serialized, and dropped within
/// a single `serialize_into` call.
#[derive(Debug, Serialize)]
pub struct IngestionEvent<'a> {
    pub uuid: Uuid,
    pub distinct_id: &'a str,
    pub ip: &'a str,
    pub data: &'a str,
    pub now: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sent_at: Option<DateTime<Utc>>,
    pub token: &'a str,
    pub event: &'a str,
    pub timestamp: DateTime<Utc>,
    #[serde(skip_serializing_if = "<&bool>::not", default)]
    pub is_cookieless_mode: bool,
    #[serde(skip_serializing_if = "<&bool>::not", default)]
    pub historical_migration: bool,
}

/// The inner `data` payload: a simplified RawEvent-shaped struct for
/// constructing the double-encoded JSON in `IngestionEvent.data`.
///
/// Omitted vs RawEvent:
/// - `token`: v1 uses Authorization header; downstream handles absence
/// - `offset`: dead field; Node.js ingestion parses but never reads it
/// - `$set`/`$set_once` at top level: legacy Python SDK cruft; v1 schema
///   does not support these at top level (clients send them inside
///   `properties`, where they pass through the opaque blob as-is)
#[derive(Debug, Serialize)]
pub struct IngestionData<'a> {
    pub event: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub distinct_id: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub uuid: Option<Uuid>,
    pub properties: &'a RawValue,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub timestamp: Option<&'a str>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_valid_batch() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": [{
                "event": "$pageview",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "user-42",
                "timestamp": "2026-03-19T14:29:58.123Z",
                "options": {}
            }]
        }"#;

        let batch: Batch = serde_json::from_str(json).unwrap();
        assert_eq!(batch.created_at, "2026-03-19T14:30:00.000Z");
        assert!(!batch.historical_migration);
        assert_eq!(batch.capture_internal, None);
        assert_eq!(batch.batch.len(), 1);

        let event = &batch.batch[0];
        assert_eq!(event.event, "$pageview");
        assert_eq!(event.uuid, "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d");
        assert_eq!(event.distinct_id, "user-42");
        assert_eq!(event.timestamp, "2026-03-19T14:29:58.123Z");
        assert_eq!(event.properties.get(), "{}");
    }

    #[test]
    fn parse_batch_with_properties() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": [{
                "event": "$identify",
                "uuid": "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e",
                "distinct_id": "user-99",
                "timestamp": "2026-03-19T14:30:00.000Z",
                "options": {},
                "properties": {
                    "$current_url": "https://example.com",
                    "$set": {"email": "test@example.com"},
                    "$set_once": {"created_at": "2026-01-01"},
                    "$groups": {"company": "posthog"},
                    "custom_prop": 42
                }
            }]
        }"#;

        let batch: Batch = serde_json::from_str(json).unwrap();
        let raw = batch.batch[0].properties.get();
        assert!(raw.contains("$current_url"));
        assert!(raw.contains("custom_prop"));
        assert!(raw.contains("$set"));
        assert!(raw.contains("$set_once"));
        assert!(raw.contains("$groups"));
    }

    #[test]
    fn parse_event_properties_array_accepted_by_serde() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": [{
                "event": "e",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "d",
                "timestamp": "2026-03-19T14:30:00.000Z",
                "options": {},
                "properties": [1, 2, 3]
            }]
        }"#;
        let batch: Batch = serde_json::from_str(json).unwrap();
        assert!(batch.batch[0].properties.get().starts_with('['));
    }

    #[test]
    fn parse_batch_missing_created_at() {
        let json = r#"{
            "batch": [{
                "event": "e",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "d",
                "timestamp": "2026-03-19T14:30:00.000Z"
            }]
        }"#;
        assert!(serde_json::from_str::<Batch>(json).is_err());
    }

    #[test]
    fn parse_batch_missing_batch_field() {
        let json = r#"{"created_at": "2026-03-19T14:30:00.000Z"}"#;
        assert!(serde_json::from_str::<Batch>(json).is_err());
    }

    #[test]
    fn parse_event_missing_event_name() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": [{
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "d",
                "timestamp": "2026-03-19T14:30:00.000Z"
            }]
        }"#;
        assert!(serde_json::from_str::<Batch>(json).is_err());
    }

    #[test]
    fn parse_event_missing_uuid() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": [{
                "event": "e",
                "distinct_id": "d",
                "timestamp": "2026-03-19T14:30:00.000Z"
            }]
        }"#;
        assert!(serde_json::from_str::<Batch>(json).is_err());
    }

    #[test]
    fn parse_event_missing_distinct_id() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": [{
                "event": "e",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "timestamp": "2026-03-19T14:30:00.000Z"
            }]
        }"#;
        assert!(serde_json::from_str::<Batch>(json).is_err());
    }

    #[test]
    fn parse_event_missing_timestamp() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": [{
                "event": "e",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "d"
            }]
        }"#;
        assert!(serde_json::from_str::<Batch>(json).is_err());
    }

    #[test]
    fn parse_event_missing_required_fields() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": [{
                "properties": {"key": "value"}
            }]
        }"#;
        assert!(serde_json::from_str::<Batch>(json).is_err());
    }

    #[test]
    fn parse_batch_empty_array() {
        let json = r#"{"created_at": "2026-03-19T14:30:00.000Z", "batch": []}"#;
        let batch: Batch = serde_json::from_str(json).unwrap();
        assert!(batch.batch.is_empty());
    }

    #[test]
    fn parse_batch_extra_fields_ignored() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "unknown_top_field": true,
            "batch": [{
                "event": "e",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "d",
                "timestamp": "2026-03-19T14:30:00.000Z",
                "options": {},
                "unknown_event_field": "ignored"
            }]
        }"#;
        let batch: Batch = serde_json::from_str(json).unwrap();
        assert_eq!(batch.batch.len(), 1);
        assert_eq!(batch.batch[0].event, "e");
    }

    #[test]
    fn parse_batch_metadata_defaults() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": []
        }"#;
        let batch: Batch = serde_json::from_str(json).unwrap();
        assert_eq!(batch.created_at, "2026-03-19T14:30:00.000Z");
        assert!(!batch.historical_migration);
        assert_eq!(batch.capture_internal, None);
    }

    #[test]
    fn parse_batch_metadata_explicit_true() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "historical_migration": true,
            "capture_internal": true,
            "batch": []
        }"#;
        let batch: Batch = serde_json::from_str(json).unwrap();
        assert_eq!(batch.created_at, "2026-03-19T14:30:00.000Z");
        assert!(batch.historical_migration);
        assert_eq!(batch.capture_internal, Some(true));
    }

    #[test]
    fn parse_batch_missing_created_at_with_events() {
        let json = r#"{
            "batch": [{
                "event": "e",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "d",
                "timestamp": "2026-03-19T14:30:00.000Z"
            }]
        }"#;
        assert!(serde_json::from_str::<Batch>(json).is_err());
    }

    #[test]
    fn parse_event_optional_fields() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": [{
                "event": "$pageview",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "user-1",
                "timestamp": "2026-03-19T14:29:58.123Z",
                "session_id": "sess-abc",
                "window_id": "win-xyz",
                "options": {
                    "cookieless_mode": true,
                    "disable_skew_adjustment": true,
                    "product_tour_id": "tour-123",
                    "process_person_profile": false
                }
            }]
        }"#;
        let batch: Batch = serde_json::from_str(json).unwrap();
        let event = &batch.batch[0];
        assert_eq!(event.session_id.as_deref(), Some("sess-abc"));
        assert_eq!(event.window_id.as_deref(), Some("win-xyz"));
        assert_eq!(event.options.cookieless_mode, Some(true));
        assert_eq!(event.options.disable_skew_adjustment, Some(true));
        assert_eq!(event.options.product_tour_id.as_deref(), Some("tour-123"));
        assert_eq!(event.options.process_person_profile, Some(false));
    }

    #[test]
    fn parse_event_missing_options_fails() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": [{
                "event": "$pageview",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "user-42",
                "timestamp": "2026-03-19T14:29:58.123Z"
            }]
        }"#;
        assert!(serde_json::from_str::<Batch>(json).is_err());
    }

    #[test]
    fn parse_event_empty_options_ok() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": [{
                "event": "$pageview",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "user-42",
                "timestamp": "2026-03-19T14:29:58.123Z",
                "options": {}
            }]
        }"#;
        let batch: Batch = serde_json::from_str(json).unwrap();
        let event = &batch.batch[0];
        assert_eq!(event.session_id, None);
        assert_eq!(event.window_id, None);
        assert_eq!(event.options.cookieless_mode, None);
        assert_eq!(event.options.disable_skew_adjustment, None);
        assert_eq!(event.options.product_tour_id, None);
        assert_eq!(event.options.process_person_profile, None);
    }

    #[test]
    fn parse_invalid_json() {
        let garbage = b"this is not json at all {{{";
        assert!(serde_json::from_slice::<Batch>(garbage).is_err());
    }

    // --- SinkEvent impl for WrappedEvent ---

    use crate::v1::sinks::event::Event as SinkEventTrait;
    use crate::v1::sinks::Destination;
    use crate::v1::test_utils;
    use common_types::HasEventName;

    fn ok_wrapped(event_name: &str, distinct_id: &str) -> WrappedEvent {
        test_utils::wrapped_event(event_name, distinct_id)
    }

    #[test]
    fn should_publish_ok_and_non_drop() {
        let ev = ok_wrapped("$pageview", "user-1");
        assert!(ev.should_publish());
    }

    #[test]
    fn should_publish_false_when_dropped() {
        let mut ev = ok_wrapped("$pageview", "user-1");
        ev.result = EventResult::Drop;
        assert!(!ev.should_publish());
    }

    #[test]
    fn should_publish_false_when_destination_drop() {
        let mut ev = ok_wrapped("$pageview", "user-1");
        ev.destination = Destination::Drop;
        assert!(!ev.should_publish());
    }

    #[test]
    fn should_publish_false_when_limited() {
        let mut ev = ok_wrapped("$pageview", "user-1");
        ev.result = EventResult::Limited;
        assert!(!ev.should_publish());
    }

    #[test]
    fn headers_base_fields_always_present() {
        let ctx = test_utils::test_context();
        let ev = ok_wrapped("$pageview", "user-1");
        let h = ev.headers(&ctx);
        assert_eq!(h.distinct_id.as_deref(), Some("user-1"));
        assert_eq!(h.event.as_deref(), Some("$pageview"));
        assert!(h.uuid.is_some());
        assert!(h.timestamp.is_some());
        assert!(h.force_disable_person_processing.is_none());
        assert!(h.session_id.is_none());
        assert!(h.dlq_reason.is_none());
    }

    #[test]
    fn headers_timestamp_is_millis_epoch() {
        let ctx = test_utils::test_context();
        let ev = ok_wrapped("$pageview", "user-1");
        let h = ev.headers(&ctx);
        let ts_str = h.timestamp.expect("timestamp should be set");
        let ts_millis: i64 = ts_str.parse().expect("timestamp should be numeric millis");
        assert_eq!(ts_millis, ev.adjusted_timestamp.unwrap().timestamp_millis());
    }

    #[test]
    fn headers_omit_timestamp_when_none() {
        let ctx = test_utils::test_context();
        let mut ev = ok_wrapped("$pageview", "user-1");
        ev.adjusted_timestamp = None;
        let h = ev.headers(&ctx);
        assert!(h.timestamp.is_none());
    }

    #[test]
    fn headers_include_session_id_when_present() {
        let ctx = test_utils::test_context();
        let mut ev = ok_wrapped("$pageview", "user-1");
        ev.event.session_id = Some("sess-abc".to_string());
        let h = ev.headers(&ctx);
        assert_eq!(h.session_id.as_deref(), Some("sess-abc"));
    }

    #[test]
    fn headers_omit_session_id_when_none() {
        let ctx = test_utils::test_context();
        let ev = ok_wrapped("$pageview", "user-1");
        assert!(ev.event.session_id.is_none());
        let h = ev.headers(&ctx);
        assert!(h.session_id.is_none());
    }

    #[test]
    fn headers_include_force_disable_person_processing() {
        let ctx = test_utils::test_context();
        let mut ev = ok_wrapped("$pageview", "user-1");
        ev.force_disable_person_processing = true;
        let h = ev.headers(&ctx);
        assert_eq!(h.force_disable_person_processing, Some(true));
    }

    #[test]
    fn headers_omit_force_disable_person_processing_when_false() {
        let ctx = test_utils::test_context();
        let ev = ok_wrapped("$pageview", "user-1");
        assert!(!ev.force_disable_person_processing);
        let h = ev.headers(&ctx);
        assert!(h.force_disable_person_processing.is_none());
    }

    #[test]
    fn headers_include_dlq_headers_when_destination_dlq() {
        let ctx = test_utils::test_context();
        let mut ev = ok_wrapped("$pageview", "user-1");
        ev.destination = Destination::Dlq;
        let h = ev.headers(&ctx);
        assert_eq!(h.dlq_reason.as_deref(), Some("event_restriction"));
        assert_eq!(h.dlq_step.as_deref(), Some("capture"));
        let dlq_ts = h.dlq_timestamp.expect("dlq_timestamp should be set");
        assert!(
            chrono::DateTime::parse_from_rfc3339(&dlq_ts).is_ok(),
            "dlq_timestamp should be valid RFC3339: {dlq_ts}"
        );
    }

    #[test]
    fn headers_omit_dlq_headers_when_not_dlq() {
        let ctx = test_utils::test_context();
        let ev = ok_wrapped("$pageview", "user-1");
        assert_ne!(ev.destination, Destination::Dlq);
        let h = ev.headers(&ctx);
        assert!(h.dlq_reason.is_none());
        assert!(h.dlq_step.is_none());
        assert!(h.dlq_timestamp.is_none());
    }

    #[test]
    fn headers_include_token_from_ctx() {
        // Absorbs coverage from the removed build_context_headers token test:
        // the api_token on the batch context must flow verbatim onto every
        // event's typed headers.
        let ctx = test_utils::test_context();
        let ev = ok_wrapped("$pageview", "user-1");
        let h = ev.headers(&ctx);
        assert_eq!(h.token, Some(ctx.api_token.clone()));
    }

    #[test]
    fn headers_now_uses_server_received_at_autosi_rfc3339() {
        // Absorbs coverage from the removed build_context_headers now test,
        // and asserts the legacy-aligned format upgrade (SecondsFormat::AutoSi,
        // matches IngestionEvent.now and legacy CapturedEvent::to_headers()).
        let ctx = test_utils::test_context();
        let ev = ok_wrapped("$pageview", "user-1");
        let h = ev.headers(&ctx);
        let now = h
            .now
            .expect("now should be set from ctx.server_received_at");
        assert_eq!(
            now,
            ctx.server_received_at
                .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true)
        );
        // Double-check the value is a valid RFC3339 timestamp regardless of
        // how the format is spelled out.
        assert!(
            chrono::DateTime::parse_from_rfc3339(&now).is_ok(),
            "now should be valid RFC3339: {now}"
        );
    }

    #[test]
    fn headers_historical_migration_from_ctx() {
        // Absorbs coverage from the removed build_context_headers
        // historical_migration tests (set → Some(true); unset → None),
        // matching legacy CapturedEvent::to_headers() convention.
        let ev = ok_wrapped("$pageview", "user-1");

        let mut ctx = test_utils::test_context();
        ctx.historical_migration = true;
        let h = ev.headers(&ctx);
        assert_eq!(h.historical_migration, Some(true));

        ctx.historical_migration = false;
        let h = ev.headers(&ctx);
        assert!(h.historical_migration.is_none());
    }

    fn partition_key_str(ev: &WrappedEvent, ctx: &Context) -> Option<String> {
        let mut buf = String::new();
        ev.partition_key(ctx, &mut buf).map(String::from)
    }

    #[test]
    fn partition_key_normal_mode() {
        let ctx = test_utils::test_context();
        let ev = ok_wrapped("$pageview", "user-42");
        assert_eq!(
            partition_key_str(&ev, &ctx),
            Some(format!("{}:user-42", ctx.api_token))
        );
    }

    #[test]
    fn partition_key_cookieless_mode() {
        let ctx = test_utils::test_context();
        let mut ev = ok_wrapped("$pageview", "user-42");
        ev.event.options.cookieless_mode = Some(true);
        assert_eq!(
            partition_key_str(&ev, &ctx),
            Some(format!("{}:{}", ctx.api_token, ctx.client_ip))
        );
    }

    #[test]
    fn partition_key_cookieless_capture_internal() {
        let mut ctx = test_utils::test_context();
        ctx.capture_internal = true;
        let mut ev = ok_wrapped("$pageview", "user-42");
        ev.event.options.cookieless_mode = Some(true);
        assert_eq!(
            partition_key_str(&ev, &ctx),
            Some(format!("{}:127.0.0.1", ctx.api_token))
        );
    }

    #[test]
    fn destination_returns_event_destination() {
        let mut ev = ok_wrapped("$pageview", "user-1");
        ev.destination = Destination::Overflow;
        assert_eq!(*ev.destination(), Destination::Overflow);
    }

    // --- partition key + force_disable_person_processing × destination ---

    #[test]
    fn partition_key_force_disable_analytics_main() {
        let ctx = test_utils::test_context();
        let mut ev = ok_wrapped("$pageview", "user-42");
        ev.force_disable_person_processing = true;
        ev.destination = Destination::AnalyticsMain;
        assert_eq!(partition_key_str(&ev, &ctx), None);
    }

    #[test]
    fn partition_key_force_disable_overflow() {
        let ctx = test_utils::test_context();
        let mut ev = ok_wrapped("$pageview", "user-42");
        ev.force_disable_person_processing = true;
        ev.destination = Destination::Overflow;
        assert_eq!(partition_key_str(&ev, &ctx), None);
    }

    #[test]
    fn partition_key_force_disable_dlq() {
        let ctx = test_utils::test_context();
        let mut ev = ok_wrapped("$pageview", "user-42");
        ev.force_disable_person_processing = true;
        ev.destination = Destination::Dlq;
        assert_eq!(
            partition_key_str(&ev, &ctx),
            Some(format!("{}:user-42", ctx.api_token))
        );
    }

    #[test]
    fn partition_key_force_disable_historical() {
        let ctx = test_utils::test_context();
        let mut ev = ok_wrapped("$pageview", "user-42");
        ev.force_disable_person_processing = true;
        ev.destination = Destination::AnalyticsHistorical;
        assert_eq!(
            partition_key_str(&ev, &ctx),
            Some(format!("{}:user-42", ctx.api_token))
        );
    }

    #[test]
    fn partition_key_force_disable_custom() {
        let ctx = test_utils::test_context();
        let mut ev = ok_wrapped("$pageview", "user-42");
        ev.force_disable_person_processing = true;
        ev.destination = Destination::Custom("my_topic".into());
        assert_eq!(
            partition_key_str(&ev, &ctx),
            Some(format!("{}:user-42", ctx.api_token))
        );
    }

    #[test]
    fn partition_key_force_disable_cookieless_dlq() {
        let ctx = test_utils::test_context();
        let mut ev = ok_wrapped("$pageview", "user-42");
        ev.force_disable_person_processing = true;
        ev.destination = Destination::Dlq;
        ev.event.options.cookieless_mode = Some(true);
        assert_eq!(
            partition_key_str(&ev, &ctx),
            Some(format!("{}:{}", ctx.api_token, ctx.client_ip))
        );
    }

    // --- HasEventName impl for WrappedEvent ---

    #[test]
    fn event_name_returns_event_field() {
        let ev = ok_wrapped("$pageview", "user-1");
        assert_eq!(ev.event_name(), "$pageview");
    }

    #[test]
    fn has_property_product_tour_id_some() {
        let mut ev = ok_wrapped("survey sent", "user-1");
        ev.event.options.product_tour_id = Some("tour-123".into());
        assert!(ev.has_property("product_tour_id"));
    }

    #[test]
    fn has_property_product_tour_id_none() {
        let ev = ok_wrapped("survey sent", "user-1");
        assert!(!ev.has_property("product_tour_id"));
    }

    #[test]
    fn has_property_unknown_key() {
        let ev = ok_wrapped("$pageview", "user-1");
        assert!(!ev.has_property("unknown_key"));
    }

    // --- serialize_into ---

    use std::net::{IpAddr, Ipv4Addr};

    use common_types::{CapturedEvent, RawEvent};
    use serde_json::Value;

    fn raw_obj(s: &str) -> Box<RawValue> {
        RawValue::from_string(s.to_owned()).unwrap()
    }

    fn dt(s: &str) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(s).unwrap().with_timezone(&Utc)
    }

    fn serialize_ctx() -> crate::v1::context::Context {
        let mut ctx = test_utils::test_context();
        ctx.api_token = "phc_project_abc123".to_string();
        ctx.client_ip = IpAddr::V4(Ipv4Addr::new(203, 0, 113, 42));
        ctx.client_timestamp = dt("2026-03-19T14:30:01.500Z");
        ctx.server_received_at = dt("2026-03-19T14:30:00.000Z");
        ctx.capture_internal = false;
        ctx.historical_migration = false;
        ctx
    }

    fn pageview_event() -> WrappedEvent {
        let uuid = Uuid::new_v4();
        WrappedEvent {
            event: Event {
                event: "$pageview".to_string(),
                uuid: uuid.to_string(),
                distinct_id: "user-42".to_string(),
                timestamp: "2026-03-19T14:29:58.123Z".to_string(),
                session_id: Some("sess-01jq9abc".to_string()),
                window_id: Some("win-xyz789".to_string()),
                options: Options {
                    cookieless_mode: Some(false),
                    disable_skew_adjustment: None,
                    product_tour_id: None,
                    process_person_profile: Some(true),
                },
                properties: raw_obj(
                    r#"{"$current_url":"https://app.example.com/dashboard","$browser":"Chrome","custom_prop":42}"#,
                ),
            },
            uuid,
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
        }
    }

    fn serialize_and_parse(
        wrapped: &WrappedEvent,
        ctx: &crate::v1::context::Context,
    ) -> (CapturedEvent, RawEvent) {
        let mut buf = String::new();
        wrapped
            .serialize_into(ctx, &mut buf)
            .expect("serialize_into failed");
        let captured: CapturedEvent =
            serde_json::from_str(&buf).expect("v1 output must deserialize as CapturedEvent");
        let data: RawEvent =
            serde_json::from_str(&captured.data).expect("data field must deserialize as RawEvent");
        (captured, data)
    }

    #[test]
    fn serialize_round_trip_basic() {
        let wrapped = pageview_event();
        let ctx = serialize_ctx();
        let (captured, data) = serialize_and_parse(&wrapped, &ctx);

        assert_eq!(captured.uuid, wrapped.uuid);
        assert_eq!(captured.distinct_id, "user-42");
        assert_eq!(captured.ip, "203.0.113.42");
        assert_eq!(captured.token, "phc_project_abc123");
        assert_eq!(captured.event, "$pageview");
        assert_eq!(captured.timestamp, wrapped.adjusted_timestamp.unwrap());
        assert!(!captured.is_cookieless_mode);
        assert!(!captured.historical_migration);

        assert_eq!(data.event, "$pageview");
        assert_eq!(data.distinct_id, Some(Value::String("user-42".to_string())));
        assert_eq!(data.timestamp.as_deref(), Some("2026-03-19T14:29:58.123Z"));

        let props = &data.properties;
        assert_eq!(props["$current_url"], "https://app.example.com/dashboard");
        assert_eq!(props["$browser"], "Chrome");
        assert_eq!(props["custom_prop"], 42);
        assert_eq!(props["$session_id"], "sess-01jq9abc");
        assert_eq!(props["$window_id"], "win-xyz789");
        assert_eq!(props["$cookieless_mode"], false);
        assert_eq!(props["$process_person_profile"], true);
    }

    #[test]
    fn serialize_ip_redaction_capture_internal() {
        let wrapped = pageview_event();
        let mut ctx = serialize_ctx();
        ctx.capture_internal = true;
        let (captured, _) = serialize_and_parse(&wrapped, &ctx);
        assert_eq!(captured.ip, "127.0.0.1");
    }

    #[test]
    fn serialize_ip_normal() {
        let wrapped = pageview_event();
        let ctx = serialize_ctx();
        let (captured, _) = serialize_and_parse(&wrapped, &ctx);
        assert_eq!(captured.ip, "203.0.113.42");
    }

    #[test]
    fn serialize_all_options_injected() {
        let uuid = Uuid::new_v4();
        let wrapped = WrappedEvent {
            event: Event {
                event: "$pageview".to_string(),
                uuid: uuid.to_string(),
                distinct_id: "user-42".to_string(),
                timestamp: "2026-03-19T14:29:58.123Z".to_string(),
                session_id: Some("sess-01jq9abc".to_string()),
                window_id: Some("win-xyz789".to_string()),
                options: Options {
                    cookieless_mode: Some(true),
                    disable_skew_adjustment: Some(true),
                    product_tour_id: Some("tour-onboarding-v2".to_string()),
                    process_person_profile: Some(false),
                },
                properties: raw_obj(r#"{"existing":"value"}"#),
            },
            uuid,
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
        };

        let ctx = serialize_ctx();
        let (_, data) = serialize_and_parse(&wrapped, &ctx);
        let props = &data.properties;

        assert_eq!(props["existing"], "value");
        assert_eq!(props["$session_id"], "sess-01jq9abc");
        assert_eq!(props["$window_id"], "win-xyz789");
        assert_eq!(props["$cookieless_mode"], true);
        assert_eq!(props["$ignore_sent_at"], true);
        assert_eq!(props["$product_tour_id"], "tour-onboarding-v2");
        assert_eq!(props["$process_person_profile"], false);
    }

    #[test]
    fn serialize_partial_options() {
        let uuid = Uuid::new_v4();
        let wrapped = WrappedEvent {
            event: Event {
                event: "$pageview".to_string(),
                uuid: uuid.to_string(),
                distinct_id: "user-42".to_string(),
                timestamp: "2026-03-19T14:29:58.123Z".to_string(),
                session_id: Some("sess-abc".to_string()),
                window_id: None,
                options: Options {
                    cookieless_mode: Some(false),
                    disable_skew_adjustment: None,
                    product_tour_id: None,
                    process_person_profile: None,
                },
                properties: raw_obj(r#"{"x":1}"#),
            },
            uuid,
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
        };

        let ctx = serialize_ctx();
        let (_, data) = serialize_and_parse(&wrapped, &ctx);
        let props = &data.properties;

        assert_eq!(props["$session_id"], "sess-abc");
        assert_eq!(props["$cookieless_mode"], false);
        assert!(!props.contains_key("$window_id"));
        assert!(!props.contains_key("$ignore_sent_at"));
        assert!(!props.contains_key("$product_tour_id"));
        assert!(!props.contains_key("$process_person_profile"));
    }

    #[test]
    fn serialize_empty_properties_no_options() {
        let uuid = Uuid::new_v4();
        let wrapped = WrappedEvent {
            event: Event {
                event: "$pageview".to_string(),
                uuid: uuid.to_string(),
                distinct_id: "user-42".to_string(),
                timestamp: "2026-03-19T14:29:58.123Z".to_string(),
                session_id: None,
                window_id: None,
                options: Options {
                    cookieless_mode: None,
                    disable_skew_adjustment: None,
                    product_tour_id: None,
                    process_person_profile: None,
                },
                properties: raw_obj("{}"),
            },
            uuid,
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
        };

        let ctx = serialize_ctx();
        let (_, data) = serialize_and_parse(&wrapped, &ctx);
        assert!(data.properties.is_empty());
    }

    #[test]
    fn serialize_empty_properties_with_options() {
        let uuid = Uuid::new_v4();
        let wrapped = WrappedEvent {
            event: Event {
                event: "$pageview".to_string(),
                uuid: uuid.to_string(),
                distinct_id: "user-42".to_string(),
                timestamp: "2026-03-19T14:29:58.123Z".to_string(),
                session_id: Some("sess-abc".to_string()),
                window_id: None,
                options: Options {
                    cookieless_mode: Some(true),
                    disable_skew_adjustment: None,
                    product_tour_id: None,
                    process_person_profile: None,
                },
                properties: raw_obj("{}"),
            },
            uuid,
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
        };

        let ctx = serialize_ctx();
        let (_, data) = serialize_and_parse(&wrapped, &ctx);
        let props = &data.properties;
        assert_eq!(props["$session_id"], "sess-abc");
        assert_eq!(props["$cookieless_mode"], true);
        assert_eq!(props.len(), 2);
    }

    #[test]
    fn serialize_existing_properties_preserved() {
        let uuid = Uuid::new_v4();
        let wrapped = WrappedEvent {
            event: Event {
                event: "$pageview".to_string(),
                uuid: uuid.to_string(),
                distinct_id: "user-42".to_string(),
                timestamp: "2026-03-19T14:29:58.123Z".to_string(),
                session_id: Some("sess-abc".to_string()),
                window_id: None,
                options: Options {
                    cookieless_mode: None,
                    disable_skew_adjustment: None,
                    product_tour_id: None,
                    process_person_profile: None,
                },
                properties: raw_obj(
                    r#"{"$lib":"posthog-js","$lib_version":"1.150.0","$referrer":"https://google.com"}"#,
                ),
            },
            uuid,
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
        };

        let ctx = serialize_ctx();
        let (_, data) = serialize_and_parse(&wrapped, &ctx);
        let props = &data.properties;
        assert_eq!(props["$lib"], "posthog-js");
        assert_eq!(props["$lib_version"], "1.150.0");
        assert_eq!(props["$referrer"], "https://google.com");
        assert_eq!(props["$session_id"], "sess-abc");
    }

    #[test]
    fn serialize_is_cookieless_mode_true() {
        let mut wrapped = pageview_event();
        wrapped.event.options.cookieless_mode = Some(true);
        let ctx = serialize_ctx();
        let (captured, data) = serialize_and_parse(&wrapped, &ctx);
        assert!(captured.is_cookieless_mode);
        assert_eq!(data.properties["$cookieless_mode"], true);
    }

    #[test]
    fn serialize_is_cookieless_mode_false_skipped() {
        let wrapped = pageview_event();
        assert_eq!(wrapped.event.options.cookieless_mode, Some(false));
        let ctx = serialize_ctx();
        let mut buf = String::new();
        wrapped.serialize_into(&ctx, &mut buf).unwrap();
        let val: Value = serde_json::from_str(&buf).unwrap();
        assert!(
            val.get("is_cookieless_mode").is_none(),
            "is_cookieless_mode should be absent when false"
        );
    }

    #[test]
    fn serialize_historical_migration_true() {
        let wrapped = pageview_event();
        let mut ctx = serialize_ctx();
        ctx.historical_migration = true;
        let (captured, _) = serialize_and_parse(&wrapped, &ctx);
        assert!(captured.historical_migration);
    }

    #[test]
    fn serialize_historical_migration_false_skipped() {
        let wrapped = pageview_event();
        let ctx = serialize_ctx();
        let mut buf = String::new();
        wrapped.serialize_into(&ctx, &mut buf).unwrap();
        let val: Value = serde_json::from_str(&buf).unwrap();
        assert!(
            val.get("historical_migration").is_none(),
            "historical_migration should be absent when false"
        );
    }

    #[test]
    fn serialize_sent_at_present() {
        let wrapped = pageview_event();
        let ctx = serialize_ctx();
        let (captured, _) = serialize_and_parse(&wrapped, &ctx);
        assert!(captured.sent_at.is_some());
    }

    #[test]
    fn serialize_data_timestamp_is_original_not_adjusted() {
        let wrapped = pageview_event();
        let ctx = serialize_ctx();
        let (captured, data) = serialize_and_parse(&wrapped, &ctx);
        assert_eq!(
            data.timestamp.as_deref(),
            Some("2026-03-19T14:29:58.123Z"),
            "data.timestamp should be the original client timestamp"
        );
        assert_eq!(
            captured.timestamp,
            dt("2026-03-19T14:29:53.123Z"),
            "captured.timestamp should be the adjusted timestamp"
        );
    }

    #[test]
    fn serialize_process_person_profile_in_properties() {
        let mut wrapped = pageview_event();
        wrapped.event.options.process_person_profile = Some(false);
        wrapped.force_disable_person_processing = false;
        let ctx = serialize_ctx();
        let (_, data) = serialize_and_parse(&wrapped, &ctx);
        assert_eq!(data.properties["$process_person_profile"], false);
    }

    #[test]
    fn serialize_force_disable_does_not_affect_data() {
        let uuid = Uuid::new_v4();
        let wrapped = WrappedEvent {
            event: Event {
                event: "$pageview".to_string(),
                uuid: uuid.to_string(),
                distinct_id: "user-42".to_string(),
                timestamp: "2026-03-19T14:29:58.123Z".to_string(),
                session_id: None,
                window_id: None,
                options: Options {
                    cookieless_mode: None,
                    disable_skew_adjustment: None,
                    product_tour_id: None,
                    process_person_profile: None,
                },
                properties: raw_obj(r#"{"x":1}"#),
            },
            uuid,
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: true,
        };

        let ctx = serialize_ctx();
        let (_, data) = serialize_and_parse(&wrapped, &ctx);
        assert!(
            !data
                .properties
                .contains_key("force_disable_person_processing"),
            "force_disable_person_processing must not appear in properties"
        );
        assert!(
            !data.properties.contains_key("$process_person_profile"),
            "$process_person_profile must not appear when options.process_person_profile is None"
        );
    }

    #[test]
    fn serialize_identify_event() {
        let uuid = Uuid::new_v4();
        let wrapped = WrappedEvent {
            event: Event {
                event: "$identify".to_string(),
                uuid: uuid.to_string(),
                distinct_id: "user-99".to_string(),
                timestamp: "2026-03-19T14:30:00.000Z".to_string(),
                session_id: None,
                window_id: None,
                options: Options {
                    cookieless_mode: None,
                    disable_skew_adjustment: None,
                    product_tour_id: None,
                    process_person_profile: Some(true),
                },
                properties: raw_obj(r#"{"$browser":"Safari","$os":"macOS"}"#),
            },
            uuid,
            adjusted_timestamp: Some(dt("2026-03-19T14:29:55.000Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
        };

        let ctx = serialize_ctx();
        let (captured, data) = serialize_and_parse(&wrapped, &ctx);
        assert_eq!(captured.event, "$identify");
        assert_eq!(captured.uuid, uuid);
        assert_eq!(data.event, "$identify");
        assert_eq!(data.properties["$browser"], "Safari");
        assert_eq!(data.properties["$os"], "macOS");
        assert_eq!(data.properties["$process_person_profile"], true);
    }

    // --- A3: property injection safety ---

    #[test]
    fn serialize_array_properties_rejected() {
        let uuid = Uuid::new_v4();
        let wrapped = WrappedEvent {
            event: Event {
                event: "$pageview".to_string(),
                uuid: uuid.to_string(),
                distinct_id: "user-42".to_string(),
                timestamp: "2026-03-19T14:29:58.123Z".to_string(),
                session_id: Some("sess-abc".to_string()),
                window_id: None,
                options: Options {
                    cookieless_mode: None,
                    disable_skew_adjustment: None,
                    product_tour_id: None,
                    process_person_profile: None,
                },
                properties: raw_obj("[1,2,3]"),
            },
            uuid,
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
        };

        let ctx = serialize_ctx();
        let mut buf = String::new();
        let err = wrapped.serialize_into(&ctx, &mut buf).unwrap_err();
        assert!(
            err.to_string().contains("must be a JSON object"),
            "expected object guard, got: {err}"
        );
    }

    #[test]
    fn serialize_whitespace_padded_empty_object() {
        let uuid = Uuid::new_v4();
        let wrapped = WrappedEvent {
            event: Event {
                event: "$pageview".to_string(),
                uuid: uuid.to_string(),
                distinct_id: "user-42".to_string(),
                timestamp: "2026-03-19T14:29:58.123Z".to_string(),
                session_id: Some("sess-abc".to_string()),
                window_id: None,
                options: Options {
                    cookieless_mode: None,
                    disable_skew_adjustment: None,
                    product_tour_id: None,
                    process_person_profile: None,
                },
                properties: raw_obj("{   }"),
            },
            uuid,
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
        };

        let ctx = serialize_ctx();
        let (_, data) = serialize_and_parse(&wrapped, &ctx);
        assert_eq!(data.properties["$session_id"], "sess-abc");
        assert_eq!(data.properties.len(), 1);
    }
}
