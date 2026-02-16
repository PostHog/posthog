use crate::{
    api::{
        errors::{ClientFacingError, FlagError},
        types::{
            ConfigResponse, FlagsQueryParams, FlagsResponse, LegacyFlagsResponse, ServiceResponse,
        },
    },
    handler::{
        decoding, process_request, run_with_canonical_log, with_canonical_log,
        FlagsCanonicalLogLine, RequestContext,
    },
    router,
    utils::user_agent::UserAgentInfo,
};
// TODO: stream this instead
use axum::extract::{MatchedPath, Query, State};
use axum::http::{HeaderMap, Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::{debug_handler, Json};
use axum_client_ip::InsecureClientIp;
use bytes::Bytes;
use serde_json;
use std::collections::HashMap;
use std::net::IpAddr;
use tracing::Instrument;
use uuid::Uuid;

/// Extracts request ID from X-REQUEST-ID header, falling back to generating a new UUID if not present or invalid
/// Good for tracing logs from the Contour layer all the way to the property evaluation
fn extract_request_id(headers: &HeaderMap) -> Uuid {
    headers
        .get("X-REQUEST-ID")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.parse::<Uuid>().ok())
        .unwrap_or_else(Uuid::new_v4)
}

/// Extracts client IP address from request headers, checking X-Forwarded-For first
/// then falling back to the direct client IP. Matches Python's get_ip_address function.
fn extract_client_ip(headers: &HeaderMap, fallback_ip: IpAddr) -> IpAddr {
    // Check X-Forwarded-For header first (case-insensitive)
    if let Some(forwarded_for) = headers.get("X-Forwarded-For") {
        if let Ok(forwarded_str) = forwarded_for.to_str() {
            // Take the first IP from the comma-separated list
            if let Some(first_ip) = forwarded_str.split(',').next() {
                let trimmed = first_ip.trim();

                // Strip port from IP address if present (Azure gateway compatibility)
                let ip_without_port = if trimmed.starts_with('[') {
                    // IPv6 with port (e.g., "[::1]:8080")
                    trimmed
                        .split(']')
                        .next()
                        .and_then(|s| s.strip_prefix('['))
                        .unwrap_or(trimmed)
                } else if trimmed.contains('.') {
                    // Likely IPv4 - check for port after the last dot
                    if let Some(colon_idx) = trimmed.rfind(':') {
                        if let Some(last_dot_idx) = trimmed.rfind('.') {
                            if colon_idx > last_dot_idx {
                                // Port comes after the last dot, so this is IPv4:port
                                &trimmed[..colon_idx]
                            } else {
                                // Colon before last dot? Malformed, return as-is
                                trimmed
                            }
                        } else {
                            // Has colon but no dot? Shouldn't happen for IPv4
                            trimmed
                        }
                    } else {
                        // No colon, just return the IP
                        trimmed
                    }
                } else {
                    // No dots and no brackets - assume IPv6 without port
                    // IPv6 can have colons as part of the address, so don't strip
                    trimmed
                };

                // Try to parse the IP address
                if let Ok(parsed_ip) = ip_without_port.parse::<IpAddr>() {
                    return parsed_ip;
                }
            }
        }
    }

    // Fall back to the direct client IP
    fallback_ip
}

/// Updates the canonical log with rate limit info and returns the error for early return.
fn rate_limit_error(error: FlagError) -> FlagError {
    with_canonical_log(|l| {
        l.rate_limited = true;
        l.set_error(&error);
    });
    error
}

