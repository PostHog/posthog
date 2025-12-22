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

use chrono::DateTime;
use common_types::{CapturedEvent, HasEventName};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tracing::{error, instrument, Span};
use uuid::Uuid;

use metrics::counter;

use crate::{
    api::CaptureError,
    debug_or_info,
    event_restrictions::{
        EventContext as RestrictionEventContext, EventRestrictionService, RestrictionType,
    },
    prometheus::report_dropped_events,
    sinks,
    utils::uuid_v7,
    v0_request::{DataType, ProcessedEvent, ProcessedEventMetadata, ProcessingContext},
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

    /// Recording-specific properties - only deserialize what we need
    #[serde(default)]
    pub properties: RecordingProperties,
}

/// Recording properties - only the fields we actually use
#[derive(Debug, Default, Deserialize, Serialize)]
pub struct RecordingProperties {
    #[serde(rename = "$session_id", skip_serializing_if = "Option::is_none")]
    pub session_id: Option<Value>,

    #[serde(rename = "$window_id", skip_serializing_if = "Option::is_none")]
    pub window_id: Option<Value>,

    #[serde(rename = "$snapshot_data", skip_serializing_if = "Option::is_none")]
    pub snapshot_data: Option<Value>,

    #[serde(rename = "$snapshot_source", skip_serializing_if = "Option::is_none")]
    pub snapshot_source: Option<Value>,

    #[serde(rename = "$lib", skip_serializing_if = "Option::is_none")]
    pub lib: Option<String>,

    #[serde(rename = "$cookieless_mode", skip_serializing_if = "Option::is_none")]
    pub cookieless_mode: Option<bool>,

    #[serde(rename = "$ignore_sent_at", skip_serializing_if = "Option::is_none")]
    pub ignore_sent_at: Option<bool>,

    /// Fallback for distinct_id if not at root level
    #[serde(skip_serializing_if = "Option::is_none")]
    pub distinct_id: Option<Value>,

