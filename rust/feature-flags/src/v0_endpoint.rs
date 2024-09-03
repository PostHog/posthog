use std::net::IpAddr;

use crate::{
    api::{FlagError, FlagsResponse},
    request_handler::{process_request, FlagsQueryParams, RequestContext},
    router,
};
// TODO: stream this instead
use axum::extract::{MatchedPath, Query, State};
use axum::http::{HeaderMap, Method};
use axum::{debug_handler, Json};
use axum_client_ip::InsecureClientIp;
use bytes::Bytes;
use tracing::instrument;

/// Feature flag evaluation endpoint.
/// Only supports a specific shape of data, and rejects any malformed data.

#[instrument(
    skip_all,
    fields(
        path,
        token,
        batch_size,
        user_agent,
        content_encoding,
        content_type,
        version,
        compression,
        historical_migration
    )
)]
#[debug_handler]
pub async fn flags(
    state: State<router::State>,
    InsecureClientIp(ip): InsecureClientIp,
    meta: Query<FlagsQueryParams>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Bytes,
) -> Result<Json<FlagsResponse>, FlagError> {
    record_request_metadata(&headers, &method, &path, &ip, &meta);

    let context = RequestContext {
        state,
        ip,
        meta: meta.0,
        headers,
        body,
    };

    Ok(Json(process_request(context).await?))
}

fn record_request_metadata(
    headers: &HeaderMap,
    method: &Method,
    path: &MatchedPath,
    ip: &IpAddr,
    meta: &Query<FlagsQueryParams>,
) {
    let user_agent = headers
        .get("user-agent")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    let content_encoding = headers
        .get("content-encoding")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    let content_type = headers
        .get("content-type")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));

    tracing::Span::current().record("user_agent", user_agent);
    tracing::Span::current().record("content_encoding", content_encoding);
    tracing::Span::current().record("content_type", content_type);
    tracing::Span::current().record("version", meta.version.as_deref().unwrap_or("unknown"));
    tracing::Span::current().record(
        "lib_version",
        meta.lib_version.as_deref().unwrap_or("unknown"),
    );
    tracing::Span::current().record(
        "compression",
        meta.compression.as_ref().map_or("none", |c| c.as_str()),
    );
    tracing::Span::current().record("method", method.as_str());
    tracing::Span::current().record("path", path.as_str().trim_end_matches('/'));
    tracing::Span::current().record("ip", ip.to_string());
    tracing::Span::current().record("sent_at", meta.sent_at.unwrap_or(0).to_string());
}
