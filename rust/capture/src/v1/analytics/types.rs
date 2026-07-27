use std::io;
use std::ops::Not;

use chrono::{DateTime, SecondsFormat, Utc};
use common_types::{CapturedEventHeaders, HasEventName};
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use serde_json::Value;
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

use crate::v1::context::RequestContext;
use crate::v1::sinks::event::Event as SinkEvent;
use crate::v1::sinks::Destination;

fn empty_raw_object() -> Box<RawValue> {
    RawValue::from_string("{}".to_owned()).unwrap()
}

/// Trim client-submitted whitespace once, at the deserialization boundary.
/// Only reallocates when padding is actually present.
fn deserialize_trimmed_string<'de, D>(deserializer: D) -> Result<String, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let s = String::deserialize(deserializer)?;
    let trimmed = s.trim();
    Ok(if trimmed.len() == s.len() {
        s
    } else {
        trimmed.to_owned()
    })
}

/// Per-event outcome in the batch response.
/// Ok: captured successfully. Drop: rejected (billing/validation). Warning: accepted
/// with person processing disabled (do not resubmit). Retry: not persisted, safe to resubmit.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EventResult {
    #[default]
    Ok,
    Drop,
    Warning,
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

#[derive(Debug, Default, Clone, Deserialize, Serialize)]
pub struct Options {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cookieless_mode: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub disable_skew_correction: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub product_tour_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub process_person_profile: Option<bool>,
}

/// Deserialize-tolerant wrapper for event options. Accepts any JSON value so
/// that a single mistyped field cannot fail batch deserialization.
#[derive(Debug, Default, Clone, Deserialize, Serialize)]
#[serde(transparent)]
pub struct RawOptions(pub Value);

/// Error produced when `RawOptions::validate` cannot coerce one or more fields.
/// Carries the offending field names for logging; the wire/metric tag is the
/// static `DETAIL_INVALID_OPTIONS` constant applied at the drop site.
#[derive(Debug)]
pub struct OptionsError {
    pub invalid_fields: Vec<&'static str>,
}

impl RawOptions {
    /// Validate and coerce raw JSON into typed Options.
    ///
    /// - Null/absent -> Ok(default)
    /// - Object -> coerce each known key, ignore unknown, collect invalid fields
    /// - Non-object -> Err with no field names
    pub fn validate(&self) -> Result<Options, OptionsError> {
        match &self.0 {
            Value::Null => Ok(Options::default()),
            Value::Object(map) => {
                let mut opts = Options::default();
                let mut invalid_fields: Vec<&'static str> = Vec::new();

                if let Some(v) = map.get("cookieless_mode") {
                    if !v.is_null() {
                        match coerce_bool(v) {
                            Some(b) => opts.cookieless_mode = Some(b),
                            None => invalid_fields.push("cookieless_mode"),
                        }
                    }
                }
                if let Some(v) = map.get("disable_skew_correction") {
                    if !v.is_null() {
                        match coerce_bool(v) {
                            Some(b) => opts.disable_skew_correction = Some(b),
                            None => invalid_fields.push("disable_skew_correction"),
                        }
                    }
                }
                if let Some(v) = map.get("process_person_profile") {
                    if !v.is_null() {
                        match coerce_bool(v) {
                            Some(b) => opts.process_person_profile = Some(b),
                            None => invalid_fields.push("process_person_profile"),
                        }
                    }
                }
                if let Some(v) = map.get("product_tour_id") {
                    if !v.is_null() {
                        match coerce_string(v) {
                            Some(s) => opts.product_tour_id = Some(s),
                            None => invalid_fields.push("product_tour_id"),
                        }
                    }
                }

                if invalid_fields.is_empty() {
                    Ok(opts)
                } else {
                    Err(OptionsError { invalid_fields })
                }
            }
            _ => Err(OptionsError {
                invalid_fields: Vec::new(),
            }),
        }
    }
}

/// Coerce a JSON value to bool with conservative rules:
/// - native bool passes through
/// - strings "true"/"false"/"1"/"0" (trimmed, case-insensitive)
/// - any nonzero number -> true, 0 -> false
fn coerce_bool(v: &Value) -> Option<bool> {
    match v {
        Value::Bool(b) => Some(*b),
        Value::String(s) => match s.trim().to_ascii_lowercase().as_str() {
            "true" | "1" => Some(true),
            "false" | "0" => Some(false),
            _ => None,
        },
        Value::Number(n) => n.as_f64().map(|f| f != 0.0),
        _ => None,
    }
}

/// Coerce a JSON value to string:
/// - native string passes through
/// - integer number -> its decimal string representation
fn coerce_string(v: &Value) -> Option<String> {
    match v {
        Value::String(s) => Some(s.clone()),
        Value::Number(n) => n
            .as_i64()
            .map(|i| i.to_string())
            .or_else(|| n.as_u64().map(|u| u.to_string())),
        _ => None,
    }
}

