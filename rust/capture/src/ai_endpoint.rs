use axum::body::Bytes;
use axum::extract::State;
use axum::http::HeaderMap;
use axum::response::Json;
use axum_client_ip::InsecureClientIp;
use common_types::{CapturedEvent, HasEventName};
use flate2::read::GzDecoder;
use futures::stream;
use metrics::{counter, histogram};
use multer::{parse_boundary, Multipart};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashSet;
use std::io::Read;
use time::format_description::well_known::Iso8601;
use time::OffsetDateTime;
use tracing::{debug, warn};
use uuid::Uuid;

// Blob metrics
const AI_BLOB_COUNT_PER_EVENT: &str = "capture_ai_blob_count_per_event";
const AI_BLOB_SIZE_BYTES: &str = "capture_ai_blob_size_bytes";
const AI_BLOB_TOTAL_BYTES_PER_EVENT: &str = "capture_ai_blob_total_bytes_per_event";
const AI_BLOB_EVENTS_TOTAL: &str = "capture_ai_blob_events_total";

use crate::api::{CaptureError, CaptureResponse, CaptureResponseCode};
use crate::event_restrictions::{
    AppliedRestrictions, EventContext as RestrictionEventContext, IngestionPipeline,
};
use crate::prometheus::report_dropped_events;
use crate::router::State as AppState;
use crate::timestamp;
use crate::token::validate_token;
use crate::v0_request::{DataType, ProcessedEvent, ProcessedEventMetadata};

#[derive(Debug, Clone, Serialize, Deserialize)]
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

/// A blob part from the multipart request, including headers for S3 storage
#[derive(Debug)]
struct BlobPart {
    name: String,
    content_type: Option<String>,
    content_encoding: Option<String>,
    data: Bytes,
}

/// Insert S3 URLs from uploaded blobs into event properties.
fn insert_blob_urls_into_properties(
    uploaded: &crate::ai_s3::UploadedBlobs,
    properties: &mut serde_json::Map<String, Value>,
) {
    for part in &uploaded.parts {
        let url = format!(
            "{}?range={}-{}",
            uploaded.base_url, part.range_start, part.range_end
        );
        properties.insert(part.property_name.clone(), Value::String(url));
    }
}

/// Metadata extracted from the event part for early checks (token dropper, quota)
#[derive(Debug)]
struct EventMetadata {
    event_name: String,
    distinct_id: String,
    event_json: Value,
    event_part_info: PartInfo,
}

impl EventMetadata {
    fn event_uuid(&self) -> Option<String> {
        self.event_json
            .as_object()
            .and_then(|obj| obj.get("uuid"))
            .and_then(|v| v.as_str())
            .map(String::from)
    }
}

impl HasEventName for EventMetadata {
    fn event_name(&self) -> &str {
        &self.event_name
    }
}

/// Raw multipart parts retrieved from the request
#[derive(Debug)]
struct RetrievedMultipartParts {
    event_json: Value,
    properties_json: Value,
    blob_parts: Vec<BlobPart>,
    accepted_parts: Vec<PartInfo>,
}

/// Result of parsing multipart AI event data
#[derive(Debug)]
struct ParsedMultipartData {
    accepted_parts: Vec<PartInfo>,
    event: Value,
    event_name: String,
    distinct_id: String,
    event_uuid: Uuid,
    timestamp: Option<String>,
    sent_at: Option<OffsetDateTime>,
    blob_parts: Vec<BlobPart>,
}

