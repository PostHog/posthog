//! Analytics event payload handling
//!
//! This module contains the payload processing logic for analytics events.
//! It extracts and validates event payloads from HTTP requests, handling
//! decompression, deserialization, and token extraction.

use axum::extract::{MatchedPath, State};
use axum::http::{HeaderMap, Method};
use axum_client_ip::InsecureClientIp;
use bytes::Bytes;
use common_types::RawEvent;
use metrics::counter;
use tracing::{debug, instrument, Span};

use crate::{
    api::CaptureError,
    payload::{extract_and_record_metadata, extract_payload_bytes, EventQuery},
    router,
    utils::extract_and_verify_token,
    v0_request::{ProcessingContext, RawRequest},
};

/// handle_event_payload owns processing of request payloads for the
/// /i/v0/e/, /batch/, /e/, /capture/, /track/, and /engage/ endpoints
#[instrument(
    skip_all,
    fields(
        method,
        path,
        user_agent,
        content_type,
        content_encoding,
        x_request_id,
        token,
        historical_migration,
        lib_version,
        compression,
        params_lib_version,
        params_compression,
        batch_size
    )
)]
pub async fn handle_event_payload(
    state: &State<router::State>,
    InsecureClientIp(ip): &InsecureClientIp,
    query_params: &mut EventQuery,
    headers: &HeaderMap,
    method: &Method,
    path: &MatchedPath,
    body: Bytes,
) -> Result<(ProcessingContext, Vec<RawEvent>), CaptureError> {
    // this endpoint handles:
    // - GET or POST requests w/payload that is one of:
    //   1. possibly base64-wrapped, possibly GZIP or LZ64 compressed JSON payload
    //   2. possibly base64-wrapped, urlencoded form where "data" is the key for JSON payload
    //
    // When POST body isn't the payload, the POST form fields or
    // GET query params should contain the following:
    //     - data        = JSON payload which may itself be compressed or base64 encoded or both
    //     - compression = hint to how "data" is encoded or compressed
    //     - lib_version = SDK version that submitted the request

    // capture arguments and add to logger, processing context
    let metadata = extract_and_record_metadata(headers, path.as_str(), state.is_mirror_deploy);

    debug!("entering handle_event_payload");

    // Extract payload bytes and metadata using shared helper
    let extract_start_time = std::time::Instant::now();
    let result = extract_payload_bytes(query_params, headers, method, body);
    let (data, compression, lib_version) = match result {
        Ok((d, c, lv)) => (d, c, lv),
        Err(e) => {
            return Err(e);
        }
    };
    metrics::histogram!("capture_debug_analytics_extract_seconds")
        .record(extract_start_time.elapsed().as_secs_f64());

    Span::current().record("compression", format!("{compression}"));
    Span::current().record("lib_version", &lib_version);

    debug!("payload processed: passing to RawRequest::from_bytes");

    let from_bytes_start_time = std::time::Instant::now();
    let result = RawRequest::from_bytes(
        data,
        compression,
        metadata.request_id,
        state.event_size_limit,
        path.as_str().to_string(),
    );
    let request = match result {
        Ok(request) => request,
        Err(e) => {
            return Err(e);
        }
    };
    metrics::histogram!("capture_debug_analytics_decompress_seconds")
        .record(from_bytes_start_time.elapsed().as_secs_f64());

    let sent_at = request.sent_at().or(query_params.sent_at());
    let historical_migration = request.historical_migration();
    Span::current().record("historical_migration", historical_migration);

    // if this was a batch request, retrieve this now for later validation
    let maybe_batch_token = request.get_batch_token();

    // consumes the parent request, so it's no longer in scope to extract metadata from
    let events_start_time = std::time::Instant::now();
    let result = request.events(path.as_str());
    let mut events = match result {
        Ok(events) => events,
        Err(e) => return Err(e),
    };
    metrics::histogram!("capture_debug_analytics_deserialize_seconds")
        .record(events_start_time.elapsed().as_secs_f64());

    Span::current().record("batch_size", events.len());

    let token = match extract_and_verify_token(&events, maybe_batch_token) {
        Ok(token) => token,
        Err(err) => {
            return Err(err);
        }
    };
    Span::current().record("token", &token);

    counter!("capture_events_received_total", &[("legacy", "true")]).increment(events.len() as u64);

    let now = state.timesource.current_time();

    let context = ProcessingContext {
        lib_version,
        sent_at,
        token,
        now,
        client_ip: ip.to_string(),
        request_id: metadata.request_id.to_string(),
        path: path.as_str().to_string(),
        is_mirror_deploy: metadata.is_mirror_deploy,
        historical_migration,
        user_agent: Some(metadata.user_agent.to_string()),
    };

    // Apply all billing limit quotas and drop partial or whole
    // payload if any are exceeded for this token (team)
    debug!(context=?context, event_count=?events.len(), "handle_event_payload: evaluating quota limits");
    events = state
        .quota_limiter
        .check_and_filter(&context.token, events)
        .await?;

    debug!(context=?context,
        event_count=?events.len(),
        "handle_event_payload: successfully hydrated events");
    Ok((context, events))
}
