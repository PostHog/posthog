use axum::body::Body;
use axum::extract::{MatchedPath, Query as AxumQuery, State};
use axum::http::{HeaderMap, Method};
use axum_client_ip::InsecureClientIp;

use super::header::*;
use super::query::Query;
use super::response::Response;
use super::types::CaptureV1Batch;
use crate::v1::context::Context;
use crate::{log_stat_error, router, v1};

pub async fn handle_request(
    state: State<router::State>,
    headers: HeaderMap,
    query: AxumQuery<Query>,
    ip: InsecureClientIp,
    method: Method,
    path: MatchedPath,
    body: Body,
) -> Result<Response, v1::Error> {
    let context = Context::new(&headers, &ip, &query, method.clone(), path.as_str())
        .map_err(|err| log_and_return_header_error(err, &headers, &ip, &query, &method, &path))?;

    // TODO: purposely chatty, for now
    tracing::info!(ctx = ?context, "handle_request called");

    let raw_bytes = v1::util::extract_body_with_timeout(
        body,
        state.event_payload_size_limit,
        state.body_chunk_read_timeout,
        state.body_read_chunk_size_kb,
        &context.path,
    )
    .await
    .map_err(|err| {
        log_stat_error!(err, ctx = &context);
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
        log_stat_error!(err, ctx = &context);
        err
    })?;

    let batch: CaptureV1Batch = serde_json::from_slice(&payload).map_err(|e| {
        let err = v1::Error::RequestParsingError(e.to_string());
        log_stat_error!(err, ctx = &context);
        err
    })?;

    if batch.batch.is_empty() {
        let err = v1::Error::EmptyBatch;
        log_stat_error!(err, ctx = &context);
        return Err(err);
    }

    match super::process::process_batch(&context, batch).await {
        Ok(resp) => Ok(resp),
        Err(err) => {
            log_stat_error!(err, ctx = &context);
            Err(err)
        }
    }
}

fn log_and_return_header_error(
    err: v1::Error,
    headers: &HeaderMap,
    ip: &InsecureClientIp,
    query: &AxumQuery<Query>,
    method: &Method,
    path: &MatchedPath,
) -> v1::Error {
    let token = raw_header_str(headers, POSTHOG_API_TOKEN);
    let request_id = raw_header_str(headers, POSTHOG_REQUEST_ID);
    let sdk_info = raw_header_str(headers, POSTHOG_SDK_INFO);
    let attempt = raw_header_str(headers, POSTHOG_ATTEMPT);
    let client_ts = raw_header_str(headers, POSTHOG_CLIENT_TIMESTAMP);
    let user_agent = raw_header_str(headers, "user-agent");
    let content_type = raw_header_str(headers, "content-type");
    let content_encoding = raw_header_str(headers, "content-encoding");

    log_stat_error!(err,
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
    );
    err
}

fn raw_header_str<'a>(headers: &'a HeaderMap, name: &str) -> &'a str {
    headers
        .get(name)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("absent")
}
