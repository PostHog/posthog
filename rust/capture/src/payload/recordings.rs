//! Recording (session replay) payload handling
//!
//! This module contains optimized payload processing logic for recording events.
//! Unlike analytics events, recording payloads are deserialized directly to
//! Vec<RawRecording> to avoid the overhead of going through RawRequest.

use axum::body::Body;
use axum::extract::{MatchedPath, State};
use axum::http::{HeaderMap, Method};
use axum_client_ip::InsecureClientIp;
use metrics::counter;
use tracing::{instrument, warn, Span};

use crate::{
    api::CaptureError,
    debug_or_info,
    events::recordings::RawRecording,
    extractors::extract_body_with_timeout,
    payload::{decompress_payload, extract_and_record_metadata, extract_payload_bytes, EventQuery},
    router,
    v0_request::ProcessingContext,
};

/// Helper enum to deserialize either a single recording or an array
#[derive(Debug, serde::Deserialize)]
#[serde(untagged)]
enum RecordingPayload {
    Array(Vec<RawRecording>),
    One(Box<RawRecording>),
}

impl RecordingPayload {
    fn into_vec(self) -> Vec<RawRecording> {
        match self {
            RecordingPayload::Array(events) => events,
            RecordingPayload::One(event) => vec![*event],
        }
    }
}

/// handle_recording_payload processes recording (session replay) payloads
/// This is optimized to avoid the double serialization that would occur
/// if we went through RawRequest -> Vec<RawEvent> -> process
#[instrument(skip_all, fields(batch_size, params_lib_version, params_compression))]
pub async fn handle_recording_payload(
    state: &State<router::State>,
    InsecureClientIp(ip): &InsecureClientIp,
    query_params: &mut EventQuery,
    headers: &HeaderMap,
    method: &Method,
    path: &MatchedPath,
    body: Body,
) -> Result<(ProcessingContext, Vec<RawRecording>), CaptureError> {
    let chatty_debug_enabled = headers.get("X-CAPTURE-DEBUG").is_some();

    debug_or_info!(chatty_debug_enabled, headers=?headers, "entering handle_recording_payload");

    // Extract body with optional chunk timeout
    let body = extract_body_with_timeout(
        body,
        state.event_payload_size_limit,
        state.body_chunk_read_timeout,
        state.body_read_chunk_size_kb,
        path.as_str(),
    )
    .await?;

    debug_or_info!(chatty_debug_enabled, headers=?headers, "streamed payload body");

    // Extract request metadata using shared helper
    let metadata = extract_and_record_metadata(headers, path.as_str(), state.is_mirror_deploy);

    debug_or_info!(chatty_debug_enabled, metadata=?metadata, "extracted metadata");

    // Extract payload bytes and metadata using shared helper
    let (data, compression, lib_version) =
        extract_payload_bytes(query_params, headers, method, body)?;

    Span::current().record("compression", format!("{compression}"));
    Span::current().record("lib_version", &lib_version);

    debug_or_info!(chatty_debug_enabled, metadata=?metadata, compression=?compression, lib_version=?lib_version, "extracted payload");

    // Decompress the payload
    let payload = decompress_payload(
        data,
        compression,
        state.event_payload_size_limit,
        path.as_str(),
    )?;

    debug_or_info!(chatty_debug_enabled, metadata=?metadata, compression=?compression, lib_version=?lib_version, "decompressed payload");

    // Deserialize to RecordingPayload (handles both single event and array)
    let recording_payload: RecordingPayload = serde_json::from_str(&payload)?;
    let mut events = recording_payload.into_vec();

    debug_or_info!(chatty_debug_enabled, metadata=?metadata, event_count=?events.len(), "hydrated events");

    if events.is_empty() {
        warn!("rejected empty recording batch");
        return Err(CaptureError::EmptyBatch);
    }

    Span::current().record("batch_size", events.len());

    // Extract token from first event
    let token = events[0]
        .extract_token()
        .ok_or(CaptureError::NoTokenError)?;
    Span::current().record("token", &token);

    counter!("capture_events_received_total").increment(events.len() as u64);

    let now = state.timesource.current_time();
    let sent_at = query_params.sent_at();

    let context = ProcessingContext {
        lib_version,
        sent_at,
        token,
        now,
        client_ip: ip.to_string(),
        request_id: metadata.request_id.to_string(),
        path: path.as_str().to_string(),
        is_mirror_deploy: metadata.is_mirror_deploy,
        historical_migration: false, // recordings don't support historical migration
        user_agent: Some(metadata.user_agent.to_string()),
        chatty_debug_enabled,
    };

    // Apply all billing limit quotas and drop partial or whole
    // payload if any are exceeded for this token (team)
    debug_or_info!(chatty_debug_enabled, context=?context, event_count=?events.len(), "evaluating quota limits");
    events = state
        .quota_limiter
        .check_and_filter(&context.token, events)
        .await?;

    debug_or_info!(chatty_debug_enabled, context=?context, event_count=?events.len(), "processing complete");
    Ok((context, events))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_recording_payload_single_event() {
        let json = json!({
            "event": "$snapshot",
            "distinct_id": "user123",
            "properties": {
                "$session_id": "session-abc",
                "$snapshot_data": [{"type": 1}]
            }
        });

        let payload: RecordingPayload = serde_json::from_value(json).unwrap();
        let events = payload.into_vec();

        assert_eq!(events.len(), 1);
        assert_eq!(events[0].event, "$snapshot");
    }

    #[test]
    fn test_recording_payload_array_of_events() {
        let json = json!([
            {
                "event": "$snapshot",
                "distinct_id": "user123",
                "properties": {
                    "$session_id": "session-abc",
                    "$snapshot_data": [{"type": 1}]
                }
            },
            {
                "event": "$snapshot",
                "distinct_id": "user123",
                "properties": {
                    "$session_id": "session-abc",
                    "$snapshot_data": [{"type": 2}]
                }
            }
        ]);

        let payload: RecordingPayload = serde_json::from_value(json).unwrap();
        let events = payload.into_vec();

        assert_eq!(events.len(), 2);
        assert_eq!(events[0].event, "$snapshot");
        assert_eq!(events[1].event, "$snapshot");
    }

    #[test]
    fn test_recording_payload_into_vec_does_not_copy() {
        // This test verifies that into_vec() moves the data rather than copying
        let json = json!([
            {
                "event": "$snapshot",
                "distinct_id": "user123",
                "properties": {
                    "$session_id": "session-abc",
                    "$snapshot_data": [{"type": 1}]
                }
            }
        ]);

        let payload: RecordingPayload = serde_json::from_value(json).unwrap();
        let events = payload.into_vec();

        // If this compiles and runs, it proves into_vec() took ownership
        assert_eq!(events.len(), 1);
    }
}