    /// Fallback for token if not at root level
    #[serde(skip_serializing_if = "Option::is_none")]
    pub token: Option<String>,
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

impl RawRecording {
    /// Extract the distinct_id, checking both root field and properties
    pub fn extract_distinct_id(&self) -> Option<String> {
        let value = match &self.distinct_id {
            None | Some(Value::Null) => match &self.properties.distinct_id {
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
        self.token.clone().or_else(|| self.properties.token.clone())
    }

    /// Extract cookieless mode flag
    pub fn extract_is_cookieless_mode(&self) -> Option<bool> {
        match self.properties.cookieless_mode {
            Some(b) => Some(b),
            None => Some(false),
        }
    }
}

impl HasEventName for RawRecording {
    fn event_name(&self) -> &str {
        &self.event
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
    restriction_service: Option<EventRestrictionService>,
    events: Vec<RawRecording>,
    context: &'a ProcessingContext,
) -> Result<(), CaptureError> {
    let chatty_debug_enabled = context.chatty_debug_enabled;

    Span::current().record("request_id", &context.request_id);

    // Compute the actual event timestamp using our timestamp parsing logic from the first event
    let sent_at_utc = context.sent_at.map(|sa| {
        DateTime::from_timestamp(sa.unix_timestamp(), sa.nanosecond()).unwrap_or_default()
    });
    let ignore_sent_at = events[0].properties.ignore_sent_at.unwrap_or(false);

    let computed_timestamp = common_types::timestamp::parse_event_timestamp(
        events[0].timestamp.as_deref(),
        events[0].offset,
        sent_at_utc,
        ignore_sent_at,
        context.now,
    );

    // Extract metadata from first event by taking ownership (no clones!)
    // We split off the first event to extract metadata, then iterate over the rest
    let mut events_iter = events.into_iter();
    let mut first_event = events_iter.next().ok_or(CaptureError::EmptyBatch)?;

    let uuid = first_event.uuid.unwrap_or_else(uuid_v7);
    let distinct_id = first_event
        .extract_distinct_id()
        .ok_or(CaptureError::MissingDistinctId)?;
    let is_cookieless_mode = first_event
        .extract_is_cookieless_mode()
        .ok_or(CaptureError::InvalidCookielessMode)?;

    // Take metadata fields by ownership (no clone!)
    let session_id = first_event
        .properties
        .session_id
        .take()
        .ok_or(CaptureError::MissingSessionId)?;

    // Validate session_id
    let session_id_str = session_id.as_str().ok_or(CaptureError::InvalidSessionId)?;
    if session_id_str.len() > 70
        || !session_id_str
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-')
    {
        return Err(CaptureError::InvalidSessionId);
    }
    Span::current().record("session_id", session_id_str);

    // Apply event restrictions
    let mut force_overflow = false;
    let mut skip_person_processing = false;
    let mut redirect_to_dlq = false;

    if let Some(ref service) = restriction_service {
        let event_ctx = RestrictionEventContext {
            distinct_id: Some(distinct_id.clone()),
            session_id: Some(session_id_str.to_string()),
            event_name: Some("$snapshot_items".to_string()),
            event_uuid: Some(uuid.to_string()),
        };

        let restrictions = service.get_restrictions(&context.token, &event_ctx).await;

        if restrictions.contains(&RestrictionType::DropEvent) {
            counter!(
                "capture_event_restrictions_applied",
                "restriction_type" => "drop_event",
                "pipeline" => "session_recordings"
            )
            .increment(1);
            report_dropped_events("event_restriction_drop", 1);
            return Ok(());
        }

        if restrictions.contains(&RestrictionType::ForceOverflow) {
            counter!(
                "capture_event_restrictions_applied",
                "restriction_type" => "force_overflow",
                "pipeline" => "session_recordings"
            )
            .increment(1);
            force_overflow = true;
        }

        if restrictions.contains(&RestrictionType::SkipPersonProcessing) {
            counter!(
                "capture_event_restrictions_applied",
                "restriction_type" => "skip_person_processing",
                "pipeline" => "session_recordings"
            )
            .increment(1);
            skip_person_processing = true;
        }

        if restrictions.contains(&RestrictionType::RedirectToDlq) {
            counter!(
                "capture_event_restrictions_applied",
                "restriction_type" => "redirect_to_dlq",
                "pipeline" => "session_recordings"
            )
            .increment(1);
            redirect_to_dlq = true;
        }
    }

    let window_id = first_event
        .properties
        .window_id
        .take()
        .unwrap_or_else(|| session_id.clone());

    let default_snapshot_source = Value::String(String::from("web"));
    let snapshot_source = first_event
        .properties
        .snapshot_source
        .take()
        .unwrap_or(default_snapshot_source);

    let snapshot_library = first_event
        .properties
        .lib
        .take()
        .or_else(|| snapshot_library_fallback_from(context.user_agent.as_ref()))
        .unwrap_or_else(|| String::from("unknown"));

    // Collect snapshot items from all events by taking ownership (no clone!)
    // Start with the first event's snapshot data, then iterate over the rest
    let mut snapshot_items: Vec<Value> = Vec::new();

    // Process first event's snapshot_data
    let Some(snapshot_data) = first_event.properties.snapshot_data.take() else {
        return Err(CaptureError::MissingSnapshotData);
    };
    match snapshot_data {
        Value::Array(mut arr) => {
            snapshot_items.append(&mut arr);
        }
        Value::Object(obj) => {
            snapshot_items.push(Value::Object(obj));
        }
        _ => {
            return Err(CaptureError::MissingSnapshotData);
        }
    }

    // Process remaining events' snapshot_data
    for mut event in events_iter {
        let Some(snapshot_data) = event.properties.snapshot_data.take() else {
            return Err(CaptureError::MissingSnapshotData);
        };
        match snapshot_data {
            Value::Array(mut arr) => {
                snapshot_items.append(&mut arr);
            }
            Value::Object(obj) => {
                snapshot_items.push(Value::Object(obj));
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
        force_overflow,
        skip_person_processing,
        redirect_to_dlq,
    };

    // Serialize snapshot data synchronously
    // Benchmarks show that sync serialization performs better under high concurrency (50-100+ requests)
    // than offloading to spawn_blocking, which has significant overhead
    let serialized_data = serialize_snapshot_data_sync(
        &distinct_id,
        &session_id,
        &window_id,
        &snapshot_source,
        &snapshot_items,
        &snapshot_library,
    );

    debug_or_info!(chatty_debug_enabled, metadata=?metadata, context=?context, "serialized snapshot data");

    let event = CapturedEvent {
        uuid,
        distinct_id, // No clone - we own it from extract_distinct_id()
        session_id: Some(session_id_str.to_string()),
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

    sink.send(ProcessedEvent { metadata, event }).await?;

    debug_or_info!(chatty_debug_enabled, context=?context, "sent recordings CapturedEvent");

    Ok(())
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
            &distinct_id,
            &session_id,
            &window_id,
            &snapshot_source,
            &snapshot_items,
            &snapshot_library,
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
    distinct_id: &str,
    session_id: &Value,
    window_id: &Value,
    snapshot_source: &Value,
    snapshot_items: &Vec<Value>,
    snapshot_library: &String,
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
            recording.properties.session_id,
            Some(Value::String("session-abc".to_string()))
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

    // ============ Restriction tests ============

    use crate::api::CaptureError;
    use crate::event_restrictions::{
        EventRestrictionService, IngestionPipeline, Restriction, RestrictionManager,
        RestrictionScope,
    };
    use crate::sinks::Event;
    use crate::v0_request::ProcessedEvent;
    use async_trait::async_trait;
    use std::sync::{Arc, Mutex};
    use std::time::Duration;

    struct MockSink {
        events: Arc<Mutex<Vec<ProcessedEvent>>>,
    }

    #[async_trait]
    impl Event for MockSink {
        async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
            self.events.lock().unwrap().push(event);
            Ok(())
        }
        async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
            self.events.lock().unwrap().extend(events);
            Ok(())
        }
    }

    fn create_test_recording() -> RawRecording {
        let json = json!({
            "event": "$snapshot",
            "distinct_id": "test_user",
            "properties": {
                "$session_id": "test-session-123",
                "$window_id": "test-window",
                "$snapshot_data": [{"type": 1, "data": {"test": "data"}}],
                "$snapshot_source": "web"
            }
        });
        serde_json::from_value(json).unwrap()
    }

    fn create_test_context() -> crate::v0_request::ProcessingContext {
        crate::v0_request::ProcessingContext {
            request_id: "test-request".to_string(),
            client_ip: "127.0.0.1".to_string(),
            now: chrono::Utc::now(),
            sent_at: None,
            token: "test_token".to_string(),
            historical_migration: false,
            is_mirror_deploy: false,
            chatty_debug_enabled: false,
            user_agent: None,
            lib_version: None,
            path: "/s/".to_string(),
        }
    }

    #[tokio::test]
    async fn test_process_replay_events_drop_event_restriction() {
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
            events: events_captured.clone(),
        });

        let service = EventRestrictionService::new(
            IngestionPipeline::SessionRecordings,
            Duration::from_secs(300),
        );

        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
            }],
        );
        service.update(manager).await;

