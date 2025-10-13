use axum::body::Bytes;
use axum::extract::State;
use axum::http::HeaderMap;
use axum::response::Json;
use flate2::read::GzDecoder;
use futures::stream;
use multer::{Multipart, parse_boundary};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashSet;
use std::io::Read;
use tracing::{debug, warn};

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

    // Check for Content-Encoding header and decompress if needed
    let content_encoding = headers
        .get("content-encoding")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    let decompressed_body = if content_encoding.eq_ignore_ascii_case("gzip") {
        debug!("Decompressing gzip-encoded request body");
        decompress_gzip(&body)?
    } else {
        body
    };

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
    let accepted_parts = parse_multipart_data(&decompressed_body, &boundary).await?;

    // Log request details for debugging
    debug!("AI endpoint request validated and parsed successfully");
    debug!("Body size: {} bytes", decompressed_body.len());
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

/// Decompress gzip-encoded body using streaming decompression
fn decompress_gzip(compressed: &Bytes) -> Result<Bytes, CaptureError> {
    let mut decoder = GzDecoder::new(&compressed[..]);
    let mut decompressed = Vec::new();

    decoder.read_to_end(&mut decompressed).map_err(|e| {
        warn!("Failed to decompress gzip body: {}", e);
        CaptureError::RequestDecodingError(format!("Failed to decompress gzip body: {}", e))
    })?;

    debug!("Decompressed {} bytes to {} bytes", compressed.len(), decompressed.len());
    Ok(Bytes::from(decompressed))
}

/// Parse multipart data and validate structure
async fn parse_multipart_data(body: &[u8], boundary: &str) -> Result<Vec<PartInfo>, CaptureError> {
    // Size limits
    const MAX_EVENT_SIZE: usize = 32 * 1024; // 32KB
    const MAX_COMBINED_SIZE: usize = 1024 * 1024 - 64 * 1024; // 1MB - 64KB = 960KB

    // Create a stream from the body data - need to own the data
    let body_owned = body.to_vec();
    let body_stream = stream::once(async move { Ok::<Vec<u8>, std::io::Error>(body_owned) });

    // Create multipart parser
    let mut multipart = Multipart::new(body_stream, boundary);

    let mut part_count = 0;
    let mut has_event_part = false;
    let mut first_part_processed = false;
    let mut accepted_parts = Vec::new();
    let mut seen_property_names = HashSet::new();
    let mut event_json: Option<Value> = None;
    let mut properties_json: Option<Value> = None;
    let mut event_size: usize = 0;
    let mut properties_size: usize = 0;

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
            event_size = field_data.len();

            // Check event size limit
            if event_size > MAX_EVENT_SIZE {
                return Err(CaptureError::RequestDecodingError(
                    format!("Event part size ({} bytes) exceeds maximum allowed size ({} bytes)",
                            event_size, MAX_EVENT_SIZE),
                ));
            }

            // Parse the event JSON (without validating properties yet)
            let event_json_str = std::str::from_utf8(&field_data).map_err(|e| {
                warn!("Event part is not valid UTF-8: {}", e);
                CaptureError::RequestDecodingError("Event part must be valid UTF-8".to_string())
            })?;

            event_json = Some(serde_json::from_str(event_json_str).map_err(|e| {
                warn!("Event part is not valid JSON: {}", e);
                CaptureError::RequestDecodingError("Event part must be valid JSON".to_string())
            })?);

            debug!("Event part parsed successfully");
        } else if field_name == "event.properties" {
            properties_size = field_data.len();

            // Parse the properties JSON
            let properties_json_str = std::str::from_utf8(&field_data).map_err(|e| {
                warn!("Properties part is not valid UTF-8: {}", e);
                CaptureError::RequestDecodingError("Properties part must be valid UTF-8".to_string())
            })?;

            properties_json = Some(serde_json::from_str(properties_json_str).map_err(|e| {
                warn!("Properties part is not valid JSON: {}", e);
                CaptureError::RequestDecodingError("Properties part must be valid JSON".to_string())
            })?);

            debug!("Properties part parsed successfully");
        } else if field_name.starts_with("event.properties.") {
            // This is a blob part - check for duplicates
            if !seen_property_names.insert(field_name.clone()) {
                return Err(CaptureError::RequestDecodingError(
                    format!("Duplicate blob property: {}", field_name),
                ));
            }
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

    // Check combined size limit
    let combined_size = event_size + properties_size;
    if combined_size > MAX_COMBINED_SIZE {
        return Err(CaptureError::RequestDecodingError(
            format!("Combined event and properties size ({} bytes) exceeds maximum allowed size ({} bytes)",
                    combined_size, MAX_COMBINED_SIZE),
        ));
    }

    // Merge properties into the event
    let mut event = event_json.unwrap();

    // Check for conflicting properties sources
    let has_embedded_properties = event.as_object()
        .and_then(|obj| obj.get("properties"))
        .is_some();

    if has_embedded_properties && properties_json.is_some() {
        return Err(CaptureError::RequestDecodingError(
            "Event cannot have both embedded properties and a separate 'event.properties' part".to_string(),
        ));
    }

    // Determine which properties to use:
    // - If there's a separate event.properties part, use it
    // - If there's no separate part, use embedded properties from the event (if any)
    // - If neither exists, use empty object
    let properties = if let Some(props) = properties_json {
        props
    } else {
        // No separate part - check for embedded properties
        if let Some(event_obj) = event.as_object() {
            event_obj.get("properties").cloned().unwrap_or(serde_json::json!({}))
        } else {
            serde_json::json!({})
        }
    };

    // Insert/replace properties in the event object
    if let Some(event_obj) = event.as_object_mut() {
        event_obj.insert("properties".to_string(), properties);
    } else {
        return Err(CaptureError::RequestDecodingError(
            "Event must be a JSON object".to_string(),
        ));
    }

    // Now validate the complete event structure
    validate_event_structure(&event)?;

    debug!("Multipart parsing completed: {} parts processed", part_count);
    Ok(accepted_parts)
}