pub async fn ai_handler(
    State(state): State<AppState>,
    ip: Option<InsecureClientIp>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<AIEndpointResponse>, CaptureError> {
    debug!("Received request to /i/v0/ai endpoint");

    // Check for empty body
    if body.is_empty() {
        warn!("AI endpoint received empty body");
        return Err(CaptureError::EmptyPayload);
    }

    // Note: Request body size limit is enforced by Axum's DefaultBodyLimit layer
    // (110% of ai_max_sum_of_parts_bytes to account for multipart overhead)

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
        warn!(
            "AI endpoint received non-multipart content type: {}",
            content_type
        );
        return Err(CaptureError::RequestDecodingError(
            "Content-Type must be multipart/form-data".to_string(),
        ));
    }

    // Extract boundary from Content-Type header using multer's built-in parser
    let boundary = parse_boundary(content_type).map_err(|e| {
        warn!("Failed to parse boundary from Content-Type: {}", e);
        CaptureError::RequestDecodingError(format!("Invalid boundary in Content-Type: {e}"))
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

    // Capture body size for logging (before we move the Bytes)
    let body_size = decompressed_body.len();

    // Create multipart parser once - reused for all parsing steps
    let body_stream = stream::once(std::future::ready(Ok::<Bytes, std::io::Error>(
        decompressed_body,
    )));
    let mut multipart = Multipart::new(body_stream, &boundary);

    // Step 1: Retrieve event metadata (parses only the first 'event' part)
    let event_metadata = retrieve_event_metadata(&mut multipart).await?;

    // Step 2: Check event restrictions early - before parsing remaining parts
    let applied_restrictions = if let Some(ref service) = state.event_restriction_service {
        let event_ctx = RestrictionEventContext {
            distinct_id: Some(event_metadata.distinct_id.clone()),
            session_id: None,
            event_name: Some(event_metadata.event_name.clone()),
            event_uuid: event_metadata.event_uuid(),
        };

        let restrictions = service.get_restrictions(token, &event_ctx).await;
        let applied = AppliedRestrictions::from_restrictions(&restrictions, IngestionPipeline::Ai);

        if applied.should_drop {
            report_dropped_events("event_restriction_drop", 1);
            return Ok(Json(AIEndpointResponse {
                accepted_parts: vec![],
            }));
        }

        applied
    } else {
        AppliedRestrictions::default()
    };

    // Step 3: Check token dropper - before parsing remaining parts
    // Token dropper silently drops events (returns 200) to avoid alerting clients
    if state
        .token_dropper
        .should_drop(token, &event_metadata.distinct_id)
    {
        report_dropped_events("token_dropper", 1);
        // Return success response with empty accepted_parts to avoid alerting clients
        return Ok(Json(AIEndpointResponse {
            accepted_parts: vec![],
        }));
    }

    // Step 4: Check quota limiter - drop if over quota
    // We pass a single-element vec and check if it's filtered out
    let filtered = state
        .quota_limiter
        .check_and_filter(token, vec![event_metadata])
        .await?;

    // If the event was filtered out by quota limiter, return billing limit error
    let event_metadata = filtered
        .into_iter()
        .next()
        .ok_or(CaptureError::BillingLimit)?;

    // Step 5: Retrieve and validate remaining multipart parts (continues parsing from multipart)
    let parts = retrieve_multipart_parts(
        &mut multipart,
        state.ai_max_sum_of_parts_bytes,
        event_metadata,
    )
    .await?;

    // Step 6: Parse the parts
    let mut parsed = parse_multipart_data(parts)?;

    // Step 7: Record blob metrics and upload to S3
    let blob_count = parsed.blob_parts.len();
    if blob_count > 0 {
        // Record blob metrics
        histogram!(AI_BLOB_COUNT_PER_EVENT).record(blob_count as f64);

        let mut total_blob_bytes: usize = 0;
        for blob in &parsed.blob_parts {
            let blob_size = blob.data.len();
            total_blob_bytes += blob_size;
            histogram!(AI_BLOB_SIZE_BYTES).record(blob_size as f64);

            // Track content type distribution (normalize to known types)
            let content_type = match blob.content_type.as_deref() {
                Some("application/json") => "application/json",
                Some("application/octet-stream") => "application/octet-stream",
                Some(ct) if ct.starts_with("text/plain") => "text/plain",
                Some(_) => "other",
                None => "unknown",
            };
            counter!(AI_BLOB_EVENTS_TOTAL, "has_blobs" => "true", "content_type" => content_type)
                .increment(1);
        }
        histogram!(AI_BLOB_TOTAL_BYTES_PER_EVENT).record(total_blob_bytes as f64);
    } else {
        counter!(AI_BLOB_EVENTS_TOTAL, "has_blobs" => "false", "content_type" => "none")
            .increment(1);
    }

    // Upload blobs to S3 and insert URLs into event properties
    if !parsed.blob_parts.is_empty() {
        let blob_storage = state.ai_blob_storage.as_ref().ok_or_else(|| {
            warn!("AI endpoint received blobs but S3 is not configured");
            CaptureError::ServiceUnavailable("blob storage not configured".to_string())
        })?;

        // Convert blob_parts to format expected by AiBlobStorage
        let blobs: Vec<crate::ai_s3::BlobData> = parsed
            .blob_parts
            .iter()
            .filter_map(|bp| {
                bp.name
                    .strip_prefix("event.properties.")
                    .map(|prop_name| crate::ai_s3::BlobData {
                        property_name: prop_name.to_string(),
                        content_type: bp.content_type.clone(),
                        content_encoding: bp.content_encoding.clone(),
                        data: bp.data.clone(),
                    })
            })
            .collect();

        // Upload blobs and get URLs
        // TODO: Replace token with team_id once secret key signing is implemented
        // and we can resolve tokens to team IDs in capture
        let uploaded = blob_storage
            .upload_blobs(token, &parsed.event_uuid.to_string(), blobs)
            .await
            .map_err(|e| {
                warn!("Failed to upload blobs to S3: {:?}", e);
                CaptureError::NonRetryableSinkError
            })?;

        // Insert S3 URLs into event properties
        if let Some(properties) = parsed
            .event
            .as_object_mut()
            .and_then(|obj| obj.get_mut("properties"))
            .and_then(|p| p.as_object_mut())
        {
            insert_blob_urls_into_properties(&uploaded, properties);
        }
    }

    // Step 8: Build Kafka event
    // Extract IP address, defaulting to 127.0.0.1 if not available (e.g., in tests)
    let client_ip = ip
        .map(|InsecureClientIp(addr)| addr.to_string())
        .unwrap_or_else(|| "127.0.0.1".to_string());
    let (accepted_parts, processed_event) = build_kafka_event(
        parsed,
        token,
        &client_ip,
        &state,
        applied_restrictions.force_overflow,
        applied_restrictions.skip_person_processing,
        applied_restrictions.redirect_to_dlq,
    )?;

    // Step 9: Send event to Kafka
    state.sink.send(processed_event).await.map_err(|e| {
        warn!("Failed to send AI event to Kafka: {:?}", e);
        e
    })?;

    // Log request details for debugging
    debug!("AI endpoint request validated and sent to Kafka successfully");
    debug!("Body size: {} bytes", body_size);
    debug!("Content-Type: {}", content_type);
    debug!("Boundary: {}", boundary);
    debug!("Token: {}...", &token[..std::cmp::min(8, token.len())]);
    debug!("Accepted parts: {}", accepted_parts.len());

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
        CaptureError::RequestDecodingError(format!("Failed to decompress gzip body: {e}"))
    })?;

    debug!(
        "Decompressed {} bytes to {} bytes",
        compressed.len(),
        decompressed.len()
    );
    Ok(Bytes::from(decompressed))
}

