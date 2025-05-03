use crate::{
    api::errors::FlagError,
    api::request_handler::{process_request, RequestContext},
    api::types::{FlagsOptionsResponse, FlagsResponseCode, LegacyFlagsResponse, ServiceResponse},
    router,
};
// TODO: stream this instead
use axum::extract::{MatchedPath, Query, State};
use axum::http::{HeaderMap, Method};
use axum::{debug_handler, Json};
use axum_client_ip::InsecureClientIp;
use bytes::Bytes;
use common_request::{create_request_span, FlagsQueryParams, RequestInfo};
use uuid::Uuid;

/// Feature flag evaluation endpoint.
/// Only supports a specific shape of data, and rejects any malformed data.
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
    let request_id = Uuid::new_v4();

    let context = RequestContext {
        request: RequestInfo {
            id: request_id,
            ip,
            headers: headers.clone(),
            meta: query_params.clone(),
            body,
            method,
        },
        state,
    };

    let version = context
        .request
        .meta
        .version
        .clone()
        .as_deref()
        .map(|v| v.parse::<i32>().unwrap_or(1));

    // NB: need to create the span, enter it, and then drop it,
    // so that the span is closed before the await (otherwise it will
    // be closed when the function returns, which won't compile)
    {
        let _span = create_request_span(&context.request, &path).entered();
    }

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

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        body::Body,
        extract::{FromRequest, Request},
        http::Uri,
    };
    use common_request::{Compression, FlagsQueryParams};

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
