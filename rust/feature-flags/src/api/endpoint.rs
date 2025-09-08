use crate::{
    api::{
        errors::FlagError,
        types::{
            ConfigResponse, FlagsQueryParams, FlagsResponse, LegacyFlagsResponse, ServiceResponse,
        },
    },
    handler::{process_request, RequestContext},
    router,
};
// TODO: stream this instead
use axum::extract::{MatchedPath, Query, State};
use axum::http::{HeaderMap, Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::{debug_handler, Json};
use axum_client_ip::InsecureClientIp;
use bytes::Bytes;
use std::collections::HashMap;
use tracing::Instrument;
use uuid::Uuid;

struct LogContext<'a> {
    headers: &'a HeaderMap,
    query_params: &'a FlagsQueryParams,
    method: &'a Method,
    path: &'a MatchedPath,
    ip: &'a str,
    request_id: Uuid,
    is_from_decide: bool,
    query_version: Option<i32>,
    response_format: &'a str,
}

fn get_minimal_flags_response(version: Option<&str>) -> Result<Json<ServiceResponse>, FlagError> {
    let request_id = Uuid::new_v4();

    // Parse version string to determine response format
    let version_num = version.map(|v| v.parse::<i32>().unwrap_or(1)).unwrap_or(1);

    // Create minimal config response
    let config = ConfigResponse {
        supported_compression: vec!["gzip".to_string(), "gzip-js".to_string()],
        ..Default::default()
    };

    // Create empty flags response with minimal config
    let response = FlagsResponse {
        errors_while_computing_flags: false,
        flags: HashMap::new(),
        quota_limited: None,
        request_id,
        config,
    };

    // Return versioned response
    let service_response = if version_num >= 2 {
        ServiceResponse::V2(response)
    } else {
        ServiceResponse::Default(LegacyFlagsResponse::from_response(response))
    };

    Ok(Json(service_response))
}

/// Determines the response format based on whether the request came from decide and the version parameter.
///
/// When the request is from decide (X-Original-Endpoint: decide):
/// - v=1 or missing -> DecideV1 response format
/// - v=2 -> DecideV2 response format  
/// - v=3 -> FlagsV1 response format
/// - v>=4 -> FlagsV2 response format
///
/// When the request is not from decide:
/// - v>=2 -> FlagsV2 response format
/// - v=1 or missing -> FlagsV1 response format
///
/// Returns a tuple of (response, format_name) for logging purposes
fn get_versioned_response(
    is_from_decide: bool,
    version: Option<i32>,
    response: FlagsResponse,
) -> Result<(ServiceResponse, &'static str), FlagError> {
    if is_from_decide {
        match version {
            Some(1) | None => Ok((
                ServiceResponse::DecideV1(crate::api::types::DecideV1Response::from_response(
                    response,
                )),
                "DecideV1",
            )),
            Some(2) => Ok((
                ServiceResponse::DecideV2(crate::api::types::DecideV2Response::from_response(
                    response,
                )),
                "DecideV2",
            )),
            Some(3) => Ok((
                ServiceResponse::Default(LegacyFlagsResponse::from_response(response)),
                "FlagsV1",
            )),
            Some(v) if v >= 4 => Ok((ServiceResponse::V2(response), "FlagsV2")),
            Some(_) => {
                // Any other version defaults to DecideV1
                Ok((
                    ServiceResponse::DecideV1(crate::api::types::DecideV1Response::from_response(
                        response,
                    )),
                    "DecideV1",
                ))
            }
        }
    } else {
        match version {
            Some(v) if v >= 2 => Ok((ServiceResponse::V2(response), "FlagsV2")),
            _ => Ok((
                ServiceResponse::Default(LegacyFlagsResponse::from_response(response)),
                "FlagsV1",
            )),
        }
    }
}

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
) -> Result<Response, FlagError> {
    let request_id = Uuid::new_v4();

    // Handle different HTTP methods
    match method {
        Method::GET => {
            // GET requests return minimal flags response
            return Ok(get_minimal_flags_response(query_params.version.as_deref())?.into_response());
        }
        Method::POST => {
            // POST requests continue with full processing logic below
        }
        Method::HEAD => {
            // HEAD returns the same headers as GET but without body
            let response = (
                StatusCode::OK,
                [("content-type", "application/json")],
                axum::body::Body::empty(),
            )
                .into_response();
            return Ok(response);
        }
        Method::OPTIONS => {
            // OPTIONS should return allowed methods
            let response = (
                StatusCode::NO_CONTENT,
                [("allow", "GET, POST, OPTIONS, HEAD")],
            )
                .into_response();
            return Ok(response);
        }
        _ => {
            // Return 405 Method Not Allowed for all other methods
            let response = (
                StatusCode::METHOD_NOT_ALLOWED,
                [("allow", "GET, POST, OPTIONS, HEAD")],
            )
                .into_response();
            return Ok(response);
        }
    }

    // Check if this request came through the decide proxy
    let is_from_decide = headers
        .get("X-Original-Endpoint")
        .and_then(|v| v.to_str().ok())
        .map(|v| v == "decide")
        .unwrap_or(false);

    // Modify query params to enable config for decide requests
    let mut modified_query_params = query_params.clone();
    if is_from_decide && modified_query_params.config.is_none() {
        modified_query_params.config = Some(true);
    }

    // Default to v=2 and config=true when both params are missing
    // This provides the latest response format for clients that don't specify these params
    if modified_query_params.version.is_none() && modified_query_params.config.is_none() {
        modified_query_params.version = Some("2".to_string());
        modified_query_params.config = Some(true);
    }

    let context = RequestContext {
        request_id,
        state,
        ip,
        headers: headers.clone(),
        meta: modified_query_params,
        body,
    };

    // Parse version from query params
    let query_version = context
        .meta
        .version
        .clone()
        .as_deref()
        .map(|v| v.parse::<i32>().unwrap_or(1));

    // Create debug span for detailed tracing when debugging
    let _span = create_request_span(
        &headers,
        &query_params,
        &method,
        &path,
        &ip.to_string(),
        request_id,
    );

    let response = async move { process_request(context).await }
        .instrument(_span)
        .await?;

    // Determine the response format based on whether request is from decide and version
    let (versioned_response, response_format) =
        get_versioned_response(is_from_decide, query_version, response)?;

    let log_context = LogContext {
        headers: &headers,
        query_params: &query_params,
        method: &method,
        path: &path,
        ip: &ip.to_string(),
        request_id,
        is_from_decide,
        query_version,
        response_format,
    };
    log_request_info(log_context);

    Ok(Json(versioned_response).into_response())
}

