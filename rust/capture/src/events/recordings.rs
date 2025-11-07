//! Recording-specific request parsing and processing
//!
//! This module contains optimized deserialization and processing for recording (session replay) events.
//! Unlike regular events, recordings contain large snapshot data that doesn't need
//! to be fully deserialized into intermediate structs - we can extract metadata and
//! keep snapshot data as raw JSON values for direct serialization.
//!
//! Key optimization: We avoid double serialization by:
//! 1. Extracting only the metadata fields we need (session_id, window_id, etc.)
//! 2. Keeping snapshot_data as serde_json::Value (already parsed)
//! 3. Serializing directly to the final CapturedEvent format without intermediate steps

use std::sync::Arc;

use bytes::Bytes;
use chrono::DateTime;
use common_types::CapturedEvent;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use tracing::{error, instrument, Span};
use uuid::Uuid;

use crate::api::CaptureError;
use crate::payload::Compression;
use crate::sinks;
use crate::utils::uuid_v7;
use crate::v0_request::{
    DataType, ProcessedEvent, ProcessedEventMetadata, ProcessingContext, RawRequest,
};

/// A recording event optimized for minimal deserialization overhead.
/// Instead of fully parsing all properties into a HashMap, we only extract
/// the fields we need and keep snapshot data as serde_json::Value for direct
/// pass-through serialization.
#[derive(Debug, Deserialize, Serialize)]
pub struct RawRecording {
    /// Event UUID (optional, will be generated if missing)
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub uuid: Option<Uuid>,

    /// Event name (should be "$snapshot" for recordings)
    pub event: String,

    /// Distinct ID from root or properties
    #[serde(alias = "$distinct_id", skip_serializing_if = "Option::is_none")]
    pub distinct_id: Option<Value>,

    /// Token from root or properties
    #[serde(
        alias = "$token",
        alias = "api_key",
        skip_serializing_if = "Option::is_none"
    )]
    pub token: Option<String>,

    /// Event timestamp
    #[serde(skip_serializing_if = "Option::is_none")]
    pub timestamp: Option<String>,

    /// Timezone offset
    #[serde(skip_serializing_if = "Option::is_none")]
    pub offset: Option<i64>,

    /// All event properties - we'll extract session_id, window_id, snapshot_data from here
    #[serde(default)]
    pub properties: HashMap<String, Value>,
}

/// Container for multiple recording events in a single request
#[derive(Debug, Deserialize)]
#[serde(untagged)]
pub enum RecordingRequest {
    /// Array of recording events (most common for recordings)
    Array(Vec<RawRecording>),
    /// Single recording event
    One(Box<RawRecording>),
}

impl RecordingRequest {
    /// Parse compressed/encoded bytes directly into RawRecording structs
    /// This bypasses the RawEvent deserialization used by regular events
    pub fn from_bytes(
        bytes: Bytes,
        compression: Compression,
        request_id: &str,
        limit: usize,
    ) -> Result<Vec<RawRecording>, CaptureError> {
        // Reuse the decompression logic from RawRequest but deserialize to RecordingRequest
        // We need to do the same decompression/decoding steps
        let raw_request = RawRequest::from_bytes(
            bytes,
            compression,
            request_id,
            limit,
            "/s/".to_string(), // Recording path
        )?;

        // Convert RawRequest to RecordingRequest
        // For now, we'll still go through RawRequest for decompression,
        // but we can optimize this further later
        let events = raw_request.events("/s/")?;

        // Convert RawEvent to RawRecording
        // TODO: fix this by deserializing directly to RawRecording
        // This is temporary - ideally we'd deserialize directly to RawRecording
        Ok(events
            .into_iter()
            .map(|event| RawRecording {
                uuid: event.uuid,
                event: event.event,
                distinct_id: event.distinct_id,
                token: event.token,
                timestamp: event.timestamp,
                offset: event.offset,
                properties: event.properties,
            })
            .collect())
    }
}

impl RawRecording {
    /// Extract the distinct_id, checking both root field and properties
    pub fn extract_distinct_id(&self) -> Option<String> {
        let value = match &self.distinct_id {
            None | Some(Value::Null) => match self.properties.get("distinct_id") {
                None | Some(Value::Null) => return None,
                Some(id) => id,
            },
            Some(id) => id,
        };

        let distinct_id = value
            .as_str()
            .map(|s| s.to_owned())
            .unwrap_or_else(|| value.to_string());

        let distinct_id = distinct_id.replace('\0', "\u{FFFD}");

        match distinct_id.len() {
            0 => None,
            1..=200 => Some(distinct_id),
            _ => Some(distinct_id.chars().take(200).collect()),
        }
    }