/// Validate the structure and content of an AI event
fn validate_event_structure(event: &Value) -> Result<(), CaptureError> {
    // Check if event is an object
    let event_obj = event.as_object().ok_or_else(|| {
        warn!("Event must be a JSON object");
        CaptureError::RequestDecodingError("Event must be a JSON object".to_string())
    })?;

    // Validate event name
    let event_name = event_obj.get("event").and_then(|v| v.as_str()).ok_or_else(|| {
        warn!("Event missing 'event' field");
        CaptureError::RequestDecodingError("Event missing 'event' field".to_string())
    })?;

    if event_name.is_empty() {
        return Err(CaptureError::RequestDecodingError(
            "Event name cannot be empty".to_string(),
        ));
    }

    if !event_name.starts_with("$ai_") {
        return Err(CaptureError::RequestDecodingError(
            format!("Event name must start with '$ai_', got '{}'", event_name),
        ));
    }

    // Validate distinct_id
    let distinct_id = event_obj.get("distinct_id").and_then(|v| v.as_str()).ok_or_else(|| {
        warn!("Event missing 'distinct_id' field");
        CaptureError::RequestDecodingError("Event missing 'distinct_id' field".to_string())
    })?;

    if distinct_id.is_empty() {
        return Err(CaptureError::RequestDecodingError(
            "distinct_id cannot be empty".to_string(),
        ));
    }

    // Validate properties object
    let properties = event_obj.get("properties").and_then(|v| v.as_object()).ok_or_else(|| {
        warn!("Event missing 'properties' field");
        CaptureError::RequestDecodingError("Event missing 'properties' field".to_string())
    })?;

    // Validate required AI properties
    if !properties.contains_key("$ai_model") {
        return Err(CaptureError::RequestDecodingError(
            "Event properties must contain '$ai_model'".to_string(),
        ));
    }

    let ai_model = properties.get("$ai_model").and_then(|v| v.as_str()).ok_or_else(|| {
        warn!("$ai_model must be a string");
        CaptureError::RequestDecodingError("$ai_model must be a string".to_string())
    })?;

    if ai_model.is_empty() {
        return Err(CaptureError::RequestDecodingError(
            "$ai_model cannot be empty".to_string(),
        ));
    }

    debug!("Event validation passed: event='{}', distinct_id='{}', ai_model='{}'",
           event_name, distinct_id, ai_model);

    Ok(())
}