/// Retrieve event metadata from the first multipart part for early checks.
/// This parses only the 'event' part to extract event_name and distinct_id
/// before processing the rest of the multipart body.
/// The multipart parser is passed in and will be reused for remaining parts.
async fn retrieve_event_metadata(
    multipart: &mut Multipart<'_>,
) -> Result<EventMetadata, CaptureError> {
    // Get the first field - must be 'event'
    let field = multipart
        .next_field()
        .await
        .map_err(|e| {
            warn!("Multipart parsing error: {}", e);
            CaptureError::RequestDecodingError(format!("Multipart parsing failed: {e}"))
        })?
        .ok_or_else(|| {
            CaptureError::RequestParsingError(
                "Missing required 'event' part in multipart data".to_string(),
            )
        })?;

    let field_name = field.name().unwrap_or("unknown").to_string();
    let content_type = field.content_type().map(|ct| ct.to_string());
    let content_encoding = field
        .headers()
        .get("content-encoding")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.to_string());

    // Validate that the first part is the event part
    if field_name != "event" {
        return Err(CaptureError::RequestParsingError(format!(
            "First part must be 'event', got '{field_name}'"
        )));
    }

    // Read the field data
    let field_data = field.bytes().await.map_err(|e| {
        warn!("Failed to read event field data: {}", e);
        CaptureError::RequestDecodingError(format!("Failed to read field data: {e}"))
    })?;

    // Process the event part
    let (event_json, event_part_info) =
        process_event_part(field_data, content_type, content_encoding)?;

    // Extract event_name and distinct_id
    let event_obj = event_json.as_object().ok_or_else(|| {
        CaptureError::RequestParsingError("Event must be a JSON object".to_string())
    })?;

    let event_name = event_obj
        .get("event")
        .and_then(|v| v.as_str())
        .ok_or_else(|| {
            CaptureError::RequestParsingError("Event missing 'event' field".to_string())
        })?
        .to_string();

    let distinct_id = event_obj
        .get("distinct_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| {
            CaptureError::RequestParsingError("Event missing 'distinct_id' field".to_string())
        })?
        .to_string();

    Ok(EventMetadata {
        event_name,
        distinct_id,
        event_json,
        event_part_info,
    })
}

