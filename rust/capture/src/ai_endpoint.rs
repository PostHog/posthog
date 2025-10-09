use axum::body::Bytes;
use axum::extract::{DefaultBodyLimit, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Json};
use futures::stream;
use multer::{Multipart, parse_boundary};
use serde::{Deserialize, Serialize};
use tracing::{debug, info, warn};

use crate::api::{CaptureError, CaptureResponse, CaptureResponseCode};
use crate::router::State as AppState;
use crate::token::validate_token;

#[derive(Debug, Serialize, Deserialize)]
pub struct PartInfo {
    pub name: String,
    pub length: usize,
    #[serde(rename = "content-type")]
    pub content_type: Option<String>,
    #[serde(rename = "content-encoding")]
    pub content_encoding: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AIEndpointResponse {
    pub accepted_parts: Vec<PartInfo>,
}

pub async fn ai_handler(
    State(_state): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<AIEndpointResponse>, CaptureError> {
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

    // Extract boundary from Content-Type header using multer's built-in parser
    let boundary = parse_boundary(content_type).map_err(|e| {
        warn!("Failed to parse boundary from Content-Type: {}", e);
        CaptureError::RequestDecodingError(format!("Invalid boundary in Content-Type: {}", e))
    })?;

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

    // Parse multipart data and collect part information
    let accepted_parts = parse_multipart_data(&body, &boundary).await?;

    // Log request details for debugging
    debug!("AI endpoint request validated and parsed successfully");
    debug!("Body size: {} bytes", body.len());
    debug!("Content-Type: {}", content_type);
    debug!("Boundary: {}", boundary);
    debug!("Token: {}...", &token[..std::cmp::min(8, token.len())]);
    debug!("Accepted parts: {}", accepted_parts.len());

    // TODO: Process AI events and upload to S3
    // For now, return the accepted parts information
    let response = AIEndpointResponse { accepted_parts };

    Ok(Json(response))
}

pub async fn options() -> Result<CaptureResponse, CaptureError> {
    Ok(CaptureResponse {
        status: CaptureResponseCode::Ok,
        quota_limited: None,
    })
}

/// Parse multipart data and validate structure
async fn parse_multipart_data(body: &[u8], boundary: &str) -> Result<Vec<PartInfo>, CaptureError> {
    // Create a stream from the body data - need to own the data
    let body_owned = body.to_vec();
    let body_stream = stream::once(async move { Ok::<Vec<u8>, std::io::Error>(body_owned) });

    // Create multipart parser
    let mut multipart = Multipart::new(body_stream, boundary);

    let mut part_count = 0;
    let mut has_event_part = false;
    let mut first_part_processed = false;
    let mut accepted_parts = Vec::new();

    // Parse each part
    while let Some(field) = multipart.next_field().await.map_err(|e| {
        warn!("Multipart parsing error: {}", e);
        CaptureError::RequestDecodingError(format!("Multipart parsing failed: {}", e))
    })? {
        part_count += 1;

        // Extract all field information before consuming the field
        let field_name = field.name().unwrap_or("unknown").to_string();
        let content_type = field.content_type().map(|ct| ct.to_string());
        let content_encoding = field.headers()
            .get("content-encoding")
            .and_then(|v| v.to_str().ok())
            .map(|s| s.to_string());

        debug!("Processing multipart field: {} (part #{})", field_name, part_count);

        // Check if this is the first part
        if !first_part_processed {
            first_part_processed = true;

            // Validate that the first part is the event part
            if field_name != "event" {
                return Err(CaptureError::RequestDecodingError(
                    format!("First part must be 'event', got '{}'", field_name),
                ));
            }

            debug!("First part is 'event' as expected");
        }

        // Read the field data to get the length (this consumes the field)
        let field_data = field.bytes().await.map_err(|e| {
            warn!("Failed to read field data for '{}': {}", field_name, e);
            CaptureError::RequestDecodingError(format!("Failed to read field data: {}", e))
        })?;

        // Create part info
        let part_info = PartInfo {
            name: field_name.clone(),
            length: field_data.len(),
            content_type,
            content_encoding,
        };

        accepted_parts.push(part_info);

        // Check if this is the event JSON part
        if field_name == "event" {
            has_event_part = true;
            debug!("Event part processed successfully");
        } else if field_name.starts_with("event.properties.") {
            // This is a blob part
            debug!("Blob part '{}' processed successfully", field_name);
        } else {
            warn!("Unknown multipart field: {}", field_name);
        }
    }

    // Validate that we have at least the event part
    if !has_event_part {
        return Err(CaptureError::RequestDecodingError(
            "Missing required 'event' part in multipart data".to_string(),
        ));
    }

    debug!("Multipart parsing completed: {} parts processed", part_count);
    Ok(accepted_parts)
}