        let recording = create_test_recording();
        let context = create_test_context();

        let result = process_replay_events(sink, Some(service), vec![recording], &context).await;

        assert!(result.is_ok());
        assert!(events_captured.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn test_process_replay_events_redirect_to_dlq_restriction() {
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
            events: events_captured.clone(),
        });

        let service = EventRestrictionService::new(
            IngestionPipeline::SessionRecordings,
            Duration::from_secs(300),
        );

        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
            vec![Restriction {
                restriction_type: RestrictionType::RedirectToDlq,
                scope: RestrictionScope::AllEvents,
            }],
        );
        service.update(manager).await;

        let recording = create_test_recording();
        let context = create_test_context();

        let result = process_replay_events(sink, Some(service), vec![recording], &context).await;

        assert!(result.is_ok());
        let captured = events_captured.lock().unwrap();
        assert_eq!(captured.len(), 1);
        assert!(captured[0].metadata.redirect_to_dlq);
    }

    #[tokio::test]
    async fn test_process_replay_events_force_overflow_restriction() {
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
            events: events_captured.clone(),
        });

        let service = EventRestrictionService::new(
            IngestionPipeline::SessionRecordings,
            Duration::from_secs(300),
        );

        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
            vec![Restriction {
                restriction_type: RestrictionType::ForceOverflow,
                scope: RestrictionScope::AllEvents,
            }],
        );
        service.update(manager).await;

        let recording = create_test_recording();
        let context = create_test_context();

        let result = process_replay_events(sink, Some(service), vec![recording], &context).await;

        assert!(result.is_ok());
        let captured = events_captured.lock().unwrap();
        assert_eq!(captured.len(), 1);
        assert!(captured[0].metadata.force_overflow);
    }

    #[tokio::test]
    async fn test_process_replay_events_skip_person_processing_restriction() {
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
            events: events_captured.clone(),
        });

        let service = EventRestrictionService::new(
            IngestionPipeline::SessionRecordings,
            Duration::from_secs(300),
        );

        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "test_token".to_string(),
            vec![Restriction {
                restriction_type: RestrictionType::SkipPersonProcessing,
                scope: RestrictionScope::AllEvents,
            }],
        );
        service.update(manager).await;

        let recording = create_test_recording();
        let context = create_test_context();

        let result = process_replay_events(sink, Some(service), vec![recording], &context).await;

        assert!(result.is_ok());
        let captured = events_captured.lock().unwrap();
        assert_eq!(captured.len(), 1);
        assert!(captured[0].metadata.skip_person_processing);
    }

    #[tokio::test]
    async fn test_process_replay_events_no_restriction_service() {
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
            events: events_captured.clone(),
        });

        let recording = create_test_recording();
        let context = create_test_context();

        let result = process_replay_events(sink, None, vec![recording], &context).await;

        assert!(result.is_ok());
        let captured = events_captured.lock().unwrap();
        assert_eq!(captured.len(), 1);
        assert!(!captured[0].metadata.force_overflow);
        assert!(!captured[0].metadata.skip_person_processing);
        assert!(!captured[0].metadata.redirect_to_dlq);
    }

    #[tokio::test]
    async fn test_process_replay_events_filtered_restriction() {
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
            events: events_captured.clone(),
        });

        let service = EventRestrictionService::new(
            IngestionPipeline::SessionRecordings,
            Duration::from_secs(300),
        );

        // Create a restriction that only applies to a different session
        let mut manager = RestrictionManager::new();
        let mut filters = crate::event_restrictions::RestrictionFilters::default();
        filters.session_ids.insert("other-session".to_string());
        manager.restrictions.insert(
            "test_token".to_string(),
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::Filtered(filters),
            }],
        );
        service.update(manager).await;

        let recording = create_test_recording(); // has session_id "test-session-123"
        let context = create_test_context();

        let result = process_replay_events(sink, Some(service), vec![recording], &context).await;

        // Should NOT be dropped because session_id doesn't match filter
        assert!(result.is_ok());
        let captured = events_captured.lock().unwrap();
        assert_eq!(captured.len(), 1);
    }
}
