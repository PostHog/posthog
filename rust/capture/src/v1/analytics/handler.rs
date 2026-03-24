use axum::body::Body;
use axum::extract::{MatchedPath, Query as AxumQuery, State};
use axum::http::{HeaderMap, Method};
use axum_client_ip::InsecureClientIp;

use super::header::*;
use super::query::Query;
use super::response::Response;
use crate::v1::context::Context;
use crate::{log_stat_error, router, v1};

pub async fn handle_request(
    state: State<router::State>,
    headers: HeaderMap,
    query: AxumQuery<Query>,
    ip: InsecureClientIp,
    _method: Method,
    path: MatchedPath,
    body: Body,
) -> Result<Response, v1::Error> {
    let context = Context::new(&headers)
        .map_err(|err| log_and_return_header_error(err, &headers, &ip, &query, &path))?;

    let _bytes = v1::util::extract_body_with_timeout(
        body,
        state.event_payload_size_limit,
        state.body_chunk_read_timeout,
        state.body_read_chunk_size_kb,
        path.as_str(),
    )
    .await
    .map_err(|err| log_and_return_body_error(err, &context, &ip, &query, &path))?;

    unimplemented!()
}

fn log_and_return_header_error(
    err: v1::Error,
    headers: &HeaderMap,
    ip: &InsecureClientIp,
    query: &Query,
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
        query = ?query,
        path = %path.as_str(),
    );
    err
}

fn log_and_return_body_error(
    err: v1::Error,
    context: &Context,
    ip: &InsecureClientIp,
    query: &Query,
    path: &MatchedPath,
) -> v1::Error {
    log_stat_error!(err,
        token = %context.api_token,
        request_id = %context.request_id,
        sdk_info = %context.sdk_info,
        attempt = context.attempt,
        client_timestamp = %context.client_timestamp,
        user_agent = %context.user_agent,
        content_type = %context.content_type,
        content_encoding = ?context.content_encoding,
        client_ip = %ip.0,
        query = ?query,
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