/// Validate blob part content type
fn is_valid_blob_content_type(content_type: &str) -> bool {
    // Supported content types for blob parts
    content_type == "application/octet-stream"
        || content_type == "application/json"
        || content_type == "text/plain"
        || content_type.starts_with("text/plain;") // Allow text/plain with charset
}

/// Build a Kafka event from parsed multipart data
fn build_kafka_event(
    parsed: ParsedMultipartData,
    token: &str,
    client_ip: &str,
    state: &AppState,
    force_overflow: bool,
    skip_person_processing: bool,
    redirect_to_dlq: bool,
) -> Result<(Vec<PartInfo>, ProcessedEvent), CaptureError> {
    // Get current time
    let now = state.timesource.current_time();

    // Convert sent_at to chrono DateTime for timestamp computation
    // If conversion fails, treat it as if sent_at wasn't provided (rather than using epoch)
    let sent_at_utc = parsed
        .sent_at
        .and_then(|sa| chrono::DateTime::from_timestamp(sa.unix_timestamp(), sa.nanosecond()));

    // Extract $ignore_sent_at from event properties
    let ignore_sent_at = parsed
        .event
        .as_object()
        .and_then(|obj| obj.get("properties"))
        .and_then(|props| props.as_object())
        .and_then(|props| props.get("$ignore_sent_at"))
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    // Compute timestamp
    let computed_timestamp = timestamp::parse_event_timestamp(
        parsed.timestamp.as_deref(),
        None, // offset
        sent_at_utc,
        ignore_sent_at,
        now,
    );

    // Serialize the event to JSON (this is what goes in the "data" field)
    let data = serde_json::to_string(&parsed.event).map_err(|e| {
        warn!("Failed to serialize AI event: {}", e);
        CaptureError::NonRetryableSinkError
    })?;

    // Redact the IP address of internally-generated events when tagged as such
    let resolved_ip = if parsed
        .event
        .as_object()
        .and_then(|obj| obj.get("properties"))
        .and_then(|props| props.as_object())
        .map(|props| props.contains_key("capture_internal"))
        .unwrap_or(false)
    {
        "127.0.0.1".to_string()
    } else {
        client_ip.to_string()
    };

    // Create CapturedEvent
    let captured_event = CapturedEvent {
        uuid: parsed.event_uuid,
        distinct_id: parsed.distinct_id.clone(),
        session_id: None,
        ip: resolved_ip,
        data,
        now: now.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true),
        sent_at: parsed.sent_at,
        token: token.to_string(),
        event: parsed.event_name.clone(),
        timestamp: computed_timestamp,
        is_cookieless_mode: false,
        historical_migration: false,
    };

    // Create metadata
    let metadata = ProcessedEventMetadata {
        data_type: DataType::AnalyticsMain,
        session_id: None,
        computed_timestamp: Some(computed_timestamp),
        event_name: parsed.event_name,
        force_overflow,
        skip_person_processing,
        redirect_to_dlq,
    };

    // Create ProcessedEvent
    let processed_event = ProcessedEvent {
        event: captured_event,
        metadata,
    };

    Ok((parsed.accepted_parts, processed_event))
}