fn get_minimal_flags_response(
    headers: &HeaderMap,
    version: Option<&str>,
) -> Result<Json<ServiceResponse>, FlagError> {
    let request_id = extract_request_id(headers);

    // Parse version string to determine response format
    let version_num = version.map(|v| v.parse::<i32>().unwrap_or(1)).unwrap_or(1);

    // Create minimal config response
    let mut config = ConfigResponse::new();
    config.set(
        "supportedCompression",
        serde_json::json!(["gzip", "gzip-js"]),
    );
    config.set(
        "config",
        serde_json::json!({"enable_collect_everything": true}),
    );
    config.set("toolbarParams", serde_json::json!({}));
    config.set("isAuthenticated", serde_json::json!(false));
    config.set("sessionRecording", serde_json::json!(false));

    // Create empty flags response with minimal config
    let mut response = FlagsResponse::new(false, HashMap::new(), None, request_id);
    response.config = config;

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
    InsecureClientIp(direct_ip): InsecureClientIp,
    Query(query_params): Query<FlagsQueryParams>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Bytes,
) -> Result<Response, FlagError> {
    let request_id = extract_request_id(&headers);

    // Extract client IP, checking X-Forwarded-For header first
    let ip = extract_client_ip(&headers, direct_ip);

    // Handle different HTTP methods (these don't need canonical logging)
    match method {
        Method::GET => {
            // GET requests return minimal flags response
            return Ok(
                get_minimal_flags_response(&headers, query_params.version.as_deref())?
                    .into_response(),
            );
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

    // Convert IP to string once and reuse throughout the request
    let ip_string = ip.to_string();

    // Parse User-Agent and extract SDK info for logging
    let user_agent = headers.get("user-agent").and_then(|v| v.to_str().ok());
    let ua_info = UserAgentInfo::parse(user_agent);

    // Initialize canonical log with all upfront request metadata.
    // Fields discovered during processing (team_id, flags_evaluated, etc.) are set via with_canonical_log().
    let canonical_log = FlagsCanonicalLogLine {
        request_id,
        ip: ip_string.clone(),
        user_agent: user_agent.map(|s| s.to_string()),
        lib: ua_info.lib_for_logging(),
        // Browser SDK sends ver= query param, server SDKs send version in User-Agent
        lib_version: query_params.lib_version.clone().or(ua_info.sdk_version),
        api_version: query_params.version.clone(),
        ..Default::default()
    };

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

    // Parse version from query params (needed for response formatting)
    let query_version = modified_query_params
        .version
        .as_deref()
        .map(|v| v.parse::<i32>().unwrap_or(1));

    let context = RequestContext {
        request_id,
        state: state.clone(),
        ip,
        headers: headers.clone(),
        meta: modified_query_params,
        body,
    };

    // Create debug span for detailed tracing when debugging
    let _span = create_request_span(
        &headers,
        &query_params,
        &method,
        &path,
        &ip_string,
        request_id,
    );

    // Run the request within a canonical log scope.
    // All code within can use with_canonical_log() to update the log.
    let (result, mut log) = run_with_canonical_log(canonical_log, async {
        // Rate limiting strategy (order matters for security):
        // 1. IP-based rate limiting first - prevents DDoS with rotating tokens
        // 2. Token-based rate limiting second - enforces per-project limits
        //
        // This order ensures that an attacker cannot bypass rate limiting by
        // simply rotating through fake tokens from the same IP address.

        // Check IP-based rate limit first
        if !state.ip_rate_limiter.allow_request(&ip_string) {
            return Err(rate_limit_error(FlagError::ClientFacing(
                ClientFacingError::IpRateLimited,
            )));
        }

        // Check token-based rate limit
        // Extract token from body, use IP as fallback if extraction fails
        let rate_limit_key =
            decoding::extract_token(&context.body).unwrap_or_else(|| ip_string.clone());
        if !state.flags_rate_limiter.allow_request(&rate_limit_key) {
            return Err(rate_limit_error(FlagError::ClientFacing(
                ClientFacingError::TokenRateLimited,
            )));
        }

        process_request(context).await
    })
    .instrument(_span)
    .await;

    // Emit DB operations metrics before the canonical log
    log.emit_db_operations_metrics();

    match result {
        Ok(response) => {
            // Determine the response format based on whether request is from decide and version
            match get_versioned_response(is_from_decide, query_version, response) {
                Ok((versioned_response, _response_format)) => {
                    log.http_status = 200;
                    log.emit();
                    Ok(Json(versioned_response).into_response())
                }
                Err(e) => {
                    log.emit_for_error(&e);
                    Err(e)
                }
            }
        }
        Err(e) => {
            log.emit_for_error(&e);
            Err(e)
        }
    }
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

    #[test]
    fn test_extract_client_ip() {
        use axum::http::HeaderValue;
        use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};

        let fallback = IpAddr::V4(Ipv4Addr::new(127, 0, 0, 1));

        // Test case 1: X-Forwarded-For with single IP
        let mut headers = HeaderMap::new();
        headers.insert(
            "X-Forwarded-For",
            HeaderValue::from_str("192.168.1.1").unwrap(),
        );
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, IpAddr::V4(Ipv4Addr::new(192, 168, 1, 1)));

        // Test case 2: X-Forwarded-For with multiple IPs (should take the first)
        headers.clear();
        headers.insert(
            "X-Forwarded-For",
            HeaderValue::from_str("10.0.0.1, 192.168.1.1, 172.16.0.1").unwrap(),
        );
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, IpAddr::V4(Ipv4Addr::new(10, 0, 0, 1)));

        // Test case 3: X-Forwarded-For with IPv4 and port (Azure gateway compatibility)
        headers.clear();
        headers.insert(
            "X-Forwarded-For",
            HeaderValue::from_str("203.0.113.195:8080").unwrap(),
        );
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, IpAddr::V4(Ipv4Addr::new(203, 0, 113, 195)));

        // Test case 4: X-Forwarded-For with IPv6
        headers.clear();
        headers.insert(
            "X-Forwarded-For",
            HeaderValue::from_str("2001:db8::8a2e:370:7334").unwrap(),
        );
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(
            ip,
            IpAddr::V6(Ipv6Addr::new(0x2001, 0xdb8, 0, 0, 0, 0x8a2e, 0x370, 0x7334))
        );

        // Test case 5: X-Forwarded-For with IPv6 and port
        headers.clear();
        headers.insert(
            "X-Forwarded-For",
            HeaderValue::from_str("[2001:db8::1]:8080").unwrap(),
        );
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(
            ip,
            IpAddr::V6(Ipv6Addr::new(0x2001, 0xdb8, 0, 0, 0, 0, 0, 1))
        );

        // Test case 6: No X-Forwarded-For header (should use fallback)
        headers.clear();
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, fallback);

        // Test case 7: Invalid IP in X-Forwarded-For (should use fallback)
        headers.clear();
        headers.insert(
            "X-Forwarded-For",
            HeaderValue::from_str("invalid-ip").unwrap(),
        );
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, fallback);

        // Test case 8: Empty X-Forwarded-For (should use fallback)
        headers.clear();
        headers.insert("X-Forwarded-For", HeaderValue::from_str("").unwrap());
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, fallback);

        // Test case 9: IPv6 address that could be confused with IPv4:port
        headers.clear();
        headers.insert("X-Forwarded-For", HeaderValue::from_str("::1").unwrap());
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, IpAddr::V6(Ipv6Addr::new(0, 0, 0, 0, 0, 0, 0, 1)));

        // Test case 10: Compact IPv6 address with few colons
        headers.clear();
        headers.insert("X-Forwarded-For", HeaderValue::from_str("fe80::1").unwrap());
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, IpAddr::V6(Ipv6Addr::new(0xfe80, 0, 0, 0, 0, 0, 0, 1)));
    }

    #[test]
    fn test_extract_request_id() {
        use axum::http::HeaderValue;

        // Test with valid UUID in header
        let mut headers = HeaderMap::new();
        let valid_uuid = "550e8400-e29b-41d4-a716-446655440000";
        headers.insert("x-request-id", HeaderValue::from_static(valid_uuid));

        let extracted_id = extract_request_id(&headers);
        assert_eq!(extracted_id.to_string(), valid_uuid);

        // Test with invalid UUID in header - should generate new UUID
        let mut headers_invalid = HeaderMap::new();
        headers_invalid.insert("x-request-id", HeaderValue::from_static("invalid-uuid"));

        let extracted_id_invalid = extract_request_id(&headers_invalid);
        // Should be a valid UUID (not the invalid string)
        assert_ne!(extracted_id_invalid.to_string(), "invalid-uuid");
        assert!(extracted_id_invalid.to_string().len() == 36); // UUID format

        // Test without header - should generate new UUID
        let empty_headers = HeaderMap::new();
        let extracted_id_empty = extract_request_id(&empty_headers);
        assert!(extracted_id_empty.to_string().len() == 36); // UUID format

        // Two calls without header should generate different UUIDs
        let extracted_id_empty2 = extract_request_id(&empty_headers);
        assert_ne!(extracted_id_empty, extracted_id_empty2);
    }
}
