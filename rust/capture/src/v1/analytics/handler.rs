use axum::body::Body;
use axum::extract::{MatchedPath, Query as AxumQuery, State};
use axum::http::{header, HeaderMap, Method};
use axum_client_ip::InsecureClientIp;

use super::constants::*;
use super::query::Query;
use super::response::Response;
use super::types::Batch;
use tracing::Level;

use crate::global_rate_limiter::GlobalRateLimitKey;
use crate::v1::constants::*;
use crate::v1::context::Context;
use crate::{ctx_log, log_stat_error, router, v1};

pub async fn handle_request(
    state: State<router::State>,
    headers: HeaderMap,
    query: AxumQuery<Query>,
    ip: InsecureClientIp,
    method: Method,
    path: MatchedPath,
    body: Body,
) -> Result<Response, v1::Error> {
    let mut context = Context::new(&headers, &ip, &query, method.clone(), path.as_str())
        .map_err(|err| log_and_return_header_error(err, &headers, &ip, &query, &method, &path))?;

    // TODO: purposely chatty, for now
    ctx_log!(Level::INFO, context, "handle_request called");

    let raw_bytes = v1::util::extract_body_with_timeout(
        body,
        CAPTURE_V1_MAX_COMPRESSED_BODY_BYTES,
        state.body_chunk_read_timeout,
        state.body_read_chunk_size_kb,
        &context.path,
    )
    .await
    .map_err(|err| {
        log_stat_error!(err, &context);
        err
    })?;

    let payload = v1::util::decompress_payload(
        context.content_encoding.as_deref(),
        raw_bytes,
        state.event_payload_size_limit,
        state.body_read_chunk_size_kb,
    )
    .await
    .map_err(|err| {
        log_stat_error!(err, &context);
        err
    })?;

    let batch: Batch = serde_json::from_slice(&payload).map_err(|e| {
        let err = v1::Error::RequestParsingError(e.to_string());
        log_stat_error!(err, &context);
        err
    })?;

    if let Some(ref limiter) = state.global_rate_limiter_token {
        check_token_rate_limit(limiter, &context, batch.batch.len() as u64).await?;
    }

    match super::process::process_batch(&state, &mut context, batch).await {
        Ok(resp) => Ok(resp),
        Err(err) => {
            log_stat_error!(err, &context);
            Err(err)
        }
    }
}

/// Logs a header-validation error before a Context could be constructed.
/// Manually extracts raw header values for structured logging, then bumps
/// the error metric with no Context path (falls back to "unknown").
fn log_and_return_header_error(
    err: v1::Error,
    headers: &HeaderMap,
    ip: &InsecureClientIp,
    query: &AxumQuery<Query>,
    method: &Method,
    path: &MatchedPath,
) -> v1::Error {
    let token = raw_header_str(headers, header::AUTHORIZATION.as_str());
    let request_id = raw_header_str(headers, POSTHOG_REQUEST_ID);
    let sdk_info = raw_header_str(headers, POSTHOG_SDK_INFO);
    let attempt = raw_header_str(headers, POSTHOG_ATTEMPT);
    let client_ts = raw_header_str(headers, POSTHOG_REQUEST_TIMESTAMP);
    let user_agent = raw_header_str(headers, "user-agent");
    let content_type = raw_header_str(headers, "content-type");
    let content_encoding = raw_header_str(headers, "content-encoding");

    let msg = format!("{}: {err:#}", err.tag());
    match err.log_level() {
        Level::WARN => tracing::warn!(
            token = %token,
            request_id = %request_id,
            sdk_info = %sdk_info,
            attempt = %attempt,
            client_timestamp = %client_ts,
            user_agent = %user_agent,
            content_type = %content_type,
            content_encoding = %content_encoding,
            client_ip = %ip.0,
            method = %method,
            query = ?query.0,
            path = %path.as_str(),
            "{}", msg
        ),
        _ => tracing::error!(
            token = %token,
            request_id = %request_id,
            sdk_info = %sdk_info,
            attempt = %attempt,
            client_timestamp = %client_ts,
            user_agent = %user_agent,
            content_type = %content_type,
            content_encoding = %content_encoding,
            client_ip = %ip.0,
            method = %method,
            query = ?query.0,
            path = %path.as_str(),
            "{}", msg
        ),
    }
    err.stat_error(None::<&Context>);
    err
}

async fn check_token_rate_limit(
    limiter: &crate::global_rate_limiter::GlobalRateLimiter,
    context: &Context,
    event_count: u64,
) -> Result<(), v1::Error> {
    let cache_key = GlobalRateLimitKey::Token(&context.api_token).to_cache_key();
    if let Some(limited) = limiter.is_limited(&cache_key, event_count).await {
        metrics::counter!(
            CAPTURE_V1_RATE_LIMITER,
            "limiter" => "token",
            "outcome" => "limited",
        )
        .increment(1);
        ctx_log!(Level::WARN, context,
            count = limited.current_count as u64,
            threshold = limited.threshold,
            interval = ?limited.window_interval,
            "token rate limit exceeded"
        );
        Err(v1::Error::RateLimited(
            "token rate limit exceeded".to_string(),
        ))
    } else {
        metrics::counter!(
            CAPTURE_V1_RATE_LIMITER,
            "limiter" => "token",
            "outcome" => "allowed",
        )
        .increment(1);
        Ok(())
    }
}

fn raw_header_str<'a>(headers: &'a HeaderMap, name: &str) -> &'a str {
    headers
        .get(name)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("absent")
}