/// Process the event metadata part
fn process_event_part(
    field_data: Bytes,
    content_type: Option<String>,
    content_encoding: Option<String>,
) -> Result<(Value, PartInfo), CaptureError> {
    const MAX_EVENT_SIZE: usize = 32 * 1024; // 32KB

    let event_size = field_data.len();

    // Check event size limit
    if event_size > MAX_EVENT_SIZE {
        return Err(CaptureError::EventTooBig(format!(
            "Event part size ({event_size} bytes) exceeds maximum allowed size ({MAX_EVENT_SIZE} bytes)"
        )));
    }

    // Parse the event JSON
    let event_json_str = std::str::from_utf8(&field_data).map_err(|e| {
        warn!("Event part is not valid UTF-8: {}", e);
        CaptureError::RequestParsingError("Event part must be valid UTF-8".to_string())
    })?;

    let event_json = serde_json::from_str(event_json_str).map_err(|e| {
        warn!("Event part is not valid JSON: {}", e);
        CaptureError::RequestParsingError("Event part must be valid JSON".to_string())
    })?;

    let part_info = PartInfo {
        name: "event".to_string(),
        length: field_data.len(),
        content_type,
        content_encoding,
    };

    debug!("Event part parsed successfully");
    Ok((event_json, part_info))
}

/// Process the event properties part
fn process_properties_part(
    field_data: Bytes,
    content_type: Option<String>,
    content_encoding: Option<String>,
) -> Result<(Value, PartInfo), CaptureError> {
    // Parse the properties JSON
    let properties_json_str = std::str::from_utf8(&field_data).map_err(|e| {
        warn!("Properties part is not valid UTF-8: {}", e);
        CaptureError::RequestParsingError("Properties part must be valid UTF-8".to_string())
    })?;

    let properties_json = serde_json::from_str(properties_json_str).map_err(|e| {
        warn!("Properties part is not valid JSON: {}", e);
        CaptureError::RequestParsingError("Properties part must be valid JSON".to_string())
    })?;

    let part_info = PartInfo {
        name: "event.properties".to_string(),
        length: field_data.len(),
        content_type,
        content_encoding,
    };

    debug!("Properties part parsed successfully");
    Ok((properties_json, part_info))
}

/// Process a blob part
fn process_blob_part(
    field_name: String,
    field_data: Bytes,
    content_type: Option<String>,
    content_encoding: Option<String>,
) -> Result<(BlobPart, PartInfo), CaptureError> {
    // Validate content type for blob parts - it's required
    if let Some(ref ct) = content_type {
        let ct_lower = ct.to_lowercase();
        if !is_valid_blob_content_type(&ct_lower) {
            return Err(CaptureError::RequestParsingError(
                format!("Unsupported content type for blob part '{field_name}': '{ct}'. Supported types: application/octet-stream, application/json, text/plain"),
            ));
        }
    } else {
        return Err(CaptureError::RequestParsingError(format!(
            "Missing required Content-Type header for blob part '{field_name}'"
        )));
    }

    // Get length before moving data
    let field_data_len = field_data.len();

    // Reject empty blobs
    if field_data_len == 0 {
        return Err(CaptureError::RequestParsingError(format!(
            "Blob part '{field_name}' cannot be empty (0 bytes)"
        )));
    }

    // Create part info (clones needed for response)
    let part_info = PartInfo {
        name: field_name.clone(),
        length: field_data_len,
        content_type: content_type.clone(),
        content_encoding: content_encoding.clone(),
    };

    // Create blob part - moves field_name, field_data, includes headers for S3 storage
    let blob_part = BlobPart {
        name: field_name,
        content_type,
        content_encoding,
        data: field_data, // MOVE - no clone of actual blob data!
    };

    debug!("Blob part processed successfully");
    Ok((blob_part, part_info))
}