#[derive(Debug, Deserialize)]
pub struct Event {
    pub event: String,
    /// Trimmed at deserialization: callers may rely on this being free of
    /// client-submitted leading/trailing whitespace.
    #[serde(deserialize_with = "deserialize_trimmed_string")]
    pub uuid: String,
    /// Trimmed at deserialization so padded IDs resolve to the same person.
    #[serde(deserialize_with = "deserialize_trimmed_string")]
    pub distinct_id: String,
    pub timestamp: String,
    pub session_id: Option<String>,
    pub window_id: Option<String>,
    #[serde(default)]
    pub options: RawOptions,
    #[serde(default = "empty_raw_object")]
    pub properties: Box<RawValue>,
}

#[derive(Debug)]
pub struct WrappedEvent {
    pub event: Event,
    /// Pre-parsed UUID from Event.uuid, set once during validate_events.
    pub uuid: Uuid,
    /// Typed options coerced from Event.options during validate_events.
    pub options: Options,
    // Post-skew-adjustment timestamp for Kafka export, None if event is malformed
    pub adjusted_timestamp: Option<DateTime<Utc>>,
    pub result: EventResult,
    pub details: Option<&'static str>,
    pub destination: Destination,
    pub force_disable_person_processing: bool,
    /// Set by the gateway-provenance step when a valid signature was verified;
    /// read by the quota shim to exempt the event from the llm_events limiter.
    pub is_gateway_verified: bool,
}

impl SinkEvent for WrappedEvent {
    // Pre-parsed UUID for result correlation. By the Sink stage,
    // we know ALL well-formed incoming events have a valid UUID.
    fn uuid(&self) -> Uuid {
        self.uuid
    }

    // Publish Ok and Warning events; skip Drop, Retry, and anything routed to Destination::Drop.
    fn should_publish(&self) -> bool {
        (self.result == EventResult::Ok || self.result == EventResult::Warning)
            && self.destination != Destination::Drop
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
    fn headers(&self, ctx: &RequestContext) -> CapturedEventHeaders {
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
            uuid: Some(self.event.uuid.clone()),
            now: Some(
                ctx.server_received_at
                    .to_rfc3339_opts(SecondsFormat::AutoSi, true),
            ),
            force_disable_person_processing,
            historical_migration,
            skip_heatmap_processing: None,
            dlq_reason,
            dlq_step,
            dlq_timestamp,
            content_encoding: None,
        }
    }

    fn partition_key(&self, ctx: &RequestContext) -> String {
        use std::fmt::Write;
        let mut buf = String::with_capacity(128);
        match (
            self.options.cookieless_mode == Some(true),
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
        buf
    }

    fn serialize(&self, ctx: &RequestContext) -> anyhow::Result<bytes::Bytes> {
        let spliced = self.build_spliced_properties(ctx)?;
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
            anyhow::anyhow!("serialize called on event without adjusted_timestamp")
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
            is_cookieless_mode: self.options.cookieless_mode.unwrap_or(false),
            historical_migration: ctx.historical_migration,
        };

        let mut buf = Vec::with_capacity(data.len() + 512);
        serde_json::to_writer(&mut buf, &ie)
            .map_err(|e| anyhow::anyhow!("serializing IngestionEvent: {e:#}"))?;
        Ok(bytes::Bytes::from(buf))
    }
}

impl WrappedEvent {
    #[allow(unused_assignments)]
    fn build_property_injections(&self, ctx: &RequestContext) -> anyhow::Result<String> {
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
        if let Some(cm) = self.options.cookieless_mode {
            inject!(buf, first, "$cookieless_mode", &cm);
        }
        if let Some(dsa) = self.options.disable_skew_correction {
            inject!(buf, first, "$ignore_sent_at", &dsa);
        }
        if let Some(ref pti) = self.options.product_tour_id {
            inject!(buf, first, "$product_tour_id", pti);
        }
        if let Some(ppp) = self.options.process_person_profile {
            inject!(buf, first, "$process_person_profile", &ppp);
        }

        // Materialize $lib/$lib_version from the required PostHog-Sdk-Info
        // header — the canonical v1 SDK identity. Appended after client keys,
        // so the header wins under last-key-wins parsing (same duplicate-key
        // semantics as the injections above). Unusable headers inject nothing
        // and are counted per-request in the handler.
        if let Some((lib, lib_version)) = ctx.sdk_lib_and_version() {
            inject!(buf, first, "$lib", lib);
            inject!(buf, first, "$lib_version", lib_version);
        }

        Ok(buf)
    }

