//! Analytics event payload handling
//!
//! This module contains the payload processing logic for analytics events.
//! It extracts and validates event payloads from HTTP requests, handling
//! decompression, deserialization, and token extraction.

use axum::body::Body;
use axum::extract::{MatchedPath, State};
use axum::http::{HeaderMap, Method};
use axum_client_ip::InsecureClientIp;
use common_types::RawEvent;
use metrics::counter;
use tracing::{instrument, Span};

use crate::{
    api::CaptureError,
    debug_or_info,
    extractors::extract_body_with_timeout,
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
        token,
        ip,
        historical_migration,
        compression,
        lib_version,
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
    body: Body,
) -> Result<(ProcessingContext, Vec<RawEvent>), CaptureError> {
    let chatty_debug_enabled = headers.get("X-CAPTURE-DEBUG").is_some();

    debug_or_info!(chatty_debug_enabled, headers=?headers, "entering handle_event_payload");

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

    // capture arguments and add to logger, processing context
    let metadata = extract_and_record_metadata(headers, path.as_str(), state.is_mirror_deploy);
    debug_or_info!(chatty_debug_enabled, metadata=?metadata, "extracted metadata");

    // Extract payload bytes and metadata using shared helper
    let (data, compression, lib_version) =
        extract_payload_bytes(query_params, headers, method, body)?;

    Span::current().record("compression", format!("{compression}"));
    Span::current().record("lib_version", &lib_version);

    debug_or_info!(chatty_debug_enabled, metadata=?metadata, "extracted payload");

    let request = RawRequest::from_bytes(
        data,
        compression,
        metadata.request_id,
        state.event_payload_size_limit,
        path.as_str().to_string(),
    )?;
    debug_or_info!(chatty_debug_enabled, metadata=?metadata, "parsed RawRequest");

    let sent_at = request.sent_at().or(query_params.sent_at());
    let historical_migration = request.historical_migration();
    Span::current().record("historical_migration", historical_migration);

    // if this was a batch request, retrieve this now for later validation
    let maybe_batch_token = request.get_batch_token();

    // consumes the parent request, so it's no longer in scope to extract metadata from
    let mut events = request.events(path.as_str())?;

    Span::current().record("batch_size", events.len());

    debug_or_info!(chatty_debug_enabled, metadata=?metadata, "extracted events from RawRequest");

    let token = match extract_and_verify_token(&events, maybe_batch_token) {
        Ok(token) => token,
        Err(err) => {
            return Err(err);
        }
    };
    Span::current().record("token", &token);

    counter!("capture_events_received_total").increment(events.len() as u64);

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
        chatty_debug_enabled,
    };
    debug_or_info!(chatty_debug_enabled, context=?context, event_count=?events.len(), "processing complete");

    // Apply global rate limit per team (API token) if enabled
    if let Some(global_rate_limiter) = &state.global_rate_limiter {
        if let Some(limited) = global_rate_limiter
            .is_limited(&context.token, events.len() as u64)
            .await
        {
            return Err(CaptureError::GlobalRateLimitExceeded(
                context.token.clone(),
                events.len() as u64,
                limited.window_start,
                limited.window_end,
                limited.threshold,
                limited.window_interval.as_secs(),
            ));
        }
        debug_or_info!(chatty_debug_enabled, context=?context, event_count=?events.len(), "global rate limit applied");
    }

    // Apply all billing limit quotas and drop partial or whole
    // payload if any are exceeded for this token (team)
    events = state
        .quota_limiter
        .check_and_filter(&context.token, events)
        .await?;
    debug_or_info!(chatty_debug_enabled, context=?context, event_count=?events.len(), "quota limits filter applied");

    Ok((context, events))
}