/// Retrieve and validate multipart parts from the request body.
/// The event metadata (first part) has already been parsed by retrieve_event_metadata.
/// Continues parsing from where retrieve_event_metadata left off.
async fn retrieve_multipart_parts(
    multipart: &mut Multipart<'_>,
    max_sum_of_parts_bytes: usize,
    event_metadata: EventMetadata,
) -> Result<RetrievedMultipartParts, CaptureError> {
    // Size limits
    const MAX_COMBINED_SIZE: usize = 1024 * 1024 - 64 * 1024; // 1MB - 64KB = 960KB

    let mut part_count = 0;
    let mut accepted_parts = Vec::new();
    let mut seen_property_names = HashSet::new();
    let mut blob_parts: Vec<BlobPart> = Vec::new();
    let mut properties_json: Option<Value> = None;
    let event_size: usize = event_metadata.event_part_info.length;
    let mut properties_size: usize = 0;
    let mut sum_of_parts_bytes: usize = event_size;

    // Add the pre-parsed event part info
    accepted_parts.push(event_metadata.event_part_info);

    // Parse each part
    while let Some(field) = multipart.next_field().await.map_err(|e| {
        warn!("Multipart parsing error: {}", e);
        CaptureError::RequestDecodingError(format!("Multipart parsing failed: {e}"))
    })? {
        part_count += 1;

        // Extract all field information before consuming the field
        let field_name = field.name().unwrap_or("unknown").to_string();
        let content_type = field.content_type().map(|ct| ct.to_string());
        let content_encoding = field
            .headers()
            .get("content-encoding")
            .and_then(|v| v.to_str().ok())
            .map(|s| s.to_string());

        debug!(
            "Processing multipart field: {} (part #{})",
            field_name, part_count
        );

        // Event part was already consumed by retrieve_event_metadata - reject duplicates
        if field_name == "event" {
            return Err(CaptureError::RequestParsingError(
                "Duplicate 'event' part found".to_string(),
            ));
        }

        // Read the field data to get the length (this consumes the field)
        let field_data = field.bytes().await.map_err(|e| {
            warn!("Failed to read field data for '{}': {}", field_name, e);
            CaptureError::RequestDecodingError(format!("Failed to read field data: {e}"))
        })?;

        // Track sum of all part sizes
        sum_of_parts_bytes += field_data.len();

        // Process based on field name
        if field_name == "event.properties" {
            properties_size = field_data.len();
            let (properties, part_info) =
                process_properties_part(field_data, content_type, content_encoding)?;
            properties_json = Some(properties);
            accepted_parts.push(part_info);
        } else if let Some(property_name) = field_name.strip_prefix("event.properties.") {
            // Extract the property name after "event.properties."
            // Validate that the property name doesn't contain dots (enforce top-level properties only)
            if property_name.contains('.') {
                return Err(CaptureError::RequestParsingError(format!(
                    "Blob property '{field_name}' contains nested properties (dots). Only top-level properties are allowed."
                )));
            }

            // Check for duplicates before processing
            if seen_property_names.contains(&field_name) {
                return Err(CaptureError::RequestParsingError(format!(
                    "Duplicate blob property: {field_name}"
                )));
            }

            let (blob_part, part_info) = process_blob_part(
                field_name.clone(),
                field_data,
                content_type,
                content_encoding,
            )?;

            seen_property_names.insert(field_name);
            blob_parts.push(blob_part);
            accepted_parts.push(part_info);
        } else {
            warn!("Unknown multipart field: {}", field_name);

            // Reject unknown fields that don't match expected patterns
            return Err(CaptureError::RequestParsingError(format!(
                "Unknown multipart field: '{field_name}'. Expected 'event', 'event.properties', or 'event.properties.<property_name>'"
            )));
        }
    }

    // Check combined size limit
    let combined_size = event_size + properties_size;
    if combined_size > MAX_COMBINED_SIZE {
        return Err(CaptureError::EventTooBig(format!(
            "Combined event and properties size ({combined_size} bytes) exceeds maximum allowed size ({MAX_COMBINED_SIZE} bytes)"
        )));
    }

    // Check sum of all parts limit
    if sum_of_parts_bytes > max_sum_of_parts_bytes {
        return Err(CaptureError::EventTooBig(format!(
            "Sum of all parts ({sum_of_parts_bytes} bytes) exceeds maximum allowed size ({max_sum_of_parts_bytes} bytes)"
        )));
    }

    // Use the event JSON from the pre-parsed metadata
    let event = event_metadata.event_json;

    // Check for conflicting properties sources
    let has_embedded_properties = event
        .as_object()
        .and_then(|obj| obj.get("properties"))
        .is_some();

    if has_embedded_properties && properties_json.is_some() {
        return Err(CaptureError::RequestParsingError(
            "Event cannot have both embedded properties and a separate 'event.properties' part"
                .to_string(),
        ));
    }

    // Determine which properties to use:
    // - If there's a separate event.properties part, use it
    // - If there's no separate part, extract embedded properties from the event
    // - If neither exists, use empty object
    let final_properties = if let Some(props) = properties_json {
        props
    } else {
        // No separate part - check for embedded properties
        event
            .as_object()
            .and_then(|obj| obj.get("properties").cloned())
            .unwrap_or(serde_json::json!({}))
    };

    debug!(
        "Multipart parts retrieved: {} parts processed, {} blob parts found",
        part_count,
        blob_parts.len()
    );

    Ok(RetrievedMultipartParts {
        event_json: event,
        properties_json: final_properties,
        blob_parts,
        accepted_parts,
    })
}

