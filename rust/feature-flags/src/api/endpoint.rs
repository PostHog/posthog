use std::net::IpAddr;

use crate::{
    api::errors::FlagError,
    api::request_handler::{process_request, FlagsQueryParams, RequestContext},
    api::types::{FlagsOptionsResponse, FlagsResponseCode, LegacyFlagsResponse, ServiceResponse},
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
    Query(query_params): Query<FlagsQueryParams>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Bytes,
) -> Result<Json<ServiceResponse>, FlagError> {
    record_request_metadata(&headers, &method, &path, &ip, &Query(query_params.clone()));

    let context = RequestContext {
        state,
        ip,
        headers,
        meta: query_params,
        body,
    };

    let version = context
        .meta
        .version
        .clone()
        .as_deref()
        .map(|v| v.parse::<i32>().unwrap_or(1));

    let response = process_request(context).await?;

    let versioned_response: Result<ServiceResponse, FlagError> = match version {
        Some(v) if v >= 2 => Ok(ServiceResponse::V2(response)),
        _ => Ok(ServiceResponse::Default(
            LegacyFlagsResponse::from_response(response),
        )),
    };

    Ok(Json(versioned_response?))
}

pub async fn options() -> Result<Json<FlagsOptionsResponse>, FlagError> {
    Ok(Json(FlagsOptionsResponse {
        status: FlagsResponseCode::Ok,
    }))
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
    let content_encoding = meta.compression.as_ref().map_or("none", |c| c.as_str());
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

#[cfg(test)]
mod tests {
    use crate::api::request_handler::Compression;

    use super::*;
    use axum::{
        body::Body,
        extract::{FromRequest, Request},
        http::Uri,
    };

    #[tokio::test]
    async fn test_query_param_extraction() {
        // Test case 1: Full query string
        let uri = Uri::from_static(
            "http://localhost:3001/flags/?v=3&compression=base64&ver=1.211.0&_=1738006794028",
        );
        let req = Request::builder().uri(uri).body(Body::empty()).unwrap();
        let Query(params) = Query::<FlagsQueryParams>::from_request(req, &())
            .await
            .unwrap();

        assert_eq!(params.version, Some("3".to_string()));
        assert_eq!(params.lib_version, Some("1.211.0".to_string()));
        assert_eq!(params.sent_at, Some(1738006794028));
        assert!(matches!(params.compression, Some(Compression::Base64)));

        // Test case 2: Partial query string
        let uri = Uri::from_static("http://localhost:3001/flags/?v=2&compression=gzip");
        let req = Request::builder().uri(uri).body(Body::empty()).unwrap();
        let Query(params) = Query::<FlagsQueryParams>::from_request(req, &())
            .await
            .unwrap();

        assert_eq!(params.version, Some("2".to_string()));
        assert!(matches!(params.compression, Some(Compression::Gzip)));
        assert_eq!(params.lib_version, None);
        assert_eq!(params.sent_at, None);

        // Test case 3: Empty query string
        let uri = Uri::from_static("http://localhost:3001/flags/");
        let req = Request::builder().uri(uri).body(Body::empty()).unwrap();
        let Query(params) = Query::<FlagsQueryParams>::from_request(req, &())
            .await
            .unwrap();

        assert_eq!(params.version, None);
        assert_eq!(params.compression, None);
        assert_eq!(params.lib_version, None);
        assert_eq!(params.sent_at, None);

        // Test case 4: Invalid compression type
        let uri = Uri::from_static("http://localhost:3001/flags/?compression=invalid");
        let req = Request::builder().uri(uri).body(Body::empty()).unwrap();
        let Query(params) = Query::<FlagsQueryParams>::from_request(req, &())
            .await
            .unwrap();

        assert!(matches!(params.compression, Some(Compression::Unsupported)));
    }
}
