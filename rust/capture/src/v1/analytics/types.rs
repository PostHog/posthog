use chrono::{DateTime, Utc};
use common_types::HasEventName;
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;

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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub capture_internal: Option<bool>,
    pub batch: Vec<Event>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Options {
    #[serde(rename = "$cookieless_mode", skip_serializing_if = "Option::is_none")]
    pub cookieless_mode: Option<bool>,
    #[serde(
        rename = "$ignore_attempt_timestamp",
        skip_serializing_if = "Option::is_none"
    )]
    pub ignore_attempt_timestamp: Option<bool>,
    #[serde(rename = "$product_tour_id", skip_serializing_if = "Option::is_none")]
    pub product_tour_id: Option<String>,
    #[serde(
        rename = "$process_person_profile",
        skip_serializing_if = "Option::is_none"
    )]
    pub process_person_profile: Option<bool>,
}

#[derive(Debug, Deserialize)]
pub struct Event {
    pub event: String,
    pub uuid: String,
    pub distinct_id: String,
    pub timestamp: String,
    #[serde(rename = "$session_id", skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
    #[serde(rename = "$window_id", skip_serializing_if = "Option::is_none")]
    pub window_id: Option<String>,
    pub options: Options,
    #[serde(default = "empty_raw_object")]
    pub properties: Box<RawValue>,
}

#[derive(Debug)]
pub struct WrappedEvent {
    pub event: Event,
    // Post-skew-adjustment timestamp for Kafka export, None if event is malformed
    pub adjusted_timestamp: Option<DateTime<Utc>>,
    pub ordinal: usize,
    pub result: EventResult,
    pub details: Option<String>,
    pub destination: Destination,
    pub skip_person_processing: bool,
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
            "$product_tour_id" => self.event.options.product_tour_id.is_some(),
            _ => false,
        }
    }
}

/// The Kafka-ready event produced by the v1 analytics pipeline.
/// Replaces legacy `CapturedEvent` from `common_types`.
///
/// Constructed from a valid `WrappedEvent` + request `Context` in a future
/// transformation step within `process_batch`, before being handed to a
/// `v1::Sink` for publishing. The sink should not perform any enrichment
/// or property inspection -- all transformations happen at construction time.
///
/// Checks needed at construction time (from legacy parity):
/// - `Context.capture_internal`: if true, redact `ip` to "127.0.0.1"
/// - `Options.cookieless_mode`: controls Kafka partition key selection
///   (true -> partition by token:ip, false -> token:distinct_id).
///   Non-boolean values are rejected at deserialization by serde.
///
/// Will implement the upcoming `v1::Sink` trait to abstract serialization
/// and partition key derivation.
#[derive(Debug, Serialize)]
pub struct IngestionEvent {
    pub uuid: String,
    pub distinct_id: String,
    pub ip: String,
    pub event: String,
    pub timestamp: DateTime<Utc>,
    pub token: String,
    pub is_cookieless_mode: bool,
    pub data: String,
    pub now: String,
    #[serde(skip)]
    pub destination: Destination,
    #[serde(skip)]
    pub skip_person_processing: bool,
    /// Maps back to the originating WrappedEvent in the batch for result tracking.
    #[serde(skip)]
    pub ordinal: usize,
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
                "$session_id": "sess-abc",
                "$window_id": "win-xyz",
                "options": {
                    "$cookieless_mode": true,
                    "$ignore_attempt_timestamp": true,
                    "$product_tour_id": "tour-123",
                    "$process_person_profile": false
                }
            }]
        }"#;
        let batch: Batch = serde_json::from_str(json).unwrap();
        let event = &batch.batch[0];
        assert_eq!(event.session_id.as_deref(), Some("sess-abc"));
        assert_eq!(event.window_id.as_deref(), Some("win-xyz"));
        assert_eq!(event.options.cookieless_mode, Some(true));
        assert_eq!(event.options.ignore_attempt_timestamp, Some(true));
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
        assert_eq!(event.options.ignore_attempt_timestamp, None);
        assert_eq!(event.options.product_tour_id, None);
        assert_eq!(event.options.process_person_profile, None);
    }

    #[test]
    fn parse_invalid_json() {
        let garbage = b"this is not json at all {{{";
        assert!(serde_json::from_slice::<Batch>(garbage).is_err());
    }
}
