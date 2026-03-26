use std::collections::HashMap;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::v1::sinks::Destination;

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
pub struct BatchMetadata {
    pub created_at: String,
    #[serde(default)]
    pub historical_migration: bool,
    #[serde(default)]
    pub capture_internal: bool,
}

#[derive(Debug, Deserialize)]
pub struct CaptureV1Batch {
    pub metadata: BatchMetadata,
    pub batch: Vec<CaptureV1Event>,
}

#[derive(Debug, Deserialize)]
pub struct CaptureV1Event {
    pub event: String,
    pub uuid: String,
    pub distinct_id: String,
    pub timestamp: String,
    #[serde(default)]
    pub properties: HashMap<String, Value>,
}

#[derive(Debug)]
pub struct WrappedEvent {
    pub event: CaptureV1Event,
    // Post-skew-adjustment timestamp for Kafka export, None if event is malformed
    pub adjusted_timestamp: Option<DateTime<Utc>>,
    pub ordinal: usize,
    pub result: EventResult,
    pub details: Option<&'static str>,
    pub destination: Destination,
    pub skip_person_processing: bool,
}

/// The Kafka-ready event produced by the v1 analytics pipeline.
/// Replaces legacy `CapturedEvent` from `common_types`.
///
/// Constructed from a valid `WrappedEvent` + request `Context` in a future
/// transformation step within `process_batch`, before being handed to a
/// `v1::Sink` for publishing. The sink should not perform any enrichment
/// or property inspection -- all transformations happen at construction time.
///
/// Property-level checks needed at construction time (from legacy parity):
/// - `properties.capture_internal`: if present, redact `ip` to "127.0.0.1"
/// - `properties.$cookieless_mode`: extract bool for Kafka partition key
///   selection (true -> partition by token:ip, false -> token:distinct_id).
///   Non-boolean values should be treated as a malformed event (status 400).
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
            "metadata": { "created_at": "2026-03-19T14:30:00.000Z" },
            "batch": [{
                "event": "$pageview",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "user-42",
                "timestamp": "2026-03-19T14:29:58.123Z"
            }]
        }"#;

        let batch: CaptureV1Batch = serde_json::from_str(json).unwrap();
        assert_eq!(batch.metadata.created_at, "2026-03-19T14:30:00.000Z");
        assert!(!batch.metadata.historical_migration);
        assert!(!batch.metadata.capture_internal);
        assert_eq!(batch.batch.len(), 1);

        let event = &batch.batch[0];
        assert_eq!(event.event, "$pageview");
        assert_eq!(event.uuid, "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d");
        assert_eq!(event.distinct_id, "user-42");
        assert_eq!(event.timestamp, "2026-03-19T14:29:58.123Z");
        assert!(event.properties.is_empty());
    }

    #[test]
    fn parse_batch_with_properties() {
        let json = r#"{
            "metadata": { "created_at": "2026-03-19T14:30:00.000Z" },
            "batch": [{
                "event": "$identify",
                "uuid": "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e",
                "distinct_id": "user-99",
                "timestamp": "2026-03-19T14:30:00.000Z",
                "properties": {
                    "$current_url": "https://example.com",
                    "$set": {"email": "test@example.com"},
                    "$set_once": {"created_at": "2026-01-01"},
                    "$groups": {"company": "posthog"},
                    "custom_prop": 42
                }
            }]
        }"#;

        let batch: CaptureV1Batch = serde_json::from_str(json).unwrap();
        let props = &batch.batch[0].properties;
        assert_eq!(props["$current_url"], "https://example.com");
        assert_eq!(props["custom_prop"], 42);
        assert!(props.contains_key("$set"));
        assert!(props.contains_key("$set_once"));
        assert!(props.contains_key("$groups"));
    }

    #[test]
    fn parse_batch_missing_created_at() {
        let json = r#"{
            "metadata": {},
            "batch": [{
                "event": "e",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "d",
                "timestamp": "2026-03-19T14:30:00.000Z"
            }]
        }"#;
        assert!(serde_json::from_str::<CaptureV1Batch>(json).is_err());
    }

    #[test]
    fn parse_batch_missing_batch_field() {
        let json = r#"{"metadata": {"created_at": "2026-03-19T14:30:00.000Z"}}"#;
        assert!(serde_json::from_str::<CaptureV1Batch>(json).is_err());
    }

    #[test]
    fn parse_event_missing_event_name() {
        let json = r#"{
            "metadata": { "created_at": "2026-03-19T14:30:00.000Z" },
            "batch": [{
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "d",
                "timestamp": "2026-03-19T14:30:00.000Z"
            }]
        }"#;
        assert!(serde_json::from_str::<CaptureV1Batch>(json).is_err());
    }

    #[test]
    fn parse_event_missing_uuid() {
        let json = r#"{
            "metadata": { "created_at": "2026-03-19T14:30:00.000Z" },
            "batch": [{
                "event": "e",
                "distinct_id": "d",
                "timestamp": "2026-03-19T14:30:00.000Z"
            }]
        }"#;
        assert!(serde_json::from_str::<CaptureV1Batch>(json).is_err());
    }

    #[test]
    fn parse_event_missing_distinct_id() {
        let json = r#"{
            "metadata": { "created_at": "2026-03-19T14:30:00.000Z" },
            "batch": [{
                "event": "e",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "timestamp": "2026-03-19T14:30:00.000Z"
            }]
        }"#;
        assert!(serde_json::from_str::<CaptureV1Batch>(json).is_err());
    }

    #[test]
    fn parse_event_missing_timestamp() {
        let json = r#"{
            "metadata": { "created_at": "2026-03-19T14:30:00.000Z" },
            "batch": [{
                "event": "e",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "d"
            }]
        }"#;
        assert!(serde_json::from_str::<CaptureV1Batch>(json).is_err());
    }

    #[test]
    fn parse_batch_empty_array() {
        let json = r#"{"metadata": {"created_at": "2026-03-19T14:30:00.000Z"}, "batch": []}"#;
        let batch: CaptureV1Batch = serde_json::from_str(json).unwrap();
        assert!(batch.batch.is_empty());
    }

    #[test]
    fn parse_batch_extra_fields_ignored() {
        let json = r#"{
            "metadata": { "created_at": "2026-03-19T14:30:00.000Z", "unknown_meta_field": 99 },
            "unknown_top_field": true,
            "batch": [{
                "event": "e",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "d",
                "timestamp": "2026-03-19T14:30:00.000Z",
                "unknown_event_field": "ignored"
            }]
        }"#;
        let batch: CaptureV1Batch = serde_json::from_str(json).unwrap();
        assert_eq!(batch.batch.len(), 1);
        assert_eq!(batch.batch[0].event, "e");
    }

    #[test]
    fn parse_batch_metadata_defaults() {
        let json = r#"{
            "metadata": { "created_at": "2026-03-19T14:30:00.000Z" },
            "batch": []
        }"#;
        let batch: CaptureV1Batch = serde_json::from_str(json).unwrap();
        assert_eq!(batch.metadata.created_at, "2026-03-19T14:30:00.000Z");
        assert!(!batch.metadata.historical_migration);
        assert!(!batch.metadata.capture_internal);
    }

    #[test]
    fn parse_batch_metadata_explicit_true() {
        let json = r#"{
            "metadata": {
                "created_at": "2026-03-19T14:30:00.000Z",
                "historical_migration": true,
                "capture_internal": true
            },
            "batch": []
        }"#;
        let batch: CaptureV1Batch = serde_json::from_str(json).unwrap();
        assert_eq!(batch.metadata.created_at, "2026-03-19T14:30:00.000Z");
        assert!(batch.metadata.historical_migration);
        assert!(batch.metadata.capture_internal);
    }

    #[test]
    fn parse_batch_missing_metadata() {
        let json = r#"{
            "batch": [{
                "event": "e",
                "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "distinct_id": "d",
                "timestamp": "2026-03-19T14:30:00.000Z"
            }]
        }"#;
        assert!(serde_json::from_str::<CaptureV1Batch>(json).is_err());
    }

    #[test]
    fn parse_invalid_json() {
        let garbage = b"this is not json at all {{{";
        assert!(serde_json::from_slice::<CaptureV1Batch>(garbage).is_err());
    }
}