    /// Build spliced properties if injection is needed, or return None
    /// to signal the caller should borrow `self.event.properties` directly.
    fn build_spliced_properties(
        &self,
        ctx: &RequestContext,
    ) -> anyhow::Result<Option<Box<RawValue>>> {
        let injection = self.build_property_injections(ctx)?;
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
/// that have been promoted to WrappedEvent.options. If a new quota limiter
/// predicate needs a property not in Options, add it there first.
impl HasEventName for WrappedEvent {
    fn event_name(&self) -> &str {
        &self.event.event
    }

    fn has_property(&self, key: &str) -> bool {
        match key {
            "product_tour_id" => self.options.product_tour_id.is_some(),
            _ => false,
        }
    }
}

/// The Kafka payload produced by `WrappedEvent::serialize`.
///
/// Field order matches `CapturedEvent` from `common_types` so that serde's
/// derived `Serialize` emits JSON keys in the same order as v0. Serde
/// annotations (`skip_serializing_if`) also match CapturedEvent exactly.
///
/// Borrows from `WrappedEvent` and `Context` to avoid per-event heap
/// allocations -- the struct is created, serialized, and dropped within
/// a single `serialize` call.
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
    fn parse_event_trims_uuid_and_distinct_id() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": [{
                "event": "$pageview",
                "uuid": "  a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d  ",
                "distinct_id": "  user-42  ",
                "timestamp": "2026-03-19T14:29:58.123Z"
            }]
        }"#;
        let batch: Batch = serde_json::from_str(json).unwrap();
        let event = &batch.batch[0];
        assert_eq!(event.uuid, "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d");
        assert_eq!(event.distinct_id, "user-42");
    }

    #[test]
    fn parse_event_whitespace_only_distinct_id_collapses_to_empty() {
        // Validation rejects the empty result with MissingDistinctId.
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": [{
                "event": "$pageview",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "   ",
                "timestamp": "2026-03-19T14:29:58.123Z"
            }]
        }"#;
        let batch: Batch = serde_json::from_str(json).unwrap();
        assert_eq!(batch.batch[0].distinct_id, "");
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
                    "disable_skew_correction": true,
                    "product_tour_id": "tour-123",
                    "process_person_profile": false
                }
            }]
        }"#;
        let batch: Batch = serde_json::from_str(json).unwrap();
        let event = &batch.batch[0];
        assert_eq!(event.session_id.as_deref(), Some("sess-abc"));
        assert_eq!(event.window_id.as_deref(), Some("win-xyz"));
        let opts = event.options.validate().unwrap();
        assert_eq!(opts.cookieless_mode, Some(true));
        assert_eq!(opts.disable_skew_correction, Some(true));
        assert_eq!(opts.product_tour_id.as_deref(), Some("tour-123"));
        assert_eq!(opts.process_person_profile, Some(false));
    }

    #[test]
    fn parse_event_missing_options_defaults() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": [{
                "event": "$pageview",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "user-42",
                "timestamp": "2026-03-19T14:29:58.123Z"
            }]
        }"#;
        let batch: Batch = serde_json::from_str(json).unwrap();
        let event = &batch.batch[0];
        let opts = event.options.validate().unwrap();
        assert_eq!(opts.cookieless_mode, None);
        assert_eq!(opts.disable_skew_correction, None);
        assert_eq!(opts.product_tour_id, None);
        assert_eq!(opts.process_person_profile, None);
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
        let opts = event.options.validate().unwrap();
        assert_eq!(opts.cookieless_mode, None);
        assert_eq!(opts.disable_skew_correction, None);
        assert_eq!(opts.product_tour_id, None);
        assert_eq!(opts.process_person_profile, None);
    }

    #[test]
    fn parse_invalid_json() {
        let garbage = b"this is not json at all {{{";
        assert!(serde_json::from_slice::<Batch>(garbage).is_err());
    }

    // --- RawOptions::validate coercion matrix ---

    #[test]
    fn raw_options_null_validates_to_defaults() {
        let raw = RawOptions::default();
        let opts = raw.validate().unwrap();
        assert_eq!(opts.cookieless_mode, None);
        assert_eq!(opts.disable_skew_correction, None);
        assert_eq!(opts.product_tour_id, None);
        assert_eq!(opts.process_person_profile, None);
    }

    #[test]
    fn raw_options_empty_object_validates_to_defaults() {
        let raw = RawOptions(serde_json::json!({}));
        let opts = raw.validate().unwrap();
        assert_eq!(opts.cookieless_mode, None);
        assert_eq!(opts.disable_skew_correction, None);
    }

    #[rstest::rstest]
    #[case::native_true(serde_json::json!(true), Some(true))]
    #[case::native_false(serde_json::json!(false), Some(false))]
    #[case::str_true(serde_json::json!("true"), Some(true))]
    #[case::str_false(serde_json::json!("false"), Some(false))]
    #[case::str_one(serde_json::json!("1"), Some(true))]
    #[case::str_zero(serde_json::json!("0"), Some(false))]
    #[case::str_uppercase(serde_json::json!("FALSE"), Some(false))]
    #[case::str_padded(serde_json::json!("  true  "), Some(true))]
    #[case::num_one(serde_json::json!(1), Some(true))]
    #[case::num_zero(serde_json::json!(0), Some(false))]
    #[case::num_large(serde_json::json!(42), Some(true))]
    #[case::num_negative(serde_json::json!(-1), Some(true))]
    fn raw_options_bool_coercion_valid(
        #[case] input: serde_json::Value,
        #[case] expected: Option<bool>,
    ) {
        let raw = RawOptions(serde_json::json!({ "cookieless_mode": input }));
        assert_eq!(raw.validate().unwrap().cookieless_mode, expected);
    }

    #[rstest::rstest]
    #[case::array(serde_json::json!([1, 2, 3]))]
    #[case::object(serde_json::json!({"nested": true}))]
    #[case::yes(serde_json::json!("yes"))]
    #[case::off(serde_json::json!("off"))]
    #[case::empty_string(serde_json::json!(""))]
    fn raw_options_bool_uncoercible(#[case] input: serde_json::Value) {
        let raw = RawOptions(serde_json::json!({ "cookieless_mode": input }));
        let err = raw.validate().unwrap_err();
        assert_eq!(err.invalid_fields, vec!["cookieless_mode"]);
    }

    #[test]
    fn raw_options_all_bool_fields_routed_to_correct_slot() {
        let raw = RawOptions(serde_json::json!({
            "cookieless_mode": "true",
            "disable_skew_correction": 0,
            "process_person_profile": false
        }));
        let opts = raw.validate().unwrap();
        assert_eq!(opts.cookieless_mode, Some(true));
        assert_eq!(opts.disable_skew_correction, Some(false));
        assert_eq!(opts.process_person_profile, Some(false));
    }

    #[rstest::rstest]
    #[case::string(serde_json::json!("tour-123"), Some("tour-123"))]
    #[case::integer(serde_json::json!(999), Some("999"))]
    #[case::negative_integer(serde_json::json!(-5), Some("-5"))]
    fn raw_options_product_tour_id_coercion_valid(
        #[case] input: serde_json::Value,
        #[case] expected: Option<&str>,
    ) {
        let raw = RawOptions(serde_json::json!({ "product_tour_id": input }));
        assert_eq!(raw.validate().unwrap().product_tour_id.as_deref(), expected);
    }

    #[rstest::rstest]
    #[case::object(serde_json::json!({"nested": true}))]
    #[case::array(serde_json::json!(["a"]))]
    #[case::bool(serde_json::json!(true))]
    #[case::float(serde_json::json!(1.5))]
    fn raw_options_product_tour_id_uncoercible(#[case] input: serde_json::Value) {
        let raw = RawOptions(serde_json::json!({ "product_tour_id": input }));
        let err = raw.validate().unwrap_err();
        assert_eq!(err.invalid_fields, vec!["product_tour_id"]);
    }

    #[test]
    fn raw_options_multiple_invalid_fields_collected() {
        let raw = RawOptions(serde_json::json!({
            "cookieless_mode": {"bad": true},
            "disable_skew_correction": [false],
            "product_tour_id": "valid-string",
            "process_person_profile": null
        }));
        let err = raw.validate().unwrap_err();
        assert!(err.invalid_fields.contains(&"cookieless_mode"));
        assert!(err.invalid_fields.contains(&"disable_skew_correction"));
        assert!(!err.invalid_fields.contains(&"product_tour_id"));
    }

    #[test]
    fn raw_options_non_object_value_returns_error() {
        let raw = RawOptions(serde_json::json!("just a string"));
        let err = raw.validate().unwrap_err();
        assert!(err.invalid_fields.is_empty());
    }

    #[test]
    fn raw_options_unknown_fields_ignored() {
        let raw = RawOptions(serde_json::json!({
            "cookieless_mode": true,
            "some_unknown_future_field": 42
        }));
        let opts = raw.validate().unwrap();
        assert_eq!(opts.cookieless_mode, Some(true));
    }

    #[test]
    fn raw_options_null_field_treated_as_absent() {
        let raw = RawOptions(serde_json::json!({
            "cookieless_mode": null,
            "disable_skew_correction": true
        }));
        let opts = raw.validate().unwrap();
        assert_eq!(opts.cookieless_mode, None);
        assert_eq!(opts.disable_skew_correction, Some(true));
    }

    #[test]
    fn batch_deserialization_survives_mistyped_options() {
        let json = r#"{
            "created_at": "2026-03-19T14:30:00.000Z",
            "batch": [{
                "event": "$pageview",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "user-42",
                "timestamp": "2026-03-19T14:29:58.123Z",
                "options": {"disable_skew_correction": 999, "cookieless_mode": "banana"}
            }]
        }"#;
        let batch: Batch = serde_json::from_str(json).unwrap();
        assert_eq!(batch.batch.len(), 1);
        // 999 coerces to true (nonzero), "banana" does not coerce
        let err = batch.batch[0].options.validate().unwrap_err();
        assert!(err.invalid_fields.contains(&"cookieless_mode"));
        assert!(!err.invalid_fields.contains(&"disable_skew_correction"));
    }

    // --- SinkEvent impl for WrappedEvent ---

    use crate::v1::sinks::event::Event as SinkEventTrait;
    use crate::v1::sinks::Destination;
    use crate::v1::test_utils;
    use common_types::HasEventName;

    fn ok_wrapped(event_name: &str, distinct_id: &str) -> WrappedEvent {
        test_utils::wrapped_event(event_name, distinct_id)
    }

    #[rstest::rstest]
    #[case::ok_main(EventResult::Ok, Destination::AnalyticsMain)]
    #[case::ok_historical(EventResult::Ok, Destination::AnalyticsHistorical)]
    #[case::ok_overflow(EventResult::Ok, Destination::Overflow)]
    #[case::warning_main(EventResult::Warning, Destination::AnalyticsMain)]
    #[case::warning_historical(EventResult::Warning, Destination::AnalyticsHistorical)]
    #[case::warning_overflow(EventResult::Warning, Destination::Overflow)]
    fn should_publish_true(#[case] result: EventResult, #[case] dest: Destination) {
        let mut ev = ok_wrapped("$pageview", "user-1");
        ev.result = result;
        ev.destination = dest;
        assert!(ev.should_publish());
    }

    #[rstest::rstest]
    #[case::drop_main(EventResult::Drop, Destination::AnalyticsMain)]
    #[case::retry_main(EventResult::Retry, Destination::AnalyticsMain)]
    #[case::ok_dest_drop(EventResult::Ok, Destination::Drop)]
    #[case::warning_dest_drop(EventResult::Warning, Destination::Drop)]
    #[case::drop_dest_drop(EventResult::Drop, Destination::Drop)]
    #[case::retry_dest_drop(EventResult::Retry, Destination::Drop)]
    fn should_publish_false(#[case] result: EventResult, #[case] dest: Destination) {
        let mut ev = ok_wrapped("$pageview", "user-1");
        ev.result = result;
        ev.destination = dest;
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

    #[test]
    fn partition_key_normal_mode() {
        let ctx = test_utils::test_context();
        let ev = ok_wrapped("$pageview", "user-42");
        assert_eq!(ev.partition_key(&ctx), format!("{}:user-42", ctx.api_token));
    }

    #[test]
    fn partition_key_cookieless_mode() {
        let ctx = test_utils::test_context();
        let mut ev = ok_wrapped("$pageview", "user-42");
        ev.options.cookieless_mode = Some(true);
        assert_eq!(
            ev.partition_key(&ctx),
            format!("{}:{}", ctx.api_token, ctx.client_ip)
        );
    }

    #[test]
    fn partition_key_cookieless_capture_internal() {
        let mut ctx = test_utils::test_context();
        ctx.capture_internal = true;
        let mut ev = ok_wrapped("$pageview", "user-42");
        ev.options.cookieless_mode = Some(true);
        assert_eq!(
            ev.partition_key(&ctx),
            format!("{}:127.0.0.1", ctx.api_token)
        );
    }

    #[test]
    fn destination_returns_event_destination() {
        let mut ev = ok_wrapped("$pageview", "user-1");
        ev.destination = Destination::Overflow;
        assert_eq!(*ev.destination(), Destination::Overflow);
    }

    #[test]
    fn partition_key_always_writes_regardless_of_force_disable() {
        let ctx = test_utils::test_context();
        let mut ev = ok_wrapped("$pageview", "user-42");
        ev.force_disable_person_processing = true;
        ev.destination = Destination::AnalyticsMain;
        assert_eq!(
            ev.partition_key(&ctx),
            format!("{}:user-42", ctx.api_token),
            "partition_key() is unconditional; sink applies null-key policy"
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
        ev.options.product_tour_id = Some("tour-123".into());
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

    // --- serialize ---

    use std::net::{IpAddr, Ipv4Addr};

    use common_types::{CapturedEvent, RawEvent};
    use serde_json::Value;

    fn raw_obj(s: &str) -> Box<RawValue> {
        RawValue::from_string(s.to_owned()).unwrap()
    }

    fn dt(s: &str) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(s).unwrap().with_timezone(&Utc)
    }

    fn serialize_ctx() -> crate::v1::context::RequestContext {
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
                options: RawOptions::default(),
                properties: raw_obj(
                    r#"{"$current_url":"https://app.example.com/dashboard","$browser":"Chrome","custom_prop":42}"#,
                ),
            },
            uuid,
            options: Options {
                cookieless_mode: Some(false),
                disable_skew_correction: None,
                product_tour_id: None,
                process_person_profile: Some(true),
            },
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
            is_gateway_verified: false,
        }
    }

    fn serialize_and_parse(
        wrapped: &WrappedEvent,
        ctx: &crate::v1::context::RequestContext,
    ) -> (CapturedEvent, RawEvent) {
        let buf = wrapped.serialize(ctx).expect("serialize failed");
        let captured: CapturedEvent =
            serde_json::from_slice(&buf).expect("v1 output must deserialize as CapturedEvent");
        let data: RawEvent =
            serde_json::from_str(&captured.data).expect("data field must deserialize as RawEvent");
        (captured, data)
    }

    #[test]
    fn serialize_fails_without_adjusted_timestamp() {
        let mut ev = pageview_event();
        ev.adjusted_timestamp = None;
        let ctx = serialize_ctx();
        let err = ev.serialize(&ctx).unwrap_err();
        assert!(
            err.to_string().contains("adjusted_timestamp"),
            "error should mention adjusted_timestamp: {err}"
        );
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
    fn serialize_injects_lib_from_sdk_info_header() {
        let wrapped = pageview_event();
        let ctx = serialize_ctx(); // sdk_info: "posthog-rs/1.0.0"
        let (_, data) = serialize_and_parse(&wrapped, &ctx);

        assert_eq!(data.properties["$lib"], "posthog-rs");
        assert_eq!(data.properties["$lib_version"], "1.0.0");
    }

    #[test]
    fn serialize_lib_injection_header_wins_over_client_properties() {
        let mut wrapped = pageview_event();
        wrapped.event.properties =
            raw_obj(r#"{"$lib":"client-lib","$lib_version":"9.9.9","custom_prop":42}"#);
        let ctx = serialize_ctx();
        let (_, data) = serialize_and_parse(&wrapped, &ctx);

        // Injections append after client keys; last-key-wins parsing makes
        // the header authoritative.
        assert_eq!(data.properties["$lib"], "posthog-rs");
        assert_eq!(data.properties["$lib_version"], "1.0.0");
        assert_eq!(data.properties["custom_prop"], 42);
    }

    #[test]
    fn serialize_oversized_sdk_info_skips_lib_injection() {
        use crate::v1::constants::MAX_SDK_INFO_LEN;

        let wrapped = pageview_event();
        let mut ctx = serialize_ctx();
        ctx.sdk_info = format!("posthog-rs/{}", "9".repeat(MAX_SDK_INFO_LEN));
        let (_, data) = serialize_and_parse(&wrapped, &ctx);

        assert!(!data.properties.contains_key("$lib"));
        assert!(!data.properties.contains_key("$lib_version"));
    }

    #[test]
    fn serialize_malformed_sdk_info_skips_lib_injection() {
        for bad in &["garbage-no-slash", "/1.0.0", "posthog-rs/", ""] {
            let wrapped = pageview_event();
            let mut ctx = serialize_ctx();
            ctx.sdk_info = bad.to_string();
            let (_, data) = serialize_and_parse(&wrapped, &ctx);

            // No placeholders: absent rather than "unknown"/"0.0.0".
            assert!(
                !data.properties.contains_key("$lib"),
                "expected no $lib for sdk_info {bad:?}"
            );
            assert!(
                !data.properties.contains_key("$lib_version"),
                "expected no $lib_version for sdk_info {bad:?}"
            );
        }
    }

    #[test]
    fn serialize_padded_distinct_id_trimmed_everywhere() {
        // Padding is stripped at the deserialization boundary; everything
        // downstream (serialization, headers, partition key) sees it trimmed.
        let mut wrapped = pageview_event();
        let json = format!(
            r#"{{"event":"$pageview","uuid":"{}","distinct_id":"  user-42  ","timestamp":"2026-03-19T14:29:58.123Z"}}"#,
            wrapped.uuid
        );
        wrapped.event = serde_json::from_str(&json).unwrap();
        assert_eq!(wrapped.event.distinct_id, "user-42");
        let ctx = serialize_ctx();

        let (captured, data) = serialize_and_parse(&wrapped, &ctx);
        assert_eq!(captured.distinct_id, "user-42");
        assert_eq!(data.distinct_id, Some(Value::String("user-42".to_string())));

        let headers = wrapped.headers(&ctx);
        assert_eq!(headers.distinct_id.as_deref(), Some("user-42"));

        let key = wrapped.partition_key(&ctx);
        assert_eq!(key, format!("{}:user-42", ctx.api_token));
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
                options: RawOptions::default(),
                properties: raw_obj(r#"{"existing":"value"}"#),
            },
            uuid,
            options: Options {
                cookieless_mode: Some(true),
                disable_skew_correction: Some(true),
                product_tour_id: Some("tour-onboarding-v2".to_string()),
                process_person_profile: Some(false),
            },
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
            is_gateway_verified: false,
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
                options: RawOptions::default(),
                properties: raw_obj(r#"{"x":1}"#),
            },
            uuid,
            options: Options {
                cookieless_mode: Some(false),
                disable_skew_correction: None,
                product_tour_id: None,
                process_person_profile: None,
            },
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
            is_gateway_verified: false,
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
                options: RawOptions::default(),
                properties: raw_obj("{}"),
            },
            uuid,
            options: Options {
                cookieless_mode: None,
                disable_skew_correction: None,
                product_tour_id: None,
                process_person_profile: None,
            },
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
            is_gateway_verified: false,
        };

        let ctx = serialize_ctx();
        let (_, data) = serialize_and_parse(&wrapped, &ctx);
        // $lib/$lib_version always materialize from the (valid) Sdk-Info header.
        let props = &data.properties;
        assert_eq!(props["$lib"], "posthog-rs");
        assert_eq!(props["$lib_version"], "1.0.0");
        assert_eq!(props.len(), 2);
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
                options: RawOptions::default(),
                properties: raw_obj("{}"),
            },
            uuid,
            options: Options {
                cookieless_mode: Some(true),
                disable_skew_correction: None,
                product_tour_id: None,
                process_person_profile: None,
            },
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
            is_gateway_verified: false,
        };

        let ctx = serialize_ctx();
        let (_, data) = serialize_and_parse(&wrapped, &ctx);
        let props = &data.properties;
        assert_eq!(props["$session_id"], "sess-abc");
        assert_eq!(props["$cookieless_mode"], true);
        assert_eq!(props["$lib"], "posthog-rs");
        assert_eq!(props["$lib_version"], "1.0.0");
        assert_eq!(props.len(), 4);
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
                options: RawOptions::default(),
                properties: raw_obj(
                    r#"{"$lib":"posthog-js","$lib_version":"1.150.0","$referrer":"https://google.com"}"#,
                ),
            },
            uuid,
            options: Options {
                cookieless_mode: None,
                disable_skew_correction: None,
                product_tour_id: None,
                process_person_profile: None,
            },
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
            is_gateway_verified: false,
        };

        let ctx = serialize_ctx();
        let (_, data) = serialize_and_parse(&wrapped, &ctx);
        let props = &data.properties;
        // Non-identity client properties survive; $lib/$lib_version come from
        // the Sdk-Info header (header-wins).
        assert_eq!(props["$lib"], "posthog-rs");
        assert_eq!(props["$lib_version"], "1.0.0");
        assert_eq!(props["$referrer"], "https://google.com");
        assert_eq!(props["$session_id"], "sess-abc");
    }

    #[test]
    fn serialize_is_cookieless_mode_true() {
        let mut wrapped = pageview_event();
        wrapped.options.cookieless_mode = Some(true);
        let ctx = serialize_ctx();
        let (captured, data) = serialize_and_parse(&wrapped, &ctx);
        assert!(captured.is_cookieless_mode);
        assert_eq!(data.properties["$cookieless_mode"], true);
    }

    #[test]
    fn serialize_is_cookieless_mode_false_skipped() {
        let wrapped = pageview_event();
        assert_eq!(wrapped.options.cookieless_mode, Some(false));
        let ctx = serialize_ctx();
        let buf = wrapped.serialize(&ctx).unwrap();
        let val: Value = serde_json::from_slice(&buf).unwrap();
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
        let buf = wrapped.serialize(&ctx).unwrap();
        let val: Value = serde_json::from_slice(&buf).unwrap();
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
        wrapped.options.process_person_profile = Some(false);
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
                options: RawOptions::default(),
                properties: raw_obj(r#"{"x":1}"#),
            },
            uuid,
            options: Options {
                cookieless_mode: None,
                disable_skew_correction: None,
                product_tour_id: None,
                process_person_profile: None,
            },
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: true,
            is_gateway_verified: false,
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
                options: RawOptions::default(),
                properties: raw_obj(r#"{"$browser":"Safari","$os":"macOS"}"#),
            },
            uuid,
            options: Options {
                cookieless_mode: None,
                disable_skew_correction: None,
                product_tour_id: None,
                process_person_profile: Some(true),
            },
            adjusted_timestamp: Some(dt("2026-03-19T14:29:55.000Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
            is_gateway_verified: false,
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
                options: RawOptions::default(),
                properties: raw_obj("[1,2,3]"),
            },
            uuid,
            options: Options {
                cookieless_mode: None,
                disable_skew_correction: None,
                product_tour_id: None,
                process_person_profile: None,
            },
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
            is_gateway_verified: false,
        };

        let ctx = serialize_ctx();
        let err = wrapped.serialize(&ctx).unwrap_err();
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
                options: RawOptions::default(),
                properties: raw_obj("{   }"),
            },
            uuid,
            options: Options {
                cookieless_mode: None,
                disable_skew_correction: None,
                product_tour_id: None,
                process_person_profile: None,
            },
            adjusted_timestamp: Some(dt("2026-03-19T14:29:53.123Z")),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
            is_gateway_verified: false,
        };

        let ctx = serialize_ctx();
        let (_, data) = serialize_and_parse(&wrapped, &ctx);
        assert_eq!(data.properties["$session_id"], "sess-abc");
        assert_eq!(data.properties["$lib"], "posthog-rs");
        assert_eq!(data.properties["$lib_version"], "1.0.0");
        assert_eq!(data.properties.len(), 3);
    }

    // --- CapturedEvent round-trip parity using realistic fixtures ---

    use crate::v1::test_utils::{
        assert_round_trip, realistic_batch, realistic_custom, realistic_identify,
        realistic_pageview, realistic_spread_destinations, WrappedEventMut,
    };

    #[test]
    fn round_trip_realistic_pageview() {
        let ctx = serialize_ctx();
        let ev = realistic_pageview("user-42");
        let (captured, data) = assert_round_trip(&ev, &ctx);
        assert_eq!(captured.event, "$pageview");
        assert_eq!(captured.distinct_id, "user-42");
        assert_eq!(
            data.properties["$current_url"],
            "https://app.example.com/dashboard"
        );
        assert_eq!(
            data.properties["$session_id"],
            "01jq9abc-def0-1234-5678-9abcdef01234"
        );
        assert_eq!(
            data.properties["$window_id"],
            "01jq9xyz-0000-4321-8765-fedcba987654"
        );
        assert_eq!(data.properties["$cookieless_mode"], false);
        assert_eq!(data.properties["$process_person_profile"], true);
    }

    #[test]
    fn round_trip_realistic_identify() {
        let ctx = serialize_ctx();
        let ev = realistic_identify("user-99");
        let (captured, data) = assert_round_trip(&ev, &ctx);
        assert_eq!(captured.event, "$identify");
        assert_eq!(captured.distinct_id, "user-99");
        assert_eq!(data.properties["$set"]["email"], "user@example.com");
        assert_eq!(data.properties["$process_person_profile"], true);
    }

    #[test]
    fn round_trip_realistic_custom() {
        let ctx = serialize_ctx();
        let ev = realistic_custom("user-7", "button_clicked");
        let (captured, data) = assert_round_trip(&ev, &ctx);
        assert_eq!(captured.event, "button_clicked");
        assert_eq!(data.properties["button_id"], "cta-signup");
        assert_eq!(data.properties["$process_person_profile"], true);
    }

    #[test]
    fn round_trip_realistic_batch_all_events() {
        let ctx = serialize_ctx();
        for ev in &realistic_batch() {
            assert_round_trip(ev, &ctx);
        }
    }

    #[test]
    fn round_trip_spread_destinations() {
        let ctx = serialize_ctx();
        for ev in &realistic_spread_destinations() {
            if (ev.result == EventResult::Ok || ev.result == EventResult::Warning)
                && ev.adjusted_timestamp.is_some()
            {
                assert_round_trip(ev, &ctx);
            }
        }
    }

    // --- Kafka header parity checks ---

    #[test]
    fn headers_parity_pageview() {
        let ctx = serialize_ctx();
        let ev = realistic_pageview("user-42");
        let h = ev.headers(&ctx);
        assert_eq!(h.token, Some(ctx.api_token.clone()));
        assert_eq!(h.distinct_id.as_deref(), Some("user-42"));
        assert_eq!(h.event.as_deref(), Some("$pageview"));
        assert_eq!(
            h.session_id.as_deref(),
            Some("01jq9abc-def0-1234-5678-9abcdef01234")
        );
        assert!(h.uuid.is_some());
        assert!(h.timestamp.is_some());
        assert!(h.force_disable_person_processing.is_none());
        assert!(h.historical_migration.is_none());
    }

    #[test]
    fn headers_parity_historical_migration() {
        let mut ctx = serialize_ctx();
        ctx.historical_migration = true;
        let ev = realistic_pageview("user-42");
        let h = ev.headers(&ctx);
        assert_eq!(h.historical_migration, Some(true));
    }

    #[test]
    fn headers_parity_force_disable_person_processing() {
        let ctx = serialize_ctx();
        let ev = realistic_pageview("user-42").with_force_disable_person_processing(true);
        let h = ev.headers(&ctx);
        assert_eq!(h.force_disable_person_processing, Some(true));
    }

    #[test]
    fn headers_parity_dlq_destination() {
        let ctx = serialize_ctx();
        let ev = realistic_pageview("user-42").with_destination(Destination::Dlq);
        let h = ev.headers(&ctx);
        assert_eq!(h.dlq_reason.as_deref(), Some("event_restriction"));
        assert_eq!(h.dlq_step.as_deref(), Some("capture"));
        assert!(h.dlq_timestamp.is_some());
    }

    // --- Partition key parity ---

    #[test]
    fn partition_key_parity_normal() {
        let ctx = serialize_ctx();
        let ev = realistic_pageview("user-42");
        let key = ev.partition_key(&ctx);
        assert_eq!(key, format!("{}:user-42", ctx.api_token));
    }

    #[test]
    fn partition_key_parity_cookieless() {
        let ctx = serialize_ctx();
        let mut ev = realistic_pageview("user-42");
        ev.options.cookieless_mode = Some(true);
        let key = ev.partition_key(&ctx);
        assert_eq!(key, format!("{}:{}", ctx.api_token, ctx.client_ip));
    }

    #[test]
    fn partition_key_parity_force_disable_main() {
        let ctx = serialize_ctx();
        let ev = realistic_pageview("user-42")
            .with_force_disable_person_processing(true)
            .with_destination(Destination::AnalyticsMain);
        let key = ev.partition_key(&ctx);
        assert_eq!(
            key,
            format!("{}:user-42", ctx.api_token),
            "partition_key() is unconditional; sink applies null-key policy"
        );
    }
}