    /// Extract token from root field or properties
    pub fn extract_token(&self) -> Option<String> {
        match &self.token {
            Some(value) => Some(value.clone()),
            None => self
                .properties
                .get("token")
                .and_then(Value::as_str)
                .map(String::from),
        }
    }

    /// Extract cookieless mode flag
    pub fn extract_is_cookieless_mode(&self) -> Option<bool> {
        match self.properties.get("$cookieless_mode") {
            Some(Value::Bool(b)) => Some(*b),
            Some(_) => None,
            None => Some(false),
        }
    }
}

/// Process recording (session replay) events with optimized serialization
///
/// This function is optimized to avoid double serialization of snapshot data:
/// - Extract metadata fields (session_id, window_id, etc.)
/// - Keep snapshot_data as Value (already parsed from JSON)
/// - Serialize directly to final format using serde::Serialize
///
#[instrument(skip_all, fields(events = events.len(), session_id, request_id))]
pub async fn process_replay_events<'a>(
    sink: Arc<dyn sinks::Event + Send + Sync>,
    mut events: Vec<RawRecording>,
    context: &'a ProcessingContext,
) -> Result<(), CaptureError> {
    Span::current().record("request_id", &context.request_id);

    // Compute the actual event timestamp using our timestamp parsing logic from the first event
    let sent_at_utc = context.sent_at.map(|sa| {
        DateTime::from_timestamp(sa.unix_timestamp(), sa.nanosecond()).unwrap_or_default()
    });
    let ignore_sent_at = events[0]
        .properties
        .get("$ignore_sent_at")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    let computed_timestamp = common_types::timestamp::parse_event_timestamp(
        events[0].timestamp.as_deref(),
        events[0].offset,
        sent_at_utc,
        ignore_sent_at,
        context.now,
    );

    // Grab metadata about the whole batch from the first event before
    // we drop all the events as we rip out the snapshot data
    let session_id = events[0]
        .properties
        .remove("$session_id")
        .ok_or(CaptureError::MissingSessionId)?;
    // Validate session_id is a valid UUID
    let session_id_str = session_id.as_str().ok_or(CaptureError::InvalidSessionId)?;

    // Reject session_ids that are too long, or that contains non-alphanumeric characters
    if session_id_str.len() > 70
        || !session_id_str
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-')
    {
        return Err(CaptureError::InvalidSessionId);
    }
    Span::current().record("session_id", session_id_str);

    let window_id = events[0]
        .properties
        .remove("$window_id")
        .unwrap_or(session_id.clone());
    let uuid = events[0].uuid.unwrap_or_else(uuid_v7);
    let distinct_id = events[0]
        .extract_distinct_id()
        .ok_or(CaptureError::MissingDistinctId)?;
    let snapshot_source = events[0]
        .properties
        .remove("$snapshot_source")
        .unwrap_or(Value::String(String::from("web")));
    let is_cookieless_mode = events[0]
        .extract_is_cookieless_mode()
        .ok_or(CaptureError::InvalidCookielessMode)?;
    let snapshot_library = events[0]
        .properties
        .remove("$lib")
        .and_then(|v| v.as_str().map(|v| v.to_string()))
        .or_else(|| snapshot_library_fallback_from(context.user_agent.as_ref()))
        .unwrap_or_else(|| String::from("unknown"));

    let mut snapshot_items: Vec<Value> = Vec::with_capacity(events.len());
    for mut event in events {
        let Some(snapshot_data) = event.properties.remove("$snapshot_data") else {
            return Err(CaptureError::MissingSnapshotData);
        };
        match snapshot_data {
            Value::Array(value) => {
                snapshot_items.extend(value);
            }
            Value::Object(value) => {
                snapshot_items.push(Value::Object(value));
            }
            _ => {
                return Err(CaptureError::MissingSnapshotData);
            }
        }
    }

    let metadata = ProcessedEventMetadata {
        data_type: DataType::SnapshotMain,
        session_id: Some(session_id_str.to_string()),
        computed_timestamp: Some(computed_timestamp),
        event_name: "$snapshot_items".to_string(),
    };

    // Serialize snapshot data on blocking thread pool to avoid blocking executor
    let serialized_data = serialize_snapshot_data_async(
        distinct_id.clone(),
        session_id.clone(),
        window_id.clone(),
        snapshot_source.clone(),
        snapshot_items,
        snapshot_library.clone(),
    )
    .await?;

    let event = CapturedEvent {
        uuid,
        distinct_id: distinct_id.clone(),
        ip: context.client_ip.clone(),
        data: serialized_data,
        now: context
            .now
            .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true),
        sent_at: context.sent_at,
        token: context.token.clone(),
        event: "$snapshot_items".to_string(),
        timestamp: computed_timestamp,
        is_cookieless_mode,
        historical_migration: context.historical_migration,
    };

    sink.send(ProcessedEvent { metadata, event }).await
}

