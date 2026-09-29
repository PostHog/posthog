use std::io;
use std::ops::Not;

use chrono::{DateTime, SecondsFormat, Utc};
use common_types::{CapturedEventHeaders, HasEventName, COOKIELESS_SENTINEL_VALUE};
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

use super::constants::{DETAIL_COOKIELESS_MODE_REQUIRED, DETAIL_INVALID_OPTIONS};
use crate::ordering::{person_ordering, OrderingGuarantee};
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
    /// Read like a boolean option, so an unreadable value means "not set"
    /// instead of failing the whole batch.
    #[serde(default, deserialize_with = "deserialize_lenient_flag")]
    pub capture_internal: Option<bool>,
    pub batch: Vec<Event>,
}

fn deserialize_lenient_flag<'de, D>(deserializer: D) -> Result<Option<bool>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    Ok(match coerce_bool(&value) {
        Parsed::Set(flag) => Some(flag),
        Parsed::Unset | Parsed::Invalid => None,
    })
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

/// An option key capture reads, validates and forwards. Capture ignores every
/// other key.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExpectedOption {
    CookielessMode,
    DisableSkewCorrection,
    ProcessPersonProfile,
    ProductTourId,
}

impl ExpectedOption {
    /// The order capture checks keys in, which is also the order it reports them in.
    const ALL: [Self; 4] = [
        Self::CookielessMode,
        Self::DisableSkewCorrection,
        Self::ProcessPersonProfile,
        Self::ProductTourId,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            Self::CookielessMode => "cookieless_mode",
            Self::DisableSkewCorrection => "disable_skew_correction",
            Self::ProcessPersonProfile => "process_person_profile",
            Self::ProductTourId => "product_tour_id",
        }
    }

    fn bit(self) -> u8 {
        1 << self as u8
    }
}

/// A set of expected option keys. It holds each key at most once and lists
/// them in `ExpectedOption::ALL` order, so unions across a batch stay bounded.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct OptionKeys(u8);

impl OptionKeys {
    pub fn of(key: ExpectedOption) -> Self {
        Self(key.bit())
    }

    fn insert(&mut self, key: ExpectedOption) {
        self.0 |= key.bit();
    }

    pub fn union(self, other: Self) -> Self {
        Self(self.0 | other.0)
    }

    pub fn is_empty(self) -> bool {
        self.0 == 0
    }

    pub fn names(self) -> impl Iterator<Item = &'static str> {
        ExpectedOption::ALL
            .into_iter()
            .filter(move |key| self.0 & key.bit() != 0)
            .map(ExpectedOption::as_str)
    }
}

/// Why `RawOptions::validate_for` rejected an event's options. The event is
/// dropped either way.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OptionsError {
    /// Expected keys whose values capture cannot read. Empty when `options`
    /// is not a JSON object.
    InvalidValues(OptionKeys),
    /// The distinct_id is the cookieless placeholder but `cookieless_mode` is
    /// not true.
    CookielessModeRequired,
}

impl OptionsError {
    /// The per-event `details` tag, which also labels the malformed-event metric.
    pub fn detail(self) -> &'static str {
        match self {
            Self::InvalidValues(_) => DETAIL_INVALID_OPTIONS,
            Self::CookielessModeRequired => DETAIL_COOKIELESS_MODE_REQUIRED,
        }
    }

    /// The expected keys to name in logs and in the ingestion warning.
    pub fn failed_keys(self) -> OptionKeys {
        match self {
            Self::InvalidValues(keys) => keys,
            Self::CookielessModeRequired => OptionKeys::of(ExpectedOption::CookielessMode),
        }
    }
}

impl RawOptions {
    /// Validate the options of an event with this (already trimmed) distinct_id.
    /// An unreadable value wins over the placeholder check.
    pub fn validate_for(&self, distinct_id: &str) -> Result<Options, OptionsError> {
        let options = self.validate()?;
        // Ingestion replaces the placeholder with a per-visitor id only when
        // cookieless mode is on. Without it, every visitor of the project
        // merges into one person and one hot partition.
        if distinct_id == COOKIELESS_SENTINEL_VALUE && options.cookieless_mode != Some(true) {
            return Err(OptionsError::CookielessModeRequired);
        }
        Ok(options)
    }