/// Parse retrieved multipart parts and validate event structure.
/// Returns parsed data with blob_parts for later S3 upload.
fn parse_multipart_data(
    parts: RetrievedMultipartParts,
) -> Result<ParsedMultipartData, CaptureError> {
    // Merge properties into the event
    let mut event = parts.event_json;
    if let Some(event_obj) = event.as_object_mut() {
        event_obj.insert("properties".to_string(), parts.properties_json);
    } else {
        return Err(CaptureError::RequestParsingError(
            "Event must be a JSON object".to_string(),
        ));
    }

    // Now validate the complete event structure
    validate_event_structure(&event)?;

    // Extract event_name, distinct_id, uuid, and timestamp for later use
    let event_name = event
        .as_object()
        .and_then(|obj| obj.get("event"))
        .and_then(|v| v.as_str())
        .ok_or_else(|| CaptureError::RequestParsingError("Event name is required".to_string()))?
        .to_string();

    let distinct_id = event
        .as_object()
        .and_then(|obj| obj.get("distinct_id"))
        .and_then(|v| v.as_str())
        .ok_or_else(|| CaptureError::RequestParsingError("distinct_id is required".to_string()))?
        .to_string();

    // Extract and validate UUID
    let event_uuid = event
        .as_object()
        .and_then(|obj| obj.get("uuid"))
        .and_then(|v| v.as_str())
        .ok_or_else(|| CaptureError::RequestParsingError("Event UUID is required".to_string()))
        .and_then(|uuid_str| {
            Uuid::parse_str(uuid_str).map_err(|e| {
                warn!("Invalid UUID format: {}", e);
                CaptureError::RequestParsingError(format!("Invalid UUID format: {e}"))
            })
        })?;

    let timestamp = event
        .as_object()
        .and_then(|obj| obj.get("timestamp"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    // Extract and parse sent_at
    let sent_at = event
        .as_object()
        .and_then(|obj| obj.get("sent_at"))
        .and_then(|v| v.as_str())
        .and_then(|sent_at_str| OffsetDateTime::parse(sent_at_str, &Iso8601::DEFAULT).ok());

    debug!(
        "Multipart parsing completed: {} blob parts",
        parts.blob_parts.len()
    );

    Ok(ParsedMultipartData {
        accepted_parts: parts.accepted_parts,
        event,
        event_name,
        distinct_id,
        event_uuid,
        timestamp,
        sent_at,
        blob_parts: parts.blob_parts,
    })
}

/// Validate the structure and content of an AI event
fn validate_event_structure(event: &Value) -> Result<(), CaptureError> {
    // Check if event is an object
    let event_obj = event.as_object().ok_or_else(|| {
        warn!("Event must be a JSON object");
        CaptureError::RequestParsingError("Event must be a JSON object".to_string())
    })?;

    // Validate event name
    let event_name = event_obj
        .get("event")
        .and_then(|v| v.as_str())
        .ok_or_else(|| {
            warn!("Event missing 'event' field");
            CaptureError::RequestParsingError("Event missing 'event' field".to_string())
        })?;

    if event_name.is_empty() {
        return Err(CaptureError::RequestParsingError(
            "Event name cannot be empty".to_string(),
        ));
    }

    // Only accept specific AI event types
    const ALLOWED_AI_EVENTS: [&str; 6] = [
        "$ai_generation",
        "$ai_trace",
        "$ai_span",
        "$ai_embedding",
        "$ai_metric",
        "$ai_feedback",
    ];

    if !ALLOWED_AI_EVENTS.contains(&event_name) {
        return Err(CaptureError::RequestParsingError(format!(
            "Event name must be one of: {}, got '{}'",
            ALLOWED_AI_EVENTS.join(", "),
            event_name
        )));
    }

    // Validate distinct_id
    let distinct_id = event_obj
        .get("distinct_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| {
            warn!("Event missing 'distinct_id' field");
            CaptureError::RequestParsingError("Event missing 'distinct_id' field".to_string())
        })?;

    if distinct_id.is_empty() {
        return Err(CaptureError::RequestParsingError(
            "distinct_id cannot be empty".to_string(),
        ));
    }

    // Validate properties object
    let properties = event_obj
        .get("properties")
        .and_then(|v| v.as_object())
        .ok_or_else(|| {
            warn!("Event missing 'properties' field");
            CaptureError::RequestParsingError("Event missing 'properties' field".to_string())
        })?;

    // Validate required AI properties
    if !properties.contains_key("$ai_model") {
        return Err(CaptureError::RequestParsingError(
            "Event properties must contain '$ai_model'".to_string(),
        ));
    }

    let ai_model = properties
        .get("$ai_model")
        .and_then(|v| v.as_str())
        .ok_or_else(|| {
            warn!("$ai_model must be a string");
            CaptureError::RequestParsingError("$ai_model must be a string".to_string())
        })?;

    if ai_model.is_empty() {
        return Err(CaptureError::RequestParsingError(
            "$ai_model cannot be empty".to_string(),
        ));
    }

    debug!(
        "Event validation passed: event='{}', distinct_id='{}', ai_model='{}'",
        event_name, distinct_id, ai_model
    );

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ai_s3::{BlobPartRange, UploadedBlobs};

    #[test]
    fn test_insert_blob_urls_into_properties() {
        let uploaded = UploadedBlobs {
            base_url: "s3://capture/llma/phc_test_token/abc-def".to_string(),
            boundary: "----posthog-ai-abc-def".to_string(),
            parts: vec![
                BlobPartRange {
                    property_name: "$ai_input".to_string(),
                    range_start: 0,
                    range_end: 99,
                },
                BlobPartRange {
                    property_name: "$ai_output".to_string(),
                    range_start: 100,
                    range_end: 249,
                },
            ],
        };

        let mut properties = serde_json::Map::new();
        insert_blob_urls_into_properties(&uploaded, &mut properties);

        assert_eq!(
            properties.get("$ai_input").unwrap().as_str().unwrap(),
            "s3://capture/llma/phc_test_token/abc-def?range=0-99"
        );
        assert_eq!(
            properties.get("$ai_output").unwrap().as_str().unwrap(),
            "s3://capture/llma/phc_test_token/abc-def?range=100-249"
        );
    }
}
