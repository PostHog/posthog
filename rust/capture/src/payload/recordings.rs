//! Recording (session replay) payload handling
//!
//! This module contains optimized payload processing logic for recording events.
//! Unlike analytics events, recording payloads are deserialized directly to
//! Vec<RawRecording> to avoid the overhead of going through RawRequest.

use axum::extract::{MatchedPath, State};
use axum::http::{HeaderMap, Method};
use axum_client_ip::InsecureClientIp;
use bytes::Bytes;
use metrics::counter;
use tracing::{debug, instrument, warn, Span};

use crate::{
    api::CaptureError,
    events::recordings::RawRecording,
    payload::{
        common::CAPTURE_OPERATION_TIMEOUT_TOTAL, decompress_payload, extract_and_record_metadata,
        extract_payload_bytes, EventQuery,
    },
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
    body: Bytes,
) -> Result<(ProcessingContext, Vec<RawRecording>), CaptureError> {
    // Extract request metadata using shared helper
    let metadata = extract_and_record_metadata(headers, path.as_str(), state.is_mirror_deploy);

    debug!("entering handle_recording_payload");

    // Extract payload bytes and metadata using shared helper
    // Capture fields before spawn_blocking consumes query_params:
    // - beacon: endpoint needs for response code (204 vs 200)
    // - sent_at: needed for ProcessingContext
    let beacon = query_params.beacon;
    let sent_at_from_query = query_params.sent_at();
    let mut query_params_owned = std::mem::take(query_params);
    let headers_clone = headers.clone();
    let method_clone = method.clone();
    let result = tokio::time::timeout(
        state.operation_timeout,
        tokio::task::spawn_blocking(move || {
            extract_payload_bytes(&mut query_params_owned, &headers_clone, &method_clone, body)
        }),
    )
    .await;
    let (data, compression, lib_version) = match result {
        Ok(Ok(Ok((d, c, lv)))) => (d, c, lv),
        Ok(Ok(Err(e))) => return Err(e),
        Ok(Err(_join_err)) => {
            return Err(CaptureError::RequestDecodingError("task panicked".into()))
        }
        Err(_) => {
            counter!(CAPTURE_OPERATION_TIMEOUT_TOTAL, "op" => "extract").increment(1);
            return Err(CaptureError::OperationTimeout);
        }
    };

    Span::current().record("compression", format!("{compression}"));
    Span::current().record("lib_version", &lib_version);

    debug!("payload processed: deserializing to RawRecording");

    // Decompress the payload
    let event_size_limit = state.event_size_limit;
    let path_owned = path.as_str().to_string();
    let result = tokio::time::timeout(
        state.operation_timeout,
        tokio::task::spawn_blocking(move || {
            decompress_payload(data, compression, event_size_limit, &path_owned)
        }),
    )
    .await;
    let payload = match result {
        Ok(Ok(Ok(payload))) => payload,
        Ok(Ok(Err(e))) => return Err(e),
        Ok(Err(_join_err)) => {
            return Err(CaptureError::RequestDecodingError("task panicked".into()))
        }
        Err(_) => {
            counter!(CAPTURE_OPERATION_TIMEOUT_TOTAL, "op" => "decompress").increment(1);
            return Err(CaptureError::OperationTimeout);
        }
    };

    // Deserialize to RecordingPayload (handles both single event and array)
    let result = tokio::time::timeout(
        state.operation_timeout,
        tokio::task::spawn_blocking(move || serde_json::from_str::<RecordingPayload>(&payload)),
    )
    .await;
    let recording_payload: RecordingPayload = match result {
        Ok(Ok(Ok(payload))) => payload,
        Ok(Ok(Err(e))) => return Err(e.into()),
        Ok(Err(_join_err)) => {
            return Err(CaptureError::RequestDecodingError("task panicked".into()))
        }
        Err(_) => {
            counter!(CAPTURE_OPERATION_TIMEOUT_TOTAL, "op" => "parse").increment(1);
            return Err(CaptureError::OperationTimeout);
        }
    };
    let mut events = recording_payload.into_vec();

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

    counter!(
        "capture_events_received_total",
        &[("legacy", "false"), ("endpoint", "recordings")]
    )
    .increment(events.len() as u64);

    let now = state.timesource.current_time();
    let sent_at = sent_at_from_query;

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
        beacon,
        user_agent: Some(metadata.user_agent.to_string()),
    };

    // Apply all billing limit quotas and drop partial or whole
    // payload if any are exceeded for this token (team)
    debug!(context=?context, event_count=?events.len(), "handle_recording_payload: evaluating quota limits");
    events = state
        .quota_limiter
        .check_and_filter(&context.token, events)
        .await?;

    debug!(context=?context,
        event_count=?events.len(),
        "handle_recording_payload: successfully hydrated recording events");

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
