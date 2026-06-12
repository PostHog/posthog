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
use limiters::redis::RedisLimiter;
use metrics::{counter, histogram};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::time::Instant;
use tracing::{error, instrument, Span};
use uuid::Uuid;

use crate::{
    api::CaptureError,
    debug_or_info,
    event_restrictions::{
        AppliedRestrictions, EventContext as RestrictionEventContext, EventRestrictionService,
        Pipeline,
    },
    prometheus::report_dropped_events,
    sinks,
    utils::uuid_v7,
    v0_request::{
        DataType, OverflowReason, ProcessedEvent, ProcessedEventMetadata, ProcessingContext,
    },
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

/// Process recording (session replay) events with optimized serialization.
///
/// This function is optimized to avoid double serialization of snapshot data:
/// - Extract metadata fields (session_id, window_id, etc.)
/// - Keep snapshot_data as Value (already parsed from JSON)
/// - Serialize directly to final format using serde::Serialize
///
/// Routing policy (event restrictions + replay overflow) is decided here and
/// stamped onto `ProcessedEventMetadata`. The kafka sink is a pure mechanism
/// layer — it reads `overflow_reason`, `force_overflow`, `redirect_to_dlq`,
/// and `redirect_to_topic` from the metadata and picks the topic/key
/// accordingly. `replay_overflow_limiter` is the redis-backed limiter keyed
/// on session_id that signals rerouting to the replay overflow topic.
///
#[instrument(skip_all, fields(events = events.len(), session_id, request_id))]
pub async fn process_replay_events(
    sink: Arc<dyn sinks::Event + Send + Sync>,
    restriction_service: Option<EventRestrictionService>,
    replay_overflow_limiter: Option<Arc<RedisLimiter>>,
    events: Vec<RawRecording>,
    context: &ProcessingContext,
) -> Result<(), CaptureError> {
    let chatty_debug_enabled = context.chatty_debug_enabled;

    Span::current().record("request_id", &context.request_id);

    // Compute the actual event timestamp using our timestamp parsing logic from the first event
    let sent_at_utc = context.sent_at.map(|sa| {
        DateTime::from_timestamp(sa.unix_timestamp(), sa.nanosecond()).unwrap_or_default()
    });
    let ignore_sent_at = events[0].properties.ignore_sent_at.unwrap_or(false);

    let parsed = common_types::timestamp::parse_event_timestamp(
        events[0].timestamp.as_deref(),
        events[0].offset,
        sent_at_utc,
        ignore_sent_at,
        context.now,
    );
    let computed_timestamp = parsed.timestamp;

    // Extract metadata from first event by taking ownership (no clones!)
    // We split off the first event to extract metadata, then iterate over the rest
    let mut events_iter = events.into_iter();
    let mut first_event = events_iter.next().ok_or(CaptureError::EmptyBatch)?;

    let uuid = first_event.uuid.unwrap_or_else(uuid_v7);
    let Some(distinct_id) = first_event.extract_distinct_id() else {
        return Err(reject_replay_batch(
            &sink,
            context,
            CaptureError::MissingDistinctId,
            "missing_distinct_id",
            None,
            None,
            computed_timestamp,
        )
        .await);
    };
    // no warning here: extract_is_cookieless_mode never returns None
    let is_cookieless_mode = first_event
        .extract_is_cookieless_mode()
        .ok_or(CaptureError::InvalidCookielessMode)?;

    // Take metadata fields by ownership (no clone!)
    let Some(session_id) = first_event.properties.session_id.take() else {
        return Err(reject_replay_batch(
            &sink,
            context,
            CaptureError::MissingSessionId,
            "missing_session_id",
            None,
            Some(&distinct_id),
            computed_timestamp,
        )
        .await);
    };

    // Validate session_id
    let session_id_valid = session_id
        .as_str()
        .is_some_and(|s| s.len() <= 70 && s.chars().all(|c| c.is_ascii_alphanumeric() || c == '-'));
    if !session_id_valid {
        // include the malformed value so teams can spot integration bugs
        let raw_session_id: String = session_id
            .as_str()
            .map(|s| s.to_string())
            .unwrap_or_else(|| session_id.to_string())
            .chars()
            .take(100)
            .collect();
        return Err(reject_replay_batch(
            &sink,
            context,
            CaptureError::InvalidSessionId,
            "invalid_session_id",
            Some(&raw_session_id),
            Some(&distinct_id),
            computed_timestamp,
        )
        .await);
    }
    let session_id_str = session_id
        .as_str()
        .expect("session_id validated as string above");
    Span::current().record("session_id", session_id_str);

    // Apply event restrictions
    let applied = if let Some(ref service) = restriction_service {
        let uuid_str = uuid.to_string();
        let event_ctx = RestrictionEventContext {
            distinct_id: Some(&distinct_id),
            session_id: Some(session_id_str),
            event_name: Some("$snapshot_items"),
            event_uuid: Some(&uuid_str),
            now_ts: context.now.timestamp(),
        };

        let applied = service
            .get_restrictions(&context.token, &event_ctx, Pipeline::SessionRecordings)
            .await;

        if applied.should_drop() {
            report_dropped_events("event_restriction_drop", 1);
            return Ok(());
        }

        applied
    } else {
        AppliedRestrictions::default()
    };

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

    // Process first event's snapshot_data, then the remaining events'
    let first_snapshot_data = first_event.properties.snapshot_data.take();
    for snapshot_data in std::iter::once(first_snapshot_data)
        .chain(events_iter.map(|mut event| event.properties.snapshot_data.take()))
    {
        match snapshot_data {
            Some(Value::Array(mut arr)) => {
                snapshot_items.append(&mut arr);
            }
            Some(Value::Object(obj)) => {
                snapshot_items.push(Value::Object(obj));
            }
            _ => {
                return Err(reject_replay_batch(
                    &sink,
                    context,
                    CaptureError::MissingSnapshotData,
                    "missing_snapshot_data",
                    Some(session_id_str),
                    Some(&distinct_id),
                    computed_timestamp,
                )
                .await);
            }
        }
    }

    // Replay overflow routing stage. This used to live in the kafka sink;
    // moving it here keeps the sink as a mechanism-only layer. `force_overflow`
    // short-circuits the limiter check (same semantics as the old sink path).
    // We preserve the old `capture_events_rerouted_overflow{reason=...}`
    // counter labels so existing dashboards keep working, and add a new
    // `capture_pipeline_replay_overflow_check_duration_seconds` histogram
    // around the redis call to make the added pipeline stage observable.
    let force_overflow = applied.force_overflow();
    let overflow_reason = if force_overflow {
        counter!(
            "capture_events_rerouted_overflow",
            "reason" => "event_restriction",
        )
        .increment(1);
        // The sink sees `force_overflow = true` and routes; no overflow_reason
        // needed in that case (None leaves room for `force_overflow` to drive
        // the sink's routing switch without double-stamping).
        None
    } else if let Some(ref limiter) = replay_overflow_limiter {
        let started = Instant::now();
        let is_overflowing = limiter.is_limited(session_id_str).await;
        histogram!("capture_pipeline_replay_overflow_check_duration_seconds")
            .record(started.elapsed().as_secs_f64());

        if is_overflowing {
            Some(OverflowReason::ReplayLimited)
        } else {
            None
        }
    } else {
        None
    };

    let metadata = ProcessedEventMetadata {
        data_type: DataType::SnapshotMain,
        session_id: Some(session_id_str.to_string()),
        computed_timestamp: Some(computed_timestamp),
        event_name: "$snapshot_items".to_string(),
        force_overflow,
        skip_person_processing: applied.skip_person_processing(),
        redirect_to_dlq: applied.redirect_to_dlq(),
        redirect_to_topic: applied.redirect_to_topic().map(|s| s.to_string()),
        skip_heatmap_processing: false,
        overflow_reason,
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

    let snapshot_items_count = snapshot_items.len();
    let snapshot_bytes = serialized_data.len();

    let event = CapturedEvent {
        uuid,
        // cloned (~200 bytes max) so the EventTooBig branch below can still build the warning
        distinct_id: distinct_id.clone(),
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

    match sink.send(ProcessedEvent { metadata, event }).await {
        Ok(()) => {}
        Err(err @ CaptureError::EventTooBig(_)) => {
            // surface a team-visible warning (best effort) before failing with 413
            counter!("capture_replay_snapshot_too_large_total").increment(1);
            let warning = replay_message_too_large_warning(
                context,
                distinct_id,
                session_id_str,
                computed_timestamp,
                snapshot_bytes,
                snapshot_items_count,
                &snapshot_library,
            );
            if let Err(warning_err) = sink.send(warning).await {
                error!(
                    "failed to send replay_message_too_large ingestion warning: {warning_err:?}"
                );
            }
            return Err(err);
        }
        Err(err) => return Err(err),
    }

    debug_or_info!(chatty_debug_enabled, context=?context, "sent recordings CapturedEvent");

    Ok(())
}

/// Warning for a snapshot batch dropped for size, persisted as a `replay_message_too_large` warning.
fn replay_message_too_large_warning(
    context: &ProcessingContext,
    distinct_id: String,
    session_id: &str,
    timestamp: chrono::DateTime<chrono::Utc>,
    snapshot_bytes: usize,
    snapshot_items_count: usize,
    snapshot_library: &str,
) -> ProcessedEvent {
    let message = format!(
        "Replay data for session {session_id} was dropped because it was too large to ingest ({snapshot_bytes} bytes, {snapshot_items_count} snapshot items)"
    );
    let details = json!({
        "timestamp": timestamp.to_rfc3339(),
        "replayRecord": { "session_id": session_id },
        "snapshotBytes": snapshot_bytes,
        "snapshotItemsCount": snapshot_items_count,
        "lib": bounded_warning_lib(snapshot_library),
    });
    client_ingestion_warning_event(
        context,
        distinct_id,
        Some(session_id),
        timestamp,
        "replay_message_too_large",
        message,
        details,
    )
}

/// Flag the rejected payload with a `replay_message_invalid` warning (best
/// effort, since the SDK drops the 400 silently), then hand back the error.
#[allow(clippy::too_many_arguments)]
async fn reject_replay_batch(
    sink: &Arc<dyn sinks::Event + Send + Sync>,
    context: &ProcessingContext,
    err: CaptureError,
    reason: &'static str,
    session_id: Option<&str>,
    distinct_id: Option<&str>,
    timestamp: chrono::DateTime<chrono::Utc>,
) -> CaptureError {
    counter!("capture_replay_message_invalid_total", "reason" => reason).increment(1);
    let message = format!("Replay data was rejected at capture: {reason}");
    let details = json!({
        "reason": reason,
        "sessionId": session_id,
    });
    let warning = client_ingestion_warning_event(
        context,
        distinct_id.unwrap_or("unknown").to_string(),
        None,
        timestamp,
        "replay_message_invalid",
        message,
        details,
    );
    if let Err(warning_err) = sink.send(warning).await {
        error!("failed to send replay_message_invalid ingestion warning: {warning_err:?}");
    }
    err
}

/// Build a `$$client_ingestion_warning` event. Ingestion resolves the team
/// from the token and persists it as an ingestion warning of `warning_type`.
fn client_ingestion_warning_event(
    context: &ProcessingContext,
    distinct_id: String,
    session_id: Option<&str>,
    timestamp: chrono::DateTime<chrono::Utc>,
    warning_type: &str,
    message: String,
    details: Value,
) -> ProcessedEvent {
    let data = json!({
        "event": "$$client_ingestion_warning",
        "distinct_id": &distinct_id,
        "properties": {
            "$$client_ingestion_warning_message": message,
            "$$client_ingestion_warning_type": warning_type,
            "$$client_ingestion_warning_details": details,
            "$session_id": session_id,
        }
    })
    .to_string();

    ProcessedEvent {
        metadata: ProcessedEventMetadata {
            data_type: DataType::ClientIngestionWarning,
            session_id: session_id.map(|s| s.to_string()),
            computed_timestamp: Some(timestamp),
            event_name: "$$client_ingestion_warning".to_string(),
            force_overflow: false,
            skip_person_processing: false,
            redirect_to_dlq: false,
            redirect_to_topic: None,
            skip_heatmap_processing: false,
            overflow_reason: None,
        },
        event: CapturedEvent {
            uuid: uuid_v7(),
            distinct_id,
            session_id: session_id.map(|s| s.to_string()),
            ip: context.client_ip.clone(),
            data,
            now: context
                .now
                .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true),
            sent_at: context.sent_at,
            token: context.token.clone(),
            event: "$$client_ingestion_warning".to_string(),
            timestamp,
            // synthetic event without the properties cookieless hashing needs
            is_cookieless_mode: false,
            historical_migration: false,
        },
    }
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
        error!("failed to spawn blocking task for snapshot serialization: {e:#}");
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

/// Cap the client-supplied `$lib` so an oversized value can't make the warning event itself too large.
fn bounded_warning_lib(snapshot_library: &str) -> String {
    const MAX_WARNING_LIB_CHARS: usize = 200;
    snapshot_library
        .chars()
        .take(MAX_WARNING_LIB_CHARS)
        .collect()
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
    use crate::event_restrictions::RestrictionType;
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

    use crate::event_restrictions::Pipeline;
    use crate::event_restrictions::{
        EventRestrictionService, Restriction, RestrictionManager, RestrictionScope,
    };
    use crate::sinks::test_sink::MockSink;
    use crate::sinks::Event;
    use common_redis::MockRedisClient;
    use limiters::redis::{QuotaResource, ServiceName, OVERFLOW_LIMITER_CACHE_KEY};
    use std::sync::{Arc, Mutex};
    use std::time::Duration;

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
            vec![Pipeline::SessionRecordings],
            Duration::from_secs(300),
        );

        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::SessionRecordings,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        let recording = create_test_recording();
        let context = create_test_context();

        let result =
            process_replay_events(sink, Some(service), None, vec![recording], &context).await;

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
            vec![Pipeline::SessionRecordings],
            Duration::from_secs(300),
        );

        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::SessionRecordings,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::RedirectToDlq,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        let recording = create_test_recording();
        let context = create_test_context();

        let result =
            process_replay_events(sink, Some(service), None, vec![recording], &context).await;

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
            vec![Pipeline::SessionRecordings],
            Duration::from_secs(300),
        );

        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::SessionRecordings,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::ForceOverflow,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        let recording = create_test_recording();
        let context = create_test_context();

        let result =
            process_replay_events(sink, Some(service), None, vec![recording], &context).await;

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
            vec![Pipeline::SessionRecordings],
            Duration::from_secs(300),
        );

        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::SessionRecordings,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::SkipPersonProcessing,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        let recording = create_test_recording();
        let context = create_test_context();

        let result =
            process_replay_events(sink, Some(service), None, vec![recording], &context).await;

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

        let result = process_replay_events(sink, None, None, vec![recording], &context).await;

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
            vec![Pipeline::SessionRecordings],
            Duration::from_secs(300),
        );

        // Create a restriction that only applies to a different session
        let mut manager = RestrictionManager::new();
        let mut filters = crate::event_restrictions::RestrictionFilters::default();
        filters.session_ids.insert("other-session".to_string());
        manager.insert_restrictions(
            Pipeline::SessionRecordings,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::Filtered(filters),
                args: None,
            }],
        );
        service.update(manager).await;

        let recording = create_test_recording(); // has session_id "test-session-123"
        let context = create_test_context();

        let result =
            process_replay_events(sink, Some(service), None, vec![recording], &context).await;

        // Should NOT be dropped because session_id doesn't match filter
        assert!(result.is_ok());
        let captured = events_captured.lock().unwrap();
        assert_eq!(captured.len(), 1);
    }

    // ============ replay overflow stamping tests ============
    // Exercise the pipeline's new replay overflow stamping stage
    // (moved here from the kafka sink's prepare_record). The limiter is
    // backed by a MockRedisClient primed with a specific session id.

    async fn build_replay_limiter(limited_session_ids: Vec<String>) -> Arc<RedisLimiter> {
        let client = Arc::new(
            MockRedisClient::new()
                .zrangebyscore_ret("@posthog/capture-overflow/replay", limited_session_ids),
        );
        let limiter = RedisLimiter::new(
            Duration::from_secs(1),
            client,
            OVERFLOW_LIMITER_CACHE_KEY.to_string(),
            None,
            QuotaResource::Replay,
            ServiceName::Capture,
        )
        .expect("failed to build test replay limiter");
        // The limiter polls redis on a background interval; give the first
        // tick a moment to populate the in-memory `limited` DashMap before
        // any is_limited call.
        tokio::time::sleep(Duration::from_millis(30)).await;
        Arc::new(limiter)
    }

    #[tokio::test]
    async fn test_replay_overflow_stamp_none_when_limiter_absent() {
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
            events: events_captured.clone(),
        });

        let recording = create_test_recording();
        let context = create_test_context();

        let result = process_replay_events(sink, None, None, vec![recording], &context).await;
        assert!(result.is_ok());

        let captured = events_captured.lock().unwrap();
        assert_eq!(captured.len(), 1);
        assert_eq!(captured[0].metadata.overflow_reason, None);
    }

    #[tokio::test]
    async fn test_replay_overflow_stamp_replay_limited_for_matching_session() {
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
            events: events_captured.clone(),
        });

        let limiter = build_replay_limiter(vec!["test-session-123".to_string()]).await;
        let recording = create_test_recording(); // session_id = "test-session-123"
        let context = create_test_context();

        let result =
            process_replay_events(sink, None, Some(limiter), vec![recording], &context).await;
        assert!(result.is_ok());

        let captured = events_captured.lock().unwrap();
        assert_eq!(captured.len(), 1);
        assert_eq!(
            captured[0].metadata.overflow_reason,
            Some(OverflowReason::ReplayLimited)
        );
    }

    #[tokio::test]
    async fn test_replay_overflow_stamp_none_for_unlimited_session() {
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
            events: events_captured.clone(),
        });

        let limiter = build_replay_limiter(vec!["some-other-session".to_string()]).await;
        let recording = create_test_recording();
        let context = create_test_context();

        let result =
            process_replay_events(sink, None, Some(limiter), vec![recording], &context).await;
        assert!(result.is_ok());

        let captured = events_captured.lock().unwrap();
        assert_eq!(captured.len(), 1);
        assert_eq!(captured[0].metadata.overflow_reason, None);
    }

    #[tokio::test]
    async fn test_replay_overflow_force_overflow_short_circuits_limiter() {
        // When event restrictions set force_overflow on a session, the pipeline
        // must leave overflow_reason = None so the sink routes on force_overflow
        // directly (matching the old sink precedence).
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
            events: events_captured.clone(),
        });

        let service = EventRestrictionService::new(
            vec![Pipeline::SessionRecordings],
            Duration::from_secs(300),
        );
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::SessionRecordings,
            "test_token",
            vec![Restriction {
                restriction_type: RestrictionType::ForceOverflow,
                scope: RestrictionScope::AllEvents,
                args: None,
            }],
        );
        service.update(manager).await;

        // Even though the session is in the limited set, force_overflow wins.
        let limiter = build_replay_limiter(vec!["test-session-123".to_string()]).await;
        let recording = create_test_recording();
        let context = create_test_context();

        let result = process_replay_events(
            sink,
            Some(service),
            Some(limiter),
            vec![recording],
            &context,
        )
        .await;
        assert!(result.is_ok());

        let captured = events_captured.lock().unwrap();
        assert_eq!(captured.len(), 1);
        assert!(captured[0].metadata.force_overflow);
        assert_eq!(captured[0].metadata.overflow_reason, None);
    }

    #[tokio::test]
    async fn test_replay_overflow_multiple_snapshots_share_batch_decision() {
        // process_replay_events folds all RawRecording items in a batch into a
        // single ProcessedEvent keyed on session_id, so overflow applies
        // uniformly to the batch. This guards against a regression where a
        // per-item check might diverge from batch-level routing.
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
            events: events_captured.clone(),
        });

        let limiter = build_replay_limiter(vec!["test-session-123".to_string()]).await;
        let recordings = vec![create_test_recording(), create_test_recording()];
        let context = create_test_context();

        let result = process_replay_events(sink, None, Some(limiter), recordings, &context).await;
        assert!(result.is_ok());

        let captured = events_captured.lock().unwrap();
        assert_eq!(
            captured.len(),
            1,
            "batch of snapshots must collapse to a single CapturedEvent"
        );
        assert_eq!(
            captured[0].metadata.overflow_reason,
            Some(OverflowReason::ReplayLimited)
        );
    }

    // ============ replay overflow histogram tests ============
    // The pipeline records `capture_pipeline_replay_overflow_check_duration_seconds`
    // around the redis `is_limited` call. These tests pin the contract that it
    // fires exactly once per call when the limiter branch runs, and NOT at all
    // when `force_overflow` short-circuits the limiter check.

    /// Snapshot of histogram metric names present after running the provided
    /// future inside a local DebuggingRecorder scope. Uses a current-thread
    /// runtime so the thread-local recorder guard stays visible across awaits.
    async fn run_with_metric_capture<F, Fut, T>(f: F) -> (Vec<String>, T)
    where
        F: FnOnce() -> Fut,
        Fut: std::future::Future<Output = T>,
    {
        use metrics_util::debugging::{DebugValue, DebuggingRecorder};

        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);

        let result = f().await;

        // Collect every histogram metric name that received at least one sample.
        let hist_names: Vec<String> = snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .filter_map(|(key, _, _, value)| match value {
                DebugValue::Histogram(samples) if !samples.is_empty() => {
                    Some(key.key().name().to_string())
                }
                _ => None,
            })
            .collect();

        (hist_names, result)
    }

    #[tokio::test(flavor = "current_thread")]
    async fn test_replay_overflow_histogram_recorded_when_limited() {
        let (histograms, _) = run_with_metric_capture(|| async {
            let events_captured = Arc::new(Mutex::new(Vec::new()));
            let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
                events: events_captured,
            });
            let limiter = build_replay_limiter(vec!["test-session-123".to_string()]).await;
            let recording = create_test_recording();
            let context = create_test_context();
            process_replay_events(sink, None, Some(limiter), vec![recording], &context)
                .await
                .unwrap();
        })
        .await;

        assert!(
            histograms
                .iter()
                .any(|n| n == "capture_pipeline_replay_overflow_check_duration_seconds"),
            "histogram must fire when limiter is present and session is limited; got {histograms:?}"
        );
    }

    #[tokio::test(flavor = "current_thread")]
    async fn test_replay_overflow_histogram_recorded_when_not_limited() {
        let (histograms, _) = run_with_metric_capture(|| async {
            let events_captured = Arc::new(Mutex::new(Vec::new()));
            let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
                events: events_captured,
            });
            // Session NOT in the limited set -> limiter returns false, but
            // the histogram must still record the call duration.
            let limiter = build_replay_limiter(vec!["some-other-session".to_string()]).await;
            let recording = create_test_recording();
            let context = create_test_context();
            process_replay_events(sink, None, Some(limiter), vec![recording], &context)
                .await
                .unwrap();
        })
        .await;

        assert!(
            histograms
                .iter()
                .any(|n| n == "capture_pipeline_replay_overflow_check_duration_seconds"),
            "histogram must fire regardless of limiter result; got {histograms:?}"
        );
    }

    #[tokio::test(flavor = "current_thread")]
    async fn test_replay_overflow_histogram_not_recorded_on_force_overflow() {
        let (histograms, _) = run_with_metric_capture(|| async {
            let events_captured = Arc::new(Mutex::new(Vec::new()));
            let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
                events: events_captured,
            });

            // force_overflow short-circuits the limiter branch; the pipeline
            // must skip the redis call AND the histogram record.
            let service = EventRestrictionService::new(
                vec![Pipeline::SessionRecordings],
                Duration::from_secs(300),
            );
            let mut manager = RestrictionManager::new();
            manager.insert_restrictions(
                Pipeline::SessionRecordings,
                "test_token",
                vec![Restriction {
                    restriction_type: RestrictionType::ForceOverflow,
                    scope: RestrictionScope::AllEvents,
                    args: None,
                }],
            );
            service.update(manager).await;

            let limiter = build_replay_limiter(vec!["test-session-123".to_string()]).await;
            let recording = create_test_recording();
            let context = create_test_context();
            process_replay_events(
                sink,
                Some(service),
                Some(limiter),
                vec![recording],
                &context,
            )
            .await
            .unwrap();
        })
        .await;

        assert!(
            !histograms
                .iter()
                .any(|n| n == "capture_pipeline_replay_overflow_check_duration_seconds"),
            "histogram must NOT fire when force_overflow short-circuits limiter; got {histograms:?}"
        );
    }

    #[tokio::test(flavor = "current_thread")]
    async fn test_replay_overflow_histogram_not_recorded_when_limiter_absent() {
        let (histograms, _) = run_with_metric_capture(|| async {
            let events_captured = Arc::new(Mutex::new(Vec::new()));
            let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
                events: events_captured,
            });
            let recording = create_test_recording();
            let context = create_test_context();
            process_replay_events(sink, None, None, vec![recording], &context)
                .await
                .unwrap();
        })
        .await;

        assert!(
            !histograms
                .iter()
                .any(|n| n == "capture_pipeline_replay_overflow_check_duration_seconds"),
            "histogram must NOT fire when limiter is absent; got {histograms:?}"
        );
    }

    // ============ end-to-end pipeline -> real KafkaSinkBase tests ============
    // Pins the pipeline-to-sink contract for replay overflow routing: the
    // pipeline stamps `overflow_reason = ReplayLimited`; the sink reads the
    // metadata and produces to `replay_overflow_topic` with the session_id
    // as partition key.

    use crate::sinks::kafka::{test_topics, KafkaSinkBase};
    use crate::sinks::producer::MockKafkaProducer;

    #[tokio::test]
    async fn e2e_replay_limited_pipeline_to_sink_routes_to_replay_overflow_with_session_key() {
        let producer = MockKafkaProducer::new();
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(KafkaSinkBase::with_producer(
            producer.clone(),
            test_topics(),
        ));

        let limiter = build_replay_limiter(vec!["test-session-123".to_string()]).await;
        let recording = create_test_recording(); // session_id = "test-session-123"
        let context = create_test_context();

        process_replay_events(sink, None, Some(limiter), vec![recording], &context)
            .await
            .unwrap();

        let records = producer.get_records();
        assert_eq!(records.len(), 1);
        assert_eq!(
            records[0].topic, "replay_overflow",
            "ReplayLimited must route to replay_overflow topic"
        );
        assert_eq!(
            records[0].key.as_deref(),
            Some("test-session-123"),
            "replay overflow keeps session_id partition key"
        );
    }

    // ============ oversized snapshot flagging tests ============

    use async_trait::async_trait;

    /// Rejects snapshot sends with the given error, accepts everything else.
    struct RejectSnapshotsSink {
        error: fn() -> CaptureError,
        events: Arc<Mutex<Vec<ProcessedEvent>>>,
    }

    #[async_trait]
    impl Event for RejectSnapshotsSink {
        async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
            if event.metadata.data_type == DataType::SnapshotMain {
                return Err((self.error)());
            }
            self.events.lock().unwrap().push(event);
            Ok(())
        }

        async fn send_batch(&self, _events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
            unreachable!("replay pipeline sends single events")
        }
    }

    #[tokio::test]
    async fn test_oversized_snapshot_emits_replay_message_too_large_warning() {
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(RejectSnapshotsSink {
            error: || CaptureError::EventTooBig("too big".to_string()),
            events: events_captured.clone(),
        });

        let recording = create_test_recording();
        let context = create_test_context();

        let result = process_replay_events(sink, None, None, vec![recording], &context).await;
        assert!(
            matches!(result, Err(CaptureError::EventTooBig(_))),
            "the request must still fail with EventTooBig, got {result:?}"
        );

        let captured = events_captured.lock().unwrap();
        assert_eq!(captured.len(), 1, "exactly one warning event must be sent");

        let warning = &captured[0];
        assert_eq!(warning.metadata.data_type, DataType::ClientIngestionWarning);
        assert_eq!(warning.event.event, "$$client_ingestion_warning");
        assert_eq!(warning.event.token, "test_token");
        assert_eq!(
            warning.event.session_id.as_deref(),
            Some("test-session-123")
        );
        assert_eq!(warning.event.distinct_id, "test_user");

        let data: Value = serde_json::from_str(&warning.event.data).unwrap();
        assert_eq!(data["event"], "$$client_ingestion_warning");
        let props = &data["properties"];
        assert_eq!(
            props["$$client_ingestion_warning_type"],
            "replay_message_too_large"
        );
        assert_eq!(
            props["$$client_ingestion_warning_details"]["replayRecord"]["session_id"],
            "test-session-123"
        );
        assert_eq!(
            props["$$client_ingestion_warning_details"]["snapshotItemsCount"],
            1
        );
        assert!(props["$$client_ingestion_warning_details"]["snapshotBytes"]
            .as_u64()
            .is_some_and(|b| b > 0));
        assert!(props["$$client_ingestion_warning_message"]
            .as_str()
            .is_some_and(|m| m.contains("test-session-123")));
    }

    // ============ rejected payload flagging tests ============

    async fn run_rejected_payload_case(
        recording_json: Value,
    ) -> (Result<(), CaptureError>, Vec<ProcessedEvent>) {
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
            events: events_captured.clone(),
        });
        let recording: RawRecording = serde_json::from_value(recording_json).unwrap();
        let context = create_test_context();
        let result = process_replay_events(sink, None, None, vec![recording], &context).await;
        let captured = events_captured.lock().unwrap().clone();
        (result, captured)
    }

    fn assert_invalid_warning(captured: &[ProcessedEvent], reason: &str) -> Value {
        assert_eq!(captured.len(), 1, "exactly one warning event must be sent");
        let warning = &captured[0];
        assert_eq!(warning.metadata.data_type, DataType::ClientIngestionWarning);
        let data: Value = serde_json::from_str(&warning.event.data).unwrap();
        let props = data["properties"].clone();
        assert_eq!(
            props["$$client_ingestion_warning_type"],
            "replay_message_invalid"
        );
        assert_eq!(
            props["$$client_ingestion_warning_details"]["reason"],
            reason
        );
        props
    }

    #[tokio::test]
    async fn test_missing_session_id_emits_invalid_warning() {
        let (result, captured) = run_rejected_payload_case(json!({
            "event": "$snapshot",
            "distinct_id": "test_user",
            "properties": { "$snapshot_data": [{"type": 1}] }
        }))
        .await;

        assert!(matches!(result, Err(CaptureError::MissingSessionId)));
        assert_invalid_warning(&captured, "missing_session_id");
    }

    #[tokio::test]
    async fn test_invalid_session_id_emits_warning_with_offending_value() {
        let (result, captured) = run_rejected_payload_case(json!({
            "event": "$snapshot",
            "distinct_id": "test_user",
            "properties": {
                "$session_id": "not!a!valid!session!id",
                "$snapshot_data": [{"type": 1}]
            }
        }))
        .await;

        assert!(matches!(result, Err(CaptureError::InvalidSessionId)));
        let props = assert_invalid_warning(&captured, "invalid_session_id");
        assert_eq!(
            props["$$client_ingestion_warning_details"]["sessionId"],
            "not!a!valid!session!id"
        );
    }

    #[tokio::test]
    async fn test_missing_snapshot_data_emits_invalid_warning() {
        let (result, captured) = run_rejected_payload_case(json!({
            "event": "$snapshot",
            "distinct_id": "test_user",
            "properties": { "$session_id": "test-session-123" }
        }))
        .await;

        assert!(matches!(result, Err(CaptureError::MissingSnapshotData)));
        let props = assert_invalid_warning(&captured, "missing_snapshot_data");
        assert_eq!(
            props["$$client_ingestion_warning_details"]["sessionId"],
            "test-session-123"
        );
    }

    #[tokio::test]
    async fn test_missing_distinct_id_emits_invalid_warning_with_fallback_id() {
        let (result, captured) = run_rejected_payload_case(json!({
            "event": "$snapshot",
            "properties": {
                "$session_id": "test-session-123",
                "$snapshot_data": [{"type": 1}]
            }
        }))
        .await;

        assert!(matches!(result, Err(CaptureError::MissingDistinctId)));
        assert_invalid_warning(&captured, "missing_distinct_id");
        assert_eq!(captured[0].event.distinct_id, "unknown");
    }

    #[tokio::test]
    async fn test_valid_payload_emits_no_invalid_warning() {
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(MockSink {
            events: events_captured.clone(),
        });
        let context = create_test_context();

        let result =
            process_replay_events(sink, None, None, vec![create_test_recording()], &context).await;

        assert!(result.is_ok());
        let captured = events_captured.lock().unwrap();
        assert_eq!(captured.len(), 1);
        assert_eq!(captured[0].metadata.data_type, DataType::SnapshotMain);
    }

    #[tokio::test]
    async fn test_oversized_snapshot_warning_caps_client_lib() {
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(RejectSnapshotsSink {
            error: || CaptureError::EventTooBig("too big".to_string()),
            events: events_captured.clone(),
        });

        let huge_lib = "x".repeat(5000);
        let recording: RawRecording = serde_json::from_value(json!({
            "event": "$snapshot",
            "distinct_id": "test_user",
            "properties": {
                "$session_id": "test-session-123",
                "$window_id": "test-window",
                "$snapshot_data": [{"type": 1, "data": {"test": "data"}}],
                "$snapshot_source": "web",
                "$lib": huge_lib,
            }
        }))
        .unwrap();
        let context = create_test_context();

        let result = process_replay_events(sink, None, None, vec![recording], &context).await;
        assert!(matches!(result, Err(CaptureError::EventTooBig(_))));

        let captured = events_captured.lock().unwrap();
        assert_eq!(captured.len(), 1);
        let data: Value = serde_json::from_str(&captured[0].event.data).unwrap();
        let props = &data["properties"];
        assert_eq!(
            props["$$client_ingestion_warning_details"]["lib"]
                .as_str()
                .map(|s| s.chars().count()),
            Some(200),
            "client lib must be capped in the warning details"
        );
    }

    #[tokio::test]
    async fn test_other_sink_errors_do_not_emit_warning() {
        let events_captured = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn Event + Send + Sync> = Arc::new(RejectSnapshotsSink {
            error: || CaptureError::RetryableSinkError,
            events: events_captured.clone(),
        });

        let recording = create_test_recording();
        let context = create_test_context();

        let result = process_replay_events(sink, None, None, vec![recording], &context).await;
        assert!(matches!(result, Err(CaptureError::RetryableSinkError)));
        assert!(
            events_captured.lock().unwrap().is_empty(),
            "only EventTooBig should produce a warning"
        );
    }
}