fn log_request_info(ctx: LogContext) {
    let user_agent = ctx
        .headers
        .get("user-agent")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    let content_encoding = ctx
        .query_params
        .compression
        .as_ref()
        .map_or("none", |c| c.as_str());
    let content_type = ctx
        .headers
        .get("content-type")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));

    tracing::info!(
        user_agent = %user_agent,
        content_encoding = %content_encoding,
        content_type = %content_type,
        version = %ctx.query_params.version.as_deref().unwrap_or("unknown"),
        lib_version = %ctx.query_params.lib_version.as_deref().unwrap_or("unknown"),
        compression = %ctx.query_params.compression.as_ref().map_or("none", |c| c.as_str()),
        method = %ctx.method.as_str(),
        path = %ctx.path.as_str().trim_end_matches('/'),
        ip = %ctx.ip,
        sent_at = %ctx.query_params.sent_at.unwrap_or(0).to_string(),
        request_id = %ctx.request_id,
        is_from_decide = %ctx.is_from_decide,
        query_version = ?ctx.query_version,
        response_format = %ctx.response_format,
        "Processing request"
    );
}

fn create_request_span(
    headers: &HeaderMap,
    query_params: &FlagsQueryParams,
    method: &Method,
    path: &MatchedPath,
    ip: &str,
    request_id: Uuid,
) -> tracing::Span {
    let user_agent = headers
        .get("user-agent")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    let content_encoding = query_params
        .compression
        .as_ref()
        .map_or("none", |c| c.as_str());
    let content_type = headers
        .get("content-type")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));

    tracing::debug_span!(
        "request",
        user_agent = %user_agent,
        content_encoding = %content_encoding,
        content_type = %content_type,
        version = %query_params.version.as_deref().unwrap_or("unknown"),
        lib_version = %query_params.lib_version.as_deref().unwrap_or("unknown"),
        compression = %query_params.compression.as_ref().map_or("none", |c| c.as_str()),
        method = %method.as_str(),
        path = %path.as_str().trim_end_matches('/'),
        ip = %ip,
        sent_at = %query_params.sent_at.unwrap_or(0).to_string(),
        request_id = %request_id
    )
}

#[cfg(test)]
mod tests {
    use crate::api::types::Compression;

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

    #[test]
    fn test_default_params_logic() {
        // Test the parameter modification logic that's applied in the flags endpoint
        let mut params_both_none = FlagsQueryParams {
            version: None,
            config: None,
            compression: None,
            lib_version: None,
            sent_at: None,
            only_evaluate_survey_feature_flags: None,
        };

        if params_both_none.version.is_none() && params_both_none.config.is_none() {
            params_both_none.version = Some("2".to_string());
            params_both_none.config = Some(true);
        }

        assert_eq!(params_both_none.version, Some("2".to_string()));
        assert_eq!(params_both_none.config, Some(true));

        // Test when only version is missing - no defaults should apply
        let mut params_version_missing = FlagsQueryParams {
            version: None,
            config: Some(false),
            compression: None,
            lib_version: None,
            sent_at: None,
            only_evaluate_survey_feature_flags: None,
        };

        if params_version_missing.version.is_none() && params_version_missing.config.is_none() {
            params_version_missing.version = Some("2".to_string());
            params_version_missing.config = Some(true);
        }

        assert_eq!(params_version_missing.version, None);
        assert_eq!(params_version_missing.config, Some(false));

        // Test when only config is missing - no defaults should apply
        let mut params_config_missing = FlagsQueryParams {
            version: Some("1".to_string()),
            config: None,
            compression: None,
            lib_version: None,
            sent_at: None,
            only_evaluate_survey_feature_flags: None,
        };

        if params_config_missing.version.is_none() && params_config_missing.config.is_none() {
            params_config_missing.version = Some("2".to_string());
            params_config_missing.config = Some(true);
        }

        assert_eq!(params_config_missing.version, Some("1".to_string()));
        assert_eq!(params_config_missing.config, None);
    }
}