    fn validate(&self) -> Result<Options, OptionsError> {
        let map = match &self.0 {
            Value::Null => return Ok(Options::default()),
            Value::Object(map) => map,
            _ => return Err(OptionsError::InvalidValues(OptionKeys::default())),
        };

        let mut invalid = OptionKeys::default();
        let options = Options {
            cookieless_mode: read_option(
                map,
                ExpectedOption::CookielessMode,
                coerce_bool,
                &mut invalid,
            ),
            disable_skew_correction: read_option(
                map,
                ExpectedOption::DisableSkewCorrection,
                coerce_bool,
                &mut invalid,
            ),
            process_person_profile: read_option(
                map,
                ExpectedOption::ProcessPersonProfile,
                coerce_bool,
                &mut invalid,
            ),
            product_tour_id: read_option(
                map,
                ExpectedOption::ProductTourId,
                coerce_product_tour_id,
                &mut invalid,
            ),
        };

        if invalid.is_empty() {
            Ok(options)
        } else {
            Err(OptionsError::InvalidValues(invalid))
        }
    }
}

/// The result of reading one expected option value.
enum Parsed<T> {
    Set(T),
    Unset,
    Invalid,
}

fn read_option<T>(
    map: &serde_json::Map<String, Value>,
    key: ExpectedOption,
    parse: fn(&Value) -> Parsed<T>,
    invalid: &mut OptionKeys,
) -> Option<T> {
    match map.get(key.as_str()).map_or(Parsed::Unset, parse) {
        Parsed::Set(value) => Some(value),
        Parsed::Unset => None,
        Parsed::Invalid => {
            invalid.insert(key);
            None
        }
    }
}

/// Read a boolean leniently: booleans, numbers (zero is off), on/off words and
/// numeric strings. `null` and blank strings mean "not set".
fn coerce_bool(v: &Value) -> Parsed<bool> {
    match v {
        Value::Null => Parsed::Unset,
        Value::Bool(b) => Parsed::Set(*b),
        Value::Number(n) => n
            .as_f64()
            .map_or(Parsed::Invalid, |f| Parsed::Set(f != 0.0)),
        Value::String(s) => parse_bool_str(s),
        Value::Array(_) | Value::Object(_) => Parsed::Invalid,
    }
}

fn parse_bool_str(raw: &str) -> Parsed<bool> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Parsed::Unset;
    }
    match trimmed.to_ascii_lowercase().as_str() {
        "true" | "t" | "yes" | "y" | "on" => Parsed::Set(true),
        "false" | "f" | "no" | "n" | "off" => Parsed::Set(false),
        // Rust's float parser also accepts "inf" and "nan", which are not numbers
        // a sender means as a flag.
        other => match other.parse::<f64>() {
            Ok(f) if f.is_finite() => Parsed::Set(f != 0.0),
            _ => Parsed::Invalid,
        },
    }
}