/// Asynchronously serialize snapshot data by offloading to blocking thread pool
/// This prevents blocking the async executor with CPU-intensive JSON serialization
pub async fn serialize_snapshot_data_async(
    distinct_id: String,
    session_id: Value,
    window_id: Value,
    snapshot_source: Value,
    snapshot_items: Vec<Value>,
    snapshot_library: String,
) -> Result<String, CaptureError> {
    tokio::task::spawn_blocking(move || {
        serialize_snapshot_data_sync(
            distinct_id,
            session_id,
            window_id,
            snapshot_source,
            snapshot_items,
            snapshot_library,
        )
    })
    .await
    .map_err(|e| {
        error!(
            "failed to spawn blocking task for snapshot serialization: {}",
            e
        );
        CaptureError::NonRetryableSinkError
    })
}

/// Synchronously serialize snapshot data to JSON string
/// This function is CPU-intensive and should be called from a blocking thread pool
pub fn serialize_snapshot_data_sync(
    distinct_id: String,
    session_id: Value,
    window_id: Value,
    snapshot_source: Value,
    snapshot_items: Vec<Value>,
    snapshot_library: String,
) -> String {
    json!({
        "event": "$snapshot_items",
        "properties": {
            "distinct_id": distinct_id,
            "$session_id": session_id,
            "$window_id": window_id,
            "$snapshot_source": snapshot_source,
            "$snapshot_items": snapshot_items,
            "$lib": snapshot_library,
        }
    })
    .to_string()
}

fn snapshot_library_fallback_from(user_agent: Option<&String>) -> Option<String> {
    user_agent?
        .split('/')
        .next()
        .map(|s| s.to_string())
        .filter(|s| s.contains("posthog"))
        .or(Some("web".to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_raw_recording_deserialization() {
        let json = json!({
            "event": "$snapshot",
            "distinct_id": "user123",
            "properties": {
                "$session_id": "session-abc",
                "$window_id": "window-xyz",
                "$snapshot_data": [{"type": 1, "data": {}}],
                "$snapshot_source": "web"
            }
        });

        let recording: RawRecording = serde_json::from_value(json).unwrap();
        assert_eq!(recording.event, "$snapshot");
        assert_eq!(recording.extract_distinct_id(), Some("user123".to_string()));
        assert_eq!(
            recording.properties.get("$session_id"),
            Some(&Value::String("session-abc".to_string()))
        );
    }

    #[test]
    fn test_extract_distinct_id_from_properties() {
        let json = json!({
            "event": "$snapshot",
            "properties": {
                "distinct_id": "user456",
                "$session_id": "session-def"
            }
        });

        let recording: RawRecording = serde_json::from_value(json).unwrap();
        assert_eq!(recording.extract_distinct_id(), Some("user456".to_string()));
    }

    #[test]
    fn test_extract_token() {
        let json = json!({
            "event": "$snapshot",
            "token": "my-token",
            "properties": {}
        });

        let recording: RawRecording = serde_json::from_value(json).unwrap();
        assert_eq!(recording.extract_token(), Some("my-token".to_string()));
    }

    #[test]
    fn test_extract_cookieless_mode() {
        let json = json!({
            "event": "$snapshot",
            "properties": {
                "$cookieless_mode": true
            }
        });

        let recording: RawRecording = serde_json::from_value(json).unwrap();
        assert_eq!(recording.extract_is_cookieless_mode(), Some(true));
    }
}
