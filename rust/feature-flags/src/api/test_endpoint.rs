use axum::{
    debug_handler,
    extract::{MatchedPath, Query},
    http::{HeaderMap, Method},
    Json,
};
use axum_client_ip::InsecureClientIp;
use bytes::Bytes;
use tracing::error;
use uuid::Uuid;

use crate::api::{
    errors::FlagError,
    request_handler::{decode_request, FlagsQueryParams},
    types::LegacyFlagsResponse,
};

// Metrics constants for test endpoint
pub const REQUEST_SEEN: &str = "flags_test_request_seen";
pub const CONTENT_HEADER_TYPE: &str = "flags_test_content_header_type";
pub const REQUEST_OUTCOME: &str = "flags_test_request_outcome";
pub const COMPRESSION_TYPE: &str = "flags_test_compression_type";
pub const PARSING_FAILED: &str = "flags_test_parsing_failed";
pub const TOKEN_VALIDATION: &str = "flags_test_token_validation";

#[debug_handler]
pub async fn test_black_hole(
    _ip: InsecureClientIp,
    meta: Query<FlagsQueryParams>,
    headers: HeaderMap,
    _method: Method,
    _path: MatchedPath,
    body: Bytes,
) -> Result<Json<LegacyFlagsResponse>, FlagError> {
    metrics::counter!(REQUEST_SEEN).increment(1);

    // Track compression type
    let comp = meta.compression.as_ref().map_or("none", |c| c.as_str());
    metrics::counter!(COMPRESSION_TYPE, "type" => comp.to_string()).increment(1);

    // Track content type
    let content_type = headers
        .get("content-type")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    metrics::counter!(CONTENT_HEADER_TYPE, "type" => content_type.to_string()).increment(1);

    // Attempt to decode the request using the handler's decode_request function
    let request = match decode_request(&headers, body, &meta) {
        Ok(req) => req,
        Err(e) => {
            error!("failed to decode request: {}", e);
            metrics::counter!(
                REQUEST_OUTCOME,
                "outcome" => "failure",
                "reason" => "request_decoding_error"
            )
            .increment(1);
            metrics::counter!(PARSING_FAILED).increment(1);
            return Err(e);
        }
    };

    // Validate token
    match request.token {
        Some(token) if !token.is_empty() => {
            metrics::counter!(TOKEN_VALIDATION, "outcome" => "success").increment(1);
        }
        _ => {
            metrics::counter!(TOKEN_VALIDATION, "outcome" => "failure").increment(1);
            metrics::counter!(
                REQUEST_OUTCOME,
                "outcome" => "failure",
                "reason" => "missing_token"
            )
            .increment(1);
            return Err(FlagError::NoTokenError);
        }
    }

    // Validate distinct_id
    match request.distinct_id {
        Some(distinct_id) if !distinct_id.is_empty() => {
            metrics::counter!(
                REQUEST_OUTCOME,
                "outcome" => "success",
                "reason" => "valid_distinct_id"
            )
            .increment(1);
        }
        Some(_) => {
            metrics::counter!(
                REQUEST_OUTCOME,
                "outcome" => "failure",
                "reason" => "empty_distinct_id"
            )
            .increment(1);
            return Err(FlagError::EmptyDistinctId);
        }
        None => {
            metrics::counter!(
                REQUEST_OUTCOME,
                "outcome" => "failure",
                "reason" => "missing_distinct_id"
            )
            .increment(1);
            return Err(FlagError::MissingDistinctId);
        }
    }

    // If we got here, the request is valid
    metrics::counter!(REQUEST_OUTCOME, "outcome" => "success").increment(1);

    let request_id = Uuid::new_v4();

    Ok(Json(LegacyFlagsResponse {
        feature_flags: Default::default(),
        feature_flag_payloads: Default::default(),
        quota_limited: None,
        errors_while_computing_flags: false,
        request_id,
    }))
}