/// `product_tour_id` must be a string, forwarded unchanged. A blank string
/// means "not set".
fn coerce_product_tour_id(v: &Value) -> Parsed<String> {
    match v {
        Value::Null => Parsed::Unset,
        Value::String(s) if s.trim().is_empty() => Parsed::Unset,
        Value::String(s) => Parsed::Set(s.clone()),
        _ => Parsed::Invalid,
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
    /// Set when the overflow limiter decided this key is bursting and should
    /// be spread across the overflow topic's partitions. Deliberately separate
    /// from `force_disable_person_processing`: spreading a hot key is a
    /// partitioning decision, while disabling person processing is a
    /// customer-visible instruction to skip identity resolution, and the
    /// overflow limiter only means the former. Consumed by `ordering()`,
    /// which realizes it only on lanes whose consumers do not write persons —
    /// elsewhere the key holds until person processing is off.
    pub spread_partitions: bool,
    /// Set by the gateway-provenance step when a valid signature was verified;
    /// read by the quota shim to exempt the event from the llm_events limiter.
    pub is_gateway_verified: bool,
}

impl WrappedEvent {
    /// The expected option keys that made validation drop this event, empty for
    /// any other outcome. Recomputed from the options because only dropped
    /// events need it.
    pub fn failed_option_keys(&self) -> OptionKeys {
        match self.details {
            Some(DETAIL_INVALID_OPTIONS | DETAIL_COOKIELESS_MODE_REQUIRED) => self
                .event
                .options
                .validate_for(&self.event.distinct_id)
                .err()
                .map_or_else(OptionKeys::default, OptionsError::failed_keys),
            _ => OptionKeys::default(),
        }
    }
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
        // Downstream treats this header as absolute: `decideProcessPerson` in
        // nodejs/src/common/persons/person-utils.ts skips person processing
        // outright when it is set. So it carries only the person-processing
        // decision, never the partitioning one, which travels as `ordering()`.
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

    /// Computed here rather than stamped during processing because it depends
    /// on the final destination: `apply_restrictions` can disable person
    /// processing while an event is still `AnalyticsMain`, and
    /// `apply_historical_rerouting` may afterwards move it to
    /// `AnalyticsHistorical`, whose consumers need the key. Deciding late
    /// keeps the rule correct no matter how the stages are ordered.
    fn ordering(&self) -> OrderingGuarantee {
        if !self.destination.absorbs_hot_keys() {
            return OrderingGuarantee::PerDistinctId;
        }
        // A spread decision takes effect on its own only where the consumer
        // does not write persons; on person-writing lanes the key holds until
        // person processing is off, so the person flag alone decides there
        // (see `Destination::writes_persons`).
        if self.spread_partitions && !self.destination.writes_persons() {
            return OrderingGuarantee::None;
        }
        person_ordering(self.force_disable_person_processing)
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

    fn invalid(keys: &[ExpectedOption]) -> OptionsError {
        OptionsError::InvalidValues(keys.iter().fold(OptionKeys::default(), |acc, key| {
            acc.union(OptionKeys::of(*key))
        }))
    }

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
    #[case::str_t(serde_json::json!("t"), Some(true))]
    #[case::str_f(serde_json::json!("f"), Some(false))]
    #[case::str_yes(serde_json::json!("yes"), Some(true))]
    #[case::str_no(serde_json::json!("no"), Some(false))]
    #[case::str_y(serde_json::json!("y"), Some(true))]
    #[case::str_n(serde_json::json!("n"), Some(false))]
    #[case::str_on(serde_json::json!("on"), Some(true))]
    #[case::str_off(serde_json::json!("off"), Some(false))]
    #[case::str_one(serde_json::json!("1"), Some(true))]
    #[case::str_zero(serde_json::json!("0"), Some(false))]
    #[case::str_uppercase(serde_json::json!("FALSE"), Some(false))]
    #[case::str_mixed_case(serde_json::json!("Yes"), Some(true))]
    #[case::str_padded(serde_json::json!("  true  "), Some(true))]
    #[case::str_float_one(serde_json::json!("1.0"), Some(true))]
    #[case::str_float_zero(serde_json::json!("0.0"), Some(false))]
    #[case::str_negative_zero(serde_json::json!("-0"), Some(false))]
    #[case::str_negative(serde_json::json!("-1"), Some(true))]
    #[case::num_one(serde_json::json!(1), Some(true))]
    #[case::num_zero(serde_json::json!(0), Some(false))]
    #[case::num_float_zero(serde_json::json!(0.0), Some(false))]
    #[case::num_float(serde_json::json!(1.5), Some(true))]
    #[case::num_large(serde_json::json!(42), Some(true))]
    #[case::num_negative(serde_json::json!(-1), Some(true))]
    #[case::null_is_unset(serde_json::json!(null), None)]
    #[case::empty_is_unset(serde_json::json!(""), None)]
    #[case::blank_is_unset(serde_json::json!("   "), None)]
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
    #[case::junk_word(serde_json::json!("maybe"))]
    #[case::redaction_placeholder(serde_json::json!("[Filtered]"))]
    #[case::nan_word(serde_json::json!("nan"))]
    #[case::inf_word(serde_json::json!("inf"))]
    fn raw_options_bool_uncoercible(#[case] input: serde_json::Value) {
        let raw = RawOptions(serde_json::json!({ "cookieless_mode": input }));
        assert_eq!(
            raw.validate().unwrap_err(),
            invalid(&[ExpectedOption::CookielessMode])
        );
    }

    #[test]
    fn raw_options_all_bool_fields_routed_to_correct_slot() {
        let raw = RawOptions(serde_json::json!({
            "cookieless_mode": "true",
            "disable_skew_correction": 0,
            "process_person_profile": "no"
        }));
        let opts = raw.validate().unwrap();
        assert_eq!(opts.cookieless_mode, Some(true));
        assert_eq!(opts.disable_skew_correction, Some(false));
        assert_eq!(opts.process_person_profile, Some(false));
    }

    #[rstest::rstest]
    #[case::string(serde_json::json!("tour-123"), Some("tour-123"))]
    #[case::padded_kept_unchanged(serde_json::json!(" tour-123 "), Some(" tour-123 "))]
    #[case::null_is_unset(serde_json::json!(null), None)]
    #[case::empty_is_unset(serde_json::json!(""), None)]
    #[case::blank_is_unset(serde_json::json!("  "), None)]
    fn raw_options_product_tour_id_coercion_valid(
        #[case] input: serde_json::Value,
        #[case] expected: Option<&str>,
    ) {
        let raw = RawOptions(serde_json::json!({ "product_tour_id": input }));
        assert_eq!(raw.validate().unwrap().product_tour_id.as_deref(), expected);
    }

    #[rstest::rstest]
    #[case::integer(serde_json::json!(999))]
    #[case::negative_integer(serde_json::json!(-5))]
    #[case::float(serde_json::json!(1.5))]
    #[case::bool(serde_json::json!(true))]
    #[case::array(serde_json::json!(["a"]))]
    #[case::object(serde_json::json!({"nested": true}))]
    fn raw_options_product_tour_id_uncoercible(#[case] input: serde_json::Value) {
        let raw = RawOptions(serde_json::json!({ "product_tour_id": input }));
        assert_eq!(
            raw.validate().unwrap_err(),
            invalid(&[ExpectedOption::ProductTourId])
        );
    }

    #[test]
    fn raw_options_invalid_keys_reported_once_in_check_order() {
        let raw = RawOptions(serde_json::json!({
            "product_tour_id": 7,
            "disable_skew_correction": [false],
            "cookieless_mode": {"bad": true},
            "process_person_profile": null
        }));
        let err = raw.validate().unwrap_err();
        assert_eq!(err.detail(), "invalid_options");
        assert_eq!(
            err.failed_keys().names().collect::<Vec<_>>(),
            vec![
                "cookieless_mode",
                "disable_skew_correction",
                "product_tour_id"
            ]
        );
    }

    #[test]
    fn option_keys_union_is_deduplicated_and_ordered() {
        let first = OptionKeys::of(ExpectedOption::ProductTourId)
            .union(OptionKeys::of(ExpectedOption::CookielessMode));
        let second = OptionKeys::of(ExpectedOption::CookielessMode)
            .union(OptionKeys::of(ExpectedOption::ProcessPersonProfile))
            .union(OptionKeys::of(ExpectedOption::DisableSkewCorrection));
        assert_eq!(
            first.union(second).names().collect::<Vec<_>>(),
            vec![
                "cookieless_mode",
                "disable_skew_correction",
                "process_person_profile",
                "product_tour_id"
            ]
        );
    }

    #[test]
    fn raw_options_non_object_value_returns_error() {
        let raw = RawOptions(serde_json::json!("just a string"));
        let err = raw.validate().unwrap_err();
        assert_eq!(err.detail(), "invalid_options");
        assert!(err.failed_keys().is_empty());
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
        let err = batch.batch[0].options.validate().unwrap_err();
        assert_eq!(err, invalid(&[ExpectedOption::CookielessMode]));
    }

    // --- RawOptions::validate_for: the cookieless placeholder rule ---

    #[rstest::rstest]
    #[case::placeholder_with_true("$posthog_cookieless", serde_json::json!({"cookieless_mode": true}), Ok(()))]
    #[case::placeholder_with_yes("$posthog_cookieless", serde_json::json!({"cookieless_mode": "yes"}), Ok(()))]
    #[case::placeholder_with_one("$posthog_cookieless", serde_json::json!({"cookieless_mode": 1}), Ok(()))]
    #[case::placeholder_without_options("$posthog_cookieless", serde_json::json!(null), Err(OptionsError::CookielessModeRequired))]
    #[case::placeholder_empty_options("$posthog_cookieless", serde_json::json!({}), Err(OptionsError::CookielessModeRequired))]
    #[case::placeholder_null_option("$posthog_cookieless", serde_json::json!({"cookieless_mode": null}), Err(OptionsError::CookielessModeRequired))]
    #[case::placeholder_blank_option("$posthog_cookieless", serde_json::json!({"cookieless_mode": ""}), Err(OptionsError::CookielessModeRequired))]
    #[case::placeholder_false("$posthog_cookieless", serde_json::json!({"cookieless_mode": false}), Err(OptionsError::CookielessModeRequired))]
    #[case::placeholder_no("$posthog_cookieless", serde_json::json!({"cookieless_mode": "no"}), Err(OptionsError::CookielessModeRequired))]
    #[case::bad_value_wins("$posthog_cookieless", serde_json::json!({"cookieless_mode": "maybe"}), Err(invalid(&[ExpectedOption::CookielessMode])))]
    #[case::other_bad_value_wins("$posthog_cookieless", serde_json::json!({"cookieless_mode": true, "product_tour_id": 5}), Err(invalid(&[ExpectedOption::ProductTourId])))]
    #[case::real_id_without_options("user-1", serde_json::json!(null), Ok(()))]
    #[case::uppercase_is_not_placeholder("$POSTHOG_COOKIELESS", serde_json::json!(null), Ok(()))]
    #[case::suffix_is_not_placeholder("$posthog_cookieless_1", serde_json::json!(null), Ok(()))]
    fn raw_options_validate_for_placeholder(
        #[case] distinct_id: &str,
        #[case] options: serde_json::Value,
        #[case] expected: Result<(), OptionsError>,
    ) {
        let result = RawOptions(options).validate_for(distinct_id).map(|_| ());
        assert_eq!(result, expected);
    }

    #[rstest::rstest]
    #[case::invalid_values(invalid(&[ExpectedOption::ProcessPersonProfile]), "invalid_options", vec!["process_person_profile"])]
    #[case::cookieless_mode_required(OptionsError::CookielessModeRequired, "cookieless_mode_required", vec!["cookieless_mode"])]
    fn options_error_detail_and_failed_keys(
        #[case] err: OptionsError,
        #[case] detail: &str,
        #[case] keys: Vec<&str>,
    ) {
        assert_eq!(err.detail(), detail);
        assert_eq!(err.failed_keys().names().collect::<Vec<_>>(), keys);
    }

    #[rstest::rstest]
    #[case::native_true(serde_json::json!(true), Some(true))]
    #[case::native_false(serde_json::json!(false), Some(false))]
    #[case::str_true(serde_json::json!("true"), Some(true))]
    #[case::str_yes(serde_json::json!("yes"), Some(true))]
    #[case::num_one(serde_json::json!(1), Some(true))]
    #[case::str_zero(serde_json::json!("0"), Some(false))]
    #[case::null(serde_json::json!(null), None)]
    #[case::empty(serde_json::json!(""), None)]
    #[case::junk(serde_json::json!("maybe"), None)]
    #[case::object(serde_json::json!({"x": 1}), None)]
    #[case::array(serde_json::json!([true]), None)]
    fn parse_batch_capture_internal_is_lenient(
        #[case] flag: serde_json::Value,
        #[case] expected: Option<bool>,
    ) {
        let json = serde_json::json!({
            "created_at": "2026-03-19T14:30:00.000Z",
            "capture_internal": flag,
            "batch": []
        });
        let batch: Batch = serde_json::from_value(json).unwrap();
        assert_eq!(batch.capture_internal, expected);
    }

    // --- SinkEvent impl for WrappedEvent ---

    use crate::v1::sinks::event::Event as SinkEventTrait;
    use crate::v1::sinks::Destination;
    use crate::v1::test_utils;
    use common_types::HasEventName;

    fn ok_wrapped(event_name: &str, distinct_id: &str) -> WrappedEvent {
        test_utils::wrapped_event(event_name, distinct_id)
    }

    /// One row of the ordering matrix: the lane, plus the two event stamps
    /// `ordering()` consults — `person_off` mirrors
    /// `force_disable_person_processing`, `spread` mirrors `spread_partitions`.
    struct Stamps {
        destination: Destination,
        person_off: bool,
        spread: bool,
    }

    impl Stamps {
        fn on(destination: Destination) -> Self {
            Self {
                destination,
                person_off: false,
                spread: false,
            }
        }
    }

    /// The ordering rule, per lane and per reason for giving ordering up. The
    /// `spread`-without-`person_off` rows are the ones that matter most:
    /// on the person-writing analytics lanes a bursting key must keep its
    /// partition key while person processing is on (spreading one distinct id
    /// across partitions contends the consumer's person updates), while the
    /// read-only AI overflow lane spreads it immediately.
    #[rstest::rstest]
    #[case::main_untouched(
        Stamps::on(Destination::AnalyticsMain),
        OrderingGuarantee::PerDistinctId
    )]
    #[case::main_person_off(
        Stamps { person_off: true, ..Stamps::on(Destination::AnalyticsMain) },
        OrderingGuarantee::None
    )]
    #[case::main_spread(
        Stamps { spread: true, ..Stamps::on(Destination::AnalyticsMain) },
        OrderingGuarantee::PerDistinctId
    )]
    #[case::overflow_untouched(Stamps::on(Destination::Overflow), OrderingGuarantee::PerDistinctId)]
    #[case::overflow_person_off(
        Stamps { person_off: true, ..Stamps::on(Destination::Overflow) },
        OrderingGuarantee::None
    )]
    #[case::overflow_spread(
        Stamps { spread: true, ..Stamps::on(Destination::Overflow) },
        OrderingGuarantee::PerDistinctId
    )]
    #[case::overflow_spread_person_off(
        Stamps { person_off: true, spread: true, ..Stamps::on(Destination::Overflow) },
        OrderingGuarantee::None
    )]
    #[case::ai_overflow_spread(
        Stamps { spread: true, ..Stamps::on(Destination::AiEventsOverflow) },
        OrderingGuarantee::None
    )]
    #[case::ai_overflow_person_off(
        Stamps { person_off: true, ..Stamps::on(Destination::AiEventsOverflow) },
        OrderingGuarantee::None
    )]
    // Lanes whose consumers need the key regardless: person processing being
    // off must not spread them, matching v0's route().
    #[case::ai_main_person_off(
        Stamps { person_off: true, ..Stamps::on(Destination::AiEvents) },
        OrderingGuarantee::PerDistinctId
    )]
    #[case::historical_person_off(
        Stamps { person_off: true, ..Stamps::on(Destination::AnalyticsHistorical) },
        OrderingGuarantee::PerDistinctId
    )]
    #[case::dlq_person_off(
        Stamps { person_off: true, ..Stamps::on(Destination::Dlq) },
        OrderingGuarantee::PerDistinctId
    )]
    #[case::custom_person_off(
        Stamps { person_off: true, ..Stamps::on(Destination::Custom("t".into())) },
        OrderingGuarantee::PerDistinctId
    )]
    fn ordering_per_lane(#[case] stamps: Stamps, #[case] expected: OrderingGuarantee) {
        let ctx = test_utils::test_context();
        let mut ev = ok_wrapped("$pageview", "user-1");
        ev.destination = stamps.destination;
        ev.force_disable_person_processing = stamps.person_off;
        ev.spread_partitions = stamps.spread;

        assert_eq!(ev.ordering(), expected);
        // The header tracks the person-processing flag and nothing else, so
        // spreading a key never asks downstream to skip identity resolution.
        assert_eq!(
            ev.headers(&ctx).force_disable_person_processing,
            stamps.person_off.then_some(true),
            "the header must follow the person flag alone"
        );
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
            spread_partitions: false,
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
            spread_partitions: false,
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
            spread_partitions: false,
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
            spread_partitions: false,
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
            spread_partitions: false,
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
            spread_partitions: false,
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
            spread_partitions: false,
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
            spread_partitions: false,
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
            spread_partitions: false,
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
            spread_partitions: false,
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
