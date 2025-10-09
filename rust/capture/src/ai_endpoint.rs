use axum::body::Bytes;
use axum::extract::{DefaultBodyLimit, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::IntoResponse;
use tracing::{debug, info, warn};

use crate::api::{CaptureError, CaptureResponse, CaptureResponseCode};
use crate::router::State as AppState;
use crate::token::validate_token;

pub async fn ai_handler(
    State(_state): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<CaptureResponse, CaptureError> {
    debug!("Received request to /i/v0/ai endpoint");

    // Check for empty body
    if body.is_empty() {
        warn!("AI endpoint received empty body");
        return Err(CaptureError::EmptyPayload);
    }

    // Check content type - must be multipart/form-data
    let content_type = headers
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    if !content_type.starts_with("multipart/form-data") {
        warn!("AI endpoint received non-multipart content type: {}", content_type);
        return Err(CaptureError::RequestDecodingError(
            "Content-Type must be multipart/form-data".to_string(),
        ));
    }

    // Check for authentication
    let auth_header = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    if !auth_header.starts_with("Bearer ") {
        warn!("AI endpoint missing or invalid Authorization header");
        return Err(CaptureError::NoTokenError);
    }

    // Extract and validate token
    let token = &auth_header[7..]; // Remove "Bearer " prefix
    validate_token(token)?;

    // Log request details for debugging
    debug!("AI endpoint request validated successfully");
    debug!("Body size: {} bytes", body.len());
    debug!("Content-Type: {}", content_type);
    debug!("Token: {}...", &token[..std::cmp::min(8, token.len())]);

    // TODO: Parse multipart data and process AI events
    // For now, just return success
    Ok(CaptureResponse {
        status: CaptureResponseCode::Ok,
        quota_limited: None,
    })
}

pub async fn options() -> Result<CaptureResponse, CaptureError> {
    Ok(CaptureResponse {
        status: CaptureResponseCode::Ok,
        quota_limited: None,
    })
}
